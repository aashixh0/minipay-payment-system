"""
api/dependencies.py — FastAPI dependencies for authentication and services.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from minipay.core.config import settings
from minipay.core.db import get_session
from minipay.services.payment_service import PaymentService


def verify_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> str:
    """Verify the shared X-API-Key header (§8 API Contract)."""
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_api_key", "message": "Invalid or missing API key"},
        )
    return x_api_key


def get_payment_service(session: Session = Depends(get_session)) -> PaymentService:
    """Yield a PaymentService scoped to the current request's DB session."""
    return PaymentService(session=session)
