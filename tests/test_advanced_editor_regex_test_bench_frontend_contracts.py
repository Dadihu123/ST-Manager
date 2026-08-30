import json
from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def run_regex_test_bench_runtime_check(script_body: str) -> None:
    source_path = (ROOT / 'static/js/utils/regexTestBench.js').resolve()
    node_script = textwrap.dedent(
        f'''
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        const source = readFileSync(sourcePath, 'utf8');
        const module = await import(
          'data:text/javascript,' + encodeURIComponent(source),
        );

        {textwrap.dedent(script_body)}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def run_advanced_editor_runtime_check(script_body: str) -> None:
    source_path = ROOT / 'static/js/components/advancedEditor.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function advancedEditor()', 'function advancedEditor()');

        const stubs = `
        class ManagerScriptRuntime {{
          constructor(options = {{}}) {{
            this.options = options;
          }}
          mount() {{}}
          stop() {{}}
          updateData() {{}}
          updateButtons() {{}}
          setContext() {{}}
        }}
        const subscribeRuntimeManager = () => () => {{}};
        const updateShadowContent = () => {{}};
        const updateMixedPreviewContent = () => {{}};
        const regexErrorMessage = 'Invalid regular expression: Unterminated group';
        const applyDisplayRules = () => {{
          throw new Error(regexErrorMessage);
        }};
        const runRegexTestBenchScript = () => {{
          throw new Error(regexErrorMessage);
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default advancedEditor;'),
        );
        const component = module.default();

        {textwrap.dedent(script_body)}
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_regex_test_bench_plain_patterns_are_not_global_by_default():
    script_body = textwrap.dedent(
        '''
        const output = module.runRegexTestBenchScript(
          {
            findRegex: 'foo',
            replaceString: 'X',
            trimStrings: [],
            substituteRegex: 0,
          },
          'foo foo',
        );

        if (output !== 'X foo') {
          throw new Error(`expected plain pattern to replace once, got ${output}`);
        }
        '''
    )

    run_regex_test_bench_runtime_check(script_body)


def test_regex_test_bench_ignores_runtime_filter_fields():
    script_body = textwrap.dedent(
        '''
        const output = module.runRegexTestBenchScript(
          {
            findRegex: 'foo',
            replaceString: 'bar',
            trimStrings: [],
            substituteRegex: 0,
            disabled: true,
            markdownOnly: true,
            promptOnly: true,
            runOnEdit: false,
            placement: [1],
            minDepth: 10,
            maxDepth: 0,
          },
          'foo',
        );

        if (output !== 'bar') {
          throw new Error(`expected test bench to ignore runtime filters, got ${output}`);
        }
        '''
    )

    run_regex_test_bench_runtime_check(script_body)


def test_regex_test_bench_expands_groups_match_and_trim_strings():
    script_body = textwrap.dedent(
        '''
        const output = module.runRegexTestBenchScript(
          {
            findRegex: '/^(hello) (?<target>world)$/',
            replaceString: '[$0][$1][$<target>][{{match}}]',
            trimStrings: ['l'],
            substituteRegex: 0,
          },
          'hello world',
        );

        if (output !== '[heo word][heo][world][heo word]') {
          throw new Error(`unexpected replacement output: ${output}`);
        }
        '''
    )

    run_regex_test_bench_runtime_check(script_body)


def test_regex_test_bench_supports_raw_and_escaped_macro_substitution():
    script_body = textwrap.dedent(
        '''
        const rawSource = module.resolveRegexTestBenchFindSource(
          {
            findRegex: '{{needle}}+',
            substituteRegex: 1,
          },
          { needle: 'ab' },
        );
        if (rawSource !== 'ab+') {
          throw new Error(`expected raw macro expansion, got ${rawSource}`);
        }

        const escapedSource = module.resolveRegexTestBenchFindSource(
          {
            findRegex: '{{needle}}+',
            substituteRegex: 2,
          },
          { needle: 'a.b' },
        );
        if (escapedSource !== 'a\\\\.b+') {
          throw new Error(`expected escaped macro expansion, got ${escapedSource}`);
        }

        const output = module.runRegexTestBenchScript(
          {
            findRegex: '{{needle}}',
            replaceString: 'X',
            trimStrings: [],
            substituteRegex: 2,
          },
          'a.b',
          {
            macroContext: {
              needle: 'a.b',
            },
          },
        );

        if (output !== 'X') {
          throw new Error(`expected escaped macro match, got ${output}`);
        }
        '''
    )

    run_regex_test_bench_runtime_check(script_body)


def test_advanced_editor_run_regex_test_formats_regex_errors():
    script_body = textwrap.dedent(
        '''
        component.editingData = {
          extensions: {
            regex_scripts: [{
              findRegex: '/(/',
              replaceString: 'X',
              trimStrings: [],
            }],
          },
        };
        component.activeRegexIndex = 0;
        component.regexTestInput = 'foo';
        component.regexTestResult = '';

        component.runRegexTest();

        if (!component.regexTestResult.startsWith('正则表达式错误: ')) {
          throw new Error(`missing user-facing error prefix: ${component.regexTestResult}`);
        }

        if (component.regexTestResultIcon !== 'close') {
          throw new Error(`missing SVG error icon: ${component.regexTestResultIcon}`);
        }

        if (!component.regexTestResult.includes('Invalid regular expression: Unterminated group')) {
          throw new Error(`missing regex error details: ${component.regexTestResult}`);
        }
        '''
    )

    run_advanced_editor_runtime_check(script_body)


def test_advanced_editor_runtime_tracks_buffered_mode_and_dispatches_apply_and_persist_events():
    script_body = textwrap.dedent(
        '''
        const events = [];
        const listeners = {};
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = handler;
          },
          removeEventListener() {},
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };

        component.$store = { global: { deviceType: 'desktop', showToast() {} } };
        component.$nextTick = (fn) => { if (typeof fn === 'function') fn(); };
        component.$watch = () => {};
        component.mountScriptRuntimeHost = () => {};
        component.syncRuntimeContext = () => {};
        component.getTavernScripts = () => [];
        component._normalizeScript = () => {};
        component.init();

        listeners['open-advanced-editor']({
          detail: {
            extensions: {
              regex_scripts: [{ scriptName: 'alpha' }],
              tavern_helper: { scripts: [] },
            },
            editorCommitMode: 'buffered',
            showPersistButton: true,
          },
        });

        if (component.isFileMode !== false) {
          throw new Error('expected buffered editor open to stay out of file mode');
        }
        if (component.showPersistButton !== true) {
          throw new Error(`expected buffered editor to expose persist button, got ${component.showPersistButton}`);
        }

        component.applyChangesAndClose();
        if (events[0]?.type !== 'advanced-editor-apply') {
          throw new Error(`expected apply event, got ${events[0]?.type}`);
        }
        if (component.showAdvancedModal !== false) {
          throw new Error('expected apply to close advanced modal');
        }

        component.showAdvancedModal = true;
        component.persistChanges();
        if (events[1]?.type !== 'advanced-editor-persist') {
          throw new Error(`expected persist event, got ${events[1]?.type}`);
        }
        if (component.showAdvancedModal !== true) {
          throw new Error('expected persist to keep advanced modal open until save succeeds');
        }

        listeners['advanced-editor-close']();
        if (component.showAdvancedModal !== false) {
          throw new Error('expected advanced-editor-close acknowledgement to close modal');
        }
        '''
    )

    run_advanced_editor_runtime_check(script_body)


def test_advanced_editor_runtime_blocks_unmanaged_close_paths_while_buffered_persist_is_pending():
    script_body = textwrap.dedent(
        '''
        const listeners = {};
        const events = [];
        globalThis.window = {
          addEventListener(type, handler) {
            listeners[type] = handler;
          },
          removeEventListener() {},
          dispatchEvent(event) {
            events.push(event);
            return true;
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) {
            this.type = type;
            this.detail = init.detail;
          }
        };

        component.$store = { global: { deviceType: 'desktop', showToast() {} } };
        component.$nextTick = (fn) => { if (typeof fn === 'function') fn(); };
        component.$watch = () => {};
        component.mountScriptRuntimeHost = () => {};
        component.syncRuntimeContext = () => {};
        component.getTavernScripts = () => [];
        component._normalizeScript = () => {};
        component.init();

        listeners['open-advanced-editor']({
          detail: {
            extensions: {
              regex_scripts: [{ scriptName: 'alpha' }],
              tavern_helper: { scripts: [] },
            },
            editorCommitMode: 'buffered',
            showPersistButton: true,
          },
        });

        component.requestClose();
        if (component.showAdvancedModal !== false) {
          throw new Error('expected buffered mode requestClose to close normally before persist starts');
        }

        listeners['open-advanced-editor']({
          detail: {
            extensions: {
              regex_scripts: [{ scriptName: 'alpha' }],
              tavern_helper: { scripts: [] },
            },
            editorCommitMode: 'buffered',
            showPersistButton: true,
          },
        });

        component.persistChanges();
        if (events[0]?.type !== 'advanced-editor-persist') {
          throw new Error(`expected persist event before close gating, got ${events[0]?.type}`);
        }

        component.requestClose();
        if (component.showAdvancedModal !== true) {
          throw new Error('expected buffered mode requestClose to stay blocked while persist is pending');
        }

        listeners['advanced-editor-close']();
        if (component.showAdvancedModal !== false) {
          throw new Error('expected advanced-editor-close acknowledgement to bypass buffered close gate');
        }

        listeners['open-script-file-editor']({
          detail: {
            fileData: { scriptName: 'file-alpha' },
            filePath: 'extensions/alpha.json',
            type: 'regex',
          },
        });

        component.requestClose();
        if (component.showAdvancedModal !== false) {
          throw new Error('expected file mode requestClose to remain unmanaged and close immediately');
        }
        '''
    )

    run_advanced_editor_runtime_check(script_body)


def test_advanced_editor_template_keeps_modal_shell_transparent_while_preserving_split_panels():
    template = (ROOT / 'templates/modals/advanced_editor.html').read_text(encoding='utf-8')
    modal_css = (ROOT / 'static/css/modules/components.css').read_text(encoding='utf-8')
    advanced_modal_css = (ROOT / 'static/css/modules/modal-tools.css').read_text(encoding='utf-8')

    assert 'class="modal-container advanced-editor-container ui-modal-shell"' in template
    assert 'background: var(--bg-panel);' not in template
    assert 'border: 1px solid var(--border-default);' not in template
    assert 'class="adv-list-pane custom-scrollbar overflow-y-auto"' in template
    assert 'class="adv-editor-pane custom-scrollbar"' in template
    assert re.search(
        r'\.modal-container\s*\{[^}]*background:\s*var\(--surface-container\);',
        modal_css,
        re.DOTALL,
    )
    assert re.search(
        r'\.modal-container\.advanced-editor-container\s*\{[^}]*background:\s*transparent;',
        advanced_modal_css,
        re.DOTALL,
    )
