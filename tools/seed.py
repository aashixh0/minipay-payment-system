"""
tools/seed.py — Seed demo merchants into the database.
Creates m_001 and m_002 if they don't already exist.
Run: python tools/seed.py
"""

import os
import sys

# Allow running directly from project root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import logging  # noqa: E402

from minipay.core.config import settings  # noqa: E402
from minipay.core.db import Base, SessionLocal, engine  # noqa: E402
from minipay.core.logging import configure_logging  # noqa: E402

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

MERCHANTS = [
    {
        "id": "m_001",
        "name": "Demo Merchant One",
        "webhook_url": "http://localhost:9000/hook",
        "webhook_secret": "secret-m001-change-me",
    },
    {
        "id": "m_002",
        "name": "Demo Merchant Two",
        "webhook_url": None,
        "webhook_secret": "secret-m002-change-me",
    },
]


def seed() -> None:
    # Import models so create_all knows about them (populated in Phase 1).
    try:
        from minipay.domain import models as _  # noqa: F401
    except ImportError:
        logger.info("Domain models not yet defined; skipping table creation.")
        return

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        from minipay.domain.models import Merchant  # noqa: F401

        for data in MERCHANTS:
            existing = session.get(Merchant, data["id"])
            if existing:
                logger.info("Merchant already exists", extra={"merchant_id": data["id"]})
                continue

            merchant = Merchant(**data)
            session.add(merchant)
            logger.info("Created merchant", extra={"merchant_id": data["id"]})

        session.commit()

    logger.info("Seeding complete.")


if __name__ == "__main__":
    seed()
