"""User account model."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """A PulseOrder user who can own one or more Grab stores."""

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str = Field()
    created_at: datetime = Field(default_factory=datetime.utcnow)
