"""Scoring engine: turns triggered signals into a risk score, category,
confidence, and recommended action. Pure and deterministic.

This is the auditable heart of the system — every number here is traceable to a
signal defined in config.WEIGHTS, and the category is a documented function of
the score bands.
"""
from __future__ import annotations

from typing import Any

from ..core.config import (
    ACTIONS,
    BANDS,
    BORROWER_ACTIONS,
    INSUFFICIENT_HISTORY_CAP,
)
from .signals import compute_signals

# Ordered worst -> best so we can compare / cap categories.
_ORDER = ["Critical", "High Risk", "Watchlist", "Low"]


def _category_for_score(score: int) -> str:
    for minimum, category in BANDS:  # BANDS is ordered high -> low
        if score >= minimum:
            return category
    return "Low"


def _cap_category(category: str, ceiling: str) -> str:
    """Return the less-severe of category and ceiling."""
    if _ORDER.index(category) < _ORDER.index(ceiling):
        return ceiling
    return category


def score_borrower(
    borrower: dict, payments: list[dict], transactions: list[dict]
) -> dict[str, Any]:
    """Compute the full risk assessment for one borrower.

    Returns a 'facts' dict that is the single source of truth consumed by the
    API response shaping and the LLM grounding layer.
    """
    computed = compute_signals(borrower, payments, transactions)
    signals = computed["signals"]
    caveats = computed["caveats"]

    raw_score = sum(s["weight"] for s in signals)
    category = _category_for_score(raw_score)

    # Edge case: insufficient history cannot produce a high-severity alert.
    if "insufficient_history" in caveats:
        category = _cap_category(category, INSUFFICIENT_HISTORY_CAP)

    confidence = "low" if caveats else "high"

    return {
        "borrower_id": borrower["borrower_id"],
        "name": borrower["name"],
        "risk_score": raw_score,
        "category": category,
        "confidence": confidence,
        "triggered_signals": signals,
        "recommended_action": ACTIONS[category],
        "borrower_action": BORROWER_ACTIONS[category],
        "data_caveats": caveats,
        "assigned_analyst": borrower["assigned_analyst"],
    }
