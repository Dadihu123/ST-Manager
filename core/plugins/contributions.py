"""贡献声明（contributions）的宿主适配层。

规则本体在 `core/plugins/contract.py`（纯标准库的单一事实源）：本模块只做宿主侧
的适配——调用 `contract.normalize_contributions()`、把节点级 issues 转成人类可读
warnings、检查图标名、提供计数辅助。**不接触**注册表、数据库与 DOM。

两级校验（设计 §4.9）：宿主**宽容**（非法节点丢弃 + 警告，插件其余部分照常加载），
`stm-plugin-check` **严格**（把同样的问题升级为错误）。这里始终按宽容模式工作。
"""

import logging

from core.plugins import contract
from core.plugins.icons import is_host_icon_name, sprite_for_icon

logger = logging.getLogger(__name__)

# 容量/默认值的转发（宿主侧代码只需要 import 本模块，不必直接碰 contract）
DEFAULT_ORDER = contract.DEFAULT_ORDER
MAX_MENU_NODES_PER_PLUGIN = contract.MAX_MENU_NODES_PER_PLUGIN
MAX_MENU_DEPTH = contract.MAX_MENU_DEPTH
MAX_COMMANDS_PER_PLUGIN = contract.MAX_COMMANDS_PER_PLUGIN
MAX_SLOTS_PER_PLUGIN = contract.MAX_SLOTS_PER_PLUGIN
MAX_DOCK_SLOTS = contract.MAX_DOCK_SLOTS
MAX_DOCK_PER_PLUGIN = contract.MAX_DOCK_PER_PLUGIN

CONTRIBUTION_KINDS = ('menus', 'slots', 'commands')


def empty_contributions() -> dict:
    """三原语的空声明（失败插件 / 缺省 manifest 的快照形状）。"""
    return {'menus': [], 'slots': [], 'commands': []}


def issue_to_warning(issue) -> str:
    """把一条契约 issue 转成人类可读的 warning 文本。"""
    if not isinstance(issue, dict):
        return str(issue or '').strip()
    field = str(issue.get('field') or '').strip()
    message = str(issue.get('message') or '').strip()
    if field and message:
        return f'{field}: {message}'
    return message or field


def issues_to_warnings(issues) -> list:
    """把契约 issues 全部转成 warning 文本（宿主宽容：全部按警告处理）。"""
    warnings = []
    for issue in issues or []:
        text = issue_to_warning(issue)
        if text:
            warnings.append(text)
    return warnings


def normalize_contributions(plugin_id: str, raw_contributions) -> tuple:
    """归一化 `frontend.contributions`，返回 `(contributions, warnings)`。

    宿主宽容模式：节点级问题（非法节点、未知子键、容量/深度超出、命令引用缺失）
    一律丢弃该节点并记 warning；不会拒绝加载整个插件。
    """
    contributions, issues = contract.normalize_contributions(
        raw_contributions, field='frontend.contributions',
    )
    warnings = issues_to_warnings(issues)
    warnings.extend(check_contribution_icons(contributions))
    for warning in warnings:
        logger.warning('插件 %s 的贡献声明有问题（已按宽容策略处理）: %s', plugin_id, warning)
    return contributions, warnings


def iter_menu_nodes(menus):
    """深度优先遍历菜单节点（含子节点）；契约实现转发。"""
    return contract.iter_menu_nodes(menus)


def count_menu_nodes(menus) -> int:
    """菜单节点总数（含子节点）。"""
    return contract.count_menu_nodes(menus)


def contribution_counts(contributions) -> dict:
    """三原语计数，供列表载荷 / 日志 / 测试使用。"""
    menus = (contributions or {}).get('menus') or []
    return {
        'menus': count_menu_nodes(menus),
        'menu_roots': len(menus),
        'slots': len((contributions or {}).get('slots') or []),
        'commands': len((contributions or {}).get('commands') or []),
    }


def check_contribution_icons(contributions) -> list:
    """检查菜单节点 / 命令的图标名是否为已知宿主图标。

    图标名契约（沿用 v2 的 D4）：不含 `/` 与 `.` 的是宿主图标名，宿主负责解析；
    含 `/` 的是插件自带资源路径，由前端按资产 URL 加载，本层不检查存在性。
    未知宿主图标只警告（不丢弃节点）——图标缺失不应让功能消失。
    """
    warnings = []
    for node in iter_menu_nodes((contributions or {}).get('menus') or []):
        warnings.extend(_check_icon(node.get('icon'), f'菜单节点 {node.get("id")}'))
    for command in (contributions or {}).get('commands') or []:
        warnings.extend(_check_icon(command.get('icon'), f'命令 {command.get("id")}'))
    return warnings


def _check_icon(icon, label: str) -> list:
    value = str(icon or '').strip()
    if not value or not is_host_icon_name(value):
        return []
    if sprite_for_icon(value):
        return []
    return [f'{label} 引用了不存在的宿主图标: {value}（用 /api/plugins/ui-icons 查询合法名字）']


def snapshot(contributions) -> dict:
    """返回可安全放进列表载荷的深拷贝（调用方修改不会影响 manifest）。"""
    source = contributions or {}
    return {
        'menus': [_copy_node(node) for node in source.get('menus') or []],
        'slots': [dict(item) for item in source.get('slots') or [] if isinstance(item, dict)],
        'commands': [dict(item) for item in source.get('commands') or [] if isinstance(item, dict)],
    }


def _copy_node(node) -> dict:
    if not isinstance(node, dict):
        return {}
    copied = dict(node)
    copied['when'] = dict(copied.get('when') or {})
    copied['children'] = [_copy_node(child) for child in copied.get('children') or []]
    if copied.get('action') is not None:
        copied['action'] = dict(copied['action'])
    return copied
