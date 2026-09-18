import json
import sys
from io import BytesIO
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import presets as presets_api
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
        self.calls.append((path, serialized_kwargs))
        if self.error:
            raise self.error
        return self.response


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(presets_api.bp)
    return app


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _make_card(card_id, category, *, char_name='Lucy'):
    return {
        'id': card_id,
        'category': category,
        'char_name': char_name,
        'filename': card_id.split('/')[-1],
    }


def _configure_paths(monkeypatch, tmp_path, *, ui_payload=None, cards=None, include_openai_dir=False):
    presets_dir = tmp_path / 'presets'
    resources_dir = tmp_path / 'resources'
    openai_dir = tmp_path / 'st-openai-presets'
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps(ui_payload or {}, ensure_ascii=False), encoding='utf-8')

    config = {
        'presets_dir': str(presets_dir),
        'resources_dir': str(resources_dir),
        'st_auth_type': 'basic',
    }
    if include_openai_dir:
        config['st_openai_preset_dir'] = str(openai_dir)

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(presets_api, 'load_config', lambda: config)
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(
        presets_api,
        '_get_cards_by_resource_folder',
        lambda: {
            str((ui_payload or {}).get(card.get('id'), {}).get('resource_folder') or ''): card
            for card in (cards or [])
            if (ui_payload or {}).get(card.get('id'), {}).get('resource_folder')
        },
        raising=False,
    )

    return presets_dir, resources_dir, openai_dir, ui_path


def _read_ui_data(ui_path: Path):
    return json.loads(ui_path.read_text(encoding='utf-8'))


def _assert_ui_data_unchanged(ui_path: Path, before_ui):
    assert _read_ui_data(ui_path) == before_ui


def _global_ui_key(rel_path: str) -> str:
    return f'preset::global::{rel_path}'


def _resource_ui_key(file_path: Path) -> str:
    return f"preset::resource::{str(file_path).replace('\\', '/')}"


def test_preset_send_to_st_global_openai_success_persists_timestamp_and_surfaces_in_list_and_detail(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / '写作' / 'dragon.json'
    sent_at = 1712345678.25
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))
    preset_id = 'global::写作/dragon.json'

    _write_json(
        preset_file,
        {
            'name': 'Dragon',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': preset_id})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['st_response'] == {'ok': True}
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/presets/save'
    assert 'json' in st_kwargs
    assert 'files' not in st_kwargs
    assert st_kwargs['timeout'] == 10
    assert st_kwargs['json'] == {
        'apiId': 'openai',
        'name': 'Dragon',
        'preset': json.loads(preset_file.read_text(encoding='utf-8')),
    }

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_global_ui_key('写作/dragon.json')]['last_sent_to_st'] == sent_at

    list_res = client.get('/api/presets/list?filter_type=global')
    assert list_res.status_code == 200
    list_payload = list_res.get_json()
    item = next(entry for entry in list_payload['items'] if entry['id'] == preset_id)
    assert item['last_sent_to_st'] == sent_at
    assert item['preset_kind'] == 'openai'
    assert item['preset_kind_label'] == 'ST 聊天补全预设'

    detail_res = client.get(f'/api/presets/detail/{preset_id}')
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()
    assert detail_payload['success'] is True
    assert detail_payload['preset']['last_sent_to_st'] == sent_at


def test_preset_send_to_st_versioned_family_id_uses_default_version_and_surfaces_family_timestamp(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    default_file = presets_dir / '写作' / 'companion-v1.json'
    other_file = presets_dir / '写作' / 'companion-v2.json'
    sent_at = 1712345688.5
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))
    family_id = 'family-alpha'
    family_entry_id = 'global::global::family-alpha'

    _write_json(
        default_file,
        {
            'name': 'Companion',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'default'}],
            'x_st_manager': {
                'preset_family_id': family_id,
                'preset_family_name': 'Companion Family',
                'preset_version_label': 'V1',
                'preset_version_order': 10,
                'preset_is_default_version': True,
            },
        },
    )
    _write_json(
        other_file,
        {
            'name': 'Companion',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'other'}],
            'x_st_manager': {
                'preset_family_id': family_id,
                'preset_family_name': 'Companion Family',
                'preset_version_label': 'V2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': family_entry_id})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/presets/save'
    assert st_kwargs['json']['preset'] == json.loads(default_file.read_text(encoding='utf-8'))

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_global_ui_key('写作/companion-v1.json')]['last_sent_to_st'] == sent_at

    list_res = client.get('/api/presets/list?filter_type=global')
    assert list_res.status_code == 200
    family_item = next(entry for entry in list_res.get_json()['items'] if entry['id'] == family_entry_id)
    assert family_item['default_version_id'] == 'global::写作/companion-v1.json'
    assert family_item['last_sent_to_st'] == sent_at
    assert family_item['preset_kind'] == 'openai'
    assert family_item['preset_kind_label'] == 'ST 聊天补全预设'

    detail_res = client.get('/api/presets/detail/global::写作/companion-v1.json')
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()['preset']
    assert detail_payload['last_sent_to_st'] == sent_at


def test_preset_version_merge_global_openai_singles_promotes_target_and_rewrites_family_metadata(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    target_file = presets_dir / 'merge-target.json'
    source_file = presets_dir / 'merge-source.json'

    _write_json(
        target_file,
        {
            'name': 'Merge Target',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'target'}],
        },
    )
    _write_json(
        source_file,
        {
            'name': 'Merge Source',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'source'}],
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/version/merge',
        json={
            'target_preset_id': 'global::merge-target.json',
            'source_preset_ids': ['global::merge-source.json'],
            'family_name': 'Merged OpenAI Family',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset_id'] == 'global::merge-target.json'
    assert payload['preset']['family_info']['family_name'] == 'Merged OpenAI Family'
    assert payload['preset']['family_info']['default_version_id'] == 'global::merge-target.json'
    assert payload['preset']['current_version']['version_label'] == 'merge-target'
    assert payload['preset']['current_version']['is_default_version'] is True
    assert [version['id'] for version in payload['preset']['available_versions']] == [
        'global::merge-target.json',
        'global::merge-source.json',
    ]

    target_payload = json.loads(target_file.read_text(encoding='utf-8'))
    source_payload = json.loads(source_file.read_text(encoding='utf-8'))
    target_meta = target_payload['x_st_manager']
    source_meta = source_payload['x_st_manager']
    assert target_meta['preset_family_id']
    assert source_meta['preset_family_id'] == target_meta['preset_family_id']
    assert target_meta['preset_family_name'] == 'Merged OpenAI Family'
    assert source_meta['preset_family_name'] == 'Merged OpenAI Family'
    assert target_meta['preset_version_label'] == 'merge-target'
    assert source_meta['preset_version_label'] == 'merge-source'
    assert target_meta['preset_is_default_version'] is True
    assert source_meta['preset_is_default_version'] is False


def test_preset_version_merge_rejects_cross_scope_entries(monkeypatch, tmp_path):
    presets_dir, resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    global_file = presets_dir / 'global-openai.json'
    resource_file = resources_dir / 'hero' / 'presets' / 'resource-openai.json'

    _write_json(
        global_file,
        {
            'name': 'Global OpenAI',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'global'}],
        },
    )
    _write_json(
        resource_file,
        {
            'name': 'Resource OpenAI',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'resource'}],
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/version/merge',
        json={
            'target_preset_id': 'global::global-openai.json',
            'source_preset_ids': ['resource::hero::resource-openai'],
            'family_name': 'Invalid Mixed Family',
        },
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert '同一作用域' in payload['msg']


def test_preset_version_import_openai_file_into_existing_family_returns_updated_family_payload(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    default_file = presets_dir / 'companion-v1.json'

    _write_json(
        default_file,
        {
            'name': 'Companion V1',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'default'}],
            'x_st_manager': {
                'preset_family_id': 'family-alpha',
                'preset_family_name': 'Companion Family',
                'preset_version_label': 'v1',
                'preset_version_order': 10,
                'preset_is_default_version': True,
            },
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/version/import',
        data={
            'preset_id': 'global::companion-v1.json',
            'file': (
                BytesIO(
                    json.dumps(
                        {
                            'name': 'Imported Companion',
                            'openai_model': 'gpt-4.1',
                            'prompts': [{'identifier': 'main', 'content': 'imported'}],
                        },
                        ensure_ascii=False,
                    ).encode('utf-8')
                ),
                'imported-companion.json',
            ),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset_id'] == 'global::imported-companion.json'
    assert payload['preset']['family_info']['family_id'] == 'family-alpha'
    assert payload['preset']['family_info']['family_name'] == 'Companion Family'
    assert payload['preset']['family_info']['default_version_id'] == 'global::companion-v1.json'
    assert payload['preset']['current_version']['version_label'] == 'imported-companion'
    assert payload['preset']['current_version']['is_default_version'] is False
    assert [version['id'] for version in payload['preset']['available_versions']] == [
        'global::companion-v1.json',
        'global::imported-companion.json',
    ]

    imported_file = presets_dir / 'imported-companion.json'
    assert imported_file.exists()
    imported_payload = json.loads(imported_file.read_text(encoding='utf-8'))
    imported_meta = imported_payload['x_st_manager']
    assert imported_meta['preset_family_id'] == 'family-alpha'
    assert imported_meta['preset_family_name'] == 'Companion Family'
    assert imported_meta['preset_version_label'] == 'imported-companion'
    assert imported_meta['preset_is_default_version'] is False


def test_preset_version_import_rejects_generic_uploaded_json(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    default_file = presets_dir / 'companion-v1.json'

    _write_json(
        default_file,
        {
            'name': 'Companion V1',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'default'}],
            'x_st_manager': {
                'preset_family_id': 'family-alpha',
                'preset_family_name': 'Companion Family',
                'preset_version_label': 'v1',
                'preset_version_order': 10,
                'preset_is_default_version': True,
            },
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/version/import',
        data={
            'preset_id': 'global::companion-v1.json',
            'file': (
                BytesIO(
                    json.dumps(
                        {
                            'name': 'Imported Generic',
                            'temperature': 0.7,
                            'top_p': 0.9,
                            'prompts': [{'identifier': 'main', 'content': 'generic'}],
                        },
                        ensure_ascii=False,
                    ).encode('utf-8')
                ),
                'imported-generic.json',
            ),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '仅支持 OpenAI/对话补全预设导入版本'
    assert not (presets_dir / 'imported-generic.json').exists()


def test_preset_version_merge_deduplicates_repeated_ids(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    target_file = presets_dir / 'merge-target.json'
    source_file = presets_dir / 'merge-source.json'

    _write_json(
        target_file,
        {
            'name': 'Merge Target',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'target'}],
        },
    )
    _write_json(
        source_file,
        {
            'name': 'Merge Source',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'source'}],
        },
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/version/merge',
        json={
            'target_preset_id': 'global::merge-target.json',
            'source_preset_ids': [
                'global::merge-target.json',
                'global::merge-source.json',
                'global::merge-source.json',
            ],
            'family_name': 'Merged OpenAI Family',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert [version['id'] for version in payload['preset']['available_versions']] == [
        'global::merge-target.json',
        'global::merge-source.json',
    ]

    target_payload = json.loads(target_file.read_text(encoding='utf-8'))
    source_payload = json.loads(source_file.read_text(encoding='utf-8'))
    assert target_payload['x_st_manager']['preset_version_order'] == 10
    assert source_payload['x_st_manager']['preset_version_order'] == 20


def test_preset_send_to_st_rejects_global_openai_under_alt_root(monkeypatch, tmp_path):
    _presets_dir, _resources_dir, openai_dir, ui_path = _configure_paths(
        monkeypatch,
        tmp_path,
        include_openai_dir=True,
    )
    preset_file = openai_dir / 'OpenAI' / 'chat.json'
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))
    preset_id = 'global-alt::st_openai_preset_dir::OpenAI/chat.json'
    before_ui = _read_ui_data(ui_path)

    _write_json(
        preset_file,
        {
            'name': 'Alt Root Chat',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': preset_id})

    assert res.status_code == 400
    payload = res.get_json()
    assert payload == {'success': False, 'msg': '仅管理器预设库中的预设支持发送到 ST'}
    _assert_ui_data_unchanged(ui_path, before_ui)
    assert fake_http_client.calls == []


def test_preset_send_to_st_rejects_alt_root_family_id(monkeypatch, tmp_path):
    _presets_dir, _resources_dir, openai_dir, ui_path = _configure_paths(
        monkeypatch,
        tmp_path,
        include_openai_dir=True,
    )
    default_file = openai_dir / 'OpenAI' / 'chat-v1.json'
    other_file = openai_dir / 'OpenAI' / 'chat-v2.json'
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))
    family_id = 'alt-root-family'
    family_entry_id = 'global::st_openai_preset_dir::alt-root-family'
    before_ui = _read_ui_data(ui_path)

    version_meta = {
        'preset_family_id': family_id,
        'preset_family_name': 'Alt Root Family',
        'preset_version_label': 'v1',
        'preset_version_order': 10,
        'preset_is_default_version': True,
    }
    _write_json(
        default_file,
        {
            'name': 'Alt Root Chat',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'default'}],
            'x_st_manager': version_meta,
        },
    )
    _write_json(
        other_file,
        {
            'name': 'Alt Root Chat',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'other'}],
            'x_st_manager': {
                **version_meta,
                'preset_version_label': 'v2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': family_entry_id})

    assert res.status_code == 400
    assert res.get_json() == {'success': False, 'msg': '仅管理器预设库中的预设支持发送到 ST'}
    _assert_ui_data_unchanged(ui_path, before_ui)
    assert fake_http_client.calls == []


def test_global_alt_root_preset_does_not_reuse_manager_global_last_sent_timestamp(monkeypatch, tmp_path):
    presets_dir, _resources_dir, openai_dir, _ui_path = _configure_paths(
        monkeypatch,
        tmp_path,
        include_openai_dir=True,
        ui_payload={
            _global_ui_key('OpenAI/chat.json'): {'last_sent_to_st': 1712345678.25},
        },
    )
    manager_preset = presets_dir / 'OpenAI' / 'chat.json'
    alt_root_preset = openai_dir / 'OpenAI' / 'chat.json'

    _write_json(
        manager_preset,
        {
            'name': 'Manager Chat',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'manager'}],
        },
    )
    _write_json(
        alt_root_preset,
        {
            'name': 'Alt Root Chat',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'alt'}],
        },
    )

    client = _make_test_app().test_client()

    list_res = client.get('/api/presets/list?filter_type=global')
    assert list_res.status_code == 200
    list_payload = list_res.get_json()

    manager_item = next(entry for entry in list_payload['items'] if entry['id'] == 'global::OpenAI/chat.json')
    alt_root_item = next(
        entry for entry in list_payload['items'] if entry['id'] == 'global-alt::st_openai_preset_dir::OpenAI/chat.json'
    )
    assert manager_item['last_sent_to_st'] == 1712345678.25
    assert alt_root_item['last_sent_to_st'] == 0.0

    detail_res = client.get('/api/presets/detail/global-alt::st_openai_preset_dir::OpenAI/chat.json')
    assert detail_res.status_code == 200
    detail_payload = detail_res.get_json()
    assert detail_payload['success'] is True
    assert detail_payload['preset']['last_sent_to_st'] == 0.0


def test_preset_send_to_st_global_openai_without_name_uses_file_stem_for_st_payload_name(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'fallback-name.json'
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))

    outgoing_body = {
        'openai_model': 'gpt-4.1',
        'openai_max_context': 8192,
        'openai_max_tokens': 1200,
        'prompts': [{'identifier': 'main', 'content': 'hello'}],
    }
    _write_json(preset_file, outgoing_body)

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::fallback-name.json'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    assert len(fake_http_client.calls) == 1
    _st_path, st_kwargs = fake_http_client.calls[0]
    assert st_kwargs['json']['name'] == 'fallback-name'
    assert st_kwargs['json']['preset'] == outgoing_body


def test_preset_send_to_st_resource_openai_success_uses_st_save_endpoint(monkeypatch, tmp_path):
    ui_payload = {
        'cards/lucy.png': {'resource_folder': 'lucy'},
    }
    _presets_dir, resources_dir, _openai_dir, ui_path = _configure_paths(
        monkeypatch,
        tmp_path,
        ui_payload=ui_payload,
        cards=[_make_card('cards/lucy.png', '角色分类')],
    )
    preset_file = resources_dir / 'lucy' / 'presets' / 'companion.json'
    sent_at = 1712349999.5
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'name': 'Companion'}))
    preset_id = 'resource::lucy::companion'

    _write_json(
        preset_file,
        {
            'name': 'Companion',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': preset_id})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['st_response'] == {'name': 'Companion'}
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/presets/save'
    assert 'json' in st_kwargs
    assert 'files' not in st_kwargs
    assert st_kwargs['timeout'] == 10
    assert st_kwargs['json'] == {
        'apiId': 'openai',
        'name': 'Companion',
        'preset': json.loads(preset_file.read_text(encoding='utf-8')),
    }

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_resource_ui_key(preset_file)]['last_sent_to_st'] == sent_at


def test_preset_send_to_st_resource_family_id_uses_default_version(monkeypatch, tmp_path):
    ui_payload = {
        'cards/lucy.png': {'resource_folder': 'lucy'},
    }
    _presets_dir, resources_dir, _openai_dir, ui_path = _configure_paths(
        monkeypatch,
        tmp_path,
        ui_payload=ui_payload,
        cards=[_make_card('cards/lucy.png', '角色分类')],
    )
    default_file = resources_dir / 'lucy' / 'presets' / 'companion-v1.json'
    other_file = resources_dir / 'lucy' / 'presets' / 'companion-v2.json'
    sent_at = 1712350008.5
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))
    family_id = 'resource-family'
    family_entry_id = 'resource::resource::lucy::resource-family'

    version_meta = {
        'preset_family_id': family_id,
        'preset_family_name': 'Resource Family',
        'preset_version_label': 'v1',
        'preset_version_order': 10,
        'preset_is_default_version': True,
    }
    _write_json(
        default_file,
        {
            'name': 'Resource Companion',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'default'}],
            'x_st_manager': version_meta,
        },
    )
    _write_json(
        other_file,
        {
            'name': 'Resource Companion',
            'openai_model': 'gpt-4.1',
            'prompts': [{'identifier': 'main', 'content': 'other'}],
            'x_st_manager': {
                **version_meta,
                'preset_version_label': 'v2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': family_entry_id})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['last_sent_to_st'] == sent_at

    assert len(fake_http_client.calls) == 1
    st_path, st_kwargs = fake_http_client.calls[0]
    assert st_path == '/api/presets/save'
    assert st_kwargs['json']['preset'] == json.loads(default_file.read_text(encoding='utf-8'))

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_resource_ui_key(default_file)]['last_sent_to_st'] == sent_at


def test_preset_send_to_st_global_openai_success_with_non_json_body_still_succeeds_locally(
    monkeypatch, tmp_path
):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'chat.json'
    sent_at = 1712351111.0
    fake_http_client = FakeHTTPClient(
        response=DummyResponse(200, json_data=None, text='saved', content=b'saved')
    )

    _write_json(
        preset_file,
        {
            'name': 'Chat Preset',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api.time, 'time', lambda: sent_at)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::chat.json'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['st_response'] == 'saved'
    assert payload['last_sent_to_st'] == sent_at

    saved_ui = _read_ui_data(ui_path)
    assert saved_ui[_global_ui_key('chat.json')]['last_sent_to_st'] == sent_at


def test_preset_send_to_st_save_ui_failure_after_st_success_returns_500(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'chat.json'
    fake_http_client = FakeHTTPClient(response=DummyResponse(200, json_data={'ok': True}))

    _write_json(
        preset_file,
        {
            'name': 'Chat Preset',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(presets_api, 'save_ui_data', lambda data, **_kwargs: False)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::chat.json'})

    assert res.status_code == 500
    assert res.get_json() == {'success': False, 'msg': '保存发送时间失败'}
    assert len(fake_http_client.calls) == 1


def test_preset_send_to_st_outer_exception_returns_500_for_manager_global_openai(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, _ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'chat.json'

    _write_json(
        preset_file,
        {
            'name': 'Chat Preset',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'load_preset_json', lambda path: (_ for _ in ()).throw(RuntimeError('boom')))

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::chat.json'})

    assert res.status_code == 500
    assert res.get_json() == {'success': False, 'msg': 'boom'}


def test_preset_send_to_st_rejects_generic_preset(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'generic.json'
    before_ui = _read_ui_data(ui_path)

    _write_json(
        preset_file,
        {
            'name': 'Generic Preset',
            'temp': 0.7,
            'top_p': 0.9,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::generic.json'})

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == '仅 OpenAI/对话补全预设可发送到 ST'
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_preset_send_to_st_rejects_invalid_path(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::../outside.json'})

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == 'Invalid preset ID'


def test_preset_send_to_st_rejects_missing_file(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/send_to_st', json={'id': 'global::missing.json'})

    assert res.status_code == 404
    payload = res.get_json(silent=True)
    if payload is None:
        pytest.fail(
            'Expected /api/presets/send_to_st missing-file response to be JSON; '
            'route is likely missing and Flask returned the default HTML 404 page instead.'
        )
    assert payload['success'] is False
    assert payload['msg'] == '预设文件不存在'


@pytest.mark.parametrize(
    ('error', 'expected_phrases'),
    [
        (st_auth.STAuthError('basic_auth', 'bad auth', status_code=401), ['Basic/Auth', '认证失败', '401']),
        (st_auth.STAuthError('web_login', 'bad web login', status_code=401), ['Web', '登录失败', '401']),
    ],
)
def test_preset_send_to_st_formats_auth_failures(monkeypatch, tmp_path, error, expected_phrases):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'chat.json'
    before_ui = _read_ui_data(ui_path)

    _write_json(
        preset_file,
        {
            'name': 'Chat Preset',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(
        presets_api,
        'build_st_http_client',
        lambda cfg, timeout=10: FakeHTTPClient(error=error),
        raising=False,
    )

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/send_to_st',
        json={'id': 'global::chat.json'},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    for phrase in expected_phrases:
        assert phrase in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)


def test_preset_send_to_st_formats_http_400_like_existing_send_flow(monkeypatch, tmp_path):
    presets_dir, _resources_dir, _openai_dir, ui_path = _configure_paths(monkeypatch, tmp_path)
    preset_file = presets_dir / 'chat.json'
    before_ui = _read_ui_data(ui_path)

    _write_json(
        preset_file,
        {
            'name': 'Chat Preset',
            'openai_model': 'gpt-4.1',
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    fake_http_client = FakeHTTPClient(
        response=DummyResponse(400, text='bad request from ST', content=b'bad request from ST')
    )
    monkeypatch.setattr(presets_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/send_to_st',
        json={'id': 'global::chat.json'},
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert '400' in payload['msg']
    assert 'bad request from ST' in payload['msg']
    assert 'ST 请求错误' in payload['msg']
    _assert_ui_data_unchanged(ui_path, before_ui)
