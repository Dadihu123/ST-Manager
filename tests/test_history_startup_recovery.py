"""旧历史转换遇到目录失权时，基础启动与恢复入口必须仍然可用。"""

import errno
import json
import os
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

import core
from core.data import db_session
from core.services import wi_entry_history_service as history


@pytest.fixture
def library(monkeypatch, tmp_path):
    world = tmp_path / 'worldinfo'
    resources = tmp_path / 'resources'
    cards = tmp_path / 'cards'
    cards.mkdir()
    books = [world / 'first.json', world / 'nested' / 'second.json',
             resources / 'pack' / 'lorebooks' / 'book.json']
    for book in books:
        book.parent.mkdir(parents=True, exist_ok=True)
        book.write_text('{}', encoding='utf-8')
    db = tmp_path / 'history.db'
    monkeypatch.setattr(history, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(history, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(history, 'load_config', lambda: {
        'world_info_dir': str(world), 'resources_dir': str(resources),
    })
    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(db_session, 'CARDS_FOLDER', str(cards))
    with sqlite3.connect(db) as conn:
        history.ensure_entry_history_schema(conn)
        for book, source in zip(books, ['global', 'global', 'resource']):
            legacy = history._legacy_path_scope(source, str(book).replace('\\', '/'))
            conn.execute('INSERT INTO wi_entry_history '
                         '(scope_key, entry_uid, snapshot_json, snapshot_hash, created_at) '
                         'VALUES (?, ?, ?, ?, ?)',
                         (legacy, 'entry', '{"content":"saved"}', 'hash', 1))
        conn.execute('INSERT INTO wi_entry_history '
                     '(scope_key, entry_uid, snapshot_json, snapshot_hash, created_at) '
                     'VALUES (?, ?, ?, ?, ?)',
                     ('orphan', 'entry', '{"content":"keep until complete"}', 'hash', 1))
    return db, cards, world, resources, books


def rows(db):
    with sqlite3.connect(db) as conn:
        return (conn.execute('SELECT * FROM wi_entry_history ORDER BY id').fetchall(),
                conn.execute('SELECT * FROM wi_history_roots').fetchall())


@pytest.mark.parametrize('blocked', ['world', 'resources'])
def test_upgrade_starts_services_during_permission_loss_then_retries_without_restart(
        library, monkeypatch, blocked):
    db, cards, world, resources, books = library
    denied = world / 'nested' if blocked == 'world' else resources / 'pack'
    before = rows(db)
    started = []
    statuses = []
    monkeypatch.setattr(core, 'cleanup_temp_files', lambda: None)
    monkeypatch.setattr(core, 'plan_startup_upgrade', lambda **kw: [])
    monkeypatch.setattr(core.ctx, 'cache', SimpleNamespace(reload_from_db=lambda: None))
    monkeypatch.setattr(core.ctx, 'set_status', lambda **kw: statuses.append(kw.get('status')))
    for name in ['start_background_scanner', 'start_index_job_worker', 'start_monitor_scheduler']:
        monkeypatch.setattr(core, name, lambda name=name: started.append(name))
    monkeypatch.setattr(core.plugin_jobs, 'start_plugin_job_worker', lambda: started.append('plugins'))
    monkeypatch.setattr('core.plugins.hooks.emit', lambda *a, **kw: None)
    original_scandir = os.scandir

    def scandir(path):
        if os.path.abspath(path) == str(denied):
            raise PermissionError(errno.EACCES, 'permission revoked', os.fspath(path))
        return original_scandir(path)

    with monkeypatch.context() as failure:
        failure.setattr(os, 'scandir', scandir)
        core.init_services()  # 真正执行数据库升级和历史转换，仅隔离常驻服务的线程启动。
        assert statuses[-1] == 'ready' and 'error' not in statuses
        assert started == ['start_background_scanner', 'start_index_job_worker',
                           'start_monitor_scheduler', 'plugins']
        assert rows(db) == before, '部分转换必须回滚，也不能把根记录标记为转换完成'
        with pytest.raises(PermissionError):
            history.purge_orphaned_entry_history(cards_root=cards, world_info_root=world,
                                                 resources_root=resources)
        assert rows(db) == before
        # 历史兼容读取与新增均不能因转换待重试而失效。
        assert history.list_entry_history_records('global', '', str(books[0]), 'entry')
        assert history.append_entry_history_records('global', '', str(books[0]), [
            {'entry_uid': 'new', 'snapshot': {'content': 'created while pending'}},
        ]) == 1

    # 权限恢复后的既有清理入口会重试转换，无须重新执行 init_services。
    assert history.purge_orphaned_entry_history(cards_root=cards, world_info_root=world,
                                                 resources_root=resources) == 1
    after, roots = rows(db)
    assert len(after) == 4 and len(roots) == 1
    for row, book, source in zip(after[:3], books, ['global', 'global', 'resource']):
        assert row[1] == history.build_scope_key(source, file_path=str(book))
        assert json.loads(row[3]) == {'content': 'saved'}
    assert history.list_entry_history_records('global', '', str(books[0]), 'new')


def test_schema_creation_has_no_filesystem_dependency(monkeypatch):
    def unavailable():
        pytest.fail('建表不能解析或遍历资源根')

    monkeypatch.setattr(history, '_history_roots', unavailable)
    with sqlite3.connect(':memory:') as conn:
        history.ensure_entry_history_schema(conn)
        assert conn.execute('SELECT * FROM wi_entry_history').fetchall() == []
        assert conn.execute('SELECT * FROM wi_history_roots').fetchall() == []


def test_inaccessible_external_root_aborts_history_cleanup(library, monkeypatch, tmp_path):
    db, cards, world, resources, _ = library
    external = tmp_path / 'external-history'
    external.mkdir()
    before = rows(db)
    original_walk = history.walk_directory_strict
    def walk(root):
        if os.path.abspath(root) == str(external):
            raise PermissionError(errno.EACCES, 'external permission revoked', str(external))
        yield from original_walk(root)
    monkeypatch.setattr(history, 'walk_directory_strict', walk)
    with pytest.raises(PermissionError):
        history.purge_orphaned_entry_history(cards_root=cards, world_info_root=world,
                                             resources_root=resources,
                                             external_resource_roots=[external])
    assert rows(db) == before


def test_pending_migration_blocks_orphan_cleanup_and_preserves_previous_roots(library, monkeypatch):
    db, cards, world, resources, _ = library
    previous = deepcopy(history._history_roots())
    previous['base'] += '-old'
    previous['world_info_dir'] += '-old'
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO wi_history_roots VALUES (1, ?)', (json.dumps(previous),))
    before = rows(db)
    original_walk = history.walk_directory_strict
    calls = []

    def walk(root):
        calls.append(os.fspath(root))
        # 三个资源根已经完成枚举，接下来历史转换再次访问时权限丢失。
        if len(calls) > 3 and os.fspath(root) == str(world):
            raise PermissionError(errno.EACCES, 'permission revoked', str(world))
        yield from original_walk(root)

    monkeypatch.setattr(history, 'walk_directory_strict', walk)
    assert history.purge_orphaned_entry_history(cards_root=cards, world_info_root=world,
                                                 resources_root=resources) == 0
    assert len(calls) == 4
    assert rows(db) == before


@pytest.mark.parametrize('fail', [False, True])
def test_database_initialization_always_closes_connection(library, monkeypatch, fail):
    connections = []
    original_connect = sqlite3.connect

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(db_session.sqlite3, 'connect', connect)
    if fail:
        def broken_schema(conn):
            raise sqlite3.OperationalError('schema failure')

        monkeypatch.setattr(db_session, 'ensure_index_runtime_schema', broken_schema)
        with pytest.raises(sqlite3.OperationalError, match='schema failure'):
            db_session.init_database()
    else:
        db_session.init_database()
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            conn.execute('SELECT 1')
