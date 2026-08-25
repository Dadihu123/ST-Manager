"""角色卡来源更新监控池、运行记录和应用内调度器。"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.10 always provides zoneinfo
    ZoneInfo = None

from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.source_update_monitor_store import (
    DEFAULT_MONITOR_POOL_ID,
    DEFAULT_MONITOR_POOL_NAME,
    ensure_source_update_monitor_schema,
)
from core.data.ui_store import get_source_update_state, load_ui_data
from core.services.card_operation_lock import (
    card_busy_result,
    release_card_lock,
    try_acquire_card_lock,
)
from core.services.forum_update_service import (
    check_card_source_update,
    is_supported_source_url,
    prepare_source_link_for_card,
    resolve_card_source,
)

logger = logging.getLogger(__name__)

VALID_SCHEDULE_MODES = frozenset({'manual', 'daily'})
ACTIVE_RUN_STATUSES = ('queued', 'running')
TERMINAL_RUN_STATUSES = ('completed', 'failed', 'cancelled', 'aborted')
DAILY_TIME_RE = re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d$')
SCHEDULER_INTERVAL_SECONDS = 45

_scheduler_guard = threading.Lock()
_scheduler_thread = None
_scheduler_stop = threading.Event()
_active_pool_guard = threading.Lock()
_active_pool_ids = set()


def _normalize_card_id(card_id):
    value = str(card_id or '').strip().replace('\\', '/')
    if not value or value.startswith('/') or value == '.' or value == '..':
        return ''
    if any(part in {'', '.', '..'} for part in value.split('/')):
        return ''
    drive, _ = os.path.splitdrive(value)
    if drive or re.match(r'^[A-Za-z]:', value) or '\x00' in value:
        return ''
    return value


def is_safe_monitor_card_id(card_id):
    return bool(_normalize_card_id(card_id))


def _connect():
    conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    ensure_source_update_monitor_schema(conn, recover_stale=False)
    return conn


def _with_connection(callback):
    """执行一个短数据库事务，并对 SQLite 锁冲突做有限重试。"""
    last_error = None
    for attempt in range(5):
        conn = None
        try:
            conn = _connect()
            result = callback(conn)
            conn.commit()
            return result
        except sqlite3.OperationalError as exc:
            last_error = exc
            if 'locked' not in str(exc).lower() or attempt >= 4:
                raise
            if conn is not None:
                conn.rollback()
            time.sleep(0.1 * (attempt + 1))
        finally:
            if conn is not None:
                conn.close()
    raise last_error or RuntimeError('监控池数据库操作失败')


def _card_path(card_id):
    normalized = _normalize_card_id(card_id)
    if not normalized:
        return ''
    root = os.path.abspath(os.fspath(CARDS_FOLDER))
    path = os.path.abspath(os.path.join(root, normalized.replace('/', os.sep)))
    try:
        if os.path.commonpath([root, path]) != root:
            return ''
    except ValueError:
        return ''
    return path


def _card_exists(card_id, conn=None):
    path = _card_path(card_id)
    if path and os.path.exists(path):
        return True
    return False


def _ui_key_for_card(card_id):
    try:
        from core.services.card_service import resolve_ui_key

        return resolve_ui_key(card_id)
    except (AttributeError, KeyError, TypeError):
        return card_id


def _current_source_url(card_id, ui_data):
    try:
        _card, ui_key, link, _data = resolve_card_source(
            card_id,
            ui_data=ui_data if isinstance(ui_data, dict) else None,
        )
    except (AttributeError, KeyError, TypeError):
        ui_key = _ui_key_for_card(card_id)
        link = ''
    return str(link or '').strip(), ui_key


def _entry_row(conn, card_id, pool_id=DEFAULT_MONITOR_POOL_ID):
    return conn.execute(
        '''
        SELECT * FROM source_update_monitor_entries
        WHERE pool_id = ? AND card_id = ?
        ''',
        (pool_id, card_id),
    ).fetchone()


def _pool_row(conn, pool_id=DEFAULT_MONITOR_POOL_ID):
    row = conn.execute(
        'SELECT * FROM source_update_monitor_pools WHERE pool_id = ?',
        (pool_id,),
    ).fetchone()
    if row is not None:
        return row
    now = time.time()
    conn.execute(
        '''
        INSERT INTO source_update_monitor_pools
            (pool_id, name, enabled, schedule_mode, created_at, updated_at)
        VALUES (?, ?, 0, 'manual', ?, ?)
        ''',
        (pool_id, DEFAULT_MONITOR_POOL_NAME, now, now),
    )
    return conn.execute(
        'SELECT * FROM source_update_monitor_pools WHERE pool_id = ?',
        (pool_id,),
    ).fetchone()


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {'', '0', 'false', 'no', 'off'}


def _normalize_card_ids(card_ids):
    if isinstance(card_ids, str):
        card_ids = [card_ids]
    if not isinstance(card_ids, (list, tuple, set)):
        return []
    result = []
    for raw_id in card_ids:
        card_id = _normalize_card_id(raw_id)
        if card_id and card_id not in result:
            result.append(card_id)
    return result


def _source_reason(source_url):
    if not source_url:
        return '来源链接为空，请先在角色卡详情中填写 Discord 类脑帖子链接'
    return '来源链接无效，仅支持 Discord 类脑帖子链接'


def add_monitor_entries(card_ids, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    """校验并幂等加入监控池；此操作不会发起网络请求。"""
    raw_ids = card_ids if isinstance(card_ids, (list, tuple, set)) else [card_ids]
    ui_data = load_ui_data()

    def operation(conn):
        _pool_row(conn, pool_id)
        now = time.time()
        results = []
        for raw_id in raw_ids:
            normalized = _normalize_card_id(raw_id)
            if not normalized:
                results.append({
                    'card_id': str(raw_id or ''),
                    'success': False,
                    'status': 'invalid_path',
                    'reason': '路径非法，必须是安全的相对路径',
                })
                continue

            existing = _entry_row(conn, normalized, pool_id)
            if existing is not None:
                results.append({
                    'card_id': normalized,
                    'success': True,
                    'status': 'already_in_pool',
                    'message': '角色卡已经在监控池中',
                })
                continue

            if not _card_exists(normalized, conn):
                results.append({
                    'card_id': normalized,
                    'success': False,
                    'status': 'not_found',
                    'reason': '找不到角色卡',
                })
                continue

            source_url, _ = _current_source_url(normalized, ui_data)
            if not is_supported_source_url(source_url):
                reason = _source_reason(source_url)
                results.append({
                    'card_id': normalized,
                    'success': False,
                    'status': 'invalid_source',
                    'reason': reason,
                    'invalid_reason': reason,
                })
                continue

            conn.execute(
                '''
                INSERT INTO source_update_monitor_entries
                    (pool_id, card_id, source_url_snapshot, enabled, added_at,
                     last_seen_source_url, last_run_status, last_error, invalid_reason)
                VALUES (?, ?, ?, 1, ?, ?, 'never_checked', '', '')
                ''',
                (pool_id, normalized, source_url, now, source_url),
            )
            results.append({
                'card_id': normalized,
                'success': True,
                'status': 'added',
                'source_url_snapshot': source_url,
            })
        return results

    results = _with_connection(operation)
    return {
        'success': True,
        'pool_id': pool_id,
        'results': results,
        'added': sum(item['status'] == 'added' for item in results),
        'already_in_pool': sum(item['status'] == 'already_in_pool' for item in results),
        'failed': sum(not item.get('success') for item in results),
    }


def remove_monitor_entries(card_ids, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    """只删除监控池成员关系，不触碰角色卡来源状态。"""
    raw_ids = card_ids if isinstance(card_ids, (list, tuple, set)) else [card_ids]

    def operation(conn):
        results = []
        for raw_id in raw_ids:
            normalized = _normalize_card_id(raw_id)
            if not normalized:
                results.append({
                    'card_id': str(raw_id or ''),
                    'success': False,
                    'status': 'invalid_path',
                    'reason': '路径非法，必须是安全的相对路径',
                })
                continue
            deleted = conn.execute(
                'DELETE FROM source_update_monitor_entries WHERE pool_id = ? AND card_id = ?',
                (pool_id, normalized),
            ).rowcount
            results.append({
                'card_id': normalized,
                'success': True,
                'status': 'removed' if deleted else 'not_in_pool',
            })
        return results

    results = _with_connection(operation)
    return {
        'success': True,
        'pool_id': pool_id,
        'results': results,
        'removed': sum(item['status'] == 'removed' for item in results),
        'not_in_pool': sum(item['status'] == 'not_in_pool' for item in results),
        'failed': sum(not item.get('success') for item in results),
    }


def set_monitor_entry_enabled(card_id, enabled, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    normalized = _normalize_card_id(card_id)
    if not normalized:
        return {'success': False, 'status': 'invalid_path', 'error': '路径非法'}

    def operation(conn):
        changed = conn.execute(
            '''
            UPDATE source_update_monitor_entries SET enabled = ?
            WHERE pool_id = ? AND card_id = ?
            ''',
            (1 if _coerce_bool(enabled) else 0, pool_id, normalized),
        ).rowcount
        if not changed:
            return {'success': False, 'status': 'not_in_pool', 'card_id': normalized}
        return {
            'success': True,
            'status': 'updated',
            'card_id': normalized,
            'enabled': _coerce_bool(enabled),
        }

    return _with_connection(operation)


def get_monitor_target_ids(*, pool_id=DEFAULT_MONITOR_POOL_ID):
    def operation(conn):
        rows = conn.execute(
            '''
            SELECT card_id FROM source_update_monitor_entries
            WHERE pool_id = ? AND enabled = 1
            ORDER BY added_at, card_id
            ''',
            (pool_id,),
        ).fetchall()
        return [str(row['card_id']) for row in rows]

    return _with_connection(operation)


def is_monitor_entry(card_id, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    normalized = _normalize_card_id(card_id)
    if not normalized:
        return False

    def operation(conn):
        return _entry_row(conn, normalized, pool_id) is not None

    return bool(_with_connection(operation))


def _cache_card(card_id):
    cache = getattr(ctx, 'cache', None)
    id_map = getattr(cache, 'id_map', None)
    return id_map.get(card_id) if isinstance(id_map, dict) else None


def _build_entry_payload(row, conn, ui_data, current_run=None):
    card_id = str(row['card_id'])
    source_url, ui_key = _current_source_url(card_id, ui_data)
    state = get_source_update_state(ui_data, ui_key)
    card = _cache_card(card_id) or {}
    metadata = conn.execute(
        'SELECT char_name FROM card_metadata WHERE id = ?',
        (card_id,),
    ).fetchone()
    char_name = card.get('char_name') if isinstance(card, dict) else ''
    if not char_name and metadata is not None:
        char_name = metadata['char_name'] or ''
    exists = _card_exists(card_id, conn)
    supported = bool(source_url and is_supported_source_url(source_url))
    invalid_reason = ''
    display_last_status = row['last_run_status'] or 'never_checked'
    if not exists:
        invalid_reason = '角色卡文件不存在，可能已删除、移动或重命名'
    elif not supported:
        invalid_reason = _source_reason(source_url)
    elif row['invalid_reason'] and row['last_run_status'] in {
        'missing',
        'invalid_source',
    }:
        invalid_reason = ''

    if not exists and row['last_run_status'] != 'missing':
        display_last_status = 'missing'
        conn.execute(
            '''
            UPDATE source_update_monitor_entries
            SET last_run_status = 'missing', invalid_reason = ?
            WHERE pool_id = ? AND card_id = ?
            ''',
            (invalid_reason, row['pool_id'], card_id),
        )
    elif exists and not supported and row['last_run_status'] != 'invalid_source':
        display_last_status = 'invalid_source'
        conn.execute(
            '''
            UPDATE source_update_monitor_entries
            SET last_run_status = 'invalid_source', invalid_reason = ?
            WHERE pool_id = ? AND card_id = ?
            ''',
            (invalid_reason, row['pool_id'], card_id),
        )

    return {
        'pool_id': row['pool_id'],
        'card_id': card_id,
        'char_name': char_name or os.path.splitext(os.path.basename(card_id))[0],
        'source_title': state.get('source_title', ''),
        'source_url': source_url,
        'source_url_current': source_url,
        'source_url_snapshot': row['source_url_snapshot'] or '',
        'source_url_changed': source_url != (row['source_url_snapshot'] or ''),
        'enabled': bool(row['enabled']),
        'added_at': row['added_at'],
        'last_seen_source_url': row['last_seen_source_url'] or '',
        'last_run_status': display_last_status,
        'last_run_at': row['last_run_at'],
        'last_error': row['last_error'] or '',
        'invalid_reason': invalid_reason,
        'exists': exists,
        'supported': supported,
        'pending_update': bool(state.get('pending_update')),
        'source_update': state,
        'is_checking': bool(current_run and current_run.get('current_card_id') == card_id),
    }


def _serialize_run(row):
    if row is None:
        return None
    try:
        summary = json.loads(row['summary_json'] or '{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        summary = {}
    return {
        'run_id': row['run_id'],
        'pool_id': row['pool_id'],
        'trigger': row['trigger'],
        'status': row['status'],
        'started_at': row['started_at'],
        'finished_at': row['finished_at'],
        'total': row['total'] or 0,
        'completed': row['completed'] or 0,
        'current_card_id': row['current_card_id'] or '',
        'summary': summary,
        'error': row['error'] or '',
    }


def _run_row(conn, run_id):
    return conn.execute(
        'SELECT * FROM source_update_monitor_runs WHERE run_id = ?',
        (run_id,),
    ).fetchone()


def _active_run(conn, pool_id):
    return conn.execute(
        '''
        SELECT * FROM source_update_monitor_runs
        WHERE pool_id = ? AND status IN ('queued', 'running')
        ORDER BY started_at, run_id LIMIT 1
        ''',
        (pool_id,),
    ).fetchone()


def _empty_summary(total=0):
    return {
        'total': int(total or 0),
        'selected': int(total or 0),
        'completed': 0,
        'checked': 0,
        'updated': 0,
        'new_changes': 0,
        'pending': 0,
        'unchanged': 0,
        'invalid_source': 0,
        'missing': 0,
        'failed': 0,
        'skipped': 0,
        'card_busy': 0,
    }


def _classify_result(result):
    status = str(result.get('status') or '')
    if status == 'missing':
        return 'missing'
    if status == 'card_busy':
        return 'card_busy'
    if status == 'invalid_source' or not result.get('supported'):
        return 'invalid_source'
    if not result.get('success'):
        return 'failed'
    return 'updated' if result.get('changed') else 'unchanged'


def _add_result_to_summary(summary, result):
    kind = _classify_result(result)
    summary['completed'] += 1
    if kind == 'updated':
        summary['checked'] += 1
        summary['updated'] += 1
        summary['new_changes'] += 1
    elif kind == 'unchanged':
        summary['checked'] += 1
        summary['unchanged'] += 1
    elif kind == 'invalid_source':
        summary['invalid_source'] += 1
        summary['skipped'] += 1
    elif kind == 'missing':
        summary['missing'] += 1
        summary['skipped'] += 1
    elif kind == 'card_busy':
        summary['card_busy'] += 1
        summary['skipped'] += 1
    else:
        summary['failed'] += 1
    if (result.get('source_update') or {}).get('pending_update'):
        summary['pending'] += 1
    return summary


def _record_entry_result(conn, card_id, result, *, pool_id=DEFAULT_MONITOR_POOL_ID, now=None):
    row = _entry_row(conn, card_id, pool_id)
    if row is None:
        return
    ui_data = load_ui_data()
    source_url, _ = _current_source_url(card_id, ui_data)
    status = str(result.get('status') or 'error')
    if status == 'missing':
        last_status = 'missing'
        invalid_reason = '角色卡文件不存在，可能已删除、移动或重命名'
    elif status == 'card_busy':
        last_status = 'card_busy'
        invalid_reason = ''
    elif status == 'invalid_source' or not result.get('supported'):
        last_status = 'invalid_source'
        invalid_reason = result.get('invalid_reason') or result.get('message') or _source_reason(source_url)
    elif result.get('success'):
        last_status = 'updated' if result.get('changed') else 'unchanged'
        invalid_reason = ''
    else:
        last_status = 'error'
        invalid_reason = ''

    next_snapshot = source_url if source_url and is_supported_source_url(source_url) else row['source_url_snapshot']
    conn.execute(
        '''
        UPDATE source_update_monitor_entries
        SET source_url_snapshot = ?, last_seen_source_url = ?, last_run_status = ?,
            last_run_at = ?, last_error = ?, invalid_reason = ?
        WHERE pool_id = ? AND card_id = ?
        ''',
        (
            next_snapshot or '',
            source_url or '',
            last_status,
            float(now if now is not None else time.time()),
            str(result.get('error') or result.get('last_error') or ''),
            invalid_reason,
            pool_id,
            card_id,
        ),
    )


def check_monitored_card(card_id, *, pool_id=DEFAULT_MONITOR_POOL_ID, ui_data=None, now=None):
    """检查一条监控项；无效来源在这里提前返回，绝不触发网络请求。"""
    normalized = _normalize_card_id(card_id)
    if not normalized:
        return card_busy_result(card_id)

    acquired, lock = try_acquire_card_lock(
        normalized,
        blocking=False,
        allow_reentrant=False,
    )
    if not acquired:
        result = card_busy_result(normalized)
        _with_connection(lambda conn: _record_entry_result(conn, normalized, result, pool_id=pool_id, now=now))
        return result

    data = ui_data if isinstance(ui_data, dict) else {}
    try:
        if not data:
            data = load_ui_data()
        with _MonitorReadConnection() as conn:
            entry = _entry_row(conn, normalized, pool_id)
            exists = _card_exists(normalized, conn)
            snapshot = entry['source_url_snapshot'] if entry is not None else ''
        if entry is None:
            return {
                'success': False,
                'status': 'not_in_pool',
                'error': '角色卡不在监控池中',
                'card_id': normalized,
            }

        source_url, ui_key = _current_source_url(normalized, data)
        state = get_source_update_state(data, ui_key)
        if not exists:
            result = {
                'success': False,
                'status': 'missing',
                'supported': False,
                'error': '找不到角色卡文件，可能已删除、移动或重命名',
                'message': '角色卡不存在，已跳过来源检查',
                'card_id': normalized,
                'source_update': state,
            }
        elif not is_supported_source_url(source_url):
            reason = _source_reason(source_url)
            result = {
                'success': True,
                'status': 'invalid_source',
                'supported': False,
                'changed': False,
                'skipped': True,
                'error': reason,
                'message': '来源链接无效，未发起网络请求',
                'invalid_reason': reason,
                'card_id': normalized,
                'source_update': state,
            }
        else:
            if source_url != str(snapshot or '').strip():
                # 先重置旧来源状态，再让现有检查逻辑建立新来源基线。
                prepare_source_link_for_card(
                    normalized,
                    source_link=source_url,
                    ui_data=data,
                )
            result = check_card_source_update(
                normalized,
                source_link=source_url,
                ui_data=data,
            )
    except Exception as exc:
        logger.warning('监控池检查角色卡失败 %s: %s', normalized, exc)
        result = {
            'success': False,
            'status': 'error',
            'supported': True,
            'error': str(exc),
            'card_id': normalized,
            'source_update': get_source_update_state(data, _ui_key_for_card(normalized)),
        }
    finally:
        release_card_lock(lock)

    _with_connection(lambda conn: _record_entry_result(conn, normalized, result, pool_id=pool_id, now=now))
    return result


def record_monitor_check_result(card_id, result, *, pool_id=DEFAULT_MONITOR_POOL_ID, now=None):
    """把单卡检查结果同步到监控项；不存在监控项时保持无操作。"""
    normalized = _normalize_card_id(card_id)
    if not normalized:
        return False

    def operation(conn):
        if _entry_row(conn, normalized, pool_id) is None:
            return False
        _record_entry_result(conn, normalized, result, pool_id=pool_id, now=now)
        return True

    return bool(_with_connection(operation))


class _MonitorReadConnection:
    """让监控检查只短暂持有数据库连接，避免网络请求期间占用 SQLite。"""

    def __enter__(self):
        self.conn = _connect()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if self.conn is not None:
            if exc_type:
                self.conn.rollback()
            self.conn.close()
        return False


def list_monitor_entries(*, pool_id=DEFAULT_MONITOR_POOL_ID):
    ui_data = load_ui_data()

    def operation(conn):
        current = _serialize_run(_active_run(conn, pool_id))
        rows = conn.execute(
            '''
            SELECT * FROM source_update_monitor_entries
            WHERE pool_id = ? ORDER BY added_at, card_id
            ''',
            (pool_id,),
        ).fetchall()
        return [_build_entry_payload(row, conn, ui_data, current) for row in rows]

    return _with_connection(operation)


def get_monitor_status(*, pool_id=DEFAULT_MONITOR_POOL_ID):
    def operation(conn):
        pool = _pool_row(conn, pool_id)
        ui_data = load_ui_data()
        current = _serialize_run(_active_run(conn, pool_id))
        rows = conn.execute(
            '''
            SELECT * FROM source_update_monitor_entries
            WHERE pool_id = ? ORDER BY added_at, card_id
            ''',
            (pool_id,),
        ).fetchall()
        entries = [_build_entry_payload(row, conn, ui_data, current) for row in rows]
        enabled_entries = [item for item in entries if item['enabled']]
        valid_count = sum(item['exists'] and item['supported'] for item in enabled_entries)
        invalid_count = len(enabled_entries) - valid_count
        pending_count = sum(item['pending_update'] for item in entries)
        last_row = conn.execute(
            '''
            SELECT * FROM source_update_monitor_runs
            WHERE pool_id = ? AND status IN ('completed', 'failed', 'cancelled', 'aborted')
            ORDER BY finished_at DESC, started_at DESC LIMIT 1
            ''',
            (pool_id,),
        ).fetchone()
        return {
            'pool_id': pool['pool_id'],
            'name': pool['name'] or DEFAULT_MONITOR_POOL_NAME,
            'enabled': bool(pool['enabled']),
            'schedule_mode': pool['schedule_mode'] or 'manual',
            'daily_time': pool['daily_time'] or '',
            'timezone': pool['timezone'] or '',
            'next_run_at': pool['next_run_at'],
            'last_run_at': pool['last_run_at'],
            'last_run_id': pool['last_run_id'] or '',
            'member_total': len(entries),
            'valid_members': int(valid_count),
            'invalid_members': int(invalid_count),
            'pending_count': int(pending_count),
            'current_run': current,
            'last_run': _serialize_run(last_row),
            'last_run_summary': _serialize_run(last_row).get('summary', {}) if last_row else None,
        }

    return _with_connection(operation)


def _timezone_for_name(name):
    value = str(name or '').strip()
    if not value:
        return datetime.now().astimezone().tzinfo
    if ZoneInfo is None:
        raise ValueError('当前 Python 不支持时区设置')
    try:
        return ZoneInfo(value)
    except (KeyError, ValueError):
        raise ValueError('无效的时区设置')


def _next_daily_run(daily_time, timezone_name, now=None):
    if not DAILY_TIME_RE.fullmatch(str(daily_time or '')):
        raise ValueError('每日检查时间必须是 HH:MM 格式')
    tz = _timezone_for_name(timezone_name)
    current = datetime.fromtimestamp(float(now if now is not None else time.time()), tz=tz)
    hour, minute = [int(item) for item in daily_time.split(':')]
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.timestamp()


def update_monitor_settings(payload, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    data = payload if isinstance(payload, dict) else {}
    enabled = _coerce_bool(data.get('enabled'), default=False)
    schedule_mode = str(data.get('schedule_mode') or 'manual').strip().lower()
    if schedule_mode not in VALID_SCHEDULE_MODES:
        return {'success': False, 'status': 'invalid_settings', 'error': '不支持的调度模式'}

    daily_time = str(data.get('daily_time') or '').strip()
    timezone_name = str(data.get('timezone') or '').strip()
    next_run_at = None
    if schedule_mode == 'daily':
        if not DAILY_TIME_RE.fullmatch(daily_time):
            return {'success': False, 'status': 'invalid_settings', 'error': '每日检查时间必须是 HH:MM 格式'}
        try:
            next_run_at = _next_daily_run(daily_time, timezone_name)
        except ValueError as exc:
            return {'success': False, 'status': 'invalid_settings', 'error': str(exc)}
    else:
        daily_time = daily_time if DAILY_TIME_RE.fullmatch(daily_time) else ''

    def operation(conn):
        _pool_row(conn, pool_id)
        now = time.time()
        conn.execute(
            '''
            UPDATE source_update_monitor_pools
            SET enabled = ?, schedule_mode = ?, daily_time = ?, timezone = ?,
                next_run_at = ?, updated_at = ?
            WHERE pool_id = ?
            ''',
            (
                1 if enabled else 0,
                schedule_mode,
                daily_time or None,
                timezone_name or None,
                next_run_at,
                now,
                pool_id,
            ),
        )
        return dict(conn.execute(
            'SELECT * FROM source_update_monitor_pools WHERE pool_id = ?',
            (pool_id,),
        ).fetchone())

    row = _with_connection(operation)
    row.update({
        'success': True,
        'enabled': bool(row.get('enabled')),
        'daily_time': row.get('daily_time') or '',
        'timezone': row.get('timezone') or '',
    })
    return row


def _freeze_targets(conn, pool_id, card_ids=None):
    if card_ids is None:
        rows = conn.execute(
            '''
            SELECT card_id FROM source_update_monitor_entries
            WHERE pool_id = ? AND enabled = 1 ORDER BY added_at, card_id
            ''',
            (pool_id,),
        ).fetchall()
        return [row['card_id'] for row in rows]

    requested = _normalize_card_ids(card_ids)
    if not requested:
        return []
    placeholders = ','.join('?' for _ in requested)
    rows = conn.execute(
        f'''
        SELECT card_id FROM source_update_monitor_entries
        WHERE pool_id = ? AND enabled = 1 AND card_id IN ({placeholders})
        ''',
        [pool_id, *requested],
    ).fetchall()
    available = {row['card_id'] for row in rows}
    return [card_id for card_id in requested if card_id in available]


def create_monitor_run(
    *,
    pool_id=DEFAULT_MONITOR_POOL_ID,
    trigger='manual',
    card_ids=None,
    execute=False,
):
    """创建冻结目标的运行记录；``execute`` 为 True 时交给 daemon worker。"""
    trigger = str(trigger or 'manual').strip() or 'manual'

    def operation(conn):
        conn.execute('BEGIN IMMEDIATE')
        _pool_row(conn, pool_id)
        active = _active_run(conn, pool_id)
        if active is not None:
            conn.rollback()
            return {
                'success': False,
                'status': 'already_running',
                'run': _serialize_run(active),
                'card_ids': [],
            }
        targets = _freeze_targets(conn, pool_id, card_ids)
        run_id = uuid.uuid4().hex
        now = time.time()
        summary = _empty_summary(len(targets))
        status = 'running' if targets else 'completed'
        conn.execute(
            '''
            INSERT INTO source_update_monitor_runs
                (run_id, pool_id, trigger, status, started_at, finished_at,
                 total, completed, current_card_id, summary_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?, '')
            ''',
            (
                run_id,
                pool_id,
                trigger,
                status,
                now,
                None if targets else now,
                len(targets),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        row = _run_row(conn, run_id)
        return {
            'success': True,
            'status': status,
            'run': _serialize_run(row),
            'card_ids': targets,
        }

    result = _with_connection(operation)
    if result.get('success') and result.get('status') == 'running':
        with _active_pool_guard:
            _active_pool_ids.add(pool_id)
        if execute:
            worker = threading.Thread(
                target=_run_monitor_run,
                args=(result['run']['run_id'], pool_id, result['card_ids']),
                name=f'source-monitor-{pool_id}',
                daemon=True,
            )
            worker.start()
    return result


def _update_run_current(run_id, card_id):
    def operation(conn):
        conn.execute(
            '''
            UPDATE source_update_monitor_runs
            SET status = 'running', current_card_id = ?
            WHERE run_id = ? AND status = 'running'
            ''',
            (card_id, run_id),
        )

    _with_connection(operation)


def _record_run_progress(run_id, pool_id, card_id, result, completed=None):
    def operation(conn):
        row = _run_row(conn, run_id)
        if row is None or row['status'] not in ACTIVE_RUN_STATUSES:
            return None
        _record_entry_result(conn, card_id, result, pool_id=pool_id)
        try:
            summary = json.loads(row['summary_json'] or '{}')
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = _empty_summary(row['total'])
        if not summary:
            summary = _empty_summary(row['total'])
        _add_result_to_summary(summary, result)
        next_completed = int(completed if completed is not None else summary['completed'])
        summary['completed'] = max(summary.get('completed', 0), next_completed)
        conn.execute(
            '''
            UPDATE source_update_monitor_runs
            SET completed = ?, current_card_id = ?, summary_json = ?
            WHERE run_id = ? AND status IN ('queued', 'running')
            ''',
            (
                next_completed,
                card_id,
                json.dumps(summary, ensure_ascii=False),
                run_id,
            ),
        )
        return summary

    return _with_connection(operation)


def complete_monitor_run(run_id, *, summary=None, status='completed', error=''):
    final_status = status if status in TERMINAL_RUN_STATUSES else 'completed'

    def operation(conn):
        row = _run_row(conn, run_id)
        if row is None:
            return {'success': False, 'status': 'not_found', 'error': '找不到监控任务'}
        if row['status'] in TERMINAL_RUN_STATUSES:
            return {'success': True, 'status': row['status'], 'run': _serialize_run(row)}
        try:
            current_summary = json.loads(row['summary_json'] or '{}')
        except (TypeError, ValueError, json.JSONDecodeError):
            current_summary = _empty_summary(row['total'])
        if isinstance(summary, dict):
            current_summary.update({key: value for key, value in summary.items() if value is not None})
        current_summary['total'] = int(row['total'] or current_summary.get('total') or 0)
        current_summary['selected'] = current_summary['total']
        current_summary['completed'] = int(row['completed'] or current_summary.get('completed') or 0)
        now = time.time()
        conn.execute(
            '''
            UPDATE source_update_monitor_runs
            SET status = ?, finished_at = ?, current_card_id = NULL,
                completed = ?, summary_json = ?, error = ?
            WHERE run_id = ? AND status IN ('queued', 'running')
            ''',
            (
                final_status,
                now,
                current_summary['completed'],
                json.dumps(current_summary, ensure_ascii=False),
                str(error or ''),
                run_id,
            ),
        )
        updated = _run_row(conn, run_id)
        conn.execute(
            '''
            UPDATE source_update_monitor_pools
            SET last_run_at = ?, last_run_id = ?, updated_at = ?
            WHERE pool_id = ?
            ''',
            (now, run_id, now, row['pool_id']),
        )
        return {'success': True, 'status': final_status, 'run': _serialize_run(updated)}

    result = _with_connection(operation)
    with _active_pool_guard:
        if result.get('run'):
            _active_pool_ids.discard(result['run']['pool_id'])
    return result


def cancel_monitor_run(run_id):
    def operation(conn):
        row = _run_row(conn, run_id)
        if row is None:
            return {'success': False, 'status': 'not_found', 'error': '找不到监控任务'}
        if row['status'] not in ACTIVE_RUN_STATUSES:
            return {'success': True, 'status': row['status'], 'run': _serialize_run(row)}
        now = time.time()
        conn.execute(
            '''
            UPDATE source_update_monitor_runs
            SET status = 'cancelled', finished_at = ?, current_card_id = NULL,
                error = '用户取消了后续检查'
            WHERE run_id = ? AND status IN ('queued', 'running')
            ''',
            (now, run_id),
        )
        updated = _run_row(conn, run_id)
        conn.execute(
            'UPDATE source_update_monitor_pools SET last_run_at = ?, last_run_id = ?, updated_at = ? WHERE pool_id = ?',
            (now, run_id, now, row['pool_id']),
        )
        return {'success': True, 'status': 'cancelled', 'run': _serialize_run(updated)}

    result = _with_connection(operation)
    with _active_pool_guard:
        if result.get('run'):
            _active_pool_ids.discard(result['run']['pool_id'])
    return result


def get_monitor_run(run_id):
    def operation(conn):
        row = _run_row(conn, str(run_id or '').strip())
        if row is None:
            return None
        return _serialize_run(row)

    return _with_connection(operation)


def record_monitor_run_item(run_id, card_id, result, *, completed=None):
    if not isinstance(result, dict):
        result = {
            'success': False,
            'status': 'error',
            'error': '检查返回了无效结果',
            'card_id': card_id,
        }
    run = get_monitor_run(run_id)
    if not run:
        return {'success': False, 'status': 'not_found', 'error': '找不到监控任务'}
    summary = _record_run_progress(
        run_id,
        run['pool_id'],
        _normalize_card_id(card_id),
        result,
        completed=completed,
    )
    return {'success': summary is not None, 'summary': summary or {}, 'run_id': run_id}


def check_monitor_pool_sync(card_ids=None, *, pool_id=DEFAULT_MONITOR_POOL_ID):
    """供兼容 check_batch 接口使用的顺序监控池检查。"""
    targets = _normalize_card_ids(card_ids) if card_ids is not None else get_monitor_target_ids(pool_id=pool_id)
    summary = _empty_summary(len(targets))
    details = []
    for card_id in targets:
        try:
            result = check_monitored_card(card_id, pool_id=pool_id)
        except Exception as exc:
            logger.warning('监控池批量检查跳过 %s: %s', card_id, exc)
            result = {
                'success': False,
                'status': 'error',
                'supported': True,
                'error': str(exc),
                'card_id': card_id,
            }
        summary = _add_result_to_summary(summary, result)
        details.append({
            'card_id': card_id,
            'success': bool(result.get('success')),
            'supported': bool(result.get('supported')),
            'status': result.get('status', 'error'),
            'changed': bool(result.get('changed')),
            'pending': bool((result.get('source_update') or {}).get('pending_update')),
            'message': result.get('message') or result.get('error', ''),
        })
    return {**summary, 'details': details, 'success': True}


def _run_monitor_run(run_id, pool_id, card_ids):
    summary = _empty_summary(len(card_ids))
    try:
        for card_id in card_ids:
            run = get_monitor_run(run_id)
            if not run or run['status'] != 'running':
                break
            _update_run_current(run_id, card_id)
            try:
                result = check_monitored_card(card_id, pool_id=pool_id)
            except Exception as exc:
                logger.warning('后台监控检查跳过 %s: %s', card_id, exc)
                result = {
                    'success': False,
                    'status': 'error',
                    'supported': True,
                    'error': str(exc),
                    'card_id': card_id,
                }
            summary = _add_result_to_summary(summary, result)
            _record_run_progress(run_id, pool_id, card_id, result, completed=summary['completed'])
        run = get_monitor_run(run_id)
        if run and run['status'] == 'running':
            complete_monitor_run(run_id, summary=summary, status='completed')
    except Exception as exc:
        logger.exception('后台监控任务异常: %s', run_id)
        complete_monitor_run(run_id, summary=summary, status='failed', error=str(exc))
    finally:
        with _active_pool_guard:
            _active_pool_ids.discard(pool_id)


def _set_next_run_at(pool_id, daily_time, timezone_name):
    try:
        next_run = _next_daily_run(daily_time, timezone_name)
    except ValueError:
        logger.warning('监控池 %s 的下次运行时间无效', pool_id)
        return

    def operation(conn):
        conn.execute(
            'UPDATE source_update_monitor_pools SET next_run_at = ?, updated_at = ? WHERE pool_id = ?',
            (next_run, time.time(), pool_id),
        )

    _with_connection(operation)


def _run_due_scheduled_pools():
    now = time.time()

    def operation(conn):
        rows = conn.execute(
            '''
            SELECT * FROM source_update_monitor_pools
            WHERE enabled = 1 AND schedule_mode = 'daily'
            ''',
        ).fetchall()
        return [dict(row) for row in rows]

    pools = _with_connection(operation)
    for pool in pools:
        if not pool.get('next_run_at'):
            _set_next_run_at(pool['pool_id'], pool.get('daily_time') or '', pool.get('timezone') or '')
            continue
        if float(pool['next_run_at']) > now:
            continue
        with _active_pool_guard:
            if pool['pool_id'] in _active_pool_ids:
                continue
        result = create_monitor_run(
            pool_id=pool['pool_id'],
            trigger='scheduled',
            execute=True,
        )
        if result.get('success'):
            _set_next_run_at(pool['pool_id'], pool.get('daily_time') or '', pool.get('timezone') or '')


def _scheduler_loop():
    logger.info('角色卡来源监控调度器已启动')
    while not _scheduler_stop.is_set():
        try:
            _run_due_scheduled_pools()
        except Exception:
            logger.exception('角色卡来源监控调度轮询失败')
        _scheduler_stop.wait(SCHEDULER_INTERVAL_SECONDS)


def start_monitor_scheduler():
    """启动幂等 daemon 调度线程。"""
    global _scheduler_thread
    with _scheduler_guard:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return _scheduler_thread
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name='source-update-monitor-scheduler',
            daemon=True,
        )
        _scheduler_thread.start()
        return _scheduler_thread


def stop_monitor_scheduler():
    """测试和应用重载使用的停止入口；生产流程不依赖它。"""
    _scheduler_stop.set()
