"""日志域：`api.log.*`。

把原来的字符串 level（`api.log('info', msg)`）换成具名方法；
`notify(level, msg)` 是它的纯转发，已合并。

当插件正处于某个作业的执行上下文中时，日志会同时追加一条 `log` 事件，
供前端作业面板实时展示。
"""

from core.plugins.domains._base import DomainBase


class LogDomain(DomainBase):
    """带插件前缀的日志（具名 level），并转发到活跃作业事件流。"""

    domain_name = 'log'

    def debug(self, message: str, **extra) -> None:
        """写一条 debug 日志。"""
        self._api._write_log('debug', message, **extra)

    def info(self, message: str, **extra) -> None:
        """写一条 info 日志。"""
        self._api._write_log('info', message, **extra)

    def warn(self, message: str, **extra) -> None:
        """写一条 warning 日志。"""
        self._api._write_log('warning', message, **extra)

    def error(self, message: str, **extra) -> None:
        """写一条 error 日志。"""
        self._api._write_log('error', message, **extra)
