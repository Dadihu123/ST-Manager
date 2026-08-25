import os
import time
import threading
import sqlite3
import json
import logging

# === 基础设施 ===
from core.config import BASE_DIR, CARDS_FOLDER, DEFAULT_DB_PATH, current_config, load_config
from core.context import ctx
from core.data.ui_store import load_ui_data, save_ui_data

# === 业务逻辑引用 ===
from core.services.card_binding_service import rename_card_ui_references
from core.services.cache_service import schedule_reload
from core.services.index_build_service import classify_worldinfo_path, resolve_resource_worldinfo_owner_card_ids
from core.services.index_job_worker import enqueue_index_job
from core.utils.card_identity import new_card_uid, normalize_card_uid

# === 工具函数 ===
from core.utils.filesystem import is_card_file
from core.utils.image import extract_card_info
from core.utils.hash import get_file_hash_and_size
from core.utils.text import calculate_token_count
from core.utils.data import get_wi_meta, sanitize_for_utf8

logger = logging.getLogger(__name__)


WRITE_LIKE_EVENT_TYPES = {'created', 'modified', 'deleted', 'moved'}
FULL_SCAN_TASK = 'FULL_SCAN'
CARD_UPSERT_TASK = 'CARD_UPSERT'
CARD_MOVE_TASK = 'CARD_MOVE'
CARD_DELETE_TASK = 'CARD_DELETE'


def _normalize_watch_path(path):
    return os.path.normcase(os.path.abspath(str(path or '')))


def _resolve_runtime_dir(raw_path, default):
    value = str(raw_path or default or '').strip()
    if not value:
        return ''
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(BASE_DIR, value))


def _is_global_worldinfo_watch_path(path):
    return classify_worldinfo_path(path).get('kind') == 'global'


def _is_resource_worldinfo_watch_path(path):
    return classify_worldinfo_path(path).get('kind') == 'resource'


def _is_worldinfo_watch_path(path):
    return _is_global_worldinfo_watch_path(path) or _is_resource_worldinfo_watch_path(path)


def _resolve_card_rel_path(path):
    raw_path = str(path or '').strip()
    if not raw_path or not is_card_file(raw_path):
        return ''

    cards_root = os.path.abspath(os.fspath(CARDS_FOLDER))
    abs_path = os.path.abspath(raw_path)
    try:
        rel_path = os.path.relpath(abs_path, cards_root).replace('\\', '/')
    except ValueError:
        return ''

    if rel_path.startswith('../') or rel_path == '..':
        return ''
    return rel_path.strip('/')


def _build_card_watch_task(event):
    event_type = str(getattr(event, 'event_type', '') or '').lower()
    src_path = str(getattr(event, 'src_path', '') or '')
    dest_path = str(getattr(event, 'dest_path', '') or '')
    src_card_id = _resolve_card_rel_path(src_path)
    dest_card_id = _resolve_card_rel_path(dest_path)

    if event_type == 'moved':
        if src_card_id and dest_card_id:
            return {'type': CARD_MOVE_TASK, 'src_path': src_path, 'dest_path': dest_path}
        if dest_card_id:
            return {'type': CARD_UPSERT_TASK, 'path': dest_path}
        if src_card_id:
            return {'type': CARD_DELETE_TASK, 'path': src_path}
        return None

    if event_type == 'deleted' and src_card_id:
        return {'type': CARD_DELETE_TASK, 'path': src_path}

    if event_type in {'created', 'modified'} and src_card_id:
        return {'type': CARD_UPSERT_TASK, 'path': src_path}

    return None


def _enqueue_full_scan_fallback(reason='fs_event_fallback'):
    logger.warning('Falling back to full scan: %s', reason)
    ctx.scan_queue.put({'type': FULL_SCAN_TASK, 'reason': reason})


def _normalize_card_tags(raw_tags):
    if isinstance(raw_tags, str):
        raw_tags = [tag.strip() for tag in raw_tags.split(',') if tag.strip()]
    elif raw_tags is None:
        raw_tags = []

    return list(dict.fromkeys([str(tag).strip() for tag in raw_tags if str(tag).strip()]))


def _find_full_scan_rename_candidate(db_files_map, fs_found_files, full_path, file_size):
    """Find a unique missing DB row with the same content hash and size."""
    try:
        file_hash, actual_size = get_file_hash_and_size(full_path)
    except Exception:
        return None
    if not file_hash or actual_size != file_size:
        return None

    candidates = []
    for old_id, info in db_files_map.items():
        if old_id in fs_found_files or info.get('size') != file_size:
            continue
        if info.get('hash') and info.get('hash') == file_hash:
            candidates.append((old_id, info))
    return candidates[0] if len(candidates) == 1 else None


def _upsert_card_metadata_row(conn, card_id, full_path, *, fallback_favorite=0, card_uid=None):
    try:
        st = os.stat(full_path)
    except OSError:
        return False

    info = extract_card_info(full_path)
    if not info:
        return False

    data_block = info.get('data', {}) if 'data' in info else info
    tags = _normalize_card_tags(data_block.get('tags', []))
    char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(full_path))[0]
    category = card_id.rsplit('/', 1)[0] if '/' in card_id else ''

    calc_data = data_block.copy()
    if 'name' not in calc_data:
        calc_data['name'] = char_name
    token_count = calculate_token_count(calc_data)
    has_wi, wi_name = get_wi_meta(data_block)

    if not card_uid:
        try:
            row = conn.execute(
                'SELECT card_uid FROM card_metadata WHERE id = ?',
                (card_id,),
            ).fetchone()
            card_uid = row[0] if row else ''
        except sqlite3.OperationalError as exc:
            if 'no such column' not in str(exc).lower() and 'no column named' not in str(exc).lower():
                raise
            card_uid = ''
    card_uid = normalize_card_uid(card_uid) or new_card_uid()

    values = (
        card_id,
        char_name,
        data_block.get('description', ''),
        data_block.get('first_mes', ''),
        data_block.get('mes_example', ''),
        json.dumps(tags),
        category,
        data_block.get('creator', ''),
        data_block.get('character_version', ''),
        st.st_mtime,
        '',
        st.st_size,
        token_count,
        has_wi,
        wi_name,
        int(fallback_favorite or 0),
        card_uid,
    )
    try:
        conn.execute(
            '''
                INSERT OR REPLACE INTO card_metadata
                (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite, card_uid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            values,
        )
    except sqlite3.OperationalError as exc:
        if 'no such column' not in str(exc).lower() and 'no column named' not in str(exc).lower():
            raise
        conn.execute(
            '''
                INSERT OR REPLACE INTO card_metadata
                (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            values[:-1],
        )
    conn.commit()
    return True


def _enqueue_card_reconcile_jobs(card_id, full_path, *, remove_entity_ids=None, remove_owner_ids=None):
    cleanup_ids = [str(value).strip() for value in (remove_entity_ids or []) if str(value).strip()]
    if cleanup_ids:
        enqueue_index_job(
            'upsert_card',
            entity_id=card_id,
            source_path=full_path,
            payload={'remove_entity_ids': cleanup_ids},
        )
    else:
        enqueue_index_job('upsert_card', entity_id=card_id, source_path=full_path)

    stale_owner_ids = [str(value).strip() for value in (remove_owner_ids or []) if str(value).strip()]
    if stale_owner_ids:
        enqueue_index_job(
            'upsert_world_owner',
            entity_id=card_id,
            source_path=full_path,
            payload={'remove_owner_ids': stale_owner_ids},
        )
    else:
        enqueue_index_job('upsert_world_owner', entity_id=card_id, source_path=full_path)


def _process_card_upsert_task(full_path):
    card_id = _resolve_card_rel_path(full_path)
    if not card_id:
        return False

    if not os.path.isfile(full_path):
        return _process_card_delete_task(full_path)

    with sqlite3.connect(DEFAULT_DB_PATH, timeout=60) as conn:
        try:
            conn.execute('PRAGMA journal_mode=WAL;')
        except Exception:
            pass

        row = conn.execute('SELECT is_favorite FROM card_metadata WHERE id = ?', (card_id,)).fetchone()
        favorite = int(row[0] or 0) if row else 0
        if not _upsert_card_metadata_row(conn, card_id, full_path, fallback_favorite=favorite):
            return False

    _enqueue_card_reconcile_jobs(card_id, full_path)
    schedule_reload(reason='watchdog_card_upsert')
    return True


def _process_card_move_task(old_card_id, new_full_path):
    new_card_id = _resolve_card_rel_path(new_full_path)
    if not old_card_id or not new_card_id:
        return False

    if not os.path.isfile(new_full_path):
        return False

    with sqlite3.connect(DEFAULT_DB_PATH, timeout=60) as conn:
        try:
            conn.execute('PRAGMA journal_mode=WAL;')
        except Exception:
            pass

        try:
            row = conn.execute(
                'SELECT is_favorite, card_uid FROM card_metadata WHERE id = ?',
                (old_card_id,),
            ).fetchone()
            stable_uid = row[1] if row else ''
        except sqlite3.OperationalError as exc:
            if 'no such column' not in str(exc).lower() and 'no column named' not in str(exc).lower():
                raise
            row = conn.execute(
                'SELECT is_favorite FROM card_metadata WHERE id = ?',
                (old_card_id,),
            ).fetchone()
            stable_uid = ''
        favorite = int(row[0] or 0) if row else 0
        conn.execute('DELETE FROM card_metadata WHERE id = ?', (old_card_id,))
        conn.commit()
        if not _upsert_card_metadata_row(
            conn,
            new_card_id,
            new_full_path,
            fallback_favorite=favorite,
            card_uid=stable_uid,
        ):
            return False

    try:
        ui_data = load_ui_data()
        if rename_card_ui_references(ui_data, old_card_id, new_card_id):
            if not save_ui_data(ui_data):
                logger.warning(
                    '文件监控移动卡片后保存 UI 绑定失败: %s -> %s',
                    old_card_id,
                    new_card_id,
                )
    except Exception:
        logger.exception(
            '文件监控移动卡片后迁移 UI 绑定失败: %s -> %s',
            old_card_id,
            new_card_id,
        )

    _enqueue_card_reconcile_jobs(
        new_card_id,
        new_full_path,
        remove_entity_ids=[old_card_id],
        remove_owner_ids=[old_card_id],
    )
    schedule_reload(reason='watchdog_card_move')
    return True


def _process_card_delete_task(full_path):
    card_id = _resolve_card_rel_path(full_path)
    if not card_id:
        return False

    with sqlite3.connect(DEFAULT_DB_PATH, timeout=60) as conn:
        try:
            conn.execute('PRAGMA journal_mode=WAL;')
        except Exception:
            pass
        conn.execute('DELETE FROM card_metadata WHERE id = ?', (card_id,))
        conn.commit()

    _enqueue_card_reconcile_jobs(
        card_id,
        full_path,
        remove_entity_ids=[card_id],
        remove_owner_ids=[card_id],
    )
    schedule_reload(reason='watchdog_card_delete')
    return True


def _process_scan_task(task):
    task_type = FULL_SCAN_TASK
    if isinstance(task, dict):
        task_type = str(task.get('type') or FULL_SCAN_TASK)

    if task_type == FULL_SCAN_TASK:
        _perform_scan_logic()
        return True

    if task_type == CARD_UPSERT_TASK:
        if _process_card_upsert_task(task.get('path')):
            return True
        _enqueue_full_scan_fallback(reason=f'{CARD_UPSERT_TASK.lower()}_failed')
        return False

    if task_type == CARD_MOVE_TASK:
        old_card_id = _resolve_card_rel_path(task.get('src_path'))
        if _process_card_move_task(old_card_id, task.get('dest_path')):
            return True
        _enqueue_full_scan_fallback(reason=f'{CARD_MOVE_TASK.lower()}_failed')
        return False

    if task_type == CARD_DELETE_TASK:
        if _process_card_delete_task(task.get('path')):
            return True
        _enqueue_full_scan_fallback(reason=f'{CARD_DELETE_TASK.lower()}_failed')
        return False

    _enqueue_full_scan_fallback(reason=f'unknown_scan_task:{task_type}')
    return False

def suppress_fs_events(seconds: float = 1.5):
    """
    在本进程即将进行一批文件写入/移动/删除时调用：
    在 seconds 时间窗口内忽略 watchdog 事件，避免触发后台扫描重复劳动。
    """
    ctx.update_fs_ignore(seconds)

def request_scan(reason="fs_event"):
    """
    按需触发扫描：做 debounce，把短时间内多次事件合并成一次扫描。
    """
    with ctx.scan_debounce_lock:
        if ctx.scan_debounce_timer:
            ctx.scan_debounce_timer.cancel()
        
        # 1秒后执行实际的入队操作
        ctx.scan_debounce_timer = threading.Timer(
            1.0, 
            lambda: ctx.scan_queue.put({'type': FULL_SCAN_TASK, 'reason': reason})
        )
        ctx.scan_debounce_timer.daemon = True
        ctx.scan_debounce_timer.start()

def start_fs_watcher():
    """
    监听 CARDS_FOLDER 的变化，触发 request_scan()。
    需要安装 watchdog：pip install watchdog
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.warning("Watchdog module not found. Automatic file system monitoring is disabled.")
        return
    except Exception as e:
        logger.warning(f"Failed to start watchdog: {e}")
        return

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            # 忽略目录本身的修改事件，只关注文件
            if event.is_directory:
                return

            # 仅处理真正会改变索引结果的写类事件，避免读取/打开文件触发无意义重建
            if str(getattr(event, 'event_type', '') or '').lower() not in WRITE_LIKE_EVENT_TYPES:
                return

            # 本进程写文件期间抑制 watchdog
            if ctx.should_ignore_fs_event():
                return

            handled_worldinfo = False
            for candidate_path in (getattr(event, 'src_path', ''), getattr(event, 'dest_path', '')):
                worldinfo_path = classify_worldinfo_path(candidate_path)
                if worldinfo_path.get('kind') == 'global':
                    enqueue_index_job('upsert_worldinfo_path', source_path=candidate_path)
                    handled_worldinfo = True
                    continue
                if worldinfo_path.get('kind') == 'resource':
                    owner_card_ids = resolve_resource_worldinfo_owner_card_ids(candidate_path)
                    if owner_card_ids:
                        for owner_card_id in owner_card_ids:
                            enqueue_index_job('upsert_world_owner', entity_id=owner_card_id, source_path=candidate_path)
                        handled_worldinfo = True

            if handled_worldinfo:
                return

            card_task = _build_card_watch_task(event)
            if card_task:
                ctx.scan_queue.put(card_task)
                return

            for candidate_path in (getattr(event, 'src_path', ''), getattr(event, 'dest_path', '')):
                if _resolve_card_rel_path(candidate_path):
                    _enqueue_full_scan_fallback(reason=f'watchdog_unknown_card_event:{event.event_type}')
                    return

    observer = Observer()
    handler = Handler()
    watch_paths = [os.fspath(CARDS_FOLDER)]
    cfg = load_config()
    for candidate in (cfg.get('world_info_dir'), cfg.get('resources_dir')):
        path = os.fspath(candidate) if candidate else ''
        if path and path not in watch_paths:
            watch_paths.append(path)

    for watch_path in watch_paths:
        try:
            observer.schedule(handler, watch_path, recursive=True)
        except FileNotFoundError:
            logger.warning('Watch path does not exist yet, skipping watchdog registration: %s', watch_path)
        except OSError as e:
            logger.warning('Failed to register watchdog path %s: %s', watch_path, e)
    observer.daemon = True
    observer.start()
    logger.info("File system watcher (watchdog) started.")

def background_scanner():
    """
    后台扫描线程主循环：
    1. 负责将磁盘上的新文件/修改文件同步到数据库。
    2. 负责清理数据库中不存在的文件。
    """
    while True:
        try:
            # === 阻塞等待任务 ===
            task = ctx.scan_queue.get()
            
            if task == "STOP" or (isinstance(task, dict) and task.get("type") == "STOP"):
                ctx.scan_active = False
                break

            # 如果应用还在初始化，暂停扫描，重新入队稍后处理
            if ctx.init_status.get('status') != 'ready':
                time.sleep(1)
                ctx.scan_queue.put(task)
                ctx.scan_queue.task_done()
                continue

            # 开始扫描逻辑
            _process_scan_task(task)
            
            ctx.scan_queue.task_done()
                
        except Exception as e:
            logger.error(f"Background scanner critical error: {e}")
            time.sleep(5)

def _perform_scan_logic():
    """执行具体的数据库同步逻辑"""
    db_path = DEFAULT_DB_PATH
    cards_root = os.path.abspath(os.fspath(CARDS_FOLDER))
    
    # 使用上下文管理器手动连接，不使用 Flask g.db，因为这是后台线程
    with sqlite3.connect(db_path, timeout=60) as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except:
            pass
        
        cursor = conn.cursor()
        
        # 1. 获取数据库当前状态 (用于比对)
        try:
            cursor.execute("""
                SELECT id, last_modified, file_size, token_count, file_hash, is_favorite, card_uid
                FROM card_metadata
            """)
            rows_include_uid = True
        except sqlite3.OperationalError as exc:
            if 'no such column' not in str(exc).lower():
                raise
            cursor.execute("""
                SELECT id, last_modified, file_size, token_count, file_hash, is_favorite
                FROM card_metadata
            """)
            rows_include_uid = False
        rows = cursor.fetchall()
        
        # 构建内存映射: id -> info
        db_files_map = {
            row[0]: {
                'mtime': row[1] or 0,
                'size': row[2] or 0,
                'tokens': row[3] or 0,
                'hash': row[4] or "",
                'fav': row[5] or 0,
                'card_uid': normalize_card_uid(row[6]) if rows_include_uid and len(row) > 6 else '',
            }
            for row in rows
        }
        
        changed_card_paths = {}
        deleted_card_ids = set()
        fs_found_files = set()
        ui_data = load_ui_data()
        ui_changed = False
    
        # 2. 遍历文件系统
        scanned_dir_count = 0
        scanned_file_count = 0
        for root, dirs, files in os.walk(CARDS_FOLDER):
            scanned_dir_count += 1
            rel_path = os.path.relpath(root, CARDS_FOLDER)
            
            if rel_path == ".":
                category = ""
            else:
                category = rel_path.replace('\\', '/')
            
            for file in files:
                file = sanitize_for_utf8(file)
                if not is_card_file(file):
                    continue
                scanned_file_count += 1
                
                full_path = os.path.join(root, file)
                
                # 计算 ID
                if category == "":
                    file_id = file
                else:
                    file_id = f"{category}/{file}"
                
                fs_found_files.add(file_id)
                
                # 获取文件属性 (一次 stat 调用)
                try:
                    st = os.stat(full_path)
                    current_mtime = st.st_mtime
                    current_size = st.st_size
                except OSError:
                    continue
                
                db_info = db_files_map.get(file_id)
                renamed_from_id = ''
                if not db_info:
                    candidate = _find_full_scan_rename_candidate(
                        db_files_map,
                        fs_found_files,
                        full_path,
                        current_size,
                    )
                    if candidate:
                        renamed_from_id, db_info = candidate
                        if rename_card_ui_references(ui_data, renamed_from_id, file_id):
                            ui_changed = True
                
                need_update = False
                file_changed = False
                
                # 判断是否需要更新
                if not db_info:
                    # 新文件
                    need_update = True
                    file_changed = True
                else:
                    # 检查 mtime (容差 0.01s) 或 size
                    if (current_mtime > (db_info['mtime'] + 0.01)) or (current_size != db_info['size']):
                        need_update = True
                        file_changed = True
                    # 文件未变，但 token_count 缺失 -> 仅补全 token
                    elif (db_info['tokens'] is None or db_info['tokens'] == 0) and current_size > 100:
                        need_update = True

                if renamed_from_id:
                    need_update = True
                    file_changed = True
                
                if need_update:
                    # 解析文件
                    info = extract_card_info(full_path)
                    
                    if info:
                        data_block = info.get('data', {}) if 'data' in info else info
                        tags = data_block.get('tags', [])
                        if isinstance(tags, str): 
                            tags = [t.strip() for t in tags.split(',') if t.strip()]
                        elif tags is None: 
                            tags = []
                        tags = list(dict.fromkeys([str(t).strip() for t in tags if str(t).strip()]))
                        
                        char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(full_path))[0]
                        
                        calc_data = data_block.copy()
                        if 'name' not in calc_data: calc_data['name'] = char_name
                        token_count = calculate_token_count(calc_data)
                        has_wi, wi_name = get_wi_meta(data_block)
                        keep_fav = db_info['fav'] if db_info else 0
                        stable_uid = normalize_card_uid(db_info.get('card_uid')) if db_info else ''
                        stable_uid = stable_uid or new_card_uid()

                        # 优化：仅在文件真正变更时重置 hash，否则保留旧 hash (避免昂贵的 hash 计算)
                        if file_changed and not renamed_from_id:
                            file_hash = "" # 下次读取或手动更新时再计算，此处保持为空以示脏数据
                        else:
                            file_hash = (db_info.get('hash', "") if db_info else "")

                        values = (
                                file_id, char_name,
                                data_block.get('description', ''), 
                                data_block.get('first_mes', ''), 
                                data_block.get('mes_example', ''),
                                json.dumps(tags), category, 
                                data_block.get('creator', ''), 
                                data_block.get('character_version', ''),
                                current_mtime, file_hash, current_size, 
                                token_count, has_wi, wi_name,
                                keep_fav, stable_uid,
                            )
                        try:
                            cursor.execute('''
                                    INSERT OR REPLACE INTO card_metadata
                                    (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite, card_uid)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', values)
                        except sqlite3.OperationalError as exc:
                            if 'no such column' not in str(exc).lower() and 'no column named' not in str(exc).lower():
                                raise
                            cursor.execute('''
                                    INSERT OR REPLACE INTO card_metadata
                                    (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', values[:-1])
                        changed_card_paths[file_id] = full_path

        # 3. 清理已删除文件
        for db_id in list(db_files_map.keys()):
            if db_id not in fs_found_files:
                cursor.execute("DELETE FROM card_metadata WHERE id = ?", (db_id,))
                deleted_card_ids.add(db_id)

        if changed_card_paths or deleted_card_ids:
            conn.commit()
            for card_id in sorted(changed_card_paths):
                full_path = changed_card_paths[card_id]
                _enqueue_card_reconcile_jobs(card_id, full_path)

            for card_id in sorted(deleted_card_ids):
                deleted_path = os.path.join(cards_root, card_id.replace('/', os.sep))
                _enqueue_card_reconcile_jobs(card_id, deleted_path, remove_owner_ids=[card_id])

        if ui_changed and not save_ui_data(ui_data):
            logger.warning('全量扫描后保存角色卡聊天绑定失败')

        if changed_card_paths or deleted_card_ids:
            logger.info("Background scan detected changes. Updating cache...")
            schedule_reload(reason="background_scanner")

def start_background_scanner():
    """启动后台扫描线程与（可选的）文件系统监听"""
    if not ctx.scan_active:
        ctx.scan_active = True
        scanner_thread = threading.Thread(target=background_scanner, daemon=True)
        scanner_thread.start()
        logger.info("Background scanner thread started.")
        
        # 根据配置决定是否启动自动文件监听
        enable_auto_scan = current_config.get("enable_auto_scan", True)
        if enable_auto_scan:
            start_fs_watcher()
        else:
            logger.info("Auto file system watcher is disabled by config (enable_auto_scan = false).")
