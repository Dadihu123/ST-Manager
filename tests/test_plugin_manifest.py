"""manifest 解析与校验测试（设计文档 2.2 / 13.1）。"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins.errors import PluginApiVersionError, PluginManifestError
from core.plugins.manifest import PluginManifest, compare_versions, parse_semver
from core.version import APP_VERSION
from tests.plugins_test_support import base_manifest, write_plugin


def test_load_accepts_valid_manifest(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.plugin_id == 'demo-plugin'
    assert manifest.version == '0.1.0'
    assert manifest.api_version == 1
    assert manifest.has_backend and manifest.has_frontend
    assert manifest.is_frontend_only is False
    assert manifest.backend_jobs == ['demo.run']
    assert manifest.backend_hooks == ['card.updated']
    assert manifest.permissions == ['cards.read']
    assert manifest.frontend_entry_rel == 'frontend/plugin.js'
    assert manifest.frontend_styles_rel == ['frontend/plugin.css']
    assert manifest.config_schema['properties']['greeting']['default'] == 'hi'


def test_load_rejects_invalid_id_pattern(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'Demo_Plugin')

    with pytest.raises(PluginManifestError, match='id'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_id_directory_mismatch(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('other-plugin'))

    with pytest.raises(PluginManifestError, match='目录名'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_expected_id_mismatch(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    with pytest.raises(PluginManifestError, match='预期'):
        PluginManifest.load(plugin_dir, expected_id='another-plugin')


def test_load_rejects_non_semver_version(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', version='1.0'))

    with pytest.raises(PluginManifestError, match='语义化版本'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_unsupported_api_version(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', api_version=99))

    with pytest.raises(PluginApiVersionError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.field == 'api_version'
    assert excinfo.value.user_msg


def test_load_accepts_legacy_api_version(tmp_path):
    """api_version 1 是受支持的旧契约（多版本机制的第一个真实用例）。"""
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', api_version=1))

    assert PluginManifest.load(plugin_dir).api_version == 1


def test_load_rejects_newer_min_app_version(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', min_app_version='99.0.0'),
    )

    with pytest.raises(PluginManifestError, match='升级主程序'):
        PluginManifest.load(plugin_dir)


def test_load_accepts_current_min_app_version(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', min_app_version=APP_VERSION),
    )

    assert PluginManifest.load(plugin_dir).min_app_version == APP_VERSION


def test_load_rejects_backend_entry_escape(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', backend={'entry': '../outside', 'register': 'register'}),
    )

    with pytest.raises(PluginManifestError, match='backend.entry'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_backend_entry_without_init(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', backend=None)
    os.makedirs(os.path.join(plugin_dir, 'backend'), exist_ok=True)

    with pytest.raises(PluginManifestError, match='__init__.py'):
        PluginManifest.load(plugin_dir)


def test_load_requires_backend_or_frontend(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', backend={}, frontend={}),
        frontend=None,
    )

    with pytest.raises(PluginManifestError, match='至少要有一个'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_absolute_frontend_entry(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', frontend={'entry': 'C:/windows/system32/x.js', 'styles': []}),
        frontend=None,
    )

    with pytest.raises(PluginManifestError, match='frontend.entry'):
        PluginManifest.load(plugin_dir)


def test_unknown_hooks_and_permissions_are_ignored_with_warning(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest(
            'demo-plugin',
            permissions=['cards.read', 'os.shell'],
            backend={
                'entry': 'backend',
                'register': 'register',
                'jobs': ['demo.run'],
                'hooks': ['card.updated', 'not.a.real.hook'],
            },
        ),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.permissions == ['cards.read']
    assert manifest.backend_hooks == ['card.updated']
    assert any('not.a.real.hook' in warning for warning in manifest.warnings)
    assert any('os.shell' in warning for warning in manifest.warnings)


def test_load_rejects_invalid_job_type(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest(
            'demo-plugin',
            backend={'entry': 'backend', 'register': 'register', 'jobs': ['Demo Run!'], 'hooks': []},
        ),
    )

    with pytest.raises(PluginManifestError, match='backend.jobs'):
        PluginManifest.load(plugin_dir)


def test_config_schema_subset_drops_unsupported_types(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', config_schema={
            'type': 'object',
            'properties': {
                'ok': {'type': 'string', 'default': 'x'},
                'bad': {'type': 'array'},
                'nested': {'type': 'object', 'properties': {'a': {'type': 'string'}}},
            },
            'required': ['ok', 'missing'],
        }),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert set(manifest.config_schema['properties'].keys()) == {'ok'}
    assert manifest.config_schema['required'] == ['ok']


def test_invalid_root_schema_falls_back_to_empty_form(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', secret_schema={'type': 'array'}),
    )

    assert PluginManifest.load(plugin_dir).secret_schema == {}


def test_load_rejects_malformed_json(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        handle.write('{not json')

    with pytest.raises(PluginManifestError, match='JSON'):
        PluginManifest.load(plugin_dir)


def test_to_dict_exposes_frontend_relative_paths(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    payload = PluginManifest.load(plugin_dir).to_dict()

    assert payload['frontend_entry'] == 'frontend/plugin.js'
    assert payload['frontend_styles'] == ['frontend/plugin.css']
    assert payload['backend'] is True
    assert payload['frontend'] is True


def test_semver_helpers():
    assert parse_semver('1.2.3') == (1, 2, 3)
    assert parse_semver('1.2.3-beta.1+build') == (1, 2, 3)
    assert parse_semver('1.2') is None
    assert compare_versions('1.10.0', '1.9.9') == 1
    assert compare_versions('1.0.0', '1.0.0') == 0
    assert compare_versions('0.9.0', '1.0.0') == -1


def test_frontend_only_plugin_is_flagged(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', backend={}),
        backend=None,
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.is_frontend_only is True
    assert manifest.to_dict()['frontend_only'] is True
    assert json.loads(json.dumps(manifest.to_dict()))  # to_dict 可 JSON 序列化


# --- 结构键严格校验（D3） ---------------------------------------------------


def test_unknown_top_level_key_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['entires'] = []
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'entires'
    assert excinfo.value.hint
    assert '插件' in excinfo.value.user_msg


def test_unknown_frontend_subkey_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['entrys'] = 'frontend/plugin.js'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'frontend.entrys'
    assert 'entry' in excinfo.value.hint and 'entries' in excinfo.value.hint


def test_unknown_backend_subkey_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['backend']['hooks_'] = []
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'backend.hooks_'


def test_unknown_entry_subkey_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = [
        {'id': 'demo', 'kind': 'dock', 'label': '演示', 'surfaces': {'type': 'panel'}},
    ]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'frontend.entries[0].surfaces'


def test_legacy_frontend_fields_are_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['panels'] = [{'id': 'demo'}]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_legacy_key'
    assert excinfo.value.field == 'frontend.panels'
    assert 'frontend.entries' in excinfo.value.hint


def test_error_message_stays_human_readable(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['settings_tab'] = {'id': 'demo'}
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    text = str(excinfo.value)
    assert '已废弃字段' in text
    assert 'frontend.entries' in text


# --- manifest_version -------------------------------------------------------


def test_manifest_version_defaults_to_one(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.manifest_version == 1
    assert manifest.to_dict()['manifest_version'] == 1


def test_manifest_version_two_is_accepted(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    assert PluginManifest.load(plugin_dir).manifest_version == 2


def test_manifest_version_rejects_unsupported_value(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 99
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_version_unsupported'
    assert excinfo.value.field == 'manifest_version'


def test_manifest_version_rejects_non_integer(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = '2'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError, match='manifest_version'):
        PluginManifest.load(plugin_dir)


def test_manifest_requires_array_entries(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = {'id': 'demo'}
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.field == 'frontend.entries'


# --- entries 解析（宽松） ---------------------------------------------------


def test_entries_are_normalized_with_host_keys(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = [
        {
            'id': 'open-demo',
            'kind': 'dock',
            'label': '打开演示',
            'icon': 'wand',
            'contexts': ['cards', 'chats'],
            'surface': {'type': 'panel'},
            'priority': 10,
        },
    ]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    entry = PluginManifest.load(plugin_dir).frontend_entries[0]

    assert entry['key'] == 'demo-plugin:open-demo'
    assert entry['plugin_id'] == 'demo-plugin'
    assert entry['surface'] == {'type': 'panel'}
    assert entry['contexts'] == ['cards', 'chats']
    assert entry['priority'] == 10
    # tier 由 catalog 决定（D5），manifest 解析阶段不写入
    assert 'tier' not in entry


def test_invalid_entries_are_dropped_with_warning(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = [
        {'id': 'Bad_Id', 'kind': 'dock', 'label': '非法 id'},
        {'id': 'bad-kind', 'kind': 'toolbar', 'label': '非法 kind'},
        {'id': 'no-label', 'kind': 'dock'},
        {'id': 'ok', 'kind': 'command', 'label': '可用'},
    ]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert [item['id'] for item in parsed.frontend_entries] == ['ok']
    assert len(parsed.warnings) >= 3


def test_entries_limit_is_enforced(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = [
        {'id': f'entry-{index}', 'kind': 'command', 'label': f'入口 {index}'}
        for index in range(20)
    ]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert len(parsed.frontend_entries) == 16
    assert any('上限' in item for item in parsed.warnings)


def test_to_dict_has_no_legacy_panel_keys(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    payload = PluginManifest.load(plugin_dir).to_dict()

    assert 'panels' not in payload
    assert 'settings_tab' not in payload
    assert payload['entries'] == []
