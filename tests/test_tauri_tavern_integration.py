import json
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import presets as presets_api
from core.api.v1 import st_sync as st_sync_api
from core.api.v1 import system as system_api
from core.api.v1 import world_info as world_info_api
from core.api.v1 import beautify as beautify_api
from core.config import normalize_config, write_config_file
from core.data import ui_store as ui_store_module
from core.services import tauri_tavern_client as tauri_client_module
from core.services.tauri_tavern_client import TauriTavernClient


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _make_tauri_config(_root: Path):
    return normalize_config({
        'st_target': 'tauritavern',
        'tt_user_handle': 'default-user',
    })


def _make_app(*blueprints):
    app = Flask(__name__)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app


class _FakeTauriApiClient:
    """Route-level double for the native TT API client."""

    def __init__(self):
        self.character_source = None
        self.world_payload = None
        self.preset_payload = None
        self.theme_payload = None

    def send_character(self, source_path):
        self.character_source = source_path
        return {'path': 'api://characters/card.png', 'filename': 'card.png'}

    def send_world_info(self, source_path, payload_bytes):
        self.world_payload = (source_path, json.loads(payload_bytes.decode('utf-8')))
        return {'path': 'api://worlds/dragon.json', 'filename': 'dragon.json'}

    def send_preset(self, source_path, preset_data):
        self.preset_payload = (source_path, preset_data)
        return {'path': 'api://presets/Writing.json', 'filename': 'Writing.json'}

    def send_theme(self, theme_data):
        self.theme_payload = theme_data
        return {
            'path': 'api://themes/Demo.json',
            'settings_path': 'api://settings.json',
            'filename': 'Demo.json',
        }


def test_tauri_client_is_api_only_and_rejects_unsafe_handle():
    client = TauriTavernClient(
        api_url='http://127.0.0.1:19999',
        user_handle='writer-user',
    )
    assert client.api_url == 'http://127.0.0.1:19999'
    assert client.user_handle == 'writer-user'

    with pytest.raises(ValueError):
        TauriTavernClient(
            api_url='http://127.0.0.1:19999',
            user_handle='../outside',
        )


def test_tauri_client_from_config_uploads_character_to_integration_api(monkeypatch, tmp_path):
    source_path = tmp_path / 'card.png'
    source_path.write_bytes(b'png-data')

    class FakeResponse:
        status_code = 200
        text = ''

        @staticmethod
        def json():
            return {
                'success': True,
                'path': 'api://characters/card.png',
                'filename': 'card.png',
            }

    class FakeSession:
        def __init__(self):
            self.trust_env = None
            self.call = None

        def request(self, method, url, **kwargs):
            upload = kwargs['files']['file']
            self.call = {
                'method': method,
                'url': url,
                'data': kwargs['data'],
                'filename': upload[0],
                'content_type': upload[2],
                'content': upload[1].read(),
            }
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(tauri_client_module.requests, 'Session', lambda: fake_session)

    client = TauriTavernClient.from_config({
        'tt_api_url': 'http://127.0.0.1:19999',
        'tt_user_handle': 'writer-user',
    })
    result = client.send_character(str(source_path))

    assert result == {'path': 'api://characters/card.png', 'filename': 'card.png'}
    assert fake_session.trust_env is False
    assert fake_session.call == {
        'method': 'POST',
        'url': 'http://127.0.0.1:19999/api/st-manager/v1/characters/import',
        'data': {
            'user_handle': 'writer-user',
            'preserve_file_name': 'card.png',
        },
        'filename': 'card.png',
        'content_type': 'image/png',
        'content': b'png-data',
    }


def test_tauri_client_check_connection_sends_configured_user_handle(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ''

        @staticmethod
        def json():
            return {'success': True, 'service': 'tauritavern', 'api_version': 1}

    class FakeSession:
        def __init__(self):
            self.trust_env = None
            self.call = None

        def request(self, method, url, **kwargs):
            self.call = {'method': method, 'url': url, **kwargs}
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(tauri_client_module.requests, 'Session', lambda: fake_session)

    result = TauriTavernClient(
        api_url='http://127.0.0.1:19999',
        user_handle='writer-user',
    ).check_connection()

    assert result['success'] is True
    assert fake_session.trust_env is False
    assert fake_session.call['params'] == {'user_handle': 'writer-user'}


def test_tauri_client_sends_user_handle_for_json_resources(monkeypatch, tmp_path):
    source_path = tmp_path / 'writing.json'
    _write_json(source_path, {'name': 'Writing', 'prompts': []})

    class FakeResponse:
        status_code = 200
        text = ''

        @staticmethod
        def json():
            return {'success': True, 'path': 'api://resource', 'filename': 'resource.json'}

    class FakeSession:
        def __init__(self):
            self.trust_env = None
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append({'method': method, 'url': url, **kwargs})
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(tauri_client_module.requests, 'Session', lambda: fake_session)
    client = TauriTavernClient(
        api_url='http://127.0.0.1:19999',
        user_handle='writer-user',
    )

    client.send_world_info(str(source_path), b'{"entries": {}}')
    client.send_preset(str(source_path), {'name': 'Writing', 'prompts': []})
    client.send_theme({'name': 'Demo', 'colors': {}})

    assert [call['json']['user_handle'] for call in fake_session.calls] == [
        'writer-user',
        'writer-user',
        'writer-user',
    ]


def test_tauri_connection_endpoint_uses_default_api_url(monkeypatch):
    captured = {}

    class FakeClient:
        api_url = 'http://127.0.0.1:19999'

        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

        @staticmethod
        def check_connection():
            return {'success': True, 'service': 'tauritavern', 'api_version': 1}

    monkeypatch.setattr(st_sync_api, 'TauriTavernClient', FakeClient)
    monkeypatch.setattr(st_sync_api, 'load_config', lambda: {
        'tt_user_handle': 'default-user',
        'tt_api_url': 'http://127.0.0.1:19999',
    })

    response = _make_app(st_sync_api.bp).test_client().post(
        '/api/st/tt/check_connection',
        json={},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'message': 'TauriTavern 集成 API 已连接',
        'api_url': 'http://127.0.0.1:19999',
        'service': 'tauritavern',
        'api_version': 1,
    }
    assert captured == {
        'api_url': 'http://127.0.0.1:19999',
        'user_handle': 'default-user',
    }


def test_target_switch_preserves_st_config_and_tt_user_config(tmp_path):
    config_path = tmp_path / 'config.json'
    write_config_file(config_path, {
        'st_target': 'tauritavern',
        'st_url': 'http://127.0.0.1:8000',
        'st_data_dir': 'D:/SillyTavern',
        'st_user_handle': 'st-user',
        'tt_user_handle': 'default-user',
    })

    saved = json.loads(config_path.read_text(encoding='utf-8'))
    assert saved['st_target'] == 'tauritavern'
    assert saved['st_url'] == 'http://127.0.0.1:8000'
    assert saved['st_data_dir'] == 'D:/SillyTavern'
    assert saved['st_user_handle'] == 'st-user'
    assert saved['tt_user_handle'] == 'default-user'
    assert 'tt_data_dir' not in saved


def test_tauri_path_validation_endpoint_is_removed():
    response = _make_app(st_sync_api.bp).test_client().post(
        '/api/st/tt/validate_path',
        json={'path': 'D:/TauriTavern/data', 'tt_user_handle': 'default-user'},
    )

    assert response.status_code == 404


def test_beautify_send_route_writes_standard_theme_in_tauri_mode(monkeypatch, tmp_path):
    (tmp_path / 'tauri-data' / 'default-user').mkdir(parents=True)
    ui_path = tmp_path / 'ui.json'
    ui_path.write_text('{}', encoding='utf-8')

    class FakeBeautifyService:
        def build_sendable_theme_bundle(self, _package_id, _variant_id):
            return {'theme_data': {'name': 'Demo'}}

        def get_variant_send_state_key(self, package_id, variant_id):
            return f'beautify::{package_id}::{variant_id}'

    monkeypatch.setattr(
        beautify_api,
        'get_beautify_service',
        lambda: FakeBeautifyService(),
    )
    monkeypatch.setattr(
        beautify_api,
        'load_config',
        lambda: _make_tauri_config(tmp_path / 'tauri-data'),
    )
    fake_client = _FakeTauriApiClient()
    monkeypatch.setattr(
        beautify_api.TauriTavernClient,
        'from_config',
        lambda _config: fake_client,
    )
    # The send route persists the send timestamp; keep it off the real ui_data.json.
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(
        beautify_api,
        'build_st_http_client',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('HTTP must not be used')),
    )

    response = _make_app(beautify_api.bp).test_client().post(
        '/api/beautify/send-theme-to-st',
        json={'package_id': 'pkg', 'variant_id': 'variant'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['target'] == 'tauritavern'
    assert fake_client.theme_payload == {'name': 'Demo'}
    # TauriTavern sends stamp their own key so both histories stay distinguishable.
    assert payload['last_sent_to_tt'] > 0
    assert 'last_sent_to_st' not in payload
    saved_ui = json.loads(ui_path.read_text(encoding='utf-8'))
    assert saved_ui['beautify::pkg::variant']['last_sent_to_tt'] == payload['last_sent_to_tt']
    assert 'last_sent_to_st' not in saved_ui['beautify::pkg::variant']


def test_character_send_route_writes_to_tauri_without_http(monkeypatch, tmp_path):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    (cards_root / 'card.png').write_bytes(b'png')
    tauri_root = tmp_path / 'tauri-data'
    (tauri_root / 'default-user').mkdir(parents=True)
    ui_path = tmp_path / 'ui.json'
    ui_path.write_text('{}', encoding='utf-8')

    class FakeCache:
        id_map = {}
        bundle_map = {}

        def update_card_data(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(system_api, 'load_config', lambda: _make_tauri_config(tauri_root))
    fake_client = _FakeTauriApiClient()
    monkeypatch.setattr(
        system_api.TauriTavernClient,
        'from_config',
        lambda _config: fake_client,
    )
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(system_api.ctx, 'cache', FakeCache())
    monkeypatch.setattr(
        system_api,
        'build_st_http_client',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('HTTP must not be used')),
    )

    response = _make_app(system_api.bp).test_client().post(
        '/api/send_to_st',
        json={'card_id': 'card.png'},
    )

    assert response.status_code == 200
    assert response.get_json()['target'] == 'tauritavern'
    payload = response.get_json()
    assert payload['target_path'] == 'api://characters/card.png'
    assert fake_client.character_source == str(cards_root / 'card.png')
    assert payload['last_sent_to_tt'] > 0
    assert 'last_sent_to_st' not in payload
    saved_ui = json.loads(ui_path.read_text(encoding='utf-8'))
    assert saved_ui['card.png']['last_sent_to_tt'] == payload['last_sent_to_tt']
    assert 'last_sent_to_st' not in saved_ui['card.png']


def test_world_info_send_route_writes_normalized_payload_to_tauri(monkeypatch, tmp_path):
    lorebooks_root = tmp_path / 'lorebooks'
    lorebooks_root.mkdir()
    world_path = lorebooks_root / 'dragon.json'
    _write_json(world_path, [{'key': ['dragon'], 'content': 'fire'}])
    tauri_root = tmp_path / 'tauri-data'
    (tauri_root / 'default-user').mkdir(parents=True)
    ui_path = tmp_path / 'ui.json'
    ui_path.write_text('{}', encoding='utf-8')

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: normalize_config({
            'st_target': 'tauritavern',
            'world_info_dir': str(lorebooks_root),
            'resources_dir': str(tmp_path / 'resources'),
        }),
    )
    fake_client = _FakeTauriApiClient()
    monkeypatch.setattr(
        world_info_api.TauriTavernClient,
        'from_config',
        lambda _config: fake_client,
    )
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(
        world_info_api,
        'build_st_http_client',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('HTTP must not be used')),
    )

    response = _make_app(world_info_api.bp).test_client().post(
        '/api/world_info/send_to_st',
        json={'source_type': 'global', 'file_path': str(world_path)},
    )

    assert response.status_code == 200
    assert response.get_json()['target'] == 'tauritavern'
    assert fake_client.world_payload[1]['entries']['0']['content'] == 'fire'
    assert response.get_json()['last_sent_to_tt'] > 0
    saved_ui = json.loads(ui_path.read_text(encoding='utf-8'))
    assert all('last_sent_to_st' not in entry for entry in saved_ui.values())
    assert any(entry.get('last_sent_to_tt') for entry in saved_ui.values())


def test_openai_preset_send_route_writes_to_tauri_without_http(monkeypatch, tmp_path):
    presets_root = tmp_path / 'presets'
    preset_path = presets_root / 'writing.json'
    _write_json(preset_path, {
        'name': 'Writing',
        'openai_model': 'gpt-4.1',
        'openai_max_context': 8192,
        'prompts': [],
    })
    tauri_root = tmp_path / 'tauri-data'
    (tauri_root / 'default-user').mkdir(parents=True)
    ui_path = tmp_path / 'ui.json'
    ui_path.write_text('{}', encoding='utf-8')

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: normalize_config({
            'st_target': 'tauritavern',
            'presets_dir': str(presets_root),
            'resources_dir': str(tmp_path / 'resources'),
        }),
    )
    fake_client = _FakeTauriApiClient()
    monkeypatch.setattr(
        presets_api.TauriTavernClient,
        'from_config',
        lambda _config: fake_client,
    )
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(
        presets_api,
        'build_st_http_client',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('HTTP must not be used')),
    )

    response = _make_app(presets_api.bp).test_client().post(
        '/api/presets/send_to_st',
        json={'id': 'global::writing.json'},
    )

    assert response.status_code == 200
    assert response.get_json()['target'] == 'tauritavern'
    assert fake_client.preset_payload[1]['openai_model'] == 'gpt-4.1'
    assert response.get_json()['last_sent_to_tt'] > 0
    saved_ui = json.loads(ui_path.read_text(encoding='utf-8'))
    assert all('last_sent_to_st' not in entry for entry in saved_ui.values())
    assert any(entry.get('last_sent_to_tt') for entry in saved_ui.values())
