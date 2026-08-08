"""Store router — list stores, get store detail, select active store."""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.core.security import decrypt_token
from app.core.grab_errors import PASSCODE_CODE, PASSCODE_MESSAGE, is_passcode_error
from app.deps import get_session, require_user
from app.models import Store
from app.schemas import (
    OpeningHourDay,
    OpeningHourRange,
    OpeningHoursData,
    OpeningHoursResponse,
    SelectStoreRequest,
    StoreListResponse,
    StoreOut,
    StoreRuntimeStatus,
    UpdateStoreStatusRequest,
    UpdateStoreStatusResponse,
)
from grab import GrabClient
from grab.endpoints.profile import (
    get_merchant,
    get_open_status_v3,
    get_store_list,
    get_unified_profile,
)
from grab.endpoints.store import (
    get_business_attributes,
    get_scorecard,
    set_store_busy,
    set_store_temp_paused,
)

router = APIRouter(prefix="/api/stores", tags=["stores"])

log = logging.getLogger("pulseorder.stores")


@router.get("", response_model=StoreListResponse)
@router.get("/", response_model=StoreListResponse)
async def list_stores(
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> StoreListResponse:
    """Return all stores owned by the authenticated user."""
    stores = session.query(Store).filter(Store.owner_user_id == user.id).all()
    return StoreListResponse(stores=[StoreOut.model_validate(s) for s in stores])


@router.get("/{merchant_id}")
async def get_store(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Return combined store info from Grab (business attributes + scorecard)."""
    # Defensive: reject empty merchant_id so this catch-all never
    # matches the bare /api/stores path (the list endpoint above).
    if not merchant_id:
        raise HTTPException(status_code=404, detail="Store not found")
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    authn_token = decrypt_token(store.encrypted_auth_token)

    async with GrabClient(authn_token=authn_token, merchant_id=store.merchant_id) as client:
        attrs = await get_business_attributes(client)
        scorecard = await get_scorecard(client)

    return {
        "store": StoreOut.model_validate(store).model_dump(),
        "business_attributes": attrs,
        "scorecard": scorecard,
    }


@router.get("/{merchant_id}/info")
async def get_store_info(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Combined Grab store info + payout + scorecard for /settings.

    Mirrors `trangchu/get_thongtin_cuahang.py`: fans out to
    `business-attributes` + `scorecard` + `unified-profile` in sequence,
    then projects three grouped sections onto the wire:

    * `store_info`  — name, address, status, email, lat/long, photo
                     (from `data.grab_food_profile.merchant`)
    * `payout`      — store phone, owner phone, bank account, bank name,
                     account name (from `data.grab_food_store_profile`,
                     `data.grab_owner_contact`, `data.bank_details`)
    * `scorecard`   — store rating + tier (raw Grab payload, frontend
                     picks out `{title, desc, score, scoreRank}`)

    Each group is wrapped in `{"ok": bool, "data": ..., "error": str|None}`
    so the UI can still render the other two sections if Grab is partial.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    authn_token = decrypt_token(store.encrypted_auth_token)

    async with GrabClient(authn_token=authn_token, merchant_id=store.merchant_id) as client:
        # business-attributes
        try:
            attrs = await get_business_attributes(client)
            biz_ok = True
            biz_err: str | None = None
        except Exception as exc:  # noqa: BLE001 — wrap into a partial payload
            log.warning("business-attributes failed for %s: %s", merchant_id, exc)
            attrs = {}
            biz_ok = False
            biz_err = str(exc)

        # scorecard
        try:
            score = await get_scorecard(client)
            score_ok = True
            score_err: str | None = None
        except Exception as exc:  # noqa: BLE001
            log.warning("scorecard failed for %s: %s", merchant_id, exc)
            score = {}
            score_ok = False
            score_err = str(exc)

        # unified-profile
        try:
            unified = await get_unified_profile(client)
            unified_ok = True
            unified_err: str | None = None
        except Exception as exc:  # noqa: BLE001
            log.warning("unified-profile failed for %s: %s", merchant_id, exc)
            unified = {}
            unified_ok = False
            unified_err = str(exc)

    # Project — defensive against Grab reshaping the payload mid-release.
    merchant_block = (
        ((unified.get("data") or {}).get("grab_food_profile") or {}).get("merchant")
        if isinstance(unified, dict)
        else {}
    ) or {}
    store_profile_block = (
        ((unified.get("data") or {}).get("grab_food_store_profile") or {}).get("storeProfile")
        if isinstance(unified, dict)
        else {}
    ) or {}
    owner_contact = (
        (unified.get("data") or {}).get("grab_owner_contact")
        if isinstance(unified, dict)
        else {}
    ) or {}
    bank_details = (
        (unified.get("data") or {}).get("bank_details")
        if isinstance(unified, dict)
        else {}
    ) or {}

    store_info = {
        "ok": unified_ok,
        "data": {
            "name": merchant_block.get("name"),
            "address": merchant_block.get("address"),
            "status": merchant_block.get("status"),
            "email": merchant_block.get("email"),
            "latitude": merchant_block.get("latitude"),
            "longitude": merchant_block.get("longitude"),
            "photo": merchant_block.get("photo"),
            "small_picture": merchant_block.get("smallPicture"),
        },
        "error": unified_err,
    }

    payout = {
        "ok": unified_ok,
        "data": {
            "store_phone": (store_profile_block.get("storePIC") or {}).get("outletPhone"),
            "owner_name": (owner_contact.get("ContactName") if isinstance(owner_contact, dict) else None),
            "owner_phone": owner_contact.get("ContactPhoneNumber") if isinstance(owner_contact, dict) else None,
            "bank_account_name": bank_details.get("account_name") if isinstance(bank_details, dict) else None,
            "bank_name": bank_details.get("bank_name") if isinstance(bank_details, dict) else None,
            "bank_account_number": bank_details.get("account_number") if isinstance(bank_details, dict) else None,
        },
        "error": unified_err,
    }

    # Grab's scorecard endpoint returns a flat payload:
    #   {"title": "Gold", "desc": "...", "score": 92, "scoreRank": "TOP_10_PERCENT"}
    # Some Grab API versions may wrap it in {"data": {...}}. Try flat first,
    # then fall back to the .data wrapper — whichever succeeds wins.
    _score_data = score if isinstance(score, dict) else {}
    _inner = _score_data.get("data") if isinstance(_score_data, dict) else None
    _fields = _score_data if _inner is None else _inner
    if not isinstance(_fields, dict):
        _fields = {}

    scorecard_section = {
        "ok": score_ok,
        "data": {
            "title": _fields.get("title"),
            "desc": _fields.get("desc"),
            "score": _fields.get("score"),
            "scoreRank": _fields.get("scoreRank"),
            # Full payload so future fields remain accessible.
            "raw": score,
        },
        "error": score_err,
    }

    return {
        "store": StoreOut.model_validate(store).model_dump(),
        "store_info": store_info,
        "payout": payout,
        "scorecard": scorecard_section,
        "business_attributes": {"ok": biz_ok, "data": attrs, "error": biz_err},
    }


@router.get("/{merchant_id}/authn-token")
async def reveal_authn_token(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Return the decrypted `authnToken` for a store.

    Used by the Settings page so the operator can copy it and feed it into
    `Menu/getmenu.py` / `trangchu/get_thongtin_cuahang.py` directly. The
    token is decrypted server-side only; never persisted in plaintext.

    Each call writes an `audit_log` row (`action=store.authn_token.reveal`)
    so the operator has a tamper-evident record of every reveal.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    authn_token = decrypt_token(store.encrypted_auth_token)

    from app.deps import write_audit_log

    write_audit_log(
        session=session,
        user_id=user.id,
        action="store.authn_token.reveal",
        entity_type="store",
        entity_id=merchant_id,
        payload={"source": "settings"},
    )

    return {
        "merchant_id": store.merchant_id,
        "authn_token": authn_token,
        "last_refresh_at": store.last_refresh_at.isoformat() if store.last_refresh_at else None,
    }


@router.post("/select")
def select_store(
    body: SelectStoreRequest,
    response: Response,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    """Set the active store cookie so subsequent requests use it by default."""
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == body.merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    from app.core.config import settings

    response.set_cookie(
        key="active_store_id",
        value=str(store.id),
        httponly=True,
        samesite="lax",
        secure=settings.require_https,
        path="/",
    )
    return {"ok": True}


@router.delete("/{merchant_id}")
def delete_store(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    """Danger zone: permanently delete a store and its tokens.

    This removes the local row only — does not touch Grab. Use with care.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    from app.deps import write_audit_log

    session.delete(store)
    session.commit()

    write_audit_log(
        session=session,
        user_id=user.id,
        action="store.delete",
        entity_type="store",
        entity_id=merchant_id,
    )

    return {"deleted": True}


@router.get("/{merchant_id}/opening-hours", response_model=OpeningHoursResponse)
async def get_store_opening_hours(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> OpeningHoursResponse:
    """Realtime merchant runtime state + 7-day opening hours.

    Fans out to two Grab endpoints in parallel via `asyncio.gather` so
    the dashboard's overview card sees ALL of:

      * `name`               — from `GET /food/merchant/v2/merchants`
      * `opening_hours[]`    — from `GET /food/merchant/v2/merchants`
      * `status_label`       — `"Open" | "BusyMode" | "Paused"`
      * `status_content`     — verbatim Grab human label (e.g.
                               "Quán đang bận", "Đang mở cửa")
      * `is_open`            — `True` for Open and BusyMode, `False`
                               for Paused (matches `trangthai2.py`'s
                               `status_label == "Open"` shortcut but
                               also keeps BUSY = still open).
      * `status_note`        — operator-friendly sentence the UI
                               renders under the pill.

    Mirrors TWO Python scripts:
      * `cuahang/trangthai.py`     → `v2/merchants` → name + hours
      * `cuahang/trangthai2.py`    → `v3/open-status` → state enum

    Failure isolation: each `gather` branch swallows its own exception
    and emits `None` so the merged response always returns a 200 with
    whichever fields succeeded. The frontend can render the schedule
    even when the runtime-status endpoint is flaky, and vice versa.

    Polling cadence is owned by the frontend (typically 30 s) since
    the overview card already polls `/status` at the same rate.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    authn_token = decrypt_token(store.encrypted_auth_token)

    # Fan out to v2/merchants (name + hours) and v3/open-status
    # (runtime state) concurrently so total latency = max of the two.
    async def _safe(coro):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 — branch-local swallow
            log.warning("opening-hours fanout branch failed: %r", exc)
            return None

    async with GrabClient(
        authn_token=authn_token, merchant_id=store.merchant_id
    ) as client:
        v2_raw, v3_raw = await asyncio.gather(
            _safe(get_merchant(client)),
            _safe(get_open_status_v3(client)),
        )

    # --- Project v2/merchants → name + opening_hours ----------------
    name: str | None = None
    opening_hours: list[OpeningHourDay] = []
    if isinstance(v2_raw, dict):
        merchant_block = (
            v2_raw.get("merchant")
            if "merchant" in v2_raw
            else (v2_raw.get("data") or {}).get("merchant")
            if isinstance(v2_raw.get("data"), dict)
            else None
        )
        if isinstance(merchant_block, dict):
            raw_name = merchant_block.get("name")
            if isinstance(raw_name, str):
                name = raw_name
            raw_hours = merchant_block.get("openingHours") or []
            if isinstance(raw_hours, list):
                for idx, day_info in enumerate(raw_hours[:7]):
                    if not isinstance(day_info, dict):
                        continue
                    ranges_raw = day_info.get("ranges") or []
                    ranges: list[OpeningHourRange] = []
                    if isinstance(ranges_raw, list):
                        for r in ranges_raw:
                            if not isinstance(r, dict):
                                continue
                            ranges.append(
                                OpeningHourRange(
                                    start=str(r.get("start", "") or ""),
                                    end=str(r.get("end", "") or ""),
                                )
                            )
                    opening_hours.append(
                        OpeningHourDay(day_index=idx, ranges=ranges)
                    )

    # --- Project v3/open-status → status_label + content + is_open --
    status_label: StoreRuntimeStatus | None = None
    status_content: str | None = None
    is_open_from_v3: bool | None = None
    if isinstance(v3_raw, dict):
        # Grab sometimes wraps under data.{...}; walk defensively.
        candidates = [v3_raw]
        inner = v3_raw.get("data")
        if isinstance(inner, dict):
            candidates.append(inner)
        status_display: dict | None = None
        for c in candidates:
            sd = c.get("statusDisplayInfo") if isinstance(c, dict) else None
            if isinstance(sd, dict):
                status_display = sd
                break
        if status_display is not None:
            raw_label = status_display.get("statusLabel")
            if raw_label in ("Open", "BusyMode", "Paused"):
                status_label = raw_label  # type: ignore[assignment]
            raw_content = status_display.get("statusContent")
            if isinstance(raw_content, str) and raw_content.strip():
                status_content = raw_content.strip()
        # Map runtime → accepting-orders semantics: only Paused is closed.
        if status_label == "Paused":
            is_open_from_v3 = False
        elif status_label in ("Open", "BusyMode"):
            is_open_from_v3 = True

    # --- Synthesize the operator note -------------------------------
    status_note = _build_status_note(status_label, status_content)

    # Final fallback: if v3 failed entirely, surface the v2 boolean so
    # the pill doesn't go blank.
    final_is_open: bool | None = is_open_from_v3
    if final_is_open is None and isinstance(v2_raw, dict):
        merchant_block = (
            v2_raw.get("merchant")
            if "merchant" in v2_raw
            else (v2_raw.get("data") or {}).get("merchant")
            if isinstance(v2_raw.get("data"), dict)
            else None
        )
        if isinstance(merchant_block, dict):
            raw_is_open = merchant_block.get("isOpen")
            if isinstance(raw_is_open, bool):
                final_is_open = raw_is_open
                # We don't know which label triggered it — leave as None.

    # If both branches failed, the response is "empty" but still 200
    # so the client can keep polling without a 5xx loop.
    overall_ok = v2_raw is not None or v3_raw is not None

    return OpeningHoursResponse(
        ok=overall_ok,
        data=OpeningHoursData(
            name=name,
            is_open=final_is_open,
            status_label=status_label,
            status_content=status_content,
            status_note=status_note,
            opening_hours=opening_hours,
        ),
        error=None if overall_ok else "Both v2/merchants and v3/open-status failed",
    )


def _build_status_note(
    label: StoreRuntimeStatus | None,
    content: str | None,
) -> str | None:
    """Build a short operator-friendly sentence the UI shows under the pill.

    The note supplements the verbatim `status_content` from Grab with a
    plain-Vietnamese summary so a merchant skimming the dashboard sees:

      * Open      → "Cửa hàng đang mở cửa" + verbatim Grab text
      * BusyMode  → "Quán đang bận" + verbatim Grab text (e.g. "Bận 15 phút")
      * Paused    → "Cửa hàng đang tạm nghỉ" + verbatim Grab text

    Returns `None` when we don't know the state yet.
    """
    if label is None:
        return None
    prefix = {
        "Open": "Cửa hàng đang mở cửa",
        "BusyMode": "Quán đang bận",
        "Paused": "Cửa hàng đang tạm nghỉ",
    }.get(label)
    if not prefix:
        return None
    if content:
        return f"{prefix} · {content}"
    return prefix


@router.get("/{merchant_id}/status")
async def get_store_status(
    merchant_id: str,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> dict:
    """Store account status from Grab's `store-list` endpoint.

    Returns the account-level status for this merchant_id:
    `ACTIVE`, `PENDING`, `SUSPENDED`, `INACTIVE`, etc. along with the
    human-readable `status_display`.

    Mirrors `trangchu/get_trangthai_hoatdong.py` which calls
    `GET /mex-app/troy/user-profile/v1/store-list`.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    authn_token = decrypt_token(store.encrypted_auth_token)

    try:
        async with GrabClient(authn_token=authn_token, merchant_id=store.merchant_id) as client:
            raw = await get_store_list(client)
    except Exception as exc:  # noqa: BLE001
        log.warning("store-list failed for %s: %s", merchant_id, exc)
        return {"ok": False, "error": str(exc), "status": None, "status_display": None}

    # Walk data.stores[] and find the entry whose gpid/gfid matches our merchant.
    stores_list = (
        (raw.get("data") or {}).get("stores")
        if isinstance(raw, dict)
        else []
    )
    entry: dict | None = None
    if isinstance(stores_list, list):
        for s in stores_list:
            if s.get("gpid") == merchant_id or s.get("gfid") == merchant_id:
                entry = s
                break

    return {
        "ok": True,
        "error": None,
        "status": entry.get("status") if entry else None,
        "status_display": entry.get("status_display") if entry else None,
        "pending": entry.get("pending") if entry else None,
        "raw": raw,
    }


@router.post(
    "/{merchant_id}/status",
    response_model=UpdateStoreStatusResponse,
)
async def update_store_status(
    merchant_id: str,
    body: UpdateStoreStatusRequest,
    user=Depends(require_user),
    session: Session = Depends(get_session),
) -> UpdateStoreStatusResponse:
    """Update the store's runtime state — mirrors cuahang/setting_*.py.

    Two operations are supported via the `kind` discriminator:

    * ``kind="temp_pause"`` — toggle ``TEMPPAUSED`` (Nghỉ 1h / 2h /
      hôm nay / 30 ngày) and "Mở lại" via ``unpause=True``.
      Requires ``pause_end_utc`` (UTC ISO-8601) when not unpausing.
    * ``kind="busy"`` — toggle ``BUSY`` (Bận 15 / 30 / 60 phút) and
      "Mở lại" via ``unpause=True``. Requires ``minutes`` to be one of
      15, 30, 60 when not unpausing.

    The endpoint writes an `audit_log` row per call so the operator has
    a tamper-evident record of every status change.
    """
    store: Store | None = (
        session.query(Store)
        .filter(Store.merchant_id == merchant_id, Store.owner_user_id == user.id)
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    # Discriminator-fold: validate per-kind required fields here so the
    # helper gets a clean call. Pydantic enforces the enums (kind +
    # minutes); we just need to ensure the field combinations are sane.
    if body.kind == "temp_pause":
        if not body.unpause and body.pause_end_utc is None:
            raise HTTPException(
                status_code=422,
                detail="pause_end_utc là bắt buộc khi kind=temp_pause và unpause=false",
            )
    elif body.kind == "busy":
        if not body.unpause and body.minutes is None:
            raise HTTPException(
                status_code=422,
                detail="minutes (15|30|60) là bắt buộc khi kind=busy và unpause=false",
            )

    authn_token = decrypt_token(store.encrypted_auth_token)

    try:
        async with GrabClient(authn_token=authn_token, merchant_id=store.merchant_id) as client:
            if body.kind == "temp_pause":
                raw = await set_store_temp_paused(
                    client,
                    pause_end_utc=body.pause_end_utc,
                    is_unpause=body.unpause,
                    current_runtime=body.current_runtime,
                )
            else:  # body.kind == "busy"
                raw = await set_store_busy(
                    client,
                    busy_minutes=body.minutes,
                    is_unpause=body.unpause,
                    current_runtime=body.current_runtime,
                )
    except httpx.HTTPStatusError as exc:
        log.warning(
            "store status update failed for %s kind=%s unpause=%s: %s — %s",
            merchant_id, body.kind, body.unpause,
            exc.response.status_code, (exc.response.text or "")[:300],
        )
        # Whether Grab gates store pause/busy behind the passcode the way
        # it now gates every menu write is unmeasured — toggling a live
        # store to find out is not a probe worth running. Recognising it
        # costs nothing and beats the alternative, which was a raw Python
        # exception repr shown to the operator in place of a reason.
        if is_passcode_error(exc.response.status_code, exc.response.text):
            raise HTTPException(
                status_code=403,
                detail={"code": PASSCODE_CODE, "message": PASSCODE_MESSAGE},
            ) from exc
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_rejected_store_status",
                "grab_status": exc.response.status_code,
                "message": "Grab từ chối đổi trạng thái cửa hàng. Thử lại sau ít phút.",
                "grab_body": (exc.response.text or "")[:500],
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface raw Grab failure
        log.warning(
            "store status update failed for %s kind=%s unpause=%s: %s",
            merchant_id,
            body.kind,
            body.unpause,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_unreachable",
                "message": "Không kết nối được tới Grab. Thử lại sau ít phút.",
            },
        ) from exc

    # Audit log — tamper-evident record of every state change.
    from app.deps import write_audit_log

    write_audit_log(
        session=session,
        user_id=user.id,
        action=(
            "store.status.temp_pause.unpause"
            if body.kind == "temp_pause" and body.unpause
            else "store.status.busy.unpause"
            if body.kind == "busy" and body.unpause
            else "store.status.temp_pause"
            if body.kind == "temp_pause"
            else "store.status.busy"
        ),
        entity_type="store",
        entity_id=merchant_id,
        payload={
            "kind": body.kind,
            "unpause": body.unpause,
            "minutes": body.minutes,
            "pause_end_utc": body.pause_end_utc.isoformat()
            if body.pause_end_utc is not None
            else None,
            # Recorded for forensics so we can later confirm the actual
            # `fromState` we sent matched what Grab had on its side at
            # the time of the call.
            "current_runtime": body.current_runtime,
        },
    )

    return UpdateStoreStatusResponse(
        merchant_id=merchant_id,
        kind=body.kind,
        unpause=body.unpause,
        raw=raw if isinstance(raw, dict) else {},
    )
