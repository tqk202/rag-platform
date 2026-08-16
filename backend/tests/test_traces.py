"""调用追踪测试：问答落 trace / 缓存命中置位 / 流式落库 / admin 端点 RBAC。"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.query_trace import QueryTrace
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, role: Role = Role.manager) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department="hr",
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


async def _upload_doc(client, token: str) -> None:
    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    resp = await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_chat_writes_trace(client):
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    await _upload_doc(client, token)

    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})

    async with AsyncSessionLocal() as db:
        trace = await db.scalar(select(QueryTrace).order_by(QueryTrace.id.desc()))
    assert trace is not None
    assert trace.question == "年假有几天？"
    assert trace.cache_hit is False
    assert trace.retrieved_count >= 1
    assert trace.department == "hr"
    assert trace.latency_ms >= 0


@pytest.mark.asyncio
async def test_cache_hit_trace(client):
    """第一次 miss，第二次命中缓存 -> 两条 trace 的 cache_hit 分别置位。"""
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    await _upload_doc(client, token)

    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})
    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})

    async with AsyncSessionLocal() as db:
        traces = list((await db.scalars(select(QueryTrace).order_by(QueryTrace.id))).all())
    assert len(traces) == 2
    assert traces[0].cache_hit is False
    assert traces[1].cache_hit is True


@pytest.mark.asyncio
async def test_stream_writes_trace(client):
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    await _upload_doc(client, token)

    async with client.stream(
        "POST", "/api/v1/chat/stream", headers=_auth(token),
        json={"question": "年假有几天？"},
    ) as resp:
        text = "".join([chunk async for chunk in resp.aiter_text()])
    assert "event: done" in text

    async with AsyncSessionLocal() as db:
        trace = await db.scalar(select(QueryTrace).order_by(QueryTrace.id.desc()))
    assert trace is not None
    assert trace.question == "年假有几天？"


@pytest.mark.asyncio
async def test_admin_traces_endpoint_rbac(client):
    await _seed_user("mgr_hr", Role.manager)
    await _seed_user("admin", Role.admin)
    mgr_token = await _login(client, "mgr_hr")
    admin_token = await _login(client, "admin")

    r403 = await client.get("/api/v1/admin/traces", headers=_auth(mgr_token))
    assert r403.status_code == 403

    r = await client.get("/api/v1/admin/traces", headers=_auth(admin_token))
    assert r.status_code == 200
