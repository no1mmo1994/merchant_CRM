"""Authentication router — login, logout, me, refresh-token."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import (
    _extract_cookie_domain,
    clear_session_cookie,
    create_session_cookie,
    encrypt_token,
)
from app.deps import get_session, require_user
from app.models import Store, User
from app.schemas import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RefreshTokenRequest,
    StoreOut,
    UserOut,
)
from grab import ChallengeError, LoginError, StaticXRayProvider

router = APIRouter(prefix="/api/auth", tags=["auth"])

log = logging.getLogger("pulseorder.auth")


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    """Authenticate against Grab and create (or find) the associated PulseOrder user + store.

    Rate-limited to settings.rate_limit_per_minute requests per IP.

    Flow (mirrors `Login/login1-done.py`):
      1. Run Grab's 3-step login (email + password) using the x-ray
         token the user pasted into the form. Same token is used for
         step-1 and step-3.
      2. Fetch the merchant's user profile via Grab's
         `GET /mex-app/troy/user-profile/v2/details` — `login_three_step`
         does this as Step 4 of the flow. From that payload we extract
         `user_profile.merchant_grab_id` (canonical store id) and
         `user_profile_details.first_name` (store display name). The
         user no longer has to type either into the form.
      3. Encrypt tokens, upsert the User row, upsert the Store row keyed
         by (merchant_grab_id, owner_user_id).
      4. Set session + active-store cookies.
    """
    from grab import login_three_step

    # The user pastes a fresh x-ray token each time they sign in. The token
    # is HMAC-tagged against a device clock and goes stale in a few hours,
    # so we never reuse a stored one. Same value drives step-1 and step-3
    # (matches `Login/login1-done.py:get_xray_token`).
    xray_provider = StaticXRayProvider(
        step1_token=body.xray_token,
        step3_token=body.xray_token,
    )

    # ── Run the 3-step Grab login ───────────────────────────────────────────────
    try:
        result = await login_three_step(
            email=body.email,
            password=body.password,
            xray=xray_provider,
            verify_ssl=settings.grab_verify_ssl,
        )
    except LoginError as exc:
        # We still forward the step-1 token so the error translator can
        # diagnose clock-drift (x-ray JWT `iat` age) — diagnostic only.
        raise _login_error_to_http(
            exc,
            source="login",
            xray_token=xray_provider.step1_token,
        )

    authn_token: str = result.authn_token
    display_token: str = result.display_token
    profile: dict = result.profile or {}

    # ── Extract merchant_id + store name from the profile ──────────────────────
    # The v2/details response shape (see `Login/login1-done.py` output):
    #   {
    #     "user_profile": {
    #       "merchant_grab_id": "<canonical merchant id>",
    #       "user_profile_details": {"first_name": "<store name>"},
    #       "first_name": "<duplicate of user_profile_details.first_name>",
    #       ...
    #     }
    #   }
    user_profile = profile.get("user_profile") if isinstance(profile, dict) else None
    if not isinstance(user_profile, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Grab returned an unexpected user-profile shape — could "
                "not discover merchant_id. Please retry shortly."
            ),
        )
    merchant_id = user_profile.get("merchant_grab_id")
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Grab user-profile is missing `merchant_grab_id`. The "
                "account may not have an active store linked."
            ),
        )
    details = user_profile.get("user_profile_details") or {}
    store_name: str = (
        user_profile.get("first_name")
        or details.get("first_name")
        or "(unnamed store)"
    )

    # ── Encrypt Grab tokens before storing ──────────────────────────────────────
    enc_authn = encrypt_token(authn_token)
    enc_display = encrypt_token(display_token)
    enc_xray = encrypt_token(xray_provider.step1_token)

    # ── Find or create the user ─────────────────────────────────────────────────
    user: User = session.query(User).filter(User.username == body.email).first()
    if user is None:
        user = User(
            username=body.email,
            password_hash="",  # no local password in Phase 03
        )
        session.add(user)
        session.flush()  # get the ID

    # ── Find or create the store ────────────────────────────────────────────────
    store: Store = (
        session.query(Store)
        .filter(
            Store.merchant_id == merchant_id,
            Store.owner_user_id == user.id,
        )
        .first()
    )
    if store is None:
        store = Store(
            merchant_id=merchant_id,
            name=store_name,
            address="",  # merchant address lookup deferred to Phase 06
            encrypted_auth_token=enc_authn,
            encrypted_display_token=enc_display,
            encrypted_xray_token=enc_xray,
            owner_user_id=user.id,
            last_refresh_at=datetime.utcnow(),
        )
        session.add(store)
    else:
        store.encrypted_auth_token = enc_authn
        store.encrypted_display_token = enc_display
        store.encrypted_xray_token = enc_xray
        store.last_refresh_at = datetime.utcnow()
        # Keep the user-visible name fresh — Grab admins can rename a store.
        store.name = store_name
    session.commit()
    session.refresh(store)

    # ── Set session + active-store cookies ─────────────────────────────────────
    create_session_cookie(response, user.id, request)
    response.set_cookie(
        key="active_store_id",
        value=str(store.id),
        httponly=True,
        samesite="lax",
        secure=settings.require_https,
        path="/",
        domain=_extract_cookie_domain(request),
    )

    return LoginResponse(
        user=UserOut.model_validate(user),
        store=StoreOut.model_validate(store),
        message="ok",
    )


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    """Clear session and active-store cookies."""
    clear_session_cookie(response, request)
    response.delete_cookie(
        key="active_store_id",
        path="/",
        domain=_extract_cookie_domain(request),
    )
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> MeResponse:
    """Return the current user and all their stores."""
    stores = session.query(Store).filter(Store.owner_user_id == user.id).all()
    return MeResponse(
        user=UserOut.model_validate(user),
        stores=[StoreOut.model_validate(s) for s in stores],
    )


@router.post("/refresh-token")
async def refresh_token(
    body: RefreshTokenRequest,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Re-run Grab login to refresh an expired auth token for the given merchant.

    Historically this re-ran `login_three_step` with the stored x-ray and
    an empty password. Grab's PWD_V2 challenge now requires a real
    password on every challenge — there's no way to refresh server-side
    without re-prompting the user. We surface that as a structured 410
    so the frontend can show "please sign in again".
    """
    store: Store | None = (
        session.query(Store)
        .filter(
            Store.merchant_id == body.merchant_id,
            Store.owner_user_id == user.id,
        )
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "reauth_required",
            "message": (
                "Grab tokens can't be refreshed server-side — sign in "
                "again with your email and password to get a fresh session."
            ),
            "hint": "Use the login form to start a new session.",
            "fields": ["email", "password"],
            "source": "refresh-token",
        },
    )


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------
# Mapping of the structured `LoginError` (raised by the `grab` library)
# into an `HTTPException` the frontend can branch on. Each branch returns:
#   - HTTP status: 401 for auth errors, 429 for rate-limit, 422 for
#     invalid input, 502 for upstream failure, 503 for transient.
#   - `detail.code`: stable machine identifier the frontend matches on.
#   - `detail.message`: human-friendly, actionable text — already
#     localised to English (we only support English right now).
#   - `detail.hint`: optional next-step guidance.
#   - `detail.fields`: which fields to focus (`["xray_token"]`) so the
#     LoginForm can call `form.setFocus("xray_token")`.

_CHALLENGE_FIELDS_BY_STEP = {1: ["email"], 2: ["password"], 3: []}


def _xray_jwt_age_hours(token: str | None) -> float | None:
    """Decode an x-ray JWT payload and return how old it is, in hours.

    Returns `None` for any non-JWT input (e.g. the legacy outer-wrapper
    format), malformed JWTs, missing `iat`, or `iat` from the future.
    Used only for diagnostic messages — never for authentication.

    SECURITY: signature is NOT verified. A malicious client could craft
    a JWT with any `iat` they like; we trust the value only for a
    human-readable hint. Grab's SDK signed this token and Grab's server
    is the source of truth for validity.
    """
    import base64
    import binascii
    import json
    import time as _time

    if not token or token.count(".") < 2:
        return None
    try:
        parts = token.split(".")
        payload_b64 = parts[1]
        # JWTs use URL-safe base64 without padding.
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError, IndexError, TypeError):
        # Malformed JWT — common with the legacy outer-wrapper format or
        # with truncated tokens. Fall through to the generic clock-drift
        # message in the caller. We intentionally do NOT catch broader
        # exceptions (e.g. AttributeError) — those are real bugs and
        # should fail loud as 500s.
        return None
    # Guard against non-object payloads (lists, strings, nulls).
    if not isinstance(payload, dict):
        return None
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)) or iat <= 0:
        return None
    age_s = _time.time() - float(iat)
    # Negative age = iat in the future (device clock ahead of Grab's).
    # Caller branches on `age_h < 0` to distinguish future vs stale.
    return round(age_s / 3600, 1)


def _login_error_to_http(
    exc: LoginError,
    *,
    source: str,
    xray_token: str | None = None,
) -> HTTPException:
    """Translate a `grab.auth.LoginError` into an HTTPException.

    The frontend (apps/web/lib/api/auth.ts) checks `error.body.detail.code`
    to decide which toast / retry hint to show.

    Classification order matters when multiple signals are present (e.g.
    HTTP 429 with a `clock_drift` reason shows up as both rate-limited and
    clock-drifted). We pick the most actionable one for the user.
    """
    # ── 1. Clock drift — check FIRST because Grab also returns 429 ─────────────
    if exc.is_clock_drift:
        age_h = _xray_jwt_age_hours(xray_token)
        if age_h is not None and age_h < 0:
            msg = (
                "Grab's HMAC tag inside this x-ray token was computed against a "
                f"device clock {abs(age_h):.1f}h in the future relative to "
                "Grab's server. Recapture the token after setting the device "
                "clock correctly."
            )
        elif age_h is not None:
            msg = (
                f"Your x-ray token is {age_h:.1f}h old. Grab validates the "
                "device clock embedded in this token — a stale device clock "
                "always fails. A fresh capture is required."
            )
        else:
            msg = (
                "Grab rejected the x-ray token because the device clock "
                "embedded in its HMAC differs from Grab's server time. The "
                "token must be recaptured from a device whose clock matches "
                "NTP (date, time, and time-zone all set automatically)."
            )
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "grab_clock_drift",
                "message": msg,
                "hint": (
                    "Your stored x-ray token has drifted. Re-authenticate "
                    "with a fresh token via the login form."
                    if source == "refresh-token"
                    else (
                        "Re-capture the x-ray token from your browser "
                        "DevTools Network panel: filter for `authnv4`, "
                        "click the POST to `login`, and copy the `x-ray` "
                        "header value."
                    )
                ),
                "fields": ["xray_token"],
                "source": source,
                "request_id": exc.request_id,
                "xray_age_hours": age_h,
            },
        )

    # ── 2. Rate-limited ────────────────────────────────────────────────────────
    if exc.is_rate_limited:
        # Surface `xray_age_hours` so the LoginForm can warn the user that
        # the bundled x-ray is stale and recommend re-capture. The x-ray
        # is bound to a per-device HMAC tag and the per-token throttle
        # resets only on a fresh capture — a 5-minute wait on a stale
        # token will just hit 429 again.
        age_h = _xray_jwt_age_hours(xray_token)
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "grab_rate_limited",
                "message": (
                    "Too many login attempts. Grab is throttling this "
                    "network — please wait a few minutes and try again."
                ),
                "hint": (
                    "Wait ~5 minutes, then re-submit. If the bundled x-ray "
                    "is stale, re-capture it from your browser DevTools "
                    "Network panel (filter for `authnv4`)."
                ),
                "fields": (
                    ["xray_token"] if age_h is not None and age_h > 4 else []
                ),
                "source": source,
                "request_id": exc.request_id,
                # Echo the raw reason so the integration test (and any
                # future server-side triage) can confirm which Grab
                # classifier fired — without it, the 429 branch is
                # indistinguishable from the generic 502.
                "grab_reason": exc.grab_reason,
                # ~5 minute cooldown window — see grab/auth.py docstring.
                "retry_after_seconds": 300,
                "xray_age_hours": age_h,
            },
        )

    # ── 3. X-ray / device challenge ───────────────────────────────────────────
    if exc.is_xray_rejected:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "grab_xray_rejected",
                "message": (
                    "Grab rejected the x-ray token "
                    f"(reason: {exc.grab_reason or 'unknown'})."
                ),
                "hint": (
                    "Re-capture the x-ray token from your browser DevTools "
                    "Network panel."
                ),
                "fields": ["xray_token"],
                "source": source,
                "request_id": exc.request_id,
            },
        )

    # ── 4. Step 1 missing challengeSessionID → invalid email ──────────────────
    if isinstance(exc, ChallengeError) or (
        exc.http_status == 400 and exc.step == 1
    ):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_email",
                "message": (
                    "Grab didn't recognise this email — check the spelling "
                    "and make sure the account exists."
                ),
                "hint": "Double-check the email; accounts are case-sensitive.",
                "fields": ["email"],
                "source": source,
                "request_id": exc.request_id,
            },
        )

    # ── 5. Step 2 → wrong password ────────────────────────────────────────────
    # Status code: Grab returns 401/403 for bad passwords. Some clients
    # have observed 400 with a reason string — we honour the reason as a
    # secondary signal so those don't fall through to the generic message.
    _PASSWORD_REASON_TOKENS = ("password", "credential", "auth", "login")
    is_password_failure = exc.step == 2 and (
        exc.http_status in (401, 403)
        or (
            exc.grab_reason
            and any(tok in exc.grab_reason.lower() for tok in _PASSWORD_REASON_TOKENS)
        )
    )
    if is_password_failure:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "wrong_password",
                "message": "The Grab password didn't match. Try again.",
                "hint": "Caps Lock off? Try logging into the Grab app to confirm.",
                "fields": ["password"],
                "source": source,
                "request_id": exc.request_id,
            },
        )

    # ── 6. Server errors → surface as 502 ─────────────────────────────────────
    if exc.http_status and exc.http_status >= 500:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "grab_upstream_error",
                "message": (
                    "Grab returned an upstream error. This is almost "
                    "always transient — retry shortly."
                ),
                "hint": "If it persists for an hour, contact support.",
                "fields": [],
                "source": source,
                "request_id": exc.request_id,
            },
        )

    # ── 7. Anything else ──────────────────────────────────────────────────────
    # NOTE: We deliberately do NOT include `exc.raw_body` in the response
    # body. It can contain Grab's internal response fragments (token bits,
    # session IDs, infrastructure hints) and is visible in browser DevTools.
    # Log it server-side keyed by `request_id` instead — supports triage
    # without leaking data to the browser.
    snippet = (exc.raw_body or "").strip().replace("\n", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "…"
    log.warning(
        "Grab login failed (unclassified): step=%s http=%s reason=%s "
        "request_id=%s source=%s body=%s",
        exc.step,
        exc.http_status,
        exc.grab_reason,
        exc.request_id,
        source,
        snippet,
    )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "grab_login_failed",
            "message": (
                f"Grab login failed (step {exc.step}, "
                f"HTTP {exc.http_status}): "
                f"{exc.grab_message or str(exc) or 'unknown'}"
            ),
            "hint": (
                "If this keeps happening, re-capture the x-ray token "
                "and confirm your Grab password."
            ),
            "fields": _CHALLENGE_FIELDS_BY_STEP.get(exc.step, []),
            "source": source,
            "request_id": exc.request_id,
        },
    )
