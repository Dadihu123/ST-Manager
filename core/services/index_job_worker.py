import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections import deque
from contextlib import ExitStack, closing

from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.index_runtime_store import (
    SEARCH_CONTENT_FORMAT_VERSION, cleanup_obsolete_generation, ensure_index_runtime_schema,
    get_active_generation, get_search_content_format_version,
)
from core.services.index_build_service import (
    WorldinfoCategoryScanError,
    WorldinfoGenerationMissing,
    _observe_worldinfo_read,
    apply_card_increment,
    classify_worldinfo_path,
    apply_worldinfo_embedded_increment,
    apply_worldinfo_owner_increment,
    apply_worldinfo_path_increment,
    apply_worldinfo_resource_path_increment,
    refresh_worldinfo_category_stats,
    resolve_resource_worldinfo_owner_card_ids,
    worldinfo_increment_batch,
    worldinfo_path_leases,
    worldinfo_prepare_job,
    worldinfo_summaries_match,
)
from core.services.index_upgrade_service import rebuild_scope_generation
from core.services.maintenance_gate import gate
from core.services.path_operation import PATH_BUSY, PATH_RETRY_SECONDS, PathOperationBusy, path_operation
from core.utils.filesystem import filesystem_path_bucket, filesystem_paths_match, prepare_filesystem_path_match


logger = logging.getLogger(__name__)

_worker_start_lock = threading.Lock()


DEDUPABLE_JOB_TYPES = {'rebuild_scope', 'upsert_card', 'upsert_world_embedded', 'upsert_world_owner',
                       'refresh_worldinfo_categories'}
WORLDINFO_RECONCILE_JOB_TYPES = {'upsert_worldinfo_path', 'upsert_world_embedded', 'upsert_world_owner'}
INDEX_JOB_DONE_RETENTION = 200
INDEX_JOB_RETRY_SECONDS = 30
INDEX_DB_TIMEOUT_SECONDS = 60
_NEEDS_PATH_PREFLIGHT = object()


def _connect(*, ensure_schema: bool = False):
    conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=INDEX_DB_TIMEOUT_SECONDS)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=FULL;')
        if ensure_schema:
            ensure_index_runtime_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def enqueue_index_job(job_type: str, entity_id: str = '', source_path: str = '', payload: dict | None = None,
                      *, conn=None, path_matches=None):
    payload = dict(payload or {})
    if job_type == 'upsert_card':
        from core.utils.source_revision import build_file_source_revision
        from core.data.local_state_repository import Repository
        from core.services.card_service import resolve_ui_key
        payload.setdefault('source_revision', build_file_source_revision(source_path))
        ui_key = payload.get('ui_key') or resolve_ui_key(entity_id)
        if conn is None:
            ui_revision = Repository().revision(ui_key)
        else:
            row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (ui_key,)).fetchone()
            ui_revision = row[0] if row else 0
        payload.setdefault('ui_revision', ui_revision)
    payload_json = json.dumps(payload, ensure_ascii=False)
    if conn is None:
        with closing(_connect()) as writer:
            while True:
                with writer:
                    if job_type == 'upsert_worldinfo_path':
                        writer.execute('BEGIN IMMEDIATE')
                    job_id = _enqueue_index_job_on_connection(writer, job_type, entity_id, source_path,
                                                              payload_json, path_matches)
                if job_id is not _NEEDS_PATH_PREFLIGHT:
                    break
                # 此次事务没有写入。释放写锁后采集目录属性，再同当前队列比较。
                path_matches = prepare_filesystem_path_match(source_path)
    else:
        if job_type == 'upsert_worldinfo_path' and path_matches is None:
            path_matches = prepare_filesystem_path_match(source_path, probe=not conn.in_transaction)
        job_id = _enqueue_index_job_on_connection(conn, job_type, entity_id, source_path, payload_json, path_matches)
    ctx.index_wakeup.set()
    return job_id


def _enqueue_index_job_on_connection(conn, job_type, entity_id, source_path, payload_json, path_matches):
    if job_type == 'upsert_worldinfo_path':
        path_key = filesystem_path_bucket(source_path)
        candidates = conn.execute(
            "SELECT id,source_path FROM index_jobs WHERE job_type='upsert_worldinfo_path' AND status='pending' AND path_key=? "
            "ORDER BY id DESC", (path_key,),
        ).fetchall()
        # 持有写锁后只判断当前仍待处理的任务，也能匹配预检期间新入队的别名。
        if path_matches is None:
            normalized_path = os.path.normpath(source_path)
            existing = next((job_id for job_id, path in candidates if os.path.normpath(path) == normalized_path),
                            None)
            if existing is None and candidates and os.name == 'nt':
                return _NEEDS_PATH_PREFLIGHT
        else:
            existing = next((job_id for job_id, path in candidates if path_matches(path)), None)
        if existing is not None:
            job_id = existing
        else:
            job_id = conn.execute(
                'INSERT INTO index_jobs(job_type, entity_id, source_path, payload_json, path_key) VALUES (?,?,?,?,?)',
                (job_type, entity_id, source_path, payload_json, path_key),
            ).lastrowid
    elif job_type in DEDUPABLE_JOB_TYPES:
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
            cursor = conn.execute(
                'INSERT INTO index_jobs(job_type, entity_id, source_path, payload_json) VALUES (?, ?, ?, ?)',
                (job_type, entity_id, source_path, payload_json),
            )
            job_id = cursor.lastrowid
        else:
            job_id = existing[0]
    else:
        cursor = conn.execute(
            'INSERT INTO index_jobs(job_type, entity_id, source_path, payload_json) VALUES (?, ?, ?, ?)',
            (job_type, entity_id, source_path, payload_json),
        )
        job_id = cursor.lastrowid
    pending = conn.execute(
        "SELECT COUNT(*) FROM index_jobs WHERE status = 'pending'"
    ).fetchone()[0]
    _set_jobs_state(pending_jobs=int(pending))
    return job_id


def _set_jobs_state(**updates):
    with ctx.index_lock:
        ctx.index_state['jobs'].update(updates)
        if 'pending_jobs' in updates:
            ctx.index_state['pending_jobs'] = updates['pending_jobs']


def _claim_pending_jobs(limit: int = 50):
    claim_token = f'claim:{uuid.uuid4().hex}'
    with closing(_connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        now = time.time()
        cutoff = int(now) - INDEX_JOB_RETRY_SECONDS
        fresh = conn.execute(
            "SELECT id FROM index_jobs WHERE status='pending' AND retry_after<=? ORDER BY id LIMIT ?",
            (now, limit),
        ).fetchall()
        # 两队列都有积压时各保留半批，任一队列不足时由另一队列填满。
        retries = conn.execute(
            "SELECT id FROM index_jobs WHERE status='failed' AND finished_at<=? AND retry_after<=? "
            "ORDER BY finished_at, id LIMIT ?", (cutoff, now, max(limit // 2, limit - len(fresh))),
        ).fetchall()
        job_ids = [row['id'] for row in fresh[:limit - len(retries)] + retries]
        claimed_rows = []
        pending = 0
        if job_ids:
            placeholders = ','.join('?' for _ in job_ids)
            conn.execute(
                "UPDATE index_jobs SET status='running', started_at=COALESCE(NULLIF(started_at,0), "
                f"strftime('%s','now')), retry_after=0, error_msg=? WHERE id IN ({placeholders})",
                [claim_token, *job_ids],
            )
            claimed_rows = conn.execute(
                'SELECT id, job_type, entity_id, source_path, payload_json, error_msg AS claim_token '
                f'FROM index_jobs WHERE status = ? AND error_msg = ? AND id IN ({placeholders}) ORDER BY id',
                ['running', claim_token, *job_ids],
            ).fetchall()
            if len(job_ids) == limit:
                pending = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM index_jobs WHERE status='pending') + "
                    "(SELECT COUNT(*) FROM index_jobs WHERE status='failed' AND finished_at<=?)", (cutoff,),
                ).fetchone()[0]
        elif limit:
            pending = conn.execute(
                "SELECT COUNT(*) FROM index_jobs WHERE retry_after>0 AND status IN ('pending','failed')",
            ).fetchone()[0]

    return claimed_rows, int(pending)


def _mark_job_status(job_id: int, status: str, error_msg: str = ''):
    with closing(_connect()) as conn, conn:
        updated = conn.execute(
            "UPDATE index_jobs SET status=?, started_at=COALESCE(NULLIF(started_at, 0), strftime('%s','now')), "
            "finished_at=strftime('%s','now'), error_msg=? WHERE id=? AND (status<>'done' OR ?='done')",
            (status, error_msg, int(job_id), status),
        )
        if not updated.rowcount:
            return  # 同步保存可能已在确认重试期间完成该任务。
        _prune_terminal_jobs(conn)
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


def _indexed_resource_rows(conn, path_key):
    return tuple(conn.execute(
        "SELECT entity_id, owner_entity_id, source_path FROM index_entities_v2 WHERE generation=("
        "SELECT active_generation FROM index_build_state WHERE scope='worldinfo') "
        "AND entity_type='world_resource' AND path_key=? ORDER BY entity_id", (path_key,),
    ))


def _resource_path_inputs(conn, source_path):
    owners = resolve_resource_worldinfo_owner_card_ids(source_path, conn=conn)
    indexed = _observe_worldinfo_read(conn, _indexed_resource_rows, filesystem_path_bucket(source_path))
    directory_cases = {}
    return owners, [(entity, owner) for entity, owner, path in indexed
                    if filesystem_paths_match(source_path, path, directory_cases=directory_cases)]


def _resource_job_owners(conn, source_path, include_existing):
    if include_existing:
        owners, indexed = _resource_path_inputs(conn, source_path)
        return sorted(set(owners) | {owner[6:] for _, owner in indexed if owner.startswith('card::')})
    return resolve_resource_worldinfo_owner_card_ids(source_path, conn=conn)


def _prepare_resource_worldinfo_path(conn, source_path):
    owners, indexed = _resource_path_inputs(conn, source_path)
    if owners or indexed:
        apply_worldinfo_resource_path_increment(
            conn, source_path, owners, [entity_id for entity_id, _ in indexed], commit=False,
        )


def _migration_rebuild_covered(payload):
    """启动重建可能已消费这次备注变化；在一个读视图内确认后才可跳过。"""
    previous = payload.get('note_migration_generation')
    if payload.get('scope') != 'worldinfo' or type(previous) is not int or previous <= 0:
        return False
    with closing(_connect()) as conn:
        conn.execute('BEGIN')
        active = get_active_generation(conn, 'worldinfo')
        return (active > previous
                and get_search_content_format_version(conn, 'worldinfo') >= SEARCH_CONTENT_FORMAT_VERSION
                and worldinfo_summaries_match(conn, active))


def _apply_single_worldinfo_job(row, payload):
    with closing(_connect()) as conn, conn:
        if row['job_type'] == 'upsert_world_embedded':
            apply_worldinfo_embedded_increment(conn, row['entity_id'], row['source_path'])
        elif row['job_type'] == 'upsert_world_owner':
            apply_worldinfo_owner_increment(conn, row['entity_id'], row['source_path'],
                                           remove_owner_ids=payload.get('remove_owner_ids') or [])
        elif classify_worldinfo_path(row['source_path']).get('kind') == 'resource':
            source_path = row['source_path']
            # 无绑定且无旧投影时，不需要首次构建。
            owners, indexed = _resource_path_inputs(conn, source_path)
            if owners or indexed:
                with worldinfo_increment_batch(conn):
                    _prepare_resource_worldinfo_path(conn, source_path)
        else:
            apply_worldinfo_path_increment(conn, row['source_path'])


class _WorldinfoBootstrap:
    """缺少活动代时，所有依赖首次构建的作业共享同一次失败和重试窗口。"""

    def __init__(self):
        self.error = None
        self.retry_at = 0

    def rebuild(self):
        if time.time() >= self.retry_at:
            try:
                rebuild_scope_generation('worldinfo', reason='incremental_reconcile')
            except PathOperationBusy:
                raise
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
                self.retry_at = int(time.time()) + INDEX_JOB_RETRY_SECONDS
                logger.warning('Worldinfo bootstrap failed; retaining jobs for retry: %s', self.error)
            else:
                self.error = None
                self.retry_at = 0
        return self.error


def _flush_job_results(results):
    while results:
        _mark_job_status(*results[0])
        results.popleft()


def _defer_path_jobs(rows):
    retry_after = time.time() + PATH_RETRY_SECONDS
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "UPDATE index_jobs SET status=CASE WHEN finished_at>0 THEN 'failed' ELSE 'pending' END, "
            "retry_after=?, error_msg=CASE WHEN finished_at>0 THEN ? ELSE '' END "
            "WHERE id=? AND status='running' AND error_msg=?",
            ((retry_after, PATH_BUSY, row['id'], row['claim_token']) for row in rows),
        )


def _process_claimed_jobs(rows, bootstrap, results):
    world_rows, deferred, other_rows = [], [], []
    with ExitStack() as leases, worldinfo_path_leases(leases):
        for row in rows:
            if row['job_type'] in WORLDINFO_RECONCILE_JOB_TYPES:
                if leases.enter_context(path_operation(row['source_path'], exclusive=False)):
                    world_rows.append(row)
                else:
                    deferred.append(row)
            else:
                other_rows.append(row)
        if world_rows:
            _process_ready_jobs(world_rows, bootstrap, results, deferred)
    if other_rows:
        _process_ready_jobs(other_rows, bootstrap, results, deferred)
    if deferred:
        _defer_path_jobs(deferred)


def _process_ready_jobs(rows, bootstrap, results, deferred):
    from core.data.local_state_repository import StateConflict

    bootstrap_attempted = False
    bootstrap_error = None
    bootstrap_busy = False
    world_rows = [row for row in rows if row['job_type'] in WORLDINFO_RECONCILE_JOB_TYPES]
    if world_rows:
        with closing(_connect()) as batch_conn, batch_conn:
            active = batch_conn.execute("SELECT active_generation FROM index_build_state WHERE scope='worldinfo'").fetchone()
            if active and int(active[0] or 0) > 0:
                preparation_failures = {}
                path_conflicts = set()
                try:
                    with worldinfo_increment_batch(batch_conn):
                        for item in world_rows:
                            try:
                                with worldinfo_prepare_job():
                                    process_worldinfo_job(batch_conn, item)
                            except PathOperationBusy:
                                path_conflicts.add(item['id'])
                            except (sqlite3.Error, StateConflict, WorldinfoGenerationMissing):
                                raise  # 由批次的事务重试策略处理
                            except Exception as exc:
                                preparation_failures[item['id']] = str(exc) or type(exc).__name__
                                logger.warning('Worldinfo job %s preparation failed: %s', item['id'], exc)
                    batch_conn.commit()
                except WorldinfoCategoryScanError as exc:
                    batch_conn.rollback()
                    logger.warning('Worldinfo categories unavailable; retaining batch for retry: %s', exc)
                    results.extend((item['id'], 'failed', preparation_failures.get(item['id'], str(exc)))
                                   for item in world_rows if item['id'] not in path_conflicts)
                    _flush_job_results(results)
                except Exception as exc:
                    batch_conn.rollback()
                    if _database_locked(exc) and not _worldinfo_snapshot_conflict(exc, assume_legacy=True):
                        raise
                    logger.warning('Worldinfo batch failed; retrying jobs independently: %s', exc)
                    # A shared-resource job still prepares and commits all
                    # its owners atomically; unrelated jobs can make progress.
                    for item in world_rows:
                        if item['id'] in path_conflicts:
                            continue
                        if item['id'] in preparation_failures:
                            results.append((item['id'], 'failed', preparation_failures[item['id']]))
                            _flush_job_results(results)
                            continue
                        try:
                            with worldinfo_increment_batch(batch_conn):
                                process_worldinfo_job(batch_conn, item)
                            batch_conn.commit()
                        except PathOperationBusy:
                            batch_conn.rollback()
                            path_conflicts.add(item['id'])
                            continue
                        except Exception as item_exc:
                            batch_conn.rollback()
                            if _database_locked(item_exc) and not _worldinfo_snapshot_conflict(item_exc):
                                raise
                            results.append((item['id'], 'failed', str(item_exc)))
                        else:
                            results.append((item['id'], 'done', ''))
                        _flush_job_results(results)
                else:
                    # 整批投影已提交。首次确认失败时也要保留批内所有结果。
                    for item in world_rows:
                        if item['id'] in path_conflicts:
                            continue
                        error = preparation_failures.get(item['id'])
                        results.append((item['id'], 'failed' if error else 'done', error or ''))
                    _flush_job_results(results)
                deferred.extend(row for row in world_rows if row['id'] in path_conflicts)
                rows = [row for row in rows if row['job_type'] not in WORLDINFO_RECONCILE_JOB_TYPES]

    for row in rows:
        error = None
        try:
            payload = json.loads(row['payload_json'] or '{}')
            if row['job_type'] == 'rebuild_scope':
                if not _migration_rebuild_covered(payload):
                    rebuild_scope_generation(payload.get('scope') or 'cards',
                                             reason=payload.get('reason') or 'manual_rebuild',
                                             rebuild_job=(row['id'], row['claim_token']))
            elif row['job_type'] == 'cleanup_generation':
                with closing(_connect()) as conn:
                    cleanup_obsolete_generation(conn, payload.get('scope'), payload.get('generation'))
            elif row['job_type'] == 'upsert_card':
                process_card_job(row, payload)
            elif row['job_type'] == 'refresh_worldinfo_categories':
                with closing(_connect()) as conn, conn:
                    refresh_worldinfo_category_stats(conn)
            elif row['job_type'] in WORLDINFO_RECONCILE_JOB_TYPES:
                try:
                    _apply_single_worldinfo_job(row, payload)
                except WorldinfoGenerationMissing:
                    if not bootstrap_attempted:
                        bootstrap_attempted = True
                        try:
                            bootstrap_error = bootstrap.rebuild()
                        except PathOperationBusy:
                            bootstrap_busy = True
                    if bootstrap_busy:
                        raise PathOperationBusy(PATH_BUSY)
                    error = bootstrap_error
            else:
                raise ValueError(f"unsupported index job type: {row['job_type']}")

        except PathOperationBusy:
            deferred.append(row)
            continue
        except Exception as exc:
            logger.warning('Index job failed %s', row['id'], exc_info=True)
            error = str(exc)
        results.append((row['id'], 'done' if error is None else 'failed', error or ''))
        _flush_job_results(results)


def _database_locked(exc):
    code = getattr(exc, 'sqlite_errorcode', None)
    if code is not None:
        return (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    # Python 3.10 does not expose SQLite error codes on exceptions.
    return isinstance(exc, sqlite3.OperationalError) and str(exc).lower().startswith((
        'database is locked', 'database table is locked', 'database schema is locked', 'database is busy'))


def _worldinfo_snapshot_conflict(exc, *, assume_legacy=False):
    code = getattr(exc, 'sqlite_errorcode', None)
    if code is not None:
        return code == getattr(sqlite3, 'SQLITE_BUSY_SNAPSHOT', None)
    # Python 3.10 only reports the message. Allow a fresh single-job transaction
    # after a batch conflict, then back off if that transaction also hits a lock.
    return assume_legacy and isinstance(exc, sqlite3.OperationalError) and str(exc) == 'database is locked'


def _restore_running_jobs(conn, claim_token=None):
    sql = "UPDATE index_jobs SET status=CASE WHEN finished_at>0 THEN 'failed' ELSE 'pending' END WHERE status='running'"
    if claim_token is None:  # daemon startup: recover work interrupted by process exit
        conn.execute(sql)
    else:
        conn.execute(sql + ' AND error_msg=?', (claim_token,))


def worker_loop(*, recover_running=False):
    initialize = True
    interrupted_claim = None
    wait_for_work = True
    wait_seconds = 30
    bootstrap = _WorldinfoBootstrap()
    results = deque()
    while True:
        try:
            if initialize:
                with gate.activity(), closing(_connect(ensure_schema=True)) as conn, conn:
                    if recover_running:
                        _restore_running_jobs(conn)
                initialize = False
            if wait_for_work:
                _set_jobs_state(worker_state='waiting')
                ctx.index_wakeup.wait(wait_seconds)
            ctx.index_wakeup.clear()

            if ctx.index_upgrade_active:
                _set_jobs_state(worker_state='waiting')
                wait_for_work = False
                ctx.index_upgrade_done.wait(30)
                continue

            with gate.activity():
                if interrupted_claim is not None:
                    # Persist known outcomes before returning this claim's unfinished rows.
                    _flush_job_results(results)
                    with closing(_connect()) as conn, conn:
                        _restore_running_jobs(conn, interrupted_claim)
                    interrupted_claim = None
                rows, pending = _claim_pending_jobs(50)
                wait_for_work = not rows
                wait_seconds = PATH_RETRY_SECONDS if wait_for_work and pending else 30
                _set_jobs_state(worker_state='processing' if rows else 'idle', pending_jobs=int(pending))
                if rows:
                    try:
                        _process_claimed_jobs(rows, bootstrap, results)
                    except sqlite3.OperationalError as exc:
                        if _database_locked(exc):
                            interrupted_claim = rows[0]['claim_token']
                        raise
                from core.data.card_list_projection import drain_active_batch
                try:
                    if drain_active_batch(DEFAULT_DB_PATH, os.fspath(CARDS_FOLDER)):
                        wait_for_work = False
                except OSError as exc:
                    logger.warning('卡片列表暂未完成后台对账: %s', exc)
        except sqlite3.OperationalError as exc:
            if not _database_locked(exc):
                raise
            logger.warning('Index database locked; retrying after backoff: %s', exc)
            _set_jobs_state(worker_state='waiting')
            # Do not hold the maintenance gate or depend on another enqueue to recover.
            time.sleep(1)
            wait_for_work = False


def _run_index_worker():
    try:
        worker_loop(recover_running=True)
    finally:
        with _worker_start_lock:
            ctx.index_worker_started = False


def start_index_job_worker():
    with _worker_start_lock:
        if ctx.index_worker_started:
            return
        ctx.index_wakeup.set()
        threading.Thread(target=_run_index_worker, daemon=True).start()
        ctx.index_worker_started = True


def _prepare_card_ui(card_id, ui_key=None, *, conn=None):
    from core.data.local_state_repository import Repository
    from core.data.ui_store import VERSION_REMARKS_KEY
    from core.services.card_service import resolve_ui_key
    ui_key = ui_key or resolve_ui_key(card_id)
    parent = card_id.rpartition('/')[0]
    rows = Repository().get_many([ui_key, parent] if parent else [ui_key], conn=conn)
    if ui_key == card_id and isinstance(rows.get(parent, (None, 0))[0], dict):
        if VERSION_REMARKS_KEY in rows[parent][0]:
            ui_key = parent
    value, revision = rows.get(ui_key, ({}, 0))
    return ui_key, value, revision


def _check_prepared_ui(conn, ui_key, revision):
    from core.data.local_state_repository import StateConflict
    # BEGIN 在所有文件读取之后；复核版本与投影写入共用这个写事务。
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (ui_key,)).fetchone()
    if (int(row[0]) if row else 0) != revision:
        raise StateConflict('准备索引期间本地状态已变化，请重试')


def _projection_job_matches(payload, ui_key, ui_revision, source_revision):
    """Only a projection task with the applied versions can be acknowledged here."""
    if not isinstance(payload, dict) or set(payload) - {'ui_key', 'ui_revision', 'source_revision'}:
        return False
    try:
        return (payload.get('ui_key', ui_key) == ui_key
                and int(payload.get('ui_revision', 0)) <= ui_revision
                and payload.get('source_revision', source_revision) == source_revision)
    except (TypeError, ValueError):
        return False


def apply_card_increment_and_ack(conn, card_id, source_path='', *, remove_entity_ids=None, ui_key=None,
                                 source_revision=None, file_metadata_applied=False, file_move_applied=False):
    """确认已应用的投影，以及本次完整保存实际完成的文件任务。"""
    from core.data.local_state_repository import card_projection_matches, record_card_projection
    from core.utils.source_revision import build_file_source_revision
    if get_active_generation(conn, 'cards') <= 0:
        raise RuntimeError('cards active generation missing')
    jobs = conn.execute("SELECT id,payload_json FROM index_jobs WHERE job_type='upsert_card' "
                        "AND entity_id=? AND status IN ('pending','running','failed')", (card_id,)).fetchall()
    ui_key, ui, ui_revision = _prepare_card_ui(card_id, ui_key, conn=conn)
    source_revision = build_file_source_revision(source_path) if source_revision is None else source_revision
    ack_ids = []
    if file_metadata_applied:
        from core.services.card_operation_lock import current_file_intents
        if not source_revision or build_file_source_revision(source_path) != source_revision:
            raise OSError('元数据写入后角色文件已变化，保留恢复任务等待重试')
        receipts = dict(current_file_intents())
        for job in jobs:
            payload = json.loads(job[1] or '{}')
            if (receipts.get(job[0]) == payload.get('operation') and payload.get('operation')
                    and payload.get('refresh_file') and not payload.get('remove_entity_ids')
                    and ((payload.get('operation_kind') == 'replace' and not payload.get('old_id'))
                         or (file_move_applied and payload.get('operation_kind') in ('rename', 'convert')
                             and payload.get('old_id') in (remove_entity_ids or [])))):
                _complete_card_companions(payload, move=False)
                ack_ids.append(job[0])
            if file_move_applied and set(payload) <= {'remove_entity_ids', 'ui_key', 'ui_revision', 'source_revision'}:
                cleanup_ids = payload.get('remove_entity_ids') or []
                projection_payload = {key: value for key, value in payload.items() if key != 'remove_entity_ids'}
                if (cleanup_ids and set(cleanup_ids) <= set(remove_entity_ids or [])
                        and _projection_job_matches(projection_payload, ui_key, ui_revision, source_revision)):
                    ack_ids.append(job[0])
    try:
        _check_prepared_ui(conn, ui_key, ui_revision)
        generation = get_active_generation(conn, 'cards')
        if not file_metadata_applied and any(json.loads(job[1] or '{}').get('refresh_file') for job in jobs):
            # UI 保存读到的是旧正文；文件恢复前不能为它签发新文件版本的凭据。
            existing = conn.execute('SELECT source_revision FROM index_entities_v2 WHERE generation=? AND entity_id=?',
                                    (generation, 'card::' + card_id)).fetchone()
            source_revision = existing[0] if existing else ''
        ack_ids.extend(job[0] for job in jobs if _projection_job_matches(
            json.loads(job[1] or '{}'), ui_key, ui_revision, source_revision))
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_ui_projections'").fetchone()
        from core.data import card_list_projection as logical
        metadata_dirty = logical.installed(conn) and conn.execute(
            'SELECT 1 FROM card_list_dirty WHERE generation=? AND key IN (?,?) LIMIT 1',
            (generation, card_id, ui_key)).fetchone()
        already_applied = (not file_metadata_applied and not remove_entity_ids and table
                           and not metadata_dirty
                           and card_projection_matches(conn, card_id, ui_key, ui_revision, source_revision, generation))
        result = True
        if not already_applied:
            result = apply_card_increment(conn, card_id, source_path,
                                          remove_entity_ids=remove_entity_ids, commit=False,
                                          ui_data={ui_key: ui}, source_revision=source_revision, ui_key=ui_key)
            if result and table:
                record_card_projection(conn, card_id, ui_key, ui_revision, source_revision, generation)
        if result:
            conn.executemany("UPDATE index_jobs SET status='done', finished_at=strftime('%s','now') "
                             "WHERE id=? AND status IN ('pending','running','failed')",
                             [(job_id,) for job_id in ack_ids])
        conn.commit()
        if not already_applied or ack_ids:
            ctx.index_wakeup.set()
        return result
    except Exception:
        conn.rollback()
        raise


def complete_card_file_move(conn, card_id, source_path, *, old_id, source_revision):
    """Confirm this writer's move only after metadata and authoritative UI migration."""
    from core.services.card_operation_lock import current_file_intents
    receipts = dict(current_file_intents())
    if not receipts:
        return False
    jobs = conn.execute("SELECT id,payload_json FROM index_jobs WHERE job_type='upsert_card' "
                        "AND entity_id=? AND status IN ('pending','running','failed')", (card_id,)).fetchall()
    moves = []
    for job in jobs:
        payload = json.loads(job[1] or '{}')
        if (receipts.get(job[0]) == payload.get('operation') and payload.get('operation')
                and payload.get('refresh_file') and payload.get('old_id') == old_id
                and payload.get('operation_kind') in ('rename', 'convert')):
            _complete_card_companions(payload, move=False)
            moves.append(job[0])
    if not moves:
        return False
    from core.utils.source_revision import build_file_source_revision
    if not source_revision or build_file_source_revision(source_path) != source_revision:
        raise OSError('文件移动后版本已变化，保留恢复任务等待重试')
    row = conn.execute('SELECT card_uid FROM card_metadata WHERE id=?', (card_id,)).fetchone()
    if not row:
        raise RuntimeError('文件已移动，元数据未完成，需要恢复')
    from core.data.source_update_monitor_store import rename_source_update_monitor_card_reference
    rename_source_update_monitor_card_reference(conn, old_id, card_id)
    conn.execute('DELETE FROM card_metadata WHERE id=?', (old_id,))
    # A move also changes embedded/resource owner IDs. The durable follow-up and
    # operation acknowledgement belong to the same transaction.
    enqueue_index_job('upsert_world_owner', entity_id=card_id, source_path=source_path,
                      payload={'remove_owner_ids': [old_id]}, conn=conn)
    # A body write can precede this rename in the same operation. Its bytes are
    # now represented by the final metadata as well; do not leave its old path
    # protected. Receipts from earlier requests are deliberately excluded.
    for job in conn.execute("SELECT id,payload_json FROM index_jobs WHERE job_type='upsert_card' "
                            "AND entity_id=? AND status IN ('pending','running','failed')", (old_id,)).fetchall():
        payload = json.loads(job[1] or '{}')
        if (receipts.get(job[0]) == payload.get('operation') and payload.get('operation')
                and payload.get('refresh_file') and payload.get('operation_kind') == 'replace'
                and not payload.get('old_id')):
            conn.execute("UPDATE index_jobs SET status='done',finished_at=strftime('%s','now') WHERE id=?", (job[0],))
    from core.data.index_runtime_store import get_active_generation
    if get_active_generation(conn, 'cards') > 0:
        row_factory = conn.row_factory
        try:
            conn.row_factory = sqlite3.Row
            return apply_card_increment_and_ack(conn, card_id, source_path, remove_entity_ids=[old_id],
                                                 source_revision=source_revision, file_metadata_applied=True,
                                                 file_move_applied=True)
        finally:
            conn.row_factory = row_factory
    # A generation may not exist yet. Metadata/UI migration is still complete;
    # retain the projection work instead of protecting obsolete filesystem IDs.
    enqueue_index_job('upsert_card', entity_id=card_id, source_path=source_path,
                      payload={'remove_entity_ids': [old_id], 'source_revision': source_revision}, conn=conn)
    conn.executemany("UPDATE index_jobs SET status='done',finished_at=strftime('%s','now') WHERE id=?",
                     [(job_id,) for job_id in moves])
    conn.commit()
    ctx.index_wakeup.set()
    return True


def _file_commit_evidence(path):
    """Capture bytes and file identity; an existing destination is not a commit."""
    try:
        with open(path, 'rb') as source:
            before = os.fstat(source.fileno())
            digest = hashlib.sha256()
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
            after = os.fstat(source.fileno())
        current = os.stat(path)
    except FileNotFoundError:
        return None

    def identity(stat):
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    # Windows fstat/stat can report different ctime meanings; compare ctime only
    # on the same open handle, while path identity guards replacement races.
    if (identity(before) != identity(after) or before.st_ctime_ns != after.st_ctime_ns
            or identity(after) != identity(current)):
        raise OSError('准备文件恢复凭据时文件已变化，请重试')
    return {'device': after.st_dev, 'inode': after.st_ino, 'size': after.st_size,
            'mtime_ns': after.st_mtime_ns, 'sha256': digest.hexdigest()}


def pending_card_file_ids(conn, *, cards_root=None):
    """Scanners must leave identities owned by unfinished file recovery intact."""
    protected = set()
    from core.utils.paths import is_under_base

    for entity_id, source_path, payload_json in conn.execute(
            "SELECT entity_id,source_path,payload_json FROM index_jobs WHERE job_type='upsert_card' "
            "AND status IN ('pending','running','failed')"):
        payload = json.loads(payload_json or '{}')
        if payload.get('refresh_file'):
            if cards_root and source_path and not is_under_base(source_path, cards_root):
                continue
            protected.update(value for value in [entity_id, payload.get('old_id'),
                             *(payload.get('remove_entity_ids') or [])] if value)
            protected.update(os.path.relpath(item[key], cards_root or CARDS_FOLDER).replace('\\', '/')
                             for item in payload.get('companions', []) for key in ('source', 'target'))
    return protected


def _prepare_card_companions(source, target):
    """伴生图是主 JSON 的资源，不应创建角色卡解析任务。"""
    from core.consts import SIDECAR_EXTENSIONS
    from core.config import CARDS_FOLDER
    from core.utils.paths import is_under_base
    if not source or not source.lower().endswith('.json'):
        return []
    base = os.path.splitext(source)[0]
    companions = []
    for extension in SIDECAR_EXTENSIONS:
        original = base + extension
        destination = os.path.join(os.path.dirname(target), os.path.basename(original))
        if not all(is_under_base(path, CARDS_FOLDER, resolve_symlinks=True)
                   for path in (original, destination)):
            raise ValueError('伴生图路径越界')
        evidence = _file_commit_evidence(original)
        if evidence is None:
            continue
        if _file_commit_evidence(destination) is not None:
            raise OSError('伴生图目标已存在，保留原文件并中止转包')
        companions.append({'source': original, 'target': destination, 'evidence': evidence})
    return companions


def _complete_card_companions(payload, *, move):
    from core.config import CARDS_FOLDER
    from core.utils.paths import is_under_base
    for item in payload.get('companions', []):
        source, target, expected = item['source'], item['target'], item['evidence']
        if not all(is_under_base(path, CARDS_FOLDER, resolve_symlinks=True) for path in (source, target)):
            raise ValueError('伴生图恢复路径越界')
        original, destination = _file_commit_evidence(source), _file_commit_evidence(target)
        if original is None and destination == expected:
            continue  # 已移动，包含移动后再次退出进程的情况。
        if not move or original != expected or destination is not None:
            raise OSError('伴生图未完成移动或文件已变化，保留恢复任务等待重试')
        # 同一父目录内转包不跨卷；rename 保留意图记录的文件身份。
        os.rename(source, target)
        if _file_commit_evidence(source) is not None or _file_commit_evidence(target) != expected:
            raise OSError('伴生图移动后身份不匹配，保留恢复任务等待重试')


def complete_card_path_companions(job_ids, *, conn):
    """补齐主卡意图中的伴生移动，最终任务确认仍由完整保存流程负责。"""
    for job_id in job_ids:
        row = conn.execute('SELECT payload_json FROM index_jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise RuntimeError('文件恢复意图不存在')
        _complete_card_companions(json.loads(row[0]), move=True)


def prepare_card_file_intent(path, *, old_path=None, operation_kind='replace', ui_move=None,
                             prepared_path=None, bundle_conversion=False):
    """文件原子替换之前持久化意图，崩溃后重新读取实际文件，不重放旧正文。"""
    from core.config import CARDS_FOLDER
    root, absolute = os.path.abspath(CARDS_FOLDER), os.path.abspath(path)
    if os.path.splitdrive(root)[0].lower() != os.path.splitdrive(absolute)[0].lower() or os.path.commonpath([root, absolute]) != root:
        return None  # 快照/临时上传不是活跃卡片。
    card_id = os.path.relpath(absolute, root).replace('\\', '/')
    from core.services.card_operation_lock import retain_card_file_locks
    retain_card_file_locks(absolute, old_path)
    payload = {'refresh_file': True, 'operation': uuid.uuid4().hex, 'operation_kind': operation_kind}
    if ui_move:
        payload.update(ui_move_from=ui_move[0], ui_move_to=ui_move[1])
    if old_path:
        old_absolute = os.path.abspath(old_path)
        if os.path.commonpath([root, old_absolute]) != root:
            raise ValueError('旧角色卡路径越界')
        from core.utils.source_revision import build_file_source_revision
        payload.update(old_id=os.path.relpath(old_absolute, root).replace('\\', '/'),
                       old_path=old_absolute, old_source_revision=build_file_source_revision(old_absolute))
        if operation_kind == 'convert':
            if not prepared_path:
                raise ValueError('转换恢复意图缺少暂存输出')
            output = _file_commit_evidence(prepared_path)
            if not output or not output['inode']:
                raise OSError('无法确认转换暂存输出的文件身份')
            payload.update(prepared_output=output, target_before=_file_commit_evidence(absolute),
                           old_file=_file_commit_evidence(old_absolute))
    # 在文件操作前捕获 bundle 归属；冷启动恢复时不能再依赖旧缓存或新目录已存在。
    marker = os.path.join(os.path.dirname(old_path or absolute), '.bundle')
    try:
        os.stat(marker)
    except FileNotFoundError:
        pass
    else:
        payload['ui_key'] = card_id.rpartition('/')[0]
    if bundle_conversion:
        payload.update(bundle_conversion=True, ui_key=card_id.rpartition('/')[0])
        payload['companions'] = _prepare_card_companions(old_path, absolute)
    job_id = enqueue_index_job('upsert_card', entity_id=card_id, source_path=absolute, payload=payload)
    from core.services.card_operation_lock import record_file_intent
    record_file_intent(job_id, payload['operation'])
    return job_id


def prepare_card_path_intents(source, destination, *, bundle_conversion=False):
    """移动前严格枚举目录，复用单卡文件意图覆盖最终位置及 UI 前缀。"""
    from core.config import CARDS_FOLDER
    from core.utils.filesystem import walk_directory_strict
    root = os.path.normcase(os.path.abspath(CARDS_FOLDER))
    old, new = os.path.abspath(source), os.path.abspath(destination)
    def inside(path):
        try:
            return os.path.commonpath([root, os.path.normcase(path)]) == root
        except ValueError:
            return False
    if not inside(new):
        return []
    in_cards = inside(old)
    if os.path.isdir(old):
        move = (os.path.relpath(old, CARDS_FOLDER).replace('\\', '/'),
                os.path.relpath(new, CARDS_FOLDER).replace('\\', '/')) if in_cards else None
        files = [(os.path.join(parent, name), os.path.join(new, os.path.relpath(os.path.join(parent, name), old)))
                 for parent, _dirs, names in walk_directory_strict(old) for name in names
                 if name.lower().endswith(('.png', '.json'))]
    else:
        move, files = None, [(old, new)] if new.lower().endswith(('.png', '.json')) else []
    from core.services.card_operation_lock import retain_card_file_locks
    retain_card_file_locks(*(path for pair in files for path in pair))
    return [prepare_card_file_intent(target, old_path=original if in_cards else None,
                                    operation_kind='rename' if in_cards else 'replace', ui_move=move,
                                    bundle_conversion=bundle_conversion)
            for original, target in files]


def process_card_job(row, payload):
    from core.config import CARDS_FOLDER
    from core.data import card_list_projection as logical
    from core.data.local_state_repository import card_projection_matches, record_card_projection
    from core.services.card_operation_lock import card_locks
    from core.services.index_build_service import _owner_file_confirmed_missing
    from core.utils.paths import is_under_base
    root = os.fspath(CARDS_FOLDER)
    companion_ids = [os.path.relpath(item[key], CARDS_FOLDER).replace('\\', '/')
                     for item in payload.get('companions', []) for key in ('source', 'target')]
    with card_locks([row['entity_id'], payload.get('old_id'), *(payload.get('remove_entity_ids') or []),
                     *companion_ids]):
        with _connect() as conn:
            # 同步保存已完成的领取任务不再执行；只按自己的 id 完成。
            state = conn.execute('SELECT status FROM index_jobs WHERE id=?', (row['id'],)).fetchone()
            if state and state[0] == 'done':
                return
            scanned_root = logical.metadata_root(conn)
            if scanned_root and (not logical.metadata_matches(conn, root)
                                 or row['source_path'] and not is_under_base(row['source_path'], root)):
                if payload.get('refresh_file'):
                    raise RuntimeError('待恢复角色卡所属目录未激活')
                # Derived work from a previous root is superseded by a full scan and rebuild.
                return
            from core.utils.source_revision import build_file_source_revision
            old_id = payload.get('old_id')
            old_path = payload.get('old_path')
            recovery_ui = None
            recovery_jobs_before = None
            source_to_remove = None
            if old_id:
                try:
                    os.stat(row['source_path'])
                except FileNotFoundError:
                    # 意图已落盘但文件操作尚未发生；旧文件仍是权威事实。
                    if not _owner_file_confirmed_missing(row['entity_id']):
                        raise OSError('待恢复角色卡在目录核验期间变化，请重试')
                    os.stat(old_path)
                    conn.execute("UPDATE index_jobs SET status='done' WHERE id=?", (row['id'],))
                    conn.commit()
                    return
                if old_id != row['entity_id']:
                    try:
                        os.stat(old_path)
                    except FileNotFoundError:
                        if not _owner_file_confirmed_missing(old_id):
                            raise OSError('待恢复旧角色卡在目录核验期间变化，请重试')
                    else:
                        if payload.get('operation_kind') != 'convert':
                            raise RuntimeError('恢复旧路径已变化，需保留两份文件并重试')
                        old_evidence = _file_commit_evidence(old_path)
                        target_evidence = _file_commit_evidence(row['source_path'])
                        expected_output = payload.get('prepared_output')
                        if not expected_output or not payload.get('old_file'):
                            raise RuntimeError('转换恢复缺少输出身份凭据，保留源文件等待重试')
                        if target_evidence != expected_output:
                            if (target_evidence == payload.get('target_before')
                                    and old_evidence == payload['old_file']):
                                # The original companion image is still at the destination.
                                # The durable intent predates replace; cancel this attempt.
                                conn.execute("UPDATE index_jobs SET status='done' WHERE id=?", (row['id'],))
                                conn.commit()
                                return
                            raise RuntimeError('无法确认转换已提交，保留源文件和目标文件等待重试')
                        if old_evidence != payload['old_file']:
                            raise RuntimeError('恢复转换源文件已变化，需保留两份文件并重试')
                        source_to_remove = old_path
                    from core.data.ui_store import load_ui_data, rename_embedded_worldinfo_note_card_prefix
                    recovery_ui = load_ui_data()
                    if payload.get('bundle_conversion'):
                        from core.services.card_service import migrate_card_to_bundle_ui
                        _complete_card_companions(payload, move=True)
                        marker = os.path.join(os.path.dirname(row['source_path']), '.bundle')
                        try:
                            with open(marker, 'x') as stream:
                                stream.write('1')
                        except FileExistsError:
                            pass
                        migrate_card_to_bundle_ui(recovery_ui, old_id, row['entity_id'],
                                                  import_time=os.path.getmtime(row['source_path']))
                    else:
                        from core.services.card_service import rename_folder_in_ui, _merge_bundle_version_remarks_after_card_move
                        rename_folder_in_ui(recovery_ui, payload.get('ui_move_from') or old_id,
                                            payload.get('ui_move_to') or row['entity_id'])
                        if not payload.get('ui_move_from'):
                            _merge_bundle_version_remarks_after_card_move(recovery_ui, old_id, row['entity_id'], row['source_path'])
                        rename_embedded_worldinfo_note_card_prefix(recovery_ui,
                            payload.get('ui_move_from') or old_id, payload.get('ui_move_to') or row['entity_id'])
            ui_key, ui, ui_revision = _prepare_card_ui(row['entity_id'], payload.get('ui_key'))
            source_revision = build_file_source_revision(row['source_path'])
            if payload.get('refresh_file'):
                from flask import Flask, g
                from core.services.cache_service import update_card_cache
                from core.utils.image import extract_card_info_with_status, CARD_INFO_UNREADABLE
                from core.utils.hash import get_file_hash_and_size
                try:
                    os.stat(row['source_path'])
                except FileNotFoundError:
                    if not _owner_file_confirmed_missing(row['entity_id']):
                        raise OSError('待恢复角色卡在目录核验期间变化，请重试')
                    _check_prepared_ui(conn, ui_key, ui_revision)
                    conn.execute('DELETE FROM card_metadata WHERE id=?', (row['entity_id'],))
                else:
                    info, status = extract_card_info_with_status(row['source_path'], raise_access_errors=True)
                    if status == CARD_INFO_UNREADABLE:
                        raise OSError('无法读取待恢复角色卡')
                    if info is None:
                        raise ValueError('待恢复文件不是合法角色卡')
                    file_hash, file_size = get_file_hash_and_size(row['source_path'])
                    from core.utils.text import calculate_token_count
                    body = info.get('data', info)
                    calc = dict(body)
                    calc.setdefault('name', info.get('name') or body.get('name') or os.path.splitext(os.path.basename(row['source_path']))[0])
                    token_count = calculate_token_count(calc)
                    mtime = os.stat(row['source_path']).st_mtime
                    if build_file_source_revision(row['source_path']) != source_revision:
                        raise OSError('待恢复文件在读取期间变化，请重试')
                    _check_prepared_ui(conn, ui_key, ui_revision)
                    if recovery_ui is not None:
                        from core.data.local_state_repository import Repository
                        recovery_jobs_before = conn.execute('SELECT COALESCE(MAX(id),0) FROM index_jobs').fetchone()[0]
                        Repository().save(recovery_ui, conn=conn)
                        from core.data.source_update_monitor_store import rename_source_update_monitor_card_reference
                        rename_source_update_monitor_card_reference(conn, old_id, row['entity_id'])
                        ui_key, ui, ui_revision = _prepare_card_ui(row['entity_id'], payload.get('ui_key'), conn=conn)
                    with Flask(__name__).app_context():
                        g.db = conn
                        result = update_card_cache(row['entity_id'], row['source_path'], parsed_info=info,
                                                   file_hash=file_hash, file_size=file_size, mtime=mtime,
                                                   token_count=token_count, commit=False,
                                                   remove_entity_ids=[old_id] if old_id else None)
                        g.pop('db', None)
                        if not result.get('cache_updated'):
                            raise RuntimeError('文件已保存，元数据恢复失败')
                    if old_id and old_id != row['entity_id']:
                        conn.execute('DELETE FROM card_metadata WHERE id=?', (old_id,))
                    if old_id:
                        conn.execute("INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) "
                                     "VALUES ('upsert_world_owner',?,?,?)",
                                     (row['entity_id'], row['source_path'], json.dumps({'remove_owner_ids': [old_id]})))
                    elif result.get('has_embedded_wi') or result.get('previous_has_embedded_wi'):
                        conn.execute("INSERT INTO index_jobs(job_type,entity_id,source_path) "
                                     "VALUES ('upsert_world_embedded',?,?)", (row['entity_id'], row['source_path']))
            _check_prepared_ui(conn, ui_key, ui_revision)
            if not logical.metadata_matches(conn, root):
                raise RuntimeError('索引任务执行期间卡片目录已变化')
            generation = get_active_generation(conn, 'cards')
            projection_table = conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_ui_projections'").fetchone()
            cleanup = set(payload.get('remove_entity_ids') or []) | ({old_id} if old_id else set())
            if (payload.get('refresh_file') or cleanup or not projection_table or not card_projection_matches(
                    conn, row['entity_id'], ui_key, ui_revision, source_revision, generation)):
                apply_card_increment(conn, row['entity_id'], row['source_path'], remove_entity_ids=list(cleanup),
                                     commit=False, ui_data={ui_key: ui}, source_revision=source_revision, ui_key=ui_key)
                if projection_table:
                    record_card_projection(conn, row['entity_id'], ui_key, ui_revision, source_revision, generation)
            if recovery_jobs_before is not None:
                # 只确认本事务迁移 UI 时产生的卡片投影任务，不触碰进入恢复前已有的新任务。
                conn.execute("UPDATE index_jobs SET status='done' WHERE job_type='upsert_card' "
                             "AND entity_id IN (?,?) AND id>?", (old_id, row['entity_id'], recovery_jobs_before))
                if projection_table:
                    conn.execute('DELETE FROM card_ui_projections WHERE card_id=?', (old_id,))
            if source_to_remove:
                # The valid target and its metadata/UI/index are durable before the
                # only original is removed. Until cleanup succeeds, keep this job retryable.
                conn.commit()
                if (_file_commit_evidence(row['source_path']) != payload['prepared_output']
                        or _file_commit_evidence(source_to_remove) != payload['old_file']):
                    raise RuntimeError('转换清理前文件已变化，保留源文件等待重试')
                os.remove(source_to_remove)
            conn.execute("UPDATE index_jobs SET status='done' WHERE id=?", (row['id'],))
            conn.commit()


def process_worldinfo_job(conn, row):
    payload = json.loads(row['payload_json'] or '{}')
    job_type = row['job_type']
    source_path = row['source_path']
    if job_type == 'upsert_world_owner':
        cleanup_ids = payload.get('remove_owner_ids') or []
        if not cleanup_ids and classify_worldinfo_path(source_path).get('kind') == 'resource':
            # 兼容已入队的旧版按角色刷新任务。角色卡移动则只处理指定角色。
            include_existing = payload.get('resource_note') or payload.get('unbound_resource_note')
            owners = set(_resource_job_owners(conn, source_path, include_existing))
            if not owners and include_existing:
                return True
            owners.add(row['entity_id'])
            for owner in sorted(owners):
                apply_worldinfo_owner_increment(conn, owner, source_path, commit=False)
            return True
        return apply_worldinfo_owner_increment(conn, row['entity_id'], source_path,
                                              remove_owner_ids=cleanup_ids, commit=False)
    if job_type == 'upsert_world_embedded':
        return apply_worldinfo_embedded_increment(conn, row['entity_id'], source_path, commit=False)
    if classify_worldinfo_path(source_path).get('kind') == 'resource':
        # 路径任务包含当前绑定和待清理的旧投影，包括带旧备注标志的任务。
        _prepare_resource_worldinfo_path(conn, source_path)
        return True
    return apply_worldinfo_path_increment(conn, source_path, commit=False)
