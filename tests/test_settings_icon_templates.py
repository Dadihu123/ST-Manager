from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SETTINGS_ICON_NAMES = {
    'security-status',
    'help-entry',
    'save',
    'background-upload',
    'wallpaper',
    'general-path',
    'advanced-settings',
    'integration',
    'warning',
    'connection-service',
    'path',
    'path-validation',
    'path-auto-detect',
    'key',
    'authentication',
    'data-backup',
    'tip',
    'sync-cards',
    'sync-quick-replies',
    'sync-chats',
    'sync-scan',
    'sync-worldbook',
    'sync-presets',
    'sync-regex',
    'appearance',
    'appearance-display',
    'maintenance',
    'maintenance-advanced',
    'show',
    'hide',
    'user-database',
    'resource-directory',
    'resource-sync',
}


def read_settings_template():
    return (PROJECT_ROOT / 'templates/modals/settings.html').read_text(encoding='utf-8')


def test_settings_and_help_icons_use_requested_assets_or_shared_icons():
    source = read_settings_template()

    for name in SETTINGS_ICON_NAMES:
        assert source.count(f"icon('settings-{name}'") > 0, name

    shared_icons = {
        "icon('header-settings'": 1,
        "icon('context-close'": 4,
        "icon('context-new'": 1,
        "icon('context-delete'": 2,
        "icon('header-dark-mode'": 1,
        "icon('header-light-mode'": 1,
    }
    for token, count in shared_icons.items():
        assert source.count(token) == count, token


def test_settings_icons_are_all_scaled_and_icon_frames_are_removed():
    source = read_settings_template()
    calls = re.findall(r"\{\{\s*icon\('[^']+',\s*'([^']+)'\)\s*\}\}", source)

    assert calls
    assert all('settings-icon--150' in class_name for class_name in calls)

    icons_css = (PROJECT_ROOT / 'static/css/modules/icons.css').read_text(encoding='utf-8')
    settings_css = (PROJECT_ROOT / 'static/css/modules/modal-settings.css').read_text(encoding='utf-8')

    assert '.settings-icon--150.ui-icon--xs' in icons_css
    assert '.settings-icon--150.ui-icon--sm' in icons_css
    assert '.settings-icon--150.ui-icon--md' in icons_css
    assert '.settings-title-mark,\n.nav-icon,\n.settings-help-title-mark' in settings_css
    assert 'border: 0;' in settings_css


def test_settings_svg_symbols_are_valid_and_background_free():
    source = (PROJECT_ROOT / 'static/icons/ui.svg').read_text(encoding='utf-8')

    for name in SETTINGS_ICON_NAMES:
        symbol = f'id="icon-settings-{name}"'
        assert symbol in source, symbol

    assert 'style="display: block; background: rgb(255, 255, 255);"' not in source


def test_settings_followup_icon_layout_and_theme_controls():
    source = read_settings_template()
    settings_css = (PROJECT_ROOT / 'static/css/modules/modal-settings.css').read_text(encoding='utf-8')

    assert '深浅色模式 (Light / Dark Mode)' in source
    assert 'class="settings-icon-button settings-theme-toggle"' in source
    assert "x-text=\"isDarkMode ? '深色模式' : '浅色模式'\"" in source
    assert 'class="btn-secondary settings-inline-action whitespace-nowrap"' not in source
    assert 'settings-background-upload-button' in source
    assert 'settings-background-clear-button' in source
    assert "icon('settings-background-upload', 'ui-icon--md settings-icon--150')" in source

    assert 'settings-path-action-icon--150' in source
    assert 'width: 1.96875rem;' in settings_css
    assert 'width: 2.3625rem;' in settings_css
    assert 'width: 2.475rem;' in settings_css
    assert 'settings-section-label-with-icon' in source
    assert source.count('class="settings-status-icon"') == 4
    assert 'settings-help-title-icon--150' in source
    assert '.settings-help-body h4 > [aria-hidden' in settings_css
    assert 'settings-icon-button--field-centered' in source
    assert '.settings-icon-button--field-centered:hover' in settings_css
    assert 'transform: translateY(-50%);' in settings_css
    assert '<h4 class="font-bold text-emerald-400 mb-2">' in source
