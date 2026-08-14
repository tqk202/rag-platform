"""向量化服务：把文本转成向量。

mock: 哈希占位向量，跑通链路用（无语义，仅验证流程）。
api: 真实嵌入（SiliconFlow bge-m3 等，OpenAI 兼容 /embeddings 协议）。
接口统一，实现可替换——生产切 bge-m3/qwen 只改配置不改代码。
"""
import hashlib
import math
import random

import httpx

from app.core.config import get_settings

settings = get_settings()


class EmbeddingProvider:
    """向量化接口。所有真实实现都需要提供 embed_texts。"""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class MockEmbeddingProvider(EmbeddingProvider):
    """模拟向量：以文本哈希为种子生成固定向量，同一文本永远得到同一向量。"""

    def __init__(self, dim: int):
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        vec = [rng.uniform(-1, 1) for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class ApiEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容嵌入 API（SiliconFlow 等）：POST {base_url}/embeddings。

    与 LLM 同一套协议，切模型只改 EMBEDDING_MODEL。接口是同步的
    （与 Mock 一致）；生产环境嵌入发生在 Celery worker，不阻塞 API，
    评测是串行脚本，均无并发问题。
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=90)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # 分批调用，避免单请求过大（文档切片可能上百条）
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            out.extend(self._embed_batch(texts[i : i + 32]))
        return out


def get_embedding_provider() -> EmbeddingProvider:
    """按配置返回向量化实现（EMBEDDING_BACKEND: mock | api | local）。"""
    backend = settings.EMBEDDING_BACKEND
    if backend == "mock":
        return MockEmbeddingProvider(settings.EMBEDDING_DIM)
    if backend == "api":
        if not settings.EMBEDDING_API_KEY:
            raise RuntimeError("EMBEDDING_BACKEND=api 但未配置 EMBEDDING_API_KEY（backend/.env）")
        return ApiEmbeddingProvider(
            base_url=settings.EMBEDDING_BASE_URL,
            api_key=settings.EMBEDDING_API_KEY,
            model=settings.EMBEDDING_MODEL,
        )
    raise NotImplementedError(f"embedding backend 未实现: {backend}")
