"""外部 HTTP 依赖的统一重试：只重试可恢复的错误，避免重试风暴。

背景（生产痛点）：LLM / 嵌入 / 重排都是真实 API 调用。上游一次 429（限流）、
5xx（瞬时故障）或网络抖动，没有重试 = 聊天直接 502、入库整篇 failed——
系统对外部依赖没有自愈能力。

策略（面试点）：
- 只重试可恢复错误：429（尊重 Retry-After）/ 5xx / 传输错误（超时、连接重置）
- 4xx（400 参数错 / 401 鉴权错 / 422 校验错）不重试——重放也必然失败，白花钱
- 指数退避 + 抖动：base * 2^n，再乘 ±20% 随机因子，避免所有请求同时重试（重试风暴）
- 流式（SSE）不重试：半截内容已吐给用户，无法安全重放——在调用方显式不接入

用法（fn 只负责发起请求并返回 Response，重试判断在内部完成）：
    resp = await async_retry(lambda: client.post(url, ...))
    resp.raise_for_status()
重试耗尽后抛出最后一次的 HTTPStatusError / TransportError，由全局异常
handler 统一转 502（UPSTREAM_ERROR / UPSTREAM_UNAVAILABLE）。
"""
import asyncio
import random
import time
from collections.abc import Awaitable, Callable

import httpx

# 可重试状态码：429 限流（服务端可能马上恢复）+ 5xx 服务器瞬时故障
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 模块级可调参数：函数体内读取（而非参数默认值），测试可 monkeypatch 调快
DEFAULT_ATTEMPTS = 3
DEFAULT_BASE = 0.5  # 首次退避秒数
DEFAULT_CAP = 8.0  # 退避上限（秒）


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """指数退避 + 抖动：base * 2^n，再乘 ±20% 随机因子。"""
    exp = min(cap, base * (2**attempt))
    return exp * (0.8 + 0.4 * random.random())


def _next_delay(exc: BaseException | None, attempt: int, base: float, cap: float) -> float:
    """429 带 Retry-After 时优先尊重它（限流恢复时间已知，不必退避空等）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        header = exc.response.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), cap)
    return _backoff_delay(attempt, base, cap)


def retry(
    fn: Callable[[], httpx.Response],
    *,
    attempts: int | None = None,
    base: float | None = None,
    cap: float | None = None,
) -> httpx.Response:
    """同步重试（嵌入 API 用同步 httpx.Client，Celery worker 里跑）。"""
    attempts = DEFAULT_ATTEMPTS if attempts is None else attempts
    base = DEFAULT_BASE if base is None else base
    cap = DEFAULT_CAP if cap is None else cap
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            resp = fn()
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                return resp
            last_exc = httpx.HTTPStatusError(
                f"可重试状态码 {resp.status_code}", request=resp.request, response=resp
            )
        if attempt < attempts - 1:
            time.sleep(_next_delay(last_exc, attempt, base, cap))
    assert last_exc is not None
    raise last_exc


async def async_retry(
    fn: Callable[[], Awaitable[httpx.Response]],
    *,
    attempts: int | None = None,
    base: float | None = None,
    cap: float | None = None,
) -> httpx.Response:
    """异步重试（LLM / 重排 API 用异步 AsyncClient，API 进程里跑）。"""
    attempts = DEFAULT_ATTEMPTS if attempts is None else attempts
    base = DEFAULT_BASE if base is None else base
    cap = DEFAULT_CAP if cap is None else cap
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            resp = await fn()
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                return resp
            last_exc = httpx.HTTPStatusError(
                f"可重试状态码 {resp.status_code}", request=resp.request, response=resp
            )
        if attempt < attempts - 1:
            await asyncio.sleep(_next_delay(last_exc, attempt, base, cap))
    assert last_exc is not None
    raise last_exc
