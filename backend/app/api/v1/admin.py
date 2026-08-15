"""管理端点（仅 admin）：存储对账、审计日志等运维操作。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DbSession, require_role
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.user import Role, User
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page
from app.services import reconcile_service

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
