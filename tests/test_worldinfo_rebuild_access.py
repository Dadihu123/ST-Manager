"""世界书重建访问失败不能替换仍可查询的活动 generation。"""

import builtins
import errno
import json
import os
import sqlite3
import threading

import pytest

from core.context import IndexState
from core.data.index_runtime_store import (
    SEARCH_CONTENT_FORMAT_VERSION, ensure_index_runtime_schema, get_search_content_format_version,
    set_search_content_format_version,
)
from core.services import index_build_service as build, index_upgrade_service as upgrade
from core.services import index_service
from core.services.worldinfo_index_query_service import query_worldinfo_index
from test_scan_performance_regression import _create_card_metadata_table


@pytest.fixture
def indexed_library(monkeypatch, tmp_path):
    db = tmp_path / 'index.db'
    cards = tmp_path / 'cards'
    world = tmp_path / 'world'
    resources = tmp_path / 'resources'
    card = cards / 'hero.json'
    global_book = world / 'main.json'
    child_book = world / 'nested' / 'child.json'
    resource_book = resources / 'pack' / 'lorebooks' / 'resource.json'
    book = {'name': 'Alpha', 'entries': {'0': {'content': 'precious searchable lore'}}}
    for path in (global_book, child_book, resource_book):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(book), encoding='utf-8')
    cards.mkdir()
    card.write_text(json.dumps({'spec': 'chara_card_v2', 'data': {
        'name': 'Hero', 'character_book': book,
    }}), encoding='utf-8')
    _create_card_metadata_table(db)
    with sqlite3.connect(db) as conn:
        ensure_index_runtime_schema(conn)
        conn.execute('ALTER TABLE card_metadata ADD COLUMN wi_metadata_scanned INTEGER DEFAULT 0')
        conn.execute('INSERT INTO card_metadata (id, char_name) VALUES (?, ?)', ('hero.json', 'Hero'))
    for module in (build, upgrade, index_service):
        monkeypatch.setattr(module, 'DEFAULT_DB_PATH', str(db))
        monkeypatch.setattr(module, 'CARDS_FOLDER', str(cards))
    monkeypatch.setattr(build, 'load_config', lambda: {
        'world_info_dir': str(world), 'resources_dir': str(resources),
    })
    monkeypatch.setattr(build, 'load_ui_data', lambda: {'hero.json': {'resource_folder': 'pack'}})
    monkeypatch.setattr(upgrade.ctx, 'index_state', IndexState())
    monkeypatch.setattr(upgrade.ctx, 'cache', None)
    monkeypatch.setattr(upgrade.ctx, 'index_wakeup', threading.Event())
    monkeypatch.setattr(upgrade.ctx, 'index_upgrade_done', threading.Event())
    monkeypatch.setattr(upgrade.ctx, 'index_upgrade_active', False)
    monkeypatch.setattr(upgrade.ctx, 'index_owner_token', 'rebuild-access-test')
    # 每条都真实提交，验证失败时连已经提交的半成品也不会泄漏。
    monkeypatch.setattr(build, 'BUILD_COMMIT_BATCH_SIZE', 1)
    upgrade.rebuild_scope_generation('worldinfo')
    assert query(db)['total'] == 4
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE index_build_state SET active_generation=1, state='ready' WHERE scope='cards'")
        set_search_content_format_version(conn, 'cards')
        set_search_content_format_version(conn, 'worldinfo', SEARCH_CONTENT_FORMAT_VERSION - 1)
    return db, world, resources, card, global_book, child_book, resource_book


def query(db):
    return query_worldinfo_index({'db_path': str(db), 'search': 'Alpha', 'search_mode': 'fast'})


def snapshot(db):
    with sqlite3.connect(db) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} WHERE generation=1 ORDER BY 1, 2').fetchall()
                for table in ['index_entities_v2', 'index_search_fast_v2',
                              'index_category_stats_v2', 'index_facet_stats_v2']}


@pytest.mark.parametrize('denied', [
    'global_root', 'global_child', 'global_file', 'global_io_error', 'resource_root',
    'resource_directory', 'resource_file', 'card_file', 'card_backfill', 'category_pass',
])
def test_permission_loss_keeps_old_index_format_and_retries_after_access_recovers(
        indexed_library, monkeypatch, denied):
    db, world, resources, card, global_book, child_book, resource_book = indexed_library
    before = snapshot(db)
    old_results = query(db)
    # 本轮待构建内容与旧索引不同，失败后必须仍查到旧内容。
    global_book.write_text('{"name":"Alpha Updated","entries":{}}', encoding='utf-8')
    if denied == 'card_backfill':
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE card_metadata SET wi_metadata_scanned=0')
    original_scandir, original_open = os.scandir, builtins.open
    original_listdir, original_stat = os.listdir, os.stat
    passes = []

    def scandir(path):
        path = os.path.abspath(path)
        if path == str(world):
            passes.append(path)
        if ((denied == 'global_root' and path == str(world)) or
            (denied == 'global_child' and path == str(world / 'nested')) or
            (denied == 'category_pass' and path == str(world) and len(passes) > 1)):
            raise PermissionError(errno.EACCES, 'directory denied', path)
        return original_scandir(path)

    def open_file(path, *args, **kwargs):
        target = {'global_file': global_book, 'global_io_error': child_book,
                  'resource_file': resource_book, 'card_file': card, 'card_backfill': card}.get(denied)
        if target and os.path.abspath(path) == str(target):
            if denied == 'global_io_error':
                raise OSError(errno.EIO, 'read failed', os.fspath(path))
            raise PermissionError(errno.EACCES, 'file denied', os.fspath(path))
        return original_open(path, *args, **kwargs)

    def listdir(path):
        if denied == 'resource_directory' and os.path.abspath(path) == str(resource_book.parent):
            raise PermissionError(errno.EACCES, 'resource directory denied', os.fspath(path))
        return original_listdir(path)

    def stat(path, *args, **kwargs):
        if denied == 'resource_root' and os.path.abspath(path) == str(resources):
            raise PermissionError(errno.EACCES, 'resource root denied', os.fspath(path))
        return original_stat(path, *args, **kwargs)

    plan = upgrade.plan_startup_upgrade()
    assert plan == [{'scope': 'worldinfo', 'reason': 'search_content_format_upgrade'}]
    with monkeypatch.context() as failure:
        failure.setattr(os, 'scandir', scandir)
        failure.setattr(builtins, 'open', open_file)
        failure.setattr(os, 'listdir', listdir)
        failure.setattr(os, 'stat', stat)
        upgrade.ctx.index_upgrade_active = True
        upgrade._background_upgrade_worker(plan)
        assert snapshot(db) == before
        assert query(db) == old_results
        assert upgrade.ctx.index_upgrade_active is False
        assert upgrade.ctx.index_upgrade_done.is_set()
        status = index_service.get_index_status()
        assert status['state'] == 'error' and status['worldinfo']['phase'] == 'resource_access'
        assert '重试' in status['message'] and '保留原索引' in status['message']
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT active_generation, building_generation, state, last_error "
                               "FROM index_build_state WHERE scope='worldinfo'").fetchone()
            assert row[:3] == (1, 0, 'failed') and '重试' in row[3]
            assert conn.execute('SELECT DISTINCT generation FROM index_entities_v2').fetchall() == [(1,)]
            assert get_search_content_format_version(conn, 'worldinfo') == SEARCH_CONTENT_FORMAT_VERSION - 1
            if denied == 'card_backfill':
                assert conn.execute('SELECT wi_metadata_scanned FROM card_metadata').fetchone() == (0,)

    assert global_book.is_file() and child_book.is_file() and resource_book.is_file() and card.is_file()
    # 即使模拟重启，失败索引仍在计划中，不会被错误记为已升级而永久跳过。
    monkeypatch.setattr(upgrade.ctx, 'index_owner_token', 'next-process')
    retry = upgrade.plan_startup_upgrade()
    assert [item['scope'] for item in retry] == ['worldinfo']
    upgrade._background_upgrade_worker(retry)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT active_generation, building_generation, state FROM index_build_state "
                            "WHERE scope='worldinfo'").fetchone() == (2, 0, 'ready')
        assert get_search_content_format_version(conn, 'worldinfo') == SEARCH_CONTENT_FORMAT_VERSION
        assert conn.execute('SELECT DISTINCT generation FROM index_entities_v2').fetchall() == [(2,)]
    results = query(db)
    assert results['total'] == 4 and any(item['name'] == 'Alpha Updated' for item in results['items'])
    assert upgrade.plan_startup_upgrade() == []


def test_invalid_json_format_can_be_skipped_without_masking_access_errors(indexed_library):
    db, world, _, _, _, _, resource_book = indexed_library
    (world / 'invalid.json').write_text('{broken', encoding='utf-8')
    (resource_book.parent / 'invalid.json').write_text('{broken', encoding='utf-8')
    (world / 'invalid-encoding.json').write_bytes(b'\xff\xfe\xfd')
    upgrade.rebuild_scope_generation('worldinfo')
    assert query(db)['total'] == 4
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT active_generation, state FROM index_build_state "
                            "WHERE scope='worldinfo'").fetchone() == (2, 'ready')


@pytest.mark.parametrize('legacy_wrapper', [False, True])
def test_synchronous_rebuild_also_reports_failure_and_keeps_old_generation(
        indexed_library, monkeypatch, legacy_wrapper):
    db, world, resources, card, _, _, _ = indexed_library
    original = builtins.open

    def open_file(path, *args, **kwargs):
        if os.path.abspath(path) == str(card):
            raise PermissionError(errno.EACCES, 'card denied', os.fspath(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', open_file)
    monkeypatch.setattr(index_service, 'load_config', lambda: {
        'world_info_dir': str(world), 'resources_dir': str(resources),
    })
    monkeypatch.setattr(index_service, 'load_ui_data', lambda: {'hero.json': {'resource_folder': 'pack'}})
    with pytest.raises(PermissionError):
        if legacy_wrapper:
            index_service.rebuild_worldinfo_index()
        else:
            upgrade.rebuild_scope_generation('worldinfo')
    assert query(db)['total'] == 4
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT active_generation, state FROM index_build_state "
                            "WHERE scope='worldinfo'").fetchone() == (1, 'failed')
