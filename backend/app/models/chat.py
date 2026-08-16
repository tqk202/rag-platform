"""会话历史表：问答落库，刷新不丢，支持多轮复盘。"""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chat import ChatMessage


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    # 多知识库：会话创建/提问时绑定的知识库名（快照，不随库改名漂移）
    knowledge_base: Mapped[str | None] = mapped_column(String(64), nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # 引文存 JSON 字符串（schema 层解析回列表）；无引文存 NULL
    citations: Mapped[str | None] = mapped_column(Text, nullable=True)
    no_answer: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
