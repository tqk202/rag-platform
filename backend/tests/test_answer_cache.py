"""W11 回答语义缓存测试：命中/语义/版本失效/部门隔离/流式回放/TTL/开关。

测试库用内存 KV（conftest 强制 ANSWER_CACHE_BACKEND=memory，不依赖 Redis），
Milvus Lite 存问句向量。语义命中通过注入固定向量模拟真实嵌入把相近问法聚到一起。
"""
import math

import pytest

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User
from app.schemas.chat import Citation
from app.services import answer_cache, rag_service
from app.services.answer_cache import MemoryCacheKV, RedisCacheKV
from app.services.llm_service import MockLLMProvider

settings = get_settings()
PASSWORD = "password123"


async def _seed_user(username: str, department: str, role: Role = Role.manager) -> int:
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


def _citation(n: int) -> Citation:
    return Citation(
        chunk_id=n, document_id=1, document_title="报销制度", content="费用报销必须附发票。", page_no=1
    )


# ---------- 核心单元：lookup / store / bump ----------

@pytest.mark.asyncio
async def test_lookup_miss_when_cache_empty():
    assert await answer_cache.lookup("如何报销？", "hr") is None


@pytest.mark.asyncio
async def test_store_then_exact_hit():
    citations = [_citation(1)]
    await answer_cache.store("如何报销？", "hr", "回答内容", citations, False)
    hit = await answer_cache.lookup("如何报销？", "hr")
    assert hit is not None
    assert hit["answer"] == "回答内容"
    assert hit["no_answer"] is False
    assert hit["citations"][0]["chunk_id"] == 1


@pytest.mark.asyncio
async def test_different_question_misses():
    """mock 嵌入是哈希随机向量：不同问法余弦≈0，低于阈值自然 miss。"""
    await answer_cache.store("如何报销？", "hr", "回答", [], False)
    assert await answer_cache.lookup("如何请假？", "hr") is None


@pytest.mark.asyncio
async def test_semantic_hit_for_rephrased_question(monkeypatch):
    """注入固定向量模拟真实嵌入：相近问法聚到同一向量，换种问法也能命中。"""
    vec = [0.5, -0.5, 0.5, 0.5] + [0.0] * (settings.EMBEDDING_DIM - 4)
    norm = math.sqrt(sum(x * x for x in vec))
    monkeypatch.setattr(answer_cache, "_embed", lambda q: [x / norm for x in vec])

    await answer_cache.store("天气怎么样？", "hr", "回答A", [], False)
    hit = await answer_cache.lookup("今天天气如何？", "hr")
    assert hit is not None
    assert hit["answer"] == "回答A"


@pytest.mark.asyncio
async def test_version_bump_invalidates_old_answer():
    await answer_cache.store("如何报销？", "hr", "旧回答", [], False)
    assert await answer_cache.lookup("如何报销？", "hr") is not None
    await answer_cache.bump_version("hr")
    assert await answer_cache.lookup("如何报销？", "hr") is None


@pytest.mark.asyncio
async def test_department_isolation():
    await answer_cache.store("如何报销？", "hr", "hr的回答", [], False)
    assert await answer_cache.lookup("如何报销？", "finance") is None


@pytest.mark.asyncio
async def test_disabled_returns_miss_and_skips_store(monkeypatch):
    monkeypatch.setattr(settings, "ANSWER_CACHE_ENABLED", False)
    await answer_cache.store("问题", "hr", "回答", [], False)  # 应 no-op
    assert await answer_cache.lookup("问题", "hr") is None


# ---------- KV 存储实现 ----------

@pytest.mark.asyncio
async def test_memory_kv_ttl_expiry():
    kv = MemoryCacheKV()
    await kv.set("k", "v", ttl=0)  # 立即过期
    assert await kv.get("k") is None


@pytest.mark.asyncio
async def test_memory_kv_incr_and_clear():
    kv = MemoryCacheKV()
    assert await kv.incr("v") == 1
    assert await kv.incr("v") == 2
    await kv.clear()
    assert await kv.get("v") is None


@pytest.mark.asyncio
async def test_redis_kv_roundtrip_skips_if_unavailable():
    """真实 Redis 路径验证：连不上就跳过（本地无 Redis 时测试照常绿）。"""
    import os

    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    import redis.asyncio as aioredis

    probe = aioredis.from_url(url, decode_responses=True)
    try:
        await probe.ping()
    except Exception:
        pytest.skip("Redis 不可用，跳过真实 Redis 测试")
    await probe.flushdb()

    kv = RedisCacheKV(url)
    await kv.set("k", "v", ttl=60)
    assert await kv.get("k") == "v"
    assert await kv.incr("cnt") == 1
    await kv.clear()
    assert await kv.get("k") is None


# ---------- 端到端：挂勾 rag_service ----------

@pytest.mark.asyncio
async def test_chat_second_ask_hits_cache_skips_llm(client, monkeypatch):
    """同一问题问两次：第一次真调 LLM，第二次走缓存不再调。"""
    await _seed_user("mgr_hr", "hr")
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "费用报销必须附发票，餐费每人每天上限50元。", "报销制度.txt")

    calls = {"n": 0}

    class _CountingLLM(MockLLMProvider):
        async def generate(self, question, chunks):
            calls["n"] += 1
            return await super().generate(question, chunks)

    monkeypatch.setattr(rag_service, "get_llm_provider", _CountingLLM)

    r1 = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "报销要发票吗？"}
    )
    assert r1.status_code == 200, r1.text
    assert calls["n"] == 1

    r2 = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "报销要发票吗？"}
    )
    assert r2.status_code == 200, r2.text
    assert calls["n"] == 1  # 第二次未调 LLM
    assert r1.json()["answer"] == r2.json()["answer"]


@pytest.mark.asyncio
async def test_chat_doc_change_invalidates_cache(client, monkeypatch):
    """文档升版后同一问题重新走 LLM（版本号失效生效）。"""
    await _seed_user("mgr_hr", "hr")
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。", "年假制度.txt")

    calls = {"n": 0}

    class _CountingLLM(MockLLMProvider):
        async def generate(self, question, chunks):
            calls["n"] += 1
            return await super().generate(question, chunks)

    monkeypatch.setattr(rag_service, "get_llm_provider", _CountingLLM)

    q = "年假几天？"
    await client.post("/api/v1/chat", headers=_auth(token), json={"question": q})
    assert calls["n"] == 1

    # 重新上传同一文件名（内容不同）→ 升版 → 缓存作废
    await _upload(client, token, "员工年假每年15天。", "年假制度.txt")
    r2 = await client.post("/api/v1/chat", headers=_auth(token), json={"question": q})
    assert r2.status_code == 200
    assert calls["n"] == 2  # 文档变了，重新调了 LLM


@pytest.mark.asyncio
async def test_stream_second_ask_replays_single_delta(client, monkeypatch):
    """流式命中：整个回答一次推完（单 delta），且不再调 LLM。"""
    await _seed_user("mgr_hr", "hr")
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "费用报销必须附发票。", "报销制度.txt")

    calls = {"n": 0}

    class _CountingLLM(MockLLMProvider):
        async def generate_stream(self, question, chunks):
            calls["n"] += 1
            async for delta in super().generate_stream(question, chunks):
                yield delta

    monkeypatch.setattr(rag_service, "get_llm_provider", _CountingLLM)

    async def _ask_stream():
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            headers=_auth(token),
            json={"question": "报销要发票吗？"},
        ) as resp:
            return "".join([chunk async for chunk in resp.aiter_text()])

    first = await _ask_stream()
    assert calls["n"] == 1
    assert first.count("event: delta") >= 2  # 首次流式至少多段

    second = await _ask_stream()
    assert calls["n"] == 1  # 第二次未调 LLM
    assert second.count("event: delta") == 1  # 缓存命中：单段推完
    assert "event: done" in second
