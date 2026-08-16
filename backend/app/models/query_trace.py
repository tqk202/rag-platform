"""调用追踪表：每次问答的一条 trace，自建轻量可观测（不依赖 Langfuse）。

记录：谁在哪个部门/知识库问了什么、是否命中缓存、检索到几条、LLM 用了多少
token（estimate_tokens 近似）、每阶段耗时、最终回答预览。写入一律 best-effort
（异常不影响问答主链路），管理后台按时间线展示，配合 request_id 串起日志。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryTrace(Base):
    __tablename__ = "query_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_base: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0)
    no_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 阶段耗时 JSON：{"cache_ms":..,"retrieve_ms":..,"llm_ms":..}
    stage_timing: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_preview: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
