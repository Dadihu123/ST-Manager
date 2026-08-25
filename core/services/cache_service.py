import threading
import time
import sqlite3
import json
import os
import logging

# === 基础设施 ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.context import ctx
from core.data.db_session import get_db, execute_with_retry
from core.data.ui_store import load_ui_data
from core.utils.card_identity import new_card_uid, normalize_card_uid

# === 工具函数 ===
from core.utils.hash import get_file_hash_and_size
from core.utils.image import extract_card_info
from core.utils.data import get_wi_meta
from core.utils.text import calculate_token_count

logger = logging.getLogger(__name__)

# ================= 模块级辅助函数 =================


class CardCacheUpdateResult(dict):
    def __bool__(self):
        return bool(self.get('cache_updated'))


def _row_value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return default


def _load_card_identity(cursor, card_id):
    try:
        cursor.execute(
            'SELECT is_favorite, has_character_book, card_uid FROM card_metadata WHERE id = ?',
            (card_id,),
        )
        return cursor.fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such column' not in str(exc).lower():
            raise
        cursor.execute(
            'SELECT is_favorite, has_character_book FROM card_metadata WHERE id = ?',
            (card_id,),
        )
        return cursor.fetchone()

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

def update_card_cache(card_id, full_path, *, parsed_info=None, file_hash=None, file_size=None, mtime=None, remove_entity_ids=None, card_uid=None):
    """
    [数据库写操作] 更新单个卡片的数据库记录。
    通常由 API 路由或扫描器调用。
    使用 get_db()，因此必须在请求上下文或手动推送的上下文中运行。
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        result = CardCacheUpdateResult({
            'cache_updated': False,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        })

        # 获取收藏状态和历史 embedded worldinfo 状态，供调用方决定后续索引同步
        row = _load_card_identity(cursor, card_id)
        current_fav = _row_value(row, 'is_favorite', 0) or 0
        previous_has_wi = bool(_row_value(row, 'has_character_book', 0))
        stable_uid = normalize_card_uid(card_uid) or normalize_card_uid(_row_value(row, 'card_uid'))
        if not stable_uid:
            for old_id in remove_entity_ids or []:
                old_row = _load_card_identity(cursor, old_id)
                stable_uid = normalize_card_uid(_row_value(old_row, 'card_uid'))
                if stable_uid:
                    break
        stable_uid = stable_uid or new_card_uid()
        result['previous_has_embedded_wi'] = previous_has_wi
        
        if file_hash is None or file_size is None:
            file_hash, file_size = get_file_hash_and_size(full_path)
        
        if mtime is None:
            try: mtime = os.path.getmtime(full_path)
            except: mtime = 0
            
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
                mtime,
                file_hash,
                file_size,
                token_count,
                has_wi,
                wi_name,
                current_fav,
                stable_uid,
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
            
            conn.commit()
            result['cache_updated'] = True
            result['has_embedded_wi'] = bool(has_wi)
            return result
        return result
    except Exception as e:
        logger.error(f"Failed to update DB cache for {card_id}: {e}")
        return CardCacheUpdateResult({
            'cache_updated': False,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        })

def invalidate_wi_list_cache():
    """主动失效：解决 overwrite 保存不改目录mtime 的情况"""
    with ctx.wi_list_cache_lock:
        ctx.wi_list_cache.clear()
