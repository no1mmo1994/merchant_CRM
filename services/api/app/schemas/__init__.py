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
from app.schemas.finance import (
    FinancialMetricGroup,
    FinancialMetricValue,
    FinancialSettlement,
    FinancialSummaryRequest,
    FinancialSummaryResponse,
    FinancialTransaction,
    SettlementsListResponse,
    SettlementsSummaryResponse,
    TransactionsListResponse,
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
from app.schemas.orders import (
    OrderDetail,
    OrderEater,
    OrderFare,
    OrderItem,
    OrderItemInfo,
    OrderItemModifier,
    OrderItemModifierGroup,
    OrderListResponse,
    OrderMexOPT,
    OrderSummary,
    OrderTimes,
)
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
    # orders
    "OrderDetail",
    "OrderEater",
    "OrderFare",
    "OrderItem",
    "OrderItemInfo",
    "OrderItemModifier",
    "OrderItemModifierGroup",
    "OrderListResponse",
    "OrderMexOPT",
    "OrderSummary",
    "OrderTimes",
    # category
    "CreateCategoryRequest",
    "CreateCategoryResponse",
    "DeleteCategoryResponse",
    "SortCategoryItem",
    "SortCategoryRequest",
    "SortCategoryResponse",
    # finance
    "FinancialMetricGroup",
    "FinancialMetricValue",
    "FinancialSettlement",
    "FinancialSummaryRequest",
    "FinancialSummaryResponse",
    "FinancialTransaction",
    "SettlementsListResponse",
    "SettlementsSummaryResponse",
    "TransactionsListResponse",
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
