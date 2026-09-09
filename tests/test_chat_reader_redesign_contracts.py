from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_chat_reader_redesign_exposes_mobile_navigation_and_accessible_shortcuts():
    template = read_project_file('templates/modals/detail_chat_reader.html')
    stylesheet = read_project_file('static/css/modules/view-chats/reader-workbench.css')

    assert '@keydown.window="handleReaderKeydown($event)"' in template
    assert 'class="chat-reader-mobile-dock"' in template
    assert 'data-reader-search-input' in template
    assert 'id="chat-reader-content"' in template
    assert '.chat-reader-mobile-dock' in stylesheet
    assert ':focus-visible' in stylesheet


def test_chat_reader_delete_flow_uses_custom_confirmation_without_changing_api_call():
    template = read_project_file('templates/modals/detail_chat_reader.html')
    chat_grid = read_project_file('static/js/components/chatGrid.js')

    assert '@click="requestDeleteChat(activeChat)"' in template
    assert 'class="chat-reader-delete-confirm' in template
    assert 'readerDeleteConfirmOpen: false' in chat_grid
    assert 'requestDeleteChat(item)' in chat_grid
    assert 'await this.deleteChat(target, { skipConfirm: true });' in chat_grid
    assert 'const res = await deleteChat(item.id);' in chat_grid


def test_chat_reader_keyboard_navigation_keeps_editable_controls_out_of_scope():
    chat_grid = read_project_file('static/js/components/chatGrid.js')

    keyboard_handler = chat_grid.split('handleReaderKeydown(event) {', 1)[1].split(
        'stepReaderKeyboardFloor(delta) {',
        1,
    )[0]

    assert 'event.key === "/"' in keyboard_handler
    assert 'ArrowDown: 1' in keyboard_handler
    assert 'ArrowUp: -1' in keyboard_handler
    assert 'tagName === "input"' in keyboard_handler
    assert 'tagName === "textarea"' in keyboard_handler
    assert 'tagName === "select"' in keyboard_handler
