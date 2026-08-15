"""P1-6 上下文预算测试：token 估算、预算截断、max_tokens 输出上限。"""
import httpx
import pytest

from app.core.config import get_settings
from app.core.token_counter import estimate_tokens
from app.services import rag_service
from app.services.llm_service import OpenAICompatibleLLM

settings = get_settings()

BASE = "https://x.example/v1"
API_KEY = "key"
MODEL = "deepseek-chat"


def _llm(handler):
    return OpenAICompatibleLLM(BASE, API_KEY, MODEL, transport=httpx.MockTransport(handler))


def test_estimate_tokens_heuristic():
    """中文约 1 字 1 token，英文约 4 字符 1 token。"""
    assert estimate_tokens("员工年假每年10天") == 8  # 7 中文 + "10"(2字符/4=1)
    assert estimate_tokens("hello world") == 3  # 11 字符 / 4 ≈ 3


def test_fit_context_budget_truncates(monkeypatch):
    """预算不足时检索切片被动态截断，且重新编号连续。"""
    monkeypatch.setattr(settings, "MAX_CONTEXT_TOKENS", 400)
    chunks = [{"content": "员工年假每年10天需提前申请。"} for _ in range(20)]
    fitted = rag_service._fit_context_budget("年假", chunks)
    assert 0 < len(fitted) < 20
    assert [c["no"] for c in fitted] == list(range(1, len(fitted) + 1))


def test_fit_context_budget_respects_budget(monkeypatch):
    """截断后总 token 不超过预算（含问题 + 模板开销）。"""
    monkeypatch.setattr(settings, "MAX_CONTEXT_TOKENS", 400)
    chunks = [{"content": "报销需要发票，餐费每人每天上限50元。"} for _ in range(20)]
    fitted = rag_service._fit_context_budget("报销", chunks)
    used = estimate_tokens("报销") + 200 + sum(
        estimate_tokens(c["content"]) for c in fitted
    )
    assert used <= 400
    assert len(fitted) < 20


@pytest.mark.asyncio
async def test_generate_payload_includes_max_tokens():
    """LLM 请求带 max_tokens 输出上限（防长回答失控）。"""
    seen = {}

    def handler(request: httpx.Request):
        seen["payload"] = request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "答案是 x"}}]},
        )

    result = await _llm(handler).generate("年假", [{"no": 1, "content": "年假10天"}])
    assert result.answer == "答案是 x"
    assert f'"max_tokens":{settings.MAX_OUTPUT_TOKENS}' in seen["payload"]
