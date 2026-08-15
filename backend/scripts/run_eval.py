"""W4 评测运行器（单配置）。

职责：在独立的评测库（不碰开发数据）里 入库演示文档 → 对黄金评测集逐题
跑检索 + 生成 → 算 4 个指标 → 聚合输出 JSON 报告。

由 ablation.py 以子进程方式逐配置调用；也可单独跑 `python scripts/run_eval.py`。
每个配置跑在独立进程里，配置（chunk 参数 / 重排开关 / 检索模式）从环境变量注入，
保证消融实验"控制变量"干净。

环境变量：
  SEARCH_MODE   hybrid(默认, 混合检索) | vector(纯向量，消融对比用)
  RERANKER_BACKEND  lexical|none（重排开关）
  CHUNK_SIZE / CHUNK_OVERLAP 切片参数（消融 chunk 500 vs 300）
  LLM_BACKEND   mock(默认, 占位数字) | api(真实 LLM 裁判，花 API 费用)
  REPORT_JSON   报告输出路径（不设则写到 eval_reports/ 下）
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# 让 .env 和相对路径（data/、demo_docs/）都从 backend/ 解析
BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

# 必须在 import app 之前设置环境变量（隔离评测库，不污染开发数据）
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/eval_rag.db")
os.environ.setdefault("VECTOR_URI", "data/eval_milvus.db")
os.environ.setdefault("MILVUS_COLLECTION", "rag_chunks_eval")
os.environ.setdefault("INGESTION_MODE", "inline")
os.environ.setdefault("EMBEDDING_BACKEND", "mock")
os.environ.setdefault("SEARCH_MODE", "hybrid")
os.environ.setdefault("DEBUG", "false")  # 评测不需要 SQL 回显
# 评测默认 mock（占位数字），绝不默认烧 API；只有 ablation.py 显式传 LLM_BACKEND=api 才用真实模型。
# 注意：必须放在 import app.* 之前，且用普通赋值兜底（.env 里可能配了 api）。
if not os.getenv("LLM_BACKEND"):
    os.environ["LLM_BACKEND"] = "mock"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eval")

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.document import DocStatus, Document  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import rerank_service, retrieval_service  # noqa: E402
from app.services.sparse_service import get_sparse_index  # noqa: E402
from app.services.evaluator import LLMJudge, evaluate_case  # noqa: E402
from app.services.ingestion_service import compute_content_hash, process_document  # noqa: E402
from app.services.llm_service import NO_ANSWER_SENTINEL, get_llm_provider  # noqa: E402
from app.services.vector_service import COLLECTION_NAME, vector_store  # noqa: E402

settings = get_settings()

DEMO_DOCS = sorted(Path("demo_docs").glob("*.txt"))
GOLDEN_PATH = Path("eval_data/golden_set.json")


def load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def make_label() -> str:
    mode = os.getenv("SEARCH_MODE", "hybrid")
    rerank = os.getenv("RERANKER_BACKEND", "lexical")
    cs = os.getenv("CHUNK_SIZE", str(settings.CHUNK_SIZE))
    llm = os.getenv("LLM_BACKEND", "mock")
    if mode == "vector":
        return f"纯向量-无重排-chunk{cs}-{llm}"
    return f"混合+{rerank}-chunk{cs}-{llm}"


async def reset_state() -> None:
    """重建评测库：SQLite 表 + Milvus 集合 + 稀疏索引都清空重来。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    if vector_store.client.has_collection(COLLECTION_NAME):
        vector_store.client.drop_collection(COLLECTION_NAME)
    async with AsyncSessionLocal() as db:
        await get_sparse_index().drop(db)  # FTS 表不在 ORM 元数据里，需显式清（防多进程评测残留）
    logger.info("评测库已重置（SQLite + Milvus 集合 %s + 稀疏索引）", COLLECTION_NAME)


async def ingest_demo_docs() -> None:
    """复用生产管线入库 5 份演示文档（parse -> chunk -> embed -> insert）。"""
    async with AsyncSessionLocal() as db:
        user = User(username="eval_admin", hashed_password="x", department="hr")
        db.add(user)
        await db.flush()

        for path in DEMO_DOCS:
            raw = path.read_bytes()
            doc = Document(
                title=path.stem,
                file_name=path.name,
                file_path=str(path),
                content_hash=compute_content_hash(raw),
                status=DocStatus.pending,
                department="hr",
                owner_id=user.id,
            )
            db.add(doc)
            await db.flush()
            await process_document(db, doc.id)
            logger.info("已入库 %s（%s 个切片）", path.name, doc.chunk_count)
    logger.info("演示文档全部入库完成")


async def _fill_titles(chunks: list[dict]) -> list[dict]:
    """纯向量召回不带 document_title，统一补全（一次查询，避免 N+1）。"""
    if not chunks:
        return chunks
    async with AsyncSessionLocal() as db:
        doc_ids = {c["document_id"] for c in chunks}
        rows = (await db.execute(select(Document.id, Document.title).where(Document.id.in_(doc_ids)))).all()
    by_doc = dict(rows)
    for c in chunks:
        c.setdefault("document_title", by_doc.get(c["document_id"], ""))
    return chunks


async def retrieve(question: str) -> list[dict]:
    """按 SEARCH_MODE 召回（+ 重排），返回喂给 LLM 的切片列表。"""
    mode = os.getenv("SEARCH_MODE", "hybrid")
    if mode == "vector":
        # 消融组"纯向量"：直接取向量检索前 N，不重排
        async with AsyncSessionLocal() as db:
            chunks = await retrieval_service.vector_search(
                db, question, "hr", top_k=settings.RERANK_TOP_N
            )
        return await _fill_titles(chunks)

    # 生产链路：召回(宽) -> 重排(精) -> 取前 N
    async with AsyncSessionLocal() as db:
        chunks = await retrieval_service.hybrid_search(
            db, question, "hr", top_k=settings.RERANK_RECALL_K
        )
    reranker = rerank_service.get_reranker_provider()
    if reranker:
        chunks = await reranker.rerank(question, chunks)
        chunks = chunks[: settings.RERANK_TOP_N]
    return chunks


async def run_case(judge: LLMJudge, case: dict) -> dict:
    """单题：检索 -> 生成 -> 指标。"""
    chunks = await retrieve(case["question"])
    contexts = [c["content"] for c in chunks]

    numbered = [{**c, "no": i} for i, c in enumerate(chunks, start=1)]
    llm = get_llm_provider()
    result = await llm.generate(case["question"], numbered)
    answer = result.answer
    no_answer = result.no_answer or NO_ANSWER_SENTINEL in answer

    metrics = await evaluate_case(
        judge, case["question"], answer, no_answer, contexts, case["golden_passage"]
    )
    return {
        "id": case["id"],
        "doc": case["doc"],
        "question": case["question"],
        "answer": answer[:120],
        "retrieved": len(contexts),
        "no_answer": no_answer,
        **metrics,
    }


def aggregate(cases: list[dict]) -> dict:
    keys = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    n = len(cases)
    means = {k: round(sum(c[k] for c in cases) / n, 4) for k in keys}
    means["no_answer_rate"] = round(sum(1 for c in cases if c["no_answer"]) / n, 4)
    means["questions"] = n
    return means


async def main() -> None:
    await reset_state()
    await ingest_demo_docs()

    golden = load_golden()
    judge = LLMJudge()
    try:
        results = [await run_case(judge, case) for case in golden["cases"]]
    finally:
        await judge.aclose()

    agg = aggregate(results)
    report = {
        "label": os.getenv("LABEL", make_label()),
        "config": {
            "SEARCH_MODE": os.getenv("SEARCH_MODE", "hybrid"),
            "RERANKER_BACKEND": os.getenv("RERANKER_BACKEND", "lexical"),
            "CHUNK_SIZE": os.getenv("CHUNK_SIZE", str(settings.CHUNK_SIZE)),
            "CHUNK_OVERLAP": os.getenv("CHUNK_OVERLAP", str(settings.CHUNK_OVERLAP)),
            "LLM_BACKEND": os.getenv("LLM_BACKEND", "mock"),
            "department": golden["meta"]["department"],
        },
        "metrics": agg,
        "per_case": results,
    }

    out = os.getenv("REPORT_JSON") or f"eval_reports/run_{int(time.time())}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== {report['label']} ==")
    print(f"context_precision={agg['context_precision']}  "
          f"context_recall={agg['context_recall']}  "
          f"faithfulness={agg['faithfulness']}  "
          f"answer_relevancy={agg['answer_relevancy']}  "
          f"no_answer_rate={agg['no_answer_rate']}")
    for c in results:
        flag = "NO-ANSWER" if c["no_answer"] else "          "
        print(f"  {c['id']:14} cp={c['context_precision']:.2f} cr={c['context_recall']:.2f} "
              f"fa={c['faithfulness']:.2f} ar={c['answer_relevancy']:.2f} {flag} {c['question'][:24]}")
    print(f"报告已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
