"""Pydantic schemas for item endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# Grab's v1 available-status enum. 1/2/3 are sold-out reasons; 7 = HIDDEN
# (verified against Menu/monan/hide_monan.py). Using `Literal` so the
# generated OpenAPI enum is exact — clients get a clear 422 on bad values.
AvailabilityStatus = Literal[1, 2, 3, 7]


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

    * ``status`` (1|2|3|7) + optional ``selling_time_id`` — sold-out /
      hide reasons (Grab's v1 endpoint).
        1 = AVAILABLE (sellable, listed)
        2 = OUT_OF_STOCK_TODAY (listed, can't order until midnight)
        3 = OUT_OF_STOCK (listed, can't order until merchant toggles back)
        7 = HIDDEN (not in customer menu at all; merchant still sees it)
    * ``available: bool`` (back-compat) — translated to status=1 (true)
      or status=3 (false). Use this for the simple on/off Switch case.
    * ``hidden: bool`` — convenience alias for ``status=7`` (true) /
      ``status=1`` (false). The backend prefers ``hidden`` if both are
      supplied because it conveys intent more clearly.
    """

    status: AvailabilityStatus | None = None
    selling_time_id: str | None = None
    available: bool | None = None
    hidden: bool | None = None


class UpdateAvailabilityResponse(BaseModel):
    item_id: str
    available: bool | None = None
    status: int | None = None
    hidden: bool | None = None
