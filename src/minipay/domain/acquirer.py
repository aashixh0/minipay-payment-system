"""
domain/acquirer.py — Acquirer interface (Strategy pattern) and MockAcquirer.

The Acquirer Protocol defines the interface; MockAcquirer is a deterministic
implementation controlled by magic card last4 endings (§6.2).
A factory function selects the implementation from config.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from minipay.core.config import settings


@dataclass
class AcquirerResult:
    approved: bool
    failure_reason: str | None = None


class Acquirer(Protocol):
    """Strategy interface — swap implementations via config without changing callers."""

    def authorize(self, amount_minor: int, currency: str, card_last4: str) -> AcquirerResult: ...
    def capture(self, payment_id: str, card_last4: str) -> AcquirerResult: ...
    def refund(self, payment_id: str) -> AcquirerResult: ...


class MockAcquirer:
    """
    Deterministic mock acquirer driven by magic card last4 endings.

    | card_last4 | authorize behavior               | capture behavior |
    |------------|----------------------------------|------------------|
    | 4242       | Approve (default)                | Approve          |
    | 0002       | Decline → card_declined          | n/a              |
    | 0005       | Fail   → timeout                 | n/a              |
    | 9995       | Approve                          | Fail → capture_failed |

    Additionally, MOCK_ACQUIRER_FAILURE_RATE (float 0.0–1.0) injects random
    failures for live demos without changing card data.
    """

    DECLINE_CARD = "0002"
    TIMEOUT_CARD = "0005"
    CAPTURE_FAIL_CARD = "9995"

    def __init__(self, failure_rate: float = 0.0) -> None:
        self._failure_rate = max(0.0, min(1.0, failure_rate))

    def _random_fail(self) -> bool:
        return self._failure_rate > 0 and random.random() < self._failure_rate

    def authorize(self, amount_minor: int, currency: str, card_last4: str) -> AcquirerResult:
        if card_last4 == self.DECLINE_CARD:
            return AcquirerResult(approved=False, failure_reason="card_declined")
        if card_last4 == self.TIMEOUT_CARD:
            return AcquirerResult(approved=False, failure_reason="timeout")
        if self._random_fail():
            return AcquirerResult(approved=False, failure_reason="acquirer_error")
        return AcquirerResult(approved=True)

    def capture(self, payment_id: str, card_last4: str = "4242") -> AcquirerResult:
        if card_last4 == self.CAPTURE_FAIL_CARD:
            return AcquirerResult(approved=False, failure_reason="capture_failed")
        if self._random_fail():
            return AcquirerResult(approved=False, failure_reason="acquirer_error")
        return AcquirerResult(approved=True)

    def refund(self, payment_id: str) -> AcquirerResult:
        if self._random_fail():
            return AcquirerResult(approved=False, failure_reason="acquirer_error")
        return AcquirerResult(approved=True)


def get_acquirer() -> MockAcquirer:
    """Factory: return the acquirer implementation selected by config."""
    if settings.acquirer == "mock":
        return MockAcquirer(failure_rate=settings.mock_acquirer_failure_rate)
    raise ValueError(f"Unknown acquirer: {settings.acquirer!r}")
