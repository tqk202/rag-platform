"""W9 外部依赖重试测试：可恢复错误自动重试、不可恢复错误不重试、耗尽后抛错。

用 httpx.MockTransport 模拟上游故障，不发起真实网络请求、不花 API 钱。
退避时长在 fixture 里压到近零，测试不用真等。
"""
import asyncio

import httpx
import pytest

from app.core import http_retry
from app.services.embedding_service import ApiEmbeddingProvider
from app.services.llm_service import OpenAICompatibleLLM
from app.services.rerank_service import ApiReranker

BASE = "http://mock"
API_KEY = "test-key"
MODEL = "test-model"

CHUNKS = [{"no": 1, "content": "员工年假每年10天，需提前申请。"}]


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """把退避时长压到近零：只测重试行为，不测真实等待。"""
    monkeypatch.setattr(http_retry, "DEFAULT_BASE", 0.001)
    monkeypatch.setattr(http_retry, "DEFAULT_CAP", 0.01)


def _llm(handler):
    return OpenAICompatibleLLM(BASE, API_KEY, MODEL, transport=httpx.MockTransport(handler))


def _embed(handler):
    return ApiEmbeddingProvider(BASE, API_KEY, MODEL, transport=httpx.MockTransport(handler))


def _rerank(handler):
    return ApiReranker(BASE, API_KEY, MODEL, transport=httpx.MockTransport(handler))


def _ok_llm_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_llm_retries_on_500():
    """500（瞬时故障）应自动重试一次后成功，最终只返回一次成功结果。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(200, json=_ok_llm_body("你好"), request=request)

    result = await _llm(handler).generate("年假怎么休", CHUNKS)
    assert result.answer == "你好"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_llm_4xx_not_retried():
    """400（参数/请求错误）不重试——重放也必然失败，白花钱。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(400, json={"error": "bad request"}, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        await _llm(handler).generate("年假怎么休", CHUNKS)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_llm_503_exhausts_retries():
    """持续 503：重试耗尽后抛最后一次 HTTPStatusError，不再无限重试。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(503, request=request)

    with pytest.raises(httpx.HTTPStatusError):
        await _llm(handler).generate("年假怎么休", CHUNKS)
    assert len(calls) == http_retry.DEFAULT_ATTEMPTS  # 默认 3 次尝试


@pytest.mark.asyncio
async def test_llm_transport_error_retries():
    """网络层错误（连接拒绝）属瞬时故障，应重试。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=_ok_llm_body("你好"), request=request)

    result = await _llm(handler).generate("年假怎么休", CHUNKS)
    assert result.answer == "你好"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_embedding_retries_on_500():
    """嵌入（同步 Client）同样走重试。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}, request=request
        )

    vectors = _embed(handler).embed_texts(["员工年假每年10天"])
    assert vectors == [[0.1, 0.2, 0.3]]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_rerank_retries_on_500():
    """重排（异步 Client）同样走重试。"""
    calls: list[str] = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(500, request=request)
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]}, request=request)

    out = await _rerank(handler).rerank("年假怎么休", [{"content": "员工年假每年10天"}])
    assert out[0]["rerank_score"] == 0.9
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retry_after_header_respected(monkeypatch):
    """429 带 Retry-After 时用服务端给的时长重试，不按退避算法。"""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls: list[int] = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "5"},
                request=httpx.Request("POST", "http://x"),
            )
        return httpx.Response(200, request=httpx.Request("POST", "http://x"))

    resp = await http_retry.async_retry(fn)
    assert resp.status_code == 200
    # Retry-After=5 被读到，但受 DEFAULT_CAP 封顶（本测试 fixture 压到 0.01）
    # —— 若未读 Retry-After，会走退避 ≈0.001，两者数值差一个数量级
    assert sleeps == [min(5.0, http_retry.DEFAULT_CAP)]
