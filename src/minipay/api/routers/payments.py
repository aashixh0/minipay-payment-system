"""
api/routers/payments.py — REST endpoints for /v1/payments (§8 API Contract).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from minipay.api.dependencies import get_payment_service, verify_api_key
from minipay.domain.schemas import (
    PaymentCreateRequest,
    PaymentListResponse,
    PaymentResponse,
)
from minipay.services.payment_service import PaymentService

router = APIRouter(
    prefix="/v1/payments",
    tags=["Payments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and authorize a payment",
)
def create_payment(
    request: PaymentCreateRequest,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    """
    Create a new payment record, authorize with acquirer, and transition state.
    Declined payments also return HTTP 201 with status=FAILED.
    """
    payment = service.create_payment(request)
    return PaymentResponse.model_validate(payment)


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch a payment by ID",
)
def get_payment(
    payment_id: uuid.UUID,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    payment = service.get_payment(payment_id)
    return PaymentResponse.model_validate(payment)


@router.get(
    "",
    response_model=PaymentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List payments with cursor pagination",
)
def list_payments(
    merchant_id: str,
    service: Annotated[PaymentService, Depends(get_payment_service)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> PaymentListResponse:
    items, next_cursor = service.list_payments(
        merchant_id=merchant_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    return PaymentListResponse(
        items=[PaymentResponse.model_validate(p) for p in items],
        next_cursor=next_cursor,
    )


@router.post(
    "/{payment_id}/capture",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture an AUTHORIZED payment",
)
def capture_payment(
    payment_id: uuid.UUID,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    payment = service.capture_payment(payment_id)
    return PaymentResponse.model_validate(payment)


@router.post(
    "/{payment_id}/refund",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Refund a CAPTURED payment",
)
def refund_payment(
    payment_id: uuid.UUID,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    payment = service.refund_payment(payment_id)
    return PaymentResponse.model_validate(payment)
