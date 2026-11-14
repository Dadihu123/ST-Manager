"""目录枚举不完整时保留元数据、收藏及三种来源的历史，恢复后可重试。"""

import errno
import os
import sqlite3
from copy import deepcopy

import pytest

from core.services import scan_service, wi_entry_history_service as history
from test_scan_performance_regression import _prepare_scan_env


@pytest.fixture
def scan_library(monkeypatch, tmp_path):
    db_path, cards, _ = _prepare_scan_env(monkeypatch, tmp_path, card_count=3,
                                        files=['first.png', 'second.png', 'nested/third.png'])
    world = tmp_path / 'worldinfo'
    resources = tmp_path / 'resources'
    book = world / 'nested' / 'book.json'
    resource = resources / 'pack' / 'lorebooks' / 'book.json'
    for path in (book, resource):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}', encoding='utf-8')
    cfg = {'world_info_dir': str(world), 'resources_dir': str(resources)}
    monkeypatch.setattr(history, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(history, 'load_config', lambda: cfg)
    # 用真实历史清理和 purge，避免替身掩盖数据丢失。
    monkeypatch.setattr(scan_service, 'purge_orphaned_entry_history', history.purge_orphaned_entry_history)
    monkeypatch.setattr(scan_service, 'purge_entry_history_scope', history.purge_entry_history_scope)
    for source_type, source_id, path in [('embedded', 'second.png', ''), ('global', '', str(book)),
                                         ('resource', '', str(resource)), ('embedded', 'orphan.png', '')]:
        assert history.append_entry_history_records(source_type, source_id, path, records=[{
            'entry_uid': 'entry', 'snapshot': {'content': 'precious history'},
        }]) == 1
    with sqlite3.connect(db_path) as conn:
        conn.execute('UPDATE card_metadata SET is_favorite = 1')
    # 第一张卡先写入事务，稍后的子目录失败必须回滚它的改动。
    (cards / 'first.png').write_bytes(b'changed contents' * 8)
    state = deepcopy(scan_service.ctx.index_state)
    monkeypatch.setattr(scan_service.ctx, 'index_state', state)
    return db_path, cards, world, resources


def snapshot(db_path):
    with sqlite3.connect(db_path) as conn:
        return (conn.execute('SELECT * FROM card_metadata ORDER BY id').fetchall(),
                conn.execute('SELECT * FROM wi_entry_history ORDER BY id').fetchall())


@pytest.mark.parametrize('blocked', ['cards', 'cards/nested', 'world/nested', 'resources/pack'])
def test_incomplete_scan_rolls_back_and_preserves_favorites_and_all_history(scan_library, monkeypatch, blocked):
    db_path, cards, world, resources = scan_library
    roots = {'cards': cards, 'world': world, 'resources': resources}
    key, _, child = blocked.partition('/')
    denied = os.path.abspath(roots[key] / child)
    original_scandir = os.scandir
    before = snapshot(db_path)
    jobs = []
    monkeypatch.setattr(scan_service, '_enqueue_card_reconcile_jobs', lambda *a, **k: jobs.append(a))

    def scandir(path):
        if os.path.abspath(path) == denied:
            raise PermissionError(errno.EACCES, 'permission revoked', os.fspath(path))
        return original_scandir(path)

    with monkeypatch.context() as failure:
        failure.setattr(os, 'scandir', scandir)
        with pytest.raises(PermissionError):
            scan_service._perform_scan_logic()
    assert snapshot(db_path) == before
    assert jobs == []
    assert len(list(cards.rglob('*.png'))) == 3
    assert not scan_service.ctx.index_state['scan_active']
    assert '目录不可访问' in scan_service.ctx.index_state['scan_error']
    from core.services import index_service
    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', str(db_path))
    status = index_service.get_index_status()
    assert status['state'] == 'error' and status['scope'] == 'scan'
    assert '目录不可访问' in status['message']
    with sqlite3.connect(db_path) as conn:
        assert not conn.execute("SELECT value FROM scan_runtime_state WHERE key='last_full_scan_at'").fetchone()

    scan_service._perform_scan_logic()
    after_cards, after_history = snapshot(db_path)
    assert len(after_cards) == 3
    assert all(row[-2] == 1 for row in after_cards)  # is_favorite
    assert len(after_history) == 3  # 恢复后才清理真正的孤儿。
    assert not scan_service.ctx.index_state['scan_error']


def test_complete_enumeration_still_removes_genuinely_deleted_card(scan_library):
    db_path, cards, _, _ = scan_library
    (cards / 'second.png').unlink()
    scan_service._perform_scan_logic()
    cards_rows, history_rows = snapshot(db_path)
    assert len(cards_rows) == 2
    assert {row[0] for row in cards_rows} == {'first.png', 'nested/third.png'}
    assert len(history_rows) == 2  # 仅保留世界书及资源目录的历史。


def test_atomic_scan_keeps_legacy_history_until_rename_is_migrated(scan_library):
    db_path, cards, _, _ = scan_library
    signature, _ = scan_service.get_file_hash_and_size(cards / 'second.png')
    with sqlite3.connect(db_path) as conn:
        conn.execute('UPDATE card_metadata SET file_hash=? WHERE id=?', (signature, 'second.png'))
    (cards / 'second.png').rename(cards / 'renamed.png')
    scan_service._perform_scan_logic()
    assert history.list_entry_history_records('embedded', 'renamed.png', '', 'entry')
    assert not history.list_entry_history_records('embedded', 'second.png', '', 'entry')
    with sqlite3.connect(db_path) as conn:
        assert conn.execute('SELECT is_favorite FROM card_metadata WHERE id=?', ('renamed.png',)).fetchone() == (1,)


def test_standalone_history_cleanup_does_not_delete_on_partial_resource_enumeration(scan_library, monkeypatch):
    db_path, cards, world, resources = scan_library
    before = snapshot(db_path)
    original_scandir = os.scandir

    def scandir(path):
        if os.path.abspath(path) == os.path.abspath(resources / 'pack'):
            raise PermissionError(errno.EACCES, 'denied', os.fspath(path))
        return original_scandir(path)

    monkeypatch.setattr(os, 'scandir', scandir)
    with pytest.raises(PermissionError):
        history.purge_orphaned_entry_history(cards_root=cards, world_info_root=world,
                                             resources_root=resources, db_path=db_path)
    assert snapshot(db_path) == before
