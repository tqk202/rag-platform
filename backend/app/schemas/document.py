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
    version: int
    department: str
    chunk_count: int
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: int
    message: str
