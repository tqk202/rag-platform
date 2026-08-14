"""文档生命周期服务：上传（去重）/ 列表（按部门隔离）/ 删除（连向量一起清）。"""
import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.models.chunk import Chunk
from app.models.document import DocStatus, Document
from app.models.user import Role, User
from app.schemas.common import Page
from app.schemas.document import ChunkOut, DocumentDetail, DocumentOut, UploadResponse
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


def _check_extension(filename: str) -> None:
    """类型白名单：只收常见文档格式，exe/压缩包/图片等一律拒绝。"""
    allowed = {
        e.strip().lower()
        for e in settings.ALLOWED_UPLOAD_EXTENSIONS.split(",")
        if e.strip()
    }
    suffix = Path(filename).suffix.lower()
    if suffix not in allowed:
        raise AppError(f"不支持的文件类型 {suffix}，仅支持：{', '.join(sorted(allowed))}")


async def _read_capped(file) -> bytes:
    """分块读取并限制大小，避免超大文件一次性读进内存。"""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AppError(f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")
        parts.append(chunk)
    return b"".join(parts)


async def _delete_doc_chunks(db: AsyncSession, doc_id: int) -> None:
    """删除文档的所有切片：Milvus 向量 + DB 记录，保证双存储一致不留幽灵。"""
    chunk_ids = list(
        (await db.scalars(select(Chunk.id).where(Chunk.document_id == doc_id))).all()
    )
    if chunk_ids:
        vector_store.delete_by_chunk_ids(chunk_ids)
        await db.execute(delete(Chunk).where(Chunk.document_id == doc_id))


async def _finish_processing(db: AsyncSession, doc: Document) -> UploadResponse:
    """处理新内容：生产投递 Celery，开发 inline 直接处理。"""
    if settings.INGESTION_MODE == "inline":
        from app.services.ingestion_service import process_document

        try:
            await process_document(db, doc.id)
            return UploadResponse(document_id=doc.id, message="处理完成")
        except Exception:
            logger.exception("文档 %s 处理失败", doc.id)
            return UploadResponse(document_id=doc.id, message="处理失败")

    from app.tasks.process_document import process_document_task

    try:
        process_document_task.delay(doc.id)
    except Exception:
        # broker 未就绪时保持 pending，不影响上传；但必须留痕，方便排查
        logger.warning("投递处理任务失败（broker 未就绪？）doc_id=%s", doc.id)
    return UploadResponse(document_id=doc.id, message="正在处理")


async def _update_document_version(
    db: AsyncSession, doc: Document, content: bytes, content_hash: str, filename: str
) -> UploadResponse:
    """同文件名重传 = 版本更新：版本 +1，先清旧切片再灌新内容。"""
    if doc.content_hash == content_hash:
        raise AppError(f"「{doc.file_name}」已是最新版本，无需更新")

    if doc.status not in (DocStatus.ready, DocStatus.failed):
        # 处理中/待处理的文档不能更新：异步模式下会和新旧处理任务抢数据
        raise AppError(f"「{doc.file_name}」正在处理中，请稍后再更新")

    # 旧切片先清掉（向量 + DB），否则新旧数据混在库里
    await _delete_doc_chunks(db, doc.id)

    rel_path = UPLOAD_DIR / f"{content_hash[:16]}_{filename}"
    rel_path.write_bytes(content)

    doc.content_hash = content_hash
    doc.file_path = str(rel_path)
    doc.version += 1
    doc.chunk_count = 0
    doc.status = DocStatus.pending
    await db.commit()
    await db.refresh(doc)

    result = await _finish_processing(db, doc)
    result.message = f"更新成功，已升级到第 {doc.version} 版"
    return result


async def upload_document(
    db: AsyncSession, user: User, file, department: str | None = None
) -> UploadResponse:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    filename = Path(file.filename or "untitled").name
    _check_extension(filename)

    content = await _read_capped(file)
    if not content:
        raise AppError("文件内容为空")
    content_hash = compute_content_hash(content)

    target_dept = _resolve_upload_department(user, department)

    # 同部门同文件名 = 版本更新（重新上传新版本文档）
    existing = await db.scalar(
        select(Document).where(
            Document.file_name == filename,
            Document.department == target_dept,
        )
    )
    if existing is not None:
        return await _update_document_version(db, existing, content, content_hash, filename)

    # 新文档：同部门内容去重，同一份内容不重复入库（即使文件名不同）
    dup = await db.scalar(
        select(Document).where(
            Document.content_hash == content_hash,
            Document.department == target_dept,
        )
    )
    if dup is not None:
        raise AppError(f"该文档已存在：{dup.file_name}")

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

    result = await _finish_processing(db, doc)
    result.message = f"上传成功，{result.message}"
    return result


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


async def get_document_detail(
    db: AsyncSession, user: User, doc_id: int
) -> DocumentDetail:
    """文档详情：元信息 + 按序切片全文。部门隔离——非管理员只能看本部门。"""
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    if user.role != Role.admin and doc.department != user.department:
        raise PermissionDeniedError("无权查看该文档")

    stmt = (
        select(Chunk)
        .where(Chunk.document_id == doc.id)
        .order_by(Chunk.chunk_index)
    )
    chunks = list((await db.scalars(stmt)).all())
    return DocumentDetail(
        **DocumentOut.model_validate(doc).model_dump(),
        chunks=[ChunkOut.model_validate(c) for c in chunks],
    )


async def delete_document(db: AsyncSession, user: User, doc_id: int) -> None:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    if user.role != Role.admin and doc.department != user.department:
        raise PermissionDeniedError("无权删除该文档")

    # 先删向量库（Milvus），再删数据库，保证双存储一致，不留"幽灵"数据
    await _delete_doc_chunks(db, doc_id)

    await db.delete(doc)
    await db.commit()
