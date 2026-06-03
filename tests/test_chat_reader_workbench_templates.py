import json
from pathlib import Path
import re
import subprocess
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def run_sidebar_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/sidebar.js'
    node_script = textwrap.dedent(
        """
        import { readFileSync } from 'node:fs';

        const sourcePath = __SOURCE_PATH__;
        let source = readFileSync(sourcePath, 'utf8');
        source = source
          .split(/\\r?\\n/)
          .filter((line) => !line.trim().startsWith('import '))
          .join('\\n');

        globalThis.__sidebarTestState = {
          localStorageState: new Map(),
          windowListeners: [],
          shellClassNames: new Set(),
          rafQueue: [],
        };
        const { localStorageState, windowListeners, shellClassNames, rafQueue } = globalThis.__sidebarTestState;

        const stubs = `
        const createFolder = async () => ({});
        const moveFolder = async () => ({});
        const moveCard = async () => ({});
        const migrateLorebooks = async () => ({});
        globalThis.fetch = async () => ({ json: async () => ({ success: true }) });
        globalThis.requestAnimationFrame = (cb) => {
          globalThis.__sidebarTestState.rafQueue.push(cb);
          return globalThis.__sidebarTestState.rafQueue.length;
        };
        globalThis.cancelAnimationFrame = (id) => {
          if (id > 0 && id <= globalThis.__sidebarTestState.rafQueue.length) {
            globalThis.__sidebarTestState.rafQueue[id - 1] = null;
          }
        };
        globalThis.window = {
          addEventListener(type, handler) {
            globalThis.__sidebarTestState.windowListeners.push({ action: 'add', type, handler });
          },
          removeEventListener(type, handler) {
            globalThis.__sidebarTestState.windowListeners.push({ action: 'remove', type, handler });
          },
          dispatchEvent() {},
        };
        globalThis.document = {
          querySelectorAll() { return []; },
          body: { style: {} },
        };
        globalThis.localStorage = {
          getItem(key) {
            const storage = globalThis.__sidebarTestState.localStorageState;
            return storage.has(key) ? storage.get(key) : null;
          },
          setItem(key, value) {
            globalThis.__sidebarTestState.localStorageState.set(key, String(value));
          },
          removeItem(key) {
            globalThis.__sidebarTestState.localStorageState.delete(key);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.detail = options.detail;
          }
        };
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source),
        );

        const store = {
          global: {
            currentMode: 'cards',
            visibleSidebar: true,
            deviceType: 'desktop',
            allFoldersList: [],
            isolatedCategories: [],
            allTagsPool: [],
            tagIndexActiveCategory: '',
            cardCategorySearchQuery: '',
            wiCategorySearchQuery: '',
            presetCategorySearchQuery: '',
            wiAllFolders: [],
            presetAllFolders: [],
            viewState: {
              filterCategory: '',
              filterTags: [],
              draggedCards: [],
              draggedFolder: '',
              selectedIds: [],
            },
            groupTagsByTaxonomy(tags) {
              return [{ category: '', tags }];
            },
            getTagCategory() {
              return '';
            },
          },
        };

        const component = module.default();
        component.$store = store;
        component.$watch = () => {};
        component.$nextTick = (cb) => cb();
        component.$refs = {
          cardSidebarShell: {
            getBoundingClientRect() { return { height: 500 }; },
            classList: {
              add(name) { shellClassNames.add(name); },
              remove(name) { shellClassNames.delete(name); },
              contains(name) { return shellClassNames.has(name); },
            },
          },
          cardTagsPane: {
            getBoundingClientRect() { return { height: 170 }; },
          },
          cardTagsHeader: {
            getBoundingClientRect() { return { height: 48 }; },
          },
          cardTagCategoryStrip: {
            getBoundingClientRect() { return { height: 34 }; },
          },
          cardTagCloud: {
            clientWidth: 286,
          },
        };

        const flushRaf = () => {
          while (rafQueue.length) {
            const cb = rafQueue.shift();
            if (typeof cb === 'function') cb();
          }
        };

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
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def compact_whitespace(source):
    return re.sub(r'\s+', ' ', source).strip()


def normalize_js_assertion_source(source):
    compact = compact_whitespace(source).replace('"', "'")
    compact = re.sub(r'([({\[])\s+', r'\1', compact)
    compact = re.sub(r'\s+([)}\]])', r'\1', compact)
    compact = re.sub(r'\s*,\s*', ', ', compact)
    return re.sub(r',\s*([)\]}])', r'\1', compact)


def js_contains(source, snippet):
    return normalize_js_assertion_source(snippet) in normalize_js_assertion_source(source)


def extract_css_block(css_source, selector):
    selector_start = css_source.index(selector)
    block_start = css_source.index('{', selector_start)
    block_end = css_source.index('}', block_start)
    return css_source[block_start + 1:block_end]


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
    try:
        function_start = source.index(signature)
        block_start = source.index('{', function_start)
    except ValueError:
        name_match = re.search(r'(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(', signature)
        if not name_match:
            raise ValueError(f'Function signature not found: {signature}')

        function_name = re.escape(name_match.group(1))
        fallback_match = re.search(
            rf'(^|\n)\s*(?:async\s+)?{function_name}\s*\([\s\S]*?\)\s*\{{',
            source,
            re.MULTILINE,
        )
        if not fallback_match:
            raise ValueError(f'Function signature not found: {signature}')
        block_start = fallback_match.end() - 1

    depth = 1
    index = block_start + 1

    while depth > 0:
        current_char = source[index]

        if current_char == '{':
            depth += 1
        elif current_char == '}':
            depth -= 1

        index += 1

    return source[block_start + 1:index - 1]


def extract_chat_reader_shell(template_source):
    shell_start = template_source.index('<div class="chat-reader-modal chat-reader-modal--fullscreen" role="dialog" aria-modal="true" aria-label="聊天阅读器">')
    settings_overlay_start = template_source.index('<div x-show="readerViewSettingsOpen"')
    return template_source[shell_start:settings_overlay_start]


def extract_balanced_tag_block(source, opening_tag):
    block_start = source.index(opening_tag)
    tag_name = opening_tag[1:opening_tag.index(' ')]
    opening_pattern = re.compile(rf'<{tag_name}(?:\s|>)')
    closing_tag = f'</{tag_name}>'
    depth = 0

    for match in opening_pattern.finditer(source, block_start):
        if match.start() == block_start:
            depth = 1
            index = match.end()
            break
    else:
        raise ValueError(f'Opening tag not found: {opening_tag}')

    while depth > 0:
        next_open = opening_pattern.search(source, index)
        next_close = source.find(closing_tag, index)

        if next_close == -1:
            raise ValueError(f'Closing tag not found for: {opening_tag}')

        if next_open and next_open.start() < next_close:
            depth += 1
            index = next_open.end()
            continue

        depth -= 1
        index = next_close + len(closing_tag)

    return source[block_start:index]


def extract_first_chat_message_card(template_source):
    floor_loop_start = template_source.index('<template x-for="message in visibleDetailMessages"')
    floor_markup = template_source[floor_loop_start:]
    return extract_balanced_tag_block(floor_markup, '<article class="chat-message-card"')


def test_header_template_does_not_expose_runtime_inspector_controls():
    header_template = read_project_file('templates/components/header.html')

    assert 'openRuntimeInspector' not in header_template
    assert 'open-runtime-inspector' not in header_template
    assert '运行时检查器' not in header_template
    assert 'title="运行时检查器"' not in header_template
    assert '<div class="menu-label">运行时</div>' not in header_template


def test_mobile_header_keeps_search_mode_inside_primary_search_tools_contract():
    header_template = read_project_file('templates/components/header.html')

    assert 'class="mobile-header-search-tools"' in header_template
    assert 'class="mobile-search-mode-row"' not in header_template
    assert 'class="mobile-search-mode-toggle"' in header_template
    assert (
        'x-show="[\'cards\', \'worldinfo\'].includes(currentMode) && canUseFulltextSearch"'
        in header_template
    )

    mobile_tools_segment = extract_balanced_tag_block(
        header_template,
        '<div class="mobile-header-search-tools">',
    )
    assert 'class="mobile-search-mode-toggle"' in mobile_tools_segment


def test_index_template_does_not_include_runtime_inspector_modal():
    index_template = read_project_file('templates/index.html')

    assert 'runtime_inspector.html' not in index_template
    assert 'runtime_inspector' not in index_template


def test_app_js_does_not_import_or_register_runtime_inspector():
    app_source = read_project_file('static/js/app.js')

    assert 'runtimeInspector' not in app_source
    assert 'runtimeInspector.js' not in app_source


def test_header_component_does_not_wire_runtime_inspector_events():
    header_source = read_project_file('static/js/components/header.js')

    assert 'openRuntimeInspector' not in header_source
    assert 'open-runtime-inspector' not in header_source


def test_worldinfo_grid_and_detail_expose_export_actions():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')
    wi_grid_template = read_project_file('templates/components/grid_wi.html')
    wi_detail_source = read_project_file('static/js/components/wiDetailPopup.js')
    wi_detail_template = read_project_file('templates/modals/detail_wi_popup.html')

    export_grid_block = extract_js_function_block(
        wi_grid_source,
        'async exportWorldInfoItem(item)',
    )
    export_detail_block = extract_js_function_block(
        wi_detail_source,
        'async exportActiveWorldInfo()',
    )

    assert 'downloadFileFromApi(' in export_grid_block
    assert '/api/world_info/export' in export_grid_block
    assert 'source_type: item.source_type || item.type' in export_grid_block
    assert 'file_path: item.path' in export_grid_block
    assert 'card_id: item.card_id' in export_grid_block
    assert 'id: item.id' in export_grid_block
    assert '@click.stop="exportWorldInfoItem(item)"' in wi_grid_template
    assert 'title="导出世界书 JSON"' in wi_grid_template

    assert 'downloadFileFromApi(' in export_detail_block
    assert '/api/world_info/export' in export_detail_block
    assert 'source_type: detail.type' in export_detail_block
    assert 'file_path: detail.path' in export_detail_block
    assert 'card_id: detail.card_id' in export_detail_block
    assert 'id: detail.id' in export_detail_block
    assert '@click="exportActiveWorldInfo()"' in wi_detail_template
    assert 'title="导出 JSON"' in wi_detail_template
    assert re.search(
        r'@click="exportActiveWorldInfo\(\)"[\s\S]*?>[\s\S]*导出[\s\S]*</button>',
        wi_detail_template,
    )


def test_worldinfo_grid_template_splits_footer_meta_and_tools():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    footer_block = extract_balanced_tag_block(
        wi_grid_template,
        '<div class="wi-card-footer"'
    )

    tools_block = extract_balanced_tag_block(
        footer_block,
        '<div class="wi-card-footer-tools"'
    )

    info_index = footer_block.index('wi-card-footer-info')
    tools_index = footer_block.index('wi-card-footer-tools')
    date_index = footer_block.index('wi-card-date-chip')

    assert info_index < date_index < tools_index
    assert 'wi-card-footer-tools-left' in tools_block
    assert 'wi-card-note-tool' in tools_block
    assert 'wi-card-footer-tools-right' in tools_block
    assert 'wi-card-note-state' not in footer_block
    assert 'getWorldInfoNoteState(item)' not in footer_block


def test_preset_grid_and_detail_expose_export_actions():
    preset_grid_source = read_project_file('static/js/components/presetGrid.js')
    preset_grid_template = read_project_file('templates/components/grid_presets.html')
    preset_detail_source = read_project_file('static/js/components/presetDetailReader.js')
    preset_detail_template = read_project_file('templates/modals/detail_preset_popup.html')

    export_grid_block = extract_js_function_block(
        preset_grid_source,
        'async exportPresetItem(item, event = null)',
    )
    export_detail_block = extract_js_function_block(
        preset_detail_source,
        'async exportActivePreset()',
    )

    assert 'downloadFileFromApi(' in export_grid_block
    assert '/api/presets/export' in export_grid_block
    assert 'const targetId = this.getPresetActionTargetId(item)' in export_grid_block
    assert 'id: targetId' in export_grid_block
    assert 'event?.stopPropagation?.()' in export_grid_block
    assert '@click.stop="exportPresetItem(item, $event)"' in preset_grid_template
    assert 'title="导出预设 JSON"' in preset_grid_template

    assert 'downloadFileFromApi(' in export_detail_block
    assert '/api/presets/export' in export_detail_block
    assert 'id: detail.id' in export_detail_block
    assert '@click="exportActivePreset()"' in preset_detail_template
    assert re.search(
        r'@click="exportActivePreset\(\)"[\s\S]*?>\s*导出\s*</button>',
        preset_detail_template,
    )


def test_preset_grid_template_places_selection_left_and_actions_right():
    preset_template = read_project_file('templates/components/grid_presets.html')

    assert 'preset-grid-card' in preset_template
    assert 'preset-card-toolbar' in preset_template
    assert 'class="preset-card-toolbar-actions ml-auto flex items-center gap-1"' in preset_template
    assert 'preset-select-shell' in preset_template
    assert 'title="选择预设"' in preset_template
    assert 'title="删除预设"' in preset_template
    assert 'title="导出预设 JSON"' in preset_template
    assert 'absolute top-0 left-0 w-6 h-6' not in preset_template
    assert 'absolute top-0 left-7 w-6 h-6' not in preset_template


def test_automation_modal_template_exposes_rule_trigger_chip_controls_contract():
    template = read_project_file('templates/modals/automation.html')

    expected_trigger_chips = [
        ('manual_run', '手动执行'),
        ('auto_import', '导入后'),
        ('card_update', '更新角色卡后'),
        ('link_update', '更新来源链接后'),
        ('tag_edit', '手动打标后'),
    ]

    trigger_chip_matches = re.findall(
        r'<button type="button" class="automation-preset-chip"[\s\S]*?</button>',
        template,
    )
    trigger_chip_blocks = [
        block for block in trigger_chip_matches if 'toggleRuleTrigger(rule,' in block
    ]

    assert len(trigger_chip_blocks) == len(expected_trigger_chips)

    for trigger_name, trigger_label in expected_trigger_chips:
        expected_block = f'''
        <button type="button" class="automation-preset-chip"
            :class="ruleHasTrigger(rule, '{trigger_name}') ? 'border-[var(--accent-main)] text-[var(--accent-main)]' : 'text-[var(--text-dim)]'"
            @click="toggleRuleTrigger(rule, '{trigger_name}')">
            {trigger_label}
        </button>
        '''
        assert js_contains(template, expected_block)

    assert '仅勾选的触发场景会参与该规则。' in template


def test_automation_modal_template_updates_trigger_and_rename_help_copy_contract():
    template = read_project_file('templates/modals/automation.html')

    assert '当前状态：全局默认规则' in template
    assert '按规则触发时机和动作类型在不同场景执行' in template
    assert '仅在 upload-file 或 update-from-URL' in template
    assert '用新角色卡内容覆盖已有角色卡时触发' in template
    assert '普通保存详情' in template
    assert '单独更换封面' in template
    assert '修改本地备注' in template
    assert '修改来源链接' in template
    assert '都不会触发' in template
    assert '若想在覆盖更新后重命名' in template
    assert '请在规则上启用“更新角色卡后”' in template
    assert '如果文件名要体现本次更新时间' in template
    assert '优先使用 modified_date' in template
    assert '{% raw %}{{char_name}} - {{char_version|version}} - {{modified_date|date:%Y-%m-%d}}{% endraw %}' in template
    assert 'import_date' in template
    assert '首次导入时命名' in template
    assert 'modified_date 更适合覆盖更新后命名' in template


def test_preset_grid_css_reveals_selection_and_actions_on_hover():
    preset_template = read_project_file('templates/components/grid_presets.html')
    cards_css = read_project_file('static/css/modules/view-cards.css')

    assert 'preset-select-shell' in preset_template
    assert 'preset-card-action-btn is-danger' in preset_template
    assert 'preset-card-action-btn is-export' in preset_template
    assert 'text-red-400' not in preset_template
    assert 'text-sky-300' not in preset_template
    assert '.preset-grid-card:hover .card-select-overlay' in cards_css
    assert '.preset-grid-card:focus-within .card-select-overlay' in cards_css
    assert '.preset-grid-card .preset-card-toolbar-actions' in cards_css
    assert 'visibility: hidden' in cards_css
    assert '.preset-grid-card:hover .preset-card-toolbar-actions' in cards_css
    assert '.preset-grid-card:focus-within .preset-card-toolbar-actions' in cards_css
    assert 'visibility: visible' in cards_css
    assert '.preset-select-shell {' in cards_css
    assert '.preset-select-shell.is-selected {' in cards_css
    assert '.preset-card-action-btn {' in cards_css


def test_preset_grid_source_badge_stays_top_right_and_shifts_left_on_hover():
    preset_template = read_project_file('templates/components/grid_presets.html')
    cards_css = read_project_file('static/css/modules/view-cards.css')

    assert 'preset-card-source-badge' in preset_template
    assert 'absolute right-3 top-3' in preset_template
    assert 'absolute right-3 top-11' not in preset_template
    assert '.preset-card-source-badge {' in cards_css

    badge_block = extract_exact_css_block(cards_css, '.preset-card-source-badge')
    hover_block = extract_exact_css_block(
        cards_css,
        '.preset-grid-card:hover .preset-card-source-badge',
    )
    focus_block = extract_exact_css_block(
        cards_css,
        '.preset-grid-card:focus-within .preset-card-source-badge',
    )

    assert 'right: 0.75rem;' in badge_block
    assert 'top: 0.75rem;' in badge_block
    assert 'transition:' in badge_block
    assert 'right:' in hover_block
    assert 'right:' in focus_block
    assert 'left:' not in hover_block
    assert 'left:' not in focus_block
    assert '.preset-card-action-btn.is-danger {' in cards_css
    assert '.preset-card-action-btn.is-export {' in cards_css
    assert 'html.light-mode .preset-card-action-btn {' in cards_css
    assert 'html.light-mode .preset-card-action-btn.is-danger {' in cards_css
    assert 'html.light-mode .preset-card-action-btn.is-export {' in cards_css
    assert '.preset-card-source-badge {' in cards_css


def test_shared_download_helper_handles_attachment_downloads_and_json_errors():
    download_source = read_project_file('static/js/utils/download.js')

    assert 'export async function downloadFileFromApi(' in download_source
    assert 'response.headers.get("Content-Disposition")' in download_source
    assert 'response.headers.get("content-disposition")' in download_source
    assert 'await response.blob()' in download_source
    assert 'URL.createObjectURL(blob)' in download_source
    assert 'link.download = filename' in download_source
    assert 'response.headers.get("content-type")' in download_source
    assert 'contentType.includes("application/json")' in download_source
    assert 'await response.json()' in download_source
    assert 'throw new Error(' in download_source


def test_advanced_editor_no_longer_listens_for_runtime_inspector_bridge_events():
    advanced_editor_source = read_project_file('static/js/components/advancedEditor.js')

    assert 'runtime-inspector-control' not in advanced_editor_source
    assert 'focus-script-runtime-owner' not in advanced_editor_source


def test_advanced_editor_regex_test_bench_uses_shared_preview_renderer_and_dedicated_runner():
    advanced_editor_source = read_project_file('static/js/components/advancedEditor.js')
    advanced_editor_template = read_project_file('templates/modals/advanced_editor.html')
    run_regex_block = extract_js_function_block(advanced_editor_source, 'runRegexTest() {')

    assert '../utils/regexTestBench.js' in advanced_editor_source
    assert '../utils/dom.js' in advanced_editor_source
    assert 'runRegexTestBenchScript' in advanced_editor_source
    assert 'renderUnifiedPreviewHost' in advanced_editor_source
    assert 'updateMixedPreviewContent' not in advanced_editor_source
    assert 'this.regexTestResult = runRegexTestBenchScript(' in run_regex_block
    assert '❌ 正则表达式错误:' in run_regex_block
    assert 'applyDisplayRules: true' not in advanced_editor_template


def test_chat_reader_css_defines_workbench_theme_tokens():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    reader_overlay_block = extract_css_block(chat_reader_css, '.chat-reader-overlay')
    light_mode_overlay_block = extract_css_block(chat_reader_css, 'html.light-mode .chat-reader-overlay')

    required_tokens = [
        '--chat-reader-accent-soft',
        '--chat-reader-accent-strong',
        '--chat-reader-accent-border',
        '--chat-reader-accent-text',
        '--chat-reader-surface-raised',
        '--chat-reader-surface-selected',
        '--chat-reader-danger-soft',
        '--chat-reader-focus-ring',
    ]

    derived_token_prefixes = [
        '--chat-reader-accent-soft:',
        '--chat-reader-accent-strong:',
        '--chat-reader-accent-border:',
        '--chat-reader-accent-text:',
        '--chat-reader-surface-raised:',
        '--chat-reader-surface-selected:',
        '--chat-reader-focus-ring:',
    ]

    for token in required_tokens:
        assert token in chat_reader_css
        assert token in reader_overlay_block
        assert token in light_mode_overlay_block

    for block in (reader_overlay_block, light_mode_overlay_block):
        for line in block.splitlines():
            stripped_line = line.strip()

            if any(stripped_line.startswith(prefix) for prefix in derived_token_prefixes):
                assert '#' not in stripped_line


def test_chat_reader_icon_buttons_define_focus_visible_state():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '.chat-reader-icon-button:focus-visible' in chat_reader_css
    assert 'outline: 2px solid var(--chat-reader-focus-ring)' in chat_reader_css
    assert 'outline-offset: 2px' in chat_reader_css


def test_chat_reader_css_caps_message_stream_width_with_reader_token():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    reader_overlay_block = extract_css_block(chat_reader_css, '.chat-reader-overlay')
    message_list_block = extract_exact_css_block(chat_reader_css, '.chat-message-list')

    assert '--chat-reader-reading-max-width:' in reader_overlay_block
    assert 'width: 100%;' in message_list_block
    assert 'max-width: var(--chat-reader-reading-max-width);' in message_list_block
    assert 'margin: 0 auto;' in message_list_block


def test_chat_reader_css_flattens_floor_cards_into_stream_sections():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    message_card_block = extract_exact_css_block(chat_reader_css, '.chat-message-card')
    message_card_before_block = extract_exact_css_block(chat_reader_css, '.chat-message-card::before')
    user_card_block = extract_exact_css_block(chat_reader_css, '.chat-message-card.is-user')
    assistant_card_block = extract_exact_css_block(chat_reader_css, '.chat-message-card.is-assistant')
    system_card_block = extract_exact_css_block(chat_reader_css, '.chat-message-card.is-system')

    assert 'border-radius: 0;' in message_card_block
    assert 'padding: 0;' in message_card_block
    assert 'background: transparent;' in message_card_block
    assert 'box-shadow: none;' in message_card_block
    assert 'content: none;' in message_card_before_block
    assert 'background: transparent;' in user_card_block
    assert 'background: transparent;' in assistant_card_block
    assert 'background: transparent;' in system_card_block
    assert '.chat-message-card + .chat-message-card {' in chat_reader_css


def test_chat_reader_css_light_mode_message_cards_do_not_restore_card_shadows():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert not re.search(
        r'html\.light-mode\s+[^\{]*\.chat-message-card[^\{]*\{[^\}]*box-shadow\s*:',
        chat_reader_css,
        re.DOTALL,
    )


def test_chat_reader_template_contains_workbench_regions():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    shell = extract_chat_reader_shell(reader_template)

    shell_pattern = re.compile(
        r'<div class="chat-reader-header" :class=".*?readerResponsiveMode.*?">.*?'
        r'<div class="chat-reader-body" :style="readerBodyGridStyle">.*?'
        r'<aside x-show="readerShowLeftPanel" class="chat-reader-left custom-scrollbar".*?>.*?'
        r'<main class="chat-reader-center custom-scrollbar" :style="readerCenterPaneStyle" @scroll.passive="handleReaderScroll\(\)">.*?'
        r'<aside x-show="readerShowRightPanel" class="chat-reader-right custom-scrollbar" :style="readerRightPaneStyle">',
        re.DOTALL,
    )

    assert shell_pattern.search(shell)
    assert shell.count('<aside ') == 2
    assert shell.index('class="chat-reader-header"') < shell.index('class="chat-reader-body"')
    assert '<div class="chat-reader-body" :style="readerBodyGridStyle">' in shell
    assert '<aside x-show="readerShowLeftPanel" class="chat-reader-left custom-scrollbar"' in shell
    assert '\n            </aside>\n\n            <main class="chat-reader-center custom-scrollbar" :style="readerCenterPaneStyle" @scroll.passive="handleReaderScroll()">' in shell
    assert '\n            </main>\n\n            <aside x-show="readerShowRightPanel" class="chat-reader-right custom-scrollbar" :style="readerRightPaneStyle">' in shell


def test_chat_reader_template_groups_desktop_workbench_controls():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-header-context' in reader_template
    assert 'chat-reader-header-primary' in reader_template
    assert 'chat-reader-header-secondary' in reader_template
    assert 'chat-reader-panel-group' in reader_template
    assert 'chat-reader-danger-zone' in reader_template
    assert 'chat-reader-icon-button' in reader_template


def test_chat_reader_template_includes_mobile_drawer_segments():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'readerMobilePanel' in reader_template
    assert "readerMobilePanel === 'tools'" in reader_template
    assert "readerMobilePanel === 'search'" in reader_template
    assert "readerMobilePanel === 'navigator'" in reader_template


def test_chat_grid_tracks_mobile_reader_panel_state():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'readerMobilePanel' in chat_grid_source


def test_chat_grid_reconciles_reader_panel_state_on_device_type_changes():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'reconcileReaderPanelsForDeviceType' in chat_grid_source
    assert js_contains(chat_grid_source, "this.$watch('$store.global.deviceType'")
    assert 'this.reconcileReaderPanelsForDeviceType();' in chat_grid_source
    assert js_contains(chat_grid_source, "if (responsiveMode === 'mobile')")
    assert js_contains(chat_grid_source, "if (responsiveMode === 'tablet')")
    assert js_contains(
        chat_grid_source,
        "this.readerMobilePanel = this.readerShowLeftPanel ? 'tools' : this.readerRightTab === 'floors' ? 'navigator' : 'search';",
    )
    assert js_contains(chat_grid_source, "this.readerShowLeftPanel = this.readerMobilePanel === 'tools';")
    assert js_contains(chat_grid_source, "this.readerShowRightPanel = true;")


def test_chat_reader_template_keeps_all_nested_modal_entry_points():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    for entry_point in (
        'readerViewSettingsOpen',
        'regexConfigOpen',
        'regexRulePickerOpen',
        'regexPresetPickerOpen',
        'editingFloor',
        'bindPickerOpen',
    ):
        assert entry_point in reader_template


def test_chat_reader_template_keeps_bind_picker_outside_floor_editor_overlay():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    before_bind_picker = reader_template.split('<div x-show="bindPickerOpen"', 1)[0]
    floor_editor_start = before_bind_picker.rfind('<div x-show="editingFloor"')
    floor_editor_block = before_bind_picker[floor_editor_start:]

    assert floor_editor_block.count('<div') == floor_editor_block.count('</div>')
    assert 'style="z-index: calc(var(--z-topmost) - 1);"' in reader_template.split(
        '<div x-show="bindPickerOpen"', 1
    )[1].split('>', 1)[0]


def test_chat_reader_template_exposes_reader_status_and_accessibility_hooks():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'role="dialog"' in reader_template
    assert 'aria-modal="true"' in reader_template
    assert 'aria-label="聊天阅读器"' in reader_template
    assert 'role="status"' in reader_template
    assert 'aria-live="polite"' in reader_template
    assert 'role="alert"' in reader_template
    assert 'aria-live="assertive"' in reader_template
    assert 'aria-label="关闭工具栏"' in reader_template
    assert ':aria-label="readerMobilePanelCloseLabel"' in reader_template
    assert 'aria-label="关闭聊天阅读器"' in reader_template
    assert ":aria-label=\"isBookmarked(message.floor) ? '取消收藏楼层' : '收藏楼层'\"" in reader_template
    assert '危险操作 · 删除会直接移除当前聊天记录' in reader_template
    assert 'role="note"' in reader_template
    assert 'readerShellStatusText' in reader_template
    assert 'readerSaveFeedbackTone' in reader_template
    assert "readerMobilePanelCloseLabel" in reader_template
    assert ':aria-label="readerMobilePanelCloseLabel"' in reader_template
    assert ':title="readerMobilePanelCloseLabel"' in reader_template
    assert '@keydown.escape.window.prevent="readerViewSettingsOpen = false"' in reader_template
    assert '@keydown.escape.window.prevent="closeRegexConfig()"' in reader_template
    assert '@keydown.escape.window.prevent="closeFloorEditor()"' in reader_template
    assert '@keydown.escape.window.prevent="closeBindPicker()"' in reader_template
    assert '@keydown.escape.window.prevent="closeRegexRulePicker()"' in reader_template
    assert '@keydown.escape.window.prevent="closeRegexPresetPicker()"' in reader_template
    assert '选择绑定规则' in reader_template
    assert '选择预设' in reader_template
    assert 'openRegexRulePicker()' in reader_template
    assert 'openRegexPresetPicker()' in reader_template


def test_chat_grid_resets_reader_feedback_tone_to_steady_state():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(chat_grid_source, "setReaderFeedbackTone(tone = 'neutral')")
    assert js_contains(
        chat_grid_source,
        "if (tone === 'error' || tone === 'danger' || tone === 'success')",
    )
    assert "this.readerSaveFeedbackTone = this.replaceStatus || this.regexConfigStatus ? 'neutral' : 'neutral';" not in chat_grid_source
    assert "this.readerSaveFeedbackTone = this.replaceStatus || this.regexConfigStatus ? 'neutral' : 'neutral'" not in chat_grid_source
    assert js_contains(chat_grid_source, 'this.setReaderFeedbackTone();')


def test_chat_reader_css_defines_distinct_tablet_and_mobile_breakpoints():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '@media (max-width: 1179px)' in chat_reader_css
    assert '@media (max-width: 899px)' in chat_reader_css


def test_chat_reader_template_keeps_header_identity_and_action_groups():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-header-main' in reader_template
    assert 'chat-reader-header-context' in reader_template
    assert 'chat-reader-header-actions' in reader_template
    assert 'chat-reader-header-tools' in reader_template
    assert 'chat-reader-shell-status-text' in reader_template


def test_chat_reader_css_promotes_shell_status_to_second_header_row():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    header_block = extract_exact_css_block(chat_reader_css, '.chat-reader-header')
    main_block = extract_exact_css_block(chat_reader_css, '.chat-reader-header-main')
    actions_block = extract_exact_css_block(chat_reader_css, '.chat-reader-header-actions')
    shell_status_block = extract_exact_css_block(chat_reader_css, '.chat-reader-shell-status')

    assert 'flex-wrap: wrap' in header_block
    assert 'align-items: stretch' in header_block
    assert 'flex: 1 1 34rem' in main_block
    assert 'min-width: min(100%, 24rem)' in main_block
    assert 'max-width: 100%' in actions_block
    assert 'flex: 1 0 100%' in shell_status_block
    assert 'margin-top: 0' in shell_status_block


def test_chat_reader_css_keeps_tablet_actions_in_single_wrapping_row():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    tablet_block = extract_media_block(chat_reader_css, '@media (max-width: 1179px)')

    tablet_actions_block = extract_exact_css_block(tablet_block, '.chat-reader-header-actions')
    tablet_primary_block = extract_exact_css_block(tablet_block, '.chat-reader-header-primary')
    tablet_tools_block = extract_exact_css_block(tablet_block, '.chat-reader-header-tools')

    assert 'justify-content: flex-start' in tablet_actions_block
    assert 'align-items: center' in tablet_actions_block
    assert 'flex-direction: row' in tablet_primary_block
    assert 'align-items: center' in tablet_primary_block
    assert 'justify-content: flex-start' in tablet_tools_block


def test_chat_reader_css_rebalances_header_rows_at_narrow_widths():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    tablet_block = extract_media_block(chat_reader_css, '@media (max-width: 1179px)')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-header-main,\n    .chat-reader-header-actions,\n    .chat-reader-header-context,\n    .chat-reader-header-primary,\n    .chat-reader-header-tools,\n    .chat-reader-header-stats {' not in tablet_block

    header_block = extract_css_block(tablet_block, '.chat-reader-header')
    assert 'flex-wrap: wrap' in header_block
    assert 'align-items: stretch' in header_block
    assert '.chat-grid-toolbar-actions,\n    .chat-reader-header,\n    .chat-reader-header-main {' not in tablet_block

    assert '.chat-reader-title-wrap {' in tablet_block
    assert 'width: 100%' in extract_css_block(tablet_block, '.chat-reader-title-wrap')

    title_block = extract_css_block(tablet_block, '.chat-reader-title')
    assert 'overflow-wrap: break-word' in title_block
    assert 'word-break: keep-all' in title_block

    assert '.chat-reader-header-actions {' in tablet_block
    tablet_actions_block = extract_css_block(tablet_block, '.chat-reader-header-actions')
    assert 'width: 100%;' in tablet_actions_block
    assert 'flex-wrap: wrap;' in tablet_actions_block

    assert '.chat-reader-shell-status {' in tablet_block
    tablet_status_block = extract_css_block(tablet_block, '.chat-reader-shell-status')
    assert 'display: flex;' in tablet_status_block
    assert 'width: 100%;' in tablet_status_block
    assert 'flex-basis: 100%;' in tablet_status_block
    assert 'margin-top: 0;' in tablet_status_block

    assert '.chat-reader-header-main,' in mobile_block
    assert '.chat-reader-header-actions,' in mobile_block
    assert '.chat-reader-header-primary {' in mobile_block
    assert 'width: 100%;' in mobile_block
    assert '.chat-reader-header-tools {' in mobile_block
    mobile_tools_block = extract_css_block(mobile_block, '.chat-reader-header-tools')
    assert 'flex-direction: row;' in mobile_tools_block
    assert 'justify-content: flex-start' in mobile_tools_block


def test_chat_grid_mobile_reader_panel_state_keeps_one_active_panel():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(chat_grid_source, "this.readerShowLeftPanel = active === 'tools';")
    assert js_contains(
        chat_grid_source,
        "this.readerShowRightPanel = active === 'search' || active === 'navigator';",
    )
    assert 'this.readerShowRightPanel = Boolean(active);' not in chat_grid_source


def test_chat_grid_reader_responsive_mode_uses_reactive_device_type_instead_of_window_width():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(chat_grid_source, 'const deviceType = this.$store.global.deviceType;')
    assert js_contains(chat_grid_source, "if (deviceType === 'mobile')")
    assert js_contains(chat_grid_source, "if (deviceType === 'tablet')")
    assert 'window.innerWidth < 900' not in chat_grid_source
    assert 'window.innerWidth < 1180' not in chat_grid_source


def test_chat_grid_reader_body_grid_style_drives_desktop_tablet_and_mobile_layouts_from_panel_state():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(chat_grid_source, "return 'grid-template-columns: minmax(0, 1fr);';")
    assert js_contains(
        chat_grid_source,
        'return `grid-template-columns: ${leftWidth}px minmax(0, 1fr);`;',
    )
    assert js_contains(
        chat_grid_source,
        'return `grid-template-columns: minmax(0, 1fr) ${rightWidth}px;`;',
    )
    assert js_contains(
        chat_grid_source,
        'return `grid-template-columns: ${leftWidth}px minmax(0, 1fr) ${rightWidth}px;`;',
    )


def test_chat_reader_template_assigns_dynamic_grid_columns_to_center_and_right_panes():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert ":style=\"readerCenterPaneStyle\"" in reader_template
    assert ":style=\"readerRightPaneStyle\"" in reader_template
    assert ":style=\"readerLeftPaneStyle\"" in reader_template


def test_chat_reader_template_keeps_floor_anchor_article_and_actions():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    floor_markup = extract_first_chat_message_card(reader_template)
    header_block = extract_balanced_tag_block(floor_markup, '<div class="chat-message-head">')

    assert '<article class="chat-message-card"' in floor_markup
    assert ':data-chat-floor="message.floor"' in floor_markup

    for action_hook in (
        '@click="scrollToFloor(message.floor)"',
        '@click="toggleBookmark(message)"',
        '@click="openMessageAsAppStage(message)"',
        '@click="openFloorEditor(message)"',
    ):
        assert action_hook in header_block


def test_chat_reader_template_wraps_floor_content_in_message_body():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert '<div class="chat-message-body">' in reader_template


def test_chat_reader_template_keeps_header_actions_ahead_of_message_body():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    floor_markup = extract_first_chat_message_card(reader_template)

    assert floor_markup.index('class="chat-message-head"') < floor_markup.index('class="chat-message-body"')


def test_chat_reader_template_places_timebar_inside_message_body():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    floor_markup = extract_first_chat_message_card(reader_template)
    body_block = extract_balanced_tag_block(floor_markup, '<div class="chat-message-body">')

    assert 'class="chat-message-timebar"' in body_block


def test_worldinfo_editor_template_exposes_three_at_depth_role_entries():
    wi_editor_template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert '@层级 (System)' in wi_editor_template
    assert '@层级 (User)' in wi_editor_template
    assert '@层级 (Assistant)' in wi_editor_template
    assert 'getEditorPositionSelectValue(activeEditorEntry)' in wi_editor_template
    assert "updateEditorPositionFromSelect(activeEditorEntry, $event.target.value)" in wi_editor_template
    assert '4 - @层级 (At Depth)' not in wi_editor_template


def test_chat_reader_css_keeps_floor_chip_as_primary_reader_anchor():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    floor_chip_block = extract_exact_css_block(chat_reader_css, '.chat-floor-chip')

    assert 'padding: 0.34rem 0.62rem;' in floor_chip_block
    assert 'font-weight: 700;' in floor_chip_block


def test_chat_reader_css_softens_bookmark_button_and_secondary_floor_actions():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    bookmark_toggle_block = extract_exact_css_block(chat_reader_css, '.chat-bookmark-toggle')
    secondary_floor_chip_block = extract_exact_css_block(
        chat_reader_css,
        '.chat-message-floor-wrap .chat-floor-chip:not(:first-child)',
    )
    light_mode_secondary_floor_chip_block = extract_exact_css_block(
        chat_reader_css,
        'html.light-mode .chat-message-floor-wrap .chat-floor-chip:not(:first-child)',
    )

    assert 'background: transparent;' in bookmark_toggle_block
    assert 'border-color: transparent;' in bookmark_toggle_block
    assert 'color: var(--text-dim);' in bookmark_toggle_block

    assert 'padding: 0.28rem 0.52rem;' in secondary_floor_chip_block
    assert 'font-weight: 600;' in secondary_floor_chip_block
    assert 'color: color-mix(in srgb, var(--text-dim), var(--text-main) 22%);' in secondary_floor_chip_block

    assert 'color: #475569;' in light_mode_secondary_floor_chip_block


def test_chat_reader_css_mobile_drawer_starts_below_header_instead_of_centering_content():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert 'padding: calc(var(--chat-reader-header-height) + 0.55rem) 0.85rem 1rem;' not in mobile_block
    assert 'top: var(--chat-reader-header-height);' in mobile_block
    assert 'padding: 0.85rem 0.85rem 1rem;' in mobile_block


def test_chat_reader_template_moves_mobile_meta_out_of_the_header_shell():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'readerShellStatusLineText' in reader_template
    assert 'x-show="readerResponsiveMode === \'mobile\'"' in reader_template
    assert '聊天概览' in reader_template


def test_chat_reader_css_compacts_mobile_header_for_reading_first_layout():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-header {' in mobile_block
    assert 'padding: 0.62rem 0.72rem;' in mobile_block
    assert '.chat-reader-header-main {' in mobile_block
    assert 'flex: 1 1 auto;' in mobile_block
    assert '.chat-reader-header-actions {' in mobile_block
    assert 'align-items: center;' in mobile_block
    assert '.chat-reader-header-tools {' in mobile_block
    assert 'flex-direction: row;' in mobile_block
    assert '.chat-reader-header-secondary {' in mobile_block
    assert 'position: absolute;' in mobile_block


def test_chat_reader_css_mobile_toggle_buttons_use_compact_chip_widths():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-toggle {' in mobile_block
    assert 'width: auto;' in mobile_block
    assert 'min-width: 0;' in mobile_block
    assert '.chat-toolbar-btn--primary.chat-reader-mobile-save {' in mobile_block


def test_chat_reader_template_removes_duplicate_top_stats_and_keeps_single_status_row():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-header-stats' not in reader_template
    assert 'x-text="readerShellStatusLineText"' in reader_template
    assert 'chat-reader-state-pill' not in reader_template
    assert 'x-text="readerViewportStatusText"' not in reader_template.split('chat-reader-header', 1)[1].split('chat-reader-body', 1)[0]
    assert 'x-text="readerAnchorStatusText"' not in reader_template.split('chat-reader-header', 1)[1].split('chat-reader-body', 1)[0]


def test_chat_grid_exposes_status_line_text_with_message_count_and_anchor_summary():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'get readerShellStatusLineText() {' in chat_grid_source
    assert 'activeChat?.message_count' in chat_grid_source
    assert 'readerAnchorStatusText' in chat_grid_source


def test_chat_reader_template_exposes_semi_auto_anchor_mode_in_both_anchor_control_groups():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    anchor_mode_groups = re.findall(
        r'<div class="chat-reader-option-group-label">锚点模式</div>\s*<div class="chat-inline-actions">(.*?)</div>',
        reader_template,
        re.DOTALL,
    )

    assert len(anchor_mode_groups) >= 2
    assert sum('半自动迁移' in group for group in anchor_mode_groups) >= 2
    assert sum("@click=\"setReaderAnchorMode('semi_auto')\"" in group for group in anchor_mode_groups) >= 2


def test_chat_reader_template_reasoningDefaultCollapsed_view_strategy_control_matches_approved_label():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    settings_modal = extract_balanced_tag_block(
        reader_template,
        '<div x-show="readerViewSettingsOpen"',
    )

    assert re.search(
        r'<label class="chat-reader-field">\s*<span>Reasoning 默认折叠</span>\s*<label class="chat-inline-checkbox">.*?<input type="checkbox" x-model="readerViewSettings\.reasoningDefaultCollapsed">',
        settings_modal,
        re.DOTALL,
    )


def test_chat_reader_template_autoCollapseLongCode_view_strategy_control_uses_settings_modal_checkbox_structure():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    settings_modal = extract_balanced_tag_block(
        reader_template,
        '<div x-show="readerViewSettingsOpen"',
    )

    assert re.search(
        r'<label class="chat-reader-field">\s*<span>长代码自动折叠</span>\s*<label class="chat-inline-checkbox">.*?<input type="checkbox" x-model="readerViewSettings\.autoCollapseLongCode">',
        settings_modal,
        re.DOTALL,
    )


def test_chat_reader_css_exposes_reasoning_and_code_collapse_primitives():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    for selector in (
        '.chat-message-reasoning',
        '.chat-message-reasoning-summary',
        '.chat-message-code-collapse',
        '.chat-message-meta-flags',
    ):
        assert selector in chat_reader_css


def test_chat_reader_css_positions_mobile_close_button_in_header_corner():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-header {' in mobile_block
    assert 'position: sticky;' in mobile_block or 'position: sticky' in mobile_block
    assert '.chat-reader-header-secondary {' in mobile_block
    assert 'position: absolute;' in mobile_block
    assert 'top: 0.62rem;' in mobile_block
    assert 'right: 0.72rem;' in mobile_block


def test_chat_grid_mobile_reader_toggles_can_close_same_panel_on_repeat_tap():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    toggle_block = extract_js_function_block(chat_grid_source, 'toggleReaderPanel(side) {')
    set_mobile_block = extract_js_function_block(chat_grid_source, 'setReaderMobilePanel(panel) {')

    assert "const isSamePanelOpen = this.readerMobilePanel === panel;" in toggle_block
    assert "&& this.readerShowRightPanel" not in toggle_block
    assert "if (this.readerMobilePanel === normalized) {" in set_mobile_block
    assert 'this.hideReaderPanels();' in set_mobile_block


def test_chat_grid_scroll_to_floor_closes_mobile_drawers_before_showing_target_floor():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    scroll_block = extract_js_function_block(chat_grid_source, "async scrollToFloor(floor, persist = true, behavior = 'smooth', anchorSource = READER_ANCHOR_SOURCES.JUMP) {")

    assert js_contains(
        scroll_block,
        "const shouldHideMobilePanel = this.readerResponsiveMode === 'mobile' && Boolean(this.readerMobilePanel);",
    )
    assert 'if (shouldHideMobilePanel) {' in scroll_block
    assert 'this.hideReaderPanels();' in scroll_block


def test_chat_reader_css_enables_touch_scrolling_in_mobile_reading_column():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '.chat-reader-center {' in chat_reader_css
    assert 'touch-action: pan-y;' in chat_reader_css
    assert '-webkit-overflow-scrolling: touch;' in chat_reader_css
    assert 'overscroll-behavior-y: contain;' in chat_reader_css


def test_chat_reader_css_uses_theme_surface_backgrounds_for_mobile_drawers():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert 'background: var(--bg-panel);' in mobile_block
    assert 'border-top: 1px solid var(--border-main);' in mobile_block
    assert 'backdrop-filter: blur(16px);' not in mobile_block
    assert '-webkit-backdrop-filter: blur(16px);' not in mobile_block


def test_chat_grid_scroll_element_to_top_uses_container_rect_delta_instead_of_offset_top_math():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    scroll_block = extract_js_function_block(chat_grid_source, "scrollElementToTop(el, behavior = 'smooth') {")

    assert 'const containerRect = container.getBoundingClientRect();' in scroll_block
    assert 'const elementRect = el.getBoundingClientRect();' in scroll_block
    assert js_contains(
        scroll_block,
        'const top = Math.max(0, container.scrollTop + elementRect.top - containerRect.top - 12);',
    )
    assert 'el.offsetTop - container.offsetTop - 12' not in scroll_block


def test_chat_reader_css_mobile_shell_keeps_main_reader_area_as_scroll_container():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-modal {' in mobile_block
    assert 'height: 100dvh;' in mobile_block
    assert '.chat-reader-body {' in mobile_block
    assert 'flex: 1 1 auto;' in mobile_block
    assert 'min-height: 0;' in mobile_block
    assert '.chat-reader-center {' in mobile_block
    assert 'overflow-y: auto;' in mobile_block
    assert '-webkit-overflow-scrolling: touch;' in mobile_block


def test_chat_reader_css_mobile_stream_uses_tight_safe_gutters():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    center_block = extract_exact_css_block(mobile_block, '.chat-reader-center')
    list_block = extract_exact_css_block(mobile_block, '.chat-message-list')
    card_spacing_block = extract_exact_css_block(mobile_block, '.chat-message-card + .chat-message-card')

    assert 'padding: 0.55rem 0.45rem 1rem;' in center_block
    assert 'max-width: none;' in list_block
    assert 'margin-top: 1.1rem;' in card_spacing_block
    assert 'padding-top: 1rem;' in card_spacing_block


def test_chat_reader_css_mobile_floor_header_wraps_actions_and_meta():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    head_block = extract_exact_css_block(mobile_block, '.chat-message-head')
    floor_wrap_block = extract_exact_css_block(mobile_block, '.chat-message-floor-wrap')
    meta_block = extract_exact_css_block(mobile_block, '.chat-message-meta')

    assert 'flex-wrap: wrap;' in head_block
    assert 'flex-wrap: wrap;' in floor_wrap_block
    assert 'width: 100%;' in meta_block
    assert 'align-items: flex-start;' in meta_block
    assert 'text-align: left;' in meta_block


def test_chat_reader_css_tablet_stream_keeps_moderate_reading_cap():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    tablet_block = extract_media_block(chat_reader_css, '@media (max-width: 1179px)')

    list_block = extract_exact_css_block(tablet_block, '.chat-message-list')

    assert 'max-width: 64rem;' in list_block


def test_chat_reader_css_mobile_nested_modals_expose_internal_scroll_regions():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-nested-modal,' in mobile_block
    assert 'display: flex;' in mobile_block
    assert 'flex-direction: column;' in mobile_block
    assert 'overflow: hidden;' in mobile_block
    assert '.chat-reader-editor-grid,' in mobile_block
    assert 'overflow-y: auto;' in mobile_block
    assert '.chat-reader-regex-help-body,' in mobile_block
    assert '.chat-reader-floor-preview {' in mobile_block


def test_layout_css_adds_light_mode_mobile_header_and_footer_surfaces():
    layout_css = read_project_file('static/css/modules/layout.css')

    assert 'html.light-mode .header-bar,' in layout_css
    assert 'html.light-mode .pagination-bar {' in layout_css


def test_header_listens_for_global_mobile_menu_close_requests():
    header_source = read_project_file('static/js/components/header.js')

    assert 'window.addEventListener(' in header_source
    assert 'close-header-mobile-menu' in header_source
    assert 'this.closeMobileMenu();' in header_source


def test_chat_grid_closes_mobile_navigation_chrome_before_showing_reader():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    open_detail_block = extract_js_function_block(chat_grid_source, 'async openChatDetail(item) {')

    assert js_contains(open_detail_block, "if (this.$store.global.deviceType === 'mobile') {")
    assert 'this.$store.global.visibleSidebar = false;' in open_detail_block
    assert js_contains(open_detail_block, "document.body.style.overflow = '';")
    assert js_contains(
        open_detail_block,
        "window.dispatchEvent(new CustomEvent('close-header-mobile-menu'));",
    )


def test_chat_grid_closes_mobile_navigation_chrome_before_opening_reader_nested_modals():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    for signature in (
        'openRegexConfig() {',
        'openRegexHelp() {',
        'openFloorEditor(message) {',
        'openRegexRulePicker() {',
        'openRegexPresetPicker() {',
        'async openBindPicker(item) {',
    ):
        block = extract_js_function_block(chat_grid_source, signature)
        assert js_contains(block, "if (this.$store.global.deviceType === 'mobile') {")
        assert 'this.$store.global.visibleSidebar = false;' in block
        assert js_contains(block, "document.body.style.overflow = '';")
        assert js_contains(
            block,
            "window.dispatchEvent(new CustomEvent('close-header-mobile-menu'));",
        )


def test_chat_grid_temporarily_releases_document_scroll_lock_while_reader_is_open():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    helper_block = extract_js_function_block(chat_grid_source, 'setMobileReaderDocumentScrollState(enabled = false) {')
    open_detail_block = extract_js_function_block(chat_grid_source, 'async openChatDetail(item) {')
    close_detail_block = extract_js_function_block(chat_grid_source, 'closeChatDetail() {')

    assert js_contains(helper_block, "document.documentElement.style.overflow = enabled ? 'auto' : '';")
    assert js_contains(helper_block, "document.body.style.overflow = enabled ? 'auto' : '';")
    assert js_contains(helper_block, "document.body.style.height = enabled ? 'auto' : '';")
    assert 'this.setMobileReaderDocumentScrollState(true);' in open_detail_block
    assert 'this.setMobileReaderDocumentScrollState(false);' in close_detail_block


def test_chat_reader_css_marks_mobile_scroll_regions_as_touch_pan_targets():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '.chat-reader-modal,' in chat_reader_css
    assert '.chat-reader-regex-help-body,' in chat_reader_css
    assert '.chat-reader-editor-grid,' in chat_reader_css
    assert '.chat-reader-floor-preview,' in chat_reader_css
    assert '.chat-bind-results {' in chat_reader_css
    assert 'touch-action: pan-y;' in chat_reader_css


def test_chat_grid_collapses_mobile_header_layout_height_when_header_is_hidden():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    metrics_block = extract_js_function_block(chat_grid_source, 'updateReaderLayoutMetrics() {')

    assert js_contains(
        metrics_block,
        "const effectiveHeaderHeight = this.readerResponsiveMode === 'mobile' && this.readerMobileHeaderHidden",
    )
    assert "? 0" in metrics_block
    assert js_contains(
        metrics_block,
        "root.style.setProperty('--chat-reader-header-height', `${effectiveHeaderHeight}px`);",
    )


def test_chat_grid_exposes_scoped_html_formatter_and_shadow_renderer_to_alpine():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'formatScopedDisplayedHtml' in chat_grid_source
    assert 'updateShadowContent' in chat_grid_source
    assert "from \"../utils/stDisplayFormatter.js\"" in chat_grid_source or "from '../utils/stDisplayFormatter.js'" in chat_grid_source
    assert 'updateShadowContent,' in chat_grid_source
    assert 'formatScopedDisplayedHtml,' in chat_grid_source


def test_chat_reader_css_mobile_hidden_header_releases_layout_space():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert '.chat-reader-header.is-mobile-hidden {' in mobile_block
    assert 'min-height: 0;' in mobile_block
    assert 'max-height: 0;' in mobile_block
    assert 'padding-top: 0;' in mobile_block
    assert 'padding-bottom: 0;' in mobile_block
    assert 'border-bottom-width: 0;' in mobile_block
    assert 'margin-bottom: 0;' in mobile_block


def test_chat_reader_css_mobile_header_defines_transition_for_smoother_hide_and_show():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    header_block = extract_exact_css_block(chat_reader_css, '.chat-reader-header')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 899px)')

    assert 'transition:' in header_block
    assert 'transform 0.24s cubic-bezier(0.22, 1, 0.36, 1)' in header_block
    assert 'opacity 0.18s ease' in header_block
    assert 'max-height 0.24s cubic-bezier(0.22, 1, 0.36, 1)' in header_block
    assert 'padding 0.24s cubic-bezier(0.22, 1, 0.36, 1)' in header_block
    assert 'border-color 0.18s ease' in header_block
    assert 'will-change: transform, opacity, max-height;' in header_block
    assert 'transform: translateY(calc(-100% - 0.35rem)) scaleY(0.98);' in mobile_block
    assert 'transform-origin: top center;' in mobile_block


def test_chat_grid_updates_layout_metrics_when_mobile_header_visibility_flips():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    helper_block = extract_js_function_block(chat_grid_source, 'syncReaderMobileHeaderVisibility(container) {')
    scroll_block = extract_js_function_block(chat_grid_source, 'handleReaderScroll() {')

    assert 'const previousHidden = this.readerMobileHeaderHidden;' in helper_block
    assert 'if (previousHidden !== this.readerMobileHeaderHidden) {' in helper_block
    assert 'this.updateReaderLayoutMetrics();' in helper_block
    assert 'this.syncReaderMobileHeaderVisibility(center);' in scroll_block


def test_chat_grid_extracts_mobile_header_scroll_logic_for_scroll_and_page_modes():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    helper_block = extract_js_function_block(chat_grid_source, 'syncReaderMobileHeaderVisibility(container) {')
    scroll_block = extract_js_function_block(chat_grid_source, 'handleReaderScroll() {')

    assert 'const nextTop = Math.max(0, Number(container.scrollTop || 0));' in helper_block
    assert 'const delta = nextTop - Number(this.readerLastScrollTop || 0);' in helper_block
    assert 'if (nextTop <= 24 || delta < -14) {' in helper_block
    assert '} else if (delta > 18 && nextTop > 72) {' in helper_block
    assert 'this.readerLastScrollTop = nextTop;' in helper_block
    assert 'this.syncReaderMobileHeaderVisibility(center);' in scroll_block
    assert scroll_block.index('this.syncReaderMobileHeaderVisibility(center);') < scroll_block.index('if (this.isReaderPageMode) {')


def test_chat_grid_scroll_reader_center_to_top_reveals_mobile_header_before_resetting_scroll():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    scroll_top_block = extract_js_function_block(chat_grid_source, "scrollReaderCenterToTop(behavior = 'auto') {")

    assert 'const previousHidden = this.readerMobileHeaderHidden;' in scroll_top_block
    assert 'this.readerMobileHeaderHidden = false;' in scroll_top_block
    assert 'this.readerLastScrollTop = 0;' in scroll_top_block
    assert 'if (previousHidden) {' in scroll_top_block
    assert 'this.updateReaderLayoutMetrics();' in scroll_top_block
    assert 'center.scrollTo({' in scroll_top_block


def test_chat_reader_template_moves_save_button_into_local_notes_panels():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-mobile-save' not in template_source
    assert 'x-show="readerResponsiveMode !== \'mobile\'" @click="saveChatMeta()">保存备注</button>' not in template_source
    assert template_source.count('@click="saveChatMeta()"') >= 2
    assert 'chat-reader-field-actions' in template_source


def test_chat_reader_template_keeps_modal_close_actions_separate_from_regex_toolbar_groups():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-modal-close-slot' in template_source
    assert '<div class="chat-reader-regex-toolbar chat-reader-nested-actions">' in template_source
    assert '<div class="chat-reader-regex-toolbar-group">' in template_source


def test_chat_reader_css_mobile_modal_headers_pin_close_buttons_to_right():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-nested-header,' in mobile_block
    assert 'display: grid;' in mobile_block
    assert 'grid-template-columns: minmax(0, 1fr) auto;' in mobile_block
    assert '.chat-reader-modal-close-slot {' in mobile_block
    assert 'justify-self: end;' in mobile_block
    assert 'align-self: start;' in mobile_block


def test_chat_reader_css_mobile_keeps_floor_editor_inputs_and_preview_min_height():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-floor-editor {' in mobile_block
    assert 'min-height: 11rem;' in mobile_block
    assert '.chat-reader-floor-preview {' in mobile_block
    assert 'min-height: 11rem;' in mobile_block


def test_chat_reader_template_groups_reader_controls_into_clear_sections():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-option-group-label">显示模式<' in template_source
    assert 'chat-reader-option-group-label">浏览方式<' in template_source
    assert 'chat-reader-option-group-label">规则与策略<' in template_source
    assert 'chat-reader-option-group-label">锚点模式<' in template_source
    assert 'chat-reader-option-group-label">快捷跳转<' in template_source
    assert 'chat-reader-option-group' in template_source


def test_chat_reader_css_mobile_allows_view_strategy_and_regex_summary_to_scroll():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-regex-summary-strip {' in mobile_block
    assert 'max-height: none;' in mobile_block
    assert '.chat-reader-nested-section--form {' in mobile_block
    assert 'overflow-y: auto;' in mobile_block


def test_chat_reader_template_floor_editor_uses_section_heads_and_editor_note():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-section-head' in template_source
    assert 'chat-reader-editor-note' in template_source


def test_chat_reader_css_mobile_regex_summary_becomes_inline_and_browser_keeps_space():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-regex-summary-strip--mobile {' in mobile_block
    assert 'padding-right: 0;' in mobile_block
    assert '.chat-reader-regex-summary-grid {' in mobile_block
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in mobile_block
    assert '.chat-reader-regex-summary-chip {' in mobile_block
    assert 'padding: 0.55rem 0.65rem;' in mobile_block
    assert '.chat-reader-regex-browser {' in mobile_block
    assert 'min-height: 18rem;' in mobile_block
    assert '.chat-reader-sideblock-card--browser {' in mobile_block
    assert 'min-height: 14rem;' in mobile_block
    assert '.chat-reader-sideblock-card--test {' in mobile_block
    assert 'min-height: 16rem;' in mobile_block
    assert 'max-height: 20rem;' in mobile_block
    assert '.chat-reader-regex-workbench {' in mobile_block
    assert 'gap: 0.8rem;' in mobile_block
    assert '.chat-reader-regex-browser-detail {' in mobile_block
    assert 'max-height: 16rem;' in mobile_block
    assert '.chat-reader-regex-test-input {' in mobile_block
    assert 'min-height: 8rem;' in mobile_block
    assert '.chat-reader-regex-preview {' in mobile_block
    assert 'min-height: 10rem;' in mobile_block
    assert '.chat-reader-editor-grid--balanced {' in mobile_block
    assert 'display: flex;' in mobile_block
    assert 'flex-direction: column;' in mobile_block
    assert '.chat-reader-regex-mobile-layout {' in mobile_block
    assert 'display: flex;' in mobile_block
    assert 'overflow-y: auto;' in mobile_block
    assert '.chat-reader-regex-mobile-tabs {' in mobile_block
    assert 'display: flex;' in mobile_block
    assert 'position: sticky;' in mobile_block
    assert '.chat-reader-regex-toolbar {' in mobile_block
    assert 'display: none;' in mobile_block
    assert '.chat-reader-regex-mobile-section {' in mobile_block
    assert 'display: flex;' in mobile_block
    assert 'flex-direction: column;' in mobile_block
    assert '.chat-reader-regex-mobile-layout .chat-reader-regex-browser {' in mobile_block
    assert 'grid-template-columns: 1fr;' in mobile_block
    assert '.chat-reader-regex-mobile-layout .chat-reader-regex-browser-list,' in mobile_block
    assert 'overflow: visible;' in mobile_block
    assert 'max-height: none;' in mobile_block
    assert '.chat-reader-regex-header-actions {' in mobile_block
    assert 'display: flex;' in mobile_block
    assert '.chat-reader-editor-grid--balanced {' in mobile_block
    assert 'display: none;' in mobile_block
    assert '.chat-reader-editor-grid--editor {' in mobile_block
    assert 'display: flex !important;' in mobile_block


def test_chat_reader_template_renders_regex_summary_inside_scrollable_mobile_workspace():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'class="chat-reader-regex-summary-strip chat-reader-nested-section chat-reader-nested-section--summary custom-scrollbar" x-show="readerResponsiveMode !== \'mobile\'"' in template_source
    assert 'chat-reader-regex-summary-strip--mobile' in template_source
    assert '<div class="chat-reader-regex-mobile-layout custom-scrollbar" x-show="readerResponsiveMode === \'mobile\'" @scroll.passive="handleRegexConfigScroll($event)">' in template_source


def test_chat_reader_template_adds_mobile_only_regex_sections_for_effective_rules_draft_and_test():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-regex-mobile-layout' in template_source
    assert 'chat-reader-regex-mobile-tabs' in template_source
    assert 'chat-reader-regex-mobile-section--effective' in template_source
    assert 'chat-reader-regex-mobile-section--draft' in template_source
    assert 'chat-reader-regex-mobile-section--test' in template_source
    assert "@click=\"regexConfigMobileTab = 'effective'\"" in template_source
    assert "@click=\"regexConfigMobileTab = 'draft'\"" in template_source
    assert "x-show=\"regexConfigMobileTab === 'effective'\"" in template_source
    assert "x-show=\"regexConfigMobileTab === 'draft'\"" in template_source
    assert 'chat-reader-regex-mobile-savebar' not in template_source
    assert 'chat-reader-regex-header-actions' in template_source
    assert "x-show=\"readerResponsiveMode === 'mobile'\" class=\"chat-toolbar-btn chat-toolbar-btn--primary chat-reader-regex-save-pill\" @click=\"saveRegexConfig()\">保存</button>" in template_source


def test_chat_grid_tracks_mobile_regex_header_visibility_separately_from_reader_header():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'regexConfigMobileHeaderHidden: false,' in chat_grid_source
    assert js_contains(chat_grid_source, "regexConfigMobileTab: 'effective',")
    regex_scroll_block = extract_js_function_block(chat_grid_source, 'handleRegexConfigScroll(event) {')
    assert 'const previousHidden = this.regexConfigMobileHeaderHidden;' in regex_scroll_block
    assert 'this.regexConfigMobileHeaderHidden = true;' in regex_scroll_block
    assert 'this.updateRegexConfigLayoutMetrics();' in regex_scroll_block


def test_chat_reader_template_mobile_floor_editor_keeps_right_column_note_inside_section_head():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')
    editor_block = template_source.split('<div class="chat-reader-editor-section chat-reader-editor-section--wide chat-reader-nested-section">', 1)[1].split('<div class="chat-inline-actions">', 1)[0]

    assert '<div class="chat-reader-section-head">' in editor_block
    assert '<div class="chat-reader-panel-title">显示预览</div>' in editor_block
    assert 'chat-reader-editor-note' in editor_block


def test_chat_reader_template_uses_raw_message_as_floor_editor_primary_input():
    template_source = read_project_file('templates/modals/detail_chat_reader.html')
    floor_editor_block = template_source.split('<div class="chat-bind-modal chat-reader-editor-modal chat-reader-nested-modal chat-reader-transition-surface chat-reader-editor-modal--floor"', 1)[1].split('</div>\n</div>\n\n<div x-show="bindPickerOpen"', 1)[0]

    assert '<div class="chat-reader-panel-title">原始正文</div>' in floor_editor_block
    assert '<textarea x-model="editingMessageRawDraft" @input="editingMessageDraft = extractDisplayContent($event.target.value)" class="form-textarea chat-reader-floor-editor"></textarea>' in floor_editor_block
    assert '<div class="chat-reader-panel-title">显示预览</div>' in floor_editor_block
    assert '<textarea x-model="editingMessageDraft" readonly class="form-textarea chat-reader-floor-editor chat-reader-floor-editor--raw"></textarea>' in floor_editor_block


def test_chat_grid_open_floor_editor_seeds_primary_editor_from_raw_message_only():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    open_floor_editor_block = extract_js_function_block(chat_grid_source, 'openFloorEditor(message) {')

    assert js_contains(open_floor_editor_block, "this.editingMessageRawDraft = String(message.mes || '');")
    assert js_contains(
        open_floor_editor_block,
        'this.editingMessageDraft = this.extractDisplayContent(this.editingMessageRawDraft);',
    )
    assert not js_contains(
        open_floor_editor_block,
        "this.editingMessageDraft = String(message.content || message.mes || '');",
    )


def test_chat_grid_save_floor_edit_persists_raw_message_and_rebuilds_rendered_reader_state():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    save_floor_edit_block = extract_js_function_block(chat_grid_source, 'async saveFloorEdit() {')

    assert js_contains(
        save_floor_edit_block,
        "target.mes = String(this.editingMessageRawDraft || '');",
    )
    assert 'focusFloor: this.editingFloor,' in save_floor_edit_block
    assert 'this.rebuildActiveChatMessages(runtimeConfig);' in chat_grid_source
    assert js_contains(
        chat_grid_source,
        "await this.setReaderWindowAroundFloor(focusFloor || 1, 'center');",
    )


def test_chat_reader_css_mobile_stacks_floor_editor_sections_and_resets_note_overlap_spacing():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    mobile_block = extract_media_block(chat_reader_css, '@media (max-width: 720px)')

    assert '.chat-reader-editor-grid--editor {' in mobile_block
    assert 'display: flex !important;' in mobile_block
    assert 'flex-direction: column !important;' in mobile_block
    assert '.chat-reader-editor-section--narrow,' in mobile_block
    assert '.chat-reader-editor-section--wide {' in mobile_block
    assert 'width: 100%;' in mobile_block
    assert 'flex: 0 0 auto;' in mobile_block
    assert '.chat-reader-editor-note {' in mobile_block
    assert 'margin-top: 0;' in mobile_block


def test_chat_grid_tracks_mobile_header_visibility_state_for_scroll_hiding():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'readerMobileHeaderHidden:' in chat_grid_source
    assert 'readerLastScrollTop:' in chat_grid_source
    assert 'readerMobileHeaderHidden = true' in chat_grid_source
    assert 'readerMobileHeaderHidden = false' in chat_grid_source


def test_chat_reader_template_binds_mobile_header_hidden_class():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert "'is-' + readerResponsiveMode + ((readerResponsiveMode === 'mobile' && readerMobileHeaderHidden) ? ' is-mobile-hidden' : '')" in reader_template


def test_chat_reader_template_desktop_header_exposes_independent_tools_search_and_navigator_toggles():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert "@click=\"toggleReaderPanel('left')\">工具</button>" in reader_template
    assert "@click=\"openReaderDesktopPanel('search')\">搜索</button>" in reader_template
    assert "@click=\"openReaderDesktopPanel('navigator')\">导航</button>" in reader_template
    assert "x-show=\"readerResponsiveMode !== 'mobile'\"" in reader_template


def test_chat_grid_reader_desktop_panel_controls_close_only_the_target_panel():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(
        chat_grid_source,
        'const isSamePanelOpen = this.readerShowRightPanel && this.readerRightTab === nextTab;',
    )
    assert js_contains(chat_grid_source, 'this.readerShowRightPanel = false;')
    assert js_contains(chat_grid_source, 'this.readerRightTab = nextTab;')
    assert 'closeReaderRightPanel() {' in chat_grid_source
    close_right_section = chat_grid_source.split('closeReaderRightPanel() {', 1)[1].split('}', 1)[0]
    assert 'this.readerShowLeftPanel = false;' not in close_right_section


def test_chat_reader_template_right_close_button_uses_desktop_specific_close_logic():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert '@click="closeReaderRightPanel()"' in reader_template
    assert '@click="hideReaderPanels()"' not in reader_template.split('class="chat-reader-right custom-scrollbar"', 1)[1].split('</aside>', 1)[0]


def test_chat_grid_reader_pane_styles_reflow_center_when_left_panel_closes():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert js_contains(chat_grid_source, "return 'grid-column: 1;';")
    assert js_contains(chat_grid_source, "return 'grid-column: 2;';")
    assert js_contains(chat_grid_source, "return 'grid-column: 3;';")


def test_chat_reader_template_binds_desktop_pane_visibility_to_inline_display_styles():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert ":style=" in reader_template
    assert ':style="readerLeftPaneStyle"' in reader_template
    assert ':style="readerRightPaneStyle"' in reader_template


def test_chat_grid_reader_mobile_mode_is_not_only_ua_driven():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    layout_source = read_project_file('static/js/components/layout.js')

    assert 'readerResponsiveMode' in chat_grid_source
    assert 'window.innerWidth < 900' in layout_source
    assert 'window.innerWidth < 1180' in layout_source


def test_layout_recomputes_global_device_type_on_window_resize():
    layout_source = read_project_file('static/js/components/layout.js')

    assert js_contains(layout_source, "window.addEventListener('resize', () => {")
    assert 'this.reDeviceType();' in layout_source


def test_chat_grid_keeps_right_panel_layout_during_app_stage():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    desktop_panel_block = chat_grid_source.split('get readerDesktopRightPanelOpen() {', 1)[1].split('}', 1)[0]
    body_grid_block = chat_grid_source.split('get readerBodyGridStyle() {', 1)[1].split('openReaderDesktopPanel(panel) {', 1)[0]

    assert 'return this.readerShowRightPanel;' in desktop_panel_block
    assert '!this.readerAppMode' not in desktop_panel_block
    assert 'if (this.readerShowRightPanel && !this.readerAppMode)' not in body_grid_block
    assert 'if (this.readerShowRightPanel) {' in body_grid_block


def test_chat_reader_template_keeps_app_stage_in_center_pane_with_separate_right_rail():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    shell = extract_chat_reader_shell(reader_template)

    main_section = shell.split('<main class="chat-reader-center custom-scrollbar" :style="readerCenterPaneStyle" @scroll.passive="handleReaderScroll()">', 1)[1].split('</main>', 1)[0]
    right_section = shell.split('<aside x-show="readerShowRightPanel" class="chat-reader-right custom-scrollbar" :style="readerRightPaneStyle">', 1)[1].split('</aside>', 1)[0]

    assert 'chat-reader-app-stage' in main_section
    assert 'chatAppStageHost' in main_section
    assert 'chat-reader-app-stage' not in right_section


def test_chat_reader_template_uses_compact_regex_summary_with_help_entry():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'chat-reader-regex-summary-strip' in reader_template
    assert 'chat-reader-regex-summary-grid' in reader_template
    assert '@click="openRegexHelp()"' in reader_template
    assert 'aria-label="聊天解析规则帮助"' in reader_template
    assert 'chat-reader-regex-source-grid' not in reader_template


def test_chat_grid_tracks_regex_help_modal_state():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    open_help_block = extract_js_function_block(chat_grid_source, 'openRegexHelp() {')
    close_help_block = extract_js_function_block(chat_grid_source, 'closeRegexHelp() {')
    close_regex_block = extract_js_function_block(chat_grid_source, 'closeRegexConfig() {')

    assert 'regexHelpOpen: false,' in chat_grid_source
    assert 'openRegexHelp() {' in chat_grid_source
    assert 'closeRegexHelp() {' in chat_grid_source
    assert 'this.regexHelpOpen = true;' in open_help_block
    assert 'this.regexHelpOpen = false;' in close_help_block
    assert 'this.regexHelpOpen = false;' in close_regex_block


def test_chat_reader_css_adds_regex_summary_and_help_modal_primitives():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '.chat-reader-regex-summary-strip' in chat_reader_css
    assert '.chat-reader-regex-summary-grid' in chat_reader_css
    assert '.chat-reader-regex-help-button' in chat_reader_css
    assert '.chat-reader-regex-help-modal' in chat_reader_css


def test_chat_reader_template_keeps_regex_summary_dense_without_instructional_copy():
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    summary_section = reader_template.split('chat-reader-regex-summary-strip', 1)[1].split('<div class="chat-reader-editor-grid', 1)[0]

    assert '精简显示规则来源与草稿状态，详细解释放到帮助里。' not in summary_section
    assert '左侧“当前实际生效规则”会实时预览当前草稿合并后的结果；只有保存后才会真正写回聊天文件。' not in summary_section
    assert 'x-text="regexDraftOutcomeSummary"' not in summary_section
    assert 'chat-reader-regex-summary-feedback' in summary_section


def test_chat_grid_does_not_seed_regex_summary_with_default_instruction_status():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    open_regex_block = extract_js_function_block(chat_grid_source, 'openRegexConfig() {')

    assert js_contains(open_regex_block, "this.regexConfigStatus = '';")
    assert '测试区默认不自动加载内容，按需手动载入当前定位楼层即可。' not in open_regex_block


def test_chat_reader_css_replaces_tall_regex_status_stack_with_optional_feedback_row():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')

    assert '.chat-reader-regex-summary-feedback' in chat_reader_css
    assert '.chat-reader-regex-summary-status' not in chat_reader_css


def test_chat_reader_scroll_disclosures_use_compact_chip_like_summaries_before_expansion():
    chat_reader_css = read_project_file('static/css/modules/view-chats.css')
    reasoning_block = extract_exact_css_block(
        chat_reader_css,
        '.chat-message-reasoning-summary,\n.chat-message-code-collapse-toggle',
    )
    body_block = extract_exact_css_block(chat_reader_css, '.chat-message-reasoning-body')

    assert 'display: inline-flex;' in reasoning_block
    assert 'align-items: center;' in reasoning_block
    assert 'min-height: 28px;' in reasoning_block
    assert 'border-radius: 999px;' in reasoning_block
    assert 'width: fit-content;' in reasoning_block
    assert 'padding: 0.22rem 0.68rem;' in reasoning_block
    assert 'background: color-mix(in srgb, var(--bg-sub), transparent 8%);' in reasoning_block
    assert 'border-top: 1px solid' in body_block


def test_mobile_header_template_uses_title_block_for_sidebar_and_search_upload_cluster():
    header_template = read_project_file('templates/components/header.html')

    assert '@click="openMobileSidebar()"' in header_template
    assert 'class="mobile-search-group"' in header_template
    assert 'x-show="showMobileUploadButton"' in header_template
    assert '@click="triggerMobileUpload()"' in header_template


def test_mobile_sidebar_template_removes_floating_button_group_and_keeps_single_hidden_input():
    sidebar_template = read_project_file('templates/components/sidebar.html')

    assert 'class="sidebar-button-group"' not in sidebar_template
    assert 'sidebar-group-btn' not in sidebar_template
    assert sidebar_template.count('x-data="sidebar"') == 1
    assert sidebar_template.count('x-ref="mobileImportInput"') == 1


def test_mobile_header_script_defines_upload_trigger_contract():
    header_source = read_project_file('static/js/components/header.js')
    header_template = read_project_file('templates/components/header.html')

    assert 'const MOBILE_HEADER_UPLOAD_MODES = [' in header_source
    for mode in ('cards', 'worldinfo', 'presets', 'regex', 'scripts', 'quick_replies'):
        assert f'"{mode}"' in header_source or f"'{mode}'" in header_source
    show_mobile_upload_block = extract_js_function_block(header_source, 'get showMobileUploadButton()')
    assert "this.deviceType === 'mobile'" in show_mobile_upload_block or 'this.deviceType === "mobile"' in show_mobile_upload_block
    assert 'MOBILE_HEADER_UPLOAD_MODES.includes(this.currentMode)' in show_mobile_upload_block
    assert 'request-mobile-upload' in header_source
    assert '@click="triggerMobileUpload()"' in header_template


def test_mobile_header_script_closes_menu_before_sidebar_and_upload_actions():
    header_source = read_project_file('static/js/components/header.js')
    sidebar_block = extract_js_function_block(header_source, 'openMobileSidebar()')

    assert 'openMobileSidebar()' in header_source
    assert 'this.closeMobileMenu();' in sidebar_block
    assert 'const nextVisible = !this.$store.global.visibleSidebar;' in sidebar_block
    assert 'this.$store.global.visibleSidebar = nextVisible;' in sidebar_block
    assert 'document.body.style.overflow = nextVisible ? ' in sidebar_block
    assert 'hidden' in sidebar_block
    assert 'triggerMobileUpload()' in header_source
    assert 'this.closeMobileMenu();' in extract_js_function_block(header_source, 'triggerMobileUpload()')


def test_mobile_sidebar_script_listens_for_upload_trigger_and_cleans_up():
    sidebar_source = read_project_file('static/js/components/sidebar.js')

    assert js_contains(
        sidebar_source,
        "window.addEventListener('request-mobile-upload', this.handleMobileUploadRequest);",
    )
    assert js_contains(
        sidebar_source,
        "window.removeEventListener('request-mobile-upload', this.handleMobileUploadRequest);",
    )
    handle_upload_block = extract_js_function_block(sidebar_source, 'handleMobileUploadRequest()')
    assert js_contains(handle_upload_block, "this.currentMode === 'chats'")
    assert '!this.$refs.mobileImportInput' in handle_upload_block
    assert 'this.$refs.mobileImportInput.click();' in handle_upload_block


def test_mobile_layout_css_defines_search_upload_group_and_no_legacy_sidebar_button_group_rules():
    layout_css = read_project_file('static/css/modules/layout.css')

    assert '.mobile-search-group {' in layout_css
    assert '.mobile-upload-btn {' in layout_css
    assert '.mobile-header-left {' in layout_css
    assert '.sidebar-button-group {' not in layout_css
    assert '.sidebar-group-btn {' not in layout_css


def test_mobile_header_css_keeps_search_tools_on_a_single_compact_row():
    layout_css = read_project_file('static/css/modules/layout.css')
    mobile_layout_css = extract_media_block(layout_css, '@media (max-width: 768px)')

    search_row_block = extract_exact_css_block(mobile_layout_css, '.mobile-header-search-row')
    tools_block = extract_exact_css_block(mobile_layout_css, '.mobile-header-search-tools')
    toggle_block = extract_exact_css_block(mobile_layout_css, '.mobile-search-mode-toggle')
    toggle_button_block = extract_exact_css_block(mobile_layout_css, '.mobile-search-mode-toggle button')

    assert 'display: flex;' in search_row_block
    assert 'flex-direction: row;' not in search_row_block
    assert 'flex-direction: column;' not in search_row_block
    assert 'display: flex;' in tools_block
    assert 'align-items: center;' in tools_block
    assert 'min-width: 0;' in tools_block
    assert 'width: 100%;' in tools_block
    assert 'display: flex;' in toggle_block
    assert 'flex-shrink: 0;' in toggle_block
    assert '.mobile-search-mode-row {' not in mobile_layout_css
    assert 'height: 32px;' in toggle_button_block
    assert 'border-radius: 6px;' in toggle_button_block
    assert 'border: 1px solid var(--border-light);' in toggle_button_block


def test_mobile_header_template_tracks_sidebar_open_state_for_toggle_feedback():
    header_template = read_project_file('templates/components/header.html')

    assert ":class=\"{ 'is-active': $store.global.visibleSidebar }\"" in header_template
    assert ":aria-pressed=\"$store.global.visibleSidebar ? 'true' : 'false'\"" in header_template


def test_mobile_header_script_toggles_sidebar_visibility_and_scroll_lock():
    header_source = read_project_file('static/js/components/header.js')
    sidebar_toggle_block = extract_js_function_block(header_source, 'openMobileSidebar()')

    assert 'const nextVisible = !this.$store.global.visibleSidebar;' in sidebar_toggle_block
    assert 'this.$store.global.visibleSidebar = nextVisible;' in sidebar_toggle_block
    assert 'document.body.style.overflow = nextVisible ? ' in sidebar_toggle_block
    assert 'hidden' in sidebar_toggle_block


def test_mobile_layout_css_defines_mobile_header_toggle_feedback_states():
    layout_css = read_project_file('static/css/modules/layout.css')
    active_block = extract_exact_css_block(layout_css, '.mobile-header-left:active')
    open_block = extract_exact_css_block(layout_css, '.mobile-header-left.is-active')

    assert 'background-color: var(--bg-hover);' in active_block
    assert 'transform: scale(0.98);' in active_block
    assert 'background-color: var(--accent-faint);' in open_block
    assert 'border-color: var(--accent-light);' in open_block


def test_card_sidebar_template_adds_stable_split_layout_hooks():
    sidebar_template = read_project_file('templates/components/sidebar.html')
    compact_template = compact_whitespace(sidebar_template)

    assert 'class="flex-1 card-sidebar-shell"' in sidebar_template
    assert 'x-ref="cardSidebarShell"' in sidebar_template
    assert 'class="card-sidebar-categories"' in sidebar_template
    assert 'class="card-sidebar-splitter"' in sidebar_template
    assert '@pointerdown.prevent="beginTagPaneResize($event)"' in sidebar_template
    assert 'aria-label="调整标签索引区域高度"' in sidebar_template
    assert 'class="card-sidebar-tags"' in sidebar_template
    assert 'x-ref="cardTagsPane"' in sidebar_template
    assert 'x-ref="cardTagsHeader"' in sidebar_template
    assert 'x-ref="cardTagCategoryStrip"' in sidebar_template
    assert 'x-ref="cardTagCloud"' in sidebar_template
    assert 'tagIndexVisibleTags.slice(0, dynamicVisibleTagCount)' in compact_template


def test_card_sidebar_root_uses_css_variable_binding_without_full_style_attribute_override():
    sidebar_template = read_project_file('templates/components/sidebar.html')
    root_match = re.search(
        r'<div\s+[^>]*x-show="currentMode === \'cards\' && visibleSidebar"[^>]*class="flex-1 card-sidebar-shell"[^>]*>',
        sidebar_template,
        re.DOTALL,
    )

    assert root_match is not None
    root_element = compact_whitespace(root_match.group(0))

    assert ':style="desktopTagPaneStyle"' not in sidebar_template
    assert '--card-tags-pane-basis' in root_element
    assert 'cardTagPaneBasisStyle' in root_element


def test_card_sidebar_template_removes_expansion_only_lower_pane_layout_styles():
    sidebar_template = read_project_file('templates/components/sidebar.html')
    compact_template = compact_whitespace(sidebar_template)

    assert ":style=\"tagsSectionExpanded ? 'flex: 1;' : ''\"" not in sidebar_template
    assert 'style="display: flex; flex-direction: column; overflow: hidden;"' not in sidebar_template
    assert 'x-show="tagsSectionExpanded" class="sidebar-content custom-scrollbar card-sidebar-tags-body"' in compact_template
    assert 'x-show="tagIndexVisibleTags.length > dynamicVisibleTagCount"' in compact_template
    assert 'tagIndexVisibleTags.length - dynamicVisibleTagCount' in sidebar_template


def test_card_sidebar_layout_css_defines_persistent_strip_and_scoped_solid_surfaces():
    layout_css = read_project_file('static/css/modules/layout.css')

    shell_block = extract_exact_css_block(layout_css, '.card-sidebar-shell')
    splitter_block = extract_exact_css_block(layout_css, '.card-sidebar-splitter')
    expanded_block = extract_exact_css_block(layout_css, '.card-sidebar-tags.is-expanded')

    assert '--card-tags-pane-basis: 34%;' in shell_block
    assert '.card-sidebar-tags {' in layout_css
    assert 'cursor: row-resize;' in splitter_block
    assert 'flex: 0 0 10px;' in splitter_block
    assert '.card-sidebar-splitter-grip {' in layout_css
    assert 'flex: 0 0 var(--card-tags-pane-basis);' in expanded_block
    assert 'min-height:' not in expanded_block
    assert 'clamp(10rem, 34%, 15rem)' not in expanded_block
    assert '.card-sidebar-shell .sidebar-content {' in layout_css
    assert '.card-sidebar-shell .sidebar-section-header {' in layout_css


def test_mobile_card_sidebar_layout_css_hides_desktop_splitter_and_keeps_tag_body_cap():
    layout_css = read_project_file('static/css/modules/layout.css')
    mobile_layout_css = extract_media_block(layout_css, '@media (max-width: 768px)')

    mobile_splitter_block = extract_exact_css_block(
        mobile_layout_css,
        '.sidebar-mobile .card-sidebar-splitter',
    )
    mobile_tags_block = extract_exact_css_block(
        mobile_layout_css,
        '.sidebar-mobile .card-sidebar-tags-body',
    )

    assert 'display: none;' in mobile_splitter_block
    assert 'max-height: min(34vh, 16rem);' in mobile_tags_block


def test_sidebar_js_supports_desktop_tag_pane_resize_and_dynamic_visible_tag_count():
    sidebar_source = read_project_file('static/js/components/sidebar.js')

    assert 'TAG_PANE_RATIO_STORAGE_KEY = "st_manager_card_tags_split_ratio"' in sidebar_source
    assert 'dynamicVisibleTagCount: DEFAULT_VISIBLE_TAG_COUNT' in sidebar_source
    assert 'get shouldShowCardTagSplitter() {' in sidebar_source
    assert 'get cardTagPaneBasisStyle() {' in sidebar_source
    assert 'scheduleTagPaneLayoutSync() {' in sidebar_source
    assert 'computeDynamicVisibleTagCount() {' in sidebar_source
    assert 'beginTagPaneResize(event) {' in sidebar_source
    assert 'handleTagPaneResize(event) {' in sidebar_source
    assert 'endTagPaneResize() {' in sidebar_source
    assert 'window.addEventListener("resize", this._syncTagPaneLayoutHandler);' in sidebar_source
    assert 'localStorage.setItem(TAG_PANE_RATIO_STORAGE_KEY, String(this.tagPaneRatio));' in sidebar_source

    compute_block = extract_js_function_block(
        sidebar_source,
        'computeDynamicVisibleTagCount() {',
    )
    assert 'Math.floor((tagCloudWidth + 6) / ESTIMATED_TAG_CHIP_WIDTH)' in compute_block
    assert 'Math.floor((availableTagHeight + 6) / ESTIMATED_TAG_ROW_HEIGHT)' in compute_block


def test_sidebar_runtime_resizes_desktop_tag_pane_and_persists_ratio():
    run_sidebar_runtime_check(
        """
        if (component.cardTagPaneBasisStyle !== '34.00%') {
          throw new Error(`Expected desktop style to reflect default ratio, got ${component.cardTagPaneBasisStyle}`);
        }

        const visibleTagCount = component.computeDynamicVisibleTagCount();
        if (visibleTagCount !== 6) {
          throw new Error(`Expected computed visible tag count to be 6, got ${visibleTagCount}`);
        }

        component.beginTagPaneResize({ clientY: 200 });
        if (!component.tagPaneResizeState) {
          throw new Error('Expected beginTagPaneResize to capture resize state');
        }
        if (!component.$refs.cardSidebarShell.classList.contains('is-resizing')) {
          throw new Error('Expected beginTagPaneResize to add the resizing class');
        }

        const addEvents = windowListeners
          .filter((entry) => entry.action === 'add')
          .map((entry) => entry.type);
        const expectedAddEvents = ['pointermove', 'pointerup', 'pointercancel'];
        if (JSON.stringify(addEvents) !== JSON.stringify(expectedAddEvents)) {
          throw new Error(`Expected resize listeners to be added, got ${JSON.stringify(addEvents)}`);
        }

        component.handleTagPaneResize({ clientY: 160 });
        if (component.tagPaneRatio <= 0.34) {
          throw new Error(`Expected dragging upward to increase tagPaneRatio, got ${component.tagPaneRatio}`);
        }
        flushRaf();
        if (component.dynamicVisibleTagCount !== 6) {
          throw new Error(`Expected resize sync to keep measured visible tag count, got ${component.dynamicVisibleTagCount}`);
        }

        component.endTagPaneResize();
        if (component.tagPaneResizeState !== null) {
          throw new Error('Expected endTagPaneResize to clear resize state');
        }
        if (component.$refs.cardSidebarShell.classList.contains('is-resizing')) {
          throw new Error('Expected endTagPaneResize to remove the resizing class');
        }

        const storedRatio = localStorage.getItem('st_manager_card_tags_split_ratio');
        if (storedRatio !== String(component.tagPaneRatio)) {
          throw new Error(`Expected endTagPaneResize to persist ratio, got ${storedRatio}`);
        }

        const removeEvents = windowListeners
          .filter((entry) => entry.action === 'remove')
          .map((entry) => entry.type);
        const expectedRemoveEvents = ['pointermove', 'pointerup', 'pointercancel'];
        if (JSON.stringify(removeEvents) !== JSON.stringify(expectedRemoveEvents)) {
          throw new Error(`Expected resize listeners to be removed, got ${JSON.stringify(removeEvents)}`);
        }

        component.$refs.cardSidebarShell.getBoundingClientRect = () => ({ height: 250 });
        component.$refs.cardTagsPane.getBoundingClientRect = () => ({ height: 170 });
        component.tagPaneRatio = 0.9;
        component.syncTagPaneLayout();
        const constrainedHeight = component.tagPaneRatio * 250;
        if (constrainedHeight !== 30) {
          throw new Error(`Expected short shell sync to degrade to 30px tag pane height, got ${constrainedHeight}`);
        }
        if (250 - constrainedHeight !== 220) {
          throw new Error(`Expected short shell sync to leave 220px for categories, got ${250 - constrainedHeight}`);
        }
        """
    )


def test_card_pagination_css_keeps_mobile_footer_compact_with_safe_area_spacing():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    mobile_cards_css = extract_media_block(cards_css, '@media (max-width: 768px)')

    assert '.card-pagination-summary {' in cards_css
    assert '.card-pagination-page-cluster {' in cards_css
    assert 'padding-bottom: calc(0.5rem + env(safe-area-inset-bottom, 0px));' in cards_css
    assert '.card-flip-toolbar {' in mobile_cards_css
    assert 'flex-wrap: nowrap;' in mobile_cards_css
    assert '.card-pagination-page-cluster {' in mobile_cards_css
    assert 'min-width: 0;' in cards_css


def test_base_css_stabilizes_mobile_text_inflation_and_dynamic_viewport_height():
    base_css = read_project_file('static/css/modules/base.css')
    body_block = extract_exact_css_block(base_css, 'body')
    body_lines = {line.strip() for line in body_block.splitlines() if line.strip()}

    assert 'text-size-adjust: 100%;' in base_css
    assert '-webkit-text-size-adjust: 100%;' in base_css
    assert 'min-height: 100vh;' in base_css
    assert 'min-height: 100dvh;' in base_css
    assert 'height: 100vh;' in body_lines
    assert 'height: 100dvh;' in body_lines
    assert 'height: auto;' not in body_lines


def test_global_state_syncs_visual_viewport_height_into_css_variable():
    state_source = read_project_file('static/js/state.js')

    assert 'syncViewportHeight() {' in state_source
    sync_block = extract_js_function_block(state_source, 'syncViewportHeight() {')
    init_block = extract_js_function_block(state_source, 'init() {')

    assert 'window.visualViewport' in sync_block
    assert 'window.visualViewport.height' in sync_block
    assert "updateCssVariable('--app-viewport-height'" in sync_block or 'updateCssVariable("--app-viewport-height"' in sync_block
    assert "updateCssVariable('--app-viewport-height-safe'" in sync_block or 'updateCssVariable("--app-viewport-height-safe"' in sync_block
    assert 'window.innerHeight || 0' in sync_block
    assert 'Math.max(0, roundedHeight - 1)' in sync_block
    assert 'this.syncViewportHeight();' in init_block
    assert 'window.visualViewport.addEventListener(' in init_block
    assert 'this._visualViewportResizeHandler' in init_block
    assert 'orientationchange' in init_block


def test_mobile_modal_components_css_defines_shared_fullscreen_dynamic_viewport_baseline():
    components_css = read_project_file('static/css/modules/components.css')
    assert '@media (max-width: 768px)' in components_css
    mobile_components_css = extract_media_block(components_css, '@media (max-width: 768px)')

    assert '.modal-overlay {' in mobile_components_css
    assert '.modal-container {' in mobile_components_css
    overlay_block = extract_exact_css_block(mobile_components_css, '.modal-overlay')
    container_block = extract_exact_css_block(mobile_components_css, '.modal-container')

    assert 'padding: 0;' in overlay_block
    assert 'align-items: stretch;' in overlay_block
    assert 'justify-content: flex-start;' in overlay_block
    assert 'overflow: hidden;' in overlay_block

    assert 'width: 100vw;' in container_block
    assert 'max-width: 100vw;' in container_block
    assert 'height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh));' in container_block
    assert '--app-viewport-height-safe' in container_block
    assert '--app-viewport-height, 100dvh' in container_block
    assert 'min-height:' in container_block
    assert 'border-radius: 0;' in container_block


def test_detail_modal_mobile_css_uses_dynamic_viewport_and_safe_area_spacing():
    detail_css = read_project_file('static/css/modules/modal-detail.css')
    mobile_detail_css = extract_media_block(detail_css, '@media (max-width: 768px)')

    detail_modal_block = extract_exact_css_block(mobile_detail_css, '.detail-modal')
    detail_toolbar_block = extract_exact_css_block(mobile_detail_css, '.detail-left-toolbar')
    detail_zoombar_block = extract_exact_css_block(mobile_detail_css, '.detail-zoombar')
    detail_content_block = extract_exact_css_block(mobile_detail_css, '.detail-content')

    assert 'width: 100vw;' in detail_modal_block
    assert 'height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh));' in detail_modal_block
    assert '--app-viewport-height-safe' in detail_modal_block
    assert '--app-viewport-height, 100dvh' in detail_modal_block
    assert 'min-height:' in detail_modal_block
    assert 'max-width: 100vw;' in detail_modal_block
    assert 'margin: 0 !important;' in detail_modal_block
    assert 'top: calc(env(safe-area-inset-top, 0px) + 0.5rem);' in detail_toolbar_block
    assert 'bottom: calc(env(safe-area-inset-bottom, 0px) + 0.5rem);' in detail_zoombar_block
    assert 'padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 1rem);' in detail_content_block


def test_mobile_tool_and_custom_modal_variants_prefer_dynamic_viewport_height():
    tools_css = read_project_file('static/css/modules/modal-tools.css')
    settings_css = read_project_file('static/css/modules/modal-settings.css')
    automation_css = read_project_file('static/css/modules/modal-automation.css')

    mobile_tools_css = extract_media_block(tools_css, '@media (max-width: 768px)')
    mobile_settings_css = extract_media_block(settings_css, '@media (max-width: 768px)')
    mobile_automation_css = extract_media_block(automation_css, '@media (max-width: 768px)')

    assert '.advanced-editor-container {' in mobile_tools_css
    assert '.advanced-editor-header {' in mobile_tools_css
    assert '.advanced-editor-footer {' in mobile_tools_css
    assert '.adv-split-view {' in mobile_tools_css
    assert '.adv-editor-pane {' in mobile_tools_css
    assert '.large-editor-container {' in mobile_tools_css
    advanced_editor_block = extract_exact_css_block(mobile_tools_css, '.advanced-editor-container')
    advanced_header_block = extract_exact_css_block(mobile_tools_css, '.advanced-editor-header')
    advanced_footer_block = extract_exact_css_block(mobile_tools_css, '.advanced-editor-footer')
    advanced_split_block = extract_exact_css_block(mobile_tools_css, '.adv-split-view')
    advanced_editor_pane_block = extract_exact_css_block(mobile_tools_css, '.adv-editor-pane')
    large_editor_block = extract_exact_css_block(mobile_tools_css, '.large-editor-container')
    settings_block = extract_exact_css_block(mobile_settings_css, '.settings-modal-container')
    automation_block = extract_exact_css_block(mobile_automation_css, '.automation-container')
    advanced_editor_compact = re.sub(r'\s+', ' ', advanced_editor_block).strip()
    large_editor_compact = re.sub(r'\s+', ' ', large_editor_block).strip()

    assert 'height: var( --app-viewport-height-safe, var(--app-viewport-height, 100dvh) ) !important;' in advanced_editor_compact
    assert 'min-height: var( --app-viewport-height-safe, var(--app-viewport-height, 100dvh) );' in advanced_editor_compact
    assert 'padding-top: calc(env(safe-area-inset-top, 0px) + 0.75rem) !important;' in advanced_header_block
    assert 'padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 0.75rem) !important;' in advanced_footer_block
    assert 'min-height: 0;' in advanced_split_block
    assert 'min-height: 0;' in advanced_editor_pane_block
    assert '-webkit-overflow-scrolling: touch;' in advanced_editor_pane_block

    assert 'height: var( --app-viewport-height-safe, var(--app-viewport-height, 100dvh) ) !important;' in large_editor_compact
    assert 'min-height: var( --app-viewport-height-safe, var(--app-viewport-height, 100dvh) );' in large_editor_compact
    assert 'height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh));' in settings_block
    assert 'height: 100dvh;' in settings_block
    assert 'min-height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh));' in settings_block
    assert 'height: 100dvh !important;' in automation_block
    assert 'height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh)) !important;' in automation_block
    assert 'min-height: var(--app-viewport-height-safe, var(--app-viewport-height, 100dvh)) !important;' in automation_block


def test_automation_modal_template_exposes_new_action_options_and_structured_inputs():
    automation_template = read_project_file('templates/modals/automation.html')
    rename_block = automation_template.split("action.type === 'rename_file_by_template'", 1)[1].split('</template>', 1)[0]
    split_block = automation_template.split("action.type === 'split_category_to_tags'", 1)[1].split('</template>', 1)[0]

    assert '<option value="rename_file_by_template">🧩 模板重命名文件</option>' in automation_template
    assert '<option value="split_category_to_tags">📝 分类拆分为标签</option>' in automation_template
    assert "action.type === 'rename_file_by_template'" in automation_template
    assert "action.type === 'split_category_to_tags'" in automation_template
    assert 'x-model="cfg.template"' in rename_block
    assert 'x-model="cfg.fallback_template"' in rename_block
    assert 'x-model.number="cfg.max_length"' in rename_block
    assert 'x-model="cfg.exclude_category_tags"' not in rename_block
    assert 'x-model="cfg.exclude_category_tags"' in split_block
    assert '排除分类标签:' in split_block
    assert '当前分类路径会自动按 / 拆分' in split_block
    assert '回退模板:' not in split_block
    assert '最大长度:' not in split_block
    assert '@change="initActionConfig(action)"' in automation_template
    assert 'x-data="{ cfg: initActionConfig(action) }"' in automation_template
    assert "action.type === 'fetch_forum_tags'" in automation_template
    assert "action.config = { template: '', fallback_template: '', max_length: 120, exclude_category_tags: '' }" not in automation_template


def test_automation_modal_js_centralizes_template_action_config_and_removes_duplicate_methods():
    automation_js = read_project_file('static/js/components/automationModal.js')

    assert "const TEMPLATE_ACTION_TYPES = ['rename_file_by_template', 'split_category_to_tags'];" in automation_js
    assert 'function createRenameTemplateConfig(value = {}) {' in automation_js
    assert 'function createSplitCategoryTagsConfig(value = {}) {' in automation_js
    assert "action.type === 'rename_file_by_template'" in automation_js
    assert "action.type === 'split_category_to_tags'" in automation_js
    assert 'createRenameTemplateConfig(rawValue)' in automation_js
    assert 'createSplitCategoryTagsConfig(rawValue)' in automation_js
    assert 'createRenameTemplateConfig(action.config || action.value || {})' in automation_js
    assert 'createSplitCategoryTagsConfig(action.config || action.value || {})' in automation_js
    assert automation_js.count('deleteRule(index) {') == 1
    assert automation_js.count('moveRule(index, dir) {') == 1


def test_automation_help_modal_uses_four_tab_structure_with_new_guidance():
    automation_template = read_project_file('templates/modals/automation.html')

    assert 'automation-help-tabs' in automation_template
    assert 'automation-help-panel' in automation_template
    assert 'helpActiveTab' in automation_template
    assert 'role="tablist"' in automation_template

    tab_specs = (
        ('conditions', '条件'),
        ('actions', '动作'),
        ('triggers', '触发时机'),
        ('templates', '模板语法'),
    )

    for tab_key, tab_label in tab_specs:
        assert tab_label in automation_template
        assert f'role="tab"' in automation_template
        assert f'id="automation-help-tab-{tab_key}"' in automation_template
        assert f'aria-controls="automation-help-panel-{tab_key}"' in automation_template
        assert f"x-show=\"helpActiveTab === '{tab_key}'\"" in automation_template
        assert f'role="tabpanel"' in automation_template
        assert f'id="automation-help-panel-{tab_key}"' in automation_template
        assert f'aria-labelledby="automation-help-tab-{tab_key}"' in automation_template

    assert 'rename_file_by_template' in automation_template
    assert 'split_category_to_tags' in automation_template
    assert '不同触发场景只会运行对应的动作子集' in automation_template
    assert '导入时会跳过抓取论坛标签与标签合并' in automation_template
    assert '更新链接时只执行抓取论坛标签' in automation_template
    assert '手动打标时只执行标签合并' in automation_template
    assert '{% raw %}{{char_name}} - {{char_version|version}} - {{modified_date|date:%Y-%m-%d}}{% endraw %}' in automation_template
    assert '支持字段：char_name、char_version、filename、filename_stem、category、import_time、import_date、modified_time、modified_date' in automation_template
    assert '日期字段支持 date 过滤器' in automation_template
    assert 'date:%Y-%m-%d' in automation_template
    assert 'date:%Y%m%d' in automation_template
    assert 'category = a/b/c  ->  tags += [a, b, c]' in automation_template
    assert 'split_category_to_tags' in automation_template
    assert '不读取模板' in automation_template
    assert '不会使用回退模板或最大长度' in automation_template


def test_automation_help_modal_lists_filter_examples_for_non_jinja_users():
    automation_template = read_project_file('templates/modals/automation.html')

    assert 'automation-template-field-grid' in automation_template
    assert 'automation-template-filter-list' in automation_template
    assert 'trim：去掉首尾空格' in automation_template
    assert 'default：为空时使用备用值' in automation_template
    assert 'limit：截断过长文本' in automation_template
    assert 'date：格式化导入时间或修改时间' in automation_template
    assert 'version：从版本文本里提取主版本号' in automation_template
    assert '{% raw %}{{char_name|trim}}{% endraw %}' in automation_template
    assert '{% raw %}{{char_version|default:unknown}}{% endraw %}' in automation_template
    assert '{% raw %}{{filename_stem|limit:20}}{% endraw %}' in automation_template
    assert '{% raw %}{{import_date|date:%Y-%m-%d}}{% endraw %}' in automation_template
    assert '{% raw %}{{char_version|version}}{% endraw %}' in automation_template


def test_automation_help_modal_uses_reference_card_layout_for_fields_and_filters():
    automation_template = read_project_file('templates/modals/automation.html')
    automation_css = read_project_file('static/css/modules/modal-automation.css')

    assert 'automation-template-reference-grid' in automation_template
    assert 'automation-template-reference-column' in automation_template
    assert 'automation-template-field-grid' in automation_template
    assert 'automation-template-filter-list' in automation_template
    assert '.automation-template-reference-grid' in automation_css
    assert '.automation-template-reference-column' in automation_css
    assert '.automation-template-field-grid' in automation_css
    assert '.automation-template-filter-list' in automation_css


def test_automation_help_modal_includes_template_quick_reference_cheatsheet():
    automation_template = read_project_file('templates/modals/automation.html')

    assert 'automation-template-cheatsheet' in automation_template
    assert '字段写法：' in automation_template
    assert '{% raw %}{{field}}{% endraw %}' in automation_template
    assert '过滤器写法：' in automation_template
    assert '{% raw %}{{field|filter}}{% endraw %}' in automation_template
    assert '带参数过滤器：' in automation_template
    assert '{% raw %}{{field|filter:param}}{% endraw %}' in automation_template


def test_rename_template_action_exposes_quick_fill_example_buttons():
    automation_template = read_project_file('templates/modals/automation.html')
    automation_js = read_project_file('static/js/components/automationModal.js')

    assert '套用示例' in automation_template
    assert '角色名 + 版本' in automation_template
    assert '角色名 + 导入日期' in automation_template
    assert '角色名 + 版本 + 修改日期' in automation_template
    assert 'applyRenameTemplatePreset(action, ' in automation_template
    assert 'applyRenameTemplatePreset(action, preset)' in automation_js
    assert "preset === 'name_version'" in automation_js
    assert "preset === 'name_import_date'" in automation_js
    assert "preset === 'name_version_modified_date'" in automation_js


def test_automation_help_modal_template_examples_are_jinja_safe_literals():
    automation_template = read_project_file('templates/modals/automation.html')

    assert '<code class="font-mono">{{...}}</code>' not in automation_template
    assert '<div class="bg-[var(--bg-code)] p-2 rounded text-xs font-mono">{{char_name}} - {{creator}}</div>' not in automation_template
    assert '<div class="bg-[var(--bg-code)] p-2 rounded text-xs font-mono">{{tags}}</div>' not in automation_template
    assert '{% raw %}{{...}}{% endraw %}' in automation_template
    assert '{% raw %}{{char_name}} - {{char_version|version}} - {{modified_date|date:%Y-%m-%d}}{% endraw %}' in automation_template
    assert 'category = a/b/c  ->  tags += [a, b, c]' in automation_template


def test_automation_help_modal_js_and_css_define_tab_state_and_mobile_layout():
    automation_js = read_project_file('static/js/components/automationModal.js')
    automation_css = read_project_file('static/css/modules/modal-automation.css')
    close_modal_block = extract_js_function_block(automation_js, 'closeModal() {')

    assert "helpActiveTab: 'conditions'" in automation_js
    assert 'openHelpTab(tab)' in automation_js
    assert 'showHelpModal = true' in automation_js
    assert "this.helpActiveTab = tab;" in automation_js
    assert "this.helpActiveTab = 'conditions';" in close_modal_block
    assert 'this.showHelpModal = false;' in close_modal_block

    for selector in (
        '.automation-help-tabs',
        '.automation-help-tab',
        '.automation-help-panel',
    ):
        assert selector in automation_css

    mobile_block = extract_media_block(automation_css, '@media (max-width: 768px)')
    help_tab_block = extract_exact_css_block(automation_css, '.automation-help-tab')
    active_tab_block = extract_exact_css_block(automation_css, '.automation-help-tab.is-active')
    mobile_tabs_block = extract_exact_css_block(mobile_block, '.automation-help-tabs')
    mobile_tab_block = extract_exact_css_block(mobile_block, '.automation-help-tab')

    assert 'border:' in help_tab_block
    assert 'transition:' in help_tab_block
    assert 'border-color: var(--accent-main);' in active_tab_block
    assert 'color: var(--text-main);' in active_tab_block
    assert 'flex-wrap: wrap' in mobile_tabs_block
    assert 'width: 100%' in mobile_tab_block or 'flex: 1 1' in mobile_tab_block


def test_automation_modal_template_exposes_sort_controls_for_groups_conditions_and_actions():
    automation_template = read_project_file('templates/modals/automation.html')

    assert '@click="moveGroup(rIdx, gIdx, -1)"' in automation_template
    assert '@click="moveGroup(rIdx, gIdx, 1)"' in automation_template
    assert '@click="moveConditionInGroup(rIdx, gIdx, cIdx, -1)"' in automation_template
    assert '@click="moveConditionInGroup(rIdx, gIdx, cIdx, 1)"' in automation_template
    assert '@click="moveAction(rIdx, aIdx, -1)"' in automation_template
    assert '@click="moveAction(rIdx, aIdx, 1)"' in automation_template
    assert 'title="上移条件组"' in automation_template
    assert 'title="下移条件组"' in automation_template
    assert 'title="上移条件"' in automation_template
    assert 'title="下移条件"' in automation_template
    assert 'title="上移动作"' in automation_template
    assert 'title="下移动作"' in automation_template
    assert 'automation-inline-actions' in automation_template


def test_automation_modal_js_exposes_reusable_move_helpers_for_nested_rule_items():
    automation_js = read_project_file('static/js/components/automationModal.js')
    move_rule_block = extract_js_function_block(automation_js, 'moveRule(index, dir) {')
    move_group_block = extract_js_function_block(automation_js, 'moveGroup(ruleIdx, groupIdx, dir) {')
    move_condition_block = extract_js_function_block(automation_js, 'moveConditionInGroup(ruleIdx, groupIdx, condIdx, dir) {')
    move_action_block = extract_js_function_block(automation_js, 'moveAction(ruleIdx, actIdx, dir) {')

    assert 'moveArrayItem(items, index, dir) {' in automation_js
    assert 'moveRule(index, dir) {' in automation_js
    assert 'moveGroup(ruleIdx, groupIdx, dir) {' in automation_js
    assert 'moveConditionInGroup(ruleIdx, groupIdx, condIdx, dir) {' in automation_js
    assert 'moveAction(ruleIdx, actIdx, dir) {' in automation_js
    assert 'this.moveArrayItem(this.editingRules, index, dir)' in move_rule_block
    assert 'this.moveArrayItem(groups, groupIdx, dir)' in move_group_block
    assert 'this.moveArrayItem(conditions, condIdx, dir)' in move_condition_block
    assert 'this.moveArrayItem(actions, actIdx, dir)' in move_action_block


def test_automation_modal_css_keeps_inline_sort_actions_compact_and_wrapping():
    automation_css = read_project_file('static/css/modules/modal-automation.css')
    mobile_block = extract_media_block(automation_css, '@media (max-width: 768px)')
    inline_actions_block = extract_exact_css_block(automation_css, '.automation-inline-actions')
    mobile_inline_actions_block = extract_exact_css_block(mobile_block, '.automation-inline-actions')

    assert 'display: flex;' in inline_actions_block
    assert 'align-items: center;' in inline_actions_block
    assert 'gap:' in inline_actions_block
    assert 'flex-wrap: wrap;' in inline_actions_block
    assert 'justify-content: flex-end;' in inline_actions_block
    assert 'width: 100%;' in mobile_inline_actions_block or 'justify-content: flex-start;' in mobile_inline_actions_block


def test_detail_modal_template_marks_multicard_mobile_tabs_for_stacked_layout():
    detail_template = read_project_file('templates/modals/detail_card.html')

    for tab in ('basic', 'persona', 'dialog'):
        assert f'x-show="tab===\'{tab}\'"' in detail_template
    assert detail_template.count('class="detail-section detail-section-fill detail-section-mobile-stack"') >= 3


def test_detail_modal_dialog_editors_allow_first_message_inner_box_to_shrink_with_card_height():
    detail_template = read_project_file('templates/modals/detail_card.html')
    detail_css = read_project_file('static/css/modules/modal-detail.css')

    assert 'class="form-textarea detail-dialog-grow-box detail-first-message-edit-box"' in detail_template
    assert 'class="detail-render-box custom-scrollbar detail-dialog-grow-box detail-first-message-preview-box"' in detail_template
    assert "minHeight: 0" in detail_template

    edit_box_block = extract_exact_css_block(
        detail_css,
        '.detail-section-fill .detail-card .detail-first-message-edit-box',
    )
    preview_box_block = extract_exact_css_block(
        detail_css,
        '.detail-section-fill .detail-card .detail-first-message-preview-box',
    )

    assert 'flex: 1 1 0 !important;' in edit_box_block
    assert 'min-height: 0 !important;' in edit_box_block
    assert 'flex: 1 1 0 !important;' in preview_box_block
    assert 'min-height: 0 !important;' in preview_box_block


def test_detail_modal_mobile_css_releases_equal_height_card_splits_for_stacked_tabs():
    detail_css = read_project_file('static/css/modules/modal-detail.css')
    mobile_detail_css = extract_media_block(detail_css, '@media (max-width: 768px)')

    detail_left_block = extract_exact_css_block(mobile_detail_css, '.detail-left')
    stack_section_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack')
    stack_scroll_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-tab-scroll')
    stack_card_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-tab-scroll > .detail-card')
    stack_textarea_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-card .form-textarea')
    stack_dialog_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-card .detail-dialog-grow-box')
    stack_large_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-card--lg')
    stack_small_block = extract_exact_css_block(mobile_detail_css, '.detail-section-mobile-stack .detail-card--sm')

    assert 'height: clamp(220px, 34vh, 320px);' in detail_left_block
    assert 'min-height: 220px;' in detail_left_block
    assert 'max-height: 38vh;' in detail_left_block

    assert 'flex: 0 0 auto;' in stack_section_block
    assert 'overflow: visible;' in stack_section_block
    assert 'flex: 0 0 auto;' in stack_scroll_block
    assert 'min-height: auto;' in stack_scroll_block
    assert 'overflow: visible;' in stack_scroll_block
    assert 'padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 0.75rem);' in stack_scroll_block
    assert 'flex: 0 0 auto;' in stack_card_block
    assert 'min-height: auto;' in stack_card_block
    assert 'flex: 0 0 auto;' in stack_textarea_block
    assert 'min-height: clamp(6rem, 18vh, 9rem);' in stack_textarea_block
    assert 'flex: 0 0 auto !important;' in stack_dialog_block
    assert 'min-height: clamp(11rem, 30vh, 16rem) !important;' in stack_dialog_block
    assert 'flex: 0 0 auto !important;' in stack_large_block
    assert 'flex: 0 0 auto !important;' in stack_small_block


def test_detail_modal_mobile_css_uses_border_box_chain_and_parent_relative_inner_shell():
    detail_css = read_project_file('static/css/modules/modal-detail.css')
    detail_modal_block = extract_exact_css_block(detail_css, '.detail-modal')
    detail_inner_block = extract_exact_css_block(detail_css, '.detail-modal-inner')
    mobile_detail_css = extract_media_block(detail_css, '@media (max-width: 768px)')
    mobile_detail_modal_block = extract_exact_css_block(mobile_detail_css, '.detail-modal')
    mobile_detail_inner_block = extract_exact_css_block(mobile_detail_css, '.detail-modal-inner')

    assert 'box-sizing: border-box;' in detail_modal_block
    assert 'box-sizing: border-box;' in detail_inner_block
    assert 'height: 100%;' in detail_inner_block
    assert 'max-height: 100%;' in mobile_detail_modal_block
    assert 'height: 100%;' in mobile_detail_inner_block
    assert 'max-height: 100%;' in mobile_detail_inner_block


def test_mobile_layout_css_keeps_sidebar_shell_scrollable_inside_visual_viewport():
    layout_css = read_project_file('static/css/modules/layout.css')
    mobile_layout_css = extract_media_block(layout_css, '@media (max-width: 768px)')

    sidebar_mobile_block = extract_exact_css_block(layout_css, '.sidebar-mobile')
    assert 'height: 100%;' in sidebar_mobile_block
    assert 'max-height: 100%;' in sidebar_mobile_block
    assert '.sidebar-mobile {' in mobile_layout_css
    assert 'overflow-y: auto;' in mobile_layout_css
    assert '-webkit-overflow-scrolling: touch;' in mobile_layout_css


def test_card_pagination_mobile_css_anchors_bar_with_dynamic_viewport_and_box_sizing():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    mobile_cards_css = extract_media_block(cards_css, '@media (max-width: 768px)')

    assert 'box-sizing: border-box;' in extract_exact_css_block(cards_css, '.card-pagination-bar')
    assert 'max-width: 100%;' in mobile_cards_css
    assert 'box-sizing: border-box;' in mobile_cards_css


def test_card_hover_clarity_css_removes_backdrop_blur_from_tag_text_surfaces():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    tag_block = extract_exact_css_block(cards_css, '.card-image-tags-wrap .card-tag')
    neutral_tag_block = extract_exact_css_block(
        cards_css,
        '.card-image-tags-wrap .card-tag-filter:not(.is-included):not(.is-excluded)',
    )
    light_tag_block = extract_exact_css_block(
        cards_css,
        'html.light-mode .card-image-tags-wrap .card-tag',
    )
    light_neutral_tag_block = extract_exact_css_block(
        cards_css,
        'html.light-mode\n  .card-image-tags-wrap\n  .card-tag-filter:not(.is-included):not(.is-excluded)',
    )

    assert 'backdrop-filter: var(--tag-chip-backdrop);' not in tag_block
    assert '-webkit-backdrop-filter: var(--tag-chip-backdrop);' not in tag_block
    assert 'backdrop-filter: none;' in tag_block
    assert '-webkit-backdrop-filter: none;' in tag_block
    assert 'backdrop-filter: none;' in neutral_tag_block
    assert '-webkit-backdrop-filter: none;' in neutral_tag_block
    assert 'backdrop-filter: var(--tag-chip-backdrop);' not in light_tag_block
    assert '-webkit-backdrop-filter: var(--tag-chip-backdrop);' not in light_tag_block
    assert 'backdrop-filter: none;' in light_tag_block
    assert '-webkit-backdrop-filter: none;' in light_tag_block
    assert 'backdrop-filter: none;' in light_neutral_tag_block
    assert '-webkit-backdrop-filter: none;' in light_neutral_tag_block


def test_card_hover_clarity_css_keeps_back_note_surface_sharp_without_losing_hover_feedback():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    hover_block = extract_exact_css_block(cards_css, '.st-card:hover')
    back_block = extract_exact_css_block(cards_css, '.card-back')
    flipped_back_block = extract_exact_css_block(cards_css, '.card-flip-inner.is-flipped .card-back')
    note_block = extract_exact_css_block(cards_css, '.local-note-preview')

    assert 'transform: translateY(-4px);' in hover_block
    assert 'box-shadow:' in hover_block
    assert 'brightness(0.9) saturate(0.94)' not in back_block
    assert 'brightness(1) saturate(1)' not in flipped_back_block
    assert 'background:' in note_block
    assert 'border: 1px solid' in note_block
    assert '.st-card:hover .card-source-link-fab,' in cards_css
    assert '.st-card:hover .card-fav-overlay,' in cards_css


def test_card_back_mobile_css_allows_local_note_to_fill_remaining_space():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    mobile_cards_css = extract_media_block(cards_css, '@media (max-width: 768px)')
    back_note_block = extract_exact_css_block(mobile_cards_css, '.card-back-note')

    assert 'max-height: 3.2rem;' not in back_note_block
    assert 'max-height: none;' in back_note_block
    assert 'flex: 1 1 auto;' in back_note_block


def test_card_sidebar_template_hides_complete_library_action_until_mobile_tags_panel_expands():
    sidebar_template = read_project_file('templates/components/sidebar.html')

    assert 'x-show="$store.global.deviceType !== \'mobile\' || tagsSectionExpanded"' in sidebar_template


def test_worldinfo_sidebar_template_includes_category_tree_section():
    sidebar_template = read_project_file('templates/components/sidebar.html')

    assert "currentMode === 'worldinfo'" in sidebar_template
    assert '世界书分类' in sidebar_template
    assert 'wiFolderTree' in sidebar_template
    assert 'setWiCategory' in sidebar_template
    assert 'getWiCategoryCount' in sidebar_template
    assert 'getFolderCapabilities' in sidebar_template
    assert 'can_create_child_folder' in sidebar_template


def test_preset_sidebar_template_includes_category_tree_section():
    sidebar_template = read_project_file('templates/components/sidebar.html')

    assert "currentMode === 'presets'" in sidebar_template
    assert '预设分类' in sidebar_template
    assert 'presetFolderTree' in sidebar_template
    assert 'setPresetCategory' in sidebar_template
    assert 'getPresetCategoryCount' in sidebar_template
    assert 'folder_capabilities' in sidebar_template or 'getFolderCapabilities' in sidebar_template


def test_worldinfo_grid_template_exposes_category_metadata_and_mode_hints():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'display_category' not in wi_grid_template
    assert 'category_mode' not in wi_grid_template
    assert 'showWorldInfoCategoryActions(item, $event)' not in wi_grid_template
    assert '移动到分类' not in wi_grid_template
    assert '设置管理器分类' not in wi_grid_template
    assert '恢复跟随角色卡' not in wi_grid_template
    assert '(item.source_type || item.type) === \'embedded\'' not in wi_grid_template
    assert 'selectedIds.includes(item.id)' in wi_grid_template
    assert 'toggleSelection(item)' in wi_grid_template
    assert 'handleWorldInfoClick($event, item)' in wi_grid_template
    assert '@click.ctrl.stop' not in wi_grid_template
    assert 'draggable="true"' in wi_grid_template
    assert 'jumpToCardFromWi(getWorldInfoOwnerId(item))' in wi_grid_template
    assert '如需调整分类，请移动所属角色卡' not in wi_grid_template
    assert '分类：' not in wi_grid_template
    assert '跟随角色卡' not in wi_grid_template
    assert '已覆盖管理器分类' not in wi_grid_template
    assert '内嵌世界书跟随角色卡分类' not in wi_grid_template
    assert 'isEmbeddedWorldInfo(item)' not in wi_grid_template
    assert 'locateWorldInfoOwnerCard(item)' not in wi_grid_template
    assert 'wi-book-classification' not in wi_grid_template


def test_worldinfo_grid_template_supports_flip_note_preview_and_note_actions():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'card-flip-inner' in wi_grid_template
    assert ':key="getWorldInfoRenderKey(item)"' in wi_grid_template
    assert 'wi-item-flip-corner' in wi_grid_template
    assert 'local-note-preview wi-back-note' in wi_grid_template
    assert 'toggleWorldInfoFace(item.id)' in wi_grid_template
    assert 'worldInfoHasLocalNote(item)' in wi_grid_template
    assert 'openWorldInfoLocalNote(item)' in wi_grid_template


def test_worldinfo_grid_template_uses_info_card_front_layout():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'wi-card-header' in wi_grid_template
    assert 'wi-card-primary' in wi_grid_template
    assert 'wi-card-owner-row' in wi_grid_template
    assert 'wi-card-tag-placeholder' in wi_grid_template
    assert '标签待接入' in wi_grid_template or 'getWorldInfoTagPlaceholder(item)' in wi_grid_template


def test_worldinfo_grid_template_groups_title_owner_and_tag_summary():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')
    primary_block = extract_balanced_tag_block(wi_grid_template, '<div class="wi-card-primary">')

    assert 'wi-card-title-group' in wi_grid_template
    assert 'wi-card-tag-summary' in wi_grid_template
    title_group_index = primary_block.index('wi-card-title-group')
    owner_row_index = primary_block.index('wi-card-owner-row')
    tag_summary_index = primary_block.index('wi-card-tag-summary')
    assert title_group_index < owner_row_index < tag_summary_index


def test_worldinfo_grid_template_uses_css_drawn_archive_markers():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')
    owner_row_block = wi_grid_template.split('class="wi-card-owner-row"', 1)[1].split('</template>', 1)[0]

    assert 'class="wi-card-bookmark" aria-hidden="true"' in wi_grid_template
    assert 'class="wi-card-owner-icon"' in owner_row_block
    assert 'aria-hidden="true"' in owner_row_block
    assert '📖' not in wi_grid_template
    assert '🔗' not in wi_grid_template


def test_worldinfo_grid_template_preserves_visual_icon_anchor():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'wi-card-title-row' in wi_grid_template
    assert 'wi-card-bookmark' in wi_grid_template


def test_worldinfo_css_preserves_front_visual_treatment():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '.wi-card-title-row' in wi_css
    assert '.wi-card-bookmark' in wi_css
    assert '.wi-card-front::before' in wi_css or '.wi-card-front::after' in wi_css


def test_worldinfo_css_exposes_archive_front_groups_and_light_mode_palette():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '.wi-card-title-group {' in wi_css
    assert '.wi-card-tag-summary {' in wi_css
    assert '.wi-card-owner-icon::before' in wi_css
    assert 'html.light-mode .wi-card-front {' in wi_css
    assert 'html.light-mode .wi-card-title-row::before' in wi_css
    assert 'html.light-mode .wi-card-tag-summary {' in wi_css


def test_worldinfo_css_separates_badge_tag_and_note_state_visual_weight():
    wi_css = read_project_file('static/css/modules/view-wi.css')
    header_actions_block = extract_exact_css_block(wi_css, '.wi-card-header-actions')
    footer_block = extract_exact_css_block(wi_css, '.wi-card-footer')
    footer_info_block = extract_exact_css_block(wi_css, '.wi-card-footer-info')
    footer_tools_block = extract_exact_css_block(wi_css, '.wi-card-footer-tools')
    date_chip_block = extract_exact_css_block(wi_css, '.wi-card-date-chip')

    assert '.wi-card-tag-placeholder::before' in wi_css
    assert 'padding-right:' not in header_actions_block
    assert 'flex-direction: column;' in footer_block
    assert 'align-items: stretch;' in footer_block
    assert 'justify-content: space-between;' not in footer_block
    assert 'display: flex;' in footer_info_block
    assert 'display: flex;' in footer_tools_block
    assert 'padding-right: 1.75rem;' in footer_tools_block
    assert 'margin-left: auto;' in date_chip_block
    assert '.wi-card-note-state {' not in wi_css


def test_worldinfo_css_archive_tag_summary_overrides_placeholder_rules():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    placeholder_index = wi_css.index('.wi-card-tag-placeholder {')
    archive_override_index = wi_css.index('.wi-card-tag-placeholder.wi-card-tag-summary {')
    assert placeholder_index < archive_override_index
    assert '.wi-card-tag-placeholder.wi-card-tag-summary::before {' in wi_css


def test_worldinfo_css_styles_archive_backface_and_catalog_meta():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '.wi-card-back-header::after' in wi_css
    assert '.wi-card-back-note-wrap::before' in wi_css
    assert 'html.light-mode .wi-card-back {' in wi_css
    assert 'html.light-mode .wi-card-meta-chip {' in wi_css
    assert 'html.light-mode .wi-card-note-state.has-note {' not in wi_css


def test_worldinfo_css_back_header_reserves_space_for_catalog_stamp():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    back_header_block = extract_exact_css_block(wi_css, '.wi-card-back-header')
    assert '.wi-card-back-header::after' in wi_css
    assert 'padding:' in back_header_block

    padding_match = re.search(r'padding\s*:\s*([^;]+);', back_header_block)
    assert padding_match is not None

    padding_values = padding_match.group(1).split()
    assert len(padding_values) == 4

    right_padding_match = re.fullmatch(r'([0-9]*\.?[0-9]+)([a-z%]+)', padding_values[1])
    left_padding_match = re.fullmatch(r'([0-9]*\.?[0-9]+)([a-z%]+)', padding_values[3])

    assert right_padding_match is not None
    assert left_padding_match is not None
    assert right_padding_match.group(2) == left_padding_match.group(2)
    assert float(right_padding_match.group(1)) > float(left_padding_match.group(1))


def test_worldinfo_mobile_back_note_is_constrained_within_card_bounds():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '@media (max-width: 768px)' in wi_css
    assert '.wi-card-back-note-wrap' in wi_css
    assert '.wi-back-note' in wi_css
    mobile_block = wi_css.split('@media (max-width: 768px) {', 1)[1]
    back_note_mobile_block = mobile_block.split('.wi-back-note {', 1)[1].split('}', 1)[0]
    assert '.wi-card-back {' in wi_css
    assert 'overflow: hidden;' in wi_css
    assert 'min-height: 0;' in back_note_mobile_block


def test_worldinfo_mobile_css_reuses_shared_page_boundary_tokens_for_front_and_back():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '@media (max-width: 768px)' in wi_css
    mobile_block = extract_media_block(wi_css, '@media (max-width: 768px)')
    front_mobile_block = extract_exact_css_block(mobile_block, '.wi-card-front')
    back_note_wrap_mobile_block = extract_exact_css_block(mobile_block, '.wi-card-back-note-wrap')
    back_note_frame_mobile_block = extract_exact_css_block(mobile_block, '.wi-card-back-note-wrap::before')
    footer_block = extract_exact_css_block(mobile_block, '.wi-card-footer')
    footer_info_block = extract_exact_css_block(mobile_block, '.wi-card-footer-info')
    footer_tools_block = extract_exact_css_block(mobile_block, '.wi-card-footer-tools')

    assert '--wi-card-page-inset-x:' in mobile_block
    assert '--wi-card-page-inset-y:' in mobile_block
    assert '--wi-card-page-frame-inset:' in mobile_block
    assert 'padding: var(--wi-card-page-inset-y) var(--wi-card-page-inset-x);' in front_mobile_block
    assert 'padding: 0.18rem var(--wi-card-page-inset-x) var(--wi-card-page-inset-y);' in back_note_wrap_mobile_block
    assert 'inset: 0.1rem var(--wi-card-page-inset-x) var(--wi-card-page-inset-y);' in back_note_frame_mobile_block
    assert 'align-items: stretch;' in footer_block
    assert 'gap: 0.36rem;' in footer_block
    assert 'gap: 0.42rem;' in footer_info_block
    assert 'padding-right: 1.5rem;' in footer_tools_block
    assert '.wi-card-footer-meta' not in mobile_block
    assert '.wi-card-header-actions,' not in mobile_block


def test_worldinfo_grid_template_uses_back_note_reading_layout():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'wi-card-back-note-wrap' in wi_grid_template
    assert 'wi-card-back-meta' in wi_grid_template
    assert 'card-bottom-toolbar wi-card-bottom-toolbar' not in wi_grid_template


def test_worldinfo_grid_template_uses_shell_padding_only_for_flip_corner_space():
    wi_grid_template = read_project_file('templates/components/grid_wi.html')

    assert 'class="wi-grid-card group relative rounded-xl p-[1px] cursor-pointer transition-all duration-200 flex flex-col"' in wi_grid_template
    assert 'class="wi-grid-card group relative border rounded-xl p-3 cursor-pointer transition-all duration-200 flex flex-col"' not in wi_grid_template
    assert 'style="background: var(--bg-panel); border-color: var(--border-main);"' not in wi_grid_template


def test_worldinfo_css_uses_single_shell_card_and_stretches_flip_inner():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    grid_card_block = extract_exact_css_block(wi_css, '.wi-grid-card')
    assert 'padding: 0;' in grid_card_block
    assert 'background: transparent;' in grid_card_block
    assert 'border-color: transparent;' in grid_card_block

    flip_inner_block = extract_exact_css_block(wi_css, '.wi-grid-card .card-flip-inner')
    assert 'height: 100%;' in flip_inner_block


def test_worldinfo_mobile_card_shell_uses_fixed_height_for_windowed_grid():
    wi_css = read_project_file('static/css/modules/view-wi.css')
    mobile_block = extract_media_block(wi_css, '@media (max-width: 768px)')
    grid_card_mobile_block = extract_exact_css_block(mobile_block, '.wi-grid-card')

    assert 'height:' in grid_card_mobile_block
    assert 'min-height:' not in grid_card_mobile_block


def test_worldinfo_css_exposes_shared_page_boundary_tokens_for_card_faces():
    wi_css = read_project_file('static/css/modules/view-wi.css')
    face_selector = '.wi-card-front,\n.wi-card-back'
    face_block = extract_exact_css_block(wi_css, face_selector)
    front_block = extract_exact_css_block(wi_css, '.wi-card-front')
    back_block = extract_exact_css_block(wi_css, '.wi-card-back')
    front_frame_block = extract_exact_css_block(wi_css, '.wi-card-front::before')
    back_note_wrap_block = extract_exact_css_block(wi_css, '.wi-card-back-note-wrap')
    back_note_frame_block = extract_exact_css_block(wi_css, '.wi-card-back-note-wrap::before')

    assert '--wi-card-page-inset-x:' in wi_css
    assert '--wi-card-page-inset-y:' in wi_css
    assert '--wi-card-page-frame-inset:' in wi_css
    assert 'position: absolute;' in front_block
    assert 'inset: 0;' in front_block
    assert 'padding: var(--wi-card-page-inset-y) var(--wi-card-page-inset-x);' in front_block
    assert 'position: absolute;' not in back_block
    assert 'inset: var(--wi-card-page-frame-inset);' in front_frame_block
    assert 'padding: 0.18rem var(--wi-card-page-inset-x) var(--wi-card-page-inset-y);' in back_note_wrap_block
    assert 'inset: 0.1rem var(--wi-card-page-inset-x) var(--wi-card-page-inset-y);' in back_note_frame_block
    assert 'border-radius: inherit;' in face_block


def test_worldinfo_css_keeps_flip_corner_on_outer_shell_instead_of_face_offsets():
    wi_css = read_project_file('static/css/modules/view-wi.css')
    card_css = read_project_file('static/css/modules/view-cards.css')
    grid_card_block = extract_exact_css_block(wi_css, '.wi-grid-card')
    front_block = extract_exact_css_block(wi_css, '.wi-card-front')
    header_actions_block = extract_exact_css_block(wi_css, '.wi-card-header-actions')
    footer_tools_block = extract_exact_css_block(wi_css, '.wi-card-footer-tools')
    flip_corner_block = extract_exact_css_block(card_css, '.card-flip-corner')

    assert 'padding: 0;' in grid_card_block
    assert 'position: absolute;' in front_block
    assert 'inset: 0;' in front_block
    assert 'padding-right:' not in header_actions_block
    assert 'padding-right: 1.75rem;' in footer_tools_block
    assert '.wi-item-flip-corner {' in wi_css
    assert 'right: 0;' in flip_corner_block
    assert 'bottom: 0;' in flip_corner_block
    assert 'width: 2rem;' in flip_corner_block
    assert 'height: 2rem;' in flip_corner_block


def test_worldinfo_detail_template_uses_embedded_character_note_wording():
    wi_detail_template = read_project_file('templates/modals/detail_wi_popup.html')

    assert "activeWiDetail?.type === 'embedded'" in wi_detail_template
    assert '角色卡备注' in wi_detail_template
    assert '本地备注' in wi_detail_template
    assert '清空角色卡备注' in wi_detail_template
    assert '清空备注' in wi_detail_template
    assert "placeholder=\"activeWiDetail?.type === 'embedded' ? '这是仅存储在角色卡中的私有备注，不会写入世界书文件...' : '这是仅存储在本地的私有备注，不会写入世界书文件...'\"" in wi_detail_template
    assert 'saveActiveWorldInfoNote()' in wi_detail_template
    assert 'clearActiveWorldInfoNote()' in wi_detail_template
    assert 'openActiveWorldInfoNotePreview()' in wi_detail_template


def test_worldinfo_editor_template_uses_embedded_character_note_wording():
    wi_editor_template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert "editingWiFile?.type === 'embedded'" in wi_editor_template
    assert '角色卡备注 (Character Note)' in wi_editor_template
    assert '本地备注 (Local Note)' in wi_editor_template
    assert "placeholder=\"editingWiFile?.type === 'embedded' ? '这是仅存储在角色卡中的私有备注，不会写入世界书文件...' : '这是仅存储在本地的私有备注，不会写入世界书文件...'\"" in wi_editor_template
    assert 'openLargeEditor(' in wi_editor_template
    assert 'ui_summary' in wi_editor_template
    assert 'saveEditingWorldInfoNote()' in wi_editor_template
    assert 'openEditingWorldInfoNotePreview()' in wi_editor_template


def test_worldinfo_frontend_note_sources_switch_embedded_saves_to_update_card():
    wi_detail_source = read_project_file('static/js/components/wiDetailPopup.js')
    wi_editor_source = read_project_file('static/js/components/wiEditor.js')
    detail_save_block = extract_js_function_block(wi_detail_source, 'async saveActiveWorldInfoNote()')
    editor_save_block = extract_js_function_block(wi_editor_source, 'async saveEditingWorldInfoNote()')
    editor_label_block = extract_js_function_block(wi_editor_source, 'getEditingWorldInfoNoteLabel()')

    assert 'updateCard' in wi_detail_source
    assert 'saveWorldInfoNote' in wi_detail_source
    assert 'embedded' in wi_detail_source
    assert 'updateCard' in detail_save_block
    assert 'saveWorldInfoNote' in detail_save_block
    assert 'card_id' in wi_detail_source

    assert 'updateCard' in wi_editor_source
    assert 'saveWorldInfoNote' in wi_editor_source
    assert 'embedded' in wi_editor_source
    assert 'embedded' in editor_label_block
    assert '角色卡备注' in editor_label_block
    assert '本地备注' in editor_label_block
    assert 'updateCard' in editor_save_block
    assert 'saveWorldInfoNote' in editor_save_block
    assert 'card_id' in wi_editor_source


def test_preset_grid_template_exposes_category_metadata_and_mode_hints():
    preset_grid_template = read_project_file('templates/components/grid_presets.html')

    assert 'display_category' not in preset_grid_template
    assert 'category_mode' not in preset_grid_template
    assert 'showPresetCategoryActions(item, $event)' not in preset_grid_template
    assert '移动到分类' not in preset_grid_template
    assert '设置管理器分类' not in preset_grid_template
    assert '恢复跟随角色卡' not in preset_grid_template
    assert '分类：' not in preset_grid_template
    assert 'class="text-[10px] text-[var(--text-dim)] space-y-1 mb-3"' not in preset_grid_template
    assert 'selectedIds.includes(item.id)' in preset_grid_template
    assert 'toggleSelection(item)' in preset_grid_template
    assert 'handlePresetClick($event, item)' in preset_grid_template
    assert '@click.ctrl.stop' not in preset_grid_template
    assert 'draggable="true"' in preset_grid_template


def test_state_js_tracks_mode_specific_category_state_for_worldinfo_and_presets():
    state_source = read_project_file('static/js/state.js')

    assert 'wiFilterCategory' in state_source
    assert 'wiAllFolders' in state_source
    assert 'wiCategoryCounts' in state_source
    assert 'wiFolderCapabilities' in state_source
    assert 'presetFilterCategory' in state_source
    assert 'presetAllFolders' in state_source
    assert 'presetCategoryCounts' in state_source
    assert 'presetFolderCapabilities' in state_source


def test_sidebar_js_handles_mode_specific_category_trees_and_capability_gating():
    sidebar_source = read_project_file('static/js/components/sidebar.js')

    assert 'wiFolderTree' in sidebar_source
    assert 'presetFolderTree' in sidebar_source
    assert 'setWiCategory' in sidebar_source
    assert 'setPresetCategory' in sidebar_source
    assert 'getFolderCapabilities(path, mode = this.currentMode)' in sidebar_source
    assert 'reset invalid category selection to root' not in sidebar_source
    assert js_contains(sidebar_source, 'this.$watch(\'$store.global.wiAllFolders\'')
    assert js_contains(sidebar_source, 'this.$watch(\'$store.global.presetAllFolders\'')


def test_worldinfo_grid_js_uses_category_metadata_and_explicit_upload_fallback_contract():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')

    assert 'category: this.wiFilterCategory' in wi_grid_source
    assert 'all_folders' in wi_grid_source
    assert 'category_counts' in wi_grid_source
    assert 'folder_capabilities' in wi_grid_source
    assert 'target_category' in wi_grid_source
    assert 'requires_global_fallback_confirmation' in wi_grid_source
    assert 'allow_global_fallback' in wi_grid_source
    assert 'toggleSelection(item)' in wi_grid_source
    assert 'handleWorldInfoClick(e, item)' in wi_grid_source
    assert 'if (e.ctrlKey || e.metaKey)' in wi_grid_source
    assert 'if (e.shiftKey && this.lastSelectedId)' in wi_grid_source
    assert 'dragStart(e, item)' in wi_grid_source
    assert 'canSelectWorldInfoItem(item)' in wi_grid_source
    assert 'canDeleteWorldInfoSelection()' in wi_grid_source
    assert 'canMoveWorldInfoSelection()' in wi_grid_source
    assert 'deleteSelectedWorldInfo()' in wi_grid_source
    assert 'if (!this.canSelectWorldInfoItem(item)) return;' in wi_grid_source
    assert "this.wiFilterType === 'global' || this.wiFilterType === 'all'" in wi_grid_source or 'this.wiFilterType === "global" || this.wiFilterType === "all"' in wi_grid_source
    assert 'owner_card_id' in wi_grid_source
    assert 'owner_card_name' in wi_grid_source
    assert 'source_type' in wi_grid_source
    assert 'movableItems.length !== selectedItems.length' not in wi_grid_source
    assert 'ids = [item.id]' not in wi_grid_source
    assert 'if (!this.canMoveWorldInfoSelection()) {' in wi_grid_source


def test_worldinfo_grid_js_syncs_local_note_updates_without_waiting_for_refetch():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')

    assert 'wi-note-updated' in wi_grid_source
    assert 'getWorldInfoRenderKey(item)' in wi_grid_source
    assert 'item.id !== detail.id' in wi_grid_source or 'item.id === detail.id' in wi_grid_source
    assert "item.ui_summary = detail.ui_summary || ''" in wi_grid_source or 'item.ui_summary = detail.ui_summary || ""' in wi_grid_source
    assert 'this.wiList = currentItems;' in wi_grid_source


def test_worldinfo_grid_js_exposes_redesign_display_helpers():
    wi_grid_source = read_project_file('static/js/components/wiGrid.js')
    wi_grid_template = read_project_file('templates/components/grid_wi.html')
    note_title_block = extract_js_function_block(wi_grid_source, 'getWorldInfoNoteTitle(item)')
    note_empty_block = extract_js_function_block(wi_grid_source, 'getWorldInfoEmptyNoteText(item)')
    note_preview_block = extract_js_function_block(wi_grid_source, 'getWorldInfoNotePreviewTitle(item)')
    note_state_block = extract_js_function_block(wi_grid_source, 'getWorldInfoNoteState(item)')

    assert 'getWorldInfoRenderKey(item)' in wi_grid_source
    assert 'getWorldInfoTagPlaceholder(' in wi_grid_source
    assert 'getWorldInfoNoteState(' in wi_grid_source
    assert "const sourceType = item?.source_type || item?.type;" in note_title_block
    assert "const sourceType = item?.source_type || item?.type;" in note_empty_block
    assert "const sourceType = item?.source_type || item?.type;" in note_preview_block
    assert "const sourceType = item?.source_type || item?.type;" in note_state_block
    assert 'getWorldInfoEmptyNoteText(item)' in wi_grid_template


def test_preset_grid_js_uses_category_metadata_and_explicit_upload_fallback_contract():
    preset_grid_source = read_project_file('static/js/components/presetGrid.js')

    assert 'category=' in preset_grid_source
    assert 'all_folders' in preset_grid_source
    assert 'category_counts' in preset_grid_source
    assert 'folder_capabilities' in preset_grid_source
    assert 'target_category' in preset_grid_source
    assert 'requires_global_fallback_confirmation' in preset_grid_source
    assert 'allow_global_fallback' in preset_grid_source
    assert 'toggleSelection(item)' in preset_grid_source
    assert 'handlePresetClick(e, item)' in preset_grid_source
    assert 'if (e.ctrlKey || e.metaKey)' in preset_grid_source
    assert 'if (e.shiftKey && this.lastSelectedId)' in preset_grid_source
    assert 'dragStart(e, item)' in preset_grid_source
    assert 'canSelectPresetItem(item)' in preset_grid_source
    assert 'canDeletePresetSelection()' in preset_grid_source
    assert 'canMovePresetSelection()' in preset_grid_source
    assert 'deleteSelectedPresets()' in preset_grid_source
    assert 'moveSelectedPresets(targetCategory = this.filterCategory || ' in preset_grid_source
    assert 'selectedPresetItems()' in preset_grid_source
    assert 'isPresetMovable(item)' in preset_grid_source
    assert '当前选中的预设包含资源绑定项，不能移动分类' in preset_grid_source
    assert 'ids = Array.of(item.id);' not in preset_grid_source
    drag_start_block = extract_js_function_block(preset_grid_source, 'dragStart(e, item)')
    assert 'selectedItems.length === 0' in drag_start_block
    assert 'selectedItems.every((currentItem) => this.isPresetMovable(currentItem))' in drag_start_block
    assert drag_start_block.index('selectedItems.length === 0') < drag_start_block.index('this.selectedIds = ids;')
    assert 'this.filterType === "global" || this.filterType === "all"' in preset_grid_source
    assert 'owner_card_id' in preset_grid_source
    assert 'owner_card_name' in preset_grid_source
    assert 'source_type' in preset_grid_source
    assert 'showPresetCategoryActions' not in preset_grid_source
    assert 'movePresetToCategory(item)' not in preset_grid_source
    assert 'resetPresetCategory(item)' not in preset_grid_source


def test_preset_grid_js_delegates_detail_rendering_to_reader_without_local_detail_state():
    preset_grid_source = read_project_file('static/js/components/presetGrid.js')
    open_preset_detail_block = extract_js_function_block(
        preset_grid_source,
        'openPresetDetail(item) {',
    )
    state_block = preset_grid_source[
        preset_grid_source.index('return {'):preset_grid_source.index('get selectedIds() {')
    ]

    assert 'new CustomEvent("open-preset-reader"' in open_preset_detail_block
    assert 'detail: {' in open_preset_detail_block
    assert '...item,' in open_preset_detail_block
    assert 'id: openId,' in open_preset_detail_block

    for dead_state_field in (
        'selectedPreset:',
        'showDetailModal:',
        'activePresetDetail:',
        'showPresetDetailModal:',
        'activePresetItem:',
        'activePresetItemType:',
        'uiPresetFilter:',
        'showMobileSidebar:',
    ):
        assert dead_state_field not in state_block

    for dead_helper_signature in (
        'async openPreset(item) {',
        'closeDetailModal() {',
        'closePresetDetailModal() {',
        'selectPresetItem(item, type, shouldScroll = false) {',
        'get filteredPresetItems() {',
        'get totalPresetItems() {',
        'openAdvancedExtensions() {',
        'async savePresetExtensions(extensions) {',
        'createSnapshot(type) {',
        'openRollback() {',
        'openBackupFolder(type) {',
        'deleteCurrentPreset() {',
        'editPresetRawFromDetail() {',
        'editPresetRaw() {',
        'formatSize(bytes) {',
        'formatParam(val) {',
        'formatPromptContent(val) {',
        'pickPromptContent(prompt) {',
        'collectPromptMeta(prompt) {',
        'normalizePrompts(list) {',
    ):
        assert dead_helper_signature not in preset_grid_source

    assert 'toggleSelection(item)' in preset_grid_source
    assert 'selectedPresetItems()' in preset_grid_source
    assert 'deleteSelectedPresets()' in preset_grid_source
    assert 'moveSelectedPresets(targetCategory = this.filterCategory || ' in preset_grid_source
    assert 'async exportPresetItem(item, event = null)' in preset_grid_source
    assert 'formatDate(ts) {' in preset_grid_source


def test_preset_grid_template_uses_selection_without_card_level_category_actions():
    preset_template = read_project_file('templates/components/grid_presets.html')

    assert 'toggleSelection(item)' in preset_template
    assert 'handlePresetClick($event, item)' in preset_template
    assert 'dragStart($event, item)' in preset_template
    assert 'draggable="true"' in preset_template
    assert 'data-preset-id' in preset_template
    assert 'showPresetCategoryActions' not in preset_template
    assert '移动到分类' not in preset_template
    assert '跟随角色卡' not in preset_template
    assert '已覆盖管理器分类' not in preset_template
    assert '<span>分类：</span>' not in preset_template
    assert 'locatePresetOwnerCard(item)' in preset_template
    assert 'class="text-[10px] text-[var(--text-dim)] space-y-1 mb-3"' not in preset_template


def test_preset_grid_js_exposes_send_to_st_state_and_event_sync_contracts():
    preset_grid_source = read_project_file('static/js/components/presetGrid.js')

    assert 'sendingPresetToStIds:' in preset_grid_source
    assert 'canSendPresetToST(item)' in preset_grid_source
    assert 'getPresetSendToSTTitle(item)' in preset_grid_source
    assert 'applyPresetSentState(detail)' in preset_grid_source
    assert 'window.addEventListener("preset-sent-to-st"' in preset_grid_source or "window.addEventListener('preset-sent-to-st'" in preset_grid_source
    assert 'async sendPresetToST(item, event = null)' in preset_grid_source


def test_preset_grid_template_footer_exposes_send_to_st_button_contract():
    preset_template = read_project_file('templates/components/grid_presets.html')

    assert 'card-send-st-btn' in preset_template
    assert '@click.stop="sendPresetToST(item, $event)"' in preset_template
    assert ':title="getPresetSendToSTTitle(item)"' in preset_template


def test_sidebar_template_uses_scrollable_worldinfo_and_preset_category_sections():
    sidebar_template = read_project_file('templates/components/sidebar.html')
    sidebar_source = read_project_file('static/js/components/sidebar.js')
    layout_css = read_project_file('static/css/modules/layout.css')

    assert 'worldinfo-sidebar-tree' in sidebar_template
    assert 'preset-sidebar-tree' in sidebar_template
    assert "currentMode === 'worldinfo' && visibleSidebar" in sidebar_template
    assert "currentMode === 'presets' && visibleSidebar" in sidebar_template
    assert "class=\"p-4 space-y-2 flex-1 min-h-0 flex flex-col\"" in sidebar_template
    assert '@dragover.prevent="handleDragOverRoot($event)"' in sidebar_template
    assert '@drop.prevent="handleDropOnRoot($event)"' in sidebar_template
    assert '@dragover.prevent="presetRootDragOver($event)"' in sidebar_template
    assert '@drop.prevent="presetRootDrop($event)"' in sidebar_template
    assert "folderDragOver($event, { ...folder, mode: 'presets' })" in sidebar_template
    assert "folderDrop($event, { ...folder, mode: 'presets' })" in sidebar_template
    assert 'canMovePresetSelection()' in sidebar_source
    assert 'presetRootDrop(e)' in sidebar_source
    assert 'presetRootDragOver(e)' in sidebar_source
    assert '.worldinfo-sidebar-tree,' in layout_css
    assert '.preset-sidebar-tree {' in layout_css
    assert 'min-height: 0;' in layout_css
    assert 'overflow-y: auto;' in layout_css


def test_worldinfo_css_exposes_hover_visible_selection_overlay():
    wi_css = read_project_file('static/css/modules/view-wi.css')

    assert '.wi-grid-card:hover .card-select-overlay' in wi_css


def test_header_selection_bar_switches_to_worldinfo_specific_actions():
    header_template = read_project_file('templates/components/header.html')
    header_source = read_project_file('static/js/components/header.js')

    assert "currentMode === 'worldinfo'" in header_template
    assert 'deleteSelectedWorldInfo()' in header_template
    assert 'moveSelectedWorldInfo()' in header_template
    assert 'canMoveWorldInfoSelection()' in header_template
    assert 'openBatchTagModal()' in header_template
    assert 'executeRuleSet(rs.id)' in header_template
    assert 'deleteSelectedWorldInfo()' in header_source
    assert 'canDeleteWorldInfoSelection()' in header_source
    assert 'canMoveWorldInfoSelection()' in header_source
    assert 'selectedWorldInfoItems()' in header_source


def test_header_selection_bar_switches_to_preset_specific_actions():
    header_template = read_project_file('templates/components/header.html')
    header_source = read_project_file('static/js/components/header.js')
    desktop_selection_bar_start = header_template.index('<!-- 桌面端：右侧操作区 -->')
    desktop_selection_bar_end = header_template.index('<!-- 搜索与筛选区 -->')
    desktop_selection_bar = header_template[desktop_selection_bar_start:desktop_selection_bar_end]

    assert "currentMode === 'presets'" in header_template
    assert 'mergeSelectedPresets()' in header_template
    assert 'canMergePresetSelection()' in header_template
    assert 'getPresetMergeSelectionTitle()' in header_template
    assert ':disabled="!canMergePresetSelection()"' in header_template
    assert ':title="getPresetMergeSelectionTitle()"' in header_template
    assert 'mergeSelectedPresets()' in desktop_selection_bar
    assert 'canMergePresetSelection()' in desktop_selection_bar
    assert "x-show=\"selectedIds.length > 1 && currentMode === 'presets'\"" in desktop_selection_bar
    assert "x-show=\"currentMode === 'presets' && canMergePresetSelection()\"" not in desktop_selection_bar
    assert 'moveSelectedPresets()' in desktop_selection_bar
    assert 'deleteSelectedPresets()' in desktop_selection_bar
    assert 'deleteSelectedPresets()' in header_template
    assert 'moveSelectedPresets()' in header_template
    assert 'canMovePresetSelection()' in header_template
    assert "x-show=\"selectedIds.length > 0 && currentMode === 'cards'\"" in header_template
    assert 'mergeSelectedPresets()' in header_source
    assert 'canMergePresetSelection()' in header_source
    assert 'getPresetMergeSelectionTitle()' in header_source
    assert 'deleteSelectedPresets()' in header_source
    assert 'canDeletePresetSelection()' in header_source
    assert 'canMovePresetSelection()' in header_source
    assert 'selectedPresetItems()' in header_source


def test_worldinfo_preset_context_menu_delete_copy_is_not_card_specific():
    context_menu_template = read_project_file('templates/components/context_menu.html')
    context_menu_source = read_project_file('static/js/components/contextMenu.js')

    assert 'deleteFolderConfirm.mode' in context_menu_template or 'deleteFolderConfirm.mode' in context_menu_source
    assert 'deleteFolderItemLabel' in context_menu_template
    assert "? '个项目'" in context_menu_source
    assert ": '张卡片'" in context_menu_source


def test_folder_operations_filters_parent_choices_to_capability_allowed_targets():
    folder_operations_source = read_project_file('static/js/components/folderOperations.js')
    folder_modal_template = read_project_file('templates/modals/folder_operations.html')

    assert 'creatableFolderSelectList' in folder_operations_source
    assert 'can_create_child_folder' in folder_operations_source
    assert 'x-for="folder in creatableFolderSelectList"' in folder_modal_template


def test_card_sidebar_mobile_css_pins_collapsed_tag_strip_to_sidebar_bottom():
    layout_css = read_project_file('static/css/modules/layout.css')
    mobile_layout_css = extract_media_block(layout_css, '@media (max-width: 768px)')

    assert '.sidebar-mobile .card-sidebar-shell {' in mobile_layout_css
    assert 'overflow: visible;' in mobile_layout_css
    assert '.sidebar-mobile .card-sidebar-tags {' in mobile_layout_css
    assert 'position: sticky;' in mobile_layout_css
    assert 'bottom: 0;' in mobile_layout_css
    assert '.sidebar-mobile .card-sidebar-tags.is-collapsed {' in mobile_layout_css
    assert 'z-index: 2;' in mobile_layout_css


def test_mobile_sidebar_css_uses_container_height_instead_of_fixed_dynamic_viewport_height():
    layout_css = read_project_file('static/css/modules/layout.css')
    sidebar_mobile_block = extract_exact_css_block(layout_css, '.sidebar-mobile')

    assert 'height: 100%;' in sidebar_mobile_block
    assert 'max-height: 100%;' in sidebar_mobile_block
    assert 'height: 100dvh;' not in sidebar_mobile_block
    assert 'max-height: 100dvh;' not in sidebar_mobile_block


def test_card_pagination_template_uses_mobile_short_labels_and_hides_flip_count():
    cards_template = read_project_file('templates/components/grid_cards.html')
    compact_cards_template = re.sub(r'\s+', ' ', cards_template)

    assert 'class="card-pagination-page-indicator"' in cards_template
    assert 'class="btn-secondary card-page-nav-btn"' in cards_template
    assert "x-show=\"$store.global.deviceType === 'mobile' && !bulkBackMode\"" in compact_cards_template
    assert "x-show=\"$store.global.deviceType === 'mobile' && bulkBackMode\"" in compact_cards_template
    assert '>翻面<' in compact_cards_template or '>����<' in compact_cards_template
    assert '>正面<' in compact_cards_template or '>����<' in compact_cards_template
    assert "x-show=\"$store.global.deviceType !== 'mobile'\" class=\"card-flip-count\"" in compact_cards_template


def test_card_pagination_mobile_css_compacts_footer_into_single_row():
    cards_css = read_project_file('static/css/modules/view-cards.css')
    mobile_cards_css = extract_media_block(cards_css, '@media (max-width: 768px)')

    assert 'flex-direction: row;' in mobile_cards_css
    assert 'justify-content: space-between;' in mobile_cards_css
    assert 'flex-wrap: nowrap;' in mobile_cards_css
    assert '.card-flip-toolbar {' in mobile_cards_css
    assert 'width: auto;' in mobile_cards_css
    assert 'background: transparent;' in mobile_cards_css
    assert 'border: none;' in mobile_cards_css
    assert '.card-pagination-page-cluster {' in mobile_cards_css
    assert 'width: auto;' in mobile_cards_css
    assert '.card-page-nav-btn {' in mobile_cards_css
    assert '.card-pagination-page-indicator {' in mobile_cards_css
