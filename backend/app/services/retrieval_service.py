"""检索服务：混合检索（BM25 + 向量）+ RRF 融合 + 权限过滤。

W2 核心。检索质量决定 RAG 上限，是本项目的技术主战场。

为什么混合检索比纯向量好？
- 向量（Dense）：擅长语义相似（"怎么休年假"能命中"带薪年假"），但精确词、专名、代码会漂移
- BM25（Sparse）：精确词命中（"报销上限"能精确到报销章），但无法理解同义词
- 生产里两者互补：召回率靠双路，排序靠 RRF 融合

权限过滤：只在目标 department 的切片上检索（Milvus 元数据过滤 / SQL 过滤），
不是检索完再过滤——先过滤省算力且更安全。
"""
import logging
from typing import Any

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.services import embedding_service, vector_service

logger = logging.getLogger(__name__)
settings = get_settings()

RRF_K = 60  # RRF 平滑常数（标准值），避免分母为 0 并削弱排名靠后结果的贡献


def _tokenize(text: str) -> list[str]:
    """中文分词。BM25 需要词级 token，jieba 对无空格中文做词切分。"""
    return [w.strip() for w in jieba.lcut(text) if w.strip()]


async def vector_search(
    db: AsyncSession, query: str, department: str, top_k: int
) -> list[dict[str, Any]]:
    """Dense 召回：向量相似度检索，Milvus 上做部门过滤。"""
    provider = embedding_service.get_embedding_provider()
    query_vec = provider.embed_texts([query])[0]

    hits = vector_service.vector_store.search(
        query_vector=query_vec,
        filter_expr=f'department == "{department}"',
        top_k=top_k,
        output_fields=["chunk_id", "document_id", "department", "page_no", "content"],
    )

    results: list[dict[str, Any]] = []
    for h in hits:
        entity = h["entity"]
        results.append(
            {
                "chunk_id": entity["chunk_id"],
                "document_id": entity["document_id"],
                "content": entity["content"],
                "page_no": entity["page_no"],
                "vector_score": float(h["distance"]),
            }
        )
    return results


async def keyword_search(
    db: AsyncSession, query: str, department: str, top_k: int
) -> list[dict[str, Any]]:
    """Sparse 召回：BM25 关键词检索，SQL 层按部门过滤。"""
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.department == department)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    corpus = [_tokenize(c.content) for c, _ in rows]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
    results: list[dict[str, Any]] = []
    for i in ranked:
        if scores[i] <= 0:
            continue  # 与查询零词命中，直接跳过（这是 no_answer 的检索侧依据）
        chunk, title = rows[i]
        results.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": title,
                "content": chunk.content,
                "page_no": chunk.page_no,
                "bm25_score": float(scores[i]),
            }
        )
        if len(results) >= top_k:
            break
    return results


async def hybrid_search(
    db: AsyncSession, query: str, department: str, top_k: int = 5
) -> list[dict[str, Any]]:
    """混合检索：双路召回 + RRF 融合 + 统一补全文档标题。

    RRF（Reciprocal Rank Fusion）：score(c) = Σ 1 / (k + rank_c)
    用"排名"而非"分数"融合，因为不同检索器的分数不可直接比较。
    """
    vector_hits = await vector_search(db, query, department, top_k)
    keyword_hits = await keyword_search(db, query, department, top_k)

    # 按 chunk_id 融合两路排名
    fused: dict[int, float] = {}
    for rank, h in enumerate(vector_hits, start=1):
        fused[h["chunk_id"]] = fused.get(h["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)
    for rank, h in enumerate(keyword_hits, start=1):
        fused[h["chunk_id"]] = fused.get(h["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)

    if not fused:
        return []

    ordered_ids = sorted(fused, key=fused.get, reverse=True)[:top_k]

    # 一次查询补齐标题，避免逐条查库（N+1）
    stmt = (
        select(Chunk, Document.title)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_(ordered_ids))
    )
    by_id = {c.id: (c, t) for c, t in (await db.execute(stmt)).all()}

    results: list[dict[str, Any]] = []
    for cid in ordered_ids:
        chunk, title = by_id[cid]
        results.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": title,
                "content": chunk.content,
                "page_no": chunk.page_no,
                "score": fused[cid],
            }
        )
    return results
