"""查询改写测试：rule 规则 / off 直通 / llm mock 兜底 / 聊天链路生效。"""
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.query_trace import QueryTrace
from app.models.user import Role, User
from app.services.rewrite_service import _rule_rewrite, rewrite_question

settings = get_settings()
PASSWORD = "password123"


def test_rule_rewrite_strips_fillers_and_trailing_q():
    assert _rule_rewrite("请问帮我查一下年假有几天？") == "年假有几天"
    assert _rule_rewrite("赔偿标准是多少") == "补偿标准是多少"  # 同义收敛


@pytest.mark.asyncio
async def test_off_mode_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_REWRITE", "off")
    assert await rewrite_question("请问年假有几天？") == "请问年假有几天？"


@pytest.mark.asyncio
async def test_llm_mode_falls_back_to_rule_on_mock(monkeypatch):
    """llm 模式 + mock 后端：退化为规则改写（离线/CI 可用）。"""
    monkeypatch.setattr(settings, "QUERY_REWRITE", "llm")
    monkeypatch.setattr(settings, "LLM_BACKEND", "mock")
    assert await rewrite_question("请问赔偿标准是多少？") == "补偿标准是多少"


async def _seed_user(username: str, role: Role = Role.manager) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department="hr",
            role=role,
        )
        db.add(user)
        await db.commit()
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


@pytest.mark.asyncio
async def test_rewrite_improves_retrieval_in_chat(client, monkeypatch):
    """改写作用于检索链路：off 不改写；rule 把「赔偿」收敛成「补偿」并传入检索。

    注：这里验证的是「改写串真正进入检索」——不直接断言 LLM 判定（mock LLM 用
    原始问题做字符重叠判定，「赔偿」与「补偿」恰好无重叠，会误判 no_answer）。
    """
    await _seed_user("mgr_hr")
    token = await _login(client, "mgr_hr")
    files = {"file": ("补偿制度.txt", "员工离职经济补偿按每满一年一个月工资。", "text/plain")}
    resp = await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)
    assert resp.status_code == 200, resp.text

    monkeypatch.setattr(settings, "ANSWER_CACHE_ENABLED", False)  # 避免缓存串两轮对比

    monkeypatch.setattr(settings, "QUERY_REWRITE", "off")
    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "赔偿标准是多少？"})

    monkeypatch.setattr(settings, "QUERY_REWRITE", "rule")
    await client.post("/api/v1/chat", headers=_auth(token), json={"question": "赔偿标准是多少？"})

    async with AsyncSessionLocal() as db:
        traces = list((await db.scalars(select(QueryTrace).order_by(QueryTrace.id))).all())
    assert len(traces) == 2
    assert traces[0].rewritten_query is None  # off 不改写，检索用原问题
    assert traces[1].rewritten_query == "补偿标准是多少"  # rule 改写「赔偿」→「补偿」用于检索
    assert traces[1].retrieved_count >= 1  # 改写后检索确实命中
