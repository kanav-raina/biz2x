# Loan Default Risk — Early Warning System

A prototype that flags borrowers likely to become **delinquent within the next 30 days**,
*before* they miss an EMI, with **grounded, auditable** explanations and recommended
actions for credit / collections teams.

> Built for the Fintech Lending SSE case study. FastAPI service, rule-based scoring,
> LLM explanations via the provided hosted wrapper.

---

## 1. What it does

```
mock data ──► signal engine ──► rule-based score ──► risk category ──► alert + action
                                                              │
                                                              ▼
                                              grounded LLM explanation + analyst Q&A
```

For each borrower the system:
1. Reads repayment history, loan terms, and cash-flow behaviour (mock data).
2. Computes **early-warning signals** (rising DPD, failed auto-debits, utilization, income, etc.).
3. Produces a **risk score → category**: `Low · Watchlist · High Risk · Critical`.
4. Generates an **alert** with key reasons, severity, and a **recommended action**.
5. Lets analysts ask *"Why was borrower B005 flagged?"* — answered **only** from that
   borrower's computed facts (out-of-scope questions are refused).

The LLM **never sees raw data and never does math** — the deterministic Python core
computes everything; the LLM only verbalises a structured facts object. That is the
grounding boundary that keeps every explanation auditable.

---

## 2. Quick start

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt

copy .env.example .env           # then paste the provided LLM_API_TOKEN
uvicorn app.main:app --reload
# open http://localhost:8000/docs   (interactive Swagger UI)

pytest                           # run the 46-test suite
```

The API works **without** a token too — explanation endpoints fall back to a
deterministic templated explanation built from the same facts (see §6).

---

## 3. API

All endpoints require simulated auth via two headers (see §7):
`X-User-Role` and `X-User-Id`.

| Method | Path | Role | Purpose |
|---|---|---|---|
| `GET` | `/health` | any | Liveness |
| `GET` | `/borrowers?severity=High Risk,Critical` | analyst / manager | Borrowers by risk severity |
| `GET` | `/borrowers/{id}` | analyst / borrower | Risk detail (borrower gets a minimal, score-free view) |
| `GET` | `/borrowers/{id}/trend` | analyst / borrower | Risk **trend over time** (month-by-month; borrower view is score-free) |
| `POST` | `/borrowers/{id}/simulate` | analyst | **Scenario simulation** — *"What if the next EMI is missed?"* |
| `GET` | `/borrowers/{id}/explanation` | analyst / borrower | Grounded LLM explanation of the alert |
| `POST` | `/borrowers/{id}/query` | analyst | Q&A — *"Why was B005 flagged?"*, facts-only |
| `GET` | `/portfolio/summary` | manager | **Portfolio risk summary** — tiers, exposure-at-risk, top signals, per-analyst book health |

### Example

```bash
# List analyst_2's high-severity book
curl -H "X-User-Role: analyst" -H "X-User-Id: analyst_2" \
  "http://localhost:8000/borrowers?severity=Critical"

# Ask why a borrower was flagged
curl -X POST "http://localhost:8000/borrowers/B005/query" \
  -H "X-User-Role: analyst" -H "X-User-Id: analyst_2" \
  -H "Content-Type: application/json" \
  -d '{"question":"Why was this borrower flagged?"}'
```

Every response from the AI endpoints carries `grounded_on` (the exact signals used)
and `trace_id` (for the audit log) — so any explanation is traceable to its inputs.

### Bonus features (trend, simulation, portfolio)

All three are built on the **same deterministic scoring core** — no new heuristics,
no LLM math — so every number stays auditable.

**1. Risk trend over time** — `GET /borrowers/{id}/trend`
Replays history month by month: at each month the borrower is re-scored using only
the data available up to that point, yielding a time series plus a `direction`
(`improving` / `worsening` / `stable`). The newest point equals the current score.

```bash
curl -H "X-User-Role: analyst" -H "X-User-Id: analyst_2" \
  "http://localhost:8000/borrowers/B005/trend"
# -> points: 2025-12 Low(0) ... 2026-03 High Risk(55) ... 2026-05 Critical(100)
#    direction: "worsening", score_change: 100
```

**2. Scenario simulation** — `POST /borrowers/{id}/simulate`
Appends a *hypothetical* missed next-cycle EMI (parameters in `core/config.py →
SIMULATION`) and re-scores, returning the before/after delta and which signals the
miss would newly trigger.

```bash
curl -X POST -H "X-User-Role: analyst" -H "X-User-Id: analyst_1" \
  "http://localhost:8000/borrowers/B002/simulate"
# -> "If Vikram Shetty misses the 2026-06 EMI, the risk score would rise from
#     30 to 55 (+25), moving from Watchlist to High Risk." (new_signals: rising_dpd)
```

**3. Portfolio-level risk summary** — `GET /portfolio/summary` (managers)
Aggregate, PII-free book health: counts and percentages per tier, **at-risk
exposure** (outstanding balance in High Risk + Critical), average score, the most
prevalent early-warning signals, low-confidence (data-quality) count, and
**per-analyst book health** so caseload can be rebalanced.

---

## 4. Sample data schema

Mock data lives in `data/` (3 files). 9 borrowers, ~6 months of history each.

**`borrowers.json`**
```jsonc
{ "borrower_id": "B005", "name": "Priya Menon", "loan_amount": 900000,
  "emi_amount": 20000, "outstanding_balance": 780000, "credit_limit": 200000,
  "due_day": 3, "assigned_analyst": "analyst_2" }
```

**`payments.json`** (one row per borrower per month)
```jsonc
{ "borrower_id": "B005", "month": "2026-05", "due_date": "2026-05-03",
  "paid_date": "2026-05-21", "days_past_due": 18, "status": "paid_late",
  "auto_debit_failed": true, "partial": false }
```

**`transactions.json`** (monthly cash-flow aggregates)
```jsonc
{ "borrower_id": "B005", "month": "2026-05", "income_inflow": 70000,
  "avg_balance": 15500, "credit_utilization": 0.90 }
```

---

## 5. Risk scoring logic (thresholds & assumptions)

All weights, bands, and thresholds live in **`app/core/config.py`** — one tunable
source of truth. Signals are computed in `app/domain/signals.py`, scored in
`app/domain/scoring.py` (both pure, fully unit-tested).

### Signals & weights

| Signal | Fires when | Weight |
|---|---|---|
| `rising_dpd` | avg days-past-due (recent 3mo) − (prior 3mo) > 3 days | 25 |
| `recent_late` | latest EMI paid > 5 days late | 20 |
| `failed_auto_debit` | ≥ 2 auto-debit failures in last 3 months | 20 |
| `skipped_partial` | any partial payment in last 3 months | 10 |
| `high_utilization` | credit utilization > 80% | 15 |
| `rising_utilization` | utilization up > 15 pts over 3 months | 10 |
| `falling_income` | recent avg inflow < 80% of prior avg | 15 |
| `declining_balance` | avg balance < half an EMI **and** trending down | 10 |

> Payment-behaviour signals are weighted highest (most direct delinquency
> predictors); cash-flow signals are earlier but noisier, so weighted lower.

### Bands

| Score | Category | Recommended action |
|---|---|---|
| 0–20 | **Low** | Monitor — no action |
| 21–45 | **Watchlist** | Soft reminder (SMS/email) |
| 46–70 | **High Risk** | Proactive call + payment-plan offer |
| 71+ | **Critical** | Restructuring review + senior analyst escalation |

### Edge cases

| Scenario | Behaviour |
|---|---|
| **< 2 months history** | `insufficient_history` caveat; category **capped at Watchlist**; confidence `low` |
| **No transaction data** | cash-flow signals skipped; `degraded_confidence`; confidence `low` |
| **Recovered borrower** | past lateness does **not** flag if the *trend* is improving (signals are trend-based, not absolute) |
| **Unknown borrower** | `404 BORROWER_NOT_FOUND` |

---

## 6. AI explanations & grounding safeguards

- The LLM receives **only** a structured facts object (category, score, the triggered
  signals' detail strings, recommended action) — never raw rows, never asked to compute.
- **Q&A is grounded** by a strict prompt: answer only from the facts; if the answer
  isn't present, reply with a fixed refusal string → surfaced as `out_of_scope: true`.
  (Demo: ask for a borrower's "credit score" — not in the data — and it refuses.)
- **Resilience / graceful degradation:** if the wrapper is unreachable, times out, or
  no token is set, the endpoint returns a deterministic **templated** explanation from
  the same facts and reports `explanation_source: "fallback"`. The alerting API never
  hard-fails on an LLM outage.
- **Auditability:** every inference logs a structured line with `trace_id`, `borrower_id`,
  `source` (`llm`/`fallback`), and `grounded_on` (the signals used).

LLM transport: the provided hosted wrapper
(`POST /llm/query`, `Authorization: Bearer <token>`), called via `httpx` in
`app/services/explain.py`. Response text is parsed defensively across common field names.

---

## 7. Security & privacy

Authentication is **mocked** via headers for the prototype, but the **authorization
rules enforced are the real ones**:

| Role | May access |
|---|---|
| `borrower` | only their **own** record, and only a **minimal** view (no score, no internal signals) — just a plain-language explanation + next step |
| `analyst` | only borrowers where `assigned_analyst == them` (cross-analyst access → `403`) |
| `manager` | portfolio summary only (no individual borrower data) |

**In a real implementation** (described, not built here):
- Replace header auth with **JWT / OAuth**; derive role + identity from a verified token.
- **Row-level data isolation** at the query layer (borrower/analyst scoping in SQL or a policy engine), not just in the API.
- **PII handling**: mask/segregate sensitive fields; borrowers never receive internal scores or signal weights; LLM prompts carry only the minimal facts needed.
- **Audit logging** (already implemented in prototype form) on every data access and LLM inference, with `trace_id` correlation and retention controls.

---

## 8. Architecture & extensibility

The app is organised into layers, each with a single responsibility:

```
app/
  main.py                            app factory: wires layers, lifespan, error handler
  core/
    config.py                        all weights, bands, thresholds (single source of truth)
  domain/                            pure business logic (no I/O, fully unit-tested)
    signals.py                       signal engine (the 8 indicators)
    scoring.py                       signals -> score, category, confidence, action
    trend.py                         risk-trend replay (re-score on growing windows)
    simulation.py                    "what if next EMI is missed?" re-scoring
  repositories/
    borrower_repository.py           in-memory store; loads data and scores everyone at startup
  services/
    explain.py                       LLM wrapper (httpx) + grounding prompts + fallback + audit log
  schemas/                           Pydantic request/response models (= OpenAPI contract)
    borrower.py, explanation.py, portfolio.py, trend.py, simulation.py, common.py
  api/                               HTTP layer
    security.py                      mock RBAC dependency + authorization rules
    errors.py                        uniform error envelope
    deps.py                          shared route dependencies (e.g. fetch-or-404)
    routes/                          one router per resource
      meta.py, borrowers.py, portfolio.py
data/            borrowers.json, payments.json, transactions.json
tests/           test_scoring.py (persona tiers + edges), test_api.py (RBAC + grounding),
                 test_bonus.py (trend, simulation, portfolio)
```

Designed to extend cleanly:
- **Scale the store** → swap `repositories/borrower_repository.py` for a DB + scheduled batch
  scoring; nothing else changes.
- **Scale Q&A retrieval** → the facts lookup is keyed by `borrower_id`; replace the direct
  lookup with a retrieval layer. The grounding contract (facts-only prompt) stays identical.
- **Tune risk policy** → edit `core/config.py` only.

---

## 9. Test scenarios

`pytest` runs 46 tests. Highlights:

- **Persona tiers** — each of the 9 borrowers lands in its engineered category
  (B001 Low … B005 Critical … B009 Low-recovered).
- **Edge cases** — insufficient history is capped + flagged; missing transactions degrade
  confidence and skip cash-flow signals; a recovered borrower is *not* flagged.
- **RBAC** — cross-analyst isolation (403), borrower minimal view hides score, manager
  cannot read individuals, missing headers (401).
- **Grounding** — out-of-scope question is refused (`out_of_scope: true`); LLM failure /
  no token falls back gracefully (`explanation_source: "fallback"`). The wrapper is mocked
  with `respx` so tests run offline and deterministically.
- **Bonus features** — trend correctly reads a spiraling borrower as `worsening` and a
  recovered one as `improving`/`stable`; a simulated missed EMI escalates a Watchlist
  borrower into High Risk (and is deterministic); the portfolio summary's at-risk exposure,
  signal ranking, and per-analyst totals all reconcile to the book.

---

## 10. Assumptions, limitations, trade-offs

- **Heuristic, not ML.** Per the brief, scoring is rule-based with documented thresholds.
  Trade-off: transparent and tunable, but weights are hand-set rather than learned.
- **Monthly granularity.** Signals use monthly aggregates; intra-month deterioration
  isn't modelled. Sufficient for a 30-day early-warning horizon.
- **In-memory, batch-at-startup.** No DB or streaming; scores recompute on launch.
  Production would use scheduled batch scoring (noted in §8).
- **Mock auth.** Identity is trusted from headers; real deployment needs proper token
  verification (§7).
- **Bonus features implemented** — risk-trend visualization, EMI-miss scenario simulation,
  and a manager portfolio summary (see §3). All three reuse the deterministic scoring core,
  so they add no new risk heuristics and stay fully auditable. Trade-off: trend and
  simulation re-score on demand (cheap for this in-memory dataset; in production the trend
  would read pre-computed historical scores from the scoring batch rather than replaying).
- **Trend is monthly, simulation is single-cycle.** The trend uses the same monthly
  aggregates as scoring; the what-if models exactly one missed EMI (a 30-day cycle), which
  matches the early-warning horizon — multi-cycle cascades are out of scope.
