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
    UpdateAvailabilityRequest,
    UpdateAvailabilityResponse,
    UpdateItemRequest,
    UpdateItemResponse,
    UploadImageResponse,
)
from app.schemas.menu import MenuResponse
from app.schemas.modifier import (
    CreateModifierGroupRequest,
    CreateModifierGroupResponse,
    ListModifierGroupsResponse,
    ModifierGroup,
    ModifierGroupCategoryLink,
    ModifierOption,
    ModifierSpec,
    VerifyModifierRequest,
)
from app.schemas.store import (
    OpeningHourDay,
    OpeningHourRange,
    OpeningHoursData,
    OpeningHoursResponse,
    SelectStoreRequest,
    StoreListResponse,
    StoreOut,
    StoreRuntimeStatus,
    StoreStatusKind,
    UpdateStoreStatusRequest,
    UpdateStoreStatusResponse,
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
    "StoreRuntimeStatus",
    "StoreStatusKind",
    "UpdateStoreStatusRequest",
    "UpdateStoreStatusResponse",
    "OpeningHourDay",
    "OpeningHourRange",
    "OpeningHoursData",
    "OpeningHoursResponse",
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
    "UpdateAvailabilityRequest",
    "UpdateAvailabilityResponse",
    "UpdateItemRequest",
    "UpdateItemResponse",
    "UploadImageResponse",
    # modifier
    "CreateModifierGroupRequest",
    "CreateModifierGroupResponse",
    "ListModifierGroupsResponse",
    "ModifierGroup",
    "ModifierGroupCategoryLink",
    "ModifierOption",
    "ModifierSpec",
    "VerifyModifierRequest",
]
