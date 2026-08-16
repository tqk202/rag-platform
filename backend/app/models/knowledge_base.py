"""知识库表：多知识库支持的归属实体。

多租户从「部门单维度」升级为「部门 × 知识库」双维度：部门是硬隔离边界，
知识库是部门内的内容分组（如人力资源制度库 / 薪酬绩效库）。检索时两个维度
都落到向量/FTS 过滤，防止跨库串读。name 是业务键（与 department 一样以
字符串下沉到向量元数据与稀疏索引），department + name 唯一。
"""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    __table_args__ = (
        UniqueConstraint("department", "name", name="uq_kb_department_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    department: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    documents: Mapped[list["Document"]] = relationship(back_populates="knowledge_base")
