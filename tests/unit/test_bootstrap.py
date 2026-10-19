"""
tests/unit/test_bootstrap.py

Phase 0 acceptance test:
- Verifies the package is importable.
- Verifies Settings loads without errors.
- Verifies JSON logging is configurable without errors.
"""

import logging


def test_settings_loads() -> None:
    """Settings should load from defaults without raising."""
    from minipay.core.config import settings

    assert settings.api_key == "dev-key-change-me"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.ingestion_workers == 4
    assert settings.webhook_max_attempts == 6


def test_logging_configures() -> None:
    """configure_logging() should not raise and should set the root level."""
    from minipay.core.logging import configure_logging

    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG

    configure_logging("INFO")
    assert logging.getLogger().level == logging.INFO


def test_package_importable() -> None:
    """The minipay package root must be importable."""
    import minipay  # noqa: F401
