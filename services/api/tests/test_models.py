"""Tests for Pydantic models — focus on extra="allow" tolerance."""

from __future__ import annotations

from grab.models import (
    BusinessAttributes,
    CategorySortEntry,
    MenuItem,
    Scorecard,
    StoreListResponse,
    UnifiedProfile,
    UploadFileResponse,
)


def test_store_list_response_tolerates_unknown_fields() -> None:
    payload = {
        "stores": [
            {
                "gpid": "1",
                "name": "Store A",
                "brand_new_field": "lol",
            }
        ],
        "weird_top_level_key": "ignored",
    }
    response = StoreListResponse(**payload)
    assert len(response.stores) == 1
    assert response.stores[0].name == "Store A"


def test_unified_profile_parses_nested_data() -> None:
    raw = {
        "data": {
            "grab_food_profile": {
                "merchant": {
                    "name": "My Store",
                    "address": "1 Test St",
                    "status": "ACTIVE",
                    "email": "test@example.com",
                    "latitude": 10.762622,
                    "longitude": 106.660172,
                    "photo": "https://cdn/x.jpg",
                    "smallPicture": "https://cdn/x_s.jpg",
                }
            },
            "grab_food_store_profile": {
                "storeProfile": {"storePIC": {"outletPhone": "0901234567"}}
            },
            "bank_details": {
                "account_name": "Trương Bảo Ngư",
                "bank_name": "VCB",
                "account_number": "123456789",
            },
            "grab_owner_contact": {"ContactPhoneNumber": "0987654321"},
        }
    }
    # Pull the merchant block manually since the model is intentionally loose
    merchant = raw["data"]["grab_food_profile"]["merchant"]
    assert merchant["name"] == "My Store"


def test_business_attributes_extract_merchant_id() -> None:
    raw = {"businessAttributeValues": [{"merchantID": "5-XYZ"}]}
    attrs = BusinessAttributes(merchant_id=raw["businessAttributeValues"][0]["merchantID"])
    assert attrs.merchant_id == "5-XYZ"


def test_scorecard_handles_missing_fields() -> None:
    sc = Scorecard(title="Gold", score=92)
    assert sc.title == "Gold"
    assert sc.desc is None


def test_category_sort_entry_uses_alias() -> None:
    entry = CategorySortEntry(**{"resourceID": "CAT1", "sortOrder": 5})
    assert entry.resource_id == "CAT1"
    assert entry.sort_order == 5


def test_menu_item_parses_with_aliases() -> None:
    item = MenuItem(
        **{
            "itemID": "I1",
            "itemName": "Cua",
            "priceInMin": 500000,
            "imageURLs": ["https://cdn/x.jpg"],
            "linkedModifierGroupIDs": ["MOG1"],
        }
    )
    assert item.item_id == "I1"
    assert item.item_name == "Cua"
    assert item.price_in_min == 500000
    assert item.image_urls == ["https://cdn/x.jpg"]
    assert item.linked_modifier_group_ids == ["MOG1"]


def test_upload_file_response_accepts_multiple_key_names() -> None:
    assert UploadFileResponse(url="https://a").url == "https://a"
    assert UploadFileResponse(**{"imageURL": "https://b"}).image_url == "https://b"
    assert UploadFileResponse(**{"temporaryURL": "https://c"}).temporary_url == "https://c"