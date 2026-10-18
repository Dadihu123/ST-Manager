import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.context import AppContext
from core.data.index_runtime_store import (
    activate_generation,
    allocate_build_generation,
    clear_generation_data,
    ensure_index_runtime_schema,
    get_build_progress,
    update_build_progress,
)


def test_ensure_schema_adds_build_progress_columns_to_existing_database(tmp_path):
    """老库的 index_build_state 没有进度列，升级时必须补上，否则前端没有进度。"""
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE index_build_state (
                scope TEXT PRIMARY KEY,
                active_generation INTEGER NOT NULL DEFAULT 0,
                building_generation INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'empty',
                phase TEXT NOT NULL DEFAULT '',
                build_reason TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL DEFAULT 0,
                finished_at REAL NOT NULL DEFAULT 0,
                last_error TEXT DEFAULT '',
                owner_token TEXT DEFAULT '',
                items_written INTEGER NOT NULL DEFAULT 0
            )
            '''
        )
        conn.execute(
            "INSERT INTO index_build_state(scope) VALUES ('worldinfo')"
        )
        conn.commit()

        ensure_index_runtime_schema(conn)
        # 再跑一次必须幂等（列已存在时不报错）。
        ensure_index_runtime_schema(conn)

        columns = {
            row[1] for row in conn.execute('PRAGMA table_info(index_build_state)').fetchall()
        }

    assert 'progress_done' in columns
    assert 'progress_total' in columns


def test_update_build_progress_roundtrip(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        update_build_progress(
            conn, 'worldinfo', phase='build_entities', done=12, total=40, commit=True
        )
        progress = get_build_progress(conn, 'worldinfo')
        phase = conn.execute(
            "SELECT phase FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()[0]

    assert progress == {'done': 12, 'total': 40}
    assert phase == 'build_entities'


def test_allocate_build_generation_resets_progress(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        update_build_progress(conn, 'cards', phase='build_entities', done=99, total=99, commit=True)
        allocate_build_generation(conn, 'cards')

    with sqlite3.connect(db_path) as conn:
        assert get_build_progress(conn, 'cards') == {'done': 0, 'total': 0}


def test_allocate_build_generation_increments_from_active(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 4 WHERE scope = 'cards'"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        generation = allocate_build_generation(conn, 'cards')
        row = conn.execute(
            "SELECT active_generation, building_generation FROM index_build_state WHERE scope = 'cards'"
        ).fetchone()

    assert generation == 5
    assert row == (4, 5)


def test_activate_generation_promotes_building_generation(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 2, building_generation = 3, state = 'running', phase = 'activate_generation' WHERE scope = 'cards'"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        activate_generation(conn, 'cards', 3, items_written=12)
        row = conn.execute(
            "SELECT active_generation, building_generation, state, items_written FROM index_build_state WHERE scope = 'cards'"
        ).fetchone()

    assert row == (3, 0, 'ready', 12)


def test_activate_generation_rejects_stale_generation(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 2, building_generation = 4, state = 'running', phase = 'activate_generation' WHERE scope = 'cards'"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        activated = activate_generation(conn, 'cards', 3, items_written=12)
        row = conn.execute(
            "SELECT active_generation, building_generation, state, items_written FROM index_build_state WHERE scope = 'cards'"
        ).fetchone()

    assert activated is False
    assert row == (2, 4, 'running', 0)


def test_activate_generation_cleans_obsolete_scope_generations(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 1, building_generation = 2, state = 'running', phase = 'activate_generation' WHERE scope = 'cards'"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (1, 'card::old.png', 'card', 'old.png', 'Old', 'old.png')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (2, 'card::new.png', 'card', 'new.png', 'New', 'new.png')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (1, 'world::global::book.json', 'world_global', 'book.json', 'Book', 'book.json')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (1, 'card::old.png', 'stale-card')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (2, 'card::new.png', 'fresh-card')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (1, 'world::global::book.json', 'world-tag')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (1, 'card::old.png', 'old fast')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (2, 'card::new.png', 'new fast')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (1, 'world::global::book.json', 'world fast')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (1, 'card::old.png', 'old full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (2, 'card::new.png', 'new full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (1, 'world::global::book.json', 'world full')"
        )
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (1, 'cards', 'card', 'old', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (1, 'worldinfo', 'world_global', 'books', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (1, 'cards', 'card', 'tag', 'stale-card', 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (1, 'worldinfo', 'world_global', 'tag', 'world-tag', 1)"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        activated = activate_generation(conn, 'cards', 2, items_written=1)
        state_row = conn.execute(
            "SELECT active_generation, building_generation, state, items_written FROM index_build_state WHERE scope = 'cards'"
        ).fetchone()
        entity_rows = conn.execute(
            'SELECT generation, entity_id FROM index_entities_v2 ORDER BY generation, entity_id'
        ).fetchall()
        tag_rows = conn.execute(
            'SELECT generation, entity_id, tag FROM index_entity_tags_v2 ORDER BY generation, entity_id'
        ).fetchall()
        fast_rows = conn.execute(
            'SELECT generation, entity_id, content FROM index_search_fast_v2 ORDER BY generation, entity_id'
        ).fetchall()
        full_rows = conn.execute(
            'SELECT generation, entity_id, content FROM index_search_full_v2 ORDER BY generation, entity_id'
        ).fetchall()
        category_rows = conn.execute(
            'SELECT generation, scope, entity_type, category_path FROM index_category_stats_v2 ORDER BY scope, generation'
        ).fetchall()
        facet_rows = conn.execute(
            'SELECT generation, scope, entity_type, facet_name, facet_value FROM index_facet_stats_v2 ORDER BY scope, generation'
        ).fetchall()

    assert activated is True
    assert state_row == (2, 0, 'ready', 1)
    assert entity_rows == [
        (1, 'world::global::book.json'),
        (2, 'card::new.png'),
    ]
    assert tag_rows == [
        (1, 'world::global::book.json', 'world-tag'),
        (2, 'card::new.png', 'fresh-card'),
    ]
    assert fast_rows == [
        (1, 'world::global::book.json', 'world fast'),
        (2, 'card::new.png', 'new fast'),
    ]
    assert full_rows == [
        (1, 'world::global::book.json', 'world full'),
        (2, 'card::new.png', 'new full'),
    ]
    assert category_rows == [
        (1, 'worldinfo', 'world_global', 'books'),
    ]
    assert facet_rows == [
        (1, 'worldinfo', 'world_global', 'tag', 'world-tag'),
    ]


def test_activate_generation_cleans_obsolete_worldinfo_generations(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "UPDATE index_build_state SET active_generation = 4, building_generation = 5, state = 'running', phase = 'activate_generation' WHERE scope = 'worldinfo'"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename) VALUES (4, 'world::global::old.json', 'world_global', 'old.json', '', 'Old Global', 'old.json')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename) VALUES (5, 'world::global::new.json', 'world_global', 'new.json', '', 'New Global', 'new.json')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename) VALUES (4, 'card::hero.png', 'card', 'hero.png', '', 'Hero', 'hero.png')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (4, 'world::global::old.json', 'old-world')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (5, 'world::global::new.json', 'new-world')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (4, 'card::hero.png', 'card-tag')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (4, 'world::global::old.json', 'old world fast')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (5, 'world::global::new.json', 'new world fast')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (4, 'card::hero.png', 'card fast')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (4, 'world::global::old.json', 'old world full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (5, 'world::global::new.json', 'new world full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (4, 'card::hero.png', 'card full')"
        )
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (4, 'worldinfo', 'world_global', 'old', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (4, 'cards', 'card', 'hero', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (4, 'worldinfo', 'world_global', 'tag', 'old-world', 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (4, 'cards', 'card', 'tag', 'card-tag', 1)"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        activated = activate_generation(conn, 'worldinfo', 5, items_written=1)
        entity_rows = conn.execute(
            'SELECT generation, entity_id FROM index_entities_v2 ORDER BY generation, entity_id'
        ).fetchall()
        tag_rows = conn.execute(
            'SELECT generation, entity_id, tag FROM index_entity_tags_v2 ORDER BY generation, entity_id'
        ).fetchall()
        fast_rows = conn.execute(
            'SELECT generation, entity_id, content FROM index_search_fast_v2 ORDER BY generation, entity_id'
        ).fetchall()
        full_rows = conn.execute(
            'SELECT generation, entity_id, content FROM index_search_full_v2 ORDER BY generation, entity_id'
        ).fetchall()
        category_rows = conn.execute(
            'SELECT generation, scope, entity_type, category_path FROM index_category_stats_v2 ORDER BY scope, generation'
        ).fetchall()
        facet_rows = conn.execute(
            'SELECT generation, scope, entity_type, facet_name, facet_value FROM index_facet_stats_v2 ORDER BY scope, generation'
        ).fetchall()

    assert activated is True
    assert entity_rows == [
        (4, 'card::hero.png'),
        (5, 'world::global::new.json'),
    ]
    assert tag_rows == [
        (4, 'card::hero.png', 'card-tag'),
        (5, 'world::global::new.json', 'new-world'),
    ]
    assert fast_rows == [
        (4, 'card::hero.png', 'card fast'),
        (5, 'world::global::new.json', 'new world fast'),
    ]
    assert full_rows == [
        (4, 'card::hero.png', 'card full'),
        (5, 'world::global::new.json', 'new world full'),
    ]
    assert category_rows == [
        (4, 'cards', 'card', 'hero'),
    ]
    assert facet_rows == [
        (4, 'cards', 'card', 'tag', 'card-tag'),
    ]


def test_clear_generation_data_removes_only_target_generation(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (1, 'card::old', 'card', 'old.png', 'Old', 'old.png')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (2, 'card::new', 'card', 'new.png', 'New', 'new.png')"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        clear_generation_data(conn, 'cards', 2)
        rows = conn.execute(
            "SELECT generation, entity_id FROM index_entities_v2 ORDER BY generation, entity_id"
        ).fetchall()

    assert rows == [(1, 'card::old')]


def test_clear_generation_data_preserves_other_scope_rows_for_same_generation(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (2, 'card::same-gen', 'card', 'card.png', 'Card', 'card.png')"
        )
        conn.execute(
            "INSERT INTO index_entities_v2(generation, entity_id, entity_type, source_path, name, filename) VALUES (2, 'world::same-gen', 'world_entry', 'world.json', 'World', 'world.json')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (2, 'card::same-gen', 'card-tag')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (2, 'world::same-gen', 'world-tag')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (2, 'card::same-gen', 'card search')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (2, 'world::same-gen', 'world search')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (2, 'card::same-gen', 'card search full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (2, 'world::same-gen', 'world search full')"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        clear_generation_data(conn, 'cards', 2)
        entity_rows = conn.execute(
            "SELECT generation, entity_id FROM index_entities_v2 ORDER BY entity_id"
        ).fetchall()
        tag_rows = conn.execute(
            "SELECT generation, entity_id, tag FROM index_entity_tags_v2 ORDER BY entity_id"
        ).fetchall()
        fast_rows = conn.execute(
            "SELECT generation, entity_id, content FROM index_search_fast_v2 ORDER BY entity_id"
        ).fetchall()
        full_rows = conn.execute(
            "SELECT generation, entity_id, content FROM index_search_full_v2 ORDER BY entity_id"
        ).fetchall()

    assert entity_rows == [(2, 'world::same-gen')]
    assert tag_rows == [(2, 'world::same-gen', 'world-tag')]
    assert fast_rows == [(2, 'world::same-gen', 'world search')]
    assert full_rows == [(2, 'world::same-gen', 'world search full')]


def test_clear_generation_data_removes_scope_owned_orphan_aux_rows_only(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (2, 'card::orphan', 'card-tag')"
        )
        conn.execute(
            "INSERT INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (2, 'world::orphan', 'world-tag')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (2, 'card::orphan', 'card orphan search')"
        )
        conn.execute(
            "INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (2, 'world::orphan', 'world orphan search')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (2, 'card::orphan', 'card orphan search full')"
        )
        conn.execute(
            "INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (2, 'world::orphan', 'world orphan search full')"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        clear_generation_data(conn, 'cards', 2)
        tag_rows = conn.execute(
            "SELECT generation, entity_id, tag FROM index_entity_tags_v2 ORDER BY entity_id"
        ).fetchall()
        fast_rows = conn.execute(
            "SELECT generation, entity_id, content FROM index_search_fast_v2 ORDER BY entity_id"
        ).fetchall()
        full_rows = conn.execute(
            "SELECT generation, entity_id, content FROM index_search_full_v2 ORDER BY entity_id"
        ).fetchall()

    assert tag_rows == [(2, 'world::orphan', 'world-tag')]
    assert fast_rows == [(2, 'world::orphan', 'world orphan search')]
    assert full_rows == [(2, 'world::orphan', 'world orphan search full')]


def test_clear_generation_data_clears_target_scope_stats(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (2, 'cards', 'card', 'a', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (2, 'worldinfo', 'world_entry', 'a', 1, 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (2, 'cards', 'card', 'tag', 'x', 1)"
        )
        conn.execute(
            "INSERT INTO index_facet_stats_v2(generation, scope, entity_type, facet_name, facet_value, facet_count) VALUES (2, 'worldinfo', 'world_entry', 'tag', 'x', 1)"
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        clear_generation_data(conn, 'cards', 2)
        category_rows = conn.execute(
            "SELECT generation, scope, entity_type, category_path FROM index_category_stats_v2 ORDER BY scope"
        ).fetchall()
        facet_rows = conn.execute(
            "SELECT generation, scope, entity_type, facet_name, facet_value FROM index_facet_stats_v2 ORDER BY scope"
        ).fetchall()

    assert category_rows == [(2, 'worldinfo', 'world_entry', 'a')]
    assert facet_rows == [(2, 'worldinfo', 'world_entry', 'tag', 'x')]


def test_app_context_exposes_richer_index_runtime_state():
    AppContext._instance = None
    ctx = AppContext()

    assert ctx.index_state['schema'] == {
        'db_version': 0,
        'index_runtime_version': 0,
        'state': 'empty',
        'message': '',
    }
    assert ctx.index_state['cards'] == {
        'state': 'empty',
        'phase': '',
        'active_generation': 0,
        'building_generation': 0,
        'items_written': 0,
        'last_error': '',
        'progress_done': 0,
        'progress_total': 0,
    }
    assert ctx.index_state['worldinfo'] == {
        'state': 'empty',
        'phase': '',
        'active_generation': 0,
        'building_generation': 0,
        'items_written': 0,
        'last_error': '',
        'progress_done': 0,
        'progress_total': 0,
    }
    assert ctx.index_state['jobs'] == {
        'pending_jobs': 0,
        'worker_state': 'idle',
    }
    assert ctx.index_state['state'] == 'empty'
    assert ctx.index_state['scope'] == 'cards'
    assert ctx.index_state['progress'] == 0
    assert ctx.index_state['message'] == ''
    assert ctx.index_state['pending_jobs'] == 0
    assert ctx.index_owner_token == ''
    assert ctx.index_wakeup.is_set() is False
    assert ctx.index_upgrade_active is False
    assert ctx.index_worker_started is False

    AppContext._instance = None


def test_app_context_index_state_update_preserves_legacy_flat_keys():
    AppContext._instance = None
    ctx = AppContext()

    ctx.index_state.update(
        state='building',
        scope='worldinfo',
        progress=7,
        message='queued rebuild',
        pending_jobs=3,
    )

    assert ctx.index_state['state'] == 'building'
    assert ctx.index_state['scope'] == 'worldinfo'
    assert ctx.index_state['progress'] == 7
    assert ctx.index_state['message'] == 'queued rebuild'
    assert ctx.index_state['pending_jobs'] == 3
    assert ctx.index_state['worldinfo']['state'] == 'building'
    assert ctx.index_state['jobs']['pending_jobs'] == 3

    snapshot = dict(ctx.index_state)
    assert snapshot['state'] == 'building'
    assert snapshot['scope'] == 'worldinfo'
    assert snapshot['message'] == 'queued rebuild'
    assert snapshot['pending_jobs'] == 3
    assert snapshot['worldinfo']['state'] == 'building'

    AppContext._instance = None
