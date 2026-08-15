"""审计服务（P1-5）：操作留痕写入 audit_logs，责任可追溯。

写审计尽量与业务同事务：业务 commit 时审计一起落库，操作即留痕。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


async def record(
    db: AsyncSession,
    actor: User,
    action: str,
    object_type: str | None = None,
    object_id: int | None = None,
    detail: str | None = None,
) -> None:
    """记录一条审计日志（随当前事务一起提交）。"""
    db.add(
        AuditLog(
            actor_id=actor.id,
            actor_username=actor.username,
            department=actor.department,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail=detail,
        )
    )
