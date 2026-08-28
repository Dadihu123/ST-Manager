from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WORLD_BOOK_SYMBOLS = (
    'worldbook-save-all',
    'worldbook-backup',
    'worldbook-entry-rollback',
    'worldbook-back',
    'worldbook-rollback',
    'worldbook-clipboard',
    'worldbook-snapshot',
    'worldbook-save-as',
    'worldbook-sort',
    'worldbook-calendar',
    'worldbook-search',
    'worldbook-constant',
    'worldbook-vectorize',
    'worldbook-layout',
    'worldbook-tip',
    'worldbook-keyword-trigger',
    'worldbook-list',
    'worldbook-shortcut',
    'worldbook-closed',
)

LEGACY_FUNCTIONAL_GLYPHS = (
    '🌎',
    '📂',
    '📤',
    '📥',
    '✏️',
    '📝',
    '🚀',
    '⏳',
    '📖',
    '📅',
    '🔍',
    '🔎',
    '✕',
    '⏪',
    '📸',
    '💾',
    '🗂️',
    '◀',
    '▶',
    '↩',
    '↺',
    '🕰️',
    '🔵',
    '📎',
    '👁',
    '▼',
    '✅',
    '🚫',
    '⚠️',
    '➕',
    '🗑️',
)


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_worldbook_design_symbols_are_theme_safe():
    source = _read('static/icons/ui.svg')
    design_block = source.split('<!-- 世界书套件专用图标', 1)[1]

    assert 'background' not in design_block
    assert '#000000' not in design_block

    for name in WORLD_BOOK_SYMBOLS:
        assert f'id="icon-{name}"' in design_block

    for name, view_box in (
        ('worldbook-constant', '0 0 596 727'),
        ('worldbook-vectorize', '0 0 689 735'),
        ('worldbook-layout', '0 0 666 715'),
        ('worldbook-tip', '0 0 648 747'),
        ('worldbook-keyword-trigger', '0 0 729 897'),
        ('worldbook-list', '0 0 660 544'),
        ('worldbook-shortcut', '0 0 709 607'),
    ):
        assert f'<symbol id="icon-{name}" viewBox="{view_box}">' in design_block
    assert design_block.count('fill="currentColor"') >= len(WORLD_BOOK_SYMBOLS)


def test_worldbook_templates_use_shared_icons_for_functional_controls():
    template_paths = (
        'templates/components/grid_wi.html',
        'templates/modals/detail_wi_popup.html',
        'templates/modals/detail_wi_fullscreen.html',
        'templates/modals/detail_card.html',
    )

    for relative_path in template_paths:
        source = _read(relative_path)
        assert '{% from "components/icon.html" import icon' in source

    assert '{% from "components/icon.html" import icon %}' in _read(
        'templates/components/grid_wi.html'
    )
    for relative_path in template_paths[1:]:
        assert '{% from "components/icon.html" import icon, sidebar_icon %}' in _read(
            relative_path
        )

    grid_source = _read('templates/components/grid_wi.html')
    popup_source = _read('templates/modals/detail_wi_popup.html')
    fullscreen_source = _read('templates/modals/detail_wi_fullscreen.html')
    detail_card_source = _read('templates/modals/detail_card.html')

    fullscreen_controls = fullscreen_source.split('<!-- 帮助指南模态框 -->', 1)[0]
    detail_card_worldbook = detail_card_source.split('<!-- TAB: 世界书', 1)[1].split(
        "x-show=\"tab==='chats'\"", 1
    )[0]

    for source in (
        grid_source,
        popup_source,
        fullscreen_controls,
        detail_card_worldbook,
    ):
        assert not any(glyph in source for glyph in LEGACY_FUNCTIONAL_GLYPHS)

    assert "icon('worldbook-save-all'" in fullscreen_controls
    assert "icon('worldbook-entry-rollback'" in fullscreen_controls
    assert "icon('worldbook-vectorize'" in fullscreen_controls
    assert "icon('worldbook-calendar'" in popup_source
    assert "icon('worldbook-search'" in popup_source
    assert "icon('worldbook-snapshot'" in popup_source

    assert "icon('card-upload'" in grid_source
    assert "icon('card-check'" in grid_source
    assert "icon('card-folder'" in grid_source
    assert "icon('card-sticky-note'" in grid_source
    assert "icon('card-send'" in grid_source
    assert "icon('card-loader'" in grid_source
    assert "icon('context-rename'" in popup_source
    assert "icon('context-close'" in popup_source
    assert "icon('card-send'" in popup_source
    assert "icon('card-loader'" in popup_source
    assert "icon('header-import'" in fullscreen_controls
    assert "icon('worldbook-search'" in fullscreen_controls
    assert "icon('worldbook-constant'" in fullscreen_controls
    assert "icon('search'" not in fullscreen_controls
    assert "icon('circle-dot'" not in fullscreen_controls
    assert "icon('settings-save'" in fullscreen_controls
    assert "icon('settings-help-entry'" in fullscreen_controls
    assert "icon('context-new'" in fullscreen_controls
    assert "icon('context-delete'" in fullscreen_controls
    assert "icon('settings-warning'" in fullscreen_controls
    assert "icon('settings-advanced-settings'" in fullscreen_controls
    assert "icon('settings-show'" in fullscreen_controls
    assert "icon('header-import'" in detail_card_worldbook
    assert "icon('card-upload'" in detail_card_worldbook
    assert "icon('header-import'" in grid_source
    assert "icon('worldbook-closed'" in grid_source
    assert "icon('worldbook-save-as'" not in grid_source
    assert "icon('context-rename'" in fullscreen_controls
    assert "icon('context-new'" in detail_card_worldbook
    assert "icon('context-delete'" in detail_card_worldbook


def test_worldbook_help_reuses_shared_icons_without_functional_glyphs():
    source = _read('templates/modals/detail_wi_fullscreen.html')
    help_source = source.split('<!-- 帮助指南模态框 -->', 1)[1]

    for name in (
        'settings-save',
        'worldbook-save-all',
        'worldbook-save-as',
        'worldbook-rollback',
        'worldbook-entry-rollback',
        'worldbook-backup',
        'worldbook-clipboard',
        'context-new',
        'settings-warning',
        'settings-advanced-settings',
        'worldbook-constant',
        'worldbook-vectorize',
        'worldbook-layout',
        'worldbook-tip',
        'worldbook-keyword-trigger',
        'worldbook-list',
        'worldbook-shortcut',
        'worldbook-search',
    ):
        assert f"icon('{name}'" in help_source

    for glyph in (
        '🖥️',
        '💡',
        '🟢',
        '📋',
        '⌨️',
        '💾',
        '🗂️',
        '📤',
        '⏪',
        '🕰️',
        '📂',
        '➕',
        '⚠️',
        '⚙️',
        '🔵',
        '📎',
        '🔎',
    ):
        assert glyph not in help_source


def test_worldbook_clipboard_loading_uses_svg_sprite():
    source = _read('static/js/components/wiEditor.js')
    request_block = source.split('_addWiClipboardRequest', 1)[1].split(
        'addWiEntryFromClipboard', 1
    )[0]

    assert 'icon-card-loader' in request_block
    assert 'icon-loader-circle' not in request_block
    assert 'ui-icon--spin' in request_block
    assert '⏳' not in request_block


def test_worldbook_icons_use_phase_one_scale_and_borderless_actions():
    css = _read('static/css/modules/view-wi.css')
    grid_source = _read('templates/components/grid_wi.html')
    popup_source = _read('templates/modals/detail_wi_popup.html')
    fullscreen_source = _read('templates/modals/detail_wi_fullscreen.html')
    detail_card_source = _read('templates/modals/detail_card.html')

    assert 'wi-worldbook-icon-scope wi-worldbook-grid' in grid_source
    assert 'wi-reader-modal wi-worldbook-icon-scope' in popup_source
    assert 'detail-wi-full-screen wi-worldbook-icon-scope' in fullscreen_source
    assert 'wi-container wi-worldbook-icon-scope' in detail_card_source
    assert 'wi-worldbook-tab-icon' in detail_card_source

    for size, value in (
        ('xs', '1.125rem'),
        ('sm', '1.3125rem'),
        ('md', '1.6875rem'),
        ('lg', '2.25rem'),
        ('xl', '4.5rem'),
    ):
        selector = f'.wi-worldbook-icon-scope .ui-icon--{size}'
        block = css.split(selector, 1)[1].split('}', 1)[0]
        assert f'width: {value}' in block
        assert f'height: {value}' in block

    assert '.wi-worldbook-grid .wi-grid-tool-btn' in css
    assert '.wi-worldbook-grid .card-local-note-btn' in css
    assert '.wi-worldbook-grid .card-send-st-btn' in css
    assert 'border-color: transparent !important' in css
    assert 'background: transparent !important' in css
    assert 'box-shadow: none !important' in css
    assert 'width: 1.725rem' in css
    assert 'width: 1.575rem' in css
    assert '.wi-worldbook-icon-scope .wi-worldbook-backup-icon.ui-icon--md' in css
    assert '.wi-reader-title-icon .ui-icon--lg' in css
    assert '.wi-reader-close-icon' in css
    assert '.wi-reader-date-meta .wi-reader-calendar-icon' in css
    assert 'margin-right: -0.25rem' in css
    assert '.wi-editor-container .wi-icon-only-action .ui-icon' in css
    assert '.wi-editor-container .wi-editor-top-actions .wi-editor-close-action' in css
    assert '.wi-editor-container .wi-vectorize-icon' in css
    vectorize_css = css.split('.wi-editor-container .wi-vectorize-icon', 1)[1].split(
        '}', 1
    )[0]
    assert 'transform: scale(1)' in vectorize_css
    assert 'wi-vectorize-icon' in fullscreen_source
    assert 'wi-help-shortcut-icon' in fullscreen_source
    help_source = fullscreen_source.split('<!-- 帮助指南模态框 -->', 1)[1]
    assert "icon('worldbook-vectorize', 'ui-icon--xs wi-vectorize-icon')" not in help_source
    shortcut_css = css.split('.wi-help-modal-content .wi-help-shortcut-icon', 1)[1].split(
        '}', 1
    )[0]
    assert 'transform: scale(1.5)' in shortcut_css
    assert 'wi-card-bookmark' in grid_source
    assert '.wi-worldbook-grid .wi-card-title-row::before' in css
    assert 'display: none;' in css.split(
        '.wi-worldbook-grid .wi-card-title-row::before', 1
    )[1].split('}', 1)[0]
    assert 'width: 3rem' in css
    assert fullscreen_source.count('wi-icon-only-action') == 2

    assert fullscreen_source.count('wi-action-btn wi-action-btn--bright') == 2
    assert fullscreen_source.count('wi-icon-only-action') == 2
    assert '.wi-editor-container .wi-action-btn--bright' in css
    assert '.wi-editor-container .wi-icon-only-action' in css
    assert '.wi-tab-btn {\n  flex: 1;\n  display: flex;' in css
    assert 'align-items: center;' in css.split('.wi-tab-btn {', 1)[1].split('}', 1)[0]
    assert 'justify-content: center;' in css.split('.wi-tab-btn {', 1)[1].split('}', 1)[0]
