"""存储对账：DB（事实来源）与 Milvus 的收敛检查（P1-1）。

Milvus 不参与 DB 事务，崩溃/重试/删除中断都可能留下偏差：
- 孤儿向量：Milvus 有行、DB 无对应切片（重灌中断、DB 回滚后）
- 缺向量：DB 有切片、Milvus 缺失（Milvus 写入失败）

对账以 DB 为准：孤儿向量直接清，缺向量的切片报告出来（交给重灌）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.chunk import Chunk
from app.models.document import Document
from app.services.vector_service import vector_store

logger = logging.getLogger(__name__)


async def reconcile_document(db: AsyncSession, doc_id: int) -> dict:
    """对账单个文档：清孤儿向量 + 报告缺向量，返回清理统计。"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")

    db_ids = list(
        (await db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id))).all()
    )
    milvus_ids = vector_store.list_chunk_ids_by_document(doc_id)
    db_set, mv_set = set(db_ids), set(milvus_ids)

    orphans = sorted(mv_set - db_set)  # Milvus 有、DB 无 -> 清
    missing = sorted(db_set - mv_set)  # DB 有、Milvus 无 -> 报告

    if orphans:
        vector_store.delete_by_chunk_ids(orphans)
    if orphans or missing:
        logger.warning(
            "文档 %s 对账：清孤儿向量 %s 个，缺向量切片 %s 个",
            doc_id, len(orphans), len(missing),
        )

    return {
        "document_id": doc_id,
        "orphans_cleaned": len(orphans),
        "missing_in_milvus": missing,
    }
