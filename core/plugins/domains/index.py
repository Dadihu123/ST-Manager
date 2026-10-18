"""索引域：`api.index.*`。

插件用 `search()` 做候选筛选，用 `status()` 判断索引是否就绪
（未就绪时应退化为 `api.cards.list()` 或直接读卡片），
用 `rebuild()` 触发重建（返回一个作业 id，进度走 `api.index.status()`）。
"""

from core.plugins.domains._base import DomainBase


class IndexDomain(DomainBase):
    """宿主索引的状态、搜索与重建。"""

    domain_name = 'index'

    def status(self) -> dict:
        """读取索引状态。

        启动时的索引重建已改为后台执行，因此 `status()` 可能在应用就绪后
        仍然返回 `state='building'`；`upgrade_active` 表示这次构建是否属于
        「首次引导 / 搜索内容格式升级」的后台重建。

        Returns:
            `{'state', 'scope', 'progress', 'message', 'pending_jobs',
              'schema': {...}, 'cards': {...}, 'worldinfo': {...},
              'scan_active', 'scan_message', 'upgrade_active'}`
            其中每个 scope 块含 `state` / `phase` / `active_generation` /
            `building_generation` / `items_written` / `last_error` /
            `progress_done` / `progress_total`。
        """
        return self._api._index_status()

    def search(
        self, query: str, *, scope: str = 'cards', limit: int = 50,
        offset: int = 0, category: str = '', tags=(), search_mode: str = 'fast',
    ) -> dict:
        """在宿主索引里搜索实体。

        Args:
            query: 搜索词；`search_mode='fulltext'` 时走 FTS5（语法非法时返回空集
                而不是抛错）。
            scope: `'cards'` 或 `'worldinfo'`。
            limit / offset: 分页。
            category: 分类前缀过滤。
            tags: 必须包含的标签（仅 `scope='cards'` 有意义）。
            search_mode: `'fast'`（子串匹配，默认）或 `'fulltext'`。

        Returns:
            `{'items': [...], 'total': int, 'index_ready': bool}`
        """
        return self._api._index_search(
            query, scope=scope, limit=limit, offset=offset,
            category=category, tags=tags, search_mode=search_mode,
        )

    def rebuild(self, *, scope: str = 'cards') -> str:
        """触发索引重建，返回作业 id（进度走 `status()`）。

        `scope` 只接受 `'cards'` / `'worldinfo'`；其它值抛 `ValueError`。
        """
        return self._api._request_index_rebuild(scope)
