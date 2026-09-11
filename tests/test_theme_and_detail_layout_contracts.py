from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_mobile_sidebar_close_is_centered_and_borderless():
    source = (PROJECT_ROOT / 'static/css/modules/layout.css').read_text(encoding='utf-8')

    header_block = source.split('.sidebar-mobile .sidebar-mobile-nav-head {', 1)[1].split('}', 1)[0]
    close_block = source.split('.sidebar-mobile .sidebar-close-btn {', 1)[1].split('}', 1)[0]

    assert 'align-items: center;' in header_block
    assert 'align-self: center;' in close_block
    assert 'border: 0;' in close_block
    assert 'border-color: var(--sidebar-divider);' not in close_block


def test_detail_management_update_grid_stacks_at_1920px():
    source = (PROJECT_ROOT / 'static/css/modules/modal-detail.css').read_text(encoding='utf-8')

    breakpoint_block = source.split('@media (max-width: 1920px) {', 1)[1].split('}', 2)

    assert 'grid-template-columns: minmax(0, 1fr);' in breakpoint_block[0]
    assert '.detail-manage-panel--update' in breakpoint_block[1]


def test_desktop_theme_toggle_uses_circular_view_transition():
    header = (PROJECT_ROOT / 'templates/components/header.html').read_text(encoding='utf-8')
    state = (PROJECT_ROOT / 'static/js/state.js').read_text(encoding='utf-8')
    color_system = (PROJECT_ROOT / 'static/css/color-system.css').read_text(encoding='utf-8')
    layout = (PROJECT_ROOT / 'static/css/modules/layout.css').read_text(encoding='utf-8')

    assert '@click="toggleDarkMode($event)"' in header
    assert 'header-theme-icon--dark' in header
    assert 'header-theme-icon--light' in header
    assert 'header-theme-icon--dark .ui-icon' in state
    assert 'header-theme-icon--light .ui-icon' in state
    assert 'const rect = activeIcon?.getBoundingClientRect?.();' in state
    assert 'document.startViewTransition' in state
    assert 'pseudoElement: "::view-transition-new(root)"' in state
    assert 'this.deviceType === "desktop"' in state
    assert '::view-transition-new(root)' in color_system
    assert '.header-theme-toggle.is-light .header-theme-icon--light' in layout
