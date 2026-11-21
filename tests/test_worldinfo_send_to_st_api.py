import json
import sys
import threading
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import world_info as world_info_api
from core.config import normalize_config
from core.data import ui_store as ui_store_module
from core.services import st_auth


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, text='', content=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content if content is not None else (b'{}' if json_data is not None else text.encode('utf-8'))

    def json(self):
        if self._json_data is None:
            raise ValueError('No JSON payload')
        return self._json_data


class FakeHTTPClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, path, **kwargs):
        serialized_kwargs = dict(kwargs)
        files = serialized_kwargs.get('files') or {}
        if files:
            serialized_files = {}
            for field_name, file_tuple in files.items():
                filename, handle, content_type = file_tuple
                body = handle.read()
                handle.seek(0)
                serialized_files[field_name] = {
                    'filename': filename,
                    'content_type': content_type,
                    'body_bytes': body,
                    'body_text': body.decode('utf-8'),
                }
            serialized_kwargs['files'] = serialized_files
        self.calls.append((path, serialized_kwargs))
        if self.error:
            raise self.error
        return self.response


class _FakeCache:
    def __init__(self, cards=None):
        self.cards = list(cards or [])
        self.visible_folders = []
        self.category_counts = {}
        self.global_tags = set()
        self.lock = threading.Lock()
        self.initialized = True

    def reload_from_db(self):
        raise AssertionError('reload_from_db should not run in send-to-st tests')


class _EmptyCursor:
    def fetchall(self):
        return []


class _EmptyConn:
    def execute(self, _query, _params=None):
        return _EmptyCursor()


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(world_info_api.bp)
    return app


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _configure_paths(monkeypatch, tmp_path, *, ui_payload=None):
    lorebooks_dir = tmp_path / 'lorebooks'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps(ui_payload or {}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(world_info_api.ctx, 'cache', _FakeCache([]))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(world_info_api, 'get_db', lambda: _EmptyConn())
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: normalize_config({
            'world_info_dir': str(lorebooks_dir),
            'resources_dir': str(resources_dir),
            'st_auth_type': 'basic',
        }),
    )
    world_info_api.ctx.wi_list_cache.clear()
    return lorebooks_dir, resources_dir, ui_path


def _ui_worldinfo_key(source_type: str, file_path: Path, *, lorebooks_dir: Path, resources_dir: Path) -> str:
    if source_type == 'global':
        rel_path = file_path.relative_to(lorebooks_dir)
    elif source_type == 'resource':
        rel_path = file_path.relative_to(resources_dir)
    else:
        raise AssertionError(f'unsupported world info source type: {source_type}')
    return f"{source_type}::{str(rel_path).replace('\\', '/')}"


def _read_ui_data(ui_path: Path):
    return __import__('core.data.local_state_repository', fromlist=['Repository']).Repository().export_snapshot()


def _assert_ui_data_unchanged(ui_path: Path, before_ui):
    assert _read_ui_data(ui_path) == before_ui


def test_worldinfo_send_to_st_global_success_persists_timestamp_and_surfaces_in_list_and_detail(monkeypatch, tmp_path):
    lorebooks_dir, resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = lorebooks_dir / 'dragon.json'
    sent_at = 1712345678.25
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'imported': True}))

    _write_json(global_file, {
        'name': 'Dragon Lore',
        'entries': {
            '0': {
                'key': ['dragon'],
                'content': 'Ancient fire lore',
            }
        },
    })

    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(world_info_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['st_response'] == {'imported': True}
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/worldinfo/import'
    assert st_kwargs['timeout'] == 10
    assert 'json' not in st_kwargs
    assert st_kwargs['files'] == {
        'avatar': {
            'filename': 'dragon.json',
            'content_type': 'application/json',
            'body_bytes': global_file.read_bytes(),
            'body_text': global_file.read_text(encoding='utf-8'),
        },
    }

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_ui_worldinfo_key('global', global_file, lorebooks_dir=lorebooks_dir, resources_dir=resources_dir)]['last_sent_to_st'] == sent_at

    list_res = client.get('/api/world_info/list?type=all')
    assert list_res.status_code == 200
    list_payload = list_res.get_json()
    global_item = next(item for item in list_payload['items'] if item['type'] == 'global')
    assert global_item['last_sent_to_st'] == sent_at

    detail_res = client.post('/api/world_info/detail', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()
    assert detail_payload['success'] is True
    assert detail_payload['last_sent_to_st'] == sent_at


def test_worldinfo_send_to_st_resource_success_persists_resource_key(monkeypatch, tmp_path):
    ui_payload = {
        'cards/lucy.png': {'resource_folder': 'lucy'},
    }
    lorebooks_dir, resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path, ui_payload=ui_payload)
    resource_file = resources_dir / 'lucy' / 'lorebooks' / 'companion.json'
    sent_at = 1712349999.5
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'name': 'Companion Lore'}))

    _write_json(resource_file, {
        'name': 'Companion Lore',
        'entries': {
            '0': {
                'key': ['companion'],
                'content': 'Resource world info',
            }
        },
    })

    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(world_info_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'resource',
        'file_path': str(resource_file),
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['st_response'] == {'name': 'Companion Lore'}
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/worldinfo/import'
    assert st_kwargs['timeout'] == 10
    assert 'json' not in st_kwargs
    assert st_kwargs['files'] == {
        'avatar': {
            'filename': 'companion.json',
            'content_type': 'application/json',
            'body_bytes': resource_file.read_bytes(),
            'body_text': resource_file.read_text(encoding='utf-8'),
        },
    }

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_ui_worldinfo_key('resource', resource_file, lorebooks_dir=lorebooks_dir, resources_dir=resources_dir)]['last_sent_to_st'] == sent_at


def test_worldinfo_send_to_st_accepts_top_level_list_and_normalizes_payload(monkeypatch, tmp_path):
    lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = lorebooks_dir / 'legacy-list.json'
    sent_at = 1712350001.0
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'imported': True}))

    _write_json(global_file, [
        {
            'keys': ['dragon'],
            'content': 'Ancient fire lore',
            'enabled': True,
        }
    ])

    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(world_info_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    _st_path, st_kwargs = fake_http_client.calls[0]
    serialized = json.loads(st_kwargs['files']['avatar']['body_text'])
    assert isinstance(serialized, dict)
    assert serialized['name'] == 'World Info'
    assert serialized['entries']['0']['content'] == 'Ancient fire lore'

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_ui_worldinfo_key('global', global_file, lorebooks_dir=lorebooks_dir, resources_dir=_resources_dir)]['last_sent_to_st'] == sent_at


def test_worldinfo_send_to_st_rejects_embedded_source(monkeypatch, tmp_path):
    _lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    before_ui = _read_ui_data(ui_path)
    client = _make_test_app().test_client()

    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'embedded',
        'file_path': 'cards/lucy.png',
    })

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert 'embedded' in payload['msg'].lower()
    assert 'send' in payload['msg'].lower() or '不支持' in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_worldinfo_send_to_st_rejects_invalid_path(monkeypatch, tmp_path):
    lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    invalid_file = tmp_path / 'outside.json'
    _write_json(invalid_file, {'name': 'Outside Lore', 'entries': {}})
    assert invalid_file.parent != lorebooks_dir
    before_ui = _read_ui_data(ui_path)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(invalid_file),
    })

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert '非法路径' in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_worldinfo_send_to_st_rejects_invalid_worldinfo_payload(monkeypatch, tmp_path):
    lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = lorebooks_dir / 'broken.json'
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'unused': True}))

    _write_json(global_file, {'name': 'Broken Lore'})
    before_ui = _read_ui_data(ui_path)

    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert '世界书' in payload['msg']
    assert fake_http_client.calls == []
    _assert_ui_data_unchanged(ui_path, before_ui)


@pytest.mark.parametrize(
    ('error', 'expected_phrases'),
    [
        (st_auth.STAuthError('basic_auth', 'bad auth', status_code=401), ['Basic/Auth', '认证失败', '401']),
        (st_auth.STAuthError('web_login', 'bad web login', status_code=401), ['Web', '登录失败', '401']),
    ],
)
def test_worldinfo_send_to_st_formats_auth_failures(monkeypatch, tmp_path, error, expected_phrases):
    lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = lorebooks_dir / 'dragon.json'

    _write_json(global_file, {
        'name': 'Dragon Lore',
        'entries': {
            '0': {'key': ['dragon'], 'content': 'Ancient fire lore'},
        },
    })
    before_ui = _read_ui_data(ui_path)

    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: FakeHTTPClient(error=error), raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    for phrase in expected_phrases:
        assert phrase in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_worldinfo_send_to_st_formats_http_400_like_card_send_flow(monkeypatch, tmp_path):
    lorebooks_dir, _resources_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = lorebooks_dir / 'dragon.json'

    _write_json(global_file, {
        'name': 'Dragon Lore',
        'entries': {
            '0': {'key': ['dragon'], 'content': 'Ancient fire lore'},
        },
    })
    before_ui = _read_ui_data(ui_path)

    fake_http_client = FakeHTTPClient(
        response=DummyResponse(400, text='bad request from ST', content=b'bad request from ST')
    )
    monkeypatch.setattr(world_info_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/world_info/send_to_st', json={
        'source_type': 'global',
        'file_path': str(global_file),
    })

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '400' in payload['msg']
    assert 'bad request from ST' in payload['msg']
    assert 'ST 请求错误' in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_enrich_indexed_worldinfo_item_uses_passed_cfg_for_last_sent_lookup(monkeypatch, tmp_path):
    lorebooks_dir = tmp_path / 'lorebooks'
    lorebooks_dir.mkdir(parents=True, exist_ok=True)
    global_file = lorebooks_dir / 'dragon.json'
    _write_json(global_file, {'name': 'Dragon Lore', 'entries': {'0': {'key': ['dragon'], 'content': 'Ancient fire lore'}}})

    cfg = normalize_config({'world_info_dir': str(lorebooks_dir), 'resources_dir': str(tmp_path / 'resources')})
    ui_data = {
        'global::dragon.json': {'last_sent_to_st': 123.5},
    }

    monkeypatch.setattr(world_info_api, 'load_config', lambda: (_ for _ in ()).throw(AssertionError('load_config should not be called')))

    enriched = world_info_api._enrich_indexed_worldinfo_item(
        {
            'id': 'world::global::dragon.json',
            'type': 'global',
            'filename': 'dragon.json',
            'name': 'Dragon Lore',
            'path': str(global_file),
            'category_mode': 'physical',
        },
        {},
        ui_data,
        cfg,
    )

    assert enriched['last_sent_to_st'] == 123.5
