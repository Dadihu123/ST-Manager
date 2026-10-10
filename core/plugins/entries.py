"""入口（entries）契约：全局键、字段规范化与准入分级。

设计文档 2.2 的「入口（entries）规范（D1）」「入口 kind 准入分级（D5）」「坞槽位（D6）」
在代码里的落点。本模块只做声明层的纯函数处理，不接触注册表、数据库与 DOM：

- `build_entry_key()` 生成跨插件唯一的全局键（`<plugin_id>:<entry_id>`）；
- `normalize_entries()` 把 manifest 的 `frontend.entries` 规范化为宿主内部结构，
  非法项**丢弃 + 警告**，不拒绝加载整个插件（D1）；
- `entry_kind_allowed()` 实现 tier 准入分级（D5）。

结构键的严格校验（未知子键 → 拒绝加载）由 `core.plugins.manifest` 负责。
"""

import logging
import re

logger = logging.getLogger(__name__)

# 宿主内建入口使用的前缀（与插件 id 正则互斥：插件 id 不含 `:`）
CORE_ENTRY_PREFIX = 'core:'

# 单插件入口上限（设计文档 D1）
MAX_ENTRIES_PER_PLUGIN = 16

# 入口 id：比插件 id 宽松一位，允许单字符
ENTRY_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{0,63}$')

ENTRY_KINDS = frozenset({'dock', 'nav', 'settings', 'context', 'command', 'status'})
SURFACE_TYPES = frozenset({'panel', 'modal', 'page', 'sheet'})

# 入口允许声明的子键（严格校验白名单）
KNOWN_ENTRY_KEYS = frozenset({
    'id', 'kind', 'label', 'description', 'icon', 'contexts',
    'requires_selection', 'surface', 'priority', 'badge', 'shortcut',
    'when', 'disabledHint',
})

# `when` 条件表达式的允许子键（D7）
KNOWN_WHEN_KEYS = frozenset({
    'mode', 'selection', 'indexState', 'config', 'hostVersion', 'feature',
})
SELECTION_MODES = frozenset({'none', 'any', 'single', 'multi'})

# 宿主工作模式集合（`contexts` 与 `when.mode` 的合法值）
KNOWN_MODES = frozenset({
    'cards', 'worldinfo', 'chats', 'presets',
    'regex', 'scripts', 'quick_replies', 'beautify',
})

# 归属分级：由宿主仓库的 catalog 决定，插件 manifest 不能声明（D5）
ENTRY_TIERS = ('official', 'verified', 'community')
DEFAULT_ENTRY_TIER = 'community'

# kind → 允许的 tier 集合（D5 准入表）
_KIND_TIER_ALLOWLIST = {
    'command': frozenset({'official', 'verified', 'community'}),
    'context': frozenset({'official', 'verified', 'community'}),
    'settings': frozenset({'official', 'verified', 'community'}),
    'dock': frozenset({'official', 'verified', 'community'}),
    'status': frozenset({'official', 'verified'}),
    'nav': frozenset({'official', 'verified'}),
}

# 坞槽位（D6）：宿主分配的资源，插件 priority 仅建议值
MAX_DOCK_SLOTS = 8
MAX_DOCK_ENTRIES_PER_PLUGIN = 2
DEFAULT_ENTRY_PRIORITY = 100
DEFAULT_SURFACE_TYPE = 'panel'


def build_entry_key(plugin_id: str, entry_id: str) -> str:
    """生成跨插件唯一的全局入口键：`<plugin_id>:<entry_id>`。"""
    return f'{str(plugin_id or "").strip()}:{str(entry_id or "").strip()}'


def is_host_entry_key(key) -> bool:
    """判断是否宿主内建入口键（`core:` 前缀，与插件键互不冲突）。"""
    return isinstance(key, str) and key.startswith(CORE_ENTRY_PREFIX)


def split_entry_key(key) -> tuple[str, str] | None:
    """拆解全局入口键；非法返回 None。"""
    if not isinstance(key, str) or is_host_entry_key(key):
        return None
    plugin_id, _, entry_id = key.partition(':')
    if not plugin_id or not entry_id:
        return None
    return plugin_id, entry_id


def normalize_tier(raw_tier) -> str:
    """归一归属分级；未知值回退 `community`。"""
    value = str(raw_tier or '').strip().lower()
    return value if value in ENTRY_TIERS else DEFAULT_ENTRY_TIER


def entry_kind_allowed(kind: str, tier: str) -> bool:
    """按 tier 判断该 kind 是否准入（D5）。"""
    allowed = _KIND_TIER_ALLOWLIST.get(str(kind or '').strip())
    if not allowed:
        return False
    return normalize_tier(tier) in allowed


def _normalize_when(plugin_id: str, raw_when, warnings: list) -> dict:
    """规范化 `when` 条件表达式；未知子键忽略 + 警告。"""
    if raw_when is None:
        return {}
    if not isinstance(raw_when, dict):
        warnings.append(f'插件 {plugin_id} 的 entries[].when 必须是对象，已忽略')
        return {}

    when = {}
    for raw_key, raw_value in raw_when.items():
        key = str(raw_key or '').strip()
        if key not in KNOWN_WHEN_KEYS:
            warnings.append(f'忽略未知的 when 子键: {key}')
            continue

        if key in ('mode', 'feature'):
            values = raw_value if isinstance(raw_value, list) else []
            cleaned = [str(item).strip() for item in values if isinstance(item, str) and str(item).strip()]
            if key == 'mode':
                kept = []
                for mode in cleaned:
                    if mode in KNOWN_MODES:
                        kept.append(mode)
                    else:
                        warnings.append(f'忽略未知的工作模式: {mode}')
                when['mode'] = kept
            else:
                when['feature'] = cleaned
            continue

        if key == 'selection':
            value = str(raw_value or '').strip()
            if value not in SELECTION_MODES:
                warnings.append(f'忽略非法的 when.selection: {raw_value!r}')
                continue
            when['selection'] = value
            continue

        if key == 'config':
            if not isinstance(raw_value, dict):
                warnings.append('忽略非法的 when.config（应为对象）')
                continue
            raw_keys = raw_value.get('requireKeys')
            require_keys = []
            if isinstance(raw_keys, list):
                require_keys = [
                    str(item).strip() for item in raw_keys
                    if isinstance(item, str) and str(item).strip()
                ]
            when['config'] = {'requireKeys': require_keys}
            continue

        when[key] = str(raw_value or '').strip()

    return when


def _normalize_surface(plugin_id: str, raw_surface, warnings: list) -> dict | None:
    """规范化 `surface`；非法返回 None（调用方据此丢弃该项）。"""
    if raw_surface is None:
        return {'type': DEFAULT_SURFACE_TYPE}
    if not isinstance(raw_surface, dict):
        warnings.append(f'插件 {plugin_id} 的 entries[].surface 必须是对象，已丢弃该项')
        return None

    surface = {str(k): v for k, v in raw_surface.items()}
    surface_type = str(surface.get('type') or '').strip()
    if not surface_type:
        surface['type'] = DEFAULT_SURFACE_TYPE
        return surface
    if surface_type not in SURFACE_TYPES:
        warnings.append(
            f'插件 {plugin_id} 的 entries[].surface.type 非法: {surface_type!r}，已丢弃该项'
        )
        return None
    surface['type'] = surface_type
    return surface


def _normalize_priority(raw_priority) -> int:
    if isinstance(raw_priority, bool) or not isinstance(raw_priority, int):
        return DEFAULT_ENTRY_PRIORITY
    return raw_priority


def _normalize_badge(raw_badge):
    if isinstance(raw_badge, bool):
        return None
    if isinstance(raw_badge, (str, int, float)):
        return raw_badge
    return None


def normalize_entries(plugin_id: str, raw_entries) -> tuple[list, list]:
    """把 `frontend.entries` 规范化为宿主内部结构。

    非法项一律**丢弃 + 警告**，不抛出异常（D1）。返回 `(entries, warnings)`。
    每一项都会带上宿主生成的全局键 `key` 与归属 `plugin_id`。

    注意：这里**不做 tier 准入过滤**（D5）——tier 由宿主仓库的 catalog 决定，
    而 manifest 解析阶段还不知道 tier。准入过滤由 `apply_tier()` 在注册表侧完成。
    """
    warnings = []
    if raw_entries is None:
        return [], warnings
    if not isinstance(raw_entries, list):
        warnings.append(f'插件 {plugin_id} 的 frontend.entries 必须是数组，已忽略')
        return [], warnings

    if len(raw_entries) > MAX_ENTRIES_PER_PLUGIN:
        warnings.append(
            f'插件 {plugin_id} 声明了 {len(raw_entries)} 个入口，'
            f'超过上限 {MAX_ENTRIES_PER_PLUGIN}，超出部分已忽略'
        )
        raw_entries = raw_entries[:MAX_ENTRIES_PER_PLUGIN]

    entries = []
    seen_ids = set()
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            warnings.append(f'插件 {plugin_id} 的 entries[{index}] 必须是对象，已丢弃')
            continue

        entry_id = str(raw_entry.get('id') or '').strip()
        if not ENTRY_ID_PATTERN.match(entry_id):
            warnings.append(
                f'插件 {plugin_id} 的 entries[{index}] id 不符合 ^[a-z][a-z0-9-]{{0,63}}$: '
                f'{raw_entry.get("id")!r}，已丢弃该项'
            )
            continue
        if entry_id in seen_ids:
            warnings.append(f'插件 {plugin_id} 的入口 id 重复: {entry_id}，已丢弃重复项')
            continue

        kind = str(raw_entry.get('kind') or '').strip()
        if kind not in ENTRY_KINDS:
            warnings.append(
                f'插件 {plugin_id} 的入口 {entry_id} kind 非法: {raw_entry.get("kind")!r}，已丢弃该项'
            )
            continue

        label = str(raw_entry.get('label') or '').strip()
        if not label:
            warnings.append(f'插件 {plugin_id} 的入口 {entry_id} 缺少 label，已丢弃该项')
            continue

        surface = _normalize_surface(plugin_id, raw_entry.get('surface'), warnings)
        if surface is None:
            continue

        raw_contexts = raw_entry.get('contexts')
        contexts = []
        if isinstance(raw_contexts, list):
            for item in raw_contexts:
                mode = str(item or '').strip()
                if mode in KNOWN_MODES:
                    contexts.append(mode)
                elif mode:
                    warnings.append(f'插件 {plugin_id} 的入口 {entry_id} 含未知工作模式: {mode}')
        elif raw_contexts is not None:
            warnings.append(f'插件 {plugin_id} 的入口 {entry_id} 的 contexts 必须是数组，已忽略')

        seen_ids.add(entry_id)
        entries.append({
            'id': entry_id,
            'key': build_entry_key(plugin_id, entry_id),
            'plugin_id': plugin_id,
            'kind': kind,
            'label': label,
            'description': str(raw_entry.get('description') or '').strip(),
            'icon': str(raw_entry.get('icon') or '').strip(),
            'contexts': contexts,
            'requires_selection': bool(raw_entry.get('requires_selection')),
            'surface': surface,
            'priority': _normalize_priority(raw_entry.get('priority')),
            'badge': _normalize_badge(raw_entry.get('badge')),
            'shortcut': str(raw_entry.get('shortcut') or '').strip(),
            'when': _normalize_when(plugin_id, raw_entry.get('when'), warnings),
            'disabledHint': str(raw_entry.get('disabledHint') or '').strip(),
        })

    return entries, warnings


def apply_tier(plugin_id: str, entries, *, tier: str = DEFAULT_ENTRY_TIER) -> tuple[list, list]:
    """按归属分级过滤入口并写入 `tier` 字段（D5）。

    `status` / `nav` 仅 official 与 verified 可用；不允许的 kind 被**忽略 + 警告**，
    不影响该插件其余入口，也不拒绝加载整个插件。
    """
    warnings = []
    resolved = normalize_tier(tier)
    kept = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get('kind') or '').strip()
        if not entry_kind_allowed(kind, resolved):
            warnings.append(
                f'插件 {plugin_id} 的入口 {entry.get("id")} 使用了 {resolved} 不可用的 '
                f'kind: {kind}，已忽略'
            )
            continue
        item = dict(entry)
        item['tier'] = resolved
        kept.append(item)
    return kept, warnings


def unknown_entry_keys(raw_entry) -> list:
    """返回该项里不在白名单中的子键（供 manifest 严格校验使用）。"""
    if not isinstance(raw_entry, dict):
        return []
    return sorted(str(key) for key in raw_entry.keys() if str(key) not in KNOWN_ENTRY_KEYS)
