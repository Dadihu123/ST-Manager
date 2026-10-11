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


# ------------------------------------------------------------------ 核心事件流


def test_core_events_are_routed_to_sse_not_window():
    """`api.on()` 分流：核心事件走 SSE，其余保持 window 事件（行为不变）。

    这是本次修复的核心：`api.on('card.updated', h)` 此前只做
    `window.addEventListener`，而后端是 `hooks.emit(...)`——两条独立总线，
    因此处理器**永远不会被调用**。
    """
    source = read_source('static/js/pluginHost.js')

    assert 'if (CORE_EVENTS.has(name))' in source
    assert 'subscribeCoreEvent(pluginId, name, handler)' in source
    # 非核心事件仍走既有通路
    assert 'window.addEventListener(name, wrapped)' in source


def test_core_event_bridge_uses_a_single_lazy_connection_per_plugin():
    """懒连接 + 每插件一条流：零订阅不占配额，N 个 `on()` 也只一条连接。"""
    source = read_source('static/js/pluginHost.js')

    # 连接按 pluginId 复用
    assert 'this.connections.get(key)' in source
    # 首次订阅才建立
    assert 'new EventSource(url)' in source
    assert 'const url = "/api/plugins/events"' in source
    # 零订阅即释放（否则插件反复订阅/取消会耗尽服务端配额）
    assert 'if (!current.listeners.size) this.close(key);' in source


def test_core_event_bridge_is_never_created_in_load_plugin():
    """**懒连接**：不得在 loadPlugin 里建流（那会让每个插件都占一条配额）。"""
    source = read_source('static/js/pluginHost.js')

    load_plugin = source.split('async loadPlugin(entry, manifest) {', 1)[1]
    load_plugin = load_plugin.split('this.loaded.set(pluginId', 1)[0]
    assert 'coreEventBridge' not in load_plugin
    assert 'new EventSource' not in load_plugin


def test_core_event_bridge_is_released_on_destroy():
    """连接生命周期挂到插件回收链（与 `subscribeJob` 的 `own()` 同一模式）。"""
    source = read_source('static/js/pluginHost.js')

    assert 'coreEventBridge.close(key);' in source
    assert 'coreEventBridge.closeAll();' in source
    # own() 也登记了一次，双保险
    assert '(disposer) => PluginHost.addDisposer(pluginId, disposer)' in source


def test_core_event_bridge_dispatches_locally_per_event_name():
    """分派在插件本地按事件名筛：因此流只需订阅全部核心事件，不必因订阅变化重连。"""
    source = read_source('static/js/pluginHost.js')

    assert '_dispatch(key, conn, payload)' in source
    assert 'conn.listeners.get(name)' in source


def test_core_event_bridge_does_not_invent_a_polling_endpoint():
    """核心事件是**广播**，没有历史可轮询——不得编造不存在的轮询端点。"""
    source = read_source('static/js/pluginHost.js')

    assert '/api/plugins/events/poll' not in source
    # 无 EventSource 时明确告警（而非静默失败）
    assert '当前环境不支持 EventSource' in source


def test_backend_core_event_endpoint_broadcasts_only_core_events():
    """后端只广播 `CORE_EVENTS`；插件自定义事件不进流。"""
    source = read_source('core/plugins/routes.py')

    assert "@bp.route('/api/plugins/events', methods=['GET'])" in source
    assert 'hooks.is_core_event' in source
    assert 'hooks.subscribe_core_events()' in source
    assert 'hooks.unsubscribe_core_events(bucket)' in source


def test_backend_broadcast_is_fire_and_forget():
    """广播必须非阻塞：`hooks.emit` 的派发语义是核心不变量。"""
    source = read_source('core/plugins/hooks.py')

    assert 'publish_core_event(event, data)' in source
    assert 'put_nowait' in source
    # 不得在广播路径上阻塞等待
    broadcast = source.split('def publish_core_event(', 1)[1].split('def subscribe_core_events', 1)[0]
    assert '.put(' not in broadcast, '广播路径不得出现阻塞式 put'
    assert 'logger.exception' not in broadcast

