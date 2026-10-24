import logging
import math
import re

logger = logging.getLogger(__name__)

#: token 估算公式的非 CJK 系数。前端 `estimateTokens`（`static/js/pluginHost.js`）
#: 与 `calculate_token_count` 必须与此保持一致，否则三处会静默漂移。
NON_CJK_TOKEN_RATIO = 3.5

_CJK_PATTERN = re.compile(r'[\u4e00-\u9fa5]')

#: 参与卡片级 token 估算的正文字段。顺序沿用历史实现，保证结果逐字节一致。
_CARD_TEXT_FIELDS = ('name', 'description', 'first_mes', 'mes_example')


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


def iter_worldbook_entries(card_data):
    """按 V2/V3 兼容方式取出内嵌世界书条目列表。

    `character_book` 可能是 V2 的数组，也可能是 V3 的对象；V3 对象的 `entries`
    存在两种写法：**数组**（角色卡规范）和**以 uid 为键的字典**（SillyTavern
    世界书文件的写法，第三方工具导出内嵌书时会出现）。字典形态必须先转成
    值列表，否则逐条读取会抛异常，整张卡的 token 估算被吞成 0。
    """
    if not isinstance(card_data, dict):
        return []

    book = card_data.get('character_book')
    entries = []
    if isinstance(book, list):
        entries = book
    elif isinstance(book, dict):
        entries = book.get('entries') or []
        if isinstance(entries, dict):
            entries = list(entries.values())

    return [entry for entry in entries if isinstance(entry, dict)]


def _entry_text(entry):
    """条目参与 token 估算的文本：内容 + 触发关键词。"""
    text = str(entry.get('content') or '')
    keys = entry.get('keys')
    if isinstance(keys, list):
        text += ''.join(str(key) for key in keys)
    elif keys is not None:
        text += str(keys)
    return text


def _aggregate_card_text(card_data, *, include_disabled):
    text = ''
    for field in _CARD_TEXT_FIELDS:
        text += str(card_data.get(field) or '')

    for entry in iter_worldbook_entries(card_data):
        # 只统计启用条目时沿用历史判定：`enabled` 为假值即视为关闭（不看 `disable`）。
        if not include_disabled and not entry.get('enabled', True):
            continue
        text += _entry_text(entry)

    return estimate_text_tokens(text)


# token计算
def calculate_token_count(card_data):
    """
    Python 版 Token 估算（只统计默认启用的世界书条目）：
    中文 = 1, 其他 = 1/3.5
    """
    try:
        return _aggregate_card_text(card_data, include_disabled=False)
    except Exception as exc:  # noqa: BLE001 - 估算失败不应中断扫描或规则评估
        logger.warning('Token calc error: %s', exc)
        return 0


def calculate_all_worldbook_token_count(card_data):
    """Python 版 Token 估算（世界书条目全部计入，包含未启用条目）。

    与 `calculate_token_count` 的唯一区别是世界书条目不做启用过滤；卡片级
    正文字段与估算公式完全一致，因此两个数字可以直接比较。
    """
    try:
        return _aggregate_card_text(card_data, include_disabled=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning('All-worldbook token calc error: %s', exc)
        return 0
