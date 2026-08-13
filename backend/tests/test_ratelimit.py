"""W5 限流测试：令牌桶单元测试 + /chat 429 集成测试。

面试官会问"限流真的生效了吗"——429 测试就是证据：
同一个用户连打两个请求，第二个被拒绝并拿到 Retry-After。
"""
import asyncio

import pytest

from app.api import deps
from app.core.ratelimit import RateLimiter, TokenBucket
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User

PASSWORD = "password123"


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_then_denies():
    bucket = TokenBucket(capacity=2, refill_rate=1.0)
    assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is True
    allowed, retry_after = bucket.try_acquire()
    assert allowed is False
    assert retry_after > 0  # 返回需要等待的秒数


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time():
    bucket = TokenBucket(capacity=1, refill_rate=2.0)  # 每秒补 2 个令牌
    assert bucket.try_acquire()[0] is True  # 打光
    await asyncio.sleep(0.6)  # 0.6s 补回 1.2 个
    assert bucket.try_acquire()[0] is True


@pytest.mark.asyncio
async def test_rate_limiter_keys_are_isolated():
    """每个用户独立令牌桶：A 被打满不影响 B。"""
    limiter = RateLimiter(capacity=1, refill_rate=1.0)
    assert (await limiter.allow("user_a"))[0] is True
    assert (await limiter.allow("user_b"))[0] is True
    assert (await limiter.allow("user_a"))[0] is False


async def _seed_user(username: str, department: str, role: Role) -> int:
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


@pytest.mark.asyncio
async def test_chat_returns_429_when_rate_limit_exceeded(client, monkeypatch):
    """容量=1：第一个请求通过（200），第二个被限流（429 + Retry-After）。"""
    monkeypatch.setattr(deps, "rate_limiter", RateLimiter(capacity=1, refill_rate=0.001))
    await _seed_user("rl_user", "hr", Role.member)
    token = await _login(client, "rl_user")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"question": "介绍一下公司年假制度"}

    first = await client.post("/api/v1/chat", json=payload, headers=headers)
    assert first.status_code == 200, first.text

    second = await client.post("/api/v1/chat", json=payload, headers=headers)
    assert second.status_code == 429
    assert second.headers.get("retry-after")
    assert second.json()["code"] == "RATE_LIMITED"
