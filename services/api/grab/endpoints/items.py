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
) -> dict:
    """POST /food/merchant/v2/upsert-item — create or update a menu item.

    Granular keyword-only arguments keep call sites readable from the
    FastAPI layer. The full payload shape mirrors the original `taomon.py`.
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
            "eligibleSellingStatus": "",
            "skuID": item_id or "",
        },
        "itemAttributeValues": [],
        "categoryID": category_id,
    }
    res = await client.post("/food/merchant/v2/upsert-item", json=payload)
    res.raise_for_status()
    return res.json()
