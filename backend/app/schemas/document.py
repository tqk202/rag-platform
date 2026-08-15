"""文档相关接口结构。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    file_name: str
    status: DocStatus
    failure_reason: str | None = None  # W10 处理失败原因，前端展示 + 判断能否重试
    version: int
    department: str
    chunk_count: int
    created_at: datetime


class ChunkOut(BaseModel):
    """文档详情里的切片：按序全文展示，供引文跳转定位。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    page_no: int | None = None


class DocumentDetail(DocumentOut):
    chunks: list[ChunkOut] = []


class UploadResponse(BaseModel):
    document_id: int
    message: str
