"""密钥域：`api.secrets.*`。

密钥纪律不变：`list()` 永不返回明文，只返回 `{key: {set, hint, updated_at}}`。
"""

from core.plugins.domains._base import DomainBase


class SecretDomain(DomainBase):
    """插件密钥读写（`secrets.json`，按插件 id 命名空间隔离）。"""

    domain_name = 'secrets'

    def get(self, key: str):
        """读取密钥：环境变量 > `secrets.json` > 非 secret 项的 schema 默认值。"""
        return self._api._get_secret(key)

    def set(self, key: str, value) -> bool:
        """写入密钥；`None` / 空串表示清除该项。"""
        return self._api._set_secret(key, value)

    def list(self) -> dict:
        """返回 `{key: {set, hint, updated_at}}`，secret 项永不返回明文。"""
        return self._api._list_secrets()
