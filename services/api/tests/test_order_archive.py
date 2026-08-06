"""Regression tests for the OrderArchive snapshot flow.

Guards the "khách hàng vẫn hiển thị khi đơn chuyển sang hoàn tất
hoặc đã hủy" path — the 30-second cron writes ``OrderArchive`` rows
at first sight, and `/api/orders/history` reads from there as a
fallback before fanning out to Grab's per-order detail endpoint.

Coverage:
  1. ``OrderArchive`` is wired into ``SQLModel.metadata`` so the
     test SQLite engine creates the table.
  2. ``_load_archive_for_order_ids`` returns the parsed
     ``OrderDetailLite`` for archived rows, ignoring invalid JSON.
  3. ``_poll_one_store`` upserts on the second call (same
     ``order_id``) — ``first_seen_at`` stays pinned, ``last_seen_at``
     moves forward.
  4. ``_poll_one_store`` inserts a NEW row on the first sight —
     ``first_seen_at == last_seen_at``.
  5. The general user-facing invariant: when the cron has archived
     an order's full detail, the history route can hydrate the
     lite-detail from the archive without a successful Grab call.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.scheduler import _write_archive_rows
from app.models import OrderArchive, Store, User


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def session() -> Session:
    """In-memory SQLite with every model registered (OrderArchive included)."""
    from app.models import AuditLog  # noqa: F401 — registers table

    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        # Seed a store + owner so foreign keys resolve.
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
        yield s


# ── 1. table is registered ───────────────────────────────────────────────────


def test_order_archive_table_is_registered_in_metadata() -> None:
    """The cron assumes SQLModel.metadata.create_all creates the table.

    We assert via the live metadata tables instead of poking the
    engine — much more readable when a future import drift drops
    the table from the registry.
    """
    assert "order_archives" in SQLModel.metadata.tables, (
        "OrderArchive must be registered in SQLModel.metadata so "
        "SQLModel.metadata.create_all(engine) creates the table "
        "in tests (and the production startup hook)."
    )


# ── 2. _write_archive_rows: insert + upsert + invalid JSON ───────────────────


def _sample_payload(order_id: str, display_id: str) -> dict[str, Any]:
    """Build a raw Grab detail payload for one order."""
    return {
        "order": {
            "orderID": order_id,
            "displayID": display_id,
            "state": "ORDER_IN_PREPARE",
            "eater": {
                "ID": "u1",
                "name": "Nguyen Van A",
                "mobileNumber": "0901234567",
                "address": "12 Le Loi, Q1",
                "comment": "Ít cay",
            },
            "itemInfo": {
                "count": 1,
                "items": [
                    {
                        "itemID": "VNITE-1",
                        "name": "Phở bò",
                        "quantity": 1,
                        "priceDisplay": "65.000",
                        "modifierGroups": [],
                    },
                ],
            },
            "fare": {
                "currencySymbol": "₫",
                "totalDisplay": "65.000",
                "subTotalDisplay": "60.000",
                "taxDisplay": "0",
                "deliveryFeeDisplay": "5.000",
                "promotionDisplay": "0",
            },
            "times": {
                "createdAt": "2026-08-04T07:00:00.000Z",
                "acceptedAt": "2026-08-04T07:01:00.000Z",
            },
        },
    }


def test_write_archive_rows_inserts_new_row(session: Session) -> None:
    """First sight of an order → INSERT with first_seen = last_seen."""
    store = session.exec(select(Store)).first()
    assert store is not None
    payload = _sample_payload("OID-1", "GF-1")
    rows = [
        ("OID-1", "GF-1", "ORDER_IN_PREPARE", json.dumps(payload)),
    ]
    now = datetime.utcnow()

    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=rows,
        now=now,
    )
    session.commit()

    archive = session.exec(select(OrderArchive)).all()
    assert len(archive) == 1, f"expected 1 archive row, got {len(archive)}"
    row = archive[0]
    assert row.order_id == "OID-1"
    assert row.display_id == "GF-1"
    assert row.state == "ORDER_IN_PREPARE"
    assert row.first_seen_at == now
    assert row.last_seen_at == now
    # Detail round-trips through JSON without loss.
    assert row.detail_payload()["order"]["eater"]["name"] == "Nguyen Van A"


def test_write_archive_rows_upserts_on_second_sight(session: Session) -> None:
    """Second sight (same order) → UPDATE, first_seen pinned, last_seen moves."""
    store = session.exec(select(Store)).first()
    assert store is not None
    t0 = datetime.utcnow()
    payload_v1 = _sample_payload("OID-1", "GF-1")

    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-1", "GF-1", "ORDER_IN_PREPARE", json.dumps(payload_v1))],
        now=t0,
    )
    session.commit()

    # 5 minutes later — same order, possibly different state/displayID.
    t1 = t0 + timedelta(minutes=5)
    payload_v2 = _sample_payload("OID-1", "GF-1")
    payload_v2["order"]["state"] = "ORDER_READY"
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-1", "GF-1", "ORDER_READY", json.dumps(payload_v2))],
        now=t1,
    )
    session.commit()

    rows = session.exec(select(OrderArchive)).all()
    assert len(rows) == 1, f"expected upsert (1 row), got {len(rows)}"
    row = rows[0]
    assert row.state == "ORDER_READY", "state must be updated on upsert"
    assert row.first_seen_at == t0, "first_seen_at must NOT move on upsert"
    assert row.last_seen_at == t1, "last_seen_at must move forward on upsert"


def test_write_archive_rows_preserves_detail_json_on_state_transition(
    session: Session,
) -> None:
    """Second sight must NOT overwrite ``detail_json`` even if the
    new payload is anonymised.

    Operator contract: "thông tin của khách hàng sđt, tên và món ăn
    khi đã được get sẽ được lưu mặc định không thay đổi, chỉ trạng
    thái đơn hàng thay đổi theo real-time". The cron fans out two
    paths that both feed ``_write_archive_rows``:

      * preparing-queue fan-out (rich detail, real name/phone)
      * daily-reports COMPLETED/CANCELLED fan-out (often anonymised
        by Grab: ``name="***"`` + ``mobileNumber=""``)

    If the upsert clobbered ``detail_json`` on the second sight, the
    daily-reports anonymised payload would wipe the rich first-sight
    payload and the merchant would see "Khách ẩn danh" on every order
    that ever moved out of the preparing queue. This test guards the
    freeze: only ``state`` advances on re-archive, the
    customer/items/fare block stays as it was at first sight.
    """
    store = session.exec(select(Store)).first()
    assert store is not None
    t0 = datetime.utcnow()

    # First sight — preparing queue, rich detail.
    payload_first = _sample_payload("OID-1", "GF-1")
    assert payload_first["order"]["eater"]["name"] == "Nguyen Van A"
    assert payload_first["order"]["eater"]["mobileNumber"] == "0901234567"
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[
            (
                "OID-1",
                "GF-1",
                "ORDER_IN_PREPARE",
                json.dumps(payload_first),
            )
        ],
        now=t0,
    )
    session.commit()

    # Second sight — Grab's daily-reports sent back an anonymised
    # payload (name="***", mobileNumber="") because the order
    # transitioned to ORDER_CANCELLED. The operator's rule says: only
    # state moves, detail_json stays frozen.
    payload_second = json.loads(json.dumps(payload_first))  # deep copy
    payload_second["order"]["state"] = "ORDER_CANCELLED"
    payload_second["order"]["eater"]["name"] = "***"
    payload_second["order"]["eater"]["mobileNumber"] = ""
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[
            (
                "OID-1",
                "GF-1",
                "ORDER_CANCELLED",
                json.dumps(payload_second),
            )
        ],
        now=t0 + timedelta(minutes=10),
    )
    session.commit()

    rows = session.exec(select(OrderArchive)).all()
    assert len(rows) == 1, f"expected 1 archive row, got {len(rows)}"
    row = rows[0]

    # State advances in real-time (the only thing that changes).
    assert row.state == "ORDER_CANCELLED", "state must reflect latest sight"

    # detail_json is FROZEN — the rich customer info from first sight
    # is preserved, not overwritten by Grab's anonymised second-sight
    # payload. The operator's "Khách ẩn danh" surface never appears
    # because the original name/phone are still there.
    payload_now = row.detail_payload()
    assert payload_now["order"]["eater"]["name"] == "Nguyen Van A", (
        "detail_json must NOT be overwritten by the anonymised "
        "second-sight payload — first-sight name must survive"
    )
    assert payload_now["order"]["eater"]["mobileNumber"] == "0901234567", (
        "detail_json must NOT be overwritten by the anonymised "
        "second-sight payload — first-sight phone must survive"
    )
    # Items/fare block also frozen.
    assert payload_now["order"]["itemInfo"]["items"][0]["name"] == "Phở bò"
    # Display-id monotonic — first non-empty wins.
    assert row.display_id == "GF-1"


def test_write_archive_rows_handles_bad_json_gracefully(session: Session) -> None:
    """A malformed JSON blob must not crash the cron — just skip the row."""
    store = session.exec(select(Store)).first()
    assert store is not None
    rows = [
        ("OID-bad", "GF-bad", "ORDER_IN_PREPARE", "{not json"),
        ("OID-good", "GF-good", "ORDER_IN_PREPARE", json.dumps(_sample_payload("OID-good", "GF-good"))),
    ]
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=rows,
        now=datetime.utcnow(),
    )
    session.commit()

    archive = session.exec(select(OrderArchive)).all()
    ids = {r.order_id for r in archive}
    # Bad-JSON row is persisted (we don't validate at write time) but
    # the loader filters it out — see the loader test below.
    assert "OID-bad" in ids
    assert "OID-good" in ids


# ── 3. _load_archive_for_order_ids: hydrate + skip bad JSON ──────────────────


def test_load_archive_for_order_ids_hydrates_lite_detail(session: Session) -> None:
    """Archive-hydrated lite-detail must carry the eater + items + fare."""
    from app.routers.orders import _load_archive_for_order_ids

    store = session.exec(select(Store)).first()
    assert store is not None
    payload = _sample_payload("OID-1", "GF-1")
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-1", "GF-1", "ORDER_IN_PREPARE", json.dumps(payload))],
        now=datetime.utcnow(),
    )
    session.commit()

    out = _load_archive_for_order_ids(session, store.id, ["OID-1"])
    assert "OID-1" in out, "archive row must hydrate into OrderDetailLite"
    lite = out["OID-1"]
    # Python attribute access (snake_case). The pydantic alias
    # `mobileNumber` -> `mobile_number` is the wire-shape; the
    # dashboard renders the camelCase wire via pydantic's
    # by_alias=True serialization, not via attribute access.
    assert lite.eater.name == "Nguyen Van A"
    assert lite.eater.mobile_number == "0901234567"
    assert lite.item_info.count == 1
    assert lite.item_info.items[0].name == "Phở bò"
    assert lite.fare.total_display == "65.000"


def test_load_archive_for_order_ids_skips_bad_json(session: Session) -> None:
    """A row with malformed JSON must NOT appear in the loader output."""
    from app.routers.orders import _load_archive_for_order_ids

    store = session.exec(select(Store)).first()
    assert store is not None
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-bad", "GF-bad", "ORDER_IN_PREPARE", "{not json")],
        now=datetime.utcnow(),
    )
    session.commit()

    out = _load_archive_for_order_ids(session, store.id, ["OID-bad"])
    assert "OID-bad" not in out, (
        "bad-JSON row must be silently skipped (one bad row must not "
        "deny the whole hydration — the dashboard still has the summary row)"
    )


def test_load_archive_for_order_ids_respects_store_scope(session: Session) -> None:
    """A row in store A must not leak into a query for store B.

    Multi-store data isolation guardrail — the cron snapshots per
    (store_id, order_id), and the loader must filter by store_id.
    """
    from app.routers.orders import _load_archive_for_order_ids

    owner = session.exec(select(User)).first()
    assert owner is not None
    other_store = Store(
        owner_user_id=owner.id,
        merchant_id="other:123",
        name="Other Store",
        encrypted_auth_token=b"x",
        encrypted_xray_token=b"x",
        encrypted_display_token=b"x",
    )
    session.add(other_store)
    session.commit()
    session.refresh(other_store)

    store = session.exec(select(Store).where(Store.merchant_id == "zeus_store:5-C6VKAT5GRK3CTT")).first()
    assert store is not None
    payload = _sample_payload("OID-1", "GF-1")
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-1", "GF-1", "ORDER_IN_PREPARE", json.dumps(payload))],
        now=datetime.utcnow(),
    )
    session.commit()

    out = _load_archive_for_order_ids(session, other_store.id, ["OID-1"])
    assert "OID-1" not in out, (
        "store B must not see store A's archive row — that would leak "
        "Grab order data across merchants"
    )


def test_load_archive_for_order_ids_handles_empty_inputs(session: Session) -> None:
    """Empty input / no store → empty dict, no DB hit.

    Route resilience check: the history route calls the loader
    once with target_ids=[] for the no-orders case (the early-return
    path). We must not explode on that.
    """
    from app.routers.orders import _load_archive_for_order_ids

    assert _load_archive_for_order_ids(session, None, []) == {}
    assert _load_archive_for_order_ids(session, 1, []) == {}
    assert _load_archive_for_order_ids(session, 1, ["nonexistent"]) == {}


# ── 4. end-to-end: state transition preserves customer info ──────────────────


def test_state_transition_preserves_customer_info_in_archive(session: Session) -> None:
    """The user-facing invariant: when the cron archives an order
    while it is still in preparing, that snapshot MUST survive later
    state transitions (the historical state is irrelevant — the
    archived data is whatever the cron captured at first sight).
    """
    from app.routers.orders import _load_archive_for_order_ids

    store = session.exec(select(Store)).first()
    assert store is not None

    # Simulate the cron snapshotting an order while it is in preparing.
    payload_preparing = _sample_payload("OID-X", "GF-X")
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-X", "GF-X", "ORDER_IN_PREPARE", json.dumps(payload_preparing))],
        now=datetime.utcnow(),
    )
    session.commit()

    # Now simulate the order transitioning to COMPLETED — but the
    # cron doesn't run again (the order left the preparing queue),
    # so we DON'T update the archive row. The completed-row lookup
    # must still return the customer info from the first-sight
    # snapshot.
    out = _load_archive_for_order_ids(session, store.id, ["OID-X"])
    assert "OID-X" in out, (
        "completed-row lookup must still find the archived customer info "
        "even though the order is no longer in the preparing queue"
    )
    lite = out["OID-X"]
    assert lite.eater.name == "Nguyen Van A"
    assert lite.eater.mobile_number == "0901234567"
    assert lite.item_info.count == 1
    # The lite-detail's state is the first-sight state, not the
    # current state — and that's fine, the dashboard only reads the
    # eater/items/fare blocks from it.


# ── 5. completed/cancelled archive path (regression for "stuck" state) ──────


def test_archive_completed_cancelled_today_inserts_cancelled_row(session: Session) -> None:
    """A CANCELLED summary row from daily-reports must produce an
    OrderArchive tuple with ``state='ORDER_CANCELLED'``.

    Regression for the bug where an order that left the preparing
    queue (cancelled by merchant or customer) kept its stale
    ``ORDER_IN_PREPARE`` state in the archive forever.
    """
    from unittest.mock import AsyncMock, patch

    from app.core.scheduler import _archive_completed_cancelled_today

    store = session.exec(select(Store)).first()
    assert store is not None

    # The detail endpoint returns the post-transition state.
    payload = _sample_payload("OID-CX", "GF-CX")
    payload["order"]["state"] = "ORDER_CANCELLED"

    with patch(
        "grab.endpoints.orders.list_daily_reports",
        new=AsyncMock(return_value={"statements": [
            {"ID": "OID-CX", "displayID": "GF-CX",
             "cancelledAt": "2026-08-04T07:30:00.000Z",
             "cancelledOriginalPriceDisplay": "65.000"}
        ]}),
    ), patch(
        "grab.endpoints.orders.get_order_detail",
        new=AsyncMock(return_value=payload),
    ):
        rows, warn = _archive_completed_cancelled_today(
            authn="x", merchant_id=store.merchant_id, now=datetime.utcnow()
        )

    assert warn is None
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    oid, display_id, state, detail_json = rows[0]
    assert oid == "OID-CX"
    assert display_id == "GF-CX"
    assert state == "ORDER_CANCELLED"
    # detail_json must be valid JSON the router can re-parse.
    parsed = json.loads(detail_json)
    assert parsed["order"]["state"] == "ORDER_CANCELLED"


def test_archive_completed_cancelled_today_returns_warning_on_daily_reports_5xx(
    session: Session,
) -> None:
    """If ``list_daily_reports`` HTTP-errors for BOTH states, the
    helper returns ``([], warning)`` — never raises. The
    preparing-poll caller relies on this to keep moving.
    """
    from unittest.mock import AsyncMock, patch

    import httpx

    from app.core.scheduler import _archive_completed_cancelled_today

    store = session.exec(select(Store)).first()
    assert store is not None

    with patch(
        "grab.endpoints.orders.list_daily_reports",
        new=AsyncMock(side_effect=httpx.ConnectError("boom")),
    ):
        rows, warn = _archive_completed_cancelled_today(
            authn="x", merchant_id=store.merchant_id, now=datetime.utcnow()
        )

    assert rows == [], "must return empty list, never raise"
    assert warn is not None
    assert "boom" in warn or "ConnectError" in warn, (
        f"warning should mention the underlying exception, got: {warn!r}"
    )


def test_archive_completed_cancelled_today_dedupes_overlap(
    session: Session,
) -> None:
    """An order that appears in BOTH COMPLETED and CANCELLED summaries
    (shouldn't happen, but defensive) must produce exactly one archive
    row — not two.
    """
    from unittest.mock import AsyncMock, patch

    from app.core.scheduler import _archive_completed_cancelled_today

    store = session.exec(select(Store)).first()
    assert store is not None

    payload = _sample_payload("OID-DUP", "GF-DUP")

    # list_daily_reports is called twice in the helper (once per state).
    # We return the SAME order id from both to exercise the dedupe.
    with patch(
        "grab.endpoints.orders.list_daily_reports",
        new=AsyncMock(side_effect=[
            {"statements": [{"ID": "OID-DUP", "displayID": "GF-DUP"}]},
            {"statements": [{"ID": "OID-DUP", "displayID": "GF-DUP"}]},
        ]),
    ), patch(
        "grab.endpoints.orders.get_order_detail",
        new=AsyncMock(return_value=payload),
    ):
        rows, _ = _archive_completed_cancelled_today(
            authn="x", merchant_id=store.merchant_id, now=datetime.utcnow()
        )

    assert len(rows) == 1, f"expected deduped 1 row, got {len(rows)}"


def test_archive_completed_cancelled_today_upserts_not_duplicates(
    session: Session,
) -> None:
    """Calling the helper twice for the same order must upsert (via
    ``_write_archive_rows``), not duplicate — same invariant as the
    preparing fan-out's existing upsert test.
    """
    from unittest.mock import AsyncMock, patch

    from app.core.scheduler import (
        _archive_completed_cancelled_today,
        _write_archive_rows,
    )

    store = session.exec(select(Store)).first()
    assert store is not None

    # First snapshot: state=IN_PREPARE (the order was cancelled AFTER
    # the preparing fan-out archived it).
    payload_v1 = _sample_payload("OID-UP", "GF-UP")
    _write_archive_rows(
        session=session,
        store_id=store.id,
        merchant_id=store.merchant_id,
        rows=[("OID-UP", "GF-UP", "ORDER_IN_PREPARE", json.dumps(payload_v1))],
        now=datetime.utcnow(),
    )
    session.commit()

    # Second snapshot: state=ORDER_COMPLETED. The upsert must move
    # the state forward WITHOUT inserting a new row.
    payload_v2 = _sample_payload("OID-UP", "GF-UP")
    payload_v2["order"]["state"] = "ORDER_COMPLETED"

    with patch(
        "grab.endpoints.orders.list_daily_reports",
        new=AsyncMock(return_value={"statements": [
            {"ID": "OID-UP", "displayID": "GF-UP"}
        ]}),
    ), patch(
        "grab.endpoints.orders.get_order_detail",
        new=AsyncMock(return_value=payload_v2),
    ):
        rows, _ = _archive_completed_cancelled_today(
            authn="x", merchant_id=store.merchant_id, now=datetime.utcnow()
        )
        _write_archive_rows(
            session=session,
            store_id=store.id,
            merchant_id=store.merchant_id,
            rows=rows,
            now=datetime.utcnow(),
        )
        session.commit()

    archives = session.exec(
        select(OrderArchive).where(OrderArchive.order_id == "OID-UP")
    ).all()
    assert len(archives) == 1, f"expected 1 upserted row, got {len(archives)}"
    assert archives[0].state == "ORDER_COMPLETED", (
        f"state should be upserted to ORDER_COMPLETED, got {archives[0].state!r}"
    )
