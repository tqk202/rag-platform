"""v1 路由汇总：所有业务接口挂载点。"""
from fastapi import APIRouter

from app.api.v1 import auth, chat, documents, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
