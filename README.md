# MiniPay: POS-to-Payments Platform

> **Purpose of this document:** This README is the single source of truth for building MiniPay. It contains the scope, architecture, data model, API contracts, conventions and a **phase-wise execution plan** with commands and acceptance criteria. Hand it to yourself (or to an AI coding assistant) as context at the start of every work session.

**Timeline:** 4 weeks (28 days), about 2–3 hrs/day.
**Language:** Python 3.12.
**Goal:** A small but credible payments backend that demonstrates the skills in the Pine Labs *Software Engineer* job description: REST APIs, MQTT, WebSockets, multithreading, OOP and design patterns, Docker, Kubernetes, cloud, Git, and MCP / AI-assisted engineering.

> **Safety rule:** MiniPay uses **fake data only**. Never store or process real card numbers. The "acquirer" (payment processor) is a mock. Say this in the final README.

---

## Table of Contents

1. [Scope](#1-scope)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Repository Layout](#4-repository-layout)
5. [Conventions](#5-conventions)
6. [Domain Design](#6-domain-design)
7. [Data Model](#7-data-model)
8. [API Contract](#8-api-contract)
9. [MQTT Contract](#9-mqtt-contract)
10. [WebSocket Contract](#10-websocket-contract)
11. [Webhook Contract](#11-webhook-contract)
12. [Configuration](#12-configuration)
13. [Phased Execution Plan](#13-phased-execution-plan)
14. [Testing Strategy](#14-testing-strategy)
15. [Deployment](#15-deployment)
16. [Cut Order If Behind Schedule](#16-cut-order-if-behind-schedule)
17. [Interview Preparation](#17-interview-preparation)
18. [Resume Entry Template](#18-resume-entry-template)
19. [Definition of Done](#19-definition-of-done)

---

## 1. Scope

### In scope (mapped to the job description)

| JD requirement | How MiniPay covers it |
|---|---|
| REST APIs | FastAPI Payment API (create, capture, refund, query) |
| MQTT | POS simulator publishes → Mosquitto → ingestion service |
| WebSockets | Live merchant dashboard feed |
| Multithreading | Webhook worker using a thread pool; ingestion worker threads |
| OOP + design patterns | State, Strategy, Repository (+ Factory for config-driven acquirer) |
| Data structures / algorithms | Exponential backoff with jitter, cursor pagination, hashing for idempotency |
| Docker | Docker Compose for the whole system |
| Kubernetes | Minimal manifests, run on kind/minikube |
| Cloud (AWS/Azure/GCP) | Single VM deployment with Docker Compose |
| Git | Feature branches, small commits, CI |
| MCP + AI-assisted tools | Small read-only MCP server; documented use of AI coding tools |

### Out of scope (list under "Future work" in the final README)

Real card data or real acquirers, partial refunds, double-entry ledger, Redis, multi-instance WebSocket fan-out, fraud ML scoring, Alembic migrations (use `create_all`), user/merchant auth beyond a shared API key, frontend frameworks, load-test suites.

---

## 2. Architecture

### 2.1 Component overview

```
                         ┌────────────────────┐
                         │   POS Simulator    │  N fake terminals
                         └─────────┬──────────┘
                                   │ MQTT publish (QoS 1)
                                   ▼
                         ┌────────────────────┐
                         │ Mosquitto (broker) │
                         └─────────┬──────────┘
                                   │ subscribe  pos/+/+/txn
                                   ▼
                         ┌────────────────────┐
                         │ Ingestion Service  │  validates, then calls API
                         │ (queue + threads)  │  with Idempotency-Key = event_id
                         └─────────┬──────────┘
                                   │ HTTP POST /v1/payments
                                   ▼
┌──────────────┐  REST   ┌────────────────────┐   SQL    ┌──────────────┐
│ Dashboard    │◄───────►│   Payment API      │◄────────►│  PostgreSQL  │
│ (HTML + JS)  │  WS     │   (FastAPI)        │          │              │
└──────────────┘◄────────│ state machine,     │          └──────▲───────┘
                         │ idempotency, WS    │                 │
                         └─────────┬──────────┘                 │ poll outbox
                                   │ writes outbox rows         │ (SKIP LOCKED)
                                   └───────────────────►┌───────┴────────┐
                                                        │ Webhook Worker │
┌──────────────┐  stdio/HTTP read-only                  │ (thread pool,  │
│ MCP Server   │───────────────► Payment API            │  retry/backoff)│
└──────────────┘                                        └───────┬────────┘
                                                                │ HTTPS POST (HMAC signed)
                                                                ▼
                                                        Merchant webhook endpoint
                                                        (tools/webhook_sink.py in dev)
```

### 2.2 Services

| Service | Responsibility | Process |
|---|---|---|
| **payment_api** | REST endpoints, state machine, idempotency, WebSocket broadcast, serves dashboard | `uvicorn minipay.api.main:app` |
| **ingestion** | Subscribes to MQTT, validates events, calls the API | `python -m minipay.ingestion.main` |
| **webhook_worker** | Polls the outbox table, delivers signed webhooks with retries | `python -m minipay.worker.main` |
| **pos_simulator** | Publishes fake terminal transactions | `python -m minipay.simulator.main` |
| **mcp_server** | Exposes read-only payment tools to AI assistants | `python -m minipay.mcp_server.server` |
| **postgres** | System of record | container |
| **mosquitto** | MQTT broker | container |

All Python services share **one package** (`minipay`) and **one Dockerfile**. Each service runs with a different command.

### 2.3 Key flows

**Flow A: A POS sale:**

```mermaid
sequenceDiagram
    participant T as POS Simulator
    participant B as Mosquitto
    participant I as Ingestion
    participant A as Payment API
    participant D as PostgreSQL
    participant W as WebSocket clients

    T->>B: PUBLISH pos/m_001/t_07/txn (QoS 1, event_id=E1)
    B->>I: deliver message
    I->>A: POST /v1/payments  (Idempotency-Key: E1)
    A->>D: insert idempotency row (in_progress)
    A->>D: insert payment (CREATED)
    A->>A: acquirer.authorize() → approve / decline
    A->>D: update status, insert payment_event, insert webhook_delivery (same txn)
    A->>D: store idempotent response, commit
    A-->>W: broadcast payment.updated (after commit)
    A-->>I: 201 Created
```

**Flow B: Webhook delivery (outbox pattern):**

```mermaid
sequenceDiagram
    participant A as Payment API
    participant D as PostgreSQL
    participant K as Webhook Worker
    participant M as Merchant endpoint

    A->>D: status change + outbox row (one transaction)
    loop every 1s
        K->>D: SELECT ... FOR UPDATE SKIP LOCKED (due rows)
        K->>D: mark IN_FLIGHT
        K->>M: POST signed payload (thread pool)
        alt 2xx
            K->>D: mark DELIVERED
        else failure
            K->>D: attempts+1, next_attempt_at = backoff+jitter (or DEAD)
        end
    end
```

### 2.4 Key design decisions (be ready to defend these)

| Decision | Reason | Trade-off |
|---|---|---|
| **Idempotency keys** on payment creation | Retries and duplicate MQTT delivery are normal; a retry must never double-charge | Extra table and request-hash comparison |
| **Ingestion uses `event_id` as the idempotency key** | MQTT QoS 1 is at-least-once, so duplicates will occur; this gives free deduplication | Depends on terminals generating unique IDs |
| **Outbox pattern** for webhooks | Status change and "to-be-sent" webhook commit atomically; no lost or phantom webhooks | Polling latency (about 1s) |
| **`FOR UPDATE SKIP LOCKED`** claiming | Lets multiple workers run without double-delivering | Needs Postgres |
| **State machine in domain layer** | Illegal transitions are impossible by construction | More code than `if` statements |
| **Money as integer minor units** | Avoids floating-point errors | Needs formatting at the edge |
| **Sync SQLAlchemy + threads** | Simpler to reason about; threads suit I/O-bound work | Bridge to async needed for WebSocket broadcast |
| **In-process WebSocket fan-out** | Avoids Redis | API must run as a single instance (documented limitation) |

---

## 3. Tech Stack

| Area | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| DB | PostgreSQL 16, SQLAlchemy 2.0 (sync), psycopg 3 |
| Messaging | Mosquitto 2.x, `paho-mqtt` 2.x |
| HTTP client | `httpx` |
| Concurrency | `threading`, `concurrent.futures.ThreadPoolExecutor`, `queue.Queue` |
| MCP | official `mcp` Python SDK (FastMCP) |
| Testing | pytest, pytest-cov, `httpx`/FastAPI `TestClient` |
| Lint/format | ruff |
| Containers | Docker, Docker Compose |
| Orchestration | Kubernetes (kind or minikube) |
| CI | GitHub Actions |
| Cloud | AWS EC2 (or any VM) |

---

## 4. Repository Layout

```
minipay/
├── src/minipay/
│   ├── core/
│   │   ├── config.py            # pydantic-settings
│   │   ├── db.py                # engine, SessionLocal, get_session
│   │   └── logging.py           # structured logging setup
│   ├── domain/
│   │   ├── models.py            # SQLAlchemy ORM models
│   │   ├── state.py             # PaymentStatus + State pattern
│   │   ├── acquirer.py          # Acquirer interface + MockAcquirer (Strategy)
│   │   ├── schemas.py           # Pydantic request/response models
│   │   └── events.py            # MQTT event schema (shared by simulator + ingestion)
│   ├── repositories/
│   │   ├── payments.py
│   │   ├── idempotency.py
│   │   ├── webhooks.py
│   │   └── merchants.py
│   ├── services/
│   │   ├── payment_service.py   # orchestration: create/capture/refund
│   │   ├── idempotency.py       # hashing + replay logic
│   │   └── signing.py           # HMAC signing/verification
│   ├── api/
│   │   ├── main.py              # app factory, startup
│   │   ├── deps.py              # auth, session dependencies
│   │   ├── ws_manager.py        # ConnectionManager (WebSocket fan-out)
│   │   ├── routers/ (payments.py, merchants.py, health.py, ws.py)
│   │   └── static/index.html    # dashboard
│   ├── ingestion/main.py
│   ├── worker/ (main.py, delivery.py, backoff.py)
│   ├── simulator/main.py
│   └── mcp_server/server.py
├── tools/
│   ├── seed.py                  # create demo merchants
│   ├── webhook_sink.py          # local webhook receiver with failure toggle
│   └── smoke.py                 # end-to-end smoke check + simple timing
├── tests/ (unit/, integration/, e2e/)
├── deploy/
│   ├── docker-compose.yml
│   ├── mosquitto/mosquitto.conf
│   └── k8s/ (namespace.yaml, configmap.yaml, secret.yaml, api.yaml, ingestion.yaml, worker.yaml, mosquitto.yaml, postgres.yaml)
├── .github/workflows/ci.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 5. Conventions

- **Money:** integer `amount_minor` (e.g., paise/cents) plus ISO-4217 `currency`. Never use floats.
- **IDs:** UUID v4 for payments/deliveries; merchants use readable IDs (`m_001`).
- **Time:** timezone-aware UTC everywhere; ISO-8601 in JSON.
- **Layering:** routers → services → repositories → models. Routers contain no business logic; repositories contain no business rules.
- **Transactions:** one DB transaction per use case. Broadcast WebSocket messages **after** commit.
- **Errors:** domain exceptions (`IllegalTransition`, `IdempotencyConflict`, `NotFound`) mapped to HTTP codes in one place.
- **Logging:** JSON logs with `payment_id`, `event_id`, `idempotency_key` where available. Never log secrets.
- **Git:** branch per phase (`phase-1-core`, …); small commits with clear messages (`feat:`, `test:`, `fix:`, `docs:`, `chore:`). Merge to `main` only when the phase's acceptance criteria pass.
- **Tests:** every phase ends with passing tests. Target ≥ 80% coverage on `domain/`, `services/` and `repositories/`.
- **AI tools:** if you use AI coding assistants, record in the final README what you used them for and what you verified. You must be able to explain every file.

---

## 6. Domain Design

### 6.1 Payment state machine (State pattern)

```
CREATED ──authorize ok──► AUTHORIZED ──capture ok──► CAPTURED ──refund──► REFUNDED
   │                          │
   └──decline──► FAILED ◄─────┘ (acquirer failure on capture)
```

| From | Allowed actions | To |
|---|---|---|
| CREATED | authorize (approve) | AUTHORIZED |
| CREATED | authorize (decline/timeout) | FAILED |
| AUTHORIZED | capture (ok) | CAPTURED |
| AUTHORIZED | capture (acquirer error) | FAILED |
| CAPTURED | refund | REFUNDED |
| FAILED, REFUNDED | none (terminal) | n/a |

Anything else raises `IllegalTransition` → HTTP 409.

Implementation shape: an abstract `PaymentState` with `authorize()`, `capture()`, `refund()`; one concrete class per status; each method either returns the next status or raises `IllegalTransition`. A factory maps `PaymentStatus → PaymentState`.

### 6.2 Acquirer (Strategy pattern)

```python
class Acquirer(Protocol):
    def authorize(self, amount_minor: int, currency: str, card_last4: str) -> AcquirerResult: ...
    def capture(self, payment_id: str) -> AcquirerResult: ...
    def refund(self, payment_id: str) -> AcquirerResult: ...
```

`MockAcquirer` is **deterministic via magic card endings** (like payment-provider test cards), so tests are reliable:

| `card_last4` | Behavior |
|---|---|
| `4242` (default) | Approve |
| `0002` | Decline ("card_declined") |
| `0005` | Simulated timeout → treated as failure |
| `9995` | Approve authorization, fail capture |

An optional `MOCK_ACQUIRER_FAILURE_RATE` env var injects random failures for demos. A factory selects the acquirer from config.

### 6.3 Idempotency algorithm

For `POST /v1/payments` with header `Idempotency-Key: K` and body `B`:

1. `request_hash = sha256(canonical_json(B))`.
2. In one transaction, try `INSERT idempotency_keys (merchant_id, key, request_hash, state='IN_PROGRESS')`.
3. **Insert succeeded** → process the payment, then update the row with `state='COMPLETED'`, `response_status`, `response_body`; commit.
4. **Unique violation** → read the existing row:
   - `request_hash` differs → **409** `idempotency_key_reused_with_different_payload`.
   - `state = COMPLETED` → **replay** the stored status and body with header `Idempotent-Replayed: true`.
   - `state = IN_PROGRESS` → **409** `request_in_progress` (client may retry shortly).
5. Rows older than 24h may be purged (optional).

Because the insert and the payment creation share one transaction, a crash cannot leave a "completed" key without a payment.

---

## 7. Data Model

```
merchants(
  id text PK,                    -- 'm_001'
  name text not null,
  webhook_url text null,
  webhook_secret text not null,
  created_at timestamptz
)

payments(
  id uuid PK,
  merchant_id text FK → merchants.id,
  amount_minor bigint not null check (amount_minor > 0),
  currency char(3) not null,
  status text not null,          -- CREATED/AUTHORIZED/CAPTURED/REFUNDED/FAILED
  card_last4 char(4) not null,
  terminal_id text null,
  source_event_id text null unique,  -- from MQTT event, if any
  failure_reason text null,
  version int not null default 1,    -- optimistic lock
  created_at timestamptz,
  updated_at timestamptz
)
INDEX payments(merchant_id, created_at desc)
INDEX payments(merchant_id, status)

payment_events(                  -- audit trail of transitions
  id bigserial PK,
  payment_id uuid FK,
  from_status text null,
  to_status text not null,
  created_at timestamptz
)

idempotency_keys(
  id bigserial PK,
  merchant_id text not null,
  key text not null,
  request_hash text not null,
  state text not null,           -- IN_PROGRESS / COMPLETED
  response_status int null,
  response_body jsonb null,
  created_at timestamptz,
  UNIQUE (merchant_id, key)
)

webhook_deliveries(              -- outbox
  id uuid PK,
  payment_id uuid FK,
  merchant_id text not null,
  event_type text not null,      -- payment.authorized / captured / refunded / failed
  payload jsonb not null,
  status text not null,          -- PENDING / IN_FLIGHT / DELIVERED / DEAD
  attempts int not null default 0,
  next_attempt_at timestamptz not null,
  locked_at timestamptz null,
  last_status_code int null,
  last_error text null,
  created_at timestamptz,
  delivered_at timestamptz null
)
INDEX webhook_deliveries(status, next_attempt_at)
```

Use `Base.metadata.create_all()` at API startup (no Alembic). Seed merchants with `tools/seed.py`.

---

## 8. API Contract

**Auth:** header `X-API-Key: <API_KEY>` on all `/v1/*` routes (single shared key, a documented simplification).
**Base path:** `/v1`. **Docs:** `/docs` (Swagger UI).

| Method | Path | Description |
|---|---|---|
| POST | `/v1/payments` | Create and authorize a payment. **Requires** `Idempotency-Key`. |
| GET | `/v1/payments/{id}` | Fetch one payment |
| GET | `/v1/payments` | List: `merchant_id`, `status`, `limit` (≤100), `cursor` |
| POST | `/v1/payments/{id}/capture` | Capture an AUTHORIZED payment |
| POST | `/v1/payments/{id}/refund` | Full refund of a CAPTURED payment |
| GET | `/v1/merchants/{id}/summary` | Counts by status and total captured amount |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (checks DB) |
| WS | `/ws/payments?merchant_id=` | Live updates |
| GET | `/` | Dashboard (static HTML) |

### Create payment

Request:
```json
{
  "merchant_id": "m_001",
  "amount_minor": 49900,
  "currency": "INR",
  "card_last4": "4242",
  "terminal_id": "t_07",
  "source_event_id": "e3b0c442-..."
}
```

Response `201`:
```json
{
  "id": "0b8f...",
  "merchant_id": "m_001",
  "amount_minor": 49900,
  "currency": "INR",
  "status": "AUTHORIZED",
  "terminal_id": "t_07",
  "failure_reason": null,
  "created_at": "2026-01-01T10:00:00Z",
  "updated_at": "2026-01-01T10:00:00Z"
}
```

A declined payment still returns `201` with `"status": "FAILED"` and a `failure_reason`. The request succeeded; the payment did not.

### Error format

```json
{ "error": { "code": "illegal_transition", "message": "Cannot capture a payment in status FAILED" } }
```

| Status | Codes |
|---|---|
| 400 | `missing_idempotency_key`, `validation_error` |
| 401 | `invalid_api_key` |
| 404 | `payment_not_found`, `merchant_not_found` |
| 409 | `illegal_transition`, `idempotency_key_reused_with_different_payload`, `request_in_progress` |

Capture and refund are also safe to retry: repeating `capture` on an already CAPTURED payment returns the current payment (no-op, 200); repeating on an incompatible state returns 409.

---

## 9. MQTT Contract

- **Broker:** Mosquitto, port 1883 (dev: anonymous; do **not** expose publicly).
- **Topic:** `pos/{merchant_id}/{terminal_id}/txn`
- **Subscriber pattern:** `pos/+/+/txn`
- **QoS:** 1 (at-least-once, so duplicates are possible and expected).
- **Optional status topic:** `pos/{merchant_id}/{terminal_id}/status` (`online`/`offline`; set as MQTT last-will by the simulator).

Payload:
```json
{
  "event_id": "uuid-v4",
  "merchant_id": "m_001",
  "terminal_id": "t_07",
  "amount_minor": 49900,
  "currency": "INR",
  "card_last4": "4242",
  "occurred_at": "2026-01-01T10:00:00Z"
}
```

Ingestion rules:
1. Validate with the shared Pydantic model. Invalid messages are logged and dropped (counted).
2. Enqueue into a bounded `queue.Queue`; worker threads POST to `/v1/payments` with `Idempotency-Key: <event_id>` and `source_event_id: <event_id>`.
3. On HTTP 5xx or network error: retry with backoff (max N attempts), then log as failed.
4. A duplicate message yields a replayed response, so no double payment.
5. Auto-reconnect with backoff on broker disconnect; re-subscribe in `on_connect`.

---

## 10. WebSocket Contract

- **Endpoint:** `ws://host/ws/payments?merchant_id=m_001` (omit `merchant_id` for all).
- **Server → client message:**
```json
{ "type": "payment.updated", "data": { "id": "...", "status": "CAPTURED", "amount_minor": 49900, "currency": "INR", "merchant_id": "m_001", "terminal_id": "t_07", "updated_at": "..." } }
```
- **Heartbeat:** server sends `{"type":"ping"}` every 20s; client ignores it.
- **Client behavior:** on close, reconnect with exponential backoff (1s → 2s → 4s … max 30s); on reconnect, refetch `GET /v1/payments?limit=50` to fill any gap.
- **Implementation note:** DB-facing endpoints are synchronous (run in FastAPI's threadpool). To broadcast from a sync endpoint, use `anyio.from_thread.run(manager.broadcast, message)` **after** the transaction commits.

---

## 11. Webhook Contract

Event types: `payment.authorized`, `payment.captured`, `payment.refunded`, `payment.failed`.

Request from worker to merchant:
```
POST {merchant.webhook_url}
Content-Type: application/json
X-MiniPay-Event: payment.captured
X-MiniPay-Delivery-Id: <uuid>
X-MiniPay-Signature: t=<unix_ts>,v1=<hex>
```
Signature: `hex(HMAC_SHA256(webhook_secret, f"{t}.{raw_body}"))`. Receivers should reject timestamps older than 5 minutes.

Retry policy:
- Success = any 2xx. Timeout per attempt = 5s.
- `delay = min(base * 2^(attempt-1), cap)` with **full jitter** (`random(0, delay)`); `base=2s`, `cap=300s`, `max_attempts=6`.
- After max attempts, status becomes `DEAD` (visible in the DB for manual replay).
- Rows stuck `IN_FLIGHT` with `locked_at` older than 60s are reclaimed (worker crash recovery).

---

## 12. Configuration

All via environment variables (`.env.example` in the repo, loaded with pydantic-settings).

| Variable | Default | Used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://minipay:minipay@postgres:5432/minipay` | api, worker |
| `API_KEY` | `dev-key-change-me` | api, ingestion, mcp |
| `API_BASE_URL` | `http://api:8000` | ingestion, mcp |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | ingestion, simulator |
| `INGESTION_WORKERS` | `4` | ingestion |
| `INGESTION_QUEUE_SIZE` | `1000` | ingestion |
| `WEBHOOK_WORKERS` | `8` | worker |
| `WEBHOOK_POLL_INTERVAL_S` | `1` | worker |
| `WEBHOOK_MAX_ATTEMPTS` | `6` | worker |
| `WEBHOOK_TIMEOUT_S` | `5` | worker |
| `ACQUIRER` | `mock` | api |
| `MOCK_ACQUIRER_FAILURE_RATE` | `0.0` | api |
| `SIM_TERMINALS` | `5` | simulator |
| `SIM_RATE_PER_TERMINAL` | `1.0` (events/s) | simulator |
| `LOG_LEVEL` | `INFO` | all |

---

## 13. Phased Execution Plan

Each phase lists **tasks**, **commands**, **deliverables** and **acceptance criteria**. Do not start a phase until the previous one's acceptance criteria pass. Work on a branch per phase and merge to `main` when done.

### Phase 0: Project Setup (Day 1)

**Tasks**
- [ ] Create the GitHub repo, clone it, and add `.gitignore` (Python), `LICENSE` and this README.
- [ ] Create the folder structure from [§4](#4-repository-layout) with empty `__init__.py` files.
- [ ] `pyproject.toml`: dependencies (`fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg[binary]`, `pydantic-settings`, `httpx`, `paho-mqtt`, `mcp`) and dev dependencies (`pytest`, `pytest-cov`, `ruff`).
- [ ] `core/config.py` (settings), `core/db.py` (engine and session), `core/logging.py`.
- [ ] `deploy/docker-compose.yml` with only `postgres` for now; `Makefile` with `up`, `down`, `test`, `lint`, `run-api`.
- [ ] `.env.example`.

**Commands**
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose -f deploy/docker-compose.yml up -d postgres
ruff check . && pytest
```

**Acceptance criteria**
- `pytest` runs (even with one trivial test) and `ruff` passes.
- Python can connect to the Postgres container.
- First commit pushed to GitHub.

---

### Phase 1: Payment Domain and API Core (Days 2–7)

**Tasks**
- [ ] ORM models for `merchants`, `payments`, `payment_events` ([§7](#7-data-model)); `create_all` on startup; `tools/seed.py` creating `m_001`, `m_002`.
- [ ] `domain/state.py`: `PaymentStatus` enum, the State classes, and `IllegalTransition`. **Write unit tests first** for every row of the transition table.
- [ ] `domain/acquirer.py`: `Acquirer` protocol, `MockAcquirer` with magic card endings, and a factory.
- [ ] Repositories: `PaymentRepository` (add, get, list with cursor pagination, update with optimistic version check), `MerchantRepository`.
- [ ] `services/payment_service.py`: `create_payment` (insert CREATED → authorize → set AUTHORIZED/FAILED → write `payment_events`), `capture`, `refund`. One transaction per call.
- [ ] Pydantic schemas and routers: create, get, list, capture, refund, summary, `/health`, `/ready`.
- [ ] API-key dependency and the central exception → error-JSON mapping.
- [ ] Tests: unit tests for state and acquirer; integration tests (TestClient + real Postgres) for each endpoint and for illegal transitions returning 409.

**Commands**
```bash
python tools/seed.py
uvicorn minipay.api.main:app --reload
pytest tests/unit tests/integration -q --cov=src/minipay
# demo via Swagger UI at http://localhost:8000/docs
```

**Deliverables:** working REST API, state machine and acquirer strategy.

**Acceptance criteria**
- Create → capture → refund works in Swagger UI.
- Every illegal transition returns 409; magic card endings produce the documented outcomes.
- Coverage ≥ 80% on `domain/` and `services/`.

---

### Phase 2: Idempotency and Concurrency Safety (Days 8–9)

**Tasks**
- [ ] `idempotency_keys` model and repository; `services/idempotency.py` implementing the algorithm in [§6.3](#63-idempotency-algorithm) (canonical JSON, SHA-256, insert-first, unique-violation handling).
- [ ] Require `Idempotency-Key` on `POST /v1/payments` (400 if missing); add `Idempotent-Replayed: true` header on replays.
- [ ] Make capture/refund retry-safe (no-op when already in the target state).
- [ ] **Concurrency test:** fire ~50 parallel requests (`ThreadPoolExecutor` with `httpx`) using the same key and body → assert exactly **one** payment row, and all responses identical. Add a second test: same key with a different body → 409.
- [ ] Optimistic locking: concurrent capture requests on one payment result in one success and the rest as no-op or 409, never a double transition.

**Acceptance criteria**
- The concurrency test passes consistently (run it 10 times in a loop).
- Replays return identical status and body.
- You can explain, without notes, why insert-first plus a unique constraint is safe.

---

### Phase 3: MQTT Pipeline (Days 10–13)

**Tasks**
- [ ] `deploy/mosquitto/mosquitto.conf` (`listener 1883`, `allow_anonymous true` for dev) and a `mosquitto` service in Compose.
- [ ] `domain/events.py`: shared Pydantic `TxnEvent` model ([§9](#9-mqtt-contract)).
- [ ] `simulator/main.py`: spawn `SIM_TERMINALS` threads; each publishes events at `SIM_RATE_PER_TERMINAL` with QoS 1, random amounts, a mix of card endings (mostly `4242`, some `0002`); optional last-will status message. Add a flag to **re-publish a duplicate** of the previous event (to demonstrate dedupe).
- [ ] `ingestion/main.py`: connect, subscribe to `pos/+/+/txn`, validate, push to a bounded queue; N worker threads POST to the API with `Idempotency-Key = event_id`; retry on 5xx/network errors; handle reconnects; count processed/duplicate/invalid.
- [ ] Add `tools/smoke.py`: publish one event, poll the API, assert the payment exists.
- [ ] Tests: unit tests for event validation; an integration test publishing a duplicate event twice and asserting one payment.

**Commands**
```bash
docker compose -f deploy/docker-compose.yml up -d postgres mosquitto
uvicorn minipay.api.main:app &
python -m minipay.ingestion.main &
python -m minipay.simulator.main
mosquitto_sub -h localhost -t 'pos/#' -v     # optional inspection
```

**Acceptance criteria**
- Running the simulator creates payments through the API.
- Sending the same `event_id` twice yields exactly one payment.
- Killing and restarting Mosquitto: ingestion reconnects and resumes without manual action.

---

### Phase 4: WebSocket Live Dashboard (Days 14–15)

**Tasks**
- [ ] `api/ws_manager.py`: `ConnectionManager` with connect/disconnect, optional per-merchant subscriptions, and `broadcast`.
- [ ] `routers/ws.py` at `/ws/payments`, with a 20s ping.
- [ ] After each successful commit in create/capture/refund, broadcast `payment.updated` (use `anyio.from_thread.run` from sync endpoints).
- [ ] `api/static/index.html`: plain HTML + vanilla JS: a merchant selector, counters (total/authorized/captured/failed from `/summary`), a live table of the latest 50 payments, and a connection status indicator. Reconnect with exponential backoff and refetch on reconnect.
- [ ] Serve static files at `/`.
- [ ] Test: WebSocket integration test using TestClient's `websocket_connect`: create a payment and assert the message arrives.

**Acceptance criteria**
- With the simulator running, rows appear in the browser in real time without refresh.
- Stopping and restarting the API: the page reconnects automatically and shows current data.
- Disconnected clients do not crash broadcasting (handle exceptions per connection).

---

### Phase 5: Webhook Worker, Multithreading and the Outbox (Days 16–19)

**Tasks**
- [ ] `webhook_deliveries` model and repository. In the same transaction as each status change, insert an outbox row (only if the merchant has a `webhook_url`).
- [ ] `services/signing.py`: `sign(secret, timestamp, body)` and `verify(...)`, with unit tests (including tamper and stale-timestamp cases).
- [ ] `worker/backoff.py`: `compute_delay(attempt, base, cap)` with full jitter, with unit tests (bounds, monotonic cap).
- [ ] `worker/main.py`: loop every `WEBHOOK_POLL_INTERVAL_S`: in one transaction `SELECT … WHERE status IN ('PENDING') AND next_attempt_at <= now() … FOR UPDATE SKIP LOCKED LIMIT batch`, mark `IN_FLIGHT` with `locked_at`, commit; submit each row to a `ThreadPoolExecutor(WEBHOOK_WORKERS)`.
- [ ] `worker/delivery.py`: send the signed POST (timeout 5s). On 2xx → `DELIVERED`. Otherwise increment attempts, record error and status code, and set `next_attempt_at` (or `DEAD` after max attempts). Each thread uses its **own** DB session.
- [ ] Reclaim stale `IN_FLIGHT` rows (older than 60s).
- [ ] Graceful shutdown on SIGTERM: stop polling, wait for in-flight tasks.
- [ ] `tools/webhook_sink.py`: tiny FastAPI receiver that verifies signatures and has a switch (`/fail?on=true`) to return 500.
- [ ] Tests: integration tests against the sink: success path; failing endpoint → retries then recovers; permanently failing → `DEAD`; two workers running concurrently never deliver the same row twice.

**Commands**
```bash
python tools/webhook_sink.py &          # port 9000
python -m minipay.worker.main
# set m_001.webhook_url=http://localhost:9000/hook via tools/seed.py
```

**Acceptance criteria**
- Every status change produces exactly one delivery per event; signatures verify at the sink.
- Toggling the sink to fail shows retries with growing delays in logs, and delivery succeeds after the toggle is released.
- You can explain how the worker would scale to multiple instances (`SKIP LOCKED`) and why the GIL does not hurt here (I/O-bound).

---

### Phase 6: Containerization, CI and Cloud (Days 20–23)

**Tasks**
- [ ] `Dockerfile` (python:3.12-slim, install package, non-root user). One image, different commands per service.
- [ ] Extend `docker-compose.yml`: `postgres` (with healthcheck and volume), `mosquitto`, `api`, `ingestion`, `webhook-worker`, and profile `demo` for `simulator` and `webhook-sink`. Use `depends_on` with health conditions. Add a startup script or init step that runs `seed.py`.
- [ ] `.github/workflows/ci.yml`: on push/PR: set up Python, start a Postgres service container, `ruff check`, `pytest --cov`, then `docker build`.
- [ ] Provision an AWS EC2 instance (or similar VM): install Docker, clone the repo, `docker compose up -d`. Open **only** the API port (and 22 for SSH) in the security group; keep Postgres and Mosquitto internal. Set a real `API_KEY` and `webhook_secret`. Add swap space if memory is tight.
- [ ] Verify the public URL shows the live dashboard with the simulator running.

**Commands**
```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml --profile demo up -d
docker compose logs -f api ingestion webhook-worker
```

**Acceptance criteria**
- One command brings up the whole system locally.
- CI is green on `main`, with a coverage figure.
- Public demo URL works; record a 60–90s screen capture as a fallback.

---

### Phase 7: MCP Server (Day 24)

**Tasks**
- [ ] `mcp_server/server.py` using FastMCP with **read-only** tools that call the Payment API over HTTP (not the DB directly):
  - `list_failed_payments(merchant_id, limit=20)`
  - `get_payment_status(payment_id)`
  - `get_merchant_summary(merchant_id)`
- [ ] Clear tool descriptions and typed parameters; return concise JSON.
- [ ] Do **not** expose refund or capture. Document in the README why (an AI agent should not move money without a human confirmation step).
- [ ] Connect to an MCP client (e.g., Claude Desktop config) and capture a short demo screenshot or GIF.

**Acceptance criteria**
- The client lists the three tools and answers "which payments failed for m_001 today?" using live data.
- The README explains the read-only design choice.

---

### Phase 8: Kubernetes Manifests (Days 25–26)

**Tasks**
- [ ] `deploy/k8s/`: `namespace.yaml`, `configmap.yaml` (non-secret env), `secret.yaml` (API key, DB password, webhook secret; placeholders only, never commit real secrets), Deployments and Services for `api`, `ingestion`, `webhook-worker`, `mosquitto`, and a minimal `postgres` (Deployment + PVC or `emptyDir` for the demo).
- [ ] API: liveness `/health`, readiness `/ready`, resource requests/limits, and `replicas: 1` (the single-instance WebSocket limitation).
- [ ] Load the image into the cluster and apply.

**Commands**
```bash
kind create cluster --name minipay
docker build -t minipay:local .
kind load docker-image minipay:local --name minipay
kubectl apply -f deploy/k8s/
kubectl -n minipay get pods
kubectl -n minipay port-forward svc/api 8000:8000
```

**Acceptance criteria**
- All pods reach `Running`/`Ready`; the dashboard works through port-forward with the simulator running.
- Keep screenshots of `kubectl get pods`. **Only list Kubernetes on the resume if this phase actually ran.**

---

### Phase 9: Documentation, Measurement and Interview Prep (Days 27–28)

**Tasks**
- [ ] Replace this planning README with a final README (keep this plan as `docs/PLAN.md`): one-paragraph pitch, architecture diagram, 5-minute quickstart, features, demo GIF/link, design decisions and trade-offs ([§2.4](#24-key-design-decisions-be-ready-to-defend-these)), **known limitations** (single-instance WebSocket, mocked acquirer, shared API key, no migrations, no real card data), future work, AI-tool disclosure.
- [ ] Measurement: use `tools/smoke.py` to send N payments (e.g., 500) with a small thread pool and report requests/s and p50/p95 latency **on your machine, with specs stated**. Do not exaggerate.
- [ ] Record the final coverage number and add CI/coverage badges.
- [ ] Tidy: remove dead code, check `.env.example`, ensure no secrets in git history.
- [ ] Rehearse the interview questions in [§17](#17-interview-preparation) out loud. Fill in the resume template with **real** numbers.

**Acceptance criteria**
- A stranger can clone the repo, run `docker compose up`, and see the dashboard in under 5 minutes.
- Every number on your resume is traceable to a test, a CI run, or a measurement.

---

## 14. Testing Strategy

| Layer | What to test | Tools |
|---|---|---|
| Unit | State transitions, acquirer rules, idempotency hashing, signing, backoff, event validation | pytest |
| Integration | Endpoints with real Postgres, idempotency conflicts, outbox creation, worker delivery against the sink, WebSocket delivery | pytest, TestClient, httpx |
| Concurrency | 50 parallel same-key requests → 1 payment; two workers → no double delivery | `ThreadPoolExecutor` in tests |
| End-to-end | Simulator → MQTT → ingestion → API → WebSocket | `tools/smoke.py` |

Rules: no sleeps for synchronization where an event or polling-with-timeout works; tests clean up their data; CI runs the full suite against a Postgres service container.

---

## 15. Deployment

| Target | Notes |
|---|---|
| **Local** | `docker compose up -d --build` (add `--profile demo` for simulator and sink) |
| **Cloud VM** | EC2 or similar, Docker Compose, security group exposing only the API port; strong `API_KEY`; do not expose 1883 or 5432 |
| **Kubernetes** | kind/minikube, manifests in `deploy/k8s/`, single API replica |

Production-style gaps (state them honestly in the final README): no TLS termination (put Caddy/nginx in front for HTTPS), shared API key, anonymous MQTT, no migrations, single-instance WebSocket fan-out.

---

## 16. Cut Order If Behind Schedule

Cut from the top of this list first. **Never cut Phases 1–5.**

1. Kubernetes (Phase 8). Keep Docker Compose.
2. MCP server (Phase 7).
3. Cloud deployment. Use a recorded demo video instead.
4. MQTT last-will status topic and the duplicate-publish simulator flag (keep the dedupe test).
5. Cursor pagination (use simple `limit` only).

---

## 17. Interview Preparation

Be able to answer these from memory:

1. **Why idempotency keys?** Retries and at-least-once delivery are normal; a repeated request must not charge twice. Explain your insert-first and unique-constraint algorithm and the 409 cases.
2. **MQTT QoS 0/1/2?** What QoS 1 guarantees (at-least-once), why duplicates occur, and how `event_id` dedupes them.
3. **What is the outbox pattern?** Why the status change and the webhook record commit in one transaction; what could go wrong without it.
4. **How does `SKIP LOCKED` work?** How several workers claim different rows without blocking.
5. **Threads, the GIL and asyncio:** Why threads help for I/O-bound webhooks and ingestion; what you'd use for CPU-bound work (multiprocessing); why the DB layer is sync here and how the WebSocket broadcast bridges to the event loop.
6. **Design patterns used:** State (payment lifecycle), Strategy (acquirer), Repository (data access), Factory (acquirer selection). Show where each lives in the code.
7. **Failure scenarios:** the webhook endpoint is down; the DB commits but the client loses the response; a terminal reconnects and replays events; the worker crashes mid-delivery.
8. **Why integer minor units?** Floating-point errors.
9. **How would you scale this?** Multiple API replicas need a shared pub/sub (Redis) for WebSockets; run more workers (safe due to `SKIP LOCKED`); partition by merchant; add migrations, auth, TLS, observability.
10. **Why is the MCP server read-only?** Safety around AI agents moving money.
11. **Be honest about limitations.** Naming your project's weak points reads as maturity.

---

## 18. Resume Entry Template

Fill in only numbers you actually measured. Delete any line you did not build.

> **MiniPay: POS-to-Payments Platform** | Python, FastAPI, PostgreSQL, MQTT, WebSockets, Docker, Kubernetes, MCP | GitHub | Live
> - Built an idempotent payment REST API with a state-machine lifecycle (State, Strategy, Repository patterns); verified single-charge behavior under **[N]** concurrent duplicate requests.
> - Ingested events from **[N]** simulated POS terminals over MQTT (QoS 1) with deduplication and streamed live updates to a dashboard via WebSockets.
> - Implemented outbox-based, HMAC-signed webhook delivery with exponential-backoff retries on a thread pool; **[Z]%** test coverage, CI with GitHub Actions, deployed on **[cloud]** using Docker.
> - Exposed read-only payment queries to AI assistants through an MCP server.

---

## 19. Definition of Done

- [ ] Phases 1–6 acceptance criteria all pass; Phases 7–8 pass or are explicitly cut.
- [ ] `docker compose up` starts the full system; the dashboard shows live transactions from the simulator.
- [ ] CI green on `main`; coverage reported; no secrets in the repo.
- [ ] Final README includes: architecture diagram, quickstart, design decisions, limitations, future work, AI-tool disclosure.
- [ ] Demo link or recorded demo available.
- [ ] Every resume claim is backed by a test, a measurement or a running deployment.
- [ ] You can explain every file in the repo and every item in [§17](#17-interview-preparation).
