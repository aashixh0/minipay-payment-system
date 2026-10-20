"""
api/main.py — FastAPI application setup, middleware, and exception handlers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from minipay.api.routers import health, merchants, payments
from minipay.core.config import settings
from minipay.core.db import Base, engine
from minipay.core.logging import configure_logging
from minipay.domain.exceptions import MiniPayError
from minipay.domain.state import IllegalTransition


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    configure_logging(settings.log_level)
    # Automatically create missing tables (Phase 1 spec: Base.metadata.create_all)
    try:
        from minipay.domain import models as _  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception:
        # Allows running in environments where DB is not yet available at import
        pass
    yield


app = FastAPI(
    title="MiniPay API",
    version="0.1.0",
    description="MiniPay POS-to-Payments REST API",
    lifespan=lifespan,
)


# ── Central exception handlers (§8 Error format) ───────────────────────────────

@app.exception_handler(IllegalTransition)
async def illegal_transition_handler(
    request: Request, exc: IllegalTransition
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": {"code": exc.code, "message": str(exc)}},
    )


@app.exception_handler(MiniPayError)
async def minipay_error_handler(
    request: Request, exc: MiniPayError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Build clean human-readable error messages from Pydantic errors
    errors = exc.errors()
    msg = "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in errors
    ) if errors else "Validation failed"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": {"code": "validation_error", "message": msg}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    code = "http_error"
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "invalid_api_key"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail)}},
    )


# ── Mount Routers ─────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(payments.router)
app.include_router(merchants.router)
