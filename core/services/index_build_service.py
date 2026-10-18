import json
import logging
import os
import sqlite3

from core.config import BASE_DIR, CARDS_FOLDER, DEFAULT_DB_PATH, load_config
from core.data.index_runtime_store import get_active_generation
from core.data.ui_store import get_import_time, load_ui_data
from core.utils.format_validation import is_valid_world_info_data
from core.utils.image import extract_card_info
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


def _worldinfo_note_summary(ui_data: dict, source_type: str, *, file_path: str = '', card_id: str = '') -> str:
    if not isinstance(ui_data, dict):
        return ''
    notes = ui_data.get('_worldinfo_notes_v1') or {}
    if source_type == 'embedded':
        key = f'embedded::{card_id}'
    else:
        normalized_path = str(file_path).replace("\\", "/")
        key = f'{source_type}::{normalized_path}'
    note = notes.get(key) or {}
    return str(note.get('summary') or '') if isinstance(note, dict) else ''


def _embedded_summary(ui_data: dict, card_id: str) -> str:
    if not isinstance(ui_data, dict):
        return ''
    card_meta = ui_data.get(card_id) or {}
    if isinstance(card_meta, dict):
        summary = str(card_meta.get('summary') or '')
        if summary.strip():
            return summary
    return _worldinfo_note_summary(ui_data, 'embedded', card_id=card_id)


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
      无需分词，索引体积也最小。
    - ``full`` 表保存**逐字切分后的 CJK**（``split_cjk_for_index``）：``unicode61``
      不切分汉字，存原文会让中文子串永远命中 0 条；切分后查询侧用短语
      ``"血 族"`` 匹配相邻 token，得到真正的子串语义。``fulltext_extra``
      额外携带世界书条目正文。
    """
    conn.execute(
        'INSERT INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)',
        (generation, entity_id, content),
    )
    fulltext = f'{content} {fulltext_extra}' if fulltext_extra else content
    conn.execute(
        'INSERT INTO index_search_full_v2(generation, entity_id, content) VALUES (?, ?, ?)',
        (generation, entity_id, split_cjk_for_index(fulltext)),
    )


def _insert_worldinfo_search(conn, generation: int, entity_id: str, *parts, fulltext_extra=''):
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
    conn.execute(
        'DELETE FROM index_search_full_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )


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
            if os.path.commonpath([os.path.normcase(global_dir), os.path.normcase(normalized_path)]) == os.path.normcase(global_dir):
                result['kind'] = 'global'
                return result
        except ValueError:
            pass

    if resource_dir:
        try:
            common = os.path.commonpath([os.path.normcase(resource_dir), os.path.normcase(normalized_path)])
        except ValueError:
            common = ''
        if common == os.path.normcase(resource_dir):
            rel_path = normalized_path.replace('\\', '/').lower()
            if '/lorebooks/' in rel_path:
                result['kind'] = 'resource'

    return result


def resolve_resource_worldinfo_owner_card_ids(source_path: str) -> list[str]:
    cfg = load_config()
    _global_dir, resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    normalized_path = os.path.normpath(str(source_path or ''))
    if not resources_dir or not normalized_path:
        return []

    try:
        rel_path = os.path.relpath(normalized_path, resources_dir).replace('\\', '/')
    except ValueError:
        return []

    if rel_path.startswith('../') or rel_path == '..':
        return []

    parts = [part for part in rel_path.split('/') if part]
    if len(parts) < 3 or parts[1].lower() != 'lorebooks':
        return []

    resource_folder = parts[0]
    ui_data = load_ui_data()
    if not isinstance(ui_data, dict):
        return []

    owner_card_ids = []
    for card_id, meta in ui_data.items():
        if not isinstance(meta, dict) or str(meta.get('resource_folder') or '').strip() != resource_folder:
            continue
        owner_card_ids.append(str(card_id))

    return sorted(set(owner_card_ids))


def _rebuild_worldinfo_category_stats_v2(conn, generation: int, global_dir: str):
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
    if global_dir and os.path.isdir(global_dir):
        for root, _dirs, _files in os.walk(global_dir):
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
    conn.execute(
        'DELETE FROM index_search_full_v2 WHERE generation = ? AND entity_id = ?',
        (generation, entity_id),
    )


def _delete_worldinfo_owner_rows(conn, generation: int, card_id: str):
    owner_entity_id = f'card::{card_id}'
    _delete_worldinfo_entity_rows(conn, generation, f'world::embedded::{card_id}')

    existing_rows = conn.execute(
        'SELECT entity_id FROM index_entities_v2 WHERE generation = ? AND entity_type = ? AND owner_entity_id = ?',
        (generation, 'world_resource', owner_entity_id),
    ).fetchall()
    for existing_row in existing_rows:
        _delete_worldinfo_entity_rows(conn, generation, str(existing_row['entity_id'] or ''))


def apply_worldinfo_path_increment(conn, source_path: str) -> bool:
    generation = get_active_generation(conn, 'worldinfo')
    if generation <= 0:
        raise RuntimeError('worldinfo active generation missing')

    cfg = load_config()
    ui_data = load_ui_data()
    normalized_path = os.path.normpath(str(source_path or ''))
    normalized_global_dir, _resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    if not normalized_path or not normalized_global_dir:
        raise RuntimeError('worldinfo global directory unavailable')

    try:
        rel_path = os.path.relpath(normalized_path, normalized_global_dir).replace('\\', '/')
    except ValueError as exc:
        raise RuntimeError(f'worldinfo path outside global directory: {source_path}') from exc

    if rel_path.startswith('..'):
        raise RuntimeError(f'worldinfo path outside global directory: {source_path}')

    entity_id = f'world::global::{rel_path}'
    _delete_worldinfo_entity_rows(conn, generation, entity_id)

    if os.path.isfile(normalized_path):
        try:
            with open(normalized_path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            logger.warning('Skipping invalid worldinfo file during incremental update: %s', normalized_path)
            _rebuild_worldinfo_category_stats_v2(conn, generation, normalized_global_dir)
            conn.commit()
            return True
        if not is_valid_world_info_data(data):
            _rebuild_worldinfo_category_stats_v2(conn, generation, normalized_global_dir)
            conn.commit()
            return True
        filename = os.path.basename(normalized_path)
        display_category = rel_path.rsplit('/', 1)[0] if '/' in rel_path else ''
        name = (data.get('name') or '').strip() or filename
        summary = _worldinfo_note_summary(ui_data, 'global', file_path=normalized_path)
        mtime = float(os.path.getmtime(normalized_path))
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
                'world_global',
                normalized_path,
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
                build_file_source_revision(normalized_path),
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

    _rebuild_worldinfo_category_stats_v2(conn, generation, normalized_global_dir)
    conn.commit()
    return True


def apply_worldinfo_embedded_increment(conn, card_id: str, source_path: str = '') -> bool:
    generation = get_active_generation(conn, 'worldinfo')
    if generation <= 0:
        raise RuntimeError('worldinfo active generation missing')

    row = conn.execute(
        'SELECT id, char_name, category, character_book_name, last_modified, has_character_book FROM card_metadata WHERE id = ?',
        (card_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f'embedded owner card missing: {card_id}')

    card_path = str(source_path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)))
    entity_id = f'world::embedded::{card_id}'
    _delete_worldinfo_entity_rows(conn, generation, entity_id)

    if int(row['has_character_book'] or 0):
        info = extract_card_info(card_path)
        data = info.get('data', {}) if isinstance(info, dict) and 'data' in info else info
        book = data.get('character_book') if isinstance(data, dict) else None
        if isinstance(book, dict):
            ui_data = load_ui_data()
            name = str(book.get('name') or row['character_book_name'] or f"{row['char_name']}'s WI").strip()
            category = str(row['category'] or '')
            summary = _embedded_summary(ui_data, card_id)
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
                    f'card::{card_id}',
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

    cfg = load_config()
    global_dir, _resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir)
    conn.commit()
    return True


def apply_worldinfo_owner_increment(conn, card_id: str, source_path: str = '', *, remove_owner_ids: list[str] | None = None) -> bool:
    generation = get_active_generation(conn, 'worldinfo')
    if generation <= 0:
        raise RuntimeError('worldinfo active generation missing')

    cleanup_only = False
    for stale_card_id in remove_owner_ids or []:
        stale_value = str(stale_card_id or '').strip()
        if not stale_value:
            continue
        _delete_worldinfo_owner_rows(conn, generation, stale_value)
        cleanup_only = cleanup_only or stale_value == str(card_id or '').strip()

    row = conn.execute(
        'SELECT id, char_name, category, last_modified, has_character_book, character_book_name FROM card_metadata WHERE id = ?',
        (card_id,),
    ).fetchone()
    if row is None:
        if cleanup_only:
            cfg = load_config()
            global_dir, _resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
            _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir)
            conn.commit()
            return True
        raise RuntimeError(f'worldinfo owner card missing: {card_id}')

    _delete_worldinfo_owner_rows(conn, generation, card_id)
    apply_worldinfo_embedded_increment(conn, card_id, source_path)

    cfg = load_config()
    ui_data = load_ui_data()
    global_dir, resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    owner_entity_id = f'card::{card_id}'

    resource_folder = str((_resolve_card_ui_meta(ui_data, card_id).get('resource_folder') or '')).strip()
    resource_item_categories = ((ui_data.get('_resource_item_categories_v1') or {}).get('worldinfo') or {})
    if resource_folder:
        lore_dir = os.path.join(resources_dir, resource_folder, 'lorebooks')
        if os.path.isdir(lore_dir):
            for filename in os.listdir(lore_dir):
                if not filename.lower().endswith('.json'):
                    continue
                full_path = os.path.join(lore_dir, filename)
                try:
                    with open(full_path, 'r', encoding='utf-8') as handle:
                        data = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    logger.warning('Skipping invalid resource worldinfo file during owner increment: %s', full_path, exc_info=True)
                    continue
                if not is_valid_world_info_data(data):
                    continue

                path_key = str(full_path).replace('\\', '/').lower()
                override = (resource_item_categories.get(path_key) or {}).get('category', '')
                display_category = override or str(row['category'] or '')
                mode = 'override' if override else 'inherited'
                name = (data.get('name') or '').strip() or filename
                summary = _worldinfo_note_summary(ui_data, 'resource', file_path=full_path)
                mtime = float(os.path.getmtime(full_path))
                entity_id = f'world::resource::{card_id}::{filename}'
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

    _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir)
    conn.commit()
    return True


def connect_index_db(db_path=None):
    conn = sqlite3.connect(db_path or DEFAULT_DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn


def refresh_worldinfo_category_stats(conn, cfg: dict | None = None) -> bool:
    generation = get_active_generation(conn, 'worldinfo')
    if generation <= 0:
        raise RuntimeError('worldinfo active generation missing')

    global_dir, _resources_dir = _resolve_worldinfo_runtime_dirs(cfg)
    _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir)
    conn.commit()
    return True


def apply_card_increment(conn, card_id: str, source_path: str = '', *, remove_entity_ids: list[str] | None = None) -> bool:
    generation = get_active_generation(conn, 'cards')
    if generation <= 0:
        raise RuntimeError('cards active generation missing')

    remove_entity_ids = remove_entity_ids or []
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
        conn.commit()
        return True

    ui_data = load_ui_data()
    tags = json.loads(row['tags'] or '[]') if row['tags'] else []
    summary = str((ui_data.get(card_id) or {}).get('summary', ''))
    resolved_source_path = str(source_path or os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep)))
    filename = str(card_id).split('/')[-1]
    last_modified = float(row['last_modified'] or 0)
    import_time = get_import_time(ui_data, card_id, last_modified)
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
            build_file_source_revision(resolved_source_path),
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
    conn.commit()
    return True


def build_cards_generation(conn, generation: int, progress_cb=None):
    ui_data = load_ui_data()
    rows = conn.execute(
        'SELECT id, char_name, tags, category, last_modified, token_count, is_favorite FROM card_metadata'
    ).fetchall()
    total = len(rows)
    _report_progress(progress_cb, 0, total)

    for index, row in enumerate(rows, start=1):
        entity_id = f"card::{row['id']}"
        tags = json.loads(row['tags'] or '[]') if row['tags'] else []
        summary = str((ui_data.get(row['id']) or {}).get('summary', ''))
        source_path = os.path.join(CARDS_FOLDER, row['id'].replace('/', os.sep))
        last_modified = float(row['last_modified'] or 0)
        import_time = get_import_time(ui_data, row['id'], last_modified)
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


def build_worldinfo_generation(conn, generation: int, inspected_books=None, progress_cb=None):
    cfg = load_config()
    ui_data = load_ui_data()
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
    if global_dir and os.path.isdir(global_dir):
        for root, _dirs, files in os.walk(global_dir):
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
        except (OSError, json.JSONDecodeError):
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
        summary = _worldinfo_note_summary(ui_data, 'global', file_path=full_path)
        mtime = float(os.path.getmtime(full_path))
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

    resource_item_categories = ((ui_data.get('_resource_item_categories_v1') or {}).get('worldinfo') or {})
    for row in rows:
        card_id = str(row['id'])
        card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        owner_entity_id = f'card::{card_id}'
        resource_folder = str((_resolve_card_ui_meta(ui_data, card_id).get('resource_folder') or '')).strip()
        if resource_folder:
            lore_dir = os.path.join(resources_dir, resource_folder, 'lorebooks')
            if os.path.isdir(lore_dir):
                for filename in os.listdir(lore_dir):
                    if not filename.lower().endswith('.json'):
                        continue
                    full_path = os.path.join(lore_dir, filename)
                    try:
                        with open(full_path, 'r', encoding='utf-8') as handle:
                            data = json.load(handle)
                    except (OSError, json.JSONDecodeError):
                        logger.warning('Skipping invalid resource worldinfo file during v2 rebuild: %s', full_path, exc_info=True)
                        continue
                    if not is_valid_world_info_data(data):
                        continue

                    path_key = str(full_path).replace('\\', '/').lower()
                    override = (resource_item_categories.get(path_key) or {}).get('category', '')
                    display_category = override or str(row['category'] or '')
                    mode = 'override' if override else 'inherited'
                    name = (data.get('name') or '').strip() or filename
                    summary = _worldinfo_note_summary(ui_data, 'resource', file_path=full_path)
                    mtime = float(os.path.getmtime(full_path))
                    entity_id = f'world::resource::{card_id}::{filename}'
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
        summary = _embedded_summary(ui_data, card_id)

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

    _rebuild_worldinfo_category_stats_v2(conn, generation, global_dir)
    conn.commit()
    _report_progress(progress_cb, max(done, total), max(total, done))
    return items_written
