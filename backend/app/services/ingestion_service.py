"""文档处理管线：解析 -> 切片 -> 向量化 -> 入库。

W1 核心实现。由 Celery worker（生产）或上传接口 inline（开发）调用。
"""
import hashlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.chunk import Chunk
from app.models.document import DocStatus, Document
from app.services import embedding_service, vector_service
from app.services.chunker import chunk_text
from app.services.parsers import parse_document
from app.services.sparse_service import get_sparse_index

logger = logging.getLogger(__name__)
settings = get_settings()


def compute_content_hash(content: bytes) -> str:
    """文件内容 SHA-256，用于去重与版本判断。"""
    return hashlib.sha256(content).hexdigest()


async def process_document(db: AsyncSession, document_id: int) -> None:
    """处理单个文档，完整走一遍四步管线并更新状态。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return

    doc.status = DocStatus.processing
    doc.failure_reason = None  # 重试时清掉上次的失败原因
    await db.commit()

    try:
        # 1. 解析：文件 -> 纯文本
        text = parse_document(doc.file_path)

        # 2. 切片：长文本 -> 小块
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("解析后没有提取到任何文本")

        # 3. 向量化：每个切片 -> 向量
        provider = embedding_service.get_embedding_provider()
        vectors = provider.embed_texts(chunks)

        # 4. 入库：切片写入 PostgreSQL + 稀疏索引，向量 + 元数据写入 Milvus
        rows: list[dict] = []
        sparse = get_sparse_index()
        for i, content in enumerate(chunks):
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=i,
                content=content,
                token_count=len(content),
            )
            db.add(chunk)
            await db.flush()  # 拿到 chunk.id，作为 Milvus 主键
            # 同步写稀疏索引（同一事务）：正文切片与关键词索引一起提交，失败一起回滚
            await sparse.add(db, chunk.id, doc.department, content)
            rows.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "department": doc.department,  # 权限过滤键（W3）
                    "page_no": chunk.page_no or 0,  # Milvus INT32 不接受 None
                    "content": content,
                    "vector": vectors[i],
                }
            )

        vector_service.vector_store.insert_chunks(rows)

        doc.status = DocStatus.ready
        doc.chunk_count = len(chunks)
        await db.commit()
        logger.info("文档 %s 处理完成，切片数 %s", doc.id, len(chunks))
    except Exception as exc:
        await db.rollback()
        doc.status = DocStatus.failed
        doc.failure_reason = str(exc)[:500]  # W10 失败原因落库，前端可见
        await db.commit()
        logger.exception("文档 %s 处理失败", doc.id)
        raise
