from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SIDEBAR_ICON_NAMES = {
    'all-content',
    'tag-library',
    'global-directory',
    'folder',
    'all-cards-categories',
    'embedded',
    'bound',
    'unbound',
    'organize',
    'category-menu',
    'cards',
    'worldbook',
    'chats',
    'presets',
    'regex',
    'scripts',
    'quick-replies',
    'beautify',
}


def read_sidebar_template():
    return (PROJECT_ROOT / 'templates/components/sidebar.html').read_text(encoding='utf-8')


def test_sidebar_uses_the_new_asset_set_for_all_sidebar_specific_icons():
    source = read_sidebar_template()

    for name in SIDEBAR_ICON_NAMES:
        assert f"sidebar_icon('{name}'" in source, name

    assert not re.search(r'[\u2600-\u27bf\U0001f000-\U0001faff]', source)
    assert not re.search(r'[↻✓✕♥⋯▼▶☰−✗✔★]', source)
    assert '+ <span x-text="tagIndexVisibleTags.length - dynamicVisibleTagCount"' not in source


def test_sidebar_reuses_existing_shared_icons_for_common_actions():
    source = read_sidebar_template()

    expected_counts = {
        "icon('context-close'": 1,
        "icon('chevron-down'": 4,
        "icon('chevron-right'": 4,
        "icon('context-new'": 2,
        "icon('header-refresh'": 1,
    }

    for token, count in expected_counts.items():
        assert source.count(token) == count, token


def test_sidebar_sprite_symbols_are_valid_and_background_free():
    sprite_path = PROJECT_ROOT / 'static/icons/sidebar.svg'
    root = ET.parse(sprite_path).getroot()
    symbols = {
        element.get('id')
        for element in root
        if element.tag.rsplit('}', 1)[-1] == 'symbol'
    }

    assert symbols == {f'icon-sidebar-{name}' for name in SIDEBAR_ICON_NAMES}

    sprite_source = sprite_path.read_text(encoding='utf-8')
    assert 'background: rgb(255, 255, 255)' not in sprite_source
    assert 'M0,0 L947,0 L947,518 L0,518 Z' not in sprite_source


def test_sidebar_icon_layout_styles_cover_custom_aspect_ratio_and_labels():
    icons_css = (PROJECT_ROOT / 'static/css/modules/icons.css').read_text(encoding='utf-8')
    layout_css = (PROJECT_ROOT / 'static/css/modules/layout.css').read_text(encoding='utf-8')

    assert '.sidebar-icon {' in icons_css
    assert '.sidebar-icon--unbound {' in icons_css
    assert '.sidebar .ui-icon--xs {' in icons_css
    assert 'width: 1.125rem;' in icons_css
    assert '.sidebar .ui-icon--sm {' in icons_css
    assert 'width: 1.3125rem;' in icons_css
    assert '.sidebar .ui-icon--md {' in icons_css
    assert 'width: 1.6875rem;' in icons_css
    assert '.sidebar .sidebar-icon--unbound {' in icons_css
    assert 'width: 2.4rem;' in icons_css
    assert '.sidebar .sidebar-filter-label .ui-icon--sm {' in icons_css
    assert 'width: 1.96875rem;' in icons_css
    assert '.sidebar .sidebar-filter-label .sidebar-icon--unbound {' in icons_css
    assert 'width: 3.6rem;' in icons_css
    assert '.sidebar .sidebar-tag-library-label {' in icons_css
    assert 'gap: 0.25rem;' in icons_css
    assert '.sidebar .sidebar-tag-library-label .ui-icon--xs {' in icons_css
    assert '.sidebar .sidebar-tag-library-label .ui-icon--sm {' in icons_css
    assert '.sidebar-filter-label,' in layout_css
    assert '.sidebar-inline-label {' in layout_css


def test_sidebar_icon_macro_references_the_sidebar_sprite_namespace():
    source = (PROJECT_ROOT / 'templates/components/icon.html').read_text(encoding='utf-8')

    assert 'icons/sidebar.svg' in source
    assert '#icon-sidebar-{{ name }}' in source
