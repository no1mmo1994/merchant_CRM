"""Pydantic schemas for modifier endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ModifierSpec(BaseModel):
    name: str
    name_en: str = ""
    price_vnd: int
    #: Grab's own id for an already-existing modifier. Empty means "this
    #: is a new option, let Grab mint an id". On update this MUST be
    #: echoed back for every option the operator kept, otherwise Grab
    #: treats them as new: the old ones are dropped and recreated with
    #: fresh ids, which silently breaks any order history or item linkage
    #: pointing at the previous ids. Ignored on create (nothing exists
    #: yet), so the field is safe to carry on the shared spec.
    modifier_id: str = ""


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


class UpdateModifierGroupRequest(BaseModel):
    """Body for editing an existing group.

    Same shape as create minus the id (which travels in the path). The
    `modifiers` list is a full replacement, not a delta: whatever the
    operator left in the editor is the group's new content. Options the
    operator kept must carry their `modifier_id` so Grab updates them in
    place instead of dropping and recreating them — see `ModifierSpec`.
    """

    group_name: str
    selection_range_min: int = 0
    selection_range_max: int = 1
    modifiers: list[ModifierSpec] = []


class UpdateModifierGroupResponse(BaseModel):
    modifier_group_id: str
    modifier_group_name: str
    #: False when the server could not confirm Grab edited in place
    #: rather than creating a duplicate — the group listing was
    #: unreadable, or the before/after snapshots came from different
    #: Grab surfaces and diffing them would be meaningless. The write
    #: itself succeeded; only the duplicate check was skipped. Surfacing
    #: it beats silently implying a verification that never ran.
    verified: bool = True


class LinkModifierGroupItemsRequest(BaseModel):
    """The full set of menu items that should offer this group.

    A desired state, not a delta: items missing from the list get
    unlinked. That mirrors the picker UI, where the operator ticks and
    unticks a list and presses save once.
    """

    item_ids: list[str] = []


class LinkModifierGroupItemsResponse(BaseModel):
    """Per-item outcome of reconciling the link set.

    Reported per item rather than as one flag because Grab is asked once
    per item and any of them can fail on its own — a partial result is
    the normal case, not an exception, and the operator needs to know
    which items actually changed.
    """

    modifier_group_id: str
    linked: list[str] = []
    unlinked: list[str] = []
    #: Already in the requested state; no request was made for these.
    unchanged: list[str] = []
    #: `{item_id: reason}` for items Grab rejected.
    failed: dict[str, str] = {}
    #: False when Grab refused the menu edit lock. The writes were still
    #: attempted — see `acquire_menu_edit_lock` — but a 409 here is more
    #: likely, so say the lock was missing rather than let it look
    #: inexplicable.
    lock_acquired: bool = True


class DeleteModifierGroupResponse(BaseModel):
    """Confirmation for a deleted group.

    Shaped like the category-delete response (`{"deleted": true}`) plus
    the id, so the client can reconcile optimistically. Deliberately does
    NOT re-report `linked_item_count`: the list endpoint already computed
    it for the row the operator is looking at, so warning them "9 món sẽ
    mất nhóm này" is a client-side concern and re-deriving it here would
    cost two extra Grab round-trips per delete.
    """

    modifier_group_id: str
    deleted: bool = True


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
