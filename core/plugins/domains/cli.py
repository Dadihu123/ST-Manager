"""CLI 域：`api.cli.*`。

子命令入口：`python app.py plugin <id> <name> [args…]`。
"""

from core.plugins.domains._base import DomainBase


class CliDomain(DomainBase):
    """插件 CLI 子命令注册。"""

    domain_name = 'cli'

    def register(self, name: str, handler, description: str = '') -> None:
        """注册一个 CLI 子命令。

        `handler(namespace)` 接收 `argparse.Namespace`，字段约定见
        `core/plugins/cli.py` 的模块文档（`args` / `options` 与退出码规则）。
        """
        from core.plugins import cli as cli_module

        cli_module.register_cli(self.plugin_id, name, handler, description)
