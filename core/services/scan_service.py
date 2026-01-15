import os
import time
import threading
import sqlite3
import json
import logging

# === 基础设施 ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx

# === 业务逻辑引用 ===
from core.services.cache_service import schedule_reload

# === 工具函数 ===
from core.utils.filesystem import is_card_file
from core.utils.image import extract_card_info
from core.utils.text import calculate_token_count
from core.utils.data import get_wi_meta, sanitize_for_utf8

logger = logging.getLogger(__name__)

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
            lambda: ctx.scan_queue.put({"type": "FULL_SCAN", "reason": reason})
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

            # 本进程写文件期间抑制 watchdog
            if ctx.should_ignore_fs_event():
                return
            
            # 过滤掉非关注文件类型，减少噪音
            if not is_card_file(event.src_path):
                return

            # 触发扫描
            request_scan(reason=f"{event.event_type}:{os.path.basename(event.src_path)}")

    observer = Observer()
    observer.schedule(Handler(), CARDS_FOLDER, recursive=True)
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
            _perform_scan_logic()
            
            ctx.scan_queue.task_done()
                
        except Exception as e:
            logger.error(f"Background scanner critical error: {e}")
            time.sleep(5)

def _perform_scan_logic():
    """执行具体的数据库同步逻辑"""
    db_path = DEFAULT_DB_PATH
    
    # 使用上下文管理器手动连接，不使用 Flask g.db，因为这是后台线程
    with sqlite3.connect(db_path, timeout=60) as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except:
            pass
        
        cursor = conn.cursor()
        
        # 1. 获取数据库当前状态 (用于比对)
        cursor.execute("""
            SELECT id, last_modified, file_size, token_count, file_hash, is_favorite
            FROM card_metadata
        """)
        rows = cursor.fetchall()
        
        # 构建内存映射: id -> info
        db_files_map = {
            row[0]: {
                'mtime': row[1] or 0,
                'size': row[2] or 0,
                'tokens': row[3] or 0,
                'hash': row[4] or "",
                'fav': row['is_favorite'] or 0
            }
            for row in rows
        }
        
        changes_detected = False
        fs_found_files = set()
    
        # 2. 遍历文件系统
        for root, dirs, files in os.walk(CARDS_FOLDER):
            rel_path = os.path.relpath(root, CARDS_FOLDER)
            
            if rel_path == ".":
                category = ""
            else:
                category = rel_path.replace('\\', '/')
            
            for file in files:
                file = sanitize_for_utf8(file)
                if not is_card_file(file):
                    continue
                
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

                        # 优化：仅在文件真正变更时重置 hash，否则保留旧 hash (避免昂贵的 hash 计算)
                        if file_changed:
                            file_hash = "" # 下次读取或手动更新时再计算，此处保持为空以示脏数据
                        else:
                            file_hash = (db_info.get('hash', "") if db_info else "")

                        cursor.execute('''
                                INSERT OR REPLACE INTO card_metadata
                                (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                file_id, char_name,
                                data_block.get('description', ''), 
                                data_block.get('first_mes', ''), 
                                data_block.get('mes_example', ''),
                                json.dumps(tags), category, 
                                data_block.get('creator', ''), 
                                data_block.get('character_version', ''),
                                current_mtime, file_hash, current_size, 
                                token_count, has_wi, wi_name,
                                keep_fav
                            ))
                        changes_detected = True

        # 3. 清理已删除文件
        for db_id in list(db_files_map.keys()):
            if db_id not in fs_found_files:
                cursor.execute("DELETE FROM card_metadata WHERE id = ?", (db_id,))
                changes_detected = True

        if changes_detected:
            conn.commit()
            logger.info("Background scan detected changes. Updating cache...")
            schedule_reload(reason="background_scanner")

def start_background_scanner():
    """启动后台扫描线程"""
    if not ctx.scan_active:
        ctx.scan_active = True
        scanner_thread = threading.Thread(target=background_scanner, daemon=True)
        scanner_thread.start()
        logger.info("Background scanner thread started.")
        
        # 同时启动文件监听
        start_fs_watcher()