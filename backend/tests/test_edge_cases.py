"""W6 边界打磨测试：输入校验 + 上传安全边界 + 外部依赖兜底。

这层证明的不是"正常流程能跑"，而是"异常/恶意输入也不会把系统打穿"——
面试官问"线上会出什么问题你怎么防"，答案都在这里。
"""
import httpx
import pytest

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User
from app.services import rag_service

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


@pytest.mark.asyncio
async def test_chat_rejects_blank_question(client):
    """空问题/纯空格问题必须被 API 层拦截（不能白烧一次 LLM 调用）。"""
    await _seed_user("member_hr", "hr", Role.member)
    token = await _login(client, "member_hr")
    resp = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "   \n  "}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(client):
    """非文档类型（exe/压缩包等）直接拒绝，不允许入库。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("evil.exe", b"MZ fake exe", "application/octet-stream")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(client):
    """空文件拒绝，避免建一堆没有内容的僵尸文档。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("empty.txt", b"", "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 400
    assert "文件内容为空" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client, monkeypatch):
    """超过大小上限的文件拒绝（测试里把上限临时压到 1MB 避免造大文件）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("big.txt", b"x" * (1024 * 1024 + 1), "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 400
    assert "超过" in resp.json()["detail"]


class _FailProvider:
    """模拟上游 LLM 挂了：抛 httpx 连接错误。"""

    async def generate(self, question, chunks, history=None):
        raise httpx.ConnectError("connection refused", request=None)

    async def generate_stream(self, question, chunks, history=None):
        # 与真实实现一致：是异步生成器，首次迭代才抛错（yield 不可达，仅标记生成器）
        raise httpx.ConnectError("connection refused", request=None)
        yield ""  # pragma: no cover


@pytest.mark.asyncio
async def test_llm_failure_returns_friendly_502(client, monkeypatch):
    """DeepSeek 挂了时返回友好的 502 + 统一错误码，而不是裸 500。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")

    # 先上传一份文档让检索能命中（inline 模式处理成切片）
    files = {"file": ("报销制度.txt", "费用报销必须附发票，餐费每人每天上限50元。", "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 200

    # 让 LLM 调用抛 httpx 连接错误，模拟 DeepSeek 不可用（类即工厂，调用即实例化）
    monkeypatch.setattr(rag_service, "get_llm_provider", _FailProvider)

    resp = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "报销需要发票吗？"}
    )
    assert resp.status_code == 502
    assert resp.json()["code"] == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_stream_llm_failure_yields_error_event(client, monkeypatch):
    """SSE 流式路径：上游挂了时发出 error 事件（SSE 协议不中断），而非裸断流。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("报销制度.txt", "费用报销必须附发票，餐费每人每天上限50元。", "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 200

    monkeypatch.setattr(rag_service, "get_llm_provider", _FailProvider)

    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=_auth(token),
        json={"question": "报销需要发票吗？"},
    ) as resp:
        assert resp.status_code == 200
        text = "".join([chunk async for chunk in resp.aiter_text()])
    assert "event: error" in text
    assert "回答生成失败" in text


@pytest.mark.asyncio
async def test_chat_happy_path_still_works(client):
    """回归：加了一堆兜底后，正常问答路径不能被误伤。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("报销制度.txt", "费用报销必须附发票，餐费每人每天上限50元。", "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "报销需要发票吗？"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "发票" in body["answer"] or body["no_answer"] is False
