"""ST-Manager 插件系统。

公开入口（设计文档 4.1）：
- `hooks`：Hook 总线（替代已删除的 `core/event_bus.py`）
- `registry`：插件发现 / 加载 / 启用禁用 / 失败隔离
- `cli`：插件 CLI 子命令（N2，`python app.py plugin <id> <cmd>`）
- `get_api(plugin_id)`：取出已加载插件的 `PluginAPI`

导入策略：包初始化只加载**无内部依赖**的子模块（`errors` / `hooks` /
`job_store`），其余模块通过 PEP 562 的模块级 `__getattr__` 惰性加载。

原因：`core.data.db_session` → `core.plugins.job_store` 会在 `core.context`
尚未初始化完成时触发本包初始化；若此处急切导入 `api`（依赖 `core.context.ctx`）
就会形成 `core.context → core.data.cache → core.data.db_session → core.plugins
→ api → core.context` 的循环导入。
"""

import importlib

from core.plugins import errors, hooks, job_store  # noqa: F401
from core.plugins.errors import PluginError  # noqa: F401

_LAZY_MODULES = {
    'secrets': 'core.plugins.secrets',
    'secrets_store': 'core.plugins.secrets',
    'manifest': 'core.plugins.manifest',
    'api': 'core.plugins.api',
    'jobs': 'core.plugins.jobs',
    'registry': 'core.plugins.registry',
    'assets': 'core.plugins.assets',
    'catalog': 'core.plugins.catalog',
    'installer': 'core.plugins.installer',
    'routes': 'core.plugins.routes',
    'cli': 'core.plugins.cli',
}

_LAZY_ATTRIBUTES = {
    'PluginAPI': ('core.plugins.api', 'PluginAPI'),
}

__all__ = [
    'errors',
    'hooks',
    'job_store',
    'secrets',
    'secrets_store',
    'manifest',
    'api',
    'jobs',
    'registry',
    'assets',
    'catalog',
    'installer',
    'routes',
    'cli',
    'PluginAPI',
    'PluginError',
    'get_api',
]


def __getattr__(name):
    if name in _LAZY_ATTRIBUTES:
        module_name, attribute = _LAZY_ATTRIBUTES[name]
        value = getattr(importlib.import_module(module_name), attribute)
        globals()[name] = value
        return value

    module_path = _LAZY_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module 'core.plugins' has no attribute {name!r}")

    module = importlib.import_module(module_path)
    globals()[name] = module
    return module


def get_api(plugin_id: str):
    """获取已加载插件的 `PluginAPI`；插件未加载或被禁用时返回 None。"""
    return __getattr__('registry').get_api(plugin_id)
