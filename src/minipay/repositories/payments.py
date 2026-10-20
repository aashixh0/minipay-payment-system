"""
repositories/payments.py — PaymentRepository: all DB reads/writes for payments.

Layering rule: no business logic here — only DB operations.
Business rules live in services/ and domain/.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from minipay.domain.models import Payment, PaymentEvent
from minipay.domain.state import PaymentStatus


class PaymentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Write operations ───────────────────────────────────────────────────────

    def add(self, payment: Payment) -> Payment:
        """Persist a new payment and flush to populate generated columns."""
        self._session.add(payment)
        self._session.flush()
        return payment

    def update_status(
        self,
        payment: Payment,
        new_status: PaymentStatus,
        *,
        failure_reason: str | None = None,
    ) -> Payment:
        """
        Transition payment to new_status, bump the optimistic-lock version,
        and append a PaymentEvent to the audit trail — all within the current
        transaction (caller must commit).
        """
        old_status = payment.status
        payment.status = str(new_status)
        payment.failure_reason = failure_reason
        payment.updated_at = datetime.now(tz=timezone.utc)
        payment.version += 1

        event = PaymentEvent(
            payment_id=payment.id,
            from_status=old_status,
            to_status=str(new_status),
        )
        self._session.add(event)
        self._session.flush()
        return payment

    # ── Read operations ────────────────────────────────────────────────────────

    def get(self, payment_id: uuid.UUID | str) -> Payment | None:
        """Fetch a single payment by UUID. Returns None if not found or invalid id."""
        if isinstance(payment_id, str):
            try:
                payment_id = uuid.UUID(payment_id)
            except ValueError:
                return None
        return self._session.get(Payment, payment_id)

    def list_payments(
        self,
        merchant_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[Payment], str | None]:
        """
        Cursor-paginated list of payments (newest first).

        cursor  — ISO-8601 created_at of the last seen item.
        Returns (items, next_cursor); next_cursor is None on the last page.
        """
        stmt = (
            select(Payment)
            .where(Payment.merchant_id == merchant_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit + 1)  # fetch one extra to detect next page
        )
        if status:
            stmt = stmt.where(Payment.status == status)
        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor)
                stmt = stmt.where(Payment.created_at < cursor_dt)
            except ValueError:
                pass  # ignore malformed cursors

        rows = list(self._session.scalars(stmt))
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1].created_at.isoformat() if has_more and items else None
        return items, next_cursor

    def summary(self, merchant_id: str) -> tuple[dict[str, int], int]:
        """
        Return (counts_by_status, total_captured_amount_minor).
        Used by GET /v1/merchants/{id}/summary.
        """
        count_stmt = (
            select(Payment.status, func.count().label("cnt"))
            .where(Payment.merchant_id == merchant_id)
            .group_by(Payment.status)
        )
        by_status: dict[str, int] = {s.value: 0 for s in PaymentStatus}
        for row in self._session.execute(count_stmt):
            by_status[row.status] = row.cnt

        captured_stmt = (
            select(func.coalesce(func.sum(Payment.amount_minor), 0))
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.status == str(PaymentStatus.CAPTURED))
        )
        total_captured = self._session.scalar(captured_stmt) or 0
        return by_status, int(total_captured)
