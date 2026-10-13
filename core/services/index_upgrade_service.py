import logging
import os
import random
import sqlite3
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
)
from core.services.index_build_service import (
    build_cards_generation,
    build_worldinfo_generation,
    connect_index_db,
)
from core.utils.data import get_wi_meta
from core.utils.image import extract_card_info


logger = logging.getLogger(__name__)


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


def backfill_embedded_worldinfo_metadata(conn=None):
    owns_connection = conn is None
    if owns_connection:
        conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=60)

    try:
        cursor = conn.cursor()
        rows = cursor.execute('SELECT id FROM card_metadata WHERE wi_metadata_scanned = 0').fetchall()
        updates = []
        inspected_books = {}

        for (card_id,) in rows:
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
                ('backfill_embedded_worldinfo_metadata', scope),
            )
            inspected_books = backfill_embedded_worldinfo_metadata(conn)
            conn.execute(
                'UPDATE index_build_state SET phase = ? WHERE scope = ?',
                ('build_entities', scope),
            )
            items_written = build_worldinfo_generation(conn, generation, inspected_books=inspected_books)
            _ensure_worldinfo_projection_complete(conn, generation, inspected_books)
        else:
            items_written = build_cards_generation(conn, generation)

        conn.execute(
            'UPDATE index_build_state SET phase = ? WHERE scope = ?',
            ('activate_generation', scope),
        )
        # activate_generation 会在同一事务里记录搜索内容格式版本。
        activate_generation(conn, scope, generation, items_written=items_written)
        _print_and_log(f'{scope} 索引构建完成，已激活 generation={generation}')


def run_startup_upgrade_if_needed(index_auto_bootstrap: bool = True):
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
        return

    with connect_index_db(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            'SELECT scope, state, active_generation FROM index_build_state ORDER BY scope'
        ).fetchall()
        # 每个 scope 已建索引的搜索内容格式版本（0 表示没有记录，即历史格式）。
        built_formats = {
            str(row['scope']): get_search_content_format_version(conn, str(row['scope']))
            for row in rows
        }

    for row in rows:
        scope = str(row['scope'])
        if row['state'] == 'ready' and int(row['active_generation'] or 0) > 0:
            # 索引本身是就绪的，但内容格式可能已过时（例如本次升级引入了
            # CJK 切分）。此时必须重建，否则搜索会静默失效。
            if built_formats.get(scope, 0) >= SEARCH_CONTENT_FORMAT_VERSION:
                continue
            _print_and_log(
                f'{scope} 索引的搜索内容格式为 v{built_formats.get(scope, 0)}，'
                f'需要升级到 v{SEARCH_CONTENT_FORMAT_VERSION}，正在重建'
            )
            rebuild_scope_generation(scope, reason='search_content_format_upgrade')
            continue
        rebuild_scope_generation(scope, reason='bootstrap')
