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
