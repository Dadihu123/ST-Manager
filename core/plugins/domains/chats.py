"""会话域：`api.chats.*`（P2）。

只做**读取**：会话列表与单个会话的元数据（来自主程序的 `chat_data.json`）。
会话正文解析见 `core/utils/chat_parser.py`，本域暂不投影。
"""

from core.plugins.domains._base import DomainBase


class ChatDomain(DomainBase):
    """宿主会话列表与元数据读取。"""

    domain_name = 'chats'

    def list(self, *, search: str = '', favorite=None, limit: int = 0) -> list:
        """列出会话条目（主程序 `chat_data.json` 的归一化结果）。

        Args:
            search: 按会话 id 子串过滤（大小写不敏感）。
            favorite: `True` / `False` 只取已收藏 / 未收藏；`None` 不过滤。
            limit: 返回上限；`0` 表示不设上限。

        Returns:
            `[{'id', 'favorite', 'bookmarks', …}, …]`
        """
        return self._api._list_chats(search=search, favorite=favorite, limit=limit)

    def get(self, chat_id: str):
        """读取单个会话条目；不存在返回 `None`。"""
        return self._api._get_chat(chat_id)
