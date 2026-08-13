"""文档生命周期服务：上传（去重）/ 列表（按部门隔离）/ 删除（连向量一起清）。"""
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.models.chunk import Chunk
from app.models.document import DocStatus, Document
from app.models.user import Role, User
from app.schemas.common import Page
from app.schemas.document import DocumentOut, UploadResponse
from app.services.ingestion_service import compute_content_hash
from app.services.vector_service import vector_store

logger = logging.getLogger(__name__)
settings = get_settings()

UPLOAD_DIR = Path("data/uploads")


def _resolve_upload_department(user: User, requested: str | None) -> str:
    """上传归属部门：管理员可指定任意部门，经理只能传本部门。"""
    if requested:
        if user.role == Role.admin:
            return requested
        raise PermissionDeniedError("只有管理员可以指定上传部门")
    return user.department


async def upload_document(
    db: AsyncSession, user: User, file, department: str | None = None
) -> UploadResponse:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    content_hash = compute_content_hash(content)

    target_dept = _resolve_upload_department(user, department)

    # 同部门内容去重：同一份文件不重复入库
    dup = await db.scalar(
        select(Document).where(
            Document.content_hash == content_hash,
            Document.department == target_dept,
        )
    )
    if dup is not None:
        raise AppError(f"该文档已存在：{dup.file_name}")

    filename = Path(file.filename or "untitled").name
    rel_path = UPLOAD_DIR / f"{content_hash[:16]}_{filename}"
    rel_path.write_bytes(content)

    doc = Document(
        title=filename,
        file_name=filename,
        file_path=str(rel_path),
        content_hash=content_hash,
        status=DocStatus.pending,
        department=target_dept,
        owner_id=user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 生产：投递 Celery 异步处理；开发：inline 直接处理（无需 Redis/Worker）
    if settings.INGESTION_MODE == "inline":
        from app.services.ingestion_service import process_document

        try:
            await process_document(db, doc.id)
            return UploadResponse(document_id=doc.id, message="上传成功，处理完成")
        except Exception:
            logger.exception("文档 %s 处理失败", doc.id)
            return UploadResponse(document_id=doc.id, message="上传成功，但处理失败")

    from app.tasks.process_document import process_document_task

    try:
        process_document_task.delay(doc.id)
    except Exception:
        # broker 未就绪时保持 pending，不影响上传；但必须留痕，方便排查
        logger.warning("投递处理任务失败（broker 未就绪？）doc_id=%s", doc.id)

    return UploadResponse(document_id=doc.id, message="上传成功，正在处理")


async def list_documents(
    db: AsyncSession, user: User, page: int, page_size: int
) -> Page[DocumentOut]:
    stmt = select(Document)
    if user.role != Role.admin:
        stmt = stmt.where(Document.department == user.department)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.execute(
        stmt.order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return Page(
        items=[DocumentOut.model_validate(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


async def delete_document(db: AsyncSession, user: User, doc_id: int) -> None:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    if user.role != Role.admin and doc.department != user.department:
        raise PermissionDeniedError("无权删除该文档")

    # 先删向量库（Milvus），再删数据库，保证双存储一致，不留"幽灵"数据
    chunk_ids = list(
        (await db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id))).all()
    )
    if chunk_ids:
        vector_store.delete_by_chunk_ids(chunk_ids)

    await db.delete(doc)
    await db.commit()
