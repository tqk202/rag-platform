"""问答接口：检索增强生成（普通 + 流式 SSE）+ 会话历史。"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, check_rate_limit
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionDetail,
    ChatSessionOut,
)
from app.services import chat_session_service, rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="问答")
async def chat(
    db: DbSession,
    user: CurrentUser,
    data: ChatRequest,
    _rl: None = Depends(check_rate_limit),
) -> ChatResponse:
    return await rag_service.answer(db, user, data)


@router.post("/stream", summary="问答（流式 SSE）")
async def chat_stream(
    db: DbSession,
    user: CurrentUser,
    data: ChatRequest,
    _rl: None = Depends(check_rate_limit),
):
    async def event_stream():
        try:
            async for event, payload in rag_service.stream_answer(db, user, data):
                # SSE 协议：每个事件 = "event: 名字\ndata: JSON\n\n"
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("流式问答失败")
            yield f"event: error\ndata: {json.dumps({'detail': '回答生成失败，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions", response_model=list[ChatSessionOut], summary="我的会话列表")
async def list_sessions(db: DbSession, user: CurrentUser) -> list[ChatSessionOut]:
    return await chat_session_service.list_sessions(db, user)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail, summary="会话详情")
async def get_session(
    session_id: int, db: DbSession, user: CurrentUser
) -> ChatSessionDetail:
    session, messages = await chat_session_service.get_session_with_messages(
        db, user, session_id
    )
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages,
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: int, db: DbSession, user: CurrentUser
) -> dict:
    await chat_session_service.delete_session(db, user, session_id)
    return {"ok": True}
