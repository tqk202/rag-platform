"""管理端点（仅 admin）：存储对账、审计日志、知识库、反馈、调用追踪。"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.api.deps import DbSession, require_role
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.feedback import AnswerFeedback
from app.models.query_trace import QueryTrace
from app.models.user import Role, User
from app.schemas.audit import AuditLogOut
from app.schemas.common import AuditCleanupRequest, BatchDeleteRequest, Page
from app.schemas.feedback import FeedbackOut
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseOut, KnowledgeBaseUpdate
from app.schemas.trace import QueryTraceOut
from app.services import audit_service, feedback_service, knowledge_base_service, reconcile_service

router = APIRouter(prefix="/admin", tags=["admin"])

AdminGuard = Annotated[User, Depends(require_role(Role.admin))]


@router.post("/documents/{doc_id}/reconcile", summary="对账单个文档（仅管理员）")
async def reconcile_doc(doc_id: int, db: DbSession, _guard: AdminGuard) -> dict:
    return await reconcile_service.reconcile_document(db, doc_id)


@router.post("/documents/reconcile", summary="对账全部文档（仅管理员）")
async def reconcile_all(db: DbSession, _guard: AdminGuard) -> dict:
    doc_ids = list((await db.scalars(select(Document.id))).all())
    results = [
        await reconcile_service.reconcile_document(db, doc_id) for doc_id in doc_ids
    ]
    return {
        "documents": len(doc_ids),
        "total_orphans_cleaned": sum(r["orphans_cleaned"] for r in results),
        "results": results,
    }


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="审计日志（仅管理员）")
async def list_audit_logs(
    db: DbSession,
    _guard: AdminGuard,
    action: str | None = None,
    actor_username: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[AuditLogOut]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_username:
        stmt = stmt.where(AuditLog.actor_username == actor_username)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.execute(
        stmt.order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return Page(
        items=[AuditLogOut.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/knowledge-bases", response_model=KnowledgeBaseOut, summary="创建知识库（仅管理员）")
async def create_kb(
    db: DbSession, _guard: AdminGuard, data: KnowledgeBaseCreate
) -> KnowledgeBaseOut:
    return KnowledgeBaseOut.model_validate(
        await knowledge_base_service.create_kb(db, data.name, data.department, data.description)
    )


@router.patch("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut, summary="更新知识库（仅管理员）")
async def update_kb(
    kb_id: int, db: DbSession, _guard: AdminGuard, data: KnowledgeBaseUpdate
) -> KnowledgeBaseOut:
    return KnowledgeBaseOut.model_validate(
        await knowledge_base_service.update_kb(db, kb_id, data.name, data.description, data.is_active)
    )


@router.get("/feedback", response_model=Page[FeedbackOut], summary="回答反馈列表（仅管理员）")
async def list_feedback(
    db: DbSession,
    _guard: AdminGuard,
    sentiment: str | None = None,
    username: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[FeedbackOut]:
    items, total = await feedback_service.list_feedback(db, sentiment, username, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.delete("/feedback/{feedback_id}", summary="删除一条反馈（仅管理员，留痕）")
async def delete_feedback(
    feedback_id: int, db: DbSession, user: AdminGuard
) -> dict:
    fb = await db.get(AnswerFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    await db.delete(fb)
    await audit_service.record(
        db, user, "feedback.delete",
        object_type="feedback", object_id=feedback_id,
        detail=f"删除反馈记录 {feedback_id}",
    )
    await db.commit()
    return {"deleted": 1}


@router.post("/feedback/batch-delete", summary="批量删除反馈（仅管理员，留痕）")
async def batch_delete_feedback(
    db: DbSession, user: AdminGuard, data: BatchDeleteRequest
) -> dict:
    result = await db.execute(delete(AnswerFeedback).where(AnswerFeedback.id.in_(data.ids)))
    deleted = result.rowcount or 0
    await audit_service.record(
        db, user, "feedback.batch_delete",
        object_type="feedback",
        detail=f"批量删除反馈 {deleted} 条",
    )
    await db.commit()
    return {"deleted": deleted}


@router.post("/feedback/clear-all", summary="清空全部反馈（仅管理员，留痕）")
async def clear_all_feedback(db: DbSession, user: AdminGuard) -> dict:
    result = await db.execute(delete(AnswerFeedback))
    deleted = result.rowcount or 0
    await audit_service.record(
        db, user, "feedback.clear",
        object_type="feedback",
        detail=f"清空全部反馈（{deleted} 条）",
    )
    await db.commit()
    return {"deleted": deleted}


@router.get("/traces", response_model=Page[QueryTraceOut], summary="调用追踪列表（仅管理员）")
async def list_traces(
    db: DbSession,
    _guard: AdminGuard,
    department: str | None = None,
    username: str | None = None,
    cache_hit: bool | None = None,
    no_answer: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[QueryTraceOut]:
    stmt = select(QueryTrace)
    if department:
        stmt = stmt.where(QueryTrace.department == department)
    if cache_hit is not None:
        stmt = stmt.where(QueryTrace.cache_hit.is_(cache_hit))
    if no_answer is not None:
        stmt = stmt.where(QueryTrace.no_answer.is_(no_answer))
    if username:
        stmt = stmt.join(User, User.id == QueryTrace.user_id).where(User.username == username)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.execute(
        stmt.order_by(QueryTrace.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return Page(
        items=[QueryTraceOut.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/traces/{trace_id}", summary="删除一条调用追踪（仅管理员，留痕）")
async def delete_trace(trace_id: int, db: DbSession, user: AdminGuard) -> dict:
    tr = await db.get(QueryTrace, trace_id)
    if tr is None:
        raise HTTPException(status_code=404, detail="调用追踪不存在")
    await db.delete(tr)
    await audit_service.record(
        db, user, "trace.delete",
        object_type="trace", object_id=trace_id,
        detail=f"删除调用追踪 {trace_id}",
    )
    await db.commit()
    return {"deleted": 1}


@router.post("/traces/batch-delete", summary="批量删除调用追踪（仅管理员，留痕）")
async def batch_delete_traces(
    db: DbSession, user: AdminGuard, data: BatchDeleteRequest
) -> dict:
    result = await db.execute(delete(QueryTrace).where(QueryTrace.id.in_(data.ids)))
    deleted = result.rowcount or 0
    await audit_service.record(
        db, user, "trace.batch_delete",
        object_type="trace",
        detail=f"批量删除调用追踪 {deleted} 条",
    )
    await db.commit()
    return {"deleted": deleted}


@router.post("/traces/clear-all", summary="清空全部调用追踪（仅管理员，留痕）")
async def clear_all_traces(db: DbSession, user: AdminGuard) -> dict:
    result = await db.execute(delete(QueryTrace))
    deleted = result.rowcount or 0
    await audit_service.record(
        db, user, "trace.clear",
        object_type="trace",
        detail=f"清空全部调用追踪（{deleted} 条）",
    )
    await db.commit()
    return {"deleted": deleted}


@router.post("/audit-logs/cleanup", summary="清理 N 天前的审计日志（仅管理员，留痕）")
async def cleanup_audit_logs(
    db: DbSession, user: AdminGuard, data: AuditCleanupRequest
) -> dict:
    """审计日志是留痕数据，只能按时间清理旧记录，不提供任意单删/批量删。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=data.before_days)
    result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    deleted = result.rowcount or 0
    # 本次清理本身也留痕（新记录不在删除范围内，安全）
    await audit_service.record(
        db, user, "audit.cleanup",
        object_type="audit_log",
        detail=f"清理 {data.before_days} 天前的审计日志（{deleted} 条）",
    )
    await db.commit()
    return {"deleted": deleted}
