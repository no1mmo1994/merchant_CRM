"""APScheduler wiring for PulseOrder.

Phase 11: register background jobs that keep all stores' tokens fresh
and pre-warm menu/scorecard data so the frontend stays fast.

Intervals are tuned to Grab's typical token lifetime (~6 h):
    - token_refresh   every 6 h, per store
    - menu_sync       every 12 h, per store (caches menu locally)
    - store_sync      every 24 h, per store (updates name/address)
    - scorecard_sync  every 1 h, per store (kpi freshness)
    - health_pulse    every 5 min (liveness heartbeat)
    - orders_poll     every 30 s, per store (detects new orders +
                       writes the "đã chạy get lại đơn" snapshot for
                       the dashboard banner)

The scheduler runs in the same process as FastAPI — no external worker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import httpx
from sqlmodel import Session

from app.core.db import session_scope
from app.core.security import decrypt_token, encrypt_token
from app.models import AuditLog, OrderArchive, OrderSnapshot, Store

log = logging.getLogger("pulseorder.scheduler")

_scheduler: AsyncIOScheduler | None = None


# ── Job bodies ──────────────────────────────────────────────────────────────────


def _refresh_one_store(store_id: int) -> None:
    """Re-run Grab login for one store and persist the new tokens."""
    from app.core.config import settings
    from grab import ChallengeError, GrabClient, LoginError, StaticXRayProvider, login_three_step

    with session_scope() as session:
        store: Store | None = session.get(Store, store_id)
        if store is None:
            log.warning("token_refresh: store id=%s not found, skipping", store_id)
            return

        xray = decrypt_token(store.encrypted_xray_token)
        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    login_three_step(
                        email=store.owner.username if store.owner else "",
                        password="",
                        xray=StaticXRayProvider(step1_token=xray, step3_token=xray),
                        verify_ssl=settings.grab_verify_ssl,
                    )
                )
            finally:
                loop.close()
        except (LoginError, ChallengeError) as exc:
            log.warning("token_refresh: store=%s failed: %s", store.merchant_id, exc)
            session.add(
                AuditLog(
                    user_id=store.owner_user_id,
                    action="scheduler.token_refresh.failed",
                    entity_type="store",
                    entity_id=store.merchant_id,
                    payload_json=str(exc),
                )
            )
            session.commit()
            return

        store.encrypted_auth_token = encrypt_token(result.authn_token)
        store.encrypted_display_token = encrypt_token(result.display_token)
        store.last_refresh_at = datetime.utcnow()
        session.add(store)
        session.add(
            AuditLog(
                user_id=store.owner_user_id,
                action="scheduler.token_refresh.ok",
                entity_type="store",
                entity_id=store.merchant_id,
            )
        )
        session.commit()
        log.info("token_refresh: store=%s ok", store.merchant_id)


def _all_stores() -> list[int]:
    with session_scope() as session:
        return [s.id for s in session.query(Store).all()]


def job_refresh_all_tokens() -> None:
    """Refresh every store's token. Scheduled every 6 hours."""
    for store_id in _all_stores():
        try:
            _refresh_one_store(store_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("token_refresh: store_id=%s crashed: %s", store_id, exc)


def _sync_one_menu(store_id: int) -> None:
    """Cache the full menu for a single store. Errors are logged, never raised."""
    from grab import GrabClient
    from grab.endpoints.menu import get_full_menu

    with session_scope() as session:
        store = session.get(Store, store_id)
        if store is None:
            return
        authn = decrypt_token(store.encrypted_auth_token)
        merchant_id = store.merchant_id

    async def _drive() -> dict[str, Any]:
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            return await get_full_menu(client)

    try:
        loop = asyncio.new_event_loop()
        try:
            menu = loop.run_until_complete(_drive())
        finally:
            loop.close()
        log.info("menu_sync: store=%s ok (%d top-level keys)", merchant_id, len(menu))
        # We don't persist the menu to a table yet — it's served live from
        # /api/menu. The job keeps the token fresh and warms the path.
    except Exception as exc:  # noqa: BLE001
        log.warning("menu_sync: store=%s failed: %s", merchant_id, exc)


def job_sync_all_menus() -> None:
    """Pre-warm the menu endpoint for every store. Every 12 hours."""
    for store_id in _all_stores():
        try:
            _sync_one_menu(store_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("menu_sync: store_id=%s crashed: %s", store_id, exc)


def _sync_one_store(store_id: int) -> None:
    """Refresh store name/address from Grab's business_attributes."""
    from grab import GrabClient
    from grab.endpoints.store import get_business_attributes

    with session_scope() as session:
        store = session.get(Store, store_id)
        if store is None:
            return
        authn = decrypt_token(store.encrypted_auth_token)
        merchant_id = store.merchant_id

    async def _drive() -> dict[str, Any]:
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            return await get_business_attributes(client)

    try:
        loop = asyncio.new_event_loop()
        try:
            attrs = loop.run_until_complete(_drive())
        finally:
            loop.close()
        # Update null address/name if Grab returned them
        with session_scope() as session:
            s = session.get(Store, store_id)
            if s is not None:
                if not s.name and attrs.get("name"):
                    s.name = str(attrs["name"])
                if not s.address and attrs.get("address"):
                    s.address = str(attrs["address"])
                session.add(s)
                session.commit()
        log.info("store_sync: store=%s ok", merchant_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("store_sync: store=%s failed: %s", merchant_id, exc)


def job_sync_all_stores() -> None:
    """Refresh business attributes for every store. Every 24 hours."""
    for store_id in _all_stores():
        try:
            _sync_one_store(store_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("store_sync: store_id=%s crashed: %s", store_id, exc)


def _sync_one_scorecard(store_id: int) -> None:
    """Touch the scorecard endpoint so a cached value is ready on read."""
    from grab import GrabClient
    from grab.endpoints.store import get_scorecard

    with session_scope() as session:
        store = session.get(Store, store_id)
        if store is None:
            return
        authn = decrypt_token(store.encrypted_auth_token)
        merchant_id = store.merchant_id

    async def _drive() -> dict[str, Any]:
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            return await get_scorecard(client)

    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_drive())
        finally:
            loop.close()
        log.info("scorecard_sync: store=%s ok", merchant_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("scorecard_sync: store=%s failed: %s", merchant_id, exc)


def job_sync_all_scorecards() -> None:
    """Refresh scorecard data for every store. Every 1 hour."""
    for store_id in _all_stores():
        try:
            _sync_one_scorecard(store_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("scorecard_sync: store_id=%s crashed: %s", store_id, exc)


def job_health_pulse() -> None:
    """Cheap heartbeat — proves the scheduler thread is alive."""
    log.debug("scheduler heartbeat at %s", datetime.utcnow().isoformat())


# ── Order-polling cron (every 30 s) ────────────────────────────────────────────
#
# The dashboard needs new orders to surface within seconds of the
# merchant accepting them on the Grab side. Operator feedback: "đơn
# mới không push realtime lên dashboard" — 2 min was too slow. We
# shortened to 30 s. The per-store poll reuses the same authn token
# and runs sequentially across stores, so the network cost is one
# list_preparing_orders call per store per 30 s. Detail fan-out
# (which only fires when the list returns ≥ 1 row) reuses the same
# connection so we don't double the Grab API surface.


ORDERS_POLL_INTERVAL_SECONDS = 30


# Module-level mirrors of the OrderSnapshot status values so the
# scheduler + the router agree on the exact vocabulary the frontend
# reads (status-banner copy is keyed off these strings).
POLL_STATUS_OK = "ok"
POLL_STATUS_EMPTY = "empty"
POLL_STATUS_ERROR = "error"
POLL_STATUS_NEVER = "never"


def _friendly_now() -> datetime:
    """UTC tz-aware ``datetime`` for snapshot timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _format_localized(dt: datetime | None) -> str:
    """Render a snapshot timestamp as ``HH:MM`` (Vietnam local time).

    Used by the message string so the dashboard banner can show
    "lúc 14:42" without re-deriving the timezone on the client.
    """
    if dt is None:
        return ""
    # UTC + 7 ≈ Vietnam. We never reach for zoneinfo here so the
    # scheduler stays free of system-tz lookups.
    local = dt + timedelta(hours=7)
    return local.strftime("%H:%M")


# ── Per-order detail fan-out + archive writer ───────────────────────────────
#
# The "Đã hoàn tất" + "Đã hủy" tabs on the dashboard need the full
# customer info (name / phone / address / comment / items) for every
# historical order. Grab's daily-reports endpoint only returns a thin
# summary — once an order has left the preparing queue, the per-order
# detail endpoint often WAF-rejects it. So the cron snapshots every
# preparing order's full detail at first sight, and the
# ``/api/orders/history`` route hydrates ``OrderDetailLite`` from
# this archive instead of fanning out a detail call that might 400.


def _archive_preparing_orders(
    *,
    order_ids: list[str],
    authn: str,
    merchant_id: str,
) -> list[tuple[str, str, str, str]]:
    """Fan out one ``/orders/{id}`` call per row in ``order_ids``.

    Returns ``[(order_id, display_id, state, detail_json), …]`` —
    one tuple per order whose detail call succeeded. The
    ``detail_json`` is the raw ``{"order": {...}}`` payload verbatim
    so the router's existing ``OrderDetailLite.from_raw`` projection
    keeps working unchanged.

    Fan-out runs sequentially inside a single event loop so we
    don't fight Grab's WAF with parallel connections from the same
    IP. The number of rows in a typical preparing queue is small
    (1–10), so sequential is fine.
    """
    import json

    from grab import GrabClient
    from grab.endpoints.orders import get_order_detail

    results: list[tuple[str, str, str, str]] = []

    async def _drive() -> list[tuple[str, str, str, str]]:
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            out: list[tuple[str, str, str, str]] = []
            for oid in order_ids:
                try:
                    payload = await get_order_detail(client, oid)
                except httpx.HTTPError as exc:
                    # WAF rejection / network blip on a single row
                    # must NOT stop the rest of the fan-out — we
                    # still want to archive every other row.
                    log.warning(
                        "orders_poll archive: detail failed for %s: %r",
                        oid, exc,
                    )
                    continue
                if not isinstance(payload, dict):
                    continue
                order = payload.get("order")
                if not isinstance(order, dict):
                    order = payload
                display_id = str(order.get("displayID") or "")
                state = str(order.get("state") or "")
                try:
                    detail_json = json.dumps(payload, ensure_ascii=False)
                except (TypeError, ValueError):
                    log.warning(
                        "orders_poll archive: %s detail not JSON-serialisable",
                        oid,
                    )
                    continue
                out.append((oid, display_id, state, detail_json))
            return out

    try:
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(_drive())
        finally:
            loop.close()
    except Exception as exc:  # noqa: BLE001
        # An entire-loop failure (auth, TLS, etc.) is already
        # captured in the snapshot's status banner; the archive
        # write is best-effort and must never crash the cron.
        log.warning(
            "orders_poll archive: fan-out crashed for store=%s: %r",
            merchant_id, exc,
        )
        return []
    return results


def _write_archive_rows(
    *,
    session: Session,
    store_id: int,
    merchant_id: str,
    rows: list[tuple[str, str, str, str]],
    now: datetime,
) -> None:
    """Upsert ``OrderArchive`` rows in the SAME session as the snapshot.

    For each ``(order_id, display_id, state, detail_json)`` tuple:
      * If a row with this ``order_id`` doesn't exist → INSERT
        with ``first_seen_at = last_seen_at = now`` and the full
        ``detail_json`` captured verbatim — this is the "frozen at
        first sight" snapshot.
      * Otherwise → UPDATE ``state``, ``display_id``,
        ``last_seen_at``, ``updated_at`` only. ``detail_json`` is
        deliberately NOT overwritten — the operator's contract is
        that once we've captured customer info (name / phone /
        items / fare / address / comment), it stays put forever
        regardless of subsequent state transitions.

        Why freeze ``detail_json`` after first sight?
        Two cron paths feed this upsert: the preparing queue
        fan-out (rich detail) and the daily-reports COMPLETED /
        CANCELLED fan-out (often thin / anonymised by Grab). If we
        overwrote on every tick, the COMPLETED/CANCELLED snapshot
        would clobber the preparing snapshot's eater block with
        Grab's anonymised ``name="***" + mobileNumber=""`` payload
        — the merchant would see "Khách Ẩn danh" on every order
        that ever moved out of the preparing queue. The user's
        rule ("chỉ trạng thái đơn hàng thay đổi theo real-time")
        maps directly to "state advances, detail_json freezes".

        ``first_seen_at`` also stays at its original value so we
        can tell which orders we've been seeing for a while vs.
        just-arrived.
    """
    from sqlmodel import select as _sel

    if not rows:
        return
    incoming_ids = [oid for oid, _, _, _ in rows]
    existing = {
        r.order_id: r
        for r in session.exec(
            _sel(OrderArchive).where(OrderArchive.order_id.in_(incoming_ids))
        ).all()
    }
    for order_id, display_id, state, detail_json in rows:
        row = existing.get(order_id)
        if row is None:
            # First sight — freeze the detail payload verbatim.
            # Subsequent state transitions will only touch
            # ``state`` / ``display_id`` / ``last_seen_at``.
            session.add(
                OrderArchive(
                    store_id=store_id,
                    merchant_id=merchant_id,
                    order_id=order_id,
                    display_id=display_id,
                    state=state,
                    detail_json=detail_json,
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.store_id = store_id
            row.merchant_id = merchant_id
            # ``display_id`` is monotonic: the first non-empty value
            # we ever saw wins, later updates don't blank it out.
            # This keeps the customer-card headline stable across
            # state transitions.
            row.display_id = display_id or row.display_id
            # Real-time state transitions — the only thing that
            # changes after first sight, per the operator's rule.
            row.state = state
            # ``detail_json`` deliberately left untouched. See the
            # docstring above for the anonymisation reasoning.
            row.last_seen_at = now
            row.updated_at = now
            session.add(row)


def _archive_completed_cancelled_today(
    *,
    authn: str,
    merchant_id: str,
    now: datetime,
) -> tuple[list[tuple[str, str, str, str]], str | None]:
    """Fetch today's COMPLETED + CANCELLED summaries and archive them.

    The preparing-poll only sees orders currently in the preparing
    queue. Once an order transitions to ``ORDER_COMPLETED`` /
    ``ORDER_CANCELLED`` it disappears from that queue — so the
    preparing-poll never sees the new state, and the
    ``OrderArchive.state`` field freezes at ``ORDER_IN_PREPARE``
    forever. This helper closes that gap: after each preparing
    tick, also pull today's daily-reports summaries for both
    final states, fan out a per-row ``get_order_detail`` call
    (same pattern as the preparing fan-out), and let
    ``_write_archive_rows`` upsert the new state + full detail
    onto the existing archive row.

    Lookback:
      1 day. The daily-reports endpoint has bitten us before when
      the boundary crossed midnight Vietnam time — orders placed
      late yesterday that complete today would otherwise be
      missed. A 1-day window is cheap (it's just one HTTP call per
      state) and safe.

    Failure isolation:
      This helper is best-effort. Each state call is wrapped in
      its own try/except so a 5xx on COMPLETED doesn't block
      CANCELLED. The outer try/except around the event-loop dance
      ensures an auth/TLS failure never raises into the
      preparing-poll caller. The returned ``warning`` short-string
      is for the audit log payload only.
    """
    import json as _json

    from grab import GrabClient
    from grab.endpoints.orders import get_order_detail, list_daily_reports

    # 1-day lookback, ISO-8601 UTC with explicit ``Z`` suffix —
    # mirrors ``_iso_utc`` in routers/orders.py so the
    # daily-reports endpoint parses the window the same way as
    # the orders-history route.
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    warnings: list[str] = []

    async def _gather_order_ids() -> list[str]:
        """Return today's order_ids for COMPLETED + CANCELLED, deduped."""
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            ids: list[str] = []
            seen: set[str] = set()
            for state in ("COMPLETED", "CANCELLED"):
                try:
                    raw = await list_daily_reports(
                        client,
                        start_time=start_iso,
                        end_time=end_iso,
                        state=state,
                    )
                except httpx.HTTPError as exc:
                    log.warning(
                        "orders_poll daily-reports state=%s failed: %r",
                        state, exc,
                    )
                    warnings.append(
                        f"daily-reports {state}: {type(exc).__name__}"
                    )
                    continue
                if not isinstance(raw, dict):
                    continue
                rows = raw.get("statements") or []
                if not isinstance(rows, list):
                    continue
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    # Daily-reports uses ``ID`` (capital); fall back
                    # to ``orderID`` for forward-compat (same as
                    # routers/orders.py line 656).
                    oid = str(r.get("ID") or r.get("orderID") or "")
                    if oid and oid not in seen:
                        seen.add(oid)
                        ids.append(oid)
            return ids

    async def _fan_out(ids: list[str]) -> list[tuple[str, str, str, str]]:
        """Per-row ``get_order_detail`` fan-out, same loop as the
        preparing fan-out. Returns tuples shaped for
        ``_write_archive_rows``."""
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            out: list[tuple[str, str, str, str]] = []
            for oid in ids:
                try:
                    payload = await get_order_detail(client, oid)
                except httpx.HTTPError as exc:
                    log.warning(
                        "orders_poll daily-reports detail failed for %s: %r",
                        oid, exc,
                    )
                    continue
                if not isinstance(payload, dict):
                    continue
                order = payload.get("order")
                if not isinstance(order, dict):
                    order = payload
                display_id = str(order.get("displayID") or "")
                state = str(order.get("state") or "")
                try:
                    detail_json = _json.dumps(payload, ensure_ascii=False)
                except (TypeError, ValueError):
                    log.warning(
                        "orders_poll daily-reports %s not JSON-serialisable",
                        oid,
                    )
                    continue
                out.append((oid, display_id, state, detail_json))
            return out

    try:
        loop = asyncio.new_event_loop()
        try:
            order_ids = loop.run_until_complete(_gather_order_ids())
            archive_rows = (
                loop.run_until_complete(_fan_out(order_ids))
                if order_ids
                else []
            )
        finally:
            loop.close()
    except Exception as exc:  # noqa: BLE001 — defensive
        log.warning(
            "orders_poll daily-reports crashed for store=%s: %r",
            merchant_id, exc,
        )
        return [], f"daily-reports loop: {type(exc).__name__}"

    warning_concat = "; ".join(warnings) if warnings else None
    return archive_rows, warning_concat


def _poll_one_store(store_id: int) -> None:
    """Poll Grab's preparing-order queue once and write the snapshot.

    Outcome mapping:
      * ≥ 1 order    → ``status="ok"``   message="Đã chạy get lại đơn
        lúc HH:MM — tìm thấy N đơn".
      * 0 orders     → ``status="empty"`` message="Đã chạy get lại
        đơn lúc HH:MM — chưa tìm thấy đơn" (the user-facing banner
        the operator wanted — verbatim).
      * exception    → ``status="error"`` message="Lỗi khi get lại
        đơn lúc HH:MM — <short>".

    Side effect: when the list call succeeds, the cron also fans out
    one ``GET /orders/{id}`` per row and persists the full payload
    into ``OrderArchive``. This is the persistence guarantee the
    user asked for — once we've seen a preparing order, the
    customer's name / phone / address / items / fare / note are
    captured in our DB regardless of whether the order later moves
    to ``ORDER_COMPLETED`` / ``ORDER_CANCELLED`` (those states
    return only thin summary fields from Grab's daily-reports
    endpoint, so without an archive we'd lose the customer info
    forever).

    The snapshot write must still happen on detail-fan-out failure —
    that's the "cron still runs even if detail calls fail" guarantee
    the dashboard banner depends on.
    """
    from grab import GrabClient
    from grab.endpoints.orders import get_order_detail, list_preparing_orders

    with session_scope() as session:
        store = session.get(Store, store_id)
        if store is None:
            log.warning("orders_poll: store id=%s not found, skipping", store_id)
            return
        authn = decrypt_token(store.encrypted_auth_token)
        merchant_id = store.merchant_id
        owner_user_id = store.owner_user_id

    started_at = _friendly_now()
    status_value = POLL_STATUS_ERROR
    message = ""
    order_count = 0
    # Archive payloads keyed by Grab order id — collected from the
    # list's per-row fan-out and written to ``OrderArchive`` below.
    archive_rows: list[tuple[str, str, str, str]] = []
    # Free-form short warnings from the daily-reports sub-poll. Used
    # only for the audit-log payload (the user-facing banner still
    # describes the preparing poll's outcome).
    daily_warnings: list[str] = []

    async def _drive() -> dict[str, Any]:
        async with GrabClient(authn_token=authn, merchant_id=merchant_id) as client:
            return await list_preparing_orders(client)

    try:
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(_drive())
        finally:
            loop.close()
    except httpx.HTTPError as exc:
        log.warning("orders_poll: store=%s http error: %r", merchant_id, exc)
        message = (
            f"Lỗi khi get lại đơn lúc {_format_localized(started_at)} — "
            f"{type(exc).__name__}."
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("orders_poll: store=%s crashed: %s", merchant_id, exc)
        message = (
            f"Lỗi khi get lại đơn lúc {_format_localized(started_at)} — "
            f"{type(exc).__name__}."
        )
    else:
        orders_block = raw.get("orders") if isinstance(raw, dict) else None
        order_ids: list[str] = []
        if isinstance(orders_block, list):
            order_ids = [
                str(r.get("orderID") or "")
                for r in orders_block
                if isinstance(r, dict) and r.get("orderID")
            ]
            order_count = len(order_ids)
        if order_count > 0:
            status_value = POLL_STATUS_OK
            message = (
                f"Đã chạy get lại đơn lúc {_format_localized(started_at)} "
                f"— tìm thấy {order_count} đơn."
            )
        else:
            status_value = POLL_STATUS_EMPTY
            message = (
                f"Đã chạy get lại đơn lúc {_format_localized(started_at)} "
                f"— chưa tìm thấy đơn."
            )

        # Per-row detail fan-out — runs only when the list call
        # actually returned ≥ 1 row. We reuse the same authn/merchant
        # pair so we don't need a second GrabClient round-trip; the
        # list endpoint already authenticated the connection.
        if order_ids:
            archive_rows = _archive_preparing_orders(
                order_ids=order_ids,
                authn=authn,
                merchant_id=merchant_id,
            )

        # Also poll today's COMPLETED + CANCELLED summaries and
        # upsert them into OrderArchive. The preparing queue loses
        # track of an order as soon as it transitions out of
        # ORDER_IN_PREPARE, so without this the customer-info menu
        # would show stale "Đang chuẩn bị" forever. Failure here
        # must NOT poison the preparing poll above.
        try:
            daily_rows, daily_warning = _archive_completed_cancelled_today(
                authn=authn,
                merchant_id=merchant_id,
                now=started_at,
            )
            archive_rows.extend(daily_rows)
            if daily_warning:
                daily_warnings.append(daily_warning)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning(
                "orders_poll completed/cancelled sub-poll crashed for store=%s: %r",
                merchant_id, exc,
            )
            daily_warnings.append(f"sub-poll: {type(exc).__name__}")

    next_at = started_at + timedelta(seconds=ORDERS_POLL_INTERVAL_SECONDS)

    with session_scope() as session:
        snap = session.get(OrderSnapshot, store_id)
        if snap is None:
            snap = OrderSnapshot(
                store_id=store_id,
                merchant_id=merchant_id,
                last_polled_at=started_at,
                next_poll_at=next_at,
                last_order_count=order_count,
                last_status=status_value,
                message=message,
                updated_at=started_at,
            )
            session.add(snap)
        else:
            snap.last_polled_at = started_at
            snap.next_poll_at = next_at
            snap.last_order_count = order_count
            snap.last_status = status_value
            snap.message = message
            snap.updated_at = started_at
            session.add(snap)

        # Persist the per-order customer snapshot. We do this in
        # the SAME session as the OrderSnapshot update so a single
        # commit covers both — no half-written cron state on crash.
        if archive_rows:
            _write_archive_rows(
                session=session,
                store_id=store_id,
                merchant_id=merchant_id,
                rows=archive_rows,
                now=started_at,
            )

        session.add(
            AuditLog(
                user_id=owner_user_id,
                action=f"scheduler.orders_poll.{status_value}",
                entity_type="store",
                entity_id=merchant_id,
                payload_json=(
                    f"order_count={order_count} archived={len(archive_rows)} "
                    f"daily_warnings={len(daily_warnings)}"
                ),
            )
        )
        session.commit()
        log.info(
            "orders_poll: store=%s status=%s count=%s archived=%s",
            merchant_id, status_value, order_count, len(archive_rows),
        )


def job_poll_all_stores() -> None:
    """Poll every store's preparing queue. Scheduled every 30 seconds.

    Per-store failures are swallowed so one bad store doesn't stop
    the others. The per-store snapshot remains ``status="error"``
    so the banner correctly surfaces the failure.
    """
    for store_id in _all_stores():
        try:
            _poll_one_store(store_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("orders_poll: store_id=%s crashed: %s", store_id, exc)


# ── Lifecycle ───────────────────────────────────────────────────────────────────


def start_scheduler() -> AsyncIOScheduler:
    """Idempotent — returns the existing scheduler if already started."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(job_refresh_all_tokens, IntervalTrigger(hours=6), id="token_refresh", replace_existing=True)
    scheduler.add_job(job_sync_all_menus, IntervalTrigger(hours=12), id="menu_sync", replace_existing=True)
    scheduler.add_job(job_sync_all_stores, IntervalTrigger(hours=24), id="store_sync", replace_existing=True)
    scheduler.add_job(job_sync_all_scorecards, IntervalTrigger(hours=1), id="scorecard_sync", replace_existing=True)
    scheduler.add_job(job_health_pulse, IntervalTrigger(minutes=5), id="health_pulse", replace_existing=True)
    scheduler.add_job(
        job_poll_all_stores,
        IntervalTrigger(seconds=ORDERS_POLL_INTERVAL_SECONDS),
        id="orders_poll",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler stopped")
