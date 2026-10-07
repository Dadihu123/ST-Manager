"""一个坏插件不得阻止应用启动（设计文档 13.3 回归保护）。"""

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


def test_broken_plugins_do_not_block_load_all(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'good-plugin')
    write_plugin(tmp_path, 'broken-manifest', manifest={'id': 'broken-manifest'})
    write_plugin(tmp_path, 'broken-backend', backend='raise RuntimeError("boom")\n')
    write_plugin(
        tmp_path, 'broken-api-version',
        manifest=base_manifest('broken-api-version', api_version=99),
    )
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    app = Flask('isolation-test')

    summary = registry_module.load_all(app)

    assert summary['loaded'] == ['good-plugin']
    assert sorted(summary['failed']) == ['broken-api-version', 'broken-backend', 'broken-manifest']


def test_broken_plugin_does_not_break_create_app(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'good-plugin')
    write_plugin(tmp_path, 'broken-backend', backend='raise RuntimeError("boom")\n')
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    import core

    app = core.create_app()

    assert app is not None
    assert registry_module.get_state('good-plugin').loaded is True
    assert registry_module.get_state('broken-backend').loaded is False

    client = app.test_client()
    assert client.get('/api/plugins/good-plugin/ping').status_code == 200
    assert client.get('/api/plugins/broken-backend/ping').status_code == 404


def test_load_error_is_persisted_to_ui_data(tmp_path, monkeypatch):
    write_plugin(tmp_path, 'broken-backend', backend='raise RuntimeError("persisted error")\n')
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    registry_module.load_all(Flask('isolation-test'))

    entry = registry_module.read_ui_entry('broken-backend')
    assert entry.get('load_error')


def test_successful_load_clears_previous_load_error(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', backend='raise RuntimeError("first")\n')
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))
    registry_module.load_all(Flask('isolation-test'))
    assert registry_module.read_ui_entry('demo-plugin').get('load_error')

    with open(os.path.join(plugin_dir, 'backend', '__init__.py'), 'w', encoding='utf-8') as handle:
        handle.write('def register(api):\n    return None\n')

    registry_module.load_all(Flask('isolation-test'))

    assert registry_module.read_ui_entry('demo-plugin').get('load_error', '') == ''
