import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def compact_whitespace(value):
    return ' '.join(value.split())


def test_header_template_replaces_card_inline_filters_with_advanced_filter_button():
    header_template = read_project_file('templates/components/header.html')

    assert 'class="header-advanced-filter-btn"' in header_template
    assert '@click="openCardAdvancedFilter()"' in header_template
    assert 'x-text="cardAdvancedFilterCount"' in header_template
    assert 'class="search-scope-inline"' not in header_template
    assert 'class="search-sort-group"' not in header_template


def test_header_js_exposes_drawer_opener_and_limits_favorite_button_to_chats():
    header_source = read_project_file('static/js/components/header.js')

    assert 'get cardAdvancedFilterCount() {' in header_source
    assert 'openCardAdvancedFilter() {' in header_source
    assert 'return this.currentMode === "chats";' in header_source
    assert 'vs.allDirsOnlyWithFilters === true && vs.recursiveFilter !== false' in header_source
    assert 'recursive: vs.recursiveFilter !== false' in header_source


def test_index_template_includes_card_advanced_filter_drawer_and_app_registers_component():
    index_template = read_project_file('templates/index.html')
    app_source = read_project_file('static/js/app.js')

    assert 'modals/card_advanced_filter.html' in index_template
    assert 'import cardAdvancedFilter from "./components/cardAdvancedFilter.js";' in app_source
    assert 'Alpine.data("cardAdvancedFilter", cardAdvancedFilter);' in app_source


def test_state_js_defines_advanced_filter_applied_state_draft_and_summary_helpers():
    state_source = read_project_file('static/js/state.js')

    assert 'importDateFrom: ""' in state_source
    assert 'importDateTo: ""' in state_source
    assert 'modifiedDateFrom: ""' in state_source
    assert 'modifiedDateTo: ""' in state_source
    assert 'tokenMin: ""' in state_source
    assert 'tokenMax: ""' in state_source
    assert 'showCardAdvancedFilterDrawer: false,' in state_source
    assert 'cardAdvancedFilterDraft: null,' in state_source
    assert 'openCardAdvancedFilterDrawer(section = "") {' in state_source
    assert 'applyCardAdvancedFilterDraft() {' in state_source
    assert 'getCardAdvancedFilterSummaryItems() {' in state_source
    assert 'clearAllCardAdvancedFilters() {' in state_source
    assert 'allDirsOnlyWithFilters: false' in state_source
    assert 'viewState.recursiveFilter !== false' in state_source
    assert 'draft.recursiveFilter !== false' in state_source


def test_state_js_tracks_workbench_sections_validation_and_stats():
    state_source = read_project_file('static/js/state.js')
    compact = compact_whitespace(state_source)

    assert 'cardAdvancedFilterActiveSection: "basic"' in compact
    assert 'cardAdvancedFilterValidationState: buildDefaultCardAdvancedFilterValidationState()' in compact
    assert 'return { section: "", field: "", message: ""' in compact
    assert 'openCardAdvancedFilterDrawer(section = "") {' in state_source
    assert 'setCardAdvancedFilterSection(section = "") {' in state_source
    assert 'return nextSection;' in compact
    assert 'clearCardAdvancedFilterValidationState() {' in state_source
    assert 'getCardAdvancedFilterStatItems() {' in state_source
    assert 'label: "已启用条件"' in compact
    assert 'label: "时间范围"' in compact
    assert 'label: "数值 / 标签"' in compact
    assert 'value: String(this.getCardAdvancedFilterCount())' in compact
    assert 'section: "basic"' in compact
    assert 'section: "time"' in compact
    assert 'section: "numeric"' in compact
    assert 'section: "tags"' in compact
    assert re.search(
        r'const\s+numericAndTagSection\s*=\s*hasNumericRange\s*\?\s*"numeric"\s*:\s*"tags"\s*;',
        state_source,
    )
    assert 'section: numericAndTagSection' in compact
    assert 'cardAdvancedFilterTagEditSource: ""' in compact
    assert 'getCardAdvancedFilterTagState() {' in state_source
    assert 'isCardAdvancedFilterTagEditActive() {' in state_source
    assert 'setCardAdvancedFilterTagEditSource(source = "") {' in state_source
    assert 'syncCardAdvancedFilterValidationState() {' in state_source


def test_card_grid_source_sends_advanced_filter_params_and_debounces_filter_watches():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')

    assert '"$store.global.viewState.importDateFrom"' in card_grid_source
    assert '"$store.global.viewState.modifiedDateTo"' in card_grid_source
    assert '"$store.global.viewState.tokenMax"' in card_grid_source
    assert 'import_date_from: vs.importDateFrom || ""' in card_grid_source
    assert 'modified_date_to: vs.modifiedDateTo || ""' in card_grid_source
    assert 'token_min: vs.tokenMin === "" ? "" : String(vs.tokenMin)' in card_grid_source
    assert 'token_max: vs.tokenMax === "" ? "" : String(vs.tokenMax)' in card_grid_source
    assert '"$store.global.viewState.allDirsOnlyWithFilters"' in card_grid_source
    assert 'vs.allDirsOnlyWithFilters === true && vs.recursiveFilter !== false' in card_grid_source
    assert 'this.scheduleFetchCards("filters");' in card_grid_source


def test_grid_cards_template_renders_filter_summary_bar():
    grid_template = read_project_file('templates/components/grid_cards.html')

    assert 'class="card-filter-summary-bar"' in grid_template
    assert 'x-for="item in $store.global.getCardAdvancedFilterSummaryItems()"' in grid_template
    assert '@click="$store.global.clearAllCardAdvancedFilters()"' in grid_template
    assert '@click.stop="$store.global.clearCardAdvancedFilterItem(item.key)"' in grid_template


def test_header_and_summary_bar_render_workbench_status_and_section_targeting():
    header_template = read_project_file('templates/components/header.html')
    grid_template = read_project_file('templates/components/grid_cards.html')

    assert 'class="mobile-advanced-filter-entry-status"' in header_template
    assert '`已启用 ${cardAdvancedFilterCount} 项条件`' in header_template
    assert '已启用 ${cardAdvancedFilterCount} 个筛选条件，打开高级筛选' in header_template
    assert header_template.count('当前无附加条件') == 1
    assert 'class="card-filter-summary-chip-main"' in grid_template
    assert 'class="card-filter-summary-chip-remove"' in grid_template
    assert '@click="$store.global.openCardAdvancedFilterDrawer(item.section)"' in grid_template


def test_card_advanced_filter_template_exposes_sections_and_footer_actions():
    drawer_template = read_project_file('templates/modals/card_advanced_filter.html')
    drawer_component = read_project_file('static/js/components/cardAdvancedFilter.js')
    compact = compact_whitespace(drawer_template)

    assert 'x-data="cardAdvancedFilter"' in drawer_template
    assert 'class="card-advanced-filter-drawer"' in drawer_template
    assert '>基础筛选<' in compact
    assert '>时间筛选<' in compact
    assert '>数值筛选<' in compact
    assert '>标签条件<' in compact
    assert '@click="clearDraft()"' in drawer_template
    assert '@click="applyFilters()"' in drawer_template
    assert '@click="openTagFilterEditor()"' in drawer_template
    assert 'x-text="tagSummary"' in drawer_template
    assert '{% from "components/icon.html" import icon, detail_icon %}' in drawer_template
    assert drawer_template.count("detail_icon('tags', 'ui-icon--sm')") == 2
    assert "icon('palette'" not in drawer_template
    assert 'get tagSummary() {' in drawer_component
    assert 'x-show="draft.searchScope === \'all_dirs\' && draft.recursiveFilter"' in drawer_template
    assert 'x-model="draft.allDirsOnlyWithFilters"' in drawer_template
    assert '仅在有筛选条件时搜索全部目录' in drawer_template
    assert '@change="handleRecursiveFilterChange($event)"' in drawer_template
    assert 'handleRecursiveFilterChange(event) {' in drawer_component


def test_card_advanced_filter_numeric_inputs_use_shared_stepper_contract():
    drawer_template = read_project_file('templates/modals/card_advanced_filter.html')

    assert drawer_template.count('type="number"') == 2
    assert drawer_template.count('class="ui-number-control"') == 2
    assert drawer_template.count('class="ui-number-stepper"') == 2
    assert drawer_template.count('class="ui-number-input"') == 2
    assert drawer_template.count('min="0"') == 2
    assert drawer_template.count('step="1"') == 2
    assert drawer_template.count("icon('arrow-up', 'ui-icon--xs')") == 2
    assert drawer_template.count("icon('arrow-down', 'ui-icon--xs')") == 2
    assert 'window.stepNumberInput($event.currentTarget, 1)' in drawer_template
    assert 'window.stepNumberInput($event.currentTarget, -1)' in drawer_template


def test_card_advanced_filter_component_exposes_section_navigation_and_inline_validation():
    drawer_component = read_project_file('static/js/components/cardAdvancedFilter.js')
    state_source = read_project_file('static/js/state.js')
    drawer_template = read_project_file('templates/modals/card_advanced_filter.html')

    assert 'get activeSection() {' in drawer_component
    assert 'get validationMessage() {' in drawer_component
    assert 'get statItems() {' in drawer_component
    assert 'get sectionItems() {' in drawer_component
    assert 'setSection(section) {' in drawer_component
    assert 'isSectionActive(section) {' in drawer_component
    assert 'alert(result.error);' not in drawer_component
    assert 'this.$store.global.cardAdvancedFilterDraft =' not in drawer_component
    assert 'clearCardAdvancedFilterValidationState();' in state_source
    assert 'syncValidationState() {' in drawer_component
    assert 'this.$store.global.syncCardAdvancedFilterValidationState();' in drawer_component
    assert '@input="syncValidationState()"' in drawer_template
    assert '@change="syncValidationState()"' in drawer_template
    assert 'sort: "",' not in state_source


def test_tag_filter_modal_and_drawer_keep_tags_live_and_only_use_return_context_from_workbench():
    state_source = read_project_file('static/js/state.js')
    drawer_component = read_project_file('static/js/components/cardAdvancedFilter.js')
    tag_modal_source = read_project_file('static/js/components/tagFilterModal.js')
    tag_modal_template = read_project_file('templates/modals/tag_filter.html')
    clear_draft_block = state_source.split('clearCardAdvancedFilterDraft() {', 1)[1].split('validateCardAdvancedFilterDraft', 1)[0]

    assert 'filterTags: [...(viewState.filterTags || [])],' not in state_source
    assert 'excludedTags: [...(viewState.excludedTags || [])],' not in state_source
    assert 'this.viewState.filterTags = Array.isArray(draft.filterTags)' not in state_source
    assert 'this.viewState.excludedTags = Array.isArray(draft.excludedTags)' not in state_source
    assert 'getCardAdvancedFilterDraftTagState()' not in state_source
    assert 'return this.viewState;' in state_source
    assert 'this.setCardAdvancedFilterTagEditSource("card-advanced-filter");' in drawer_component
    assert 'getCardAdvancedFilterDraftTagState' not in drawer_component
    assert 'requestCloseTagFilterEditor()' in tag_modal_source
    assert 'this.$store.global.getCardAdvancedFilterTagState()' in tag_modal_source
    assert 'this.$store.global.openCardAdvancedFilterDrawer("tags")' in tag_modal_source
    assert 'this.$store.global.setCardAdvancedFilterTagEditSource("")' in tag_modal_source
    assert 'window.dispatchEvent(new CustomEvent("refresh-card-list"));' in state_source
    assert 'if (this.isCardAdvancedFilterTagEditActive()) {' in state_source
    assert 'return;' not in state_source.split('if (this.isCardAdvancedFilterTagEditActive()) {', 1)[1].split('// 触发列表刷新', 1)[0]
    assert 'this.viewState.filterTags = [];' not in clear_draft_block
    assert 'this.viewState.excludedTags = [];' not in clear_draft_block
    assert 'x-for="tag in excludedTags"' in tag_modal_template
    assert '@click.away="requestCloseTagFilterEditor()"' in tag_modal_template
    assert tag_modal_template.count('@click="requestCloseTagFilterEditor()"') >= 2
    assert '@click="requestCloseModal()"' not in tag_modal_template
    assert 'closeCardAdvancedFilterDrawer(false)' in drawer_component
    assert 'closeCardAdvancedFilterDrawer(clearTagEditSource = true) {' in state_source
    assert 'if (clearTagEditSource) {' in state_source


def test_card_advanced_filter_template_renders_workbench_overview_nav_and_error_banner():
    drawer_template = read_project_file('templates/modals/card_advanced_filter.html')
    compact = compact_whitespace(drawer_template)

    assert 'class="card-advanced-filter-overview"' in drawer_template
    assert 'class="card-advanced-filter-stat-grid"' in drawer_template
    assert 'class="card-advanced-filter-workbench"' in drawer_template
    assert 'class="card-advanced-filter-nav"' in drawer_template
    assert 'class="card-advanced-filter-error"' in drawer_template
    assert '@click="setSection(section.key)"' in drawer_template
    assert 'x-show="validationMessage"' in drawer_template
    assert "x-show=\"isSectionActive('basic')\"" in drawer_template
    assert "x-show=\"isSectionActive('time')\"" in drawer_template
    assert "x-show=\"isSectionActive('numeric')\"" in drawer_template
    assert "x-show=\"isSectionActive('tags')\"" in drawer_template
    assert '>当前筛选概览<' in compact


def test_mobile_menu_replaces_card_specific_filter_controls_with_advanced_filter_entry():
    header_template = read_project_file('templates/components/header.html')
    layout_css = read_project_file('static/css/modules/layout.css')
    mobile_menu = header_template.split('<!-- 移动端：展开菜单 -->', 1)[1]
    mobile_menu_css = layout_css.split('.mobile-menu {', 1)[1].split('}', 1)[0]

    assert '高级筛选' in mobile_menu
    assert '@click="openCardAdvancedFilter(); closeMobileMenu()"' in mobile_menu
    assert '搜索范围' not in mobile_menu
    assert '当前列表排序' not in mobile_menu
    assert '包含子目录' not in mobile_menu
    assert 'top: calc(100% + 1px);' in mobile_menu_css


def test_mobile_filter_and_random_entries_use_the_intended_icon_slots():
    header_template = read_project_file('templates/components/header.html')
    layout_css = read_project_file('static/css/modules/layout.css')

    assert "icon('filter', 'ui-icon--lg ')" in header_template
    assert "dice_icon('ui-icon--xl')" in header_template
    assert '.mobile-advanced-filter-entry-icon .ui-icon {' in layout_css
    mobile_override = layout_css.rsplit('.mobile-advanced-filter-entry-icon {', 1)[1].split(
        '}', 1
    )[0]
    assert 'border: 0;' in mobile_override
    assert '.mobile-advanced-filter-entry-desc {' in layout_css


def test_layout_css_styles_filter_button_summary_bar_and_drawer_shell():
    css_source = read_project_file('static/css/modules/layout.css')

    assert '.header-advanced-filter-btn {' in css_source
    assert '.card-filter-summary-bar {' in css_source
    assert '.card-filter-summary-chip {' in css_source
    assert '.card-advanced-filter-overlay {' in css_source
    assert '.card-advanced-filter-drawer {' in css_source
    assert '.mobile-advanced-filter-entry {' in css_source


def test_card_advanced_filter_component_does_not_auto_open_drawer_and_css_exposes_modal_backdrop():
    drawer_component = read_project_file('static/js/components/cardAdvancedFilter.js')
    drawer_template = read_project_file('templates/modals/card_advanced_filter.html')
    css_source = read_project_file('static/css/modules/layout.css')

    assert 'this.$store.global.openCardAdvancedFilterDrawer()' not in drawer_component
    assert 'this.$store.global.getDefaultCardAdvancedFilterDraft()' in drawer_component
    assert 'class="card-advanced-filter-backdrop"' in drawer_template
    assert '.card-advanced-filter-backdrop {' in css_source
    assert 'backdrop-filter: blur(' in css_source


def test_layout_css_styles_workbench_panels_summary_split_actions_and_mobile_state():
    css_source = read_project_file('static/css/modules/layout.css')

    assert '.header-advanced-filter-btn:focus-visible {' in css_source
    assert '.header-advanced-filter-count {' in css_source
    assert '.card-filter-summary-chip-main {' in css_source
    assert '.card-filter-summary-chip-remove {' in css_source
    assert '.card-advanced-filter-overview {' in css_source
    assert '.card-advanced-filter-stat-grid {' in css_source
    assert '.card-advanced-filter-workbench {' in css_source
    assert '.card-advanced-filter-nav {' in css_source
    assert '.card-advanced-filter-module-card {' in css_source
    assert '.card-advanced-filter-error {' in css_source
    assert '.mobile-advanced-filter-entry-status {' in css_source
    assert '@media (max-width: 900px)' in css_source
    assert '@media (max-width: 768px)' in css_source
    assert 'grid-template-columns: 1fr;' in css_source
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in css_source
    assert 'overflow-x: auto;' in css_source
