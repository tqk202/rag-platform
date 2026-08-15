"""管理端点（仅 admin）：存储对账等运维操作。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.models.document import Document
from app.models.user import Role, User
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
