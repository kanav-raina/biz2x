"""Shared route dependencies/helpers."""
from __future__ import annotations

from fastapi import HTTPException

from ..repositories.borrower_repository import repo


def get_facts_or_404(borrower_id: str) -> dict:
    """Fetch a borrower's computed risk facts or raise a 404."""
    facts = repo.get_facts(borrower_id)
    if facts is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "BORROWER_NOT_FOUND",
                    "message": f"No borrower with id {borrower_id}"},
        )
    return facts
