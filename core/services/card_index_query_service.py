import json
import sqlite3
from collections import OrderedDict
from contextlib import closing
from threading import Lock

from core.config import DEFAULT_DB_PATH
from core.data import card_list_projection as logical
from core.data.index_runtime_store import get_active_generation
from core.data.sqlite_capabilities import supports_fts5
from core.utils.search_text import build_fts_match_query, escape_like

_facets_cache = OrderedDict()
_facets_lock = Lock()


def _directory_filter(filters, *, scope=None, category=None):
    scope = scope or filters['search_scope']
    category = filters['category'] if category is None else category
    where, args = [], []
    if scope == 'current':
        directory = '' if category == '根目录' else category.lower()
        if not filters['recursive']:
            where.append('category_key=?')
            args.append(directory)
        elif directory:
            where.append('category_key>=? AND category_key<? AND (category_key=? OR category_key>=?)')
            args.extend((directory, directory + '0', directory, directory + '/'))
    current = logical.category_key(category) if category != '根目录' else ''
    visible = []
    for folder in map(logical.category_key, filters['isolated']):
        if folder:
            visible.append((folder, current == folder or current.startswith(folder + '/')))
    if visible:
        # Preserve the first matching isolation rule for nested isolation settings.
        cases = []
        for folder, allowed in visible:
            cases.append(f'WHEN isolated_key=? OR (isolated_key>=? AND isolated_key<?) THEN {int(allowed)}')
            args.extend((folder, folder + '/', folder + '0'))
        where.append(f"(CASE {' '.join(cases)} ELSE 1 END)=1")
    return where, args


def _logical_filter(generation, filters):
    where, args = _directory_filter(filters)
    where.insert(0, 'c.generation=?')
    args.insert(0, generation)
    if filters['search_scope'] != 'full':
        if filters['fav_filter'] in ('included', 'excluded'):
            where.append('c.favorite=?')
            args.append(int(filters['fav_filter'] == 'included'))
        for tag in filters['include_tags']:
            if filters['category'] and filters['search_scope'] == 'current':
                # A folder query already restricts candidates. Avoid building a library-wide
                # set of keys for each common tag for both the exact count and the page.
                where.append('EXISTS (SELECT 1 FROM card_list_tags t '
                             'WHERE t.generation=c.generation AND t.key=c.key AND t.tag=?)')
                args.append(tag)
            else:
                where.append('c.key IN (SELECT key FROM card_list_tags WHERE generation=? AND tag=?)')
                args.extend((generation, tag))
        for tag in filters['exclude_tags']:
            where.append('NOT EXISTS (SELECT 1 FROM card_list_tags t '
                         'WHERE t.generation=c.generation AND t.key=c.key AND t.tag=?)')
            args.append(tag)
    for field, op, key in (
        ('imported', '>=', 'import_date_from'), ('imported', '<', 'import_date_to'),
        ('mtime', '>=', 'modified_date_from'), ('mtime', '<', 'modified_date_to'),
        ('tokens', '>=', 'token_min'), ('tokens', '<=', 'token_max'),
    ):
        if filters.get(key) is not None:
            where.append(f'c.{field}{op}?')
            args.append(filters[key])
    search = filters['search']
    if search:
        kind = filters['search_type']
        kind = kind if kind in ('name', 'filename', 'tags', 'creator') else 'mix'
        if filters['search_mode'] == 'fulltext' and supports_fts5():
            match = build_fts_match_query(search)
            if match:
                where.append('c.rowid IN (SELECT rowid FROM card_list_fts WHERE card_list_fts MATCH ?)')
                args.append(f'{kind}:({match})')
            else:
                where.append('0')
        else:
            fields = {'name': ('name_key',), 'filename': ('filename_key',), 'creator': ('creator_key',),
                      'tags': (), 'mix': ('name_key', 'filename_key', 'note_key')}[kind]
            tests = [f'instr(c.{field},?)>0' for field in fields]
            if kind in ('tags', 'mix'):
                tests.append('EXISTS (SELECT 1 FROM card_list_tags t WHERE t.generation=c.generation '
                             'AND t.key=c.key AND instr(t.tag_key,?)>0)')
            where.append(f"({' OR '.join(tests)})")
            args.extend([search] * len(tests))
    return ' AND '.join(where), args


def _logical_order(filters):
    column, direction = filters['sort'].split('_')
    field = {'date': 'mtime', 'import': 'import_sort', 'name': 'name_key', 'token': 'tokens'}[column]
    direction = 'DESC' if direction == 'desc' else 'ASC'
    return (('c.favorite DESC,' if filters['fav_first'] else '') + f'c.{field} {direction},c.key {direction}')


def _facet_tags(conn, generation, filters, *, global_tags=False):
    where, params = _directory_filter(filters, scope='all_dirs' if global_tags else None,
                                       category='' if global_tags else None)
    where.insert(0, 'generation=? AND kind=1')
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT tag FROM card_list_facets WHERE {' AND '.join(where)}", (generation, *params))}


def _logical_statistics(conn, generation, filters):
    revision = conn.execute('SELECT stats_key,stats_revision FROM card_list_state WHERE generation=?',
                            (generation,)).fetchone()
    key = (*revision, filters['search_scope'], filters['category'], filters['recursive'], tuple(filters['isolated']))
    with _facets_lock:
        cached = _facets_cache.get(key)
        if cached is not None:
            _facets_cache.move_to_end(key)
            return cached
    folders = {r[0] for r in conn.execute(
        'SELECT folder FROM card_list_folders WHERE generation=? AND bundle=0', (generation,))}
    counts = dict.fromkeys(folders, 0)
    library_total = 0
    for category, count in conn.execute(
            'SELECT category,count FROM card_list_facets WHERE generation=? AND kind=0', (generation,)):
        library_total += count
        current = category
        while True:
            counts[current] = counts.get(current, 0) + count
            if current:
                folders.add(current)
            if '/' not in current:
                break
            current = current.rpartition('/')[0]
    result = dict(all_folders=sorted(folders), category_counts=counts, library_total=library_total,
                  sidebar_tags=_facet_tags(conn, generation, filters),
                  global_tags=_facet_tags(conn, generation, filters, global_tags=True))
    with _facets_lock:
        _facets_cache[key] = result
        _facets_cache.move_to_end(key)
        if len(_facets_cache) > 24:
            _facets_cache.popitem(last=False)
    return result


def query_logical_cards(filters, *, target=None):
    """A page and its statistics (or a target rank) from one active-generation snapshot."""
    with closing(_connect(filters['db_path'])) as conn, conn:
        conn.execute('BEGIN')
        generation = get_active_generation(conn, 'cards')
        if (logical.root_changed(conn, generation, filters['root'])
                or not logical.metadata_matches(conn, filters['root'])):
            return {'index_ready': False}
        if not logical.eligible(conn, generation, filters['root']):
            return None
        stale = bool(conn.execute('SELECT 1 FROM card_list_dirty WHERE generation=? LIMIT 1', (generation,)).fetchone())
        if target:
            item = conn.execute('SELECT key,card_id,category FROM card_list_items '
                                'WHERE generation=? AND card_id=?', (generation, target)).fetchone()
            if not item:
                item = conn.execute('SELECT key,card_id,category FROM card_list_items WHERE generation=? AND key=?',
                                    (generation, target)).fetchone()
            if not item:
                parent = target.rpartition('/')[0]
                item = conn.execute('''SELECT key,card_id,category FROM card_list_items
                    WHERE generation=? AND key=? AND EXISTS (SELECT 1 FROM json_each(payload,'$.versions')
                    WHERE json_extract(value,'$.id')=?)''', (generation, parent, target)).fetchone()
                if not item:
                    return {}
            if filters['category'] is None:
                filters = {**filters, 'category': item['category']}
            where, args = _logical_filter(generation, filters)
            rank = conn.execute(f'''SELECT rank FROM (
                SELECT c.key,row_number() OVER (ORDER BY {_logical_order(filters)}) AS rank
                FROM card_list_items c WHERE {where}) WHERE key=?''', (*args, item['key'])).fetchone()
            return (dict(found_id=item['card_id'], page=(rank[0] - 1) // filters['page_size'] + 1,
                         category=filters['category']) if rank else {})
        where, args = _logical_filter(generation, filters)
        statistics = _logical_statistics(conn, generation, filters)
        directory_where, directory_params = _directory_filter(filters)
        if where == ' AND '.join(['c.generation=?', *directory_where]):
            if not directory_where:
                total = statistics['library_total']
            else:
                where_stats = ' AND '.join(['generation=?', 'kind=0', *directory_where])
                total = conn.execute(f'SELECT coalesce(sum(count),0) FROM card_list_facets WHERE {where_stats}',
                                     (generation, *directory_params)).fetchone()[0]
        else:
            # Do not let the requested sort's index drive the exact count for a small folder.
            count_index = (' INDEXED BY card_list_folder_sort_tokens' if filters['category']
                           and filters['category'] != '根目录' and filters['search_scope'] == 'current' else '')
            total = conn.execute(f'SELECT count(*) FROM card_list_items c{count_index} WHERE {where}',
                                 args).fetchone()[0]
        size, page = filters['page_size'], filters['page']
        # Keep wide payloads out of OFFSET and sort operations.
        rows = conn.execute(f'''SELECT rowid FROM card_list_items c WHERE {where}
            ORDER BY {_logical_order(filters)} LIMIT ? OFFSET ?''', (*args, size, (page - 1) * size)).fetchall()
        ids = [row[0] for row in rows]
        by_id = {}
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            by_id.update(conn.execute(
                f"SELECT rowid,payload FROM card_list_items WHERE rowid IN ({','.join('?' for _ in batch)})", batch))
        return dict(cards=[json.loads(by_id[rowid]) for rowid in ids], total_count=total,
                    page=page, page_size=size, index_stale=stale, **statistics)


def _is_malformed_match_error(exc):
    message = str(exc or '').lower()
    malformed_markers = (
        'fts5: syntax error',
        'unterminated string',
        'malformed match expression',
    )
    return any(marker in message for marker in malformed_markers)


def _connect(db_path=None):
    conn = sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def query_indexed_cards(filters):
    page_size = int(filters.get('page_size') or 20)
    offset = (int(filters.get('page') or 1) - 1) * page_size
    db_path = filters.get('db_path')
    search = str(filters.get('search') or '').strip()

    try:
        with _connect(db_path) as conn:
            generation = get_active_generation(conn, 'cards')
            if generation <= 0:
                return {
                    'cards': [],
                    'total_count': 0,
                    'index_ready': False,
                }

            where = ['e.generation = ?', "e.entity_type = 'card'"]
            params = [generation]
            search_scope = str(filters.get('search_scope') or 'current').strip().lower()

            category = str(filters.get('category') or '').strip()
            if category:
                where.append('(e.display_category = ? OR e.display_category LIKE ?)')
                params.extend([category, f'{category}/%'])

            if search_scope != 'full':
                if filters.get('fav_filter') == 'included':
                    where.append('e.favorite = 1')
                elif filters.get('fav_filter') == 'excluded':
                    where.append('e.favorite = 0')

                include_tags = [tag for tag in filters.get('include_tags', []) if tag]
                for tag in include_tags:
                    where.append(
                        'EXISTS (SELECT 1 FROM index_entity_tags_v2 t WHERE t.generation = e.generation AND t.entity_id = e.entity_id AND t.tag = ?)'
                    )
                    params.append(tag)

                exclude_tags = [tag for tag in filters.get('exclude_tags', []) if tag]
                for tag in exclude_tags:
                    where.append(
                        'NOT EXISTS (SELECT 1 FROM index_entity_tags_v2 t WHERE t.generation = e.generation AND t.entity_id = e.entity_id AND t.tag = ?)'
                    )
                    params.append(tag)

            token_min = filters.get('token_min')
            if token_min is not None:
                where.append('COALESCE(e.token_count, 0) >= ?')
                params.append(int(token_min))

            token_max = filters.get('token_max')
            if token_max is not None:
                where.append('COALESCE(e.token_count, 0) <= ?')
                params.append(int(token_max))

            if search:
                # 无 FTS5 的平台（如 iOS）没有 index_search_full_v2 表，
                # 全文搜索降级为 fast 的 LIKE 路径：语义同为子串匹配，结果同样正确。
                if filters.get('search_mode') == 'fulltext' and supports_fts5():
                    # MATCH 需要语法合法的表达式；原始输入里的 . - : 等字符
                    # 会触发 fts5 语法错误或 "no such column"，因此先规范化。
                    match_query = build_fts_match_query(search)
                    if match_query:
                        where.append(
                            'e.entity_id IN (SELECT entity_id FROM index_search_full_v2'
                            ' WHERE generation = ? AND index_search_full_v2 MATCH ?)'
                        )
                        params.extend([generation, match_query])
                    else:
                        # 输入里没有可搜索的词，直接返回空集而不是全部卡片。
                        where.append('0 = 1')
                else:
                    where.append(
                        'e.entity_id IN (SELECT entity_id FROM index_search_fast_v2'
                        " WHERE generation = ? AND content LIKE ? ESCAPE '\\')"
                    )
                    params.extend([generation, f'%{escape_like(search.lower())}%'])

            sql = f'''
                SELECT
                    substr(e.entity_id, 7) AS id,
                    e.name AS char_name,
                    e.filename,
                    e.display_category AS category,
                    e.favorite AS is_favorite,
                    e.summary_preview AS ui_summary,
                    e.updated_at AS last_modified,
                    e.import_time,
                    e.token_count,
                    e.thumb_url,
                    e.source_revision
                FROM index_entities_v2 e
                WHERE {' AND '.join(where)}
                ORDER BY e.sort_mtime DESC, e.sort_name ASC
                LIMIT ? OFFSET ?
            '''
            rows = conn.execute(sql, [*params, page_size, offset]).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM index_entities_v2 e WHERE {' AND '.join(where)}",
                params,
            ).fetchone()[0]
    except sqlite3.OperationalError as exc:
        # FTS MATCH rejects some malformed-but-plausible user input such as bare quotes.
        if search and _is_malformed_match_error(exc):
            return {
                'cards': [],
                'total_count': 0,
                'index_ready': True,
            }
        raise

    return {
        'cards': [dict(row) for row in rows],
        'total_count': int(total),
        'index_ready': True,
    }
