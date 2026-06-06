"""Shared schema fragments reused across resources."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RiskSignal(BaseModel):
    signal: str = Field(..., examples=["rising_dpd"])
    weight: int = Field(..., examples=[25])
    detail: str = Field(..., examples=["avg days-past-due rose from 0 to 9 over recent months"])


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResp(BaseModel):
    error: ErrorBody
