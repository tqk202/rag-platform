"""文档表：文档生命周期 + 版本管理 + 部门权限归属。"""
import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class DocStatus(str, enum.Enum):
    pending = "pending"        # 已上传，待处理
    processing = "processing"  # 解析/切片/向量化中
    ready = "ready"            # 已就绪，可被检索
    failed = "failed"          # 处理失败


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # 内容去重
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus), default=DocStatus.pending, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)  # W10 失败原因（前端可看、可判断是否重试）
    version: Mapped[int] = mapped_column(Integer, default=1)
    department: Mapped[str] = mapped_column(String(64), index=True)  # 文档归属部门（权限过滤键）
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
