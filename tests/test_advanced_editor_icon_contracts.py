from pathlib import Path
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_advanced_editor_uses_the_requested_icon_mappings():
    source = read_project_file('templates/modals/advanced_editor.html')

    expected_fragments = [
        '{% from "components/icon.html" import icon, detail_icon %}',
        "icon('settings-advanced-settings'",
        "icon('context-close'",
        "detail_icon('regex'",
        "detail_icon('scripts'",
        "detail_icon('quick-replies'",
        "icon('extension-file'",
        "icon('header-import'",
        "icon('card-upload'",
        "icon('context-new'",
        "icon('worldbook-search'",
        "icon('advanced-editor-replace'",
        "icon('advanced-editor-trim'",
        "icon('settings'",
        "icon('advanced-editor-test-lab'",
        "icon('advanced-editor-execute'",
        "detail_icon('expand'",
        "icon('advanced-editor-quick-buttons'",
        "icon('advanced-editor-script-code'",
        "icon('advanced-editor-data'",
        "icon('advanced-editor-send-content'",
        "icon('advanced-editor-trigger'",
        "icon('worldbook-list'",
        "detail_icon('regex', 'ui-icon--lg advanced-editor-icon--150')",
        "detail_icon('scripts', 'ui-icon--lg advanced-editor-icon--150')",
    ]

    for fragment in expected_fragments:
        assert fragment in source

    for emoji in ('🛠️', '🧩', '📜', '📥', '📤', '🔍', '✨', '✂️', '🧪', '🎮', '📦', '📝', '⚡', '📋', '⤢'):
        assert emoji not in source

    assert 'title="上移"' in source
    assert 'title="下移"' in source
    assert 'title="删除正则脚本"' in source
    assert '✕' in source
    assert '<span>▶ 运行时 (Runtime)</span>' in source
    assert '<p>请在左侧选择一个条目进行详细编辑</p>' in source
    assert '👈 请在左侧选择一个条目进行详细编辑' not in source


def test_advanced_editor_icon_sizes_have_150_percent_tokens():
    css = read_project_file('static/css/modules/icons.css')

    expected_sizes = {
        'xs': '1.125rem',
        'sm': '1.3125rem',
        'md': '1.6875rem',
        'lg': '2.25rem',
        'xl': '4.5rem',
    }
    for size_name, size in expected_sizes.items():
        selector = f'.advanced-editor-icon--150.ui-icon--{size_name}'
        selector_start = css.index(selector)
        selector_block = css[selector_start:css.index('}', selector_start) + 1]
        assert f'width: {size};' in selector_block
        assert f'height: {size};' in selector_block


def test_automation_uses_shared_file_rule_and_mobile_list_icons():
    source = read_project_file('templates/modals/automation.html')

    for fragment in (
        '{% from "components/icon.html" import icon %}',
        "icon('worldbook-list'",
        "icon('header-import'",
        "icon('context-new'",
        "icon('card-upload'",
        "icon('context-delete'",
    ):
        assert fragment in source

    assert 'title="导入规则集">📥' not in source
    assert 'title="导出 JSON">\n                                📤' not in source
    assert 'title="删除规则">🗑️' not in source


def test_advanced_editor_custom_symbols_are_theme_safe():
    sprite = ET.parse(PROJECT_ROOT / 'static/icons/ui.svg').getroot()
    symbols = {
        symbol.attrib['id']: symbol
        for symbol in sprite
        if symbol.tag.endswith('symbol')
    }
    expected_viewboxes = {
        'icon-advanced-editor-test-lab': '0 0 677 632',
        'icon-advanced-editor-replace': '0 0 715 658',
        'icon-advanced-editor-trim': '0 0 731 649',
        'icon-advanced-editor-execute': '0 0 590 602',
        'icon-advanced-editor-quick-buttons': '0 0 526 470',
        'icon-advanced-editor-script-code': '0 0 481 494',
        'icon-advanced-editor-data': '0 0 539 509',
        'icon-advanced-editor-send-content': '0 0 520 517',
        'icon-advanced-editor-trigger': '0 0 482 471',
    }

    for symbol_id, viewbox in expected_viewboxes.items():
        assert symbol_id in symbols
        assert symbols[symbol_id].attrib['viewBox'] == viewbox
        serialized = ET.tostring(symbols[symbol_id], encoding='unicode').lower()
        assert 'background' not in serialized
        assert '#000000' not in serialized
        assert 'fill="currentcolor"' in serialized
