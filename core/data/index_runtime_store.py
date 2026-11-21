import json
import logging
import sqlite3
import time
from contextlib import nullcontext

from core.data.sqlite_capabilities import supports_fts5
from core.utils.filesystem import filesystem_path_bucket


logger = logging.getLogger(__name__)


DB_SCHEMA_VERSION = 1
#: 2 = ``index_search_fast_v2`` 由 FTS5 虚拟表改为普通表（见 ``_migrate_fast_search_table``）。
INDEX_RUNTIME_SCHEMA_VERSION = 4


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
    CREATE TABLE IF NOT EXISTS index_search_fast_v2 (
        generation INTEGER NOT NULL,
        entity_id TEXT NOT NULL,
        content TEXT,
        PRIMARY KEY (generation, entity_id)
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
    'CREATE INDEX IF NOT EXISTS idx_index_jobs_status_finished ON index_jobs(status, finished_at, id)',
    # 构建期间已写入旧活动代的变化。每张卡只保留最后一次；worker 不能提前领取。
    '''CREATE TABLE IF NOT EXISTS index_card_build_changes (
        generation INTEGER NOT NULL, card_id TEXT NOT NULL, source_path TEXT NOT NULL,
        payload_json TEXT NOT NULL, PRIMARY KEY (generation, card_id)
    )''',
    'CREATE INDEX IF NOT EXISTS idx_index_jobs_type_status_id ON index_jobs(job_type, status, id)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_type_sort ON index_entities_v2(generation, entity_type, sort_mtime DESC, sort_name ASC)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_category ON index_entities_v2(generation, display_category)',
    'CREATE INDEX IF NOT EXISTS idx_index_entities_v2_gen_owner ON index_entities_v2(generation, owner_entity_id)',
    'CREATE INDEX IF NOT EXISTS idx_index_entity_tags_v2_gen_tag_entity ON index_entity_tags_v2(generation, tag, entity_id)',
    'CREATE INDEX IF NOT EXISTS idx_index_search_fast_v2_gen_entity ON index_search_fast_v2(generation, entity_id)',
]


#: 仅在 SQLite 支持 FTS5 时才建的语句。
#: ``index_search_full_v2`` 是唯一真正依赖 FTS5 的表（查询侧用 ``MATCH``）；
#: ``index_search_fast_v2`` 只用 ``LIKE``，因此已是普通表，不在此列。
FTS5_SCHEMA_STATEMENTS = [
    '''
    CREATE VIRTUAL TABLE IF NOT EXISTS index_search_full_v2 USING fts5(
        generation UNINDEXED,
        entity_id UNINDEXED,
        content
    )
    ''',
]


def _scope_generation_filters(scope: str) -> tuple[str, str, str]:
    if scope == 'cards':
        return "entity_type = 'card'", 'card::%', 'cards'
    return "entity_type IN ('world_global', 'world_resource', 'world_embedded')", 'world::%', 'worldinfo'


def _find_obsolete_generations(conn: sqlite3.Connection, scope: str, active_generation: int) -> list[int]:
    entity_where, entity_id_pattern, stats_scope = _scope_generation_filters(scope)
    # full 表只在支持 FTS5 时存在；无 FTS5 时把它从 UNION 里去掉，
    # 否则整条查询会因为「no such table」失败，连带让所有过期代清理失效。
    full_union = (
        'UNION\n        SELECT generation FROM index_search_full_v2 WHERE entity_id LIKE ?'
        if supports_fts5()
        else ''
    )
    params = [entity_id_pattern, entity_id_pattern]
    if supports_fts5():
        params.append(entity_id_pattern)
    params.extend([stats_scope, stats_scope])
    rows = conn.execute(
        f'''
        SELECT generation FROM index_entities_v2 WHERE {entity_where}
        UNION
        SELECT generation FROM index_entity_tags_v2 WHERE entity_id LIKE ?
        UNION
        SELECT generation FROM index_search_fast_v2 WHERE entity_id LIKE ?
        {full_union}
        UNION
        SELECT generation FROM index_category_stats_v2 WHERE scope = ?
        UNION
        SELECT generation FROM index_facet_stats_v2 WHERE scope = ?
        ORDER BY generation
        ''',
        params,
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


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    """读取某表的建表 SQL；表不存在或连接是测试替身时返回空串。"""
    try:
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        row = cursor.fetchone() if cursor is not None else None
    except sqlite3.Error:
        return ''
    except (AttributeError, TypeError, IndexError):
        # 测试替身连接可能返回非游标对象；迁移是可选的，读不到就跳过。
        return ''
    if not row:
        return ''
    return str(row[0] or '')


def _migrate_fast_search_table(conn: sqlite3.Connection) -> bool:
    """把历史库里的 fts5 ``index_search_fast_v2`` 改成普通表。

    ``index_search_fast_v2`` 的查询全部是 ``content LIKE``，从不用 ``MATCH``，
    因此不需要 FTS5。改成普通表后 iOS 等无 FTS5 平台也能正常搜索，且（实测）
    在 ``LIKE`` 场景下不慢于 fts5 表。

    在事务内搬运三列内容，保留当前 generation 在后台重建期间的查询能力。

    返回 True 表示发生了迁移（调用方据此记录 schema 版本）。
    """
    existing = _table_sql(conn, 'index_search_fast_v2')
    if not existing:
        # 表不存在：交给 CREATE TABLE IF NOT EXISTS 建普通表，无需迁移。
        return False
    if 'USING FTS5' not in existing.upper():
        return False

    logger.info('检测到 fts5 版 index_search_fast_v2，正在保留内容迁移为普通表')
    conn.execute('SAVEPOINT migrate_fast_search')
    try:
        conn.execute('''CREATE TABLE index_search_fast_plain (
            generation INTEGER NOT NULL, entity_id TEXT NOT NULL, content TEXT,
            PRIMARY KEY (generation, entity_id))''')
        conn.execute('''INSERT OR REPLACE INTO index_search_fast_plain
            SELECT generation, entity_id, content FROM index_search_fast_v2''')
        conn.execute('DROP TABLE index_search_fast_v2')
        conn.execute('ALTER TABLE index_search_fast_plain RENAME TO index_search_fast_v2')
        conn.execute('RELEASE migrate_fast_search')
    except sqlite3.Error:
        conn.execute('ROLLBACK TO migrate_fast_search')
        conn.execute('RELEASE migrate_fast_search')
        raise
    return True


def repair_full_search_mapping(conn):
    """校验并原子修复历史 FTS 定位映射；WAL 读者继续使用旧代。"""
    conn.execute("CREATE TABLE IF NOT EXISTS index_full_rowids (generation INTEGER NOT NULL, "
                 "entity_id TEXT NOT NULL, fts_rowid INTEGER NOT NULL UNIQUE, "
                 "PRIMARY KEY(generation, entity_id))")
    if not supports_fts5():
        return
    conn.execute('SAVEPOINT repair_full_mapping')
    try:
        # 历史重复项保留最后一次写入；不改变搜索文本格式或 active generation。
        conn.execute("DELETE FROM index_search_full_v2 WHERE rowid NOT IN "
                     "(SELECT MAX(rowid) FROM index_search_full_v2 GROUP BY generation, entity_id)")
        conn.execute("DELETE FROM index_full_rowids WHERE NOT EXISTS "
                     "(SELECT 1 FROM index_search_full_v2 f WHERE f.rowid = fts_rowid "
                     "AND f.generation = index_full_rowids.generation "
                     "AND f.entity_id = index_full_rowids.entity_id)")
        conn.execute("INSERT OR REPLACE INTO index_full_rowids "
                     "SELECT generation, entity_id, rowid FROM index_search_full_v2")
        conn.execute('RELEASE repair_full_mapping')
    except Exception:
        conn.execute('ROLLBACK TO repair_full_mapping')
        conn.execute('RELEASE repair_full_mapping')
        raise


def delete_full_search_rows(conn, generation, entity_id):
    if not supports_fts5():
        return
    conn.execute('DELETE FROM index_search_full_v2 WHERE rowid IN '
                 '(SELECT fts_rowid FROM index_full_rowids WHERE generation = ? AND entity_id = ?)',
                 (generation, entity_id))
    conn.execute('DELETE FROM index_full_rowids WHERE generation = ? AND entity_id = ?',
                 (generation, entity_id))


def ensure_index_job_columns(conn):
    """保留旧任务的路径和状态，补充去重及路径冲突重试字段。"""
    columns = {row[1] for row in conn.execute('PRAGMA table_info(index_jobs)')}
    if 'path_key' not in columns:
        conn.execute('ALTER TABLE index_jobs ADD COLUMN path_key TEXT')
        jobs = conn.execute("SELECT id,source_path FROM index_jobs "
                            "WHERE job_type='upsert_worldinfo_path' AND status IN ('pending','running','failed')")
        conn.executemany('UPDATE index_jobs SET path_key=? WHERE id=?',
                         ((filesystem_path_bucket(path), job_id) for job_id, path in jobs))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_worldinfo_jobs_pending_path ON index_jobs(path_key) "
                 "WHERE job_type='upsert_worldinfo_path' AND status='pending'")
    if 'retry_after' not in columns:
        conn.execute('ALTER TABLE index_jobs ADD COLUMN retry_after REAL NOT NULL DEFAULT 0')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_index_jobs_deferred ON index_jobs(retry_after) "
                 "WHERE retry_after>0 AND status IN ('pending','failed')")


def _ensure_worldinfo_path_keys(conn):
    conn.execute('SAVEPOINT worldinfo_path_keys')
    try:
        ensure_index_job_columns(conn)
        if not any(row[1] == 'path_key' for row in conn.execute('PRAGMA table_info(index_entities_v2)')):
            conn.execute('ALTER TABLE index_entities_v2 ADD COLUMN path_key TEXT')
            rows = conn.execute("SELECT rowid,source_path FROM index_entities_v2 WHERE entity_type='world_resource'")
            conn.executemany('UPDATE index_entities_v2 SET path_key=? WHERE rowid=?',
                             ((filesystem_path_bucket(path), row_id) for row_id, path in rows))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_world_resource_path_key "
                     "ON index_entities_v2(generation,path_key) WHERE entity_type='world_resource'")
        # 旧库可能已有资源书路径键，但还没有全局书路径键。
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' "
                            "AND name='idx_world_global_path_key'").fetchone():
            rows = conn.execute("SELECT rowid,source_path FROM index_entities_v2 WHERE entity_type='world_global'")
            conn.executemany('UPDATE index_entities_v2 SET path_key=? WHERE rowid=?',
                             ((filesystem_path_bucket(path), row_id) for row_id, path in rows))
            conn.execute("CREATE INDEX idx_world_global_path_key "
                         "ON index_entities_v2(generation,path_key) WHERE entity_type='world_global'")
        conn.execute('DROP INDEX IF EXISTS idx_world_resource_path_owner')
    except BaseException:
        conn.execute('ROLLBACK TO worldinfo_path_keys')
        raise
    finally:
        conn.execute('RELEASE worldinfo_path_keys')


def ensure_index_runtime_schema(conn: sqlite3.Connection):
    # 先迁移历史 fts5 fast 表，后面的 CREATE TABLE IF NOT EXISTS 才能建出普通表。
    _migrate_fast_search_table(conn)

    for statement in RUNTIME_SCHEMA_STATEMENTS:
        conn.execute(statement)
    _ensure_worldinfo_path_keys(conn)

    # full 表是唯一真正依赖 FTS5 的表：无 FTS5 的平台上不建，搜索降级为 fast。
    if supports_fts5():
        for statement in FTS5_SCHEMA_STATEMENTS:
            conn.execute(statement)

    mapping_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='index_full_rowids'").fetchone()
    version = conn.execute("SELECT applied_version FROM index_schema_state WHERE component='index_runtime'").fetchone()
    if not mapping_exists or not version or version[0] < INDEX_RUNTIME_SCHEMA_VERSION:
        repair_full_search_mapping(conn)
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


def activate_generation(conn: sqlite3.Connection, scope: str, generation: int, *, items_written: int,
                        rebuild_job: tuple[int, str] | None = None, activation_guard=nullcontext):
    obsolete_generations = _find_obsolete_generations(conn, scope, generation)
    cleanup_jobs = []
    with conn:
        if not conn.in_transaction:
            conn.execute('BEGIN IMMEDIATE')
        with activation_guard():
            if not _activate_generation_on_connection(conn, scope, generation, items_written, rebuild_job,
                                                      obsolete_generations, cleanup_jobs):
                conn.rollback()
                return False
            conn.commit()
    # 清理与激活分开提交。即使进程退出或清理遇锁，worker 也只重试清理。
    for job_id, obsolete in cleanup_jobs:
        try:
            cleanup_obsolete_generation(conn, scope, obsolete, pending_job_id=job_id)
        except sqlite3.Error:
            from core.context import ctx
            ctx.index_wakeup.set()
            logger.warning('索引已激活，旧代清理等待重试 (%s, %s)', scope, obsolete, exc_info=True)
            break
    return True


def _activate_generation_on_connection(conn, scope, generation, items_written, rebuild_job,
                                       obsolete_generations, cleanup_jobs):
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
        return False

    if scope == 'cards':
        # 换代与补偿任务一起提交；中断时两者一起回滚，旧代仍可查询。
        conn.execute("INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) "
                     "SELECT 'upsert_card',card_id,source_path,payload_json FROM index_card_build_changes "
                     "WHERE generation=?", (generation,))
        conn.execute('DELETE FROM index_card_build_changes WHERE generation=?', (generation,))

    set_search_content_format_version(conn, scope, SEARCH_CONTENT_FORMAT_VERSION, commit=False)
    if rebuild_job is not None:
        # 重启只恢复仍在执行的重建。完成凭据与活动代一起提交。
        finished = conn.execute(
            "UPDATE index_jobs SET status='done', finished_at=strftime('%s','now'), error_msg='' "
            "WHERE id=? AND job_type='rebuild_scope' AND status='running' AND error_msg=?",
            rebuild_job,
        )
        if finished.rowcount != 1:
            return False
    for obsolete in obsolete_generations:
        job = conn.execute(
            "INSERT INTO index_jobs(job_type,payload_json) VALUES ('cleanup_generation',?)",
            (json.dumps({'scope': scope, 'generation': obsolete}),),
        )
        cleanup_jobs.append((job.lastrowid, obsolete))
    return True


def cleanup_obsolete_generation(conn: sqlite3.Connection, scope: str, generation: int, *, pending_job_id=None):
    """清理重试必须在写事务中复核，防止删除活动或正在构建的代。"""
    if scope not in ('cards', 'worldinfo') or type(generation) is not int or generation <= 0:
        raise ValueError('invalid index cleanup target')
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if pending_job_id is not None and not conn.execute(
                "SELECT 1 FROM index_jobs WHERE id=? AND status='pending'", (pending_job_id,)).fetchone():
            return
        state = conn.execute('SELECT active_generation,building_generation FROM index_build_state WHERE scope=?',
                             (scope,)).fetchone()
        if state is not None and generation not in state:
            clear_generation_data(conn, scope, generation, commit=False)
        if pending_job_id is not None:
            conn.execute('DELETE FROM index_jobs WHERE id=?', (pending_job_id,))


def clear_generation_data(conn: sqlite3.Connection, scope: str, generation: int, *, commit=True):
    if scope == 'cards':
        from core.data.card_list_projection import clear
        clear(conn, generation)
        conn.execute('DELETE FROM index_card_build_changes WHERE generation=?', (generation,))
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
    if supports_fts5():
        conn.execute(
            'DELETE FROM index_search_full_v2 WHERE rowid IN (SELECT fts_rowid FROM index_full_rowids WHERE generation = ? AND entity_id LIKE ?)',
            (generation, entity_id_pattern),
        )

    conn.execute('DELETE FROM index_full_rowids WHERE generation = ? AND entity_id LIKE ?',
                 (generation, entity_id_pattern))

    for entity_id in entity_ids:
        conn.execute(
            'DELETE FROM index_entity_tags_v2 WHERE generation = ? AND entity_id = ?',
            (generation, entity_id),
        )
        conn.execute(
            'DELETE FROM index_search_fast_v2 WHERE generation = ? AND entity_id = ?',
            (generation, entity_id),
        )
        delete_full_search_rows(conn, generation, entity_id)

    conn.execute('DELETE FROM index_category_stats_v2 WHERE generation = ? AND scope = ?', (generation, stats_scope))
    conn.execute('DELETE FROM index_facet_stats_v2 WHERE generation = ? AND scope = ?', (generation, stats_scope))
    if commit:
        conn.commit()


SCAN_STATE_LAST_FULL_SCAN_AT = 'last_full_scan_at'
SCAN_STATE_CARD_ROOT = 'last_full_scan_card_root'
SCAN_STATE_CARD_ROOT_EPOCH = 'card_metadata_root_epoch'

# FTS 搜索内容列的格式版本。写入侧改变内容形态时必须 +1，否则老索引不会重建，
# 搜索会静默失效（例如中文子串在未切分的旧内容上永远命中 0 条）。
#   1 = 原文（历史格式，CJK 未切分）
#   2 = CJK 逐字切分 + 世界书条目正文
#   3 = index_search_fast_v2 由 fts5 改为普通表（迁移后必须重建索引才能回填内容）
SEARCH_CONTENT_FORMAT_VERSION = 3


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
    # 激活凭据不是可丢弃的扫描时间戳；SQLite 回滚时必须让激活方得知失败。
    _write_scan_state(conn, search_content_format_state_key(scope), str(int(version)))
    if commit:
        conn.commit()


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


def _write_scan_state(conn, key, value):
    conn.execute(
        '''
        INSERT INTO scan_runtime_state(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        ''',
        (str(key), str(value), time.time()),
    )


def set_scan_state(conn: sqlite3.Connection, key: str, value, *, commit: bool = True) -> None:
    """写入扫描器簿记状态。"""
    try:
        _write_scan_state(conn, key, value)
        if commit:
            conn.commit()
    except sqlite3.Error:
        pass

