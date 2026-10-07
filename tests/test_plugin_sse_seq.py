"""G3 seq 语义：作业内自增、SSE id 对齐、snapshot 不落表（设计文档 13.1）。"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import job_store, jobs


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(jobs, 'SSE_POLL_INTERVAL_SECONDS', 0.01)
    monkeypatch.setattr(jobs, 'SSE_HEARTBEAT_INTERVAL_SECONDS', 0.05)
    jobs.reset_for_tests()
    yield
    jobs.reset_for_tests()


def _register(job_type='demo.echo'):
    def handler(ctx):
        for item in ctx.items:
            ctx.report(item['key'], status='done', result={'echo': item['key']})

    jobs.register_job_handler('demo-plugin', job_type, handler)


def _run(items, job_type='demo.echo'):
    _register(job_type)
    run_id = jobs.submit_job('demo-plugin', job_type, list(items))
    jobs._process_pending_jobs()
    return run_id


def _events(run_id):
    conn = job_store.connect(ensure_schema=True)
    try:
        return job_store.read_events(conn, run_id)
    finally:
        conn.close()


def _collect(response):
    return ''.join(list(response.response))


def _frames(text):
    result = []
    for block in text.split('\n\n'):
        block = block.strip('\n')
        if not block or block.startswith(':'):
            continue
        frame = {'id': None, 'event': '', 'data': []}
        for line in block.split('\n'):
            if line.startswith('id:'):
                frame['id'] = int(line[3:].strip())
            elif line.startswith('event:'):
                frame['event'] = line[6:].strip()
            elif line.startswith('data:'):
                frame['data'].append(line[5:].lstrip())
        result.append(frame)
    return result


def test_seq_is_per_job_not_global(job_env):
    first = _run(['a'], job_type='demo.echo1')
    second = _run(['b'], job_type='demo.echo2')

    first_seq = [event['seq'] for event in _events(first)]
    second_seq = [event['seq'] for event in _events(second)]

    assert first_seq == [1, 2, 3]
    assert second_seq == [1, 2, 3]


def test_seq_starts_at_one_and_is_contiguous(job_env):
    run_id = _run(['a', 'b', 'c'])

    seqs = [event['seq'] for event in _events(run_id)]

    assert seqs == list(range(1, len(seqs) + 1))


def test_event_types_are_ordered_log_items_done(job_env):
    run_id = _run(['a', 'b'])

    types = [event['type'] for event in _events(run_id)]

    assert types == ['log', 'item', 'item', 'done']


def test_sse_id_equals_event_seq(job_env):
    run_id = _run(['a', 'b'])

    frames = _frames(_collect(jobs.stream_job_events(run_id)))
    stored = _events(run_id)

    # 第一帧是现场合成的 snapshot（id=0），其后各帧的 id 与库内 seq 一一对应
    assert frames[0]['event'] == 'snapshot'

    event_frames = [frame for frame in frames[1:] if frame['event'] == 'item']
    assert [frame['id'] for frame in event_frames] == [
        event['seq'] for event in stored if event['type'] == 'item'
    ]


def test_snapshot_seq_is_zero_and_not_stored(job_env):
    run_id = _run(['a'])

    frames = _frames(_collect(jobs.stream_job_events(run_id)))

    assert frames[0]['id'] == 0
    assert json.loads('\n'.join(frames[0]['data']))['status'] == 'completed'

    stored_types = [event['type'] for event in _events(run_id)]
    assert 'snapshot' not in stored_types

    conn = job_store.connect(ensure_schema=True)
    try:
        zero_seq = conn.execute(
            'SELECT COUNT(*) AS total FROM plugin_job_events WHERE run_id = ? AND seq = 0', (run_id,),
        ).fetchone()['total']
    finally:
        conn.close()

    assert zero_seq == 0


def test_latest_event_seq_matches_last_event(job_env):
    run_id = _run(['a', 'b'])

    conn = job_store.connect(ensure_schema=True)
    try:
        latest = job_store.latest_event_seq(conn, run_id)
    finally:
        conn.close()

    assert latest == _events(run_id)[-1]['seq']


def test_read_events_after_seq_filters_correctly(job_env):
    run_id = _run(['a', 'b'])

    conn = job_store.connect(ensure_schema=True)
    try:
        all_events = job_store.read_events(conn, run_id, after_seq=0)
        tail = job_store.read_events(conn, run_id, after_seq=2)
    finally:
        conn.close()

    assert [event['seq'] for event in all_events] == [1, 2, 3, 4]
    assert [event['seq'] for event in tail] == [3, 4]


def test_resume_from_last_event_id_skips_consumed_frames(job_env):
    run_id = _run(['a'])

    frames = _frames(_collect(jobs.stream_job_events(run_id, last_event_id=2)))

    assert frames[0]['event'] == 'snapshot'
    assert [frame['id'] for frame in frames[1:]] == [3, 4]


def test_seq_continues_after_retry(job_env):
    attempts = {'first': True}

    def handler(ctx):
        for item in ctx.items:
            key = item['key']
            if attempts['first']:
                ctx.report(key, status='failed', error='transient')
            else:
                ctx.report(key, status='done')

    jobs.register_job_handler('demo-plugin', 'demo.retry', handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.retry', ['a'])
    jobs._process_pending_jobs()
    attempts['first'] = False

    before = [event['seq'] for event in _events(run_id)]

    jobs.retry_job(run_id, only_failed=True)
    jobs._process_pending_jobs()

    after = [event['seq'] for event in _events(run_id)]

    assert after[:len(before)] == before
    assert after == list(range(1, len(after) + 1))
