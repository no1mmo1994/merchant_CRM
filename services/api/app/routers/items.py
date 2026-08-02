"""Menu item router — upload image, create item."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, UploadFile

from app.deps import get_grab_client, get_session, require_user
from app.models import User
from app.schemas import CreateItemRequest, CreateItemResponse, UploadImageResponse
from grab.endpoints.items import create_or_update_item, upload_image

router = APIRouter(prefix="/api/items", tags=["items"])


@router.post("/upload-image", response_model=UploadImageResponse)
async def upload_item_image(
    file: UploadFile,
    user: User = Depends(require_user),
    client=Depends(get_grab_client),
) -> UploadImageResponse:
    """Upload a menu item image and return the hosted URL."""
    # Save uploaded file to a temp file, pass to Grab API, clean up
    suffix = os.path.splitext(file.filename or ".tmp")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        url = await upload_image(client, tmp_path)
        if url is None:
            raise RuntimeError("Image upload returned no URL")
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
