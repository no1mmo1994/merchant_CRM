"""Category management router — create, delete, sort."""

from __future__ import annotations

from fastapi import APIRouter, Depends

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

router = APIRouter(prefix="/api/categories", tags=["categories"])


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

    # Auto-translate VI -> EN
    en_name = await translate_name(client, body.name)

    result = await create_category(client, name_vi=body.name, name_en=en_name)

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

    await delete_category(client, category_id)

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
    result = await sort_categories(client, sorts)

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
