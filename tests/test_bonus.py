"""Tests for the bonus features: risk-trend visualization, EMI-miss scenario
simulation, and the enriched portfolio summary.

Domain logic is tested directly on the repository (pure, deterministic); the API
layer is tested through the app for RBAC and response shaping.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.borrower_repository import BorrowerRepository

ANALYST1 = {"X-User-Role": "analyst", "X-User-Id": "analyst_1"}
ANALYST2 = {"X-User-Role": "analyst", "X-User-Id": "analyst_2"}
BORROWER_B005 = {"X-User-Role": "borrower", "X-User-Id": "B005"}
MANAGER = {"X-User-Role": "manager", "X-User-Id": "mgr_1"}


@pytest.fixture(scope="module")
def repo():
    r = BorrowerRepository()
    r.load()
    return r


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- Risk trend over time ----------------------------------------------------
def test_trend_has_one_point_per_month(repo):
    trend = repo.risk_trend("B005")
    assert [p["month"] for p in trend["points"]] == [
        "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
    ]


def test_trend_latest_point_matches_current_score(repo):
    trend = repo.risk_trend("B005")
    facts = repo.get_facts("B005")
    assert trend["points"][-1]["risk_score"] == facts["risk_score"]
    assert trend["points"][-1]["category"] == facts["category"]


def test_trend_detects_worsening_borrower(repo):
    # B005 spirals from healthy to Critical.
    trend = repo.risk_trend("B005")
    assert trend["direction"] == "worsening"
    assert trend["score_change"] > 0


def test_trend_detects_recovering_borrower(repo):
    # B009 was late months ago, now current — trend should not be worsening.
    trend = repo.risk_trend("B009")
    assert trend["direction"] in {"improving", "stable"}


def test_trend_endpoint_analyst_full_view(client):
    resp = client.get("/borrowers/B005/trend", headers=ANALYST2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"][0].keys() >= {"month", "risk_score", "category"}
    assert body["direction"] == "worsening"


def test_trend_endpoint_borrower_view_hides_score(client):
    resp = client.get("/borrowers/B005/trend", headers=BORROWER_B005)
    assert resp.status_code == 200
    body = resp.json()
    assert all("risk_score" not in p for p in body["points"])
    assert body["points"][-1]["category"]  # category is still present


def test_trend_rbac_cross_analyst_blocked(client):
    # B005 belongs to analyst_2; analyst_1 must not read its trend.
    assert client.get("/borrowers/B005/trend", headers=ANALYST1).status_code == 403


# --- Scenario simulation: "What if next EMI is missed?" ----------------------
def test_simulation_increases_risk(repo):
    sim = repo.simulate_missed_emi("B002")
    assert sim["scenario"] == "miss_next_emi"
    assert sim["simulated"]["risk_score"] >= sim["baseline"]["risk_score"]
    assert sim["score_change"] >= 0


def test_simulation_can_escalate_category(repo):
    # A Watchlist borrower missing an EMI should cross into a worse tier.
    sim = repo.simulate_missed_emi("B002")
    assert sim["category_change"] is True
    assert "rising_dpd" in sim["new_signals"]


def test_simulation_is_grounded_and_deterministic(repo):
    sim1 = repo.simulate_missed_emi("B002")
    sim2 = repo.simulate_missed_emi("B002")
    assert sim1 == sim2  # pure, no randomness
    assert str(sim1["baseline"]["risk_score"]) in sim1["summary"]


def test_simulation_endpoint_analyst_only(client):
    assert client.post("/borrowers/B005/simulate", headers=ANALYST2).status_code == 200
    # borrowers may not run the analyst what-if tool
    assert client.post("/borrowers/B005/simulate", headers=BORROWER_B005).status_code == 403


def test_simulation_unknown_borrower_404(client):
    assert client.post("/borrowers/B999/simulate", headers=ANALYST1).status_code == 404


# --- Enriched portfolio summary ----------------------------------------------
def test_portfolio_summary_aggregates(repo):
    s = repo.portfolio_summary()
    assert s["total_borrowers"] == 9
    assert sum(s["by_category"].values()) == 9
    # at-risk count equals High Risk + Critical
    assert s["at_risk_count"] == s["by_category"]["High Risk"] + s["by_category"]["Critical"]
    # at-risk exposure cannot exceed total exposure
    assert 0 < s["at_risk_outstanding"] <= s["total_outstanding"]


def test_portfolio_top_signals_sorted_desc(repo):
    counts = [item["count"] for item in repo.portfolio_summary()["top_signals"]]
    assert counts == sorted(counts, reverse=True)


def test_portfolio_analyst_breakdown_complete(repo):
    s = repo.portfolio_summary()
    analysts = {b["analyst"] for b in s["by_analyst"]}
    assert {"analyst_1", "analyst_2"} <= analysts
    assert sum(b["total"] for b in s["by_analyst"]) == s["total_borrowers"]


def test_portfolio_endpoint_manager_only(client):
    resp = client.get("/portfolio/summary", headers=MANAGER)
    assert resp.status_code == 200
    body = resp.json()
    assert "by_category_pct" in body
    assert "top_signals" in body
    assert "by_analyst" in body
    # analysts cannot read the portfolio summary
    assert client.get("/portfolio/summary", headers=ANALYST1).status_code == 403
