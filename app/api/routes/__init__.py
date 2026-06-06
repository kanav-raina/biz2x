"""Resource routers, aggregated into a single ``api_router``."""
from fastapi import APIRouter

from . import borrowers, meta, portfolio

api_router = APIRouter()
api_router.include_router(meta.router)
api_router.include_router(borrowers.router)
api_router.include_router(portfolio.router)
