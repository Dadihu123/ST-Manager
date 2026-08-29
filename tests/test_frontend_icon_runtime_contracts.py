from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_layout_uses_compiled_tailwind_and_guards_empty_toast_icon_href():
    source = read_project_file('templates/layout.html')

    assert '/static/css/tailwind.css' in source
    assert '/static/lib/tailwindcss.js' not in source
    assert '<template x-if="toastIcon">' in source
    assert "<use :href=\"'{{ url_for('static', filename='icons/') }}' + toastIconHref\"></use>" in source


def test_card_detail_help_modal_is_teleported_above_detail_modal_stack():
    source = read_project_file('templates/modals/detail_card.html')
    help_start = source.index('<!-- 字段说明帮助模态框 (Help Modal) -->')
    help_source = source[help_start:]

    assert '<template x-teleport="body">' in help_source
    assert "icon('settings-help-entry'" in help_source
    assert 'z-modal-popover' in help_source
    assert 'z-[60]' not in help_source


def test_worldbook_backup_folder_actions_use_the_shared_medium_icon_tier():
    popup_source = read_project_file('templates/modals/detail_wi_popup.html')
    fullscreen_source = read_project_file('templates/modals/detail_wi_fullscreen.html')
    detail_card_source = read_project_file('templates/modals/detail_card.html')

    assert "icon('book-backup', 'ui-icon--md')" in popup_source
    assert "icon('book-backup', 'ui-icon--md')" in fullscreen_source
    assert "icon('book-backup', 'ui-icon--xl')" not in popup_source
    assert "icon('book-backup', 'ui-icon--xl')" not in fullscreen_source
    assert "icon('book-backup', 'ui-icon--lg')" in detail_card_source


def test_personalized_save_icon_is_restored_for_all_production_save_calls():
    sprite = read_project_file('static/icons/ui.svg')

    assert '<symbol id="icon-settings-save" viewBox="46 48 353 350">' in sprite
    assert 'transform="translate(234,76)" fill="currentColor" stroke="none"' in sprite
    assert 'transform="translate(68,48)" fill="currentColor" stroke="none"' in sprite
    assert '<symbol id="icon-save"' not in sprite

    save_sources = (
        'templates/modals/settings.html',
        'templates/modals/automation.html',
        'templates/modals/detail_wi_fullscreen.html',
        'static/js/state.js',
        'static/js/components/advancedEditor.js',
        'static/js/components/automationModal.js',
        'static/js/components/detailModal.js',
        'static/js/components/wiDetailPopup.js',
        'static/js/components/wiEditor.js',
    )
    for relative_path in save_sources:
        source = read_project_file(relative_path)
        assert "icon('save'" not in source
        assert '"save"' not in source
        assert "'save'" not in source
