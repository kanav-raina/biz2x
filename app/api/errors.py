"""Uniform error envelope for HTTPExceptions.

Every error response is shaped as ``{"error": {"code": ..., "message": ...}}`` so
clients can rely on a single structure regardless of which endpoint failed.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse


async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": detail}
    else:
        body = {"error": {"code": "ERROR", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
