"""问答相关接口结构：回答必须带引文，这是降低幻觉的关键设计。"""
from pydantic import BaseModel


class Citation(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    page_no: int | None = None


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    no_answer: bool = False
