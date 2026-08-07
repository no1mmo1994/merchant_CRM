"""Grab store model — encrypted tokens are stored at rest in the DB."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Store(SQLModel, table=True):
    """A Grab merchant store linked to one PulseOrder user.

    `address` is the raw Grab merchant address pulled from
    `GET /mex-app/troy/user-profile/v1/unified-profile`. Stored
    verbatim (commas + accents) so the dashboard can render it on
    the "Nguồn" source card.

    `region` is the city/province auto-derived from `address` at
    write time via `app.core.region.extract_city` (e.g.
    "110 Hà Duy Phiên, Hòa Châu, Hòa Vang" → "Đà Nẵng"). The
    partner API reads `region` to label each order's `source`
    field as "GF <region>" so the partner can route orders by
    geography without re-parsing the address string.
    """

    __tablename__ = "stores"

    id: int | None = Field(default=None, primary_key=True)
    merchant_id: str = Field(unique=True, index=True)
    name: str = Field()
    address: str = Field(default="")
    region: str = Field(default="")
    encrypted_auth_token: str = Field()
    encrypted_display_token: str = Field(default="")
    encrypted_xray_token: str = Field(default="")
    owner_user_id: int = Field(foreign_key="users.id")
    last_refresh_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
