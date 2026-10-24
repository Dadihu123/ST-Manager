"""插件作业系统测试（设计文档第 6 部分 / 13.1）。

覆盖：创建 / 认领 / 进度落库 / 协作式取消 / 暂停恢复 / 重试 / 崩溃恢复 /
单插件并发上限 / 同插件同类型串行化。
"""

import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import job_store, jobs
from core.plugins.errors import (
    PluginJobDuplicateError,
    PluginJobError,
    PluginJobNotFoundError,
    PluginJobStateError,
)


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    jobs.reset_for_tests()
    yield {'db': tmp_path / 'jobs.db'}
    jobs.reset_for_tests()


def _register_echo(plugin_id='demo-plugin', job_type='demo.echo', *, delay=0.0, fail_keys=()):
    def handler(ctx):
        for item in ctx.items:
            if ctx.should_cancel():
                return
            if delay:
                time.sleep(delay)
            key = item['key']
            if key in fail_keys:
                ctx.report(key, status='failed', error='synthetic failure')
            else:
                ctx.report(key, status='done', result={'echo': key})
        ctx.set_message('全部完成')

    jobs.register_job_handler(plugin_id, job_type, handler)
    return handler


def _run_one(run_id):
    jobs._process_pending_jobs()
    return jobs.get_job_detail(run_id)


# ------------------------------------------------------------------ 提交


def test_submit_job_creates_queued_job(job_env):
    _register_echo()

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b'], {'note': 'x'})

    detail = jobs.get_job_detail(run_id)
    assert detail['status'] == 'queued'
    assert detail['total'] == 2
    assert detail['payload'] == {'note': 'x'}
    assert [item['key'] for item in detail['items']] == ['a', 'b']


def test_submit_job_requires_registered_handler(job_env):
    with pytest.raises(PluginJobError, match='未注册'):
        jobs.submit_job('demo-plugin', 'missing.type', ['a'])


def test_submit_job_rejects_empty_items(job_env):
    _register_echo()

    with pytest.raises(PluginJobError, match='items'):
        jobs.submit_job('demo-plugin', 'demo.echo', [])


def test_submit_job_rejects_too_many_items(job_env, monkeypatch):
    _register_echo()
    monkeypatch.setattr(jobs, 'MAX_ITEMS_PER_RUN', 2)

    with pytest.raises(PluginJobError):
        jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c'])


def test_same_job_type_cannot_run_concurrently(job_env):
    _register_echo()
    jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    with pytest.raises(PluginJobDuplicateError):
        jobs.submit_job('demo-plugin', 'demo.echo', ['b'])


def test_different_job_types_can_queue_together(job_env):
    _register_echo(job_type='demo.echo')
    _register_echo(job_type='demo.other')

    first = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])
    second = jobs.submit_job('demo-plugin', 'demo.other', ['b'])

    assert first != second
    assert jobs.list_plugin_jobs('demo-plugin')['total'] == 2


def test_normalize_items_supports_dicts_and_deduplicates(job_env):
    _register_echo()

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', [
        {'key': 'a', 'model': 'x'},
        {'key': 'b'},
        {'key': 'a', 'model': 'y'},
    ])

    detail = jobs.get_job_detail(run_id)
    assert [item['key'] for item in detail['items']] == ['a', 'b']
    assert detail['items'][0]['payload'] == {'model': 'y'}


# ------------------------------------------------------------------ 执行与进度


def test_worker_completes_job_and_records_progress(job_env):
    _register_echo()

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c'])
    detail = _run_one(run_id)

    assert detail['status'] == 'completed'
    assert (detail['completed'], detail['failed'], detail['skipped']) == (3, 0, 0)
    assert detail['message'] == '全部完成'
    assert all(item['status'] == 'done' for item in detail['items'])
    assert detail['finished_at'] > 0


def test_failed_items_are_counted_and_reported(job_env):
    _register_echo(fail_keys={'b'})

    detail = _run_one(jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b']))

    assert detail['status'] == 'completed'
    assert (detail['completed'], detail['failed']) == (1, 1)
    statuses = {item['key']: item['status'] for item in detail['items']}
    assert statuses == {'a': 'done', 'b': 'failed'}
    failed_item = next(item for item in detail['items'] if item['key'] == 'b')
    assert failed_item['error'] == 'synthetic failure'


def test_handler_exception_marks_job_failed(job_env):
    def boom(ctx):
        raise RuntimeError('handler exploded')

    jobs.register_job_handler('demo-plugin', 'demo.boom', boom)

    detail = _run_one(jobs.submit_job('demo-plugin', 'demo.boom', ['a']))

    assert detail['status'] == 'failed'
    assert 'handler exploded' in detail['error']


def test_unregistered_handler_on_execution_marks_failed(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    jobs.unregister_plugin_handlers('demo-plugin')
    detail = _run_one(run_id)

    assert detail['status'] == 'failed'
    assert '未注册' in detail['error']


def test_report_rejects_unknown_status(job_env):
    captured = {}

    def handler(ctx):
        try:
            ctx.report('a', status='bogus')
        except PluginJobError as exc:
            captured['error'] = str(exc)

    jobs.register_job_handler('demo-plugin', 'demo.bad', handler)
    _run_one(jobs.submit_job('demo-plugin', 'demo.bad', ['a']))

    assert 'bogus' in captured.get('error', '')


def test_job_without_pending_items_completes_immediately(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    # 先手动把条目置为 done，模拟断点续跑无剩余项
    conn = job_store.connect(ensure_schema=True)
    try:
        job_store.update_item(conn, run_id, 'a', status='done')
    finally:
        conn.close()

    detail = _run_one(run_id)
    assert detail['status'] == 'completed'


def test_save_and_load_state(job_env):
    captured = {}

    def handler(ctx):
        ctx.save_state({'cursor': 7})
        captured['state'] = ctx.load_state()
        for item in ctx.items:
            ctx.report(item['key'], status='done')

    jobs.register_job_handler('demo-plugin', 'demo.state', handler)
    _run_one(jobs.submit_job('demo-plugin', 'demo.state', ['a']))

    assert captured['state'] == {'cursor': 7}


# ------------------------------------------------------------------ 取消 / 暂停 / 恢复


def test_cancel_marks_job_cancelled(job_env):
    _register_echo()

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    assert jobs.cancel_job(run_id) is True
    assert jobs.get_job_detail(run_id)['status'] == 'cancelled'


def test_cancel_interrupts_running_handler(job_env):
    processed = []

    def handler(ctx):
        for item in ctx.items:
            if ctx.should_cancel():
                return
            processed.append(item['key'])
            ctx.report(item['key'], status='done')

    jobs.register_job_handler('demo-plugin', 'demo.long', handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.long', ['a', 'b'])

    conn = job_store.connect(ensure_schema=True)
    try:
        job_store.update_job(conn, run_id, status='running')
    finally:
        conn.close()

    # 模拟运行中被取消：先取消再执行，handler 第一项就该退出
    jobs.cancel_job(run_id)
    conn = job_store.connect(ensure_schema=True)
    try:
        job = job_store.get_job(conn, run_id)
    finally:
        conn.close()

    jobs._run_job(job)

    assert processed == []
    assert jobs.get_job_detail(run_id)['status'] == 'cancelled'


def test_cancel_rejects_terminal_job(job_env):
    _register_echo()
    detail = _run_one(jobs.submit_job('demo-plugin', 'demo.echo', ['a']))

    with pytest.raises(PluginJobStateError):
        jobs.cancel_job(detail['run_id'])


def test_cancel_unknown_job_raises(job_env):
    with pytest.raises(PluginJobNotFoundError):
        jobs.cancel_job('missing-run')


def test_pause_and_resume(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    assert jobs.pause_job(run_id) is True
    assert jobs.get_job_detail(run_id)['status'] == 'paused'

    assert jobs.resume_job(run_id) is True
    assert jobs.get_job_detail(run_id)['status'] == 'queued'

    assert _run_one(run_id)['status'] == 'completed'


def test_resume_rejects_non_paused_job(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    with pytest.raises(PluginJobStateError):
        jobs.resume_job(run_id)


def test_pause_rejects_completed_job(job_env):
    _register_echo()
    detail = _run_one(jobs.submit_job('demo-plugin', 'demo.echo', ['a']))

    with pytest.raises(PluginJobStateError):
        jobs.pause_job(detail['run_id'])


def test_paused_job_is_not_claimed(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])
    jobs.pause_job(run_id)

    jobs._process_pending_jobs()

    assert jobs.get_job_detail(run_id)['status'] == 'paused'


# ------------------------------------------------------------------ 重试


def test_retry_only_failed_items(job_env):
    attempts = {'count': 0}

    def handler(ctx):
        attempts['count'] += 1
        for item in ctx.items:
            key = item['key']
            if key == 'b' and attempts['count'] == 1:
                ctx.report(key, status='failed', error='first attempt')
            else:
                ctx.report(key, status='done', result={'echo': key})

    jobs.register_job_handler('demo-plugin', 'demo.retry', handler)
    detail = _run_one(jobs.submit_job('demo-plugin', 'demo.retry', ['a', 'b']))
    assert (detail['completed'], detail['failed']) == (1, 1)

    jobs.retry_job(detail['run_id'], only_failed=True)
    after = _run_one(detail['run_id'])

    assert after['status'] == 'completed'
    assert (after['completed'], after['failed']) == (2, 0)
    assert attempts['count'] == 2
    statuses = {item['key']: item['status'] for item in after['items']}
    assert statuses == {'a': 'done', 'b': 'done'}


def test_retry_all_items_resets_everything(job_env):
    counter = {'count': 0}

    def handler(ctx):
        for item in ctx.items:
            counter['count'] += 1
            ctx.report(item['key'], status='done')

    jobs.register_job_handler('demo-plugin', 'demo.count', handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.count', ['a', 'b'])
    _run_one(run_id)

    jobs.retry_job(run_id, only_failed=False)
    _run_one(run_id)

    assert counter['count'] == 4


def test_retry_rejects_running_job(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    with pytest.raises(PluginJobStateError):
        jobs.retry_job(run_id)


# ------------------------------------------------------------------ 崩溃恢复与清理


def test_abort_stale_jobs_on_startup(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    conn = job_store.connect(ensure_schema=True)
    try:
        job_store.update_job(conn, run_id, status='running')
        aborted = job_store.abort_stale_jobs(conn)
        detail = job_store.get_job(conn, run_id)
    finally:
        conn.close()

    assert aborted == 1
    assert detail['status'] == 'aborted'
    assert '重启' in detail['error']


def test_abort_does_not_touch_paused_jobs(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])
    jobs.pause_job(run_id)

    conn = job_store.connect(ensure_schema=True)
    try:
        job_store.abort_stale_jobs(conn)
        detail = job_store.get_job(conn, run_id)
    finally:
        conn.close()

    assert detail['status'] == 'paused'


def test_prune_keeps_recent_terminal_jobs(job_env, monkeypatch):
    _register_echo()
    monkeypatch.setattr(job_store, 'PLUGIN_JOB_DONE_RETENTION', 2)
    monkeypatch.setattr(job_store, 'PLUGIN_JOB_FAILED_RETENTION', 1)

    run_ids = []
    for index in range(4):
        job_type = f'demo.echo{index}'
        _register_echo(job_type=job_type)
        run_ids.append(jobs.submit_job('demo-plugin', job_type, [f'item-{index}']))
        _run_one(run_ids[-1])

    conn = job_store.connect(ensure_schema=True)
    try:
        remaining = {row['run_id'] for row in conn.execute('SELECT run_id FROM plugin_jobs')}
        event_runs = {row['run_id'] for row in conn.execute('SELECT DISTINCT run_id FROM plugin_job_events')}
        item_runs = {row['run_id'] for row in conn.execute('SELECT DISTINCT run_id FROM plugin_job_items')}
    finally:
        conn.close()

    assert len(remaining) == 2
    assert remaining == event_runs == item_runs
    assert set(run_ids[-2:]) == remaining


def test_prune_never_removes_active_jobs(job_env, monkeypatch):
    _register_echo()
    monkeypatch.setattr(job_store, 'PLUGIN_JOB_DONE_RETENTION', 0)

    running_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    conn = job_store.connect(ensure_schema=True)
    try:
        job_store.prune_terminal_jobs(conn)
        assert job_store.get_job(conn, running_id) is not None
    finally:
        conn.close()


# ------------------------------------------------------------------ 认领与限流


def test_claim_limits_jobs_per_plugin(job_env):
    for index in range(4):
        _register_echo(job_type=f'demo.echo{index}')
        jobs.submit_job('demo-plugin', f'demo.echo{index}', [f'item-{index}'])

    conn = job_store.connect(ensure_schema=True)
    try:
        claimed = job_store.claim_runnable_jobs(conn, limit=4, max_per_plugin=2)
    finally:
        conn.close()

    assert len(claimed) == 2


def test_claim_spreads_across_plugins(job_env):
    for plugin_id in ('plugin-a', 'plugin-b'):
        for index in range(3):
            _register_echo(plugin_id=plugin_id, job_type=f'demo.echo{index}')
            jobs.submit_job(plugin_id, f'demo.echo{index}', ['x'])

    conn = job_store.connect(ensure_schema=True)
    try:
        claimed = job_store.claim_runnable_jobs(conn, limit=4, max_per_plugin=2)
    finally:
        conn.close()

    plugins = [job['plugin_id'] for job in claimed]
    assert len(claimed) == 4
    assert plugins.count('plugin-a') == 2
    assert plugins.count('plugin-b') == 2


def test_claim_uses_own_token_column(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    conn = job_store.connect(ensure_schema=True)
    try:
        claimed = job_store.claim_runnable_jobs(conn, limit=1, max_per_plugin=1)
        row = conn.execute('SELECT claim_token, error FROM plugin_jobs WHERE run_id = ?', (run_id,)).fetchone()
    finally:
        conn.close()

    assert len(claimed) == 1
    assert row['claim_token'].startswith('claim:')
    assert row['error'] == ''


def test_second_claim_returns_nothing(job_env):
    _register_echo()
    jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    conn = job_store.connect(ensure_schema=True)
    try:
        assert len(job_store.claim_runnable_jobs(conn, limit=4, max_per_plugin=2)) == 1
        assert job_store.claim_runnable_jobs(conn, limit=4, max_per_plugin=2) == []
    finally:
        conn.close()


def test_has_active_job(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    conn = job_store.connect(ensure_schema=True)
    try:
        assert job_store.has_active_job(conn, 'demo-plugin') is True
        job_store.update_job(conn, run_id, status='completed')
        assert job_store.has_active_job(conn, 'demo-plugin') is False
    finally:
        conn.close()


# ------------------------------------------------------------------ 审批与日志


def test_review_item_resolves_awaiting_review(job_env):
    def handler(ctx):
        ctx.report('a', status='awaiting_review', result={'suggestion': 'x'})

    jobs.register_job_handler('demo-plugin', 'demo.review', handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.review', ['a'])
    _run_one(run_id)

    assert jobs.review_item(run_id, 'a', status='done', result={'applied': True}) is True

    detail = jobs.get_job_detail(run_id)
    assert detail['items'][0]['status'] == 'done'
    assert detail['items'][0]['result'] == {'applied': True}
    assert detail['completed'] == 1


def test_review_item_keeps_pending_result_when_omitted(job_env):
    """审批只发 `{status}` 时不能把 `awaiting_review` 的候选 result 清空。"""
    def handler(ctx):
        ctx.report(ctx.items[0]['key'], status='awaiting_review', result={'suggestion': 'x'})

    jobs.register_job_handler('demo-plugin', 'demo.review', handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.review', ['a'])
    _run_one(run_id)

    assert jobs.review_item(run_id, 'a', status='done') is True

    detail = jobs.get_job_detail(run_id)
    assert detail['items'][0]['status'] == 'done'
    assert detail['items'][0]['result'] == {'suggestion': 'x'}

    conn = job_store.connect(ensure_schema=True)
    try:
        events = job_store.read_events(conn, run_id)
    finally:
        conn.close()
    item_events = [event for event in events if event['type'] == 'item']
    # SSE 事件里回传的 result 必须与落库一致
    assert item_events[-1]['data']['result'] == {'suggestion': 'x'}


def test_review_item_rejects_unknown_item(job_env):
    _register_echo()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    with pytest.raises(PluginJobNotFoundError):
        jobs.review_item(run_id, 'missing', status='done')


def test_append_log_event_ignores_unknown_run(job_env):
    jobs.append_log_event('missing-run', 'info', 'hello')


def test_list_plugin_jobs_pagination(job_env):
    for index in range(3):
        _register_echo(job_type=f'demo.echo{index}')
        jobs.submit_job('demo-plugin', f'demo.echo{index}', ['x'])

    page = jobs.list_plugin_jobs('demo-plugin', limit=2, offset=0)

    assert page['total'] == 3
    assert len(page['items']) == 2
