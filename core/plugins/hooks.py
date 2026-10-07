"""Hook 总线（设计文档第 5 部分）。

替换原 `core/event_bus.py`（15 行空壳、全仓零引用）。核心代码在关键流程末尾
调用 `hooks.emit(event, payload)`，插件通过 `api.on(event, handler)` 订阅。

派发语义（5.3）：
- **同步派发**：调用方阻塞直到所有 handler 返回，简单可预测。
- **异常吞掉**：插件 handler 抛错只记日志，绝不影响核心流程。
- **耗时告警**：单个 handler 超过 `SLOW_HANDLER_THRESHOLD` 记 warning。
- 不提供返回值聚合，避免插件之间的隐式顺序依赖。
"""

import logging
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

_handlers_lock = threading.RLock()

# event -> list[_Handler]，保序派发
_handlers = {}


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
