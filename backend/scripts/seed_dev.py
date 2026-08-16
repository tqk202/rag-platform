"""种子脚本：重建数据 + 三角色账号 + 重灌演示文档（真实嵌入）。

验收/演示前跑一次：清空当前配置的库（开发=SQLite+Milvus Lite，
生产=PostgreSQL+Milvus standalone），建好 admin / mgr_hr / member_hr
三个已知密码账号（测 W3 权限 UI），再用当前 .env 配置（真实 bge-m3）
灌入 demo_docs 下 5 份演示文档。

用法（在 backend/ 下）：
  .venv/Scripts/python scripts/seed_dev.py

注意：会删除开发库所有数据（仅含演示文档和测试账号，可重建）。
"""
import asyncio
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
# 让 data/、demo_docs/ 从 backend/ 解析（与 run_eval 一致）
import os  # noqa: E402

os.chdir(BACKEND_DIR)

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.document import DocStatus, Document  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.services.ingestion_service import compute_content_hash, process_document  # noqa: E402
from app.services.sparse_service import get_sparse_index  # noqa: E402
from app.services.vector_service import COLLECTION_NAME, vector_store  # noqa: E402

PASSWORD = "123456"

USERS = [
    ("admin", Role.admin, "hr"),
    ("mgr_hr", Role.manager, "hr"),
    ("member_hr", Role.member, "hr"),
]

DEMO_DOCS = sorted(Path("demo_docs").glob("*.md"))


async def main() -> None:
    # 1. 重建表 + 清空 Milvus 集合 + 清稀疏索引
    #    稀疏索引表（chunks_fts）不在 ORM 元数据里，drop_all 不会删——
    #    不显式清会导致二次灌库撞 chunk_id 唯一约束（与 94e2599 评测同源问题）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    if vector_store.client.has_collection(COLLECTION_NAME):
        vector_store.client.drop_collection(COLLECTION_NAME)
    async with AsyncSessionLocal() as db:
        await get_sparse_index().drop(db)
    settings = get_settings()
    db_kind = "PostgreSQL" if settings.DATABASE_URL.startswith("postgres") else "SQLite"
    print(f"数据已重置（{db_kind} 表 + Milvus 集合 + 稀疏索引）")

    # 2. 三角色账号（密码统一 123456）
    async with AsyncSessionLocal() as db:
        users = [User(username=u, hashed_password=hash_password(PASSWORD), role=r, department=d) for u, r, d in USERS]
        db.add_all(users)
        await db.flush()
        mgr_id = {u.username: u.id for u in users}["mgr_hr"]

        # 3. 演示文档走完整管线（parse -> chunk -> 真实嵌入 -> 入库）
        for path in DEMO_DOCS:
            raw = path.read_bytes()
            doc = Document(
                title=path.stem,
                file_name=path.name,
                file_path=str(path),
                content_hash=compute_content_hash(raw),
                status=DocStatus.pending,
                department="hr",
                owner_id=mgr_id,
            )
            db.add(doc)
            await db.flush()
            await process_document(db, doc.id)
            print(f"已灌入 {path.name}（切片 {doc.chunk_count}）")

    # 重建后 alembic_version 表被 drop_all 清掉，stamp 打回当前迁移版本，
    # 否则下次 `alembic upgrade head` 会因表已存在而报错（stamp 只写版本号、不跑 DDL）
    subprocess.run([sys.executable, "-m", "alembic", "stamp", "head"], cwd=BACKEND_DIR, check=True)

    print("\n完成。登录账号（密码均 123456）：")
    for u, r, _ in USERS:
        print(f"  {u}  /  {PASSWORD}  （{r.value}）")


if __name__ == "__main__":
    asyncio.run(main())
