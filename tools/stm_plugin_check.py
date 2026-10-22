#!/usr/bin/env python3
# stm-plugin-check —— ST-Manager 插件契约 v3 的独立严格校验器。
#
# 用法（复制本文件到任意插件仓库即可运行，**不依赖宿主仓库**）：
#
#   python stm_plugin_check.py path/to/plugin            # 严格模式
#   python stm_plugin_check.py path/to/plugin --json     # 机器可读结果
#
# 退出码：0 = 没有 error；1 = 存在 error（任何会导致宿主丢弃/降级的问题）；
# 2 = 命令行用法错误。
#
# 检查项 = 设计文档 §8.2 的 9 条：
#   1 manifest JSON 合法性 / 大小 / 字段白名单 / 契约版本
#   2 落点 / 插槽 / 数量·深度·容量 / id 唯一
#   3 action 引用（command 必须存在；surface 只校验格式；url 协议）
#   4 模块与导出静态检查（文件存在 + export 文本检查）
#   5 when 条件与 shortcut（格式 / 修饰键 / 同插件冲突）
#   6 render_mode / capabilities / global_styles 一致性
#   7 CSS 作用域扫描（styles 全部；global_styles 豁免）
#   8 图标名 / 资源存在性（未知宿主图标名 = warning）
#   9 契约版本提示（min_app_version 等）
#
# 与宿主同源的实现方式：下方生成区**逐字内嵌** `core/plugins/contract.py`
# 的源码与宿主事实常量（主程序版本、合法图标名）。生成区由
# `tools/gen_plugin_api_docs.py` 重写，`--check` 校验同步；**不要手改生成区**。
# >>> BEGIN GENERATED: core/plugins/contract.py (by tools/gen_plugin_api_docs.py) >>>
"""插件契约 v3 的单一事实源：版本、枚举、容量上限与声明层校验。

设计文档：`docs/2026-10-21-plugin-contract-v3-design.md`（§4 manifest、§4.4–§4.7 三原语、§5 落点/插槽）。

**硬约束（改动前先读）**：

- 本模块只依赖标准库，且**不得 import 宿主其它模块、不得产生副作用**。
  独立校验器 `tools/stm_plugin_check.py` 由生成器把本文件源码**逐字内嵌**，
  以便脱离宿主仓库运行；宿主校验（`core/plugins/manifest.py`）、生成器
  （`tools/gen_plugin_api_docs.py`）与 CLI 校验器必须共用这里的同一份规则。
- 校验分两级（设计 §4.9）：宿主**宽容**（节点级问题 → 丢弃 + 警告，插件其余部分照常加载），
  CLI **严格**（任何会导致宿主丢弃/降级的问题都是错误 → 非零退出）。
  实现方式：`make_issue(..., escalate=True)` 标记「宿主容忍但 CLI 必须报错」，
  `finalize_issues(issues, strict=True)` 提升为 error。
- 结构键（顶层 / `backend` / `frontend` / `contributions`）是**宿主致命错误**；
  节点级子键、容量、深度、引用缺失是**可丢弃项**（escalate）。
- `x-` 前缀的任意键**静默忽略**（实验命名空间）。
"""

from __future__ import annotations

import re

# ============================================================ 版本

MANIFEST_VERSION = 3
SUPPORTED_MANIFEST_VERSIONS = (MANIFEST_VERSION,)
API_VERSION = 3
SUPPORTED_API_VERSIONS = (API_VERSION,)
MAX_MANIFEST_BYTES = 256 * 1024

# ============================================================ 结构键白名单

KNOWN_TOP_LEVEL_KEYS = frozenset({
    'id', 'name', 'version', 'api_version', 'manifest_version', 'author',
    'description', 'homepage', 'license', 'icon', 'min_app_version',
    'backend', 'frontend', 'capabilities', 'requires', 'config_schema',
    'secret_schema', 'i18n',
})
KNOWN_BACKEND_KEYS = frozenset({'entry', 'register', 'jobs', 'hooks'})
KNOWN_FRONTEND_KEYS = frozenset({
    'entry', 'styles', 'global_styles', 'render_mode', 'contributions',
})
# 已删除且不保留别名的旧前端字段（出现即拒绝加载，并给出针对性提示）
LEGACY_FRONTEND_KEYS = ('entries', 'panels', 'settings_tab', 'detail_tab')
LEGACY_FRONTEND_HINT = (
    'frontend.entries 已删除：菜单/插槽/命令改用 frontend.contributions'
    '（menus / slots / commands），运行期结构只能静态声明'
)
KNOWN_CONTRIBUTION_KEYS = frozenset({'menus', 'slots', 'commands'})

# ============================================================ 落点 / 插槽 / 工作模式

# 菜单落点（设计 §5.1，v1 清单，新增走 additive）
MENU_PLACEMENTS = (
    'context.folder',
    'context.card',
    'context.footer',
    'batch.actions',
    'commandPalette',
    'dock',
    'settings.nav',
)
MENU_PLACEMENTS_SET = frozenset(MENU_PLACEMENTS)

# 命名插槽（设计 §5.2）；`empty.<mode>` 由 EMPTY_SLOT_PREFIX + 工作模式组成
SLOT_NAMES = (
    'settings.section',
    'header.actions',
    'card.detail.tabs',
    'page.cards.toolbar',
    'page.worldinfo.toolbar',
)
EMPTY_SLOT_PREFIX = 'empty.'

# 宿主工作模式（与前端 `KNOWN_MODES` 一致）
KNOWN_MODES = frozenset({
    'cards', 'worldinfo', 'chats', 'presets',
    'regex', 'scripts', 'quick_replies', 'beautify',
})

# ============================================================ 三原语

MENU_NODE_TYPES = ('item', 'submenu', 'separator')
ACTION_TYPES = ('surface', 'command', 'url')

DEFAULT_ORDER = 100
MAX_MENU_NODES_PER_PLUGIN = 64
MAX_MENU_DEPTH = 3
MAX_COMMANDS_PER_PLUGIN = 32
MAX_SLOTS_PER_PLUGIN = 16
MAX_DOCK_SLOTS = 8
MAX_DOCK_PER_PLUGIN = 2

KNOWN_NODE_KEYS = frozenset({
    'id', 'placement', 'type', 'label', 'description', 'icon', 'order',
    'when', 'badge', 'disabledHint', 'action', 'children',
})

# `when` 条件（设计 §4.4.3）；`contexts` / `when.target` 已删除
KNOWN_WHEN_KEYS = frozenset({
    'mode', 'selection', 'config', 'hostVersion', 'feature', 'indexState',
})
SELECTION_MODES = frozenset({'none', 'any', 'single', 'multi'})
INDEX_STATES = frozenset({'idle', 'running'})

# ============================================================ 能力位（设计 §4.7）

CAPABILITY_UI_CUSTOM = 'ui.custom'
CAPABILITY_UI_GLOBAL_STYLES = 'ui.global_styles'

KNOWN_CAPABILITIES = frozenset({
    # 数据
    'cards.read', 'cards.write',
    'worldbook.read', 'worldbook.write',
    'tags.read', 'tags.write',
    'chats.read', 'chats.write',
    'presets.read', 'presets.write',
    # 运行时
    'secrets.read', 'network.outbound', 'jobs.run', 'hooks.subscribe', 'cli.run',
    # UI
    CAPABILITY_UI_CUSTOM, CAPABILITY_UI_GLOBAL_STYLES,
})

RENDER_MODES = ('declarative', 'custom')
DEFAULT_RENDER_MODE = 'declarative'

# ============================================================ 后端 hook / 配置 schema

KNOWN_HOOKS = frozenset({
    'app.ready',
    'card.created',
    'card.updated',
    'card.deleted',
    'card.moved',
    'tag.applied',
    'tag.deleted',
    'worldbook.saved',
    'worldbook.entry_changed',
    'scan.completed',
    'index.job_done',
})

SCHEMA_TYPES = frozenset({'string', 'integer', 'number', 'boolean', 'enum'})
SCHEMA_ALLOWED_KEYS = frozenset({
    'type', 'title', 'description', 'default', 'minimum', 'maximum',
    'enum', 'secret', 'required', 'properties',
})

# ============================================================ 正则

PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
NODE_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
SEMVER_PATTERN = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$')
REQUIREMENT_PATTERN = re.compile(
    r'^(>=|>|<=|<|==|=)?\s*(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?|\*)$'
)
JOB_TYPE_PATTERN = re.compile(r'^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$')
ENTRY_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
EXPORT_NAME_PATTERN = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')

SHORTCUT_MODIFIERS = ('Ctrl', 'Alt', 'Meta', 'Shift')
SHORTCUT_REQUIRED_MODIFIERS = ('Ctrl', 'Alt', 'Meta')
SHORTCUT_KEY_PATTERN = re.compile(
    r'^(?:[A-Za-z0-9]|F(?:[1-9]|1[0-2])|Escape|Enter|Space|Tab|Backspace|Delete'
    r'|Home|End|PageUp|PageDown|ArrowUp|ArrowDown|ArrowLeft|ArrowRight)$'
)

# ============================================================ issue 工具

SEVERITY_ERROR = 'error'
SEVERITY_WARNING = 'warning'


def make_issue(severity, code, field, message, *, escalate=False, hint=''):
    """构造一条校验问题。

    Args:
        severity: `error`（宿主拒绝加载 / CLI 失败）或 `warning`。
        code: 机器可读错误码（如 `manifest_unknown_key`）。
        field: 字段路径（如 `frontend.contributions.menus[0].placement`）。
        message: 人类可读说明。
        escalate: 宿主容忍、但 CLI 严格模式必须报错的项（设计 §4.9 / §8.2）。
        hint: 修复提示。
    """
    return {
        'severity': str(severity),
        'code': str(code or ''),
        'field': str(field or ''),
        'message': str(message or ''),
        'escalate': bool(escalate),
        'hint': str(hint or ''),
    }


def error_issue(code, field, message, *, hint=''):
    return make_issue(SEVERITY_ERROR, code, field, message, hint=hint)


def warning_issue(code, field, message, *, escalate=False, hint=''):
    return make_issue(SEVERITY_WARNING, code, field, message, escalate=escalate, hint=hint)


def finalize_issues(issues, *, strict=False):
    """按模式收口：严格模式把「宿主容忍项」提升为 error。"""
    result = []
    for item in issues or []:
        issue = dict(item)
        if strict and issue.get('escalate') and issue.get('severity') == SEVERITY_WARNING:
            issue['severity'] = SEVERITY_ERROR
        result.append(issue)
    return result


def has_errors(issues) -> bool:
    return any(str(item.get('severity')) == SEVERITY_ERROR for item in issues or [])


def first_error(issues):
    for item in issues or []:
        if str(item.get('severity')) == SEVERITY_ERROR:
            return item
    return None


def issue_summary(issues) -> str:
    """给日志/CLI 的一行摘要（第一条错误，其次第一条警告）。"""
    for severity in (SEVERITY_ERROR, SEVERITY_WARNING):
        for item in issues or []:
            if str(item.get('severity')) == severity:
                field = item.get('field') or ''
                prefix = f'{field}: ' if field else ''
                return f'[{severity}] {prefix}{item.get("message")}'
    return ''


# ============================================================ 基础判定


def is_experimental_key(key) -> bool:
    """`x-` 前缀 = 实验命名空间，静默忽略（设计 §4.9）。"""
    return str(key or '').startswith('x-')


def unknown_keys(payload, allowed) -> list:
    """返回 payload 中不在白名单、也不是 `x-` 实验键的键（排序）。"""
    if not isinstance(payload, dict):
        return []
    return sorted(
        str(key) for key in payload.keys()
        if str(key) not in allowed and not is_experimental_key(key)
    )


def is_known_placement(name) -> bool:
    return str(name or '').strip() in MENU_PLACEMENTS_SET


def is_known_slot(name) -> bool:
    value = str(name or '').strip()
    if value in SLOT_NAMES:
        return True
    if value.startswith(EMPTY_SLOT_PREFIX):
        return value[len(EMPTY_SLOT_PREFIX):] in KNOWN_MODES
    return False


def is_known_mode(name) -> bool:
    return str(name or '').strip() in KNOWN_MODES


def is_relative_module_path(value) -> bool:
    """相对插件根目录的模块/资源路径：非空、不以 `/` 开头、无盘符、无 `..`。"""
    text = str(value or '').replace('\\', '/').strip()
    if not text or text.startswith('/'):
        return False
    if '..' in text.split('/'):
        return False
    if re.match(r'^[A-Za-z]:', text):
        return False
    return True


def parse_semver(value):
    """把语义化版本解析为可比较元组；非法返回 None。"""
    if not isinstance(value, str) or not SEMVER_PATTERN.match(value.strip()):
        return None
    core = value.strip().split('+', 1)[0].split('-', 1)[0]
    try:
        return tuple(int(part) for part in core.split('.'))
    except ValueError:
        return None


def compare_versions(left, right) -> int:
    """left > right → 1，相等 → 0，更小 → -1；不可解析按 -1。"""
    parsed_left = parse_semver(left)
    parsed_right = parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return -1
    if parsed_left > parsed_right:
        return 1
    if parsed_left < parsed_right:
        return -1
    return 0


def parse_requirement(constraint):
    """解析依赖版本约束，返回 `(操作符, 版本)`；`*` 的版本为 `'*'`。"""
    text = str(constraint or '').strip()
    match = REQUIREMENT_PATTERN.match(text) if text else None
    if not match:
        return None
    return match.group(1) or '==', match.group(2)


def satisfies_requirement(version, constraint) -> bool:
    parsed = parse_requirement(constraint)
    if parsed is None:
        return False
    operator, target = parsed
    if target == '*':
        return parse_semver(version) is not None
    current = parse_semver(version)
    expected = parse_semver(target)
    if current is None or expected is None:
        return False
    if operator == '>=':
        return current >= expected
    if operator == '>':
        return current > expected
    if operator == '<=':
        return current <= expected
    if operator == '<':
        return current < expected
    return current == expected


def normalize_shortcut(value) -> str:
    """归一化快捷键写法（去空格、统一修饰键大小写）；非法返回空串。"""
    text = str(value or '').strip()
    if not text:
        return ''
    parts = [part.strip() for part in text.split('+')]
    if len(parts) < 2 or not all(parts):
        return ''
    modifiers = []
    for part in parts[:-1]:
        canonical = part[:1].upper() + part[1:].lower()
        if canonical in ('Ctrl', 'Control'):
            canonical = 'Ctrl'
        elif canonical in ('Cmd', 'Command', 'Meta', 'Super', 'Win'):
            canonical = 'Meta'
        elif canonical in ('Alt', 'Option'):
            canonical = 'Alt'
        elif canonical == 'Shift':
            canonical = 'Shift'
        else:
            return ''
        if canonical not in modifiers:
            modifiers.append(canonical)
    key = parts[-1]
    key_canonical = key if len(key) > 1 else key.upper()
    if key_canonical.lower() == 'space':
        key_canonical = 'Space'
    if not SHORTCUT_KEY_PATTERN.match(key_canonical):
        return ''
    return '+'.join(modifiers + [key_canonical])


def is_valid_shortcut(value) -> bool:
    """快捷键必须含修饰键 Ctrl / Alt / Meta 之一（设计 §4.6）。"""
    normalized = normalize_shortcut(value)
    if not normalized:
        return False
    parts = normalized.split('+')
    return any(part in SHORTCUT_REQUIRED_MODIFIERS for part in parts[:-1])


# ============================================================ when / action


def normalize_when(raw_when, *, field='when'):
    """归一化 `when` 条件；未知子键忽略 + 警告（设计 §4.4.3）。"""
    issues = []
    if raw_when is None:
        return {}, issues
    if not isinstance(raw_when, dict):
        issues.append(warning_issue(
            'when_invalid', field, f'{field} 必须是对象，已忽略', escalate=True,
        ))
        return {}, issues

    when = {}
    for raw_key, raw_value in raw_when.items():
        key = str(raw_key or '').strip()
        if is_experimental_key(key):
            continue
        if key not in KNOWN_WHEN_KEYS:
            issues.append(warning_issue(
                'when_unknown_key', f'{field}.{key}',
                f'忽略未知的 when 子键: {key}',
                escalate=True,
                hint=f'when 支持的子键：{", ".join(sorted(KNOWN_WHEN_KEYS))}',
            ))
            continue

        if key == 'mode':
            if not isinstance(raw_value, list):
                issues.append(warning_issue(
                    'when_invalid', f'{field}.mode', 'when.mode 必须是数组，已忽略', escalate=True,
                ))
                continue
            kept = []
            for item in raw_value:
                mode = str(item or '').strip()
                if not mode:
                    continue
                if mode in KNOWN_MODES:
                    kept.append(mode)
                else:
                    issues.append(warning_issue(
                        'when_unknown_mode', f'{field}.mode',
                        f'忽略未知的工作模式: {mode}', escalate=True,
                    ))
            when['mode'] = kept
            continue

        if key == 'feature':
            if not isinstance(raw_value, list):
                issues.append(warning_issue(
                    'when_invalid', f'{field}.feature', 'when.feature 必须是数组，已忽略', escalate=True,
                ))
                continue
            when['feature'] = [
                str(item).strip() for item in raw_value
                if isinstance(item, str) and str(item).strip()
            ]
            continue

        if key == 'selection':
            value = str(raw_value or '').strip()
            if value not in SELECTION_MODES:
                issues.append(warning_issue(
                    'when_invalid', f'{field}.selection',
                    f'忽略非法的 when.selection: {raw_value!r}', escalate=True,
                    hint=f'合法取值：{", ".join(sorted(SELECTION_MODES))}',
                ))
                continue
            when['selection'] = value
            continue

        if key == 'indexState':
            value = str(raw_value or '').strip()
            if value not in INDEX_STATES:
                issues.append(warning_issue(
                    'when_invalid', f'{field}.indexState',
                    f'忽略非法的 when.indexState: {raw_value!r}', escalate=True,
                ))
                continue
            when['indexState'] = value
            continue

        if key == 'hostVersion':
            value = str(raw_value or '').strip()
            if not value:
                continue
            if parse_semver(value) is None:
                issues.append(warning_issue(
                    'when_invalid', f'{field}.hostVersion',
                    f'忽略非法的 when.hostVersion: {raw_value!r}（应为 1.2.3 形式）', escalate=True,
                ))
                continue
            when['hostVersion'] = value
            continue

        if key == 'config':
            if not isinstance(raw_value, dict):
                issues.append(warning_issue(
                    'when_invalid', f'{field}.config', 'when.config 必须是对象，已忽略', escalate=True,
                ))
                continue
            unknown = unknown_keys(raw_value, frozenset({'requireKeys'}))
            for item in unknown:
                issues.append(warning_issue(
                    'when_unknown_key', f'{field}.config.{item}',
                    f'忽略未知的 when.config 子键: {item}', escalate=True,
                ))
            raw_keys = raw_value.get('requireKeys')
            require_keys = []
            if raw_keys is not None:
                if not isinstance(raw_keys, list):
                    issues.append(warning_issue(
                        'when_invalid', f'{field}.config.requireKeys',
                        'when.config.requireKeys 必须是字符串数组，已忽略', escalate=True,
                    ))
                else:
                    for item in raw_keys:
                        if isinstance(item, str) and item.strip():
                            require_keys.append(item.strip())
                        else:
                            issues.append(warning_issue(
                                'when_invalid', f'{field}.config.requireKeys',
                                f'忽略非法的 requireKeys 项: {item!r}', escalate=True,
                            ))
            when['config'] = {'requireKeys': require_keys}
            continue

    return when, issues


def normalize_action(raw_action, *, field='action', command_ids=None):
    """归一化 `action`；非法返回 `(None, issues)`（调用方丢弃该节点）。"""
    issues = []
    if not isinstance(raw_action, dict):
        issues.append(warning_issue(
            'action_invalid', field, f'{field} 必须是对象，该项已丢弃', escalate=True,
        ))
        return None, issues

    action_type = str(raw_action.get('type') or '').strip()
    if action_type not in ACTION_TYPES:
        issues.append(warning_issue(
            'action_invalid', f'{field}.type',
            f'{field}.type 非法: {raw_action.get("type")!r}，该项已丢弃',
            escalate=True,
            hint=f'合法取值：{", ".join(ACTION_TYPES)}',
        ))
        return None, issues

    if action_type == 'surface':
        surface_id = str(raw_action.get('id') or '').strip()
        if not NODE_ID_PATTERN.match(surface_id):
            issues.append(warning_issue(
                'action_invalid', f'{field}.id',
                f'{field}.id 非法: {raw_action.get("id")!r}，该项已丢弃', escalate=True,
            ))
            return None, issues
        for key in unknown_keys(raw_action, frozenset({'type', 'id'})):
            issues.append(warning_issue(
                'action_unknown_key', f'{field}.{key}',
                f'忽略未知的 action 子键: {key}', escalate=True,
            ))
        return {'type': 'surface', 'id': surface_id}, issues

    if action_type == 'command':
        command_id = str(raw_action.get('id') or '').strip()
        if not NODE_ID_PATTERN.match(command_id):
            issues.append(warning_issue(
                'action_invalid', f'{field}.id',
                f'{field}.id 非法: {raw_action.get("id")!r}，该项已丢弃', escalate=True,
            ))
            return None, issues
        if command_ids is not None and command_id not in command_ids:
            issues.append(warning_issue(
                'action_command_missing', f'{field}.id',
                f'action.command 引用了未声明的命令: {command_id}，该项已丢弃',
                escalate=True,
                hint='命令必须同时声明在 frontend.contributions.commands[]',
            ))
            return None, issues
        for key in unknown_keys(raw_action, frozenset({'type', 'id'})):
            issues.append(warning_issue(
                'action_unknown_key', f'{field}.{key}',
                f'忽略未知的 action 子键: {key}', escalate=True,
            ))
        return {'type': 'command', 'id': command_id}, issues

    url = str(raw_action.get('url') or '').strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        issues.append(warning_issue(
            'action_invalid', f'{field}.url',
            f'{field}.url 仅允许 http(s):// 绝对地址: {raw_action.get("url")!r}，该项已丢弃',
            escalate=True,
        ))
        return None, issues
    for key in unknown_keys(raw_action, frozenset({'type', 'url'})):
        issues.append(warning_issue(
            'action_unknown_key', f'{field}.{key}',
            f'忽略未知的 action 子键: {key}', escalate=True,
        ))
    return {'type': 'url', 'url': url}, issues


# ============================================================ 菜单树


def _text(value, default=''):
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return default


def _normalize_order(raw_order, *, field, issues):
    if isinstance(raw_order, bool) or not isinstance(raw_order, int):
        if raw_order is not None:
            issues.append(warning_issue(
                'order_invalid', field, f'非法的 order: {raw_order!r}，已回退默认值 {DEFAULT_ORDER}',
                escalate=True,
            ))
        return DEFAULT_ORDER
    return raw_order


def _normalize_badge(raw_badge, *, field, issues):
    if raw_badge is None:
        return None
    if isinstance(raw_badge, bool) or not isinstance(raw_badge, (str, int, float)):
        issues.append(warning_issue(
            'badge_invalid', field, f'非法的 badge: {raw_badge!r}，已忽略', escalate=True,
        ))
        return None
    return raw_badge


def _normalize_menu_node(raw_node, *, depth, field, command_ids, issues, counter):
    """归一化一个菜单节点（含子树）；非法返回 None（调用方丢弃该节点）。"""
    counter['count'] = int(counter.get('count', 0)) + 1
    if counter['count'] > MAX_MENU_NODES_PER_PLUGIN:
        if not counter.get('truncated'):
            counter['truncated'] = True
            issues.append(warning_issue(
                'menu_capacity', field,
                f'菜单节点超过单插件上限 {MAX_MENU_NODES_PER_PLUGIN}，超出部分已丢弃',
                escalate=True,
            ))
        return None

    if not isinstance(raw_node, dict):
        issues.append(warning_issue(
            'menu_node_invalid', field, f'{field} 必须是对象，已丢弃', escalate=True,
        ))
        return None

    for key in unknown_keys(raw_node, KNOWN_NODE_KEYS):
        issues.append(warning_issue(
            'menu_unknown_key', f'{field}.{key}',
            f'忽略未知的菜单节点子键: {key}', escalate=True,
            hint=f'菜单节点支持的字段：{", ".join(sorted(KNOWN_NODE_KEYS))}',
        ))

    node_id = str(raw_node.get('id') or '').strip()
    if not NODE_ID_PATTERN.match(node_id):
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.id',
            f'菜单节点 id 不符合 ^[a-z][a-z0-9-]{{0,63}}$: {raw_node.get("id")!r}，已丢弃',
            escalate=True,
        ))
        return None
    seen_ids = counter.setdefault('ids', set())
    if node_id in seen_ids:
        issues.append(warning_issue(
            'menu_id_duplicate', f'{field}.id',
            f'菜单节点 id 重复: {node_id}，已丢弃重复项', escalate=True,
        ))
        return None
    seen_ids.add(node_id)

    node_type = str(raw_node.get('type') or '').strip()
    if node_type not in MENU_NODE_TYPES:
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.type',
            f'菜单节点 type 非法: {raw_node.get("type")!r}，已丢弃', escalate=True,
            hint=f'合法取值：{", ".join(MENU_NODE_TYPES)}',
        ))
        return None

    node = {
        'id': node_id,
        'type': node_type,
        'label': _text(raw_node.get('label')),
        'description': _text(raw_node.get('description')),
        'icon': _text(raw_node.get('icon')),
        'order': _normalize_order(raw_node.get('order'), field=f'{field}.order', issues=issues),
        'when': {},
        'badge': _normalize_badge(raw_node.get('badge'), field=f'{field}.badge', issues=issues),
        'disabledHint': _text(raw_node.get('disabledHint')),
        'action': None,
        'children': [],
    }

    if depth == 0:
        placement = str(raw_node.get('placement') or '').strip()
        if not placement:
            issues.append(warning_issue(
                'menu_node_invalid', f'{field}.placement',
                '根菜单节点缺少 placement，已丢弃', escalate=True,
                hint=f'合法落点：{", ".join(MENU_PLACEMENTS)}',
            ))
            return None
        if placement not in MENU_PLACEMENTS_SET:
            issues.append(warning_issue(
                'menu_placement_unknown', f'{field}.placement',
                f'未知落点: {placement}，该节点已丢弃', escalate=True,
                hint=f'合法落点：{", ".join(MENU_PLACEMENTS)}',
            ))
            return None
        node['placement'] = placement
    elif 'placement' in raw_node:
        issues.append(warning_issue(
            'menu_placement_forbidden', f'{field}.placement',
            '子节点不允许声明 placement（落点由根节点决定），已忽略', escalate=True,
        ))

    when, when_issues = normalize_when(raw_node.get('when'), field=f'{field}.when')
    issues.extend(when_issues)
    node['when'] = when

    if node_type == 'separator':
        for key in ('label', 'action', 'children'):
            if raw_node.get(key) not in (None, '', [], {}):
                issues.append(warning_issue(
                    'menu_node_invalid', f'{field}.{key}',
                    f'separator 节点不使用 {key}，已忽略', escalate=True,
                ))
        return node

    if not node['label']:
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.label',
            f'{node_type} 节点缺少 label，已丢弃', escalate=True,
        ))
        return None

    if node_type == 'item':
        action, action_issues = normalize_action(
            raw_node.get('action'), field=f'{field}.action', command_ids=command_ids,
        )
        issues.extend(action_issues)
        if action is None:
            issues.append(warning_issue(
                'menu_node_invalid', f'{field}.action',
                f'item 节点 {node_id} 缺少合法 action，已丢弃', escalate=True,
            ))
            return None
        node['action'] = action
        if raw_node.get('children') not in (None, [], {}):
            issues.append(warning_issue(
                'menu_node_invalid', f'{field}.children',
                'item 节点不接受 children，已忽略', escalate=True,
            ))
        return node

    # submenu
    raw_children = raw_node.get('children')
    if not isinstance(raw_children, list) or not raw_children:
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.children',
            f'submenu 节点 {node_id} 缺少非空 children，已丢弃', escalate=True,
        ))
        return None
    if raw_node.get('action') not in (None, {}, []):
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.action',
            'submenu 节点不使用 action，已忽略', escalate=True,
        ))

    child_depth = depth + 1
    if child_depth >= MAX_MENU_DEPTH:
        issues.append(warning_issue(
            'menu_depth_exceeded', f'{field}.children',
            f'菜单树最大深度 {MAX_MENU_DEPTH}，更深的部分已丢弃', escalate=True,
        ))
        return None

    children = []
    for index, raw_child in enumerate(raw_children):
        child = _normalize_menu_node(
            raw_child,
            depth=child_depth,
            field=f'{field}.children[{index}]',
            command_ids=command_ids,
            issues=issues,
            counter=counter,
        )
        if child is not None:
            children.append(child)
    if not children:
        issues.append(warning_issue(
            'menu_node_invalid', f'{field}.children',
            f'submenu 节点 {node_id} 的子节点全部非法，已丢弃该节点', escalate=True,
        ))
        return None
    node['children'] = children
    return node


def normalize_menu_roots(raw_menus, *, command_ids=None, field='frontend.contributions.menus'):
    """归一化 `contributions.menus`（根节点数组，children 递归）。"""
    issues = []
    if raw_menus is None:
        return [], issues
    if not isinstance(raw_menus, list):
        issues.append(warning_issue(
            'menus_invalid', field, f'{field} 必须是数组，已忽略', escalate=True,
        ))
        return [], issues

    counter = {'count': 0, 'ids': set()}
    menus = []
    for index, raw_node in enumerate(raw_menus):
        node = _normalize_menu_node(
            raw_node,
            depth=0,
            field=f'{field}[{index}]',
            command_ids=command_ids,
            issues=issues,
            counter=counter,
        )
        if node is not None:
            menus.append(node)
    return menus, issues


def _normalize_slot(raw_slot, *, field, issues, seen_ids):
    if not isinstance(raw_slot, dict):
        issues.append(warning_issue(
            'slot_invalid', field, f'{field} 必须是对象，已丢弃', escalate=True,
        ))
        return None

    for key in unknown_keys(raw_slot, frozenset({
        'id', 'slot', 'title', 'order', 'when', 'module', 'export',
    })):
        issues.append(warning_issue(
            'slot_unknown_key', f'{field}.{key}', f'忽略未知的插槽子键: {key}', escalate=True,
        ))

    slot_id = str(raw_slot.get('id') or '').strip()
    if not NODE_ID_PATTERN.match(slot_id):
        issues.append(warning_issue(
            'slot_invalid', f'{field}.id',
            f'插槽 id 不符合 ^[a-z][a-z0-9-]{{0,63}}$: {raw_slot.get("id")!r}，已丢弃', escalate=True,
        ))
        return None
    if slot_id in seen_ids:
        issues.append(warning_issue(
            'slot_id_duplicate', f'{field}.id', f'插槽 id 重复: {slot_id}，已丢弃重复项', escalate=True,
        ))
        return None

    slot_name = str(raw_slot.get('slot') or '').strip()
    if not is_known_slot(slot_name):
        issues.append(warning_issue(
            'slot_unknown', f'{field}.slot',
            f'未知插槽: {slot_name!r}，该插槽已丢弃', escalate=True,
            hint=f'命名插槽：{", ".join(SLOT_NAMES)}；空状态插槽：{EMPTY_SLOT_PREFIX}<mode>',
        ))
        return None

    module = str(raw_slot.get('module') or '').replace('\\', '/').strip()
    if not is_relative_module_path(module):
        issues.append(warning_issue(
            'slot_invalid', f'{field}.module',
            f'module 必须是插件内相对路径: {raw_slot.get("module")!r}，该插槽已丢弃', escalate=True,
        ))
        return None

    export = str(raw_slot.get('export') or '').strip()
    if not EXPORT_NAME_PATTERN.match(export):
        issues.append(warning_issue(
            'slot_invalid', f'{field}.export',
            f'export 必须是合法标识符: {raw_slot.get("export")!r}，该插槽已丢弃', escalate=True,
        ))
        return None

    when, when_issues = normalize_when(raw_slot.get('when'), field=f'{field}.when')
    issues.extend(when_issues)
    seen_ids.add(slot_id)
    return {
        'id': slot_id,
        'slot': slot_name,
        'title': _text(raw_slot.get('title')),
        'order': _normalize_order(raw_slot.get('order'), field=f'{field}.order', issues=issues),
        'when': when,
        'module': module,
        'export': export,
    }


def normalize_slots(raw_slots, *, field='frontend.contributions.slots'):
    """归一化 `contributions.slots`（容量 16）。"""
    issues = []
    if raw_slots is None:
        return [], issues
    if not isinstance(raw_slots, list):
        issues.append(warning_issue(
            'slots_invalid', field, f'{field} 必须是数组，已忽略', escalate=True,
        ))
        return [], issues

    seen_ids = set()
    slots = []
    for index, raw_slot in enumerate(raw_slots):
        if len(slots) >= MAX_SLOTS_PER_PLUGIN:
            issues.append(warning_issue(
                'slot_capacity', field,
                f'插槽超过单插件上限 {MAX_SLOTS_PER_PLUGIN}，超出部分已丢弃', escalate=True,
            ))
            break
        slot = _normalize_slot(
            raw_slot, field=f'{field}[{index}]', issues=issues, seen_ids=seen_ids,
        )
        if slot is not None:
            slots.append(slot)
    return slots, issues


def _normalize_command(raw_command, *, field, issues, seen_ids, seen_shortcuts):
    if not isinstance(raw_command, dict):
        issues.append(warning_issue(
            'command_invalid', field, f'{field} 必须是对象，已丢弃', escalate=True,
        ))
        return None

    for key in unknown_keys(raw_command, frozenset({
        'id', 'title', 'description', 'icon', 'shortcut', 'when', 'module', 'export',
    })):
        issues.append(warning_issue(
            'command_unknown_key', f'{field}.{key}', f'忽略未知的命令子键: {key}', escalate=True,
        ))

    command_id = str(raw_command.get('id') or '').strip()
    if not NODE_ID_PATTERN.match(command_id):
        issues.append(warning_issue(
            'command_invalid', f'{field}.id',
            f'命令 id 不符合 ^[a-z][a-z0-9-]{{0,63}}$: {raw_command.get("id")!r}，已丢弃', escalate=True,
        ))
        return None
    if command_id in seen_ids:
        issues.append(warning_issue(
            'command_id_duplicate', f'{field}.id',
            f'命令 id 重复: {command_id}，已丢弃重复项', escalate=True,
        ))
        return None

    title = _text(raw_command.get('title'))
    if not title:
        issues.append(warning_issue(
            'command_invalid', f'{field}.title', '命令缺少 title，已丢弃', escalate=True,
        ))
        return None

    module = str(raw_command.get('module') or '').replace('\\', '/').strip()
    if not is_relative_module_path(module):
        issues.append(warning_issue(
            'command_invalid', f'{field}.module',
            f'module 必须是插件内相对路径: {raw_command.get("module")!r}，该命令已丢弃', escalate=True,
        ))
        return None

    export = str(raw_command.get('export') or '').strip()
    if not EXPORT_NAME_PATTERN.match(export):
        issues.append(warning_issue(
            'command_invalid', f'{field}.export',
            f'export 必须是合法标识符: {raw_command.get("export")!r}，该命令已丢弃', escalate=True,
        ))
        return None

    raw_shortcut = str(raw_command.get('shortcut') or '').strip()
    shortcut = ''
    if raw_shortcut:
        shortcut = normalize_shortcut(raw_shortcut)
        if not is_valid_shortcut(raw_shortcut):
            issues.append(warning_issue(
                'shortcut_invalid', f'{field}.shortcut',
                f'快捷键必须含 Ctrl/Alt/Meta 修饰键且格式合法: {raw_shortcut!r}，已忽略该快捷键',
                escalate=True,
            ))
            shortcut = ''
        elif shortcut in seen_shortcuts:
            issues.append(warning_issue(
                'shortcut_duplicate', f'{field}.shortcut',
                f'快捷键 {shortcut} 在同一插件内重复（保留先声明者），已忽略', escalate=True,
            ))
            shortcut = ''

    when, when_issues = normalize_when(raw_command.get('when'), field=f'{field}.when')
    issues.extend(when_issues)
    seen_ids.add(command_id)
    if shortcut:
        seen_shortcuts.add(shortcut)
    return {
        'id': command_id,
        'title': title,
        'description': _text(raw_command.get('description')),
        'icon': _text(raw_command.get('icon')),
        'shortcut': shortcut,
        'when': when,
        'module': module,
        'export': export,
    }


def normalize_commands(raw_commands, *, field='frontend.contributions.commands'):
    """归一化 `contributions.commands`（容量 32）。"""
    issues = []
    if raw_commands is None:
        return [], issues
    if not isinstance(raw_commands, list):
        issues.append(warning_issue(
            'commands_invalid', field, f'{field} 必须是数组，已忽略', escalate=True,
        ))
        return [], issues

    seen_ids = set()
    seen_shortcuts = set()
    commands = []
    for index, raw_command in enumerate(raw_commands):
        if len(commands) >= MAX_COMMANDS_PER_PLUGIN:
            issues.append(warning_issue(
                'command_capacity', field,
                f'命令超过单插件上限 {MAX_COMMANDS_PER_PLUGIN}，超出部分已丢弃', escalate=True,
            ))
            break
        command = _normalize_command(
            raw_command,
            field=f'{field}[{index}]',
            issues=issues,
            seen_ids=seen_ids,
            seen_shortcuts=seen_shortcuts,
        )
        if command is not None:
            commands.append(command)
    return commands, issues


def normalize_contributions(raw_contributions, *, field='frontend.contributions'):
    """归一化 `frontend.contributions`：命令 → 插槽 → 菜单（菜单要引用命令）。"""
    issues = []
    empty = {'menus': [], 'slots': [], 'commands': []}
    if raw_contributions is None:
        return empty, issues
    if not isinstance(raw_contributions, dict):
        issues.append(warning_issue(
            'contributions_invalid', field, f'{field} 必须是对象，已忽略', escalate=True,
        ))
        return empty, issues

    for key in unknown_keys(raw_contributions, KNOWN_CONTRIBUTION_KEYS):
        issues.append(warning_issue(
            'contributions_unknown_key', f'{field}.{key}',
            f'忽略未知的 contributions 子键: {key}', escalate=True,
            hint=f'contributions 支持的子键：{", ".join(sorted(KNOWN_CONTRIBUTION_KEYS))}',
        ))

    commands, command_issues = normalize_commands(
        raw_contributions.get('commands'), field=f'{field}.commands',
    )
    issues.extend(command_issues)
    command_ids = {item['id'] for item in commands}

    slots, slot_issues = normalize_slots(
        raw_contributions.get('slots'), field=f'{field}.slots',
    )
    issues.extend(slot_issues)

    menus, menu_issues = normalize_menu_roots(
        raw_contributions.get('menus'), command_ids=command_ids, field=f'{field}.menus',
    )
    issues.extend(menu_issues)

    return {'menus': menus, 'slots': slots, 'commands': commands}, issues


def iter_menu_nodes(menus):
    """深度优先遍历菜单节点（含子节点）。"""
    for node in menus or []:
        if not isinstance(node, dict):
            continue
        yield node
        for child in iter_menu_nodes(node.get('children') or []):
            yield child


def count_menu_nodes(menus) -> int:
    return sum(1 for _ in iter_menu_nodes(menus))


# ============================================================ 能力位 / schema


def normalize_capabilities(raw_capabilities, *, field='capabilities'):
    """归一化能力位：未知项**保留**并警告（设计 §4.7，披露不强制）。"""
    issues = []
    if raw_capabilities is None:
        return [], issues
    if not isinstance(raw_capabilities, list):
        issues.append(warning_issue(
            'capabilities_invalid', field, f'{field} 必须是数组，已忽略', escalate=True,
        ))
        return [], issues

    capabilities = []
    for index, item in enumerate(raw_capabilities):
        if not isinstance(item, str) or not item.strip():
            issues.append(warning_issue(
                'capability_invalid', f'{field}[{index}]',
                f'忽略非法的能力位: {item!r}', escalate=True,
            ))
            continue
        value = item.strip()
        if value in capabilities:
            continue
        if value not in KNOWN_CAPABILITIES:
            issues.append(warning_issue(
                'capability_unknown', f'{field}[{index}]',
                f'未知能力位（宿主保留并标注「未知名」）: {value}',
            ))
        capabilities.append(value)
    return capabilities, issues


def check_capability_consistency(render_mode, capabilities, global_styles,
                                 *, field='frontend') -> list:
    """`render_mode` / `global_styles` 与能力位的一致性（设计 §4.7）。"""
    issues = []
    declared = set(capabilities or [])
    if str(render_mode or DEFAULT_RENDER_MODE) == 'custom' and CAPABILITY_UI_CUSTOM not in declared:
        issues.append(warning_issue(
            'capability_custom_undeclared', f'{field}.render_mode',
            f'render_mode 为 custom 但未声明 {CAPABILITY_UI_CUSTOM}（宿主仍加载，披露中会标注「未声明自绘」）',
        ))
    if list(global_styles or []) and CAPABILITY_UI_GLOBAL_STYLES not in declared:
        issues.append(warning_issue(
            'global_styles_capability_missing', f'{field}.global_styles',
            f'声明了 global_styles 但缺少 {CAPABILITY_UI_GLOBAL_STYLES} 能力位，宿主将拒绝注入这些文件',
            escalate=True,
        ))
    return issues


def normalize_schema(raw_schema, *, field='config_schema'):
    """校验配置/密钥表单的 JSON Schema 子集；非法项忽略 + 警告（不阻断加载）。"""
    issues = []
    if not raw_schema:
        return {}, issues
    if not isinstance(raw_schema, dict) or raw_schema.get('type') != 'object':
        issues.append(warning_issue(
            'schema_invalid', field, f'{field} 不是 object 结构，已回退为空表单', escalate=True,
        ))
        return {}, issues

    properties = raw_schema.get('properties') or {}
    if not isinstance(properties, dict):
        issues.append(warning_issue(
            'schema_invalid', f'{field}.properties',
            f'{field}.properties 不是对象，已回退为空表单', escalate=True,
        ))
        return {}, issues

    cleaned_properties = {}
    for key, spec in properties.items():
        name = str(key or '').strip()
        if not name or not isinstance(spec, dict):
            issues.append(warning_issue(
                'schema_invalid', f'{field}.properties',
                f'{field} 中的字段 {key!r} 非法，已忽略', escalate=True,
            ))
            continue
        schema_type = spec.get('type')
        if schema_type not in SCHEMA_TYPES:
            issues.append(warning_issue(
                'schema_invalid', f'{field}.properties.{name}',
                f'{field}.{name} 的 type={schema_type!r} 不受支持，已忽略该字段', escalate=True,
            ))
            continue

        entry = {'type': schema_type}
        for option in ('title', 'description'):
            if isinstance(spec.get(option), str):
                entry[option] = spec[option]
        for option in ('minimum', 'maximum'):
            value = spec.get(option)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                entry[option] = value
        if isinstance(spec.get('default'), (str, int, float, bool)):
            entry['default'] = spec['default']
        if isinstance(spec.get('enum'), list) and spec['enum']:
            entry['enum'] = [
                item for item in spec['enum'] if isinstance(item, (str, int, float, bool))
            ]
        if bool(spec.get('secret')):
            entry['secret'] = True

        unknown = sorted(set(str(key) for key in spec.keys()) - SCHEMA_ALLOWED_KEYS)
        if unknown:
            issues.append(warning_issue(
                'schema_unknown_key', f'{field}.properties.{name}',
                f'{field}.{name} 含未支持的属性 {unknown}，已忽略', escalate=True,
            ))
        cleaned_properties[name] = entry

    cleaned = {'type': 'object', 'properties': cleaned_properties}
    required = raw_schema.get('required')
    if isinstance(required, list):
        cleaned['required'] = [
            str(item) for item in required
            if isinstance(item, str) and item in cleaned_properties
        ]
    return cleaned, issues


# ============================================================ manifest 归一化


def _normalize_string_list(raw_value, *, field, issues, allow_empty=True):
    """归一化字符串数组；非法项报错/警告并跳过。"""
    if raw_value in (None, ''):
        return []
    if not isinstance(raw_value, list):
        issues.append(error_issue('manifest_invalid_field', field, f'{field} 必须是数组'))
        return []
    result = []
    for index, item in enumerate(raw_value):
        if not isinstance(item, str) or not item.strip():
            issues.append(warning_issue(
                'manifest_invalid_field', f'{field}[{index}]',
                f'{field} 只能是非空字符串，已忽略该项', escalate=True,
            ))
            continue
        value = item.strip()
        if value not in result:
            result.append(value)
    return result


def _normalize_relative_path(value, *, field, issues):
    text = str(value or '').replace('\\', '/').strip()
    if not text:
        return ''
    if not is_relative_module_path(text):
        issues.append(error_issue(
            'manifest_invalid_field', field,
            f'{field} 必须是插件内相对路径: {value!r}',
        ))
        return ''
    return text.lstrip('/')


def validate_manifest(payload, *, strict=False):
    """校验并按 v3 归一化一份 manifest。

    Returns:
        `(normalized, issues)`：`normalized` 是补齐默认值后的字典（即使有 error 也尽力返回），
        `issues` 是 `make_issue` 形状的列表；`strict=True` 时宿主容忍项升级为 error。
    """
    issues = []
    normalized = {
        'id': '',
        'name': '',
        'version': '',
        'api_version': 0,
        'manifest_version': 0,
        'author': '',
        'description': '',
        'homepage': '',
        'license': '',
        'icon': '',
        'min_app_version': '',
        'backend': None,
        'frontend': None,
        'capabilities': [],
        'requires': {},
        'config_schema': {},
        'secret_schema': {},
        'i18n': {},
    }

    if not isinstance(payload, dict):
        issues.append(error_issue('manifest_invalid', '', 'manifest 顶层必须是对象'))
        return normalized, finalize_issues(issues, strict=strict)

    # 结构键白名单：拼错字段名要立刻暴露（设计 §4.1 / §4.9）
    unknown = unknown_keys(payload, KNOWN_TOP_LEVEL_KEYS)
    if unknown:
        field = unknown[0]
        issues.append(error_issue(
            'manifest_unknown_key', field, f'manifest 中存在未知字段 {field}',
            hint=f'顶层支持的字段：{", ".join(sorted(KNOWN_TOP_LEVEL_KEYS))}',
        ))

    raw_id = payload.get('id')
    plugin_id = str(raw_id or '').strip()
    if not PLUGIN_ID_PATTERN.match(plugin_id):
        issues.append(error_issue(
            'manifest_invalid_id', 'id',
            f'id 不符合 ^[a-z][a-z0-9-]{{1,63}}$: {raw_id!r}',
        ))
    normalized['id'] = plugin_id
    normalized['name'] = str(payload.get('name') or plugin_id).strip() or plugin_id

    version = str(payload.get('version') or '').strip()
    if parse_semver(version) is None:
        issues.append(error_issue(
            'manifest_invalid_version', 'version',
            f'version 不是合法语义化版本: {payload.get("version")!r}',
        ))
    normalized['version'] = version

    raw_manifest_version = payload.get('manifest_version')
    if isinstance(raw_manifest_version, bool) or not isinstance(raw_manifest_version, int):
        issues.append(error_issue(
            'manifest_version_unsupported', 'manifest_version',
            f'manifest_version 必须是整数: {raw_manifest_version!r}',
            hint=f'支持的 manifest 版本：{list(SUPPORTED_MANIFEST_VERSIONS)}',
        ))
    elif raw_manifest_version not in SUPPORTED_MANIFEST_VERSIONS:
        issues.append(error_issue(
            'manifest_version_unsupported', 'manifest_version',
            f'manifest_version 不受支持: {raw_manifest_version!r}',
            hint=f'支持的 manifest 版本：{list(SUPPORTED_MANIFEST_VERSIONS)}',
        ))
        normalized['manifest_version'] = raw_manifest_version
    else:
        normalized['manifest_version'] = raw_manifest_version

    raw_api_version = payload.get('api_version')
    if isinstance(raw_api_version, bool) or not isinstance(raw_api_version, int):
        issues.append(error_issue(
            'api_version_unsupported', 'api_version',
            f'api_version 必须是整数: {raw_api_version!r}',
            hint=f'当前主程序支持 api_version {list(SUPPORTED_API_VERSIONS)}',
        ))
    elif raw_api_version not in SUPPORTED_API_VERSIONS:
        issues.append(error_issue(
            'api_version_unsupported', 'api_version',
            f'插件需要 api_version {raw_api_version}，当前主程序仅支持 '
            f'{list(SUPPORTED_API_VERSIONS)}（需更新主程序）',
            hint=f'当前主程序支持 api_version {list(SUPPORTED_API_VERSIONS)}',
        ))
        normalized['api_version'] = raw_api_version
    else:
        normalized['api_version'] = raw_api_version

    min_app_version = str(payload.get('min_app_version') or '').strip()
    if min_app_version and parse_semver(min_app_version) is None:
        issues.append(error_issue(
            'manifest_invalid_field', 'min_app_version',
            f'min_app_version 不是合法语义化版本（不带比较符）: {min_app_version!r}',
        ))
    normalized['min_app_version'] = min_app_version

    for key in ('author', 'description', 'homepage', 'license'):
        normalized[key] = str(payload.get(key) or '').strip()
    normalized['icon'] = str(payload.get('icon') or '').strip()

    if payload.get('i18n') is not None and not isinstance(payload.get('i18n'), dict):
        issues.append(warning_issue(
            'manifest_invalid_field', 'i18n', 'i18n 必须是对象，已忽略', escalate=True,
        ))
    elif isinstance(payload.get('i18n'), dict):
        normalized['i18n'] = dict(payload['i18n'])

    # ---------------- backend ----------------
    raw_backend = payload.get('backend')
    if raw_backend is not None and not isinstance(raw_backend, dict):
        issues.append(error_issue('manifest_invalid_field', 'backend', 'backend 必须是对象'))
        raw_backend = None
    if isinstance(raw_backend, dict):
        for key in unknown_keys(raw_backend, KNOWN_BACKEND_KEYS):
            issues.append(error_issue(
                'manifest_unknown_key', f'backend.{key}', f'manifest 中存在未知字段 backend.{key}',
                hint=f'backend 支持的字段：{", ".join(sorted(KNOWN_BACKEND_KEYS))}',
            ))
        entry_name = str(raw_backend.get('entry') or '').replace('\\', '/').strip().strip('/')
        if not entry_name or not all(
            ENTRY_NAME_PATTERN.match(part) for part in entry_name.split('/')
        ):
            issues.append(error_issue(
                'manifest_invalid_field', 'backend.entry',
                f'backend.entry 非法: {raw_backend.get("entry")!r}',
            ))
            entry_name = ''
        register = str(raw_backend.get('register') or 'register').strip() or 'register'
        if not ENTRY_NAME_PATTERN.match(register):
            issues.append(error_issue(
                'manifest_invalid_field', 'backend.register',
                f'backend.register 非法: {register!r}',
            ))
            register = 'register'
        jobs = _normalize_string_list(
            raw_backend.get('jobs'), field='backend.jobs', issues=issues,
        )
        for job_type in list(jobs):
            if not JOB_TYPE_PATTERN.match(job_type):
                issues.append(error_issue(
                    'manifest_invalid_field', 'backend.jobs', f'backend.jobs 项非法: {job_type!r}',
                ))
                jobs.remove(job_type)
        hooks = []
        for hook_name in _normalize_string_list(
            raw_backend.get('hooks'), field='backend.hooks', issues=issues,
        ):
            if hook_name not in KNOWN_HOOKS:
                issues.append(warning_issue(
                    'hook_unknown', 'backend.hooks', f'忽略未知 hook: {hook_name}',
                ))
                continue
            hooks.append(hook_name)
        normalized['backend'] = {
            'entry': entry_name,
            'register': register,
            'jobs': jobs,
            'hooks': hooks,
        }

    # ---------------- frontend ----------------
    raw_frontend = payload.get('frontend')
    if raw_frontend is not None and not isinstance(raw_frontend, dict):
        issues.append(error_issue('manifest_invalid_field', 'frontend', 'frontend 必须是对象'))
        raw_frontend = None
    if isinstance(raw_frontend, dict):
        legacy = [key for key in LEGACY_FRONTEND_KEYS if key in raw_frontend]
        if legacy:
            issues.append(error_issue(
                'manifest_legacy_key', f'frontend.{legacy[0]}',
                f'manifest 中存在已废弃字段 frontend.{legacy[0]}',
                hint=LEGACY_FRONTEND_HINT,
            ))
        for key in unknown_keys(raw_frontend, KNOWN_FRONTEND_KEYS):
            issues.append(error_issue(
                'manifest_unknown_key', f'frontend.{key}',
                f'manifest 中存在未知字段 frontend.{key}',
                hint=f'frontend 支持的字段：{", ".join(sorted(KNOWN_FRONTEND_KEYS))}',
            ))

        entry = _normalize_relative_path(
            raw_frontend.get('entry'), field='frontend.entry', issues=issues,
        )
        styles = [
            _normalize_relative_path(item, field='frontend.styles', issues=issues)
            for item in _normalize_string_list(
                raw_frontend.get('styles'), field='frontend.styles', issues=issues,
            )
        ]
        styles = [item for item in styles if item]
        global_styles = [
            _normalize_relative_path(item, field='frontend.global_styles', issues=issues)
            for item in _normalize_string_list(
                raw_frontend.get('global_styles'), field='frontend.global_styles', issues=issues,
            )
        ]
        global_styles = [item for item in global_styles if item]

        render_mode = str(raw_frontend.get('render_mode') or '').strip()
        if not render_mode:
            render_mode = DEFAULT_RENDER_MODE
        elif render_mode not in RENDER_MODES:
            issues.append(warning_issue(
                'render_mode_invalid', 'frontend.render_mode',
                f'未知的 render_mode: {render_mode!r}，已回退 {DEFAULT_RENDER_MODE}',
                escalate=True,
                hint=f'合法取值：{", ".join(RENDER_MODES)}',
            ))
            render_mode = DEFAULT_RENDER_MODE

        raw_contributions = raw_frontend.get('contributions')
        if raw_contributions is not None and not isinstance(raw_contributions, dict):
            issues.append(error_issue(
                'contributions_invalid', 'frontend.contributions',
                'frontend.contributions 必须是对象',
            ))
            raw_contributions = None
        contributions, contribution_issues = normalize_contributions(
            raw_contributions, field='frontend.contributions',
        )
        issues.extend(contribution_issues)

        normalized['frontend'] = {
            'entry': entry,
            'styles': styles,
            'global_styles': global_styles,
            'render_mode': render_mode,
            'contributions': contributions,
        }

    if not normalized['backend'] and not normalized['frontend']:
        issues.append(error_issue(
            'manifest_invalid_field', '',
            'backend 与 frontend 至少要有一个',
        ))

    # ---------------- 能力位 / 依赖 ----------------
    capabilities, capability_issues = normalize_capabilities(payload.get('capabilities'))
    issues.extend(capability_issues)
    normalized['capabilities'] = capabilities

    global_styles = (normalized['frontend'] or {}).get('global_styles') or []
    render_mode = (normalized['frontend'] or {}).get('render_mode') or DEFAULT_RENDER_MODE
    issues.extend(check_capability_consistency(render_mode, capabilities, global_styles))

    raw_requires = payload.get('requires')
    if raw_requires is not None and not isinstance(raw_requires, dict):
        issues.append(warning_issue(
            'requires_invalid', 'requires',
            'requires 必须是对象（{plugin_id: 版本约束}），已忽略', escalate=True,
        ))
    elif isinstance(raw_requires, dict):
        for raw_dep_id, raw_constraint in raw_requires.items():
            dep_id = str(raw_dep_id or '').strip()
            constraint = str(raw_constraint or '').strip()
            if not PLUGIN_ID_PATTERN.match(dep_id):
                issues.append(warning_issue(
                    'requires_invalid', f'requires.{dep_id}',
                    f'忽略非法依赖 id: {raw_dep_id!r}', escalate=True,
                ))
                continue
            if dep_id == plugin_id:
                issues.append(warning_issue(
                    'requires_invalid', f'requires.{dep_id}', '忽略对自身的依赖声明', escalate=True,
                ))
                continue
            if parse_requirement(constraint) is None:
                issues.append(warning_issue(
                    'requires_invalid', f'requires.{dep_id}',
                    f'忽略依赖 {dep_id} 的非法版本约束: {constraint!r}', escalate=True,
                ))
                continue
            normalized['requires'][dep_id] = constraint

    normalized['config_schema'], schema_issues = normalize_schema(
        payload.get('config_schema'), field='config_schema',
    )
    issues.extend(schema_issues)
    normalized['secret_schema'], secret_issues = normalize_schema(
        payload.get('secret_schema'), field='secret_schema',
    )
    issues.extend(secret_issues)

    return normalized, finalize_issues(issues, strict=strict)
# <<< END GENERATED: core/plugins/contract.py <<<
# >>> BEGIN GENERATED: host facts (core/version.py + static/icons) >>>
# 生成区：宿主事实（CLI 脱离宿主仓库运行时的参照，勿手改）。
# 来源：`core/version.py` 的 APP_VERSION、`static/icons/*.svg` 的 `id="icon-*"`
# 与模板别名表（与 `static/js/utils/iconMap.js` 同一份来源）。
HOST_APP_VERSION = '1.0.0'

# 合法宿主图标名（含模板别名）；未知名字只算 warning：宿主会渲染占位图标。
HOST_ICON_NAMES = frozenset({
    'alert-triangle',
    'archive-new',
    'archive-old',
    'arrow-down',
    'arrow-left',
    'arrow-left-outline',
    'arrow-right',
    'arrow-up',
    'arrow-up-left',
    'backup-rollback',
    'ban',
    'beautify-details',
    'beautify-dual',
    'beautify-mobile',
    'beautify-pc',
    'beautify-screenshot',
    'beautify-user',
    'beautify-variant-atomic',
    'bolt',
    'book-backup',
    'book-closed',
    'book-open',
    'book-read',
    'book-save',
    'book-save-as',
    'book-stack',
    'book-tip',
    'broom',
    'calendar',
    'card-forum-search',
    'card-send-to-st',
    'card-update-check',
    'cards-grid',
    'character-cards',
    'character-description',
    'character-personality',
    'chat-bubble',
    'chat-empty',
    'chat-examples',
    'chat-history',
    'chat-reader-render',
    'check',
    'check-bold',
    'chevron-down',
    'chevron-right',
    'circle-dot',
    'clipboard',
    'clock',
    'close',
    'close-bold',
    'close-small',
    'code-file',
    'collapse',
    'cover-image',
    'data-grid',
    'database-backup',
    'database-user',
    'definition-after',
    'definition-before',
    'dialog',
    'directory-root',
    'directory-tree',
    'discord',
    'display',
    'edit-mode',
    'editor',
    'empty-state',
    'entry-rollback',
    'expand',
    'external-link',
    'eye',
    'eye-off',
    'file',
    'file-check',
    'file-code',
    'file-current',
    'file-edit',
    'file-embedded',
    'file-import',
    'file-name',
    'filter',
    'flask',
    'folder',
    'folder-create',
    'folder-open',
    'folder-path',
    'folder-resources',
    'folder-root',
    'folder-search',
    'folder-solid',
    'folder-sync',
    'forbidden',
    'fullscreen',
    'github',
    'grid',
    'header-dark-mode',
    'header-light-mode',
    'heart',
    'heart-broken',
    'history-rollback',
    'idea',
    'image',
    'image-keep',
    'image-replace',
    'info',
    'isolate',
    'key',
    'key-snapshot',
    'key-trigger',
    'keyboard',
    'layers',
    'layout',
    'leaf-wind',
    'link-bound',
    'link-import',
    'link-source',
    'link-unbound',
    'list',
    'locate',
    'locate-jump',
    'lock',
    'manage',
    'maximize',
    'menu',
    'menu-bold',
    'menu-category',
    'merge',
    'metadata',
    'minus',
    'monitor-user',
    'note',
    'organize',
    'overwrite',
    'owner',
    'package',
    'paint-brush',
    'pencil-edit',
    'persona',
    'persona-description',
    'pin',
    'play',
    'plug',
    'plugin',
    'plus',
    'plus-square',
    'preset',
    'prompt-count',
    'quick-actions',
    'quick-reply',
    'refresh',
    'regex',
    'replace',
    'reset',
    'resource',
    'resource-settings',
    'resources',
    'rules',
    'scan',
    'scenario',
    'scissors',
    'script-file',
    'search',
    'send-content',
    'settings',
    'settings-connection-service',
    'settings-gear',
    'settings-help-entry',
    'settings-maintenance',
    'settings-maintenance-advanced',
    'settings-save',
    'shield',
    'shield-check',
    'shield-key',
    'sillytavern',
    'sliders-settings',
    'snapshot',
    'sort',
    'sticky-note',
    'tag-library',
    'tags',
    'tauritavern',
    'thermometer',
    'token-count',
    'toolbox',
    'trash',
    'unisolate',
    'update',
    'update-policy',
    'upload',
    'user',
    'version',
    'vertical-flip',
    'volume-off',
    'volume-on',
    'wallpaper',
    'wand',
    'workflow',
})
# <<< END GENERATED: host facts <<<

import argparse
import json
import os
import re
import sys

# ============================================================ 检查项元数据

CHECK_DEFINITIONS = (
    (1, 'manifest', 'manifest JSON / 大小 / 字段白名单 / 契约版本'),
    (2, 'structure', '落点、插槽、数量/深度/容量、id 唯一'),
    (3, 'action', 'action 引用（command / surface / url）'),
    (4, 'modules', '模块与导出静态检查'),
    (5, 'condition', 'when 条件与 shortcut'),
    (6, 'capability', 'render_mode / capabilities / global_styles 一致性'),
    (7, 'css', 'CSS 作用域扫描'),
    (8, 'icons', '图标名与资源存在性'),
    (9, 'version', '契约版本提示'),
)

#: 契约 issue 的 code → 检查项编号（用于把 contract 的问题归到 9 条检查里）。
_ISSUE_CHECK_PREFIXES = (
    ('manifest_version', 1),
    ('api_version', 1),
    ('manifest_', 1),
    ('shortcut_', 5),
    ('when_', 5),
    ('action_', 3),
    ('slot_', 2),
    ('command_', 2),
    ('menu_', 2),
    ('contributions_', 2),
    ('order_', 2),
    ('badge_', 2),
    ('render_mode_', 6),
    ('global_styles_', 6),
    ('capabilities_', 6),
    ('capability_', 6),
)


def _check_for_code(code):
    text = str(code or '')
    for prefix, check in _ISSUE_CHECK_PREFIXES:
        if text.startswith(prefix):
            return check
    return 1


# ============================================================ 结果收集


class _Report:
    """收集全部问题（带检查项编号、字段路径、行号、hint）。"""

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.issues = []

    def add(self, severity, check, code, field, message, *, line=None, hint=''):
        self.issues.append({
            'severity': str(severity),
            'check': int(check),
            'code': str(code or ''),
            'field': str(field or ''),
            'message': str(message or ''),
            'hint': str(hint or ''),
            'line': int(line) if isinstance(line, int) and line > 0 else None,
        })

    def error(self, check, code, field, message, *, line=None, hint=''):
        self.add(SEVERITY_ERROR, check, code, field, message, line=line, hint=hint)

    def warning(self, check, code, field, message, *, line=None, hint=''):
        self.add(SEVERITY_WARNING, check, code, field, message, line=line, hint=hint)


def _build_result(report, plugin_id):
    checks = []
    for check_id, name, title in CHECK_DEFINITIONS:
        related = [item for item in report.issues if item['check'] == check_id]
        errors = sum(1 for item in related if item['severity'] == SEVERITY_ERROR)
        warnings = sum(1 for item in related if item['severity'] == SEVERITY_WARNING)
        status = 'fail' if errors else ('warn' if warnings else 'pass')
        checks.append({
            'id': check_id,
            'name': name,
            'title': title,
            'status': status,
            'error_count': errors,
            'warning_count': warnings,
        })
    errors_total = sum(1 for item in report.issues if item['severity'] == SEVERITY_ERROR)
    warnings_total = sum(1 for item in report.issues if item['severity'] == SEVERITY_WARNING)
    return {
        'tool': 'stm-plugin-check',
        'contract_version': API_VERSION,
        'host_app_version': HOST_APP_VERSION,
        'plugin_dir': report.plugin_dir,
        'plugin_id': plugin_id,
        'ok': errors_total == 0,
        'error_count': errors_total,
        'warning_count': warnings_total,
        'checks': checks,
        'issues': report.issues,
    }


# ============================================================ manifest 读取与行号定位


class _JsonLineIndex:
    """扫描 manifest 文本，记录「JSON 路径 → 起始行号」。

    只用标准库、不依赖第三方；解析失败时尽力返回已记录的路径（错误本身由
    `json.loads` 报告行号）。行号是**提示**，用于把契约 issue 指回文件位置。
    """

    def __init__(self, text):
        self.text = str(text or '')
        self.length = len(self.text)
        self.pos = 0
        self.line = 1
        self.lines = {}

    def build(self):
        try:
            self._skip_ws()
            self._value(())
        except (IndexError, ValueError):
            pass
        return self.lines

    def _skip_ws(self):
        while self.pos < self.length:
            char = self.text[self.pos]
            if char == '\n':
                self.line += 1
                self.pos += 1
            elif char in ' \t\r':
                self.pos += 1
            else:
                return

    def _value(self, path):
        self._skip_ws()
        if self.pos >= self.length:
            return
        char = self.text[self.pos]
        if char == '{':
            self._object(path)
        elif char == '[':
            self._array(path)
        elif char == '"':
            self.lines.setdefault(path, self.line)
            self._scan_string()
        else:
            self.lines.setdefault(path, self.line)
            self._scan_scalar()

    def _object(self, path):
        self.lines.setdefault(path, self.line)
        self.pos += 1
        self._skip_ws()
        if self.pos < self.length and self.text[self.pos] == '}':
            self.pos += 1
            return
        while self.pos < self.length:
            self._skip_ws()
            key_line = self.line
            key = self._scan_string()
            key_path = path + (key,)
            self.lines.setdefault(key_path, key_line)
            self._skip_ws()
            self.pos += 1  # ':'
            self._value(key_path)
            self._skip_ws()
            if self.pos >= self.length:
                return
            char = self.text[self.pos]
            self.pos += 1
            if char == ',':
                continue
            return

    def _array(self, path):
        self.lines.setdefault(path, self.line)
        self.pos += 1
        self._skip_ws()
        if self.pos < self.length and self.text[self.pos] == ']':
            self.pos += 1
            return
        index = 0
        while self.pos < self.length:
            self._value(path + (index,))
            index += 1
            self._skip_ws()
            if self.pos >= self.length:
                return
            char = self.text[self.pos]
            self.pos += 1
            if char == ',':
                continue
            return

    def _scan_string(self):
        self.pos += 1  # 开引号
        chars = []
        while self.pos < self.length:
            char = self.text[self.pos]
            if char == '\\':
                if self.pos + 1 >= self.length:
                    break
                nxt = self.text[self.pos + 1]
                if nxt == 'u':
                    hex_text = self.text[self.pos + 2:self.pos + 6]
                    try:
                        chars.append(chr(int(hex_text, 16)))
                    except ValueError:
                        pass
                    self.pos += 6
                    continue
                mapping = {
                    '"': '"', '\\': '\\', '/': '/', 'n': '\n',
                    't': '\t', 'r': '\r', 'b': '\b', 'f': '\f',
                }
                chars.append(mapping.get(nxt, nxt))
                self.pos += 2
                continue
            if char == '"':
                self.pos += 1
                return ''.join(chars)
            if char == '\n':
                self.line += 1
            chars.append(char)
            self.pos += 1
        return ''.join(chars)

    def _scan_scalar(self):
        while self.pos < self.length:
            if self.text[self.pos] in ',}] \t\r\n':
                return
            self.pos += 1


_FIELD_TOKEN_PATTERN = re.compile(r'([A-Za-z0-9_-]+)|\[(\d+)\]')


def _field_path(field):
    tokens = []
    for match in _FIELD_TOKEN_PATTERN.finditer(str(field or '')):
        if match.group(1) is not None:
            tokens.append(match.group(1))
        else:
            tokens.append(int(match.group(2)))
    return tuple(tokens)


def _locate_line(lines, field):
    """把契约 issue 的字段路径映射回 manifest 行号（找不到时退到最近祖先）。"""
    if not lines:
        return None
    path = _field_path(field)
    while path:
        if path in lines:
            return lines[path]
        path = path[:-1]
    return lines.get(())


def _read_manifest(report):
    """读取并解析 manifest.json；返回 `(payload, lines)`，失败时 payload 为 None。"""
    manifest_path = os.path.join(report.plugin_dir, 'manifest.json')
    field = 'manifest.json'
    if not os.path.isfile(manifest_path):
        report.error(1, 'manifest_missing', field, '插件目录缺少 manifest.json')
        return None, {}
    try:
        size = os.path.getsize(manifest_path)
    except OSError as exc:
        report.error(1, 'manifest_unreadable', field, f'无法读取 manifest.json: {exc}')
        return None, {}
    if size > MAX_MANIFEST_BYTES:
        report.error(
            1, 'manifest_too_large', field,
            f'manifest.json 超过 {MAX_MANIFEST_BYTES} 字节上限（当前 {size} 字节），宿主会拒绝加载',
        )
    try:
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        report.error(1, 'manifest_unreadable', field, f'manifest.json 读取失败: {exc}')
        return None, {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(
            1, 'manifest_invalid_json', field,
            f'manifest.json 不是合法 JSON: {exc.msg}', line=exc.lineno,
        )
        return None, {}
    lines = _JsonLineIndex(text).build()
    if not isinstance(payload, dict):
        report.error(1, 'manifest_invalid', field, 'manifest 顶层必须是 JSON 对象', line=1)
        return None, lines
    return payload, lines


def _apply_contract_issues(report, issues, lines):
    """把 `contract.validate_manifest(strict=True)` 的问题并入报告。"""
    for issue in issues or []:
        field = issue.get('field') or ''
        report.add(
            issue.get('severity') or SEVERITY_ERROR,
            _check_for_code(issue.get('code')),
            issue.get('code'),
            field,
            issue.get('message'),
            line=_locate_line(lines, field),
            hint=issue.get('hint') or '',
        )


# ============================================================ 静态文件检查（检查项 4 / 7 / 8）


def _plugin_relative_path(plugin_dir, relative):
    """把插件相对路径解析为绝对路径；越界返回 None，空路径返回 ''。"""
    text = str(relative or '').replace('\\', '/').strip()
    if not text:
        return ''
    root = os.path.abspath(plugin_dir)
    candidate = os.path.abspath(os.path.join(root, text))
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _module_exports_name(source, name):
    """静态文本检查模块是否导出 `name`（ES module 为主，兼容 CommonJS 写法）。"""
    text = str(source or '')
    export_name = str(name or '')
    if not export_name:
        return False
    if export_name == 'default':
        return bool(re.search(r'\bexport\s+default\b', text))
    escaped = re.escape(export_name)
    patterns = (
        re.compile(
            r'\bexport\s+(?:async\s+)?(?:function\s*\*?|const|let|var|class)\s+'
            + escaped + r'\b'
        ),
        re.compile(r'\bexport\s*\{[^}]*\b' + escaped + r'\b[^}]*\}', re.S),
        re.compile(r'\b(?:module\.)?exports\.' + escaped + r'\s*='),
    )
    return any(pattern.search(text) for pattern in patterns)


def _check_module_export(report, plugin_dir, module, export_name, *,
                         module_field, export_field, lines):
    path = _plugin_relative_path(plugin_dir, module)
    if path is None:
        report.error(
            4, 'module_path_invalid', module_field,
            f'模块路径必须是插件内相对路径（不允许绝对路径或 ..）: {module!r}',
            line=_locate_line(lines, module_field),
        )
        return
    if not path:
        report.error(
            4, 'module_missing', module_field, '缺少模块路径',
            line=_locate_line(lines, module_field),
        )
        return
    if not os.path.isfile(path):
        report.error(
            4, 'module_missing', module_field,
            f'模块文件不存在: {module}（相对插件根目录）',
            line=_locate_line(lines, module_field),
        )
        return
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
    except OSError as exc:
        report.error(
            4, 'module_unreadable', module_field, f'模块读取失败: {module} ({exc})',
            line=_locate_line(lines, module_field),
        )
        return
    if not _module_exports_name(source, export_name):
        report.error(
            4, 'module_export_missing', export_field,
            f'模块 {module} 中没有导出 {export_name!r}（宿主动态 import 后取不到，插件会被降级）',
            line=_locate_line(lines, export_field),
        )


def _check_asset_exists(report, plugin_dir, relative, *, field, code, lines):
    path = _plugin_relative_path(plugin_dir, relative)
    if path is None:
        report.error(
            4, code + '_path_invalid', field,
            f'路径必须是插件内相对路径（不允许绝对路径或 ..）: {relative!r}',
            line=_locate_line(lines, field),
        )
        return None
    if path and not os.path.isfile(path):
        report.error(
            4, code, field, f'文件不存在: {relative}（相对插件根目录）',
            line=_locate_line(lines, field),
        )
        return None
    return path or None


def _check_static_assets(report, plugin_dir, normalized, lines):
    """检查项 4：frontend 入口 / 样式 / contributions 模块与导出。"""
    frontend = normalized.get('frontend')
    if not frontend:
        return
    entry = frontend.get('entry') or ''
    if entry:
        _check_module_export(
            report, plugin_dir, entry, 'activate',
            module_field='frontend.entry', export_field='frontend.entry', lines=lines,
        )
    elif frontend.get('styles') or frontend.get('global_styles') or any(
        (frontend.get('contributions') or {}).get(key)
        for key in ('menus', 'slots', 'commands')
    ):
        report.warning(
            4, 'frontend_entry_missing', 'frontend.entry',
            '声明了 frontend 内容但没有 frontend.entry（宿主不会加载/激活该插件前端）',
            line=_locate_line(lines, 'frontend.entry'),
        )

    for index, relative in enumerate(frontend.get('styles') or []):
        _check_asset_exists(
            report, plugin_dir, relative,
            field=f'frontend.styles[{index}]', code='style_missing', lines=lines,
        )
    for index, relative in enumerate(frontend.get('global_styles') or []):
        _check_asset_exists(
            report, plugin_dir, relative,
            field=f'frontend.global_styles[{index}]', code='global_style_missing', lines=lines,
        )

    contributions = frontend.get('contributions') or {}
    for index, slot in enumerate(contributions.get('slots') or []):
        _check_module_export(
            report, plugin_dir, slot.get('module'), slot.get('export'),
            module_field=f'frontend.contributions.slots[{index}].module',
            export_field=f'frontend.contributions.slots[{index}].export',
            lines=lines,
        )
    for index, command in enumerate(contributions.get('commands') or []):
        _check_module_export(
            report, plugin_dir, command.get('module'), command.get('export'),
            module_field=f'frontend.contributions.commands[{index}].module',
            export_field=f'frontend.contributions.commands[{index}].export',
            lines=lines,
        )


_CSS_SKIP_BLOCKS = ('@media', '@supports', '@layer', '@container', '@keyframes', '@font-face')


def _is_keyframe_selector(selector):
    """`0%` / `from` / `to` 这类关键帧步骤选择器。"""
    first = str(selector or '').split(',', 1)[0].strip().lower()
    return first in ('from', 'to') or bool(re.match(r'^\d+(\.\d+)?%$', first))


def scan_css_scope(css_path, plugin_id):
    """与宿主 `core/plugins/installer.py:scan_css_scope` 同一规则的静态扫描。

    Returns:
        `(violations, read_error)`：`violations` 是未以插件作用域开头的选择器
        列表；`read_error` 是读取失败信息（成功为 ''）。
    """
    plugin_id = str(plugin_id or '')
    filename = os.path.basename(str(css_path or '')) or 'style.css'
    try:
        with open(css_path, 'r', encoding='utf-8') as handle:
            source = handle.read()
    except OSError as exc:
        return [], f'{filename}: 读取失败 ({exc})'
    if not plugin_id:
        return [], f'{filename}: 缺少插件 id'

    scope_tokens = (
        f'.plugin-{plugin_id}',
        f'[data-plugin="{plugin_id}"]',
        f"[data-plugin='{plugin_id}']",
    )

    violations = []
    stack = []
    buffer = []
    skip_blocks = 0
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == '/' and index + 1 < length and source[index + 1] == '*':
            end = source.find('*/', index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == '{':
            selector = ''.join(buffer).strip()
            buffer = []
            head = selector.split(None, 1)[0].lower() if selector else ''
            if head.startswith('@'):
                if head in _CSS_SKIP_BLOCKS:
                    skip_blocks += 1
                stack.append(head)
            else:
                if skip_blocks == 0 and selector and not any(
                    token in selector for token in scope_tokens
                ):
                    if not _is_keyframe_selector(selector):
                        violations.append(selector)
                stack.append('')
            index += 1
            continue
        if char == '}':
            if stack:
                head = stack.pop()
                if head.startswith('@') and head in _CSS_SKIP_BLOCKS:
                    skip_blocks = max(0, skip_blocks - 1)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    return violations, ''


def _check_css_scope(report, plugin_dir, normalized, lines):
    """检查项 7：`frontend.styles[]` 全部按插件作用域扫描；global_styles 豁免。"""
    frontend = normalized.get('frontend') or {}
    plugin_id = str(normalized.get('id') or '')
    for index, relative in enumerate(frontend.get('styles') or []):
        field = f'frontend.styles[{index}]'
        path = _plugin_relative_path(plugin_dir, relative)
        if not path or not os.path.isfile(path):
            continue  # 文件缺失已由检查项 4 报告
        violations, read_error = scan_css_scope(path, plugin_id)
        if read_error:
            report.error(
                7, 'css_read_error', field, read_error,
                line=_locate_line(lines, field),
            )
            continue
        for selector in violations:
            report.error(
                7, 'css_unscoped', field,
                f'选择器未以 .plugin-{plugin_id} 或 [data-plugin="{plugin_id}"] 为根作用域，'
                f'宿主会拒绝注入该样式: {selector}',
                line=_locate_line(lines, field),
            )


# ============================================================ 图标检查（检查项 8）


def _is_host_icon_name(value):
    """不含 `/`、`\\`、`.` 的取值 = 宿主图标名（与前端 `isHostIconName` 一致）。"""
    text = str(value or '').strip()
    if not text:
        return False
    return '/' not in text and '\\' not in text and '.' not in text


def _check_icon_value(report, plugin_dir, value, field, lines):
    text = str(value or '').strip()
    if not text:
        return
    if _is_host_icon_name(text):
        if text not in HOST_ICON_NAMES:
            report.warning(
                8, 'icon_unknown', field,
                f'未知宿主图标名: {text}（宿主会渲染占位图标；宿主图标名清单见 docs/plugin-api.md）',
                line=_locate_line(lines, field),
            )
        return
    path = _plugin_relative_path(plugin_dir, text)
    if path is None:
        report.error(
            8, 'icon_path_invalid', field,
            f'插件内图标路径非法（不允许绝对路径或 ..）: {text}',
            line=_locate_line(lines, field),
        )
        return
    if path and not os.path.isfile(path):
        report.error(
            8, 'icon_missing', field, f'插件内图标文件不存在: {text}',
            line=_locate_line(lines, field),
        )


def _walk_menu_nodes(menus, prefix):
    """深度优先遍历菜单节点，同时给出该节点在 manifest 里的字段路径。"""
    for index, node in enumerate(menus or []):
        if not isinstance(node, dict):
            continue
        field = f'{prefix}[{index}]'
        yield node, field
        for pair in _walk_menu_nodes(node.get('children') or [], f'{field}.children'):
            yield pair


def _check_icons(report, plugin_dir, payload, normalized, lines):
    _check_icon_value(report, plugin_dir, payload.get('icon'), 'icon', lines)
    contributions = (normalized.get('frontend') or {}).get('contributions') or {}
    for node, field in _walk_menu_nodes(
        contributions.get('menus') or [], 'frontend.contributions.menus',
    ):
        _check_icon_value(report, plugin_dir, node.get('icon'), f'{field}.icon', lines)
    for index, command in enumerate(contributions.get('commands') or []):
        _check_icon_value(
            report, plugin_dir, command.get('icon'),
            f'frontend.contributions.commands[{index}].icon', lines,
        )


# ============================================================ 容量提示与版本提示（检查项 2 / 9）


def _check_dock_capacity(report, normalized, lines):
    """dock 落点单插件上限（超出进「更多」浮层，不丢弃 → warning）。"""
    contributions = (normalized.get('frontend') or {}).get('contributions') or {}
    menus = contributions.get('menus') or []
    dock_roots = [node for node in menus if node.get('placement') == 'dock']
    if len(dock_roots) > MAX_DOCK_PER_PLUGIN:
        report.warning(
            2, 'dock_capacity', 'frontend.contributions.menus',
            f'dock 落点单插件最多 {MAX_DOCK_PER_PLUGIN} 个（当前 {len(dock_roots)} 个），'
            '超出的会进入坞栏「更多」浮层',
            line=_locate_line(lines, 'frontend.contributions.menus'),
        )


def _check_version_hints(report, payload, lines):
    """检查项 9：主程序版本门槛与契约版本提示。"""
    min_app = str(payload.get('min_app_version') or '').strip()
    if min_app and parse_semver(min_app) is not None:
        if compare_versions(HOST_APP_VERSION, min_app) < 0:
            report.warning(
                9, 'min_app_version_newer', 'min_app_version',
                f'插件要求主程序 ≥ {min_app}，本校验器对应的主程序版本为 {HOST_APP_VERSION}；'
                '旧版主程序会拒绝加载，请升级主程序或降低 min_app_version',
                line=_locate_line(lines, 'min_app_version'),
            )
    raw_api = payload.get('api_version')
    if (
        isinstance(raw_api, int)
        and not isinstance(raw_api, bool)
        and raw_api not in SUPPORTED_API_VERSIONS
    ):
        report.warning(
            9, 'api_version_unsupported_hint', 'api_version',
            f'插件声明 api_version={raw_api}，当前宿主契约 API 版本为 '
            f'{list(SUPPORTED_API_VERSIONS)}；需要升级主程序或迁移插件（契约破坏性变更）',
            line=_locate_line(lines, 'api_version'),
        )


# ============================================================ 顶层校验流程


def _looks_like_install_root(plugin_dir: str) -> bool:
    """目录是否像宿主的**安装目录**（`.../plugins/<plugin-id>`）。

    宿主安装插件时以 `manifest.id` 作为目录名，因此只有在安装目录里
    「id 与目录名不一致」才是 error；插件仓库的目录名通常是仓库名
    （如 `ST-Manager-AI-Assistant`），不能因此阻断仓库 CI。
    """
    parent = os.path.basename(os.path.dirname(os.path.abspath(plugin_dir)))
    return parent.lower() == 'plugins'


def validate_plugin(plugin_dir):
    """对插件目录做严格校验，返回机器可读结果（`ok` 为 False 表示有 error）。"""
    resolved = os.path.abspath(os.path.expanduser(str(plugin_dir or '.')))
    report = _Report(resolved)
    plugin_id = ''

    if not os.path.isdir(resolved):
        report.error(1, 'plugin_dir_missing', '', f'插件目录不存在: {resolved}')
        return _build_result(report, plugin_id)

    payload, lines = _read_manifest(report)
    if payload is None:
        return _build_result(report, plugin_id)

    normalized, contract_issues = validate_manifest(payload, strict=True)
    _apply_contract_issues(report, contract_issues, lines)

    plugin_id = str(normalized.get('id') or '').strip()
    dir_name = os.path.basename(resolved.rstrip('\\/')) or ''
    if plugin_id and dir_name and dir_name != plugin_id:
        message = (
            f'manifest.id ({plugin_id!r}) 与当前目录名 ({dir_name!r}) 不一致'
        )
        if _looks_like_install_root(resolved):
            report.error(
                1, 'manifest_id_dir_mismatch', 'id',
                message + '；宿主安装目录（.../plugins/<id>）要求两者一致',
                line=_locate_line(lines, 'id'),
                hint='把目录重命名为 manifest.id（或修改 manifest.id）后重新校验',
            )
        else:
            report.warning(
                1, 'manifest_id_dir_mismatch', 'id',
                message + '；当前目录不是宿主安装目录（父目录不是 plugins），'
                '仓库目录名不影响校验',
                line=_locate_line(lines, 'id'),
                hint='宿主安装时会以 manifest.id 为目录名；在插件仓库根目录运行时可忽略本条',
            )

    _check_static_assets(report, resolved, normalized, lines)
    _check_css_scope(report, resolved, normalized, lines)
    _check_icons(report, resolved, payload, normalized, lines)
    _check_dock_capacity(report, normalized, lines)
    _check_version_hints(report, payload, lines)
    return _build_result(report, plugin_id)


# ============================================================ CLI


def _print_issues(issues, severity):
    items = [item for item in issues if item['severity'] == severity]
    if not items:
        return
    label = 'ERROR' if severity == SEVERITY_ERROR else 'WARN '
    print(f'— {label}（{len(items)} 条）—')
    for issue in items:
        location = issue.get('field') or '(manifest)'
        line = issue.get('line')
        if line:
            location = f'{location}:{line}'
        print(f'  {label} [{issue["code"]}] {location}: {issue["message"]}')
        if issue.get('hint'):
            print(f'          ↳ {issue["hint"]}')
    print('')


def print_report(result):
    """人类可读输出：先逐项检查状态，再按 error / warning 列明细。"""
    print(f'stm-plugin-check · 契约 v{result["contract_version"]} · '
          f'宿主 {result["host_app_version"]}')
    plugin_label = result['plugin_id'] or '(未知 id)'
    print(f'插件: {plugin_label}  ({result["plugin_dir"]})')
    print('')
    print('检查项（设计文档 §8.2）：')
    icons = {'pass': '✅', 'warn': '⚠️ ', 'fail': '❌'}
    for check in result['checks']:
        icon = icons.get(check['status'], '•')
        counts = []
        if check['error_count']:
            counts.append(f'{check["error_count"]} error')
        if check['warning_count']:
            counts.append(f'{check["warning_count"]} warning')
        suffix = f'（{"，".join(counts)}）' if counts else ''
        print(f'  {icon} [{check["id"]}/{len(CHECK_DEFINITIONS)}] '
              f'{check["name"]}: {check["title"]}{suffix}')
    print('')
    _print_issues(result['issues'], SEVERITY_ERROR)
    _print_issues(result['issues'], SEVERITY_WARNING)
    if result['ok']:
        print(f'✅ 通过：0 error / {result["warning_count"]} warning')
    else:
        print(f'❌ 失败：{result["error_count"]} error / {result["warning_count"]} warning')


def _configure_stdout():
    """Windows 控制台默认 GBK，直接打印中文会抛 UnicodeEncodeError。"""
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError, ValueError):
        pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog='stm_plugin_check.py',
        description='ST-Manager 插件契约 v3 严格校验器（单文件，可复制到任意插件仓库）',
    )
    parser.add_argument('plugin_dir', help='插件目录（包含 manifest.json）')
    parser.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    return parser


def main(argv=None):
    _configure_stdout()
    args = build_parser().parse_args(argv)
    result = validate_plugin(args.plugin_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
