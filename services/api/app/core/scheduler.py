"""APScheduler wiring for PulseOrder.

Phase 11: register background jobs that keep all stores' tokens fresh
and pre-warm menu/scorecard data so the frontend stays fast.

Intervals are tuned to Grab's typical token lifetime (~6 h):
    - token_refresh   every 6 h, per store
    - menu_sync       every 12 h, per store (caches menu locally)
    - store_sync      every 24 h, per store (updates name/address)
    - scorecard_sync  every 1 h, per store (kpi freshness)
    - health_pulse    every 5 min (liveness heartbeat)

The scheduler runs in the same process as FastAPI — no external worker.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session

from app.core.db import get_session
from app.core.security import decrypt_token, encrypt_token
from app.models import AuditLog, Store

log = logging.getLogger("pulseorder.scheduler")

_scheduler: AsyncIOScheduler | None = None


# ── Job bodies ──────────────────────────────────────────────────────────────────


def _refresh_one_store(store_id: int) -> None:
    """Re-run Grab login for one store and persist the new tokens."""
    from app.core.config import settings
    from grab import ChallengeError, GrabClient, LoginError, StaticXRayProvider, login_three_step

    with get_session() as session:
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
    with get_session() as session:
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

    with get_session() as session:
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

    with get_session() as session:
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
        with get_session() as session:
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

    with get_session() as session:
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
