"""Pydantic schemas for modifier endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ModifierSpec(BaseModel):
    name: str
    name_en: str = ""
    price_vnd: int


class VerifyModifierRequest(BaseModel):
    name: str
    name_en: str = ""
    price_vnd: int


class CreateModifierGroupRequest(BaseModel):
    group_name: str
    selection_range_min: int = 0
    selection_range_max: int = 1
    modifiers: list[ModifierSpec] = []


class CreateModifierGroupResponse(BaseModel):
    modifier_group_id: str
    modifier_group_name: str


class ModifierOption(BaseModel):
    """A single modifier (topping choice) inside a group.

    Mirrors the structure from Grab's response:
      { modifierID, modifierName, priceDisplay, isNeedExtraCost,
        availableStatus, sortOrder, quantity, priceInMin, priceRange, ... }
    """

    modifier_id: str = ""
    modifier_name: str = ""
    price_display: str | None = None
    price_vnd: int = 0
    is_need_extra_cost: bool = False
    available_status: int | None = None
    sort_order: int = 0
    quantity: int = 0
    max_modifier_selection_quantity: int | None = None


class ModifierGroupCategoryLink(BaseModel):
    """A category that a modifier group is attached to.

    `item_count` is how many items in that category reference the group
    (one group can be reused across categories — `linked_item_count` on
    `ModifierGroup` is the sum across all categories). Both fields are
    optional / empty when the menu tree wasn't available at parse time
    (which only happens on the direct endpoint when we skip the menu
    fetch — see the router for when this fires).
    """

    category_id: str = ""
    category_name: str = ""
    item_count: int = 0


class ModifierGroup(BaseModel):
    """A group of related modifier options (e.g. 'Topping', 'Size').

    Mirrors Grab's `modifierGroups` array under each item:
      { modifierGroupID, modifierGroupName, selectionRangeMin,
        selectionRangeMax, modifiers: [...] }

    `linked_item_count` is computed by walking the menu's category tree
    and counting how many items reference this group (so the UI can
    render "Liên kết với X món"). `linked_categories` carries the same
    walk but per-category, so the UI can render "Thuộc: Phở (cat-001),
    Bún (cat-002)" instead of the previous meaningless "Nguồn:
    menu_fallback" badge when the modifier was discovered via the
    `/menu` fallback path.
    """

    modifier_group_id: str = ""
    modifier_group_name: str = ""
    selection_range_min: int = 0
    selection_range_max: int = 1
    modifiers: list[ModifierOption] = []
    linked_item_count: int = 0
    linked_categories: list[ModifierGroupCategoryLink] = []


class ListModifierGroupsResponse(BaseModel):
    """Wrapper for the full store-wide modifier-group list.

    `partial` is true when the list was assembled from a fallback path
    (e.g. dedupe of menu-embedded modifier groups) instead of Grab's
    authoritative `/menu/modifier-groups` endpoint. `source` is a
    short tag for the UI to render an info hint: `"direct"`,
    `"menu_fallback"`, or `"empty"`.
    """

    modifier_groups: list[ModifierGroup] = []
    total: int = 0
    partial: bool = False
    source: str = "direct"
