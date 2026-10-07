"""插件作业存储层（设计文档 6.1 / 6.5 / 6.6）。

主库新增 4 张表：
- `plugin_jobs` / `plugin_job_items` / `plugin_job_events`：作业状态机、条目与事件流
- `plugin_install_log`：安装/卸载/启停审计

约定：
- `plugin_jobs.claim_token` 是**独立列**（不复用 `error` 列），保证认领去重语义清晰。
- `plugin_job_events.seq` 是**作业内自增**（不是全表自增），SSE 的 `id:` 用它。
- `payload_json` / `result_json` 有大小上限，超限截断并标注 `_truncated`。
- 三张作业表共用同一保留决策，在 `prune_terminal_jobs()` 的事务里一并清理。
"""

import json
import logging
import sqlite3
import time
import uuid

from core.config import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

PLUGIN_JOB_DONE_RETENTION = 100
PLUGIN_JOB_FAILED_RETENTION = 50

MAX_ITEM_PAYLOAD_BYTES = 64 * 1024
MAX_ITEM_RESULT_BYTES = 256 * 1024

TERMINAL_STATUSES = ('completed', 'failed', 'cancelled', 'aborted')
FAILED_LIKE_STATUSES = ('failed', 'cancelled', 'aborted')
ACTIVE_STATUSES = ('queued', 'running', 'paused')

JOB_STATUSES = ('queued', 'running', 'paused', 'completed', 'failed', 'cancelled', 'aborted')
ITEM_STATUSES = ('pending', 'running', 'done', 'failed', 'skipped', 'awaiting_review')
EVENT_TYPES = ('snapshot', 'item', 'log', 'done')

_UPDATABLE_JOB_FIELDS = frozenset({
    'status', 'total', 'completed', 'failed', 'skipped',
    'current_item', 'message', 'summary_json', 'error',
    'started_at', 'finished_at', 'claim_token',
})

_SCHEMA_DDL = (
    '''
    CREATE TABLE IF NOT EXISTS plugin_jobs (
        run_id        TEXT PRIMARY KEY,
        plugin_id     TEXT NOT NULL,
        job_type      TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'queued',
        payload_json  TEXT NOT NULL DEFAULT '{}',
        total         INTEGER NOT NULL DEFAULT 0,
        completed     INTEGER NOT NULL DEFAULT 0,
        failed        INTEGER NOT NULL DEFAULT 0,
        skipped       INTEGER NOT NULL DEFAULT 0,
        current_item  TEXT DEFAULT '',
        message       TEXT DEFAULT '',
        summary_json  TEXT DEFAULT '{}',
        error         TEXT DEFAULT '',
        claim_token   TEXT DEFAULT '',
        created_at    REAL NOT NULL,
        started_at    REAL DEFAULT 0,
        finished_at   REAL DEFAULT 0
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_plugin_jobs_status ON plugin_jobs(status, created_at)',
    'CREATE INDEX IF NOT EXISTS idx_plugin_jobs_plugin ON plugin_jobs(plugin_id, created_at DESC)',
    '''
    CREATE TABLE IF NOT EXISTS plugin_job_items (
        run_id      TEXT NOT NULL,
        item_key    TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'pending',
        attempt     INTEGER NOT NULL DEFAULT 0,
        seq         INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT DEFAULT '{}',
        result_json TEXT DEFAULT '{}',
        error       TEXT DEFAULT '',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (run_id, item_key),
        CHECK (length(result_json) <= 262144)
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_plugin_job_items_status ON plugin_job_items(run_id, status, seq)',
    'CREATE INDEX IF NOT EXISTS idx_plugin_job_items_order ON plugin_job_items(run_id, seq)',
    '''
    CREATE TABLE IF NOT EXISTS plugin_job_events (
        run_id     TEXT NOT NULL,
        seq        INTEGER NOT NULL,
        type       TEXT NOT NULL,
        data_json  TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        PRIMARY KEY (run_id, seq)
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_plugin_job_events_run ON plugin_job_events(run_id, seq)',
    '''
    CREATE TABLE IF NOT EXISTS plugin_install_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        plugin_id   TEXT NOT NULL,
        action      TEXT NOT NULL,
        version     TEXT DEFAULT '',
        source      TEXT DEFAULT '',
        detail_json TEXT DEFAULT '{}',
        success     INTEGER NOT NULL DEFAULT 1,
        created_at  REAL NOT NULL
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_plugin_install_log ON plugin_install_log(plugin_id, created_at DESC)',
)


def ensure_plugin_jobs_schema(conn) -> None:
    """建表（幂等）；同时补齐早期版本缺失的 `claim_token` 列。"""
    cursor = conn.cursor()
    for statement in _SCHEMA_DDL:
        cursor.execute(statement)

    cursor.execute('PRAGMA table_info(plugin_jobs)')
    columns = {row[1] for row in cursor.fetchall()}
    if 'claim_token' not in columns:
        cursor.execute("ALTER TABLE plugin_jobs ADD COLUMN claim_token TEXT DEFAULT ''")


def connect(*, ensure_schema: bool = False) -> sqlite3.Connection:
    """worker / 后台线程自建连接（sqlite3 连接不能跨线程共享）。"""
    conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    if ensure_schema:
        ensure_plugin_jobs_schema(conn)
    return conn


def new_run_id() -> str:
    return uuid.uuid4().hex


def _dump_json(payload, *, limit: int = 0) -> str:
    try:
        text = json.dumps(payload if payload is not None else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        text = '{}'
    if limit and len(text.encode('utf-8')) > limit:
        try:
            trimmed = json.loads(text)
            if isinstance(trimmed, dict):
                trimmed = {key: value for key, value in trimmed.items() if key not in ('result', 'payload')}
                trimmed['_truncated'] = True
                text = json.dumps(trimmed, ensure_ascii=False)
            else:
                text = json.dumps({'_truncated': True}, ensure_ascii=False)
        except (TypeError, ValueError):
            text = json.dumps({'_truncated': True}, ensure_ascii=False)
    return text


def _load_json(text, fallback=None):
    try:
        value = json.loads(text or '')
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}
    return value


def normalize_items(items) -> list:
    """按 10.2 契约把 items 归一化为 `[{key, payload}]`（保持提交顺序、按 key 去重）。"""
    if not isinstance(items, (list, tuple)):
        raise ValueError('items 必须是数组')

    normalized = []
    index_by_key = {}
    for raw in items:
        if isinstance(raw, str):
            key = raw.strip()
            payload = {}
        elif isinstance(raw, dict):
            key = str(raw.get('key') or '').strip()
            payload = {k: v for k, v in raw.items() if k != 'key'}
        else:
            raise ValueError(f'不支持的 item 类型: {type(raw).__name__}')

        if not key:
            raise ValueError('item key 不能为空')

        if key in index_by_key:
            normalized[index_by_key[key]]['payload'] = payload
            continue
        index_by_key[key] = len(normalized)
        normalized.append({'key': key, 'payload': payload})

    return normalized


def create_job(conn, plugin_id: str, job_type: str, items, payload: dict | None = None) -> str:
    """创建作业并写入全部条目，返回 run_id。"""
    normalized_items = normalize_items(items)
    run_id = new_run_id()
    now = time.time()
    payload_json = _dump_json(payload or {})

    conn.execute(
        '''
        INSERT INTO plugin_jobs (run_id, plugin_id, job_type, status, payload_json, total, created_at)
        VALUES (?, ?, ?, 'queued', ?, ?, ?)
        ''',
        (run_id, str(plugin_id), str(job_type), payload_json, len(normalized_items), now),
    )

    rows = []
    for seq, item in enumerate(normalized_items):
        rows.append((
            run_id,
            item['key'],
            'pending',
            seq,
            _dump_json(item['payload'], limit=MAX_ITEM_PAYLOAD_BYTES),
            '{}',
            '',
            now + seq * 1e-6,
            now + seq * 1e-6,
        ))

    if rows:
        conn.executemany(
            '''
            INSERT INTO plugin_job_items
                (run_id, item_key, status, attempt, seq, payload_json, result_json, error, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            ''',
            rows,
        )

    conn.commit()
    return run_id


def _row_to_job(row) -> dict:
    if row is None:
        return {}
    keys = row.keys() if hasattr(row, 'keys') else []
    job = {key: row[key] for key in keys if key != 'claim_token'}
    job['payload'] = _load_json(job.pop('payload_json', '{}'))
    job['summary'] = _load_json(job.pop('summary_json', '{}'))
    return job


def get_job(conn, run_id: str) -> dict | None:
    row = conn.execute('SELECT * FROM plugin_jobs WHERE run_id = ?', (str(run_id),)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def list_jobs(conn, plugin_id: str | None = None, *, statuses=None, limit: int = 50, offset: int = 0) -> list:
    """按创建时间倒序列出作业。"""
    conditions = []
    params = []
    if plugin_id:
        conditions.append('plugin_id = ?')
        params.append(str(plugin_id))
    if statuses:
        placeholders = ','.join('?' for _ in statuses)
        conditions.append(f'status IN ({placeholders})')
        params.extend(statuses)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
    params.extend([max(1, int(limit)), max(0, int(offset))])
    rows = conn.execute(
        f'SELECT * FROM plugin_jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params,
    ).fetchall()
    return [_row_to_job(row) for row in rows]


def count_jobs(conn, plugin_id: str | None = None, *, statuses=None) -> int:
    conditions = []
    params = []
    if plugin_id:
        conditions.append('plugin_id = ?')
        params.append(str(plugin_id))
    if statuses:
        placeholders = ','.join('?' for _ in statuses)
        conditions.append(f'status IN ({placeholders})')
        params.extend(statuses)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
    row = conn.execute(f'SELECT COUNT(*) AS total FROM plugin_jobs {where}', params).fetchone()
    return int(row['total'] if row else 0)


def has_active_job(conn, plugin_id: str) -> bool:
    """同插件是否已有排队/运行/暂停中的作业（用于「同插件串行化」）。"""
    placeholders = ','.join('?' for _ in ACTIVE_STATUSES)
    row = conn.execute(
        f'SELECT COUNT(*) AS total FROM plugin_jobs WHERE plugin_id = ? AND status IN ({placeholders})',
        (str(plugin_id), *ACTIVE_STATUSES),
    ).fetchone()
    return bool(row and int(row['total']) > 0)


def _row_to_item(row) -> dict:
    item = {
        'run_id': row['run_id'],
        'key': row['item_key'],
        'status': row['status'],
        'attempt': int(row['attempt'] or 0),
        'seq': int(row['seq'] or 0),
        'payload': _load_json(row['payload_json'], {}),
        'result': _load_json(row['result_json'], {}),
        'error': row['error'] or '',
        'created_at': float(row['created_at'] or 0),
        'updated_at': float(row['updated_at'] or 0),
    }
    return item


def list_items(conn, run_id: str, *, statuses=None, limit: int = 200, offset: int = 0) -> list:
    """按 `seq`（提交顺序）列出条目。"""
    conditions = ['run_id = ?']
    params = [str(run_id)]
    if statuses:
        placeholders = ','.join('?' for _ in statuses)
        conditions.append(f'status IN ({placeholders})')
        params.extend(statuses)
    params.extend([max(1, int(limit)), max(0, int(offset))])
    rows = conn.execute(
        f'SELECT * FROM plugin_job_items WHERE {" AND ".join(conditions)} ORDER BY seq ASC LIMIT ? OFFSET ?',
        params,
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def count_items(conn, run_id: str, *, statuses=None) -> int:
    conditions = ['run_id = ?']
    params = [str(run_id)]
    if statuses:
        placeholders = ','.join('?' for _ in statuses)
        conditions.append(f'status IN ({placeholders})')
        params.extend(statuses)
    row = conn.execute(
        f'SELECT COUNT(*) AS total FROM plugin_job_items WHERE {" AND ".join(conditions)}',
        params,
    ).fetchone()
    return int(row['total'] if row else 0)


def get_item(conn, run_id: str, item_key: str) -> dict | None:
    row = conn.execute(
        'SELECT * FROM plugin_job_items WHERE run_id = ? AND item_key = ?',
        (str(run_id), str(item_key)),
    ).fetchone()
    if row is None:
        return None
    return _row_to_item(row)


def update_job(conn, run_id: str, **fields) -> bool:
    """更新作业字段（白名单列）。"""
    updates = {key: value for key, value in fields.items() if key in _UPDATABLE_JOB_FIELDS}
    if not updates:
        return False

    assignments = ', '.join(f'{key} = ?' for key in updates)
    params = list(updates.values()) + [str(run_id)]
    cursor = conn.execute(f'UPDATE plugin_jobs SET {assignments} WHERE run_id = ?', params)
    conn.commit()
    return cursor.rowcount > 0


def update_item(
    conn, run_id: str, item_key: str, *,
    status: str, result=None, error: str = '', bump_attempt: bool = False,
) -> bool:
    """更新条目状态与结果。"""
    result_json = _dump_json(result if result is not None else {}, limit=MAX_ITEM_RESULT_BYTES)
    attempt_sql = 'attempt + 1' if bump_attempt else 'attempt'
    cursor = conn.execute(
        f'''
        UPDATE plugin_job_items
        SET status = ?, result_json = ?, error = ?, attempt = {attempt_sql}, updated_at = ?
        WHERE run_id = ? AND item_key = ?
        ''',
        (str(status), result_json, str(error or ''), time.time(), str(run_id), str(item_key)),
    )
    conn.commit()
    return cursor.rowcount > 0


def reset_failed_items(conn, run_id: str) -> int:
    """把 `failed` 条目重置为 `pending`（配合 retry_job 使用）。"""
    cursor = conn.execute(
        '''
        UPDATE plugin_job_items
        SET status = 'pending', error = '', result_json = '{}', updated_at = ?
        WHERE run_id = ? AND status IN ('failed', 'awaiting_review')
        ''',
        (time.time(), str(run_id)),
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def claim_runnable_jobs(conn, *, limit: int = 4, max_per_plugin: int = 2) -> list:
    """认领可运行作业：`claim_token` 独立列 + 每插件并发上限。

    先按创建顺序挑候选（每插件最多 `max_per_plugin` 条），再用 `UPDATE ... WHERE
    status='queued'` 原子认领，最后按 token 取回本 worker 真正拿到的那几行。
    """
    limit = max(1, int(limit))
    max_per_plugin = max(1, int(max_per_plugin))

    candidates = conn.execute(
        "SELECT run_id, plugin_id FROM plugin_jobs WHERE status = 'queued' ORDER BY created_at LIMIT ?",
        (limit * 8,),
    ).fetchall()

    picked = []
    per_plugin = {}
    for row in candidates:
        plugin_id = row['plugin_id']
        if per_plugin.get(plugin_id, 0) >= max_per_plugin:
            continue
        per_plugin[plugin_id] = per_plugin.get(plugin_id, 0) + 1
        picked.append(row['run_id'])
        if len(picked) >= limit:
            break

    if not picked:
        return []

    claim_token = f'claim:{uuid.uuid4().hex}'
    placeholders = ','.join('?' for _ in picked)
    conn.execute(
        f'''
        UPDATE plugin_jobs
        SET status = 'running', claim_token = ?,
            started_at = COALESCE(NULLIF(started_at, 0), ?)
        WHERE run_id IN ({placeholders}) AND status = 'queued'
        ''',
        [claim_token, time.time(), *picked],
    )
    conn.commit()

    rows = conn.execute(
        f'SELECT * FROM plugin_jobs WHERE claim_token = ? ORDER BY created_at',
        (claim_token,),
    ).fetchall()
    return [_row_to_job(row) for row in rows]


def release_claim(conn, run_id: str) -> None:
    conn.execute("UPDATE plugin_jobs SET claim_token = '' WHERE run_id = ?", (str(run_id),))
    conn.commit()


def append_event(conn, run_id: str, event_type: str, data: dict | None = None) -> int:
    """追加一条作业事件，返回作业内自增的 `seq`。"""
    cursor = conn.execute(
        '''
        INSERT INTO plugin_job_events (run_id, seq, type, data_json, created_at)
        VALUES (?, COALESCE((SELECT MAX(seq) FROM plugin_job_events WHERE run_id = ?), 0) + 1, ?, ?, ?)
        RETURNING seq
        ''',
        (str(run_id), str(run_id), str(event_type), _dump_json(data or {}), time.time()),
    )
    row = cursor.fetchone()
    conn.commit()
    if row is None:
        return 0
    try:
        return int(row['seq'])
    except (TypeError, IndexError):
        return int(row[0])


def read_events(conn, run_id: str, *, after_seq: int = 0, limit: int = 500) -> list:
    """读取 `seq > after_seq` 的事件（升序）。"""
    rows = conn.execute(
        '''
        SELECT seq, type, data_json, created_at FROM plugin_job_events
        WHERE run_id = ? AND seq > ?
        ORDER BY seq ASC
        LIMIT ?
        ''',
        (str(run_id), int(after_seq), max(1, int(limit))),
    ).fetchall()
    return [
        {
            'seq': int(row['seq']),
            'type': row['type'],
            'data': _load_json(row['data_json'], {}),
            'created_at': float(row['created_at'] or 0),
        }
        for row in rows
    ]


def latest_event_seq(conn, run_id: str) -> int:
    row = conn.execute(
        'SELECT COALESCE(MAX(seq), 0) AS max_seq FROM plugin_job_events WHERE run_id = ?',
        (str(run_id),),
    ).fetchone()
    return int(row['max_seq'] if row else 0)


def abort_stale_jobs(conn) -> int:
    """崩溃恢复：启动时把 `running` / `queued` 作业标记为 `aborted`。"""
    cursor = conn.execute(
        '''
        UPDATE plugin_jobs
        SET status = 'aborted', finished_at = ?,
            error = CASE WHEN error = '' THEN '应用重启，作业已中断' ELSE error END
        WHERE status IN ('running', 'queued')
        ''',
        (time.time(),),
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def _kept_run_ids(conn, status: str, retention: int) -> set:
    keep_count = max(int(retention), 0)
    if keep_count == 0:
        return set()
    rows = conn.execute(
        '''
        SELECT run_id FROM plugin_jobs
        WHERE status = ?
        ORDER BY finished_at DESC, created_at DESC
        LIMIT ?
        ''',
        (status, keep_count),
    ).fetchall()
    return {row['run_id'] for row in rows}


def prune_terminal_jobs(conn) -> int:
    """按作业条数清理三张作业表（终态才清理，运行中的作业永不清理）。"""
    keep = _kept_run_ids(conn, 'completed', PLUGIN_JOB_DONE_RETENTION)
    for status in FAILED_LIKE_STATUSES:
        keep |= _kept_run_ids(conn, status, PLUGIN_JOB_FAILED_RETENTION)

    placeholders = ','.join('?' for _ in TERMINAL_STATUSES)
    rows = conn.execute(
        f'SELECT run_id FROM plugin_jobs WHERE status IN ({placeholders})',
        list(TERMINAL_STATUSES),
    ).fetchall()
    stale = [row['run_id'] for row in rows if row['run_id'] not in keep]
    if not stale:
        return 0

    deleted = 0
    for start in range(0, len(stale), 200):
        batch = stale[start:start + 200]
        marks = ','.join('?' for _ in batch)
        conn.execute(f'DELETE FROM plugin_job_events WHERE run_id IN ({marks})', batch)
        conn.execute(f'DELETE FROM plugin_job_items WHERE run_id IN ({marks})', batch)
        cursor = conn.execute(f'DELETE FROM plugin_jobs WHERE run_id IN ({marks})', batch)
        deleted += int(cursor.rowcount or 0)
    conn.commit()
    return deleted


def log_install_action(
    conn, plugin_id: str, action: str, *,
    version: str = '', source: str = '', detail=None, success: bool = True,
) -> None:
    """写入安装/卸载/启停审计记录（保留全部记录，不随作业清理）。"""
    conn.execute(
        '''
        INSERT INTO plugin_install_log (plugin_id, action, version, source, detail_json, success, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            str(plugin_id), str(action), str(version or ''), str(source or ''),
            _dump_json(detail or {}), 1 if success else 0, time.time(),
        ),
    )
    conn.commit()


def list_install_log(conn, plugin_id: str | None = None, *, limit: int = 50) -> list:
    if plugin_id:
        rows = conn.execute(
            'SELECT * FROM plugin_install_log WHERE plugin_id = ? ORDER BY created_at DESC LIMIT ?',
            (str(plugin_id), max(1, int(limit))),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM plugin_install_log ORDER BY created_at DESC LIMIT ?',
            (max(1, int(limit)),),
        ).fetchall()
    return [
        {
            'id': int(row['id']),
            'plugin_id': row['plugin_id'],
            'action': row['action'],
            'version': row['version'],
            'source': row['source'],
            'detail': _load_json(row['detail_json'], {}),
            'success': bool(row['success']),
            'created_at': float(row['created_at'] or 0),
        }
        for row in rows
    ]
