"""多知识库测试：建库 / 角色隔离 / 文档归属 / 检索隔离 / 缓存隔离 / 会话记录。"""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.chat import ChatSession
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, role: Role, department: str = "hr") -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department=department,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _login(client, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_kb(client, token: str, name: str, department: str):
    resp = await client.post(
        "/api/v1/admin/knowledge-bases",
        headers=_auth(token),
        json={"name": name, "department": department},
    )
    assert resp.status_code == 200, resp.text


async def _upload(client, token: str, content: str, name: str = "制度.txt", kb: str | None = None) -> int:
    files = {"file": (name, content, "text/plain")}
    data = {"knowledge_base": kb} if kb else {}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files, data=data
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


@pytest.mark.asyncio
async def test_member_sees_only_own_department_kbs(client):
    """角色隔离：成员只见本部门启用中的库；admin 见全部。"""
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    await _seed_user("member_hr", Role.member, "hr")

    await _create_kb(client, admin_token, "薪酬库", "hr")
    await _create_kb(client, admin_token, "财务库", "finance")

    member_token = await _login(client, "member_hr")
    resp = await client.get("/api/v1/knowledge-bases", headers=_auth(member_token))
    assert resp.status_code == 200
    names = [kb["name"] for kb in resp.json()]
    assert "薪酬库" in names
    assert "财务库" not in names  # 跨部门不可见

    admin_list = await client.get("/api/v1/knowledge-bases", headers=_auth(admin_token))
    assert "财务库" in [kb["name"] for kb in admin_list.json()]


@pytest.mark.asyncio
async def test_duplicate_kb_name_rejected(client):
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")
    await _create_kb(client, token, "薪酬库", "hr")
    resp = await client.post(
        "/api/v1/admin/knowledge-bases",
        headers=_auth(token),
        json={"name": "薪酬库", "department": "hr"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_first_upload_auto_creates_default_kb(client):
    """首次上传到无知识库的部门：自动建默认库并归属。"""
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。", "年假制度.txt")

    async with AsyncSessionLocal() as db:
        doc = await db.scalar(select(Document))
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        assert kb is not None
        assert kb.department == "hr"


@pytest.mark.asyncio
async def test_upload_to_explicit_kb(client):
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    await _create_kb(client, admin_token, "薪酬库", "hr")
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")

    await _upload(client, token, "薪酬绩效每年3月调整。", "薪酬制度.txt", kb="薪酬库")

    async with AsyncSessionLocal() as db:
        doc = await db.scalar(
            select(Document).options(selectinload(Document.knowledge_base))
        )
        assert doc.knowledge_base.name == "薪酬库"


@pytest.mark.asyncio
async def test_retrieval_isolated_by_knowledge_base(client):
    """检索隔离：同部门不同知识库互不可见。"""
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    for name in ("人事库", "食堂库"):
        await _create_kb(client, admin_token, name, "hr")
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")

    await _upload(client, token, "员工年假每年10天。", "年假制度.txt", kb="人事库")
    await _upload(client, token, "食堂卤肉饭定价12元。", "食堂菜谱.txt", kb="食堂库")

    r_a = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "人事库"},
    )
    assert r_a.status_code == 200
    assert r_a.json()["no_answer"] is False
    assert "10天" in r_a.json()["answer"]

    r_b = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "食堂库"},
    )
    assert r_b.json()["no_answer"] is True  # 食堂库没有年假内容 -> 拒答


@pytest.mark.asyncio
async def test_chat_session_records_knowledge_base(client):
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    await _create_kb(client, admin_token, "人事库", "hr")
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。", "年假制度.txt", kb="人事库")

    await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "人事库"},
    )
    async with AsyncSessionLocal() as db:
        session = await db.scalar(select(ChatSession))
        assert session.knowledge_base == "人事库"


@pytest.mark.asyncio
async def test_cache_isolated_across_knowledge_bases(client):
    """语义缓存带知识库维度：同问题在不同库各自命中，不串库。"""
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    for name in ("人事库", "食堂库"):
        await _create_kb(client, admin_token, name, "hr")
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。", "年假制度.txt", kb="人事库")

    a1 = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "人事库"},
    )
    b1 = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "食堂库"},
    )
    assert a1.json()["no_answer"] is False
    assert b1.json()["no_answer"] is True

    a2 = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "人事库"},
    )
    b2 = await client.post(
        "/api/v1/chat", headers=_auth(token),
        json={"question": "年假有几天？", "knowledge_base": "食堂库"},
    )
    assert a2.json()["answer"] == a1.json()["answer"]  # 各自命中各自缓存
    assert b2.json()["answer"] == b1.json()["answer"]
    assert a2.json()["no_answer"] is False
    assert b2.json()["no_answer"] is True
