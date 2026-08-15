"""P2-2 切片升级测试：Markdown 标题感知切分。"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.user import Role, User
from app.services.chunker import chunk_markdown, chunk_text

PASSWORD = "password123"


def test_markdown_keeps_section_boundaries():
    """每个标题小节整块保留，标题是章节锚点不被硬切。"""
    text = (
        "## 年假制度\n员工年假每年10天，需提前申请。\n\n"
        "## 报销制度\n费用报销必须附发票，餐费每人每天上限50元。"
    )
    chunks = chunk_markdown(text, chunk_size=500, overlap=50)
    assert len(chunks) == 2
    assert "## 年假制度" in chunks[0]
    assert "年假" in chunks[0] and "报销" not in chunks[0]
    assert "## 报销制度" in chunks[1]


def test_markdown_long_section_split_with_heading_prefix():
    """超长章节按基础切片再切，但每片都带标题前缀保持上下文。"""
    text = "## 报销细则\n" + "费用报销必须附发票，餐费每人每天上限50元。" * 60
    chunks = chunk_markdown(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert all(c.startswith("## 报销细则") for c in chunks)


def test_markdown_without_headings_falls_back():
    """无标题的纯文本退化为普通切分。"""
    text = "员工年假每年10天。\n" * 50
    assert chunk_markdown(text, chunk_size=100, overlap=10) == chunk_text(text, 100, 10)


@pytest.mark.asyncio
async def test_md_upload_chunks_keep_heading(client):
    """上传 .md 走标题感知切片：切片内容带章节上下文。"""
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                username="mgr_hr", hashed_password=hash_password(PASSWORD),
                department="hr", role=Role.manager,
            )
        )
        await db.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "mgr_hr", "password": PASSWORD},
    )
    token = resp.json()["access_token"]
    files = {
        "file": (
            "制度.md",
            "## 年假制度\n员工年假每年10天。\n\n## 报销制度\n费用报销必须附发票。",
            "text/markdown",
        )
    }
    up = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )
    assert up.status_code == 200, up.text

    async with AsyncSessionLocal() as db:
        chunks = list(
            (await db.scalars(select(Chunk).where(Chunk.document_id == up.json()["document_id"]))).all()
        )
    assert len(chunks) == 2
    assert all("## " in c.content for c in chunks)
