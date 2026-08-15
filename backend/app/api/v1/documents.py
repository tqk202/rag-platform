"""文档接口：上传 / 列表 / 删除。

W3 权限规则：上传/删除仅限 经理(manager) 和 管理员(admin)；普通成员(member)只读。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.user import Role, User
from app.schemas.common import Page
from app.schemas.document import DocumentDetail, DocumentOut, UploadResponse
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse, summary="上传文档")
async def upload(
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require_role(Role.manager, Role.admin))],
    file: UploadFile = File(...),
    department: str | None = Form(None, description="目标部门，仅管理员可指定"),
) -> UploadResponse:
    return await document_service.upload_document(db, user, file, department)


@router.get("", response_model=Page[DocumentOut], summary="文档列表")
async def list_documents(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[DocumentOut]:
    return await document_service.list_documents(db, user, page, page_size)


@router.get("/{doc_id}", response_model=DocumentDetail, summary="文档详情（含切片全文）")
async def get_document(
    doc_id: int, db: DbSession, user: CurrentUser
) -> DocumentDetail:
    return await document_service.get_document_detail(db, user, doc_id)


@router.post("/{doc_id}/retry", response_model=UploadResponse, summary="重试处理失败的文档")
async def retry_document(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require_role(Role.manager, Role.admin))],
) -> UploadResponse:
    return await document_service.retry_document(db, user, doc_id)


@router.delete("/{doc_id}", summary="删除文档")
async def delete_document(
    doc_id: int,
    db: DbSession,
    user: CurrentUser,
    _guard: Annotated[User, Depends(require_role(Role.manager, Role.admin))],
) -> dict:
    await document_service.delete_document(db, user, doc_id)
    return {"ok": True}
