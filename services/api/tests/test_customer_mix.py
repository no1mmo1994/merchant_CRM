"""New-vs-returning customer reporting, from Grab's `isPaxNewCustomer`.

Grab labels every order with `flags.isPaxNewCustomer` — its own view of
whether the eater has ordered from this store before. That view reaches
back further than anything the dashboard can compute: the archive only
knows the orders it has polled, while Grab knows the customer's whole
history with the store.

The care in these tests is about not over-claiming from that flag. Three
distinct traps, each with a test below:

  * an absent flag is not "returning" — it is unknown, and must not be
    reported as a fact about the customer;
  * a cancelled order is not revenue, and half the orders this store has
    archived are cancelled;
  * "no orders yet" is not "0% from new customers".
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.security import COOKIE_NAME, SessionToken
from app.deps import get_session
from app.main import app
from app.models import AuditLog, OrderArchive, Store, User  # noqa: F401
from app.routers.customers import _is_cancelled
from app.schemas.orders import (
    OrderDetailLite,
    extract_new_customer_flag,
    parse_order_amount,
)


# ── unit: reading the flag ───────────────────────────────────────────────────


class TestExtractNewCustomerFlag:
    def test_true_and_false_both_read(self) -> None:
        assert extract_new_customer_flag({"flags": {"isPaxNewCustomer": True}}) is True
        assert extract_new_customer_flag({"flags": {"isPaxNewCustomer": False}}) is False

    def test_accepts_the_order_envelope(self) -> None:
        """Callers pass either `{"order": {...}}` or the bare order."""
        assert (
            extract_new_customer_flag({"order": {"flags": {"isPaxNewCustomer": True}}})
            is True
        )

    def test_absent_flag_is_unknown_not_returning(self) -> None:
        """The trap this whole feature could fall into.

        Reporting a missing flag as "khách quay lại" would state
        something about the customer that Grab never said — on a screen
        whose entire purpose is measuring customer acquisition.
        """
        assert extract_new_customer_flag({"flags": {"isPayOnCollect": False}}) is None
        assert extract_new_customer_flag({}) is None
        assert extract_new_customer_flag({"flags": None}) is None
        assert extract_new_customer_flag(None) is None

    def test_non_boolean_is_unknown(self) -> None:
        """A string or number here means the wire shape moved on."""
        assert extract_new_customer_flag({"flags": {"isPaxNewCustomer": "true"}}) is None
        assert extract_new_customer_flag({"flags": {"isPaxNewCustomer": 1}}) is None

    def test_hydrated_detail_carries_the_flag(self) -> None:
        lite = OrderDetailLite.from_raw(
            {"order": {"orderID": "O1", "flags": {"isPaxNewCustomer": True}}}
        )
        assert lite.is_new_customer is True
        assert OrderDetailLite.from_raw({"order": {"orderID": "O1"}}).is_new_customer is None


class TestParseOrderAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("65.000", 65_000.0),
            ("1.234.567", 1_234_567.0),
            ("715.000", 715_000.0),
            ("240,000", 240_000.0),
            (65000, 65_000.0),
        ],
    )
    def test_reads_grab_money_strings(self, raw, expected) -> None:
        assert parse_order_amount(raw) == expected

    def test_missing_total_is_none_not_zero(self) -> None:
        """A zero would silently drag the average order value down."""
        assert parse_order_amount("") is None
        assert parse_order_amount(None) is None
        assert parse_order_amount("—") is None

    def test_negative_is_rejected_not_flipped_positive(self) -> None:
        """An order total is never negative.

        Stripping non-digits would turn `"-65.000"` into a positive
        65.000 — a plausible-looking number from a field this is clearly
        misreading. Reporting nothing is the honest answer.
        """
        assert parse_order_amount("-65.000") is None
        assert parse_order_amount(-65_000) is None

    def test_decimal_tail_is_not_read_as_thousands(self) -> None:
        """`"65.000,50"` must not become 6.500.050 — a 100x error.

        Length is what separates the two: three digits after the final
        separator is a thousands group, one or two is a fraction.
        """
        assert parse_order_amount("65.000,50") == pytest.approx(65_000.50)
        assert parse_order_amount("1.234.567") == 1_234_567.0
        assert parse_order_amount("100,5") == pytest.approx(100.5)

    def test_currency_symbol_and_spacing_survive(self) -> None:
        assert parse_order_amount("715.000 ₫") == 715_000.0
        assert parse_order_amount(" 240.000₫ ") == 240_000.0


class TestIsCancelled:
    def test_matches_both_spellings_the_archive_holds(self) -> None:
        """Different sweeps write different state strings for the same thing."""
        assert _is_cancelled("CANCELLED") is True
        assert _is_cancelled("ORDER_CANCELLED") is True
        assert _is_cancelled("COMPLETED") is False
        assert _is_cancelled("ORDER_IN_PREPARE") is False
        assert _is_cancelled("") is False


# ── integration: the mix on GET /api/customers/overview ──────────────────────


def _make_engine():
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def _keys():
    settings.token_encryption_key = settings.generate_fernet_key()
    settings.session_secret = settings.generate_session_secret()
    yield


@pytest.fixture
def store(monkeypatch):
    engine = _make_engine()
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
        st = Store(
            owner_user_id=owner.id,
            merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
            name="Test Store",
            encrypted_auth_token=b"x",
            encrypted_xray_token=b"x",
            encrypted_display_token=b"x",
        )
        s.add(st)
        s.commit()
        s.refresh(st)
        owner_id, store_id = owner.id, st.id

    def _override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _override
    try:
        yield engine, owner_id, store_id
    finally:
        app.dependency_overrides.clear()


def _archive(
    engine,
    *,
    store_id: int,
    order_id: str,
    phone: str,
    total: str,
    state: str = "COMPLETED",
    is_new: bool | None = True,
    minutes_ago: int = 0,
    created_at: str | None = None,
    seen_at: datetime | None = None,
) -> None:
    """Insert one archived order shaped like Grab's real detail payload."""
    order: dict = {
        "orderID": order_id,
        "displayID": order_id,
        "eater": {"name": "Khach", "mobileNumber": phone, "address": ""},
        "itemInfo": {"count": 1, "items": []},
        "fare": {"totalDisplay": total, "currencySymbol": "₫"},
        # Grab's own placement time — the only trustworthy ordering
        # signal, since `last_seen_at` is when the cron polled.
        "times": {"createdAt": created_at} if created_at else {},
    }
    if is_new is not None:
        # Mirrors the live shape: a whole block of booleans, not one key.
        order["flags"] = {
            "isPayOnCollect": False,
            "isCrossSell": False,
            "isPaxNewCustomer": is_new,
        }
    seen = seen_at or (datetime.utcnow() - timedelta(minutes=minutes_ago))
    with Session(engine) as s:
        s.add(
            OrderArchive(
                store_id=store_id,
                merchant_id="zeus_store:5-C6VKAT5GRK3CTT",
                order_id=order_id,
                display_id=order_id,
                state=state,
                first_seen_at=seen,
                last_seen_at=seen,
                detail_json=json.dumps({"order": order}),
            )
        )
        s.commit()


def _client(owner_id: int) -> TestClient:
    c = TestClient(app)
    c.cookies.set(
        COOKIE_NAME,
        SessionToken(user_id=owner_id, exp=int(time.time()) + 86400).to_signed(
            settings.session_secret
        ),
    )
    return c


class TestCustomerMixEndpoint:
    def test_splits_orders_revenue_and_customers(self, store) -> None:
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="N1", phone="0900000001",
                 total="100.000", is_new=True)
        _archive(engine, store_id=store_id, order_id="N2", phone="0900000002",
                 total="200.000", is_new=True)
        _archive(engine, store_id=store_id, order_id="R1", phone="0900000003",
                 total="300.000", is_new=False)

        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]

        assert mix["new"]["orders"] == 2
        assert mix["new"]["customers"] == 2
        assert mix["new"]["revenueVnd"] == 300_000
        assert mix["new"]["avgOrderValue"] == 150_000

        assert mix["returning"]["orders"] == 1
        assert mix["returning"]["revenueVnd"] == 300_000
        assert mix["returning"]["avgOrderValue"] == 300_000

        assert mix["newOrderShare"] == pytest.approx(2 / 3)
        assert mix["newRevenueShare"] == pytest.approx(0.5)

    def test_cancelled_orders_are_counted_but_not_earned(self, store) -> None:
        """Half the orders this store has archived are cancelled.

        Folding a cancelled order's total into revenue would overstate
        takings; dropping the order entirely would hide real demand. It
        is counted, shown separately, and left out of both revenue and
        the average.
        """
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="C1", phone="0900000001",
                 total="240.000", state="CANCELLED", is_new=True)
        _archive(engine, store_id=store_id, order_id="C2", phone="0900000002",
                 total="255.000", state="ORDER_CANCELLED", is_new=True)
        _archive(engine, store_id=store_id, order_id="K1", phone="0900000003",
                 total="715.000", state="COMPLETED", is_new=True)

        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]

        assert mix["new"]["orders"] == 3
        assert mix["new"]["cancelledOrders"] == 2
        assert mix["new"]["revenueVnd"] == 715_000
        # Averaged over the one order that happened, not all three.
        assert mix["new"]["avgOrderValue"] == 715_000

    def test_unflagged_orders_are_their_own_slice(self, store) -> None:
        """Never folded into `returning` — a data gap is not a finding."""
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="U1", phone="0900000001",
                 total="50.000", is_new=None)
        _archive(engine, store_id=store_id, order_id="N1", phone="0900000002",
                 total="50.000", is_new=True)

        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]

        assert mix["unknown"]["orders"] == 1
        assert mix["returning"]["orders"] == 0
        # Shares are computed over flagged orders only, so an unknown
        # can't dilute the new-customer rate.
        assert mix["newOrderShare"] == 1.0

    def test_no_orders_gives_null_shares_not_zero(self, store) -> None:
        """"No orders yet" is not "0% from new customers"."""
        _engine, owner_id, _store_id = store
        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]
        assert mix["newOrderShare"] is None
        assert mix["newRevenueShare"] is None
        assert mix["new"]["orders"] == 0

    def test_all_cancelled_gives_null_revenue_share(self, store) -> None:
        """Nothing was earned, so no split of earnings exists."""
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="C1", phone="0900000001",
                 total="240.000", state="CANCELLED", is_new=True)
        _archive(engine, store_id=store_id, order_id="C2", phone="0900000002",
                 total="255.000", state="CANCELLED", is_new=False)

        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]
        assert mix["newOrderShare"] == pytest.approx(0.5)
        assert mix["newRevenueShare"] is None
        assert mix["new"]["avgOrderValue"] == 0.0


class TestCustomerCardFlag:
    def test_customer_takes_the_flag_from_their_latest_order(self, store) -> None:
        """Someone new on their first order is returning on their second."""
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="O1", phone="0911111111",
                 total="100.000", is_new=True, minutes_ago=60)
        _archive(engine, store_id=store_id, order_id="O2", phone="0911111111",
                 total="120.000", is_new=False, minutes_ago=1)

        body = _client(owner_id).get("/api/customers/overview").json()
        (customer,) = body["customers"]
        assert customer["orderCount"] == 2
        assert customer["isNewCustomer"] is False

    @pytest.mark.parametrize("insert_newest_first", [False, True])
    def test_tied_poll_timestamps_still_pick_the_real_latest_order(
        self, store, insert_newest_first: bool
    ) -> None:
        """The cron stamps every row in one sweep with the same time.

        Both 08-08 rows in this store's live archive carry an identical
        `last_seen_at` while the orders themselves were placed twelve
        hours apart — so ranking on poll time leaves the winner to
        whatever order SQLite returns rows in. That coin toss decides
        which order's new-customer flag the card reports.

        Run both insertion orders: the answer must be the same, and it
        must come from `times.createdAt`.
        """
        engine, owner_id, store_id = store
        tied = datetime(2026, 8, 8, 3, 0, 24, 300464)
        older = {
            "order_id": "OLD",
            "created_at": "2026-08-07T12:55:40Z",
            "is_new": True,
            "state": "COMPLETED",
            "total": "715.000",
        }
        newer = {
            "order_id": "NEW",
            "created_at": "2026-08-08T02:31:20Z",
            "is_new": False,
            "state": "ORDER_EXECUTING",
            "total": "240.000",
        }
        for spec in ([newer, older] if insert_newest_first else [older, newer]):
            _archive(
                engine,
                store_id=store_id,
                phone="0911111111",
                seen_at=tied,
                **spec,
            )

        (customer,) = _client(owner_id).get("/api/customers/overview").json()["customers"]
        assert customer["orderCount"] == 2
        assert customer["isNewCustomer"] is False
        assert customer["lastState"] == "ORDER_EXECUTING"
        # The headline describes ONE order — state, flag and total all
        # from the same winner.
        assert customer["totalDisplay"] == "240.000"

    def test_unreadable_total_stays_out_of_the_average(self, store) -> None:
        """An order whose total we can't read is not a zero-value order.

        Counting it in the denominator would do exactly what
        `parse_order_amount` returns None to prevent.
        """
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="A", phone="0900000001",
                 total="100.000", is_new=True)
        _archive(engine, store_id=store_id, order_id="B", phone="0900000002",
                 total="", is_new=True)

        mix = _client(owner_id).get("/api/customers/overview").json()["customerMix"]
        assert mix["new"]["orders"] == 2
        assert mix["new"]["revenueVnd"] == 100_000
        # 100.000 over the one order that had a readable total, not 50.000
        # over both.
        assert mix["new"]["avgOrderValue"] == 100_000

    def test_flag_is_null_when_grab_never_sent_it(self, store) -> None:
        engine, owner_id, store_id = store
        _archive(engine, store_id=store_id, order_id="O1", phone="0911111111",
                 total="100.000", is_new=None)

        body = _client(owner_id).get("/api/customers/overview").json()
        assert body["customers"][0]["isNewCustomer"] is None
        assert body["orders"][0]["detail"]["isNewCustomer"] is None
