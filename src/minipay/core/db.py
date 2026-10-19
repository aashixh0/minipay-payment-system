"""
core/db.py — SQLAlchemy engine, session factory, and FastAPI dependency.

Design notes
------------
- Uses synchronous SQLAlchemy 2.0 + psycopg 3 (psycopg driver).
- WebSocket broadcasts are done via anyio.from_thread after commit, so we
  don't need async sessions here.
- get_session() is a FastAPI dependency that yields a session and always
  closes it, even on exception.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from minipay.core.config import settings

# ── Engine ─────────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,          # recycle stale connections
    pool_size=10,
    max_overflow=20,
    echo=False,                  # set True for SQL debugging
)

# ── Session factory ────────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,      # avoid lazy-load after commit in sync code
)


# ── ORM base ───────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ── FastAPI dependency ─────────────────────────────────────────────────────────
def get_session() -> Generator[Session, None, None]:
    """Yield a DB session; always close it when the request is done."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Health helper ──────────────────────────────────────────────────────────────
def check_db_connection() -> bool:
    """Return True if the database is reachable, False otherwise."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
