"""W10 文档入库重试测试：瞬时错误自动重试 / 永久错误不重试 / 失败原因落库 / 手动重试接口。

两条路径都覆盖：
- 任务层：瞬时（嵌入 API 网络故障）→ 自动重试；永久（解析失败）→ 直接失败
- 接口层：失败文档一键重试，非失败文档拒绝重试，普通成员无权重试
"""
import httpx
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.document import DocStatus, Document
from app.models.user import Role, User
from app.services.ingestion_service import process_document
from app.tasks import process_document as task_module
from app.tasks.process_document import MAX_ATTEMPTS, is_transient, process_document_task

PASSWORD = "password123"


def _req():
    return httpx.Request("POST", "http://mock")


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


# ---------- 任务层：瞬时/永久错误分类 ----------


def test_is_transient_classification():
    """与 W9 同一套判断：429/5xx/网络错误是瞬时；4xx/业务错误是永久。"""
    req = _req()
    assert is_transient(httpx.HTTPStatusError("x", request=req, response=httpx.Response(503, request=req)))
    assert is_transient(httpx.HTTPStatusError("x", request=req, response=httpx.Response(429, request=req)))
    assert not is_transient(httpx.HTTPStatusError("x", request=req, response=httpx.Response(400, request=req)))
    assert is_transient(httpx.ConnectError("refused", request=req))
    assert not is_transient(ValueError("解析后没有提取到任何文本"))


def test_task_retries_transient_error(monkeypatch):
    """嵌入 API 网络故障（瞬时）→ 任务按退避自动重试，不直接失败。"""
    retried: dict = {}

    def fake_retry(exc=None, countdown=None):
        retried["countdown"] = countdown
        raise RuntimeError("模拟 Celery 重新入队")  # Celery 的 retry() 不会返回

    monkeypatch.setattr(process_document_task, "retry", fake_retry)

    async def boom(document_id: int) -> None:
        raise httpx.ConnectError("connection refused", request=_req())

    monkeypatch.setattr(task_module, "_run", boom)
    with pytest.raises(RuntimeError):
        process_document_task(123)
    assert retried["countdown"] > 0  # 指数退避给了个正的等待秒数


def test_task_transient_exhausted_no_retry(monkeypatch):
    """瞬时错误但重试次数耗尽 → 不再重试，直接抛错（文档已标 failed+原因）。"""
    called: list[dict] = []

    def fake_retry(**kwargs):
        called.append(kwargs)
        raise AssertionError("重试耗尽后不应再重试")

    monkeypatch.setattr(process_document_task, "retry", fake_retry)

    async def boom(document_id: int) -> None:
        raise httpx.ConnectError("connection refused", request=_req())

    monkeypatch.setattr(task_module, "_run", boom)
    process_document_task.request.retries = MAX_ATTEMPTS - 1  # 已到最后一轮
    with pytest.raises(httpx.ConnectError):
        process_document_task(123)
    assert called == []


def test_task_permanent_error_no_retry(monkeypatch):
    """解析失败（永久）→ 不重试，直接抛错。"""
    called: list[dict] = []

    def fake_retry(**kwargs):
        called.append(kwargs)
        raise AssertionError("永久错误不应重试")

    monkeypatch.setattr(process_document_task, "retry", fake_retry)

    async def boom(document_id: int) -> None:
        raise ValueError("解析后没有提取到任何文本")

    monkeypatch.setattr(task_module, "_run", boom)
    with pytest.raises(ValueError):
        process_document_task(123)
    assert called == []


# ---------- 服务层：失败原因落库 ----------


@pytest.mark.asyncio
async def test_process_document_failure_records_reason():
    """处理失败 → 状态 failed + failure_reason 落库（前端可见）。"""
    async with AsyncSessionLocal() as db:
        user = User(
            username="mgr_hr",
            hashed_password=hash_password(PASSWORD),
            department="hr",
            role=Role.manager,
        )
        db.add(user)
        await db.flush()
        doc = Document(
            title="坏文件.txt",
            file_name="坏文件.txt",
            file_path="data/uploads/不存在.bad",  # parse 必然失败
            content_hash="hash",
            status=DocStatus.pending,
            department="hr",
            owner_id=user.id,
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id

    async with AsyncSessionLocal() as db:
        with pytest.raises(Exception):
            await process_document(db, doc_id)

    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        assert doc.status == DocStatus.failed
        assert doc.failure_reason  # 非空


# ---------- 接口层：手动重试 ----------


@pytest.mark.asyncio
async def test_retry_reenqueues_failed_doc(client):
    """失败文档手动重试 → 重新处理并恢复 ready。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    r = await _upload(client, token, "员工年假每年10天，需提前申请。")
    assert r.status_code == 200
    doc_id = r.json()["document_id"]

    # 模拟一次失败：直接把状态标 failed + 原因
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        doc.status = DocStatus.failed
        doc.failure_reason = "嵌入服务暂不可用"
        await db.commit()

    resp = await client.post(f"/api/v1/documents/{doc_id}/retry", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert "重新提交处理" in resp.json()["message"]

    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        assert doc.status == DocStatus.ready  # inline 模式重处理成功
        assert doc.failure_reason is None


@pytest.mark.asyncio
async def test_retry_rejects_non_failed_doc(client):
    """处理成功的文档不能重试（无意义）。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    r = await _upload(client, token, "员工年假每年10天，需提前申请。")
    doc_id = r.json()["document_id"]

    resp = await client.post(f"/api/v1/documents/{doc_id}/retry", headers=_auth(token))
    assert resp.status_code == 400
    assert "处理失败" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_retry_member_denied(client):
    """普通成员只读，无权重试。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    await _seed_user("member_hr", "hr", Role.member)
    token = await _login(client, "mgr_hr")
    member_token = await _login(client, "member_hr")

    r = await _upload(client, token, "员工年假每年10天，需提前申请。")
    doc_id = r.json()["document_id"]

    resp = await client.post(
        f"/api/v1/documents/{doc_id}/retry", headers=_auth(member_token)
    )
    assert resp.status_code == 403
