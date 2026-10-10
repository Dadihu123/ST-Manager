"""目录页「已安装」状态契约（问题：已安装插件在目录里仍可反复安装）。

后端 `/api/plugins/catalog` 一直正确返回 `installed` / `installed_version`
（`routes.py` 里 `installed = {state.plugin_id: state.header ...}`），但前端
`plugin_manager.html` 的「安装」按钮是**无条件渲染**的，两个字段从未被消费，
于是已安装的插件照样显示「安装」并可反复覆盖安装。

这里锁定：后端字段正确 + 前端确实消费了它们。
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


# ------------------------------------------------------------------ 后端字段


@pytest.fixture
def catalog_client(tmp_path, monkeypatch):
    """挂上插件蓝图的最小 Flask app，并把 plugins_dir 指到临时目录。"""
    from flask import Flask

    from core.plugins import registry, routes
    from core.plugins.manifest import PluginManifest
    from tests.plugins_test_support import write_plugin

    plugins_root = tmp_path / 'plugins'
    plugins_root.mkdir()
    monkeypatch.setattr(registry, 'plugins_dir', lambda: str(plugins_root))
    registry.reset_for_tests()

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    client = app.test_client()

    def install(plugin_id, version):
        directory = write_plugin(plugins_root, plugin_id)
        with open(os.path.join(directory, 'manifest.json'), 'r', encoding='utf-8') as handle:
            import json
            payload = json.load(handle)
        payload['version'] = version
        with open(os.path.join(directory, 'manifest.json'), 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)

        state = registry.PluginState(plugin_id, directory)
        state.manifest = PluginManifest.load(directory, check_dir_name=False)
        state.loaded = True
        registry._states[plugin_id] = state
        return state

    yield {'client': client, 'install': install}

    registry.reset_for_tests()


def test_catalog_marks_installed_plugin(catalog_client):
    """已安装的插件必须带 `installed=True` 与 `installed_version`。"""
    catalog_client['install']('stm-ai-assistant', '0.1.0')

    data = catalog_client['client'].get('/api/plugins/catalog').get_json()

    items = {item['id']: item for item in data['items']}
    # 包内清单里登记的官方插件
    assert 'stm-ai-assistant' in items, '包内 catalog 应含 stm-ai-assistant'
    item = items['stm-ai-assistant']
    assert item['installed'] is True
    assert item['installed_version'] == '0.1.0'


def test_catalog_leaves_uninstalled_plugin_marked_false(catalog_client):
    """未安装的条目 `installed=False` 且 `installed_version` 为空串。"""
    data = catalog_client['client'].get('/api/plugins/catalog').get_json()

    items = {item['id']: item for item in data['items']}
    item = items['stm-ai-assistant']
    assert item['installed'] is False
    assert item['installed_version'] == ''


# ------------------------------------------------------------------ 前端消费


def test_catalog_template_does_not_always_render_install_button():
    """回归：「安装」按钮必须有条件，不能对已安装插件照样显示。"""
    template = read_source('templates/modals/plugin_manager.html')

    # 三个动作互斥地由 catalogAction 决定
    assert "catalogAction(entry) === 'install'" in template
    assert "catalogAction(entry) === 'update'" in template
    assert "catalogAction(entry) === 'installed'" in template
    # 已安装最新版时给静态标记而不是按钮
    assert 'plugin-card-installed-tag' in template


def test_plugin_manager_consumes_installed_fields():
    """`installed` / `installed_version` 必须真的被用来决定动作。"""
    source = read_source('static/js/components/pluginManager.js')

    assert 'catalogAction(entry)' in source
    assert 'entry.installed' in source
    assert 'entry.installed_version' in source
    # 版本比较用共享实现，不自己造一份
    assert 'compareVersions' in source
    assert 'updateCatalogItem' in source


def test_install_catalog_item_guards_against_reinstall():
    """防御：即使函数被别处调用，也不该对已安装插件走「安装」。"""
    source = read_source('static/js/components/pluginManager.js')

    # 取 installCatalogItem 的函数体
    start = source.index('async installCatalogItem(item) {')
    end = source.index('async updateCatalogItem(', start) if 'async updateCatalogItem(' in source[start:] else start + 2000
    body = source[start:start + 1800]

    assert 'this.catalogAction(item)' in body, 'installCatalogItem 应先判定动作'
    assert '"update"' in body and '"installed"' in body


def test_catalog_actions_refresh_both_lists():
    """安装/更新后要同时刷新目录与已安装列表，卡片才会切到「已安装」。"""
    source = read_source('static/js/components/pluginManager.js')

    assert 'this.loadCatalog(true)' in source
    assert 'this.loadPlugins()' in source
