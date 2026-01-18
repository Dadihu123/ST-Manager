import threading
import sqlite3
import json
import os
import time
import logging
from urllib.parse import quote

# === 基础设施 (只导入配置和底层数据操作，不导入 context) ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH
from core.data.db_session import execute_with_retry
from core.data.ui_store import load_ui_data

logger = logging.getLogger(__name__)

class GlobalMetadataCache:
    """
    全局元数据内存缓存。
    负责维护卡片列表、ID映射、文件夹结构统计等信息，减少数据库查询频率。
    实例由 core.context.ctx.cache 管理。
    """
    def __init__(self):
        self.cards = []                 # 扁平化的卡片列表 (包含 Bundle 聚合后的逻辑卡片)
        self.id_map = {}                # id -> card_obj 映射
        self.bundle_map = {}            # bundle_dir -> bundle_card_id (聚合文件夹 -> 主卡ID)
        self.global_tags = set()        # 全局标签池
        self.category_counts = {}       # 分类计数 (路径 -> 数量)
        self.visible_folders = []       # 可见的文件夹列表 (用于前端目录树)
        self.lock = threading.Lock()    # 读写锁
        self.initialized = False        # 是否已加载完成

    def update_card_data(self, card_id, new_data):
        """
        [增量更新] 原地更新单个卡片对象的字段，无需重载数据库。
        用于编辑卡片信息后的快速响应。
        """
        with self.lock:
            if card_id in self.id_map:
                card = self.id_map[card_id]
                
                # 1. 处理分类变更导致的计数更新
                old_category = card.get('category', '')
                new_category = new_data.get('category', old_category)
                
                if old_category != new_category:
                    self._update_category_count(old_category, -1)
                    self._update_category_count(new_category, 1)

                # 2. 批量更新字段
                for k, v in new_data.items():
                    card[k] = v
                
                # 3. 刷新 URL 时间戳 (强制前端重载图片)
                mtime = card.get('last_modified', time.time())
                encoded_id = quote(card['id'])
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"
                
                # 4. 更新全局标签池
                if 'tags' in new_data:
                    current_tags = set(self.global_tags)
                    for t in new_data['tags']:
                        current_tags.add(t)
                    self.global_tags = sorted(list(current_tags))

                return card
            return None

    def move_folder_update(self, old_path_prefix, new_path_prefix):
        """
        [增量更新] 文件夹移动/重命名时的批量更新。
        """
        with self.lock:
            # 1. 找出所有受影响的卡片 ID
            affected_ids = []
            for cid in self.id_map.keys():
                if cid.startswith(old_path_prefix + '/'):
                    affected_ids.append(cid)
            
            # 2. 逐个更新
            for old_id in affected_ids:
                card = self.id_map.pop(old_id)
                
                # 计算新 ID 和新分类
                suffix = old_id[len(old_path_prefix):] 
                new_id = new_path_prefix + suffix
                
                card['id'] = new_id
                
                old_cat = card['category']
                if old_cat == old_path_prefix:
                    new_cat = new_path_prefix
                elif old_cat.startswith(old_path_prefix + '/'):
                    new_cat = new_path_prefix + old_cat[len(old_path_prefix):]
                else:
                    new_cat = new_id.rsplit('/', 1)[0] if '/' in new_id else ""
                
                card['category'] = new_cat
                
                # 处理 Bundle 路径
                if card.get('is_bundle'):
                    b_dir = card.get('bundle_dir', '')
                    if b_dir == old_path_prefix:
                        card['bundle_dir'] = new_path_prefix
                    elif b_dir.startswith(old_path_prefix + '/'):
                        card['bundle_dir'] = new_path_prefix + b_dir[len(old_path_prefix):]

                # 更新 URL
                encoded_id = quote(new_id)
                mtime = card.get('last_modified', 0)
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"

                self.id_map[new_id] = card

            # 3. 重算计数 (全量重算最稳妥)
            self._recalculate_counts()

            # 4. 更新可见文件夹列表
            new_visible = []
            for f in self.visible_folders:
                if f == old_path_prefix:
                    new_visible.append(new_path_prefix)
                elif f.startswith(old_path_prefix + '/'):
                    new_visible.append(new_path_prefix + f[len(old_path_prefix):])
                else:
                    new_visible.append(f)
            self.visible_folders = sorted(new_visible)

    def rename_folder_update(self, old_path, new_path):
        """[增量更新] 文件夹重命名 (逻辑与 move 类似，但包含本身)"""
        # 复用 move 逻辑，但需要处理 folder 本身作为前缀的情况
        # 此处简化逻辑，直接调用 move_folder_update 即可，因为逻辑通用
        self.move_folder_update(old_path, new_path)

    def update_tags_update(self, card_id, new_tags):
        """[增量更新] 更新标签"""
        with self.lock:
            if card_id in self.id_map:
                card = self.id_map[card_id]
                card['tags'] = new_tags
                
                temp_tags = set(self.global_tags)
                for t in new_tags:
                    temp_tags.add(t)
                self.global_tags = sorted(list(temp_tags))

    def move_card_update(self, old_id, new_id, old_category, new_category, new_filename, full_path):
        """[增量更新] 单卡移动/重命名"""
        with self.lock:
            if old_id in self.id_map:
                card = self.id_map.pop(old_id)
                
                card['id'] = new_id
                card['filename'] = new_filename
                card['category'] = new_category
                
                try: 
                    card['last_modified'] = os.path.getmtime(full_path)
                except: 
                    pass
                
                encoded_id = quote(new_id)
                mtime = card.get('last_modified', 0)
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"
                
                self.id_map[new_id] = card
                
                if old_category != new_category:
                    self._update_category_count(old_category, -1)
                    self._update_category_count(new_category, 1)

    def move_bundle_update(self, old_bundle_path, new_bundle_path, old_category, new_category):
        """[增量更新] Bundle 文件夹移动"""
        with self.lock:
            entries_to_move = []
            count_change = 0
            
            for cid in self.id_map.keys():
                if cid == old_bundle_path or cid.startswith(old_bundle_path + '/'):
                    entries_to_move.append(cid)

            for old_id in entries_to_move:
                card = self.id_map.pop(old_id)
                
                # 计算新 ID
                if old_id == old_bundle_path:
                    new_id = new_bundle_path
                else:
                    new_id = new_bundle_path + old_id[len(old_bundle_path):]
                
                card['id'] = new_id
                card['category'] = new_category
                
                if card.get('is_bundle'):
                    card['bundle_dir'] = new_bundle_path
                    if card in self.cards: 
                        count_change = 1 # 只有主显示卡片影响计数

                encoded_id = quote(new_id)
                mtime = card.get('last_modified', 0)
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"
                
                self.id_map[new_id] = card
            
            if count_change > 0 and old_category != new_category:
                self._update_category_count(old_category, -1)
                self._update_category_count(new_category, 1)

    def delete_card_update(self, card_id):
        """[增量更新] 删除卡片"""
        with self.lock:
            if card_id in self.id_map:
                card = self.id_map.pop(card_id)
                if card in self.cards:
                    self.cards.remove(card)
                    self._update_category_count(card['category'], -1)
    
    def delete_bundle_update(self, bundle_dir):
        """[增量更新] 删除 Bundle"""
        with self.lock:
            ids_to_remove = []
            category = ""
            found_main = False
            
            for cid, card in self.id_map.items():
                if (card.get('is_bundle') and card.get('bundle_dir') == bundle_dir) or cid.startswith(bundle_dir + '/'):
                    ids_to_remove.append(cid)
                    if card in self.cards:
                        category = card['category']
                        found_main = True
            
            for cid in ids_to_remove:
                card = self.id_map.pop(cid)
                if card in self.cards:
                    self.cards.remove(card)
            
            if found_main:
                self._update_category_count(category, -1)

    def add_card_update(self, new_card_data):
        """[增量更新] 新增卡片"""
        with self.lock:
            self.cards.append(new_card_data)
            self.id_map[new_card_data['id']] = new_card_data
            
            self._update_category_count(new_card_data['category'], 1)
            
            if isinstance(self.global_tags, list):
                temp_tags = set(self.global_tags)
            else:
                temp_tags = self.global_tags
            for t in new_card_data.get('tags', []):
                temp_tags.add(t)
            self.global_tags = sorted(list(temp_tags))

    def _update_category_count(self, category, delta):
        """递归更新分类计数"""
        if not category: return
        parts = category.split('/')
        current_path = ""
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            if current_path not in self.category_counts:
                self.category_counts[current_path] = 0
            self.category_counts[current_path] += delta
            if self.category_counts[current_path] < 0:
                 self.category_counts[current_path] = 0

    def _recalculate_counts(self):
        """全量重算分类计数 (用于复杂移动操作后)"""
        self.category_counts = {}
        for card in self.cards:
            cat = card['category']
            self._update_category_count(cat, 1)

    def reload_from_db(self):
        """
        [全量加载] 从数据库和 UI Store 读取所有数据并重建内存缓存。
        此操作通常在后台线程执行。
        """
        def _do_fetch_all():
            # 使用独立连接，确保线程安全
            conn = sqlite3.connect(DEFAULT_DB_PATH, timeout=30)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, char_name, tags, category, creator, 
                       char_version, last_modified, created_at, file_hash, token_count, is_favorite
                FROM card_metadata
            """)
            rows = cursor.fetchall()
            conn.close()
            return rows

        with self.lock:
            try:
                # 1. 加载数据
                ui_data = load_ui_data()
                rows = execute_with_retry(_do_fetch_all, max_retries=5)
                
                raw_cards = []
                for row in rows:
                    try: 
                        tags = json.loads(row['tags']) if row['tags'] else []
                    except: 
                        tags = []
                    
                    card_id = row['id'].replace('\\', '/')
                    dir_path = card_id.rsplit('/', 1)[0] if '/' in card_id else ""

                    card_data = {
                        "id": card_id,
                        "filename": os.path.basename(card_id),
                        "char_name": row['char_name'],
                        "tags": tags,
                        "category": row['category'].replace('\\', '/'),
                        "creator": row['creator'],
                        "char_version": row['char_version'],
                        "last_modified": row['last_modified'],
                        "created_at": row['created_at'],
                        "file_hash": row['file_hash'],
                        "token_count": row['token_count'] if 'token_count' in row.keys() else 0,
                        "dir_path": dir_path,
                        "is_bundle": False, 
                        "versions": [],
                        "is_favorite": bool(row['is_favorite']),
                    }
                    raw_cards.append(card_data)

                # 2. 处理 Bundle 聚合逻辑
                bundle_dirs = set()
                unique_dirs = set(c['dir_path'] for c in raw_cards)
                
                # 扫描文件系统确认 .bundle 标记 (这步可能略慢，但通常文件夹不多)
                for d in unique_dirs:
                    if not d: continue
                    sys_path_d = d.replace('/', os.sep)
                    full_dir_path = os.path.join(CARDS_FOLDER, sys_path_d)
                    if os.path.exists(os.path.join(full_dir_path, '.bundle')):
                        bundle_dirs.add(d)

                final_cards = []
                bundles = {}
                new_bundle_map = {} 

                for card in raw_cards:
                    d = card['dir_path']
                    if d in bundle_dirs:
                        if d not in bundles: bundles[d] = []
                        bundles[d].append(card)
                    else:
                        self._enrich_card_ui(card, ui_data, is_bundle=False)
                        final_cards.append(card)

                # 聚合 Bundle 版本
                for dir_path, version_list in bundles.items():
                    if not version_list: continue
                    # 按时间倒序，最新的为主版本
                    version_list.sort(key=lambda x: x['last_modified'], reverse=True)
                    latest_card = version_list[0]
                    
                    bundle_card = latest_card.copy()
                    bundle_card['is_bundle'] = True
                    bundle_card['bundle_dir'] = dir_path
                    bundle_card['versions'] = [
                        {"id": v['id'], "filename": v['filename'], "last_modified": v['last_modified'], "char_version": v['char_version']} 
                        for v in version_list
                    ]
                    # 分类为 Bundle 所在文件夹的父级
                    bundle_card['category'] = dir_path.rsplit('/', 1)[0] if '/' in dir_path else ""
                    
                    self._enrich_card_ui(bundle_card, ui_data, is_bundle=True)
                    final_cards.append(bundle_card)
                    new_bundle_map[dir_path] = bundle_card['id']

                # 3. 统计计数和标签
                new_global_tags = set()
                new_cat_counts = {}
                bundle_paths = set(bundle_dirs)
                # 用于推导文件夹列表
                derived_folders = set()

                for c in final_cards:
                    for t in c.get('tags', []): 
                        new_global_tags.add(t)
                    
                    cat = c['category']
                    if cat: derived_folders.add(cat)
                    if cat not in new_cat_counts: new_cat_counts[cat] = 0
                    new_cat_counts[cat] += 1
                    
                    # 递归统计父分类
                    if cat != "":
                        parts = cat.split('/')
                        current = ""
                        for part in parts:
                            current = f"{current}/{part}" if current else part
                            derived_folders.add(current) # 记录父级分类
                            if current != cat:
                                if current not in new_cat_counts: new_cat_counts[current] = 0
                                new_cat_counts[current] += 1

                # 4. 更新实例状态
                self.cards = final_cards
                self.id_map = {c['id']: c for c in final_cards}
                self.bundle_map = new_bundle_map
                self.global_tags = sorted(list(new_global_tags))
                self.category_counts = new_cat_counts
                self.visible_folders = [f for f in sorted(list(derived_folders)) if f not in bundle_paths and f != ""]
                
                self.initialized = True
                logger.info(f"Cache reloaded: {len(self.cards)} items (including bundles).")
                
            except Exception as e:
                logger.error(f"Cache reload error: {e}")
                # 保持旧数据，防止应用崩溃

    def toggle_favorite_update(self, card_id, new_status):
        """[增量更新] 更新卡片收藏状态"""
        with self.lock:
            if card_id in self.id_map:
                self.id_map[card_id]['is_favorite'] = new_status
                return True
            return False

    def _enrich_card_ui(self, card, ui_data, is_bundle=False):
        """辅助函数：将 UI 数据合并到卡片对象中"""
        key = card['bundle_dir'] if is_bundle else card['id']
        # 如果 Bundle 目录没有 UI 数据，尝试回退使用主卡片 ID
        fallback_key = card['id'] if is_bundle else None
        
        ui_info = ui_data.get(key)
        if not ui_info and fallback_key:
            ui_info = ui_data.get(fallback_key, {})
        if not ui_info: 
            ui_info = {}
            
        card['ui_summary'] = ui_info.get('summary', '')
        card['source_link'] = ui_info.get('link', '')
        card['source_title_sync'] = ui_info.get('source_title_sync', '')
        card['resource_folder'] = ui_info.get('resource_folder', '')
        
        # 预计算 URL
        mtime = int(card.get('last_modified', 0))
        encoded_id = quote(card['id'])
        card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
        card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"

