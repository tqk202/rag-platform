"""Alembic 迁移环境（async）：URL 从应用配置注入，元数据指向项目模型。

项目全栈用 async 引擎（sqlite+aiosqlite / postgresql+asyncpg），没有同步驱动，
因此采用 alembic 的 async 模板：在线迁移在 asyncio.run 里跑 async engine。
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# 让 `app.*` 可导入：env.py 在 backend/alembic/ 下，上一级即 backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config

# 日志配置沿用 alembic.ini 的 [loggers]/[handlers]
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 对比的目标：项目全部 ORM 模型聚合的 metadata
target_metadata = Base.metadata

# 数据库 URL 单一来源：跟随应用配置（开发 sqlite / 生产 postgresql），
# 避免在 alembic.ini 里硬编码、也避免 set_main_option 的 % 插值踩坑
DATABASE_URL = get_settings().DATABASE_URL


def include_object(object, name, type_, reflected, compare_to):
    # chunks_fts 稀疏索引表（含 SQLite FTS5 伴生表）由迁移手写 SQL 管理、
    # 运行期 ensure() 惰性兜底，不在 ORM metadata；排除在 autogenerate 对比外，
    # 否则 alembic check 每次都会误报"待删除"
    if type_ == "table" and name and name.startswith("chunks_fts"):
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：用应用配置的 URL 建 async engine，在单个连接里跑迁移。"""
    connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
