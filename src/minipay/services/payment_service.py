"""
services/payment_service.py — Core payment orchestration.

Coordinates repositories, state machine transitions, and acquirer calls.
Rule: exactly one DB transaction per business operation.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from minipay.domain.acquirer import Acquirer, get_acquirer
from minipay.domain.exceptions import MerchantNotFoundError, PaymentNotFoundError
from minipay.domain.models import Payment, PaymentEvent
from minipay.domain.schemas import PaymentCreateRequest
from minipay.domain.state import PaymentStatus, get_state
from minipay.repositories.merchants import MerchantRepository
from minipay.repositories.payments import PaymentRepository

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        session: Session,
        payment_repo: PaymentRepository | None = None,
        merchant_repo: MerchantRepository | None = None,
        acquirer: Acquirer | None = None,
    ) -> None:
        self._session = session
        self._payment_repo = payment_repo or PaymentRepository(session)
        self._merchant_repo = merchant_repo or MerchantRepository(session)
        self._acquirer = acquirer or get_acquirer()

    def create_payment(self, request: PaymentCreateRequest) -> Payment:
        """
        Create a payment in CREATED, call the acquirer to authorize,
        and transition to AUTHORIZED or FAILED.
        """
        merchant = self._merchant_repo.get(request.merchant_id)
        if not merchant:
            raise MerchantNotFoundError(request.merchant_id)

        payment = Payment(
            merchant_id=request.merchant_id,
            amount_minor=request.amount_minor,
            currency=request.currency.upper(),
            status=str(PaymentStatus.CREATED),
            card_last4=request.card_last4,
            terminal_id=request.terminal_id,
            source_event_id=request.source_event_id,
        )
        self._payment_repo.add(payment)

        # Audit initial CREATED state
        initial_event = PaymentEvent(
            payment_id=payment.id,
            from_status=None,
            to_status=str(PaymentStatus.CREATED),
        )
        self._session.add(initial_event)
        self._session.flush()

        # Acquirer call
        acq_result = self._acquirer.authorize(
            amount_minor=request.amount_minor,
            currency=request.currency.upper(),
            card_last4=request.card_last4,
        )

        state = get_state(PaymentStatus.CREATED)
        next_status = state.authorize(
            approved=acq_result.approved,
            failure_reason=acq_result.failure_reason,
        )

        self._payment_repo.update_status(
            payment,
            next_status,
            failure_reason=acq_result.failure_reason,
        )
        self._session.commit()
        self._session.refresh(payment)

        logger.info(
            "Payment created and authorized",
            extra={
                "payment_id": str(payment.id),
                "merchant_id": payment.merchant_id,
                "status": payment.status,
            },
        )
        return payment

    def get_payment(self, payment_id: uuid.UUID | str) -> Payment:
        """Fetch payment or raise PaymentNotFoundError."""
        payment = self._payment_repo.get(payment_id)
        if not payment:
            raise PaymentNotFoundError(str(payment_id))
        return payment

    def list_payments(
        self,
        merchant_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[Payment], str | None]:
        """Fetch paginated payments for a merchant."""
        merchant = self._merchant_repo.get(merchant_id)
        if not merchant:
            raise MerchantNotFoundError(merchant_id)

        limit = max(1, min(100, limit))
        return self._payment_repo.list_payments(
            merchant_id=merchant_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )

    def capture_payment(self, payment_id: uuid.UUID | str) -> Payment:
        """
        Capture an AUTHORIZED payment.
        Idempotent/retry safe: if already CAPTURED, return as no-op.
        """
        payment = self.get_payment(payment_id)
        current_status = PaymentStatus(payment.status)

        if current_status == PaymentStatus.CAPTURED:
            logger.info("Payment already CAPTURED; returning current state", extra={"payment_id": str(payment.id)})
            return payment

        state = get_state(current_status)
        acq_result = self._acquirer.capture(str(payment.id), payment.card_last4)
        next_status = state.capture(success=acq_result.approved)

        self._payment_repo.update_status(
            payment,
            next_status,
            failure_reason=acq_result.failure_reason,
        )
        self._session.commit()
        self._session.refresh(payment)

        logger.info(
            "Payment capture completed",
            extra={"payment_id": str(payment.id), "status": payment.status},
        )
        return payment

    def refund_payment(self, payment_id: uuid.UUID | str) -> Payment:
        """
        Refund a CAPTURED payment.
        Idempotent/retry safe: if already REFUNDED, return as no-op.
        """
        payment = self.get_payment(payment_id)
        current_status = PaymentStatus(payment.status)

        if current_status == PaymentStatus.REFUNDED:
            logger.info("Payment already REFUNDED; returning current state", extra={"payment_id": str(payment.id)})
            return payment

        state = get_state(current_status)
        acq_result = self._acquirer.refund(str(payment.id))
        next_status = state.refund()

        self._payment_repo.update_status(
            payment,
            next_status,
            failure_reason=acq_result.failure_reason,
        )
        self._session.commit()
        self._session.refresh(payment)

        logger.info(
            "Payment refund completed",
            extra={"payment_id": str(payment.id), "status": payment.status},
        )
        return payment

    def get_merchant_summary(self, merchant_id: str) -> tuple[dict[str, int], int]:
        """Fetch summary of counts by status and total captured minor amount."""
        merchant = self._merchant_repo.get(merchant_id)
        if not merchant:
            raise MerchantNotFoundError(merchant_id)
        return self._payment_repo.summary(merchant_id)
