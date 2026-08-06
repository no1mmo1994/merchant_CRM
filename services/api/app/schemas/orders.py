"""Pydantic schemas for the orders / customer-overview dashboard.

Mirrors the wire shape from
``donhang/getdonhangmoi.py`` + ``donhang/donhanghoantat_dondalamxong.py``
(which together call
``GET /food/merchant/v3/orders-pagination`` + ``/orders/{id}`` +
``/scheduled-orders`` + ``/reports/daily-pagination``) but projects
the responses into typed models so the dashboard renders directly
without recursion.

Why a separate module:
  * The orders endpoints sit under ``/food/merchant/v3/...`` /
    ``/v1/...`` (the storefront surface), not ``/mex/finances/...``
    — different URL space, different operator scripts.
  * The dashboard exposes these to a *different* audience (the
    kitchen + front-of-house staff running the merchant dashboard),
    whereas finance targets the merchant accountant. Two files keeps
    the audit chain clean: each tab can be cross-checked against its
    corresponding CLI script.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ─── Shared building blocks ──────────────────────────────────────────────────


class OrderEater(BaseModel):
    """Customer block.

    On the live merchant's orders, Grab returns ``name`` only in the
    list view; ``mobileNumber`` / ``address`` / ``comment`` are only
    populated in the detail view. We accept empty strings so a single
    schema works for both surfaces.
    """

    id: str = Field(default="", alias="ID")
    name: str = ""
    mobile_number: str = Field(default="", alias="mobileNumber")
    address: str = ""
    comment: str = ""

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        """See ``OrderDetailLite._coerce_none_to_str`` — same rationale."""
        if not isinstance(data, dict):
            return data
        for k in ("ID", "name", "mobileNumber", "address", "comment"):
            if data.get(k) is None:
                data[k] = ""
        return data


class OrderItemModifier(BaseModel):
    """One modifier option inside an order item.

    Example payload from Grab:
        {"modifierID": "VNMOD...", "modifierName": "Bào ngư Hàn - size to",
         "priceDisplay": "65.000", "quantity": 1}
    """

    modifier_id: str = Field(default="", alias="modifierID")
    modifier_name: str = Field(default="", alias="modifierName")
    quantity: int = 1
    price_display: str = Field(default="0", alias="priceDisplay")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for k in ("modifierID", "modifierName", "priceDisplay"):
            if data.get(k) is None:
                data[k] = "" if k != "priceDisplay" else "0"
        return data


class OrderItemModifierGroup(BaseModel):
    """One group of modifiers (e.g. "TOPPING LẺ").

    Real wire shape:
        {"modifierGroupID": "VNMOG...", "modifierGroupName": "TOPPING LẺ",
         "modifiers": [OrderItemModifier, ...]}
    """

    modifier_group_id: str = Field(default="", alias="modifierGroupID")
    modifier_group_name: str = Field(default="", alias="modifierGroupName")
    modifiers: list[OrderItemModifier] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for k in ("modifierGroupID", "modifierGroupName"):
            if data.get(k) is None:
                data[k] = ""
        return data


class OrderItem(BaseModel):
    """One line-item inside an order.

    Real shape (list view, condensed):
        {"itemID": "VNITE...", "name": "Súp Bào Ngư - Tiểu Bảo",
         "quantity": 1, "weight": null}

    Detail view adds:
        {"fare": {"priceDisplay": "305.000", ...},
         "comment": "",
         "modifierGroups": [OrderItemModifierGroup, ...],
         ...}
    """

    item_id: str = Field(default="", alias="itemID")
    name: str = ""
    quantity: int = 0
    weight: float | None = None
    comment: str = ""
    price_display: str = Field(default="0", alias="priceDisplay")
    original_item_price_display: str = Field(
        default="", alias="originalItemPriceDisplay"
    )
    modifier_groups: list[OrderItemModifierGroup] = Field(
        default_factory=list, alias="modifierGroups"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for k in (
            "itemID", "name", "comment",
            "originalItemPriceDisplay",
        ):
            if data.get(k) is None:
                data[k] = ""
        if data.get("priceDisplay") is None:
            data["priceDisplay"] = "0"
        return data


class OrderItemInfo(BaseModel):
    """Wrapper around the items list.

    Wire shape:
        {"count": 1, "items": [OrderItem, ...]}
    """

    count: int = 0
    items: list[OrderItem] = Field(default_factory=list)


class OrderTimes(BaseModel):
    """ISO-8601 timestamps throughout the order lifecycle.

    We accept any/all of them and let the dashboard render whichever
    is meaningful for the current state.
    """

    created_at: str = Field(default="", alias="createdAt")
    accepted_at: str = Field(default="", alias="acceptedAt")
    ready_at: str = Field(default="", alias="readyAt")
    delivered_at: str = Field(default="", alias="deliveredAt")
    completed_at: str = Field(default="", alias="completedAt")
    cancelled_at: str = Field(default="", alias="cancelledAt")
    expired_at: str = Field(default="", alias="expiredAt")
    displayed_at: str = Field(default="", alias="displayedAt")
    driver_arrive_resto_at: str = Field(
        default="", alias="driverArriveRestoAt"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        """See ``OrderDetailLite._coerce_none_to_str`` — same rationale."""
        if not isinstance(data, dict):
            return data
        for k in (
            "createdAt", "acceptedAt", "readyAt", "deliveredAt",
            "completedAt", "cancelledAt", "expiredAt", "displayedAt",
            "driverArriveRestoAt",
        ):
            if data.get(k) is None:
                data[k] = ""
        return data


class OrderFare(BaseModel):
    """Money breakdown for the order.

    Real shape exposes many display strings (``totalDisplay``,
    ``subTotalDisplay``, ``taxDisplay``, ``deliveryFeeDisplay``, …).
    We keep the most useful ones; downstream widgets can add fields
    without breaking the dashboard.
    """

    currency_symbol: str = Field(default="₫", alias="currencySymbol")
    total_display: str = Field(default="0", alias="totalDisplay")
    sub_total_display: str = Field(default="0", alias="subTotalDisplay")
    tax_display: str = Field(default="0", alias="taxDisplay")
    delivery_fee_display: str = Field(default="0", alias="deliveryFeeDisplay")
    promotion_display: str = Field(default="0", alias="promotionDisplay")
    passenger_total_display: str = Field(
        default="0", alias="passengerTotalDisplay"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("currencySymbol") is None:
            data["currencySymbol"] = "₫"
        for k in (
            "totalDisplay", "subTotalDisplay", "taxDisplay",
            "deliveryFeeDisplay", "promotionDisplay",
            "passengerTotalDisplay",
        ):
            if data.get(k) is None:
                data[k] = "0"
        return data


class OrderMexOPT(BaseModel):
    """Order-preparation-task timing fields.

    Only the dashboard-relevant fields are kept:
      * `isPreparationTaskDelayed` — the "⚠️ Đang bị chậm trễ" flag the
        merchant script prints.
      * `preparationTaskDelayedByMin` — how late (minutes) the prep
        is running.
    """

    is_preparation_task_delayed: bool = Field(
        default=False, alias="isPreparationTaskDelayed"
    )
    preparation_task_delayed_by_min: int = Field(
        default=0, alias="preparationTaskDelayedByMin"
    )
    estimated_opt_done_at: str = Field(default="", alias="estimatedOPTDoneAt")
    actual_opt: str = Field(default="", alias="actualOPT")

    model_config = {"populate_by_name": True}


# ─── List response ───────────────────────────────────────────────────────────


class OrderSummary(BaseModel):
    """One row in the merchant's preparing-order queue.

    Comes from the list endpoint
    (``/orders-pagination?pageType=Preparing``). Grab's wire shape
    carries enough for an overview card (displayID, eater name,
    item count, state, created time), but not the full detail
    (phone, address, items, fare). The router fans out one
    ``GET /orders/{id}`` per row to enrich the list view with the
    detail fields the dashboard wants — see
    ``app/routers/orders.py``.
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    state: str = ""
    eater: OrderEater = Field(default_factory=OrderEater)
    item_count: int = 0
    times: OrderTimes = Field(default_factory=OrderTimes)

    model_config = {"populate_by_name": True}


class OrderListResponse(BaseModel):
    """Response for ``GET /api/orders``.

    The dashboard expects to render both the summary row *and* the
    rich detail (items, modifiers, fare, mexOPT) per row, so we
    project each list entry into an ``OrderDetail`` after the
    detail call. We keep the explicit field name to make the
    one-fan-out-per-order flow obvious to maintainers.
    """

    page_type: str = "Preparing"
    orders: list["OrderDetail"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ─── Detail response ─────────────────────────────────────────────────────────


class OrderDetail(BaseModel):
    """Full order detail.

    Comes from ``/orders/{id}?deviceTimeInMillis=…`` (the endpoint
    ``donhang/getdonhangmoi.py:get_order_details`` uses).

    Field layout mirrors the merchant script's print order so a
    developer reading the dashboard's JSX can map lines 1:1 to the
    script's print statements.
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    booking_code: str = Field(default="", alias="bookingCode")
    state: str = ""
    eater: OrderEater = Field(default_factory=OrderEater)
    item_info: OrderItemInfo = Field(
        default_factory=OrderItemInfo, alias="itemInfo"
    )
    fare: OrderFare = Field(default_factory=OrderFare)
    times: OrderTimes = Field(default_factory=OrderTimes)
    mex_opt: OrderMexOPT = Field(
        default_factory=OrderMexOPT, alias="mexOPT"
    )

    model_config = {"populate_by_name": True}


# Late-resolve the forward ref so the list response can carry detail rows.
OrderListResponse.model_rebuild()


# ─── History buckets (Scheduled / Completed / Cancelled) ─────────────────────


class ScheduledOrder(BaseModel):
    """One row from the merchant's scheduled-orders queue.

    Wire shape (real response):
        {"orderID": "0014...", "displayID": "GF-XXX",
         "scheduledAt": "2026-08-04T14:46:01Z", "eater": {"name": "..."}}
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    eater_name: str = Field(default="", alias="eaterName")
    scheduled_at: str = Field(default="", alias="scheduledAt")
    state: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ScheduledOrder":
        """Project any of the endpoint's envelope shapes into one row.

        The endpoint sometimes nests the eater under ``eater``,
        sometimes flattens ``eaterName`` at the top level. We accept
        both — the projections here tolerate the messier Grab payloads.
        """
        if not isinstance(raw, dict):
            return cls()
        eater = raw.get("eater") if isinstance(raw.get("eater"), dict) else {}
        eater_name = eater.get("name") if isinstance(eater, dict) else ""
        return cls(
            orderID=_coerce_str(raw.get("orderID")),
            displayID=_coerce_str(raw.get("displayID")),
            eaterName=_coerce_str(raw.get("eaterName") or eater_name),
            scheduledAt=_coerce_str(raw.get("scheduledAt")),
            state=_coerce_str(raw.get("state")),
        )


class OrderDetailLite(BaseModel):
    """Subset of ``OrderDetail`` we attach to completed/cancelled rows.

    The daily-reports endpoint only carries summary fields (price,
    displayID, completion/cancel timestamps). To render the per-order
    item list on the "Đã hoàn tất" / "Đã hủy" tabs (which is what the
    dashboard operator wants — they can reconcile against the kitchen
    log without clicking into a detail view), we fan-out a per-order
    detail call and project it down to this ``OrderDetailLite`` model.

    Lives on the row as ``detail: OrderDetailLite | None`` so a single
    detail call failure (e.g. WAF rejection on a stale order) doesn't
    drop the row — just the item list.
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    eater: OrderEater = Field(default_factory=OrderEater)
    item_info: OrderItemInfo = Field(
        default_factory=OrderItemInfo, alias="itemInfo"
    )
    fare: OrderFare = Field(default_factory=OrderFare)
    times: OrderTimes = Field(default_factory=OrderTimes)

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_to_str(cls, data: Any) -> Any:
        """Replace ``None`` values in string fields with empty strings.

        Grab's per-order detail endpoint returns nullable string
        fields (``eater.address``, ``times.readyAt``,
        ``times.cancelledAt``, ``times.driverArriveRestoAt``, etc.)
        as JSON ``null`` rather than omitting the key. Pydantic v2
        rejects ``None`` for non-nullable ``str`` fields, which
        would silently drop the entire lite-detail payload.

        Rather than make every field nullable (which would ripple
        through the rest of the dashboard types), we coerce ``None``
        to ``""`` on the way in. This mirrors what the
        ``_project_*`` helpers in ``app/routers/orders.py`` do
        manually for the preparing-queue fan-out.

        We walk the entire tree and replace any ``None`` whose key
        looks like a known string field. Unknown keys / non-string
        leaves are left untouched (Pydantic will reject them with
        a clearer error than "None for str field" downstream).
        """
        # Known camelCase string fields from the wire shape.
        string_keys = {
            "orderID", "displayID", "ID", "name", "mobileNumber",
            "address", "comment", "currencySymbol", "totalDisplay",
            "subTotalDisplay", "taxDisplay", "deliveryFeeDisplay",
            "promotionDisplay", "passengerTotalDisplay", "itemID",
            "priceDisplay", "originalItemPriceDisplay", "modifierID",
            "modifierName", "modifierGroupID", "modifierGroupName",
            "createdAt", "acceptedAt", "readyAt", "deliveredAt",
            "completedAt", "cancelledAt", "expiredAt", "displayedAt",
            "driverArriveRestoAt",
        }

        def _walk(node: Any) -> Any:
            if isinstance(node, dict):
                return {
                    k: ("" if (k in string_keys and v is None)
                        else _walk(v))
                    for k, v in node.items()
                }
            if isinstance(node, list):
                return [_walk(v) for v in node]
            return node

        if not isinstance(data, dict):
            return data
        return _walk(data)

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> "OrderDetailLite":
        """Project a ``/orders/{id}`` response payload.

        ``raw`` may be either ``{"order": {...}}`` (the response
        envelope) or the raw order dict itself (callers vary).

        Implementation note: the inner Pydantic classes
        (``OrderEater`` / ``OrderItem`` / ``OrderItemInfo`` /
        ``OrderFare`` / ``OrderTimes``) use ``populate_by_name=True``
        and expose camelCase aliases, so ``model_validate`` will map
        the wire shape directly without a per-class ``from_raw``.
        """
        if not isinstance(raw, dict):
            return cls()
        # Unwrap ``{"order": {...}}`` envelopes so callers can pass the
        # whole detail response (the shape ``GET /orders/{id}`` returns).
        order = raw.get("order") if isinstance(raw.get("order"), dict) else raw
        # The detail response nests items under ``itemInfo`` (camelCase)
        # but we also accept the snake_case key in case the wire shape
        # ever flattens.
        item_info = order.get("itemInfo") or order.get("item_info") or {}
        if not isinstance(item_info, dict):
            item_info = {}
        items = item_info.get("items") or []
        if not isinstance(items, list):
            items = []
        # If ``itemInfo.count`` is missing or zero but we have an items
        # list, fall back to the items length so the UI doesn't show 0.
        count = item_info.get("count") or len(items)
        # Build a fully-typed payload then hand it to ``model_validate``.
        payload: dict[str, Any] = {
            "orderID": _coerce_str(order.get("orderID")),
            "displayID": _coerce_str(order.get("displayID")),
            "eater": order.get("eater") or {},
            "itemInfo": {
                "count": count,
                "items": [it for it in items if isinstance(it, dict)],
            },
            "fare": order.get("fare") or {},
            "times": order.get("times") or {},
        }
        return cls.model_validate(payload)


# ─── Completed / Cancelled order projections ─────────────────────────────────


class CompletedOrder(BaseModel):
    """One row from the daily reports ``COMPLETED`` bucket.

    Wire shape:
        {"displayID": "GF-XXX", "priceDisplay": "305.000",
         "updatedAt": "2026-08-04T14:46:01Z", "orderID": "0014..."}

    The dashboard wants the per-order item list so the operator can
    reconcile against the kitchen log without leaving the page. The
    daily-reports endpoint only carries summary fields, so we
    fan-out a detail call per row and attach the lite-detail payload
    (``OrderDetailLite``) here. ``detail`` is nullable because the
    detail endpoint occasionally WAF-rejects old cancelled orders —
    the row is still rendered, just without the item list.
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    price_display: str = Field(default="0", alias="priceDisplay")
    completed_at: str = Field(default="", alias="updatedAt")
    detail: "OrderDetailLite | None" = None

    model_config = {"populate_by_name": True}


class CancelledOrder(BaseModel):
    """One row from the daily reports ``CANCELLED`` bucket.

    Wire shape:
        {"displayID": "GF-XXX", "cancelledOriginalPriceDisplay": "305.000",
         "cancelledAt": "2026-08-04T14:46:01Z", "cancelRole": "MERCHANT",
         "orderID": "0014..."}

    Same fan-out rationale as ``CompletedOrder``: include
    ``OrderDetailLite`` so the dashboard can show items + cancellation
    context without a second click.
    """

    order_id: str = Field(default="", alias="orderID")
    display_id: str = Field(default="", alias="displayID")
    cancelled_original_price_display: str = Field(
        default="0", alias="cancelledOriginalPriceDisplay"
    )
    cancelled_at: str = Field(default="", alias="cancelledAt")
    cancel_role: str = Field(default="", alias="cancelRole")
    detail: "OrderDetailLite | None" = None

    model_config = {"populate_by_name": True}


class OrderPollStatus(BaseModel):
    """Latest result of the 30-second cron poll.

    Returned by ``GET /api/orders/poll-status`` so the dashboard
    banner can tell the operator "đã chạy get lại đơn nhưng chưa
    tìm thấy đơn" without keeping state in the frontend.
    """

    last_polled_at: datetime | None = Field(default=None, alias="lastPolledAt")
    next_poll_at: datetime | None = Field(default=None, alias="nextPollAt")
    last_order_count: int = Field(default=0, alias="lastOrderCount")
    last_status: str = Field(default="never", alias="lastStatus")
    """One of ``never`` / ``ok`` / ``empty`` / ``error``."""
    message: str = Field(default="", alias="message")
    store_id: int | None = Field(default=None, alias="storeId")

    model_config = {"populate_by_name": True}


class OrderHistoryResponse(BaseModel):
    """Multi-bucket response for ``GET /api/orders/history``.

    The dashboard renders four tabs (Đang chuẩn bị / Sắp tới / Đã
    hoàn tất / Đã hủy) from this single object — the backend fans
    out the four Grab calls in parallel so the dashboard only needs
    one round-trip per filter change.
    """

    date_range: dict[str, str] = Field(default_factory=dict, alias="dateRange")
    preparing: list[OrderDetail] = Field(default_factory=list)
    scheduled: list[ScheduledOrder] = Field(default_factory=list)
    completed: list[CompletedOrder] = Field(default_factory=list)
    cancelled: list[CancelledOrder] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ─── helpers ─────────────────────────────────────────────────────────────────


def _coerce_str(raw: Any, default: str = "") -> str:
    """Return ``raw`` if it's a non-empty string, otherwise ``default``."""
    if isinstance(raw, str) and raw:
        return raw
    return default