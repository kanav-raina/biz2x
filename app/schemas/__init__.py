"""Pydantic request/response models. These double as the OpenAPI contract at
/docs, so they are the public API surface.

Models are grouped by resource in submodules and re-exported here so callers can
import them from a single, stable location.
"""
from .borrower import BorrowerRisk, BorrowerSummary, BorrowerView
from .common import ErrorBody, ErrorResp, RiskSignal
from .explanation import ExplanationResp, QueryReq, QueryResp
from .portfolio import AnalystBook, PortfolioSummary, SignalPrevalence
from .simulation import ScenarioState, SimulationResp
from .trend import (
    BorrowerTrendPoint,
    BorrowerTrendResp,
    RiskTrendResp,
    TrendPoint,
)

__all__ = [
    "BorrowerRisk",
    "BorrowerSummary",
    "BorrowerView",
    "ErrorBody",
    "ErrorResp",
    "RiskSignal",
    "ExplanationResp",
    "QueryReq",
    "QueryResp",
    "PortfolioSummary",
    "SignalPrevalence",
    "AnalystBook",
    "RiskTrendResp",
    "TrendPoint",
    "BorrowerTrendResp",
    "BorrowerTrendPoint",
    "SimulationResp",
    "ScenarioState",
]
