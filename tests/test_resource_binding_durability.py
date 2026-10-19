"""资源目录绑定的原子写入、失败传播与既有目录接管契约。

对应文档：
- docs/2026-10-19-card-resource-binding-and-save-failure-analysis.md

覆盖三件事：
1. 绑定写入失败时必须报错且不更新内存缓存（旧实现会「界面上有、重启后没了」）；
2. 绑定丢失但磁盘上还留着同名目录时优先接管，不再新建 ``名字_1`` 空目录；
3. ``update_card`` 传空 ``resource_folder`` 不再静默解绑，只有显式声明才允许清空。
"""

import json
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.api.v1 import resources as resources_api
from core.api.v1 import system as system_api
from core.data import ui_store as ui_store_module
from core.services import card_resource_binding_service as binding_service


class _FakeCache:
    def __init__(self):
        self.id_map = {}
        self.bundle_map = {}
        self.lock = threading.Lock()
        self.updates = []

    def update_card_data(self, card_id, payload):
        self.updates.append((card_id, dict(payload)))
        self.id_map.setdefault(card_id, {}).update(payload)
        return self.id_map[card_id]


def _make_app(*blueprints):
    app = Flask(__name__)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app


@pytest.fixture()
def resources_env(monkeypatch, tmp_path):
    resources_root = tmp_path / 'resources'
    resources_root.mkdir(parents=True, exist_ok=True)
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text('{}', encoding='utf-8')

    fake_cache = _FakeCache()
    monkeypatch.setattr(resources_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(resources_api, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(resources_api, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(
        resources_api,
        'load_config',
        lambda: {'resources_dir': str(resources_root), 'allowed_abs_resource_roots': []},
    )
    monkeypatch.setattr(resources_api, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(resources_api, 'extract_card_info', lambda _path: {'name': 'Hero'})
    monkeypatch.setattr(resources_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    # system.py 是另一份模块命名空间，需要同样替身
    monkeypatch.setattr(system_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {'resources_dir': str(resources_root)},
    )
    monkeypatch.setattr(system_api, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(system_api, 'extract_card_info', lambda _path: {'name': 'Hero'})
    monkeypatch.setattr(system_api.ctx, 'cache', fake_cache, raising=False)
    return {
        'resources_root': resources_root,
        'cards_root': cards_root,
        'ui_path': ui_path,
        'cache': fake_cache,
    }


def _card_file(cards_root, name='hero.png'):
    path = cards_root / name
    path.write_bytes(b'card')
    return path


def test_resource_binding_save_failure_is_reported_and_cache_untouched(
    monkeypatch, resources_env
):
    _card_file(resources_env['cards_root'])

    def _reject(_mutator, **_kwargs):
        return False

    monkeypatch.setattr(binding_service, 'update_ui_data', _reject)

    client = _make_app(system_api.bp).test_client()
    res = client.post('/api/create_resource_folder', json={'card_id': 'hero.png'})

    assert res.status_code == 500
    body = res.get_json()
    assert body['success'] is False
    assert body.get('binding_failed') is True
    # 缓存不能被写入，否则前端会显示一个磁盘上不存在的绑定。
    assert resources_env['cache'].updates == []
    # 绑定失败时刚建的空目录要清掉，磁盘上不能留下无主目录
    assert not (resources_env['resources_root'] / 'Hero').exists()
    assert list(resources_env['resources_root'].iterdir()) == []


def test_upload_reports_binding_failure_instead_of_pretending_success(
    monkeypatch, resources_env
):
    _card_file(resources_env['cards_root'])
    monkeypatch.setattr(
        resources_api,
        'bind_card_resource_folder',
        lambda *_args, **_kwargs: {'ok': False, 'resource_folder': '', 'changed': False, 'msg': '写盘失败'},
    )
    monkeypatch.setattr(
        resources_api,
        'find_recoverable_resource_folder',
        lambda *_args, **_kwargs: '',
    )

    client = _make_app(resources_api.bp).test_client()
    data = {'card_id': 'hero.png', 'file': (__import__('io').BytesIO(b'img'), 'skin.png')}
    res = client.post('/api/upload_card_resource', data=data, content_type='multipart/form-data')

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is False
    assert body['msg']
    assert resources_env['cache'].updates == []


def test_create_resource_folder_restores_binding_for_existing_orphan_folder(
    monkeypatch, resources_env
):
    _card_file(resources_env['cards_root'])
    orphan = resources_env['resources_root'] / 'Hero'
    orphan.mkdir()
    (orphan / 'skin.png').write_bytes(b'png')

    client = _make_app(system_api.bp).test_client()
    res = client.post('/api/create_resource_folder', json={'card_id': 'hero.png'})

    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['resource_folder'] == 'Hero'
    assert body.get('binding_restored') is True
    # 不能多建一个 Hero_1 空目录
    assert sorted(p.name for p in resources_env['resources_root'].iterdir()) == ['Hero']

    saved = json.loads(resources_env['ui_path'].read_text(encoding='utf-8'))
    assert saved['hero.png']['resource_folder'] == 'Hero'


def test_find_recoverable_resource_folder_skips_other_cards_bindings(monkeypatch, tmp_path):
    resources_root = tmp_path / 'resources'
    (resources_root / 'Hero').mkdir(parents=True)
    (resources_root / 'Hero_1').mkdir(parents=True)
    (resources_root / 'Other').mkdir(parents=True)

    ui_data = {
        'other.png': {'resource_folder': 'Hero_1'},
    }

    assert binding_service.find_recoverable_resource_folder(
        'Hero',
        card_ui_key='hero.png',
        resources_root=str(resources_root),
        loader=lambda: ui_data,
    ) == 'Hero'
    # Other 目录已被 other.png 绑定（这里 other.png 绑的是 Hero_1），
    # 因此 Hero 卡不能接管 Hero_1；Other 卡自己已有绑定，不需要接管。
    assert binding_service.find_recoverable_resource_folder(
        'Hero_1',
        card_ui_key='hero.png',
        resources_root=str(resources_root),
        loader=lambda: ui_data,
    ) == ''
    assert binding_service.find_recoverable_resource_folder(
        'Missing',
        card_ui_key='hero.png',
        resources_root=str(resources_root),
        loader=lambda: ui_data,
    ) == ''


def test_bind_card_resource_folder_is_atomic_and_idempotent(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))

    first = binding_service.bind_card_resource_folder('hero.png', 'hero-assets')
    assert first['ok'] is True
    assert first['changed'] is True

    second = binding_service.bind_card_resource_folder('hero.png', 'hero-assets')
    assert second['ok'] is True
    assert second['changed'] is False

    # allow_existing 不会覆盖已有绑定
    third = binding_service.bind_card_resource_folder(
        'hero.png', 'other-assets', allow_existing=True
    )
    assert third['ok'] is True
    assert third['resource_folder'] == 'hero-assets'

    saved = json.loads(ui_path.read_text(encoding='utf-8'))
    assert saved['hero.png']['resource_folder'] == 'hero-assets'


def _configure_update_card_env(monkeypatch, tmp_path, *, ui_state):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir(parents=True, exist_ok=True)
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps(ui_state, ensure_ascii=False), encoding='utf-8')
    card_rel = 'cards/lucy.png'
    card_path = cards_dir / card_rel
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'card')

    fake_cache = _FakeCache()
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {
        'data': {
            'name': 'Lucy',
            'description': 'kept',
            'tags': ['tag'],
            'extensions': {},
            'alternate_greetings': [],
            'character_book': {'name': 'Book', 'entries': {}},
        }
    })
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cards_api, 'update_card_cache', lambda *_args, **_kwargs: {'cache_updated': False})
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(cards_api, 'get_import_time', lambda _ui, _key, fallback: fallback)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda _ui, _key, fallback: (False, fallback))
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _path: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _name: True)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api, 'append_entry_history_records', lambda **_kwargs: None)
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_apply_card_index_increment_now', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', fake_cache, raising=False)
    return card_rel


def test_update_card_keeps_resource_folder_when_payload_sends_empty(monkeypatch, tmp_path):
    card_rel = _configure_update_card_env(
        monkeypatch,
        tmp_path,
        ui_state={
            'cards/lucy.png': {'summary': 'note', 'link': 'l', 'resource_folder': 'keep-folder'}
        },
    )

    client = _make_app(cards_api.bp).test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'char_name': 'Lucy',
        'description': 'kept',
        'ui_summary': 'note',
        'source_link': 'l',
        'resource_folder': '',
    })

    assert res.status_code == 200
    saved = json.loads((tmp_path / 'ui_data.json').read_text(encoding='utf-8'))
    assert saved['cards/lucy.png']['resource_folder'] == 'keep-folder'


def test_update_card_allows_explicit_resource_folder_clear(monkeypatch, tmp_path):
    card_rel = _configure_update_card_env(
        monkeypatch,
        tmp_path,
        ui_state={
            'cards/lucy.png': {'summary': 'note', 'link': 'l', 'resource_folder': 'keep-folder'}
        },
    )

    client = _make_app(cards_api.bp).test_client()
    res = client.post('/api/update_card', json={
        'id': card_rel,
        'char_name': 'Lucy',
        'description': 'kept',
        'ui_summary': 'note',
        'source_link': 'l',
        'resource_folder': '',
        'clear_ui_fields': ['resource_folder'],
    })

    assert res.status_code == 200
    saved = json.loads((tmp_path / 'ui_data.json').read_text(encoding='utf-8'))
    assert saved['cards/lucy.png']['resource_folder'] == ''


def test_swap_skin_cover_returns_revision_and_card_id(monkeypatch, tmp_path):
    """换封必须返回新修订号与新卡片 ID，否则下一次保存会被乐观锁拒绝。"""
    from core.services import card_service

    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    resources_root = tmp_path / 'resources'
    skin_dir = resources_root / 'hero-assets'
    skin_dir.mkdir(parents=True)
    card_path = cards_dir / 'hero.png'
    card_path.write_bytes(b'old')
    (skin_dir / 'skin.png').write_bytes(b'new')

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(card_service, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(card_service, 'THUMB_FOLDER', str(tmp_path / 'thumbs'))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': 'resources'})
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: {
        'hero.png': {'resource_folder': 'hero-assets'}
    })
    monkeypatch.setattr(card_service, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(card_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero'}})
    monkeypatch.setattr(card_service, 'clean_thumbnail_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(card_service, 'get_file_hash_and_size', lambda _path: ('hash', 3))

    class _FakeImage:
        def save(self, path, _fmt, **_kwargs):
            Path(path).write_bytes(b'new-png')

    class _FakeCache:
        def __init__(self):
            self.id_map = {'hero.png': {'id': 'hero.png', 'image_url': '/x'}}

        def update_card_data(self, card_id, payload):
            self.id_map[card_id].update(payload)
            return self.id_map[card_id]

    fake_cache = _FakeCache()
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(card_service.Image, 'open', lambda _path: _FakeImage())

    result = card_service.swap_skin_to_cover('hero.png', 'skin.png')

    assert result['success'] is True
    assert result['new_card_id'] == 'hero.png'
    assert result.get('source_revision')
    assert result['source_revision'] == card_service.build_file_source_revision(str(card_path))
    assert result['updated_card']['source_revision'] == result['source_revision']
