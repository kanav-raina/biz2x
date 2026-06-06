"""In-memory borrower repository. Loads the mock JSON once at startup, computes
each borrower's risk assessment, and exposes simple lookup/query methods.

In production this layer would sit in front of a database with scheduled batch
scoring; the rest of the app depends only on these methods, so swapping the
backing store would not touch scoring, API, or LLM code.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import AT_RISK_CATEGORIES
from ..domain.scoring import score_borrower
from ..domain.simulation import simulate_missed_emi
from ..domain.trend import compute_trend

# app/repositories/borrower_repository.py -> project root is three parents up.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Severity ordering (worst first) for list sorting and summary scaffolding.
_SEVERITY_ORDER = ["Critical", "High Risk", "Watchlist", "Low"]


class BorrowerRepository:
    def __init__(self, data_dir: Path = DATA_DIR):
        self._data_dir = data_dir
        self._facts: dict[str, dict] = {}      # borrower_id -> risk facts
        self._borrowers: dict[str, dict] = {}  # borrower_id -> raw record
        self._payments: dict[str, list] = {}   # borrower_id -> payment rows
        self._transactions: dict[str, list] = {}  # borrower_id -> txn rows

    def load(self) -> None:
        borrowers = _read_json(self._data_dir / "borrowers.json")
        payments = _read_json(self._data_dir / "payments.json")
        transactions = _read_json(self._data_dir / "transactions.json")

        pay_by_id = _group_by(payments, "borrower_id")
        txn_by_id = _group_by(transactions, "borrower_id")

        for b in borrowers:
            bid = b["borrower_id"]
            self._borrowers[bid] = b
            # Retain the raw history so trend replay and what-if simulation can
            # re-score on demand without re-reading the data files.
            self._payments[bid] = pay_by_id.get(bid, [])
            self._transactions[bid] = txn_by_id.get(bid, [])
            self._facts[bid] = score_borrower(
                b, self._payments[bid], self._transactions[bid]
            )

    # --- queries -----------------------------------------------------
    def exists(self, borrower_id: str) -> bool:
        return borrower_id in self._facts

    def get_facts(self, borrower_id: str) -> dict[str, Any] | None:
        return self._facts.get(borrower_id)

    def list_facts(
        self, severities: set[str] | None = None, analyst: str | None = None
    ) -> list[dict]:
        items = list(self._facts.values())
        if analyst is not None:
            items = [f for f in items if f["assigned_analyst"] == analyst]
        if severities:
            items = [f for f in items if f["category"] in severities]
        # sort by severity (worst first) then score desc
        order = {cat: i for i, cat in enumerate(_SEVERITY_ORDER)}
        items.sort(key=lambda f: (order.get(f["category"], 9), -f["risk_score"]))
        return items

    def risk_trend(self, borrower_id: str) -> dict[str, Any] | None:
        """Month-by-month risk history for one borrower (None if unknown)."""
        borrower = self._borrowers.get(borrower_id)
        if borrower is None:
            return None
        return compute_trend(
            borrower, self._payments[borrower_id], self._transactions[borrower_id]
        )

    def simulate_missed_emi(self, borrower_id: str) -> dict[str, Any] | None:
        """What-if: re-score assuming the next EMI is missed (None if unknown)."""
        borrower = self._borrowers.get(borrower_id)
        if borrower is None:
            return None
        return simulate_missed_emi(
            borrower, self._payments[borrower_id], self._transactions[borrower_id]
        )

    def portfolio_summary(self) -> dict[str, Any]:
        """Aggregate, PII-free portfolio health for managers.

        Counts per tier plus the metrics a portfolio manager actually steers by:
        exposure concentrated in the at-risk book, average risk, data-quality
        coverage, the most prevalent early-warning signals, and per-analyst book
        health (so caseload can be rebalanced).
        """
        facts = list(self._facts.values())
        total = len(facts)

        by_cat: dict[str, int] = {cat: 0 for cat in _SEVERITY_ORDER}
        signal_counts: dict[str, int] = {}
        total_outstanding = 0.0
        at_risk_outstanding = 0.0
        low_confidence = 0
        score_sum = 0

        for f in facts:
            by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
            score_sum += f["risk_score"]
            if f["confidence"] == "low":
                low_confidence += 1
            outstanding = self._borrowers[f["borrower_id"]].get("outstanding_balance", 0)
            total_outstanding += outstanding
            if f["category"] in AT_RISK_CATEGORIES:
                at_risk_outstanding += outstanding
            for s in f["triggered_signals"]:
                signal_counts[s["signal"]] = signal_counts.get(s["signal"], 0) + 1

        at_risk_count = sum(by_cat.get(c, 0) for c in AT_RISK_CATEGORIES)
        by_cat_pct = {
            cat: round(100 * cnt / total, 1) if total else 0.0
            for cat, cnt in by_cat.items()
        }
        # Most prevalent signals across the book, worst first — where to focus.
        top_signals = [
            {"signal": sig, "count": cnt}
            for sig, cnt in sorted(signal_counts.items(), key=lambda kv: -kv[1])
        ]

        return {
            "total_borrowers": total,
            "by_category": by_cat,
            "by_category_pct": by_cat_pct,
            "at_risk_count": at_risk_count,
            "average_risk_score": round(score_sum / total, 1) if total else 0.0,
            "total_outstanding": total_outstanding,
            "at_risk_outstanding": at_risk_outstanding,
            "low_confidence_count": low_confidence,
            "top_signals": top_signals,
            "by_analyst": self._analyst_breakdown(),
        }

    def _analyst_breakdown(self) -> list[dict[str, Any]]:
        """Per-analyst book health (total + at-risk count), worst-loaded first."""
        books: dict[str, dict[str, int]] = {}
        for f in self._facts.values():
            analyst = f["assigned_analyst"]
            book = books.setdefault(analyst, {"total": 0, "at_risk": 0})
            book["total"] += 1
            if f["category"] in AT_RISK_CATEGORIES:
                book["at_risk"] += 1
        return [
            {"analyst": analyst, "total": b["total"], "at_risk": b["at_risk"]}
            for analyst, b in sorted(books.items(), key=lambda kv: (-kv[1]["at_risk"], kv[0]))
        ]


def _read_json(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _group_by(records: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(r[key], []).append(r)
    return out


# Module-level singleton used by the app.
repo = BorrowerRepository()
