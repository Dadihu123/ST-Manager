"""G2 顺序保证：提交顺序、seq 与断点续跑顺序（设计文档 13.1）。"""

import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import job_store, jobs


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    jobs.reset_for_tests()
    yield
    jobs.reset_for_tests()


def _register(handler, job_type='demo.echo', plugin_id='demo-plugin'):
    jobs.register_job_handler(plugin_id, job_type, handler)


def _items(conn, run_id):
    return job_store.list_items(conn, run_id)


def test_item_seq_follows_submission_order(job_env):
    seen = []

    def handler(ctx):
        for item in ctx.items:
            seen.append(item['key'])
            ctx.report(item['key'], status='done')

    _register(handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c'])

    conn = job_store.connect(ensure_schema=True)
    try:
        items = _items(conn, run_id)
    finally:
        conn.close()

    assert [item['seq'] for item in items] == [0, 1, 2]
    assert [item['key'] for item in items] == ['a', 'b', 'c']

    jobs._process_pending_jobs()
    assert seen == ['a', 'b', 'c']


def test_created_at_is_monotonic_within_a_job(job_env):
    _register(lambda ctx: [ctx.report(item['key'], status='done') for item in ctx.items])
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c', 'd'])

    conn = job_store.connect(ensure_schema=True)
    try:
        items = _items(conn, run_id)
    finally:
        conn.close()

    created = [item['created_at'] for item in items]
    assert created == sorted(created)
    assert len(set(created)) == len(created)


def test_dict_items_keep_submission_order_and_payload(job_env):
    _register(lambda ctx: [ctx.report(item['key'], status='done') for item in ctx.items])

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', [
        {'key': 'third', 'index': 3},
        {'key': 'first', 'index': 1},
        {'key': 'second', 'index': 2},
    ])

    conn = job_store.connect(ensure_schema=True)
    try:
        items = _items(conn, run_id)
    finally:
        conn.close()

    assert [item['key'] for item in items] == ['third', 'first', 'second']
    assert [item['payload']['index'] for item in items] == [3, 1, 2]


def test_duplicate_key_keeps_first_position(job_env):
    _register(lambda ctx: [ctx.report(item['key'], status='done') for item in ctx.items])

    run_id = jobs.submit_job('demo-plugin', 'demo.echo', [
        {'key': 'a', 'v': 1},
        {'key': 'b', 'v': 2},
        {'key': 'a', 'v': 3},
    ])

    conn = job_store.connect(ensure_schema=True)
    try:
        items = _items(conn, run_id)
    finally:
        conn.close()

    assert [item['key'] for item in items] == ['a', 'b']
    assert [item['seq'] for item in items] == [0, 1]
    assert items[0]['payload'] == {'v': 3}


def test_retry_preserves_seq_and_only_reprocesses_failed(job_env):
    attempts = {'first': True}
    processed = []

    def handler(ctx):
        for item in ctx.items:
            key = item['key']
            processed.append(key)
            if key == 'b' and attempts['first']:
                ctx.report(key, status='failed', error='transient')
            else:
                ctx.report(key, status='done')

    _register(handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c'])
    jobs._process_pending_jobs()
    attempts['first'] = False

    jobs.retry_job(run_id, only_failed=True)
    jobs._process_pending_jobs()

    assert processed == ['a', 'b', 'c', 'b']

    conn = job_store.connect(ensure_schema=True)
    try:
        items = _items(conn, run_id)
    finally:
        conn.close()

    assert [item['seq'] for item in items] == [0, 1, 2]
    assert [item['key'] for item in items] == ['a', 'b', 'c']


def test_pending_items_are_processed_in_seq_order_after_resume(job_env):
    order = []

    def handler(ctx):
        for item in ctx.items:
            order.append(item['key'])
            ctx.report(item['key'], status='done')

    _register(handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['x1', 'x2', 'x3'])

    # 模拟「跑到一半崩溃」：只剩最后一个 pending
    conn = job_store.connect(ensure_schema=True)
    try:
        for key in ('x1', 'x2'):
            job_store.update_item(conn, run_id, key, status='done')
    finally:
        conn.close()

    jobs._process_pending_jobs()

    assert order == ['x3']


def test_job_items_are_paginated_by_seq(job_env):
    _register(lambda ctx: [ctx.report(item['key'], status='done') for item in ctx.items])
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a', 'b', 'c', 'd'])

    conn = job_store.connect(ensure_schema=True)
    try:
        first_page = job_store.list_items(conn, run_id, limit=2, offset=0)
        second_page = job_store.list_items(conn, run_id, limit=2, offset=2)
        total = job_store.count_items(conn, run_id)
    finally:
        conn.close()

    assert [item['key'] for item in first_page] == ['a', 'b']
    assert [item['key'] for item in second_page] == ['c', 'd']
    assert total == 4


def test_item_attempt_increments_on_report(job_env):
    _register(lambda ctx: [ctx.report(item['key'], status='done') for item in ctx.items])
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])
    jobs._process_pending_jobs()

    conn = job_store.connect(ensure_schema=True)
    try:
        item = job_store.get_item(conn, run_id, 'a')
    finally:
        conn.close()

    assert item['attempt'] == 1
    assert item['updated_at'] >= item['created_at']


def test_large_item_result_is_truncated(job_env):
    def handler(ctx):
        for item in ctx.items:
            ctx.report(item['key'], status='done', result={'blob': 'x' * (job_store.MAX_ITEM_RESULT_BYTES * 2)})

    _register(handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])
    jobs._process_pending_jobs()

    conn = job_store.connect(ensure_schema=True)
    try:
        item = job_store.get_item(conn, run_id, 'a')
    finally:
        conn.close()

    assert item['result'].get('_truncated') is True
