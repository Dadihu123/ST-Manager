import json
import sqlite3
import sys
import threading
from io import BytesIO
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import world_info as world_info_api
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.data import ui_store as ui_store_module


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(world_info_api.bp)
    return app


class _FakeCache:
    def __init__(self, cards):
        self.cards = list(cards)
        self.visible_folders = []
        self.category_counts = {}
        self.global_tags = set()
        self.lock = threading.Lock()
        self.initialized = True

    def reload_from_db(self):
        raise AssertionError('reload_from_db should not be called in worldinfo category tests')


class _LazyFakeCache(_FakeCache):
    def __init__(self, cards):
        super().__init__([])
        self._seed_cards = list(cards)
        self.initialized = False

    def reload_from_db(self):
        self.cards = list(self._seed_cards)
        self.initialized = True


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _activate_worldinfo_generation(db_path: Path, lorebooks_dir: Path, *, category='科幻'):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'"
        )
        source_path = lorebooks_dir / category / 'dragon.json'
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps({'name': 'Dragon Lore', 'entries': {}}, ensure_ascii=False), encoding='utf-8')
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, f'world::global::{category}/dragon.json', 'world_global', str(source_path), '', 'Dragon Lore', 'dragon.json', category, category, 'physical', 0, '', 300.0, 0.0, 0, 'dragon lore', 300.0, '', '300:1'),
        )
        for entity_type in ('world_global', 'world_all'):
            conn.execute(
                "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
                (1, 'worldinfo', entity_type, category, 1, 1),
            )
        conn.commit()


def _make_card(card_id, category, *, char_name='Lucy', has_character_book=False):
    card = {
        'id': card_id,
        'category': category,
        'char_name': char_name,
        'filename': card_id.split('/')[-1],
        'tags': [],
        'is_favorite': False,
        'ui_summary': '',
        'last_modified': 100.0,
        'import_time': 100.0,
        'token_count': 0,
        'has_character_book': has_character_book,
    }
    return card


def test_worldinfo_list_returns_display_category_for_global_resource_and_embedded(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json',
        {'name': 'Dragon Lore', 'entries': {}},
    )
    _write_json(
        resources_dir / 'lucy' / 'lorebooks' / 'companion.json',
        {'name': 'Companion Lore', 'entries': {}},
    )

    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    cards = [_make_card('cards/lucy.png', '科幻', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=all')

    assert res.status_code == 200
    payload = res.get_json()
    items = {item['type']: item for item in payload['items']}
    assert items['global']['display_category'] == '科幻/赛博朋克'
    assert items['global']['category_mode'] == 'physical'
    assert items['resource']['display_category'] == '科幻'
    assert items['resource']['category_mode'] == 'inherited'
    assert items['embedded']['display_category'] == '科幻'
    assert items['embedded']['category_mode'] == 'inherited'
    assert payload['folder_capabilities']['科幻']['has_physical_folder'] is True


def test_worldinfo_list_uses_owner_category_even_when_cache_lazy_loads(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(resources_dir / 'lucy' / 'lorebooks' / 'companion.json', {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    cards = [_make_card('cards/lucy.png', '科幻', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _LazyFakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=all')

    assert res.status_code == 200
    payload = res.get_json()
    items = {item['type']: item for item in payload['items']}
    assert items['resource']['display_category'] == '科幻'
    assert items['embedded']['display_category'] == '科幻'


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def execute(self, _query, _params=None):
        return _FakeCursor([
            {'id': 'cards/lucy.png', 'char_name': 'Lucy', 'character_book_name': 'Embedded Book', 'last_modified': 123.0},
        ])


def test_worldinfo_list_filters_by_display_category(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json',
        {'name': 'Dragon Lore', 'entries': {}},
    )
    _write_json(
        lorebooks_dir / '奇幻' / '精灵' / 'forest.json',
        {'name': 'Forest Lore', 'entries': {}},
    )

    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=global&category=科幻')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Dragon Lore']


def test_worldinfo_list_uses_override_category_for_resource_item(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'

    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {'resource_folder': 'lucy'},
                '_resource_item_categories_v1': {
                    'worldinfo': {
                        str(resource_file).replace('\\', '/').lower(): {
                            'category': '自定义分类',
                            'updated_at': 100,
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    cards = [_make_card('cards/lucy.png', '原始分类')]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=resource')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    resource_item = payload['items'][0]
    assert resource_item['display_category'] == '自定义分类'
    assert resource_item['category_mode'] == 'override'


def test_worldinfo_list_recomputes_inherited_categories_from_current_card_category(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        resources_dir / 'lucy' / 'lorebooks' / 'companion.json',
        {'name': 'Companion Lore', 'entries': {}},
    )
    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    cards = [_make_card('cards/lucy.png', '迁移后分类', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=all')

    assert res.status_code == 200
    payload = res.get_json()
    items = {item['type']: item for item in payload['items']}
    assert items['resource']['display_category'] == '迁移后分类'
    assert items['embedded']['display_category'] == '迁移后分类'


def test_worldinfo_override_category_stays_pinned_when_owner_card_category_changes(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'

    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {'resource_folder': 'lucy'},
                '_resource_item_categories_v1': {
                    'worldinfo': {
                        str(resource_file).replace('\\', '/').lower(): {
                            'category': '自定义分类',
                            'updated_at': 100,
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    cards = [_make_card('cards/lucy.png', '迁移后分类')]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=resource')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    resource_item = payload['items'][0]
    assert resource_item['display_category'] == '自定义分类'
    assert resource_item['category_mode'] == 'override'


def test_worldinfo_detail_supports_embedded_card_id(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    card_path = cards_dir / 'cards' / 'lucy.png'
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(tmp_path / 'resources')})
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}},
    )

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/detail', json={'id': 'embedded::cards/lucy.png', 'source_type': 'embedded'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['data']['name'] == 'Embedded Book'


def test_worldinfo_export_returns_attachment_for_global_file(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / '科幻' / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        global_file,
        {
            'name': 'Dragon Lore',
            'entries': {
                '0': {
                    'key': ['dragon'],
                    'content': 'A dragon entry',
                }
            },
        },
    )
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'global', 'file_path': str(global_file), 'id': 'global::科幻/dragon.json'},
    )

    assert res.status_code == 200
    assert 'application/json' in res.headers['Content-Type']
    assert 'attachment' in res.headers['Content-Disposition']

    payload = json.loads(res.data.decode('utf-8'))
    assert payload['name'] == 'Dragon Lore'
    assert payload['entries']['0']['key'] == ['dragon']


def test_worldinfo_export_returns_attachment_for_resource_file(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        resource_file,
        {
            'name': 'Companion Lore',
            'entries': {
                '0': {
                    'key': ['companion'],
                    'content': 'A companion entry',
                }
            },
        },
    )
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'resource', 'file_path': str(resource_file), 'id': 'resource::lucy::companion.json'},
    )

    assert res.status_code == 200
    assert 'application/json' in res.headers['Content-Type']
    assert 'attachment' in res.headers['Content-Disposition']

    payload = json.loads(res.data.decode('utf-8'))
    assert payload['name'] == 'Companion Lore'
    assert payload['entries']['0']['key'] == ['companion']


def test_worldinfo_export_returns_attachment_for_embedded_book(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    cards_dir = tmp_path / 'cards'
    card_path = cards_dir / 'cards' / 'lucy.png'
    ui_path = tmp_path / 'ui_data.json'

    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')

    cards = [_make_card('cards/lucy.png', '科幻', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {
            'data': {
                'character_book': {
                    'name': 'Embedded Book',
                    'entries': {
                        '0': {
                            'keys': ['embedded'],
                            'content': 'Embedded entry',
                            'enabled': True,
                        }
                    },
                }
            }
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'embedded', 'card_id': 'cards/lucy.png', 'id': 'embedded::cards/lucy.png'},
    )

    assert res.status_code == 200
    assert 'application/json' in res.headers['Content-Type']
    assert 'attachment' in res.headers['Content-Disposition']
    assert 'Embedded Book.json' in res.headers['Content-Disposition']

    payload = json.loads(res.data.decode('utf-8'))
    assert payload['name'] == 'Embedded Book'
    assert payload['entries']['0']['key'] == ['embedded']
    assert payload['entries']['0']['disable'] is False


def test_worldinfo_export_rejects_invalid_file_path(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'global', 'file_path': str(tmp_path / 'outside.json')},
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '非法路径'


def test_worldinfo_export_rejects_embedded_card_path_escape(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'embedded', 'card_id': '../outside.png'},
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '非法路径'


def test_worldinfo_export_rejects_unsupported_source_type(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'remote', 'file_path': str(global_file)},
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '不支持的世界书来源'


def test_worldinfo_export_rejects_global_source_with_resource_file(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'global', 'file_path': str(resource_file)},
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '非法路径'


def test_worldinfo_export_rejects_resource_source_with_global_file(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/export',
        json={'source_type': 'resource', 'file_path': str(global_file)},
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '非法路径'


def test_legacy_worldinfo_export_rejects_card_path_escape(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))

    client = _make_test_app().test_client()
    res = client.post('/api/export_worldbook_single', json={'card_id': '../outside.png'})

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '非法路径'


def test_worldinfo_list_and_detail_include_ui_summary(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    cards_dir = tmp_path / 'cards'
    global_file = lorebooks_dir / 'dragon.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    card_path = cards_dir / 'cards' / 'lucy.png'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {
                    'resource_folder': 'lucy',
                    'summary': 'card note',
                },
                '_worldinfo_notes_v1': {
                    f"global::{str(global_file).replace('\\', '/').lower()}": {'summary': 'global note'},
                    f"resource::{str(resource_file).replace('\\', '/').lower()}": {'summary': 'resource note'},
                    'embedded::cards/lucy.png': {'summary': 'embedded note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    cards = [_make_card('cards/lucy.png', '科幻', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}},
    )
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    list_res = client.get('/api/world_info/list?type=all')

    assert list_res.status_code == 200
    list_payload = list_res.get_json()
    items = {item['type']: item for item in list_payload['items']}
    assert items['global']['ui_summary'] == 'global note'
    assert items['resource']['ui_summary'] == 'resource note'
    assert items['embedded']['ui_summary'] == 'card note'

    detail_res = client.post('/api/world_info/detail', json={'id': 'embedded::cards/lucy.png', 'source_type': 'embedded'})
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()
    assert detail_payload['success'] is True
    assert detail_payload['ui_summary'] == 'card note'


def test_worldinfo_embedded_summary_falls_back_to_legacy_note_when_card_summary_missing(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_path = cards_dir / 'cards' / 'lucy.png'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {'resource_folder': 'lucy'},
                '_worldinfo_notes_v1': {
                    'embedded::cards/lucy.png': {'summary': 'embedded fallback note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    cards = [_make_card('cards/lucy.png', '科幻', has_character_book=True)]
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(
        world_info_api,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}},
    )
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    list_res = client.get('/api/world_info/list?type=embedded')

    assert list_res.status_code == 200
    payload = list_res.get_json()
    embedded_item = next(item for item in payload['items'] if item['id'] == 'embedded::cards/lucy.png')
    assert embedded_item['ui_summary'] == 'embedded fallback note'

    detail_res = client.post('/api/world_info/detail', json={'id': 'embedded::cards/lucy.png', 'source_type': 'embedded'})
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()
    assert detail_payload['success'] is True
    assert detail_payload['ui_summary'] == 'embedded fallback note'


def test_worldinfo_search_matches_local_note_summary(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(global_file).replace('\\', '/').lower()}": {'summary': 'secret planet'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=global&search=planet')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Dragon Lore']


def test_worldinfo_note_save_updates_ui_store_for_all_source_types(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()

    for payload in (
        {'source_type': 'global', 'file_path': str(global_file), 'summary': 'global note'},
        {'source_type': 'resource', 'file_path': str(resource_file), 'summary': 'resource note'},
        {'source_type': 'embedded', 'card_id': 'cards/lucy.png', 'summary': 'embedded note'},
    ):
        res = client.post('/api/world_info/note/save', json=payload)
        assert res.status_code == 200
        body = res.get_json()
        assert body['success'] is True
        assert body['ui_summary'] == payload['summary']

    saved = json.loads(ui_path.read_text(encoding='utf-8'))
    notes = saved['_worldinfo_notes_v1']
    assert notes[f"global::{str(global_file).replace('\\', '/').lower()}"]['summary'] == 'global note'
    assert notes[f"resource::{str(resource_file).replace('\\', '/').lower()}"]['summary'] == 'resource note'
    assert notes['embedded::cards/lucy.png']['summary'] == 'embedded note'


def test_worldinfo_note_save_enqueues_incremental_index_jobs_for_all_source_types(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {'resource_folder': 'lucy'},
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'resolve_resource_worldinfo_owner_card_ids', lambda _path: ['cards/lucy.png', 'cards/zeta.png'], raising=False)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()

    res = client.post('/api/world_info/note/save', json={
        'source_type': 'global',
        'file_path': str(global_file),
        'summary': 'global note',
    })
    assert res.status_code == 200

    res = client.post('/api/world_info/note/save', json={
        'source_type': 'resource',
        'file_path': str(resource_file),
        'summary': 'resource note',
    })
    assert res.status_code == 200

    res = client.post('/api/world_info/note/save', json={
        'source_type': 'embedded',
        'card_id': 'cards/lucy.png',
        'summary': 'embedded note',
    })
    assert res.status_code == 200

    assert job_calls == [
        ('upsert_worldinfo_path', {'source_path': str(global_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/lucy.png', 'source_path': str(resource_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/zeta.png', 'source_path': str(resource_file)}),
        ('upsert_world_embedded', {'entity_id': 'cards/lucy.png', 'source_path': ''}),
    ]


def test_update_card_ui_only_flag_uses_string_aware_bool_parsing():
    from core.api.v1 import cards as cards_api

    assert cards_api._coerce_request_bool(False) is False
    assert cards_api._coerce_request_bool(True) is True
    assert cards_api._coerce_request_bool('false') is False
    assert cards_api._coerce_request_bool('0') is False
    assert cards_api._coerce_request_bool('true') is True
    assert cards_api._coerce_request_bool('1') is True


def test_update_card_ui_only_updates_summary_without_touching_card_payload(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'keep-link', 'resource_folder': 'keep-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    captured = {}

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'kept description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'keep-link',
            'resource_folder': 'keep-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: captured.setdefault('write_called', True))
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'ui_summary': 'new ui note',
        'source_link': '',
        'resource_folder': '',
        'ui_only': True,
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['updated_card']['ui_summary'] == 'new ui note'
    assert 'write_called' not in captured

    saved = json.loads(ui_path.read_text(encoding='utf-8'))
    assert saved[card_rel]['summary'] == 'new ui note'
    assert saved[card_rel]['link'] == 'keep-link'
    assert saved[card_rel]['resource_folder'] == 'keep-folder'


def test_update_card_ui_only_can_clear_selected_ui_fields_when_opted_in(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'keep-link', 'resource_folder': 'keep-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    captured = {}

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'kept description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'keep-link',
            'resource_folder': 'keep-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: captured.setdefault('write_called', True))
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'ui_summary': 'new ui note',
        'source_link': '',
        'resource_folder': '',
        'ui_only': True,
        'ui_only_fields': ['source_link', 'resource_folder'],
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['updated_card']['ui_summary'] == 'new ui note'
    assert body['updated_card']['source_link'] == ''
    assert body['updated_card']['resource_folder'] == ''
    assert 'write_called' not in captured

    saved = json.loads(ui_path.read_text(encoding='utf-8'))
    assert saved[card_rel]['summary'] == 'new ui note'
    assert saved[card_rel]['link'] == ''
    assert saved[card_rel]['resource_folder'] == ''


def test_update_card_ui_only_does_not_refresh_card_cache_or_enqueue_world_owner(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'old-link', 'resource_folder': 'keep-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    cache_calls = []
    job_calls = []

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'kept description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'old-link',
            'resource_folder': 'keep-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: cache_calls.append((_args, _kwargs)))
    monkeypatch.setattr('core.services.card_index_sync_service.enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'ui_summary': 'new ui note',
        'source_link': 'new-link',
        'resource_folder': 'keep-folder',
        'ui_only': True,
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert cache_calls == []
    assert job_calls == [
        ('upsert_card', {'entity_id': card_rel, 'source_path': str(card_path)}),
    ]


def test_update_card_resource_folder_change_enqueues_world_owner_without_refreshing_card_cache(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'old-link', 'resource_folder': 'old-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    cache_calls = []
    job_calls = []

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'kept description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'old-link',
            'resource_folder': 'old-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: cache_calls.append((_args, _kwargs)))
    monkeypatch.setattr('core.services.card_index_sync_service.enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'ui_summary': 'old note',
        'source_link': 'old-link',
        'resource_folder': 'new-folder',
        'ui_only': True,
        'ui_only_fields': ['resource_folder'],
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert cache_calls == []
    assert job_calls == [
        ('upsert_world_owner', {'entity_id': card_rel, 'source_path': str(card_path)}),
    ]


def test_update_card_bundle_ui_only_resource_folder_change_enqueues_world_owner_without_refreshing_card_cache(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    bundle_dir = 'bundles/lucy'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({bundle_dir: {'link': 'old-link', 'resource_folder': 'old-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    cache_calls = []
    job_calls = []

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'kept description',
            'tags': ['tag'],
            'ui_summary': '',
            'source_link': 'old-link',
            'resource_folder': 'old-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    class _FakeBundleCursor:
        def fetchall(self):
            return []

    class _FakeBundleConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeBundleCursor()

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: cache_calls.append((_args, _kwargs)))
    monkeypatch.setattr('core.services.card_index_sync_service.enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.sqlite3, 'connect', lambda *_args, **_kwargs: _FakeBundleConn())
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'ui_summary': '',
        'source_link': '',
        'resource_folder': 'new-folder',
        'ui_only': True,
        'ui_only_fields': ['resource_folder'],
        'save_ui_to_bundle': True,
        'bundle_dir': bundle_dir,
        'version_id': card_rel,
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['updated_card']['resource_folder'] == 'new-folder'
    assert cache_calls == []
    assert job_calls == [
        ('upsert_world_owner', {'entity_id': card_rel, 'source_path': str(card_path)}),
    ]


def test_update_card_file_content_change_enqueues_embedded_worldinfo_refresh(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'old-link', 'resource_folder': 'keep-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    cache_calls = []
    job_calls = []
    written = {}

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'old description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'old-link',
            'resource_folder': 'keep-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'old description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: written.setdefault('called', True))
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: (
        cache_calls.append((_args, _kwargs)),
        {
            'cache_updated': True,
            'has_embedded_wi': True,
            'previous_has_embedded_wi': False,
        }
    )[1])
    monkeypatch.setattr('core.services.card_index_sync_service.enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'char_name': 'Lucy',
        'description': 'new description',
        'first_mes': 'hello',
        'mes_example': 'example',
        'personality': 'calm',
        'scenario': 'lab',
        'creator_notes': 'creator',
        'system_prompt': 'system',
        'post_history_instructions': 'post',
        'creator': 'tester',
        'character_version': 'v1',
        'tags': ['tag'],
        'extensions': {},
        'alternate_greetings': [],
        'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}},
        'ui_summary': 'old note',
        'source_link': 'old-link',
        'resource_folder': 'keep-folder',
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert written == {'called': True}
    assert len(cache_calls) == 1
    assert job_calls == [
        ('upsert_card', {'entity_id': card_rel, 'source_path': str(card_path)}),
        ('upsert_world_embedded', {'entity_id': card_rel, 'source_path': str(card_path)}),
        ('upsert_world_owner', {'entity_id': card_rel, 'source_path': str(card_path)}),
    ]


def test_update_card_file_content_change_with_existing_resource_folder_enqueues_owner_and_embedded_refresh(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    ui_path = tmp_path / 'ui_data.json'
    cards_dir = tmp_path / 'cards'
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'fake-card')
    ui_path.write_text(
        json.dumps({card_rel: {'summary': 'old note', 'link': 'old-link', 'resource_folder': 'keep-folder'}}, ensure_ascii=False),
        encoding='utf-8',
    )

    cache_calls = []
    job_calls = []
    written = {}

    def _fake_update_card_data(_raw_id, payload):
        card_obj = {
            'id': card_rel,
            'filename': 'lucy.png',
            'char_name': 'Lucy',
            'description': 'old description',
            'tags': ['tag'],
            'ui_summary': 'old note',
            'source_link': 'old-link',
            'resource_folder': 'keep-folder',
            'token_count': 0,
            'last_modified': 0,
            'import_time': 0,
            'dir_path': 'cards',
            'char_version': 'v1',
            'creator': 'tester',
            'image_url': '/cards_file/cards%2Flucy.png?t=1',
            'thumb_url': '/api/thumbnail/cards%2Flucy.png?t=1',
            'category': '',
        }
        card_obj.update(payload)
        return card_obj

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'old description',
            'first_mes': 'hello',
            'mes_example': 'example',
            'personality': 'calm',
            'scenario': 'lab',
            'creator_notes': 'creator',
            'system_prompt': 'system',
            'post_history_instructions': 'post',
            'creator': 'tester',
            'character_version': 'v1',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: written.setdefault('called', True))
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: (
        cache_calls.append((_args, _kwargs)),
        {
            'cache_updated': True,
            'has_embedded_wi': True,
            'previous_has_embedded_wi': False,
        }
    )[1])
    monkeypatch.setattr('core.services.card_index_sync_service.enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui_data, _ui_key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui_data, _ui_key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, 'get_last_sent_to_st', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', type('Cache', (), {
        'update_card_data': staticmethod(_fake_update_card_data),
        'id_map': {},
        'bundle_map': {},
        'lock': threading.Lock(),
    })())

    client = app.test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'char_name': 'Lucy',
        'description': 'new description',
        'first_mes': 'hello',
        'mes_example': 'example',
        'personality': 'calm',
        'scenario': 'lab',
        'creator_notes': 'creator',
        'system_prompt': 'system',
        'post_history_instructions': 'post',
        'creator': 'tester',
        'character_version': 'v1',
        'tags': ['tag'],
        'extensions': {},
        'alternate_greetings': [],
        'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}},
        'ui_summary': 'old note',
        'source_link': 'old-link',
        'resource_folder': 'keep-folder',
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert written == {'called': True}
    assert len(cache_calls) == 1
    assert job_calls == [
        ('upsert_card', {'entity_id': card_rel, 'source_path': str(card_path)}),
        ('upsert_world_embedded', {'entity_id': card_rel, 'source_path': str(card_path)}),
        ('upsert_world_owner', {'entity_id': card_rel, 'source_path': str(card_path)}),
    ]


def test_worldinfo_delete_removes_note_and_rejects_embedded_delete(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(global_file).replace('\\', '/').lower()}": {'summary': 'global note'},
                    'embedded::cards/lucy.png': {'summary': 'embedded note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'safe_move_to_trash', lambda path, _trash: Path(path).unlink() or True)

    client = _make_test_app().test_client()

    delete_res = client.post('/api/world_info/delete', json={'file_path': str(global_file), 'source_type': 'global'})
    assert delete_res.status_code == 200
    delete_payload = delete_res.get_json()
    assert delete_payload['success'] is True
    saved = json.loads(ui_path.read_text(encoding='utf-8'))
    assert f"global::{str(global_file).replace('\\', '/').lower()}" not in saved.get('_worldinfo_notes_v1', {})

    embedded_res = client.post('/api/world_info/delete', json={'source_type': 'embedded', 'card_id': 'cards/lucy.png'})
    assert embedded_res.status_code == 200
    embedded_payload = embedded_res.get_json()
    assert embedded_payload['success'] is False
    assert '内嵌' in embedded_payload['msg'] or 'embedded' in embedded_payload['msg'].lower()


def test_worldinfo_list_category_filter_is_cache_safe(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json',
        {'name': 'Dragon Lore', 'entries': {}},
    )
    _write_json(
        lorebooks_dir / '奇幻' / '精灵' / 'forest.json',
        {'name': 'Forest Lore', 'entries': {}},
    )

    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()

    warm = client.get('/api/world_info/list?type=global')
    assert warm.status_code == 200
    assert [item['name'] for item in warm.get_json()['items']] == ['Forest Lore', 'Dragon Lore']

    filtered = client.get('/api/world_info/list?type=global&category=科幻')
    assert filtered.status_code == 200
    assert [item['name'] for item in filtered.get_json()['items']] == ['Dragon Lore']


def test_worldinfo_resource_inherited_category_cache_recomputes_when_card_changes(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        resources_dir / 'lucy' / 'lorebooks' / 'companion.json',
        {'name': 'Companion Lore', 'entries': {}},
    )
    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    cache = _FakeCache([_make_card('cards/lucy.png', '旧分类')])
    monkeypatch.setattr(world_info_api.ctx, 'cache', cache)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()

    first = client.get('/api/world_info/list?type=resource')
    assert first.status_code == 200
    assert first.get_json()['items'][0]['display_category'] == '旧分类'

    cache.cards[0]['category'] = '新分类'

    second = client.get('/api/world_info/list?type=resource')
    assert second.status_code == 200
    assert second.get_json()['items'][0]['display_category'] == '新分类'


def test_worldinfo_list_cache_hit_returns_folder_metadata(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(
        lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json',
        {'name': 'Dragon Lore', 'entries': {}},
    )
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()

    cold = client.get('/api/world_info/list?type=global')
    assert cold.status_code == 200
    cold_payload = cold.get_json()
    assert cold_payload['all_folders'] == ['科幻', '科幻/赛博朋克']

    warm = client.get('/api/world_info/list?type=global')
    assert warm.status_code == 200
    warm_payload = warm.get_json()
    assert warm_payload['all_folders'] == ['科幻', '科幻/赛博朋克']
    assert warm_payload['category_counts']['科幻'] == 1
    assert warm_payload['folder_capabilities']['科幻']['has_physical_folder'] is True


def test_worldinfo_list_cache_invalidates_when_nested_global_file_changes(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    nested_file = lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json'

    _write_json(nested_file, {'name': 'Old Dragon Lore', 'entries': {}})
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()

    first = client.get('/api/world_info/list?type=global')
    assert first.status_code == 200
    assert [item['name'] for item in first.get_json()['items']] == ['Old Dragon Lore']

    _write_json(nested_file, {'name': 'New Dragon Lore', 'entries': {}})

    second = client.get('/api/world_info/list?type=global')
    assert second.status_code == 200
    assert [item['name'] for item in second.get_json()['items']] == ['New Dragon Lore']


def test_worldinfo_shared_resource_lore_dir_uses_deterministic_owner(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    shared_file = resources_dir / 'shared-pack' / 'lorebooks' / 'companion.json'

    _write_json(shared_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                'cards/zeta.png': {'resource_folder': 'shared-pack'},
                'cards/alpha.png': {'resource_folder': 'shared-pack'},
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())

    client = _make_test_app().test_client()

    for cards in (
        [_make_card('cards/zeta.png', '后出现分类', char_name='Zeta'), _make_card('cards/alpha.png', '稳定分类', char_name='Alpha')],
        [_make_card('cards/alpha.png', '稳定分类', char_name='Alpha'), _make_card('cards/zeta.png', '后出现分类', char_name='Zeta')],
    ):
        world_info_api.ctx.wi_list_cache.clear()
        monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache(cards))

        res = client.get('/api/world_info/list?type=resource')
        assert res.status_code == 200
        payload = res.get_json()
        assert len(payload['items']) == 1
        item = payload['items'][0]
        assert item['owner_card_id'] == 'cards/alpha.png'
        assert item['owner_card_name'] == 'Alpha'
        assert item['display_category'] == '稳定分类'


def test_worldinfo_save_rejects_new_resource_mode_safely(monkeypatch, tmp_path):
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(tmp_path / 'resources')})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/save',
        json={'save_mode': 'new_resource', 'name': 'Companion', 'content': {'entries': {}}},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert 'resource' in payload['msg'].lower()


def test_worldinfo_save_overwrite_enqueues_incremental_index_repair_for_global_and_resource_files(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})

    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'invalidate_wi_list_cache', lambda: None)
    monkeypatch.setattr(world_info_api, 'resolve_resource_worldinfo_owner_card_ids', lambda _path: ['cards/lucy.png', 'cards/zeta.png'], raising=False)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()

    global_res = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'overwrite',
            'file_path': str(global_file),
            'name': 'Dragon Lore',
            'content': {'name': 'Dragon Lore', 'entries': {}},
            'source_revision': world_info_api.build_file_source_revision(str(global_file)),
        },
    )
    assert global_res.status_code == 200
    assert global_res.get_json()['success'] is True

    resource_res = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'overwrite',
            'file_path': str(resource_file),
            'name': 'Companion Lore',
            'content': {'name': 'Companion Lore', 'entries': {}},
            'source_revision': world_info_api.build_file_source_revision(str(resource_file)),
        },
    )
    assert resource_res.status_code == 200
    assert resource_res.get_json()['success'] is True

    assert job_calls == [
        ('upsert_worldinfo_path', {'source_path': str(global_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/lucy.png', 'source_path': str(resource_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/zeta.png', 'source_path': str(resource_file)}),
    ]


def test_worldinfo_save_new_global_enqueues_incremental_index_repair(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'invalidate_wi_list_cache', lambda: None)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'new_global',
            'name': 'Dragon Lore',
            'content': {'name': 'Dragon Lore', 'entries': {}},
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['new_path']
    assert job_calls == [
        ('upsert_worldinfo_path', {'source_path': payload['new_path']}),
    ]


def test_worldinfo_save_rejects_embedded_paths_without_enqueuing_repair(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    cards_dir = tmp_path / 'cards'
    card_file = cards_dir / 'lucy.json'
    _write_json(card_file, {'name': 'Lucy', 'entries': {}})

    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(cards_dir), raising=False)
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'overwrite',
            'file_path': str(card_file),
            'name': 'Lucy',
            'content': {'name': 'Lucy', 'entries': {}},
            'source_revision': 'ignored-for-invalid-path',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '内嵌' in payload['msg'] or 'embedded' in payload['msg'].lower()
    assert job_calls == []


def test_worldinfo_save_does_not_enqueue_repair_when_write_fails(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})

    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'invalidate_wi_list_cache', lambda: None)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    def _boom(*_args, **_kwargs):
        raise OSError('disk full')

    monkeypatch.setattr('builtins.open', _boom)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'overwrite',
            'file_path': str(global_file),
            'name': 'Dragon Lore',
            'content': {'name': 'Dragon Lore', 'entries': {}},
            'source_revision': world_info_api.build_file_source_revision(str(global_file)),
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert job_calls == []


def test_worldinfo_save_returns_controlled_error_for_missing_json(monkeypatch, tmp_path):
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(tmp_path / 'resources')})

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/save', data='not json', content_type='text/plain')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert 'json' in payload['msg'].lower() or '请求' in payload['msg']


def test_move_worldinfo_global_item_moves_file_to_target_category(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_file = lorebooks_dir / '科幻' / 'dragon.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'id': 'global::科幻/dragon.json',
            'source_type': 'global',
            'file_path': str(source_file),
            'target_category': '奇幻/巨龙',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert source_file.exists() is False
    assert (lorebooks_dir / '奇幻' / '巨龙' / 'dragon.json').exists()


def test_move_worldinfo_global_item_remaps_note_and_refreshes_old_and_new_paths(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_file = lorebooks_dir / '科幻' / 'dragon.json'
    target_file = lorebooks_dir / '奇幻' / '巨龙' / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(source_file).replace('\\', '/').lower()}": {'summary': 'global note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    refresh_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda path, cfg: refresh_calls.append((path, cfg)))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'source_type': 'global',
            'file_path': str(source_file),
            'target_category': '奇幻/巨龙',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    notes = ui_store_module.get_worldinfo_notes(ui_store_module.load_ui_data())
    assert f"global::{str(source_file).replace('\\', '/').lower()}" not in notes
    assert notes[f"global::{str(target_file).replace('\\', '/').lower()}"]['summary'] == 'global note'
    assert refresh_calls == [
        (str(source_file), {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)}),
        (str(target_file), {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)}),
    ]


def test_move_worldinfo_global_item_returns_error_when_note_remap_persistence_fails(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_file = lorebooks_dir / '科幻' / 'dragon.json'
    target_file = lorebooks_dir / '奇幻' / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(source_file).replace('\\', '/').lower()}": {'summary': 'global note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'save_ui_data', lambda _data, **_kwargs: False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'source_type': 'global',
            'file_path': str(source_file),
            'target_category': '奇幻',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '保存' in payload['msg']
    assert source_file.exists() is True
    assert target_file.exists() is False


def test_rename_worldinfo_folder_returns_error_and_rolls_back_when_note_remap_persistence_fails(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_dir = lorebooks_dir / '科幻' / '旧分类'
    source_file = source_dir / 'dragon.json'
    target_dir = lorebooks_dir / '科幻' / '新分类'
    target_file = target_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(source_file).replace('\\', '/').lower()}": {'summary': 'folder note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'save_ui_data', lambda _data, **_kwargs: False)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/rename', json={'category': '科幻/旧分类', 'new_name': '新分类'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '保存' in payload['msg']
    assert source_dir.is_dir() is True
    assert source_file.exists() is True
    assert target_dir.exists() is False
    assert target_file.exists() is False


def test_worldinfo_delete_enqueues_incremental_index_repair_for_global_and_resource_files(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / 'dragon.json'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'

    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(global_file).replace('\\', '/').lower()}": {'summary': 'global note'},
                    f"resource::{str(resource_file).replace('\\', '/').lower()}": {'summary': 'resource note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    job_calls = []

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, 'invalidate_wi_list_cache', lambda: None)
    monkeypatch.setattr(world_info_api, 'resolve_resource_worldinfo_owner_card_ids', lambda _path: ['cards/lucy.png', 'cards/zeta.png'], raising=False)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)
    monkeypatch.setattr(world_info_api, 'safe_move_to_trash', lambda path, _trash: Path(path).unlink() or True)

    client = _make_test_app().test_client()

    global_res = client.post('/api/world_info/delete', json={'file_path': str(global_file), 'source_type': 'global'})
    assert global_res.status_code == 200
    assert global_res.get_json()['success'] is True

    resource_res = client.post('/api/world_info/delete', json={'file_path': str(resource_file), 'source_type': 'resource'})
    assert resource_res.status_code == 200
    assert resource_res.get_json()['success'] is True

    embedded_res = client.post('/api/world_info/delete', json={'source_type': 'embedded', 'card_id': 'cards/lucy.png'})
    assert embedded_res.status_code == 200
    assert embedded_res.get_json()['success'] is False

    assert job_calls == [
        ('upsert_worldinfo_path', {'source_path': str(global_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/lucy.png', 'source_path': str(resource_file)}),
        ('upsert_world_owner', {'entity_id': 'cards/zeta.png', 'source_path': str(resource_file)}),
    ]


def test_move_worldinfo_resource_item_sets_override_without_moving_file(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    job_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([_make_card('cards/lucy.png', '原始分类')]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'resolve_resource_worldinfo_owner_card_ids', lambda _path: ['cards/lucy.png'], raising=False)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'id': 'resource::lucy::companion',
            'source_type': 'resource',
            'file_path': str(resource_file),
            'target_category': '自定义分类',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert resource_file.exists() is True
    saved_payload = ui_store_module.get_resource_item_categories(ui_store_module.load_ui_data())
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file))
    assert saved_payload['worldinfo'][path_key]['category'] == '自定义分类'
    assert job_calls == [
        ('upsert_world_owner', {'entity_id': 'cards/lucy.png', 'source_path': str(resource_file)}),
    ]


def test_move_embedded_worldinfo_category_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(tmp_path / 'resources')})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'id': 'embedded::cards/lucy.png',
            'source_type': 'embedded',
            'target_category': '新分类',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '角色卡' in payload['msg'] or 'embedded' in payload['msg'].lower()


def test_reset_worldinfo_resource_category_override_restores_inherited_category(monkeypatch, tmp_path):
    resources_dir = tmp_path / 'resources'
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    ui_path = tmp_path / 'ui_data.json'
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file))
    _write_json(resource_file, {'name': 'Companion Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                'cards/lucy.png': {'resource_folder': 'lucy'},
                '_resource_item_categories_v1': {
                    'worldinfo': {
                        path_key: {'category': '自定义分类', 'updated_at': 100},
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    job_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([_make_card('cards/lucy.png', '继承分类')]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'resolve_resource_worldinfo_owner_card_ids', lambda _path: ['cards/lucy.png'], raising=False)
    monkeypatch.setattr(world_info_api, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/reset',
        json={
            'id': 'resource::lucy::companion',
            'source_type': 'resource',
            'file_path': str(resource_file),
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    saved_payload = ui_store_module.get_resource_item_categories(ui_store_module.load_ui_data())
    assert path_key not in saved_payload['worldinfo']
    assert job_calls == [
        ('upsert_world_owner', {'entity_id': 'cards/lucy.png', 'source_path': str(resource_file)}),
    ]


def test_create_worldinfo_folder_creates_real_subdirectory(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/create', json={'parent_category': '科幻', 'name': '赛博朋克'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (lorebooks_dir / '科幻' / '赛博朋克').is_dir()
    assert '科幻' in payload['all_folders']
    assert '科幻/赛博朋克' in payload['all_folders']
    assert payload['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert payload['folder_capabilities']['科幻/赛博朋克']['can_delete_physical_folder'] is True


def test_rename_worldinfo_folder_renames_real_subdirectory(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    (lorebooks_dir / '科幻' / '旧分类').mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/rename', json={'category': '科幻/旧分类', 'new_name': '新分类'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (lorebooks_dir / '科幻' / '旧分类').exists() is False
    assert (lorebooks_dir / '科幻' / '新分类').is_dir()


def test_rename_worldinfo_folder_reindexes_contained_files_and_remaps_notes(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_dir = lorebooks_dir / '科幻' / '旧分类'
    source_file = source_dir / 'dragon.json'
    target_dir = lorebooks_dir / '科幻' / '新分类'
    target_file = target_dir / 'dragon.json'
    ui_path = tmp_path / 'ui_data.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})
    ui_path.write_text(
        json.dumps(
            {
                '_worldinfo_notes_v1': {
                    f"global::{str(source_file).replace('\\', '/').lower()}": {'summary': 'folder note'},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    refresh_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda path, cfg: refresh_calls.append((path, cfg)))

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/rename', json={'category': '科幻/旧分类', 'new_name': '新分类'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert refresh_calls == [
        (str(source_file), {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)}),
        (str(target_file), {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)}),
    ]
    notes = ui_store_module.get_worldinfo_notes(ui_store_module.load_ui_data())
    assert f"global::{str(source_file).replace('\\', '/').lower()}" not in notes
    assert notes[f"global::{str(target_file).replace('\\', '/').lower()}"]['summary'] == 'folder note'


def test_rename_worldinfo_folder_suppresses_fs_events(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    (lorebooks_dir / '科幻' / '旧分类').mkdir(parents=True, exist_ok=True)
    suppress_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda seconds=0: suppress_calls.append(seconds))

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/rename', json={'category': '科幻/旧分类', 'new_name': '新分类'})

    assert res.status_code == 200
    assert suppress_calls


def test_delete_empty_worldinfo_folder_removes_directory(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    target_dir = lorebooks_dir / '科幻' / '待删除'
    target_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/delete', json={'category': '科幻/待删除'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert target_dir.exists() is False


def test_indexed_worldinfo_folder_create_refreshes_folder_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    _activate_worldinfo_generation(db_path, lorebooks_dir)

    monkeypatch.setattr(world_info_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {
        'worldinfo_list_use_index': True,
        'world_info_dir': str(lorebooks_dir),
        'resources_dir': str(resources_dir),
    })

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/create', json={'parent_category': '科幻', 'name': '赛博朋克'})
    listed = client.get('/api/world_info/list?type=global&page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert listed.status_code == 200
    list_payload = listed.get_json()
    assert '科幻/赛博朋克' in list_payload['all_folders']
    assert list_payload['folder_capabilities']['科幻/赛博朋克']['has_physical_folder'] is True
    assert list_payload['folder_capabilities']['科幻/赛博朋克']['can_delete_physical_folder'] is True


def test_indexed_worldinfo_folder_rename_refreshes_folder_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    _activate_worldinfo_generation(db_path, lorebooks_dir)
    (lorebooks_dir / '科幻' / '旧分类').mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {
        'worldinfo_list_use_index': True,
        'world_info_dir': str(lorebooks_dir),
        'resources_dir': str(resources_dir),
    })

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/rename', json={'category': '科幻/旧分类', 'new_name': '新分类'})
    listed = client.get('/api/world_info/list?type=global&page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert listed.status_code == 200
    list_payload = listed.get_json()
    assert '科幻/旧分类' not in list_payload['all_folders']
    assert '科幻/新分类' in list_payload['all_folders']
    assert list_payload['folder_capabilities']['科幻/新分类']['can_delete_physical_folder'] is True


def test_indexed_worldinfo_folder_delete_refreshes_folder_metadata(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    _activate_worldinfo_generation(db_path, lorebooks_dir)
    (lorebooks_dir / '科幻' / '待删除').mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {
        'worldinfo_list_use_index': True,
        'world_info_dir': str(lorebooks_dir),
        'resources_dir': str(resources_dir),
    })

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/delete', json={'category': '科幻/待删除'})
    listed = client.get('/api/world_info/list?type=global&page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert listed.status_code == 200
    list_payload = listed.get_json()
    assert '科幻/待删除' not in list_payload['all_folders']


def test_worldinfo_folder_mutation_returns_warning_when_stats_refresh_fails(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {
        'worldinfo_list_use_index': True,
        'world_info_dir': str(lorebooks_dir),
        'resources_dir': str(resources_dir),
    })
    monkeypatch.setattr(world_info_api, '_refresh_worldinfo_folder_stats', lambda _cfg=None: '索引分类统计刷新失败', raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/folders/create', json={'parent_category': '科幻', 'name': '赛博朋克'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['warning'] == '索引分类统计刷新失败'
    assert (lorebooks_dir / '科幻' / '赛博朋克').is_dir()


def test_create_worldinfo_uses_target_category_subfolder(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/create',
        json={'name': 'New World Info', 'target_category': '科幻/赛博朋克'},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['path'].endswith('科幻/赛博朋克/New World Info.json')
    assert (lorebooks_dir / '科幻' / '赛博朋克' / 'New World Info.json').exists()
    assert payload['item']['id'] == 'global::科幻/赛博朋克/New World Info.json'


def test_create_worldinfo_suppresses_fs_events(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    suppress_calls = []
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda seconds=0: suppress_calls.append(seconds))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/create',
        json={'name': 'New World Info', 'target_category': '科幻/赛博朋克'},
    )

    assert res.status_code == 200
    assert suppress_calls


def test_create_worldinfo_enqueues_incremental_refresh(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    refresh_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda path, cfg: refresh_calls.append((path, cfg)))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/create',
        json={'name': 'New World Info', 'target_category': '科幻/赛博朋克'},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert refresh_calls == [
        (
            str(lorebooks_dir / '科幻' / '赛博朋克' / 'New World Info.json'),
            {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
        )
    ]


def test_move_worldinfo_category_reset_rejects_non_resource_item(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_file = lorebooks_dir / '科幻' / 'dragon.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()

    move_res = client.post(
        '/api/world_info/category/move',
        json={
            'id': 'global::科幻/dragon.json',
            'source_type': 'global',
            'file_path': str(source_file),
            'target_category': '自定义分类',
            'mode': 'resource_only',
        },
    )
    assert move_res.status_code == 200
    move_payload = move_res.get_json()
    assert move_payload['success'] is False
    assert 'resource' in move_payload['msg'].lower() or '资源' in move_payload['msg']

    reset_res = client.post(
        '/api/world_info/category/reset',
        json={
            'id': 'global::科幻/dragon.json',
            'source_type': 'global',
            'file_path': str(source_file),
        },
    )
    assert reset_res.status_code == 200
    reset_payload = reset_res.get_json()
    assert reset_payload['success'] is False
    assert 'resource' in reset_payload['msg'].lower() or '资源' in reset_payload['msg']


def test_move_global_worldinfo_category_enqueues_incremental_refresh(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    source_file = lorebooks_dir / '科幻' / 'dragon.json'
    target_file = lorebooks_dir / '奇幻' / 'dragon.json'
    _write_json(source_file, {'name': 'Dragon Lore', 'entries': {}})
    refresh_calls = []

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda path, cfg: refresh_calls.append((path, cfg)))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/world_info/category/move',
        json={
            'source_type': 'global',
            'file_path': str(source_file),
            'target_category': '奇幻',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert Path(payload['path']) == target_file
    assert refresh_calls == [
        (
            str(source_file),
            {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
        ),
        (
            str(target_file),
            {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
        )
    ]


def test_upload_worldinfo_uses_target_category_subfolder(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/upload_world_info',
        data={
            'target_category': '科幻/赛博朋克',
            'files': (BytesIO(json.dumps({'name': 'Dragon Lore', 'entries': {}}).encode('utf-8')), 'dragon.json'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json').exists()


def test_upload_worldinfo_enqueues_refresh_for_each_saved_file(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    refresh_calls = []
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda path, cfg: refresh_calls.append((path, cfg)))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/upload_world_info',
        data={
            'target_category': '科幻/赛博朋克',
            'files': [
                (BytesIO(json.dumps({'name': 'Dragon Lore', 'entries': {}}).encode('utf-8')), 'dragon.json'),
                (BytesIO(json.dumps({'name': 'Phoenix Lore', 'entries': {}}).encode('utf-8')), 'phoenix.json'),
            ],
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert refresh_calls == [
        (
            str(lorebooks_dir / '科幻' / '赛博朋克' / 'dragon.json'),
            {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
        ),
        (
            str(lorebooks_dir / '科幻' / '赛博朋克' / 'phoenix.json'),
            {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)},
        ),
    ]


def test_upload_worldinfo_suppresses_fs_events(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    suppress_calls = []
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'suppress_fs_events', lambda seconds=0: suppress_calls.append(seconds))

    client = _make_test_app().test_client()
    res = client.post(
        '/api/upload_world_info',
        data={
            'target_category': '科幻/赛博朋克',
            'files': (BytesIO(json.dumps({'name': 'Dragon Lore', 'entries': {}}).encode('utf-8')), 'dragon.json'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    assert suppress_calls


def test_upload_worldinfo_from_non_global_context_requires_explicit_fallback_confirmation_contract(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/upload_world_info',
        data={
            'source_context': 'resource',
            'files': (BytesIO(json.dumps({'name': 'Dragon Lore', 'entries': {}}).encode('utf-8')), 'dragon.json'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['requires_global_fallback_confirmation'] is True
    assert not any(lorebooks_dir.rglob('dragon.json'))


def test_worldinfo_list_includes_empty_physical_folders_in_metadata(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    empty_dir = lorebooks_dir / '科幻' / '空目录'
    empty_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=global')

    assert res.status_code == 200
    payload = res.get_json()
    assert '科幻' in payload['all_folders']
    assert '科幻/空目录' in payload['all_folders']
    assert payload['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert payload['folder_capabilities']['科幻/空目录']['can_delete_physical_folder'] is True


def test_worldinfo_list_keeps_global_folder_tree_when_category_filter_is_active(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    _write_json(lorebooks_dir / '科幻' / 'dragon.json', {'name': 'Dragon Lore', 'entries': {}})
    (lorebooks_dir / '奇幻' / '空目录').mkdir(parents=True, exist_ok=True)
    _write_json(resources_dir / 'lucy' / 'lorebooks' / 'companion.json', {'name': 'Companion Lore', 'entries': {}})
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps({'cards/lucy.png': {'resource_folder': 'lucy'}}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([_make_card('cards/lucy.png', '日常')]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=all&category=%E7%A7%91%E5%B9%BB')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Dragon Lore']
    assert '科幻' in payload['all_folders']
    assert '奇幻' in payload['all_folders']
    assert '奇幻/空目录' in payload['all_folders']
    assert '日常' in payload['all_folders']
    assert payload['folder_capabilities']['奇幻']['has_physical_folder'] is True


def test_worldinfo_root_folder_capabilities_allow_create_subcategory(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    lorebooks_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _FakeConn())
    world_info_api.ctx.wi_list_cache.clear()

    client = _make_test_app().test_client()
    res = client.get('/api/world_info/list?type=global')

    assert res.status_code == 200
    payload = res.get_json()
    root_caps = payload['folder_capabilities'].get('', {})
    assert root_caps.get('has_physical_folder') is True
    assert root_caps.get('can_create_child_folder') is True


def test_worldinfo_resource_override_rejects_non_resource_path_even_with_resource_source_type(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    global_file = lorebooks_dir / '科幻' / 'dragon.json'
    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {}})

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'load_config', lambda: {'world_info_dir': str(lorebooks_dir), 'resources_dir': str(resources_dir)})

    client = _make_test_app().test_client()

    move_res = client.post(
        '/api/world_info/category/move',
        json={
            'id': 'resource::fake::dragon',
            'source_type': 'resource',
            'file_path': str(global_file),
            'target_category': '自定义分类',
        },
    )
    assert move_res.status_code == 200
    move_payload = move_res.get_json()
    assert move_payload['success'] is False
    assert '非法路径' in move_payload['msg'] or '资源' in move_payload['msg']

    reset_res = client.post(
        '/api/world_info/category/reset',
        json={
            'id': 'resource::fake::dragon',
            'source_type': 'resource',
            'file_path': str(global_file),
        },
    )
    assert reset_res.status_code == 200
    reset_payload = reset_res.get_json()
    assert reset_payload['success'] is False
    assert '非法路径' in reset_payload['msg'] or '资源' in reset_payload['msg']
