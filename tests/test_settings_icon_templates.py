from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


SETTINGS_ICON_NAMES = {
    'shield-check',
    'settings-help-entry',
    'settings-save',
    'image-upload',
    'wallpaper',
    'directory-root',
    'sliders-settings',
    'plug',
    'alert-triangle',
    'settings-connection-service',
    'folder-path',
    'file-check',
    'folder-search',
    'key',
    'shield-key',
    'database-backup',
    'idea',
    'cards-sync',
    'replies-sync',
    'chats-sync',
    'scan',
    'book-sync',
    'presets-sync',
    'regex-sync',
    'palette',
    'display',
    'settings-maintenance',
    'settings-maintenance-advanced',
    'eye',
    'eye-off',
    'database-user',
    'folder-resources',
    'folder-sync',
}


def read_settings_template():
    return (PROJECT_ROOT / 'templates/modals/settings.html').read_text(encoding='utf-8')


def test_settings_and_help_icons_use_requested_assets_or_shared_icons():
    source = read_settings_template()

    for name in SETTINGS_ICON_NAMES:
        assert source.count(f"icon('{name}'") > 0, name

    shared_icons = {
        "icon('settings-gear'": 1,
        "icon('close'": 4,
        "icon('plus-square'": 1,
        "icon('trash'": 2,
        "icon('header-dark-mode'": 1,
        "icon('header-light-mode'": 1,
    }
    for token, count in shared_icons.items():
        assert source.count(token) == count, token


def test_settings_icons_use_shared_integer_tiers_and_no_icon_frames():
    source = read_settings_template()
    calls = re.findall(r"\{\{\s*icon\('[^']+',\s*'([^']+)'\)\s*\}\}", source)

    assert calls
    assert all('ui-icon--' in class_name for class_name in calls)

    icons_css = (PROJECT_ROOT / 'static/css/modules/icons.css').read_text(encoding='utf-8')
    settings_css = (PROJECT_ROOT / 'static/css/modules/modal-settings.css').read_text(encoding='utf-8')

    assert '.ui-icon--xs {' in icons_css
    assert '.ui-icon--sm {' in icons_css
    assert '.ui-icon--md {' in icons_css
    assert 'width: 12px;' in icons_css
    assert 'width: 16px;' in icons_css
    assert 'width: 20px;' in icons_css
    assert '--150' not in icons_css
    assert '.settings-title-mark,\n.nav-icon,\n.settings-help-title-mark' in settings_css
    assert 'border: 0;' in settings_css


def test_settings_svg_symbols_are_valid_and_background_free():
    source = (PROJECT_ROOT / 'static/icons/ui.svg').read_text(encoding='utf-8')

    for name in SETTINGS_ICON_NAMES:
        symbol = f'id="icon-{name}"'
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
    assert "icon('image-upload', 'ui-icon--md ')" in source

    assert 'settings-path-action-icon--150' not in source
    assert 'width: 2.3625rem;' in settings_css
    assert 'width: 2.475rem;' in settings_css
    assert '.nav-icon .ui-icon {' in settings_css
    assert 'width: 16px;' in settings_css
    assert 'height: 16px;' in settings_css
    assert '--150' not in settings_css
    assert 'settings-section-label-with-icon' in source
    assert source.count('class="settings-status-icon"') == 4
    assert 'settings-help-title-icon--150' not in source
    assert '.settings-help-body h4 > [aria-hidden' in settings_css
    assert 'settings-icon-button--field-centered' in source
    assert '.settings-icon-button--field-centered:hover' in settings_css
    assert 'transform: translateY(-50%);' in settings_css
    assert '<h4 class="font-bold text-emerald-400 mb-2">' in source


def test_settings_path_trash_and_number_controls_use_shared_visual_contract():
    source = read_settings_template()
    settings_css = (PROJECT_ROOT / 'static/css/modules/modal-settings.css').read_text(encoding='utf-8')
    settings_js = (PROJECT_ROOT / 'static/js/components/settingsModal.js').read_text(encoding='utf-8')

    assert 'settings-path-open-button' in source
    assert 'settings-path-open-icon' in source
    assert '.settings-path-open-button' in settings_css
    assert 'border: 0;' in settings_css
    assert 'height: 2.35rem;' in settings_css

    assert 'settings-trash-open-icon' in source
    assert '.settings-trash-open-icon.ui-icon--sm {' in settings_css
    assert 'height: 16px;' in settings_css

    assert source.count('class="settings-number-control') == 6
    assert source.count('class="settings-number-stepper"') == 6
    assert source.count('class="settings-number-stepper-btn"') == 12
    assert source.count('class="form-input settings-number-input"') == 6
    assert 'adjustNumberSetting(field, delta, min = null, max = null)' in settings_js
    assert 'settings-number-input::-webkit-inner-spin-button' in settings_css
    assert '.settings-number-stepper-btn:hover' in settings_css
    assert '.settings-number-stepper-btn:focus-visible' in settings_css
