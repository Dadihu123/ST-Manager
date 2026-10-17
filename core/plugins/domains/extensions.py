"""扩展资源域：`api.extensions.*`（P2）。

投影的是 ST 的**全局**扩展资源（不在卡片内嵌的）：
正则脚本库与 Tavern Helper 脚本库。

卡片内嵌的正则/脚本请走 `api.cards.read_extensions(card_id)`。
"""

from core.plugins.domains._base import DomainBase


class ExtensionDomain(DomainBase):
    """全局正则脚本与脚本库的读取。"""

    domain_name = 'extensions'

    def regex_scripts(self) -> list:
        """列出 ST 全局正则脚本。

        Returns:
            `[{'id', 'filename', 'name', 'enabled', 'find_regex',
               'replace_string', 'filepath', 'data'}, …]`
        """
        return self._api._list_regex_scripts()

    def scripts(self) -> list:
        """列出 Tavern Helper 脚本资源。

        Returns:
            `[{'id', 'name', 'enabled', 'folder', 'scripts', 'filepath'}, …]`
        """
        return self._api._list_scripts()
