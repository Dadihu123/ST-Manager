"""角色卡来源更新监控池的 SQLite 表结构。"""

import sqlite3
import time

from core.utils.card_identity import normalize_card_uid


DEFAULT_MONITOR_POOL_ID = 'default'
DEFAULT_MONITOR_POOL_NAME = '角色卡监控池'


def _normalize_card_reference(value):
    return str(value or '').strip().replace('\\', '/').strip('/')


def rename_source_update_monitor_card_reference(conn, old_card_id, new_card_id, card_uid=None):
    """迁移角色卡路径时同步监控成员，保留路径兼容字段和稳定 UUID。"""
    if not isinstance(conn, sqlite3.Connection):
        return False

    old_id = _normalize_card_reference(old_card_id)
    new_id = _normalize_card_reference(new_card_id)
    if not old_id or not new_id or old_id == new_id:
        return False

    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_update_monitor_entries'"
    ).fetchone()
    if table_exists is None:
        return False

    columns = {
        row[1] for row in conn.execute(
            'PRAGMA table_info(source_update_monitor_entries)'
        ).fetchall()
    }
    has_card_uid = 'card_uid' in columns
    normalized_uid = normalize_card_uid(card_uid)
    if not normalized_uid and has_card_uid:
        metadata_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'card_metadata'"
        ).fetchone()
        if metadata_exists is not None:
            metadata_columns = {
                row[1] for row in conn.execute('PRAGMA table_info(card_metadata)').fetchall()
            }
            if 'card_uid' in metadata_columns:
                row = conn.execute(
                    'SELECT card_uid FROM card_metadata WHERE id = ?',
                    (new_id,),
                ).fetchone()
                normalized_uid = normalize_card_uid(row[0]) if row is not None else ''

    rows = conn.execute(
        'SELECT pool_id FROM source_update_monitor_entries WHERE card_id = ?',
        (old_id,),
    ).fetchall()
    if not rows:
        return False

    changed = False
    for row in rows:
        pool_id = row[0]
        target_query = (
            '''
            SELECT card_uid FROM source_update_monitor_entries
            WHERE pool_id = ? AND card_id = ?
            '''
            if has_card_uid
            else '''
            SELECT 1 FROM source_update_monitor_entries
            WHERE pool_id = ? AND card_id = ?
            '''
        )
        target = conn.execute(target_query, (pool_id, new_id)).fetchone()
        if target is not None:
            if has_card_uid and normalized_uid and not normalize_card_uid(target[0]):
                conn.execute(
                    '''
                    UPDATE source_update_monitor_entries SET card_uid = ?
                    WHERE pool_id = ? AND card_id = ?
                    ''',
                    (normalized_uid, pool_id, new_id),
                )
            conn.execute(
                'DELETE FROM source_update_monitor_entries WHERE pool_id = ? AND card_id = ?',
                (pool_id, old_id),
            )
            changed = True
            continue

        if has_card_uid:
            conn.execute(
                '''
                UPDATE source_update_monitor_entries
                SET card_id = ?, card_uid = COALESCE(NULLIF(card_uid, ''), ?)
                WHERE pool_id = ? AND card_id = ?
                ''',
                (new_id, normalized_uid or None, pool_id, old_id),
            )
        else:
            conn.execute(
                '''
                UPDATE source_update_monitor_entries SET card_id = ?
                WHERE pool_id = ? AND card_id = ?
                ''',
                (new_id, pool_id, old_id),
            )
        changed = True

    return changed


def _ensure_columns(conn, table_name, columns):
    existing = {
        row[1]
        for row in conn.execute(f'PRAGMA table_info({table_name})').fetchall()
    }
    for column_name, column_definition in columns.items():
        if column_name in existing:
            continue
        conn.execute(
            f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}'
        )


def ensure_source_update_monitor_schema(conn, *, recover_stale=True):
    """幂等创建监控池表，并按需恢复上次进程遗留的运行任务状态。"""
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_update_monitor_pools (
            pool_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            schedule_mode TEXT NOT NULL DEFAULT 'manual',
            daily_time TEXT,
            timezone TEXT,
            next_run_at REAL,
            last_run_at REAL,
            last_run_id TEXT,
            created_at REAL,
            updated_at REAL
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_update_monitor_entries (
            pool_id TEXT NOT NULL,
            card_id TEXT NOT NULL,
            card_uid TEXT,
            source_url_snapshot TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at REAL,
            last_seen_source_url TEXT,
            last_run_status TEXT,
            last_run_at REAL,
            last_error TEXT,
            invalid_reason TEXT,
            PRIMARY KEY (pool_id, card_id)
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_update_monitor_runs (
            run_id TEXT PRIMARY KEY,
            pool_id TEXT NOT NULL,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at REAL,
            finished_at REAL,
            total INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            current_card_id TEXT,
            summary_json TEXT,
            error TEXT
        )
        '''
    )

    # 兼容开发版本中可能已经创建但字段不完整的表。
    _ensure_columns(
        conn,
        'source_update_monitor_pools',
        {
            'name': "TEXT NOT NULL DEFAULT '角色卡监控池'",
            'enabled': 'INTEGER NOT NULL DEFAULT 0',
            'schedule_mode': "TEXT NOT NULL DEFAULT 'manual'",
            'daily_time': 'TEXT',
            'timezone': 'TEXT',
            'next_run_at': 'REAL',
            'last_run_at': 'REAL',
            'last_run_id': 'TEXT',
            'created_at': 'REAL',
            'updated_at': 'REAL',
        },
    )
    _ensure_columns(
        conn,
        'source_update_monitor_entries',
        {
            'card_uid': 'TEXT',
            'source_url_snapshot': 'TEXT',
            'enabled': 'INTEGER NOT NULL DEFAULT 1',
            'added_at': 'REAL',
            'last_seen_source_url': 'TEXT',
            'last_run_status': 'TEXT',
            'last_run_at': 'REAL',
            'last_error': 'TEXT',
            'invalid_reason': 'TEXT',
        },
    )
    _ensure_columns(
        conn,
        'source_update_monitor_runs',
        {
            'pool_id': "TEXT NOT NULL DEFAULT 'default'",
            'trigger': "TEXT NOT NULL DEFAULT 'manual'",
            'status': "TEXT NOT NULL DEFAULT 'queued'",
            'started_at': 'REAL',
            'finished_at': 'REAL',
            'total': 'INTEGER NOT NULL DEFAULT 0',
            'completed': 'INTEGER NOT NULL DEFAULT 0',
            'current_card_id': 'TEXT',
            'summary_json': "TEXT NOT NULL DEFAULT '{}'",
            'error': 'TEXT',
        },
    )

    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_source_update_monitor_entries_pool '
        'ON source_update_monitor_entries(pool_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_source_update_monitor_entries_card '
        'ON source_update_monitor_entries(card_id)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_source_update_monitor_entries_card_uid '
        'ON source_update_monitor_entries(card_uid)'
    )

    # 监控成员原本只保存路径；为已有记录补挂当前角色卡的稳定 UUID。
    card_metadata_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'card_metadata'"
    ).fetchone()
    if card_metadata_exists:
        card_columns = {
            row[1] for row in conn.execute('PRAGMA table_info(card_metadata)').fetchall()
        }
        if 'card_uid' in card_columns:
            conn.execute(
                '''
                UPDATE source_update_monitor_entries
                SET card_uid = (
                    SELECT card_metadata.card_uid
                    FROM card_metadata
                    WHERE card_metadata.id = source_update_monitor_entries.card_id
                )
                WHERE (card_uid IS NULL OR card_uid = '')
                  AND EXISTS (
                    SELECT 1 FROM card_metadata
                    WHERE card_metadata.id = source_update_monitor_entries.card_id
                      AND card_metadata.card_uid IS NOT NULL
                      AND card_metadata.card_uid != ''
                  )
                '''
            )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_source_update_monitor_runs_pool_status '
        'ON source_update_monitor_runs(pool_id, status)'
    )

    now = time.time()
    conn.execute(
        '''
        INSERT INTO source_update_monitor_pools
            (pool_id, name, enabled, schedule_mode, daily_time, timezone, created_at, updated_at)
        VALUES (?, ?, 0, 'manual', NULL, NULL, ?, ?)
        ON CONFLICT(pool_id) DO UPDATE SET
            name = COALESCE(NULLIF(source_update_monitor_pools.name, ''), excluded.name),
            updated_at = COALESCE(source_update_monitor_pools.updated_at, excluded.updated_at)
        ''',
        (DEFAULT_MONITOR_POOL_ID, DEFAULT_MONITOR_POOL_NAME, now, now),
    )

    # running/queued 任务只属于旧进程；恢复后不能再次显示为已完成。
    if recover_stale:
        conn.execute(
            '''
            UPDATE source_update_monitor_runs
            SET status = 'aborted', finished_at = COALESCE(finished_at, ?),
                current_card_id = NULL,
                error = COALESCE(NULLIF(error, ''), '应用重启，任务未完成')
            WHERE status IN ('running', 'queued')
            ''',
            (now,),
        )
    conn.commit()
