"""通用键值存储：redis（生产）| memory（测试/无 Redis）。

回答缓存（W11）与令牌黑名单（P1-3）共用同一抽象：生产 Redis、
测试内存，避免测试依赖外部服务。沿用 W8 SparseIndex 可插拔思路。
"""
import logging
import time
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CacheKV(Protocol):
    """键值存储协议：get/set/incr/clear。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...

    async def incr(self, key: str) -> int: ...

    async def clear(self) -> None: ...


class MemoryCacheKV:
    """进程内实现：字典 + 过期时间，测试/无 Redis 环境用。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expire: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        exp = self._expire.get(key)
        if exp is not None and exp <= time.monotonic():
            self._data.pop(key, None)
            self._expire.pop(key, None)
            return None
        return self._data.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = value
        self._expire[key] = time.monotonic() + ttl

    async def incr(self, key: str) -> int:
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val

    async def clear(self) -> None:
        self._data.clear()
        self._expire.clear()


class RedisCacheKV:
    """生产实现：Redis。懒导入避免内存模式也拉 redis 依赖。"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._r.set(key, value, ex=ttl)

    async def incr(self, key: str) -> int:
        return await self._r.incr(key)

    async def clear(self) -> None:
        await self._r.flushdb()


def build_default_kv() -> CacheKV:
    """按配置返回 KV 实现（ANSWER_CACHE_BACKEND: redis | memory）。"""
    if settings.ANSWER_CACHE_BACKEND == "redis":
        return RedisCacheKV(settings.REDIS_URL)
    return MemoryCacheKV()
