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
    available: bool


class UpdateAvailabilityResponse(BaseModel):
    item_id: str
    available: bool
