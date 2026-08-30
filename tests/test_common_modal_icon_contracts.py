"""通用弹窗 SVG 图标契约。"""

from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_common_modal_templates_use_semantic_svg_mappings():
    expected_fragments = {
        'templates/modals/batch_import.html': (
            "icon('file-import'",
            "icon('close'",
            "detail_icon('overwrite'",
            "icon('pencil-edit'",
            "icon('forbidden'",
            "icon('alert-triangle'",
            "icon('check'",
            "icon('loader-circle'",
        ),
        'templates/modals/import.html': (
            "icon('link-import'",
            "icon('alert-triangle'",
            "detail_icon('link-source'",
            "sidebar_icon('folder-open'",
            "sidebar_icon('folder-solid'",
            "icon('folder-root'",
            "detail_icon('locate'",
            "icon('file-import'",
            "detail_icon('overwrite'",
            "icon('pencil-edit'",
        ),
        'templates/modals/move_cards.html': (
            "sidebar_icon('folder-open'",
            "sidebar_icon('folder-solid'",
            "icon('folder-root'",
            "detail_icon('locate'",
        ),
        'templates/modals/large_editor.html': (
            "icon('file-edit'",
            "icon('book-tip'",
            "icon('chevron-right'",
            'large-editor-nav-icon--reverse',
        ),
        'templates/modals/markdown_preview.html': (
            "icon('file'",
            "icon('close'",
        ),
        'templates/modals/html_preview.html': (
            "detail_icon('book-read'",
            "icon('close'",
        ),
        'templates/modals/rollback.html': (
            "icon('history-rollback'",
            "icon('close'",
            "icon('loader-circle'",
                'color-surface-danger-solid',
                'color-surface-success-solid',
        ),
        'templates/modals/execute_rules_mobile.html': (
            "icon('workflow'",
            "icon('settings'",
        ),
    }

    for relative_path, fragments in expected_fragments.items():
        source = read_project_file(relative_path)
        for fragment in fragments:
            assert fragment in source

    mapped_glyphs = (
        '📥',
        '✕',
        '➕',
        '🔄',
        '🚫',
        '⚠️',
        '✅',
        '⏳',
        '🌍',
        '🔗',
        '📂',
        '📁',
        '🏠',
        '📍',
        '📝',
        '◀',
        '▶',
        '📄',
        '👁',
        '⏪',
        '🛑',
        '🟢',
        '⚡',
        '⚙️',
    )
    for relative_path in expected_fragments:
        source = read_project_file(relative_path)
        assert not any(glyph in source for glyph in mapped_glyphs)


def test_icon_select_contract_covers_import_batch_and_automation_controls():
    import_template = read_project_file('templates/modals/import.html')
    move_template = read_project_file('templates/modals/move_cards.html')
    batch_template = read_project_file('templates/modals/batch_import.html')
    automation_template = read_project_file('templates/modals/automation.html')
    automation_css = read_project_file('static/css/modules/modal-automation.css')

    for source in (import_template, move_template):
        assert 'role="listbox"' in source
        assert 'sidebar_icon(\'folder-open\'' in source
        assert 'sidebar_icon(\'folder-solid\'' in source
        assert 'icon(\'folder-root\'' in source
        assert '<select' not in source

    assert 'role="listbox" aria-label="冲突处理方式"' in batch_template
    assert "icon('pencil-edit'" in batch_template
    assert "detail_icon('overwrite'" in batch_template
    assert "icon('forbidden'" in batch_template

    assert 'role="listbox" aria-label="执行动作"' in automation_template
    assert 'actionTypeOptions' in automation_template
    assert 'automation-help-trigger' in automation_template
    assert "icon('settings-help-entry', 'ui-icon--md')" in automation_template
    assert 'border border-gray-500' not in automation_template
    assert '.automation-export-btn' in automation_css


def test_url_import_input_keeps_icon_gutter_on_mobile():
    import_template = read_project_file('templates/modals/import.html')
    modal_css = read_project_file('static/css/modules/modal-tools.css')

    assert 'class="form-input import-url-input"' in import_template
    assert modal_css.index('.import-url-input') > modal_css.index('padding: 0.5rem !important;')
    input_css = modal_css.split('.import-url-input', 1)[1].split('}', 1)[0]
    assert 'box-sizing: border-box;' in input_css
    assert 'padding-left: 2.5rem !important;' in input_css


def test_repeated_action_menus_ignore_sibling_outside_click_handlers():
    automation_template = read_project_file('templates/modals/automation.html')
    automation_js = read_project_file('static/js/components/automationModal.js')
    batch_template = read_project_file('templates/modals/batch_import.html')
    batch_js = read_project_file('static/js/components/batchImportModal.js')

    assert '@click.outside="closeActionMenu($event)"' in automation_template
    assert 'closeActionMenu(event = null)' in automation_js
    assert "event?.target?.closest?.('.automation-action-type-select')" in automation_js
    assert '@click.outside="closeConflictActionMenu($event)"' in batch_template
    assert 'closeConflictActionMenu(event = null)' in batch_js
    assert "event?.target?.closest?.('.batch-import-action-select')" in batch_js


def test_source_monitor_schedule_select_opens_above_scroll_panel_bottom():
    monitor_template = read_project_file('templates/modals/source_update_monitor.html')
    monitor_css = read_project_file('static/css/modules/modal-source-update-monitor.css')

    assert 'source-monitor-schedule-select' in monitor_template
    assert 'menu_class="source-monitor-schedule-menu"' in monitor_template
    menu_block = monitor_css.split(
        '.source-monitor-schedule-select .source-monitor-schedule-menu', 1
    )[1].split('}', 1)[0]
    assert 'top: auto;' in menu_block
    assert 'bottom: calc(100% + 0.35rem);' in menu_block


def test_project_single_selects_reuse_shared_shell_without_touching_sidebar_or_multiselects():
    templates_root = PROJECT_ROOT / 'templates'
    sidebar_source = read_project_file('templates/components/sidebar.html')

    assert '<select' in sidebar_source
    assert 'styled_select' not in sidebar_source

    for template_path in templates_root.rglob('*.html'):
        relative_path = template_path.relative_to(templates_root).as_posix()
        if relative_path in {'components/styled_select.html', 'components/sidebar.html'}:
            continue
        source = template_path.read_text(encoding='utf-8')
        select_tags = re.findall(r'<select\b[^>]*>', source, re.IGNORECASE | re.DOTALL)
        single_select_tags = [
            tag for tag in select_tags
            if not re.search(r'\bmultiple(?:\s|=|>)', tag, re.IGNORECASE)
        ]
        assert not single_select_tags, f'unstyled single select remains in {template_path}'


def test_worldinfo_open_select_can_escape_props_group_clipping():
    worldinfo_css = read_project_file('static/css/modules/view-wi.css')

    assert '.props-group:has(.icon-select.is-open)' in worldinfo_css
    open_group_block = worldinfo_css.split('.props-group:has(.icon-select.is-open)', 1)[1].split('}', 1)[0]
    assert 'z-index: var(--z-dropdown);' in open_group_block
    assert 'overflow: visible;' in open_group_block


def test_other_open_selects_can_escape_known_rounded_clipping_shells():
    automation_css = read_project_file('static/css/modules/modal-automation.css')
    layout_css = read_project_file('static/css/modules/layout.css')
    batch_template = read_project_file('templates/modals/batch_import.html')

    assert '.rule-card:has(.icon-select.is-open)' in automation_css
    assert '.batch-import-card:has(.batch-import-action-select.is-open)' in automation_css
    assert '.header-search-container:has(.icon-select.is-open)' in layout_css
    assert 'class="batch-import-card rounded border transition-colors overflow-hidden"' in batch_template

    for selector, source in (
        ('.rule-card:has(.icon-select.is-open)', automation_css),
        ('.batch-import-card:has(.batch-import-action-select.is-open)', automation_css),
        ('.header-search-container:has(.icon-select.is-open)', layout_css),
    ):
        open_shell_block = source.split(selector, 1)[1].split('}', 1)[0]
        assert 'z-index: var(--z-dropdown);' in open_shell_block
        assert 'overflow: visible;' in open_shell_block


def test_forum_preview_icons_are_kept_as_separate_svg_assets():
    css = read_project_file('static/css/modules/modal-forum-preview.css')
    template = read_project_file('templates/modals/forum_thread_preview.html')

    for name in ('date', 'time', 'reply', 'reaction', 'view', 'close'):
        asset = PROJECT_ROOT / f'static/icons/forum-preview/{name}.svg'
        ET.parse(asset)
        assert f'forum-preview/{name}.svg' in css
        assert f'forum-preview-raw-icon--{name}' in template


def test_common_modal_custom_symbols_are_theme_safe():
    sprite = ET.parse(PROJECT_ROOT / 'static/icons/ui.svg').getroot()
    symbols = {
        symbol.attrib['id']: symbol
        for symbol in sprite
        if symbol.tag.endswith('symbol')
    }

    for symbol_id, viewbox in (
        ('icon-folder-root', '18 33 436 428'),
        ('icon-file', '87 93 660 1044'),
        ('icon-file-edit', '51 54 728 1044'),
    ):
        assert symbol_id in symbols
        assert symbols[symbol_id].attrib['viewBox'] == viewbox
        serialized = ET.tostring(symbols[symbol_id], encoding='unicode').lower()
        assert 'background' not in serialized
        assert '#000000' not in serialized
        assert 'fill="currentcolor"' in serialized


def test_preset_detail_status_uses_svg_icons():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "icon('check-bold', 'ui-icon--xs')" in source
    assert "icon('minus', 'ui-icon--xs')" in source
    assert "x-text=\"item.prompt_meta?.is_enabled ? '✓' : '−'\"" not in source
    assert "x-text=\"activeContextItem?.prompt_meta?.is_enabled ? '✓' : '−'\"" not in source


def test_card_import_and_move_success_toasts_use_the_shared_check_icon():
    expected_calls = {
        'static/js/components/batchImportModal.js': "showToast(`成功导入 ${res.new_cards.length} 张卡片`, 3000, 'check')",
        'static/js/components/importModal.js': "showToast(`导入成功：${res.new_card.char_name}`, 3000, 'check')",
        'static/js/components/moveCardsModal.js': "showToast(`已移动 ${count} 张卡片`, 3000, 'check')",
        'static/js/components/cardGrid.js': "showToast(`已导入: ${cardName}`, 3000, 'check')",
        'static/js/components/detailModal.js': "showToast(`成功导入: \"${importedData.name}\"`, 3000, 'check')",
        'static/js/components/sidebar.js': "showToast(`已移动 ${count} 张卡片`, 3000, 'check')",
        'static/js/components/wiGrid.js': "showToast(`已移动 ${count} 本世界书`, 3000, 'check')",
        'static/js/components/wiEditor.js': "`已导入 ${uniqueBlocks.length} 条标签条目`,\n          2200,\n          'check'",
    }

    for relative_path, expected_call in expected_calls.items():
        assert expected_call in read_project_file(relative_path)

    legacy_calls = {
        'static/js/components/batchImportModal.js': 'showToast(`✅ 成功导入 ${res.new_cards.length} 张卡片`)',
        'static/js/components/importModal.js': 'showToast(`✅ 导入成功：${res.new_card.char_name}`, 3000)',
        'static/js/components/moveCardsModal.js': 'showToast(`✅ 已移动 ${count} 张卡片`)',
        'static/js/components/cardGrid.js': 'showToast(`✅ 已导入: ${cardName}`)',
        'static/js/components/detailModal.js': 'showToast(`✅ 成功导入: "${importedData.name}"`)',
        'static/js/components/sidebar.js': 'showToast(`✅ 已移动 ${count} 张卡片`)',
        'static/js/components/wiGrid.js': 'showToast(`✅ 已移动 ${count} 本世界书`)',
        'static/js/components/wiEditor.js': '`✅ 已导入 ${uniqueBlocks.length} 条标签条目`',
    }
    for relative_path, legacy_call in legacy_calls.items():
        assert legacy_call not in read_project_file(relative_path)
