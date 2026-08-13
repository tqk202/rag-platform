"""FastAPI 依赖：注入数据库会话、解析当前用户、角色校验。"""
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import Role, User

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    payload = decode_access_token(token)  # 无效/过期会抛 UnauthorizedError
    user_id = payload.get("sub")
    if user_id is None:
        raise UnauthorizedError("无效的登录态")
    user = await db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已被禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role):
    """返回一个依赖，校验当前用户是否为指定角色之一。"""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("没有权限执行该操作")
        return user

    return checker
