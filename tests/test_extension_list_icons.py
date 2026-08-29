from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_extension_grid_uses_semantic_icon_mappings():
    source = read_project_file('templates/components/grid_extensions.html')

    expected_fragments = [
        "detail_icon('regex'",
        "detail_icon('script-file'",
        "detail_icon('quick-reply'",
        "icon('refresh'",
        "icon('upload'",
        "icon('loader-circle'",
        "icon('file-code'",
        "preset_icon('owner'",
        "preset_icon('empty-state'",
    ]

    for fragment in expected_fragments:
        assert fragment in source

    for emoji in ('🧩', '📜', '⚡', '↻', '📥', '⏳', '📄', '👤', '📭'):
        assert emoji not in source


def test_extension_list_icons_use_the_shared_integer_size_tiers():
    source = read_project_file('static/css/modules/icons.css')

    expected_sizes = {
        'sm': '16px',
        'md': '20px',
        'lg': '24px',
        'xl': '32px',
    }
    for size_name, size in expected_sizes.items():
        selector = f'.ui-icon--{size_name} {{'
        selector_start = source.index(selector)
        selector_block = source[selector_start:source.index('}', selector_start) + 1]
        assert f'width: {size};' in selector_block
        assert f'height: {size};' in selector_block

    assert '--150' not in source


def test_ui_sprite_contains_the_extension_file_asset_as_a_theme_aware_symbol():
    sprite_source = read_project_file('static/icons/ui.svg')
    root = ET.fromstring(sprite_source)
    namespace = '{http://www.w3.org/2000/svg}'
    symbol = next(
        symbol
        for symbol in root.findall(f'{namespace}symbol')
        if symbol.attrib.get('id') == 'icon-file-code'
    )

    assert symbol.attrib['viewBox'] == '361 347 1133 1548'
    assert 'fill="currentColor"' in ET.tostring(symbol, encoding='unicode')
    assert 'background' not in ET.tostring(symbol, encoding='unicode').lower()
