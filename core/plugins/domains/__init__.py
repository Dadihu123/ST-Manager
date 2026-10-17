"""PluginAPI 域命名空间（设计文档：插件 API 全面放开方案 §3）。

每个域类只负责把服务层能力**投影**成插件可用的形状；
一致性机制（卡片锁、fs 事件抑制、缓存/DB/索引同步、路径边界校验）
一律由 `DomainBase` 提供的共享工具处理，各域不得各写一份。

`DOMAIN_CLASSES` 是**域名的唯一来源**：`PluginAPI.__init__` 按它构造实例属性，
`tools/gen_plugin_api_docs.py` 与测试也按它枚举域。新增一个域只需要在这里加一行。
"""

from core.plugins.domains._base import DomainBase
from core.plugins.domains.backups import BackupDomain
from core.plugins.domains.cards import CardDomain
from core.plugins.domains.chats import ChatDomain
from core.plugins.domains.cli import CliDomain
from core.plugins.domains.config import ConfigDomain
from core.plugins.domains.extensions import ExtensionDomain
from core.plugins.domains.http import HttpDomain
from core.plugins.domains.index import IndexDomain
from core.plugins.domains.jobs import JobDomain
from core.plugins.domains.log import LogDomain
from core.plugins.domains.presets import PresetDomain
from core.plugins.domains.private import PrivateDomain
from core.plugins.domains.secrets import SecretDomain
from core.plugins.domains.tags import TagDomain
from core.plugins.domains.worldbook import WorldbookDomain

#: 域属性名 → 域类（`PluginAPI` 的实例属性名与之逐字对应）
DOMAIN_CLASSES = {
    'cards': CardDomain,
    'tags': TagDomain,
    'worldbook': WorldbookDomain,
    'backups': BackupDomain,
    'jobs': JobDomain,
    'private': PrivateDomain,
    'config': ConfigDomain,
    'secrets': SecretDomain,
    'http': HttpDomain,
    'cli': CliDomain,
    'log': LogDomain,
    'index': IndexDomain,
    'chats': ChatDomain,
    'presets': PresetDomain,
    'extensions': ExtensionDomain,
}

__all__ = [
    'DOMAIN_CLASSES',
    'DomainBase',
    'BackupDomain',
    'CardDomain',
    'ChatDomain',
    'CliDomain',
    'ConfigDomain',
    'ExtensionDomain',
    'HttpDomain',
    'IndexDomain',
    'JobDomain',
    'LogDomain',
    'PresetDomain',
    'PrivateDomain',
    'SecretDomain',
    'TagDomain',
    'WorldbookDomain',
]
