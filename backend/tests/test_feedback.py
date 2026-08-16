"""回答反馈测试：提交 / 切换 / 取消 / 越权 403 / 管理端列表 RBAC。"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.feedback import AnswerFeedback
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, role: Role = Role.member, department: str = "hr") -> int:
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


async def _ask(client, token: str, question: str = "年假有几天？") -> int:
    resp = await client.post("/api/v1/chat", headers=_auth(token), json={"question": question})
    assert resp.status_code == 200, resp.text
    assert resp.json()["message_id"] is not None
    return resp.json()["message_id"]


@pytest.mark.asyncio
async def test_submit_then_toggle_then_cancel(client):
    """同倾向再点 = 取消；异倾向 = 切换。最终无残留记录。"""
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")
    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    msg_id = await _ask(client, token)

    r1 = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token),
        json={"sentiment": "like"},
    )
    assert r1.status_code == 200
    assert r1.json()["sentiment"] == "like"

    r2 = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token),
        json={"sentiment": "dislike", "comment": "答案不准确"},
    )
    assert r2.json()["sentiment"] == "dislike"

    r3 = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token),
        json={"sentiment": "dislike"},
    )
    assert r3.json()["sentiment"] is None  # 再点同倾向 = 取消

    async with AsyncSessionLocal() as db:
        rows = list((await db.scalars(select(AnswerFeedback))).all())
        assert rows == []


@pytest.mark.asyncio
async def test_feedback_only_own_message(client):
    """只能给自己的消息反馈：他人消息 403。"""
    await _seed_user("user_a", Role.member)
    await _seed_user("user_b", Role.member)
    token_a = await _login(client, "user_a")
    token_b = await _login(client, "user_b")

    msg_id = await _ask(client, token_a)

    resp = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token_b),
        json={"sentiment": "like"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invalid_sentiment_rejected(client):
    await _seed_user("member_hr", Role.member)
    token = await _login(client, "member_hr")
    msg_id = await _ask(client, token)
    resp = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token),
        json={"sentiment": "neutral"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_lists_feedback_and_rbac(client):
    """管理端列表：manager 403，admin 可见反馈含问题上下文。"""
    await _seed_user("mgr_hr", Role.manager)
    mgr_token = await _login(client, "mgr_hr")
    await _seed_user("member_hr", Role.member)
    member_token = await _login(client, "member_hr")
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")

    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    await client.post("/api/v1/documents/upload", headers=_auth(mgr_token), files=files)
    msg_id = await _ask(client, member_token)
    await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(member_token),
        json={"sentiment": "dislike", "comment": "不对"},
    )

    r403 = await client.get("/api/v1/admin/feedback", headers=_auth(mgr_token))
    assert r403.status_code == 403

    r = await client.get("/api/v1/admin/feedback", headers=_auth(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["username"] == "member_hr"
    assert item["sentiment"] == "dislike"
    assert item["question"] == "年假有几天？"
    assert item["comment"] == "不对"
