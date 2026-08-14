"""问答接口：检索增强生成（普通 + 流式 SSE）。"""
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, check_rate_limit
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import rag_service

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
