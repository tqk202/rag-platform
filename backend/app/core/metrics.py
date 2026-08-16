"""Prometheus 指标（fail-open）：HTTP 层指标由 instrumentator 负责，这里集中定义业务指标。

依赖 prometheus_client（由 prometheus-fastapi-instrumentator 带入）。缺依赖时
全部退化为 no-op，绝不影响问答主链路——指标是观测不是依赖。
"""
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover - 依赖缺失兜底
    Counter = None
    Histogram = None


class _NoopMetric:
    def labels(self, *_a, **_k):
        return self

    def inc(self, _amount: float = 1) -> None:
        pass

    def observe(self, _value: float) -> None:
        pass


def _counter(name: str, doc: str, labelnames: tuple[str, ...] = ()):
    if Counter is None:
        return _NoopMetric()
    return Counter(name, doc, labelnames)


def _histogram(name: str, doc: str):
    if Histogram is None:
        return _NoopMetric()
    return Histogram(name, doc, buckets=[0.1, 0.3, 1, 3, 10, 30, 60])

# fmt: off
_questions = _counter("rag_questions_total", "RAG 问答请求数", ("department", "cache_hit"))
_llm_calls = _counter("rag_llm_calls_total", "LLM 调用次数")
_llm_errors = _counter("rag_llm_errors_total", "LLM 调用失败次数")
_cache_hits = _counter("rag_cache_hits_total", "回答缓存命中次数")
_cache_misses = _counter("rag_cache_misses_total", "回答缓存未命中次数")
_no_answer = _counter("rag_no_answer_total", "拒答次数")
_latency = _histogram("rag_latency_seconds", "问答端到端耗时(秒)")
# fmt: on


def record_question(department: str, cache_hit: bool) -> None:
    _questions.labels(department, "hit" if cache_hit else "miss").inc()


def record_llm_call() -> None:
    _llm_calls.inc()


def record_llm_error() -> None:
    _llm_errors.inc()


def record_cache_hit() -> None:
    _cache_hits.inc()


def record_cache_miss() -> None:
    _cache_misses.inc()


def record_no_answer() -> None:
    _no_answer.inc()


def record_latency(seconds: float) -> None:
    _latency.observe(seconds)
