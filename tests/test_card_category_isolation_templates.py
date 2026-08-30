from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_card_api_exposes_isolated_category_endpoints():
    source = read_project_file('static/js/api/card.js')

    assert 'export async function getIsolatedCategories()' in source
    assert "fetch('/api/isolated_categories')" in source
    assert 'export async function saveIsolatedCategories(payload)' in source
    assert "fetch('/api/isolated_categories', {" in source


def test_state_defines_isolated_category_store_and_actions():
    source = read_project_file('static/js/state.js')

    assert 'isolatedCategories: []' in source
    assert 'loadIsolatedCategories() {' in source
    assert 'saveIsolatedCategories(paths) {' in source
    assert 'addIsolatedCategory(path) {' in source
    assert 'removeIsolatedCategory(path) {' in source


def test_legacy_excluded_category_filter_state_and_request_are_removed():
    state_source = read_project_file('static/js/state.js')
    header_source = read_project_file('templates/components/header.html')
    header_js_source = read_project_file('static/js/components/header.js')
    card_grid_source = read_project_file('static/js/components/cardGrid.js')
    cards_api_source = read_project_file('core/api/v1/cards.py')

    assert 'excludedCategories' not in state_source
    assert '排除目录的 Chips' not in header_source
    assert 'toggleExcludedCategory' not in header_js_source
    assert 'excluded_cats' not in card_grid_source
    assert 'excluded_cats' not in cards_api_source


def test_state_bootstrap_loads_isolated_categories():
    source = read_project_file('static/js/state.js')

    assert 'return Promise.all([' in source
    assert 'this.loadIsolatedCategories()' in source


def test_card_grid_syncs_isolated_categories_from_list_response():
    source = read_project_file('static/js/components/cardGrid.js')

    assert 'if (data.isolated_categories)' in source
    assert 'store.isolatedCategories = data.isolated_categories.paths || [];' in source


def test_sidebar_template_renders_isolated_marker_and_accessibility_hooks():
    template_source = read_project_file('templates/components/sidebar.html')

    assert 'folder-item--isolated' in template_source
    assert '已设为隔离分类' in template_source
    assert 'aria-label' in template_source


def test_context_menu_template_exposes_isolate_and_unisolate_actions():
    template_source = read_project_file('templates/components/context_menu.html')

    assert 'handleToggleIsolation()' in template_source
    assert '设为隔离分类' in template_source
    assert '取消隔离分类' in template_source


def test_context_menu_uses_theme_aware_desktop_hover_colors():
    template_source = read_project_file('templates/components/context_menu.html')

    assert 'hover:bg-gray-700' not in template_source
    assert 'border-gray-700' not in template_source
    assert template_source.count('hover:bg-[var(--state-hover-surface)]') >= 8


def test_settings_template_contains_isolated_category_management_section():
    template_source = read_project_file('templates/modals/settings.html')

    assert '隔离分类' in template_source
    assert '这些分类在其上级目录视图中不会显示' in template_source
    assert 'clearIsolatedCategories()' in template_source


def test_sidebar_js_computes_isolation_state_for_folders():
    source = read_project_file('static/js/components/sidebar.js')

    assert 'isIsolatedFolder(path) {' in source
    assert 'isInsideIsolatedBranch(path) {' in source
    assert 'isIsolated: this.isIsolatedFolder(folder.path)' in source


def test_context_menu_js_uses_persistent_isolation_actions():
    source = read_project_file('static/js/components/contextMenu.js')

    assert 'handleToggleIsolation() {' in source
    assert 'this.$store.global.addIsolatedCategory(this.target)' in source
    assert 'this.$store.global.removeIsolatedCategory(this.target)' in source


def test_settings_modal_js_exposes_remove_and_clear_helpers():
    source = read_project_file('static/js/components/settingsModal.js')

    assert 'removeIsolatedCategory(path) {' in source
    assert 'clearIsolatedCategories() {' in source


def test_layout_and_settings_css_define_isolated_category_hooks():
    layout_css = read_project_file('static/css/modules/layout.css')
    settings_css = read_project_file('static/css/modules/modal-settings.css')

    assert '.folder-item--isolated' in layout_css
    assert '.folder-isolated-badge' in layout_css
    assert '.settings-isolated-list' in settings_css
