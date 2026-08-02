"""
grab: Reverse-engineered Grab Merchant API client.

Public API surface — re-exports the classes and async functions used by
the FastAPI backend (Phase 03+). All endpoint functions return unparsed
dicts (Phase 02 keeps things loose; Phase 03 will tighten with Pydantic
response models as needed).
"""

from grab.client import GrabClient
from grab.auth import (
    XRayProvider,
    StaticXRayProvider,
    login_three_step,
    LoginError,
    ChallengeError,
)
from grab.models import (
    StoreProfile,
    StoreListResponse,
    UnifiedProfile,
    BusinessAttributes,
    Scorecard,
    Menu,
    MenuCategory,
    MenuItem,
    MenuSection,
    MenuTranslation,
    CategorySortEntry,
    CreateCategoryPayload,
    UploadFileResponse,
    UpsertItemPayload,
    VerifyModifierPayload,
    CreateModifierGroupPayload,
)

# Endpoint functions (lazy import to avoid circulars)
__all__ = [
    "GrabClient",
    "XRayProvider",
    "StaticXRayProvider",
    "login_three_step",
    "LoginError",
    "ChallengeError",
    # models
    "StoreProfile",
    "StoreListResponse",
    "UnifiedProfile",
    "BusinessAttributes",
    "Scorecard",
    "Menu",
    "MenuCategory",
    "MenuItem",
    "MenuSection",
    "MenuTranslation",
    "CategorySortEntry",
    "CreateCategoryPayload",
    "UploadFileResponse",
    "UpsertItemPayload",
    "VerifyModifierPayload",
    "CreateModifierGroupPayload",
]