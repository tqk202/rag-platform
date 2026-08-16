"""稀疏检索：关键词召回从「全表扫描 + 内存 BM25」换成数据库倒排索引。

为什么换（面试点）：原实现 select(Chunk) 全量拉进内存再逐条算分（O(N)），
文档量一上去线性劣化。倒排索引（Inverted Index）走索引 O(log N)，
是生产级检索的地基。

双实现（开发/生产代码零改动，与项目「配置分离」原则一致）：
- SQLite（开发/测试/评测）：FTS5 虚拟表，自带 bm25() 排名函数
- PostgreSQL（生产）：chunks_fts 表 + tsvector 表达式索引（GIN），ts_rank() 排序

中文分词：PG/FTS5 默认都不切中文。统一在应用层用 jieba 分词、空格拼接后
入索引，查询同样处理——与旧 BM25 的切词语义一致，召回不漂移。
"""
import logging

import jieba
from sqlalchemy import bindparam, text

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FTS_TABLE = "chunks_fts"


def _join_tokens(text: str) -> str:
    """jieba 分词 -> 空格拼接。过滤纯标点/空白，避免破坏全文检索查询语法。"""
    return " ".join(
        t.strip() for t in jieba.lcut(text) if t.strip() and t.strip().isalnum()
    )


class SparseIndex:
    """稀疏索引抽象。add/remove 由文档管线调用，search 供检索服务使用。"""

    def __init__(self) -> None:
        # 进程内只建一次表：容器重建 = 新进程，标志自动重置；drop() 显式复位（测试）
        self._ensured = False

    async def ensure(self, db) -> None:
        raise NotImplementedError

    async def add(
        self, db, chunk_id: int, department: str, knowledge_base: str | None, content: str
    ) -> None:
        raise NotImplementedError

    async def remove(self, db, chunk_ids: list[int]) -> None:
        raise NotImplementedError

    async def search(
        self,
        db,
        query: str,
        department: str,
        knowledge_base: str | None,
        top_k: int,
    ) -> list[dict]:
        """返回 [{chunk_id, score}]，按相关度降序。score 越大越相关。"""
        raise NotImplementedError

    async def drop(self, db) -> None:
        """清空索引（测试重建用）。"""
        raise NotImplementedError


class SQLiteFTS5Index(SparseIndex):
    """开发/测试用：FTS5 虚拟表。bm25() 分越小越相关，取负后越大越相关。"""

    async def ensure(self, db) -> None:
        if self._ensured:
            return
        await db.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
                "chunk_id UNINDEXED, department UNINDEXED, knowledge_base UNINDEXED, "
                "tokens, tokenize='unicode61')"
            )
        )
        self._ensured = True

    def _match_query(self, tokens: str) -> str:
        # FTS5 查询语法：双引号括词避免保留字（OR/AND/NOT）冲突，词间 OR 召回广
        return " OR ".join(f'"{t}"' for t in tokens.split())

    async def add(
        self, db, chunk_id: int, department: str, knowledge_base: str | None, content: str
    ) -> None:
        await self.ensure(db)
        await db.execute(
            text(
                f"INSERT INTO {FTS_TABLE} (chunk_id, department, knowledge_base, tokens) "
                "VALUES (:cid, :dept, :kb, :tokens)"
            ),
            {
                "cid": chunk_id,
                "dept": department,
                "kb": knowledge_base or "",
                "tokens": _join_tokens(content),
            },
        )

    async def remove(self, db, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        stmt = (
            text(f"DELETE FROM {FTS_TABLE} WHERE chunk_id IN :ids")
            .bindparams(bindparam("ids", expanding=True))
        )
        await db.execute(stmt, {"ids": chunk_ids})

    async def search(
        self, db, query: str, department: str, knowledge_base: str | None, top_k: int
    ) -> list[dict]:
        await self.ensure(db)
        tokens = _join_tokens(query)
        if not tokens:
            return []
        params: dict = {"q": self._match_query(tokens), "dept": department, "limit": top_k}
        kb_filter = ""
        if knowledge_base:
            kb_filter = " AND knowledge_base = :kb"
            params["kb"] = knowledge_base
        rows = (
            await db.execute(
                text(
                    f"SELECT chunk_id, -bm25({FTS_TABLE}) AS score "
                    f"FROM {FTS_TABLE} "
                    f"WHERE {FTS_TABLE} MATCH :q AND department = :dept{kb_filter} "
                    f"ORDER BY score DESC LIMIT :limit"
                ),
                params,
            )
        ).all()
        return [{"chunk_id": r[0], "score": float(r[1])} for r in rows]

    async def drop(self, db) -> None:
        await db.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        self._ensured = False
        await db.commit()


class PostgresTSVIndex(SparseIndex):
    """生产用：chunks_fts 表 + tsvector GIN 表达式索引。ts_rank() 越大越相关。"""

    async def ensure(self, db) -> None:
        if self._ensured:
            return
        await db.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {FTS_TABLE} ("
                "chunk_id BIGINT PRIMARY KEY, "
                "department TEXT NOT NULL, "
                "knowledge_base TEXT NOT NULL DEFAULT '', "
                "tokens TEXT NOT NULL)"
            )
        )
        await db.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_chunks_fts_gin ON {FTS_TABLE} "
                "USING gin (to_tsvector('simple', tokens))"
            )
        )
        self._ensured = True

    def _ts_query(self, tokens: str) -> str:
        # websearch_to_tsquery 语法：对输入更宽容。
        # 注意不能用 to_tsquery + 单引号括中文词：'一线' OR '城市' 在 PG 会报
        # syntax error（中文词经 simple 配置解析后组合 OR 触发解析 bug），
        # 实测 websearch_to_tsquery('simple', '一线 OR 城市') 正确生成 '一线' | '城市'。
        return tokens.replace(" ", " OR ")

    async def add(
        self, db, chunk_id: int, department: str, knowledge_base: str | None, content: str
    ) -> None:
        await self.ensure(db)
        await db.execute(
            text(
                f"INSERT INTO {FTS_TABLE} (chunk_id, department, knowledge_base, tokens) "
                "VALUES (:cid, :dept, :kb, :tokens)"
            ),
            {
                "cid": chunk_id,
                "dept": department,
                "kb": knowledge_base or "",
                "tokens": _join_tokens(content),
            },
        )

    async def remove(self, db, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        stmt = (
            text(f"DELETE FROM {FTS_TABLE} WHERE chunk_id IN :ids")
            .bindparams(bindparam("ids", expanding=True))
        )
        await db.execute(stmt, {"ids": chunk_ids})

    async def search(
        self, db, query: str, department: str, knowledge_base: str | None, top_k: int
    ) -> list[dict]:
        await self.ensure(db)
        tokens = _join_tokens(query)
        if not tokens:
            return []
        q = self._ts_query(tokens)
        params: dict = {"q": q, "dept": department, "limit": top_k}
        kb_filter = ""
        if knowledge_base:
            kb_filter = " AND knowledge_base = :kb"
            params["kb"] = knowledge_base
        rows = (
            await db.execute(
                text(
                    f"SELECT chunk_id, ts_rank(to_tsvector('simple', tokens), "
                    f"websearch_to_tsquery('simple', :q)) AS score FROM {FTS_TABLE} "
                    f"WHERE to_tsvector('simple', tokens) @@ "
                    f"websearch_to_tsquery('simple', :q) AND department = :dept{kb_filter} "
                    f"ORDER BY score DESC LIMIT :limit"
                ),
                params,
            )
        ).all()
        return [{"chunk_id": r[0], "score": float(r[1])} for r in rows]

    async def drop(self, db) -> None:
        await db.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        self._ensured = False
        await db.commit()


def get_sparse_index() -> SparseIndex:
    """按数据库类型返回稀疏索引实现（单例）。"""
    if settings.DATABASE_URL.startswith("sqlite"):
        return SQLiteFTS5Index()
    if settings.DATABASE_URL.startswith("postgresql"):
        return PostgresTSVIndex()
    raise RuntimeError(f"不支持的数据库类型: {settings.DATABASE_URL}")
