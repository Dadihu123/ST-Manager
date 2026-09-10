import os
import json
import time
import uuid
import hashlib
import logging
import sqlite3

from core.config import BASE_DIR, DEFAULT_DB_PATH, load_config
from core.config import CARDS_FOLDER
from core.utils.card_identity import normalize_card_uid

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


def _build_scope_keys(source_type, source_id='', file_path='', fallback_contexts=None):
    """Build the primary and compatibility scope keys for one source."""
    scope_keys = []
    contexts = [(source_type, source_id, file_path)]
    for context in fallback_contexts or []:
        if isinstance(context, dict):
            contexts.append((
                context.get('source_type', source_type),
                context.get('source_id', ''),
                context.get('file_path', ''),
            ))
        elif isinstance(context, (list, tuple)) and len(context) >= 3:
            contexts.append((context[0], context[1], context[2]))

    for context in contexts:
        scope_key = build_scope_key(*context)
        if scope_key and scope_key not in scope_keys:
            scope_keys.append(scope_key)
    return scope_keys


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
    if stype == 'embedded':
        sid = normalize_card_uid(sid) or sid
    npath = _normalize_path(file_path)
    if npath:
        raw = f'{stype}|{npath}'
    else:
        raw = f'{stype}|{sid}|'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def resolve_card_uid(card_id: str, cache=None, db_path=None) -> str:
    """Resolve a card's durable UUID from the runtime cache or metadata DB."""
    normalized_id = str(card_id or '').strip().replace('\\', '/').strip('/')
    if normalized_id.startswith('embedded::'):
        normalized_id = normalized_id.split('::', 1)[1]
    if not normalized_id:
        return ''

    cache_id_map = getattr(cache, 'id_map', {}) if cache is not None else {}
    candidates = []
    bundle_map = getattr(cache, 'bundle_map', {}) if cache is not None else {}
    if isinstance(bundle_map, dict):
        bundle_keys = [normalized_id]
        if '/' in normalized_id:
            bundle_keys.append(normalized_id.rsplit('/', 1)[0])
        for bundle_key in bundle_keys:
            real_card_id = bundle_map.get(bundle_key)
            if real_card_id:
                candidates.append(str(real_card_id).replace('\\', '/').strip('/'))
    candidates.extend([normalized_id, str(card_id or '').strip()])

    for candidate in candidates:
        item = cache_id_map.get(candidate) if isinstance(cache_id_map, dict) else None
        if isinstance(item, dict):
            uid = normalize_card_uid(item.get('card_uid'))
            if uid:
                return uid

    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            row = conn.execute(
                'SELECT card_uid FROM card_metadata WHERE id = ?',
                (normalized_id,),
            ).fetchone()
        return normalize_card_uid(row[0]) if row and row[0] else ''
    except (OSError, sqlite3.Error, AttributeError):
        return ''


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


def get_entry_uids(book_data):
    """Return the persisted UIDs currently present in a worldbook."""
    return [
        str(entry.get(ENTRY_UID_FIELD, '') or '').strip()
        for entry in _get_entries_ref(book_data)
        if str(entry.get(ENTRY_UID_FIELD, '') or '').strip()
    ]


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


def purge_entry_history_scope(
    source_type: str,
    source_id: str = '',
    file_path: str = '',
    fallback_contexts=None,
    db_path=None,
) -> int:
    """Delete all history rows belonging to a source and its legacy scopes."""
    scope_keys = _build_scope_keys(
        source_type,
        source_id,
        file_path,
        fallback_contexts=fallback_contexts,
    )
    if not scope_keys:
        return 0

    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            placeholders = ', '.join('?' for _ in scope_keys)
            cursor = conn.execute(
                f'DELETE FROM wi_entry_history WHERE scope_key IN ({placeholders})',
                tuple(scope_keys),
            )
            conn.commit()
            return max(int(cursor.rowcount or 0), 0)
    except Exception as e:
        logger.warning(f'Purge WI entry history failed: {e}')
        return 0


def reconcile_entry_history_scope(
    source_type: str,
    source_id: str = '',
    file_path: str = '',
    active_entry_uids=None,
    fallback_contexts=None,
    db_path=None,
) -> int:
    """Remove history for entries no longer present in the saved worldbook."""
    scope_keys = _build_scope_keys(
        source_type,
        source_id,
        file_path,
        fallback_contexts=fallback_contexts,
    )
    if not scope_keys:
        return 0

    active_uids = {
        str(uid or '').strip()
        for uid in (active_entry_uids or [])
        if str(uid or '').strip()
    }

    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            if not active_uids:
                placeholders = ', '.join('?' for _ in scope_keys)
                cursor = conn.execute(
                    f'DELETE FROM wi_entry_history WHERE scope_key IN ({placeholders})',
                    tuple(scope_keys),
                )
            else:
                uid_placeholders = ', '.join('?' for _ in active_uids)
                scope_placeholders = ', '.join('?' for _ in scope_keys)
                cursor = conn.execute(
                    f'''
                    DELETE FROM wi_entry_history
                    WHERE scope_key IN ({scope_placeholders})
                      AND entry_uid NOT IN ({uid_placeholders})
                    ''',
                    (*scope_keys, *sorted(active_uids)),
                )
            conn.commit()
            return max(int(cursor.rowcount or 0), 0)
    except Exception as e:
        logger.warning(f'Reconcile WI entry history failed: {e}')
        return 0


def _trim_scope_history(conn, scope_key: str, limit: int):
    """Deduplicate and bound history after a scope migration."""
    entry_rows = conn.execute(
        'SELECT DISTINCT entry_uid FROM wi_entry_history WHERE scope_key = ?',
        (scope_key,),
    ).fetchall()
    for (entry_uid,) in entry_rows:
        rows = conn.execute(
            '''
            SELECT id, snapshot_hash
            FROM wi_entry_history
            WHERE scope_key = ? AND entry_uid = ?
            ORDER BY created_at DESC, id DESC
            ''',
            (scope_key, entry_uid),
        ).fetchall()
        keep_ids = []
        seen_hashes = set()
        for row in rows:
            if row[1] in seen_hashes or len(keep_ids) >= limit:
                continue
            seen_hashes.add(row[1])
            keep_ids.append(row[0])
        if not keep_ids:
            continue
        placeholders = ', '.join('?' for _ in keep_ids)
        conn.execute(
            f'''
            DELETE FROM wi_entry_history
            WHERE scope_key = ? AND entry_uid = ? AND id NOT IN ({placeholders})
            ''',
            (scope_key, entry_uid, *keep_ids),
        )


def move_entry_history_scope(
    source_type: str,
    source_id: str = '',
    file_path: str = '',
    target_source_type: str = '',
    target_source_id: str = '',
    target_file_path: str = '',
    fallback_contexts=None,
    db_path=None,
) -> int:
    """Move history to a renamed source while collapsing legacy scopes."""
    old_scope_keys = _build_scope_keys(
        source_type,
        source_id,
        file_path,
        fallback_contexts=fallback_contexts,
    )
    target_scope_key = build_scope_key(
        target_source_type or source_type,
        target_source_id,
        target_file_path,
    )
    if not old_scope_keys or not target_scope_key:
        return 0

    old_scope_keys = [key for key in old_scope_keys if key != target_scope_key]
    if not old_scope_keys:
        return 0

    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            placeholders = ', '.join('?' for _ in old_scope_keys)
            cursor = conn.execute(
                f'''
                UPDATE wi_entry_history
                SET scope_key = ?
                WHERE scope_key IN ({placeholders})
                ''',
                (target_scope_key, *old_scope_keys),
            )
            _trim_scope_history(conn, target_scope_key, get_history_limit())
            conn.commit()
            return max(int(cursor.rowcount or 0), 0)
    except Exception as e:
        logger.warning(f'Move WI entry history failed: {e}')
        return 0


def purge_orphaned_entry_history(
    *,
    cards_root=None,
    world_info_root=None,
    resources_root=None,
    db_path=None,
) -> int:
    """Remove history scopes that no longer map to an existing source file."""
    cards_root = os.path.abspath(os.fspath(cards_root or CARDS_FOLDER))
    world_info_root = os.path.abspath(os.fspath(world_info_root or '')) if world_info_root else ''
    resources_root = os.path.abspath(os.fspath(resources_root or '')) if resources_root else ''

    roots = [cards_root, world_info_root, resources_root]
    if any(not root or not os.path.isdir(root) for root in roots):
        return 0

    valid_scope_keys = set()
    card_uid_map = {}
    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            try:
                card_uid_map = {
                    str(row[0]).replace('\\', '/').strip('/'): normalize_card_uid(row[1])
                    for row in conn.execute('SELECT id, card_uid FROM card_metadata').fetchall()
                }
            except sqlite3.Error:
                card_uid_map = {}
    except sqlite3.Error:
        card_uid_map = {}

    def add_worldbook_scopes(path, source_type):
        valid_scope_keys.add(build_scope_key(source_type, file_path=path))
        # History written before source_type was corrected used lorebook for all files.
        valid_scope_keys.add(build_scope_key('lorebook', file_path=path))

    for root, _dirs, files in os.walk(world_info_root):
        for name in files:
            if name.lower().endswith('.json'):
                add_worldbook_scopes(os.path.join(root, name), 'global')

    for root, _dirs, files in os.walk(resources_root):
        for name in files:
            if not name.lower().endswith('.json'):
                continue
            path = os.path.abspath(os.path.join(root, name))
            rel_path = os.path.relpath(path, resources_root).replace('\\', '/').lower()
            if '/lorebooks/' not in f'/{rel_path}/':
                continue
            add_worldbook_scopes(path, 'resource')

    for root, _dirs, files in os.walk(cards_root):
        for name in files:
            if not name.lower().endswith(('.json', '.png')):
                continue
            path = os.path.abspath(os.path.join(root, name))
            card_id = os.path.relpath(path, cards_root).replace('\\', '/').strip('/')
            valid_scope_keys.add(build_scope_key('embedded', source_id=card_id))
            card_uid = card_uid_map.get(card_id)
            if card_uid:
                valid_scope_keys.add(build_scope_key('embedded', source_id=card_uid))

    try:
        with sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            if valid_scope_keys:
                conn.execute(
                    'CREATE TEMP TABLE IF NOT EXISTS wi_valid_history_scopes (scope_key TEXT PRIMARY KEY)'
                )
                conn.execute('DELETE FROM wi_valid_history_scopes')
                conn.executemany(
                    'INSERT OR IGNORE INTO wi_valid_history_scopes (scope_key) VALUES (?)',
                    [(scope_key,) for scope_key in valid_scope_keys],
                )
                cursor = conn.execute(
                    '''
                    DELETE FROM wi_entry_history
                    WHERE scope_key NOT IN (SELECT scope_key FROM wi_valid_history_scopes)
                    '''
                )
            else:
                cursor = conn.execute('DELETE FROM wi_entry_history')
            conn.commit()
            return max(int(cursor.rowcount or 0), 0)
    except Exception as e:
        logger.warning(f'Purge orphaned WI entry history failed: {e}')
        return 0


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


def list_entry_history_records(
    source_type: str,
    source_id: str,
    file_path: str,
    entry_uid: str,
    limit=None,
    fallback_contexts=None,
):
    uid = str(entry_uid or '').strip()
    if not uid:
        return []

    scope_keys = _build_scope_keys(
        source_type,
        source_id,
        file_path,
        fallback_contexts=fallback_contexts,
    )
    if not scope_keys:
        return []

    fetch_limit = get_history_limit(limit)
    items = []

    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            _ensure_table(conn)
            cursor = conn.cursor()
            placeholders = ', '.join('?' for _ in scope_keys)
            cursor.execute(
                f'''
                SELECT id, snapshot_json, created_at
                FROM wi_entry_history
                WHERE scope_key IN ({placeholders}) AND entry_uid = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                ''',
                (*scope_keys, uid, fetch_limit),
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
