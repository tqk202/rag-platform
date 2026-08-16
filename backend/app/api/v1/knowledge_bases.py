"""知识库接口：列表（按角色隔离，供聊天/上传下拉）。"""
from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models.document import Document
from app.schemas.knowledge_base import KnowledgeBaseOut
from app.services import knowledge_base_service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseOut], summary="知识库列表")
async def list_kbs(db: DbSession, user: CurrentUser) -> list[KnowledgeBaseOut]:
    """非 admin 只见本部门启用中的库；admin 见全部（带文档数）。"""
    kbs = await knowledge_base_service.list_kbs(db, user)
    counts = dict(
        (
            await db.execute(
                select(Document.knowledge_base_id, func.count())
                .where(Document.knowledge_base_id.is_not(None))
                .group_by(Document.knowledge_base_id)
            )
        ).all()
    )
    out = [KnowledgeBaseOut.model_validate(k) for k in kbs]
    for o in out:
        o.document_count = counts.get(o.id, 0)
    return out
