"""测试夹具：独立测试库 + 独立向量库，每个用例前重建，避免污染开发数据。"""
import os

# 必须在导入 app 前设置环境变量：pytest 在 backend/ 下运行时 .env 也会被读，
# 环境变量优先级高于 .env，这里强制指向测试专用库。
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_rag.db"
os.environ["VECTOR_URI"] = "data/test_milvus.db"
os.environ["INGESTION_MODE"] = "inline"
os.environ["EMBEDDING_BACKEND"] = "mock"
os.environ["LLM_BACKEND"] = "mock"
os.environ["RERANKER_BACKEND"] = "lexical"  # 测试固定离线词法重排，避免 .env 的 api 烧真实 rerank
os.environ["ANSWER_CACHE_BACKEND"] = "memory"  # 测试不依赖 Redis，用内存 KV
os.environ["OCR_BACKEND"] = "none"  # 测试不跑真实 OCR，扫描页行为用 monkeypatch 验证

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.token_blacklist import reset_blacklist
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models import Base
from app.services import answer_cache
from app.services.sparse_service import get_sparse_index
from app.services.vector_service import COLLECTION_NAME, vector_store


@pytest.fixture(autouse=True)
async def _reset_state():
    # 每个用例前重置 SQLite 表 + Milvus 集合 + 稀疏索引，保证用例互相独立
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    if vector_store.client.has_collection(COLLECTION_NAME):
        vector_store.client.drop_collection(COLLECTION_NAME)
    async with AsyncSessionLocal() as db:
        await get_sparse_index().drop(db)  # FTS 表不在 ORM 元数据里，需显式清
    await answer_cache.reset_cache()  # W11: 清 KV + 问句索引，避免缓存跨用例泄漏
    await reset_blacklist()  # P1-3: 清令牌黑名单，避免跨用例泄漏
    from app.api.v1.auth import reset_login_limiter

    reset_login_limiter()  # P1-3: 清登录限流桶（测试共用 IP，会跨用例累积）
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
