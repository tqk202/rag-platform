"""保守文本清洗层：入库前去掉影响检索的"机械噪音"，不碰正文文字。

定位（区别于评测脏文档）：W4 评测集故意保留页眉页脚/全角空格等脏数据来验证
检索抗噪能力；清洗层是另一条可选链路——TEXT_CLEANING=basic 时先清洗再入库，
适合"脏数据已知、想干净入库"的场景。默认 none 不启用，评测基准不漂移。

保守原则：只处理可安全判定的格式噪音，不做错别字/OCR 纠错（误伤风险高，
且与"检索阶段抗噪"定位重叠）。
"""
import re

from app.core.config import get_settings

settings = get_settings()

# 页眉页脚残留：如「第 1 页 共 7 页」「第 3 页，共 12 页」独占一行
PAGE_FOOTER_RE = re.compile(r"^\s*第\s*\d+\s*页[，,、]?\s*共\s*\d+\s*页.*$", re.MULTILINE)
# 英文页码残留：Page 1 of 5 / Page 1/5 / Page 5 独占一行（PDF 导出常见页脚）
PAGE_FOOTER_EN_RE = re.compile(r"^\s*page\s*\d+\s*(of|/|-)\s*\d+\s*$", re.MULTILINE | re.IGNORECASE)

# 连续空行（含纯空白行）压成单个空行
BLANK_LINES_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+")

FULL_WIDTH_SPACE = "　"  # 全角空格（日文/中文排版常用来对齐，检索时是噪音）


def clean_text(text: str) -> str:
    """basic 清洗：删页眉页脚残留 -> 全角空格转半角 -> 去行尾空白 -> 合并连续空行。

    全部规则都只改"格式"，不改正文文字，重复调用结果不变（幂等）。
    """
    text = PAGE_FOOTER_RE.sub("", text)
    text = PAGE_FOOTER_EN_RE.sub("", text)
    text = text.replace(FULL_WIDTH_SPACE, " ")
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def should_clean() -> bool:
    """按配置判断是否启用清洗。"""
    return settings.TEXT_CLEANING == "basic"
