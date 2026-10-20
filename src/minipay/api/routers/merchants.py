"""
api/routers/merchants.py — REST endpoints for /v1/merchants (§8 API Contract).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from minipay.api.dependencies import get_payment_service, verify_api_key
from minipay.domain.schemas import MerchantSummaryResponse
from minipay.services.payment_service import PaymentService

router = APIRouter(
    prefix="/v1/merchants",
    tags=["Merchants"],
    dependencies=[Depends(verify_api_key)],
)


@router.get(
    "/{merchant_id}/summary",
    response_model=MerchantSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payment counts by status and total captured minor amount",
)
def get_merchant_summary(
    merchant_id: str,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> MerchantSummaryResponse:
    by_status, total_captured = service.get_merchant_summary(merchant_id)
    return MerchantSummaryResponse(
        merchant_id=merchant_id,
        by_status=by_status,
        total_captured_minor=total_captured,
    )
