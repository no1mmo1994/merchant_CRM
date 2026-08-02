"""Re-export all Pydantic schemas for convenient top-level imports."""

from __future__ import annotations

from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RefreshTokenRequest,
    UserOut,
)
from app.schemas.category import (
    CreateCategoryRequest,
    CreateCategoryResponse,
    DeleteCategoryResponse,
    SortCategoryItem,
    SortCategoryRequest,
    SortCategoryResponse,
)
from app.schemas.item import (
    CreateItemRequest,
    CreateItemResponse,
    UploadImageResponse,
)
from app.schemas.menu import MenuResponse
from app.schemas.modifier import (
    CreateModifierGroupRequest,
    CreateModifierGroupResponse,
    ListModifierGroupsResponse,
    ModifierGroup,
    ModifierOption,
    ModifierSpec,
    VerifyModifierRequest,
)
from app.schemas.store import (
    SelectStoreRequest,
    StoreListResponse,
    StoreOut,
)

__all__ = [
    # auth
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "RefreshTokenRequest",
    "UserOut",
    # store
    "SelectStoreRequest",
    "StoreListResponse",
    "StoreOut",
    # menu
    "MenuResponse",
    # category
    "CreateCategoryRequest",
    "CreateCategoryResponse",
    "DeleteCategoryResponse",
    "SortCategoryItem",
    "SortCategoryRequest",
    "SortCategoryResponse",
    # item
    "CreateItemRequest",
    "CreateItemResponse",
    "UploadImageResponse",
    # modifier
    "CreateModifierGroupRequest",
    "CreateModifierGroupResponse",
    "ListModifierGroupsResponse",
    "ModifierGroup",
    "ModifierOption",
    "ModifierSpec",
    "VerifyModifierRequest",
]
