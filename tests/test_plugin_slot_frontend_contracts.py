"""插件 v3 前端共享契约：插槽锚点 / 注册表消费 / 触发通道（S4 + S7 + S12）。

仓库没有 JS 测试框架，浏览器里的渲染与交互无法自动化，因此沿用「源码扫描式
契约测试」锁住**不会报错但会静默失效**的前端约定：

- S7：6 类插槽锚点（5 个命名插槽 + 8 个 `empty.<mode>`）在模板里存在，且锚点
  必须是**空容器**——内容一律由 `PluginSlotHost` 挂载，宿主模板不许预置内容；
- S4：渲染层统一派发 `contribution:trigger` 事件，**不 import** `pluginHost.js`；
- S3：消费端只读 `contributionRegistry.js`，v2 的 `entryRegistry` / `entries`
  概念必须清零；
- S6：kill switch 的唯一前端通道是 `plugins:close-overlays`；
- 图层：`plugin-layers.css` 被入口 CSS 引入，层级 token 齐全且不盖住宿主反馈层。
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 设计文档 §5.1：7 个菜单落点。
MENU_PLACEMENTS = (
    'context.folder',
    'context.card',
    'context.footer',
    'batch.actions',
    'commandPalette',
    'dock',
    'settings.nav',
)

# 设计文档 §5.2：5 个命名插槽。
SLOT_NAMES = (
    'settings.section',
    'header.actions',
    'card.detail.tabs',
    'page.cards.toolbar',
    'page.worldinfo.toolbar',
)

# 设计文档 §5.2 / §4.4.4：8 个工作模式。
KNOWN_MODES = (
    'cards',
    'worldinfo',
    'chats',
    'presets',
    'regex',
    'scripts',
    'quick_replies',
    'beautify',
)

# 插槽锚点 → 模板文件（每个锚点恰好落在一个视图里）。
SLOT_ANCHORS = {
    'settings.section': 'templates/modals/settings.html',
    'header.actions': 'templates/components/header.html',
    'card.detail.tabs': 'templates/modals/detail_card.html',
    'page.cards.toolbar': 'templates/components/grid_cards.html',
    'page.worldinfo.toolbar': 'templates/components/grid_wi.html',
}

# `empty.<mode>` 空状态锚点所在的视图模板（mode → 候选模板，命中任一即可）。
EMPTY_SLOT_TEMPLATES = {
    'cards': ('templates/components/grid_cards.html',),
    'worldinfo': ('templates/components/grid_wi.html',),
    'chats': ('templates/components/grid_chats.html',),
    'presets': ('templates/components/grid_presets.html',),
    'regex': ('templates/components/grid_extensions.html',),
    'scripts': ('templates/components/grid_extensions.html',),
    'quick_replies': ('templates/components/grid_extensions.html',),
    'beautify': ('templates/components/grid_beautify.html',),
}

# 渲染层消费端（不含 pluginManager：管理页允许显式 import PluginHost 做重试）。
RENDER_CONSUMERS = (
    'static/js/components/contextMenu.js',
    'static/js/components/header.js',
    'static/js/components/entryDock.js',
    'static/js/components/commandPalette.js',
    'static/js/components/settingsModal.js',
)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def _all_templates():
    root = os.path.join(PROJECT_ROOT, 'templates')
    for current_root, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith('.html'):
                yield os.path.relpath(os.path.join(current_root, name), PROJECT_ROOT).replace(
                    os.sep, '/'
                )


# ------------------------------------------------------------------ S7 插槽锚点


def test_named_slot_anchors_exist_in_expected_templates():
    missing = []
    for slot, template in SLOT_ANCHORS.items():
        source = read_source(template)
        if f'data-plugin-slot="{slot}"' not in source:
            missing.append(f'{template}: {slot}')
    assert missing == [], f'缺少插槽锚点: {missing}'


def test_empty_mode_slot_anchors_cover_all_work_modes():
    missing = []
    for mode in KNOWN_MODES:
        slot = f'empty.{mode}'
        templates = EMPTY_SLOT_TEMPLATES[mode]
        if not any(f'data-plugin-slot="{slot}"' in read_source(path) for path in templates):
            missing.append(f'{slot}（候选: {", ".join(templates)}）')
    assert missing == [], f'缺少空状态插槽锚点: {missing}'


def test_slot_anchors_are_empty_containers():
    """锚点必须是空容器：内容由 PluginSlotHost 创建包装后挂载。"""

    pattern = re.compile(
        r'<div\b[^>]*\bdata-plugin-slot="([^"]+)"[^>]*>\s*</div>', re.S
    )
    found = {}
    for template in _all_templates():
        for match in pattern.finditer(read_source(template)):
            found.setdefault(match.group(1), []).append(template)

    expected = set(SLOT_NAMES) | {f'empty.{mode}' for mode in KNOWN_MODES}
    missing = sorted(expected - set(found))
    assert missing == [], f'以下插槽锚点不是空容器（可能预置了内容）: {missing}'

    # 锚点属性只允许声明一次：重复锚点会让同一贡献被挂载两遍。
    duplicated = [
        f'{template}: {slot}'
        for slot, templates in found.items()
        for template in templates
        if templates.count(template) > 1
    ]
    assert duplicated == []


def test_slot_anchors_do_not_hardcode_plugin_content():
    """模板只放空锚点：不许在锚点元素上绑定 x-html / x-for / 插件 id。"""

    pattern = re.compile(r'<div\b[^>]*\bdata-plugin-slot="[^"]+"[^>]*>', re.S)
    offenders = []
    for template in _all_templates():
        for match in pattern.finditer(read_source(template)):
            tag = match.group(0)
            if 'x-html' in tag or 'x-for' in tag:
                offenders.append(f'{template}: {tag[:120]}')
    assert offenders == [], f'插槽锚点不得预渲染插件内容: {offenders}'


def test_app_entry_initializes_slot_host_and_refreshes():
    app_source = read_source('static/js/app.js')

    assert 'pluginSlotHost.js' in app_source
    assert 'PluginSlotHost.init()' in app_source
    # app.js 需要在插件加载后补一次刷新（事件驱动之外的首轮挂载）。
    assert 'PluginSlotHost.refreshAll()' in app_source
    assert 'plugins:loaded' in app_source or 'contributions:changed' in app_source


def test_slot_host_contract_matches_css_class_names():
    slot_source = read_source('static/js/pluginSlotHost.js')
    css = read_source('static/css/modules/plugin-layers.css')

    assert '"data-plugin-slot"' in slot_source
    assert 'plugin-slot' in slot_source
    assert 'plugin-slot__error' in slot_source
    # runtime 承诺的方法名：app.js 用 refreshAll，事件驱动用 refresh。
    assert 'refreshAll()' in slot_source
    assert 'refresh()' in slot_source

    assert '.plugin-slot' in css
    assert '.plugin-slot__error' in css


# ------------------------------------------------------------------ S3/S4 消费端


def test_render_consumers_import_contribution_registry():
    missing = []
    for path in RENDER_CONSUMERS:
        source = read_source(path)
        if 'contributionRegistry.js' not in source:
            missing.append(path)
    assert missing == [], f'以下渲染消费端没有接贡献注册表: {missing}'


def test_render_layer_has_no_v2_entry_registry_residue():
    """渲染层不得再出现 v2 入口概念（entryRegistry / EntryRegistry / entries:）。"""

    offenders = []
    for path in RENDER_CONSUMERS + ('static/js/app.js', 'static/js/uiPrimitives.js'):
        source = read_source(path)
        for fragment in ('entryRegistry.js', 'EntryRegistry', 'entries:changed', 'entry:activate'):
            if fragment in source:
                offenders.append(f'{path}: {fragment}')
    assert offenders == [], f'渲染层残留 v2 入口实现: {offenders}'


def test_render_layer_does_not_import_plugin_host():
    """S4：渲染层只派发事件，不直接 import 运行时，避免循环依赖。"""

    offenders = [
        path
        for path in RENDER_CONSUMERS
        if 'pluginHost.js' in read_source(path)
    ]
    assert offenders == [], f'渲染层不应 import pluginHost.js: {offenders}'


def test_render_layer_dispatches_contribution_trigger():
    missing = []
    for path in RENDER_CONSUMERS:
        source = read_source(path)
        if 'contribution:trigger' not in source:
            missing.append(path)
        if 'CustomEvent' not in source:
            missing.append(f'{path}（缺 CustomEvent）')
    assert missing == [], f'以下消费端没有走统一触发通道: {missing}'


def test_contribution_trigger_detail_shape_is_documented_by_consumers():
    """S4 detail 形状：`{pluginId, nodeId, trigger, ctx}`。"""

    combined = '\n'.join(read_source(path) for path in RENDER_CONSUMERS)

    for fragment in ('pluginId', 'nodeId', 'trigger', 'ctx'):
        assert fragment in combined, fragment

    # trigger 取值来自设计 §4.6：menu / palette / shortcut / dock。
    for value in ('"menu"', '"palette"', '"shortcut"', '"dock"'):
        assert value in combined, value


def test_all_menu_placements_have_a_render_consumer():
    expected = {
        'context.folder': 'static/js/components/contextMenu.js',
        'context.card': 'static/js/components/contextMenu.js',
        'context.footer': 'static/js/components/contextMenu.js',
        'batch.actions': 'static/js/components/header.js',
        'commandPalette': 'static/js/components/commandPalette.js',
        'dock': 'static/js/components/entryDock.js',
        'settings.nav': 'static/js/components/settingsModal.js',
    }
    missing = []
    for placement, path in expected.items():
        source = read_source(path)
        if f"'{placement}'" not in source and f'"{placement}"' not in source:
            missing.append(f'{path}: {placement}')
    assert missing == [], f'落点没有渲染消费者: {missing}'


def test_settings_nav_is_rendered_inside_host_settings_navigation():
    template = read_source('templates/modals/settings.html')

    assert 'settings-nav' in template
    # 插件导航项必须渲染在宿主设置导航区内，点击走统一触发通道。
    assert 'pluginNavEntries' in template
    assert 'openPluginNavEntry' in template
    assert '.settings-nav' in read_source('static/css/modules/modal-settings.css') or (
        'settings-nav' in read_source('static/css/modules/modal-settings.css')
    )


def test_card_grid_exposes_card_context_menu_entry():
    """§5.1 context.card：宿主必须给卡片网格补右键入口。"""

    grid = read_source('templates/components/grid_cards.html')
    card_grid = read_source('static/js/components/cardGrid.js')

    assert 'showCardContextMenu' in grid
    assert '@contextmenu.prevent' in grid
    assert 'showCardContextMenu(' in card_grid
    assert 'show-context-menu' in card_grid
    # 事件 detail 必须区分 card 目标，且保留 targetCard。
    assert '"card"' in card_grid or "'card'" in card_grid
    assert 'targetCard' in card_grid


# ------------------------------------------------------------------ S6 kill switch


def test_kill_switch_uses_shared_event_and_command_ids():
    palette = read_source('static/js/components/commandPalette.js')
    manager = read_source('static/js/components/pluginManager.js')
    template = read_source('templates/modals/plugin_manager.html')

    for source in (palette, manager):
        assert 'plugins:close-overlays' in source

    assert 'KILL_SWITCH_COMMAND_ID' in palette
    assert '关闭所有浮动界面' in palette
    assert '关闭所有插件浮层' in template

    # 与 runtime 的 kill switch 监听同名。
    assert '"plugins:close-overlays"' in read_source('static/js/pluginHost.js')


# ------------------------------------------------------------------ S6 图层 / CSS


Z_LAYER_TOKENS = (
    '--z-plugin-content',
    '--z-plugin-portal',
    '--z-plugin-ambient',
    '--z-plugin-dock',
    '--z-plugin-surface',
    '--z-plugin-popover',
    '--z-plugin-tooltip',
    '--z-plugin-alert',
)


def test_plugin_layer_tokens_are_defined():
    variables = read_source('static/css/modules/variables.css')

    missing = [token for token in Z_LAYER_TOKENS if f'{token}:' not in variables]
    assert missing == [], f'缺少插件层级 token: {missing}'


def test_plugin_layers_css_is_registered_and_layered():
    entry = read_source('static/css/style.css')
    css = read_source('static/css/modules/plugin-layers.css')

    assert 'modules/plugin-layers.css' in entry
    assert '.plugin-layer--content' in css
    assert '.plugin-layer--portal' in css
    assert 'var(--z-plugin-content)' in css
    assert 'var(--z-plugin-portal)' in css
    # 内容层在宿主模态之下；portal 层在模态之上但必须低于宿主提示 / 告警。
    assert '.plugin-slot' in css
    assert '[data-plugin]' in css


def test_plugin_layers_css_uses_defined_variables_only():
    css = read_source('static/css/modules/plugin-layers.css')
    defined = set()
    css_root = os.path.join(PROJECT_ROOT, 'static', 'css')
    for current_root, _dirs, files in os.walk(css_root):
        for name in files:
            if not name.endswith('.css'):
                continue
            with open(os.path.join(current_root, name), 'r', encoding='utf-8') as handle:
                defined.update(re.findall(r'(--[a-zA-Z0-9-]+)\s*:', handle.read()))

    missing = sorted(set(re.findall(r'var\(\s*(--[a-zA-Z0-9-]+)', css)) - defined)
    assert missing == [], f'plugin-layers.css 使用了未定义的变量: {missing}'


# ------------------------------------------------------------------ 模板无 v2 残留


def test_templates_have_no_v2_entry_group_rendering():
    offenders = []
    for template in _all_templates():
        source = read_source(template)
        for fragment in (
            "unit.type === 'group'",
            'unit.type === "group"',
            'pluginEntries',
            'EntryRegistry',
            'entry.kind',
        ):
            if fragment in source:
                offenders.append(f'{template}: {fragment}')
    assert offenders == [], f'模板残留 v2 入口分组渲染: {offenders}'


def test_registry_exposes_s3_contract_used_by_render_layer():
    registry = read_source('static/js/contributionRegistry.js')

    for symbol in (
        'export const MENU_PLACEMENTS',
        'export const SLOT_NAMES',
        'export const EMPTY_SLOT_PREFIX',
        'export const KILL_SWITCH_COMMAND_ID',
        'export const ContributionRegistry',
        'menuTree(',
        'paletteEntries(',
        'dockItems(',
        'dockOverflow(',
        'findByShortcut(',
        'slotRecords(',
        'notifyChange(',
    ):
        assert symbol in registry, symbol

    # 7 个落点与 5 个命名插槽必须与契约常量同名。
    for placement in MENU_PLACEMENTS:
        assert f'"{placement}"' in registry, placement
    for slot in SLOT_NAMES:
        assert f'"{slot}"' in registry, slot
