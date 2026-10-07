"""前端 SSE 订阅与轮询降级契约测试（设计文档 6.4.4 / 13.2）。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def test_subscribe_job_prefers_event_source():
    source = read_source('static/js/pluginHost.js')

    assert 'typeof EventSource === "function"' in source
    assert 'new EventSource(url)' in source
    assert '/events' in source


def test_subscribe_job_handles_all_event_types():
    source = read_source('static/js/pluginHost.js')

    assert '["snapshot", "item", "log", "done"]' in source


def test_subscribe_job_falls_back_to_polling():
    source = read_source('static/js/pluginHost.js')

    assert 'startPolling' in source
    assert 'notify("error"' in source
    assert 'setTimeout(tick, 4000)' in source


def test_subscribe_job_stops_on_terminal_status():
    source = read_source('static/js/pluginHost.js')

    assert '"completed", "failed", "cancelled", "aborted"' in source
    assert 'stop();' in source


def test_backend_sse_frames_carry_id_and_event():
    source = read_source('core/plugins/jobs.py')

    assert "f'id: {int(seq)}'" in source
    assert "f'event: {event}'" in source
    assert ': heartbeat\\n\\n' in source


def test_backend_snapshot_is_not_persisted():
    source = read_source('core/plugins/jobs.py')

    assert "'snapshot'" in source
    # snapshot 由端点现场合成：分派逻辑里只读作业行，不写事件表
    snapshot_section = source.split("yield _sse_frame('snapshot'", 1)[1].split('while True:', 1)[0]
    assert 'append_event' not in snapshot_section
