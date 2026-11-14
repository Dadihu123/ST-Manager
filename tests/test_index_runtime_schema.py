import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import db_session
from core.data.index_runtime_store import INDEX_RUNTIME_SCHEMA_VERSION, ensure_index_runtime_schema


def test_init_database_creates_runtime_index_v2_tables(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda conn: None)
    from core.services import wi_entry_history_service as history
    world = tmp_path / 'worldinfo'
    resources = tmp_path / 'resources'
    world.mkdir()
    resources.mkdir()
    monkeypatch.setattr(history, 'load_config', lambda: {
        'world_info_dir': str(world), 'resources_dir': str(resources),
    })

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
        }

    assert 'index_schema_state' in names
    assert 'index_build_state' in names
    assert 'index_entities_v2' in names
    assert 'index_entity_tags_v2' in names
    assert 'index_search_fast_v2' in names
    assert 'index_search_full_v2' in names
    assert 'index_category_stats_v2' in names
    assert 'index_facet_stats_v2' in names
    assert 'wi_history_roots' in names
    with sqlite3.connect(db_path) as conn:
        assert conn.execute('SELECT roots_json FROM wi_history_roots WHERE id = 1').fetchone()


def test_init_database_adds_wi_metadata_scanned_column(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda conn: None)

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        columns = [
            row[1]
            for row in conn.execute('PRAGMA table_info(card_metadata)')
        ]

    assert 'wi_metadata_scanned' in columns


def test_init_database_seeds_schema_and_build_state_rows(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda conn: None)

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        schema_rows = conn.execute(
            'SELECT component, applied_version, state FROM index_schema_state ORDER BY component'
        ).fetchall()
        build_rows = conn.execute(
            'SELECT scope, active_generation, building_generation, state FROM index_build_state ORDER BY scope'
        ).fetchall()

    assert schema_rows == [
        ('db', 1, 'ready'),
        ('index_runtime', INDEX_RUNTIME_SCHEMA_VERSION, 'ready'),
    ]
    assert build_rows == [('cards', 0, 0, 'empty'), ('worldinfo', 0, 0, 'empty')]


def test_init_database_adds_pending_job_indexes(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda conn: None)

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[1]
            for row in conn.execute('PRAGMA index_list(index_jobs)')
        }

    assert 'idx_index_jobs_status_id' in indexes
    assert 'idx_index_jobs_type_status_id' in indexes


def test_init_database_adds_missing_character_book_name_for_existing_db(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0
            )
            '''
        )
        conn.commit()

    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(db_session, '_migrate_existing_data', lambda conn: None)

    db_session.init_database()

    with sqlite3.connect(db_path) as conn:
        columns = [
            row[1]
            for row in conn.execute('PRAGMA table_info(card_metadata)')
        ]

    assert 'character_book_name' in columns


def test_ensure_index_runtime_schema_refreshes_existing_schema_state_versions(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE index_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,
                entity_id TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                payload_json TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
                started_at REAL DEFAULT 0,
                finished_at REAL DEFAULT 0,
                error_msg TEXT DEFAULT ''
            )
            '''
        )
        ensure_index_runtime_schema(conn)
        conn.execute(
            '''
            UPDATE index_schema_state
            SET target_version = ?, applied_version = ?, state = ?
            WHERE component = ?
            ''',
            (99, 98, 'failed', 'index_runtime'),
        )
        conn.commit()

        ensure_index_runtime_schema(conn)

        runtime_row = conn.execute(
            '''
            SELECT target_version, applied_version, state
            FROM index_schema_state
            WHERE component = ?
            ''',
            ('index_runtime',),
        ).fetchone()
        db_row = conn.execute(
            '''
            SELECT target_version, applied_version, state
            FROM index_schema_state
            WHERE component = ?
            ''',
            ('db',),
        ).fetchone()

    assert runtime_row == (INDEX_RUNTIME_SCHEMA_VERSION, INDEX_RUNTIME_SCHEMA_VERSION, 'ready')
    assert db_row == (1, 1, 'ready')
