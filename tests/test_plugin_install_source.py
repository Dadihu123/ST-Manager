"""插件「安装来源」外链契约（设置 → 插件管理 → 已安装插件卡片上的「来源」按钮）。

背景：官方目录卡片一直有 GitHub 外链（`entry.homepage`），但**已安装**插件的
卡片没有——安装时拿到的仓库地址在 `install_from_catalog` 里被丢弃，磁盘上也没
任何地方记着「这个插件是从哪儿装的」。

这里锁定三件事：
1. 安装时把来源写进 `ui_data._plugins_v1.<id>.install_source`（catalog / upload 两条路径）；
2. `/api/plugins/list` 解析出**单个** `source_url`（安装记录 → manifest.homepage → 由 repo 派生）；
3. 模板只在 URL 存在时才渲染那个链接。
"""

import json
import os
import sys
import zipfile

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import installer as installer_module
from core.plugins import job_store, registry
from core.plugins import routes as routes_module
from core.plugins import secrets as secrets_module
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import (
    base_manifest,
    clear_plugin_ui_namespace,
    write_plugin,
)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    plugins_root = tmp_path / 'plugins'
    plugins_root.mkdir()
    temp_root = tmp_path / 'temp'
    temp_root.mkdir()

    monkeypatch.setattr(registry, 'plugins_dir', lambda: str(plugins_root))
    monkeypatch.setattr(installer_module, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(installer_module, 'TEMP_DIR', str(temp_root))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    registry.reset_for_tests()
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()

    yield {'plugins_root': plugins_root, 'temp_root': temp_root, 'tmp_path': tmp_path}

    registry.reset_for_tests()
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()


def _write_plugin_zip(path, plugin_id='zip-plugin'):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps({
            'id': plugin_id,
            'name': plugin_id,
            'version': '0.1.0',
            'api_version': 1,
            'backend': {'entry': 'backend', 'register': 'register'},
        }))
        archive.writestr('backend/__init__.py', 'def register(api):\n    return None\n')
    return path


def _stub_download(archive_path, monkeypatch):
    def fake_download(url, dest_path, *, max_bytes=installer_module.MAX_DOWNLOAD_BYTES):
        import shutil as _shutil

        _shutil.copy2(archive_path, dest_path)
        return os.path.getsize(dest_path)

    monkeypatch.setattr(installer_module, 'download_archive', fake_download)


class _FakeUpload:
    def __init__(self, source_path):
        self.filename = os.path.basename(source_path)
        self._source = source_path

    def save(self, destination):
        import shutil as _shutil

        _shutil.copy2(self._source, destination)


# ------------------------------------------------------------------ 纯函数


def test_build_repo_url_points_at_the_web_page_not_codeload():
    """外链必须是人类可读的仓库页，**不是** codeload 的 zip 归档地址。"""
    assert installer_module.build_repo_url('owner/repo') == 'https://github.com/owner/repo'
    assert 'codeload' not in installer_module.build_repo_url('owner/repo')
    # 非法 repo 不造链接（返回空串，让 UI 不渲染）
    assert installer_module.build_repo_url('https://evil.example/x.zip') == ''
    assert installer_module.build_repo_url('') == ''


def test_build_install_source_fills_repo_url_when_missing():
    record = installer_module.build_install_source(kind='github', repo='owner/repo')

    assert record['kind'] == 'github'
    assert record['repo'] == 'owner/repo'
    assert record['url'] == 'https://github.com/owner/repo'
    assert isinstance(record['installed_at'], float)


def test_build_install_source_never_invents_a_url():
    """没有 repo、也没有显式 url 时 `url` 必须为空——不猜一个可能 404 的链接。"""
    record = installer_module.build_install_source(kind='upload')

    assert record['url'] == ''
    assert record['repo'] == ''


# ------------------------------------------------------------------ 安装时落盘


def test_install_from_catalog_persists_install_source(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', plugin_id='catalog-plugin')
    _stub_download(archive_path, monkeypatch)

    installer_module.install_from_catalog(None, {
        'id': 'catalog-plugin',
        'source': {'type': 'github', 'repo': 'owner/repo', 'ref': 'main'},
    })

    record = registry.read_install_source('catalog-plugin')
    assert record['kind'] == 'catalog'
    assert record['repo'] == 'owner/repo'
    assert record['url'] == 'https://github.com/owner/repo', '必须是仓库页而不是 codeload'
    assert record['ref'] == 'main'
    assert record['subdir'] == ''
    assert record['installed_at'] > 0


def test_install_from_catalog_prefers_catalog_homepage(tmp_path, install_env, monkeypatch):
    """catalog 条目声明了 `homepage` 时用它（发布方可能指向文档站而非仓库页）。"""
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', plugin_id='catalog-plugin')
    _stub_download(archive_path, monkeypatch)

    installer_module.install_from_catalog(None, {
        'id': 'catalog-plugin',
        'homepage': 'https://example.test/docs',
        'source': {'type': 'github', 'repo': 'owner/repo'},
    })

    record = registry.read_install_source('catalog-plugin')
    assert record['url'] == 'https://example.test/docs'


def test_install_from_github_path_is_marked_as_github_kind(tmp_path, install_env, monkeypatch):
    """`/api/plugins/install_github` 走同一条安装路径，但来源分类是 `github`。"""
    archive_path = _write_plugin_zip(tmp_path / 'gh.zip', plugin_id='gh-plugin')
    _stub_download(archive_path, monkeypatch)

    installer_module.install_from_catalog(
        None,
        {'id': 'gh-plugin', 'source': {'type': 'github', 'repo': 'owner/gh'}},
        kind='github',
    )

    record = registry.read_install_source('gh-plugin')
    assert record['kind'] == 'github'
    assert record['url'] == 'https://github.com/owner/gh'


def test_install_from_upload_persists_no_url(tmp_path, install_env):
    """上传路径没有来源网址：`kind='upload'` 且 `url` 为空。"""
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', plugin_id='upload-plugin')

    installer_module.install_from_upload(_FakeUpload(str(archive_path)))

    record = registry.read_install_source('upload-plugin')
    assert record['kind'] == 'upload'
    assert record['url'] == ''
    assert record['repo'] == ''


def test_reinstall_updates_the_record_without_duplicating(tmp_path, install_env, monkeypatch):
    """覆盖安装只刷新同一条记录（幂等），且不破坏同命名空间下的其它键。"""
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', plugin_id='catalog-plugin')
    _stub_download(archive_path, monkeypatch)

    from core.data.ui_store import update_ui_data

    def seed_config(ui_data):
        ui_data.setdefault('_plugins_v1', {}).setdefault('catalog-plugin', {})['config'] = {
            'greeting': 'kept',
        }

    update_ui_data(seed_config)

    for _ in range(2):
        installer_module.install_from_catalog(None, {
            'id': 'catalog-plugin',
            'source': {'type': 'github', 'repo': 'owner/repo'},
        })

    entry = registry.read_ui_entry('catalog-plugin')
    assert entry['config'] == {'greeting': 'kept'}, '安装不得清掉既有配置'
    assert isinstance(entry['install_source'], dict), '记录必须是单条对象，不是列表'
    assert entry['install_source']['url'] == 'https://github.com/owner/repo'


def test_install_source_is_cleared_on_uninstall(tmp_path, install_env):
    """卸载（默认不保留数据）时随 `_plugins_v1.<id>` 一并清理。"""
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', plugin_id='upload-plugin')
    installer_module.install_from_upload(_FakeUpload(str(archive_path)))
    assert registry.read_install_source('upload-plugin')

    installer_module.uninstall_plugin('upload-plugin')

    assert registry.read_install_source('upload-plugin') == {}


# ------------------------------------------------------------------ /api/plugins/list


@pytest.fixture
def client(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')

    state = registry.PluginState('demo-plugin', plugin_dir)
    state.manifest = PluginManifest.load(plugin_dir)
    state.loaded = True

    monkeypatch.setattr(registry, '_states', {'demo-plugin': state})
    monkeypatch.setattr(registry, 'plugins_dir', lambda: str(tmp_path))
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))
    secrets_module._clear_degraded()
    clear_plugin_ui_namespace()

    app = Flask('plugin-install-source-test')
    app.register_blueprint(routes_module.bp)
    yield {'client': app.test_client(), 'plugin_dir': plugin_dir, 'tmp_path': tmp_path}
    clear_plugin_ui_namespace()


def _list_item(client, plugin_id='demo-plugin'):
    data = client.get('/api/plugins/list').get_json()
    assert data['success'] is True
    items = {item['id']: item for item in data['items']}
    return items[plugin_id]


def test_list_without_any_source_exposes_empty_source_url(client):
    """既没有安装记录也没有 `homepage` → `source_url` 为空串（前端不渲染按钮）。"""
    item = _list_item(client['client'])

    assert item['source_url'] == ''
    assert item['install_source'] == {}


def test_list_prefers_persisted_install_source_over_homepage(client):
    """优先级 1：持久化的 `install_source.url` 压过 manifest 的 `homepage`。"""
    plugin_dir = client['plugin_dir']
    with open(os.path.join(plugin_dir, 'manifest.json'), 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    payload['homepage'] = 'https://example.test/homepage'
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    state = registry.get_state('demo-plugin')
    state.manifest = PluginManifest.load(plugin_dir, check_dir_name=False)

    registry.persist_install_source('demo-plugin', {
        'kind': 'catalog',
        'repo': 'owner/repo',
        'url': 'https://github.com/owner/repo',
        'ref': 'main',
        'subdir': '',
        'installed_at': 1700000000.0,
    })

    item = _list_item(client['client'])
    assert item['source_url'] == 'https://github.com/owner/repo'
    assert item['install_source']['kind'] == 'catalog'
    # `homepage` 仍然原样带出（不覆盖字段，只是不再用于外链解析）
    assert item['homepage'] == 'https://example.test/homepage'


def test_list_falls_back_to_manifest_homepage(client):
    """优先级 2：没有安装记录时回退到 manifest 的 `homepage`。"""
    plugin_dir = client['plugin_dir']
    with open(os.path.join(plugin_dir, 'manifest.json'), 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    payload['homepage'] = 'https://example.test/homepage'
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    state = registry.get_state('demo-plugin')
    state.manifest = PluginManifest.load(plugin_dir, check_dir_name=False)

    assert _list_item(client['client'])['source_url'] == 'https://example.test/homepage'


def test_list_derives_repo_url_when_only_repo_is_known(client):
    """优先级 3：老记录只有 repo、没有 url 时派生仓库页地址。"""
    registry.persist_install_source('demo-plugin', {
        'kind': 'github',
        'repo': 'owner/legacy',
        'installed_at': 1700000000.0,
    })

    assert _list_item(client['client'])['source_url'] == 'https://github.com/owner/legacy'


def test_list_ignores_malformed_install_source(client):
    """畸形记录（非对象 / repo 非法）不得造出链接，也不得让接口 500。"""
    from core.data.ui_store import update_ui_data

    def mutator(ui_data):
        namespace = ui_data.setdefault('_plugins_v1', {})
        namespace.setdefault('demo-plugin', {})['install_source'] = ['not', 'an', 'object']

    update_ui_data(mutator)

    item = _list_item(client['client'])
    assert item['source_url'] == ''
    assert item['install_source'] == {}


def test_read_install_sources_reads_everything_in_one_pass(client):
    """批量读取：`/api/plugins/list` 与 `/api/plugins/catalog` 都走这一条，
    否则 N 个插件会把整个 ui_data.json 解析 N 遍。"""
    registry.persist_install_source('demo-plugin', {
        'kind': 'catalog', 'repo': 'owner/repo', 'url': 'https://github.com/owner/repo',
        'installed_at': 1700000000.0,
    })

    sources = registry.read_install_sources()

    assert sources['demo-plugin']['repo'] == 'owner/repo'
    # 返回的是拷贝：调用方改动不会污染下一次读取
    sources['demo-plugin']['repo'] = 'tampered'
    assert registry.read_install_source('demo-plugin')['repo'] == 'owner/repo'


def test_batch_and_single_plugin_header_paths_agree(client):
    """`header` / `detail()` 与批量路径必须给出同一个 `source_url`。"""
    registry.persist_install_source('demo-plugin', {
        'kind': 'github', 'repo': 'owner/repo', 'installed_at': 1700000000.0,
    })
    state = registry.get_state('demo-plugin')

    single = state.header
    batched = state.build_header(registry.read_install_sources()['demo-plugin'])

    assert single == batched
    assert single['source_url'] == 'https://github.com/owner/repo'
    assert state.detail()['source_url'] == single['source_url']


def test_list_source_url_survives_unreadable_manifest(client):
    """插件加载失败（无 manifest）时依然能给出安装记录里的来源链接。"""
    registry.persist_install_source('demo-plugin', {
        'kind': 'catalog',
        'repo': 'owner/repo',
        'url': 'https://github.com/owner/repo',
        'installed_at': 1700000000.0,
    })
    registry.get_state('demo-plugin').manifest = None

    assert _list_item(client['client'])['source_url'] == 'https://github.com/owner/repo'


# ------------------------------------------------------------------ 模板契约


def test_template_renders_source_link_only_when_url_present():
    """已安装卡片上的外链必须 `x-show` 门控在 `source_url` 上，且新窗口 + noopener。"""
    template = read_source('templates/modals/plugin_manager.html')

    # 已安装卡片区域（① 已安装 → ② 官方目录之间）
    installed = template.split('id="plugin-panel-installed"', 1)[1].split(
        'id="plugin-panel-catalog"', 1,
    )[0]

    assert 'x-show="item.source_url"' in installed, '按钮必须只在 URL 已知时渲染'
    assert ':href="item.source_url"' in installed
    assert 'target="_blank"' in installed
    assert 'rel="noopener noreferrer"' in installed
    assert '>来源' in installed or '来源\n' in installed


def test_installed_card_link_matches_catalog_card_link_markup():
    """与官方目录卡片的 GitHub 链接保持同一套 class（样式必须一致）。"""
    template = read_source('templates/modals/plugin_manager.html')

    installed = template.split('id="plugin-panel-installed"', 1)[1].split(
        'id="plugin-panel-catalog"', 1,
    )[0]
    catalog = template.split('id="plugin-panel-catalog"', 1)[1]

    link_block = (
        'class="plugin-button plugin-button--ghost"\n'
        '                x-show="item.source_url"\n'
        '                :href="item.source_url"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"'
    )
    assert link_block in installed

    # 目录卡片那份仍然原样存在（未被这次改动影响）
    assert 'x-show="entry.homepage"' in catalog
    assert ':href="entry.homepage"' in catalog


def test_catalog_card_markup_is_unchanged_by_this_feature():
    """回归：目录卡片的 GitHub 链接块逐字未变。"""
    template = read_source('templates/modals/plugin_manager.html')

    assert (
        '<a\n'
        '                class="plugin-button plugin-button--ghost"\n'
        '                x-show="entry.homepage"\n'
        '                :href="entry.homepage"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '              >\n'
        '                GitHub\n'
        '              </a>'
    ) in template


def test_component_does_not_rebuild_the_url_from_the_repo():
    """`source_url` 由后端解析并下发，前端不得自己拼 `https://github.com/<repo>`。

    组件里唯一允许出现 `github.com` 的地方是「从 GitHub 安装」输入框的提示文案
    （`owner/repo 或 https://github.com/owner/repo`），与来源外链无关。
    """
    component = read_source('static/js/components/pluginManager.js')

    assert "item.source_url" not in component, '模板直接绑定，无需组件侧状态'
    assert 'install_source' not in component, '结构化记录本轮不消费，模板只用 source_url'
    assert 'https://github.com/' not in component.replace(
        'https://github.com/owner/repo', '',
    ), '除输入提示外，组件不得拼装 GitHub 地址'


def test_base_manifest_fixture_has_no_homepage_by_default():
    """前置事实：测试夹具默认**不**声明 homepage，否则上面的空值断言会失真。"""
    assert 'homepage' not in base_manifest('demo-plugin')
