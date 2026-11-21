import json
import logging
import os
import sqlite3
import stat
from functools import cache, lru_cache, partial, wraps
from contextlib import ExitStack, closing, contextmanager
from contextvars import ContextVar

from core.context import ctx
from core.config import BASE_DIR, CARDS_FOLDER, DEFAULT_DB_PATH, load_config
from core.data.index_runtime_store import get_active_generation, delete_full_search_rows
from core.data.sqlite_capabilities import supports_fts5
from core.data.ui_store import WORLDINFO_NOTES_KEY, build_worldinfo_note_key, get_import_time, load_ui_data
from core.services.path_operation import PATH_BUSY, PathOperationBusy, observe_path_changes, path_operation
from core.utils.format_validation import is_valid_world_info_data
from core.utils.filesystem import (
    cache_directory_case_checks, filesystem_path_bucket, filesystem_path_key,
    filesystem_paths_match, walk_directory_strict,
)
from core.utils.image import extract_card_info_strict as extract_card_info
from core.utils.search_text import split_cjk_for_index
from core.utils.source_revision import build_file_source_revision


logger = logging.getLogger(__name__)


# 单本世界书写入全文索引的条目正文上限。超出后只截断正文，标题/关键词仍全部收录，
# 避免个别超大世界书把 FTS 索引撑大几个数量级。
WORLDBOOK_FULLTEXT_MAX_CHARS = 200000

# 单条条目正文的收录上限。
WORLDBOOK_FULLTEXT_ENTRY_MAX_CHARS = 20000

# 重建过程中每隔多少条提交一次事务。
# 两个作用：① 让前端能持续看到进度；② 不把整个重建压进一个长写事务里，
# 否则后台重建期间其它写入（扫描器、增量索引作业）会长时间拿不到写锁。
BUILD_COMMIT_BATCH_SIZE = 200


def _normalize_category_path(value: str) -> str:
    path = str(value or '').replace('\\', '/').strip().strip('/')
    if not path:
        return ''
    return '/'.join(part.strip() for part in path.split('/') if part.strip())


def _iter_category_ancestors(category: str):
    current = _normalize_category_path(category)
    while current:
        yield current
        if '/' not in current:
            break
        current = current.rsplit('/', 1)[0]


def _worldinfo_summary(ui_data: dict, source_type: str, *, file_path: str = '', card_id: str = '', card_ui=None) -> str:
    if not isinstance(ui_data, dict):
        return ''
    if source_type == 'embedded':
        card_meta = (ui_data if card_ui is None else card_ui).get(card_id)
        if isinstance(card_meta, dict):
            summary = str(card_meta.get('summary') or '')
            if summary.strip():
                return summary
    notes = ui_data.get(WORLDINFO_NOTES_KEY)
    key = build_worldinfo_note_key(source_type, file_path=file_path, card_id=card_id)
    note = notes.get(key) if isinstance(notes, dict) else None
    return str(note.get('summary') or '') if isinstance(note, dict) else ''


@cache_directory_case_checks
def worldinfo_summaries_match(conn, generation):
    """在迁移事务内按批核对活动索引；只读取这批实体用到的权威记录。"""
    from core.data.local_state_repository import NamespaceRepository, Repository

    notes = NamespaceRepository(WORLDINFO_NOTES_KEY)
    cards = Repository()
    rows = conn.execute(
        "SELECT entity_type, entity_id, source_path, summary_preview FROM index_entities_v2 "
        "WHERE generation=? AND entity_type IN ('world_global', 'world_resource', 'world_embedded')",
        (generation,))
    while batch := rows.fetchmany(400):
        targets = []
        note_keys = []
        card_ids = []
        for entity_type, entity_id, path, stored in batch:
            source = entity_type.removeprefix('world_')
            card_id = ''
            if source == 'embedded':
                card_id = entity_id.removeprefix('world::embedded::')
                card_ids.append(card_id)
            note_keys.append(build_worldinfo_note_key(source, file_path=path, card_id=card_id))
            targets.append((source, path, card_id, stored))
        ui = {key: value for key, (value, _) in cards.get_many(card_ids, conn=conn).items()}
        ui[WORLDINFO_NOTES_KEY] = {key: value for key, (value, _) in notes.get_many(note_keys, conn=conn).items()}
        for source, path, card_id, stored in targets:
            if _worldinfo_summary(ui, source, file_path=path, card_id=card_id) != (stored or ''):
                return False
    return True


def _resolve_card_ui_meta(ui_data: dict, card_id: str) -> dict:
    if not isinstance(ui_data, dict):
        return {}

    card_meta = ui_data.get(card_id) or {}
    if isinstance(card_meta, dict) and card_meta:
        return card_meta

    parent_dir = str(card_id or '').replace('\\', '/').rsplit('/', 1)[0] if '/' in str(card_id or '') else ''
    bundle_meta = ui_data.get(parent_dir) or {}
    if isinstance(bundle_meta, dict):
        return bundle_meta

    return {}


def _iter_book_entries(book_data):
    """遍历世界书条目（兼容 entries 为对象或数组、以及裸数组格式）。"""
    if isinstance(book_data, list):
        candidates = book_data
    elif isinstance(book_data, dict):
        entries = book_data.get('entries')
        if isinstance(entries, dict):
            candidates = list(entries.values())
        elif isinstance(entries, list):
            candidates = entries
        else:
            return
    else:
        return

    for entry in candidates:
        if isinstance(entry, dict):
            yield entry


def collect_worldbook_fulltext(book_data) -> str:
    """汇总世界书的条目正文与关键词，供全文索引使用。

    只收录文本字段，并用 ``WORLDBOOK_FULLTEXT_*`` 上限截断，避免超大世界书
    让索引体积失控。调用方传入的是已经解析好的 JSON，因此没有额外磁盘开销。
    """
    if not book_data:
        return ''

    chunks = []
    total = 0
    for entry in _iter_book_entries(book_data):
        parts = []
        comment = entry.get('comment')
        if isinstance(comment, str) and comment.strip():
            parts.append(comment)
        content = entry.get('content')
        if isinstance(content, str) and content.strip():
            parts.append(content[:WORLDBOOK_FULLTEXT_ENTRY_MAX_CHARS])
        for key_field in ('key', 'keys', 'keysecondary', 'secondary_keys'):
            value = entry.get(key_field)
            if isinstance(value, list):
                parts.extend(item for item in value if isinstance(item, str) and item.strip())
            elif isinstance(value, str) and value.strip():
                parts.append(value)
        if not parts:
            continue

        chunk = ' '.join(parts)
        chunks.append(chunk)
        total += len(chunk)
        if total >= WORLDBOOK_FULLTEXT_MAX_CHARS:
            break

    return ' '.join(chunks)[:WORLDBOOK_FULLTEXT_MAX_CHARS]


def _report_progress(progress_cb, done: int, total: int):
    """把「已处理 / 总数」上报给调用方；进度是展示信息，绝不能影响构建本身。"""
    if not progress_cb:
        return
    try:
        progress_cb(int(done), int(total))
    except Exception:
        logger.debug('索引构建进度回调失败', exc_info=True)


def _commit_and_report(conn, progress_cb, done: int, total: int):
    """分批提交 + 上报进度。

    重建不能把所有写入压进一个长事务：后台重建期间扫描器与增量索引作业仍在
    写同一个库，长写事务会让它们拿不到写锁。每 ``BUILD_COMMIT_BATCH_SIZE``
    条提交一次，顺便把进度刷新给前端。
    """
    if done % BUILD_COMMIT_BATCH_SIZE != 0:
        return
    conn.commit()
    _report_progress(progress_cb, done, total)


def _insert_search_rows(conn, generation: int, entity_id: str, content: str, fulltext_extra: str = ''):
    """写入两张搜索表。

    - ``fast`` 表保存**原文**：查询侧用 ``LIKE`` 做子串匹配，中文子串本来就成立，
      无需分词，索引体积也最小。该表是**普通表**（不需要 FTS5）。
    - ``full`` 表保存**逐字切分后的 CJK**（``split_cjk_for_index``）：``unicode61``
      不切分汉字，存原文会让中文子串永远命中 0 条；切分后查询侧用短语
      ``"血 族"`` 匹配相邻 token，得到真正的子串语义。``fulltext_extra``
      额外携带世界书条目正文。

    无 FTS5 的平台（如 iOS）不会创建 ``full`` 表，此时跳过写入而不是报错，
    全文搜索在查询侧降级为 ``fast``。
    """
    conn.execute(
        'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
        (generation, entity_id, content),
    )
    if not supports_fts5():
        return
    fulltext = f'{content} {fulltext_extra}' if fulltext_extra else content
    cursor = conn.execute(
        'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)',
        (generation, entity_id, split_cjk_for_index(fulltext)),
    )
    conn.execute('INSERT INTO index_full_rowids VALUES (?, ?, ?)',
                 (generation, entity_id, cursor.lastrowid))


def _adjust_world_category(conn, generation, entity_type, category, amount):
    category = _normalize_category_path(category)
    if not category or not entity_type.startswith('world_'):
        return
    for scope_type in (entity_type, 'world_all'):
        for ancestor in _iter_category_ancestors(category):
            if amount < 0:
                conn.execute("UPDATE index_category_stats_v2 SET direct_count=MAX(0,direct_count+?), "
                             "subtree_count=MAX(0,subtree_count-1) WHERE generation=? AND scope='worldinfo' "
                             "AND entity_type=? AND category_path=?",
                             (-1 if ancestor == category else 0, generation, scope_type, ancestor))
                continue
            conn.execute("INSERT INTO index_category_stats_v2 "
                         "(generation,scope,entity_type,category_path,direct_count,subtree_count) "
                         "VALUES (?,'worldinfo',?,?,?,?) ON CONFLICT(generation,scope,entity_type,category_path) "
                         "DO UPDATE SET direct_count=MAX(0,direct_count+excluded.direct_count), "
                         "subtree_count=MAX(0,subtree_count+excluded.subtree_count)",
                         (generation, scope_type, ancestor, amount if ancestor == category else 0, amount))


def _insert_worldinfo_search(conn, generation: int, entity_id: str, *parts, fulltext_extra=''):
    row = conn.execute('SELECT entity_type,display_category FROM index_entities_v2 WHERE generation=? AND entity_id=?',
                       (generation, entity_id)).fetchone()
    if row:
        _adjust_world_category(conn, generation, row[0], row[1], 1)
    content = ' '.join(str(part or '').strip() for part in parts if str(part or '').strip())
    _insert_search_rows(conn, generation, entity_id, content, fulltext_extra)


def _delete_card_entity_rows(conn, generation: int, entity_id: str):
    conn.execute(
        'DELETE FROM index_entities_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    conn.execute(
        'DELETE FROM index_entity_tags_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    conn.execute(
        'DELETE FROM index_search_fast_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    delete_full_search_rows(conn, generation, entity_id)


def _resolve_runtime_dir(raw_path: str, default: str) -> str:
    value = str(raw_path or default or '').strip()
    if not value:
        return ''
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(BASE_DIR, value))


def _resolve_worldinfo_runtime_dirs(cfg: dict | None = None) -> tuple[str, str]:
    cfg = cfg or load_config()
    return (
        _resolve_runtime_dir(cfg.get('world_info_dir'), 'data/library/lorebooks'),
        _resolve_runtime_dir(cfg.get('resources_dir'), 'data/assets/card_assets'),
    )


def classify_worldinfo_path(source_path: str) -> dict:
    cfg = load_config()
    raw_path = str(source_path or '').strip()
    normalized_path = os.path.normpath(raw_path)
    result = {
        'kind': 'invalid',
        'source_path': normalized_path.replace('\\', '/'),
    }
    if not normalized_path or not normalized_path.lower().endswith('.json'):
        return result

    global_dir, resource_dir = _resolve_worldinfo_runtime_dirs(cfg)

    if global_dir:
        try:
            if filesystem_paths_match(os.path.commonpath([normalized_path, global_dir]), global_dir):
                result['kind'] = 'global'
                return result
        except ValueError:
            pass

    if resource_dir:
        try:
            common = os.path.commonpath([normalized_path, resource_dir])
        except ValueError:
            common = ''
        if common and filesystem_paths_match(common, resource_dir):
            rel_path = normalized_path.replace('\\', '/').lower()
            if '/lorebooks/' in rel_path:
                result['kind'] = 'resource'

    return result


def _resource_worldinfo_folder(source_path, cfg):
    _global_dir, resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    normalized_path = os.path.normpath(str(source_path or ''))
    if not resources_dir or not normalized_path:
        return ''

    try:
        rel_path = os.path.relpath(normalized_path, resources_dir).replace('\\', '/')
    except ValueError:
        return ''

    if rel_path.startswith('../') or rel_path == '..':
        return ''

    parts = [part for part in rel_path.split('/') if part]
    if len(parts) != 3:
        return ''
    if not filesystem_paths_match(os.path.dirname(normalized_path),
                                  os.path.join(resources_dir, parts[0], 'lorebooks')):
        return ''

    return parts[0]


def _bound_worldinfo_owners(conn, resource_folder):
    owners = set()
    for key, folder in conn.execute(
            'SELECT card_ui_key,resource_folder FROM card_resource_bindings WHERE folder_key=?', (resource_folder,)):
        for (card_id,) in conn.execute(
                'SELECT id FROM card_metadata WHERE id=? UNION ALL '
                'SELECT id FROM card_metadata WHERE id>=? AND id<?', (key, key + '/', key + '/\uffff')):
            if card_id == key or card_id.rsplit('/', 1)[0] == key:
                owners.add((folder, card_id))
    return sorted(owners)


def resolve_resource_worldinfo_owner_card_ids(source_path: str, *, conn=None) -> list[str]:
    batch = _worldinfo_batch.get()
    cfg = batch['cfg'] if batch else load_config()
    folder = _resource_worldinfo_folder(source_path, cfg)
    if not folder:
        return []
    _, resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    resource_folder = filesystem_path_bucket(folder)
    directory_cases = batch['directory_cases'] if batch else {}

    def matching_owners(bindings):
        return sorted({card_id for bound_folder, card_id in bindings if filesystem_paths_match(
            os.path.join(resources_dir, folder), os.path.join(resources_dir, bound_folder),
            directory_cases=directory_cases,
        )})

    if conn is not None and batch and batch['conn'] is conn and batch['authoritative_ui']:
        return matching_owners(_observe_worldinfo_read(conn, _bound_worldinfo_owners, resource_folder))
    ui_data = load_ui_data()
    if not isinstance(ui_data, dict):
        return []
    from core.data.local_state_repository import StateSnapshot, connect
    if isinstance(ui_data, StateSnapshot):
        with closing(connect(ui_data.repository.path)) as conn:
            return matching_owners(_bound_worldinfo_owners(conn, resource_folder))

    return matching_owners((str(meta.get('resource_folder') or '').strip(), str(card_id))
                           for card_id, meta in ui_data.items() if isinstance(meta, dict))


def _rebuild_worldinfo_category_stats_v2(conn, generation: int, global_dir: str, *, strict=False):
    conn.execute(
        'DELETE FROM index_category_stats_v2 WHERE generation = ? AND scope = ?',
        (generation, 'worldinfo'),
    )

    direct_counts = {}
    subtree_counts = {}

    rows = conn.execute(
        "SELECT entity_type, display_category FROM index_entities_v2 WHERE generation = ? AND entity_type IN ('world_global', 'world_resource', 'world_embedded')",
        (generation,),
    ).fetchall()
    for row in rows:
        entity_type = str(row['entity_type'] or '')
        category = _normalize_category_path(row['display_category'])
        if not category:
            continue

        direct_counts[(entity_type, category)] = direct_counts.get((entity_type, category), 0) + 1
        direct_counts[('world_all', category)] = direct_counts.get(('world_all', category), 0) + 1

        for path in _iter_category_ancestors(category):
            subtree_counts[(entity_type, path)] = subtree_counts.get((entity_type, path), 0) + 1
            subtree_counts[('world_all', path)] = subtree_counts.get(('world_all', path), 0) + 1

    physical_paths = set()
    if global_dir and (strict or os.path.isdir(global_dir)):
        walker = walk_directory_strict if strict else os.walk
        for root, _dirs, _files in walker(global_dir):
            rel_root = os.path.relpath(root, global_dir).replace('\\', '/')
            current_category = '' if rel_root == '.' else _normalize_category_path(rel_root)
            if not current_category:
                continue
            for path in _iter_category_ancestors(current_category):
                physical_paths.add(path)

    stat_keys = set(direct_counts) | set(subtree_counts)
    stat_keys.update(('world_global', path) for path in physical_paths)
    stat_keys.update(('world_all', path) for path in physical_paths)

    for entity_type, category in sorted(stat_keys):
        conn.execute(
            'INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)',
            (
                generation,
                'worldinfo',
                entity_type,
                category,
                int(direct_counts.get((entity_type, category), 0)),
                int(subtree_counts.get((entity_type, category), 0)),
            ),
        )


def _delete_worldinfo_entity_rows(conn, generation: int, entity_id: str):
    row = conn.execute('SELECT entity_type,display_category FROM index_entities_v2 WHERE generation=? AND entity_id=?',
                       (generation, entity_id)).fetchone()
    if row:
        _adjust_world_category(conn, generation, row[0], row[1], -1)
    conn.execute(
        'DELETE FROM index_entities_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    conn.execute(
        'DELETE FROM index_entity_tags_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    conn.execute(
        'DELETE FROM index_search_fast_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )
    delete_full_search_rows(conn, generation, entity_id)


def _delete_worldinfo_owner_rows(conn, generation: int, card_id: str):
    owner_entity_id = f'card::{card_id}'
    _delete_worldinfo_entity_rows(conn, generation, f'world::embedded::{card_id}')

    existing_rows = conn.execute(
        'SELECT entity_id FROM index_entities_v2 WHERE generation = ? AND entity_type = ? AND owner_entity_id = ?',
        (generation, 'world_resource', owner_entity_id),
    ).fetchall()
    for existing_row in existing_rows:
        _delete_worldinfo_entity_rows(conn, generation, str(existing_row['entity_id'] or ''))


_worldinfo_batch = ContextVar('worldinfo_batch', default=None)
_worldinfo_path_leases = ContextVar('worldinfo_path_leases', default=None)


@contextmanager
def worldinfo_path_leases(leases):
    token = _worldinfo_path_leases.set(leases)
    try:
        yield
    finally:
        _worldinfo_path_leases.reset(token)


class WorldinfoGenerationMissing(RuntimeError):
    pass


class WorldinfoCategoryScanError(OSError):
    """The required directory traversal failed for the entire batch."""


def _observe_worldinfo_read(conn, read, *args):
    batch = _worldinfo_batch.get()
    if batch is None or batch['conn'] is not conn:
        return read(conn, *args)
    key = (read, args)
    reads = batch['reads']
    if key not in reads:
        reads[key] = read(conn, *args)
    batch['required_reads'].add(key)
    return reads[key]


def _worldinfo_ui_revision(conn, key):
    row = conn.execute('SELECT revision FROM ui_records WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


class _WorldinfoBatchUI(dict):
    def __init__(self, conn, snapshot):
        super().__init__()
        self.conn = conn
        self.snapshot = snapshot

    def get(self, key, default=None):
        # Record the revision before the lazy fetch. A change between the two
        # reads is still caught by the revision check under the write lock.
        _observe_worldinfo_read(self.conn, _worldinfo_ui_revision, key)
        return self.snapshot.get(key, default)


def _worldinfo_note_payload(conn, key):
    row = conn.execute('SELECT payload_json FROM ui_namespace_records WHERE namespace=? AND key=?',
                       (WORLDINFO_NOTES_KEY, key)).fetchone()
    return row[0] if row else None


def _increment_worldinfo_summary(conn, source_type, *, file_path='', card_id=''):
    batch = _worldinfo_batch.get()
    ui = batch['ui']
    if not batch['authoritative_ui']:
        return _worldinfo_summary(ui, source_type, file_path=file_path, card_id=card_id)
    if source_type == 'embedded':
        card = ui.get(card_id)
        summary = str(card.get('summary') or '') if isinstance(card, dict) else ''
        if summary.strip():
            return summary
    key = build_worldinfo_note_key(source_type, file_path=file_path, card_id=card_id,
                                  directory_cases=batch['directory_cases'])
    payload = _observe_worldinfo_read(conn, _worldinfo_note_payload, key)
    note = json.loads(payload) if payload is not None else None
    return str(note.get('summary') or '') if isinstance(note, dict) else ''


def _read_worldinfo_physical_categories(global_dir):
    physical = set()
    if global_dir:
        for root, _, _files in walk_directory_strict(global_dir):
            relative = os.path.relpath(root, global_dir).replace('\\', '/')
            if relative != '.':
                physical.update(_iter_category_ancestors(relative))
    return physical


@contextmanager
def worldinfo_increment_batch(conn, *, cfg=None, refresh_categories=False):
    """先准备整批文件与搜索文本，再在短事务中统一应用；目录只严格枚举一次。"""
    active = _worldinfo_batch.get()
    if active is not None and active['conn'] is conn:
        yield
        return
    from core.data.local_state_repository import StateConflict, StateSnapshot

    ui = load_ui_data()
    authoritative_ui = isinstance(ui, StateSnapshot)
    if authoritative_ui:
        ui = _WorldinfoBatchUI(conn, ui)
    outer_transaction = conn.in_transaction
    # 只读语句不固定跨文件扫描的 SQLite 快照，也不阻塞聊天进度写入。
    generation = get_active_generation(conn, 'worldinfo')
    if generation <= 0:
        raise WorldinfoGenerationMissing('worldinfo active generation missing')
    cfg = load_config() if cfg is None else cfg
    batch = {'conn': conn, 'plans': [], 'files': {}, 'ui': ui, 'cfg': cfg, 'reads': {}, 'required_reads': set(),
             'resource_paths': {}, 'resource_dirs': {}, 'resource_files': {},
             'resource_names': {}, 'resource_entities': {}, 'owner_refreshes': {},
             'authoritative_ui': authoritative_ui, 'directory_cases': {}}
    token = _worldinfo_batch.set(batch)
    try:
        yield
        if not batch['plans'] and not refresh_categories:
            return
        global_dir, _ = _resolve_worldinfo_runtime_dirs(cfg)
        with ExitStack() as local_leases, observe_path_changes(global_dir) as observed:
            leases = _worldinfo_path_leases.get() or local_leases
            physical, scan_error = None, None
            if not observed.changed:
                try:
                    physical = _read_worldinfo_physical_categories(global_dir)
                except OSError as exc:
                    scan_error = exc
            if not leases.enter_context(observed.pin()):
                physical = None
            elif scan_error is not None:
                raise WorldinfoCategoryScanError(str(scan_error)) from scan_error
            if physical is None and refresh_categories:
                raise PathOperationBusy(PATH_BUSY)
            if not outer_transaction:
                conn.execute('BEGIN IMMEDIATE')
            conn.execute('SAVEPOINT worldinfo_batch')
            try:
                if (get_active_generation(conn, 'worldinfo') != generation
                        or any(read(conn, *args) != batch['reads'][(read, args)]
                               for read, args in batch['required_reads'])):
                    raise StateConflict('准备世界书索引期间相关记录已变化，请重试')
                _apply_worldinfo_plans(conn, generation, batch['plans'], physical)
                if physical is None:
                    # 其它路径的实体仍可提交。目录快照只在完全稳定后单独补齐。
                    from core.services.index_job_worker import enqueue_index_job
                    enqueue_index_job('refresh_worldinfo_categories', source_path=global_dir, conn=conn)
            except BaseException:
                conn.execute('ROLLBACK TO worldinfo_batch')
                conn.execute('RELEASE worldinfo_batch')
                if not outer_transaction:
                    conn.rollback()
                raise
            conn.execute('RELEASE worldinfo_batch')
    finally:
        _worldinfo_batch.reset(token)


@contextmanager
def worldinfo_prepare_job():
    """仅保留成功准备的计划和校验项，整条共享资源任务一起撤回。"""
    batch = _worldinfo_batch.get()
    plans = batch['plans']
    plan_count = len(plans)
    # 这些缓存只追加。文件读取等不依赖计划的缓存可以继续复用。
    checkpoints = [(batch[key], len(batch[key])) for key in
                   ('resource_paths', 'resource_entities', 'owner_refreshes')]
    required = batch['required_reads']
    batch['required_reads'] = job_reads = set()
    try:
        yield
    except BaseException:
        del plans[plan_count:]
        for prepared, count in checkpoints:
            while len(prepared) > count:
                prepared.popitem()
        raise
    else:
        required.update(job_reads)
    finally:
        batch['required_reads'] = required


def _atomic_worldinfo_increment(operation):
    @wraps(operation)
    def wrapped(conn, *args, **kwargs):
        with worldinfo_increment_batch(conn):
            result = operation(conn, *args, **kwargs)
        if kwargs.get('commit', True):
            conn.commit()
        return result
    return wrapped


def _resource_lore_dir(resources_dir, resource_folder):
    if not stat.S_ISDIR(os.stat(resources_dir).st_mode):
        raise NotADirectoryError(resources_dir)
    lore_dir = os.path.join(resources_dir, resource_folder, 'lorebooks')
    try:
        mode = os.stat(lore_dir).st_mode
    except FileNotFoundError:
        return ''
    if not stat.S_ISDIR(mode):
        raise NotADirectoryError(lore_dir)
    return lore_dir


def _increment_resource_lore_dir(batch, resources_dir, resource_folder):
    key = os.path.normpath(resource_folder)
    directories = batch['resource_dirs']
    if key not in directories:
        directories[key] = _resource_lore_dir(resources_dir, resource_folder)
    return directories[key]


def _prepared_world_file(path, *, card=False):
    batch = _worldinfo_batch.get()
    key = (os.path.normpath(path), card)
    if key not in batch['files']:
        try:
            before = os.stat(path)
        except FileNotFoundError:
            result = (None, 0, '')
        else:
            if card:
                info = extract_card_info(path)
                data = info.get('data', info) if isinstance(info, dict) else None
                data = data.get('character_book') if isinstance(data, dict) else None
            else:
                try:
                    with open(path, encoding='utf-8') as handle:
                        data = json.load(handle)
                except (json.JSONDecodeError, UnicodeError):
                    data = None  # invalid format is a confirmed removal; access errors propagate
                if data is not None and not is_valid_world_info_data(data):
                    data = None
            after = os.stat(path)
            if (before.st_mtime_ns, before.st_ctime_ns, before.st_size, before.st_ino) != (
                    after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_ino):
                raise OSError('世界书在准备增量时变化，请重试: ' + path)
            result = (data, before.st_mtime, f'{before.st_mtime_ns}:{before.st_size}')
        batch['files'][key] = result
    return batch['files'][key]


def _world_entity(entity_id, entity_type, path, owner, name, category, mode, summary,
                  mtime, revision, book, owner_name=''):
    # JSON 解析、文本提取和分词均在取得 SQLite 写锁之前完成。
    filename = os.path.basename(path)
    parts = (name, filename, category, summary, owner_name)
    fast = ' '.join(str(part or '').strip() for part in parts if str(part or '').strip())
    full = ' '.join(part for part in (fast, collect_worldbook_fulltext(book)) if part)
    return ((entity_id, entity_type, path, owner, name, filename, category,
             category if entity_type == 'world_global' else '', mode, 0, summary,
             mtime, 0, 0, name.lower(), mtime, '', revision),
            fast, split_cjk_for_index(full))


def _owner_file_confirmed_missing(card_id):
    """A missing metadata row alone is insufficient evidence to remove an owner."""
    path = os.path.abspath(os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)))
    root = os.path.abspath(CARDS_FOLDER)
    if os.path.commonpath([root, path]) != root:
        raise ValueError('角色卡路径越界')
    try:
        os.stat(path)
    except FileNotFoundError:
        # A removed parent folder is legitimate; enumerate the configured root
        # strictly so an inaccessible root/child cannot be mistaken for deletion.
        for directory, _, files in walk_directory_strict(root):
            if path in (os.path.abspath(os.path.join(directory, name)) for name in files):
                return False
        return True
    return False


def _worldinfo_card_metadata(conn, card_id):
    return conn.execute('SELECT has_character_book,character_book_name,char_name,category,last_modified,file_hash '
                        'FROM card_metadata WHERE id=?', (card_id,)).fetchone()


def _prepare_embedded(conn, card_id, source_path=''):
    row = _observe_worldinfo_read(conn, _worldinfo_card_metadata, card_id)
    if row is None:
        if _owner_file_confirmed_missing(card_id):
            return []
        raise RuntimeError(f'embedded owner card missing: {card_id}')
    if not int(row['has_character_book'] or 0):
        return []
    path = source_path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
    book, mtime, revision = _prepared_world_file(path, card=True)
    if not isinstance(book, dict):
        return []
    name = str(book.get('name') or row['character_book_name'] or f"{row['char_name']}'s WI").strip()
    summary = _increment_worldinfo_summary(conn, 'embedded', card_id=card_id)
    return [_world_entity(f'world::embedded::{card_id}', 'world_embedded', path,
                          'card::' + card_id, name, str(row['category'] or ''), 'inherited',
                          summary, mtime, revision, book, str(row['char_name'] or ''))]


def _indexed_global_rows(conn, path_key):
    return tuple(conn.execute(
        "SELECT entity_id,source_path FROM index_entities_v2 WHERE generation=("
        "SELECT active_generation FROM index_build_state WHERE scope='worldinfo') "
        "AND entity_type='world_global' AND path_key=? ORDER BY entity_id", (path_key,),
    ))


@_atomic_worldinfo_increment
def apply_worldinfo_path_increment(conn, source_path: str, *, commit=True) -> bool:
    batch = _worldinfo_batch.get()
    global_dir, _ = _resolve_worldinfo_runtime_dirs(batch['cfg'])
    path = os.path.normpath(source_path or '')
    if not path or not global_dir:
        raise RuntimeError('worldinfo global directory unavailable')
    try:
        relative = os.path.relpath(path, global_dir).replace('\\', '/')
    except ValueError as exc:
        raise RuntimeError('worldinfo path outside global directory') from exc
    if relative == '..' or relative.startswith('../'):
        raise RuntimeError('worldinfo path outside global directory')
    candidates = _observe_worldinfo_read(conn, _indexed_global_rows, filesystem_path_bucket(path))
    directory_cases = batch['directory_cases']
    old_ids = [entity_id for entity_id, previous in candidates
               if filesystem_paths_match(path, previous, directory_cases=directory_cases)]
    book, mtime, revision = _prepared_world_file(path)
    entities = []
    if book is not None:
        if os.name == 'nt':
            # Windows 事件可能携带旧拼写。只采用同一根下的大小写修正，保留符号链接的逻辑路径。
            disk_root = os.path.realpath(global_dir, strict=True)
            disk_path = os.path.realpath(path, strict=True)
            if filesystem_paths_match(disk_path, os.path.join(disk_root, relative), directory_cases=directory_cases):
                relative = os.path.relpath(disk_path, disk_root).replace('\\', '/')
                path = os.path.join(global_dir, relative.replace('/', os.sep))
        name = str(book.get('name') or os.path.basename(path)).strip()
        category = relative.rsplit('/', 1)[0] if '/' in relative else ''
        summary = _increment_worldinfo_summary(conn, 'global', file_path=path)
        entities.append(_world_entity('world::global::' + relative, 'world_global', path, '', name, category,
                                       'physical', summary, mtime, revision, book))
    batch['plans'].append((old_ids, [], entities))
    return True


@_atomic_worldinfo_increment
def apply_worldinfo_embedded_increment(conn, card_id: str, source_path: str = '', *, commit=True) -> bool:
    entities = _prepare_embedded(conn, card_id, source_path)
    _worldinfo_batch.get()['plans'].append((['world::embedded::' + card_id], [], entities))
    return True


def _prepare_resource_entity(conn, card_id, row, path):
    batch = _worldinfo_batch.get()
    normalized_path = os.path.normpath(path)
    key = (card_id, normalized_path)
    prepared = batch['resource_entities']
    if key not in prepared:
        book, mtime, revision = _prepared_world_file(path)
        entity = None
        if book is not None:
            if os.name == 'nt':
                # 保留磁盘上的文件名，避免大小写别名生成不同的实体 ID。
                names = batch['resource_names']
                if normalized_path not in names:
                    names[normalized_path] = os.path.basename(os.path.realpath(path, strict=True))
                filename = names[normalized_path]
                if filesystem_paths_match(path, os.path.join(os.path.dirname(path), filename),
                                          directory_cases=batch['directory_cases']):
                    path = os.path.join(os.path.dirname(path), filename)
            filename = os.path.basename(path)
            overrides = ((batch['ui'].get('_resource_item_categories_v1') or {}).get('worldinfo') or {})
            path_key = filesystem_path_key(path, directory_cases=batch['directory_cases'])
            override = (overrides.get(path_key.replace('\\', '/')) or {}).get('category', '')
            name = str(book.get('name') or filename).strip()
            summary = _increment_worldinfo_summary(conn, 'resource', file_path=path)
            entity = _world_entity(f'world::resource::{card_id}::{filename}',
                'world_resource', path, 'card::' + card_id, name, override or str(row['category'] or ''),
                'override' if override else 'inherited', summary, mtime, revision, book, str(row['char_name'] or ''))
        prepared[key] = entity
    return prepared[key]


@_atomic_worldinfo_increment
def apply_worldinfo_resource_path_increment(conn, source_path, owner_ids, indexed_rows, *, commit=True):
    """更新一本资源书的所有当前投影，同时删除这条路径失效的旧投影。"""
    batch = _worldinfo_batch.get()
    key = os.path.normpath(source_path)
    if key in batch['resource_paths'] or not (owner_ids or indexed_rows):
        return True
    folder = _resource_worldinfo_folder(source_path, batch['cfg'])
    if not folder:
        return True

    # 根目录不可访问时不能把未读到的文件当成删除。
    _, resources_dir = _resolve_worldinfo_runtime_dirs(batch['cfg'])
    lore_dir = _increment_resource_lore_dir(batch, resources_dir, folder)
    path = os.path.join(lore_dir, os.path.basename(os.path.normpath(source_path))) if lore_dir else ''
    entities = []
    for card_id in owner_ids:
        row = _observe_worldinfo_read(conn, _worldinfo_card_metadata, card_id)
        resource = str(_resolve_card_ui_meta(batch['ui'], card_id).get('resource_folder') or '').strip()
        if (row is not None and path and resource and filesystem_paths_match(
                os.path.join(resources_dir, resource), os.path.join(resources_dir, folder),
                directory_cases=batch['directory_cases'])):
            entity = _prepare_resource_entity(conn, card_id, row, path)
            if entity is not None:
                entities.append(entity)

    current_ids = {entity[0][0] for entity in entities}
    deletes = [entity_id for entity_id in indexed_rows if entity_id not in current_ids]
    if deletes or entities:
        batch['plans'].append((deletes, [], entities))
    batch['resource_paths'][key] = True
    return True


@_atomic_worldinfo_increment
def apply_worldinfo_owner_increment(conn, card_id: str, source_path: str = '', *,
                                   remove_owner_ids=None, commit=True) -> bool:
    batch = _worldinfo_batch.get()
    owners = list(dict.fromkeys([str(value) for value in remove_owner_ids or [] if value] + [card_id]))
    card_source = source_path if classify_worldinfo_path(source_path).get('kind') != 'resource' else ''
    card_source = card_source or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
    refresh_key = (card_id, os.path.normpath(card_source))
    if refresh_key in batch['owner_refreshes']:
        batch['plans'].append(([], owners, []))
        return True
    row = _observe_worldinfo_read(conn, _worldinfo_card_metadata, card_id)
    entities = []
    if row is None:
        if not _owner_file_confirmed_missing(card_id):
            raise RuntimeError(f'worldinfo owner card missing: {card_id}')
    else:
        entities.extend(_prepare_embedded(conn, card_id, card_source))
        _, resources_dir = _resolve_worldinfo_runtime_dirs(batch['cfg'])
        resource = str(_resolve_card_ui_meta(batch['ui'], card_id).get('resource_folder') or '').strip()
        if resource:
            leases = _worldinfo_path_leases.get()
            if leases is not None and not leases.enter_context(path_operation(
                    os.path.join(resources_dir, resource, 'lorebooks'), exclusive=False)):
                raise PathOperationBusy(PATH_BUSY)
            lore_dir = _increment_resource_lore_dir(batch, resources_dir, resource)
            if lore_dir:
                files = batch['resource_files']
                if lore_dir not in files:
                    files[lore_dir] = [filename for filename in os.listdir(lore_dir) if filename.lower().endswith('.json')]
                for filename in files[lore_dir]:
                    entity = _prepare_resource_entity(conn, card_id, row, os.path.join(lore_dir, filename))
                    if entity is not None:
                        entities.append(entity)
    batch['owner_refreshes'][refresh_key] = True
    batch['plans'].append(([], owners, entities))
    return True


def _apply_worldinfo_plans(conn, generation, plans, physical):
    deletes, owners, final_entities = set(), set(), {}
    for entity_deletes, owner_deletes, entities in plans:
        deletes.update(entity_deletes)
        owners.update(owner_deletes)
        for entity in entities:
            final_entities[entity[0][0]] = entity
    for owner in owners:
        _delete_worldinfo_owner_rows(conn, generation, owner)
    for entity_id in deletes:
        _delete_worldinfo_entity_rows(conn, generation, entity_id)
    for values, fast, full in final_entities.values():
        # Overlapping shared-resource tasks replace the same entity exactly once in the batch.
        _delete_worldinfo_entity_rows(conn, generation, values[0])
        path_key = filesystem_path_bucket(values[2]) if values[1] in ('world_global', 'world_resource') else None
        conn.execute('''INSERT INTO index_entities_v2 (
            generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
            display_category, physical_category, category_mode, favorite, summary_preview,
            updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision, path_key
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (generation, *values, path_key))
        _adjust_world_category(conn, generation, values[1], values[6], 1)
        conn.execute('INSERT OR REPLACE INTO index_search_fast_v2 VALUES (?,?,?)',
                     (generation, values[0], fast))
        if supports_fts5():
            cursor = conn.execute('INSERT INTO index_search_full_v2 VALUES (?,?,?)',
                                  (generation, values[0], full))
            conn.execute('INSERT OR REPLACE INTO index_full_rowids VALUES (?,?,?)',
                         (generation, values[0], cursor.lastrowid))
    # 仅在路径稳定且严格枚举成功后更新物理目录。
    if physical is None:
        return
    zero_rows = conn.execute("SELECT entity_type,category_path FROM index_category_stats_v2 "
                             "WHERE generation=? AND scope='worldinfo' AND subtree_count=0",
                             (generation,)).fetchall()
    for entity_type, category in zero_rows:
        if entity_type not in ('world_global', 'world_all') or category not in physical:
            conn.execute("DELETE FROM index_category_stats_v2 WHERE generation=? AND scope='worldinfo' "
                         "AND entity_type=? AND category_path=? AND subtree_count=0",
                         (generation, entity_type, category))
    for entity_type in ('world_global', 'world_all'):
        for category in physical:
            conn.execute("INSERT OR IGNORE INTO index_category_stats_v2 VALUES (?,'worldinfo',?,?,0,0)",
                         (generation, entity_type, category))


def connect_index_db(db_path=None):
    conn = sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=FULL;')
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='index_full_rowids'").fetchone():
        from core.data.index_runtime_store import repair_full_search_mapping
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='index_search_full_v2'").fetchone():
            repair_full_search_mapping(conn)
            conn.commit()
    return conn


def refresh_worldinfo_category_stats(conn, cfg: dict | None = None) -> bool:
    with ExitStack() as leases, worldinfo_path_leases(leases):
        with worldinfo_increment_batch(conn, cfg=cfg, refresh_categories=True):
            pass
        conn.commit()
    return True


def _metadata_bundle_cover(conn, ui_key):
    cover = conn.execute('SELECT id FROM card_metadata WHERE id>=? AND id<? '
                         'ORDER BY last_modified DESC,id', (ui_key + '/', ui_key + '/\uffff'))
    return next((row[0] for row in cover if row[0].rpartition('/')[0] == ui_key), None)


def cached_bundle_cover_lookup(conn):
    """多卡核对共用一次目录封面查询；缓存只在本次构建或迁移内有效。"""
    return lru_cache(maxsize=200)(partial(_metadata_bundle_cover, conn))


def _card_ui_projection(ui_data, card_id, ui_key=None, *, lookup_cover=None):
    from core.data.ui_store import get_version_remark, VERSION_REMARKS_KEY
    from core.services.card_service import resolve_ui_key

    ui_key = ui_key or resolve_ui_key(card_id)
    parent = os.path.dirname(card_id).replace('\\', '/')
    parent_entry = ui_data.get(parent)
    if ui_key == card_id and isinstance(parent_entry, dict) and VERSION_REMARKS_KEY in parent_entry:
        ui_key = parent
    if ui_key != card_id:
        entry = ui_data.get(ui_key)
        if not isinstance(entry, dict):
            return ui_key, ''
        cover_id = (getattr(ctx.cache, 'bundle_map', {}) or {}).get(ui_key)
        if (not cover_id and lookup_cover and entry.get('summary')
                and card_id not in (entry.get(VERSION_REMARKS_KEY) or {})):
            # 冷 bundle 的旧格式根备注只属于主版本；不能凭缓存缺失丢失或串给其他版本。
            cover_id = lookup_cover(ui_key)
        summary = get_version_remark(ui_data, ui_key, card_id, cover_id).get('summary', '')
    else:
        entry = ui_data.get(card_id)
        summary = entry.get('summary', '') if isinstance(entry, dict) else ''
    return ui_key, str(summary)


def apply_card_increment(conn, card_id: str, source_path: str = '', *, remove_entity_ids: list[str] | None = None,
                         commit=True, ui_data=None, source_revision=None, ui_key=None) -> bool:
    # 外部读取在短写事务之前完成。
    ui_data = load_ui_data() if ui_data is None else ui_data
    ui_key, summary = _card_ui_projection(ui_data, card_id, ui_key, lookup_cover=partial(_metadata_bundle_cover, conn))
    source_revision = (build_file_source_revision(source_path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)))
                       if source_revision is None else source_revision)
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    generations = conn.execute("SELECT active_generation,building_generation FROM index_build_state "
                               "WHERE scope='cards'").fetchone()
    generation, building = generations or (0, 0)
    if generation <= 0:
        raise RuntimeError('cards active generation missing')

    remove_entity_ids = remove_entity_ids or []
    resolved_source_path = str(source_path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)))
    if building:
        # 构建器可能已经读过本批的旧数据。记录受影响的 ID，换代后再读取权威值；
        # 不重放文件操作，改名的旧 ID 也只按届时的 metadata 协调。
        changes = {old_id: (os.path.join(CARDS_FOLDER, old_id.replace('/', os.sep)), '{}')
                   for old_id in remove_entity_ids if old_id}
        changes[card_id] = (resolved_source_path, json.dumps({'ui_key': ui_key}, ensure_ascii=False))
        conn.executemany('INSERT OR REPLACE INTO index_card_build_changes '
                         '(generation,card_id,source_path,payload_json) VALUES (?,?,?,?)',
                         [(building, key, path, payload) for key, (path, payload) in changes.items()])
    for stale_card_id in remove_entity_ids:
        stale_value = str(stale_card_id or '').strip()
        if not stale_value:
            continue
        _delete_card_entity_rows(conn, generation, f'card::{stale_value}')

    row = conn.execute(
        'SELECT id, char_name, tags, category, last_modified, token_count, is_favorite FROM card_metadata WHERE id = ?',
        (card_id,),
    ).fetchone()
    entity_id = f'card::{card_id}'
    _delete_card_entity_rows(conn, generation, entity_id)

    if row is None:
        if commit:
            conn.commit()
        return True

    tags = json.loads(row['tags'] or '[]') if row['tags'] else []
    filename = str(card_id).split('/')[-1]
    last_modified = float(row['last_modified'] or 0)
    import_time = get_import_time(ui_data, ui_key, last_modified)
    conn.execute(
        '''
        INSERT OR REPLACE INTO index_entities_v2(
            generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
            display_category, physical_category, category_mode, favorite, summary_preview,
            updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            generation,
            entity_id,
            'card',
            resolved_source_path,
            '',
            row['char_name'] or '',
            filename,
            row['category'] or '',
            row['category'] or '',
            'physical',
            int(row['is_favorite'] or 0),
            summary,
            last_modified,
            import_time,
            int(row['token_count'] or 0),
            str(row['char_name'] or '').lower(),
            last_modified,
            '',
            source_revision,
        ),
    )

    for tag in tags:
        normalized_tag = str(tag).strip()
        if not normalized_tag:
            continue
        conn.execute(
            'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
            (generation, entity_id, normalized_tag),
        )

    content = ' '.join([
        str(row['char_name'] or ''),
        filename,
        str(row['category'] or ''),
        summary,
        ' '.join(str(tag) for tag in tags),
    ]).strip()
    _insert_search_rows(conn, generation, entity_id, content)
    if commit:
        conn.commit()
    return True


@contextmanager
def _generation_ui_reader():
    from core.data.local_state_repository import StateSnapshot, connect

    ui = load_ui_data()
    if not isinstance(ui, StateSnapshot):
        yield lambda keys: ui
        return
    with closing(connect(ui.repository.path)) as reader:
        def read(keys):
            # 根与成员从同一视图读取。构建文件和写入索引期间不持有状态读事务。
            with reader:
                reader.execute('BEGIN')
                records = ui.repository.get_many(keys, conn=reader)
            return {key: value for key, (value, _) in records.items()}
        yield read


def _card_rows_with_ui(rows, read_ui, resolve_key=None):
    for start in range(0, len(rows), BUILD_COMMIT_BATCH_SIZE):
        batch = rows[start:start + BUILD_COMMIT_BATCH_SIZE]
        keys = {''}
        for row in batch:
            card_id = row['id']
            keys.add(card_id)
            keys.add(os.path.dirname(card_id).replace('\\', '/'))
            if resolve_key:
                keys.add(resolve_key(card_id))
        card_ui = read_ui(keys)
        for row in batch:
            yield row, card_ui


def build_cards_generation(conn, generation: int, progress_cb=None):
    with _generation_ui_reader() as read_ui:
        return _build_cards_generation(conn, generation, read_ui, progress_cb)


def _build_cards_generation(conn, generation, read_ui, progress_cb):
    from core.services.card_service import resolve_ui_key

    rows = conn.execute(
        'SELECT id, char_name, tags, category, last_modified, token_count, is_favorite FROM card_metadata'
    ).fetchall()
    total = len(rows)
    lookup_cover = cached_bundle_cover_lookup(conn)
    _report_progress(progress_cb, 0, total)
    for index, (row, ui_data) in enumerate(_card_rows_with_ui(rows, read_ui, resolve_ui_key), start=1):
        entity_id = f"card::{row['id']}"
        tags = json.loads(row['tags'] or '[]') if row['tags'] else []
        ui_key, summary = _card_ui_projection(ui_data, row['id'], lookup_cover=lookup_cover)
        source_path = os.path.join(CARDS_FOLDER, row['id'].replace('/', os.sep))
        last_modified = float(row['last_modified'] or 0)
        import_time = get_import_time(ui_data, ui_key, last_modified)
        conn.execute(
            '''
            INSERT OR REPLACE INTO index_entities_v2(
                generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
                display_category, physical_category, category_mode, favorite, summary_preview,
                updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                generation,
                entity_id,
                'card',
                source_path,
                '',
                row['char_name'] or '',
                str(row['id']).split('/')[-1],
                row['category'] or '',
                row['category'] or '',
                'physical',
                int(row['is_favorite'] or 0),
                summary,
                last_modified,
                import_time,
                int(row['token_count'] or 0),
                str(row['char_name'] or '').lower(),
                last_modified,
                '',
                build_file_source_revision(source_path),
            ),
        )

        for tag in tags:
            normalized_tag = str(tag).strip()
            if not normalized_tag:
                continue
            conn.execute(
                'INSERT OR REPLACE INTO index_entity_tags_v2(generation, entity_id, tag) VALUES (?, ?, ?)',
                (generation, entity_id, normalized_tag),
            )

        content = ' '.join([
            str(row['char_name'] or ''),
            str(row['id']).split('/')[-1],
            str(row['category'] or ''),
            summary,
            ' '.join(str(tag) for tag in tags),
        ]).strip()
        _insert_search_rows(conn, generation, entity_id, content)

        if index % BUILD_COMMIT_BATCH_SIZE == 0:
            conn.commit()
            _report_progress(progress_cb, index, total)

    conn.commit()
    _report_progress(progress_cb, total, total)
    return len(rows)


@cache_directory_case_checks
def build_worldinfo_generation(conn, generation: int, inspected_books=None, progress_cb=None):
    with _generation_ui_reader() as read_ui:
        return _build_worldinfo_generation(conn, generation, read_ui, inspected_books, progress_cb)


def _build_worldinfo_generation(conn, generation, read_ui, inspected_books, progress_cb):
    cfg = load_config()
    @cache
    def world_notes():
        return read_ui([WORLDINFO_NOTES_KEY])

    global_dir, resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    rows = conn.execute(
        '''
        SELECT id, char_name, category, character_book_name, last_modified, has_character_book
        FROM card_metadata
        '''
    ).fetchall()
    inspected_books = inspected_books or {}

    items_written = 0
    done = 0

    # 进度总数 = 全局世界书文件数 + 角色卡数（每张卡最多再带一批资源世界书，
    # 那部分数量无法预知，因此按「卡片已处理」计数，超出的进度在展示侧截断）。
    global_files = []
    if global_dir:
        for root, _dirs, files in walk_directory_strict(global_dir):
            for filename in files:
                if filename.lower().endswith('.json'):
                    global_files.append((root, filename))
    total = len(global_files) + len(rows)
    _report_progress(progress_cb, 0, total)

    for root, filename in global_files:
        full_path = os.path.join(root, filename)
        try:
            with open(full_path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeError):
            logger.warning('Skipping invalid worldinfo file during v2 rebuild: %s', full_path, exc_info=True)
            done += 1
            continue
        if not is_valid_world_info_data(data):
            done += 1
            continue

        rel_path = os.path.relpath(full_path, global_dir).replace('\\', '/')
        display_category = rel_path.rsplit('/', 1)[0] if '/' in rel_path else ''
        name = (data.get('name') or '').strip() or filename
        entity_id = f'world::global::{rel_path}'
        summary = _worldinfo_summary(world_notes(), 'global', file_path=full_path)
        mtime = float(os.path.getmtime(full_path))
        conn.execute(
            '''
            INSERT OR REPLACE INTO index_entities_v2(
                generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
                display_category, physical_category, category_mode, favorite, summary_preview,
                updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision, path_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                generation,
                entity_id,
                'world_global',
                full_path,
                '',
                name,
                filename,
                display_category,
                display_category,
                'physical',
                0,
                summary,
                mtime,
                0,
                0,
                name.lower(),
                mtime,
                '',
                build_file_source_revision(full_path),
                filesystem_path_bucket(full_path),
            ),
        )
        _insert_worldinfo_search(
            conn,
            generation,
            entity_id,
            name,
            filename,
            display_category,
            summary,
            fulltext_extra=collect_worldbook_fulltext(data),
        )
        items_written += 1
        done += 1
        if done % BUILD_COMMIT_BATCH_SIZE == 0:
            conn.commit()
            _report_progress(progress_cb, done, total)

    categories = read_ui(['_resource_item_categories_v1']).get('_resource_item_categories_v1') or {}
    resource_item_categories = categories.get('worldinfo') or {}
    directory_cases = {}
    for row, card_ui in _card_rows_with_ui(rows, read_ui):
        card_id = str(row['id'])
        card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        owner_entity_id = f'card::{card_id}'
        resource_folder = str((_resolve_card_ui_meta(card_ui, card_id).get('resource_folder') or '')).strip()
        if resource_folder:
            lore_dir = _resource_lore_dir(resources_dir, resource_folder)
            if lore_dir:
                for filename in os.listdir(lore_dir):
                    if not filename.lower().endswith('.json'):
                        continue
                    full_path = os.path.join(lore_dir, filename)
                    try:
                        with open(full_path, 'r', encoding='utf-8') as handle:
                            data = json.load(handle)
                    except (json.JSONDecodeError, UnicodeError):
                        logger.warning('Skipping invalid resource worldinfo file during v2 rebuild: %s', full_path, exc_info=True)
                        continue
                    if not is_valid_world_info_data(data):
                        continue

                    path_key = filesystem_path_bucket(full_path)
                    category_key = filesystem_path_key(full_path, directory_cases=directory_cases).replace('\\', '/')
                    override = (resource_item_categories.get(category_key) or {}).get('category', '')
                    display_category = override or str(row['category'] or '')
                    mode = 'override' if override else 'inherited'
                    name = (data.get('name') or '').strip() or filename
                    summary = _worldinfo_summary(world_notes(), 'resource', file_path=full_path)
                    mtime = float(os.path.getmtime(full_path))
                    entity_id = f'world::resource::{card_id}::{filename}'
                    conn.execute(
                        '''
                        INSERT OR REPLACE INTO index_entities_v2(
                            generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
                            display_category, physical_category, category_mode, favorite, summary_preview,
                            updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision, path_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            generation,
                            entity_id,
                            'world_resource',
                            full_path,
                            owner_entity_id,
                            name,
                            filename,
                            display_category,
                            '',
                            mode,
                            0,
                            summary,
                            mtime,
                            0,
                            0,
                            name.lower(),
                            mtime,
                            '',
                            build_file_source_revision(full_path),
                            path_key,
                        ),
                    )
                    _insert_worldinfo_search(
                        conn,
                        generation,
                        entity_id,
                        name,
                        filename,
                        display_category,
                        summary,
                        str(row['char_name'] or ''),
                        fulltext_extra=collect_worldbook_fulltext(data),
                    )
                    items_written += 1

        book = inspected_books.get(card_id)
        if book is None:
            info = extract_card_info(card_path)
            if not info:
                done += 1
                _commit_and_report(conn, progress_cb, done, total)
                continue

            data = info.get('data', {}) if isinstance(info, dict) and 'data' in info else info
            book = data.get('character_book') if isinstance(data, dict) else None
        if not isinstance(book, dict):
            done += 1
            _commit_and_report(conn, progress_cb, done, total)
            continue

        name = str(book.get('name') or row['character_book_name'] or f"{row['char_name']}'s WI").strip()
        entity_id = f'world::embedded::{card_id}'
        category = str(row['category'] or '')
        summary = _worldinfo_summary(world_notes(), 'embedded', card_id=card_id, card_ui=card_ui)

        conn.execute(
            '''
            INSERT OR REPLACE INTO index_entities_v2(
                generation, entity_id, entity_type, source_path, owner_entity_id, name, filename,
                display_category, physical_category, category_mode, favorite, summary_preview,
                updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                generation,
                entity_id,
                'world_embedded',
                card_path,
                owner_entity_id,
                name,
                os.path.basename(card_path),
                category,
                '',
                'inherited',
                0,
                summary,
                float(row['last_modified'] or 0),
                0,
                0,
                name.lower(),
                float(row['last_modified'] or 0),
                '',
                build_file_source_revision(card_path),
            ),
        )
        _insert_worldinfo_search(
            conn,
            generation,
            entity_id,
            name,
            os.path.basename(card_path),
            category,
            summary,
            str(row['char_name'] or ''),
            fulltext_extra=collect_worldbook_fulltext(book),
        )
        items_written += 1
        done += 1
        _commit_and_report(conn, progress_cb, done, total)

    _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir, strict=True)
    _report_progress(progress_cb, max(done, total), max(total, done))
    conn.commit()
    return items_written
