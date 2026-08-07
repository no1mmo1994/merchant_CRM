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
    #: Weight-priced item. Hardcoded False before, which silently
    #: converted such items to unit-priced on any round-trip.
    sold_by_weight: bool = False,
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
        "soldByWeight": bool(sold_by_weight),
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


async def set_item_linked_modifier_groups(
    client: GrabClient,
    *,
    item_id: str,
    linked_modifier_group_ids: list[str],
    menu: dict | None = None,
) -> dict:
    """Replace the set of modifier groups an item offers.

    Same read-modify-write as `set_item_availability` — Grab's
    `upsert-item` takes the whole item, so we read it back out of `/menu`,
    change one field, and write it all again.

    Used for UNLINKING. Linking has a dedicated, captured endpoint
    (`link_modifier_group_to_item`) which is far cheaper; nothing
    equivalent has been captured for removal, so removal goes through the
    full item. Prefer the dedicated endpoint whenever one turns up.
    """
    return await _rewrite_item(
        client,
        item_id=item_id,
        menu=menu,
        linked_modifier_group_ids=list(linked_modifier_group_ids),
    )


async def set_item_availability(
    client: GrabClient,
    *,
    item_id: str,
    available: bool,
) -> dict:
    """Toggle the storefront availability of an existing menu item.

    On a 5xx from Grab, raises the underlying httpx error.
    """
    return await _rewrite_item(
        client,
        item_id=item_id,
        eligible_selling_status="ELIGIBLE" if available else "INELIGIBLE",
    )


async def _rewrite_item(
    client: GrabClient,
    *,
    item_id: str,
    menu: dict | None = None,
    **overrides,
) -> dict:
    """Read an item out of `/menu`, change some fields, write it back.

    Grab's `upsert-item` requires the full item payload, so changing one
    property means round-tripping all of them. Every caller that mutates
    an existing item shares this, so the reconstruction — and the
    category-resolution rule below, which is easy to get wrong and
    destructive when you do — lives in exactly one place.

    `overrides` replaces any keyword `create_or_update_item` accepts.

    Pass `menu` when the caller already holds a `/menu` payload. `/menu`
    is the heaviest response Grab serves, and a batch that rewrites N
    items would otherwise fetch it N times to read N items out of the
    same snapshot.
    """
    if not item_id:
        raise ValueError("item_id is required")

    from grab.endpoints.menu import find_item_with_category, get_full_menu

    if menu is None:
        menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        raise ValueError("menu payload from Grab was not a dict")

    # `find_item_with_category` walks both the flat `categories` list and
    # the nested `sections[].categories` shape. The old loop here only
    # walked the flat one, so on a real store — which uses the nested
    # shape — it usually found nothing and raised "item not found".
    found = find_item_with_category(menu, item_id)
    if found is None:
        raise ValueError(f"item {item_id} not found in current menu")
    target, found_category_id = found

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
    # Take the category from the category we found the item INSIDE, not
    # from the item's own `categoryID` — that field is often absent on
    # `/menu` items, and defaulting it to "" wrote an empty category back
    # through upsert-item, knocking the item out of its category on Grab.
    category_id = found_category_id or str(target.get("categoryID") or "")
    sold_quantity = int(target.get("soldQuantity") or 0)
    sort_order = target.get("sortOrder")
    available_at = str(target.get("availableAt") or "0001-01-01T00:00:00.000Z")

    fields: dict = {
        "name_vi": name_vi,
        "name_en": name_en,
        "description_vi": description_vi,
        "description_en": description_en,
        "price_vnd": price_vnd,
        "category_id": category_id,
        "image_urls": image_urls,
        "webp_urls": webp_urls,
        "webp_url": webp_url,
        "linked_modifier_group_ids": linked_modifier_group_ids,
        "selling_time_id": selling_time_id,
        "item_id": item_id,
        "sold_quantity": sold_quantity,
        "sort_order": int(sort_order) if isinstance(sort_order, (int, float)) else None,
        "available_at": available_at,
        # Preserve whatever the item already is unless the caller says
        # otherwise. Defaulting these would silently un-hide an item every
        # time someone changed an unrelated field.
        #
        # Two separate flags govern "is this item visible/sellable", and
        # BOTH have to be carried:
        #   eligibleSellingStatus — ELIGIBLE / INELIGIBLE
        #   availableStatus       — 1 available, 2/3 sold out, 7 hidden
        # `create_or_update_item` defaults availableStatus to 1, so
        # omitting it here turned every rewrite into "un-hide and mark in
        # stock". An operator who hid an item and later unticked it in the
        # topping picker would have watched it reappear on the storefront.
        "eligible_selling_status": str(
            target.get("eligibleSellingStatus") or "ELIGIBLE"
        ),
        "available_status": int(target.get("availableStatus") or 1),
        # Same reasoning: hardcoding this to False silently converts a
        # weight-priced item to unit-priced.
        "sold_by_weight": bool(target.get("soldByWeight", False)),
    }
    fields.update(overrides)
    return await create_or_update_item(client, **fields)


async def set_item_availability_status(
    client: GrabClient,
    *,
    item_id: str,
    available_status: int,
    selling_time_id: str | None = None,
) -> dict:
    """Set storefront availability via Grab's dedicated v1 endpoint.

    Mirrors `Menu/monan/bat_tatmon.py`: PUT /food/merchant/v1/items/available-status
    with ``{itemIDs: [...], availableStatus, sellingTimeID?}``. This is the
    endpoint the merchant mobile app actually calls when toggling item
    availability from the menu editor — it's lighter than upsert-item and
    preserves name/price/description automatically.

    `available_status` per Grab:
        1 = AVAILABLE (item is sellable again, listed on storefront)
        2 = OUT_OF_STOCK_TODAY (sold-out until midnight, then auto-reset;
            item stays listed in the menu, just can't be ordered)
        3 = OUT_OF_STOCK (sold-out, item stays listed in the menu, just
            can't be ordered until merchant toggles it back to 1)
        7 = HIDDEN (item disappears from customer menu entirely; merchant
            dashboard still shows it with a "ẩn giấu" badge so it stays
            editable. Verified against ``Menu/monan/hide_monan.py``.)

    `selling_time_id` is required when ``available_status == 1`` to tell
    Grab when the item is sellable again. Pass the store's existing
    selling-time ID (e.g. ``VNSLT202408290406064350``); default to the
    current item's `sellingTimeID` if omitted.
    """
    if not item_id:
        raise ValueError("item_id is required to set availability status")
    # Grab's v1 endpoint accepts 1 (AVAILABLE), 2 (OUT_OF_STOCK_TODAY),
    # 3 (OUT_OF_STOCK), and 7 (HIDDEN — verified against
    # Menu/monan/hide_monan.py).
    if available_status not in (1, 2, 3, 7):
        raise ValueError(
            f"available_status must be 1, 2, 3 or 7 (got {available_status})"
        )

    payload: dict = {
        "itemIDs": [item_id],
        "subDepartmentIDs": [],
        "departmentIDs": [],
        "availableStatus": int(available_status),
    }
    if selling_time_id:
        payload["sellingTimeID"] = selling_time_id
    elif available_status == 1:
        # The endpoint requires sellingTimeID for status=1. The merchant
        # app always supplies it; raise so the caller can fetch from menu.
        raise ValueError(
            "selling_time_id is required when available_status == 1 (AVAILABLE). "
            "Fetch the current sellingTimeID from the menu first."
        )

    res = await client.put("/food/merchant/v1/items/available-status", json=payload)
    res.raise_for_status()
    return res.json()


async def set_item_visibility(
    client: GrabClient,
    *,
    item_id: str,
    hidden: bool,
) -> dict:
    """Toggle whether an item is visible to customers on the storefront.

    Verified against ``Menu/monan/hide_monan.py`` — Grab's v1 endpoint
    ``PUT /food/merchant/v1/items/available-status`` accepts
    ``availableStatus: 7`` to mean "ẩn món hoàn toàn". The item disappears
    from the customer-facing menu entirely but the merchant dashboard still
    shows it (with a "ẩn giấu" badge) so it stays editable.

    Note: ``availableStatus=7`` is *separate* from sold-out:
        1 = AVAILABLE (sellable, listed)
        2 = OUT_OF_STOCK_TODAY (sellable in menu list, can't order today)
        3 = OUT_OF_STOCK (sellable in menu list, can't order)
        7 = HIDDEN (not in customer menu list; merchant still sees it)

    Setting ``hidden=False`` sends ``availableStatus=1`` to restore both
    visibility and sellability.

    On a 5xx from Grab, raises the underlying httpx error.
    """
    if not item_id:
        raise ValueError("item_id is required to toggle visibility")

    # 7 = HIDDEN, 1 = AVAILABLE (re-show + re-sell in one call).
    return await set_item_availability_status(
        client,
        item_id=item_id,
        available_status=7 if hidden else 1,
    )
