"""会话历史服务：问答落库 + 会话 CRUD。

设计要点：
- 会话属于用户：跨用户访问一律 404，不暴露他人会话存在。
- 落库整段「问题 + 回答 + 引文」，历史完整可复盘。
- 新会话标题取第一问截断；已建会话追加消息时刷新 updated_at（会话列表按它倒序）。
"""
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import Citation


def _first_question_title(question: str) -> str:
    q = question.strip()
    return (q[:30] + "…") if len(q) > 30 else (q or "新会话")


async def _own_session(db: AsyncSession, session_id: int, user: User) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise NotFoundError("会话不存在")
    return session


async def save_exchange(
    db: AsyncSession,
    user: User,
    session_id: int | None,
    question: str,
    answer: str,
    citations: list[Citation],
    no_answer: bool,
) -> ChatSession:
    """把一问一答写入（或新建）会话，返回会话。"""
    if session_id is not None:
        session = await _own_session(db, session_id, user)
    else:
        session = ChatSession(user_id=user.id, title=_first_question_title(question))
        db.add(session)
        await db.flush()

    db.add(
        ChatMessage(
            session_id=session.id,
            role="user",
            content=question,
            citations=None,
            no_answer=False,
        )
    )
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=json.dumps(
                [c.model_dump() for c in citations], ensure_ascii=False
            ),
            no_answer=no_answer,
        )
    )
    # 显式刷新 updated_at：子表插消息不会自动触发父表 onupdate，会话列表要按它排序
    session.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return session


async def list_sessions(db: AsyncSession, user: User) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def get_session_with_messages(
    db: AsyncSession, user: User, session_id: int
) -> tuple[ChatSession, list[ChatMessage]]:
    session = await _own_session(db, session_id, user)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
    )
    messages = list((await db.scalars(stmt)).all())
    return session, messages


async def delete_session(db: AsyncSession, user: User, session_id: int) -> None:
    session = await _own_session(db, session_id, user)
    await db.delete(session)  # cascade 会连带删掉 messages
    await db.commit()
