"""P1-1 跨存储一致性测试：入库幂等、失败不留孤儿、对账收敛。

核心保证：DB 是事实来源，Milvus 可被对账收敛——崩溃/重试不会无限堆积脏数据。
"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.document import DocStatus, Document
from app.models.user import Role, User
from app.services import reconcile_service
from app.services.ingestion_service import process_document
from app.services.vector_service import vector_store

PASSWORD = "password123"


async def _seed_user(username: str, department: str = "hr") -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department=department,
            role=Role.manager,
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


async def _upload(client, token: str, content: str, name: str = "制度.txt") -> int:
    files = {"file": (name, content, "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


@pytest.mark.asyncio
async def test_reprocess_is_idempotent(client):
    """同一文档重复处理：切片不翻倍、Milvus 不重复。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    doc_id = await _upload(client, token, "员工年假每年10天，需提前申请。报销上限500元。")

    async def _counts():
        async with AsyncSessionLocal() as db:
            doc = await db.get(Document, doc_id)
            db_count = doc.chunk_count
        mv_count = len(vector_store.list_chunk_ids_by_document(doc_id))
        return db_count, mv_count

    db1, mv1 = await _counts()
    assert db1 > 0 and db1 == mv1  # 初始 DB 与 Milvus 一致

    # 再处理一次（模拟重试/升版重灌）
    async with AsyncSessionLocal() as db:
        await process_document(db, doc_id)

    db2, mv2 = await _counts()
    assert db2 == db1 and mv2 == mv1  # 幂等：数量不变，无翻倍


@pytest.mark.asyncio
async def test_failed_ingest_leaves_no_orphan(client, monkeypatch):
    """Milvus 写入失败 -> 文档标 failed，且 Milvus 无残留孤儿。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")

    def _boom(rows):
        raise RuntimeError("milvus down")

    # 上传时走 inline 处理，先把 insert 弄挂
    monkeypatch.setattr(vector_store, "insert_chunks", _boom)
    doc_id = await _upload(client, token, "员工年假每年10天。")

    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        assert doc.status == DocStatus.failed
        assert "milvus down" in doc.failure_reason

    # Milvus 无残留（insert 抛错前 delete_by_document 已清）
    assert vector_store.list_chunk_ids_by_document(doc_id) == []


@pytest.mark.asyncio
async def test_reconcile_cleans_orphan_vectors(client):
    """对账：Milvus 里的孤儿向量被清掉，DB 切片不受影响。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    doc_id = await _upload(client, token, "员工年假每年10天。")

    # 手工造孤儿：插入一个 DB 里不存在的 chunk_id
    vector_store.insert_chunks(
        [
            {
                "chunk_id": 999999,
                "document_id": doc_id,
                "department": "hr",
                "page_no": 0,
                "content": "幽灵切片",
                "vector": [0.1] * 1024,
            }
        ]
    )
    assert 999999 in vector_store.list_chunk_ids_by_document(doc_id)

    async with AsyncSessionLocal() as db:
        result = await reconcile_service.reconcile_document(db, doc_id)

    assert result["orphans_cleaned"] == 1
    assert 999999 not in vector_store.list_chunk_ids_by_document(doc_id)


@pytest.mark.asyncio
async def test_reconcile_reports_missing_vectors(client, monkeypatch):
    """对账：DB 有切片但 Milvus 缺，报告为 missing。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    doc_id = await _upload(client, token, "员工年假每年10天。")

    # 手工删掉 Milvus 全部行，模拟 Milvus 写入丢失
    vector_store.delete_by_document(doc_id)

    async with AsyncSessionLocal() as db:
        result = await reconcile_service.reconcile_document(db, doc_id)

    assert result["orphans_cleaned"] == 0
    assert result["missing_in_milvus"], "应报告 DB 有而 Milvus 缺的切片"


@pytest.mark.asyncio
async def test_reconcile_endpoint_requires_admin(client):
    """对账端点仅 admin 可调：非管理员 403。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    resp = await client.post(
        "/api/v1/admin/documents/reconcile", headers=_auth(token)
    )
    assert resp.status_code == 403
