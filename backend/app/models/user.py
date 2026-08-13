"""用户表：RBAC 角色 + 部门归属（多租户的"租户"维度）。"""
import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Role(str, enum.Enum):
    admin = "admin"      # 管理员：管理全平台/权限/用户
    manager = "manager"  # 部门管理员：管理本部门文档
    member = "member"    # 普通成员：问答


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.member)
    department: Mapped[str] = mapped_column(String(64), default="default", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
