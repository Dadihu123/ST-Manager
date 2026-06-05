import re

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_js_function_block(source, signature):
    start = source.index(signature)
    brace_start = source.index('{', start)
    depth = 0

    for idx in range(brace_start, len(source)):
        char = source[idx]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:idx + 1]

    raise AssertionError(f'Could not extract JS block for {signature!r}')


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


def test_automation_modal_defines_shared_tag_splitter_contract_for_slash_separator_setting():
    source = read_project_file('static/js/components/automationModal.js')
    save_section = extract_js_function_block(source, 'saveCurrentRuleSet() {')

    assert 'splitTagTokens(' in source
    assert 'parseReplaceRulesText' in save_section
    assert 'splitTagTokens(' in save_section


def test_automation_modal_uses_local_id_helper_instead_of_crypto_random_uuid():
    source = read_project_file('static/js/components/automationModal.js')

    assert "import { createLocalId } from '../utils/data.js';" in source
    assert 'createLocalId(' in source
    assert 'crypto.randomUUID(' not in source


def test_data_utils_exposes_create_local_id_with_random_uuid_fallback():
    source = read_project_file('static/js/utils/data.js')

    assert 'export function createLocalId()' in source
    assert 'cryptoRef.randomUUID()' in source
    assert 'Date.now().toString(36)' in source


def test_automation_modal_trigger_contexts_contract_defaults_normalizes_and_persists():
    source = read_project_file('static/js/components/automationModal.js')
    select_section = extract_js_function_block(source, 'selectRuleSet(id) {')
    add_rule_section = extract_js_function_block(source, 'addRule() {')
    save_section = extract_js_function_block(source, 'saveCurrentRuleSet() {')
    normalize_section = extract_js_function_block(source, 'normalizeRuleTriggerContexts(rule) {')
    toggle_section = extract_js_function_block(source, 'toggleRuleTrigger(rule, trigger) {')
    has_trigger_section = extract_js_function_block(source, 'ruleHasTrigger(rule, trigger) {')

    assert 'normalizeRuleTriggerContexts(rule) {' in source
    assert 'deriveLegacyRuleTriggerContexts(rule)' in source
    assert 'DEFAULT_RULE_TRIGGER_CONTEXTS' in source
    assert "['manual_run', 'auto_import']" in source
    assert 'SUPPORTED_RULE_TRIGGER_CONTEXTS' in source
    assert "'manual_run'" in source
    assert "'auto_import'" in source
    assert "'card_update'" in source
    assert "'link_update'" in source
    assert "'tag_edit'" in source
    assert 'Array.isArray(rule?.trigger_contexts) ? rule.trigger_contexts : null' in normalize_section
    assert 'trigger_contexts.filter' in normalize_section
    assert 'deriveLegacyRuleTriggerContexts(rule)' in normalize_section
    assert 'SUPPORTED_RULE_TRIGGER_CONTEXTS.includes(trigger)' in normalize_section
    assert 'normalized.includes(trigger)' in normalize_section
    assert 'return normalized.length ? normalized : deriveLegacyRuleTriggerContexts(rule);' in normalize_section
    assert "action.type === 'fetch_forum_tags'" in source
    assert "action.type === 'merge_tags'" in source

    assert 'rule.trigger_contexts = this.normalizeRuleTriggerContexts(rule);' in select_section
    assert "trigger_contexts: ['manual_run', 'auto_import']" in add_rule_section
    assert 'rule.trigger_contexts = this.normalizeRuleTriggerContexts(rule);' in save_section

    assert 'toggleRuleTrigger(rule, trigger) {' in source
    assert 'this.normalizeRuleTriggerContexts(rule)' in toggle_section
    assert 'if (currentTriggers.length === 1 && currentTriggers[0] === normalizedTrigger) return;' in toggle_section
    assert 'rule.trigger_contexts = nextTriggers;' in toggle_section
    assert 'this.editingRules = [...this.editingRules];' in toggle_section

    assert 'ruleHasTrigger(rule, trigger) {' in source
    assert 'return this.normalizeRuleTriggerContexts(rule).includes(trigger);' in has_trigger_section


def test_automation_modal_split_category_tags_contract_uses_backend_exclude_segments_shape():
    source = read_project_file('static/js/components/automationModal.js')
    save_section = extract_js_function_block(source, 'saveCurrentRuleSet() {')

    assert 'function createSplitCategoryTagsConfig(value = {}) {' in source
    assert 'exclude_category_tags' in source
    assert 'value.exclude_segments' in source
    assert "join('|')" in source
    assert 'exclude_segments: splitTagTokens(config.exclude_category_tags' in save_section
    assert 'exclude_category_tags: config.exclude_category_tags' not in save_section


def test_state_defines_localstorage_backed_tag_view_pref_contracts():
    source = read_project_file('static/js/state.js')

    assert 'const TAG_VIEW_PREFS_STORAGE_KEY =' in source
    assert 'loadTagViewPrefs() {' in source
    assert 'saveTagViewPrefs(nextPrefs) {' in source
    assert 'localStorage.getItem(TAG_VIEW_PREFS_STORAGE_KEY)' in source
    assert_matches(r'localStorage\.setItem\(\s*TAG_VIEW_PREFS_STORAGE_KEY,', source)


def test_state_bootstrap_loads_tag_view_prefs_before_components_consume_them():
    source = read_project_file('static/js/state.js')

    assert 'tagViewPrefs:' in source
    assert 'mixedCategoryView: true' in source
    assert 'this.loadTagViewPrefs();' in source


def test_tag_filter_modal_uses_store_backed_tag_view_prefs_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'this.$store.global.loadTagViewPrefs()' in source
    assert 'this.$store.global.saveTagViewPrefs({' in source
    assert 'mixedCategoryView: this.mixedCategoryView' in source


def test_tag_filter_modal_reloads_tag_view_prefs_when_reopened_in_same_session():
    source = read_project_file('static/js/components/tagFilterModal.js')

    open_watch_section = source.split("if (val) {", 1)[1].split('return;', 1)[0]

    assert 'this.loadDesktopWorkbenchPrefs();' in open_watch_section
    assert_matches(
        r'window\.addEventListener\(["\']open-tag-filter-modal["\'],\s*\(\)\s*=>\s*\{[\s\S]*?this\.loadDesktopWorkbenchPrefs\(\);',
        source,
    )
    assert 'this.rememberLastTagView = tagViewPrefs.rememberLastTagView === true;' in source
    assert 'this.mixedCategoryView = this.rememberLastTagView' in source
    assert '? tagViewPrefs.mixedCategoryView !== false' in source


def test_tag_filter_modal_desktop_workbench_uses_shared_search_matcher_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    filtered_pool_section = extract_js_function_block(source, 'get filteredTagsPool() {')

    assert 'matchAnyTagSearchToken' in source
    assert 'automation_slash_is_tag_separator' in filtered_pool_section
    assert 'slashIsSeparator' in filtered_pool_section
    assert 'matchAnyTagSearchToken(t, query, { slashIsSeparator })' in filtered_pool_section


def test_tag_filter_modal_desktop_workbench_loads_and_saves_governance_prefs_via_api_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'getTagManagementPrefs' in source
    assert 'saveTagManagementPrefs' in source
    assert 'loadTagManagementPrefs() {' in source
    assert 'saveTagManagementPrefsState() {' in source
    assert "this.lockTagLibrary = prefs.lock_tag_library === true;" in source
    assert 'this.tagBlacklistTags = blacklist;' in source
    assert_contains_either(source, ["this.tagBlacklistInput = blacklist.join(', ');", 'this.tagBlacklistInput = blacklist.join(", ");'])


def test_tag_filter_modal_batch_category_supports_splitter_based_bulk_selection_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    template = read_project_file('templates/modals/tag_filter.html')
    apply_section = extract_js_function_block(source, 'applyCategorySelectionInput() {')

    assert_contains_either(source, ["categorySelectionInput: ''", 'categorySelectionInput: ""'])
    assert 'applyCategorySelectionInput() {' in source
    assert 'this.splitManualTagInput(this.categorySelectionInput)' in apply_section
    assert_matches(
        r'const\s+addedCount\s*=\s*this\.appendTokensToSelection\(\s*tokens\s*,\s*["\']selectedCategoryTags["\']\s*,?\s*\)',
        apply_section,
    )
    assert template.count('x-model="categorySelectionInput"') >= 2
    assert template.count('@click="applyCategorySelectionInput()"') >= 2


def test_tag_filter_modal_batch_category_save_allows_style_only_category_updates_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    save_section = extract_js_function_block(source, 'saveCategoryBatch() {')

    assert_contains_either(save_section, ['alert("请先填写分类名");', "alert('请先填写分类名');"])
    assert "alert('请先选择要设置分类的标签');" not in save_section
    assert 'const successMsg =' in save_section
    assert 'tags.length > 0' in save_section
    assert '已更新分类' in save_section


def test_tag_filter_modal_category_draft_style_sync_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    save_taxonomy_section = extract_js_function_block(source, 'saveTaxonomy(taxonomy, successMsg = "") {')

    assert 'this.categoryDraftColor = this.getCategoryColor(draftName);' in save_taxonomy_section
    assert 'this.categoryDraftOpacity = this.getCategoryOpacity(draftName);' in save_taxonomy_section


def test_tag_filter_modal_desktop_workbench_remember_last_tag_view_uses_store_helpers_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'rememberLastTagView: false' in source
    assert 'loadDesktopWorkbenchPrefs() {' in source
    assert 'saveDesktopWorkbenchPrefs() {' in source
    assert 'this.rememberLastTagView = tagViewPrefs.rememberLastTagView === true;' in source
    assert 'rememberLastTagView: this.rememberLastTagView' in source
    assert 'mixedCategoryView: this.mixedCategoryView' in source
    assert 'categoryFilterInclude: this.categoryFilterInclude' in source
    assert 'categoryFilterExclude: this.categoryFilterExclude' in source


def test_state_tag_view_prefs_contract_includes_category_filter_and_last_category_fields():
    source = read_project_file('static/js/state.js')

    assert 'categoryFilterInclude: []' in source
    assert 'categoryFilterExclude: []' in source
    assert_contains_either(source, ["lastCategorySortName: ''", 'lastCategorySortName: ""'])


def test_tag_filter_modal_governance_blacklist_uses_literal_selection_flow():
    source = read_project_file('static/js/components/tagFilterModal.js')
    split_section = compact_whitespace(
        extract_js_function_block(source, 'splitManualTagInput(rawValue) {')
    )
    apply_section = extract_js_function_block(source, 'applyBlacklistSelectionInput() {')

    assert 'splitTagTokens(' in source
    assert 'automation_slash_is_tag_separator' in split_section
    assert 'splitTagTokens(rawValue' in split_section
    assert 'slashIsSeparator' in split_section
    assert 'appendTokensToBlacklistSelection(tokens)' in apply_section
    assert "appendTokensToSelection(tokens, 'selectedBlacklistTags')" not in apply_section


def test_tag_filter_modal_delete_mode_can_add_selected_tags_to_blacklist_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    action_section = extract_js_function_block(source, 'addDeleteSelectionToBlacklist() {')

    assert 'addDeleteSelectionToBlacklist() {' in source
    assert 'this.selectedTagsForDeletion.length === 0' in action_section
    assert 'this.mergeTagsIntoBlacklist(this.selectedTagsForDeletion, {' in action_section
    assert 'clearDeleteSelectionOnSuccess: true' in action_section


def test_tag_filter_modal_blacklist_mode_supports_click_and_splitter_selection_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    template = read_project_file('templates/modals/tag_filter.html')
    toggle_section = extract_js_function_block(source, 'toggleTagSelectionForBlacklist(tag) {')
    save_section = extract_js_function_block(source, 'saveBlacklistSelection() {')

    assert "selectedBlacklistTags: []" in source
    assert 'blacklistSelectionInput: ""' in source
    assert "get isBlacklistMode() {" in source
    assert 'toggleTagSelectionForBlacklist(tag) {' in source
    assert 'this.selectedBlacklistTags.push(name);' in toggle_section
    assert 'saveBlacklistSelection() {' in source
    assert 'return this.mergeTagsIntoBlacklist(this.selectedBlacklistTags, {' in save_section
    assert 'clearBlacklistSelectionOnSuccess: true' in save_section
    assert 'clearBlacklistInputOnSuccess: true' in save_section
    assert '@click="desktopWorkspaceMode === \'blacklist\' ? setDesktopWorkspaceMode(\'filter\') : setDesktopWorkspaceMode(\'blacklist\')"' in template
    assert 'x-model="blacklistSelectionInput"' in template
    assert '@click="applyBlacklistSelectionInput()"' in template
    assert '@click="saveBlacklistSelection()"' in template
    assert '待加入黑名单' in template


def test_governance_drawer_js_defines_desktop_state_and_toggle_hooks():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'isGovernanceDrawerOpen: false' in source
    assert 'toggleGovernanceDrawer() {' in source
    assert 'closeGovernanceDrawer() {' in source
    assert 'this.isGovernanceDrawerOpen = !this.isGovernanceDrawerOpen;' in source
    assert 'this.isGovernanceDrawerOpen = false;' in source


def test_governance_drawer_js_closes_when_desktop_mode_changes_or_modal_resets():
    source = read_project_file('static/js/components/tagFilterModal.js')
    sync_section = extract_js_function_block(source, 'syncDesktopWorkspaceMode(mode) {')
    reset_section = extract_js_function_block(source, 'resetModalStateAfterClose() {')

    assert 'this.closeGovernanceDrawer();' in sync_section
    assert 'this.closeGovernanceDrawer();' in reset_section


def test_workspace_help_js_defines_toggle_and_reset_hooks():
    source = read_project_file('static/js/components/tagFilterModal.js')
    sync_section = extract_js_function_block(source, 'syncDesktopWorkspaceMode(mode) {')
    reset_section = extract_js_function_block(source, 'resetModalStateAfterClose() {')

    assert 'isWorkspaceHelpOpen: false' in source
    assert 'toggleWorkspaceHelp() {' in source
    assert 'closeWorkspaceHelp() {' in source
    assert 'this.isWorkspaceHelpOpen = !this.isWorkspaceHelpOpen;' in source
    assert 'this.closeWorkspaceHelp();' in sync_section
    assert 'this.closeWorkspaceHelp();' in reset_section


def test_workspace_help_js_defines_directory_sections_and_jump_helper():
    source = read_project_file('static/js/components/tagFilterModal.js')
    jump_section = extract_js_function_block(source, 'jumpToWorkspaceHelpSection(sectionId) {')

    assert 'workspaceHelpSections: [' in source
    assert_contains_either(source, ["activeWorkspaceHelpSection: 'overview'", 'activeWorkspaceHelpSection: "overview"'])
    assert_contains_either(source, [
        "{ id: 'separator-rules', label: '分隔符规则' }",
        '{ id: "separator-rules", label: "分隔符规则" }',
    ])
    assert 'jumpToWorkspaceHelpSection(sectionId) {' in source
    assert 'this.activeWorkspaceHelpSection = nextId;' in jump_section
    assert 'data-workspace-help-section' in jump_section
    assert 'scrollIntoView' in jump_section


def test_explicit_mode_state_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert_contains_either(source, ["desktopWorkspaceMode: 'filter'", 'desktopWorkspaceMode: "filter"'])
    assert 'setDesktopWorkspaceMode(mode) {' in source
    assert 'syncDesktopWorkspaceMode(mode) {' in source
    assert_matches(
        r'!\[\s*["\']filter["\']\s*,\s*["\']batch-category["\']\s*,\s*["\']sort["\']\s*,\s*["\']delete["\']\s*,\s*["\']blacklist["\']\s*,\s*["\']category-manager["\']\s*,?\s*\]\.includes\(mode\)',
        source,
    )
    assert 'const changed = this.syncDesktopWorkspaceMode(mode);' in source
    assert 'if (changed === false) return false;' in source
    assert 'this.desktopWorkspaceMode = mode;' in source
    assert 'return true;' in source
    assert_contains_either(source, ["this.desktopWorkspaceMode = 'filter';", 'this.desktopWorkspaceMode = "filter";'])


def test_desktop_workspace_separates_batch_category_and_category_manager_modes_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert_contains_either(source, ["if (mode === 'batch-category') {", 'if (mode === "batch-category") {'])
    assert_contains_either(source, ["if (mode === 'blacklist') {", 'if (mode === "blacklist") {'])
    assert_contains_either(source, ["if (mode === 'category-manager') {", 'if (mode === "category-manager") {'])
    assert "this.showCategoryMode = true;" in source
    assert "this.showCategoryManager = true;" in source
    assert "this.showCategoryMode = false;" in source
    assert "this.showCategoryManager = false;" in source


def test_tag_filter_modal_desktop_workspace_fullscreen_toggle_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')

    assert 'isDesktopWorkspaceFullscreen: false' in source
    assert 'toggleDesktopWorkspaceFullscreen() {' in source
    assert 'requestFullscreen' in source
    assert 'exitFullscreen' in source
    assert_matches(
        r'document\.addEventListener\(\s*["\']fullscreenchange["\'],\s*this\._handleDesktopFullscreenChange,\s*\)',
        source,
    )
    assert 'this.isDesktopWorkspaceFullscreen = false;' in source


def test_tag_filter_modal_grouped_view_toggle_no_longer_resets_during_pref_save_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    save_section = extract_js_function_block(source, 'saveDesktopWorkbenchPrefs() {')

    assert 'mixedCategoryView: this.mixedCategoryView' in save_section
    assert 'this.mixedCategoryView = true;' not in save_section


def test_tag_filter_modal_filter_category_names_follow_taxonomy_categories_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    filter_names_section = extract_js_function_block(source, 'get filterCategoryNames() {')

    assert 'return this.availableCategoryNames;' in filter_names_section
    assert 'this.baseTagGroups' not in filter_names_section


def test_tag_filter_modal_desktop_sort_mode_supports_grouped_drag_sort_contract():
    source = read_project_file('static/js/components/tagFilterModal.js')
    template = read_project_file('templates/modals/tag_filter.html')

    assert 'sortWorkingCategoryOrder: []' in source
    assert 'sortWorkingCategoryTagOrder: {}' in source
    assert 'get sortModeTagGroups() {' in source
    assert 'get sortModeMixedTagsPool() {' in source
    assert 'get sortModeVisibleTagCount() {' in source
    assert 'getSortCategoryTags(categoryName) {' in source
    assert 'buildTagGroups(tags, categoryOrder = []) {' in source
    assert 'onSortCategoryDragStart(event, categoryName) {' in source
    assert 'onSortCategoryDragOver(event, categoryName) {' in source
    assert 'onSortCategoryDrop(event, targetCategoryName) {' in source
    assert 'onSortCategoryDragEnd() {' in source
    assert 'category_tag_order' in source
    assert 'saveTagTaxonomy({ taxonomy })' in source
    assert 'x-for="group in sortModeTagGroups"' in template
    assert '@dragstart="onSortCategoryDragStart($event, group.category)"' in template
    assert '@drop="onSortCategoryDrop($event, group.category)"' in template
    assert '@dragstart="onSortDragStart($event, tag)"' in template


def test_batch_tag_modal_manual_inputs_use_shared_splitter_without_search_matching_contract():
    source = read_project_file('static/js/components/batchTagModal.js')
    add_section = extract_js_function_block(source, 'batchAddTag(tag) {')
    remove_section = extract_js_function_block(source, 'batchRemoveTag(tag) {')

    assert 'splitTagTokens(' in source
    assert 'splitTagTokens(' in add_section
    assert 'splitTagTokens(' in remove_section
    assert 'matchAnyTagSearchToken(' not in add_section
    assert 'matchAnyTagSearchToken(' not in remove_section


def test_detail_modal_manual_add_input_uses_shared_splitter_without_search_semantics_contract():
    source = read_project_file('static/js/components/detailModal.js')
    add_section = extract_js_function_block(source, 'addTag() {')

    assert 'splitTagTokens(' in source
    assert 'splitTagTokens(' in add_section
    assert 'matchAnyTagSearchToken(' not in add_section
    assert 'splitPattern' not in add_section


def test_templates_keep_manual_tag_inputs_distinct_from_search_inputs_contract():
    batch_template = read_project_file('templates/modals/batch_tag.html')
    detail_template = read_project_file('templates/modals/detail_card.html')

    assert 'x-model="batchTagInputAdd"' in batch_template
    assert 'x-model="batchTagInputRemove"' in batch_template
    assert 'x-model="batchTagPickerSearch"' in batch_template
    assert 'placeholder="搜索标签（支持多个关键词，逗号/竖线分隔）…"' in batch_template
    assert 'x-model="batchTagPickerSearch"' in batch_template
    assert 'placeholder="输入标签…"' in batch_template
    assert batch_template.count('placeholder="输入标签…"') == 2
    assert 'placeholder="搜索标签库（支持多个关键词，逗号/竖线分隔）..."' in detail_template
    assert 'x-model="newTagInput"' in detail_template
    assert ':placeholder="$store.global.settingsForm.automation_slash_is_tag_separator ? ' in detail_template
    assert ':title="$store.global.settingsForm.automation_slash_is_tag_separator ? ' in detail_template


def test_batch_tag_modal_uses_shared_search_matcher_and_copy_contract():
    template = read_project_file('templates/modals/batch_tag.html')
    source = read_project_file('static/js/components/batchTagModal.js')
    filtered_pool_section = extract_js_function_block(source, 'get filteredBatchTagPool() {')

    assert "import { matchAnyTagSearchToken, splitTagTokens } from '../state.js';" in source
    assert 'matchAnyTagSearchToken(t, query' in filtered_pool_section
    assert 'placeholder="搜索标签（支持多个关键词，逗号/竖线分隔）…"' in template


def test_batch_tag_modal_template_contract_keeps_wider_room_without_desktop_workbench_ui():
    template = read_project_file('templates/modals/batch_tag.html')

    assert 'batch-tag-modal-shell' in template
    assert 'tag-filter-desktop-workbench' not in template
    assert 'tag-category-manager-panel' not in template
    assert 'sort' not in template.lower()


def test_batch_tag_modal_uses_shared_tag_view_prefs_on_open_and_updates_contract():
    source = read_project_file('static/js/components/batchTagModal.js')
    init_section = extract_js_function_block(source, 'init() {')

    assert 'loadTagViewPrefs() {' in source
    assert 'saveTagViewPrefs() {' in source
    assert 'this.$store.global.loadTagViewPrefs()' in source
    assert 'this.$store.global.saveTagViewPrefs({' in source
    assert 'mixedCategoryView: this.mixedCategoryView' in source
    assert 'categoryFilterInclude: this.batchCategoryFilterInclude' in source
    assert 'categoryFilterExclude: this.batchCategoryFilterExclude' in source
    assert 'this.loadTagViewPrefs();' in init_section
    assert 'this.batchCategoryFilterInclude = [];' not in init_section
    assert 'this.batchCategoryFilterExclude = [];' not in init_section
    assert 'this.mixedCategoryView = true;' not in init_section
    assert 'this.saveTagViewPrefs();' in source


def test_batch_tag_modal_honors_remember_last_tag_view_false_on_open_contract():
    source = read_project_file('static/js/components/batchTagModal.js')

    assert 'const rememberLastTagView = tagViewPrefs.rememberLastTagView === true;' in source
    assert 'this.mixedCategoryView = rememberLastTagView' in source
    assert '? [...tagViewPrefs.categoryFilterInclude]' in source
    assert ': [];' in source
    assert '? [...tagViewPrefs.categoryFilterExclude]' in source


def test_detail_tag_library_uses_shared_search_matcher_and_view_prefs_contract():
    template = read_project_file('templates/modals/detail_card.html')
    source = read_project_file('static/js/components/detailModal.js')
    filtered_pool_section = extract_js_function_block(source, 'get filteredTagLibraryPool() {')
    open_picker_section = extract_js_function_block(source, 'openTagPicker() {')

    assert "import { matchAnyTagSearchToken, splitTagTokens } from '../state.js';" in source
    assert 'matchAnyTagSearchToken(tag, query' in filtered_pool_section
    assert 'loadTagViewPrefs() {' in source
    assert 'saveTagViewPrefs() {' in source
    assert 'this.$store.global.loadTagViewPrefs()' in source
    assert 'this.$store.global.saveTagViewPrefs({' in source
    assert 'this.loadTagViewPrefs();' in open_picker_section
    assert 'placeholder="搜索标签库（支持多个关键词，逗号/竖线分隔）..."' in template
    assert "x-text=\"mixedCategoryView ? '切换分组显示' : '切换混合显示'\"" in template


def test_detail_tag_library_restores_shared_category_filter_view_prefs_on_open_contract():
    source = read_project_file('static/js/components/detailModal.js')
    open_detail_section = extract_js_function_block(source, 'openDetail(c) {')

    assert 'loadTagViewPrefs() {' in source
    assert 'categoryFilterInclude: this.detailCategoryFilterInclude' in source
    assert 'categoryFilterExclude: this.detailCategoryFilterExclude' in source
    assert 'this.detailCategoryFilterInclude = Array.isArray(tagViewPrefs.categoryFilterInclude)' in source
    assert 'this.detailCategoryFilterExclude = Array.isArray(tagViewPrefs.categoryFilterExclude)' in source
    assert 'this.loadTagViewPrefs();' in open_detail_section
    assert 'this.detailCategoryFilterInclude = [];' not in open_detail_section
    assert 'this.detailCategoryFilterExclude = [];' not in open_detail_section


def test_detail_tag_library_honors_remember_last_tag_view_false_on_open_contract():
    source = read_project_file('static/js/components/detailModal.js')

    assert 'const rememberLastTagView = tagViewPrefs.rememberLastTagView === true;' in source
    assert 'this.mixedCategoryView = rememberLastTagView' in source
    assert '? [...tagViewPrefs.categoryFilterInclude]' in source
    assert '? [...tagViewPrefs.categoryFilterExclude]' in source
    assert ': [];' in source


def test_detail_tag_library_uses_shared_view_prefs_without_live_store_sync_contract():
    source = read_project_file('static/js/components/detailModal.js')

    assert 'loadTagViewPrefs() {' in source
    assert 'saveTagViewPrefs() {' in source
    assert 'this.$store.global.loadTagViewPrefs()' in source
    assert 'this.$store.global.saveTagViewPrefs({' in source
    assert "$watch('$store.global.tagViewPrefs.mixedCategoryView'" not in source


def test_detail_tag_library_stays_lightweight_without_desktop_workbench_or_ordering_contract():
    template = read_project_file('templates/modals/detail_card.html')
    source = read_project_file('static/js/components/detailModal.js')

    assert 'tag-filter-desktop-workbench' not in template
    assert 'categoryManager' not in source
    assert 'isSortMode' not in source
    assert 'saveTagOrder' not in source
