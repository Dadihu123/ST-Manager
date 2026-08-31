import json
import re
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def assert_contains_any(text, variants):
    assert any(variant in text for variant in variants), f'Missing expected variants: {variants}'


def run_beautify_preview_frame_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/beautifyPreviewFrame.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
            source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function beautifyPreviewFrame()', 'function beautifyPreviewFrame()');

        const stubs = `
        const buildBeautifyPreviewAssetUrl = (value) => String(value || '');
        const clearIsolatedHtml = (host, options = {{}}) => {{
          if (!host.__events) host.__events = [];
          host.__events.push({{ type: 'clear', options }});
          host.innerHTML = '';
        }};
        const renderIsolatedHtml = (host, options = {{}}) => {{
          if (!host.__events) host.__events = [];
          host.__events.push({{ type: 'render', options }});
          host.innerHTML = String(options.htmlPayload || '');
        }};
        const DEFAULT_PREVIEW_SCENE_ID = 'daily';
        const PREVIEW_SCENE_OPTIONS = [
          {{ id: 'daily', label: '日常陪伴', description: '轻松自然的日常聊天' }},
          {{ id: 'flirty', label: '暧昧互动', description: '更柔和的情绪和停顿' }},
          {{ id: 'lore', label: '设定说明', description: '长段落和说明性文本' }},
          {{ id: 'story', label: '剧情推进', description: '带动作与状态变化的连续片段' }},
          {{ id: 'system', label: '系统提示', description: '系统通知与规则提醒' }},
        ];
        const buildBeautifyPreviewDocument = (options = {{}}) => JSON.stringify(options);
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default beautifyPreviewFrame;'),
        );

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


def run_beautify_grid_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/beautifyGrid.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function beautifyGrid()', 'function beautifyGrid()');

        const stubs = `
        const getGridStub = (name, fallback) => (...args) => {{
          const fn = globalThis.__gridStubs?.[name];
          return typeof fn === 'function' ? fn(...args) : fallback(...args);
        }};
        const buildBeautifyPreviewAssetUrl = getGridStub('buildBeautifyPreviewAssetUrl', (value) => String(value || ''));
        const clearIsolatedHtmlByOwner = getGridStub('clearIsolatedHtmlByOwner', () => 0);
        const deleteBeautifyPackage = getGridStub('deleteBeautifyPackage', async () => ({{ success: true }}));
        const getBeautifySettings = getGridStub('getBeautifySettings', async () => ({{ success: true, item: null }}));
        const getBeautifyPackage = getGridStub('getBeautifyPackage', async () => ({{ success: true, item: null }}));
        const importBeautifyScreenshot = getGridStub('importBeautifyScreenshot', async () => ({{ success: true, screenshot: {{ id: '' }} }}));
        const importBeautifyTheme = getGridStub('importBeautifyTheme', async () => ({{ success: true, package: {{ id: '' }} }}));
        const importBeautifyVariant = getGridStub('importBeautifyVariant', async () => ({{ success: true, package: {{ id: '' }}, variant: {{ id: '' }} }}));
        const importBeautifyPackageAvatar = getGridStub('importBeautifyPackageAvatar', async () => ({{ success: true, item: {{}} }}));
        const importGlobalBeautifyAvatar = getGridStub('importGlobalBeautifyAvatar', async () => ({{ success: true, item: null }}));
        const importGlobalBeautifyWallpaper = getGridStub('importGlobalBeautifyWallpaper', async () => ({{ success: true, item: null }}));
        const importSharedPreviewWallpaperForBeautify = getGridStub('importSharedPreviewWallpaperForBeautify', async () => ({{ success: true, item: null }}));
        const importBeautifyWallpaper = getGridStub('importBeautifyWallpaper', async () => ({{ success: true, wallpaper: {{ id: '' }} }}));
        const listBeautifyPackages = getGridStub('listBeautifyPackages', async () => ({{ success: true, items: [] }}));
        const sendBeautifyThemeToSt = getGridStub('sendBeautifyThemeToSt', async () => ({{ success: true, last_sent_to_st: '' }}));
        const selectSharedPreviewWallpaperForBeautify = getGridStub('selectSharedPreviewWallpaperForBeautify', async () => ({{ success: true, wallpaper: null }}));
        const updateBeautifyPackageIdentities = getGridStub('updateBeautifyPackageIdentities', async () => ({{ success: true, item: {{}} }}));
        const updateBeautifySettings = getGridStub('updateBeautifySettings', async () => ({{ success: true, item: null }}));
        const updateBeautifyVariant = getGridStub('updateBeautifyVariant', async () => ({{ success: true, item: null }}));
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default beautifyGrid;'),
        );

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


def run_layout_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/layout.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function layout()', 'function layout()');

        const stubs = `
        const moveFolder = async () => ({{ success: true }});
        const moveCard = async () => ({{ success: true }});
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default layout;'),
        );

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
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function sidebar()', 'function sidebar()');

        const stubs = `
        const createFolder = async () => ({{ success: true }});
        const moveFolder = async () => ({{ success: true }});
        const moveCard = async () => ({{ success: true }});
        const migrateLorebooks = async () => ({{ count: 0 }});
        globalThis.fetch = async () => ({{ json: async () => ({{ success: true }}) }});
        globalThis.window = {{
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
        }};
        globalThis.document = {{
          body: {{ style: {{}} }},
          querySelectorAll() {{ return []; }},
        }};
        globalThis.localStorage = {{
          getItem() {{ return null; }},
          setItem() {{}},
          removeItem() {{}},
        }};
        globalThis.requestAnimationFrame = (cb) => {{ cb(); return 1; }};
        globalThis.cancelAnimationFrame = () => {{}};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default sidebar;'),
        );

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


def test_sidebar_card_tag_basis_binding_returns_plain_value_for_non_card_modes():
    run_sidebar_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'regex',
            visibleSidebar: true,
            deviceType: 'desktop',
            viewState: {
              filterCategory: '',
              filterTags: [],
              draggedCards: [],
              draggedFolder: null,
              selectedIds: [],
              excludedTags: [],
            },
            allFoldersList: [],
            isolatedCategories: [],
            allTagsPool: [],
            tagIndexActiveCategory: '',
            wiAllFolders: [],
            presetAllFolders: [],
          },
        };

        component.tagPaneRatio = 0.34;
        if (component.cardTagPaneBasisStyle !== null) {
          throw new Error(`expected null for non-card mode, got ${component.cardTagPaneBasisStyle}`);
        }
        if (typeof component.desktopTagPaneStyle !== 'undefined') {
          throw new Error(`expected legacy desktopTagPaneStyle whole-style contract to be removed, got ${component.desktopTagPaneStyle}`);
        }
        '''
    )


def test_sidebar_card_tag_basis_style_returns_percent_only_for_active_card_splitter():
    run_sidebar_runtime_check(
        '''
        const baseStore = {
          global: {
            currentMode: 'cards',
            visibleSidebar: true,
            deviceType: 'desktop',
            viewState: {
              filterCategory: '',
              filterTags: [],
              draggedCards: [],
              draggedFolder: null,
              selectedIds: [],
              excludedTags: [],
            },
            allFoldersList: [],
            isolatedCategories: [],
            allTagsPool: [],
            tagIndexActiveCategory: '',
            wiAllFolders: [],
            presetAllFolders: [],
          },
        };

        const component = module.default();
        component.$store = baseStore;
        component.tagPaneRatio = 0.34;
        component.tagsSectionExpanded = false;

        if (component.cardTagPaneBasisStyle !== null) {
          throw new Error(`expected null when splitter is inactive, got ${component.cardTagPaneBasisStyle}`);
        }

        component.tagsSectionExpanded = true;

        if (component.cardTagPaneBasisStyle !== '34.00%') {
          throw new Error(`expected 34.00% for active cards desktop splitter, got ${component.cardTagPaneBasisStyle}`);
        }
        '''
    )


def run_render_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/runtime/renderRuntime.js'
    node_script = textwrap.dedent(
        """
        import { readFileSync } from 'node:fs';

        const sourcePath = __SOURCE_PATH__;
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');

        const stubs = `
        const buildRenderIframeDocument = (options = {}) => JSON.stringify(options);
        const RUNTIME_CHANNEL = 'st-manager:render-runtime';
        const removeRuntime = () => false;
        const upsertRuntime = (snapshot) => snapshot;
        class ShadowRootStub {
          constructor(host) {
            this.host = host;
            this.childNodes = [];
            this._innerHTML = '';
          }
          set innerHTML(value) {
            this._innerHTML = String(value || '');
            this.childNodes = [];
          }
          get innerHTML() {
            return this._innerHTML;
          }
          append(...nodes) {
            nodes.forEach((node) => this.appendChild(node));
          }
          appendChild(node) {
            if (!node) return node;
            node.parentNode = this;
            this.childNodes.push(node);
            return node;
          }
          querySelector(selector) {
            const match = (node) => {
              if (!node) return false;
              if (String(selector || '').startsWith('.')) {
                const token = String(selector || '').slice(1);
                return String(node.className || '').split(/\s+/).filter(Boolean).includes(token);
              }
              return String(node.tagName || '').toLowerCase() === String(selector || '').toLowerCase();
            };
            const stack = [...this.childNodes];
            while (stack.length) {
              const node = stack.shift();
              if (match(node)) {
                return node;
              }
              if (Array.isArray(node?.childNodes) && node.childNodes.length) {
                stack.unshift(...node.childNodes);
              }
            }
            return null;
          }
        }
        class ElementBase {
          constructor(tagName = 'div') {
            this.tagName = String(tagName || 'div').toUpperCase();
            this.childNodes = [];
            this.parentNode = null;
            this.style = {};
            this.dataset = {};
            this.className = '';
            this.attributes = {};
            this.isConnected = true;
            this.shadowRoot = null;
            this.__rectHeight = 0;
            this.__rectWidth = 0;
            this.eventListeners = {};
            this.contentWindow = this.tagName === 'IFRAME'
              ? { postMessage() {} }
              : null;
          }
          append(...nodes) {
            nodes.forEach((node) => this.appendChild(node));
          }
          appendChild(node) {
            if (!node) return node;
            node.parentNode = this;
            this.childNodes.push(node);
            return node;
          }
          attachShadow() {
            this.shadowRoot = new ShadowRootStub(this);
            return this.shadowRoot;
          }
          setAttribute(name, value) {
            this.attributes[String(name || '')] = String(value || '');
          }
          addEventListener(type, handler) {
            this.eventListeners[String(type || '')] = handler;
          }
          getBoundingClientRect() {
            return {
              width: Number(this.__rectWidth || 0),
              height: Number(this.__rectHeight || 0),
            };
          }
        }
        globalThis.window = {
          innerHeight: 900,
          addEventListener() {},
        };
        globalThis.document = {
          createElement(tagName) {
            return new ElementBase(tagName);
          },
        };
        globalThis.URL = {
          createObjectURL() {
            return 'blob:runtime-test';
          },
          revokeObjectURL() {},
        };
        globalThis.Blob = class Blob {
          constructor(parts = [], options = {}) {
            this.parts = parts;
            this.type = options.type || '';
          }
        };
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source),
        );

        __SCRIPT_BODY__
        """
    ).replace('__SOURCE_PATH__', json.dumps(str(source_path))).replace(
        '__SCRIPT_BODY__', textwrap.dedent(script_body)
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_beautify_settings_wallpaper_cards_bind_to_nested_shared_wallpaper_picker_helper_contract():
    template = read_project_file('templates/components/grid_beautify.html')
    picker_source = read_project_file('static/js/components/sharedWallpaperPicker.js')

    assert_contains_any(
        picker_source,
        (
            'sharedWallpaperPreviewUrl(relativePath) {',
            "sharedWallpaperPreviewUrl(relativePath) {",
        ),
    )
    assert re.search(
        r'''x-data="sharedWallpaperPicker\(\{\s*sourceFilter:\s*'all',\s*selectionTarget:\s*'preview'\s*\}\)"[\s\S]*?sharedWallpaperPreviewUrl\(item\.file\)''',
        template,
        re.DOTALL,
    )
    assert re.search(
        r'''x-data="sharedWallpaperPicker\(\{\s*sourceFilter:\s*'all',\s*selectionTarget:\s*'preview'\s*\}\)"[\s\S]*?selectGlobalWallpaper\(item\.id\)''',
        template,
        re.DOTALL,
    )


def test_index_template_lifts_beautify_scope_to_main_container_above_shared_includes():
    template = read_project_file('templates/index.html')

    main_container_index = template.index('<div class="main-container" x-data="beautifyGrid">')
    sidebar_index = template.index('{% include "components/sidebar.html" %}')
    beautify_grid_index = template.index('{% include "components/grid_beautify.html" %}')

    assert main_container_index < sidebar_index < beautify_grid_index


def test_sidebar_template_hosts_beautify_toolbar_filters_and_package_list_contract():
    sidebar_template = read_project_file('templates/components/sidebar.html')
    theme_change_handlers = (
        '@change="handleThemeFiles($event.target.files); $event.target.value = \'\'"',
        '@change="handleThemeFiles($event.target.files); $event.target.value = \"\""',
    )
    wallpaper_change_handlers = (
        '@change="handleWallpaperFiles($event.target.files); $event.target.value = \'\'"',
        '@change="handleWallpaperFiles($event.target.files); $event.target.value = \"\""',
    )

    assert "currentMode === 'beautify' && visibleSidebar" in sidebar_template
    assert 'beautify-sidebar-panel' in sidebar_template
    assert 'class="flex-1 flex flex-col overflow-hidden bg-[var(--surface-container)] beautify-sidebar-panel beautify-sidebar-pane"' in sidebar_template
    assert 'beautify-toolbar' in sidebar_template
    assert 'beautify-package-list custom-scrollbar' in sidebar_template
    assert 'x-model.debounce.200ms="beautifySearch"' in sidebar_template
    assert 'x-model="platformFilter"' in sidebar_template
    assert 'x-model="installFilter"' not in sidebar_template
    assert '@click="fetchPackages()"' in sidebar_template
    assert any(handler in sidebar_template for handler in theme_change_handlers)
    assert any(handler in sidebar_template for handler in wallpaper_change_handlers)
    assert 'filteredPackages' in sidebar_template
    assert '@click="selectPackage(item.id)"' in sidebar_template
    assert 'selectedPackageId === item.id' in sidebar_template
    assert 'beautify-status-pill' not in sidebar_template
    assert 'item.install_state' not in sidebar_template
    assert '当前应用中' not in sidebar_template
    assert '已安装' not in sidebar_template
    assert '未安装' not in sidebar_template


def test_app_js_registers_beautify_runtime_components():
    app_js = read_project_file('static/js/app.js')

    assert_contains_any(app_js, ('import beautifyGrid from "./components/beautifyGrid.js";', "import beautifyGrid from './components/beautifyGrid.js';"))
    assert_contains_any(app_js, ('import beautifyPreviewFrame from "./components/beautifyPreviewFrame.js";', "import beautifyPreviewFrame from './components/beautifyPreviewFrame.js';"))
    assert_contains_any(app_js, ('Alpine.data("beautifyGrid", beautifyGrid);', "Alpine.data('beautifyGrid', beautifyGrid);"))
    assert_contains_any(app_js, ('Alpine.data("beautifyPreviewFrame", beautifyPreviewFrame);', "Alpine.data('beautifyPreviewFrame', beautifyPreviewFrame);"))


def test_beautify_api_exports_core_runtime_helpers():
    beautify_api = read_project_file('static/js/api/beautify.js')

    expected_exports = (
        'listBeautifyPackages',
        'getBeautifyPackage',
        'importBeautifyTheme',
        'importBeautifyWallpaper',
        'updateBeautifyVariant',
        'deleteBeautifyPackage',
        'buildBeautifyPreviewAssetUrl',
    )

    for export_name in expected_exports:
        assert_contains_any(
            beautify_api,
            (
                f'export async function {export_name}(',
                f'export function {export_name}(',
            ),
        )


def test_beautify_api_exports_settings_and_screenshot_helpers():
    beautify_api = read_project_file('static/js/api/beautify.js')

    expected_exports = (
        'getBeautifySettings',
        'updateBeautifySettings',
        'importGlobalBeautifyWallpaper',
        'importGlobalBeautifyAvatar',
        'importBeautifyScreenshot',
        'updateBeautifyPackageIdentities',
        'importBeautifyPackageAvatar',
    )

    for export_name in expected_exports:
        assert_contains_any(
            beautify_api,
            (
                f'export async function {export_name}(',
                f'export function {export_name}(',
            ),
        )

    assert '/api/beautify/settings' in beautify_api
    assert '/api/beautify/update-settings' in beautify_api
    assert '/api/beautify/import-global-wallpaper' in beautify_api
    assert '/api/beautify/import-global-avatar' in beautify_api
    assert '/api/beautify/import-screenshot' in beautify_api
    assert '/api/beautify/update-package-identities' in beautify_api
    assert '/api/beautify/import-package-avatar' in beautify_api

    assert beautify_api.count('headers: { "Content-Type": "application/json" }') >= 2
    assert 'formData.append("package_id", packageId);' in beautify_api
    assert 'formData.append("target", target);' in beautify_api


def test_beautify_api_exposes_package_scoped_variant_import_helper():
    beautify_api = read_project_file('static/js/api/beautify.js')

    assert_contains_any(
        beautify_api,
        (
            'export async function importBeautifyVariant(file, packageId, options = {})',
            'export async function importBeautifyVariant(file, packageId, options={})',
        ),
    )
    assert_contains_any(
        beautify_api,
        (
            'if (!packageId) throw new Error("packageId is required");',
            "if (!packageId) throw new Error('packageId is required');",
        ),
    )
    assert 'return importBeautifyTheme(file, { ...options, package_id: packageId });' in beautify_api


def test_beautify_api_exports_shared_preview_wallpaper_helpers():
    beautify_api = read_project_file('static/js/api/beautify.js')

    for export_name in (
        'importSharedPreviewWallpaperForBeautify',
        'selectSharedPreviewWallpaperForBeautify',
    ):
        assert_contains_any(
            beautify_api,
            (
                f'export async function {export_name}(',
                f'export function {export_name}(',
            ),
        )

    assert '/api/shared-wallpapers/import' in beautify_api
    assert '/api/shared-wallpapers/select' in beautify_api
    assert 'formData.append("selection_target", "preview");' in beautify_api
    assert 'selection_target: "preview"' in beautify_api


def test_beautify_api_exposes_send_theme_to_st_helper_contract():
    beautify_api = read_project_file('static/js/api/beautify.js')

    assert_contains_any(
        beautify_api,
        (
            'export async function sendBeautifyThemeToSt(payload = {})',
            'export async function sendBeautifyThemeToSt(payload={})',
        ),
    )
    assert '/api/beautify/send-theme-to-st' in beautify_api
    assert_contains_any(
        beautify_api,
        (
            'method: "POST"',
            "method: 'POST'",
        ),
    )
    assert_contains_any(
        beautify_api,
        (
            'headers: { "Content-Type": "application/json" }',
            "headers: { 'Content-Type': 'application/json' }",
        ),
    )
    assert_contains_any(
        beautify_api,
        (
            'body: JSON.stringify(payload || {})',
            'body: JSON.stringify(payload||{})',
        ),
    )


def test_beautify_template_exposes_send_theme_to_st_button_contract():
    template = read_project_file('templates/components/grid_beautify.html')

    assert re.search(
        r'''<template\s+x-if="activeVariant">[\s\S]*?<button[\s\S]*?>[\s\S]*?发送主题到 ST[\s\S]*?</button>[\s\S]*?</template>''',
        template,
        re.DOTALL,
    )
    assert '@click="sendActiveThemeToST()"' in template
    assert ':title="getActiveVariantSendToSTTitle()"' in template
    assert ':disabled="isActionLoading || !canSendActiveVariantToST()"' in template


def test_beautify_grid_js_exposes_send_theme_to_st_contracts():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    assert_contains_any(
        grid_source,
        (
            'sendBeautifyThemeToSt,',
            'sendBeautifyThemeToSt,\n',
        ),
    )
    for token in (
        'canSendActiveVariantToST()',
        'getActiveVariantSendToSTTitle()',
        'applyActiveVariantSentState(lastSentToSt)',
        'async sendActiveThemeToST()',
        'this.$store.global.beautifyActiveVariant.last_sent_to_st = lastSentToSt;',
        'sendBeautifyThemeToSt({',
        "throw new Error(res?.error || '发送主题到 ST 失败');",
        'this.applyActiveVariantSentState(res.last_sent_to_st);',
        'this.$store.global.showToast("主题已发送到 ST 并设为当前主题", 2200, "send");',
    ):
        assert token in grid_source


def test_beautify_api_removes_install_and_apply_client_exports():
    beautify_api = read_project_file('static/js/api/beautify.js')

    assert 'export async function installBeautifyVariant(' not in beautify_api
    assert 'export async function applyBeautifyVariant(' not in beautify_api


def test_native_st_vendor_assets_are_present_with_attribution():
    vendor_root = PROJECT_ROOT / 'static/vendor/sillytavern'

    assert (vendor_root / 'LICENSE').exists()
    assert (vendor_root / 'SOURCE.md').exists()
    assert (vendor_root / 'style.css').exists()
    assert (vendor_root / 'css/mobile-styles.css').exists()


def test_native_st_vendor_popup_css_uses_vendored_dialog_polyfill_path():
    popup_css = read_project_file('static/vendor/sillytavern/css/popup.css')

    assert "@import url('/lib/dialog-polyfill.css');" not in popup_css
    assert '../lib/dialog-polyfill.css' in popup_css


def test_beautify_grid_removes_install_and_apply_selection_methods():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    assert 'async installCurrentSelection()' not in grid_source
    assert 'async applyCurrentSelection()' not in grid_source
    assert 'function filterPackages(items, search, platformFilter, installFilter)' not in grid_source
    assert 'get installFilter()' not in grid_source
    assert 'set installFilter(val)' not in grid_source
    assert 'item.install_state' not in grid_source
    assert 'beautifyInstallFilter' not in grid_source


def test_beautify_grid_runtime_send_active_theme_updates_active_variant_timestamp():
    run_beautify_grid_runtime_check(
        '''
        const payloads = [];
        const toastCalls = [];
        globalThis.__gridStubs = {
          sendBeautifyThemeToSt: async (payload) => {
            payloads.push(payload);
            return {
              success: true,
              last_sent_to_st: '2026-04-28T12:34:56Z',
            };
          },
        };

        const variantInDetail = {
          id: 'var_1',
          platform: 'pc',
          wallpaper_ids: [],
          selected_wallpaper_id: '',
          last_sent_to_st: '2025-01-01T00:00:00Z',
          theme_data: { name: 'Blue Theme' },
        };
        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_1',
            beautifyActiveDetail: {
              id: 'pkg_1',
              variants: {
                var_1: variantInDetail,
              },
            },
            beautifyActiveVariant: {
              id: 'var_1',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
              last_sent_to_st: '2025-01-01T00:00:00Z',
              theme_data: { name: 'Blue Theme' },
            },
            showToast: (...args) => toastCalls.push(args),
          },
        };

        const pending = component.sendActiveThemeToST();
        if (component.isActionLoading !== true) {
          throw new Error('expected sendActiveThemeToST to set isActionLoading while request is pending');
        }
        await pending;

        if (component.isActionLoading !== false) {
          throw new Error('expected sendActiveThemeToST to clear isActionLoading after success');
        }
        if (payloads.length !== 1) {
          throw new Error(`expected one send payload, got ${payloads.length}`);
        }
        if (payloads[0].package_id !== 'pkg_1' || payloads[0].variant_id !== 'var_1') {
          throw new Error(`unexpected send payload: ${JSON.stringify(payloads[0])}`);
        }
        if (component.$store.global.beautifyActiveVariant.last_sent_to_st !== '2026-04-28T12:34:56Z') {
          throw new Error(`expected active variant timestamp to update, got ${component.$store.global.beautifyActiveVariant.last_sent_to_st}`);
        }
        if (component.$store.global.beautifyActiveDetail.variants.var_1.last_sent_to_st !== '2026-04-28T12:34:56Z') {
          throw new Error(`expected active detail variant timestamp to update, got ${component.$store.global.beautifyActiveDetail.variants.var_1.last_sent_to_st}`);
        }
        if (toastCalls.length !== 1 || toastCalls[0][0] !== '主题已发送到 ST 并设为当前主题' || toastCalls[0][2] !== 'send') {
          throw new Error(`expected success toast, got ${JSON.stringify(toastCalls)}`);
        }
        '''
    )


def test_beautify_grid_runtime_send_active_theme_does_not_stamp_new_selection_after_switch():
    run_beautify_grid_runtime_check(
        '''
        const payloads = [];
        const toastCalls = [];
        let resolveSend;
        globalThis.__gridStubs = {
          sendBeautifyThemeToSt: (payload) => {
            payloads.push(payload);
            return new Promise((resolve) => {
              resolveSend = () => resolve({
                success: true,
                last_sent_to_st: '2026-04-28T12:34:56Z',
              });
            });
          },
        };

        const sentVariant = {
          id: 'var_1',
          platform: 'pc',
          wallpaper_ids: [],
          selected_wallpaper_id: '',
          last_sent_to_st: '2025-01-01T00:00:00Z',
          theme_data: { name: 'Blue Theme' },
        };
        const nextVariant = {
          id: 'var_2',
          platform: 'mobile',
          wallpaper_ids: [],
          selected_wallpaper_id: '',
          last_sent_to_st: '2025-02-02T00:00:00Z',
          theme_data: { name: 'Green Theme' },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_1',
            beautifyActiveDetail: {
              id: 'pkg_1',
              variants: {
                var_1: sentVariant,
              },
            },
            beautifyActiveVariant: {
              ...sentVariant,
            },
            showToast: (...args) => toastCalls.push(args),
          },
        };

        const pending = component.sendActiveThemeToST();
        if (payloads.length !== 1) {
          throw new Error(`expected one send payload before switch, got ${payloads.length}`);
        }

        component.$store.global.beautifySelectedPackageId = 'pkg_2';
        component.$store.global.beautifyActiveDetail = {
          id: 'pkg_2',
          variants: {
            var_2: nextVariant,
          },
        };
        component.$store.global.beautifyActiveVariant = {
          ...nextVariant,
        };

        resolveSend();
        await pending;

        if (component.$store.global.beautifyActiveVariant.last_sent_to_st !== '2025-02-02T00:00:00Z') {
          throw new Error(`expected newly selected active variant to remain unchanged, got ${component.$store.global.beautifyActiveVariant.last_sent_to_st}`);
        }
        if (component.$store.global.beautifyActiveDetail.variants.var_2.last_sent_to_st !== '2025-02-02T00:00:00Z') {
          throw new Error(`expected newly selected detail variant to remain unchanged, got ${component.$store.global.beautifyActiveDetail.variants.var_2.last_sent_to_st}`);
        }
        if (sentVariant.last_sent_to_st !== '2025-01-01T00:00:00Z') {
          throw new Error(`expected stale package variant object to remain untouched after switch, got ${sentVariant.last_sent_to_st}`);
        }
        if (toastCalls.length !== 1 || toastCalls[0][0] !== '主题已发送到 ST 并设为当前主题' || toastCalls[0][2] !== 'send') {
          throw new Error(`expected success toast after delayed send, got ${JSON.stringify(toastCalls)}`);
        }
        '''
    )


def test_beautify_grid_runtime_send_active_theme_surfaces_backend_error_without_mutating_timestamp():
    run_beautify_grid_runtime_check(
        '''
        const payloads = [];
        const toastCalls = [];
        globalThis.__gridStubs = {
          sendBeautifyThemeToSt: async (payload) => {
            payloads.push(payload);
            return {
              success: false,
              error: '后端发送失败',
            };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_1',
            beautifyActiveDetail: {
              id: 'pkg_1',
              variants: {
                var_1: {
                  id: 'var_1',
                  platform: 'pc',
                  wallpaper_ids: [],
                  selected_wallpaper_id: '',
                  last_sent_to_st: '2025-01-01T00:00:00Z',
                  theme_data: { name: 'Blue Theme' },
                },
              },
            },
            beautifyActiveVariant: {
              id: 'var_1',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
              last_sent_to_st: '2025-01-01T00:00:00Z',
              theme_data: { name: 'Blue Theme' },
            },
            showToast: (...args) => toastCalls.push(args),
          },
        };

        await component.sendActiveThemeToST();

        if (component.isActionLoading !== false) {
          throw new Error('expected sendActiveThemeToST to clear isActionLoading after failure');
        }
        if (payloads.length !== 1) {
          throw new Error(`expected one send payload, got ${payloads.length}`);
        }
        if (component.$store.global.beautifyActiveVariant.last_sent_to_st !== '2025-01-01T00:00:00Z') {
          throw new Error(`expected active variant timestamp to remain unchanged, got ${component.$store.global.beautifyActiveVariant.last_sent_to_st}`);
        }
        if (component.$store.global.beautifyActiveDetail.variants.var_1.last_sent_to_st !== '2025-01-01T00:00:00Z') {
          throw new Error(`expected active detail timestamp to remain unchanged, got ${component.$store.global.beautifyActiveDetail.variants.var_1.last_sent_to_st}`);
        }
        if (toastCalls.length !== 1 || toastCalls[0][0] !== '后端发送失败') {
          throw new Error(`expected backend error toast, got ${JSON.stringify(toastCalls)}`);
        }
        '''
    )


def test_beautify_grid_platform_selector_does_not_optimistically_mutate_active_variant_platform():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'x-model="activeVariant.platform"' not in template
    assert "x-model='activeVariant.platform'" not in template
    assert 'updateCurrentVariantPlatform(option.value)' in template
    assert '"activeVariant?.platform || \'pc\'"' in template


def test_beautify_grid_source_tracks_workspace_screenshot_and_settings_methods():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    for token in (
        'get workspace()',
        'set workspace(val)',
        'get stageMode()',
        'set stageMode(val)',
        'get screenshotOptions()',
        'get activeScreenshot()',
        'async fetchGlobalSettings()',
        'async handleScreenshotFiles(fileList)',
        'async saveGlobalSettings()',
        'async savePackageIdentityOverrides()',
        'async handleGlobalWallpaperFiles(fileList)',
        'async handleGlobalAvatarFile(target, fileList)',
        'async handlePackageAvatarFile(target, fileList)',
        'async clearGlobalWallpaper()',
        'async clearGlobalCharacterAvatar()',
        'async clearGlobalUserAvatar()',
        'async clearPackageCharacterAvatar()',
        'async clearPackageUserAvatar()',
        'switchBeautifyWorkspace(workspace)',
        'setStageMode(mode)',
        'selectScreenshot(screenshotId)',
    ):
        assert token in grid_source


def test_beautify_grid_exposes_beautify_workspace_alias_for_templates():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    assert 'get beautifyWorkspace()' in grid_source
    assert 'set beautifyWorkspace(val)' in grid_source


def test_beautify_grid_switching_to_settings_workspace_refetches_global_settings():
    run_beautify_grid_runtime_check(
        '''
        let settingsFetches = 0;
        globalThis.__gridStubs = {
          getBeautifySettings: async () => {
            settingsFetches += 1;
            return {
              success: true,
              item: {
                identities: {
                  character: { name: '全局角色', avatar_file: '' },
                  user: { name: '全局用户', avatar_file: '' },
                },
              },
            };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            showToast: () => {},
          },
        };

        component.switchBeautifyWorkspace('settings');
        await Promise.resolve();

        if (settingsFetches !== 1) {
          throw new Error(`expected one settings refetch, got ${settingsFetches}`);
        }
        '''
    )


def test_beautify_grid_reselects_first_visible_package_when_platform_filter_hides_current_selection():
    run_beautify_grid_runtime_check(
        '''
        const watchers = new Map();
        globalThis.__gridStubs = {
          getBeautifyPackage: async (packageId) => ({
            success: true,
            item: {
              id: packageId,
              variants: {},
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };
        globalThis.window = {
          addEventListener: () => {},
        };

        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'cards',
            beautifyList: [
              { id: 'pkg_pc', name: 'PC Package', platforms: ['pc'] },
              { id: 'pkg_mobile', name: 'Mobile Package', platforms: ['mobile'] },
            ],
            beautifyPlatformFilter: 'all',
            beautifySelectedPackageId: 'pkg_pc',
            showToast: () => {},
          },
        };
        component.$watch = (key, callback) => watchers.set(key, callback);

        component.init();

        const platformWatcher = watchers.get('$store.global.beautifyPlatformFilter');
        if (typeof platformWatcher !== 'function') {
          throw new Error('expected platform filter watcher');
        }

        component.$store.global.currentMode = 'beautify';
        component.$store.global.beautifyPlatformFilter = 'mobile';
        platformWatcher('mobile');
        await Promise.resolve();

        if (component.$store.global.beautifySelectedPackageId !== 'pkg_mobile') {
          throw new Error(`expected platform filter change to reselect first visible package, got ${component.$store.global.beautifySelectedPackageId}`);
        }
      '''
    )


def test_beautify_grid_switching_variant_rebinds_wallpaper_when_previous_selection_is_not_supported():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {
                wall_old: { id: 'wall_old', file: 'old.png' },
                wall_new: { id: 'wall_new', file: 'new.png' },
              },
              screenshots: {},
              identity_overrides: {},
            },
            beautifySelectedWallpaperId: 'wall_old',
            beautifyPreviewDevice: 'pc',
            showToast: () => {},
          },
        };

        component.applyActiveVariant({
          id: 'variant_new',
          platform: 'pc',
          wallpaper_ids: ['wall_new'],
        });

        if (component.$store.global.beautifySelectedWallpaperId !== 'wall_new') {
          throw new Error(`expected variant switch to fall back to first bound wallpaper, got ${component.$store.global.beautifySelectedWallpaperId}`);
        }
        if (component.$store.global.beautifyActiveWallpaper?.id !== 'wall_new') {
          throw new Error('active wallpaper should follow the new variant wallpaper binding');
        }
        '''
    )


def test_beautify_grid_restores_persisted_variant_selected_wallpaper_after_package_reload():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: {
              wallpapers: {
                wall_first: { id: 'wall_first', file: 'first.png' },
                wall_selected: { id: 'wall_selected', file: 'selected.png' },
              },
            },
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            beautifyPreviewDevice: 'pc',
          },
        };
        component.selectedWallpaperId = '';
        component.selectedVariantPlatform = 'pc';

        const variant = {
          id: 'var_pc',
          platform: 'pc',
          wallpaper_ids: ['wall_first', 'wall_selected'],
          selected_wallpaper_id: 'wall_selected',
        };

        component.applyActiveVariant(variant);

        if (component.selectedWallpaperId !== 'wall_selected') {
          throw new Error(`expected persisted selected wallpaper restore, got: ${component.selectedWallpaperId}`);
        }
        if (component.$store.global.beautifyActiveWallpaper?.id !== 'wall_selected') {
          throw new Error(`expected active wallpaper to restore selected id, got: ${component.$store.global.beautifyActiveWallpaper?.id}`);
        }
        '''
    )


def test_beautify_grid_select_wallpaper_persists_variant_selection_and_updates_active_preview():
    run_beautify_grid_runtime_check(
        '''
        const updateCalls = [];
        globalThis.__gridStubs = {
          updateBeautifyVariant: async (payload) => {
            updateCalls.push(payload);
            return {
              success: true,
              item: {
                id: payload.variant_id,
                platform: 'pc',
                wallpaper_ids: ['wall_old', 'wall_new'],
                selected_wallpaper_id: payload.selected_wallpaper_id,
                preview_hint: {
                  needs_platform_review: false,
                  preview_accuracy: 'approx',
                },
              },
            };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedVariantId: 'var_pc',
            beautifySelectedWallpaperId: 'wall_old',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                var_pc: {
                  id: 'var_pc',
                  platform: 'pc',
                  wallpaper_ids: ['wall_old', 'wall_new'],
                  selected_wallpaper_id: 'wall_old',
                },
              },
              wallpapers: {
                wall_old: { id: 'wall_old', file: 'old.png' },
                wall_new: { id: 'wall_new', file: 'new.png' },
              },
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'var_pc',
              platform: 'pc',
              wallpaper_ids: ['wall_old', 'wall_new'],
              selected_wallpaper_id: 'wall_old',
            },
            beautifyActiveWallpaper: { id: 'wall_old', file: 'old.png' },
            showToast: () => {},
          },
        };

        await component.selectWallpaper('wall_new');

        if (updateCalls.length !== 1) {
          throw new Error(`expected one variant update call, got ${updateCalls.length}`);
        }
        if (updateCalls[0].package_id !== 'pkg_demo' || updateCalls[0].variant_id !== 'var_pc') {
          throw new Error(`unexpected variant update payload: ${JSON.stringify(updateCalls[0])}`);
        }
        if (updateCalls[0].selected_wallpaper_id !== 'wall_new') {
          throw new Error(`expected selected_wallpaper_id update, got ${JSON.stringify(updateCalls[0])}`);
        }
        if (component.selectedWallpaperId !== 'wall_new') {
          throw new Error(`expected selectedWallpaperId to update, got ${component.selectedWallpaperId}`);
        }
        if (component.$store.global.beautifyActiveWallpaper?.id !== 'wall_new') {
          throw new Error(`expected active wallpaper to switch, got ${component.$store.global.beautifyActiveWallpaper?.id}`);
        }
        if (component.$store.global.beautifyActiveVariant?.selected_wallpaper_id !== 'wall_new') {
          throw new Error(`expected active variant selected_wallpaper_id to update, got ${component.$store.global.beautifyActiveVariant?.selected_wallpaper_id}`);
        }
        if (component.$store.global.beautifyActiveDetail?.variants?.var_pc?.selected_wallpaper_id !== 'wall_new') {
          throw new Error(`expected active detail variant selection to update, got ${component.$store.global.beautifyActiveDetail?.variants?.var_pc?.selected_wallpaper_id}`);
        }
        '''
    )


def test_beautify_grid_preserves_existing_screenshot_selection_when_importing_more_images():
    run_beautify_grid_runtime_check(
        '''
        let imported = 0;
        globalThis.__gridStubs = {
          importBeautifyScreenshot: async () => {
            imported += 1;
            return { success: true, screenshot: { id: `shot_new_${imported}` } };
          },
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {
                shot_existing: { id: 'shot_existing', file: 'existing.png' },
                shot_new_1: { id: 'shot_new_1', file: 'new-1.png' },
                shot_new_2: { id: 'shot_new_2', file: 'new-2.png' },
              },
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedScreenshotId: 'shot_existing',
            showToast: () => {},
          },
        };

        await component.handleScreenshotFiles([{ name: 'one.png' }, { name: 'two.png' }]);

        if (component.$store.global.beautifySelectedScreenshotId !== 'shot_existing') {
          throw new Error(`expected existing screenshot selection to be preserved, got ${component.$store.global.beautifySelectedScreenshotId}`);
        }
        '''
    )


def test_beautify_grid_activates_first_imported_screenshot_when_none_was_selected():
    run_beautify_grid_runtime_check(
        '''
        let imported = 0;
        globalThis.__gridStubs = {
          importBeautifyScreenshot: async () => {
            imported += 1;
            return { success: true, screenshot: { id: `shot_new_${imported}` } };
          },
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {
                shot_old: { id: 'shot_old', file: 'old.png' },
                shot_new_1: { id: 'shot_new_1', file: 'new-1.png' },
                shot_new_2: { id: 'shot_new_2', file: 'new-2.png' },
              },
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedScreenshotId: '',
            showToast: () => {},
          },
        };

        await component.handleScreenshotFiles([{ name: 'one.png' }, { name: 'two.png' }]);

        if (component.$store.global.beautifySelectedScreenshotId !== 'shot_new_1') {
          throw new Error(`expected first imported screenshot to become active, got ${component.$store.global.beautifySelectedScreenshotId}`);
        }
        '''
    )


def test_beautify_grid_variant_import_uses_selected_package_and_preserves_existing_same_platform_variants():
    run_beautify_grid_runtime_check(
        '''
        let imported = 0;
        const importCalls = [];
        globalThis.__gridStubs = {
          importBeautifyVariant: async (file, packageId) => {
            importCalls.push({ fileName: file?.name || '', packageId });
            imported += 1;
            return {
              success: true,
              package: { id: 'pkg_demo' },
              variant: { id: `var_new_${imported}`, platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
            };
          },
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {
                var_old: { id: 'var_old', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                var_new_1: { id: 'var_new_1', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedVariantId: 'var_old',
            beautifyPreviewDevice: 'pc',
            beautifyVariantSelectionByDevice: {},
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                var_old: { id: 'var_old', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'var_old', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        await component.handleVariantFiles([{ name: 'warm.json' }]);

        if (importCalls.length !== 1) {
          throw new Error(`expected one variant import call, got ${importCalls.length}`);
        }
        if (importCalls[0].packageId !== 'pkg_demo') {
          throw new Error(`expected variant import to use selected package id, got ${JSON.stringify(importCalls[0])}`);
        }
        if (component.$store.global.beautifyActiveDetail.variants.var_old == null) {
          throw new Error('old same-platform variant should remain after import');
        }
        if (component.$store.global.beautifyActiveDetail.variants.var_new_1 == null) {
          throw new Error('new sibling variant should exist after import');
        }
        '''
    )


def test_beautify_grid_selects_concrete_variant_without_erasing_preview_device_history():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {
                pc_a: { id: 'pc_a', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                pc_b: { id: 'pc_b', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_a: { id: 'mobile_a', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };
        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifyPreviewDevice: 'pc',
            beautifyVariantSelectionByDevice: {},
            beautifySelectedVariantId: '',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                pc_a: { id: 'pc_a', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                pc_b: { id: 'pc_b', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_a: { id: 'mobile_a', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.selectVariant('pc_b');

        if (component.$store.global.beautifySelectedVariantId !== 'pc_b') {
          throw new Error('expected concrete variant selection to persist id');
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.pc !== 'pc_b') {
          throw new Error('expected device-specific variant history to be recorded');
        }

        component.selectVariant('mobile_a');

        if (component.$store.global.beautifyVariantSelectionByDevice.mobile !== 'mobile_a') {
          throw new Error(`expected cross-platform manual selection to be remembered under mobile, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }

        await component.previewPlatform('mobile');

        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_a') {
          throw new Error(`expected remembered mobile variant to be restored on mobile preview, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        await component.previewPlatform('pc');

        if (component.$store.global.beautifyActiveVariant?.id !== 'pc_b') {
          throw new Error(`expected remembered pc variant to be restored on device switch, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        component.$store.global.beautifyActiveVariant = null;
        component.$store.global.beautifySelectedVariantId = '';
        await component.selectPackage('pkg_demo');

        if (component.$store.global.beautifyActiveVariant?.id !== 'pc_b') {
          throw new Error(`expected remembered pc variant to be preferred on package re-resolution, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        '''
    )


def test_beautify_grid_fetch_packages_reselects_first_available_package_when_existing_selection_disappears():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          listBeautifyPackages: async () => ({
            success: true,
            items: [
              { id: 'pkg_fresh', name: 'Fresh Package', platforms: ['pc'] },
            ],
          }),
          getBeautifyPackage: async (packageId) => {
            if (packageId === 'pkg_missing') {
              return { success: false, item: null };
            }
            if (packageId === 'pkg_fresh') {
              return {
                success: true,
                item: {
                  id: 'pkg_fresh',
                  variants: {
                    variant_pc: { id: 'variant_pc', platform: 'pc', wallpaper_ids: ['wall_fresh'] },
                  },
                  wallpapers: {
                    wall_fresh: { id: 'wall_fresh', file: 'fresh.png' },
                  },
                  screenshots: {
                    shot_fresh: { id: 'shot_fresh', file: 'fresh-shot.png' },
                  },
                  identity_overrides: {},
                },
              };
            }
            return { success: false, item: null };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_missing',
            beautifySelectedVariantId: 'variant_stale',
            beautifySelectedWallpaperId: 'wall_stale',
            beautifySelectedScreenshotId: 'shot_stale',
            beautifyActiveDetail: {
              id: 'pkg_missing',
              variants: {
                variant_stale: { id: 'variant_stale', platform: 'pc', wallpaper_ids: ['wall_stale'] },
              },
              wallpapers: {
                wall_stale: { id: 'wall_stale', file: 'stale.png' },
              },
              screenshots: {
                shot_stale: { id: 'shot_stale', file: 'stale-shot.png' },
              },
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'variant_stale', platform: 'pc', wallpaper_ids: ['wall_stale'] },
            beautifyActiveWallpaper: { id: 'wall_stale', file: 'stale.png' },
            showToast: () => {},
          },
        };

        await component.fetchPackages();

        if (component.$store.global.beautifySelectedPackageId !== 'pkg_fresh') {
          throw new Error(`expected missing selection to fall back to first refreshed package, got ${component.$store.global.beautifySelectedPackageId}`);
        }
        if (component.$store.global.beautifyActiveDetail?.id !== 'pkg_fresh') {
          throw new Error('active detail should be replaced by the refreshed fallback package');
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'variant_pc') {
          throw new Error('fallback package should activate its default variant');
        }
        if (component.$store.global.beautifyActiveWallpaper?.id !== 'wall_fresh') {
          throw new Error('fallback package should activate its default wallpaper');
        }
        if (component.$store.global.beautifySelectedScreenshotId !== 'shot_fresh') {
          throw new Error(`fallback package should replace stale screenshot selection, got ${component.$store.global.beautifySelectedScreenshotId}`);
        }
        '''
    )


def test_beautify_grid_preserves_global_name_drafts_during_avatar_uploads():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          importGlobalBeautifyAvatar: async () => ({
            success: true,
            item: {
              identities: {
                character: { name: '已保存角色', avatar_file: 'character.png' },
                user: { name: '已保存用户', avatar_file: '' },
              },
            },
          }),
        };

        const component = module.default();
        component.$store = { global: { showToast: () => {} } };
        component.globalCharacterName = '草稿角色';
        component.globalUserName = '草稿用户';

        await component.handleGlobalAvatarFile('character', [{ name: 'avatar.png' }]);

        if (component.globalCharacterName !== '草稿角色' || component.globalUserName !== '草稿用户') {
          throw new Error('global draft names should survive avatar uploads');
        }
        '''
    )


def test_beautify_grid_preserves_package_name_drafts_during_avatar_uploads():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          importBeautifyPackageAvatar: async () => ({
            success: true,
            item: {
              avatar_file: 'character.png',
            },
          }),
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {},
              identity_overrides: {
                character: { name: '已保存角色', avatar_file: 'character.png' },
                user: { name: '已保存用户', avatar_file: '' },
              },
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedScreenshotId: '',
            showToast: () => {},
          },
        };
        component.packageCharacterName = '草稿角色';
        component.packageUserName = '草稿用户';

        await component.handlePackageAvatarFile('character', [{ name: 'avatar.png' }]);

        if (component.packageCharacterName !== '草稿角色' || component.packageUserName !== '草稿用户') {
          throw new Error('package draft names should survive avatar uploads');
        }
        '''
    )


def test_beautify_grid_imported_global_wallpaper_uses_shared_preview_selection_flow():
    run_beautify_grid_runtime_check(
        '''
        let importedCalls = 0;
        let settingsFetches = 0;
        globalThis.__gridStubs = {
          importSharedPreviewWallpaperForBeautify: async (file) => {
            importedCalls += 1;
            if (!file || file.name !== 'preview.png') {
              throw new Error('expected uploaded preview wallpaper file');
            }
            return {
              success: true,
              item: {
                id: 'imported:preview',
                file: 'data/library/wallpapers/imported/preview.png',
                filename: 'preview.png',
                source_type: 'imported',
              },
            };
          },
          getBeautifySettings: async () => {
            settingsFetches += 1;
            return {
              success: true,
              item: {
                preview_wallpaper_id: 'imported:preview',
                wallpaper: {
                  id: 'imported:preview',
                  file: 'data/library/wallpapers/imported/preview.png',
                  filename: 'preview.png',
                  source_type: 'imported',
                },
                identities: {
                  character: { name: '', avatar_file: '' },
                  user: { name: '', avatar_file: '' },
                },
              },
            };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            sharedWallpapers: [
              {
                id: 'builtin:space/stars.png',
                file: 'static/assets/wallpapers/builtin/space/stars.png',
                filename: 'stars.png',
                source_type: 'builtin',
              },
            ],
            beautifyGlobalSettings: {
              identities: {
                character: { name: '', avatar_file: '' },
                user: { name: '', avatar_file: '' },
              },
            },
            showToast: () => {},
          },
        };
        component.globalCharacterName = '草稿角色';
        component.globalUserName = '草稿用户';

        await component.handleGlobalWallpaperFiles([{ name: 'preview.png' }]);

        if (importedCalls !== 1) {
          throw new Error(`expected shared preview wallpaper import once, got ${importedCalls}`);
        }
        if (settingsFetches !== 1) {
          throw new Error(`expected one settings refresh after import, got ${settingsFetches}`);
        }
        if (component.$store.global.beautifyGlobalSettings?.preview_wallpaper_id !== 'imported:preview') {
          throw new Error('expected refreshed settings to keep preview wallpaper id');
        }
        if (component.$store.global.beautifyGlobalSettings?.wallpaper?.id !== 'imported:preview') {
          throw new Error('expected refreshed settings to expose resolved shared wallpaper object');
        }
        const sharedIds = (component.$store.global.sharedWallpapers || []).map((item) => item.id).sort();
        if (sharedIds.length !== 2 || sharedIds[0] !== 'builtin:space/stars.png' || sharedIds[1] !== 'imported:preview') {
          throw new Error(`expected imported shared wallpaper to merge into store, got ${JSON.stringify(sharedIds)}`);
        }
        if (component.globalCharacterName !== '草稿角色' || component.globalUserName !== '草稿用户') {
          throw new Error('global draft names should survive shared preview wallpaper imports');
        }
        '''
    )


def test_beautify_grid_imported_package_wallpaper_merges_shared_wallpaper_store():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          importBeautifyWallpaper: async () => ({
            success: true,
            wallpaper: {
              id: 'package_embedded:pkg_demo/wall_new',
              file: 'data/library/wallpapers/package_embedded/pkg_demo/var_pc/wall_new.png',
              filename: 'wall_new.png',
              source_type: 'package_embedded',
              origin_package_id: 'pkg_demo',
              origin_variant_id: 'var_pc',
            },
          }),
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {
                var_pc: {
                  id: 'var_pc',
                  platform: 'pc',
                  wallpaper_ids: ['package_embedded:pkg_demo/wall_new'],
                  selected_wallpaper_id: 'package_embedded:pkg_demo/wall_new',
                },
              },
              wallpapers: {
                'package_embedded:pkg_demo/wall_new': {
                  id: 'package_embedded:pkg_demo/wall_new',
                  file: 'data/library/wallpapers/package_embedded/pkg_demo/var_pc/wall_new.png',
                  filename: 'wall_new.png',
                  source_type: 'package_embedded',
                  origin_package_id: 'pkg_demo',
                  origin_variant_id: 'var_pc',
                },
              },
              screenshots: {},
              identity_overrides: {},
            },
          }),
          updateBeautifyVariant: async () => ({
            success: true,
            item: {
              id: 'var_pc',
              platform: 'pc',
              wallpaper_ids: ['package_embedded:pkg_demo/wall_new'],
              selected_wallpaper_id: 'package_embedded:pkg_demo/wall_new',
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedVariantId: 'var_pc',
            beautifySelectedWallpaperId: '',
            beautifySelectedScreenshotId: '',
            sharedWallpapers: [
              {
                id: 'builtin:space/stars.png',
                file: 'static/assets/wallpapers/builtin/space/stars.png',
                source_type: 'builtin',
              },
            ],
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                var_pc: {
                  id: 'var_pc',
                  platform: 'pc',
                  wallpaper_ids: [],
                  selected_wallpaper_id: '',
                },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'var_pc',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        await component.handleWallpaperFiles([{ name: 'wall_new.png' }]);

        const sharedIds = (component.$store.global.sharedWallpapers || []).map((item) => item.id).sort();
        if (sharedIds.length !== 2 || sharedIds[0] !== 'builtin:space/stars.png' || sharedIds[1] !== 'package_embedded:pkg_demo/wall_new') {
          throw new Error(`expected imported package wallpaper in shared store, got ${JSON.stringify(sharedIds)}`);
        }
        '''
    )


def test_beautify_grid_remove_current_package_prunes_package_shared_wallpapers_from_store():
    run_beautify_grid_runtime_check(
        '''
        globalThis.confirm = () => true;
        globalThis.__gridStubs = {
          deleteBeautifyPackage: async () => ({ success: true }),
          listBeautifyPackages: async () => ({ success: true, items: [] }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedVariantId: 'var_pc',
            beautifySelectedWallpaperId: 'package_embedded:pkg_demo/wall_new',
            beautifySelectedScreenshotId: '',
            sharedWallpapers: [
              {
                id: 'package_embedded:pkg_demo/wall_new',
                file: 'data/library/wallpapers/package_embedded/pkg_demo/var_pc/wall_new.png',
                source_type: 'package_embedded',
                origin_package_id: 'pkg_demo',
                origin_variant_id: 'var_pc',
              },
              {
                id: 'imported:keep-me',
                file: 'data/library/wallpapers/imported/keep-me.png',
                source_type: 'imported',
              },
            ],
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                var_pc: {
                  id: 'var_pc',
                  platform: 'pc',
                  wallpaper_ids: ['package_embedded:pkg_demo/wall_new'],
                  selected_wallpaper_id: 'package_embedded:pkg_demo/wall_new',
                },
              },
              wallpapers: {
                'package_embedded:pkg_demo/wall_new': {
                  id: 'package_embedded:pkg_demo/wall_new',
                  file: 'data/library/wallpapers/package_embedded/pkg_demo/var_pc/wall_new.png',
                  source_type: 'package_embedded',
                  origin_package_id: 'pkg_demo',
                  origin_variant_id: 'var_pc',
                },
              },
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'var_pc',
              platform: 'pc',
              wallpaper_ids: ['package_embedded:pkg_demo/wall_new'],
            },
            beautifyActiveWallpaper: {
              id: 'package_embedded:pkg_demo/wall_new',
              file: 'data/library/wallpapers/package_embedded/pkg_demo/var_pc/wall_new.png',
            },
            showToast: () => {},
          },
        };

        await component.removeCurrentPackage();

        const sharedIds = (component.$store.global.sharedWallpapers || []).map((item) => item.id);
        if (sharedIds.length !== 1 || sharedIds[0] !== 'imported:keep-me') {
          throw new Error(`expected package shared wallpapers pruned from store, got ${JSON.stringify(sharedIds)}`);
        }
        '''
    )


def test_beautify_grid_releases_preview_before_delete_request():
    run_beautify_grid_runtime_check(
        '''
        globalThis.confirm = () => true;
        const releaseCalls = [];
        globalThis.__gridStubs = {
          clearIsolatedHtmlByOwner: (...args) => releaseCalls.push(args),
          deleteBeautifyPackage: async () => {
            if (releaseCalls.length !== 1) {
              throw new Error('delete request started before preview release');
            }
            return { success: true };
          },
          listBeautifyPackages: async () => ({ success: true, items: [] }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifySelectedPackageId: 'pkg_demo',
            beautifyMobileFullscreenOpen: true,
            beautifyPreviewResetToken: 0,
            beautifyActiveDetail: null,
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        await component.removeCurrentPackage();

        if (releaseCalls.length !== 1 || releaseCalls[0][0] !== 'beautify-preview') {
          throw new Error(`expected beautify preview release, got ${JSON.stringify(releaseCalls)}`);
        }
        if (releaseCalls[0][1]?.clearShadow !== true) {
          throw new Error('preview release should clear the isolated shadow root');
        }
        if (component.$store.global.beautifyMobileFullscreenOpen !== false) {
          throw new Error('delete should close mobile fullscreen preview');
        }
        if (component.$store.global.beautifyPreviewResetToken !== 1) {
          throw new Error('delete should request a preview reset');
        }
        '''
    )


def test_state_js_keeps_beautify_store_keys():
    state_js = read_project_file('static/js/state.js')

    expected_keys = (
        'beautifyList',
        'beautifySearch',
        'beautifyPlatformFilter',
        'beautifySelectedPackageId',
        'beautifySelectedVariantId',
        'beautifySelectedWallpaperId',
        'beautifyPreviewDevice',
        'beautifyActiveDetail',
        'beautifyActiveVariant',
        'beautifyActiveWallpaper',
    )

    for key in expected_keys:
        assert_contains_any(state_js, (f'{key}:', f'"{key}":', f"'{key}':"))

    assert 'beautifyInstallFilter' not in state_js


def test_state_js_keeps_extended_beautify_store_keys():
    state_js = read_project_file('static/js/state.js')

    assert 'beautifyWorkspace: "packages"' in state_js
    assert 'beautifySelectedScreenshotId: ""' in state_js
    assert 'beautifyStageMode: "preview"' in state_js
    assert 'beautifyPackageDetailCollapsed: false' in state_js
    assert 'beautifyPackageDetailDrawerOpen: false' in state_js
    assert 'beautifyGlobalSettings: null' in state_js


def test_state_js_tracks_explicit_beautify_variant_selection_keys():
    state_js = read_project_file('static/js/state.js')

    assert 'beautifyVariantSelectionByDevice: {}' in state_js
    assert_contains_any(
        state_js,
        ('beautifyPreviewUnavailableReason: ""', "beautifyPreviewUnavailableReason: ''"),
    )


def test_state_js_keeps_mobile_beautify_fullscreen_store_keys():
    state_js = read_project_file('static/js/state.js')

    assert 'beautifyMobileFullscreenOpen: false' in state_js
    assert 'beautifyMobileDrawerOpen: false' not in state_js
    assert 'beautifyMobileDrawerTab: "variant"' not in state_js
    assert "beautifyMobileDrawerTab: 'variant'" not in state_js


def test_state_js_tracks_beautify_preview_reset_token():
    state_js = read_project_file('static/js/state.js')

    assert 'beautifyPreviewResetToken: 0' in state_js


def test_header_js_binds_beautify_search_and_mobile_upload_mode():
    header_js = read_project_file('static/js/components/header.js')

    assert_contains_any(header_js, ('"beautify"', "'beautify'"))
    assert_contains_any(header_js, ('get beautifySearch()', 'get beautifySearch ()'))
    assert_contains_any(header_js, ('return this.$store.global.beautifySearch;', 'return this.$store.global.beautifySearch || "";', "return this.$store.global.beautifySearch || '';"))
    assert_contains_any(header_js, ('set beautifySearch(val)', 'set beautifySearch (val)'))
    assert 'this.$store.global.beautifySearch = val;' in header_js
    assert_contains_any(header_js, ('new CustomEvent("request-mobile-upload")', "new CustomEvent('request-mobile-upload')"))


def test_beautify_grid_source_tracks_mobile_fullscreen_methods():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    for token in (
        'get mobileFullscreenOpen()',
        'set mobileFullscreenOpen(val)',
        'get showMobileFullscreen()',
        'isMobileBeautifyViewport()',
        'isMobileFullscreenEnabled()',
        'openMobileFullscreen(mode = this.stageMode)',
        'closeMobileFullscreen()',
    ):
        assert token in grid_source

    for removed_token in (
        'get mobileDrawerOpen()',
        'set mobileDrawerOpen(val)',
        'get mobileDrawerTab()',
        'set mobileDrawerTab(val)',
        'get mobileDrawerSummary()',
        'toggleMobileDrawer(force = null)',
        'setMobileDrawerTab(tab)',
    ):
        assert removed_token not in grid_source


def test_beautify_grid_source_tracks_mobile_preview_reset_helpers():
    grid_source = read_project_file('static/js/components/beautifyGrid.js')

    for token in (
        'hasMobilePreviewContext()',
        'requestPreviewReset()',
        'closeMobilePreviewAndReset()',
    ):
        assert token in grid_source


def test_beautify_grid_opens_mobile_fullscreen_for_stage_entry_and_screenshot_selection():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = {
          matchMedia: (query) => ({ matches: query === '(max-width: 900px)' }),
          innerWidth: 390,
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {
                shot_1: { id: 'shot_1', file: 'shot-1.png' },
              },
            },
            beautifyStageMode: 'preview',
            beautifySelectedScreenshotId: '',
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };

        component.setStageMode('preview');

        if (component.$store.global.beautifyMobileFullscreenOpen !== true) {
          throw new Error('preview stage entry should open mobile fullscreen');
        }

        component.selectScreenshot('shot_1');

        if (component.$store.global.beautifyStageMode !== 'screenshot') {
          throw new Error('selectScreenshot should switch into screenshot stage');
        }
        if (component.$store.global.beautifySelectedScreenshotId !== 'shot_1') {
          throw new Error('selected screenshot id should be preserved');
        }
        if (component.$store.global.beautifyMobileFullscreenOpen !== true) {
          throw new Error('screenshot selection should keep mobile fullscreen open');
        }
        if (component.$store.global.beautifyStageMode !== 'screenshot') {
          throw new Error('mobile fullscreen should keep screenshot stage active');
        }
        '''
    )


def test_beautify_grid_supports_settings_fullscreen_and_resets_on_mobile_close():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = {
          matchMedia: () => ({ matches: true }),
          innerWidth: 390,
          addEventListener: () => {},
        };

        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'beautify',
            beautifyWorkspace: 'settings',
            beautifyStageMode: 'preview',
            beautifyPreviewResetToken: 0,
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };

        if (component.isMobileFullscreenEnabled() !== true) {
          throw new Error('settings workspace should allow mobile fullscreen preview');
        }

        component.openMobileFullscreen('preview');

        if (component.$store.global.beautifyMobileFullscreenOpen !== true) {
          throw new Error('settings preview should open the mobile fullscreen shell');
        }
        if (component.$store.global.beautifyStageMode !== 'preview') {
          throw new Error('settings preview should keep preview stage mode');
        }

        component.closeMobilePreviewAndReset();

        if (component.$store.global.beautifyMobileFullscreenOpen !== false) {
          throw new Error('mobile fullscreen should close on reset');
        }
        if (component.$store.global.beautifyPreviewResetToken !== 1) {
          throw new Error('closing mobile preview should increment the preview reset token');
        }
        '''
    )


def test_beautify_grid_aligns_settings_preview_device_with_current_viewport():
    run_beautify_grid_runtime_check(
        '''
        const createComponent = (matches, initialDevice) => {
          globalThis.window = {
            matchMedia: () => ({ matches }),
            innerWidth: matches ? 390 : 1280,
            addEventListener: () => {},
          };

          const component = module.default();
          component.$store = {
            global: {
              currentMode: 'beautify',
              beautifyWorkspace: 'packages',
              beautifyStageMode: 'preview',
              beautifyPreviewDevice: initialDevice,
              beautifyMobileFullscreenOpen: false,
              beautifyActiveDetail: {
                id: 'pkg-1',
                variants: {
                  pc: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
                  mobile: { id: 'mobile', platform: 'mobile', wallpaper_ids: [] },
                },
                wallpapers: {},
                screenshots: {},
                identity_overrides: {},
              },
              beautifyActiveVariant: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
              beautifyActiveWallpaper: null,
              showToast: () => {},
            },
          };
          return component;
        };

        const mobileComponent = createComponent(true, 'pc');
        mobileComponent.switchBeautifyWorkspace('settings');
        if (mobileComponent.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error('settings workspace should align preview device to mobile on mobile viewport');
        }

        const desktopComponent = createComponent(false, 'mobile');
        desktopComponent.switchBeautifyWorkspace('settings');
        if (desktopComponent.$store.global.beautifyPreviewDevice !== 'pc') {
          throw new Error('settings workspace should align preview device to pc on desktop viewport');
        }
        '''
    )


def test_beautify_grid_closes_mobile_fullscreen_when_switching_to_settings_workspace():
    run_beautify_grid_runtime_check(
        '''
        let settingsFetches = 0;
        globalThis.__gridStubs = {
          getBeautifySettings: async () => {
            settingsFetches += 1;
            return { success: true, item: null };
          },
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyMobileFullscreenOpen: true,
            showToast: () => {},
          },
        };

        component.switchBeautifyWorkspace('settings');
        await Promise.resolve();

        if (component.$store.global.beautifyWorkspace !== 'settings') {
          throw new Error('workspace should change to settings');
        }
        if (component.$store.global.beautifyMobileFullscreenOpen !== false) {
          throw new Error('fullscreen should close when entering settings workspace');
        }
        if (settingsFetches !== 1) {
          throw new Error(`expected one settings refetch, got ${settingsFetches}`);
        }
        '''
    )


def test_beautify_grid_switching_back_to_packages_resyncs_mobile_only_preview_shell():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'pc',
            beautifyMobileFullscreenOpen: false,
            beautifyActiveDetail: {
              id: 'pkg_mobile_only',
              variants: {
                mobile: { id: 'mobile', platform: 'mobile', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'mobile', platform: 'mobile', wallpaper_ids: [] },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.switchBeautifyWorkspace('packages');

        if (component.$store.global.beautifyWorkspace !== 'packages') {
          throw new Error('workspace should change back to packages');
        }
        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`expected mobile-only package preview shell to realign to mobile, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        '''
    )


def test_beautify_grid_dual_variant_preserves_existing_mobile_preview_shell():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifyMobileFullscreenOpen: false,
            beautifyActiveDetail: {
              id: 'pkg_dual',
              variants: {
                dual: { id: 'dual', platform: 'dual', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.applyActiveVariant({
          id: 'dual',
          platform: 'dual',
          wallpaper_ids: [],
        });

        if (component.$store.global.beautifyActiveVariant?.id !== 'dual') {
          throw new Error('expected dual variant to become active');
        }
        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`expected valid mobile shell to be preserved for dual variant, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        '''
    )


def test_beautify_grid_prior_dual_shell_falls_back_to_pc_when_next_package_has_split_variants_only():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'dual',
            beautifyMobileFullscreenOpen: false,
            beautifyActiveDetail: {
              id: 'pkg_split',
              variants: {
                pc: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
                mobile: { id: 'mobile', platform: 'mobile', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.switchBeautifyWorkspace('packages');

        if (component.$store.global.beautifyPreviewDevice !== 'pc') {
          throw new Error(`expected prior dual shell to fall back to pc when next package only has split pc/mobile variants, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        '''
    )


def test_beautify_grid_split_package_dual_target_remains_reachable_on_desktop():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 1280, addEventListener: () => {} };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {
              pc: 'pc_only',
              mobile: 'mobile_only',
            },
            beautifySelectedVariantId: 'pc_only',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_split',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_only: { id: 'mobile_only', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        await component.previewPlatform('dual');

        if (component.$store.global.beautifyPreviewDevice !== 'dual') {
          throw new Error(`desktop split package should still enter dual target, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'pc_only') {
          throw new Error(`desktop split package should fall back to a remembered compatible pc variant, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error(`desktop split package dual target should stay available, got ${component.$store.global.beautifyPreviewUnavailableReason}`);
        }
        '''
    )


def test_beautify_grid_split_package_dual_target_uses_mobile_fallback_on_mobile_viewport():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 390, addEventListener: () => {} };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {
              pc: 'pc_only',
              mobile: 'mobile_only',
            },
            beautifySelectedVariantId: 'pc_only',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_split',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_only: { id: 'mobile_only', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        await component.previewPlatform('dual');

        if (component.$store.global.beautifyPreviewDevice !== 'dual') {
          throw new Error(`mobile split package should still enter dual target, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_only') {
          throw new Error(`mobile split package should not fall back to pc for dual target, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error(`mobile split package dual target should use mobile fallback without unavailable state, got ${component.$store.global.beautifyPreviewUnavailableReason}`);
        }
        '''
    )


def test_beautify_grid_switching_back_to_packages_realigns_active_variant_with_mobile_shell():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'mobile',
            beautifyMobileFullscreenOpen: false,
            beautifyVariantSelectionByDevice: {
              mobile: 'mobile_b',
            },
            beautifyActiveDetail: {
              id: 'pkg_split',
              variants: {
                pc: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
                mobile: { id: 'mobile', platform: 'mobile', wallpaper_ids: [] },
                mobile_b: { id: 'mobile_b', platform: 'mobile', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'pc', platform: 'pc', wallpaper_ids: [] },
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.switchBeautifyWorkspace('packages');

        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`expected package workspace to preserve mobile preview shell, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_b') {
          throw new Error(`expected package workspace to reactivate the remembered mobile variant for the mobile shell, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        '''
    )


def test_beautify_grid_exposes_package_detail_collapse_state_and_toggle_helpers():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyPackageDetailCollapsed: false,
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: { id: 'pkg_v06' },
          },
        };

        if (component.packageDetailCollapsed !== false) {
          throw new Error('expected default collapse state to be false');
        }

        component.togglePackageDetailCollapsed();
        if (component.packageDetailCollapsed !== true) {
          throw new Error('toggle should collapse package details');
        }

        component.openPackageDetailDrawer();
        if (component.packageDetailDrawerOpen !== true) {
          throw new Error('openPackageDetailDrawer should open the overlay drawer');
        }
        '''
    )


def test_beautify_grid_forces_package_detail_drawer_closed_when_workspace_switches_to_settings():
    run_beautify_grid_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: { id: 'pkg_v06' },
          },
        };
        component.closeMobileFullscreen = () => {};
        component.closeMobilePreviewAndReset = () => {};
        component.alignSettingsPreviewDeviceToViewport = () => {};
        component.fetchGlobalSettings = () => {};
        component.resolvePackagePreviewPlatform = () => 'pc';
        component.findVariantForPreviewPlatform = () => null;

        component.switchBeautifyWorkspace('settings');

        if (component.$store.global.beautifyWorkspace !== 'settings') {
          throw new Error('expected workspace switch to settings');
        }
        if (component.packageDetailDrawerOpen !== false) {
          throw new Error('settings workspace should close the package detail drawer');
        }
        '''
    )


def test_beautify_grid_preserves_package_detail_collapse_and_closes_drawer_when_switching_packages():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          getBeautifyPackage: async (packageId) => ({
            success: true,
            item: {
              id: packageId,
              variants: {
                pc: { id: `variant_${packageId}`, platform: 'pc', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifySelectedPackageId: 'pkg_a',
            beautifySelectedVariantId: 'variant_pkg_a',
            beautifySelectedWallpaperId: '',
            beautifyPreviewDevice: 'pc',
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyActiveDetail: {
              id: 'pkg_a',
              variants: {
                pc: { id: 'variant_pkg_a', platform: 'pc', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'variant_pkg_a', platform: 'pc', wallpaper_ids: [] },
            showToast: () => {},
          },
        };

        await component.selectPackage('pkg_b');

        if (component.selectedPackageId !== 'pkg_b') {
          throw new Error(`expected package switch to pkg_b, got ${component.selectedPackageId}`);
        }
        if (component.packageDetailCollapsed !== true) {
          throw new Error('package switch should preserve the user-owned collapsed state');
        }
        if (component.packageDetailDrawerOpen !== false) {
          throw new Error('package switch should still close the stale detail drawer');
        }
        '''
    )


def test_beautify_grid_closes_package_detail_drawer_when_reloading_same_package_detail():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          getBeautifyPackage: async (packageId) => ({
            success: true,
            item: {
              id: packageId,
              variants: {
                pc: { id: 'variant_pkg_a', platform: 'pc', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifySelectedPackageId: 'pkg_a',
            beautifySelectedVariantId: 'variant_pkg_a',
            beautifySelectedWallpaperId: '',
            beautifyPreviewDevice: 'pc',
            beautifySelectedScreenshotId: '',
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyActiveDetail: {
              id: 'pkg_a',
              variants: {
                pc: { id: 'variant_pkg_a', platform: 'pc', wallpaper_ids: [] },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: { id: 'variant_pkg_a', platform: 'pc', wallpaper_ids: [] },
            showToast: () => {},
          },
        };

        await component.selectPackage('pkg_a', { preserveSelection: true });

        if (component.packageDetailCollapsed !== true) {
          throw new Error('same-package refresh should preserve collapse state');
        }
        if (component.packageDetailDrawerOpen !== false) {
          throw new Error('same-package refresh should close the stale detail drawer session');
        }
        '''
    )


def test_beautify_grid_closes_stale_package_detail_drawer_on_mobile_resize_transition():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = {
          matchMedia: () => ({ matches: true }),
          innerWidth: 390,
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };

        component.syncMobileFullscreenState();

        if (component.packageDetailDrawerOpen !== false) {
          throw new Error('mobile viewport transition should close stale desktop detail drawer state');
        }
        if (component.packageDetailCollapsed !== true) {
          throw new Error('mobile viewport transition should preserve collapsed state');
        }
        '''
    )


def test_beautify_grid_preserves_current_package_detail_rail_when_next_package_fetch_fails():
    run_beautify_grid_runtime_check(
        '''
        globalThis.__gridStubs = {
          getBeautifyPackage: async () => ({ success: false, error: 'load failed' }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifySelectedPackageId: 'pkg_a',
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyActiveDetail: {
              id: 'pkg_a',
              variants: {},
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            showToast: () => {},
          },
        };

        const loaded = await component.selectPackage('pkg_b');

        if (loaded !== false) {
          throw new Error('failed package fetch should return false');
        }
        if (component.selectedPackageId !== 'pkg_a') {
          throw new Error(`failed package switch should preserve current package id, got ${component.selectedPackageId}`);
        }
        if (component.packageDetailCollapsed !== true) {
          throw new Error('failed package switch should preserve current collapse state');
        }
        if (component.packageDetailDrawerOpen !== true) {
          throw new Error('failed package switch should preserve current drawer session');
        }
        '''
    )


def test_beautify_grid_uses_reactive_window_width_for_mobile_viewport_checks():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = {
          matchMedia: () => ({ matches: false }),
          innerWidth: 1280,
        };

        const component = module.default();
        component.$store = {
          global: {
            windowWidth: 860,
          },
        };

        if (component.isMobileBeautifyViewport() !== true) {
          throw new Error('reactive global windowWidth should drive mobile viewport checks');
        }

        component.$store.global.windowWidth = 1280;
        if (component.isMobileBeautifyViewport() !== false) {
          throw new Error('viewport checks should react when global windowWidth changes back to desktop');
        }
        '''
    )


def test_beautify_grid_opens_mobile_fullscreen_for_screenshot_empty_state_without_images():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = {
          matchMedia: () => ({ matches: true }),
          innerWidth: 390,
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {},
              wallpapers: {},
              screenshots: {},
            },
            beautifyStageMode: 'preview',
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };

        component.setStageMode('screenshot');

        if (component.$store.global.beautifyStageMode !== 'screenshot') {
          throw new Error('screenshot mode should be preserved even without images');
        }
        if (component.$store.global.beautifyMobileFullscreenOpen !== true) {
          throw new Error('mobile fullscreen should still open for screenshot empty state');
        }
        if (component.$store.global.beautifyStageMode !== 'screenshot') {
          throw new Error('screenshot empty state should preserve screenshot mode');
        }
        '''
    )


def test_beautify_grid_clears_mobile_fullscreen_when_leaving_beautify_mode():
    run_beautify_grid_runtime_check(
        '''
        const watchers = new Map();
        globalThis.window = {
          addEventListener: () => {},
        };
        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'beautify',
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: { id: 'pkg_demo', variants: {}, wallpapers: {}, screenshots: {} },
            beautifyPackageDetailCollapsed: true,
            beautifyPackageDetailDrawerOpen: true,
            beautifyMobileFullscreenOpen: true,
            showToast: () => {},
          },
        };
        component.$watch = (key, callback) => watchers.set(key, callback);

        component.init();

        const modeWatcher = watchers.get('$store.global.currentMode');
        if (typeof modeWatcher !== 'function') {
          throw new Error('expected currentMode watcher');
        }

        component.$store.global.currentMode = 'cards';
        modeWatcher('cards');

        if (component.$store.global.beautifyMobileFullscreenOpen !== false) {
          throw new Error('fullscreen should clear when leaving beautify mode');
        }
        if (component.$store.global.beautifyPreviewResetToken !== 1) {
          throw new Error('leaving beautify mode should trigger preview reset when fullscreen was open');
        }
        if (component.packageDetailDrawerOpen !== false) {
          throw new Error('leaving beautify mode should close stale package detail drawer state');
        }
        '''
    )


def test_beautify_grid_clears_stale_mobile_fullscreen_on_desktop_resize():
    run_beautify_grid_runtime_check(
        '''
        const listeners = new Map();
        globalThis.window = {
          matchMedia: () => ({ matches: false }),
          innerWidth: 1280,
          addEventListener: (name, callback) => listeners.set(name, callback),
        };

        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'beautify',
            beautifyWorkspace: 'packages',
            beautifyActiveDetail: { id: 'pkg_demo', variants: {}, wallpapers: {}, screenshots: {} },
            beautifyMobileFullscreenOpen: true,
            beautifyPreviewResetToken: 0,
            showToast: () => {},
          },
        };
        component.$watch = () => {};

        component.init();

        const resizeHandler = listeners.get('resize');
        if (typeof resizeHandler !== 'function') {
          throw new Error('expected resize handler registration');
        }

        resizeHandler();

        if (component.$store.global.beautifyMobileFullscreenOpen !== false) {
          throw new Error('desktop resize should clear stale mobile fullscreen state');
        }
        if (component.$store.global.beautifyPreviewResetToken !== 1) {
          throw new Error('desktop resize should trigger preview reset when stale fullscreen closes');
        }
        '''
    )


def test_layout_or_sidebar_keeps_beautify_mode_refresh_and_upload_routing():
    layout_js = read_project_file('static/js/components/layout.js')
    sidebar_js = read_project_file('static/js/components/sidebar.js')

    assert_contains_any(layout_js, ('mode !== "beautify"', "mode !== 'beautify'"))
    assert_contains_any(layout_js, ('mode === "beautify"', "mode === 'beautify'"))
    assert_contains_any(layout_js, ('new CustomEvent("refresh-beautify-list")', "new CustomEvent('refresh-beautify-list')"))

    assert_contains_any(sidebar_js, ('const mode = this.currentMode;',))
    assert_contains_any(sidebar_js, ('mode === "beautify"', "mode === 'beautify'"))
    assert_contains_any(sidebar_js, ('window.stUploadBeautifyThemeFiles(files);',))
    assert_contains_any(sidebar_js, ('window.dispatchEvent(new CustomEvent("refresh-beautify-list"));', "window.dispatchEvent(new CustomEvent('refresh-beautify-list'));"))


def test_layout_switch_mode_closes_mobile_sidebar_before_entering_beautify():
    run_layout_runtime_check(
        '''
        const events = [];
        globalThis.document = {
          body: {
            style: {
              overflow: 'hidden',
            },
          },
        };
        globalThis.window = {
          dispatchEvent: (event) => events.push(event.type),
        };

        const component = module.default();
        component.$store = {
          global: {
            deviceType: 'mobile',
            visibleSidebar: true,
            currentMode: 'cards',
            viewState: {
              searchQuery: 'demo',
              filterTags: ['tag_a'],
              excludedTags: ['tag_b'],
              filterCategory: 'folder/demo',
              favFilter: 'fav',
              selectedIds: [],
              draggedCards: [],
              draggedFolder: null,
            },
          },
        };

        component.switchMode('beautify');

        if (component.$store.global.currentMode !== 'beautify') {
          throw new Error('expected switchMode to enter beautify');
        }
        if (component.$store.global.visibleSidebar !== false) {
          throw new Error('mobile mode switch should close the sidebar');
        }
        if (document.body.style.overflow !== '') {
          throw new Error('mobile mode switch should clear body scroll lock');
        }
        if (!events.includes('refresh-beautify-list')) {
          throw new Error('beautify mode switch should still refresh the beautify list');
        }
        '''
    )


def test_beautify_preview_document_module_exports_document_builder_contract():
    module_source = read_project_file('static/js/components/beautifyPreviewDocument.js')

    assert 'export function buildBeautifyPreviewDocument(' in module_source
    assert 'export function buildBeautifyPreviewThemeVars(' in module_source
    assert 'export function buildBeautifyPreviewSampleMarkup(' in module_source
    assert 'function buildPreviewBehaviorScript(' in module_source


def test_beautify_preview_frame_uses_render_isolated_html_and_preview_document_builder():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'renderIsolatedHtml' in source
    assert 'clearIsolatedHtml' in source
    assert 'buildBeautifyPreviewDocument' in source
    assert 'buildBeautifyPreviewAssetUrl' in source
    assert 'customCssMarkup()' not in source
    assert 'function resolvePreviewRenderMinHeight(platform)' in source
    assert 'return platform === "mobile" ? 420 : 520;' in source or "return platform === 'mobile' ? 420 : 520;" in source
    assert 'minHeight: resolvePreviewRenderMinHeight(state.platform),' in source
    assert 'maxHeight:' not in source


def test_beautify_preview_frame_prefers_package_assets_then_global_settings():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              identity_overrides: {
                character: { name: '包角色', avatar_file: 'data/library/beautify/packages/pkg_demo/avatars/character.png' },
                user: { name: '', avatar_file: '' },
              },
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {
              preview_wallpaper_id: 'global-wallpaper',
              wallpaper: {
                id: 'global-wallpaper',
                file: 'data/library/wallpapers/shared/wallpaper.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: 'data/library/beautify/global/avatars/character.png' },
                user: { name: '全局用户', avatar_file: 'data/library/beautify/global/avatars/user.png' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== 'data/library/wallpapers/shared/wallpaper.png') throw new Error('missing global wallpaper fallback');
        if (state.identities.character.name !== '包角色') throw new Error('package override should win');
        if (state.identities.user.name !== '全局用户') throw new Error('global user fallback should win');
        '''
    )


def test_beautify_preview_frame_prefers_selected_package_wallpaper_over_global_fallback():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {
                wall_pkg: {
                  id: 'wall_pkg',
                  file: 'data/library/wallpapers/shared/package.png',
                },
              },
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: 'wall_pkg',
            },
            beautifyActiveWallpaper: {
              id: 'wall_stale',
              file: 'data/library/wallpapers/shared/stale-active.png',
            },
            beautifyGlobalSettings: {
              preview_wallpaper_id: 'wall_global',
              wallpaper: {
                id: 'wall_global',
                file: 'data/library/wallpapers/shared/global.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== 'data/library/wallpapers/shared/package.png') {
          throw new Error('selected package wallpaper should win');
        }
        '''
    )


def test_beautify_preview_frame_uses_effective_bound_package_wallpaper_when_persisted_variant_selection_is_empty():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifySelectedWallpaperId: 'package_embedded:04a85e07a1e6',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {
                'package_embedded:04a85e07a1e6': {
                  id: 'package_embedded:04a85e07a1e6',
                  file: 'data/library/wallpapers/package_embedded/pkg_crying/var_mobile/demo.webp',
                },
              },
            },
            beautifyActiveVariant: {
              theme_data: { name: 'crying' },
              wallpaper_ids: ['package_embedded:04a85e07a1e6'],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: {
              id: 'package_embedded:04a85e07a1e6',
              file: 'data/library/wallpapers/package_embedded/pkg_crying/var_mobile/demo.webp',
            },
            beautifyGlobalSettings: {
              wallpaper: {
                id: 'wall_global',
                file: 'static/assets/wallpapers/builtin/fallback.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== 'data/library/wallpapers/package_embedded/pkg_crying/var_mobile/demo.webp') {
          throw new Error(`expected effective bound package wallpaper to win, got ${state.wallpaperUrl}`);
        }
        '''
    )


def test_beautify_preview_frame_resolve_preview_state_includes_host_owned_active_scene():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveScene: 'flirty',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: '',
            },
            beautifyGlobalSettings: {
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.activeScene !== 'flirty') {
          throw new Error(`expected host-owned active scene to flow into preview state, got ${state.activeScene}`);
        }
        '''
    )


def test_beautify_preview_frame_passes_trimmed_package_meta_to_preview_document_builder():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              name: '  Warm Demo  ',
              tags: [' night ', 'oled', '', '   ', ' dusk', 'sunrise ', ' cozy ', 'mono', 'contrast', ' late'],
              notes: '  drawer preview notes  ',
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };
        component.$refs = { previewHost: host };

        component.isPreviewLoaded = true;
        component.renderPreview();

        const renderEvent = host.__events.find((entry) => entry.type === 'render');
        if (!renderEvent) {
          throw new Error('expected preview render event');
        }
        const payload = JSON.parse(renderEvent.options.htmlPayload || '{}');
        if (payload.detail?.packageName !== 'Warm Demo') {
          throw new Error(`expected trimmed packageName, got ${payload.detail?.packageName}`);
        }
        if (JSON.stringify(payload.detail?.tags || []) !== JSON.stringify(['night', 'oled', 'dusk', 'sunrise', 'cozy', 'mono', 'contrast', 'late'])) {
          throw new Error(`expected trimmed tags, got ${JSON.stringify(payload.detail?.tags || [])}`);
        }
        if (payload.detail?.notes !== 'drawer preview notes') {
          throw new Error(`expected trimmed notes, got ${payload.detail?.notes}`);
        }
      '''
    )


def test_beautify_preview_frame_resolve_preview_state_uses_viewport_aware_shell_for_dual_target():
    run_beautify_preview_frame_runtime_check(
        '''
        globalThis.window = { innerWidth: 390 };

        const mobileComponent = module.default();
        mobileComponent.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'dual',
            windowWidth: 390,
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              id: 'mobile_fallback',
              platform: 'mobile',
              theme_data: { name: 'Mobile Fallback' },
              selected_wallpaper_id: '',
            },
            beautifyGlobalSettings: {
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const mobileState = mobileComponent.resolvePreviewState();
        if (mobileState.platform !== 'mobile') {
          throw new Error(`dual target on mobile viewport should render mobile shell, got ${mobileState.platform}`);
        }

        globalThis.window.innerWidth = 1280;

        const desktopComponent = module.default();
        desktopComponent.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'dual',
            windowWidth: 1280,
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              id: 'pc_fallback',
              platform: 'pc',
              theme_data: { name: 'PC Fallback' },
              selected_wallpaper_id: '',
            },
            beautifyGlobalSettings: {
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const desktopState = desktopComponent.resolvePreviewState();
        if (desktopState.platform !== 'pc') {
          throw new Error(`dual target on desktop viewport should render pc shell, got ${desktopState.platform}`);
        }
        '''
    )


def test_beautify_preview_frame_reuses_document_scene_catalog_for_host_switcher():
    preview_frame_source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'import {' in preview_frame_source
    assert 'DEFAULT_PREVIEW_SCENE_ID' in preview_frame_source
    assert 'PREVIEW_SCENE_OPTIONS' in preview_frame_source
    assert 'const HOST_PREVIEW_SCENES' not in preview_frame_source


def test_beautify_grid_mobile_viewport_marks_pc_only_variant_preview_unavailable_when_selected():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 390, addEventListener: () => {} };

        const component = module.default();
        component.$store = {
          global: {
            beautifyPreviewDevice: 'mobile',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {},
            beautifySelectedVariantId: '',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            showToast: () => {},
          },
        };

        component.selectVariant('pc_only');

        if (component.$store.global.beautifySelectedVariantId !== 'pc_only') {
          throw new Error('pc-only variant should still be selected for management');
        }
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('mobile selection of pc-only variant should mark preview unavailable');
        }
        if (component.$store.global.beautifyPreviewUnavailableReason.includes('切换到移动端')) {
          throw new Error(`mobile-target unavailable copy should not tell the user to switch to mobile, got ${component.$store.global.beautifyPreviewUnavailableReason}`);
        }
        '''
    )


def test_beautify_grid_desktop_to_mobile_resize_realigns_to_mobile_capable_preview_target():
    run_beautify_grid_runtime_check(
        '''
        const listeners = new Map();
        globalThis.window = {
          innerWidth: 1280,
          addEventListener: (name, callback) => listeners.set(name, callback),
        };

        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'beautify',
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {
              mobile: 'mobile_only',
            },
            beautifySelectedVariantId: 'pc_only',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_split',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_only: { id: 'mobile_only', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'pc_only',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };
        component.$watch = () => {};

        component.init();

        const resizeHandler = listeners.get('resize');
        if (typeof resizeHandler !== 'function') {
          throw new Error('expected resize handler registration');
        }

        globalThis.window.innerWidth = 390;
        resizeHandler();

        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`desktop-to-mobile resize should realign preview target to mobile when a mobile-capable fallback exists, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_only') {
          throw new Error(`desktop-to-mobile resize should activate the mobile-capable fallback, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error(`desktop-to-mobile resize should clear unavailable state when a mobile-capable fallback exists, got ${component.$store.global.beautifyPreviewUnavailableReason}`);
        }
        '''
    )


def test_beautify_grid_recomputes_preview_unavailable_on_desktop_to_mobile_resize_transition():
    run_beautify_grid_runtime_check(
        '''
        const listeners = new Map();
        globalThis.window = {
          innerWidth: 1280,
          addEventListener: (name, callback) => listeners.set(name, callback),
        };

        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'beautify',
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {},
            beautifySelectedVariantId: 'pc_only',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_pc_only',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'pc_only',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyMobileFullscreenOpen: false,
            showToast: () => {},
          },
        };
        component.$watch = () => {};

        component.init();

        const resizeHandler = listeners.get('resize');
        if (typeof resizeHandler !== 'function') {
          throw new Error('expected resize handler registration');
        }

        globalThis.window.innerWidth = 390;
        resizeHandler();

        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`desktop-to-mobile resize should realign preview target to mobile, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('desktop-to-mobile resize should recompute preview unavailable for pc-only variant');
        }
        '''
    )


def test_beautify_grid_recomputes_preview_unavailable_reason_across_device_workspace_and_package_flows():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 1280, addEventListener: () => {} };
        globalThis.__gridStubs = {
          getBeautifyPackage: async (packageId) => ({
            success: true,
            item: {
              id: packageId,
              variants: {
                ...(packageId === 'pkg_pc_only'
                  ? {
                      pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                    }
                  : {
                      pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                      mobile_only: { id: 'mobile_only', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
                    }),
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
          getBeautifySettings: async () => ({ success: true, item: null }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {},
            beautifySelectedPackageId: 'pkg_demo',
            beautifySelectedVariantId: '',
            beautifySelectedWallpaperId: '',
            beautifySelectedScreenshotId: '',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_only: { id: 'mobile_only', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {},
            showToast: () => {},
          },
        };
        component.syncPackageIdentityFields = () => {};
        component.fetchGlobalSettings = () => {};
        component.closePackageDetailDrawer = () => {};
        component.closeMobilePreviewAndReset = () => {};
        component.closeMobileFullscreen = () => {};

        component.$store.global.beautifyPreviewDevice = 'mobile';
        component.selectVariant('pc_only');
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('selecting pc-only variant on mobile preview target should set unavailable reason even on desktop viewport');
        }

        await component.previewPlatform('mobile');
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('switching preview target to a compatible mobile variant should clear unavailable reason');
        }

        await component.previewPlatform('pc');
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('switching preview target to pc should keep pc-only variant preview available');
        }

        component.$store.global.beautifyPreviewDevice = 'mobile';
        component.selectVariant('pc_only');
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('pc-only variant should become unavailable again after reselecting on mobile target');
        }

        component.switchBeautifyWorkspace('settings');
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('settings workspace should clear package-specific preview unavailable reason');
        }

        component.$store.global.beautifyPreviewDevice = 'mobile';
        await component.selectPackage('pkg_demo');
        component.selectVariant('pc_only');
        component.switchBeautifyWorkspace('settings');
        component.switchBeautifyWorkspace('packages');
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('returning to package workspace should recompute away stale unavailable reason when a compatible mobile variant exists');
        }
        if (component.$store.global.beautifyPreviewDevice !== 'pc') {
          throw new Error(`expected settings round-trip on desktop viewport to realign effective preview target to pc, got ${component.$store.global.beautifyPreviewDevice}`);
        }

        component.$store.global.beautifyPreviewDevice = 'pc';
        await component.selectPackage('pkg_pc_only', { preserveSelection: true });
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('reloading package with pc target should clear unavailable reason for pc-only variant');
        }

        component.$store.global.beautifyPreviewDevice = 'mobile';
        component.$store.global.beautifySelectedVariantId = 'pc_only';
        await component.selectPackage('pkg_demo', { preserveSelection: true });
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('reloading package with mobile target and preserved pc-only selection should recompute unavailable reason');
        }
        '''
    )


def test_beautify_grid_mobile_viewport_keeps_mobile_preview_target_unavailable_for_pc_only_package_reload_and_workspace_return():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 390, addEventListener: () => {} };
        globalThis.__gridStubs = {
          getBeautifyPackage: async (packageId) => ({
            success: true,
            item: {
              id: packageId,
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
          getBeautifySettings: async () => ({ success: true, item: null }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {},
            beautifySelectedPackageId: 'pkg_pc_only',
            beautifySelectedVariantId: 'pc_only',
            beautifySelectedWallpaperId: '',
            beautifySelectedScreenshotId: '',
            beautifyActiveDetail: {
              id: 'pkg_pc_only',
              variants: {
                pc_only: { id: 'pc_only', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'pc_only',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {},
            showToast: () => {},
          },
        };
        component.syncPackageIdentityFields = () => {};
        component.fetchGlobalSettings = () => {};
        component.closePackageDetailDrawer = () => {};
        component.closeMobilePreviewAndReset = () => {};
        component.closeMobileFullscreen = () => {};

        await component.selectPackage('pkg_pc_only', { preserveSelection: true });
        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`mobile package reload should preserve mobile preview target, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('mobile package reload should keep preview unavailable for pc-only package');
        }

        component.switchBeautifyWorkspace('settings');
        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`mobile settings workspace should preserve mobile preview target, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('settings workspace should clear package-specific preview unavailable reason');
        }

        component.switchBeautifyWorkspace('packages');
        if (component.$store.global.beautifyPreviewDevice !== 'mobile') {
          throw new Error(`mobile workspace return should preserve mobile preview target, got ${component.$store.global.beautifyPreviewDevice}`);
        }
        if (!component.$store.global.beautifyPreviewUnavailableReason) {
          throw new Error('mobile workspace return should restore unavailable state for pc-only package');
        }
        '''
    )


def test_beautify_grid_preview_platform_change_preserves_compatible_selected_variant():
    run_beautify_grid_runtime_check(
        '''
        globalThis.window = { innerWidth: 1280, addEventListener: () => {} };
        let editedPlatform = 'dual';
        globalThis.__gridStubs = {
          updateBeautifyVariant: async ({ platform }) => {
            editedPlatform = platform;
            return { success: true, item: { id: 'dual_a', platform } };
          },
          getBeautifyPackage: async () => ({
            success: true,
            item: {
              id: 'pkg_demo',
              variants: {
                pc_a: { id: 'pc_a', name: 'PC A', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                pc_b: { id: 'pc_b', name: 'PC B', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_a: { id: 'mobile_a', name: 'Mobile A', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
                dual_a: { id: 'dual_a', name: 'Dual A', platform: editedPlatform, wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
          }),
        };

        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifySelectedPackageId: 'pkg_demo',
            beautifyPreviewDevice: 'pc',
            beautifyPreviewUnavailableReason: '',
            beautifyVariantSelectionByDevice: {
              pc: 'pc_b',
              mobile: 'mobile_a',
              dual: 'dual_a',
            },
            beautifySelectedVariantId: 'pc_b',
            beautifySelectedWallpaperId: '',
            beautifyActiveDetail: {
              id: 'pkg_demo',
              variants: {
                pc_a: { id: 'pc_a', name: 'PC A', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                pc_b: { id: 'pc_b', name: 'PC B', platform: 'pc', wallpaper_ids: [], selected_wallpaper_id: '' },
                mobile_a: { id: 'mobile_a', name: 'Mobile A', platform: 'mobile', wallpaper_ids: [], selected_wallpaper_id: '' },
                dual_a: { id: 'dual_a', name: 'Dual A', platform: 'dual', wallpaper_ids: [], selected_wallpaper_id: '' },
              },
              wallpapers: {},
              screenshots: {},
              identity_overrides: {},
            },
            beautifyActiveVariant: {
              id: 'pc_b',
              name: 'PC B',
              platform: 'pc',
              wallpaper_ids: [],
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {},
            showToast: () => {},
          },
        };
        component.closePackageDetailDrawer = () => {};
        component.closeMobilePreviewAndReset = () => {};
        component.closeMobileFullscreen = () => {};
        component.fetchGlobalSettings = () => {};

        await component.previewPlatform('pc');
        if (component.$store.global.beautifyActiveVariant?.id !== 'pc_b') {
          throw new Error(`expected compatible selected pc variant to stay active, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        await component.previewPlatform('mobile');
        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_a') {
          throw new Error(`expected remembered mobile variant on mobile target, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        component.$store.global.beautifySelectedVariantId = 'dual_a';
        component.$store.global.beautifyActiveVariant = component.$store.global.beautifyActiveDetail.variants.dual_a;

        await component.previewPlatform('pc');
        if (component.$store.global.beautifyActiveVariant?.id !== 'dual_a') {
          throw new Error(`expected compatible dual variant to remain selected on pc target, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        await component.previewPlatform('mobile');
        if (component.$store.global.beautifyActiveVariant?.id !== 'dual_a') {
          throw new Error(`expected compatible dual variant to remain selected on mobile target, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        component.$store.global.beautifyVariantSelectionByDevice = {
          pc: 'pc_b',
          mobile: 'mobile_a',
        };
        component.selectVariant('dual_a');
        if (component.$store.global.beautifyVariantSelectionByDevice.pc !== 'pc_b') {
          throw new Error(`selecting dual variant should not overwrite remembered pc selection, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.mobile !== 'mobile_a') {
          throw new Error(`selecting dual variant should not overwrite remembered mobile selection, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.dual !== 'dual_a') {
          throw new Error(`selecting dual variant should remember the dual slot, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }

        component.switchBeautifyWorkspace('settings');
        component.switchBeautifyWorkspace('packages');
        if (component.$store.global.beautifyActiveVariant?.id !== 'dual_a') {
          throw new Error(`expected settings return to preserve compatible dual selection, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        component.$store.global.beautifySelectedVariantId = 'pc_b';
        component.$store.global.beautifyActiveVariant = component.$store.global.beautifyActiveDetail.variants.pc_b;
        component.$store.global.beautifyPreviewDevice = 'pc';

        await component.previewPlatform('dual');
        if (component.$store.global.beautifyActiveVariant?.id !== 'dual_a') {
          throw new Error(`expected dual target to resolve a dual-capable variant, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }
        if (component.$store.global.beautifyPreviewDevice !== 'dual') {
          throw new Error(`expected preview target to remain dual, got ${component.$store.global.beautifyPreviewDevice}`);
        }

        component.$store.global.beautifyPreviewDevice = 'mobile';
        component.$store.global.beautifySelectedVariantId = 'dual_a';
        component.$store.global.beautifyActiveVariant = component.$store.global.beautifyActiveDetail.variants.dual_a;
        component.$store.global.beautifyVariantSelectionByDevice = {
          pc: 'pc_b',
          mobile: 'mobile_a',
          dual: 'dual_a',
        };

        await component.updateCurrentVariantPlatform('pc');

        if (component.$store.global.beautifyVariantSelectionByDevice.pc !== 'dual_a') {
          throw new Error(`expected platform edit to re-key remembered pc selection, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.dual) {
          throw new Error(`expected stale dual remembered selection to be cleared after pc edit, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyActiveVariant?.id !== 'mobile_a') {
          throw new Error(`expected post-edit package reload to resolve the remembered compatible mobile variant, got ${component.$store.global.beautifyActiveVariant?.id}`);
        }

        component.$store.global.beautifyPreviewDevice = 'pc';
        component.$store.global.beautifySelectedVariantId = 'mobile_a';
        component.$store.global.beautifyActiveVariant = component.$store.global.beautifyActiveDetail.variants.mobile_a;
        component.$store.global.beautifyVariantSelectionByDevice = {
          pc: 'pc_b',
          mobile: 'mobile_a',
        };

        await component.updateCurrentVariantPlatform('dual');

        if (component.$store.global.beautifyVariantSelectionByDevice.pc !== 'pc_b') {
          throw new Error(`converting variant to dual should preserve remembered pc selection, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.mobile !== 'mobile_a') {
          throw new Error(`converting variant to dual should preserve remembered mobile selection, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        if (component.$store.global.beautifyVariantSelectionByDevice.dual !== 'mobile_a') {
          throw new Error(`converting variant to dual should remember the dual slot only, got ${JSON.stringify(component.$store.global.beautifyVariantSelectionByDevice)}`);
        }
        '''
    )


def test_beautify_grid_exposes_variant_selector_markup():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'x-show="variantOptions.length > 0"' in template
    assert '"selectedVariantId",' in template
    assert '@change="selectVariant($event.target.value)"' in template
    assert '<option value="">选择具体变体</option>' in template
    assert 'x-for="variant in variantOptions"' in template
    assert 'x-text="variant.label"' in template
    assert ":disabled=\"stageMode === 'screenshot' || !hasDualVariant\"" not in template


def test_beautify_preview_frame_falls_back_to_global_wallpaper_when_variant_selection_has_no_resolved_wallpaper():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: 'missing-wallpaper',
            },
            beautifyActiveWallpaper: {
              id: 'wall_stale',
              file: 'data/library/wallpapers/shared/stale-active.png',
            },
            beautifyGlobalSettings: {
              preview_wallpaper_id: 'wall_global',
              wallpaper: {
                id: 'wall_global',
                file: 'data/library/wallpapers/shared/global-fallback.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== 'data/library/wallpapers/shared/global-fallback.png') {
          throw new Error('global wallpaper should be used when variant selection is unresolved');
        }
        '''
    )


def test_beautify_preview_frame_allows_preview_without_wallpaper_when_variant_and_global_wallpapers_are_missing():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: 'missing-wallpaper',
            },
            beautifyActiveWallpaper: {
              id: 'wall_stale',
              file: 'data/library/wallpapers/shared/stale-active.png',
            },
            beautifyGlobalSettings: {
              preview_wallpaper_id: '',
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== '') {
          throw new Error(`expected wallpaperUrl to be empty when no wallpaper is resolved, got ${state.wallpaperUrl}`);
        }
        '''
    )


def test_beautify_preview_frame_ignores_stale_active_wallpaper_when_variant_selection_is_cleared():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: {
              identity_overrides: {},
              wallpapers: {},
            },
            beautifyActiveVariant: {
              theme_data: { name: 'Demo' },
              selected_wallpaper_id: '',
            },
            beautifyActiveWallpaper: {
              id: 'wall_stale',
              file: 'data/library/wallpapers/shared/stale-active.png',
            },
            beautifyGlobalSettings: {
              preview_wallpaper_id: '',
              wallpaper: null,
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.wallpaperUrl !== '') {
          throw new Error(`expected cleared variant selection to ignore stale active wallpaper, got ${state.wallpaperUrl}`);
        }
        '''
    )


def test_beautify_preview_frame_uses_global_only_preview_in_settings_workspace():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'mobile',
            beautifyActiveDetail: {
              identity_overrides: {
                character: { name: '包角色', avatar_file: 'data/library/beautify/packages/pkg_demo/avatars/character.png' },
                user: { name: '包用户', avatar_file: 'data/library/beautify/packages/pkg_demo/avatars/user.png' },
              },
            },
            beautifyActiveVariant: { theme_data: { name: 'Package Theme' } },
            beautifyActiveWallpaper: {
              id: 'wall_pkg',
              file: 'data/library/wallpapers/shared/package.png',
            },
            beautifyGlobalSettings: {
              preview_wallpaper_id: 'wall_global',
              wallpaper: {
                id: 'wall_global',
                file: 'data/library/wallpapers/shared/global.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: 'data/library/beautify/global/avatars/character.png' },
                user: { name: '全局用户', avatar_file: 'data/library/beautify/global/avatars/user.png' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.platform !== 'mobile') throw new Error('settings workspace should still respect preview shell mode');
        if (state.theme.name) throw new Error('settings workspace should ignore package theme data');
        if (state.wallpaperUrl !== 'data/library/wallpapers/shared/global.png') throw new Error('settings workspace should use global wallpaper');
        if (state.identities.character.name !== '全局角色') throw new Error('settings workspace should ignore package character override');
        if (state.identities.user.name !== '全局用户') throw new Error('settings workspace should ignore package user override');
        '''
    )


def test_beautify_preview_frame_injects_desktop_shell_width_fallback_for_settings_workspace():
    run_beautify_preview_frame_runtime_check(
        '''
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: null,
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {
              wallpaper: {
                file: 'data/library/wallpapers/shared/global.png',
              },
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };

        const state = component.resolvePreviewState();
        if (state.platform !== 'pc') {
          throw new Error(`expected desktop settings preview to keep pc platform, got ${state.platform}`);
        }
        if (state.theme.chat_width !== 55) {
          throw new Error(`expected desktop settings preview to inject 55 chat_width fallback, got ${state.theme.chat_width}`);
        }
        if (state.wallpaperUrl !== 'data/library/wallpapers/shared/global.png') {
          throw new Error(`expected global wallpaper to remain active, got ${state.wallpaperUrl}`);
        }
      '''
    )


def test_beautify_preview_frame_allows_settings_workspace_preview_without_active_package():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'settings',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: null,
            beautifyActiveVariant: null,
            beautifyActiveWallpaper: null,
            beautifyGlobalSettings: {
              wallpaper: { file: 'data/library/beautify/global/wallpapers/global.png' },
              identities: {
                character: { name: '全局角色', avatar_file: '' },
                user: { name: '全局用户', avatar_file: '' },
              },
            },
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        if (!host.__events.some((entry) => entry.type === 'render')) {
          throw new Error('settings workspace preview should render without active package detail');
        }
        '''
    )


def test_beautify_preview_frame_re_renders_when_workspace_or_global_settings_change():
    run_beautify_preview_frame_runtime_check(
        '''
        const watchers = new Map();
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: { id: 'detail-1', identity_overrides: {} },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyGlobalSettings: {
              wallpaper: { file: 'data/library/beautify/global/wallpapers/one.png' },
              identities: {
                character: { name: '角色一', avatar_file: '' },
                user: { name: '用户一', avatar_file: '' },
              },
            },
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = (key, callback) => watchers.set(key, callback);
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const initialRenderCount = host.__events.filter((entry) => entry.type === 'render').length;
        const workspaceWatcher = watchers.get('$store.global.beautifyWorkspace');
        const settingsWatcher = watchers.get('$store.global.beautifyGlobalSettings');
        if (typeof workspaceWatcher !== 'function') throw new Error('expected workspace watcher');
        if (typeof settingsWatcher !== 'function') throw new Error('expected global settings watcher');

        component.$store.global.beautifyWorkspace = 'settings';
        workspaceWatcher('settings');
        component.$store.global.beautifyGlobalSettings = {
          wallpaper: { file: 'data/library/beautify/global/wallpapers/two.png' },
          identities: {
            character: { name: '角色二', avatar_file: '' },
            user: { name: '用户二', avatar_file: '' },
          },
        };
        settingsWatcher(component.$store.global.beautifyGlobalSettings);

        const renderCount = host.__events.filter((entry) => entry.type === 'render').length;
        if (renderCount < initialRenderCount + 2) {
          throw new Error(`expected rerenders after workspace/global-settings changes, got ${renderCount - initialRenderCount}`);
        }
        '''
    )


def test_beautify_preview_frame_requests_host_filling_runtime_mode_for_native_preview():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
            beautifyActiveDetail: { id: 'detail-1', identity_overrides: {} },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyGlobalSettings: { identities: {}, wallpaper: {} },
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const renderEvent = host.__events.find((entry) => entry.type === 'render');
        if (!renderEvent) {
          throw new Error('expected preview render event');
        }
        if (renderEvent.options?.fillHostHeight !== true) {
          throw new Error('beautify preview should request host-filling runtime mode');
        }
        '''
    )


def test_render_runtime_fill_host_height_locks_iframe_to_host_height():
    run_render_runtime_check(
        '''
        const host = document.createElement('div');
        host.__rectHeight = 758;
        host.__rectWidth = 1200;

        const runtime = module.renderIsolatedHtml(host, {
          htmlPayload: '<div>demo</div>',
          minHeight: 520,
          fillHostHeight: true,
        });
        const shell = runtime?.shell || null;
        const iframe = runtime?.iframe || null;

        if (!runtime || !shell || !iframe) {
          throw new Error('expected render runtime to mount shell and iframe');
        }
        if (shell.style.height !== '758px') {
          throw new Error(`expected shell height to fill host, got ${shell.style.height}`);
        }
        if (iframe.style.height !== '758px') {
          throw new Error(`expected iframe height to fill host, got ${iframe.style.height}`);
        }
        '''
    )


def test_render_runtime_can_clear_all_runtimes_for_owner():
    run_render_runtime_check(
        '''
        const previewHost = document.createElement('div');
        previewHost.dataset.runtimeOwner = 'beautify-preview';
        const otherHost = document.createElement('div');
        otherHost.dataset.runtimeOwner = 'other-preview';

        const previewRuntime = module.renderIsolatedHtml(previewHost, {
          htmlPayload: '<div>preview</div>',
        });
        const otherRuntime = module.renderIsolatedHtml(otherHost, {
          htmlPayload: '<div>other</div>',
        });

        const releasedCount = module.clearIsolatedHtmlByOwner('beautify-preview', {
          clearShadow: true,
        });

        if (releasedCount !== 1) {
          throw new Error(`expected one beautify runtime to be released, got ${releasedCount}`);
        }
        if (previewRuntime.iframe.src !== 'about:blank') {
          throw new Error('beautify preview iframe should navigate to about:blank on release');
        }
        if (otherRuntime.iframe.src === 'about:blank') {
          throw new Error('unrelated preview runtime should remain active');
        }
        '''
    )


def test_beautify_preview_frame_keeps_preview_unloaded_until_user_requests_it():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'isPreviewLoaded' in source
    assert 'loadPreview()' in source
    assert 'if (!this.isPreviewLoaded) {' in source


def test_beautify_preview_frame_retries_render_after_preview_host_ref_appears():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'this.$nextTick(() =>' in source
    assert 'this.renderPreview();' in source
    assert_contains_any(source, ('this.$watch("$store.global.beautifyActiveDetail"', "this.$watch('$store.global.beautifyActiveDetail'"))
    assert_contains_any(source, ('this.$watch("$store.global.beautifyActiveVariant"', "this.$watch('$store.global.beautifyActiveVariant'"))
    assert_contains_any(source, ('this.$watch("$store.global.beautifyActiveWallpaper"', "this.$watch('$store.global.beautifyActiveWallpaper'"))
    assert_contains_any(source, ('this.$watch("$store.global.beautifyPreviewDevice"', "this.$watch('$store.global.beautifyPreviewDevice'"))
    assert 'if (!host) {' in source


def test_beautify_preview_frame_clears_runtime_when_active_detail_disappears():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert_contains_any(
        source,
        (
            'this.$watch("$store.global.beautifyActiveDetail", (detail) => {',
            "this.$watch('$store.global.beautifyActiveDetail', (detail) => {",
        ),
    )
    assert 'if (!detail) {' in source
    assert 'this.destroy();' in source


def test_beautify_preview_frame_falls_back_to_dom_query_when_alpine_ref_is_unavailable():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'this.$refs.previewHost' in source
    assert "querySelector('.beautify-preview-host')" in source or 'querySelector(".beautify-preview-host")' in source


def test_beautify_preview_frame_source_tracks_reset_preview_signal():
    source = read_project_file('static/js/components/beautifyPreviewFrame.js')

    assert 'resetPreview() {' in source
    assert_contains_any(
        source,
        (
            'this.$watch("$store.global.beautifyPreviewResetToken", () => {',
            "this.$watch('$store.global.beautifyPreviewResetToken', () => {",
        ),
    )
    assert 'this.isPreviewLoaded = false;' in source
    assert 'this.destroy();' in source


def test_beautify_preview_frame_resets_loaded_runtime_when_preview_reset_token_changes():
    run_beautify_preview_frame_runtime_check(
        '''
        const watchers = new Map();
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'mobile',
            beautifyPreviewResetToken: 0,
            beautifyActiveDetail: { id: 'detail-1', identity_overrides: {} },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyGlobalSettings: { identities: {}, wallpaper: {} },
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = (key, callback) => watchers.set(key, callback);
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const resetWatcher = watchers.get('$store.global.beautifyPreviewResetToken');
        if (typeof resetWatcher !== 'function') {
          throw new Error('expected preview reset watcher');
        }

        component.$store.global.beautifyPreviewResetToken = 1;
        resetWatcher(1);

        if (component.isPreviewLoaded !== false) {
          throw new Error('reset should unload preview state');
        }
        if (!host.__events.some((entry) => entry.type === 'clear')) {
          throw new Error('reset should clear the isolated runtime host');
        }

        const renderCountAfterReset = host.__events.filter((entry) => entry.type === 'render').length;
        component.renderPreview();
        if (host.__events.filter((entry) => entry.type === 'render').length !== renderCountAfterReset) {
          throw new Error('renderPreview should no-op while preview is unloaded');
        }

        component.loadPreview();
        if (host.__events.filter((entry) => entry.type === 'render').length !== renderCountAfterReset + 1) {
          throw new Error('manual reload should render again after reset');
        }
        '''
    )


def test_beautify_preview_frame_does_not_render_until_load_preview_is_called():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();

        if (host.__events.some((entry) => entry.type === 'render')) {
          throw new Error('preview should not render before manual activation');
        }

        component.loadPreview();

        if (!host.__events.some((entry) => entry.type === 'render')) {
          throw new Error('preview should render after manual activation');
        }
        '''
    )


def test_beautify_preview_frame_retries_after_load_when_host_is_not_ready_on_first_tick():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };

        let nextTickCount = 0;
        component.$refs = {};
        component.$el = {
          querySelector: () => (nextTickCount >= 2 ? host : null),
        };
        component.$watch = () => {};
        component.$nextTick = (callback) => {
          nextTickCount += 1;
          callback();
        };

        component.init();
        component.loadPreview();

        const renderEvents = host.__events.filter((entry) => entry.type === 'render');
        if (renderEvents.length !== 1) {
          throw new Error(`expected one delayed render after host mount, got ${renderEvents.length}`);
        }
        '''
    )


def test_beautify_preview_frame_retries_on_next_paint_when_host_mounts_after_next_tick_budget_is_exhausted():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };

        let paintReady = false;
        component.$refs = {};
        component.$el = {
          querySelector: () => (paintReady ? host : null),
        };
        globalThis.window = {
          requestAnimationFrame: (callback) => {
            paintReady = true;
            callback();
            return 1;
          },
          setTimeout: (callback) => {
            paintReady = true;
            callback();
            return 1;
          },
        };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const renderEvents = host.__events.filter((entry) => entry.type === 'render');
        if (renderEvents.length !== 1) {
          throw new Error(`expected one render after next paint host mount, got ${renderEvents.length}`);
        }
        '''
    )


def test_beautify_preview_frame_uses_timeout_backup_when_frame_retry_callback_never_fires():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };

        let timeoutReady = false;
        component.$refs = {};
        component.$el = {
          querySelector: () => (timeoutReady ? host : null),
        };
        globalThis.window = {
          requestAnimationFrame: () => 1,
          setTimeout: (callback) => {
            timeoutReady = true;
            callback();
            return 1;
          },
        };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const renderEvents = host.__events.filter((entry) => entry.type === 'render');
        if (renderEvents.length !== 1) {
          throw new Error(`expected one render after timeout backup, got ${renderEvents.length}`);
        }
        '''
    )


def test_beautify_preview_frame_renders_when_preview_host_is_inserted_after_activation():
    run_beautify_preview_frame_runtime_check(
        '''
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };

        let hostReady = false;
        const observers = [];
        component.$refs = {};
        component.$el = {
          querySelector: () => (hostReady ? host : null),
        };
        globalThis.MutationObserver = class MutationObserver {
          constructor(callback) {
            this.callback = callback;
            observers.push(this);
          }
          observe() {}
          disconnect() {}
        };
        globalThis.window = {
          requestAnimationFrame: () => 1,
          setTimeout: () => 1,
        };
        component.$watch = () => {};
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        hostReady = true;
        for (const observer of observers) {
          observer.callback([{ type: 'childList' }]);
        }

        const renderEvents = host.__events.filter((entry) => entry.type === 'render');
        if (renderEvents.length !== 1) {
          throw new Error(`expected one render after host insertion, got ${renderEvents.length}`);
        }
        '''
    )


def test_beautify_preview_frame_restarts_observer_after_destroy_and_reload():
    run_beautify_preview_frame_runtime_check(
        '''
        const watchers = new Map();
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        const observers = [];
        component.$store = {
          global: {
            beautifyActiveDetail: { id: 'detail-1', identity_overrides: {} },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyGlobalSettings: { identities: {}, wallpaper: {} },
            beautifyWorkspace: 'packages',
            beautifyPreviewDevice: 'pc',
          },
        };
        component.$refs = { previewHost: host };
        component.$el = { querySelector: () => host };
        component.$watch = (key, callback) => watchers.set(key, callback);
        component.$nextTick = (callback) => callback();
        globalThis.MutationObserver = class MutationObserver {
          constructor(callback) {
            this.callback = callback;
            this.disconnected = false;
            observers.push(this);
          }
          observe() {}
          disconnect() { this.disconnected = true; }
        };

        component.init();
        component.loadPreview();

        const detailWatcher = watchers.get('$store.global.beautifyActiveDetail');
        if (typeof detailWatcher !== 'function') throw new Error('expected active detail watcher');

        detailWatcher(null);
        if (!observers[0]?.disconnected) throw new Error('expected first observer to disconnect on destroy');

        component.$store.global.beautifyActiveDetail = { id: 'detail-2', identity_overrides: {} };
        detailWatcher(component.$store.global.beautifyActiveDetail);
        component.loadPreview();

        if (observers.length < 2) throw new Error('expected observer to restart on reload');
        if (observers[1].disconnected) throw new Error('new observer should stay connected after reload');
        '''
    )


def test_beautify_preview_frame_re_renders_when_beautify_mode_becomes_visible_after_hidden_init():
    run_beautify_preview_frame_runtime_check(
        '''
        const watchers = new Map();
        const host = { innerHTML: '', __events: [] };
        const component = module.default();
        component.$store = {
          global: {
            currentMode: 'chat',
            beautifyActiveDetail: { id: 'detail-1' },
            beautifyActiveVariant: { theme_data: {} },
            beautifyActiveWallpaper: {},
            beautifyPreviewDevice: 'pc',
          },
        };
        component.$refs = { previewHost: host };
        component.$watch = (key, callback) => watchers.set(key, callback);
        component.$nextTick = (callback) => callback();

        component.init();
        component.loadPreview();

        const initialRenderCount = host.__events.filter((entry) => entry.type === 'render').length;
        const variantWatcher = watchers.get('$store.global.beautifyActiveVariant');
        if (typeof variantWatcher !== 'function') {
          throw new Error('expected active variant watcher to be registered');
        }

        component.$store.global.beautifyActiveVariant = { theme_data: { custom_css: 'body{color:red;}' } };
        variantWatcher(component.$store.global.beautifyActiveVariant);

        const renderCountAfterVariantChange = host.__events.filter((entry) => entry.type === 'render').length;
        if (renderCountAfterVariantChange !== initialRenderCount + 1) {
          throw new Error(`expected one rerender after active variant change, got ${renderCountAfterVariantChange - initialRenderCount}`);
        }
        '''
    )
