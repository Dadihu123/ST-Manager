import json
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def run_state_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/state.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');

        const stubs = `
        const getServerStatus = async () => ({{}});
        const getSettings = async () => ({{}});
        const saveSettings = async () => ({{ success: true }});
        const performSystemAction = async () => ({{ success: true }});
        const triggerScan = async () => ({{ success: true }});
        const updateCssVariable = () => {{}};
        const applyFont = () => {{}};
        const getIsolatedCategories = async () => ({{ isolated_categories: {{ paths: [] }} }});
        const saveIsolatedCategoriesRequest = async () => ({{ success: true, isolated_categories: {{ paths: [] }} }});
        globalThis.window = {{
          innerWidth: 1280,
          innerHeight: 720,
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
          visualViewport: null,
        }};
        globalThis.document = {{
          documentElement: {{
            classList: {{ add() {{}}, remove() {{}} }},
          }},
        }};
        globalThis.localStorage = {{
          getItem() {{ return null; }},
          setItem() {{}},
          removeItem() {{}},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};
        globalThis.alert = () => {{}};
        globalThis.confirm = () => true;
        globalThis.Alpine = {{
          _stores: new Map(),
          store(name, value) {{
            if (arguments.length === 1) return this._stores.get(name);
            this._stores.set(name, value);
            return value;
          }},
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source),
        );
        module.initState();
        const store = globalThis.Alpine.store('global');

        {textwrap.dedent(script_body)}
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def run_sidebar_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/sidebar.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source
          .split(/\\r?\\n/)
          .filter((line) => !line.trim().startsWith('import '))
          .join('\\n');

        const stubs = `
        const createFolder = async () => ({{}});
        const moveFolder = async () => ({{}});
        const moveCard = async () => ({{}});
        const migrateLorebooks = async () => ({{}});
        globalThis.fetch = async () => ({{ json: async () => ({{ success: true }}) }});
        globalThis.window = {{
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
        }};
        globalThis.document = {{
          querySelectorAll() {{ return []; }},
          body: {{ style: {{}} }},
        }};
        globalThis.localStorage = {{
          getItem() {{ return null; }},
          setItem() {{}},
          removeItem() {{}},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source),
        );

        const store = {{
          global: {{
            currentMode: 'cards',
            visibleSidebar: true,
            deviceType: 'desktop',
            allFoldersList: [],
            isolatedCategories: [],
            cardCategorySearchQuery: '',
            wiCategorySearchQuery: '',
            presetCategorySearchQuery: '',
            wiAllFolders: [],
            presetAllFolders: [],
            viewState: {{
              filterCategory: '',
              filterTags: [],
              draggedCards: [],
              draggedFolder: '',
              selectedIds: [],
            }},
          }},
        }};

        const component = module.default();
        component.$store = store;
        component.$watch = () => {{}};
        component.$nextTick = (cb) => cb();

        {textwrap.dedent(script_body)}
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_state_store_tracks_mode_specific_sidebar_category_queries():
    source = read_project_file('static/js/state.js')

    assert 'cardCategorySearchQuery: ""' in source
    assert 'wiCategorySearchQuery: ""' in source
    assert 'presetCategorySearchQuery: ""' in source

    run_state_runtime_check(
        """
        const fieldNames = [
          'cardCategorySearchQuery',
          'wiCategorySearchQuery',
          'presetCategorySearchQuery',
        ];

        for (const fieldName of fieldNames) {
          if (store[fieldName] !== '') {
            throw new Error(`${fieldName} should default to an empty string`);
          }

          store[fieldName] = `${fieldName}-value`;
          if (store[fieldName] !== `${fieldName}-value`) {
            throw new Error(`${fieldName} should be writable`);
          }
        }
        """
    )


def test_sidebar_component_filters_card_categories_by_name_and_path_and_keeps_parent_chain():
    run_sidebar_runtime_check(
        """
        store.global.allFoldersList = [
          { path: 'Characters', name: 'Characters', level: 0 },
          { path: 'Characters/Heroes', name: 'Heroes', level: 1 },
          { path: 'Characters/Villains', name: 'Villains', level: 1 },
          { path: 'Lore/Regions', name: 'Regions', level: 1 },
          { path: 'Archive/2025', name: '2025', level: 1 },
        ];

        const fullTreePaths = component.folderTree.map((folder) => folder.path);
        if (fullTreePaths.length !== 5) {
          throw new Error(`Expected full card tree before search, got ${JSON.stringify(fullTreePaths)}`);
        }

        component.cardCategorySearchQuery = 'hero';
        const nameMatchTree = component.folderTree;
        const nameMatchPaths = nameMatchTree.map((folder) => folder.path);
        const expectedNameMatchPaths = ['Characters', 'Characters/Heroes'];
        if (JSON.stringify(nameMatchPaths) !== JSON.stringify(expectedNameMatchPaths)) {
          throw new Error(`Expected parent chain for name match, got ${JSON.stringify(nameMatchPaths)}`);
        }
        const retainedParent = nameMatchTree.find((folder) => folder.path === 'Characters');
        const retainedChild = nameMatchTree.find((folder) => folder.path === 'Characters/Heroes');
        if (!retainedParent || retainedParent.visible !== true) {
          throw new Error(`Expected retained parent chain folder to stay visible, got ${JSON.stringify(retainedParent)}`);
        }
        if (!retainedChild || retainedChild.visible !== true) {
          throw new Error(`Expected matching child folder to stay visible, got ${JSON.stringify(retainedChild)}`);
        }

        component.cardCategorySearchQuery = 'archive/2025';
        const pathMatchPaths = component.folderTree.map((folder) => folder.path);
        if (JSON.stringify(pathMatchPaths) !== JSON.stringify(['Archive/2025'])) {
          throw new Error(`Expected path fragment search to match Archive/2025, got ${JSON.stringify(pathMatchPaths)}`);
        }

        component.cardCategorySearchQuery = '';
        const restoredPaths = component.folderTree.map((folder) => folder.path);
        if (JSON.stringify(restoredPaths) !== JSON.stringify(fullTreePaths)) {
          throw new Error(`Expected clearing card search to restore full tree, got ${JSON.stringify(restoredPaths)}`);
        }
        """
    )


def test_sidebar_component_keeps_mode_specific_search_queries_and_empty_result_flags():
    run_sidebar_runtime_check(
        """
        store.global.wiAllFolders = [
          'World/People',
          'World/Places',
        ];
        store.global.presetAllFolders = [
          'Style/Portrait',
          'Utility/Batch',
        ];

        component.cardCategorySearchQuery = 'cards-only';
        component.wiCategorySearchQuery = 'people';
        component.presetCategorySearchQuery = 'missing';

        if (!component.isWiCategorySearchActive) {
          throw new Error('World info search should be active');
        }
        if (component.isWiCategorySearchEmpty) {
          throw new Error('World info search should report visible results');
        }
        const wiPaths = component.wiFolderTree.map((folder) => folder.path);
        const expectedWiPaths = ['World/People'];
        if (JSON.stringify(wiPaths) !== JSON.stringify(expectedWiPaths)) {
          throw new Error(`Expected world info search to use its own query, got ${JSON.stringify(wiPaths)}`);
        }

        if (!component.isPresetCategorySearchActive) {
          throw new Error('Preset search should be active');
        }
        if (!component.isPresetCategorySearchEmpty) {
          throw new Error('Preset search should report the empty-result state');
        }
        if (component.presetFolderTree.length !== 0) {
          throw new Error(`Expected preset search to have no visible folders, got ${JSON.stringify(component.presetFolderTree)}`);
        }

        component.clearCategorySearch('worldinfo');
        if (component.wiCategorySearchQuery !== '') {
          throw new Error('clearCategorySearch(worldinfo) should only clear the world info query');
        }
        if (component.cardCategorySearchQuery !== 'cards-only') {
          throw new Error('World info clear should not change the card query');
        }
        if (component.presetCategorySearchQuery !== 'missing') {
          throw new Error('World info clear should not change the preset query');
        }

        component.clearCategorySearch('presets');
        if (component.presetCategorySearchQuery !== '') {
          throw new Error('clearCategorySearch(presets) should only clear the preset query');
        }
        if (component.cardCategorySearchQuery !== 'cards-only') {
          throw new Error('Preset clear should not change the card query');
        }
        """
    )


def test_sidebar_template_adds_persistent_category_search_inputs_to_cards_worldinfo_and_presets():
    source = read_project_file('templates/components/sidebar.html')

    assert 'x-model="cardCategorySearchQuery"' in source
    assert 'x-model="wiCategorySearchQuery"' in source
    assert 'x-model="presetCategorySearchQuery"' in source
    assert source.count('搜索分类或路径...') >= 3
    assert "@click=\"clearCategorySearch('cards')\"" in source
    assert "@click=\"clearCategorySearch('worldinfo')\"" in source
    assert "@click=\"clearCategorySearch('presets')\"" in source


def test_sidebar_template_exposes_category_search_empty_states_for_each_tree():
    source = read_project_file('templates/components/sidebar.html')

    assert 'x-show="isCardCategorySearchActive && isCardCategorySearchEmpty"' in source
    assert 'x-show="isWiCategorySearchActive && isWiCategorySearchEmpty"' in source
    assert (
        'x-show="isPresetCategorySearchActive && isPresetCategorySearchEmpty"' in source
    )
    assert source.count('未找到匹配分类') >= 3


def test_sidebar_category_search_layout_css_contracts_exist():
    source = read_project_file('static/css/modules/layout.css')

    assert '.sidebar-category-search-wrap {' in source
    assert '.sidebar-category-search {' in source
    assert '.sidebar-category-search:focus-within {' in source
    assert '.sidebar-category-search-input {' in source
    assert '.sidebar-category-search-clear {' in source
    assert '.sidebar-search-empty {' in source


def test_sidebar_category_search_focus_uses_the_rounded_wrapper_ring():
    source = read_project_file('static/css/modules/layout.css')

    assert '.sidebar-category-search-input:focus-visible' in source
    assert '.sidebar-category-search-clear:focus-visible' in source
    assert 'box-shadow: none !important;' in source


def test_sidebar_category_search_hover_uses_the_rounded_wrapper_surface():
    source = read_project_file('static/css/modules/layout.css')

    assert 'overflow: hidden;' in source
    assert '.sidebar-category-search:hover {' in source
    assert '.sidebar-category-search-input:hover:not(:disabled)' in source
    assert 'background-color: transparent !important;' in source


def test_sidebar_category_search_mobile_layout_css_contracts_exist():
    source = read_project_file('static/css/modules/layout.css')

    assert '.sidebar-mobile .sidebar-category-search-wrap {' in source
    assert '.sidebar-mobile .sidebar-category-search {' in source
    assert '.sidebar-mobile .sidebar-category-search-input {' in source
    assert '.sidebar-mobile .sidebar-category-search-clear {' in source
