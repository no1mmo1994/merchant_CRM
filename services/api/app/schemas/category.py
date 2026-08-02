"""Pydantic schemas for category endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class SortCategoryItem(BaseModel):
    resource_id: str
    sort_order: int


class CreateCategoryRequest(BaseModel):
    name: str  # VI only; EN auto-translated server-side via Grab translate_name


class CreateCategoryResponse(BaseModel):
    category_id: str
    name: str


class DeleteCategoryResponse(BaseModel):
    deleted: bool


class SortCategoryRequest(BaseModel):
    items: list[SortCategoryItem]


class SortCategoryResponse(BaseModel):
    success: bool
