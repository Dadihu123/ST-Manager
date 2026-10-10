"""插件管理模态框契约测试（设计文档第 9 部分 / 13.2）。"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def test_panel_is_embedded_in_settings_instead_of_a_standalone_modal():
    """插件管理已并入设置页第五个导航页，因此不能再自带模态框外壳。"""
    template = read_source('templates/modals/plugin_manager.html')

    assert 'ui-modal-shell' not in template
    assert 'modal-overlay' not in template
    assert 'ui-modal-body' not in template
    assert 'role="dialog"' not in template

    settings_source = read_source('templates/modals/settings.html')
    assert '{% include "modals/plugin_manager.html" %}' in settings_source
    assert 'settings-panel-plugins' in settings_source
    assert "selectSettingTab('plugins')" in settings_source


def test_modal_component_is_registered_in_app_entry():
    app_source = read_source('static/js/app.js')

    assert 'pluginManager' in app_source
    assert 'pluginManager.js' in app_source


def test_four_tabs_are_present():
    template = read_source('templates/modals/plugin_manager.html')

    assert '已安装' in template
    assert '官方目录' in template
    assert '手动安装' in template
    # 阶段 6.1：入口总览作为第四个页签挂在既有「插件管理」页内
    # （刻意不新增设置顶层 tab —— settingsHelpContent 是硬闸门）。
    assert '入口总览' in template
    assert 'role="tablist"' in template
    # 页签沿用角色卡详情页的 .detail-tabs / .detail-tab 契约。
    assert 'class="detail-tabs plugin-manager-tabs"' in template
    assert template.count('class="detail-tab"') == 4


def test_entry_overview_is_embedded_in_plugin_manager_not_a_new_settings_tab():
    """总览页必须挂在插件管理页内，不能新增设置顶层分区。"""
    template = read_source('templates/modals/plugin_manager.html')
    settings_source = read_source('templates/modals/settings.html')

    assert 'id="plugin-panel-entries"' in template
    assert 'selectTab(\'entries\')' in template
    # 没有新增设置顶层导航项
    assert "selectSettingTab('entries')" not in settings_source


def test_entry_overview_table_columns_match_contract():
    """表格列：图标+名称 / 归属 / 类型 / 出现位置 / 当前呈现 / 快捷键 / 操作。"""
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    for column in ('名称', '归属', '类型', '出现位置', '当前呈现', '快捷键', '操作'):
        assert f'<th scope="col">{column}</th>' in template, column

    assert 'entryKindLabel(row)' in template
    assert 'entryLocationLabel(row)' in template
    assert 'entrySurfaceLabel(row)' in template


def test_deep_link_anchors_support_config_and_secrets():
    """阶段 6.2：`plugin-config-<id>` / `plugin-secrets-<id>` 深链。"""
    component = read_source('static/js/components/pluginManager.js')

    assert 'CONFIG_ANCHOR_PATTERN' in component
    assert 'SECRET_ANCHOR_PATTERN' in component
    assert 'plugin-config-' in component
    assert 'plugin-secrets-' in component
    assert 'deepLink(pluginId, target)' in component
    # 深链必须先加载列表再展开表单，否则拿不到 item
    assert 'await this.loadPlugins();' in component
    assert 'scrollToPlugin(id)' in component


def test_tier_badge_is_rendered_on_plugin_cards():
    """阶段 6.3：归属分级徽标（tier 由宿主 catalog 决定）。"""
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    assert 'plugin-card-tier' in template
    assert 'tierLabel(item)' in template
    assert 'TIER_LABELS' in component
    assert 'official' in component and 'verified' in component and 'community' in component


def test_install_disclosure_shows_entry_count():
    """阶段 6.3：安装期披露「此插件将添加 N 个入口」。"""
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    assert 'entryCountLabel(item)' in template
    assert '此插件将添加' in component

def test_four_lifecycle_actions_are_present():
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    for label in ('安装', '卸载', '禁用', '启用'):
        assert label in template, label

    assert 'installCatalogItem' in component
    assert 'uninstall(' in component
    assert 'toggleEnabled(' in component


def test_config_and_secret_forms_are_rendered_from_schema():
    component = read_source('static/js/components/pluginManager.js')

    assert 'schemaEntries(' in component
    assert 'config_schema' in component
    assert 'secret_schema' in component


def test_plugin_docs_button_and_dependency_row_exist():
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')
    api_module = read_source('static/js/api/plugins.js')

    assert 'openDocs(item)' in template
    assert 'requirementLabels(item)' in template
    assert 'async openDocs(' in component
    assert 'requirementLabels(item) {' in component
    assert 'getPluginReadme' in api_module


def test_docs_are_rendered_through_markdown_preview():
    component = read_source('static/js/components/pluginManager.js')
    editor = read_source('static/js/components/largeEditor.js')
    preview = read_source('templates/modals/markdown_preview.html')

    assert 'open-markdown-view' in component
    # detail 支持 { content, title }，且标题可动态切换
    assert 'payload.title' in editor
    assert 'markdownModalTitle' in editor
    assert 'markdownModalTitle' in preview


def test_secret_inputs_are_password_with_hint_placeholder():
    template = read_source('templates/modals/plugin_manager.html')

    assert 'type="password"' in template
    assert 'plugin-secret-state' in template
    assert 'hint' in template


def test_secret_banner_warns_about_plaintext_storage():
    template = read_source('templates/modals/plugin_manager.html')

    assert 'data/system/secrets.json' in template


def test_style_module_is_registered_in_entry_css():
    style_entry = read_source('static/css/style.css')

    assert 'modules/modal-plugin-manager.css' in style_entry


def test_no_tailwind_palette_utilities_in_plugin_manager_sources():
    legacy_fragments = (
        'bg-red-', 'bg-blue-', 'bg-green-', 'bg-purple-',
        'text-red-', 'text-blue-', 'text-green-', 'text-purple-',
    )

    for relative_path in (
        'templates/modals/plugin_manager.html',
        'static/js/components/pluginManager.js',
        'static/js/api/plugins.js',
        'static/css/modules/modal-plugin-manager.css',
    ):
        source = read_source(relative_path)
        assert not any(fragment in source for fragment in legacy_fragments), relative_path


def test_css_uses_semantic_tokens_only():
    css = read_source('static/css/modules/modal-plugin-manager.css')

    assert 'var(--content-' in css
    assert 'var(--surface-' in css
    assert not re.search(r'#[0-9a-fA-F]{6}\b', css), '模块样式不应写死十六进制颜色'
