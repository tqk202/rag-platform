"""知识库接口结构：建库 / 列表 / 更新。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class KnowledgeBaseCreate(BaseModel):
    name: str
    department: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("知识库名称不能为空")
        return v


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    department: str
    description: str | None = None
    is_active: bool
    document_count: int = 0
    created_at: datetime
