"""认证接口：注册 + 登录。"""
from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.user import TokenResponse, UserCreate, UserLogin, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, summary="注册")
async def register(db: DbSession, data: UserCreate) -> UserOut:
    return await auth_service.register(db, data)


@router.post("/login", response_model=TokenResponse, summary="登录")
async def login(db: DbSession, data: UserLogin) -> TokenResponse:
    return await auth_service.login(db, data)
