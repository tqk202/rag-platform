"""统一业务异常：路由层抛 AppError，由全局 handler 转成统一 JSON 结构。

还兜底两类"角落"（W6 边界打磨）：
- httpx 错误（LLM/上游 HTTP 服务挂了/超时）→ 502，不把裸 500 甩给用户
- 未捕获异常 → 500 统一 JSON，真实堆栈进日志
"""
import logging
import math

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.ratelimit import RateLimitExceeded

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        # 429 按 HTTP 规范必须带 Retry-After，告诉客户端等多久再重试
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "code": "RATE_LIMITED"},
            headers={"Retry-After": str(math.ceil(exc.retry_after))},
        )

    @app.exception_handler(httpx.HTTPStatusError)
    async def _upstream_http_error(_: Request, exc: httpx.HTTPStatusError) -> JSONResponse:
        # 上游（LLM 等）返回了 4xx/5xx：错误码+状态进日志，用户只看到友好提示
        logger.warning("上游服务返回异常状态 %s：%s", exc.response.status_code, exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "生成服务暂不可用，请稍后重试", "code": "UPSTREAM_ERROR"},
        )

    @app.exception_handler(httpx.RequestError)
    async def _upstream_unavailable(_: Request, exc: httpx.RequestError) -> JSONResponse:
        # 上游连不上/超时（HTTPStatusError 是 RequestError 子类，优先走上面的 handler）
        logger.warning("上游服务不可用：%r", exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "生成服务暂不可用，请稍后重试", "code": "UPSTREAM_UNAVAILABLE"},
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        # 最后一道防线：任何漏网的异常都转成统一 JSON，而不是 FastAPI 的裸 500 文本
        logger.exception("未捕获异常：%r", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试", "code": "INTERNAL_ERROR"},
        )
