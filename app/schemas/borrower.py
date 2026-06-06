"""Borrower-facing and analyst-facing risk schemas."""
from __future__ import annotations

from pydantic import BaseModel

from .common import RiskSignal


class BorrowerSummary(BaseModel):
    """Compact row for the severity-sorted list."""
    borrower_id: str
    name: str
    risk_score: int
    category: str
    confidence: str
    recommended_action: str


class BorrowerRisk(BaseModel):
    """Full analyst-facing risk detail."""
    borrower_id: str
    name: str
    risk_score: int
    category: str
    confidence: str
    triggered_signals: list[RiskSignal]
    recommended_action: str
    data_caveats: list[str]


class BorrowerView(BaseModel):
    """Minimal borrower-facing view — no score, no internal signals."""
    borrower_id: str
    category_message: str
    next_step: str
    explanation: str
    explanation_source: str
