"""Menu item endpoints (image upload, upsert)."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from grab.client import GrabClient


_SUPPORTED_IMAGE_EXTS = {"png", "jpg", "jpeg"}


def _normalise_image_ext(path: str | os.PathLike) -> str:
    """Map the source file's extension to the {png|jpg} values Grab expects."""
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "jpeg":
        return "jpg"
    if ext in _SUPPORTED_IMAGE_EXTS:
        return ext
    # Fall back to jpg — Grab rejects unknown image types.
    return "jpg"


async def upload_image(client: GrabClient, image_path: str | os.PathLike) -> str | None:
    """POST /food/merchant/v2/upload-file — base64-encode and upload a local image.

    Returns the hosted URL on success, or None if the upload failed.
    """
    path = Path(image_path)
    if not path.exists():
        return None

    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    ext = _normalise_image_ext(path)

    res = await client.post(
        "/food/merchant/v2/upload-file",
        json={
            "file": {"data": encoded, "type": ext},
            "category": "menu_item_img",
        },
    )
    res.raise_for_status()
    data = res.json()
    return data.get("url") or data.get("imageURL") or data.get("temporaryURL")


async def create_or_update_item(
    client: GrabClient,
    *,
    name_vi: str,
    name_en: str,
    description_vi: str = "",
    description_en: str = "",
    price_vnd: int,
    category_id: str,
    image_urls: list[str] | None = None,
    linked_modifier_group_ids: list[str] | None = None,
    selling_time_id: str = "AlwaysAvailable",
    item_id: str | None = None,
    eligible_selling_status: str = "",
) -> dict:
    """POST /food/merchant/v2/upsert-item — create or update a menu item.

    Granular keyword-only arguments keep call sites readable from the
    FastAPI layer. The full payload shape mirrors the original `taomon.py`.

    `eligible_selling_status` controls whether the item is sellable on
    the storefront. Grab accepts an empty string (default = unchanged)
    or one of `"AVAILABLE"` / `"OUT_OF_STOCK"`. When updating only
    availability, callers should pass the existing item fields back in
    alongside the new status.
    """
    payload = {
        "item": {
            "specialItemType": "",
            "nameTranslation": {
                "translation": {"ko": "", "ja": "", "en": name_en, "zh": ""},
                "originalTranslationFromDS": {"en": name_en},
            },
            "descriptionTranslation": {
                "translation": {"ko": "", "ja": "", "en": description_en, "zh": ""},
                "originalTranslationFromDS": {"en": description_en},
            },
            "description": description_vi,
            "linkedModifierGroupIDs": linked_modifier_group_ids or [],
            "itemName": name_vi,
            "soldByWeight": False,
            "aiGeneratedFields": [],
            "priceInMin": int(price_vnd),
            "imageURLs": image_urls or [],
            "sellingTimeID": selling_time_id,
            "eligibleSellingStatus": eligible_selling_status,
            "skuID": item_id or "",
        },
        "itemAttributeValues": [],
        "categoryID": category_id,
    }
    res = await client.post("/food/merchant/v2/upsert-item", json=payload)
    res.raise_for_status()
    return res.json()


async def set_item_availability(
    client: GrabClient,
    *,
    item_id: str,
    available: bool,
) -> dict:
    """Toggle the storefront availability of an existing menu item.

    Grab's upsert-item endpoint requires the full item payload, so we
    have to fetch the existing item first via /menu, mutate only the
    availability flag, and write it back. This keeps name/price/desc
    unchanged while flipping `eligibleSellingStatus`.

    On a 5xx from Grab, raises the underlying httpx error.
    """
    if not item_id:
        raise ValueError("item_id is required to toggle availability")

    from grab.endpoints.menu import get_full_menu

    menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        raise ValueError("menu payload from Grab was not a dict")

    target: dict | None = None
    for cat in menu.get("categories") or []:
        for item in (cat or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("itemID") or item.get("skuID") or "") == item_id:
                target = item
                break
        if target is not None:
            break

    if target is None:
        raise ValueError(f"item {item_id} not found in current menu")

    name_vi = str(target.get("itemName") or target.get("name") or "")
    name_en = (
        ((target.get("nameTranslation") or {}).get("translation") or {}).get("en")
        or name_vi
    )
    description_vi = str(target.get("description") or "")
    description_en = (
        ((target.get("descriptionTranslation") or {}).get("translation") or {})
        .get("en")
        or description_vi
    )
    price_vnd = int(target.get("priceInMin") or target.get("price") or 0)
    image_urls = list(target.get("imageURLs") or [])
    linked_modifier_group_ids = list(target.get("linkedModifierGroupIDs") or [])
    selling_time_id = str(target.get("sellingTimeID") or "AlwaysAvailable")
    category_id = str(target.get("categoryID") or "")

    return await create_or_update_item(
        client,
        name_vi=name_vi,
        name_en=name_en,
        description_vi=description_vi,
        description_en=description_en,
        price_vnd=price_vnd,
        category_id=category_id,
        image_urls=image_urls,
        linked_modifier_group_ids=linked_modifier_group_ids,
        selling_time_id=selling_time_id,
        item_id=item_id,
        eligible_selling_status="AVAILABLE" if available else "OUT_OF_STOCK",
    )
