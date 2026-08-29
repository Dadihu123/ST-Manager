import json
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.data import ui_store as ui_store_module
from core.data.ui_store import get_tag_taxonomy
from core.services.card_index_query_service import query_indexed_cards


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def _write_ui_data(ui_path: Path, payload):
    ui_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _ts(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def _make_card(
    card_id,
    *,
    char_name,
    category='',
    import_time=0.0,
    last_modified=0.0,
    token_count=0,
    tags=None,
    ui_summary='',
    creator='',
    is_favorite=False,
):
    return {
        'id': card_id,
        'category': category,
        'char_name': char_name,
        'filename': card_id,
        'tags': list(tags or []),
        'ui_summary': ui_summary,
        'creator': creator,
        'is_favorite': is_favorite,
        'last_modified': last_modified,
        'import_time': import_time,
        'token_count': token_count,
    }


class _FakeCache:
    def __init__(self, cards):
        self.cards = list(cards)
        self.visible_folders = sorted({c.get('category', '') for c in cards if c.get('category', '')})
        self.category_counts = {}
        self.global_tags = set()
        self.lock = threading.Lock()
        self.initialized = True

    def reload_from_db(self):
        raise AssertionError('reload_from_db should not run in indexed fallback tests')


def _install_fake_cache(monkeypatch, cards):
    fake_cache = _FakeCache(cards)
    monkeypatch.setattr(cards_api.ctx, 'cache', fake_cache)
    return fake_cache


def _seed_index(db_path):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::cards/alpha.png', 'card', 'cards/alpha.png', 'Alpha', 'alpha.png', 'SciFi', 'SciFi', 'physical', 1, 'pilot note', 200.0, 150.0, 3200, 'alpha', 200.0, '', '200:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::cards/beta.png', 'card', 'cards/beta.png', 'Beta', 'beta.png', 'Fantasy', 'Fantasy', 'physical', 0, 'forest note', 100.0, 90.0, 1200, 'beta', 100.0, '', '100:1'),
        )
        conn.execute("INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)", (1, 'card::cards/alpha.png', 'blue'))
        conn.execute("INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)", (1, 'card::cards/alpha.png', 'hero'))
        conn.execute("INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)", (1, 'card::cards/beta.png', 'green'))
        conn.execute("INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)", (1, 'card::cards/alpha.png', 'Alpha alpha.png SciFi blue hero pilot note'))
        conn.execute("INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)", (1, 'card::cards/beta.png', 'Beta beta.png Fantasy green forest note'))
        conn.commit()


def _seed_index_v2_cards(db_path, *, active_generation=1):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = ?, state = 'ready', phase = 'ready' WHERE scope = 'cards'",
            (active_generation,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (active_generation, 'card::cards/alpha.png', 'card', 'cards/alpha.png', 'Alpha', 'alpha.png', 'SciFi', 'SciFi', 'physical', 1, 'pilot note', 200.0, 150.0, 3200, 'alpha', 200.0, '', '200:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (active_generation + 1, 'card::cards/beta.png', 'card', 'cards/beta.png', 'Beta', 'beta.png', 'Fantasy', 'Fantasy', 'physical', 0, 'forest note', 100.0, 90.0, 1200, 'beta', 100.0, '', '100:1'),
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (active_generation, 'card::cards/alpha.png', 'blue'),
        )
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (active_generation + 1, 'card::cards/beta.png', 'green'),
        )
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (active_generation, 'card::cards/alpha.png', 'Alpha alpha.png SciFi blue pilot note'),
        )
        conn.execute(
            'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
            (active_generation + 1, 'card::cards/beta.png', 'Beta beta.png Fantasy green forest note'),
        )
        conn.commit()


def _seed_fulltext_index(db_path):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::cards/fulltext.png', 'card', 'cards/fulltext.png', 'Fulltext Hero', 'fulltext.png', 'SciFi', 'SciFi', 'physical', 0, 'rare pilot entry', 210.0, 160.0, 2200, 'fulltext hero', 210.0, '', '210:1'),
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)",
            (1, 'card::cards/fulltext.png', 'phrase hero "quoted term" rare pilot entry'),
        )
        conn.commit()


def _seed_root_index(db_path):
    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::cards/root.png', 'card', 'cards/root.png', 'Root', 'root.png', '', '', 'physical', 0, 'root note', 300.0, 250.0, 800, 'root', 300.0, '', '300:1'),
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)",
            (1, 'card::cards/root.png', 'Root root.png root note'),
        )
        conn.commit()


def _configure_indexed_list(monkeypatch, tmp_path, cards):
    db_path = tmp_path / 'cards_metadata.db'
    ui_path = tmp_path / 'ui_data.json'
    _write_ui_data(ui_path, {})
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(
        cards_api,
        'load_config',
        lambda: {'cards_list_use_index': True, 'fast_search_use_index': True, 'default_sort': 'date_desc'},
    )
    _install_fake_cache(monkeypatch, cards)
    return db_path


def test_indexed_list_cards_filters_category_tags_and_favorites(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=SciFi&tags=blue&fav_filter=included')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_uses_fast_search_mode(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=pilot&search_mode=fast')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_search_falls_back_when_fast_search_index_disabled(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/alpha.png', char_name='Alpha', ui_summary='legacy pilot note', last_modified=10.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'load_config',
        lambda: {'cards_list_use_index': True, 'fast_search_use_index': False, 'default_sort': 'date_desc'},
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed search should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=pilot')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_fast_search_preserves_substring_matching(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=alp&search_mode=fast')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_full_search_ignores_tag_and_favorite_filters(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get(
        '/api/list_cards?page=1&page_size=20'
        '&search_scope=full'
        '&search=beta'
        '&fav_filter=included'
        '&tags=blue'
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/beta.png']


def test_indexed_list_cards_filters_token_range(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&token_min=2000&token_max=4000')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_full_search_with_category_falls_back_to_legacy_behavior(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/alpha.png', char_name='Alpha', category='SciFi', last_modified=10.0),
            _make_card('cards/beta.png', char_name='Beta', category='Fantasy', last_modified=20.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed path should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get(
        '/api/list_cards?page=1&page_size=20'
        '&search_scope=full'
        '&category=SciFi'
        '&search=beta'
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/beta.png']


def test_indexed_list_cards_only_with_filters_uses_current_category_without_filters(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get(
        '/api/list_cards?page=1&page_size=20'
        '&category=SciFi'
        '&search_scope=all_dirs'
        '&all_dirs_only_with_filters=true'
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_recursive_false_preserves_exact_folder_behavior(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/base/direct.png', char_name='Direct', category='base', last_modified=30.0),
            _make_card('cards/base/sub/nested.png', char_name='Nested', category='base/sub', last_modified=20.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed path should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=base&recursive=false')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/base/direct.png']


def test_indexed_list_cards_import_date_filter_falls_back_to_legacy_behavior(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card(
                'cards/old.png',
                char_name='Old',
                import_time=_ts(2026, 3, 1, 12),
                last_modified=_ts(2026, 3, 1, 12),
            ),
            _make_card(
                'cards/match.png',
                char_name='Match',
                import_time=_ts(2026, 3, 15, 9),
                last_modified=_ts(2026, 3, 15, 9),
            ),
            _make_card(
                'cards/late.png',
                char_name='Late',
                import_time=_ts(2026, 4, 2, 18),
                last_modified=_ts(2026, 4, 2, 18),
            ),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed path should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&import_date_from=2026-03-10&import_date_to=2026-03-31')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/match.png']


def test_indexed_list_cards_search_type_specific_search_falls_back_to_legacy_behavior(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/name-match.png', char_name='Different', tags=['alpha'], last_modified=10.0),
            _make_card('cards/tag-match.png', char_name='Unrelated', tags=['special-tag'], last_modified=20.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed path should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=special&search_type=tags')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/tag-match.png']


def test_indexed_list_cards_non_default_sort_falls_back_to_legacy_behavior(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/zeta.png', char_name='Zeta', last_modified=100.0),
            _make_card('cards/alpha.png', char_name='Alpha', last_modified=200.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('indexed path should not run')),
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&sort=name_asc')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png', 'cards/zeta.png']


def test_indexed_list_cards_malformed_search_input_does_not_500(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=%22')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['cards'] == []
    assert payload['total_count'] == 0


def test_indexed_list_cards_fulltext_search_returns_matches(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_fulltext_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=%22quoted%20term%22&search_mode=fulltext')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/fulltext.png']
    assert payload['total_count'] == 1


def test_indexed_list_cards_malformed_fulltext_search_input_does_not_500(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_fulltext_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&search=%22&search_mode=fulltext')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['cards'] == []
    assert payload['total_count'] == 0


def test_indexed_list_cards_returns_relative_ids_when_index_source_paths_are_absolute(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    absolute_source_path = str((tmp_path / 'cards' / 'alpha.png').resolve())

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute("UPDATE index_build_state SET active_generation = 1, state = 'ready', phase = 'ready' WHERE scope = 'cards'")
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'card::cards/alpha.png', 'card', absolute_source_path, 'Alpha', 'alpha.png', 'SciFi', 'SciFi', 'physical', 0, 'pilot note', 200.0, 150.0, 3200, 'alpha', 200.0, '', '200:1'),
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)",
            (1, 'card::cards/alpha.png', 'Alpha alpha.png SciFi pilot note'),
        )
        conn.commit()

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']


def test_indexed_list_cards_root_category_normalizes_sentinel(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_root_index(db_path)

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=%E6%A0%B9%E7%9B%AE%E5%BD%95')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/root.png']


def test_indexed_list_cards_returns_sidebar_and_tag_metadata_from_cache_and_ui_state(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/alpha.png', char_name='Alpha', category='SciFi', tags=['blue', 'hero']),
            _make_card('cards/beta.png', char_name='Beta', category='Fantasy', tags=['green']),
        ],
    )
    _seed_index(db_path)

    ui_payload = {
        '_tag_order_v1': {'order': ['hero', 'blue', 'green'], 'enabled': True},
        '_tag_taxonomy_v1': {
            'default_category': 'Other',
            'categories': {
                'Roles': {'color': '#123456', 'opacity': 70},
                'Palette': {'color': '#abcdef', 'opacity': 45},
                'Other': {'color': '#999999', 'opacity': 20},
            },
            'tag_to_category': {
                'hero': 'Roles',
                'blue': 'Palette',
                'green': 'Palette',
            },
            'category_order': ['Roles', 'Palette', 'Other'],
            'category_tag_order': {'Palette': ['green', 'blue']},
        },
    }
    _write_ui_data(tmp_path / 'ui_data.json', ui_payload)

    fake_cache = cards_api.ctx.cache
    fake_cache.global_tags = {'green', 'hero', 'blue'}

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=SciFi')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['sidebar_tags'] == ['hero', 'blue']
    assert payload['global_tags'] == ['hero', 'blue', 'green']
    assert payload['tag_taxonomy'] == get_tag_taxonomy(ui_payload)
    assert payload['sidebar_tag_groups'] == [
        {'category': 'Roles', 'color': '#123456', 'opacity': 70, 'tags': ['hero']},
        {'category': 'Palette', 'color': '#abcdef', 'opacity': 45, 'tags': ['blue']},
    ]
    assert payload['global_tag_groups'] == [
        {'category': 'Roles', 'color': '#123456', 'opacity': 70, 'tags': ['hero']},
        {'category': 'Palette', 'color': '#abcdef', 'opacity': 45, 'tags': ['green', 'blue']},
    ]


def test_indexed_list_cards_sorts_all_folders_like_legacy_response(monkeypatch, tmp_path):
    db_path = _configure_indexed_list(monkeypatch, tmp_path, [])
    _seed_index(db_path)

    fake_cache = cards_api.ctx.cache
    fake_cache.visible_folders = ['z-last', 'Alpha', 'alpha/sub', 'beta']

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['all_folders'] == ['Alpha', 'alpha/sub', 'beta', 'z-last']


def test_query_indexed_cards_reraises_unrelated_operational_error(monkeypatch):
    class _BrokenConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(
        'core.services.card_index_query_service._connect',
        lambda _db_path=None: _BrokenConnection(),
    )

    try:
        query_indexed_cards({'search': 'alpha', 'page': 1, 'page_size': 20})
    except sqlite3.OperationalError as exc:
        assert 'database is locked' in str(exc)
    else:
        raise AssertionError('Expected sqlite3.OperationalError to be re-raised')


def test_query_indexed_cards_reraises_no_such_column_operational_error(monkeypatch):
    class _BrokenConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError('no such column: missing_column')

    monkeypatch.setattr(
        'core.services.card_index_query_service._connect',
        lambda _db_path=None: _BrokenConnection(),
    )

    try:
        query_indexed_cards({'search': 'alpha', 'page': 1, 'page_size': 20})
    except sqlite3.OperationalError as exc:
        assert 'no such column: missing_column' in str(exc)
    else:
        raise AssertionError('Expected sqlite3.OperationalError to be re-raised')


def test_query_indexed_cards_reads_only_active_generation_v2_rows(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    _seed_index_v2_cards(db_path, active_generation=3)

    result = query_indexed_cards({
        'page': 1,
        'page_size': 20,
        'category': 'SciFi',
        'search': 'pilot',
        'search_mode': 'fast',
        'include_tags': ['blue'],
        'db_path': str(db_path),
    })

    assert result['index_ready'] is True
    assert [item['id'] for item in result['cards']] == ['cards/alpha.png']
    assert result['total_count'] == 1


def test_query_indexed_cards_reports_not_ready_when_active_generation_missing(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    result = query_indexed_cards({
        'page': 1,
        'page_size': 20,
        'db_path': str(db_path),
    })

    assert result == {
        'cards': [],
        'total_count': 0,
        'index_ready': False,
    }


def test_list_cards_falls_back_when_index_query_reports_not_ready(monkeypatch, tmp_path):
    _configure_indexed_list(
        monkeypatch,
        tmp_path,
        [
            _make_card('cards/alpha.png', char_name='Alpha', category='SciFi', last_modified=10.0),
            _make_card('cards/beta.png', char_name='Beta', category='Fantasy', last_modified=20.0),
        ],
    )
    monkeypatch.setattr(
        cards_api,
        'query_indexed_cards',
        lambda *_args, **_kwargs: {'cards': [], 'total_count': 0, 'index_ready': False},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/list_cards?page=1&page_size=20&category=SciFi')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['id'] for item in payload['cards']] == ['cards/alpha.png']
