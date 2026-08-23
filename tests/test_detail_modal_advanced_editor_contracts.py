import json
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_detail_modal_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/detailModal.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function detailModal()', 'function detailModal()');

        const stubs = `
        const getCardDetail = async () => ({{ success: true, card: {{}} }});
        const updateCard = async () => ({{ success: true }});
        const previewMergedTags = async () => ({{ success: true }});
        const updateCardFile = async () => ({{ success: true }});
        const updateCardFileFromUrl = async () => ({{ success: true }});
        const changeCardImage = async () => ({{ success: true }});
        const getCardMetadata = async () => ({{ success: true }});
        const sendToSillyTavern = async () => ({{ success: true }});
        const apiSetAsBundleCover = async () => ({{ success: true }});
        const apiConvertToBundle = async () => ({{ success: true }});
        const apiToggleBundleMode = async () => ({{ success: true }});
        const listChats = async () => ({{ success: true, items: [] }});
        const renameFolder = async () => ({{ success: true }});
        const performSystemAction = async () => ({{ success: true }});
        const readFileContent = async () => ({{ success: true }});
        const setSkinAsCover = async () => ({{ success: true }});
        const deleteResourceFile = async (payload) => globalThis.__deleteResourceFile
          ? globalThis.__deleteResourceFile(payload)
          : ({{ success: true }});
        const uploadCardResource = async () => ({{ success: true }});
        const uploadNoteImage = async (formData) => globalThis.__uploadNoteImage
          ? globalThis.__uploadNoteImage(formData)
          : ({{ success: true, url: '/uploads/default.png' }});
        const listResourceFiles = async () => ({{ success: true, files: [] }});
        const apiSetResourceFolder = async () => ({{ success: true }});
        const apiOpenResourceFolder = async () => ({{ success: true }});
        const apiCreateResourceFolder = async () => ({{ success: true }});
        const getCleanedV3Data = (data) => JSON.parse(JSON.stringify(data || {{}}));
        const updateWiKeys = () => {{}};
        const toStV3Worldbook = (value) => value;
        const formatDate = (value) => value;
        const getVersionName = (value) => value;
        const estimateTokens = () => 0;
        const formatWiKeys = (value) => value;
        const getTopbarTokenLevelClass = () => '';
        const updateShadowContent = () => {{}};
        const insertAtCursor = (textarea, myValue) => {{
          if (textarea.selectionStart || textarea.selectionStart == '0') {{
            const startPos = textarea.selectionStart;
            const endPos = textarea.selectionEnd;
            return textarea.value.substring(0, startPos) + myValue + textarea.value.substring(endPos, textarea.value.length);
          }}
          return textarea.value + myValue;
        }};
        const renderUnifiedPreviewHost = () => '';
        const updateMixedPreviewContent = () => '';
        const createAutoSaver = () => ({{ stop() {{}}, initBaseline() {{}}, start() {{}} }});
        const wiHelpers = {{}};
        const clearActiveRuntimeContext = () => {{}};
        const setActiveRuntimeContext = () => {{}};
        const matchAnyTagSearchToken = () => true;
        const splitTagTokens = () => [];
        globalThis.alert = () => {{}};
        globalThis.confirm = () => true;
        globalThis.prompt = () => '';
        globalThis.window = {{
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{ return true; }},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(name, options = {{}}) {{
            this.type = name;
            this.detail = options.detail;
          }}
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default detailModal;'),
        );
        const modal = module.default();
        modal.$nextTick = (fn) => {{ if (typeof fn === 'function') fn(); }};

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


def test_detail_modal_runtime_whitespace_only_fields_do_not_count_as_view_content():
    run_detail_modal_runtime_check(
        """
        modal.isEditMode = false;
        modal.tab = 'dialog';
        modal.editingData = {
          description: '\\r\\n',
          first_mes: '\\r\\n',
          mes_example: '   ',
          personality: '\\n',
          scenario: '   ',
          creator_notes: '',
          system_prompt: '\\t',
          post_history_instructions: '',
          alternate_greetings: ['\\n', '   ', ''],
        };

        if (typeof modal.hasTextValue !== 'function') {
          throw new Error('expected hasTextValue helper');
        }
        if (modal.hasTextValue('\\r\\n') !== false) {
          throw new Error('expected whitespace-only text to be empty');
        }
        if (modal.hasPersonaFields !== false) {
          throw new Error('expected whitespace-only persona fields to hide the persona tab');
        }
        if (modal.hasDialogFields !== false) {
          throw new Error('expected whitespace-only dialog fields to hide the dialog tab');
        }

        modal.toggleEditMode();
        if (modal.isEditMode !== true) {
          throw new Error('expected toggleEditMode to enter edit mode');
        }
        if (modal.hasPersonaFields !== true || modal.hasDialogFields !== true) {
          throw new Error('expected edit mode to keep editable tabs visible');
        }

        modal.toggleEditMode();
        if (modal.isEditMode !== false) {
          throw new Error('expected toggleEditMode to return to view mode');
        }
        if (modal.tab !== 'basic') {
          throw new Error(`expected empty active dialog tab to fall back to basic, got ${modal.tab}`);
        }

        modal.editingData.first_mes = 'Hello';
        if (modal.hasDialogFields !== true) {
          throw new Error('expected non-empty first_mes to show the dialog tab');
        }
        modal.editingData.first_mes = '';
        modal.editingData.alternate_greetings = ['  Alternate  '];
        if (modal.hasDialogFields !== true) {
          throw new Error('expected non-empty alternate greeting to show the dialog tab');
        }
        """
    )


def test_detail_modal_formats_source_update_times_with_explicit_empty_states():
    run_detail_modal_runtime_check(
        """
        modal.activeCard = {
          source_update: {
            first_message_edited_at: 1704067200,
            first_message_timestamp: 1704067100,
            last_checked_at: 1704067300,
          },
        };
        if (modal.formatSourceFirstMessageEditedAt() !== 1704067200) {
          throw new Error('expected the first message edit timestamp to be formatted');
        }
        if (modal.formatSourceUpdateCheckedAt() !== 1704067300) {
          throw new Error('expected the source check timestamp to be formatted');
        }

        modal.activeCard.source_update = {
          first_message_timestamp: 1704067100,
        };
        if (modal.formatSourceFirstMessageEditedAt() !== '未编辑过') {
          throw new Error('expected an available but never-edited starter message to be labeled');
        }
        if (modal.formatSourceUpdateCheckedAt() !== '未检查') {
          throw new Error('expected a missing check timestamp to be labeled');
        }

        modal.activeCard.source_update = {};
        if (modal.formatSourceFirstMessageEditedAt() !== '未取得') {
          throw new Error('expected a missing starter message timestamp to be labeled');
        }
        """
    )


def test_detail_template_uses_trimmed_visibility_for_empty_readonly_text_cards():
    template = (PROJECT_ROOT / 'templates/modals/detail_card.html').read_text(encoding='utf-8')

    assert 'x-show="hasDialogFields"' in template
    assert '@click="toggleEditMode()"' in template
    assert 'x-show="tab===\'dialog\' && hasDialogFields"' in template
    assert 'x-show="isEditMode || hasTextValue(editingData.description)"' in template
    assert 'x-show="!isEditMode && hasTextValue(editingData.description)"' in template
    assert 'x-if="isEditMode || hasTextValue(editingData.personality)"' in template
    assert 'x-if="isEditMode || hasTextValue(editingData.scenario)"' in template
    assert 'x-if="isEditMode || hasTextValue(editingData.creator_notes)"' in template
    assert 'x-if="isEditMode || hasTextValue(editingData.system_prompt)"' in template
    assert 'x-if="isEditMode || hasTextValue(editingData.post_history_instructions)"' in template
    assert 'dialogPage === \'greeting\' && hasGreetingPage' in template
    assert 'dialogPage === \'example\' && (isEditMode || hasTextValue(editingData.mes_example))' in template
    assert 'x-show="shouldShowDialogPageNav"' in template
    assert template.count('detail-dialog-page-nav--inline') == 2
    assert template.count('detail-dialog-card-head') == 2
    assert '@click="moveDialogPage(-1)"' in template
    assert '@click="moveDialogPage(1)"' in template
    assert 'class="detail-greeting-card"' in template
    assert "@click=\"selectGreeting('default')\"" in template
    assert '@click="handleAltCardClick($event, item.index)"' in template
    assert '@click="addAlt()"' in template
    assert '@click="removeSelectedAlternate()"' in template
    assert 'detail-greeting-manage--side' in template
    assert '@click="promoteSelectedAlternate()"' not in template
    assert '@click="moveAlternateGreeting(item.index, -1)"' not in template
    assert '@click="moveAlternateGreeting(item.index, 1)"' not in template
    assert 'showFirstPreview' not in template


def test_detail_modal_runtime_dialog_pages_and_greeting_management_are_semantic():
    run_detail_modal_runtime_check(
        """
        modal.isEditMode = false;
        modal.dialogPage = 'greeting';
        modal.selectedGreetingKind = 'default';
        modal.altIdx = 0;
        modal.editingData = {
          first_mes: '',
          mes_example: '',
          alternate_greetings: ['', '备用一', '备用二'],
        };

        modal.syncDialogState({ preferGreeting: true });
        if (modal.dialogPages.length !== 1 || modal.dialogPages[0] !== 'greeting') {
          throw new Error('expected alternate-only card to expose just the greeting page');
        }
        if (modal.selectedGreetingKind !== 'alternate' || modal.altIdx !== 1) {
          throw new Error('expected first non-empty alternate greeting to become the read selection');
        }
        if (modal.selectedGreetingContent !== '备用一') {
          throw new Error('expected selected alternate content to be previewed');
        }
        if (modal.shouldShowDialogPageNav) {
          throw new Error('expected no page navigation without a message example');
        }

        modal.editingData.mes_example = '示例对话';
        modal.syncDialogState();
        if (modal.dialogPageCount !== 2 || !modal.shouldShowDialogPageNav) {
          throw new Error('expected a second page when the message example exists');
        }
        modal.moveDialogPage(1);
        if (modal.dialogPage !== 'example') {
          throw new Error('expected page navigation to open the message example');
        }

        modal.isEditMode = true;
        modal.editingData = {
          first_mes: '默认开场白',
          mes_example: '',
          alternate_greetings: ['备用一', '备用二', '备用三'],
        };
        modal.selectedGreetingKind = 'alternate';
        modal.altIdx = 1;
        modal.moveAlternateGreeting(1, -1);
        if (modal.editingData.alternate_greetings.join('|') !== '备用二|备用一|备用三') {
          throw new Error('expected alternate ordering to persist in the backing array');
        }
        if (modal.altIdx !== 0 || modal.editingData.first_mes !== '默认开场白') {
          throw new Error('expected sorting to keep the default greeting unchanged and selected alternate in sync');
        }

        modal.addAlt();
        if (modal.selectedGreetingKind !== 'alternate' || modal.altIdx !== 3) {
          throw new Error('expected add action to select a writable alternate greeting');
        }
        modal.setSelectedGreetingContent('备用四');
        modal.moveAlternateGreeting(3, -2);
        if (modal.editingData.alternate_greetings.join('|') !== '备用二|备用四|备用一|备用三') {
          throw new Error('expected alternate drag ordering to persist in the backing array');
        }
        if (modal.altIdx !== 1 || modal.displayedAlternateGreetingItems.map(item => item.position).join('|') !== '1|2|3|4') {
          throw new Error('expected alternate ordinals to follow the visible left-to-right order');
        }

        modal.isEditMode = false;
        modal.editingData = {
          first_mes: '',
          mes_example: '只有示例',
          alternate_greetings: [''],
        };
        modal.dialogPage = 'greeting';
        modal.selectedGreetingKind = 'default';
        modal.altIdx = 0;
        modal.syncDialogState();
        if (modal.dialogPage !== 'example' || modal.dialogPageCount !== 1 || modal.shouldShowDialogPageNav) {
          throw new Error('expected example-only cards to open directly without page controls');
        }
      """
    )


def test_detail_dialog_template_exposes_drag_and_touch_sort_fallbacks():
    template = (PROJECT_ROOT / 'templates/modals/detail_card.html').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static/css/modules/modal-detail.css').read_text(encoding='utf-8')

    assert '@dragstart="onAltDragStart($event, item.index)"' in template
    assert '@drop="onAltDrop($event, item.index)"' in template
    assert '@pointerdown="onAltPointerDown($event, item.index)"' in template
    assert '@pointermove="onAltPointerMove($event)"' in template
    assert '@pointerup="onAltPointerUp($event)"' in template
    assert '@keydown="onAltCardKeydown($event, item.index)"' in template
    assert 'detail-greeting-drag-handle' in template
    assert 'detail-greeting-manage--side' in template
    assert '@click="moveAlternateGreeting(item.index, -1)"' not in template
    assert '@click="moveAlternateGreeting(item.index, 1)"' not in template
    assert '@click="promoteSelectedAlternate()"' not in template
    assert '.detail-greeting-card.is-selected' in css
    assert '.detail-greeting-selector-body' in css
    assert '.detail-greeting-manage--side' in css
    assert '.detail-greeting-option.is-drop-target' in css
    assert 'transform: translateY(-7px);' in css
    assert '.detail-dialog-card-head' in css
    assert '.detail-dialog-page-nav--inline' in css
    assert 'overflow-y: auto' in css
    assert 'overflow-x: auto' in css
    assert '@media (prefers-reduced-motion: reduce)' in css


def test_detail_modal_runtime_open_advanced_editor_uses_detached_extensions_snapshot_and_buffered_mode_handlers():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'alpha' }],
            tavern_helper: { scripts: [] },
          },
        };

        modal.openAdvancedEditor();

        if (events.length !== 1 || events[0].type !== 'open-advanced-editor') {
          throw new Error(`expected open-advanced-editor event, got ${JSON.stringify(events.map((event) => event.type))}`);
        }
        if (events[0].detail.editorCommitMode !== 'buffered') {
          throw new Error(`expected buffered mode, got ${events[0].detail.editorCommitMode}`);
        }
        if (events[0].detail.showPersistButton !== true) {
          throw new Error(`expected persist button enabled, got ${events[0].detail.showPersistButton}`);
        }
        if (events[0].detail.extensions === modal.editingData.extensions) {
          throw new Error('expected detached extensions snapshot');
        }
        if (!listeners['advanced-editor-apply'] || !listeners['advanced-editor-persist']) {
          throw new Error('expected apply and persist listeners to be registered');
        }
      """
    )


def test_detail_modal_runtime_get_skin_url_encodes_nested_resource_segments():
    run_detail_modal_runtime_check(
        """
        modal.activeCard = { resource_folder: 'hero folder' };
        modal.editingData = { resource_folder: '' };

        const url = modal.getSkinUrl('poses/happy face.png');

        if (url !== '/resources_file/hero%20folder/poses/happy%20face.png') {
          throw new Error(`expected nested path segments to remain routable, got ${url}`);
        }
      """
    )


def test_detail_modal_runtime_skin_directory_items_navigate_and_select_by_path():
    run_detail_modal_runtime_check(
        """
        modal.activeCard = { resource_folder: 'hero' };
        modal.editingData = { resource_folder: 'hero' };
        modal.skinImages = ['1.png', '2/2.png', '2/deeper/3.png', 'alpha.png'];
        modal.currentSkinDirectory = '';
        modal.currentSkinIndex = -1;

        const rootItems = modal.currentSkinItems.map((item) => `${item.type}:${item.name}:${item.path}`);
        const expectedRoot = ['directory:2:2', 'image:1.png:1.png', 'image:alpha.png:alpha.png'];
        if (JSON.stringify(rootItems) !== JSON.stringify(expectedRoot)) {
          throw new Error(`expected root directory items ${JSON.stringify(expectedRoot)}, got ${JSON.stringify(rootItems)}`);
        }

        modal.enterSkinDirectory('2');
        if (modal.currentSkinDirectory !== '2') {
          throw new Error(`expected current directory to be 2, got ${modal.currentSkinDirectory}`);
        }
        if (modal.currentSkinIndex !== -1) {
          throw new Error(`expected entering a directory to clear selection, got ${modal.currentSkinIndex}`);
        }

        const childItems = modal.currentSkinItems.map((item) => `${item.type}:${item.name}:${item.path}`);
        const expectedChild = ['directory:deeper:2/deeper', 'image:2.png:2/2.png'];
        if (JSON.stringify(childItems) !== JSON.stringify(expectedChild)) {
          throw new Error(`expected child directory items ${JSON.stringify(expectedChild)}, got ${JSON.stringify(childItems)}`);
        }

        modal.selectSkinByPath('2/2.png');
        if (modal.currentSkinIndex !== 1) {
          throw new Error(`expected selected global skin index 1, got ${modal.currentSkinIndex}`);
        }
        if (modal.displayImageUrl !== '/resources_file/hero/2/2.png') {
          throw new Error(`expected selected nested image URL, got ${modal.displayImageUrl}`);
        }

        modal.goToSkinParentDirectory();
        if (modal.currentSkinDirectory !== '') {
          throw new Error(`expected parent navigation to return to root, got ${modal.currentSkinDirectory}`);
        }
      """
    )


def test_detail_modal_runtime_skin_gallery_opens_previews_and_handles_escape():
    run_detail_modal_runtime_check(
        """
        modal.activeCard = { resource_folder: 'hero' };
        modal.editingData = { resource_folder: 'hero' };
        modal.skinImages = ['1.png', 'poses/happy.png'];
        modal.currentSkinDirectory = '';
        modal.currentSkinIndex = -1;

        if (modal.showSkinGallery !== false) {
          throw new Error(`expected skin gallery to start closed, got ${modal.showSkinGallery}`);
        }
        if (modal.skinGalleryPreviewPath !== '') {
          throw new Error(`expected no starting preview path, got ${modal.skinGalleryPreviewPath}`);
        }

        modal.openSkinGallery();
        if (modal.showSkinGallery !== true) {
          throw new Error('expected opening gallery to show overlay');
        }

        modal.openSkinGalleryPreview('poses/happy.png');
        if (modal.skinGalleryPreviewPath !== 'poses/happy.png') {
          throw new Error(`expected preview path to track clicked image, got ${modal.skinGalleryPreviewPath}`);
        }
        if (modal.currentSkinIndex !== 1) {
          throw new Error(`expected previewing image to select skin index 1, got ${modal.currentSkinIndex}`);
        }
        if (modal.skinGalleryPreviewUrl !== '/resources_file/hero/poses/happy.png') {
          throw new Error(`expected preview URL to use existing resource image route, got ${modal.skinGalleryPreviewUrl}`);
        }

        let prevented = 0;
        modal.handleSkinGalleryKeydown({ key: 'Escape', preventDefault() { prevented += 1; } });
        if (modal.showSkinGallery !== true) {
          throw new Error('expected first Escape to keep gallery open after closing preview');
        }
        if (modal.skinGalleryPreviewPath !== '') {
          throw new Error(`expected first Escape to close image preview, got ${modal.skinGalleryPreviewPath}`);
        }

        modal.handleSkinGalleryKeydown({ key: 'Escape', preventDefault() { prevented += 1; } });
        if (modal.showSkinGallery !== false) {
          throw new Error('expected second Escape to close gallery overlay');
        }
        if (prevented !== 2) {
          throw new Error(`expected Escape events to be prevented twice, got ${prevented}`);
        }
      """
    )


def test_detail_modal_runtime_delete_resource_item_uses_relative_path_and_refreshes():
    run_detail_modal_runtime_check(
        """
        const calls = [];
        globalThis.__deleteResourceFile = async (payload) => {
          calls.push(payload);
          return { success: true };
        };
        let refreshFolder = '';
        modal.activeCard = { id: 'cards/hero.png', resource_folder: 'hero' };
        modal.editingData = { resource_folder: 'hero' };
        modal.$store = { global: { showToast() {} } };
        modal.fetchResourceFiles = (folderName) => {
          refreshFolder = folderName;
        };

        await modal.deleteResourceItem(
          { name: 'book.json', relative_path: 'lorebooks/arc/book.json' },
          '世界书',
        );

        if (calls.length !== 1) {
          throw new Error(`expected one delete call, got ${calls.length}`);
        }
        if (calls[0].filename !== 'lorebooks/arc/book.json') {
          throw new Error(`expected relative path delete, got ${JSON.stringify(calls[0])}`);
        }
        if (refreshFolder !== 'hero') {
          throw new Error(`expected resource list refresh for hero, got ${refreshFolder}`);
        }
      """
    )


def test_detail_modal_runtime_advanced_editor_apply_updates_memory_without_saving():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'alpha' }],
            tavern_helper: { scripts: [] },
          },
        };

        let saveCalls = 0;
        modal.saveChanges = async () => {
          saveCalls += 1;
          return true;
        };

        modal.openAdvancedEditor();
        events[0].detail.extensions.regex_scripts.push({ script: 'beta' });
        await listeners['advanced-editor-apply'][0]();

        if (saveCalls !== 0) {
          throw new Error(`expected apply to avoid saveChanges, got ${saveCalls}`);
        }
        if (JSON.stringify(modal.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'alpha' }, { script: 'beta' }])) {
          throw new Error(`expected apply to update in-memory extensions, got ${JSON.stringify(modal.editingData.extensions.regex_scripts)}`);
        }
      """
    )


def test_detail_modal_runtime_advanced_editor_persist_awaits_save_and_only_closes_on_success():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        let saveCalls = 0;
        modal.saveChanges = async () => {
          saveCalls += 1;
          return true;
        };

        modal.openAdvancedEditor();
        events[0].detail.extensions.regex_scripts.push({ script: 'persisted' });
        await listeners['advanced-editor-persist'][0]();

        if (saveCalls !== 1) {
          throw new Error(`expected persist to await saveChanges once, got ${saveCalls}`);
        }
        if (JSON.stringify(modal.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'persisted' }])) {
          throw new Error(`expected persist to update in-memory extensions, got ${JSON.stringify(modal.editingData.extensions.regex_scripts)}`);
        }
        if (closeEventCount !== 1) {
          throw new Error(`expected persist success to dispatch advanced-editor-close once, got ${closeEventCount}`);
        }

        modal.editingData.extensions.regex_scripts = [{ script: 'base' }];
        closeEventCount = 0;
        modal.saveChanges = async () => {
          saveCalls += 1;
          return false;
        };

        modal.openAdvancedEditor();
        events[events.length - 1].detail.extensions.regex_scripts.push({ script: 'failed' });
        await listeners['advanced-editor-persist'][0]();

        if (saveCalls !== 2) {
          throw new Error(`expected persist failure path to still await saveChanges, got ${saveCalls}`);
        }
        if (JSON.stringify(modal.editingData.extensions.regex_scripts) !== JSON.stringify([{ script: 'base' }, { script: 'failed' }])) {
          throw new Error(`expected persist failure to keep in-memory update, got ${JSON.stringify(modal.editingData.extensions.regex_scripts)}`);
        }
        if (closeEventCount !== 0) {
          throw new Error(`expected persist failure to avoid close event, got ${closeEventCount}`);
        }
      """
    )


def test_detail_modal_runtime_local_note_paste_uploads_image_and_replaces_placeholder():
    run_detail_modal_runtime_check(
        """
        const appendedFiles = [];
        globalThis.FormData = class FormData {
          append(name, value) {
            appendedFiles.push({ name, value });
          }
        };
        const uploadedBlob = { type: 'image/png', name: 'clip.png' };
        let uploadCalls = 0;
        globalThis.__uploadNoteImage = async (formData) => {
          uploadCalls += 1;
          return { success: true, url: '/api/uploads/note-image.png' };
        };
        const event = {
          clipboardData: {
            items: [
              {
                type: 'image/png',
                getAsFile() {
                  return uploadedBlob;
                },
              },
            ],
          },
          preventDefaultCalls: 0,
          preventDefault() {
            this.preventDefaultCalls += 1;
          },
          target: {
            value: 'before after',
            selectionStart: 6,
            selectionEnd: 6,
          },
        };

        modal.editingData = { ui_summary: 'before after' };

        const pastePromise = modal.handleLocalNotePaste(event);

        if (event.preventDefaultCalls !== 1) {
          throw new Error(`expected paste to be prevented once, got ${event.preventDefaultCalls}`);
        }
        if (modal.editingData.ui_summary !== 'before\\n![Uploading image...]()\\n after') {
          throw new Error(`expected upload placeholder at cursor, got ${JSON.stringify(modal.editingData.ui_summary)}`);
        }

        await pastePromise;

        if (uploadCalls !== 1) {
          throw new Error(`expected one upload call, got ${uploadCalls}`);
        }
        if (appendedFiles.length !== 1 || appendedFiles[0].name !== 'file' || appendedFiles[0].value !== uploadedBlob) {
          throw new Error(`expected clipboard blob to be uploaded, got ${JSON.stringify(appendedFiles)}`);
        }
        if (modal.editingData.ui_summary !== 'before\\n![image](/api/uploads/note-image.png)\\n after') {
          throw new Error(`expected uploaded image markdown, got ${JSON.stringify(modal.editingData.ui_summary)}`);
        }
      """
    )


def test_detail_modal_runtime_reopen_replaces_stale_advanced_editor_listeners():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        modal.openAdvancedEditor();
        const firstApplyHandler = listeners['advanced-editor-apply'][0];
        const firstPersistHandler = listeners['advanced-editor-persist'][0];

        modal.openAdvancedEditor();

        if ((listeners['advanced-editor-apply'] || []).length !== 1) {
          throw new Error(`expected one apply listener after reopen, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 1) {
          throw new Error(`expected one persist listener after reopen, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (listeners['advanced-editor-apply'][0] === firstApplyHandler) {
          throw new Error('expected reopen to replace stale apply listener');
        }
        if (listeners['advanced-editor-persist'][0] === firstPersistHandler) {
          throw new Error('expected reopen to replace stale persist listener');
        }
      """
    )


def test_detail_modal_runtime_advanced_editor_apply_cleans_both_session_listeners():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        modal.openAdvancedEditor();
        await listeners['advanced-editor-apply'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected apply to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected apply to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (modal.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (modal.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected apply to clear pendingAdvancedEditorPersistHandler reference');
        }
      """
    )


def test_detail_modal_runtime_advanced_editor_persist_cleans_both_session_listeners():
    run_detail_modal_runtime_check(
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
        modal.$store = { global: { showToast() {} } };
        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };
        modal.saveChanges = async () => true;

        modal.openAdvancedEditor();
        await listeners['advanced-editor-persist'][0]();

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected persist to clear apply listeners, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected persist to clear persist listeners, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
        if (modal.pendingAdvancedEditorApplyHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorApplyHandler reference');
        }
        if (modal.pendingAdvancedEditorPersistHandler !== null) {
          throw new Error('expected persist to clear pendingAdvancedEditorPersistHandler reference');
        }
      """
    )


def test_detail_modal_runtime_open_detail_cleans_old_pending_advanced_editor_listeners():
    run_detail_modal_runtime_check(
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
        modal.$store = {
          global: {
            loadTagViewPrefs() {
              return { rememberLastTagView: false };
            },
            showToast() {},
          },
        };

        modal.editingData = {
          extensions: {
            regex_scripts: [{ script: 'base' }],
            tavern_helper: { scripts: [] },
          },
        };

        modal.openAdvancedEditor();
        if ((listeners['advanced-editor-apply'] || []).length !== 1) {
          throw new Error(`expected pending apply listener before openDetail, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 1) {
          throw new Error(`expected pending persist listener before openDetail, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }

        modal.openDetail({
          id: 'card-2',
          char_name: 'Card Two',
          filename: 'card-two.png',
          extensions: {
            regex_scripts: [],
            tavern_helper: { scripts: [] },
          },
        });

        if ((listeners['advanced-editor-apply'] || []).length !== 0) {
          throw new Error(`expected openDetail to remove pending apply listener, got ${(listeners['advanced-editor-apply'] || []).length}`);
        }
        if ((listeners['advanced-editor-persist'] || []).length !== 0) {
          throw new Error(`expected openDetail to remove pending persist listener, got ${(listeners['advanced-editor-persist'] || []).length}`);
        }
      """
    )
