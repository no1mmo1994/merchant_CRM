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
    DeleteModifierGroupResponse,
    ListModifierGroupsResponse,
    ModifierGroup,
    ModifierGroupCategoryLink,
    ModifierOption,
    UpdateModifierGroupRequest,
    UpdateModifierGroupResponse,
    VerifyModifierRequest,
)
from grab.endpoints.categories import translate_name
from grab.endpoints.menu import get_full_menu
from grab.endpoints.modifiers import (
    create_modifier_group,
    delete_modifier_group,
    list_modifier_groups,
    update_modifier_group,
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


def _groups_in_menu(menu: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pull the `modifierGroups` array out of an already-fetched `/menu`.

    Grab's `/menu` response carries a top-level `modifierGroups` array
    (each item also references them by id, but the full list lives at the
    root), so it can stand in for the dedicated endpoint when that 502s.

    Split out from `_groups_from_menu` so a caller holding a menu payload
    can reuse it instead of paying for the heaviest request Grab serves a
    second time.
    """
    if not isinstance(menu, dict):
        return []
    return [g for g in (menu.get("modifierGroups") or []) if isinstance(g, dict)]


async def _groups_from_menu(client) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fetch `/menu` and pull `modifierGroups` out of it.

    Returns `(raw_groups, full_menu_payload)`. The second element lets
    the caller compute `linked_item_count` and `linked_categories` for
    each group by walking the embedded category tree.

    Prefer `_groups_in_menu` when a menu payload is already in hand.
    """
    menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        return [], None
    return _groups_in_menu(menu), menu


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
    # Collect the parallel `/menu` fetch we already started. This used to
    # await it purely to avoid a dangling task and THROW THE RESULT AWAY,
    # then the fallback below fetched `/menu` all over again — two copies
    # of the heaviest payload Grab serves, on every single list, because
    # the dedicated endpoint 502s on this store 100% of the time.
    menu: dict[str, Any] | None = None
    try:
        menu = await menu_task
    except Exception:  # pragma: no cover - best effort
        menu = None

    # Fallback path: derive the groups from that same menu payload. The
    # 502 we just saw from `/menu/modifier-groups` is usually
    # upstream-flaky, not per-store; `/menu` is the more frequently-cached
    # endpoint and almost always succeeds.
    try:
        if menu is None:
            # The parallel fetch failed too — this is the only branch that
            # still costs a request, and it is the retry it looks like.
            raw_groups, menu = await _groups_from_menu(client)
        else:
            raw_groups = _groups_in_menu(menu)
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

    # Before translating: every name below costs a Grab round-trip, and a
    # group whose selection window doesn't fit its option list is going to
    # be rejected regardless. Failing here keeps a doomed create from
    # paying for N translations first.
    range_error = _selection_range_error(
        selection_range_min=body.selection_range_min,
        selection_range_max=body.selection_range_max,
        option_count=len(body.modifiers),
    )
    if range_error is not None:
        raise range_error

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

    try:
        result = await create_modifier_group(
            client,
            group_name_vi=body.group_name,
            group_name_en=group_name_en,
            selection_range_min=body.selection_range_min,
            selection_range_max=body.selection_range_max,
            modifiers=modifiers_payload,
        )
    except httpx.HTTPStatusError as exc:
        raise _grab_write_error(exc, what="modifier-group create") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="modifier-group create") from exc

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


def _selection_range_error(
    *,
    selection_range_min: int,
    selection_range_max: int,
    option_count: int,
) -> HTTPException | None:
    """Reject a selection window Grab would reject anyway, but clearly.

    Grab enforces this server-side and answers 409 with
    `target: "InvalidRange"` — but its `reason` field says
    "already_exists", which reads as a name clash and is what sent an
    operator chasing the wrong fix for hours. Checking here means the
    operator gets the real sentence, pointed at the real field, without a
    round-trip.

    The rule that bit us: after deleting an option, `selectionRangeMax`
    still exceeded the number of options left (max 8, 7 options). You
    cannot offer "choose up to 8" from a list of 7.

    ⚠️ The `max > count` rule is INFERRED from that single incident, not
    from documentation. That matters because the two ways of being wrong
    are not symmetric. Too loose and the request reaches Grab, which
    rejects it and `_grab_write_error` labels it correctly — self-
    correcting. Too strict and we block a write Grab would have accepted,
    and because the request never leaves the process, nothing surfaces
    it. So every rejection here is logged: if these lines show up for
    shapes that look legitimate, the rule needs revisiting.
    """
    if option_count <= 0:
        return HTTPException(
            status_code=422,
            detail={
                "code": "modifier_group_empty",
                "message": "Nhóm tùy chọn phải có ít nhất một tùy chọn.",
                "fields": ["modifiers"],
            },
        )
    if selection_range_max > option_count:
        log.info(
            "selection range rejected locally: max=%s > options=%s (min=%s) "
            "— inferred rule, see docstring",
            selection_range_max, option_count, selection_range_min,
        )
        return HTTPException(
            status_code=422,
            detail={
                "code": "modifier_group_invalid_range",
                "message": (
                    f"\"Chọn tối đa\" ({selection_range_max}) lớn hơn số tùy "
                    f"chọn trong nhóm ({option_count}). Giảm \"Chọn tối đa\" "
                    f"xuống tối đa {option_count} rồi lưu lại."
                ),
                "fields": ["selection_range_max"],
            },
        )
    if selection_range_min > selection_range_max:
        return HTTPException(
            status_code=422,
            detail={
                "code": "modifier_group_invalid_range",
                "message": (
                    f"\"Chọn tối thiểu\" ({selection_range_min}) lớn hơn "
                    f"\"Chọn tối đa\" ({selection_range_max})."
                ),
                "fields": ["selection_range_min"],
            },
        )
    return None


def _grab_write_error(exc: httpx.HTTPStatusError, *, what: str) -> HTTPException:
    """Turn a Grab write failure into a structured HTTPException.

    Without this every Grab 4xx bubbled out of `raise_for_status()` as an
    unhandled `httpx.HTTPStatusError`, which FastAPI renders as a bare
    500 plus a stack trace — the operator saw "thất bại" with no reason
    and the actual cause only existed in the server log. Observed for
    real on create: Grab answers 409 when a group name is already taken,
    and the dashboard reported it as an internal error.

    Grab's body is logged in full but only a short, non-sensitive slice
    reaches the client, matching the decision in `list_groups`.

    Read Grab's `target`/`message`, do NOT infer the cause from the status
    alone. This function used to map every 409 to "duplicate name", which
    was wrong and actively harmful: Grab answers an out-of-range
    selection window with 409 too, carrying
    `{"target":"InvalidRange","reason":"already_exists","message":
    "Modifier group range is invalid"}`. The `reason` there says
    "already_exists" while the real cause is the range — so the operator
    was told to rename a group whose name was fine, and the actual
    problem (max selection larger than the number of options) stayed
    invisible.
    """
    status_code = exc.response.status_code
    body = (exc.response.text or "").strip()[:500]
    log.warning("Grab %s rejected: %s — %s", what, status_code, body)

    target = ""
    grab_message = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            target = str(payload.get("target") or "")
            grab_message = str(payload.get("message") or "")
    except ValueError:
        pass
    # Match `target` exactly and treat the message only as a backup.
    # `target` is Grab's enum-ish field, far less likely to drift than
    # prose, and `items.py::_grab_error_message` already reads this same
    # envelope that way (`target == "ErrImageAspectRatioNotValid"` or a
    # message substring) — worth staying consistent with. Merging both
    # fields into one blob and substring-matching, as this did first,
    # only happened to work because "InvalidRange" contains "range".
    is_range_error = target == "InvalidRange" or "range" in grab_message.lower()

    if status_code == 409 and is_range_error:
        return HTTPException(
            status_code=409,
            detail={
                "code": "grab_modifier_group_invalid_range",
                "message": (
                    "Grab từ chối vì khoảng chọn không hợp lệ. "
                    "\"Chọn tối đa\" không được lớn hơn số tùy chọn trong "
                    "nhóm — sau khi xóa bớt tùy chọn, hãy giảm \"Chọn tối "
                    "đa\" cho khớp rồi lưu lại."
                ),
                "fields": ["selection_range_max"],
                "grab_status": status_code,
                "grab_body": body,
            },
        )
    if status_code == 409:
        return HTTPException(
            status_code=409,
            detail={
                "code": "grab_modifier_group_conflict",
                "message": (
                    "Grab từ chối vì trùng: đã có nhóm tùy chọn tên này "
                    "trên cửa hàng. Đổi tên khác rồi thử lại."
                ),
                "fields": ["group_name"],
                "grab_status": status_code,
                "grab_body": body,
            },
        )
    if status_code == 404:
        return HTTPException(
            status_code=404,
            detail={
                "code": "grab_modifier_group_not_found",
                "message": (
                    "Không tìm thấy nhóm tùy chọn này trên Grab. "
                    "Có thể nhóm đã bị xóa ở nơi khác — tải lại danh sách."
                ),
                "grab_status": status_code,
                "grab_body": body,
            },
        )
    if status_code >= 500:
        return HTTPException(
            status_code=502,
            detail={
                "code": "grab_upstream_error",
                "message": "Grab đang gặp sự cố. Thử lại sau ít phút.",
                "grab_status": status_code,
                "grab_body": body,
            },
        )
    return HTTPException(
        status_code=502,
        detail={
            "code": "grab_modifier_group_rejected",
            "message": f"Grab từ chối thao tác (HTTP {status_code}).",
            "grab_status": status_code,
            "grab_body": body,
        },
    )


def _grab_unreachable(exc: httpx.HTTPError, *, what: str) -> HTTPException:
    """Transport-level failure talking to Grab (DNS, connect, timeout).

    `_grab_write_error` only handles `HTTPStatusError` — a response that
    arrived and was bad. A connection that never completed is a different
    subclass and used to escape all three write routes as an unhandled
    exception, i.e. the bare 500 with no reason that this whole error
    layer exists to eliminate. `items.py` already separates the two; this
    keeps modifier writes consistent with it.
    """
    log.warning("Grab %s unreachable: %r", what, exc)
    return HTTPException(
        status_code=502,
        detail={
            "code": "grab_unreachable",
            "message": (
                "Không kết nối được tới Grab. Kiểm tra mạng rồi thử lại."
            ),
            "grab_status": 0,
            "grab_body": "",
        },
    )


async def _known_groups(client) -> tuple[dict[str, str], str] | None:
    """Snapshot every modifier-group id Grab currently reports.

    Returns `({id: name}, source)`, or `None` — not an empty mapping —
    when the list could not be read at all, so callers can tell "no
    groups" apart from "we don't know". Names come back too because the
    update guard needs them to tell a duplicate of ITS OWN write apart
    from a group some other operator created at the same moment.

    `source` is `"direct"` or `"menu_fallback"` and is load-bearing for
    the update guard: the dedicated endpoint 502s often (that is why
    `list_groups` has a fallback at all), so two snapshots taken minutes
    apart can easily come from different Grab surfaces. Diffing across
    surfaces is meaningless — a group missing from one payload shape but
    present in the other looks exactly like a group that was just
    created. The guard therefore only trusts a diff when both snapshots
    came from the same source.
    """
    try:
        raw = await list_modifier_groups(client)
        source = "direct"
    except httpx.HTTPError:
        try:
            raw, _ = await _groups_from_menu(client)
            source = "menu_fallback"
        except httpx.HTTPError:
            return None
    by_id: dict[str, str] = {}
    for g in raw:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("modifierGroupID") or g.get("id") or "")
        if not gid:
            continue
        by_id[gid] = str(g.get("modifierGroupName") or g.get("name") or "")
    return by_id, source


@router.put("/groups/{group_id}", response_model=UpdateModifierGroupResponse)
async def update_group(
    group_id: str,
    body: UpdateModifierGroupRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> UpdateModifierGroupResponse:
    """Edit an existing modifier group.

    `modifiers` is a full replacement of the group's options. Options the
    operator kept must carry their `modifier_id`; new ones leave it empty
    and Grab mints an id.

    ⚠️ Guarded write, and the guard has already earned its keep: an
    earlier implementation reused the v3 *create* endpoint with a
    non-empty `modifierGroupID`, assuming it upserted. Against the live
    store it CREATED A SECOND GROUP (editing `VNMOG2024100714445088676`
    minted `VNMOG2026080710193865881`) and this check deleted the stray.
    The endpoint is now captured traffic rather than a guess (see
    `update_modifier_group`), so the guard is insurance against Grab
    changing behaviour, not a crutch for a hypothesis.

    Because it is insurance, it is cheap: **one** group-list read AFTER
    the write, counting how many groups carry the name we just submitted.

      * exactly one  → Grab edited in place. Done.
      * more than one → Grab made a copy. Any same-named group that is
        not `group_id` is the stray; delete it and fail loudly.
      * list unreadable → `verified=False`, no deletions, write stands.

    The previous design diffed a before-snapshot against an after-snapshot
    and was replaced deliberately. It cost two reads instead of one; the
    captured PUT answers 204 so the response never carries an id, meaning
    the cheap response-id check could never fire and the expensive diff
    ran every time; and the diff produced false positives that could
    DELETE REAL DATA — the group under edit if Grab's list lagged, or
    another operator's group created in the window, or anything at all
    when the two snapshots happened to come from different Grab surfaces
    (this store's dedicated list endpoint 502s constantly, so the menu
    fallback fires often and mixed sources were routine). Counting
    same-named groups in a single snapshot has none of those failure
    modes.
    """
    from app.deps import write_audit_log

    range_error = _selection_range_error(
        selection_range_min=body.selection_range_min,
        selection_range_max=body.selection_range_max,
        option_count=len(body.modifiers),
    )
    if range_error is not None:
        raise range_error

    # Only brand-new options need translating. The captured edit payload
    # carries no group-level `nameTranslation` and none on options that
    # already exist — Grab keeps the stored translation for those. Doing
    # it this way also avoids one Grab round-trip per option: a 10-option
    # group used to cost 11 translation calls on every single save.
    modifiers_payload: list[dict[str, Any]] = []
    for spec in body.modifiers:
        name_en = ""
        if not spec.modifier_id:
            name_en = spec.name_en or (await translate_name(client, spec.name))
        modifiers_payload.append(
            {
                "name_vi": spec.name,
                "name_en": name_en,
                "price": spec.price_vnd,
                "modifier_id": spec.modifier_id,
            }
        )

    try:
        result = await update_modifier_group(
            client,
            modifier_group_id=group_id,
            group_name_vi=body.group_name,
            selection_range_min=body.selection_range_min,
            selection_range_max=body.selection_range_max,
            modifiers=modifiers_payload,
        )
    except httpx.HTTPStatusError as exc:
        raise _grab_write_error(exc, what="modifier-group update") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="modifier-group update") from exc

    duplicates: set[str] = set()
    verified = True
    returned_id = str(result.get("modifierGroupID") or result.get("groupID") or "")
    if returned_id and returned_id != group_id:
        # Cheap check, no extra request: if Grab ever starts echoing an id
        # and it isn't the one we asked it to edit, that is a create.
        # The captured PUT answers 204 so this never fires today; it costs
        # nothing and would catch a behaviour change immediately.
        duplicates = {returned_id}
    else:
        after = await _known_groups(client)
        if after is None:
            # Grab's group list is unreadable right now. The write already
            # landed; we simply cannot confirm it. Say so rather than
            # guessing, and never delete on a guess.
            verified = False
        else:
            submitted_name = body.group_name.strip()
            # A duplicate of THIS write is a group that carries the name we
            # just submitted and is not the group we edited. Restricting to
            # the submitted name is what keeps another operator's unrelated
            # new group out of the rollback set; excluding `group_id` is
            # what stops us deleting the very thing being edited.
            duplicates = {
                gid
                for gid, gname in after[0].items()
                if gid != group_id and gname.strip() == submitted_name
            }
            if len(duplicates) > 1:
                # Two or more same-named strays is not a shape this write
                # can produce. Something else is going on (a pre-existing
                # duplicate name, a concurrent bulk import). Deleting
                # several groups on that basis is worse than reporting it.
                log.error(
                    "modifier_group.update for %s (user=%s): %d same-named "
                    "groups found (%s) — refusing to auto-delete",
                    group_id, user.id, len(duplicates), sorted(duplicates),
                )
                duplicates = set()
                verified = False

    if duplicates:
        log.error(
            "modifier_group.update created duplicates instead of editing "
            "%s for user=%s: %s — rolling back",
            group_id, user.id, sorted(duplicates),
        )
        rolled_back, failed = [], []
        for dup_id in sorted(duplicates):
            try:
                await delete_modifier_group(client, modifier_group_id=dup_id)
                rolled_back.append(dup_id)
            except httpx.HTTPError as exc:
                # Surface the orphan id — an operator can delete it by
                # hand, but only if we tell them it exists.
                log.error("rollback of duplicate %s failed: %r", dup_id, exc)
                failed.append(dup_id)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_modifier_group_update_unsupported",
                "message": (
                    "Grab tạo nhóm mới thay vì sửa nhóm cũ, nên thao tác đã "
                    "được hoàn tác. Nhóm cũ giữ nguyên, chưa có gì thay đổi."
                    if not failed
                    else
                    "Grab tạo nhóm mới thay vì sửa nhóm cũ và không hoàn tác "
                    f"được. Vui lòng xóa thủ công nhóm: {', '.join(failed)}."
                ),
                "rolled_back": rolled_back,
                "rollback_failed": failed,
            },
        )

    write_audit_log(
        session=session,
        user_id=user.id,
        action="modifier_group.update",
        entity_type="modifier_group",
        entity_id=group_id,
        payload={
            "group_name_vi": body.group_name,
            "modifier_count": len(body.modifiers),
        },
    )

    if not verified:
        log.warning(
            "modifier_group.update for %s (user=%s) could not be verified — "
            "group listing unavailable or snapshots came from different "
            "sources; duplicate check skipped",
            group_id, user.id,
        )

    return UpdateModifierGroupResponse(
        modifier_group_id=group_id,
        modifier_group_name=body.group_name,
        verified=verified,
    )


@router.delete("/groups/{group_id}", response_model=DeleteModifierGroupResponse)
async def delete_group(
    group_id: str,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> DeleteModifierGroupResponse:
    """Delete a modifier group.

    Grab allows deleting a group that menu items still reference — the
    items just lose it. Warning the operator is the client's job; the
    list endpoint already gives it `linked_item_count` for that.
    """
    from app.deps import write_audit_log

    try:
        await delete_modifier_group(client, modifier_group_id=group_id)
    except httpx.HTTPStatusError as exc:
        raise _grab_write_error(exc, what="modifier-group delete") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="modifier-group delete") from exc

    write_audit_log(
        session=session,
        user_id=user.id,
        action="modifier_group.delete",
        entity_type="modifier_group",
        entity_id=group_id,
        payload={},
    )

    return DeleteModifierGroupResponse(modifier_group_id=group_id, deleted=True)
