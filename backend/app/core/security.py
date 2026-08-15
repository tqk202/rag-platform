"""密码哈希 + JWT：认证是后端岗的必考题，安全细节在这里集中管理。"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    # jti（token 唯一 id）：登出时把 jti 拉黑，令牌立即失效（P1-3）
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError("登录态无效或已过期") from exc


def token_jti_and_ttl(token: str) -> tuple[str, int]:
    """返回 (jti, 剩余有效秒数)，登出拉黑时确定黑名单 TTL。"""
    payload = decode_access_token(token)
    remaining = int(payload["exp"] - datetime.now(UTC).timestamp())
    return payload.get("jti", ""), max(remaining, 0)
