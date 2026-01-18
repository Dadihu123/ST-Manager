import threading
import time
import sqlite3
import json
import os
import logging
from urllib.parse import quote

# === 基础设施 ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.db_session import get_db, execute_with_retry
from core.data.ui_store import load_ui_data

# === 工具函数 ===
from core.utils.hash import get_file_hash_and_size
from core.utils.image import extract_card_info
from core.utils.data import get_wi_meta
from core.utils.text import calculate_token_count

logger = logging.getLogger(__name__)

# ================= 模块级辅助函数 =================

def _do_reload_now():
    """Timer 回调：执行重载"""
    with ctx.reload_lock:
        if not ctx.reload_pending:
            return
        ctx.reload_pending = False
    
    try:
        ctx.cache.reload_from_db()
    except Exception as e:
        logger.error(f"Scheduled reload failed: {e}")

def schedule_reload(delay: float = 0.8, reason: str = ""):
    """
    防抖重载：在 delay 秒内多次调用只触发一次 reload。
    """
    with ctx.reload_lock:
        ctx.reload_pending = True
        if reason:
            ctx.reload_last_reason = reason
        
        if ctx.reload_timer:
            ctx.reload_timer.cancel()
        
        ctx.reload_timer = threading.Timer(delay, _do_reload_now)
        ctx.reload_timer.daemon = True
        ctx.reload_timer.start()

def force_reload(reason: str = ""):
    """强制立即重载"""
    with ctx.reload_lock:
        ctx.reload_pending = True
        if reason:
            ctx.reload_last_reason = reason
        if ctx.reload_timer:
            ctx.reload_timer.cancel()
            ctx.reload_timer = None
    _do_reload_now()

def update_card_cache(card_id, full_path, *, parsed_info=None, file_hash=None, file_size=None, mtime=None, ctime=None, is_favorite=None):
    """
    [数据库写操作] 更新单个卡片的数据库记录。
    通常由 API 路由或扫描器调用。
    使用 get_db()，因此必须在请求上下文或手动推送的上下文中运行。
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 如果未显式提供收藏状态，尝试从数据库获取现有值，防止被覆盖重置
        if is_favorite is None:
            try:
                cursor.execute("SELECT is_favorite FROM card_metadata WHERE id = ?", (card_id,))
                row = cursor.fetchone()
                is_favorite = row['is_favorite'] if row else 0
            except:
                is_favorite = 0

        if file_hash is None or file_size is None:
            file_hash, file_size = get_file_hash_and_size(full_path)
        
        if mtime is None:
            try: mtime = os.path.getmtime(full_path)
            except: mtime = 0
            
        if ctime is None:
            try: ctime = os.path.getctime(full_path)
            except: ctime = 0

        info = parsed_info if parsed_info is not None else extract_card_info(full_path)
        
        if info:
            data_block = info.get('data', {}) if 'data' in info else info
            tags = data_block.get('tags', [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',') if t.strip()]
            elif tags is None:
                tags = []
            tags = list(dict.fromkeys([str(t).strip() for t in tags if str(t).strip()]))
            
            char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(full_path))[0]
            
            if '/' in card_id:
                category = card_id.rsplit('/', 1)[0]
            else:
                category = ""
            
            # Token 计算
            calc_data = data_block.copy()
            if 'name' not in calc_data: calc_data['name'] = char_name
            token_count = calculate_token_count(calc_data)
            has_wi, wi_name = get_wi_meta(data_block)

            cursor.execute('''
                INSERT OR REPLACE INTO card_metadata 
                (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, created_at, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                card_id,
                char_name,
                data_block.get('description', ''),
                data_block.get('first_mes', ''),
                data_block.get('mes_example', ''),
                json.dumps(tags),
                category,
                data_block.get('creator', ''),
                data_block.get('character_version', ''),
                mtime,
                ctime,
                file_hash,
                file_size,
                token_count,
                has_wi,
                wi_name,
                is_favorite
            ))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update DB cache for {card_id}: {e}")

def invalidate_wi_list_cache():
    """主动失效：解决 overwrite 保存不改目录mtime 的情况"""
    with ctx.wi_list_cache_lock:
        ctx.wi_list_cache.clear()