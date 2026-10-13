"""搜索文本工具：CJK 切分与 FTS5 查询构造。"""

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.utils.search_text import (
    build_fts_match_query,
    escape_like,
    has_search_tokens,
    split_cjk_for_index,
)


# --- split_cjk_for_index ---------------------------------------------------


def test_split_cjk_separates_every_han_character():
    assert split_cjk_for_index('血族') == '血 族'
    assert split_cjk_for_index('血族王子') == '血 族 王 子'


def test_split_cjk_keeps_ascii_words_intact():
    """ASCII 词必须保持完整，否则 Dragon 会被切成单字母而永远搜不到。"""
    assert split_cjk_for_index('Dragon Age') == 'Dragon Age'
    assert split_cjk_for_index('book7.json') == 'book7.json'


def test_split_cjk_mixes_scripts_without_gluing_them():
    assert split_cjk_for_index('血族 Dragon 设定') == '血 族 Dragon 设 定'


def test_split_cjk_collapses_whitespace():
    """空白折叠不影响 FTS5 短语相邻性，但让内容可读且更省空间。"""
    assert split_cjk_for_index('血族   设定') == '血 族 设 定'
    assert '  ' not in split_cjk_for_index('血族\n\n设定')


def test_split_cjk_handles_empty_and_none():
    assert split_cjk_for_index('') == ''
    assert split_cjk_for_index(None) == ''


def test_split_cjk_covers_kana_and_hangul():
    assert split_cjk_for_index('テスト') == 'テ ス ト'
    assert split_cjk_for_index('한글') == '한 글'


# --- build_fts_match_query -------------------------------------------------


def test_match_query_turns_han_run_into_adjacency_phrase():
    """汉字连续段变成短语，相邻 token 匹配即子串匹配。"""
    assert build_fts_match_query('血族') == '"血 族"'
    assert build_fts_match_query('血脉觉醒') == '"血 脉 觉 醒"'


def test_match_query_quotes_ascii_words():
    assert build_fts_match_query('Dragon') == '"Dragon"'
    assert build_fts_match_query('book7') == '"book7"'


def test_match_query_survives_fts5_syntax_characters():
    """``.`` / ``-`` / ``:`` 在裸输入下会触发 fts5 语法错误或 no such column。"""
    assert build_fts_match_query('book7.json') == '"book7" "json"'
    assert build_fts_match_query('a-b') == '"a" "b"'
    assert build_fts_match_query('a:b') == '"a" "b"'
    assert build_fts_match_query('血族 (x)') == '"血 族" "x"'


def test_match_query_preserves_boolean_operators():
    """``dragon AND hero`` 是用户的布尔意图，不能被当成字面词。"""
    assert build_fts_match_query('dragon AND hero') == '"dragon" AND "hero"'
    assert build_fts_match_query('dragon OR hero') == '"dragon" OR "hero"'
    assert build_fts_match_query('dragon NOT hero') == '"dragon" NOT "hero"'


def test_match_query_drops_leading_operator_without_left_operand():
    assert build_fts_match_query('AND hero') == '"hero"'
    assert build_fts_match_query('OR') == ''


def test_match_query_returns_empty_for_punctuation_only_input():
    assert build_fts_match_query('...') == ''
    assert build_fts_match_query('!!!') == ''
    assert build_fts_match_query('   ') == ''
    assert build_fts_match_query('') == ''
    assert build_fts_match_query(None) == ''


def test_match_query_splits_very_long_han_runs():
    """超长连续汉字要拆成多个短语，避免生成巨型短语。"""
    query = build_fts_match_query('血' * 80)
    phrases = [part for part in query.split() if part.startswith('"')]
    assert len(phrases) >= 2
    assert all(len(part) <= 36 for part in phrases)


def test_match_query_caps_term_count():
    """粘贴长文本时限制词数，避免查询过慢。"""
    query = build_fts_match_query(' '.join(f'w{index}' for index in range(50)))
    assert query.count('"') // 2 <= 12


def test_has_search_tokens_matches_query_emptiness():
    assert has_search_tokens('血族') is True
    assert has_search_tokens('Dragon') is True
    assert has_search_tokens('...') is False
    assert has_search_tokens('') is False


# --- escape_like -----------------------------------------------------------


def test_escape_like_escapes_wildcards_and_backslash():
    assert escape_like('100%') == '100\\%'
    assert escape_like('a_b') == 'a\\_b'
    assert escape_like('c:\\path') == 'c:\\\\path'


# --- 端到端：切分写入 + 短语查询 -------------------------------------------


def _seed(rows):
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='unicode61')")
    for index, content in enumerate(rows):
        conn.execute(
            'INSERT INTO t(rowid, content) VALUES (?, ?)',
            (index + 1, split_cjk_for_index(content)),
        )
    conn.commit()
    return conn


def _match(conn, needle):
    query = build_fts_match_query(needle)
    if not query:
        return []
    return [
        row[0]
        for row in conn.execute('SELECT rowid FROM t WHERE t MATCH ?', (query,)).fetchall()
    ]


def test_two_character_chinese_substring_matches_split_content():
    """两字中文是最常见的查询长度；trigram 分词器在这里会失效。"""
    conn = _seed(['血族王子 血脉觉醒 家族 lorebook.json 奇幻设定'])
    try:
        assert _match(conn, '血族') == [1]
        assert _match(conn, '血脉') == [1]
        assert _match(conn, '设定') == [1]
        assert _match(conn, '族王') == [1]
    finally:
        conn.close()


def test_chinese_substring_search_does_not_match_unrelated_text():
    conn = _seed(['血族王子 血脉觉醒', '龙族纪元 设定集'])
    try:
        assert _match(conn, '血族') == [1]
        assert _match(conn, '龙族') == [2]
        assert _match(conn, '血脉') == [1]
        assert _match(conn, '龙血') == []
    finally:
        conn.close()


def test_ascii_search_still_works_alongside_chinese():
    conn = _seed(['血族王子 lorebook.json 奇幻设定', 'book7.json 奇幻设定集'])
    try:
        assert _match(conn, 'book7') == [2]
        assert _match(conn, 'lorebook') == [1]
        assert _match(conn, 'Dragon') == []
        # 带标点的输入不再抛异常，而是按词拆分后匹配。
        assert _match(conn, 'book7.json') == [2]
        assert _match(conn, 'a-b') == []
    finally:
        conn.close()


def test_mixed_script_query_matches_both_parts():
    conn = _seed(['血族纪元 Dragon Age 设定集'])
    try:
        assert _match(conn, '血族 Dragon') == [1]
        assert _match(conn, '血族 dragon') == [1]
        assert _match(conn, '血族 Missing') == []
    finally:
        conn.close()


def test_punctuation_only_query_never_reaches_fts():
    """纯标点输入没有可搜索的词，调用方据此返回空集而不是全部结果。"""
    conn = _seed(['血族王子'])
    try:
        assert build_fts_match_query('...') == ''
        assert _match(conn, '...') == []
    finally:
        conn.close()


def test_reserved_words_are_quoted_and_do_not_error():
    conn = _seed(['AND OR NOT NEAR 设定集'])
    try:
        # 单独出现时它们是运算符而非词，因此不会命中。
        assert _match(conn, 'AND') == []
        # 作为词的一部分则正常命中。
        assert _match(conn, '设定') == [1]
    finally:
        conn.close()
