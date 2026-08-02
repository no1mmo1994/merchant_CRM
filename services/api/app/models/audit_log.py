"""Audit log model — immutable append-only record of user actions."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    """Records every significant user action for compliance and debugging."""

    __tablename__ = "audit_logs"
    __table_args__ = ({"schema": ""},)  # default schema only

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    action: str = Field()
    entity_type: str = Field(default="")
    entity_id: str = Field(default="")
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        index=True,  # for efficient user+time queries
    )
