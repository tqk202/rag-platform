"""通用结构：分页、批量删除、审计清理。"""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class BatchDeleteRequest(BaseModel):
    """管理端批量删除：单删复用（ids 传单元素）。"""

    ids: list[int] = Field(min_length=1)


class AuditCleanupRequest(BaseModel):
    """审计日志按时间清理：仅删除 N 天前的记录，近期留痕保留。"""

    before_days: int = Field(ge=1, le=3650)
