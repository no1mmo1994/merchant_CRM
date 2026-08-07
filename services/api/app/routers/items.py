"""Menu item router — upload image, create, update, toggle availability."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, UploadFile

from app.deps import get_grab_client, get_session, require_user
from app.models import User
from app.schemas import (
    CreateItemRequest,
    CreateItemResponse,
    UpdateAvailabilityRequest,
    UpdateAvailabilityResponse,
    UpdateItemRequest,
    UpdateItemResponse,
    UploadImageResponse,
)
from grab.endpoints.items import create_or_update_item, set_item_availability, set_item_availability_status, upload_image

log = logging.getLogger("pulseorder.items")

router = APIRouter(prefix="/api/items", tags=["items"])


def _grab_error_message(grab_status: int, grab_body: str) -> tuple[str, str]:
    """Best-effort translation of Grab's JSON error envelope into a UI string.

    Grab's merchant v2 endpoints reply with bodies like::

        {"target":"ErrImageAspectRatioNotValid",
         "reason":"already_exists",
         "message":"Image aspect ratio must be 1:1"}

    For menu items, the most common 409 is the aspect-ratio one (the `reason`
    field is misleadingly "already_exists" — the real reason is in `target`).
    We translate a few known cases into actionable Vietnamese, and fall back
    to Grab's English `message` (or a generic one) for the rest.

    Returns ``(user_message, error_code)``.
    """
    fallback = (
        f"Grab từ chối upload ảnh (HTTP {grab_status}). Vui lòng thử ảnh khác."
    )
    if not grab_body:
        return fallback, "grab_rejected_upload"
    try:
        parsed = json.loads(grab_body)
    except json.JSONDecodeError:
        return fallback, "grab_rejected_upload"
    if not isinstance(parsed, dict):
        return fallback, "grab_rejected_upload"

    target = parsed.get("target") or ""
    grab_msg = parsed.get("message") or ""

    # Aspect-ratio: translate explicitly because the "already_exists" reason
    # field is misleading and users will not understand the English message.
    if target == "ErrImageAspectRatioNotValid" or "aspect ratio" in grab_msg.lower():
        return (
            "Ảnh phải có tỉ lệ 1:1 (vuông). Hãy crop ảnh về dạng vuông rồi thử lại.",
            "grab_aspect_ratio_invalid",
        )

    # Fall back to Grab's English message verbatim when present — it's clearer
    # than our generic copy and lets the user diagnose the real issue.
    if grab_msg.strip():
        return grab_msg.strip(), target or "grab_rejected_upload"

    return fallback, target or "grab_rejected_upload"


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_item_image(
    file: UploadFile,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> UploadImageResponse:
    """Upload a menu item image and return the hosted URL.

    Grab's /upload-file commonly returns 4xx (409 Conflict on aspect-ratio or
    duplicate hash, 400 on bad payload shape, 401 on expired token). Without
    this wrapper the exception bubbles up and the browser sees a generic 500;
    with it, the browser gets a structured 502 carrying Grab's status + body
    plus a translated message so the frontend can show "Upload failed:
    <reason>" instead of nothing.
    """
    # Save uploaded file to a temp file, pass to Grab API, clean up
    suffix = os.path.splitext(file.filename or ".tmp")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        try:
            url = await upload_image(client, tmp_path)
        except httpx.HTTPStatusError as exc:
            # Surface Grab's rejection cleanly so the UI can show the reason.
            grab_status = exc.response.status_code
            grab_body = exc.response.text[:500]
            user_msg, error_code = _grab_error_message(grab_status, grab_body)
            log.warning(
                "Grab /upload-file rejected %s for user=%s: %s — %s",
                file.filename, user.id, grab_status, grab_body,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": error_code,
                    "grab_status": grab_status,
                    "message": user_msg,
                    "grab_body": grab_body,
                },
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "Grab /upload-file transport error for %s: %r",
                file.filename, exc,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "grab_unreachable",
                    "message": "Không kết nối được tới Grab. Thử lại sau.",
                },
            ) from exc
        if url is None:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "grab_no_url",
                    "message": "Grab trả về 200 nhưng không có URL ảnh.",
                },
            )
        return UploadImageResponse(url=url)
    finally:
        os.unlink(tmp_path)


@router.post("", response_model=CreateItemResponse)
@router.post("/", response_model=CreateItemResponse)
async def create_item(
    body: CreateItemRequest,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> CreateItemResponse:
    """Create a new menu item.

    The item name is auto-translated VI -> EN server-side via Grab's
    translate_name endpoint.
    """
    from app.deps import write_audit_log
    from grab.endpoints.categories import translate_name

    # Auto-translate VI name + description -> EN.
    #
    # Both branches pass `entity`/`text_type` explicitly. `translate_name`
    # defaults to ``entity="category"`` + ``text_type="name"``, tuned for
    # category creation: Grab's translation API rejects that pairing with
    # a 4xx when applied to item descriptions, and the unhandled
    # ``HTTPStatusError`` surfaces as a raw 500.
    #
    # The name branch used to ride those defaults, so an item's name was
    # translated as though it were a category's. Grab accepted it, which
    # is why nothing broke loudly — but it fed the translator the wrong
    # context, and the description branch three lines down already showed
    # what the right call looks like.
    name_en = await translate_name(
        client,
        body.name,
        entity="item",
        text_type="name",
    )
    desc_en = (
        await translate_name(
            client,
            body.description,
            entity="item",
            text_type="description",
        )
        if body.description
        else ""
    )

    result = await create_or_update_item(
        client,
        name_vi=body.name,
        name_en=name_en,
        description_vi=body.description,
        description_en=desc_en,
        price_vnd=body.price_vnd,
        category_id=body.category_id,
        image_urls=body.image_urls,
        webp_urls=body.image_urls,  # mirror JPGs — browser will fall back
        webp_url=body.image_urls[0] if body.image_urls else None,
        linked_modifier_group_ids=body.linked_modifier_group_ids,
    )

    item_id: str = result.get("itemID", result.get("skuID", ""))
    write_audit_log(
        session=session,
        user_id=user.id,
        action="item.create",
        entity_type="item",
        entity_id=item_id,
        payload={"name_vi": body.name, "price_vnd": body.price_vnd},
    )

    return CreateItemResponse(item_id=item_id, item_name=body.name)


async def _load_item(item_id: str, client) -> tuple[dict, str]:
    """Fetch an item from Grab's /menu, plus the id of its category.

    Returns `(item, category_id)`, raising 404 if the item is missing.

    Used by the update + availability endpoints so they can preserve all
    the fields they don't intend to change (Grab's upsert-item is
    full-payload). The category is returned alongside because it is one
    of those fields, and reading it off the item itself is unreliable:
    `/menu` items frequently carry no `categoryID`, so callers defaulted
    it to `""` and then wrote that empty value back — moving the item out
    of its category on Grab. The enclosing category is authoritative.

    `find_item_with_category` also walks `sections[].categories[]`, the
    shape a real store actually returns; the loop this replaced only
    walked the flat `categories` list and so usually found nothing.
    """
    from grab.endpoints.menu import find_item_with_category, get_full_menu

    menu = await get_full_menu(client)
    if not isinstance(menu, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "menu_unavailable",
                "message": "Không đọc được thực đơn từ Grab để cập nhật món.",
            },
        )
    found = find_item_with_category(menu, item_id)
    if found is not None:
        return found
    raise HTTPException(
        status_code=404,
        detail={
            "code": "item_not_found",
            "message": f"Không tìm thấy món {item_id} trong thực đơn hiện tại.",
        },
    )


def _extract_item_locales(item: dict, category_id: str = "") -> dict[str, Any]:
    """Pull the VI/EN name + description, price, images, etc. from a menu item.

    `category_id` is the id of the category the item was found inside
    (see `_load_item`). It wins over the item's own `categoryID`, which
    `/menu` often omits — falling back to `""` there meant upsert-item
    was told the item belongs to no category, silently removing it from
    the one it was in.
    """
    name_vi = str(item.get("itemName") or item.get("name") or "")
    name_en = (
        ((item.get("nameTranslation") or {}).get("translation") or {}).get("en")
        or name_vi
    )
    description_vi = str(item.get("description") or "")
    description_en = (
        ((item.get("descriptionTranslation") or {}).get("translation") or {})
        .get("en")
        or description_vi
    )
    image_urls = list(item.get("imageURLs") or [])
    webp_urls = list(item.get("webPURLs") or image_urls)
    webp_url = str(item.get("webPURL") or (webp_urls[0] if webp_urls else ""))
    sort_order = item.get("sortOrder")
    return {
        "name_vi": name_vi,
        "name_en": name_en,
        "description_vi": description_vi,
        "description_en": description_en,
        "price_vnd": int(item.get("priceInMin") or item.get("price") or 0),
        "category_id": category_id or str(item.get("categoryID") or ""),
        "image_urls": image_urls,
        "webp_urls": webp_urls,
        "webp_url": webp_url,
        "linked_modifier_group_ids": list(item.get("linkedModifierGroupIDs") or []),
        "selling_time_id": str(item.get("sellingTimeID") or "AlwaysAvailable"),
        # Preserve current availability so an edit doesn't silently re-enable
        # items that the merchant had marked OUT_OF_STOCK. Grab's upsert-item
        # treats the full payload as authoritative, so omission/empty here
        # would let the upstream default re-enable the item.
        "eligible_selling_status": str(item.get("eligibleSellingStatus") or "ELIGIBLE"),
        "available_status": int(item.get("availableStatus") or 1),
        "sold_quantity": int(item.get("soldQuantity") or 0),
        "sort_order": int(sort_order) if isinstance(sort_order, (int, float)) else None,
        "available_at": str(item.get("availableAt") or "0001-01-01T00:00:00.000Z"),
    }


@router.put("/{item_id}", response_model=UpdateItemResponse)
async def update_item(
    body: UpdateItemRequest,
    item_id: str = Path(..., min_length=1),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> UpdateItemResponse:
    """Update an existing menu item's editable fields.

    Only fields the caller sends are mutated; everything else is preserved
    from the current upstream snapshot. Empty strings for name are treated as
    "don't change" to avoid wiping out an existing name through a stale form.
    """
    from app.deps import write_audit_log

    current, current_category_id = await _load_item(item_id, client)
    locales = _extract_item_locales(current, current_category_id)

    # Apply patches. None means "leave alone"; "" for name is ignored too
    # because Grab treats empty strings as clearing the field.
    if body.name is not None and body.name.strip():
        locales["name_vi"] = body.name.strip()
    if body.description is not None:
        locales["description_vi"] = body.description
    if body.name_en is not None:
        locales["name_en"] = body.name_en
    if body.description_en is not None:
        locales["description_en"] = body.description_en
    if body.price_vnd is not None:
        locales["price_vnd"] = body.price_vnd
    if body.category_id is not None:
        locales["category_id"] = body.category_id
    if body.image_urls is not None:
        locales["image_urls"] = body.image_urls
    if body.linked_modifier_group_ids is not None:
        locales["linked_modifier_group_ids"] = body.linked_modifier_group_ids
    if body.selling_time_id is not None:
        locales["selling_time_id"] = body.selling_time_id

    try:
        result = await create_or_update_item(
            client,
            name_vi=locales["name_vi"],
            name_en=locales["name_en"],
            description_vi=locales["description_vi"],
            description_en=locales["description_en"],
            price_vnd=locales["price_vnd"],
            category_id=locales["category_id"],
            image_urls=locales["image_urls"],
            webp_urls=locales["webp_urls"],
            webp_url=locales["webp_url"],
            linked_modifier_group_ids=locales["linked_modifier_group_ids"],
            selling_time_id=locales["selling_time_id"],
            item_id=item_id,
            eligible_selling_status=locales["eligible_selling_status"],
            available_status=locales["available_status"],
            sold_quantity=locales["sold_quantity"],
            sort_order=locales["sort_order"],
            available_at=locales["available_at"],
        )
    except httpx.HTTPStatusError as exc:
        log.warning("Grab upsert-item rejected for %s: %s", item_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_rejected_update",
                "grab_status": exc.response.status_code,
                "message": "Grab từ chối cập nhật món. Vui lòng thử lại.",
                "grab_body": exc.response.text[:500],
            },
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("Grab upsert-item transport error for %s: %r", item_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_unreachable",
                "message": "Không kết nối được tới Grab. Thử lại sau.",
            },
        ) from exc

    write_audit_log(
        session=session,
        user_id=user.id,
        action="item.update",
        entity_type="item",
        entity_id=item_id,
        payload={
            "fields_changed": [
                k for k in (
                    "name", "description", "price_vnd", "category_id",
                    "image_urls", "linked_modifier_group_ids", "selling_time_id",
                )
                if getattr(body, k) is not None
            ]
        },
    )

    return UpdateItemResponse(
        item_id=item_id,
        item_name=locales["name_vi"],
        available=None,
    )


@router.patch("/{item_id}/availability", response_model=UpdateAvailabilityResponse)
async def update_item_availability(
    body: UpdateAvailabilityRequest,
    item_id: str = Path(..., min_length=1),
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
    session=Depends(get_session),
) -> UpdateAvailabilityResponse:
    """Toggle storefront availability for a single item.

    Accepts (in any combination):

    * ``status`` (1|2|3|7) + optional ``selling_time_id`` — Grab's v1
      endpoint enum:
        1 = AVAILABLE (sellable, listed)
        2 = OUT_OF_STOCK_TODAY (listed, can't order until midnight)
        3 = OUT_OF_STOCK (listed, can't order until merchant toggles back)
        7 = HIDDEN (not in customer menu at all; merchant still sees it).
      Verified against ``Menu/monan/bat_tatmon.py`` and
      ``Menu/monan/hide_monan.py``.
    * ``available: bool`` (back-compat) — translated to status=1 (true)
      or status=3 (false).
    * ``hidden: bool`` — convenience alias for status=7 (true) /
      status=1 (false). Folded into ``status`` before dispatch.
    """
    from app.deps import write_audit_log

    # Resolve the numeric status + (if needed) the current sellingTimeID.
    status: int | None = body.status
    selling_time_id: str | None = body.selling_time_id

    # Fold ``hidden`` into ``status`` so a single v1 call handles both.
    # hidden=true  → status=7 (ẩn hoàn toàn khỏi menu khách)
    # hidden=false → status=1 (khôi phục bán + hiển thị)
    # If both are supplied, ``hidden`` wins because it conveys intent.
    if body.hidden is not None:
        status = 7 if body.hidden else 1

    if status is None and body.available is not None:
        # Back-compat: simple on/off Switch without a reason.
        status = 1 if body.available else 3
    if status is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "missing_field",
                "message": "Cần truyền `status` (1|2|3|7), `available` (bool) hoặc `hidden` (bool).",
            },
        )

    audit_payload: dict = {
        "status": status,
        "selling_time_id": selling_time_id,
        "available": body.available,
        "hidden": body.hidden,
    }

    try:
        if status == 1 and not selling_time_id:
            # v1 endpoint requires sellingTimeID for status=1; pull from
            # current menu snapshot.
            try:
                current, _ = await _load_item(item_id, client)
            except HTTPException:
                raise
            selling_time_id = (
                str(current.get("sellingTimeID") or "")
                or "AlwaysAvailable"
            )

        try:
            await set_item_availability_status(
                client,
                item_id=item_id,
                available_status=status,
                selling_time_id=selling_time_id,
            )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg.lower():
                raise HTTPException(
                    status_code=404,
                    detail={"code": "item_not_found", "message": msg},
                ) from exc
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_payload", "message": msg},
            ) from exc
    except httpx.HTTPStatusError as exc:
        log.warning("Grab availability toggle rejected for %s: %s", item_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_rejected_availability",
                "grab_status": exc.response.status_code,
                "message": "Grab từ chối đổi trạng thái bán. Vui lòng thử lại.",
                "grab_body": exc.response.text[:500],
            },
        ) from exc
    except httpx.HTTPError as exc:
        log.warning("Grab availability toggle transport error for %s: %r", item_id, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grab_unreachable",
                "message": "Không kết nối được tới Grab. Thử lại sau.",
            },
        ) from exc

    write_audit_log(
        session=session,
        user_id=user.id,
        action="item.availability",
        entity_type="item",
        entity_id=item_id,
        payload=audit_payload,
    )

    return UpdateAvailabilityResponse(
        item_id=item_id,
        available=(status == 1),
        status=status,
        hidden=body.hidden if body.hidden is not None else (status == 7),
    )
