"""
domain/state.py — Payment state machine (State pattern).

State diagram (§6.1):
  CREATED ──authorize ok──► AUTHORIZED ──capture ok──► CAPTURED ──refund──► REFUNDED
     │                          │
     └──decline──► FAILED ◄─────┘  (acquirer failure on capture)

Illegal transitions raise IllegalTransition → caller maps to HTTP 409.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class IllegalTransition(Exception):
    """Raised when an action is attempted on an incompatible payment status."""

    code: str = "illegal_transition"
    status_code: int = 409

    def __init__(self, from_status: PaymentStatus, action: str) -> None:
        self.from_status = from_status
        self.action = action
        super().__init__(f"Cannot {action} a payment in status {from_status}")


class PaymentState(ABC):
    """
    Abstract base state.

    Subclasses override only the transitions they support.
    Everything else inherits the default which raises IllegalTransition.
    """

    @property
    @abstractmethod
    def status(self) -> PaymentStatus: ...

    def authorize(self, *, approved: bool, failure_reason: str | None = None) -> PaymentStatus:
        raise IllegalTransition(self.status, "authorize")

    def capture(self, *, success: bool) -> PaymentStatus:
        raise IllegalTransition(self.status, "capture")

    def refund(self) -> PaymentStatus:
        raise IllegalTransition(self.status, "refund")


class CreatedState(PaymentState):
    @property
    def status(self) -> PaymentStatus:
        return PaymentStatus.CREATED

    def authorize(self, *, approved: bool, failure_reason: str | None = None) -> PaymentStatus:
        return PaymentStatus.AUTHORIZED if approved else PaymentStatus.FAILED


class AuthorizedState(PaymentState):
    @property
    def status(self) -> PaymentStatus:
        return PaymentStatus.AUTHORIZED

    def capture(self, *, success: bool) -> PaymentStatus:
        return PaymentStatus.CAPTURED if success else PaymentStatus.FAILED


class CapturedState(PaymentState):
    @property
    def status(self) -> PaymentStatus:
        return PaymentStatus.CAPTURED

    def refund(self) -> PaymentStatus:
        return PaymentStatus.REFUNDED


class FailedState(PaymentState):
    """Terminal state — no transitions allowed."""

    @property
    def status(self) -> PaymentStatus:
        return PaymentStatus.FAILED


class RefundedState(PaymentState):
    """Terminal state — no transitions allowed."""

    @property
    def status(self) -> PaymentStatus:
        return PaymentStatus.REFUNDED


# Module-level singleton map: status string → state object.
_STATE_MAP: dict[PaymentStatus, PaymentState] = {
    PaymentStatus.CREATED: CreatedState(),
    PaymentStatus.AUTHORIZED: AuthorizedState(),
    PaymentStatus.CAPTURED: CapturedState(),
    PaymentStatus.FAILED: FailedState(),
    PaymentStatus.REFUNDED: RefundedState(),
}


def get_state(status: PaymentStatus) -> PaymentState:
    """Factory: return the singleton State object for the given PaymentStatus."""
    return _STATE_MAP[status]
