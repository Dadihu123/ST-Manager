import os
import json
import time
import uuid
import hashlib
import logging
import sqlite3

from core.config import BASE_DIR, DEFAULT_DB_PATH, load_config

logger = logging.getLogger(__name__)

ENTRY_UID_FIELD = 'st_manager_uid'
DEFAULT_HISTORY_LIMIT = 7
MAX_HISTORY_LIMIT = 100


def _ensure_table(conn):
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wi_entry_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope_key TEXT NOT NULL,
            entry_uid TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_wi_entry_history_scope_uid_time
        ON wi_entry_history(scope_key, entry_uid, created_at DESC, id DESC)
    ''')


def _normalize_path(file_path: str) -> str:
    if not file_path:
        return ''
    path = file_path
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return os.path.normpath(path).replace('\\', '/')


def build_scope_key(source_type: str, source_id: str = '', file_path: str = '') -> str:
    stype = str(source_type or '').strip().lower() or 'unknown'
    sid = str(source_id or '').strip().replace('\\', '/')
    npath = _normalize_path(file_path)
    if npath:
        raw = f'{stype}|{npath}'
    else:
        raw = f'{stype}|{sid}|'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def get_history_limit(limit=None) -> int:
    if limit is None:
        cfg = load_config()
        limit = cfg.get('wi_entry_history_limit', DEFAULT_HISTORY_LIMIT)
    try:
        num = int(limit)
    except Exception:
        num = DEFAULT_HISTORY_LIMIT
    return max(1, min(num, MAX_HISTORY_LIMIT))


def _get_entries_ref(book_data):
    if isinstance(book_data, list):
        return [e for e in book_data if isinstance(e, dict)]
    if not isinstance(book_data, dict):
        return []
    entries = book_data.get('entries')
    if isinstance(entries, list):
        return [e for e in entries if isinstance(e, dict)]
    if isinstance(entries, dict):
        return [e for e in entries.values() if isinstance(e, dict)]
    return []


def ensure_entry_uids(book_data) -> bool:
    changed = False
    entries = _get_entries_ref(book_data)
    used = set()
    for entry in entries:
        uid = str(entry.get(ENTRY_UID_FIELD, '') or '').strip()
        if not uid or uid in used:
            uid = f'wi-{uuid.uuid4().hex[:16]}'
            entry[ENTRY_UID_FIELD] = uid
            changed = True
        elif entry.get(ENTRY_UID_FIELD) != uid:
            entry[ENTRY_UID_FIELD] = uid
            changed = True
        used.add(uid)
    return changed


def _snapshot_entry(entry: dict, forced_uid: str = '') -> dict:
    try:
        snap = json.loads(json.dumps(entry, ensure_ascii=False))
    except Exception:
        snap = dict(entry)
    snap.pop('id', None)
    snap.pop('uid', None)
    snap.pop('displayIndex', None)
    uid_val = str(forced_uid or snap.get(ENTRY_UID_FIELD, '') or '').strip()
    if uid_val:
        snap[ENTRY_UID_FIELD] = uid_val
    return snap


def _snapshot_hash(snapshot: dict) -> str:
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def collect_previous_versions(old_book, new_book):
    records = []
    old_entries = _get_entries_ref(old_book)
    new_entries = _get_entries_ref(new_book)
    if not old_entries or not new_entries:
        return records

    old_by_uid = {}
    for old_entry in old_entries:
        uid = str(old_entry.get(ENTRY_UID_FIELD, '') or '').strip()
        if uid and uid not in old_by_uid:
            old_by_uid[uid] = old_entry

    for idx, new_entry in enumerate(new_entries):
        uid = str(new_entry.get(ENTRY_UID_FIELD, '') or '').strip()
        if not uid:
            continue

        old_entry = old_by_uid.get(uid)
        if old_entry is None and idx < len(old_entries):
            fallback = old_entries[idx]
            old_uid = str(fallback.get(ENTRY_UID_FIELD, '') or '').strip()
            if not old_uid:
                old_entry = fallback

        if old_entry is None:
            continue

        old_snapshot = _snapshot_entry(old_entry, forced_uid=uid)
        new_snapshot = _snapshot_entry(new_entry, forced_uid=uid)
        if _snapshot_hash(old_snapshot) != _snapshot_hash(new_snapshot):
            records.append({
                'entry_uid': uid,
                'snapshot': old_snapshot
            })
    return records


def append_entry_history_records(source_type: str, source_id: str, file_path: str, records, limit=None) -> int:
    if not records:
        return 0

    clean_records = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        entry_uid = str(rec.get('entry_uid', '') or '').strip()
        snapshot = rec.get('snapshot')
        if not entry_uid or not isinstance(snapshot, dict):
            continue
        clean_records.append((entry_uid, _snapshot_entry(snapshot, forced_uid=entry_uid)))

    if not clean_records:
        return 0

    scope_key = build_scope_key(source_type, source_id, file_path)
    keep_limit = get_history_limit(limit)
    now_ts = time.time()
    inserted = 0

    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            cursor = conn.cursor()

            for entry_uid, snapshot in clean_records:
                snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
                snapshot_hash = _snapshot_hash(snapshot)

                cursor.execute(
                    '''
                    SELECT snapshot_hash
                    FROM wi_entry_history
                    WHERE scope_key = ? AND entry_uid = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    ''',
                    (scope_key, entry_uid)
                )
                row = cursor.fetchone()
                if row and row[0] == snapshot_hash:
                    continue

                cursor.execute(
                    '''
                    INSERT INTO wi_entry_history (scope_key, entry_uid, snapshot_json, snapshot_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (scope_key, entry_uid, snapshot_json, snapshot_hash, now_ts)
                )
                inserted += 1

                cursor.execute(
                    '''
                    DELETE FROM wi_entry_history
                    WHERE id IN (
                        SELECT id
                        FROM wi_entry_history
                        WHERE scope_key = ? AND entry_uid = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    ''',
                    (scope_key, entry_uid, keep_limit)
                )

            conn.commit()
    except Exception as e:
        logger.warning(f'Append WI entry history failed: {e}')
        return 0

    return inserted


def list_entry_history_records(source_type: str, source_id: str, file_path: str, entry_uid: str, limit=None):
    uid = str(entry_uid or '').strip()
    if not uid:
        return []

    scope_key = build_scope_key(source_type, source_id, file_path)
    fetch_limit = get_history_limit(limit)
    items = []

    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, snapshot_json, created_at
                FROM wi_entry_history
                WHERE scope_key = ? AND entry_uid = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                ''',
                (scope_key, uid, fetch_limit)
            )
            rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f'List WI entry history failed: {e}')
        return []

    for row in rows:
        try:
            snapshot = json.loads(row[1])
        except Exception:
            snapshot = {}
        items.append({
            'id': row[0],
            'created_at': row[2],
            'snapshot': snapshot
        })
    return items
