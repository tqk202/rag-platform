"""OCR + 页码落地测试：扫描页触发、页码透传、页眉页脚清洗。

用 monkeypatch 替换 OCR 实现，不真跑 RapidOCR（CI 慢且没必要）。
"""
from app.services import parsers


def _make_pdf(tmp_path, name="scan.pdf", pages=None):
    """用 PyMuPDF 生成测试 PDF。pages 为每页文本行列表；缺省 = 第一页有字、第二页空白（扫描页）。"""
    import fitz

    doc = fitz.open()
    for page_texts in pages or [["第一章 概述：普通文本页。"], []]:
        page = doc.new_page()
        for i, text in enumerate(page_texts):
            # china-s = 内置简体中文字体；默认 helv 不支持中文，会渲染丢失
            page.insert_text((72, 72 + i * 20), text, fontname="china-s")  # 不同 y 避免行重叠
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return str(path)


def test_scan_page_triggers_ocr(monkeypatch, tmp_path):
    """OCR 开启时，无文本层页走 ocr_image，页码保持真实页码。"""
    path = _make_pdf(tmp_path)
    monkeypatch.setattr(parsers.settings, "OCR_BACKEND", "rapidocr")
    calls: list = []

    def fake_ocr(png_bytes: bytes) -> str:
        calls.append(png_bytes)
        return "扫描页识别出的文字"

    monkeypatch.setattr(parsers, "ocr_image", fake_ocr)
    parsed = parsers.parse_document(path)
    assert parsed[0].text.startswith("第一章")
    assert parsed[1].page_no == 2
    assert parsed[1].text == "扫描页识别出的文字"
    assert len(calls) == 1  # 只有空白页触发 OCR


def test_scan_page_without_ocr_keeps_original(monkeypatch, tmp_path):
    """OCR 关闭时扫描页保持提取到的空文本，不崩。"""
    path = _make_pdf(tmp_path)
    monkeypatch.setattr(parsers.settings, "OCR_BACKEND", "none")
    parsed = parsers.parse_document(path)
    assert parsed[1].page_no == 2
    assert parsed[1].text.strip() == ""


def test_page_headers_stripped_when_cleaning(monkeypatch, tmp_path):
    """清洗开启时，跨页重复的页眉行被删，每页不同的正文保留。"""
    path = _make_pdf(
        tmp_path,
        pages=[["机密文件", "第一章 正文内容。"], ["机密文件", "第二章 正文内容。"]],
    )
    monkeypatch.setattr(parsers.settings, "TEXT_CLEANING", "basic")
    parsed = parsers.parse_document(path)
    assert len(parsed) == 2
    for p in parsed:
        assert "机密文件" not in p.text
        assert "正文内容" in p.text


def test_parse_text_single_page_no_pagination(tmp_path):
    """txt 无分页概念：单页 page_no=None。"""
    f = tmp_path / "a.txt"
    f.write_text("纯文本内容。", encoding="utf-8")
    parsed = parsers.parse_document(str(f))
    assert len(parsed) == 1
    assert parsed[0].page_no is None
    assert "纯文本" in parsed[0].text
