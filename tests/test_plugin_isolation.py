"""跨插件隔离测试（安全审计：作业归属 / 密钥命名空间 / 配置命名空间）。

作业的 `run_id` 会出现在 SSE 事件、日志与前端 URL 中，属于**可泄漏信息**，
因此不能依赖「不可猜测」作为隔离手段。本文件锁定「插件只能操作自己的资源」。
"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import job_store, jobs, registry
from core.plugins import secrets as secrets_module
from core.plugins.api import PluginAPI
from core.plugins.errors import PluginJobNotFoundError
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    jobs.reset_for_tests()
    secrets_module._clear_degraded()
    clear_plugin_ui_namespace()
    yield
    jobs.reset_for_tests()
    secrets_module._clear_degraded()
    clear_plugin_ui_namespace()


@pytest.fixture
def two_plugins(tmp_path):
    """两个插件各自的 API 实例 + 各自的一个作业。"""

    def _make(plugin_id):
        plugin_dir = write_plugin(tmp_path, plugin_id)
        return PluginAPI(PluginManifest.load(plugin_dir))

    def _handler(ctx):
        ctx.report(ctx.items[0]['key'], status='done')

    api_a = _make('alpha-plugin')
    api_b = _make('beta-plugin')

    jobs.register_job_handler('alpha-plugin', 'alpha.run', _handler)
    jobs.register_job_handler('beta-plugin', 'beta.run', _handler)

    run_a = jobs.submit_job('alpha-plugin', 'alpha.run', ['x'])
    run_b = jobs.submit_job('beta-plugin', 'beta.run', ['y'])

    return {'a': api_a, 'b': api_b, 'run_a': run_a, 'run_b': run_b}


# ------------------------------------------------------------------ 作业归属


def test_plugin_cannot_read_other_plugins_job(two_plugins):
    assert two_plugins['a'].get_job(two_plugins['run_a'])['run_id'] == two_plugins['run_a']
    assert two_plugins['a'].get_job(two_plugins['run_b']) is None


def test_plugin_cannot_cancel_other_plugins_job(two_plugins):
    with pytest.raises(PluginJobNotFoundError):
        two_plugins['a'].cancel_job(two_plugins['run_b'])

    conn = job_store.connect(ensure_schema=True)
    try:
        assert job_store.get_job(conn, two_plugins['run_b'])['status'] == 'queued'
    finally:
        conn.close()


def test_plugin_cannot_retry_other_plugins_job(two_plugins):
    with pytest.raises(PluginJobNotFoundError):
        two_plugins['a'].retry_job(two_plugins['run_b'])


def test_plugin_cannot_pause_other_plugins_job(two_plugins):
    with pytest.raises(PluginJobNotFoundError):
        two_plugins['a'].pause_job(two_plugins['run_b'])


def test_plugin_cannot_resume_other_plugins_job(two_plugins):
    with pytest.raises(PluginJobNotFoundError):
        two_plugins['a'].resume_job(two_plugins['run_b'])


def test_ownership_error_does_not_leak_existence(two_plugins):
    """越权与「作业不存在」必须给出同样的错误，否则可用于探测他人作业。"""
    cross_tenant = None
    nonexistent = None

    try:
        two_plugins['a'].cancel_job(two_plugins['run_b'])
    except PluginJobNotFoundError as exc:
        cross_tenant = exc.to_dict()

    try:
        two_plugins['a'].cancel_job('nonexistent-run-id')
    except PluginJobNotFoundError as exc:
        nonexistent = exc.to_dict()

    assert cross_tenant is not None and nonexistent is not None
    assert cross_tenant['error'] == nonexistent['error'] == 'job_not_found'
    # run_id 本身会出现在消息里（调用方已知），但不得透露归属插件名
    assert 'beta-plugin' not in str(cross_tenant)


def test_ownership_violation_is_logged(two_plugins, monkeypatch):
    warnings = []
    monkeypatch.setattr(jobs.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    with pytest.raises(PluginJobNotFoundError):
        two_plugins['a'].cancel_job(two_plugins['run_b'])

    assert any('非本插件作业' in str(args[0]) for args in warnings)


def test_plugin_can_operate_its_own_job(two_plugins):
    assert two_plugins['a'].cancel_job(two_plugins['run_a']) is True

    conn = job_store.connect(ensure_schema=True)
    try:
        assert job_store.get_job(conn, two_plugins['run_a'])['status'] == 'cancelled'
    finally:
        conn.close()


def test_plugin_cannot_access_other_plugins_items(two_plugins):
    """条目审批同样按作业归属隔离。"""
    with pytest.raises(PluginJobNotFoundError):
        jobs.review_item(
            two_plugins['run_b'], 'y', status='done', plugin_id='alpha-plugin',
        )


def _drain(response, *, max_chunks: int = 200) -> str:
    """读取 SSE 响应，带块数上限。

    越权请求应立刻收到一个 `done` 帧；若归属校验退化，事件流会一直挂着——
    没有上限的 `list(response.response)` 会让测试**挂死**而不是失败，
    既掩盖了缺陷也拖垮整个测试套件。
    """
    chunks = []
    for chunk in response.response:
        chunks.append(chunk)
        if len(chunks) >= max_chunks:
            chunks.append('…TRUNCATED…')
            break
    return ''.join(chunks)


def test_stream_job_events_rejects_cross_plugin_subscription(two_plugins):
    response = jobs.stream_job_events(two_plugins['run_b'], plugin_id='alpha-plugin')
    text = _drain(response)

    assert 'job_not_found' in text
    assert 'snapshot' not in text


def _completed_run(plugin_id, job_type, key):
    """跑完一个作业，使其进入终态——SSE 流只在终态后自然结束。"""
    jobs.register_job_handler(plugin_id, job_type, lambda ctx: ctx.report(key, status='done'))
    run_id = jobs.submit_job(plugin_id, job_type, [key])
    jobs._process_pending_jobs()
    return run_id


def test_stream_job_events_allows_owner(two_plugins):
    run_id = _completed_run('alpha-plugin', 'alpha.stream', 'x')

    response = jobs.stream_job_events(run_id, plugin_id='alpha-plugin')
    text = _drain(response)

    assert 'event: snapshot' in text
    assert 'event: done' in text


def test_cross_plugin_sse_does_not_consume_slot(two_plugins):
    """越权订阅不应占用 SSE 连接配额（否则可被用来耗尽他人配额）。"""
    before = jobs.sse_connection_stats()['total']

    response = jobs.stream_job_events(two_plugins['run_b'], plugin_id='alpha-plugin')
    _drain(response)

    assert jobs.sse_connection_stats()['total'] == before


def test_jobs_helpers_default_to_no_ownership_check():
    """内部 worker 调用不传 plugin_id，必须保持可用（只做存在性校验）。"""
    jobs.register_job_handler('solo-plugin', 'solo.run', lambda ctx: None)
    run_id = jobs.submit_job('solo-plugin', 'solo.run', ['a'])

    assert jobs.get_job_detail(run_id) is not None
    assert jobs.cancel_job(run_id) is True


# ------------------------------------------------------------------ 路由层


@pytest.fixture
def route_client(tmp_path, monkeypatch):
    from core.plugins import routes as routes_module

    monkeypatch.setattr(registry, 'plugins_dir', lambda: str(tmp_path / 'plugins'))
    (tmp_path / 'plugins').mkdir(exist_ok=True)
    write_plugin(tmp_path / 'plugins', 'alpha-plugin')
    write_plugin(tmp_path / 'plugins', 'beta-plugin')

    app = Flask('isolation-test')
    app.register_blueprint(routes_module.bp)
    registry.load_all(app)

    yield app.test_client()


def test_route_blocks_cross_plugin_job_read(route_client):
    jobs.register_job_handler('beta-plugin', 'beta.run', lambda ctx: None)
    run_b = jobs.submit_job('beta-plugin', 'beta.run', ['y'])

    response = route_client.get(f'/api/plugins/alpha-plugin/jobs/{run_b}')

    assert response.status_code == 404
    assert response.get_json()['error'] == 'job_not_found'


@pytest.mark.parametrize('action', ['cancel', 'pause', 'resume', 'retry'])
def test_route_blocks_cross_plugin_job_actions(route_client, action):
    jobs.register_job_handler('beta-plugin', 'beta.run', lambda ctx: None)
    run_b = jobs.submit_job('beta-plugin', 'beta.run', ['y'])

    response = route_client.post(f'/api/plugins/alpha-plugin/jobs/{run_b}/{action}')

    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()['error'] == 'job_not_found'


def test_route_blocks_cross_plugin_item_review(route_client):
    jobs.register_job_handler('beta-plugin', 'beta.run', lambda ctx: None)
    run_b = jobs.submit_job('beta-plugin', 'beta.run', ['y'])

    response = route_client.post(
        f'/api/plugins/alpha-plugin/jobs/{run_b}/items/y/review',
        json={'status': 'done'},
    )

    assert response.status_code == 404
    assert response.get_json()['error'] == 'job_not_found'


def test_route_blocks_cross_plugin_event_stream(route_client):
    jobs.register_job_handler('beta-plugin', 'beta.run', lambda ctx: None)
    run_b = jobs.submit_job('beta-plugin', 'beta.run', ['y'])

    response = route_client.get(f'/api/plugins/alpha-plugin/jobs/{run_b}/events')
    text = response.get_data(as_text=True)

    assert 'job_not_found' in text
    assert 'snapshot' not in text


# ------------------------------------------------------------------ 密钥与配置


def test_plugin_cannot_read_other_plugins_secret(two_plugins):
    two_plugins['b'].set_secret('api_key', 'sk-beta-secret')

    assert two_plugins['b'].get_secret('api_key') == 'sk-beta-secret'
    assert two_plugins['a'].get_secret('api_key') is None


def test_plugin_secret_listing_is_namespaced(two_plugins):
    two_plugins['a'].set_secret('api_key', 'sk-alpha')
    two_plugins['b'].set_secret('api_key', 'sk-beta')

    listed_a = two_plugins['a'].list_secrets()

    assert 'api_key' in listed_a
    assert 'sk-beta' not in str(listed_a)


def test_plugin_cannot_clear_other_plugins_secrets(two_plugins):
    two_plugins['b'].set_secret('api_key', 'sk-beta')

    secrets_module.clear_plugin_secrets('alpha-plugin')

    assert two_plugins['b'].get_secret('api_key') == 'sk-beta'


def test_plugin_config_namespaces_are_isolated(two_plugins):
    two_plugins['a'].set_config({'greeting': 'alpha'})
    two_plugins['b'].set_config({'greeting': 'beta'})

    assert two_plugins['a'].get_config()['greeting'] == 'alpha'
    assert two_plugins['b'].get_config()['greeting'] == 'beta'


def test_plugin_ui_data_namespaces_are_isolated(two_plugins):
    two_plugins['a'].ui_data_update(lambda entry: entry.update({'n': 1}))
    two_plugins['b'].ui_data_update(lambda entry: entry.update({'n': 2}))

    assert two_plugins['a'].ui_data_read()['n'] == 1
    assert two_plugins['b'].ui_data_read()['n'] == 2


def test_plugin_migrate_prefix_cannot_target_other_plugin_table(two_plugins):
    """表名前缀强制按插件 id，防止插件写到其他插件的表。"""
    assert two_plugins['a'].table_prefix() == 'plugin_alpha_plugin_'

    with pytest.raises(Exception):
        two_plugins['a'].migrate(['CREATE TABLE plugin_beta_plugin_data (id INTEGER)'])
