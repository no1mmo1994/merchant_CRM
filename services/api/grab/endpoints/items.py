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
    webp_urls: list[str] | None = None,
    webp_url: str | None = None,
    linked_modifier_group_ids: list[str] | None = None,
    selling_time_id: str = "AlwaysAvailable",
    item_id: str | None = None,
    eligible_selling_status: str = "ELIGIBLE",
    available_status: int = 1,
    sold_quantity: int = 0,
    sort_order: int | None = None,
    available_at: str = "0001-01-01T00:00:00.000Z",
) -> dict:
    """POST /food/merchant/v2/upsert-item — create or update a menu item.

    The payload mirrors the shape Grab's mobile app actually sends
    (verified against `Menu/monan/edit_monan.py` which the merchant
    uses for one-off edits). Earlier versions of this helper sent a
    slimmer payload that Grab's API silently rejected with 4xx — the
    full set of fields below is required, especially `priceDisplay`,
    `priceRange`, `serviceTypePriceRange`, `webPURL(s)`, `itemID`
    nested in `item`, and a top-level `categoryID`.

    `eligible_selling_status` controls whether the item is sellable on
    the storefront. Use `"ELIGIBLE"` for new / available items, or
    `"INELIGIBLE"` to hide them. Default is "ELIGIBLE" so callers
    that don't care still get a create-able item.
    """
    # Format prices as Grab expects: "1.325.000₫" with a VND dot
    # thousands separator followed by the dong sign. Grab's parser
    # accepts integers-only too, but the dotted form is what the
    # mobile app sends and the upstream rejected our int-only form.
    price_in_min = int(price_vnd)
    price_display = f"{price_in_min:,}".replace(",", ".") + "₫"

    # webP URL(s) per item. The merchant app always sends one webP
    # per JPG; if the caller doesn't know the webP variants it's
    # safe to mirror the JPG list (browsers will fall back).
    img_urls = image_urls or []
    webp_urls = webp_urls or img_urls
    webp_url = webp_url or (webp_urls[0] if webp_urls else "")

    item_block: dict = {
        # itemID lives nested under `item`, NOT as a top-level `skuID`.
        # Putting it in `skuID` made Grab reject the request with 4xx.
        "itemID": item_id or "",
        "itemName": name_vi,
        "description": description_vi,
        "priceInMin": price_in_min,
        "priceDisplay": price_display,
        "priceRange": price_display,
        "serviceTypePriceRange": {
            "DineIn": price_display,
            "Delivery": price_display,
        },
        "imageURLs": img_urls,
        "webPURLs": webp_urls,
        "webPURL": webp_url,
        "categoryID": category_id,
        "specialItemType": "",
        "nameTranslation": {
            "translation": {"ko": "", "ja": "", "en": name_en, "zh": ""},
            "originalTranslationFromDS": {},
        },
        "parentItemClassName": "",
        "itemClassName": "",
        "descriptionTranslation": {
            "translation": {"ko": "", "ja": "", "en": description_en, "zh": ""},
            "originalTranslationFromDS": {},
        },
        "linkedModifierGroupIDs": linked_modifier_group_ids or [],
        "categoryName": "",
        "soldQuantity": int(sold_quantity),
        "availableAt": available_at,
        "soldByWeight": False,
        "supportedAttributeClusterIDs": [],
        "aiGeneratedFields": [],
        "availableStatus": int(available_status),
        "sellingTimeID": selling_time_id,
        "parentItemClassID": "",
        "eligibleSellingStatus": eligible_selling_status,
        "skuID": "",
    }
    if sort_order is not None:
        item_block["sortOrder"] = int(sort_order)

    payload = {
        "item": item_block,
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
    webp_urls = list(target.get("webPURLs") or image_urls)
    webp_url = str(target.get("webPURL") or (webp_urls[0] if webp_urls else ""))
    linked_modifier_group_ids = list(target.get("linkedModifierGroupIDs") or [])
    selling_time_id = str(target.get("sellingTimeID") or "AlwaysAvailable")
    category_id = str(target.get("categoryID") or "")
    sold_quantity = int(target.get("soldQuantity") or 0)
    sort_order = target.get("sortOrder")
    available_at = str(target.get("availableAt") or "0001-01-01T00:00:00.000Z")

    return await create_or_update_item(
        client,
        name_vi=name_vi,
        name_en=name_en,
        description_vi=description_vi,
        description_en=description_en,
        price_vnd=price_vnd,
        category_id=category_id,
        image_urls=image_urls,
        webp_urls=webp_urls,
        webp_url=webp_url,
        linked_modifier_group_ids=linked_modifier_group_ids,
        selling_time_id=selling_time_id,
        item_id=item_id,
        sold_quantity=sold_quantity,
        sort_order=int(sort_order) if isinstance(sort_order, (int, float)) else None,
        available_at=available_at,
        eligible_selling_status="ELIGIBLE" if available else "INELIGIBLE",
    )
