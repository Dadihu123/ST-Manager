from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_header_template():
    return (PROJECT_ROOT / 'templates/components/header.html').read_text(encoding='utf-8')


def test_header_and_global_menu_use_requested_icon_mappings():
    source = read_header_template()

    expected_counts = {
        "icon('header-import'": 2,
        "icon('header-menu'": 1,
        "icon('context-close'": 1,
        "icon('header-advanced-filter'": 2,
        "icon('context-new'": 2,
        "icon('header-url-import'": 2,
        "icon('header-refresh'": 2,
        "icon('header-dark-mode'": 2,
        "icon('header-light-mode'": 2,
        "icon('context-automation'": 4,
        "icon('header-settings'": 2,
        "icon('card-folder'": 4,
        "icon('context-delete'": 5,
    }

    for token, count in expected_counts.items():
        assert source.count(token) == count, token

    assert source.count('header-icon--150') == 31


def test_header_keeps_shared_dice_monitor_and_source_menu_arrow_icons():
    source = read_header_template()

    assert source.count('dice_icon(') == 2
    assert source.count("icon('monitor-pool-small'") == 2
    assert source.count("icon('chevron-down'") == 2
