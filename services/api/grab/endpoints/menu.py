"""Menu retrieval endpoint."""

from __future__ import annotations

from typing import Any, Iterator

from grab.client import GrabClient


def iter_menu_categories(menu: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every category in a `/menu` payload, both wire shapes.

    Grab returns categories two ways and callers keep getting bitten by
    only handling the first:

    * ``{"categories": [...]}`` — flat, what some endpoints return.
    * ``{"sections": [{"categories": [...]}, ...]}`` — nested, and the
      **more common** shape from `/food/merchant/v2/menu`.

    Walking only the flat list silently finds nothing on a real store.
    """
    for cat in menu.get("categories") or []:
        if isinstance(cat, dict):
            yield cat
    for section in menu.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for cat in section.get("categories") or []:
            if isinstance(cat, dict):
                yield cat


def category_section_map(menu: dict[str, Any]) -> dict[str, str]:
    """Map each category id to the id of the section that holds it.

    Categories in the flat `categories` list belong to no section and map
    to `""`, which is what Grab's sort endpoint expects for a menu that
    has none — the shape `Menu/danhmuc/get_sapxepdanhmuc.py` was captured
    against, and the shape this store still has.

    A menu organised into `sections` is the other half of the split
    `iter_menu_categories` exists for. Sending `sectionID: ""` for those
    categories tells Grab to reorder a section that does not exist, which
    is exactly the kind of difference that makes one account's reorder
    work and another's fail while the code looks account-agnostic.
    """
    if not isinstance(menu, dict):
        # Grab answering `null` or a bare list would otherwise raise
        # `AttributeError` here — an uncaught 500 on the very path added to
        # stop reorders returning 500.
        return {}

    mapping: dict[str, str] = {}
    for cat in menu.get("categories") or []:
        if isinstance(cat, dict):
            cat_id = str(cat.get("categoryID") or cat.get("id") or "")
            if cat_id:
                mapping[cat_id] = ""
    for section in menu.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("sectionID") or section.get("id") or "")
        for cat in section.get("categories") or []:
            if isinstance(cat, dict):
                cat_id = str(cat.get("categoryID") or cat.get("id") or "")
                if cat_id:
                    mapping[cat_id] = section_id
    return mapping


def find_item_with_category(
    menu: dict[str, Any],
    item_id: str,
) -> tuple[dict[str, Any], str] | None:
    """Locate a menu item and the id of the category that CONTAINS it.

    Returns `(item, category_id)` or `None` when the item isn't in the
    menu.

    The category id comes from the containing category, not from the
    item's own `categoryID` field. That field is frequently absent on
    `/menu` items, and callers that read it were falling back to `""` —
    which then went out in the `upsert-item` payload as the item's new
    category and moved the item out of its category on Grab. The
    enclosing category is authoritative and always known here, because
    finding the item means we walked into it. The item's own field is
    kept only as a last resort.

    Raises:
        ValueError: if neither the containing category nor the item
            carries an id. Returning `""` here would hand callers the
            very value this function exists to stop them writing back to
            Grab, and it would do it silently. Failing is recoverable;
            an item quietly losing its category is not.
    """
    for cat in iter_menu_categories(menu):
        cat_id = str(cat.get("categoryID") or cat.get("id") or "")
        for item in cat.get("items") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("itemID") or item.get("skuID") or "") == item_id:
                resolved = cat_id or str(item.get("categoryID") or "")
                if not resolved:
                    raise ValueError(
                        f"item {item_id} was found in the menu but neither "
                        "its category nor the item itself carries a category "
                        "id; refusing to write an empty categoryID back to "
                        "Grab"
                    )
                return item, resolved
    return None


async def get_full_menu(client: GrabClient) -> dict:
    """GET /food/merchant/v2/menu — full menu tree.

    The `orderID` and `oosItemID` query parameters are kept empty by
    default; they only matter when validating an in-flight order.
    """
    res = await client.get(
        "/food/merchant/v2/menu",
        params={"orderID": "", "oosItemID": ""},
    )
    res.raise_for_status()
    return res.json()
