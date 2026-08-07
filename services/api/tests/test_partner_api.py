"""Tests for ``GET /api/partner/orders`` (Bearer-key auth).

Mirrors the fixture pattern from ``test_customers_overview.py`` —
in-memory SQLite + a seeded User/Store pair, ``TestClient``, and a
monkeypatched ``get_session`` dep override. Each test stands up
fresh state so failure messages tell us which case regressed
(operator-facing auth, owner isolation, projection shape).

Test matrix:

  1. Issue a key via cookie auth (admin endpoint) → returns
     plaintext once + summary with id/prefix.
  2. List keys → the issued key shows up.
  3. Bearer auth on ``GET /api/partner/orders`` with the
     plaintext → 200 + the wire shape we promised the user.
  4. Source = "GF <region>" exactly matches the Store's region.
  5. Anonymised eaters surface empty name + phone to partners.
  6. Owner isolation: operator A's key never lists operator B's
     store orders.
  7. Wrong prefix → 401.
  8. Right prefix + wrong tail (bcrypt mismatch) → 401.
  9. Revoked key → 401 even with the right plaintext.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import COOKIE_NAME, SessionToken
from app.deps import get_session
from app.main import app
from app.models import OrderArchive, Store, StoreApiKey, User


# ── helpers ─────────────────────────────────────────────────────────────────


def _sample_payload(
    *,
    order_id: str,
    display_id: str,
    phone: str,
    name: str,
    total: str,
    state: str = "ORDER_IN_PREPARE",
) -> dict[str, Any]:
    """A round-4-shaped payload with itemInfo + eater + fare."""
    return {
        "order": {
            "orderID": order_id,
            "displayID": display_id,
            "state": state,
            "eater": {
                "ID": "u1",
                "name": name,
                "mobileNumber": phone,
                "address": "12 Le Loi, Q1",
                "comment": "",
            },
            "itemInfo": {
                "count": 2,
                "items": [
                    {
                        "itemID": "VNITE-1",
                        "name": "Phở bò",
                        "quantity": 1,
                        "priceDisplay": "65.000",
                        "modifierGroups": [],
                    },
                    {
                        "itemID": "VNITE-2",
                        "name": "Cà phê sữa đá",
                        "quantity": 2,
                        "priceDisplay": "25.000",
                        "modifierGroups": [],
                    },
                ],
            },
            "fare": {
                "currencySymbol": "₫",
                "totalDisplay": total,
                "subTotalDisplay": total,
                "taxDisplay": "0",
                "deliveryFeeDisplay": "0",
                "promotionDisplay": "0",
            },
            "times": {
                "createdAt": "2026-08-04T07:00:00.000Z",
                "acceptedAt": "2026-08-04T07:01:00.000Z",
            },
        },
    }


def _signed_cookie(user_id: int) -> str:
    token = SessionToken(user_id=user_id, exp=int(time.time()) + 86400 * 7)
    return token.to_signed(settings.session_secret)


def _make_engine():
    """Fresh in-memory SQLite with StaticPool so all Sessions share the DB.

    Mirror of ``_make_engine`` in test_customers_overview.py. The
    StaticPool is essential: without it, the FastAPI ``get_session``
    override would open a brand-new in-memory database per request
    and our seed rows would vanish between calls.
    """
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_user_store(
    engine,
    *,
    username: str = "merchant@example.com",
    merchant_id: str = "zeus_store:5-C6VKAT5GRK3CTT",
    name: str = "Test Store",
    region: str = "Đà Nẵng",
    address: str = "110 Hà Duy Phiên, Hòa Châu, Hòa Vang",
) -> tuple[int, int]:
    """Seed one User + one Store and return their ids."""
    with Session(engine) as s:
        owner = User(
            username=username,
            display_name="Merchant",
            password_hash="x",
            is_active=True,
        )
        s.add(owner)
        s.commit()
        s.refresh(owner)
        store = Store(
            owner_user_id=owner.id,
            merchant_id=merchant_id,
            name=name,
            address=address,
            region=region,
            encrypted_auth_token=b"x",
            encrypted_xray_token=b"x",
            encrypted_display_token=b"x",
        )
        s.add(store)
        s.commit()
        s.refresh(store)
        return owner.id, store.id


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def session_override():
    """Override ``get_session`` with a StaticPool-backed in-memory DB.

    Seeded with one User + one Store (region="Đà Nẵng"). Yields the
    engine so individual tests can insert OrderArchive rows on top.
    """
    engine = _make_engine()
    _seed_user_store(engine)

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    yield engine
    app.dependency_overrides.clear()


def _authed_client(engine) -> tuple[TestClient, int]:
    """TestClient with a signed session cookie for the seeded user."""
    with Session(engine) as s:
        user = s.exec(select(User)).first()
        assert user is not None
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(user.id))
        return client, user.id


def _seed_one_archive(
    engine,
    *,
    store_id: int,
    merchant_id: str,
    state: str = "ORDER_IN_PREPARE",
    phone: str = "0901234567",
    name: str = "Nguyen Van A",
    total: str = "115.000",
    order_id: str = "OID-1",
    display_id: str = "GF-1",
    minutes_ago: int = 10,
) -> None:
    """Insert one OrderArchive row directly via Session(engine)."""
    last_seen = datetime.utcnow() - timedelta(minutes=minutes_ago)
    first_seen = last_seen - timedelta(minutes=1)
    with Session(engine) as s:
        s.add(
            OrderArchive(
                store_id=store_id,
                merchant_id=merchant_id,
                order_id=order_id,
                display_id=display_id,
                state=state,
                detail_json=json.dumps(_sample_payload(
                    order_id=order_id,
                    display_id=display_id,
                    phone=phone,
                    name=name,
                    total=total,
                    state=state,
                )),
                first_seen_at=first_seen,
                last_seen_at=last_seen,
            )
        )
        s.commit()


# ── 1. Issue + list admin endpoints ────────────────────────────────────────


def test_admin_issue_returns_plaintext_once(session_override) -> None:
    """``POST /api/partner/keys`` returns plaintextKey + a summary."""
    client, _uid = _authed_client(session_override)
    resp = client.post(
        "/api/partner/keys",
        json={"merchantId": "zeus_store:5-C6VKAT5GRK3CTT", "label": "Posmate"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Plaintext is a one-shot secret — must start with "pulse_".
    plaintext = body["plaintextKey"]
    assert plaintext.startswith("pulse_")
    assert len(plaintext) > 32
    # Summary block has the bookkeeping fields.
    summary = body["summary"]
    assert summary["label"] == "Posmate"
    assert summary["keyPrefix"] == plaintext[:8]
    assert summary["storeId"] > 0
    assert summary["revokedAt"] is None
    assert summary["lastUsedAt"] is None


def test_admin_list_returns_only_owned_store_keys(session_override) -> None:
    """``GET /api/partner/keys`` returns keys for the operator's stores only."""
    # Issue two keys for the seeded store.
    client, _uid = _authed_client(session_override)
    client.post(
        "/api/partner/keys",
        json={"merchantId": "zeus_store:5-C6VKAT5GRK3CTT", "label": "A"},
    )
    client.post(
        "/api/partner/keys",
        json={"merchantId": "zeus_store:5-C6VKAT5GRK3CTT", "label": "B"},
    )
    # And one for a store the operator does NOT own.
    with Session(session_override) as s:
        s.add(
            Store(
                owner_user_id=9999,
                merchant_id="other-store",
                name="Other",
                encrypted_auth_token=b"x",
                encrypted_xray_token=b"x",
                encrypted_display_token=b"x",
            )
        )
        s.commit()
        # Plus a stray key on that other store for good measure.
        from app.core.security import hash_password
        s.add(
            StoreApiKey(
                store_id=99999,
                key_prefix="zzzzzz",
                key_hash=hash_password("pulse_zzzzzz"),
                label="stranger",
            )
        )
        s.commit()

    resp = client.get("/api/partner/keys")
    assert resp.status_code == 200, resp.text
    keys = resp.json()
    labels = sorted(k["label"] for k in keys)
    # Operator sees their two; never the stranger's.
    assert labels == ["A", "B"]


def test_admin_issue_returns_404_for_unowned_store(session_override) -> None:
    """Minting a key against someone else's merchant_id returns 404.

    Don't leak the existence of stores the operator doesn't own —
    404 (not 403) is intentional.
    """
    client, _uid = _authed_client(session_override)
    resp = client.post(
        "/api/partner/keys",
        json={"merchantId": "zeus_store:someone-else", "label": "x"},
    )
    assert resp.status_code == 404, resp.text


# ── 2. Bearer auth on GET /api/partner/orders ───────────────────────────────


def test_partner_orders_returns_wire_shape_with_bearer_token(
    session_override,
) -> None:
    """End-to-end happy path: issue a key, use it to GET orders.

    Verifies the wire shape the user asked for verbatim:
      customerName, phone, items[].name, items[].quantity,
      items[].priceDisplay, price, source="GF <region>",
      state, orderId, displayId, orderedAt.
    """
    client, _uid = _authed_client(session_override)
    # Seed two archive rows so we have something to project.
    with Session(session_override) as s:
        store = s.exec(select(Store)).first()
        assert store is not None
        store_id = store.id
        merchant_id = store.merchant_id
    _seed_one_archive(
        session_override,
        store_id=store_id,
        merchant_id=merchant_id,
        order_id="OID-A",
        display_id="GF-A",
        phone="0901111111",
        name="Alice",
        total="115.000",
        minutes_ago=5,
    )
    _seed_one_archive(
        session_override,
        store_id=store_id,
        merchant_id=merchant_id,
        order_id="OID-B",
        display_id="GF-B",
        phone="0902222222",
        name="Bob",
        total="230.000",
        state="ORDER_READY",
        minutes_ago=2,
    )

    # Issue a key.
    issue = client.post(
        "/api/partner/keys",
        json={"merchantId": merchant_id, "label": "happy-path"},
    )
    assert issue.status_code == 201
    plaintext = issue.json()["plaintextKey"]

    # Call the partner API with the bearer token.
    partner = TestClient(app)
    resp = partner.get(
        "/api/partner/orders",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    orders = body["orders"]
    # Most-recent first → OID-B.
    assert orders[0]["orderId"] == "OID-B"
    assert orders[1]["orderId"] == "OID-A"

    o = orders[0]
    assert o["customerName"] == "Bob"
    assert o["phone"] == "0902222222"
    # Items list: 2 line items (Phở bò + 2× Cà phê).
    assert len(o["items"]) == 2
    assert o["items"][0]["name"] == "Phở bò"
    assert o["items"][0]["quantity"] == 1
    assert o["items"][1]["name"] == "Cà phê sữa đá"
    assert o["items"][1]["quantity"] == 2
    assert o["items"][0]["priceDisplay"] == "65.000"
    # Price + source — verbatim user spec.
    assert o["price"] == "230.000"
    assert o["source"] == "GF Đà Nẵng"
    assert o["state"] == "ORDER_READY"
    assert o["orderedAt"].startswith("2026-08-04")


def test_partner_orders_anonymised_eater_surfaces_empty(
    session_override,
) -> None:
    """Grab's anonymisation marker (``name="***" + phone=""``) →
    empty customer / phone on the wire.
    """
    client, _uid = _authed_client(session_override)
    with Session(session_override) as s:
        store = s.exec(select(Store)).first()
        assert store is not None
        store_id = store.id
        merchant_id = store.merchant_id
    _seed_one_archive(
        session_override,
        store_id=store_id,
        merchant_id=merchant_id,
        order_id="OID-anon",
        display_id="GF-anon",
        phone="",
        name="***",
        total="99.000",
    )
    issue = client.post(
        "/api/partner/keys",
        json={"merchantId": merchant_id, "label": "anon"},
    )
    plaintext = issue.json()["plaintextKey"]

    partner = TestClient(app)
    resp = partner.get(
        "/api/partner/orders",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 200
    order = resp.json()["orders"][0]
    assert order["customerName"] == ""
    assert order["phone"] == ""


# ── 3. Auth failure modes ───────────────────────────────────────────────────


def test_partner_orders_missing_authorization_returns_401(
    session_override,
) -> None:
    """No Authorization header → 401 with WWW-Authenticate hint."""
    partner = TestClient(app)
    resp = partner.get("/api/partner/orders")
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("www-authenticate", "").lower() == "bearer"


def test_partner_orders_unknown_key_returns_401(session_override) -> None:
    """Right-format key, never-issued prefix → 401."""
    partner = TestClient(app)
    resp = partner.get(
        "/api/partner/orders",
        headers={"Authorization": "Bearer pulse_AAAAAAAAA"},
    )
    assert resp.status_code == 401, resp.text


def test_partner_orders_revoked_key_returns_401(session_override) -> None:
    """Revoke a key, then the bearer call returns 401 — bcrypt never reached."""
    client, _uid = _authed_client(session_override)
    with Session(session_override) as s:
        store = s.exec(select(Store)).first()
        assert store is not None
        merchant_id = store.merchant_id
    issue = client.post(
        "/api/partner/keys",
        json={"merchantId": merchant_id, "label": "revoke-me"},
    )
    plaintext = issue.json()["plaintextKey"]
    key_id = issue.json()["summary"]["id"]

    # Revoke via DELETE.
    resp = client.delete(f"/api/partner/keys/{key_id}")
    assert resp.status_code == 204, resp.text

    partner = TestClient(app)
    after = partner.get(
        "/api/partner/orders",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert after.status_code == 401


# ── 4. Owner isolation across operators ─────────────────────────────────────


def test_partner_orders_only_sees_the_issuing_store(
    session_override,
) -> None:
    """A key issued for store A must NEVER return store B's orders."""
    # Seed a SECOND operator + store under the same engine.
    with Session(session_override) as s:
        op_b = User(
            username="b@example.com",
            display_name="OpB",
            password_hash="x",
            is_active=True,
        )
        s.add(op_b)
        s.commit()
        s.refresh(op_b)
        store_b = Store(
            owner_user_id=op_b.id,
            merchant_id="opB-store",
            name="Op B Store",
            region="TP.HCM",
            address="1 Lê Lợi, Quận 1, TP.HCM",
            encrypted_auth_token=b"x",
            encrypted_xray_token=b"x",
            encrypted_display_token=b"x",
        )
        s.add(store_b)
        s.commit()
        s.refresh(store_b)
        store_a = s.exec(
            select(Store).where(Store.merchant_id == "zeus_store:5-C6VKAT5GRK3CTT")
        ).first()
        assert store_a is not None

    # Operator A issues a key for store A.
    client_a, _uid = _authed_client(session_override)
    issue_a = client_a.post(
        "/api/partner/keys",
        json={"merchantId": store_a.merchant_id, "label": "storeA"},
    )
    plaintext_a = issue_a.json()["plaintextKey"]

    # Seed an archive row in store B; the partner key for A must not see it.
    _seed_one_archive(
        session_override,
        store_id=store_b.id,
        merchant_id=store_b.merchant_id,
        order_id="OID-B-only",
        display_id="GF-B-only",
        phone="0909999999",
        name="Should Not Appear",
        total="50.000",
    )
    _seed_one_archive(
        session_override,
        store_id=store_a.id,
        merchant_id=store_a.merchant_id,
        order_id="OID-A-only",
        display_id="GF-A-only",
        phone="0901111111",
        name="Should Appear",
        total="75.000",
    )

    partner = TestClient(app)
    resp = partner.get(
        "/api/partner/orders",
        headers={"Authorization": f"Bearer {plaintext_a}"},
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()["orders"]
    # Exactly ONE row, and it must be store A's. Store B's order must
    # NEVER surface under A's key.
    assert len(orders) == 1
    assert orders[0]["orderId"] == "OID-A-only"
    # And its source carries A's region (Đà Nẵng), not B's (TP.HCM).
    assert orders[0]["source"] == "GF Đà Nẵng"