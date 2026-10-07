"""插件静态资源路由测试（设计文档 8.5 / 13.1）。"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import assets as assets_module
from core.plugins import registry as registry_module
from tests.plugins_test_support import write_plugin


@pytest.fixture
def asset_app(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    with open(os.path.join(plugin_dir, 'frontend', 'secret.env'), 'w', encoding='utf-8') as handle:
        handle.write('TOKEN=1\n')
    with open(os.path.join(plugin_dir, 'backend', '__init__.py'), 'a', encoding='utf-8') as handle:
        handle.write('\n')

    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))
    monkeypatch.setattr(registry_module, '_states', {'demo-plugin': _state(plugin_dir)})

    app = Flask('plugin-assets-test')
    app.register_blueprint(assets_module.bp)
    return app


def _state(plugin_dir):
    state = registry_module.PluginState('demo-plugin', plugin_dir)
    return state


def test_serves_allowlisted_asset(asset_app):
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/plugin.js')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-cache'
    assert 'activate' in response.get_data(as_text=True)


def test_asset_response_carries_security_headers(asset_app):
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/plugin.js')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert "default-src 'none'" in response.headers['Content-Security-Policy']
    assert 'sandbox' in response.headers['Content-Security-Policy']
    assert response.headers['Cross-Origin-Resource-Policy'] == 'same-origin'


def test_rejects_disallowed_extension(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/backend/__init__.py').status_code == 404
    assert client.get('/api/plugins/demo-plugin/assets/frontend/secret.env').status_code == 404


def test_rejects_path_traversal(asset_app, tmp_path):
    outside = tmp_path.parent / 'outside.js'
    outside.write_text('window.pwned = true;', encoding='utf-8')
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/../../outside.js').status_code in (404, 308)
    assert client.get('/api/plugins/demo-plugin/assets/..%2f..%2foutside.js').status_code == 404


def test_rejects_invalid_plugin_id(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/Demo_Plugin/assets/frontend/plugin.js').status_code == 404


def test_unknown_plugin_returns_404(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/unknown-plugin/assets/frontend/plugin.js').status_code == 404


def test_missing_file_returns_404(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/frontend/missing.js').status_code == 404


def test_json_asset_is_served_with_json_mime(asset_app, tmp_path):
    with open(tmp_path / 'demo-plugin' / 'frontend' / 'manifest-snapshot.json', 'w', encoding='utf-8') as handle:
        handle.write('{"a": 1}')
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/manifest-snapshot.json')

    assert response.status_code == 200
    assert response.mimetype == 'application/json'
