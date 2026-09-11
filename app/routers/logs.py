import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogListResponse


router = APIRouter(prefix="/api/logs", tags=["logs"])


def require_admin(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def _created_at(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _out(row: AuditLog) -> dict:
    try:
        summary = json.loads(row.summary)
    except (TypeError, json.JSONDecodeError):
        summary = {"request": {"_unavailable": True}}
    return {
        "id": row.id,
        "created_at": _created_at(row.created_at),
        "user_id": row.user_id,
        "username": row.username,
        "action": row.action,
        "http_method": row.http_method,
        "resource": row.resource,
        "resource_id": row.resource_id,
        "path": row.path,
        "status_code": row.status_code,
        "ip_address": row.ip_address,
        "summary": summary,
    }


@router.get("", response_model=AuditLogListResponse)
def list_logs(
    q: str | None = Query(None),
    action: str | None = Query(None),
    resource: str | None = Query(None),
    user: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    sort_by: Literal[
        "id",
        "created_at",
        "user_id",
        "username",
        "action",
        "resource",
        "resource_id",
        "status_code",
        "ip_address",
    ] = Query("created_at"),
    sort_order: Literal["ASC", "DESC"] = Query("DESC"),
    page: int = Query(1, ge=1),
    skip: int | None = Query(None, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    query = db.query(AuditLog)
    term = (q or "").strip()
    if term:
        contains = f"%{term}%"
        query = query.filter(
            or_(
                AuditLog.username.ilike(contains),
                AuditLog.action.ilike(contains),
                AuditLog.resource.ilike(contains),
                AuditLog.resource_id.ilike(contains),
                AuditLog.path.ilike(contains),
                AuditLog.ip_address.ilike(contains),
                AuditLog.summary.ilike(contains),
                cast(AuditLog.status_code, String).ilike(contains),
            )
        )
    if action and action.strip():
        query = query.filter(AuditLog.action == action.strip().upper())
    if resource and resource.strip():
        query = query.filter(AuditLog.resource == resource.strip())
    if user and user.strip():
        actor = user.strip()
        actor_filter = AuditLog.username.ilike(f"%{actor}%")
        if actor.isdigit():
            actor_filter = or_(actor_filter, AuditLog.user_id == int(actor))
        query = query.filter(actor_filter)
    if date_from:
        query = query.filter(
            AuditLog.created_at >= datetime.combine(date_from, time.min)
        )
    if date_to:
        query = query.filter(
            AuditLog.created_at < datetime.combine(date_to, time.min) + timedelta(days=1)
        )

    total = query.count()
    order_column = getattr(AuditLog, sort_by)
    primary_order = order_column.asc() if sort_order == "ASC" else order_column.desc()
    id_order = AuditLog.id.asc() if sort_order == "ASC" else AuditLog.id.desc()
    offset = skip if skip is not None else (page - 1) * limit
    rows = query.order_by(primary_order, id_order).offset(offset).limit(limit).all()
    return {
        "total": total,
        "page": (offset // limit) + 1,
        "limit": limit,
        "data": [_out(row) for row in rows],
    }
