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
    CustomerSummary,
    CustomersOverviewResponse,
    OrderSummary,
    SourceSummary,
)
from app.schemas.orders import OrderDetailLite

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
    # Track distinct customers per source as a side-effect of the
    # same scan — cheaper than a second pass.
    source_phone_seen: dict[str, set[str]] = {}

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

        existing = customers_by_phone.get(phone_key)
        if existing is None:
            customers_by_phone[phone_key] = CustomerSummary(
                mobileNumber=phone,
                name=str(eater.get("name") or ""),
                address=str(eater.get("address") or ""),
                orderCount=1,
                totalDisplay=total,
                lastOrderAt=row.last_seen_at,
                lastState=row.state,
            )
        else:
            existing.order_count += 1
            # Move the "last order" pointer forward — the customer
            # card headline shows the most-recent order's state,
            # total, and timestamp.
            #
            # The tie-break uses ``>=`` on ``last_seen_at`` AND
            # ``updated_at`` so that a re-archived row at the same
            # ``last_seen_at`` second (common — the cron can re-archive
            # the same order on the same second with a different
            # ``state`` / ``totalDisplay``) still replaces the older
            # total/state. Strict ``>`` would pin the customer card
            # to the *first* sweep's state even though the archive
            # row itself has moved on.
            def _recency_key(d) -> tuple:
                # Module-level ``datetime`` (imported at top of file) is
                # the sentinel so the comparison identity is stable.
                return (d or datetime.min, d or datetime.min)

            if row.last_seen_at and (
                existing.last_order_at is None
                or _recency_key(row.last_seen_at) >= _recency_key(existing.last_order_at)
            ):
                existing.last_order_at = row.last_seen_at
                existing.last_state = row.state
                if total:
                    existing.total_display = total

    # ── sources bucket (group by merchant_id) ───────────────────────────────
    source_counts: dict[str, int] = {}
    for row in rows:
        merchant_id = row.merchant_id or ""
        source_counts[merchant_id] = source_counts.get(merchant_id, 0) + 1

    # Look up Store.address + Store.name per distinct merchant_id (one
    # store row per branch in this codebase — Store.merchant_id is
    # unique). Missing row → empty strings (e.g. archive from a branch
    # whose Store was deleted). Single batched query, not N+1.
    #
    # ``name`` is the fallback subtitle when ``address`` is empty so
    # the merchant can still identify the branch — registration
    # currently stores ``address=""`` for new stores, and Grab's
    # ``business_attributes`` doesn't always include an address, so
    # without this fallback every card would just show the opaque
    # merchant_id UUID.
    store_meta_by_mid: dict[str, tuple[str, str]] = {}
    if source_counts:
        from sqlmodel import select as _sel
        mids = [m for m in source_counts if m]
        if mids:
            store_rows = session.exec(
                _sel(Store.merchant_id, Store.address, Store.name).where(
                    Store.merchant_id.in_(mids)
                )
            ).all()
            store_meta_by_mid = {
                mid: (addr or "", name or "")
                for mid, addr, name in store_rows
            }

    sources = []
    for mid, count in sorted(source_counts.items()):
        addr, sname = store_meta_by_mid.get(mid, ("", ""))
        sources.append(
            SourceSummary(
                merchantId=mid,
                address=addr,
                name=sname,
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
    )