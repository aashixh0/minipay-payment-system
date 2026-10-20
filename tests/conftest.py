"""
tests/conftest.py — Shared pytest fixtures for unit and integration tests.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from minipay.api.dependencies import get_session
from minipay.api.main import app
from minipay.core.config import settings
from minipay.core.db import Base
from minipay.core.logging import configure_logging
from minipay.domain.acquirer import MockAcquirer
from minipay.domain.models import Merchant

# Configure logging once for tests
configure_logging("INFO")

# SQLite in-memory engine shared within each test function
SQLITE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a fresh, clean in-memory database session with tables and seed data."""
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()

    # Seed test merchants
    m1 = Merchant(
        id="m_001",
        name="Demo Merchant One",
        webhook_url="http://localhost:9000/hook",
        webhook_secret="secret-m001-change-me",
    )
    m2 = Merchant(
        id="m_002",
        name="Demo Merchant Two",
        webhook_url=None,
        webhook_secret="secret-m002-change-me",
    )
    session.add_all([m1, m2])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def mock_acquirer() -> MockAcquirer:
    """Mock acquirer with 0% failure rate for predictable tests."""
    return MockAcquirer(failure_rate=0.0)


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient wired to the test DB session and default API key."""
    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, base_url="http://testserver", headers={"X-API-Key": settings.api_key}) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient without the X-API-Key header to test auth protection."""
    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, base_url="http://testserver") as tc:
        yield tc
    app.dependency_overrides.clear()
