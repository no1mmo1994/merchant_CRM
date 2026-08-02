"""Modifier router — verify modifier, create/list modifier groups."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

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
from grab.endpoints.modifiers import (
    create_modifier_group,
    list_modifier_groups,
    verify_modifier,
)

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


def _parse_modifier_group(raw: dict[str, Any]) -> ModifierGroup:
    """Normalize a Grab modifier-group dict into ModifierGroup."""
    raw_mods = raw.get("modifiers") or []
    modifiers = [_parse_modifier(m) for m in raw_mods if isinstance(m, dict)]
    return ModifierGroup(
        modifier_group_id=str(raw.get("modifierGroupID") or raw.get("id") or ""),
        modifier_group_name=str(raw.get("modifierGroupName") or raw.get("name") or ""),
        selection_range_min=int(raw.get("selectionRangeMin", 0) or 0),
        selection_range_max=int(raw.get("selectionRangeMax", 1) or 1),
        modifiers=modifiers,
    )


@router.get("", response_model=ListModifierGroupsResponse)
@router.get("/", response_model=ListModifierGroupsResponse)
async def list_groups(
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> ListModifierGroupsResponse:
    """List every modifier group on the active store.

    Pulls from Grab's `/food/merchant/v2/menu/modifier-groups` endpoint so
    the dashboard can show the full inventory regardless of which menu
    item the groups are attached to.
    """
    raw_groups = await list_modifier_groups(client)
    groups = [_parse_modifier_group(g) for g in raw_groups if isinstance(g, dict)]
    return ListModifierGroupsResponse(modifier_groups=groups, total=len(groups))


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
