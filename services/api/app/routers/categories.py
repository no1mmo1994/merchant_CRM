"""Category management router — create, delete, sort."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.grab_errors import PASSCODE_CODE, PASSCODE_MESSAGE, PASSCODE_TARGET
from app.deps import get_grab_client, get_session, require_user
from app.models import User
from app.schemas import (
    CreateCategoryRequest,
    CreateCategoryResponse,
    DeleteCategoryResponse,
    SortCategoryRequest,
    SortCategoryResponse,
)
from grab.endpoints.categories import (
    create_category,
    delete_category,
    sort_categories,
    translate_name,
)
from grab.endpoints.menu import category_section_map, get_full_menu

log = logging.getLogger("pulseorder.categories")

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _grab_error(exc: httpx.HTTPStatusError, *, what: str) -> HTTPException:
    """Turn a Grab rejection into an answer the operator can act on.

    Every write in this router used to end at a bare `raise_for_status()`
    with nothing catching it, so any Grab 4xx surfaced as
    "Internal Server Error". That is what a second account hit when
    reordering its menu: Grab said something specific, and the dashboard
    reported a server fault — pointing the operator at the wrong system
    entirely, with the real reason living only in a log nobody was
    reading. `modifiers.py` and `items.py` already map their write errors
    this way; this router was the one that never got it.

    Grab's own `message` is passed through when it sends one, because a
    sentence from Grab beats anything invented here. The full body is
    logged, a short slice reaches the client.
    """
    status_code = exc.response.status_code
    body = (exc.response.text or "").strip()[:500]
    log.warning("Grab %s rejected: %s — %s", what, status_code, body)

    grab_message = ""
    target = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            grab_message = str(payload.get("message") or "")
            target = str(payload.get("target") or "")
    except ValueError:
        pass

    # A passcode refusal is not an expired login: re-authenticating mints
    # the same token and hits the same wall, so it needs its own answer.
    # Against `target` from the full body, not the 500-char `body` copy —
    # see the same note in `modifiers.py`.
    if status_code == 403 and target == PASSCODE_TARGET:
        return HTTPException(
            status_code=403,
            detail={
                "code": PASSCODE_CODE,
                "message": PASSCODE_MESSAGE,
                "grab_status": status_code,
                "grab_target": target,
            },
        )

    if status_code in (401, 403):
        message = (
            "Grab từ chối quyền thao tác trên cửa hàng này. Token có thể đã hết "
            "hạn — hãy đăng nhập lại."
        )
    elif status_code == 404:
        message = "Grab không tìm thấy danh mục — menu có thể đã thay đổi, hãy tải lại."
    elif grab_message:
        message = f"Grab từ chối: {grab_message}"
    else:
        message = f"Grab từ chối yêu cầu (HTTP {status_code})."

    # 404 is preserved rather than flattened into 400, matching
    # `marketing.py` and `modifiers.py` — "that category is gone" and
    # "Grab refused this change" are different things to the caller.
    if status_code == 404:
        http_status = 404
    elif status_code >= 500:
        http_status = 502
    else:
        http_status = 400

    return HTTPException(
        status_code=http_status,
        detail={
            "code": "grab_category_write_failed",
            "message": message,
            "grab_status": status_code,
            "grab_target": target,
        },
    )


def _grab_unreachable(exc: httpx.HTTPError, *, what: str) -> HTTPException:
    log.warning("Grab %s transport error: %r", what, exc)
    return HTTPException(
        status_code=502,
        detail={
            "code": "grab_unreachable",
            "message": "Không kết nối được tới Grab. Thử lại sau ít phút.",
        },
    )


@router.post("", response_model=CreateCategoryResponse)
@router.post("/", response_model=CreateCategoryResponse)
async def create(
    body: CreateCategoryRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> CreateCategoryResponse:
    """Create a new Grab category.

    The Vietnamese name is sent as-is; English translation is auto-generated
    by Grab's translate_name endpoint.
    """
    from app.deps import write_audit_log

    try:
        # Auto-translate VI -> EN
        en_name = await translate_name(client, body.name)
        result = await create_category(client, name_vi=body.name, name_en=en_name)
    except httpx.HTTPStatusError as exc:
        raise _grab_error(exc, what="category create") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="category create") from exc

    # Grab returns the new category object in the response
    cat_id: str = result.get("categoryID", result.get("id", ""))
    write_audit_log(
        session=session,
        user_id=user.id,
        action="category.create",
        entity_type="category",
        entity_id=cat_id,
        payload={"name_vi": body.name, "name_en": en_name},
    )

    return CreateCategoryResponse(category_id=cat_id, name=body.name)


@router.delete("/{category_id}", response_model=DeleteCategoryResponse)
async def delete(
    category_id: str,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> DeleteCategoryResponse:
    """Delete a Grab category."""
    from app.deps import write_audit_log

    try:
        await delete_category(client, category_id)
    except httpx.HTTPStatusError as exc:
        raise _grab_error(exc, what="category delete") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="category delete") from exc

    write_audit_log(
        session=session,
        user_id=user.id,
        action="category.delete",
        entity_type="category",
        entity_id=category_id,
    )

    return DeleteCategoryResponse(deleted=True)


@router.put("/sort", response_model=SortCategoryResponse)
async def sort_(
    body: SortCategoryRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> SortCategoryResponse:
    """Reorder categories. The items list defines resource_id -> sort_order."""
    from app.deps import write_audit_log

    sorts = [{"resourceID": item.resource_id, "sortOrder": item.sort_order} for item in body.items]
    try:
        # Which section each category sits in decides the request shape,
        # and only the menu knows. A flat menu yields `sectionID: ""` for
        # everything — identical to what shipped before — while a menu
        # built from sections gets its real ids instead of a blanket empty
        # string that asks Grab to reorder a section that isn't there.
        #
        # One extra GET on an explicit drag-and-drop is cheap; guessing
        # the shape is what made this work for one account and fail for
        # another.
        try:
            menu = await get_full_menu(client)
            section_by_category = category_section_map(menu)
        except (httpx.HTTPError, ValueError) as exc:
            # The reorder itself may still succeed on a flat menu, which
            # is the common case — so fall back rather than refuse.
            #
            # `ValueError` covers `json.JSONDecodeError` from a malformed
            # body. Without it this lookup — added to stop reorders
            # returning 500 — would itself return an uncaught 500.
            log.warning("category sort: menu lookup failed, using flat shape: %r", exc)
            section_by_category = {}

        result = await sort_categories(
            client, sorts, section_by_category=section_by_category
        )
    except httpx.HTTPStatusError as exc:
        raise _grab_error(exc, what="category sort") from exc
    except httpx.HTTPError as exc:
        raise _grab_unreachable(exc, what="category sort") from exc

    # sort_categories returns {} on success; treat absence of error as success
    success = not bool(result.get("errorMessage")) or result == {}

    write_audit_log(
        session=session,
        user_id=user.id,
        action="category.sort",
        entity_type="category",
        payload={"sorts": sorts},
    )

    return SortCategoryResponse(success=success)
