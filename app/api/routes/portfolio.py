"""Portfolio-level (manager) endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...repositories.borrower_repository import repo
from ...schemas import PortfolioSummary
from ..security import Principal, get_principal, require_role

router = APIRouter(prefix="/portfolio", tags=["risk"])


@router.get("/summary", response_model=PortfolioSummary)
def portfolio_summary(principal: Principal = Depends(get_principal)):
    """Portfolio-level risk counts (managers only)."""
    require_role(principal, "manager")
    return repo.portfolio_summary()
