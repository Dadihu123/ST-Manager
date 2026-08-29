from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_header_template():
    return (PROJECT_ROOT / 'templates/components/header.html').read_text(encoding='utf-8')


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
