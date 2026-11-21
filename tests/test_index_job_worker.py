import sqlite3
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.context import ctx
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services import index_job_worker


def test_enqueue_index_job_sets_worker_event(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    ctx.index_wakeup.clear()

    index_job_worker.enqueue_index_job('upsert_card', entity_id='hero.png', source_path='hero.png')

    assert ctx.index_wakeup.is_set() is True


def test_worker_waits_on_event_before_querying_jobs(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    waits = []

    class _StopLoop(Exception):
        pass

    def fake_wait(timeout):
        waits.append(timeout)
        raise _StopLoop()

    monkeypatch.setattr(ctx.index_wakeup, 'wait', fake_wait)

    try:
        index_job_worker.worker_loop()
    except _StopLoop:
        pass

    assert waits == [30]


def test_worker_skips_claiming_jobs_while_background_upgrade_runs(monkeypatch, tmp_path):
    """后台索引升级期间不得领取增量作业（否则会写进即将被丢弃的 generation）。"""
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            "INSERT INTO index_jobs(job_type, payload_json) VALUES ('upsert_card', '{}')"
        )
        conn.commit()

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    claimed = []
    monkeypatch.setattr(
        index_job_worker, '_claim_pending_jobs', lambda limit=50: (claimed.append(limit), ([], 0))[1]
    )

    class _StopLoop(Exception):
        pass

    state = {'waits': 0}

    def fake_wakeup_wait(timeout):
        state['waits'] += 1
        return True

    def fake_upgrade_wait(timeout):
        raise _StopLoop()

    monkeypatch.setattr(ctx.index_wakeup, 'wait', fake_wakeup_wait)
    monkeypatch.setattr(ctx.index_upgrade_done, 'wait', fake_upgrade_wait)
    ctx.index_upgrade_active = True

    try:
        index_job_worker.worker_loop()
    except _StopLoop:
        pass
    finally:
        ctx.index_upgrade_active = False
        ctx.index_upgrade_done.set()

    assert claimed == []
    assert ctx.index_state['jobs']['worker_state'] == 'waiting'


def test_worker_resumes_claiming_after_upgrade_finishes(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    claimed = []

    class _StopLoop(Exception):
        pass

    def fake_claim(limit=50):
        claimed.append(limit)
        raise _StopLoop()

    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', fake_claim)
    monkeypatch.setattr(ctx.index_wakeup, 'wait', lambda timeout: True)
    ctx.index_upgrade_active = False
    ctx.index_upgrade_done.set()

    try:
        index_job_worker.worker_loop()
    except _StopLoop:
        pass

    assert claimed == [50]


def test_enqueue_index_job_updates_visible_pending_jobs_immediately(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))
    ctx.index_state.update({'pending_jobs': 0})
    ctx.index_state['jobs']['pending_jobs'] = 0

    index_job_worker.enqueue_index_job('upsert_card', entity_id='hero.png', source_path='hero.png')

    assert ctx.index_state['jobs']['pending_jobs'] == 1
    assert ctx.index_state['pending_jobs'] == 1


def test_enqueue_index_job_skips_duplicate_pending_job(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    index_job_worker.enqueue_index_job('upsert_worldinfo_path', source_path='D:/data/lorebooks/book.json')
    index_job_worker.enqueue_index_job('upsert_worldinfo_path', source_path='D:/data/lorebooks/book.json')

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT job_type, status, source_path FROM index_jobs ORDER BY id'
        ).fetchall()

    assert rows == [('upsert_worldinfo_path', 'pending', 'D:/data/lorebooks/book.json')]


def test_enqueue_index_job_hot_path_does_not_reensure_schema(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    def _boom(_conn):
        raise AssertionError('ensure_index_runtime_schema should not be called from enqueue hot path')

    monkeypatch.setattr(index_job_worker, 'ensure_index_runtime_schema', _boom)

    index_job_worker.enqueue_index_job('upsert_card', entity_id='hero.png', source_path='hero.png')

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT job_type, entity_id, source_path, status FROM index_jobs ORDER BY id DESC LIMIT 1'
        ).fetchone()

    assert row == ('upsert_card', 'hero.png', 'hero.png', 'pending')


def test_worker_claims_pending_jobs_before_processing(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute(
            'INSERT INTO index_jobs(job_type, payload_json) VALUES (?, ?)',
            ('rebuild_scope', '{"scope": "cards"}'),
        )
        conn.commit()

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    class _StopLoop(Exception):
        pass

    wait_calls = {'count': 0}
    observed = {}

    def fake_wait(_timeout):
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopLoop()
        return True

    def fake_rebuild_scope_generation(_scope='cards', reason='bootstrap', *, rebuild_job):
        with sqlite3.connect(db_path) as conn:
            job_id, claim_token = rebuild_job
            observed['status'] = conn.execute(
                'SELECT status FROM index_jobs WHERE id=? AND error_msg=?', (job_id, claim_token),
            ).fetchone()[0]

    monkeypatch.setattr(ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker, 'rebuild_scope_generation', fake_rebuild_scope_generation)
    ctx.index_wakeup.set()

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert observed['status'] == 'running'


def test_start_index_job_worker_starts_only_one_thread(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(ctx, 'index_worker_started', False)
    monkeypatch.setattr(ctx, 'index_wakeup', threading.Event())
    with index_job_worker._connect(ensure_schema=True) as conn:
        conn.executemany("INSERT INTO index_jobs(job_type,status,finished_at) VALUES ('rebuild_scope',?,?)",
                         [('running', 0), ('failed', 100), ('running', 200)])

    class _FakeThread:
        def __init__(self, *, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            assert ctx.index_wakeup.is_set()
            started.append(self.target)

    monkeypatch.setattr(index_job_worker.threading, 'Thread', _FakeThread)
    index_job_worker.start_index_job_worker()
    index_job_worker.start_index_job_worker()

    assert len(started) == 1
    class StopWorker(Exception):
        pass

    def stop_after_recovery(_timeout):
        raise StopWorker()

    monkeypatch.setattr(ctx.index_wakeup, 'wait', stop_after_recovery)
    with pytest.raises(StopWorker):
        started[0]()
    assert not ctx.index_worker_started
    with index_job_worker._connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT status,finished_at FROM index_jobs ORDER BY id')] == [
            ('pending', 0), ('failed', 100), ('failed', 200)]


def test_claim_pending_jobs_returns_only_rows_claimed_by_current_invocation(monkeypatch, tmp_path):
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    with index_job_worker._connect(ensure_schema=True) as conn:
        # 高 ID 的失败意图等待最久；未到期的意图保留状态和错误信息。
        conn.executemany("INSERT INTO index_jobs(job_type,status,finished_at) VALUES ('retry','failed',?)",
                         [(100 - i,) for i in range(60)])
        conn.executemany("INSERT INTO index_jobs(job_type) VALUES (?)", [('fresh',)] * 60)
        conn.execute("INSERT INTO index_jobs(job_type,status,finished_at,error_msg) "
                     "VALUES ('later','failed',strftime('%s','now'),'backoff')")
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait(timeout=10)
        return index_job_worker._claim_pending_jobs(50)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        batches = [future.result() for future in futures]
    assert sorted(count for _, count in batches) == [20, 70]
    for rows, _ in batches:
        assert len(rows) == 50 and sum(row['job_type'] == 'fresh' for row in rows) == 25
    claimed = [row['id'] for rows, _ in batches for row in rows]
    assert len(set(claimed)) == len(claimed)
    assert set(claimed) == set(range(11, 111))
    with index_job_worker._connect() as conn:
        assert tuple(conn.execute("SELECT status,error_msg FROM index_jobs WHERE job_type='later'").fetchone()) == (
            'failed', 'backoff')


def test_worker_routes_legacy_resource_worldinfo_path_job_via_shared_classifier(monkeypatch):
    class _StopLoop(Exception):
        pass

    rows = [[{
        'id': 1,
        'job_type': 'upsert_worldinfo_path',
        'entity_id': '',
        'source_path': 'D:/data/resources/hero-assets/lorebooks/book.json',
        'payload_json': '{}',
    }], []]
    calls = []
    wait_calls = {'count': 0}

    def fake_wait(_timeout):
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopLoop()
        return True

    class _FakeResult:
        def fetchone(self):
            return [0]

    class _FakeConn:
        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeResult()

        def commit(self):
            calls.append(('commit',))

        def rollback(self):
            calls.append(('rollback',))

    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'clear', lambda: None)

    def fake_claim_pending_jobs(_limit):
        return rows.pop(0), 0

    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', fake_claim_pending_jobs)
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', lambda **_kwargs: None)
    monkeypatch.setattr(index_job_worker, '_mark_job_status', lambda job_id, status, error_msg='': calls.append(('mark', job_id, status, error_msg)))
    monkeypatch.setattr(index_job_worker, '_connect', lambda **_kwargs: _FakeConn())
    from contextlib import nullcontext
    monkeypatch.setattr(index_job_worker, 'worldinfo_increment_batch', lambda _conn: nullcontext())
    monkeypatch.setattr(
        index_job_worker,
        'classify_worldinfo_path',
        lambda source_path: {'kind': 'resource', 'source_path': source_path},
    )
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, _source_path: calls.append(('global', _source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_resource_path_increment',
                        lambda _conn, path, owners, old, *, commit:
                        calls.append(('resource', path, owners, old, commit)) or True)
    monkeypatch.setattr(index_job_worker, '_indexed_resource_rows', lambda *_args: [])
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda source_path, **_: ['cards/alpha.png', 'cards/zeta.png'] if 'hero-assets' in source_path else [], raising=False)

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('resource', 'D:/data/resources/hero-assets/lorebooks/book.json',
         ['cards/alpha.png', 'cards/zeta.png'], [], False),
        ('mark', 1, 'done', ''),
    ]


def test_worker_routes_relative_resource_worldinfo_path_via_real_classifier(monkeypatch, tmp_path):
    class _StopLoop(Exception):
        pass

    base_dir = tmp_path / 'runtime'
    resource_file = base_dir / 'data' / 'assets' / 'card_assets' / 'hero-assets' / 'lorebooks' / 'book.json'
    resource_file.parent.mkdir(parents=True)
    resource_file.write_text('{}', encoding='utf-8')

    rows = [[{
        'id': 1,
        'job_type': 'upsert_worldinfo_path',
        'entity_id': '',
        'source_path': str(resource_file),
        'payload_json': '{}',
    }], []]
    calls = []
    wait_calls = {'count': 0}

    def fake_wait(_timeout):
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopLoop()
        return True

    class _FakeResult:
        def fetchone(self):
            return [0]

    class _FakeConn:
        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeResult()

        def commit(self):
            calls.append(('commit',))

        def rollback(self):
            calls.append(('rollback',))

    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'clear', lambda: None)
    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', lambda _limit: (rows.pop(0), 0))
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', lambda **_kwargs: None)
    monkeypatch.setattr(index_job_worker, '_mark_job_status', lambda job_id, status, error_msg='': calls.append(('mark', job_id, status, error_msg)))
    monkeypatch.setattr(index_job_worker, '_connect', lambda **_kwargs: _FakeConn())
    from contextlib import nullcontext
    monkeypatch.setattr(index_job_worker, 'worldinfo_increment_batch', lambda _conn: nullcontext())
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, _source_path: calls.append(('global', _source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_resource_path_increment',
                        lambda _conn, path, owners, old, *, commit:
                        calls.append(('resource', path, owners, old, commit)) or True)
    monkeypatch.setattr(index_job_worker, '_indexed_resource_rows', lambda *_args: [])
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda source_path, **_: ['cards/alpha.png'] if str(resource_file) == source_path else [], raising=False)
    monkeypatch.setattr(index_job_worker, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    }, raising=False)
    monkeypatch.setattr(index_job_worker, 'BASE_DIR', str(base_dir), raising=False)
    monkeypatch.setattr('core.services.index_build_service.BASE_DIR', str(base_dir))
    monkeypatch.setattr('core.services.index_build_service.load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('resource', str(resource_file), ['cards/alpha.png'], [], False),
        ('mark', 1, 'done', ''),
    ]


def test_worker_keeps_global_worldinfo_path_on_global_increment_branch(monkeypatch):
    class _StopLoop(Exception):
        pass

    rows = [[{
        'id': 1,
        'job_type': 'upsert_worldinfo_path',
        'entity_id': '',
        'source_path': 'D:/data/lorebooks/main/book.json',
        'payload_json': '{}',
    }], []]
    calls = []
    wait_calls = {'count': 0}

    def fake_wait(_timeout):
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopLoop()
        return True

    class _FakeResult:
        def fetchone(self):
            return [0]

    class _FakeConn:
        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'clear', lambda: None)

    def fake_claim_pending_jobs(_limit):
        return rows.pop(0), 0

    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', fake_claim_pending_jobs)
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', lambda **_kwargs: None)
    monkeypatch.setattr(index_job_worker, '_mark_job_status', lambda job_id, status, error_msg='': calls.append(('mark', job_id, status, error_msg)))
    monkeypatch.setattr(index_job_worker, '_connect', lambda **_kwargs: _FakeConn())
    from contextlib import nullcontext
    monkeypatch.setattr(index_job_worker, 'worldinfo_increment_batch', lambda _conn: nullcontext())
    monkeypatch.setattr(
        index_job_worker,
        'classify_worldinfo_path',
        lambda source_path: {'kind': 'global', 'source_path': source_path},
    )
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, source_path: calls.append(('global', source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_owner_increment', lambda _conn, entity_id, source_path='': calls.append(('owner', entity_id, source_path)) or True)

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('global', 'D:/data/lorebooks/main/book.json'),
        ('mark', 1, 'done', ''),
    ]


def test_worker_does_not_fall_back_to_global_increment_for_resource_path_without_owners(monkeypatch):
    class _StopLoop(Exception):
        pass

    rows = [[{
        'id': 1,
        'job_type': 'upsert_worldinfo_path',
        'entity_id': '',
        'source_path': 'D:/data/resources/orphan-pack/lorebooks/book.json',
        'payload_json': '{}',
    }], []]
    calls = []
    wait_calls = {'count': 0}

    def fake_wait(_timeout):
        wait_calls['count'] += 1
        if wait_calls['count'] >= 2:
            raise _StopLoop()
        return True

    class _FakeResult:
        def fetchone(self):
            return [0]

    class _FakeConn:
        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'clear', lambda: None)

    def fake_claim_pending_jobs(_limit):
        return rows.pop(0), 0

    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', fake_claim_pending_jobs)
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', lambda **_kwargs: None)
    monkeypatch.setattr(index_job_worker, '_mark_job_status', lambda job_id, status, error_msg='': calls.append(('mark', job_id, status, error_msg)))
    monkeypatch.setattr(index_job_worker, '_connect', lambda **_kwargs: _FakeConn())
    from contextlib import nullcontext
    monkeypatch.setattr(index_job_worker, 'worldinfo_increment_batch', lambda _conn: nullcontext())
    monkeypatch.setattr(
        index_job_worker,
        'classify_worldinfo_path',
        lambda source_path: {'kind': 'resource', 'source_path': source_path},
    )
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, source_path: calls.append(('global', source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_owner_increment', lambda _conn, entity_id, source_path='': calls.append(('owner', entity_id, source_path)) or True)
    monkeypatch.setattr(index_job_worker, '_indexed_resource_rows', lambda *_args: [])
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda _source_path, **_: [], raising=False)

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('mark', 1, 'done', ''),
    ]
