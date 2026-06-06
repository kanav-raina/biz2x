"""Scenario simulation: "what if the next EMI is missed?"

A what-if tool for analysts. It takes a borrower's real history, appends a single
*hypothetical* next-cycle record describing a missed EMI, and re-runs the same
scoring engine. Comparing the baseline assessment to the simulated one shows how
much the borrower's risk would jump — letting collections teams pre-empt the miss
rather than react to it.

Pure and deterministic: the synthetic record is built from documented constants
in ``config.SIMULATION`` and the borrower's own loan terms, never from the LLM and
never with invented numbers.
"""
from __future__ import annotations

from typing import Any

from ..core.config import SIMULATION
from .scoring import _ORDER, score_borrower

_SEVERITY_RANK = {cat: i for i, cat in enumerate(_ORDER)}


def _next_month(month: str) -> str:
    """Return the ``YYYY-MM`` string one month after the given one."""
    year, mon = (int(part) for part in month.split("-"))
    if mon == 12:
        return f"{year + 1}-01"
    return f"{year}-{mon + 1:02d}"


def _hypothetical_missed_payment(borrower: dict, prev_month: str) -> dict:
    """Build the synthetic 'missed EMI' record for the cycle after ``prev_month``."""
    month = _next_month(prev_month)
    due_day = borrower.get("due_day", 1)
    return {
        "borrower_id": borrower["borrower_id"],
        "month": month,
        "due_date": f"{month}-{due_day:02d}",
        "paid_date": None,
        "days_past_due": SIMULATION["missed_emi_dpd"],
        "status": "missed",
        "auto_debit_failed": SIMULATION["missed_emi_auto_debit_failed"],
        "partial": SIMULATION["missed_emi_partial"],
    }


def _summary(facts: dict) -> dict[str, Any]:
    return {
        "risk_score": facts["risk_score"],
        "category": facts["category"],
        "confidence": facts["confidence"],
        "triggered_signals": [s["signal"] for s in facts["triggered_signals"]],
    }


def simulate_missed_emi(
    borrower: dict, payments: list[dict], transactions: list[dict]
) -> dict[str, Any]:
    """Score the borrower as-is and again with a hypothetical missed next EMI.

    Output:
      {
        "borrower_id": str,
        "scenario": "miss_next_emi",
        "assumptions": {...},                 # the synthetic record's key fields
        "baseline": {risk_score, category, confidence, triggered_signals},
        "simulated": {risk_score, category, confidence, triggered_signals},
        "score_change": int,
        "category_change": bool,
        "new_signals": [str, ...],            # signals the miss would newly trigger
        "summary": str,                       # plain-language what-if statement
      }
    """
    baseline_facts = score_borrower(borrower, payments, transactions)

    # Anchor the hypothetical cycle to the latest known payment month.
    last_month = max((p["month"] for p in payments), default=None)
    if last_month is None:
        # No payment history to anchor to — simulation is not meaningful.
        base = _summary(baseline_facts)
        return {
            "borrower_id": borrower["borrower_id"],
            "scenario": "miss_next_emi",
            "assumptions": {},
            "baseline": base,
            "simulated": base,
            "score_change": 0,
            "category_change": False,
            "new_signals": [],
            "summary": "No payment history available to simulate a missed EMI.",
        }

    missed = _hypothetical_missed_payment(borrower, last_month)
    sim_payments = payments + [missed]
    sim_facts = score_borrower(borrower, sim_payments, transactions)

    base = _summary(baseline_facts)
    sim = _summary(sim_facts)
    new_signals = [s for s in sim["triggered_signals"] if s not in base["triggered_signals"]]
    score_change = sim["risk_score"] - base["risk_score"]
    category_change = sim["category"] != base["category"]

    return {
        "borrower_id": borrower["borrower_id"],
        "scenario": "miss_next_emi",
        "assumptions": {
            "month": missed["month"],
            "days_past_due": missed["days_past_due"],
            "auto_debit_failed": missed["auto_debit_failed"],
            "partial": missed["partial"],
        },
        "baseline": base,
        "simulated": sim,
        "score_change": score_change,
        "category_change": category_change,
        "new_signals": new_signals,
        "summary": _summary_text(borrower, base, sim, score_change, missed["month"]),
    }


def _summary_text(
    borrower: dict, base: dict, sim: dict, score_change: int, month: str
) -> str:
    """Deterministic, grounded one-liner describing the what-if outcome."""
    if score_change <= 0 and base["category"] == sim["category"]:
        return (
            f"{borrower['name']} is already {base['category']}; a missed EMI in {month} "
            "would not change the risk category."
        )
    move = "rise" if score_change > 0 else "change"
    cat_clause = (
        f", moving from {base['category']} to {sim['category']}"
        if base["category"] != sim["category"]
        else f", staying {sim['category']}"
    )
    return (
        f"If {borrower['name']} misses the {month} EMI, the risk score would {move} "
        f"from {base['risk_score']} to {sim['risk_score']} (+{score_change}){cat_clause}."
    )
