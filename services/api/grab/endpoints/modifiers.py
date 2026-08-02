"""Modifier (topping) endpoints."""

from __future__ import annotations

from grab.client import GrabClient


def _translation(en: str) -> dict:
    """Build the standard nameTranslation payload with EN filled in."""
    return {
        "translation": {"ko": "", "ja": "", "en": en, "zh": ""},
        "originalTranslationFromDS": {"en": en},
    }


async def verify_modifier(
    client: GrabClient,
    *,
    name_vi: str,
    name_en: str,
    price_vnd: int,
) -> dict:
    """POST /food/merchant/v2/verify-modifier — pre-flight check before create."""
    payload = {
        "modifier": {
            "nameTranslation": _translation(name_en),
            "priceInMin": int(price_vnd),
            "modifierName": name_vi,
        }
    }
    res = await client.post("/food/merchant/v2/verify-modifier", json=payload)
    res.raise_for_status()
    return res.json()


async def create_modifier_group(
    client: GrabClient,
    *,
    group_name_vi: str,
    group_name_en: str,
    selection_range_min: int,
    selection_range_max: int,
    modifiers: list[dict],
    is_flexible_quantity_enabled: bool = False,
) -> dict:
    """POST /food/merchant/v3/modifier-groups — create a modifier group.

    `modifiers` is a list of `{name_vi, name_en, price}` dicts; the
    function translates them into the full Grab payload internally.
    """
    mods_payload = [
        {
            "nameTranslation": _translation(m["name_en"]),
            "priceInMin": int(m["price"]),
            "modifierID": "",
            "modifierName": m["name_vi"],
        }
        for m in modifiers
    ]
    payload = {
        "modifierGroup": {
            "selectionRangeMin": selection_range_min,
            "isFlexibleQuantityEnabled": is_flexible_quantity_enabled,
            "nameTranslation": _translation(group_name_en),
            "selectionRangeMax": selection_range_max,
            "modifierGroupName": group_name_vi,
            "modifiers": mods_payload,
            "modifierGroupID": "",
        }
    }
    res = await client.post("/food/merchant/v3/modifier-groups", json=payload)
    res.raise_for_status()
    return res.json()


async def list_modifier_groups(client: GrabClient) -> list[dict]:
    """GET /food/merchant/v2/menu/modifier-groups — list all modifier groups.

    Returns the raw `modifierGroups` array from Grab. The full menu
    endpoint also embeds these under each item's `modifierGroups` key,
    but the dedicated endpoint gives us the authoritative store-wide list.
    """
    res = await client.get("/food/merchant/v2/menu/modifier-groups")
    res.raise_for_status()
    data = res.json()
    # Response shape: { "modifierGroups": [...] } or just a bare list
    if isinstance(data, list):
        return data
    return data.get("modifierGroups") or data.get("groups") or []
