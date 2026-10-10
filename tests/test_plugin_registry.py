"""插件发现、加载与失败隔离测试（设计文档 4.2–4.5 / 13.1）。"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import registry as registry_module
from tests.plugins_test_support import base_manifest, clear_plugin_ui_namespace, write_plugin


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


def _patch_plugins_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))


def test_load_all_registers_routes_and_state(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')

    summary = registry_module.load_all(app)

    assert summary['loaded'] == ['demo-plugin']
    assert summary['failed'] == []

    state = registry_module.get_state('demo-plugin')
    assert state is not None
    assert state.loaded is True
    assert state.enabled is True
    assert state.manifest.version == '0.1.0'
    assert registry_module.get_api('demo-plugin') is state.api
    assert any(rule.rule.endswith('/ping') for rule in app.url_map.iter_rules())


def test_disabled_plugin_is_not_loaded(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(registry_module, '_read_enabled_map', lambda: {'demo-plugin': False})
    app = Flask('registry-test')

    summary = registry_module.load_all(app)

    assert summary['disabled'] == ['demo-plugin']
    assert summary['loaded'] == []

    state = registry_module.get_state('demo-plugin')
    assert state.enabled is False
    assert state.loaded is False
    assert state.api is None
    assert not any('plugins' in rule.rule for rule in app.url_map.iter_rules())


def test_frontend_only_plugin_is_marked_loaded_without_backend(tmp_path, monkeypatch):
    write_plugin(
        tmp_path, 'demo-plugin',
        manifest=base_manifest('demo-plugin', backend={}),
        backend=None,
    )
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')

    registry_module.load_all(app)

    state = registry_module.get_state('demo-plugin')
    assert state.loaded is True
    assert state.has_backend is False
    assert state.has_frontend is True


# --- 入口契约在注册表侧的暴露（阶段 1） ------------------------------------


def _entries_manifest(plugin_id, entries):
    manifest = base_manifest(plugin_id)
    manifest['manifest_version'] = 2
    manifest['frontend']['entries'] = entries
    return manifest


def test_header_exposes_entries(tmp_path, monkeypatch):
    write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_entries_manifest('demo-plugin', [
            {'id': 'open-demo', 'kind': 'dock', 'label': '打开演示', 'icon': 'wand'},
        ]),
    )
    _patch_plugins_dir(monkeypatch, tmp_path)

    registry_module.load_all(Flask('registry-test'))

    header = registry_module.get_state('demo-plugin').header
    assert [item['key'] for item in header['entries']] == ['demo-plugin:open-demo']
    assert header['api_version'] == 1
    assert header['manifest_version'] == 2
    # detail() 也应带出，前端 /api/plugins/list 直接消费
    assert registry_module.get_state('demo-plugin').detail()['entries'][0]['label'] == '打开演示'


def test_entries_have_no_tier_until_catalog_resolves_it(tmp_path, monkeypatch):
    """D5：tier 由 catalog 决定；不在 catalog 中即 community。"""
    write_plugin(
        tmp_path, 'demo-plugin',
        manifest=_entries_manifest('demo-plugin', [
            {'id': 'badge', 'kind': 'status', 'label': '状态徽标'},
            {'id': 'open', 'kind': 'command', 'label': '打开'},
        ]),
    )
    _patch_plugins_dir(monkeypatch, tmp_path)

    registry_module.load_all(Flask('registry-test'))

    state = registry_module.get_state('demo-plugin')
    # community 插件不得声明 status，该项被忽略并记 warning
    assert [item['id'] for item in state.manifest.frontend_entries] == ['open']
    assert all(item['tier'] == 'community' for item in state.manifest.frontend_entries)
    assert any('status' in item for item in state.warnings)


def test_structured_load_error_is_persisted(tmp_path, monkeypatch):
    manifest = base_manifest('demo-plugin')
    manifest['frontend']['entrys'] = 'frontend/plugin.js'
    write_plugin(tmp_path, 'demo-plugin', manifest=manifest)
    _patch_plugins_dir(monkeypatch, tmp_path)

    registry_module.load_all(Flask('registry-test'))

    state = registry_module.get_state('demo-plugin')
    assert state.loaded is False
    assert 'manifest 校验失败' in state.load_error
    detail = state.load_error_detail
    assert detail['code'] == 'manifest_unknown_key'
    assert detail['field'] == 'frontend.entrys'
    assert detail['hint']
    assert detail['user_msg']

    persisted = registry_module.read_ui_entry('demo-plugin')
    assert persisted['load_error'] == state.load_error
    assert persisted['load_error_detail']['field'] == 'frontend.entrys'


def test_api_version_error_carries_structured_detail(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin', manifest=base_manifest('demo-plugin', api_version=99))
    _patch_plugins_dir(monkeypatch, tmp_path)

    registry_module.load_all(Flask('registry-test'))

    detail = registry_module.get_state('demo-plugin').load_error_detail
    assert detail['code'] == 'api_version_unsupported'
    assert detail['field'] == 'api_version'
    assert '升级主程序' in detail['user_msg']


def test_manifest_error_is_recorded_as_load_error(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin', manifest={'id': 'demo-plugin'})
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')

    summary = registry_module.load_all(app)

    assert summary['failed'] == ['demo-plugin']
    state = registry_module.get_state('demo-plugin')
    assert state.loaded is False
    assert 'manifest' in state.load_error


def test_backend_exception_does_not_break_other_plugins(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'good-plugin')
    write_plugin(tmp_path, 'bad-plugin', backend='raise RuntimeError("bad plugin")\n')
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')

    summary = registry_module.load_all(app)

    assert summary['loaded'] == ['good-plugin']
    assert summary['failed'] == ['bad-plugin']
    assert registry_module.get_state('bad-plugin').load_error
    assert any(rule.rule.endswith('/ping') for rule in app.url_map.iter_rules())


def test_route_conflict_does_not_override_core_route(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)

    app = Flask('registry-test')

    @app.route('/api/plugins/demo-plugin/ping')
    def core_ping():
        return 'core'

    registry_module.load_all(app)

    client = app.test_client()
    response = client.get('/api/plugins/demo-plugin/ping')
    assert response.get_data(as_text=True) == 'core'


def test_discover_ignores_invalid_directory_names(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'valid-plugin')
    invalid_dir = os.path.join(str(tmp_path), 'Invalid_Name')
    os.makedirs(invalid_dir, exist_ok=True)

    _patch_plugins_dir(monkeypatch, tmp_path)

    discovered = [os.path.basename(path) for path in registry_module.discover_plugin_dirs()]

    assert discovered == ['valid-plugin']


def test_enabled_flag_is_read_once_from_ui_data(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    registry_module.set_enabled('demo-plugin', False)

    app = Flask('registry-test')
    summary = registry_module.load_all(app)

    assert summary['disabled'] == ['demo-plugin']


def test_set_enabled_setting_updates_runtime_state(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')
    registry_module.load_all(app)

    registry_module.set_enabled_setting('demo-plugin', False)

    assert registry_module.get_state('demo-plugin').enabled is False
    assert registry_module.read_ui_entry('demo-plugin')['enabled'] is False


def test_drop_state_removes_hook_subscriptions(tmp_path, monkeypatch):
    from core.plugins import hooks

    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')
    registry_module.load_all(app)

    api = registry_module.get_api('demo-plugin')
    api.on('card.updated', lambda payload: None)
    assert hooks.subscriber_count('card.updated') == 1

    registry_module.drop_state('demo-plugin')

    assert registry_module.get_state('demo-plugin') is None
    assert hooks.subscriber_count('card.updated') == 0


def test_restart_required_persisted_in_list_header(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'demo-plugin')
    _patch_plugins_dir(monkeypatch, tmp_path)
    app = Flask('registry-test')
    registry_module.load_all(app)

    registry_module.set_restart_required('demo-plugin', True)

    assert registry_module.get_state('demo-plugin').header['restart_required'] is True
    assert registry_module.read_ui_entry('demo-plugin')['restart_required'] is True
