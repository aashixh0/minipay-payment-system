"""
tests/unit/test_services.py — Unit tests for PaymentService business logic.
"""

import uuid
import pytest
from sqlalchemy.orm import Session

from minipay.domain.exceptions import MerchantNotFoundError, PaymentNotFoundError
from minipay.domain.schemas import PaymentCreateRequest
from minipay.domain.state import IllegalTransition, PaymentStatus
from minipay.services.payment_service import PaymentService


class TestPaymentService:
    def test_create_payment_success(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=50000,
            currency="INR",
            card_last4="4242",
            terminal_id="t_01",
        )
        payment = service.create_payment(req)
        assert payment.id is not None
        assert payment.status == str(PaymentStatus.AUTHORIZED)
        assert payment.merchant_id == "m_001"
        assert payment.amount_minor == 50000
        assert payment.failure_reason is None
        assert len(payment.events) == 2  # CREATED audit + AUTHORIZED transition

    def test_create_payment_declined(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=2000,
            currency="INR",
            card_last4="0002",
        )
        payment = service.create_payment(req)
        assert payment.status == str(PaymentStatus.FAILED)
        assert payment.failure_reason == "card_declined"

    def test_create_payment_unknown_merchant_raises_404(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_unknown",
            amount_minor=1000,
            currency="INR",
            card_last4="4242",
        )
        with pytest.raises(MerchantNotFoundError) as exc_info:
            service.create_payment(req)
        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "merchant_not_found"

    def test_capture_lifecycle_and_idempotent_retry(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=30000,
            currency="INR",
            card_last4="4242",
        )
        payment = service.create_payment(req)
        assert payment.status == str(PaymentStatus.AUTHORIZED)

        # First capture -> CAPTURED
        captured = service.capture_payment(payment.id)
        assert captured.status == str(PaymentStatus.CAPTURED)

        # Retry capture -> idempotent no-op returns CAPTURED
        retried = service.capture_payment(payment.id)
        assert retried.status == str(PaymentStatus.CAPTURED)

    def test_capture_failure_card_9995(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=15000,
            currency="INR",
            card_last4="9995",
        )
        payment = service.create_payment(req)
        assert payment.status == str(PaymentStatus.AUTHORIZED)

        # Capture fails due to card 9995
        failed = service.capture_payment(payment.id)
        assert failed.status == str(PaymentStatus.FAILED)
        assert failed.failure_reason == "capture_failed"

    def test_illegal_capture_raises_409(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=1000,
            currency="INR",
            card_last4="0002",  # Will fail
        )
        payment = service.create_payment(req)
        assert payment.status == str(PaymentStatus.FAILED)

        # Capturing FAILED payment is illegal
        with pytest.raises(IllegalTransition) as exc_info:
            service.capture_payment(payment.id)
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "illegal_transition"

    def test_refund_lifecycle_and_idempotent_retry(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=12000,
            currency="INR",
            card_last4="4242",
        )
        payment = service.create_payment(req)
        service.capture_payment(payment.id)

        # First refund -> REFUNDED
        refunded = service.refund_payment(payment.id)
        assert refunded.status == str(PaymentStatus.REFUNDED)

        # Retry refund -> idempotent no-op returns REFUNDED
        retried = service.refund_payment(payment.id)
        assert retried.status == str(PaymentStatus.REFUNDED)

    def test_illegal_refund_raises_409(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        req = PaymentCreateRequest(
            merchant_id="m_001",
            amount_minor=1000,
            currency="INR",
            card_last4="4242",
        )
        payment = service.create_payment(req)
        assert payment.status == str(PaymentStatus.AUTHORIZED)

        # Refunding AUTHORIZED without capture is illegal
        with pytest.raises(IllegalTransition) as exc_info:
            service.refund_payment(payment.id)
        assert exc_info.value.status_code == 409

    def test_get_payment_not_found(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        random_id = uuid.uuid4()
        with pytest.raises(PaymentNotFoundError):
            service.get_payment(random_id)

    def test_merchant_summary(self, db_session: Session) -> None:
        service = PaymentService(session=db_session)
        # Create one authorized, one captured
        p1 = service.create_payment(PaymentCreateRequest(
            merchant_id="m_001", amount_minor=1000, currency="INR", card_last4="4242"
        ))
        p2 = service.create_payment(PaymentCreateRequest(
            merchant_id="m_001", amount_minor=2000, currency="INR", card_last4="4242"
        ))
        service.capture_payment(p2.id)

        by_status, total_captured = service.get_merchant_summary("m_001")
        assert by_status[PaymentStatus.AUTHORIZED] == 1
        assert by_status[PaymentStatus.CAPTURED] == 1
        assert total_captured == 2000
