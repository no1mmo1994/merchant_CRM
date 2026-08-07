"""Tests for grab.endpoints.concurrency (menu edit lock).

`acquire_menu_edit_lock` is deliberately best-effort: it must never raise,
whatever Grab (or the network) does, and callers only ever see True/False.
Direct-endpoint-call style, same as tests/test_modifiers.py.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints.concurrency import acquire_menu_edit_lock

_LOCK_URL = "https://api.grab.com/food/merchant/v1/concurrency-handling/enter"


@pytest.mark.asyncio
@respx.mock
async def test_acquire_menu_edit_lock_200_returns_true_with_exact_body(
    authn_token: str, merchant_id: str
) -> None:
    route = respx.post(_LOCK_URL).mock(return_value=httpx.Response(200))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        acquired = await acquire_menu_edit_lock(c)

    assert acquired is True
    assert route.called
    assert json.loads(route.calls[0].request.content) == {
        "feature": "mexMenuEdit",
        "subFeature": "all",
    }


@pytest.mark.asyncio
@respx.mock
async def test_acquire_menu_edit_lock_409_returns_false_without_raising(
    authn_token: str, merchant_id: str
) -> None:
    respx.post(_LOCK_URL).mock(
        return_value=httpx.Response(409, json={"message": "locked by another session"})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        acquired = await acquire_menu_edit_lock(c)

    assert acquired is False


@pytest.mark.asyncio
@respx.mock
async def test_acquire_menu_edit_lock_500_returns_false_without_raising(
    authn_token: str, merchant_id: str
) -> None:
    respx.post(_LOCK_URL).mock(return_value=httpx.Response(500, text="boom"))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        acquired = await acquire_menu_edit_lock(c)

    assert acquired is False


@pytest.mark.asyncio
@respx.mock
async def test_acquire_menu_edit_lock_transport_error_returns_false_without_raising(
    authn_token: str, merchant_id: str
) -> None:
    """DNS/connect/timeout is a different exception type than a bad HTTP
    response (`httpx.HTTPError`, not `httpx.HTTPStatusError`) -- pin that
    the try/except in acquire_menu_edit_lock actually catches it rather
    than only handling status-code failures."""
    respx.post(_LOCK_URL).mock(side_effect=httpx.ConnectError("boom"))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        acquired = await acquire_menu_edit_lock(c)

    assert acquired is False
