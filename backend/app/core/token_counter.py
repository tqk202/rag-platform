"""token 估算（P1-6）：给 LLM 的上下文做预算控制。

精确计数用 tiktoken 需要按模型下载词表（运行时联网），这里用启发式：
中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token——足以支撑预算决策
（截断到上限内），且零外部依赖、离线可用。
"""
import math

_CJK_START = 0x4E00
_CJK_END = 0x9FFF


def estimate_tokens(text: str) -> int:
    """估算一段文本的 token 数。"""
    cjk = sum(1 for ch in text if _CJK_START <= ord(ch) <= _CJK_END)
    other = len(text) - cjk
    return cjk + math.ceil(other / 4)
