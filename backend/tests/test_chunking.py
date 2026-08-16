"""切片升级测试：按文档类型分发 + 句子边界对齐 + 页码透传 + Markdown 标题感知。"""
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.user import Role, User
from app.services.chunker import ChunkPiece, chunk_document, chunk_markdown, chunk_text
from app.services.parsers import ParsedPage

PASSWORD = "password123"


def _page(text: str, page_no: int | None = None) -> ParsedPage:
    return ParsedPage(page_no=page_no, text=text)


# --- 按文档类型分发 ---


def test_md_keeps_section_boundaries():
    """md 标题感知：每个标题小节整块保留，标题是章节锚点不被硬切。"""
    pages = [
        _page(
            "## 年假制度\n员工年假每年10天，需提前申请。\n\n"
            "## 报销制度\n费用报销必须附发票，餐费每人每天上限50元。"
        )
    ]
    pieces = chunk_document(pages, ".md")
    assert len(pieces) == 2
    assert "## 年假制度" in pieces[0].content
    assert "年假" in pieces[0].content and "报销" not in pieces[0].content
    assert "## 报销制度" in pieces[1].content
    assert all(p.page_no is None for p in pieces)  # md 无分页概念


def test_txt_cuts_only_at_sentence_boundary():
    """txt 句子对齐：绝不把句子拦腰切断，所有切块以句号结尾。"""
    sentence = "员工年假每年可以休假十天，需要提前向直属上级申请获得批准。"
    pieces = chunk_document([_page(sentence * 40)], ".txt")
    assert len(pieces) > 1
    for p in pieces:
        assert p.content.endswith("。"), p.content[-10:]


def test_pdf_chunks_carry_real_page_no():
    """pdf 以页为界：每片归属产出它的页，页码精确到页。"""
    pages = [_page("第一页内容" * 60, 1), _page("第二页内容很长" * 120, 2)]
    pieces = chunk_document(pages, ".pdf")
    assert len(pieces) > 1
    # 页 1 文本不足一块 -> 整页一块；页 2 超长 -> 多块，overlap 起点可能在词中间
    assert pieces[0].page_no == 1 and "第一页" in pieces[0].content
    assert all(p.page_no == 2 and "第二页" in p.content for p in pieces[1:])


def test_md_long_section_keeps_heading_prefix():
    """md 超长章节按句子对齐再切，但每片都带标题前缀保持上下文。"""
    pages = [_page("## 报销细则\n" + "费用报销必须附发票，超过额度需审批。" * 300)]
    pieces = chunk_document(pages, ".md")
    assert len(pieces) > 1
    assert all(p.content.startswith("## 报销细则") for p in pieces)


def test_chunk_text_returns_pieces_with_overlap():
    """chunk_text 返回 ChunkPiece，overlap 生效（下一块开头与上一块结尾重叠）。"""
    sentence = "员工年假每年可以休假十天。"
    text = sentence * 60
    pieces = chunk_text(text, chunk_size=200, overlap=30)
    assert isinstance(pieces[0], ChunkPiece)
    assert pieces[1].content.startswith(pieces[0].content[-30:])  # 有效重叠 30 字符


# --- 兼容旧接口（chunk_markdown 返回 ChunkPiece） ---


def test_markdown_long_section_split_with_heading_prefix():
    """旧接口兼容：超长章节按基础切片再切，每片带标题前缀。"""
    text = "## 报销细则\n" + "费用报销必须附发票，餐费每人每天上限50元。" * 60
    chunks = chunk_markdown(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert all(c.content.startswith("## 报销细则") for c in chunks)


def test_markdown_without_headings_falls_back():
    """无标题的纯文本退化为普通切分（内容一致）。"""
    text = "员工年假每年10天。\n" * 50
    assert [c.content for c in chunk_markdown(text, 100, 10)] == [
        c.content for c in chunk_text(text, 100, 10)
    ]


def test_chunk_size_validation():
    """非法参数：chunk_size<=0 或 overlap>=chunk_size 报错。"""
    with pytest.raises(ValueError):
        chunk_text("内容", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text("内容", chunk_size=100, overlap=100)


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
