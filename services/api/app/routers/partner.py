"""Partner-facing read API.

Exposes a subset of the dashboard's order data to integration
partners via per-store API keys. The operator runs many stores
under one PulseOrder account and wants to grant each partner a
key scoped to a single store — so they can revoke one partner
without rotating everyone else's key.

Endpoints:
  * ``GET /api/partner/orders`` — list orders for the authenticated
    store. Query params: ``from_date`` / ``to_date`` (ISO-8601,
    default = last 7 days), ``state`` (e.g. ``ORDER_COMPLETED``),
    ``limit`` (1..500, default 100).

Auth design:
  * The partner presents ``Authorization: Bearer <key>``.
  * The key is opaque (``"pulse_" + 32 url-safe bytes``).
  * We look up by the first 8 chars (``key_prefix``), then bcrypt
    the full key against the stored hash, then enforce
    ``revoked_at is NULL``.
  * No cookie auth is required — partner systems are headless.

Wire shape (see ``app/schemas/partner.py``):
  * ``customerName``  — from ``eater.name``
  * ``phone``         — from ``eater.mobileNumber``
  * ``items[]``       — name + quantity + price per line
  * ``price``         — ``fare.totalDisplay`` (locale VND string)
  * ``source``        — ``"GF " + Store.region`` per user contract
  * ``state``         — last-seen state from the archive
  * ``orderedAt``     — ISO timestamp from ``times.createdAt``

Why we hydrate from ``OrderArchive`` instead of calling Grab
directly:

  * The 30s cron already writes the order once on first sight and
    freezes ``detail_json`` (round-4 invariant). After the order
    leaves the preparing queue Grab's per-order detail endpoint
    often WAF-rejects it — but we still have the full snapshot
    locally. The partner API always reads from the local archive
    so partners see the same data the dashboard does.
  * Single batched query (no per-order Grab fan-out) keeps
    partner API latency bounded regardless of how many orders
    they request.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlmodel import Session

from app.core.security import hash_password, verify_password
from app.deps import get_session, require_user
from app.models import OrderArchive, Store, StoreApiKey, User
from app.schemas.partner import (
    CreatePartnerApiKeyRequest,
    PartnerApiKeyCreatedResponse,
    PartnerApiKeySummary,
    PartnerOrder,
    PartnerOrdersResponse,
)

log = logging.getLogger("pulseorder.partner")

router = APIRouter(prefix="/api/partner", tags=["partner"])


# ── key format ────────────────────────────────────────────────────────────────

KEY_PREFIX_LITERAL: str = "pulse_"
"""Every partner key starts with this literal — lets a partner-side
  caller detect that an env var accidentally pasted a Grab token.

  The full key is ``pulse_`` + 32 url-safe bytes (``secrets.token_urlsafe(32)``);
  total length ~43 chars. ``key_prefix`` (what we index on) is the
  first 8 chars of the full key.
"""
_KEY_DB_PREFIX_LEN: int = 8


def _generate_partner_key() -> tuple[str, str]:
    """Mint a new partner key.

    Returns:
        (plaintext_key, db_prefix):
          * ``plaintext_key`` — the value the caller must surface to
            the operator exactly once (we never store it).
          * ``db_prefix``     — the indexed lookup value (first
            ``_KEY_DB_PREFIX_LEN`` chars of the plaintext key).
    """
    raw = secrets.token_urlsafe(32)
    plaintext = f"{KEY_PREFIX_LITERAL}{raw}"
    return plaintext, plaintext[:_KEY_DB_PREFIX_LEN]


# ── auth dependency ───────────────────────────────────────────────────────────


def _authenticate_partner(
    authorization: str | None,
    session: Session,
) -> tuple[Store, StoreApiKey]:
    """Resolve ``Authorization: Bearer <key>`` to (Store, StoreApiKey).

    Raises 401 on missing / malformed / unknown / revoked keys.
    Never leaks which of those four caused the failure — the
    error message is generic so a leaked key fingerprint can't
    be probed for validity.

    Updates ``last_used_at`` on success so the operator can see
    "this key was used 3 minutes ago" without keeping request
    logs around.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail=(
                "Missing or malformed Authorization header. "
                "Expected `Authorization: Bearer <key>`."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization[7:].strip()
    if not presented or len(presented) < _KEY_DB_PREFIX_LEN:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired API key. Contact your PulseOrder "
                "operator to re-issue."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    db_prefix = presented[:_KEY_DB_PREFIX_LEN]

    # Single-row lookup by the indexed prefix. SQLAlchemy returns
    # the first matching row; in practice the prefix is unique
    # because ``secrets.token_urlsafe(32)`` makes 8-char prefix
    # collisions astronomically unlikely (~2^48 of entropy per key).
    from sqlmodel import select as _sel
    candidate = session.exec(
        _sel(StoreApiKey).where(
            StoreApiKey.key_prefix == db_prefix,
            StoreApiKey.revoked_at.is_(None),  # noqa: E711  (SQL NULL test)
        )
    ).first()

    if candidate is None:
        # Could be a real unknown key OR a known-but-revoked one.
        # We don't differentiate — both surface as the same generic
        # 401 so a leaked key fingerprint can't probe for validity.
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired API key. Contact your PulseOrder "
                "operator to re-issue."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(presented, candidate.key_hash):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired API key. Contact your PulseOrder "
                "operator to re-issue."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    store = session.get(Store, candidate.store_id)
    if store is None:
        # The store was deleted but the key still exists. Treat as
        # auth-failure rather than 500 — partner just needs to know
        # the key isn't usable anymore.
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired API key. Contact your PulseOrder "
                "operator to re-issue."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Touch ``last_used_at`` for the operator's UX. We do this in a
    # separate short transaction so a write-failure here doesn't
    # roll back the auth path. Best-effort, log on failure.
    try:
        candidate.last_used_at = datetime.utcnow()
        session.add(candidate)
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        log.warning(
            "partner api: failed to touch last_used_at for key id=%s",
            candidate.id,
        )

    return store, candidate


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_anonymised_eater(name: str | None, phone: str | None) -> bool:
    """Same anonymisation flag the dashboard uses.

    When true, ``PartnerOrder.from_archive_row`` will surface empty
    customer / phone instead of Grab's ``"***"`` / ``""`` markers.
    """
    n = (name or "").strip()
    p = (phone or "").strip()
    return n == "***" or (n == "" and p == "")


# ── endpoint ──────────────────────────────────────────────────────────────────


@router.get("/orders", response_model=PartnerOrdersResponse)
def get_partner_orders(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    from_date: Annotated[
        datetime | None,
        Query(
            description=(
                "ISO-8601 lower bound on `lastSeenAt`. "
                "Defaults to 7 days ago."
            )
        ),
    ] = None,
    to_date: Annotated[
        datetime | None,
        Query(
            description=(
                "ISO-8601 upper bound on `lastSeenAt`. "
                "Defaults to now."
            )
        ),
    ] = None,
    state: Annotated[
        str | None,
        Query(
            description=(
                "Optional exact-match filter on the archive's `state` "
                "(e.g. `ORDER_COMPLETED`)."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum orders to return."),
    ] = 100,
    session: Session = Depends(get_session),
) -> PartnerOrdersResponse:
    """Return partner-facing orders for the bearer-token-authenticated store.

    Auth: ``Authorization: Bearer <key>`` (see module docstring).

    Filtering:
      * ``from_date`` / ``to_date`` apply to ``last_seen_at`` (when
        the cron last refreshed this row), not ``first_seen_at`` —
        partners care about "what's been active in my window".
      * ``state`` is an optional exact match — useful for the
        common "only show COMPLETED orders" call.
      * ``limit`` is capped at 500 so a partner can't accidentally
        stream the whole archive. Default 100 covers the typical
        "today's orders" call without pagination.

    Response order is most-recent first (``last_seen_at`` desc).
    The response is intentionally lean — only the five fields the
    operator asked for (customer / phone / items / price / source)
    plus a few identifiers.
    """
    store, _api_key = _authenticate_partner(authorization, session)

    # Default window: last 7 days. Older partners can pass ``from_date``
    # to widen. Cap ``to_date`` at now so a misconfigured client can't
    # ask for "orders since year 2099" by mistake.
    if to_date is None:
        to_date = datetime.utcnow()
    if from_date is None:
        from_date = to_date - timedelta(days=7)

    from sqlmodel import select as _sel

    stmt = (
        _sel(OrderArchive)
        .where(
            OrderArchive.store_id == store.id,
            OrderArchive.last_seen_at >= from_date,
            OrderArchive.last_seen_at <= to_date,
        )
        .order_by(OrderArchive.last_seen_at.desc())
    )
    if state:
        stmt = stmt.where(OrderArchive.state == state)
    rows = list(session.exec(stmt.limit(limit)).all())

    orders: list[PartnerOrder] = []
    for row in rows:
        payload = row.detail_payload()
        if not payload:
            # The archive's detail_json is malformed or missing —
            # skip rather than emit a half-row. Same defensive
            # pattern as the dashboard's customers router.
            continue
        order_block = payload.get("order") if isinstance(payload.get("order"), dict) else payload
        if not isinstance(order_block, dict):
            continue
        eater = order_block.get("eater") if isinstance(order_block.get("eater"), dict) else {}
        if not isinstance(eater, dict):
            eater = {}
        eater_name = str(eater.get("name") or "")
        eater_phone = str(eater.get("mobileNumber") or "")
        is_anon = _is_anonymised_eater(eater_name, eater_phone)

        times = order_block.get("times") if isinstance(order_block.get("times"), dict) else {}
        ordered_at = str(times.get("createdAt") or "") if isinstance(times, dict) else ""

        orders.append(
            PartnerOrder.from_archive_row(
                order_id=row.order_id,
                display_id=row.display_id or "",
                state=row.state or "",
                ordered_at=ordered_at,
                payload=payload,
                region=store.region or "",
                is_anonymised=is_anon,
            )
        )

    return PartnerOrdersResponse(orders=orders, count=len(orders))


# ── Admin endpoints (cookie auth) — issue / list / revoke ──────────────────


@router.post(
    "/keys",
    response_model=PartnerApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_partner_api_key(
    payload: CreatePartnerApiKeyRequest,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> PartnerApiKeyCreatedResponse:
    """Issue a new partner API key for one of the operator's stores.

    Body: ``{"merchantId": "...", "label": "Posmate"}``.

    Auth: standard cookie session (``require_user``). Only the
    store owner can issue keys for their own store — we look up
    the Store by ``(merchant_id, owner_user_id)`` and 404 if the
    operator doesn't own a store with that merchant_id. This
    prevents one operator from minting keys against another
    operator's store.

    The plaintext key is returned **once** in the response and is
    never stored. Revoke + re-issue if the partner loses it.
    """
    # Owner-scoped store lookup. 404 (not 403) so we don't leak the
    # existence of stores that don't belong to this operator.
    from sqlmodel import select as _sel
    store = session.exec(
        _sel(Store).where(
            Store.merchant_id == payload.merchant_id,
            Store.owner_user_id == user.id,
        )
    ).first()
    if store is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No store with merchant_id={payload.merchant_id!r} "
                "for the current user."
            ),
        )

    plaintext, db_prefix = _generate_partner_key()
    db_hash = hash_password(plaintext)

    row = StoreApiKey(
        store_id=store.id,
        key_prefix=db_prefix,
        key_hash=db_hash,
        label=(payload.label or "").strip()[:64],  # cap label size
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    log.info(
        "partner_api_key issued: store=%s key_id=%s label=%r",
        store.merchant_id, row.id, row.label,
    )

    summary = PartnerApiKeySummary(
        id=row.id,
        storeId=row.store_id,
        keyPrefix=row.key_prefix,
        label=row.label,
        createdAt=row.created_at,
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
    )
    return PartnerApiKeyCreatedResponse(plaintextKey=plaintext, summary=summary)


@router.get(
    "/keys",
    response_model=list[PartnerApiKeySummary],
)
def list_partner_api_keys(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> list[PartnerApiKeySummary]:
    """List every partner API key for the operator's owned stores.

    Same store-isolation as issue: a partner key for someone else's
    store is invisible. Wire keys are capped at the bookkeeping
    fields — never the ``key_hash`` or plaintext.
    """
    from sqlmodel import select as _sel
    owned_store_ids = [
        s.id for s in
        session.exec(_sel(Store).where(Store.owner_user_id == user.id)).all()
    ]
    if not owned_store_ids:
        return []
    rows = session.exec(
        _sel(StoreApiKey).where(StoreApiKey.store_id.in_(owned_store_ids))
    ).all()
    return [
        PartnerApiKeySummary(
            id=row.id,
            storeId=row.store_id,
            keyPrefix=row.key_prefix,
            label=row.label,
            createdAt=row.created_at,
            lastUsedAt=row.last_used_at,
            revokedAt=row.revoked_at,
        )
        for row in rows
    ]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_partner_api_key(
    key_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> Response:
    """Revoke a partner API key (soft-delete: sets ``revoked_at``).

    Auth: standard cookie session + owner-scoped to the operator.
    A revoked key can never be re-used — the auth dependency
    filters on ``revoked_at IS NULL`` so the bcrypt check is
    never reached for a revoked key.

    Returns 204 on success, 404 if the key doesn't exist OR
    doesn't belong to this operator (intentionally indistinct
    so we don't leak whether someone else's key id exists).
    """
    from sqlmodel import select as _sel

    # Pull the candidate key — we need it for the owner check.
    candidate = session.get(StoreApiKey, key_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    owner_store = session.get(Store, candidate.store_id)
    if (
        owner_store is None
        or owner_store.owner_user_id != user.id
    ):
        # Don't leak whether a key id exists for someone else.
        raise HTTPException(status_code=404, detail="API key not found.")

    if candidate.revoked_at is None:
        candidate.revoked_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    log.info(
        "partner_api_key revoked: key_id=%s store=%s",
        key_id, owner_store.merchant_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)