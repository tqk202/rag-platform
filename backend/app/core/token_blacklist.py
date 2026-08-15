"""令牌黑名单（P1-3）：登出后令牌立即失效。

无状态 JWT 无法主动撤销，登出靠把 token 的 jti 记进黑名单，TTL = 剩余有效期。
生产 Redis，测试内存（core/kv 可插拔）。黑名单是安全冗余而非依赖：
Redis 挂了只影响"登出立即使旧令牌失效"，校验时查不到就当有效放行。
"""
import logging

from app.core.config import get_settings
from app.core.kv import CacheKV, build_default_kv

logger = logging.getLogger(__name__)
settings = get_settings()

KEY_PREFIX = "bl:"

_holder: dict[str, CacheKV] = {}


def _store() -> CacheKV:
    if not _holder:
        _holder["kv"] = build_default_kv()
    return _holder["kv"]


def _key(jti: str) -> str:
    return f"{KEY_PREFIX}{jti}"


async def revoke(jti: str, ttl_seconds: int) -> None:
    """把 jti 拉黑到过期为止。失败只影响登出即时性，不阻断登出流程。"""
    try:
        await _store().set(_key(jti), "1", max(ttl_seconds, 1))
    except Exception:
        logger.exception("令牌拉黑失败（登出仍返回成功，安全性降级）")


async def is_revoked(jti: str) -> bool:
    try:
        return await _store().get(_key(jti)) is not None
    except Exception:
        logger.exception("黑名单查询失败，按未拉黑放行")
        return False


async def reset_blacklist() -> None:
    """测试用：清空黑名单，保证用例隔离。"""
    await _store().clear()
