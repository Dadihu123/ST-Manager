"""插件管理 API 契约测试（设计文档 10.4 / 13.1）。"""

import json
import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import catalog as catalog_module
from core.plugins import installer as installer_module
from core.plugins import job_store as job_store_module
from core.plugins import registry as registry_module
from core.plugins import routes as routes_module
from core.plugins import secrets as secrets_module
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    clear_plugin_ui_namespace()
    yield
    clear_plugin_ui_namespace()


@pytest.fixture
def client(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    state = registry_module.PluginState('demo-plugin', plugin_dir)
    state.manifest = PluginManifest.load(plugin_dir)
    state.loaded = True

    monkeypatch.setattr(registry_module, '_states', {'demo-plugin': state})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    monkeypatch.setattr(installer_module, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(job_store_module, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))
    secrets_module._clear_degraded()

    app = Flask('plugin-routes-test')
    app.register_blueprint(routes_module.bp)
    yield app.test_client()
    secrets_module._clear_degraded()


def test_list_returns_manifest_and_flags(client):
    data = client.get('/api/plugins/list').get_json()

    assert data['success'] is True
    item = data['items'][0]
    assert item['id'] == 'demo-plugin'
    assert item['loaded'] is True
    assert item['enabled'] is True
    assert item['manifest']['config_schema']
    assert 'style_scope_errors' in item
    assert data['plugins_dir']


def test_config_get_and_post_roundtrip(client):
    first = client.get('/api/plugins/demo-plugin/config').get_json()
    assert first['success'] is True
    assert first['config']['greeting'] == 'hi'

    saved = client.post('/api/plugins/demo-plugin/config', json={'config': {'greeting': '你好'}}).get_json()
    assert saved['success'] is True
    assert saved['config']['greeting'] == '你好'

    again = client.get('/api/plugins/demo-plugin/config').get_json()
    assert again['config']['greeting'] == '你好'


def test_config_rejects_empty_payload(client):
    response = client.post('/api/plugins/demo-plugin/config', json={'config': {}})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_secrets_never_return_plaintext(client):
    client.post('/api/plugins/demo-plugin/secrets', json={'secrets': {'api_key': 'sk-1234567890abcdef'}})

    data = client.get('/api/plugins/demo-plugin/secrets').get_json()

    entry = data['secrets']['api_key']
    assert entry['set'] is True
    assert 'value' not in entry
    assert entry['hint'] == 'sk-…cdef'
    assert 'sk-1234567890abcdef' not in json.dumps(data, ensure_ascii=False)


def test_secret_write_and_delete(client):
    client.post('/api/plugins/demo-plugin/secrets', json={'secrets': {'api_key': 'sk-aaaa1111bbbb'}})

    deleted = client.delete('/api/plugins/demo-plugin/secrets/api_key').get_json()
    assert deleted['success'] is True

    data = client.get('/api/plugins/demo-plugin/secrets').get_json()
    assert data['secrets']['api_key']['set'] is False


def test_secret_write_returns_503_when_degraded(client, monkeypatch):
    monkeypatch.setattr(secrets_module, 'is_degraded', lambda: True)

    response = client.post('/api/plugins/demo-plugin/secrets', json={'secrets': {'api_key': 'x'}})

    assert response.status_code == 503
    assert response.get_json()['error'] == 'secret_read_failed'


def test_disable_and_enable_require_restart(client):
    disabled = client.post('/api/plugins/demo-plugin/disable').get_json()

    assert disabled['success'] is True
    assert disabled['restart_required'] is True
    assert registry_module.read_ui_entry('demo-plugin')['enabled'] is False

    enabled = client.post('/api/plugins/demo-plugin/enable').get_json()
    assert enabled['success'] is True
    assert enabled['restart_required'] is True
    assert registry_module.read_ui_entry('demo-plugin')['enabled'] is True


def test_unknown_plugin_returns_structured_error(client):
    response = client.get('/api/plugins/unknown-plugin/config')

    assert response.status_code == 404
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['error'] == 'plugin_not_found'


def test_uninstall_moves_plugin_to_trash(client, tmp_path):
    response = client.post('/api/plugins/uninstall', json={'id': 'demo-plugin'})

    payload = response.get_json()
    assert payload['success'] is True
    assert payload['restart_required'] is True
    assert not os.path.isdir(str(tmp_path / 'demo-plugin'))
    assert os.path.isdir(str(tmp_path / 'trash'))
    assert registry_module.get_state('demo-plugin') is None


def test_uninstall_keep_data_preserves_ui_entry(client, monkeypatch):
    def mutator(ui_data):
        namespace = ui_data.setdefault('_plugins_v1', {})
        namespace.setdefault('demo-plugin', {})['config'] = {'greeting': 'kept'}

    from core.data.ui_store import update_ui_data

    update_ui_data(mutator)

    client.post('/api/plugins/uninstall', json={'id': 'demo-plugin', 'keep_data': True})

    assert registry_module.read_ui_entry('demo-plugin').get('config') == {'greeting': 'kept'}


def test_install_upload_requires_file(client):
    response = client.post('/api/plugins/install_upload', data={})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_catalog_endpoint_marks_installed(client, monkeypatch):
    monkeypatch.setattr(catalog_module, 'get_catalog', lambda refresh=False: {
        'success': True,
        'items': [{'id': 'demo-plugin', 'name': 'Demo', 'source': {'repo': 'owner/repo'}}],
        'source': 'bundled',
        'offline': False,
        'updated_at': '',
        'msg': '',
    })

    data = client.get('/api/plugins/catalog').get_json()

    assert data['success'] is True
    assert data['items'][0]['installed'] is True
    assert data['items'][0]['installed_version'] == '0.1.0'


def test_catalog_install_delegates_to_installer(client, monkeypatch):
    monkeypatch.setattr(
        catalog_module, 'find_catalog_entry',
        lambda plugin_id: {'id': plugin_id, 'source': {'repo': 'owner/repo'}},
    )

    captured = {}

    def fake_install(app, entry, *, ref='', subdir=''):
        captured['entry'] = entry
        return {'id': 'demo-plugin', 'version': '0.2.0'}

    monkeypatch.setattr(installer_module, 'install_from_catalog', fake_install)

    data = client.post('/api/plugins/catalog/install', json={'id': 'demo-plugin'}).get_json()

    assert data['success'] is True
    assert data['restart_required'] is True
    assert captured['entry']['id'] == 'demo-plugin'


def test_check_updates_endpoint(client, monkeypatch):
    monkeypatch.setattr(catalog_module, 'check_updates', lambda force=False: {
        'updates': [{'id': 'demo-plugin', 'installed': '0.1.0', 'available': '0.2.0'}],
        'source': 'remote',
        'msg': '',
    })

    data = client.post('/api/plugins/catalog/check_updates', json={}).get_json()

    assert data['success'] is True
    assert data['updates'][0]['available'] == '0.2.0'


def test_job_endpoints_require_known_plugin(client):
    assert client.get('/api/plugins/unknown-plugin/jobs').status_code == 404
    assert client.get('/api/plugins/demo-plugin/jobs').get_json()['success'] is True


def test_readme_endpoint_returns_readme_and_changelog(client, tmp_path):
    plugin_dir = tmp_path / 'demo-plugin'
    (plugin_dir / 'README.md').write_text('# 示例插件\n\n使用说明', encoding='utf-8')
    (plugin_dir / 'CHANGELOG.md').write_text('## 0.1.0\n\n- 初版', encoding='utf-8')

    data = client.get('/api/plugins/demo-plugin/readme').get_json()

    assert data['success'] is True
    assert data['readme']['found'] is True
    assert data['readme']['name'] == 'README.md'
    assert '# 示例插件' in data['readme']['content']
    assert data['changelog']['found'] is True
    assert '初版' in data['changelog']['content']


def test_readme_endpoint_reports_missing_documents(client):
    data = client.get('/api/plugins/demo-plugin/readme').get_json()

    assert data['readme']['found'] is False
    assert data['changelog']['found'] is False
    assert data['readme']['content'] == ''


def test_readme_endpoint_truncates_oversized_documents(client, tmp_path, monkeypatch):
    from core.plugins import routes as routes_module

    monkeypatch.setattr(routes_module, 'MAX_DOCUMENT_BYTES', 32)
    plugin_dir = tmp_path / 'demo-plugin'
    (plugin_dir / 'README.md').write_text('x' * 1024, encoding='utf-8')

    data = client.get('/api/plugins/demo-plugin/readme').get_json()

    assert data['readme']['found'] is True
    assert data['readme']['truncated'] is True
    assert data['readme']['content'] == ''


def test_readme_endpoint_requires_known_plugin(client):
    assert client.get('/api/plugins/unknown-plugin/readme').status_code == 404


def test_management_api_responses_are_not_cached(client):
    """管理接口响应含配置与密钥掩码，必须显式禁止缓存。

    全局安全头（nosniff 等）由 `create_app` 的 after_request 统一注入，
    见 tests/test_security_headers.py 的端到端用例。
    """
    for path in (
        '/api/plugins/list',
        '/api/plugins/demo-plugin/config',
        '/api/plugins/demo-plugin/secrets',
        '/api/plugins/catalog',
    ):
        response = client.get(path)
        assert response.headers['Cache-Control'] == 'no-store', path


def test_readme_endpoint_ignores_symlink_escape(client, tmp_path):
    outside = tmp_path / 'outside.md'
    outside.write_text('secret', encoding='utf-8')
    plugin_dir = tmp_path / 'demo-plugin'
    link = plugin_dir / 'README.md'

    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError):
        pytest.skip('当前环境不支持符号链接')

    data = client.get('/api/plugins/demo-plugin/readme').get_json()

    assert data['readme']['found'] is False


def test_job_detail_requires_existing_run(client):
    response = client.get('/api/plugins/demo-plugin/jobs/not-a-run-id')

    assert response.status_code == 404
    assert response.get_json()['error'] == 'job_not_found'
