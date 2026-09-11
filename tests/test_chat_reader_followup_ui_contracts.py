from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_chat_reader_followup_template_consolidates_reader_controls_and_assets():
    template = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'class="chat-reader-header-tools" x-show="readerResponsiveMode !== \'mobile\'"' in template
    assert 'class="chat-reader-reading-mode-group"' in template
    assert 'chat-reader-controlbar' not in template
    assert template.count('src="{{ reader_render_icon_src }}"') == 4
    assert template.count("detail_icon('note', 'ui-icon--sm')") == 2
    assert "sidebar_icon('character-cards', 'ui-icon--sm')" in template
    assert 'card-fav-btn card-fav-overlay' in template
    assert 'class="chat-message-author"' in template
    assert template.count("icon('settings-help-entry', 'ui-icon--sm')") >= 3


def test_chat_reader_followup_template_marks_close_buttons_and_tabs_accessibly():
    template = read_project_file('templates/modals/detail_chat_reader.html')

    assert template.count('chat-reader-modal-close-button') == 9
    assert 'class="chat-reader-icon-button chat-reader-rail-close"' in template
    assert 'role="tablist" aria-label="检索与目录视图"' in template
    assert ':aria-selected="readerRightTab === \'search\' ? \'true\' : \'false\'"' in template
    assert ':aria-selected="readerRightTab === \'floors\' ? \'true\' : \'false\'"' in template


def test_chat_reader_followup_css_matches_detail_tabs_and_mobile_header_dock():
    stylesheet = read_project_file('static/css/modules/view-chats/reader-workbench.css')

    assert '.chat-reader-right .chat-reader-rail-tab.is-active {' in stylesheet
    assert 'border: 1px solid transparent;' in stylesheet
    assert 'border-color: var(--action-border);' in stylesheet
    assert 'background: var(--action-surface);' in stylesheet
    assert '.chat-reader-modal-close-button {' in stylesheet
    assert 'border: 0 !important;' in stylesheet
    assert 'top: var(--chat-reader-header-height);' in stylesheet
    assert 'bottom: auto;' in stylesheet
    assert 'top: calc(var(--chat-reader-header-height) + var(--chat-reader-mobile-dock-height));' in stylesheet
    assert 'overflow-wrap: anywhere;' in stylesheet


def test_chat_reader_render_asset_is_an_exact_copy_of_requested_source():
    source = (PROJECT_ROOT / 'tmp/其他/render.svg').read_bytes()
    copied = (PROJECT_ROOT / 'static/icons/chat-reader-render.svg').read_bytes()

    assert copied == source
