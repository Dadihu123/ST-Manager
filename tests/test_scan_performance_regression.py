"""针对启动扫描性能回归的测试。

背景：commit 9343dbe 把 ``extract_card_info`` 从 ``need_update`` 分支中提了出来，
导致每次启动都要完整读取并解码全部角色卡（大型库数千张卡 → 数分钟 CPU 与
数 GB 磁盘读）。这里用「解析调用次数」锁定修复后的行为。
"""

import json
import sqlite3

from core.services import scan_service


def _create_card_metadata_table(db_path):
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
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0,
                card_uid TEXT
            )
            '''
        )
        conn.commit()


def _prepare_scan_env(monkeypatch, tmp_path, *, card_count, files=None):
    """搭建一个「数据库中已有记录、磁盘文件未变更」的扫描场景。"""
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir(exist_ok=True)
    _create_card_metadata_table(db_path)

    file_specs = files or [f'card{i}.png' for i in range(card_count)]
    rows = []
    for name in file_specs:
        card_path = cards_dir / name
        card_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b'x' * 16
        card_path.write_bytes(payload)
        stat = card_path.stat()
        rows.append((name, 'Hero', '', stat.st_mtime, stat.st_size, 5, 0, 'uid-' + name))

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            '''
            INSERT INTO card_metadata
            (id, char_name, category, last_modified, file_size, token_count, is_favorite, card_uid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            rows,
        )
        conn.commit()

    parse_calls = []

    def _fake_extract(path):
        parse_calls.append(str(path))
        return {'data': {'name': 'Hero', 'tags': []}}, 'ok'

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(scan_service, 'extract_card_info_with_status', _fake_extract)
    monkeypatch.setattr(scan_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(scan_service, 'save_ui_data', lambda _payload, **_kwargs: True)
    monkeypatch.setattr(scan_service, 'calculate_token_count', lambda _payload: 1)
    monkeypatch.setattr(scan_service, 'get_wi_meta', lambda _payload: (False, ''))
    monkeypatch.setattr(scan_service, '_enqueue_card_reconcile_jobs', lambda *a, **k: None)
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: None)
    monkeypatch.setattr(scan_service, 'purge_entry_history_scope', lambda *a, **k: None)
    monkeypatch.setattr(scan_service, 'purge_orphaned_entry_history', lambda **k: None)
    monkeypatch.setattr(
        scan_service,
        'load_config',
        lambda: {
            'world_info_dir': str(tmp_path / 'worldinfo'),
            'resources_dir': str(tmp_path / 'resources'),
        },
    )

    return db_path, cards_dir, parse_calls


def test_unchanged_cards_are_never_parsed_during_full_scan(monkeypatch, tmp_path):
    """核心回归：未变更的文件只做 stat，不能读取/解析文件内容。"""
    _db_path, _cards_dir, parse_calls = _prepare_scan_env(
        monkeypatch, tmp_path, card_count=25
    )

    scan_service._perform_scan_logic()

    assert parse_calls == [], (
        '未变更卡片不应触发解析；实际解析了 %d 个文件' % len(parse_calls)
    )


def test_only_changed_cards_are_parsed_during_full_scan(monkeypatch, tmp_path):
    """只有真正变更的文件才解析，规模与变更数成正比而非库大小。"""
    db_path, cards_dir, parse_calls = _prepare_scan_env(
        monkeypatch, tmp_path, card_count=20
    )

    # 让其中一个文件看起来被修改过（写入更大内容使 size 变化）。
    target = cards_dir / 'card7.png'
    target.write_bytes(b'y' * 64)

    scan_service._perform_scan_logic()

    assert [p.replace('\\', '/').split('/')[-1] for p in parse_calls] == ['card7.png']

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT file_size FROM card_metadata WHERE id = ?', ('card7.png',)
        ).fetchone()
    assert row is not None and row[0] == 64


def test_unreadable_file_keeps_existing_database_row(monkeypatch, tmp_path):
    """读取失败（损坏/占用）不能被当成删除，否则会丢失收藏与元数据。"""
    db_path, cards_dir, _calls = _prepare_scan_env(
        monkeypatch, tmp_path, card_count=3
    )

    def _unreadable(path):
        return None, scan_service.CARD_INFO_UNREADABLE

    monkeypatch.setattr(scan_service, 'extract_card_info_with_status', _unreadable)

    # 让所有文件都视为已变更，从而进入解析分支。
    for name in ('card0.png', 'card1.png', 'card2.png'):
        (cards_dir / name).write_bytes(b'z' * 128)

    scan_service._perform_scan_logic()

    with sqlite3.connect(db_path) as conn:
        ids = [row[0] for row in conn.execute('SELECT id FROM card_metadata ORDER BY id')]
    assert ids == ['card0.png', 'card1.png', 'card2.png']


def test_non_card_file_is_purged_from_index(monkeypatch, tmp_path):
    """放错目录的世界书（可读但非卡片）应被清理，且不进入发现集合。"""
    db_path, cards_dir, _calls = _prepare_scan_env(
        monkeypatch, tmp_path, card_count=1
    )

    worldbook = cards_dir / 'worldbook.json'
    worldbook.write_text(json.dumps({'name': 'Book', 'entries': {}}), encoding='utf-8')

    with sqlite3.connect(db_path) as conn:
        stat = worldbook.stat()
        conn.execute(
            '''
            INSERT INTO card_metadata (id, char_name, category, last_modified, file_size, token_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            ('worldbook.json', 'Book', '', stat.st_mtime, stat.st_size, 0),
        )
        conn.commit()
        # 清空空字段，使其命中定向清理的筛选条件。
        conn.execute(
            "UPDATE card_metadata SET description='', first_mes='', mes_example='' WHERE id='worldbook.json'"
        )
        conn.commit()

    def _real_status(path):
        from core.utils.image import extract_card_info_with_status as real

        return real(path)

    monkeypatch.setattr(scan_service, 'extract_card_info_with_status', _real_status)

    scan_service._perform_scan_logic()

    with sqlite3.connect(db_path) as conn:
        ids = [row[0] for row in conn.execute('SELECT id FROM card_metadata ORDER BY id')]
    assert 'worldbook.json' not in ids


def test_startup_scan_skipped_within_interval(monkeypatch, tmp_path):
    """距上次校验不足阈值时应跳过启动全量扫描。"""
    db_path = tmp_path / 'cards_metadata.db'
    _create_card_metadata_table(db_path)

    import time

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'INSERT INTO card_metadata (id, char_name) VALUES (?, ?)', ('a.png', 'A')
        )
        conn.commit()

    from core.data.index_runtime_store import (
        SCAN_STATE_LAST_FULL_SCAN_AT,
        ensure_index_runtime_schema,
        set_scan_state,
    )

    with sqlite3.connect(db_path) as conn:
        ensure_index_runtime_schema(conn)
        set_scan_state(conn, SCAN_STATE_LAST_FULL_SCAN_AT, str(time.time()))

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        scan_service, 'current_config', {'enable_startup_scan': True, 'startup_scan_min_interval_hours': 24}
    )

    assert scan_service._should_run_startup_scan() is False


def test_startup_scan_runs_when_disabled_flag_is_off(monkeypatch, tmp_path):
    """显式关闭启动校验时不扫描。"""
    db_path = tmp_path / 'cards_metadata.db'
    _create_card_metadata_table(db_path)

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'current_config', {'enable_startup_scan': False})

    assert scan_service._should_run_startup_scan() is False


def test_startup_scan_runs_for_empty_database(monkeypatch, tmp_path):
    """空库（首次运行）仍需扫描以建立索引。"""
    db_path = tmp_path / 'cards_metadata.db'
    _create_card_metadata_table(db_path)

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        scan_service,
        'current_config',
        {'enable_startup_scan': True, 'startup_scan_min_interval_hours': 24},
    )

    assert scan_service._should_run_startup_scan() is True
