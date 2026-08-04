"""Modifier router — verify modifier, create/list modifier groups."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_grab_client, get_session, require_user
from app.models import User
from app.schemas import (
    CreateModifierGroupRequest,
    CreateModifierGroupResponse,
    ListModifierGroupsResponse,
    ModifierGroup,
    ModifierGroupCategoryLink,
    ModifierOption,
    VerifyModifierRequest,
)
from grab.endpoints.categories import translate_name
from grab.endpoints.menu import get_full_menu
from grab.endpoints.modifiers import (
    create_modifier_group,
    list_modifier_groups,
    verify_modifier,
)

log = logging.getLogger("pulseorder.modifiers")

router = APIRouter(prefix="/api/modifiers", tags=["modifiers"])


def _parse_modifier(raw: dict[str, Any]) -> ModifierOption:
    """Normalize a single modifier dict from Grab into ModifierOption."""
    return ModifierOption(
        modifier_id=str(raw.get("modifierID") or raw.get("id") or ""),
        modifier_name=str(raw.get("modifierName") or raw.get("name") or ""),
        price_display=raw.get("priceDisplay"),
        price_vnd=int(raw.get("priceInMin") or raw.get("price") or 0),
        is_need_extra_cost=bool(raw.get("isNeedExtraCost", False)),
        available_status=raw.get("availableStatus"),
        sort_order=int(raw.get("sortOrder", 0) or 0),
        quantity=int(raw.get("quantity", 0) or 0),
        max_modifier_selection_quantity=raw.get("maxModifierSelectionQuantity"),
    )


def _item_references_group(item: dict[str, Any], group_id: str) -> bool:
    """Return True iff a menu `item` references `group_id`.

    Grab's menu wire format puts the linkage as a flat string array on
    each item: ``linkedModifierGroupIDs: ["MOG1", "MOG2", ...]`` (see
    ``services/api/grab/models.py:MenuItem.linked_modifier_group_ids``
    for the canonical schema). The dashboard was previously walking
    ``item.modifierGroups[]`` (a list of objects) which never exists on
    real payloads, so ``linked_item_count`` always came back as 0 and
    ``category_id`` showed empty — exactly the bug the operator
    reported. We accept both shapes for safety:

      * flat string list — ``linkedModifierGroupIDs: ["MOG1", ...]``
      * object list —     ``modifierGroups: [{modifierGroupID: "MOG1"}]``
        (older / internal payloads, keep a fast-fail fallback so we
        still surface something useful if Grab ever switches shape).
    """
    # Shape A — flat string list (the actual Grab wire format).
    linked_ids = item.get("linkedModifierGroupIDs")
    if isinstance(linked_ids, list):
        for rid in linked_ids:
            if isinstance(rid, str) and rid == group_id:
                return True
            # Tolerate dicts inside the list (defensive — shouldn't
            # happen, but a single rogue entry shouldn't blank the
            # whole category count).
            if isinstance(rid, dict):
                ref_id = rid.get("modifierGroupID") or rid.get("id") or ""
                if ref_id == group_id:
                    return True

    # Shape B — object list (legacy / future-proof).
    nested = item.get("modifierGroups")
    if isinstance(nested, list):
        for ref in nested:
            if not isinstance(ref, dict):
                continue
            rid = ref.get("modifierGroupID") or ref.get("id") or ""
            if rid == group_id:
                return True

    return False


def _iter_menu_categories(menu: dict[str, Any]):
    """Yield every category dict inside the `/menu` payload.

    Grab returns categories in two shapes (see
    ``services/api/grab/models.py:Menu``):

    * ``{"categories": [...]}`` — flat top-level list (some endpoints).
    * ``{"sections": [{"categories": [...]}, ...]}`` — nested under
      sections (most common in `/food/merchant/v2/menu`). Without the
      nested walk we'd silently miss every category and the dashboard
      would always render "Liên kết với 0 món" — exactly the bug the
      operator reported on the "Topping lẻ" group.
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


def _linked_categories_for_group(
    menu: dict[str, Any] | None,
    group_id: str,
) -> tuple[int, list[ModifierGroupCategoryLink]]:
    """Walk the menu tree to compute, for one group:
      * total item-link count across all categories
      * per-category breakdown (category_id, category_name, item_count).

    Returns `(0, [])` when no menu data is available. Used both by the
    primary endpoint path (now also fetches the menu) and the `/menu`
    fallback path so the UI can render "Thuộc: Phở (cat-001), Bún
    (cat-002) · 9 món" instead of the meaningless "Nguồn:
    menu_fallback" tag.
    """
    if not menu or not group_id:
        return 0, []
    total = 0
    links: list[ModifierGroupCategoryLink] = []
    for cat in _iter_menu_categories(menu):
        cat_id = str(cat.get("categoryID") or cat.get("id") or "")
        cat_name = str(cat.get("categoryName") or cat.get("name") or "")
        cat_count = 0
        for item in cat.get("items") or []:
            if not isinstance(item, dict):
                continue
            if _item_references_group(item, group_id):
                cat_count += 1
        if cat_count > 0:
            links.append(ModifierGroupCategoryLink(
                category_id=cat_id,
                category_name=cat_name,
                item_count=cat_count,
            ))
            total += cat_count
    # Sort by descending item count so the most-used category surfaces first.
    links.sort(key=lambda l: (-l.item_count, l.category_name))
    return total, links


def _count_item_links(menu: dict[str, Any] | None, group_id: str) -> int:
    """Count how many menu items reference `group_id`.

    Thin wrapper around `_linked_categories_for_group` — kept for
    readability of the call site in `_parse_modifier_group`.
    """
    total, _ = _linked_categories_for_group(menu, group_id)
    return total


def _parse_modifier_group(
    raw: dict[str, Any],
    menu: dict[str, Any] | None = None,
) -> ModifierGroup:
    """Normalize a Grab modifier-group dict into ModifierGroup.

    When `menu` is provided, also compute:
      * `linked_item_count` — total items that reference this group
      * `linked_categories` — per-category breakdown (id, name, count)
    so the UI can show "Thuộc: <CategoryName> (<CategoryID>) · N món"
    in place of the previous meaningless "Nguồn: menu_fallback" badge.
    """
    raw_mods = raw.get("modifiers") or []
    modifiers = [_parse_modifier(m) for m in raw_mods if isinstance(m, dict)]
    group_id = str(raw.get("modifierGroupID") or raw.get("id") or "")
    total, links = _linked_categories_for_group(menu, group_id)
    return ModifierGroup(
        modifier_group_id=group_id,
        modifier_group_name=str(raw.get("modifierGroupName") or raw.get("name") or ""),
        selection_range_min=int(raw.get("selectionRangeMin", 0) or 0),
        selection_range_max=int(raw.get("selectionRangeMax", 1) or 1),
        modifiers=modifiers,
        linked_item_count=total,
        linked_categories=links,
    )


async def _groups_from_menu(client) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fallback: pull `modifierGroups` from the `/menu` payload.

    Grab's `/menu` response carries a top-level `modifierGroups` array
    (each item also references them by id, but the full list lives at the
    root). When the dedicated `/menu/modifier-groups` endpoint 502s, we
    can still recover the same data here — slightly more bytes on the
    wire, but a known-good fallback.

    Returns `(raw_groups, full_menu_payload)`. The second element lets
    the caller compute `linked_item_count` and `linked_categories` for
    each group by walking the embedded category tree.
    """
    menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        return [], None
    raw = menu.get("modifierGroups") or []
    groups = [g for g in raw if isinstance(g, dict)]
    return groups, menu


async def _try_get_menu(client) -> dict[str, Any] | None:
    """Best-effort fetch of `/menu` for `linked_categories` augmentation.

    Returns `None` on any failure so the caller can fall back to
    zero-counts without breaking the response. Used by the primary
    `/menu/modifier-groups` path to add category info without waiting
    on the fallback path.
    """
    try:
        menu = await get_full_menu(client)
        return menu if isinstance(menu, dict) else None
    except httpx.HTTPError as exc:
        log.debug("modifier_groups: /menu fetch for augmentation failed: %r", exc)
        return None


@router.get("", response_model=ListModifierGroupsResponse)
@router.get("/", response_model=ListModifierGroupsResponse)
async def list_groups(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> ListModifierGroupsResponse:
    """List every modifier group on the active store.

    Tries Grab's authoritative `/menu/modifier-groups` first. If that
    endpoint 4xx/5xx or the network drops, fall back to deduping
    `modifierGroups` out of the full `/menu` payload. If both paths
    fail, return a structured 502 so the UI can toast instead of
    silently showing zero items.

    Either way we also fetch `/menu` (in parallel with the primary
    call) so every group carries `linked_item_count` and
    `linked_categories` — the dashboard "Liên kết với X món" tile and
    "Thuộc: <CategoryName> · <ID>" line need real numbers, not zeros.
    """
    # Primary path: dedicated modifier-groups endpoint. Kick off the
    # `/menu` fetch in parallel so we don't add latency.
    menu_task = asyncio.create_task(_try_get_menu(client))
    try:
        raw_groups = await list_modifier_groups(client)
        menu = await menu_task
        groups = [_parse_modifier_group(g, menu) for g in raw_groups if isinstance(g, dict)]
        return ListModifierGroupsResponse(
            modifier_groups=groups, total=len(groups), partial=False, source="direct",
        )
    except httpx.HTTPStatusError as exc:
        grab_status = exc.response.status_code
        grab_body = exc.response.text[:500]
        log.warning(
            "Grab /menu/modifier-groups rejected for user=%s: %s — %s",
            user.id, grab_status, grab_body,
        )
    except httpx.HTTPError as exc:
        grab_status = 0
        grab_body = ""
        log.warning("Grab /menu/modifier-groups transport error: %r", exc)
    # The menu_task may still be in flight — let it finish or cancel.
    if not menu_task.done():
        try:
            await menu_task
        except Exception:  # pragma: no cover - best effort
            pass

    # Fallback path: re-use the menu payload. The 502 we just saw from
    # `/menu/modifier-groups` is usually upstream-flaky, not per-store;
    # `/menu` is the more frequently-cached endpoint and almost always
    # succeeds.
    try:
        raw_groups, menu = await _groups_from_menu(client)
        groups = [_parse_modifier_group(g, menu) for g in raw_groups]
        log.info(
            "modifier_groups: used /menu fallback for user=%s — %d groups",
            user.id, len(groups),
        )
        return ListModifierGroupsResponse(
            modifier_groups=groups, total=len(groups), partial=True, source="menu_fallback",
        )
    except httpx.HTTPStatusError as exc:
        grab_status = exc.response.status_code
        grab_body = exc.response.text[:500]
        log.warning("Grab /menu fallback also failed: %s — %s", grab_status, grab_body)
    except httpx.HTTPError as exc:
        log.warning("Grab /menu fallback transport error: %r", exc)

    # Both paths failed. Surface a structured 502 with a clear message so
    # the UI can toast instead of silently showing zero items.
    raise HTTPException(
        status_code=502,
        detail={
            "code": "grab_modifier_groups_unavailable",
            "grab_status": grab_status,
            "message": (
                "Grab đang gặp sự cố — không tải được nhóm tùy chọn. "
                "Thử lại sau ít phút."
            ),
            "grab_body": grab_body,
        },
    )


@router.post("/verify")
async def verify(
    body: VerifyModifierRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> dict[str, bool]:
    """Pre-flight check: verify a modifier name + price with Grab."""
    await verify_modifier(
        client,
        name_vi=body.name,
        name_en=body.name_en,
        price_vnd=body.price_vnd,
    )
    return {"ok": True}


@router.post("/groups", response_model=CreateModifierGroupResponse)
@router.post("/groups/", response_model=CreateModifierGroupResponse)
async def create_group(
    body: CreateModifierGroupRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> CreateModifierGroupResponse:
    """Create a modifier group.

    Modifier names are auto-translated VI -> EN server-side.
    """
    from app.deps import write_audit_log

    # Translate group name
    group_name_en = await translate_name(client, body.group_name)

    # Translate each modifier name
    modifiers_payload: list[dict[str, Any]] = []
    for spec in body.modifiers:
        name_en = spec.name_en or (await translate_name(client, spec.name))
        modifiers_payload.append(
            {
                "name_vi": spec.name,
                "name_en": name_en,
                "price": spec.price_vnd,
            }
        )

    result = await create_modifier_group(
        client,
        group_name_vi=body.group_name,
        group_name_en=group_name_en,
        selection_range_min=body.selection_range_min,
        selection_range_max=body.selection_range_max,
        modifiers=modifiers_payload,
    )

    group_id: str = result.get("modifierGroupID", result.get("groupID", ""))
    write_audit_log(
        session=session,
        user_id=user.id,
        action="modifier_group.create",
        entity_type="modifier_group",
        entity_id=group_id,
        payload={"group_name_vi": body.group_name},
    )

    return CreateModifierGroupResponse(
        modifier_group_id=group_id,
        modifier_group_name=body.group_name,
    )
