import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core import init_services
from core.context import ctx
from core.data.index_runtime_store import (
    ensure_index_runtime_schema,
    set_search_content_format_version,
)
from core.services import index_build_service
from core.services import index_upgrade_service


def test_run_startup_upgrade_skips_ready_scopes(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 2, state = 'ready', phase = 'ready' WHERE scope = 'cards'"
        )
        conn.execute(
            "UPDATE index_build_state SET active_generation = 3, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        # 就绪且搜索内容格式已是最新，才应该跳过重建。
        for scope in ('cards', 'worldinfo'):
            set_search_content_format_version(conn, scope)
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))

    calls = []
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': calls.append((scope, reason)),
    )

    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=True)

    assert calls == []


def test_run_startup_upgrade_rebuilds_ready_scope_with_stale_search_format(monkeypatch, tmp_path):
    """索引就绪但内容格式过时时必须重建，否则搜索会静默失效。

    这正是「先关掉再打开 worldinfo_list_use_index」的场景：开关只影响读路径，
    索引本身仍是旧的，需要靠格式版本比对来触发重建。
    """
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 3, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        conn.execute(
            "UPDATE index_build_state SET active_generation = 2, state = 'ready', phase = 'ready' WHERE scope = 'cards'"
        )
        # cards 已是最新格式，worldinfo 停留在历史格式（未记录 -> v0）。
        set_search_content_format_version(conn, 'cards')
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))

    calls = []
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': calls.append((scope, reason)),
    )

    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=True)

    assert calls == [('worldinfo', 'search_content_format_upgrade')]


def test_run_startup_upgrade_skips_format_rebuild_when_bootstrap_disabled(monkeypatch, tmp_path):
    """关闭自动引导时不应因为格式过时而重建（交给用户手动触发）。"""
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 3, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))

    calls = []
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': calls.append((scope, reason)),
    )

    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=False)

    assert calls == []


def test_format_version_survives_second_startup_without_rebuilding(monkeypatch, tmp_path):
    """记录格式版本后，第二次启动不应再因格式问题重建（避免每次启动都重建）。

    注意 cards scope 在本用例里从未构建过，因此它会走正常的 bootstrap；
    这里只断言 worldinfo 不会因**格式过时**而重建。
    """
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 3, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        set_search_content_format_version(conn, 'worldinfo')
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))

    calls = []
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': calls.append((scope, reason)),
    )

    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=True)
    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=True)

    assert [call for call in calls if call[0] == 'worldinfo'] == []


def test_run_startup_upgrade_recovers_interrupted_worldinfo_build(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 4, building_generation = 5, state = 'running', phase = 'build_entities', owner_token = 'old-owner' WHERE scope = 'worldinfo'"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service.ctx, 'index_owner_token', 'new-owner')

    recovered = []
    monkeypatch.setattr(index_upgrade_service, 'recover_scope_build', lambda scope: recovered.append(scope))
    monkeypatch.setattr(index_upgrade_service, 'rebuild_scope_generation', lambda scope, reason='bootstrap': None)

    index_upgrade_service.run_startup_upgrade_if_needed(index_auto_bootstrap=True)

    assert recovered == ['worldinfo']


def test_recovery_keeps_old_active_generation_when_build_generation_exists(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 7, building_generation = 8, state = 'running', phase = 'activate_generation', owner_token = 'dead-owner' WHERE scope = 'cards'"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (7, 'card::stable.png', 'card', 'stable.png', '', 'Stable', 'stable.png', '', '', 'physical', 0, '', 0, 0, 0, 'stable', 0, '', '')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (8, 'card::partial.png', 'card', 'partial.png', '', 'Partial', 'partial.png', '', '', 'physical', 0, '', 0, 0, 0, 'partial', 0, '', '')"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service.ctx, 'index_owner_token', 'new-owner')
    monkeypatch.setattr(index_upgrade_service, 'rebuild_scope_generation', lambda scope, reason='bootstrap': None)

    index_upgrade_service.recover_scope_build('cards')

    with sqlite3.connect(db_path) as conn:
        state_row = conn.execute(
            "SELECT active_generation, building_generation, state FROM index_build_state WHERE scope = 'cards'"
        ).fetchone()
        entities = conn.execute(
            'SELECT generation, entity_id FROM index_entities_v2 ORDER BY generation, entity_id'
        ).fetchall()

    assert state_row == (7, 0, 'failed')
    assert entities == [(7, 'card::stable.png')]


def test_legacy_index_table_policy_explicitly_keeps_runtime_compatibility():
    policy = index_upgrade_service.get_legacy_index_table_policy()

    assert policy['decision'] == 'stop_creating'
    assert 'runtime v2 tables only' in policy['reason']
    assert policy['runtime_callers'] == ()


def test_backfill_embedded_worldinfo_marks_rows_scanned(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.png'
    card_path.write_bytes(b'hero')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata(id, char_name, has_character_book, character_book_name, wi_metadata_scanned) VALUES ('hero.png', 'Hero', 0, '', 0)"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_upgrade_service, 'extract_card_info', lambda _path: {'data': {'character_book': {'entries': {}}}})
    monkeypatch.setattr(index_upgrade_service, 'get_wi_meta', lambda _data: (True, 'Book'))

    index_upgrade_service.backfill_embedded_worldinfo_metadata()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT has_character_book, character_book_name, wi_metadata_scanned FROM card_metadata WHERE id = ?',
            ('hero.png',),
        ).fetchone()

    assert row == (1, 'Book', 1)


def test_backfill_embedded_worldinfo_keeps_uninspectable_rows_unscanned(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    (cards_dir / 'broken.png').write_bytes(b'broken')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO card_metadata(id, char_name, has_character_book, character_book_name, wi_metadata_scanned) VALUES (?, ?, ?, ?, ?)",
            [
                ('missing.png', 'Missing', 0, '', 0),
                ('broken.png', 'Broken', 0, '', 0),
            ],
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_upgrade_service, 'extract_card_info', lambda _path: None)

    index_upgrade_service.backfill_embedded_worldinfo_metadata()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT id, has_character_book, character_book_name, wi_metadata_scanned FROM card_metadata ORDER BY id'
        ).fetchall()

    assert rows == [
        ('broken.png', 0, '', 0),
        ('missing.png', 0, '', 0),
    ]


def test_rebuild_worldinfo_generation_writes_full_v2_rows_before_ready(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    lore_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    cards_dir.mkdir()
    (cards_dir / 'hero.png').write_bytes(b'hero')
    (lore_dir / 'fantasy').mkdir(parents=True, exist_ok=True)
    (lore_dir / 'fantasy' / 'global-book.json').write_text('{"name": "Global Book", "entries": {}}', encoding='utf-8')
    (resources_dir / 'hero-assets' / 'lorebooks').mkdir(parents=True, exist_ok=True)
    (resources_dir / 'hero-assets' / 'lorebooks' / 'resource-book.json').write_text('{"name": "Resource Book", "entries": {}}', encoding='utf-8')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata(id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES ('hero.png', 'Hero', 'fantasy', 0, '', 12.0, 0)"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        index_build_service,
        'load_config',
        lambda: {
            'world_info_dir': str(lore_dir),
            'resources_dir': str(resources_dir),
        },
    )
    monkeypatch.setattr(
        index_build_service,
        'load_ui_data',
        lambda: {
            'hero.png': {'resource_folder': 'hero-assets', 'summary': 'embedded summary'},
            '_resource_item_categories_v1': {
                'worldinfo': {
                    str(resources_dir / 'hero-assets' / 'lorebooks' / 'resource-book.json').replace('\\', '/').lower(): {
                        'category': 'override-cat',
                        'updated_at': 1,
                    }
                }
            },
        },
    )

    def _extract(_path):
        return {'data': {'character_book': {'name': 'Book', 'entries': {'0': {'content': 'hello'}}}}}

    monkeypatch.setattr(index_upgrade_service, 'extract_card_info', _extract)
    monkeypatch.setattr(index_build_service, 'extract_card_info', _extract)
    monkeypatch.setattr(index_upgrade_service, 'get_wi_meta', lambda _data: (True, 'Book'))

    index_upgrade_service.rebuild_scope_generation('worldinfo')

    with sqlite3.connect(db_path) as conn:
        state_row = conn.execute(
            "SELECT active_generation, building_generation, state, items_written FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()
        entity_rows = conn.execute(
            "SELECT generation, entity_type, name, display_category, category_mode, owner_entity_id FROM index_entities_v2 WHERE entity_type LIKE 'world_%' ORDER BY entity_id"
        ).fetchall()
        stat_rows = conn.execute(
            "SELECT entity_type, category_path, direct_count, subtree_count FROM index_category_stats_v2 WHERE generation = 1 AND scope = 'worldinfo' ORDER BY entity_type, category_path"
        ).fetchall()
        metadata_row = conn.execute(
            "SELECT has_character_book, character_book_name, wi_metadata_scanned FROM card_metadata WHERE id = 'hero.png'"
        ).fetchone()

    assert state_row == (1, 0, 'ready', 3)
    assert entity_rows == [
        (1, 'world_embedded', 'Book', 'fantasy', 'inherited', 'card::hero.png'),
        (1, 'world_global', 'Global Book', 'fantasy', 'physical', ''),
        (1, 'world_resource', 'Resource Book', 'override-cat', 'override', 'card::hero.png'),
    ]
    assert stat_rows == [
        ('world_all', 'fantasy', 2, 2),
        ('world_all', 'override-cat', 1, 1),
        ('world_embedded', 'fantasy', 1, 1),
        ('world_global', 'fantasy', 1, 1),
        ('world_resource', 'override-cat', 1, 1),
    ]
    assert metadata_row == (1, 'Book', 1)


def test_rebuild_publishes_progress_into_index_state(monkeypatch, tmp_path):
    """重建过程中必须把进度写进 ctx.index_state，前端才能显示百分比。"""
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    (cards_dir / 'hero.png').write_bytes(b'hero')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata(id, char_name, category, last_modified, wi_metadata_scanned) VALUES ('hero.png', 'Hero', '', 1.0, 0)"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        index_build_service,
        'load_config',
        lambda: {'world_info_dir': str(tmp_path / 'wi'), 'resources_dir': str(tmp_path / 'res')},
    )
    monkeypatch.setattr(index_build_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(index_upgrade_service, 'extract_card_info', lambda _path: {'data': {}})
    monkeypatch.setattr(index_build_service, 'extract_card_info', lambda _path: {'data': {}})
    monkeypatch.setattr(index_upgrade_service, 'get_wi_meta', lambda _data: (False, ''))

    ctx.index_state['worldinfo']['progress_done'] = 0
    ctx.index_state['worldinfo']['progress_total'] = 0

    index_upgrade_service.rebuild_scope_generation('worldinfo')

    with sqlite3.connect(db_path) as conn:
        progress = conn.execute(
            "SELECT progress_done, progress_total, phase, state FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()

    assert progress[3] == 'ready'
    # 激活时会把 done 顶到 total，避免进度条停在 99%。
    assert progress[0] == progress[1] or progress[1] == 0
    assert ctx.index_state['worldinfo']['progress_total'] >= 1


def test_worldinfo_rebuild_keeps_backfill_but_rolls_back_projection_when_build_fails(monkeypatch, tmp_path):
    """构建失败时：索引行整体回滚，但「已扫描世界书元数据」这一事实保留。

    回填会逐张开卡文件（大库可达数分钟），且带 ``wi_metadata_scanned`` 幂等
    标记；如果跟着构建一起回滚，每次重试都要把全部卡片再读一遍，正是启动慢
    的根源。索引行本身仍由 generation 机制整体丢弃，不会出现半成品数据。
    """
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    (cards_dir / 'hero.png').write_bytes(b'hero')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata(id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES ('hero.png', 'Hero', 'fantasy', 0, '', 12.0, 0)"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'load_ui_data', lambda: {})

    calls = {'count': 0}

    def _extract(_path):
        calls['count'] += 1
        return {'data': {'character_book': {'name': 'Book', 'entries': {'0': {'content': 'hello'}}}}}

    monkeypatch.setattr(index_upgrade_service, 'extract_card_info', _extract)
    monkeypatch.setattr(index_build_service, 'extract_card_info', _extract)
    monkeypatch.setattr(index_upgrade_service, 'get_wi_meta', lambda _data: (True, 'Book'))
    monkeypatch.setattr(index_upgrade_service, 'build_worldinfo_generation', lambda conn, generation, inspected_books=None, progress_cb=None: (_ for _ in ()).throw(RuntimeError('projection build failed')))

    try:
        index_upgrade_service.rebuild_scope_generation('worldinfo')
    except RuntimeError as exc:
        assert str(exc) == 'projection build failed'
    else:
        raise AssertionError('expected rebuild to fail')

    with sqlite3.connect(db_path) as conn:
        metadata_row = conn.execute(
            "SELECT has_character_book, character_book_name, wi_metadata_scanned FROM card_metadata WHERE id = 'hero.png'"
        ).fetchone()
        entity_rows = conn.execute(
            "SELECT generation, entity_type, name FROM index_entities_v2 WHERE entity_type LIKE 'world_%'"
        ).fetchall()
        state_row = conn.execute(
            "SELECT active_generation, building_generation, state FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()

    assert metadata_row == (1, 'Book', 1)
    assert entity_rows == []
    assert state_row == (0, 1, 'running')


def test_worldinfo_rebuild_does_not_activate_ready_when_backfill_identified_owner_but_projection_skips(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    (cards_dir / 'hero.png').write_bytes(b'hero')

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, tags TEXT, category TEXT, creator TEXT, char_version TEXT, last_modified REAL, file_hash TEXT, file_size INTEGER, token_count INTEGER DEFAULT 0, has_character_book INTEGER DEFAULT 0, character_book_name TEXT DEFAULT '', is_favorite INTEGER DEFAULT 0, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata(id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES ('hero.png', 'Hero', 'fantasy', 0, '', 12.0, 0)"
        )
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(
        index_upgrade_service,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Book', 'entries': {'0': {'content': 'hello'}}}}},
    )
    monkeypatch.setattr(index_upgrade_service, 'get_wi_meta', lambda _data: (True, 'Book'))
    monkeypatch.setattr(index_upgrade_service, 'build_worldinfo_generation', lambda conn, generation, inspected_books=None, progress_cb=None: 0)

    try:
        index_upgrade_service.rebuild_scope_generation('worldinfo')
    except RuntimeError as exc:
        assert str(exc) == 'worldinfo projection incomplete for cards: hero.png'
    else:
        raise AssertionError('expected rebuild to fail')

    with sqlite3.connect(db_path) as conn:
        state_row = conn.execute(
            "SELECT active_generation, building_generation, state FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()
        entity_rows = conn.execute(
            "SELECT generation, entity_type, name FROM index_entities_v2 WHERE entity_type LIKE 'world_%'"
        ).fetchall()
        metadata_row = conn.execute(
            "SELECT has_character_book, character_book_name, wi_metadata_scanned FROM card_metadata WHERE id = 'hero.png'"
        ).fetchone()

    assert state_row == (0, 1, 'running')
    assert entity_rows == []
    assert metadata_row == (1, 'Book', 1)


def test_init_services_plans_upgrade_before_cache_and_defers_rebuild(monkeypatch):
    """启动流程只在同步阶段「判定」要不要重建，重建本身必须丢到后台线程。

    这是「旧库世界书多时卡在正在初始化资源库」的回归保护：init_services
    返回时不应已经跑完 rebuild_scope_generation。后台重建必须排在索引作业
    worker 之前启动，否则 worker 会先跑起来、在重建窗口里写旧 generation。
    """
    calls = []

    monkeypatch.setattr('core.cleanup_temp_files', lambda: calls.append('cleanup'))
    monkeypatch.setattr('core.init_database', lambda: calls.append('init_database'))
    monkeypatch.setattr(
        'core.plan_startup_upgrade',
        lambda index_auto_bootstrap=True: (
            calls.append(('plan_startup_upgrade', index_auto_bootstrap)),
            [{'scope': 'worldinfo', 'reason': 'search_content_format_upgrade'}],
        )[1],
    )
    monkeypatch.setattr(ctx, 'cache', type('CacheStub', (), {'reload_from_db': lambda self: calls.append('cache_reload')})())
    monkeypatch.setattr('core.start_background_scanner', lambda: calls.append('start_background_scanner'))
    monkeypatch.setattr('core.start_index_job_worker', lambda: calls.append('start_index_job_worker'))
    monkeypatch.setattr(
        'core.start_background_index_upgrade',
        lambda plan: calls.append(('start_background_index_upgrade', list(plan))),
    )
    monkeypatch.setattr(ctx, 'set_status', lambda **kwargs: None)

    init_services()

    assert calls == [
        'cleanup',
        'init_database',
        ('plan_startup_upgrade', True),
        'cache_reload',
        ('start_background_index_upgrade', [{'scope': 'worldinfo', 'reason': 'search_content_format_upgrade'}]),
        'start_background_scanner',
        'start_index_job_worker',
    ]


def test_init_services_marks_ready_without_waiting_for_index_rebuild(monkeypatch):
    """init_services 结束时必须已经是 ready —— 后台重建不允许阻塞启动。"""
    statuses = []

    monkeypatch.setattr('core.cleanup_temp_files', lambda: None)
    monkeypatch.setattr('core.init_database', lambda: None)
    monkeypatch.setattr('core.plan_startup_upgrade', lambda index_auto_bootstrap=True: [{'scope': 'cards', 'reason': 'bootstrap'}])
    monkeypatch.setattr(ctx, 'cache', type('CacheStub', (), {'reload_from_db': lambda self: None})())
    monkeypatch.setattr('core.start_background_scanner', lambda: None)
    monkeypatch.setattr('core.start_index_job_worker', lambda: None)
    monkeypatch.setattr(ctx, 'set_status', lambda **kwargs: statuses.append(kwargs.get('status')))
    # 后台线程用桩替换，避免测试真的去读磁盘建索引。
    monkeypatch.setattr('core.start_background_index_upgrade', lambda plan: None)

    init_services()

    assert statuses[-1] == 'ready'


def test_plan_startup_upgrade_returns_plan_without_rebuilding(monkeypatch, tmp_path):
    """计划阶段只做判定：返回待重建 scope，绝不真的跑重建。"""
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 3, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        set_search_content_format_version(conn, 'worldinfo')
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))

    rebuilt = []
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': rebuilt.append((scope, reason)),
    )

    plan = index_upgrade_service.plan_startup_upgrade(index_auto_bootstrap=True)

    # worldinfo 已就绪且格式最新 → 不需要重建；cards 从未建过 → bootstrap。
    assert plan == [{'scope': 'cards', 'reason': 'bootstrap'}]
    assert rebuilt == []


def test_start_background_index_upgrade_returns_immediately_and_sets_flags(monkeypatch):
    """后台升级必须立刻返回，且期间 index_upgrade_active 为真、结束时置位 done。"""
    import threading

    release = threading.Event()
    started = threading.Event()

    def fake_rebuild(scope, reason='bootstrap'):
        started.set()
        release.wait(5)

    monkeypatch.setattr(index_upgrade_service, 'rebuild_scope_generation', fake_rebuild)
    monkeypatch.setattr(index_upgrade_service, '_refresh_after_upgrade', lambda: None)
    monkeypatch.setattr(index_upgrade_service, 'ctx', ctx)

    ctx.index_upgrade_active = False
    ctx.index_upgrade_done.set()

    thread = index_upgrade_service.start_background_index_upgrade(
        [{'scope': 'worldinfo', 'reason': 'bootstrap'}]
    )

    try:
        assert thread is not None
        assert started.wait(5) is True
        # 线程已在跑重建，但调用方（启动流程）早已继续往下走。
        assert ctx.index_upgrade_active is True
        assert ctx.index_upgrade_done.is_set() is False
    finally:
        release.set()
        thread.join(5)

    assert ctx.index_upgrade_active is False
    assert ctx.index_upgrade_done.is_set() is True


def test_start_background_index_upgrade_with_empty_plan_is_noop():
    ctx.index_upgrade_active = True
    ctx.index_upgrade_done.clear()

    assert index_upgrade_service.start_background_index_upgrade([]) is None
    assert ctx.index_upgrade_active is True  # 空计划不应改动既有状态
    assert ctx.index_upgrade_done.is_set() is True


def test_background_upgrade_failure_marks_scope_failed_and_clears_flag(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.commit()

    monkeypatch.setattr(index_upgrade_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        index_upgrade_service,
        'rebuild_scope_generation',
        lambda scope, reason='bootstrap': (_ for _ in ()).throw(RuntimeError('boom')),
    )
    monkeypatch.setattr(index_upgrade_service, '_refresh_after_upgrade', lambda: None)
    monkeypatch.setattr(index_upgrade_service, 'ctx', ctx)

    ctx.index_upgrade_active = False
    ctx.index_upgrade_done.set()

    thread = index_upgrade_service.start_background_index_upgrade(
        [{'scope': 'worldinfo', 'reason': 'bootstrap'}]
    )
    thread.join(10)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, last_error FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()

    assert row[0] == 'failed'
    assert 'boom' in row[1]
    assert ctx.index_upgrade_active is False
    assert ctx.index_upgrade_done.is_set() is True
