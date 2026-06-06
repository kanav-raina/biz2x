"""Single source of truth for all scoring thresholds, weights, and assumptions.

Everything that controls risk segmentation lives here so it is documented in one
place and tunable without touching logic. Referenced by the README.
"""

# --- Signal weights (points added to the risk score when a signal fires) ---
# Rationale: payment-behaviour signals (DPD, failed debits) are weighted highest
# because they are the most direct, late-stage indicators of delinquency. Cash-flow
# signals (income, balance, utilization) are earlier but noisier, so weighted lower.
WEIGHTS = {
    # --- payment-behaviour signals (available from repayment history) ---
    "rising_dpd": 25,          # days-past-due trending up over recent months
    "recent_late": 20,         # most recent EMI paid late
    "failed_auto_debit": 20,   # repeated auto-debit failures (liquidity stress)
    "skipped_partial": 10,     # a partial payment in the recent window
    # --- cash-flow signals (require transaction data) ---
    "high_utilization": 15,    # credit utilization above the danger threshold
    "rising_utilization": 10,  # utilization climbing quickly
    "falling_income": 15,      # income inflow shrinking
    "declining_balance": 10,   # account balance draining toward zero
}

# Signals that depend on transaction data. If transactions are missing for a
# borrower, these are skipped and confidence is downgraded.
CASHFLOW_SIGNALS = {
    "high_utilization",
    "rising_utilization",
    "falling_income",
    "declining_balance",
}

# --- Risk bands: (minimum score inclusive, category). Checked high to low. ---
BANDS = [
    (71, "Critical"),
    (46, "High Risk"),
    (21, "Watchlist"),
    (0, "Low"),
]

# All valid risk categories, derived from the bands (used to validate filters).
CATEGORIES = {category for _, category in BANDS}

# --- Recommended action per category (analyst / collections framing) ---
ACTIONS = {
    "Low": "Monitor — no action needed",
    "Watchlist": "Soft reminder (SMS / email)",
    "High Risk": "Proactive call + offer a payment plan",
    "Critical": "Restructuring review + senior analyst escalation",
}

# --- Borrower-facing reframing of the recommended action (no scary internals) ---
BORROWER_ACTIONS = {
    "Low": "Your account is in good standing. Keep paying on time.",
    "Watchlist": "A friendly reminder: please ensure your next EMI is paid on time.",
    "High Risk": "You may be at risk of missing a payment. Consider setting up a payment plan — contact support.",
    "Critical": "Your account needs attention. Please contact us to discuss restructuring options.",
}

# --- Signal detection thresholds (documented assumptions) ---
THRESHOLDS = {
    "dpd_trend_delta_days": 3,     # recent-vs-prior avg DPD jump to flag rising_dpd
    "recent_late_days": 5,         # DPD above this on the latest EMI => recent_late
    "failed_debit_count": 2,       # failures in recent window to flag failed_auto_debit
    "high_utilization_ratio": 0.80,
    "rising_utilization_delta": 0.15,
    "income_drop_ratio": 0.80,     # recent avg < 80% of prior avg => falling_income
    "balance_floor_emi_fraction": 0.50,  # latest balance < 0.5 * EMI => low balance
    "recent_window_months": 3,     # "recent" = last N months, "prior" = the N before
    "min_history_months": 2,       # fewer than this => insufficient_history
}

# Category ceiling applied when history is insufficient (cannot be exceeded).
INSUFFICIENT_HISTORY_CAP = "Watchlist"

# --- Categories considered "at risk" for portfolio exposure metrics ---
# High Risk + Critical borrowers are where exposure (outstanding balance) and
# collections effort are concentrated; managers track these as the at-risk book.
AT_RISK_CATEGORIES = {"High Risk", "Critical"}

# --- Scenario-simulation parameters (e.g. "what if the next EMI is missed?") ---
# A hypothetical next-cycle record is appended and the borrower is re-scored. These
# values describe the synthetic missed EMI; they are assumptions, kept here so the
# simulation is transparent and tunable like every other threshold.
SIMULATION = {
    # Days-past-due stamped on the hypothetical missed EMI. A full missed cycle is
    # modelled as ~30 days late (the early-warning horizon), which is well above
    # the recent_late threshold and pushes the DPD trend upward.
    "missed_emi_dpd": 30,
    # A missed EMI is assumed to coincide with an auto-debit failure (no funds).
    "missed_emi_auto_debit_failed": True,
    # A fully missed EMI is not a partial payment.
    "missed_emi_partial": False,
}
