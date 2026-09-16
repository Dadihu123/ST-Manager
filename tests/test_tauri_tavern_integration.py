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
from core.services.tauri_tavern_client import TauriTavernClient


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _make_tauri_config(root: Path):
    return normalize_config({
        'st_target': 'tauritavern',
        'tt_data_dir': str(root),
        'tt_user_handle': 'default-user',
    })


def _make_app(*blueprints):
    app = Flask(__name__)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app


def test_tauri_client_writes_supported_resources_to_user_directories(tmp_path):
    root = tmp_path / 'tauri-data'
    user_dir = root / 'default-user'
    user_dir.mkdir(parents=True)
    character_path = tmp_path / 'card.png'
    character_path.write_bytes(b'png')
    world_path = tmp_path / 'lore.json'
    world_path.write_text('{}', encoding='utf-8')
    preset_path = tmp_path / 'preset.json'
    preset_path.write_text('{}', encoding='utf-8')

    client = TauriTavernClient(str(root), 'default-user')
    character_result = client.send_character(str(character_path))
    world_result = client.send_world_info(str(world_path), b'{"entries": {}}')
    preset_result = client.send_preset(
        str(preset_path),
        {'name': 'Writing', 'openai_model': 'gpt-4.1', 'prompts': []},
    )
    theme_result = client.send_theme({'name': 'Midnight', 'custom_css': 'body {}'})

    assert Path(character_result['path']) == user_dir / 'characters' / 'card.png'
    assert Path(world_result['path']) == user_dir / 'worlds' / 'lore.json'
    assert Path(preset_result['path']) == user_dir / 'OpenAI Settings' / 'Writing.json'
    assert Path(theme_result['path']) == user_dir / 'themes' / 'Midnight.json'
    assert (user_dir / 'characters' / 'card.png').read_bytes() == b'png'
    assert json.loads((user_dir / 'worlds' / 'lore.json').read_text(encoding='utf-8')) == {
        'entries': {},
    }
    assert json.loads((user_dir / 'OpenAI Settings' / 'Writing.json').read_text(encoding='utf-8'))[
        'name'
    ] == 'Writing'
    settings = json.loads((user_dir / 'settings.json').read_text(encoding='utf-8'))
    assert settings['power_user']['theme'] == 'Midnight'


def test_tauri_client_accepts_user_directory_path_and_rejects_unsafe_handle(tmp_path):
    user_dir = tmp_path / 'default-user'
    user_dir.mkdir(parents=True)

    client = TauriTavernClient(str(user_dir), 'default-user')
    assert client.data_root == str(tmp_path)
    assert client.validate()['valid'] is True

    with pytest.raises(ValueError):
        TauriTavernClient(str(tmp_path), '../outside')


def test_target_switch_preserves_both_tavern_config_sets(tmp_path):
    config_path = tmp_path / 'config.json'
    write_config_file(config_path, {
        'st_target': 'tauritavern',
        'st_url': 'http://127.0.0.1:8000',
        'st_data_dir': 'D:/SillyTavern',
        'st_user_handle': 'st-user',
        'tt_data_dir': 'D:/TauriTavern/data',
        'tt_user_handle': 'default-user',
    })

    saved = json.loads(config_path.read_text(encoding='utf-8'))
    assert saved['st_target'] == 'tauritavern'
    assert saved['st_url'] == 'http://127.0.0.1:8000'
    assert saved['st_data_dir'] == 'D:/SillyTavern'
    assert saved['st_user_handle'] == 'st-user'
    assert saved['tt_data_dir'] == 'D:/TauriTavern/data'
    assert saved['tt_user_handle'] == 'default-user'


def test_tauri_path_validation_endpoint_reports_user_directory(tmp_path):
    root = tmp_path / 'tauri-data'
    (root / 'default-user').mkdir(parents=True)

    response = _make_app(st_sync_api.bp).test_client().post(
        '/api/st/tt/validate_path',
        json={'path': str(root), 'tt_user_handle': 'default-user'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['valid'] is True
    assert payload['user_handle'] == 'default-user'


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
    assert (tmp_path / 'tauri-data' / 'default-user' / 'themes' / 'Demo.json').exists()
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
    assert (tauri_root / 'default-user' / 'characters' / 'card.png').exists()
    payload = response.get_json()
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
            'tt_data_dir': str(tauri_root),
            'world_info_dir': str(lorebooks_root),
            'resources_dir': str(tmp_path / 'resources'),
        }),
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
    saved = tauri_root / 'default-user' / 'worlds' / 'dragon.json'
    payload = json.loads(saved.read_text(encoding='utf-8'))
    assert payload['entries']['0']['content'] == 'fire'
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
            'tt_data_dir': str(tauri_root),
            'presets_dir': str(presets_root),
            'resources_dir': str(tmp_path / 'resources'),
        }),
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
    saved = tauri_root / 'default-user' / 'OpenAI Settings' / 'Writing.json'
    assert json.loads(saved.read_text(encoding='utf-8'))['openai_model'] == 'gpt-4.1'
    assert response.get_json()['last_sent_to_tt'] > 0
    saved_ui = json.loads(ui_path.read_text(encoding='utf-8'))
    assert all('last_sent_to_st' not in entry for entry in saved_ui.values())
    assert any(entry.get('last_sent_to_tt') for entry in saved_ui.values())
