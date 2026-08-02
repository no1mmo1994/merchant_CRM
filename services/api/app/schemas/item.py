"""Pydantic schemas for item endpoints."""

from __future__ import annotations

from pydantic import BaseModel


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
