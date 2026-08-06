"""Tests for the ``GET /api/customers/overview`` aggregation.

Mirrors the test style of ``test_order_archive.py`` — in-memory
SQLite + a seeded User/Store pair, then drive the route via
``TestClient`` (no network, no scheduler). Covers:

  1. Empty store → empty three-list response.
  2. Two orders under the same phone → one CustomerSummary
     with orderCount=2 and the latest order's state wins.
  3. Two ``merchant_id`` values → two SourceSummary entries with
     correct counts + distinctCustomers counts.
  4. Per-order hydration: valid row hydrates via OrderDetailLite,
     malformed JSON row is skipped silently from the orders list
     but still counts under sources (merchant_id is in a column,
     not the JSON blob).
  5. Store-A isolation: rows in store B must not surface in the
     store-A response.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.deps import get_session
from app.main import app
from app.models import OrderArchive, Store, User
from app.core.security import COOKIE_NAME, SessionToken
from app.schemas.customers import CustomersOverviewResponse


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
                "count": 1,
                "items": [
                    {
                        "itemID": "VNITE-1",
                        "name": "Phở bò",
                        "quantity": 1,
                        "priceDisplay": total,
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
    """Build a signed session cookie value for ``user_id``."""
    token = SessionToken(user_id=user_id, exp=int(time.time()) + 86400 * 7)
    return token.to_signed(settings.session_secret)


def _make_engine():
    """Fresh in-memory SQLite engine with all tables registered.

    Uses ``StaticPool`` so every ``Session(engine)`` reuses the
    same underlying connection — without this, each new Session
    would get a brand-new empty in-memory DB and the test's
    seed rows would vanish the moment the FastAPI dep opens a
    fresh session. With ``StaticPool``, the connection pool
    size is 1 and every Session sees the same SQLite handle.
    """
    from app.models import AuditLog  # noqa: F401 — registers table
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_one_user_one_store(engine) -> None:
    """Seed ``engine`` with one User + one Store, return their ids."""
    with Session(engine) as s:
        owner = User(
            username="merchant@example.com",
            display_name="Merchant",
            password_hash="x",
            is_active=True,
        )
        s.add(owner)
        s.commit()
        s.refresh(owner)
        store = Store(
            owner_user_id=owner.id,
            merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
            name="Test Store",
            encrypted_auth_token=b"x",
            encrypted_xray_token=b"x",
            encrypted_display_token=b"x",
        )
        s.add(store)
        s.commit()
        s.refresh(store)
        return owner.id, store.id


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def session_override():
    """Override the FastAPI ``get_session`` dep with an in-memory SQLite session.

    Mirrors the ``session`` fixture in ``test_order_archive.py``
    so the same `WriteArchiveRows`-style seeding works for the
    customers router. Yields the engine so individual tests can
    seed their own rows via ``Session(engine)``.
    """
    engine = _make_engine()
    _seed_one_user_one_store(engine)

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    yield engine
    app.dependency_overrides.clear()


def _authed_client(engine) -> TestClient:
    """Build a TestClient with a signed session cookie for the seeded user."""
    with Session(engine) as s:
        user = s.exec(select(User)).first()
        assert user is not None
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, _signed_cookie(user.id))
        return client


# ── 1. empty store ───────────────────────────────────────────────────────────


def test_overview_returns_empty_lists_when_store_has_no_archives(
    session_override,
) -> None:
    """A fresh store (no archive rows yet) returns three empty lists, not 500.

    Regression guard for the ``metadata.create_all(checkfirst=True)``
    startup path: the cron hasn't written anything yet, but the
    menu must still render an empty-state.
    """
    client = _authed_client(session_override)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200, resp.text
    body = CustomersOverviewResponse.model_validate(resp.json())
    assert body.customers == []
    assert body.sources == []
    assert body.orders == []


# ── 2. customer grouping ─────────────────────────────────────────────────────


def test_overview_groups_by_mobile_number(session_override) -> None:
    """Two orders from the same phone → one CustomerSummary with orderCount=2."""
    from app.core.scheduler import _write_archive_rows

    eng = session_override
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None

        t0 = datetime.utcnow() - timedelta(hours=2)
        t1 = datetime.utcnow() - timedelta(hours=1)
        # ``_write_archive_rows`` expects 4-tuples
        # ``(order_id, display_id, state, detail_json)`` — the per-row
        # timestamp comes from the ``now`` param (the SAME ``now`` for
        # all rows in this batch). We can't insert at t0 and t1 in a
        # single batch call, so use t1 for both rows and instead set
        # ``last_seen_at`` manually afterwards.
        rows = [
            (
                "OID-1", "GF-1", "ORDER_IN_PREPARE",
                json.dumps(_sample_payload(
                    order_id="OID-1",
                    display_id="GF-1",
                    phone="0901234567",
                    name="Nguyen Van A",
                    total="65.000",
                )),
            ),
            (
                "OID-2", "GF-2", "ORDER_READY",
                json.dumps(_sample_payload(
                    order_id="OID-2",
                    display_id="GF-2",
                    phone="0901234567",
                    name="Nguyen Van A",
                    total="120.000",
                    state="ORDER_READY",
                )),
            ),
        ]
        _write_archive_rows(
            session=sess,
            store_id=store.id,
            merchant_id=store.merchant_id,
            rows=rows,
            now=t1,
        )
        # Backdate OID-1's last_seen to t0 so the "newest order wins"
        # assertions actually exercise the sort.
        from sqlmodel import select as _sel
        sess.exec(_sel(OrderArchive).where(OrderArchive.order_id == "OID-1")).one().last_seen_at = t0
        sess.commit()
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    # One customer, two orders.
    assert len(body.customers) == 1, f"expected 1 customer, got {len(body.customers)}"
    c = body.customers[0]
    assert c.mobile_number == "0901234567"
    assert c.name == "Nguyen Van A"
    assert c.order_count == 2
    # The most-recent order (t1) wins the "last state" badge.
    assert c.last_state == "ORDER_READY"
    # The most-recent order's total fills the card.
    assert c.total_display == "120.000"

    # Two orders in the orders list, sorted by last_seen desc.
    assert len(body.orders) == 2
    assert body.orders[0].order_id == "OID-2", "newest order should sort first"


# ── 3. source grouping ───────────────────────────────────────────────────────


def test_overview_groups_by_merchant_id(session_override) -> None:
    """Two distinct merchant_ids → two SourceSummary entries with correct counts."""
    eng = session_override
    now = datetime.utcnow()
    store_merchant_id = ""
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None
        # Capture the merchant_id string BEFORE the with-block exits —
        # the SQLAlchemy session will detach the Store instance and
        # any attribute access after closing the session raises
        # ``DetachedInstanceError``.
        store_merchant_id = store.merchant_id
        store_id = store.id

        # Two rows under our test merchant_id.
        for i, (oid, phone, name, total) in enumerate([
            ("OID-1", "0901111111", "A", "10.000"),
            ("OID-2", "0902222222", "B", "20.000"),
        ]):
            sess.add(OrderArchive(
                store_id=store_id,
                merchant_id=store_merchant_id,
                order_id=oid,
                display_id=f"GF-{i+1}",
                state="ORDER_IN_PREPARE",
                detail_json=json.dumps(_sample_payload(
                    order_id=oid,
                    display_id=f"GF-{i+1}",
                    phone=phone,
                    name=name,
                    total=total,
                )),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            ))
        # And one row under a different merchant_id.
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id="other:9-XYZ",
            order_id="OID-3",
            display_id="GF-3",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-3",
                display_id="GF-3",
                phone="0903333333",
                name="C",
                total="30.000",
            )),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    by_id = {s.merchant_id: s for s in body.sources}
    assert set(by_id) == {store_merchant_id, "other:9-XYZ"}
    assert by_id[store_merchant_id].order_count == 2
    assert by_id[store_merchant_id].distinct_customers == 2
    assert by_id["other:9-XYZ"].order_count == 1
    assert by_id["other:9-XYZ"].distinct_customers == 1


# ── 4. malformed JSON skipped from orders list, still counted in sources ─────


def test_overview_skips_bad_json_orders_but_counts_sources(session_override) -> None:
    """A row with malformed JSON must NOT appear in the orders list
    but SHOULD still count under sources (merchant_id is a column,
    not in the JSON blob)."""
    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None

        sess.add(OrderArchive(
            store_id=store.id,
            merchant_id=store.merchant_id,
            order_id="OID-bad",
            display_id="GF-bad",
            state="ORDER_IN_PREPARE",
            detail_json="{not json",
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.add(OrderArchive(
            store_id=store.id,
            merchant_id=store.merchant_id,
            order_id="OID-good",
            display_id="GF-good",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-good",
                display_id="GF-good",
                phone="0901234567",
                name="A",
                total="10.000",
            )),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    # Bad JSON row skipped from orders, good row hydrated.
    order_ids = {o.order_id for o in body.orders}
    assert "OID-bad" not in order_ids
    assert "OID-good" in order_ids

    # Sources still count BOTH rows because merchant_id is on the column.
    assert len(body.sources) == 1
    assert body.sources[0].order_count == 2
    # distinctCustomers: bad-JSON row's eater is unknown → empty phone
    # bucket; good-JSON row → "0901234567" bucket → 2 distinct.
    assert body.sources[0].distinct_customers == 2


# ── 5. store-A isolation ────────────────────────────────────────────────────


def test_overview_does_not_leak_across_stores(session_override) -> None:
    """Rows in store B must not surface in the store-A response.

    Same multi-tenant guardrail as the orders router
    (``_load_archive_for_order_ids_respects_store_scope`` test).
    """
    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        owner = sess.exec(select(User)).first()
        assert owner is not None
        store_b = Store(
            owner_user_id=owner.id,
            merchant_id="other:9-XYZ",
            name="Other Store",
            encrypted_auth_token=b"x",
            encrypted_xray_token=b"x",
            encrypted_display_token=b"x",
        )
        sess.add(store_b)
        sess.commit()
        sess.refresh(store_b)

        sess.add(OrderArchive(
            store_id=store_b.id,
            merchant_id=store_b.merchant_id,
            order_id="OID-storeB",
            display_id="GF-B",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-storeB",
                display_id="GF-B",
                phone="0909999999",
                name="B-only customer",
                total="50.000",
            )),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    # store B's row must not appear in store A's view.
    assert body.orders == [], (
        "store A must not see store B's archive rows — multi-tenant isolation"
    )
    assert body.customers == []
    assert body.sources == []


# ── 6. empty-phone bucket ────────────────────────────────────────────────────


def test_overview_groups_rows_without_phone_into_empty_bucket(session_override) -> None:
    """Rows with missing ``eater.mobileNumber`` must aggregate into a
    single empty-phone bucket — not crash, not leak across buckets.

    Mirrors a real-world case where Grab returns orders without an
    eater block (3rd-party deliveries, test kitchens, etc.). The
    customer card should still surface so the merchant can see
    "phantom" orders that landed without a customer attached.
    """
    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None
        store_merchant_id = store.merchant_id
        store_id = store.id

        # Two rows under one merchant, both with NO phone in the payload.
        for i, oid in enumerate(["OID-NP-1", "OID-NP-2"]):
            payload = _sample_payload(
                order_id=oid,
                display_id=f"GF-NP-{i+1}",
                phone="",  # ← the empty-phone case
                name="",
                total="45.000",
            )
            # Strip the eater block entirely on the second row to also
            # exercise the "missing eater" path.
            if i == 1:
                payload["order"].pop("eater", None)

            sess.add(OrderArchive(
                store_id=store_id,
                merchant_id=store_merchant_id,
                order_id=oid,
                display_id=f"GF-NP-{i+1}",
                state="ORDER_IN_PREPARE",
                detail_json=json.dumps(payload),
                first_seen_at=now,
                last_seen_at=now + timedelta(seconds=i),  # NP-2 is later
                created_at=now,
                updated_at=now,
            ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    # Both rows land in ONE empty-phone customer card.
    empties = [c for c in body.customers if c.mobile_number == ""]
    assert len(empties) == 1, (
        f"expected exactly 1 empty-phone customer, got {len(empties)}: "
        f"{[c.mobile_number for c in body.customers]}"
    )
    assert empties[0].order_count == 2

    # Orders list has both rows, sorted newest-first by last_seen.
    order_ids = [o.order_id for o in body.orders]
    assert order_ids[0] == "OID-NP-2", "newest empty-phone row should sort first"
    assert order_ids[1] == "OID-NP-1"

    # Sources: one merchant, one distinct customer (the empty bucket).
    assert len(body.sources) == 1
    assert body.sources[0].order_count == 2
    assert body.sources[0].distinct_customers == 1


# ── 7. merchant-bad-JSON isolation ───────────────────────────────────────────


def test_overview_bad_json_row_does_not_pollute_customer_bucket(session_override) -> None:
    """A row with malformed JSON for ONE merchant must NOT collapse
    the other merchant's customer count.

    Regression guard for finding #3: the source-bucket scan runs on
    every row (merchant_id is on the column), but the customer
    bucket skips bad-JSON rows. Both behaviours must coexist for the
    same row without the bad-JSON row leaking into a "phantom"
    customer under a different merchant.
    """
    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None
        store_merchant_id = store.merchant_id
        store_id = store.id

        # Good row under our merchant_id — phone "0901111111".
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id=store_merchant_id,
            order_id="OID-good",
            display_id="GF-good",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-good",
                display_id="GF-good",
                phone="0901111111",
                name="A",
                total="10.000",
            )),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        # Bad-JSON row under the SAME merchant_id — eater is unknown.
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id=store_merchant_id,
            order_id="OID-bad",
            display_id="GF-bad",
            state="ORDER_IN_PREPARE",
            detail_json="{not json",
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        # Good row under a DIFFERENT merchant_id — phone "0902222222".
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id="other:9-XYZ",
            order_id="OID-other",
            display_id="GF-other",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-other",
                display_id="GF-other",
                phone="0902222222",
                name="B",
                total="20.000",
            )),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200
    body = CustomersOverviewResponse.model_validate(resp.json())

    # Exactly 2 customers: the two phones, NO phantom empty-phone entry
    # carrying the bad-JSON row (the bad-JSON row is a "" phone key,
    # which is its own bucket — and we assert it exists but is empty
    # for the bad row alone).
    phones = sorted(c.mobile_number for c in body.customers)
    assert phones == ["0901111111", "0902222222"], (
        f"unexpected customer list: {phones} "
        "(bad-JSON row must NOT pollute other merchants' customers)"
    )

    # Sources: 2 merchants, distinct counts reflect the per-row fan-out.
    by_id = {s.merchant_id: s for s in body.sources}
    assert by_id[store_merchant_id].order_count == 2  # good + bad
    assert by_id[store_merchant_id].distinct_customers == 2  # "0901111111" + "" (unknown)
    assert by_id["other:9-XYZ"].order_count == 1
    assert by_id["other:9-XYZ"].distinct_customers == 1

    # Orders list: only the 2 good rows; bad-JSON row skipped silently.
    order_ids = {o.order_id for o in body.orders}
    assert "OID-bad" not in order_ids
    assert order_ids == {"OID-good", "OID-other"}


# ── 9. source address lookup (regression for "missing branch address") ────────


def test_overview_sources_include_store_address(session_override) -> None:
    """Each ``SourceSummary`` must carry ``Store.address`` for its merchant_id.

    Regression guard for the "Nguồn tab missing branch address" fix.
    Covers three cases:
      * merchant_id matching the user's Store → address surfaced
      * merchant_id with NO matching Store → empty address (not 500)
      * empty-string merchant_id → empty address (no store can match ``""``)
    """
    from app.core.scheduler import _write_archive_rows

    eng = session_override
    now = datetime.utcnow()
    store_merchant_id = ""
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None
        store.address = "123 Nguyễn Huệ, Q1, HCM"  # the branch address
        sess.add(store)
        sess.commit()
        store_merchant_id = store.merchant_id
        store_id = store.id

        # Row under OUR store → has address.
        _write_archive_rows(
            session=sess,
            store_id=store_id,
            merchant_id=store_merchant_id,
            rows=[(
                "OID-A1", "GF-A1", "ORDER_IN_PREPARE",
                json.dumps(_sample_payload(
                    order_id="OID-A1", display_id="GF-A1",
                    phone="0901111111", name="A", total="10.000",
                )),
            )],
            now=now,
        )
        # Row under an UNKNOWN merchant_id (no Store row) → empty address.
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id="ghost:0-NOPE",
            order_id="OID-A2", display_id="GF-A2",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-A2", display_id="GF-A2",
                phone="0902222222", name="B", total="20.000",
            )),
            first_seen_at=now, last_seen_at=now,
            created_at=now, updated_at=now,
        ))
        # Row with EMPTY merchant_id → empty address (no store can match "").
        sess.add(OrderArchive(
            store_id=store_id,
            merchant_id="",
            order_id="OID-A3", display_id="GF-A3",
            state="ORDER_IN_PREPARE",
            detail_json=json.dumps(_sample_payload(
                order_id="OID-A3", display_id="GF-A3",
                phone="0903333333", name="C", total="30.000",
            )),
            first_seen_at=now, last_seen_at=now,
            created_at=now, updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200, resp.text
    body = CustomersOverviewResponse.model_validate(resp.json())

    by_id = {s.merchant_id: s for s in body.sources}
    assert by_id[store_merchant_id].address == "123 Nguyễn Huệ, Q1, HCM"
    assert by_id["ghost:0-NOPE"].address == ""
    assert by_id[""].address == ""


# ── 9b. source name fallback (regression for "address still missing") ────────


def test_overview_sources_include_store_name_fallback(session_override) -> None:
    """``SourceSummary.name`` carries ``Store.name`` so the frontend can use
    it as a subtitle when ``Store.address`` is empty.

    Regression guard for the round-3 "Nguồn tab still shows blank
    subtitle" fix. Covers the exact user scenario: a Store with
    ``address=""`` (the registration default in ``routers/auth.py``)
    but a populated ``name`` (the merchant's shop name). The card
    on the web app shows the name under the merchant_id so the
    merchant can identify the branch without leaving the page.
    """
    from app.core.scheduler import _write_archive_rows

    eng = session_override
    now = datetime.utcnow()
    store_merchant_id = ""
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None
        # Simulate the production state: address empty (auth.py
        # creates Store with address="" and Grab's
        # business_attributes doesn't always populate it), name
        # populated from the registration form.
        store.address = ""
        store.name = "Trường Bào Ngư - Súp Bào Ngư Vi Cá T"
        sess.add(store)
        sess.commit()
        store_merchant_id = store.merchant_id
        store_id = store.id

        _write_archive_rows(
            session=sess,
            store_id=store_id,
            merchant_id=store_merchant_id,
            rows=[(
                "OID-N1", "GF-N1", "ORDER_IN_PREPARE",
                json.dumps(_sample_payload(
                    order_id="OID-N1", display_id="GF-N1",
                    phone="0901111111", name="A", total="10.000",
                )),
            )],
            now=now,
        )
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200, resp.text
    body = CustomersOverviewResponse.model_validate(resp.json())

    src = next(s for s in body.sources if s.merchant_id == store_merchant_id)
    assert src.address == ""  # empty (the user's actual scenario)
    assert src.name == "Trường Bào Ngư - Súp Bào Ngư Vi Cá T"


# ── 8. orders tab renders the items list (regression for "missing items") ────


def test_overview_orders_tab_includes_items_from_archived_detail(session_override) -> None:
    """The "Thông tin đơn hàng" tab on the customers page must surface
    ``detail.itemInfo.items[]`` (name + quantity + priceDisplay) for
    every archived order — not just ``itemInfo.count``.

    Regression for the user-reported bug: the tab was rendering only
    the order count + total, never the actual food items, so the
    merchant could not see "Phở bò" / "Cà phê sữa đá" / etc.

    We also assert the wire shape is camelCase end-to-end (FastAPI
    Pydantic alias), so the dashboard's ``OrderRow.items.map(...)``
    receives the items it expects.
    """
    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None

        # Seed an ORDER_COMPLETED archive row with TWO items so we can
        # assert the items[] array carries both entries through the
        # wire shape.
        payload = {
            "order": {
                "orderID": "OID-ITEMS",
                "displayID": "GF-ITEMS",
                "state": "ORDER_COMPLETED",
                "eater": {
                    "ID": "u1",
                    "name": "Tran Thi B",
                    "mobileNumber": "0905555555",
                    "address": "45 Tran Hung Dao",
                    "comment": "",
                },
                "itemInfo": {
                    "count": 2,
                    "items": [
                        {
                            "itemID": "VNITE-PHO",
                            "name": "Phở bò",
                            "quantity": 1,
                            "priceDisplay": "65.000",
                            "modifierGroups": [],
                        },
                        {
                            "itemID": "VNITE-CAFE",
                            "name": "Cà phê sữa đá",
                            "quantity": 2,
                            "priceDisplay": "30.000",
                            "modifierGroups": [],
                        },
                    ],
                },
                "fare": {
                    "currencySymbol": "₫",
                    "totalDisplay": "125.000",
                    "subTotalDisplay": "120.000",
                    "taxDisplay": "0",
                    "deliveryFeeDisplay": "5.000",
                    "promotionDisplay": "0",
                },
                "times": {
                    "createdAt": "2026-08-06T07:00:00.000Z",
                    "acceptedAt": "2026-08-06T07:01:00.000Z",
                },
            },
        }
        sess.add(OrderArchive(
            store_id=store.id,
            merchant_id=store.merchant_id,
            order_id="OID-ITEMS",
            display_id="GF-ITEMS",
            state="ORDER_COMPLETED",
            detail_json=json.dumps(payload),
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        ))
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200, resp.text
    # Parse the RAW JSON (not the schema-validated model) so we can
    # assert the wire-shape keys (itemInfo / itemID / priceDisplay) —
    # the pydantic validator strips aliases when we round-trip
    # through the Python-attribute schema.
    raw = resp.json()
    orders = raw["orders"]
    assert len(orders) == 1, f"expected 1 order in wire shape, got {len(orders)}"
    order = orders[0]

    # State propagated end-to-end (the user-reported "stuck preparing"
    # bug — the cron now upserts cancelled/completed via daily-reports,
    # so this row should hydrate as ORDER_COMPLETED, not ORDER_IN_PREPARE).
    assert order["state"] == "ORDER_COMPLETED", (
        f"state must hydrate from the archive row, got {order['state']!r} — "
        "this is the regression test for the 'state stuck at preparing' bug"
    )

    # The detail block exposes itemInfo.items[] (camelCase wire shape).
    detail = order["detail"]
    assert "itemInfo" in detail, "wire shape must expose itemInfo"
    assert "items" in detail["itemInfo"], "itemInfo must carry items[]"
    items = detail["itemInfo"]["items"]
    assert len(items) == 2, f"expected 2 items, got {len(items)}: {items!r}"

    # Items carry name + quantity + priceDisplay in the wire shape.
    names = sorted(i["name"] for i in items)
    assert names == ["Cà phê sữa đá", "Phở bò"], (
        f"items must carry the food names in wire shape, got {names}"
    )
    by_name = {i["name"]: i for i in items}
    assert by_name["Phở bò"]["quantity"] == 1
    assert by_name["Phở bò"]["priceDisplay"] == "65.000"
    assert by_name["Cà phê sữa đá"]["quantity"] == 2
    assert by_name["Cà phê sữa đá"]["priceDisplay"] == "30.000"

    # Eater block also survives the round-trip — the dashboard renders
    # name + phone from the hydrated detail.
    assert detail["eater"]["name"] == "Tran Thi B"
    assert detail["eater"]["mobileNumber"] == "0905555555"


# ── 9c. anonymised eater block (regression for "missing name/phone") ────────


def test_overview_orders_pass_through_anonymised_eater_block(session_override) -> None:
    """Grab's per-order detail endpoint anonymises some cancelled /
    completed orders: ``name`` arrives as the literal string ``"***"``
    and ``mobileNumber`` is empty. The backend must faithfully
    surface those values (the dashboard renders "Khách ẩn danh" as
    the customer label) rather than mangling them.

    Regression guard for the round-3 "Thông tin đơn hàng tab shows
    three dots instead of name" fix — locks in the wire shape so
    the frontend's anonymisation check has stable input.
    """
    from app.core.scheduler import _write_archive_rows

    eng = session_override
    now = datetime.utcnow()
    with Session(eng) as sess:
        store = sess.exec(select(Store)).first()
        assert store is not None

        # Mirror the exact eater block from the production archive:
        # name="***", mobileNumber="", address=None.
        payload = {
            "order": {
                "orderID": "OID-ANON",
                "displayID": "GF-ANON",
                "state": "ORDER_CANCELLED",
                "eater": {
                    "name": "***",
                    "mobileNumber": "",
                    "comment": "giao tận nơi",
                    "address": None,
                },
                "itemInfo": {
                    "count": 1,
                    "items": [
                        {
                            "itemID": "VNITE-SUP",
                            "name": "Súp Bào Ngư - Tiêu Đen",
                            "quantity": 1,
                            "priceDisplay": "240.000",
                            "modifierGroups": [],
                        },
                    ],
                },
                "fare": {
                    "currencySymbol": "₫",
                    "totalDisplay": "240.000",
                    "subTotalDisplay": "240.000",
                    "taxDisplay": "0",
                    "deliveryFeeDisplay": "0",
                    "promotionDisplay": "0",
                },
                "times": {
                    "createdAt": "2026-08-06T07:00:00.000Z",
                    "acceptedAt": "2026-08-06T07:01:00.000Z",
                },
            },
        }

        _write_archive_rows(
            session=sess,
            store_id=store.id,
            merchant_id=store.merchant_id,
            rows=[(
                "OID-ANON", "GF-ANON", "ORDER_CANCELLED",
                json.dumps(payload),
            )],
            now=now,
        )
        sess.commit()

    client = _authed_client(eng)
    resp = client.get("/api/customers/overview")
    assert resp.status_code == 200, resp.text
    raw = resp.json()

    orders = raw["orders"]
    assert len(orders) == 1
    detail = orders[0]["detail"]
    # Backend must NOT munge the anonymised literal — the frontend's
    # anonymisation check (``rawName === "***"``) needs the raw value
    # to render "Khách ẩn danh" instead of "Khách lẻ (không tên)".
    assert detail["eater"]["name"] == "***", (
        f"backend must pass through the '***' anonymised literal, got "
        f"{detail['eater']['name']!r}"
    )
    assert detail["eater"]["mobileNumber"] == "", (
        f"backend must pass through empty mobileNumber, got "
        f"{detail['eater']['mobileNumber']!r}"
    )

    # Also round-trip through the schema-validated model so any future
    # Pydantic validator that mangles "***" (strip/normalize, etc.)
    # would fail here too — the raw-JSON check above doesn't exercise
    # alias resolution.
    body = CustomersOverviewResponse.model_validate(raw)
    eater = body.orders[0].detail.eater
    assert eater.name == "***", (
        f"schema-validated eater.name must be '***', got {eater.name!r}"
    )
    assert eater.mobile_number == "", (
        f"schema-validated eater.mobile_number must be '', got "
        f"{eater.mobile_number!r}"
    )
