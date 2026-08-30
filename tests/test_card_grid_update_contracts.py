import re
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_card_updated_preserves_existing_import_time_before_resort():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')

    assert 'const existingCard = idx !== -1 ? this.cards[idx] : null;' in card_grid_source
    assert 'const cardForSort = existingCard' in card_grid_source
    assert re.search(
        r'if\s*\(\s*existingCard\s*&&\s*!Number\(\s*cardForSort\.import_time\s*\|\|\s*0\s*\)\s*\)',
        card_grid_source,
    )
    assert 'cardForSort.import_time = existingCard.import_time;' in card_grid_source
    assert 'this.insertCardSorted(cardForSort);' in card_grid_source


def test_card_grid_fetch_rewinds_overflow_page_before_applying_empty_page():
    card_grid_source = read_project_file('static/js/components/cardGrid.js')

    overflow_guard = re.search(
        r'const nextTotalItems = data\.total_count \|\| 0;'
        r'[\s\S]*?const nextTotalPages = Math\.ceil\(nextTotalItems / pageSize\) \|\| 1;'
        r'[\s\S]*?if \(page > nextTotalPages\) \{'
        r'[\s\S]*?this\.currentPage = nextTotalPages;'
        r'[\s\S]*?new CustomEvent\("card-page-changed", \{ detail: \{ page: nextTotalPages \} \}\)'
        r'[\s\S]*?if \(nextTotalItems > 0\) \{'
        r'[\s\S]*?this\.fetchCards\(\);'
        r'[\s\S]*?return;',
        card_grid_source,
    )

    assert overflow_guard
    assert card_grid_source.index('if (page > nextTotalPages) {') < card_grid_source.index(
        'this.cards = data.cards || [];'
    )


def test_card_grid_places_send_to_st_before_source_update_check():
    card_grid_template = read_project_file('templates/components/grid_cards.html')
    toolbar = card_grid_template.split('<div class="card-bottom-toolbar"', 1)[1].split(
        'class="card-flip-corner"', 1
    )[0]

    assert toolbar.index('class="card-send-st-btn"') < toolbar.index(
        'class="card-source-update-btn"'
    )


def test_card_controls_are_sibling_layer_above_cards_css_effect():
    card_grid_template = read_project_file('templates/components/grid_cards.html')
    card_css = read_project_file('static/css/modules/view-cards.css')

    content = card_grid_template.split(
        'class="holo-card__content"', 1
    )[1].split('class="card-effect-controls-layer"', 1)[0]
    image_container = card_grid_template.split(
        'class="card-image-container"', 1
    )[1].split('class="card-image-overlay"', 1)[0]
    controls_layer = card_grid_template.split(
        'class="card-effect-controls-layer"', 1
    )[1].split('class="holo-card__shine"', 1)[0]
    controls_css = card_css.split(
        '.card-effect-shell .card-effect-controls-layer {', 1
    )[1].split('}', 1)[0]

    assert 'card-select-indicator' not in image_container
    assert 'card-fav-btn' not in image_container
    assert 'card-select-indicator' in controls_layer
    assert 'card-fav-btn' in controls_layer
    assert 'card-effect-controls-topbar-spacer' in controls_layer
    assert 'card-effect-controls-image-layer' in controls_layer
    assert 'card-bottom-toolbar' in controls_layer
    assert 'card-flip-corner' in controls_layer
    assert controls_layer.index('card-effect-controls-topbar-spacer') < controls_layer.index(
        'card-effect-controls-image-layer'
    ) < controls_layer.index('card-bottom-toolbar')
    assert 'class="card-image-char-name" x-text="card.char_name"' in content
    assert 'card-toolbar-layout-spacer' in content
    assert 'z-index: 5;' in controls_css
    assert 'pointer-events: none;' in controls_css
    assert '@click.stop="handleCardClick($event, card)"' in card_grid_template

    assert '.card-image-container::after' not in card_css
    assert 'border-top-color: transparent !important;' in card_css
    assert 'background: transparent !important;' in card_css
    assert '.card-local-note-btn.no-note' in card_css
    spacer_css = card_css.split(
        '.card-effect-shell .card-toolbar-layout-spacer {', 1
    )[1].split('}', 1)[0]
    assert 'visibility: visible;' in spacer_css
    assert 'backdrop-filter: blur(12px) saturate(130%);' in spacer_css
    assert 'rgba(var(--surface-container-rgb), 0.5)' in spacer_css
    assert 'rgba(var(--surface-container-rgb), 0.62)' in spacer_css
    bottom_surface_reset = card_css.rsplit(
        '.card-effect-shell .card-effect-controls-layer\n  > .card-bottom-toolbar {',
        1,
    )[1].split('}', 1)[0]
    assert 'box-shadow: none !important;' in bottom_surface_reset
    assert 'backdrop-filter: none !important;' in bottom_surface_reset
    light_surface_rule = card_css.split(
        'html.light-mode .card-front-topbar,\nhtml.light-mode .card-bottom-toolbar {',
        1,
    )[1].split('}', 1)[0]
    assert 'background: color-mix(in srgb, var(--content-on-dark) 42%, transparent) !important;' in light_surface_rule
    assert 'backdrop-filter: blur(12px) saturate(130%) !important;' in light_surface_rule


def test_bulk_flip_buttons_use_the_soft_action_treatment_in_both_themes_and_layouts():
    card_css = read_project_file('static/css/modules/view-cards.css')
    bulk_flip_button = card_css.split('.card-flip-all-btn {', 1)[1].split('}', 1)[0]
    card_template = read_project_file('templates/components/grid_cards.html')
    world_info_template = read_project_file('templates/components/grid_wi.html')

    assert 'color: var(--content-on-accent);' not in bulk_flip_button
    assert 'var(--text-main)' not in bulk_flip_button
    assert 'btn-action-soft card-flip-all-btn' in card_template
    assert 'btn-action-soft card-flip-all-btn' in world_info_template


def test_light_mode_card_toolbar_actions_keep_icon_only_surfaces():
    card_css = read_project_file('static/css/modules/view-cards.css')
    light_toolbar_actions = card_css.split(
        'html.light-mode .card-bottom-toolbar\n  > .card-local-note-btn,', 1
    )[1].split('}', 1)[0]

    assert '> .card-forum-search-btn,' in light_toolbar_actions
    assert '> .card-send-st-btn,' in light_toolbar_actions
    assert '> .card-source-update-btn {' in light_toolbar_actions
    assert 'border-color: transparent;' in light_toolbar_actions
    assert 'background: transparent;' in light_toolbar_actions
    assert 'box-shadow: none;' in light_toolbar_actions


def test_card_bundle_icon_uses_the_base_integer_size_tier():
    card_template = read_project_file('templates/components/grid_cards.html')
    card_css = read_project_file('static/css/modules/view-cards.css')

    assert "icon('package', 'ui-icon--xs ')" in card_template
    assert '.card-meta-bundle ..ui-icon--xs' not in card_css
    assert '.ui-icon--xs {' in read_project_file('static/css/modules/icons.css')
    assert 'width: 12px;' in read_project_file('static/css/modules/icons.css')
    assert 'height: 12px;' in read_project_file('static/css/modules/icons.css')


def test_card_favorite_uses_solid_theme_aware_svg_with_existing_state_colors():
    card_template = read_project_file('templates/components/grid_cards.html')
    card_css = read_project_file('static/css/modules/view-cards.css')
    ui_root = ET.parse(PROJECT_ROOT / 'static/icons/ui.svg').getroot()
    favorite_symbol = next(
        element
        for element in ui_root
        if element.get('id') == 'icon-heart'
    )
    paths = [
        element
        for element in favorite_symbol
        if element.tag.rsplit('}', 1)[-1] == 'path'
    ]
    favorite_button = card_template.split(
        'class="card-fav-btn card-fav-overlay"', 1
    )[1].split('</button>', 1)[0]

    assert "icon('heart', 'card-fav-icon')" in favorite_button
    assert '♥' not in favorite_button
    assert favorite_symbol.get('viewBox') == '98.422 75.852 629.893 552.273'
    assert len(paths) == 1
    assert paths[0].get('fill') == 'currentColor'
    assert paths[0].get('stroke') == 'none'
    assert 'style' not in paths[0].attrib
    assert '.card-fav-overlay .card-fav-icon {' in card_css
    assert 'fill: currentColor;' in card_css
    assert 'stroke: none;' in card_css
    assert 'color: color-mix(in srgb, var(--content-primary) 90%, transparent);' in card_css
    assert 'color: var(--decoration-rose);' in card_css
    assert 'color: var(--status-danger-text);' in card_css
    assert 'drop-shadow(0 1px 3px color-mix(in srgb, var(--surface-page) 32%, transparent))' in card_css
