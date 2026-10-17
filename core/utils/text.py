import math
import re

#: token 估算公式的非 CJK 系数。前端 `estimateTokens`（`static/js/pluginHost.js`）
#: 与 `calculate_token_count` 必须与此保持一致，否则三处会静默漂移。
NON_CJK_TOKEN_RATIO = 3.5

_CJK_PATTERN = re.compile(r'[\u4e00-\u9fa5]')


def estimate_text_tokens(text) -> int:
    """通用文本 token 估算：`ceil(CJK 数 + 非 CJK 数 / 3.5)`。

    公式与 `calculate_token_count` / 前端 `estimateTokens` **同源**：
    两者都改调本函数，保证「后端通用 / 后端卡片 / 前端」三处永不漂移。

    Args:
        text: 任意文本；`None` 或空文本返回 0。

    Returns:
        估算 token 数（int，向上取整）。
    """
    if text is None:
        return 0

    value = text if isinstance(text, str) else str(text)
    if not value:
        return 0

    cjk_count = len(_CJK_PATTERN.findall(value))
    other_count = len(value) - cjk_count

    return math.ceil(cjk_count + (other_count / NON_CJK_TOKEN_RATIO))


# token计算
def calculate_token_count(card_data):
    """
    Python 版 Token 估算：
    中文 = 1, 其他 = 1/3.5
    """
    try:
        # 聚合文本
        text = ""
        text += (card_data.get('name') or '')
        text += (card_data.get('description') or '')
        text += (card_data.get('first_mes') or '')
        text += (card_data.get('mes_example') or '')

        # 处理世界书 (兼容 V2/V3)
        cb = card_data.get('character_book')
        entries = []
        if cb:
            if isinstance(cb, list): # V2 数组
                entries = cb
            elif isinstance(cb, dict) and 'entries' in cb: # V3 对象
                entries = cb['entries']

        for e in entries:
            # 默认启用，除非明确 disable
            if e.get('enabled', True):
                text += e.get('content', '')
                keys = e.get('keys', [])
                if isinstance(keys, list):
                    text += "".join(keys)
                else:
                    text += str(keys)

        # 计算：公式统一在 estimate_text_tokens 里，避免两处漂移
        return estimate_text_tokens(text)
    except Exception as e:
        print(f"Token calc error: {e}")
        return 0
