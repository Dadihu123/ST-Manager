from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_marquee_selection_utility_has_mouse_only_drag_lifecycle():
    source = read_project_file('static/js/utils/marqueeSelection.js')

    assert 'export function createMarqueeSelection' in source
    assert 'event.pointerType === "mouse"' in source
    assert 'Math.hypot(deltaX, deltaY) < threshold' in source
    assert 'session.root.setPointerCapture?.(session.pointerId)' in source
    assert 'window.addEventListener("keydown", this._marqueeKeydownHandler)' in source
    assert 'event.key === "Escape"' in source
    assert 'event.stopImmediatePropagation?.()' in source


def test_supported_multi_select_grids_bind_marquee_selection():
    expected_bindings = {
        'templates/components/grid_cards.html': 'id="main-scroll"',
        'templates/components/grid_wi.html': 'id="wi-scroll-area"',
        'templates/components/grid_presets.html': 'id="preset-scroll-area"',
    }

    for relative_path, root_marker in expected_bindings.items():
        source = read_project_file(relative_path)
        assert root_marker in source
        assert '@pointerdown="beginMarqueeSelection($event)"' in source
        assert '@pointermove="updateMarqueeSelection($event)"' in source
        assert '@pointerup="endMarqueeSelection($event)"' in source
        assert '@click.capture="handleMarqueeClick($event)"' in source
        assert 'class="marquee-selection-box"' in source


def test_marquee_selection_is_limited_to_modes_with_batch_selection():
    supported_sources = [
        read_project_file('static/js/components/cardGrid.js'),
        read_project_file('static/js/components/wiGrid.js'),
        read_project_file('static/js/components/presetGrid.js'),
    ]
    unsupported_sources = [
        read_project_file('templates/components/grid_chats.html'),
        read_project_file('templates/components/grid_extensions.html'),
        read_project_file('templates/components/grid_beautify.html'),
    ]

    for source in supported_sources:
        assert 'createMarqueeSelection' in source
        assert 'initMarqueeSelection();' in source

    for source in unsupported_sources:
        assert 'beginMarqueeSelection' not in source


def test_mode_switch_cancels_active_marquee_without_restoring_old_selection():
    source = read_project_file('static/js/components/layout.js')

    assert 'this.$store.global.viewState.lastSelectedId = null;' in source
    assert 'new CustomEvent("cancel-marquee-selection"' in source
    assert 'restoreSelection: false' in source


def test_marquee_selection_keeps_existing_native_drag_entry_points():
    for relative_path, handler in [
        ('static/js/components/cardGrid.js', 'dragStart(e, card)'),
        ('static/js/components/wiGrid.js', 'dragStart(e, item)'),
        ('static/js/components/presetGrid.js', 'dragStart(e, item)'),
    ]:
        source = read_project_file(relative_path)
        assert handler in source
