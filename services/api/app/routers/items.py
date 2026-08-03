"""Menu item router — upload image, create item."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.deps import get_grab_client, get_session, require_user
from app.models import User
from app.schemas import CreateItemRequest, CreateItemResponse, UploadImageResponse
from grab.endpoints.items import create_or_update_item, upload_image

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

    # Auto-translate VI name + description -> EN
    name_en = await translate_name(client, body.name)
    desc_en = await translate_name(client, body.description) if body.description else ""

    result = await create_or_update_item(
        client,
        name_vi=body.name,
        name_en=name_en,
        description_vi=body.description,
        description_en=desc_en,
        price_vnd=body.price_vnd,
        category_id=body.category_id,
        image_urls=body.image_urls,
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
