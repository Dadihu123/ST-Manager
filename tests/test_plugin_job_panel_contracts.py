"""插件作业面板契约测试（设计文档 1.7 / 13.2）。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def test_panel_uses_ui_modal_skeleton():
    template = read_source('templates/components/plugin_job_panel.html')

    assert 'ui-modal-shell' in template
    assert 'modal-overlay' in template
    assert 'role="dialog"' in template
    assert 'plugin-job-shell' in template


def test_panel_component_is_registered():
    app_source = read_source('static/js/app.js')

    assert 'pluginJobPanel.js' in app_source
    assert 'Alpine.data("pluginJobPanel"' in app_source


def test_panel_is_included_in_layout():
    index_source = read_source('templates/index.html')

    assert 'components/plugin_job_panel.html' in index_source


def test_panel_listens_for_open_event():
    component = read_source('static/js/components/pluginJobPanel.js')

    assert '"open-plugin-job-panel"' in component
    assert 'window.addEventListener' in component


def test_panel_supports_all_job_actions():
    component = read_source('static/js/components/pluginJobPanel.js')

    for fragment in (
        'cancelPluginJob',
        'pausePluginJob',
        'resumePluginJob',
        'retryPluginJob',
        'retry_failed',
        'retry_all',
    ):
        assert fragment in component, fragment


def test_panel_streams_via_plugin_host_with_polling_fallback():
    component = read_source('static/js/components/pluginJobPanel.js')

    assert 'PluginHost.getPluginApi' in component
    assert 'subscribeJob' in component
    assert 'POLL_INTERVAL_MS = 4000' in component


def test_style_module_is_registered_in_entry_css():
    style_entry = read_source('static/css/style.css')

    assert 'modules/modal-plugin-job.css' in style_entry


def test_panel_css_uses_semantic_tokens_only():
    css = read_source('static/css/modules/modal-plugin-job.css')

    assert 'var(--content-' in css
    assert 'var(--surface-' in css
    assert '#0' not in css.split('ui-monospace')[0]
    assert 'bg-red-' not in css and 'text-blue-' not in css


def test_plugin_host_exposes_job_helpers():
    host = read_source('static/js/pluginHost.js')

    for fragment in ('jobs: {', 'async submit(jobType', 'async cancel(runId)', 'open(runId'):
        assert fragment in host, fragment


def test_plugin_host_exposes_sse_parser():
    host = read_source('static/js/pluginHost.js')

    assert 'parseSSEFrames' in host
    assert 'utils/sse.js' in host


def test_management_api_wrappers_exist_for_jobs():
    api_module = read_source('static/js/api/plugins.js')

    for fragment in (
        'getPluginJob',
        'listPluginJobs',
        'cancelPluginJob',
        'pausePluginJob',
        'resumePluginJob',
        'retryPluginJob',
    ):
        assert fragment in api_module, fragment


def test_sample_plugin_demonstrates_job_flow():
    manifest = read_source('samples/plugins/hello-world/manifest.json')
    backend = read_source('samples/plugins/hello-world/backend/__init__.py')
    frontend = read_source('samples/plugins/hello-world/frontend/plugin.js')

    assert '"demo.count"' in manifest
    assert "api.jobs.register('demo.count'" in backend
    assert 'ctx.should_cancel()' in backend
    assert 'api.jobs.submit' in frontend
    assert 'api.jobs.open' in frontend
