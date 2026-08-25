"""角色卡来源更新监控池的 SQLite 表结构。"""

import time


DEFAULT_MONITOR_POOL_ID = 'default'
DEFAULT_MONITOR_POOL_NAME = '角色卡监控池'


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
