"""Pydantic v2 models for the Grab Merchant API.

The Grab endpoints return a lot of unknown / undocumented fields. We
deliberately use `ConfigDict(extra='allow')` so:

* the parser doesn't blow up on first contact with a new key, and
* tests can slice specific fields without losing the rest of the payload.

Phase 02 keeps models loose. Phase 03 will tighten them as the FastAPI
backend lands shape-checked contracts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    """Common config: tolerate extra fields so unknown API additions
    don't break parsing.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------------------
# Store / profile
# ---------------------------------------------------------------------------
class StoreSummary(_Base):
    gpid: str | None = None
    gfid: str | None = None
    name: str | None = None
    address: str | None = None
    city: str | None = None
    status: str | None = None
    pending: bool | None = None
    status_display: str | None = None


class StoreListResponse(_Base):
    """Shape: `{ "data": { "stores": [...] } }`."""

    stores: list[StoreSummary] = Field(default_factory=list)


class StoreProfile(_Base):
    """User profile v2 — has nested `user_profile.user_profile_details`."""

    merchant_grab_id: str | None = None
    role: str | None = None
    profile_status: str | None = None
    first_name: str | None = None


class UnifiedProfile(_Base):
    """Shape: `data.{grab_food_profile.merchant, grab_food_store_profile.storeProfile, ...}`."""

    name: str | None = None
    address: str | None = None
    status: str | None = None
    email: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photo: str | None = None
    small_picture: str | None = None

    # nested store info
    store_phone: str | None = None

    # owner / bank
    owner_name: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    owner_phone: str | None = None


class BusinessAttributes(_Base):
    merchant_id: str | None = None


class Scorecard(_Base):
    title: str | None = None
    desc: str | None = None
    score: float | None = None
    score_rank: str | None = None


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
class MenuTranslation(_Base):
    translation: dict[str, str] = Field(default_factory=dict)
    original_translation_from_ds: dict[str, str] = Field(
        default_factory=dict, alias="originalTranslationFromDS"
    )


class MenuItem(_Base):
    item_id: str | None = Field(default=None, alias="itemID")
    item_name: str | None = Field(default=None, alias="itemName")
    description: str | None = None
    price_in_min: int | None = Field(default=None, alias="priceInMin")
    image_urls: list[str] = Field(default_factory=list, alias="imageURLs")
    linked_modifier_group_ids: list[str] = Field(
        default_factory=list, alias="linkedModifierGroupIDs"
    )
    name_translation: MenuTranslation | None = Field(
        default=None, alias="nameTranslation"
    )
    description_translation: MenuTranslation | None = Field(
        default=None, alias="descriptionTranslation"
    )
    selling_time_id: str | None = Field(default=None, alias="sellingTimeID")


class MenuCategory(_Base):
    category_id: str | None = Field(default=None, alias="categoryID")
    category_name: str | None = Field(default=None, alias="categoryName")
    name: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")
    items: list[MenuItem] = Field(default_factory=list)


class MenuSection(_Base):
    section_id: str | None = Field(default=None, alias="sectionID")
    categories: list[MenuCategory] = Field(default_factory=list)


class Menu(_Base):
    categories: list[MenuCategory] = Field(default_factory=list)
    sections: list[MenuSection] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sorting / translation
# ---------------------------------------------------------------------------
class CategorySortEntry(_Base):
    resource_id: str = Field(alias="resourceID")
    sort_order: int = Field(alias="sortOrder")


class CategorySortPayload(_Base):
    section_sorts: list[dict[str, Any]] = Field(
        default_factory=list, alias="sectionSorts"
    )


class CreateCategoryPayload(_Base):
    name: str
    name_translation: MenuTranslation = Field(alias="nameTranslation")
    selling_time_id: str = Field(default="AlwaysAvailable", alias="sellingTimeID")


class MenuTranslationRequest(_Base):
    text_source_lang: str = "vi"
    text_type: str = "name"
    text_target_lang: list[str] = Field(default_factory=lambda: ["en"])
    text: str
    entity: str = "category"


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
class UploadFileResponse(_Base):
    url: str | None = None
    image_url: str | None = Field(default=None, alias="imageURL")
    temporary_url: str | None = Field(default=None, alias="temporaryURL")


class UpsertItemPayload(_Base):
    """The `item` envelope inside the `/food/merchant/v2/upsert-item` body."""

    item_name: str = Field(alias="itemName")
    description: str | None = None
    price_in_min: int = Field(alias="priceInMin")
    image_urls: list[str] = Field(default_factory=list, alias="imageURLs")
    linked_modifier_group_ids: list[str] = Field(
        default_factory=list, alias="linkedModifierGroupIDs"
    )
    name_translation: MenuTranslation = Field(alias="nameTranslation")
    description_translation: MenuTranslation | None = Field(
        default=None, alias="descriptionTranslation"
    )
    selling_time_id: str = Field(default="AlwaysAvailable", alias="sellingTimeID")
    sku_id: str | None = Field(default=None, alias="skuID")
    special_item_type: str | None = Field(default=None, alias="specialItemType")
    sold_by_weight: bool = Field(default=False, alias="soldByWeight")
    eligible_selling_status: str | None = Field(
        default=None, alias="eligibleSellingStatus"
    )


# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------
class ModifierPayload(_Base):
    modifier_id: str | None = Field(default=None, alias="modifierID")
    modifier_name: str = Field(alias="modifierName")
    price_in_min: int = Field(alias="priceInMin")
    name_translation: MenuTranslation = Field(alias="nameTranslation")


class VerifyModifierPayload(_Base):
    modifier: ModifierPayload


class CreateModifierGroupPayload(_Base):
    modifier_group_name: str = Field(alias="modifierGroupName")
    modifier_group_id: str | None = Field(default=None, alias="modifierGroupID")
    selection_range_min: int = Field(alias="selectionRangeMin")
    selection_range_max: int = Field(alias="selectionRangeMax")
    is_flexible_quantity_enabled: bool = Field(
        default=False, alias="isFlexibleQuantityEnabled"
    )
    name_translation: MenuTranslation = Field(alias="nameTranslation")
    modifiers: list[ModifierPayload] = Field(default_factory=list)
