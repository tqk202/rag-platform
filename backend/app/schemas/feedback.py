"""回答反馈接口结构：提交 / 管理端列表。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class FeedbackCreate(BaseModel):
    sentiment: str
    comment: str | None = None

    @field_validator("sentiment")
    @classmethod
    def _sentiment_valid(cls, v: str) -> str:
        if v not in ("like", "dislike"):
            raise ValueError("sentiment 只能是 like 或 dislike")
        return v


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    department: str
    message_id: int
    sentiment: str
    comment: str | None = None
    question: str | None = None  # 该回答对应的问题（同会话上一条 user 消息）
    answer: str | None = None    # 被反馈的回答内容
    created_at: datetime
