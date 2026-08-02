"""Audit log read endpoint — surfaces the user's recent activity.

Phase 10 wire-up. The write path is `app.deps.write_audit_log`; this
router exposes a paginated GET so the settings page can render it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.deps import get_session, require_user
from app.models import AuditLog, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogEntry(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: str
    payload_json: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    entries: list[AuditLogEntry]
    total: int


@router.get("", response_model=AuditLogListResponse)
@router.get("/", response_model=AuditLogListResponse)
def list_audit(
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditLogListResponse:
    """Return the most recent audit entries for the current user."""
    q = (
        session.query(AuditLog)
        .filter(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc())
    )
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return AuditLogListResponse(
        entries=[AuditLogEntry.model_validate(r) for r in rows],
        total=total,
    )
