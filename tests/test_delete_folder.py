import sys
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import ANY

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import cards as cards_api
from core.data import db_session as db_session_module
from core.data import ui_store as ui_store_module
from core.context import ctx
from core.services import card_service


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def _init_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS card_metadata (
            id TEXT PRIMARY KEY,
            category TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_card_meta(db_path: Path, *, card_id: str, category: str):
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO card_metadata (id, category) VALUES (?, ?)",
        (card_id, category),
    )
    conn.commit()
    conn.close()


def _read_ui_data(ui_path: Path):
    if not ui_path.exists():
        return {}
    return json.loads(ui_path.read_text(encoding='utf-8'))


@pytest.fixture()
def folder_fixture(tmp_path):
    cards_dir = tmp_path / 'cards'
    trash_dir = tmp_path / 'trash'
    db_path = tmp_path / 'db.sqlite'
    ui_path = tmp_path / 'ui_data.json'

    cards_dir.mkdir(parents=True, exist_ok=True)
    trash_dir.mkdir(parents=True, exist_ok=True)

    _init_db(db_path)

    # 文件结构：
    # cards/testA/a.png
    # cards/testA/sub/b.png
    (cards_dir / 'testA' / 'sub').mkdir(parents=True, exist_ok=True)
    (cards_dir / 'testA' / 'a.png').write_bytes(b'png')
    (cards_dir / 'testA' / 'sub' / 'b.png').write_bytes(b'png')

    _insert_card_meta(db_path, card_id='testA/a.png', category='testA')
    _insert_card_meta(db_path, card_id='testA/sub/b.png', category='testA/sub')

    ui_path.write_text(
        json.dumps(
            {
                'testA/a.png': {'summary': 'a'},
                'testA/sub/b.png': {'summary': 'b'},
                'testA/sub': {'summary': 'bundle-sub'},
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    return {
        'cards_dir': cards_dir,
        'trash_dir': trash_dir,
        'db_path': db_path,
        'ui_path': ui_path,
    }


def test_delete_folder_dissolve_moves_children(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'schedule_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)

    # 避免增量缓存对测试结果产生干扰
    ctx.cache.visible_folders = ['testA']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA'})
    payload = res.get_json()

    assert payload['success'] is True
    assert payload['moved_count'] == 2

    # filesystem: 内容移动到上一级目录，testA 被删除
    assert not (cards_dir / 'testA').exists()
    assert (cards_dir / 'a.png').exists()
    assert (cards_dir / 'sub').is_dir()
    assert (cards_dir / 'sub' / 'b.png').exists()

    # db: id / category 按移动规则更新
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM card_metadata")
    ids = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert ids == {'a.png', 'sub/b.png'}

    # ui_data: key 按移动规则更新
    ui_after = _read_ui_data(ui_path)
    assert 'testA/a.png' not in ui_after
    assert 'a.png' in ui_after
    assert 'testA/sub' not in ui_after
    assert 'sub' in ui_after


def test_delete_folder_dissolve_delegates_post_move_sync(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    exact_sync_calls = []
    folder_sync_calls = []
    update_cache_calls = []
    sync_index_calls = []

    def _record_exact_sync(**kwargs):
        exact_sync_calls.append(kwargs.copy())
        return card_service.sync_exact_card_after_fs_move(**kwargs)

    def _record_folder_sync(**kwargs):
        folder_sync_calls.append(kwargs.copy())
        return card_service.sync_folder_prefix_after_fs_move(**kwargs)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'schedule_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'sync_exact_card_after_fs_move', _record_exact_sync, raising=False)
    monkeypatch.setattr(cards_api, 'sync_folder_prefix_after_fs_move', _record_folder_sync, raising=False)
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: update_cache_calls.append(
            {'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}
        ) or {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        },
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: sync_index_calls.append(kwargs) or {},
    )

    ctx.cache.visible_folders = ['testA']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert exact_sync_calls == [
        {
            'conn': ANY,
            'ui_data': ANY,
            'old_card_id': 'testA/a.png',
            'new_card_id': 'a.png',
            'dst_full_path': str(cards_dir / 'a.png'),
            'final_name': 'a.png',
            'old_category': 'testA',
        }
    ]
    assert folder_sync_calls == [
        {
            'conn': ANY,
            'ui_data': ANY,
            'old_path': 'testA/sub',
            'new_path': 'sub',
        }
    ]

    assert update_cache_calls == [
        {
            'card_id': 'a.png',
            'full_path': str(cards_dir / 'a.png'),
            'kwargs': {'remove_entity_ids': ['testA/a.png']},
        },
        {
            'card_id': 'sub/b.png',
            'full_path': str(cards_dir / 'sub' / 'b.png'),
            'kwargs': {'remove_entity_ids': ['testA/sub/b.png']},
        },
    ]
    assert sync_index_calls == [
        {
            'card_id': 'a.png',
            'source_path': str(cards_dir / 'a.png'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['testA/a.png'],
            'remove_owner_ids': ['testA/a.png'],
        },
        {
            'card_id': 'sub/b.png',
            'source_path': str(cards_dir / 'sub' / 'b.png'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['testA/sub/b.png'],
            'remove_owner_ids': ['testA/sub/b.png'],
        },
    ]


def test_delete_folder_dissolve_schedules_fallback_reload_when_shared_sync_fails(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    schedule_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('sync failed')),
        raising=False,
    )

    ctx.cache.visible_folders = ['testA']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'mode': 'dissolve',
        'moved_count': 2,
        'warning': '文件夹已解散，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'delete_folder:fallback'}]
    assert (cards_dir / 'a.png').exists()
    assert (cards_dir / 'sub').is_dir()
    assert (cards_dir / 'sub' / 'b.png').exists()
    assert (cards_dir / 'testA').is_dir()
    assert list((cards_dir / 'testA').iterdir()) == []


def test_delete_folder_dissolve_returns_warning_when_partial_moves_then_sync_fails(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    schedule_calls = []
    exact_sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: (exact_sync_calls.append(kwargs), None)[1],
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('sync failed')),
        raising=False,
    )

    ctx.cache.visible_folders = ['testA']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'mode': 'dissolve',
        'moved_count': 2,
        'warning': '文件夹已解散，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'delete_folder:fallback'}]
    assert len(exact_sync_calls) == 1
    assert (cards_dir / 'a.png').exists()
    assert (cards_dir / 'sub').is_dir()
    assert (cards_dir / 'sub' / 'b.png').exists()
    assert (cards_dir / 'testA').is_dir()
    assert list((cards_dir / 'testA').iterdir()) == []


def test_delete_folder_dissolve_returns_warning_when_partial_move_fails(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    schedule_calls = []
    exact_sync_calls = []
    folder_sync_calls = []
    real_listdir = cards_api.os.listdir
    real_move = cards_api.shutil.move
    move_attempts = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: exact_sync_calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **kwargs: folder_sync_calls.append(kwargs),
        raising=False,
    )

    def _ordered_listdir(path):
        if Path(path) == cards_dir / 'testA':
            return ['a.png', 'sub']
        return real_listdir(path)

    def _move_with_second_failure(src, dst, *args, **kwargs):
        move_attempts.append((src, dst))
        if len(move_attempts) == 2:
            raise RuntimeError('move failed')
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr(cards_api.os, 'listdir', _ordered_listdir)
    monkeypatch.setattr(cards_api.shutil, 'move', _move_with_second_failure)

    ctx.cache.visible_folders = ['testA']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'mode': 'dissolve',
        'moved_count': 1,
        'failed_count': 1,
        'warning': '文件夹已部分解散，已移动 1 个项目，另有 1 个项目处理失败，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'delete_folder:fallback'}]
    assert exact_sync_calls == []
    assert folder_sync_calls == []
    assert (cards_dir / 'a.png').exists() is True
    assert (cards_dir / 'testA').is_dir() is True
    assert (cards_dir / 'testA' / 'sub' / 'b.png').exists() is True
    assert any(path.name == 'sub' for path in (cards_dir / 'testA').iterdir())


def test_delete_folder_delete_children_recursive(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'schedule_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)

    # 可见文件夹列表包含子目录时也应被清理
    ctx.cache.visible_folders = ['testA', 'testA/sub']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA', 'delete_children': True})
    payload = res.get_json()

    assert payload['success'] is True
    assert payload['deleted_children'] is True
    assert payload['deleted_count'] == 2

    # filesystem: testA 不在 cards_dir，且被移动到 trash
    assert not (cards_dir / 'testA').exists()
    trash_entries = list(trash_dir.iterdir())
    assert len(trash_entries) == 1
    assert trash_entries[0].name.startswith('testA_')

    # db: 目录下的所有卡片元数据被删除
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM card_metadata")
    rows = cursor.fetchall()
    conn.close()
    assert rows == []

    # ui_data: 目录下的所有 UI keys 被删除
    ui_after = _read_ui_data(ui_path)
    assert ui_after == {}


def test_delete_folder_delete_children_dispatches_cleanup_and_clears_embedded_notes(monkeypatch, folder_fixture):
    cards_dir = folder_fixture['cards_dir']
    trash_dir = folder_fixture['trash_dir']
    db_path = folder_fixture['db_path']
    ui_path = folder_fixture['ui_path']

    ui_path.write_text(
        json.dumps(
            {
                'testA/a.png': {'summary': 'a'},
                'testA/sub/b.png': {'summary': 'b'},
                '_worldinfo_notes_v1': {
                    'embedded::testA/a.png': {'summary': 'embedded-a'},
                    'embedded::testA/sub/b.png': {'summary': 'embedded-b'},
                    'embedded::elsewhere/c.png': {'summary': 'keep-me'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    cleanup_calls = []

    def _cleanup_deleted_cards_after_fs_delete(*args, **kwargs):
        cleanup_calls.append(
            {
                'deleted_cards': args,
                'args': args,
                'kwargs': kwargs,
            }
        )
        return {'warnings': []}

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(db_session_module, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    monkeypatch.setattr(cards_api, 'schedule_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'force_reload', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cards_api,
        'cleanup_deleted_cards_after_fs_delete',
        _cleanup_deleted_cards_after_fs_delete,
        raising=False,
    )

    ctx.cache.visible_folders = ['testA', 'testA/sub']

    client = _make_test_app().test_client()
    res = client.post('/api/delete_folder', json={'folder_path': 'testA', 'delete_children': True})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['deleted_children'] is True
    assert payload['deleted_count'] == 2
    assert cleanup_calls == [
        {
            'deleted_cards': (),
            'args': (),
            'kwargs': {
                'deleted_card_ids': ['testA/a.png', 'testA/sub/b.png'],
                'source_paths_by_card_id': {
                    'testA/a.png': 'testA/a.png',
                    'testA/sub/b.png': 'testA/sub/b.png',
                },
            },
        }
    ]

    ui_after = _read_ui_data(ui_path)
    assert set(ui_after['_worldinfo_notes_v1'].keys()) == {'embedded::elsewhere/c.png'}
    assert ui_after['_worldinfo_notes_v1']['embedded::elsewhere/c.png']['summary'] == 'keep-me'


def test_delete_cards_cleans_embedded_worldinfo_notes(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    trash_dir = tmp_path / 'trash'
    db_path = tmp_path / 'db.sqlite'
    ui_path = tmp_path / 'ui_data.json'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / 'cards' / 'lucy.png'

    cards_dir.mkdir(parents=True, exist_ok=True)
    trash_dir.mkdir(parents=True, exist_ok=True)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'png')

    _init_db(db_path)
    _insert_card_meta(db_path, card_id=card_rel, category='cards')

    ui_path.write_text(
        json.dumps(
            {
                card_rel: {'summary': 'card note'},
                '_worldinfo_notes_v1': {
                    'embedded::cards/lucy.png': {'summary': 'embedded note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    class _FakeCache:
        def __init__(self):
            self.id_map = {card_rel: {'id': card_rel, 'is_bundle': False}}
            self.category_counts = {}

        def delete_card_update(self, _cid):
            return None

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(cards_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'load_config', lambda: {'resources_dir': 'resources'})
    monkeypatch.setattr(cards_api, 'get_db', lambda: sqlite3.connect(str(db_path)))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'resolve_ui_key', lambda cid: cid)
    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_test_app().test_client()
    res = client.post('/api/delete_cards', json={'card_ids': [card_rel], 'delete_resources': False})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    ui_after = _read_ui_data(ui_path)
    assert 'embedded::cards/lucy.png' not in ui_after.get('_worldinfo_notes_v1', {})


def test_delete_cards_dispatches_cleanup_after_successful_fs_delete(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    trash_dir = tmp_path / 'trash'
    db_path = tmp_path / 'db.sqlite'
    card_rel_a = 'cards/lucy.png'
    card_rel_b = 'cards/mio.png'
    card_path_a = cards_dir / 'cards' / 'lucy.png'
    card_path_b = cards_dir / 'cards' / 'mio.png'

    cards_dir.mkdir(parents=True, exist_ok=True)
    trash_dir.mkdir(parents=True, exist_ok=True)
    card_path_a.parent.mkdir(parents=True, exist_ok=True)
    card_path_a.write_bytes(b'a')
    card_path_b.write_bytes(b'b')

    _init_db(db_path)
    _insert_card_meta(db_path, card_id=card_rel_a, category='cards')
    _insert_card_meta(db_path, card_id=card_rel_b, category='cards')

    cleanup_calls = []

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                card_rel_a: {'id': card_rel_a, 'is_bundle': False},
                card_rel_b: {'id': card_rel_b, 'is_bundle': False},
            }
            self.category_counts = {}

        def delete_card_update(self, _cid):
            return None

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TRASH_FOLDER', str(trash_dir))
    monkeypatch.setattr(cards_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'load_config', lambda: {'resources_dir': 'resources'})
    monkeypatch.setattr(cards_api, 'get_db', lambda: sqlite3.connect(str(db_path)))
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(cards_api, 'resolve_ui_key', lambda cid: cid)
    monkeypatch.setattr(
        cards_api,
        'cleanup_deleted_cards_after_fs_delete',
        lambda **kwargs: cleanup_calls.append(kwargs) or {'warnings': []},
        raising=False,
    )
    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_test_app().test_client()
    res = client.post(
        '/api/delete_cards',
        json={'card_ids': [card_rel_a, card_rel_b], 'delete_resources': False},
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert cleanup_calls == [
        {
            'deleted_card_ids': [card_rel_a, card_rel_b],
            'source_paths_by_card_id': {
                card_rel_a: str(card_path_a),
                card_rel_b: str(card_path_b),
            },
        }
    ]
