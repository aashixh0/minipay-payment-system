# MiniPay: Implemented Architecture & System Status

> **Document Purpose:** This document logs every implemented module, architecture pattern, database schema, API route, and test suite across completed phases. Any developer or AI assistant can use this document to start subsequent phases (e.g., Phase 2) immediately without reading the entire codebase.

---

## 📊 Phase Progress Summary

| Phase | Description | Status | Commit |
|---|---|---|---|
| **Phase 0** | Project Setup & Foundation Scaffold | ✅ Completed | `5dd0ef0` |
| **Phase 1** | Payment Domain & Core REST API | ✅ Completed | `9ed284c` |
| **Phase 2** | Idempotency & Concurrency Safety | ⏳ **Next Up** | Pending |
| **Phase 3** | MQTT POS Ingestion Pipeline | ⏹ Planned | Pending |
| **Phase 4** | Live WebSocket Merchant Dashboard | ⏹ Planned | Pending |
| **Phase 5** | Webhook Worker & Outbox Delivery | ⏹ Planned | Pending |
| **Phase 6** | Read-Only MCP Server & Deployment | ⏹ Planned | Pending |

---

## 🏗️ Directory & Codebase Structure

```
minipay/
├── deploy/
│   └── docker-compose.yml       # Postgres & Mosquitto container definitions
├── src/
│   └── minipay/
│       ├── core/
│       │   ├── config.py         # Pydantic-settings config (env-driven)
│       │   ├── db.py             # SQLAlchemy 2.0 engine, SessionLocal, get_session
│       │   └── logging.py        # Structured JSON logging
│       ├── domain/
│       │   ├── acquirer.py       # Acquirer Protocol & MockAcquirer (Strategy pattern)
│       │   ├── exceptions.py     # Domain exceptions (PaymentNotFound, IllegalTransition, etc.)
│       │   ├── models.py         # SQLAlchemy ORM models (merchants, payments, payment_events)
│       │   ├── schemas.py        # Pydantic v2 schemas (requests, responses, errors)
│       │   └── state.py          # Payment lifecycle State machine (State pattern)
│       ├── repositories/
│       │   ├── merchants.py      # MerchantRepository (DB read/write)
│       │   ├── payments.py       # PaymentRepository (cursor pagination, summary, status update)
│       │   ├── idempotency.py   # Stub for Phase 2
│       │   └── webhooks.py      # Stub for Phase 5
│       ├── services/
│       │   └── payment_service.py# PaymentService: transactional business logic
│       └── api/
│           ├── dependencies.py   # Auth (X-API-Key) & session injection
│           ├── main.py           # FastAPI app instance, error handlers, lifespan
│           └── routers/
│               ├── health.py     # /health & /ready
│               ├── merchants.py  # /v1/merchants/{id}/summary
│               └── payments.py   # /v1/payments (create, get, list, capture, refund)
├── tests/
│   ├── conftest.py               # In-memory SQLite session, TestClient, test fixtures
│   ├── unit/
│   │   ├── test_bootstrap.py     # Phase 0 bootstrap verification
│   │   ├── test_state.py         # State pattern transition table tests
│   │   ├── test_acquirer.py      # MockAcquirer magic cards & failure rate tests
│   │   └── test_services.py      # PaymentService unit tests
│   └── integration/
│       └── test_api.py           # End-to-end FastAPI endpoint integration tests
├── tools/
│   ├── seed.py                   # Seeds demo merchants (m_001, m_002)
│   ├── smoke.py                  # Integration test script (Phase 3)
│   └── webhook_sink.py           # Webhook receiver test server (Phase 5)
├── Makefile                      # up, down, restart, logs, test, lint, run-api, seed
├── pyproject.toml                # Project metadata, dependencies, tool configs
└── README.md                     # Master project specification
```

---

## ⚙️ Phase 0 Implementation Details

1. **Configuration (`src/minipay/core/config.py`)**:
   - `Settings` class built using `pydantic-settings.BaseSettings`.
   - Reads environment variables or `.env` with fallback defaults.
   - Singleton `settings` instance imported across all modules.

2. **Database Engine & Session (`src/minipay/core/db.py`)**:
   - Synchronous SQLAlchemy 2.0 with connection pooling (`pool_pre_ping=True`, `pool_size=10`).
   - `SessionLocal`: Session factory with `expire_on_commit=False`.
   - `Base`: Declarative ORM base.
   - `get_session()`: FastAPI dependency generator yielding transactional sessions.
   - `check_db_connection()`: Executes `SELECT 1` to verify connectivity for health probes.

3. **Structured Logging (`src/minipay/core/logging.py`)**:
   - Standard library logging configured with custom JSON formatter.
   - Output includes timestamp, level, message, logger name, and extra context fields (`payment_id`, `merchant_id`).

---

## 💳 Phase 1 Implementation Details

### 1. Data Models (`src/minipay/domain/models.py`)

- **`Merchant` (`merchants` table)**:
  - `id`: String Primary Key (e.g. `m_001`)
  - `name`: String
  - `webhook_url`: String (nullable)
  - `webhook_secret`: String (used for HMAC signing in Phase 5)
  - `created_at`: DateTime UTC timestamp
  - `payments`: Relationship to `Payment`

- **`Payment` (`payments` table)**:
  - `id`: UUID Primary Key (default: `uuid.uuid4`)
  - `merchant_id`: String FK to `merchants.id`
  - `amount_minor`: BigInteger (`CheckConstraint("amount_minor > 0")`)
  - `currency`: String(3) ISO-4217 currency code
  - `status`: String (`CREATED`, `AUTHORIZED`, `CAPTURED`, `REFUNDED`, `FAILED`)
  - `card_last4`: String(4)
  - `terminal_id`: String (nullable)
  - `source_event_id`: String unique (nullable, for MQTT deduplication)
  - `failure_reason`: Text (nullable)
  - `version`: Integer (default: 1, for optimistic locking)
  - `created_at` & `updated_at`: DateTime UTC timestamps
  - Indexes:
    - `ix_payments_merchant_created` (`merchant_id`, `created_at`)
    - `ix_payments_merchant_status` (`merchant_id`, `status`)
  - Relationships: `merchant`, `events` (cascade: delete-orphan)

- **`PaymentEvent` (`payment_events` table)**:
  - Immutable audit trail of every status transition.
  - `id`: BigInteger Primary Key autoincrement
  - `payment_id`: UUID FK to `payments.id`
  - `from_status`: String (nullable for initial creation)
  - `to_status`: String
  - `created_at`: DateTime UTC timestamp

### 2. State Machine Pattern (`src/minipay/domain/state.py`)

- State lifecycle diagram:
  ```
  CREATED ──authorize ok──► AUTHORIZED ──capture ok──► CAPTURED ──refund──► REFUNDED
     │                          │
     └──decline──► FAILED ◄─────┘  (acquirer failure on capture)
  ```
- **Enum:** `PaymentStatus` (`CREATED`, `AUTHORIZED`, `CAPTURED`, `REFUNDED`, `FAILED`).
- **Base State:** `PaymentState` abstract base class defining `authorize()`, `capture()`, `refund()`. Defaults raise `IllegalTransition`.
- **Concrete States:** `CreatedState`, `AuthorizedState`, `CapturedState`, `FailedState`, `RefundedState`.
- **Exception:** `IllegalTransition` with attributes `code = "illegal_transition"`, `status_code = 409`.
- **Factory:** `get_state(status: PaymentStatus) -> PaymentState` returns singleton instances.

### 3. Acquirer Strategy Pattern (`src/minipay/domain/acquirer.py`)

- **Protocol:** `Acquirer` defining `authorize()`, `capture()`, `refund()`.
- **`MockAcquirer`:** Deterministic mock driven by magic card endings:
  | `card_last4` | Authorization | Capture | Refund | Notes |
  |---|---|---|---|---|
  | `4242` | Approved | Approved | Approved | Standard test card |
  | `0002` | Declined | n/a | n/a | `failure_reason="card_declined"` |
  | `0005` | Failed | n/a | n/a | `failure_reason="timeout"` |
  | `9995` | Approved | Failed | n/a | `failure_reason="capture_failed"` |
- **Failure Injection:** `failure_rate` (0.0 to 1.0) for demoing random network errors.
- **Factory:** `get_acquirer()` selects implementation according to `settings.acquirer`.

### 4. Repositories Layer (`src/minipay/repositories/`)

- **`PaymentRepository` (`payments.py`)**:
  - `add(payment)`: Persists and flushes record.
  - `update_status(payment, new_status, failure_reason)`: Bumps optimistic lock `version`, updates `updated_at`, records `PaymentEvent`, and flushes within the active transaction.
  - `get(payment_id)`: Fetches payment by UUID or returns `None`.
  - `list_payments(merchant_id, status, limit, cursor)`: Cursor-based pagination sorted by `created_at desc, id desc`. Returns `(items, next_cursor)`.
  - `summary(merchant_id)`: Computes counts grouped by all `PaymentStatus` values and the sum of `amount_minor` for all `CAPTURED` payments.
- **`MerchantRepository` (`merchants.py`)**:
  - `get(merchant_id)`: Fetches merchant by ID.
  - `add(merchant)`: Persists merchant.

### 5. Service Layer (`src/minipay/services/payment_service.py`)

- **`PaymentService`**: Coordinates domain models, state machine, repositories, and acquirer calls in a single transaction per use case.
  - `create_payment(request)`: Validates merchant existence, creates `CREATED` payment, invokes `acquirer.authorize()`, transitions to `AUTHORIZED` or `FAILED`, logs `PaymentEvent`, commits, and returns payment. (Declined payments return 201 with status `FAILED`).
  - `capture_payment(payment_id)`: Idempotent no-op if already `CAPTURED`. If not `AUTHORIZED`, raises `IllegalTransition` (409). Otherwise invokes `acquirer.capture()`, transitions to `CAPTURED` (or `FAILED` on card `9995`), commits, and returns payment.
  - `refund_payment(payment_id)`: Idempotent no-op if already `REFUNDED`. If not `CAPTURED`, raises `IllegalTransition` (409). Otherwise invokes `acquirer.refund()`, transitions to `REFUNDED`, commits, and returns payment.
  - `get_payment(payment_id)`: Returns payment or raises `PaymentNotFoundError` (404).
  - `list_payments(merchant_id, status, limit, cursor)`: Validates merchant and fetches paginated items.
  - `get_merchant_summary(merchant_id)`: Returns breakdown dictionary and total captured minor amount.

### 6. API Layer & Routes (`src/minipay/api/`)

- **Authentication (`dependencies.py`)**:
  - Header `X-API-Key` validated against `settings.api_key`.
  - Returns HTTP 401 with `{"error": {"code": "invalid_api_key", "message": "..."}}` if invalid or missing.
- **Central Exception Handling (`main.py`)**:
  - `IllegalTransition` → HTTP 409 `{"error": {"code": "illegal_transition", "message": "..."}}`
  - `MiniPayError` (`PaymentNotFoundError`, `MerchantNotFoundError`) → HTTP 404
  - `RequestValidationError` → HTTP 400 `{"error": {"code": "validation_error", "message": "..."}}`
  - `HTTPException` → Standardized JSON error response
- **Endpoints**:
  | Route | Method | Auth | Response | Description |
  |---|---|---|---|---|
  | `/health` | GET | None | `{"status": "ok"}` | Liveness probe |
  | `/ready` | GET | None | `{"status": "ok", "db": "ok"}` | Readiness check (tests DB ping) |
  | `/v1/payments` | POST | Required | 201 Created | Create and authorize payment |
  | `/v1/payments/{id}` | GET | Required | 200 OK / 404 | Fetch payment details |
  | `/v1/payments` | GET | Required | 200 OK | Cursor-paginated payments list |
  | `/v1/payments/{id}/capture` | POST | Required | 200 OK / 409 | Capture authorized payment |
  | `/v1/payments/{id}/refund` | POST | Required | 200 OK / 409 | Refund captured payment |
  | `/v1/merchants/{id}/summary` | GET | Required | 200 OK / 404 | Aggregate merchant statistics |

---

## 🧪 Test Suite Coverage & Verification

- **Testing Configuration (`tests/conftest.py`)**:
  - Uses in-memory SQLite database (`sqlite:///:memory:`) with `StaticPool` for isolated, ultra-fast test runs without external DB dependency.
  - Auto-seeds `m_001` and `m_002` test merchants.
  - Sets up `TestClient` fixtures with and without `X-API-Key`.
- **Test Modules**:
  - [`tests/unit/test_state.py`](tests/unit/test_state.py): 100% coverage of all valid and invalid state transitions.
  - [`tests/unit/test_acquirer.py`](tests/unit/test_acquirer.py): Validates magic card endings (`4242`, `0002`, `0005`, `9995`), failure injection rate, and config factory.
  - [`tests/unit/test_services.py`](tests/unit/test_services.py): Tests business rules, merchant validation, idempotent capture/refund retries, and illegal transitions.
  - [`tests/integration/test_api.py`](tests/integration/test_api.py): Full HTTP integration tests covering health checks, auth validation, 201/200 success paths, and 400/401/404/409 error paths.

---

## 🚀 Phase 2 Kickoff Handoff Guide

When starting **Phase 2 (Idempotency and Concurrency Safety)**, developers/agents can directly execute the following steps:

1. **Create ORM Model**:
   - Add `IdempotencyKey` model in `src/minipay/domain/models.py`:
     ```python
     class IdempotencyKey(Base):
         __tablename__ = "idempotency_keys"
         __table_args__ = (UniqueConstraint("merchant_id", "key", name="uq_idempotency_merchant_key"),)

         id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
         merchant_id: Mapped[str] = mapped_column(String, nullable=False)
         key: Mapped[str] = mapped_column(String, nullable=False)
         request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
         state: Mapped[str] = mapped_column(String, nullable=False) # 'IN_PROGRESS' | 'COMPLETED'
         response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
         response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
         created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
     ```
2. **Implement `IdempotencyRepository`** in `src/minipay/repositories/idempotency.py`:
   - `try_insert(merchant_id: str, key: str, request_hash: str)`
   - `get(merchant_id: str, key: str)`
   - `complete(record, response_status: int, response_body: dict)`
3. **Implement `IdempotencyService`** in `src/minipay/services/idempotency.py`:
   - Canonical JSON serializer (`json.dumps(obj, sort_keys=True, separators=(',', ':'))`).
   - `sha256(canonical_json).hexdigest()`.
   - Algorithm from §6.3:
     - If key not found: Insert `IN_PROGRESS`, proceed to payment creation.
     - On unique constraint violation:
       - Hash differs → raise 409 `idempotency_key_reused_with_different_payload`.
       - State is `IN_PROGRESS` → raise 409 `request_in_progress`.
       - State is `COMPLETED` → replay stored response with header `Idempotent-Replayed: true`.
4. **Update `POST /v1/payments`**:
   - Require `Idempotency-Key` header (return 400 `missing_idempotency_key` if absent).
5. **Add Concurrency Tests**:
   - `ThreadPoolExecutor` with 50 concurrent requests using identical `Idempotency-Key` → assert exactly 1 payment in DB, all 50 receive identical response bodies.
