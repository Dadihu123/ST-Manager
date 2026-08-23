import json
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def run_node(script_body):
    module_path = PROJECT_ROOT / "static/js/components/pasteImportHandler.js"
    node_script = textwrap.dedent(
        f"""
        import {{ pathToFileURL }} from 'node:url';

        const module = await import(pathToFileURL({json.dumps(str(module_path))}).href);

        function fakeFile(name, content = '', type = '') {{
          return {{
            name,
            type,
            async text() {{
              return content;
            }},
          }};
        }}

        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};

        {textwrap.dedent(script_body)}
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_app_initializes_paste_import_handler():
    source = read_project_file("static/js/app.js")

    assert 'import { initPasteImportHandler } from "./components/pasteImportHandler.js";' in source
    assert "initPasteImportHandler();" in source


def test_import_modal_prefills_url_from_open_event():
    source = read_project_file("static/js/components/importModal.js")

    assert "e.detail && e.detail.url ? e.detail.url : ''" in source


def test_grid_components_expose_paste_upload_entrypoints():
    card_grid = read_project_file("static/js/components/cardGrid.js")
    extension_grid = read_project_file("static/js/components/extensionGrid.js")
    chat_grid = read_project_file("static/js/components/chatGrid.js")
    wi_grid = read_project_file("static/js/components/wiGrid.js")
    preset_grid = read_project_file("static/js/components/presetGrid.js")

    assert "window.stUploadCardFiles" in card_grid
    assert "this._uploadFilesInternal(files)" in card_grid
    assert "window.stUploadExtensionFiles" in extension_grid
    assert "this._uploadExtensionsFiles(files, targetType || this.currentMode)" in extension_grid
    assert "window.stUploadChatFiles" in chat_grid
    assert "window.stUploadWorldInfoFiles" in wi_grid
    assert "window.stUploadPresetFiles" in preset_grid


def test_url_paste_dispatches_prefilled_import_event_and_prevents_default():
    run_node(
        """
        const dispatched = [];
        globalThis.window = {
          Alpine: {
            store(name) {
              return { viewState: { filterCategory: '角色/默认' } };
            },
          },
          dispatchEvent(event) {
            dispatched.push(event);
            return true;
          },
          alert() {},
        };

        let prevented = false;
        const handled = await module.handlePasteImport({
          target: { closest() { return false; } },
          clipboardData: {
            files: [],
            getData(type) {
              return type === 'text/plain' ? 'https://example.com/card.png' : '';
            },
          },
          preventDefault() { prevented = true; },
        });

        if (!handled || !prevented) throw new Error('URL paste should be handled');
        if (dispatched.length !== 1 || dispatched[0].type !== 'open-import-url') {
          throw new Error(`unexpected events: ${JSON.stringify(dispatched)}`);
        }
        if (dispatched[0].detail.url !== 'https://example.com/card.png') {
          throw new Error('missing pasted URL in import event');
        }
        if (dispatched[0].detail.category !== '角色/默认') {
          throw new Error('missing current category in import event');
        }
        """
    )


def test_paste_handler_does_not_intercept_editable_targets():
    run_node(
        """
        globalThis.window = {
          dispatchEvent() { throw new Error('should not dispatch from editable target'); },
          alert() {},
        };

        let prevented = false;
        const handled = await module.handlePasteImport({
          target: { closest(selector) { return selector.includes('textarea'); } },
          clipboardData: {
            files: [],
            getData() { return 'https://example.com/card.png'; },
          },
          preventDefault() { prevented = true; },
        });

        if (handled || prevented) {
          throw new Error('editable paste should pass through untouched');
        }
        """
    )


def test_file_classification_and_dispatch_group_by_resource_type():
    run_node(
        """
        const files = [
          fakeFile('hero.png', '', 'image/png'),
          fakeFile('book.json', JSON.stringify({ entries: { one: { keys: ['a'], content: 'b' } } })),
          fakeFile('preset.json', JSON.stringify({ temperature: 0.7, prompts: [] })),
          fakeFile('regex.json', JSON.stringify({ findRegex: '/a/' })),
          fakeFile('script.json', JSON.stringify({ type: 'script', scripts: [] })),
          fakeFile('quick.json', JSON.stringify({ qrList: [] })),
          fakeFile('chat.jsonl', '{}\\n'),
        ];

        const groups = await module.classifyFiles(files);
        if (groups.card.map((f) => f.name).join(',') !== 'hero.png') {
          throw new Error(`bad card group: ${groups.card.map((f) => f.name)}`);
        }
        if (groups.worldinfo.map((f) => f.name).join(',') !== 'book.json') {
          throw new Error('bad worldinfo group');
        }
        if (groups.preset.map((f) => f.name).join(',') !== 'preset.json') {
          throw new Error('bad preset group');
        }
        if (groups.extension.regex.map((f) => f.name).join(',') !== 'regex.json') {
          throw new Error('bad regex group');
        }
        if (groups.extension.scripts.map((f) => f.name).join(',') !== 'script.json') {
          throw new Error('bad script group');
        }
        if (groups.extension.quick_replies.map((f) => f.name).join(',') !== 'quick.json') {
          throw new Error('bad quick reply group');
        }
        if (groups.chat.map((f) => f.name).join(',') !== 'chat.jsonl') {
          throw new Error('bad chat group');
        }

        const calls = [];
        globalThis.window = {
          stUploadCardFiles(files) { calls.push(['card', files.map((f) => f.name)]); },
          stUploadWorldInfoFiles(files) { calls.push(['worldinfo', files.map((f) => f.name)]); },
          stUploadPresetFiles(files) { calls.push(['preset', files.map((f) => f.name)]); },
          stUploadChatFiles(files) { calls.push(['chat', files.map((f) => f.name)]); },
          stUploadExtensionFiles(files, targetType) {
            calls.push([`extension:${targetType}`, files.map((f) => f.name)]);
          },
          alert() {},
        };

        const dispatched = module.dispatchImportGroups(groups);
        if (dispatched !== files.length) {
          throw new Error(`expected ${files.length} dispatched files, got ${dispatched}`);
        }

        const labels = calls.map((call) => call[0]).sort().join('|');
        const expected = 'card|chat|extension:quick_replies|extension:regex|extension:scripts|preset|worldinfo';
        if (labels !== expected) {
          throw new Error(`unexpected dispatch labels: ${labels}`);
        }
        """
    )


def test_unknown_files_are_reported_without_uploading():
    run_node(
        """
        const groups = await module.classifyFiles([
          fakeFile('notes.txt', 'hello'),
          fakeFile('bad.json', '{not json'),
        ]);
        if (groups.unknown.length !== 2) {
          throw new Error(`expected two unknown files, got ${groups.unknown.length}`);
        }

        const alerts = [];
        globalThis.window = {
          stUploadCardFiles() { throw new Error('unknown files should not upload'); },
          alert(message) { alerts.push(message); },
        };
        const dispatched = module.dispatchImportGroups(groups);
        module.showPasteImportSummary(groups, dispatched);

        if (dispatched !== 0) throw new Error('unknown files should not dispatch');
        if (alerts.length !== 1 || !alerts[0].includes('notes.txt') || !alerts[0].includes('bad.json')) {
          throw new Error(`missing unknown file alert: ${alerts.join('\\n')}`);
        }
        """
    )
