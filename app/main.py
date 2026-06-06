"""FastAPI application entrypoint: Loan Default Risk Early Warning System.

Wires the deterministic scoring core to a role-aware REST API. The heavy lifting
lives in dedicated layers (``domain`` scoring, ``repositories`` data access,
``services`` LLM integration, ``api`` HTTP routing); this module only assembles
them into the running app.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE importing modules that read env vars at import time
# (e.g. services/explain.py captures LLM_API_TOKEN on import). Importing those
# first would read the token before it is loaded, silently forcing the fallback.
load_dotenv()

from fastapi import FastAPI

from .api.errors import register_error_handlers
from .api.routes import api_router
from .repositories.borrower_repository import repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    repo.load()  # compute all risk assessments once at startup
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Loan Default Risk Early Warning System",
        description="Flags borrowers likely to become delinquent in the next 30 days, "
        "with grounded, auditable explanations and recommended actions.",
        version="1.0.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
