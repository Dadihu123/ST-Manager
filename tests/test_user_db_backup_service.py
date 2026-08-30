import json
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services.card_index_query_service import query_indexed_cards


def _open_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _create_tables(conn):
    conn.execute(
        '''
        CREATE TABLE card_metadata (
            id TEXT PRIMARY KEY,
            is_favorite INTEGER DEFAULT 0
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE wi_clipboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_json TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE wi_entry_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_key TEXT NOT NULL,
            entry_uid TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        '''
    )
    conn.commit()


def _create_tables_without_history(conn):
    conn.execute(
        '''
        CREATE TABLE card_metadata (
            id TEXT PRIMARY KEY,
            is_favorite INTEGER DEFAULT 0
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE wi_clipboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_json TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        '''
    )
    conn.commit()


def _create_monitor_tables(conn):
    conn.execute(
        '''
        CREATE TABLE source_update_monitor_pools (
            pool_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            schedule_mode TEXT NOT NULL DEFAULT 'manual',
            daily_time TEXT,
            timezone TEXT,
            next_run_at REAL,
            last_run_at REAL,
            last_run_id TEXT,
            created_at REAL,
            updated_at REAL
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE source_update_monitor_entries (
            pool_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            source_url_snapshot TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at REAL,
            last_seen_source_url TEXT,
            last_run_status TEXT,
            last_run_at REAL,
            last_error TEXT,
            invalid_reason TEXT,
            PRIMARY KEY (pool_id, card_id)
        )
        '''
    )
    conn.commit()


def _fetch_all(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _create_card_index_metadata_table(conn):
    conn.execute(
        'CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, tags TEXT, category TEXT, last_modified REAL, token_count INTEGER, is_favorite INTEGER, has_character_book INTEGER, character_book_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, creator TEXT, char_version TEXT, file_hash TEXT, file_size INTEGER)'
    )


def _seed_card_index_projection(conn, *, card_id, source_path, name='Hero', summary='', favorite=0, token_count=100, tags=()):
    conn.execute(
        'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (card_id, name, json.dumps(list(tags)), '', 10.0, token_count, favorite, 0, '', '', '', '', '', '', 'hash', 1),
    )
    conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
    conn.execute(
        "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, f'card::{card_id}', 'card', str(source_path), '', name, Path(card_id).name, '', '', 'physical', favorite, summary, 10.0, 0.0, token_count, name.lower(), 10.0, '', '10:1'),
    )

    search_parts = [name, Path(card_id).name]
    if summary:
        search_parts.append(summary)
    search_parts.extend(tags)
    search_content = ' '.join(search_parts)

    conn.execute('INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)', (1, f'card::{card_id}', search_content))
    conn.execute('INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)', (1, f'card::{card_id}', search_content))
    for tag in tags:
        conn.execute('INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)', (1, f'card::{card_id}', tag))


def test_export_backup_includes_monitor_config_and_card_uid(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    stable_uid = '11111111-1111-4111-8111-111111111111'
    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute('ALTER TABLE card_metadata ADD COLUMN card_uid TEXT')
        _create_monitor_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite, card_uid) VALUES (?, ?, ?)',
            ('folder/hero.png', 0, stable_uid),
        )
        conn.execute(
            '''
            INSERT INTO source_update_monitor_pools
                (pool_id, name, enabled, schedule_mode, daily_time, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            ('default', '我的监控池', 1, 'daily', '09:30', 'Asia/Shanghai', 10.0, 11.0),
        )
        conn.execute(
            '''
            INSERT INTO source_update_monitor_entries
                (pool_id, card_id, source_url_snapshot, enabled, added_at, last_seen_source_url,
                 last_run_status, last_run_at, last_error, invalid_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'default',
                'folder/hero.png',
                'https://discord.com/channels/1/2/3',
                1,
                12.0,
                'https://discord.com/channels/1/2/3',
                'unchanged',
                13.0,
                '',
                '',
            ),
        )
        conn.commit()

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.BASE_DIR', str(tmp_path))

    result = UserDbBackupService().export_backup()
    payload = json.loads((tmp_path / result['file_path']).read_text(encoding='utf-8'))

    assert result['stats']['source_update_monitor'] == {'pools': 1, 'entries': 1}
    assert payload['data']['source_update_monitor'] == {
        'pools': [
            {
                'pool_id': 'default',
                'name': '我的监控池',
                'enabled': True,
                'schedule_mode': 'daily',
                'daily_time': '09:30',
                'timezone': 'Asia/Shanghai',
            }
        ],
        'entries': [
            {
                'pool_id': 'default',
                'card_id': 'folder/hero.png',
                'card_uid': stable_uid,
                'source_url_snapshot': 'https://discord.com/channels/1/2/3',
                'enabled': True,
                'added_at': 12.0,
                'last_seen_source_url': 'https://discord.com/channels/1/2/3',
            }
        ],
    }


def test_import_monitor_backup_prefers_card_uid_and_falls_back_to_card_id(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    stable_uid = '22222222-2222-4222-8222-222222222222'
    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute('ALTER TABLE card_metadata ADD COLUMN card_uid TEXT')
        _create_monitor_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite, card_uid) VALUES (?, ?, ?), (?, ?, ?)',
            ('current/hero.png', 0, stable_uid, 'legacy/mage.png', 0, None),
        )
        conn.execute(
            '''
            INSERT INTO source_update_monitor_pools
                (pool_id, name, enabled, schedule_mode, daily_time, timezone, created_at, updated_at)
            VALUES ('default', '旧名称', 0, 'manual', NULL, NULL, 1.0, 1.0)
            ''',
        )
        conn.execute(
            '''
            INSERT INTO source_update_monitor_entries
                (pool_id, card_id, source_url_snapshot, enabled, added_at, last_seen_source_url,
                 last_run_status, last_run_at, last_error, invalid_reason)
            VALUES ('default', 'old/hero.png', '', 1, 2.0, '', 'missing', 3.0, 'old', 'old')
            ''',
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-08-30T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [],
            'wi_clipboard': [],
            'wi_entry_history': [],
            'source_update_monitor': {
                'pools': [
                    {
                        'pool_id': 'default',
                        'name': '恢复后的监控池',
                        'enabled': True,
                        'schedule_mode': 'daily',
                        'daily_time': '08:00',
                        'timezone': 'Asia/Shanghai',
                    }
                ],
                'entries': [
                    {
                        'pool_id': 'default',
                        'card_id': 'old/hero.png',
                        'card_uid': stable_uid,
                        'source_url_snapshot': 'https://discord.com/channels/1/2/3',
                        'enabled': True,
                        'added_at': 20.0,
                        'last_seen_source_url': 'https://discord.com/channels/1/2/3',
                    },
                    {
                        'pool_id': 'default',
                        'card_id': 'legacy/mage.png',
                        'card_uid': '',
                        'source_url_snapshot': 'https://discord.com/channels/4/5/6',
                        'enabled': False,
                        'added_at': 21.0,
                        'last_seen_source_url': 'https://discord.com/channels/4/5/6',
                    },
                ],
            },
        },
    }
    backup_file = tmp_path / 'monitor.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', None)

    result = UserDbBackupService().import_backup(str(backup_file), source_name='monitor.json')

    with _open_db(db_path) as conn:
        pool = conn.execute(
            'SELECT name, enabled, schedule_mode, daily_time, timezone FROM source_update_monitor_pools WHERE pool_id = ?',
            ('default',),
        ).fetchone()
        entries = _fetch_all(
            conn,
            '''
            SELECT pool_id, card_id, card_uid, source_url_snapshot, enabled, added_at, last_seen_source_url
            FROM source_update_monitor_entries ORDER BY card_id
            ''',
        )

    assert tuple(pool) == ('恢复后的监控池', 1, 'daily', '08:00', 'Asia/Shanghai')
    assert entries == [
        {
            'pool_id': 'default',
            'card_id': 'current/hero.png',
            'card_uid': stable_uid,
            'source_url_snapshot': 'https://discord.com/channels/1/2/3',
            'enabled': 1,
            'added_at': 20.0,
            'last_seen_source_url': 'https://discord.com/channels/1/2/3',
        },
        {
            'pool_id': 'default',
            'card_id': 'legacy/mage.png',
            'card_uid': None,
            'source_url_snapshot': 'https://discord.com/channels/4/5/6',
            'enabled': 0,
            'added_at': 21.0,
            'last_seen_source_url': 'https://discord.com/channels/4/5/6',
        },
    ]
    assert result['stats']['source_update_monitor'] == {
        'pools': {'imported': 1, 'unchanged': 0},
        'entries': {'imported': 2, 'unchanged': 0, 'skipped_missing_cards': 0},
    }


def test_export_backup_includes_only_db_sections_and_counts(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    backup_root = tmp_path / 'data'
    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?), (?, ?)',
            ('hero.png', 1, 'mage.png', 0),
        )
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?), (?, ?, ?)',
            (
                json.dumps({'text': 'alpha'}, ensure_ascii=False),
                0,
                100.0,
                json.dumps({'text': 'beta'}, ensure_ascii=False),
                1,
                101.0,
            ),
        )
        conn.execute(
            'INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at) VALUES (?, ?, ?, ?, ?)',
            (
                'scope-a',
                'entry-1',
                json.dumps({'value': 'v1'}, ensure_ascii=False),
                'hash-1',
                102.0,
            ),
        )
        conn.commit()

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.BASE_DIR', str(tmp_path))

    service = UserDbBackupService()
    result = service.export_backup()

    export_path = tmp_path / result['file_path']
    payload = json.loads(export_path.read_text(encoding='utf-8'))

    assert result['file_name'].startswith('user_db_backup_')
    assert result['stats'] == {
        'favorites': 1,
        'wi_clipboard': 2,
        'wi_entry_history': 1,
    }
    assert payload['schema_version'] == 1
    assert payload['app'] == 'ST-Manager'
    assert set(payload['data'].keys()) == {'favorites', 'wi_clipboard', 'wi_entry_history'}
    assert payload['data']['favorites'] == [
        {'card_id': 'hero.png', 'is_favorite': True},
    ]
    assert payload['data']['wi_clipboard'] == [
        {'content': {'text': 'alpha'}, 'sort_order': 0, 'created_at': 100.0},
        {'content': {'text': 'beta'}, 'sort_order': 1, 'created_at': 101.0},
    ]
    assert payload['data']['wi_entry_history'] == [
        {
            'scope_key': 'scope-a',
            'entry_uid': 'entry-1',
            'snapshot_json': json.dumps({'value': 'v1'}, ensure_ascii=False),
            'snapshot_hash': 'hash-1',
            'created_at': 102.0,
        }
    ]


def test_export_backup_tolerates_missing_history_table(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    with _open_db(db_path) as conn:
        _create_tables_without_history(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?)',
            ('hero.png', 1),
        )
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
            (json.dumps({'text': 'alpha'}, ensure_ascii=False), 0, 100.0),
        )
        conn.commit()

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.BASE_DIR', str(tmp_path))

    result = UserDbBackupService().export_backup()

    export_path = tmp_path / result['file_path']
    payload = json.loads(export_path.read_text(encoding='utf-8'))

    assert result['stats'] == {
        'favorites': 1,
        'wi_clipboard': 1,
        'wi_entry_history': 0,
    }
    assert payload['data']['favorites'] == [
        {'card_id': 'hero.png', 'is_favorite': True},
    ]
    assert payload['data']['wi_clipboard'] == [
        {'content': {'text': 'alpha'}, 'sort_order': 0, 'created_at': 100.0},
    ]
    assert payload['data']['wi_entry_history'] == []


def test_import_backup_merges_favorites_skips_missing_cards_and_syncs_side_effects(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?), (?, ?)',
            ('hero.png', 0, 'mage.png', 1),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
                {'card_id': 'mage.png', 'is_favorite': True},
                {'card_id': 'missing.png', 'is_favorite': True},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'favorites.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    cache_calls = []
    sync_calls = []
    apply_calls = []

    class _FakeCache:
        def toggle_favorite_update(self, card_id, value):
            cache_calls.append((card_id, value))

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', _FakeCache())
    monkeypatch.setattr(
        'core.services.user_db_backup_service.sync_card_index_jobs',
        lambda **kwargs: sync_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda card_id, favorite_source_path: apply_calls.append((card_id, favorite_source_path)),
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path) if card_id == 'hero.png' else '',
    )

    result = UserDbBackupService().import_backup(str(backup_file), source_name='favorites.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 1},
        {'id': 'mage.png', 'is_favorite': 1},
    ]
    assert result['source_name'] == 'favorites.json'
    assert result['stats']['favorites'] == {
        'imported': 1,
        'skipped_missing_cards': 1,
        'unchanged': 1,
    }
    assert result['stats']['wi_clipboard'] == {'imported': 0, 'deduplicated': 0}
    assert result['stats']['wi_entry_history'] == {'imported': 0, 'deduplicated': 0, 'trimmed': 0}
    assert cache_calls == [('hero.png', True)]
    assert sync_calls == [
        {
            'card_id': 'hero.png',
            'source_path': str(source_path),
            'favorite_changed': True,
        }
    ]
    assert apply_calls == [('hero.png', str(source_path))]


def test_import_compact_favorites_backup_keeps_other_existing_favorites(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?), (?, ?)',
            ('hero.png', 0, 'mage.png', 1),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'compact-favorites.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', None)
    monkeypatch.setattr('core.services.user_db_backup_service.sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path) if card_id == 'hero.png' else '',
    )

    result = UserDbBackupService().import_backup(str(backup_file), source_name='compact-favorites.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 1},
        {'id': 'mage.png', 'is_favorite': 1},
    ]
    assert result['stats']['favorites'] == {
        'imported': 1,
        'skipped_missing_cards': 0,
        'unchanged': 0,
    }
    assert result['stats']['wi_clipboard'] == {'imported': 0, 'deduplicated': 0}
    assert result['stats']['wi_entry_history'] == {'imported': 0, 'deduplicated': 0, 'trimmed': 0}


def test_import_backup_accepts_legacy_full_favorites_snapshot(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?), (?, ?)',
            ('hero.png', 0, 'mage.png', 1),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
                {'card_id': 'mage.png', 'is_favorite': False},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'legacy-full-favorites.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', None)
    monkeypatch.setattr('core.services.user_db_backup_service.sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, _card_id: '',
    )

    result = UserDbBackupService().import_backup(str(backup_file), source_name='legacy-full-favorites.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 1},
        {'id': 'mage.png', 'is_favorite': 0},
    ]
    assert result['stats']['favorites'] == {
        'imported': 2,
        'skipped_missing_cards': 0,
        'unchanged': 0,
    }
    assert result['stats']['wi_clipboard'] == {'imported': 0, 'deduplicated': 0}
    assert result['stats']['wi_entry_history'] == {'imported': 0, 'deduplicated': 0, 'trimmed': 0}


def test_import_backup_skips_history_when_table_is_missing(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables_without_history(conn)
        conn.execute('INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?)', ('hero.png', 0))
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
            (json.dumps({'text': 'existing'}, ensure_ascii=False), 0, 10.0),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [
                {'content': {'text': 'imported'}, 'sort_order': 99, 'created_at': 11.0},
            ],
            'wi_entry_history': [
                {
                    'scope_key': 'scope-a',
                    'entry_uid': 'entry-1',
                    'snapshot_json': json.dumps({'value': 'imported'}, ensure_ascii=False),
                    'snapshot_hash': 'hash-imported',
                    'created_at': 12.0,
                },
            ],
        },
    }
    backup_file = tmp_path / 'missing-history-import.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', None)
    monkeypatch.setattr('core.services.user_db_backup_service.sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path),
    )

    result = UserDbBackupService().import_backup(str(backup_file), source_name='missing-history-import.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')
        clipboard = _fetch_all(
            conn,
            'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC',
        )

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 1},
    ]
    assert clipboard == [
        {
            'content_json': json.dumps({'text': 'existing'}, ensure_ascii=False),
            'sort_order': 0,
            'created_at': 10.0,
        },
        {
            'content_json': json.dumps({'text': 'imported'}, ensure_ascii=False),
            'sort_order': 1,
            'created_at': 11.0,
        },
    ]
    assert result['stats']['favorites'] == {
        'imported': 1,
        'skipped_missing_cards': 0,
        'unchanged': 0,
    }
    assert result['stats']['wi_clipboard'] == {'imported': 1, 'deduplicated': 0}
    assert result['stats']['wi_entry_history'] == {'imported': 0, 'deduplicated': 0, 'trimmed': 0}


def test_import_backup_reverts_favorite_db_state_when_side_effect_fails(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute('INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?)', ('hero.png', 0))
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'favorites-retry.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    cache_calls = []
    sync_calls = []
    apply_calls = []

    class _FakeCache:
        def toggle_favorite_update(self, card_id, value):
            cache_calls.append((card_id, value))

    def _failing_apply(card_id, favorite_source_path):
        apply_calls.append((card_id, favorite_source_path))
        raise RuntimeError('apply failed')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', _FakeCache())
    monkeypatch.setattr(
        'core.services.user_db_backup_service.sync_card_index_jobs',
        lambda **kwargs: sync_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        _failing_apply,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path),
    )

    with pytest.raises(RuntimeError, match='apply failed'):
        UserDbBackupService().import_backup(str(backup_file), source_name='favorites-retry.json')

    with _open_db(db_path) as conn:
        favorites_after_failure = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites_after_failure == [
        {'id': 'hero.png', 'is_favorite': 0},
    ]
    assert cache_calls == [('hero.png', True), ('hero.png', False)]
    assert sync_calls == [
        {
            'card_id': 'hero.png',
            'source_path': str(source_path),
            'favorite_changed': True,
        },
        {
            'card_id': 'hero.png',
            'source_path': str(source_path),
            'favorite_changed': True,
        }
    ]
    assert apply_calls == [
        ('hero.png', str(source_path)),
        ('hero.png', str(source_path)),
    ]

    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda card_id, favorite_source_path: apply_calls.append((card_id, favorite_source_path)),
    )

    result = UserDbBackupService().import_backup(str(backup_file), source_name='favorites-retry.json')

    with _open_db(db_path) as conn:
        favorites_after_retry = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites_after_retry == [
        {'id': 'hero.png', 'is_favorite': 1},
    ]
    assert result['stats']['favorites'] == {
        'imported': 1,
        'skipped_missing_cards': 0,
        'unchanged': 0,
    }


def test_import_backup_compensates_started_favorite_side_effects_for_multi_card_failure(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    cards_dir = tmp_path / 'cards'
    hero_path = cards_dir / 'hero.png'
    mage_path = cards_dir / 'mage.png'
    cards_dir.mkdir(parents=True, exist_ok=True)
    hero_path.write_text('hero', encoding='utf-8')
    mage_path.write_text('mage', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?), (?, ?)',
            ('hero.png', 0, 'mage.png', 0),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
                {'card_id': 'mage.png', 'is_favorite': True},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'favorites-multi-retry.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    cache_calls = []
    sync_calls = []
    apply_calls = []
    apply_failures = {'mage.png': 1}

    class _FakeCache:
        def toggle_favorite_update(self, card_id, value):
            cache_calls.append((card_id, value))

    def _apply_with_partial_failure(card_id, favorite_source_path):
        apply_calls.append((card_id, favorite_source_path))
        if apply_failures.get(card_id, 0) > 0:
            apply_failures[card_id] -= 1
            raise RuntimeError(f'apply failed for {card_id}')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', _FakeCache())
    monkeypatch.setattr(
        'core.services.user_db_backup_service.sync_card_index_jobs',
        lambda **kwargs: sync_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        _apply_with_partial_failure,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(hero_path if card_id == 'hero.png' else mage_path),
    )

    with pytest.raises(RuntimeError, match='apply failed for mage.png'):
        UserDbBackupService().import_backup(str(backup_file), source_name='favorites-multi-retry.json')

    with _open_db(db_path) as conn:
        favorites_after_failure = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')

    assert favorites_after_failure == [
        {'id': 'hero.png', 'is_favorite': 0},
        {'id': 'mage.png', 'is_favorite': 0},
    ]
    assert cache_calls == [
        ('hero.png', True),
        ('mage.png', True),
        ('hero.png', False),
        ('mage.png', False),
    ]
    assert sync_calls == [
        {
            'card_id': 'hero.png',
            'source_path': str(hero_path),
            'favorite_changed': True,
        },
        {
            'card_id': 'mage.png',
            'source_path': str(mage_path),
            'favorite_changed': True,
        },
        {
            'card_id': 'mage.png',
            'source_path': str(mage_path),
            'favorite_changed': True,
        },
        {
            'card_id': 'hero.png',
            'source_path': str(hero_path),
            'favorite_changed': True,
        },
    ]
    assert apply_calls == [
        ('hero.png', str(hero_path)),
        ('mage.png', str(mage_path)),
        ('mage.png', str(mage_path)),
        ('hero.png', str(hero_path)),
    ]


def test_import_backup_failed_favorite_rollback_restores_real_index_projection(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService
    from core.services import user_db_backup_service as backup_module
    from core.services.card_service import _apply_card_index_increment_now as real_apply_card_index_increment_now

    db_path = tmp_path / 'app.db'
    card_path = tmp_path / 'cards' / 'hero.png'
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        ensure_index_runtime_schema(conn)
        _create_card_index_metadata_table(conn)
        conn.execute(
            '''
            CREATE TABLE wi_clipboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_json TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE wi_entry_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_key TEXT NOT NULL,
                entry_uid TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            '''
        )
        _seed_card_index_projection(
            conn,
            card_id='hero.png',
            source_path=card_path,
            favorite=0,
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [],
            'wi_entry_history': [],
        },
    }
    backup_file = tmp_path / 'favorites-proof.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    class _FakeCache:
        def toggle_favorite_update(self, *_args, **_kwargs):
            return None

    apply_failures = {'remaining': 1}

    def _fail_once_then_real_apply(card_id, favorite_source_path):
        if apply_failures['remaining'] > 0:
            apply_failures['remaining'] -= 1
            raise RuntimeError('apply failed once')
        return real_apply_card_index_increment_now(card_id, favorite_source_path)

    monkeypatch.setattr(backup_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(backup_module.ctx, 'cache', _FakeCache())
    monkeypatch.setattr(backup_module, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(backup_module, '_apply_card_index_increment_now', _fail_once_then_real_apply)
    monkeypatch.setattr(
        backup_module.UserDbBackupService,
        '_resolve_card_source_path',
        lambda self, card_id: str(card_path),
    )

    with pytest.raises(RuntimeError, match='apply failed once'):
        UserDbBackupService().import_backup(str(backup_file), source_name='favorites-proof.json')

    with _open_db(db_path) as conn:
        favorite_row = conn.execute(
            'SELECT is_favorite FROM card_metadata WHERE id = ?',
            ('hero.png',),
        ).fetchone()

    indexed = query_indexed_cards({
        'db_path': str(db_path),
        'page': 1,
        'page_size': 20,
    })

    assert favorite_row['is_favorite'] == 0
    assert [item['id'] for item in indexed['cards']] == ['hero.png']
    assert indexed['cards'][0]['is_favorite'] == 0


def test_import_backup_post_commit_favorite_failure_restores_all_db_only_modules(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute('INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?)', ('hero.png', 0))
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
            (json.dumps({'text': 'existing'}, ensure_ascii=False), 0, 10.0),
        )
        conn.execute(
            'INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at) VALUES (?, ?, ?, ?, ?)',
            ('scope-a', 'entry-1', json.dumps({'value': 'existing'}, ensure_ascii=False), 'hash-existing', 20.0),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [
                {'content': {'text': 'imported'}, 'sort_order': 99, 'created_at': 30.0},
            ],
            'wi_entry_history': [
                {
                    'scope_key': 'scope-a',
                    'entry_uid': 'entry-1',
                    'snapshot_json': json.dumps({'value': 'imported'}, ensure_ascii=False),
                    'snapshot_hash': 'hash-imported',
                    'created_at': 40.0,
                },
            ],
        },
    }
    backup_file = tmp_path / 'mixed-failure.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    cache_calls = []
    sync_calls = []
    apply_calls = []

    class _FakeCache:
        def toggle_favorite_update(self, card_id, value):
            cache_calls.append((card_id, value))

    def _failing_apply(card_id, favorite_source_path):
        apply_calls.append((card_id, favorite_source_path))
        raise RuntimeError('apply failed')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', _FakeCache())
    monkeypatch.setattr(
        'core.services.user_db_backup_service.sync_card_index_jobs',
        lambda **kwargs: sync_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        _failing_apply,
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path),
    )

    with pytest.raises(RuntimeError, match='apply failed'):
        UserDbBackupService().import_backup(str(backup_file), source_name='mixed-failure.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')
        clipboard = _fetch_all(
            conn,
            'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC',
        )
        history = _fetch_all(
            conn,
            '''
            SELECT scope_key, entry_uid, snapshot_json, snapshot_hash, created_at
            FROM wi_entry_history
            ORDER BY created_at ASC, id ASC
            ''',
        )

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 0},
    ]
    assert clipboard == [
        {
            'content_json': json.dumps({'text': 'existing'}, ensure_ascii=False),
            'sort_order': 0,
            'created_at': 10.0,
        },
    ]
    assert history == [
        {
            'scope_key': 'scope-a',
            'entry_uid': 'entry-1',
            'snapshot_json': json.dumps({'value': 'existing'}, ensure_ascii=False),
            'snapshot_hash': 'hash-existing',
            'created_at': 20.0,
        },
    ]
    assert cache_calls == [('hero.png', True), ('hero.png', False)]
    assert sync_calls == [
        {
            'card_id': 'hero.png',
            'source_path': str(source_path),
            'favorite_changed': True,
        },
        {
            'card_id': 'hero.png',
            'source_path': str(source_path),
            'favorite_changed': True,
        },
    ]
    assert apply_calls == [
        ('hero.png', str(source_path)),
        ('hero.png', str(source_path)),
    ]


def test_import_backup_rollback_tolerates_missing_history_table(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    source_path = tmp_path / 'cards' / 'hero.png'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('hero', encoding='utf-8')

    with _open_db(db_path) as conn:
        _create_tables_without_history(conn)
        conn.execute('INSERT INTO card_metadata (id, is_favorite) VALUES (?, ?)', ('hero.png', 0))
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
            (json.dumps({'text': 'existing'}, ensure_ascii=False), 0, 10.0),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [
                {'card_id': 'hero.png', 'is_favorite': True},
            ],
            'wi_clipboard': [
                {'content': {'text': 'imported'}, 'sort_order': 99, 'created_at': 11.0},
            ],
            'wi_entry_history': [
                {
                    'scope_key': 'scope-a',
                    'entry_uid': 'entry-1',
                    'snapshot_json': json.dumps({'value': 'imported'}, ensure_ascii=False),
                    'snapshot_hash': 'hash-imported',
                    'created_at': 12.0,
                },
            ],
        },
    }
    backup_file = tmp_path / 'missing-history-rollback.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    cache_calls = []

    class _FakeCache:
        def toggle_favorite_update(self, card_id, value):
            cache_calls.append((card_id, value))

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.ctx.cache', _FakeCache())
    monkeypatch.setattr('core.services.user_db_backup_service.sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(
        'core.services.user_db_backup_service._apply_card_index_increment_now',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('apply failed')),
    )
    monkeypatch.setattr(
        'core.services.user_db_backup_service.UserDbBackupService._resolve_card_source_path',
        lambda self, card_id: str(source_path),
    )

    with pytest.raises(RuntimeError, match='apply failed'):
        UserDbBackupService().import_backup(str(backup_file), source_name='missing-history-rollback.json')

    with _open_db(db_path) as conn:
        favorites = _fetch_all(conn, 'SELECT id, is_favorite FROM card_metadata ORDER BY id')
        clipboard = _fetch_all(
            conn,
            'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC',
        )

    assert favorites == [
        {'id': 'hero.png', 'is_favorite': 0},
    ]
    assert clipboard == [
        {
            'content_json': json.dumps({'text': 'existing'}, ensure_ascii=False),
            'sort_order': 0,
            'created_at': 10.0,
        },
    ]
    assert cache_calls == [('hero.png', True), ('hero.png', False)]


def test_import_backup_deduplicates_clipboard_and_history_and_trims_history(tmp_path, monkeypatch):
    from core.services.user_db_backup_service import UserDbBackupService

    db_path = tmp_path / 'app.db'
    with _open_db(db_path) as conn:
        _create_tables(conn)
        conn.execute(
            'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
            (json.dumps({'text': 'alpha'}, ensure_ascii=False), 4, 10.0),
        )
        conn.execute(
            'INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at) VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?)',
            (
                'scope-a',
                'entry-1',
                json.dumps({'value': 'old-1'}, ensure_ascii=False),
                'old-hash-1',
                1.0,
                'scope-a',
                'entry-1',
                json.dumps({'value': 'old-2'}, ensure_ascii=False),
                'old-hash-2',
                2.0,
            ),
        )
        conn.commit()

    payload = {
        'schema_version': 1,
        'exported_at': '2026-04-26T10:00:00Z',
        'app': 'ST-Manager',
        'data': {
            'favorites': [],
            'wi_clipboard': [
                {'content': {'text': 'alpha'}, 'sort_order': 99, 'created_at': 20.0},
                {'content': {'text': 'beta'}, 'sort_order': 1, 'created_at': 21.0},
            ],
            'wi_entry_history': [
                {
                    'scope_key': 'scope-a',
                    'entry_uid': 'entry-1',
                    'snapshot_json': json.dumps({'value': 'old-2'}, ensure_ascii=False),
                    'snapshot_hash': 'old-hash-2',
                    'created_at': 3.0,
                },
                {
                    'scope_key': 'scope-a',
                    'entry_uid': 'entry-1',
                    'snapshot_json': json.dumps({'value': 'newest'}, ensure_ascii=False),
                    'snapshot_hash': 'new-hash',
                    'created_at': 4.0,
                },
            ],
        },
    }
    backup_file = tmp_path / 'clipboard-history.json'
    backup_file.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr('core.services.user_db_backup_service.DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr('core.services.user_db_backup_service.get_history_limit', lambda: 2)

    result = UserDbBackupService().import_backup(str(backup_file), source_name='clipboard-history.json')

    with _open_db(db_path) as conn:
        clipboard = _fetch_all(
            conn,
            'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC',
        )
        history = _fetch_all(
            conn,
            '''
            SELECT scope_key, entry_uid, snapshot_json, snapshot_hash, created_at
            FROM wi_entry_history
            ORDER BY created_at ASC, id ASC
            ''',
        )

    assert result['stats']['wi_clipboard'] == {'imported': 1, 'deduplicated': 1}
    assert result['stats']['wi_entry_history'] == {'imported': 1, 'deduplicated': 1, 'trimmed': 1}
    assert clipboard == [
        {
            'content_json': json.dumps({'text': 'alpha'}, ensure_ascii=False),
            'sort_order': 0,
            'created_at': 10.0,
        },
        {
            'content_json': json.dumps({'text': 'beta'}, ensure_ascii=False),
            'sort_order': 1,
            'created_at': 21.0,
        },
    ]
    assert history == [
        {
            'scope_key': 'scope-a',
            'entry_uid': 'entry-1',
            'snapshot_json': json.dumps({'value': 'old-2'}, ensure_ascii=False),
            'snapshot_hash': 'old-hash-2',
            'created_at': 2.0,
        },
        {
            'scope_key': 'scope-a',
            'entry_uid': 'entry-1',
            'snapshot_json': json.dumps({'value': 'newest'}, ensure_ascii=False),
            'snapshot_hash': 'new-hash',
            'created_at': 4.0,
        },
    ]


def test_import_backup_rejects_unsupported_schema_version(tmp_path):
    from core.services.user_db_backup_service import UserDbBackupService

    backup_file = tmp_path / 'bad-schema.json'
    backup_file.write_text(
        json.dumps(
            {
                'schema_version': 99,
                'exported_at': '2026-04-26T10:00:00Z',
                'app': 'ST-Manager',
                'data': {
                    'favorites': [],
                    'wi_clipboard': [],
                    'wi_entry_history': [],
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='schema_version'):
        UserDbBackupService().import_backup(str(backup_file))


def test_import_backup_rejects_non_boolean_favorite_values(tmp_path):
    from core.services.user_db_backup_service import UserDbBackupService

    backup_file = tmp_path / 'bad-favorite.json'
    backup_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'exported_at': '2026-04-26T10:00:00Z',
                'app': 'ST-Manager',
                'data': {
                    'favorites': [
                        {'card_id': 'hero.png', 'is_favorite': 'false'},
                    ],
                    'wi_clipboard': [],
                    'wi_entry_history': [],
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match='is_favorite'):
        UserDbBackupService().import_backup(str(backup_file))


def test_import_backup_rejects_malformed_json(tmp_path):
    from core.services.user_db_backup_service import UserDbBackupService

    backup_file = tmp_path / 'bad-json.json'
    backup_file.write_text('{not-valid-json', encoding='utf-8')

    with pytest.raises(ValueError, match='合法 JSON'):
        UserDbBackupService().import_backup(str(backup_file))
