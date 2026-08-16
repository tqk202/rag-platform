"""问答服务：查询改写 -> 检索 -> 组装上下文 -> LLM 生成 -> 引文标注。

RAG 的完整闭环。核心设计：回答必须带引文（Citation），
让每条回答都能溯源到具体切片——这是降低幻觉的关键，也是企业级 RAG 的门槛。
同时提供流式版 stream_answer，供 SSE 逐字推送。

可观测（自建 trace + 指标）：每次问答落一条 query_traces（阶段耗时/token/缓存命中），
并更新 Prometheus 业务指标；两者都 best-effort，绝不拖垮主链路。
"""
import json
import logging
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import get_settings
from app.core.observability import request_id_var
from app.core.token_counter import estimate_tokens
from app.models.query_trace import QueryTrace
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse, Citation
from app.services import answer_cache, chat_session_service, rerank_service, retrieval_service
from app.services.llm_service import NO_ANSWER_SENTINEL, get_llm_provider
from app.services.rewrite_service import rewrite_question

logger = logging.getLogger(__name__)
settings = get_settings()

# 匹配答案文本里的引文标记，如 [2]（LLM 输出格式约定）
_CITE_RE = re.compile(r"\[(\d+)\]")

NO_DOC_ANSWER = "抱歉，没有检索到相关文档。请先上传部门文档，或换个问题。"


async def _retrieve_and_rerank(
    db: AsyncSession, user: User, data: ChatRequest
) -> tuple[list[dict], str]:
    """查询改写 -> 召回(宽) -> 重排(精) -> 取前 N。返回 (切片, 改写后的查询)。

    改写只作用于检索/重排；LLM 生成与缓存键仍用原始问题（见 rewrite_service）。
    """
    query = await rewrite_question(data.question)
    chunks = await retrieval_service.hybrid_search(
        db, query, user.department, data.knowledge_base, top_k=settings.RERANK_RECALL_K
    )
    if not chunks:
        return [], query

    reranker = rerank_service.get_reranker_provider()
    if reranker:
        before = [c["chunk_id"] for c in chunks]
        chunks = await reranker.rerank(query, chunks)
        logger.info("rerank 前 %s -> 后 %s", before[:5], [c["chunk_id"] for c in chunks[: settings.RERANK_TOP_N]])
    # P1-6 兜底：无论是否重排，都给 LLM 截到上限，防上下文溢出/烧钱
    chunks = chunks[: settings.RERANK_TOP_N]
    return chunks, query


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
        data.knowledge_base,
    )
    response.session_id = session.id
    response.message_id = await chat_session_service.last_assistant_message_id(db, session.id)
    return response


def _fit_context_budget(
    question: str, chunks: list[dict], history: list[dict] | None = None
) -> list[dict]:
    """按 token 预算动态截断检索切片并重新编号（P1-6）。

    传入顺序即优先级（重排后已在前的强相关先保留）；超出预算的后段丢弃。
    多轮历史也计入预算（P2-1），避免历史挤掉检索上下文。
    """
    used = estimate_tokens(question) + 200  # 问题 + 提示词模板开销
    for h in history or []:
        used += estimate_tokens((h.get("content") or "")[: settings.MAX_HISTORY_CHARS])
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


async def _save_trace(
    db: AsyncSession,
    *,
    rid: str,
    user: User,
    data: ChatRequest,
    cache_hit: bool,
    retrieved: int,
    no_answer: bool,
    latency_ms: int,
    timing: dict,
    answer: str,
    rewritten: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    """best-effort 落一条调用追踪：观测是附加值，异常绝不影响问答主链路。"""
    try:
        db.add(
            QueryTrace(
                request_id=rid,
                user_id=user.id,
                department=user.department,
                knowledge_base=data.knowledge_base,
                question=data.question,
                rewritten_query=rewritten,
                cache_hit=cache_hit,
                retrieved_count=retrieved,
                no_answer=no_answer,
                llm_input_tokens=tokens_in,
                llm_output_tokens=tokens_out,
                latency_ms=latency_ms,
                stage_timing=json.dumps(timing, ensure_ascii=False),
                answer_preview=(answer or "")[:500],
            )
        )
        await db.commit()
    except Exception:
        logger.exception("调用追踪写入失败（不影响主链路）")
        await db.rollback()


def _trace_rewritten(query: str) -> str | None:
    """trace 里只有真正启用改写时才记录改写串，否则为 None。"""
    return query if settings.QUERY_REWRITE != "off" else None


async def answer(
    db: AsyncSession, user: User, data: ChatRequest
) -> ChatResponse:
    t0 = time.perf_counter()
    rid = request_id_var.get() or ""
    timing: dict = {}

    # 0. 缓存命中直接返回（热问题秒回；仅单轮——多轮含会话上下文，缓存会答非所问）
    t = time.perf_counter()
    cached = (
        None
        if data.history
        else await answer_cache.lookup(data.question, user.department, data.knowledge_base)
    )
    timing["cache_ms"] = round((time.perf_counter() - t) * 1000)
    if cached is not None:
        metrics.record_question(user.department, True)
        response = await _persist_and_tag(db, user, data, _from_cache(cached))
        await _save_trace(
            db, rid=rid, user=user, data=data, cache_hit=True, retrieved=0,
            no_answer=cached["no_answer"], latency_ms=round((time.perf_counter() - t0) * 1000),
            timing=timing, answer=cached["answer"],
        )
        return response
    metrics.record_question(user.department, False)

    # 1. 召回 + 重排（检索层已完成部门/知识库权限过滤）
    t = time.perf_counter()
    chunks, query = await _retrieve_and_rerank(db, user, data)
    timing["retrieve_ms"] = round((time.perf_counter() - t) * 1000)

    if not chunks:
        response = ChatResponse(answer=NO_DOC_ANSWER, citations=[], no_answer=True)
        if not data.history:
            await answer_cache.store(
                data.question, user.department, data.knowledge_base,
                response.answer, response.citations, response.no_answer,
            )
        response = await _persist_and_tag(db, user, data, response)
        metrics.record_no_answer()
        await _save_trace(
            db, rid=rid, user=user, data=data, cache_hit=False, retrieved=0, no_answer=True,
            latency_ms=round((time.perf_counter() - t0) * 1000), timing=timing,
            answer=response.answer, rewritten=_trace_rewritten(query),
        )
        return response

    # 2. 编号（token 预算截断）-> 组装上下文 -> 生成（P2-1 带多轮历史）
    numbered = _fit_context_budget(data.question, chunks, data.history)
    llm = get_llm_provider()
    metrics.record_llm_call()
    t = time.perf_counter()
    try:
        result = await llm.generate(data.question, numbered, data.history)
    except Exception:
        metrics.record_llm_error()
        raise
    timing["llm_ms"] = round((time.perf_counter() - t) * 1000)

    if result.no_answer:
        response = ChatResponse(answer=result.answer, citations=[], no_answer=True)
    else:
        response = ChatResponse(
            answer=result.answer,
            citations=_build_citations(numbered, result.answer),
            no_answer=False,
        )

    # 3. 回填缓存（单轮同/相近问题下次秒回）+ 落库
    if not data.history:
        await answer_cache.store(
            data.question, user.department, data.knowledge_base,
            response.answer, response.citations, response.no_answer,
        )
    response = await _persist_and_tag(db, user, data, response)
    if response.no_answer:
        metrics.record_no_answer()

    tokens_in = estimate_tokens(data.question) + sum(
        estimate_tokens(c["content"]) for c in numbered
    )
    tokens_out = estimate_tokens(response.answer)
    await _save_trace(
        db, rid=rid, user=user, data=data, cache_hit=False, retrieved=len(numbered),
        no_answer=response.no_answer, latency_ms=round((time.perf_counter() - t0) * 1000),
        timing=timing, answer=response.answer, rewritten=_trace_rewritten(query),
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
    metrics.record_latency(time.perf_counter() - t0)
    return response


async def stream_answer(db: AsyncSession, user: User, data: ChatRequest):  # noqa: PLR0915
    """流式问答：产出 (event, payload) 事件序列，供 SSE 传输。

    noqa: SSE 问答管线阶段线性、共享状态，拆散反而难读。


    事件：
    - meta  检索到的资料（供前端展示"检索到 N 条"）
    - delta 一段回答文本（逐字推送）
    - done  完整回答 + 引文 + no_answer
    """
    t0 = time.perf_counter()
    rid = request_id_var.get() or ""
    timing: dict = {}

    # 0. 缓存命中：整个回答一次推完（秒回），再落库保证会话历史完整。
    #    仅单轮走缓存——多轮含会话上下文，缓存会答非所问（P2-1）
    t = time.perf_counter()
    cached = (
        None
        if data.history
        else await answer_cache.lookup(data.question, user.department, data.knowledge_base)
    )
    timing["cache_ms"] = round((time.perf_counter() - t) * 1000)
    if cached is not None:
        metrics.record_question(user.department, True)
        citations = [Citation(**c) for c in cached["citations"]]
        session = await chat_session_service.save_exchange(
            db, user, data.session_id, data.question,
            cached["answer"], citations, cached["no_answer"], data.knowledge_base,
        )
        msg_id = await chat_session_service.last_assistant_message_id(db, session.id)
        yield "delta", cached["answer"]
        yield "done", {
            "answer": cached["answer"],
            "no_answer": cached["no_answer"],
            "citations": [c.model_dump() for c in citations],
            "session_id": session.id,
            "message_id": msg_id,
        }
        await _save_trace(
            db, rid=rid, user=user, data=data, cache_hit=True, retrieved=0,
            no_answer=cached["no_answer"], latency_ms=round((time.perf_counter() - t0) * 1000),
            timing=timing, answer=cached["answer"],
        )
        return
    metrics.record_question(user.department, False)

    t = time.perf_counter()
    chunks, query = await _retrieve_and_rerank(db, user, data)
    timing["retrieve_ms"] = round((time.perf_counter() - t) * 1000)

    if not chunks:
        session = await chat_session_service.save_exchange(
            db, user, data.session_id, data.question, NO_DOC_ANSWER, [], True,
            data.knowledge_base,
        )
        if not data.history:
            await answer_cache.store(data.question, user.department, data.knowledge_base, NO_DOC_ANSWER, [], True)
        msg_id = await chat_session_service.last_assistant_message_id(db, session.id)
        yield "done", {
            "answer": NO_DOC_ANSWER,
            "no_answer": True,
            "citations": [],
            "session_id": session.id,
            "message_id": msg_id,
        }
        metrics.record_no_answer()
        await _save_trace(
            db, rid=rid, user=user, data=data, cache_hit=False, retrieved=0, no_answer=True,
            latency_ms=round((time.perf_counter() - t0) * 1000), timing=timing,
            answer=NO_DOC_ANSWER, rewritten=_trace_rewritten(query),
        )
        return

    numbered = _fit_context_budget(data.question, chunks, data.history)
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
    metrics.record_llm_call()
    parts: list[str] = []
    t = time.perf_counter()
    try:
        async for delta in llm.generate_stream(data.question, numbered, data.history):
            parts.append(delta)
            yield "delta", delta
    except Exception:
        metrics.record_llm_error()
        raise
    timing["llm_ms"] = round((time.perf_counter() - t) * 1000)

    answer = "".join(parts)
    no_answer = NO_ANSWER_SENTINEL in answer
    citations = _build_citations(numbered, answer)
    # 流式完整回答拿到后回填缓存（相近问题下次秒回，仅单轮）
    if not data.history:
        await answer_cache.store(
            data.question, user.department, data.knowledge_base, answer, citations, no_answer
        )
    # 流式完整回答拿到后才落库，避免回答中断留半个会话
    session = await chat_session_service.save_exchange(
        db, user, data.session_id, data.question, answer, citations, no_answer,
        data.knowledge_base,
    )
    msg_id = await chat_session_service.last_assistant_message_id(db, session.id)
    yield "done", {
        "answer": answer,
        "no_answer": no_answer,
        "citations": [c.model_dump() for c in citations],
        "session_id": session.id,
        "message_id": msg_id,
    }
    if no_answer:
        metrics.record_no_answer()
    tokens_in = estimate_tokens(data.question) + sum(
        estimate_tokens(c["content"]) for c in numbered
    )
    tokens_out = estimate_tokens(answer)
    await _save_trace(
        db, rid=rid, user=user, data=data, cache_hit=False, retrieved=len(numbered),
        no_answer=no_answer, latency_ms=round((time.perf_counter() - t0) * 1000),
        timing=timing, answer=answer, rewritten=_trace_rewritten(query),
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
    metrics.record_latency(time.perf_counter() - t0)
