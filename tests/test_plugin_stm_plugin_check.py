"""`tools/stm_plugin_check.py`（stm-plugin-check）的严格校验测试。

覆盖设计文档 §11.1 的负例矩阵：每个反例都必须**非零退出**并给出定位；
正例（合法 v3 插件）必须零退出。另验证 `--json` 机器可读输出、内嵌生成区
（contract.py 源码）与宿主同步、以及脚本可复制到任意插件仓库独立运行。
"""

import copy
import json
import os
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools import gen_plugin_api_docs
from tools import stm_plugin_check
from tools.stm_plugin_check import (
    CHECK_DEFINITIONS,
    HOST_ICON_NAMES,
    main as check_main,
    validate_plugin,
)

BASE_MANIFEST = {
    'manifest_version': 3,
    'id': 'demo-plugin',
    'name': '演示插件',
    'version': '0.1.0',
    'api_version': 3,
    'author': 'tests',
    'description': 'stm-plugin-check 正例夹具',
    'license': 'MIT',
    'backend': {
        'entry': 'backend',
        'register': 'register',
        'jobs': [],
        'hooks': [],
    },
    'frontend': {
        'entry': 'frontend/plugin.js',
        'styles': ['frontend/plugin.css'],
        'render_mode': 'declarative',
        'contributions': {
            'menus': [
                {
                    'id': 'open-panel',
                    'placement': 'dock',
                    'type': 'item',
                    'label': '打开面板',
                    'description': '打开演示面板',
                    'icon': 'wand',
                    'order': 40,
                    'action': {'type': 'command', 'id': 'open-panel'},
                },
                {
                    'id': 'demo-context',
                    'placement': 'context.folder',
                    'type': 'submenu',
                    'label': '演示',
                    'icon': 'wand',
                    'children': [
                        {
                            'id': 'demo-about',
                            'type': 'item',
                            'label': '关于',
                            'action': {'type': 'url', 'url': 'https://example.com'},
                        },
                    ],
                },
            ],
            'slots': [
                {
                    'id': 'settings-inline',
                    'slot': 'settings.section',
                    'title': '演示',
                    'order': 80,
                    'module': 'frontend/views/settingsSection.js',
                    'export': 'mountSettingsSection',
                },
            ],
            'commands': [
                {
                    'id': 'open-panel',
                    'title': '打开演示面板',
                    'shortcut': 'Ctrl+Shift+D',
                    'module': 'frontend/commands.js',
                    'export': 'openPanel',
                },
            ],
        },
    },
    'capabilities': ['cards.read'],
    'config_schema': {
        'type': 'object',
        'properties': {
            'greeting': {'type': 'string', 'title': '问候语', 'default': '你好'},
        },
    },
    'secret_schema': {'type': 'object', 'properties': {}},
}

UI_FILES = {
    'backend/__init__.py': 'def register(api):\n    return None\n',
    'frontend/plugin.js': (
        'export async function activate(api) {\n'
        '  return () => {};\n'
        '}\n'
    ),
    'frontend/plugin.css': '.plugin-demo-plugin {\n  color: red;\n}\n',
    'frontend/commands.js': (
        'export async function openPanel(ctx) {\n'
        '  return null;\n'
        '}\n'
    ),
    'frontend/views/settingsSection.js': (
        'export function mountSettingsSection(container, ctx) {\n'
        '  return () => {};\n'
        '}\n'
    ),
}


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(content)


def make_plugin(
    root,
    *,
    plugin_id='demo-plugin',
    manifest=None,
    files=True,
    extra_files=None,
):
    """在 `root` 下写一个合法 v3 插件；manifest 传 None 时用基线。"""
    plugin_dir = os.path.join(str(root), plugin_id)
    os.makedirs(plugin_dir, exist_ok=True)
    payload = copy.deepcopy(manifest) if manifest is not None else copy.deepcopy(BASE_MANIFEST)
    payload['id'] = plugin_id
    _write_file(
        os.path.join(plugin_dir, 'manifest.json'),
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
    )
    if files:
        for relative, content in UI_FILES.items():
            _write_file(os.path.join(plugin_dir, relative), content)
    for relative, content in (extra_files or {}).items():
        _write_file(os.path.join(plugin_dir, relative), content)
    return plugin_dir


def _mutated(mutator):
    payload = copy.deepcopy(BASE_MANIFEST)
    mutator(payload)
    return payload


def _errors(result):
    return [item for item in result['issues'] if item['severity'] == 'error']


def _codes(result):
    return {item['code'] for item in result['issues']}


# ---------------------------------------------------------------- 正例


def test_valid_plugin_passes(tmp_path):
    plugin_dir = make_plugin(tmp_path)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True, result['issues']
    assert result['error_count'] == 0
    assert result['plugin_id'] == 'demo-plugin'
    assert result['contract_version'] == 3
    assert len(result['checks']) == len(CHECK_DEFINITIONS) == 9
    assert all(check['status'] != 'fail' for check in result['checks'])


def test_valid_plugin_cli_exits_zero(tmp_path, capsys):
    plugin_dir = make_plugin(tmp_path)

    assert check_main([plugin_dir]) == 0

    captured = capsys.readouterr()
    assert '通过' in captured.out
    assert 'demo-plugin' in captured.out


def test_json_output_is_machine_readable(tmp_path, capsys):
    plugin_dir = make_plugin(tmp_path)

    exit_code = check_main([plugin_dir, '--json'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is True
    assert payload['error_count'] == 0
    assert payload['contract_version'] == 3
    assert payload['plugin_id'] == 'demo-plugin'
    assert [check['id'] for check in payload['checks']] == list(range(1, 10))
    assert payload['issues'] == []


def test_unknown_host_icon_is_only_a_warning(tmp_path):
    payload = _mutated(
        lambda manifest: manifest['frontend']['contributions']['menus'][0].update(
            {'icon': 'definitely-not-an-icon'}
        )
    )
    plugin_dir = make_plugin(tmp_path, manifest=payload)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True
    assert 'icon_unknown' in _codes(result)
    assert result['warning_count'] >= 1


def test_known_host_icon_names_are_generated_from_sprites():
    assert 'wand' in HOST_ICON_NAMES
    assert 'plus' in HOST_ICON_NAMES  # 模板别名也算合法


# ---------------------------------------------------------------- 反例（必须非零退出）


def test_unknown_top_level_key_fails(tmp_path, capsys):
    payload = _mutated(lambda manifest: manifest.update({'permissions': ['cards.read']}))
    plugin_dir = make_plugin(tmp_path, manifest=payload)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'manifest_unknown_key' in _codes(result)
    assert check_main([plugin_dir]) == 1
    assert 'ERROR' in capsys.readouterr().out


def test_legacy_frontend_entries_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['entries'] = [
            {'id': 'legacy', 'kind': 'dock', 'label': '旧入口', 'action': {'type': 'command', 'id': 'x'}}
        ]

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'manifest_legacy_key' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_unknown_placement_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'][0]['placement'] = 'nav'

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'menu_placement_unknown' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_missing_command_reference_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'][0]['action'] = {
            'type': 'command', 'id': 'not-declared',
        }

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'action_command_missing' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_menu_depth_exceeded_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'] = [{
            'id': 'level-0',
            'placement': 'commandPalette',
            'type': 'submenu',
            'label': 'L0',
            'children': [{
                'id': 'level-1',
                'type': 'submenu',
                'label': 'L1',
                'children': [{
                    'id': 'level-2',
                    'type': 'submenu',
                    'label': 'L2',
                    'children': [{
                        'id': 'level-3',
                        'type': 'item',
                        'label': 'L3',
                        'action': {'type': 'url', 'url': 'https://example.com'},
                    }],
                }],
            }],
        }]

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'menu_depth_exceeded' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_menu_capacity_exceeded_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'] = [
            {
                'id': f'item-{index}',
                'placement': 'commandPalette',
                'type': 'item',
                'label': f'项 {index}',
                'action': {'type': 'url', 'url': 'https://example.com'},
            }
            for index in range(65)
        ]

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'menu_capacity' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_invalid_shortcut_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['commands'][0]['shortcut'] = 'D'

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'shortcut_invalid' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_global_styles_without_capability_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['global_styles'] = ['frontend/global.css']

    extra = {'frontend/global.css': 'html { color: red; }\n'}
    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator), extra_files=extra)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'global_styles_capability_missing' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_global_styles_with_capability_passes(tmp_path):
    def mutator(manifest):
        manifest['frontend']['global_styles'] = ['frontend/global.css']
        manifest['capabilities'] = ['cards.read', 'ui.global_styles']

    extra = {'frontend/global.css': 'html { color: red; }\n'}
    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator), extra_files=extra)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True, result['issues']


def test_css_out_of_scope_fails(tmp_path):
    plugin_dir = make_plugin(
        tmp_path,
        extra_files={'frontend/plugin.css': 'body {\n  color: red;\n}\n'},
    )

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'css_unscoped' in _codes(result)
    assert check_main([plugin_dir]) == 1


def test_missing_module_file_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['slots'][0]['module'] = 'frontend/views/missing.js'

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'module_missing' in _codes(result)


def test_missing_export_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['commands'][0]['export'] = 'notExported'

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'module_export_missing' in _codes(result)


def test_missing_icon_resource_fails(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'][0]['icon'] = 'frontend/assets/missing.svg'

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'icon_missing' in _codes(result)


def test_unsupported_api_version_fails(tmp_path):
    def mutator(manifest):
        manifest['api_version'] = 2

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'api_version_unsupported' in _codes(result)
    assert check_main([plugin_dir]) == 1


def _rewrite_manifest_id(plugin_dir, plugin_id):
    """把已生成夹具的 manifest.id 改成另一个合法 id（目录名保持不变）。"""
    path = os.path.join(plugin_dir, 'manifest.json')
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)
    payload['id'] = plugin_id
    _write_file(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')


def test_repo_dir_name_mismatch_is_warning(tmp_path):
    """插件仓库目录名是仓库名（如 ST-Manager-Pet），与 id 不同只应 warning。"""
    plugin_dir = make_plugin(tmp_path, plugin_id='ST-Manager-Demo')
    _rewrite_manifest_id(plugin_dir, 'demo-plugin')

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True
    mismatch = next(
        item for item in result['issues'] if item['code'] == 'manifest_id_dir_mismatch'
    )
    assert mismatch['severity'] == 'warning'
    assert mismatch['hint']
    assert check_main([plugin_dir]) == 0


def test_repo_dir_name_mismatch_warning_in_json(tmp_path, capsys):
    plugin_dir = make_plugin(tmp_path, plugin_id='ST-Manager-Demo')
    _rewrite_manifest_id(plugin_dir, 'demo-plugin')

    exit_code = check_main([plugin_dir, '--json'])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['ok'] is True
    mismatch = next(
        item for item in payload['issues'] if item['code'] == 'manifest_id_dir_mismatch'
    )
    assert mismatch['severity'] == 'warning'


def test_install_dir_name_mismatch_is_error(tmp_path):
    """宿主安装目录（.../plugins/<id>）下，目录名必须等于 manifest.id。"""
    install_root = tmp_path / 'plugins'
    plugin_dir = make_plugin(install_root, plugin_id='ST-Manager-Demo')
    _rewrite_manifest_id(plugin_dir, 'demo-plugin')

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    mismatch = next(
        item for item in result['issues'] if item['code'] == 'manifest_id_dir_mismatch'
    )
    assert mismatch['severity'] == 'error'
    assert check_main([plugin_dir]) == 1


def test_install_dir_matching_id_passes(tmp_path):
    plugin_dir = make_plugin(tmp_path / 'plugins')

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True
    assert 'manifest_id_dir_mismatch' not in _codes(result)


def test_missing_manifest_fails(tmp_path):
    plugin_dir = os.path.join(str(tmp_path), 'empty-plugin')
    os.makedirs(plugin_dir)

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    assert 'manifest_missing' in _codes(result)


def test_invalid_json_reports_line_number(tmp_path):
    plugin_dir = os.path.join(str(tmp_path), 'broken-plugin')
    os.makedirs(plugin_dir)
    _write_file(os.path.join(plugin_dir, 'manifest.json'), '{\n  "id": "broken-plugin",\n}')

    result = validate_plugin(plugin_dir)

    assert result['ok'] is False
    issue = next(item for item in result['issues'] if item['code'] == 'manifest_invalid_json')
    assert issue['line'] == 3


def test_dock_overflow_is_warning_not_error(tmp_path):
    def mutator(manifest):
        manifest['frontend']['contributions']['menus'] = [
            {
                'id': f'dock-{index}',
                'placement': 'dock',
                'type': 'item',
                'label': f'坞栏 {index}',
                'action': {'type': 'url', 'url': 'https://example.com'},
            }
            for index in range(3)
        ]

    plugin_dir = make_plugin(tmp_path, manifest=_mutated(mutator))

    result = validate_plugin(plugin_dir)

    assert result['ok'] is True
    assert 'dock_capacity' in _codes(result)


# ---------------------------------------------------------------- 独立运行 / 生成区同步


def test_checker_is_standalone_copyable_script(tmp_path):
    """复制到插件仓库后仍能运行：脚本不 import 宿主模块。"""
    source_path = os.path.join(PROJECT_ROOT, 'tools', 'stm_plugin_check.py')
    with open(source_path, 'r', encoding='utf-8') as handle:
        source = handle.read()

    assert 'from core' not in source
    assert 'import core' not in source

    copied = os.path.join(str(tmp_path), 'stm_plugin_check.py')
    shutil.copyfile(source_path, copied)
    plugin_dir = make_plugin(tmp_path / 'plugins')

    completed = subprocess.run(
        [sys.executable, copied, plugin_dir],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '通过' in completed.stdout


def test_checker_embedded_contract_is_in_sync():
    assert gen_plugin_api_docs.check_checker() is True


def test_checker_check_detects_stale_embedded_contract(tmp_path, monkeypatch):
    source_path = os.path.join(PROJECT_ROOT, 'tools', 'stm_plugin_check.py')
    with open(source_path, 'r', encoding='utf-8') as handle:
        source = handle.read()

    tampered = source.replace(
        gen_plugin_api_docs.CHECKER_CONTRACT_BEGIN + '\n',
        gen_plugin_api_docs.CHECKER_CONTRACT_BEGIN + '\n# stale marker\n',
        1,
    )
    target = tmp_path / 'stm_plugin_check.py'
    target.write_text(tampered, encoding='utf-8')
    monkeypatch.setattr(gen_plugin_api_docs, 'CHECKER_PATH', str(target))

    assert gen_plugin_api_docs.check_checker() is False
