import re

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def find_contract_index(source, contract, start=0):
    index = source.find(contract, start)

    assert index != -1, f'Missing contract: {contract}'
    return index


def slice_between(source, start_contract, end_contract):
    start_index = find_contract_index(source, start_contract)
    end_index = find_contract_index(source, end_contract, start_index)
    return source[start_index:end_index]


def compact_whitespace(value):
    return ' '.join(value.split())


def assert_contains_either(source, candidates):
    assert any(candidate in source for candidate in candidates), (
        f'Expected one of {candidates!r} in source'
    )


def assert_matches(pattern, source):
    assert re.search(pattern, source, re.MULTILINE | re.DOTALL), (
        f'Missing regex contract: {pattern}'
    )


def test_tag_filter_template_adds_mobile_shell_and_tabs():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'tag-filter-mobile-shell' in template_source
    assert 'x-show="$store.global.deviceType === \'mobile\'"' in template_source
    assert 'tag-filter-mobile-topbar' in template_source
    assert 'tag-filter-mobile-tabs' in template_source
    assert "@click=\"switchMobileTagTab('filter')\"" in template_source
    assert "@click=\"switchMobileTagTab('sort')\"" in template_source
    assert "@click=\"switchMobileTagTab('delete')\"" in template_source
    assert "@click=\"switchMobileTagTab('category')\"" in template_source


def test_tag_filter_js_defines_mobile_active_tab_and_switch_helper():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert_contains_either(source, ["mobileActiveTab: 'filter'", 'mobileActiveTab: "filter"'])
    assert 'switchMobileTagTab(tab) {' in source
    assert 'syncMobileTabState(tab) {' in source


def test_tag_filter_js_keeps_mobile_tab_when_sync_rejects_switch():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'const changed = this.syncMobileTabState(tab);' in source
    assert 'if (changed === false) return;' in source
    assert 'this.mobileActiveTab = tab;' in source
    assert 'this.toggleSortMode();' not in source.split('syncMobileTabState(tab) {', 1)[1].split('init() {', 1)[0]


def test_tag_filter_template_mobile_tabs_expose_accessibility_state():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'aria-selected' in template_source
    assert 'role="tablist"' in template_source
    assert 'role="tab"' in template_source


def test_tag_filter_template_adds_mobile_mode_specific_panels_and_bottom_bar_markers():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'tag-filter-mobile-panel tag-filter-mobile-panel--filter' in template_source
    assert 'tag-filter-mobile-panel tag-filter-mobile-panel--delete' in template_source
    assert 'tag-filter-mobile-panel tag-filter-mobile-panel--category' in template_source
    assert 'tag-filter-mobile-bottombar' in template_source
    assert 'tag-filter-mobile-category-manager' in template_source


def test_tag_filter_template_mobile_panels_bind_to_mode_specific_state_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert "x-show=\"$store.global.deviceType === 'mobile' && mobileActiveTab === 'filter'\"" in template_source
    assert "x-show=\"$store.global.deviceType === 'mobile' && mobileActiveTab === 'delete'\"" in template_source
    assert "x-show=\"$store.global.deviceType === 'mobile' && mobileActiveTab === 'category'\"" in template_source
    assert "x-show=\"$store.global.deviceType === 'mobile' && showCategoryManager && mobileActiveTab === 'category'\"" in template_source


def test_tag_filter_template_gates_legacy_control_surface_to_non_mobile_only():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert "x-show=\"$store.global.deviceType !== 'mobile'\"" in template_source
    assert "x-show=\"$store.global.deviceType !== 'mobile' && isSortMode\"" in template_source
    assert "x-show=\"$store.global.deviceType !== 'mobile' && customOrderEnabled && !isSortMode\"" in template_source
    assert "x-show=\"desktopWorkspaceMode === 'filter' || desktopWorkspaceMode === 'batch-category' || desktopWorkspaceMode === 'sort' || desktopWorkspaceMode === 'category-manager' || desktopWorkspaceMode === 'blacklist' || desktopWorkspaceMode === 'delete'\"" in template_source
    assert "x-if=\"$store.global.deviceType !== 'mobile' && desktopWorkspaceMode === 'batch-category' && showCategoryMode && !isSortMode\"" in template_source
    assert "x-if=\"$store.global.deviceType !== 'mobile' && desktopWorkspaceMode === 'category-manager' && showCategoryManager && !isSortMode\"" in template_source
    assert 'class="tag-cloud-container custom-scrollbar"' in template_source


def test_tag_filter_template_desktop_topbar_has_sort_mode_context_label():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_topbar_section = template_source.split('<div class="tag-filter-workspace-topbar">', 1)[1].split('<div class="tag-filter-workspace-topbar-search">', 1)[0]
    compact_section = compact_whitespace(desktop_topbar_section)

    assert 'x-show="desktopWorkspaceMode === \'sort\'"' in desktop_topbar_section
    assert 'class="color-text-accent"' in desktop_topbar_section
    assert '>标签排序</span' in compact_section


def test_tag_filter_template_desktop_topbar_has_category_manager_context_label():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_topbar_section = template_source.split('<div class="tag-filter-workspace-topbar">', 1)[1].split('<div class="tag-filter-workspace-topbar-search">', 1)[0]
    compact_section = compact_whitespace(desktop_topbar_section)

    assert 'x-show="desktopWorkspaceMode === \'category-manager\' && !isDeleteMode"' in desktop_topbar_section
    assert 'class="color-text-info"' in desktop_topbar_section
    assert '>分类管理中心</span' in compact_section


def test_tag_filter_js_sync_mobile_tab_state_resets_mode_specific_mobile_state():
    source = read_project_file('static/js/components/tagFilterModal.js')
    section = source.split('syncMobileTabState(tab) {', 1)[1].split('init() {', 1)[0]

    assert_contains_either(section, [
        "['filter', 'sort', 'delete', 'category'].includes(tab)",
        '["filter", "sort", "delete", "category"].includes(tab)',
    ])
    assert_contains_either(section, [
        "if (previousTab === 'delete' && tab !== 'delete')",
        'if (previousTab === "delete" && tab !== "delete")',
    ])
    assert 'this.selectedTagsForDeletion = [];' in section
    assert_contains_either(section, [
        "if (previousTab === 'category' && tab !== 'category')",
        'if (previousTab === "category" && tab !== "category")',
    ])
    assert 'this.selectedCategoryTags = [];' in section
    assert_contains_either(section, ["this.categoryDraftName = '';", 'this.categoryDraftName = "";'])
    assert 'this.categoryDraftColor = DEFAULT_TAG_CATEGORY_COLOR;' in section
    assert 'this.categoryDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;' in section
    assert 'this.showCategoryManager = false;' in section


def test_tag_filter_js_sync_mobile_tab_state_clears_search_on_sort_entry_and_preserves_sort_guard():
    source = read_project_file('static/js/components/tagFilterModal.js')
    section = source.split('syncMobileTabState(tab) {', 1)[1].split('init() {', 1)[0]

    assert_contains_either(section, ["if (tab === 'sort')", 'if (tab === "sort")'])
    assert_contains_either(section, ["this.tagSearchQuery = '';", 'this.tagSearchQuery = "";'])
    assert 'this.cancelSortMode()' in section
    assert 'if (this.isSortMode && this.hasSortChanges)' in source
    assert '当前排序尚未保存，关闭后将丢失改动。确定关闭吗？' in source
    assert '当前排序尚未保存，确定放弃改动吗？' in source


def test_tag_filter_js_modal_close_resets_mobile_and_mode_specific_state_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    request_close_section = source.split('requestCloseModal() {', 1)[1].split('toggleFilterTag(tag, event = null) {', 1)[0]

    assert 'resetModalStateAfterClose()' in source
    assert 'this.resetModalStateAfterClose();' in request_close_section


def test_tag_filter_js_close_reset_helper_covers_task2_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    reset_section = source.split('resetModalStateAfterClose() {', 1)[1].split('requestCloseModal() {', 1)[0]

    assert 'this.selectedTagsForDeletion = [];' in reset_section
    assert 'this.selectedCategoryTags = [];' in reset_section
    assert_contains_either(reset_section, ["this.categoryDraftName = '';", 'this.categoryDraftName = "";'])
    assert 'this.categoryDraftColor = DEFAULT_TAG_CATEGORY_COLOR;' in reset_section
    assert 'this.categoryDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;' in reset_section
    assert 'this.showCategoryManager = false;' in reset_section
    assert_contains_either(reset_section, ["this.mobileActiveTab = 'filter';", 'this.mobileActiveTab = "filter";'])


def test_tag_filter_template_keeps_desktop_drag_sort_and_adds_mobile_reorder_rows():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'tag-filter-mobile-sort-row' in template_source
    assert '@click="moveSortTagUp(tag)"' in template_source
    assert '@click="moveSortTagDown(tag)"' in template_source
    assert 'draggable="true"' in template_source
    assert '@dragstart="onSortDragStart($event, tag)"' in template_source


def test_tag_filter_template_mobile_sort_controls_live_under_mobile_sort_panel_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert "x-show=\"$store.global.deviceType === 'mobile' && mobileActiveTab === 'sort'\"" in template_source
    assert 'class="tag-filter-mobile-panel tag-filter-mobile-panel--sort"' in template_source
    assert '上移' in template_source
    assert '下移' in template_source


def test_tag_filter_template_mobile_sort_bottom_bar_exposes_save_action():
    template_source = read_project_file('templates/modals/tag_filter.html')
    mobile_shell_section = slice_between(
        template_source,
        'class="tag-filter-mobile-shell"',
        '<template x-if="$store.global.deviceType !== \'mobile\'">',
    )

    assert 'class="tag-filter-mobile-bottombar"' in mobile_shell_section
    assert '@click="saveSortMode()"' in mobile_shell_section
    assert "x-show=\"mobileActiveTab === 'sort' && isSortMode\"" in mobile_shell_section
    assert '保存排序' in mobile_shell_section


def test_tag_filter_template_gates_shared_drag_sort_branch_to_desktop_only():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'x-if="$store.global.deviceType !== \'mobile\' && isSortMode"' in template_source
    shared_sort_section = template_source.split('class="tag-cloud-container custom-scrollbar"', 1)[1]
    assert 'x-if="$store.global.deviceType !== \'mobile\' && isSortMode"' in shared_sort_section
    assert '<template x-if="isSortMode">' not in shared_sort_section
    assert 'draggable="true"' in template_source
    assert '@dragstart="onSortDragStart($event, tag)"' in template_source


def test_tag_filter_js_defines_shared_sort_reorder_helpers():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'moveSortTag(tag, delta) {' in source
    assert 'moveSortTagUp(tag) {' in source
    assert 'moveSortTagDown(tag) {' in source
    assert 'return this.moveSortTag(tag, -1);' in source
    assert 'return this.moveSortTag(tag, 1);' in source


def test_tag_filter_js_shared_sort_reorder_helper_has_guardrails():
    source = read_project_file('static/js/components/tagFilterModal.js')
    section = source.split('moveSortTag(tag, delta) {', 1)[1].split('onSortDragStart(event, tag) {', 1)[0]

    assert 'const tags = [...(this.sortWorkingTags || [])];' in section
    assert 'if (!this.isSortMode || !tag || !Number.isFinite(delta)) return false;' in section
    assert 'const currentIndex = tags.indexOf(tag);' in section
    assert 'const targetIndex = currentIndex + delta;' in section
    assert_matches(
        r'if\s*\(\s*currentIndex\s*===\s*-1\s*\|\|\s*targetIndex\s*<\s*0\s*\|\|\s*targetIndex\s*>=\s*tags\.length\s*\)\s*return\s+false;',
        section,
    )
    assert 'tags.splice(currentIndex, 1);' in section
    assert 'tags.splice(targetIndex, 0, tag);' in section
    assert 'this.sortWorkingTags = tags;' in section


def test_tag_filter_js_keeps_cancelable_sort_leave_paths_after_mobile_reorder_addition():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert_contains_either(source, [
        "if (previousTab === 'sort' && tab !== 'sort' && this.isSortMode)",
        'if (previousTab === "sort" && tab !== "sort" && this.isSortMode)',
    ])
    assert 'this.cancelSortMode();' in source
    assert 'if (this.isSortMode) return false;' in source
    assert '当前排序尚未保存，关闭后将丢失改动。确定关闭吗？' in source
    assert '当前排序尚未保存，确定放弃改动吗？' in source


def test_tag_filter_mobile_css_fullscreen_shell_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    mobile_section = source.split('@media (max-width: 768px) {', 1)[1]

    assert '.tag-modal-container {' in mobile_section
    assert 'width: 100vw' in mobile_section
    assert 'height: 100dvh' in mobile_section
    assert 'min-height: 100dvh' in mobile_section


def test_tag_filter_mobile_css_has_single_main_scroll_region_and_stable_rails():
    source = read_project_file('static/css/modules/modal-tools.css')
    mobile_section = source.split('@media (max-width: 768px) {', 1)[1]

    assert '.tag-filter-mobile-tabs {' in mobile_section
    assert '.tag-filter-mobile-main {' in mobile_section
    assert 'overflow-y: auto' in mobile_section
    assert 'overscroll-behavior: contain' in mobile_section
    assert '-webkit-overflow-scrolling: touch' in mobile_section
    assert '.tag-filter-mobile-topbar {' in mobile_section
    assert '.tag-filter-mobile-bottombar {' in mobile_section
    assert 'flex-shrink: 0' in mobile_section


def test_tag_filter_mobile_css_includes_touch_target_and_sort_row_hooks():
    source = read_project_file('static/css/modules/modal-tools.css')
    mobile_section = source.split('@media (max-width: 768px) {', 1)[1]

    assert '.tag-filter-mobile-tabs button {' in mobile_section
    assert 'min-height: 44px' in mobile_section
    assert '.tag-filter-mobile-utility {' in mobile_section
    assert '.tag-filter-mobile-sort-row {' in mobile_section
    assert 'padding-bottom: calc(env(safe-area-inset-bottom, 0px) + ' in mobile_section


def test_tag_filter_template_mobile_shell_exposes_stable_layout_hooks():
    template_source = read_project_file('templates/modals/tag_filter.html')
    mobile_shell_section = slice_between(
        template_source,
        'class="tag-filter-mobile-shell"',
        '<template x-if="$store.global.deviceType !== \'mobile\'">',
    )

    assert 'class="tag-filter-mobile-utility"' in mobile_shell_section
    assert 'class="tag-filter-mobile-main custom-scrollbar"' in mobile_shell_section
    assert 'class="tag-filter-mobile-bottombar"' in mobile_shell_section
    assert 'class="tag-filter-mobile-sort-row"' in mobile_shell_section


def test_tag_filter_template_gates_legacy_shared_cloud_to_desktop_only_after_mobile_shell_split():
    template_source = read_project_file('templates/modals/tag_filter.html')
    compact_template = compact_whitespace(template_source)

    assert 'x-show="$store.global.deviceType !== \'mobile\'" class="tag-cloud-container custom-scrollbar"' in compact_template
    assert '<div class="tag-cloud-container custom-scrollbar">' not in template_source


def test_tag_filter_mobile_css_applies_touch_targets_to_utility_controls():
    source = read_project_file('static/css/modules/modal-tools.css')
    mobile_section = source.split('@media (max-width: 768px) {', 1)[1]

    assert '.tag-filter-mobile-utility .tag-category-filter-pill,' in mobile_section
    assert '.tag-filter-mobile-utility .tag-category-quick-btn,' in mobile_section
    assert 'min-height: 44px' in mobile_section


def test_tag_filter_template_mobile_category_panel_restores_save_and_existing_category_controls():
    template_source = read_project_file('templates/modals/tag_filter.html')
    mobile_shell_section = slice_between(
        template_source,
        'class="tag-filter-mobile-shell"',
        '<template x-if="$store.global.deviceType !== \'mobile\'">',
    )

    assert "x-show=\"$store.global.deviceType === 'mobile' && mobileActiveTab === 'category'\"" in mobile_shell_section
    assert 'x-model="categorySelectionInput"' in mobile_shell_section
    assert '@keydown.enter.prevent="applyCategorySelectionInput()"' in mobile_shell_section
    assert '@click="applyCategorySelectionInput()"' in mobile_shell_section
    assert '输入标签名，使用 |、逗号或换行批量选中当前可见标签' in mobile_shell_section
    assert '批量选中' in mobile_shell_section
    assert '@click="saveCategoryBatch()"' in mobile_shell_section
    assert ':disabled="!canSaveCategoryBatch"' in mobile_shell_section
    assert 'class="tag-category-quick-list"' in mobile_shell_section
    assert "x-for=\"name in availableCategoryNames\"" in mobile_shell_section
    assert '@click="setCategoryDraft(name)"' in mobile_shell_section


def test_tag_filter_template_mobile_category_panel_restores_manager_entry_and_surface():
    template_source = read_project_file('templates/modals/tag_filter.html')
    mobile_shell_section = slice_between(
        template_source,
        'class="tag-filter-mobile-shell"',
        '<template x-if="$store.global.deviceType !== \'mobile\'">',
    )

    assert '@click="toggleCategoryManager()"' in mobile_shell_section
    assert "x-text=\"showCategoryManager ? '收起分类管理' : '分类管理'\"" in mobile_shell_section


def test_governance_drawer_template_moves_governance_controls_into_top_tab_drawer_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'tag-filter-governance-drawer-toggle' in template_source
    assert 'class="tag-filter-governance-drawer"' in template_source
    assert '@click="toggleGovernanceDrawer()"' in template_source
    assert '<template x-if="isGovernanceDrawerOpen">' in template_source
    assert '记住上次标签视图' in template_source
    assert '拒绝新增未知标签（自动/批量来源）' in template_source
    assert '黑名单模式' in template_source


def test_governance_drawer_template_only_renders_drawer_shell_when_open():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert '<template x-if="isGovernanceDrawerOpen">' in template_source


def test_governance_drawer_template_keeps_current_mode_tool_area_free_of_governance_controls():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_section = slice_between(
        template_source,
        'class="tag-filter-current-mode-tool-area"',
        'class="tag-filter-workspace-tag-pool"',
    )

    assert '记住上次标签视图' not in tool_area_section
    assert '锁定标签库治理' not in tool_area_section
    assert 'x-model="tagBlacklistInput"' not in tool_area_section


def test_governance_drawer_template_marks_drawer_as_secondary_surface_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert 'class="tag-filter-governance-drawer-body"' in template_source
    assert '治理设置' in template_source
    assert '这里用于管理标签视图记忆，以及自动来源的标签准入规则。' in template_source


def test_governance_drawer_css_exposes_secondary_surface_hooks_contract():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-governance-drawer {' in source
    assert '.tag-filter-governance-drawer.is-open {' in source
    assert '.tag-filter-governance-drawer-body {' in source
    assert '.tag-filter-governance-drawer-toggle {' in source


def test_tag_filter_template_desktop_workbench_shell_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    compact_template = compact_whitespace(template_source)

    assert 'class="tag-filter-desktop-shell"' in template_source
    assert 'class="tag-filter-desktop-toolbar"' in template_source
    assert 'class="tag-filter-desktop-workbench"' in template_source
    assert 'class="tag-filter-desktop-main"' in template_source
    assert 'class="tag-filter-workspace-topbar"' in template_source
    assert 'class="tag-filter-workspace-top-tabs"' in template_source
    assert 'class="tag-filter-desktop-sidebar"' not in template_source
    assert 'x-show="$store.global.deviceType !== \'mobile\'" class="tag-filter-desktop-shell" :class="isDesktopWorkspaceFullscreen ? \'tag-filter-desktop-shell--fullscreen\' : \'\'"' in compact_template


def test_tag_filter_template_desktop_workbench_sections_keep_transition_modes_reachable():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_section = template_source.split('class="tag-filter-desktop-shell"', 1)[1]

    assert 'class="tag-filter-desktop-main"' in desktop_shell_section
    assert 'class="tag-filter-workspace-topbar"' in desktop_shell_section
    assert 'class="tag-filter-workspace-top-tabs"' in desktop_shell_section
    assert 'class="tag-filter-desktop-sidebar"' not in desktop_shell_section
    assert '@click="setDesktopWorkspaceMode(\'filter\')"' in desktop_shell_section
    assert '@click="desktopWorkspaceMode === \'batch-category\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'batch-category\')"' in desktop_shell_section
    assert '@click="desktopWorkspaceMode === \'sort\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'sort\')"' in desktop_shell_section
    assert '@click="desktopWorkspaceMode === \'delete\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'delete\')"' in desktop_shell_section
    assert '@click="desktopWorkspaceMode === \'blacklist\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'blacklist\')"' in desktop_shell_section
    assert '@click="desktopWorkspaceMode === \'category-manager\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'category-manager\')"' in desktop_shell_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'batch-category\' && showCategoryMode && !isSortMode"' in desktop_shell_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'blacklist\' && !isDeleteMode && !isSortMode"' in desktop_shell_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'category-manager\' && showCategoryManager && !isSortMode"' in desktop_shell_section


def test_tag_filter_template_desktop_workbench_exposes_governance_and_remember_view_controls_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_section = slice_between(
        template_source,
        'class="tag-filter-desktop-shell"',
        '</template>',
    )

    assert 'x-model="rememberLastTagView"' in desktop_shell_section
    assert 'x-model="lockTagLibrary"' in desktop_shell_section
    assert '@change="saveDesktopWorkbenchPrefs()"' in desktop_shell_section
    assert '@change="saveTagManagementPrefsState()"' in desktop_shell_section


def test_tag_filter_template_shared_view_panel_exposes_desktop_view_switch_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    compact_template = compact_whitespace(template_source)

    assert 'tag-filter-current-mode-tool-panel tag-filter-current-mode-tool-panel--view' in template_source
    assert '标签视图' in template_source
    assert '@click="showAllCategoriesMixed()"' in compact_template
    assert '@click="mixedCategoryView = false; saveDesktopWorkbenchPrefs()"' in compact_template


def test_tag_filter_desktop_workbench_shell_css_contract():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-desktop-shell {' in source
    assert '.tag-filter-desktop-toolbar {' in source
    assert '.tag-filter-desktop-workbench {' in source
    assert '.tag-filter-desktop-main {' in source
    assert '.tag-filter-workspace-topbar {' in source
    assert '.tag-filter-workspace-top-tabs {' in source
    assert '.tag-filter-desktop-sidebar {' not in source


def test_tag_filter_desktop_workbench_sections_css_size_header_and_main_without_sidebar():
    source = read_project_file('static/css/modules/modal-tools.css')
    desktop_workbench_section = source.split('.tag-filter-desktop-workbench {', 1)[1].split('.tag-filter-desktop-main {', 1)[0]
    desktop_main_section = source.split('.tag-filter-desktop-main {', 1)[1].split('.tag-filter-workspace-center {', 1)[0]
    tag_pool_section = source.split('.tag-filter-workspace-tag-pool {', 1)[1].split('.tag-filter-selected-basket {', 1)[0]

    assert 'display: grid' in desktop_workbench_section
    assert 'min-height: 0' in desktop_workbench_section
    assert 'grid-template-columns:' not in desktop_workbench_section
    assert 'grid-template-rows:' in desktop_workbench_section
    assert 'overflow: hidden' in desktop_main_section
    assert 'display: grid' in desktop_main_section
    assert 'overflow-y: auto' in tag_pool_section


def test_tag_filter_desktop_workbench_shell_css_widens_modal_container():
    source = read_project_file('static/css/modules/modal-tools.css')
    desktop_container_section = source.split('.tag-modal-container.tag-modal-container--desktop-workspace {', 1)[1].split('.tag-filter-desktop-shell {', 1)[0]

    assert 'width: min(1680px, 98vw);' in desktop_container_section
    assert 'max-width: 98vw;' in desktop_container_section
    assert 'height: min(940px, 96vh);' in desktop_container_section
    assert 'min-height: min(820px, 88vh);' in desktop_container_section


def test_tag_filter_template_desktop_workbench_shell_uses_x_if_branch_isolation():
    template_source = read_project_file('templates/modals/tag_filter.html')
    compact_template = compact_whitespace(template_source)

    assert '<template x-if="$store.global.deviceType === \'mobile\'">' in template_source
    assert '<template x-if="$store.global.deviceType !== \'mobile\'">' in template_source
    assert 'x-show="$store.global.deviceType === \'mobile\'" class="tag-filter-mobile-shell"' in compact_template
    assert 'x-show="$store.global.deviceType !== \'mobile\'" class="tag-filter-desktop-shell" :class="isDesktopWorkspaceFullscreen ? \'tag-filter-desktop-shell--fullscreen\' : \'\'"' in compact_template
    assert 'class="tag-filter-mobile-shell"' in template_source
    assert 'class="tag-filter-desktop-shell"' in template_source


def test_desktop_top_tabs_not_left_rail_replace_primary_navigation_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_index = find_contract_index(template_source, 'class="tag-filter-desktop-shell"')
    topbar_index = find_contract_index(template_source, 'class="tag-filter-workspace-topbar"', desktop_shell_index)
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"', desktop_shell_index)
    top_tabs_index = find_contract_index(template_source, 'class="tag-filter-workspace-top-tabs"', topbar_index)

    assert desktop_shell_index < topbar_index < top_tabs_index < center_index
    assert 'class="tag-filter-workspace-mode-rail"' not in template_source
    assert find_contract_index(template_source, 'class="tag-filter-workspace-top-tabs-nav"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="setDesktopWorkspaceMode(\'filter\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'batch-category\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'batch-category\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'sort\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'sort\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'delete\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'delete\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'blacklist\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'blacklist\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'category-manager\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'category-manager\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="toggleDesktopWorkspaceFullscreen()"', topbar_index) > topbar_index


def test_workspace_topbar_exposes_fullscreen_toggle_state_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    topbar_index = find_contract_index(template_source, 'class="tag-filter-workspace-topbar"')

    assert find_contract_index(template_source, 'class="tag-filter-workspace-topbar-actions"', topbar_index) > topbar_index
    assert find_contract_index(template_source, 'class="tag-filter-workspace-fullscreen-btn"', topbar_index) > topbar_index
    assert find_contract_index(template_source, ':class="isDesktopWorkspaceFullscreen ? \'is-active\' : \'\'"', topbar_index) > topbar_index
    assert find_contract_index(template_source, "x-text=\"isDesktopWorkspaceFullscreen ? '退出全屏' : '全屏工作台'\"", topbar_index) > topbar_index


def test_tool_area_filter_mode_contract_exposes_summary_clear_and_view_controls():
    template_source = read_project_file('templates/modals/tag_filter.html')
    filter_panel_section = template_source.split(
        'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'filter\' && !isSortMode && !isDeleteMode && !showCategoryMode && !showCategoryManager"',
        1,
    )[1].split('</template>', 1)[0]

    assert 'tag-filter-current-mode-tool-panel--filter' in filter_panel_section
    assert '筛选摘要' in filter_panel_section
    assert '已包含' in filter_panel_section
    assert '已排除' in filter_panel_section
    assert '可见标签' in filter_panel_section
    assert '@click="filterTags=[]; excludedTags=[]"' in filter_panel_section
    assert '清空筛选' in filter_panel_section
    assert '标签视图' not in filter_panel_section


def test_tool_area_batch_and_sort_contracts_use_single_desktop_tool_area():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_section = slice_between(
        template_source,
        'class="tag-filter-current-mode-tool-area"',
        'class="tag-filter-workspace-tag-pool"',
    )

    assert 'tag-filter-current-mode-tool-panel tag-filter-current-mode-tool-panel--batch-category' in template_source
    assert 'x-model="categorySelectionInput"' in template_source
    assert '@click="applyCategorySelectionInput()"' in template_source
    assert '输入标签名，使用 |、逗号或换行批量选中当前可见标签' in template_source
    assert '目标分类' in template_source
    assert '@click="saveCategoryBatch()"' in template_source
    assert 'tag-filter-current-mode-tool-panel tag-filter-current-mode-tool-panel--sort' in template_source
    assert '全局排序与分组拖拽' in template_source
    assert '当前标签顺序' in template_source
    assert '未保存改动' in template_source
    assert '@click="saveSortMode()"' in template_source
    assert '保存排序' in template_source
    assert 'tag-filter-current-mode-tool-panel--view' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--batch-category' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--sort' in tool_area_section


def test_tool_area_css_supports_single_desktop_mode_panels_contract():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-current-mode-tool-panel--filter {' in source
    assert '.tag-filter-current-mode-tool-panel--view,' in source
    assert '.tag-filter-current-mode-tool-summary-grid {' in source
    assert '.tag-filter-current-mode-tool-view-modes {' in source
    assert '.tag-filter-current-mode-tool-actions {' in source


def test_sort_mode_grouped_view_uses_sortable_category_blocks_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')

    assert 'x-for="group in sortModeTagGroups"' in template_source
    assert 'tag-group-block tag-group-block--sortable-category' in template_source
    assert 'class="tag-group-head tag-group-head--sortable"' in template_source
    assert '@dragstart="onSortCategoryDragStart($event, group.category)"' in template_source
    assert '@dragover="onSortCategoryDragOver($event, group.category)"' in template_source
    assert '@drop="onSortCategoryDrop($event, group.category)"' in template_source
    assert '.tag-group-block--sortable-category {' in source
    assert '.tag-group-head--sortable {' in source


def test_tool_area_css_stretches_category_manager_column_for_long_registry_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    tool_area_section = source.split('.tag-filter-current-mode-tool-area {', 1)[1].split('.tag-filter-current-mode-tool-panel {', 1)[0]

    assert 'align-self: stretch;' in tool_area_section
    assert '.tag-filter-category-manager-registry-area {' in source
    assert '.tag-filter-category-manager-registry-list {' in source
    assert 'flex: 1;' in source


def test_fullscreen_contract_stays_out_of_mobile_shell():
    template_source = read_project_file('templates/modals/tag_filter.html')
    mobile_shell_section = slice_between(
        template_source,
        'class="tag-filter-mobile-shell"',
        '<template x-if="$store.global.deviceType !== \'mobile\'">',
    )

    assert 'toggleDesktopWorkspaceFullscreen()' not in mobile_shell_section
    assert 'tag-filter-workspace-fullscreen-btn' not in mobile_shell_section
    assert 'tag-filter-desktop-shell--fullscreen' not in mobile_shell_section


def test_desktop_top_tabs_not_left_rail_keep_mode_transitions_reachable():
    template_source = read_project_file('templates/modals/tag_filter.html')
    top_tabs_index = find_contract_index(template_source, 'class="tag-filter-workspace-top-tabs"')
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"', top_tabs_index)

    assert top_tabs_index < center_index
    assert find_contract_index(template_source, '@click="setDesktopWorkspaceMode(\'filter\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'batch-category\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'batch-category\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'sort\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'sort\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'delete\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'delete\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'blacklist\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'blacklist\')"', top_tabs_index) > top_tabs_index
    assert find_contract_index(template_source, '@click="desktopWorkspaceMode === \'category-manager\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'category-manager\')"', top_tabs_index) > top_tabs_index
    assert 'x-show="false"' not in template_source


def test_desktop_top_tabs_not_left_rail_expose_six_primary_entries_in_spec_order():
    template_source = read_project_file('templates/modals/tag_filter.html')
    top_tabs_section = template_source.split('class="tag-filter-workspace-top-tabs"', 1)[1].split('class="tag-filter-workspace-center"', 1)[0]

    expected_labels = ['筛选', '批量分类', '排序', '删除', '黑名单', '分类管理']
    label_positions = [find_contract_index(top_tabs_section, label) for label in expected_labels]

    assert label_positions == sorted(label_positions)
    assert top_tabs_section.count('class="tag-filter-workspace-top-tab"') == 6


def test_desktop_governance_drawer_moves_governance_controls_out_of_persistent_context_panel():
    template_source = read_project_file('templates/modals/tag_filter.html')
    governance_toggle_index = find_contract_index(template_source, 'tag-filter-governance-drawer-toggle')
    governance_drawer_index = find_contract_index(template_source, 'class="tag-filter-governance-drawer"', governance_toggle_index)

    assert 'class="tag-filter-workspace-context custom-scrollbar"' not in template_source
    assert find_contract_index(template_source, 'x-model="rememberLastTagView"', governance_drawer_index) > governance_drawer_index
    assert find_contract_index(template_source, 'x-model="lockTagLibrary"', governance_drawer_index) > governance_drawer_index
    assert template_source.find('x-model="tagBlacklistInput"', governance_drawer_index) == -1
    assert find_contract_index(template_source, '@click="toggleGovernanceDrawer()"', governance_toggle_index) >= governance_toggle_index
    assert find_contract_index(template_source, '<template x-if="isGovernanceDrawerOpen">', governance_toggle_index) > governance_toggle_index


def test_desktop_governance_drawer_attaches_to_top_tabs_instead_of_consuming_shell_row():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_section = template_source.split('class="tag-filter-desktop-shell"', 1)[1]
    top_tabs_section = desktop_shell_section.split('<div class="tag-filter-workspace-top-tabs">', 1)[1].split('<div class="tag-filter-desktop-workbench">', 1)[0]
    topbar_actions_section = desktop_shell_section.split('<div class="tag-filter-workspace-topbar-actions">', 1)[1].split('</div>', 1)[0]

    assert 'class="tag-filter-governance-drawer"' not in top_tabs_section
    assert 'class="tag-filter-governance-drawer"' in topbar_actions_section
    assert desktop_shell_section.count('class="tag-filter-governance-drawer"') == 1


def test_desktop_governance_drawer_css_anchors_overlay_to_topbar_actions_region():
    source = read_project_file('static/css/modules/modal-tools.css')
    topbar_actions_section = source.split('.tag-filter-workspace-topbar-actions {', 1)[1].split('.tag-filter-workspace-fullscreen-btn {', 1)[0]
    drawer_section = source.split('.tag-filter-governance-drawer {', 1)[1].split('.tag-filter-governance-drawer.is-open {', 1)[0]

    assert 'position: relative;' in topbar_actions_section
    assert 'position: absolute;' in drawer_section
    assert 'top:' in drawer_section
    assert 'right: 0;' in drawer_section


def test_desktop_single_current_mode_tool_area_replaces_persistent_right_context_structure():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_index = find_contract_index(template_source, 'class="tag-filter-desktop-shell"')
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"', desktop_shell_index)
    tool_area_index = find_contract_index(template_source, 'class="tag-filter-current-mode-tool-area"', center_index)

    assert desktop_shell_index < center_index < tool_area_index
    assert find_contract_index(template_source, 'class="tag-filter-current-mode-tool-panel ', tool_area_index) > tool_area_index
    assert 'tag-filter-context-mode-panel--sort' not in template_source
    assert 'tag-filter-context-mode-panel--delete' not in template_source
    assert 'tag-filter-context-mode-panel--batch-category' not in template_source
    assert 'tag-filter-context-mode-panel--category-manager' not in template_source


def test_desktop_single_current_mode_tool_area_surfaces_sort_tools_only_in_active_panel():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_index = find_contract_index(template_source, 'class="tag-filter-current-mode-tool-area"')

    assert find_contract_index(
        template_source,
        'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'sort\' && isSortMode"',
        tool_area_index,
    ) > tool_area_index
    assert find_contract_index(template_source, '全局排序与分组拖拽', tool_area_index) > tool_area_index
    assert find_contract_index(template_source, "x-text=\"customOrderEnabled ? '自定义' : '字符序'\"", tool_area_index) > tool_area_index
    assert find_contract_index(template_source, "x-text=\"hasSortChanges ? '有' : '无'\"", tool_area_index) > tool_area_index


def test_desktop_governance_drawer_and_single_current_mode_tool_area_define_separate_layout_hooks():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')

    assert 'class="tag-filter-governance-drawer"' in template_source
    assert 'class="tag-filter-current-mode-tool-area"' in template_source
    assert 'class="tag-filter-current-mode-tool-panel ' in template_source
    assert 'tag-filter-context-section' not in template_source
    assert 'tag-filter-context-block--governance' not in template_source
    assert 'tag-filter-context-block--sort-tools' not in template_source
    assert '.tag-filter-governance-drawer {' in source
    assert '.tag-filter-governance-drawer.is-open {' in source
    assert '.tag-filter-current-mode-tool-area {' in source
    assert '.tag-filter-current-mode-tool-panel {' in source


def test_desktop_single_current_mode_tool_area_uses_one_active_panel_branch_at_a_time():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_section = template_source.split('class="tag-filter-current-mode-tool-area"', 1)[1].split('class="tag-filter-workspace-footer"', 1)[0]

    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'sort\' && isSortMode"' in tool_area_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'delete\' && isDeleteMode"' in tool_area_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'batch-category\' && showCategoryMode && !isSortMode"' in tool_area_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'blacklist\' && !isDeleteMode && !isSortMode"' in tool_area_section
    assert 'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'category-manager\' && showCategoryManager && !isSortMode"' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--sort' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--delete' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--batch-category' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--blacklist' in tool_area_section
    assert 'tag-filter-current-mode-tool-panel--category-manager' in tool_area_section
    assert 'tag-filter-context-mode-panel' not in tool_area_section


def test_desktop_single_current_mode_tool_area_avoids_persistent_multi_mode_right_column_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_section = template_source.split('class="tag-filter-current-mode-tool-area"', 1)[1].split('class="tag-filter-workspace-footer"', 1)[0]

    assert 'desktopWorkspaceMode === \'sort\' && isSortMode' in tool_area_section
    assert 'desktopWorkspaceMode === \'delete\' && isDeleteMode' in tool_area_section
    assert 'desktopWorkspaceMode === \'batch-category\' && showCategoryMode && !isSortMode' in tool_area_section
    assert 'desktopWorkspaceMode === \'category-manager\' && showCategoryManager && !isSortMode' in tool_area_section
    assert 'tag-filter-context-section--prominent' not in tool_area_section
    assert 'tag-filter-context-block--sort-tools' not in tool_area_section
    assert 'tag-filter-context-block--delete-tools' not in tool_area_section
    assert 'tag-filter-context-block--batch-category-tools' not in tool_area_section
    assert 'tag-filter-context-block--category-manager-tools' not in tool_area_section


def test_desktop_single_current_mode_tool_area_category_manager_panel_uses_stacked_layout_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    tool_area_section = template_source.split('class="tag-filter-current-mode-tool-area"', 1)[1].split('class="tag-filter-workspace-footer"', 1)[0]

    assert 'tag-filter-current-mode-tool-panel tag-filter-current-mode-tool-panel--category-manager' in tool_area_section
    assert 'class="tag-filter-category-manager-stack"' in tool_area_section
    assert 'class="tag-filter-category-manager-stack-item tag-filter-category-manager-stack-item--draft"' in tool_area_section
    assert 'class="tag-filter-category-manager-stack-item tag-filter-category-manager-stack-item--registry"' in tool_area_section
    assert '.tag-filter-category-manager-stack {' in source
    assert 'grid-template-columns: minmax(0, 1fr);' in source
    assert '.tag-filter-category-manager-stack-item {' in source
    assert '.tag-filter-current-mode-tool-panel--category-manager' in source
    assert '.tag-category-editor-row.tag-category-editor-row-main {' in source
    assert 'align-items: stretch;' in source


def test_desktop_single_current_mode_tool_area_delete_and_category_manager_panels_use_narrow_column_stack_layout_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    tool_area_section = template_source.split('class="tag-filter-current-mode-tool-area"', 1)[1].split('class="tag-filter-workspace-footer"', 1)[0]

    assert 'class="tag-filter-delete-stack"' in tool_area_section
    assert 'class="tag-filter-delete-stack-item tag-filter-delete-stack-item--summary"' in tool_area_section
    assert 'class="tag-filter-delete-stack-item tag-filter-delete-stack-item--list tag-filter-delete-stack-item--pending"' in tool_area_section
    assert 'class="tag-filter-delete-stack-item tag-filter-delete-stack-item--actions tag-filter-delete-stack-item--danger"' in tool_area_section
    assert '.tag-filter-delete-stack {' in source
    assert '.tag-filter-delete-stack-item {' in source
    assert '.tag-filter-category-manager-registry-area {' in source
    assert '.tag-filter-category-manager-registry-list {' in source


def test_complex_modes_use_stacked_tool_layout():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    tool_area_section = template_source.split('class="tag-filter-current-mode-tool-area"', 1)[1].split('class="tag-filter-workspace-tag-pool"', 1)[0]

    assert 'tag-filter-delete-stack-item--pending' in tool_area_section
    assert 'class="tag-filter-delete-pending-list custom-scrollbar"' in tool_area_section
    assert 'tag-filter-delete-stack-item--danger' in tool_area_section
    assert tool_area_section.count('tag-filter-delete-stack-item--pending') == 1
    assert tool_area_section.count('tag-filter-delete-stack-item--danger') == 1
    assert '删除操作不可撤销' in tool_area_section
    assert 'class="tag-filter-category-manager-draft-area"' in tool_area_section
    assert 'class="tag-filter-category-manager-registry-area"' in tool_area_section
    assert 'class="tag-filter-category-manager-registry-list custom-scrollbar"' in tool_area_section
    assert '.tag-filter-current-mode-tool-panel--delete {' in source
    assert '.tag-filter-delete-pending-list {' in source
    assert '.tag-filter-delete-stack-item--danger {' in source
    assert '.tag-filter-current-mode-tool-panel--category-manager {' in source
    assert '.tag-filter-category-manager-draft-area {' in source
    assert '.tag-filter-category-manager-registry-area {' in source
    assert '.tag-filter-category-manager-registry-list {' in source


def test_selected_tag_area_wording():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert '已选标签区' in template_source
    assert '已选标签篮' not in template_source


def test_desktop_non_fullscreen_workspace_uses_parent_modal_height_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    compact_template = compact_whitespace(template_source)

    assert 'class="tag-modal-container" :class="[isDesktopWorkspaceFullscreen && $store.global.deviceType !== \'mobile\' ? \'tag-modal-container--desktop-fullscreen\' : \'\', $store.global.deviceType !== \'mobile\' ? \'tag-modal-container--desktop-workspace\' : \'\']" @click.away="requestCloseTagFilterEditor()"' in compact_template
    assert '.tag-modal-container.tag-modal-container--desktop-workspace {' in source
    desktop_container_section = source.split('.tag-modal-container.tag-modal-container--desktop-workspace {', 1)[1].split('.tag-filter-desktop-shell {', 1)[0]
    assert 'width: min(1680px, 98vw);' in desktop_container_section
    assert 'max-width: 98vw;' in desktop_container_section
    assert 'height: min(940px, 96vh);' in desktop_container_section
    assert 'min-height: min(820px, 88vh);' in desktop_container_section
    assert '.tag-filter-desktop-shell {' in source
    desktop_shell_section = source.split('.tag-filter-desktop-shell {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]
    assert 'height: 100%;' in desktop_shell_section
    assert 'min-height: 0;' in desktop_shell_section


def test_desktop_workspace_shell_and_single_current_mode_tool_area_keep_stable_stretch_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')

    assert 'class="tag-filter-current-mode-tool-area"' in template_source
    assert '.tag-filter-workspace-center {' in source
    assert '.tag-filter-current-mode-tool-area {' in source
    assert '.tag-filter-current-mode-tool-panel {' in source
    assert 'height: 100%;' in source
    assert 'overflow-y: auto;' in source
    assert 'align-self: stretch;' in source


def test_desktop_single_current_mode_tool_area_exposes_delete_pending_list_and_confirm_action():
    template_source = read_project_file('templates/modals/tag_filter.html')
    tool_area_index = find_contract_index(template_source, 'class="tag-filter-current-mode-tool-area"')

    assert find_contract_index(
        template_source,
        'x-if="$store.global.deviceType !== \'mobile\' && desktopWorkspaceMode === \'delete\' && isDeleteMode"',
        tool_area_index,
    ) > tool_area_index
    assert find_contract_index(template_source, '待删除标签', tool_area_index) > tool_area_index
    assert find_contract_index(template_source, "x-text=\"selectedTagsForDeletion.length\"", tool_area_index) > tool_area_index
    assert find_contract_index(template_source, "x-for=\"tag in selectedTagsForDeletion\"", tool_area_index) > tool_area_index
    assert find_contract_index(template_source, '@click="addDeleteSelectionToBlacklist()"', tool_area_index) > tool_area_index
    assert find_contract_index(template_source, '@click="deleteSelectedTags()"', tool_area_index) > tool_area_index


def test_blacklist_and_delete_mode_copy_reflects_blacklist_governance_flow():
    template_source = read_project_file('templates/modals/tag_filter.html')

    assert '可直接将选中标签加入黑名单，避免误删。' in template_source
    assert '输入任意标签名，使用 |、逗号或换行批量加入黑名单选择' in template_source
    assert '下方会显示待加入黑名单的具体标签。' in template_source
    assert '加入黑名单' in template_source


def test_blacklist_mode_template_exposes_pending_selection_preview_list():
    template_source = read_project_file('templates/modals/tag_filter.html')
    blacklist_index = find_contract_index(
        template_source,
        'desktopWorkspaceMode === \'blacklist\'',
    )

    assert find_contract_index(template_source, '待加入黑名单', blacklist_index) > blacklist_index
    assert find_contract_index(template_source, '当前没有待加入黑名单的标签。', blacklist_index) > blacklist_index
    assert find_contract_index(template_source, 'x-for="tag in selectedBlacklistTags"', blacklist_index) > blacklist_index
    assert find_contract_index(template_source, '@click="toggleTagSelectionForBlacklist(tag)"', blacklist_index) > blacklist_index


def test_integrates_tag_pool_and_footer():
    template_source = read_project_file('templates/modals/tag_filter.html')
    desktop_shell_index = find_contract_index(template_source, 'class="tag-filter-desktop-shell"')
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"', desktop_shell_index)
    tag_pool_index = find_contract_index(template_source, 'class="tag-filter-workspace-tag-pool"', center_index)
    footer_index = find_contract_index(template_source, 'class="tag-filter-workspace-footer"', tag_pool_index)

    assert desktop_shell_index < center_index < tag_pool_index < footer_index


def test_near_fullscreen_shell():
    source = read_project_file('static/css/modules/modal-tools.css')
    desktop_shell_section = source.split('.tag-filter-desktop-shell {', 1)[1].split('@media (max-width: 768px) {', 1)[0]

    assert 'width: 100%;' in desktop_shell_section
    assert 'max-width: 100%;' in desktop_shell_section
    assert 'height: 100%;' in desktop_shell_section
    assert 'min-height: 0;' in desktop_shell_section
    assert 'grid-template-rows: auto minmax(0, 1fr) auto;' in desktop_shell_section


def test_tag_filter_mobile_shell_does_not_inherit_desktop_modal_sizing_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    modal_container_section = source.split('.tag-modal-container {', 1)[1].split('.tag-modal-container.tag-modal-container--desktop-fullscreen {', 1)[0]
    desktop_container_section = source.split('.tag-modal-container.tag-modal-container--desktop-workspace {', 1)[1].split('.tag-filter-desktop-shell {', 1)[0]
    desktop_shell_section = source.split('.tag-filter-desktop-shell {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]

    assert 'width: min(1680px, 98vw);' not in modal_container_section
    assert 'height: min(940px, 96vh);' not in modal_container_section
    assert 'min-height: min(820px, 88vh);' not in modal_container_section
    assert 'width: min(1680px, 98vw);' in desktop_container_section
    assert 'height: min(940px, 96vh);' in desktop_container_section
    assert 'min-height: min(820px, 88vh);' in desktop_container_section
    assert 'width: 100%;' in desktop_shell_section
    assert 'height: 100%;' in desktop_shell_section


def test_fixed_non_fullscreen_shell_with_internal_scroll():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')

    desktop_container_section = source.split('.tag-modal-container.tag-modal-container--desktop-workspace {', 1)[1].split('.tag-filter-desktop-shell {', 1)[0]
    desktop_shell_section = source.split('.tag-filter-desktop-shell {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]
    topbar_section = source.split('.tag-filter-workspace-topbar {', 1)[1].split('.tag-filter-workspace-topbar-main {', 1)[0]
    top_tabs_section = source.split('.tag-filter-workspace-top-tabs {', 1)[1].split('.tag-filter-workspace-top-tabs-nav {', 1)[0]
    desktop_main_section = source.split('.tag-filter-desktop-main {', 1)[1].split('.tag-filter-workspace-center {', 1)[0]
    center_section = source.split('.tag-filter-workspace-center {', 1)[1].split('.tag-filter-current-mode-tool-area {', 1)[0]
    tag_pool_section = source.split('.tag-filter-workspace-tag-pool {', 1)[1].split('.tag-filter-selected-basket {', 1)[0]
    tool_area_section = source.split('.tag-filter-current-mode-tool-area {', 1)[1].split('.tag-filter-current-mode-tool-panel {', 1)[0]
    basket_section = source.split('.tag-filter-selected-basket--workspace {', 1)[1].split('.tag-filter-selected-basket-header {', 1)[0]
    footer_section = source.split('.tag-filter-workspace-footer {', 1)[1].split('.adv-tab-bar {', 1)[0]

    assert 'height: min(940px, 96vh);' in desktop_container_section
    assert 'min-height: min(820px, 88vh);' in desktop_container_section
    assert 'grid-template-rows: auto auto minmax(0, 1fr);' in desktop_shell_section
    assert 'overflow: hidden;' in desktop_shell_section
    assert 'position: sticky;' in topbar_section
    assert 'top: 0;' in topbar_section
    assert 'position: sticky;' in top_tabs_section
    assert 'top:' in top_tabs_section
    assert 'overflow: hidden;' in desktop_main_section
    assert 'display: grid;' in desktop_main_section
    assert 'width: 100%;' in desktop_main_section
    assert 'height: 100%;' in desktop_main_section
    assert 'grid-template-columns:' in desktop_main_section
    assert 'overflow: hidden;' in center_section
    assert 'display: flex;' in center_section
    assert 'flex-direction: column;' in center_section
    assert 'width: 100%;' in center_section
    assert 'grid-template-columns: minmax(0, 1fr) minmax(20rem, 28rem);' not in center_section
    assert 'grid-template-rows: auto minmax(0, 1fr) auto;' not in center_section
    assert 'overflow-y: auto;' in tag_pool_section
    assert 'grid-column: 1;' in tag_pool_section
    assert 'grid-row: 2;' in tag_pool_section
    assert 'overflow-y: auto;' in tool_area_section
    assert 'grid-column: 2;' in tool_area_section
    assert 'grid-row: 2;' in tool_area_section
    assert 'overscroll-behavior: contain;' in tag_pool_section
    assert 'overscroll-behavior: contain;' in tool_area_section
    assert 'grid-column: 1 / -1;' in basket_section
    assert 'grid-row: 1;' in basket_section
    assert 'grid-column: 1 / -1;' in footer_section
    assert 'grid-row: 3;' in footer_section
    assert footer_section.count('@click="saveSortMode()"') == 0
    assert 'class="tag-filter-workspace-topbar"' in template_source
    assert 'class="tag-filter-workspace-top-tabs"' in template_source
    assert 'class="tag-filter-workspace-center"' in template_source
    assert 'class="tag-filter-workspace-tag-pool"' in template_source
    assert 'class="tag-filter-current-mode-tool-area"' in template_source


def test_desktop_workspace_fullscreen_css_contract():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {' in source
    assert 'padding: clamp(1rem, 1.6vw, 1.75rem);' in source
    assert 'box-sizing: border-box;' in source
    assert 'border-radius: 0;' in source
    assert '.tag-filter-workspace-fullscreen-btn {' in source
    assert '.tag-filter-workspace-fullscreen-btn.is-active {' in source
    assert '.tag-modal-container.tag-modal-container--desktop-fullscreen {' in source


def test_desktop_template_routes_fullscreen_state_to_parent_modal_container():
    template_source = read_project_file('templates/modals/tag_filter.html')
    compact_template = compact_whitespace(template_source)

    assert 'class="tag-modal-container" :class="[isDesktopWorkspaceFullscreen && $store.global.deviceType !== \'mobile\' ? \'tag-modal-container--desktop-fullscreen\' : \'\', $store.global.deviceType !== \'mobile\' ? \'tag-modal-container--desktop-workspace\' : \'\']" @click.away="requestCloseTagFilterEditor()"' in compact_template
    assert 'class="modal-overlay" :class="isDesktopWorkspaceFullscreen && $store.global.deviceType !== \'mobile\' ? \'modal-overlay--desktop-workspace-fullscreen\' : \'\'"' in compact_template


def test_desktop_topbar_owns_search_and_selection_summary_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    topbar_index = find_contract_index(template_source, 'class="tag-filter-workspace-topbar"')
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"', topbar_index)
    footer_index = find_contract_index(template_source, 'class="tag-filter-workspace-footer"', center_index)

    search_index = find_contract_index(template_source, 'x-model="tagSearchQuery"', topbar_index)
    summary_index = find_contract_index(template_source, 'class="tag-filter-workspace-selection-summary"', topbar_index)
    summary_section = template_source[summary_index:center_index]

    assert topbar_index < search_index < center_index
    assert topbar_index < summary_index < center_index
    assert 'class="tag-filter-workspace-topbar-search"' in template_source
    assert '已选' in summary_section
    assert 'x-text="filterTags.length + excludedTags.length"' in summary_section
    assert '可见' in summary_section
    assert 'x-text="filteredVisibleTagCount"' in summary_section
    assert template_source.find('x-model="tagSearchQuery"', center_index, footer_index) == -1


def test_desktop_center_keeps_persistent_selected_tag_basket_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    center_index = find_contract_index(template_source, 'class="tag-filter-workspace-center"')
    tool_area_index = find_contract_index(template_source, 'class="tag-filter-current-mode-tool-area"', center_index)
    basket_index = find_contract_index(
        template_source,
        'class="tag-filter-selected-basket tag-filter-selected-basket--workspace"',
        center_index,
    )

    assert center_index < basket_index < tool_area_index
    assert 'class="tag-filter-selected-basket-header tag-filter-selected-basket-header--calm"' in template_source
    assert 'class="tag-filter-selected-basket-list custom-scrollbar tag-filter-selected-basket-list--workspace"' in template_source
    assert 'class="tag-filter-selected-basket-chip tag-filter-selected-basket-chip--included tag-filter-selected-basket-chip--workspace"' in template_source
    assert 'class="tag-filter-selected-basket-chip tag-filter-selected-basket-chip--excluded tag-filter-selected-basket-chip--workspace"' in template_source
    assert '@click="filterTags = filterTags.filter(item => item !== tag)"' in template_source
    assert '@click="excludedTags = excludedTags.filter(item => item !== tag)"' in template_source


def test_desktop_workspace_fullscreen_parent_css_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    fullscreen_parent_section = source.split('.tag-modal-container.tag-modal-container--desktop-fullscreen {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]

    assert '.tag-modal-container.tag-modal-container--desktop-fullscreen {' in source
    assert 'width: 100%;' in fullscreen_parent_section
    assert 'max-width: 100%;' in fullscreen_parent_section
    assert 'height: 100%;' in fullscreen_parent_section
    assert 'min-height: 100%;' in fullscreen_parent_section
    assert 'padding: 0;' in fullscreen_parent_section
    assert 'border: none;' in fullscreen_parent_section
    assert 'border-radius: 0;' in fullscreen_parent_section
    assert 'box-shadow: none;' in fullscreen_parent_section


def test_desktop_workspace_fullscreen_overlay_stops_centering_modal_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    overlay_section = source.split('.modal-overlay.modal-overlay--desktop-workspace-fullscreen {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]

    assert 'align-items: stretch;' in overlay_section
    assert 'justify-content: stretch;' in overlay_section
    assert 'padding: 0;' in overlay_section


def test_desktop_workspace_fullscreen_shell_uses_inner_safe_inset_instead_of_negative_margin_hack():
    source = read_project_file('static/css/modules/modal-tools.css')
    fullscreen_shell_section = source.split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[1].split('.tag-filter-desktop-toolbar {', 1)[0]

    assert 'width: 100%;' in fullscreen_shell_section
    assert 'height: 100%;' in fullscreen_shell_section
    assert 'margin: 0;' in fullscreen_shell_section
    assert 'padding: clamp(1rem, 1.6vw, 1.75rem);' in fullscreen_shell_section
    assert 'margin: -1.5rem;' not in fullscreen_shell_section


def test_desktop_workspace_css_exposes_topbar_search_summary_and_selected_basket_hooks():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-workspace-topbar-search {' in source
    assert '.tag-filter-workspace-selection-summary {' in source
    assert '.tag-filter-selected-basket {' in source
    assert '.tag-filter-selected-basket-header {' in source
    assert '.tag-filter-selected-basket-list {' in source
    assert '.tag-filter-selected-basket-chip {' in source
    assert '.tag-filter-selected-basket-chip--included {' in source
    assert '.tag-filter-selected-basket-chip--excluded {' in source


def test_topbar_groups_search_status_and_actions():
    template_source = read_project_file('templates/modals/tag_filter.html')
    topbar_section = template_source.split('<div class="tag-filter-workspace-topbar">', 1)[1].split('<div class="tag-filter-desktop-workbench">', 1)[0]

    assert 'class="tag-filter-workspace-topbar-main"' in topbar_section
    assert 'class="tag-filter-workspace-topbar-status"' in topbar_section
    assert 'class="tag-filter-workspace-topbar-search"' in topbar_section
    assert 'class="tag-filter-workspace-selection-summary"' in topbar_section
    assert 'class="tag-filter-workspace-topbar-actions"' in topbar_section


def test_desktop_top_tabs_not_left_rail_use_tab_navigation_hooks():
    template_source = read_project_file('templates/modals/tag_filter.html')
    top_tabs_section = template_source.split('<div class="tag-filter-workspace-top-tabs">', 1)[1].split('<div class="tag-filter-desktop-workbench">', 1)[0]

    assert 'class="tag-filter-workspace-top-tabs-nav"' in top_tabs_section
    assert top_tabs_section.count('class="tag-filter-workspace-top-tab"') == 6
    assert '恢复字符排序' not in top_tabs_section
    assert '治理设置' not in top_tabs_section


def test_topbar_actions_host_governance_entry_outside_primary_tabs():
    template_source = read_project_file('templates/modals/tag_filter.html')
    topbar_actions_section = template_source.split('<div class="tag-filter-workspace-topbar-actions">', 1)[1].split('</div>', 1)[0]

    assert '恢复字符排序' in topbar_actions_section
    assert '帮助' in topbar_actions_section
    assert 'tag-filter-governance-drawer-toggle' in topbar_actions_section
    assert '治理设置' in topbar_actions_section


def test_workspace_utility_actions_host_restore_sort_outside_primary_tabs():
    template_source = read_project_file('templates/modals/tag_filter.html')
    workbench_section = template_source.split('<div class="tag-filter-desktop-workbench">', 1)[1].split('<div class="tag-filter-workspace-center">', 1)[0]

    assert '恢复字符排序' not in workbench_section
    assert 'tag-filter-workspace-utility-actions' not in workbench_section


def test_compact_workspace_layout_css_removes_redundant_gap_and_persistent_right_shell_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    desktop_shell_section = source.split('.tag-filter-desktop-shell {', 1)[1].split('.tag-filter-desktop-shell.tag-filter-desktop-shell--fullscreen {', 1)[0]
    top_tabs_section = source.split('.tag-filter-workspace-top-tabs {', 1)[1].split('.tag-filter-workspace-top-tabs-nav {', 1)[0]
    top_tabs_nav_section = source.split('.tag-filter-workspace-top-tabs-nav {', 1)[1].split('.tag-filter-workspace-top-tab {', 1)[0]
    workbench_section = source.split('.tag-filter-desktop-workbench {', 1)[1].split('.tag-filter-desktop-main {', 1)[0]
    center_section = source.split('.tag-filter-workspace-center {', 1)[1].split('.tag-filter-current-mode-tool-area {', 1)[0]
    tool_area_section = source.split('.tag-filter-current-mode-tool-area {', 1)[1].split('.tag-filter-current-mode-tool-panel {', 1)[0]
    tool_panel_section = source.split('.tag-filter-current-mode-tool-panel {', 1)[1].split('.tag-filter-current-mode-tool-panel--delete {', 1)[0]

    assert 'gap: 0.5rem;' in desktop_shell_section
    assert 'padding: 0.1rem 0 0.1rem;' in top_tabs_section
    assert 'display: block;' in top_tabs_section
    assert 'display: inline-flex;' in top_tabs_nav_section
    assert 'gap: 0;' in workbench_section
    assert 'display: flex;' in center_section
    assert 'flex-direction: column;' in center_section
    assert 'align-self: stretch;' in tool_area_section
    assert 'border: 1px solid var(--border-light);' not in tool_area_section
    assert 'background: color-mix(in srgb, var(--bg-sub), transparent 26%);' not in tool_area_section
    assert 'height: 100%;' not in tool_area_section
    assert 'border-radius: 0.75rem;' in tool_panel_section


def test_workspace_center_css_does_not_duplicate_two_column_layout_contract():
    source = read_project_file('static/css/modules/modal-tools.css')
    desktop_main_section = source.split('.tag-filter-desktop-main {', 1)[1].split('.tag-filter-workspace-center {', 1)[0]
    center_section = source.split('.tag-filter-workspace-center {', 1)[1].split('.tag-filter-current-mode-tool-area {', 1)[0]

    assert 'grid-template-columns: minmax(0, 1fr) minmax(20rem, 28rem);' in desktop_main_section
    assert 'grid-template-columns: minmax(0, 1fr) minmax(20rem, 28rem);' not in center_section
    assert 'display: flex;' in center_section
    assert 'width: 100%;' in center_section


def test_governance_drawer_css_has_independent_scroll_constraints():
    source = read_project_file('static/css/modules/modal-tools.css')
    drawer_section = source.split('.tag-filter-governance-drawer {', 1)[1].split('.tag-filter-governance-drawer.is-open {', 1)[0]

    assert 'max-height:' in drawer_section
    assert 'overflow-y: auto' in drawer_section


def test_top_tabs_css_polish():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-workspace-topbar-main {' in source
    assert '.tag-filter-workspace-topbar-status {' in source
    assert '.tag-filter-workspace-topbar-actions {' in source
    assert '.tag-filter-workspace-top-tabs {' in source
    assert '.tag-filter-workspace-top-tabs-nav {' in source
    assert '.tag-filter-workspace-top-tab {' in source
    assert '.tag-filter-workspace-top-tab.is-active {' in source
    assert '.tag-filter-workspace-top-tab--utility {' in source
    assert '.tag-filter-workspace-help {' in source
    assert '.tag-filter-workspace-help-layout {' in source
    assert '.tag-filter-workspace-help-nav {' in source
    assert '.tag-filter-workspace-help-nav-item {' in source
    assert '.tag-filter-workspace-help-nav-list {' in source
    assert '.tag-filter-workspace-help-grid {' in source
    assert '.tag-filter-workspace-help-card {' in source
    assert '.tag-filter-workspace-mode-nav {' not in source
    assert '.tag-filter-workspace-mode-item {' not in source
    assert '.tag-filter-workspace-mode-item--utility {' not in source


def test_workspace_help_surface_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    compact_template = compact_whitespace(template_source)

    assert '@click="toggleWorkspaceHelp()"' in template_source
    assert '> 帮助 </button>' in compact_template or '>帮助</button>' in compact_template
    assert 'class="tag-filter-workspace-help"' in template_source
    assert 'x-show="isWorkspaceHelpOpen"' in template_source
    assert 'class="tag-filter-workspace-help-layout"' in template_source
    assert 'class="tag-filter-workspace-help-nav"' in template_source
    assert 'class="tag-filter-workspace-help-nav-list custom-scrollbar"' in template_source
    assert '@click="jumpToWorkspaceHelpSection(section.id)"' in template_source
    assert 'data-workspace-help-section="overview"' in template_source
    assert 'data-workspace-help-section="separator-rules"' in template_source
    assert 'data-workspace-help-section="faq"' in template_source
    assert '标签工作台帮助页' in template_source
    assert '如何高效使用标签工作台' in template_source
    assert '工作台总览' in template_source
    assert '搜索与视图' in template_source
    assert '分隔符规则' in template_source
    assert '批量分类模式下的“批量选中”输入框也遵循这个规则' in template_source
    assert '筛选模式' in template_source
    assert '批量分类模式' in template_source
    assert '排序模式' in template_source
    assert '删除模式' in template_source
    assert '分类管理模式' in template_source
    assert '治理设置说明' in template_source
    assert '推荐工作流' in template_source
    assert '常见问题' in template_source
    assert 'overflow-y: auto;' in source.split('.tag-filter-workspace-help-nav-list {', 1)[1].split('.tag-filter-workspace-help-nav-item {', 1)[0]


def test_workspace_footer_exposes_category_quick_index_contract():
    template_source = read_project_file('templates/modals/tag_filter.html')
    footer_section = template_source.split('<div\n                class="tag-filter-workspace-footer"', 1)[1].split('<div\n                class="tag-filter-workspace-help"', 1)[0]

    assert 'x-for="name in footerCategoryIndexNames"' in footer_section
    assert '@click="applyFooterCategoryQuickFilter(name)"' in footer_section
    assert '快速查看分类' in footer_section
    assert '@click="saveSortMode()"' not in footer_section


def test_category_manager_registry_panel_uses_internal_scroll_instead_of_overflowing_contract():
    source = read_project_file('static/css/modules/modal-tools.css')

    panel_section = source.split('.tag-filter-current-mode-tool-panel--category-manager {', 1)[1].split('.tag-filter-current-mode-tool-panel--filter {', 1)[0]
    stack_section = source.split('.tag-filter-category-manager-stack {', 1)[1].split('.tag-filter-category-manager-stack-item {', 1)[0]
    registry_item_section = source.split('.tag-filter-category-manager-stack-item--registry {', 1)[1].split('.tag-filter-category-manager-registry-area {', 1)[0]
    registry_area_section = source.split('.tag-filter-category-manager-registry-area {', 1)[1].split('.tag-filter-category-manager-registry-list {', 1)[0]
    registry_list_section = source.split('.tag-filter-category-manager-registry-list {', 1)[1].split('.tag-filter-category-manager-registry-list', 1)[0]

    assert 'flex: 1;' in panel_section
    assert 'overflow: hidden;' in panel_section
    assert 'grid-template-rows: auto minmax(0, 1fr);' in stack_section
    assert 'display: flex;' in registry_item_section
    assert 'flex: 1;' in registry_area_section
    assert 'overflow: hidden;' in registry_area_section
    assert 'overflow-y: auto;' in registry_list_section


def test_selected_basket_css_polish():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    center_section = template_source.split('<div class="tag-filter-workspace-center">', 1)[1].split('<div class="tag-filter-workspace-tag-pool">', 1)[0]

    assert 'class="tag-filter-selected-basket tag-filter-selected-basket--workspace"' in center_section
    assert 'class="tag-filter-selected-basket-header tag-filter-selected-basket-header--calm"' in center_section
    assert 'class="tag-filter-selected-basket-list custom-scrollbar tag-filter-selected-basket-list--workspace"' in center_section
    assert 'class="tag-filter-selected-basket-chip tag-filter-selected-basket-chip--included tag-filter-selected-basket-chip--workspace"' in center_section
    assert 'class="tag-filter-selected-basket-chip tag-filter-selected-basket-chip--excluded tag-filter-selected-basket-chip--workspace"' in center_section
    assert 'class="tag-filter-selected-basket-empty"' in center_section
    assert '暂无标签' in center_section

    assert '.tag-filter-selected-basket--workspace {' in source
    assert '.tag-filter-selected-basket-header--calm {' in source
    assert '.tag-filter-selected-basket-list--workspace {' in source
    assert '.tag-filter-selected-basket-chip--workspace {' in source
    assert '.tag-filter-selected-basket-chip--workspace:hover {' in source
    assert '.tag-filter-selected-basket-chip--included.tag-filter-selected-basket-chip--workspace {' in source
    assert '.tag-filter-selected-basket-chip--excluded.tag-filter-selected-basket-chip--workspace {' in source
    assert '.tag-filter-selected-basket-empty {' in source


def test_category_filter_css_polish():
    template_source = read_project_file('templates/modals/tag_filter.html')
    source = read_project_file('static/css/modules/modal-tools.css')
    center_section = template_source.split('<div class="tag-filter-workspace-center">', 1)[1].split('<div class="tag-filter-workspace-tag-pool">', 1)[0]

    assert 'class="tag-category-filter-row tag-category-filter-row--workspace"' in center_section
    assert 'class="tag-category-filter-pill tag-category-filter-pill--workspace"' in center_section
    assert 'class="tag-category-filter-pill tag-category-filter-pill--workspace tag-category-filter-pill--all"' in center_section
    assert 'class="tag-category-filter-dot tag-category-filter-dot--workspace"' in center_section

    assert '.tag-category-filter-row--workspace {' in source
    assert '.tag-category-filter-pill--workspace {' in source
    assert '.tag-category-filter-pill--workspace:hover {' in source
    assert '.tag-category-filter-pill--workspace.active-mixed {' in source
    assert '.tag-category-filter-pill--workspace.active-included {' in source
    assert '.tag-category-filter-pill--workspace.active-excluded {' in source
    assert '.tag-category-filter-dot--workspace {' in source


def test_desktop_chip_state_css_polish():
    source = read_project_file('static/css/modules/modal-tools.css')

    assert '.tag-filter-desktop-main .tag-cloud-container {' in source
    assert '.tag-filter-desktop-main .tag-chip-btn {' in source
    assert '.tag-filter-desktop-main .tag-chip-btn:hover {' in source
    assert '.tag-filter-desktop-main .tag-chip-selected {' in source
    assert '.tag-filter-desktop-main .tag-chip-unselected {' in source
    assert '.tag-filter-desktop-main .tag-chip-excluded {' in source
    assert '.tag-filter-desktop-main .tag-chip-delete-selected {' in source
    assert '.tag-filter-desktop-main .tag-chip-delete-unselected {' in source
    assert '.tag-filter-desktop-main .tag-chip-categorized {' in source
    assert '.tag-filter-desktop-main .tag-chip-category-selected {' in source
    assert '.tag-filter-desktop-main .tag-chip-category-unselected {' in source
    assert 'border-radius: 0.85rem;' in source
    assert 'padding: 0.45rem 0.78rem;' in source
    assert 'background-color 0.16s ease,' in source
    assert 'border-color 0.16s ease,' in source
    assert 'color 0.16s ease,' in source
    assert 'box-shadow: none;' in source
