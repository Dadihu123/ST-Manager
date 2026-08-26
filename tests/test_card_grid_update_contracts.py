import re
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


def test_bulk_flip_buttons_keep_white_text_in_both_themes_and_layouts():
    card_css = read_project_file('static/css/modules/view-cards.css')
    bulk_flip_button = card_css.split('.card-flip-all-btn {', 1)[1].split('}', 1)[0]
    card_template = read_project_file('templates/components/grid_cards.html')
    world_info_template = read_project_file('templates/components/grid_wi.html')

    assert 'color: var(--text-on-accent);' in bulk_flip_button
    assert 'var(--text-main)' not in bulk_flip_button
    assert 'card-flip-all-btn' in card_template
    assert 'card-flip-all-btn' in world_info_template


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
