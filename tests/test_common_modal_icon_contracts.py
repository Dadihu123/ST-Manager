"""通用弹窗 SVG 图标契约。"""

from pathlib import Path
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_common_modal_templates_use_requested_svg_mappings():
    expected_fragments = {
        'templates/modals/batch_import.html': (
            "icon('header-import'",
            "icon('context-close'",
            "detail_icon('overwrite'",
            "icon('context-rename'",
            "icon('automation-forbidden'",
            "icon('settings-warning'",
            "icon('card-check'",
            "icon('card-loader'",
        ),
        'templates/modals/import.html': (
            "icon('header-url-import'",
            "icon('settings-warning'",
            "detail_icon('source-link'",
            "sidebar_icon('category-expanded'",
            "sidebar_icon('folder'",
            "icon('modal-root-directory'",
            "detail_icon('locate'",
            "icon('header-import'",
            "detail_icon('overwrite'",
            "icon('context-rename'",
        ),
        'templates/modals/move_cards.html': (
            "sidebar_icon('category-expanded'",
            "sidebar_icon('folder'",
            "icon('modal-root-directory'",
            "detail_icon('locate'",
        ),
        'templates/modals/large_editor.html': (
            "icon('modal-document-edit'",
            "icon('worldbook-tip'",
            "icon('chevron-right'",
            'large-editor-nav-icon--reverse',
        ),
        'templates/modals/markdown_preview.html': (
            "icon('modal-document'",
            "icon('context-close'",
        ),
        'templates/modals/html_preview.html': (
            "detail_icon('read-mode'",
            "icon('context-close'",
        ),
        'templates/modals/rollback.html': (
            "icon('worldbook-rollback'",
            "icon('context-close'",
            "icon('card-loader'",
            'bg-red-500',
            'bg-green-500',
        ),
        'templates/modals/execute_rules_mobile.html': (
            "icon('context-automation'",
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
        ('icon-modal-root-directory', '0 0 530 504'),
        ('icon-modal-document', '0 0 851 1267'),
        ('icon-modal-document-edit', '0 0 824 1215'),
    ):
        assert symbol_id in symbols
        assert symbols[symbol_id].attrib['viewBox'] == viewbox
        serialized = ET.tostring(symbols[symbol_id], encoding='unicode').lower()
        assert 'background' not in serialized
        assert '#000000' not in serialized
        assert 'fill="currentcolor"' in serialized


def test_preset_detail_status_uses_svg_icons():
    source = read_project_file('templates/modals/detail_preset_popup.html')

    assert "icon('other-check', 'ui-icon--xs')" in source
    assert "icon('other-minus', 'ui-icon--xs')" in source
    assert "x-text=\"item.prompt_meta?.is_enabled ? '✓' : '−'\"" not in source
    assert "x-text=\"activeContextItem?.prompt_meta?.is_enabled ? '✓' : '−'\"" not in source


def test_card_import_and_move_success_toasts_use_the_card_check_icon():
    expected_calls = {
        'static/js/components/batchImportModal.js': "showToast(`成功导入 ${res.new_cards.length} 张卡片`, 3000, 'card-check')",
        'static/js/components/importModal.js': "showToast(`导入成功：${res.new_card.char_name}`, 3000, 'card-check')",
        'static/js/components/moveCardsModal.js': "showToast(`已移动 ${count} 张卡片`, 3000, 'card-check')",
        'static/js/components/cardGrid.js': "showToast(`已导入: ${cardName}`, 3000, 'card-check')",
        'static/js/components/detailModal.js': "showToast(`成功导入: \"${importedData.name}\"`, 3000, 'card-check')",
        'static/js/components/sidebar.js': "showToast(`已移动 ${count} 张卡片`, 3000, 'card-check')",
        'static/js/components/wiGrid.js': "showToast(`已移动 ${count} 本世界书`, 3000, 'card-check')",
        'static/js/components/wiEditor.js': "`已导入 ${uniqueBlocks.length} 条标签条目`,\n          2200,\n          'card-check'",
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
