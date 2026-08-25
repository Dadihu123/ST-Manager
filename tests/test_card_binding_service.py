import sqlite3
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_rename_card_ui_references_merges_chat_ids_and_preserves_special_records():
    from core.services.card_binding_service import rename_card_ui_references

    ui_data = {
        'old/hero.png': {
            'summary': 'old summary',
            'chat_ids': ['Hero/one.jsonl', 'Hero/two.jsonl'],
        },
        'new/hero.png': {
            'link': 'https://example.test/card',
            'chat_ids': ['Hero/two.jsonl', 'Hero/three.jsonl'],
        },
        '_worldinfo_notes_v1': {
            'embedded::old/hero.png': {'summary': 'keep owner-specific migration separate'},
        },
    }

    assert rename_card_ui_references(ui_data, 'old/hero.png', 'new/hero.png') is True

    assert 'old/hero.png' not in ui_data
    assert ui_data['new/hero.png'] == {
        'link': 'https://example.test/card',
        'summary': 'old summary',
        'chat_ids': [
            'Hero/two.jsonl',
            'Hero/three.jsonl',
            'Hero/one.jsonl',
        ],
    }
    assert '_worldinfo_notes_v1' in ui_data


def test_rename_card_ui_references_moves_nested_folder_bindings():
    from core.services.card_binding_service import rename_card_ui_references

    ui_data = {
        'old-pack': {'chat_ids': ['Hero/folder.jsonl']},
        'old-pack/hero.png': {'chat_ids': ['Hero/card.jsonl']},
        'old-pack/other.png': {'summary': 'other'},
        'old-pack-archive/hero.png': {'chat_ids': ['Hero/keep.jsonl']},
    }

    assert rename_card_ui_references(
        ui_data,
        'old-pack',
        'new-pack',
        recursive=True,
    ) is True

    assert ui_data['new-pack']['chat_ids'] == ['Hero/folder.jsonl']
    assert ui_data['new-pack/hero.png']['chat_ids'] == ['Hero/card.jsonl']
    assert ui_data['new-pack/other.png']['summary'] == 'other'
    assert 'old-pack/hero.png' not in ui_data
    assert 'old-pack-archive/hero.png' in ui_data


def test_reconcile_stale_card_bindings_is_recoverable():
    from core.services.card_binding_service import (
        STALE_CARD_BINDINGS_KEY,
        reconcile_stale_card_bindings,
    )

    ui_data = {
        'old/hero.png': {
            'summary': 'keep this metadata',
            'chat_ids': ['Hero/chat.jsonl'],
        },
        'current/hero.png': {'chat_ids': ['Hero/current.jsonl']},
    }

    assert reconcile_stale_card_bindings(ui_data, {'current/hero.png'}) is True
    assert 'chat_ids' not in ui_data['old/hero.png']
    assert ui_data[STALE_CARD_BINDINGS_KEY]['old/hero.png']['chat_ids'] == [
        'Hero/chat.jsonl',
    ]
    assert ui_data[STALE_CARD_BINDINGS_KEY]['old/hero.png']['entry'] == {
        'summary': 'keep this metadata',
    }


def test_reconcile_stale_card_bindings_restores_by_uuid():
    from core.services.card_binding_service import (
        CARD_UID_FIELD,
        reconcile_stale_card_bindings,
    )

    stable_uid = '12345678-1234-5678-1234-567812345678'
    ui_data = {
        'old/hero.png': {
            CARD_UID_FIELD: stable_uid,
            'chat_ids': ['Hero/chat.jsonl'],
        },
    }

    assert reconcile_stale_card_bindings(
        ui_data,
        {'current/hero.png'},
        card_uid_by_ui_key={'current/hero.png': stable_uid},
    ) is True
    assert 'old/hero.png' not in ui_data
    assert ui_data['current/hero.png']['chat_ids'] == ['Hero/chat.jsonl']
    assert ui_data['current/hero.png'][CARD_UID_FIELD] == stable_uid


def test_reconcile_stale_store_restores_by_uuid():
    from core.services.card_binding_service import (
        CARD_UID_FIELD,
        STALE_CARD_BINDINGS_KEY,
        reconcile_stale_card_bindings,
    )

    stable_uid = '12345678-1234-5678-1234-567812345678'
    ui_data = {
        STALE_CARD_BINDINGS_KEY: {
            'old/hero.png': {
                CARD_UID_FIELD: stable_uid,
                'chat_ids': ['Hero/chat.jsonl'],
                'entry': {'summary': 'old note'},
            },
        },
    }

    assert reconcile_stale_card_bindings(
        ui_data,
        {'current/hero.png'},
        card_uid_by_ui_key={'current/hero.png': stable_uid},
    ) is True
    assert ui_data['current/hero.png']['summary'] == 'old note'
    assert ui_data['current/hero.png']['chat_ids'] == ['Hero/chat.jsonl']
    assert STALE_CARD_BINDINGS_KEY not in ui_data


def test_chat_binding_does_not_resolve_stale_card_key(monkeypatch):
    from core.api.v1 import chats as chats_api

    fake_cache = SimpleNamespace(
        initialized=True,
        id_map={
            'current/hero.png': {
                'id': 'current/hero.png',
                'char_name': 'Hero',
                'category': 'current',
                'is_bundle': False,
            },
        },
        bundle_map={},
    )
    monkeypatch.setattr(chats_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(
        chats_api,
        'resolve_ui_key',
        lambda card_id: str(card_id).replace('\\', '/'),
    )

    ui_data = {
        'old/hero.png': {'chat_ids': ['Hero/chat.jsonl']},
        'current/hero.png': {'chat_ids': ['Hero/current.jsonl']},
    }

    assert chats_api._build_binding_info(ui_data, 'Hero/chat.jsonl') == []
    assert chats_api._build_binding_info(ui_data, 'Hero/current.jsonl') == [
        {
            'ui_key': 'current/hero.png',
            'card_id': 'current/hero.png',
            'card_name': 'Hero',
            'category': 'current',
            'is_bundle': False,
        },
    ]


def test_chat_binding_uses_bundle_ui_key_and_keeps_chat_ids(monkeypatch):
    from core.api.v1 import chats as chats_api

    fake_cache = SimpleNamespace(
        initialized=True,
        id_map={
            'bundle/hero-v2.png': {
                'id': 'bundle/hero-v2.png',
                'char_name': 'Hero',
                'category': '',
                'is_bundle': True,
            },
        },
        bundle_map={'bundle': 'bundle/hero-v2.png'},
    )
    monkeypatch.setattr(chats_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(
        chats_api,
        'resolve_ui_key',
        lambda card_id: 'bundle' if card_id.startswith('bundle/') else card_id,
    )

    ui_data = {'bundle': {'chat_ids': ['Hero/existing.jsonl']}}
    changed, bindings = chats_api._bind_chat_to_card(
        ui_data,
        'Hero/new.jsonl',
        'bundle/hero-v2.png',
    )

    assert changed is True
    assert ui_data['bundle']['chat_ids'] == [
        'Hero/existing.jsonl',
        'Hero/new.jsonl',
    ]
    assert bindings[0]['ui_key'] == 'bundle'
    assert bindings[0]['card_id'] == 'bundle/hero-v2.png'


def test_watchdog_card_move_migrates_chat_binding(monkeypatch, tmp_path):
    from core.services import scan_service

    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    new_card_path = cards_dir / 'renamed' / 'new-name.png'
    new_card_path.parent.mkdir(parents=True)
    new_card_path.write_bytes(b'new')

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0
            )
            ''',
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, category, last_modified, file_size, is_favorite) VALUES (?, ?, ?, ?, ?, ?)',
            ('old-name.png', 'Hero', '', 10.0, 3, 1),
        )
        conn.commit()

    saved = []
    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        scan_service,
        'extract_card_info',
        lambda _path: {'data': {'name': 'Hero', 'tags': []}},
    )
    monkeypatch.setattr(scan_service, 'calculate_token_count', lambda _payload: 222)
    monkeypatch.setattr(scan_service, 'get_wi_meta', lambda _payload: (False, ''))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: None)
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: None)

    ui_data = {'old-name.png': {'chat_ids': ['Hero/chat.jsonl']}}
    monkeypatch.setattr(scan_service, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(
        scan_service,
        'save_ui_data',
        lambda payload: saved.append(payload) or True,
    )

    assert scan_service._process_card_move_task('old-name.png', str(new_card_path)) is True
    assert saved[-1]['renamed/new-name.png']['chat_ids'] == ['Hero/chat.jsonl']
    assert 'old-name.png' not in saved[-1]


def test_full_scan_renamed_file_reuses_uuid_and_chat_binding(monkeypatch, tmp_path):
    from core.services import scan_service

    stable_uid = '12345678-1234-5678-1234-567812345678'
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    new_card_path = cards_dir / 'renamed' / 'hero.png'
    new_card_path.parent.mkdir(parents=True)
    new_card_path.write_bytes(b'new')

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0,
                card_uid TEXT
            )
            ''',
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, category, last_modified, file_hash, file_size, token_count, is_favorite, card_uid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('old/hero.png', 'Hero', 'old', 10.0, 'same-hash', 3, 7, 1, stable_uid),
        )
        conn.commit()

    saved = []
    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        scan_service,
        'extract_card_info',
        lambda _path: {'data': {'name': 'Hero', 'tags': ['blue']}},
    )
    monkeypatch.setattr(scan_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(scan_service, 'get_wi_meta', lambda _payload: (False, ''))
    monkeypatch.setattr(
        scan_service,
        'get_file_hash_and_size',
        lambda _path: ('same-hash', 3),
    )
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: None)
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: None)
    ui_data = {
        'old/hero.png': {
            'card_uid': stable_uid,
            'chat_ids': ['Hero/chat.jsonl'],
        },
    }
    monkeypatch.setattr(scan_service, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(
        scan_service,
        'save_ui_data',
        lambda payload: saved.append(json.loads(json.dumps(payload))) or True,
    )

    scan_service._perform_scan_logic()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT id, card_uid FROM card_metadata ORDER BY id',
        ).fetchone()
    assert row == ('renamed/hero.png', stable_uid)
    assert saved[-1]['renamed/hero.png']['chat_ids'] == ['Hero/chat.jsonl']
    assert 'old/hero.png' not in saved[-1]


def test_init_database_backfills_card_uid_for_existing_cards(monkeypatch, tmp_path):
    from core.data import db_session
    from core.utils.card_identity import normalize_card_uid

    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0
            )
            ''',
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name) VALUES (?, ?)',
            ('hero.png', 'Hero'),
        )
        conn.commit()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda _conn: None)

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(card_metadata)')}
        raw_uid = conn.execute(
            'SELECT card_uid FROM card_metadata WHERE id = ?',
            ('hero.png',),
        ).fetchone()[0]

    assert 'card_uid' in columns
    assert normalize_card_uid(raw_uid) == raw_uid
