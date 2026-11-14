"""活动世界书增量遇到访问失败必须保留完整旧投影，恢复后可重新执行。"""

import builtins
import errno
import json
import os
import sqlite3

import pytest

from core.data.index_runtime_store import (
    SEARCH_CONTENT_FORMAT_VERSION, get_search_content_format_version,
)
from core.services import index_build_service as build, index_job_worker as worker
from core.services import index_upgrade_service as upgrade
from test_worldinfo_rebuild_access import indexed_library, query, snapshot


def full_snapshot(db):
    result = snapshot(db)
    with sqlite3.connect(db) as conn:
        for table in ('index_entity_tags_v2', 'index_search_full_v2'):
            if conn.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                result[table] = conn.execute(
                    f'SELECT * FROM {table} WHERE generation=1 ORDER BY entity_id'
                ).fetchall()
    return result


def assert_retained(db, before):
    assert full_snapshot(db) == before
    assert query(db)['total'] == 4
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT active_generation FROM index_build_state "
                            "WHERE scope='worldinfo'").fetchone() == (1,)
        assert get_search_content_format_version(conn, 'worldinfo') == SEARCH_CONTENT_FORMAT_VERSION - 1


def update_sources(card, global_book, resource_book):
    book = {'name': 'Alpha Updated', 'entries': {'0': {'content': 'updated searchable lore'}}}
    global_book.write_text(json.dumps(book), encoding='utf-8')
    resource_book.write_text(json.dumps(book), encoding='utf-8')
    card.write_text(json.dumps({'spec': 'chara_card_v2', 'data': {
        'name': 'Hero', 'character_book': book,
    }}), encoding='utf-8')


@pytest.mark.parametrize('denied', ['file_read', 'file_stat', 'category_child', 'io_error'])
def test_global_increment_rolls_back_even_when_caller_catches_access_error(
        indexed_library, monkeypatch, denied):
    db, world, _, card, global_book, _, resource_book = indexed_library
    before = full_snapshot(db)
    update_sources(card, global_book, resource_book)
    original_open, original_stat, original_scandir = builtins.open, os.stat, os.scandir

    def open_file(path, *args, **kwargs):
        if os.path.abspath(path) == str(global_book) and denied in ('file_read', 'io_error'):
            code = errno.EIO if denied == 'io_error' else errno.EACCES
            raise OSError(code, 'global read denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    def stat_file(path, *args, **kwargs):
        if os.path.abspath(path) == str(global_book) and denied == 'file_stat':
            raise PermissionError(errno.EACCES, 'global stat denied', os.fspath(path))
        return original_stat(path, *args, **kwargs)

    def scandir(path):
        if os.path.abspath(path) == str(world / 'nested') and denied == 'category_child':
            raise PermissionError(errno.EACCES, 'category denied', os.fspath(path))
        return original_scandir(path)

    with monkeypatch.context() as failure:
        failure.setattr(builtins, 'open', open_file)
        failure.setattr(os, 'stat', stat_file)
        failure.setattr(os, 'scandir', scandir)
        with build.connect_index_db(db) as conn:
            with pytest.raises(OSError):
                build.apply_worldinfo_path_increment(conn, str(global_book))
            # 调用方捕获异常后仍提交，不能提交本轮删掉或改写的投影。
            conn.commit()
        assert_retained(db, before)

    with build.connect_index_db(db) as conn:
        assert build.apply_worldinfo_path_increment(conn, str(global_book))
    assert query(db)['total'] == 4
    assert any(item['name'] == 'Alpha Updated' for item in query(db)['items'])


@pytest.mark.parametrize('denied', [
    'resource_root', 'resource_directory', 'resource_list', 'resource_file',
    'card_file', 'category_child',
])
def test_owner_increment_rolls_back_embedded_resources_and_stats_together(
        indexed_library, monkeypatch, denied):
    db, world, resources, card, global_book, _, resource_book = indexed_library
    before = full_snapshot(db)
    update_sources(card, global_book, resource_book)
    original_stat, original_listdir = os.stat, os.listdir
    original_open, original_scandir = builtins.open, os.scandir

    def stat_file(path, *args, **kwargs):
        target = resources if denied == 'resource_root' else resource_book.parent
        if denied in ('resource_root', 'resource_directory') and os.path.abspath(path) == str(target):
            raise PermissionError(errno.EACCES, 'resource stat denied', os.fspath(path))
        return original_stat(path, *args, **kwargs)

    def listdir(path):
        if denied == 'resource_list' and os.path.abspath(path) == str(resource_book.parent):
            raise PermissionError(errno.EACCES, 'resource list denied', os.fspath(path))
        return original_listdir(path)

    def open_file(path, *args, **kwargs):
        target = card if denied == 'card_file' else resource_book
        if denied in ('card_file', 'resource_file') and os.path.abspath(path) == str(target):
            raise PermissionError(errno.EACCES, 'source read denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    def scandir(path):
        if denied == 'category_child' and os.path.abspath(path) == str(world / 'nested'):
            raise PermissionError(errno.EACCES, 'category denied', os.fspath(path))
        return original_scandir(path)

    with monkeypatch.context() as failure:
        failure.setattr(os, 'stat', stat_file)
        failure.setattr(os, 'listdir', listdir)
        failure.setattr(builtins, 'open', open_file)
        failure.setattr(os, 'scandir', scandir)
        with build.connect_index_db(db) as conn:
            with pytest.raises(PermissionError):
                build.apply_worldinfo_owner_increment(
                    conn, 'hero.json', str(card), remove_owner_ids=['hero.json'],
                )
            conn.commit()
        assert_retained(db, before)

    with build.connect_index_db(db) as conn:
        assert build.apply_worldinfo_owner_increment(conn, 'hero.json', str(card))
    names = [item['name'] for item in query(db)['items']]
    assert len(names) == 4 and names.count('Alpha Updated') == 2


def test_embedded_update_can_defer_commit_to_caller(indexed_library):
    db, _, _, card, global_book, _, resource_book = indexed_library
    before = full_snapshot(db)
    update_sources(card, global_book, resource_book)
    with build.connect_index_db(db) as conn:
        assert build.apply_worldinfo_embedded_increment(conn, 'hero.json', str(card), commit=False)
        assert conn.in_transaction
        assert_retained(db, before)  # 独立连接尚不能看到新投影。
        conn.rollback()
    assert_retained(db, before)


def test_failed_embedded_increment_preserves_callers_prior_transaction(indexed_library, monkeypatch):
    db, _, _, card, _, _, _ = indexed_library
    before = full_snapshot(db)
    original_open = builtins.open

    def open_file(path, *args, **kwargs):
        if os.path.abspath(path) == str(card):
            raise PermissionError(errno.EACCES, 'card denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    with build.connect_index_db(db) as conn:
        conn.execute('UPDATE card_metadata SET char_name=? WHERE id=?', ('Updated Hero', 'hero.json'))
        with monkeypatch.context() as failure:
            failure.setattr(builtins, 'open', open_file)
            with pytest.raises(PermissionError):
                build.apply_worldinfo_embedded_increment(conn, 'hero.json', str(card))
        assert conn.in_transaction
        conn.commit()
        assert conn.execute('SELECT char_name FROM card_metadata').fetchone()[0] == 'Updated Hero'
    assert_retained(db, before)


@pytest.mark.parametrize('source', ['global_deleted', 'global_invalid', 'resource_invalid'])
def test_actual_deletion_and_invalid_format_still_remove_only_affected_book(indexed_library, source):
    db, _, _, card, global_book, _, resource_book = indexed_library
    with build.connect_index_db(db) as conn:
        if source == 'global_deleted':
            global_book.unlink()
        elif source == 'global_invalid':
            global_book.write_bytes(b'\xff')
        else:
            resource_book.write_text('{invalid', encoding='utf-8')
        if source.startswith('global'):
            assert build.apply_worldinfo_path_increment(conn, str(global_book))
        else:
            assert build.apply_worldinfo_owner_increment(conn, 'hero.json', str(card))
    assert query(db)['total'] == 3


class StopWorker(BaseException):
    pass


def drain_jobs(monkeypatch):
    calls = []

    def wait(_timeout):
        if calls:
            raise StopWorker()
        calls.append(True)
        return True

    with monkeypatch.context() as control:
        control.setattr(worker.ctx.index_wakeup, 'wait', wait)
        with pytest.raises(StopWorker):
            worker.worker_loop()


def test_failed_rebuild_then_backlogged_increments_preserve_old_index_and_retry(
        indexed_library, monkeypatch):
    db, world, _, card, global_book, _, resource_book = indexed_library
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(db))
    before = full_snapshot(db)
    update_sources(card, global_book, resource_book)
    jobs = [('upsert_worldinfo_path', '', global_book),
            ('upsert_world_owner', 'hero.json', card),
            ('upsert_worldinfo_path', '', resource_book)]
    for kind, entity, path in jobs:
        worker.enqueue_index_job(kind, entity, str(path))
    plan = upgrade.plan_startup_upgrade()
    original_scandir, original_open = os.scandir, builtins.open

    def scandir(path):
        if os.path.abspath(path) == str(world):
            raise PermissionError(errno.EACCES, 'world root denied', os.fspath(path))
        return original_scandir(path)

    def open_file(path, *args, **kwargs):
        if os.path.abspath(path) in (str(global_book), str(resource_book)):
            raise PermissionError(errno.EACCES, 'world file denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(os, 'scandir', scandir)
        failure.setattr(builtins, 'open', open_file)
        upgrade.ctx.index_upgrade_active = True
        upgrade._background_upgrade_worker(plan)
        assert not upgrade.ctx.index_upgrade_active
        assert upgrade.ctx.index_upgrade_done.is_set()
        drain_jobs(monkeypatch)
        assert_retained(db, before)
        with sqlite3.connect(db) as conn:
            states = conn.execute('SELECT status, error_msg FROM index_jobs ORDER BY id').fetchall()
            assert len(states) == 3 and all(status == 'failed' and error for status, error in states)

    for kind, entity, path in jobs:
        worker.enqueue_index_job(kind, entity, str(path))
    drain_jobs(monkeypatch)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status='done'").fetchone() == (3,)
        assert conn.execute("SELECT active_generation FROM index_build_state "
                            "WHERE scope='worldinfo'").fetchone() == (1,)
    names = [item['name'] for item in query(db)['items']]
    assert len(names) == 4 and names.count('Alpha Updated') == 3


def test_shared_resource_job_rolls_back_all_owners_on_later_failure(indexed_library, monkeypatch):
    db, _, _, card, global_book, _, resource_book = indexed_library
    other = card.with_name('other.json')
    other.write_bytes(card.read_bytes())
    monkeypatch.setattr(build, 'load_ui_data', lambda: {
        'hero.json': {'resource_folder': 'pack'}, 'other.json': {'resource_folder': 'pack'},
    })
    with build.connect_index_db(db) as conn:
        conn.execute('INSERT INTO card_metadata '
                     '(id, char_name, has_character_book, character_book_name) '
                     'SELECT ?, char_name, has_character_book, character_book_name '
                     'FROM card_metadata WHERE id=?', ('other.json', 'hero.json'))
        build.apply_worldinfo_owner_increment(conn, 'other.json', str(other))
    before = full_snapshot(db)
    assert query(db)['total'] == 6
    update_sources(card, global_book, resource_book)
    original_open = builtins.open

    def open_file(path, *args, **kwargs):
        if os.path.abspath(path) == str(other):
            raise PermissionError(errno.EACCES, 'later owner denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(builtins, 'open', open_file)
        with build.connect_index_db(db) as conn:
            with pytest.raises(PermissionError):
                worker._retry_resource_worldinfo_job(conn, str(resource_book))
            conn.commit()
        assert full_snapshot(db) == before
        assert query(db)['total'] == 6
    with build.connect_index_db(db) as conn:
        assert worker._retry_resource_worldinfo_job(conn, str(resource_book))
    assert query(db)['total'] == 6
