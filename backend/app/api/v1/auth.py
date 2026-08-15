"""认证接口：注册 + 登录 + 登出。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import DbSession, oauth2_scheme
from app.core.ratelimit import RateLimiter, RateLimitExceeded
from app.core.security import token_jti_and_ttl
from app.core.token_blacklist import revoke
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# P1-3 登录防爆破：每「用户名+IP」每分钟最多 10 次尝试（令牌桶），超限 429
_login_limiter = RateLimiter(capacity=10, refill_rate=10 / 60)


def reset_login_limiter() -> None:
    """测试用：清空登录限流桶（测试共用同一 client IP，会跨用例累积）。"""
    _login_limiter.reset()


@router.post("/register", response_model=UserOut, summary="注册")
async def register(db: DbSession, data: UserCreate) -> UserOut:
    return await auth_service.register(db, data)


@router.post("/login", response_model=TokenResponse, summary="登录")
async def login(request: Request, db: DbSession, data: UserLogin) -> TokenResponse:
    ip = request.client.host if request.client else "-"
    allowed, retry_after = await _login_limiter.allow(f"{data.username}:{ip}")
    if not allowed:
        raise RateLimitExceeded(retry_after)
    return await auth_service.login(db, data)


@router.post("/logout", summary="登出")
async def logout(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    # 把 token 的 jti 拉黑到过期为止，之后任何请求 401
    jti, ttl = token_jti_and_ttl(token)
    await revoke(jti, ttl)
    return {"ok": True}
