"""Tests for store metadata endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import store


@pytest.mark.asyncio
@respx.mock
async def test_get_business_attributes(authn_token: str, merchant_id: str) -> None:
    respx.get(
        "https://api.grab.com/food/merchant/v1/business-attributes",
        params__contains={"merchantID": "5-C6VKAT5GRK3CTT"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"businessAttributeValues": [{"merchantID": "5-C6VKAT5GRK3CTT"}]},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await store.get_business_attributes(c)

    assert data["businessAttributeValues"][0]["merchantID"] == "5-C6VKAT5GRK3CTT"


@pytest.mark.asyncio
@respx.mock
async def test_get_scorecard(authn_token: str, merchant_id: str) -> None:
    respx.get(
        "https://api.grab.com/mex-app/troy/scorecard/v1/profile",
        params__contains={"screen": "ENTRY"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"title": "Gold", "score": 92, "scoreRank": "TOP_10_PERCENT"},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await store.get_scorecard(c)

    assert data["title"] == "Gold"
    assert data["score"] == 92