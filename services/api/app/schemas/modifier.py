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


class ModifierGroup(BaseModel):
    """A group of related modifier options (e.g. 'Topping', 'Size').

    Mirrors Grab's `modifierGroups` array under each item:
      { modifierGroupID, modifierGroupName, selectionRangeMin,
        selectionRangeMax, modifiers: [...] }
    """

    modifier_group_id: str = ""
    modifier_group_name: str = ""
    selection_range_min: int = 0
    selection_range_max: int = 1
    modifiers: list[ModifierOption] = []


class ListModifierGroupsResponse(BaseModel):
    """Wrapper for the full store-wide modifier-group list."""

    modifier_groups: list[ModifierGroup] = []
    total: int = 0
