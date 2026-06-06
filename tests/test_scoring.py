"""Unit tests for the scoring engine, driven by the mock dataset.

Each persona is engineered to land in a specific risk tier; these tests pin that
behaviour and the edge-case handling (insufficient history, missing transactions).
"""
import pytest

from app.repositories.borrower_repository import BorrowerRepository

EXPECTED_CATEGORY = {
    "B001": "Low",
    "B002": "Watchlist",
    "B003": "High Risk",
    "B004": "High Risk",
    "B005": "Critical",
    "B006": "High Risk",
    "B007": "Watchlist",   # capped due to insufficient history
    "B008": "High Risk",   # payment signals only
    "B009": "Low",         # recovered — trend direction matters
}


@pytest.fixture(scope="module")
def repo():
    r = BorrowerRepository()
    r.load()
    return r


@pytest.mark.parametrize("bid,expected", EXPECTED_CATEGORY.items())
def test_category_per_persona(repo, bid, expected):
    facts = repo.get_facts(bid)
    assert facts is not None, f"{bid} missing"
    assert facts["category"] == expected, (
        f"{bid} scored {facts['risk_score']} -> {facts['category']}, expected {expected}; "
        f"signals={[s['signal'] for s in facts['triggered_signals']]}"
    )


def test_healthy_borrower_has_no_signals(repo):
    facts = repo.get_facts("B001")
    assert facts["risk_score"] == 0
    assert facts["triggered_signals"] == []
    assert facts["confidence"] == "high"


def test_insufficient_history_is_capped_and_flagged(repo):
    facts = repo.get_facts("B007")
    assert "insufficient_history" in facts["data_caveats"]
    assert facts["confidence"] == "low"
    # Even if raw signals were severe, category cannot exceed the cap.
    assert facts["category"] in {"Low", "Watchlist"}


def test_missing_transactions_degrades_confidence(repo):
    facts = repo.get_facts("B008")
    assert "degraded_confidence" in facts["data_caveats"]
    assert facts["confidence"] == "low"
    # No cash-flow signals should appear when transactions are absent.
    cashflow = {"high_utilization", "rising_utilization", "falling_income", "declining_balance"}
    fired = {s["signal"] for s in facts["triggered_signals"]}
    assert fired & cashflow == set()


def test_recovered_borrower_not_flagged_despite_past_lateness(repo):
    # B009 was 10 days late months ago but is now current — trend logic should
    # NOT flag rising_dpd or recent_late.
    facts = repo.get_facts("B009")
    fired = {s["signal"] for s in facts["triggered_signals"]}
    assert "rising_dpd" not in fired
    assert "recent_late" not in fired
    assert facts["category"] == "Low"


def test_critical_borrower_fires_multiple_signals(repo):
    facts = repo.get_facts("B005")
    fired = {s["signal"] for s in facts["triggered_signals"]}
    assert {"rising_dpd", "recent_late", "failed_auto_debit"} <= fired
    assert facts["risk_score"] >= 71


def test_every_signal_detail_is_grounded(repo):
    # Each fired signal must carry a non-empty human-readable detail string —
    # this is the only text the LLM is allowed to ground on.
    for facts in repo.list_facts():
        for s in facts["triggered_signals"]:
            assert s["detail"].strip(), f"{facts['borrower_id']} {s['signal']} has empty detail"
            assert s["weight"] > 0
