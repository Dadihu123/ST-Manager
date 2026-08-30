"""角色卡来源更新监控池的服务和 API 契约测试。"""

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import cards as cards_api
from core.context import ctx
from core.data.source_update_monitor_store import (
    ensure_source_update_monitor_schema,
    rename_source_update_monitor_card_reference,
)
from core.services import source_update_monitor_service as monitor


SOURCE_URL = 'https://discord.com/channels/1/2/threads/3'


@pytest.fixture()
def monitor_env(tmp_path, monkeypatch):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    (cards_root / 'demo.png').write_bytes(b'card')
    db_path = tmp_path / 'monitor.db'
    ui_data = {
        'demo.png': {
            'link': SOURCE_URL,
            '_source_update_v1': {
                'source_url': SOURCE_URL,
                'source_title': '标题',
                'baseline_established': True,
                'pending_update': True,
                'pending_status': 'updated',
                'pending_since': 100.0,
            },
        }
    }
    cache = SimpleNamespace(
        id_map={'demo.png': {'id': 'demo.png', 'char_name': '测试角色', 'last_modified': 100.0}},
        bundle_map={},
    )
    monkeypatch.setattr(monitor, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(monitor, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(monitor, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(ctx, 'cache', cache)
    monitor._active_pool_ids.clear()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, card_uid TEXT)'
        )
        ensure_source_update_monitor_schema(conn)
        conn.execute(
            'INSERT INTO card_metadata (id, char_name) VALUES (?, ?)',
            ('demo.png', '测试角色'),
        )
        conn.commit()
    return ui_data, db_path


def test_valid_card_can_be_added_and_duplicate_is_idempotent(monitor_env):
    first = monitor.add_monitor_entries(['demo.png'])
    repeated = monitor.add_monitor_entries(['demo.png'])

    assert first['results'][0]['status'] == 'added'
    assert repeated['results'][0]['status'] == 'already_in_pool'
    assert monitor.get_monitor_target_ids() == ['demo.png']


def test_monitor_member_persists_card_uuid(monitor_env):
    ui_data, db_path = monitor_env
    stable_uid = '33333333-3333-4333-8333-333333333333'
    ui_data['demo.png']['card_uid'] = stable_uid
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'UPDATE card_metadata SET card_uid = ? WHERE id = ?',
            ('55555555-5555-4555-8555-555555555555', 'demo.png'),
        )
        conn.commit()

    result = monitor.add_monitor_entries(['demo.png'])

    assert result['results'][0]['status'] == 'added'
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT card_id, card_uid FROM source_update_monitor_entries'
        ).fetchone()
    assert row == ('demo.png', stable_uid)


def test_monitor_member_path_move_keeps_card_uuid(monitor_env):
    _, db_path = monitor_env
    stable_uid = '44444444-4444-4444-8444-444444444444'
    monitor.add_monitor_entries(['demo.png'])

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'UPDATE source_update_monitor_entries SET card_uid = ?',
            (stable_uid,),
        )
        changed = rename_source_update_monitor_card_reference(
            conn,
            'demo.png',
            'renamed/demo.png',
            stable_uid,
        )
        conn.commit()
        row = conn.execute(
            'SELECT card_id, card_uid FROM source_update_monitor_entries'
        ).fetchone()

    assert changed is True
    assert row == ('renamed/demo.png', stable_uid)


def test_invalid_source_cannot_be_added_and_returns_reason(monitor_env, monkeypatch):
    ui_data, _ = monitor_env
    ui_data['demo.png']['link'] = 'https://example.test/card/3'

    result = monitor.add_monitor_entries(['demo.png'])

    assert result['results'][0]['status'] == 'invalid_source'
    assert 'Discord' in result['results'][0]['reason']
    assert monitor.get_monitor_target_ids() == []


def test_remove_only_deletes_membership_and_preserves_source_state(monitor_env):
    monitor.add_monitor_entries(['demo.png'])
    before = json.loads(json.dumps(monitor_env[0]['demo.png']['_source_update_v1']))

    result = monitor.remove_monitor_entries(['demo.png'])

    assert result['results'][0]['status'] == 'removed'
    assert monitor.get_monitor_target_ids() == []
    assert monitor_env[0]['demo.png']['_source_update_v1'] == before


def test_deleted_card_remains_as_missing_monitor_entry(monitor_env):
    _, db_path = monitor_env
    monitor.add_monitor_entries(['demo.png'])
    Path(monitor._card_path('demo.png')).unlink()

    entries = monitor.list_monitor_entries()

    assert entries[0]['last_run_status'] == 'missing'
    assert entries[0]['invalid_reason']
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT card_id, last_run_status FROM source_update_monitor_entries'
        ).fetchone()
    assert row == ('demo.png', 'missing')


def test_monitor_target_scope_freezes_ids(monitor_env):
    monitor.add_monitor_entries(['demo.png'])
    frozen = monitor.get_monitor_target_ids()
    monitor.remove_monitor_entries(['demo.png'])

    assert frozen == ['demo.png']
    assert monitor.get_monitor_target_ids() == []


def test_invalid_current_url_skips_network_and_preserves_pending(monitor_env, monkeypatch):
    ui_data, _ = monitor_env
    monitor.add_monitor_entries(['demo.png'])
    ui_data['demo.png']['link'] = ''
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('invalid monitor source must not call source checker')

    monkeypatch.setattr(monitor, 'check_card_source_update', fail_if_called)
    result = monitor.check_monitored_card('demo.png')

    assert result['status'] == 'invalid_source'
    assert result['source_update']['pending_update'] is True
    assert calls == []
    entry = monitor.list_monitor_entries()[0]
    assert entry['invalid_reason']


def test_pending_card_is_checked_again_and_remains_pending(monitor_env, monkeypatch):
    monitor.add_monitor_entries(['demo.png'])
    calls = []

    def fake_check(card_id, **kwargs):
        calls.append(card_id)
        return {
            'success': True,
            'supported': True,
            'status': 'unchanged',
            'changed': False,
            'card_id': card_id,
            'source_update': {
                'pending_update': True,
                'source_title': '标题',
            },
            'message': '来源暂无后续变化，仍有待处理更新',
        }

    monkeypatch.setattr(monitor, 'check_card_source_update', fake_check)
    result = monitor.check_monitored_card('demo.png')

    assert calls == ['demo.png']
    assert result['source_update']['pending_update'] is True
    assert monitor.get_monitor_status()['pending_count'] == 1


def test_busy_card_is_skipped_without_waiting_for_the_lock(monitor_env):
    monitor.add_monitor_entries(['demo.png'])
    lock = ctx.get_card_lock('demo.png')
    lock.acquire()
    try:
        result = monitor.check_monitored_card('demo.png')
    finally:
        lock.release()

    assert result['status'] == 'card_busy'
    assert monitor.list_monitor_entries()[0]['last_run_status'] == 'card_busy'


def test_scheduler_start_is_idempotent_and_thread_is_daemon(monkeypatch):
    created = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.daemon = kwargs.get('daemon')
            created.append(self)

        def is_alive(self):
            return True

        def start(self):
            return None

    monkeypatch.setattr(monitor.threading, 'Thread', FakeThread)
    monkeypatch.setattr(monitor, '_scheduler_thread', None)
    monitor.stop_monitor_scheduler()
    monitor._scheduler_stop.clear()

    first = monitor.start_monitor_scheduler()
    second = monitor.start_monitor_scheduler()

    assert first is second
    assert len(created) == 1
    assert first.daemon is True
    monitor.stop_monitor_scheduler()
    monitor._scheduler_thread = None
    monitor._scheduler_stop.clear()


def test_scheduler_survives_worker_exception(monkeypatch):
    calls = []

    def fail_once():
        calls.append(True)
        monitor._scheduler_stop.set()
        raise RuntimeError('scheduler test failure')

    monkeypatch.setattr(monitor, '_run_due_scheduled_pools', fail_once)
    monitor._scheduler_stop.clear()
    monitor._scheduler_loop()

    assert calls == [True]


def test_monitor_run_rejects_duplicate_and_can_complete(monitor_env):
    monitor.add_monitor_entries(['demo.png'])
    first = monitor.create_monitor_run(card_ids=['demo.png'])
    duplicate = monitor.create_monitor_run(card_ids=['demo.png'])

    assert first['success'] is True
    assert first['card_ids'] == ['demo.png']
    assert duplicate['success'] is False
    assert duplicate['status'] == 'already_running'

    completed = monitor.complete_monitor_run(first['run']['run_id'])
    assert completed['status'] == 'completed'
    assert monitor.get_monitor_status()['current_run'] is None


def test_old_running_run_is_aborted_by_schema_recovery(monitor_env):
    _, db_path = monitor_env
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            INSERT INTO source_update_monitor_runs
                (run_id, pool_id, trigger, status, started_at, total, summary_json)
            VALUES ('old-run', 'default', 'scheduled', 'running', 1, 1, '{}')
            ''',
        )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        ensure_source_update_monitor_schema(conn)
        row = conn.execute(
            'SELECT status, error FROM source_update_monitor_runs WHERE run_id = ?',
            ('old-run',),
        ).fetchone()

    assert row[0] == 'aborted'
    assert '重启' in row[1]


def test_monitor_scope_api_returns_frozen_pool_ids(monkeypatch):
    monkeypatch.setattr(cards_api, 'get_monitor_target_ids', lambda: ['demo.png', 'other.png'])
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)

    response = app.test_client().post(
        '/api/cards/source_update/targets',
        json={'scope': 'monitor_pool'},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 2,
        'card_ids': ['demo.png', 'other.png'],
    }
