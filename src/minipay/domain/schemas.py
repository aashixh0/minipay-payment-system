"""
domain/schemas.py — Pydantic v2 request/response schemas (§8 API Contract).

Naming convention:
  *Request  — inbound request body
  *Response — outbound response body
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Error format ───────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Payment ────────────────────────────────────────────────────────────────────

class PaymentCreateRequest(BaseModel):
    merchant_id: str
    amount_minor: int = Field(gt=0, description="Amount in minor currency units (e.g. paise)")
    currency: str = Field(min_length=3, max_length=3, description="ISO-4217 currency code")
    card_last4: str = Field(min_length=4, max_length=4, description="Last 4 digits of the card")
    terminal_id: str | None = Field(default=None, description="POS terminal identifier")
    source_event_id: str | None = Field(
        default=None, description="MQTT event_id for deduplication"
    )


class PaymentResponse(BaseModel):
    id: uuid.UUID
    merchant_id: str
    amount_minor: int
    currency: str
    status: str
    terminal_id: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    next_cursor: str | None = None


# ── Merchant ───────────────────────────────────────────────────────────────────

class MerchantSummaryResponse(BaseModel):
    merchant_id: str
    by_status: dict[str, int]
    total_captured_minor: int


# ── Health ─────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    db: str
