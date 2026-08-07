"""Tests for the 3-step login flow + structured error handling."""

from __future__ import annotations

import base64
import json
import time as _time

import httpx
import pytest
import respx

from app.routers.auth import _login_error_to_http, _xray_jwt_age_hours
from grab.auth import (
    ChallengeError,
    LoginError,
    StaticXRayProvider,
    login_three_step,
)


@pytest.mark.asyncio
@respx.mock
async def test_login_happy_path() -> None:
    """Run through the full 3-step login with mocked Grab responses."""

    # Step 1 — server returns HTTP 400 with challengeSessionID inside
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        side_effect=[
            httpx.Response(
                400,
                json={"details": {"challengeSessionID": "challenge-abc"}},
            ),
            httpx.Response(
                200,
                json={
                    "displayToken": "display.fake",
                    "authnToken": "authn.fake",
                },
            ),
        ]
    )

    respx.post(
        "https://api.grab.com/grabid/v1/challengesession/challengeSession/verifyChallenge"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    # Step 4: user-profile v2/details. `login_three_step` fetches this
    # after a successful 3-step login to extract `merchant_grab_id` and
    # the store display name (mirrors `Login/login1-done.py`).
    respx.get(
        "https://api.grab.com/mex-app/troy/user-profile/v2/details"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "user_profile": {
                    "merchant_grab_id": "zeus_store:MERCH-001",
                    "first_name": "My Store",
                    "user_profile_details": {"first_name": "My Store"},
                    "role": "Owner",
                    "profile_status": "ACTIVE",
                },
                "merchant_grab_id": "zeus_store:MERCH-001",
            },
        )
    )

    result = await login_three_step(
        "user@example.com",
        "password",
        xray=StaticXRayProvider(),
    )
    assert result.display_token == "display.fake"
    assert result.authn_token == "authn.fake"
    assert result.as_dict() == {"displayToken": "display.fake", "authnToken": "authn.fake"}
    assert result.profile["user_profile"]["merchant_grab_id"] == "zeus_store:MERCH-001"

    # Four requests should have been made: step1, step2, step3, profile.
    assert len(respx.calls) == 4


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_missing_challenge_raises() -> None:
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(400, json={"details": {}})
    )

    with pytest.raises(ChallengeError, match="challengeSessionID"):
        await login_three_step("user@example.com", "password")


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_unexpected_status_raises() -> None:
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(500, text="server down")
    )
    with pytest.raises(LoginError, match="HTTP 500"):
        await login_three_step("user@example.com", "password")


@pytest.mark.asyncio
@respx.mock
async def test_login_step2_wrong_password_raises() -> None:
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            400,
            json={"details": {"challengeSessionID": "challenge-abc"}},
        )
    )
    respx.post(
        "https://api.grab.com/grabid/v1/challengesession/challengeSession/verifyChallenge"
    ).mock(return_value=httpx.Response(401, text="wrong password"))

    with pytest.raises(LoginError, match="HTTP 401"):
        await login_three_step("user@example.com", "badpass")


@pytest.mark.asyncio
@respx.mock
async def test_login_step3_missing_tokens_raises() -> None:
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        side_effect=[
                httpx.Response(
                    400,
                    json={"details": {"challengeSessionID": "challenge-abc"}},
                ),
                httpx.Response(200, json={"something_else": True}),
            ]
    )
    respx.post(
        "https://api.grab.com/grabid/v1/challengesession/challengeSession/verifyChallenge"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    with pytest.raises(LoginError, match="missing tokens"):
        await login_three_step("user@example.com", "password")


def test_static_xray_provider_returns_tokens() -> None:
    provider = StaticXRayProvider()
    assert provider.get(1) != ""
    assert provider.get(3) != ""
    assert provider.get(2) == ""  # step 2 doesn't need an x-ray


# ──────────────────────────────────────────────────────────────────────────
# Structured error handling — the regression test for the clock-drift fix
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_rate_limited_carries_reason() -> None:
    """Step-1 returns HTTP 429 with a `rate_exceeded` body → LoginError
    must surface both `grab_reason` and `http_status` so the FastAPI
    layer can map it to a 429 HTTP response with a friendly message."""
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            429,
            json={"target": "", "reason": "rate_exceeded", "message": "rate limited"},
            headers={
                "x-grabbit-error-reason": "rate_exceeded",
                "x-grabbit-grab-requestid": "req-abc",
            },
        )
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.http_status == 429
    assert exc.grab_reason == "rate_exceeded"
    assert exc.grab_message == "rate limited"
    assert exc.request_id == "req-abc"
    assert exc.step == 1
    assert exc.is_rate_limited is True
    assert exc.is_clock_drift is False
    assert exc.is_xray_rejected is False


# ──────────────────────────────────────────────────────────────────────────
# Retry behaviour — step 1 rate-limiting fails fast, no server-side retry
# ──────────────────────────────────────────────────────────────────────────
# Server-side retry on a step-1 429 was deliberately removed — see the
# comment block above `login_three_step` in `grab/auth.py` (~line 311):
# the frontend's LoginErrorBanner already runs a 5-minute retry countdown
# after a user-initiated login attempt, so a transparent server-side retry
# here only delays an error the user is already going to see, and risks
# the frontend's 15s watchdog firing first. The three tests that used to
# assert retry-with-backoff (`..._retries_then_succeeds`,
# `..._exhausts_retries`, `..._non_rate_limit_does_not_retry`) tested
# behaviour that no longer exists and failed with
# `ModuleNotFoundError: No module named 'grab.auth.asyncio'` (there's no
# `asyncio.sleep` call left to monkeypatch). Replaced with a single test
# pinning the CURRENT contract below.


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_rate_limited_fails_fast_no_retry() -> None:
    """A 429 at step 1 propagates immediately as a rate-limited
    `LoginError` with exactly ONE request made to Grab — no
    server-side retry. This is the current, deliberate contract (see
    `grab/auth.py`'s comment block above `login_three_step`)."""
    route = respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            429,
            json={"reason": "rate_exceeded", "message": "rate limited"},
        )
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.is_rate_limited is True
    assert exc.http_status == 429
    # Exactly one request — no retry loop.
    assert route.call_count == 1
    assert len(respx.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_clock_drift_detected() -> None:
    """Step-1 returns HTTP 429 with `clock_drift` reason → is_clock_drift True."""
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            429,
            json={
                "target": "xray",
                "reason": "clock_drift",
                "message": "ERROR_CODE_POSSIBLE_DEVICE_CLOCK_DRIFT",
            },
        )
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.grab_reason == "clock_drift"
    assert exc.is_clock_drift is True
    # clock_drift also signals rate-limit-style throttling on this code path
    # but should NOT be classified as xray_rejected (it's a clock issue, not
    # a signature issue).
    assert exc.is_xray_rejected is False


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_xray_rejected_detected() -> None:
    """Step-1 returns an `xray` reason → is_xray_rejected True."""
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            401,
            json={"reason": "invalid_xray_signature", "message": "xray bad"},
        )
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.grab_reason == "invalid_xray_signature"
    assert exc.is_xray_rejected is True
    assert exc.is_clock_drift is False
    assert exc.is_rate_limited is False


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_device_challenge_detected() -> None:
    """`device_challenge_rejected` reason (matches the `"device"` token in
    `is_xray_rejected`) must classify as xray_rejected — but NOT as
    clock_drift (the `clock` substring check would otherwise fire on the
    word `clock` if it ever appeared). Lock both predicates here."""
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(
            401,
            json={
                "reason": "device_challenge_rejected",
                "message": "device challenge failed",
            },
        )
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.grab_reason == "device_challenge_rejected"
    assert exc.is_xray_rejected is True
    assert exc.is_clock_drift is False


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_non_json_body_still_classifies() -> None:
    """If Grab returns a non-JSON 5xx, we should still produce a structured
    LoginError — the raw body is preserved for debugging, but reason
    stays None."""
    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(502, text="<html>bad gateway</html>")
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    exc = info.value
    assert exc.http_status == 502
    assert exc.grab_reason is None
    assert exc.grab_message is None
    assert exc.step == 1
    assert exc.raw_body.startswith("<html>bad gateway</html>")


def test_login_error_as_dict_is_stable() -> None:
    """The dict projection used by the FastAPI layer must be stable so the
    frontend can rely on its shape across releases."""
    exc = LoginError(
        "step 1 failed (HTTP 429): reason='rate_exceeded'",
        step=1,
        grab_reason="rate_exceeded",
        grab_message="rate limited",
        http_status=429,
        request_id="req-xyz",
    )
    assert exc.as_dict() == {
        "step": 1,
        "http_status": 429,
        "grab_reason": "rate_exceeded",
        "grab_message": "rate limited",
        "request_id": "req-xyz",
    }


def test_login_error_truncates_pathological_bodies() -> None:
    """raw_body must be capped to prevent log/memory blow-ups."""
    exc = LoginError(
        "huge body",
        step=1,
        http_status=500,
        raw_body="x" * 100_000,
    )
    assert len(exc.raw_body) == 4096
    assert exc.raw_body == "x" * 4096


# ---------------------------------------------------------------------------
# _xray_jwt_age_hours — diagnostic JWT decoder
# ---------------------------------------------------------------------------
# These are unit tests for the helper that turns a JWT x-ray into a
# human-readable "your token is N hours old" hint. After the dashboard
# stopped accepting an x-ray_token from the user, the bundled token is
# the legacy outer-wrapper format (no JWT dots), so the integration
# tests in test_routers.py can no longer flow a synthetic JWT through
# the request body. The decoder still ships — exercised here directly.


def _build_jwt(payload: dict) -> str:
    """Build a syntactically valid (but unsigned) JWT for testing."""
    def _b64(d: dict) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(d).encode()
        ).rstrip(b"=").decode()
    header = {"alg": "RS256", "typ": "JWT"}
    return f"{_b64(header)}.{_b64(payload)}.fake-signature"


def test_xray_jwt_age_hours_returns_positive_age_for_stale_token() -> None:
    """JWT with `iat` 5h ago → age ≈ 5.0h (positive = stale)."""
    payload = {"iat": int(_time.time()) - 5 * 3600, "sub": "test"}
    age = _xray_jwt_age_hours(_build_jwt(payload))
    assert age is not None
    assert age == pytest.approx(5.0, abs=0.1)


def test_xray_jwt_age_hours_returns_negative_age_for_future_token() -> None:
    """JWT with `iat` 2h in the future → negative age (device clock ahead)."""
    payload = {"iat": int(_time.time()) + 2 * 3600, "sub": "future"}
    age = _xray_jwt_age_hours(_build_jwt(payload))
    assert age is not None
    assert age < 0
    assert age == pytest.approx(-2.0, abs=0.1)


def test_xray_jwt_age_hours_returns_none_for_legacy_format() -> None:
    """Legacy outer-wrapper format has zero dots → returns None.

    This is the actual format of the bundled `StaticXRayProvider` token
    from `login1-done.py`, so this is the production path.
    """
    assert _xray_jwt_age_hours("legacy-outer-wrapper-1992-chars-no-dots") is None


def test_xray_jwt_age_hours_returns_none_for_malformed_jwt() -> None:
    """Malformed JWT (non-JSON payload) must return None, not raise."""
    # Three dots but the middle part is garbage that won't decode.
    assert _xray_jwt_age_hours("aaa.!!!not-base64!!!.bbb") is None


def test_xray_jwt_age_hours_returns_none_for_missing_iat() -> None:
    """JWT without `iat` claim → returns None (no way to infer age)."""
    payload = {"sub": "no-iat-claim"}
    assert _xray_jwt_age_hours(_build_jwt(payload)) is None


def test_xray_jwt_age_hours_returns_none_for_none_input() -> None:
    """Defensive: None input must return None."""
    assert _xray_jwt_age_hours(None) is None


# ──────────────────────────────────────────────────────────────────────────
# Regression: step-2 "verify challenge payload" must NOT be misclassified as
# grab_xray_rejected. Step 2 (verifyChallenge) never carries an x-ray header
# — `StaticXRayProvider.get()` returns "" for step 2 — so a step-2 failure
# can never mean Grab rejected a token we didn't send. Before the fix,
# `is_xray_rejected`'s substring scan matched the literal token "challenge",
# which fires on Grab's own endpoint vocabulary (verifyChallenge errors
# routinely say "challenge") — so a wrong password sent operators off to
# re-capture an x-ray token Grab had already accepted at step 1.
# ──────────────────────────────────────────────────────────────────────────


def test_login_error_step2_verify_challenge_payload_is_not_xray_rejected() -> None:
    """Step 2 + reason 'invalid verify challenge payload' (Grab's flattened
    ERROR_CODE_INVALID_VERIFY_CHALLENGE_PAYLOAD) must NOT match
    `is_xray_rejected` — the `step == 2` guard short-circuits before the
    'challenge' substring can misfire. This is the exact reason string that
    caused the original misclassification."""
    exc = LoginError(
        "step 2 failed (HTTP 400): reason='invalid verify challenge payload'",
        step=2,
        grab_reason="invalid verify challenge payload",
        http_status=400,
    )
    assert exc.is_xray_rejected is False


def test_login_error_to_http_step2_verify_challenge_payload_maps_to_wrong_password() -> None:
    """The FastAPI translation of the same step-2 error must classify as
    `wrong_password` (not `grab_xray_rejected`), focus the `password` field,
    and echo `grab_reason` in the response body so operators can confirm
    which Grab classifier fired without re-reading server logs."""
    exc = LoginError(
        "step 2 failed (HTTP 400): reason='invalid verify challenge payload'",
        step=2,
        grab_reason="invalid verify challenge payload",
        http_status=400,
    )
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "wrong_password"
    assert http_exc.detail["fields"] == ["password"]
    assert http_exc.detail["grab_reason"] == "invalid verify challenge payload"


def test_login_error_step1_genuine_xray_reason_still_rejected() -> None:
    """Regression guard: step 1 DOES carry an x-ray header, so a genuine
    x-ray rejection there must still classify as `grab_xray_rejected`. The
    `step == 2` guard added by the fix must not blanket-disable x-ray
    detection for every step."""
    exc = LoginError(
        "step 1 failed (HTTP 401): reason='invalid xray token'",
        step=1,
        grab_reason="invalid xray token",
        http_status=401,
    )
    assert exc.is_xray_rejected is True
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "grab_xray_rejected"
    assert http_exc.detail["fields"] == ["xray_token"]


def test_login_error_step3_device_challenge_still_rejected() -> None:
    """Regression guard: step 3 (commit) also carries an x-ray header, so a
    'device challenge failed' reason there must still classify as
    `grab_xray_rejected` — only step 2 is exempted by the fix."""
    exc = LoginError(
        "step 3 failed (HTTP 401): reason='device challenge failed'",
        step=3,
        grab_reason="device challenge failed",
        http_status=401,
    )
    assert exc.is_xray_rejected is True
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "grab_xray_rejected"


# ──────────────────────────────────────────────────────────────────────────
# Precedence at step 2 — the wrong_password branch must not swallow other
# signals that happen to co-occur at step 2 (clock drift, rate limiting,
# upstream 5xx). `_login_error_to_http` checks clock-drift and rate-limit
# BEFORE the password branch, so those must win even though `is_xray_rejected`
# is now unconditionally False at step 2.
# ──────────────────────────────────────────────────────────────────────────


def test_login_error_to_http_step2_clock_drift_beats_wrong_password() -> None:
    """Step 2 + a clock-drift reason + HTTP 429 (which would otherwise also
    look rate-limited AND like a 401/403-style password failure) must still
    resolve to `grab_clock_drift` — clock drift is checked first because it
    is the most actionable diagnosis when several signals overlap."""
    exc = LoginError(
        "step 2 failed (HTTP 429): reason='possible device clock drift'",
        step=2,
        grab_reason="possible device clock drift",
        http_status=429,
    )
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "grab_clock_drift"


def test_login_error_to_http_step2_rate_limited_beats_wrong_password() -> None:
    """Step 2 + HTTP 429 must resolve to `grab_rate_limited`, not
    `wrong_password` — the rate-limit check runs before the password branch
    even though HTTP 429 is not one of the 401/403 codes the password
    branch itself checks."""
    exc = LoginError(
        "step 2 failed (HTTP 429): reason='rate_exceeded'",
        step=2,
        grab_reason="rate_exceeded",
        http_status=429,
    )
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "grab_rate_limited"


def test_login_error_to_http_step2_upstream_5xx_beats_wrong_password() -> None:
    """Step 2 + HTTP 500 with no password-shaped reason must fall through to
    `grab_upstream_error`, not `wrong_password` — a 500 is not in the
    password branch's (401, 403) status set and carries no reason token, so
    it must reach the generic server-error branch instead."""
    exc = LoginError(
        "step 2 failed (HTTP 500)",
        step=2,
        grab_reason=None,
        http_status=500,
    )
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "grab_upstream_error"


def test_login_error_to_http_step2_401_no_reason_still_wrong_password() -> None:
    """The original (pre-fix) detection path must keep working: step 2 +
    HTTP 401 with NO reason string at all still classifies as
    `wrong_password` purely on status code — the new reason-token list is
    additive, not a replacement for this path."""
    exc = LoginError(
        "step 2 failed (HTTP 401)",
        step=2,
        grab_reason=None,
        http_status=401,
    )
    http_exc = _login_error_to_http(exc, source="login")
    assert http_exc.detail["code"] == "wrong_password"
    assert http_exc.detail["fields"] == ["password"]
    assert http_exc.detail["grab_reason"] is None
