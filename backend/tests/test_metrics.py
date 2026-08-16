"""Prometheus 指标测试：/metrics 端点 + 业务指标存在 + 问答后计数出现。"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department="hr",
            role=Role.manager,
        )
        db.add(user)
        await db.commit()
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
async def test_metrics_endpoint_exposes_rag_metrics(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "rag_questions_total" in resp.text
    assert "rag_latency_seconds" in resp.text


@pytest.mark.asyncio
async def test_chat_increments_rag_questions(client):
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    resp = await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    assert resp.status_code == 200, resp.text

    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert 'department="hr"' in resp.text
