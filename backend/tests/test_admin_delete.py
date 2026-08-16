"""管理端删除功能测试：反馈/追踪单删、批量、清空（仅 admin + 留痕）；审计日志按时间清理。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.feedback import AnswerFeedback
from app.models.query_trace import QueryTrace
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


async def _seed_feedback(client, token: str, sentiment: str = "dislike") -> int:
    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    resp = await client.post(
        "/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"}
    )
    assert resp.status_code == 200, resp.text
    msg_id = resp.json()["message_id"]
    r = await client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback", headers=_auth(token),
        json={"sentiment": sentiment},
    )
    assert r.status_code == 200
    # 反馈 id 从管理端列表取
    admin_token = await _login(client, "admin")
    page = await client.get("/api/v1/admin/feedback", headers=_auth(admin_token))
    assert page.status_code == 200
    return page.json()["items"][0]["id"]


@pytest.mark.asyncio
async def test_delete_feedback_rbac(client):
    """删除反馈：manager 403，admin 成功且审计留痕。"""
    await _seed_user("mgr_hr", Role.manager)
    mgr_token = await _login(client, "mgr_hr")
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    fb_id = await _seed_feedback(client, mgr_token)

    r403 = await client.delete(
        f"/api/v1/admin/feedback/{fb_id}", headers=_auth(mgr_token)
    )
    assert r403.status_code == 403

    r = await client.delete(
        f"/api/v1/admin/feedback/{fb_id}", headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == 1

    async with AsyncSessionLocal() as db:
        assert not list((await db.scalars(select(AnswerFeedback))).all())
        actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "feedback.delete" in actions


@pytest.mark.asyncio
async def test_delete_feedback_not_found(client):
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")
    r = await client.delete("/api/v1/admin/feedback/99999", headers=_auth(token))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_batch_and_clear_feedback(client):
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")
    ids = [await _seed_feedback(client, token) for _ in range(3)]

    r = await client.post(
        "/api/v1/admin/feedback/batch-delete",
        headers=_auth(token),
        json={"ids": ids[:2]},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    r2 = await client.post(
        "/api/v1/admin/feedback/clear-all", headers=_auth(token)
    )
    assert r2.status_code == 200
    assert r2.json()["deleted"] == 1

    async with AsyncSessionLocal() as db:
        assert not list((await db.scalars(select(AnswerFeedback))).all())
        actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "feedback.batch_delete" in actions
    assert "feedback.clear" in actions


@pytest.mark.asyncio
async def test_trace_delete_and_clear(client):
    """追踪单删/批量/清空 + 留痕；追踪在问答时自动写入。"""
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")

    for _ in range(3):
        files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
        await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
        await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})

    page = await client.get("/api/v1/admin/traces", headers=_auth(token))
    trace_ids = [t["id"] for t in page.json()["items"]]
    assert len(trace_ids) == 3

    r1 = await client.delete(
        f"/api/v1/admin/traces/{trace_ids[0]}", headers=_auth(token)
    )
    assert r1.status_code == 200
    assert r1.json()["deleted"] == 1

    r2 = await client.post(
        "/api/v1/admin/traces/batch-delete",
        headers=_auth(token),
        json={"ids": trace_ids[1:]},
    )
    assert r2.status_code == 200
    assert r2.json()["deleted"] == 2

    page2 = await client.get("/api/v1/admin/traces", headers=_auth(token))
    assert page2.json()["total"] == 0

    # 再造一条再清空
    files = {"file": ("年假制度.txt", "员工年假每年10天。", "text/plain")}
    await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "年假有几天？"})
    r3 = await client.post("/api/v1/admin/traces/clear-all", headers=_auth(token))
    assert r3.status_code == 200
    assert r3.json()["deleted"] == 1

    async with AsyncSessionLocal() as db:
        assert not list((await db.scalars(select(QueryTrace))).all())
        actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "trace.delete" in actions
    assert "trace.batch_delete" in actions
    assert "trace.clear" in actions


@pytest.mark.asyncio
async def test_cleanup_audit_logs(client):
    """审计日志只能按时间清理：旧记录删、近期保留、清理动作本身留痕。"""
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")

    async with AsyncSessionLocal() as db:
        db.add(AuditLog(actor_username="old", action="old.test", created_at=datetime(2020, 1, 1)))
        db.add(
            AuditLog(
                actor_username="new", action="new.test",
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    r = await client.post(
        "/api/v1/admin/audit-logs/cleanup",
        headers=_auth(token),
        json={"before_days": 30},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1

    async with AsyncSessionLocal() as db:
        actions = list((await db.scalars(select(AuditLog.action))).all())
    assert "new.test" in actions
    assert "old.test" not in actions
    assert "audit.cleanup" in actions


@pytest.mark.asyncio
async def test_cleanup_audit_logs_validation(client):
    """before_days 越界/负数被 422 拒绝。"""
    await _seed_user("admin", Role.admin)
    token = await _login(client, "admin")
    r = await client.post(
        "/api/v1/admin/audit-logs/cleanup",
        headers=_auth(token),
        json={"before_days": 0},
    )
    assert r.status_code == 422
