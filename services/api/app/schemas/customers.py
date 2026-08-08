"""Customers / sources / order-info aggregation schemas.

The ``/api/customers/overview`` endpoint surfaces three read-only
lenses over the existing ``OrderArchive`` table — the same snapshot
the 30-second cron writes at first sight of every preparing order.
No new tables, no new columns — the cron already captures
``detail_json`` + ``merchant_id`` + ``state`` + ``first_seen_at`` +
``last_seen_at`` per ``(store_id, order_id)`` row.

Wire shape:
  * ``customers[]``  — grouped by ``eater.mobileNumber``
  * ``sources[]``    — grouped by ``merchant_id`` (mã cửa hàng /
                       chi nhánh per user clarification)
  * ``orders[]``     — full per-order detail hydrated via
                       ``OrderDetailLite.from_raw``, plus the
                       archive's first/last seen timestamps + state

All fields use camelCase aliases so the dashboard's
``api.get<T>(path)`` client can read them straight off the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.orders import OrderDetailLite


class CustomerSummary(BaseModel):
    """One distinct customer, aggregated from all their archived orders.

    Group key: ``eater.mobileNumber``. Customers with no phone on
    file fall under an empty-string bucket (``mobileNumber=""``)
    so they still surface — better to see an "unknown" row than
    to silently drop them.

    ``totalDisplay`` is the SUM of ``fare.totalDisplay`` strings
    across all their orders — kept as a string (rather than
    float) because Grab returns locale-formatted prices like
    ``"65.000"`` / ``"1.234.567"`` that don't survive JSON→float
    round-trip. The UI formats / parses on display.
    """

    model_config = ConfigDict(populate_by_name=True)

    mobile_number: str = Field(default="", alias="mobileNumber")
    name: str = ""
    address: str = ""
    order_count: int = Field(default=0, alias="orderCount")
    total_display: str = Field(default="", alias="totalDisplay")
    last_order_at: datetime | None = Field(default=None, alias="lastOrderAt")
    last_state: str = Field(default="", alias="lastState")
    #: Grab's verdict on this person as of their **most recent** order.
    #: Distinct from `orderCount`, which only knows what this dashboard
    #: has archived — Grab has seen their whole history with the store,
    #: including orders from before the dashboard existed. `None` when
    #: Grab didn't say.
    is_new_customer: bool | None = Field(default=None, alias="isNewCustomer")


class SourceSummary(BaseModel):
    """One distinct merchant_id (mã cửa hàng / chi nhánh).

    ``distinctCustomers`` is the count of unique phone numbers
    under this merchant_id — useful for the merchant to see how
    wide their reach is per branch.

    ``address`` is the branch address pulled from ``Store.address``
    at query time (one batched ``IN`` lookup per distinct
    merchant_id). Empty when no matching Store row exists — e.g.
    archive rows from a branch whose Store was deleted.

    ``name`` is the human-readable shop name from ``Store.name``
    (also pulled in the same batched query). The dashboard shows
    it as a subtitle whenever ``address`` is empty so the merchant
    can still identify the branch — the UUID merchant_id alone is
    opaque. Registration currently stores ``address=""`` for new
    stores (the address comes from Grab's ``business_attributes``,
    which often returns nothing), so the name fallback is the most
    useful UX we can give without changing the login flow.
    """

    model_config = ConfigDict(populate_by_name=True)

    merchant_id: str = Field(alias="merchantId")
    address: str = Field(default="", alias="address")
    name: str = Field(default="", alias="name")
    region: str = Field(default="", alias="region")
    order_count: int = Field(default=0, alias="orderCount")
    distinct_customers: int = Field(default=0, alias="distinctCustomers")


class OrderSummary(BaseModel):
    """Full per-order detail + archive metadata.

    The ``detail`` block is the same ``OrderDetailLite`` the
    orders page renders — hydrated from ``detail_json`` via the
    existing ``OrderDetailLite.from_raw`` projector so we don't
    fork the wire shape.

    ``firstSeenAt`` / ``lastSeenAt`` come from the archive row,
    NOT from the detail payload — they tell the merchant when
    the dashboard first/last saw this order in the preparing
    queue (the dashboard's polling history, not Grab's).

    ``state`` reflects what the cron captured at last sight —
    for orders that have since left the preparing queue the
    archive keeps the last-seen state (typically
    ``ORDER_IN_PREPARE`` / ``ORDER_READY``). See the plan's open
    assumptions for the known limitation.
    """

    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(alias="orderId")
    display_id: str = Field(default="", alias="displayId")
    state: str = ""
    first_seen_at: datetime = Field(alias="firstSeenAt")
    last_seen_at: datetime = Field(alias="lastSeenAt")
    detail: OrderDetailLite = Field(default_factory=OrderDetailLite)


class CustomerMixBucket(BaseModel):
    """Trading figures for one slice of customers.

    Cancelled orders are counted but kept out of revenue — a cancelled
    order still says something about demand, and folding its total into
    revenue would overstate takings. Half the orders archived so far are
    cancelled, so this is not a hypothetical distinction.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: Every archived order in this slice, cancelled included.
    orders: int = 0
    cancelled_orders: int = Field(default=0, alias="cancelledOrders")
    #: Distinct phone numbers. A person can appear in both the new and
    #: returning slices — they were new once and came back.
    customers: int = 0
    #: Sum of `fare.totalDisplay`, cancelled orders excluded.
    revenue_vnd: float = Field(default=0.0, alias="revenueVnd")
    #: Revenue over non-cancelled orders, so it reads as "what an order
    #: from this kind of customer is worth".
    avg_order_value: float = Field(default=0.0, alias="avgOrderValue")


class CustomerMix(BaseModel):
    """New versus returning customers, the trading question behind them.

    Grab labels each order with `flags.isPaxNewCustomer`, which is the
    only view of a customer's history with the store that predates this
    dashboard. Splitting orders and revenue along it answers what the
    order list on its own cannot: whether the store is growing on new
    faces or on people coming back, and which of the two spends more.

    `unknown` holds orders where Grab sent no flag. It is reported rather
    than folded into `returning` so a gap in the data never reads as a
    finding about customer behaviour.
    """

    model_config = ConfigDict(populate_by_name=True)

    new: CustomerMixBucket = Field(default_factory=CustomerMixBucket)
    returning: CustomerMixBucket = Field(default_factory=CustomerMixBucket)
    unknown: CustomerMixBucket = Field(default_factory=CustomerMixBucket)
    #: New orders over new+returning, 0–1. `None` when neither slice has
    #: an order — no orders is not a 0% new-customer rate.
    new_order_share: float | None = Field(default=None, alias="newOrderShare")
    #: The same split over revenue. `None` when both slices earned
    #: nothing, e.g. every order so far was cancelled.
    new_revenue_share: float | None = Field(default=None, alias="newRevenueShare")


class CustomersOverviewResponse(BaseModel):
    """Three-lens view over every order the dashboard has ever fetched.

    The shape mirrors what the three tabs render:

      * ``customers[]`` → tab "Khách hàng"
      * ``sources[]``   → tab "Nguồn"
      * ``orders[]``    → tab "Thông tin đơn hàng"
    """

    model_config = ConfigDict(populate_by_name=True)

    customers: list[CustomerSummary] = Field(default_factory=list)
    sources: list[SourceSummary] = Field(default_factory=list)
    orders: list[OrderSummary] = Field(default_factory=list)
    #: New vs returning, across the same rows — the headline above the tabs.
    customer_mix: CustomerMix = Field(
        default_factory=CustomerMix, alias="customerMix"
    )