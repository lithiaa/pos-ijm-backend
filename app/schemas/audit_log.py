from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    created_at: str
    user_id: int | None
    username: str | None
    action: str
    http_method: str
    resource: str
    resource_id: str | None
    path: str
    status_code: int
    ip_address: str | None
    summary: dict[str, Any]


class AuditLogListResponse(BaseModel):
    total: int
    page: int
    limit: int
    data: list[AuditLogOut]
