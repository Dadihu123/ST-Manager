from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WORLD_BOOK_SYMBOLS = (
    'book-save',
    'book-backup',
    'entry-rollback',
    'arrow-left',
    'history-rollback',
    'clipboard',
    'snapshot',
    'book-save-as',
    'sort',
    'calendar',
    'book-search',
    'pin',
    'wand',
    'layout',
    'book-tip',
    'key-trigger',
    'list',
    'keyboard',
    'book-closed',
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


def _button_block(source, marker):
    start = source.index(marker)
    end = source.index('</button>', start)
    return source[start:end]


def test_worldbook_design_symbols_are_theme_safe():
    source = _read('static/icons/ui.svg')
    design_block = source.split('<!-- 世界书套件专用图标', 1)[1]

    assert 'background' not in design_block
    assert '#000000' not in design_block

    for name in WORLD_BOOK_SYMBOLS:
        assert f'id="icon-{name}"' in design_block

    for name, view_box in (
        ('pin', '21 34 525 636'),
        ('wand', '41 53 567 600'),
        ('layout', '78 109 487 492'),
        ('book-tip', '117 62 409 604'),
        ('key-trigger', '53 186 577 578'),
        ('list', '86 127.216 487.425 312.31'),
        ('keyboard', '80 129 519 355'),
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

    assert '{% from "components/icon.html" import icon, loading_icon %}' in _read(
        'templates/components/grid_wi.html'
    )
    for relative_path in template_paths[1:]:
        assert '{% from "components/icon.html" import icon, loading_icon, sidebar_icon %}' in _read(
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

    assert "icon('book-save'" in fullscreen_controls
    assert "icon('entry-rollback'" in fullscreen_controls
    assert "icon('wand'" in fullscreen_controls
    assert "icon('calendar'" in popup_source
    assert "icon('book-search'" in popup_source
    assert "icon('snapshot'" in popup_source

    assert "icon('upload'" in grid_source
    assert "icon('check'" in grid_source
    assert "icon('folder'" in grid_source
    assert "icon('sticky-note'" in grid_source
    assert "icon('send'" in grid_source
    assert "loading_icon('" in grid_source
    assert "icon('pencil-edit'" in popup_source
    assert "icon('close'" in popup_source
    assert "icon('send'" in popup_source
    assert "loading_icon('" in popup_source
    assert "icon('file-import'" in fullscreen_controls
    assert "icon('book-search'" in fullscreen_controls
    assert "icon('pin'" in fullscreen_controls
    assert "icon('search'" not in fullscreen_controls
    assert "icon('circle-dot'" not in fullscreen_controls
    assert "icon('settings-save'" in fullscreen_controls
    assert "icon('settings-help-entry'" in fullscreen_controls
    assert "icon('plus-square'" in fullscreen_controls
    assert "icon('trash'" in fullscreen_controls
    assert "icon('alert-triangle'" in fullscreen_controls
    assert "icon('sliders-settings'" in fullscreen_controls
    assert "icon('eye'" in fullscreen_controls
    assert "icon('file-import'" in detail_card_worldbook
    assert "icon('upload'" in detail_card_worldbook
    assert "icon('file-import'" in grid_source
    assert "icon('book-closed'" in grid_source
    assert "icon('book-save-as'" not in grid_source
    assert "icon('pencil-edit'" in fullscreen_controls
    assert "icon('plus-square'" in detail_card_worldbook
    assert "icon('trash'" in detail_card_worldbook


def test_worldbook_export_controls_use_the_outbound_icon_direction():
    grid_source = _read('templates/components/grid_wi.html')
    popup_source = _read('templates/modals/detail_wi_popup.html')
    detail_card_source = _read('templates/modals/detail_card.html')

    for source, marker in (
        (grid_source, '@click.stop="exportWorldInfoItem(item)"'),
        (popup_source, '@click="exportActiveWorldInfo()"'),
        (detail_card_source, '@click="exportWorldBookSingle()"'),
    ):
        button = _button_block(source, marker)
        assert "icon('upload'" in button
        assert "icon('book-save-as'" not in button
        assert "icon('file-import'" not in button


def test_worldbook_help_reuses_shared_icons_without_functional_glyphs():
    source = _read('templates/modals/detail_wi_fullscreen.html')
    help_source = source.split('<!-- 帮助指南模态框 -->', 1)[1]

    for name in (
        'settings-save',
        'book-save',
        'book-save-as',
        'history-rollback',
        'entry-rollback',
        'book-backup',
        'clipboard',
        'plus-square',
        'alert-triangle',
        'sliders-settings',
        'pin',
        'wand',
        'layout',
        'book-tip',
        'key-trigger',
        'list',
        'keyboard',
        'book-search',
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


def test_worldbook_clipboard_loading_uses_the_animated_asset():
    source = _read('static/js/components/wiEditor.js')
    request_block = source.split('_addWiClipboardRequest', 1)[1].split(
        'addWiEntryFromClipboard', 1
    )[0]

    assert 'loading-animation.svg' in request_block
    assert '<img' in request_block
    assert request_block.count('<use') == 0
    assert 'ui-icon--spin' not in request_block
    assert '⏳' not in request_block


def test_worldbook_icons_use_integer_size_tiers_and_borderless_actions():
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

    icons_css = _read('static/css/modules/icons.css')
    for size, value in (
        ('xs', '12px'),
        ('sm', '16px'),
        ('md', '20px'),
        ('lg', '24px'),
        ('xl', '32px'),
    ):
        selector = f'.ui-icon--{size} {{'
        block = icons_css.split(selector, 1)[1].split('}', 1)[0]
        assert f'width: {value};' in block
        assert f'height: {value};' in block

    assert '.wi-worldbook-grid .wi-grid-tool-btn' in css
    assert '.wi-worldbook-grid .card-local-note-btn' in css
    assert '.wi-worldbook-grid .card-send-st-btn' in css
    assert 'border-color: transparent !important' in css
    assert 'background: transparent !important' in css
    assert 'box-shadow: none !important' in css
    assert 'width: 1.725rem' not in css
    assert 'width: 1.575rem' not in css
    assert '.wi-worldbook-icon-scope .wi-worldbook-backup-icon.ui-icon--md' not in css
    assert '.wi-reader-title-icon .ui-icon--lg' not in css
    assert "icon('close', 'ui-icon--md')" in popup_source
    assert '.wi-reader-date-meta .wi-reader-calendar-icon' in css
    assert 'margin-right: -0.25rem' in css
    assert '.wi-editor-container .wi-icon-only-action .ui-icon' in css
    assert '.wi-editor-container .wi-editor-top-actions .wi-editor-close-action' in css
    assert '.wi-editor-container .wi-vectorize-icon' not in css
    assert 'wi-vectorize-icon' not in fullscreen_source
    assert 'wi-help-shortcut-icon' in fullscreen_source
    help_source = fullscreen_source.split('<!-- 帮助指南模态框 -->', 1)[1]
    assert "icon('wand', 'ui-icon--xs')" in help_source
    shortcut_css = css.split('.wi-help-modal-content .wi-help-shortcut-icon', 1)[1].split(
        '}', 1
    )[0]
    assert 'width: 24px;' in shortcut_css
    assert 'height: 24px;' in shortcut_css
    assert 'wi-card-bookmark' in grid_source
    assert '.wi-worldbook-grid .wi-card-title-row::before' in css
    assert 'display: none;' in css.split(
        '.wi-worldbook-grid .wi-card-title-row::before', 1
    )[1].split('}', 1)[0]
    assert '.wi-worldbook-grid .wi-card-bookmark .wi-card-bookmark-icon' in css
    assert 'width: 32px;' in css
    assert fullscreen_source.count('wi-icon-only-action') == 2

    assert fullscreen_source.count('wi-action-btn wi-action-btn--bright') == 2
    assert fullscreen_source.count('wi-icon-only-action') == 2
    assert '.wi-editor-container .wi-action-btn--bright' in css
    assert '.wi-editor-container .wi-icon-only-action' in css
    assert '.wi-tab-btn {\n  flex: 1;\n  display: flex;' in css
    assert 'align-items: center;' in css.split('.wi-tab-btn {', 1)[1].split('}', 1)[0]
    assert 'justify-content: center;' in css.split('.wi-tab-btn {', 1)[1].split('}', 1)[0]
