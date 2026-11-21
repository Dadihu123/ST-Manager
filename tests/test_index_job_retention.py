import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services import index_job_worker


def test_mark_job_status_prunes_done_history_but_keeps_recoverable_intents(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_job_worker, 'INDEX_JOB_DONE_RETENTION', 3, raising=False)

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        for idx in range(5):
            conn.execute(
                'INSERT INTO index_jobs(job_type, status, finished_at, error_msg) VALUES (?, ?, ?, ?)',
                ('rebuild_scope', 'done', float(idx + 1), ''),
            )
        for idx in range(4):
            conn.execute(
                'INSERT INTO index_jobs(job_type, status, finished_at, error_msg) VALUES (?, ?, ?, ?)',
                ('upsert_card', 'failed', float(idx + 1), f'failed-{idx}'),
            )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status) VALUES (?, ?)',
            ('upsert_worldinfo_path', 'pending'),
        )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status, started_at, error_msg) VALUES (?, ?, ?, ?)',
            ('upsert_world_owner', 'running', 99.0, 'claim:active'),
        )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status) VALUES (?, ?)',
            ('upsert_world_embedded', 'pending'),
        )
        trigger_job_id = conn.execute(
            'SELECT MAX(id) FROM index_jobs'
        ).fetchone()[0]
        conn.commit()

    index_job_worker._mark_job_status(trigger_job_id, 'done', '')

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT id, job_type, status, error_msg FROM index_jobs ORDER BY id'
        ).fetchall()

    assert rows == [
        (4, 'rebuild_scope', 'done', ''),
        (5, 'rebuild_scope', 'done', ''),
        (6, 'upsert_card', 'failed', 'failed-0'),
        (7, 'upsert_card', 'failed', 'failed-1'),
        (8, 'upsert_card', 'failed', 'failed-2'),
        (9, 'upsert_card', 'failed', 'failed-3'),
        (10, 'upsert_worldinfo_path', 'pending', ''),
        (11, 'upsert_world_owner', 'running', 'claim:active'),
        (12, 'upsert_world_embedded', 'done', ''),
    ]


def test_mark_job_status_keeps_all_unrecovered_failures(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_job_worker, 'INDEX_JOB_DONE_RETENTION', 10, raising=False)

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            'INSERT INTO index_jobs(job_type, status, finished_at, error_msg) VALUES (?, ?, ?, ?)',
            ('upsert_card', 'failed', 500.0, 'older-id-newest-failure'),
        )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status, finished_at, error_msg) VALUES (?, ?, ?, ?)',
            ('upsert_card', 'failed', 100.0, 'older-failure'),
        )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status, finished_at, error_msg) VALUES (?, ?, ?, ?)',
            ('upsert_card', 'failed', 200.0, 'middle-failure'),
        )
        conn.execute(
            'INSERT INTO index_jobs(job_type, status) VALUES (?, ?)',
            ('upsert_world_embedded', 'pending'),
        )
        trigger_job_id = conn.execute('SELECT MAX(id) FROM index_jobs').fetchone()[0]
        conn.commit()

    index_job_worker._mark_job_status(trigger_job_id, 'failed', 'latest-failure')

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, status, error_msg FROM index_jobs WHERE status = 'failed' ORDER BY finished_at, id"
        ).fetchall()

    assert rows == [
        (2, 'failed', 'older-failure'),
        (3, 'failed', 'middle-failure'),
        (1, 'failed', 'older-id-newest-failure'),
        (4, 'failed', 'latest-failure'),
    ]
