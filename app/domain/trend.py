"""Risk-trend engine: how a borrower's risk evolved over time.

Pure and deterministic, like the rest of ``domain``. The idea is simple and
auditable: replay history month by month, and at each month re-run the *same*
scoring engine using only the data that was available up to that point. The
result is a time series of (month, score, category) that visualises whether a
borrower is deteriorating, stable, or recovering — exactly the early-warning
signal credit teams want to see before an EMI is actually missed.

No I/O, no LLM — just the existing scoring core applied to growing windows.
"""
from __future__ import annotations

from typing import Any

from ..core.config import THRESHOLDS
from .scoring import _ORDER, score_borrower

# Worst -> best, so a smaller index means a more severe category. Reused to turn
# the first/last categories into a single human-readable trend direction.
_SEVERITY_RANK = {cat: i for i, cat in enumerate(_ORDER)}


def _months(records: list[dict]) -> list[str]:
    return sorted({r["month"] for r in records})


def compute_trend(
    borrower: dict, payments: list[dict], transactions: list[dict]
) -> dict[str, Any]:
    """Return the borrower's risk score/category for each month of history.

    For every payment month ``m`` we score the borrower using only the records
    with ``month <= m`` — so each point reflects what the system would have
    known at that time. The newest point equals the borrower's current score.

    Output:
      {
        "borrower_id": str,
        "points": [ {month, risk_score, category, confidence}, ... ],
        "direction": "improving" | "worsening" | "stable",
        "score_change": int,        # last score - first score
      }
    """
    months = _months(payments)
    points: list[dict] = []

    for m in months:
        pay_sub = [p for p in payments if p["month"] <= m]
        txn_sub = [t for t in transactions if t["month"] <= m]
        facts = score_borrower(borrower, pay_sub, txn_sub)
        points.append(
            {
                "month": m,
                "risk_score": facts["risk_score"],
                "category": facts["category"],
                "confidence": facts["confidence"],
            }
        )

    direction, score_change = _direction(points)
    return {
        "borrower_id": borrower["borrower_id"],
        "points": points,
        "direction": direction,
        "score_change": score_change,
    }


def _direction(points: list[dict]) -> tuple[str, int]:
    """Summarise the series as a single direction + net score change.

    Uses both the numeric score and the category so a borrower who crossed a
    band boundary is reported consistently with what the analyst sees.
    """
    if len(points) < 2:
        return "stable", 0

    first, last = points[0], points[-1]
    score_change = last["risk_score"] - first["risk_score"]
    band_shift = _SEVERITY_RANK[first["category"]] - _SEVERITY_RANK[last["category"]]

    # band_shift > 0 means the latest category is more severe (worsening).
    if score_change > THRESHOLDS["dpd_trend_delta_days"] or band_shift > 0:
        return "worsening", score_change
    if score_change < -THRESHOLDS["dpd_trend_delta_days"] or band_shift < 0:
        return "improving", score_change
    return "stable", score_change
