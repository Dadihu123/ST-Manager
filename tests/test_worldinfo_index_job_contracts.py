import json
import sqlite3
import sys
from io import BytesIO
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.services import card_index_sync_service


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def test_change_image_runtime_contract_enqueues_cleanup_jobs_from_sync_service(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False), encoding='utf-8')

    db_path = tmp_path / 'cards_metadata.db'
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE card_metadata (id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO card_metadata (id) VALUES (?)', ('hero.json',))
        conn.commit()

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'resize_image_if_needed', lambda image: image)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cards_api, 'clean_sidecar_images', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'clean_thumbnail_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda *_args, **_kwargs: {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        },
    )
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)

    enqueue_calls = []
    monkeypatch.setattr(
        card_index_sync_service,
        'enqueue_index_job',
        lambda *args, **kwargs: enqueue_calls.append((args, kwargs)),
    )

    class _FakeCache:
        initialized = True
        category_counts = {}

        def __init__(self):
            self.id_map = {}
            self.cards = []
            self.bundle_map = {}

        def delete_card_update(self, card_id):
            assert card_id == 'hero.json'

        def add_card_update(self, payload):
            self.id_map[payload['id']] = payload
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
        data={'id': 'hero.json', 'image': (image_bytes, 'cover.png')},
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['new_id'] == 'hero.png'
    assert enqueue_calls == [
        (
            ('upsert_card',),
            {
                'entity_id': 'hero.png',
                'source_path': str(cards_dir / 'hero.png'),
                'payload': {'remove_entity_ids': ['hero.json']},
            },
        ),
        (
            ('upsert_world_owner',),
            {
                'entity_id': 'hero.png',
                'source_path': str(cards_dir / 'hero.png'),
                'payload': {'remove_owner_ids': ['hero.json']},
            },
        ),
    ]
