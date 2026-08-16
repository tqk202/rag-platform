"""查询改写：检索前把口语化问题改写成适合混合检索的查询。

QUERY_REWRITE 三种模式（config 控制）：
- off   默认。不改写，检索行为与评测基线完全一致。
- rule  纯规则：去口语填充词 / 去句尾问号 / 同义收敛，零成本离线可跑。
- llm   真实 LLM 改写（检索质量最好，花一次 LLM 调用）；
        LLM_BACKEND=mock 或调用异常时自动回退规则改写，保证离线/CI 可用。

关键设计：改写只影响「检索 + 重排」用的查询串；LLM 生成与回答缓存仍用原始问题
——用户要的是原始问题的答案，缓存键也应按用户意图稳定（同一问题改写成不同串
会破坏缓存命中）。
"""
import logging
import re

from app.core.config import get_settings
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)
settings = get_settings()

# 口语填充词：检索前剥掉，避免污染全文检索查询
_FILLERS = [
    "请问一下", "麻烦问下", "麻烦帮我查", "麻烦查一下", "帮我查一下", "帮我查查",
    "帮我查", "我想知道一下", "我想知道", "我想问一下", "我想问", "问一下",
    "能不能告诉我", "请问", "谢谢", "拜托",
]
# 同义收敛（只做口语/近义 -> 文档常用词，扩大召回；不做危险扩展）
_SYNONYMS = {"赔偿": "补偿"}


def _rule_rewrite(query: str) -> str:
    q = query
    for f in _FILLERS:
        q = q.replace(f, "")
    for src, dst in _SYNONYMS.items():
        q = q.replace(src, dst)
    q = re.sub(r"[?？。]+$", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q or query  # 全被剥光时保底原问题


async def rewrite_question(query: str) -> str:
    """按配置改写查询。off 原样返回，rule 走规则，llm 优先 LLM、异常/mock 回退规则。"""
    mode = settings.QUERY_REWRITE
    if mode == "off":
        return query
    if mode == "rule":
        return _rule_rewrite(query)
    if mode == "llm":
        if settings.LLM_BACKEND == "api":
            try:
                rewritten = await get_llm_provider().rewrite(query)
                if rewritten and rewritten.strip():
                    return rewritten.strip()
            except Exception:
                logger.exception("LLM 查询改写失败，回退规则改写")
        return _rule_rewrite(query)
    return query
