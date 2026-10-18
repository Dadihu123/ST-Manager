import sqlite3
import sys
import types
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

    def fake_rebuild_scope_generation(_scope='cards', reason='bootstrap'):
        with sqlite3.connect(db_path) as conn:
            observed['status'] = conn.execute('SELECT status FROM index_jobs WHERE id = 1').fetchone()[0]

    monkeypatch.setattr(ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker, 'rebuild_scope_generation', fake_rebuild_scope_generation)
    ctx.index_wakeup.set()

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert observed['status'] == 'running'


def test_start_index_job_worker_starts_only_one_thread(monkeypatch):
    started = []

    class _FakeThread:
        def __init__(self, *, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(index_job_worker.threading, 'Thread', _FakeThread)
    ctx.index_worker_started = False

    index_job_worker.start_index_job_worker()
    index_job_worker.start_index_job_worker()

    assert started == [index_job_worker.worker_loop]


def test_claim_pending_jobs_returns_only_rows_claimed_by_current_invocation(monkeypatch, tmp_path):
    class _FakeResult:
        def __init__(self, *, rows=None, scalar=None):
            self._rows = rows or []
            self._scalar = scalar

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return [self._scalar]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=()):
            normalized = ' '.join(str(sql).split()).lower()
            if normalized.startswith('select id from index_jobs where status = '):
                return _FakeResult(rows=[{'id': 1}])
            if normalized.startswith('update index_jobs set status = ?'):
                self._claim_token = params[1]
                return _FakeResult()
            if 'select id, job_type, entity_id, source_path, payload_json from index_jobs' in normalized:
                if len(params) >= 2 and params[1] == getattr(self, '_claim_token', None):
                    return _FakeResult(rows=[])
                return _FakeResult(rows=[{'id': 1, 'job_type': 'rebuild_scope', 'entity_id': '', 'source_path': '', 'payload_json': '{}'}])
            if normalized.startswith('select count(*) from index_jobs where status = '):
                return _FakeResult(scalar=0)
            raise AssertionError(f'unexpected sql: {sql}')

        def commit(self):
            return None

    monkeypatch.setattr(index_job_worker, '_connect', lambda: _FakeConn())

    claimed_rows, pending = index_job_worker._claim_pending_jobs(50)

    assert claimed_rows == []
    assert pending == 0


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
    monkeypatch.setattr(index_job_worker, '_connect', lambda: _FakeConn())
    monkeypatch.setattr(
        index_job_worker,
        'classify_worldinfo_path',
        lambda source_path: {'kind': 'resource', 'source_path': source_path},
    )
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, _source_path: calls.append(('global', _source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_owner_increment', lambda _conn, entity_id, source_path='': calls.append(('owner', entity_id, source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda source_path: ['cards/alpha.png', 'cards/zeta.png'] if 'hero-assets' in source_path else [], raising=False)

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('owner', 'cards/alpha.png', 'D:/data/resources/hero-assets/lorebooks/book.json'),
        ('owner', 'cards/zeta.png', 'D:/data/resources/hero-assets/lorebooks/book.json'),
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
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'wait', fake_wait)
    monkeypatch.setattr(index_job_worker.ctx.index_wakeup, 'clear', lambda: None)
    monkeypatch.setattr(index_job_worker, '_claim_pending_jobs', lambda _limit: (rows.pop(0), 0))
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', lambda **_kwargs: None)
    monkeypatch.setattr(index_job_worker, '_mark_job_status', lambda job_id, status, error_msg='': calls.append(('mark', job_id, status, error_msg)))
    monkeypatch.setattr(index_job_worker, '_connect', lambda: _FakeConn())
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, _source_path: calls.append(('global', _source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_owner_increment', lambda _conn, entity_id, source_path='': calls.append(('owner', entity_id, source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda source_path: ['cards/alpha.png'] if str(resource_file) == source_path else [], raising=False)
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
        ('owner', 'cards/alpha.png', str(resource_file)),
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
    monkeypatch.setattr(index_job_worker, '_connect', lambda: _FakeConn())
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
    monkeypatch.setattr(index_job_worker, '_connect', lambda: _FakeConn())
    monkeypatch.setattr(
        index_job_worker,
        'classify_worldinfo_path',
        lambda source_path: {'kind': 'resource', 'source_path': source_path},
    )
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_path_increment', lambda _conn, source_path: calls.append(('global', source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'apply_worldinfo_owner_increment', lambda _conn, entity_id, source_path='': calls.append(('owner', entity_id, source_path)) or True)
    monkeypatch.setattr(index_job_worker, 'resolve_resource_worldinfo_owner_card_ids', lambda _source_path: [], raising=False)

    with pytest.raises(_StopLoop):
        index_job_worker.worker_loop()

    assert calls == [
        ('mark', 1, 'failed', 'resource worldinfo path has no owner cards'),
    ]
