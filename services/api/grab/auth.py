"""3-step Grab login flow + x-ray token abstraction.

The Grab Merchant login isn't a single POST — it's three:

1. POST `/grabid/v1/authnv4/login` with the email + serviceID. The server
   replies with HTTP 400 + `details.challengeSessionID`. Header MUST carry
   `x-ray` (step-1 token).
2. POST `/grabid/v1/challengesession/challengeSession/verifyChallenge`
   with the password. No `x-ray` header needed. Server replies 200 if the
   password is correct.
3. POST `/grabid/v1/authnv4/login` again with the same payload plus
   `challengeSessionId`. Header MUST carry `x-ray` (step-3 token). Server
   replies 200 with `{displayToken, authnToken}`.

`XRayProvider` exists so we can swap in a real x-ray token generator
later (Phase 11) without rewriting the login flow. `StaticXRayProvider`
ships with the historical captured tokens so the flow can be exercised
end-to-end today.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from re import sub
from typing import Any, Protocol, runtime_checkable

import httpx

log = logging.getLogger("pulseorder.grab.auth")

# Step-1 and step-3 x-ray tokens captured from the historical log files.
# They're tied to the static DEVICE_UDID + UA in `client.py`. If those
# change, these tokens become invalid — Phase 11 will replace them with a
# real x-ray generator.
_STATIC_XRAY_STEP1 = (
    "eyJhIjoiUDY2dDNtaE84M1MxZHdERk1PcSt1cENWdVFCVjY1YXMyR1ZpM3dmNGNwOHd6QUFIKzB4ZX"
    "YwRityS3hPRmxEN3RCbVI2OExienNpXC84TW50Ymx2K0hqTTdiaW1yVm9wU3lsQzdOcVNQdUVFUitq"
    "M3Vvc0JMVEJpNE1KQW5GSmY4OXlFXC94aWRBUG1EXC9NSlkrQ2Y2b3kzcm0wSGVDNmJyZ2xvWjhyck"
    "pUdUxVM05iQXg1SXRjUEJcL2cxUVNkN3psQWVxYWFob2lYdzRaWFlGSTd1dWQzM0gyTTRyaGQxWDNK"
    "WDRZK0hudFVZclFXeGlEdUQ4MnE0V1lkK0JVbHhkT0U1Mmd5R0hlSG1saEFKWjdkNnpxMVFRRzdMY3"
    "g5TVZGb1l4UEJHMzU3ZW9PWFprcDdGTDFUS2pNcko0bFMwbVpBTTBsWUNjODNBYWg1MkpJRmh6amJB"
    "NkdVZ3JVczd3SUVteE9VY2ZMS1hBOXhPdlF2VzBqMG9ra21mRDBMeFVVWXlBcW93dkdjK0tMVmZhcn"
    "pZWEN5XC8rWXZjekZsdXRcL1FuVFZFKzdtTWJpaDBvZVk5STNUN2phazFkeDhtbzZBZVJsOUVKUld1"
    "ZUs4UGtUdmdES2J1NlF6cUFmaEZ4eHpJTENXczZ6TjlTMWczUURKS2ZVUldPUnRzXC9DTlc4NnI5c0"
    "Y3ZGNWazJMU2JqTlh2VmJyajlIeDkyS2I0bjZHNWJjYWc4WHJRVys5VnM2am5oamp0QjFaQzlKOThE"
    "amh3cEtNZTYwV1hhTjBMdjdVcVwvV1NLeGVGY1YwUmZuaGZrb0krdWo4V05SYlNUUGZsRCtwQlc3UU"
    "w0b3hEZ3ByOHg3aVloV0lsSGlqNUFOVFdEN0xleXlOQXlqU3pOS2VQalFcL3lnK2pIRjVmNEk9Iiwi"
    "YyI6IjhweVwvR0RpdmtkbFlPNjZUSFhReDREWmRBelZDSWljc2lidzNkWXR5T0o4a2N1VHhDMnI1RV"
    "ErOUd4R1pjblZpTHpqckt3YjFyYUZ2XC9CSmpSbUphcnV1TFwveUFyenRsT1RkNnZvUHRMMlJVaFRN"
    "Tm5FWWRJQk44RnNOU0pRRFBSSzJSMjNBWDkxN3JrcER0XC82c0pGblJHaGFCUGhDU21BQ0Z2YWYzU2"
    "5nYzRSTzNSd0sxalUxV0FKUnFCUWFNT2orNHdiY1lIUGlPTjJ5WUExUmlGMXY3RjBzRWgwcDZ4dEU3"
    "WDM5eVwvbWVmVmlCYTBYQ0p3UEdPQUFyM0hTWFJNNHdhTVBWc2VMVXpZNGV3ZlBQY0U2d3REbzVJRX"
    "N2d1wvWVQzS2JLQnA1bnRubGNOK2QySW5ab1B5VEQ4RmVwQlplVVN3ZjZUWXlwZFwvaXBIYXdtWkIw"
    "cFVxRXhWQUREcnJCRDZUajJjd3RFdGsxS05LZElLdmRjSWpHUUsxY0hSZzdpSTVXSmRvSyt2dHJwek"
    "FZUnRuc2JLZjJqY2tjXC9oT1lra2ZuNE02RW1ucXlZbUl6ZEV3YUwxK1pYZGw5a3UzekNHOGMzY0gx"
    "R1E3NFwvWk5SVllJRU9KTkp3NWw4cHNRRUFnTXBCeHZMRFpuK2hwSzdMVmttU2tIaGlSM1FpUHhTbU"
    "EyR2dlK3E1Vk9zMFA3Y2ltcUs5bzBFQ3k0QkJxcmJvYjFEMVwvUnNvM0VqWnZMUjFoNU5zb2RHQVlT"
    "NlRZbU9yRG1JT256ZUZuVWhRR1FIcWdtR3lIeTNYa3BxUHJkajVIZjBlU0VxVzhWU3IzSmEya1k9Ii"
    "wiaXMiOiJ0IiwidGFtcGVyZWQiOiJmIiwiaSI6Im0xIiwidiI6IncuNC43Ny4wLjE4NyIsImsiOjM3"
    "NDYzNDksImt2IjoiMyIsIm9pIjoiRDJ2NGdGM2M2ciIsImdzaWQiOiJjb20uZ3JhYi5tZXguYXBwbG"
    "ljYXRpb24uTWV4QXBwbGljYXRpb25AOWVkNGQwMyJ9"
)

_STATIC_XRAY_STEP3 = _STATIC_XRAY_STEP1  # same value in the captured log


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class LoginError(RuntimeError):
    """Raised when the login flow fails at any of the three steps.

    Carries enough structured context for the FastAPI layer to map the
    failure to an actionable HTTP response — instead of leaking the raw
    Grab JSON to end users.
    """

    #: Grab's machine-readable reason code (e.g. "rate_exceeded",
    #: "clock_drift"). Sourced from the `reason` field of the Grab error
    #: envelope, or the `X-Grabkit-Error-Reason` header. `None` when the
    #: failure is non-JSON (network error, malformed body, …).
    grab_reason: str | None
    #: Human message from Grab's `message` field (e.g. "rate limited").
    grab_message: str | None
    #: HTTP status from Grab (e.g. 429, 401, 5xx).
    http_status: int | None
    #: Which login step raised the error (1, 2, or 3).
    step: int
    #: Raw response body — used for debugging. Truncated to 4 KiB so a
    #: pathological response can't blow up logs.
    raw_body: str = ""
    #: `X-Grabkit-Grab-Requestid` if present; useful for support tickets.
    request_id: str | None = None

    def __init__(
        self,
        message: str,
        *,
        step: int,
        grab_reason: str | None = None,
        grab_message: str | None = None,
        http_status: int | None = None,
        raw_body: str = "",
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.grab_reason = grab_reason
        self.grab_message = grab_message
        self.http_status = http_status
        self.raw_body = raw_body[:4096]
        self.request_id = request_id

    @property
    def is_rate_limited(self) -> bool:
        """True if Grab returned HTTP 429 or a `rate_exceeded` reason."""
        return self.http_status == 429 or self.grab_reason == "rate_exceeded"

    @property
    def is_clock_drift(self) -> bool:
        """True if Grab flagged the request as clock-drifted.

        The error code can surface as `clock_drift`, `clock_skew`, or
        the full `ERROR_CODE_POSSIBLE_DEVICE_CLOCK_DRIFT` constant —
        we accept any of them. As a final fallback, also scan the raw
        body text — Grab occasionally returns a plain-text error body
        (not JSON) that still contains "clock drift".
        """
        if self.grab_reason and "clock" in self.grab_reason.lower():
            return True
        if self.grab_message and "clock" in self.grab_message.lower():
            return True
        if self.raw_body and "clock" in self.raw_body.lower():
            return True
        return False

    @property
    def is_xray_rejected(self) -> bool:
        """True if the failure looks like Grab rejected the x-ray token
        specifically (signature mismatch, expired, replay, …)."""
        if not self.grab_reason:
            return False
        reason = self.grab_reason.lower()
        return any(
            token in reason
            for token in ("xray", "x_ray", "x-ray", "challenge", "device")
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "http_status": self.http_status,
            "grab_reason": self.grab_reason,
            "grab_message": self.grab_message,
            "request_id": self.request_id,
        }


class ChallengeError(LoginError):
    """Raised when step 1 returns no challengeSessionID (e.g. invalid email).

    Note: `grab_reason` stays None here — this is a structural failure
    (missing field), not a Grab-classified error.
    """


# ---------------------------------------------------------------------------
# x-ray provider
# ---------------------------------------------------------------------------
@runtime_checkable
class XRayProvider(Protocol):
    """Returns the x-ray token for a given login step.

    Step 1 is the initial challenge request; step 3 is the final commit.
    Step 2 (challenge verify) does not require an x-ray token, so
    implementations may return an empty string there.
    """

    def get(self, step: int) -> str: ...


@dataclass
class StaticXRayProvider:
    """Hard-coded x-ray provider using the captured log tokens.

    Useful for development against a known-good account. Phase 11 will
    swap in a runtime generator when the long-lived flow lands.
    """

    step1_token: str = _STATIC_XRAY_STEP1
    step3_token: str = _STATIC_XRAY_STEP3

    def get(self, step: int) -> str:
        if step == 1:
            return self.step1_token
        if step == 3:
            return self.step3_token
        return ""


# ---------------------------------------------------------------------------
# Pre-login header template (mirrors what the Login/*.py scripts use).
# Imported by GrabClient-like flows only when needed; kept here so the
# login path stays self-contained.
# ---------------------------------------------------------------------------
_PRELOGIN_HEADERS: dict[str, str] = {
    "host": "api.grab.com",
    "accept": "application/json",
    "x-timezone": "Asia/Bangkok",
    "x-accept-language": "vi-VN;q=1.0",
    "x-deviceudid": "da7ca3ef14e2efb04362157a3b8fbbd12be5e387addfab651d5dd0057a9ca2df",
    "x-tracking-id": "J7mpkanH6rFmVhCe39zxpM7wm4ahy6iN",
    "user-agent": "Grab Merchant/4.181.0 (android 12; Build 290)",
    "content-type": "application/json; charset=utf-8",
    "accept-encoding": "gzip",
}


def _prelogin_headers(xray_provider: XRayProvider, step: int) -> dict[str, str]:
    headers = dict(_PRELOGIN_HEADERS)
    token = xray_provider.get(step)
    if token:
        headers["x-ray"] = token
    return headers


def _classify_grab_error(
    response: httpx.Response,
    step: int,
) -> LoginError:
    """Build a `LoginError` from a non-OK Grab response.

    Pulls `reason` + `message` out of Grab's standard JSON envelope
    (`{"target":"","reason":"...","message":"..."}`) and the
    `X-Grabkit-Error-Reason` header. Falls back to a plain LoginError
    with the raw body when the body isn't JSON.

    Grab occasionally returns an error envelope shaped
    `{"code":"ERROR_CODE_POSSIBLE_DEVICE_CLOCK_DRIFT"}` with neither
    `reason` nor `message` populated. The classifier hoists `code` into
    `grab_reason` when those are missing so downstream consumers (the
    FastAPI layer's `_login_error_to_http` and the LoginForm banner)
    can branch on it.
    """
    request_id = response.headers.get("x-grabbit-grab-requestid")
    raw_body = response.text or ""

    reason: str | None = None
    message: str | None = None
    code: str | None = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            reason = payload.get("reason") or response.headers.get(
                "x-grabbit-error-reason"
            )
            message = payload.get("message")
            code = payload.get("code")
    except (json.JSONDecodeError, ValueError):
        pass

    if reason is None:
        reason = response.headers.get("x-grabbit-error-reason")
    if reason is None and code:
        # Hoist the `code` field into reason so predicates like
        # `is_xray_rejected` (which scan for tokens like "xray",
        # "challenge", "device") and `is_clock_drift` (which scans
        # for "clock") work uniformly regardless of envelope shape.
        # Convert e.g. "ERROR_CODE_POSSIBLE_DEVICE_CLOCK_DRIFT" →
        # "possible_device_clock_drift" so the tokenized predicates
        # match without growing the keyword list.
        reason = sub(r"^ERROR_CODE_|_$", "", code).lower().replace("_", " ").strip()

    pretty = (
        f"step {step} failed (HTTP {response.status_code})"
        + (f": reason={reason!r}" if reason else "")
        + (f" message={message!r}" if message else "")
    )
    return LoginError(
        pretty,
        step=step,
        grab_reason=reason,
        grab_message=message,
        http_status=response.status_code,
        raw_body=raw_body,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# 3-step login
# ---------------------------------------------------------------------------

# Rate-limit mitigation: Grab throttles repeated POSTs to the same
# `/grabid/v1/authnv4/login` endpoint with the same x-ray token + IP for
# ~5 minutes. The 3-step flow's step 1 is the first to trip it.
#
# We previously retried step 1 with exponential backoff (3 attempts,
# 2s/4s/8s with ±30% jitter). On a throttled IP the full retry cycle
# can run 10-30s — long enough that the frontend's login watchdog
# (`apps/web/lib/api/auth.ts` — 15s Promise.race) fires first and the
# user sees a "Login request timed out" toast instead of the
# structured "wait 5 minutes" message the backend can produce.
#
# Fail-fast fix: surface the first 429 immediately. The user is
# already mid-login (a single user-initiated action, not an
# automated retry storm), so a transparent retry here only delays
# an error we can't avoid. The frontend's
# `LoginErrorBanner → RetryCountdown` already auto-retries after
# the cooldown with a fresh user gesture.
#
# If a future workflow needs automatic retry (e.g. an unattended
# refresh-token cron), introduce a SECOND retry policy dedicated to
# that path — don't share the constant with the user-facing login.
# Currently `login_three_step` makes exactly one step-1 attempt.


@dataclass
class LoginResult:
    """Successful login result — both tokens the Grab server returns."""

    display_token: str
    authn_token: str
    # Raw user-profile payload returned by Grab's
    # `GET /mex-app/troy/user-profile/v2/details` (Step 4 of the
    # flow that mirrors `Login/login1-done.py`). The caller
    # extracts `merchant_grab_id` + `first_name` from here so
    # the user never has to type their store name into the form.
    profile: dict[str, Any]

    def as_dict(self) -> dict[str, str]:
        return {
            "displayToken": self.display_token,
            "authnToken": self.authn_token,
        }


async def login_three_step(
    email: str,
    password: str,
    *,
    xray: XRayProvider | None = None,
    verify_ssl: bool = False,
) -> LoginResult:
    """Run the full 3-step login against api.grab.com.

    Args:
        email: The Grab Merchant account email.
        password: The plaintext password.
        xray: Token provider; defaults to `StaticXRayProvider`.
        verify_ssl: Set True to enable TLS verification (default False to
            match the MITM-captured log traffic).

    Returns:
        LoginResult with `display_token` and `authn_token`.

    Raises:
        ChallengeError: If step 1 returns no challengeSessionID.
        LoginError: On any other HTTP or parse failure. If Grab rate-
            limits step 1, the first 429 is surfaced immediately as a
            ``grab_rate_limited`` LoginError — the dashboard's
            LoginErrorBanner auto-retries after Grab's ~5 minute cooldown.
    """
    provider = xray or StaticXRayProvider()
    step1_payload = {
        "accountIdentifier": email,
        "accountIdentifierType": "USERNAME",
        "redirect": "grabmex://success",
        "serviceID": "MEXUSERS",
        "rememberMe": True,
    }

    async with httpx.AsyncClient(
        base_url="https://api.grab.com",
        verify=verify_ssl,
        timeout=30.0,
    ) as http:
        # --- Step 1: kick off login, get challengeSessionID. ---
        # Fail-fast on 429: when Grab throttles, the FIRST response is
        # the one we want to surface — the LoginErrorBanner has a
        # 5-minute auto-retry countdown, so retrying server-side only
        # delays an error the user is already going to see.
        step1 = await http.post(
            "/grabid/v1/authnv4/login",
            headers=_prelogin_headers(provider, step=1),
            json=step1_payload,
        )
        # Step 1 is expected to return HTTP 400 — that's how Grab
        # signals "your email is valid, here's the challenge".
        if step1.status_code != 400:
            raise _classify_grab_error(step1, step=1)

        # step1 is non-None here; we either got the 400 we wanted or
        # raised above.
        assert step1 is not None and step1.status_code == 400

        try:
            step1_data = step1.json()
        except json.JSONDecodeError as e:
            raise LoginError(
                f"Step 1 JSON decode failed: {e}",
                step=1,
                http_status=step1.status_code,
                raw_body=step1.text or "",
            ) from e

        challenge_session_id = (step1_data.get("details") or {}).get("challengeSessionID")
        if not challenge_session_id:
            raise ChallengeError(
                f"Step 1 missing challengeSessionID: {step1_data!r}",
                step=1,
                http_status=step1.status_code,
                raw_body=step1.text or "",
            )

        # --- Step 2: verify the password against the challenge
        step2 = await http.post(
            "/grabid/v1/challengesession/challengeSession/verifyChallenge",
            headers=_prelogin_headers(provider, step=2),
            json={
                "challengeSessionID": challenge_session_id,
                "challengeType": "PWD_V2",
                "payload": {"code": password},
            },
        )
        if step2.status_code != 200:
            raise _classify_grab_error(step2, step=2)

        # --- Step 3: commit the login, get tokens
        step3 = await http.post(
            "/grabid/v1/authnv4/login",
            headers=_prelogin_headers(provider, step=3),
            json={
                "accountIdentifier": email,
                "accountIdentifierType": "USERNAME",
                "redirect": "grabmex://success",
                "serviceID": "MEXUSERS",
                "challengeSessionId": challenge_session_id,
                "rememberMe": True,
            },
        )
        if step3.status_code != 200:
            raise _classify_grab_error(step3, step=3)
        try:
            step3_data = step3.json()
        except json.JSONDecodeError as e:
            raise LoginError(
                f"Step 3 JSON decode failed: {e}",
                step=3,
                http_status=step3.status_code,
                raw_body=step3.text or "",
            ) from e

        display_token = step3_data.get("displayToken")
        authn_token = step3_data.get("authnToken")
        if not display_token or not authn_token:
            raise LoginError(
                f"Step 3 response missing tokens: {step3_data!r}",
                step=3,
                http_status=step3.status_code,
                raw_body=step3.text or "",
            )

    # --- Step 4: fetch user profile (merchant_id + store name come from here) ---
    # `login1-done.py` does this on the same session with the freshly-minted
    # `authnToken` (passed via `x-mts-ssid` on GrabClient). Use a fresh
    # GrabClient so we get the proper header set + post-login User-Agent.
    from grab.client import GrabClient
    from grab.endpoints.profile import get_user_profile

    try:
        async with GrabClient(
            authn_token=authn_token,
            verify_ssl=verify_ssl,
        ) as client:
            profile = await get_user_profile(client)
    except httpx.HTTPError as exc:
        raise LoginError(
            f"Step 4 (profile) HTTP error: {exc}",
            step=4,
            http_status=getattr(exc, "response", None)
            and getattr(exc.response, "status_code", None),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Pydantic ValidationError, JSONDecodeError, anything else.
        raise LoginError(
            f"Step 4 (profile) failed: {exc}",
            step=4,
        ) from exc

    return LoginResult(
        display_token=display_token,
        authn_token=authn_token,
        profile=profile,
    )