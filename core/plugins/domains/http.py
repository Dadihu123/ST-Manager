"""HTTP 域：`api.http.*`。

路由前缀强制 `/api/plugins/<id>`，插件无法注册前缀之外的路由。
"""

from flask import Blueprint

from core.plugins.domains._base import DomainBase
from core.plugins.errors import PluginLoadError


class HttpDomain(DomainBase):
    """插件 HTTP 路由注册。"""

    domain_name = 'http'

    def route(self, rule: str, methods=None):
        """装饰器：把视图函数注册到本插件的默认蓝图。

        规则先收集在默认蓝图上，等插件的 `register(api)` 返回后由
        `finalize()` 统一注册（Flask 禁止在蓝图注册后继续添加规则）。
        """
        return self._api._route(rule, methods)

    def blueprint(self, bp: Blueprint) -> bool:
        """注册插件蓝图（自动加 `/api/plugins/<id>` 前缀 + 冲突检查）。"""
        return self._api._register_blueprint(bp)
