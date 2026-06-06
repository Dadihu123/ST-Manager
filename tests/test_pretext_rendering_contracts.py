from pathlib import Path
import re
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def read_css_module_bundle(relative_path: str, seen=None) -> str:
    seen = set() if seen is None else seen
    source_path = (PROJECT_ROOT / relative_path).resolve()
    if source_path in seen:
        return ''
    seen.add(source_path)

    source = source_path.read_text(encoding='utf-8')

    def replace_import(match):
        import_path = unquote(match.group(1))
        imported_relative = source_path.parent.joinpath(import_path).resolve().relative_to(PROJECT_ROOT)
        return read_css_module_bundle(str(imported_relative).replace('\\', '/'), seen)

    return re.sub(
        r'@import\s+url\([\'"]([^\'"]+)[\'"]\)\s*;',
        replace_import,
        source,
    )


def test_pretext_vendor_module_exists_and_exports_prepare_and_layout_contracts():
    source = read_project_file('static/js/vendor/pretext/layout.js')

    assert 'export function prepare(' in source
    assert 'export function layout(' in source
    assert 'export function clearCache(' in source
    assert 'export function setLocale(' in source


def test_dom_utils_exposes_pretext_backed_intrinsic_size_helpers():
    source = read_project_file('static/js/utils/dom.js')

    assert 'export function applyPretextIntrinsicSize(' in source
    assert 'export function estimatePretextBlockHeight(' in source
    assert (
        "import('../vendor/pretext/layout.js')" in source
        or 'import("../vendor/pretext/layout.js")' in source
    )
    assert 'module.prepare(' in source
    assert 'module.layout(' in source
    assert 'containIntrinsicSize' in source


def test_chat_reader_uses_pretext_intrinsic_size_hint_before_mounting_message_html():
    source = read_project_file('static/js/components/chatGrid.js')

    assert 'applyPretextIntrinsicSize' in source
    assert 'estimatePretextBlockHeight' in source
    assert 'shouldApplyReaderPretextIntrinsicSize(variant, message)' in source
    assert 'applyReaderPretextIntrinsicSize(el, message, variant' in source


def test_chat_reader_skips_pretext_for_page_mode_full_render_hot_path():
    source = read_project_file('static/js/components/chatGrid.js')

    assert 'shouldApplyReaderPretextIntrinsicSize(variant, message) {' in source
    assert (
        "variant !== 'simple'" in source
        or 'variant !== "simple"' in source
    ), 'expected simple-only pretext gating to remain in the reader path'
    assert 'this.isReaderPageMode' in source, 'expected page-mode bypass to remain in the reader path'


def test_large_preview_surfaces_use_pretext_intrinsic_size_hints():
    dom_source = read_project_file('static/js/utils/dom.js')

    assert 'applyPretextIntrinsicSize(el, source,' in dom_source
    assert 'applyPretextIntrinsicSize(host, source,' in dom_source
    assert 'runtimeOwner' in dom_source


def test_update_mixed_preview_content_is_a_compatibility_wrapper_over_render_unified_preview_host():
    dom_source = read_project_file('static/js/utils/dom.js')

    assert 'export function renderUnifiedPreviewHost(' in dom_source
    assert 'export function updateMixedPreviewContent(' in dom_source
    assert 'function buildMixedPreviewParts(' not in dom_source
    assert 'renderUnifiedPreviewHost(el, content, options)' in dom_source
    wrapper_block = dom_source.split('export function updateMixedPreviewContent(', 1)[1]
    wrapper_block = wrapper_block.split('}', 1)[0]
    assert 'buildMixedPreviewParts' not in wrapper_block
    assert 'classifyPreviewFrontendText' not in wrapper_block


def test_preview_entrypoints_continue_using_shared_dom_renderers_with_unified_preview_host():
    advanced_editor_template = read_project_file('templates/modals/advanced_editor.html')
    large_editor_template = read_project_file('templates/modals/large_editor.html')
    markdown_preview_template = read_project_file('templates/modals/markdown_preview.html')
    detail_card_template = read_project_file('templates/modals/detail_card.html')
    html_preview_template = read_project_file('templates/modals/html_preview.html')
    detail_modal_source = read_project_file('static/js/components/detailModal.js')
    large_editor_source = read_project_file('static/js/components/largeEditor.js')

    assert 'renderUnifiedPreviewHost' in read_project_file('static/js/utils/dom.js')
    assert 'renderUnifiedPreviewHost,' in detail_modal_source
    assert 'renderUnifiedPreviewHost,' in large_editor_source
    assert 'buildPreviewRegexConfig() {' in detail_modal_source
    assert 'resolvePreviewOptions() {' in large_editor_source
    assert 'renderUnifiedPreviewHost($el' in advanced_editor_template
    assert 'renderUnifiedPreviewHost($el' in large_editor_template
    assert 'renderUnifiedPreviewHost($el' in detail_card_template
    assert 'renderUnifiedPreviewHost($el' in html_preview_template
    assert 'updateMixedPreviewContent($el' not in advanced_editor_template
    assert 'updateMixedPreviewContent($el' not in large_editor_template
    assert 'updateMixedPreviewContent($el' not in detail_card_template
    assert 'updateMixedPreviewContent($el' not in html_preview_template
    assert 'updateShadowContent($el' not in large_editor_template
    assert 'updateShadowContent($el' in markdown_preview_template
    assert 'updateMixedPreviewContent(' not in large_editor_source
    assert 'updateShadowContent,' in large_editor_source
    update_preview_block = large_editor_source.split('updatePreview(el) {', 1)[1]
    update_preview_block = update_preview_block.split('        // === 粘贴处理', 1)[0]
    assert 'renderUnifiedPreviewHost(el, this.largeEditorContent, {' in update_preview_block
    assert '...this.resolvePreviewOptions()' in update_preview_block
    resolve_options_block = large_editor_source.split('resolvePreviewOptions() {', 1)[1].split('        // 更新统一预览宿主', 1)[0]
    assert 'renderMode: this.largeRenderMode' in resolve_options_block
    assert 'applyDisplayRules: true' in resolve_options_block
    assert 'displayRules: regexScripts' in resolve_options_block
    preview_block = large_editor_template.split('class="large-editor-preview"', 1)[1]
    preview_block = preview_block.split('></div>', 1)[0]
    assert "largeRenderMode === 'html' ?" not in preview_block
    assert '...resolvePreviewOptions()' in preview_block
    assert "renderMode: 'markdown'" not in preview_block
    assert '...resolvePreviewOptions()' in preview_block
    detail_preview_block = detail_card_template.split('x-show="showFirstPreview"', 1)[1]
    detail_preview_block = detail_preview_block.split('</div>', 1)[0]
    assert "renderUnifiedPreviewHost($el, showFirstPreview ? editingData.first_mes : null" in detail_preview_block
    assert "renderMode: 'markdown'" in detail_preview_block
    assert 'applyDisplayRules: true' in detail_preview_block
    assert 'config: buildPreviewRegexConfig()' in detail_preview_block


def test_detail_local_note_supports_inline_markdown_preview_contract():
    detail_card_template = read_project_file('templates/modals/detail_card.html')
    detail_modal_source = read_project_file('static/js/components/detailModal.js')

    assert 'showLocalNotePreview: false,' in detail_modal_source
    open_detail_reset_block = detail_modal_source.split('openDetail(c) {', 1)[1].split(
        '// 深拷贝并清洗数据',
        1,
    )[0]
    assert 'this.showLocalNotePreview = false;' in open_detail_reset_block

    local_note_block = detail_card_template.split('<span>本地备注 (Local Note)</span>', 1)[1]
    local_note_block = local_note_block.split('<!-- 原简介卡片：条件渲染 -->', 1)[0]

    assert ':class="!showLocalNotePreview ? \'active\' : \'\'"' in local_note_block
    assert ':class="showLocalNotePreview ? \'active\' : \'\'"' in local_note_block
    assert '@click="showLocalNotePreview=false"' in local_note_block
    assert '@click="showLocalNotePreview=true"' in local_note_block
    assert 'Markdown预览' in local_note_block
    assert 'x-show="!showLocalNotePreview"' in local_note_block
    assert 'x-show="showLocalNotePreview"' in local_note_block
    assert (
        'renderUnifiedPreviewHost($el, showLocalNotePreview ? editingData.ui_summary : null'
        in local_note_block
    )
    assert "renderMode: 'markdown'" in local_note_block
    assert 'applyDisplayRules' not in local_note_block
    assert 'buildPreviewRegexConfig()' not in local_note_block


def test_detail_local_note_preview_keeps_textarea_footprint_and_paste_contract():
    detail_card_template = read_project_file('templates/modals/detail_card.html')
    detail_css = read_project_file('static/css/modules/modal-detail.css')
    detail_modal_source = read_project_file('static/js/components/detailModal.js')

    local_note_block = detail_card_template.split('<span>本地备注 (Local Note)</span>', 1)[1]
    local_note_block = local_note_block.split('<!-- 原简介卡片：条件渲染 -->', 1)[0]

    assert '@paste="handleLocalNotePaste($event)"' in local_note_block
    assert 'class="detail-local-note-editor"' in local_note_block
    assert 'class="form-textarea note-textarea"' in local_note_block
    assert 'class="detail-render-box custom-scrollbar detail-local-note-preview-box"' in local_note_block
    assert 'height: 10rem;' not in local_note_block

    editor_css_block = detail_css.split(
        '.detail-section-fill .detail-card .detail-local-note-editor {',
        1,
    )[1].split('}', 1)[0]
    assert 'flex: 1' in editor_css_block
    assert 'min-height: 0' in editor_css_block
    assert 'display: flex;' in editor_css_block
    assert 'flex-direction: column;' in editor_css_block

    assert '.detail-local-note-editor > .form-textarea,' in detail_css
    assert '.detail-local-note-editor > .detail-local-note-preview-box {' in detail_css

    preview_css_block = detail_css.split(
        '.detail-section-fill .detail-card .detail-local-note-preview-box {',
        1,
    )[1].split('}', 1)[0]
    assert 'height: auto !important;' in preview_css_block
    assert 'overflow: auto !important;' in preview_css_block

    assert 'uploadNoteImage,' in detail_modal_source
    assert 'insertAtCursor,' in detail_modal_source
    assert 'handleLocalNotePaste(e) {' in detail_modal_source


def test_advanced_editor_footer_distinguishes_file_mode_from_buffered_apply_and_persist_actions():
    advanced_editor_template = read_project_file('templates/modals/advanced_editor.html')

    assert 'x-show="isFileMode" @click="saveFileChanges()"' in advanced_editor_template
    assert 'x-show="!isFileMode && showPersistButton" @click="persistChanges()"' in advanced_editor_template
    assert 'x-show="!isFileMode" @click="applyChangesAndClose()"' in advanced_editor_template
    assert '保存文件' in advanced_editor_template
    assert '>\n                保存\n            </button>' in advanced_editor_template
    assert '>\n                完成\n            </button>' in advanced_editor_template
    assert '完成：仅返回当前编辑界面' in advanced_editor_template
    assert '保存：直接写入原文件' in advanced_editor_template
    assert 'advanced-editor-save' not in advanced_editor_template


def test_chat_reader_css_enables_content_visibility_and_intrinsic_size_placeholder_strategy():
    css_source = read_css_module_bundle('static/css/modules/view-chats.css')

    assert '.chat-message-card {' in css_source
    assert 'content-visibility: auto;' in css_source
    assert 'contain-intrinsic-size:' in css_source
    assert '--stm-pretext-block-size:' in css_source

    card_block = css_source.split('.chat-message-card {', 1)[1].split('}', 1)[0]
    content_block = css_source.split('.chat-message-content {', 1)[1].split('}', 1)[0]

    assert 'content-visibility: auto;' not in card_block
    assert 'contain-intrinsic-size:' not in card_block
    assert 'content-visibility: auto;' in content_block
    assert 'contain-intrinsic-size:' in content_block
