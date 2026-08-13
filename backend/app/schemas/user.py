"""用户/认证相关接口结构。"""
from pydantic import BaseModel, ConfigDict, Field

from app.models.user import Role


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    department: str = "default"


class UserLogin(BaseModel):
    username: str
    password: str


class UserCreateAdmin(BaseModel):
    """管理员创建用户：可指定角色与部门（注册接口只能建普通成员）。"""
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    department: str = "default"
    role: Role = Role.member


class UserUpdate(BaseModel):
    """管理员更新用户：改角色 / 部门 / 启用状态。"""
    role: Role | None = None
    department: str | None = None
    is_active: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    department: str
    is_active: bool
