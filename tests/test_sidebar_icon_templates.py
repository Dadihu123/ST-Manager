from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SIDEBAR_CONTENT_ICON_NAMES = {
    'all-content',
    'tag-library',
    'global-directory',
    'folder',
    'all-cards-categories',
    'category-expanded',
    'embedded',
    'bound',
    'unbound',
    'organize',
    'category-menu',
}

MODULE_DETAIL_ICON_NAMES = {
    'worldbook',
    'chat',
    'preset',
    'regex',
    'scripts',
    'quick-replies',
}


def read_sidebar_template():
    return (PROJECT_ROOT / 'templates/components/sidebar.html').read_text(encoding='utf-8')


def test_sidebar_uses_the_sidebar_sprite_for_content_specific_icons():
    source = read_sidebar_template()

    for name in SIDEBAR_CONTENT_ICON_NAMES:
        assert f"sidebar_icon('{name}'" in source, name

    assert not re.search(r'[\u2600-\u27bf\U0001f000-\U0001faff]', source)
    assert not re.search(r'[↻✓✕♥⋯▼▶☰−✗✔★]', source)
    assert '+ <span x-text="tagIndexVisibleTags.length - dynamicVisibleTagCount"' not in source


def test_module_navigation_reuses_detail_and_custom_icon_assets():
    source = read_sidebar_template()
    icons_css = (PROJECT_ROOT / 'static/css/modules/icons.css').read_text(encoding='utf-8')
    navigation_source = source.split('<!-- === 模式 1', 1)[0]

    assert 'detail_icon' in source
    for name in MODULE_DETAIL_ICON_NAMES:
        assert source.count(f"detail_icon('{name}'") == 2, name

    assert source.count('sidebar-module-image-icon--cards') == 2
    assert source.count('sidebar-module-image-icon--beautify') == 3
    assert "sidebar_icon('cards'" not in navigation_source
    assert "sidebar_icon('beautify'" not in navigation_source

    for class_name in (
        '.sidebar-module-image-icon--cards',
        '.sidebar-module-image-icon--beautify',
    ):
        assert class_name in icons_css
        assert 'mask-image: url(' in icons_css


def test_beautify_icon_uses_a_cropped_canvas_at_the_shared_navigation_size():
    asset_source = (
        PROJECT_ROOT / 'static/icons/sidebar-nav/美化-简.svg'
    ).read_text(encoding='utf-8')
    beautify_css = (
        PROJECT_ROOT / 'static/css/modules/view-beautify.css'
    ).read_text(encoding='utf-8')

    assert 'viewBox="835 235 1082 1067"' in asset_source
    assert 'background: rgb(255, 255, 255)' not in asset_source
    assert (
        '.beautify-title-icon .sidebar-module-image-icon {\n'
        '  width: 30px;\n'
        '  height: 30px;\n'
        '  flex-basis: 30px;\n'
        '}'
    ) in beautify_css


def test_sidebar_reuses_existing_shared_icons_for_common_actions():
    source = read_sidebar_template()

    expected_counts = {
        "icon('context-close'": 1,
        "icon('chevron-down'": 5,
        "icon('chevron-right'": 4,
        "icon('context-new'": 2,
        "icon('header-refresh'": 1,
    }

    for token, count in expected_counts.items():
        assert source.count(token) == count, token


def test_beautify_refresh_button_matches_extension_list_button_sizing():
    sidebar_source = read_sidebar_template()
    extension_source = (
        PROJECT_ROOT / 'templates/components/grid_extensions.html'
    ).read_text(encoding='utf-8')

    expected_button_classes = 'btn-secondary px-3 py-1 text-xs flex items-center gap-1'
    assert expected_button_classes in sidebar_source
    assert expected_button_classes in extension_source
    assert "icon('header-refresh', 'ui-icon--sm header-icon--150')" in sidebar_source
    assert "icon('header-refresh', 'ui-icon--sm extension-list-icon--150')" in extension_source


def test_sidebar_sprite_symbols_are_valid_and_background_free():
    sprite_path = PROJECT_ROOT / 'static/icons/sidebar.svg'
    root = ET.parse(sprite_path).getroot()
    symbols = {
        element.get('id')
        for element in root
        if element.tag.rsplit('}', 1)[-1] == 'symbol'
    }

    all_sidebar_icon_names = SIDEBAR_CONTENT_ICON_NAMES | {
        'cards',
        'worldbook',
        'chats',
        'presets',
        'regex',
        'scripts',
        'quick-replies',
        'beautify',
    }
    assert symbols == {f'icon-sidebar-{name}' for name in all_sidebar_icon_names}

    sprite_source = sprite_path.read_text(encoding='utf-8')
    assert 'background: rgb(255, 255, 255)' not in sprite_source
    assert 'M0,0 L947,0 L947,518 L0,518 Z' not in sprite_source


def test_unbound_sidebar_icon_uses_theme_color_from_the_updated_asset():
    sprite_path = PROJECT_ROOT / 'static/icons/sidebar.svg'
    root = ET.parse(sprite_path).getroot()
    symbol = next(
        element
        for element in root
        if element.get('id') == 'icon-sidebar-unbound'
    )
    paths = [
        element
        for element in symbol
        if element.tag.rsplit('}', 1)[-1] == 'path'
    ]

    assert symbol.get('viewBox') == '163 197 1789 1265'
    assert len(paths) == 7
    assert all(path.get('fill') == 'currentColor' for path in paths)
    assert all(path.get('stroke') == 'none' for path in paths)
    assert all('style' not in path.attrib for path in paths)


def test_sidebar_icon_layout_styles_cover_custom_aspect_ratio_and_labels():
    source = read_sidebar_template()
    icons_css = (PROJECT_ROOT / 'static/css/modules/icons.css').read_text(encoding='utf-8')
    layout_css = (PROJECT_ROOT / 'static/css/modules/layout.css').read_text(encoding='utf-8')

    assert '.sidebar-icon {' in icons_css
    assert '.sidebar-icon--unbound {' in icons_css
    assert '.sidebar .ui-icon--xs {' in icons_css
    assert 'width: 16px;' in icons_css
    assert '.sidebar .ui-icon--sm {' in icons_css
    assert 'width: 20px;' in icons_css
    assert '.sidebar .ui-icon--md {' in icons_css
    assert 'width: 24px;' in icons_css
    assert '.sidebar .sidebar-filter-label .ui-icon--sm {' in icons_css
    assert 'width: 24px;' in icons_css
    assert '.sidebar .sidebar-filter-label .sidebar-icon--unbound {' in icons_css
    assert (
        '.sidebar .sidebar-filter-label .sidebar-icon--unbound {\n'
        '  width: 24px;\n'
        '  height: 24px;\n'
        '}'
    ) in icons_css
    assert '.sidebar .sidebar-category-root-icon.ui-icon--sm {' in icons_css
    assert 'sidebar-category-root-icon' in source
    assert '.sidebar .sidebar-tag-library-label {' in icons_css
    assert 'gap: 0.25rem;' in icons_css
    assert '.sidebar .sidebar-tag-library-label .ui-icon--xs {' in icons_css
    assert '.sidebar .sidebar-tag-library-label .ui-icon--sm {' in icons_css
    assert 'width: 16px;' in icons_css
    assert 'width: 20px;' in icons_css
    assert '.sidebar-filter-label,' in layout_css
    assert '.sidebar-inline-label {' in layout_css
    assert 'sidebar-tag-library-button' in source
    assert 'sidebar-tag-library-text' in source
    assert '.sidebar-tag-library-button:hover .sidebar-tag-library-text' in layout_css
    assert 'text-decoration-line: underline;' in layout_css
    assert '.sidebar-module-menu-item > span:last-child' in layout_css
    assert 'justify-content: flex-start;' in layout_css
    assert 'text-align: left;' in layout_css


def test_sidebar_category_rows_switch_to_the_expanded_folder_icon():
    source = read_sidebar_template()

    assert source.count("sidebar_icon('category-expanded'") == 3
    assert source.count("sidebar_icon('folder'") >= 6


def test_sidebar_icon_macro_references_the_sidebar_sprite_namespace():
    source = (PROJECT_ROOT / 'templates/components/icon.html').read_text(encoding='utf-8')

    assert 'icons/sidebar.svg' in source
    assert '#icon-sidebar-{{ name }}' in source
