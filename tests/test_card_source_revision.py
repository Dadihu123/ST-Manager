import json
import sys
from io import BytesIO
from threading import RLock
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def test_get_card_detail_returns_source_revision(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(
        json.dumps({'data': {'name': 'Hero', 'tags': ['alpha', 'beta']}}, ensure_ascii=False),
        encoding='utf-8',
    )

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        cards_api,
        'extract_card_info',
        lambda _path: {'data': {'name': 'Hero', 'tags': ['alpha', 'beta']}},
    )

    class _FakeCache:
        bundle_map = {}
        id_map = {}

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    client = _make_app().test_client()
    res = client.post('/api/get_card_detail', json={'id': 'hero.json'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['card']['source_revision']
    assert payload['card']['tags'] == ['alpha', 'beta']


def test_update_card_rejects_stale_source_revision(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))

    client = _make_app().test_client()
    res = client.post('/api/update_card', json={
        'id': 'hero.json',
        'char_name': 'Hero',
        'tags': [],
        'source_revision': '1:1',
    })

    assert res.status_code == 409
    payload = res.get_json()
    assert payload['success'] is False
    assert 'source_revision' in payload['msg']


def test_update_card_success_returns_refreshed_source_revision(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(
        json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False),
        encoding='utf-8',
    )

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'hero.json': {}})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api.os, 'utime', lambda *_args, **_kwargs: None)

    current_revision = cards_api.build_file_source_revision(str(card_path))
    refreshed_revision = 'refreshed:2'

    class _FakeCache:
        bundle_map = {}
        cards = []
        lock = RLock()

        def __init__(self):
            self.id_map = {}

        def update_card_data(self, card_id, update_payload):
            assert card_id == 'hero.json'
            updated = {
                'id': card_id,
                'image_url': '/cards_file/hero.json',
                **update_payload,
            }
            self.id_map[update_payload['id']] = updated
            return updated

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    revision_reads = {'count': 0}

    def _fake_build_file_source_revision(_path):
        revision_reads['count'] += 1
        if revision_reads['count'] == 1:
            return current_revision
        return refreshed_revision

    monkeypatch.setattr(cards_api, 'build_file_source_revision', _fake_build_file_source_revision)

    client = _make_app().test_client()
    res = client.post('/api/update_card', json={
        'id': 'hero.json',
        'char_name': 'Hero',
        'tags': [],
        'source_revision': current_revision,
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['updated_card']['source_revision'] == refreshed_revision


def test_change_image_json_to_png_enqueues_stale_cleanup_with_raw_id(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'resize_image_if_needed', lambda image: image)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cards_api, 'clean_sidecar_images', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'clean_thumbnail_cache', lambda *_args, **_kwargs: None)
    cache_calls = []
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: cache_calls.append((_args, _kwargs)) or {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)

    sync_calls = []
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})

    class _FakeCache:
        initialized = True
        id_map = {}
        cards = []
        bundle_map = {}
        category_counts = {}

        def delete_card_update(self, card_id):
            assert card_id == 'hero.json'

        def add_card_update(self, payload):
            return payload

        def update_card_data(self, _card_id, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    image_bytes = BytesIO()
    from PIL import Image
    Image.new('RGBA', (1, 1), (255, 0, 0, 255)).save(image_bytes, format='PNG')
    image_bytes.seek(0)

    client = _make_app().test_client()
    res = client.post(
        '/api/change_image',
        data={
            'id': 'hero.json',
            'image': (image_bytes, 'cover.png'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['new_id'] == 'hero.png'
    assert payload['source_revision']
    assert payload['updated_card']['source_revision'] == payload['source_revision']
    assert cache_calls == [
        (
            ('hero.png', str(cards_dir / 'hero.png')),
            {'remove_entity_ids': ['hero.json']},
        )
    ]
    assert sync_calls == [
        {
            'card_id': 'hero.png',
            'source_path': str(cards_dir / 'hero.png'),
            'file_content_changed': True,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['hero.json'],
            'remove_owner_ids': ['hero.json'],
        }
    ]
