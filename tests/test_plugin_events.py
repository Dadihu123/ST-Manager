"""核心事件流测试（设计文档 6.7 / 13.1）。

背景：后端在 9 处核心流程末尾 `hooks.emit(...)` 派发核心事件，但前端
`api.on()` 只做 `window.addEventListener`，因此 `api.on('card.updated', h)`
**在浏览器里永远不会被调用**；「扫描完成」「索引重建完毕」这类无 UI 触发的变更
前端更是无从得知。本文件覆盖新增的 `GET /api/plugins/events` SSE 通路。

覆盖的契约：
- 核心事件能到达订阅者
- **插件自定义事件不进这条流**（否则插件 A 的噪声会灌给所有插件）
- 广播**绝不阻塞**核心流程（慢客户端不得拖住 `emit` 的调用方）
- 连接配额上限返回结构化错误，而不是静默挂住
- 断开后清理（连接计数归零）
- 负载形状 `{event, payload, ts}`，且只放 `hooks.emit()` 给出的 payload 原样
"""

import json
import os
import sys
import threading
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import hooks, routes
from core.plugins.errors import PluginSseLimitError


@pytest.fixture(autouse=True)
def _clean_hook_state():
    hooks.reset()
    hooks.reset_event_stream_for_tests()
    yield
    hooks.reset()
    hooks.reset_event_stream_for_tests()


@pytest.fixture
def event_app():
    """极简 Flask app：只挂插件蓝图，用于端点级断言。"""
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app


def _collect(response, *, limit=None):
    """收集 SSE 文本块。

    Flask 测试客户端的流可能给 `str`（`direct_passthrough` 关闭时）也可能是
    `bytes`，两种都归一成 `str`——否则断言会在解码层面失败，与契约无关。
    """
    chunks = []
    for chunk in response.response:
        if isinstance(chunk, bytes):
            chunk = chunk.decode('utf-8', errors='replace')
        chunks.append(chunk)
        if limit is not None and len(chunks) >= limit:
            break
    return ''.join(chunks)


def _parse_frames(text):
    """把 SSE 文本解析成 `[{id, event, data}]`（忽略 `:` 注释帧）。"""
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


def _payloads(text, event_name='core'):
    out = []
    for frame in _parse_frames(text):
        if frame['event'] != event_name:
            continue
        out.append(json.loads('\n'.join(frame['data'])))
    return out


# ------------------------------------------------------------------ 总线层


def test_emit_feeds_event_stream_subscribers():
    """核心事件在 `emit()` 时被投递给事件流订阅者。"""
    bucket = hooks.subscribe_core_events()
    assert bucket is not None

    hooks.emit('card.updated', {'card_id': 'a.json'})

    record = bucket.get_nowait()
    assert record['event'] == 'card.updated'
    assert record['payload'] == {'card_id': 'a.json'}
    assert isinstance(record['ts'], float)


def test_plugin_custom_events_do_not_enter_the_stream():
    """插件自定义事件（`<id>:` 前缀）**不进**这条广播流。

    否则插件 A 的噪声会灌给所有插件，且 N1 对插件间通信的「best-effort、
    不保证顺序」承诺会被这条流误读成强保证。
    """
    bucket = hooks.subscribe_core_events()

    hooks.emit('demo-plugin:something', {'value': 1})

    from queue import Empty

    with pytest.raises(Empty):
        bucket.get_nowait()


def test_publish_ignores_non_core_events():
    """`publish_core_event` 对非核心事件返回 0 投递数（防御性，双保险）。"""
    hooks.subscribe_core_events()

    assert hooks.publish_core_event('demo-plugin:thing', {}) == 0
    assert hooks.publish_core_event('card.updated', {}) == 1


def test_emit_without_subscribers_still_works():
    """零订阅时 `emit` 完全不受影响（既有语义不变）。"""
    seen = []
    hooks.register('card.updated', lambda payload: seen.append(payload), plugin_id='p1')

    hooks.emit('card.updated', {'card_id': 'x'})

    assert seen == [{'card_id': 'x'}]


def test_broadcast_never_blocks_on_a_stalled_client():
    """**核心不变量**：广播是 fire-and-forget，慢客户端不得拖住核心流程。

    构造一个从不读取的订阅者，然后灌满它的缓冲并继续 `emit`——每次 `emit`
    都必须在极短时间内返回（阈值取得很宽松，只排除「被阻塞」这种量级）。
    """
    bucket = hooks.subscribe_core_events()
    assert bucket is not None

    # 灌爆缓冲（订阅者从不 get）
    for index in range(hooks.EVENT_STREAM_QUEUE_SIZE + 50):
        hooks.emit('card.updated', {'card_id': str(index)})

    start = time.monotonic()
    hooks.emit('card.updated', {'card_id': 'after-flood'})
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, f'广播阻塞了核心流程：{elapsed:.3f}s'
    # 缓冲仍是满的（丢弃最旧策略生效），且新事件在队尾
    assert bucket.qsize() == hooks.EVENT_STREAM_QUEUE_SIZE


def test_queue_full_drops_oldest_and_keeps_newest():
    """慢客户端场景保留**最新**事件（新事件比旧事件有用）。"""
    bucket = hooks.subscribe_core_events()

    for index in range(hooks.EVENT_STREAM_QUEUE_SIZE):
        hooks.emit('card.updated', {'card_id': f'old-{index}'})

    hooks.emit('card.updated', {'card_id': 'newest'})

    drained = []
    while not bucket.empty():
        drained.append(bucket.get_nowait()['payload']['card_id'])

    assert 'newest' in drained
    assert 'old-0' not in drained, '缓冲满时必须丢弃最旧事件'
    assert len(drained) == hooks.EVENT_STREAM_QUEUE_SIZE


def test_emit_dispatches_to_handlers_even_when_broadcast_is_muted():
    """广播不可用/无订阅者时，同步 handler 派发照常（两条通路互不影响）。"""
    seen = []
    hooks.register('scan.completed', lambda payload: seen.append(payload), plugin_id='p1')

    hooks.emit('scan.completed', {'scanned': 7})

    assert seen == [{'scanned': 7}]


def test_handler_dispatch_precedes_nothing_critical():
    """handler 抛错仍被吞掉（既有语义 + 广播共存）。"""
    calls = []

    def boom(payload):
        raise RuntimeError('handler failed')

    hooks.register('card.updated', boom, plugin_id='broken')
    hooks.register('card.updated', lambda payload: calls.append('ok'), plugin_id='ok')
    bucket = hooks.subscribe_core_events()

    hooks.emit('card.updated', {'card_id': 'x'})

    assert calls == ['ok']
    assert bucket.get_nowait()['event'] == 'card.updated'


# ------------------------------------------------------------------ 配额


def test_connection_quota_is_enforced(monkeypatch):
    monkeypatch.setattr(hooks, 'EVENT_STREAM_MAX_CONNECTIONS', 2)

    first = hooks.subscribe_core_events()
    second = hooks.subscribe_core_events()
    third = hooks.subscribe_core_events()

    assert first is not None
    assert second is not None
    assert third is None, '超限必须返回 None，由路由层转成结构化错误'


def test_quota_is_released_on_disconnect(monkeypatch):
    monkeypatch.setattr(hooks, 'EVENT_STREAM_MAX_CONNECTIONS', 1)

    first = hooks.subscribe_core_events()
    assert hooks.subscribe_core_events() is None

    hooks.unsubscribe_core_events(first)
    assert hooks.event_stream_stats()['connections'] == 0

    again = hooks.subscribe_core_events()
    assert again is not None, '断开后配额必须释放'


def test_unsubscribe_is_idempotent():
    bucket = hooks.subscribe_core_events()
    hooks.unsubscribe_core_events(bucket)
    hooks.unsubscribe_core_events(bucket)

    assert hooks.event_stream_stats()['connections'] == 0


def test_broadcast_reaches_every_connection():
    """广播是**多点**投递：每个连接都收到同一份事件。"""
    first = hooks.subscribe_core_events()
    second = hooks.subscribe_core_events()

    delivered = hooks.publish_core_event('card.created', {'card_ids': ['a']})

    assert delivered == 2
    assert first.get_nowait()['event'] == 'card.created'
    assert second.get_nowait()['event'] == 'card.created'


# ------------------------------------------------------------------ 端点层


def test_endpoint_streams_core_event_to_client(event_app):
    """端到端：`emit` 之后 SSE 流里真的出现该事件。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    assert response.status_code == 200
    assert response.mimetype == 'text/event-stream'

    hooks.emit('card.updated', {'card_id': 'a.json', 'changed_fields': ['name']})

    text = _collect(response, limit=2)
    frames = _parse_frames(text)

    assert frames[0]['event'] == 'ready', '首帧必须是 ready（前端据此确认通路可用）'
    payloads = _payloads(text)
    assert payloads, f'未收到 core 帧: {text!r}'
    assert payloads[0]['event'] == 'card.updated'
    assert payloads[0]['payload'] == {'card_id': 'a.json', 'changed_fields': ['name']}


def test_endpoint_payload_shape_is_event_payload_ts(event_app):
    """负载形状固定为 `{event, payload, ts}`，payload 是 `emit()` 的原样对象。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    hooks.emit('scan.completed', {'scanned': 12, 'elapsed': 1.5})

    text = _collect(response, limit=2)
    payloads = _payloads(text)

    assert payloads, f'未收到 core 帧: {text!r}'
    record = payloads[0]
    assert set(record.keys()) == {'event', 'payload', 'ts'}
    assert record['event'] == 'scan.completed'
    assert record['payload'] == {'scanned': 12, 'elapsed': 1.5}
    assert isinstance(record['ts'], float)


def test_endpoint_does_not_stream_plugin_custom_events(event_app):
    """端点层同样不得把插件自定义事件放进广播流。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    hooks.emit('demo-plugin:noise', {'value': 1})
    # 再发一条核心事件把它「顶」出来，确认流是活的
    hooks.emit('card.deleted', {'card_ids': ['a']})

    text = _collect(response, limit=2)
    payloads = _payloads(text)

    assert [item['event'] for item in payloads] == ['card.deleted']


def test_endpoint_rejects_unknown_event_filter(event_app):
    """`?events=` 里的未知事件名返回结构化 400（帮插件作者发现拼写错误）。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events?events=card.updated,card.updted')

    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False
    assert data['error'] == 'invalid_payload'
    assert 'card.updted' in data['msg']
    # 顺带把合法集合告诉调用方
    assert 'card.updated' in data['events']


def test_endpoint_honours_event_filter(event_app):
    """`?events=` 过滤生效：不在白名单里的事件不投递。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events?events=scan.completed')

    hooks.emit('card.updated', {'card_id': 'ignored'})
    hooks.emit('scan.completed', {'scanned': 3})

    text = _collect(response, limit=2)
    payloads = _payloads(text)

    assert [item['event'] for item in payloads] == ['scan.completed']


def test_endpoint_returns_structured_error_when_quota_exhausted(event_app, monkeypatch):
    """超限返回 **429 + 结构化错误**，绝不静默挂住。"""
    monkeypatch.setattr(hooks, 'EVENT_STREAM_MAX_CONNECTIONS', 1)

    client = event_app.test_client()
    first = client.get('/api/plugins/events')
    assert first.status_code == 200

    second = client.get('/api/plugins/events')

    assert second.status_code == 429
    data = second.get_json()
    assert data['success'] is False
    assert data['error'] == 'sse_limit_reached'
    assert '上限' in data['msg']


def test_endpoint_releases_quota_when_client_disconnects(event_app, monkeypatch):
    """客户端断开后配额必须还回去（否则几次刷新就把连接数耗光）。"""
    monkeypatch.setattr(hooks, 'EVENT_STREAM_MAX_CONNECTIONS', 1)

    client = event_app.test_client()
    response = client.get('/api/plugins/events')
    _collect(response, limit=1)  # 只取首帧就「断开」

    assert hooks.event_stream_stats()['connections'] == 1
    # 显式关掉生成器（Flask 测试客户端在响应对象被回收时才关，这里手动触发）
    response.close()
    assert hooks.event_stream_stats()['connections'] == 0


def test_endpoint_emits_heartbeat_when_idle(event_app, monkeypatch):
    """空闲时发 `: heartbeat` 帧（代理会掐掉长时间无输出的流）。"""
    monkeypatch.setattr(hooks, 'EVENT_STREAM_HEARTBEAT_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(hooks, 'EVENT_STREAM_POLL_INTERVAL_SECONDS', 0.01)

    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    text = _collect(response, limit=2)
    assert ': heartbeat' in text


def test_stream_is_not_broken_by_no_store_header(event_app):
    """蓝图的 `Cache-Control: no-store` 不得影响 SSE 流（实测确认，见提示词 D3.2）。

    `no-store` 是**响应头**，与流式生成无关；但这条头部由 `after_request`
    统一加上，因此必须验证它真的不会让流变成非流式。
    """
    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    assert response.status_code == 200
    assert response.mimetype == 'text/event-stream'
    # `after_request` 的 no-store 仍然在（保持管理接口的既有约定）
    assert response.headers['Cache-Control'] == 'no-store'

    hooks.emit('card.updated', {'card_id': 'still-works'})
    text = _collect(response, limit=2)
    assert _payloads(text)[0]['event'] == 'card.updated'


def test_exception_inside_stream_does_not_hang_response(event_app, monkeypatch):
    """流内异常不能让响应挂死，且必须释放配额。"""
    client = event_app.test_client()
    response = client.get('/api/plugins/events')

    def boom(*args, **kwargs):
        raise RuntimeError('frame build failed')

    monkeypatch.setattr(routes.jobs, 'sse_frame', boom)

    hooks.emit('card.updated', {'card_id': 'x'})

    text = _collect(response, limit=2)
    # 流已结束（异常被吞并走到 finally），配额被释放
    assert 'ready' in text
    assert hooks.event_stream_stats()['connections'] == 0


# ------------------------------------------------------------------ 并发


def test_concurrent_emit_and_subscribe_is_safe():
    """多线程同时 emit / 订阅取消不得抛错（锁保护）。"""
    errors = []
    stop = threading.Event()

    def emitter():
        try:
            while not stop.is_set():
                hooks.emit('card.updated', {'card_id': 'x'})
        except Exception as exc:  # noqa: BLE001 - 测试要捕获任何异常
            errors.append(exc)

    threads = [threading.Thread(target=emitter, daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()

    try:
        for _ in range(40):
            bucket = hooks.subscribe_core_events()
            if bucket is not None:
                hooks.unsubscribe_core_events(bucket)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

    assert errors == []
    assert hooks.event_stream_stats()['connections'] == 0


def test_core_events_are_not_subscribable_as_custom():
    """`emit` 报错名与广播无关：无名事件既不派发也不广播。"""
    bucket = hooks.subscribe_core_events()

    hooks.emit('', {'x': 1})

    from queue import Empty

    with pytest.raises(Empty):
        bucket.get_nowait()
