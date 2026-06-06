"""API + RBAC + LLM-grounding tests.

The LLM wrapper is mocked with respx so tests run offline and deterministically.
"""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.services import explain

ANALYST1 = {"X-User-Role": "analyst", "X-User-Id": "analyst_1"}
ANALYST2 = {"X-User-Role": "analyst", "X-User-Id": "analyst_2"}
BORROWER_B001 = {"X-User-Role": "borrower", "X-User-Id": "B001"}
MANAGER = {"X-User-Role": "manager", "X-User-Id": "mgr_1"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- auth / RBAC -------------------------------------------------------------
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_requires_auth(client):
    assert client.get("/borrowers").status_code == 401


def test_analyst_sees_only_assigned_book(client):
    rows = client.get("/borrowers", headers=ANALYST2).json()
    assert rows, "analyst_2 should have borrowers"
    # B003,B004,B005,B008 are analyst_2's; none of analyst_1's should leak in.
    ids = {r["borrower_id"] for r in rows}
    assert ids <= {"B003", "B004", "B005", "B008"}


def test_severity_filter(client):
    rows = client.get("/borrowers?severity=Critical", headers=ANALYST2).json()
    assert all(r["category"] == "Critical" for r in rows)


def test_invalid_severity_is_400(client):
    assert client.get("/borrowers?severity=Nope", headers=ANALYST1).status_code == 400


def test_rbac_cross_analyst_isolation(client):
    # analyst_1 cannot read B003 (assigned to analyst_2)
    assert client.get("/borrowers/B003", headers=ANALYST1).status_code == 403


def test_unknown_borrower_404(client):
    assert client.get("/borrowers/B999", headers=ANALYST1).status_code == 404


def test_borrower_minimal_view_hides_score(client):
    resp = client.get("/borrowers/B001", headers=BORROWER_B001)
    assert resp.status_code == 200
    body = resp.json()
    assert "risk_score" not in body
    assert "triggered_signals" not in body
    assert "next_step" in body


def test_borrower_cannot_read_others(client):
    assert client.get("/borrowers/B002", headers=BORROWER_B001).status_code == 403


def test_manager_portfolio_only(client):
    assert client.get("/portfolio/summary", headers=MANAGER).status_code == 200
    # managers cannot read an individual borrower
    assert client.get("/borrowers/B001", headers=MANAGER).status_code == 403


def test_query_requires_analyst(client):
    resp = client.post("/borrowers/B001/query", headers=BORROWER_B001,
                       json={"question": "why?"})
    assert resp.status_code == 403


# --- LLM grounding -----------------------------------------------------------
def test_explanation_falls_back_without_token(client, monkeypatch):
    monkeypatch.setattr(explain, "LLM_TOKEN", "")
    resp = client.get("/borrowers/B005/explanation", headers=ANALYST2)
    assert resp.status_code == 200
    body = resp.json()
    assert body["explanation_source"] == "fallback"
    assert body["grounded_on"]  # signals are listed
    # fallback text must mention a grounded reason, not invent one
    assert "days-past-due" in body["explanation"] or "utilization" in body["explanation"]


@respx.mock
def test_explanation_uses_llm_when_available(client, monkeypatch):
    monkeypatch.setattr(explain, "LLM_TOKEN", "test-token")
    respx.post(explain.LLM_URL).mock(
        return_value=httpx.Response(200, json={"response": "This borrower is high risk."})
    )
    resp = client.get("/borrowers/B005/explanation", headers=ANALYST2)
    body = resp.json()
    assert body["explanation_source"] == "llm"
    assert body["explanation"] == "This borrower is high risk."


@respx.mock
def test_query_out_of_scope_is_flagged(client, monkeypatch):
    monkeypatch.setattr(explain, "LLM_TOKEN", "test-token")
    respx.post(explain.LLM_URL).mock(
        return_value=httpx.Response(200, json={"response": explain.OUT_OF_SCOPE_MARKER})
    )
    resp = client.post("/borrowers/B005/query", headers=ANALYST2,
                      json={"question": "What is the borrower's credit score?"})
    body = resp.json()
    assert body["out_of_scope"] is True


@respx.mock
def test_llm_failure_falls_back_gracefully(client, monkeypatch):
    monkeypatch.setattr(explain, "LLM_TOKEN", "test-token")
    respx.post(explain.LLM_URL).mock(side_effect=httpx.ConnectError("boom"))
    resp = client.get("/borrowers/B005/explanation", headers=ANALYST2)
    assert resp.status_code == 200
    assert resp.json()["explanation_source"] == "fallback"
