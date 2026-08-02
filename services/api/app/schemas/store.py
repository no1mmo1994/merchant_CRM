"""Pydantic schemas for store endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StoreOut(BaseModel):
    id: int
    merchant_id: str
    name: str
    address: str
    last_refresh_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StoreListResponse(BaseModel):
    stores: list[StoreOut]


class SelectStoreRequest(BaseModel):
    merchant_id: str
