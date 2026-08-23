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
