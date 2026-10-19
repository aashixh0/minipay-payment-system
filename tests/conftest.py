"""
tests/conftest.py — Shared pytest fixtures.
Phase 0: minimal setup.
Later phases will add DB, API client, and MQTT fixtures here.
"""

from minipay.core.config import settings
from minipay.core.logging import configure_logging

# Ensure JSON logging is configured once before the test session.
configure_logging(settings.log_level)
