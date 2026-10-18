import logging
import os
import random
import sqlite3
import threading
import time

from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.index_runtime_store import (
    SEARCH_CONTENT_FORMAT_VERSION,
    activate_generation,
    allocate_build_generation,
    clear_generation_data,
    ensure_index_runtime_schema,
    get_search_content_format_version,
    update_build_state,
    update_build_progress,
)
from core.services.index_build_service import (
    build_cards_generation,
    build_worldinfo_generation,
    connect_index_db,
)
from core.utils.data import get_wi_meta
from core.utils.image import extract_card_info


logger = logging.getLogger(__name__)


# 升级重建阶段名。前端据此显示「正在扫描世界书 / 正在建索引 / 正在激活」。
PHASE_BACKFILL = 'backfill_embedded_worldinfo_metadata'
PHASE_BUILD = 'build_entities'
PHASE_ACTIVATE = 'activate_generation'

# 每处理多少张卡刷新一次「已扫描世界书元数据」进度。
BACKFILL_PROGRESS_STEP = 25
BACKFILL_COMMIT_BATCH_SIZE = 100


LEGACY_INDEX_TABLE_POLICY = {
    'decision': 'stop_creating',
    'reason': 'new databases now use runtime v2 tables only; legacy tables remain only for pre-existing database compatibility',
    'runtime_callers': (),
}


def _print_and_log(message: str):
    print(message)
    logger.info(message)


def get_legacy_index_table_policy() -> dict:
    """Return the current compatibility decision for pre-v2 index tables."""
    return dict(LEGACY_INDEX_TABLE_POLICY)


def _ensure_worldinfo_projection_complete(conn, generation: int, inspected_books):
    if not inspected_books:
        return

    expected_ids = sorted(str(card_id) for card_id in inspected_books)
    actual_ids = {
        row[0]
        for row in conn.execute(
            '''
            SELECT SUBSTR(owner_entity_id, 7)
            FROM index_entities_v2
            WHERE generation = ? AND entity_type = 'world_embedded'
            ''',
            (generation,),
        ).fetchall()
    }
    missing_ids = [card_id for card_id in expected_ids if card_id not in actual_ids]
    if missing_ids:
        raise RuntimeError(f"worldinfo projection incomplete for cards: {', '.join(missing_ids)}")


def ensure_owner_token():
    if ctx.index_owner_token:
        return ctx.index_owner_token

    ctx.index_owner_token = f'{os.getpid()}-{int(time.time())}-{random.randint(1000, 9999)}'
    return ctx.index_owner_token


def backfill_embedded_worldinfo_metadata(conn=None, progress_cb=None):
    owns_connection = conn is None
    if owns_connection:
        conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=60)

    try:
        cursor = conn.cursor()
        rows = cursor.execute('SELECT id FROM card_metadata WHERE wi_metadata_scanned = 0').fetchall()
        total = len(rows)
        updates = []
        inspected_books = {}

        for done, (card_id,) in enumerate(rows, start=1):
            full_path = os.path.join(CARDS_FOLDER, str(card_id).replace('/', os.sep))
            if not os.path.exists(full_path):
                continue

            try:
                info = extract_card_info(full_path)
            except Exception:
                logger.warning('Failed to inspect embedded worldinfo metadata: %s', full_path, exc_info=True)
                continue

            if not info:
                continue

            data = info.get('data', {}) if isinstance(info, dict) and 'data' in info else info
            has_wi, wi_name = get_wi_meta(data)
            if has_wi and isinstance(data, dict):
                book = data.get('character_book')
                if isinstance(book, dict):
                    inspected_books[str(card_id)] = book
            updates.append((1 if has_wi else 0, wi_name if has_wi else '', 1, card_id))

            # 这一步要逐张开卡文件（大卡几十毫秒），是全流程最慢的一段：
            # 必须持续上报进度，否则前端只能看到「卡住」。
            if done % BACKFILL_PROGRESS_STEP == 0 or done == total:
                if progress_cb:
                    progress_cb(done, total)
            if len(updates) >= BACKFILL_COMMIT_BATCH_SIZE:
                cursor.executemany(
                    'UPDATE card_metadata SET has_character_book = ?, character_book_name = ?, wi_metadata_scanned = ? WHERE id = ?',
                    updates,
                )
                conn.commit()
                updates = []

        if updates:
            cursor.executemany(
                'UPDATE card_metadata SET has_character_book = ?, character_book_name = ?, wi_metadata_scanned = ? WHERE id = ?',
                updates,
            )
        if owns_connection:
            conn.commit()
        return inspected_books
    finally:
        if owns_connection:
            conn.close()


def recover_scope_build(scope: str):
    with connect_index_db(DEFAULT_DB_PATH) as conn:
        row = conn.execute(
            'SELECT building_generation FROM index_build_state WHERE scope = ?',
            (scope,),
        ).fetchone()
        generation = int((row or [0])[0] or 0)
        if generation > 0:
            _print_and_log(f'检测到上次 {scope} 索引构建中断，正在清理 generation={generation}')
            clear_generation_data(conn, scope, generation)

        update_build_state(
            conn,
            scope,
            building_generation=0,
            state='failed',
            phase='recovery',
            last_error='interrupted previous run',
            owner_token=ensure_owner_token(),
        )


def _publish_build_progress(scope: str, phase: str | None = None, done: int | None = None, total: int | None = None):
    """把构建进度写进内存索引状态，供前端 `/api/index/status` 轮询展示。

    持久化的进度列由 ``update_build_progress`` 在分批提交点写入；这里只负责
    「当前进程立刻可见」，让前端不必等下一次提交才看到数字变化。
    """
    try:
        with ctx.index_lock:
            block = ctx.index_state.get(scope)
            if isinstance(block, dict):
                if phase is not None:
                    block['phase'] = str(phase)
                if done is not None:
                    block['progress_done'] = int(done)
                if total is not None:
                    block['progress_total'] = int(total)
            ctx.index_state['state'] = 'building'
            ctx.index_state['scope'] = scope
            if done is not None and total:
                percent = max(0, min(100, int(int(done) * 100 / int(total))))
                ctx.index_state['progress'] = percent
                ctx.index_state['message'] = f'{phase or ""} {int(done)}/{int(total)}'.strip()
    except Exception:
        logger.debug('发布索引构建进度失败: %s', scope, exc_info=True)


def _make_progress_callback(conn, scope: str, phase: str):
    """构造 (done, total) 回调：同时更新内存状态和持久化进度列。"""

    def _callback(done, total):
        _publish_build_progress(scope, phase=phase, done=done, total=total)
        update_build_progress(conn, scope, phase=phase, done=done, total=total, commit=False)

    return _callback


def rebuild_scope_generation(scope: str, reason: str = 'bootstrap'):
    with connect_index_db(DEFAULT_DB_PATH) as conn:
        generation = allocate_build_generation(conn, scope)
        update_build_state(
            conn,
            scope,
            state='running',
            phase='build_entities',
            build_reason=reason,
            owner_token=ensure_owner_token(),
        )

        if scope == 'worldinfo':
            conn.execute(
                'UPDATE index_build_state SET phase = ? WHERE scope = ?',
                (PHASE_BACKFILL, scope),
            )
            conn.commit()
            _publish_build_progress(scope, phase=PHASE_BACKFILL, done=0, total=0)
            inspected_books = backfill_embedded_worldinfo_metadata(
                conn,
                progress_cb=_make_progress_callback(conn, scope, PHASE_BACKFILL),
            )
            # 「已扫描过世界书元数据」是独立于索引构建的事实：单独提交。
            # 否则一次构建失败就要在下次启动重新逐张读全部卡片（大库可达数分钟），
            # 而这正是启动慢的主因。索引行本身仍整体回滚，由 generation 机制保证。
            conn.commit()
            conn.execute(
                'UPDATE index_build_state SET phase = ? WHERE scope = ?',
                (PHASE_BUILD, scope),
            )
            conn.commit()
            _publish_build_progress(scope, phase=PHASE_BUILD, done=0, total=0)
            items_written = build_worldinfo_generation(
                conn,
                generation,
                inspected_books=inspected_books,
                progress_cb=_make_progress_callback(conn, scope, PHASE_BUILD),
            )
            _ensure_worldinfo_projection_complete(conn, generation, inspected_books)
        else:
            items_written = build_cards_generation(
                conn,
                generation,
                progress_cb=_make_progress_callback(conn, scope, PHASE_BUILD),
            )

        conn.execute(
            'UPDATE index_build_state SET phase = ? WHERE scope = ?',
            (PHASE_ACTIVATE, scope),
        )
        conn.commit()
        _publish_build_progress(scope, phase=PHASE_ACTIVATE)
        # activate_generation 会在同一事务里记录搜索内容格式版本。
        activate_generation(conn, scope, generation, items_written=items_written)
        _print_and_log(f'{scope} 索引构建完成，已激活 generation={generation}')


def plan_startup_upgrade(index_auto_bootstrap: bool = True) -> list[dict]:
    """启动时的**轻量**升级计划：只做恢复与判定，不做任何重建。

    重建要逐张读卡片文件（旧库世界书多时可达数分钟），放在启动路径上会让
    「正在初始化资源库」一直卡住。因此这里只做三件很快的事：

    1. 建/补运行时表结构；
    2. 清理上次中断留下的半成品 generation；
    3. 判断哪些 scope 需要重建（首次引导 / 搜索内容格式过时）。

    返回 ``[{'scope': 'worldinfo', 'reason': 'search_content_format_upgrade'}]``，
    由调用方决定同步跑（`run_startup_upgrade_if_needed`）还是丢到后台线程
    （`start_background_index_upgrade`）。
    """
    ensure_owner_token()

    with connect_index_db(DEFAULT_DB_PATH) as conn:
        ensure_index_runtime_schema(conn)
        rows = conn.execute(
            'SELECT scope, state, owner_token, active_generation FROM index_build_state ORDER BY scope'
        ).fetchall()

    for row in rows:
        scope = str(row['scope'])
        if row['state'] == 'running' and str(row['owner_token'] or '') != ctx.index_owner_token:
            recover_scope_build(scope)

    if not index_auto_bootstrap:
        return []

    with connect_index_db(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            'SELECT scope, state, active_generation FROM index_build_state ORDER BY scope'
        ).fetchall()
        # 每个 scope 已建索引的搜索内容格式版本（0 表示没有记录，即历史格式）。
        built_formats = {
            str(row['scope']): get_search_content_format_version(conn, str(row['scope']))
            for row in rows
        }

    plan = []
    for row in rows:
        scope = str(row['scope'])
        if row['state'] == 'ready' and int(row['active_generation'] or 0) > 0:
            # 索引本身是就绪的，但内容格式可能已过时（例如本次升级引入了
            # CJK 切分）。此时必须重建，否则搜索会静默失效。
            if built_formats.get(scope, 0) >= SEARCH_CONTENT_FORMAT_VERSION:
                continue
            _print_and_log(
                f'{scope} 索引的搜索内容格式为 v{built_formats.get(scope, 0)}，'
                f'需要升级到 v{SEARCH_CONTENT_FORMAT_VERSION}，将在后台重建'
            )
            plan.append({'scope': scope, 'reason': 'search_content_format_upgrade'})
            continue
        plan.append({'scope': scope, 'reason': 'bootstrap'})
    return plan


def run_startup_upgrade_if_needed(index_auto_bootstrap: bool = True):
    """同步执行升级计划（会阻塞调用线程，仅供测试与手动维护路径使用）。

    应用启动走的是 ``start_background_index_upgrade``：先在后台重建，前端
    用 ``/api/index/status`` 看进度，不再卡住启动流程。
    """
    for item in plan_startup_upgrade(index_auto_bootstrap=index_auto_bootstrap):
        rebuild_scope_generation(item['scope'], reason=item['reason'])


def _refresh_after_upgrade():
    """重建完成后刷新内存缓存与世界书列表缓存，让新索引立刻生效。"""
    try:
        from core.services.cache_service import invalidate_wi_list_cache

        invalidate_wi_list_cache()
    except Exception:
        logger.debug('刷新世界书列表缓存失败', exc_info=True)

    try:
        if ctx.cache:
            ctx.cache.reload_from_db()
    except Exception:
        logger.warning('索引升级完成后重载缓存失败', exc_info=True)


def _settle_index_state():
    """重建结束后把内存里的临时构建状态收尾，避免状态条一直停在 building。"""
    try:
        with ctx.index_lock:
            ctx.index_state['state'] = 'ready'
            ctx.index_state['message'] = ''
            ctx.index_state['progress'] = 100
    except Exception:
        logger.debug('收尾索引状态失败', exc_info=True)


def _background_upgrade_worker(plan: list[dict]):
    try:
        # 串行化靠**启动顺序**保证，不靠锁：init_services 先调用
        # start_background_index_upgrade（置位 index_upgrade_active）再启动索引
        # 作业 worker，所以 worker 第一次观察就会看到「升级中」并让路。
        for item in plan:
            scope = item['scope']
            reason = item['reason']
            _print_and_log(f'开始后台重建 {scope} 索引（原因: {reason}）')
            rebuild_scope_generation(scope, reason=reason)
        _refresh_after_upgrade()
        _settle_index_state()
        _print_and_log('后台索引升级完成')
    except Exception as exc:
        logger.error('后台索引升级失败: %s', exc, exc_info=True)
        with ctx.index_lock:
            ctx.index_state['state'] = 'error'
            ctx.index_state['message'] = f'索引升级失败: {exc}'
        for item in plan:
            try:
                with connect_index_db(DEFAULT_DB_PATH) as conn:
                    update_build_state(
                        conn,
                        item['scope'],
                        state='failed',
                        phase='background_upgrade',
                        last_error=str(exc)[:500],
                    )
            except Exception:
                logger.debug('记录后台升级失败状态时出错', exc_info=True)
    finally:
        ctx.index_upgrade_active = False
        ctx.index_upgrade_done.set()
        # 唤醒索引作业线程，让它接着处理积压的增量作业。
        ctx.index_wakeup.set()


def start_background_index_upgrade(plan: list[dict] | None = None):
    """把升级重建丢到后台 daemon 线程，启动流程不再等它。

    ``ctx.index_upgrade_active`` 为真期间，索引作业线程与启动全量扫描都会让路，
    避免与重建并发写同一批索引行。
    """
    plan = list(plan or [])
    if not plan:
        ctx.index_upgrade_done.set()
        return None

    # 先置位再起线程：否则「起线程 → 立刻被扫描器/作业线程观察」的窗口里
    # 它们会看到 False 而继续跑。
    ctx.index_upgrade_active = True
    ctx.index_upgrade_done.clear()
    thread = threading.Thread(
        target=_background_upgrade_worker,
        args=(plan,),
        name='index-startup-upgrade',
        daemon=True,
    )
    thread.start()
    return thread
