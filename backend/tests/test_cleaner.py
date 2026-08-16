"""保守清洗层单元测试：页眉残留/全角空格/行尾空白/连续空行，且不碰正文。"""

from app.services.cleaner import clean_text, should_clean


def test_removes_page_footer_lines():
    text = "第一章 总则\n第 1 页 共 7 页\n正文内容\n第 2 页，共 7 页\n"
    cleaned = clean_text(text)
    assert "第 1 页 共 7 页" not in cleaned
    assert "第 2 页" not in cleaned
    assert "第一章 总则" in cleaned
    assert "正文内容" in cleaned


def test_removes_english_page_footer_lines():
    text = "Introduction\nPage 1 of 5\nBody text\nPage 2/5\n"
    cleaned = clean_text(text)
    assert "Page 1 of 5" not in cleaned
    assert "Page 2/5" not in cleaned
    assert "Introduction" in cleaned
    assert "Body text" in cleaned


def test_converts_fullwidth_space_to_halfwidth():
    text = "　　　第 1 页 共 8 页　　星辰云驰科技有限公司\n正文"
    cleaned = clean_text(text)
    assert "　" not in cleaned
    assert "正文" in cleaned


def test_strips_trailing_whitespace_per_line():
    text = "正文一  \n正文二\t\n正文三\n"
    cleaned = clean_text(text)
    assert cleaned == "正文一\n正文二\n正文三"


def test_collapses_consecutive_blank_lines():
    text = "第一段\n\n\n\n第二段\n\n\n第三段\n"
    cleaned = clean_text(text)
    assert "\n\n\n" not in cleaned
    assert "第一段\n\n第二段\n\n第三段" == cleaned


def test_empty_and_whitespace_only_text_safe():
    assert clean_text("") == ""
    assert clean_text("\n  \n  \n") == ""


def test_idempotent():
    text = "第 1 页 共 7 页\n正文内容　有全角空格\n"
    once = clean_text(text)
    twice = clean_text(once)
    assert once == twice


def test_does_not_touch_body_words():
    text = "试用期为三个月，最长不超过六个月。\n"
    assert clean_text(text) == "试用期为三个月，最长不超过六个月。"


def test_should_clean_default_none():
    # conftest 不设 TEXT_CLEANING，默认 none -> 不清洗（评测路径不受影响）
    assert should_clean() is False
