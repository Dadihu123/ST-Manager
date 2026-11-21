"""权威本地状态。锁顺序：卡片锁 -> repository；写事务内禁止外部 I/O/hook。

兼容快照按需读取，提交时只重放实际修改；不同字段合并，同字段冲突拒绝。
旧 JSON 只在首次迁移读取，激活后绝不回退或双写。
"""
from contextlib import contextmanager, closing, nullcontext
from copy import deepcopy
import hashlib
import json
import os
import sqlite3
import threading
import time

from core.config import DEFAULT_DB_PATH
from core.data.index_runtime_store import ensure_index_job_columns
from core.data.ui_store import UiDataLoadError, WORLDINFO_NOTES_KEY, worldinfo_note_rekeys
from core.utils.filesystem import filesystem_path_bucket, prepare_filesystem_path_match

SCHEMA_VERSION = 3
MAX_LEGACY_BYTES = 512 * 1024 ** 2
_MISSING = object()
_ready = {}
_lock = threading.RLock()


class LocalStateError(UiDataLoadError):
    pass


class StateConflict(LocalStateError):
    pass


def encode(value):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def plain(value):
    if isinstance(value, dict):
        return {key: plain(payload) for key, payload in value.items()}
    if isinstance(value, list):
        return [plain(payload) for payload in value]
    return value


def ensure_schema(conn):
    """SQL-only，不能访问旧文件或外部资源。"""
    for table in ('ui_records', 'chat_local_state'):
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (key TEXT PRIMARY KEY, "
                     "payload_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)")
    conn.execute("CREATE TABLE IF NOT EXISTS chat_card_bindings (card_ui_key TEXT NOT NULL, "
                 "chat_id TEXT NOT NULL, PRIMARY KEY(card_ui_key, chat_id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_binding_reverse ON chat_card_bindings(chat_id, card_ui_key)")
    conn.execute('CREATE TABLE IF NOT EXISTS card_resource_bindings(card_ui_key TEXT PRIMARY KEY, resource_folder TEXT NOT NULL)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_resource_binding_folder ON card_resource_bindings(resource_folder,card_ui_key)')
    conn.execute("CREATE TABLE IF NOT EXISTS local_state_migrations (id INTEGER PRIMARY KEY CHECK(id=1), "
                 "version INTEGER NOT NULL, state TEXT NOT NULL, fingerprint TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE TABLE IF NOT EXISTS local_state_clock (id INTEGER PRIMARY KEY CHECK(id=1), "
                 "revision INTEGER NOT NULL DEFAULT 0)")
    conn.execute('INSERT OR IGNORE INTO local_state_clock VALUES (1, 0)')
    conn.execute("CREATE TABLE IF NOT EXISTS card_ui_projections (card_id TEXT PRIMARY KEY, "
                 "ui_key TEXT NOT NULL, ui_revision INTEGER NOT NULL, source_revision TEXT NOT NULL, "
                 "generation INTEGER NOT NULL DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS index_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "job_type TEXT NOT NULL, entity_id TEXT DEFAULT '', source_path TEXT DEFAULT '', "
                 "payload_json TEXT DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending', "
                 "created_at REAL NOT NULL DEFAULT (strftime('%s','now')), started_at REAL DEFAULT 0, "
                 "finished_at REAL DEFAULT 0, error_msg TEXT DEFAULT '')")
    conn.execute("CREATE TABLE IF NOT EXISTS local_state_staging (component TEXT NOT NULL, key TEXT NOT NULL, "
                 "payload_json TEXT NOT NULL, PRIMARY KEY(component, key))")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_index_jobs_status_id ON index_jobs(status,id)')
    conn.execute('CREATE TABLE IF NOT EXISTS ui_namespace_roots(namespace TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS ui_namespace_records(namespace TEXT NOT NULL, '
                 'key TEXT NOT NULL,payload_json TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1, '
                 'PRIMARY KEY(namespace,key))')
    ensure_index_job_columns(conn)
    if not any(row[1] == 'folder_key' for row in conn.execute('PRAGMA table_info(card_resource_bindings)')):
        conn.execute('ALTER TABLE card_resource_bindings ADD COLUMN folder_key TEXT')
        bindings = conn.execute('SELECT card_ui_key,resource_folder FROM card_resource_bindings')
        conn.executemany('UPDATE card_resource_bindings SET folder_key=? WHERE card_ui_key=?',
                         ((filesystem_path_bucket(folder), key) for key, folder in bindings))
    conn.execute('CREATE INDEX IF NOT EXISTS idx_resource_binding_folder_key '
                 'ON card_resource_bindings(folder_key,card_ui_key)')
    from core.data.card_list_projection import ensure_schema as ensure_card_list_schema
    from core.services.chat_catalog_service import ensure_schema as ensure_chat_catalog_schema
    ensure_card_list_schema(conn)
    ensure_chat_catalog_schema(conn)
    if 'generation' not in {row[1] for row in conn.execute('PRAGMA table_info(card_ui_projections)')}:
        conn.execute('ALTER TABLE card_ui_projections ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
        _queue_stale_legacy_card_notes(conn)


def _queue_stale_legacy_card_notes(conn):
    """旧凭据没有代号，且可能已误确认任务。只为活动代中已过期的备注安排修复。"""
    from core.config import CARDS_FOLDER
    from core.data.index_runtime_store import get_active_generation
    from core.services.index_build_service import _card_ui_projection, cached_bundle_cover_lookup

    active = get_active_generation(conn, 'cards')
    if not active or not conn.execute('SELECT 1 FROM card_ui_projections LIMIT 1').fetchone():
        return
    rows = conn.execute('SELECT p.card_id,p.ui_key,e.source_path,e.summary_preview FROM card_ui_projections p '
                        'JOIN card_metadata m ON m.id=p.card_id LEFT JOIN index_entities_v2 e '
                        "ON e.generation=? AND e.entity_id='card::'||p.card_id ORDER BY p.card_id", (active,))
    repo = Repository()
    lookup_cover = cached_bundle_cover_lookup(conn)
    ui = {}
    while batch := rows.fetchmany(200):
        keys = {r[1] for r in batch} | {r[0].rpartition('/')[0] for r in batch if '/' in r[0]}
        # 同一 bundle 跨批时复用父记录，避免反复解码完整版本备注。
        ui = {key: ui[key] for key in keys if key in ui}
        ui.update((key, value) for key, (value, _) in repo.get_many(keys - ui.keys(), conn=conn).items())
        jobs = []
        for card_id, key, path, summary in batch:
            if summary != _card_ui_projection(ui, card_id, key, lookup_cover=lookup_cover)[1]:
                jobs.append((card_id, path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)),
                             encode({'ui_key': key})))
        conn.executemany("INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) "
                         "VALUES ('upsert_card',?,?,?)", jobs)


def record_card_projection(conn, card_id, ui_key, ui_revision, source_revision, generation):
    conn.execute('INSERT OR REPLACE INTO card_ui_projections '
                 '(card_id,ui_key,ui_revision,source_revision,generation) VALUES (?,?,?,?,?)',
                 (card_id, ui_key, ui_revision, source_revision, generation))


def card_projection_matches(conn, card_id, ui_key, ui_revision, source_revision, generation):
    return generation > 0 and conn.execute(
        'SELECT 1 FROM card_ui_projections WHERE card_id=? AND ui_key=? AND ui_revision=? '
        'AND source_revision=? AND generation=?',
        (card_id, ui_key, ui_revision, source_revision, generation)).fetchone() is not None


def connect(path=None):
    conn = sqlite3.connect(path or DEFAULT_DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    # 权威状态至少保持文件 fsync 级耐久性；所有同库连接也必须使用 FULL。
    conn.execute('PRAGMA synchronous=FULL')
    conn.row_factory = sqlite3.Row
    return conn


def _write_authority_marker(db_path):
    with open(db_path + '.local-state-authority', 'w', encoding='utf-8') as marker:
        marker.write(str(SCHEMA_VERSION))
        marker.flush()
        os.fsync(marker.fileno())


def _legacy(path):
    def decode(raw):
        if len(raw) > MAX_LEGACY_BYTES:
            raise LocalStateError('旧状态超过 512 MiB 迁移预算: ' + path)
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('top level must be an object')
        encode(value)
        return value, raw

    try:
        with open(path, 'rb') as stream:
            raw = stream.read(MAX_LEGACY_BYTES + 1)
    except FileNotFoundError:
        raw = None
    try:
        if raw is not None:
            return decode(raw)
    except (ValueError, UnicodeError):
        pass
    # 只对确认的缺失/格式损坏选用经过验证的备份，访问失败必须传播。
    found_backup = False
    for suffix in ('.bak', '.bak.1', '.bak.2'):
        try:
            with open(path + suffix, 'rb') as backup:
                backup_raw = backup.read(MAX_LEGACY_BYTES + 1)
        except FileNotFoundError:
            continue
        found_backup = True
        try:
            return decode(backup_raw)
        except (ValueError, UnicodeError):
            continue
    if raw is not None or found_backup:
        raise LocalStateError('旧状态及备份损坏，迁移未激活: ' + path)
    return {}, b''


def normalize_record(component, payload, key=''):
    if not isinstance(payload, dict):
        return payload
    if component == 'chat':
        from core.data.chat_store import normalize_chat_entry
        return normalize_chat_entry(payload)
    if key.startswith('_'):
        return deepcopy(payload)
    from core.data.ui_store import _normalize_timestamp, IMPORT_TIME_KEY, LAST_SENT_TO_ST_KEY, LAST_SENT_TO_TT_KEY
    from core.consts import RESERVED_RESOURCE_NAMES
    result = deepcopy(payload)
    resource = result.get('resource_folder')
    if isinstance(resource, str) and resource.replace('\\', '/').split('/')[0].lower() in RESERVED_RESOURCE_NAMES:
        result['resource_folder'] = ''
    for field in (IMPORT_TIME_KEY, LAST_SENT_TO_ST_KEY, LAST_SENT_TO_TT_KEY):
        if field in result:
            normalized = _normalize_timestamp(result[field])
            if normalized is None:
                result.pop(field)
            else:
                result[field] = normalized
    return result


def _bindings(conn, key, value):
    conn.execute('DELETE FROM chat_card_bindings WHERE card_ui_key=?', (key,))
    conn.execute('DELETE FROM card_resource_bindings WHERE card_ui_key=?', (key,))
    if isinstance(value, dict) and isinstance(value.get('resource_folder'), str) and value['resource_folder'].strip():
        folder = value['resource_folder'].strip()
        conn.execute('INSERT INTO card_resource_bindings(card_ui_key,resource_folder,folder_key) VALUES (?,?,?)',
                     (key, folder, filesystem_path_bucket(folder)))
    if isinstance(value, dict) and isinstance(value.get('chat_ids'), list):
        conn.executemany('INSERT OR IGNORE INTO chat_card_bindings VALUES (?, ?)',
                         [(key, item) for item in value['chat_ids'] if isinstance(item, str) and item])


def _refresh_existing_worldinfo_index(conn, *, force=False):
    from core.data.index_runtime_store import get_active_generation
    from core.services.index_build_service import worldinfo_summaries_match

    generation = get_active_generation(conn, 'worldinfo')
    if not generation:
        return
    payload = {'scope': 'worldinfo'}
    migration = dict(payload, note_migration_generation=generation)
    if conn.execute("SELECT 1 FROM index_jobs WHERE job_type='rebuild_scope' AND status='pending' "
                    "AND payload_json IN (?,?,?) LIMIT 1",
                    (encode(migration), encode(payload), json.dumps(payload))).fetchone():
        return
    if force or not worldinfo_summaries_match(conn, generation):
        conn.execute("INSERT INTO index_jobs(job_type,payload_json) VALUES ('rebuild_scope',?)", (encode(migration),))


def _upgrade_worldinfo_note_keys(conn):
    keys = [r[0] for r in conn.execute('SELECT key FROM ui_namespace_records WHERE namespace=?',
                                       (WORLDINFO_NOTES_KEY,))]
    def read(key):
        return json.loads(conn.execute('SELECT payload_json FROM ui_namespace_records WHERE namespace=? AND key=?',
                                       (WORLDINFO_NOTES_KEY, key)).fetchone()[0])
    changed = False
    for old, new in worldinfo_note_rekeys(keys, read):
        conn.execute('UPDATE ui_namespace_records SET key=?,revision=revision+1 WHERE namespace=? AND key=?',
                     (new, WORLDINFO_NOTES_KEY, old))
        changed = True
    if changed:
        conn.execute('UPDATE ui_records SET revision=revision+1 WHERE key=?', (WORLDINFO_NOTES_KEY,))
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')


def _activate(conn, *, refresh_existing_index=False):
    conn.execute('DELETE FROM ui_namespace_roots')
    conn.execute('DELETE FROM ui_namespace_records')
    for component, table in (('ui', 'ui_records'), ('chat', 'chat_local_state')):
        conn.execute(f'DELETE FROM {table}')
        conn.execute(f"INSERT INTO {table}(key, payload_json) SELECT key, payload_json "
                     "FROM local_state_staging WHERE component=?", (component,))
    conn.execute('DELETE FROM chat_card_bindings')
    conn.execute('DELETE FROM card_resource_bindings')
    for row in conn.execute('SELECT key, payload_json FROM ui_records').fetchall():
        value = json.loads(row[1])
        _bindings(conn, row[0], value)
        if row[0].startswith('_') and isinstance(value, dict):
            _replace_namespace(conn, row[0], value)
    _refresh_existing_worldinfo_index(conn, force=refresh_existing_index)
    conn.execute("UPDATE local_state_migrations SET state='activated',version=? WHERE id=1", (SCHEMA_VERSION,))
    conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')
    conn.execute('DELETE FROM local_state_staging')


def initialize(path=None, ui_path=None, chat_path=None):
    try:
        return _initialize(path, ui_path, chat_path)
    except (OSError, sqlite3.Error) as exc:
        raise LocalStateError('本地状态不可用，禁止写入或回退旧 JSON') from exc


def _initialize(path=None, ui_path=None, chat_path=None):
    """独占迁移；preparing/imported 均可重复启动，最终切换单事务提交。"""
    from core.data import ui_store, chat_store
    db_path = os.path.abspath(path or DEFAULT_DB_PATH)
    ui_path, chat_path = ui_path or ui_store.UI_DATA_FILE, chat_path or chat_store.CHAT_DATA_FILE
    identity = (db_path, os.path.abspath(ui_path), os.path.abspath(chat_path))
    with _lock:
        if identity in _ready:
            if not os.path.isfile(db_path):
                raise LocalStateError('已激活的权威数据库丢失，禁止回退旧 JSON')
            return
        if os.path.exists(db_path + '.local-state-authority') and not os.path.isfile(db_path):
            raise LocalStateError('权威数据库丢失，必须显式恢复')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        from core.data.data_dir_lock import _try_lock_handle, _unlock_handle
        with open(db_path + '.migration.lock', 'a+', encoding='utf-8') as handle:
            if not _try_lock_handle(handle):
                raise LocalStateError('本地状态正在由另一进程迁移')
            try:
                with closing(connect(db_path)) as conn:
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if os.path.exists(db_path + '.local-state-authority'):
                        required = {'ui_records', 'chat_local_state', 'chat_card_bindings',
                                    'local_state_migrations', 'local_state_clock',
                                    'ui_namespace_roots', 'ui_namespace_records', 'card_resource_bindings'}
                        if not required.issubset(tables):
                            raise LocalStateError('权威数据库结构损坏，必须显式恢复，禁止自动建空表')
                    ensure_schema(conn)
                    conn.commit()
                    row = conn.execute('SELECT * FROM local_state_migrations WHERE id=1').fetchone()
                    if not row and os.path.exists(db_path + '.local-state-authority'):
                        raise LocalStateError('已激活的权威数据库状态缺失，禁止重新导入旧 JSON')
                    if row and row['version'] not in (1, 2, SCHEMA_VERSION):
                        raise LocalStateError('不支持的本地状态版本')
                    if row and row['state'] == 'activated':
                        if row['version'] < SCHEMA_VERSION:
                            with conn:
                                conn.execute('BEGIN IMMEDIATE')
                                if row['version'] == 1:
                                    _upgrade_worldinfo_note_keys(conn)
                                _refresh_existing_worldinfo_index(conn, force=row['version'] == 1)
                                conn.execute('UPDATE local_state_migrations SET version=? WHERE id=1', (SCHEMA_VERSION,))
                        _write_authority_marker(db_path)
                        _ready[identity] = True
                        return
                    if row and row['state'] == 'imported':
                        _write_authority_marker(db_path)
                        with conn:
                            _activate(conn, refresh_existing_index=row['version'] == 1)
                        _ready[identity] = True
                        return
                    sources = [('ui', ui_path, *_legacy(ui_path)), ('chat', chat_path, *_legacy(chat_path))]
                    fingerprint = hashlib.sha256(b''.join(item[3] for item in sources)).hexdigest()
                    # 保存 WAL 中已提交的数据；不直接复制主数据库文件。
                    backup_path = db_path + '.before-local-state.sqlite3'
                    if not os.path.exists(backup_path):
                        with closing(sqlite3.connect(backup_path)) as backup:
                            conn.backup(backup)
                    with conn:
                        conn.execute("INSERT OR REPLACE INTO local_state_migrations VALUES (1, ?, 'preparing', ?)",
                                     (SCHEMA_VERSION, fingerprint))
                        conn.execute('DELETE FROM local_state_staging')
                    for component, source_path, value, raw in sources:
                        value = {key: normalize_record(component, payload, key) for key, payload in value.items()}
                        if raw:
                            snapshot = source_path + '.before-local-state'
                            if not os.path.exists(snapshot):
                                with open(snapshot, 'xb') as output:
                                    output.write(raw)
                                    output.flush()
                                    os.fsync(output.fileno())
                        rows = [(component, key, encode(payload)) for key, payload in value.items()]
                        for start in range(0, len(rows), 500):
                            with conn:
                                conn.executemany('INSERT INTO local_state_staging VALUES (?, ?, ?)', rows[start:start+500])
                        restored = {row[0]: json.loads(row[1]) for row in conn.execute(
                            'SELECT key, payload_json FROM local_state_staging WHERE component=?', (component,))}
                        if encode(restored) != encode(value):
                            raise LocalStateError('本地状态迁移校验失败')
                    with conn:
                        conn.execute("UPDATE local_state_migrations SET state='imported' WHERE id=1")
                    _write_authority_marker(db_path)
                    with conn:
                        _activate(conn)
                    _ready[identity] = True
            except (OSError, sqlite3.Error) as exc:
                raise LocalStateError('本地状态不可用，禁止写入或回退旧 JSON') from exc
            finally:
                _unlock_handle(handle)


def merge(current, original, edited):
    if edited == original:
        return current
    if isinstance(original, dict) and isinstance(edited, dict) and isinstance(current, dict):
        result = deepcopy(current)
        for key in original.keys() | edited.keys():
            before, after = original.get(key, _MISSING), edited.get(key, _MISSING)
            if before == after:
                continue
            now = current.get(key, _MISSING)
            if after is _MISSING:
                if now != before and now is not _MISSING:
                    raise StateConflict('同字段已被其他请求修改: ' + key)
                result.pop(key, None)
            else:
                result[key] = merge(now, before, after)
        return result
    if current != original and current != edited:
        raise StateConflict('同字段已被其他请求修改，请重新载入')
    return deepcopy(edited)


class Repository:
    def __init__(self, component='ui', path=None):
        if component not in ('ui', 'chat'):
            raise ValueError('unknown local state component')
        self.component, self.path = component, path
        self.table = 'ui_records' if component == 'ui' else 'chat_local_state'

    @contextmanager
    def transaction(self):
        from core.services.maintenance_gate import gate
        with gate.activity():
            with self._transaction() as conn:
                yield conn

    def _enclosing_writer(self):
        # Flask 路由已经持有同库写事务时，复用它；绝不能再打开竞争写连接。
        from flask import has_app_context, g
        enclosing = g.get('db') if has_app_context() else None
        if enclosing is not None and getattr(enclosing, 'in_transaction', False):
            database = enclosing.execute('PRAGMA database_list').fetchone()[2]
            if os.path.normcase(os.path.abspath(database)) == os.path.normcase(os.path.abspath(self.path or DEFAULT_DB_PATH)):
                return enclosing
        return None

    @contextmanager
    def _transaction(self):
        initialize(self.path)
        enclosing = self._enclosing_writer()
        if enclosing is not None:
            enclosing.execute('SAVEPOINT local_state_update')
            try:
                yield enclosing
                enclosing.execute('RELEASE local_state_update')
            except Exception:
                enclosing.execute('ROLLBACK TO local_state_update')
                enclosing.execute('RELEASE local_state_update')
                raise
            return
        with closing(connect(self.path)) as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_many(self, keys=None, *, conn=None):
        if conn is None:
            initialize(self.path)
            try:
                with closing(connect(self.path)) as reader:
                    reader.execute('BEGIN')
                    return self.get_many(keys, conn=reader)
            except (sqlite3.Error, OSError, ValueError) as exc:
                raise LocalStateError('权威状态读取失败，禁止回退旧 JSON') from exc
        if keys is None:
            rows = conn.execute(f'SELECT key,payload_json,revision FROM {self.table}')
        else:
            keys = list(dict.fromkeys(keys))
            result = {}
            for start in range(0, len(keys), 400):
                batch = keys[start:start+400]
                rows = conn.execute(f"SELECT key,payload_json,revision FROM {self.table} WHERE key IN "
                                    f"({','.join('?' for _ in batch)})", batch)
                result.update({r[0]: (self._decode_record(r, conn), r[2]) for r in rows.fetchall()})
            return result
        return {r[0]: (self._decode_record(r, conn), r[2]) for r in rows.fetchall()}

    def _decode_record(self, row, conn):
        if self.component == 'ui' and row[0].startswith('_') and conn.execute(
                'SELECT 1 FROM ui_namespace_roots WHERE namespace=?', (row[0],)).fetchone():
            # 根与成员来自同一事务；仅冻结原始 JSON，保留大 namespace 的按需解码。
            records = {r[0]: (r[1], r[2]) for r in conn.execute(
                'SELECT key,payload_json,revision FROM ui_namespace_records WHERE namespace=?', (row[0],))}
            return StateSnapshot(NamespaceRepository(row[0], self.path), root_revision=row[2], records=records)
        return json.loads(row[1])

    def get(self, key, default=None, *, conn=None):
        return self.get_many([key], conn=conn).get(key, (deepcopy(default), 0))[0]

    def get_namespace_members(self, key, members, *, conn=None):
        """在一个短读事务内取得根版本及指定成员，完整根读取仍由 get 提供。"""
        if self.component != 'ui' or not key.startswith('_'):
            raise ValueError('namespace requires an underscore UI key')
        members = list(dict.fromkeys(members))
        if conn is None:
            initialize(self.path)
            try:
                with closing(connect(self.path)) as reader:
                    reader.execute('BEGIN')
                    return self.get_namespace_members(key, members, conn=reader)
            except (sqlite3.Error, OSError, ValueError) as exc:
                raise LocalStateError('权威命名空间读取失败') from exc
        row = conn.execute('SELECT key,payload_json,revision FROM ui_records WHERE key=?', (key,)).fetchone()
        if row is None:
            return _MISSING
        if not conn.execute('SELECT 1 FROM ui_namespace_roots WHERE namespace=?', (key,)).fetchone():
            return json.loads(row[1])
        repository = NamespaceRepository(key, self.path)
        return StateSnapshot(repository, root_revision=row[2], records=repository._read_records(members, conn=conn),
                             record_keys=members, records_complete=False)

    def revision(self, key=None):
        initialize(self.path)
        with closing(connect(self.path)) as conn:
            if key is None:
                row = conn.execute('SELECT revision FROM local_state_clock WHERE id=1').fetchone()
            else:
                row = conn.execute(f'SELECT revision FROM {self.table} WHERE key=?', (key,)).fetchone()
            return row[0] if row else 0

    def _put(self, conn, key, value, *, defer_projection=False, prepared_notes=False):
        value = normalize_record(self.component, value, key)
        previous = self.get(key, None, conn=conn)
        conn.execute(f'INSERT INTO {self.table}(key,payload_json,revision) '
                     'VALUES (?,?,(SELECT revision+1 FROM local_state_clock WHERE id=1)) '
                     'ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, revision=excluded.revision',
                     (key, encode(value)))
        if self.component == 'ui':
            if key.startswith('_') and isinstance(value, dict):
                _replace_namespace(conn, key, value, prepared_notes=prepared_notes)
            else:
                conn.execute('DELETE FROM ui_namespace_records WHERE namespace=?', (key,))
                conn.execute('DELETE FROM ui_namespace_roots WHERE namespace=?', (key,))
            _bindings(conn, key, value)
            self._project_ui(conn, key, previous, value, defer_projection=defer_projection)
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')

    def _project_ui(self, conn, key, previous, value, *, defer_projection=False):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_metadata'").fetchone():
            return
        revision_row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (key,)).fetchone()
        revision = revision_row[0] if revision_row else 0
        # bundle 只扩展直接子版本，未知命名空间和非对象值原样保存。
        rows = conn.execute('SELECT id FROM card_metadata WHERE id=? UNION ALL '
                            'SELECT id FROM card_metadata WHERE id>=? AND id<?',
                            (key, key + '/', key + '/\uffff')).fetchall()
        old, new = previous if isinstance(previous, dict) else {}, value if isinstance(value, dict) else {}
        resource_changed = str(old.get('resource_folder') or '').strip() != str(new.get('resource_folder') or '').strip()
        from core.data.index_runtime_store import get_active_generation
        from core.services.index_build_service import apply_card_increment
        generation = (get_active_generation(conn, 'cards') if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='index_build_state'").fetchone() else 0)
        for row in rows:
            card_id = row[0]
            if card_id != key and card_id.rsplit('/', 1)[0] != key:
                continue
            existing = conn.execute('SELECT source_path,source_revision FROM index_entities_v2 '
                                    'WHERE generation=? AND entity_id=?', (generation, 'card::' + card_id)).fetchone() if generation > 0 else None
            source_path, source_revision = (existing[0], existing[1]) if existing else ('', '')
            # 没有文件变化；搜索投影、UI 记录及任务意图属于同一事务。
            applied = generation > 0 and existing is not None and not defer_projection
            if applied:
                apply_card_increment(conn, card_id, source_path, commit=False,
                                     ui_data={key: value}, source_revision=source_revision, ui_key=key)
                record_card_projection(conn, card_id, key, revision, source_revision, generation)
            payload = encode({'ui_key': key, 'ui_revision': revision})
            conn.execute("INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json,status) "
                         "VALUES ('upsert_card',?,?,?,?)",
                         (card_id, source_path, payload, 'done' if applied else 'pending'))
            if resource_changed:
                owner_payload = encode({'ui_key': key, 'ui_revision': revision,
                                        **({'remove_owner_ids': [card_id]} if value is None else {})})
                conn.execute("INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) "
                             "VALUES ('upsert_world_owner',?,?,?)", (card_id, source_path, owner_payload))
        # 同步完成的任务也有有界保留，避免普通备注不断扩大队列表。
        conn.execute("DELETE FROM index_jobs WHERE status='done' AND id < COALESCE("
                     "(SELECT id FROM index_jobs WHERE status='done' ORDER BY id DESC LIMIT 1 OFFSET 199),0)")

    def update_fields(self, key, fields, *, conn=None):
        return self.update_many({key: fields}, conn=conn)

    def update_many(self, updates, *, conn=None):
        if conn is None:
            with self.transaction() as writer:
                return self.update_many(updates, conn=writer)
        for key, fields in updates.items():
            if (self.component == 'ui' and key.startswith('_') and isinstance(fields, dict)
                    and conn.execute('SELECT 1 FROM ui_namespace_roots WHERE namespace=?', (key,)).fetchone()):
                namespace = NamespaceRepository(key, self.path)
                for member, value in fields.items():
                    namespace._put(conn, member, value)
                continue
            current = self.get(key, {}, conn=conn)
            if not isinstance(current, dict) or not isinstance(fields, dict):
                raise ValueError('update_fields requires objects')
            current.update(deepcopy(fields))
            self._put(conn, key, current)
        return True

    def delete(self, key, *, conn=None):
        if conn is None:
            with self.transaction() as writer:
                return self.delete(key, conn=writer)
        previous = self.get(key, conn=conn)
        conn.execute(f'DELETE FROM {self.table} WHERE key=?', (key,))
        if self.component == 'ui':
            conn.execute('DELETE FROM chat_card_bindings WHERE card_ui_key=?', (key,))
            conn.execute('DELETE FROM card_resource_bindings WHERE card_ui_key=?', (key,))
            conn.execute('DELETE FROM ui_namespace_records WHERE namespace=?', (key,))
            conn.execute('DELETE FROM ui_namespace_roots WHERE namespace=?', (key,))
            self._project_ui(conn, key, previous, None)
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')

    def export_snapshot(self):
        initialize(self.path)
        with closing(connect(self.path)) as conn:
            conn.execute('BEGIN')
            return _export_at(conn, self.component)

    def replace_snapshot(self, value):
        if not isinstance(value, dict):
            raise ValueError('state must be an object')
        with self.transaction() as conn:
            conn.execute(f'DELETE FROM {self.table}')
            if self.component == 'ui':
                conn.execute('DELETE FROM chat_card_bindings')
                conn.execute('DELETE FROM card_resource_bindings')
                conn.execute('DELETE FROM ui_namespace_records')
                conn.execute('DELETE FROM ui_namespace_roots')
            for key, payload in value.items():
                self._put(conn, key, payload)

    def save(self, snapshot, *, conn=None, worldinfo_jobs=(), worldinfo_note_move=None, require_unchanged=()):
        def prepare_refreshes(can_probe):
            prepared = []
            for job in worldinfo_jobs:
                if job['job_type'] == 'upsert_worldinfo_path':
                    # 外层事务已开始时只使用已采集的目录属性；不明确就保留独立刷新意图。
                    match = prepare_filesystem_path_match(job.get('source_path', ''), probe=can_probe)
                    job = {**job, 'path_matches': match}
                prepared.append(job)
            return prepared

        def enqueue_refreshes(writer, prepared):
            if worldinfo_note_move is not None:
                _move_worldinfo_note_paths(writer, *worldinfo_note_move)
            if prepared:
                from core.services.index_job_worker import enqueue_index_job
                for job in prepared:
                    if job.get('if_card_not_projected'):
                        # 有元数据的卡片已由绑定投影写入；尚未扫描的卡片也保留刷新意图。
                        job = dict(job)
                        job.pop('if_card_not_projected')
                        card_id, ui_key = job['entity_id'], job['payload']['ui_key']
                        metadata_exists = writer.execute(
                            "SELECT 1 FROM sqlite_master WHERE name='card_metadata'"
                        ).fetchone()
                        if (metadata_exists and ui_key in (card_id, card_id.rsplit('/', 1)[0])
                                and writer.execute('SELECT 1 FROM card_metadata WHERE id=?', (card_id,)).fetchone()):
                            continue
                    enqueue_index_job(conn=writer, **job)

        def prepare_value(key, value, can_probe):
            if can_probe and self.component == 'ui' and key == WORLDINFO_NOTES_KEY and isinstance(value, dict):
                return _canonicalize_worldinfo_notes(value)
            return value

        if not isinstance(snapshot, StateSnapshot):
            if not isinstance(snapshot, dict):
                raise LocalStateError('状态必须是对象')
            enclosing = conn if conn is not None else self._enclosing_writer()
            can_probe = enclosing is None or not enclosing.in_transaction
            prepared = prepare_refreshes(can_probe)
            values = [(key, prepare_value(key, value, can_probe)) for key, value in snapshot.items()]
            # 无基线仅能创建新记录；从不允许覆盖已有记录或隐式删除。
            with (self.transaction() if conn is None else nullcontext(conn)) as conn:
                if self.get_many(snapshot.keys(), conn=conn):
                    raise StateConflict('已有记录需要带基线的快照；导入请使用 replace_snapshot')
                for key, value in values:
                    self._put(conn, key, value, prepared_notes=True)
                enqueue_refreshes(conn, prepared)
            return True
        if snapshot.repository.component != self.component:
            raise LocalStateError('状态快照类型不匹配')
        for key in require_unchanged:
            snapshot._load(key)
        # 对象序列化、差异计算在取得写锁前完成。
        changes, namespaces, replaced_namespaces = [], [], {}
        for key, before in snapshot.baseline.items():
            after = dict.get(snapshot, key, _MISSING)
            if (isinstance(after, StateSnapshot) and after.repository.component == 'namespace'
                    and isinstance(before, StateSnapshot)):
                if after.changed():
                    namespaces.append(after)
                continue
            if isinstance(before, StateSnapshot) and before.repository.component == 'namespace':
                # 整个 namespace 替换/删除不能在此刻重新读取一个漂移的懒基线。
                replaced_namespaces[key] = before.root_revision
                changes.append((key, before, plain(after) if after is not _MISSING else _MISSING))
            elif before != after:
                changes.append((key, before, deepcopy(after) if after is not _MISSING else _MISSING))
        if not changes and not namespaces and not worldinfo_jobs and worldinfo_note_move is None and not require_unchanged:
            return True
        enclosing = conn if conn is not None else self._enclosing_writer()
        can_probe = enclosing is None or not enclosing.in_transaction
        prepared = prepare_refreshes(can_probe)
        # 定向备注已经在调用方规范化。兼容的整根替换也在取得写锁前规范化；
        # 外层事务已开始时保留提交的键，避免在写锁下猜测离线目录的大小写规则。
        changes = [(key, before, prepare_value(key, after, can_probe)) for key, before, after in changes]
        owns_commit = enclosing is None
        with (self.transaction() if conn is None else nullcontext(conn)) as conn:
            for key in require_unchanged:
                before = snapshot.baseline[key]
                row = conn.execute(f'SELECT payload_json,revision FROM {self.table} WHERE key=?', (key,)).fetchone()
                if isinstance(before, StateSnapshot):
                    unchanged = row is not None and row[1] == before.root_revision
                else:
                    unchanged = (json.loads(row[0]) if row is not None else _MISSING) == before
                if not unchanged:
                    raise StateConflict('记录已被其他请求修改，请重新读取: ' + key)
            if self.component == 'namespace':
                row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (self.namespace,)).fetchone()
                starting_revision = row[0] if row else 0
            for namespace in namespaces:
                namespace.defer_projection = getattr(snapshot, 'defer_projection', False)
                namespace.repository.save(namespace, conn=conn)
            for key, before, after in changes:
                if (self.component == 'ui' and key == WORLDINFO_NOTES_KEY and before is _MISSING
                        and isinstance(after, dict) and conn.execute(
                            'SELECT 1 FROM ui_namespace_roots WHERE namespace=?', (key,)).fetchone()):
                    # 两本书都观察到空根时，后提交的备注仍可按成员合并。
                    notes = NamespaceRepository(key, self.path)
                    current = notes.get_many(after, conn=conn)
                    for note_key, edited in after.items():
                        now = current.get(note_key, (_MISSING, 0))[0]
                        merged = merge(now, _MISSING, edited)
                        if merged != now:
                            notes._put(conn, note_key, merged)
                    continue
                if key in replaced_namespaces:
                    row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (key,)).fetchone()
                    if (row[0] if row else 0) != replaced_namespaces[key]:
                        raise StateConflict('命名空间已被其他请求修改，请重新读取: ' + key)
                    before = self.get(key, conn=conn)
                    before = plain(before)
                current = self.get_many([key], conn=conn).get(key, (_MISSING, 0))[0]
                if after is _MISSING:
                    if current != before and current is not _MISSING:
                        raise StateConflict('删除的记录已被修改: ' + key)
                    self.delete(key, conn=conn)
                else:
                    if self.component == 'chat' and all(isinstance(item, dict) for item in (current, before, after)):
                        # updated_at 是派生时间，不能让备注与阅读进度等不同字段互相冲突。
                        value = merge(*({k: v for k, v in item.items() if k != 'updated_at'}
                                        for item in (current, before, after)))
                        from core.data.chat_store import _normalize_timestamp
                        value['updated_at'] = max(time.time(), _normalize_timestamp(current.get('updated_at')),
                                                  _normalize_timestamp(after.get('updated_at')))
                    else:
                        value = merge(current, before, after)
                    kwargs = {'prepared_notes': True} if self.component == 'ui' and key == WORLDINFO_NOTES_KEY else {}
                    self._put(conn, key, value, defer_projection=getattr(snapshot, 'defer_projection', False), **kwargs)
            enqueue_refreshes(conn, prepared)
            if self.component == 'namespace':
                row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (self.namespace,)).fetchone()
                revision = row[0] if row else 0
                if snapshot._records is not None and not snapshot._records_complete:
                    # 定向快照只确认已观察的成员；以后扩展成员时必须校验这个根版本。
                    keys = snapshot._record_keys | snapshot.baseline.keys()
                    records = self._read_records(keys, conn=conn)
                    snapshot._pending_namespace = (revision, records, set(keys))
                elif snapshot.root_revision == starting_revision:
                    # 完整冻结视图没有遗漏并发写入时，才能提升其整根替换基线。
                    records = dict(snapshot._records) if snapshot._records is not None else None
                    if records is not None:
                        for key, _, _ in changes:
                            records.pop(key, None)
                        records.update(self._read_records([key for key, _, _ in changes], conn=conn))
                    snapshot._pending_namespace = (revision, records, set(records or ()))
                else:
                    snapshot._pending_namespace = None
        # 只有真正提交的事务拥有者可以确认基线；savepoint release 不代表耐久提交。
        if owns_commit:
            snapshot.confirm_saved()
        return True

    def has_unobserved(self, observed):
        initialize(self.path)
        with closing(connect(self.path)) as conn:
            return any(row[0] not in observed for row in conn.execute(f'SELECT key FROM {self.table}'))


def _canonicalize_worldinfo_notes(value):
    changes = list(worldinfo_note_rekeys(value, value.__getitem__))
    if changes:
        value = dict(value)
        for old, new in changes:
            value[new] = value.pop(old)
    return value


def _replace_namespace(conn, namespace, value, *, prepared_notes=False):
    if namespace == WORLDINFO_NOTES_KEY and not prepared_notes:
        value = _canonicalize_worldinfo_notes(value)
    conn.execute('INSERT OR IGNORE INTO ui_namespace_roots VALUES (?)', (namespace,))
    conn.execute('DELETE FROM ui_namespace_records WHERE namespace=?', (namespace,))
    conn.executemany('INSERT INTO ui_namespace_records(namespace,key,payload_json) VALUES (?,?,?)',
                     [(namespace, key, encode(payload)) for key, payload in value.items()])
    conn.execute("UPDATE ui_records SET payload_json='{}' WHERE key=?", (namespace,))


def _move_worldinfo_note_paths(conn, old_prefix, new_prefix):
    # '/' 与 '0' 相邻，范围只覆盖旧目录下的成员。主键冲突会中止整次状态保存。
    cursor = conn.execute(
        'UPDATE ui_namespace_records SET key=? || substr(key,length(?) + 1), revision=revision+1 '
        'WHERE namespace=? AND key>=? AND key<? AND (key=? OR key>=?)',
        (new_prefix, old_prefix, WORLDINFO_NOTES_KEY, old_prefix, old_prefix + '0', old_prefix, old_prefix + '/'),
    )
    if cursor.rowcount:
        conn.execute('UPDATE ui_records SET revision=revision+1 WHERE key=?', (WORLDINFO_NOTES_KEY,))
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')


def _export_at(conn, component):
    table = 'ui_records' if component == 'ui' else 'chat_local_state'
    result = {r[0]: json.loads(r[1]) for r in conn.execute(f'SELECT key,payload_json FROM {table}')}
    if component == 'ui':
        roots = {r[0] for r in conn.execute('SELECT namespace FROM ui_namespace_roots')}
        for root in roots:
            result[root] = {}
        for namespace, key, raw in conn.execute('SELECT namespace,key,payload_json FROM ui_namespace_records'):
            if namespace in roots:
                result[namespace][key] = json.loads(raw)
    return result


class NamespaceRepository(Repository):
    """全局空间按直接成员持久化：一本世界书、一插件或一配置项各自合并。"""
    def __init__(self, namespace, path=None):
        self.namespace, self.path = namespace, path
        self.component, self.table = 'namespace', 'ui_namespace_records'

    def get_many(self, keys=None, *, conn=None):
        if conn is None:
            initialize(self.path)
            try:
                with closing(connect(self.path)) as reader:
                    return self.get_many(keys, conn=reader)
            except (sqlite3.Error, OSError, ValueError) as exc:
                raise LocalStateError('权威命名空间读取失败') from exc
        return {key: (json.loads(raw), revision) for key, (raw, revision) in self._read_records(keys, conn=conn).items()}

    def _read_records(self, keys=None, *, conn):
        sql = 'SELECT key,payload_json,revision FROM ui_namespace_records WHERE namespace=?'
        params = [self.namespace]
        if keys is not None:
            keys = list(dict.fromkeys(keys))
            result = {}
            for start in range(0, len(keys), 400):
                batch = keys[start:start + 400]
                rows = conn.execute(sql + ' AND key IN (' + ','.join('?' for _ in batch) + ')',
                                    [*params, *batch])
                result.update({r[0]: (r[1], r[2]) for r in rows})
            return result
        return {r[0]: (r[1], r[2]) for r in conn.execute(sql, params)}

    def _card_ui_value(self, conn):
        # 物理 namespace 不能改变 _hero.png 或 _bundle 等实际卡片 UI 的语义。
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_metadata'").fetchone():
            return None
        cards = conn.execute('SELECT id FROM card_metadata WHERE id=? UNION ALL '
                             'SELECT id FROM card_metadata WHERE id>=? AND id<?',
                             (self.namespace, self.namespace + '/', self.namespace + '/\uffff'))
        if not any(row[0] == self.namespace or row[0].rsplit('/', 1)[0] == self.namespace for row in cards):
            return None
        return {key: value for key, (value, _) in self.get_many(conn=conn).items()}

    def _project_card_ui(self, conn, previous, *, defer_projection=False):
        if previous is not None:
            value = {key: item for key, (item, _) in self.get_many(conn=conn).items()}
            _bindings(conn, self.namespace, value)
            self._project_ui(conn, self.namespace, previous, value, defer_projection=defer_projection)

    def _put(self, conn, key, value, *, defer_projection=False):
        if not conn.execute('SELECT 1 FROM ui_namespace_roots WHERE namespace=?', (self.namespace,)).fetchone():
            raise StateConflict('命名空间已被删除，请重新读取')
        previous = self._card_ui_value(conn)
        conn.execute('INSERT INTO ui_namespace_records(namespace,key,payload_json) VALUES (?,?,?) '
                     'ON CONFLICT(namespace,key) DO UPDATE SET payload_json=excluded.payload_json, revision=revision+1',
                     (self.namespace, key, encode(value)))
        conn.execute('UPDATE ui_records SET revision=revision+1 WHERE key=?', (self.namespace,))
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')
        self._project_card_ui(conn, previous, defer_projection=defer_projection)

    def delete(self, key, *, conn=None):
        if conn is None:
            with self.transaction() as writer:
                return self.delete(key, conn=writer)
        previous = self._card_ui_value(conn)
        conn.execute('DELETE FROM ui_namespace_records WHERE namespace=? AND key=?', (self.namespace, key))
        conn.execute('UPDATE ui_records SET revision=revision+1 WHERE key=?', (self.namespace,))
        conn.execute('UPDATE local_state_clock SET revision=revision+1 WHERE id=1')
        self._project_card_ui(conn, previous)

    def has_unobserved(self, observed):
        initialize(self.path)
        with closing(connect(self.path)) as conn:
            return any(row[0] not in observed for row in conn.execute(
                'SELECT key FROM ui_namespace_records WHERE namespace=?', (self.namespace,)))


class StateSnapshot(dict):
    """兼容旧 dict 协议；只读取实际访问的记录，枚举显式物化。"""
    def __init__(self, repository, *, root_revision=None, records=None, record_keys=(), records_complete=True):
        super().__init__()
        self.repository = repository
        self.root_revision = root_revision
        self._records = records
        self._record_keys = set(record_keys)
        self._records_complete = records_complete
        self.baseline = {}
        self.complete = False

    def _read(self, keys=None):
        if self._records is None:
            return self.repository.get_many(keys)
        if not self._records_complete and (keys is None or any(key not in self._record_keys for key in keys)):
            # 连接不逃出生命周期；扩展定向快照只能读取同一根版本。
            try:
                with closing(connect(self.repository.path)) as conn:
                    conn.execute('BEGIN')
                    row = conn.execute('SELECT revision FROM ui_records WHERE key=?',
                                       (self.repository.namespace,)).fetchone()
                    if (row[0] if row else 0) != self.root_revision:
                        raise StateConflict('命名空间已被其他请求修改，请重新读取: ' + self.repository.namespace)
                    records = self.repository._read_records(keys, conn=conn)
            except (sqlite3.Error, OSError) as exc:
                raise LocalStateError('权威命名空间读取失败') from exc
            self._records = {**self._records, **records}
            self._record_keys.update(records if keys is None else keys)
            self._records_complete = keys is None
        keys = self._records if keys is None else keys
        try:
            return {key: (json.loads(self._records[key][0]), self._records[key][1])
                    for key in keys if key in self._records}
        except ValueError as exc:
            raise LocalStateError('权威命名空间读取失败') from exc

    def _load(self, key):
        if key not in self.baseline:
            rows = {} if self.complete else self._read([key])
            value = rows.get(key, (_MISSING, 0))[0]
            self.baseline[key] = deepcopy(value) if value is not _MISSING else _MISSING
            if value is not _MISSING:
                dict.__setitem__(self, key, value)

    def prefetch(self, keys):
        keys = list(keys)
        for key, (value, _) in self._read([key for key in keys if key not in self.baseline]).items():
            if key not in self.baseline:
                self.baseline[key] = deepcopy(value)
                dict.__setitem__(self, key, value)
        # 批量确认缺失键，后续 get 不再逐条连接数据库。
        for key in keys:
            self.baseline.setdefault(key, _MISSING)
        return self

    def confirm_saved(self):
        pending = getattr(self, '_pending_namespace', None)
        if pending is not None:
            self.root_revision, self._records, self._record_keys = pending
            for key in list(self.baseline):
                if self._records is not None:
                    if key in self._records:
                        dict.__setitem__(self, key, json.loads(self._records[key][0]))
                    else:
                        dict.pop(self, key, None)
        if hasattr(self, '_pending_namespace'):
            del self._pending_namespace
        for key in list(self.baseline):
            value = dict.get(self, key, _MISSING)
            if isinstance(value, StateSnapshot):
                value.confirm_saved()
            self.baseline[key] = deepcopy(value) if value is not _MISSING else _MISSING

    def namespace_members(self, key, members):
        """兼容门面单成员路径，根与目标成员一起观察并记录缺失基线。"""
        members = list(members)
        if key not in self.baseline and not self.complete:
            value = self.repository.get_namespace_members(key, members)
            self.baseline[key] = deepcopy(value) if value is not _MISSING else _MISSING
            if value is not _MISSING:
                dict.__setitem__(self, key, value)
        value = self.get(key)
        if isinstance(value, StateSnapshot):
            value.prefetch(members)
        return value

    def materialize(self):
        if not self.complete:
            for key, (value, _) in self._read().items():
                if key not in self.baseline:
                    self.baseline[key] = deepcopy(value)
                    dict.__setitem__(self, key, value)
            self.complete = True
        return self

    def __getitem__(self, key):
        self._load(key)
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self._load(key)
        return dict.get(self, key, default)

    def __contains__(self, key):
        self._load(key)
        return dict.__contains__(self, key)

    def __setitem__(self, key, value):
        self._load(key)
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        self._load(key)
        dict.__delitem__(self, key)

    def setdefault(self, key, default=None):
        self._load(key)
        return dict.setdefault(self, key, default)

    def pop(self, key, *default):
        self._load(key)
        return dict.pop(self, key, *default)

    def __iter__(self):
        self.materialize()
        return dict.__iter__(self)

    def __len__(self):
        self.materialize()
        return dict.__len__(self)

    def keys(self):
        self.materialize()
        return dict.keys(self)

    def items(self):
        self.materialize()
        return dict.items(self)

    def values(self):
        self.materialize()
        return dict.values(self)

    def clear(self):
        self.materialize()
        dict.clear(self)

    def update(self, other=(), **kwargs):
        for key, value in dict(other, **kwargs).items():
            self[key] = value

    def __deepcopy__(self, memo):
        result = StateSnapshot(self.repository, root_revision=self.root_revision, records=self._records,
                               record_keys=self._record_keys, records_complete=self._records_complete)
        memo[id(self)] = result
        for key in self.baseline:
            if dict.__contains__(self, key):
                dict.__setitem__(result, key, deepcopy(dict.__getitem__(self, key), memo))
        result.baseline = {key: (_MISSING if value is _MISSING else deepcopy(value, memo))
                           for key, value in self.baseline.items()}
        result.complete = self.complete
        return result

    def copy(self):
        return deepcopy(self)

    def changed(self):
        return any(before != dict.get(self, key, _MISSING) for key, before in self.baseline.items())

    def __eq__(self, other):
        self.materialize()
        if isinstance(other, StateSnapshot):
            other.materialize()
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return not self == other

    def __bool__(self):
        # truth testing never decodes the whole table
        if dict.__len__(self):
            return True
        if self.complete:
            return False
        if self._records is not None and self._records_complete:
            return any(key not in self.baseline for key in self._records)
        if self._records is not None:
            self.materialize()
            return bool(dict.__len__(self))
        return self.repository.has_unobserved(self.baseline)


def snapshot(component='ui'):
    initialize()
    return StateSnapshot(Repository(component))


def binding_keys(chat_ids=None):
    initialize()
    with closing(connect()) as conn:
        if chat_ids is None:
            rows = conn.execute('SELECT card_ui_key, chat_id FROM chat_card_bindings')
        else:
            ids = list(chat_ids)
            rows = conn.execute('SELECT card_ui_key, chat_id FROM chat_card_bindings WHERE chat_id IN (' +
                                ','.join('?' for _ in ids) + ')', ids)
        return [(row[0], row[1]) for row in rows]


def read_snapshot_at(db_path, component, legacy_path=None):
    """备份只读权威状态；旧库仅由显式导入/导出流程读取旧文件。"""
    activated = os.path.exists(db_path + '.local-state-authority')
    if os.path.isfile(db_path):
        with closing(sqlite3.connect('file:' + db_path.replace('\\', '/') + '?mode=ro', uri=True)) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='local_state_migrations'").fetchone()
            if exists:
                row = conn.execute('SELECT state FROM local_state_migrations WHERE id=1').fetchone()
                if row and row[0] == 'activated':
                    return _export_at(conn, component)
    if activated:
        raise LocalStateError('权威数据库缺失或状态损坏，禁止从旧 JSON 导出陈旧备份')
    if legacy_path:
        return _legacy(legacy_path)[0]
    return {}


def activate_snapshots_at(db_path, ui, chat):
    """经过归档校验及路径转换后的 staging 库专用，禁止用于普通保存。"""
    for payload in (ui, chat):
        if not isinstance(payload, dict):
            raise LocalStateError('导入状态必须是对象')
        encode(payload)
    with closing(connect(db_path)) as conn:
        ensure_schema(conn)
        conn.commit()
        with conn:
            conn.execute('DELETE FROM local_state_staging')
            for component, payload in (('ui', ui), ('chat', chat)):
                conn.executemany('INSERT INTO local_state_staging VALUES (?,?,?)',
                                 [(component, k, encode(normalize_record(component, v, k))) for k, v in payload.items()])
            conn.execute("INSERT OR REPLACE INTO local_state_migrations VALUES (1, ?, 'imported', 'explicit-restore')",
                         (SCHEMA_VERSION,))
            _activate(conn)
