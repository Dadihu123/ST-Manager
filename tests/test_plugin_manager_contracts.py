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


def test_modal_uses_ui_modal_skeleton():
    template = read_source('templates/modals/plugin_manager.html')

    assert 'ui-modal-shell' in template
    assert 'modal-overlay' in template
    assert 'ui-modal-body' in template
    assert 'role="dialog"' in template


def test_modal_component_is_registered_in_app_entry():
    app_source = read_source('static/js/app.js')

    assert 'pluginManager' in app_source
    assert 'pluginManager.js' in app_source


def test_three_tabs_are_present():
    template = read_source('templates/modals/plugin_manager.html')

    assert '已安装' in template
    assert '官方目录' in template
    assert '手动安装' in template
    assert 'role="tablist"' in template


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
