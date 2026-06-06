"""Signal engine: pure functions that turn raw borrower records into triggered
risk indicators. No scoring, no LLM, no I/O — just deterministic feature logic so
it is trivially unit-testable.

Each fired signal returns a dict: {signal, weight, detail}, where `detail` is a
short human-readable fact. Those detail strings are the ONLY information later
passed to the LLM, which keeps explanations grounded.
"""
from __future__ import annotations

from typing import Any

from ..core.config import THRESHOLDS, WEIGHTS

T = THRESHOLDS


def _sorted(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: r["month"])


def _windows(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split chronologically-sorted records into (recent, prior) windows."""
    n = T["recent_window_months"]
    recent = records[-n:]
    prior = records[-2 * n : -n]
    return recent, prior


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _signal(name: str, detail: str) -> dict[str, Any]:
    return {"signal": name, "weight": WEIGHTS[name], "detail": detail}


def compute_signals(
    borrower: dict, payments: list[dict], transactions: list[dict]
) -> dict[str, Any]:
    """Return triggered signals plus data-availability metadata.

    Output:
      {
        "signals": [ {signal, weight, detail}, ... ],
        "history_months": int,
        "has_transactions": bool,
        "caveats": [str, ...],
      }
    """
    payments = _sorted(payments)
    transactions = _sorted(transactions)
    signals: list[dict] = []
    caveats: list[str] = []

    history_months = len(payments)
    has_transactions = len(transactions) > 0

    # ---------------------------------------------------------------
    # Payment-behaviour signals (available whenever we have payments)
    # ---------------------------------------------------------------
    if payments:
        recent_p, prior_p = _windows(payments)

        # rising_dpd — needs a prior window to compare against
        if prior_p:
            recent_dpd = _avg([p["days_past_due"] for p in recent_p])
            prior_dpd = _avg([p["days_past_due"] for p in prior_p])
            if recent_dpd - prior_dpd > T["dpd_trend_delta_days"]:
                signals.append(
                    _signal(
                        "rising_dpd",
                        f"avg days-past-due rose from {prior_dpd:.0f} to {recent_dpd:.0f} "
                        "over recent months",
                    )
                )

        # recent_late — latest EMI paid late
        latest = payments[-1]
        if latest["days_past_due"] > T["recent_late_days"]:
            signals.append(
                _signal(
                    "recent_late",
                    f"most recent EMI ({latest['month']}) paid {latest['days_past_due']} "
                    "days late",
                )
            )

        # failed_auto_debit — repeated failures in the recent window
        failed = sum(1 for p in recent_p if p.get("auto_debit_failed"))
        if failed >= T["failed_debit_count"]:
            signals.append(
                _signal(
                    "failed_auto_debit",
                    f"{failed} failed auto-debits in the last "
                    f"{T['recent_window_months']} months",
                )
            )

        # skipped_partial — any partial payment in the recent window
        if any(p.get("partial") for p in recent_p):
            signals.append(
                _signal(
                    "skipped_partial",
                    f"partial payment recorded in the last "
                    f"{T['recent_window_months']} months",
                )
            )

    # ---------------------------------------------------------------
    # Cash-flow signals (require transaction data)
    # ---------------------------------------------------------------
    if has_transactions:
        recent_t, prior_t = _windows(transactions)
        latest_t = transactions[-1]
        n = T["recent_window_months"]

        # high_utilization — latest utilization above danger threshold
        util_now = latest_t["credit_utilization"]
        if util_now > T["high_utilization_ratio"]:
            signals.append(
                _signal("high_utilization", f"credit utilization at {util_now:.0%}")
            )

        # rising_utilization — compare latest to N months earlier
        if len(transactions) > n:
            util_then = transactions[-(n + 1)]["credit_utilization"]
            if util_now - util_then > T["rising_utilization_delta"]:
                signals.append(
                    _signal(
                        "rising_utilization",
                        f"utilization climbed {(util_now - util_then) * 100:.0f} points "
                        f"(from {util_then:.0%} to {util_now:.0%})",
                    )
                )

        # falling_income — recent avg inflow well below prior avg
        if prior_t:
            recent_inc = _avg([t["income_inflow"] for t in recent_t])
            prior_inc = _avg([t["income_inflow"] for t in prior_t])
            if prior_inc > 0 and recent_inc < T["income_drop_ratio"] * prior_inc:
                drop = (1 - recent_inc / prior_inc) * 100
                signals.append(
                    _signal("falling_income", f"income inflow down {drop:.0f}% vs prior months")
                )

        # declining_balance — draining toward zero and trending down
        if prior_t:
            recent_bal = _avg([t["avg_balance"] for t in recent_t])
            prior_bal = _avg([t["avg_balance"] for t in prior_t])
            floor = T["balance_floor_emi_fraction"] * borrower["emi_amount"]
            if latest_t["avg_balance"] < floor and recent_bal < prior_bal:
                signals.append(
                    _signal(
                        "declining_balance",
                        f"avg balance ({latest_t['avg_balance']:,.0f}) below half an EMI "
                        "and trending down",
                    )
                )
    else:
        caveats.append("degraded_confidence")  # no transaction data

    # ---------------------------------------------------------------
    # History sufficiency
    # ---------------------------------------------------------------
    if history_months < T["min_history_months"]:
        caveats.append("insufficient_history")

    return {
        "signals": signals,
        "history_months": history_months,
        "has_transactions": has_transactions,
        "caveats": caveats,
    }
