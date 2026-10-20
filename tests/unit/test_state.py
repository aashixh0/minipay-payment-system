"""
tests/unit/test_state.py — Unit tests for payment state machine (State pattern).
Verifies every row of the transition table and all illegal transitions (§6.1).
"""

import pytest

from minipay.domain.state import (
    IllegalTransition,
    PaymentStatus,
    get_state,
)


class TestStateTransitions:
    """Verify legal state transitions per §6.1."""

    def test_created_authorize_approved(self) -> None:
        state = get_state(PaymentStatus.CREATED)
        next_status = state.authorize(approved=True)
        assert next_status == PaymentStatus.AUTHORIZED

    def test_created_authorize_declined(self) -> None:
        state = get_state(PaymentStatus.CREATED)
        next_status = state.authorize(approved=False, failure_reason="card_declined")
        assert next_status == PaymentStatus.FAILED

    def test_authorized_capture_success(self) -> None:
        state = get_state(PaymentStatus.AUTHORIZED)
        next_status = state.capture(success=True)
        assert next_status == PaymentStatus.CAPTURED

    def test_authorized_capture_failed(self) -> None:
        state = get_state(PaymentStatus.AUTHORIZED)
        next_status = state.capture(success=False)
        assert next_status == PaymentStatus.FAILED

    def test_captured_refund(self) -> None:
        state = get_state(PaymentStatus.CAPTURED)
        next_status = state.refund()
        assert next_status == PaymentStatus.REFUNDED


class TestIllegalTransitions:
    """Verify illegal transitions raise IllegalTransition with 409."""

    @pytest.mark.parametrize("status", [
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.REFUNDED,
    ])
    def test_cannot_authorize_from_non_created(self, status: PaymentStatus) -> None:
        state = get_state(status)
        with pytest.raises(IllegalTransition) as exc_info:
            state.authorize(approved=True)
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "illegal_transition"
        assert exc_info.value.from_status == status
        assert exc_info.value.action == "authorize"

    @pytest.mark.parametrize("status", [
        PaymentStatus.CREATED,
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.REFUNDED,
    ])
    def test_cannot_capture_from_non_authorized(self, status: PaymentStatus) -> None:
        state = get_state(status)
        with pytest.raises(IllegalTransition) as exc_info:
            state.capture(success=True)
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "illegal_transition"
        assert exc_info.value.from_status == status
        assert exc_info.value.action == "capture"

    @pytest.mark.parametrize("status", [
        PaymentStatus.CREATED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.FAILED,
        PaymentStatus.REFUNDED,
    ])
    def test_cannot_refund_from_non_captured(self, status: PaymentStatus) -> None:
        state = get_state(status)
        with pytest.raises(IllegalTransition) as exc_info:
            state.refund()
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "illegal_transition"
        assert exc_info.value.from_status == status
        assert exc_info.value.action == "refund"
