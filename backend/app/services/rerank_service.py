"""重排服务：召回 -> 重排精排 -> 取前 N 给 LLM 的三层管线中间层。

为什么重排（面试点）：
- 召回用 bi-encoder（问题和文档各自编码算相似度），快但粗
- 重排用 cross-encoder（问题和文档拼接过模型打分），精但慢
- 所以只对 top-k 重排——成本 O(n)，全文重排不现实

两个实现：
- lexical：轻量词法重排（查询词覆盖率 + 命中位置加分），免费、离线，
  诚实说明：词法信号和 BM25 有重叠，提升有限。
- api：真实 cross-encoder（SiliconFlow bge-reranker-v2-m3，OpenAI 兼容
  /rerank 协议），生产默认。RerankerProvider 同接口，切换只改 factory。
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
import jieba

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 极简停用词：只滤纯虚词，不滤"怎么/多少/如何"这类承载语义的词
_STOPWORDS = {"的", "了", "吗", "呢", "啊", "吧", "在", "和", "与", "或", "及", "或者", "以及"}


def _tokenize(text: str) -> list[str]:
    return [w.strip() for w in jieba.lcut(text) if w.strip() and w.strip() not in _STOPWORDS]


class RerankerProvider(ABC):
    """重排器抽象。真实 cross-encoder（bge-reranker）接入时实现同接口。"""

    @abstractmethod
    async def rerank(self, query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """输入：混合检索召回的结果。输出：追加 rerank_score 后按新分数降序。"""


class LexicalReranker(RerankerProvider):
    """轻量词法重排：查询词覆盖率 + 命中位置靠前加分。"""

    def _score(self, query: str, chunk: dict[str, Any]) -> float:
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return 0.0
        c_tokens = set(_tokenize(chunk["content"]))
        hit = q_tokens & c_tokens
        score = len(hit) / len(q_tokens)  # 覆盖率 [0,1]
        # 位置加分：查询词首次出现越靠前，越可能一开头就答到点
        content = chunk["content"]
        positions = [content.find(t) for t in hit if t in content]
        if positions:
            first = min(positions) / max(len(content), 1)
            score += 0.05 * (1 - first)
        return score

    async def rerank(self, query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for c in chunks:
            c["rerank_score"] = self._score(query, c)
        return sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)


class ApiReranker(RerankerProvider):
    """OpenAI 兼容重排 API（SiliconFlow bge-reranker-v2-m3）：POST {base_url}/rerank。

    真实 cross-encoder：query 与每条文档拼接打分，比词法重排更准。
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=90)

    async def rerank(self, query: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return chunks
        resp = await self._client.post(
            f"{self.base_url}/rerank",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "query": query,
                "documents": [c["content"] for c in chunks],
                "top_n": len(chunks),  # 全量打分，排序交给调用方截取前 N
            },
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        scores = {r["index"]: r.get("relevance_score", 0.0) for r in results}
        for i, c in enumerate(chunks):
            c["rerank_score"] = scores.get(i, 0.0)
        return sorted(chunks, key=lambda c: c["rerank_score"], reverse=True)


def get_reranker_provider() -> RerankerProvider | None:
    """工厂：按配置返回重排器。RERANKER_BACKEND=none 返回 None（关闭重排，W4 消融对比用）。"""
    if settings.RERANKER_BACKEND == "none":
        return None
    if settings.RERANKER_BACKEND == "lexical":
        return LexicalReranker()
    if settings.RERANKER_BACKEND == "api":
        if not settings.RERANKER_API_KEY:
            raise RuntimeError("RERANKER_BACKEND=api 但未配置 RERANKER_API_KEY（backend/.env）")
        return ApiReranker(
            base_url=settings.RERANKER_BASE_URL,
            api_key=settings.RERANKER_API_KEY,
            model=settings.RERANKER_MODEL,
        )
    raise RuntimeError(f"未知 RERANKER_BACKEND: {settings.RERANKER_BACKEND}")
