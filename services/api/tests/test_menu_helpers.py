"""Tests for the menu-walking helpers in grab/endpoints/menu.py.

Regression coverage for a bug where two call sites walked only the FLAT
`menu["categories"]` wire shape and ignored the more common NESTED
`menu["sections"][].categories[].items[]` shape returned by
`/food/merchant/v2/menu` -- so on a real store the item usually wasn't
found at all. And once found, both call sites read the item's own
`categoryID` (frequently absent on `/menu` items) instead of the id of
the category that actually contained it, defaulting to `""` and
knocking the item out of its category on Grab when written back via
`upsert-item`.

These are pure-function tests: `iter_menu_categories` and
`find_item_with_category` just take a plain dict, no HTTP involved.
"""

from __future__ import annotations

from grab.endpoints.menu import find_item_with_category, iter_menu_categories


# ── iter_menu_categories ──────────────────────────────────────────────────────


def test_iter_menu_categories_flat_shape() -> None:
    menu = {
        "categories": [
            {"categoryID": "CAT1", "categoryName": "Món chính"},
            {"categoryID": "CAT2", "categoryName": "Tráng miệng"},
        ]
    }

    cats = list(iter_menu_categories(menu))

    assert [c["categoryID"] for c in cats] == ["CAT1", "CAT2"]


def test_iter_menu_categories_nested_sections_shape() -> None:
    """The `/food/merchant/v2/menu` shape most stores actually return."""
    menu = {
        "sections": [
            {
                "sectionID": "SEC1",
                "categories": [{"categoryID": "CAT1", "categoryName": "Món chính"}],
            },
            {
                "sectionID": "SEC2",
                "categories": [{"categoryID": "CAT2", "categoryName": "Tráng miệng"}],
            },
        ]
    }

    cats = list(iter_menu_categories(menu))

    assert [c["categoryID"] for c in cats] == ["CAT1", "CAT2"]


def test_iter_menu_categories_both_shapes_present() -> None:
    """A payload with both flat `categories` AND `sections` yields from both."""
    menu = {
        "categories": [{"categoryID": "FLAT1"}],
        "sections": [{"categories": [{"categoryID": "NESTED1"}]}],
    }

    cats = list(iter_menu_categories(menu))

    assert [c["categoryID"] for c in cats] == ["FLAT1", "NESTED1"]


def test_iter_menu_categories_ignores_non_dict_entries() -> None:
    """Garbage / malformed entries anywhere in the walk must not crash it."""
    menu = {
        "categories": ["not-a-dict", None, {"categoryID": "CAT1"}],
        "sections": [
            "not-a-dict-section",
            None,
            {"categories": [123, "nope", {"categoryID": "CAT2"}]},
        ],
    }

    cats = list(iter_menu_categories(menu))

    assert [c["categoryID"] for c in cats] == ["CAT1", "CAT2"]


def test_iter_menu_categories_empty_menu() -> None:
    assert list(iter_menu_categories({})) == []


# ── find_item_with_category ───────────────────────────────────────────────────


def test_find_item_with_category_nested_sections_shape_no_item_category_id() -> None:
    """The regression that matters most: an item nested under
    `sections[].categories[].items[]` with NO `categoryID` of its own must
    resolve to the CONTAINING category's id, never `""`."""
    menu = {
        "sections": [
            {
                "categories": [
                    {
                        "categoryID": "CAT-NESTED",
                        "categoryName": "Món chính",
                        "items": [
                            {"itemID": "ITEM1", "itemName": "Phở bò"},
                        ],
                    }
                ]
            }
        ]
    }

    found = find_item_with_category(menu, "ITEM1")

    assert found is not None
    item, category_id = found
    assert item["itemID"] == "ITEM1"
    assert category_id == "CAT-NESTED"
    assert category_id != ""


def test_find_item_with_category_flat_shape_no_item_category_id() -> None:
    """Same regression, but for the flat `menu["categories"]` shape."""
    menu = {
        "categories": [
            {
                "categoryID": "CAT-FLAT",
                "categoryName": "Món chính",
                "items": [
                    {"itemID": "ITEM1", "itemName": "Phở bò"},
                ],
            }
        ]
    }

    found = find_item_with_category(menu, "ITEM1")

    assert found is not None
    item, category_id = found
    assert item["itemID"] == "ITEM1"
    assert category_id == "CAT-FLAT"
    assert category_id != ""


def test_find_item_with_category_falls_back_to_item_category_id() -> None:
    """When the containing category itself carries no id, fall back to the
    item's own `categoryID` rather than emitting `""`."""
    menu = {
        "sections": [
            {
                "categories": [
                    {
                        # No "categoryID" and no "id" on the container.
                        "categoryName": "Món chính",
                        "items": [
                            {"itemID": "ITEM1", "categoryID": "CAT-FROM-ITEM"},
                        ],
                    }
                ]
            }
        ]
    }

    found = find_item_with_category(menu, "ITEM1")

    assert found is not None
    item, category_id = found
    assert category_id == "CAT-FROM-ITEM"


def test_find_item_with_category_matches_by_sku_id() -> None:
    """Some items key off `skuID` instead of `itemID`."""
    menu = {
        "categories": [
            {
                "categoryID": "CAT1",
                "items": [{"skuID": "SKU1", "itemName": "Trà sữa"}],
            }
        ]
    }

    found = find_item_with_category(menu, "SKU1")

    assert found is not None
    item, category_id = found
    assert item["skuID"] == "SKU1"
    assert category_id == "CAT1"


def test_find_item_with_category_unknown_item_returns_none() -> None:
    menu = {
        "categories": [
            {"categoryID": "CAT1", "items": [{"itemID": "ITEM1"}]},
        ],
        "sections": [
            {"categories": [{"categoryID": "CAT2", "items": [{"itemID": "ITEM2"}]}]}
        ],
    }

    assert find_item_with_category(menu, "NOPE") is None


def test_find_item_with_category_empty_menu_returns_none() -> None:
    assert find_item_with_category({}, "ITEM1") is None
