"""预设域：`api.presets.*`（P2）。

只做**读取**：预设列表与文件内容。写入走主程序路由层的能力暂不投影——
预设写入涉及家族版本、默认版本标记等语义，放开前需要单独设计。
"""

from core.plugins.domains._base import DomainBase


class PresetDomain(DomainBase):
    """宿主预设的读取。"""

    domain_name = 'presets'

    def list(self, *, search: str = '', limit: int = 0) -> list:
        """列出 ST 预设（名称 / 文件名 / 路径）。

        Args:
            search: 按名称或文件名子串过滤（大小写不敏感）。
            limit: 返回上限；`0` 表示不设上限。

        Returns:
            `[{'id', 'filename', 'name', 'enabled', 'filepath'}, …]`
        """
        return self._api._list_presets(search=search, limit=limit)

    def read(self, file_path: str):
        """读取预设文件内容（原始 JSON）。

        `file_path` 必须在预设目录之内，越界返回 `None`。
        """
        return self._api._read_preset(file_path)
