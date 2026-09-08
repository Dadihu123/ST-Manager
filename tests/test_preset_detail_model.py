import json
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import presets as presets_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(presets_api.bp)
    return app


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def test_preset_detail_returns_source_revision_but_not_display_only_metadata(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'textgen-main.json',
        {
            'name': 'Textgen Main',
            'temp': 0.95,
            'top_p': 0.9,
            'top_k': 40,
            'repetition_penalty': 1.1,
            'json_schema': '{"type":"object"}',
            'extensions': {'regex_scripts': []},
            'custom_flag': True,
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::textgen-main.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset']['preset_kind'] == 'generic'
    assert payload['preset']['source_revision']
    assert payload['preset']['sections'] == {}
    assert payload['preset']['editor_profile']['id'] == 'generic_json'
    assert 'capabilities' not in payload['preset']
    assert 'has_unknown_fields' not in payload['preset']
    assert 'unknown_fields' not in payload['preset']


def test_preset_detail_falls_back_to_generic_for_legacy_sysprompt_shape_when_folder_missing(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'prompt.json',
        {
            'name': 'Sys Prompt',
            'content': '你是助手',
            'post_history': True,
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::prompt.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset']['preset_kind'] == 'generic'
    assert payload['preset']['preset_kind_label'] == '通用 JSON'
    assert payload['preset']['reader_view']['family'] == 'generic'


def test_preset_detail_falls_back_to_generic_for_legacy_instruct_context_and_reasoning_shapes(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'instruct.json',
        {
            'name': 'Instruct',
            'input_sequence': 'User:',
            'output_sequence': 'Assistant:',
            'system_sequence': 'System:',
        },
    )
    _write_json(
        presets_dir / 'context.json',
        {
            'name': 'Context',
            'story_string': '{{char}}',
            'chat_start': '###',
        },
    )
    _write_json(
        presets_dir / 'reasoning.json',
        {
            'name': 'Reasoning',
            'prefix': '<think>',
            'suffix': '</think>',
            'separator': '\n',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    instruct = client.get('/api/presets/detail/global::instruct.json').get_json()['preset']
    context = client.get('/api/presets/detail/global::context.json').get_json()['preset']
    reasoning = client.get('/api/presets/detail/global::reasoning.json').get_json()['preset']

    assert instruct['preset_kind'] == 'generic'
    assert instruct['preset_kind_label'] == '通用 JSON'
    assert instruct['editor_profile']['id'] == 'generic_json'
    assert context['preset_kind'] == 'generic'
    assert context['editor_profile']['id'] == 'generic_json'
    assert reasoning['preset_kind'] == 'generic'
    assert reasoning['editor_profile']['id'] == 'generic_json'


def test_preset_detail_reader_view_uses_prompt_manager_family_for_prompt_presets(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'openai-chat.json',
        {
            'name': 'OpenAI Chat',
            'temperature': 0.8,
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'system_prompt': True,
                },
                {
                    'identifier': 'worldInfoAfter',
                    'name': 'World Info (after)',
                    'system_prompt': True,
                    'marker': True,
                },
                {
                    'identifier': 'summary',
                    'name': 'Summary',
                    'role': 'assistant',
                    'content': '总结要点',
                },
            ],
            'prompt_order': ['summary', 'main'],
            'extensions': {'memory': {'enabled': True}},
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::openai-chat.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    reader_view = preset['reader_view']
    prompt_items = [item for item in reader_view['items'] if item['type'] == 'prompt']

    assert reader_view['family'] == 'prompt_manager'
    assert reader_view['family_label'] == '提示词管理预设'
    assert [group['id'] for group in reader_view['groups']][0] == 'prompts'
    assert 'prompt_order' not in [group['id'] for group in reader_view['groups']]
    assert [item['payload']['identifier'] for item in prompt_items] == ['summary', 'main', 'worldInfoAfter']
    assert prompt_items[0]['editor']['kind'] == 'prompt-manager-item'
    assert prompt_items[0]['reorderable'] is False
    assert prompt_items[0]['prompt_meta']['identifier'] == 'summary'
    assert prompt_items[0]['prompt_meta']['is_enabled'] is True
    assert prompt_items[0]['prompt_meta']['content_editable'] is True
    assert prompt_items[0]['prompt_meta']['uses_prompt_order'] is True
    assert prompt_items[0]['prompt_meta']['order_index'] == 0
    assert prompt_items[0]['prompt_meta']['is_orphan'] is False
    assert '启用' in prompt_items[0]['summary']
    assert '相对位置' in prompt_items[0]['summary']
    assert prompt_items[2]['prompt_meta']['is_marker'] is True
    assert prompt_items[2]['content_editable'] is False
    assert prompt_items[2]['prompt_meta']['content_editable'] is False
    assert prompt_items[2]['prompt_meta']['is_orphan'] is True
    assert '预留字段' in prompt_items[2]['summary']


def test_preset_detail_reader_view_stays_generic_for_prompt_only_generic_preset(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'generic-prompt-only.json',
        {
            'name': 'Generic Prompt Only',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                }
            ],
            'custom_flag': {'keep': True},
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::generic-prompt-only.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    prompt_items = [item for item in preset['reader_view']['items'] if item['type'] == 'prompt']

    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'
    assert preset['reader_view']['family'] == 'generic'
    assert preset['reader_view']['family_label'] == '通用预设'
    assert preset['reader_view']['scalar_workspace'] is None
    assert len(prompt_items) == 1
    assert prompt_items[0]['payload']['identifier'] == 'main'
    assert prompt_items[0]['editor']['kind'] == 'raw-json'
    assert 'prompt_meta' not in prompt_items[0]
    assert 'reorderable' not in prompt_items[0]
    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'


def test_preset_detail_detects_openai_profile_from_prompt_metadata_without_prompt_order(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'prompt-metadata-openai.json',
        {
            'name': 'Prompt Metadata OpenAI',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'system_prompt': True,
                },
                {
                    'identifier': 'worldInfoAfter',
                    'name': 'World Info (after)',
                    'system_prompt': True,
                    'marker': True,
                },
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::prompt-metadata-openai.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_stays_generic_when_prompts_only_use_enabled_without_st_metadata(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'prompt-enabled-generic.json',
        {
            'name': 'Prompt Enabled Generic',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'enabled': False,
                }
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::prompt-enabled-generic.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'


def test_preset_detail_uses_openai_prompt_manager_when_enabled_and_simple_prompt_order_are_present(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'prompt-enabled-order-generic.json',
        {
            'name': 'Prompt Enabled Order Generic',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'enabled': False,
                }
            ],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::prompt-enabled-order-generic.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_returns_family_context_for_versioned_global_preset(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    shared_meta = {
        'preset_family_id': 'family-alpha',
        'preset_family_name': 'Companion Family',
    }
    _write_json(
        presets_dir / '写作' / 'companion-v1.json',
        {
            'name': 'Companion V1',
            'x_st_manager': {
                **shared_meta,
                'preset_version_label': 'v1',
                'preset_version_order': 10,
                'preset_is_default_version': True,
            },
        },
    )
    _write_json(
        presets_dir / '写作' / 'companion-v2.json',
        {
            'name': 'Companion V2',
            'x_st_manager': {
                **shared_meta,
                'preset_version_label': 'v2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::写作/companion-v2.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    assert preset['id'] == 'global::写作/companion-v2.json'
    assert preset['family_info'] == {
        'entry_type': 'family',
        'id': 'global::global::family-alpha',
        'family_id': 'family-alpha',
        'family_name': 'Companion Family',
        'default_version_id': 'global::写作/companion-v1.json',
        'default_version_label': 'v1',
        'version_count': 2,
        'source_type': 'global',
        'root_scope_key': 'global',
    }
    assert preset['current_version'] == {
        'id': 'global::写作/companion-v2.json',
        'name': 'Companion V2',
        'version_label': 'v2',
        'version_order': 20,
        'is_default_version': False,
    }
    assert preset['available_versions'] == [
        {
            'id': 'global::写作/companion-v1.json',
            'name': 'Companion V1',
            'version_label': 'v1',
            'version_order': 10,
            'is_default_version': True,
        },
        {
            'id': 'global::写作/companion-v2.json',
            'name': 'Companion V2',
            'version_label': 'v2',
            'version_order': 20,
            'is_default_version': False,
        },
    ]


def test_preset_detail_reader_view_stays_generic_for_prompt_and_prompt_order_without_openai_markers(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'generic-prompt-order.json',
        {
            'name': 'Generic Prompt Order',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                }
            ],
            'prompt_order': ['main'],
            'custom_flag': {'keep': True},
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::generic-prompt-order.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']

    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'
    assert preset['reader_view']['family'] == 'generic'


def test_preset_detail_reader_view_reads_enabled_state_from_nested_st_prompt_order(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'st-openai.json',
        {
            'name': 'ST OpenAI',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'system_prompt': True,
                },
                {
                    'identifier': 'worldInfoBefore',
                    'name': 'World Info (before)',
                    'system_prompt': True,
                    'marker': True,
                },
            ],
            'prompt_order': [
                {
                    'character_id': 100000,
                    'order': [
                        {'identifier': 'worldInfoBefore', 'enabled': False},
                        {'identifier': 'main', 'enabled': True},
                    ],
                },
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::st-openai.json')

    assert res.status_code == 200
    payload = res.get_json()
    prompt_items = [item for item in payload['preset']['reader_view']['items'] if item['type'] == 'prompt']

    assert [item['payload']['identifier'] for item in prompt_items] == ['worldInfoBefore', 'main']
    assert prompt_items[0]['prompt_meta']['is_enabled'] is False
    assert prompt_items[0]['prompt_meta']['uses_prompt_order'] is True
    assert prompt_items[0]['content_editable'] is False
    assert '禁用' in prompt_items[0]['summary']


def test_preset_detail_uses_openai_prompt_manager_for_object_prompt_order_entries(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'object-prompt-order.json',
        {
            'name': 'Object Prompt Order',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                },
                {
                    'identifier': 'summary',
                    'name': 'Summary',
                    'role': 'assistant',
                    'content': '总结要点',
                },
            ],
            'prompt_order': [
                {'identifier': 'summary'},
                {'identifier': 'main', 'enabled': False},
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::object-prompt-order.json')

    assert res.status_code == 200
    payload = res.get_json()['preset']
    prompt_items = [item for item in payload['reader_view']['items'] if item['type'] == 'prompt']

    assert payload['preset_kind'] == 'openai'
    assert payload['reader_view']['family'] == 'prompt_manager'
    assert [item['payload']['identifier'] for item in prompt_items] == ['summary', 'main']
    assert prompt_items[0]['prompt_meta']['is_enabled'] is True
    assert prompt_items[1]['prompt_meta']['is_enabled'] is False


def test_preset_detail_reader_view_uses_prompt_enabled_state_for_simple_prompt_order(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'simple-openai.json',
        {
            'name': 'Simple OpenAI',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'enabled': False,
                },
                {
                    'identifier': 'summary',
                    'name': 'Summary',
                    'role': 'assistant',
                    'content': '总结要点',
                    'enabled': True,
                },
            ],
            'prompt_order': ['main', 'summary'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::simple-openai.json')

    assert res.status_code == 200
    payload = res.get_json()
    prompt_items = [item for item in payload['preset']['reader_view']['items'] if item['type'] == 'prompt']

    assert [item['payload']['identifier'] for item in prompt_items] == ['main', 'summary']
    assert prompt_items[0]['prompt_meta']['uses_prompt_order'] is True
    assert prompt_items[0]['prompt_meta']['is_enabled'] is True
    assert '启用' in prompt_items[0]['summary']


def test_preset_detail_reader_view_handles_malformed_prompt_position_values(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'bad-position.json',
        {
            'name': 'Bad Position',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                    'injection_position': 'oops',
                    'injection_depth': 'NaN',
                },
            ],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::bad-position.json')

    assert res.status_code == 200
    payload = res.get_json()
    prompt_items = [item for item in payload['preset']['reader_view']['items'] if item['type'] == 'prompt']

    assert len(prompt_items) == 1
    assert '相对位置' in prompt_items[0]['summary']


def test_preset_detail_reader_view_uses_generic_fallback_for_legacy_textgen_prompt_manager(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'st-params.json',
        {
            'name': 'ST Params',
            'temp': 0.8,
            'top_k': 40,
            'top_p': 0.92,
            'min_p': 0.1,
            'rep_pen': 1.1,
            'freq_pen': 0.2,
            'pres_pen': 0.1,
            'temperature_last': True,
            'dynatemp': True,
            'min_temp': 0.5,
            'max_temp': 1.2,
            'mirostat_mode': 2,
            'mirostat_tau': 5,
            'mirostat_eta': 0.1,
            'guidance_scale': 1.5,
            'negative_prompt': 'avoid repetition',
            'json_schema': '{"type":"object"}',
            'grammar_string': 'root ::= "hi"',
            'banned_tokens': 'bad\nword',
            'logit_bias': [{'text': 'forbidden', 'value': -10}],
            'sampler_order': ['temperature', 'top_p'],
            'samplers': ['top_p', 'min_p'],
            'top_a': 0.4,
            'typical_p': 0.95,
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                }
            ],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::st-params.json')

    assert res.status_code == 200
    payload = res.get_json()
    reader_view = payload['preset']['reader_view']
    scalar_field_keys = {
        item['payload']['key']
        for item in reader_view['items']
        if item.get('group') == 'scalar_fields' and item.get('type') == 'field'
    }

    assert payload['preset']['preset_kind'] == 'generic'
    assert reader_view['family'] == 'generic'
    assert reader_view['scalar_workspace'] is None
    assert {'temp', 'top_p', 'rep_pen', 'temperature_last'} <= scalar_field_keys


def test_preset_detail_exposes_chat_completion_editor_profile(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'chat-mirror.json',
        {
            'name': 'Chat Mirror',
            'temperature': 0.8,
            'top_p': 0.92,
            'frequency_penalty': 0.3,
            'presence_penalty': 0.2,
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'stream_openai': True,
            'show_thoughts': True,
            'reasoning_effort': 'medium',
            'logit_bias': [{'text': 'foo', 'value': 1}],
            'prompts': [{'identifier': 'main', 'role': 'system', 'content': '你是助手'}],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::chat-mirror.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    profile = preset['editor_profile']

    assert profile['id'] == 'st_chat_completion_preset'
    assert profile['id'] != 'st_textgen_preset'
    assert profile['family'] == 'st_mirror'
    assert profile['supports_prompt_workspace'] is True
    assert profile['save_target'] == 'st_openai_preset_dir'
    assert profile['reader_layout'] == 'mirrored_sections'
    assert [section['id'] for section in profile['sections']] == [
        'provider_and_models',
        'connection_and_endpoints',
        'output_and_reasoning',
        'core_sampling',
        'penalties_and_behavior',
        'prompt_manager',
        'templates_and_features',
        'images_and_advanced',
    ]
    assert profile['fields']['temperature']['canonical_key'] == 'temperature'
    assert profile['fields']['temperature']['storage_keys'] == ['temperature', 'temp']
    assert profile['fields']['temperature']['step'] == 0.01
    assert profile['fields']['temperature']['preserve_existing_key'] is True
    assert profile['fields']['openai_max_context']['control'] == 'range_with_number'
    assert profile['fields']['openai_max_context']['min'] == 512
    assert profile['fields']['openai_max_context']['max']['type'] == 'dynamic'
    assert profile['fields']['openai_max_context']['step'] == 1
    assert profile['fields']['openai_max_tokens']['max'] == 128000
    assert profile['fields']['reasoning_effort']['options'] == ['auto', 'low', 'medium', 'high', 'min', 'max']
    assert profile['fields']['prompts']['control'] == 'prompt_workspace'
    assert profile['fields']['prompt_order']['control'] == 'prompt_workspace'
    assert profile['fields']['wi_format']['control'] == 'textarea'
    assert profile['fields']['extensions']['control'] == 'raw_json'


def test_preset_detail_uses_generic_editor_profile_for_legacy_textgen_shape(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'textgen-mirror.json',
        {
            'name': 'Textgen Mirror',
            'temp': 1.1,
            'top_p': 0.93,
            'top_k': 40,
            'rep_pen': 1.2,
            'freq_pen': 0.15,
            'pres_pen': 0.05,
            'streaming': True,
            'dynatemp': True,
            'min_temp': 0.7,
            'max_temp': 1.4,
            'mirostat_mode': 2,
            'sampler_order': ['temperature', 'top_p'],
            'samplers': ['top_p', 'min_p'],
            'prompts': [{'identifier': 'main', 'role': 'system', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::textgen-mirror.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    profile = preset['editor_profile']

    assert preset['preset_kind'] == 'generic'
    assert profile['id'] == 'generic_json'
    assert profile['family'] == 'generic'
    assert profile['supports_prompt_workspace'] is False
    assert profile['save_target'] == 'presets_dir'
    assert profile['reader_layout'] == 'generic'
    assert profile['fields'] == {}


def test_preset_detail_editor_profile_fields_use_canonical_keys_and_hide_absent_present_only_fields(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'chat-canonical.json',
        {
            'name': 'Chat Canonical',
            'temp': 0.8,
            'top_p': 0.92,
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'stream_openai': True,
            'prompts': [{'identifier': 'main', 'role': 'system', 'content': 'hello'}],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::chat-canonical.json')

    assert res.status_code == 200
    fields = res.get_json()['preset']['editor_profile']['fields']

    assert 'temperature' in fields
    assert fields['temperature']['storage_key'] == 'temp'
    assert fields['temperature']['source_key'] == 'temp'
    assert 'temp' not in fields
    assert 'logit_bias' not in fields


def test_preset_detail_falls_back_to_chat_completion_editor_profile_for_mixed_legacy_textgen_shapes(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'legacy-mixed-textgen.json',
        {
            'name': 'Legacy Mixed Textgen',
            'temp': 1.1,
            'top_p': 0.93,
            'rep_pen': 1.2,
            'dynatemp': True,
            'sampler_order': ['temperature', 'top_p'],
            'openai_max_tokens': 2048,
            'prompts': [{'identifier': 'main', 'role': 'system', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::legacy-mixed-textgen.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'
    assert 'repetition_penalty' in preset['editor_profile']['fields']
    assert preset['editor_profile']['fields']['repetition_penalty']['control'] == 'range_with_number'


def test_preset_detail_falls_back_to_generic_editor_profile_for_temperature_alias_shape(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'temperature-alias-textgen.json',
        {
            'name': 'Temperature Alias Textgen',
            'temperature': 0.8,
            'top_p': 0.9,
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::temperature-alias-textgen.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'
    assert preset['editor_profile']['fields'] == {}


def test_preset_detail_prefers_chat_completion_editor_profile_when_chat_markers_dominate_alias_overlap(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'chat-alias-overlap.json',
        {
            'name': 'Chat Alias Overlap',
            'temp': 0.8,
            'freq_pen': 0.2,
            'pres_pen': 0.1,
            'openai_max_context': 8192,
            'openai_max_tokens': 1200,
            'stream_openai': True,
            'reasoning_effort': 'medium',
            'prompts': [{'identifier': 'main', 'role': 'system', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::chat-alias-overlap.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'
    assert 'openai_max_context' in preset['editor_profile']['fields']


def test_preset_detail_detects_openai_profile_from_new_st_provider_field_only(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'openrouter-only.json',
        {
            'name': 'OpenRouter Only',
            'openrouter_model': 'openrouter/auto',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::openrouter-only.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_detects_openai_profile_from_openai_model_only(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'openai-model-only.json',
        {
            'name': 'OpenAI Model Only',
            'openai_model': 'gpt-4.1',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::openai-model-only.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_detects_openai_profile_from_verbosity_only(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'verbosity-only.json',
        {
            'name': 'Verbosity Only',
            'verbosity': 'high',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::verbosity-only.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_uses_openai_alt_root_path_hint_for_sparse_preset(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    openai_dir = tmp_path / 'st-openai-presets'
    _write_json(
        openai_dir / 'sparse-openai.json',
        {
            'name': 'Sparse OpenAI',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
            'st_openai_preset_dir': str(openai_dir),
            'st_textgen_preset_dir': '',
            'st_instruct_preset_dir': '',
            'st_context_preset_dir': '',
            'st_sysprompt_dir': '',
            'st_reasoning_dir': '',
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global-alt::st_openai_preset_dir::sparse-openai.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['editor_profile']['id'] == 'st_chat_completion_preset'


def test_preset_detail_does_not_use_normal_openai_folder_name_as_openai_hint(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'openai' / 'sparse-generic.json',
        {
            'name': 'Sparse Generic',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
            'st_openai_preset_dir': '',
            'st_textgen_preset_dir': '',
            'st_instruct_preset_dir': '',
            'st_context_preset_dir': '',
            'st_sysprompt_dir': '',
            'st_reasoning_dir': '',
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::openai/sparse-generic.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'generic'
    assert preset['editor_profile']['id'] == 'generic_json'


def test_preset_detail_exposes_new_openai_provider_fields_in_sections(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'custom-url-openai.json',
        {
            'name': 'Custom URL OpenAI',
            'custom_url': 'https://example.invalid/v1',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::custom-url-openai.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['sections']['connection_and_endpoints'] == [
        {
            'key': 'custom_url',
            'source_key': 'custom_url',
            'label': '自定义接口地址',
            'value': 'https://example.invalid/v1',
        }
    ]


def test_preset_detail_exposes_aligned_openai_output_and_behavior_sections(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'aligned-openai-sections.json',
        {
            'name': 'Aligned OpenAI Sections',
            'openai_max_context': 8192,
            'reasoning_effort': 'medium',
            'verbosity': 'high',
            'names_behavior': 'always',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::aligned-openai-sections.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['sections']['output_and_reasoning'] == [
        {
            'key': 'openai_max_context',
            'source_key': 'openai_max_context',
            'label': '上下文长度',
            'value': 8192,
        },
        {
            'key': 'reasoning_effort',
            'source_key': 'reasoning_effort',
            'label': '推理强度',
            'value': 'medium',
        },
        {
            'key': 'verbosity',
            'source_key': 'verbosity',
            'label': '输出冗长度',
            'value': 'high',
        },
    ]
    assert preset['sections']['penalties_and_behavior'] == [
        {
            'key': 'names_behavior',
            'source_key': 'names_behavior',
            'label': '名称行为',
            'value': 'always',
        }
    ]

    reader_field = preset['reader_view']['scalar_workspace']['field_map']['names_behavior']
    assert reader_field['control'] == 'select'
    assert reader_field['options'] == [-1, 0, 1, 2]


def test_preset_detail_uses_canonical_openai_section_keys(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'canonical-openai-keys.json',
        {
            'name': 'Canonical OpenAI Keys',
            'openai_max_tokens': 1200,
            'temp': 0.8,
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::canonical-openai-keys.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'
    assert preset['sections']['output_and_reasoning'] == [
        {
            'key': 'openai_max_tokens',
            'source_key': 'openai_max_tokens',
            'label': '最大生成长度',
            'value': 1200,
        }
    ]
    assert preset['sections']['core_sampling'] == [
        {
            'key': 'temperature',
            'source_key': 'temp',
            'label': '温度',
            'value': 0.8,
        }
    ]
    assert all(item['key'] != 'max_tokens' for item in preset['sections']['output_and_reasoning'])
    assert all(item['key'] != 'temp' for item in preset['sections']['core_sampling'])


def test_preset_detail_uses_only_aligned_openai_section_ids_for_advanced_fields(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'aligned-openai-advanced-sections.json',
        {
            'name': 'Aligned OpenAI Advanced Sections',
            'openai_model': 'gpt-4.1',
            'dynamic_temperature': True,
            'mirostat_mode': 2,
            'mirostat_tau': 5,
            'mirostat_eta': 0.1,
            'guidance_scale': 1.5,
            'negative_prompt': 'avoid repetition',
            'wrap_in_quotes': True,
            'json_schema': '{"type":"object"}',
            'grammar': 'root ::= "ok"',
            'logit_bias': [{'text': 'forbidden', 'value': -10}],
            'sampler_order': ['temperature', 'top_p'],
            'samplers': ['top_p', 'min_p'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::aligned-openai-advanced-sections.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    assert preset['preset_kind'] == 'openai'

    assert 'images_and_advanced' in preset['sections']
    assert {item['key'] for item in preset['sections']['images_and_advanced']} >= {
        'dynamic_temperature',
        'mirostat_mode',
        'mirostat_tau',
        'mirostat_eta',
        'guidance_scale',
        'negative_prompt',
        'wrap_in_quotes',
        'json_schema',
        'grammar',
        'logit_bias',
        'sampler_order',
        'samplers',
    }

    assert 'core_sampling_advanced' not in preset['sections']
    assert 'schema_and_grammar' not in preset['sections']
    assert 'bans_and_bias' not in preset['sections']
    assert 'sampler_ordering' not in preset['sections']


def test_preset_detail_reader_view_flattens_all_nested_prompt_order_buckets(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'multi-bucket.json',
        {
            'name': 'Multi Bucket',
            'prompts': [
                {'identifier': 'alpha', 'name': 'Alpha', 'role': 'system', 'content': 'A'},
                {'identifier': 'beta', 'name': 'Beta', 'role': 'system', 'content': 'B'},
                {'identifier': 'gamma', 'name': 'Gamma', 'role': 'system', 'content': 'C'},
            ],
            'prompt_order': [
                {
                    'character_id': 100000,
                    'order': [
                        {'identifier': 'beta', 'enabled': False},
                    ],
                },
                {
                    'character_id': 100001,
                    'order': [
                        {'identifier': 'alpha', 'enabled': True},
                        {'identifier': 'gamma', 'enabled': True},
                    ],
                },
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::multi-bucket.json')

    assert res.status_code == 200
    payload = res.get_json()['preset']
    prompt_items = [item for item in payload['reader_view']['items'] if item['type'] == 'prompt']

    assert [item['payload']['identifier'] for item in prompt_items] == ['beta', 'alpha', 'gamma']
    assert prompt_items[0]['prompt_meta']['is_enabled'] is False
    assert prompt_items[1]['prompt_meta']['is_enabled'] is True
    assert prompt_items[2]['prompt_meta']['is_enabled'] is True
    assert prompt_items[0]['prompt_meta']['is_orphan'] is False
    assert prompt_items[1]['prompt_meta']['is_orphan'] is True
    assert prompt_items[2]['prompt_meta']['is_orphan'] is True
    assert prompt_items[0]['prompt_meta']['character_id'] == 100000


def test_preset_detail_reader_view_deduplicates_prompt_identifiers_across_nested_prompt_order_buckets(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'duplicate-buckets.json',
        {
            'name': 'Duplicate Buckets',
            'prompts': [
                {'identifier': 'alpha', 'name': 'Alpha', 'role': 'system', 'content': 'A'},
                {'identifier': 'beta', 'name': 'Beta', 'role': 'system', 'content': 'B'},
            ],
            'prompt_order': [
                {
                    'character_id': 100000,
                    'order': [
                        {'identifier': 'beta', 'enabled': False},
                        {'identifier': 'alpha', 'enabled': True},
                    ],
                },
                {
                    'character_id': 100001,
                    'order': [
                        {'identifier': 'beta', 'enabled': True},
                    ],
                },
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::duplicate-buckets.json')

    assert res.status_code == 200
    payload = res.get_json()['preset']
    prompt_items = [item for item in payload['reader_view']['items'] if item['type'] == 'prompt']

    assert [item['payload']['identifier'] for item in prompt_items] == ['beta', 'alpha']
    assert len(prompt_items) == 2
    assert prompt_items[0]['prompt_meta']['order_index'] == 0
    assert prompt_items[1]['prompt_meta']['order_index'] == 1
    assert prompt_items[0]['prompt_meta']['is_enabled'] is False


def test_preset_detail_openai_prompt_manager_does_not_expose_legacy_scalar_workspace(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'alias-params.json',
        {
            'name': 'Alias Params',
            'temp': 0.7,
            'rep_pen': 1.2,
            'freq_pen': 0.3,
            'pres_pen': 0.4,
            'dynatemp': True,
            'min_temp': 0.4,
            'max_temp': 1.1,
            'grammar_string': 'root ::= "ok"',
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::alias-params.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']

    assert preset['preset_kind'] == 'generic'
    assert preset['reader_view']['scalar_workspace'] is None


def test_preset_detail_openai_prompt_manager_keeps_legacy_scalar_fields_in_reader_items(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'hidden-params.json',
        {
            'name': 'Hidden Params',
            'temp': 0.8,
            'top_a': 0.4,
            'typical_p': 0.95,
            'xtc_threshold': 0.2,
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': '你是助手',
                }
            ],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::hidden-params.json')

    assert res.status_code == 200
    preset = res.get_json()['preset']
    reader_view = preset['reader_view']
    scalar_item_keys = [
        item.get('source_key')
        for item in reader_view['items']
        if item.get('group') == 'scalar_fields'
    ]

    assert 'temp' in scalar_item_keys
    assert 'top_a' in scalar_item_keys
    assert 'typical_p' in scalar_item_keys
    assert 'xtc_threshold' in scalar_item_keys
    assert preset['raw_data']['top_a'] == 0.4


def test_preset_detail_reader_view_stays_generic_for_instruct_overlap_without_st_prompt_markers(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'instruct-overlap.json',
        {
            'name': 'Instruct Overlap',
            'temperature': 0.8,
            'grammar': 'root ::= "ok"',
            'input_sequence': 'User:',
            'output_sequence': 'Assistant:',
            'prompts': [
                {
                    'identifier': 'main',
                    'name': 'Main Prompt',
                    'role': 'system',
                    'content': 'hello',
                }
            ],
            'prompt_order': ['main'],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::instruct-overlap.json')

    assert res.status_code == 200
    payload = res.get_json()
    preset = payload['preset']
    assert preset['preset_kind'] == 'generic'
    assert preset['reader_view']['family'] == 'generic'
    assert preset['reader_view']['scalar_workspace'] is None


def test_merge_preset_content_preserves_hidden_textgen_fields_when_visible_workspace_fields_change():
    raw_data = {
        'temp': 0.7,
        'top_a': 0.35,
        'typical_p': 0.9,
        'xtc_threshold': 0.2,
        'prompts': [{'identifier': 'main', 'content': 'hello'}],
    }

    merged = presets_api.merge_preset_content(
        raw_data,
        'generic',
        {
            'temp': 1.05,
            'prompts': [{'identifier': 'main', 'content': 'hello'}],
        },
    )

    assert merged['temp'] == 1.05
    assert merged['top_a'] == 0.35
    assert merged['typical_p'] == 0.9
    assert merged['xtc_threshold'] == 0.2


def test_preset_detail_handles_non_dict_json_root(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(presets_dir / 'list-root.json', ['bad', 'root'])

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::list-root.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    assert preset['name'] == 'list-root'
    assert preset['extensions'] == {}
    assert preset['reader_view']['family'] == 'generic'
    assert preset['reader_view']['items'] == []


def test_preset_detail_reader_view_has_generic_fallback(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'malformed.json',
        {
            'name': 'Malformed',
            'prompt_order': 'not-a-list',
            'prompts': {'main': 'bad-shape'},
            'custom_flag': 'x',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::malformed.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    assert 'reader_view' in preset
    reader_view = preset['reader_view']
    assert reader_view['family'] == 'generic'
    assert reader_view['family_label'] == '通用预设'
    assert reader_view['groups']
    assert reader_view['stats']['prompt_count'] == 0

    group_ids = [group['id'] for group in reader_view['groups']]
    assert 'structured_objects' in group_ids
    assert 'scalar_fields' in group_ids
    assert 'unknown_fields' not in group_ids

    assert all('id' in item and 'title' in item and 'payload' in item for item in reader_view['items'])


def test_preset_detail_reader_items_expose_scalar_editor_metadata(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'textgen.json',
        {
            'name': 'Textgen',
            'temp': 0.8,
            'top_p': 0.92,
            'do_sample': True,
            'negative_prompt': 'avoid repetition',
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::textgen.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    items = preset['reader_view']['items']

    temp_items = [item for item in items if item['group'] == 'scalar_fields' and item['payload']['key'] == 'temp']
    do_sample_items = [
        item for item in items if item['group'] == 'scalar_fields' and item['payload']['key'] == 'do_sample'
    ]
    negative_prompt_items = [
        item
        for item in items
        if item['group'] == 'scalar_fields' and item['payload']['key'] == 'negative_prompt'
    ]

    assert len(temp_items) == 1
    assert len(do_sample_items) == 1
    assert len(negative_prompt_items) == 1

    temp_item = temp_items[0]
    do_sample_item = do_sample_items[0]
    negative_prompt_item = negative_prompt_items[0]

    assert temp_item['editable'] is True
    assert temp_item['source_key'] == 'temp'
    assert temp_item['value_path'] == 'temp'
    assert temp_item['editor']['kind'] == 'number'

    assert do_sample_item['editor']['kind'] == 'boolean'
    assert negative_prompt_item['editor']['kind'] == 'textarea'


def test_preset_detail_reader_items_expose_logit_bias_editor_metadata(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'textgen-bias.json',
        {
            'name': 'Textgen Bias',
            'temp': 0.8,
            'logit_bias': [
                {'text': 'forbidden', 'value': -10},
            ],
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::textgen-bias.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True

    preset = payload['preset']
    items = preset['reader_view']['items']

    bias_items = [
        item for item in items if item['group'] == 'structured_objects' and item['payload']['key'] == 'logit_bias'
    ]

    assert len(bias_items) == 1

    bias_item = bias_items[0]

    assert bias_item['editable'] is True
    assert bias_item['source_key'] == 'logit_bias'
    assert bias_item['value_path'] == 'logit_bias'
    assert bias_item['editor']['kind'] == 'key-value-list'


def test_preset_detail_reader_groups_openai_settings_and_hides_unknown_sensitive_and_spreset_data(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    _write_json(
        presets_dir / 'reader-alignment.json',
        {
            'name': 'Reader Alignment',
            'deepseek_model': 'deepseek-chat',
            'proxy_password': 'secret',
            'custom_url': 'https://example.test',
            'future_runtime_key': 'do not show',
            'prompts': [
                {
                    'identifier': 'relative',
                    'role': 'system',
                    'content': 'relative content',
                    'injection_position': 0,
                    'injection_depth': 33,
                    'injection_order': 44,
                },
                {
                    'identifier': 'absolute',
                    'role': 'system',
                    'content': 'absolute content',
                    'injection_position': 1,
                },
                {
                    'identifier': 'marker',
                    'marker': True,
                    'content': 'marker content must stay hidden',
                },
            ],
            'prompt_order': ['relative', 'absolute', 'marker'],
            'extensions': {
                'SPreset': {'regex': [{'findRegex': 'hidden'}]},
                'regex_scripts': [{'findRegex': 'visible'}],
            },
        },
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')},
    )

    preset = _make_test_app().test_client().get(
        '/api/presets/detail/global::reader-alignment.json'
    ).get_json()['preset']
    reader_view = preset['reader_view']
    prompt_items = [item for item in reader_view['items'] if item['type'] == 'prompt']
    field_map = reader_view['scalar_workspace']['field_map']

    assert [item['payload']['identifier'] for item in prompt_items] == [
        'relative', 'absolute', 'marker'
    ]
    assert 'future_runtime_key' not in field_map
    assert field_map['proxy_password']['reader_value'] == '已设置'
    assert field_map['custom_url']['reader_value'] == '已设置'
    assert reader_view['stats']['base_count'] == len(field_map)
    assert reader_view['stats']['hidden_count'] == 1
    assert [item['title'] for item in reader_view['items'] if item['type'] == 'extension'] == [
        '正则与 ST 脚本'
    ]

    relative_payload = prompt_items[0]['payload']
    absolute_payload = prompt_items[1]['payload']
    marker_payload = prompt_items[2]['payload']
    assert 'injection_depth' not in relative_payload
    assert 'injection_order' not in relative_payload
    assert absolute_payload['injection_depth'] == 4
    assert absolute_payload['injection_order'] == 100
    assert marker_payload['content'] == ''
    assert preset['raw_data']['extensions']['SPreset']['regex'][0]['findRegex'] == 'hidden'
