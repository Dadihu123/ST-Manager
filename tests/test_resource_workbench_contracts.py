from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_resource_grid_workbenches_leave_wallpaper_visible():
    source = (PROJECT_ROOT / 'static/css/modules/resource-workbench.css').read_text(
        encoding='utf-8'
    )

    preset_block = source.split('.resource-grid-view--presets {', 1)[1].split('}', 1)[0]
    extension_block = source.split(
        '.extension-workbench.resource-grid-view {', 1
    )[1].split('}', 1)[0]
    extension_content_block = source.split(
        '.extension-workbench.resource-grid-view .extension-workbench-content {', 1
    )[1].split('}', 1)[0]

    assert 'background: transparent;' in preset_block
    assert 'background: transparent;' in extension_block
    assert 'background: transparent;' in extension_content_block


def test_chat_grid_toolbar_keeps_own_readable_panel_and_shared_actions():
    css = (PROJECT_ROOT / 'static/css/modules/resource-workbench.css').read_text(
        encoding='utf-8'
    )
    template = (PROJECT_ROOT / 'templates/components/grid_chats.html').read_text(
        encoding='utf-8'
    )

    toolbar_block = next(
        block.split('}', 1)[0]
        for block in css.split('.chat-mode-shell.resource-grid-view .chat-grid-toolbar {')[1:]
        if 'background: var(--resource-workbench-header);' in block.split('}', 1)[0]
    )

    assert 'background: var(--resource-workbench-header);' in toolbar_block
    assert 'border: 1px solid var(--resource-workbench-border);' in toolbar_block
    assert 'border-radius: var(--resource-workbench-radius);' in toolbar_block
    assert template.count('resource-grid-action') >= 2
    assert 'resource-grid-action resource-grid-action--primary chat-toolbar-btn' in template


def test_detail_management_actions_use_semantic_status_colors():
    css = (PROJECT_ROOT / 'static/css/modules/detail-card-workbench.css').read_text(
        encoding='utf-8'
    )
    template = (PROJECT_ROOT / 'templates/modals/detail_card.html').read_text(
        encoding='utf-8'
    )

    assert 'detail-manage-action-btn--url' in template
    assert 'detail-manage-action-btn--warn' in template
    assert 'detail-manage-action-btn--danger' in template
    assert 'background-color: var(--status-warning-surface) !important;' in css
    assert 'background-color: var(--status-danger-surface) !important;' in css
    assert 'background-color: var(--status-success-surface) !important;' in css
    assert 'background-color: var(--status-info-surface) !important;' in css
