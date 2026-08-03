"""Pydantic schemas for item endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateItemRequest(BaseModel):
    name: str
    description: str = ""
    price_vnd: int
    category_id: str
    image_urls: list[str] = []
    linked_modifier_group_ids: list[str] = []


class CreateItemResponse(BaseModel):
    item_id: str
    item_name: str


class UploadImageResponse(BaseModel):
    url: str


class UpdateItemRequest(BaseModel):
    """Payload for PUT /api/items/{id}. All fields optional to allow partial updates
    through the existing upsert-item endpoint, but callers are encouraged to send
    the full set so the upstream payload mirrors the current item exactly."""

    name: str | None = None
    description: str | None = None
    name_en: str | None = None
    description_en: str | None = None
    price_vnd: int | None = Field(default=None, ge=0)
    category_id: str | None = None
    image_urls: list[str] | None = None
    linked_modifier_group_ids: list[str] | None = None
    selling_time_id: str | None = None


class UpdateItemResponse(BaseModel):
    item_id: str
    item_name: str
    available: bool | None = None


class UpdateAvailabilityRequest(BaseModel):
    """Payload for PATCH /api/items/{id}/availability.

    Three independent toggles are supported (any combination):

    * ``status`` (1|2|3) + optional ``selling_time_id`` — sold-out reasons
      (Grab's v1 endpoint). Use 1=AVAILABLE, 2=OUT_OF_STOCK_TODAY,
      3=OUT_OF_STOCK. The customer's app still sees the item but cannot
      order it.
    * ``available: bool`` (back-compat) — translated to status=1 (true) or
      status=3 (false). Use this for the simple on/off Switch case.
    * ``hidden: bool`` — controls ``eligibleSellingStatus`` (whether the
      item appears on the storefront at all). When true, customers can't
      see the item in the menu; merchant can still edit it.
    """

    status: int | None = Field(default=None, ge=1, le=3)
    selling_time_id: str | None = None
    available: bool | None = None
    hidden: bool | None = None


class UpdateAvailabilityResponse(BaseModel):
    item_id: str
    available: bool | None = None
    status: int | None = None
    hidden: bool | None = None
