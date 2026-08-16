"""回答反馈表：用户对 LLM 回答的点赞/点踩，构成「反馈 → badcase → 评测集」闭环。

同一条消息同一用户只留一行（UniqueConstraint），再次提交同倾向 = 取消（toggle），
异倾向 = 切换。点踩数据由 scripts/export_badcases.py 导出成候选 badcase 供人工
审核入黄金评测集。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    sentiment: Mapped[str] = mapped_column(String(16))  # like | dislike
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
