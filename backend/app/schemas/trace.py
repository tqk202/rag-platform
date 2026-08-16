"""调用追踪接口结构：管理端按时间线查看每次问答。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class QueryTraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str | None = None
    user_id: int | None = None
    department: str | None = None
    knowledge_base: str | None = None
    question: str
    rewritten_query: str | None = None
    cache_hit: bool
    retrieved_count: int
    no_answer: bool
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    latency_ms: int
    stage_timing: str | None = None  # JSON 串，前端展开
    answer_preview: str | None = None
    created_at: datetime
