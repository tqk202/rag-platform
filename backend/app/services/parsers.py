"""文档解析：按扩展名把文件转成纯文本。

W1 支持 PDF / DOCX / TXT / MD。扫描件 OCR 与表格结构识别留作后续扩展。
"""
from pathlib import Path

from app.core.exceptions import AppError


def parse_document(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(file_path)
    if suffix in (".docx", ".doc"):
        return _parse_docx(file_path)
    if suffix in (".txt", ".md"):
        return _parse_text(file_path)
    raise AppError(f"暂不支持的文档格式: {suffix or '未知'}")


def _parse_text(file_path: str) -> str:
    return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def _parse_pdf(file_path: str) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(file_path) as doc:
        for page in doc:
            parts.append(page.get_text())
    return "\n".join(parts)


def _parse_docx(file_path: str) -> str:
    from docx import Document

    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs)
