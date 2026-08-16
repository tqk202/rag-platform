"""文档处理管线：解析 -> 切片 -> 向量化 -> 入库。

W1 核心实现。由 Celery worker（生产）或上传接口 inline（开发）调用。

一致性设计（P1-1）：DB 是事实来源，外部存储（Milvus）不参与事务，
所以写入顺序固定为「DB 先提交 -> Milvus 后写 -> 置 ready」：
- 崩溃在 DB 提交前：回滚干净，无残留；
- 崩溃在 Milvus 写入后：DB 有切片但状态仍是 processing/failed，
  重试会先清旧切片（幂等重入），Milvus 在插入前也按文档清旧行；
- Milvus 写入失败：DB 保持事实，残余交给对账任务收敛。
"""
import hashlib
import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import DocStatus, Document
from app.services import embedding_service, vector_service
from app.services.chunker import chunk_document
from app.services.cleaner import clean_text, should_clean
from app.services.knowledge_base_service import doc_kb_name
from app.services.parsers import ParsedPage, parse_document
from app.services.sparse_service import get_sparse_index

logger = logging.getLogger(__name__)
settings = get_settings()


def compute_content_hash(content: bytes) -> str:
    """文件内容 SHA-256，用于去重与版本判断。"""
    return hashlib.sha256(content).hexdigest()


async def _clear_doc_chunks(db: AsyncSession, doc_id: int) -> None:
    """清掉该文档在 DB 里的切片 + 稀疏索引（幂等重入用，不动 Milvus）。"""
    chunk_ids = list(
        (await db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id))).all()
    )
    if chunk_ids:
        await get_sparse_index().remove(db, chunk_ids)
        await db.execute(delete(Chunk).where(Chunk.document_id == doc_id))


async def process_document(db: AsyncSession, document_id: int) -> None:
    """处理单个文档，完整走一遍四步管线并更新状态。

    noqa: 入库四步管线阶段线性、共享 doc 状态，拆散反而难读。
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        return
    # 多知识库：文档归属库名下沉到稀疏索引与向量元数据，检索层按它过滤
    kb_name = await doc_kb_name(db, doc)

    doc.status = DocStatus.processing
    doc.failure_reason = None  # 重试时清掉上次的失败原因
    await db.commit()

    try:
        # 1. 解析：文件 -> 分页文本（PDF 每页带真实页码，扫描件走 OCR）
        pages = parse_document(doc.file_path)

        # 1.5 可选清洗（TEXT_CLEANING=basic）：逐页去页眉页脚残留/全角空格/行尾空白。
        # 默认 none 原样入库——W4 评测的脏文档故意不清洗，验证检索抗噪能力
        if should_clean():
            pages = [ParsedPage(p.page_no, clean_text(p.text)) for p in pages]

        # 2. 切片：按文档类型分发（标题感知/页边界/句子对齐），切片携带页码
        pieces = chunk_document(pages, Path(doc.file_path).suffix.lower())
        if not pieces:
            raise ValueError("解析后没有提取到任何文本")

        # 3. 向量化：每个切片 -> 向量
        provider = embedding_service.get_embedding_provider()
        vectors = provider.embed_texts([p.content for p in pieces])

        # 4. 幂等重入：清掉上次残留的 DB 切片（重试/升版不会留下旧数据）
        await _clear_doc_chunks(db, doc.id)
        await db.commit()

        # 5. 切片 + 稀疏索引同事务先提交（DB 是事实来源，状态仍 processing）
        rows: list[dict] = []
        sparse = get_sparse_index()
        for i, piece in enumerate(pieces):
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=i,
                content=piece.content,
                page_no=piece.page_no,  # PDF 切片带真实页码
                token_count=len(piece.content),
            )
            db.add(chunk)
            await db.flush()  # 拿到 chunk.id，作为 Milvus 主键
            # 同步写稀疏索引（同一事务）：正文切片与关键词索引一起提交，失败一起回滚
            await sparse.add(db, chunk.id, doc.department, kb_name, piece.content)
            rows.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "department": doc.department,  # 权限过滤键（W3）
                    "knowledge_base": kb_name or "",  # 知识库过滤键（多知识库）
                    "page_no": piece.page_no or 0,  # Milvus INT32 不接受 None
                    "content": piece.content,
                    "vector": vectors[i],
                }
            )
        await db.commit()

        # 6. 外部存储后写：先清本档旧行再插入（幂等），失败不影响 DB 事实
        vector_service.vector_store.delete_by_document(doc.id)
        vector_service.vector_store.insert_chunks(rows)

        # 7. 全部落位后置 ready
        doc.status = DocStatus.ready
        doc.chunk_count = len(pieces)
        await db.commit()
        logger.info("文档 %s 处理完成，切片数 %s", doc.id, len(pieces))
    except Exception as exc:
        await db.rollback()
        # 失败不留下可检索切片：清掉本次已提交的 DB 切片 + 稀疏索引
        # （否则失败文档的内容仍能被检索到——P1-1 事实来源不能被污染）
        try:
            await _clear_doc_chunks(db, doc.id)
            await db.commit()
        except Exception:
            await db.rollback()
        doc.status = DocStatus.failed
        doc.failure_reason = str(exc)[:500]  # W10 失败原因落库，前端可见
        await db.commit()
        # 尽力清 Milvus 本档行：DB 已回滚时 Milvus 可能残留孤儿，交给对账任务兜底
        try:
            vector_service.vector_store.delete_by_document(doc.id)
        except Exception:
            logger.warning("文档 %s 失败后清理 Milvus 残留失败，由对账任务收敛", doc.id)
        logger.exception("文档 %s 处理失败", doc.id)
        raise
