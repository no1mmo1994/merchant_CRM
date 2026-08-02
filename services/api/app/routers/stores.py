"""Store router — list stores, get store detail, select active store."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.core.security import decrypt_token
from app.deps import get_session, require_user
from app.models import Store
from app.schemas import SelectStoreRequest, StoreListResponse, StoreOut
from grab import GrabClient
from grab.endpoints.profile import get_store_list, get_unified_profile
from grab.endpoints.store import get_business_attributes, get_scorecard

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
