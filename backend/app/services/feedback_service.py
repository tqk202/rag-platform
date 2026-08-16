"""回答反馈服务：提交（点赞/点踩切换）/ 管理端列表。

反馈是「用户对 LLM 回答」的质量信号，构成闭环：dislike 数据由
scripts/export_badcases.py 导出成候选 badcase，人工审核后并入黄金评测集。
同一条消息同用户只留一行：再点同倾向 = 取消，点不同倾向 = 切换。
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.chat import ChatMessage, ChatSession
from app.models.feedback import AnswerFeedback
from app.models.user import User
from app.schemas.feedback import FeedbackOut


async def _own_message(db: AsyncSession, message_id: int, user: User) -> ChatMessage:
    """取自己的消息：消息必须属于当前用户的会话，否则 404/403。"""
    message = await db.get(ChatMessage, message_id)
    if message is None:
        raise NotFoundError("消息不存在")
    session = await db.get(ChatSession, message.session_id)
    if session is None or session.user_id != user.id:
        raise PermissionDeniedError("无权操作该消息")
    return message


async def submit_feedback(
    db: AsyncSession,
    user: User,
    message_id: int,
    sentiment: str,
    comment: str | None = None,
) -> dict:
    """提交反馈：同倾向再点 = 取消；异倾向 = 切换；无记录 = 新增。"""
    await _own_message(db, message_id, user)

    existing = await db.scalar(
        select(AnswerFeedback).where(
            AnswerFeedback.user_id == user.id,
            AnswerFeedback.message_id == message_id,
        )
    )
    if existing is not None and existing.sentiment == sentiment:
        # 再点同倾向：取消反馈
        await db.delete(existing)
        await db.commit()
        return {"sentiment": None, "message": "已取消反馈"}
    if existing is not None:
        existing.sentiment = sentiment
        existing.comment = comment
        await db.commit()
        return {"sentiment": sentiment, "message": "已切换反馈"}
    db.add(
        AnswerFeedback(
            user_id=user.id, message_id=message_id, sentiment=sentiment, comment=comment
        )
    )
    await db.commit()
    return {"sentiment": sentiment, "message": "已提交反馈"}


async def list_feedback(
    db: AsyncSession,
    sentiment: str | None = None,
    actor_username: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FeedbackOut], int]:
    """管理端列表：反馈 + 被反馈回答 + 对应问题（同会话上一条 user 消息）。"""
    conditions = []
    if sentiment:
        conditions.append(AnswerFeedback.sentiment == sentiment)
    if actor_username:
        conditions.append(User.username == actor_username)

    total = await db.scalar(
        select(func.count()).select_from(AnswerFeedback).where(*conditions)
    ) or 0

    stmt = (
        select(AnswerFeedback, ChatMessage.content, User.username, User.department, ChatMessage.session_id)
        .join(ChatMessage, ChatMessage.id == AnswerFeedback.message_id)
        .join(User, User.id == AnswerFeedback.user_id)
        .where(*conditions)
        .order_by(AnswerFeedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    items: list[FeedbackOut] = []
    for fb, answer, username, department, session_id in rows:
        # 该回答的前一条 user 消息 = 问题
        question = await db.scalar(
            select(ChatMessage.content)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
                ChatMessage.id < fb.message_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        items.append(
            FeedbackOut(
                id=fb.id,
                user_id=fb.user_id,
                username=username,
                department=department,
                message_id=fb.message_id,
                sentiment=fb.sentiment,
                comment=fb.comment,
                question=question,
                answer=answer,
                created_at=fb.created_at,
            )
        )
    return items, total
