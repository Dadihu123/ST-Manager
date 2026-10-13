"""世界书索引搜索：性能修复、搜索分类与 CJK 全文的集成契约。"""

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services import worldinfo_index_query_service as wi_query
from core.services.index_build_service import (
    collect_worldbook_fulltext,
    split_cjk_for_index,
)


def _seed(db_path, *, entity_type='world_global', name='Dragon Lore', filename='dragon.json',
          display_category='科幻', owner_entity_id='', entity_id=None, fast=None, full=None):
    entity_id = entity_id or f'world::{entity_type}::{filename}'
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready'"
            " WHERE scope = 'worldinfo'"
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path,'
            ' owner_entity_id, name, filename, display_category, physical_category, category_mode,'
            ' favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime,'
            ' thumb_url, source_revision)'
            ' VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                entity_id, entity_type, f'/lorebooks/{filename}', owner_entity_id, name, filename,
                display_category, display_category, 'physical', 0, '', 100.0, 0.0, 0,
                name.lower(), 100.0, '', 'rev',
            ),
        )
        fast_content = fast if fast is not None else f'{name} {filename}'
        full_content = full if full is not None else split_cjk_for_index(fast_content)
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (1,?,?)',
            (entity_id, fast_content),
        )
        conn.execute(
            'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (1,?,?)',
            (entity_id, full_content),
        )
        conn.commit()
    return entity_id


def _query(db_path, **filters):
    filters.setdefault('type', 'all')
    filters.setdefault('page', 1)
    filters.setdefault('page_size', 20)
    filters.setdefault('paginate', True)
    filters.setdefault('db_path', str(db_path))
    return wi_query.query_worldinfo_index(filters)


# --- 搜索分类 ---------------------------------------------------------------


def test_search_field_name_only_matches_world_book_name(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='alpha.json')

    # 名称里有 dragon -> 命中
    assert len(_query(db_path, search='dragon', search_field='name')['items']) == 1
    # 只在文件名里出现 -> 名称分类不命中
    assert _query(db_path, search='alpha', search_field='name')['items'] == []


def test_search_field_filename_matches_only_filename(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='alpha.json')

    assert len(_query(db_path, search='alpha', search_field='filename')['items']) == 1
    assert _query(db_path, search='dragon', search_field='filename')['items'] == []


def test_search_field_owner_matches_owning_card(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(
        db_path,
        entity_type='world_resource',
        name='Companion Lore',
        filename='companion.json',
        owner_entity_id='card::cards/lucy.png',
    )

    assert len(_query(db_path, search='lucy', search_field='owner')['items']) == 1
    assert _query(db_path, search='nobody', search_field='owner')['items'] == []


def test_search_field_defaults_to_smart_and_reports_it(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    result = _query(db_path, search='dragon')
    assert result['search_field'] == 'smart'
    assert len(result['items']) == 1


def test_unknown_search_field_falls_back_to_smart(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    assert _query(db_path, search='dragon', search_field='bogus')['search_field'] == 'smart'
    assert _query(db_path, search='dragon', search_field='')['search_field'] == 'smart'


def test_precise_search_fields_do_not_use_fts_tables(tmp_path):
    """精确分类只查索引列，因此 FTS 表内容为空时依旧能命中。"""
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json', fast='', full='')

    assert len(_query(db_path, search='dragon', search_field='name')['items']) == 1
    assert len(_query(db_path, search='dragon', search_field='filename')['items']) == 1
    # 智能搜索依赖 FTS + 名称，名称仍能命中。
    assert len(_query(db_path, search='dragon')['items']) == 1


# --- 中文全文 ---------------------------------------------------------------


def test_fulltext_two_character_chinese_substring_matches(tmp_path):
    """修复前：unicode61 不切分汉字，两字中文恒为 0 条。"""
    db_path = tmp_path / 'db.sqlite'
    _seed(
        db_path,
        name='血族纪元',
        filename='vampire.json',
        fast='血族纪元 vampire.json',
        full=split_cjk_for_index('血族纪元 vampire.json'),
    )

    for needle in ('血族', '血族纪', '纪元'):
        result = _query(db_path, search=needle, search_mode='fulltext')
        assert len(result['items']) == 1, needle


def test_fast_search_still_matches_chinese_via_like(tmp_path):
    """fast 表存原文，LIKE 子串匹配对中文本来就没问题。"""
    db_path = tmp_path / 'db.sqlite'
    _seed(
        db_path,
        name='血族纪元',
        filename='vampire.json',
        fast='血族纪元 vampire.json',
        full=split_cjk_for_index('血族纪元 vampire.json'),
    )

    assert len(_query(db_path, search='血族', search_mode='fast')['items']) == 1


def test_fulltext_entry_body_is_searchable(tmp_path):
    """全文索引收录条目正文，因此能搜到世界书内部的内容。"""
    db_path = tmp_path / 'db.sqlite'
    body = collect_worldbook_fulltext({'entries': {'0': {'content': '远古血脉契约的传说'}}})
    assert body

    _seed(
        db_path,
        name='Setting Book',
        filename='setting.json',
        fast='Setting Book setting.json',
        full=split_cjk_for_index(f'Setting Book setting.json {body}'),
    )

    assert len(_query(db_path, search='契约', search_mode='fulltext')['items']) == 1
    # fast 表不含正文，因此搜不到。
    assert _query(db_path, search='契约', search_mode='fast')['items'] == []


def test_fulltext_query_with_punctuation_does_not_raise(tmp_path):
    """``book7.json`` / ``a-b`` 曾经抛 fts5 语法错误或 no such column。"""
    db_path = tmp_path / 'db.sqlite'
    _seed(
        db_path,
        name='Book Seven',
        filename='book7.json',
        fast='Book Seven book7.json',
        full=split_cjk_for_index('Book Seven book7.json'),
    )

    for needle in ('book7.json', 'a-b', 'a:b', 'AND', '...'):
        result = _query(db_path, search=needle, search_mode='fulltext')
        assert isinstance(result['items'], list), needle


def test_punctuation_only_search_returns_empty_not_everything(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    result = _query(db_path, search='...', search_mode='fulltext')
    assert result['items'] == []
    assert result['total'] == 0
    assert result['search_degraded'] is True


def test_search_degraded_is_false_for_normal_queries(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    assert _query(db_path, search='dragon', search_mode='fulltext')['search_degraded'] is False
    assert _query(db_path, search='dragon', search_mode='fast')['search_degraded'] is False
    assert _query(db_path)['search_degraded'] is False


# --- 结果键集合 -------------------------------------------------------------


def test_ready_result_exposes_search_metadata_keys(tmp_path):
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    result = _query(db_path, search='dragon')
    assert result['index_ready'] is True
    assert set(result) == {
        'items',
        'total',
        'all_folders',
        'category_counts',
        'folder_capabilities',
        'index_ready',
        'search_field',
        'search_degraded',
    }


def test_not_ready_result_keeps_its_original_key_set(tmp_path):
    """该键集合被 tests/test_worldinfo_index_list_api.py 的闭等值断言锁定。"""
    db_path = tmp_path / 'db.sqlite'
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    assert _query(db_path) == {
        'items': [],
        'total': 0,
        'all_folders': [],
        'category_counts': {},
        'folder_capabilities': {},
        'index_ready': False,
    }


# --- 性能相关：查询形状 -----------------------------------------------------


def test_fts_subquery_uses_bound_generation_not_correlated_reference(tmp_path):
    """关联子查询 ``generation = e.generation`` 会让每行重跑一次 FTS 扫描。

    这里直接锁定 SQL 形状：FTS 子查询里的 generation 必须是占位符。
    """
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        generation = 1
        _, _, _, _, sql, where, params = wi_query._build_query_parts(
            {'search': 'dragon', 'search_mode': 'fast', 'type': 'all'},
            generation,
        )

    assert 'generation = e.generation' not in sql
    assert 'index_search_fast_v2 WHERE generation = ?' in sql
    # generation 作为参数出现，且没有内插进 SQL 文本。
    assert params[0] == generation
    assert 'entity_type IN ' in sql
    assert "LIKE 'world_%'" not in sql


def test_entity_type_filter_is_an_indexable_in_list(tmp_path):
    """``LIKE 'world_%'`` 会让 idx_index_entities_v2_gen_type_sort 失效。"""
    db_path = tmp_path / 'db.sqlite'
    _seed(db_path, name='Dragon Lore', filename='dragon.json')

    _, _, _, _, sql, _, _ = wi_query._build_query_parts({'type': 'all'}, 1)
    assert wi_query.WORLD_ENTITY_TYPE_FILTER in sql
    assert "e.entity_type LIKE 'world_%'" not in sql

    with sqlite3.connect(db_path) as conn:
        plan = [
            row[3]
            for row in conn.execute(
                'EXPLAIN QUERY PLAN SELECT e.entity_id FROM index_entities_v2 e'
                ' WHERE e.generation = 1'
                " AND e.entity_type IN ('world_global','world_resource','world_embedded')"
                ' ORDER BY e.sort_mtime DESC, e.sort_name ASC LIMIT 20'
            )
        ]
    assert any('idx_index_entities_v2_gen_type_sort' in step for step in plan), plan


def test_world_entity_types_constant_matches_index_producers():
    """枚举必须覆盖全部 world_* 生产者，否则清理会漏行、查询会漏结果。"""
    assert set(wi_query.WORLD_ENTITY_TYPES) == {
        'world_global',
        'world_resource',
        'world_embedded',
    }


def test_world_entity_enum_is_shared_with_cleanup_filters():
    """清理路径与查询路径必须用同一套枚举，否则会产生孤儿行。"""
    from core.data.index_runtime_store import _scope_generation_filters

    entity_where, entity_id_pattern, stats_scope = _scope_generation_filters('worldinfo')
    for entity_type in wi_query.WORLD_ENTITY_TYPES:
        assert f"'{entity_type}'" in entity_where
    assert 'LIKE' not in entity_where
    assert entity_id_pattern == 'world::%'
    assert stats_scope == 'worldinfo'


def test_unrelated_operational_errors_are_still_raised(tmp_path, monkeypatch):
    """真正的数据库故障不能被搜索降级逻辑吞掉。"""
    import sqlite3 as sqlite_module

    def _boom(_db_path=None):
        raise sqlite_module.OperationalError('database is locked')

    monkeypatch.setattr(wi_query, '_connect', _boom)

    try:
        wi_query.query_worldinfo_index({'search': 'dragon', 'db_path': str(tmp_path / 'x.sqlite')})
    except sqlite_module.OperationalError as exc:
        assert 'database is locked' in str(exc)
    else:
        raise AssertionError('OperationalError should propagate')


def test_schema_errors_are_not_treated_as_malformed_search(tmp_path, monkeypatch):
    """``no such column`` 说明是 schema 问题，不应被当成搜索输入问题。"""
    import sqlite3 as sqlite_module

    def _boom(_db_path=None):
        raise sqlite_module.OperationalError('no such column: missing_column')

    monkeypatch.setattr(wi_query, '_connect', _boom)

    try:
        wi_query.query_worldinfo_index({'search': 'dragon', 'db_path': str(tmp_path / 'x.sqlite')})
    except sqlite_module.OperationalError as exc:
        assert 'no such column' in str(exc)
    else:
        raise AssertionError('OperationalError should propagate')


def test_malformed_match_marker_detection_is_narrow():
    """只识别 FTS5 语法类错误，避免把数据库故障误判为可降级。"""
    import sqlite3 as sqlite_module

    assert wi_query._is_malformed_match_error(
        sqlite_module.OperationalError('fts5: syntax error near "."')
    )
    assert wi_query._is_malformed_match_error(
        sqlite_module.OperationalError('unterminated string')
    )
    assert not wi_query._is_malformed_match_error(
        sqlite_module.OperationalError('database is locked')
    )
    assert not wi_query._is_malformed_match_error(
        sqlite_module.OperationalError('no such column: missing_column')
    )


# --- 条目正文收录 -----------------------------------------------------------


def test_collect_worldbook_fulltext_reads_entries_object_and_array():
    from_dict = collect_worldbook_fulltext({'entries': {'0': {'content': '第一段'}}})
    from_list = collect_worldbook_fulltext({'entries': [{'content': '第一段'}]})
    assert '第一段' in from_dict
    assert from_dict == from_list


def test_collect_worldbook_fulltext_includes_keys_and_comments():
    body = collect_worldbook_fulltext({
        'entries': [{'comment': '标题', 'content': '正文', 'key': ['关键词'], 'keysecondary': ['次要']}]
    })
    for token in ('标题', '正文', '关键词', '次要'):
        assert token in body


def test_collect_worldbook_fulltext_handles_empty_and_invalid_input():
    assert collect_worldbook_fulltext(None) == ''
    assert collect_worldbook_fulltext({}) == ''
    assert collect_worldbook_fulltext({'entries': 'nonsense'}) == ''
    assert collect_worldbook_fulltext({'entries': [None, 'x', 3]}) == ''


def test_collect_worldbook_fulltext_caps_entry_and_book_size():
    from core.services.index_build_service import (
        WORLDBOOK_FULLTEXT_ENTRY_MAX_CHARS,
        WORLDBOOK_FULLTEXT_MAX_CHARS,
    )

    huge_entry = collect_worldbook_fulltext({'entries': [{'content': '血' * 100000}]})
    assert len(huge_entry) <= WORLDBOOK_FULLTEXT_ENTRY_MAX_CHARS

    many_entries = collect_worldbook_fulltext({
        'entries': [{'content': '血' * 20000} for _ in range(50)]
    })
    assert len(many_entries) <= WORLDBOOK_FULLTEXT_MAX_CHARS
