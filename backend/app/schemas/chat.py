"""问答相关接口结构：回答必须带引文，这是降低幻觉的关键设计。

会话历史（W6.5）：/chat 带可选 session_id 时落库到指定会话，不带则自动新建，
响应统一返回 session_id，供前端刷新不丢。
"""
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class Citation(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    page_no: int | None = None


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]
    session_id: int | None = None  # 带则追加到该会话；不带则自动新建
    # 多知识库：指定库名则在库内检索；None = 部门内全部知识库
    knowledge_base: str | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, v: str) -> str:
        # 空问题/纯空格问题直接拒绝：检索和 LLM 调用都花钱，API 层自己把关
        v = v.strip()
        if not v:
            raise ValueError("问题不能为空")
        return v


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    no_answer: bool = False
    session_id: int | None = None
    message_id: int | None = None  # 回答消息 id（前端点赞/点踩绑定）


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    citations: list[Citation] = []
    no_answer: bool = False
    created_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _parse_citations(cls, v):
        # DB 里是 JSON 字符串，schema 层解析回列表
        if isinstance(v, str):
            return json.loads(v) if v else []
        return v or []


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    knowledge_base: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut] = []
