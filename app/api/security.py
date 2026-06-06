"""Mock role-based access control.

Authentication is simulated via two request headers (no real JWT for the
prototype):
    X-User-Role:  analyst | borrower | manager
    X-User-Id:    e.g. analyst_1, B123

The enforcement rules below are the SAME ones a production system would apply
after decoding a real token — only the identity source is mocked. See README
"Security & Privacy" for the production design (JWT, row-level isolation,
PII masking, audit logging).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

VALID_ROLES = {"analyst", "borrower", "manager"}


@dataclass
class Principal:
    role: str
    user_id: str


def get_principal(
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency: resolve and validate the caller identity."""
    if not x_user_role or not x_user_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHENTICATED",
                    "message": "X-User-Role and X-User-Id headers are required"},
        )
    if x_user_role not in VALID_ROLES:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_ROLE",
                    "message": f"role must be one of {sorted(VALID_ROLES)}"},
        )
    return Principal(role=x_user_role, user_id=x_user_id)


def authorize_borrower_access(principal: Principal, facts: dict) -> None:
    """Enforce who may read a given borrower's risk record.

    - borrower : only their own record
    - analyst  : only borrowers assigned to them
    - manager  : not allowed at the individual-borrower level (portfolio only)
    """
    if principal.role == "borrower":
        if principal.user_id != facts["borrower_id"]:
            _forbid()
    elif principal.role == "analyst":
        if principal.user_id != facts["assigned_analyst"]:
            _forbid()
    elif principal.role == "manager":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN",
                    "message": "managers access portfolio summaries, not individual borrowers"},
        )


def require_role(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        _forbid()


def _forbid() -> None:
    raise HTTPException(
        status_code=403,
        detail={"code": "FORBIDDEN", "message": "you are not permitted to access this resource"},
    )
