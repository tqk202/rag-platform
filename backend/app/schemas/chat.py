"""问答相关接口结构：回答必须带引文，这是降低幻觉的关键设计。"""
from pydantic import BaseModel, field_validator


class Citation(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    page_no: int | None = None


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]

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
