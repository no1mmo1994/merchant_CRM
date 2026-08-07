"""Tests for modifier endpoints."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi import HTTPException

from app.models import AuditLog, User
from app.routers.modifiers import (
    _selection_range_error,
    create_group,
    delete_group,
    update_group,
)
from app.schemas import (
    CreateModifierGroupRequest,
    ModifierSpec,
    UpdateModifierGroupRequest,
)
from grab.client import GrabClient
from grab.endpoints import modifiers


@pytest.mark.asyncio
@respx.mock
async def test_verify_modifier(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v2/verify-modifier").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await modifiers.verify_modifier(
            c, name_vi="Thêm trứng", name_en="Extra egg", price_vnd=5000
        )

    assert data == {"ok": True}
    body = respx.calls[0].request.content
    assert '"modifierName":"Thêm trứng"'.encode("utf-8") in body
    assert b'"priceInMin":5000' in body


@pytest.mark.asyncio
@respx.mock
async def test_create_modifier_group(authn_token: str, merchant_id: str) -> None:
    respx.post("https://api.grab.com/food/merchant/v3/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={"modifierGroupID": "MOG1", "modifierGroupName": "Topping"},
        )
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        data = await modifiers.create_modifier_group(
            c,
            group_name_vi="Topping",
            group_name_en="Topping",
            selection_range_min=0,
            selection_range_max=2,
            modifiers=[
                {"name_vi": "Thêm trứng", "name_en": "Extra egg", "price": 5000},
                {"name_vi": "Thêm phô mai", "name_en": "Extra cheese", "price": 8000},
            ],
        )

    assert data["modifierGroupID"] == "MOG1"
    body = respx.calls[0].request.content
    assert b'"modifierGroupName":"Topping"' in body
    assert b'"selectionRangeMin":0' in body
    assert b'"selectionRangeMax":2' in body
    assert '"modifierName":"Thêm trứng"'.encode("utf-8") in body
    assert '"modifierName":"Thêm phô mai"'.encode("utf-8") in body


# ── DELETE /api/modifiers/groups/{id} ────────────────────────────────────────────
#
# These call the router coroutines directly (bypassing FastAPI's DI, same as
# the tests above call grab.endpoints.modifiers directly) so we can exercise
# `_grab_write_error` / the duplicate-guard rollback logic without spinning up
# a full TestClient. `user`/`client`/`session` are plain keyword args that
# override the `Depends(...)` defaults.


@pytest.mark.asyncio
@respx.mock
async def test_delete_modifier_group_happy_path(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab 204 -> router returns 200 {deleted: true}; must hit v2, not v3
    (delete is v2 while create is v3 -- not a typo, see delete_modifier_group)."""
    user = User(username="delete-happy@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    route = respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG1"
    ).mock(return_value=httpx.Response(204))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await delete_group("MOG1", user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.deleted is True
    assert route.called
    req = route.calls[0].request
    assert req.url.path == "/food/merchant/v2/modifier-groups/MOG1"
    assert req.content == b"{}"

    logs = db_session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].action == "modifier_group.delete"


@pytest.mark.asyncio
@respx.mock
async def test_delete_modifier_group_not_found_maps_404(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab 404 -> structured HTTP 404, not an unhandled 500."""
    user = User(username="delete-404@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG404"
    ).mock(return_value=httpx.Response(404, json={"message": "not found"}))

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await delete_group("MOG404", user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "grab_modifier_group_not_found"


# ── PUT /api/modifiers/groups/{id} ───────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_happy_path_same_id(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab's PUT succeeds with 204 No Content -- the documented common
    case (update_modifier_group returns {} rather than parsing a body
    that isn't there). A 204 means no id is echoed, so the guard reads
    the group list exactly ONCE, after the write (this is the whole
    point of the single-snapshot redesign -- the old before/after diff
    cost two reads per edit); since group_id is the only entry and gets
    excluded from candidates, that must NOT be treated as a duplicate ->
    200, no rollback DELETE. Also pins the modifierID forwarding: a kept
    option carries its real modifier_id, a brand-new option sends "" ."""
    user = User(username="update-happy@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    list_route = respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    update_route = respx.put(
        "https://api.grab.com/food/merchant/v3/modifier-groups/MOG1"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        selection_range_min=0,
        selection_range_max=2,
        modifiers=[
            ModifierSpec(
                name="Thêm trứng", name_en="Extra egg", price_vnd=5000,
                modifier_id="MOD-KEPT-1",
            ),
            ModifierSpec(name="Thêm phô mai", name_en="Extra cheese", price_vnd=8000),
        ],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.verified is True
    assert not any(call.request.method == "DELETE" for call in respx.calls)
    assert update_route.called
    assert list_route.call_count == 1

    payload = json.loads(update_route.calls[0].request.content)
    group = payload["modifierGroup"]
    assert group["modifierGroupID"] == "MOG1"
    mods = group["modifiers"]
    assert mods[0]["modifierID"] == "MOD-KEPT-1"
    assert mods[1]["modifierID"] == ""

    logs = db_session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].action == "modifier_group.update"


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_duplicate_by_response_id_rolls_back(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab hands back a DIFFERENT modifierGroupID than we asked it to edit
    -- that's a silent CREATE, not an update. The route must delete the
    ghost group and fail with 502 grab_modifier_group_update_unsupported."""
    user = User(username="update-dup-response@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(200, json={"modifierGroupID": "MOG-NEW-DUP"})
    )
    delete_route = respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG-NEW-DUP"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert delete_route.called
    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_update_unsupported"
    assert detail["rolled_back"] == ["MOG-NEW-DUP"]
    assert detail["rollback_failed"] == []


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_duplicate_detected_by_same_name_rolls_back(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab's update response carries no id at all (the ordinary 204
    shape) -> the guard reads the group list exactly ONCE, after the
    write, and counts groups carrying the submitted name. A stray with
    that name (never `group_id` itself) means Grab made a copy instead
    of editing in place; delete the stray and fail loudly."""
    user = User(username="update-dup-samename@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    list_route = respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={
                "modifierGroups": [
                    {"modifierGroupID": "MOG1", "modifierGroupName": "Topping"},
                    {"modifierGroupID": "MOG-GHOST", "modifierGroupName": "Topping"},
                ]
            },
        )
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )
    delete_route = respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG-GHOST"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert list_route.call_count == 1
    assert delete_route.called
    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_update_unsupported"
    assert detail["rolled_back"] == ["MOG-GHOST"]
    assert detail["rollback_failed"] == []


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_rollback_failure_reports_id(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """If the rollback DELETE of the duplicate itself fails, the route must
    still 502, and the orphan id must show up in rollback_failed so an
    operator can clean it up by hand."""
    user = User(username="update-rollback-fail@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(200, json={"modifierGroupID": "MOG-FAIL-DUP"})
    )
    respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG-FAIL-DUP"
    ).mock(return_value=httpx.Response(500, text="boom"))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_update_unsupported"
    assert detail["rolled_back"] == []
    assert detail["rollback_failed"] == ["MOG-FAIL-DUP"]


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_404_maps_not_found(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Grab 404 on the v3 edit PUT -> structured HTTP 404 via
    _grab_write_error, not an unhandled 500 and not silently reported as
    success. (Captured traffic settled the version question -- edit is
    v3 only now, no 404/405 fallback loop.)"""
    user = User(username="update-404@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "grab_modifier_group_not_found"


# ── captured-payload shape (donhang/suagia_taomon_xoamon.py) ─────────────────────
#
# Real captured app traffic disproved the v2-PUT guess: edit is v3, and the
# edit body is NOT the create body with an id filled in -- it deliberately
# omits nameTranslation at the group level, and per-option, only a brand-new
# option (empty modifier_id) carries one. Kept options are just
# {priceInMin, modifierID, modifierName}. These tests pin that shape and the
# translation-call-count win it buys (zero round-trips for kept options).


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_payload_matches_captured_shape(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """No group-level nameTranslation at all; an existing option (real
    modifier_id) is exactly {priceInMin, modifierID, modifierName} with no
    nameTranslation; a brand-new option (empty modifier_id) carries
    modifierID: "" plus a nameTranslation. Also proves the call-count win:
    one new option costs exactly one translate_name round-trip."""
    user = User(username="update-payload-shape@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    translate_route = respx.post(
        "https://api.grab.com/food/merchant/v1/menu-translations"
    ).mock(return_value=httpx.Response(200, json={"textTranslation": {"en": "Extra cheese"}}))
    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    update_route = respx.put(
        "https://api.grab.com/food/merchant/v3/modifier-groups/MOG1"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[
            ModifierSpec(name="Thêm trứng", modifier_id="MOD-KEPT-1", price_vnd=5000),
            # No name_en supplied -- forces the router to actually call
            # translate_name for this brand-new option.
            ModifierSpec(name="Thêm phô mai", price_vnd=8000),
        ],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert len(translate_route.calls) == 1

    payload = json.loads(update_route.calls[0].request.content)
    group = payload["modifierGroup"]
    assert "nameTranslation" not in group

    existing, new = group["modifiers"]
    assert existing == {
        "priceInMin": 5000,
        "modifierID": "MOD-KEPT-1",
        "modifierName": "Thêm trứng",
    }
    assert new["modifierID"] == ""
    assert "nameTranslation" in new
    assert new["nameTranslation"]["translation"]["en"] == "Extra cheese"


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_no_translate_calls_when_all_options_existing(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Every option in the request already has a real modifier_id -> zero
    translate_name round-trips. A 10-option group used to cost 11
    translation calls per save; kept options now cost none. The
    translate endpoint is deliberately left UNMOCKED: `assert_all_mocked`
    (respx default) means a regression that calls it anyway blows up the
    request instead of silently passing."""
    user = User(username="update-zero-translate@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[
            ModifierSpec(name="Thêm trứng", modifier_id="MOD-A", price_vnd=5000),
            ModifierSpec(name="Thêm phô mai", modifier_id="MOD-B", price_vnd=8000),
        ],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert not any(
        "menu-translations" in str(call.request.url) for call in respx.calls
    )


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_add_edit_remove_in_one_put(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """One PUT covers all three option operations because `modifiers` is a
    full replacement of the option list: keep option A (its real id, a
    new price), drop option B entirely, and add brand-new option C (empty
    id). The payload must contain exactly A (updated) and C (new); B must
    not appear anywhere in it."""
    user = User(username="update-add-edit-remove@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.post("https://api.grab.com/food/merchant/v1/menu-translations").mock(
        return_value=httpx.Response(200, json={"textTranslation": {"en": "Size Large"}})
    )
    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(200, json={"modifierGroups": [{"modifierGroupID": "MOG1"}]})
    )
    update_route = respx.put(
        "https://api.grab.com/food/merchant/v3/modifier-groups/MOG1"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[
            # A: kept, price changed 5000 -> 6000.
            ModifierSpec(name="Thêm trứng", modifier_id="MOD-A", price_vnd=6000),
            # B (MOD-B) intentionally left out of the list entirely -> removed.
            # C: brand new, no modifier_id.
            ModifierSpec(name="Size Large", price_vnd=3000),
        ],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        await update_group("MOG1", body, user=user, client=c, session=db_session)

    payload = json.loads(update_route.calls[0].request.content)
    mods = payload["modifierGroup"]["modifiers"]
    assert len(mods) == 2

    kept = mods[0]
    assert kept["modifierID"] == "MOD-A"
    assert kept["priceInMin"] == 6000
    assert "nameTranslation" not in kept

    added = mods[1]
    assert added["modifierID"] == ""
    assert added["priceInMin"] == 3000
    assert "nameTranslation" in added

    assert all(m["modifierID"] != "MOD-B" for m in mods)


# ── duplicate-guard, single-snapshot design (post code-review) ───────────────────
#
# The captured PUT always answers 204, so `returned_id` is always empty and the
# cheap response-id check could never fire — the old before/after list-diff ran
# on every single edit, at the cost of two `_known_groups` reads (this store's
# dedicated list endpoint 502s constantly, so each read often falls back to the
# whole /menu). Worse, the diff could DELETE REAL DATA: the group under edit if
# Grab's list lagged, another operator's group created in the window, or
# anything at all when the two snapshots came from different Grab surfaces.
# The guard now reads the group list exactly ONCE, after the write, and counts
# how many groups (other than `group_id`) carry the name just submitted:
# 0 -> fine, 1 -> a real duplicate (roll it back), >1 -> not a shape this write
# can produce, so refuse to guess and report `verified=False` instead.


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_own_id_never_rolled_back(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """`group_id` itself always carries the name we just submitted (we
    just wrote it) -- the guard must exclude it from duplicate candidates
    BY ID, not rely on the name differing. Without that exclusion, the
    group being edited would be deleted as its own "duplicate" while the
    response claims success."""
    user = User(username="update-own-id-safe@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={"modifierGroups": [{"modifierGroupID": "MOG1", "modifierGroupName": "Topping"}]},
        )
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )
    # Mocked defensively so a buggy guard fails a clean assertion, not a
    # respx "unmocked route" error.
    delete_route = respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG1"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.verified is True
    assert not delete_route.called
    assert not any(call.request.method == "DELETE" for call in respx.calls)


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_new_group_different_name_no_rollback(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """A group in the post-write snapshot that is NOT `group_id` but
    carries a DIFFERENT name than the one just submitted is not a
    duplicate of THIS write -- it could be another operator's group.
    Only a same-name stray is a rollback candidate."""
    user = User(username="update-newgroup-diffname@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={
                "modifierGroups": [
                    {"modifierGroupID": "MOG1", "modifierGroupName": "Topping"},
                    {"modifierGroupID": "MOG-OTHEROP", "modifierGroupName": "Size"},
                ]
            },
        )
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )
    delete_route = respx.delete(
        "https://api.grab.com/food/merchant/v2/modifier-groups/MOG-OTHEROP"
    ).mock(return_value=httpx.Response(204))

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.verified is True
    assert not delete_route.called
    assert not any(call.request.method == "DELETE" for call in respx.calls)


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_multiple_same_name_strays_refuses_to_delete(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Two groups other than `group_id` both carry the submitted name --
    not a shape a single-group edit can produce (a pre-existing duplicate
    name, a concurrent bulk import, ...). The guard refuses to guess
    which one(s) to delete: no DELETE issued, the write still stands
    (200), and `verified=False` signals the check was skipped rather
    than silently claiming it passed."""
    user = User(username="update-multi-stray@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(
            200,
            json={
                "modifierGroups": [
                    {"modifierGroupID": "MOG1", "modifierGroupName": "Topping"},
                    {"modifierGroupID": "MOG-GHOST-1", "modifierGroupName": "Topping"},
                    {"modifierGroupID": "MOG-GHOST-2", "modifierGroupName": "Topping"},
                ]
            },
        )
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.verified is False
    assert not any(call.request.method == "DELETE" for call in respx.calls)


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_both_snapshots_unavailable_skips_verification(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """The direct list endpoint AND the /menu fallback both fail -- the
    single post-write `_known_groups` call returns None. The write itself
    already succeeded; the guard must not fabricate a duplicate finding
    from data it doesn't have, and must report `verified=False` rather
    than silently claiming the check ran. Each endpoint is hit exactly
    once (one read total, tries direct then falls back), not twice."""
    user = User(username="update-both-unavailable@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    list_route = respx.get("https://api.grab.com/food/merchant/v2/menu/modifier-groups").mock(
        return_value=httpx.Response(500, text="upstream flaky")
    )
    menu_route = respx.get("https://api.grab.com/food/merchant/v2/menu").mock(
        return_value=httpx.Response(500, text="upstream flaky too")
    )
    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(204)
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        result = await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert result.modifier_group_id == "MOG1"
    assert result.verified is False
    assert not any(call.request.method == "DELETE" for call in respx.calls)
    assert list_route.call_count == 1
    assert menu_route.call_count == 1


# ── create() 409 mapping regression ──────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_modifier_group_grab_409_returns_409_not_500(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Regression: a real Grab 409 (duplicate group name) on create used to
    bubble out of raise_for_status() as an unhandled 500. _grab_write_error
    must map it to a structured HTTP 409 instead."""
    user = User(username="create-409@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.post("https://api.grab.com/food/merchant/v1/menu-translations").mock(
        return_value=httpx.Response(200, json={"textTranslation": {"en": "Topping"}})
    )
    respx.post("https://api.grab.com/food/merchant/v3/modifier-groups").mock(
        return_value=httpx.Response(409, json={"message": "duplicate group name"})
    )

    # Needs at least one option: create now runs the same
    # `_selection_range_error` pre-check as update, and a group with no
    # options is rejected 422 before any Grab call — which would mask
    # the Grab-error mapping this test exists to pin.
    body = CreateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await create_group(body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "grab_modifier_group_conflict"


# ── transport-error (_grab_unreachable) mapping ──────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_delete_modifier_group_transport_error_returns_502_unreachable(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """A transport-level failure (DNS/connect/timeout) talking to Grab is a
    different exception type than a bad HTTP response (`httpx.HTTPError`,
    not `httpx.HTTPStatusError`) and used to escape all three write routes
    as an unhandled exception -- the bare 500 the whole error-mapping
    layer exists to eliminate. `_grab_unreachable` must catch it and map
    to a structured 502."""
    user = User(username="delete-unreachable@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.delete("https://api.grab.com/food/merchant/v2/modifier-groups/MOG1").mock(
        side_effect=httpx.ConnectError("boom")
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await delete_group("MOG1", user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "grab_unreachable"


@pytest.mark.asyncio
@respx.mock
async def test_create_modifier_group_transport_error_returns_502_unreachable(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """Same transport-error mapping, exercised on create."""
    user = User(username="create-unreachable@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.post("https://api.grab.com/food/merchant/v1/menu-translations").mock(
        return_value=httpx.Response(200, json={"textTranslation": {"en": "Topping"}})
    )
    respx.post("https://api.grab.com/food/merchant/v3/modifier-groups").mock(
        side_effect=httpx.ConnectError("boom")
    )

    # Needs at least one option: create now runs the same
    # `_selection_range_error` pre-check as update, and a group with no
    # options is rejected 422 before any Grab call — which would mask
    # the Grab-error mapping this test exists to pin.
    body = CreateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await create_group(body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "grab_unreachable"


# ── _selection_range_error() -- pure-function tests ───────────────────────────────
#
# Regression: editing a pre-existing group after deleting an option (7 left,
# selectionRangeMax still 8) made Grab answer 409 with
# `{"target":"InvalidRange","reason":"already_exists","message":"Modifier
# group range is invalid"}`. The old `_grab_write_error` mapped every 409 to
# "duplicate group name", which sent an operator chasing a rename that could
# never fix anything. `_selection_range_error` catches the invalid window
# BEFORE the request ever reaches Grab. It takes plain ints, no HTTP/DI
# involved -- these tests call it directly.


def test_selection_range_error_max_exceeds_option_count() -> None:
    """The actual failure an operator hit: max (8) > options left (7)."""
    exc = _selection_range_error(
        selection_range_min=0, selection_range_max=8, option_count=7,
    )

    assert exc is not None
    assert exc.status_code == 422
    assert exc.detail["code"] == "modifier_group_invalid_range"
    assert exc.detail["fields"] == ["selection_range_max"]
    assert "8" in exc.detail["message"]
    assert "7" in exc.detail["message"]


def test_selection_range_error_empty_group() -> None:
    """Zero options is a distinct failure from an out-of-range max -- must
    not be reported as a range problem, and must not divide-by/compare
    against a max that's meaningless with no options at all."""
    exc = _selection_range_error(
        selection_range_min=0, selection_range_max=1, option_count=0,
    )

    assert exc is not None
    assert exc.status_code == 422
    assert exc.detail["code"] == "modifier_group_empty"
    assert exc.detail["fields"] == ["modifiers"]


def test_selection_range_error_min_exceeds_max() -> None:
    exc = _selection_range_error(
        selection_range_min=3, selection_range_max=2, option_count=5,
    )

    assert exc is not None
    assert exc.status_code == 422
    assert exc.detail["code"] == "modifier_group_invalid_range"
    assert exc.detail["fields"] == ["selection_range_min"]


def test_selection_range_error_valid_combos_return_none() -> None:
    """max == count, max < count, and min == max are all legal windows --
    none of them should be rejected."""
    assert _selection_range_error(
        selection_range_min=0, selection_range_max=8, option_count=8,
    ) is None
    assert _selection_range_error(
        selection_range_min=0, selection_range_max=5, option_count=8,
    ) is None
    assert _selection_range_error(
        selection_range_min=2, selection_range_max=2, option_count=8,
    ) is None


# ── update_group() range pre-check -- route level ─────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_invalid_range_rejected_before_grab_call(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """selectionRangeMax=8 with only 7 modifiers left must 422 out of
    `_selection_range_error` before doing anything else -- no group-list
    read, no PUT, no round-trip to Grab at all. No routes are mocked;
    respx's `assert_all_mocked` default (still on) means any request that
    did go out would blow up with a clear "not mocked" error instead of
    silently passing, on top of the explicit zero-calls assertion below."""
    user = User(username="update-range-precheck@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        selection_range_min=0,
        selection_range_max=8,
        modifiers=[
            ModifierSpec(name=f"Option {i}", name_en=f"Option {i}", price_vnd=1000)
            for i in range(7)
        ],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "modifier_group_invalid_range"
    assert exc_info.value.detail["fields"] == ["selection_range_max"]
    assert len(respx.calls) == 0


# ── _grab_write_error() 409 mapping on update -- the misleading-error regression ──


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_grab_409_range_maps_to_invalid_range(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """The regression itself: Grab's 409 for an invalid selection range
    carries `reason: "already_exists"` (reads like a name clash) but
    `target: "InvalidRange"` and a message naming "range". The request
    body here has a VALID range (default max=1, one modifier) so the
    local pre-check passes and this 409 is Grab's alone to explain --
    `_grab_write_error` must read `target`/`message`, not guess from the
    status code, and must NOT fall back to
    `grab_modifier_group_conflict`."""
    user = User(username="update-409-range@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(
            409,
            json={
                "target": "InvalidRange",
                "reason": "already_exists",
                "message": "Modifier group range is invalid",
            },
        )
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_invalid_range"
    assert detail["fields"] == ["selection_range_max"]
    assert detail["code"] != "grab_modifier_group_conflict"


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_grab_409_name_conflict_still_maps_to_conflict(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """A genuine name clash -- no "range" anywhere in target/message --
    must still map to the original `grab_modifier_group_conflict`. Only
    the range-shaped 409 gets the new code."""
    user = User(username="update-409-name-conflict@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(
            409,
            json={"reason": "already_exists", "message": "Modifier group already exists"},
        )
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_conflict"
    assert detail["fields"] == ["group_name"]


@pytest.mark.asyncio
@respx.mock
async def test_update_modifier_group_grab_409_unparseable_body_falls_back_to_conflict(
    authn_token: str, merchant_id: str, db_session
) -> None:
    """A 409 with a body that isn't valid JSON must not raise out of the
    `.json()` parse inside `_grab_write_error` -- `target`/`message` stay
    empty, `"range"` can't match, and the mapping falls back to the
    original `grab_modifier_group_conflict` instead of an unhandled 500."""
    user = User(username="update-409-bad-body@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    respx.put("https://api.grab.com/food/merchant/v3/modifier-groups/MOG1").mock(
        return_value=httpx.Response(409, text="upstream returned garbage, not JSON")
    )

    body = UpdateModifierGroupRequest(
        group_name="Topping",
        modifiers=[ModifierSpec(name="Thêm trứng", name_en="Extra egg", price_vnd=5000)],
    )

    async with GrabClient(authn_token=authn_token, merchant_id=merchant_id) as c:
        with pytest.raises(HTTPException) as exc_info:
            await update_group("MOG1", body, user=user, client=c, session=db_session)

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "grab_modifier_group_conflict"
    assert detail["fields"] == ["group_name"]