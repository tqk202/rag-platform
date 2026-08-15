"""P1-5 审计日志测试：文档操作留痕 + 管理员可查 + 非管理员 403。"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.user import Role, User

PASSWORD = "password123"


async def _seed_user(username: str, role: Role) -> int:
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


async def _upload(client, token: str, content: str, name: str = "制度.txt") -> int:
    files = {"file": (name, content, "text/plain")}
    resp = await client.post(
        "/api/v1/documents/upload", headers=_auth(token), files=files
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


@pytest.mark.asyncio
async def test_document_ops_written_to_audit_log(client):
    """上传 + 升版 + 删除都应留痕，且含操作人。"""
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")

    doc_id = await _upload(client, token, "员工年假每年10天。", "年假制度.txt")
    # 升版
    await _upload(client, token, "员工年假每年15天。", "年假制度.txt")
    # 删除
    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        logs = list(
            (await db.scalars(select(AuditLog).order_by(AuditLog.id))).all()
        )

    actions = [log.action for log in logs]
    assert actions == ["document.upload", "document.update", "document.delete"]
    assert all(log.actor_username == "mgr_hr" for log in logs)
    assert logs[0].object_id == doc_id


@pytest.mark.asyncio
async def test_audit_logs_endpoint_admin_only(client):
    """审计查询仅 admin：manager 403。"""
    await _seed_user("mgr_hr", Role.manager)
    token = await _login(client, "mgr_hr")
    resp = await client.get("/api/v1/admin/audit-logs", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_queries_audit_logs(client):
    """admin 可查审计，且能按 action 过滤。"""
    await _seed_user("admin", Role.admin)
    admin_token = await _login(client, "admin")
    await _seed_user("mgr_hr", Role.manager)
    mgr_token = await _login(client, "mgr_hr")

    await _upload(client, mgr_token, "员工年假每年10天。", "年假制度.txt")

    resp = await client.get(
        "/api/v1/admin/audit-logs", headers=_auth(admin_token)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(a["action"] == "document.upload" for a in data["items"])

    resp2 = await client.get(
        "/api/v1/admin/audit-logs?action=document.delete", headers=_auth(admin_token)
    )
    assert resp2.json()["items"] == []
