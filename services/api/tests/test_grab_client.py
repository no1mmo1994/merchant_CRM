"""Tests for the GrabClient header injection + async lifecycle."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient


@pytest.mark.asyncio
async def test_context_manager_requires_auth_token() -> None:
    with pytest.raises(ValueError, match="authn_token"):
        GrabClient(authn_token="", merchant_id="zeus_store:1")


@pytest.mark.asyncio
async def test_merchant_id_is_optional_for_user_level_endpoints() -> None:
    """merchant_id is optional: user-level endpoints (store-list, profile)
    don't need the x-mex-resource header.  Constructing without one must
    NOT raise; the header simply isn't emitted on requests.
    """
    # No ValueError when merchant_id is missing.
    client = GrabClient(authn_token="x")  # no merchant_id
    assert client.merchant_id is None


@pytest.mark.asyncio
async def test_uses_async_context_manager() -> None:
    """`_client` is only constructed inside `__aenter__`."""
    client = GrabClient(authn_token="x", merchant_id="zeus_store:1")
    assert client._client is None  # type: ignore[attr-defined]
    async with client:
        assert isinstance(client._client, httpx.AsyncClient)
    assert client._client is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_injects_required_headers_on_request(
    authn_token: str, merchant_id: str
) -> None:
    """Each request must carry authn token + merchant id + UA fingerprint."""
    respx.get("https://api.grab.com/mex-app/troy/user-profile/v2/details").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with GrabClient(
        authn_token=authn_token, merchant_id=merchant_id, verify_ssl=True
    ) as client:
        await client.get("/mex-app/troy/user-profile/v2/details")

    request = respx.calls[0].request
    assert request.headers["authorization"] == authn_token
    assert request.headers["x-mts-ssid"] == authn_token
    assert request.headers["x-mex-resource"] == merchant_id
    assert request.headers["user-agent"].startswith("Grab Merchant/")


@pytest.mark.asyncio
@respx.mock
async def test_omits_x_mex_resource_when_merchant_id_missing(authn_token: str) -> None:
    """When merchant_id is None (user-level endpoint), the x-mex-resource
    header must NOT be sent — Grab rejects unknown resource headers on
    user-level routes."""
    respx.get("https://api.grab.com/mex-app/troy/user-profile/v1/store-list").mock(
        return_value=httpx.Response(200, json={"data": {"stores": []}})
    )

    async with GrabClient(authn_token=authn_token, verify_ssl=True) as client:
        await client.get("/mex-app/troy/user-profile/v1/store-list")

    request = respx.calls[0].request
    assert request.headers["authorization"] == authn_token
    assert "x-mex-resource" not in request.headers


@pytest.mark.asyncio
@respx.mock
async def test_request_outside_context_raises() -> None:
    client = GrabClient(authn_token="x", merchant_id="zeus_store:1")
    with pytest.raises(RuntimeError, match="async with"):
        await client.get("/food/merchant/v2/menu")