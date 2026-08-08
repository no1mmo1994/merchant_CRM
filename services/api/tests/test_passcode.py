"""Tests for grab.endpoints.passcode — the merchant PIN gate on menu writes.

The endpoint is proven from a capture; the *hash* the operator's app sends
is not reproducible on the web (see the module docstring), so nothing in
the app feeds this a real PIN yet. These tests pin the two things that ARE
known: the exact request shape, and how each Grab status is read — so the
day a reproducible hash arrives, the wiring is already correct and
verified.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints.passcode import VALIDATE_PATH, validate_passcode

_URL = "https://api.grab.com" + VALIDATE_PATH
_HASH = "0" * 32  # dummy fixture — the mock ignores the value


@pytest.mark.asyncio
@respx.mock
async def test_sends_the_captured_request_shape(
    authn_token: str, merchant_id: str
) -> None:
    """`{"passcode": "<hash>"}` — exactly what the app sent, hash and all."""
    route = respx.post(_URL).mock(return_value=httpx.Response(200))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        ok = await validate_passcode(c, _HASH)

    assert ok is True
    assert json.loads(route.calls[0].request.content) == {"passcode": _HASH}


@pytest.mark.asyncio
@respx.mock
async def test_rejection_is_false_not_an_exception(
    authn_token: str, merchant_id: str
) -> None:
    """409 is what the live capture got — a wrong/expired passcode.

    It must read as "PIN rejected", not as an outage, so a caller can tell
    the two apart.
    """
    respx.post(_URL).mock(
        return_value=httpx.Response(
            409, json={"target": "ErrPasscode", "reason": "conflict"}
        )
    )
    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        assert await validate_passcode(c, _HASH) is False


@pytest.mark.parametrize("code", [400, 401, 403])
@pytest.mark.asyncio
@respx.mock
async def test_other_client_rejections_are_also_false(
    code: int, authn_token: str, merchant_id: str
) -> None:
    respx.post(_URL).mock(return_value=httpx.Response(code, json={}))
    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        assert await validate_passcode(c, _HASH) is False


@pytest.mark.asyncio
@respx.mock
async def test_server_error_propagates(
    authn_token: str, merchant_id: str
) -> None:
    """A 5xx is Grab failing, not the PIN being wrong — surface it."""
    respx.post(_URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(httpx.HTTPStatusError):
            await validate_passcode(c, _HASH)
