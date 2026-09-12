import json
from pathlib import Path
import re
import subprocess
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


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
        let __sendPresetToSillyTavernImpl = async () => ({{ success: true, last_sent_to_st: 0 }});
        const sendPresetToSillyTavern = (...args) => __sendPresetToSillyTavernImpl(...args);
        globalThis.__setSendPresetToSillyTavern = (fn) => {{
          __sendPresetToSillyTavernImpl = fn;
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
        const createMarqueeSelection = () => ({{
          initMarqueeSelection() {{}},
        }});
        const downloadFileFromApi = async () => {{}};
        globalThis.window = {{
          __listeners: {{}},
          addEventListener(type, handler) {{
            this.__listeners[type] = this.__listeners[type] || [];
            this.__listeners[type].push(handler);
          }},
          removeEventListener(type, handler) {{
            this.__listeners[type] = (this.__listeners[type] || []).filter((entry) => entry !== handler);
          }},
          dispatchEvent(event) {{
            (this.__listeners[event.type] || []).forEach((handler) => handler(event));
            return true;
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
        grid.$watch = () => {{}};
        grid.$store = {{
          global: {{
            currentMode: 'cards',
            presetFilterType: 'all',
            presetFilterCategory: '',
            presetList: [],
            viewState: {{
              selectedIds: [],
              lastSelectedId: '',
              draggedCards: [],
            }},
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


def test_presets_api_exposes_send_to_sillytavern_helper_contract():
    source = read_project_file('static/js/api/presets.js')

    assert 'export async function sendPresetToSillyTavern(payload) {' in source
    assert 'fetch("/api/presets/send_to_st", {' in source or "fetch('/api/presets/send_to_st', {" in source
    assert 'method: "POST"' in source or "method: 'POST'" in source
    assert 'body: JSON.stringify(payload || {})' in source
    assert 'return res.json()' in source
    assert '/api/presets/send-to-sillytavern' not in source


def test_preset_grid_js_exposes_send_to_st_state_methods_and_alt_root_guard_contracts():
    source = read_project_file('static/js/components/presetGrid.js')
    can_send_block = extract_js_function_block(source, 'canSendPresetToST(item) {')

    assert 'sendPresetToSillyTavern,' in source
    assert 'sendingPresetToStIds:' in source
    assert 'canSendPresetToST(item) {' in source
    assert 'return item?.preset_kind === "openai"' in can_send_block or "return item?.preset_kind === 'openai'" in can_send_block
    assert 'isSendingPresetToST(itemId) {' in source
    assert 'getPresetSendToSTTitle(item) {' in source
    assert 'applyPresetSentState(detail) {' in source
    assert 'window.addEventListener("preset-sent-to-st"' in source or "window.addEventListener('preset-sent-to-st'" in source
    assert 'async sendPresetToST(item, event = null) {' in source
    assert 'detail.last_sent_to_st' in source

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


def test_preset_grid_template_exposes_send_button_title_and_visibility_contracts():
    source = read_project_file('templates/components/grid_presets.html')

    assert '@click.stop="sendPresetToST(item, $event)"' in source
    assert ':title="getPresetSendToSTTitle(item)"' in source
    assert 'x-show="canSendPresetToST(item)"' in source
    assert 'class="card-send-st-btn"' in source


def test_preset_grid_runtime_tracks_shared_send_state_events_for_duplicate_prevention():
    run_preset_grid_runtime_check(
        """
        grid.init();

        window.dispatchEvent(new CustomEvent('preset-send-to-st-pending', {
          detail: { id: 'preset-1', sending: true },
        }));
        if (!grid.isSendingPresetToST('preset-1')) {
          throw new Error('expected shared pending event to mark preset as sending in grid');
        }

        window.dispatchEvent(new CustomEvent('preset-send-to-st-finished', {
          detail: { id: 'preset-1' },
        }));
        if (grid.isSendingPresetToST('preset-1')) {
          throw new Error('expected shared finished event to clear sending state in grid');
        }
        """
    )


def test_preset_grid_runtime_send_family_item_uses_default_version_id_for_request_and_sent_state():
    run_preset_grid_runtime_check(
        """
        const sendCalls = [];
        const events = [];
        globalThis.__setSendPresetToSillyTavern(async (payload) => {
          sendCalls.push(payload);
          return { success: true, last_sent_to_st: 456.5 };
        });
        window.dispatchEvent = (event) => {
          (window.__listeners[event.type] || []).forEach((handler) => handler(event));
          events.push(event);
          return true;
        };

        grid.init();
        grid.items = [{
          id: 'global::global::family-alpha',
          entry_type: 'family',
          default_version_id: 'global::companion-v1.json',
          preset_kind: 'openai',
          last_sent_to_st: 0,
          versions: [
            { id: 'global::companion-v1.json', preset_version: { is_default_version: true } },
          ],
        }];
        grid.$store.global.presetList = JSON.parse(JSON.stringify(grid.items));

        await grid.sendPresetToST(grid.items[0]);

        if (sendCalls.length !== 1 || sendCalls[0].id !== 'global::companion-v1.json') {
          throw new Error(`expected family send to target default_version_id, got ${JSON.stringify(sendCalls)}`);
        }
        if (Number(grid.items[0].last_sent_to_st || 0) !== 456.5) {
          throw new Error(`expected family item timestamp to update, got ${grid.items[0].last_sent_to_st}`);
        }

        const sentEvent = events.find((event) => event.type === 'preset-sent-to-st');
        if (!sentEvent || sentEvent.detail?.id !== 'global::companion-v1.json') {
          throw new Error(`expected sent event to carry concrete default version id, got ${JSON.stringify(sentEvent?.detail || null)}`);
        }
        """
    )


def test_preset_grid_runtime_hides_send_for_alt_root_family_items():
    run_preset_grid_runtime_check(
        """
        grid.items = [{
          id: 'global::st_openai_preset_dir::alt-root-family',
          entry_type: 'family',
          root_scope_key: 'st_openai_preset_dir',
          default_version_id: 'global-alt::st_openai_preset_dir::OpenAI/chat-v1.json',
          preset_kind: 'openai',
          last_sent_to_st: 0,
        }];

        if (grid.canSendPresetToST(grid.items[0])) {
          throw new Error('expected alt-root family item to hide send action');
        }
        """
    )


def test_preset_grid_runtime_allows_send_for_openai_list_item_with_kind_metadata():
    run_preset_grid_runtime_check(
        """
        grid.items = [{
          id: 'global::OpenAI/chat.json',
          entry_type: 'preset',
          source_folder: null,
          preset_kind: 'openai',
          preset_kind_label: 'ST 聊天补全预设',
          last_sent_to_st: 0,
        }];

        if (!grid.canSendPresetToST(grid.items[0])) {
          throw new Error('expected openai list item with preset_kind metadata to remain sendable');
        }
        """
    )
