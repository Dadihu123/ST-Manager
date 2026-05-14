import json
import os
import shutil
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.context import ctx
from core.data import cache as cache_module
from core.data import ui_store as ui_store_module
from core.data.cache import GlobalMetadataCache
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services import automation_service
from core.services import card_service
from core.services import cache_service
from core.services import index_build_service
from core.services import index_job_worker
from core.utils.image import write_card_metadata


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


class _StopWorkerLoop(Exception):
    pass


def _init_index_db(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)


def _create_card_metadata_table(conn):
    conn.execute(
        'CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, tags TEXT, category TEXT, last_modified REAL, token_count INTEGER, is_favorite INTEGER, has_character_book INTEGER, character_book_name TEXT, description TEXT, first_mes TEXT, mes_example TEXT, creator TEXT, char_version TEXT, file_hash TEXT, file_size INTEGER)'
    )


def _open_row_db(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def test_cache_reload_preserves_bundle_version_remarks_when_db_row_is_missing(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True)
    (bundle_dir / '.bundle').write_text('1', encoding='utf-8')
    (bundle_dir / 'cover.png').write_bytes(b'cover')
    (bundle_dir / 'alt.png').write_bytes(b'alt')

    ui_path.write_text(
        json.dumps(
            {
                'pack': {
                    'import_time': 100.0,
                    ui_store_module.VERSION_REMARKS_KEY: {
                        'pack/cover.png': {'summary': 'cover note'},
                        'pack/alt.png': {'summary': 'alt note'},
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    with _open_row_db(db_path) as conn:
        _create_card_metadata_table(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('pack/cover.png', 'Cover', json.dumps([]), 'pack', 20.0, 0, 0, 0, '', '', '', '', '', '', '', 1),
        )
        conn.commit()

    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    cache = GlobalMetadataCache()
    cache.reload_from_db()

    ui_payload = json.loads(ui_path.read_text(encoding='utf-8'))
    assert ui_payload['pack'][ui_store_module.VERSION_REMARKS_KEY] == {
        'pack/cover.png': {'summary': 'cover note'},
        'pack/alt.png': {'summary': 'alt note'},
    }


def _run_index_worker_once(monkeypatch, db_path: Path):
    rebuild_calls = []
    wait_calls = {'count': 0}

    def fake_wait(timeout):
        del timeout
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopWorkerLoop()
        return True

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        index_job_worker,
        'rebuild_scope_generation',
        lambda scope='cards', reason='bootstrap': rebuild_calls.append((scope, reason)),
    )
    monkeypatch.setattr(ctx.index_wakeup, 'wait', fake_wait)
    ctx.index_state.update({'state': 'empty', 'scope': 'cards', 'progress': 0, 'message': '', 'pending_jobs': 0})
    ctx.index_wakeup.set()

    with pytest.raises(_StopWorkerLoop):
        index_job_worker.worker_loop()

    return rebuild_calls


def _write_png_card(path: Path, *, name: str, tags):
    payload = {
        'data': {
            'name': name,
            'tags': list(tags),
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'extensions': {},
            'creator': '',
            'character_version': '',
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGBA', (1, 1), (255, 0, 0, 255)).save(path, format='PNG')
    assert write_card_metadata(str(path), payload) is True


def _setup_update_card_content_test(monkeypatch, tmp_path, *, ui_state=None):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)
    metadata_db = tmp_path / 'cards_metadata.db'

    class _FakeImage:
        def save(self, path, _fmt):
            Path(path).write_bytes(b'png-data')

    class _FakeCache:
        def __init__(self):
            self.id_map = {}
            self.cards = []
            self.bundle_map = {}

        def reload_from_db(self):
            return None

        def delete_card_update(self, card_id):
            self.id_map.pop(card_id, None)

        def add_card_update(self, payload):
            self.id_map[payload['id']] = dict(payload)
            return self.id_map[payload['id']]

        def update_card_data(self, card_id, payload):
            current = self.id_map.setdefault(
                card_id,
                {
                    'image_url': f'/cards_file/{card_id}',
                    'thumb_url': f'/api/thumbnail/{card_id}',
                },
            )
            current.update(payload)
            return self.id_map[card_id]

    ui_payload = ui_state if ui_state is not None else {}
    real_sqlite_connect = sqlite3.connect

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(metadata_db))
    monkeypatch.setattr(card_service, 'THUMB_FOLDER', str(tmp_path / 'thumbs'))
    monkeypatch.setattr(card_service, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': 'resources'})
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(card_service, 'resize_image_if_needed', lambda image: image)
    monkeypatch.setattr(card_service, 'clean_sidecar_images', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(card_service, 'clean_thumbnail_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: ui_payload)
    monkeypatch.setattr(card_service, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(card_service, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(card_service, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(card_service, 'get_import_time', lambda *_args, **_kwargs: 123.0)
    monkeypatch.setattr(card_service, 'calculate_token_count', lambda _payload: 42)
    monkeypatch.setattr(card_service, 'get_file_hash_and_size', lambda _path: ('new-hash', 11))
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(
        card_service.sqlite3,
        'connect',
        lambda *_args, **_kwargs: real_sqlite_connect(metadata_db, timeout=30, check_same_thread=False),
    )
    monkeypatch.setattr(card_service.ctx, 'cache', _FakeCache())
    monkeypatch.setattr(card_service.Image, 'open', lambda _path: _FakeImage())

    with _open_row_db(metadata_db) as conn:
        _create_card_metadata_table(conn)
        conn.commit()

    return cards_root


def test_update_card_content_archive_old_keeps_original_filename(monkeypatch, tmp_path):
    ui_state = {'hero.png': {'resource_folder': 'hero-assets'}}
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path, ui_state=ui_state)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    resource_dir = tmp_path / 'resources' / 'hero-assets'
    resource_dir.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={'resource_folder': 'hero-assets'},
        new_upload_ext='.png',
        image_policy='archive_old',
    )

    assert result['success'] is True
    assert sorted(path.name for path in resource_dir.iterdir()) == ['hero.png']


def test_update_card_content_archive_old_uses_suffix_on_collision(monkeypatch, tmp_path):
    ui_state = {'hero.png': {'resource_folder': 'hero-assets'}}
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path, ui_state=ui_state)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    resource_dir = tmp_path / 'resources' / 'hero-assets'
    resource_dir.mkdir(parents=True, exist_ok=True)
    (resource_dir / 'hero.png').write_bytes(b'existing-archive')
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={'resource_folder': 'hero-assets'},
        new_upload_ext='.png',
        image_policy='archive_old',
    )

    assert result['success'] is True
    assert sorted(path.name for path in resource_dir.iterdir()) == ['hero.png', 'hero_1.png']


def test_update_card_content_archive_old_failure_aborts_overwrite(monkeypatch, tmp_path):
    ui_state = {'hero.json': {'resource_folder': 'hero-assets'}}
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path, ui_state=ui_state)
    card_path = cards_root / 'hero.json'
    sidecar_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': ['old']}}, ensure_ascii=False), encoding='utf-8')
    sidecar_path.write_bytes(b'old-sidecar')
    temp_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': ['new']}}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.json') else 'old']}},
    )
    monkeypatch.setattr(card_service, 'find_sidecar_image', lambda _path: str(sidecar_path))
    monkeypatch.setattr(card_service.shutil, 'copy2', lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('copy failed')))

    result = card_service.update_card_content(
        'hero.json',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={'resource_folder': 'hero-assets'},
        new_upload_ext='.json',
        image_policy='archive_old',
    )

    assert result['success'] is False
    assert '归档' in result['msg'] or 'archive' in result['msg'].lower()
    assert card_path.read_text(encoding='utf-8') == json.dumps({'data': {'name': 'Hero', 'tags': ['old']}}, ensure_ascii=False)


def test_update_card_content_png_upload_json_keeps_existing_png_pixels(monkeypatch, tmp_path):
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.json'
    card_path.write_bytes(b'old-png')
    temp_path.write_text(
        json.dumps({'data': {'name': 'Hero V2', 'tags': ['new']}}, ensure_ascii=False),
        encoding='utf-8',
    )

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {
            'data': {
                'name': 'Hero V2' if str(path).endswith('upload.json') else 'Hero',
                'tags': ['new'] if str(path).endswith('upload.json') else ['old'],
            }
        },
    )

    opened_paths = []

    class _TrackingImage:
        def save(self, path, _fmt):
            Path(path).write_bytes(b'png-data')

    def _fake_open(path):
        opened_paths.append(Path(path).name)
        return _TrackingImage()

    monkeypatch.setattr(card_service.Image, 'open', _fake_open)

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.json',
        image_policy='overwrite',
    )

    assert result['success'] is True
    assert result['new_id'] == 'hero.png'
    assert result['updated_card']['char_name'] == 'Hero V2'
    assert result['updated_card']['source_revision'] == result['source_revision']
    assert opened_paths == ['hero.png']


def test_update_card_content_overwrite_runs_card_update_automation(monkeypatch, tmp_path):
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )

    automation_calls = []

    def fake_auto_run_rules_for_trigger(card_id, trigger_context):
        automation_calls.append((card_id, trigger_context))
        updated = {'id': 'hero-automated.png', 'filename': 'hero-automated.png', 'image_url': '/cards_file/hero-automated.png'}
        card_service.ctx.cache.id_map['hero-automated.png'] = updated
        return {'run': True, 'result': {'final_id': 'hero-automated.png'}}

    monkeypatch.setattr(automation_service, 'auto_run_rules_for_trigger', fake_auto_run_rules_for_trigger)

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
        image_policy='overwrite',
    )

    assert result['success'] is True
    assert automation_calls == [('hero.png', 'card_update')]
    assert result['new_id'] == 'hero-automated.png'
    assert result['new_filename'] == 'hero-automated.png'
    assert result['updated_card']['id'] == 'hero-automated.png'


def test_update_card_content_bundle_update_skips_card_update_automation(monkeypatch, tmp_path):
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )

    def fail_auto_run_rules_for_trigger(card_id, trigger_context):
        raise AssertionError(f'automation should be skipped, got {(card_id, trigger_context)}')

    monkeypatch.setattr(automation_service, 'auto_run_rules_for_trigger', fail_auto_run_rules_for_trigger)

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=True,
        keep_ui_data={},
        new_upload_ext='.png',
        image_policy='overwrite',
    )

    assert result['success'] is True


def test_update_card_content_automation_failure_payload_returns_warning(monkeypatch, tmp_path):
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )
    monkeypatch.setattr(
        automation_service,
        'auto_run_rules_for_trigger',
        lambda _card_id, _trigger_context: {'run': False, 'error': 'automation failed'},
    )

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
        image_policy='overwrite',
    )

    assert result['success'] is True
    assert 'warning' in result
    assert '自动化' in result['warning']


def test_update_card_content_automation_exception_returns_warning(monkeypatch, tmp_path):
    cards_root = _setup_update_card_content_test(monkeypatch, tmp_path)
    card_path = cards_root / 'hero.png'
    temp_path = tmp_path / 'upload.png'
    card_path.write_bytes(b'old-png')
    temp_path.write_bytes(b'new-png')

    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'name': 'Hero', 'tags': ['new' if str(path).endswith('upload.png') else 'old']}},
    )

    def raise_auto_run_rules_for_trigger(_card_id, _trigger_context):
        raise RuntimeError('automation exploded')

    monkeypatch.setattr(
        automation_service,
        'auto_run_rules_for_trigger',
        raise_auto_run_rules_for_trigger,
    )

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
        image_policy='overwrite',
    )

    assert result['success'] is True
    assert 'warning' in result
    assert '自动化' in result['warning']


def test_import_from_url_enqueues_card_and_world_sync_jobs(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    downloaded_path = temp_dir / 'temp_dl_1_Hero.png'

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield b'fake-card'

    sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Hero',
            'tags': ['blue'],
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'creator_notes': '',
            'personality': '',
            'scenario': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'character_version': '',
            'character_book': {'name': 'Book', 'entries': {}},
            'extensions': {},
            'creator': '',
        }
    })
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': True,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {'jobs_enqueued': ['upsert_card', 'upsert_world_embedded', 'upsert_world_owner']})
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post('/api/import_from_url', json={'url': 'https://example.com/hero.png', 'category': ''})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sync_calls == [
        {
            'card_id': 'Hero.png',
            'source_path': str(cards_dir / 'Hero.png'),
            'file_content_changed': True,
            'cache_updated': True,
            'has_embedded_wi': True,
            'previous_has_embedded_wi': False,
        }
    ]
    assert downloaded_path.exists() is False


def test_upload_commit_enqueues_card_and_world_sync_jobs(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    stage_dir = temp_dir / 'batch_upload' / 'batch-1'
    cards_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_card = stage_dir / 'hero.png'
    staged_card.write_bytes(b'fake-card')

    sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Hero',
            'tags': ['blue'],
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'creator_notes': '',
            'personality': '',
            'scenario': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'character_version': '',
            'character_book': {'name': 'Book', 'entries': {}},
            'extensions': {},
            'creator': '',
        }
    })
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': True,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {'jobs_enqueued': ['upsert_card', 'upsert_world_embedded', 'upsert_world_owner']})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/upload/commit',
        json={
            'batch_id': 'batch-1',
            'category': '',
            'decisions': [{'filename': 'hero.png', 'action': 'overwrite'}],
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sync_calls == [
        {
            'card_id': 'Hero.png',
            'source_path': str(cards_dir / 'Hero.png'),
            'file_content_changed': True,
            'cache_updated': True,
            'has_embedded_wi': True,
            'previous_has_embedded_wi': False,
        }
    ]


def test_import_from_url_overwrite_removes_opposite_extension_sibling(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield b'fake-card'

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Hero',
            'tags': ['blue'],
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'creator_notes': '',
            'personality': '',
            'scenario': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'character_version': '',
            'character_book': {'name': 'Book', 'entries': {}},
            'extensions': {},
            'creator': '',
        }
    })
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/import_from_url',
        json={'url': 'https://example.com/hero.png', 'category': '', 'resolution': 'overwrite'},
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sorted(path.name for path in cards_dir.iterdir()) == ['Hero.png']


def test_import_from_url_cross_extension_overwrite_preserves_old_tags(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')

    write_calls = []

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield b'fake-card'

    def _extract(path):
        if str(path).endswith('Hero.json'):
            return {'data': {'name': 'Hero', 'tags': ['old']}}
        return {'data': {'name': 'Hero', 'tags': ['new']}}

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda path, info: write_calls.append({'path': str(path), 'info': json.loads(json.dumps(info))}) or True)
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/import_from_url',
        json={'url': 'https://example.com/hero.png', 'category': '', 'resolution': 'overwrite'},
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert res.get_json()['new_card']['tags'] == ['old', 'new']
    assert len(write_calls) == 1
    assert Path(write_calls[0]['path']).parent == temp_dir
    assert Path(write_calls[0]['path']).name.endswith('_hero.png')
    assert write_calls[0]['info'] == {'data': {'name': 'Hero', 'tags': ['old', 'new']}}


def test_import_from_url_overwrite_suppresses_delete_and_move_boundary(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')

    events = []
    real_move = shutil.move
    real_remove = os.remove

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield b'fake-card'

    def _move(src, dst):
        events.append(f'move:{Path(dst).name}')
        return real_move(src, dst)

    def _remove(path):
        events.append(f'remove:{Path(path).name}')
        return real_remove(path)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: events.append('suppress'))
    monkeypatch.setattr(cards_api.shutil, 'move', _move)
    monkeypatch.setattr(cards_api.os, 'remove', _remove)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': ['new']}})
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/import_from_url',
        json={'url': 'https://example.com/hero.png', 'category': '', 'resolution': 'overwrite'},
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert events == ['suppress', 'remove:Hero.json', 'move:Hero.png']


def test_import_from_url_check_uses_existing_sibling_for_conflict_metadata(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    existing_json = cards_dir / 'Hero.json'
    existing_json.write_text('{"spec": "chara_card_v2"}', encoding='utf-8')

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield b'fake-card'

    def _extract(path):
        if str(path) == str(existing_json):
            return {'data': {'name': 'ExistingHero', 'tags': ['old']}}
        if str(path).endswith('.png'):
            return {'data': {'name': 'Hero', 'tags': ['new']}}
        raise AssertionError(f'unexpected extract path: {path}')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda data: 11 if data.get('name') == 'ExistingHero' else 7)
    monkeypatch.setattr(cards_api.os.path, 'getsize', lambda path: 123 if str(path) == str(existing_json) else 45)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    client = _make_app().test_client()
    res = client.post('/api/import_from_url', json={'url': 'https://example.com/hero.png', 'category': '', 'resolution': 'check'})

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is False
    assert body['status'] == 'conflict'
    assert body['existing_card']['char_name'] == 'ExistingHero'
    assert body['existing_card']['token_count'] == 11
    assert body['existing_card']['file_size'] == 123
    assert '/cards_file/Hero.json?' in body['existing_card']['image_url']


def test_import_from_url_suppresses_watchdog_immediately_before_move(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    cards_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    events = []
    real_move = shutil.move

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            del chunk_size
            events.append('download')
            yield b'fake-card'

    def _move(src, dst):
        events.append('move')
        return real_move(src, dst)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: events.append('suppress'))
    monkeypatch.setattr(cards_api.shutil, 'move', _move)
    monkeypatch.setattr(cards_api, 'requests', type('Requests', (), {'get': staticmethod(lambda *_args, **_kwargs: _FakeResponse())})())
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Hero',
            'tags': ['blue'],
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'creator_notes': '',
            'personality': '',
            'scenario': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'character_version': '',
            'character_book': {'name': 'Book', 'entries': {}},
            'extensions': {},
            'creator': '',
        }
    })
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post('/api/import_from_url', json={'url': 'https://example.com/hero.png', 'category': ''})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert events[-2:] == ['suppress', 'move']
    assert events.index('download') < events.index('suppress')


def test_upload_commit_overwrite_removes_opposite_extension_sibling(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    stage_dir = temp_dir / 'batch_upload' / 'batch-1'
    cards_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')
    staged_card = stage_dir / 'Hero.png'
    staged_card.write_bytes(b'fake-card')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Hero',
            'tags': ['blue'],
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'alternate_greetings': [],
            'creator_notes': '',
            'personality': '',
            'scenario': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'character_version': '',
            'character_book': {'name': 'Book', 'entries': {}},
            'extensions': {},
            'creator': '',
        }
    })
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/upload/commit',
        json={
            'batch_id': 'batch-1',
            'category': '',
            'decisions': [{'filename': 'Hero.png', 'action': 'overwrite'}],
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sorted(path.name for path in cards_dir.iterdir()) == ['Hero.png']


def test_upload_commit_cross_extension_overwrite_preserves_old_tags(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    stage_dir = temp_dir / 'batch_upload' / 'batch-1'
    cards_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')
    staged_card = stage_dir / 'Hero.png'
    staged_card.write_bytes(b'fake-card')

    write_calls = []

    def _extract(path):
        if str(path).endswith('Hero.json'):
            return {'data': {'name': 'Hero', 'tags': ['old']}}
        return {'data': {'name': 'Hero', 'tags': ['new']}}

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda path, info: write_calls.append({'path': str(path), 'info': json.loads(json.dumps(info))}) or True)
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/upload/commit',
        json={
            'batch_id': 'batch-1',
            'category': '',
            'decisions': [{'filename': 'Hero.png', 'action': 'overwrite'}],
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert write_calls == [
        {
            'path': str(stage_dir / 'Hero.png'),
            'info': {'data': {'name': 'Hero', 'tags': ['old', 'new']}},
        }
    ]


def test_upload_commit_overwrite_suppresses_delete_and_move_boundary(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    stage_dir = temp_dir / 'batch_upload' / 'batch-1'
    cards_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / 'Hero.json').write_text('{"spec": "chara_card_v2"}', encoding='utf-8')
    (stage_dir / 'Hero.png').write_bytes(b'fake-card')

    events = []
    real_move = shutil.move
    real_remove = os.remove

    def _move(src, dst):
        events.append(f'move:{Path(dst).name}')
        return real_move(src, dst)

    def _remove(path):
        events.append(f'remove:{Path(path).name}')
        return real_remove(path)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: events.append('suppress'))
    monkeypatch.setattr(cards_api.shutil, 'move', _move)
    monkeypatch.setattr(cards_api.os, 'remove', _remove)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': ['new']}})
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/upload/commit',
        json={
            'batch_id': 'batch-1',
            'category': '',
            'decisions': [{'filename': 'Hero.png', 'action': 'overwrite'}],
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert events == ['suppress', 'remove:Hero.json', 'move:Hero.png']


def test_upload_commit_suppresses_watchdog_for_each_move(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    temp_dir = tmp_path / 'temp'
    stage_dir = temp_dir / 'batch_upload' / 'batch-1'
    cards_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    for name in ('Alpha.png', 'Beta.png'):
        (stage_dir / name).write_bytes(b'fake-card')

    events = []
    real_move = shutil.move

    def _move(src, dst):
        events.append(f'move:{Path(dst).name}')
        return real_move(src, dst)

    def _extract(path):
        stem = Path(path).stem
        return {
            'data': {
                'name': stem,
                'tags': ['blue'],
                'description': '',
                'first_mes': '',
                'mes_example': '',
                'alternate_greetings': [],
                'creator_notes': '',
                'personality': '',
                'scenario': '',
                'system_prompt': '',
                'post_history_instructions': '',
                'character_version': '',
                'character_book': {'name': 'Book', 'entries': {}},
                'extensions': {},
                'creator': '',
            }
        }

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'TEMP_DIR', str(temp_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: events.append('suppress'))
    monkeypatch.setattr(cards_api.shutil, 'move', _move)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'current_config', {'auto_rename_on_import': True})
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api, 'sanitize_filename', lambda value: value)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'get_file_hash_and_size', lambda _path: ('hash', 8))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_rules_on_card', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})

    class _FakeCache:
        category_counts = {}

        def add_card_update(self, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post(
        '/api/upload/commit',
        json={
            'batch_id': 'batch-1',
            'category': '',
            'decisions': [
                {'filename': 'Alpha.png', 'action': 'overwrite'},
                {'filename': 'Beta.png', 'action': 'overwrite'},
            ],
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert events == ['suppress', 'move:Alpha.png', 'suppress', 'move:Beta.png']


def test_toggle_bundle_mode_enable_persists_merged_tags_and_enqueues_card_sync(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    cover_path.write_bytes(b'cover')
    alt_path.write_bytes(b'alt')

    write_calls = []
    cache_calls = []
    sync_calls = []
    apply_calls = []
    saved_ui_payloads = []
    force_reload_calls = []
    sorted_calls = []

    mtime_map = {
        str(cover_path): 20.0,
        str(alt_path): 10.0,
    }
    cover_getmtime_calls = {'count': 0}

    class _OrderedSet:
        def __init__(self, values=()):
            self._values = []
            self.update(values)

        def update(self, values):
            for value in values:
                if value not in self._values:
                    self._values.append(value)

        def __iter__(self):
            return iter(self._values)

    def _extract(path):
        normalized = str(path)
        if normalized == str(cover_path):
            return {'data': {'name': 'Cover', 'tags': ['zeta']}}
        if normalized == str(alt_path):
            return {'data': {'name': 'Alt', 'tags': ['alpha']}}
        raise AssertionError(f'unexpected path: {path}')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(
        cards_api.os,
        'walk',
        lambda path: [(str(bundle_dir), [], ['cover.png', 'alt.png'])] if str(path) == str(bundle_dir) else [],
    )
    def _getmtime(path):
        normalized = str(path)
        if normalized == str(cover_path):
            cover_getmtime_calls['count'] += 1
            if cover_getmtime_calls['count'] >= 2:
                return 25.0
        return mtime_map[normalized]

    def _sorted(values):
        values_list = list(values)
        sorted_calls.append(values_list)
        return sorted(values_list)

    monkeypatch.setattr(cards_api.os.path, 'getmtime', _getmtime)
    monkeypatch.setattr(cards_api, 'set', _OrderedSet, raising=False)
    monkeypatch.setattr(cards_api, 'sorted', _sorted, raising=False)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'pack/cover.png': {'summary': 'cover note'}})
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _card_id, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0.0))
    monkeypatch.setattr(cards_api, 'set_version_remark', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        cards_api,
        'write_card_metadata',
        lambda path, info: write_calls.append({'path': str(path), 'info': json.loads(json.dumps(info))}) or True,
    )
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: (
            cache_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        )[1],
    )
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        cards_api,
        '_apply_card_index_increment_now',
        lambda card_id, source_path, remove_entity_ids=None: apply_calls.append(
            {
                'card_id': card_id,
                'source_path': source_path,
                'remove_entity_ids': remove_entity_ids,
            }
        ),
    )
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'enable'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sorted_calls == [['zeta', 'alpha']]
    assert write_calls == [
        {
            'path': str(cover_path),
            'info': {'data': {'name': 'Cover', 'tags': ['alpha', 'zeta']}},
        }
    ]
    assert cache_calls == [
        {
            'card_id': 'pack/cover.png',
            'full_path': str(cover_path),
            'kwargs': {
                'parsed_info': {'data': {'name': 'Cover', 'tags': ['alpha', 'zeta']}},
                'mtime': 25.0,
            },
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'pack/cover.png',
            'source_path': str(cover_path),
            'tags_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        }
    ]
    assert apply_calls == [
        {
            'card_id': 'pack/cover.png',
            'source_path': str(cover_path),
            'remove_entity_ids': None,
        }
    ]
    assert saved_ui_payloads[-1]['pack']['import_time'] == 20.0
    assert force_reload_calls == [{'reason': 'toggle_bundle_mode:enable'}]
    assert (bundle_dir / '.bundle').exists() is True


def test_toggle_bundle_mode_enable_stops_when_metadata_write_fails(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    cover_path.write_bytes(b'cover')
    alt_path.write_bytes(b'alt')

    cache_calls = []
    sync_calls = []
    apply_calls = []
    force_reload_calls = []
    saved_ui_payloads = []

    mtime_map = {
        str(cover_path): 20.0,
        str(alt_path): 10.0,
    }

    def _extract(path):
        normalized = str(path)
        if normalized == str(cover_path):
            return {'data': {'name': 'Cover', 'tags': ['alpha']}}
        if normalized == str(alt_path):
            return {'data': {'name': 'Alt', 'tags': ['beta']}}
        raise AssertionError(f'unexpected path: {path}')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api.os.path, 'getmtime', lambda path: mtime_map[str(path)])
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'pack/cover.png': {'summary': 'cover note'}})
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _card_id, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0.0))
    monkeypatch.setattr(cards_api, 'set_version_remark', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda *args, **kwargs: cache_calls.append({'args': args, 'kwargs': kwargs}) or {},
    )
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        cards_api,
        '_apply_card_index_increment_now',
        lambda card_id, source_path, remove_entity_ids=None: apply_calls.append(
            {
                'card_id': card_id,
                'source_path': source_path,
                'remove_entity_ids': remove_entity_ids,
            }
        ),
    )
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'enable'})

    assert res.status_code == 200
    assert res.get_json() == {'success': False, 'msg': '写入卡片元数据失败'}
    assert cache_calls == []
    assert sync_calls == []
    assert apply_calls == []
    assert force_reload_calls == []
    assert saved_ui_payloads == []
    assert (bundle_dir / '.bundle').exists() is False


def test_toggle_bundle_mode_enable_stops_when_cover_metadata_missing(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    cover_path.write_bytes(b'cover')
    alt_path.write_bytes(b'alt')

    cache_calls = []
    sync_calls = []
    apply_calls = []
    force_reload_calls = []
    saved_ui_payloads = []

    mtime_map = {
        str(cover_path): 20.0,
        str(alt_path): 10.0,
    }
    cover_extract_calls = {'count': 0}

    def _extract(path):
        normalized = str(path)
        if normalized == str(cover_path):
            cover_extract_calls['count'] += 1
            if cover_extract_calls['count'] >= 2:
                return None
            return {'data': {'name': 'Cover', 'tags': ['alpha']}}
        if normalized == str(alt_path):
            return {'data': {'name': 'Alt', 'tags': ['beta']}}
        raise AssertionError(f'unexpected path: {path}')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(
        cards_api.os,
        'walk',
        lambda path: [(str(bundle_dir), [], ['cover.png', 'alt.png'])] if str(path) == str(bundle_dir) else [],
    )
    monkeypatch.setattr(cards_api, 'extract_card_info', _extract)
    monkeypatch.setattr(cards_api.os.path, 'getmtime', lambda path: mtime_map[str(path)])
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'pack/cover.png': {'summary': 'cover note'}})
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _card_id, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0.0))
    monkeypatch.setattr(cards_api, 'set_version_remark', lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda *args, **kwargs: cache_calls.append({'args': args, 'kwargs': kwargs}) or {},
    )
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        cards_api,
        '_apply_card_index_increment_now',
        lambda card_id, source_path, remove_entity_ids=None: apply_calls.append(
            {
                'card_id': card_id,
                'source_path': source_path,
                'remove_entity_ids': remove_entity_ids,
            }
        ),
    )
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'enable'})

    assert res.status_code == 200
    assert res.get_json() == {'success': False, 'msg': '读取封面卡片元数据失败'}
    assert cache_calls == []
    assert sync_calls == []
    assert apply_calls == []
    assert force_reload_calls == []
    assert saved_ui_payloads == []
    assert (bundle_dir / '.bundle').exists() is False


def test_move_card_internal_enqueues_incremental_cleanup_for_single_card(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    src_dir = cards_root / 'src'
    dst_dir = cards_root / 'dst'
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_path = src_dir / 'demo.json'
    src_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    sync_calls = []
    cache_calls = {}
    saved_ui_payloads = []
    events = []

    class _FakeConn:
        def execute(self, _sql, _params=()):
            return self

        def commit(self):
            events.append('commit')
            return None

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'load_ui_data',
        lambda: {
            'src/demo.json': {
                'summary': 'note',
                card_service.VERSION_REMARKS_KEY: {
                    'src/demo.json': {'summary': 'version note'},
                },
            },
            '_worldinfo_notes_v1': {
                'embedded::src/demo.json': {'summary': 'embedded note'},
                'embedded::src/other.json': {'summary': 'keep other note'},
            },
        },
    )
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload: (events.append('save_ui_data'), saved_ui_payloads.append(dict(payload)))[1],
    )
    monkeypatch.setattr(card_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *args, **kwargs: (
        cache_calls.setdefault('update_card_cache', {'args': args, 'kwargs': kwargs}),
        {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        }
    )[1])
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(
            id_map={'src/demo.json': {'id': 'src/demo.json', 'category': 'src'}},
            move_card_update=lambda *args, **kwargs: cache_calls.setdefault('move_card_update', (args, kwargs)),
        ),
        raising=False,
    )

    ok, new_id, msg = card_service.move_card_internal('src/demo.json', 'dst')

    assert ok is True
    assert msg == 'Success'
    assert new_id == 'dst/demo.json'
    assert sync_calls == [
        {
            'card_id': 'dst/demo.json',
            'source_path': str(dst_dir / 'demo.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/demo.json'],
            'remove_owner_ids': ['src/demo.json'],
        }
    ]
    assert events[:2] == ['commit', 'save_ui_data']
    assert saved_ui_payloads[-1] == {
        'dst/demo.json': {
            'summary': 'note',
            card_service.VERSION_REMARKS_KEY: {
                'dst/demo.json': {'summary': 'version note'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::dst/demo.json': {'summary': 'embedded note'},
            'embedded::src/other.json': {'summary': 'keep other note'},
        },
    }


def test_api_move_card_uses_shared_move_card_internal(monkeypatch):
    move_calls = []

    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'move_card_internal', lambda card_id, target_category: move_calls.append((card_id, target_category)) or (True, 'dst/demo.json', 'Success'))
    monkeypatch.setattr(
        cards_api.ctx,
        'cache',
        SimpleNamespace(
            id_map={'dst/demo.json': {'image_url': '/cards_file/dst%2Fdemo.json?t=1'}},
            category_counts={},
        ),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post('/api/move_card', json={'card_ids': ['src/demo.json'], 'target_category': 'dst'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'count': 1,
        'moved_details': [
            {
                'old_id': 'src/demo.json',
                'new_id': 'dst/demo.json',
                'new_filename': 'demo.json',
                'new_category': 'dst',
                'new_image_url': '/cards_file/dst%2Fdemo.json?t=1',
            }
        ],
        'category_counts': {},
    }
    assert move_calls == [('src/demo.json', 'dst')]


def test_move_card_internal_directory_migrates_prefixed_ui_data_and_nested_categories(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    src_dir = cards_root / 'src' / 'pack' / 'sub'
    dst_dir = cards_root / 'dst'
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    moved_file = src_dir / 'hero.json'
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    saved_ui_payloads = []
    update_calls = []
    sync_calls = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self._rows = []

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            normalized_sql = ' '.join(str(sql).split())
            if normalized_sql.startswith("SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'"):
                self._rows = [('src/pack/sub/hero.json',)]
            return self

        def fetchall(self):
            return list(self._rows)

        def commit(self):
            return None

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                'src/pack/sub/hero.json': {
                    'id': 'src/pack/sub/hero.json',
                    'category': 'src/pack/sub',
                    'is_bundle': False,
                    'last_modified': 1,
                }
            }
            self.bundle_map = {}
            self.visible_folders = []

        def move_bundle_update(self, old_bundle_path, new_bundle_path, old_category, new_category):
            moved_items = []
            for card_id in list(self.id_map.keys()):
                if card_id == old_bundle_path or card_id.startswith(old_bundle_path + '/'):
                    moved_items.append((card_id, self.id_map.pop(card_id)))

            for old_id, card in moved_items:
                if old_id == old_bundle_path:
                    new_id = new_bundle_path
                else:
                    new_id = new_bundle_path + old_id[len(old_bundle_path):]

                card = dict(card)
                card['id'] = new_id
                card['category'] = new_category
                self.id_map[new_id] = card

        def move_folder_update(self, old_path_prefix, new_path_prefix):
            new_bundle_map = {}
            for bundle_dir, bundle_card_id in self.bundle_map.items():
                if bundle_dir == old_path_prefix:
                    remapped_dir = new_path_prefix
                elif bundle_dir.startswith(old_path_prefix + '/'):
                    remapped_dir = new_path_prefix + bundle_dir[len(old_path_prefix):]
                else:
                    remapped_dir = bundle_dir

                if bundle_card_id.startswith(old_path_prefix + '/'):
                    remapped_card_id = new_path_prefix + bundle_card_id[len(old_path_prefix):]
                else:
                    remapped_card_id = bundle_card_id

                new_bundle_map[remapped_dir] = remapped_card_id

            moved_items = []
            for card_id in list(self.id_map.keys()):
                if not card_id.startswith(old_path_prefix + '/'):
                    continue
                moved_items.append((card_id, self.id_map.pop(card_id)))

            for old_id, card in moved_items:
                suffix = old_id[len(old_path_prefix):]
                new_id = new_path_prefix + suffix
                old_category = card.get('category', '')
                if old_category == old_path_prefix:
                    new_category = new_path_prefix
                elif old_category.startswith(old_path_prefix + '/'):
                    new_category = new_path_prefix + old_category[len(old_path_prefix):]
                else:
                    new_category = new_id.rsplit('/', 1)[0] if '/' in new_id else ''

                card = dict(card)
                card['id'] = new_id
                card['category'] = new_category
                self.id_map[new_id] = card

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'load_ui_data',
        lambda: {
            'src/pack/sub/hero.json': {
                'summary': 'nested note',
                card_service.VERSION_REMARKS_KEY: {
                    'src/pack/sub/hero.json': {'label': 'nested remark'},
                },
            },
            'src/pack': {'summary': 'folder note'},
            '_worldinfo_notes_v1': {
                'embedded::src/pack/sub/hero.json': {'summary': 'embedded note'},
                'resource::book.json': {'summary': 'keep resource note'},
            },
        },
    )
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: (
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        )[1],
    )
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    ok, new_id, msg = card_service.move_card_internal('src/pack', 'dst')

    assert ok is True
    assert msg == 'Success'
    assert new_id == 'dst/pack'
    assert saved_ui_payloads[-1] == {
        'dst/pack': {'summary': 'folder note'},
        'dst/pack/sub/hero.json': {
            'summary': 'nested note',
            card_service.VERSION_REMARKS_KEY: {
                'dst/pack/sub/hero.json': {'label': 'nested remark'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::dst/pack/sub/hero.json': {'summary': 'embedded note'},
            'resource::book.json': {'summary': 'keep resource note'},
        },
    }
    assert fake_conn.executed == [
        ("SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", ('src/pack',)),
        (
            """
            UPDATE card_metadata 
            SET id = ?, category = REPLACE(category, ?, ?) 
            WHERE id = ?
        """,
            ('dst/pack/sub/hero.json', 'src/pack', 'dst/pack', 'src/pack/sub/hero.json'),
        ),
    ]
    assert update_calls == [
        {
            'card_id': 'dst/pack/sub/hero.json',
            'full_path': str(cards_root / 'dst' / 'pack' / 'sub' / 'hero.json'),
            'kwargs': {'remove_entity_ids': ['src/pack/sub/hero.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/pack/sub/hero.json',
            'source_path': str(cards_root / 'dst' / 'pack' / 'sub' / 'hero.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/pack/sub/hero.json'],
            'remove_owner_ids': ['src/pack/sub/hero.json'],
        }
    ]
    assert fake_cache.id_map == {
        'dst/pack/sub/hero.json': {
            'id': 'dst/pack/sub/hero.json',
            'category': 'dst/pack/sub',
            'is_bundle': False,
            'last_modified': 1,
        }
    }


def test_move_card_internal_bundle_directory_migrates_version_remarks_and_bundle_cache(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    src_dir = cards_root / 'src' / 'bundle'
    dst_dir = cards_root / 'dst'
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / '.bundle').write_text('1', encoding='utf-8')
    (src_dir / 'cover.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (src_dir / 'alt.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    saved_ui_payloads = []
    update_calls = []
    sync_calls = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self._rows = []

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            normalized_sql = ' '.join(str(sql).split())
            if normalized_sql.startswith("SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'"):
                self._rows = [
                    ('src/bundle/cover.json',),
                    ('src/bundle/alt.json',),
                ]
            return self

        def fetchall(self):
            return list(self._rows)

        def commit(self):
            return None

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                'src/bundle/cover.json': {
                    'id': 'src/bundle/cover.json',
                    'category': 'src',
                    'is_bundle': True,
                    'bundle_dir': 'src/bundle',
                    'last_modified': 1,
                    'versions': [
                        {'id': 'src/bundle/cover.json', 'filename': 'cover.json'},
                        {'id': 'src/bundle/alt.json', 'filename': 'alt.json'},
                    ],
                }
            }
            self.bundle_map = {'src/bundle': 'src/bundle/cover.json'}
            self.visible_folders = []

        def move_bundle_update(self, old_bundle_path, new_bundle_path, old_category, new_category):
            moved_items = []
            for card_id in list(self.id_map.keys()):
                if card_id == old_bundle_path or card_id.startswith(old_bundle_path + '/'):
                    moved_items.append((card_id, self.id_map.pop(card_id)))

            for old_id, card in moved_items:
                if old_id == old_bundle_path:
                    new_id = new_bundle_path
                else:
                    new_id = new_bundle_path + old_id[len(old_bundle_path):]

                card = dict(card)
                card['id'] = new_id
                card['category'] = new_category
                if card.get('is_bundle'):
                    card['bundle_dir'] = new_bundle_path
                self.id_map[new_id] = card

            main_id = self.bundle_map.pop(old_bundle_path, None)
            if main_id:
                self.bundle_map[new_bundle_path] = new_bundle_path + main_id[len(old_bundle_path):]

        def move_folder_update(self, old_path_prefix, new_path_prefix):
            new_bundle_map = {}
            for bundle_dir, bundle_card_id in self.bundle_map.items():
                if bundle_dir == old_path_prefix:
                    remapped_dir = new_path_prefix
                elif bundle_dir.startswith(old_path_prefix + '/'):
                    remapped_dir = new_path_prefix + bundle_dir[len(old_path_prefix):]
                else:
                    remapped_dir = bundle_dir

                if bundle_card_id.startswith(old_path_prefix + '/'):
                    remapped_card_id = new_path_prefix + bundle_card_id[len(old_path_prefix):]
                else:
                    remapped_card_id = bundle_card_id

                new_bundle_map[remapped_dir] = remapped_card_id

            moved_items = []
            for card_id in list(self.id_map.keys()):
                if not card_id.startswith(old_path_prefix + '/'):
                    continue
                moved_items.append((card_id, self.id_map.pop(card_id)))

            for old_id, card in moved_items:
                suffix = old_id[len(old_path_prefix):]
                new_id = new_path_prefix + suffix
                card = dict(card)
                card['id'] = new_id
                if card.get('bundle_dir') == old_path_prefix:
                    card['bundle_dir'] = new_path_prefix
                versions = card.get('versions')
                if isinstance(versions, list):
                    for version in versions:
                        if not isinstance(version, dict):
                            continue
                        version_id = str(version.get('id') or '')
                        if version_id.startswith(old_path_prefix + '/'):
                            version['id'] = new_path_prefix + version_id[len(old_path_prefix):]
                self.id_map[new_id] = card

            self.bundle_map = new_bundle_map

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'load_ui_data',
        lambda: {
            'src/bundle': {
                card_service.VERSION_REMARKS_KEY: {
                    'src/bundle/cover.json': {'summary': 'cover note'},
                    'src/bundle/alt.json': {'summary': 'alt note'},
                },
                'resource_folder': 'hero-assets',
            }
        },
    )
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: (
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        )[1],
    )
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    ok, new_id, msg = card_service.move_card_internal('src/bundle', 'dst')

    assert ok is True
    assert msg == 'Success'
    assert new_id == 'dst/bundle'
    assert saved_ui_payloads[-1] == {
        'dst/bundle': {
            card_service.VERSION_REMARKS_KEY: {
                'dst/bundle/cover.json': {'summary': 'cover note'},
                'dst/bundle/alt.json': {'summary': 'alt note'},
            },
            'resource_folder': 'hero-assets',
        }
    }
    assert update_calls == [
        {
            'card_id': 'dst/bundle/cover.json',
            'full_path': str(cards_root / 'dst' / 'bundle' / 'cover.json'),
            'kwargs': {'remove_entity_ids': ['src/bundle/cover.json']},
        },
        {
            'card_id': 'dst/bundle/alt.json',
            'full_path': str(cards_root / 'dst' / 'bundle' / 'alt.json'),
            'kwargs': {'remove_entity_ids': ['src/bundle/alt.json']},
        },
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/bundle/cover.json',
            'source_path': str(cards_root / 'dst' / 'bundle' / 'cover.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/bundle/cover.json'],
            'remove_owner_ids': ['src/bundle/cover.json'],
        },
        {
            'card_id': 'dst/bundle/alt.json',
            'source_path': str(cards_root / 'dst' / 'bundle' / 'alt.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/bundle/alt.json'],
            'remove_owner_ids': ['src/bundle/alt.json'],
        },
    ]
    assert fake_cache.bundle_map == {'dst/bundle': 'dst/bundle/cover.json'}
    assert fake_cache.id_map['dst/bundle/cover.json']['bundle_dir'] == 'dst/bundle'
    assert fake_cache.id_map['dst/bundle/cover.json']['versions'] == [
        {'id': 'dst/bundle/cover.json', 'filename': 'cover.json'},
        {'id': 'dst/bundle/alt.json', 'filename': 'alt.json'},
    ]


def test_convert_to_bundle_updates_category_and_enqueues_incremental_sync(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'group'
    source_dir.mkdir(parents=True, exist_ok=True)
    src_path = source_dir / 'hero.json'
    src_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (source_dir / 'hero.png').write_bytes(b'sidecar')

    executed = []
    cache_calls = []
    sync_calls = []
    apply_calls = []
    saved_ui_payloads = []
    force_reload_calls = []

    class _FakeCursor:
        def execute(self, sql, params=()):
            executed.append((sql, params))
            return self

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def commit(self):
            executed.append(('commit', ()))

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'group/hero.json': {'summary': 'note'}})
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: (
            cache_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        )[1],
    )
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        cards_api,
        '_apply_card_index_increment_now',
        lambda card_id, source_path, remove_entity_ids=None: apply_calls.append(
            {
                'card_id': card_id,
                'source_path': source_path,
                'remove_entity_ids': remove_entity_ids,
            }
        ),
    )
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(cards_api.ctx, 'cache', SimpleNamespace(id_map={}, category_counts={}), raising=False)

    client = _make_app().test_client()
    res = client.post('/api/convert_to_bundle', json={'card_id': 'group/hero.json', 'bundle_name': 'pack'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert (
        'UPDATE card_metadata SET id = ?, category = ? WHERE id = ?',
        ('group/pack/hero.json', 'group/pack', 'group/hero.json'),
    ) in executed
    assert cache_calls == [
        {
            'card_id': 'group/pack/hero.json',
            'full_path': str(cards_dir / 'group' / 'pack' / 'hero.json'),
            'kwargs': {'remove_entity_ids': ['group/hero.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'group/pack/hero.json',
            'source_path': str(cards_dir / 'group' / 'pack' / 'hero.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['group/hero.json'],
            'remove_owner_ids': ['group/hero.json'],
        }
    ]
    assert apply_calls == [
        {
            'card_id': 'group/pack/hero.json',
            'source_path': str(cards_dir / 'group' / 'pack' / 'hero.json'),
            'remove_entity_ids': ['group/hero.json'],
        }
    ]
    assert saved_ui_payloads == [{'group/pack': {'summary': 'note'}}]
    assert force_reload_calls == [{'reason': 'convert_to_bundle'}]


def test_convert_to_bundle_rebuilds_new_owner_projection_after_old_cleanup(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    resources_dir = tmp_path / 'resources'
    old_id = 'group/hero.json'
    new_id = 'group/pack/hero.json'
    old_card_path = cards_dir / 'group' / 'hero.json'
    new_card_path = cards_dir / 'group' / 'pack' / 'hero.json'
    old_card_path.parent.mkdir(parents=True, exist_ok=True)
    old_card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': ['alpha']}}, ensure_ascii=False), encoding='utf-8')
    (cards_dir / 'group' / 'hero.png').write_bytes(b'sidecar')
    resource_file = resources_dir / 'hero-assets' / 'lorebooks' / 'companion.json'
    resource_file.parent.mkdir(parents=True, exist_ok=True)
    resource_file.write_text(json.dumps({'name': 'Fresh Resource', 'entries': {}}, ensure_ascii=False), encoding='utf-8')
    ui_path.write_text(
        json.dumps({old_id: {'summary': 'note', 'resource_folder': 'hero-assets'}}, ensure_ascii=False),
        encoding='utf-8',
    )
    
    _init_index_db(db_path)
    with _open_row_db(db_path) as conn:
        _create_card_metadata_table(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (old_id, 'Hero', json.dumps(['alpha']), 'group', 10.0, 11, 0, 0, '', '', '', '', '', '', 'hash', 1),
        )
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, f'card::{old_id}', 'card', str(old_card_path), '', 'Old Hero', 'hero.json', 'group', 'group', 'physical', 0, 'note', 10.0, 0.0, 11, 'old hero', 10.0, '', '10:1'),
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (1, f'card::{old_id}', 'alpha'),
        )
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, f'card::{old_id}', 'Old Hero hero.json group note alpha'),
        )
        conn.execute(
            'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, f'card::{old_id}', 'Old Hero hero.json group note alpha'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, f'world::resource::{old_id}::companion.json', 'world_resource', str(resource_file), f'card::{old_id}', 'Old Resource', 'companion.json', 'group', '', 'inherited', 0, '', 10.0, 0.0, 0, 'old resource', 10.0, '', '10:1'),
        )
        conn.commit()

    real_cache_conn = _open_row_db(db_path)

    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cache_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_build_service, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: _open_row_db(db_path))
    monkeypatch.setattr(cache_service, 'get_db', lambda: real_cache_conn)
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda _path: ('new-hash', 12))
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _data: 22)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _data: (False, ''))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'global-lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'force_reload', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', SimpleNamespace(id_map={}, category_counts={}), raising=False)

    client = _make_app().test_client()
    res = client.post('/api/convert_to_bundle', json={'card_id': old_id, 'bundle_name': 'pack'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert old_card_path.exists() is False
    assert new_card_path.exists() is True

    rebuild_calls = _run_index_worker_once(monkeypatch, db_path)

    with sqlite3.connect(db_path) as verify_conn:
        card_rows = verify_conn.execute(
            'SELECT id, category FROM card_metadata ORDER BY id'
        ).fetchall()
        card_entities = verify_conn.execute(
            "SELECT entity_id, source_path FROM index_entities_v2 WHERE generation = 1 AND entity_type = 'card' ORDER BY entity_id"
        ).fetchall()
        world_rows = verify_conn.execute(
            "SELECT entity_id, owner_entity_id, name FROM index_entities_v2 WHERE generation = 1 AND entity_type LIKE 'world_%' ORDER BY entity_id"
        ).fetchall()
        queued = verify_conn.execute(
            'SELECT job_type, entity_id, payload_json, status FROM index_jobs ORDER BY id'
        ).fetchall()

    assert card_rows == [(new_id, 'group/pack')]
    assert card_entities == [(f'card::{new_id}', str(new_card_path))]
    assert world_rows == [
        (f'world::resource::{new_id}::companion.json', f'card::{new_id}', 'Fresh Resource'),
    ]
    assert queued == [
        ('upsert_card', new_id, json.dumps({'remove_entity_ids': [old_id]}, ensure_ascii=False), 'done'),
        ('upsert_world_owner', new_id, json.dumps({'remove_owner_ids': [old_id]}, ensure_ascii=False), 'done'),
    ]
    assert rebuild_calls == []

    real_cache_conn.close()


def test_update_card_rename_moves_embedded_worldinfo_note_key(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    old_id = 'group/hero.json'
    new_id = 'group/hero-renamed.json'
    old_path = cards_dir / 'group' / 'hero.json'
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False), encoding='utf-8')

    ui_data = {
        old_id: {'summary': 'hero note'},
        '_worldinfo_notes_v1': {
            f'embedded::{old_id}': {'summary': 'embedded note'},
            'embedded::group/other.json': {'summary': 'keep other note'},
        },
    }
    saved_ui_payloads = []
    sync_calls = []

    class _FakeConn:
        def execute(self, _sql, _params=()):
            return self

        def commit(self):
            return None

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                old_id: {
                    'id': old_id,
                    'category': 'group',
                    'image_url': '/cards_file/group%2Fhero.json',
                }
            }
            self.category_counts = {}
            self.bundle_map = {}
            self.lock = threading.Lock()

        def update_card_data(self, _card_id, payload):
            payload = dict(payload)
            payload['image_url'] = '/cards_file/group%2Fhero-renamed.json'
            return payload

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 123.0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(cards_api, '_apply_card_index_increment_now', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache(), raising=False)

    client = _make_app().test_client()
    res = client.post(
        '/api/update_card',
        json={
            'id': old_id,
            'new_filename': 'hero-renamed.json',
            'char_name': 'Hero',
            'description': '',
            'first_mes': '',
            'mes_example': '',
            'personality': '',
            'scenario': '',
            'creator_notes': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'creator': '',
            'character_version': '',
            'extensions': {},
            'tags': [],
            'alternate_greetings': [],
            'character_book': None,
            'ui_summary': 'hero note',
            'source_link': '',
            'resource_folder': '',
        },
    )

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert saved_ui_payloads[-1]['_worldinfo_notes_v1'] == {
        f'embedded::{new_id}': {'summary': 'embedded note'},
        'embedded::group/other.json': {'summary': 'keep other note'},
    }
    assert sync_calls == [
        {
            'card_id': new_id,
            'source_path': str(cards_dir / 'group' / 'hero-renamed.json'),
            'file_content_changed': True,
            'rename_changed': True,
            'force_set_cover': False,
            'resource_folder_changed': False,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': [old_id],
            'remove_owner_ids': [old_id],
        }
    ]


def test_toggle_bundle_mode_enable_keeps_tags_consistent_between_file_db_cache_and_index(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    _write_png_card(cover_path, name='Cover', tags=['zeta'])
    _write_png_card(alt_path, name='Alt', tags=['alpha'])
    ui_path.write_text(
        json.dumps({'pack/cover.png': {'summary': 'cover note'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    _init_index_db(db_path)
    real_cache_conn = _open_row_db(db_path)
    with _open_row_db(db_path) as conn:
        _create_card_metadata_table(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('pack/cover.png', 'Cover', json.dumps(['zeta']), 'pack', 20.0, 11, 0, 0, '', '', '', '', '', '', 'cover-hash', 1),
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('pack/alt.png', 'Alt', json.dumps(['alpha']), 'pack', 10.0, 12, 0, 0, '', '', '', '', '', '', 'alt-hash', 1),
        )
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::pack/cover.png', 'card', str(cover_path), '', 'Cover', 'cover.png', 'pack', 'pack', 'physical', 0, 'cover note', 20.0, 0.0, 11, 'cover', 20.0, '', '20:1'),
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (1, 'card::pack/cover.png', 'zeta'),
        )
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, 'card::pack/cover.png', 'Cover cover.png pack cover note zeta'),
        )
        conn.execute(
            'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, 'card::pack/cover.png', 'Cover cover.png pack cover note zeta'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::pack/alt.png', 'card', str(alt_path), '', 'Alt', 'alt.png', 'pack', 'pack', 'physical', 0, '', 10.0, 0.0, 12, 'alt', 10.0, '', '10:1'),
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (1, 'card::pack/alt.png', 'alpha'),
        )
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, 'card::pack/alt.png', 'Alt alt.png pack alpha'),
        )
        conn.execute(
            'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (1, 'card::pack/alt.png', 'Alt alt.png pack alpha'),
        )
        conn.commit()

    cache = GlobalMetadataCache()

    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cache_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_build_service, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cache_service, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(
        cards_api.os.path,
        'getmtime',
        lambda path: 20.0 if str(path) == str(cover_path) else 10.0,
    )
    monkeypatch.setattr(cache_service, 'get_db', lambda: real_cache_conn)
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda path: ('cover-hash' if str(path) == str(cover_path) else 'alt-hash', 1))
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _data: 77)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _data: (False, ''))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _card_id, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0.0))
    monkeypatch.setattr(cards_api.ctx, 'cache', cache, raising=False)

    monkeypatch.setattr(
        cards_api,
        'force_reload',
        lambda **_kwargs: cache.reload_from_db(),
    )

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'enable'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True

    cover_info = cards_api.extract_card_info(str(cover_path))
    alt_info = cards_api.extract_card_info(str(alt_path))

    with sqlite3.connect(db_path) as verify_conn:
        db_rows = verify_conn.execute(
            'SELECT id, tags, category FROM card_metadata ORDER BY id'
        ).fetchall()
        index_rows = verify_conn.execute(
            "SELECT entity_id FROM index_entities_v2 WHERE generation = 1 AND entity_type = 'card' ORDER BY entity_id"
        ).fetchall()
        cover_tags = verify_conn.execute(
            "SELECT tag FROM index_entity_tags_v2 WHERE generation = 1 AND entity_id = 'card::pack/cover.png' ORDER BY tag"
        ).fetchall()
        alt_tags = verify_conn.execute(
            "SELECT tag FROM index_entity_tags_v2 WHERE generation = 1 AND entity_id = 'card::pack/alt.png' ORDER BY tag"
        ).fetchall()
        cover_search = verify_conn.execute(
            "SELECT content FROM index_search_fast_v2 WHERE generation = 1 AND entity_id = 'card::pack/cover.png'"
        ).fetchone()

    assert cover_info['data']['tags'] == ['alpha', 'zeta']
    assert alt_info['data']['tags'] == ['alpha']
    assert db_rows == [
        ('pack/alt.png', json.dumps(['alpha']), 'pack'),
        ('pack/cover.png', json.dumps(['alpha', 'zeta']), 'pack'),
    ]
    assert index_rows == [('card::pack/alt.png',), ('card::pack/cover.png',)]
    assert cover_tags == [('alpha',), ('zeta',)]
    assert alt_tags == [('alpha',)]
    assert cover_search == ('Cover cover.png pack cover note alpha zeta',)
    assert cache.bundle_map == {'pack': 'pack/cover.png'}
    assert cache.id_map['pack/cover.png']['is_bundle'] is True
    assert cache.id_map['pack/cover.png']['tags'] == ['alpha', 'zeta']
    assert [version['id'] for version in cache.id_map['pack/cover.png']['versions']] == [
        'pack/cover.png',
        'pack/alt.png',
    ]

    real_cache_conn.close()


def test_toggle_bundle_mode_disable_enqueues_incremental_repairs_for_versions(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    cover_path.write_bytes(b'cover')
    alt_path.write_bytes(b'alt')
    (bundle_dir / '.bundle').write_text('1', encoding='utf-8')

    saved_ui_payloads = []
    sync_calls = []
    force_reload_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(
        cards_api.os,
        'walk',
        lambda path: [(str(bundle_dir), [], ['cover.png', 'alt.png'])] if str(path) == str(bundle_dir) else [],
    )
    monkeypatch.setattr(
        cards_api,
        'load_ui_data',
        lambda: {
            'pack': {
                'link': 'https://example.com/card',
                'resource_folder': 'hero-assets',
            }
        },
    )
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda ui_data, ver_id: (ui_data.setdefault(ver_id, {}).update({'import_time': 123.0}) is None, 123.0))
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'disable'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sync_calls == [
        {
            'card_id': 'pack/cover.png',
            'source_path': str(cover_path),
            'file_content_changed': False,
            'summary_changed': True,
            'resource_folder_changed': True,
        },
        {
            'card_id': 'pack/alt.png',
            'source_path': str(alt_path),
            'file_content_changed': False,
            'summary_changed': True,
            'resource_folder_changed': True,
        },
    ]
    assert saved_ui_payloads == [
        {
            'pack/cover.png': {
                'link': 'https://example.com/card',
                'resource_folder': 'hero-assets',
                'import_time': 123.0,
            },
            'pack/alt.png': {
                'link': 'https://example.com/card',
                'resource_folder': 'hero-assets',
                'import_time': 123.0,
            },
        }
    ]
    assert force_reload_calls == [{'reason': 'toggle_bundle_mode:disable'}]
    assert (bundle_dir / '.bundle').exists() is False


def test_toggle_bundle_mode_disable_still_enqueues_incremental_repairs_without_bundle_ui_entry(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    bundle_dir = cards_dir / 'pack'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    cover_path = bundle_dir / 'cover.png'
    alt_path = bundle_dir / 'alt.png'
    cover_path.write_bytes(b'cover')
    alt_path.write_bytes(b'alt')
    (bundle_dir / '.bundle').write_text('1', encoding='utf-8')

    saved_ui_payloads = []
    sync_calls = []
    force_reload_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(
        cards_api.os,
        'walk',
        lambda path: [(str(bundle_dir), [], ['cover.png', 'alt.png'])] if str(path) == str(bundle_dir) else [],
    )
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(
        cards_api,
        'save_ui_data',
        lambda payload: saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
    )
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0.0))
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/toggle_bundle_mode', json={'folder_path': 'pack', 'action': 'disable'})

    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert sync_calls == [
        {
            'card_id': 'pack/cover.png',
            'source_path': str(cover_path),
            'file_content_changed': False,
            'summary_changed': True,
            'resource_folder_changed': False,
        },
        {
            'card_id': 'pack/alt.png',
            'source_path': str(alt_path),
            'file_content_changed': False,
            'summary_changed': True,
            'resource_folder_changed': False,
        },
    ]
    assert saved_ui_payloads == []
    assert force_reload_calls == [{'reason': 'toggle_bundle_mode:disable'}]
    assert (bundle_dir / '.bundle').exists() is False


def test_api_move_folder_merge_bundle_preserves_version_remarks_and_rebuilds_projection(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    src_bundle_dir = cards_dir / 'src' / 'pack'
    dst_bundle_dir = cards_dir / 'dst' / 'pack'
    src_bundle_dir.mkdir(parents=True, exist_ok=True)
    dst_bundle_dir.mkdir(parents=True, exist_ok=True)

    (src_bundle_dir / '.bundle').write_text('1', encoding='utf-8')
    (dst_bundle_dir / '.bundle').write_text('1', encoding='utf-8')

    src_cover_path = src_bundle_dir / 'cover.png'
    src_alt_path = src_bundle_dir / 'alt.png'
    dst_cover_path = dst_bundle_dir / 'cover.png'
    dst_renamed_cover_path = dst_bundle_dir / 'cover_1.png'
    dst_alt_path = dst_bundle_dir / 'alt.png'

    _write_png_card(src_cover_path, name='Src Cover', tags=['src'])
    _write_png_card(src_alt_path, name='Src Alt', tags=['src'])
    _write_png_card(dst_cover_path, name='Dst Cover', tags=['dst'])

    ui_path.write_text(
        json.dumps(
            {
                'src/pack': {
                    ui_store_module.VERSION_REMARKS_KEY: {
                        'src/pack/cover.png': {'summary': 'src cover note'},
                        'src/pack/alt.png': {'summary': 'src alt note'},
                    }
                },
                'dst/pack': {
                    ui_store_module.VERSION_REMARKS_KEY: {
                        'dst/pack/cover.png': {'summary': 'dst cover note'},
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    _init_index_db(db_path)
    real_cache_conn = _open_row_db(db_path)

    with _open_row_db(db_path) as conn:
        _create_card_metadata_table(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('src/pack/cover.png', 'Src Cover', json.dumps(['src']), 'src/pack', 20.0, 11, 0, 0, '', '', '', '', '', '', 'src-cover-hash', 1),
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('src/pack/alt.png', 'Src Alt', json.dumps(['src']), 'src/pack', 10.0, 12, 0, 0, '', '', '', '', '', '', 'src-alt-hash', 1),
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, tags, category, last_modified, token_count, is_favorite, has_character_book, character_book_name, description, first_mes, mes_example, creator, char_version, file_hash, file_size) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('dst/pack/cover.png', 'Dst Cover', json.dumps(['dst']), 'dst/pack', 30.0, 13, 0, 0, '', '', '', '', '', '', 'dst-cover-hash', 1),
        )
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::src/pack/cover.png', 'card', str(src_cover_path), '', 'Src Cover', 'cover.png', 'src/pack', 'src/pack', 'physical', 0, 'src cover note', 20.0, 0.0, 11, 'src cover', 20.0, '', '20:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::src/pack/alt.png', 'card', str(src_alt_path), '', 'Src Alt', 'alt.png', 'src/pack', 'src/pack', 'physical', 0, 'src alt note', 10.0, 0.0, 12, 'src alt', 10.0, '', '10:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::dst/pack/cover.png', 'card', str(dst_cover_path), '', 'Dst Cover', 'cover.png', 'dst/pack', 'dst/pack', 'physical', 0, 'dst cover note', 30.0, 0.0, 13, 'dst cover', 30.0, '', '30:1'),
        )
        conn.commit()

    cache = GlobalMetadataCache()

    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cache_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_build_service, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cache_service, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: _open_row_db(db_path))
    monkeypatch.setattr(cache_service, 'get_db', lambda: real_cache_conn)
    monkeypatch.setattr(
        cache_service.os.path,
        'getmtime',
        lambda path: {
            str(dst_renamed_cover_path): 20.0,
            str(dst_alt_path): 10.0,
        }.get(str(path), 30.0),
    )
    monkeypatch.setattr(
        cache_service,
        'get_file_hash_and_size',
        lambda path: {
            str(dst_renamed_cover_path): ('src-cover-hash', 1),
            str(dst_alt_path): ('src-alt-hash', 1),
            str(dst_cover_path): ('dst-cover-hash', 1),
        }[str(path)],
    )
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _data: 77)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _data: (False, ''))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'global-lorebooks'), 'resources_dir': str(tmp_path / 'resources')})
    monkeypatch.setattr(cards_api.ctx, 'cache', cache, raising=False)

    cache.reload_from_db()

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {'success': True, 'new_path': 'dst/pack', 'mode': 'merge'}
    assert src_bundle_dir.exists() is False
    assert dst_cover_path.exists() is True
    assert dst_renamed_cover_path.exists() is True
    assert dst_alt_path.exists() is True

    ui_payload = json.loads(ui_path.read_text(encoding='utf-8'))
    assert 'src/pack' not in ui_payload
    assert ui_payload['dst/pack'][ui_store_module.VERSION_REMARKS_KEY] == {
        'dst/pack/cover.png': {'summary': 'dst cover note'},
        'dst/pack/cover_1.png': {'summary': 'src cover note'},
        'dst/pack/alt.png': {'summary': 'src alt note'},
    }

    with sqlite3.connect(db_path) as verify_conn:
        queued_before_worker = verify_conn.execute(
            'SELECT job_type, entity_id, payload_json, status FROM index_jobs ORDER BY entity_id, job_type'
        ).fetchall()

    assert queued_before_worker == [
        ('upsert_card', 'dst/pack/alt.png', json.dumps({'remove_entity_ids': ['src/pack/alt.png']}, ensure_ascii=False), 'pending'),
        ('upsert_world_owner', 'dst/pack/alt.png', json.dumps({'remove_owner_ids': ['src/pack/alt.png']}, ensure_ascii=False), 'pending'),
        ('upsert_card', 'dst/pack/cover_1.png', json.dumps({'remove_entity_ids': ['src/pack/cover.png']}, ensure_ascii=False), 'pending'),
        ('upsert_world_owner', 'dst/pack/cover_1.png', json.dumps({'remove_owner_ids': ['src/pack/cover.png']}, ensure_ascii=False), 'pending'),
    ]

    rebuild_calls = _run_index_worker_once(monkeypatch, db_path)
    cache.reload_from_db()

    with sqlite3.connect(db_path) as verify_conn:
        card_rows = verify_conn.execute(
            'SELECT id, category FROM card_metadata ORDER BY id'
        ).fetchall()
        card_entities = verify_conn.execute(
            "SELECT entity_id, source_path FROM index_entities_v2 WHERE generation = 1 AND entity_type = 'card' ORDER BY entity_id"
        ).fetchall()
        queued_after_worker = verify_conn.execute(
            'SELECT job_type, entity_id, payload_json, status FROM index_jobs ORDER BY entity_id, job_type'
        ).fetchall()

    assert rebuild_calls == []
    assert card_rows == [
        ('dst/pack/alt.png', 'dst/pack'),
        ('dst/pack/cover.png', 'dst/pack'),
        ('dst/pack/cover_1.png', 'dst/pack'),
    ]
    assert card_entities == [
        ('card::dst/pack/alt.png', str(dst_alt_path)),
        ('card::dst/pack/cover.png', str(dst_cover_path)),
        ('card::dst/pack/cover_1.png', str(dst_renamed_cover_path)),
    ]
    assert queued_after_worker == [
        ('upsert_card', 'dst/pack/alt.png', json.dumps({'remove_entity_ids': ['src/pack/alt.png']}, ensure_ascii=False), 'done'),
        ('upsert_world_owner', 'dst/pack/alt.png', json.dumps({'remove_owner_ids': ['src/pack/alt.png']}, ensure_ascii=False), 'done'),
        ('upsert_card', 'dst/pack/cover_1.png', json.dumps({'remove_entity_ids': ['src/pack/cover.png']}, ensure_ascii=False), 'done'),
        ('upsert_world_owner', 'dst/pack/cover_1.png', json.dumps({'remove_owner_ids': ['src/pack/cover.png']}, ensure_ascii=False), 'done'),
    ]

    assert cache.bundle_map == {'dst/pack': 'dst/pack/cover.png'}
    assert cache.id_map['dst/pack/cover.png']['is_bundle'] is True
    assert [version['id'] for version in cache.id_map['dst/pack/cover.png']['versions']] == [
        'dst/pack/cover.png',
        'dst/pack/cover_1.png',
        'dst/pack/alt.png',
    ]
    assert {
        version['id']: version.get('ui_summary', '')
        for version in cache.id_map['dst/pack/cover.png']['versions']
    } == {
        'dst/pack/cover.png': 'dst cover note',
        'dst/pack/cover_1.png': 'src cover note',
        'dst/pack/alt.png': 'src alt note',
    }

    real_cache_conn.close()
