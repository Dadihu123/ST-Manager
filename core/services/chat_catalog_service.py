"""Rebuildable file facts; user state and bindings remain in the repository."""

import errno
import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
from contextlib import closing
from functools import wraps

from core import config
from core.data import local_state_repository as state
from core.services.maintenance_gate import coordinated
from core.utils.card_identity import normalize_card_uid
from core.utils.chat_parser import build_chat_stats_from_index, get_chat_jsonl_index
from core.utils.filesystem import walk_directory_strict
from core.utils.paths import is_under_base

logger = logging.getLogger(__name__)
PARSE_VERSION = 1
_writes = threading.RLock()
_reconciles = threading.Lock()
_mutation_epoch = 0
_wake = threading.Event()
_start_lock = threading.Lock()
_worker = None
_event_lock = threading.Lock()
_changed_paths = set()
_ROOT_PREFIX = '@stm-chat-root:'
_ROOT_PREFIX_BOUNDS = (_ROOT_PREFIX, '@stm-chat-root;')
_BINDING_EDIT = '@bindings'


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_state_roots (
        root TEXT PRIMARY KEY, prefix TEXT NOT NULL UNIQUE
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_root_aliases (
        alias TEXT PRIMARY KEY, root TEXT NOT NULL
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_legacy_root_claim (
        id INTEGER PRIMARY KEY CHECK (id=1), root TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_legacy_claim_edits (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, field TEXT NOT NULL,
        PRIMARY KEY (root,chat_id,field)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_legacy_claim_replacements (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, revision TEXT NOT NULL,
        PRIMARY KEY (root,chat_id)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_legacy_claim_moves (
        root TEXT NOT NULL, origin TEXT NOT NULL, target TEXT NOT NULL, revision TEXT NOT NULL,
        PRIMARY KEY (root,origin), UNIQUE (root,target)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_files (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, revision TEXT NOT NULL,
        parse_version INTEGER NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL,
        name TEXT NOT NULL, character TEXT NOT NULL, preview TEXT NOT NULL, facts TEXT NOT NULL,
        PRIMARY KEY (root, chat_id)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_catalog_state (
        root TEXT PRIMARY KEY, parse_version INTEGER NOT NULL, error TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_file_moves (
        root TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, digest TEXT NOT NULL,
        source_identity TEXT NOT NULL DEFAULT '', target_identity TEXT NOT NULL DEFAULT '',
        staging TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (root,source)
    ) WITHOUT ROWID''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(chat_file_moves)')}
    for name in ('source_identity', 'target_identity', 'staging'):
        if name not in columns:
            conn.execute(f"ALTER TABLE chat_file_moves ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_missing_files (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, revision TEXT NOT NULL,
        PRIMARY KEY (root,chat_id)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_retired_state (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, revision TEXT NOT NULL,
        payload TEXT NOT NULL, bindings TEXT NOT NULL,
        PRIMARY KEY (root,chat_id,revision)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_root_merge_conflicts (
        root TEXT NOT NULL, chat_id TEXT NOT NULL, legacy_payload TEXT NOT NULL, active_payload TEXT NOT NULL,
        PRIMARY KEY (root,chat_id)
    ) WITHOUT ROWID''')


def root_key(root):
    """Normalize a path spelling for SQL; this does not resolve aliases."""
    return os.path.normcase(os.path.abspath(root))


def physical_root(root):
    path = os.path.realpath(root, strict=True)
    if not stat.S_ISDIR(os.stat(path).st_mode):
        raise NotADirectoryError(path)
    return path


def _catalog_key(conn, root):
    key = root_key(root)
    alias = conn.execute('SELECT root FROM chat_root_aliases WHERE alias=?', (key,)).fetchone()
    return alias[0] if alias else key


def _prefix_at(conn, key):
    row = conn.execute('SELECT prefix FROM chat_state_roots WHERE root=?', (key,)).fetchone()
    return row[0] if row else None


def root_prefix(root, *, conn=None, db_path=None):
    """Look up the verified root without touching the chat directory."""
    if conn is None:
        state.initialize(db_path)
        with closing(state.connect(db_path)) as reader, reader:
            reader.execute('BEGIN')
            return root_prefix(root, conn=reader)
    prefix = _prefix_at(conn, _catalog_key(conn, root))
    if prefix is None and _legacy_claim(conn) == root_key(root):
        return ''
    return prefix


def _legacy_claim(conn):
    row = conn.execute('SELECT root FROM chat_legacy_root_claim WHERE id=1').fetchone()
    return row[0] if row else None


def _claim_matches(claim, alias, physical_key):
    if claim is None:
        return False
    if claim == alias:
        return True
    try:
        return root_key(physical_root(claim)) == physical_key
    except OSError:
        return False


@coordinated
def register_root(root, *, db_path=None):
    """Pin a reachable root and persist its alias before opening a file or projecting it."""
    alias = root_key(root)
    physical = physical_root(root)
    key = root_key(physical)
    state.initialize(db_path)
    with closing(state.connect(db_path)) as conn, conn:
        conn.execute('BEGIN')
        prefix = _prefix_at(conn, key)
        mapped = _catalog_key(conn, alias) == key and _catalog_key(conn, key) == key
        claim = _legacy_claim(conn)
    if prefix is not None and mapped and not _claim_matches(claim, alias, key):
        return physical, prefix
    with _writes, state.Repository('chat', db_path).transaction() as conn:
        # A junction can change while this caller waits for either write lock.
        physical = physical_root(root)
        key = root_key(physical)
        prefix = _prefix_at(conn, key)
        current_claim = _legacy_claim(conn)
        claimed_here = _claim_matches(current_claim, alias, key)
        merge_now = claimed_here and not conn.execute(
            'SELECT 1 FROM chat_file_moves WHERE root=? LIMIT 1', (key,)).fetchone()
        if prefix is None:
            legacy = merge_now or (current_claim is None and not conn.execute(
                'SELECT 1 FROM chat_state_roots LIMIT 1').fetchone())
            prefix = '' if legacy else _ROOT_PREFIX + uuid.uuid4().hex + ':'
            conn.execute('INSERT INTO chat_state_roots VALUES (?,?)', (key, prefix))
        if merge_now:
            if prefix:
                _merge_legacy_root(conn, key, prefix, db_path)
            conn.execute('DELETE FROM chat_legacy_root_claim WHERE id=1')
            conn.execute('DELETE FROM chat_legacy_claim_edits')
            conn.execute('DELETE FROM chat_legacy_claim_replacements')
            conn.execute('DELETE FROM chat_legacy_claim_moves')
        conn.execute('DELETE FROM chat_root_aliases WHERE alias=?', (key,))
        if claimed_here and current_claim != key:
            conn.execute('INSERT OR REPLACE INTO chat_root_aliases VALUES (?,?)', (current_claim, key))
        if alias != key:
            conn.execute('INSERT OR REPLACE INTO chat_root_aliases VALUES (?,?)', (alias, key))
        if (root_key(physical_root(root)) != key
                or claimed_here and not _claim_matches(current_claim, alias, key)):
            raise OSError('聊天目录在登记期间变化，请重试')
    return physical, prefix


def claim_legacy_root(root, *, db_path=None):
    """Reserve the original configured library without accessing it at startup."""
    with state.Repository('chat', db_path).transaction() as conn:
        if not conn.execute('SELECT 1 FROM chat_state_roots LIMIT 1').fetchone():
            conn.execute('INSERT OR IGNORE INTO chat_legacy_root_claim VALUES (1,?)', (root_key(root),))


def local_chat_id(prefix, key):
    if prefix is None or not key.startswith(prefix) or (not prefix and key.startswith(_ROOT_PREFIX)):
        return None
    return key[len(prefix):]


def _remap_binding_ids(record, translate):
    ids = record.get('chat_ids') if isinstance(record, dict) else None
    if not isinstance(ids, list):
        return False
    seen = set()
    unique = []
    for value in ids:
        if isinstance(value, str):
            value = translate(value)
            if value is None:
                continue
            if value in seen:
                continue
            seen.add(value)
        unique.append(value)
    if unique == ids:
        return False
    record['chat_ids'] = unique
    return True


def record_legacy_claim_edit(conn, root, chat_id, fields):
    """Remember authored values (including defaults) until the legacy claim is resolved."""
    if fields and _legacy_claim(conn) is not None:
        key = root_key(root)
        conn.executemany('INSERT OR IGNORE INTO chat_legacy_claim_edits VALUES (?,?,?)',
                         ((key, chat_id, field) for field in fields))


def record_legacy_claim_binding(conn, root, chat_id):
    record_legacy_claim_edit(conn, root, chat_id, (_BINDING_EDIT,))


def _merge_chat_records(legacy, active, edited_fields):
    from core.data.chat_store import default_chat_entry

    if not isinstance(legacy, dict) or not isinstance(active, dict):
        return active
    defaults = default_chat_entry()
    merged = {**legacy, **active}
    for field, default in defaults.items():
        if field not in edited_fields and field in active and active[field] == default and field in legacy:
            merged[field] = legacy[field]
    # Each scope may have added bookmarks while the other was unavailable.
    if 'bookmarks' not in edited_fields:
        bookmarks = {item['id']: item for item in legacy.get('bookmarks', [])}
        bookmarks.update((item['id'], item) for item in active.get('bookmarks', []))
        merged['bookmarks'] = list(bookmarks.values())
    return merged


def _merge_legacy_root(conn, root, prefix, db_path):
    """Merge an unbound legacy scope into its verified library in the caller's transaction."""
    chat, ui = state.Repository('chat', db_path), state.Repository('ui', db_path)
    verify_legacy_claim_moves(conn, root, db_path)

    for chat_id, revision in conn.execute('SELECT chat_id,revision FROM chat_legacy_claim_replacements WHERE root=?',
                                         (root,)).fetchall():
        # The temporary scope may already have archived its own state for this revision.
        _retire_previous_state(conn, root, chat_id, 'legacy:' + revision, db_path, stored_id=chat_id)
    edits = {}
    for chat_id, field in conn.execute('SELECT chat_id,field FROM chat_legacy_claim_edits WHERE root=?', (root,)):
        edits.setdefault(chat_id, set()).add(field)
    moves = dict(conn.execute('SELECT origin,target FROM chat_legacy_claim_moves WHERE root=?', (root,)))

    def translate_binding(key):
        if local_chat_id('', key) is None:
            return key
        target = moves.get(key, key)
        return None if _BINDING_EDIT in edits.get(target, ()) else prefix + target

    # Prefix ranges let SQLite skip all already-scoped records.
    legacy = conn.execute('SELECT key,payload_json FROM chat_local_state WHERE key<? OR key>=?',
                          _ROOT_PREFIX_BOUNDS).fetchall()
    for chat_id, legacy_json in legacy:
        old = json.loads(legacy_json)
        target_id = moves.get(chat_id, chat_id)
        target = prefix + target_id
        existing = conn.execute('SELECT payload_json FROM chat_local_state WHERE key=?', (target,)).fetchone()
        if existing is None:
            merged = old
        else:
            active = json.loads(existing[0])
            merged = _merge_chat_records(old, active, edits.get(target_id, ()))
            if active != old:
                conn.execute('INSERT INTO chat_root_merge_conflicts VALUES (?,?,?,?)',
                             (root, chat_id, legacy_json, existing[0]))
        chat._put(conn, target, merged)
        chat.delete(chat_id, conn=conn)

    keys = conn.execute('SELECT DISTINCT card_ui_key FROM chat_card_bindings WHERE chat_id<? OR chat_id>=?',
                        _ROOT_PREFIX_BOUNDS).fetchall()
    for (key,) in keys:
        record = ui.get(key, conn=conn)
        if _remap_binding_ids(record, translate_binding):
            ui._put(conn, key, record, defer_projection=True)
    stale = ui.get('_stale_card_bindings_v1', {}, conn=conn)
    if isinstance(stale, dict):
        changed = False
        for value in stale.values():
            changed = _remap_binding_ids(value, translate_binding) or changed
        if changed:
            ui._put(conn, '_stale_card_bindings_v1', stale)


def request_reconcile():
    _wake.set()


def queue_file_event(*paths):
    with _event_lock:
        _changed_paths.update(path for path in paths if path and path.lower().endswith('.jsonl'))


def file_mutation(func):
    @wraps(func)
    def locked(*args, **kwargs):
        global _mutation_epoch
        with _writes:
            try:
                return func(*args, **kwargs)
            finally:
                _mutation_epoch += 1
    return locked


def _birthtime_ns(st):
    if hasattr(st, 'st_birthtime_ns'):
        return st.st_birthtime_ns
    if os.name == 'nt':  # Python < 3.12 exposes Windows creation time as ctime.
        return st.st_ctime_ns
    return int(getattr(st, 'st_birthtime', 0) * 1_000_000_000)


def file_revision(st):
    return ':'.join(str(value) for value in
                    (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                     _birthtime_ns(st)))


def _inspect(root, path, chat_id, previous=None):
    if local_chat_id('', chat_id) is None:
        return None
    if not is_under_base(os.path.realpath(path, strict=True), root):
        return None
    before = os.stat(path)
    if not stat.S_ISREG(before.st_mode):
        return None
    revision = file_revision(before)
    if previous and previous == (revision, PARSE_VERSION):
        return ()
    indexed = get_chat_jsonl_index(path, catalog=True)
    if revision != file_revision(os.stat(path)):
        raise OSError(f'聊天文件在读取期间变化: {path}')
    if indexed is None:
        return None
    facts = build_chat_stats_from_index(path, indexed['metadata'], indexed['message_index'])
    character = chat_id.split('/', 1)[0] if '/' in chat_id else ''
    return (root_key(root), chat_id, revision, PARSE_VERSION, before.st_mtime, before.st_size,
            facts['chat_name'], character, facts['preview'], state.encode(facts))


_UPSERT = 'INSERT OR REPLACE INTO chat_files VALUES (?,?,?,?,?,?,?,?,?,?)'


def _file_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _move_path(root, chat_id, *, existing=True):
    path = os.path.join(root, chat_id)
    real_root = os.path.realpath(root, strict=True)
    checked = path if existing else os.path.dirname(path)
    if not is_under_base(os.path.realpath(checked, strict=True), real_root):
        raise OSError('聊天移动路径不在当前目录内')
    return path


def _identity(st):
    if not stat.S_ISREG(st.st_mode) or not st.st_ino:
        raise OSError('无法验证聊天文件身份')
    return f'{st.st_dev}:{st.st_ino}:{_birthtime_ns(st)}'


def _move_evidence(path):
    before = file_revision(os.stat(path, follow_symlinks=False))
    digest = _file_digest(path)
    info = os.stat(path, follow_symlinks=False)
    if file_revision(info) != before:
        raise OSError('聊天文件在校验期间变化')
    return _identity(info), digest


def _target_state_conflicts(conn, target):
    if (conn.execute('SELECT 1 FROM chat_local_state WHERE key=?', (target,)).fetchone()
            or conn.execute('SELECT 1 FROM chat_card_bindings WHERE chat_id=?', (target,)).fetchone()):
        return True
    stale = state.Repository('ui').get('_stale_card_bindings_v1', {}, conn=conn)
    return isinstance(stale, dict) and any(
        isinstance(record, dict) and target in (record.get('chat_ids') or []) for record in stale.values())


def _reserved_target(conn, key, prefix, chat_id, source=None):
    if _has_active_reservation(conn, key, prefix, chat_id):
        return True
    if not prefix or _legacy_claim(conn) is None:
        return False
    if conn.execute('SELECT 1 FROM chat_legacy_claim_moves WHERE root=? AND target=?',
                    (key, chat_id)).fetchone():
        return True
    return (source is None or _legacy_origin_at(conn, key, source) != chat_id) and _target_state_conflicts(conn, chat_id)


def _has_active_reservation(conn, key, prefix, chat_id):
    return (_target_state_conflicts(conn, prefix + chat_id)
            or conn.execute('SELECT 1 FROM chat_missing_files WHERE root=? AND chat_id=?',
                            (key, chat_id)).fetchone() is not None)


def has_reserved_state(root, chat_id, *, source=None):
    with closing(state.connect()) as conn:
        key = root_key(root)
        prefix = root_prefix(root, conn=conn)
        return (prefix is not None and _reserved_target(conn, key, prefix, chat_id, source)) or bool(conn.execute(
            'SELECT 1 FROM chat_file_moves WHERE root=? AND (source=? OR target=?)',
            (key, chat_id, chat_id)).fetchone())


def is_pending_move_path(root, chat_id, *, conn=None):
    if conn is None:
        with closing(state.connect()) as reader:
            return is_pending_move_path(root, chat_id, conn=reader)
    return conn.execute('SELECT 1 FROM chat_file_moves WHERE root=? AND (source=? OR target=?)',
                        (root_key(root), chat_id, chat_id)).fetchone() is not None


def observed_revision(root, chat_id):
    return file_revision(os.stat(_move_path(root, chat_id), follow_symlinks=False))


def needs_reidentify(root, chat_id, *, conn=None):
    if conn is None:
        with closing(state.connect()) as reader:
            return needs_reidentify(root, chat_id, conn=reader)
    key = root_key(root)
    move = _claim_move_at(conn, key, chat_id)
    if (conn.execute('SELECT 1 FROM chat_missing_files WHERE root=? AND chat_id=?', (key, chat_id)).fetchone()
            or move and not _same_file(move[1], _claim_move_revision(root, chat_id) or '')):
        request_reconcile()
        return True
    return False


def validate_metadata_write(conn, root, chat_id, revision):
    # Move intents are reserved before changing the filesystem, on this same database.
    if is_pending_move_path(root, chat_id, conn=conn) or observed_revision(root, chat_id) != revision:
        raise state.StateConflict('聊天已移动或变化，请重新载入后重试')
    if needs_reidentify(root, chat_id, conn=conn):
        raise state.StateConflict('聊天文件等待重新识别，请稍后重试')


def prepare_move(root, source, target):
    path = _move_path(root, source)
    _move_path(root, target, existing=False)
    identity, digest = _move_evidence(path)
    with state.Repository('chat').transaction() as conn:
        key = root_key(root)
        prefix = _prefix_at(conn, key)
        revision = observed_revision(root, source)
        validate_metadata_write(conn, root, source, revision)
        if _reserved_target(conn, key, prefix, target, source) or conn.execute(
                'SELECT 1 FROM chat_file_moves WHERE root=? AND (source IN (?,?) OR target IN (?,?))',
                (key, source, target, source, target)).fetchone():
            raise OSError('聊天移动目标已有状态或存在未处理的移动')
        conn.execute('INSERT INTO chat_file_moves VALUES (?,?,?,?,?,?,?)',
                     (key, source, target, digest, identity, identity, ''))
    request_reconcile()  # Picks up the intent if the request fails after the filesystem move.


def _rename_without_replace(source, target, *, expected):
    if os.name == 'nt':
        if _identity(os.stat(source, follow_symlinks=False)) != expected:
            raise OSError('聊天移动源文件已变化')
        os.rename(source, target)
    else:
        os.link(source, target, follow_symlinks=False)
        if (_identity(os.stat(target, follow_symlinks=False)) != expected
                or _identity(os.stat(source, follow_symlinks=False)) != expected):
            raise OSError('聊天移动源文件已变化')
        os.unlink(source)


def move_file(root, source, target):
    """Move without replacing a file and persist the destination identity before publication."""
    prepare_move(root, source, target)
    source_path = _move_path(root, source)
    target_path = _move_path(root, target, existing=False)
    with closing(state.connect()) as conn:
        digest, source_identity = conn.execute(
            'SELECT digest,source_identity FROM chat_file_moves WHERE root=? AND source=?',
            (root_key(root), source)).fetchone()
    try:
        _rename_without_replace(source_path, target_path, expected=source_identity)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    with tempfile.NamedTemporaryFile(prefix='.stm-chat-move-', suffix='.tmp',
                                     dir=os.path.dirname(target_path), delete=False) as handle:
        staging_path = handle.name
    recorded = False
    try:
        shutil.copy2(source_path, staging_path)
        with open(staging_path, 'r+b') as stream:
            os.fsync(stream.fileno())
        target_identity, copied_digest = _move_evidence(staging_path)
        if copied_digest != digest or _move_evidence(source_path) != (source_identity, digest):
            raise OSError('聊天源文件在复制期间变化')
        staging = os.path.relpath(staging_path, root).replace('\\', '/')
        with state.Repository('chat').transaction() as conn:
            conn.execute('UPDATE chat_file_moves SET target_identity=?,staging=? WHERE root=? AND source=?',
                         (target_identity, staging, root_key(root), source))
        recorded = True
        _rename_without_replace(staging_path, target_path, expected=target_identity)
        if _move_evidence(source_path) != (source_identity, digest):
            raise OSError('聊天源文件在复制后变化')
        os.unlink(source_path)
    finally:
        if not recorded:
            os.unlink(staging_path)


def _apply_recovered_move(conn, source, target, db_path):
    chat, ui = state.Repository('chat', db_path), state.Repository('ui', db_path)
    original = chat.get(source, conn=conn)
    if original is not None:
        chat._put(conn, target, original)
        chat.delete(source, conn=conn)

    def translate(value):
        return target if value == source else value

    keys = [row[0] for row in conn.execute('SELECT card_ui_key FROM chat_card_bindings WHERE chat_id=?', (source,))]
    for key in keys:
        record = ui.get(key, {}, conn=conn)
        if _remap_binding_ids(record, translate):
            ui._put(conn, key, record)
    quarantined = ui.get('_stale_card_bindings_v1', {}, conn=conn)
    if isinstance(quarantined, dict):
        changed = False
        for value in quarantined.values():
            changed = _remap_binding_ids(value, translate) or changed
        if changed:
            ui._put(conn, '_stale_card_bindings_v1', quarantined)


def _legacy_origin_at(conn, key, path):
    row = _claim_move_at(conn, key, path)
    if row:
        return row[0]
    if (conn.execute('SELECT 1 FROM chat_legacy_claim_moves WHERE root=? AND origin=?', (key, path)).fetchone()
            or conn.execute('SELECT 1 FROM chat_legacy_claim_replacements WHERE root=? AND chat_id=?',
                            (key, path)).fetchone()):
        return None
    return path


def _claim_move_at(conn, key, path):
    return conn.execute('SELECT origin,revision FROM chat_legacy_claim_moves WHERE root=? AND target=?',
                        (key, path)).fetchone()


def _record_claim_move(conn, key, source, target, revision, prefix):
    if not prefix or _legacy_claim(conn) is None:
        return
    origin = _legacy_origin_at(conn, key, source)
    if origin is not None:
        conn.execute('INSERT INTO chat_legacy_claim_moves VALUES (?,?,?,?) '
                     'ON CONFLICT(root,origin) DO UPDATE SET target=excluded.target,revision=excluded.revision',
                     (key, origin, target, revision))
    conn.execute('UPDATE OR IGNORE chat_legacy_claim_edits SET chat_id=? WHERE root=? AND chat_id=?',
                 (target, key, source))
    conn.execute('DELETE FROM chat_legacy_claim_edits WHERE root=? AND chat_id=?', (key, source))


def _evidence_if_present(root, chat_id):
    try:
        return _move_evidence(_move_path(root, chat_id))
    except FileNotFoundError:
        return None


def _finish_move(conn, root, move, db_path, *, finalize=None):
    source, target, digest, source_identity, target_identity, staging = move
    source_evidence = _evidence_if_present(root, source)
    target_evidence = _evidence_if_present(root, target)
    staging_evidence = _evidence_if_present(root, staging) if staging else None
    source_matches = bool(source_identity) and source_evidence == (source_identity, digest)
    target_matches = bool(target_identity) and target_evidence == (target_identity, digest)
    abandoned = source_matches and target_evidence is None
    if ((not abandoned and (not target_matches or source_evidence is not None and not source_matches))
            or (staging_evidence is not None and staging_evidence != (target_identity, digest))):
        raise OSError(f'无法确认聊天移动结果，请检查源文件与目标文件：{source} → {target}')
    row = None
    if target_matches:
        row = _inspect(root, _move_path(root, target), target)
        if not row or _evidence_if_present(root, target) != target_evidence:
            raise OSError('聊天移动目标无法读取或已变化')
    key = root_key(root)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if row:
            prefix = _prefix_at(conn, key)
            if file_revision(os.stat(_move_path(root, target), follow_symlinks=False)) != row[2]:
                raise OSError('聊天移动目标在提交前变化')
            if _reserved_target(conn, key, prefix, target, source):
                raise OSError(f'聊天移动目标已有其他用户状态，请检查：{source} → {target}')
            if source_matches:
                if _evidence_if_present(root, source) != source_evidence:
                    raise OSError('聊天移动源文件已变化')
                os.unlink(_move_path(root, source))
            _apply_recovered_move(conn, prefix + source, prefix + target, db_path)
            _record_claim_move(conn, key, source, target, row[2], prefix)
            if finalize:
                finalize(conn, json.loads(row[-1]))
            conn.execute('DELETE FROM chat_files WHERE root=? AND chat_id=?', (key, source))
            conn.execute(_UPSERT, row)
        if staging_evidence:
            if _evidence_if_present(root, staging) != staging_evidence:
                raise OSError('聊天移动临时文件已变化')
            os.unlink(_move_path(root, staging))
        conn.execute('DELETE FROM chat_file_moves WHERE root=? AND source=?', (key, source))
    return bool(row)


def _pending_moves(conn, root, source=None):
    query = ('SELECT source,target,digest,source_identity,target_identity,staging '
             'FROM chat_file_moves WHERE root=?')
    return conn.execute(query, (root_key(root),)).fetchall() if source is None else conn.execute(
        query + ' AND source=?', (root_key(root), source)).fetchall()


def finish_move(root, source, *, finalize):
    with closing(state.connect()) as conn:
        moves = _pending_moves(conn, root, source)
        if not moves or not _finish_move(conn, root, moves[0], None, finalize=finalize):
            raise OSError('未能完成聊天移动')


def _recover_moves(root, conn, db_path):
    blocked, errors = set(), []
    for move in _pending_moves(conn, root):
        try:
            _finish_move(conn, root, move, db_path)
        except OSError as exc:
            blocked.update(move[:2])
            errors.append(str(exc))
    return blocked, '；'.join(errors)


def _retire_previous_state(conn, root, chat_id, revision, db_path, *, stored_id=None):
    chats, ui = state.Repository('chat', db_path), state.Repository('ui', db_path)
    if stored_id is None:
        stored_id = _prefix_at(conn, root) + chat_id
    previous = chats.get(stored_id, conn=conn)
    bindings = {}
    for key, in conn.execute('SELECT card_ui_key FROM chat_card_bindings WHERE chat_id=?', (stored_id,)).fetchall():
        record = ui.get(key, conn=conn)
        bindings[key] = {'card_uid': record.get('card_uid'), 'chat_ids': record['chat_ids']}
        record['chat_ids'] = [item for item in record['chat_ids'] if item != stored_id]
        ui._put(conn, key, record)
    stale_store = ui.get('_stale_card_bindings_v1', {}, conn=conn)
    stale_bindings = {}
    for key, record in stale_store.items():
        if isinstance(record, dict) and stored_id in (record.get('chat_ids') or []):
            stale_bindings[key] = dict(record)
            record['chat_ids'] = [item for item in record['chat_ids'] if item != stored_id]
    if stale_bindings:
        ui._put(conn, '_stale_card_bindings_v1', stale_store)
    if previous is not None or bindings or stale_bindings:
        conn.execute('INSERT INTO chat_retired_state VALUES (?,?,?,?,?) '
                     'ON CONFLICT(root,chat_id,revision) DO NOTHING',
                     (root, chat_id, revision, state.encode(previous),
                      state.encode({'owners': bindings, 'stale': stale_bindings})))
    if previous is not None:
        chats.delete(stored_id, conn=conn)


def _same_file(previous, current):
    old, new = previous.split(':'), current.split(':')
    if len(old) != 6 or len(new) != 6 or old[:2] != new[:2] or old[1] == '0':
        return False
    # File ID and birth time survive edits. With no birth time, allow only the
    # unchanged content version; an inode can be reused after unlink.
    if old[5] != '0' or new[5] != '0':
        return old[5] == new[5]
    return old[2:4] == new[2:4]


def _note_claim_identity_break(conn, key, chat_id, revision):
    if _legacy_claim(conn) is not None:
        origin = _legacy_origin_at(conn, key, chat_id)
        if origin is not None:
            # Keep the first identity break even when the temporary scope had no user state to retire.
            conn.execute('INSERT OR IGNORE INTO chat_legacy_claim_replacements VALUES (?,?,?)',
                         (key, origin, revision))
            conn.execute('DELETE FROM chat_legacy_claim_moves WHERE root=? AND origin=?', (key, origin))
        conn.execute('DELETE FROM chat_legacy_claim_edits WHERE root=? AND chat_id=?', (key, chat_id))


def _verify_claim_move_at(conn, key, chat_id, revision, db_path, *, previous_revision=None):
    move = _claim_move_at(conn, key, chat_id)
    if not move:
        return False
    origin, expected = move
    if expected.startswith('retire:') or not _same_file(expected, previous_revision or revision):
        _note_claim_identity_break(conn, key, chat_id, expected.removeprefix('retire:'))
        _retire_previous_state(conn, key, chat_id, expected.removeprefix('retire:'), db_path)
        conn.execute('DELETE FROM chat_files WHERE root=? AND chat_id=?', (key, chat_id))
        return True
    if revision != expected:
        conn.execute('UPDATE chat_legacy_claim_moves SET revision=? WHERE root=? AND origin=?',
                     (revision, key, origin))
    return False


def _claim_move_revision(root, chat_id):
    try:
        return observed_revision(root, chat_id)
    except FileNotFoundError:
        return None


def verify_legacy_claim_moves(conn, root, db_path):
    for target, expected in conn.execute('SELECT target,revision FROM chat_legacy_claim_moves WHERE root=?',
                                         (root,)).fetchall():
        current = expected if expected.startswith('retire:') else _claim_move_revision(root, target)
        if current is None:
            # Keep the state at the verified destination. The file may return after this claim is cleared.
            conn.execute('INSERT OR IGNORE INTO chat_missing_files VALUES (?,?,?)', (root, target, expected))
        else:
            _verify_claim_move_at(conn, root, target, current, db_path)


def archive_legacy_claim_move_revision(revision, packed):
    if revision.startswith('retire:'):
        return revision
    if packed and _same_file(revision, packed[0]):
        return 'portable:' + packed[1]
    return 'retire:' + revision


def restore_legacy_claim_move_revision(from_root, chat_id, revision):
    """Rebase verified file evidence when archive copies receive new file identities."""
    if revision.startswith('retire:'):
        return revision
    try:
        current = observed_revision(from_root, chat_id)
    except FileNotFoundError:
        return 'retire:' + revision
    if not revision.startswith('portable:'):
        return 'retire:' + revision
    digest = _file_digest(_move_path(from_root, chat_id))
    if current != observed_revision(from_root, chat_id):
        raise OSError('聊天文件在备份验证期间变化')
    return current if revision == 'portable:' + digest else 'retire:' + revision


def _publish_rows(conn, rows, db_path, *, rewritten=None):
    for row in rows:
        key, chat_id, revision = row[:3]
        retired = _verify_claim_move_at(conn, key, chat_id, revision, db_path,
                                         previous_revision=(rewritten or {}).get(chat_id))
        missing = conn.execute('SELECT revision FROM chat_missing_files WHERE root=? AND chat_id=?',
                               (key, chat_id)).fetchone()
        if missing:
            if not retired and not _same_file(missing[0], revision):
                _note_claim_identity_break(conn, key, chat_id, missing[0])
                _retire_previous_state(conn, key, chat_id, missing[0], db_path)
            conn.execute('DELETE FROM chat_missing_files WHERE root=? AND chat_id=?', (key, chat_id))
        conn.execute(_UPSERT, row)


@file_mutation
def publish(root, paths=(), *, removed=None, rewritten=None, db_path=None):
    """Publish successful application writes before acknowledging them."""
    try:
        rows = []
        deleted = []
        for path in paths:
            chat_id = os.path.relpath(path, root).replace('\\', '/')
            row = _inspect(root, path, chat_id)
            if row:
                rows.append(row)
            else:
                deleted.append(chat_id)
        state.initialize(db_path)
        with closing(state.connect(db_path)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if removed is not None:
                chat_id, revision = removed
                _note_claim_identity_break(conn, root_key(root), chat_id, revision)
                deleted.append(chat_id)
            conn.executemany('DELETE FROM chat_files WHERE root=? AND chat_id=?',
                             ((root_key(root), chat_id) for chat_id in deleted))
            _publish_rows(conn, rows, db_path, rewritten=rewritten)
    except Exception:
        request_reconcile()
        raise


def _record_error(conn, key, error):
    conn.execute('INSERT INTO chat_catalog_state VALUES (?,0,?) '
                 'ON CONFLICT(root) DO UPDATE SET error=excluded.error', (key, str(error)))


@coordinated
def reconcile(root, *, db_path=None, before_read=None):
    """Only a complete read may remove old file facts; never remove user state."""
    state.initialize(db_path)
    configured_root = root
    try:
        root, _ = register_root(root, db_path=db_path)
    except OSError as exc:
        with _writes, closing(state.connect(db_path)) as conn, conn:
            _record_error(conn, _catalog_key(conn, root), exc)
        raise
    if before_read is not None:
        before_read(root)
    key = root_key(root)
    with _reconciles, closing(state.connect(db_path)) as conn:
        seen, present, updates = set(), set(), []
        try:
            with _writes:
                epoch = _mutation_epoch
                blocked, recovery_error = _recover_moves(root, conn, db_path)
                if not blocked and _legacy_claim(conn) is not None and _claim_matches(
                        _legacy_claim(conn), root_key(configured_root), key):
                    resolved, _ = register_root(configured_root, db_path=db_path)
                    if root_key(resolved) != key:
                        request_reconcile()
                        return False
                previous = {row[0]: (row[1], row[2]) for row in conn.execute(
                    '''SELECT f.chat_id,f.revision,CASE WHEN m.chat_id IS NULL THEN f.parse_version END
                    FROM chat_files f LEFT JOIN chat_missing_files m ON m.root=f.root AND m.chat_id=f.chat_id
                    WHERE f.root=?''', (key,))}
            present.update(blocked)
            seen.update(blocked)
            for directory, children, files in walk_directory_strict(root):
                children[:] = [name for name in children if not name.startswith('.')]
                for filename in files:
                    if not filename.lower().endswith('.jsonl'):
                        continue
                    path = os.path.join(directory, filename)
                    chat_id = os.path.relpath(path, root).replace('\\', '/')
                    if chat_id in blocked:
                        continue
                    present.add(chat_id)
                    row = _inspect(root, path, chat_id, previous.get(chat_id))
                    if row is not None:
                        seen.add(chat_id)
                    if row:
                        updates.append(row)
        except OSError as exc:
            with _writes, conn:
                if epoch != _mutation_epoch:
                    request_reconcile()
                    return False
                _record_error(conn, key, exc)
            raise
        with _writes, conn:
            if epoch != _mutation_epoch:
                request_reconcile()
                return False
            conn.executemany('INSERT INTO chat_missing_files VALUES (?,?,?) '
                             'ON CONFLICT(root,chat_id) DO NOTHING',
                             ((key, chat_id, previous[chat_id][0]) for chat_id in previous.keys() - present))
            conn.executemany('DELETE FROM chat_files WHERE root=? AND chat_id=?',
                             ((key, chat_id) for chat_id in previous.keys() - seen))
            _publish_rows(conn, updates, db_path)
            conn.execute('INSERT OR REPLACE INTO chat_catalog_state VALUES (?,?,?)', (key, PARSE_VERSION, recovery_error))
        return True


def _loop():
    configured_root = watched_root = None
    observer = None
    next_scan = 0

    def watch(current_root):
        nonlocal observer, watched_root
        if current_root != watched_root or observer is None:
            if observer:
                observer.stop()
            observer = _observe(current_root)
            watched_root = current_root

    while True:
        try:
            root = os.fspath(config.CHATS_FOLDER)
            if root != configured_root:
                if observer:
                    observer.stop()
                    observer = None
                configured_root, watched_root = root, None
                next_scan = 0
            if _wake.is_set() or time.monotonic() >= next_scan:
                _wake.clear()
                reconcile(root, before_read=watch)
                next_scan = time.monotonic() + 60
            with _event_lock:
                paths = list(_changed_paths)
                _changed_paths.clear()
            if paths:
                _apply_events(root, paths)
        except Exception as exc:
            logger.warning('聊天目录暂未完成对账: %s', exc)
            next_scan = min(time.monotonic() + 15, next_scan) if next_scan > time.monotonic() else time.monotonic() + 15
        _wake.wait(2)


def _observe(root):
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.event_type not in ('created', 'modified', 'moved', 'deleted'):
                    return
                if not event.is_directory:
                    queue_file_event(event.src_path, getattr(event, 'dest_path', ''))
                elif event.event_type in ('moved', 'deleted'):
                    request_reconcile()

        observer = Observer()
        observer.schedule(Handler(), root, recursive=True)
        observer.start()
        return observer
    except Exception as exc:
        logger.warning('聊天目录监听不可用，将定期对账: %s', exc)
        return None


@coordinated
@file_mutation
def _apply_events(root, paths, *, db_path=None):
    watched_root = root
    root, _ = register_root(root, db_path=db_path)
    key = root_key(root)
    with closing(state.connect(db_path)) as conn, conn:
        updates = []
        for path in paths:
            source = root if is_under_base(path, root) else watched_root
            if not is_under_base(path, source):
                continue
            chat_id = os.path.relpath(path, source).replace('\\', '/')
            if any(part.startswith('.') for part in chat_id.split('/')[:-1]):
                continue
            if conn.execute('SELECT 1 FROM chat_file_moves WHERE root=? AND (source=? OR target=?)',
                            (key, chat_id, chat_id)).fetchone():
                continue
            previous = conn.execute('''SELECT f.revision,f.parse_version FROM chat_files f
                WHERE f.root=? AND f.chat_id=? AND NOT EXISTS (
                    SELECT 1 FROM chat_missing_files m WHERE m.root=f.root AND m.chat_id=f.chat_id
                )''', (key, chat_id)).fetchone()
            try:
                row = _inspect(root, os.path.join(root, chat_id), chat_id, tuple(previous) if previous else None)
            except FileNotFoundError:
                # A move or delete requires a complete enumeration before removing rows.
                request_reconcile()
                continue
            if row:
                updates.append(row)
            elif row is None and previous:
                request_reconcile()
        if updates:
            conn.execute('BEGIN IMMEDIATE')
            _publish_rows(conn, updates, db_path)


def start_worker():
    global _worker
    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name='chat-catalog', daemon=True)
            _worker.start()
    request_reconcile()


def read_page(root, *, page, page_size, query, filter_type, fav_filter, card_id,
              resolve_card, card_root=None, db_path=None):
    """Read one SQLite snapshot, including the exact stats for the filtered query."""
    state.initialize(db_path)
    with closing(state.connect(db_path)) as conn, conn:
        conn.execute('BEGIN')
        key = _catalog_key(conn, root)
        status = conn.execute('SELECT parse_version,error FROM chat_catalog_state WHERE root=?', (key,)).fetchone()
        if not status or status[0] != PARSE_VERSION:
            return None, status[1] if status else ''
        prefix = _prefix_at(conn, key)
        if prefix is None:
            return None, ''
        lookup = card_lookup(conn, card_root, resolve_card)
        resolved = lookup(card_id) if card_id else None
        target = resolved['ui_key'] if resolved else ''

        def valid(ui_key, stored_uid):
            owner = _valid_owner(lookup, ui_key, stored_uid)
            return owner['card_name'] if owner else None

        conn.create_function('chat_lower', 1, lambda value: str(value or '').lower())
        conn.create_function('valid_chat_owner', 2, valid)
        # Read the indexed chat_id directly for the legacy library.
        storage_id = "(chat_root_prefix()||f.chat_id)" if prefix else 'f.chat_id'
        conn.create_function('chat_root_prefix', 0, lambda: prefix, deterministic=True)

        owners = f'''SELECT valid_chat_owner(b.card_ui_key,json_extract(u.payload_json,'$.card_uid')) AS card_name
            FROM chat_card_bindings b JOIN ui_records u ON u.key=b.card_ui_key WHERE b.chat_id={storage_id}'''
        local = 'coalesce(s.payload_json,\'{}\')'
        title = f"coalesce(nullif(trim(json_extract({local},'$.display_name')),''),f.name)"
        character = f"coalesce(nullif(trim(json_extract({local},'$.character_name')),''),f.character)"
        favorite = f"coalesce(json_extract({local},'$.favorite'),0)"
        bound = f'({owners} AND card_name IS NOT NULL ORDER BY chat_lower(card_name),b.card_ui_key LIMIT 1)'
        source = 'chat_files f'
        clauses, params = ['f.root=?'], [key]
        if card_id:
            source = 'chat_card_bindings target CROSS JOIN chat_files f'
            target_id = 'substr(target.chat_id,length(chat_root_prefix())+1)' if prefix else 'target.chat_id'
            if prefix:
                clauses.append('substr(target.chat_id,1,length(chat_root_prefix()))=chat_root_prefix()')
            clauses.extend(['target.card_ui_key=?', f'f.chat_id={target_id}', '''valid_chat_owner(target.card_ui_key,
                (SELECT json_extract(payload_json,'$.card_uid') FROM ui_records WHERE key=target.card_ui_key)) IS NOT NULL'''])
            params.append(target)
        source += f' LEFT JOIN chat_local_state s ON s.key={storage_id}'
        if filter_type == 'bound':
            clauses.append(f'{bound} IS NOT NULL')
        elif filter_type == 'unbound':
            clauses.append(f'{bound} IS NULL')
        if filter_type == 'favorites' or fav_filter == 'included':
            clauses.append(f'{favorite} != 0')
        if fav_filter == 'excluded':
            clauses.append(f'{favorite} = 0')
        if query:
            clauses.append(f"""instr(chat_lower({title}||' '||f.name||' '||{character}||' '||f.preview
                ||' '||coalesce({bound},'')||' '||coalesce(json_extract({local},'$.notes'),'')),?)>0""")
            params.append(query)
        selection = f"FROM {source} WHERE {' AND '.join(clauses)}"
        counts = conn.execute(f'''SELECT count(*),coalesce(sum({favorite} != 0),0),
            coalesce(sum({bound} IS NOT NULL),0) {selection}''', params).fetchone()
        page_ids = [row[0] for row in conn.execute(f'''SELECT f.chat_id {selection}
            ORDER BY ({favorite} != 0) DESC,f.mtime DESC,chat_lower({title}),f.chat_id LIMIT ? OFFSET ?''',
                                                  (*params, page_size, (page - 1) * page_size))]
        bound_by_id = {}
        page_rows = {}
        if page_ids:
            placeholders = ','.join('?' for _ in page_ids)
            page_rows = {row['chat_id']: row for row in conn.execute(f'''SELECT f.*,s.payload_json FROM chat_files f
                LEFT JOIN chat_local_state s ON s.key={storage_id} WHERE f.root=? AND f.chat_id IN ({placeholders})''',
                                                                    (key, *page_ids))}
            for chat_id, owner in conn.execute(f'''SELECT b.chat_id,b.card_ui_key FROM chat_card_bindings b
                JOIN ui_records u ON u.key=b.card_ui_key WHERE b.chat_id IN ({placeholders})
                AND valid_chat_owner(b.card_ui_key,json_extract(u.payload_json,'$.card_uid')) IS NOT NULL''',
                                               tuple(prefix + chat_id for chat_id in page_ids)):
                item = lookup(owner)
                if item:
                    bound_by_id.setdefault(local_chat_id(prefix, chat_id), []).append(item)
        items = []
        for chat_id in page_ids:
            row = page_rows[chat_id]
            entry = json.loads(row['payload_json'] or '{}')
            entry.update(json.loads(row['facts']), file_mtime=row['mtime'], file_size=row['size'])
            entry['import_time'] = entry.get('import_time') or row['mtime']
            bindings = sorted(bound_by_id.get(chat_id, []),
                              key=lambda item: (item['card_name'].lower(), item['ui_key']))
            items.append((chat_id, entry, bindings))
        total, favorites, bound_count = counts
        return (items, total, {'favorites': favorites, 'bound': bound_count,
                               'unbound': total - bound_count}), status[1]


def card_lookup(conn, card_root, fallback):
    """An indexed, request-local owner resolver; never traverses all card IDs."""
    from functools import lru_cache

    from core.data import card_list_projection as logical
    from core.data.index_runtime_store import get_active_generation

    generation = get_active_generation(conn, 'cards') if card_root and logical.installed(conn) else 0
    eligible = bool(generation and logical.eligible(conn, generation, card_root))
    wrong_root = bool(card_root and (not logical.metadata_matches(conn, card_root)
                                    or generation and logical.root_changed(conn, generation, card_root)))

    @lru_cache(maxsize=512)
    def lookup(card_id):
        if not card_id or card_id.startswith('_') or wrong_root:
            return None
        if not eligible:
            return fallback(card_id)
        parent = card_id.rpartition('/')[0]
        dirty = conn.execute('SELECT 1 FROM card_list_dirty WHERE generation=? AND key IN (?,?) LIMIT 1',
                             (generation, card_id, parent)).fetchone()
        item = conn.execute('''SELECT key,card_id,category,json_extract(payload,'$.char_name'),
            json_extract(payload,'$.card_uid') FROM card_list_items WHERE generation=? AND key=?''',
                            (generation, card_id)).fetchone()
        if item is None and parent and conn.execute('SELECT 1 FROM card_metadata WHERE id=?', (card_id,)).fetchone():
            item = conn.execute('''SELECT key,card_id,category,json_extract(payload,'$.char_name'),
                json_extract(payload,'$.card_uid') FROM card_list_items WHERE generation=? AND key=?''',
                                (generation, parent)).fetchone()
        if not item:
            if not dirty:
                return None
            item = conn.execute('SELECT id,id,category,char_name,card_uid FROM card_metadata WHERE id=?',
                                (card_id,)).fetchone()
            if not item:
                return None
        key, effective_id, category, name, uid = item
        if not dirty and key != effective_id:
            dirty = conn.execute('SELECT 1 FROM card_list_dirty WHERE generation=? AND key>=? AND key<? LIMIT 1',
                                 (generation, key + '/', key + '0')).fetchone()
        if dirty:
            current = conn.execute('SELECT char_name,card_uid FROM card_metadata WHERE id=?',
                                   (effective_id,)).fetchone()
            if key != effective_id:
                members = logical._members(conn, key)
                if not members:
                    return None
                effective_id, name, *_, uid = members[0]
                bundle_ui = logical.read_ui(conn, (key,)).get(key, {})
                current = name, bundle_ui.get('card_uid') or uid
            if not current:
                return None
            name, uid = current
        result = dict(ui_key=key, card_id=effective_id, category=category,
                      card_name=name or os.path.basename(effective_id), is_bundle=key != effective_id)
        if uid:
            result['card_uid'] = uid
        return result

    return lookup


def _valid_owner(lookup, ui_key, stored_uid):
    item = lookup(ui_key)
    if not item or item['ui_key'] != ui_key:
        return None
    actual = normalize_card_uid(item.get('card_uid'))
    stored_uid = normalize_card_uid(stored_uid)
    return item if not stored_uid or not actual or stored_uid == actual else None


def read_chat_bindings(chat_id, card_root, resolve_card):
    with closing(state.connect()) as conn, conn:
        conn.execute('BEGIN')
        lookup = card_lookup(conn, card_root, resolve_card)
        rows = conn.execute('''SELECT b.card_ui_key,json_extract(u.payload_json,'$.card_uid')
            FROM chat_card_bindings b JOIN ui_records u ON u.key=b.card_ui_key WHERE b.chat_id=?''', (chat_id,))
        owners = [item for key, uid in rows if (item := _valid_owner(lookup, key, uid))]
        return sorted(owners, key=lambda item: (item['card_name'].lower(), item['ui_key']))


def iter_discovered_chat_facts(root, chat_id=None):
    """Read only fields owned by the file projection."""
    state.initialize()
    with closing(state.connect()) as conn:
        clause = '' if chat_id is None else ' AND f.chat_id=?'
        args = (_catalog_key(conn, root), PARSE_VERSION)
        if chat_id is not None:
            args += (chat_id,)
        for key, facts, character, mtime, size in conn.execute('''SELECT f.chat_id,f.facts,f.character,f.mtime,f.size
            FROM chat_files f JOIN chat_catalog_state c ON c.root=f.root
            WHERE f.root=? AND c.parse_version=?''' + clause, args):
            yield key, dict(json.loads(facts), character_name=character,
                            file_mtime=mtime, import_time=mtime, file_size=size)


def merge_chat_facts(local, facts):
    from core.data.chat_store import normalize_chat_entry

    local = local if isinstance(local, dict) else {}
    if facts is None:
        return local
    return normalize_chat_entry({
        **local, **facts,
        'character_name': local.get('character_name') or facts.get('character_name'),
        'import_time': local.get('import_time') or facts.get('import_time'),
    })
