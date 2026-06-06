"""Scenario-simulation ("what if the next EMI is missed?") schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScenarioState(BaseModel):
    """A risk assessment snapshot (baseline or simulated)."""
    risk_score: int
    category: str
    confidence: str
    triggered_signals: list[str]


class SimulationResp(BaseModel):
    borrower_id: str
    scenario: str = Field(..., examples=["miss_next_emi"])
    assumptions: dict = Field(
        ..., description="The synthetic record's key fields (transparent inputs)"
    )
    baseline: ScenarioState
    simulated: ScenarioState
    score_change: int
    category_change: bool
    new_signals: list[str] = Field(
        ..., description="Signals the missed EMI would newly trigger"
    )
    summary: str
