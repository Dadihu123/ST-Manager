import logging
import sqlite3
import time


logger = logging.getLogger(__name__)


DB_SCHEMA_VERSION = 1
INDEX_RUNTIME_SCHEMA_VERSION = 1


# 构建进度列：老库用 ALTER TABLE 补齐（CREATE TABLE IF NOT EXISTS 不会加列）。
# 有了这两列，前端才能显示「已处理 / 总数」，而不是只有一个不确定的 phase。
BUILD_STATE_PROGRESS_COLUMNS = (
    ('progress_done', 'INTEGER NOT NULL DEFAULT 0'),
    ('progress_total', 'INTEGER NOT NULL DEFAULT 0'),
)


RUNTIME_SCHEMA_STATEMENTS = [
    '''
    CREATE TABLE IF NOT EXISTS index_schema_state (
        component TEXT PRIMARY KEY,
        target_version INTEGER NOT NULL,
        applied_version INTEGER NOT NULL,
        state TEXT NOT NULL,
        started_at REAL NOT NULL DEFAULT 0,
        finished_at REAL NOT NULL DEFAULT 0,
        last_error TEXT DEFAULT '',
        owner_token TEXT DEFAULT ''
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_build_state (
        scope TEXT PRIMARY KEY,
        active_generation INTEGER NOT NULL DEFAULT 0,
        building_generation INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'empty',
        phase TEXT NOT NULL DEFAULT '',
        build_reason TEXT NOT NULL DEFAULT '',
        started_at REAL NOT NULL DEFAULT 0,
        finished_at REAL NOT NULL DEFAULT 0,
        last_error TEXT DEFAULT '',
        owner_token TEXT DEFAULT '',
        items_written INTEGER NOT NULL DEFAULT 0
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_entities_v2 (
        generation INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        source_path TEXT NOT NULL,
        owner_entity_id TEXT DEFAULT '',
        name TEXT NOT NULL,
        filename TEXT NOT NULL,
        display_category TEXT DEFAULT '',
        physical_category TEXT DEFAULT '',
        category_mode TEXT DEFAULT 'physical',
        favorite INTEGER DEFAULT 0,
        summary_preview TEXT DEFAULT '',
        updated_at REAL DEFAULT 0,
        import_time REAL DEFAULT 0,
        token_count INTEGER DEFAULT 0,
        sort_name TEXT DEFAULT '',
        sort_mtime REAL DEFAULT 0,
        thumb_url TEXT DEFAULT '',
        source_revision TEXT DEFAULT '',
        PRIMARY KEY (generation, entity_id)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_entity_tags_v2 (
        generation INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (generation, entity_id, tag)
    )
    ''',
    '''
    CREATE VIRTUAL TABLE IF NOT EXISTS index_search_fast_v2 USING fts5(
        generation UNINDEXED,
        entity_id UNINDEXED,
        content
    )
    ''',
    '''
    CREATE VIRTUAL TABLE IF NOT EXISTS index_search_full_v2 USING fts5(
        generation UNINDEXED,
        entity_id UNINDEXED,
        content
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_category_stats_v2 (
        generation INTEGER NOT NULL,
        scope TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        category_path TEXT NOT NULL,
        direct_count INTEGER NOT NULL DEFAULT 0,
        subtree_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (generation, scope, entity_type, category_path)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_facet_stats_v2 (
        generation INTEGER NOT NULL,
        scope TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        facet_name TEXT NOT NULL,
        facet_value TEXT NOT NULL,
        facet_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (generation, scope, entity_type, facet_name, facet_value)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS index_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_type TEXT NOT NULL,
        entity_id TEXT DEFAULT '',
        source_path TEXT DEFAULT '',
        payload_json TEXT DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
        started_at REAL DEFAULT 0,
        finished_at REAL DEFAULT 0,
        error_msg TEXT DEFAULT ''
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_index_jobs_status_id ON index_jobs(status, id)',
    'CREATE INDEX IF NOT EXISTS idx_index_jobs_type_status_id ON index_jobs(job_type, status, id)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_type_sort ON index_entities_v2(generation, entity_type, sort_mtime DESC, sort_name ASC)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_category ON index_entities_v2(generation, display_category)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_owner ON index_entities_v2(generation, owner_entity_id)',
    'CREATE INDEX IF NOT EXISTS idx_index_entity_tags_v2_gen_tag_entity ON index_entity_tags_v2(generation, tag, entity_id)',
]


def _scope_generation_filters(scope: str) -> tuple[str, str, str]:
    if scope == 'cards':
        return "entity_type = 'card'", 'card::%', 'cards'
    return "entity_type IN ('world_global', 'world_resource', 'world_embedded')", 'world::%', 'worldinfo'


def _find_obsolete_generations(conn: sqlite3.Connection, scope: str, active_generation: int) -> list[int]:
    entity_where, entity_id_pattern, stats_scope = _scope_generation_filters(scope)
    rows = conn.execute(
        f'''
        SELECT generation FROM index_entities_v2 WHERE {entity_where}
        UNION
        SELECT generation FROM index_entity_tags_v2 WHERE entity_id LIKE ?
        UNION
        SELECT generation FROM index_search_fast_v2 WHERE entity_id LIKE ?
        UNION
        SELECT generation FROM index_search_full_v2 WHERE entity_id LIKE ?
        UNION
        SELECT generation FROM index_category_stats_v2 WHERE scope = ?
        UNION
        SELECT generation FROM index_facet_stats_v2 WHERE scope = ?
        ORDER BY generation
        ''',
        (entity_id_pattern, entity_id_pattern, entity_id_pattern, stats_scope, stats_scope),
    ).fetchall()
    return [
        int(row[0] or 0)
        for row in rows
        if int(row[0] or 0) > 0 and int(row[0] or 0) != int(active_generation)
    ]


def _ensure_build_state_progress_columns(conn: sqlite3.Connection):
    """给历史数据库补上进度列。

    ``CREATE TABLE IF NOT EXISTS`` 只负责建新表，不会给已有表加列，因此升级
    路径必须单独 ALTER。列已存在时静默跳过。
    """
    try:
        cursor = conn.execute('PRAGMA table_info(index_build_state)')
        rows = cursor.fetchall() if cursor is not None else []
        existing = {str(row[1]) for row in rows}
    except sqlite3.Error:
        return
    except (AttributeError, TypeError, IndexError):
        # 某些测试替身会返回非游标对象；进度列是可选增强，读不到就跳过。
        return

    for column, definition in BUILD_STATE_PROGRESS_COLUMNS:
        if column in existing:
            continue
        try:
            conn.execute(f'ALTER TABLE index_build_state ADD COLUMN {column} {definition}')
        except sqlite3.OperationalError as exc:
            logger.warning('补建索引构建进度列失败 (%s): %s', column, exc)


def ensure_index_runtime_schema(conn: sqlite3.Connection):
    for statement in RUNTIME_SCHEMA_STATEMENTS:
        conn.execute(statement)

    _ensure_build_state_progress_columns(conn)

    # 扫描器簿记状态（最近一次全量校验时间等），与索引构建状态分开存放。
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS scan_runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL DEFAULT 0
        )
        '''
    )

    conn.execute(
        '''
        INSERT INTO index_schema_state(
            component, target_version, applied_version, state, started_at, finished_at, last_error, owner_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(component) DO UPDATE SET
            target_version = excluded.target_version,
            applied_version = excluded.applied_version,
            state = excluded.state
        ''',
        ('db', DB_SCHEMA_VERSION, DB_SCHEMA_VERSION, 'ready', 0, 0, '', ''),
    )
    conn.execute(
        '''
        INSERT INTO index_schema_state(
            component, target_version, applied_version, state, started_at, finished_at, last_error, owner_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(component) DO UPDATE SET
            target_version = excluded.target_version,
            applied_version = excluded.applied_version,
            state = excluded.state
        ''',
        (
            'index_runtime',
            INDEX_RUNTIME_SCHEMA_VERSION,
            INDEX_RUNTIME_SCHEMA_VERSION,
            'ready',
            0,
            0,
            '',
            '',
        ),
    )
    conn.execute(
        '''
        INSERT OR IGNORE INTO index_build_state(
            scope, active_generation, building_generation, state, phase, build_reason,
            started_at, finished_at, last_error, owner_token, items_written
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        ('cards', 0, 0, 'empty', '', '', 0, 0, '', '', 0),
    )
    conn.execute(
        '''
        INSERT OR IGNORE INTO index_build_state(
            scope, active_generation, building_generation, state, phase, build_reason,
            started_at, finished_at, last_error, owner_token, items_written
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        ('worldinfo', 0, 0, 'empty', '', '', 0, 0, '', '', 0),
    )
    conn.commit()


def allocate_build_generation(conn: sqlite3.Connection, scope: str) -> int:
    row = conn.execute(
        'SELECT active_generation, building_generation FROM index_build_state WHERE scope = ?',
        (scope,),
    ).fetchone()
    active_generation = int((row or (0, 0))[0] or 0)
    building_generation = int((row or (0, 0))[1] or 0)
    next_generation = max(active_generation, building_generation) + 1
    conn.execute(
        '''
        UPDATE index_build_state
        SET building_generation = ?,
            state = ?,
            phase = ?,
            started_at = ?,
            finished_at = 0,
            last_error = ?,
            items_written = 0,
            progress_done = 0,
            progress_total = 0
        WHERE scope = ?
        ''',
        (next_generation, 'running', 'prepare_generation', time.time(), '', scope),
    )
    conn.commit()
    return next_generation


def get_active_generation(conn: sqlite3.Connection, scope: str) -> int:
    try:
        row = conn.execute(
            'SELECT active_generation FROM index_build_state WHERE scope = ?',
            (scope,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc).lower():
            return 0
        raise
    return int((row or [0])[0] or 0)


def update_build_progress(
    conn: sqlite3.Connection,
    scope: str,
    *,
    phase: str | None = None,
    done: int | None = None,
    total: int | None = None,
    commit: bool = False,
):
    """记录构建进度，供前端显示「已处理 / 总数」。

    默认不提交：调用方通常正处在自己的写事务里（分批提交点），把进度与数据
    一起落盘即可，避免额外的事务开销。
    """
    assignments = []
    params = []
    if phase is not None:
        assignments.append('phase = ?')
        params.append(str(phase))
    if done is not None:
        assignments.append('progress_done = ?')
        params.append(int(done))
    if total is not None:
        assignments.append('progress_total = ?')
        params.append(int(total))
    if not assignments:
        return

    params.append(scope)
    try:
        conn.execute(
            f"UPDATE index_build_state SET {', '.join(assignments)} WHERE scope = ?",
            params,
        )
    except sqlite3.OperationalError as exc:
        # 进度是纯展示信息，列缺失不应中断构建本身。
        logger.debug('写入索引构建进度失败 (%s): %s', scope, exc)
        return
    except (AttributeError, TypeError):
        # 测试替身连接没有真实游标时同样只跳过进度写入。
        return
    if commit:
        conn.commit()


def get_build_progress(conn: sqlite3.Connection, scope: str) -> dict:
    """读取某个 scope 的构建进度；表/列缺失时返回全 0。"""
    try:
        cursor = conn.execute(
            'SELECT progress_done, progress_total FROM index_build_state WHERE scope = ?',
            (scope,),
        )
        row = cursor.fetchone() if cursor is not None else None
    except sqlite3.OperationalError:
        return {'done': 0, 'total': 0}
    except (AttributeError, TypeError):
        return {'done': 0, 'total': 0}
    if not row:
        return {'done': 0, 'total': 0}
    return {'done': int(row[0] or 0), 'total': int(row[1] or 0)}


def update_build_state(conn: sqlite3.Connection, scope: str, **updates):
    columns = []
    params = []
    for key, value in updates.items():
        columns.append(f'{key} = ?')
        params.append(value)

    if not columns:
        return

    params.append(scope)
    conn.execute(
        f"UPDATE index_build_state SET {', '.join(columns)} WHERE scope = ?",
        params,
    )
    conn.commit()


def activate_generation(conn: sqlite3.Connection, scope: str, generation: int, *, items_written: int):
    obsolete_generations = _find_obsolete_generations(conn, scope, generation)
    cursor = conn.execute(
        '''
        UPDATE index_build_state
        SET active_generation = ?,
            building_generation = 0,
            state = 'ready',
            phase = 'ready',
            finished_at = ?,
            last_error = '',
            items_written = ?,
            progress_done = CASE WHEN progress_total > 0 THEN progress_total ELSE progress_done END
        WHERE scope = ? AND building_generation = ?
        ''',
        (generation, time.time(), int(items_written), scope, generation),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        return False

    # 与激活同一个事务写入搜索内容格式版本：若中途崩溃，两者一起回滚，
    # 下次启动会重新构建，而不会出现「已激活但版本未记录」导致的反复重建。
    set_search_content_format_version(conn, scope, SEARCH_CONTENT_FORMAT_VERSION, commit=False)

    conn.commit()
    for obsolete_generation in obsolete_generations:
        clear_generation_data(conn, scope, obsolete_generation)
    return True


def clear_generation_data(conn: sqlite3.Connection, scope: str, generation: int):
    entity_prefix, entity_id_pattern, stats_scope = _scope_generation_filters(scope)
    entity_ids = [
        row[0]
        for row in conn.execute(
            f'SELECT entity_id FROM index_entities_v2 WHERE generation = ? AND {entity_prefix}',
            (generation,),
        ).fetchall()
    ]

    conn.execute(
        f'DELETE FROM index_entities_v2 WHERE generation = ? AND {entity_prefix}',
        (generation,),
    )

    conn.execute(
        'DELETE FROM index_entity_tags_v2 WHERE generation = ? AND entity_id LIKE ?',
        (generation, entity_id_pattern),
    )
    conn.execute(
        'DELETE FROM index_search_fast_v2 WHERE generation = ? AND entity_id LIKE ?',
        (generation, entity_id_pattern),
    )
    conn.execute(
        'DELETE FROM index_search_full_v2 WHERE generation = ? AND entity_id LIKE ?',
        (generation, entity_id_pattern),
    )

    for entity_id in entity_ids:
        conn.execute(
            'DELETE FROM index_entity_tags_v2 WHERE generation = ? AND entity_id = ?',
            (generation, entity_id),
        )
        conn.execute(
            'DELETE FROM index_search_fast_v2 WHERE generation = ? AND entity_id = ?',
            (generation, entity_id),
        )
        conn.execute(
            'DELETE FROM index_search_full_v2 WHERE generation = ? AND entity_id = ?',
            (generation, entity_id),
        )

    conn.execute('DELETE FROM index_category_stats_v2 WHERE generation = ? AND scope = ?', (generation, stats_scope))
    conn.execute('DELETE FROM index_facet_stats_v2 WHERE generation = ? AND scope = ?', (generation, stats_scope))
    conn.commit()


SCAN_STATE_LAST_FULL_SCAN_AT = 'last_full_scan_at'

# FTS 搜索内容列的格式版本。写入侧改变内容形态时必须 +1，否则老索引不会重建，
# 搜索会静默失效（例如中文子串在未切分的旧内容上永远命中 0 条）。
#   1 = 原文（历史格式，CJK 未切分）
#   2 = CJK 逐字切分 + 世界书条目正文
SEARCH_CONTENT_FORMAT_VERSION = 2


def search_content_format_state_key(scope: str) -> str:
    """记录某个 scope 的搜索内容格式版本所用的 scan_runtime_state 键。"""
    return f'search_content_format::{str(scope or "").strip() or "unknown"}'


def get_search_content_format_version(conn: sqlite3.Connection, scope: str) -> int:
    """读取该 scope 已建索引的搜索内容格式版本；未知返回 0。"""
    raw = get_scan_state(conn, search_content_format_state_key(scope), '')
    try:
        return int(str(raw or '0') or 0)
    except (TypeError, ValueError):
        return 0


def set_search_content_format_version(
    conn: sqlite3.Connection,
    scope: str,
    version: int = SEARCH_CONTENT_FORMAT_VERSION,
    *,
    commit: bool = True,
) -> None:
    set_scan_state(conn, search_content_format_state_key(scope), str(int(version)), commit=commit)


def get_scan_state(conn: sqlite3.Connection, key: str, default: str = '') -> str:
    """读取扫描器簿记状态；缺失或表不存在时返回默认值。"""
    try:
        row = conn.execute(
            'SELECT value FROM scan_runtime_state WHERE key = ?',
            (str(key),),
        ).fetchone()
    except sqlite3.Error:
        return default
    if not row:
        return default
    return str(row[0] if not isinstance(row, sqlite3.Row) else row['value'] or default)


def set_scan_state(conn: sqlite3.Connection, key: str, value, *, commit: bool = True) -> None:
    """写入扫描器簿记状态。"""
    try:
        conn.execute(
            '''
            INSERT INTO scan_runtime_state(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            ''',
            (str(key), str(value), time.time()),
        )
        if commit:
            conn.commit()
    except sqlite3.Error:
        pass

