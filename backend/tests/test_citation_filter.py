"""引文过滤测试：只保留重排分强相关的引文（W6.5.1）。

_build_citations 是纯函数，直接单测即可，不依赖 DB/网络。
规则：带 rerank_score 的切片里，分数 < 最强引文分 * CITATION_MIN_SCORE_RATIO 者剔除。
"""
from app.core.config import get_settings
from app.services.rag_service import _build_citations

RATIO = get_settings().CITATION_MIN_SCORE_RATIO


def _numbered(scores: list[float | None]) -> list[dict]:
    """构造编号后的切片列表，rerank_score 按入参给定（None 表示无分数，如重排关闭）。"""
    return [
        {
            "no": i,
            "chunk_id": i,
            "document_id": 10 + i,
            "document_title": f"文档{i}",
            "content": f"切片{i}的内容",
            "page_no": None,
            "rerank_score": s,
        }
        for i, s in enumerate(scores, start=1)
    ]


def test_weak_citation_dropped():
    numbered = _numbered([0.9, 0.8, 0.3])
    answer = "依据[1]回答，同时参考[2]，也提一下[3]。"
    cits = _build_citations(numbered, answer)
    assert [c.chunk_id for c in cits] == [1, 2]  # 0.3 < 0.9*RATIO 被剔除


def test_single_citation_kept():
    numbered = _numbered([0.6, 0.2])
    cits = _build_citations(numbered, "答案[1]。")
    assert [c.chunk_id for c in cits] == [1]


def test_no_score_keeps_all():
    # 重排关闭时无 rerank_score，无法判断强弱，全部保留（行为与之前一致）
    numbered = _numbered([None, None, None])
    cits = _build_citations(numbered, "引用[1]和[3]。")
    assert [c.chunk_id for c in cits] == [1, 3]


def test_close_scores_all_kept():
    # 都接近最强引文分时不误杀，只有明显弱于最强的才剔除
    numbered = _numbered([0.8, 0.6])
    cits = _build_citations(numbered, "引用[1]和[2]。")
    assert [c.chunk_id for c in cits] == [1, 2]
