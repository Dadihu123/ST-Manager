import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

from core.config import BASE_DIR, CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.source_update_monitor_store import ensure_source_update_monitor_schema
from core.services.card_index_sync_service import sync_card_index_jobs
from core.services.card_service import _apply_card_index_increment_now as _card_apply_card_index_increment_now
from core.services.wi_entry_history_service import get_history_limit
from core.utils.card_identity import normalize_card_uid


logger = logging.getLogger(__name__)

BACKUP_DIR = os.path.join('data', 'system', 'backups', 'user_db')
MONITOR_BACKUP_KEY = 'source_update_monitor'
MONITOR_SCHEDULE_MODES = frozenset({'manual', 'daily'})
MONITOR_DAILY_TIME_RE = re.compile(r'^(?:[01]\d|2[0-3]):[0-5]\d$')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _timestamp_for_file() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _apply_card_index_increment_now(card_id, source_path):
    _card_apply_card_index_increment_now(card_id, source_path)


class UserDbBackupService:
    def _table_exists(self, conn, table_name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _table_columns(self, conn, table_name):
        if not self._table_exists(conn, table_name):
            return set()
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table_name})').fetchall()}

    @staticmethod
    def _normalize_monitor_pool_id(value):
        normalized = str(value or '').strip()
        if not normalized or len(normalized) > 128:
            return ''
        if any(ord(char) < 32 for char in normalized):
            return ''
        return normalized

    @staticmethod
    def _normalize_monitor_card_id(value):
        normalized = str(value or '').strip().replace('\\', '/')
        if not normalized or normalized.startswith('/') or normalized in {'.', '..'}:
            return ''
        if '\x00' in normalized or any(part in {'', '.', '..'} for part in normalized.split('/')):
            return ''
        drive, _ = os.path.splitdrive(normalized)
        if drive or re.match(r'^[A-Za-z]:', normalized):
            return ''
        return normalized

    @staticmethod
    def _optional_timestamp(value):
        if value in (None, ''):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError('监控池时间字段格式无效')

    @staticmethod
    def _backup_bool(value, field_name):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        raise ValueError(f'{field_name} 必须是布尔值')

    def _current_card_uid(self, conn, card_id, stored_uid=''):
        """按现有缓存和数据库身份解析角色卡 UUID，兼容普通卡片与 Bundle。"""
        cache = getattr(ctx, 'cache', None)
        id_map = getattr(cache, 'id_map', None)
        if isinstance(id_map, dict):
            cache_item = id_map.get(card_id)
            if isinstance(cache_item, dict):
                cache_uid = normalize_card_uid(cache_item.get('card_uid'))
                if cache_uid:
                    return cache_uid

        normalized_stored_uid = normalize_card_uid(stored_uid)
        if normalized_stored_uid:
            return normalized_stored_uid

        if self._table_exists(conn, 'card_metadata') and 'card_uid' in self._table_columns(conn, 'card_metadata'):
            row = conn.execute(
                'SELECT card_uid FROM card_metadata WHERE id = ?',
                (card_id,),
            ).fetchone()
            if row is not None:
                return normalize_card_uid(row['card_uid'])
        return ''

    def _read_history_rows(self, conn):
        if not self._table_exists(conn, 'wi_entry_history'):
            return []
        return [
            {
                'scope_key': row['scope_key'],
                'entry_uid': row['entry_uid'],
                'snapshot_json': row['snapshot_json'],
                'snapshot_hash': row['snapshot_hash'],
                'created_at': row['created_at'],
            }
            for row in conn.execute(
                '''
                SELECT scope_key, entry_uid, snapshot_json, snapshot_hash, created_at
                FROM wi_entry_history
                ORDER BY created_at ASC, id ASC
                '''
            ).fetchall()
        ]

    def _read_monitor_backup(self, conn):
        pool_columns = self._table_columns(conn, 'source_update_monitor_pools')
        entry_columns = self._table_columns(conn, 'source_update_monitor_entries')
        required_pool_columns = {
            'pool_id', 'name', 'enabled', 'schedule_mode', 'daily_time', 'timezone',
        }
        required_entry_columns = {
            'pool_id', 'card_id', 'source_url_snapshot', 'enabled', 'added_at',
            'last_seen_source_url',
        }
        if not required_pool_columns.issubset(pool_columns) or not required_entry_columns.issubset(entry_columns):
            return None

        has_card_metadata = self._table_exists(conn, 'card_metadata')
        has_metadata_uid = has_card_metadata and 'card_uid' in self._table_columns(conn, 'card_metadata')
        monitor_uid_expr = 'e.card_uid' if 'card_uid' in entry_columns else "''"
        metadata_uid_expr = 'c.card_uid' if has_metadata_uid else "''"
        card_join = 'LEFT JOIN card_metadata AS c ON c.id = e.card_id' if has_card_metadata else ''
        entries = []
        for row in conn.execute(
            f'''
            SELECT e.pool_id, e.card_id, {monitor_uid_expr} AS monitor_card_uid,
                   {metadata_uid_expr} AS metadata_card_uid, e.source_url_snapshot,
                   e.enabled, e.added_at, e.last_seen_source_url
            FROM source_update_monitor_entries AS e
            {card_join}
            ORDER BY e.pool_id, e.added_at, e.card_id
            '''
        ).fetchall():
            entries.append(
                {
                    'pool_id': str(row['pool_id'] or '').strip(),
                    'card_id': self._normalize_monitor_card_id(row['card_id']),
                    'card_uid': self._current_card_uid(
                        conn,
                        row['card_id'],
                        stored_uid=(
                            normalize_card_uid(row['monitor_card_uid'])
                            or normalize_card_uid(row['metadata_card_uid'])
                        ),
                    ),
                    'source_url_snapshot': str(row['source_url_snapshot'] or '').strip(),
                    'enabled': bool(row['enabled']),
                    'added_at': row['added_at'],
                    'last_seen_source_url': str(row['last_seen_source_url'] or '').strip(),
                }
            )

        pools = [
            {
                'pool_id': str(row['pool_id'] or '').strip(),
                'name': str(row['name'] or '').strip(),
                'enabled': bool(row['enabled']),
                'schedule_mode': str(row['schedule_mode'] or 'manual').strip().lower(),
                'daily_time': str(row['daily_time'] or '').strip(),
                'timezone': str(row['timezone'] or '').strip(),
            }
            for row in conn.execute(
                '''
                SELECT pool_id, name, enabled, schedule_mode, daily_time, timezone
                FROM source_update_monitor_pools
                ORDER BY pool_id
                '''
            ).fetchall()
        ]
        return {'pools': pools, 'entries': entries}

    def export_backup(self):
        file_name = f'user_db_backup_{_timestamp_for_file()}.json'
        relative_path = os.path.join(BACKUP_DIR, file_name).replace('\\', '/')
        full_path = os.path.join(BASE_DIR, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            favorites = [
                {
                    'card_id': row['id'],
                    'is_favorite': bool(row['is_favorite']),
                }
                for row in conn.execute(
                    'SELECT id, is_favorite FROM card_metadata WHERE is_favorite = 1 ORDER BY id ASC'
                ).fetchall()
            ]
            wi_clipboard = [
                {
                    'content': json.loads(row['content_json']),
                    'sort_order': row['sort_order'],
                    'created_at': row['created_at'],
                }
                for row in conn.execute(
                    'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC'
                ).fetchall()
            ]
            wi_entry_history = self._read_history_rows(conn)
            monitor_data = self._read_monitor_backup(conn)

        backup_data = {
            'favorites': favorites,
            'wi_clipboard': wi_clipboard,
            'wi_entry_history': wi_entry_history,
        }
        stats = {
            'favorites': len(favorites),
            'wi_clipboard': len(wi_clipboard),
            'wi_entry_history': len(wi_entry_history),
        }
        if monitor_data is not None:
            backup_data[MONITOR_BACKUP_KEY] = monitor_data
            stats[MONITOR_BACKUP_KEY] = {
                'pools': len(monitor_data['pools']),
                'entries': len(monitor_data['entries']),
            }

        payload = {
            'schema_version': 1,
            'exported_at': _utc_now_iso(),
            'app': 'ST-Manager',
            'data': backup_data,
        }
        with open(full_path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

        return {
            'file_name': file_name,
            'file_path': relative_path,
            'stats': stats,
        }

    def import_backup(self, source_path, source_name=''):
        payload = self._load_backup_payload(source_path)
        data = payload.get('data') or {}
        favorites = self._validate_favorites(data.get('favorites'))
        wi_clipboard = self._validate_clipboard(data.get('wi_clipboard'))
        wi_entry_history = self._validate_history(data.get('wi_entry_history'))
        monitor_data = (
            self._validate_monitor_backup(data.get(MONITOR_BACKUP_KEY))
            if MONITOR_BACKUP_KEY in data else None
        )
        if monitor_data is not None:
            self._ensure_monitor_schema()

        favorite_changes = []
        rollback_snapshot = self._snapshot_db_only_state()
        stats = {
            'favorites': {
                'imported': 0,
                'skipped_missing_cards': 0,
                'unchanged': 0,
            },
            'wi_clipboard': {
                'imported': 0,
                'deduplicated': 0,
            },
            'wi_entry_history': {
                'imported': 0,
                'deduplicated': 0,
                'trimmed': 0,
            },
        }
        if monitor_data is not None:
            stats[MONITOR_BACKUP_KEY] = {
                'pools': {'imported': 0, 'unchanged': 0},
                'entries': {
                    'imported': 0,
                    'unchanged': 0,
                    'skipped_missing_cards': 0,
                },
            }

        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('BEGIN')
            has_history_table = self._table_exists(conn, 'wi_entry_history')

            for item in favorites:
                row = cursor.execute(
                    'SELECT is_favorite FROM card_metadata WHERE id = ?',
                    (item['card_id'],),
                ).fetchone()
                if row is None:
                    stats['favorites']['skipped_missing_cards'] += 1
                    continue
                new_value = 1 if item['is_favorite'] else 0
                old_value = 1 if row['is_favorite'] else 0
                if old_value == new_value:
                    stats['favorites']['unchanged'] += 1
                    continue
                cursor.execute(
                    'UPDATE card_metadata SET is_favorite = ? WHERE id = ?',
                    (new_value, item['card_id']),
                )
                favorite_changes.append(
                    {
                        'card_id': item['card_id'],
                        'old_value': bool(old_value),
                        'new_value': bool(new_value),
                    }
                )
                stats['favorites']['imported'] += 1

            existing_clipboard = set()
            for row in cursor.execute('SELECT content_json FROM wi_clipboard').fetchall():
                try:
                    existing_clipboard.add(_stable_json(json.loads(row['content_json'])))
                except (TypeError, ValueError, json.JSONDecodeError):
                    existing_clipboard.add(str(row['content_json']))
            next_sort_order_row = cursor.execute(
                'SELECT COALESCE(MAX(sort_order), -1) AS max_sort_order FROM wi_clipboard'
            ).fetchone()
            next_sort_order = int(next_sort_order_row['max_sort_order']) + 1
            for item in wi_clipboard:
                content_key = _stable_json(item['content'])
                if content_key in existing_clipboard:
                    stats['wi_clipboard']['deduplicated'] += 1
                    continue
                content_json = json.dumps(item['content'], ensure_ascii=False)
                cursor.execute(
                    'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
                    (content_json, next_sort_order, item['created_at']),
                )
                existing_clipboard.add(content_key)
                stats['wi_clipboard']['imported'] += 1
                next_sort_order += 1

            clipboard_rows = cursor.execute(
                'SELECT id FROM wi_clipboard ORDER BY sort_order ASC, id ASC'
            ).fetchall()
            for index, row in enumerate(clipboard_rows):
                cursor.execute(
                    'UPDATE wi_clipboard SET sort_order = ? WHERE id = ?',
                    (index, row['id']),
                )

            if has_history_table:
                existing_history = {
                    (row['scope_key'], row['entry_uid'], row['snapshot_hash'])
                    for row in cursor.execute(
                        'SELECT scope_key, entry_uid, snapshot_hash FROM wi_entry_history'
                    ).fetchall()
                }
                for item in wi_entry_history:
                    key = (item['scope_key'], item['entry_uid'], item['snapshot_hash'])
                    if key in existing_history:
                        stats['wi_entry_history']['deduplicated'] += 1
                        continue
                    cursor.execute(
                        '''
                        INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        ''',
                        (
                            item['scope_key'],
                            item['entry_uid'],
                            item['snapshot_json'],
                            item['snapshot_hash'],
                            item['created_at'],
                        ),
                    )
                    existing_history.add(key)
                    stats['wi_entry_history']['imported'] += 1

                history_limit = get_history_limit()
                history_groups = cursor.execute(
                    '''
                    SELECT scope_key, entry_uid
                    FROM wi_entry_history
                    GROUP BY scope_key, entry_uid
                    '''
                ).fetchall()
                for group in history_groups:
                    overflow = cursor.execute(
                        '''
                        SELECT id
                        FROM wi_entry_history
                        WHERE scope_key = ? AND entry_uid = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                        ''',
                        (group['scope_key'], group['entry_uid'], history_limit),
                    ).fetchall()
                    if not overflow:
                        continue
                    stats['wi_entry_history']['trimmed'] += len(overflow)
                    cursor.executemany(
                        'DELETE FROM wi_entry_history WHERE id = ?',
                        [(row['id'],) for row in overflow],
                    )

            if monitor_data is not None:
                self._import_monitor_backup(
                    conn,
                    monitor_data,
                    stats[MONITOR_BACKUP_KEY],
                )

            conn.commit()

        applied_favorite_changes = []
        try:
            for change in favorite_changes:
                card_id = change['card_id']
                source_file_path = self._resolve_card_source_path(card_id)
                change['source_path'] = source_file_path
                applied_favorite_changes.append(change)
                if ctx.cache:
                    ctx.cache.toggle_favorite_update(card_id, change['new_value'])
                sync_card_index_jobs(
                    card_id=card_id,
                    source_path=source_file_path,
                    favorite_changed=True,
                )
                _apply_card_index_increment_now(card_id, source_file_path)
        except Exception:
            self._restore_db_only_state(rollback_snapshot)
            self._restore_favorite_changes(favorite_changes, applied_favorite_changes)
            raise

        return {
            'source_name': source_name,
            'stats': stats,
        }

    def _ensure_monitor_schema(self):
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            ensure_source_update_monitor_schema(conn, recover_stale=False)

    def _validate_monitor_backup(self, raw_data):
        if not isinstance(raw_data, dict):
            raise ValueError(f'{MONITOR_BACKUP_KEY} 格式无效')

        raw_pools = raw_data.get('pools')
        raw_entries = raw_data.get('entries')
        if not isinstance(raw_pools, list) or not isinstance(raw_entries, list):
            raise ValueError(f'{MONITOR_BACKUP_KEY} 必须包含 pools 和 entries 数组')

        pools = []
        pool_ids = set()
        for item in raw_pools:
            if not isinstance(item, dict):
                raise ValueError('监控池配置格式无效')
            pool_id = self._normalize_monitor_pool_id(item.get('pool_id'))
            if not pool_id:
                raise ValueError('监控池配置缺少有效 pool_id')
            if pool_id in pool_ids:
                raise ValueError('监控池配置包含重复 pool_id')
            pool_ids.add(pool_id)

            schedule_mode = str(item.get('schedule_mode') or 'manual').strip().lower()
            if schedule_mode not in MONITOR_SCHEDULE_MODES:
                raise ValueError('监控池 schedule_mode 无效')
            daily_time = str(item.get('daily_time') or '').strip()
            if daily_time and not MONITOR_DAILY_TIME_RE.fullmatch(daily_time):
                raise ValueError('监控池 daily_time 格式无效')
            if schedule_mode == 'daily' and not MONITOR_DAILY_TIME_RE.fullmatch(daily_time):
                raise ValueError('每日监控池必须提供有效 daily_time')

            pools.append(
                {
                    'pool_id': pool_id,
                    'name': str(item.get('name') or '').strip(),
                    'enabled': self._backup_bool(item.get('enabled'), '监控池 enabled'),
                    'schedule_mode': schedule_mode,
                    'daily_time': daily_time,
                    'timezone': str(item.get('timezone') or '').strip(),
                }
            )

        entries_by_key = {}
        for item in raw_entries:
            if not isinstance(item, dict):
                raise ValueError('监控池成员格式无效')
            pool_id = self._normalize_monitor_pool_id(item.get('pool_id'))
            card_id = self._normalize_monitor_card_id(item.get('card_id'))
            raw_card_uid = item.get('card_uid')
            card_uid = normalize_card_uid(raw_card_uid)
            if raw_card_uid not in (None, '') and not card_uid:
                raise ValueError('监控池成员 card_uid 格式无效')
            if not pool_id or pool_id not in pool_ids:
                raise ValueError('监控池成员引用了不存在的 pool_id')
            if not card_id and not card_uid:
                raise ValueError('监控池成员缺少 card_uid 或 card_id')

            key = (pool_id, card_uid or card_id)
            entries_by_key[key] = {
                'pool_id': pool_id,
                'card_id': card_id,
                'card_uid': card_uid,
                'source_url_snapshot': str(item.get('source_url_snapshot') or '').strip(),
                'enabled': self._backup_bool(item.get('enabled'), '监控池成员 enabled'),
                'added_at': self._optional_timestamp(item.get('added_at')),
                'last_seen_source_url': str(item.get('last_seen_source_url') or '').strip(),
            }

        return {'pools': pools, 'entries': list(entries_by_key.values())}

    def _card_ids_by_uid(self, conn):
        metadata_columns = self._table_columns(conn, 'card_metadata')
        candidates = {}

        def add_candidate(card_uid, card_id):
            normalized_uid = normalize_card_uid(card_uid)
            normalized_id = self._normalize_monitor_card_id(card_id)
            if not normalized_uid or not normalized_id:
                return
            card_ids = candidates.setdefault(normalized_uid, [])
            if normalized_id not in card_ids:
                card_ids.append(normalized_id)

        if 'card_uid' in metadata_columns:
            for row in conn.execute('SELECT id, card_uid FROM card_metadata').fetchall():
                add_candidate(row['card_uid'], row['id'])

        cache = getattr(ctx, 'cache', None)
        id_map = getattr(cache, 'id_map', None)
        if isinstance(id_map, dict):
            for card_id, card in id_map.items():
                if isinstance(card, dict):
                    add_candidate(card.get('card_uid'), card_id)

        return {
            card_uid: card_ids[0]
            for card_uid, card_ids in candidates.items()
            if len(card_ids) == 1
        }

    def _import_monitor_backup(self, conn, monitor_data, monitor_stats):
        if not (
            self._table_exists(conn, 'source_update_monitor_pools')
            and self._table_exists(conn, 'source_update_monitor_entries')
        ):
            monitor_stats['pools']['unchanged'] = len(monitor_data['pools'])
            monitor_stats['entries']['skipped_missing_cards'] = len(monitor_data['entries'])
            return

        now = datetime.now(timezone.utc).timestamp()
        for item in monitor_data['pools']:
            existing = conn.execute(
                '''
                SELECT name, enabled, schedule_mode, daily_time, timezone
                FROM source_update_monitor_pools WHERE pool_id = ?
                ''',
                (item['pool_id'],),
            ).fetchone()
            desired = (
                item['name'],
                1 if item['enabled'] else 0,
                item['schedule_mode'],
                item['daily_time'] or None,
                item['timezone'] or None,
            )
            if existing is None:
                conn.execute(
                    '''
                    INSERT INTO source_update_monitor_pools
                        (pool_id, name, enabled, schedule_mode, daily_time, timezone,
                         next_run_at, last_run_at, last_run_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, '', ?, ?)
                    ''',
                    (item['pool_id'], *desired, now, now),
                )
                monitor_stats['pools']['imported'] += 1
                continue

            current = (
                str(existing['name'] or ''),
                1 if existing['enabled'] else 0,
                str(existing['schedule_mode'] or 'manual'),
                existing['daily_time'],
                existing['timezone'],
            )
            if current == desired:
                monitor_stats['pools']['unchanged'] += 1
                continue
            conn.execute(
                '''
                UPDATE source_update_monitor_pools
                SET name = ?, enabled = ?, schedule_mode = ?, daily_time = ?, timezone = ?,
                    next_run_at = NULL, updated_at = ?
                WHERE pool_id = ?
                ''',
                (*desired, now, item['pool_id']),
            )
            monitor_stats['pools']['imported'] += 1

        has_card_metadata = self._table_exists(conn, 'card_metadata')
        card_ids_by_uid = self._card_ids_by_uid(conn)
        for item in monitor_data['entries']:
            card_id = card_ids_by_uid.get(item['card_uid']) if item['card_uid'] else ''
            if not card_id and has_card_metadata:
                fallback_card_id = item['card_id']
                if fallback_card_id and conn.execute(
                    'SELECT 1 FROM card_metadata WHERE id = ?', (fallback_card_id,)
                ).fetchone() is not None:
                    card_id = fallback_card_id
            if not card_id:
                monitor_stats['entries']['skipped_missing_cards'] += 1
                continue

            card_uid = item['card_uid'] or self._current_card_uid(
                conn,
                card_id,
            )

            legacy_card_id = item['card_id']
            if legacy_card_id and legacy_card_id != card_id:
                old_entry = conn.execute(
                    '''
                    SELECT 1 FROM source_update_monitor_entries
                    WHERE pool_id = ? AND card_id = ?
                    ''',
                    (item['pool_id'], legacy_card_id),
                ).fetchone()
                current_entry = conn.execute(
                    '''
                    SELECT 1 FROM source_update_monitor_entries
                    WHERE pool_id = ? AND card_id = ?
                    ''',
                    (item['pool_id'], card_id),
                ).fetchone()
                if old_entry is not None:
                    if current_entry is not None:
                        conn.execute(
                            'DELETE FROM source_update_monitor_entries WHERE pool_id = ? AND card_id = ?',
                            (item['pool_id'], legacy_card_id),
                        )
                    else:
                        conn.execute(
                            '''
                            UPDATE source_update_monitor_entries
                            SET card_id = ?, card_uid = COALESCE(NULLIF(card_uid, ''), ?)
                            WHERE pool_id = ? AND card_id = ?
                            ''',
                            (card_id, card_uid or None, item['pool_id'], legacy_card_id),
                        )

            existing = conn.execute(
                '''
                SELECT source_url_snapshot, enabled, added_at, last_seen_source_url, card_uid
                FROM source_update_monitor_entries
                WHERE pool_id = ? AND card_id = ?
                ''',
                (item['pool_id'], card_id),
            ).fetchone()
            desired = (
                item['source_url_snapshot'],
                1 if item['enabled'] else 0,
                item['added_at'],
                item['last_seen_source_url'] or item['source_url_snapshot'],
            )
            if existing is None:
                conn.execute(
                    '''
                    INSERT INTO source_update_monitor_entries
                        (pool_id, card_id, card_uid, source_url_snapshot, enabled, added_at,
                         last_seen_source_url, last_run_status, last_run_at, last_error, invalid_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'never_checked', NULL, '', '')
                    ''',
                    (item['pool_id'], card_id, card_uid or None, *desired),
                )
                monitor_stats['entries']['imported'] += 1
                continue

            existing_card_uid = normalize_card_uid(existing['card_uid'])
            effective_card_uid = existing_card_uid or card_uid
            current = (
                str(existing['source_url_snapshot'] or ''),
                1 if existing['enabled'] else 0,
                existing['added_at'],
                str(existing['last_seen_source_url'] or ''),
                existing_card_uid,
            )
            desired_with_uid = (*desired, effective_card_uid)
            if current == desired_with_uid:
                monitor_stats['entries']['unchanged'] += 1
                continue
            conn.execute(
                '''
                UPDATE source_update_monitor_entries
                SET card_uid = COALESCE(NULLIF(card_uid, ''), ?),
                    source_url_snapshot = ?, enabled = ?, added_at = ?, last_seen_source_url = ?
                WHERE pool_id = ? AND card_id = ?
                ''',
                (card_uid or None, *desired, item['pool_id'], card_id),
            )
            monitor_stats['entries']['imported'] += 1

    def _load_backup_payload(self, source_path):
        try:
            with open(source_path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError('备份文件必须是合法 JSON') from exc

        if not isinstance(payload, dict):
            raise ValueError('备份文件必须是合法 JSON 对象')

        if payload.get('schema_version') != 1:
            raise ValueError('不支持的 schema_version')

        data = payload.get('data')
        if not isinstance(data, dict):
            raise ValueError('data 字段格式无效')
        return payload

    def _validate_favorites(self, items):
        if not isinstance(items, list):
            raise ValueError('favorites 必须是数组')
        validated = []
        for item in items:
            if not isinstance(item, dict) or 'card_id' not in item or 'is_favorite' not in item:
                raise ValueError('favorites 缺少必填字段')
            if not isinstance(item['is_favorite'], bool):
                raise ValueError('favorites.is_favorite 必须是布尔值')
            validated.append(
                {
                    'card_id': str(item['card_id']).strip(),
                    'is_favorite': item['is_favorite'],
                }
            )
        return validated

    def _validate_clipboard(self, items):
        if not isinstance(items, list):
            raise ValueError('wi_clipboard 必须是数组')
        validated = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('wi_clipboard 缺少必填字段')
            required = {'content', 'sort_order', 'created_at'}
            if not required.issubset(item.keys()):
                raise ValueError('wi_clipboard 缺少必填字段')
            validated.append(
                {
                    'content': item['content'],
                    'sort_order': int(item['sort_order']),
                    'created_at': float(item['created_at']),
                }
            )
        return validated

    def _validate_history(self, items):
        if not isinstance(items, list):
            raise ValueError('wi_entry_history 必须是数组')
        validated = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('wi_entry_history 缺少必填字段')
            required = {'scope_key', 'entry_uid', 'snapshot_json', 'snapshot_hash', 'created_at'}
            if not required.issubset(item.keys()):
                raise ValueError('wi_entry_history 缺少必填字段')
            validated.append(
                {
                    'scope_key': str(item['scope_key']),
                    'entry_uid': str(item['entry_uid']),
                    'snapshot_json': str(item['snapshot_json']),
                    'snapshot_hash': str(item['snapshot_hash']),
                    'created_at': float(item['created_at']),
                }
            )
        return validated

    def _resolve_card_source_path(self, card_id):
        return os.path.join(CARDS_FOLDER, str(card_id or '').replace('/', os.sep))

    def _snapshot_db_only_state(self):
        snapshot = {
            'favorites': [],
            'wi_clipboard': [],
            'wi_entry_history': [],
            'has_wi_entry_history_table': False,
            'monitor_pools': [],
            'monitor_entries': [],
            'has_monitor_pools_table': False,
            'has_monitor_entries_table': False,
        }

        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            snapshot['favorites'] = [
                {
                    'card_id': row['id'],
                    'is_favorite': 1 if row['is_favorite'] else 0,
                }
                for row in conn.execute('SELECT id, is_favorite FROM card_metadata ORDER BY id ASC').fetchall()
            ]
            snapshot['wi_clipboard'] = [
                {
                    'content_json': row['content_json'],
                    'sort_order': row['sort_order'],
                    'created_at': row['created_at'],
                }
                for row in conn.execute(
                    'SELECT content_json, sort_order, created_at FROM wi_clipboard ORDER BY sort_order ASC, id ASC'
                ).fetchall()
            ]
            snapshot['has_wi_entry_history_table'] = self._table_exists(conn, 'wi_entry_history')
            snapshot['wi_entry_history'] = self._read_history_rows(conn)
            snapshot['has_monitor_pools_table'] = self._table_exists(
                conn, 'source_update_monitor_pools'
            )
            snapshot['has_monitor_entries_table'] = self._table_exists(
                conn, 'source_update_monitor_entries'
            )
            if snapshot['has_monitor_pools_table']:
                snapshot['monitor_pools'] = [
                    dict(row)
                    for row in conn.execute(
                        'SELECT * FROM source_update_monitor_pools ORDER BY pool_id'
                    ).fetchall()
                ]
            if snapshot['has_monitor_entries_table']:
                snapshot['monitor_entries'] = [
                    dict(row)
                    for row in conn.execute(
                        '''
                        SELECT * FROM source_update_monitor_entries
                        ORDER BY pool_id, added_at, card_id
                        '''
                    ).fetchall()
                ]

        return snapshot

    def _restore_db_only_state(self, snapshot):
        if not snapshot:
            return

        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN')
            has_history_table = self._table_exists(conn, 'wi_entry_history')

            cursor.execute('DELETE FROM wi_clipboard')
            if snapshot.get('has_wi_entry_history_table') and has_history_table:
                cursor.execute('DELETE FROM wi_entry_history')
            for favorite in snapshot.get('favorites', []):
                cursor.execute(
                    'UPDATE card_metadata SET is_favorite = ? WHERE id = ?',
                    (favorite['is_favorite'], favorite['card_id']),
                )
            for row in snapshot.get('wi_clipboard', []):
                cursor.execute(
                    'INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)',
                    (row['content_json'], row['sort_order'], row['created_at']),
                )
            if snapshot.get('has_wi_entry_history_table') and has_history_table:
                for row in snapshot.get('wi_entry_history', []):
                    cursor.execute(
                        '''
                        INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        ''',
                        (
                            row['scope_key'],
                            row['entry_uid'],
                            row['snapshot_json'],
                            row['snapshot_hash'],
                            row['created_at'],
                        ),
                    )

            has_monitor_pools_table = self._table_exists(conn, 'source_update_monitor_pools')
            has_monitor_entries_table = self._table_exists(conn, 'source_update_monitor_entries')
            if snapshot.get('has_monitor_entries_table') and has_monitor_entries_table:
                cursor.execute('DELETE FROM source_update_monitor_entries')
            if snapshot.get('has_monitor_pools_table') and has_monitor_pools_table:
                cursor.execute('DELETE FROM source_update_monitor_pools')

            if snapshot.get('has_monitor_pools_table') and has_monitor_pools_table:
                for row in snapshot.get('monitor_pools', []):
                    cursor.execute(
                        '''
                        INSERT INTO source_update_monitor_pools
                            (pool_id, name, enabled, schedule_mode, daily_time, timezone,
                             next_run_at, last_run_at, last_run_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            row.get('pool_id'),
                            row.get('name'),
                            row.get('enabled'),
                            row.get('schedule_mode'),
                            row.get('daily_time'),
                            row.get('timezone'),
                            row.get('next_run_at'),
                            row.get('last_run_at'),
                            row.get('last_run_id'),
                            row.get('created_at'),
                            row.get('updated_at'),
                        ),
                    )
            if snapshot.get('has_monitor_entries_table') and has_monitor_entries_table:
                monitor_entry_columns = self._table_columns(
                    conn,
                    'source_update_monitor_entries',
                )
                if 'card_uid' in monitor_entry_columns:
                    entry_insert_sql = '''
                        INSERT INTO source_update_monitor_entries
                            (pool_id, card_id, card_uid, source_url_snapshot, enabled, added_at,
                             last_seen_source_url, last_run_status, last_run_at, last_error, invalid_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                else:
                    entry_insert_sql = '''
                        INSERT INTO source_update_monitor_entries
                            (pool_id, card_id, source_url_snapshot, enabled, added_at,
                             last_seen_source_url, last_run_status, last_run_at, last_error, invalid_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                for row in snapshot.get('monitor_entries', []):
                    entry_values = (
                        row.get('pool_id'),
                        row.get('card_id'),
                        row.get('card_uid'),
                        row.get('source_url_snapshot'),
                        row.get('enabled'),
                        row.get('added_at'),
                        row.get('last_seen_source_url'),
                        row.get('last_run_status'),
                        row.get('last_run_at'),
                        row.get('last_error'),
                        row.get('invalid_reason'),
                    )
                    if 'card_uid' not in monitor_entry_columns:
                        entry_values = entry_values[:2] + entry_values[3:]
                    cursor.execute(entry_insert_sql, entry_values)

            conn.commit()

    def _restore_favorite_changes(self, favorite_changes, applied_favorite_changes):
        if not favorite_changes:
            return

        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            for change in favorite_changes:
                cursor.execute(
                    'UPDATE card_metadata SET is_favorite = ? WHERE id = ?',
                    (1 if change['old_value'] else 0, change['card_id']),
                )
            conn.commit()

        for change in favorite_changes:
            if ctx.cache:
                try:
                    ctx.cache.toggle_favorite_update(change['card_id'], change['old_value'])
                except Exception:
                    logger.warning('Restore favorite cache state failed for %s', change['card_id'])

        for change in reversed(applied_favorite_changes):
            try:
                sync_card_index_jobs(
                    card_id=change['card_id'],
                    source_path=change.get('source_path', ''),
                    favorite_changed=True,
                )
                _apply_card_index_increment_now(change['card_id'], change.get('source_path', ''))
            except Exception:
                logger.warning('Restore favorite index state failed for %s', change['card_id'])
