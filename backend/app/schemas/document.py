"""文档相关接口结构。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

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
    knowledge_base: str | None = None  # 多知识库：文档归属库名
    chunk_count: int
    created_at: datetime

    @field_validator("knowledge_base", mode="before")
    @classmethod
    def _kb_from_relationship(cls, v):
        # DB 里是 relationship 对象，这里取 name 字符串
        if hasattr(v, "name"):
            return v.name
        return v


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
