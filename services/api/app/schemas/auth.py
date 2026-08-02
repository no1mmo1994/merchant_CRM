"""Pydantic schemas for authentication endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Login payload from the dashboard.

    The x-ray token is captured once per session by the user from their
    Grab Merchant app / browser DevTools and pasted into the form — it
    is HMAC-tagged against a device clock and goes stale quickly, so we
    never reuse a stored one. Backend feeds it into both step-1 and
    step-3 of the 3-step login (matching `Login/login1-done.py`).
    """

    email: EmailStr
    password: str
    xray_token: str = Field(
        ...,
        min_length=10,
        max_length=8192,
        description=(
            "x-ray token captured from the most recent POST to "
            "`/grabid/v1/authnv4/login`. Same value is used for step-1 "
            "and step-3 of the 3-step login."
        ),
    )


class UserOut(BaseModel):
    id: int
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StoreOut(BaseModel):
    id: int
    merchant_id: str
    name: str
    address: str
    last_refresh_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    user: UserOut
    store: StoreOut
    message: str = "ok"


class RefreshTokenRequest(BaseModel):
    merchant_id: str


class MeResponse(BaseModel):
    user: UserOut
    stores: list[StoreOut]
