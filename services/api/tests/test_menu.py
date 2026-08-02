"""Tests for menu retrieval endpoint."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import menu


@pytest.mark.asyncio
@respx.mock
async def test_get_full_menu(authn_token: str, merchant_id: str) -> None:
    respx.get("https://api.grab.com/food/merchant/v2/menu").mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": [
                    {
                        "categoryID": "CAT1",
                        "categoryName": "Món chính",
                        "sortOrder": 5,
                    }
                ],
                "sections": [],
            },
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await menu.get_full_menu(c)

    assert data["categories"][0]["categoryName"] == "Món chính"
    # And the request URL carried orderID + oosItemID empty params
    assert "orderID=" in str(respx.calls[0].request.url)
    assert "oosItemID=" in str(respx.calls[0].request.url)