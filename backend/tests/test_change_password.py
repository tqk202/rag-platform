"""W6.5 改密码测试：原密码校验 + 新密码生效。"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import User

PASSWORD = "password123"


async def _seed_user(username: str) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department="hr",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _login(client, username: str, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_change_password_success_and_new_password_works(client):
    await _seed_user("alice")
    resp = await _login(client, "alice")
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    resp = await client.patch(
        "/api/v1/users/me/password",
        headers=_auth(token),
        json={"old_password": PASSWORD, "new_password": "newpass123"},
    )
    assert resp.status_code == 200

    # 旧密码失效，新密码可登录
    assert (await _login(client, "alice")).status_code == 401
    resp = await _login(client, "alice", "newpass123")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_old_password(client):
    await _seed_user("alice")
    resp = await _login(client, "alice")
    token = resp.json()["access_token"]

    resp = await client.patch(
        "/api/v1/users/me/password",
        headers=_auth(token),
        json={"old_password": "wrongold", "new_password": "newpass123"},
    )
    assert resp.status_code == 400

    # 原密码仍可登录
    assert (await _login(client, "alice")).status_code == 200


@pytest.mark.asyncio
async def test_change_password_requires_auth(client):
    resp = await client.patch(
        "/api/v1/users/me/password",
        json={"old_password": PASSWORD, "new_password": "newpass123"},
    )
    assert resp.status_code == 401
