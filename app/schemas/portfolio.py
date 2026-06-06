"""Portfolio-level (manager) schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SignalPrevalence(BaseModel):
    signal: str = Field(..., examples=["high_utilization"])
    count: int = Field(..., examples=[4])


class AnalystBook(BaseModel):
    analyst: str = Field(..., examples=["analyst_2"])
    total: int
    at_risk: int = Field(..., description="High Risk + Critical borrowers in this book")


class PortfolioSummary(BaseModel):
    """Aggregate, PII-free portfolio health for managers."""
    total_borrowers: int
    by_category: dict[str, int]
    by_category_pct: dict[str, float]
    at_risk_count: int = Field(..., description="High Risk + Critical borrowers")
    average_risk_score: float
    total_outstanding: float = Field(..., description="Total outstanding balance across the book")
    at_risk_outstanding: float = Field(
        ..., description="Outstanding balance concentrated in the at-risk book (exposure)"
    )
    low_confidence_count: int = Field(
        ..., description="Borrowers scored with low confidence (data-quality watch)"
    )
    top_signals: list[SignalPrevalence] = Field(
        ..., description="Most prevalent early-warning signals across the portfolio"
    )
    by_analyst: list[AnalystBook] = Field(
        ..., description="Per-analyst book health, most at-risk first"
    )
