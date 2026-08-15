"""W6 版本管理测试：同文件名重传 = 升版，旧切片双存储同步清理。

面试七问之一「文档更新了会不会过时」的代码证明：
重新上传 → 版本 +1 → 旧切片从向量库和 DB 一起清掉 → 只留新内容。
"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.user import Role, User
from app.services import embedding_service
from app.services.vector_service import vector_store

PASSWORD = "password123"


async def _seed_user(username: str, department: str, role: Role) -> int:
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


async def _upload(client, token: str, content: str, name: str = "制度.txt"):
    files = {"file": (name, content, "text/plain")}
    return await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)


async def _doc_chunks(doc_id: int) -> list[Chunk]:
    async with AsyncSessionLocal() as db:
        return list(
            (await db.scalars(select(Chunk).where(Chunk.document_id == doc_id))).all()
        )


async def _milvus_chunk_contents(department: str = "hr") -> set[str]:
    vec = embedding_service.get_embedding_provider().embed_texts(["查询"])[0]
    hits = vector_store.search(
        query_vector=vec,
        filter_expr=f'department == "{department}"',
        top_k=100,
        output_fields=["content"],
    )
    return {h["entity"]["content"] for h in hits}


@pytest.mark.asyncio
async def test_reupload_same_name_bumps_version(client):
    """同文件名不同内容重传 → 版本 +1，检索只剩新内容。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    r1 = await _upload(client, token, "员工年假每年10天，需提前申请。")
    assert r1.status_code == 200
    doc_id = r1.json()["document_id"]

    r2 = await _upload(client, token, "员工年假每年15天，需提前申请。")
    assert r2.status_code == 200
    assert r2.json()["document_id"] == doc_id
    assert "升级到第 2 版" in r2.json()["message"]

    # 版本 +1
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        version = doc.version
        chunk_count = doc.chunk_count
    assert version == 2

    # DB 里只剩新内容的切片，旧切片全部清掉
    chunks = await _doc_chunks(doc_id)
    assert len(chunks) == chunk_count > 0
    merged = "".join(c.content for c in chunks)
    assert "15天" in merged
    assert "10天" not in merged

    # Milvus 与 DB 内容一致（SQLite 会复用被删的 rowid，所以按内容而非 id 校验）
    milvus_contents = await _milvus_chunk_contents()
    assert milvus_contents == {c.content for c in chunks}


@pytest.mark.asyncio
async def test_reupload_same_content_rejected(client):
    """同文件名同内容重传 → 拒绝，版本不变，不白处理一遍。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    r1 = await _upload(client, token, "员工年假每年10天，需提前申请。")
    assert r1.status_code == 200
    doc_id = r1.json()["document_id"]

    r2 = await _upload(client, token, "员工年假每年10天，需提前申请。")
    assert r2.status_code == 400
    assert "已是最新版本" in r2.json()["detail"]

    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        version = doc.version
    assert version == 1


@pytest.mark.asyncio
async def test_version_update_visible_in_list(client):
    """列表接口能看到升版后的版本号（前端表格直接展示）。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    await _upload(client, token, "年假10天", "年假制度.txt")
    await _upload(client, token, "年假15天", "年假制度.txt")

    resp = await client.get("/api/v1/documents", headers=_auth(token))
    assert resp.status_code == 200
    doc = resp.json()["items"][0]
    assert doc["file_name"] == "年假制度.txt"
    assert doc["version"] == 2


@pytest.mark.asyncio
async def test_duplicate_filename_rejected_by_constraint(client):
    """P1-2 并发防线：同部门同文件名唯一约束，DB 层拦截重复建档。

    绕过接口直接插两条同 (department, file_name)，第二条必须被约束拒绝。
    """
    import pytest as _pytest
    from sqlalchemy.exc import IntegrityError

    uid = await _seed_user("mgr_hr", "hr", Role.manager)
    async with AsyncSessionLocal() as db:
        db.add(
            Document(
                title="制度.txt", file_name="制度.txt", file_path="data/uploads/x",
                content_hash="h1", department="hr", owner_id=uid,
            )
        )
        await db.commit()
        db.add(
            Document(
                title="制度.txt", file_name="制度.txt", file_path="data/uploads/y",
                content_hash="h2", department="hr", owner_id=uid,
            )
        )
        with _pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async with AsyncSessionLocal() as db:
        rows = list(
            (await db.scalars(select(Document).where(Document.file_name == "制度.txt"))).all()
        )
    assert len(rows) == 1  # 只有一条，约束生效
