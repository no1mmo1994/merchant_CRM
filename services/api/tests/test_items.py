"""Tests for menu item endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import items


@pytest.mark.asyncio
@respx.mock
async def test_upload_image_returns_url(authn_token: str, merchant_id: str, tmp_path) -> None:
    respx.post("https://api.grab.com/food/merchant/v2/upload-file").mock(
        return_value=httpx.Response(
            200,
            json={"url": "https://cdn.grab.com/uploads/abc.jpg"},
        )
    )

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        url = await items.upload_image(c, image_path)

    assert url == "https://cdn.grab.com/uploads/abc.jpg"
    body = respx.calls[0].request.content
    assert b'"category":"menu_item_img"' in body


@pytest.mark.asyncio
@respx.mock
async def test_upload_image_missing_file(authn_token: str, merchant_id: str) -> None:
    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        url = await items.upload_image(c, "/nonexistent/path.png")
    assert url is None


@pytest.mark.asyncio
@respx.mock
async def test_create_or_update_item(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v2/upsert-item").mock(
        return_value=httpx.Response(
            200,
            json={"itemID": "ITEM1", "itemName": "Cua Hoàng Đế"},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await items.create_or_update_item(
            c,
            name_vi="Cua Hoàng Đế",
            name_en="King Crab",
            description_vi="Rất ngon",
            description_en="Very tasty",
            price_vnd=500000,
            category_id="VNCAT1",
            image_urls=["https://cdn.example.com/1.jpg"],
            linked_modifier_group_ids=["VNMOG1"],
        )

    assert data["itemID"] == "ITEM1"
    body = respx.calls[0].request.content
    # Spot-check the payload shape (encode UTF-8 strings at runtime since
    # Python bytes literals are ASCII-only).
    assert '"itemName":"Cua Hoàng Đế"'.encode("utf-8") in body
    assert b'"priceInMin":500000' in body
    assert b'"categoryID":"VNCAT1"' in body
    assert b'"linkedModifierGroupIDs":["VNMOG1"]' in body    # noqa: RUF001
    assert b'"imageURLs":["https://cdn.example.com/1.jpg"]' in body