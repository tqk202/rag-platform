"""重排服务：召回 -> 重排精排 -> 取前 N 给 LLM 的三层管线中间层。

为什么重排（面试点）：
- 召回用 bi-encoder（问题和文档各自编码算相似度），快但粗
- 重排用 cross-encoder（问题和文档拼接过模型打分），精但慢
- 所以只对 top-k 重排——成本 O(n)，全文重排不现实

当前实现是"轻量词法重排"（RERANKER_BACKEND=lexical）：
用查询词覆盖率 + 命中位置靠前加分，对召回结果二次打分。
诚实说明：词法信号和 BM25 有重叠，提升有限；真正的 cross-encoder
（如 bge-reranker）接入时实现 RerankerProvider 同接口，只改 factory 一处。
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

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


def get_reranker_provider() -> RerankerProvider | None:
    """工厂：按配置返回重排器。RERANKER_BACKEND=none 返回 None（关闭重排，W4 消融对比用）。"""
    if settings.RERANKER_BACKEND == "none":
        return None
    if settings.RERANKER_BACKEND == "lexical":
        return LexicalReranker()
    raise RuntimeError(f"未知 RERANKER_BACKEND: {settings.RERANKER_BACKEND}")
