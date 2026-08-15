"""审计日志结构（P1-5）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_username: str | None
    department: str | None
    action: str
    object_type: str | None
    object_id: int | None
    detail: str | None
    created_at: datetime
