"""
domain/exceptions.py — Domain exceptions mapped to HTTP errors (§8 API Contract).
"""

from __future__ import annotations

from minipay.domain.state import IllegalTransition, PaymentStatus


class MiniPayError(Exception):
    """Base domain exception with standardized code and status code."""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class PaymentNotFoundError(MiniPayError):
    code = "payment_not_found"
    status_code = 404

    def __init__(self, payment_id: str) -> None:
        super().__init__(
            f"Payment {payment_id} not found",
            code=self.code,
            status_code=self.status_code,
        )


class MerchantNotFoundError(MiniPayError):
    code = "merchant_not_found"
    status_code = 404

    def __init__(self, merchant_id: str) -> None:
        super().__init__(
            f"Merchant {merchant_id} not found",
            code=self.code,
            status_code=self.status_code,
        )


__all__ = [
    "IllegalTransition",
    "MerchantNotFoundError",
    "MiniPayError",
    "PaymentNotFoundError",
    "PaymentStatus",
]
