"""
api/routers/health.py — Health and readiness check endpoints (§8 API Contract).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from minipay.core.db import check_db_connection
from minipay.domain.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, summary="Readiness check")
def ready(response: Response) -> ReadyResponse:
    db_ok = check_db_connection()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="degraded", db="down")
    return ReadyResponse(status="ok", db="ok")
