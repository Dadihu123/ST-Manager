"""插件管理面板的 v3 契约（S12）。

面板从 v2 的「入口总览 / 快捷键改绑」迁移为 v3 的只读「贡献总览」，
并补上四件宿主职责：

- 能力位（``capabilities``，披露性）取代 ``permissions``，未知能力位显示「未知名」；
- ``frontend.render_mode``（``declarative`` / ``custom``）徽标与
  「自绘但未声明 ``ui.custom``」警告；
- ``frontend.global_styles`` 的全局样式风险提示；
- 前端激活失败展示 + 重试（派发 ``plugin:reload``），以及 kill switch
  「关闭所有插件浮层」（派发 ``plugins:close-overlays``）。

``settings.nav`` 落点由设置弹窗消费：插件导航项渲染在既有「插件管理」分区内，
点击派发 ``contribution:trigger``；``settings.section`` 插槽锚点挂在插件管理内容区。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANAGER_JS = "static/js/components/pluginManager.js"
MANAGER_TMPL = "templates/modals/plugin_manager.html"
SETTINGS_JS = "static/js/components/settingsModal.js"
SETTINGS_TMPL = "templates/modals/settings.html"
SETTINGS_CSS = "static/css/modules/modal-settings.css"
MANAGER_CSS = "static/css/modules/modal-plugin-manager.css"
PALETTE_JS = "static/js/components/commandPalette.js"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------- 页签与锚点


def test_four_tabs_cover_installed_catalog_upload_and_contributions():
    template = read(MANAGER_TMPL)
    for tab in ("installed", "catalog", "upload", "contributions"):
        assert f"id=\"plugin-tab-{tab}\"" in template
        assert f"id=\"plugin-panel-{tab}\"" in template
        assert f"selectTab('{tab}')" in template
    assert "plugin-tab-entries" not in template
    assert "plugin-panel-entries" not in template
    assert "入口总览" not in template
    assert "贡献总览" in template


def test_anchor_map_targets_the_contributions_panel():
    source = read(MANAGER_JS)
    assert '"plugin-panel-contributions": "contributions"' in source
    assert '"plugin-panel-entries"' not in source
    assert "CONFIG_ANCHOR_PATTERN" in source
    assert "SECRET_ANCHOR_PATTERN" in source
    assert '["installed", "catalog", "upload", "contributions"]' in source


def test_manager_is_embedded_in_existing_settings_plugins_section():
    settings = read(SETTINGS_TMPL)
    # 仍是既有「插件管理」分区的 include，不新增设置顶层 tab。
    assert '{% include "modals/plugin_manager.html" %}' in settings
    assert 'data-plugin-slot="settings.section"' in settings
    assert "settings-nav-plugin-group" in settings


# --------------------------------------------------------------------- 能力位 / 渲染方式


def test_capabilities_replace_permissions_with_unknown_names():
    source = read(MANAGER_JS)
    assert "CAPABILITY_LABELS" in source
    assert "\"ui.custom\":" in source
    assert "\"ui.global_styles\":" in source
    assert "capacity" not in source
    assert "capabilityLabel(capability)" in source
    assert '"未知名"' in source
    assert "capabilitiesOf(item)" in source
    assert "manifest.capabilities" in source
    assert "PERMISSION_LABELS" not in source
    assert "permissionLabels" not in source
    template = read(MANAGER_TMPL)
    assert "能力位" in template
    assert "permissions" not in template


def test_render_mode_badge_and_declaration_warning():
    source = read(MANAGER_JS)
    assert "RENDER_MODE_LABELS" in source
    assert '"declarative": "声明式"' in source or 'declarative: "声明式"' in source
    assert '"custom": "自绘"' in source or 'custom: "自绘"' in source
    assert "renderMode(item)" in source
    assert "manifest.render_mode" in source
    assert "manifest.frontend.render_mode" not in source
    assert "renderModeLabel(item)" in source
    assert "renderModeClass(item)" in source
    assert "未声明自绘" in source
    assert '"ui.custom"' in source
    template = read(MANAGER_TMPL)
    assert "renderModeLabel(item)" in template
    assert "renderModeWarning(item)" in template


def test_global_styles_warning_is_surfaced():
    source = read(MANAGER_JS)
    assert "globalStylesOf(item)" in source
    # S2 扁平快照：manifest 顶层 `frontend_global_styles`。
    assert "manifest.frontend_global_styles" in source
    assert "frontend.global_styles" not in source
    assert "此插件会修改全局样式" in source
    assert "ui.global_styles" in source
    template = read(MANAGER_TMPL)
    assert "globalStylesWarning(item)" in template


# --------------------------------------------------------------------- 贡献总览


def test_contribution_overview_is_built_from_manifest_contributions():
    source = read(MANAGER_JS)
    # `/api/plugins/list` 的 manifest 是 S2 扁平快照：`contributions` 在顶层，
    # 不是 v2 的 nested `frontend` 对象。
    assert "manifest.contributions" in source
    assert "frontend.contributions" not in source
    assert "contributionsOf(item)" in source
    assert "buildContributionRows" in source
    assert "walkMenus" in source
    assert "MENU_PLACEMENT_LABELS" in source
    assert "SLOT_LABELS" in source
    assert "EMPTY_SLOT_MODE_LABELS" in source
    assert "menu" in source and "slot" in source and "command" in source
    assert "contributionLocationLabel" in source
    assert "contributionKindLabel" in source
    # 菜单树缩进只对菜单节点生效。
    assert "contributionIndent(row)" in source


def test_contribution_overview_is_read_only_and_has_no_v2_shortcut_recorder():
    source = read(MANAGER_JS)
    for forbidden in (
        "entryRows",
        "entryQuery",
        "filteredEntryRows",
        "ENTRY_KIND_LABELS",
        "ENTRY_LOCATION_LABELS",
        "IMPLEMENTED_ENTRY_KINDS",
        "SURFACE_LABELS",
        "captureEntryShortcut",
        "onShortcutKeydown",
        "assignEntryShortcut",
        "clearEntryShortcut",
        "recordingKey",
        "settingsEntries",
        "openSettingsEntry",
        "EntryRegistry",
        "entryRegistry.js",
        "layout.shortcuts",
        "updateLayout",
    ):
        assert forbidden not in source, f"插件管理仍残留 v2: {forbidden}"
    template = read(MANAGER_TMPL)
    assert "contributionRows" in template
    assert "filteredContributionGroups" in template
    assert "contributionIndent(row)" in template
    assert "row.shortcut" in template
    for forbidden in ("entryRows", "recordingKey", "captureEntryShortcut", "openSettingsEntry"):
        assert forbidden not in template


def test_contribution_overview_groups_by_plugin_and_defaults_collapsed():
    source = read(MANAGER_JS)
    # 分组是派生数据：插件 -> 具体贡献，折叠状态只记插件 id，默认空数组。
    assert "get contributionGroups()" in source
    assert "get filteredContributionGroups()" in source
    assert "expandedContributionPlugins: []" in source
    assert "isContributionGroupOpen(pluginId)" in source
    assert "toggleContributionGroup(pluginId)" in source
    assert "contributionGroupSections(group)" in source
    assert "contributionOverviewSummary()" in source
    # 组内分节复用 kind 文案（菜单 / 插槽 / 命令），不另造一套标签。
    assert '["menu", "slot", "command"]' in source
    assert "this.contributionKindLabel({ kind })" in source
    # 筛选时自动展开命中分组（否则搜索后还要逐组点击）；清空后回到全折叠。
    assert 'this.$watch("contributionQuery"' in source
    assert "expandMatchingContributionGroups()" in source
    assert "collapseAllContributionGroups()" in source

    template = read(MANAGER_TMPL)
    assert "plugin-contribution-group" in template
    assert "plugin-contribution-summary" in template
    assert "plugin-contribution-body" in template
    assert 'x-for="group in filteredContributionGroups"' in template
    assert 'x-for="section in contributionGroupSections(group)"' in template
    assert '@click="toggleContributionGroup(group.pluginId)"' in template
    assert ':aria-expanded="isContributionGroupOpen(group.pluginId).toString()"' in template
    assert "全部展开" in template
    assert "全部折叠" in template
    # 旧的平铺表格已移除。
    assert "plugin-entries-table" not in template


def test_contribution_group_panel_styles_exist():
    css = read(MANAGER_CSS)
    for selector in (
        ".plugin-contribution-group",
        ".plugin-contribution-summary",
        ".plugin-contribution-chevron.is-open",
        ".plugin-contribution-body",
        ".plugin-contribution-section",
        ".plugin-contribution-row",
        ".plugin-contribution-location",
        ".plugin-contribution-description",
    ):
        assert selector in css, f"贡献分组样式缺少 {selector}"


def test_contribution_counts_are_disclosed_before_enable():
    source = read(MANAGER_JS)
    assert "contributionCounts(item)" in source
    assert "entryCountLabel(item)" in source
    assert "entryCount(item)" in source
    assert "条贡献（菜单" in source
    template = read(MANAGER_TMPL)
    assert "entryCount(item) > 0" in template
    assert "entryCountLabel(item)" in template


def test_manager_keeps_compare_versions_and_avoids_runtime_imports():
    source = read(MANAGER_JS)
    assert 'from "../contributionRegistry.js"' in source
    assert "compareVersions" in source
    assert "pluginHost.js" not in source
    assert "pluginSurfaceHost.js" not in source
    assert "entry:activate" not in source
    assert "entry:open" not in source


# --------------------------------------------------------------------- 失败与 kill switch


def test_frontend_failure_is_shown_and_retried_through_the_event():
    source = read(MANAGER_JS)
    assert "failedPluginIds" in source
    assert "isPluginFailed(item)" in source
    assert "pluginFailReason(item)" in source
    assert "retryPluginActivation(item)" in source
    assert '"plugin:reload"' in source
    assert "plugins:loaded" in source
    template = read(MANAGER_TMPL)
    assert "failedPluginIds" in template
    assert "isPluginFailed(item)" in template
    assert "retryPluginActivation" in template
    assert "前端激活失败" in template
    assert "重试" in template


def test_kill_switch_is_shared_between_manager_and_palette():
    manager_js = read(MANAGER_JS)
    manager_tmpl = read(MANAGER_TMPL)
    palette = read(PALETTE_JS)
    for source in (manager_js, manager_tmpl):
        assert "plugins:close-overlays" in source or "closeAllPluginOverlays()" in source
    assert "closeAllPluginOverlays()" in manager_js
    assert "plugins:close-overlays" in manager_js
    assert "关闭所有插件浮层" in manager_js
    assert "关闭所有插件浮层" in manager_tmpl
    assert "KILL_SWITCH_COMMAND_ID" in palette
    assert "插件：关闭所有浮动界面" in palette


def test_manager_css_covers_v3_surfaces():
    css = read(MANAGER_CSS)
    for selector in (
        ".plugin-card-render-mode",
        ".plugin-activation-failures",
        ".plugin-activation-failure-id",
        ".plugin-manager-kill-switch",
        ".plugin-manager-kill-switch-footer",
    ):
        assert selector in css, f"插件管理样式缺少 {selector}"


# --------------------------------------------------------------------- settings.nav / settings.section


def test_settings_nav_consumes_contribution_registry_menu_tree():
    source = read(SETTINGS_JS)
    assert 'ContributionRegistry.menuTree("settings.nav"' in source
    assert "pluginNavEntries" in source
    assert "refreshPluginNav" in source
    assert "openPluginNavEntry(node, event)" in source
    assert 'trigger: "menu"' in source or "trigger: 'menu'" in source
    assert "contributions:changed" in source
    assert "plugins:loaded" in source
    for forbidden in ("EntryRegistry", "entryRegistry.js", "entry:open", "entry:activate"):
        assert forbidden not in source, f"设置侧栏仍有 v2 残留: {forbidden}"
    # 点击设置导航先探测插件 surface；不存在时只警告，不抛错。
    assert "PluginSurfaceHost.has" in source
    assert "console.warn" in source


def test_settings_template_renders_plugin_nav_and_section_anchor():
    template = read(SETTINGS_TMPL)
    assert "pluginNavEntries" in template
    assert "openPluginNavEntry(node, $event)" in template
    assert "settings-nav-plugin-group" in template
    assert "settings-nav-subitems" in template
    assert 'data-plugin-slot="settings.section"' in template
    css = read(SETTINGS_CSS)
    assert ".settings-nav-divider" in css
    assert ".settings-nav-plugin-group" in css
    assert ".settings-nav-subitems" in css
    assert ".settings-plugin-slot" in css
