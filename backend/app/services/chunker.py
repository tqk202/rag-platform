"""切片器：把长文本切成带重叠、句子边界对齐的小块。

chunk_document 是按文档类型分发的统一入口：
- .md  标题感知切分（章节锚点整段保留，超长章节再切）
- .pdf 以页为界优先，跨页拼接，记录起始页码
- .docx/.txt 通用句子对齐切分（换行/句号即边界，段落不断）

每个 chunk 都对齐到句子边界（。！？；\n 或英文句点+空白），不再硬切句子；
overlap 取块长的 1/5，兼顾上下文连续与索引密度。
"""
import re
from dataclasses import dataclass

from app.core.config import get_settings

settings = get_settings()

HEADING_RE = re.compile(r"^#{1,6}\s+.+$")

# 句子边界字符：中文句号/感叹/问号/分号 + 换行（段落边界）
_SENTENCE_END = "。！？；\n"

# 往回找边界的最远距离：兼顾"对齐到边界"与"避免极端长句撑爆"
_SENTENCE_LOOKBACK = 200


@dataclass
class ChunkPiece:
    """一个切片：内容 + 起始页码（PDF 有，其他格式 None）。"""

    content: str
    page_no: int | None = None


def _sentence_cut(text: str, target: int, n: int) -> int:
    """从 target 往回找最近的句子边界，返回切点；找不到则硬切兜底。"""
    target = min(target, n)
    if target >= n:
        return n
    start = max(target - _SENTENCE_LOOKBACK, 0)
    for i in range(target, start, -1):
        ch = text[i - 1]
        if ch in _SENTENCE_END:
            return i
        # 英文句点需后接空白/行尾，避免把 "U.S.A" 这类缩写切开
        if ch == "." and (i >= n or text[i].isspace()):
            return i
    return target  # 找不到边界，硬切兜底（防死循环）


def _split_sentence_aligned(text: str, chunk_size: int, overlap: int) -> list[str]:
    """把长文本切成 chunk_size 左右、句子边界对齐的块，块间 overlap。"""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size 必须 > 0，overlap 必须 >= 0 且 < chunk_size")
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = _sentence_cut(text, start + chunk_size, n)
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _join_pages(pages: list) -> str:
    """多页文本拼接成全文（页间双换行，页边界是天然段落边界）。"""
    return "\n\n".join(p.text for p in pages if p.text and p.text.strip())


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[ChunkPiece]:
    """通用切分（txt/docx 回退路径）：句子对齐 + overlap。无分页概念。"""
    size = settings.CHUNK_SIZE if chunk_size is None else chunk_size
    ov = size // 5 if overlap is None else overlap
    return [ChunkPiece(content=c) for c in _split_sentence_aligned(text, size, ov)]


def _split_markdown_sections(text: str) -> list[dict]:
    """按标题行把文本切成 [{heading, body}]，标题前的引导内容并入第一段。"""
    sections: list[dict] = []
    heading = ""
    body_lines: list[str] = []
    for line in text.splitlines():
        if HEADING_RE.match(line):
            if heading or body_lines:
                sections.append({"heading": heading, "body": "\n".join(body_lines)})
            heading = line  # 保留整行（含 # 层级）
            body_lines = []
        else:
            body_lines.append(line)
    if heading or body_lines:
        sections.append({"heading": heading, "body": "\n".join(body_lines)})
    return sections


def chunk_markdown(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[ChunkPiece]:
    """Markdown 标题感知切分（无分页概念）。

    标题是章节锚点：整段（标题+正文）不长就整段保留，避免硬切把语义割断；
    超长章节按句子对齐再切，但每片都带标题前缀保持上下文。
    """
    size = settings.CHUNK_SIZE if chunk_size is None else chunk_size
    ov = size // 5 if overlap is None else overlap
    max_section_len = size * 4
    text = text.strip()
    if not text:
        return []

    chunks: list[ChunkPiece] = []
    for sec in _split_markdown_sections(text):
        body = sec["body"].strip()
        full = f"{sec['heading']}\n{body}".strip() if sec["heading"] else body
        if not full:
            continue
        if len(full) <= max_section_len:
            chunks.append(ChunkPiece(content=full))
            continue
        if sec["heading"]:
            # 超长章节：每片带标题前缀保持上下文
            chunks.extend(
                ChunkPiece(content=f"{sec['heading']}\n{piece}".strip())
                for piece in _split_sentence_aligned(body, size, ov)
                if piece
            )
        else:
            chunks.extend(
                ChunkPiece(content=piece) for piece in _split_sentence_aligned(body, size, ov) if piece
            )
    return chunks


def _chunk_md(pages: list, size: int) -> list[ChunkPiece]:
    return chunk_markdown(_join_pages(pages), chunk_size=size)


def _chunk_pdf(pages: list, size: int) -> list[ChunkPiece]:
    """PDF 逐页切分：以页为界（页是自然语义边界），页内句子对齐。

    页码精确到页：每片都归属于产出它的那一页，不会跨页拼接导致页码模糊。
    """
    overlap = size // 5
    pieces: list[ChunkPiece] = []
    for p in pages:
        text = p.text.strip()
        if not text:
            continue
        for piece in _split_sentence_aligned(text, size, overlap):
            pieces.append(ChunkPiece(content=piece, page_no=p.page_no))
    return pieces


def _chunk_generic(pages: list, size: int) -> list[ChunkPiece]:
    """txt/docx 共用：句子对齐 + overlap，无分页。"""
    overlap = size // 5
    return [ChunkPiece(content=c) for c in _split_sentence_aligned(_join_pages(pages), size, overlap)]


def chunk_document(pages: list, suffix: str) -> list[ChunkPiece]:
    """按文档类型分发切分。pages 来自 parsers.parse_document，suffix 带点后缀。"""
    suffix = suffix.lower()
    if suffix == ".md":
        return _chunk_md(pages, settings.CHUNK_SIZE_MD)
    if suffix == ".pdf":
        return _chunk_pdf(pages, settings.CHUNK_SIZE_PDF)
    if suffix in (".docx", ".doc"):
        return _chunk_generic(pages, settings.CHUNK_SIZE_DOCX)
    return _chunk_generic(pages, settings.CHUNK_SIZE_TXT)
