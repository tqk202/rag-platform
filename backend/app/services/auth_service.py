"""认证服务：注册与登录 + 管理员用户管理。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import (
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserCreateAdmin,
    UserLogin,
    UserUpdate,
)


async def register(db: AsyncSession, data: UserCreate) -> User:
    exists = await db.scalar(select(User).where(User.username == data.username))
    if exists:
        raise AppError("用户名已存在")
    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        department=data.department,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login(db: AsyncSession, data: UserLogin) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == data.username))
    if user is None or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("用户名或密码错误")
    if not user.is_active:
        raise UnauthorizedError("账号已被禁用")
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


async def create_user(db: AsyncSession, data: UserCreateAdmin) -> User:
    """管理员建号：注册接口只能建 member，这里可指定 role/department。"""
    exists = await db.scalar(select(User).where(User.username == data.username))
    if exists:
        raise AppError("用户名已存在")
    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        department=data.department,
        role=data.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(
    db: AsyncSession, user: User, data: PasswordChange
) -> None:
    """用户改自己的密码：先校验原密码，再写新哈希。"""
    if not verify_password(data.old_password, user.hashed_password):
        raise AppError("原密码不正确")
    user.hashed_password = hash_password(data.new_password)
    await db.commit()


async def update_user(db: AsyncSession, user_id: int, data: UserUpdate) -> User:
    """管理员改号：角色 / 部门 / 启用状态。"""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    if data.role is not None:
        user.role = data.role
    if data.department is not None:
        user.department = data.department
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return user
