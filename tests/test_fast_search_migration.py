"""fast 搜索表由 fts5 迁移为普通表的行为。"""

import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import index_runtime_store, sqlite_capabilities
from core.data.index_runtime_store import ensure_index_runtime_schema


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    sqlite_capabilities.reset_cache_for_tests()
    yield
    sqlite_capabilities.reset_cache_for_tests()


def _table_sql(conn, table):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ? AND type = 'table'", (table,)
    ).fetchone()
    return str(row[0]) if row and row[0] else ''


def test_fresh_schema_creates_fast_as_plain_table():
    """新建库：fast 表必须是普通表，不能再依赖 FTS5。"""
    conn = sqlite3.connect(':memory:')
    ensure_index_runtime_schema(conn)

    sql = _table_sql(conn, 'index_search_fast_v2')
    conn.close()

    assert sql, 'index_search_fast_v2 应该存在'
    assert 'fts5' not in sql.lower()
    assert 'CREATE TABLE' in sql.upper()


def test_legacy_fts5_fast_table_is_migrated():
    """历史 fts5 fast 表必须被迁移为普通表（fts5 表无法 ALTER，只能重建）。"""
    conn = sqlite3.connect(':memory:')
    # 先造一个「旧版本」的 fts5 fast 表并写入数据
    conn.execute(
        'CREATE VIRTUAL TABLE index_search_fast_v2 USING fts5('
        'generation UNINDEXED, entity_id UNINDEXED, content)'
    )
    conn.execute(
        "INSERT INTO index_search_fast_v2(generation, entity_id, content) "
        "VALUES (1, 'card::old', 'old content')"
    )
    conn.commit()
    assert 'fts5' in _table_sql(conn, 'index_search_fast_v2').lower()

    ensure_index_runtime_schema(conn)

    sql = _table_sql(conn, 'index_search_fast_v2')
    remaining = conn.execute('SELECT COUNT(*) FROM index_search_fast_v2').fetchone()[0]
    columns = [row[1] for row in conn.execute('PRAGMA table_info(index_search_fast_v2)')]
    conn.close()

    assert 'fts5' not in sql.lower(), '迁移后不应再是 fts5 表'
    assert 'CREATE TABLE' in sql.upper()
    assert set(columns) >= {'generation', 'entity_id', 'content'}
    assert remaining == 1


def test_migration_is_idempotent():
    """重复调用不得反复重建表。"""
    conn = sqlite3.connect(':memory:')
    ensure_index_runtime_schema(conn)
    conn.execute(
        "INSERT INTO index_search_fast_v2(generation, entity_id, content) "
        "VALUES (1, 'card::a', 'x')"
    )
    conn.commit()

    ensure_index_runtime_schema(conn)
    ensure_index_runtime_schema(conn)

    count = conn.execute('SELECT COUNT(*) FROM index_search_fast_v2').fetchone()[0]
    conn.close()

    assert count == 1, '幂等调用不得清空普通表'


def test_old_database_reports_format_version_bump():
    """迁移后旧库的内容格式版本低于当前版本，从而触发自动重建。"""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        'CREATE VIRTUAL TABLE index_search_fast_v2 USING fts5('
        'generation UNINDEXED, entity_id UNINDEXED, content)'
    )
    conn.commit()

    ensure_index_runtime_schema(conn)
    # 老库从未写过格式版本 → 读到 0，低于 SEARCH_CONTENT_FORMAT_VERSION
    built = index_runtime_store.get_search_content_format_version(conn, 'cards')
    conn.close()

    assert built < index_runtime_store.SEARCH_CONTENT_FORMAT_VERSION


def test_without_fts5_full_table_is_skipped():
    """无 FTS5 时不建 full 表，且 schema 初始化不报错。"""
    sqlite_capabilities.force_for_tests(False)

    conn = sqlite3.connect(':memory:')
    ensure_index_runtime_schema(conn)

    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    conn.close()

    assert 'index_search_fast_v2' in names, 'fast 表不依赖 FTS5，必须仍然创建'
    assert 'index_search_full_v2' not in names, '无 FTS5 时不应创建 full 表'


def _seed_single_card(db_path):
    conn = sqlite3.connect(db_path)
    ensure_index_runtime_schema(conn)
    conn.execute(
        "UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' "
        "WHERE scope = 'cards'"
    )
    conn.execute(
        'INSERT OR REPLACE INTO index_entities_v2('
        'generation, entity_id, entity_type, source_path, name, filename, display_category, '
        'physical_category, category_mode, favorite, summary_preview, updated_at, import_time, '
        'token_count, sort_name, sort_mtime, thumb_url, source_revision'
        ') VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            1, 'card::cards/alpha.png', 'card', 'cards/alpha.png', 'Alpha', 'alpha.png',
            'SciFi', 'SciFi', 'physical', 1, 'pilot note', 200.0, 150.0, 3200,
            'alpha', 200.0, '', '200:1',
        ),
    )
    conn.execute(
        'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
        (1, 'card::cards/alpha.png', 'Alpha alpha.png SciFi blue hero pilot note 血族王子'),
    )
    conn.commit()
    conn.close()


def test_without_fts5_fast_search_still_works(tmp_path):
    """无 FTS5 时 fast 搜索（LIKE）必须照常返回结果。"""
    from core.services.card_index_query_service import query_indexed_cards

    sqlite_capabilities.force_for_tests(False)
    db_path = tmp_path / 'cards_metadata.db'
    _seed_single_card(db_path)

    result = query_indexed_cards(
        {'db_path': str(db_path), 'search': 'Alpha', 'page': 1, 'page_size': 20}
    )

    assert result['index_ready'] is True
    assert [row['id'] for row in result['cards']] == ['cards/alpha.png']


def test_without_fts5_fulltext_falls_back_to_fast(tmp_path):
    """无 FTS5 时请求 fulltext 不得报错，应降级为 fast 并仍返回结果。"""
    from core.services.card_index_query_service import query_indexed_cards

    sqlite_capabilities.force_for_tests(False)
    db_path = tmp_path / 'cards_metadata.db'
    _seed_single_card(db_path)

    result = query_indexed_cards(
        {
            'db_path': str(db_path),
            'search': '血族',
            'search_mode': 'fulltext',
            'page': 1,
            'page_size': 20,
        }
    )

    assert result['index_ready'] is True
    assert [row['id'] for row in result['cards']] == ['cards/alpha.png']


def test_legacy_fast_migration_preserves_active_search(tmp_path):
    from core.services.card_index_query_service import query_indexed_cards

    db_path = tmp_path / 'cards.db'
    _seed_single_card(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute('ALTER TABLE index_search_fast_v2 RENAME TO saved_fast')
        conn.execute('CREATE VIRTUAL TABLE index_search_fast_v2 USING fts5('
                     'generation UNINDEXED, entity_id UNINDEXED, content)')
        conn.execute('INSERT INTO index_search_fast_v2 SELECT * FROM saved_fast')
        conn.execute('DROP TABLE saved_fast')
        conn.commit()
        ensure_index_runtime_schema(conn)
    result = query_indexed_cards({'db_path': str(db_path), 'search': 'Alpha', 'page': 1, 'page_size': 20})
    assert result['index_ready'] is True
    assert [row['id'] for row in result['cards']] == ['cards/alpha.png']
