"""SSE 事件流测试（设计文档 6.4 / 13.1）。"""

import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import job_store, jobs
from core.plugins.errors import PluginSseLimitError


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(jobs, 'SSE_POLL_INTERVAL_SECONDS', 0.01)
    monkeypatch.setattr(jobs, 'SSE_HEARTBEAT_INTERVAL_SECONDS', 0.05)
    jobs.reset_for_tests()
    yield {'db': tmp_path / 'jobs.db'}
    jobs.reset_for_tests()


def _register_handler(plugin_id='demo-plugin', job_type='demo.echo'):
    def handler(ctx):
        for item in ctx.items:
            ctx.report(item['key'], status='done', result={'echo': item['key']})

    jobs.register_job_handler(plugin_id, job_type, handler)


def _completed_run(items=('a', 'b')):
    _register_handler()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', list(items))
    jobs._process_pending_jobs()
    return run_id


def _collect(response, *, limit=None):
    chunks = []
    for chunk in response.response:
        chunks.append(chunk)
        if limit is not None and len(chunks) >= limit:
            break
    return ''.join(chunks)


def _parse_frames(text):
    """把 SSE 文本解析成 `[{id, event, data}]`（忽略注释行）。"""
    frames = []
    for block in text.split('\n\n'):
        block = block.strip('\n')
        if not block:
            continue
        frame = {'id': None, 'event': '', 'data': []}
        is_comment = True
        for line in block.split('\n'):
            if line.startswith(':'):
                continue
            is_comment = False
            if line.startswith('id:'):
                frame['id'] = int(line[3:].strip())
            elif line.startswith('event:'):
                frame['event'] = line[6:].strip()
            elif line.startswith('data:'):
                frame['data'].append(line[5:].lstrip())
        if not is_comment:
            frames.append(frame)
    return frames


# ------------------------------------------------------------------ 帧格式


def test_snapshot_is_first_frame_with_seq_zero(job_env):
    run_id = _completed_run()

    text = _collect(jobs.stream_job_events(run_id))
    frames = _parse_frames(text)

    assert frames[0]['event'] == 'snapshot'
    assert frames[0]['id'] == 0

    import json

    snapshot = json.loads('\n'.join(frames[0]['data']))
    assert snapshot['run_id'] == run_id
    assert snapshot['status'] == 'completed'
    assert snapshot['total'] == 2
    assert snapshot['completed'] == 2


def test_item_frames_carry_id_and_event(job_env):
    run_id = _completed_run()

    frames = _parse_frames(_collect(jobs.stream_job_events(run_id)))
    item_frames = [frame for frame in frames if frame['event'] == 'item']

    assert len(item_frames) == 2
    assert all(frame['id'] and frame['id'] > 0 for frame in item_frames)

    import json

    payloads = [json.loads('\n'.join(frame['data'])) for frame in item_frames]
    assert [payload['item_key'] for payload in payloads] == ['a', 'b']
    assert payloads[0]['status'] == 'done'
    assert payloads[0]['result'] == {'echo': 'a'}


def test_done_frame_terminates_stream(job_env):
    run_id = _completed_run()

    frames = _parse_frames(_collect(jobs.stream_job_events(run_id)))

    assert frames[-1]['event'] == 'done'

    import json

    payload = json.loads('\n'.join(frames[-1]['data']))
    assert payload['status'] == 'completed'
    assert payload['completed'] == 2
    assert payload['failed'] == 0


def test_sse_response_headers(job_env):
    run_id = _completed_run()

    response = jobs.stream_job_events(run_id)

    assert response.mimetype == 'text/event-stream'
    assert response.headers['Cache-Control'] == 'no-cache'
    assert response.headers['X-Accel-Buffering'] == 'no'
    assert response.headers['Connection'] == 'keep-alive'

    _collect(response)


def test_unknown_run_returns_done_not_found(job_env):
    text = _collect(jobs.stream_job_events('missing-run-id'))

    frames = _parse_frames(text)

    assert frames and frames[0]['event'] == 'done'
    assert 'job_not_found' in text


def test_snapshot_is_not_persisted(job_env):
    run_id = _completed_run()

    _collect(jobs.stream_job_events(run_id))

    conn = job_store.connect(ensure_schema=True)
    try:
        rows = conn.execute(
            'SELECT seq, type FROM plugin_job_events WHERE run_id = ? ORDER BY seq', (run_id,),
        ).fetchall()
    finally:
        conn.close()

    assert all(row['type'] != 'snapshot' for row in rows)
    assert min(row['seq'] for row in rows) >= 1


# ------------------------------------------------------------------ 续传


def test_last_event_id_resumes_stream(job_env):
    run_id = _completed_run()

    text = _collect(jobs.stream_job_events(run_id, last_event_id=3))
    frames = _parse_frames(text)

    import json

    # 首帧永远是现场合成的 snapshot（id 固定 0，不代表事件游标）
    assert frames[0]['event'] == 'snapshot'
    assert frames[0]['id'] == 0
    assert json.loads('\n'.join(frames[0]['data']))['run_id'] == run_id

    # seq <= 3 的事件已消费，不再回放：先补发持久化的 done 事件（seq=4），
    # 再发端点现场合成的 done 终帧（seq = last_seq + 1）
    replay_ids = [frame['id'] for frame in frames[1:]]
    assert replay_ids == [4, 5]
    assert [frame['event'] for frame in frames[1:]] == ['done', 'done']


def test_last_event_id_beyond_tail_still_terminates(job_env):
    run_id = _completed_run()

    frames = _parse_frames(_collect(jobs.stream_job_events(run_id, last_event_id=99)))

    assert [frame['event'] for frame in frames] == ['snapshot', 'done']


def test_heartbeat_is_emitted_for_running_job(job_env):
    _register_handler()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    text = _collect(jobs.stream_job_events(run_id), limit=3)

    assert ': heartbeat' in text


def test_heartbeat_frames_have_no_id(job_env):
    _register_handler()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    text = _collect(jobs.stream_job_events(run_id), limit=3)

    heartbeat_block = next(
        block for block in text.split('\n\n') if block.strip().startswith(': heartbeat')
    )
    assert not re.search(r'^id:', heartbeat_block, re.MULTILINE)


# ------------------------------------------------------------------ 连接上限与清理


def test_connection_limit_per_run(job_env):
    run_id = _completed_run()

    for _ in range(jobs.SSE_MAX_CONNECTIONS_PER_RUN):
        assert jobs._acquire_sse_slot(run_id) is True

    with pytest.raises(PluginSseLimitError):
        jobs.stream_job_events(run_id)

    stats = jobs.sse_connection_stats()
    for _ in range(jobs.SSE_MAX_CONNECTIONS_PER_RUN):
        jobs._release_sse_slot(run_id)
    assert jobs.sse_connection_stats()['total'] == stats['total'] - jobs.SSE_MAX_CONNECTIONS_PER_RUN


def test_connection_limit_is_global(job_env):
    for index in range(jobs.SSE_MAX_CONNECTIONS_TOTAL):
        assert jobs._acquire_sse_slot(f'run-{index}') is True

    with pytest.raises(PluginSseLimitError):
        jobs.stream_job_events('run-extra')

    for index in range(jobs.SSE_MAX_CONNECTIONS_TOTAL):
        jobs._release_sse_slot(f'run-{index}')


def test_slot_is_released_when_client_disconnects(job_env):
    _register_handler()
    run_id = jobs.submit_job('demo-plugin', 'demo.echo', ['a'])

    response = jobs.stream_job_events(run_id)
    assert jobs.sse_connection_stats()['total'] == 1

    generator = response.response
    next(generator)
    generator.close()

    assert jobs.sse_connection_stats()['total'] == 0


def test_slot_is_released_after_stream_completes(job_env):
    run_id = _completed_run()

    _collect(jobs.stream_job_events(run_id))

    assert jobs.sse_connection_stats() == {'total': 0, 'per_run': {}}


def test_multiline_data_is_split_into_data_lines(job_env):
    """多行 JSON 必须拆成多行 data:，否则 EventSource 解析会截断。"""
    _register_handler('demo-plugin', 'demo.long')
    run_id = jobs.submit_job('demo-plugin', 'demo.long', ['a'])
    jobs._process_pending_jobs()

    text = _collect(jobs.stream_job_events(run_id))

    for block in text.split('\n\n'):
        if 'event: item' not in block:
            continue
        data_lines = [line for line in block.split('\n') if line.startswith('data:')]
        assert len(data_lines) >= 1
        # 块内不应出现未加前缀的裸 JSON 行
        for line in block.split('\n'):
            if line and not line.startswith(('id:', 'event:', 'data:', ':')):
                raise AssertionError(f'unprefixed line: {line}')
