"""可观测性：request_id 全链路追踪 + 结构化访问日志。

核心思路：用 contextvars 把 request_id 注入当前协程上下文，
不用给每个函数签名传参，就能让同一请求的整条链
（鉴权→检索→LLM→响应）的日志都带上同一个 request_id。
线上遇到一条坏回答，拿它的 request_id 一捞，这条链上的日志全出来了。
"""
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def install_request_id_logging() -> None:
    """让每条日志记录都带 rid 字段（从 contextvar 实时读取），配合格式里的 %(rid)s。

    用 setLogRecordFactory 而不是 logger/handler 加 Filter：
    后者只对经过某些 logger/handler 的记录生效，第三方库直接打的日志会漏，
    一格式化就崩"Formatting field not found"。工厂方法保证所有记录无一遗漏。
    """
    _orig_factory = logging.getLogRecordFactory()

    def _factory(*args, **kwargs):
        record = _orig_factory(*args, **kwargs)
        record.rid = request_id_var.get()
        return record

    logging.setLogRecordFactory(_factory)


class RequestIDMiddleware:
    """纯 ASGI 中间件：分配 request_id、注入响应头、记录访问日志。

    故意不用 BaseHTTPMiddleware：它会缓存整个响应体，把 SSE 流式输出打断。
    纯 ASGI 写法只拦 http 类型，响应头注入在 send 包装里做，流式不受影响。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 透传上游（网关/负载均衡）已分配的 request_id，否则自己生成——分布式追踪的接入口
        request_id = None
        for name, value in scope["headers"]:
            if name == b"x-request-id":
                request_id = value.decode("ascii", "ignore")
                break
        if not request_id:
            request_id = uuid.uuid4().hex

        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status: int | None = None

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (n, v) for n, v in message.get("headers", []) if n != b"x-request-id"
                ]
                message["headers"] = [*headers, (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "http %s %s -> %s (%.1f ms)",
                scope.get("method", ""),
                scope.get("path", ""),
                status or "?",
                duration_ms,
            )
            request_id_var.reset(token)
