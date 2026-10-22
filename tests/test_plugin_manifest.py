"""manifest v3 解析与校验测试（设计文档 §4 manifest / §4.9 校验与容错 / §11.1）。

覆盖矩阵：

- 合法 manifest v3（含三个官方插件的形状）；
- v2 manifest（`frontend.entries` / `permissions` / `api_version: 2`）被拒绝，错误码清晰；
- 未知顶层 / `backend.*` / `frontend.*` 键拒绝加载；`x-` 键静默忽略；
- 节点级问题（菜单/插槽/命令）丢弃 + 警告，插件其余部分照常加载；
- 容量/深度上限、命令引用校验、图标检查；
- `capabilities` 未知项保留 + 警告；`global_styles` 能力位门控；
- `PluginManifest.to_dict()` 按实现日志 S2 输出归一化快照。
"""

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


def _valid_menu(menu_id='workbench', placement='dock', **overrides):
    payload = {
        'id': menu_id,
        'placement': placement,
        'type': 'item',
        'label': 'AI 助手',
        'action': {'type': 'url', 'url': 'https://example.com'},
    }
    payload.update(overrides)
    return payload


def _command(command_id='open', **overrides):
    payload = {
        'id': command_id,
        'title': '打开',
        'module': 'frontend/commands.js',
        'export': 'open',
    }
    payload.update(overrides)
    return payload


def _manifest_with_contributions(plugin_id, contribs, **overrides):
    manifest = base_manifest(plugin_id, **overrides)
    manifest['frontend'] = dict(manifest.get('frontend') or {})
    manifest['frontend']['contributions'] = contribs
    return manifest


# ------------------------------------------------------------------ 合法 v3


def test_load_accepts_valid_manifest(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.plugin_id == 'demo-plugin'
    assert manifest.version == '0.1.0'
    assert manifest.api_version == 3
    assert manifest.manifest_version == 3
    assert manifest.has_backend and manifest.has_frontend
    assert manifest.is_frontend_only is False
    assert manifest.backend_jobs == ['demo.run']
    assert manifest.backend_hooks == ['card.updated']
    assert manifest.capabilities == ['cards.read']
    assert manifest.frontend_entry_rel == 'frontend/plugin.js'
    assert manifest.frontend_styles_rel == ['frontend/plugin.css']
    assert manifest.frontend_global_styles_rel == []
    assert manifest.frontend_render_mode == 'declarative'
    assert manifest.frontend_contributions == {'menus': [], 'slots': [], 'commands': []}
    assert manifest.config_schema['properties']['greeting']['default'] == 'hi'
    assert manifest.warnings == []


def test_load_accepts_official_plugin_shaped_manifest(tmp_path):
    """AI 助手形状：贡献树 + 命令 + 能力位 + render_mode 缺省（declarative）。"""
    manifest = base_manifest('stm-ai-assistant')
    manifest['frontend']['contributions'] = {
        'commands': [
            _command('open-workbench', shortcut='Ctrl+Shift+A'),
        ],
        'slots': [{
            'id': 'settings-body',
            'slot': 'settings.section',
            'module': 'frontend/views/settingsSection.js',
            'export': 'mountSettingsSection',
        }],
        'menus': [
            {
                'id': 'workbench',
                'placement': 'dock',
                'type': 'item',
                'label': 'AI 助手',
                'icon': 'wand',
                'action': {'type': 'command', 'id': 'open-workbench'},
            },
            {
                'id': 'ai-group',
                'placement': 'context.folder',
                'type': 'submenu',
                'label': 'AI 助手',
                'children': [_valid_menu('analyze-folder', placement=None)],
            },
        ],
    }
    # 子节点不允许 placement：从夹具里删掉
    manifest['frontend']['contributions']['menus'][1]['children'][0].pop('placement', None)
    manifest['capabilities'] = ['cards.read', 'cards.write', 'network.outbound']

    plugin_dir = write_plugin(tmp_path, 'stm-ai-assistant', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_contributions['commands'][0]['shortcut'] == 'Ctrl+Shift+A'
    assert parsed.frontend_contributions['menus'][1]['children'][0]['id'] == 'analyze-folder'
    assert parsed.warnings == []


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


def test_load_checks_directory_name_only_when_allowed(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('other-plugin'))

    manifest = PluginManifest.load(plugin_dir, check_dir_name=False)

    assert manifest.plugin_id == 'other-plugin'


def test_load_rejects_non_semver_version(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', version='1.0'))

    with pytest.raises(PluginManifestError, match='语义化版本'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_api_version_two(tmp_path):
    """v2 插件被拒绝（ADR-0012：删除旧版本兼容，不保留别名）。"""
    legacy = base_manifest('demo-plugin', api_version=2)

    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=legacy)

    with pytest.raises(PluginApiVersionError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.field == 'api_version'
    assert excinfo.value.user_msg
    assert '3' in str(excinfo.value)


def test_load_rejects_unsupported_api_version(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', api_version=99))

    with pytest.raises(PluginApiVersionError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.field == 'api_version'
    assert excinfo.value.user_msg


def test_load_rejects_manifest_version_two(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', manifest_version=2),
    )

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_version_unsupported'
    assert excinfo.value.field == 'manifest_version'


def test_load_requires_explicit_manifest_version(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest.pop('manifest_version')
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_version_unsupported'


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
        manifest=base_manifest('demo-plugin', backend=None, frontend=None),
        backend=None,
        frontend=None,
    )

    with pytest.raises(PluginManifestError, match='至少要有一个'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_absolute_frontend_entry(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', frontend={
            'entry': 'C:/windows/system32/x.js', 'styles': [],
        }),
        frontend=None,
    )

    with pytest.raises(PluginManifestError, match='frontend.entry'):
        PluginManifest.load(plugin_dir)


def test_unknown_hooks_are_ignored_with_warning(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest(
            'demo-plugin',
            backend={
                'entry': 'backend',
                'register': 'register',
                'jobs': ['demo.run'],
                'hooks': ['card.updated', 'not.a.real.hook'],
            },
        ),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.backend_hooks == ['card.updated']
    assert any('not.a.real.hook' in warning for warning in manifest.warnings)


def test_unknown_capability_is_retained_with_warning(tmp_path):
    """能力位只做披露：未知能力位原样保留（宿主标注「未知名」）并警告。"""
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest(
            'demo-plugin', capabilities=['cards.read', 'totally.new.capability'],
        ),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.capabilities == ['cards.read', 'totally.new.capability']
    assert any('totally.new.capability' in warning for warning in manifest.warnings)


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


def test_load_rejects_missing_manifest(tmp_path):
    plugin_dir = os.path.join(str(tmp_path), 'demo-plugin')
    os.makedirs(plugin_dir)

    with pytest.raises(PluginManifestError, match='缺少 manifest.json'):
        PluginManifest.load(plugin_dir)


def test_load_rejects_oversized_manifest(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        handle.write(' ' * (256 * 1024 + 1))

    with pytest.raises(PluginManifestError, match='过大'):
        PluginManifest.load(plugin_dir)


# ------------------------------------------------------------------ to_dict（S2）


def test_to_dict_exposes_v3_contract_shape(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    payload = PluginManifest.load(plugin_dir).to_dict()

    assert payload['frontend_entry'] == 'frontend/plugin.js'
    assert payload['frontend_styles'] == ['frontend/plugin.css']
    assert payload['frontend_global_styles'] == []
    assert payload['render_mode'] == 'declarative'
    assert payload['capabilities'] == ['cards.read']
    assert payload['contributions'] == {'menus': [], 'slots': [], 'commands': []}
    assert payload['backend'] is True
    assert payload['frontend'] is True
    assert payload['jobs'] == ['demo.run']
    assert payload['hooks'] == ['card.updated']


def test_to_dict_has_no_v2_keys(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    payload = PluginManifest.load(plugin_dir).to_dict()

    assert 'entries' not in payload
    assert 'permissions' not in payload
    for legacy in ('panels', 'settings_tab', 'detail_tab'):
        assert legacy not in payload


def test_to_dict_is_json_serializable(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    payload = PluginManifest.load(plugin_dir).to_dict()

    assert json.loads(json.dumps(payload, ensure_ascii=False))['id'] == 'demo-plugin'


def test_to_dict_contains_normalized_contributions(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {
            'menus': [_valid_menu(icon='wand')],
            'commands': [_command()],
        }),
    )

    payload = PluginManifest.load(plugin_dir).to_dict()

    node = payload['contributions']['menus'][0]
    assert node['placement'] == 'dock'
    assert node['order'] == 100
    assert node['action'] == {'type': 'url', 'url': 'https://example.com'}
    assert payload['contributions']['commands'][0]['id'] == 'open'


def test_homepage_is_the_only_source_url_key(tmp_path):
    """「安装来源」外链**复用** `homepage`，不新增 manifest 键。"""
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', homepage='https://github.com/owner/repo'),
    )

    manifest = PluginManifest.load(plugin_dir)
    assert manifest.homepage == 'https://github.com/owner/repo'
    assert manifest.to_dict()['homepage'] == 'https://github.com/owner/repo'

    plain_dir = write_plugin(tmp_path, 'plain-plugin')
    assert PluginManifest.load(plain_dir).homepage == ''

    bad_dir = write_plugin(
        tmp_path, 'bad-plugin',
        manifest=base_manifest('bad-plugin', source_url='https://github.com/owner/repo'),
    )
    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(bad_dir)
    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'source_url'


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
        manifest=base_manifest('demo-plugin', backend=None),
        backend=None,
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.is_frontend_only is True
    assert manifest.has_backend is False
    assert manifest.to_dict()['frontend_only'] is True


# ------------------------------------------------------------------ 结构键严格校验


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


def test_permissions_top_level_key_is_rejected(tmp_path):
    """`permissions` 改名 `capabilities`，**不保留别名**（ADR-0011）。"""
    manifest = base_manifest('demo-plugin', capabilities=None)
    manifest['permissions'] = ['cards.read']
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'permissions'


def test_unknown_frontend_subkey_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['entrys'] = 'frontend/plugin.js'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'frontend.entrys'
    assert 'contributions' in excinfo.value.hint


def test_unknown_backend_subkey_is_rejected(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['backend']['hooks_'] = []
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_unknown_key'
    assert excinfo.value.field == 'backend.hooks_'


@pytest.mark.parametrize('legacy_key', ['entries', 'panels', 'settings_tab', 'detail_tab'])
def test_legacy_frontend_fields_are_rejected(tmp_path, legacy_key):
    manifest = base_manifest('demo-plugin')
    manifest['frontend'][legacy_key] = [{'id': 'demo'}]
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'manifest_legacy_key'
    assert excinfo.value.field == f'frontend.{legacy_key}'
    assert 'frontend.contributions' in excinfo.value.hint


def test_legacy_entries_error_message_is_human_readable(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['entries'] = []
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    with pytest.raises(PluginManifestError) as excinfo:
        PluginManifest.load(plugin_dir)

    text = str(excinfo.value)
    assert '已废弃字段' in text
    assert 'frontend.contributions' in text


def test_x_prefixed_keys_are_silently_ignored(tmp_path):
    """`x-` 前缀是实验命名空间：顶层、frontend、菜单节点都不警告。"""
    manifest = base_manifest('demo-plugin', **{'x-vendor-experiment': {'anything': True}})
    manifest['frontend']['x-local'] = 'ok'
    manifest['frontend']['contributions'] = {
        'menus': [{
            'id': 'ok',
            'placement': 'dock',
            'type': 'item',
            'label': '演示',
            'action': {'type': 'url', 'url': 'https://example.com'},
            'x-experimental': {'future': True},
        }],
        'slots': [],
        'commands': [],
    }
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_contributions['menus'][0]['id'] == 'ok'
    assert parsed.warnings == []


# ------------------------------------------------------------------ 节点级容错（§4.9）


def test_invalid_contribution_nodes_are_dropped_with_warning(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {
            'menus': [
                {'id': 'Bad_Id', 'placement': 'dock', 'type': 'item', 'label': '非法 id',
                 'action': {'type': 'url', 'url': 'https://example.com'}},
                {'id': 'bad-placement', 'placement': 'toolbar', 'type': 'item', 'label': '非法落点',
                 'action': {'type': 'url', 'url': 'https://example.com'}},
                _valid_menu('ok'),
            ],
            'commands': [
                {'id': 'Bad_Id', 'title': '非法 id', 'module': 'frontend/commands.js', 'export': 'x'},
                _command('good-command'),
            ],
            'slots': [
                {'id': 'bad-slot', 'slot': 'nope.slot',
                 'module': 'frontend/views/s.js', 'export': 'mount'},
            ],
        }),
    )

    parsed = PluginManifest.load(plugin_dir)

    assert [node['id'] for node in parsed.frontend_contributions['menus']] == ['ok']
    assert [item['id'] for item in parsed.frontend_contributions['commands']] == ['good-command']
    # 节点级问题全部变成 warnings，不拒绝加载
    assert len(parsed.warnings) >= 3
    assert all(isinstance(warning, str) for warning in parsed.warnings)


def test_unknown_menu_node_subkey_only_warns(tmp_path):
    node = _valid_menu('ok')
    node['surfaces'] = {'type': 'panel'}
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {'menus': [node]}),
    )

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_contributions['menus'][0]['id'] == 'ok'
    assert any('surfaces' in warning for warning in parsed.warnings)


def test_menu_action_command_reference_is_validated_at_load(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {
            'menus': [_valid_menu('item', action={'type': 'command', 'id': 'missing'})],
            'commands': [],
        }),
    )

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_contributions['menus'] == []
    assert any('missing' in warning for warning in parsed.warnings)


def test_menu_capacity_is_enforced_with_warning(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {
            'menus': [_valid_menu(f'node-{index}') for index in range(70)],
        }),
    )

    parsed = PluginManifest.load(plugin_dir)

    assert len(parsed.frontend_contributions['menus']) == 64
    assert any('上限 64' in warning for warning in parsed.warnings)


def test_unknown_host_icon_warns_but_keeps_node(tmp_path):
    menu = _valid_menu('menu', icon='not-a-real-icon')
    command = _command('cmd', icon='also-not-real')
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_manifest_with_contributions('demo-plugin', {
            'menus': [menu],
            'commands': [command],
        }),
    )

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_contributions['menus'][0]['icon'] == 'not-a-real-icon'
    assert any('not-a-real-icon' in warning for warning in parsed.warnings)
    assert any('also-not-real' in warning for warning in parsed.warnings)


# ------------------------------------------------------------------ 格式非法 / 版本拒绝


def test_v2_manifest_is_rejected_with_clear_error(tmp_path):
    """完整 v2 manifest（entries + permissions + api_version 2）被拒绝。"""
    legacy = {
        'manifest_version': 2,
        'id': 'demo-plugin',
        'name': '老插件',
        'version': '0.1.0',
        'api_version': 2,
        'permissions': ['cards.read'],
        'backend': {'entry': 'backend', 'register': 'register'},
        'frontend': {
            'entry': 'frontend/plugin.js',
            'styles': ['frontend/plugin.css'],
            'entries': [{'id': 'open', 'kind': 'dock', 'label': '打开'}],
        },
    }
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=legacy)

    with pytest.raises(PluginApiVersionError) as excinfo:
        PluginManifest.load(plugin_dir)

    assert excinfo.value.code == 'api_version_unsupported'
    assert excinfo.value.field == 'api_version'


# ------------------------------------------------------------------ 能力位 / render_mode / global_styles


def test_render_mode_defaults_to_declarative(tmp_path):
    manifest = base_manifest('demo-plugin', capabilities=['ui.custom'])
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    assert PluginManifest.load(plugin_dir).frontend_render_mode == 'declarative'


def test_custom_render_mode_loads_and_is_exposed(tmp_path):
    manifest = base_manifest('demo-plugin', capabilities=['ui.custom'])
    manifest['frontend']['render_mode'] = 'custom'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_render_mode == 'custom'
    assert parsed.to_dict()['render_mode'] == 'custom'
    assert parsed.warnings == []


def test_custom_render_mode_without_capability_warns_but_loads(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['render_mode'] = 'custom'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_render_mode == 'custom'
    assert any('ui.custom' in warning for warning in parsed.warnings)


def test_invalid_render_mode_falls_back_to_declarative_with_warning(tmp_path):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['render_mode'] = 'fancy'
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_render_mode == 'declarative'
    assert any('render_mode' in warning for warning in parsed.warnings)


def test_global_styles_are_kept_with_capability(tmp_path):
    manifest = base_manifest('demo-plugin', capabilities=['cards.read', 'ui.global_styles'])
    manifest['frontend']['global_styles'] = ['frontend/global.css']
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)
    with open(os.path.join(plugin_dir, 'frontend', 'global.css'), 'w', encoding='utf-8') as handle:
        handle.write('body { color: inherit; }\n')

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_global_styles_rel == ['frontend/global.css']
    assert parsed.frontend_global_styles == [
        os.path.join(plugin_dir, 'frontend', 'global.css'),
    ]
    assert parsed.to_dict()['frontend_global_styles'] == ['frontend/global.css']
    assert parsed.warnings == []


def test_global_styles_without_capability_are_refused_with_warning(tmp_path):
    """缺 `ui.global_styles` 能力位时宿主拒绝注入：路径置空 + 警告（文件甚至不必存在）。"""
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['global_styles'] = ['frontend/global.css']
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)

    parsed = PluginManifest.load(plugin_dir)

    assert parsed.frontend_global_styles_rel == []
    assert parsed.frontend_global_styles == []
    assert parsed.to_dict()['frontend_global_styles'] == []
    assert any('ui.global_styles' in warning for warning in parsed.warnings)


def test_global_styles_capability_does_not_leak_into_scoped_styles(tmp_path):
    manifest = base_manifest('demo-plugin', capabilities=['ui.global_styles'])
    manifest['frontend']['global_styles'] = ['frontend/global.css']
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', manifest=manifest)
    with open(os.path.join(plugin_dir, 'frontend', 'global.css'), 'w', encoding='utf-8') as handle:
        handle.write('body { color: inherit; }\n')

    parsed = PluginManifest.load(plugin_dir)

    # 作用域扫描只看 styles；global_styles 是免扫描文件
    assert parsed.frontend_styles_rel == ['frontend/plugin.css']
    assert 'frontend/global.css' not in parsed.frontend_styles_rel
