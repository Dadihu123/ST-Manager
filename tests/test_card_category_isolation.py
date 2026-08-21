import json
import sys
import threading
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import cards as cards_api
from core.data import ui_store as ui_store_module


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def _write_ui_data(ui_path: Path, payload):
    ui_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _make_card(card_id, category, char_name, tags=None):
    return {
        'id': card_id,
        'category': category,
        'char_name': char_name,
        'filename': card_id.split('/')[-1],
        'tags': list(tags or []),
        'is_favorite': False,
        'ui_summary': '',
        'last_modified': 100.0,
        'import_time': 100.0,
        'token_count': 0,
    }


class _FakeCache:
    def __init__(self, cards, visible_folders=None, category_counts=None, global_tags=None):
        self.cards = list(cards)
        self.visible_folders = list(visible_folders or [])
        self.category_counts = dict(category_counts or {})
        self.global_tags = set(global_tags or [])
        self.lock = threading.Lock()
        self.initialized = True

    def reload_from_db(self):
        raise AssertionError('reload_from_db should not be called in isolated category tests')


def _install_fake_cache(monkeypatch, cards):
    fake_cache = _FakeCache(
        cards,
        visible_folders=['base', 'base/iso', 'base/iso/deep'],
        category_counts={'base': 1, 'base/iso': 1, 'base/iso/deep': 1},
        global_tags=[],
    )
    monkeypatch.setattr(cards_api.ctx, 'cache', fake_cache)
    return fake_cache


def test_normalize_isolated_categories_collapses_parents():
    payload = {'paths': ['  A/B  ', 'A', 'A\\C', '', 'A/B/C']}

    normalized = ui_store_module._normalize_isolated_categories(payload)

    assert normalized['paths'] == ['A']


def test_set_isolated_categories_persists_normalized_paths_and_skips_equivalent_save():
    ui_data = {}

    changed = ui_store_module.set_isolated_categories(ui_data, {'paths': ['foo/bar', 'foo', 'foo\\baz']})

    assert changed is True
    stored = ui_store_module.get_isolated_categories(ui_data)
    assert stored['paths'] == ['foo']
    assert stored['updated_at'] > 0

    changed_again = ui_store_module.set_isolated_categories(ui_data, {'paths': ['foo', 'foo/bar']})

    assert changed_again is False


def test_get_isolated_categories_falls_back_to_empty_structure_for_malformed_data():
    malformed = {'_isolated_categories_v1': 'broken'}

    normalized = ui_store_module.get_isolated_categories(malformed)

    assert normalized['paths'] == []
    assert normalized['updated_at'] == 0


def test_api_get_isolated_categories_returns_empty_state(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    client = _make_test_app().test_client()
    res = client.get('/api/isolated_categories')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['isolated_categories']['paths'] == []
    assert payload['isolated_categories']['updated_at'] == 0


def test_api_post_isolated_categories_normalizes_paths_and_returns_object_shape(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    client = _make_test_app().test_client()
    res = client.post('/api/isolated_categories', json={'paths': ['base/iso/deep', 'base\\iso', 'base/iso']})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['isolated_categories']['paths'] == ['base/iso']
    assert payload['isolated_categories']['updated_at'] > 0

    stored = json.loads(ui_path.read_text(encoding='utf-8'))
    assert stored['_isolated_categories_v1']['paths'] == ['base/iso']


def test_api_post_isolated_categories_rejects_invalid_payload(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    client = _make_test_app().test_client()
    res = client.post('/api/isolated_categories', json='broken')

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False


def test_list_cards_root_view_hides_isolated_subtree_and_returns_canonical_state(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {'_isolated_categories_v1': {'paths': ['base/iso/deep', 'base\\iso'], 'updated_at': 1}})
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    _install_fake_cache(
        monkeypatch,
        [
            _make_card('base/a.png', 'base', 'Base A'),
            _make_card('base/iso/x.png', 'base/iso', 'Iso X'),
            _make_card('base/iso/deep/y.png', 'base/iso/deep', 'Iso Y'),
        ],
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['base/a.png']
    assert payload['isolated_categories']['paths'] == ['base/iso']
    assert 'base/iso' in payload['all_folders']


def test_list_cards_ancestor_all_dirs_search_does_not_cross_isolated_boundary(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {'_isolated_categories_v1': {'paths': ['base/iso'], 'updated_at': 1}})
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    _install_fake_cache(
        monkeypatch,
        [
            _make_card('base/a.png', 'base', 'Base A'),
            _make_card('base/iso/x.png', 'base/iso', 'Iso X'),
        ],
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=base&search_scope=all_dirs&search=Iso%20X')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == []


def test_list_cards_full_search_does_not_cross_isolated_boundary_from_root(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {'_isolated_categories_v1': {'paths': ['base/iso'], 'updated_at': 1}})
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    _install_fake_cache(
        monkeypatch,
        [
            _make_card('base/a.png', 'base', 'Base A'),
            _make_card('base/iso/x.png', 'base/iso', 'Iso X'),
        ],
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search_scope=full&search=Iso%20X')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == []


def test_list_cards_self_view_restores_isolated_search_results(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {'_isolated_categories_v1': {'paths': ['base/iso'], 'updated_at': 1}})
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    _install_fake_cache(
        monkeypatch,
        [
            _make_card('base/a.png', 'base', 'Base A'),
            _make_card('base/iso/x.png', 'base/iso', 'Iso X'),
            _make_card('base/iso/deep/y.png', 'base/iso/deep', 'Iso Y'),
        ],
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=base/iso&search=Iso%20X')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['base/iso/x.png']
    assert payload['isolated_categories']['paths'] == ['base/iso']


def test_list_cards_global_tags_excludes_isolated_exclusive_tags(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {'_isolated_categories_v1': {'paths': ['base/iso'], 'updated_at': 1}})
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    fake_cache = _install_fake_cache(
        monkeypatch,
        [
            _make_card('base/a.png', 'base', 'Base A', tags=['public', 'shared']),
            _make_card('base/iso/x.png', 'base/iso', 'Iso X', tags=['secret', 'shared']),
        ],
    )
    fake_cache.global_tags = {'public', 'shared', 'secret'}

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert set(payload['global_tags']) == {'public', 'shared'}
    assert payload['global_tag_groups']
