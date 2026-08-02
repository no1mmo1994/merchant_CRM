"""Tests for modifier endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import modifiers


@pytest.mark.asyncio
@respx.mock
async def test_verify_modifier(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v2/verify-modifier").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await modifiers.verify_modifier(
            c, name_vi="Thêm trứng", name_en="Extra egg", price_vnd=5000
        )

    assert data == {"ok": True}
    body = respx.calls[0].request.content
    assert '"modifierName":"Thêm trứng"'.encode("utf-8") in body
    assert b'"priceInMin":5000' in body


@pytest.mark.asyncio
@respx.mock
async def test_create_modifier_group(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v3/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={"modifierGroupID": "MOG1", "modifierGroupName": "Topping"},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await modifiers.create_modifier_group(
            c,
            group_name_vi="Topping",
            group_name_en="Topping",
            selection_range_min=0,
            selection_range_max=2,
            modifiers=[
                {"name_vi": "Thêm trứng", "name_en": "Extra egg", "price": 5000},
                {"name_vi": "Thêm phô mai", "name_en": "Extra cheese", "price": 8000},
            ],
        )

    assert data["modifierGroupID"] == "MOG1"
    body = respx.calls[0].request.content
    assert b'"modifierGroupName":"Topping"' in body
    assert b'"selectionRangeMin":0' in body
    assert b'"selectionRangeMax":2' in body
    assert '"modifierName":"Thêm trứng"'.encode("utf-8") in body
    assert '"modifierName":"Thêm phô mai"'.encode("utf-8") in body