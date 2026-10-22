"""入口坞 + 命令面板的 v3 前端消费者契约（S12）。

覆盖：
- 坞只消费 ``ContributionRegistry.dockItems()`` / ``dockOverflow()``（v2 的
  ``EntryRegistry`` / ``layout.pinned|hidden|order`` / 拖拽重排全部删除）；
- 全局 8 / 每插件 2 的容量裁剪由注册表负责，坞只渲染「槽位 + 更多溢出」；
- 节点置灰仍可见并带 ``disabledHint``（D7），进度按 0–1 比例兼容 ``{done,total}``；
- 打开统一派发 ``contribution:trigger``（trigger = ``dock``），不 import 运行时；
- 命令面板合并 ``paletteEntries()`` + ``coreCommands``，kill switch 走
  ``plugins:close-overlays``；快捷键经 ``findByShortcut()`` 在按下时求值。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCK_JS = "static/js/components/entryDock.js"
DOCK_TMPL = "templates/components/entry_dock.html"
PALETTE_JS = "static/js/components/commandPalette.js"
PALETTE_TMPL = "templates/components/command_palette.html"
REGISTRY_JS = "static/js/contributionRegistry.js"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------- 坞：数据源


def test_dock_reads_contribution_registry_items_and_overflow():
    source = read(DOCK_JS)
    assert "from \"../contributionRegistry.js\"" in source
    assert "ContributionRegistry.dockItems()" in source
    assert "ContributionRegistry.dockOverflow()" in source
    assert "normalizeNode" in source
    assert "hasEntries" in source
    assert "entryCount" in source


def test_dock_removes_v2_layout_pin_hide_and_drag():
    source = read(DOCK_JS)
    for forbidden in (
        "entryRegistry.js",
        "EntryRegistry.",
        "PluginSurfaceHost",
        "entries:changed",
        "entry:activate",
        "entry:open",
        "togglePin",
        "updateLayout",
        "layout.pinned",
        "layout.hidden",
        "layout.order",
        "draggingKey",
        "dragOverKey",
        "onSlotDrop",
        "onSlotDragStart",
    ):
        assert forbidden not in source, f"坞仍有 v2 残留: {forbidden}"
    template = read(DOCK_TMPL)
    for forbidden in ("draggable=", "@contextmenu", "togglePin"):
        assert forbidden not in template, f"坞模板仍有 v2 残留: {forbidden}"


def test_dock_capacity_is_owned_by_registry_not_the_dock():
    registry = read(REGISTRY_JS)
    assert "MAX_DOCK_SLOTS" in registry
    assert "MAX_DOCK_PER_PLUGIN" in registry
    source = read(DOCK_JS)
    # 坞自己不再做容量裁剪或布局持久化，只渲染注册表给出的两份列表。
    assert "MAX_DOCK" not in source
    assert "updateLayout" not in source
    assert "dockItems" in source and "dockOverflow" in source


def test_dock_template_renders_icons_titles_and_more_overflow():
    template = read(DOCK_TMPL)
    assert "x-for=\"entry in slots\"" in template
    assert "entry-rail__slot--more" in template
    assert "更多入口" in template
    assert "overflowGroups" in template
    assert "filteredOverflow" in template
    assert "@click=\"entry.enabled ? open(entry) : onDisabledClick(entry)\"" in template
    # 槽位只显示图标：label 只走 title / aria-label。
    assert "entry.label" in template
    assert "aria-label" in template


def test_dock_slot_buttons_carry_badge_progress_status_and_busy():
    template = read(DOCK_TMPL)
    for hook in ("badgeText(entry)", "progressText(entry)", "statusClass(entry)", "entry.busy"):
        assert hook in template, f"坞槽位缺少状态钩子: {hook}"


def test_dock_progress_accepts_ratio_and_legacy_done_total():
    source = read(DOCK_JS)
    assert "progressText(entry)" in source
    assert "typeof progress === \"number\"" in source
    assert "Math.round(progress * 100)" in source
    assert "progress.done" in source and "progress.total" in source


def test_dock_disabled_nodes_stay_visible_with_hint():
    source = read(DOCK_JS)
    assert "node.enabled !== false && node.ok !== false" in source
    assert "disabledHint" in source
    assert "menuNodeHint(entry)" in source
    template = read(DOCK_TMPL)
    assert ":aria-disabled" in template
    assert "onDisabledClick" in template


# --------------------------------------------------------------------- 坞：打开链路


def test_dock_open_dispatches_contribution_trigger_with_semantic_context():
    source = read(DOCK_JS)
    assert '"contribution:trigger"' in source
    assert 'trigger: "dock"' in source
    for field in ("pluginId:", "nodeId:", "ctx:"):
        assert field in source
    assert "contributionContext()" in source
    assert "mode" in source and "selection" in source
    assert "pluginHost.js" not in source


def test_dock_mobile_sheet_uses_the_same_open_path():
    template = read(DOCK_TMPL)
    assert "entry-sheet" in template
    assert "x-for=\"entry in entries\"" in template
    assert "open(entry)" in template
    assert "hasEntries" in template


def test_dock_keyboard_supports_arrows_enter_home_end_without_delete_pin():
    source = read(DOCK_JS)
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Enter", "Escape"):
        assert key in source, f"坞键盘缺少 {key}"
    assert "togglePin" not in source
    assert '"Delete"' not in source


def test_dock_styles_do_not_keep_pin_or_drag_rules():
    css = read("static/css/modules/entry-dock.css")
    for forbidden in ("is-dragging", "is-drop-target", ".entry-overflow__pin"):
        assert forbidden not in css, f"坞样式仍有 v2 交互: {forbidden}"


# --------------------------------------------------------------------- 命令面板


def test_palette_merges_registry_palette_and_core_commands():
    source = read(PALETTE_JS)
    assert "paletteEntries()" in source
    assert "coreCommands" in source
    assert "CORE_ACTIONS" in source
    assert "HOST_COMMANDS" in source
    assert "commandPalette" in source, "面板必须覆盖 commandPalette 落点"
    assert "findByShortcut" in source
    assert "contributions:changed" in source
    assert "pluginHost.js" not in source


def test_palette_kill_switch_uses_shared_event_and_title():
    source = read(PALETTE_JS)
    assert "KILL_SWITCH_COMMAND_ID" in source
    assert "plugins:close-overlays" in source
    assert "插件：关闭所有浮动界面" in source
    assert "pluginId" in source and "nodeId" in source


def test_palette_shortcut_dispatch_uses_shortcut_trigger():
    source = read(PALETTE_JS)
    assert '"shortcut"' in source
    assert '"palette"' in source
    assert "isTypingTarget" in source
    assert "shortcutCombo" in source
    # 按下时求值：快捷键不写 when / layout 持久化。
    assert "layout.shortcuts" not in source
    assert "updateLayout" not in source


def test_palette_activate_dispatches_trigger_and_closes():
    source = read(PALETTE_JS)
    assert "activate(item)" in source
    assert "this.close()" in source
    assert '"contribution:trigger"' in source


def test_palette_ranks_prefix_matches_first():
    source = read(PALETTE_JS)
    assert "label.startsWith(query)" in source
    assert "score = 3" in source and "score = 2" in source
    assert "MAX_RESULTS" in source


def test_palette_template_renders_icon_label_description_and_shortcut():
    template = read(PALETTE_TMPL)
    assert "x-for=\"(entry, index) in items\"" in template
    assert "iconHtml(entry)" in template
    assert "entry.label" in template
    assert "entry.shortcut" in template
    assert "activate(entry)" in template
    assert "isDisabled(entry)" in template
    assert "entry.key" in template


def test_dock_and_palette_templates_do_not_reference_removed_registry():
    for rel in (DOCK_JS, DOCK_TMPL, PALETTE_JS, PALETTE_TMPL):
        source = read(rel)
        for forbidden in ("EntryRegistry", "entryRegistry.js", "entries:changed", "entry:activate"):
            assert forbidden not in source, f"{rel} 仍有 v2 残留: {forbidden}"
