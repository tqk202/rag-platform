"""限流：令牌桶（token bucket）保护 LLM 接口。

为什么 LLM 接口必须限流：一次 /chat 就是一次真实 API 调用、真金白银，
被脚本刷爆或被爬虫打，轻则烧钱、重则服务不可用（W4 评测就意外花过钱）。
令牌桶：以稳态速率往桶里注令牌，每次请求消耗一个令牌；
桶满时允许突发，令牌不足时拒绝并告诉客户端等多久——允许突发 + 限平均速率，
比简单计数器更接近真实流量特征。

单机内存版（单进程开发够用）；生产多副本需要换成 Redis 分布式限流，
思路不变：令牌桶状态放到 Redis，用 Lua 脚本保证原子性。
"""
import asyncio
import math
import time

from app.core.config import get_settings

settings = get_settings()


class TokenBucket:
    """单桶令牌桶。capacity=桶容量（允许的最大突发），refill_rate=每秒注令牌数。"""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def try_acquire(self, tokens: int = 1) -> tuple[bool, float]:
        """尝试消耗 tokens 个令牌。返回 (是否允许, 若拒绝则需等待的秒数)。"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0.0
        return False, (tokens - self.tokens) / self.refill_rate


class RateLimiter:
    """按 key（如用户 id）分配独立令牌桶的限流器。"""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, float]:
        async with self._lock:
            bucket = self._buckets.setdefault(
                key, TokenBucket(self.capacity, self.refill_rate)
            )
            return bucket.try_acquire()

    def reset(self) -> None:
        """清空所有桶（测试用）。"""
        self._buckets.clear()


# 模块级单例：容量 = 每分钟配额（允许突发把桶打满），稳态速率 = RPM / 60
rate_limiter = RateLimiter(
    capacity=float(settings.RATE_LIMIT_RPM),
    refill_rate=settings.RATE_LIMIT_RPM / 60,
)


class RateLimitExceeded(Exception):
    """限流触发。路由层捕获后转 429。"""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"请求过于频繁，请在 {math.ceil(retry_after)} 秒后重试")
