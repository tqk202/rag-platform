"""真实后端（SiliconFlow API）的离线单元测试。

不真正调网络——用假 httpx client 验证：请求体符合 OpenAI 兼容协议、
返回解析正确（按 index 对齐、按 relevance_score 重排）。
"""
import pytest

from app.services import embedding_service, rerank_service


class _FakeResp:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class _FakeSyncClient:
    """假同步 client：记录请求，返回按 index 对齐的嵌入。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        texts = kwargs["json"]["input"]
        data = [{"index": i, "embedding": [float(i + 1), 0.0]} for i in range(len(texts))]
        return _FakeResp({"data": data})


class _FakeAsyncClient:
    """假异步 client：记录请求，返回按 relevance_score 排序的重排结果。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        docs = kwargs["json"]["documents"]
        results = [{"index": i, "relevance_score": float(i)} for i in range(len(docs))]
        return _FakeResp({"results": results})


def test_api_embedding_openai_compatible_payload(monkeypatch):
    fake = _FakeSyncClient()
    monkeypatch.setattr(embedding_service.httpx, "Client", lambda **kw: fake)

    prov = embedding_service.ApiEmbeddingProvider("https://x.example/v1", "key", "BAAI/bge-m3")
    vecs = prov.embed_texts(["第一段", "第二段", "第三段"])

    assert len(vecs) == 3
    assert vecs[2] == [3.0, 0.0]  # 按返回 index 对齐，不是乱序
    url, kwargs = fake.calls[0]
    assert url == "https://x.example/v1/embeddings"
    assert kwargs["headers"]["Authorization"] == "Bearer key"
    assert kwargs["json"] == {"model": "BAAI/bge-m3", "input": ["第一段", "第二段", "第三段"]}


def test_api_embedding_batches_large_lists(monkeypatch):
    fake = _FakeSyncClient()
    monkeypatch.setattr(embedding_service.httpx, "Client", lambda **kw: fake)

    prov = embedding_service.ApiEmbeddingProvider("https://x.example/v1", "key", "m")
    vecs = prov.embed_texts([f"t{i}" for i in range(40)])

    assert len(vecs) == 40
    assert len(fake.calls) == 2  # 32 + 8，分批
    assert len(fake.calls[0][1]["json"]["input"]) == 32
    assert len(fake.calls[1][1]["json"]["input"]) == 8


@pytest.mark.asyncio
async def test_api_reranker_reorders_by_score(monkeypatch):
    fake = _FakeAsyncClient()
    monkeypatch.setattr(rerank_service.httpx, "AsyncClient", lambda **kw: fake)

    rk = rerank_service.ApiReranker("https://x.example/v1", "key", "bge-reranker-v2-m3")
    chunks = [{"content": f"第{i}段内容"} for i in range(3)]
    out = await rk.rerank("问题", chunks)

    # 分数 = index（0,1,2）→ 降序后最后一段排最前
    assert [c["content"] for c in out] == ["第2段内容", "第1段内容", "第0段内容"]
    assert out[0]["rerank_score"] == 2.0
    url, kwargs = fake.calls[0]
    assert url == "https://x.example/v1/rerank"
    assert kwargs["json"]["query"] == "问题"
    assert kwargs["json"]["documents"] == ["第0段内容", "第1段内容", "第2段内容"]
