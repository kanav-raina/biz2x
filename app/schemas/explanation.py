"""Schemas for the LLM explanation and Q&A endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExplanationResp(BaseModel):
    borrower_id: str
    explanation: str
    explanation_source: str = Field(..., description="'llm' or 'fallback'")
    grounded_on: list[str]
    trace_id: str


class QueryReq(BaseModel):
    question: str = Field(..., examples=["Why was this borrower flagged?"])


class QueryResp(BaseModel):
    borrower_id: str
    answer: str
    grounded_on: list[str]
    out_of_scope: bool
    explanation_source: str
    trace_id: str
