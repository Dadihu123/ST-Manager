from pathlib import Path
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_advanced_editor_uses_semantic_icon_mappings():
    source = read_project_file('templates/modals/advanced_editor.html')

    expected_fragments = [
        '{% from "components/icon.html" import icon, detail_icon %}',
        "icon('sliders-settings'",
        "icon('close'",
        "detail_icon('regex'",
        "detail_icon('script-file'",
        "detail_icon('quick-reply'",
        "icon('file-code'",
        "icon('file-import'",
        "icon('upload'",
        "icon('plus-square'",
        "icon('book-search'",
        "icon('replace'",
        "icon('scissors'",
        "icon('settings'",
        "icon('flask'",
        "icon('play'",
        "detail_icon('expand'",
        "icon('quick-actions'",
        "icon('code-file'",
        "icon('data-grid'",
        "icon('send-content'",
        "icon('bolt'",
        "icon('list'",
        "detail_icon('regex', 'ui-icon--lg ')",
        "detail_icon('script-file', 'ui-icon--lg ')",
    ]

    for fragment in expected_fragments:
        assert fragment in source

    for emoji in ('🛠️', '🧩', '📜', '📥', '📤', '🔍', '✨', '✂️', '🧪', '🎮', '📦', '📝', '⚡', '📋', '⤢'):
        assert emoji not in source

    assert 'title="上移"' in source
    assert 'title="下移"' in source
    assert 'title="删除正则脚本"' in source
    assert "icon('close-bold'" not in source
    assert "icon('arrow-right'" in source
    assert '运行时 (Runtime)' in source
    assert '<p>请在左侧选择一个条目进行详细编辑</p>' in source
    assert '👈 请在左侧选择一个条目进行详细编辑' not in source


def test_advanced_editor_uses_integer_icon_size_tiers():
    css = read_project_file('static/css/modules/icons.css')

    expected_sizes = {
        'xs': '12px',
        'sm': '16px',
        'md': '20px',
        'lg': '24px',
        'xl': '32px',
        '2xl': '48px',
        '3xl': '64px',
    }
    for size_name, size in expected_sizes.items():
        selector = f'.ui-icon--{size_name} {{'
        selector_start = css.index(selector)
        selector_block = css[selector_start:css.index('}', selector_start) + 1]
        assert f'width: {size};' in selector_block
        assert f'height: {size};' in selector_block

    assert '--150' not in css
    assert '1.125rem' not in css
    assert '1.3125rem' not in css
    assert '1.6875rem' not in css
    assert '2.25rem' not in css
    assert '4.5rem' not in css


def test_automation_uses_shared_file_rule_and_mobile_list_icons():
    source = read_project_file('templates/modals/automation.html')

    for fragment in (
        '{% from "components/icon.html" import icon, sidebar_icon, detail_icon %}',
        "icon('list'",
        "icon('file-import'",
        "icon('plus-square'",
        "icon('upload'",
        "icon('trash'",
        "icon('settings-save'",
        "icon('close'",
        "icon('workflow'",
        "icon('settings-help-entry'",
        "sidebar_icon('folder-open'",
        "detail_icon('tags'",
        "icon('heart'",
        "icon('merge'",
        "detail_icon('link-source'",
        "detail_icon('clock'",
        "icon('pencil-edit'",
        "detail_icon('file-name'",
        "icon('book-tip'",
        "icon('check'",
        "icon('forbidden'",
    ):
        assert fragment in source

    for emoji in ('📂', '🏷️', '🗑️', '★', '🔀', '🌐', '🕒', '🧩', '📝', '📚', '📄', '💡', '✅', '🚫', '🤖', '💾'):
        assert emoji not in source

    assert 'title="导入规则集">📥' not in source
    assert 'title="导出 JSON">\n                                📤' not in source
    assert 'title="删除规则">🗑️' not in source
    assert '<span class="text-xs font-bold">?</span>' not in source
    assert 'ⓘ' not in source


def test_automation_mobile_execution_template_uses_shared_toolbar_icons():
    source = read_project_file('templates/modals/execute_rules_mobile.html')

    for fragment in (
        '{% from "components/icon.html" import icon %}',
        "icon('workflow'",
        "icon('settings'",
    ):
        assert fragment in source

    for emoji in ('⚡', '⚙️'):
        assert emoji not in source


def test_automation_execution_notifications_use_shared_svg_icons():
    automation_js = read_project_file('static/js/components/automationModal.js')
    mobile_js = read_project_file('static/js/components/executeRulesMobileModal.js')
    context_menu_js = read_project_file('static/js/components/contextMenu.js')
    header_js = read_project_file('static/js/components/header.js')
    state_js = read_project_file('static/js/state.js')

    for fragment in (
        "showToast(`导入成功: ${res.name}`, 3000, 'check')",
        "showToast('已关闭全局自动规则', 3000, 'forbidden')",
        "showToast('规则集已保存', 3000, 'settings-save')",
    ):
        assert fragment in automation_js

    assert "showToast('执行完成！', 2400, 'check')" in mobile_js
    assert "showToast(error?.message || '批量执行失败', 3600, 'close')" in mobile_js
    assert "showToast('执行完成！', 2400, 'check')" in context_menu_js
    assert 'showToast("执行完成！", 2400, "check")' in header_js
    assert 'showToast(error?.message || "批量执行失败", 3600, "close")' in header_js
    assert '"forbidden"' in state_js
    assert '"settings-save"' in state_js


def test_advanced_editor_custom_symbols_are_theme_safe():
    sprite = ET.parse(PROJECT_ROOT / 'static/icons/ui.svg').getroot()
    symbols = {
        symbol.attrib['id']: symbol
        for symbol in sprite
        if symbol.tag.endswith('symbol')
    }
    expected_viewboxes = {
        'icon-flask': '53 71 490 529',
        'icon-replace': '29 71 584 543',
        'icon-scissors': '81 60 520 540',
        'icon-play': '92 62 397 487',
        'icon-quick-actions': '11 74 426 358',
        'icon-code-file': '35 61 426 388',
        'icon-data-grid': '55 54 410 417',
        'icon-send-content': '18 58 426 419',
        'icon-bolt': '25 32 424 418',
    }

    for symbol_id, viewbox in expected_viewboxes.items():
        assert symbol_id in symbols
        assert symbols[symbol_id].attrib['viewBox'] == viewbox
        serialized = ET.tostring(symbols[symbol_id], encoding='unicode').lower()
        assert 'background' not in serialized
        assert '#000000' not in serialized
        assert 'fill="currentcolor"' in serialized


def test_automation_custom_symbols_are_theme_safe():
    sprite = ET.parse(PROJECT_ROOT / 'static/icons/ui.svg').getroot()
    symbols = {
        symbol.attrib['id']: symbol
        for symbol in sprite
        if symbol.tag.endswith('symbol')
    }
    expected_viewboxes = {
        'icon-merge': '91 103 523 602',
        'icon-forbidden': '48 23 601 584',
    }

    for symbol_id, viewbox in expected_viewboxes.items():
        assert symbol_id in symbols
        assert symbols[symbol_id].attrib['viewBox'] == viewbox
        serialized = ET.tostring(symbols[symbol_id], encoding='unicode').lower()
        assert 'background' not in serialized
        assert '#000000' not in serialized
        assert 'fill="currentcolor"' in serialized
