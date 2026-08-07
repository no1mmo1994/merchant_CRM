"""Tests for menu item endpoints."""

from __future__ import annotations

import json

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


# ── set_item_availability -- nested-menu / missing-categoryID regression ────────
#
# `set_item_availability` fetches /menu, walks it via `find_item_with_category`
# to locate the item, and writes the item back via upsert-item. Two bugs used
# to live here: (1) the walk only looked at the flat `menu["categories"]`
# shape, so it usually found nothing on a real store, which returns the
# nested `menu["sections"][].categories[].items[]` shape; and (2) once found,
# the category sent back to Grab was read from the item's own `categoryID`
# (frequently absent on `/menu` items) rather than the id of the category
# that actually contained it, defaulting to "" and knocking the item out of
# its category on Grab.


@pytest.mark.asyncio
@respx.mock
async def test_set_item_availability_nested_menu_uses_containing_category_id(
    authn_token: str, merchant_id: str
) -> None:
    """Item lives under sections[].categories[].items[] and carries no
    categoryID of its own -- the outgoing upsert-item payload must carry the
    CONTAINING category's id, not "" ."""
    respx.get("https://api.grab.com/food/merchant/v2/menu").mock(
        return_value=httpx.Response(
            200,
            json={
                "sections": [
                    {
                        "categories": [
                            {
                                "categoryID": "CAT-NESTED",
                                "categoryName": "Món chính",
                                "items": [
                                    {
                                        "itemID": "ITEM1",
                                        "itemName": "Phở bò",
                                        "priceInMin": 45000,
                                        # Deliberately no "categoryID" here --
                                        # this is what /menu items usually
                                        # look like in practice.
                                    }
                                ],
                            }
                        ]
                    }
                ]
            },
        )
    )
    upsert_route = respx.post("https://api.grab.com/food/merchant/v2/upsert-item").mock(
        return_value=httpx.Response(200, json={"itemID": "ITEM1"})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        await items.set_item_availability(c, item_id="ITEM1", available=False)

    assert upsert_route.called
    payload = json.loads(upsert_route.calls[0].request.content)
    assert payload["categoryID"] == "CAT-NESTED"
    assert payload["item"]["categoryID"] == "CAT-NESTED"
    assert payload["item"]["eligibleSellingStatus"] == "INELIGIBLE"


@pytest.mark.asyncio
@respx.mock
async def test_set_item_availability_flat_menu_uses_containing_category_id(
    authn_token: str, merchant_id: str
) -> None:
    """Same regression, but for the flat `menu["categories"]` shape."""
    respx.get("https://api.grab.com/food/merchant/v2/menu").mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": [
                    {
                        "categoryID": "CAT-FLAT",
                        "categoryName": "Món chính",
                        "items": [
                            {"itemID": "ITEM1", "itemName": "Phở bò", "priceInMin": 45000}
                        ],
                    }
                ]
            },
        )
    )
    upsert_route = respx.post("https://api.grab.com/food/merchant/v2/upsert-item").mock(
        return_value=httpx.Response(200, json={"itemID": "ITEM1"})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        await items.set_item_availability(c, item_id="ITEM1", available=True)

    payload = json.loads(upsert_route.calls[0].request.content)
    assert payload["categoryID"] == "CAT-FLAT"
    assert payload["item"]["eligibleSellingStatus"] == "ELIGIBLE"


@pytest.mark.asyncio
@respx.mock
async def test_set_item_availability_item_not_found_raises(
    authn_token: str, merchant_id: str
) -> None:
    respx.get("https://api.grab.com/food/merchant/v2/menu").mock(
        return_value=httpx.Response(200, json={"categories": [], "sections": []})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(ValueError, match="not found"):
            await items.set_item_availability(c, item_id="MISSING", available=True)