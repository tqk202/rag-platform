"""LLM 回答语义缓存（W11）：热问题秒回 + 省 LLM 调用。

思路：问句先向量化，在 Milvus `question_cache` 集合里找语义相近的已缓存问句
（余弦相似度 >= 阈值即命中），命中则从 KV 拿完整回答负载（回答 + 引文 + no_answer）。

两个关键设计（面试点）：
1. 权限隔离：缓存键带 department——检索本就按部门过滤，同部门可见文档一致，
   缓存键带上部门就不会把 A 部门的回答泄露给 B 部门。
2. 失效策略：每部门一个「知识库版本号」（KV 计数器），文档增/删/改/重试时 +1；
   缓存负载记录生成时的版本号，查回时版本不一致即 miss。粗粒度但简单可靠，
   配合 TTL 双保险（缓存不会无限膨胀）。

KV 可插拔（redis | memory），沿用 W8 SparseIndex 的思路：生产用 Redis，
测试/无 Redis 环境用内存实现。缓存是优化而非依赖：所有读写都 fail-open，
Redis/Milvus 异常时直接 miss，绝不让缓存拖垮问答主链路。
"""
import hashlib
import json
import logging
import time

from app.core.config import get_settings
from app.schemas.chat import Citation
from app.services.embedding_service import get_embedding_provider
from app.services.vector_service import vector_store

logger = logging.getLogger(__name__)
settings = get_settings()

Q_COLLECTION = settings.ANSWER_CACHE_MILVUS_COLLECTION


class CacheKV:
    """键值存储抽象：回答负载 + 每部门版本号。redis | memory 双实现。"""

    async def get(self, key: str) -> str | None:
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl: int) -> None:
        raise NotImplementedError

    async def incr(self, key: str) -> int:
        raise NotImplementedError

    async def clear(self) -> None:
        raise NotImplementedError


class MemoryCacheKV(CacheKV):
    """测试/无 Redis 环境的内存实现：进程内字典 + 过期时间。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expire: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        exp = self._expire.get(key)
        if exp is not None and exp <= time.monotonic():
            self._data.pop(key, None)
            self._expire.pop(key, None)
            return None
        return self._data.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = value
        self._expire[key] = time.monotonic() + ttl

    async def incr(self, key: str) -> int:
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val

    async def clear(self) -> None:
        self._data.clear()
        self._expire.clear()


class RedisCacheKV(CacheKV):
    """生产实现：Redis。懒导入避免内存模式也拉 redis 依赖。"""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._r.set(key, value, ex=ttl)

    async def incr(self, key: str) -> int:
        return await self._r.incr(key)

    async def clear(self) -> None:
        await self._r.flushdb()


_kv_holder: dict[str, CacheKV] = {}


def _kv_store() -> CacheKV:
    if not _kv_holder:
        _kv_holder["kv"] = _redis_or_memory()
    return _kv_holder["kv"]


def _redis_or_memory() -> CacheKV:
    if settings.ANSWER_CACHE_BACKEND == "redis":
        return RedisCacheKV(settings.REDIS_URL)
    return MemoryCacheKV()


def _cache_key(question: str, department: str) -> str:
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]
    return f"ans:{department}:{digest}"


def _version_key(department: str) -> str:
    return f"kv:{department}"


def _ensure_question_collection() -> None:
    client = vector_store.client
    if client.has_collection(Q_COLLECTION):
        return
    from pymilvus import DataType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False)
    schema.add_field(
        field_name="cache_key", datatype=DataType.VARCHAR, max_length=128, is_primary=True
    )
    schema.add_field(field_name="department", datatype=DataType.VARCHAR, max_length=64)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM)
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=Q_COLLECTION, schema=schema, index_params=index_params
    )


def _embed(question: str) -> list[float]:
    """问句向量化。mock 模式下同一问句永远同一向量（哈希种子），语义退化为精确。"""
    return get_embedding_provider().embed_texts([question])[0]


async def _current_version(department: str) -> int:
    raw = await _kv_store().get(_version_key(department))
    return int(raw or 0)


async def lookup(question: str, department: str) -> dict | None:
    """按问句找已缓存回答；miss 返回 None。任何异常都 fail-open 成 miss。"""
    if not settings.ANSWER_CACHE_ENABLED:
        return None
    try:
        _ensure_question_collection()
        vector_store.client.load_collection(Q_COLLECTION)
        hits = vector_store.client.search(
            collection_name=Q_COLLECTION,
            data=[_embed(question)],
            filter=f'department == "{department}"',
            limit=1,
            output_fields=["cache_key"],
        )[0]
        if not hits or hits[0]["distance"] < settings.ANSWER_CACHE_SIMILARITY_THRESHOLD:
            return None  # 无候选或相似度不足
        key = hits[0]["entity"]["cache_key"]
        payload = await _kv_store().get(key)
        if payload is None:
            # TTL 已过期但 Milvus 还有残影：清掉，避免空命中
            vector_store.client.delete(collection_name=Q_COLLECTION, ids=[key])
            return None
        data = json.loads(payload)
        if data["doc_version"] != await _current_version(department):
            return None  # 文档集已变，旧回答作废
        return data
    except Exception:
        logger.exception("回答缓存查找失败，按 miss 处理")
        return None


async def store(
    question: str,
    department: str,
    answer: str,
    citations: list[Citation],
    no_answer: bool,
) -> None:
    """生成完成后回填缓存：KV 存回答负载，Milvus 存问句向量。"""
    if not settings.ANSWER_CACHE_ENABLED:
        return
    try:
        key = _cache_key(question, department)
        payload = json.dumps(
            {
                "answer": answer,
                "citations": [c.model_dump() for c in citations],
                "no_answer": no_answer,
                "doc_version": await _current_version(department),
            },
            ensure_ascii=False,
        )
        await _kv_store().set(key, payload, settings.ANSWER_CACHE_TTL_SECONDS)
        # 先删后插：同一问句只留一行语义索引
        _ensure_question_collection()
        vector_store.client.load_collection(Q_COLLECTION)
        vector_store.client.delete(collection_name=Q_COLLECTION, ids=[key])
        vector_store.client.insert(
            collection_name=Q_COLLECTION,
            data=[
                {"cache_key": key, "department": department, "vector": _embed(question)}
            ],
        )
    except Exception:
        logger.exception("回答缓存写入失败，跳过缓存")


async def bump_version(department: str) -> None:
    """文档集变更时 +1，旧缓存查回时版本不一致自动 miss。异常不影响主链路。"""
    try:
        await _kv_store().incr(_version_key(department))
    except Exception:
        logger.exception("知识库版本号递增失败，缓存可能短暂过期")


async def reset_cache() -> None:
    """测试用：清空 KV + 问句索引集合，保证用例隔离。"""
    await _kv_store().clear()
    if vector_store.client.has_collection(Q_COLLECTION):
        vector_store.client.drop_collection(Q_COLLECTION)
