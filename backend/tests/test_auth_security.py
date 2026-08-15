"""P1-3 认证安全测试：登出令牌失效、登录防爆破、弱密钥生产拦截。"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings
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


@pytest.mark.asyncio
async def test_logout_invalidates_token(client):
    """登出后旧令牌立即失效（黑名单 jti）。"""
    await _seed_user("alice")
    resp = await _login(client, "alice")
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # 登出前可用
    me = await client.get("/api/v1/users/me", headers=auth)
    assert me.status_code == 200

    # 登出
    logout = await client.post("/api/v1/auth/logout", headers=auth)
    assert logout.status_code == 200

    # 旧令牌立即失效
    me2 = await client.get("/api/v1/users/me", headers=auth)
    assert me2.status_code == 401


@pytest.mark.asyncio
async def test_login_bruteforce_rate_limited(client):
    """连续失败登录触发 429（防暴力破解）。"""
    await _seed_user("bob")
    for _ in range(10):  # 桶容量 10，前 10 次放行（即使密码错）
        resp = await _login(client, "bob", "wrong-password")
        assert resp.status_code == 401
    resp = await _login(client, "bob", "wrong-password")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_weak_secret_rejected_in_production():
    """生产环境默认占位密钥拒绝启动。"""
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="production", SECRET_KEY="change-me")
