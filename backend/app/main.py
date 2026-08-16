"""FastAPI 应用入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.observability import RequestIDMiddleware, install_request_id_logging

settings = get_settings()

# 让 app.* 的 INFO 日志可见（uvicorn 默认只显示它自己的 logger）。
# 结构化为每条日志带 [rid=...]，配合 request_id 中间件做全链路追踪（W5）。
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [rid=%(rid)s] %(message)s",
    )
install_request_id_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # schema 由 Alembic 管理：部署/启动前先跑 `alembic upgrade head`
    # （docker compose 的 backend 命令已自动执行），这里不再建表
    from app.db.session import engine

    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    # P1-4：CORS 白名单配置化（默认 * 开发放开，生产设前端域名）
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 后加的中间件在外层先执行：request_id 在 CORS 之前分配，访问日志覆盖所有请求
app.add_middleware(RequestIDMiddleware)

register_exception_handlers(app)

from app.api.v1.router import api_router  # noqa: E402

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"], summary="健康检查")
async def health() -> dict:
    return {"status": "ok"}
