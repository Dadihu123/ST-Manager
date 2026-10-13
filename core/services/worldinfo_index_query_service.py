import os
import sqlite3

from core.config import DEFAULT_DB_PATH
from core.data.index_runtime_store import get_active_generation
from core.utils.search_text import build_fts_match_query, escape_like


# 世界书实体类型。用 IN 而不是 LIKE 'world_%'：LIKE 前缀通配会让
# idx_index_entities_v2_gen_type_sort 失效，退化成扫描全部实体（含角色卡）。
WORLD_ENTITY_TYPES = ('world_global', 'world_resource', 'world_embedded')
WORLD_ENTITY_TYPE_FILTER = 'e.entity_type IN ' + repr(WORLD_ENTITY_TYPES)

# 搜索字段分类，与前端 search_field 参数一一对应。
SEARCH_FIELD_SMART = 'smart'
SEARCH_FIELD_NAME = 'name'
SEARCH_FIELD_FILENAME = 'filename'
SEARCH_FIELD_OWNER = 'owner'
SEARCH_FIELDS = (
    SEARCH_FIELD_SMART,
    SEARCH_FIELD_NAME,
    SEARCH_FIELD_FILENAME,
    SEARCH_FIELD_OWNER,
)

# 精确分类直接命中索引列，不需要 FTS 子查询，也不受分词器限制。
_FIELD_LIKE_COLUMNS = {
    SEARCH_FIELD_NAME: 'e.name',
    SEARCH_FIELD_FILENAME: 'e.filename',
    SEARCH_FIELD_OWNER: 'e.owner_entity_id',
}


def _connect(db_path=None):
    conn = sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _normalized_search_field(value) -> str:
    field = str(value or '').strip().lower()
    return field if field in SEARCH_FIELDS else SEARCH_FIELD_SMART


def _is_malformed_match_error(exc):
    message = str(exc or '').lower()
    malformed_markers = (
        'fts5: syntax error',
        'unterminated string',
        'malformed match expression',
    )
    return any(marker in message for marker in malformed_markers)


def _normalized_category(value: str) -> str:
    path = str(value or '').replace('\\', '/').strip().strip('/')
    if not path:
        return ''
    return '/'.join(part.strip() for part in path.split('/') if part.strip())


def _world_entity_type(requested_type: str) -> str:
    type_map = {
        'global': 'world_global',
        'resource': 'world_resource',
        'embedded': 'world_embedded',
    }
    return type_map.get(str(requested_type or '').strip().lower(), 'world_all')


def _build_field_clause(field: str, search: str):
    """精确分类的 WHERE 片段；智能搜索返回 ``(None, [])`` 交给调用方处理。"""
    column = _FIELD_LIKE_COLUMNS.get(field)
    if not column:
        return None, []
    return f'LOWER({column}) LIKE ?', [f'%{search.lower()}%']


def _build_folder_capabilities(all_folders, folder_semantics=None):
    semantics = folder_semantics or {}
    folder_capabilities = {
        '': {
            'has_physical_folder': True,
            'has_virtual_items': bool(semantics.get('', {}).get('has_virtual_items', False)),
            'can_create_child_folder': True,
            'can_rename_physical_folder': False,
            'can_delete_physical_folder': False,
        }
    }
    for path in all_folders:
        meta = semantics.get(path) or {}
        has_physical_folder = bool(meta.get('has_physical_folder', False))
        has_virtual_items = bool(meta.get('has_virtual_items', False))
        folder_capabilities[path] = {
            'has_physical_folder': has_physical_folder,
            'has_virtual_items': has_virtual_items,
            'can_create_child_folder': has_physical_folder,
            'can_rename_physical_folder': has_physical_folder,
            'can_delete_physical_folder': False,
        }
    return folder_capabilities


def _iter_category_ancestors(category: str):
    current = _normalized_category(category)
    while current:
        yield current
        if '/' not in current:
            break
        current = current.rsplit('/', 1)[0]


def _fallback_folder_metadata(conn, requested_entity_type: str, generation: int):
    where = ['generation = ?', 'entity_type IN ' + repr(WORLD_ENTITY_TYPES)]
    params = [generation]
    if requested_entity_type != 'world_all':
        where.append('entity_type = ?')
        params.append(requested_entity_type)

    rows = conn.execute(
        f"SELECT entity_type, display_category, source_path FROM index_entities_v2 WHERE {' AND '.join(where)}",
        params,
    ).fetchall()

    category_counts = {}
    all_folders = set()
    global_roots = set()
    empty_physical_folders = set()
    folder_semantics = {'': {'has_physical_folder': True, 'has_virtual_items': False}}

    def _ensure_semantics(path):
        if path not in folder_semantics:
            folder_semantics[path] = {'has_physical_folder': False, 'has_virtual_items': False}
        return folder_semantics[path]

    for row in rows:
        category = _normalized_category(row['display_category'])
        entity_type = str(row['entity_type'] or '')
        if category:
            for path in _iter_category_ancestors(category):
                category_counts[path] = category_counts.get(path, 0) + 1
                meta = _ensure_semantics(path)
                if entity_type == 'world_global':
                    meta['has_physical_folder'] = True
                else:
                    meta['has_virtual_items'] = True
            for path in _iter_category_ancestors(category):
                all_folders.add(path)

        if entity_type == 'world_global':
            source_path = str(row['source_path'] or '').replace('\\', '/')
            filename = source_path.split('/')[-1] if source_path else ''
            if source_path and filename and source_path.lower().endswith('/' + filename.lower()):
                if category:
                    expected_suffix = '/' + category.lower() + '/' + filename.lower()
                    if source_path.lower().endswith(expected_suffix):
                        root_path = source_path[:-len(expected_suffix)]
                    else:
                        root_path = ''
                else:
                    root_path = source_path[:-(len(filename) + 1)]

                if root_path:
                    global_roots.add(root_path.rstrip('/'))

    for root in sorted(global_roots):
        if not root:
            continue
        try:
            for current_root, dirs, _files in os.walk(root):
                rel_root = os.path.relpath(current_root, root).replace('\\', '/')
                current_category = '' if rel_root == '.' else _normalized_category(rel_root)
                if not current_category:
                    continue
                for path in _iter_category_ancestors(current_category):
                    all_folders.add(path)
                    _ensure_semantics(path)['has_physical_folder'] = True
                if not dirs and not _files:
                    empty_physical_folders.add(current_category)
        except Exception:
            continue

    return sorted(all_folders), category_counts, empty_physical_folders, folder_semantics


def _category_stats_metadata(conn, requested_entity_type: str, generation: int):
    stat_rows = conn.execute(
        'SELECT category_path, direct_count, subtree_count FROM index_category_stats_v2 WHERE generation = ? AND scope = ? AND entity_type = ? ORDER BY category_path ASC',
        (generation, 'worldinfo', requested_entity_type),
    ).fetchall()
    if not stat_rows:
        return None

    all_folders = [str(row['category_path'] or '') for row in stat_rows if str(row['category_path'] or '')]
    category_counts = {
        str(row['category_path'] or ''): int(row['subtree_count'] or 0)
        for row in stat_rows
        if str(row['category_path'] or '')
    }
    folder_semantics = {'': {'has_physical_folder': True, 'has_virtual_items': False}}
    empty_physical_folders = set()

    def _stat_count(entity_type: str, path: str) -> int:
        row = conn.execute(
            'SELECT subtree_count FROM index_category_stats_v2 WHERE generation = ? AND scope = ? AND entity_type = ? AND category_path = ?',
            (generation, 'worldinfo', entity_type, path),
        ).fetchone()
        return int((row or [0])[0] or 0)

    def _has_stat_row(entity_type: str, path: str) -> bool:
        row = conn.execute(
            'SELECT 1 FROM index_category_stats_v2 WHERE generation = ? AND scope = ? AND entity_type = ? AND category_path = ? LIMIT 1',
            (generation, 'worldinfo', entity_type, path),
        ).fetchone()
        return row is not None

    def _has_physical_child_folder(path: str) -> bool:
        prefix = f'{path}/%'
        row = conn.execute(
            'SELECT 1 FROM index_category_stats_v2 WHERE generation = ? AND scope = ? AND entity_type = ? AND category_path LIKE ? LIMIT 1',
            (generation, 'worldinfo', 'world_global', prefix),
        ).fetchone()
        return row is not None

    for row in stat_rows:
        path = str(row['category_path'] or '')
        if not path:
            continue
        has_count = int(row['subtree_count'] or 0) > 0
        if requested_entity_type == 'world_global':
            folder_semantics[path] = {'has_physical_folder': True, 'has_virtual_items': False}
            if not has_count and not _has_physical_child_folder(path):
                empty_physical_folders.add(path)
        elif requested_entity_type == 'world_all':
            has_physical_folder = _has_stat_row('world_global', path)
            physical_count = _stat_count('world_global', path)
            resource_count = _stat_count('world_resource', path)
            embedded_count = _stat_count('world_embedded', path)
            folder_semantics[path] = {
                'has_physical_folder': has_physical_folder,
                'has_virtual_items': bool(resource_count > 0 or embedded_count > 0),
            }
            if has_physical_folder and physical_count == 0 and not _has_physical_child_folder(path):
                empty_physical_folders.add(path)
        else:
            folder_semantics[path] = {'has_physical_folder': False, 'has_virtual_items': has_count}

    return all_folders, category_counts, empty_physical_folders, folder_semantics


def _build_search_clause(search, search_mode, search_field, generation, extras, *, literal_only=False):
    """构造搜索 WHERE 片段。

    ``extras`` 是 ``[(sql_fragment, [params...]), ...]``，会与名称/内容条件一起
    OR 进同一个括号组 —— 这是既有语义：备注摘要命中或所属角色卡命中都算搜索命中。

    返回 ``(clause, params, degraded)``。``degraded`` 为 True 表示当前模式
    无法表达该输入，已退化为名称匹配（前端据此提示用户）。

    关键性能点：FTS 子查询里的 ``generation`` 必须用占位符传参，不能写成
    ``generation = e.generation``。后者会让 SQLite 生成 CORRELATED LIST SUBQUERY，
    对每一行外层记录重跑一次 FTS 扫描，实测慢约 380 倍。
    """
    field = _normalized_search_field(search_field)
    field_clause, field_params = _build_field_clause(field, search)

    if field_clause:
        # 精确分类：只在该列上匹配，附加来源不再参与 OR（用户明确限定了范围）。
        return field_clause, field_params, False

    # 智能搜索：名称 + 内容 + 备注/角色卡等附加来源。
    terms = ['LOWER(e.name) LIKE ?']
    params = [f'%{search.lower()}%']
    degraded = False

    if not literal_only:
        if search_mode == 'fulltext':
            match_query = build_fts_match_query(search)
            if match_query:
                terms.insert(
                    0,
                    'e.entity_id IN (SELECT entity_id FROM index_search_full_v2'
                    ' WHERE generation = ? AND index_search_full_v2 MATCH ?)',
                )
                params.insert(0, match_query)
                params.insert(0, generation)
            else:
                # 输入只剩标点，FTS 无法表达；不带词地 MATCH 会命中 0 行。
                degraded = True
        else:
            terms.insert(
                0,
                'e.entity_id IN (SELECT entity_id FROM index_search_fast_v2'
                " WHERE generation = ? AND content LIKE ? ESCAPE '\\')",
            )
            params.insert(0, f'%{escape_like(search.lower())}%')
            params.insert(0, generation)

    for fragment, fragment_params in extras or []:
        terms.append(fragment)
        params.extend(fragment_params)

    return '(' + ' OR '.join(terms) + ')', params, degraded


def _build_search_extras(filters):
    """搜索 OR 组里的附加来源条件：世界书备注路径与所属角色卡。"""
    extras = []

    extra_source_paths = [str(path) for path in (filters.get('source_paths') or []) if str(path).strip()]
    if extra_source_paths:
        placeholders = ', '.join('?' for _ in extra_source_paths)
        extras.append((
            f"LOWER(REPLACE(e.source_path, '\\', '/')) IN ({placeholders})",
            [str(path).replace('\\', '/').lower() for path in extra_source_paths],
        ))

    extra_owner_entity_ids = [str(value) for value in (filters.get('owner_entity_ids') or []) if str(value).strip()]
    if extra_owner_entity_ids:
        placeholders = ', '.join('?' for _ in extra_owner_entity_ids)
        extras.append((
            f'e.owner_entity_id IN ({placeholders})',
            extra_owner_entity_ids,
        ))

    return extras


def _build_query_parts(filters, generation: int, *, literal_only=False):
    where = ['e.generation = ?', WORLD_ENTITY_TYPE_FILTER]
    params = [generation]
    search_mode = str(filters.get('search_mode') or 'fast').strip().lower()
    if search_mode not in ('fast', 'fulltext'):
        search_mode = 'fast'

    requested_type = str(filters.get('type') or 'all').strip().lower()
    requested_entity_type = _world_entity_type(requested_type)
    if requested_entity_type != 'world_all':
        where.append('e.entity_type = ?')
        params.append(requested_entity_type)

    category = _normalized_category(filters.get('category') or '')
    if category:
        where.append('(e.display_category = ? OR e.display_category LIKE ?)')
        params.extend([category, f'{category}/%'])

    search_field = _normalized_search_field(filters.get('search_field'))
    degraded = False
    search = str(filters.get('search') or '').strip()
    if search:
        clause, search_params, degraded = _build_search_clause(
            search,
            search_mode,
            search_field,
            generation,
            _build_search_extras(filters),
            literal_only=literal_only,
        )
        if clause:
            where.append(clause)
            params.extend(search_params)
        else:
            # 输入无法表达为有效查询时不放宽到「全部结果」，直接返回空集。
            where.append('0 = 1')

        extra_source_paths = [str(path) for path in (filters.get('source_paths') or []) if str(path).strip()]
        if extra_source_paths:
            placeholders = ', '.join('?' for _ in extra_source_paths)
            where.append(f"LOWER(REPLACE(e.source_path, '\\', '/')) IN ({placeholders})")
            params.extend(str(path).replace('\\', '/').lower() for path in extra_source_paths)

        extra_owner_entity_ids = [str(value) for value in (filters.get('owner_entity_ids') or []) if str(value).strip()]
        if extra_owner_entity_ids:
            placeholders = ', '.join('?' for _ in extra_owner_entity_ids)
            where.append(f'e.owner_entity_id IN ({placeholders})')
            params.extend(extra_owner_entity_ids)

    sql = f'''
        SELECT
            e.entity_id AS id,
            e.name,
            e.source_path AS path,
            e.filename,
            e.owner_entity_id,
            e.display_category,
            e.physical_category,
            e.category_mode,
            e.summary_preview,
            e.updated_at AS mtime,
            e.source_revision,
            CASE
                WHEN e.entity_type = 'world_global' THEN 'global'
                WHEN e.entity_type = 'world_resource' THEN 'resource'
                ELSE 'embedded'
            END AS type,
            CASE
                WHEN e.entity_type = 'world_global' THEN 'global'
                WHEN e.entity_type = 'world_resource' THEN 'resource'
                ELSE 'embedded'
            END AS source_type
        FROM index_entities_v2 e
        WHERE {' AND '.join(where)}
        ORDER BY e.sort_mtime DESC, e.sort_name ASC
    '''
    return requested_entity_type, search, search_field, degraded, sql, where, params


def _run_query(conn, filters, generation: int, *, literal_only=False):
    (
        requested_entity_type,
        search,
        search_field,
        search_degraded,
        sql,
        where,
        params,
    ) = _build_query_parts(filters, generation, literal_only=literal_only)
    paginate = bool(filters.get('paginate', True))
    query_params = list(params)
    if paginate:
        page_size = int(filters.get('page_size') or 20)
        offset = (int(filters.get('page') or 1) - 1) * page_size
        sql = f'{sql} LIMIT ? OFFSET ?'
        query_params.extend([page_size, offset])

    items = [dict(row) for row in conn.execute(sql, query_params).fetchall()]
    total = conn.execute(
        f"SELECT COUNT(*) FROM index_entities_v2 e WHERE {' AND '.join(where)}",
        params,
    ).fetchone()[0]
    return (
        requested_entity_type,
        search,
        search_field,
        search_degraded,
        items,
        int(total),
    )


def _not_ready_result():
    """索引未就绪时的返回值。

    键集合被 tests/test_worldinfo_index_list_api.py 的闭等值断言锁定，
    不要在这里追加新键。
    """
    return {
        'items': [],
        'total': 0,
        'all_folders': [],
        'category_counts': {},
        'folder_capabilities': {},
        'index_ready': False,
    }


def query_worldinfo_index(filters):
    search = str(filters.get('search') or '').strip()
    try:
        with _connect(filters.get('db_path')) as conn:
            generation = get_active_generation(conn, 'worldinfo')
            if generation <= 0:
                return _not_ready_result()

            requested_entity_type, search, search_field, search_degraded, items, total = _run_query(
                conn, filters, generation, literal_only=False
            )
            stats_result = _category_stats_metadata(conn, requested_entity_type, generation)
            if stats_result is None:
                all_folders, category_counts, empty_physical_folders, folder_semantics = _fallback_folder_metadata(conn, requested_entity_type, generation)
            else:
                all_folders, category_counts, empty_physical_folders, folder_semantics = stats_result
    except sqlite3.OperationalError as exc:
        if search and _is_malformed_match_error(exc):
            with _connect(filters.get('db_path')) as conn:
                generation = get_active_generation(conn, 'worldinfo')
                if generation <= 0:
                    return _not_ready_result()
                (
                    requested_entity_type,
                    _search,
                    search_field,
                    _degraded,
                    items,
                    total,
                ) = _run_query(conn, filters, generation, literal_only=True)
                # 退化到名称匹配，明确告诉调用方这次搜索不完整。
                search_degraded = True
                stats_result = _category_stats_metadata(conn, requested_entity_type, generation)
                if stats_result is None:
                    all_folders, category_counts, empty_physical_folders, folder_semantics = _fallback_folder_metadata(conn, requested_entity_type, generation)
                else:
                    all_folders, category_counts, empty_physical_folders, folder_semantics = stats_result
        else:
            raise

    return {
        'items': items,
        'total': int(total),
        'all_folders': all_folders,
        'category_counts': category_counts,
        'folder_capabilities': {
            path: {
                **caps,
                'can_delete_physical_folder': path in empty_physical_folders,
            }
            for path, caps in _build_folder_capabilities(all_folders, folder_semantics).items()
        },
        'index_ready': True,
        'search_field': search_field,
        'search_degraded': bool(search_degraded),
    }
