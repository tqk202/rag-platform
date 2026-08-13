"""评测服务：RAGAS 风格指标的轻量实现（W4）。

四个指标回答面试官"回答质量怎么度量"：
- context_recall    标准答案所在的切片被检索到没有（资料够不够全）
- context_precision 检索回来的切片里多少条真正相关（检索精不精准）
- faithfulness      回答是否忠于检索到的资料（有没有编造）
- answer_relevancy  回答是否切题

前两个是"检索质量"，用黄金评测集（标准答案出处）就能算，不需要 LLM。
后两个是"生成质量"，官方 ragas 用 LLM 当裁判；本项目手写实现——
LLM_BACKEND=api 时用真实 LLM 逐句判断（能讲清原理，面试加分），
LLM_BACKEND=mock 时用启发式兜底（验证流程用，数字是占位）。
"""
import logging
import re

import httpx
import jieba

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 匹配裁判输出的 0~1 数字
_NUM_RE = re.compile(r"[01](?:\.\d+)?|\.\d+")


def _norm(text: str) -> str:
    """去掉所有空白，中文文档逐字可比。"""
    return re.sub(r"\s+", "", text)


def _split_sentences(text: str) -> list[str]:
    """按中文/英文句号分句。"""
    parts = [p.strip() for p in re.split(r"[。！？!?；;\n]", text) if p.strip()]
    return parts or [text]


def _tokenize(text: str) -> list[str]:
    return [w.strip() for w in jieba.lcut(text) if w.strip()]


def is_relevant(chunk_content: str, golden: str) -> bool:
    """一个检索切片是否"相关"：标准答案出处（golden_passage）是否落在该切片里。

    用逐字命中（golden 出现在切片中，或切片整段是 golden 的子串）判断，
    比向量相似度可解释、可复现——评测集是已知答案，不需要模型来判断相关。
    """
    c = _norm(chunk_content)
    g = _norm(golden)
    if not g:
        return False
    return g in c or c in g


def context_precision(contexts: list[str], golden: str) -> float:
    """相关切片在检索结果里的靠前程度（RAGAS 公式）。

    对每个出现在第 i 位的相关切片，记 precision@i = 相关数/i，
    最后对所有相关切片取平均。相关切片排得越靠前，分数越高。
    """
    relevant = 0
    total = 0.0
    for i, c in enumerate(contexts, start=1):
        if is_relevant(c, golden):
            relevant += 1
            total += relevant / i
    return total / relevant if relevant else 0.0


def context_recall(contexts: list[str], golden: str) -> float:
    """标准答案出处是否被检索到（0 或 1）。"""
    return 1.0 if any(is_relevant(c, golden) for c in contexts) else 0.0


def faithfulness_mock(answer: str, contexts: list[str]) -> float:
    """Mock 兜底：回答里每句是否能在检索到的资料里找到词（启发式）。

    Mock LLM 的回答会整段引用某条切片，所以这里基本恒为 1.0——
    这是"跑通流程"的占位值，真实值由真实 LLM 裁判给出。
    """
    if not answer.strip():
        return 1.0
    sentences = _split_sentences(answer)
    pool: set[str] = set()
    for c in contexts:
        pool.update(_tokenize(c))
    if not pool:
        return 0.0
    supported = sum(1 for s in sentences if any(t in pool for t in _tokenize(s)))
    return supported / len(sentences)


class LLMJudge:
    """真实 LLM 裁判：LLM_BACKEND=api 时启用，逐句判断回答是否忠于资料。"""

    def __init__(self, s: Settings = settings):
        self.enabled = s.LLM_BACKEND == "api"
        self._client = None
        if self.enabled:
            self._client = httpx.AsyncClient(
                base_url=s.LLM_BASE_URL.rstrip("/"),
                headers={"Authorization": f"Bearer {s.LLM_API_KEY}"},
                timeout=60,
            )

    async def ask(self, system: str, user: str) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def faithfulness_llm(judge: LLMJudge, answer: str, contexts: list[str]) -> float:
    """Faithfulness：拆句 → 逐句问 LLM 是否被资料支持 → 支持占比。

    这就是官方 ragas faithfulness 的做法，手写以便面试时讲清原理。
    """
    if not answer.strip():
        return 1.0
    sentences = _split_sentences(answer)
    if not sentences:
        return 1.0

    ctx = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(contexts, start=1))
    system = "你是 RAG 问答系统的评测助手，只负责判断回答是否忠于给定的资料。"
    user = (
        f"资料：\n{ctx}\n\n回答：\n{answer}\n\n"
        "请把回答按句拆开，逐句判断该句是否有资料依据（资料支持 = 1，资料没有/编造 = 0）。"
        "每句单独一行输出一个数字：1 或 0。"
    )
    try:
        out = await judge.ask(system, user)
    except Exception:
        logger.warning("faithfulness 裁判调用失败，给中性分 0.5", exc_info=True)
        return 0.5

    supported = sum(1 for line in out.splitlines() if line.strip() == "1")
    judged = sum(1 for line in out.splitlines() if line.strip() in ("0", "1"))
    return supported / judged if judged else 0.5


async def answer_relevancy_llm(judge: LLMJudge, question: str, answer: str) -> float:
    """Answer relevancy：直接让 LLM 对"回答是否切题"打分 0~1。"""
    if not answer.strip():
        return 0.0
    system = "你是 RAG 问答系统的评测助手，只负责判断回答是否切题。"
    user = (
        f"问题：{question}\n\n回答：{answer}\n\n"
        "判断：这个回答是否直接、切题地回答了问题？只输出一个 0 到 1 之间的小数"
        "（0 = 完全跑题，1 = 完全切题），不要输出任何其他内容。"
    )
    try:
        out = await judge.ask(system, user)
    except Exception:
        logger.warning("answer_relevancy 裁判调用失败，给中性分 0.5", exc_info=True)
        return 0.5
    m = _NUM_RE.search(out)
    if not m:
        return 0.5
    return max(0.0, min(1.0, float(m.group(0))))


async def evaluate_case(
    judge: LLMJudge,
    question: str,
    answer: str,
    no_answer: bool,
    contexts: list[str],
    golden: str,
) -> dict:
    """跑一个评测问题的全部指标。"""
    if not contexts:
        return {
            "context_precision": 0.0,
            "context_recall": 0.0,
            "faithfulness": 0.0,
            "answer_relevancy": 0.0,
            "no_answer": no_answer,
        }

    cp = context_precision(contexts, golden)
    cr = context_recall(contexts, golden)

    if judge.enabled:
        fa = await faithfulness_llm(judge, answer, contexts)
        ar = await answer_relevancy_llm(judge, question, answer)
    else:
        fa = faithfulness_mock(answer, contexts)
        # no_answer = 没回答上问题，切题度记 0；正常回答记 1（mock 占位）
        ar = 0.0 if no_answer else 1.0

    return {
        "context_precision": round(cp, 4),
        "context_recall": round(cr, 4),
        "faithfulness": round(fa, 4),
        "answer_relevancy": round(ar, 4),
        "no_answer": no_answer,
    }
