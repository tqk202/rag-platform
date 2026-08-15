"""LLM 服务：抽象接口 + Mock / OpenAI 兼容实现。

- Mock：用「问题与切片字符重叠度」模拟挑资料，跑通链路，不依赖网络
- api：真实 LLM（DeepSeek/通义/Qwen/OpenAI，都是 OpenAI 兼容协议），
  通过 LLM_BACKEND=mock|api 切换。Mock 保留作回归对照。

真实 LLM 的 no_answer 检测：提示词约定「资料中没答案就回答固定短语」，
实现里检测该短语出现即判定 no_answer——这是生产里常见做法（哨兵句）。
"""
import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.http_retry import async_retry

logger = logging.getLogger(__name__)
settings = get_settings()

# Mock 用：重叠度低于该阈值视为"资料中没有相关内容" -> no_answer
OVERLAP_THRESHOLD = 0.25

# 与提示词约定一致的"资料里没答案"哨兵句
NO_ANSWER_SENTINEL = "现有资料中没有找到"


@dataclass
class LLMResult:
    answer: str
    no_answer: bool = False


class LLMProvider:
    """LLM 接口。所有实现都接收「问题 + 编号后的资料切片」，返回回答。"""

    async def generate(self, question: str, chunks: list[dict]) -> LLMResult:
        raise NotImplementedError

    async def generate_stream(self, question: str, chunks: list[dict]):
        """流式生成：逐段产出回答文本。"""
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    def _overlap(self, question: str, content: str) -> float:
        """问题中出现在切片里的字符占比，0~1。简化的"相关性"代理。"""
        q_chars = {ch for ch in question if not ch.isspace()}
        if not q_chars:
            return 0.0
        hits = sum(1 for ch in q_chars if ch in content)
        return hits / len(q_chars)

    async def generate(self, question: str, chunks: list[dict]) -> LLMResult:
        best: tuple[int, dict] | None = None
        best_overlap = 0.0
        for i, c in enumerate(chunks, start=1):
            ov = self._overlap(question, c["content"])
            if ov > best_overlap:
                best, best_overlap = (i, c), ov

        if best is None or best_overlap < OVERLAP_THRESHOLD:
            return LLMResult(
                answer="抱歉，现有资料中没有找到与这个问题相关的内容。", no_answer=True
            )

        idx, chunk = best
        answer = f"根据公司资料[{idx}]：{chunk['content']}"
        return LLMResult(answer=answer)

    async def generate_stream(self, question: str, chunks: list[dict]):
        # 复用 generate 的判断逻辑，只把结果按小块吐出来模拟打字机
        result = await self.generate(question, chunks)
        for i in range(0, len(result.answer), 6):
            yield result.answer[i : i + 6]
            await asyncio.sleep(0.02)


class OpenAICompatibleLLM(LLMProvider):
    """OpenAI 兼容协议的 LLM。base_url 可指向 DeepSeek / 通义 / Qwen / OpenAI。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # transport 注入仅用于测试（MockTransport 模拟上游故障）；生产走真实网络
        self._client = httpx.AsyncClient(timeout=90, transport=transport)

    def _build_messages(self, question: str, chunks: list[dict]) -> list[dict]:
        context = "\n\n".join(f"[{c['no']}] {c['content']}" for c in chunks)
        system = (
            "你是企业知识库问答助手。请严格依据下方提供的资料回答用户问题。\n"
            "资料按 [编号] 组织。回答中凡是依据某条资料的内容，就在对应句子后标注 [编号]。\n"
            "要求：\n"
            "1. 只依据资料，不要编造资料里没有的信息。\n"
            "2. 如果资料中没有答案，第一句就回答：抱歉，现有资料中没有找到与这个问题相关的内容。\n"
            "3. 用简洁通顺的中文回答。\n"
            "4. 标注引用要克制：每个句子后只标注直接支撑它的 [编号]；只引用与回答强相关、真正\n"
            "   支撑答案的资料，不要引用只沾边的。宁可少标，不要为了凑引用而标注弱相关资料。\n"
        )
        user = f"资料：\n{context}\n\n问题：{question}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    async def generate(self, question: str, chunks: list[dict]) -> LLMResult:
        resp = await async_retry(
            lambda: self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": self._build_messages(question, chunks),
                    "temperature": 0.3,
                    "stream": False,
                },
            )
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip()
        return LLMResult(answer=answer, no_answer=NO_ANSWER_SENTINEL in answer)

    async def generate_stream(self, question: str, chunks: list[dict]):
        """OpenAI 兼容协议的流式：stream=True，逐块解析 SSE 里的 delta。"""
        payload = {
            "model": self.model,
            "messages": self._build_messages(question, chunks),
            "temperature": 0.3,
            "stream": True,
        }
        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data or data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta


def get_llm_provider() -> LLMProvider:
    """按配置返回 LLM 实现（LLM_BACKEND: mock | api）。"""
    backend = settings.LLM_BACKEND
    if backend == "mock":
        return MockLLMProvider()
    if backend == "api":
        if not settings.LLM_API_KEY:
            raise RuntimeError("LLM_BACKEND=api 但未配置 LLM_API_KEY（backend/.env）")
        return OpenAICompatibleLLM(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
        )
    raise NotImplementedError(f"llm backend 未实现: {backend}")
