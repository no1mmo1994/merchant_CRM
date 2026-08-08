"""Customers / sources / order-info read-only aggregation router.

This router surfaces a three-lens view of every order the
30-second cron has ever fetched, hydrated from the
``OrderArchive`` table the cron writes at first sight of each
order. Endpoints:

  * ``GET /api/customers/overview`` — single round-trip returning
    three lists: ``customers[]``, ``sources[]``, ``orders[]``.

Why one endpoint (not three):
  The three lists are derived from the same in-memory archive
  rows — splitting them across three requests would force us
  to re-scan the same rows three times and waste the cron
  snapshot. The single-endpoint fan-out is also what the
  three-tab page wants (one ``useQuery`` per tab-mount).

No new tables, no new columns. The cron keeps archiving as
before; this router is a pure read-side view.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.deps import get_session, require_user
from app.models import OrderArchive, Store, User
from app.schemas.customers import (
    CustomerMix,
    CustomerMixBucket,
    CustomerSummary,
    CustomersOverviewResponse,
    OrderSummary,
    SourceSummary,
)
from app.schemas.orders import (
    OrderDetailLite,
    extract_new_customer_flag,
    parse_order_amount,
)

log = logging.getLogger("pulseorder.customers")

router = APIRouter(prefix="/api/customers", tags=["customers"])


# ── helpers ──────────────────────────────────────────────────────────────────


def _store_id_for_user(session: Session, user_id: int) -> int | None:
    """Look up the owned store for a user.

    Inlined from ``routers/orders.py`` so the customers router
    doesn't reach into another module's private helper. The seed
    maps 1 user → 1 store; multi-store users would need a
    store-cookie / active-store selection, but that's out of
    scope for this read-only view.
    """
    from sqlmodel import select as _sel

    store = session.exec(_sel(Store).where(Store.owner_user_id == user_id)).first()
    return store.id if store is not None else None


def _extract_eater(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the eater block from the raw detail payload, defensively.

    The detail payload may be ``{"order": {...}}`` (the
    response envelope) or the raw order dict itself. We accept
    both so the loader can be called with either shape.
    """
    if not isinstance(payload, dict):
        return {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    if not isinstance(order, dict):
        return {}
    eater = order.get("eater")
    return eater if isinstance(eater, dict) else {}


def _normalize_total(raw: str) -> str:
    """Pass-through for Grab's locale-formatted total like ``"65.000"``.

    We keep the string verbatim instead of converting to float
    because:
      * Grab's wire shape always returns a string (e.g.
        ``"1.234.567"`` with thousands separators). Float
        round-trip would silently mangle the formatting.
      * Summing locale-formatted strings across orders is the
        UI's job (parse + reformat). Here we just concatenate
        the digest enough that the aggregation not be lossy.

    For the aggregator we just pick the latest order's total
    as the display — that's the most useful single number for
    a customer card (last order total). The full per-order
    total is on each OrderSummary.
    """
    return raw if isinstance(raw, str) else ""


def _order_created_at(payload: dict[str, Any]) -> datetime | None:
    """Grab's own `times.createdAt` — when the order was actually placed.

    Not the same thing as `OrderArchive.last_seen_at`, which records when
    this dashboard last polled. The cron stamps every row it touches in
    one tick with a single shared timestamp, so two orders hours apart
    routinely land on the identical `last_seen_at` — both rows in this
    store's archive from the 08-08 sweep did, while the orders themselves
    were placed twelve hours apart.

    That matters because "the customer's latest order" decides which
    order's new-customer flag the customer card reports. Ranking on
    poll time would let a returning customer read as new depending on
    nothing more than row iteration order.
    """
    order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
    if not isinstance(order, dict):
        return None
    times = order.get("times")
    if not isinstance(times, dict):
        return None
    raw = times.get("createdAt")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # Grab sends `2026-08-08T02:31:20Z`; `fromisoformat` wants an
        # offset it recognises.
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_cancelled(state: str) -> bool:
    """True for any state Grab uses to mean the order didn't happen.

    Substring rather than an exact set: the archive holds both
    ``CANCELLED`` and ``ORDER_CANCELLED`` depending on which sweep wrote
    the row, and a state that means cancelled must never be counted as
    revenue because it didn't match a literal.
    """
    return "CANCEL" in (state or "").upper()


def _mix_key(flag: bool | None) -> str:
    """Which slice an order belongs to. `None` is its own slice."""
    if flag is True:
        return "new"
    if flag is False:
        return "returning"
    return "unknown"


def _build_customer_mix(
    tallies: dict[str, dict[str, Any]],
) -> CustomerMix:
    """Turn the per-slice tallies collected during the scan into the mix."""
    buckets: dict[str, CustomerMixBucket] = {}
    for key in ("new", "returning", "unknown"):
        t = tallies[key]
        earning = t["earning_orders"]
        buckets[key] = CustomerMixBucket(
            orders=t["orders"],
            cancelledOrders=t["cancelled"],
            customers=len(t["phones"]),
            revenueVnd=t["revenue"],
            # Averaged over the orders that actually contributed revenue:
            # cancellations are out, and so is any order whose total we
            # couldn't read. Both would otherwise pull the figure down as
            # if customers had spent less.
            avgOrderValue=(t["revenue"] / earning) if earning > 0 else 0.0,
        )

    known_orders = buckets["new"].orders + buckets["returning"].orders
    known_revenue = buckets["new"].revenue_vnd + buckets["returning"].revenue_vnd

    return CustomerMix(
        new=buckets["new"],
        returning=buckets["returning"],
        unknown=buckets["unknown"],
        # None, not 0.0 — "no orders yet" is not "0% from new customers".
        newOrderShare=(
            buckets["new"].orders / known_orders if known_orders > 0 else None
        ),
        newRevenueShare=(
            buckets["new"].revenue_vnd / known_revenue if known_revenue > 0 else None
        ),
    )


# ── endpoint ─────────────────────────────────────────────────────────────────


@router.get("/overview", response_model=CustomersOverviewResponse)
def get_customers_overview(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> CustomersOverviewResponse:
    """Return the customers / sources / orders three-lens view.

    Auth: requires a logged-in user (the standard
    ``require_user`` dep). The view is scoped to that user's
    owned store — rows in other stores are invisible, matching
    the multi-store isolation guardrail in ``/api/orders``.

    Aggregation strategy:
      * Scan all ``OrderArchive`` rows for the store once.
      * For each row, fan out into three upstreams:
        - the customer bucket (group on ``eater.mobileNumber``)
        - the source bucket (group on ``merchant_id``)
        - the per-order bucket (passes through with the
          hydrated ``OrderDetailLite``)
      * Rows with malformed ``detail_json`` are silently
        skipped from the customer / orders bucket (the
        source bucket still counts them because the
        merchant_id is in a column, not the JSON blob).

    Performance note: for a busy store this is a single-table
    scan. The cron writes at most ~30 rows per minute per
    store in the worst case, so the per-scan cost is bounded.
    If the store grows past ~10k archived rows we should add a
    last-30d default filter — flagged as a future optimisation.
    """
    log.info("customers_overview user=%s", user.id)

    store_id = _store_id_for_user(session, user.id)
    if store_id is None:
        # No store yet → empty three lists (the menu still renders
        # an empty-state, which is the right UX for a fresh signup).
        return CustomersOverviewResponse()

    from sqlmodel import select as _sel

    rows: list[OrderArchive] = list(
        session.exec(
            _sel(OrderArchive).where(OrderArchive.store_id == store_id)
        ).all()
    )

    # ── customers bucket (group by eater.mobileNumber) ─────────────────────
    customers_by_phone: dict[str, CustomerSummary] = {}
    # Which order currently owns each customer's headline — see the
    # `recency` tuple built per row below.
    customer_recency: dict[str, tuple[datetime, datetime, int]] = {}
    # Track distinct customers per source as a side-effect of the
    # same scan — cheaper than a second pass.
    source_phone_seen: dict[str, set[str]] = {}
    # New / returning / unknown tallies, filled in the same pass for the
    # same reason.
    mix_tallies: dict[str, dict[str, Any]] = {
        key: {
            "orders": 0,
            "cancelled": 0,
            "earning_orders": 0,
            "revenue": 0.0,
            "phones": set(),
        }
        for key in ("new", "returning", "unknown")
    }

    for row in rows:
        merchant_id = row.merchant_id or ""
        if merchant_id not in source_phone_seen:
            source_phone_seen[merchant_id] = set()

        payload = row.detail_payload()
        if not payload:
            # The source bucket still gets this row (merchant_id is
            # a column, not in the JSON blob). The customer / orders
            # buckets skip it silently — same defensive pattern as
            # ``_load_archive_for_order_ids``.
            source_phone_seen[merchant_id].add("")  # unknown customer
            continue

        eater = _extract_eater(payload)
        phone = eater.get("mobileNumber") or ""
        phone_key = phone or ""  # keep empty-phone rows grouped together
        source_phone_seen[merchant_id].add(phone_key)

        # Pull the fare total from the raw payload so the customer
        # card headline can show the most-recent order's total.
        order = payload.get("order") if isinstance(payload.get("order"), dict) else payload
        fare = order.get("fare") if isinstance(order, dict) else None
        total = ""
        if isinstance(fare, dict):
            total = _normalize_total(str(fare.get("totalDisplay") or ""))

        is_new = extract_new_customer_flag(payload)

        tally = mix_tallies[_mix_key(is_new)]
        tally["orders"] += 1
        tally["phones"].add(phone_key)
        if _is_cancelled(row.state):
            tally["cancelled"] += 1
        else:
            amount = parse_order_amount(total)
            if amount is not None:
                tally["revenue"] += amount
                # Counted separately from `orders` so an order whose total
                # we couldn't read stays out of the average as well as out
                # of the revenue. Leaving it in the denominator would be
                # the same as treating its total as zero — exactly what
                # `parse_order_amount` returns None to prevent.
                tally["earning_orders"] += 1

        # Rank on when the ORDER was placed, falling back to when we
        # polled, then the row id so the winner is never decided by the
        # order rows happen to come back from SQLite.
        #
        # This used to compare `last_seen_at` against itself twice
        # (`(d, d)`), which is no tie-break at all — and ties are the norm,
        # not the exception: the cron stamps every row in one sweep with a
        # single timestamp, and both 08-08 rows in this store's archive
        # carry the identical `last_seen_at` while the orders were placed
        # twelve hours apart. The losing side of that coin toss decides
        # which order's new-customer flag the card reports, so a returning
        # customer could read as new for no reason at all.
        recency = (
            _order_created_at(payload) or row.last_seen_at or datetime.min,
            row.last_seen_at or datetime.min,
            row.id or 0,
        )

        existing = customers_by_phone.get(phone_key)
        if existing is None:
            summary = CustomerSummary(
                mobileNumber=phone,
                name=str(eater.get("name") or ""),
                address=str(eater.get("address") or ""),
                orderCount=1,
                totalDisplay=total,
                isNewCustomer=is_new,
                lastOrderAt=row.last_seen_at,
                lastState=row.state,
            )
            customers_by_phone[phone_key] = summary
            customer_recency[phone_key] = recency
        else:
            existing.order_count += 1
            if recency >= customer_recency[phone_key]:
                customer_recency[phone_key] = recency
                # Everything on the headline comes from the same winning
                # order, `total` included even when it's empty. Keeping a
                # previous order's total next to this one's state and
                # new-customer flag would make the card quietly describe
                # two different orders at once.
                existing.last_order_at = row.last_seen_at
                existing.last_state = row.state
                existing.is_new_customer = is_new
                existing.total_display = total

    # ── sources bucket (group by merchant_id) ───────────────────────────────
    source_counts: dict[str, int] = {}
    for row in rows:
        merchant_id = row.merchant_id or ""
        source_counts[merchant_id] = source_counts.get(merchant_id, 0) + 1

    # Look up Store.address + Store.name + Store.region per distinct
    # merchant_id (one store row per branch in this codebase —
    # Store.merchant_id is unique). Missing row → empty strings (e.g.
    # archive from a branch whose Store was deleted). Single batched
    # query, not N+1.
    #
    # ``name`` is the fallback subtitle when ``address`` is empty so
    # the merchant can still identify the branch — registration
    # currently stores ``address=""`` for new stores, and Grab's
    # ``business_attributes`` doesn't always include an address, so
    # without this fallback every card would just show the opaque
    # merchant_id UUID.
    #
    # ``region`` is the auto-derived city/province (e.g. "Đà Nẵng")
    # populated by ``app.core.region.extract_city`` at write time. The
    # dashboard renders it as a region badge next to the address; the
    # partner API reads it to label each order's `source` field as
    # ``"GF " + region`` so partners can route orders by geography
    # without re-parsing the address string.
    store_meta_by_mid: dict[str, tuple[str, str, str]] = {}
    if source_counts:
        from sqlmodel import select as _sel
        mids = [m for m in source_counts if m]
        if mids:
            store_rows = session.exec(
                _sel(Store.merchant_id, Store.address, Store.name, Store.region).where(
                    Store.merchant_id.in_(mids)
                )
            ).all()
            store_meta_by_mid = {
                mid: (addr or "", name or "", region or "")
                for mid, addr, name, region in store_rows
            }

    sources = []
    for mid, count in sorted(source_counts.items()):
        addr, sname, sregion = store_meta_by_mid.get(mid, ("", "", ""))
        sources.append(
            SourceSummary(
                merchantId=mid,
                address=addr,
                name=sname,
                region=sregion,
                orderCount=count,
                distinctCustomers=len(source_phone_seen.get(mid, set())),
            )
        )

    # ── orders bucket (one OrderSummary per archive row) ────────────────────
    orders: list[OrderSummary] = []
    for row in rows:
        payload = row.detail_payload()
        if not payload:
            continue
        try:
            detail = OrderDetailLite.from_raw(payload)
        except Exception as exc:  # noqa: BLE001 — defensive
            log.warning(
                "customers_overview: %s failed to hydrate: %r",
                row.order_id, exc,
            )
            continue
        orders.append(
            OrderSummary(
                orderId=row.order_id,
                displayId=row.display_id or "",
                state=row.state or "",
                firstSeenAt=row.first_seen_at,
                lastSeenAt=row.last_seen_at,
                detail=detail,
            )
        )

    # Latest seen first — the merchant wants to see today's
    # activity at the top, not the order they fetched for the
    # first time three weeks ago.
    orders.sort(key=lambda o: o.last_seen_at, reverse=True)

    # Customers: most-recent-order first too. ``datetime.min`` is
    # the sentinel for any customer whose ``last_order_at`` is
    # None — they sort to the end on ``reverse=True``.
    from datetime import datetime as _dt
    customers = sorted(
        customers_by_phone.values(),
        key=lambda c: c.last_order_at or _dt.min,
        reverse=True,
    )

    return CustomersOverviewResponse(
        customers=customers,
        sources=sources,
        orders=orders,
        customerMix=_build_customer_mix(mix_tallies),
    )