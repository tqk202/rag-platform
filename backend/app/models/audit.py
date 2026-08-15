"""审计日志表（P1-5）：谁在何时对什么做了什么，责任可追溯（企业合规）。

操作留痕是"可交付企业级"的硬要求——能删数据不留痕的系统进不了企业。
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

if TYPE_CHECKING:
    pass


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 冗余，防用户删除后无法追溯
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # document.upload 等
    object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # document
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
