import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_balanced_tag_block(source, opening_tag):
    start = source.find(opening_tag)
    if start == -1:
        raise AssertionError(f'Opening tag not found: {opening_tag}')

    search_from = start
    depth = 0
    while search_from < len(source):
        next_open = source.find('<div', search_from)
        next_close = source.find('</div>', search_from)

        if next_close == -1:
            break

        if next_open != -1 and next_open < next_close:
            depth += 1
            search_from = next_open + 4
            continue

        depth -= 1
        search_from = next_close + len('</div>')
        if depth == 0:
            return source[start:search_from]

    raise AssertionError(f'Balanced block not found for: {opening_tag}')


def test_header_template_exposes_search_mode_and_index_status_contracts():
    header_template = read_project_file('templates/components/header.html')
    header_source = read_project_file('static/js/components/header.js')
    state_source = read_project_file('static/js/state.js')

    assert 'class="search-mode-toggle"' in header_template
    assert '@click=\'searchMode = "fast"\'' in header_template
    assert '@click=\'searchMode = "fulltext"\'' in header_template
    assert 'class="index-status-chip"' in header_template
    assert 'get searchMode() {' in header_source
    assert 'refreshIndexStatus() {' in header_source
    assert 'indexStatusPollTimer' in state_source
    assert 'startIndexStatusPolling() {' in header_source
    assert 'stopIndexStatusPolling() {' in header_source
    assert 'cardSearchMode: "fast",' in state_source
    assert 'wiSearchMode: "fast",' in state_source
    assert 'indexStatus: {' in state_source


def test_header_template_hides_index_status_chip_when_state_is_not_actionable():
    header_template = read_project_file('templates/components/header.html')

    assert (
        'x-show="$store.global.indexStatus.state === \'building\' || $store.global.indexStatus.state === \'error\'"'
        in header_template
    )
    assert 'x-text="indexStatusLabel"' in header_template


def test_header_source_maps_index_status_to_human_readable_labels():
    header_source = read_project_file('static/js/components/header.js')

    assert 'get indexStatusLabel() {' in header_source
    assert 'const state = String(this.$store.global.indexStatus?.state || "")' in header_source
    assert 'if (state === "building") return "索引构建中";' in header_source
    assert 'if (state === "error") return "索引异常";' in header_source


def test_grid_sources_propagate_search_mode_contracts():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')

    assert 'search_mode: store.cardSearchMode || "fast",' in card_grid_source
    assert 'this.$watch("$store.global.cardSearchMode", () => {' in card_grid_source
    assert 'search_mode: this.$store.global.wiSearchMode || "fast",' in wi_grid_source
    assert 'this.$watch("$store.global.wiSearchMode", () => {' in wi_grid_source


def test_header_source_gates_search_mode_and_handles_index_status_poll_failures():
    header_template = read_project_file('templates/components/header.html')
    header_source = read_project_file('static/js/components/header.js')
    state_source = read_project_file('static/js/state.js')

    assert 'get canUseFulltextSearch() {' in header_source
    assert "this.currentMode === 'worldinfo'" in header_source or 'this.currentMode === "worldinfo"' in header_source
    assert "this.$store.global.settingsForm.worldinfo_list_use_index" in header_source
    assert "this.$store.global.settingsForm.cards_list_use_index" in header_source
    assert "this.$store.global.settingsForm.fast_search_use_index" in header_source
    assert '.catch(() => {' in header_source
    assert 'this.$store.global.indexStatus = {' in header_source
    assert 'fast_search_use_index: false,' in state_source
    assert 'class="mobile-search-mode-toggle"' in header_template
    assert (
        'x-show="[\'cards\', \'worldinfo\'].includes(currentMode) && canUseFulltextSearch"'
        in header_template
    )


def test_header_source_forces_stale_fulltext_modes_back_to_fast():
    header_source = read_project_file('static/js/components/header.js')

    assert 'ensureSearchModeAllowed() {' in header_source
    assert (
        "if (this.searchMode !== 'fulltext' || this.canUseFulltextSearch) return;" in header_source
        or 'if (this.searchMode !== "fulltext" || this.canUseFulltextSearch) return;' in header_source
    )
    assert "this.searchMode = 'fast';" in header_source or 'this.searchMode = "fast";' in header_source
    assert 'this.ensureSearchModeAllowed();' in header_source


def test_header_template_exposes_beautify_search_contract():
    header_template = read_project_file('templates/components/header.html')
    header_source = read_project_file('static/js/components/header.js')

    assert "x-show=\"currentMode === 'beautify'\"" in header_template
    assert 'x-model.debounce.300ms="beautifySearch"' in header_template
    assert 'get beautifySearch() {' in header_source
    assert 'set beautifySearch(val) {' in header_source


def test_desktop_header_places_search_mode_toggle_inside_search_block_contract():
    header_template = read_project_file('templates/components/header.html')

    search_block_anchor = '<div class="header-search-block ml-auto">'
    search_container_anchor = 'search-container'
    search_mode_anchor = 'search-mode-toggle'
    advanced_filter_anchor = 'header-advanced-filter-btn'

    assert search_block_anchor in header_template
    search_block_markup = extract_balanced_tag_block(header_template, search_block_anchor)

    assert 'header-search-block' in search_block_markup
    assert search_container_anchor in search_block_markup
    assert search_mode_anchor in search_block_markup
    assert advanced_filter_anchor in search_block_markup
    assert (
        search_block_markup.index(search_container_anchor)
        < search_block_markup.index(advanced_filter_anchor)
        < search_block_markup.index(search_mode_anchor)
    )
    assert 'header-advanced-filter-btn-meta' not in search_block_markup
    assert 'class="header-search-icon"' in search_block_markup
    assert "icon('book-search', 'ui-icon--sm')" in search_block_markup
    assert "icon('filter', 'ui-icon--lg')" in search_block_markup
    assert ':aria-label=' in search_block_markup

    toggle_match = re.search(r'<[^>]*class="[^"]*\bsearch-mode-toggle\b[^"]*"[^>]*>', search_block_markup)
    assert toggle_match is not None

    toggle_tag = toggle_match.group(0)
    assert 'x-show=' in toggle_tag
    assert '.includes(currentMode)' in toggle_tag
    assert 'canUseFulltextSearch' in toggle_tag
    assert "'cards'" in toggle_tag or '"cards"' in toggle_tag
    assert "'worldinfo'" in toggle_tag or '"worldinfo"' in toggle_tag


def test_layout_css_defines_compact_desktop_search_mode_toggle_contract():
    layout_css = read_project_file('static/css/modules/layout.css')

    toggle_block = re.search(r'\.search-mode-toggle\s*\{([^}]*)\}', layout_css)
    button_block = re.search(r'\.search-mode-toggle button\s*\{([^}]*)\}', layout_css)
    active_button_block = re.search(r'\.search-mode-toggle button\.is-active\s*\{([^}]*)\}', layout_css)

    assert toggle_block is not None
    assert button_block is not None
    assert active_button_block is not None

    toggle_css = toggle_block.group(1)
    button_css = button_block.group(1)
    active_button_css = active_button_block.group(1)

    assert 'display: inline-flex;' in toggle_css
    assert 'flex-shrink: 0;' in toggle_css
    assert 'border-radius:' in toggle_css
    assert 'background:' in toggle_css or 'background-color:' in toggle_css

    assert 'height: 100%;' in button_css
    assert 'background: transparent;' in button_css
    assert 'cursor: pointer;' in button_css
    assert 'border-radius:' in button_css
    assert 'color: var(--content-muted);' in button_css

    assert 'background:' in active_button_css
    assert 'border-color: var(--action-border);' in active_button_css
    assert 'color: var(--action-text);' in active_button_css


def test_layout_css_flattens_header_search_type_and_focus_states():
    layout_css = read_project_file('static/css/modules/layout.css')

    search_shell_block = re.search(r'\.header-search-container\s*\{([^}]*)\}', layout_css)
    search_icon_block = re.search(r'\.header-search-icon\s*\{([^}]*)\}', layout_css)
    search_type_block = re.search(r'\.search-type-inline\s*\{([^}]*)\}', layout_css)
    search_trigger_block = re.search(r'\.search-type-select \.icon-select-trigger\s*\{([^}]*)\}', layout_css)

    assert search_shell_block is not None
    assert search_icon_block is not None
    assert search_type_block is not None
    assert search_trigger_block is not None

    assert 'height: 38px;' in search_shell_block.group(1)
    assert 'border-radius: 0.75rem;' in search_shell_block.group(1)
    assert 'border-right: 1px solid var(--border-subtle);' in search_icon_block.group(1)
    assert 'border-right: none;' in search_type_block.group(1)
    assert 'height: 2rem;' in search_trigger_block.group(1)
    assert 'border: 1px solid transparent;' in search_trigger_block.group(1)
    assert '.header-search-container .search-input:focus,' in layout_css
    assert 'box-shadow: none !important;' in layout_css


def test_card_grid_source_and_template_use_windowed_slice_contracts():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')
    grid_template = read_project_file('templates/components/grid_cards.html')
    windowing_source = read_project_file('static/js/utils/windowing.js')

    assert 'export function buildWindowedGridState(' in windowing_source
    assert 'get visibleCards() {' in card_grid_source
    assert 'syncCardWindowRange() {' in card_grid_source
    assert 'virtualTopSpacerStyle' in card_grid_source
    assert 'virtualBottomSpacerStyle' in card_grid_source
    assert 'x-for="card in visibleCards"' in grid_template
    assert 'class="card-grid-virtual-spacer card-grid-virtual-spacer--top"' in grid_template
    assert 'class="card-grid-virtual-spacer card-grid-virtual-spacer--bottom"' in grid_template


def test_card_grid_source_uses_rendered_grid_measurements_and_cleans_up_windowing_listeners():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')
    cards_css = read_project_file('static/css/modules/view-cards.css')

    assert 'window.getComputedStyle(grid).gridTemplateColumns' in card_grid_source
    assert 'grid.querySelector(".st-card")' in card_grid_source
    assert 'gridStyle.rowGap || gridStyle.gap' in card_grid_source
    assert 'destroy() {' in card_grid_source
    assert re.search(
        r'removeEventListener\(\s*["\']scroll["\'],\s*this\._syncCardWindowRangeHandler\s*,?\s*\)',
        card_grid_source,
    )
    assert re.search(
        r'window\.removeEventListener\(\s*["\']resize["\'],\s*this\._syncCardWindowRangeHandler\s*\)',
        card_grid_source,
    )
    assert 'grid-column: 1 / -1;' in cards_css


def test_card_grid_delete_success_path_resyncs_window_range_contract():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')

    assert re.search(
        r'this\.cards = this\.cards\.filter\(\(c\) => !deletedSet\.has\(c\.id\)\);'
        r'[\s\S]*?this\.\$nextTick\(\(\) => \{'
        r'[\s\S]*?this\.syncCardWindowRange\(\);',
        card_grid_source,
    )


def test_worldinfo_grid_source_and_template_use_abortable_windowed_contracts():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')
    grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'scheduleFetchWorldInfoList() {' in wi_grid_source
    assert 'this._fetchWorldInfoAbort = new AbortController();' in wi_grid_source
    assert 'get visibleWiItems() {' in wi_grid_source
    assert 'syncWiWindowRange() {' in wi_grid_source
    assert 'x-for="item in visibleWiItems"' in grid_template
    assert 'class="wi-grid-virtual-spacer wi-grid-virtual-spacer--top"' in grid_template


def test_worldinfo_grid_source_measures_rendered_layout_and_compensates_spacer_gap():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')
    wi_css = read_project_file('static/css/modules/view-wi.css')
    grid_template = read_project_file('templates/components/grid_wi.html')

    assert '_fetchWorldInfoAbort: new AbortController(),' in wi_grid_source
    assert 'window.getComputedStyle(grid).gridTemplateColumns' in wi_grid_source
    assert 'grid.querySelector(".wi-grid-card")' in wi_grid_source
    assert 'gridStyle.rowGap || gridStyle.gap' in wi_grid_source
    assert 'Math.max(0, this.windowRange.topPadding - this.wiGridGap)' in wi_grid_source
    assert 'Math.max(0, this.windowRange.bottomPadding - this.wiGridGap)' in wi_grid_source
    assert 'class="wi-grid-window grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4"' in grid_template
    assert 'grid-column: 1 / -1;' in wi_css


def test_worldinfo_grid_source_ignores_stale_abortable_request_callbacks():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')

    assert 'const requestController = this._fetchWorldInfoAbort;' in wi_grid_source
    assert 'if (this._fetchWorldInfoAbort !== requestController) return;' in wi_grid_source
    assert 'this._fetchWorldInfoAbort = null;' in wi_grid_source


def test_worldinfo_detail_popup_batches_toc_and_reader_entries():
    source = read_project_file('static/js/components/wiDetailPopup.js')
    template = read_project_file('templates/modals/detail_wi_popup.html')

    assert 'tocRenderLimit:' in source
    assert 'readerRenderLimit:' in source
    assert 'get visibleTocEntries() {' in source
    assert 'get visibleReaderEntries() {' in source
    assert 'runDetailSearch(query) {' in source
    assert 'x-for="(entry, idx) in visibleTocEntries"' in template
    assert 'x-for="(entry, idx) in visibleReaderEntries"' in template
    assert '@click="loadMoreReaderEntries()"' in template


def test_worldinfo_detail_popup_uses_backend_search_for_truncated_books():
    source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'const shouldUseBackendSearch =' in source
    assert 'this.isTruncated' in source
    assert 'this.totalEntries >= 500' in source
    assert 'if (!shouldUseBackendSearch) {' in source


def test_worldinfo_detail_popup_expands_reader_batch_before_toc_scroll():
    source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'const visibleIndex = (this.uiFilteredEntries || []).indexOf(entry);' in source
    assert 'if (visibleIndex >= this.readerRenderLimit) {' in source
    assert re.search(
        r'this\.readerRenderLimit\s*=\s*Math\.max\(\s*this\.readerRenderLimit,\s*visibleIndex\s*\+\s*1,?\s*\)',
        source,
    )


def test_worldinfo_detail_popup_load_more_controls_match_task4_contract():
    template = read_project_file('templates/modals/detail_wi_popup.html')

    assert 'class="wi-filter-chip mt-2 w-full"' in template
    assert '加载更多目录' in template
    assert 'class="wi-filter-chip mt-4 w-full"' in template
    assert '加载更多正文' in template


def test_worldinfo_detail_popup_loads_full_content_before_large_truncated_search():
    source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'async loadFullContent(options = {}) {' in source
    assert 'const rerunSearch = options.rerunSearch !== false;' in source
    assert 'await this.loadFullContent({ rerunSearch: false });' in source


def test_worldinfo_detail_popup_preserves_entry_id_zero_for_reader_dom_ids():
    template = read_project_file('templates/modals/detail_wi_popup.html')

    assert template.count(':key="entry.id ?? idx"') == 2
    assert ':key="entry.id || idx"' not in template
    assert ":id=\"'wi-reader-entry-' + (entry.id ?? ((entry.insertion_order ?? 'x') + '-' + idx))\"" in template
    assert ":class=\"{'active': activeEntry === entry,'toc-flash': highlightEntryKey !== null && highlightEntryKey !== undefined && (highlightEntryKey === (entry.id ?? ((entry.insertion_order ?? 'x') + '-' + idx)))}\"" in template
