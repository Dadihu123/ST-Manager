import json
import re
import subprocess
import textwrap

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_div_block(source, marker):
    marker_index = source.find(marker)
    assert marker_index != -1

    block_start = source.rfind('<div', 0, marker_index)
    assert block_start != -1

    depth = 0
    search_index = block_start
    while search_index < len(source):
        next_open = source.find('<div', search_index)
        next_close = source.find('</div>', search_index)
        assert next_close != -1

        if next_open != -1 and next_open < next_close:
            depth += 1
            search_index = next_open + 4
            continue

        depth -= 1
        search_index = next_close + 6
        if depth == 0:
            return source[block_start:search_index]

    raise AssertionError(f'Could not extract div block for marker: {marker}')


def extract_exact_css_block(css_source, selector):
    match = re.search(rf'(^|\n)\s*{re.escape(selector)}\s*\{{', css_source)
    if not match:
        raise ValueError(f'Exact selector not found: {selector}')

    selector_start = match.start()
    block_start = css_source.index('{', selector_start)
    block_end = css_source.index('}', block_start)
    return css_source[block_start + 1:block_end]


def extract_media_block(css_source, media_query):
    media_start = css_source.index(media_query)
    block_start = css_source.index('{', media_start)
    depth = 1
    index = block_start + 1

    while depth > 0:
        current_char = css_source[index]

        if current_char == '{':
            depth += 1
        elif current_char == '}':
            depth -= 1

        index += 1

    return css_source[block_start + 1:index - 1]


def extract_js_function_block(source, signature):
    start = source.find(signature)
    assert start != -1

    block_start = source.find('{', start)
    assert block_start != -1

    depth = 1
    index = block_start + 1
    while depth > 0 and index < len(source):
        current_char = source[index]
        if current_char == '{':
            depth += 1
        elif current_char == '}':
            depth -= 1
        index += 1

    assert depth == 0
    return source[start:index]


def run_preset_detail_reader_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/presetDetailReader.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function presetDetailReader()', 'function presetDetailReader()');

        const stubs = `
        const getPresetDetail = async (...args) => {{
          if (typeof globalThis.getPresetDetail === 'function') {{
            return globalThis.getPresetDetail(...args);
          }}
          return {{ success: true, preset: {{}} }};
        }};

        let __sendPresetToSillyTavernImpl = async () => ({{ success: true, last_sent_to_st: 0 }});
        const sendPresetToSillyTavern = (...args) => __sendPresetToSillyTavernImpl(...args);
        globalThis.__setSendPresetToSillyTavern = (fn) => {{
          __sendPresetToSillyTavernImpl = fn;
        }};
        let __importPresetVersionImpl = async () => ({{ success: true, preset: null }});
        const importPresetVersion = (...args) => __importPresetVersionImpl(...args);
        globalThis.__setImportPresetVersion = (fn) => {{
          __importPresetVersionImpl = fn;
        }};
        const __presetSendToStInFlightIds = new Set();
        const isPresetSendToStPending = (presetId) => __presetSendToStInFlightIds.has(String(presetId || '').trim());
        const setPresetSendToStPending = (presetId, sending) => {{
          const key = String(presetId || '').trim();
          if (!key) return;
          if (sending) {{
            __presetSendToStInFlightIds.add(key);
            return;
          }}
          __presetSendToStInFlightIds.delete(key);
        }};
        const apiSavePresetExtensions = async () => ({{ success: true }});
        const clearActiveRuntimeContext = () => {{}};
        const setActiveRuntimeContext = () => {{}};
        const downloadFileFromApi = async () => {{}};
        const formatDate = (value) => value;
        const PROMPT_MARKER_VISUALS = {{
          scenario: {{ key: 'scenario', label: '场景', paths: ['M4.75 17.5 9.5 12.75 12.25 15.5 16.75 11 19.25 13.5'] }},
          fallback: {{ key: 'marker', label: '预留字段', paths: ['M12 5v14'] }},
        }};
        const getPromptMarkerVisual = (identifier) => PROMPT_MARKER_VISUALS[String(identifier || '').trim()] || PROMPT_MARKER_VISUALS.fallback;
        const resolvePromptMarkerVisual = getPromptMarkerVisual;
        const buildPromptMarkerIcon = (visual, options = {{}}) => {{
          const strokeWidth = options.strokeWidth || '1.5';
          const svgAttributes = options.svgAttributes || 'aria-hidden="true" fill="none"';
          const pathAttributes = options.pathAttributes || 'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" fill="none"';
          const paths = Array.isArray(visual?.paths)
            ? visual.paths.map((path) => '<path d="' + path + '" ' + pathAttributes + ' stroke-width="' + strokeWidth + '"></path>').join('')
            : '';
          return '<svg viewBox="0 0 24 24" ' + svgAttributes + '>' + paths + '</svg>';
        }};
        globalThis.window = {{
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(name, options = {{}}) {{
            this.type = name;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default presetDetailReader;'),
        );
        const reader = module.default();
        reader.$store = {{
          global: {{
            deviceType: 'desktop',
            showToast() {{}},
          }},
        }};

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


def test_preset_detail_reader_js_exposes_reader_view_state_and_helpers_contracts():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'activeGroup:' in source
    assert 'activeItemId:' in source
    assert 'searchTerm:' in source
    assert 'uiFilter:' in source
    assert 'showRightPanel:' in source
    assert 'showMobileSidebar:' in source

    assert 'get readerView() {' in source
    assert 'get readerGroups() {' in source
    assert 'get readerItems() {' in source
    assert 'get filteredItems() {' in source
    assert 'get activeItem() {' in source
    assert 'get readerStats() {' in source

    assert 'selectGroup(groupId) {' in source
    assert 'selectItem(itemId) {' in source
    assert 'getItemValuePreview(item) {' in source
    assert 'getItemFullDetail(item) {' in source
    assert 'getItemBadge(item) {' in source
    assert 'formatItemPayload(item) {' not in source


def test_preset_detail_reader_js_search_haystack_includes_prompt_identifier():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'item.payload?.identifier' in source


def test_preset_detail_reader_js_exposes_prompt_workspace_helpers():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'activeWorkspace:' in source
    assert 'activePromptId:' in source
    assert 'get isPromptWorkspaceReader() {' in source
    assert 'get promptItems() {' in source
    assert 'get orderedPromptItems() {' in source
    assert 'get activePromptItem() {' in source
    assert 'get activeContextItem() {' in source
    assert 'selectWorkspace(workspaceId) {' in source
    assert 'selectPrompt(itemId) {' in source
    assert 'getPromptPreview(item) {' in source
    assert 'getPromptFullDetail(item) {' in source
    assert 'getPromptPositionLabel(item) {' in source


def test_preset_detail_reader_js_exposes_mobile_detail_view_state_and_actions():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'showMobileDetailView:' in source
    assert 'openMobileDetailView() {' in source
    assert 'closeMobileDetailView() {' in source


def test_preset_detail_reader_template_exposes_import_merge_action_for_openai_presets():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert '@click="triggerImportActivePresetVersion()"' in source
    assert '导入并合并' in source


def test_preset_detail_reader_runtime_import_action_posts_formdata_and_refreshes_versions():
    run_preset_detail_reader_runtime_check(
        """
        const importCalls = [];
        globalThis.__setImportPresetVersion(async (formData) => {
          importCalls.push(formData.get('preset_id'));
          return {
            success: true,
            preset: {
              id: 'global::alpha.json',
              preset_kind: 'openai',
              available_versions: [
                { id: 'global::alpha.json', version_label: 'alpha', is_default_version: true },
                { id: 'global::imported.json', version_label: 'imported', is_default_version: false },
              ],
              family_info: { family_name: 'Alpha' },
            },
          };
        });

        const fakeFile = new Blob(['{}'], { type: 'application/json' });
        fakeFile.name = 'imported.json';
        let changeHandler = null;
        let clicked = false;
        globalThis.document = {
          createElement(tagName) {
            if (tagName !== 'input') {
              throw new Error(`expected input element, got ${tagName}`);
            }
            return {
              type: '',
              accept: '',
              files: [fakeFile],
              addEventListener(eventName, handler) {
                if (eventName !== 'change') {
                  throw new Error(`expected change handler, got ${eventName}`);
                }
                changeHandler = handler;
              },
              click() {
                clicked = true;
                return Promise.resolve(changeHandler?.());
              },
            };
          },
        };
        reader.$store = { global: { showToast() {}, deviceType: 'desktop' } };
        reader.activePresetDetail = {
          id: 'global::alpha.json',
          preset_kind: 'openai',
          available_versions: [{ id: 'global::alpha.json', version_label: 'alpha', is_default_version: true }],
        };

        await reader.triggerImportActivePresetVersion();

        if (!clicked) {
          throw new Error('expected import trigger to click file input');
        }
        if (importCalls.length !== 1 || importCalls[0] !== 'global::alpha.json') {
          throw new Error(`expected preset id in import request, got ${JSON.stringify(importCalls)}`);
        }
        if (reader.availableVersions.length !== 2) {
          throw new Error(`expected refreshed versions after import, got ${reader.availableVersions.length}`);
        }
        """
    )


def test_preset_detail_reader_runtime_exposes_version_helpers_and_switches_by_concrete_version_id():
    run_preset_detail_reader_runtime_check(
        """
        const detailCalls = [];
        globalThis.__detailCalls = detailCalls;
        globalThis.getPresetDetail = async (presetId) => {
          detailCalls.push(presetId);
          return {
            success: true,
            preset: {
              id: presetId,
              name: 'Family Preset',
              type: 'global',
              path: '/presets/' + presetId + '.json',
              reader_view: {
                family: 'generic',
                family_label: '通用预设',
                groups: [],
                items: [],
                stats: { total_count: 0 },
              },
              family_info: {
                entry_type: 'family',
                family_id: 'family-alpha',
                default_version_id: 'preset-v2',
                default_version_label: 'v2',
                version_count: 2,
              },
              available_versions: [
                { id: 'preset-v1', version_label: 'v1', is_default: false },
                { id: 'preset-v2', version_label: 'v2', is_default: true },
              ],
            },
          };
        };

        await reader.openPreset({ id: 'family-entry-id', entry_type: 'family', default_version_id: 'preset-v2' });

        if (!reader.hasMultipleVersions) {
          throw new Error('expected versioned preset to report multiple versions');
        }
        if (reader.availableVersions.length !== 2) {
          throw new Error(`expected available versions to expose two entries, got ${JSON.stringify(reader.availableVersions)}`);
        }
        if (reader.availableVersions[1].id !== 'preset-v2') {
          throw new Error(`expected version list to preserve ids, got ${JSON.stringify(reader.availableVersions)}`);
        }

        await reader.switchVersion('preset-v1');

        if (JSON.stringify(detailCalls) !== JSON.stringify(['preset-v2', 'preset-v1'])) {
          throw new Error(`expected concrete detail loads for default then switched version, got ${JSON.stringify(detailCalls)}`);
        }
        if (reader.activePresetDetail?.id !== 'preset-v1') {
          throw new Error(`expected switched preset detail to become active, got ${JSON.stringify(reader.activePresetDetail)}`);
        }
        """
    )


def test_preset_detail_reader_js_exposes_scalar_workspace_helpers():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'get scalarWorkspace() {' in source
    assert 'get hasScalarWorkspace() {' in source
    assert 'get isScalarWorkspaceReader() {' in source
    assert 'get scalarWorkspaceSections() {' in source
    assert 'get scalarWorkspaceVisibleFieldEntries() {' in source
    assert 'get scalarWorkspaceSummaryCards() {' in source
    assert 'getScalarWorkspaceFieldValue(fieldKey) {' in source
    assert 'getScalarWorkspaceFieldSummary(fieldKey) {' in source


def test_preset_detail_reader_js_exposes_mirrored_profile_helpers():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'get editorProfile() {' in source
    assert 'get isMirroredProfileReader() {' in source
    assert 'get mirroredProfileSections() {' in source
    assert 'get readerMirroredProfileSections() {' in source
    assert 'prompt_manager' in source
    assert 'extensions_and_advanced' in source
    assert 'getProfileSectionFields(sectionId) {' in source
    assert 'getProfileFieldValue(fieldKey) {' in source
    assert 'getProfileFieldDisplay(fieldKey) {' in source
    assert 'getProfileFieldPercent(fieldKey) {' in source
    assert 'isProfileFieldSlider(field) {' in source
    assert 'isProfileFieldToggle(field) {' in source
    assert 'isProfileFieldSelect(field) {' in source


def test_preset_detail_reader_template_compacts_prompt_list_metadata_row():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    prompt_card_match = re.search(
        r'@click="selectPrompt\(item\.id\)"[\s\S]*?x-text="getPromptPreview\(item\)"',
        source,
    )
    assert prompt_card_match is not None

    prompt_card_block = prompt_card_match.group(0)

    assert 'class="mt-2 flex items-center gap-2"' not in prompt_card_block
    assert 'item.summary ||' not in prompt_card_block
    assert 'x-text="getPromptPositionLabel(item)"' in prompt_card_block
    assert 'x-text="getPromptPreview(item)"' in prompt_card_block
    assert 'item.prompt_meta?.is_enabled' in prompt_card_block
    assert ('sr-only' in prompt_card_block) or ('aria-label=' in prompt_card_block) or ('title=' in prompt_card_block)
    assert "icon('check-bold', 'ui-icon--xs')" in prompt_card_block
    assert "icon('minus', 'ui-icon--xs')" in prompt_card_block


def test_preset_detail_reader_template_compacts_prompt_state_info_bar():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    prompt_state_match = re.search(
        r'提示词状态[\s\S]*?x-text="getPromptFullDetail\(activeContextItem\)"',
        source,
    )
    assert prompt_state_match is not None

    prompt_state_block = prompt_state_match.group(0)

    assert '<div class="flex justify-end">' not in prompt_state_block
    assert 'x-text="getPromptPositionLabel(activeContextItem)"' in prompt_state_block
    assert 'x-text="getPromptFullDetail(activeContextItem)"' in prompt_state_block
    assert '@click="copyText(getPromptFullDetail(activeContextItem), \'条目内容\')"' in prompt_state_block or '@click="copyText(getPromptFullDetail(activeContextItem), "条目内容")"' in prompt_state_block
    assert 'justify-between' in prompt_state_block
    assert 'class="text-[10px] font-medium"' not in prompt_state_block
    assert ('sr-only' in prompt_state_block) or ('aria-label=' in prompt_state_block)


def test_preset_detail_reader_template_localizes_remaining_prompt_copy():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert '提示词列表' in source
    assert '按提示词顺序排序' in source
    assert '没有匹配的提示词' in source
    assert '提示词已启用' in source
    assert '提示词已禁用' in source
    assert '活动提示词' in source
    assert '尚未选择提示词' in source
    assert '标识符' in source

    assert 'Prompt 列表' not in source
    assert '按 prompt_order 排序' not in source
    assert '没有匹配的 Prompt' not in source
    assert 'Prompt 已启用' not in source
    assert 'Prompt 已禁用' not in source
    assert '活动 Prompt' not in source
    assert '尚未选择 Prompt' not in source
    assert 'Identifier' not in source


def test_preset_detail_reader_template_renders_version_selector_for_multi_version_families():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-show="hasMultipleVersions"' in source
    assert 'switchVersion(option.value)' in source
    assert 'x-for="version in availableVersions"' in source


def test_preset_detail_reader_template_renders_mobile_version_selector_for_family_presets():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    mobile_header_block = extract_div_block(source, 'preset-reader-mobile-header')

    assert 'x-show="hasMultipleVersions"' in mobile_header_block
    assert 'switchVersion(option.value)' in mobile_header_block
    assert 'x-for="version in availableVersions"' in mobile_header_block


def test_preset_detail_reader_template_mobile_header_only_renders_for_mobile_list_page():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    mobile_header_block = extract_div_block(source, 'preset-reader-mobile-header')
    main_header_block = extract_div_block(mobile_header_block, 'preset-reader-mobile-header-main')
    secondary_header_block = extract_div_block(mobile_header_block, 'preset-reader-mobile-header-secondary')

    assert 'preset-reader-mobile-header-main' in mobile_header_block
    assert 'preset-reader-mobile-header-secondary' in mobile_header_block
    assert 'x-show="$store.global.deviceType === \'mobile\' && !showMobileDetailView"' in mobile_header_block
    assert '@click="toggleMobileSidebar()"' in main_header_block
    assert '@click="openFullscreenEditor()"' in main_header_block
    assert '@click="closeModal()"' in main_header_block
    assert '@click="toggleMobileMoreMenu()"' in secondary_header_block
    assert '>\n          编辑\n        </button>' in main_header_block


def test_preset_detail_reader_template_mobile_more_menu_is_list_page_only_and_has_no_detail_toggle():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    mobile_header_block = extract_div_block(source, 'preset-reader-mobile-header')
    main_header_block = extract_div_block(mobile_header_block, 'preset-reader-mobile-header-main')
    more_menu_block = extract_div_block(source, 'preset-reader-mobile-more-menu')

    assert 'x-show="$store.global.deviceType === \'mobile\' && showMobileMoreMenu && !showMobileDetailView"' in more_menu_block
    assert 'toggleMobileRightPanel()' not in more_menu_block
    assert '打开详情' not in more_menu_block
    assert '收起详情' not in more_menu_block
    assert '@click="exportActivePreset(); showMobileMoreMenu = false"' in more_menu_block
    assert '@click="openAdvancedExtensions(); showMobileMoreMenu = false"' in more_menu_block
    assert '@click="exportActivePreset(); showMobileMoreMenu = false"' not in main_header_block
    assert '@click="openAdvancedExtensions(); showMobileMoreMenu = false"' not in main_header_block


def test_preset_detail_reader_template_hides_central_list_on_mobile_detail_page():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'class="flex-1 min-w-0 flex flex-col border-r border-[var(--border-light)] md:border-r-0 lg:border-r lg:border-[var(--border-light)]"' in source
    assert "'hidden': $store.global.deviceType === 'mobile' && showMobileDetailView" in source


def test_preset_detail_reader_template_repurposes_detail_panel_for_desktop_and_mobile_detail_view():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "x-show=\"($store.global.deviceType !== 'mobile' && showRightPanel) || ($store.global.deviceType === 'mobile' && showMobileDetailView)\"" in source
    assert "'flex': $store.global.deviceType === 'mobile' && showMobileDetailView" in source
    assert "'hidden': $store.global.deviceType === 'mobile' && !showMobileDetailView" in source


def test_preset_detail_reader_template_adds_mobile_detail_header_and_body_hooks():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'preset-reader-mobile-detail-header' in source
    assert 'preset-reader-mobile-detail-body' in source
    assert '@click="closeMobileDetailView()"' in source


def test_preset_detail_reader_template_compacts_mobile_title_meta_and_marks_scroll_region():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'getMobileHeaderMetaLine()' in source
    assert 'preset-reader-mobile-title' in source
    assert 'preset-reader-mobile-subtitle' in source
    assert '@scroll.passive="handleMobileContentScroll($event)"' in source
    assert 'x-ref="presetReaderContentScroll"' in source


def test_preset_detail_reader_js_exposes_mobile_header_state_and_helpers():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'presetMobileHeaderHidden:' in source
    assert 'presetLastScrollTop:' in source
    assert 'showMobileMoreMenu:' in source
    assert 'updatePresetLayoutMetrics() {' in source
    assert 'syncPresetMobileHeaderVisibility(container) {' in source
    assert 'handleMobileContentScroll(event) {' in source
    assert 'toggleMobileMoreMenu() {' in source
    assert 'toggleMobileSidebar() {' in source
    assert 'getMobileHeaderMetaLine() {' in source
    assert 'getMobileHeaderContextLabel() {' in source
    assert 'getMobileHeaderCountLabel() {' in source


def test_preset_detail_reader_js_exposes_send_to_st_contracts():
    source = read_project_file('static/js/components/presetDetailReader.js')
    can_send_block = extract_js_function_block(source, 'canSendActivePresetToST() {')

    assert 'sendPresetToSillyTavern,' in source
    assert 'isSendingPresetToST: false,' in source
    assert 'canSendActivePresetToST() {' in source
    assert 'getActivePresetSendToSTTitle() {' in source
    assert 'async sendActivePresetToST() {' in source
    assert 'window.dispatchEvent(new CustomEvent("preset-sent-to-st", {' in source or "window.dispatchEvent(new CustomEvent('preset-sent-to-st', {" in source
    assert 'id:' in source
    assert 'last_sent_to_st:' in source

    assert ('global-alt::' in can_send_block) or ('st_openai_preset_dir' in can_send_block)
    assert (
        'source_folder.includes("global-alt::")' in can_send_block
        or "source_folder.includes('global-alt::')" in can_send_block
        or 'startsWith("global-alt::")' in can_send_block
        or "startsWith('global-alt::')" in can_send_block
        or 'source_folder === "st_openai_preset_dir"' in can_send_block
        or "source_folder === 'st_openai_preset_dir'" in can_send_block
        or 'source_folder !== "st_openai_preset_dir"' in can_send_block
        or "source_folder !== 'st_openai_preset_dir'" in can_send_block
    )


def test_preset_detail_reader_template_exposes_send_to_st_buttons_contracts():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert '@click="sendActivePresetToST()"' in source
    assert 'x-show="canSendActivePresetToST()"' in source
    assert '发送到 ST（对话补全预设，同名将直接覆盖 ST 中现有预设）' in source


def test_preset_detail_reader_css_adds_mobile_hidden_header_contracts():
    source = read_project_file('static/css/modules/modal-detail.css')
    root_block = extract_exact_css_block(source, '.preset-reader-modal')
    header_block = extract_exact_css_block(source, '.preset-reader-modal .preset-reader-mobile-header')
    hidden_header_block = extract_exact_css_block(
        source,
        '.preset-reader-modal .preset-reader-mobile-header.is-mobile-hidden',
    )

    assert '--preset-reader-header-height:' in root_block
    assert 'max-height:' in header_block
    assert 'max-height: 0;' in hidden_header_block
    assert 'opacity: 0.01;' in hidden_header_block
    assert 'transform: translateY(' in hidden_header_block


def test_preset_detail_reader_css_positions_mobile_sidebar_drawer_with_header_height_variable():
    source = read_project_file('static/css/modules/modal-detail.css')
    mobile_block = extract_media_block(source, '@media (max-width: 768px)')
    sidebar_block = extract_exact_css_block(mobile_block, '.preset-reader-modal .preset-reader-mobile-sidebar')

    assert 'top: var(--preset-reader-header-height);' in sidebar_block


def test_preset_detail_reader_template_uses_mobile_fullscreen_detail_shell_hooks():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'preset-reader-overlay' in source
    assert 'preset-reader-mobile-detail-panel' in source
    assert 'preset-reader-mobile-detail-header' in source
    assert 'preset-reader-mobile-detail-body' in source


def test_preset_detail_reader_template_promotes_mobile_list_overlay_and_modal_to_fullscreen_shell():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "class=\"modal-overlay preset-reader-overlay z-modal-std flex\"" in source
    assert ":class=\"$store.global.deviceType === 'mobile' ? 'items-stretch justify-stretch p-0' : 'items-center justify-center p-4'\"" in source
    assert "class=\"preset-reader-modal bg-[var(--bg-panel)] border border-[var(--border-light)] flex flex-col overflow-hidden\"" in source
    assert ":class=\"$store.global.deviceType === 'mobile' ? 'w-screen max-w-none h-[100dvh] min-h-[100dvh] rounded-none shadow-none' : 'w-full max-w-7xl h-[90vh] rounded-2xl shadow-2xl'\"" in source


def test_preset_detail_reader_runtime_mobile_header_meta_line_includes_source_label():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          preset_kind: 'textgen',
          source: 'global',
          reader_view: {
            family: 'generic',
            family_label: '通用预设',
            groups: [],
            items: [],
            stats: { total_count: 0 },
          },
        };

        if (reader.getMobileHeaderMetaLine() !== 'textgen · 全局 / 通用预设') {
          throw new Error(`expected source-aware mobile meta line, got ${reader.getMobileHeaderMetaLine()}`);
        }
        """
    )


def test_preset_detail_reader_css_adds_fullscreen_mobile_overlay_and_detail_panel_contracts():
    source = read_project_file('static/css/modules/modal-detail.css')
    mobile_block = extract_media_block(source, '@media (max-width: 768px)')
    overlay_block = extract_exact_css_block(mobile_block, '.preset-reader-overlay')
    modal_block = extract_exact_css_block(mobile_block, '.preset-reader-modal')
    detail_panel_block = extract_exact_css_block(
        mobile_block,
        '.preset-reader-modal .preset-reader-mobile-detail-panel',
    )
    detail_header_block = extract_exact_css_block(
        mobile_block,
        '.preset-reader-modal .preset-reader-mobile-detail-header',
    )
    detail_body_block = extract_exact_css_block(
        mobile_block,
        '.preset-reader-modal .preset-reader-mobile-detail-body',
    )

    assert 'padding: 0;' in overlay_block
    assert 'align-items: stretch;' in overlay_block
    assert 'justify-content: stretch;' in overlay_block

    assert 'width: 100vw;' in modal_block
    assert 'max-width: none;' in modal_block
    assert 'height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh));' in modal_block
    assert 'min-height: var(' in modal_block
    assert 'border-radius: 0;' in modal_block
    assert 'box-shadow: none;' in modal_block

    assert 'width: 100%;' in detail_panel_block
    assert 'max-width: none;' in detail_panel_block
    assert 'height: 100%;' in detail_panel_block
    assert 'border-left: none;' in detail_panel_block
    assert 'top: var(--preset-reader-header-height);' not in detail_panel_block

    assert 'position: sticky;' in detail_header_block
    assert 'top: 0;' in detail_header_block

    assert 'overflow-y: auto;' in detail_body_block
    assert 'padding-bottom:' in detail_body_block


def test_preset_detail_reader_css_keeps_sidebar_and_more_menu_tied_to_header_height_without_old_detail_panel_anchor():
    source = read_project_file('static/css/modules/modal-detail.css')
    mobile_block = extract_media_block(source, '@media (max-width: 768px)')
    more_menu_block = extract_exact_css_block(
        mobile_block,
        '.preset-reader-modal .preset-reader-mobile-more-menu',
    )
    sidebar_block = extract_exact_css_block(mobile_block, '.preset-reader-modal .preset-reader-mobile-sidebar')
    detail_panel_block = extract_exact_css_block(
        mobile_block,
        '.preset-reader-modal .preset-reader-mobile-detail-panel',
    )

    assert 'top: var(--preset-reader-header-height);' in more_menu_block
    assert 'top: var(--preset-reader-header-height);' in sidebar_block
    assert 'top: var(--preset-reader-header-height);' not in detail_panel_block


def test_preset_detail_reader_runtime_reveals_mobile_header_for_sidebar_and_more_menu():
    run_preset_detail_reader_runtime_check(
        """
        reader.$store.global.deviceType = 'mobile';
        reader.presetMobileHeaderHidden = true;
        reader.showMobileMoreMenu = false;
        reader.showMobileSidebar = false;
        reader.showRightPanel = false;
        reader.updatePresetLayoutMetrics = () => {};

        reader.toggleMobileMoreMenu();
        if (!reader.showMobileMoreMenu || reader.presetMobileHeaderHidden) {
          throw new Error('expected more menu open to reveal header');
        }

        reader.presetMobileHeaderHidden = true;
        reader.toggleMobileSidebar();
        if (!reader.showMobileSidebar || reader.presetMobileHeaderHidden) {
          throw new Error('expected sidebar open to reveal header');
        }
        """
    )


def test_preset_detail_reader_runtime_tracks_shared_send_state_for_active_preset():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            (listeners[event.type] || []).forEach((handler) => handler(event));
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { deviceType: 'desktop', showToast() {} } };
        reader.init();
        reader.activePresetDetail = {
          id: 'preset-1',
          preset_kind: 'openai',
          last_sent_to_st: 0,
        };

        window.dispatchEvent(new CustomEvent('preset-send-to-st-pending', {
          detail: { id: 'preset-1', sending: true },
        }));
        if (reader.isSendingPresetToST !== true) {
          throw new Error('expected shared pending event to set active preset sending state');
        }

        window.dispatchEvent(new CustomEvent('preset-send-to-st-finished', {
          detail: { id: 'preset-1' },
        }));
        if (reader.isSendingPresetToST !== false) {
          throw new Error('expected shared finished event to clear active preset sending state');
        }
        """
    )


def test_preset_detail_reader_runtime_clears_mobile_header_state_on_close():
    run_preset_detail_reader_runtime_check(
        """
        reader.$store.global.deviceType = 'mobile';
        reader.showModal = true;
        reader.showMobileSidebar = true;
        reader.showRightPanel = true;
        reader.showMobileMoreMenu = true;
        reader.presetMobileHeaderHidden = true;
        reader.activePresetDetail = { id: 'preset-1', reader_view: { family: 'generic', groups: [], items: [], stats: { total_count: 0 } } };

        reader.closeModal();

        if (reader.showMobileSidebar || reader.showRightPanel || reader.showMobileMoreMenu || reader.presetMobileHeaderHidden) {
          throw new Error('expected closeModal to clear mobile header state');
        }
        """
    )


def test_preset_detail_reader_runtime_send_active_preset_keeps_submitted_id_after_async_switch():
    run_preset_detail_reader_runtime_check(
        """
        const events = [];
        let resolveSend;
        globalThis.window = {
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        globalThis.__setSendPresetToSillyTavern(() => new Promise((resolve) => {
          resolveSend = resolve;
        }));

        reader.$store = { global: { showToast() {} } };
        reader.activePresetDetail = {
          id: 'preset-1',
          preset_kind: 'openai',
          last_sent_to_st: 0,
        };

        const pending = reader.sendActivePresetToST();
        reader.activePresetDetail = {
          id: 'preset-2',
          preset_kind: 'openai',
          last_sent_to_st: 0,
        };

        resolveSend({ success: true, last_sent_to_st: 321.5 });
        await pending;

        if (reader.activePresetDetail.id !== 'preset-2') {
          throw new Error(`expected reader to keep switched preset active, got ${reader.activePresetDetail.id}`);
        }
        if (Number(reader.activePresetDetail.last_sent_to_st || 0) !== 0) {
          throw new Error(`expected switched preset timestamp to stay unchanged, got ${reader.activePresetDetail.last_sent_to_st}`);
        }

        const sentEvent = events.find((event) => event.type === 'preset-sent-to-st');
        if (!sentEvent) {
          throw new Error('expected sendActivePresetToST to dispatch preset-sent-to-st event');
        }
        if (sentEvent.detail?.id !== 'preset-1') {
          throw new Error(`expected event to report submitted preset id, got ${sentEvent.detail?.id}`);
        }
        if (Number(sentEvent.detail?.last_sent_to_st || 0) !== 321.5) {
          throw new Error(`expected event to report returned timestamp, got ${sentEvent.detail?.last_sent_to_st}`);
        }
        """
    )


def test_preset_detail_reader_runtime_send_active_preset_uses_current_version_id():
    run_preset_detail_reader_runtime_check(
        """
        const sendCalls = [];
        globalThis.__setSendPresetToSillyTavern(async (payload) => {
          sendCalls.push(payload);
          return { success: true, last_sent_to_st: 654.25 };
        });

        const events = [];
        globalThis.window = {
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.activePresetDetail = {
          id: 'global::companion-v2.json',
          preset_kind: 'openai',
          last_sent_to_st: 0,
          family_info: {
            entry_type: 'family',
            default_version_id: 'global::companion-v1.json',
          },
          current_version: {
            id: 'global::companion-v2.json',
            version_label: 'V2',
          },
          available_versions: [
            { id: 'global::companion-v1.json', version_label: 'V1', is_default_version: true },
            { id: 'global::companion-v2.json', version_label: 'V2', is_default_version: false },
          ],
        };

        await reader.sendActivePresetToST();

        if (sendCalls.length !== 1 || sendCalls[0].id !== 'global::companion-v2.json') {
          throw new Error(`expected detail send to use current active version id, got ${JSON.stringify(sendCalls)}`);
        }
        const sentEvent = events.find((event) => event.type === 'preset-sent-to-st');
        if (!sentEvent || sentEvent.detail?.id !== 'global::companion-v2.json') {
          throw new Error(`expected sent event to keep current active version id, got ${JSON.stringify(sentEvent?.detail || null)}`);
        }
        if (Number(reader.activePresetDetail.last_sent_to_st || 0) !== 654.25) {
          throw new Error(`expected active version timestamp to update, got ${reader.activePresetDetail.last_sent_to_st}`);
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_apply_updates_detail_state_without_persisting():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        const saveCalls = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.savePresetExtensions = async (extensions) => {
          saveCalls.push(JSON.parse(JSON.stringify(extensions)));
          return true;
        };
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'alpha' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        const payload = events[0].detail;

        if (payload.editorCommitMode !== 'buffered') {
          throw new Error(`expected open payload to use buffered mode, got ${payload.editorCommitMode}`);
        }
        if (payload.showPersistButton !== true) {
          throw new Error(`expected open payload to show persist button, got ${payload.showPersistButton}`);
        }
        if (payload.extensions === reader.activePresetDetail.extensions) {
          throw new Error('expected open payload extensions to be detached from activePresetDetail');
        }
        if (payload.extensions.regex_scripts === reader.activePresetDetail.extensions.regex_scripts) {
          throw new Error('expected regex scripts payload to be detached from activePresetDetail');
        }
        if (payload.extensions.tavern_helper === reader.activePresetDetail.extensions.tavern_helper) {
          throw new Error('expected tavern helper payload to be detached from activePresetDetail');
        }

        payload.extensions.regex_scripts.push({ script: 'beta' });

        await listeners['advanced-editor-apply'][0]();

        if (saveCalls.length !== 0) {
          throw new Error(`expected apply to avoid persistence, got ${saveCalls.length}`);
        }
        if (JSON.stringify(reader.activePresetDetail.extensions.regex_scripts) !== JSON.stringify([{ script: 'alpha' }, { script: 'beta' }])) {
          throw new Error(`expected apply to update activePresetDetail extensions, got ${JSON.stringify(reader.activePresetDetail.extensions.regex_scripts)}`);
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_persist_calls_save_with_updated_extensions():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        const saveCalls = [];
        let closeEventCount = 0;
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            if (event.type === 'advanced-editor-close') {
              closeEventCount += 1;
            }
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.savePresetExtensions = async (extensions) => {
          saveCalls.push(JSON.parse(JSON.stringify(extensions)));
          return true;
        };
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        events[0].detail.extensions.regex_scripts.push({ script: 'persisted' });

        await listeners['advanced-editor-persist'][0]();

        if (saveCalls.length !== 1) {
          throw new Error(`expected persist to call savePresetExtensions once, got ${saveCalls.length}`);
        }
        if (JSON.stringify(saveCalls[0].regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'persisted' }])) {
          throw new Error(`expected persist payload to include updated extensions, got ${JSON.stringify(saveCalls[0])}`);
        }
        if (JSON.stringify(reader.activePresetDetail.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'persisted' }])) {
          throw new Error(`expected persist to update activePresetDetail extensions, got ${JSON.stringify(reader.activePresetDetail.extensions.regex_scripts)}`);
        }
        if (closeEventCount !== 1) {
          throw new Error(`expected persist success to close advanced editor once, got ${closeEventCount}`);
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_close_modal_clears_pending_advanced_editor_handlers():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { deviceType: 'desktop', showToast() {} } };
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        reader.closeModal();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected closeModal to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected closeModal to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (reader.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected closeModal to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (reader.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected closeModal to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_reopen_replaces_stale_apply_and_persist_listeners():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        const firstApplyHandler = listeners['advanced-editor-apply'][0];
        const firstPersistHandler = listeners['advanced-editor-persist'][0];

        reader.openAdvancedExtensions();

        if ((listeners['advanced-editor-apply'] || []).length !== 1) {
          throw new Error(`expected reopen to keep one apply listener, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 1) {
          throw new Error(`expected reopen to keep one persist listener, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (listeners['advanced-editor-apply'][0] === firstApplyHandler) {
          throw new Error('expected reopen to replace stale apply listener');
        }
        if (listeners['advanced-editor-persist'][0] === firstPersistHandler) {
          throw new Error('expected reopen to replace stale persist listener');
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_apply_cleans_both_session_listeners():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        await listeners['advanced-editor-apply'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected apply to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected apply to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (reader.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (reader.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_persist_cleans_both_session_listeners():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.savePresetExtensions = async () => true;
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        await listeners['advanced-editor-persist'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected persist to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected persist to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (reader.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (reader.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_detail_reader_runtime_advanced_extensions_persist_failure_keeps_editor_open():
    run_preset_detail_reader_runtime_check(
        """
        const listeners = {};
        const events = [];
        let closeEventCount = 0;
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
          dispatchEvent(event) {
            events.push(event);
            if (event.type === 'advanced-editor-close') {
              closeEventCount += 1;
            }
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };

        reader.$store = { global: { showToast() {} } };
        reader.savePresetExtensions = async () => false;
        reader.activePresetDetail = {
          id: 'preset-1',
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        reader.openAdvancedExtensions();
        events[0].detail.extensions.regex_scripts.push({ script: 'failed-save' });

        await listeners['advanced-editor-persist'][0]();

        if (JSON.stringify(reader.activePresetDetail.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'failed-save' }])) {
          throw new Error(`expected persist failure to keep in-memory update, got ${JSON.stringify(reader.activePresetDetail.extensions.regex_scripts)}`);
        }
        if (closeEventCount !== 0) {
          throw new Error(`expected persist failure to avoid closing advanced editor, got ${closeEventCount}`);
        }
        """
    )


def test_preset_detail_reader_runtime_mobile_prompt_selection_enters_detail_view_and_returns_to_list():
    run_preset_detail_reader_runtime_check(
        """
        reader.$store.global.deviceType = 'mobile';
        reader.updatePresetLayoutMetrics = () => {};
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello' },
                prompt_meta: { order_index: 0 },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        if (reader.showMobileDetailView !== false) {
          throw new Error(`expected mobile reader to start in list view, got ${reader.showMobileDetailView}`);
        }

        reader.showRightPanel = false;
        reader.selectPrompt('prompt:main');

        if (reader.showMobileDetailView !== true) {
          throw new Error('expected prompt selection on mobile to enter detail view');
        }
        if (reader.showRightPanel) {
          throw new Error('expected mobile prompt detail flow to avoid showRightPanel');
        }
        if (reader.activeContextItem?.id !== 'prompt:main') {
          throw new Error(`expected prompt context to remain active, got ${reader.activeContextItem?.id}`);
        }

        reader.closeMobileDetailView();

        if (reader.showMobileDetailView !== false) {
          throw new Error('expected closeMobileDetailView to return mobile prompt flow to list view');
        }
        if (reader.activeContextItem?.id !== 'prompt:main') {
          throw new Error(`expected closing mobile detail view to preserve prompt context, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_initializes_prompt_workspace_and_switches_active_context():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello' },
                prompt_meta: { order_index: 1 },
              },
              {
                id: 'prompt:summary',
                type: 'prompt',
                group: 'prompts',
                title: 'Summary Prompt',
                payload: { identifier: 'summary', content: 'world' },
                prompt_meta: { order_index: 0 },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        if (reader.activeWorkspace !== 'prompts') {
          throw new Error(`expected prompt workspace by default, got ${reader.activeWorkspace}`);
        }
        if (reader.activePromptId !== 'prompt:summary') {
          throw new Error(`expected first ordered prompt active, got ${reader.activePromptId}`);
        }
        if (reader.activeContextItem?.id !== 'prompt:summary') {
          throw new Error(`expected active context to use prompt item, got ${reader.activeContextItem?.id}`);
        }

        reader.selectWorkspace('extensions');
        if (reader.activeGroup !== 'extensions') {
          throw new Error(`expected workspace switch to sync activeGroup, got ${reader.activeGroup}`);
        }
        if (reader.activeItemId !== 'ext:memory') {
          throw new Error(`expected extension item selection, got ${reader.activeItemId}`);
        }
        if (reader.activeContextItem?.id !== 'ext:memory') {
          throw new Error(`expected generic context item after workspace switch, got ${reader.activeContextItem?.id}`);
        }

        reader.selectPrompt('prompt:main');
        if (reader.activeWorkspace !== 'prompts') {
          throw new Error(`expected prompt selection to switch workspace, got ${reader.activeWorkspace}`);
        }
        if (reader.activePromptId !== 'prompt:main') {
          throw new Error(`expected prompt selection to persist id, got ${reader.activePromptId}`);
        }
        if (reader.activeContextItem?.id !== 'prompt:main') {
          throw new Error(`expected prompt context after selectPrompt, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_mobile_generic_selection_enters_detail_view():
    run_preset_detail_reader_runtime_check(
        """
        reader.$store.global.deviceType = 'mobile';
        reader.updatePresetLayoutMetrics = () => {};
        reader.activePresetDetail = {
          reader_view: {
            family: 'generic',
            groups: [
              { id: 'extensions', label: 'Extensions' },
              { id: 'structured_objects', label: 'Structured Objects' },
            ],
            items: [
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: { total_count: 1 },
          },
        };

        reader.initializeReaderState();
        reader.showRightPanel = false;
        reader.selectItem('ext:memory');

        if (reader.showMobileDetailView !== true) {
          throw new Error('expected generic selection on mobile to enter detail view');
        }
        if (reader.showRightPanel) {
          throw new Error('expected mobile generic detail flow to avoid showRightPanel');
        }
        if (reader.activeContextItem?.id !== 'ext:memory') {
          throw new Error(`expected generic context to stay active, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_preserves_items_when_reader_groups_are_missing():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'generic',
            groups: null,
            items: [
              {
                id: 'field:temperature',
                type: 'field',
                group: 'scalar_fields',
                title: 'Temperature',
                payload: { value: 0.7 },
              },
            ],
            stats: { total_count: 1 },
          },
        };

        if (reader.readerItems.length !== 1) {
          throw new Error(`expected reader items to survive missing groups, got ${reader.readerItems.length}`);
        }
        if (reader.readerGroups.length !== 0) {
          throw new Error(`expected missing groups to degrade to empty group list, got ${reader.readerGroups.length}`);
        }

        reader.initializeReaderState();
        if (reader.activeItem?.id !== 'field:temperature') {
          throw new Error(`expected first item to remain selectable, got ${reader.activeItem?.id}`);
        }
        if (reader.readerStats.total_count !== 1) {
          throw new Error(`expected stats total count to stay intact, got ${reader.readerStats.total_count}`);
        }
        """
    )


def test_preset_detail_reader_runtime_reports_slider_percent_for_mirrored_profile():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          raw_data: {
            openai_max_context: 4096,
            openai_max_tokens: 1200,
            stream_openai: true,
            reasoning_effort: 'medium',
          },
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'output_and_reasoning', label: '输出与推理' },
            ],
            fields: {
              openai_max_context: {
                canonical_key: 'openai_max_context',
                storage_key: 'openai_max_context',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 0,
                max: 8192,
              },
              openai_max_tokens: {
                canonical_key: 'openai_max_tokens',
                storage_key: 'openai_max_tokens',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 0,
                max: 2400,
              },
              stream_openai: {
                canonical_key: 'stream_openai',
                storage_key: 'stream_openai',
                section: 'output_and_reasoning',
                control: 'checkbox',
              },
            },
          },
          reader_view: { family: 'prompt_manager', groups: [], items: [], stats: {} },
        };

        if (!reader.isMirroredProfileReader) {
          throw new Error('expected mirrored profile reader');
        }
        if (reader.mirroredProfileSections.length !== 1) {
          throw new Error(`expected one mirrored section, got ${reader.mirroredProfileSections.length}`);
        }
        if (reader.getProfileFieldPercent('openai_max_context') !== 50) {
          throw new Error(`expected 50 percent, got ${reader.getProfileFieldPercent('openai_max_context')}`);
        }
        if (!reader.isProfileFieldToggle(reader.editorProfile.fields.stream_openai)) {
          throw new Error('expected checkbox detection to work');
        }
        """
    )


def test_preset_detail_reader_runtime_filters_reader_mirrored_sections_for_scalar_workspace():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          raw_data: {},
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'prompt_manager', label: '提示词管理' },
              { id: 'core_sampling', label: '核心采样' },
              { id: 'extensions_and_advanced', label: '扩展与高级' },
            ],
            fields: {},
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'scalar_fields', label: '基础字段' },
            ],
            items: [],
            scalar_workspace: {
              sections: [],
              field_map: {},
            },
            stats: {},
          },
        };

        reader.initializeReaderState();
        reader.selectWorkspace('scalar_fields');

        const sectionIds = reader.readerMirroredProfileSections.map((section) => section.id);
        if (JSON.stringify(sectionIds) !== JSON.stringify(['core_sampling'])) {
          throw new Error(`expected filtered mirrored sections to equal ['core_sampling'], got ${JSON.stringify(sectionIds)}`);
        }
        """
    )


def test_preset_detail_reader_runtime_reads_mirrored_fields_when_object_keys_differ_from_canonical_key():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          raw_data: {
            openai_max_context: 4096,
            stream_openai: true,
          },
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'output_and_reasoning', label: '输出与推理' },
            ],
            fields: {
              context_window: {
                canonical_key: 'openai_max_context',
                storage_key: 'openai_max_context',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 0,
                max: 8192,
              },
              stream_toggle: {
                canonical_key: 'stream_openai',
                storage_key: 'stream_openai',
                section: 'output_and_reasoning',
                control: 'checkbox',
              },
            },
          },
          reader_view: { family: 'prompt_manager', groups: [], items: [], stats: {} },
        };

        const fields = reader.getProfileSectionFields('output_and_reasoning');
        if (fields.length !== 2) {
          throw new Error(`expected two mirrored fields, got ${fields.length}`);
        }
        if (reader.getProfileFieldValue('openai_max_context') !== 4096) {
          throw new Error(`expected storage-key lookup to resolve mirrored value, got ${reader.getProfileFieldValue('openai_max_context')}`);
        }
        if (reader.getProfileFieldPercent('openai_max_context') !== 50) {
          throw new Error(`expected canonical lookup percent to remain 50, got ${reader.getProfileFieldPercent('openai_max_context')}`);
        }
        if (!reader.isProfileFieldToggle(fields.find((field) => field.canonical_key === 'stream_openai'))) {
          throw new Error('expected checkbox field lookup by canonical key to work');
        }
        """
    )


def test_preset_detail_reader_runtime_uses_scalar_workspace_overview_and_keeps_hidden_fields_out_of_search():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'scalar_fields', label: '基础字段' },
            ],
            items: [
              { id: 'field:temp', type: 'field', group: 'scalar_fields', title: 'temp', source_key: 'temp', value_path: 'temp', payload: { key: 'temp', value: 0.8 } },
              { id: 'field:top_a', type: 'field', group: 'scalar_fields', title: 'top_a', source_key: 'top_a', value_path: 'top_a', payload: { key: 'top_a', value: 0.3 } },
            ],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
                { id: 'penalties', label: '惩罚参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
              },
              hidden_fields: ['top_a'],
              aliases: { temp: 'temperature' },
            },
            stats: {},
          },
          raw_data: { temp: 0.8, top_a: 0.3 },
        };

        reader.activeWorkspace = 'scalar_fields';
        reader.initializeReaderState();

        if (!Array.isArray(reader.scalarWorkspaceSections)) {
          throw new Error(`expected scalarWorkspaceSections helper array, got ${JSON.stringify(reader.scalarWorkspaceSections)}`);
        }
        if (typeof reader.getScalarWorkspaceFieldValue !== 'function') {
          throw new Error(`expected getScalarWorkspaceFieldValue helper function, got ${typeof reader.getScalarWorkspaceFieldValue}`);
        }
        if (!reader.isScalarWorkspaceReader) {
          throw new Error('expected scalar workspace reader mode to activate');
        }
        if (JSON.stringify(reader.scalarWorkspaceSections.map((section) => section.id)) !== JSON.stringify(['core_sampling', 'penalties'])) {
          throw new Error(`expected scalar workspace sections, got ${JSON.stringify(reader.scalarWorkspaceSections.map((section) => section.id))}`);
        }
        if (reader.getScalarWorkspaceFieldValue('temp') !== 0.8) {
          throw new Error(`expected field read by storage key, got ${JSON.stringify(reader.getScalarWorkspaceFieldValue('temp'))}`);
        }

        reader.updateSearchTerm('top_a');
        if (reader.scalarWorkspaceVisibleFieldEntries.length !== 0) {
          throw new Error(`expected hidden field search to stay hidden, got ${JSON.stringify(reader.scalarWorkspaceVisibleFieldEntries)}`);
        }

        reader.updateSearchTerm('温度');
        if (reader.scalarWorkspaceVisibleFieldEntries.length !== 1) {
          throw new Error(`expected visible scalar workspace search result, got ${JSON.stringify(reader.scalarWorkspaceVisibleFieldEntries)}`);
        }
        """
    )


def test_preset_detail_reader_runtime_scalar_workspace_does_not_leak_hidden_scalar_item_into_active_context():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'scalar_fields', label: '基础字段' },
            ],
            items: [
              { id: 'field:temp', type: 'field', group: 'scalar_fields', title: 'temp', source_key: 'temp', value_path: 'temp', payload: { key: 'temp', value: 0.8 } },
              { id: 'field:top_a', type: 'field', group: 'scalar_fields', title: 'top_a', source_key: 'top_a', value_path: 'top_a', payload: { key: 'top_a', value: 0.3 } },
            ],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
              },
              hidden_fields: ['top_a'],
              aliases: { temp: 'temperature' },
            },
            stats: {},
          },
          raw_data: { temp: 0.8, top_a: 0.3 },
        };

        reader.activeWorkspace = 'scalar_fields';
        reader.initializeReaderState();
        reader.searchTerm = 'top_a';
        reader.refreshReaderCollections();

        if (reader.filteredItems.length !== 0) {
          throw new Error(`expected generic filtered items to stay empty in scalar workspace hidden-field search, got ${JSON.stringify(reader.filteredItems.map((item) => item.id))}`);
        }
        if (reader.activeItem !== null) {
          throw new Error(`expected no active generic item in scalar workspace hidden-field search, got ${reader.activeItem?.id}`);
        }
        if (reader.activeContextItem !== null) {
          throw new Error(`expected no active context item leak for hidden scalar field, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_scalar_workspace_visible_count_tracks_visible_workspace_entries():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'scalar_fields', label: '基础字段' },
            ],
            items: [
              { id: 'field:temp', type: 'field', group: 'scalar_fields', title: 'temp', source_key: 'temp', value_path: 'temp', payload: { key: 'temp', value: 0.8 } },
              { id: 'field:rep_pen', type: 'field', group: 'scalar_fields', title: 'rep_pen', source_key: 'rep_pen', value_path: 'rep_pen', payload: { key: 'rep_pen', value: 1.1 } },
            ],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
                { id: 'penalties', label: '惩罚参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
                rep_pen: { canonical_key: 'repetition_penalty', section: 'penalties', label: '重复惩罚', storage_key: 'rep_pen', editor: 'number' },
              },
              hidden_fields: [],
              aliases: { temp: 'temperature', rep_pen: 'repetition_penalty' },
            },
            stats: {},
          },
          raw_data: { temp: 0.8, rep_pen: 1.1 },
        };

        reader.activeWorkspace = 'scalar_fields';
        reader.initializeReaderState();

        if (reader.scalarWorkspaceVisibleFieldEntries.length !== 2) {
          throw new Error(`expected two visible scalar workspace entries, got ${reader.scalarWorkspaceVisibleFieldEntries.length}`);
        }
        if (reader.readerStats.visible_count !== 2) {
          throw new Error(`expected visible_count to track scalar workspace entries, got ${reader.readerStats.visible_count}`);
        }
        """
    )


def test_preset_detail_reader_runtime_scalar_workspace_total_count_tracks_workspace_entry_total():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'scalar_fields', label: '基础字段' },
              { id: 'extensions', label: '扩展设置' },
            ],
            items: [
              { id: 'prompt:main', type: 'prompt', group: 'prompts', title: 'Main', payload: { identifier: 'main', content: 'hello' }, prompt_meta: { order_index: 0 } },
              { id: 'field:temp', type: 'field', group: 'scalar_fields', title: 'temp', source_key: 'temp', value_path: 'temp', payload: { key: 'temp', value: 0.8 } },
              { id: 'field:rep_pen', type: 'field', group: 'scalar_fields', title: 'rep_pen', source_key: 'rep_pen', value_path: 'rep_pen', payload: { key: 'rep_pen', value: 1.1 } },
              { id: 'ext:memory', type: 'extension', group: 'extensions', title: 'Memory', payload: { value: { enabled: true } } },
            ],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
                { id: 'penalties', label: '惩罚参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
                rep_pen: { canonical_key: 'repetition_penalty', section: 'penalties', label: '重复惩罚', storage_key: 'rep_pen', editor: 'number' },
              },
              hidden_fields: [],
              aliases: { temp: 'temperature', rep_pen: 'repetition_penalty' },
            },
            stats: { total_count: 4 },
          },
          raw_data: { temp: 0.8, rep_pen: 1.1 },
        };

        reader.activeWorkspace = 'scalar_fields';
        reader.initializeReaderState();

        if (reader.readerStats.visible_count !== 2) {
          throw new Error(`expected scalar workspace visible_count 2, got ${reader.readerStats.visible_count}`);
        }
        if (reader.readerStats.total_count !== 2) {
          throw new Error(`expected scalar workspace total_count 2, got ${reader.readerStats.total_count}`);
        }

        reader.updateSearchTerm('温度');
        if (reader.readerStats.visible_count !== 1) {
          throw new Error(`expected narrowed scalar visible_count 1, got ${reader.readerStats.visible_count}`);
        }
        if (reader.readerStats.total_count !== 2) {
          throw new Error(`expected scalar workspace total_count to stay 2 after search, got ${reader.readerStats.total_count}`);
        }
        """
    )


def test_preset_detail_reader_runtime_does_not_borrow_item_from_other_workspace_when_filters_hide_target_items():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'generic',
            groups: [
              { id: 'scalar_fields', label: 'Fields' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'field:temperature',
                type: 'field',
                group: 'scalar_fields',
                title: 'Temperature',
                payload: { value: 0.7 },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: { total_count: 2 },
          },
        };

        reader.initializeReaderState();
        reader.uiFilter = 'structured';
        reader.searchTerm = 'missing';
        reader.selectWorkspace('extensions');

        if (reader.activeGroup !== 'extensions') {
          throw new Error(`expected workspace switch to target extensions, got ${reader.activeGroup}`);
        }
        if (reader.filteredItems.length !== 0) {
          throw new Error(`expected zero visible items in filtered workspace, got ${reader.filteredItems.length}`);
        }
        if (reader.activeItemId !== '') {
          throw new Error(`expected no active item id when workspace has no visible items, got ${reader.activeItemId}`);
        }
        if (reader.activeItem !== null) {
          throw new Error(`expected active item to stay empty instead of borrowing another workspace item, got ${reader.activeItem?.id}`);
        }
        if (reader.activeContextItem !== null) {
          throw new Error(`expected active context item to stay empty, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_falls_back_to_default_prompt_depth_for_invalid_values():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: {
                  identifier: 'main',
                  content: 'hello',
                  injection_position: 1,
                  injection_depth: 'oops',
                },
                prompt_meta: { order_index: 0 },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        const label = reader.getPromptPositionLabel(reader.activePromptItem);
        if (label !== '聊天中 @ 4') {
          throw new Error(`expected invalid prompt depth to fall back to 4, got ${label}`);
        }
        """
    )


def test_preset_detail_reader_runtime_localizes_prompt_labels_and_hides_marker_placeholder_preview():
    run_preset_detail_reader_runtime_check(
        """
        const relativePrompt = {
          id: 'prompt:relative',
          type: 'prompt',
          group: 'prompts',
          title: 'Relative Prompt',
          payload: {
            identifier: 'relative',
            content: 'relative content',
            injection_position: 0,
          },
          prompt_meta: { order_index: 0, is_enabled: true, is_marker: false },
        };
        const markerPrompt = {
          id: 'prompt:marker',
          type: 'prompt',
          group: 'prompts',
          title: 'Marker Prompt',
          payload: {
            identifier: 'marker',
            marker: true,
            injection_position: 1,
            injection_depth: 'bad-depth',
          },
          prompt_meta: { order_index: 1, is_enabled: false, is_marker: true },
        };

        const relativeLabel = reader.getPromptPositionLabel(relativePrompt);
        if (relativeLabel !== '相对') {
          throw new Error(`expected relative prompt label to be localized, got ${relativeLabel}`);
        }

        const markerPreview = reader.getPromptPreview(markerPrompt);
        if (markerPreview !== '') {
          throw new Error(`expected marker preview to be empty, got ${JSON.stringify(markerPreview)}`);
        }

        const inChatLabel = reader.getPromptPositionLabel(markerPrompt);
        if (inChatLabel !== '聊天中 @ 4') {
          throw new Error(`expected invalid in-chat depth to fall back to 4, got ${inChatLabel}`);
        }
        """
    )


def test_preset_detail_reader_runtime_exposes_full_prompt_detail_without_preview_truncation():
    run_preset_detail_reader_runtime_check(
        """
        const longContent = 'A'.repeat(300);
        const promptItem = {
          id: 'prompt:long',
          type: 'prompt',
          group: 'prompts',
          title: 'Long Prompt',
          payload: {
            identifier: 'long',
            content: longContent,
          },
          prompt_meta: { order_index: 0, is_marker: false },
        };
        const markerPrompt = {
          id: 'prompt:marker',
          type: 'prompt',
          group: 'prompts',
          title: 'Marker Prompt',
          payload: {
            identifier: 'marker',
            marker: true,
            content: longContent,
          },
          prompt_meta: { order_index: 1, is_marker: true },
        };

        const preview = reader.getPromptPreview(promptItem);
        const fullDetail = reader.getPromptFullDetail(promptItem);
        const markerFullDetail = reader.getPromptFullDetail(markerPrompt);

        if (preview.length >= longContent.length) {
          throw new Error(`expected preview to remain truncated, got length ${preview.length}`);
        }
        if (fullDetail !== longContent) {
          throw new Error(`expected full prompt detail to keep complete content, got length ${fullDetail.length}`);
        }
        if (markerFullDetail !== '') {
          throw new Error(`expected marker prompt full detail to stay empty, got ${JSON.stringify(markerFullDetail)}`);
        }
        """
    )


def test_preset_detail_reader_runtime_accepts_zero_depth_and_rejects_negative_or_fractional_depths():
    run_preset_detail_reader_runtime_check(
        """
        const zeroDepthPrompt = {
          id: 'prompt:zero',
          type: 'prompt',
          group: 'prompts',
          title: 'Zero Depth Prompt',
          payload: {
            identifier: 'zero',
            injection_position: 1,
            injection_depth: 0,
          },
          prompt_meta: { order_index: 0, is_marker: false },
        };
        const negativeDepthPrompt = {
          id: 'prompt:negative',
          type: 'prompt',
          group: 'prompts',
          title: 'Negative Depth Prompt',
          payload: {
            identifier: 'negative',
            injection_position: 1,
            injection_depth: -1,
          },
          prompt_meta: { order_index: 1, is_marker: false },
        };
        const fractionalDepthPrompt = {
          id: 'prompt:fractional',
          type: 'prompt',
          group: 'prompts',
          title: 'Fractional Depth Prompt',
          payload: {
            identifier: 'fractional',
            injection_position: 1,
            injection_depth: 2.5,
          },
          prompt_meta: { order_index: 2, is_marker: false },
        };

        if (reader.getPromptPositionLabel(zeroDepthPrompt) !== '聊天中 @ 0') {
          throw new Error(`expected zero depth to stay valid, got ${reader.getPromptPositionLabel(zeroDepthPrompt)}`);
        }
        if (reader.getPromptPositionLabel(negativeDepthPrompt) !== '聊天中 @ 4') {
          throw new Error(`expected negative depth to fall back to 4, got ${reader.getPromptPositionLabel(negativeDepthPrompt)}`);
        }
        if (reader.getPromptPositionLabel(fractionalDepthPrompt) !== '聊天中 @ 4') {
          throw new Error(`expected fractional depth to fall back to 4, got ${reader.getPromptPositionLabel(fractionalDepthPrompt)}`);
        }
        """
    )


def test_preset_detail_reader_runtime_filters_prompts_by_marker_and_search():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                summary: 'system · 启用 · 相对位置',
                payload: { identifier: 'main', content: 'hello' },
                prompt_meta: { order_index: 0, is_enabled: true, is_marker: false },
              },
              {
                id: 'prompt:worldInfoAfter',
                type: 'prompt',
                group: 'prompts',
                title: 'World Info (after)',
                summary: 'prompt · 禁用 · 相对位置 · 预留字段',
                payload: { identifier: 'worldInfoAfter', marker: true },
                prompt_meta: { order_index: 1, is_enabled: false, is_marker: true },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        reader.setUiFilter('marker');

        if (reader.promptFilteredItems.length !== 1) {
          throw new Error(`expected marker filter to keep one prompt, got ${reader.promptFilteredItems.length}`);
        }
        if (reader.promptFilteredItems[0].id !== 'prompt:worldInfoAfter') {
          throw new Error(`expected marker filter to keep worldInfoAfter, got ${reader.promptFilteredItems[0]?.id}`);
        }
        if (reader.readerStats.visible_count !== 1) {
          throw new Error(`expected prompt workspace visible count to follow filtered prompts, got ${reader.readerStats.visible_count}`);
        }

        reader.setUiFilter('all');
        reader.updateSearchTerm('worldinfoafter');
        if (reader.promptFilteredItems.length !== 1) {
          throw new Error(`expected search to narrow prompt workspace to one item, got ${reader.promptFilteredItems.length}`);
        }
        if (reader.promptFilteredItems[0].id !== 'prompt:worldInfoAfter') {
          throw new Error(`expected prompt search to match identifier, got ${reader.promptFilteredItems[0]?.id}`);
        }
        if (reader.readerStats.visible_count !== 1) {
          throw new Error(`expected prompt search visible count to stay in sync, got ${reader.readerStats.visible_count}`);
        }
        """
    )


def test_preset_detail_reader_runtime_explicit_handlers_refresh_prompt_filters_and_search():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello' },
                prompt_meta: { order_index: 0, is_enabled: true, is_marker: false },
              },
              {
                id: 'prompt:worldInfoAfter',
                type: 'prompt',
                group: 'prompts',
                title: 'World Info (after)',
                payload: { identifier: 'worldInfoAfter', content: 'world info' },
                prompt_meta: { order_index: 1, is_enabled: false, is_marker: false },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        reader.setUiFilter('enabled');

        if (JSON.stringify(reader.promptFilteredItems.map((item) => item.id)) !== JSON.stringify(['prompt:main'])) {
          throw new Error(`expected enabled handler filter to keep only prompt:main, got ${JSON.stringify(reader.promptFilteredItems.map((item) => item.id))}`);
        }
        if (reader.readerStats.visible_count !== 1) {
          throw new Error(`expected enabled handler filter visible count 1, got ${reader.readerStats.visible_count}`);
        }

        reader.setUiFilter('all');
        reader.updateSearchTerm('worldinfoafter');

        if (JSON.stringify(reader.promptFilteredItems.map((item) => item.id)) !== JSON.stringify(['prompt:worldInfoAfter'])) {
          throw new Error(`expected search handler to keep only prompt:worldInfoAfter, got ${JSON.stringify(reader.promptFilteredItems.map((item) => item.id))}`);
        }
        if (reader.readerStats.visible_count !== 1) {
          throw new Error(`expected search handler visible count 1, got ${reader.readerStats.visible_count}`);
        }
        """
    )


def test_preset_detail_reader_runtime_normalizes_filters_when_switching_workspaces():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello' },
                prompt_meta: { order_index: 0, is_enabled: true, is_marker: false },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: {},
          },
        };

        reader.initializeReaderState();
        reader.setUiFilter('marker');
        reader.selectWorkspace('extensions');

        if (reader.uiFilter !== 'all') {
          throw new Error(`expected prompt-only filter to reset for generic workspace, got ${reader.uiFilter}`);
        }

        reader.setUiFilter('structured');
        reader.selectWorkspace('prompts');

        if (reader.uiFilter !== 'all') {
          throw new Error(`expected generic-only filter to reset for prompts workspace, got ${reader.uiFilter}`);
        }
        """
    )


def test_preset_detail_reader_js_caches_prompt_collections_and_exposes_marker_icon_helpers():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'promptItemsCache:' in source
    assert 'orderedPromptItemsCache:' in source
    assert 'promptFilteredItemsCache:' in source
    assert 'filteredItemsCache:' in source
    assert 'activePromptItemCache:' in source
    assert 'activeItemCache:' in source
    assert 'activeContextItemCache:' in source
    assert 'readerStatsCache:' in source
    assert 'refreshReaderCollections() {' in source
    assert 'syncActiveReaderSelections() {' in source
    assert 'getPromptMarkerVisual(item) {' in source
    assert 'getPromptMarkerIcon(item) {' in source
    assert 'return this.orderedPromptItemsCache;' in source
    assert 'return this.promptFilteredItemsCache;' in source
    assert 'return this.filteredItemsCache;' in source


def test_preset_detail_reader_js_exposes_explicit_control_handlers_for_reader_caches():
    source = read_project_file('static/js/components/presetDetailReader.js')

    assert 'updateSearchTerm(value) {' in source
    assert 'setUiFilter(filterId) {' in source


def test_preset_detail_reader_runtime_clears_hidden_generic_selection_when_filtered_workspace_is_empty():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello world' },
                prompt_meta: { order_index: 0 },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: { total_count: 2 },
          },
        };

        reader.initializeReaderState();
        reader.selectWorkspace('extensions');
        if (reader.activeContextItem?.id !== 'ext:memory') {
          throw new Error(`expected extensions workspace to select ext:memory, got ${reader.activeContextItem?.id}`);
        }

        reader.updateSearchTerm('missing');
        if (reader.filteredItems.length !== 0) {
          throw new Error(`expected empty filtered generic workspace, got ${reader.filteredItems.length}`);
        }
        if (reader.activeItemId !== '') {
          throw new Error(`expected cleared activeItemId for hidden generic item, got ${reader.activeItemId}`);
        }
        if (reader.activeItem !== null) {
          throw new Error(`expected activeItem to clear instead of keeping hidden generic item, got ${reader.activeItem?.id}`);
        }
        if (reader.activeContextItem !== null) {
          throw new Error(`expected activeContextItem to clear for empty filtered generic workspace, got ${reader.activeContextItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_runtime_refreshes_cached_prompt_collections_and_marker_icons():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'extensions', label: 'Extensions' },
            ],
            items: [
              {
                id: 'prompt:main',
                type: 'prompt',
                group: 'prompts',
                title: 'Main Prompt',
                payload: { identifier: 'main', content: 'hello world', injection_position: 0 },
                prompt_meta: { order_index: 1, is_enabled: true },
              },
              {
                id: 'prompt:scenario',
                type: 'prompt',
                group: 'prompts',
                title: 'Scenario Anchor',
                payload: { identifier: 'scenario', injection_position: 1, injection_depth: 6 },
                prompt_meta: { order_index: 0, is_marker: true, is_enabled: false },
              },
              {
                id: 'ext:memory',
                type: 'extension',
                group: 'extensions',
                title: 'Memory',
                payload: { value: { enabled: true } },
              },
            ],
            stats: { total_count: 3 },
          },
        };

        reader.initializeReaderState();
        if (JSON.stringify(reader.orderedPromptItems.map((item) => item.id)) !== JSON.stringify(['prompt:scenario', 'prompt:main'])) {
          throw new Error(`expected ordered prompt cache, got ${JSON.stringify(reader.orderedPromptItems.map((item) => item.id))}`);
        }
        if (reader.activeContextItem?.id !== 'prompt:scenario') {
          throw new Error(`expected prompt selection cache to use first ordered prompt, got ${reader.activeContextItem?.id}`);
        }

        reader.setUiFilter('marker');
        if (JSON.stringify(reader.promptFilteredItems.map((item) => item.id)) !== JSON.stringify(['prompt:scenario'])) {
          throw new Error(`expected marker filter cache to keep only scenario marker, got ${JSON.stringify(reader.promptFilteredItems.map((item) => item.id))}`);
        }

        const visual = reader.getPromptMarkerVisual(reader.promptFilteredItems[0]);
        if (visual.key !== 'scenario') {
          throw new Error(`expected scenario marker visual, got ${JSON.stringify(visual)}`);
        }
        if (!reader.getPromptMarkerIcon(reader.promptFilteredItems[0]).includes('<svg')) {
          throw new Error('expected inline svg marker icon output');
        }

        reader.selectWorkspace('extensions');
        if (reader.filteredItems.length !== 1 || reader.activeContextItem?.id !== 'ext:memory') {
          throw new Error(`expected generic workspace cache after workspace switch, got ${JSON.stringify({ filtered: reader.filteredItems.map((item) => item.id), active: reader.activeContextItem?.id })}`);
        }
        """
    )


def test_preset_detail_reader_template_uses_reader_view_three_column_layout_contracts():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-if="!isPromptWorkspaceReader"' in source
    assert "x-show=\"($store.global.deviceType !== 'mobile' && showRightPanel) || ($store.global.deviceType === 'mobile' && showMobileDetailView)\"" in source
    assert 'x-text="activeItem?.title ||' in source
    assert 'readerStats.prompt_count' not in source
    assert 'readerStats.unknown_count' not in source


def test_preset_detail_reader_template_removes_prompt_order_unknown_and_metadata_sections():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'Payload' not in source
    assert 'Revision' not in source
    assert '保存能力' not in source
    assert 'x-if="activeItem?.type === \'prompt_order\'"' not in source
    assert "x-if=\"activeItem?.group === 'unknown_fields' || activeItem?.type === 'unknown_field'\"" not in source


def test_preset_detail_reader_flow_keeps_full_content_in_right_panel_only():
    js_source = read_project_file('static/js/components/presetDetailReader.js')
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'line-clamp-3' in source or 'line-clamp-4' in source
    assert 'getItemDetailContent(' not in js_source
    assert 'getItemFullDetail(item) {' in js_source
    assert 'x-text="getItemFullDetail(activeItem)"' in source
    assert 'Summary' not in source
    assert 'Prompt Detail' not in source


def test_preset_detail_reader_template_adds_prompt_workspace_branch_contracts():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-if="isPromptWorkspaceReader"' in source
    assert "@click=\"selectWorkspace('prompts')\"" in source
    assert 'x-text="getPromptPreview(item)"' in source
    assert 'x-text="getPromptPositionLabel(item)"' in source
    assert 'x-text="activeContextItem?.title ||' in source
    assert 'x-text="getPromptFullDetail(activeContextItem)"' in source
    assert "!isPromptWorkspaceReader || activeWorkspace === 'prompts'" in source
    assert "activeWorkspace === 'prompts' && orderedPromptItems.length > 0 && promptFilteredItems.length === 0" in source
    assert '`${promptFilteredItems.length} / ${orderedPromptItems.length}`' in source or '`${promptFilteredItems.length}/${orderedPromptItems.length}`' in source
    assert '`${orderedPromptItems.length} / ${readerStats.total_count}`' not in source
    assert '启用' in source
    assert '禁用' in source
    assert '预留字段' in source


def test_preset_detail_reader_template_exposes_scalar_workspace_overview_branch():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-if="isScalarWorkspaceReader"' in source
    assert '参数一览' in source
    assert '参数概览' not in source
    assert '高级参数摘要' not in source


def test_preset_detail_reader_template_exposes_null_safe_mirrored_profile_snapshot_branch():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert '提示词列表' in source
    assert 'Prompt Workspace' not in source
    assert 'x-if="isScalarWorkspaceReader && isMirroredProfileReader && editorProfile"' in source
    assert 'x-for="section in readerMirroredProfileSections"' in source
    assert 'editorProfile.label || editorProfile.id' not in source
    assert "editorProfile?.label || editorProfile?.id || '参数一览'" in source or 'editorProfile?.label || editorProfile?.id || "参数一览"' in source


def test_preset_detail_reader_template_uses_user_facing_copy_without_developer_mirror_labels():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'Reader Workspace' not in source
    assert 'profile schema' not in source
    assert '只读展示当前基础字段对应的镜像参数。' not in source
    assert '提示词列表' in source
    assert '当前预设暂无可展示内容' in source


def test_preset_detail_reader_runtime_degrades_safely_when_editor_profile_is_missing():
    run_preset_detail_reader_runtime_check(
        """
        reader.activePresetDetail = {
          raw_data: {
            name: 'Test Preset',
          },
          reader_view: {
            family: 'generic',
            groups: [
              { id: 'basic', label: '基础信息' },
            ],
            items: [
              {
                id: 'field:name',
                type: 'field',
                group: 'basic',
                title: '名称',
                payload: { value: 'Test Preset' },
              },
            ],
            stats: { total_count: 1 },
          },
        };

        if (reader.editorProfile != null) {
          throw new Error(`expected missing editor_profile to keep editorProfile nullish, got ${JSON.stringify(reader.editorProfile)}`);
        }
        if (reader.isMirroredProfileReader !== false) {
          throw new Error(`expected missing editor_profile to disable mirrored reader mode, got ${reader.isMirroredProfileReader}`);
        }

        reader.initializeReaderState();

        if (reader.editorProfile != null) {
          throw new Error(`expected editorProfile to remain nullish after initializeReaderState, got ${JSON.stringify(reader.editorProfile)}`);
        }
        if (reader.isMirroredProfileReader !== false) {
          throw new Error(`expected mirrored reader mode to stay false after initializeReaderState, got ${reader.isMirroredProfileReader}`);
        }
        if (reader.activeItem?.id !== 'field:name') {
          throw new Error(`expected generic field item to remain active, got ${reader.activeItem?.id}`);
        }
        """
    )


def test_preset_detail_reader_template_exposes_non_scalar_mirrored_snapshot_kinds():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "field.control === 'sortable_string_list'" in source
    assert "field.control === 'prompt_workspace'" in source


def test_preset_detail_reader_template_scalar_workspace_header_uses_visible_count():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'isScalarWorkspaceReader' in source
    assert '`${readerStats.visible_count} / ${readerStats.total_count}`' in source
    assert "isPromptWorkspaceReader && activeWorkspace === 'prompts' ? `${promptFilteredItems.length} / ${orderedPromptItems.length}` : `${filteredItems.length} / ${readerStats.total_count}`" not in source


def test_preset_detail_reader_template_removes_marker_placeholder_copy():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert '占位用预留字段，不承载提示词内容' not in source


def test_preset_detail_reader_template_keeps_generic_items_available_for_non_prompt_workspaces():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-show="activeWorkspace !== \"prompts\""' in source or "x-show=\"activeWorkspace !== 'prompts'\"" in source
    assert 'x-text="getItemValuePreview(activeContextItem)"' in source
    assert 'x-text="getItemFullDetail(activeContextItem)"' in source
    assert "x-if=\"activeContextItem?.group !== 'prompts'\"" in source


def test_preset_detail_reader_template_renders_marker_icons_switches_and_inner_scroll_regions():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-html="getPromptMarkerIcon(item)"' in source
    assert 'x-html="getPromptMarkerIcon(activeContextItem)"' in source
    assert 'class="flex-1 min-h-0"' in source
    assert 'class="flex-1 min-h-0 p-4"' not in source
    assert 'class="h-full min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-3"' in source
    assert 'class="preset-marker-icon-frame flex-shrink-0 text-sky-200"' in source
    assert 'rounded-2xl border border-sky-400/30 bg-sky-500/10' not in source
    assert 'class="relative h-5 w-9 rounded-full transition-colors"' in source
    assert source.count('aria-hidden="true"') >= 4


def test_preset_detail_reader_template_keeps_right_panel_scroll_and_prompt_state_within_bounds():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'class="w-full lg:w-[340px] xl:w-[380px] flex-shrink-0 bg-[var(--bg-sub)] border-l border-[var(--border-light)] flex flex-col min-h-0"' in source
    assert 'class="preset-reader-mobile-detail-body flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4"' in source
    assert 'class="min-w-0 flex flex-1 items-start gap-3"' in source


def test_preset_detail_reader_template_prevents_blank_prompt_content_cards_and_shows_prompt_empty_state():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "activeWorkspace === 'prompts' && orderedPromptItems.length > 0 && promptFilteredItems.length === 0" in source
    assert '没有匹配的提示词' in source
    assert "x-if=\"activeContextItem?.group !== 'prompts'\"" in source
    assert "activeContextItem?.group === 'prompts' ? getPromptPreview(activeContextItem) : getItemFullDetail(activeContextItem)" not in source


def test_preset_detail_reader_template_restores_prompt_copy_action_without_reopening_generic_content_card():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "x-if=\"activeContextItem?.group === 'prompts' && getPromptFullDetail(activeContextItem)\"" in source
    assert '@click="copyText(getPromptFullDetail(activeContextItem), \"条目内容\")"' in source or "@click=\"copyText(getPromptFullDetail(activeContextItem), '条目内容')\"" in source
    assert "x-if=\"activeContextItem?.group !== 'prompts'\"" in source
    assert '@click="copyText(getItemFullDetail(activeContextItem), \"条目内容\")"' in source or "@click=\"copyText(getItemFullDetail(activeContextItem), '条目内容')\"" in source


def test_preset_detail_reader_template_guards_active_item_accesses():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert 'x-if="activeItem?.type === \'prompt_order\'"' not in source
    assert 'x-if="activeItem?.type === \'extension\'"' not in source
    assert 'x-if="activeItem?.type === \'field\'"' not in source
    assert 'x-if="activeItem?.type === \'structured\'"' not in source
    assert 'x-if="activeContextItem?.type === \'extension\'"' in source
    assert 'x-if="activeContextItem?.type === \'field\'"' in source
    assert 'x-if="activeContextItem?.type === \'structured\'"' in source
    assert "x-if=\"activeItem?.group === 'unknown_fields' || activeItem?.type === 'unknown_field'\"" not in source


def test_preset_detail_reader_template_removes_invalid_raw_json_and_restore_default_actions():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert not re.search(r'<button\s+@click="openRawViewer\(\)"[\s\S]*?>[\s\S]*?查看原始 JSON[\s\S]*?</button>', source)
    assert not re.search(r'<button\s+@click="previewRestoreDefault\(\)"[\s\S]*?>[\s\S]*?恢复默认[\s\S]*?</button>', source)
