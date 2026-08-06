"""Orders / customer-overview router — surfaces the data behind the Đơn hàng page.

Mirrors ``donhang/getdonhangmoi.py``. The operator script:

  1. Calls ``GET /food/merchant/v3/orders-pagination?pageType=Preparing``
     to fetch the prep queue's ``orderID`` list.
  2. For each id, calls
     ``GET /food/merchant/v3/orders/{id}?deviceTimeInMillis=…`` to fetch
     the full detail (customer name, phone, address, comment, items +
     modifiers, fare, mexOPT delay flag).

The dashboard wants the same projection, so the router mirrors that
fan-out — one ``list`` call, then one ``detail`` call per row — and
returns a single ``OrderListResponse`` containing the full detail for
every active order.

The endpoint exposes four routes:

  * ``GET /api/orders`` — list+detail fan-out, returns
    ``OrderListResponse``.
  * ``GET /api/orders/{order_id}`` — single order detail, returns
    ``OrderDetail``.
  * ``GET /api/orders/history`` — four-bucket history (preparing +
    scheduled + completed + cancelled) for a date range, returns
    ``OrderHistoryResponse``.
  * ``GET /api/orders/poll-status`` — latest result of the
    30-second order-poll cron (powers the "đã chạy get lại đơn"
    banner), returns ``OrderPollStatus``.

Why this lives on ``/api/orders`` and not ``/api/finance``:
  Orders are the kitchen / front-of-house view (per-customer, itemised,
  tied to a state machine), whereas finance is the accountant view
  (balances, payouts, taxes). Two routers, two intents, two
  frontend tabs.

Auth tokens are auto-rotated via ``get_grab_client`` (see
``app/deps.py``); this router never touches tokens.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlmodel import Session

from app.deps import get_grab_client, get_session, require_user
from app.models import OrderArchive, OrderSnapshot, Store, User
from app.schemas.orders import (
    CancelledOrder,
    CompletedOrder,
    OrderDetail,
    OrderDetailLite,
    OrderEater,
    OrderFare,
    OrderHistoryResponse,
    OrderItem,
    OrderItemInfo,
    OrderItemModifier,
    OrderItemModifierGroup,
    OrderListResponse,
    OrderMexOPT,
    OrderPollStatus,
    OrderTimes,
    ScheduledOrder,
)
from grab.endpoints.orders import (
    get_order_detail,
    list_daily_reports,
    list_preparing_orders,
    list_scheduled_orders,
)

log = logging.getLogger("pulseorder.orders")

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── Projection helpers ───────────────────────────────────────────────────────


def _coerce_str(raw: Any, default: str = "") -> str:
    """Return ``raw`` if it's a non-empty string, otherwise ``default``."""
    if isinstance(raw, str) and raw:
        return raw
    return default


def _coerce_int(raw: Any, default: int = 0) -> int:
    """Best-effort integer coercion.

    Grab sometimes sends locale-formatted strings (``"1"`` vs ``1``)
    or ints-as-strings (``"2"``).  We accept either.
    """
    if isinstance(raw, bool):  # bool is a subclass of int — exclude explicitly
        return default
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            return default
    return default


def _project_eater(raw: Any) -> OrderEater:
    """Flatten the ``eater`` block into the dashboard's ``OrderEater``.

    The list endpoint returns only ``name``; the detail endpoint returns
    the full block (name + mobileNumber + address + comment). Both
    shapes share the same field names — no branching needed, just
    project into the model with safe defaults.
    """
    if not isinstance(raw, dict):
        return OrderEater()
    return OrderEater(
        id=_coerce_str(raw.get("ID")),
        name=_coerce_str(raw.get("name")),
        mobile_number=_coerce_str(raw.get("mobileNumber")),
        address=_coerce_str(raw.get("address")),
        comment=_coerce_str(raw.get("comment")),
    )


def _project_modifier(raw: Any) -> OrderItemModifier | None:
    """Project one modifier option row, dropping rows missing a name."""
    if not isinstance(raw, dict):
        return None
    name = _coerce_str(raw.get("modifierName"))
    if not name:
        return None
    return OrderItemModifier(
        modifier_id=_coerce_str(raw.get("modifierID")),
        modifier_name=name,
        quantity=_coerce_int(raw.get("quantity"), 1) or 1,
        price_display=_coerce_str(raw.get("priceDisplay"), "0"),
    )


def _project_modifier_group(raw: Any) -> OrderItemModifierGroup:
    """Project one modifier group row.

    Drops individual modifier rows missing a name (the merchant's wire
    sometimes carries a placeholder row), but keeps the group itself so
    the UI can still show the group label.
    """
    if not isinstance(raw, dict):
        return OrderItemModifierGroup()
    mods_raw = raw.get("modifiers") or []
    mods: list[OrderItemModifier] = []
    if isinstance(mods_raw, list):
        for m in mods_raw:
            projected = _project_modifier(m)
            if projected is not None:
                mods.append(projected)
    return OrderItemModifierGroup(
        modifier_group_id=_coerce_str(raw.get("modifierGroupID")),
        modifier_group_name=_coerce_str(raw.get("modifierGroupName")),
        modifiers=mods,
    )


def _project_item(raw: Any) -> OrderItem | None:
    """Project one item row.

    Items without a name are dropped (the dashboard can't render a
    nameless row meaningfully); the count is recomputed from the
    surviving items so the merchant sees accurate numbers.
    """
    if not isinstance(raw, dict):
        return None
    name = _coerce_str(raw.get("name"))
    if not name:
        return None
    # The detail payload puts price inside ``fare.priceDisplay``; the
    # list payload omits ``fare``.  Try both.
    fare = raw.get("fare")
    price_display = "0"
    if isinstance(fare, dict):
        price_display = _coerce_str(fare.get("priceDisplay"), "0")
    if price_display == "0":
        # list endpoint fallback — sometimes the price is flat on the item.
        price_display = _coerce_str(raw.get("priceDisplay"), "0")

    groups_raw = raw.get("modifierGroups") or []
    groups: list[OrderItemModifierGroup] = []
    if isinstance(groups_raw, list):
        groups = [_project_modifier_group(g) for g in groups_raw]

    return OrderItem(
        item_id=_coerce_str(raw.get("itemID")),
        name=name,
        quantity=_coerce_int(raw.get("quantity"), 1),
        weight=raw.get("weight") if isinstance(raw.get("weight"), (int, float)) else None,
        comment=_coerce_str(raw.get("comment")),
        price_display=price_display,
        original_item_price_display=_coerce_str(raw.get("originalItemPriceDisplay")),
        modifier_groups=groups,
    )


def _project_item_info(raw: Any) -> OrderItemInfo:
    if not isinstance(raw, dict):
        return OrderItemInfo()
    items_raw = raw.get("items") or []
    items: list[OrderItem] = []
    if isinstance(items_raw, list):
        for i in items_raw:
            projected = _project_item(i)
            if projected is not None:
                items.append(projected)
    return OrderItemInfo(
        count=len(items) if items else _coerce_int(raw.get("count"), len(items)),
        items=items,
    )


def _project_fare(raw: Any) -> OrderFare:
    if not isinstance(raw, dict):
        return OrderFare()
    return OrderFare(
        currency_symbol=_coerce_str(raw.get("currencySymbol"), "₫"),
        total_display=_coerce_str(raw.get("totalDisplay"), "0"),
        sub_total_display=_coerce_str(raw.get("subTotalDisplay"), "0"),
        tax_display=_coerce_str(raw.get("taxDisplay"), "0"),
        delivery_fee_display=_coerce_str(raw.get("deliveryFeeDisplay"), "0"),
        promotion_display=_coerce_str(raw.get("promotionDisplay"), "0"),
        passenger_total_display=_coerce_str(raw.get("passengerTotalDisplay"), "0"),
    )


def _project_times(raw: Any) -> OrderTimes:
    if not isinstance(raw, dict):
        return OrderTimes()
    return OrderTimes(
        created_at=_coerce_str(raw.get("createdAt")),
        accepted_at=_coerce_str(raw.get("acceptedAt")),
        ready_at=_coerce_str(raw.get("readyAt")),
        delivered_at=_coerce_str(raw.get("deliveredAt")),
        completed_at=_coerce_str(raw.get("completedAt")),
        cancelled_at=_coerce_str(raw.get("cancelledAt")),
        expired_at=_coerce_str(raw.get("expiredAt")),
        displayed_at=_coerce_str(raw.get("displayedAt")),
        driver_arrive_resto_at=_coerce_str(raw.get("driverArriveRestoAt")),
    )


def _project_mex_opt(raw: Any) -> OrderMexOPT:
    if not isinstance(raw, dict):
        return OrderMexOPT()
    delayed_flag = raw.get("isPreparationTaskDelayed")
    return OrderMexOPT(
        is_preparation_task_delayed=bool(delayed_flag) if delayed_flag is not None else False,
        preparation_task_delayed_by_min=_coerce_int(raw.get("preparationTaskDelayedByMin"), 0),
        estimated_opt_done_at=_coerce_str(raw.get("estimatedOPTDoneAt")),
        actual_opt=_coerce_str(raw.get("actualOPT")),
    )


def _project_detail(raw: dict[str, Any]) -> OrderDetail:
    """Project the raw ``{"order": {...}}`` envelope into ``OrderDetail``.

    Safe against missing inner blocks (the list endpoint's row is
    much thinner than the detail endpoint's) — any missing block
    collapses to its default.
    """
    inner = raw.get("order") if isinstance(raw, dict) else None
    if not isinstance(inner, dict):
        # Some error envelopes still carry useful bits at the top level.
        # Fall back to projecting the whole blob as the order — names
        # match the inner schema in practice.
        if isinstance(raw, dict) and (
            "orderID" in raw or "displayID" in raw or "eater" in raw
        ):
            inner = raw
        else:
            return OrderDetail()
    return OrderDetail(
        order_id=_coerce_str(inner.get("orderID")),
        display_id=_coerce_str(inner.get("displayID")),
        booking_code=_coerce_str(inner.get("bookingCode")),
        state=_coerce_str(inner.get("state")),
        eater=_project_eater(inner.get("eater")),
        item_info=_project_item_info(inner.get("itemInfo")),
        fare=_project_fare(inner.get("fare")),
        times=_project_times(inner.get("times")),
        mex_opt=_project_mex_opt(inner.get("mexOPT")),
    )


# ── Error envelopes ──────────────────────────────────────────────────────────


def _grab_failure(exc: httpx.HTTPStatusError, code: str) -> HTTPException:
    """Translate a Grab HTTPStatusError into a structured 502."""
    grab_status = exc.response.status_code
    grab_body = exc.response.text[:500]
    msg = "Grab đang gặp sự cố — không tải được đơn hàng. Thử lại sau ít phút."
    if grab_status in (401, 403):
        msg = "Phiên đăng nhập Grab đã hết hạn — đăng nhập lại để tiếp tục."
    return HTTPException(
        status_code=502,
        detail={
            "code": code,
            "message": msg,
            "grab_status": grab_status,
            "grab_body": grab_body,
        },
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=OrderListResponse)
async def list_orders(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> OrderListResponse:
    """Return the preparing-order queue with full detail per row.

    Mirrors ``donhang/getdonhangmoi.py``: list first, then one
    detail call per row in parallel (the operator script did this
    serially — we parallelise since they're independent and Grab's
    edge is fast). The dashboard renders one card per order with
    customer name, phone, address, items, notes, total, and the
    delay flag — all of which come from the detail call.

    Per-order failures are downgraded to warnings so one missing /
    rejected detail doesn't fail the whole overview list. If Grab
    itself rejects the list call (e.g. auth failure), we surface
    that as a 502 so the frontend can render an explicit error
    instead of an empty dashboard.
    """
    log.info("orders_list user=%s", user.id)
    try:
        list_raw = await list_preparing_orders(client)
    except httpx.HTTPStatusError as exc:
        log.warning("orders_list rejected: %s %s", exc.response.status_code, exc.response.text[:200])
        raise _grab_failure(exc, "grab_orders_list_unavailable") from exc
    except httpx.HTTPError as exc:
        log.warning("orders_list transport error: %r", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_orders_list_unavailable",
                "message": "Mất kết nối tới Grab — không tải được danh sách đơn hàng.",
                "grab_status": 0,
                "grab_body": "",
            },
        ) from exc

    orders_block = list_raw.get("orders") if isinstance(list_raw, dict) else None
    raw_rows: list[dict[str, Any]] = []
    if isinstance(orders_block, list):
        raw_rows = [r for r in orders_block if isinstance(r, dict)]

    # Fan out detail calls in parallel so a 10-order queue doesn't
    # block 10× the round-trip.
    async def _safe_detail(order_id: str) -> tuple[str, dict[str, Any] | None, str | None]:
        if not order_id:
            return ("", None, "Bỏ qua đơn hàng thiếu orderID.")
        try:
            payload = await get_order_detail(client, order_id)
            return (order_id, payload, None)
        except httpx.HTTPError as exc:  # noqa: PERF203 — fan-out branch
            log.warning("orders_detail error id=%s: %r", order_id, exc)
            return (order_id, None, f"Không tải được chi tiết đơn {order_id}.")

    if raw_rows:
        detail_results = await asyncio.gather(
            *(
                _safe_detail(_coerce_str(r.get("orderID")))
                for r in raw_rows
            )
        )
    else:
        detail_results = []

    orders: list[OrderDetail] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    for order_id, payload, err in detail_results:
        if err is not None:
            warnings.append(err)
        if isinstance(payload, dict):
            detail = _project_detail(payload)
            # Use the detail's orderID as the dedup key — protects against
            # the (rare) case where the list and detail disagree on ID.
            dedup_key = detail.order_id or order_id
            if dedup_key and dedup_key in seen_ids:
                continue
            if dedup_key:
                seen_ids.add(dedup_key)
            orders.append(detail)

    return OrderListResponse(
        page_type="Preparing",
        orders=orders,
        warnings=warnings,
    )


# ─── Multi-bucket history (Đang chuẩn bị / Sắp tới / Đã hoàn tất / Đã hủy) ──

# NOTE: the ``/{order_id}`` route below is registered AFTER the static
# routes (``/history``, ``/poll-status``) further down this file.
# FastAPI matches routes in registration order, so a literal path
# like ``/api/orders/history`` would otherwise be captured by the
# dynamic handler with ``order_id="history"`` and forwarded to Grab
# as a non-existent order — which is exactly the bug we just hit
# (the dashboard's history endpoint returned 502 forever and the
# "Đã hoàn tất / Đã hủy" tabs showed 0 rows).


def _iso_utc(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with explicit ``Z`` suffix + ms.

    Matches the format used by ``donhang/donhanghoantat_dondalamxong.py``:
    ``"%Y-%m-%dT%H:%M:%S.000Z"``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _project_scheduled(raw: dict[str, Any]) -> ScheduledOrder:
    if not isinstance(raw, dict):
        return ScheduledOrder()
    return ScheduledOrder.from_raw(raw)


def _load_archive_for_order_ids(
    session: Session,
    store_id: int | None,
    order_ids: list[str],
) -> dict[str, OrderDetailLite]:
    """Return ``{order_id: OrderDetailLite}`` for archived rows in this store.

    Used by the ``/api/orders/history`` route to hydrate completed
    / cancelled customer info straight from the per-store snapshot
    the cron wrote (so the dashboard doesn't depend on Grab's
    per-order detail endpoint, which often WAF-rejects orders that
    have already left the preparing queue).

    Empty input / missing store → empty dict. Bad JSON in an
    archived row is silently skipped (one bad row must not deny
    the whole hydration).
    """
    from sqlmodel import select as _sel

    if store_id is None or not order_ids:
        return {}
    rows = session.exec(
        _sel(OrderArchive).where(
            OrderArchive.store_id == store_id,
            OrderArchive.order_id.in_(order_ids),
        )
    ).all()
    out: dict[str, OrderDetailLite] = {}
    for row in rows:
        if not row.order_id:
            continue
        payload = row.detail_payload()
        if not payload:
            continue
        try:
            out[row.order_id] = OrderDetailLite.from_raw(payload)
        except Exception as exc:  # noqa: BLE001 — defensive
            log.warning(
                "orders_history archive: %s failed to hydrate: %r",
                row.order_id, exc,
            )
    return out


def _project_completed(
    raw: dict[str, Any],
    detail: OrderDetailLite | None = None,
) -> CompletedOrder | None:
    """Project one ``statements`` row. Drop rows missing displayID.

    Daily-reports uses the capital ``ID`` key (not ``orderID`` — the
    list and the per-order detail endpoints share the camelCase
    scheme but the daily-reports deviated). Falls back to
    ``orderID`` for forward-compat in case Grab unifies the keys.
    """
    if not isinstance(raw, dict):
        return None
    if not _coerce_str(raw.get("displayID")):
        return None
    order_id = _coerce_str(raw.get("ID")) or _coerce_str(raw.get("orderID"))
    return CompletedOrder(
        orderID=order_id,
        displayID=_coerce_str(raw.get("displayID")),
        priceDisplay=_coerce_str(raw.get("priceDisplay"), "0"),
        updatedAt=_coerce_str(raw.get("updatedAt")),
        detail=detail,
    )


def _project_cancelled(
    raw: dict[str, Any],
    detail: OrderDetailLite | None = None,
) -> CancelledOrder | None:
    if not isinstance(raw, dict):
        return None
    if not _coerce_str(raw.get("displayID")):
        return None
    order_id = _coerce_str(raw.get("ID")) or _coerce_str(raw.get("orderID"))
    return CancelledOrder(
        orderID=order_id,
        displayID=_coerce_str(raw.get("displayID")),
        cancelledOriginalPriceDisplay=_coerce_str(
            raw.get("cancelledOriginalPriceDisplay"), "0"
        ),
        cancelledAt=_coerce_str(raw.get("cancelledAt")),
        cancelRole=_coerce_str(raw.get("cancelRole")),
        detail=detail,
    )


@router.get("/history", response_model=OrderHistoryResponse)
async def get_orders_history(
    from_date: str = Query(
        "2026-08-01",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD inclusive (used for Completed/Cancelled buckets)",
    ),
    to_date: str = Query(
        "2026-08-04",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD inclusive (used for Completed/Cancelled buckets)",
    ),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session: Session = Depends(get_session),
) -> OrderHistoryResponse:
    """Return the four-bucket history (All four views in one round-trip).

    Buckets:
      * ``preparing`` — fetch via ``/orders-pagination?pageType=Preparing``,
        fan out to detail per order (so the dashboard can render the
        full customer / item view for "Đang chuẩn bị").
      * ``scheduled`` — ``/scheduled-orders`` (no date filter — Grab
        returns the upcoming booking window).
      * ``completed`` — ``/reports/daily-pagination?states=COMPLETED``
        for ``[from_date, to_date]``.
      * ``cancelled`` — ``/reports/daily-pagination?states=CANCELLED``
        for the same range.

    All four Grab calls run in parallel. Per-bucket failures are
    downgraded to warnings so a transient 5xx on one bucket doesn't
    fail the whole tab.
    """
    from datetime import datetime as _dt
    try:
        start_dt = _dt.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = _dt.strptime(to_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": "Ngày phải đúng định dạng YYYY-MM-DD.",
            },
        )
    if from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_date_range",
                "message": "Ngày bắt đầu phải trước ngày kết thúc.",
            },
        )

    log.info(
        "orders_history user=%s range=%s..%s",
        user.id, from_date, to_date,
    )

    start_iso = _iso_utc(start_dt)
    end_iso = _iso_utc(end_dt)

    warnings: list[str] = []
    fan_out_results: dict[str, Any] = {}

    # Resolve the user's store once — used for the archive lookup
    # so the dashboard can hydrate completed/cancelled customer info
    # from the per-store snapshot the cron writes (instead of fanning
    # out to Grab's per-order detail endpoint, which often WAF-rejects
    # orders that have already left the preparing queue).
    archive_store_id = _store_id_for_user(session, user.id)
    archive_by_id: dict[str, OrderDetailLite] = {}

    async def _safe_preparing() -> tuple[list[OrderDetail], list[str], list[dict[str, Any]]]:
        try:
            raw = await list_preparing_orders(client)
        except httpx.HTTPError as e:
            log.warning("orders_history preparing error: %r", e)
            return [], ["Không tải được đơn đang chuẩn bị."], []
        if not isinstance(raw, dict):
            return [], [], []
        orders_block = raw.get("orders")
        if not isinstance(orders_block, list):
            return [], [], []
        rows = [r for r in orders_block if isinstance(r, dict)]
        return [], [], rows

    async def _safe_scheduled() -> list[ScheduledOrder]:
        try:
            raw = await list_scheduled_orders(client)
        except httpx.HTTPError as e:
            log.warning("orders_history scheduled error: %r", e)
            warnings.append("Không tải được đơn sắp tới.")
            return []
        if not isinstance(raw, dict):
            return []
        rows = raw.get("orders") or []
        if not isinstance(rows, list):
            return []
        return [_project_scheduled(r) for r in rows if isinstance(r, dict)]

    async def _safe_completed() -> list[CompletedOrder]:
        try:
            raw = await list_daily_reports(
                client,
                start_time=start_iso,
                end_time=end_iso,
                state="COMPLETED",
            )
        except httpx.HTTPError as e:
            log.warning("orders_history completed error: %r", e)
            warnings.append("Không tải được đơn đã hoàn tất.")
            return []
        if not isinstance(raw, dict):
            return []
        rows = raw.get("statements") or []
        if not isinstance(rows, list):
            return []
        # Project summary rows first; we'll fan out per-row detail
        # calls below so each row carries its item list.
        projected: list[tuple[CompletedOrder, str]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Daily-reports uses ``ID`` (capital). Fall back to
            # ``orderID`` for forward-compat.
            order_id = _coerce_str(r.get("ID")) or _coerce_str(r.get("orderID"))
            p = _project_completed(r)
            if p is not None:
                projected.append((p, order_id))
        if not projected:
            return []
        # Hydrate the local archive once for the IDs we care about —
        # ``archive_by_id`` was pre-loaded with all of them up-front
        # (so we don't issue one DB query per row).
        target_ids = [oid for _, oid in projected if oid]
        fresh_archive = _load_archive_for_order_ids(
            session, archive_store_id, target_ids
        )
        # Rows whose detail lives in the archive: no Grab call needed.
        # The rest still go through the per-row fan-out below.
        missing_ids: list[str] = [
            oid for oid in target_ids if oid not in fresh_archive
        ]
        # Per-order detail fan-out (matches the same pattern used for
        # preparing rows). Any failure on one row is folded into a
        # warning — the row still renders, just without its item list.
        async def _safe_detail(order_id: str) -> tuple[str, OrderDetailLite | None]:
            if not order_id:
                return ("", None)
            try:
                payload = await get_order_detail(client, order_id)
                return (order_id, OrderDetailLite.from_raw(payload))
            except httpx.HTTPError:
                return (order_id, None)
            except HTTPException as exc:
                log.warning(
                    "orders_history completed detail %s -> HTTPException %s",
                    order_id, exc.status_code,
                )
                return (order_id, None)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "orders_history completed detail %s -> unexpected %r",
                    order_id, exc,
                )
                return (order_id, None)

        detail_results = (
            await asyncio.gather(
                *(_safe_detail(oid) for oid in missing_ids),
                return_exceptions=True,
            )
            if missing_ids
            else []
        )
        # Map order_id -> lite detail so we can stitch back onto the
        # projected rows even when some details errored out.
        detail_by_id: dict[str, OrderDetailLite] = dict(fresh_archive)
        missing = 0
        for entry in detail_results:
            if isinstance(entry, BaseException):
                missing += 1
                continue
            oid, lite = entry
            if lite is not None and oid:
                detail_by_id[oid] = lite
            elif oid:
                missing += 1
        if missing:
            warnings.append(
                f"Không tải được chi tiết sản phẩm của {missing} đơn đã hoàn tất."
            )
        out: list[CompletedOrder] = []
        for p, oid in projected:
            lite = detail_by_id.get(oid) if oid else None
            # Re-project with the lite detail attached. We rebuild via
            # model_copy so any future fields stay in sync without
            # editing this call site.
            out.append(p.model_copy(update={"detail": lite}))
        return out

    async def _safe_cancelled() -> list[CancelledOrder]:
        try:
            raw = await list_daily_reports(
                client,
                start_time=start_iso,
                end_time=end_iso,
                state="CANCELLED",
            )
        except httpx.HTTPError as e:
            log.warning("orders_history cancelled error: %r", e)
            warnings.append("Không tải được đơn đã hủy.")
            return []
        if not isinstance(raw, dict):
            return []
        rows = raw.get("statements") or []
        if not isinstance(rows, list):
            return []
        projected: list[tuple[CancelledOrder, str]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            order_id = _coerce_str(r.get("ID")) or _coerce_str(r.get("orderID"))
            p = _project_cancelled(r)
            if p is not None:
                projected.append((p, order_id))
        if not projected:
            return []
        # Same archive-first strategy as ``_safe_completed`` — read
        # the per-store snapshot the cron wrote, fall back to the
        # per-row Grab fan-out for IDs we never archived.
        target_ids = [oid for _, oid in projected if oid]
        fresh_archive = _load_archive_for_order_ids(
            session, archive_store_id, target_ids
        )
        missing_ids: list[str] = [
            oid for oid in target_ids if oid not in fresh_archive
        ]
        async def _safe_detail(order_id: str) -> tuple[str, OrderDetailLite | None]:
            if not order_id:
                return ("", None)
            try:
                payload = await get_order_detail(client, order_id)
                return (order_id, OrderDetailLite.from_raw(payload))
            except httpx.HTTPError:
                return (order_id, None)
            except HTTPException as exc:
                log.warning(
                    "orders_history cancelled detail %s -> HTTPException %s",
                    order_id, exc.status_code,
                )
                return (order_id, None)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "orders_history cancelled detail %s -> unexpected %r",
                    order_id, exc,
                )
                return (order_id, None)

        detail_results = (
            await asyncio.gather(
                *(_safe_detail(oid) for oid in missing_ids),
                return_exceptions=True,
            )
            if missing_ids
            else []
        )
        detail_by_id: dict[str, OrderDetailLite] = dict(fresh_archive)
        missing = 0
        for entry in detail_results:
            if isinstance(entry, BaseException):
                missing += 1
                continue
            oid, lite = entry
            if lite is not None and oid:
                detail_by_id[oid] = lite
            elif oid:
                missing += 1
        if missing:
            warnings.append(
                f"Không tải được chi tiết sản phẩm của {missing} đơn đã hủy."
            )
        out: list[CancelledOrder] = []
        for p, oid in projected:
            lite = detail_by_id.get(oid) if oid else None
            out.append(p.model_copy(update={"detail": lite}))
        return out

    (
        _prep_empty,
        _prep_warnings,
        prep_rows,
    ), scheduled, completed, cancelled = await asyncio.gather(
        _safe_preparing(),
        _safe_scheduled(),
        _safe_completed(),
        _safe_cancelled(),
        return_exceptions=True,
    )
    # `return_exceptions=True` means any bucket that blew up arrives
    # here as the exception itself. Convert each into a warning so the
    # other buckets still surface — this is the same "don't fail the
    # whole tab when one bucket is down" guarantee we want for the
    # preparing-detail fan-out below.
    for name, value in (
        ("preparing", _prep_empty),
        ("scheduled", scheduled),
        ("completed", completed),
        ("cancelled", cancelled),
    ):
        if isinstance(value, BaseException):
            log.warning("orders_history %s bucket crashed: %r", name, value)
            warnings.append(f"Không tải được đơn {name}.")
    warnings.extend(_prep_warnings)
    if isinstance(prep_rows, BaseException):
        log.warning("orders_history preparing rows crashed: %r", prep_rows)
        prep_rows = []
        warnings.append("Không tải được danh sách đơn đang chuẩn bị.")

    # Fan out detail calls for the preparing rows (same fan-out as
    # `GET /api/orders` so the dashboard can render the customer /
    # items / notes / fare / mexOPT view for the active queue).
    #
    # IMPORTANT: any per-order failure here MUST stay inside this fan-out
    # and surface as a warning — it must never propagate out of
    # `asyncio.gather`, because that would convert the entire
    # `/api/orders/history` response into a 502 and leave the
    # ``completed`` / ``cancelled`` tabs with `undefined` data (the
    # very "đơn đã hủy / đã hoàn tất không hiển thị" bug the dashboard
    # is meant to avoid). `get_order_detail` raises an `HTTPException`
    # when Grab's WAF rejects a detail call (we've seen status 400
    # with `{"reason": "invalid_argument"}`), and `asyncio.gather`
    # bubbles the first such exception out — catching only
    # `httpx.HTTPError` is not enough.
    detail_results: list[tuple[str, dict[str, Any] | None, str | None]]
    if prep_rows:
        async def _safe_detail(order_id: str) -> tuple[str, dict[str, Any] | None, str | None]:
            if not order_id:
                return ("", None, "Bỏ qua đơn hàng thiếu orderID.")
            try:
                payload = await get_order_detail(client, order_id)
                return (order_id, payload, None)
            except httpx.HTTPError:
                return (order_id, None, f"Không tải được chi tiết đơn {order_id}.")
            except HTTPException as exc:
                # Grab WAF rejection or session expiry — fold into a
                # warning so the rest of the history response (the
                # completed / cancelled / scheduled buckets the user
                # actually clicked on) is still served.
                log.warning(
                    "orders_history preparing detail %s -> HTTPException %s",
                    order_id, exc.status_code,
                )
                return (
                    order_id,
                    None,
                    f"Không tải được chi tiết đơn {order_id} (Grab trả về {exc.status_code}).",
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    "orders_history preparing detail %s -> unexpected %r",
                    order_id, exc,
                )
                return (order_id, None, f"Lỗi không xác định khi tải đơn {order_id}.")

        detail_results = await asyncio.gather(
            *(_safe_detail(_coerce_str(r.get("orderID"))) for r in prep_rows),
            return_exceptions=False,
        )
    else:
        detail_results = []

    preparing: list[OrderDetail] = []
    seen: set[str] = set()
    for order_id, payload, err in detail_results:
        if err is not None:
            warnings.append(err)
        if isinstance(payload, dict):
            detail = _project_detail(payload)
            key = detail.order_id or order_id
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            preparing.append(detail)

    return OrderHistoryResponse(
        dateRange={"from": from_date, "to": to_date},
        preparing=preparing,
        scheduled=scheduled,
        completed=completed,
        cancelled=cancelled,
        warnings=warnings,
    )


# ─── Polling status ("đã chạy get lại đơn") ────────────────────────────────


@router.get("/poll-status", response_model=OrderPollStatus)
async def get_poll_status(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> OrderPollStatus:
    """Return the last result of the 30-second order cron for the user's store.

    Powers the "đã chạy get lại đơn lúc HH:MM — tìm thấy N đơn /
    chưa tìm thấy đơn" banner. We compute the store from the user's
    session (the require_user dependency guarantees the user resolves
    to one store in this merchant app).
    """
    store_id = _store_id_for_user(session, user.id)
    store = session.get(Store, store_id) if store_id is not None else None
    if store is None:
        # Fall back to the first store — order-poll status is a
        # per-store attribute, but the seed user typically owns
        # exactly one. If the user genuinely has no store, we return
        # the `never` sentinel so the UI still renders something.
        from sqlmodel import select as _sel
        store = session.exec(_sel(Store)).first()
    if store is None:
        return OrderPollStatus(
            lastPolledAt=None,
            nextPollAt=None,
            lastOrderCount=0,
            lastStatus="never",
            message="Chưa có dữ liệu poll đơn hàng.",
            storeId=None,
        )
    snap = session.get(OrderSnapshot, store.id)
    if snap is None:
        return OrderPollStatus(
            lastPolledAt=None,
            nextPollAt=None,
            lastOrderCount=0,
            lastStatus="never",
            message="Chưa có dữ liệu poll đơn hàng.",
            storeId=store.id,
        )
    return OrderPollStatus(
        lastPolledAt=snap.last_polled_at,
        nextPollAt=snap.next_poll_at,
        lastOrderCount=snap.last_order_count,
        lastStatus=snap.last_status,
        message=snap.message,
        storeId=store.id,
    )


def _store_id_for_user(session: Session, user_id: int) -> int | None:
    """Look up the owned store for a user.

    The seed for this dashboard maps 1 user → 1 store; multi-store
    users would need a store-cookie / active-store selection, but
    that's out of scope for the orders polling tab.
    """
    from sqlmodel import select as _sel
    store = session.exec(_sel(Store).where(Store.owner_user_id == user_id)).first()
    return store.id if store is not None else None


# ─── Single-order detail (drill-in modal) ────────────────────────────────────
#
# REGISTERED LAST on purpose. FastAPI matches routes in declaration
# order, so the static ``/history`` and ``/poll-status`` paths above
# take precedence; this dynamic handler only fires for paths that
# aren't claimed by the static routes. Re-registering it before
# them turns the history endpoint into a 502 (it would be matched
# with ``order_id="history"`` and look up a non-existent Grab order).


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: str = Path(..., description="Grab order ID (e.g. 001475307051-C8C2LU4WJ4MBA6)"),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> OrderDetail:
    """Return the full detail for a single order.

    Used by the dashboard's per-order drill-in view (when the
    operator clicks one of the overview cards).
    """
    log.info("orders_detail user=%s order_id=%s", user.id, order_id)
    try:
        raw = await get_order_detail(client, order_id)
    except httpx.HTTPStatusError as exc:
        log.warning("orders_detail rejected: %s %s", exc.response.status_code, exc.response.text[:200])
        raise _grab_failure(exc, "grab_order_detail_unavailable") from exc
    except httpx.HTTPError as exc:
        log.warning("orders_detail transport error: %r", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_order_detail_unavailable",
                "message": "Mất kết nối tới Grab — không tải được chi tiết đơn hàng.",
                "grab_status": 0,
                "grab_body": "",
            },
        ) from exc
    return _project_detail(raw)