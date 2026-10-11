"""Hook 总线（设计文档第 5 部分）。

替换原 `core/event_bus.py`（15 行空壳、全仓零引用）。核心代码在关键流程末尾
调用 `hooks.emit(event, payload)`，插件通过 `api.on(event, handler)` 订阅。

派发语义（5.3）：
- **同步派发**：调用方阻塞直到所有 handler 返回，简单可预测。
- **异常吞掉**：插件 handler 抛错只记日志，绝不影响核心流程。
- **耗时告警**：单个 handler 超过 `SLOW_HANDLER_THRESHOLD` 记 warning。
- 不提供返回值聚合，避免插件之间的隐式顺序依赖。

另有一条**只读广播**通路（设计文档 6.7）：核心事件同时被喂给
`GET /api/plugins/events` 的 SSE 流，让浏览器侧的 `api.on('card.updated', …)`
真的能收到。广播严格 **fire-and-forget**——上面三条派发语义是核心不变量，
不得因为某个慢客户端而拖住 `card.updated` 的调用方。
"""

import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

# 单个 handler 的耗时告警阈值（秒）
SLOW_HANDLER_THRESHOLD = 0.5

# 核心事件集合（设计文档 5.2）。插件自定义事件必须以 "<plugin_id>:" 开头。
CORE_EVENTS = frozenset({
    'app.ready',
    'card.created',
    'card.updated',
    'card.deleted',
    'card.moved',
    'tag.applied',
    'tag.deleted',
    'worldbook.saved',
    'worldbook.entry_changed',
    'scan.completed',
    'index.job_done',
})

# ---- SSE 广播参数（取值风格对齐 core/plugins/jobs.py）----------------------

#: 单条连接的待发缓冲上限。慢客户端撑满后**丢弃最旧事件**而不是阻塞派发方。
EVENT_STREAM_QUEUE_SIZE = 256

#: 事件流连接的全局上限（与 jobs.SSE_MAX_CONNECTIONS_TOTAL 同量级）。
EVENT_STREAM_MAX_CONNECTIONS = 32

#: 心跳间隔（秒），对齐 jobs.SSE_HEARTBEAT_INTERVAL_SECONDS。
EVENT_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15

#: 生成器轮询缓冲的间隔（秒），对齐 jobs.SSE_POLL_INTERVAL_SECONDS。
EVENT_STREAM_POLL_INTERVAL_SECONDS = 1.0

#: 广播帧的 SSE 事件名。前端 `EventSource` 用同名监听（设计文档 6.7.1）。
EVENT_STREAM_FRAME_NAME = 'core'

_handlers_lock = threading.RLock()

# event -> list[_Handler]，保序派发
_handlers = {}

_stream_lock = threading.Lock()
#: 已连接的事件流缓冲队列集合
_stream_subscribers = set()
#: 当前事件流连接数（全局配额）
_stream_total = 0


class _Handler:
    """一条订阅记录。"""

    __slots__ = ('plugin_id', 'event', 'func')

    def __init__(self, plugin_id: str, event: str, func):
        self.plugin_id = plugin_id
        self.event = event
        self.func = func


def is_core_event(event: str) -> bool:
    """是否为核心事件。"""
    return str(event or '') in CORE_EVENTS


def build_custom_event_name(plugin_id: str, event: str) -> str:
    """校验并返回插件的自定义事件名（强制 `<plugin_id>:` 前缀）。"""
    plugin_id = str(plugin_id or '').strip()
    event = str(event or '').strip()
    prefix = f'{plugin_id}:'
    if not plugin_id or not event.startswith(prefix) or len(event) <= len(prefix):
        return ''
    return event


def register(event: str, handler, *, plugin_id: str = '') -> None:
    """订阅事件。

    Args:
        event: 事件名，核心事件见 `CORE_EVENTS`；插件自定义事件须带 `<id>:` 前缀。
        handler: 可调用对象，接收 payload dict。
        plugin_id: 订阅方插件 id（用于日志与卸载清理）。
    """
    event = str(event or '').strip()
    if not event:
        raise ValueError('hook 事件名不能为空')
    if not callable(handler):
        raise ValueError('hook handler 必须可调用')
    if ':' in event and not is_core_event(event):
        if not plugin_id or not event.startswith(f'{plugin_id}:'):
            raise ValueError(f'插件自定义事件必须以 "{plugin_id}:" 开头: {event}')

    with _handlers_lock:
        _handlers.setdefault(event, []).append(_Handler(str(plugin_id or ''), event, handler))


def unregister(event: str, handler) -> bool:
    """取消订阅指定 handler。返回是否移除成功。"""
    event = str(event or '').strip()
    with _handlers_lock:
        bucket = _handlers.get(event)
        if not bucket:
            return False
        for index, item in enumerate(bucket):
            if item.func is handler:
                del bucket[index]
                if not bucket:
                    _handlers.pop(event, None)
                return True
    return False


def unregister_plugin(plugin_id: str) -> int:
    """移除某个插件的全部订阅，返回移除条数。"""
    plugin_id = str(plugin_id or '')
    removed = 0
    with _handlers_lock:
        for event in list(_handlers.keys()):
            bucket = _handlers[event]
            kept = [item for item in bucket if item.plugin_id != plugin_id]
            removed += len(bucket) - len(kept)
            if kept:
                _handlers[event] = kept
            else:
                _handlers.pop(event, None)
    return removed


def emit(event: str, payload: dict | None = None) -> None:
    """同步派发事件；任何 handler 异常都被吞掉并记录。

    Args:
        event: 事件名。
        payload: 事件数据，缺省为空 dict。
    """
    event = str(event or '').strip()
    if not event:
        logger.warning('忽略无名 hook 事件派发')
        return

    data = payload if isinstance(payload, dict) else {}

    # 广播是 fire-and-forget：只入队，不做任何等待。放在 handler 派发**之前**，
    # 这样即便某个 handler 很慢，浏览器侧也仍是「事件一发生就收到」。
    publish_core_event(event, data)

    with _handlers_lock:
        handlers = list(_handlers.get(event, ()))

    if not handlers:
        return

    for item in handlers:
        start = time.monotonic()
        try:
            item.func(data)
        except Exception:
            logger.exception('插件 %s 的 %s 处理器异常，已忽略', item.plugin_id or '?', event)
            continue

        elapsed = time.monotonic() - start
        if elapsed > SLOW_HANDLER_THRESHOLD:
            logger.warning(
                '插件 %s 的 %s 处理器耗时 %.2fs，超过 %.2fs 阈值',
                item.plugin_id or '?', event, elapsed, SLOW_HANDLER_THRESHOLD,
            )


def subscriber_count(event: str) -> int:
    """订阅某个事件的 handler 数量。"""
    with _handlers_lock:
        return len(_handlers.get(str(event or ''), ()))


def handler_plugin_ids(event: str) -> list:
    """订阅某个事件的插件 id 列表（含空串表示核心侧订阅）。"""
    with _handlers_lock:
        return [item.plugin_id for item in _handlers.get(str(event or ''), ())]


def reset() -> None:
    """清空全部订阅。仅用于测试隔离或进程内重新加载。"""
    with _handlers_lock:
        _handlers.clear()


# ------------------------------------------------------------------ 核心事件广播


def publish_core_event(event: str, payload: dict) -> int:
    """把一条**核心事件**投递给所有事件流订阅者，返回投递到的连接数。

    只广播 `CORE_EVENTS`：插件的自定义事件（`<plugin_id>:` 前缀）**不进这条流**，
    否则插件 A 的噪声会灌给所有插件，且 N1 对插件间通信的「best-effort、不保证
    顺序」承诺会被误读成强保证。

    **绝不阻塞**：只做 `put_nowait`。队列满（慢客户端）时丢弃最旧事件并记 debug，
    而不是让核心流程（`card.updated` 的调用方）等一个不读缓冲的浏览器。
    """
    if not is_core_event(event):
        return 0

    record = {'event': event, 'payload': payload, 'ts': time.time()}
    delivered = 0
    with _stream_lock:
        subscribers = list(_stream_subscribers)

    for bucket in subscribers:
        try:
            bucket.put_nowait(record)
            delivered += 1
        except queue.Full:
            # 慢客户端：丢最旧的那条，保证最新事件能被看到（新事件比旧事件有用）
            try:
                bucket.get_nowait()
                bucket.put_nowait(record)
                delivered += 1
            except (queue.Empty, queue.Full):
                logger.debug('插件事件流缓冲已满，丢弃事件 %s', event)
    return delivered


def subscribe_core_events() -> queue.Queue | None:
    """登记一条事件流连接；超出全局配额时返回 None（由路由层转成结构化错误）。"""
    global _stream_total
    with _stream_lock:
        if _stream_total >= EVENT_STREAM_MAX_CONNECTIONS:
            return None
        bucket: queue.Queue = queue.Queue(maxsize=EVENT_STREAM_QUEUE_SIZE)
        _stream_subscribers.add(bucket)
        _stream_total += 1
        return bucket


def unsubscribe_core_events(bucket: queue.Queue) -> None:
    """注销一条事件流连接。重复调用是安全的。"""
    global _stream_total
    with _stream_lock:
        if bucket in _stream_subscribers:
            _stream_subscribers.discard(bucket)
            _stream_total = max(0, _stream_total - 1)


def event_stream_stats() -> dict:
    """当前事件流连接数（供测试与诊断）。"""
    with _stream_lock:
        return {'connections': _stream_total, 'max': EVENT_STREAM_MAX_CONNECTIONS}


def reset_event_stream_for_tests() -> None:
    """清空事件流订阅与计数。仅用于测试隔离（对齐 `reset()`）。"""
    global _stream_total
    with _stream_lock:
        _stream_subscribers.clear()
        _stream_total = 0
