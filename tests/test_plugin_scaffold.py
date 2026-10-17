"""插件脚手架测试（tools/new_plugin.py）。"""

import json
import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import registry as registry_module
from core.plugins.installer import scan_css_scope
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace
from tools.new_plugin import main as scaffold_main
from tools.new_plugin import scaffold_plugin, validate_plugin_id


@pytest.fixture(autouse=True)
def _isolate_registry():
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    yield
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    for name in list(sys.modules):
        if name.startswith(registry_module.MODULE_PREFIX):
            sys.modules.pop(name, None)


def test_scaffold_generates_expected_files(tmp_path):
    target = scaffold_plugin('scaffold-demo', name='脚手架示例', out_dir=str(tmp_path))

    assert os.path.isdir(target)
    for relative in (
        'manifest.json',
        'README.md',
        'backend/__init__.py',
        'frontend/plugin.js',
        'frontend/plugin.css',
    ):
        assert os.path.isfile(os.path.join(target, relative)), relative


def test_generated_manifest_passes_validation(tmp_path):
    target = scaffold_plugin('scaffold-demo', name='脚手架示例', out_dir=str(tmp_path))

    manifest = PluginManifest.load(target)

    assert manifest.plugin_id == 'scaffold-demo'
    assert manifest.name == '脚手架示例'
    assert manifest.version == '0.1.0'
    assert manifest.api_version == 1
    assert manifest.has_backend and manifest.has_frontend
    assert manifest.warnings == []


def test_generated_css_passes_scope_check(tmp_path):
    target = scaffold_plugin('scaffold-demo', out_dir=str(tmp_path))

    violations = scan_css_scope(os.path.join(target, 'frontend', 'plugin.css'), 'scaffold-demo')

    assert violations == []


def test_generated_backend_uses_domain_namespaces(tmp_path):
    """脚手架必须产出**域命名空间**写法，旧扁平名会误导插件作者。"""
    target = scaffold_plugin('scaffold-demo', out_dir=str(tmp_path))

    source = open(os.path.join(target, 'backend', '__init__.py'), encoding='utf-8').read()

    assert 'import backend' not in source
    assert '@api.http.route' in source
    assert 'api.config.get()' in source
    assert 'api.log.info(' in source

    # 旧扁平名不应该再出现在脚手架里
    for legacy in ('@api.route', 'api.get_config(', "api.log('", 'api.set_secret('):
        assert legacy not in source, legacy


def test_generated_plugin_loads_and_serves_route(tmp_path, monkeypatch):
    plugins_root = tmp_path / 'plugins'
    scaffold_plugin('scaffold-demo', name='脚手架示例', out_dir=str(plugins_root))
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(plugins_root))

    app = Flask('scaffold-test')
    summary = registry_module.load_all(app)

    assert summary['loaded'] == ['scaffold-demo']

    client = app.test_client()
    response = client.get('/api/plugins/scaffold-demo/ping')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['plugin'] == 'scaffold-demo'
    assert payload['greeting'] == '你好'


def test_scaffold_supports_frontend_only_plugin(tmp_path):
    target = scaffold_plugin('frontend-only-demo', out_dir=str(tmp_path), with_backend=False)

    manifest = PluginManifest.load(target)

    assert manifest.is_frontend_only is True
    assert not os.path.exists(os.path.join(target, 'backend'))
    assert os.path.isfile(os.path.join(target, 'frontend', 'plugin.js'))


def test_scaffold_supports_backend_only_plugin(tmp_path):
    target = scaffold_plugin('backend-only-demo', out_dir=str(tmp_path), with_frontend=False)

    manifest = PluginManifest.load(target)

    assert manifest.has_backend is True
    assert manifest.has_frontend is False
    assert not os.path.exists(os.path.join(target, 'frontend'))


def test_scaffold_requires_force_when_directory_exists(tmp_path):
    scaffold_plugin('scaffold-demo', out_dir=str(tmp_path))

    with pytest.raises(FileExistsError):
        scaffold_plugin('scaffold-demo', out_dir=str(tmp_path))

    # --force 允许覆盖
    target = scaffold_plugin('scaffold-demo', out_dir=str(tmp_path), force=True)
    assert os.path.isfile(os.path.join(target, 'manifest.json'))


@pytest.mark.parametrize('plugin_id', ['Demo_Plugin', 'demo plugin', '1demo', '', 'a', '../evil'])
def test_scaffold_rejects_invalid_plugin_ids(tmp_path, plugin_id):
    with pytest.raises(ValueError):
        validate_plugin_id(plugin_id)

    with pytest.raises((ValueError, FileExistsError)):
        scaffold_plugin(plugin_id, out_dir=str(tmp_path))


def test_scaffold_version_and_name_are_applied(tmp_path):
    target = scaffold_plugin('version-demo', name='版本演示', version='2.3.4', out_dir=str(tmp_path))

    payload = json.loads(open(os.path.join(target, 'manifest.json'), encoding='utf-8').read())

    assert payload['name'] == '版本演示'
    assert payload['version'] == '2.3.4'

    # 版本号非法时 load 会拒绝，这里顺带确认脚手架没有写出非法版本
    assert PluginManifest.load(target).version == '2.3.4'


def test_cli_main_returns_zero_and_prints_path(tmp_path, capsys):
    exit_code = scaffold_main(['cli-demo', '--name', 'CLI 示例', '--out', str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert '已生成插件骨架' in captured.out
    assert os.path.isfile(os.path.join(str(tmp_path), 'cli-demo', 'manifest.json'))


def test_cli_main_returns_nonzero_for_invalid_id(tmp_path, capsys):
    exit_code = scaffold_main(['Bad_Id', '--out', str(tmp_path)])

    assert exit_code == 1
    assert '❌' in capsys.readouterr().out


def test_cli_main_rejects_disabling_both_sides(tmp_path):
    exit_code = scaffold_main(['both-demo', '--out', str(tmp_path), '--no-backend', '--no-frontend'])

    assert exit_code == 2
