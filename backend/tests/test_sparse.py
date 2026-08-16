"""稀疏检索（倒排索引）测试：召回正确性 / 部门隔离 / 删除与升版同步清理 / 边界输入。

关键词检索从「全表 + 内存 BM25」换成数据库全文检索（SQLite FTS5）后，
核心保证：召回语义不漂移 + 与文档生命周期（删除/升版）同步一致。
"""
import pytest

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import Role, User
from app.services import retrieval_service

PASSWORD = "password123"


async def _seed_user(username: str, department: str, role: Role) -> int:
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            hashed_password=hash_password(PASSWORD),
            department=department,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def _login(client, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _upload(client, token: str, content: str, name: str = "制度.txt"):
    files = {"file": (name, content, "text/plain")}
    return await client.post("/api/v1/documents/upload", headers=_auth(token), files=files)


async def _search(query: str, department: str = "hr", top_k: int = 5) -> list[dict]:
    async with AsyncSessionLocal() as db:
        return await retrieval_service.keyword_search(db, query, department, None, top_k)


@pytest.mark.asyncio
async def test_keyword_recalls_matching_content(client):
    """关键词只召回含该词的切片，且按相关度排序。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天，需提前申请。", "年假制度.txt")
    await _upload(client, token, "报销上限为单次500元。", "报销制度.txt")

    hits = await _search("年假")
    assert hits
    assert all("年假" in h["content"] for h in hits)
    assert not any("报销" in h["content"] for h in hits)

    # 双词查询按 OR 召回：命中任一词都算
    hits = await _search("年假 报销")
    assert any("年假" in h["content"] for h in hits)
    assert any("报销" in h["content"] for h in hits)


@pytest.mark.asyncio
async def test_keyword_department_isolation(client):
    """部门隔离：hr 的文档，其他部门搜不到。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天，需提前申请。")

    assert await _search("年假", department="hr")
    assert await _search("年假", department="finance") == []


@pytest.mark.asyncio
async def test_keyword_delete_removes_from_index(client):
    """删除文档后，稀疏索引不再召回它的内容（三存储一致）。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    r = await _upload(client, token, "报销上限为单次500元。", "报销制度.txt")
    doc_id = r.json()["document_id"]

    assert await _search("报销")

    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert await _search("报销") == []


@pytest.mark.asyncio
async def test_keyword_version_update_cleans_old(client):
    """升版后旧内容从稀疏索引清掉，新内容可召回（不新旧混库）。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。", "年假制度.txt")
    assert await _search("10")

    await _upload(client, token, "员工年假每年15天。", "年假制度.txt")
    assert await _search("15")
    # 用只属于旧内容的精确词验证：升版后旧内容从索引彻底清除
    assert await _search("10") == []


@pytest.mark.asyncio
async def test_keyword_empty_or_no_match(client):
    """空 query / 纯标点 / 完全无命中：返回空，不崩。"""
    await _seed_user("mgr_hr", "hr", Role.manager)
    token = await _login(client, "mgr_hr")
    await _upload(client, token, "员工年假每年10天。")

    assert await _search("   ") == []
    assert await _search("？？？") == []
    assert await _search("完全无关的词语") == []


def test_pg_ts_query_uses_websearch_format():
    """生产 PG 路径：_ts_query 输出 websearch 语法（词间 OR、不加引号）。

    to_tsquery 对「单引号中文词 + OR」报 syntax error，必须用 websearch
    语法生成 '一线' | '城市'（生产踩坑回归测试）。
    """
    from app.services.sparse_service import PostgresTSVIndex

    idx = PostgresTSVIndex()
    assert idx._ts_query("一线 城市 出差") == "一线 OR 城市 OR 出差"
    assert "'" not in idx._ts_query("一线 城市")  # 不输出单引号，避免 to_tsquery 解析 bug
