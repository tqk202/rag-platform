"""用户接口：当前用户信息 + 管理员用户管理（列表/创建/改角色）。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.user import Role, User
from app.schemas.user import UserCreateAdmin, UserOut, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])

AdminGuard = Annotated[User, Depends(require_role(Role.admin))]


@router.get("/me", response_model=UserOut, summary="当前用户信息")
async def me(user: CurrentUser) -> User:
    return user


@router.get("", response_model=list[UserOut], summary="用户列表（仅管理员）")
async def list_users(db: DbSession, _guard: AdminGuard) -> list[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


@router.post("", response_model=UserOut, summary="创建用户（仅管理员）")
async def create_user(
    db: DbSession, _guard: AdminGuard, data: UserCreateAdmin
) -> User:
    return await auth_service.create_user(db, data)


@router.patch("/{user_id}", response_model=UserOut, summary="更新用户（仅管理员）")
async def update_user(
    user_id: int, db: DbSession, _guard: AdminGuard, data: UserUpdate
) -> User:
    return await auth_service.update_user(db, user_id, data)
