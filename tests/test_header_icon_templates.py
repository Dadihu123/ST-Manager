from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_header_template():
    return (PROJECT_ROOT / 'templates/components/header.html').read_text(encoding='utf-8')


def read_loading_template():
    return (PROJECT_ROOT / 'templates/components/loading.html').read_text(encoding='utf-8')


def read_layout_template():
    return (PROJECT_ROOT / 'templates/layout.html').read_text(encoding='utf-8')


def test_header_and_global_menu_use_semantic_icon_mappings():
    source = read_header_template()

    expected_counts = {
        "icon('file-import'": 2,
        "icon('menu'": 1,
        "icon('close'": 1,
        "icon('filter'": 2,
        "icon('plus-square'": 2,
        "icon('link-import'": 2,
        "icon('refresh'": 2,
        "icon('header-dark-mode'": 2,
        "icon('header-light-mode'": 2,
        "icon('workflow'": 4,
        "icon('settings-gear'": 2,
        "icon('folder'": 4,
        "icon('trash'": 5,
    }

    for token, count in expected_counts.items():
        assert source.count(token) == count, token

    assert 'header-icon--150' not in source


def test_header_keeps_shared_dice_monitor_and_source_menu_arrow_icons():
    source = read_header_template()

    assert source.count('dice_icon(') == 2
    assert source.count("icon('monitor-user'") == 2
    assert source.count("icon('chevron-down'") == 2


def test_brand_assets_are_used_in_header_and_loading_screen():
    header_source = read_header_template()
    loading_source = read_loading_template()

    assert header_source.count('images/brand/stm-mark.png') == 2
    assert "detail_icon('brand'" not in header_source
    assert 'images/brand/stm-lockup.png' in loading_source
    assert "detail_icon('brand'" not in loading_source


def test_browser_icon_uses_the_mark_and_legacy_ico_is_removed():
    layout_source = read_layout_template()
    views_source = (PROJECT_ROOT / 'core/api/views.py').read_text(encoding='utf-8')

    assert 'rel="icon"' in layout_source
    assert 'type="image/png"' in layout_source
    assert "images/brand/stm-mark.png" in layout_source
    assert "'stm-mark.png'" in views_source
    assert "'image/png'" in views_source
    assert not (PROJECT_ROOT / 'static/images/STM.ico').exists()


def test_brand_assets_are_trimmed_and_legacy_sprite_symbol_is_removed():
    expected_sizes = {
        'stm-mark.png': (256, 252),
        'stm-lockup.png': (499, 515),
    }
    max_file_sizes = {
        'stm-mark.png': 50_000,
        'stm-lockup.png': 100_000,
    }

    for filename, expected_size in expected_sizes.items():
        asset_path = PROJECT_ROOT / 'static/images/brand' / filename
        with Image.open(asset_path) as image:
            assert image.size == expected_size
            assert image.mode in {'P', 'RGBA'}
            assert image.convert('RGBA').getchannel('A').getbbox() == (0, 0, *expected_size)
        assert asset_path.stat().st_size < max_file_sizes[filename]

    detail_sprite = (PROJECT_ROOT / 'static/icons/detail.svg').read_text(encoding='utf-8')
    assert 'id="icon-brand"' not in detail_sprite
