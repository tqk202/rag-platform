"""W6.5 文档详情测试：切片全文 + 部门隔离（越权 403 / 不存在 404）。"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.document import DocStatus, Document
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, department: str, role: Role = Role.member) -> int:
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


async def _seed_doc(department: str, owner_id: int) -> int:
    async with AsyncSessionLocal() as db:
        doc = Document(
            title="制度文档.txt",
            file_name="制度文档.txt",
            file_path="data/uploads/fake",
            content_hash="fake-hash",
            status=DocStatus.ready,
            department=department,
            owner_id=owner_id,
            chunk_count=2,
        )
        db.add(doc)
        await db.flush()
        db.add_all(
            [
                Chunk(document_id=doc.id, chunk_index=1, content="第一章 报销规定", page_no=1),
                Chunk(document_id=doc.id, chunk_index=2, content="第二章 请假流程", page_no=None),
            ]
        )
        await db.commit()
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


@pytest.mark.asyncio
async def test_document_detail_returns_ordered_chunks(client):
    uid = await _seed_user("hr_member", "hr")
    doc_id = await _seed_doc("hr", uid)
    token = await _login(client, "hr_member")

    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["file_name"] == "制度文档.txt"
    assert [c["chunk_index"] for c in body["chunks"]] == [1, 2]
    assert body["chunks"][0]["content"] == "第一章 报销规定"
    assert body["chunks"][0]["page_no"] == 1
    assert body["chunks"][1]["page_no"] is None


@pytest.mark.asyncio
async def test_cross_department_detail_forbidden(client):
    uid = await _seed_user("hr_member", "hr")
    doc_id = await _seed_doc("finance", uid)  # 文档在 finance 部门
    token = await _login(client, "hr_member")

    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_view_any_department(client):
    uid = await _seed_user("finance_member", "finance")
    doc_id = await _seed_doc("finance", uid)
    await _seed_user("boss", "admin", Role.admin)
    token = await _login(client, "boss")

    resp = await client.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_document_detail_not_found(client):
    await _seed_user("hr_member", "hr")
    token = await _login(client, "hr_member")

    resp = await client.get("/api/v1/documents/9999", headers=_auth(token))
    assert resp.status_code == 404
