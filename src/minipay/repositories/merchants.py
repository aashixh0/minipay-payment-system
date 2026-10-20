"""
repositories/merchants.py — MerchantRepository: DB access for merchants.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from minipay.domain.models import Merchant


class MerchantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, merchant_id: str) -> Merchant | None:
        return self._session.get(Merchant, merchant_id)

    def add(self, merchant: Merchant) -> Merchant:
        self._session.add(merchant)
        self._session.flush()
        return merchant
