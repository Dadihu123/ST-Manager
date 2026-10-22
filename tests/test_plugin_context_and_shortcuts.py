"""右键菜单 / 批量菜单 / 快捷键的 v3 前端消费者契约（S12）。

覆盖：
- `contextMenu.js` 按 `context.folder` / `context.card` / `context.footer`
  三个落点求值，构造 `{mode, target, selection}` 上下文；
- 角色卡右键入口由宿主卡片网格提供（`showCardContextMenu` → `show-context-menu`）；
- 所有可执行节点统一派发 `contribution:trigger`（trigger = ``menu``），
  不 import 运行时；置灰节点仍渲染（D7）；
- 批量菜单消费 `batch.actions`，selection 上下文取当前选中集；
- 二级菜单是独立 fixed 浮层，点击父项两次会收起；
- 快捷键由命令面板的 keydown 监听在按下时通过 `findByShortcut()` 求值，
  不写 `layout.shortcuts` 持久化。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTEXT_JS = "static/js/components/contextMenu.js"
CONTEXT_TMPL = "templates/components/context_menu.html"
HEADER_JS = "static/js/components/header.js"
HEADER_TMPL = "templates/components/header.html"
PALETTE_JS = "static/js/components/commandPalette.js"
CARD_GRID_JS = "static/js/components/cardGrid.js"
CARD_GRID_TMPL = "templates/components/grid_cards.html"
REGISTRY_JS = "static/js/contributionRegistry.js"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------- 右键菜单：落点


def test_context_menu_consumes_three_context_placements():
    source = read(CONTEXT_JS)
    for placement in ("context.folder", "context.card", "context.footer"):
        assert placement in source, f"右键菜单缺少落点消费: {placement}"
    assert "ContributionRegistry.menuTree(" in source
    assert "contextOverride" in source and "context: ctx" in source
    assert "pluginMenuNodes" in source and "pluginCardNodes" in source
    assert "pluginFooterNodes" in source
    assert "pluginContextPlacement" in source


def test_context_menu_builds_semantic_target_context():
    source = read(CONTEXT_JS)
    assert "contributionContext()" in source
    for field in ("mode", "target", "selection"):
        assert field in source
    assert "target: {" in source
    assert "type: kind" in source and "kind," in source and "id:" in source
    assert "path:" in source
    # 右键语义是对目标操作，与全局选中集无关。
    assert "selection: { mode: 'none', ids: [] }" in source


def test_context_menu_distinguishes_folder_and_card_targets():
    source = read(CONTEXT_JS)
    assert "this.type === 'card'" in source
    assert "targetCard" in source
    assert "targetFolder" in source
    assert "'context.card'" in source and "'context.folder'" in source
    template = read(CONTEXT_TMPL)
    assert "pluginContextNodes" in template
    assert "pluginFooterNodes" in template


def test_card_grid_offers_card_context_entry():
    grid = read(CARD_GRID_JS)
    assert "showCardContextMenu" in grid
    assert '"show-context-menu"' in grid
    assert 'type: "card"' in grid
    assert "targetCard: card" in grid
    template = read(CARD_GRID_TMPL)
    assert "@contextmenu.prevent.stop=\"showCardContextMenu($event, card)\"" in template


# --------------------------------------------------------------------- 右键菜单：触发


def test_context_menu_triggers_contribution_and_never_imports_runtime():
    source = read(CONTEXT_JS)
    assert "contribution:trigger" in source
    assert "new CustomEvent" in source
    assert 'trigger: "menu"' in source or "trigger: 'menu'" in source
    for field in ("pluginId:", "nodeId:", "ctx:"):
        assert field in source
    assert "pluginHost.js" not in source
    assert "pluginSurfaceHost.js" not in source
    assert "entry:activate" not in source
    assert "EntryRegistry" not in source


def test_context_menu_disabled_nodes_are_rendered_but_not_executed():
    source = read(CONTEXT_JS)
    assert "isMenuNodeDisabled" in source
    assert "node.enabled === false || node.ok === false" in source
    assert "disabledHint" in source
    assert "menuNodeHint" in source
    template = read(CONTEXT_TMPL)
    assert ":disabled=\"isMenuNodeDisabled" in template or ":disabled=" in template


def test_context_menu_renders_badge_and_progress():
    source = read(CONTEXT_JS)
    assert "menuNodeBadge" in source
    assert "99+" in source
    template = read(CONTEXT_TMPL)
    assert "menuNodeBadge" in template


def test_context_menu_submenu_is_a_fixed_flyout_toggled_twice():
    source = read(CONTEXT_JS)
    assert "positionFlyoutElement" in source
    assert "data-plugin-contribution-flyout" in source
    assert "toggleContributionSubmenu" in source
    assert "isContributionsubmenuOpen" in source
    assert "backFromContributionSubmenu" in source
    # 二级浮层固定向右展开：flyout 工具负责测量与翻转。
    assert "resolveAnchorElement" in source


def test_context_menu_keeps_host_folder_actions_and_hover_contract():
    template = read(CONTEXT_TMPL)
    # 宿主文件夹动作仍在（foreign test 也依赖这些字符串）。
    assert "handleToggleIsolation()" in template
    assert "deleteFolderItemLabel" in template
    assert template.count("hover:bg-[var(--state-hover-surface)]") >= 8


# --------------------------------------------------------------------- 批量菜单


def test_batch_menu_consumes_batch_actions_placement():
    source = read(HEADER_JS)
    assert 'ContributionRegistry.menuTree("batch.actions"' in source
    assert "pluginBatchNodes" in source
    assert "refreshPluginBatchEntries" in source
    assert "EntryRegistry" not in source
    assert "pluginHost.js" not in source


def test_batch_menu_passes_selection_target():
    source = read(HEADER_JS)
    assert "contributionContext()" in source
    assert "target: {" in source
    assert "type: \"selection\"" in source
    assert "selection: {" in source
    assert 'mode: ids.length === 0 ? "none"' in source
    assert "multi" in source and "single" in source


def test_batch_menu_nodes_support_submenu_disabled_and_badges():
    source = read(HEADER_JS)
    assert "hasMenuChildren" in source
    assert "isMenuNodeDisabled" in source
    assert "menuNodeBadge" in source
    assert "pluginBatchEntryProgressPercent" in source
    assert "activePluginBatchGroupUnit" in source
    assert "pluginBatchFlatEntries" in source
    template = read(HEADER_TMPL)
    assert "pluginBatchNodes" in template
    assert "runPluginBatchEntry(node)" in template
    assert "togglePluginBatchGroup(node" in template
    assert "activePluginBatchGroupUnit()" in template
    assert "data-plugin-batch-flyout" in template


def test_batch_menu_triggers_contribution():
    source = read(HEADER_JS)
    assert "contribution:trigger" in source
    assert "new CustomEvent" in source
    assert 'trigger: "menu"' in source or "trigger: 'menu'" in source
    assert "pluginId:" in source and "nodeId:" in source and "ctx:" in source


def test_batch_menu_mobile_bar_only_lists_executable_leaf_nodes():
    source = read(HEADER_JS)
    assert "get pluginBatchFlatEntries()" in source
    assert "hasMenuChildren" in source
    template = read(HEADER_TMPL)
    assert "x-for=\"node in pluginBatchFlatEntries\"" in template


# --------------------------------------------------------------------- 快捷键


def test_shortcut_lookup_happens_at_keydown_time():
    palette = read(PALETTE_JS)
    assert "keydown" in palette
    assert "findByShortcut(combo)" in palette
    assert "shortcutCombo(event)" in palette
    assert "isTypingTarget(event.target)" in palette
    # 快捷键不再持久化到 layout（v3 无 layout）。
    assert "layout.shortcuts" not in palette
    assert "updateLayout" not in palette


def test_shortcut_dispatch_ignores_declaration_time_when():
    palette = read(PALETTE_JS)
    # findByShortcut 只返回 ok:true，按下时求值；面板本身不缓存 when 结果。
    assert "node.enabled === false || node.ok === false" in palette
    assert "disabledHint" in palette
    assert "triggerNode(node, \"shortcut\")" in palette or "triggerNode(node, 'shortcut')" in palette


def test_shortcut_ui_is_read_only_in_contribution_overview():
    manager_js = read("static/js/components/pluginManager.js")
    manager_tmpl = read("templates/modals/plugin_manager.html")
    # v3：命令声明 shortcut 只展示，宿主不再提供录制/改绑。
    assert "row.shortcut" in manager_tmpl
    for forbidden in ("captureEntryShortcut", "onShortcutKeydown", "assignEntryShortcut", "clearEntryShortcut"):
        assert forbidden not in manager_js
        assert forbidden not in manager_tmpl


# --------------------------------------------------------------------- 注册表契约


def test_registry_exports_the_placements_consumed_by_these_consumers():
    registry = read(REGISTRY_JS)
    assert "MENU_PLACEMENTS" in registry
    for placement in ("context.folder", "context.card", "context.footer", "batch.actions"):
        assert placement in registry
    assert "contribution:trigger" in registry or "ContributionRegistry" in registry
