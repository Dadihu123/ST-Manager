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
    # 安装来源（D9）：解析后的外链 + 结构化记录，前端「来源」按钮据此渲染。
    # 夹具既没有安装记录也没有 homepage，因此这里是空值（详见
    # tests/test_plugin_install_source.py 的各条优先级用例）。
    assert item['source_url'] == ''
    assert item['install_source'] == {}


def test_install_github_marks_source_kind_and_keeps_the_repo(client, monkeypatch):
    """`/api/plugins/install_github` 走同一安装路径，但来源分类是 `github`。

    这条路径此前**丢弃**了用户填的仓库地址（只把它塞进合成的 catalog 条目），
    已安装卡片因此拿不到任何来源链接。
    """
    captured = {}

    def fake_install(app, entry, *, ref='', subdir='', kind='catalog'):
        captured['entry'] = entry
        captured['kind'] = kind
        return {'id': 'demo-plugin', 'version': '0.2.0'}

    monkeypatch.setattr(installer_module, 'install_from_catalog', fake_install)

    data = client.post(
        '/api/plugins/install_github',
        json={'repo': 'https://github.com/owner/repo', 'ref': 'main'},
    ).get_json()

    assert data['success'] is True
    assert captured['entry']['source']['repo'] == 'owner/repo'
    assert captured['kind'] == 'github'


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


# ---------------------------------------------------------------- 存储（D8）


def test_storage_roundtrip(client):
    """`api.storage.*` 的持久化后端：写入 → 读回 → 删除。"""
    first = client.get('/api/plugins/demo-plugin/storage').get_json()
    assert first['success'] is True
    assert first['storage'] == {}

    saved = client.post(
        '/api/plugins/demo-plugin/storage',
        json={'storage': {'last_tab': 'prompts', 'count': 3}},
    ).get_json()
    assert saved['success'] is True
    assert saved['storage'] == {'last_tab': 'prompts', 'count': 3}

    again = client.get('/api/plugins/demo-plugin/storage').get_json()
    assert again['storage'] == {'last_tab': 'prompts', 'count': 3}

    # 整体替换语义：提交空对象即清空
    cleared = client.post('/api/plugins/demo-plugin/storage', json={'storage': {}}).get_json()
    assert cleared['storage'] == {}


def test_storage_is_isolated_per_plugin(client, monkeypatch, tmp_path):
    """存储落在各自的 `_plugins_v1.<id>` 命名空间，不串味。"""
    from core.plugins import registry as registry_module

    other_dir = write_plugin(tmp_path, 'other-plugin')
    other_state = registry_module.PluginState('other-plugin', other_dir)
    other_state.manifest = PluginManifest.load(other_dir)
    other_state.loaded = True

    states = dict(registry_module._states)
    states['other-plugin'] = other_state
    monkeypatch.setattr(registry_module, '_states', states)

    client.post('/api/plugins/demo-plugin/storage', json={'storage': {'owner': 'demo'}})
    client.post('/api/plugins/other-plugin/storage', json={'storage': {'owner': 'other'}})

    assert client.get('/api/plugins/demo-plugin/storage').get_json()['storage'] == {'owner': 'demo'}
    assert client.get('/api/plugins/other-plugin/storage').get_json()['storage'] == {'owner': 'other'}


def test_storage_rejects_non_object_payload(client):
    response = client.post('/api/plugins/demo-plugin/storage', json={'storage': [1, 2, 3]})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_storage_enforces_quota(client):
    """超过 256KB 上限时拒绝写入（与 `api.ui_data_update` 同一配额）。"""
    from core.plugins.api import PLUGIN_DATA_QUOTA_BYTES

    oversized = {'blob': 'x' * (PLUGIN_DATA_QUOTA_BYTES + 1024)}
    response = client.post('/api/plugins/demo-plugin/storage', json={'storage': oversized})

    assert response.status_code == 413
    assert response.get_json()['error'] == 'quota_exceeded'
    # 被拒绝后磁盘内容不变
    assert client.get('/api/plugins/demo-plugin/storage').get_json()['storage'] == {}


def test_storage_requires_known_plugin(client):
    response = client.get('/api/plugins/nope-plugin/storage')

    assert response.status_code == 404


# ---------------------------------------------------------------- 图标与令牌


def test_ui_icons_endpoint_exports_host_icon_catalog(client):
    """D4.2：图标名清单导出，供插件作者与设置页查询。"""
    data = client.get('/api/plugins/ui-icons').get_json()

    assert data['success'] is True
    icons = data['icons']
    assert len(icons) >= 100

    names = {item['name'] for item in icons}
    assert 'wand' in names or 'bolt' in names
    for item in icons:
        assert set(item) >= {'name', 'sprite', 'category', 'keywords'}
        assert item['sprite'].endswith('.svg')


def test_ui_tokens_endpoint_exports_host_css_tokens(client):
    """D12：宿主 CSS 令牌清单导出（插件样式检查依据）。"""
    data = client.get('/api/plugins/ui-tokens').get_json()

    assert data['success'] is True
    tokens = data['tokens']
    assert tokens == sorted(tokens)
    assert '--content-primary' in tokens
    assert '--surface-container' in tokens


# ---------------------------------------------------------------- 入口布局


def test_entry_layout_defaults_to_empty(client):
    data = client.get('/api/plugins/entries/layout').get_json()

    assert data['success'] is True
    assert data['layout'] == {}


def test_entry_layout_saves_and_merges(client):
    first = client.post(
        '/api/plugins/entries/layout',
        json={'layout': {'pinned': ['demo-plugin:a']}},
    ).get_json()
    assert first['success'] is True
    assert first['layout']['pinned'] == ['demo-plugin:a']

    # 合并语义：第二次提交不清掉第一次的键
    second = client.post(
        '/api/plugins/entries/layout',
        json={'layout': {'hidden': ['demo-plugin:b']}},
    ).get_json()
    assert second['layout']['pinned'] == ['demo-plugin:a']
    assert second['layout']['hidden'] == ['demo-plugin:b']

    assert client.get('/api/plugins/entries/layout').get_json()['layout'] == second['layout']


def test_entry_layout_ignores_unknown_keys(client):
    """只接受已知键，避免畸形前端把任意数据写进 ui_data。"""
    saved = client.post(
        '/api/plugins/entries/layout',
        json={'layout': {'pinned': ['x'], 'evil_key': 'boom'}},
    ).get_json()

    assert saved['layout'] == {'pinned': ['x']}
    assert 'evil_key' not in saved['layout']


def test_entry_layout_rejects_empty_payload(client):
    response = client.post('/api/plugins/entries/layout', json={'layout': {}})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_entry_layout_rejects_oversized_field(client):
    from core.plugins.routes import MAX_ENTRY_LAYOUT_BYTES

    response = client.post(
        '/api/plugins/entries/layout',
        json={'layout': {'order': ['k' * (MAX_ENTRY_LAYOUT_BYTES + 1)]}},
    )

    assert response.status_code == 400


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


def test_catalog_update_requires_installed_plugin(client, monkeypatch):
    """更新端点只服务**已安装**插件。

    否则它会变成「安装任意 catalog 条目」的后门——那是 `/catalog/install`
    的职责（有独立的确认流程）。
    """
    monkeypatch.setattr(registry_module, 'get_state', lambda plugin_id: None)

    response = client.post('/api/plugins/catalog/update', json={'id': 'not-installed'})

    assert response.status_code == 404
    data = response.get_json()
    assert data['success'] is False
    assert data['error'] == 'plugin_not_installed'


def test_catalog_update_requires_id(client):
    response = client.post('/api/plugins/catalog/update', json={})

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_payload'


def test_catalog_update_delegates_to_installer_and_reports_version_jump(client, monkeypatch):
    """更新 = 覆盖安装（原子替换），并回报 `v旧 → v新` 供前端提示。"""
    state = registry_module.PluginState('demo-plugin', '/tmp/demo-plugin')
    state.manifest = type('M', (), {'version': '0.1.0', 'name': 'Demo'})()
    monkeypatch.setattr(registry_module, 'get_state', lambda plugin_id: state)
    monkeypatch.setattr(
        catalog_module, 'find_catalog_entry',
        lambda plugin_id: {'id': plugin_id, 'source': {'repo': 'owner/repo'}},
    )

    captured = {}

    def fake_install(app, entry, *, ref='', subdir=''):
        captured['entry'] = entry
        return {'id': 'demo-plugin', 'version': '0.2.0'}

    monkeypatch.setattr(installer_module, 'install_from_catalog', fake_install)

    data = client.post('/api/plugins/catalog/update', json={'id': 'demo-plugin'}).get_json()

    assert data['success'] is True
    assert data['restart_required'] is True
    assert data['previous_version'] == '0.1.0'
    assert data['result']['version'] == '0.2.0'
    assert '0.1.0' in data['msg'] and '0.2.0' in data['msg']
    assert captured['entry']['id'] == 'demo-plugin'


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
