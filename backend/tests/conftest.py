"""测试夹具：独立测试库 + 独立向量库，每个用例前重建，避免污染开发数据。"""
import os

# 必须在导入 app 前设置环境变量：pytest 在 backend/ 下运行时 .env 也会被读，
# 环境变量优先级高于 .env，这里强制指向测试专用库。
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_rag.db"
os.environ["VECTOR_URI"] = "data/test_milvus.db"
os.environ["INGESTION_MODE"] = "inline"
os.environ["EMBEDDING_BACKEND"] = "mock"
os.environ["LLM_BACKEND"] = "mock"

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import engine
from app.main import app
from app.models import Base
from app.services.vector_service import COLLECTION_NAME, vector_store


@pytest.fixture(autouse=True)
async def _reset_state():
    # 每个用例前重置 SQLite 表 + Milvus 集合，保证用例互相独立
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    if vector_store.client.has_collection(COLLECTION_NAME):
        vector_store.client.drop_collection(COLLECTION_NAME)
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
