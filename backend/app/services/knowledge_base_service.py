"""知识库服务：默认库解析、名称查库、文档 -> 知识库名。

多知识库把「部门单维度」升级为「部门 × 知识库」双维度。知识库按名称为业务键
（与 department 一样下沉到向量元数据与稀疏索引），这里统一负责「名称 <-> 实体」
解析，检索/入库/缓存各环节复用，避免各处重复查询。

聊天侧不同：ChatRequest.knowledge_base 为 None 表示「部门内全部知识库」，
直接透传给检索即可（不校验，库下拉来自知识库列表本身）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Role, User

DEFAULT_KB_NAME = "默认知识库"


async def get_kb_by_name(
    db: AsyncSession, department: str, name: str | None
) -> KnowledgeBase | None:
    if not name:
        return None
    return await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.department == department, KnowledgeBase.name == name
        )
    )


async def get_default_kb(db: AsyncSession, department: str) -> KnowledgeBase:
    """部门下第一个启用的知识库；没有则自动建默认库（首传兜底）。"""
    kb = await db.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.department == department, KnowledgeBase.is_active.is_(True)
        )
        .order_by(KnowledgeBase.id)
    )
    if kb is None:
        kb = KnowledgeBase(
            name=DEFAULT_KB_NAME, department=department, description="系统自动创建"
        )
        db.add(kb)
        await db.flush()
    return kb


async def resolve_kb_entity(
    db: AsyncSession, department: str, requested: str | None = None
) -> KnowledgeBase | None:
    """上传归属知识库：显式指定则校验存在且启用，否则落到部门默认库。"""
    if requested is not None:
        kb = await get_kb_by_name(db, department, requested)
        if kb is None or not kb.is_active:
            raise AppError(f"知识库「{requested}」不存在或已停用")
        return kb
    return await get_default_kb(db, department)


async def doc_kb_name(db: AsyncSession, doc: Document) -> str | None:
    """文档对应的知识库名（缓存失效用）。lazy relationship 需要显式取。"""
    if not doc.knowledge_base_id:
        return None
    kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
    return kb.name if kb else None


async def list_kbs(db: AsyncSession, user: User) -> list[KnowledgeBase]:
    """知识库列表：非 admin 只见本部门启用中的库（下拉 + 管理都用它）。"""
    stmt = select(KnowledgeBase)
    if user.role != Role.admin:
        stmt = stmt.where(
            KnowledgeBase.department == user.department,
            KnowledgeBase.is_active.is_(True),
        )
    stmt = stmt.order_by(KnowledgeBase.id)
    return list((await db.scalars(stmt)).all())


async def create_kb(
    db: AsyncSession, name: str, department: str, description: str | None = None
) -> KnowledgeBase:
    existing = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.department == department, KnowledgeBase.name == name
        )
    )
    if existing is not None:
        raise AppError(f"该部门已存在知识库「{name}」")
    kb = KnowledgeBase(name=name, department=department, description=description)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def update_kb(
    db: AsyncSession,
    kb_id: int,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    if name is not None and name.strip() and name != kb.name:
        dup = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.department == kb.department, KnowledgeBase.name == name
            )
        )
        if dup is not None:
            raise AppError(f"该部门已存在知识库「{name}」")
        kb.name = name.strip()
    if description is not None:
        kb.description = description
    if is_active is not None:
        kb.is_active = is_active
    await db.commit()
    await db.refresh(kb)
    return kb
