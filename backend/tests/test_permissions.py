"""W3 越权测试：跨部门 / 跨角色访问控制的核心证明。

面试官会问"你怎么证明权限生效了"——答案就在这里：每个越权场景都有测试拦截。
"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.document import DocStatus, Document
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, department: str, role: Role) -> int:
    """直接在库里造用户（注册接口只能建 member，管理员/经理需直接造）。"""
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


async def _seed_doc(department: str, owner_id: int, title: str = "doc.txt") -> int:
    async with AsyncSessionLocal() as db:
        doc = Document(
            title=title,
            file_name=title,
            file_path="data/uploads/fake",
            content_hash="fake-hash",
            status=DocStatus.ready,
            department=department,
            owner_id=owner_id,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc.id


async def _login(client, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _upload(client, token: str, department: str | None = None):
    files = {"file": ("测试文档.txt", "这是用于权限测试的文档内容", "text/plain")}
    data = {"department": department} if department else None
    return await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files, data=data
    )


@pytest.mark.asyncio
async def test_member_cannot_upload(client):
    await _seed_user("member_hr", "hr", Role.member)
    token = await _login(client, "member_hr")
    resp = await _upload(client, token)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_delete(client):
    uid = await _seed_user("member_hr", "hr", Role.member)
    doc_id = await _seed_doc("hr", uid)
    token = await _login(client, "member_hr")
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_cannot_specify_other_department(client):
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    resp = await _upload(client, token, department="finance")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_cannot_delete_other_department_doc(client):
    uid = await _seed_user("mgr_hr", "hr", Role.manager)
    doc_id = await _seed_doc("finance", uid)
    token = await _login(client, "mgr_hr")
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_can_delete_own_department_doc(client):
    uid = await _seed_user("mgr_hr", "hr", Role.manager)
    doc_id = await _seed_doc("hr", uid)
    token = await _login(client, "mgr_hr")
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_member_sees_only_own_department_docs(client):
    uid = await _seed_user("member_hr", "hr", Role.member)
    await _seed_doc("hr", uid, "hr_doc.txt")
    await _seed_doc("finance", 999, "finance_doc.txt")
    token = await _login(client, "member_hr")
    resp = await client.get("/api/v1/documents", headers=_auth(token))
    assert resp.status_code == 200
    names = {d["file_name"] for d in resp.json()["items"]}
    assert names == {"hr_doc.txt"}


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(client):
    await _seed_user("member_hr", "hr", Role.member)
    token = await _login(client, "member_hr")
    resp = await client.get("/api/v1/users", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_user_with_role(client):
    await _seed_user("boss", "admin", Role.admin)
    token = await _login(client, "boss")
    resp = await client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={
            "username": "new_mgr",
            "password": PASSWORD,
            "department": "hr",
            "role": "manager",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"
    assert resp.json()["department"] == "hr"


@pytest.mark.asyncio
async def test_admin_can_upload_to_any_department(client):
    await _seed_user("boss", "admin", Role.admin)
    token = await _login(client, "boss")
    resp = await _upload(client, token, department="finance")
    assert resp.status_code == 200
    assert resp.json()["document_id"]
