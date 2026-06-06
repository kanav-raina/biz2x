"""Risk-trend (time-series) schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TrendPoint(BaseModel):
    month: str = Field(..., examples=["2026-05"])
    risk_score: int = Field(..., examples=[78])
    category: str = Field(..., examples=["Critical"])
    confidence: str = Field(..., examples=["high"])


class RiskTrendResp(BaseModel):
    """Month-by-month risk history for one borrower (analyst view)."""
    borrower_id: str
    points: list[TrendPoint]
    direction: str = Field(..., description="improving | worsening | stable")
    score_change: int = Field(..., description="latest score minus earliest score")


class BorrowerTrendPoint(BaseModel):
    """Score-free trend point for the borrower-facing view."""
    month: str
    category: str


class BorrowerTrendResp(BaseModel):
    """Minimal, score-free trend for the borrower's own view."""
    borrower_id: str
    points: list[BorrowerTrendPoint]
    direction: str
