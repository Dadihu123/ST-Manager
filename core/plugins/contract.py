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
