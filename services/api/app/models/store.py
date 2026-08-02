"""Grab store model — encrypted tokens are stored at rest in the DB."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Store(SQLModel, table=True):
    """A Grab merchant store linked to one PulseOrder user."""

    __tablename__ = "stores"

    id: int | None = Field(default=None, primary_key=True)
    merchant_id: str = Field(unique=True, index=True)
    name: str = Field()
    address: str = Field(default="")
    encrypted_auth_token: str = Field()
    encrypted_display_token: str = Field(default="")
    encrypted_xray_token: str = Field(default="")
    owner_user_id: int = Field(foreign_key="users.id")
    last_refresh_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
