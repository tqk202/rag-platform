"""P2-1 多轮对话测试：历史进生成、追问有上下文、多轮不进缓存。"""
import json

import httpx
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User
from app.services import rag_service
from app.services.llm_service import MockLLMProvider, OpenAICompatibleLLM

PASSWORD = "password123"
BASE = "https://x.example/v1"


def _llm(handler):
    return OpenAICompatibleLLM(BASE, "key", "deepseek-chat", transport=httpx.MockTransport(handler))


async def _seed_user(username: str, department: str = "hr") -> None:
    async with AsyncSessionLocal() as db:
        db.add(User(username=username, hashed_password=hash_password(PASSWORD), department=department, role=Role.manager))
        await db.commit()


async def _login(client, username: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _upload(client, token: str, content: str, name: str = "制度.txt"):
    files = {"file": (name, content, "text/plain")}
    resp = await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_generate_includes_history():
    """LLM 请求包含多轮历史，且当前问题放在最后。"""
    seen = {}

    def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "答"}}]})

    await _llm(handler).generate(
        "那上限呢？",
        [{"no": 1, "content": "报销制度"}],
        history=[
            {"role": "user", "content": "报销怎么走？"},
            {"role": "assistant", "content": "需提交申请。"},
        ],
    )

    roles = [m["role"] for m in seen["payload"]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen["payload"]["messages"][1]["content"] == "报销怎么走？"
    assert seen["payload"]["messages"][-1]["content"].startswith("请阅读以下资料")


@pytest.mark.asyncio
async def test_multi_turn_bypasses_cache(client, monkeypatch):
    """多轮请求不进缓存（含会话上下文，缓存会答非所问）——每次都真调 LLM。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "费用报销必须附发票。", "报销制度.txt")

    calls = {"n": 0}

    class _CountingLLM(MockLLMProvider):
        async def generate(self, question, chunks, history=None):
            calls["n"] += 1
            return await super().generate(question, chunks, history)

    monkeypatch.setattr(rag_service, "get_llm_provider", _CountingLLM)

    history = [
        {"role": "user", "content": "报销怎么走？"},
        {"role": "assistant", "content": "需提交申请。"},
    ]
    for _ in range(2):
        resp = await client.post(
            "/api/v1/chat",
            headers=_auth(token),
            json={"question": "那上限呢？", "history": history},
        )
        assert resp.status_code == 200, resp.text
    assert calls["n"] == 2  # 多轮不走缓存


@pytest.mark.asyncio
async def test_single_turn_still_caches(client, monkeypatch):
    """单轮仍走缓存：同一问题第二次不调 LLM（防 P2-1 误伤 W11）。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "费用报销必须附发票。", "报销制度.txt")

    calls = {"n": 0}

    class _CountingLLM(MockLLMProvider):
        async def generate(self, question, chunks, history=None):
            calls["n"] += 1
            return await super().generate(question, chunks, history)

    monkeypatch.setattr(rag_service, "get_llm_provider", _CountingLLM)

    for _ in range(2):
        resp = await client.post(
            "/api/v1/chat", headers=_auth(token), json={"question": "报销要发票吗？"}
        )
        assert resp.status_code == 200, resp.text
    assert calls["n"] == 1  # 单轮第二次命中缓存
