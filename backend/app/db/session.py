"""异步数据库会话：SQLAlchemy 2.0 async + asyncpg。

连接池用 NullPool：Celery worker 每个任务 asyncio.run 新建事件循环，
默认连接池会被多个循环共享导致 "Future attached to a different loop"。
每次会话独立建连/释放，彻底规避跨循环复用（本项目规模下建连开销可忽略）。
"""
from sqlalchemy import pool as sa_pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    poolclass=sa_pool.NullPool,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
