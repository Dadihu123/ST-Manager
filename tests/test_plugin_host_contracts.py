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
    assert 'injectStyle(pluginId, stylePath)' in source


def test_custom_events_require_plugin_prefix():
    source = read_source('static/js/pluginHost.js')

    assert '${pluginId}:' in source
    assert 'CORE_EVENTS' in source


def test_plugin_host_is_initialised_from_app_entry():
    app_source = read_source('static/js/app.js')

    assert 'pluginHost.js' in app_source
    assert 'PluginHost.init()' in app_source


def test_layout_registers_plugin_manager_modal():
    index_source = read_source('templates/index.html')

    assert 'modals/plugin_manager.html' in index_source


def test_settings_exposes_plugin_manager_entry():
    settings_source = read_source('templates/modals/settings.html')

    assert 'settings-maintenance-plugins' in settings_source
    assert 'open-plugin-manager' in settings_source
