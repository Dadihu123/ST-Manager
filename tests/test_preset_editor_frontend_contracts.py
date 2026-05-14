import json
import re
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_tag_block(source, marker, tag_name='div'):
    marker_index = source.find(marker)
    assert marker_index != -1, f'marker not found: {marker}'

    block_start = source.rfind(f'<{tag_name}', 0, marker_index)
    assert block_start != -1, f'opening {tag_name} not found for marker: {marker}'

    open_token = f'<{tag_name}'
    close_token = f'</{tag_name}>'
    cursor = block_start
    depth = 0

    while cursor < len(source):
        next_open = source.find(open_token, cursor)
        next_close = source.find(close_token, cursor)

        if next_close == -1:
            break

        if next_open != -1 and next_open < next_close:
            depth += 1
            cursor = next_open + len(open_token)
            continue

        depth -= 1
        cursor = next_close + len(close_token)
        if depth == 0:
            return source[block_start:cursor]

    raise AssertionError(f'failed to extract {tag_name} block for marker: {marker}')


def run_preset_editor_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/presetEditor.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function presetEditor()', 'function presetEditor()');

        const stubs = `
        const createAutoSaver = () => ({{ stop() {{}}, initBaseline() {{}}, start() {{}} }});
        globalThis.__apiCreateSnapshot = async () => ({{ success: true }});
        globalThis.__getPresetDetail = async () => ({{ success: true, preset: {{}} }});
        globalThis.__savePreset = async () => ({{ success: true }});
        globalThis.__apiSavePresetExtensions = async () => ({{ success: true }});
        globalThis.__setDefaultPresetVersion = async () => ({{ success: true }});
        const apiCreateSnapshot = (...args) => globalThis.__apiCreateSnapshot(...args);
        const getPresetDetail = (...args) => globalThis.__getPresetDetail(...args);
        const savePreset = (...args) => globalThis.__savePreset(...args);
        const apiSavePresetExtensions = (...args) => globalThis.__apiSavePresetExtensions(...args);
        const setDefaultPresetVersion = (...args) => globalThis.__setDefaultPresetVersion(...args);
        const estimateTokens = () => 0;
        const formatDate = (value) => value;
        const clearActiveRuntimeContext = () => {{}};
        const setActiveRuntimeContext = () => {{}};
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
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default presetEditor;'),
        );
        const editor = module.default();

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


def run_preset_grid_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/presetGrid.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function presetGrid()', 'function presetGrid()');

        const stubs = `
        globalThis.downloadCalls = [];
        const downloadFileFromApi = async (payload) => {{
          globalThis.downloadCalls.push(payload);
        }};
        globalThis.fetchCalls = [];
        globalThis.fetch = async (url, options = {{}}) => {{
          globalThis.fetchCalls.push({{ url, options }});
          return {{
            json: async () => ({{ success: true, msg: 'ok' }}),
          }};
        }};
        globalThis.confirm = () => true;
        globalThis.alert = () => {{}};
        const dispatchedEvents = [];
        globalThis.window = {{
          dispatchedEvents,
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent(event) {{
            dispatchedEvents.push(event);
          }},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(name, options = {{}}) {{
            this.type = name;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default presetGrid;'),
        );
        const grid = module.default();
        grid.$store = {{
          global: {{
            viewState: {{ selectedIds: [], lastSelectedId: '', draggedCards: [] }},
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


def run_preset_api_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/api/presets.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');

        globalThis.fetchCalls = [];
        globalThis.fetch = async (url, options = {{}}) => {{
          fetchCalls.push({{ url, options }});
          return {{
            json: async () => ({{ success: true, url, options }}),
          }};
        }};

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(source),
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


def test_preset_editor_js_exposes_reader_item_workspace_state():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'activeGroup:' in source
    assert 'activeItemId:' in source
    assert 'searchTerm:' in source
    assert 'uiFilter:' in source
    assert 'showMobileSidebar:' in source
    assert 'showRightPanel:' in source
    assert 'get editorView() {' in source
    assert 'get filteredItems() {' in source
    assert 'get activeItem() {' in source
    assert 'getByPath(path) {' in source
    assert 'setByPath(path, value) {' in source


def test_preset_editor_js_exposes_complex_editor_handlers():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'updatePromptItem(index, key, value) {' not in source
    assert 'addPromptItem() {' not in source
    assert 'removePromptItem(index) {' not in source
    assert 'moveListItem(path, fromIndex, toIndex) {' in source
    assert 'addStringListItem(path) {' in source
    assert 'updateStringListItem(path, index, value) {' in source
    assert 'removeStringListItem(path, index) {' in source
    assert 'updateBiasEntry(index, key, value) {' in source
    assert 'openAdvancedExtensions() {' in source
    assert 'deletePreset() {' in source
    assert 'rawUnknownJsonText' not in source
    assert 'applyRawUnknownJson(text) {' not in source
    assert 'removedUnknownFields' not in source
    assert 'previewRestoreDefault() {' not in source


def test_preset_editor_js_exposes_prompt_workspace_state_and_helpers():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'activeWorkspace:' in source
    assert 'activePromptId:' in source
    assert 'activeGenericItemId:' in source
    assert 'get isPromptWorkspaceEditor() {' in source
    assert 'get promptItems() {' in source
    assert 'get orderedPromptItems() {' in source
    assert 'get activePromptItem() {' in source
    assert 'get genericWorkspaceItems() {' in source
    assert 'normalizePromptOrder() {' in source
    assert 'syncPromptOrder(nextOrderedPrompts = null) {' in source
    assert 'selectWorkspace(workspaceId) {' in source
    assert 'selectPrompt(promptId) {' in source
    assert 'getPromptRoleValue(prompt) {' in source
    assert 'getPromptRoleLabel(role) {' in source
    assert 'normalizePromptPosition(value) {' in source
    assert 'isChatInjectionPosition(prompt) {' in source
    assert 'getPromptPositionLabel(prompt) {' in source
    assert 'label: "系统"' in source
    assert 'label: "用户"' in source
    assert 'label: "AI助手"' in source
    assert 'label: "常规"' in source
    assert 'label: "继续"' in source
    assert 'label: "角色扮演"' in source
    assert 'label: "滑动"' in source
    assert 'label: "重新生成"' in source
    assert 'label: "静默"' in source
    assert 'label: "相对"' in source
    assert 'label: "聊天中"' in source


def test_preset_editor_js_exposes_scalar_workspace_helpers():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'get scalarWorkspace() {' in source
    assert 'get hasScalarWorkspace() {' in source
    assert 'get isScalarWorkspaceEditor() {' in source
    assert 'get scalarWorkspaceSections() {' in source
    assert 'getScalarWorkspaceFieldValue(fieldKey) {' in source
    assert 'setScalarWorkspaceFieldValue(fieldKey, value) {' in source
    assert 'getScalarWorkspaceSectionEntries(sectionId) {' in source


def test_preset_editor_js_exposes_filtered_mirrored_field_helpers():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'activeMirroredFieldId:' in source
    assert 'get mirroredWorkspaceFieldItems() {' in source
    assert 'get activeMirroredField() {' in source
    assert 'getFilteredProfileSectionFields(sectionId) {' in source
    assert 'selectMirroredField(fieldId) {' in source
    assert 'syncActiveMirroredField() {' in source
    assert 'getProfileSectionFields(sectionId) {' in source


def test_preset_editor_js_exposes_localized_prompt_option_metadata():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'promptRoleOptions:' in source
    assert 'promptTriggerOptions:' in source
    assert 'promptPositionOptions:' in source
    assert 'value: "system", label: "系统"' in source
    assert 'value: "user", label: "用户"' in source
    assert 'value: "assistant", label: "AI助手"' in source
    assert 'value: "normal", label: "常规"' in source
    assert 'value: "continue", label: "继续"' in source
    assert 'value: "impersonate", label: "角色扮演"' in source
    assert 'value: "swipe", label: "滑动"' in source
    assert 'value: "regenerate", label: "重新生成"' in source
    assert 'value: "quiet", label: "静默"' in source
    assert 'value: 0, label: "相对"' in source
    assert 'value: 1, label: "聊天中"' in source


def test_preset_editor_js_uses_explicit_dirty_state_and_cached_workspace_collections():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'hasUnsavedChanges:' in source
    assert 'promptItemsCache:' in source
    assert 'orderedPromptItemsCache:' in source
    assert 'filteredItemsCache:' in source
    assert 'genericWorkspaceItemsCache:' in source
    assert 'activePromptItemCache:' in source
    assert 'activeItemCache:' in source
    assert 'refreshEditorCollections() {' in source
    assert 'syncActiveEditorSelections() {' in source
    assert 'markDirty(path = null) {' in source
    assert 'markClean() {' in source
    assert 'getPromptMarkerVisual(prompt) {' in source
    assert 'getPromptMarkerIcon(prompt) {' in source
    assert 'return JSON.stringify(this.editingData) !== this.baseDataJson;' not in source


def test_preset_editor_js_exposes_version_actions_and_getters():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'get availableVersions() {' in source
    assert 'get hasMultipleVersions() {' in source
    assert 'openVersion(versionId) {' in source
    assert 'saveAsVersion() {' in source
    assert 'setCurrentVersionAsDefault() {' in source
    assert 'setDefaultPresetVersion' in source


def test_preset_api_runtime_set_default_version_posts_expected_payload():
    run_preset_api_runtime_check(
        """
        await module.setDefaultPresetVersion({ preset_id: 'global::companion-v2.json' });
        const call = globalThis.fetchCalls[0];
        if (!call) {
          throw new Error('expected fetch to be called');
        }
        if (call.url !== '/api/presets/version/set-default') {
          throw new Error(`expected set-default url, got ${call.url}`);
        }
        if (call.options.method !== 'POST') {
          throw new Error(`expected POST method, got ${JSON.stringify(call.options)}`);
        }
        if (call.options.headers?.['Content-Type'] !== 'application/json') {
          throw new Error(`expected json content type, got ${JSON.stringify(call.options.headers)}`);
        }
        const payload = JSON.parse(call.options.body || '{}');
        if (payload.preset_id !== 'global::companion-v2.json') {
          throw new Error(`expected preset_id payload, got ${call.options.body}`);
        }
        """
    )


def test_preset_editor_runtime_open_version_preserves_prompt_workspace_context_through_real_reopen():
    run_preset_editor_runtime_check(
        """
        const requestedPresetIds = [];
        globalThis.window = {
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent() {},
        };
        editor.$store = { global: { deviceType: 'desktop', showToast() {} } };
        editor.$nextTick = (callback) => callback();
        editor.restoreLocalDraft = () => false;
        editor.updatePresetEditorLayoutMetrics = () => {};
        globalThis.__getPresetDetail = async (presetId) => {
          requestedPresetIds.push(presetId);
          return {
            success: true,
            preset: {
              id: presetId,
              name: presetId === 'preset::v2' ? 'Companion V2' : 'Companion V1',
              preset_kind: 'textgen',
              type: 'global',
              path: '/presets/companion.json',
              source_revision: 'rev-' + presetId,
              sections: { sampling: { label: 'Sampling' } },
              reader_view: {
                family: 'prompt_manager',
                family_label: 'Prompt Manager',
                groups: [
                  { id: 'prompts', label: 'Prompts' },
                  { id: 'sampling', label: 'Sampling' },
                ],
                items: [],
                stats: {},
              },
              raw_data: {
                name: presetId === 'preset::v2' ? 'Companion V2' : 'Companion V1',
                prompts: [
                  { identifier: 'prompt-main', content: 'hello' },
                  { identifier: 'prompt-secondary', content: 'world' },
                ],
              },
            },
          };
        };

        await editor.openPresetEditor({ presetId: 'preset::v1' });
        editor.activeNav = 'sampling';
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'prompt-main';
        editor.activeGroup = 'prompts';
        editor.activeItemId = 'item-alpha';
        editor.activeGenericItemId = 'item-alpha';

        await editor.openVersion('preset::v2');

        if (requestedPresetIds.length !== 2) {
          throw new Error(`expected two detail fetches, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (requestedPresetIds[1] !== 'preset::v2') {
          throw new Error(`expected reopen to request target preset, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (editor.editingPresetFile?.id !== 'preset::v2') {
          throw new Error(`expected editor to reopen returned preset, got ${JSON.stringify(editor.editingPresetFile)}`);
        }
        if (editor.activeNav !== 'sampling') {
          throw new Error(`expected activeNav to be preserved, got ${JSON.stringify(editor.activeNav)}`);
        }
        if (editor.activeWorkspace !== 'prompts') {
          throw new Error(`expected prompt workspace to be preserved, got ${JSON.stringify(editor.activeWorkspace)}`);
        }
        if (editor.activePromptId !== 'prompt-main') {
          throw new Error(`expected prompt selection to be preserved, got ${JSON.stringify(editor.activePromptId)}`);
        }
        if (editor.activeGroup !== 'prompts') {
          throw new Error(`expected prompt group to be preserved, got ${JSON.stringify(editor.activeGroup)}`);
        }
        """
    )


def test_preset_editor_runtime_selector_change_reopens_even_if_bound_id_mutated_first():
    run_preset_editor_runtime_check(
        """
        const requestedPresetIds = [];
        globalThis.window = {
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent() {},
        };
        editor.$store = { global: { deviceType: 'desktop', showToast() {} } };
        editor.$nextTick = (callback) => callback();
        editor.restoreLocalDraft = () => false;
        editor.updatePresetEditorLayoutMetrics = () => {};
        globalThis.__getPresetDetail = async (presetId) => {
          requestedPresetIds.push(presetId);
          return {
            success: true,
            preset: {
              id: presetId,
              name: presetId,
              preset_kind: 'textgen',
              type: 'global',
              path: '/presets/companion.json',
              source_revision: 'rev-' + presetId,
              sections: { sampling: { label: 'Sampling' } },
              reader_view: {
                family: 'prompt_manager',
                family_label: 'Prompt Manager',
                groups: [{ id: 'prompts', label: 'Prompts' }],
                items: [],
                stats: {},
              },
              raw_data: {
                name: presetId,
                prompts: [{ identifier: 'prompt-main', content: 'hello' }],
              },
            },
          };
        };

        await editor.openPresetEditor({ presetId: 'preset::v1' });
        editor.activeNav = 'sampling';
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'prompt-main';
        editor.activeGroup = 'prompts';

        editor.editingPresetFile.id = 'preset::v2';
        await editor.openVersion('preset::v2');

        if (requestedPresetIds.length !== 2) {
          throw new Error(`expected selector-driven reopen fetch, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (requestedPresetIds[1] !== 'preset::v2') {
          throw new Error(`expected target preset fetch after selector change, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (editor.editingPresetFile?.id !== 'preset::v2') {
          throw new Error(`expected editor to reopen target version, got ${JSON.stringify(editor.editingPresetFile)}`);
        }
        """
    )


def test_preset_editor_runtime_save_as_version_reopens_returned_preset_with_preserved_context():
    run_preset_editor_runtime_check(
        """
        const prompts = ['Companion Family', 'v3', 'Companion V3'];
        globalThis.prompt = () => prompts.shift() || '';
        globalThis.window = {
          dispatchedEvents: [],
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent(event) {
            this.dispatchedEvents.push(event);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };
        const requestedPresetIds = [];
        editor.$store = { global: { deviceType: 'desktop', showToast() {} } };
        editor.$nextTick = (callback) => callback();
        editor.restoreLocalDraft = () => false;
        editor.updatePresetEditorLayoutMetrics = () => {};
        globalThis.__getPresetDetail = async (presetId) => {
          requestedPresetIds.push(presetId);
          return {
            success: true,
            preset: {
              id: presetId,
              name: presetId === 'preset::v3' ? 'Companion V3' : 'Companion V2',
              preset_kind: 'textgen',
              type: 'global',
              path: '/presets/companion.json',
              source_revision: 'rev-' + presetId,
              family_info: { family_name: 'Companion Family' },
              available_versions: [
                { id: 'preset::v2', version_label: 'v2', name: 'Companion V2' },
                { id: 'preset::v3', version_label: 'v3', name: 'Companion V3' },
              ],
              sections: { sampling: { label: 'Sampling' } },
              reader_view: {
                family: 'prompt_manager',
                family_label: 'Prompt Manager',
                groups: [
                  { id: 'prompts', label: 'Prompts' },
                  { id: 'sampling', label: 'Sampling' },
                ],
                items: [],
                stats: {},
              },
              raw_data: {
                name: presetId === 'preset::v3' ? 'Companion V3' : 'Companion V2',
                x_st_manager: {},
                prompts: [
                  { identifier: 'prompt-main', content: 'hello' },
                  { identifier: 'prompt-secondary', content: 'world' },
                ],
              },
            },
          };
        };

        await editor.openPresetEditor({ presetId: 'preset::v2' });
        editor.activeNav = 'sampling';
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'prompt-main';
        editor.activeGroup = 'prompts';
        editor.activeItemId = 'item-alpha';
        editor.activeGenericItemId = 'item-alpha';
        globalThis.__savePreset = async (payload) => {
          globalThis.__lastSavePayload = payload;
          return { success: true, preset_id: 'preset::v3' };
        };

        await editor.saveAsVersion();

        const saveCall = globalThis.__lastSavePayload;
        if (!saveCall) {
          throw new Error('expected savePreset to be called');
        }
        if (saveCall.create_as_version !== true) {
          throw new Error(`expected create_as_version=true, got ${JSON.stringify(saveCall)}`);
        }
        if (saveCall.version_label !== 'v3') {
          throw new Error(`expected version label payload, got ${JSON.stringify(saveCall)}`);
        }
        if (requestedPresetIds.length !== 2) {
          throw new Error(`expected saveAsVersion to perform real reopen fetch, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (requestedPresetIds[1] !== 'preset::v3') {
          throw new Error(`expected reopen fetch for returned preset, got ${JSON.stringify(requestedPresetIds)}`);
        }
        if (editor.editingPresetFile?.id !== 'preset::v3') {
          throw new Error(`expected reopened preset to be active, got ${JSON.stringify(editor.editingPresetFile)}`);
        }
        if (editor.activeNav !== 'sampling' || editor.activeWorkspace !== 'prompts') {
          throw new Error(`expected preserved reopen navigation context, got ${JSON.stringify({ activeNav: editor.activeNav, activeWorkspace: editor.activeWorkspace })}`);
        }
        if (editor.activePromptId !== 'prompt-main' || editor.activeGroup !== 'prompts') {
          throw new Error(`expected preserved prompt selection context, got ${JSON.stringify({ activePromptId: editor.activePromptId, activeGroup: editor.activeGroup })}`);
        }
        const refreshEvent = globalThis.window.dispatchedEvents[0];
        if (!refreshEvent || refreshEvent.type !== 'refresh-preset-list') {
          throw new Error(`expected refresh-preset-list event, got ${JSON.stringify(refreshEvent)}`);
        }
        """
    )


def test_preset_editor_runtime_set_default_version_refreshes_and_reopens_with_preserved_context():
    run_preset_editor_runtime_check(
        """
        const calls = [];
        globalThis.window = {
          dispatchedEvents: [],
          addEventListener() {},
          removeEventListener() {},
          dispatchEvent(event) {
            this.dispatchedEvents.push(event);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(name, options = {}) {
            this.type = name;
            this.detail = options.detail;
          }
        };
        editor.$store = { global: { showToast() {} } };
        editor.editingPresetFile = {
          id: 'preset::v2',
          preset_kind: 'textgen',
        };
        editor.activeNav = 'sampling';
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'prompt-main';
        editor.activeGroup = 'prompts';
        editor.activeItemId = 'item-alpha';
        editor.activeGenericItemId = 'item-alpha';
        editor.openPresetEditor = async (payload) => {
          calls.push({ reopen: payload });
        };
        globalThis.__setDefaultPresetVersion = async (payload) => {
          calls.push({ api: payload });
          return { success: true, preset_id: 'preset::v2' };
        };

        await editor.setCurrentVersionAsDefault();

        const apiCall = calls.find((entry) => entry.api)?.api;
        const reopenCall = calls.find((entry) => entry.reopen)?.reopen;
        if (!apiCall || apiCall.preset_id !== 'preset::v2') {
          throw new Error(`expected setDefaultPresetVersion call, got ${JSON.stringify(calls)}`);
        }
        const refreshEvent = globalThis.window.dispatchedEvents[0];
        if (!refreshEvent || refreshEvent.type !== 'refresh-preset-list') {
          throw new Error(`expected refresh-preset-list event, got ${JSON.stringify(refreshEvent)}`);
        }
        if (!reopenCall) {
          throw new Error('expected setCurrentVersionAsDefault to reopen preset context');
        }
        if (reopenCall.presetId !== 'preset::v2') {
          throw new Error(`expected reopen preset id, got ${JSON.stringify(reopenCall)}`);
        }
        if (reopenCall.activeNav !== 'sampling' || !reopenCall.preserveContext) {
          throw new Error(`expected reopen to preserve navigation context, got ${JSON.stringify(reopenCall)}`);
        }
        if (reopenCall.context?.activeWorkspace !== 'prompts' || reopenCall.context?.activePromptId !== 'prompt-main') {
          throw new Error(`expected preserved prompt context, got ${JSON.stringify(reopenCall)}`);
        }
        """
    )


def test_preset_editor_js_uses_shared_prompt_marker_visual_source():
    editor_source = read_project_file('static/js/components/presetEditor.js')
    reader_source = read_project_file('static/js/components/presetDetailReader.js')
    util_source = read_project_file('static/js/utils/promptMarkerVisuals.js')

    assert 'from "../utils/promptMarkerVisuals.js"' in editor_source
    assert 'from "../utils/promptMarkerVisuals.js"' in reader_source
    assert 'const PROMPT_MARKER_VISUALS = {' not in editor_source
    assert 'const PROMPT_MARKER_VISUALS = {' not in reader_source
    assert 'export const PROMPT_MARKER_VISUALS = {' in util_source
    assert 'export function getPromptMarkerVisual' in util_source
    assert 'export function buildPromptMarkerIcon' in util_source
    assert 'return buildPromptMarkerIcon(visual);' in editor_source
    assert 'return buildPromptMarkerIcon(visual);' in reader_source
    assert 'buildPromptMarkerIcon(visual, {' not in editor_source


def test_prompt_marker_visual_util_runtime_exports_shared_visuals_and_icon_builder():
    source_path = (PROJECT_ROOT / 'static/js/utils/promptMarkerVisuals.js').resolve()
    node_script = textwrap.dedent(
        f"""
        const module = await import({json.dumps(source_path.as_uri())});

        const scenario = module.getPromptMarkerVisual('scenario');
        if (scenario.key !== 'scenario') {{
          throw new Error(`expected scenario visual, got ${{JSON.stringify(scenario)}}`);
        }}

        const fallback = module.getPromptMarkerVisual('missing');
        if (fallback.key !== 'marker') {{
          throw new Error(`expected fallback visual, got ${{JSON.stringify(fallback)}}`);
        }}

        const svg = module.buildPromptMarkerIcon(scenario);
        if (!svg.includes('<svg') || !svg.includes('aria-hidden="true"') || !svg.includes('stroke-width="1.5"')) {{
          throw new Error(`expected shared icon builder output, got ${{svg}}`);
        }}
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


def test_preset_editor_template_removes_prompt_and_unknown_raw_editor_sections():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    js_source = read_project_file('static/js/components/presetEditor.js')

    assert not re.search(r'<button\s+@click="openRawEditor\(\)"[\s\S]*?>[\s\S]*?查看原始 JSON[\s\S]*?</button>', source)
    assert not re.search(r'<button\s+@click="previewRestoreDefault\(\)"[\s\S]*?>[\s\S]*?恢复默认[\s\S]*?</button>', source)
    assert 'openRawEditor() {' not in js_source
    assert "activeItem?.editor?.kind === 'prompt-item'" not in source
    assert '未知字段检查器' not in source
    assert '高级原始编辑区' not in source
    assert '@click="applyRawUnknownJson(rawUnknownDraft)"' not in source
    assert 'rawUnknownJsonText' not in js_source
    assert 'applyRawUnknownJson(text) {' not in js_source


def test_preset_editor_template_renders_fullscreen_version_selector_and_actions():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-show="hasMultipleVersions"' in source
    assert 'x-model="editingPresetFile.id"' not in source
    assert ':value="editingPresetFile?.id || \'\'"' in source
    assert '@change="openVersion($event.target.value)"' in source
    assert 'x-for="version in availableVersions"' in source
    assert '@click="saveAsVersion()"' in source
    assert '@click="setCurrentVersionAsDefault()"' in source
    assert '设为默认版本' in source
    assert '另存为版本' in source


def test_grid_presets_template_leaves_manager_wallpaper_visible_at_root_surface():
    source = read_project_file('templates/components/grid_presets.html')

    assert 'x-data="presetGrid"' in source
    assert 'class="flex-1 flex flex-col overflow-hidden w-full relative h-full bg-[var(--bg-body)]"' not in source
    assert 'class="flex-1 flex flex-col overflow-hidden w-full relative h-full"' in source


def test_grid_presets_template_uses_owner_link_without_extra_locate_button():
    source = read_project_file('templates/components/grid_presets.html')

    assert '定位所属角色卡' not in source
    assert '@click.stop="locatePresetOwnerCard(item)"' in source
    assert ':title="`所属角色卡：${getPresetOwnerName(item)}`"' in source


def test_preset_grid_runtime_prefers_family_default_version_id_for_reader_open():
    run_preset_grid_runtime_check(
        """
        const familyItem = {
          id: 'family::alpha',
          entry_type: 'family',
          default_version_id: 'preset::v2',
          default_version_label: 'v2',
        };

        if (grid.getPresetOpenId(familyItem) !== 'preset::v2') {
          throw new Error(`expected family open id to prefer default version, got ${JSON.stringify(grid.getPresetOpenId(familyItem))}`);
        }

        grid.openPresetDetail(familyItem);
        const dispatched = globalThis.window.dispatchedEvents[0];
        if (!dispatched || dispatched.type !== 'open-preset-reader') {
          throw new Error(`expected open-preset-reader event, got ${JSON.stringify(dispatched)}`);
        }
        if (dispatched.detail.id !== 'preset::v2') {
          throw new Error(`expected reader open detail to use default version id, got ${JSON.stringify(dispatched.detail)}`);
        }
        if (dispatched.detail.entry_type !== 'family') {
          throw new Error(`expected family metadata to remain available, got ${JSON.stringify(dispatched.detail)}`);
        }
        """
    )


def test_preset_grid_runtime_resolves_family_action_targets_to_concrete_preset_ids():
    run_preset_grid_runtime_check(
        """
        const familyItem = {
          id: 'family::alpha',
          entry_type: 'family',
          default_version_id: 'preset::v2',
          source_type: 'global',
          type: 'global',
          path: '/presets/companion.json',
          name: 'Companion',
          filename: 'companion.json',
        };

        if (grid.getPresetActionTargetId(familyItem) !== 'preset::v2') {
          throw new Error(`expected family action target id to prefer concrete version, got ${JSON.stringify(grid.getPresetActionTargetId(familyItem))}`);
        }

        await grid.exportPresetItem(familyItem);
        const exportCall = globalThis.downloadCalls[0];
        if (!exportCall) {
          throw new Error('expected export to invoke download helper');
        }
        if (exportCall.body?.id !== 'preset::v2') {
          throw new Error(`expected export to use concrete preset id, got ${JSON.stringify(exportCall)}`);
        }

        await grid.deletePreset(familyItem, { stopPropagation() {} });
        const deleteCall = globalThis.fetchCalls[0];
        if (!deleteCall || deleteCall.url !== '/api/presets/delete') {
          throw new Error(`expected delete api call, got ${JSON.stringify(deleteCall)}`);
        }
        const deletePayload = JSON.parse(deleteCall.options.body || '{}');
        if (deletePayload.id !== 'preset::v2') {
          throw new Error(`expected delete to use concrete preset id, got ${JSON.stringify(deletePayload)}`);
        }
        """
    )


def test_preset_grid_runtime_bulk_actions_resolve_family_targets_to_concrete_ids():
    run_preset_grid_runtime_check(
        """
        const familyItem = {
          id: 'family::alpha',
          entry_type: 'family',
          default_version_id: 'preset::v2',
          source_type: 'global',
          type: 'global',
          path: '/presets/companion.json',
          name: 'Companion',
        };
        const regularItem = {
          id: 'preset::solo',
          entry_type: 'preset',
          source_type: 'global',
          type: 'global',
          path: '/presets/solo.json',
          name: 'Solo',
        };

        grid.items = [familyItem, regularItem];
        grid.selectedIds = ['family::alpha', 'preset::solo'];

        await grid.deleteSelectedPresets();
        const deletePayloads = globalThis.fetchCalls
          .filter((call) => call.url === '/api/presets/delete')
          .map((call) => JSON.parse(call.options.body || '{}'));
        if (deletePayloads.length !== 2) {
          throw new Error(`expected two delete calls, got ${JSON.stringify(globalThis.fetchCalls)}`);
        }
        if (deletePayloads[0].id !== 'preset::v2' || deletePayloads[1].id !== 'preset::solo') {
          throw new Error(`expected bulk delete to use concrete ids, got ${JSON.stringify(deletePayloads)}`);
        }

        globalThis.fetchCalls.length = 0;
        grid.selectedIds = ['family::alpha', 'preset::solo'];
        await grid.moveSelectedPresets('archive');
        const movePayloads = globalThis.fetchCalls
          .filter((call) => call.url === '/api/presets/category/move')
          .map((call) => JSON.parse(call.options.body || '{}'));
        if (movePayloads.length !== 2) {
          throw new Error(`expected two move calls, got ${JSON.stringify(globalThis.fetchCalls)}`);
        }
        if (movePayloads[0].id !== 'preset::v2' || movePayloads[1].id !== 'preset::solo') {
          throw new Error(`expected bulk move to use concrete ids, got ${JSON.stringify(movePayloads)}`);
        }
        if (movePayloads[0].target_category !== 'archive') {
          throw new Error(`expected move payload to preserve target category, got ${JSON.stringify(movePayloads[0])}`);
        }
        """
    )


def test_grid_presets_template_renders_family_badges_only_for_family_entries():
    source = read_project_file('templates/components/grid_presets.html')

    assert "x-if=\"item.entry_type === 'family'\"" in source
    assert 'item.version_count' in source
    assert 'item.default_version_label' in source


def test_preset_editor_template_uses_user_facing_copy_for_prompt_and_mirrored_workspaces():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '提示词列表' in source
    assert '当前筛选下没有可用字段' in source
    assert '提示词管理' not in source
    assert 'Reader Workspace' not in source
    assert 'SillyTavern 提示词管理' not in source
    assert '当前分区使用 profile schema 直接驱动 ST 镜像控件。' not in source


def test_preset_editor_template_localizes_remaining_prompt_workspace_copy():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '当前提示词' in source
    assert '提示词内容' in source
    assert '提示词基础信息' in source
    assert '当前预设没有可编辑的提示词条目。' in source
    assert '切换提示词启用状态' in source
    assert '标识符' in source
    assert '聊天内深度' in source

    assert '当前 Prompt' not in source
    assert 'Prompt 内容' not in source
    assert 'Prompt 基础信息' not in source
    assert '当前预设没有可编辑的 Prompt 条目。' not in source
    assert '切换 Prompt 启用状态' not in source
    assert 'In-Chat 深度' not in source


def test_preset_editor_template_localizes_prompt_manager_guidance_copy():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '按常用提示词编辑方式调整' in source
    assert '名称、角色、注入位置与触发器' in source
    assert '按提示词管理的常用方式编辑' not in source
    assert 'SillyTavern 提示词管理的使用习惯编辑。' not in source


def test_preset_editor_template_collapses_prompt_triggers_by_default():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '按需展开设置触发场景。' in source
    assert '勾选后仅在对应场景触发此提示词。' in source
    assert re.search(r'<button\b[\s\S]*?>[\s\S]*?触发器[\s\S]*?按需展开设置触发场景。[\s\S]*?</button>', source)
    assert re.search(r'<button\b[\s\S]*?>[\s\S]*?触发器[\s\S]*?</button>[\s\S]*?勾选后仅在对应场景触发此提示词。', source)


def test_preset_editor_template_localizes_remaining_parameter_copy():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '当前分组参数会直接写回对应参数项。' in source
    assert '添加偏置' in source

    assert '当前分组参数会直接写回对应 storage key。' not in source
    assert '添加 Bias' not in source


def test_preset_editor_runtime_rejects_invalid_bias_numbers():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          logit_bias: [{ text: 'blocked', value: -10 }],
        };

        editor.updateBiasEntry(0, 'value', '2.5');
        if (editor.editingData.logit_bias[0].value !== 2.5) {
          throw new Error(`expected numeric bias update, got ${JSON.stringify(editor.editingData.logit_bias[0])}`);
        }

        editor.updateBiasEntry(0, 'value', 'not-a-number');
        if (editor.editingData.logit_bias[0].value !== 0) {
          throw new Error(`expected invalid bias value to fall back to 0, got ${JSON.stringify(editor.editingData.logit_bias[0])}`);
        }
        """
    )


def test_preset_editor_runtime_exposes_localized_prompt_option_helpers_and_filters_unknown_triggers():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', role: 'unknown', injection_position: 1 },
          ],
        };
        editor.activePromptId = 'main';

        const roleLabels = editor.promptRoleOptions.map((option) => option.label);
        if (JSON.stringify(roleLabels) !== JSON.stringify(['系统', '用户', 'AI助手'])) {
          throw new Error(`expected localized role labels, got ${JSON.stringify(roleLabels)}`);
        }

        const triggerLabels = editor.promptTriggerOptions.map((option) => option.label);
        if (JSON.stringify(triggerLabels) !== JSON.stringify(['常规', '继续', '角色扮演', '滑动', '重新生成', '静默'])) {
          throw new Error(`expected localized trigger labels, got ${JSON.stringify(triggerLabels)}`);
        }

        const roleValue = editor.getPromptRoleValue(editor.activePromptItem);
        if (roleValue !== 'system') {
          throw new Error(`expected unknown role to fall back to system, got ${JSON.stringify(roleValue)}`);
        }

        const positionLabel = editor.getPromptPositionLabel({ injection_position: 1, injection_depth: undefined });
        if (positionLabel !== '聊天中 @ 4') {
          throw new Error(`expected default chat position depth label, got ${JSON.stringify(positionLabel)}`);
        }

        editor.updatePromptTriggers(['swipe', 'unknown', 'quiet']);
        if (JSON.stringify(editor.editingData.prompts[0].injection_trigger) !== JSON.stringify(['swipe', 'quiet'])) {
          throw new Error(`expected unknown trigger values to be ignored, got ${JSON.stringify(editor.editingData.prompts[0].injection_trigger)}`);
        }
        """
    )


def test_preset_editor_runtime_normalizes_injection_depth_to_reader_safe_values():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', role: 'system', injection_position: 1, injection_depth: 4 },
          ],
        };
        editor.activePromptId = 'main';

        editor.updatePromptField('injection_depth', '-1');
        if (editor.editingData.prompts[0].injection_depth !== 4) {
          throw new Error(`expected negative depth to fall back to 4, got ${JSON.stringify(editor.editingData.prompts[0])}`);
        }

        editor.updatePromptField('injection_depth', '2.5');
        if (editor.editingData.prompts[0].injection_depth !== 4) {
          throw new Error(`expected fractional depth to fall back to 4, got ${JSON.stringify(editor.editingData.prompts[0])}`);
        }

        editor.updatePromptField('injection_depth', '0');
        if (editor.editingData.prompts[0].injection_depth !== 0) {
          throw new Error(`expected zero depth to stay valid, got ${JSON.stringify(editor.editingData.prompts[0])}`);
        }

        const positionLabel = editor.getPromptPositionLabel(editor.activePromptItem);
        if (positionLabel !== '聊天中 @ 0') {
          throw new Error(`expected normalized editor position label, got ${JSON.stringify(positionLabel)}`);
        }
        """
    )


def test_preset_editor_runtime_tracks_dirty_state_and_refreshes_cached_prompt_collections():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          id: 'preset-1',
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'scalar_fields', label: 'Fields' },
            ],
            items: [
              {
                id: 'field:temperature',
                group: 'scalar_fields',
                title: 'Temperature',
                summary: 'temp',
                source_key: 'temperature',
                editor: { kind: 'number' },
              },
            ],
          },
        };
        editor.editingData = {
          temperature: 0.7,
          prompts: [
            { identifier: 'main', name: 'Main Prompt', role: 'system', content: 'hello world' },
            { identifier: 'scenario', name: 'Scenario', role: 'system', marker: true },
          ],
          prompt_order: ['main', 'scenario'],
        };
        editor.activeWorkspace = 'prompts';
        editor.activeGroup = 'all';
        editor.activePromptId = 'main';
        editor.markClean();
        editor.refreshEditorCollections();

        if (editor.isDirty) {
          throw new Error('expected clean editor after markClean');
        }
        if (JSON.stringify(editor.orderedPromptItems.map((item) => item.__identifier)) !== JSON.stringify(['main', 'scenario'])) {
          throw new Error(`expected cached prompt order, got ${JSON.stringify(editor.orderedPromptItems.map((item) => item.__identifier))}`);
        }

        editor.updatePromptField('name', 'Renamed Prompt');
        if (!editor.isDirty) {
          throw new Error('expected prompt rename to mark editor dirty');
        }
        if (editor.activePromptItem?.name !== 'Renamed Prompt') {
          throw new Error(`expected active prompt cache to refresh after rename, got ${JSON.stringify(editor.activePromptItem)}`);
        }
        if (!editor.getPromptMarkerIcon(editor.orderedPromptItems[1]).includes('<svg')) {
          throw new Error('expected editor marker icon helper to output svg');
        }

        editor.markClean();
        editor.activeWorkspace = 'scalar_fields';
        editor.activeGroup = 'all';
        editor.searchTerm = 'temp';
        editor.refreshEditorCollections();
        if (editor.filteredItems.length !== 1 || editor.activeItem?.id !== 'field:temperature') {
          throw new Error(`expected cached generic filter results, got ${JSON.stringify({ filtered: editor.filteredItems.map((item) => item.id), active: editor.activeItem?.id })}`);
        }

        editor.setByPath('temperature', 1.1);
        if (!editor.isDirty) {
          throw new Error('expected setByPath to mark editor dirty');
        }
        """
    )


def test_preset_editor_runtime_clamps_mirrored_slider_values():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [{ id: 'core_sampling', label: '核心采样' }],
            fields: {
              top_p: {
                canonical_key: 'top_p',
                storage_key: 'top_p',
                section: 'core_sampling',
                control: 'range_with_number',
                min: 0,
                max: 1,
                step: 0.01,
              },
              stream_openai: {
                canonical_key: 'stream_openai',
                storage_key: 'stream_openai',
                section: 'core_sampling',
                control: 'checkbox',
              },
              reasoning_effort: {
                canonical_key: 'reasoning_effort',
                storage_key: 'reasoning_effort',
                section: 'core_sampling',
                control: 'select',
                default: 'auto',
                options: ['auto', 'low', 'medium', 'high', 'min', 'max'],
              },
            },
          },
          reader_view: { family: 'prompt_manager', groups: [], items: [], stats: {} },
        };
        editor.editingData = {
          top_p: 0.8,
          stream_openai: false,
          reasoning_effort: 'medium',
          prompts: [{ identifier: 'main', content: 'hello' }],
        };

        editor.setProfileFieldValue('top_p', 9);
        if (editor.editingData.top_p !== 1) {
          throw new Error(`expected top_p clamp to 1, got ${editor.editingData.top_p}`);
        }

        editor.setProfileFieldValue('stream_openai', true);
        if (editor.editingData.stream_openai !== true) {
          throw new Error('expected checkbox value to be written');
        }

        editor.setProfileFieldValue('reasoning_effort', 'invalid');
        if (editor.editingData.reasoning_effort !== 'medium') {
          throw new Error(`expected invalid enum to preserve current valid value, got ${editor.editingData.reasoning_effort}`);
        }
        """
    )


def test_preset_editor_runtime_preserves_numeric_mirrored_select_option_types():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          editor_profile: {
            id: 'st_textgen_preset',
            family: 'st_mirror',
            sections: [{ id: 'advanced_sampling', label: '高级采样' }],
            fields: {
              mirostat_mode: {
                id: 'mirostat_mode',
                storage_key: 'mirostat_mode',
                section: 'advanced_sampling',
                control: 'select',
                default: 0,
                options: [0, 1, 2],
              },
            },
          },
          reader_view: { family: 'prompt_manager', groups: [], items: [], stats: {} },
        };
        editor.editingData = {
          mirostat_mode: 0,
          prompts: [{ identifier: 'main', content: 'hello' }],
        };

        editor.setProfileFieldValue('mirostat_mode', '2');

        if (editor.editingData.mirostat_mode !== 2) {
          throw new Error(`expected numeric mirrored select option to persist as number 2, got ${JSON.stringify(editor.editingData.mirostat_mode)}`);
        }
        if (typeof editor.editingData.mirostat_mode !== 'number') {
          throw new Error(`expected numeric mirrored select option type to stay numeric, got ${typeof editor.editingData.mirostat_mode}`);
        }
        """
    )


def test_preset_editor_runtime_tracks_active_mirrored_section_workspace_and_counts():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'output_and_reasoning', label: '输出与推理' },
              { id: 'prompt_manager', label: '提示词管理' },
            ],
            fields: {
              openai_max_context: {
                id: 'openai_max_context',
                storage_key: 'openai_max_context',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 512,
                max: 8192,
                step: 1,
              },
              openai_max_tokens: {
                id: 'openai_max_tokens',
                storage_key: 'openai_max_tokens',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 1,
                max: 4096,
                step: 1,
              },
              prompts: {
                id: 'prompts',
                storage_key: 'prompts',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
              prompt_order: {
                id: 'prompt_order',
                storage_key: 'prompt_order',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
            },
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'prompts', label: 'Prompt 条目' }],
            items: [],
            stats: {},
          },
        };
        editor.editingData = {
          openai_max_context: 4096,
          openai_max_tokens: 1200,
          prompts: [{ identifier: 'main', content: 'hello' }],
          prompt_order: ['main'],
        };
        editor.activeWorkspace = 'prompts';

        if (editor.activeMirroredSection?.id !== 'prompt_manager') {
          throw new Error(`expected prompt workspace to map to prompt_manager section, got ${editor.activeMirroredSection?.id}`);
        }
        if (editor.getMirroredSectionFieldCount('output_and_reasoning') !== 2) {
          throw new Error(`expected mirrored section count to include both output fields, got ${editor.getMirroredSectionFieldCount('output_and_reasoning')}`);
        }

        editor.selectWorkspace('output_and_reasoning');

        if (editor.activeWorkspace !== 'output_and_reasoning') {
          throw new Error(`expected mirrored section workspace to be selectable, got ${editor.activeWorkspace}`);
        }
        if (editor.activeMirroredSection?.id !== 'output_and_reasoning') {
          throw new Error(`expected active mirrored section to follow workspace, got ${editor.activeMirroredSection?.id}`);
        }
        """
    )


def test_preset_editor_runtime_filters_and_selects_mirrored_fields_by_workspace_state():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'prompt_manager', label: '提示词管理' },
              { id: 'output_and_reasoning', label: '输出与推理' },
            ],
            fields: {
              openai_max_context: {
                id: 'openai_max_context',
                label: '上下文长度',
                storage_key: 'openai_max_context',
                section: 'output_and_reasoning',
                control: 'range_with_number',
                min: 512,
                max: 8192,
                step: 1,
              },
              openai_reasoning_notes: {
                id: 'openai_reasoning_notes',
                label: '推理说明',
                storage_key: 'openai_reasoning_notes',
                section: 'output_and_reasoning',
                control: 'textarea',
              },
              prompts: {
                id: 'prompts',
                label: '提示词列表',
                storage_key: 'prompts',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
            },
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'prompts', label: 'Prompt 条目' }],
            items: [],
            stats: {},
          },
        };
        editor.editingData = {
          openai_max_context: 4096,
          openai_reasoning_notes: 'long reasoning text',
          prompts: [{ identifier: 'main', content: 'hello' }],
          prompt_order: ['main'],
        };
        editor.activeWorkspace = 'output_and_reasoning';
        editor.refreshEditorCollections();

        if (JSON.stringify(editor.mirroredWorkspaceFieldItems.map((field) => field.id)) !== JSON.stringify(['openai_max_context', 'openai_reasoning_notes'])) {
          throw new Error(`expected mirrored workspace fields, got ${JSON.stringify(editor.mirroredWorkspaceFieldItems.map((field) => field.id))}`);
        }
        if (editor.activeMirroredField?.id !== 'openai_max_context') {
          throw new Error(`expected first mirrored field active by default, got ${editor.activeMirroredField?.id}`);
        }

        editor.selectMirroredField('openai_reasoning_notes');
        if (editor.activeMirroredField?.id !== 'openai_reasoning_notes') {
          throw new Error(`expected explicit mirrored field selection, got ${editor.activeMirroredField?.id}`);
        }

        editor.uiFilter = 'longtext';
        editor.refreshEditorCollections();
        if (JSON.stringify(editor.mirroredWorkspaceFieldItems.map((field) => field.id)) !== JSON.stringify(['openai_reasoning_notes'])) {
          throw new Error(`expected longtext filter to keep textarea field only, got ${JSON.stringify(editor.mirroredWorkspaceFieldItems.map((field) => field.id))}`);
        }
        if (editor.activeMirroredField?.id !== 'openai_reasoning_notes') {
          throw new Error(`expected filtered selection to stay on surviving field, got ${editor.activeMirroredField?.id}`);
        }

        editor.searchTerm = 'missing';
        editor.refreshEditorCollections();
        if (editor.mirroredWorkspaceFieldItems.length !== 0) {
          throw new Error(`expected search to clear mirrored field list, got ${editor.mirroredWorkspaceFieldItems.length}`);
        }
        if (editor.activeMirroredField !== null) {
          throw new Error(`expected no active mirrored field after empty result, got ${editor.activeMirroredField?.id}`);
        }
        """
    )


def test_preset_editor_runtime_resets_prompt_trigger_collapse_state():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          id: 'preset-1',
          preset_kind: 'textgen',
          raw_data: {},
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [{ id: 'prompt_manager', label: '提示词管理' }],
            fields: {
              prompts: {
                id: 'prompts',
                storage_key: 'prompts',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
            },
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'prompts', label: 'Prompt 条目' }],
            items: [],
            stats: {},
          },
        };
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main', content: 'hello' },
            { identifier: 'summary', name: 'Summary', content: 'world' },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activeWorkspace = 'prompts';
        editor.refreshEditorCollections();

        if (editor.showPromptTriggers !== false) {
          throw new Error(`expected prompt triggers collapsed by default, got ${editor.showPromptTriggers}`);
        }

        editor.showPromptTriggers = true;
        editor.selectPrompt('summary');

        if (editor.showPromptTriggers !== false) {
          throw new Error(`expected prompt selection to re-collapse triggers, got ${editor.showPromptTriggers}`);
        }

        editor.showPromptTriggers = true;
        editor.closeEditor();

        if (editor.showPromptTriggers !== false) {
          throw new Error(`expected closeEditor to reset trigger collapse state, got ${editor.showPromptTriggers}`);
        }
        """
    )


def test_preset_editor_runtime_degrades_safely_when_editor_profile_is_missing():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          reader_view: {
            family: 'generic',
            groups: [
              { id: 'basic', label: '基础信息' },
            ],
            items: [
              {
                id: 'field:name',
                group: 'basic',
                title: '名称',
                summary: 'preset name',
                editable: true,
                value_path: 'name',
                editor: { kind: 'text' },
              },
            ],
            stats: {},
          },
        };
        editor.editingData = { name: 'Test Preset' };
        editor.activeWorkspace = 'all';
        editor.refreshEditorCollections();

        if (editor.editorProfile) {
          throw new Error(`expected missing editor profile to stay absent, got ${JSON.stringify(editor.editorProfile)}`);
        }
        if (editor.activeMirroredSection?.id) {
          throw new Error(`expected no mirrored section, got ${editor.activeMirroredSection?.id}`);
        }
        if (editor.activeMirroredField?.id) {
          throw new Error(`expected no mirrored field, got ${editor.activeMirroredField?.id}`);
        }
        if (editor.filteredItems[0]?.id !== 'field:name') {
          throw new Error(`expected generic item flow to remain available, got ${editor.filteredItems[0]?.id}`);
        }
        """
    )


def test_preset_editor_runtime_mirrored_profile_editor_is_hidden_for_prompt_workspace():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [{ id: 'core_sampling', label: '核心采样' }],
            fields: {},
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'prompts', label: 'Prompts' }],
            items: [],
            stats: {},
          },
        };
        editor.activeWorkspace = 'prompts';

        if (!editor.isMirroredProfileEditor) {
          throw new Error('expected mirrored profile editor to be recognized');
        }
        if (!editor.isPromptWorkspaceEditor) {
          throw new Error('expected prompt workspace editor to be recognized');
        }
        if (editor.activeWorkspace !== 'prompts') {
          throw new Error(`expected activeWorkspace to stay prompts, got ${editor.activeWorkspace}`);
        }
        """
    )


def test_preset_editor_runtime_uses_scalar_workspace_storage_key_helpers_with_canonical_metadata():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'scalar_fields', label: '基础字段' },
            ],
            items: [],
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
              hidden_fields: ['top_a'],
              aliases: { temp: 'temperature', rep_pen: 'repetition_penalty' },
            },
          },
        };
        editor.editingData = {
          temp: 0.7,
          rep_pen: 1.1,
          top_a: 0.3,
          prompts: [{ identifier: 'main', content: 'hello' }],
        };
        editor.activeWorkspace = 'scalar_fields';
        editor.refreshEditorCollections();

        if (!editor.isScalarWorkspaceEditor) {
          throw new Error('expected scalar workspace editor mode to activate');
        }
        if (editor.scalarWorkspace?.field_map?.temp?.canonical_key !== 'temperature') {
          throw new Error(`expected temp canonical metadata, got ${JSON.stringify(editor.scalarWorkspace?.field_map?.temp)}`);
        }
        if (editor.scalarWorkspace?.field_map?.rep_pen?.canonical_key !== 'repetition_penalty') {
          throw new Error(`expected rep_pen canonical metadata, got ${JSON.stringify(editor.scalarWorkspace?.field_map?.rep_pen)}`);
        }
        if (editor.getScalarWorkspaceFieldValue('temp') !== 0.7) {
          throw new Error(`expected scalar workspace storage-key read, got ${JSON.stringify(editor.getScalarWorkspaceFieldValue('temp'))}`);
        }

        editor.setScalarWorkspaceFieldValue('rep_pen', 1.35);
        if (editor.editingData.rep_pen !== 1.35) {
          throw new Error(`expected scalar workspace write to hit storage key, got ${JSON.stringify(editor.editingData)}`);
        }
        if (editor.editingData.top_a !== 0.3) {
          throw new Error(`expected hidden field to remain untouched, got ${JSON.stringify(editor.editingData)}`);
        }
        if (!editor.isDirty) {
          throw new Error('expected scalar workspace field write to mark editor dirty');
        }
        """
    )


def test_preset_editor_runtime_scalar_workspace_section_entries_exclude_hidden_fields():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'scalar_fields', label: '基础字段' }],
            items: [],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
                top_a: { canonical_key: 'top_a', section: 'core_sampling', label: 'Top A', storage_key: 'top_a', editor: 'number' },
              },
              hidden_fields: ['top_a'],
              aliases: { temp: 'temperature', top_a: 'top_a' },
            },
          },
        };
        editor.editingData = { temp: 0.7, top_a: 0.3 };
        editor.activeWorkspace = 'scalar_fields';
        editor.refreshEditorCollections();

        const entries = editor.getScalarWorkspaceSectionEntries('core_sampling').map((entry) => entry.fieldKey);
        if (JSON.stringify(entries) !== JSON.stringify(['temp'])) {
          throw new Error(`expected hidden scalar field to be excluded from section entries, got ${JSON.stringify(entries)}`);
        }
        """
    )


def test_preset_editor_runtime_scalar_workspace_excludes_generic_scalar_items_from_collections():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          preset_kind: 'textgen',
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'scalar_fields', label: '基础字段' }],
            items: [
              {
                id: 'field:temp',
                type: 'field',
                group: 'scalar_fields',
                title: '温度',
                source_key: 'temp',
                value_path: 'temp',
                editable: true,
                editor: { kind: 'number' },
              },
            ],
            scalar_workspace: {
              profile_id: 'legacy_scalar_workspace',
              sections: [
                { id: 'core_sampling', label: '核心采样参数' },
              ],
              field_map: {
                temp: { canonical_key: 'temperature', section: 'core_sampling', label: '温度', storage_key: 'temp', editor: 'number' },
              },
              hidden_fields: [],
              aliases: { temp: 'temperature' },
            },
          },
        };
        editor.editingData = { temp: 0.7, prompts: [{ identifier: 'main', content: 'hello' }] };
        editor.activeWorkspace = 'scalar_fields';
        editor.activeGroup = 'scalar_fields';
        editor.refreshEditorCollections();

        if (editor.filteredItems.length !== 0) {
          throw new Error(`expected specialized scalar workspace to exclude generic scalar items from filteredItems, got ${JSON.stringify(editor.filteredItems.map((item) => item.id))}`);
        }
        if (editor.genericWorkspaceItems.length !== 0) {
          throw new Error(`expected specialized scalar workspace to exclude generic workspace items, got ${JSON.stringify(editor.genericWorkspaceItems.map((item) => item.id))}`);
        }
        if (editor.activeItem !== null) {
          throw new Error(`expected no generic active item in scalar workspace mode, got ${editor.activeItem?.id}`);
        }
        """
    )


def test_preset_editor_runtime_prompt_content_edit_only_updates_dirty_state_and_active_prompt_cache():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          id: 'preset-1',
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompts' },
              { id: 'scalar_fields', label: 'Fields' },
            ],
            items: [
              {
                id: 'field:temperature',
                group: 'scalar_fields',
                title: 'Temperature',
                summary: 'temp',
                source_key: 'temperature',
                editor: { kind: 'number' },
              },
            ],
          },
        };
        editor.editingData = {
          temperature: 0.7,
          prompts: [
            { identifier: 'main', name: 'Main Prompt', role: 'system', content: 'hello world' },
            { identifier: 'marker', name: 'Marker', role: 'system', marker: true },
          ],
          prompt_order: ['main', 'marker'],
        };
        editor.activeWorkspace = 'scalar_fields';
        editor.activeGroup = 'all';
        editor.searchTerm = 'temp';
        editor.refreshEditorCollections();
        const genericCacheBefore = editor.filteredItems;

        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'main';
        editor.syncActiveEditorSelections();
        editor.markClean();
        const genericWorkspaceCacheBefore = editor.genericWorkspaceItems;

        const originalRefreshEditorCollections = editor.refreshEditorCollections.bind(editor);
        let refreshCalls = 0;
        editor.refreshEditorCollections = (...args) => {
          refreshCalls += 1;
          return originalRefreshEditorCollections(...args);
        };

        editor.updatePromptField('content', 'updated body');

        if (!editor.isDirty) {
          throw new Error('expected prompt content edit to mark editor dirty');
        }
        if (refreshCalls !== 0) {
          throw new Error(`expected prompt content edit to avoid full collection refresh, got ${refreshCalls}`);
        }
        if (editor.activePromptItem?.content !== 'updated body') {
          throw new Error(`expected active prompt cache to update in place, got ${JSON.stringify(editor.activePromptItem)}`);
        }
        if (editor.genericWorkspaceItems !== genericWorkspaceCacheBefore) {
          throw new Error('expected prompt content edit to leave generic workspace cache untouched');
        }
        if (editor.editingData.prompts[0].content !== 'updated body') {
          throw new Error(`expected prompt content write to persist, got ${JSON.stringify(editor.editingData.prompts[0])}`);
        }
        """
    )


def test_preset_editor_runtime_large_editor_external_write_marks_dirty_and_refreshes_caches():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = handler;
          },
          removeEventListener(type, handler) {
            if (listeners[type] === handler) {
              delete listeners[type];
            }
          },
        };

        editor.editingData = {
          stop_sequence: ['alpha'],
        };
        editor.editingPresetFile = {
          reader_view: {
            family: 'generic',
            groups: [{ id: 'sequences', title: 'Sequences' }],
            items: [
              {
                id: 'field:stop_sequence',
                group: 'sequences',
                title: 'Stop Sequence',
                value_path: 'stop_sequence',
                source_key: 'stop_sequence',
                editable: true,
                editor: { kind: 'string-list' },
              },
            ],
          },
        };
        editor.markClean();

        editor.openLargeEditorForItem({ key: 'stop_sequence', label: 'Stop Sequence', value_path: 'stop_sequence' });
        if (events.length !== 1 || events[0].type !== 'open-large-editor') {
          throw new Error(`expected large editor open event, got ${JSON.stringify(events.map((event) => event.type))}`);
        }

        events[0].detail.editingData.stop_sequence.push('beta');
        if (editor.isDirty) {
          throw new Error('expected dirty state to stay clean before external save callback');
        }

        if (!listeners['large-editor-save']) {
          throw new Error('expected large editor save listener to be registered');
        }
        listeners['large-editor-save']();

        if (!editor.isDirty) {
          throw new Error('expected external large editor save to mark editor dirty');
        }
        if (JSON.stringify(editor.getByPath('stop_sequence')) !== JSON.stringify(['alpha', 'beta'])) {
          throw new Error(`expected external large editor write to persist, got ${JSON.stringify(editor.getByPath('stop_sequence'))}`);
        }
        if (!editor.isItemDirty(editor.filteredItems[0])) {
          throw new Error('expected changed-item tracking to refresh after large editor save');
        }
        """
    )


def test_preset_editor_runtime_advanced_extensions_apply_and_persist_follow_buffered_dual_save_flow():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = handler;
          },
          removeEventListener(type, handler) {
            if (listeners[type] === handler) {
              delete listeners[type];
            }
          },
        };
        editor.$store = { global: { showToast() {} } };

        editor.editingData = {
          extensions: {
            regex_scripts: [{ script: 'alpha' }],
            tavern_helper: { scripts: [] },
          },
        };
        editor.editingPresetFile = { id: 'preset-1' };
        editor.markClean();

        editor.openAdvancedExtensions();
        if (events.length !== 1 || events[0].type !== 'open-advanced-editor') {
          throw new Error(`expected advanced editor open event, got ${JSON.stringify(events.map((event) => event.type))}`);
        }
        if (events[0].detail.extensions === editor.editingData.extensions) {
          throw new Error('expected advanced editor payload to be detached from live extensions object');
        }

        events[0].detail.extensions.regex_scripts.push({ script: 'beta' });
        if (JSON.stringify(editor.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'alpha' }])) {
          throw new Error(`expected live extensions state to stay unchanged before save, got ${JSON.stringify(editor.editingData.extensions.regex_scripts)}`);
        }

        if (!listeners['advanced-editor-apply']) {
          throw new Error('expected advanced editor apply listener to be registered');
        }
        if (!listeners['advanced-editor-persist']) {
          throw new Error('expected advanced editor persist listener to be registered');
        }

        let saveExtensionsCalls = 0;
        editor.saveExtensions = async () => {
          saveExtensionsCalls += 1;
        };

        await listeners['advanced-editor-apply']();

        if (!editor.isDirty) {
          throw new Error('expected advanced editor apply to mark editor dirty');
        }
        if (JSON.stringify(editor.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'alpha' }, { script: 'beta' }])) {
          throw new Error(`expected advanced editor apply to update detached extensions payload, got ${JSON.stringify(editor.editingData.extensions.regex_scripts)}`);
        }
        if (saveExtensionsCalls !== 0) {
          throw new Error(`expected advanced editor apply to avoid saving immediately, got ${saveExtensionsCalls}`);
        }

        editor.openAdvancedExtensions();
        events[events.length - 1].detail.extensions.regex_scripts.push({ script: 'gamma' });
        await listeners['advanced-editor-persist']();

        if (saveExtensionsCalls !== 1) {
          throw new Error(`expected advanced editor persist to save once, got ${saveExtensionsCalls}`);
        }
        if (JSON.stringify(editor.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'alpha' }, { script: 'beta' }, { script: 'gamma' }])) {
          throw new Error(`expected advanced editor persist to update detached extensions payload, got ${JSON.stringify(editor.editingData.extensions.regex_scripts)}`);
        }
        if (events[events.length - 1]?.type !== 'advanced-editor-close') {
          throw new Error(`expected advanced editor persist to request close after save, got ${events[events.length - 1]?.type}`);
        }
        """
    )


def test_preset_editor_runtime_reopening_large_editor_replaces_stale_save_listener():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };

        editor.editingData = {
          stop_sequence: ['base'],
        };
        editor.markClean();

        editor.openLargeEditorForItem({ key: 'stop_sequence', label: 'Stop Sequence', value_path: 'stop_sequence' });
        const firstPayload = events[0].detail.editingData;
        firstPayload.stop_sequence.push('stale');

        editor.openLargeEditorForItem({ key: 'stop_sequence', label: 'Stop Sequence', value_path: 'stop_sequence' });
        const secondPayload = events[1].detail.editingData;
        secondPayload.stop_sequence.push('fresh');

        if ((listeners['large-editor-save'] || []).length !== 1) {
          throw new Error(`expected stale large editor listener cleanup, got ${(listeners['large-editor-save'] || []).length}`);
        }
        listeners['large-editor-save'][0]();

        if (JSON.stringify(editor.getByPath('stop_sequence')) !== JSON.stringify(['base', 'fresh'])) {
          throw new Error(`expected reopened large editor to ignore stale snapshot, got ${JSON.stringify(editor.getByPath('stop_sequence'))}`);
        }
        if (JSON.stringify(firstPayload.stop_sequence) !== JSON.stringify(['base', 'stale'])) {
          throw new Error(`expected stale payload to remain detached, got ${JSON.stringify(firstPayload.stop_sequence)}`);
        }
        """
    )


def test_preset_editor_runtime_reopening_advanced_editor_replaces_stale_apply_and_persist_listeners():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };
        editor.$store = { global: { showToast() {} } };

        editor.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };
        editor.editingPresetFile = { id: 'preset-1' };
        editor.markClean();

        editor.openAdvancedExtensions();
        const firstPayload = events[0].detail;
        firstPayload.extensions.regex_scripts.push({ script: 'stale' });

        editor.openAdvancedExtensions();
        const secondPayload = events[1].detail;
        secondPayload.extensions.regex_scripts.push({ script: 'fresh' });

        if ((listeners['advanced-editor-apply'] || []).length !== 1) {
          throw new Error(`expected stale advanced editor apply listener cleanup, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 1) {
          throw new Error(`expected stale advanced editor persist listener cleanup, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        await listeners['advanced-editor-apply'][0]();

        if (JSON.stringify(editor.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'fresh' }])) {
          throw new Error(`expected reopened advanced editor to ignore stale snapshot, got ${JSON.stringify(editor.editingData.extensions.regex_scripts)}`);
        }
        if (JSON.stringify(firstPayload.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'stale' }])) {
          throw new Error(`expected stale advanced payload to remain detached, got ${JSON.stringify(firstPayload.extensions.regex_scripts)}`);
        }
        """
    )


def test_preset_editor_runtime_close_editor_clears_pending_large_editor_save_listener():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.confirm = () => true;
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.editingData = {
          stop_sequence: ['base'],
        };
        editor.editingPresetFile = { id: 'preset-1' };
        editor.markClean();

        editor.openLargeEditorForItem({ key: 'stop_sequence', label: 'Stop Sequence', value_path: 'stop_sequence' });
        if ((listeners['large-editor-save'] || []).length !== 1) {
          throw new Error(`expected pending large editor save listener, got ${(listeners['large-editor-save'] || []).length}`);
        }

        editor.closeEditor();

        if ((listeners['large-editor-save'] || []).length !== 0) {
          throw new Error(`expected closeEditor to remove pending large editor save listener, got ${(listeners['large-editor-save'] || []).length}`);
        }
        if (editor.pendingLargeEditorSaveHandler !== null) {
          throw new Error('expected closeEditor to clear pendingLargeEditorSaveHandler reference');
        }
        """
    )


def test_preset_editor_runtime_close_editor_clears_pending_advanced_editor_apply_and_persist_listeners():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.confirm = () => true;
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };
        editor.editingPresetFile = { id: 'preset-1' };
        editor.markClean();

        editor.openAdvancedExtensions();
        if ((listeners['advanced-editor-apply'] || []).length !== 1) {
          throw new Error(`expected pending advanced editor apply listener, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 1) {
          throw new Error(`expected pending advanced editor persist listener, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }

        editor.closeEditor();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected closeEditor to remove pending advanced editor apply listener, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected closeEditor to remove pending advanced editor persist listener, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (editor.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected closeEditor to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (editor.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected closeEditor to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_editor_runtime_advanced_editor_apply_cleans_both_session_listeners():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };
        editor.$store = { global: { showToast() {} } };
        editor.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };
        editor.editingPresetFile = { id: 'preset-1' };

        editor.openAdvancedExtensions();
        await listeners['advanced-editor-apply'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected apply to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected apply to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (editor.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (editor.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_editor_runtime_advanced_editor_persist_cleans_both_session_listeners():
    run_preset_editor_runtime_check(
        """
        const listeners = {};
        const events = [];
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };
        globalThis.window = {
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
          addEventListener(type, handler) {
            listeners[type] = listeners[type] || [];
            listeners[type].push(handler);
          },
          removeEventListener(type, handler) {
            listeners[type] = (listeners[type] || []).filter((entry) => entry !== handler);
          },
        };
        editor.$store = { global: { showToast() {} } };
        editor.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };
        editor.editingPresetFile = { id: 'preset-1' };
        editor.saveExtensions = async () => true;

        editor.openAdvancedExtensions();
        await listeners['advanced-editor-persist'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected persist to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected persist to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (editor.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (editor.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorPersistHandler reference');
        }
        """
    )


def test_preset_editor_runtime_updates_and_removes_string_list_entries_by_path():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          stop_sequence: ['alpha', 'beta', 'gamma'],
        };

        editor.updateStringListItem('stop_sequence', 1, 'BETA');
        if (JSON.stringify(editor.editingData.stop_sequence) !== JSON.stringify(['alpha', 'BETA', 'gamma'])) {
          throw new Error(`expected string list update by path, got ${JSON.stringify(editor.editingData.stop_sequence)}`);
        }

        editor.removeStringListItem('stop_sequence', 0);
        if (JSON.stringify(editor.editingData.stop_sequence) !== JSON.stringify(['BETA', 'gamma'])) {
          throw new Error(`expected string list removal by path, got ${JSON.stringify(editor.editingData.stop_sequence)}`);
        }
        """
    )


def test_preset_editor_runtime_preserves_prompt_level_enabled_fallback_for_object_and_nested_prompt_order():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt', enabled: false },
            { identifier: 'summary', name: 'Summary', enabled: false },
          ],
          prompt_order: [
            { identifier: 'main' },
            { identifier: 'summary' },
          ],
        };

        const normalized = editor.normalizePromptOrder();
        if (normalized.length !== 2 || normalized.some((entry) => entry.enabled !== null)) {
          throw new Error(`expected object prompt_order entries without enabled to preserve fallback state, got ${JSON.stringify(normalized)}`);
        }

        let ordered = editor.orderedPromptItems.map((item) => ({
          id: item.__identifier,
          enabled: item.__enabled,
        }));
        if (JSON.stringify(ordered) !== JSON.stringify([
          { id: 'main', enabled: false },
          { id: 'summary', enabled: false },
        ])) {
          throw new Error(`expected object prompt_order fallback to preserve prompt enabled state, got ${JSON.stringify(ordered)}`);
        }

        editor.editingData.prompt_order = [
          {
            character_id: 100000,
            order: [
              { identifier: 'summary' },
            ],
          },
        ];

        const nestedNormalized = editor.normalizePromptOrder();
        if (nestedNormalized.length !== 1 || nestedNormalized[0].enabled !== null) {
          throw new Error(`expected nested prompt_order entry without enabled to preserve fallback state, got ${JSON.stringify(nestedNormalized)}`);
        }

        ordered = editor.orderedPromptItems.map((item) => ({
          id: item.__identifier,
          enabled: item.__enabled,
        }));
        if (JSON.stringify(ordered) !== JSON.stringify([
          { id: 'summary', enabled: false },
          { id: 'main', enabled: false },
        ])) {
          throw new Error(`expected nested prompt_order fallback to preserve prompt enabled state, got ${JSON.stringify(ordered)}`);
        }
        """
    )


def test_preset_editor_runtime_non_prompt_presets_keep_generic_workspace_flow():
    run_preset_editor_runtime_check(
        """
        editor.editingPresetFile = {
          reader_view: {
            family: 'generic',
            groups: [
              { id: 'scalar_fields', title: 'Fields' },
            ],
            items: [
              { id: 'field:temperature', group: 'scalar_fields', title: 'Temperature', editable: true },
            ],
            stats: {},
          },
        };
        editor.editingData = { temperature: 0.7 };
        editor.activeItemId = 'field:temperature';

        if (editor.isPromptWorkspaceEditor !== false) {
          throw new Error('expected generic preset to stay out of prompt workspace mode');
        }
        if (editor.genericWorkspaceItems.length !== 1) {
          throw new Error(`expected generic workspace items to come from filteredItems, got ${editor.genericWorkspaceItems.length}`);
        }

        editor.selectWorkspace('scalar_fields');
        if (editor.activeGroup !== 'scalar_fields') {
          throw new Error(`expected generic selectWorkspace to route through group selection, got ${editor.activeGroup}`);
        }
        if (editor.activeGenericItemId !== 'field:temperature') {
          throw new Error(`expected generic item selection to persist, got ${editor.activeGenericItemId}`);
        }
        """
    )


def test_preset_editor_runtime_reorders_prompt_items_and_syncs_simple_prompt_order():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt', role: 'system', content: 'A', marker: false },
            { identifier: 'worldInfoAfter', name: 'World Info (after)', marker: true },
            { identifier: 'summary', name: 'Summary', role: 'assistant', content: 'B', marker: false },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activePromptId = 'summary';

        editor.movePromptItem(1, 0);

        const ordered = editor.orderedPromptItems.map((item) => item.__identifier);
        if (JSON.stringify(ordered) !== JSON.stringify(['summary', 'main', 'worldInfoAfter'])) {
          throw new Error(`expected reordered prompts, got ${JSON.stringify(ordered)}`);
        }
        if (editor.editingData.prompts[0].identifier !== 'summary') {
          throw new Error(`expected prompts array reorder, got ${JSON.stringify(editor.editingData.prompts)}`);
        }
        if (JSON.stringify(editor.editingData.prompt_order) !== JSON.stringify(['summary', 'main', 'worldInfoAfter'])) {
          throw new Error(`expected synced simple prompt_order, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        """
    )


def test_preset_editor_runtime_toggles_nested_prompt_order_enabled_state():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt', role: 'system', content: 'A', marker: false },
            { identifier: 'worldInfoBefore', name: 'World Info (before)', marker: true },
          ],
          prompt_order: [
            {
              character_id: 100000,
              order: [
                { identifier: 'main', enabled: true },
                { identifier: 'worldInfoBefore', enabled: false },
              ],
            },
          ],
        };

        editor.togglePromptEnabled('worldInfoBefore');

        const nestedOrder = editor.editingData.prompt_order[0].order;
        if (nestedOrder[1].enabled !== true) {
          throw new Error(`expected nested enabled toggle, got ${JSON.stringify(nestedOrder)}`);
        }
        """
    )


def test_preset_editor_runtime_blocks_marker_content_updates():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'worldInfoAfter', name: 'World Info (after)', marker: true },
            { identifier: 'main', name: 'Main Prompt', role: 'system', content: 'A', marker: false },
          ],
          prompt_order: ['worldInfoAfter', 'main'],
        };
        editor.activePromptId = 'worldInfoAfter';

        editor.updatePromptField('content', 'should not be written');
        editor.activePromptId = 'main';
        editor.updatePromptField('content', 'updated');

        if ('content' in editor.editingData.prompts[0]) {
          throw new Error(`marker prompt content should stay absent, got ${JSON.stringify(editor.editingData.prompts[0])}`);
        }
        if (editor.editingData.prompts[1].content !== 'updated') {
          throw new Error(`non-marker prompt content should update, got ${JSON.stringify(editor.editingData.prompts[1])}`);
        }
        """
    )


def test_preset_editor_runtime_reorders_prompts_without_identifier_and_keeps_them_in_prompts_array():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { name: 'Unnamed A', content: 'A' },
            { name: 'Unnamed B', content: 'B' },
          ],
        };

        editor.movePromptItem(1, 0);

        if (editor.editingData.prompts.length !== 2) {
          throw new Error(`expected reorder to preserve prompts without identifiers, got ${JSON.stringify(editor.editingData.prompts)}`);
        }
        if (editor.editingData.prompts[0].name !== 'Unnamed B') {
          throw new Error(`expected unnamed prompt reorder to preserve moved item, got ${JSON.stringify(editor.editingData.prompts)}`);
        }
        if (Object.prototype.hasOwnProperty.call(editor.editingData, 'prompt_order')) {
          throw new Error(`expected unnamed prompt reorder to avoid persisting synthetic prompt_order, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        """
    )


def test_preset_editor_runtime_toggles_unnamed_prompt_enabled_without_creating_prompt_order():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { name: 'Unnamed A', enabled: true },
            { name: 'Unnamed B', enabled: true },
          ],
        };

        editor.togglePromptEnabled('prompt_2');

        if (editor.editingData.prompts[1].enabled !== false) {
          throw new Error(`expected unnamed prompt toggle to persist on prompt object, got ${JSON.stringify(editor.editingData.prompts)}`);
        }
        if (Object.prototype.hasOwnProperty.call(editor.editingData, 'prompt_order')) {
          throw new Error(`expected unnamed prompt toggle to avoid persisting synthetic prompt_order, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        """
    )


def test_preset_editor_runtime_preserves_missing_enabled_fields_when_syncing_object_prompt_order():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt', enabled: false },
            { identifier: 'summary', name: 'Summary', enabled: false },
          ],
          prompt_order: [
            { identifier: 'main' },
            { identifier: 'summary' },
          ],
        };

        editor.movePromptItem(1, 0);

        if (JSON.stringify(editor.editingData.prompt_order) !== JSON.stringify([
          { identifier: 'summary' },
          { identifier: 'main' },
        ])) {
          throw new Error(`expected object prompt_order sync to preserve missing enabled fields, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        """
    )


def test_preset_editor_runtime_ignores_reorder_for_unsupported_multi_bucket_nested_prompt_order():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt' },
            { identifier: 'summary', name: 'Summary' },
          ],
          prompt_order: [
            {
              character_id: 100000,
              order: [
                { identifier: 'main', enabled: true },
              ],
            },
            {
              character_id: 100001,
              order: [
                { identifier: 'summary', enabled: false },
              ],
            },
          ],
        };

        const beforePrompts = JSON.stringify(editor.editingData.prompts);
        const beforeOrder = JSON.stringify(editor.editingData.prompt_order);

        editor.movePromptItem(1, 0);

        if (JSON.stringify(editor.editingData.prompts) !== beforePrompts) {
          throw new Error(`expected unsupported multi-bucket reorder to leave prompts unchanged, got ${JSON.stringify(editor.editingData.prompts)}`);
        }
        if (JSON.stringify(editor.editingData.prompt_order) !== beforeOrder) {
          throw new Error(`expected unsupported multi-bucket reorder to leave prompt_order unchanged, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        """
    )


def test_preset_editor_runtime_renames_prompt_identifier_and_keeps_prompt_order_and_selection_in_sync():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main Prompt', content: 'A' },
            { identifier: 'summary', name: 'Summary', content: 'B' },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activePromptId = 'main';

        editor.updatePromptField('identifier', 'main-renamed');

        if (editor.activePromptId !== 'main-renamed') {
          throw new Error(`expected active prompt selection to follow renamed identifier, got ${editor.activePromptId}`);
        }
        if (JSON.stringify(editor.editingData.prompt_order) !== JSON.stringify(['main-renamed', 'summary'])) {
          throw new Error(`expected prompt_order to stay aligned after identifier rename, got ${JSON.stringify(editor.editingData.prompt_order)}`);
        }
        if (editor.orderedPromptItems[0].__identifier !== 'main-renamed') {
          throw new Error(`expected ordered prompt metadata to use renamed identifier, got ${JSON.stringify(editor.orderedPromptItems.map((item) => item.__identifier))}`);
        }
        """
    )


def test_preset_editor_js_tracks_changed_state_and_safe_nested_path_writes():
    source = read_project_file('static/js/components/presetEditor.js')

    assert 'isItemDirty(item) {' in source
    assert 'return [item.value_path, item.source_key, item.key, item.id].some(' in source
    assert 'if (target[part] === null || typeof target[part] !== "object") {' in source
    assert 'markAllReaderItemsDirty() {' in source
    assert 'this.markAllReaderItemsDirty();' in source


def test_preset_editor_template_uses_three_column_workspace_contracts():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-model="searchTerm"' in source
    assert '@click="selectGroup(group.id)"' in source
    assert 'x-for="item in filteredItems"' in source
    assert '@click="selectItem(item.id)"' in source
    assert 'x-text="activeItem?.title ||' in source
    assert 'x-show="showRightPanel || $store.global.deviceType !== ' in source
    assert 'x-show="uiFilter ===' in source or 'uiFilter' in source


def test_preset_editor_template_routes_scalar_editors_through_field_helpers():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert ':value="getFieldValue(activeItem) || \'' in source
    assert '@input="setFieldValue(activeItem, $event.target.value)"' in source
    assert ':checked="Boolean(getFieldValue(activeItem))"' in source
    assert '@change="setFieldValue(activeItem, $event.target.checked)"' in source
    assert ':value="getFieldValue(activeItem) ?? 0"' in source
    assert '@input="setFieldValue(activeItem, Number($event.target.value))"' in source
    assert 'x-text="formatValue(getFieldValue(activeItem))"' in source
    assert ':value="getByPath(activeItem.value_path) || \'' not in source
    assert '@input="setByPath(activeItem.value_path, $event.target.value)"' not in source
    assert ':checked="Boolean(getByPath(activeItem.value_path))"' not in source
    assert '@change="setByPath(activeItem.value_path, $event.target.checked)"' not in source
    assert ':value="getByPath(activeItem.value_path) ?? 0"' not in source
    assert '@input="setByPath(activeItem.value_path, Number($event.target.value))"' not in source
    assert 'x-text="formatValue(getByPath(activeItem?.value_path))"' not in source


def test_preset_editor_template_uses_prompt_workspace_layout_contracts():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-if="isPromptWorkspaceEditor && activeWorkspace === \'prompts\'"' in source
    assert 'x-if="isPromptWorkspaceEditor"' not in source
    assert 'x-for="(prompt, index) in orderedPromptItems"' in source or 'x-for="prompt in orderedPromptItems"' in source
    assert '@click="selectPrompt(prompt.__identifier)"' in source
    assert '@click.stop="movePromptItem(index, index - 1)"' in source or '@click="movePromptItem(index, index - 1)"' in source
    assert '@click.stop="movePromptItem(index, index + 1)"' in source or '@click="movePromptItem(index, index + 1)"' in source
    assert '@click.stop="togglePromptEnabled(prompt.__identifier)"' not in source
    assert '切换启用' not in source
    assert 'getPromptRoleLabel(prompt.role)' in source
    assert 'getPromptPositionLabel(prompt)' in source
    assert 'prompt.__enabled !== false ? \'启用\' : \'禁用\'' not in source
    assert '<span>启用</span>' not in source
    assert 'aria-label="切换提示词启用状态"' in source
    assert '占位用预留字段，不承载提示词内容' not in source
    assert 'x-show="!activePromptItem?.marker"' not in source


def test_preset_editor_template_exposes_scalar_workspace_parameter_panels():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-if="isScalarWorkspaceEditor"' in source
    assert 'x-for="section in scalarWorkspaceSections"' in source
    assert 'getScalarWorkspaceSectionEntries(section.id)' in source
    assert (
        'getScalarWorkspaceFieldValue(field.storage_key)' in source
        or 'setScalarWorkspaceFieldValue(field.storage_key' in source
    )


def test_preset_editor_template_exposes_filtered_mirrored_profile_control_panels():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-for="field in mirroredWorkspaceFieldItems"' in source
    assert '@click="selectMirroredField(field.id)"' in source
    assert 'x-for="field in getProfileSectionFields(activeMirroredSection.id)"' not in source


def test_preset_editor_template_exposes_mirrored_profile_section_navigation():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '@click="selectWorkspace(section.id === \'prompt_manager\' ? \'prompts\' : section.id)"' in source
    assert 'getMirroredSectionFieldCount(section.id)' in source


def test_preset_editor_template_mirrored_profile_renders_active_section_only_and_skips_prompt_manager_panel():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "x-if=\"activeMirroredSection && activeMirroredSection.id !== 'prompt_manager'\"" in source
    assert 'x-text="activeMirroredSection.label"' in source
    assert 'x-text="activeMirroredSection.description || activeMirroredSection.id"' in source
    assert "x-if=\"section.id !== 'prompt_manager'\"" not in source


def test_preset_editor_template_mirrored_profile_uses_stable_field_ids_for_bindings():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'getProfileFieldValue(field.id)' in source
    assert 'getProfileFieldPercent(field.id)' in source
    assert 'setProfileFieldValue(field.id, $event.target.value)' in source
    assert 'setProfileFieldValue(field.id, $event.target.checked)' in source
    assert 'getProfileFieldValue(field.canonical_key)' not in source
    assert 'getProfileFieldPercent(field.canonical_key)' not in source
    assert 'setProfileFieldValue(field.canonical_key, $event.target.value)' not in source
    assert 'setProfileFieldValue(field.canonical_key, $event.target.checked)' not in source


def test_preset_editor_template_uses_user_facing_active_mirrored_field_panel():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'activeMirroredField?.description' in source
    assert '当前筛选下没有可用字段' in source
    assert 'getProfileFieldValue(activeMirroredField.id)' not in source
    assert 'getProfileFieldValue(activeMirroredField?.id)' in source
    assert 'activeMirroredField?.storage_key' not in source
    assert 'activeMirroredField?.source_key ||' not in source
    assert 'activeMirroredField?.preset_bound' not in source


def test_preset_editor_template_exposes_full_mirrored_profile_control_kinds():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "field.control === 'sortable_string_list' || field.control === 'string_list'" in source
    assert "field.control === 'key_value_list'" in source
    assert "field.control === 'raw_json'" in source
    assert "field.control === 'key_value_list' && field.id === 'logit_bias'" in source
    assert "field.control === 'raw_json' && field.id === 'extensions'" in source
    assert '@click="openAdvancedExtensions()"' in source


def test_preset_editor_template_mirrored_profile_supports_number_controls_and_live_textarea_updates():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "field.control === 'number'" in source
    assert '@input="setProfileFieldValue(field.id, $event.target.value)"' in source


def test_preset_editor_template_mirrored_profile_branch_yields_to_prompt_workspace():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "x-if=\"isMirroredProfileEditor && editorProfile && (!isPromptWorkspaceEditor || activeWorkspace !== 'prompts')\"" in source


def test_preset_editor_template_scalar_workspace_supports_structured_editor_kinds():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "field.editor === 'textarea'" in source
    assert "field.editor === 'sortable-string-list'" in source
    assert "field.editor === 'key-value-list'" in source
    assert "field.editor !== 'number' && field.editor !== 'boolean'" not in source


def test_preset_editor_template_exposes_prompt_form_fields_instead_of_prompt_raw_json():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "updatePromptField('name'" in source
    assert "updatePromptField('role'" in source
    assert "updatePromptField('injection_position'" in source
    assert "updatePromptField('injection_depth'" in source
    assert "updatePromptField('injection_order'" in source
    assert 'updatePromptTriggers(' in source
    assert 'x-for="option in promptRoleOptions"' in source
    assert 'x-for="option in promptTriggerOptions"' in source
    assert 'x-for="option in promptPositionOptions"' in source
    assert ':value="option.value"' in source
    assert 'x-text="option.label"' in source
    assert 'activePromptItem.injection_trigger.includes(option.value)' in source
    assert 'isChatInjectionPosition(activePromptItem)' in source
    assert '占位用预留字段，不承载提示词内容' not in source
    assert 'placeholder="占位用预留字段，不承载提示词内容"' not in source
    assert "item.editor?.kind === 'prompt-item'" not in source
    assert "activeItem?.editor?.kind === 'prompt-item'" not in source


def test_preset_editor_template_adds_prompt_helper_copy_and_removes_nested_list_scroll_regions():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert '用于侧栏列表和编辑器顶部的可读名称。' in source
    assert '角色决定提示词以谁的身份注入上下文。' in source
    assert '勾选后仅在对应场景触发此提示词。' in source
    assert '控制提示词是在聊天外相对插入，还是注入到聊天流中。' in source
    assert '仅在“聊天中”位置下生效，数值越小越靠前。' in source
    assert '仅在“聊天中”位置下生效，用于同深度提示词排序。' in source
    assert '填写实际要注入的提示词正文；marker 条目无需内容。' in source
    assert 'p-3 space-y-2 overflow-y-auto custom-scrollbar max-h-[calc(100vh-12rem)] xl:max-h-none' not in source
    assert 'overflow-y-auto custom-scrollbar min-h-[22rem]' not in source


def test_preset_editor_template_renders_marker_icons_switches_and_scroll_safe_prompt_columns():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'x-html="getPromptMarkerIcon(prompt)"' in source
    assert 'xl:grid-cols-[22rem_minmax(0,1fr)]' in source
    for token in ['gap-4', 'h-full', 'min-h-0']:
        assert token in source
    for token in ['flex-1', 'min-h-0', 'overflow-y-auto', 'custom-scrollbar', 'p-3', 'space-y-2']:
        assert token in source
    assert 'class="peer prompt-toggle-input"' in source
    assert 'min-h-9' in source
    assert 'min-w-9' in source
    assert 'justify-center' in source
    assert 'peer-focus-visible:ring-2' in source
    assert 'peer-focus-visible:ring-[var(--accent-main)]/60' in source
    assert 'pointer-events-none absolute left-[2px] top-[2px] h-4 w-4 rounded-full transition-transform' in source


def test_preset_editor_template_splits_mobile_prompt_workspace_into_list_and_detail_views_mobile_prompt_detail_view():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'showMobilePromptDetailView' in source
    assert 'showMobilePromptDetailView ?' not in source
    assert "x-show=\"$store.global.deviceType === 'mobile' && !showMobilePromptDetailView\"" in source
    assert "x-show=\"$store.global.deviceType === 'mobile' && showMobilePromptDetailView\"" in source
    assert '返回提示词列表' in source
    assert '@click="closeMobilePromptDetailView()"' in source


def test_preset_editor_template_wraps_prompt_workspace_mobile_and_desktop_branches_in_single_root_mobile_prompt_detail_view():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    prompt_workspace_start = source.index(
        '<template x-if="isPromptWorkspaceEditor && activeWorkspace === \'prompts\'">'
    )
    scalar_workspace_start = source.index('<template x-if="isScalarWorkspaceEditor">')
    prompt_workspace_block = source[prompt_workspace_start:scalar_workspace_start]

    assert 'class="space-y-4 h-full min-h-0"' in prompt_workspace_block
    assert 'x-if="$store.global.deviceType !== \'mobile\'"' in prompt_workspace_block
    assert "x-show=\"$store.global.deviceType === 'mobile' && !showMobilePromptDetailView\"" in prompt_workspace_block
    assert "x-show=\"$store.global.deviceType === 'mobile' && showMobilePromptDetailView\"" in prompt_workspace_block


def test_preset_editor_template_uses_single_prompt_workspace_gate_in_main_content_mobile_prompt_detail_view():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    main_start = source.index('<main')
    scalar_workspace_start = source.index('<template x-if="isScalarWorkspaceEditor">')
    main_prompt_block = source[main_start:scalar_workspace_start]

    assert '<template x-if="isPromptWorkspaceEditor && activeWorkspace === \'prompts\'">' in main_prompt_block
    assert '<template x-if="isPromptWorkspaceEditor">' not in main_prompt_block
    assert '<template x-if="activeWorkspace === \'prompts\'">' not in main_prompt_block


def test_preset_editor_template_removes_mobile_prompt_right_info_toggle_and_keeps_desktop_prompt_editor_mobile_prompt_detail_view():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    desktop_prompt_workspace_block = extract_tag_block(
        source,
        "x-if=\"$store.global.deviceType !== 'mobile'\"",
        tag_name='template',
    )
    mobile_prompt_detail_block = extract_tag_block(
        source,
        "x-show=\"$store.global.deviceType === 'mobile' && showMobilePromptDetailView\"",
    )

    assert 'xl:grid-cols-[22rem_minmax(0,1fr)]' in desktop_prompt_workspace_block
    assert '当前提示词' in desktop_prompt_workspace_block
    assert '@click="toggleMobileRightPanel()"' not in desktop_prompt_workspace_block

    assert '当前提示词' in mobile_prompt_detail_block
    assert '提示词内容' in mobile_prompt_detail_block
    assert "updatePromptField('name'" in mobile_prompt_detail_block
    assert "updatePromptField('role'" in mobile_prompt_detail_block
    assert "updatePromptField('content'" in mobile_prompt_detail_block
    assert '@click="toggleMobileRightPanel()"' not in mobile_prompt_detail_block
    assert '右侧信息' not in mobile_prompt_detail_block


def test_preset_editor_template_keeps_mobile_prompt_list_and_detail_branches_specialized_mobile_prompt_detail_view():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    mobile_prompt_list_block = extract_tag_block(
        source,
        "x-show=\"$store.global.deviceType === 'mobile' && !showMobilePromptDetailView\"",
    )
    mobile_prompt_detail_block = extract_tag_block(
        source,
        "x-show=\"$store.global.deviceType === 'mobile' && showMobilePromptDetailView\"",
    )

    assert '点选条目进入编辑' in mobile_prompt_list_block
    assert '@click="selectPrompt(prompt.__identifier)"' in mobile_prompt_list_block
    assert '@change="togglePromptEnabled(prompt.__identifier)"' in mobile_prompt_list_block
    assert '@click.stop="movePromptItem(index, index - 1)"' in mobile_prompt_list_block
    assert '@click.stop="movePromptItem(index, index + 1)"' in mobile_prompt_list_block
    assert '提示词内容' not in mobile_prompt_list_block
    assert '返回提示词列表' not in mobile_prompt_list_block

    assert '@click="closeMobilePromptDetailView()"' in mobile_prompt_detail_block
    assert '返回提示词列表' in mobile_prompt_detail_block
    assert '提示词基础信息' in mobile_prompt_detail_block
    assert '提示词内容' in mobile_prompt_detail_block
    assert '@click="selectPrompt(prompt.__identifier)"' not in mobile_prompt_detail_block


def test_preset_editor_template_uses_dedicated_prompt_toggle_input_skin_override():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    css_source = read_project_file('static/css/modules/components.css')

    assert 'class="peer prompt-toggle-input"' in source
    assert '.prompt-toggle-input[type="checkbox"] {' in css_source
    for token in ['position: absolute;', 'inset: 0;', 'width: 100%;', 'height: 100%;', 'opacity: 0;']:
        assert token in css_source
    assert '.prompt-toggle-input[type="checkbox"]:checked::after {' in css_source
    assert 'content: none;' in css_source


def test_preset_editor_template_keeps_editor_panels_within_width_bounds():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    for token in ['bg-[var(--bg-panel)]', 'min-h-[22rem]', 'flex', 'flex-col', 'min-w-0', 'overflow-hidden']:
        assert token in source
    for token in ['flex-1', 'min-h-0', 'overflow-y-auto', 'custom-scrollbar', 'p-5', 'space-y-5']:
        assert token in source
    for token in ['form-textarea', 'min-h-[320px]', 'w-full', 'max-w-full']:
        assert token in source
    for token in ['form-textarea', 'min-h-[280px]', 'w-full', 'max-w-full', 'min-w-0', 'custom-scrollbar']:
        assert token in source
    assert 'xl:grid-cols-[20rem_minmax(0,1fr)]' in source
    for token in ['gap-4', 'h-full', 'min-h-0']:
        assert token in source


def test_preset_editor_template_localizes_prompt_sidebar_summary_labels():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert 'getPromptRoleLabel(activePromptItem?.role)' in source
    assert 'getPromptPositionLabel(activePromptItem)' in source
    assert 'prompt.role || prompt.__identifier || \'prompt\'' not in source
    assert 'Number(prompt.injection_position ?? 0) === 1 ? `In-Chat @ ${Number(prompt.injection_depth ?? 4)}` : \'相对位置\'' not in source


def test_preset_editor_runtime_normalizes_role_and_trigger_option_object_values():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          prompts: [
            {
              identifier: 'main',
              role: 'assistant',
              injection_trigger: ['normal'],
            },
          ],
        };
        editor.activePromptId = 'main';

        const selectedTriggerValues = editor.promptTriggerOptions
          .filter((option) => ['continue', 'quiet'].includes(option.value))
          .map((option) => option.value);
        editor.updatePromptTriggers(selectedTriggerValues);

        if (JSON.stringify(editor.editingData.prompts[0].injection_trigger) !== JSON.stringify(['continue', 'quiet'])) {
          throw new Error(`expected trigger option object values to persist, got ${JSON.stringify(editor.editingData.prompts[0].injection_trigger)}`);
        }

        editor.updatePromptField('role', editor.promptRoleOptions[1].value);
        if (editor.editingData.prompts[0].role !== 'user') {
          throw new Error(`expected role select option value to persist, got ${JSON.stringify(editor.editingData.prompts[0].role)}`);
        }
        """
    )


def test_preset_editor_template_keeps_right_info_toggle_mobile_only():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    right_info_buttons = re.findall(
        r'<button\b[^>]*>[\s\S]*?右侧信息\s*</button>',
        source,
    )

    assert right_info_buttons

    for button in right_info_buttons:
        assert '@click="toggleMobileRightPanel()"' in button
        assert 'md:hidden' in button


def test_preset_editor_template_adds_mobile_header_shell_and_primary_actions():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    mobile_header_block = extract_tag_block(source, 'preset-editor-mobile-header')

    assert 'x-show="$store.global.deviceType !== \'mobile\'"' in source
    assert 'hidden md:flex h-12' not in source
    assert 'preset-editor-mobile-header' in source
    assert 'preset-editor-mobile-header-top' in mobile_header_block
    assert 'preset-editor-mobile-header-bottom' in mobile_header_block
    assert 'x-ref="presetEditorMobileHeader"' in mobile_header_block
    assert '@click="closeEditor()"' in mobile_header_block
    assert '@click="saveOverwrite()"' in mobile_header_block
    assert '@click="toggleMobileHeaderMoreMenu()"' in mobile_header_block
    assert 'x-text="presetTitle"' in mobile_header_block
    assert 'x-text="getMobileHeaderMetaLine()"' in mobile_header_block


def test_preset_editor_template_moves_secondary_actions_into_mobile_more_menu_and_marks_scroll_region():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    mobile_header_block = extract_tag_block(source, 'preset-editor-mobile-header')
    mobile_more_menu_block = extract_tag_block(source, 'preset-editor-mobile-more-menu')

    assert 'preset-editor-mobile-more-menu' in source
    assert '@click="saveAs()"' in mobile_more_menu_block
    assert '@click="renamePreset()"' in mobile_more_menu_block
    assert '@click="deletePreset()"' in mobile_more_menu_block
    assert '@click="createSnapshot()"' in mobile_more_menu_block
    assert '@click="openRollback()"' in mobile_more_menu_block
    assert '@click="openAdvancedExtensions()"' in mobile_more_menu_block
    assert 'x-ref="presetEditorContentScroll"' in source
    assert '@scroll.passive="handleMobileEditorContentScroll($event)"' in source

    assert '@click="saveAs()"' not in mobile_header_block
    assert '@click="renamePreset()"' not in mobile_header_block
    assert '@click="deletePreset()"' not in mobile_header_block
    assert '@click="createSnapshot()"' not in mobile_header_block
    assert '@click="openRollback()"' not in mobile_header_block
    assert '@click="openAdvancedExtensions()"' not in mobile_header_block


def test_preset_editor_mobile_header_css_uses_safe_area_compact_state_and_header_height_offsets():
    css_source = read_project_file('static/css/modules/modal-detail.css')

    assert '.detail-preset-full-screen .preset-editor-mobile-header {' in css_source
    assert '.detail-preset-full-screen .preset-editor-mobile-header.is-compact {' in css_source
    assert '.detail-preset-full-screen .preset-editor-mobile-header-bottom {' in css_source
    assert '.detail-preset-full-screen .preset-editor-mobile-more-menu {' in css_source
    assert '.detail-preset-full-screen .preset-editor-mobile-panel {' in css_source
    assert '.detail-preset-full-screen .preset-editor-mobile-panel--right {' in css_source
    assert 'padding: calc(env(safe-area-inset-top, 0px) + 0.75rem)' in css_source
    assert 'top: var(--preset-editor-header-height);' in css_source


def test_preset_editor_js_exposes_mobile_header_state_and_helpers():
    source = read_project_file('static/js/components/presetEditor.js')

    required_tokens = [
        'presetEditorMobileHeaderCompact:',
        'presetEditorLastScrollTop:',
        'showMobileHeaderMoreMenu:',
        'getMobileHeaderMetaLine() {',
        'getCompactHeaderStatusLabel() {',
        'resetMobileHeaderState() {',
        'revealMobileHeader() {',
        'toggleMobileHeaderMoreMenu() {',
        'openMobileSidebar() {',
        'closeMobileSidebar() {',
        'toggleMobileRightPanel() {',
        'closeMobileRightPanel() {',
        'updatePresetEditorLayoutMetrics() {',
        'syncPresetEditorMobileHeaderCompactState(container) {',
        'handleMobileEditorContentScroll(event) {',
    ]

    for token in required_tokens:
        assert token in source, f'missing mobile header state/helper contract token: {token}'


def test_preset_editor_js_exposes_mobile_prompt_detail_view_state_and_helpers_mobile_prompt_detail_view():
    source = read_project_file('static/js/components/presetEditor.js')

    required_tokens = [
        'showMobilePromptDetailView:',
        'openMobilePromptDetailView() {',
        'closeMobilePromptDetailView() {',
    ]

    for token in required_tokens:
        assert token in source, f'missing mobile prompt detail view contract token: {token}'


def test_preset_editor_runtime_reveals_mobile_header_for_more_menu():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };

        editor.presetEditorMobileHeaderCompact = true;
        editor.showMobileHeaderMoreMenu = false;

        editor.toggleMobileHeaderMoreMenu();
        if (editor.showMobileHeaderMoreMenu !== true) {
          throw new Error(`expected more menu to open, got ${editor.showMobileHeaderMoreMenu}`);
        }
        if (editor.presetEditorMobileHeaderCompact !== false) {
          throw new Error(`expected opening more menu to reveal mobile header, got compact=${editor.presetEditorMobileHeaderCompact}`);
        }
        """
    )


def test_preset_editor_runtime_reveals_mobile_header_for_mobile_sidebar():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };

        editor.presetEditorMobileHeaderCompact = true;
        editor.showMobileSidebar = false;

        editor.openMobileSidebar();
        if (editor.showMobileSidebar !== true) {
          throw new Error(`expected mobile sidebar to open, got ${editor.showMobileSidebar}`);
        }
        if (editor.presetEditorMobileHeaderCompact !== false) {
          throw new Error(`expected opening sidebar to reveal mobile header, got compact=${editor.presetEditorMobileHeaderCompact}`);
        }
        """
    )


def test_preset_editor_runtime_reveals_mobile_header_for_right_panel():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };

        editor.presetEditorMobileHeaderCompact = true;
        editor.showRightPanel = false;

        editor.toggleMobileRightPanel();
        if (editor.showRightPanel !== true) {
          throw new Error(`expected right panel to open, got ${editor.showRightPanel}`);
        }
        if (editor.presetEditorMobileHeaderCompact !== false) {
          throw new Error(`expected opening right panel to reveal mobile header, got compact=${editor.presetEditorMobileHeaderCompact}`);
        }
        """
    )


def test_preset_editor_runtime_compacts_and_expands_mobile_header_from_scroll():
    run_preset_editor_runtime_check(
        """
        globalThis.Element = class Element {};

        const container = new Element();
        container.scrollTop = 0;

        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.showMobileSidebar = false;
        editor.showRightPanel = false;
        editor.showMobileHeaderMoreMenu = false;
        editor.presetEditorMobileHeaderCompact = false;
        editor.presetEditorLastScrollTop = 0;

        container.scrollTop = 96;
        editor.handleMobileEditorContentScroll({ target: container });
        if (editor.presetEditorMobileHeaderCompact !== true) {
          throw new Error(`expected downward mobile scroll to compact header, got ${editor.presetEditorMobileHeaderCompact}`);
        }

        container.scrollTop = 8;
        editor.handleMobileEditorContentScroll({ target: container });
        if (editor.presetEditorMobileHeaderCompact !== false) {
          throw new Error(`expected upward or near-top scroll to expand header, got ${editor.presetEditorMobileHeaderCompact}`);
        }
        """
    )


def test_preset_editor_runtime_clears_mobile_header_state_on_close():
    run_preset_editor_runtime_check(
        """
        globalThis.confirm = () => {
          throw new Error('confirm should not run when hasUnsavedChanges is false');
        };

        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.showMobileSidebar = true;
        editor.showRightPanel = true;
        editor.showMobileHeaderMoreMenu = true;
        editor.presetEditorMobileHeaderCompact = true;
        editor.presetEditorLastScrollTop = 96;
        editor.hasUnsavedChanges = false;

        editor.closeEditor();

        if (editor.showMobileSidebar !== false) {
          throw new Error(`expected closeEditor to clear mobile sidebar, got ${editor.showMobileSidebar}`);
        }
        if (editor.showRightPanel !== false) {
          throw new Error(`expected closeEditor to clear right panel, got ${editor.showRightPanel}`);
        }
        if (editor.showMobileHeaderMoreMenu !== false) {
          throw new Error(`expected closeEditor to clear mobile more menu, got ${editor.showMobileHeaderMoreMenu}`);
        }
        if (editor.presetEditorMobileHeaderCompact !== false) {
          throw new Error(`expected closeEditor to reveal mobile header, got compact=${editor.presetEditorMobileHeaderCompact}`);
        }
        if (editor.presetEditorLastScrollTop !== 0) {
          throw new Error(`expected closeEditor to reset last scroll position, got ${editor.presetEditorLastScrollTop}`);
        }
        """
    )


def test_preset_editor_runtime_select_prompt_enters_mobile_prompt_detail_view():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.editingPresetFile = {
          id: 'preset-1',
          preset_kind: 'textgen',
          raw_data: {},
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [{ id: 'prompt_manager', label: '提示词管理' }],
            fields: {
              prompts: {
                id: 'prompts',
                storage_key: 'prompts',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
            },
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [{ id: 'prompts', label: 'Prompt 条目' }],
            items: [],
            stats: {},
          },
        };
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main', content: 'hello' },
            { identifier: 'summary', name: 'Summary', content: 'world' },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activeWorkspace = 'prompts';
        editor.showMobilePromptDetailView = false;
        editor.refreshEditorCollections();

        editor.selectPrompt('summary');

        if (editor.activePromptId !== 'summary') {
          throw new Error(`expected prompt selection to switch active prompt, got ${editor.activePromptId}`);
        }
        if (editor.showMobilePromptDetailView !== true) {
          throw new Error(`expected mobile prompt selection to open detail view, got ${editor.showMobilePromptDetailView}`);
        }
        """
    )


def test_preset_editor_runtime_closes_mobile_prompt_detail_view_without_clearing_selection():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main', content: 'hello' },
            { identifier: 'summary', name: 'Summary', content: 'world' },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'summary';
        editor.showMobilePromptDetailView = true;
        editor.refreshEditorCollections();

        editor.closeMobilePromptDetailView();

        if (editor.showMobilePromptDetailView !== false) {
          throw new Error(`expected closing mobile prompt detail view to hide detail pane, got ${editor.showMobilePromptDetailView}`);
        }
        if (editor.activePromptId !== 'summary') {
          throw new Error(`expected closing mobile prompt detail view to preserve selection, got ${editor.activePromptId}`);
        }
        """
    )


def test_preset_editor_runtime_resets_mobile_prompt_detail_view_on_workspace_switch_and_close():
    run_preset_editor_runtime_check(
        """
        editor.$store = { global: { deviceType: 'mobile', showToast() {} } };
        editor.editingPresetFile = {
          id: 'preset-1',
          preset_kind: 'textgen',
          raw_data: {},
          editor_profile: {
            id: 'st_chat_completion_preset',
            family: 'st_mirror',
            sections: [
              { id: 'prompt_manager', label: '提示词管理' },
              { id: 'output_and_reasoning', label: '输出与思考' },
            ],
            fields: {
              prompts: {
                id: 'prompts',
                storage_key: 'prompts',
                section: 'prompt_manager',
                control: 'prompt_workspace',
              },
            },
          },
          reader_view: {
            family: 'prompt_manager',
            groups: [
              { id: 'prompts', label: 'Prompt 条目' },
              { id: 'output_and_reasoning', label: '输出与思考' },
            ],
            items: [],
            stats: {},
          },
        };
        editor.editingData = {
          prompts: [
            { identifier: 'main', name: 'Main', content: 'hello' },
            { identifier: 'summary', name: 'Summary', content: 'world' },
          ],
          prompt_order: ['main', 'summary'],
        };
        editor.activeWorkspace = 'prompts';
        editor.activePromptId = 'summary';
        editor.showMobilePromptDetailView = true;
        editor.refreshEditorCollections();

        editor.selectWorkspace('output_and_reasoning');
        if (editor.showMobilePromptDetailView !== false) {
          throw new Error(`expected workspace switch to reset mobile prompt detail view, got ${editor.showMobilePromptDetailView}`);
        }

        editor.activeWorkspace = 'prompts';
        editor.showMobilePromptDetailView = true;
        editor.closeEditor();
        if (editor.showMobilePromptDetailView !== false) {
          throw new Error(`expected closeEditor to reset mobile prompt detail view, got ${editor.showMobilePromptDetailView}`);
        }
        """
    )


def test_preset_editor_template_exposes_specialized_editor_sections():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')
    select_block = source.split('<template x-if="activeItem?.editor?.kind === \'select\'">', 1)[1].split(
        '<template x-if="activeItem?.editor?.kind === \'text\'">', 1
    )[0]

    assert (
        "item.editor?.kind === 'prompt-item'" not in source
        and "activeItem?.editor?.kind === 'prompt-item'" not in source
    )
    assert (
        "item.editor?.kind === 'sortable-string-list'" in source
        or "activeItem?.editor?.kind === 'sortable-string-list'" in source
    )
    assert (
        "item.editor?.kind === 'string-list'" in source
        or "activeItem?.editor?.kind === 'string-list'" in source
    )
    assert (
        "item.editor?.kind === 'key-value-list'" in source
        or "activeItem?.editor?.kind === 'key-value-list'" in source
    )
    assert "activeItem?.editor?.kind === 'select'" in source
    assert 'x-for="option in (activeItem?.editor?.options || [])"' in source
    assert 'resolveSelectOptionValue(activeItem, $event.target.value)' in source
    assert ':value="option.value ?? option"' in source
    assert 'x-text="option.label ?? option"' in source
    assert re.search(
        r'<template x-if="activeItem\?\.editor\?\.kind === \'select\'">[\s\S]*?<select[\s\S]*?</select>',
        source,
    )
    assert '<input\n                            type="text"' not in select_block
    assert '高级原始编辑区' not in source


def test_preset_editor_runtime_preserves_select_option_value_types():
    run_preset_editor_runtime_check(
        """
        editor.editingData = {
          temperature_mode: 0,
          feature_enabled: false,
          plain_mode: 'alpha',
        };

        const numericItem = {
          key: 'temperature_mode',
          editor: {
            kind: 'select',
            options: [
              { value: 0, label: 'Zero' },
              { value: 1, label: 'One' },
            ],
          },
        };
        const booleanItem = {
          key: 'feature_enabled',
          editor: {
            kind: 'select',
            options: [
              { value: false, label: 'Off' },
              { value: true, label: 'On' },
            ],
          },
        };
        const primitiveItem = {
          key: 'plain_mode',
          editor: {
            kind: 'select',
            options: ['alpha', 'beta'],
          },
        };

        editor.setFieldValue(numericItem, editor.resolveSelectOptionValue(numericItem, '1'));
        if (editor.editingData.temperature_mode !== 1 || typeof editor.editingData.temperature_mode !== 'number') {
          throw new Error(`expected numeric select value type to persist, got ${JSON.stringify(editor.editingData.temperature_mode)} (${typeof editor.editingData.temperature_mode})`);
        }

        editor.setFieldValue(booleanItem, editor.resolveSelectOptionValue(booleanItem, 'true'));
        if (editor.editingData.feature_enabled !== true || typeof editor.editingData.feature_enabled !== 'boolean') {
          throw new Error(`expected boolean select value type to persist, got ${JSON.stringify(editor.editingData.feature_enabled)} (${typeof editor.editingData.feature_enabled})`);
        }

        editor.setFieldValue(primitiveItem, editor.resolveSelectOptionValue(primitiveItem, 'beta'));
        if (editor.editingData.plain_mode !== 'beta' || typeof editor.editingData.plain_mode !== 'string') {
          throw new Error(`expected primitive string option to stay string, got ${JSON.stringify(editor.editingData.plain_mode)} (${typeof editor.editingData.plain_mode})`);
        }
        """
    )


def test_preset_editor_template_avoids_mixing_x_if_and_x_for_on_specialized_editor_templates():
    source = read_project_file('templates/modals/detail_preset_fullscreen.html')

    assert "<template x-if=\"item.editor?.kind === 'prompt-item'\" x-for=" not in source
    assert "<template x-if=\"item.editor?.kind === 'sortable-string-list'\" x-for=" not in source
    assert "<template x-if=\"item.editor?.kind === 'string-list'\" x-for=" not in source
    assert "<template x-if=\"item.editor?.kind === 'key-value-list'\" x-for=" not in source
