"""域基类：插件 API 各域共享的机制层（方案 §3.7）。

设计要点：
1. 域对象**只持有一个 `api` 引用**，不复制任何宿主状态；需要宿主状态时
   每次调用重新解析（卡片可能已被移走、配置可能已改）。
2. 一致性机制（路径边界、卡片锁、fs 事件抑制、缓存/DB/索引三处同步）
   一律**转发到 `PluginAPI` 上的唯一实现**，域不得各写一份——否则会出现
   「插件移动卡片后列表不刷新」这类难查的 bug。
3. 域方法**不接受 `api_key` 参数**：密钥由域内部通过 `api.secrets.get` 解析。
4. 域**不接受 `card_id` 之外的原始路径**：路径一律经过边界校验。
"""

import contextlib
import logging

logger = logging.getLogger(__name__)


class DomainBase:
    """所有域的基类。"""

    #: 用于文档与日志的域显示名（子类覆盖）
    domain_name = ''

    def __init__(self, api):
        self._api = api

    # ------------------------------------------------------------ 公共属性

    @property
    def plugin_id(self) -> str:
        """当前插件 id（域内部与域方法日志都用它）。"""
        return self._api.plugin_id

    # ------------------------------------------------------------ 机制转发

    def _resolve_card_path(self, card_id) -> str:
        """解析卡片相对 id 为绝对路径；越界或非法时返回空串。"""
        return self._api._resolve_card_path(card_id)

    @contextlib.contextmanager
    def _card_lock(self, card_id):
        """卡片写锁；宿主未提供锁时退化为空上下文（不阻断调用）。"""
        lock = self._api._card_lock(card_id)
        with lock:
            yield

    def _suppress_fs(self, seconds: float = 1.5):
        """抑制文件系统事件的上下文管理器（写被监视目录前必须使用）。"""
        return self._api._suppress_fs_events(seconds)

    def _sync_card_index(self, card_id: str, full_path: str, card_data: dict) -> None:
        """同步内存缓存、`card_metadata` 行与索引增量。"""
        self._api._sync_card_index(card_id, full_path, card_data)

    # ------------------------------------------------------------ 辅助

    def _log(self, level: str, message: str, **extra) -> None:
        self._api._write_log(level, message, **extra)

    def _card_tags(self, card_data: dict) -> list:
        return self._api._card_tags(card_data)

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f'<{type(self).__name__} plugin={self._api.plugin_id!r}>'
