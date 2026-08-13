"""向量化服务：把文本转成向量。

当前用 MockEmbeddingProvider 跑通全流程（不依赖密钥/模型下载）。
设计为可替换接口：之后接真实模型（API 或本地 bge-m3）只改这里。
"""
import hashlib
import math
import random

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


def get_embedding_provider() -> EmbeddingProvider:
    """按配置返回向量化实现（EMBEDDING_BACKEND: mock | api | local）。"""
    backend = settings.EMBEDDING_BACKEND
    if backend == "mock":
        return MockEmbeddingProvider(settings.EMBEDDING_DIM)
    raise NotImplementedError(f"embedding backend 未实现: {backend}")
