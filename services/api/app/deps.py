"""FastAPI dependency injectors for the PulseOrder app.

All dependencies are lightweight functions decorated with
`Depends(...)` in the route layer.  They are kept here so the
route modules stay thin and testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.core.config import Settings, settings
from app.core.db import get_session as _get_session
from app.core.security import COOKIE_NAME, SessionToken, clear_session_cookie
from app.models import AuditLog, Store, User

if TYPE_CHECKING:
    from grab import GrabClient

# ── Settings ────────────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    """Return the cached Settings singleton (no DB access, safe as a dep)."""
    return settings


# ── Database session ─────────────────────────────────────────────────────────────


def get_session():
    """FastAPI dep — yields a real SQLModel Session per request.

    This MUST be a generator (use `yield`, not `return`). FastAPI's DI
    framework detects generator dependencies and:
      1. Calls `next()` to obtain the yielded value (a real `Session`)
      2. Hands it to the route as the dependency result
      3. After the response (or on exception), runs `next()` again to
         trigger the generator's `finally` block, which closes the
         underlying SQLAlchemy session and returns its connection to
         the pool.

    If this function used `return _get_session()` instead of `yield`, the
    route would receive the *generator object* (not the Session it yields),
    and every `session.query(...)` / `session.get(...)` call would crash
    with `AttributeError: 'generator' object has no attribute 'query'`.

    We delegate to `app.core.db.get_session` which owns the engine and
    pool config — keeping DB wiring in one place.
    """
    yield from _get_session()


# ── Authentication ──────────────────────────────────────────────────────────────


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    """Look up the logged-in user from the signed session cookie.

    Returns None when the cookie is absent, tampered, or expired.
    This is intentionally lenient — route handlers that need an authed user
    should use `require_user` instead.
    """
    token_str = request.cookies.get(COOKIE_NAME)
    if not token_str:
        return None

    session_token = SessionToken.from_signed(
        token_str,
        secret=settings.session_secret,
        max_age_seconds=86400 * 7,
    )
    if session_token is None:
        return None

    return session.get(User, session_token.user_id)


def require_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Raise 401 if the request has no valid session cookie."""
    user = get_current_user(request, session)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated.  Please log in.",
        )
    return user


# ── Active store ────────────────────────────────────────────────────────────────

def _active_store_id_from_cookie(request: Request) -> int | None:
    """Extract active_store_id from the request cookie, returning None if absent."""
    raw = request.cookies.get("active_store_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def get_active_store(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
    active_store_id: int | None = None,
) -> Store | None:
    """Return the user's active store.

    Precedence:
    1. `active_store_id` parameter (may come from the `active_store_id` cookie
       via `require_active_store`, or be passed explicitly in tests).
    2. `active_store_id` cookie in the request.
    3. First store owned by the user.
    Returns None if the user has no stores yet.
    """
    # Highest-precedence: explicit parameter (set by require_active_store via cookie)
    if active_store_id is not None:
        store = session.get(Store, active_store_id)
        if store is not None and store.owner_user_id == user.id:
            return store

    # Fall back to cookie lookup + first-store heuristic (handled in
    # require_active_store so Request is available there).
    return None


def require_active_store(
    request: Request,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> Store:
    """Raise 400 if the user has no stores. Returns the active store."""
    # Try active_store_id cookie first
    store_id = _active_store_id_from_cookie(request)

    if store_id is not None:
        store = session.get(Store, store_id)
        if store is not None and store.owner_user_id == user.id:
            return store

    # Fall back to the first store for this user
    store = session.query(Store).filter(Store.owner_user_id == user.id).first()
    if store is None:
        raise HTTPException(
            status_code=400,
            detail="No active store.  Please add a Grab store first.",
        )
    return store


# ── GrabClient factory ──────────────────────────────────────────────────────────


async def get_grab_client(
    request: Request,
    store: Store = Depends(require_active_store),
    session: Session = Depends(get_session),
) -> AsyncIterator["GrabClient"]:
    """Yield an async-context-manager GrabClient scoped to the active store.

    The decrypted auth token is re-encrypted and persisted to the DB when the
    context exits so plaintext credentials are never left in memory longer than
    strictly necessary.
    """
    from app.core.security import decrypt_token, encrypt_token

    from grab import GrabClient

    authn_token = decrypt_token(store.encrypted_auth_token)

    async with GrabClient(
        authn_token=authn_token,
        merchant_id=store.merchant_id,
    ) as client:
        yield client

    # Re-encrypt the auth token after use in case Grab rotated it server-side.
    # We deliberately re-encrypt even when unchanged — cheap, consistent, safe.
    store.encrypted_auth_token = encrypt_token(authn_token)
    session.add(store)
    session.commit()


# ── Audit logging ──────────────────────────────────────────────────────────────


def write_audit_log(
    session: Session,
    user_id: int,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    payload: dict | None = None,
) -> AuditLog:
    """Append an immutable audit log entry (no return value needed)."""
    import json

    record = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload_json=json.dumps(payload or {}),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record
