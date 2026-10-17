"""配置域：`api.config.*`。

配置存在 `ui_data._plugins_v1.<id>.config`，`config_schema` 默认值打底。
"""

from core.plugins.domains._base import DomainBase


class ConfigDomain(DomainBase):
    """插件配置读写（`config_schema` 声明过的键）。"""

    domain_name = 'config'

    def get(self) -> dict:
        """读取插件配置：`config_schema` 默认值打底 + 用户保存值。"""
        return self._api._get_config()

    def set(self, patch: dict) -> bool:
        """浅合并写入插件配置（只接受 `config_schema` 声明过的键）。"""
        return self._api._set_config(patch)
