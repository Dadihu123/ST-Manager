import json
import logging
import sqlite3
import threading
import uuid

from core.config import DEFAULT_DB_PATH
from core.context import ctx
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.services.index_build_service import (
    apply_card_increment,
    classify_worldinfo_path,
    apply_worldinfo_embedded_increment,
    apply_worldinfo_owner_increment,
    apply_worldinfo_path_increment,
    resolve_resource_worldinfo_owner_card_ids,
)
from core.services.index_upgrade_service import rebuild_scope_generation


logger = logging.getLogger(__name__)

_worker_start_lock = threading.Lock()


DEDUPABLE_JOB_TYPES = {'rebuild_scope', 'upsert_card', 'upsert_worldinfo_path', 'upsert_world_embedded', 'upsert_world_owner'}
WORLDINFO_RECONCILE_JOB_TYPES = {'upsert_worldinfo_path', 'upsert_world_embedded', 'upsert_world_owner'}
INDEX_JOB_DONE_RETENTION = 200
INDEX_JOB_FAILED_RETENTION = 50


def _connect(*, ensure_schema: bool = False):
    conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    if ensure_schema:
        ensure_index_runtime_schema(conn)
    return conn


def enqueue_index_job(job_type: str, entity_id: str = '', source_path: str = '', payload: dict | None = None):
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    with _connect() as conn:
        if job_type in DEDUPABLE_JOB_TYPES:
            existing = conn.execute(
                '''
                SELECT id
                FROM index_jobs
                WHERE status = 'pending'
                  AND job_type = ?
                  AND entity_id = ?
                  AND source_path = ?
                  AND payload_json = ?
                ORDER BY id DESC
                LIMIT 1
                ''',
                (job_type, entity_id, source_path, payload_json),
            ).fetchone()
            if not existing:
                conn.execute(
                    'INSERT INTO index_jobs(job_type, entity_id, source_path, payload_json) VALUES (?, ?, ?, ?)',
                    (job_type, entity_id, source_path, payload_json),
                )
        else:
            conn.execute(
                'INSERT INTO index_jobs(job_type, entity_id, source_path, payload_json) VALUES (?, ?, ?, ?)',
                (job_type, entity_id, source_path, payload_json),
            )
        pending = conn.execute(
            "SELECT COUNT(*) FROM index_jobs WHERE status = 'pending'"
        ).fetchone()[0]
        conn.commit()
    _set_jobs_state(pending_jobs=int(pending))
    ctx.index_wakeup.set()


def _set_jobs_state(**updates):
    with ctx.index_lock:
        ctx.index_state['jobs'].update(updates)
        if 'pending_jobs' in updates:
            ctx.index_state['pending_jobs'] = updates['pending_jobs']


def _claim_pending_jobs(limit: int = 50):
    claim_token = f'claim:{uuid.uuid4().hex}'

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM index_jobs WHERE status = 'pending' ORDER BY id LIMIT ?",
            (int(limit),),
        ).fetchall()
        job_ids = [int(row['id']) for row in rows]
        if job_ids:
            placeholders = ','.join('?' for _ in job_ids)
            conn.execute(
                f"UPDATE index_jobs SET status = ?, started_at = COALESCE(NULLIF(started_at, 0), strftime('%s', 'now')), error_msg = ? WHERE id IN ({placeholders}) AND status = 'pending'",
                ['running', claim_token, *job_ids],
            )
            conn.commit()
            claimed_rows = conn.execute(
                f'SELECT id, job_type, entity_id, source_path, payload_json FROM index_jobs WHERE status = ? AND error_msg = ? AND id IN ({placeholders}) ORDER BY id',
                ['running', claim_token, *job_ids],
            ).fetchall()
        else:
            claimed_rows = []

        pending = conn.execute(
            "SELECT COUNT(*) FROM index_jobs WHERE status = 'pending'"
        ).fetchone()[0]

    return claimed_rows, int(pending)


def _mark_job_status(job_id: int, status: str, error_msg: str = ''):
    with _connect() as conn:
        conn.execute(
            'UPDATE index_jobs SET status = ?, started_at = COALESCE(NULLIF(started_at, 0), strftime(\'%s\', "now")), finished_at = strftime(\'%s\', "now"), error_msg = ? WHERE id = ?',
            (status, error_msg, int(job_id)),
        )
        _prune_terminal_jobs(conn)
        conn.commit()
        row = conn.execute(
            'SELECT job_type, entity_id FROM index_jobs WHERE id = ?',
            (int(job_id),),
        ).fetchone()

    # 通知插件：索引作业进入终态（成功/失败都会经过这里）
    try:
        from core.plugins import hooks

        hooks.emit('index.job_done', {
            'job_type': row['job_type'] if row else '',
            'entity_id': row['entity_id'] if row else '',
            'status': status,
        })
    except Exception:
        logger.debug('index.job_done hook 派发失败', exc_info=True)


def _prune_terminal_jobs(conn):
    _prune_jobs_by_status(conn, 'done', INDEX_JOB_DONE_RETENTION)
    _prune_jobs_by_status(conn, 'failed', INDEX_JOB_FAILED_RETENTION)


def _prune_jobs_by_status(conn, status: str, retention: int):
    keep_count = max(int(retention), 0)
    if keep_count == 0:
        conn.execute('DELETE FROM index_jobs WHERE status = ?', (status,))
        return

    conn.execute(
        '''
        DELETE FROM index_jobs
        WHERE status = ?
          AND id NOT IN (
              SELECT id FROM (
                  SELECT id
                  FROM index_jobs
                  WHERE status = ?
                  ORDER BY finished_at DESC, id DESC
                  LIMIT ?
              )
          )
        ''',
        (status, status, keep_count),
    )


def _retry_resource_worldinfo_job(conn, source_path: str) -> bool:
    owner_card_ids = resolve_resource_worldinfo_owner_card_ids(source_path)
    if not owner_card_ids:
        return False
    for owner_card_id in owner_card_ids:
        apply_worldinfo_owner_increment(conn, owner_card_id, source_path)
    return True


def worker_loop():
    while True:
        _set_jobs_state(worker_state='waiting')
        ctx.index_wakeup.wait(30)
        ctx.index_wakeup.clear()

        rows, pending = _claim_pending_jobs(50)
        _set_jobs_state(worker_state='processing' if rows else 'idle', pending_jobs=int(pending))

        processed_worldinfo_reconcile = False

        for row in rows:
            try:
                payload = json.loads(row['payload_json'] or '{}')
                if row['job_type'] == 'rebuild_scope':
                    rebuild_scope_generation(payload.get('scope') or 'cards', reason='manual_rebuild')
                elif row['job_type'] == 'upsert_card':
                    with _connect() as conn:
                        apply_card_increment(
                            conn,
                            row['entity_id'],
                            row['source_path'],
                            remove_entity_ids=payload.get('remove_entity_ids') or [],
                        )
                elif row['job_type'] == 'upsert_worldinfo_path':
                    classification = classify_worldinfo_path(row['source_path'])
                    try:
                        if classification.get('kind') == 'resource':
                            with _connect() as conn:
                                if _retry_resource_worldinfo_job(conn, row['source_path']):
                                    processed_worldinfo_reconcile = True
                                    _mark_job_status(row['id'], 'done', '')
                                    continue
                            raise RuntimeError('resource worldinfo path has no owner cards')
                        with _connect() as conn:
                            apply_worldinfo_path_increment(conn, row['source_path'])
                    except RuntimeError as exc:
                        if 'active generation missing' not in str(exc):
                            raise
                        if not processed_worldinfo_reconcile:
                            rebuild_scope_generation('worldinfo', reason='incremental_reconcile')
                            processed_worldinfo_reconcile = True
                    else:
                        processed_worldinfo_reconcile = True
                elif row['job_type'] == 'upsert_world_embedded':
                    try:
                        with _connect() as conn:
                            apply_worldinfo_embedded_increment(conn, row['entity_id'], row['source_path'])
                    except RuntimeError as exc:
                        if 'active generation missing' not in str(exc):
                            raise
                        if not processed_worldinfo_reconcile:
                            rebuild_scope_generation('worldinfo', reason='incremental_reconcile')
                            processed_worldinfo_reconcile = True
                    else:
                        processed_worldinfo_reconcile = True
                elif row['job_type'] == 'upsert_world_owner':
                    try:
                        with _connect() as conn:
                            apply_worldinfo_owner_increment(
                                conn,
                                row['entity_id'],
                                row['source_path'],
                                remove_owner_ids=payload.get('remove_owner_ids') or [],
                            )
                    except RuntimeError as exc:
                        if 'active generation missing' not in str(exc):
                            raise
                        if not processed_worldinfo_reconcile:
                            rebuild_scope_generation('worldinfo', reason='incremental_reconcile')
                            processed_worldinfo_reconcile = True
                    else:
                        processed_worldinfo_reconcile = True
                elif row['job_type'] in WORLDINFO_RECONCILE_JOB_TYPES:
                    if not processed_worldinfo_reconcile:
                        rebuild_scope_generation('worldinfo', reason='incremental_reconcile')
                        processed_worldinfo_reconcile = True
                else:
                    raise ValueError(f"unsupported index job type: {row['job_type']}")

                _mark_job_status(row['id'], 'done', '')
            except Exception as exc:
                logger.warning('Index job failed %s', row['id'], exc_info=True)
                _mark_job_status(row['id'], 'failed', str(exc))

        if rows:
            with _connect() as conn:
                pending = conn.execute(
                    "SELECT COUNT(*) FROM index_jobs WHERE status = 'pending'"
                ).fetchone()[0]
            _set_jobs_state(worker_state='idle', pending_jobs=int(pending))


def start_index_job_worker():
    with _worker_start_lock:
        if ctx.index_worker_started:
            return
        with _connect(ensure_schema=True):
            pass
        ctx.index_worker_started = True
        threading.Thread(target=worker_loop, daemon=True).start()
