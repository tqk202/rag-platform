"""W6.5 会话历史测试：问答落库 + 会话 CRUD + 归属隔离。

测试库无文档，/chat 走 NO_DOC_ANSWER 分支（离线、不烧 LLM），
正好验证「问题+回答落库」这条核心链路。
"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
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


async def _login(client, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _ask(client, token: str, question: str, session_id: int | None = None):
    body = {"question": question}
    if session_id is not None:
        body["session_id"] = session_id
    return await client.post("/api/v1/chat", headers=_auth(token), json=body)


@pytest.mark.asyncio
async def test_chat_creates_session_and_persists_exchange(client):
    await _seed_user("alice", "hr")
    token = await _login(client, "alice")

    resp = await _ask(client, token, "如何申请报销？")
    assert resp.status_code == 200, resp.text
    sid = resp.json()["session_id"]
    assert sid is not None

    # 会话出现在列表里，标题取第一问截断
    sessions = (await client.get("/api/v1/chat/sessions", headers=_auth(token))).json()
    assert len(sessions) == 1
    assert sessions[0]["title"] == "如何申请报销？"

    # 详情含一问一答两条消息
    detail = (
        await client.get(f"/api/v1/chat/sessions/{sid}", headers=_auth(token))
    ).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "如何申请报销？"
    assert detail["messages"][1]["citations"] == []


@pytest.mark.asyncio
async def test_chat_appends_to_existing_session(client):
    await _seed_user("alice", "hr")
    token = await _login(client, "alice")

    sid = (await _ask(client, token, "第一个问题")).json()["session_id"]
    resp = await _ask(client, token, "第二个问题", session_id=sid)
    assert resp.json()["session_id"] == sid

    detail = (
        await client.get(f"/api/v1/chat/sessions/{sid}", headers=_auth(token))
    ).json()
    assert len(detail["messages"]) == 4
    assert [m["role"] for m in detail["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]


@pytest.mark.asyncio
async def test_session_isolation_between_users(client):
    await _seed_user("alice", "hr")
    await _seed_user("bob", "hr")
    token_a = await _login(client, "alice")
    token_b = await _login(client, "bob")

    sid = (await _ask(client, token_a, "机密问题")).json()["session_id"]

    # bob 看不到 alice 的会话：列表空、详情 404
    sessions = (await client.get("/api/v1/chat/sessions", headers=_auth(token_b))).json()
    assert sessions == []
    resp = await client.get(f"/api/v1/chat/sessions/{sid}", headers=_auth(token_b))
    assert resp.status_code == 404
    # bob 拿 alice 的 session_id 追问也被拒
    resp = await _ask(client, token_b, "试试越权", session_id=sid)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(client):
    await _seed_user("alice", "hr")
    token = await _login(client, "alice")

    sid = (await _ask(client, token, "待删除")).json()["session_id"]
    resp = await client.delete(
        f"/api/v1/chat/sessions/{sid}", headers=_auth(token)
    )
    assert resp.status_code == 200

    sessions = (await client.get("/api/v1/chat/sessions", headers=_auth(token))).json()
    assert sessions == []
    resp = await client.get(f"/api/v1/chat/sessions/{sid}", headers=_auth(token))
    assert resp.status_code == 404
