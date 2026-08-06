"""Pytest fixtures shared across grab/ + app tests."""

from __future__ import annotations

from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from grab.client import GrabClient

from app.core.config import Settings
from app.models import AuditLog, OrderArchive, Store, User  # noqa: F401  (imports register tables)


# ── Phase 02 fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def merchant_id() -> str:
    return "zeus_store:5-C6VKAT5GRK3CTT"


@pytest.fixture
def authn_token() -> str:
    return "fake.authn.token"


@pytest.fixture
def grab_client(authn_token: str, merchant_id: str) -> GrabClient:
    """A GrabClient pre-bound to a fake token + merchant.

    Tests enter the async context manager themselves so they can also
    exercise the `async with` lifecycle.
    """
    return GrabClient(authn_token=authn_token, merchant_id=merchant_id, verify_ssl=True)


# ── Phase 03 fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def settings() -> Settings:
    """A Settings instance with token_encryption_key pre-set for testing."""
    s = Settings()
    s.token_encryption_key = Settings.generate_fernet_key()
    s.session_secret = Settings.generate_session_secret()
    s.grab_verify_ssl = False
    return s


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite engine + tables, yields a Session, auto-rollbacks after."""
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def test_client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with DB session + settings overridden.

    Tests that hit the HTTP layer should use this. The dependency overrides
    are reset after the test.
    """
    from app.deps import get_session
    from app.main import app

    def _get_session_override() -> Session:
        return db_session

    app.dependency_overrides[get_session] = _get_session_override
    yield TestClient(app)
    app.dependency_overrides.clear()
