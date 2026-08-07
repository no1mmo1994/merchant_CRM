"""Modifier (topping) endpoints."""

from __future__ import annotations

import logging

import httpx

from grab.client import GrabClient

log = logging.getLogger("pulseorder.grab.modifiers")


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


def _group_payload(
    *,
    modifier_group_id: str,
    group_name_vi: str,
    group_name_en: str,
    selection_range_min: int,
    selection_range_max: int,
    modifiers: list[dict],
    is_flexible_quantity_enabled: bool,
) -> dict:
    """Build the `{"modifierGroup": {...}}` body for v3/modifier-groups.

    Create-shaped: every modifier carries a `nameTranslation` and the
    group carries one too. `modifier_group_id` is "" here because a
    create has no id yet.

    Editing uses `_update_group_payload` instead, which is deliberately
    NOT this shape — see that function.
    """
    mods_payload = [
        {
            "nameTranslation": _translation(m["name_en"]),
            "priceInMin": int(m["price"]),
            # Hardcoded, not read from the caller: a create has no
            # pre-existing options, so a real `modifierID` here would
            # always be a mistake. Letting one through is the exact shape
            # that made Grab duplicate a group once already — see
            # `update_modifier_group`. Edits go through
            # `_update_group_payload`, which does honour real ids.
            "modifierID": "",
            "modifierName": m["name_vi"],
        }
        for m in modifiers
    ]
    return {
        "modifierGroup": {
            "selectionRangeMin": selection_range_min,
            "isFlexibleQuantityEnabled": is_flexible_quantity_enabled,
            "nameTranslation": _translation(group_name_en),
            "selectionRangeMax": selection_range_max,
            "modifierGroupName": group_name_vi,
            "modifiers": mods_payload,
            "modifierGroupID": modifier_group_id,
        }
    }


def _update_group_payload(
    *,
    modifier_group_id: str,
    group_name_vi: str,
    selection_range_min: int,
    selection_range_max: int,
    modifiers: list[dict],
    is_flexible_quantity_enabled: bool,
) -> dict:
    """Build the edit body, mirroring captured app traffic byte for byte.

    Source: `donhang/suagia_taomon_xoamon.py`, a capture of the Grab
    Merchant app adding an option to an existing group. Two things in it
    differ from the create shape and both are deliberate here:

      * **No group-level `nameTranslation`.** The app simply doesn't send
        one when editing.
      * **No per-modifier `nameTranslation` on options that already
        exist.** Only the brand-new option carries one; the kept ones are
        just `{priceInMin, modifierID, modifierName}`.

    We follow the capture rather than "improving" on it, because the last
    time this code deviated from proven traffic Grab silently created a
    duplicate group on a live store.

    The practical consequence: renaming an existing option updates its
    Vietnamese `modifierName` but leaves the stored English translation
    at its old value, exactly as the app behaves. It also means editing a
    group costs zero translation round-trips for kept options — only
    genuinely new ones need translating.

    `modifiers` is a FULL replacement of the group's option list: an
    option the caller omits is deleted, one with an empty `modifier_id`
    is created, and one with a real id is updated in place. That is how a
    single PUT covers add, edit and remove.
    """
    mods_payload: list[dict] = []
    for m in modifiers:
        mid = str(m.get("modifier_id") or "")
        entry: dict = {
            "priceInMin": int(m["price"]),
            "modifierID": mid,
            "modifierName": m["name_vi"],
        }
        if not mid:
            # Grab needs a translation to mint a new option. Kept options
            # already have one stored on Grab's side.
            entry["nameTranslation"] = _translation(m.get("name_en") or m["name_vi"])
        mods_payload.append(entry)
    return {
        "modifierGroup": {
            "selectionRangeMin": selection_range_min,
            "isFlexibleQuantityEnabled": is_flexible_quantity_enabled,
            "selectionRangeMax": selection_range_max,
            "modifierGroupName": group_name_vi,
            "modifiers": mods_payload,
            "modifierGroupID": modifier_group_id,
        }
    }


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
    payload = _group_payload(
        modifier_group_id="",
        group_name_vi=group_name_vi,
        group_name_en=group_name_en,
        selection_range_min=selection_range_min,
        selection_range_max=selection_range_max,
        modifiers=modifiers,
        is_flexible_quantity_enabled=is_flexible_quantity_enabled,
    )
    res = await client.post("/food/merchant/v3/modifier-groups", json=payload)
    res.raise_for_status()
    return res.json()


async def update_modifier_group(
    client: GrabClient,
    *,
    modifier_group_id: str,
    group_name_vi: str,
    selection_range_min: int,
    selection_range_max: int,
    modifiers: list[dict],
    is_flexible_quantity_enabled: bool = False,
) -> dict:
    """PUT /food/merchant/v3/modifier-groups/{id} — edit a group in place.

    **Captured traffic**, not inference: `donhang/suagia_taomon_xoamon.py`
    records the Grab Merchant app adding an option to an existing group
    via exactly this method, path and body, answered with 204 No Content.

    One PUT covers all three option operations, because `modifiers` is a
    full replacement of the list:

      * **edit**  — keep the option's `modifier_id`, change name or price
      * **add**   — include an option with an empty `modifier_id`
      * **remove**— leave the option out of the list entirely

    That is also why every kept option must be sent back on every edit.
    The capture spells it out: "CÁC TÙY CHỌN CŨ ĐÃ CÓ (BẮT BUỘC PHẢI
    TRUYỀN LẠI)".

    Getting here took two wrong turns worth recording. First we reused
    the v3 create endpoint with a non-empty `modifierGroupID`, assuming
    it upserted; against the live store it CREATED A SECOND GROUP
    (`VNMOG2024100714445088676` → minted `VNMOG2026080710193865881`) and
    the router's duplicate guard had to roll it back. Then we guessed
    `PUT` on the **v2** path, by analogy with delete
    (`DELETE /food/merchant/v2/modifier-groups/{id}` → 204, verified
    live). The capture says v3. The version split is real: create is v3,
    edit is v3, delete is v2.

    The router's duplicate guard stays in place even now — it costs
    little and it is the only thing standing between a future Grab
    behaviour change and a silently duplicated menu.
    """
    payload = _update_group_payload(
        modifier_group_id=modifier_group_id,
        group_name_vi=group_name_vi,
        selection_range_min=selection_range_min,
        selection_range_max=selection_range_max,
        modifiers=modifiers,
        is_flexible_quantity_enabled=is_flexible_quantity_enabled,
    )
    res = await client.put(
        f"/food/merchant/v3/modifier-groups/{modifier_group_id}",
        json=payload,
    )
    res.raise_for_status()
    # 204 No Content is the documented success answer — there is no body
    # to parse, and no id echoed back.
    if res.status_code == 204 or not (res.content or b"").strip():
        return {}
    try:
        return res.json()
    except ValueError:
        return {}


async def delete_modifier_group(
    client: GrabClient,
    *,
    modifier_group_id: str,
) -> None:
    """DELETE /food/merchant/v2/modifier-groups/{id} — remove a group.

    Note the version split: creating a group is v3 (see
    `create_modifier_group`) but deleting one is **v2**. That is not a
    typo — it matches the request the Grab Merchant Android app actually
    sends, captured in `donhang/xoatuychonnhom.py`.

    Grab answers a successful delete with **204 No Content**, so there is
    no body to parse and nothing useful to return. Grab also wants an
    empty JSON object as the request body rather than no body at all.

    Deleting a group that is still linked to menu items is allowed by
    Grab — the items simply lose the group. The caller is responsible for
    warning the operator first (the list endpoint already computes
    `linked_item_count` for exactly this purpose).

    Raises:
        httpx.HTTPStatusError: on any non-2xx, so the router can map
            Grab's status onto a structured response.
    """
    res = await client.delete(
        f"/food/merchant/v2/modifier-groups/{modifier_group_id}",
        json={},
    )
    res.raise_for_status()


async def link_modifier_group_to_item(
    client: GrabClient,
    *,
    modifier_group_id: str,
    item_id: str,
) -> None:
    """POST /food/merchant/v2/item-modifier-groups — attach a group to one item.

    Captured from the Merchant app in `donhang/lienkettuychon.py`: one
    request per item, `{itemID, modifierGroupID}`, answered 204.

    Grab answers **409 when the pair is already linked**. That is not an
    error the operator needs to see — re-linking is a no-op — so the
    router treats it as success. Every other status raises.
    """
    res = await client.post(
        "/food/merchant/v2/item-modifier-groups",
        json={"itemID": item_id, "modifierGroupID": modifier_group_id},
    )
    res.raise_for_status()


async def unlink_modifier_group_from_item(
    client: GrabClient,
    *,
    modifier_group_id: str,
    item_id: str,
    menu: dict | None = None,
) -> None:
    """Detach a group from one item by rewriting the item's linked list.

    ⚠️ No captured traffic exists for unlinking. There is no known
    counterpart to `POST /item-modifier-groups`, so this goes the long way
    round: read the item out of `/menu`, drop `modifier_group_id` from its
    `linkedModifierGroupIDs`, and write the whole item back through
    `upsert-item`.

    That is the same read-modify-write shape `set_item_availability`
    already uses, on an endpoint this codebase exercises constantly — so
    the mechanism is proven even though this particular use of it is not.
    The cost is real though: it rewrites every field of the item, so a
    field that round-trips badly corrupts more than the link. Prefer a
    captured DELETE if one ever turns up.

    A no-op when the item does not reference the group.

    Pass `menu` when unlinking a batch: without it this fetches the whole
    menu once to find the item and the rewrite fetches it AGAIN, so
    N items cost 2N reads of Grab's largest payload.
    """
    from grab.endpoints.items import set_item_linked_modifier_groups
    from grab.endpoints.menu import find_item_with_category, get_full_menu

    if menu is None:
        menu = await get_full_menu(client)
    found = find_item_with_category(menu, item_id) if isinstance(menu, dict) else None
    if found is None:
        raise ValueError(f"item {item_id} not found in current menu")
    item, _ = found

    current = [str(g) for g in (item.get("linkedModifierGroupIDs") or [])]
    if modifier_group_id not in current:
        return
    await set_item_linked_modifier_groups(
        client,
        item_id=item_id,
        menu=menu,
        linked_modifier_group_ids=[g for g in current if g != modifier_group_id],
    )


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
