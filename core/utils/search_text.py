"""搜索共用的文本处理：CJK 切分与 FTS5 查询构造。

FTS5 默认的 ``unicode61`` 分词器不切分中日韩文字，一整段汉字会被当成单个
token，因此中文子串查询永远命中 0 条（例如内容含「血族王子」时搜「血族」无结果）。

这里的做法是：
1. 写入索引前把连续 CJK 逐字用空格分开，让每个汉字成为独立 token；
2. 查询时再把连续汉字还原成 FTS5 短语 ``"血 族"``，相邻 token 匹配即得到子串语义。

ASCII / 数字部分不做任何变换，跨语种内容互不影响。查询侧对所有词加引号，
因此 ``a-b``、``book7.json``、``AND`` 这类输入不再触发 FTS5 语法错误。
"""

import re


# 需要逐字切分的文字范围：假名、CJK 扩展 A、CJK 基本区、CJK 兼容表意文字、韩文音节。
CJK_RANGES = (
    '\u3040-\u30ff',
    '\u3400-\u4dbf',
    '\u4e00-\u9fff',
    '\uf900-\ufaff',
    '\uac00-\ud7af',
)

_CJK_RUN_RE = re.compile(f'[{"".join(CJK_RANGES)}]+')

# 查询侧按顺序扫出的 token：连续 CJK，或连续 ASCII 词（含下划线）。
_QUERY_TOKEN_RE = re.compile(f'([{"".join(CJK_RANGES)}]+)|([0-9A-Za-z_]+)')

# 单个词组最长长度，避免超长连续汉字生成过大的短语。
_MAX_PHRASE_CHARS = 32

# 查询最多保留的词数，防止用户粘贴长文本导致查询过慢。
_MAX_QUERY_TERMS = 12

# FTS5 的布尔运算符。查询里单独出现时按「连接词」处理并丢弃：
# 词与词之间本来就是隐式 AND，所以 `dragon AND hero` 与 `dragon hero` 等价。
# 若把它们当普通词加引号，会变成必须字面命中 "AND" 这个单词，与用户意图相反。
_OPERATOR_KEYWORDS = frozenset({'and', 'or', 'not', 'near'})


def split_cjk_for_index(text) -> str:
    """把连续 CJK 逐字空格分开，其余字符原样保留。

    用于写入 FTS5 内容列，使 ``unicode61`` 能对中文做子串匹配。
    多余空白会折叠成单个空格，便于人工排查与体积控制；FTS5 的短语相邻性
    按 token 位置计算，与空格数量无关，因此折叠不影响匹配结果。
    """
    if not text:
        return ''
    return ' '.join(_CJK_RUN_RE.sub(lambda match: ' ' + ' '.join(match.group(0)) + ' ', str(text)).split())


def build_fts_match_query(text) -> str:
    """把用户输入转成语法合法的 FTS5 查询表达式。

    连续汉字变成短语（相邻 token 匹配 = 子串匹配），ASCII 词原样成词，
    两者都加双引号，因此标点与保留字不再具有语法含义（``a-b``、``book7.json``
    这类输入不会再生出 ``no such column`` / ``syntax error``）。

    识别到的 ``AND`` / ``OR`` / ``NOT`` / ``NEAR`` 作为运算符保留在词之间
    （``dragon AND hero`` 维持原意）；其余词之间是 FTS5 的隐式 AND。
    返回空串表示没有可搜索的词。
    """
    terms = []
    pending_operator = ''
    term_count = 0

    for match in _QUERY_TOKEN_RE.finditer(str(text or '')):
        cjk_run, ascii_word = match.group(1), match.group(2)

        if cjk_run:
            pieces = [
                '"' + ' '.join(cjk_run[start:start + _MAX_PHRASE_CHARS]) + '"'
                for start in range(0, len(cjk_run), _MAX_PHRASE_CHARS)
            ]
        else:
            if ascii_word.lower() in _OPERATOR_KEYWORDS:
                # 运算符需要左操作数；开头的运算符直接忽略。
                if term_count and not pending_operator:
                    pending_operator = ascii_word.upper()
                continue
            pieces = ['"' + ascii_word + '"']

        for piece in pieces:
            if term_count >= _MAX_QUERY_TERMS:
                break
            if pending_operator:
                terms.append(pending_operator)
                pending_operator = ''
            terms.append(piece)
            term_count += 1

        if term_count >= _MAX_QUERY_TERMS:
            break

    return ' '.join(terms)


def has_search_tokens(text) -> bool:
    """输入里是否存在可搜索的词（全是标点时返回 False）。"""
    return bool(build_fts_match_query(text))


def escape_like(text) -> str:
    """转义 LIKE 通配符，供 ``LIKE ? ESCAPE '\\\\'`` 使用。"""
    return str(text or '').replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
