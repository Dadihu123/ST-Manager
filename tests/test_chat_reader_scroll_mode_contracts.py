from pathlib import Path
import re
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def read_css_module_bundle(relative_path, seen=None):
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


def project_file_exists(relative_path):
    return (PROJECT_ROOT / relative_path).exists()


def extract_js_block(source, signature):
    block_start = source.index(signature)
    paren_start = source.find('(', block_start, block_start + len(signature) + 8)
    if paren_start != -1:
        depth = 0
        index = paren_start
        while index < len(source):
            current_char = source[index]
            if current_char == '(':
                depth += 1
            elif current_char == ')':
                depth -= 1
                if depth == 0:
                    break
            index += 1
        brace_start = source.index('{', index)
    else:
        brace_start = source.index('{', block_start)
    depth = 1
    index = brace_start + 1

    while depth > 0:
        current_char = source[index]
        if current_char == '{':
            depth += 1
        elif current_char == '}':
            depth -= 1
        index += 1

    return source[brace_start + 1:index - 1]


def extract_exact_js_method_block(source, signature):
    pattern = re.compile(rf'(^|\n)\s*{re.escape(signature)}\s*\{{', re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise ValueError(f'Exact method signature not found: {signature}')

    block_start = source.index(signature, match.start())
    brace_start = source.index('{', block_start)
    depth = 1
    index = brace_start + 1

    while depth > 0:
        current_char = source[index]
        if current_char == '{':
            depth += 1
        elif current_char == '}':
            depth -= 1
        index += 1

    return source[brace_start + 1:index - 1]


def assert_contains_either(source, candidates):
    assert any(candidate in source for candidate in candidates), (
        f'Expected one of {candidates!r} in source block'
    )


def assert_matches(pattern, source):
    assert re.search(pattern, source, re.MULTILINE | re.DOTALL), (
        f'Missing regex contract: {pattern}'
    )


def test_chat_reader_semi_auto_anchor_mode_contract_is_defined_in_source():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    anchor_modes_block = extract_js_block(chat_grid_source, 'const READER_ANCHOR_MODES =')
    normalize_anchor_mode_block = extract_js_block(chat_grid_source, 'function normalizeReaderAnchorMode(mode)')
    anchor_status_block = extract_js_block(chat_grid_source, 'get readerAnchorStatusText()')

    assert_contains_either(anchor_modes_block, [
        "SEMI_AUTO: 'semi_auto'",
        'SEMI_AUTO: "semi_auto"',
    ])
    assert 'semi_auto' in normalize_anchor_mode_block
    assert 'READER_ANCHOR_MODES.SEMI_AUTO' in normalize_anchor_mode_block
    assert '半自动迁移' in anchor_status_block
    assert '锁定楼层' in anchor_status_block
    assert '末楼兼容' in anchor_status_block


def test_chat_reader_reasoning_and_long_code_view_settings_contract_is_defined_in_source():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    default_settings_block = extract_js_block(chat_grid_source, 'const DEFAULT_CHAT_READER_VIEW_SETTINGS =')
    normalize_view_settings_block = extract_js_block(chat_grid_source, 'function normalizeViewSettings(raw)')

    for setting_key in ('reasoningDefaultCollapsed', 'autoCollapseLongCode'):
        assert re.search(rf'\b{setting_key}\b', default_settings_block)
        assert re.search(rf'\b{setting_key}\b', normalize_view_settings_block)


def test_chat_reader_enhancement_helper_module_contract_exists_and_exports_required_entry_points():
    helper_relative_path = 'static/js/utils/chatReaderEnhancements.js'

    assert project_file_exists(helper_relative_path), (
        'Expected scroll-mode helper module to exist at '
        'static/js/utils/chatReaderEnhancements.js'
    )

    helper_source = read_project_file(helper_relative_path)

    for export_name in (
        'extractReaderEnhancementMetadata',
        'buildReaderEnhancementPolicy',
        'decorateReaderRenderedHtml',
    ):
        assert re.search(
            rf'export\s+(function|const)\s+{export_name}\b|export\s*\{{[^}}]*\b{export_name}\b[^}}]*\}}',
            helper_source,
        ), f'Missing helper export: {export_name}'


def test_chat_reader_anchor_promotion_policy_hooks_exist_in_source():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')

    assert 'function shouldPromoteReaderAnchorForSource(' in chat_grid_source
    assert 'function shouldResetReaderWindowForAnchorTarget(' in chat_grid_source


def test_chat_reader_scroll_to_floor_uses_anchor_policy_helpers_and_explicit_sources():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    scroll_to_floor_block = extract_js_block(chat_grid_source, 'async scrollToFloor')

    assert 'shouldPromoteReaderAnchorForSource(' in scroll_to_floor_block
    assert 'shouldResetReaderWindowForAnchorTarget(' in scroll_to_floor_block
    assert_matches(
        r'const\s+shouldPromoteAnchor\s*=\s*shouldPromoteReaderAnchorForSource\(\s*this\.readerAnchorMode,\s*anchorSource,?\s*\)',
        scroll_to_floor_block,
    )
    assert_matches(
        r'const\s+shouldResetWindow\s*=\s*shouldResetReaderWindowForAnchorTarget\(\s*\{[\s\S]*?targetFloor\s*,[\s\S]*?windowStartFloor:\s*this\.readerWindowStartFloor\s*,[\s\S]*?windowEndFloor:\s*this\.readerWindowEndFloor\s*,[\s\S]*?totalMessages:\s*[\s\S]*?this\.readerTotalMessages[\s\S]*?\}\s*\)',
        scroll_to_floor_block,
    )
    assert 'if (shouldPromoteAnchor) {' in scroll_to_floor_block
    assert 'if (shouldResetWindow) {' in scroll_to_floor_block


def test_chat_reader_navigation_entry_points_use_approved_anchor_sources():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    reader_template = read_project_file('templates/modals/detail_chat_reader.html')
    set_reader_app_floor_block = extract_js_block(chat_grid_source, 'setReaderAppFloor(floor)')
    open_message_as_app_stage_block = extract_js_block(chat_grid_source, 'openMessageAsAppStage(message)')

    assert_matches(
        r"scrollToFloor\(\s*matches\[0\],\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.SEARCH\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*this\.detailSearchResults\[this\.detailSearchIndex\],\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.SEARCH\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*floor,\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.BOOKMARK\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*floor,\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.JUMP\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*messages\[0\]\.floor,\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.JUMP\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*messages\[messages\.length\s*-\s*1\]\.floor,\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.JUMP\s*,?\s*\)",
        chat_grid_source,
    )
    assert_matches(
        r"scrollToFloor\(\s*floor,\s*true,\s*['\"]smooth['\"],\s*READER_ANCHOR_SOURCES\.NAVIGATOR\s*,?\s*\)",
        chat_grid_source,
    )
    assert 'syncReaderPageGroupForFloor(targetFloor, {' in chat_grid_source
    assert 'source: anchorSource,' in chat_grid_source
    assert_matches(
        r"this\.\$nextTick\(\(\)\s*=>\s*this\.scrollToFloor\(\s*previousStart,\s*false,\s*['\"]auto['\"],\s*READER_ANCHOR_SOURCES\.NAVIGATOR\s*,?\s*\)\s*,?\s*\);",
        chat_grid_source,
    )
    assert_matches(
        r"this\.\$nextTick\(\(\)\s*=>\s*this\.scrollToFloor\(\s*previousEnd,\s*false,\s*['\"]auto['\"],\s*READER_ANCHOR_SOURCES\.NAVIGATOR\s*,?\s*\)\s*,?\s*\);",
        chat_grid_source,
    )
    assert '@click="jumpToBookmarkFloor(bookmark.floor)"' in reader_template
    assert '@click="jumpToNavigatorFloor(message.floor)"' in reader_template
    assert "@click=\"scrollToFloor(bookmark.floor, true, 'smooth', 'bookmark')\"" not in reader_template
    assert "@click=\"scrollToFloor(message.floor, true, 'smooth', 'jump')\"" not in reader_template
    assert_matches(
        r'const\s+shouldPromoteAnchor\s*=\s*shouldPromoteReaderAnchorForSource\(\s*this\.readerAnchorMode,\s*READER_ANCHOR_SOURCES\.APP_STAGE,?\s*\)',
        set_reader_app_floor_block,
    )
    assert_matches(
        r'this\.updateReaderAnchorFloor\(\s*targetFloor,\s*READER_ANCHOR_SOURCES\.APP_STAGE,?\s*\);',
        set_reader_app_floor_block,
    )
    assert 'this.updateReaderAnchorFloor(floor, READER_ANCHOR_SOURCES.APP_STAGE);' not in open_message_as_app_stage_block


def test_chat_reader_rebuild_extracts_enhancement_metadata():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    rebuild_block = extract_js_block(chat_grid_source, 'rebuildActiveChatMessages(config = null)')

    assert_matches(
        r'extractReaderEnhancementMetadata\(\s*rawMessage,\s*parsedMessage\s*,?\s*\)',
        rebuild_block,
    )
    assert '__readerEnhancementMeta' in rebuild_block
    assert_contains_either(rebuild_block, [
        "reasoningState: 'missing'",
        'reasoningState: "missing"',
    ])


def test_chat_reader_visible_messages_build_per_tier_enhancement_policy():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    visible_detail_block = extract_js_block(chat_grid_source, 'get visibleDetailMessages()')

    assert 'const enhancementPolicy = buildReaderEnhancementPolicy(' in visible_detail_block
    assert '__readerEnhancementPolicy: enhancementPolicy' in visible_detail_block
    assert 'meta_flags: enhancementPolicy.metaFlags' in visible_detail_block
    assert 'reasoning_mode: enhancementPolicy.reasoningMode' in visible_detail_block
    assert 'code_mode: enhancementPolicy.codeMode' in visible_detail_block


def test_extract_reader_enhancement_metadata_prefers_structured_reasoning_fields_before_tag_fallbacks():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    candidate_block = extract_js_block(
        helper_source,
        'function collectReasoningCandidates(rawMessage = null, message = null)',
    )
    extract_block = extract_js_block(
        helper_source,
        'export function extractReaderEnhancementMetadata(rawMessage = null, message = null)',
    )

    assert 'extra.reasoning' in candidate_block
    assert 'reasoning_content' in candidate_block
    assert 'thinking' in candidate_block
    assert 'collectReasoningCandidates(rawMessage, message)' in extract_block
    assert 'extractTaggedReasoning' in extract_block
    assert extract_block.index('collectReasoningCandidates(rawMessage, message)') < extract_block.index('extractTaggedReasoning')


def test_extract_reader_enhancement_metadata_preserves_missing_reasoning_marker_contract():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    extract_block = extract_js_block(
        helper_source,
        'export function extractReaderEnhancementMetadata(rawMessage = null, message = null)',
    )

    assert 'hasReasoning' in extract_block
    assert 'reasoningState' in extract_block
    assert "reasoningState = 'missing'" in extract_block or "reasoningState: 'missing'" in extract_block
    assert 'reasoningPreview' in extract_block


def test_decorate_reader_rendered_html_contract_emits_reasoning_disclosure_and_code_collapse_classes():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    reasoning_block = extract_js_block(
        helper_source,
        'function wrapReasoningDisclosure(metadata, policy, options = {})',
    )
    preview_block = extract_js_block(
        helper_source,
        'function buildCodePreviewHtml(renderedHtml, policy)',
    )
    collapse_block = extract_js_block(
        helper_source,
        'function collapseLongCodeBlocks(renderedHtml, policy)',
    )
    decorate_block = extract_js_block(
        helper_source,
        'export function decorateReaderRenderedHtml(renderedHtml, metadata, policy, options = {})',
    )

    assert 'chat-message-reasoning' in reasoning_block
    assert 'chat-message-reasoning-summary' in reasoning_block
    assert 'chat-message-reasoning-body' in reasoning_block
    assert '<details' in reasoning_block
    assert '<summary' in reasoning_block
    assert 'chat-message-code-collapse' in preview_block
    assert 'chat-message-code-collapse-toggle' in preview_block
    assert 'chat-message-code-collapse' in collapse_block
    assert 'chat-message-code-collapse-toggle' in collapse_block
    assert 'wrapReasoningDisclosure' in decorate_block
    assert 'buildCodePreviewHtml' in decorate_block
    assert 'collapseLongCodeBlocks' in decorate_block


def test_render_message_display_html_passes_full_tier_policy_into_decorator():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    display_block = extract_exact_js_method_block(chat_grid_source, 'renderMessageDisplayHtml(message)')

    assert 'buildReaderEnhancementPolicy(' in display_block
    assert_contains_either(display_block, ["'full'", '"full"'])
    assert 'render_tier' not in display_block.split('buildReaderEnhancementPolicy(', 1)[1].split(')', 1)[0]
    assert 'decorateReaderRenderedHtml(' in display_block


def test_reader_render_decoration_is_guarded_to_scroll_mode_only():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    display_block = extract_exact_js_method_block(chat_grid_source, 'renderMessageDisplayHtml(message)')
    simple_block = extract_exact_js_method_block(chat_grid_source, 'renderMessageSimpleHtml(message)')

    for block in (display_block, simple_block):
        assert 'this.isReaderPageMode' in block
        assert 'decorateReaderRenderedHtml(' in block


def test_render_message_simple_html_uses_simple_tier_markers_or_previews_instead_of_full_disclosure_blocks():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    simple_block = extract_exact_js_method_block(chat_grid_source, 'renderMessageSimpleHtml(message)')

    assert 'buildReaderEnhancementPolicy(' in simple_block
    assert_contains_either(simple_block, ["'simple'", '"simple"'])
    assert 'render_tier' not in simple_block.split('buildReaderEnhancementPolicy(', 1)[1].split(')', 1)[0]
    assert 'decorateReaderRenderedHtml(' in simple_block
    assert 'previewedHtml' in simple_block
    assert 'chat-message-reasoning-body' not in simple_block
    assert 'chat-message-reasoning-summary' not in simple_block
    assert 'metaFlagsHtml' not in simple_block
    assert "renderMode: 'literal'" not in simple_block
    assert_matches(
        r'renderMode:\s*this\.resolveSimpleReaderRenderMode\(\s*message,\s*source,\s*enhancementMeta,\s*\)',
        simple_block,
    )


def test_build_reader_enhancement_policy_uses_shorter_simple_code_preview_than_full():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    policy_block = extract_js_block(
        helper_source,
        'export function buildReaderEnhancementPolicy(renderTier, metadata, options = {})',
    )

    assert 'codePreviewLines: previewLines' in policy_block
    assert 'codePreviewLines: Math.min(previewLines, 6)' in policy_block or 'codePreviewLines: Math.min(previewLines, 5)' in policy_block


def test_missing_reasoning_marker_contract_prefers_explicit_missing_label_over_generic_reasoning_hint():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    helper_block = extract_js_block(
        helper_source,
        'function wrapReasoningDisclosure(metadata, policy, options = {})',
    )

    marker_block = extract_js_block(
        helper_source,
        'function buildReasoningMarkerLabel(metadata)',
    )

    assert 'buildReasoningMarkerLabel(metadata)' in helper_block
    assert 'Reasoning missing body' in marker_block
    assert "return 'Reasoning';" in marker_block


def test_reasoning_collapsed_ui_contract_uses_generic_labels_without_preview_snippets():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    disclosure_block = extract_js_block(
        helper_source,
        'function wrapReasoningDisclosure(metadata, policy, options = {})',
    )
    marker_block = extract_js_block(
        helper_source,
        'function buildReasoningMarkerLabel(metadata)',
    )

    assert 'metadata.reasoningPreview' not in disclosure_block
    assert 'metadata?.reasoningPreview' not in marker_block
    assert 'Reasoning' in disclosure_block
    assert 'Reasoning' in marker_block


def test_simple_tier_reasoning_marker_contract_uses_single_rendering_path_without_duplicate_meta_flag():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    disclosure_block = extract_js_block(
        helper_source,
        'function wrapReasoningDisclosure(metadata, policy, options = {})',
    )
    meta_flags_block = extract_js_block(
        helper_source,
        'function renderMetaFlags(metadata, policy)',
    )

    assert "policy?.reasoningMode === 'marker'" in disclosure_block
    assert "policy?.reasoningMode !== 'marker'" in meta_flags_block
    assert 'flags.includes(\'reasoning\') && metadata?.hasReasoning && policy?.reasoningMode !== \'marker\'' in meta_flags_block


def test_long_code_collapse_contract_detects_long_rendered_pre_blocks_even_when_metadata_misses_them():
    helper_source = read_project_file('static/js/utils/chatReaderEnhancements.js')
    preview_block = extract_js_block(
        helper_source,
        'function buildCodePreviewHtml(renderedHtml, policy)',
    )
    collapse_block = extract_js_block(
        helper_source,
        'function collapseLongCodeBlocks(renderedHtml, policy)',
    )
    decorate_block = extract_js_block(
        helper_source,
        'export function decorateReaderRenderedHtml(renderedHtml, metadata, policy, options = {})',
    )

    assert 'function analyzeRenderedCodeBlock' in helper_source
    assert 'analyzeRenderedCodeBlock(codeBody)' in preview_block
    assert 'analyzeRenderedCodeBlock(codeBody)' in collapse_block
    assert 'resolveEffectiveCodePolicy' in decorate_block


def test_runtime_wrapper_contract_collapses_long_inline_runtime_source_in_scroll_mode():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    css_source = read_css_module_bundle('static/css/modules/view-chats.css')
    wrap_block = extract_js_block(chat_grid_source, 'function wrapRuntimeHostsInContainer(container, floor)')

    assert 'chat-inline-runtime-disclosure' in wrap_block
    assert 'chat-inline-runtime-summary' in wrap_block
    assert 'chat-inline-runtime-source-shell' in wrap_block
    assert 'chat-inline-runtime-host' in wrap_block
    assert 'wrapper.appendChild(host);' in wrap_block
    assert 'wrapper.appendChild(disclosure);' in wrap_block
    assert wrap_block.index('wrapper.appendChild(host);') < wrap_block.index('wrapper.appendChild(disclosure);')
    assert_contains_either(wrap_block, [
        "preNode.classList.add('chat-inline-runtime-source', 'is-collapsible');",
        'preNode.classList.add("chat-inline-runtime-source", "is-collapsible");',
    ])
    assert 'chat-inline-runtime-wrap.is-active .chat-inline-runtime-disclosure' in css_source
    assert '.chat-inline-runtime-source.is-collapsible' in css_source


def test_runtime_wrapper_contract_detects_existing_wrappers_via_ancestor_lookup_not_direct_parent():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    wrap_block = extract_js_block(chat_grid_source, 'function wrapRuntimeHostsInContainer(container, floor)')

    assert_contains_either(wrap_block, [
        "preNode.closest('.chat-inline-runtime-wrap')",
        'preNode.closest(".chat-inline-runtime-wrap")',
    ])
    assert "preNode.parentElement?.classList.contains('chat-inline-runtime-wrap')" not in wrap_block


def test_deferred_runtime_placeholder_contract_keeps_runtime_host_reserved_for_rendered_content():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    placeholder_block = extract_js_block(chat_grid_source, 'function buildDeferredInstancePlaceholder(message, viewSettings)')
    mount_block = extract_exact_js_method_block(chat_grid_source, 'mountMessageDisplayNow(el, message)')

    assert '实例预览已折叠' not in placeholder_block
    assert '前端实例未进入当前执行范围' not in placeholder_block
    assert '当前只执行锚点附近最接近的' not in placeholder_block
    assert '可点击楼层头部的“实例”按钮' not in placeholder_block
    assert 'chat-inline-runtime-placeholder-chip' in placeholder_block
    assert 'host.innerHTML = buildDeferredInstancePlaceholder(message, this.readerViewSettings);' not in mount_block
    assert 'host.insertAdjacentHTML(' not in mount_block
    assert_matches(
        r'setDeferredRuntimePlaceholder\(\s*host,\s*message,\s*this\.readerViewSettings,\s*\)',
        mount_block,
    )


def test_deferred_runtime_placeholder_contract_uses_separate_indicator_outside_runtime_host_and_source_disclosure():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    wrap_block = extract_js_block(chat_grid_source, 'function wrapRuntimeHostsInContainer(container, floor)')
    placeholder_mount_block = extract_js_block(chat_grid_source, 'function setDeferredRuntimePlaceholder(host, message, viewSettings)')
    clear_placeholder_block = extract_js_block(chat_grid_source, 'function clearDeferredRuntimePlaceholder(host)')

    assert 'chat-inline-runtime-placeholder' in wrap_block
    assert 'wrapper.appendChild(placeholder);' in wrap_block
    assert wrap_block.index('wrapper.appendChild(host);') < wrap_block.index('wrapper.appendChild(placeholder);')
    assert wrap_block.index('wrapper.appendChild(placeholder);') < wrap_block.index('wrapper.appendChild(disclosure);')
    assert_contains_either(wrap_block, [
        "placeholder.className = 'chat-inline-runtime-placeholder';",
        'placeholder.className = "chat-inline-runtime-placeholder";',
    ])
    assert_matches(
        r'placeholderHost\.innerHTML\s*=\s*buildDeferredInstancePlaceholder\(\s*message,\s*viewSettings,?\s*\);',
        placeholder_mount_block,
    )
    assert 'host.innerHTML = ' not in placeholder_mount_block
    assert_contains_either(clear_placeholder_block, [
        "placeholderHost.innerHTML = '';",
        'placeholderHost.innerHTML = "";',
    ])


def test_active_runtime_contract_hides_source_disclosure_but_keeps_runtime_host_visible():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    css_source = read_css_module_bundle('static/css/modules/view-chats.css')
    active_block = extract_js_block(chat_grid_source, 'function setRuntimeWrapperActive(host, active)')

    assert_contains_either(active_block, [
        "wrapper.classList.toggle('is-active', Boolean(active));",
        'wrapper.classList.toggle("is-active", Boolean(active));',
    ])
    assert '.chat-inline-runtime-wrap.is-active .chat-inline-runtime-disclosure' in css_source
    assert '.chat-inline-runtime-wrap.is-active > .chat-inline-runtime-host' not in css_source
    assert '.chat-inline-runtime-wrap.is-active > .chat-inline-runtime-source' not in css_source


def test_simple_tier_render_contract_uses_plain_text_path_for_normal_messages_and_keeps_long_code_enhancement_detection():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    render_mode_block = extract_js_block(chat_grid_source, 'resolveSimpleReaderRenderMode(message, source, enhancementMeta)')
    simple_block = extract_exact_js_method_block(chat_grid_source, 'renderMessageSimpleHtml(message)')

    assert_matches(
        r'resolveSimpleReaderRenderMode\(\s*message,\s*source,\s*enhancementMeta\s*,?\s*\)',
        simple_block,
    )
    assert 'enhancementMeta?.hasLongCode' in render_mode_block
    assert 'source.includes("```")' in render_mode_block
    assert_contains_either(render_mode_block, [
        "return 'literal';",
        'return "literal";',
    ])
    assert_contains_either(render_mode_block, [
        "return 'plain';",
        'return "plain";',
    ])
    assert_matches(
        r'decorateReaderRenderedHtml\(\s*baseHtml,\s*enhancementMeta,\s*enhancementPolicy',
        simple_block,
    )
    assert 'autoCollapseLongCode: this.readerViewSettings?.autoCollapseLongCode' in simple_block


def test_chat_reader_viewport_sync_preserves_scroll_and_idle_policy_split():
    chat_grid_source = read_project_file('static/js/components/chatGrid.js')
    schedule_block = extract_js_block(chat_grid_source, 'scheduleReaderViewportSync()')

    assert 'window.requestAnimationFrame' in schedule_block
    assert 'this.syncReaderViewportFloor({ force: false, nextTick: false });' in schedule_block
    assert 'window.setTimeout' in schedule_block
    assert 'this.syncReaderViewportFloor({ force: true, nextTick: false });' in schedule_block
