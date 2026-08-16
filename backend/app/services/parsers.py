"""文档解析：按扩展名把文件转成分页纯文本。

W1 支持 PDF / DOCX / TXT / MD。
- PDF 用 PyMuPDF 逐页提取文本，每页带真实页码；
- 扫描版 PDF（无文本层）在 OCR_BACKEND=rapidocr 时走 RapidOCR 识别；
- 页眉页脚清洗（TEXT_CLEANING=basic）：跨页重复行检测，真页眉只能在「页」结构里识别。
"""
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.cleaner import should_clean

settings = get_settings()


@dataclass
class ParsedPage:
    """一页解析结果。PDF 的 page_no 从 1 开始；DOCX/TXT/MD 无分页概念为 None。"""

    page_no: int | None
    text: str


def parse_document(file_path: str) -> list[ParsedPage]:
    """按扩展名解析文档，返回分页文本。"""
    suffix = _suffix(file_path)
    if suffix == ".pdf":
        return _parse_pdf(file_path)
    if suffix in (".docx", ".doc"):
        return _parse_docx(file_path)
    if suffix in (".txt", ".md"):
        return _parse_text(file_path)
    raise AppError(f"暂不支持的文档格式: {suffix or '未知'}")


def _suffix(file_path: str) -> str:
    from pathlib import Path

    return Path(file_path).suffix.lower()


def _parse_text(file_path: str) -> list[ParsedPage]:
    from pathlib import Path

    return [ParsedPage(page_no=None, text=Path(file_path).read_text(encoding="utf-8", errors="ignore"))]


def _parse_pdf(file_path: str) -> list[ParsedPage]:
    import fitz  # PyMuPDF

    pages: list[ParsedPage] = []
    with fitz.open(file_path) as doc:
        for pno, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            # 扫描版 PDF：文本层为空/极少 -> 判定扫描页，OCR 开启时走识别
            if settings.OCR_BACKEND == "rapidocr" and len(text) < settings.OCR_MIN_TEXT_CHARS:
                text = _ocr_page(page)
            pages.append(ParsedPage(page_no=pno, text=text))
    if should_clean():
        pages = _strip_repeated_page_edges(pages)
    return pages


def _parse_docx(file_path: str) -> list[ParsedPage]:
    from docx import Document

    doc = Document(file_path)
    text = "\n".join(p.text for p in doc.paragraphs)
    return [ParsedPage(page_no=None, text=text)]


# --- OCR（可选依赖，RapidOCR）---

# 引擎单例放 dict（与 answer_cache._kv_holder 同款惯例），避免模块级 global 可变状态
_ocr_holder: dict[str, Any] = {}


def _get_ocr_engine():
    """RapidOCR 单例。实例化很慢（加载模型），只建一次。包缺失时报明确错误。"""
    if "_engine" not in _ocr_holder:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise AppError(
                "OCR_BACKEND=rapidocr 但未安装 rapidocr-onnxruntime，"
                "请先 pip install rapidocr-onnxruntime"
            )
        _ocr_holder["_engine"] = RapidOCR()
    return _ocr_holder["_engine"]


def ocr_image(png_bytes: bytes) -> str:
    """把图片字节交给 RapidOCR，按行拼接识别出的文本。"""
    result, _ = _get_ocr_engine()(png_bytes)
    if not result:
        return ""
    return "\n".join(item[1] for item in result)


def _ocr_page(page) -> str:
    """把 PDF 页渲染成图片再 OCR。dpi 200 兼顾速度与精度。"""
    pix = page.get_pixmap(dpi=200)
    return ocr_image(pix.tobytes("png"))


# --- 页眉页脚清洗（跨页重复行检测）---

_EDGE_SCAN_LINES = 3  # 每页顶/底部最多扫的行数


def _top_lines(page: ParsedPage) -> list[str]:
    return [ln.strip() for ln in page.text.splitlines() if ln.strip()][:_EDGE_SCAN_LINES]


def _bottom_lines(page: ParsedPage) -> list[str]:
    return [ln.strip() for ln in page.text.splitlines() if ln.strip()][-_EDGE_SCAN_LINES:]


def _strip_repeated_page_edges(pages: list[ParsedPage]) -> list[ParsedPage]:
    """删除相邻页顶部/底部重复的行（页眉页脚）。

    页眉页脚的特征是每页重复：第 i 页首行 == 第 i+1 页首行 -> 该行是页眉，
    底部同理。正文不会逐页重复同一行，故不误伤。只删连续两页以上重复的行。
    """
    headers: set[str] = set()
    footers: set[str] = set()
    for prev, cur in pairwise(pages):
        if prev.page_no is None:
            continue
        headers.update(ln for ln in _top_lines(prev) if ln in _top_lines(cur))
        footers.update(ln for ln in _bottom_lines(prev) if ln in _bottom_lines(cur))

    if not headers and not footers:
        return pages
    cleaned: list[ParsedPage] = []
    for p in pages:
        lines = [
            ln
            for ln in p.text.splitlines()
            if ln.strip() not in headers and ln.strip() not in footers
        ]
        cleaned.append(ParsedPage(page_no=p.page_no, text="\n".join(lines)))
    return cleaned
