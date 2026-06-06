"""Borrower risk endpoints: list, detail, explanation, and analyst Q&A.

Response shaping per role is centralised here so borrowers, analysts, and
managers each see only what they should.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.config import CATEGORIES
from ...repositories.borrower_repository import repo
from ...schemas import (
    BorrowerRisk,
    BorrowerSummary,
    BorrowerTrendResp,
    BorrowerView,
    ExplanationResp,
    QueryReq,
    QueryResp,
    RiskTrendResp,
    SimulationResp,
)
from ...services import explain
from ..deps import get_facts_or_404
from ..security import (
    Principal,
    authorize_borrower_access,
    get_principal,
    require_role,
)

router = APIRouter(prefix="/borrowers", tags=["risk"])


@router.get("", response_model=list[BorrowerSummary])
def list_borrowers(
    principal: Principal = Depends(get_principal),
    severity: str | None = Query(
        default=None,
        description="Comma-separated severities to filter, e.g. 'High Risk,Critical'",
    ),
):
    """List borrowers by risk severity (analysts see only their assigned book)."""
    require_role(principal, "analyst", "manager")

    severities: set[str] | None = None
    if severity:
        severities = {s.strip() for s in severity.split(",") if s.strip()}
        invalid = severities - CATEGORIES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_SEVERITY",
                        "message": f"unknown severity values: {sorted(invalid)}"},
            )

    analyst = principal.user_id if principal.role == "analyst" else None
    facts_list = repo.list_facts(severities=severities, analyst=analyst)
    return [
        BorrowerSummary(
            borrower_id=f["borrower_id"],
            name=f["name"],
            risk_score=f["risk_score"],
            category=f["category"],
            confidence=f["confidence"],
            recommended_action=f["recommended_action"],
        )
        for f in facts_list
    ]


@router.get("/{borrower_id}")
def get_borrower(borrower_id: str, principal: Principal = Depends(get_principal)):
    """Risk detail for one borrower.

    Analysts get the full assessment (score + signals); borrowers get a minimal,
    score-free view with a grounded explanation.
    """
    facts = get_facts_or_404(borrower_id)
    authorize_borrower_access(principal, facts)

    if principal.role == "borrower":
        exp = explain.generate_explanation(facts, tone="borrower")
        return BorrowerView(
            borrower_id=facts["borrower_id"],
            category_message=facts["borrower_action"],
            next_step=facts["borrower_action"],
            explanation=exp["explanation"],
            explanation_source=exp["explanation_source"],
        )

    return BorrowerRisk(
        borrower_id=facts["borrower_id"],
        name=facts["name"],
        risk_score=facts["risk_score"],
        category=facts["category"],
        confidence=facts["confidence"],
        triggered_signals=facts["triggered_signals"],
        recommended_action=facts["recommended_action"],
        data_caveats=facts["data_caveats"],
    )


@router.get("/{borrower_id}/trend")
def get_trend(borrower_id: str, principal: Principal = Depends(get_principal)):
    """Risk trend over time for one borrower.

    Analysts get the full score/category series; borrowers get a minimal,
    score-free category trend (same minimal-view principle as the detail route).
    """
    facts = get_facts_or_404(borrower_id)
    authorize_borrower_access(principal, facts)
    trend = repo.risk_trend(borrower_id)

    if principal.role == "borrower":
        return BorrowerTrendResp(
            borrower_id=trend["borrower_id"],
            points=[{"month": p["month"], "category": p["category"]} for p in trend["points"]],
            direction=trend["direction"],
        )

    return RiskTrendResp(**trend)


@router.post("/{borrower_id}/simulate", response_model=SimulationResp, tags=["ai"])
def simulate_borrower(borrower_id: str, principal: Principal = Depends(get_principal)):
    """Scenario simulation — 'What if the next EMI is missed?'

    Analyst-only what-if tool: re-scores the borrower with a hypothetical missed
    next EMI and reports the before/after delta. Deterministic and grounded.
    """
    require_role(principal, "analyst")
    facts = get_facts_or_404(borrower_id)
    authorize_borrower_access(principal, facts)
    return repo.simulate_missed_emi(borrower_id)


@router.get("/{borrower_id}/explanation", response_model=ExplanationResp, tags=["ai"])
def get_explanation(borrower_id: str, principal: Principal = Depends(get_principal)):
    """LLM-generated, grounded explanation for the borrower's alert."""
    facts = get_facts_or_404(borrower_id)
    authorize_borrower_access(principal, facts)
    tone = "borrower" if principal.role == "borrower" else "analyst"
    return explain.generate_explanation(facts, tone=tone)


@router.post("/{borrower_id}/query", response_model=QueryResp, tags=["ai"])
def query_borrower(
    borrower_id: str, body: QueryReq, principal: Principal = Depends(get_principal)
):
    """Analyst Q&A: 'Why was borrower B123 flagged?' Answered only from this
    borrower's computed facts; out-of-scope questions are refused."""
    require_role(principal, "analyst")
    facts = get_facts_or_404(borrower_id)
    authorize_borrower_access(principal, facts)
    return explain.answer_query(facts, body.question)
