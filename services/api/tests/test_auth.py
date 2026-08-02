"""Tests for the 3-step login flow + structured error handling."""

from __future__ import annotations

import base64
import json
import time as _time

import httpx
import pytest
import respx

from app.routers.auth import _xray_jwt_age_hours
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
# Retry behaviour — rate-limited step 1 should retry with backoff
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_rate_limited_retries_then_succeeds(monkeypatch) -> None:
    """Two consecutive 429s then a 400 → login proceeds after backoff.

    Validates: (a) the retry loop kicks in on rate-limit, (b) the success
    path is reached once Grab stops throttling, (c) the backoff helper
    is invoked (we stub `asyncio.sleep` so the test stays fast).
    """
    sleep_calls: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    monkeypatch.setattr("grab.auth.asyncio.sleep", fake_sleep)

    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        side_effect=[
            httpx.Response(
                429,
                json={"reason": "rate_exceeded", "message": "rate limited"},
            ),
            httpx.Response(
                429,
                json={"reason": "rate_exceeded", "message": "rate limited"},
            ),
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

    # Step 4: user-profile v2/details. Successful login always fetches
    # the profile after step-3 to populate `result.profile`.
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
                }
            },
        )
    )

    result = await login_three_step("user@example.com", "password")
    assert result.display_token == "display.fake"
    assert result.authn_token == "authn.fake"

    # Two backoff sleeps were performed (one per 429 before success).
    assert len(sleep_calls) == 2
    # Backoff is BASE * 2 ** (attempt-1) with ±30% jitter, so:
    #   attempt 1 backoff: BASE * 1 = 2.0s → [1.4, 2.6]
    #   attempt 2 backoff: BASE * 2 = 4.0s → [2.8, 5.2]
    assert 1.4 <= sleep_calls[0] <= 2.6
    assert 2.8 <= sleep_calls[1] <= 5.2
    # Six calls total: two 429 retries of step1 + the successful step1 +
    # step2 (verifyChallenge) + step3 + step4 profile fetch.
    assert len(respx.calls) == 6


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_rate_limited_exhausts_retries(monkeypatch) -> None:
    """Three consecutive 429s → the last `LoginError` is surfaced."""
    sleep_calls: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    monkeypatch.setattr("grab.auth.asyncio.sleep", fake_sleep)

    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
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
    # Two backoffs between three attempts (we don't sleep after the
    # final exhausted attempt).
    assert len(sleep_calls) == 2
    # Step 1 endpoint was hit the full number of attempts.
    step1_calls = [
        c for c in respx.calls
        if c.request.url.path == "/grabid/v1/authnv4/login"
    ]
    assert len(step1_calls) == 3


@pytest.mark.asyncio
@respx.mock
async def test_login_step1_non_rate_limit_does_not_retry(monkeypatch) -> None:
    """A 500 (server error, not rate limit) should NOT trigger backoff
    retries — only `is_rate_limited` errors do. One attempt → raise."""
    sleep_calls: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    monkeypatch.setattr("grab.auth.asyncio.sleep", fake_sleep)

    respx.post("https://api.grab.com/grabid/v1/authnv4/login").mock(
        return_value=httpx.Response(500, text="server down")
    )

    with pytest.raises(LoginError) as info:
        await login_three_step("user@example.com", "password")

    assert info.value.http_status == 500
    # No backoff — server errors aren't retried, only rate-limits.
    assert sleep_calls == []


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
