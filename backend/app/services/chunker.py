"""切片器：把长文本切成带重叠的小块。

chunk_size / overlap 做成可配置，W4 消融实验时直接改参数对比效果。
P2-2 增加 Markdown 标题感知切分：按标题分段、保留标题上下文，切出的
小块语义更完整（回答时更不容易"只沾边"）。
"""
import re

from app.core.config import get_settings

settings = get_settings()

HEADING_RE = re.compile(r"^#{1,6}\s+.+$")


def chunk_text(
    text: str, chunk_size: int | None = None, overlap: int | None = None
) -> list[str]:
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap if overlap is not None else settings.CHUNK_OVERLAP
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size 必须 > 0，overlap 必须 >= 0 且 < chunk_size")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


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


def chunk_markdown(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    max_section_len: int | None = None,
) -> list[str]:
    """Markdown 标题感知切分（P2-2）。

    标题本身是章节锚点：整段（标题+正文）不长就整段保留，避免硬切把
    语义割断；长段落按基础切片再切，但每片都带标题前缀保持上下文。
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap if overlap is not None else settings.CHUNK_OVERLAP
    max_section_len = max_section_len or chunk_size * 4
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    for sec in _split_markdown_sections(text):
        body = sec["body"].strip()
        full = f"{sec['heading']}\n{body}".strip() if sec["heading"] else body
        if not full:
            continue
        if len(full) <= max_section_len:
            chunks.append(full)
            continue
        if sec["heading"]:
            # 超长章节：每片带标题前缀保持上下文；strip 只清接缝，不动切片内容
            chunks.extend(
                (f"{sec['heading']}\n{piece}").strip()
                for piece in chunk_text(body, chunk_size, overlap)
                if piece.strip()
            )
        else:
            chunks.extend(chunk_text(body, chunk_size, overlap))
    return chunks
