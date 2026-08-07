"""Tests for ``total_orders`` field on ``GET /api/finance/summary``.

The field surfaces the locally-archived ``OrderArchive`` row count
within ``[start_date, end_date]`` to the dashboard "Tổng đơn" KPI
on the overview page. Tests cover:

  1. **Happy path**: 3 OrderArchive rows in range → ``total_orders == 3``
  2. **Range filtering**: orders outside the range are excluded
  3. **Owner isolation**: a second user's orders are not counted
  4. **Bad range**: ``start_date > end_date`` → 400
  5. **Field present**: ``total_orders`` is always in the response body

We can't exercise the live Grab path here, so we monkeypatch
``grab.endpoints.finance.get_financial_summary`` to return a
deterministic payload, then assert against the projection. This
keeps the test fast, deterministic, and free of any real Grab auth.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.security import COOKIE_NAME, SessionToken, encrypt_token
from app.deps import get_session
from app.main import app
from app.models import AuditLog, OrderArchive, Store, User  # noqa: F401  (registers tables)


# ── helpers ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _configured_settings():
    """Make sure ``Settings.token_encryption_key`` and ``session_secret``
    are populated before any test that touches ``get_grab_client`` /
    ``encrypt_token`` runs.

    The router goes through ``get_grab_client`` which calls
    ``decrypt_token`` on the seeded store's auth token — without a
    real Fernet key that's a hard ``AttributeError`` (``bytes`` vs
    ``str``). We assign keys directly to the singleton here.
    """
    settings.token_encryption_key = settings.generate_fernet_key()
    settings.session_secret = settings.generate_session_secret()
    yield


def _make_engine():
    """StaticPool-backed in-memory SQLite — all Sessions share the DB.

    Mirror of the pattern used in ``test_partner_api.py`` /
    ``test_customers_overview.py``. The StaticPool is essential: a
    vanilla ``sqlite://`` engine creates a brand-new in-memory DB
    per Session, so seeded rows would vanish between requests.
    """
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_user(
    engine,
    *,
    username: str,
    merchant_id: str = "zeus_store:5-C6VKAT5GRK3CTT",
) -> tuple[int, int]:
    """Insert one User + one Store owned by that user, return their ids.

    The auth/xray/display tokens are Fernet-encrypted via
    ``encrypt_token`` so ``get_grab_client`` can decrypt them at
    request time (without this it raises ``AttributeError: 'bytes'
    object has no attribute 'encode'``).
    """
    encrypted = encrypt_token("fake-token-for-tests")
    with Session(engine) as s:
        owner = User(
            username=username,
            display_name=username,
            password_hash="x",
            is_active=True,
        )
        s.add(owner)
        s.commit()
        s.refresh(owner)
        store = Store(
            owner_user_id=owner.id,
            merchant_id=merchant_id,
            name="Test Store",
            encrypted_auth_token=encrypted,
            encrypted_xray_token=encrypted,
            encrypted_display_token=encrypted,
        )
        s.add(store)
        s.commit()
        s.refresh(store)
        return owner.id, store.id


def _signed_cookie(user_id: int) -> str:
    token = SessionToken(user_id=user_id, exp=int(time.time()) + 86400 * 7)
    return token.to_signed(settings.session_secret)


def _seed_archive(
    engine,
    *,
    store_id: int,
    merchant_id: str,
    order_id: str,
    first_seen_at: datetime,
    state: str = "ORDER_IN_PREPARE",
) -> None:
    """Insert a single OrderArchive row directly into the shared engine."""
    with Session(engine) as s:
        s.add(
            OrderArchive(
                store_id=store_id,
                merchant_id=merchant_id,
                order_id=order_id,
                display_id=order_id.replace("OID-", "GF-"),
                state=state,
                first_seen_at=first_seen_at,
                last_seen_at=first_seen_at,
                detail_json="{}",
            )
        )
        s.commit()


def _empty_grab_payload(start_date: str, end_date: str) -> dict[str, Any]:
    """Return a minimal-but-valid Grab finance summary payload.

    Real Grab returns a recursive ``uiBreakdown`` tree; for these
    tests we just need the top-level shape so the router's
    projection doesn't blow up on missing fields.
    """
    return {
        "data": {
            "currency": {"name": "VND"},
            "salesBalance": "+0₫",
            "earningsBalance": "+0₫",
            "uiBreakdown": [],
        }
    }


@pytest.fixture
def fake_grab(monkeypatch):
    """Stub ``get_financial_summary`` so no real Grab call is made."""

    async def _fake(client, start_date: str, end_date: str):  # noqa: ARG001
        return _empty_grab_payload(start_date, end_date)

    monkeypatch.setattr(
        "app.routers.finance.get_financial_summary",
        _fake,
    )


# ── 1. happy path ───────────────────────────────────────────────────────────


def test_total_orders_counts_in_range_rows(fake_grab):
    """3 OrderArchive rows inside the range → total_orders == 3."""
    engine = _make_engine()
    owner_id, store_id = _seed_user(
        engine, username="merchant@example.com",
    )

    in_range = datetime(2026, 8, 4, 10, 0, 0)
    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-1",
        first_seen_at=in_range,
    )
    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-2",
        first_seen_at=in_range + timedelta(hours=2),
    )
    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-3",
        first_seen_at=in_range + timedelta(hours=4),
    )

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(owner_id))
        resp = client.get(
            "/api/finance/summary",
            params={"start_date": "2026-08-04", "end_date": "2026-08-04"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_orders"] == 3
    assert body["date_range"]["from"] == "2026-08-04"
    assert body["date_range"]["to"] == "2026-08-04"


# ── 2. range filtering ──────────────────────────────────────────────────────


def test_total_orders_excludes_out_of_range_rows(fake_grab):
    """Orders whose ``first_seen_at`` falls outside the window are skipped."""
    engine = _make_engine()
    owner_id, store_id = _seed_user(
        engine, username="merchant@example.com",
    )

    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-old",
        first_seen_at=datetime(2026, 7, 30, 12, 0, 0),
    )
    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-future",
        first_seen_at=datetime(2026, 8, 10, 12, 0, 0),
    )
    _seed_archive(
        engine,
        store_id=store_id,
        merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
        order_id="OID-in",
        first_seen_at=datetime(2026, 8, 3, 9, 30, 0),
    )

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(owner_id))
        resp = client.get(
            "/api/finance/summary",
            params={"start_date": "2026-08-01", "end_date": "2026-08-05"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_orders"] == 1


# ── 3. owner isolation ──────────────────────────────────────────────────────


def test_total_orders_scopes_to_owner(fake_grab):
    """A second user's orders must NOT inflate the first user's count."""
    engine = _make_engine()
    owner_a, store_a = _seed_user(
        engine, username="a@example.com", merchant_id="zeus_store:A",
    )
    _seed_user(engine, username="b@example.com", merchant_id="zeus_store:B")

    # Both stores have orders within range; only A's should count.
    with Session(engine) as s:
        store_b = s.exec(select(Store).where(Store.merchant_id == "zeus_store:B")).one()

    in_range = datetime(2026, 8, 4, 10, 0, 0)
    _seed_archive(
        engine,
        store_id=store_a,
        merchant_id="zeus_store:A",
        order_id="OID-A1",
        first_seen_at=in_range,
    )
    _seed_archive(
        engine,
        store_id=store_a,
        merchant_id="zeus_store:A",
        order_id="OID-A2",
        first_seen_at=in_range,
    )
    _seed_archive(
        engine,
        store_id=store_b.id,
        merchant_id="zeus_store:B",
        order_id="OID-B1",
        first_seen_at=in_range,
    )
    _seed_archive(
        engine,
        store_id=store_b.id,
        merchant_id="zeus_store:B",
        order_id="OID-B2",
        first_seen_at=in_range,
    )

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(owner_a))
        resp = client.get(
            "/api/finance/summary",
            params={"start_date": "2026-08-04", "end_date": "2026-08-04"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_orders"] == 2


# ── 4. bad range ────────────────────────────────────────────────────────────


def test_finance_summary_rejects_inverted_range(fake_grab):
    """``start_date > end_date`` → 400 with the operator-facing message."""
    engine = _make_engine()
    owner_id, _ = _seed_user(engine, username="merchant@example.com")

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(owner_id))
        resp = client.get(
            "/api/finance/summary",
            params={"start_date": "2026-08-10", "end_date": "2026-08-01"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    body = resp.json()
    detail = body.get("detail") or {}
    assert detail.get("code") == "invalid_date_range"


# ── 5. field present ────────────────────────────────────────────────────────


def test_total_orders_field_always_present(fake_grab):
    """``total_orders`` lives on every response, including when zero.

    The dashboard reads ``data.total_orders`` directly to render the
    "Tổng đơn" tile; if the field ever goes missing (e.g. legacy
    client, schema drift) the tile breaks. Pin it down with an
    explicit assertion.
    """
    engine = _make_engine()
    owner_id, _ = _seed_user(engine, username="merchant@example.com")

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(owner_id))
        resp = client.get(
            "/api/finance/summary",
            params={"start_date": "2026-08-01", "end_date": "2026-08-07"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total_orders" in body
    assert body["total_orders"] == 0
    assert isinstance(body["total_orders"], int)
