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