"""统一业务异常：路由层抛 AppError，由全局 handler 转成统一 JSON 结构。"""
import math

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.ratelimit import RateLimitExceeded


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
