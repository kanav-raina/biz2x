"""LLM explanation layer.

Calls the provided hosted LLM wrapper to verbalise a borrower's risk facts. The
LLM NEVER sees raw data and NEVER does math — it only rewrites a structured facts
object into prose. This is the grounding boundary that keeps explanations
auditable.

Resilience: if the wrapper is unreachable, errors, or no token is configured, we
fall back to a deterministic template built from the same facts. The alerting API
therefore never hard-fails on an LLM outage, and every response reports its
`explanation_source` ('llm' or 'fallback') honestly.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger("ews.explain")

LLM_URL = os.getenv(
    "LLM_API_URL",
    "https://llm-wrapper-741152993481.asia-south1.run.app/llm/query",
)
LLM_TOKEN = os.getenv("LLM_API_TOKEN", "")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

# Exact refusal string the model is instructed to emit for out-of-scope questions.
OUT_OF_SCOPE_MARKER = "That information is not available in this borrower's risk data."


# ---------------------------------------------------------------------------
# Fact preparation — the only data the model is allowed to see.
# ---------------------------------------------------------------------------
def _facts_for_prompt(facts: dict) -> dict[str, Any]:
    return {
        "borrower_id": facts["borrower_id"],
        "risk_category": facts["category"],
        "risk_score": facts["risk_score"],
        "confidence": facts["confidence"],
        "triggered_signals": [
            {"signal": s["signal"], "detail": s["detail"]}
            for s in facts["triggered_signals"]
        ],
        "recommended_action": facts["recommended_action"],
        "data_caveats": facts["data_caveats"],
    }


def _grounded_on(facts: dict) -> list[str]:
    return [s["signal"] for s in facts["triggered_signals"]]


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------
def _explanation_prompt(facts: dict, tone: str) -> str:
    audience = (
        "a credit/collections analyst" if tone == "analyst" else "the borrower"
    )
    style = (
        "Use precise, professional language."
        if tone == "analyst"
        else "Use plain, empathetic language. Do not mention internal scores, "
        "weights, or signal names."
    )
    return (
        f"You are a credit-risk assistant. Explain a borrower's risk alert to {audience}.\n\n"
        "STRICT RULES:\n"
        "- Use ONLY the facts in the JSON below. Do not invent numbers, dates, or reasons.\n"
        "- Do not speculate about causes that are not present in the facts.\n"
        f"- Be concise (2-4 sentences). {style}\n\n"
        f"FACTS:\n{json.dumps(_facts_for_prompt(facts), indent=2)}\n\n"
        "Write the explanation."
    )


def _query_prompt(facts: dict, question: str) -> str:
    return (
        "Answer the analyst's question using ONLY the FACTS below.\n"
        f'If the answer is not in the facts, reply EXACTLY: "{OUT_OF_SCOPE_MARKER}"\n'
        "Do not guess. Do not invent information.\n\n"
        f"FACTS:\n{json.dumps(_facts_for_prompt(facts), indent=2)}\n\n"
        f"QUESTION: {question}"
    )


# ---------------------------------------------------------------------------
# Templated fallbacks (deterministic, from the same facts)
# ---------------------------------------------------------------------------
def _template_explanation(facts: dict, tone: str) -> str:
    if tone == "borrower":
        return facts["borrower_action"]
    reasons = "; ".join(s["detail"] for s in facts["triggered_signals"])
    if not reasons:
        return (
            f"{facts['name']} is currently {facts['category']} with no active risk "
            "signals. Recommended action: " + facts["recommended_action"] + "."
        )
    caveat = ""
    if facts["data_caveats"]:
        caveat = f" (Note: {', '.join(facts['data_caveats'])}.)"
    return (
        f"{facts['name']} is flagged {facts['category']} "
        f"(score {facts['risk_score']}). Key reasons: {reasons}. "
        f"Recommended action: {facts['recommended_action']}.{caveat}"
    )


def _template_answer(facts: dict, question: str) -> str:
    # Fallback Q&A simply restates grounded reasons; cannot answer beyond facts.
    return _template_explanation(facts, tone="analyst")


# ---------------------------------------------------------------------------
# Wrapper call
# ---------------------------------------------------------------------------
def _extract_text(payload: Any) -> str | None:
    """Defensively pull the generated text from the wrapper response.

    The wrapper's exact response shape is not documented, so we probe the common
    field names and fall back to the raw string if it is plain text.
    """
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, dict):
        for key in ("response", "text", "answer", "result", "output", "content", "message", "completion"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            # some wrappers nest, e.g. {"data": {"text": ...}}
            if isinstance(val, dict):
                nested = _extract_text(val)
                if nested:
                    return nested
        # Anthropic-style content list: [{"type":"text","text":"..."}]
        content = payload.get("content")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            joined = " ".join(p for p in parts if p).strip()
            if joined:
                return joined
    return None


def _call_wrapper(prompt: str, trace_id: str, borrower_id: str) -> str | None:
    """Call the LLM wrapper. Returns generated text, or None on any failure."""
    if not LLM_TOKEN:
        logger.info("LLM token not configured; using fallback", extra={"trace_id": trace_id})
        return None
    try:
        resp = httpx.post(
            LLM_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_TOKEN}",
            },
            json={
                "prompt": prompt,
                "metadata": {"client": "loan-ews", "traceId": trace_id, "borrowerId": borrower_id},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        text = _extract_text(data)
        if not text:
            logger.warning("LLM response unparsable; using fallback", extra={"trace_id": trace_id})
        return text
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("LLM call failed (%s); using fallback", exc, extra={"trace_id": trace_id})
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_explanation(facts: dict, tone: str = "analyst") -> dict[str, Any]:
    trace_id = str(uuid.uuid4())
    text = _call_wrapper(_explanation_prompt(facts, tone), trace_id, facts["borrower_id"])
    source = "llm" if text else "fallback"
    if not text:
        text = _template_explanation(facts, tone)
    _audit("explain", facts, trace_id, source)
    return {
        "borrower_id": facts["borrower_id"],
        "explanation": text,
        "explanation_source": source,
        "grounded_on": _grounded_on(facts),
        "trace_id": trace_id,
    }


def answer_query(facts: dict, question: str) -> dict[str, Any]:
    trace_id = str(uuid.uuid4())
    text = _call_wrapper(_query_prompt(facts, question), trace_id, facts["borrower_id"])
    source = "llm" if text else "fallback"
    if not text:
        text = _template_answer(facts, question)
    out_of_scope = OUT_OF_SCOPE_MARKER.lower() in text.lower()
    _audit("query", facts, trace_id, source, question=question)
    return {
        "borrower_id": facts["borrower_id"],
        "answer": text,
        "grounded_on": _grounded_on(facts),
        "out_of_scope": out_of_scope,
        "explanation_source": source,
        "trace_id": trace_id,
    }


def _audit(action: str, facts: dict, trace_id: str, source: str, **extra: Any) -> None:
    """Structured audit log — every inference is traceable to actor, borrower,
    grounding signals, and source."""
    record = {
        "action": action,
        "trace_id": trace_id,
        "borrower_id": facts["borrower_id"],
        "source": source,
        "grounded_on": _grounded_on(facts),
        **extra,
    }
    logger.info("AUDIT %s", json.dumps(record))
