"""前端 PluginHost 契约测试（设计文档 8.1–8.4 / 13.2）。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def test_api_contract_methods_are_exposed():
    source = read_source('static/js/pluginHost.js')

    for fragment in (
        'state',
        'get store()',
        'on(event, handler)',
        'off(event, handler)',
        'emit(event, detail)',
        'toast(msg',
        'progress: {',
        'openDetail(target',
        'refresh(target',
        'switchMode(mode)',
        'openSettingsSection(section',
        'registerAlpineComponent(name',
        'registerModal(spec)',
        'registerSettingsSection(spec)',
        'async api(path',
        'subscribeJob(runId',
        'estimateTokens(text)',
        'createRoot(tag',
    ):
        assert fragment in source, fragment


def test_api_uses_data_success_not_only_response_ok():
    source = read_source('static/js/pluginHost.js')

    assert 'data.success' in source
    assert 'typeof data.success !== "boolean"' in source


def test_api_sends_requested_with_and_csrf_headers():
    source = read_source('static/js/pluginHost.js')

    assert 'X-Requested-With' in source
    assert 'XMLHttpRequest' in source
    assert 'meta[name="csrf-token"]' in source
    assert 'X-CSRFToken' in source


def test_alpine_dual_branch_registration_exists():
    source = read_source('static/js/pluginHost.js')

    assert 'window.Alpine' in source
    assert 'alpine:init' in source
    assert 'registerAlpineComponent' in source


def test_plugin_loading_is_lazy():
    source = read_source('static/js/pluginHost.js')

    assert 'requestIdleCallback' in source


def test_create_root_marks_data_plugin_and_host_root():
    source = read_source('static/js/pluginHost.js')

    assert 'plugin-host-root' in source
    assert 'dataset.plugin = pluginId' in source


def test_styles_are_skipped_when_scope_check_fails():
    source = read_source('static/js/pluginHost.js')

    assert 'style_scope_errors' in source
    assert 'injectStyle(pluginId, stylePath, version)' in source


# ---------------------------------------------------------------- D8 命名空间


def test_entry_registry_namespace_is_exposed():
    source = read_source('static/js/pluginHost.js')

    for fragment in (
        'entries: {',
        'register(spec)',
        'update(entryId, patch)',
        'remove(entryId)',
        'setBadge(entryId, value)',
        'setProgress(entryId, progress)',
        'setStatus(entryId, status)',
        'setBusy(entryId, busy)',
        'open(entryId)',
        'list()',
    ):
        assert fragment in source, fragment


def test_surfaces_namespace_is_exposed():
    source = read_source('static/js/pluginHost.js')

    for fragment in (
        'surfaces: {',
        'register(surfaceId, spec)',
        'open(surfaceId, ctx = {})',
        'close(surfaceId)',
        'isOpen(surfaceId)',
    ):
        assert fragment in source, fragment


def test_ui_primitives_namespace_covers_the_full_contract():
    """D8 的 `api.ui.*` 全集必须在宿主 UI 原语模块里都有实现。"""
    primitives = read_source('static/js/uiPrimitives.js')
    host = read_source('static/js/pluginHost.js')

    assert 'ui: buildUiPrimitives()' in host
    for name in (
        'icon', 'panel', 'section', 'card', 'field', 'form', 'button', 'toolbar',
        'empty', 'error', 'loading', 'badge', 'list', 'table', 'grid', 'split',
        'confirm', 'prompt',
    ):
        assert f'export function {name}(' in primitives, name
        assert f'{name},' in primitives or f'{name}:' in primitives, name


def test_storage_and_host_namespaces_are_exposed():
    source = read_source('static/js/pluginHost.js')

    for fragment in ('storage: {', 'get(key)', 'set(key, value)', 'remove(key)', 'keys()'):
        assert fragment in source, fragment

    for fragment in (
        'host: {',
        'toast(msg, duration, iconName)',
        'refresh(target)',
        'switchMode(mode)',
        'openDetail(target, id)',
        'openSettingsSection(section, anchor = "")',
        'notify(message, level = "info")',
        'log(message, level = "info")',
    ):
        assert fragment in source, fragment


def test_legacy_members_are_kept_as_delegating_aliases():
    """旧成员必须保留（不破坏既有插件），且内部委托到新实现。"""
    source = read_source('static/js/pluginHost.js')

    assert 'registerModal(spec)' in source
    assert 'registerSettingsSection(spec)' in source
    # 旧裸动词委托到 host 命名空间，而不是各自复制一份实现
    assert 'return api.host.refresh(target);' in source
    assert 'return api.host.switchMode(mode);' in source
    assert 'return api.host.openDetail' not in source
    assert 'return api.openDetail(target, id);' in source


def test_config_change_subscription_filters_by_plugin():
    """D10：`onConfigChange` 只能投递本插件的配置变更。"""
    source = read_source('static/js/pluginHost.js')

    assert 'onConfigChange(handler)' in source
    assert 'plugin-config-changed' in source
    assert 'detail.pluginId || "") !== pluginId' in source


# ---------------------------------------------------------------- D9 缺陷修复


def test_activate_return_value_is_recorded_as_disposer():
    """D9.1：`activate()` 的返回值此前被丢弃，现在必须记为插件级 disposer。"""
    source = read_source('static/js/pluginHost.js')

    assert 'const disposer = await module.activate(api);' in source
    assert 'this.addDisposer(pluginId, disposer)' in source
    assert 'addDisposer(pluginId, disposer) {' in source


def test_destroy_has_callers_and_tears_down_surfaces():
    """D9.2：`destroy()` 不能再是死代码，且必须卸载 surface 与注册表条目。"""
    source = read_source('static/js/pluginHost.js')

    assert 'PluginSurfaceHost.unregisterPlugin(key);' in source
    assert 'EntryRegistry.removePlugin(key);' in source
    assert 'this.disposers.get(key) || []' in source
    assert "window.addEventListener(\"plugin:unloaded\"" in source
    # 管理 UI 必须真的派发这个事件，否则监听方永远收不到
    manager = read_source('static/js/components/pluginManager.js')
    assert 'notifyPluginUnloaded(' in manager
    assert 'new CustomEvent("plugin:unloaded"' in manager


def test_asset_urls_are_versioned():
    """D11：资产 URL 必须带 `?v=<插件版本>`，避免更新后复用旧 CSS/JS。"""
    source = read_source('static/js/pluginHost.js')

    assert 'function withAssetVersion(url, version)' in source
    assert 'v=${encodeURIComponent(stamp)}' in source
    assert 'injectStyle(pluginId, stylePath, version)' in source
    assert 'toAbsoluteAssetUrl(pluginId, manifest.frontend_entry, version)' in source


# ---------------------------------------------------------------- 宿主接线


def test_runtime_modules_are_initialised_from_host():
    source = read_source('static/js/pluginHost.js')

    assert 'EntryRegistry.init();' in source
    assert 'PluginSurfaceHost.init();' in source


def test_custom_events_require_plugin_prefix():
    source = read_source('static/js/pluginHost.js')

    assert '${pluginId}:' in source
    assert 'CORE_EVENTS' in source


def test_plugin_host_is_initialised_from_app_entry():
    app_source = read_source('static/js/app.js')

    assert 'pluginHost.js' in app_source
    assert 'PluginHost.init()' in app_source


def test_plugin_manager_panel_is_registered_through_settings():
    index_source = read_source('templates/index.html')
    settings_source = read_source('templates/modals/settings.html')

    assert 'modals/plugin_manager.html' not in index_source
    assert 'modals/settings.html' in index_source
    assert '{% include "modals/plugin_manager.html" %}' in settings_source


def test_settings_exposes_plugin_manager_entry():
    settings_source = read_source('templates/modals/settings.html')

    assert 'settings-maintenance-plugins' in settings_source
    assert "selectSettingTab('plugins')" in settings_source
