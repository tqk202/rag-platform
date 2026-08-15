"""问答服务：检索 -> 组装上下文 -> LLM 生成 -> 引文标注。

RAG 的完整闭环。核心设计：回答必须带引文（Citation），
让每条回答都能溯源到具体切片——这是降低幻觉的关键，也是企业级 RAG 的门槛。
同时提供流式版 stream_answer，供 SSE 逐字推送。
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.token_counter import estimate_tokens
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, Citation
from app.services import answer_cache, chat_session_service, rerank_service, retrieval_service
from app.services.llm_service import NO_ANSWER_SENTINEL, get_llm_provider

logger = logging.getLogger(__name__)
settings = get_settings()

# 匹配答案文本里的引文标记，如 [2]（LLM 输出格式约定）
_CITE_RE = re.compile(r"\[(\d+)\]")

NO_DOC_ANSWER = "抱歉，没有检索到相关文档。请先上传部门文档，或换个问题。"


async def _retrieve_and_rerank(
    db: AsyncSession, user: User, data: ChatRequest
) -> list[dict]:
    """召回(宽) -> 重排(精) -> 取前 N。重排可关（RERANKER_BACKEND=none）。"""
    chunks = await retrieval_service.hybrid_search(
        db, data.question, user.department, top_k=settings.RERANK_RECALL_K
    )
    if not chunks:
        return []

    reranker = rerank_service.get_reranker_provider()
    if reranker:
        before = [c["chunk_id"] for c in chunks]
        chunks = await reranker.rerank(data.question, chunks)
        logger.info("rerank 前 %s -> 后 %s", before[:5], [c["chunk_id"] for c in chunks[: settings.RERANK_TOP_N]])
    # P1-6 兜底：无论是否重排，都给 LLM 截到上限，防上下文溢出/烧钱
    chunks = chunks[: settings.RERANK_TOP_N]
    return chunks


def _build_citations(numbered: list[dict], answer: str) -> list[Citation]:
    """从答案文本里提取 [编号] 并映射回切片，生成引文列表。

    只保留强相关引文：带重排分的切片里，分数低于最强引文分 * 比例 的剔除，
    避免 LLM 把沾边的资料也标色。重排关闭时无分数，全部保留。
    """
    cited_numbers: list[int] = []
    for m in _CITE_RE.finditer(answer):
        n = int(m.group(1))
        if 1 <= n <= len(numbered) and n not in cited_numbers:
            cited_numbers.append(n)

    scored = [n for n in cited_numbers if numbered[n - 1].get("rerank_score") is not None]
    if scored:
        best = max(numbered[n - 1]["rerank_score"] for n in scored)
        threshold = best * settings.CITATION_MIN_SCORE_RATIO
        cited_numbers = [
            n
            for n in cited_numbers
            if numbered[n - 1].get("rerank_score") is None
            or numbered[n - 1]["rerank_score"] >= threshold
        ]

    return [
        Citation(
            chunk_id=numbered[n - 1]["chunk_id"],
            document_id=numbered[n - 1]["document_id"],
            document_title=numbered[n - 1]["document_title"],
            content=numbered[n - 1]["content"],
            page_no=numbered[n - 1]["page_no"],
        )
        for n in cited_numbers
    ]


async def _persist_and_tag(
    db: AsyncSession, user: User, data: ChatRequest, response: ChatResponse
) -> ChatResponse:
    """问答落库（新建或追加会话），并把真实 session_id 写回响应。"""
    session = await chat_session_service.save_exchange(
        db,
        user,
        data.session_id,
        data.question,
        response.answer,
        response.citations,
        response.no_answer,
    )
    response.session_id = session.id
    return response


def _fit_context_budget(question: str, chunks: list[dict]) -> list[dict]:
    """按 token 预算动态截断检索切片并重新编号（P1-6）。

    传入顺序即优先级（重排后已在前的强相关先保留）；超出预算的后段丢弃。
    """
    used = estimate_tokens(question) + 200  # 问题 + 提示词模板开销
    fitted: list[dict] = []
    for c in chunks:
        used += estimate_tokens(c["content"])
        if used > settings.MAX_CONTEXT_TOKENS:
            break
        fitted.append(c)
    return [{**c, "no": i} for i, c in enumerate(fitted, start=1)]


def _from_cache(cached: dict) -> ChatResponse:
    return ChatResponse(
        answer=cached["answer"],
        citations=[Citation(**c) for c in cached["citations"]],
        no_answer=cached["no_answer"],
    )


async def answer(
    db: AsyncSession, user: User, data: ChatRequest
) -> ChatResponse:
    # 0. 缓存命中直接返回（热问题秒回；权限隔离在缓存键，失效靠部门版本号）
    cached = await answer_cache.lookup(data.question, user.department)
    if cached is not None:
        return await _persist_and_tag(db, user, data, _from_cache(cached))

    # 1. 召回 + 重排（检索层已完成部门权限过滤）
    chunks = await _retrieve_and_rerank(db, user, data)
    if not chunks:
        response = ChatResponse(answer=NO_DOC_ANSWER, citations=[], no_answer=True)
        await answer_cache.store(
            data.question, user.department, response.answer, response.citations, response.no_answer
        )
        return await _persist_and_tag(db, user, data, response)

    # 2. 编号（token 预算截断）-> 组装上下文 -> 生成
    numbered = _fit_context_budget(data.question, chunks)
    llm = get_llm_provider()
    result = await llm.generate(data.question, numbered)

    if result.no_answer:
        response = ChatResponse(answer=result.answer, citations=[], no_answer=True)
    else:
        response = ChatResponse(
            answer=result.answer,
            citations=_build_citations(numbered, result.answer),
            no_answer=False,
        )

    # 3. 回填缓存（同/相近问题下次秒回）+ 落库
    await answer_cache.store(
        data.question, user.department, response.answer, response.citations, response.no_answer
    )
    return await _persist_and_tag(db, user, data, response)


async def stream_answer(db: AsyncSession, user: User, data: ChatRequest):
    """流式问答：产出 (event, payload) 事件序列，供 SSE 传输。

    事件：
    - meta  检索到的资料（供前端展示"检索到 N 条"）
    - delta 一段回答文本（逐字推送）
    - done  完整回答 + 引文 + no_answer
    """
    # 0. 缓存命中：整个回答一次推完（秒回），再落库保证会话历史完整
    cached = await answer_cache.lookup(data.question, user.department)
    if cached is not None:
        citations = [Citation(**c) for c in cached["citations"]]
        session = await chat_session_service.save_exchange(
            db, user, data.session_id, data.question,
            cached["answer"], citations, cached["no_answer"],
        )
        yield "delta", cached["answer"]
        yield "done", {
            "answer": cached["answer"],
            "no_answer": cached["no_answer"],
            "citations": [c.model_dump() for c in citations],
            "session_id": session.id,
        }
        return

    chunks = await _retrieve_and_rerank(db, user, data)
    if not chunks:
        session = await chat_session_service.save_exchange(
            db, user, data.session_id, data.question, NO_DOC_ANSWER, [], True
        )
        await answer_cache.store(data.question, user.department, NO_DOC_ANSWER, [], True)
        yield "done", {
            "answer": NO_DOC_ANSWER,
            "no_answer": True,
            "citations": [],
            "session_id": session.id,
        }
        return

    numbered = _fit_context_budget(data.question, chunks)
    yield "meta", {
        "chunk_count": len(numbered),
        "chunks": [
            {
                "no": c["no"],
                "document_title": c["document_title"],
                "snippet": c["content"][:80],
            }
            for c in numbered
        ],
    }

    llm = get_llm_provider()
    parts: list[str] = []
    async for delta in llm.generate_stream(data.question, numbered):
        parts.append(delta)
        yield "delta", delta

    answer = "".join(parts)
    no_answer = NO_ANSWER_SENTINEL in answer
    citations = _build_citations(numbered, answer)
    # 流式完整回答拿到后回填缓存（相近问题下次秒回）
    await answer_cache.store(data.question, user.department, answer, citations, no_answer)
    # 流式完整回答拿到后才落库，避免回答中断留半个会话
    session = await chat_session_service.save_exchange(
        db, user, data.session_id, data.question, answer, citations, no_answer
    )
    yield "done", {
        "answer": answer,
        "no_answer": no_answer,
        "citations": [c.model_dump() for c in citations],
        "session_id": session.id,
    }
