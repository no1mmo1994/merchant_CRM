"""Modifier router — verify modifier, create/list modifier groups."""

from __future__ import annotations

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


def _count_item_links(menu: dict[str, Any] | None, group_id: str) -> int:
    """Count how many menu items reference `group_id`.

    Walks `menu.categories[*].items[*].modifierGroups[*]` and matches
    by either `modifierGroupID` or `id`. Returns 0 when there is no
    menu data or no id to look up.
    """
    if not menu or not group_id:
        return 0
    total = 0
    for cat in menu.get("categories") or []:
        for item in (cat or {}).get("items") or []:
            for ref in (item or {}).get("modifierGroups") or []:
                if not isinstance(ref, dict):
                    continue
                rid = ref.get("modifierGroupID") or ref.get("id") or ""
                if rid == group_id:
                    total += 1
                    break
    return total


def _parse_modifier_group(
    raw: dict[str, Any],
    menu: dict[str, Any] | None = None,
) -> ModifierGroup:
    """Normalize a Grab modifier-group dict into ModifierGroup.

    When `menu` is provided, also compute `linked_item_count` by walking
    the menu tree.
    """
    raw_mods = raw.get("modifiers") or []
    modifiers = [_parse_modifier(m) for m in raw_mods if isinstance(m, dict)]
    group_id = str(raw.get("modifierGroupID") or raw.get("id") or "")
    return ModifierGroup(
        modifier_group_id=group_id,
        modifier_group_name=str(raw.get("modifierGroupName") or raw.get("name") or ""),
        selection_range_min=int(raw.get("selectionRangeMin", 0) or 0),
        selection_range_max=int(raw.get("selectionRangeMax", 1) or 1),
        modifiers=modifiers,
        linked_item_count=_count_item_links(menu, group_id),
    )


async def _groups_from_menu(client) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fallback: pull `modifierGroups` from the `/menu` payload.

    Grab's `/menu` response carries a top-level `modifierGroups` array
    (each item also references them by id, but the full list lives at the
    root). When the dedicated `/menu/modifier-groups` endpoint 502s, we
    can still recover the same data here — slightly more bytes on the
    wire, but a known-good fallback.

    Returns `(raw_groups, full_menu_payload)`. The second element lets
    the caller compute `linked_item_count` for each group by walking
    the embedded category tree.
    """
    menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        return [], None
    raw = menu.get("modifierGroups") or []
    groups = [g for g in raw if isinstance(g, dict)]
    return groups, menu


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
    fail, return an empty list with ``source="empty"`` and
    ``partial=True`` so the UI can render an explicit "no data" hint
    instead of looking like it loaded successfully with zero items.
    """
    # Primary path: dedicated modifier-groups endpoint.
    try:
        raw_groups = await list_modifier_groups(client)
        groups = [_parse_modifier_group(g) for g in raw_groups if isinstance(g, dict)]
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
