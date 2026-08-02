"""Tests for category endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from grab.client import GrabClient
from grab.endpoints import categories


@pytest.mark.asyncio
@respx.mock
async def test_translate_name(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v1/menu-translations").mock(
        return_value=httpx.Response(
            200,
            json={"textTranslation": {"en": "Main Course"}},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await categories.translate_name(c, "Món chính", entity="category")

    assert result == "Main Course"
    # Verify the payload included the entity field. Encode the UTF-8 string
    # at runtime because Python bytes literals are ASCII-only.
    body = respx.calls[0].request.content
    assert b'"entity":"category"' in body
    assert '"text":"Món chính"'.encode("utf-8") in body


@pytest.mark.asyncio
@respx.mock
async def test_create_category(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v2/categories").mock(
        return_value=httpx.Response(
            200,
            json={"categoryID": "NEWCAT", "name": "Món chính"},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await categories.create_category(c, "Món chính", "Main Course")

    assert data["categoryID"] == "NEWCAT"
    body = respx.calls[0].request.content
    assert '"name":"Món chính"'.encode("utf-8") in body
    assert b'"en":"Main Course"' in body


@pytest.mark.asyncio
@respx.mock
async def test_delete_category(authn_token: str, merchant_id: str) -> None:
    respx.delete("https://api.grab.com/food/merchant/v2/categories/CAT1").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await categories.delete_category(c, "CAT1")

    assert data == {"deleted": True}


@pytest.mark.asyncio
@respx.mock
async def test_delete_category_empty_body(authn_token: str, merchant_id: str) -> None:
    respx.delete("https://api.grab.com/food/merchant/v2/categories/CAT1").mock(
        return_value=httpx.Response(204, content=b"")
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await categories.delete_category(c, "CAT1")

    assert data is None


@pytest.mark.asyncio
@respx.mock
async def test_sort_categories(authn_token: str, merchant_id: str) -> None:
    respx.put("https://api.grab.com/food/merchant/categories-sort").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await categories.sort_categories(
            c,
            sorts=[
                {"resourceID": "CAT1", "sortOrder": 3},
                {"resourceID": "CAT2", "sortOrder": 2},
                {"resourceID": "CAT3", "sortOrder": 1},
            ],
        )

    assert data == {"ok": True}
    body = respx.calls[0].request.content
    assert b'"sectionID":""' in body
    assert b'"resourceID":"CAT1"' in body