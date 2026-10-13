"""资源目录改名（详情页）的服务层与接口契约。"""

import json
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import system as system_api
from core.data.ui_store import (
    rename_resource_item_category_path_prefix,
    rename_resource_worldinfo_note_path_prefix,
)
from core.services import card_service


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app


class _FakeCache:
    def __init__(self, bundle_map=None):
        self.id_map = {}
        self.bundle_map = dict(bundle_map or {})
        self.updates = []

    def update_card_data(self, card_id, payload):
        self.updates.append((card_id, dict(payload)))
        self.id_map.setdefault(card_id, {}).update(payload)
        return self.id_map[card_id]


def _setup_rename_test(monkeypatch, tmp_path, *, ui_state, bundle_map=None, cache=None):
    resources_root = tmp_path / 'resources'
    resources_root.mkdir(parents=True, exist_ok=True)
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)

    ui_data = json.loads(json.dumps(ui_state))
    saved = {'count': 0}
    history_moves = []
    sync_calls = []
    fake_cache = cache if cache is not None else _FakeCache(bundle_map=bundle_map)

    def _save(payload, **_kwargs):
        saved['count'] += 1
        # payload 通常就是 ui_data 本身，必须先快照再清空。
        snapshot = json.loads(json.dumps(payload))
        ui_data.clear()
        ui_data.update(snapshot)
        return True

    monkeypatch.setattr(card_service, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': str(resources_root)})
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(card_service, 'save_ui_data', _save)
    monkeypatch.setattr(card_service, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        card_service,
        'move_entry_history_scope',
        lambda **kwargs: history_moves.append(kwargs) or 0,
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: sync_calls.append(kwargs) or {},
    )
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache)

    return {
        'resources_root': resources_root,
        'ui_data': ui_data,
        'saved': saved,
        'history_moves': history_moves,
        'sync_calls': sync_calls,
        'cache': fake_cache,
    }


def test_rename_card_resource_folder_moves_directory_and_remaps_ui_data(monkeypatch, tmp_path):
    # ui_data 里的备注/分类键都经过 normcase 归一化：小写 + 正斜杠。
    old_book_path = str(
        tmp_path / 'resources' / 'hero-assets' / 'lorebooks' / 'companion.json'
    ).replace('\\', '/').lower()
    ui_state = {
        'hero.png': {'resource_folder': 'hero-assets'},
        '_worldinfo_notes_v1': {
            f'resource::{old_book_path}': {'summary': 'resource note', 'updated_at': 1}
        },
        '_resource_item_categories_v1': {
            'worldinfo': {
                old_book_path: {'category': 'override-cat', 'updated_at': 1}
            }
        },
    }
    env = _setup_rename_test(monkeypatch, tmp_path, ui_state=ui_state)

    old_dir = env['resources_root'] / 'hero-assets'
    (old_dir / 'lorebooks').mkdir(parents=True)
    (old_dir / 'lorebooks' / 'companion.json').write_text('{"name": "Book", "entries": {}}', encoding='utf-8')
    (old_dir / 'cover.png').write_bytes(b'png')

    result = card_service.rename_card_resource_folder('hero.png', 'hero-renamed')

    assert result['success'] is True
    assert result['renamed'] is True
    assert result['resource_folder'] == 'hero-renamed'

    new_dir = env['resources_root'] / 'hero-renamed'
    assert new_dir.is_dir()
    assert old_dir.exists() is False
    assert (new_dir / 'lorebooks' / 'companion.json').is_file()
    assert (new_dir / 'cover.png').is_file()

    assert env['ui_data']['hero.png']['resource_folder'] == 'hero-renamed'
    assert env['saved']['count'] == 1

    # 世界书备注与资源条目分类都按新的绝对路径重挂。
    new_book_path = str(new_dir / 'lorebooks' / 'companion.json').replace('\\', '/').lower()
    assert list(env['ui_data']['_worldinfo_notes_v1'].keys()) == [f'resource::{new_book_path}']
    assert list(env['ui_data']['_resource_item_categories_v1']['worldinfo'].keys()) == [new_book_path]
    assert (
        env['ui_data']['_resource_item_categories_v1']['worldinfo'][new_book_path]['category']
        == 'override-cat'
    )

    # 缓存与索引同步都带上新目录。
    assert env['cache'].updates == [('hero.png', {'resource_folder': 'hero-renamed'})]
    assert len(env['sync_calls']) == 1
    assert env['sync_calls'][0]['resource_folder_changed'] is True
    assert env['sync_calls'][0]['card_id'] == 'hero.png'

    # 资源世界书的条目历史按绝对路径迁移。
    assert len(env['history_moves']) == 1
    move = env['history_moves'][0]
    assert move['source_type'] == 'resource'
    assert move['target_file_path'] == str(new_dir / 'lorebooks' / 'companion.json')
    assert move['file_path'] == str(old_dir / 'lorebooks' / 'companion.json')


def test_rename_card_resource_folder_rejects_reserved_and_conflicting_names(monkeypatch, tmp_path):
    env = _setup_rename_test(
        monkeypatch,
        tmp_path,
        ui_state={'hero.png': {'resource_folder': 'hero-assets'}},
    )
    (env['resources_root'] / 'hero-assets').mkdir(parents=True)
    (env['resources_root'] / 'taken').mkdir(parents=True)

    reserved = card_service.rename_card_resource_folder('hero.png', 'lorebooks')
    assert reserved['success'] is False
    assert '保留' in reserved['msg']

    conflict = card_service.rename_card_resource_folder('hero.png', 'taken')
    assert conflict['success'] is False
    assert '已存在' in conflict['msg']

    traversal = card_service.rename_card_resource_folder('hero.png', '../escape')
    assert traversal['success'] is False

    empty = card_service.rename_card_resource_folder('hero.png', '   ')
    assert empty['success'] is False

    assert (env['resources_root'] / 'hero-assets').is_dir()
    assert env['saved']['count'] == 0
    assert env['sync_calls'] == []


def test_rename_card_resource_folder_requires_existing_binding(monkeypatch, tmp_path):
    env = _setup_rename_test(monkeypatch, tmp_path, ui_state={'hero.png': {}})

    missing = card_service.rename_card_resource_folder('hero.png', 'anything')
    assert missing['success'] is False
    assert missing['msg'] == '未设置资源目录'

    unknown_card = card_service.rename_card_resource_folder('ghost.png', 'anything')
    assert unknown_card['success'] is False
    assert unknown_card['msg'] == '未设置资源目录'

    assert env['saved']['count'] == 0


def test_rename_card_resource_folder_supports_absolute_binding(monkeypatch, tmp_path):
    abs_dir = tmp_path / 'external-assets'
    abs_dir.mkdir(parents=True)
    (abs_dir / 'cover.png').write_bytes(b'png')

    env = _setup_rename_test(
        monkeypatch,
        tmp_path,
        ui_state={'hero.png': {'resource_folder': str(abs_dir)}},
    )

    result = card_service.rename_card_resource_folder('hero.png', 'external-renamed')

    assert result['success'] is True
    assert result['resource_folder'] == 'external-renamed'
    assert (tmp_path / 'external-renamed').is_dir()
    assert abs_dir.exists() is False
    assert env['ui_data']['hero.png']['resource_folder'] == 'external-renamed'


def test_rename_card_resource_folder_noop_when_name_unchanged(monkeypatch, tmp_path):
    env = _setup_rename_test(
        monkeypatch,
        tmp_path,
        ui_state={'hero.png': {'resource_folder': 'hero-assets'}},
    )
    (env['resources_root'] / 'hero-assets').mkdir(parents=True)

    result = card_service.rename_card_resource_folder('hero.png', 'hero-assets')

    assert result['success'] is True
    assert result['renamed'] is False
    assert env['saved']['count'] == 0
    assert env['sync_calls'] == []


def test_rename_card_resource_folder_updates_bundle_main_card_cache(monkeypatch, tmp_path):
    env = _setup_rename_test(
        monkeypatch,
        tmp_path,
        ui_state={'pack': {'resource_folder': 'pack-assets'}},
        bundle_map={'pack': 'pack/main.png'},
    )
    (env['resources_root'] / 'pack-assets').mkdir(parents=True)

    # bundle 场景下 ui_key 由 resolve_ui_key 解析为目录键。
    monkeypatch.setattr(card_service, 'resolve_ui_key', lambda card_id: 'pack')

    result = card_service.rename_card_resource_folder('pack/main.png', 'pack-renamed')

    assert result['success'] is True
    assert env['cache'].updates == [('pack/main.png', {'resource_folder': 'pack-renamed'})]
    assert env['sync_calls'][0]['card_id'] == 'pack/main.png'


def test_rename_resource_folder_endpoint_returns_structured_result(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        system_api,
        'rename_card_resource_folder',
        lambda card_id, new_name: calls.append((card_id, new_name))
        or {'success': True, 'resource_folder': new_name, 'resource_path': '/tmp/x', 'renamed': True},
    )

    client = _make_test_app().test_client()

    ok = client.post(
        '/api/rename_resource_folder',
        json={'card_id': 'cards/hero.png', 'new_name': 'hero-renamed'},
    )
    assert ok.status_code == 200
    assert ok.get_json()['resource_folder'] == 'hero-renamed'
    assert calls == [('cards/hero.png', 'hero-renamed')]

    missing_name = client.post('/api/rename_resource_folder', json={'card_id': 'cards/hero.png'})
    assert missing_name.status_code == 400
    assert missing_name.get_json()['success'] is False

    missing_card = client.post('/api/rename_resource_folder', json={'new_name': 'x'})
    assert missing_card.status_code == 400

    traversal = client.post(
        '/api/rename_resource_folder',
        json={'card_id': '../escape.png', 'new_name': 'x'},
    )
    assert traversal.status_code == 400
    assert traversal.get_json()['success'] is False

    assert len(calls) == 1


def test_rename_resource_folder_endpoint_propagates_service_failure(monkeypatch):
    monkeypatch.setattr(
        system_api,
        'rename_card_resource_folder',
        lambda card_id, new_name: {'success': False, 'msg': '目标目录已存在: x'},
    )

    response = _make_test_app().test_client().post(
        '/api/rename_resource_folder',
        json={'card_id': 'cards/hero.png', 'new_name': 'x'},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '目标目录已存在: x'


def test_resource_worldinfo_note_prefix_rename_only_touches_resource_source():
    old_path = '/res/hero-assets/lorebooks/book.json'
    new_path = '/res/hero-renamed/lorebooks/book.json'
    ui_data = {
        '_worldinfo_notes_v1': {
            f'resource::{old_path}': {'summary': 'resource', 'updated_at': 1},
            f'global::{old_path}': {'summary': 'global', 'updated_at': 1},
            'embedded::hero.png': {'summary': 'embedded', 'updated_at': 1},
        }
    }

    assert rename_resource_worldinfo_note_path_prefix(ui_data, old_path, new_path) is True

    notes = ui_data['_worldinfo_notes_v1']
    assert f'resource::{new_path}' in notes
    assert f'resource::{old_path}' not in notes
    # global 与 embedded 不受影响。
    assert f'global::{old_path}' in notes
    assert 'embedded::hero.png' in notes


def test_resource_item_category_prefix_rename_covers_worldinfo_and_presets():
    old_root = '/res/hero-assets'
    new_root = '/res/hero-renamed'
    ui_data = {
        '_resource_item_categories_v1': {
            'worldinfo': {
                f'{old_root}/lorebooks/book.json': {'category': 'arc', 'updated_at': 1},
                '/res/other/lorebooks/book.json': {'category': 'keep', 'updated_at': 1},
            },
            'presets': {
                f'{old_root}/presets/preset.json': {'category': 'style', 'updated_at': 1},
            },
            'updated_at': 1,
        }
    }

    assert rename_resource_item_category_path_prefix(ui_data, old_root, new_root) is True

    categories = ui_data['_resource_item_categories_v1']
    assert list(categories['worldinfo']) == [
        f'{new_root}/lorebooks/book.json',
        '/res/other/lorebooks/book.json',
    ]
    assert list(categories['presets']) == [f'{new_root}/presets/preset.json']
    assert categories['worldinfo'][f'{new_root}/lorebooks/book.json']['category'] == 'arc'


def test_resource_item_category_prefix_rename_reports_no_change_for_unrelated_paths():
    ui_data = {
        '_resource_item_categories_v1': {
            'worldinfo': {'/res/other/lorebooks/book.json': {'category': 'arc', 'updated_at': 1}},
            'presets': {},
            'updated_at': 1,
        }
    }

    assert rename_resource_item_category_path_prefix(ui_data, '/res/hero-assets', '/res/hero-renamed') is False
