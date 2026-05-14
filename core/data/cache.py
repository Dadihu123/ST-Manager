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
from core.data.ui_store import (
    load_ui_data,
    get_version_remark,
    get_import_time,
    get_last_sent_to_st,
    ensure_import_time,
    cleanup_stale_version_remarks,
    migrate_bundle_remarks_to_versions,
    save_ui_data,
)
from core.utils.filesystem import is_card_file

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

    def _normalize_tags(self, tags):
        """规范化 tags，兼容 None / 字符串 / 非法类型。"""
        if tags is None:
            return []

        if isinstance(tags, str):
            raw_tags = [t.strip() for t in tags.split(',') if t.strip()]
        elif isinstance(tags, (list, tuple, set)):
            raw_tags = list(tags)
        else:
            return []

        return [str(t).strip() for t in raw_tags if str(t).strip()]

    def _rebuild_global_tags_locked(self):
        tags = set()
        for card in self.id_map.values():
            for tag in self._normalize_tags(card.get('tags')):
                tags.add(tag)
        self.global_tags = sorted(tags)

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

                # 兼容异常元数据: tags 为 null/字符串/非法类型时标准化为列表
                if 'tags' in new_data:
                    card['tags'] = self._normalize_tags(new_data.get('tags'))
                
                # 3. 刷新 URL 时间戳 (强制前端重载图片)
                mtime = card.get('last_modified', time.time())
                encoded_id = quote(card['id'])
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"
                
                # 4. 更新全局标签池
                if 'tags' in new_data:
                    self._rebuild_global_tags_locked()

                return card
            return None

    def move_folder_update(self, old_path_prefix, new_path_prefix):
        """
        [增量更新] 文件夹移动/重命名时的批量更新。
        """
        with self.lock:
            new_bundle_map = {}
            for bundle_dir, bundle_card_id in self.bundle_map.items():
                if bundle_dir == old_path_prefix:
                    remapped_dir = new_path_prefix
                elif bundle_dir.startswith(old_path_prefix + '/'):
                    remapped_dir = new_path_prefix + bundle_dir[len(old_path_prefix):]
                else:
                    remapped_dir = bundle_dir

                if bundle_card_id.startswith(old_path_prefix + '/'):
                    remapped_card_id = new_path_prefix + bundle_card_id[len(old_path_prefix):]
                else:
                    remapped_card_id = bundle_card_id

                new_bundle_map[remapped_dir] = remapped_card_id

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

                    remapped_bundle_dir = card.get('bundle_dir', '')
                    card['category'] = remapped_bundle_dir.rsplit('/', 1)[0] if '/' in remapped_bundle_dir else ''

                    versions = card.get('versions')
                    if isinstance(versions, list):
                        for version in versions:
                            if not isinstance(version, dict):
                                continue
                            version_id = str(version.get('id') or '')
                            if version_id.startswith(old_path_prefix + '/'):
                                version['id'] = new_path_prefix + version_id[len(old_path_prefix):]

                # 更新 URL
                encoded_id = quote(new_id)
                mtime = card.get('last_modified', 0)
                card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
                card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"

                self.id_map[new_id] = card

            self.bundle_map = new_bundle_map

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
                card['tags'] = self._normalize_tags(new_tags)
                self._rebuild_global_tags_locked()

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

                source_bundle_id = self.bundle_map.get(old_category)
                target_bundle_id = self.bundle_map.get(new_category)

                if source_bundle_id and source_bundle_id == target_bundle_id:
                    bundle_card = self.id_map.get(source_bundle_id)
                    versions = bundle_card.get('versions') if isinstance(bundle_card, dict) else None
                    if isinstance(versions, list):
                        for version in versions:
                            if not isinstance(version, dict):
                                continue
                            if version.get('id') in {old_id, new_id}:
                                version['id'] = new_id
                                version['filename'] = new_filename
                                break
                        else:
                            versions.append({'id': new_id, 'filename': new_filename})
                else:
                    if source_bundle_id:
                        source_bundle = self.id_map.get(source_bundle_id)
                        source_versions = source_bundle.get('versions') if isinstance(source_bundle, dict) else None
                        if isinstance(source_versions, list):
                            source_bundle['versions'] = [
                                version
                                for version in source_versions
                                if not (isinstance(version, dict) and version.get('id') == old_id)
                            ]

                    if target_bundle_id:
                        target_bundle = self.id_map.get(target_bundle_id)
                        target_versions = target_bundle.get('versions') if isinstance(target_bundle, dict) else None
                        if isinstance(target_versions, list):
                            for version in target_versions:
                                if not isinstance(version, dict):
                                    continue
                                if version.get('id') in {old_id, new_id}:
                                    version['id'] = new_id
                                    version['filename'] = new_filename
                                    break
                            else:
                                target_versions.append({'id': new_id, 'filename': new_filename})
                
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
            new_card_data['tags'] = self._normalize_tags(new_card_data.get('tags'))
            ui_data = load_ui_data()

            import_ts = new_card_data.get('import_time')
            try:
                import_ts = float(import_ts)
                if import_ts <= 0:
                    raise ValueError('invalid import_time')
            except Exception:
                import_ts = new_card_data.get('last_modified', time.time())
            new_card_data['import_time'] = import_ts

            sent_ts = new_card_data.get('last_sent_to_st')
            try:
                sent_ts = float(sent_ts)
                if sent_ts <= 0:
                    raise ValueError('invalid last_sent_to_st')
            except Exception:
                ui_key = new_card_data.get('bundle_dir') if new_card_data.get('is_bundle') else new_card_data.get('id')
                sent_ts = get_last_sent_to_st(ui_data, ui_key)
            new_card_data['last_sent_to_st'] = sent_ts

            self.cards.append(new_card_data)
            self.id_map[new_card_data['id']] = new_card_data
            
            self._update_category_count(new_card_data['category'], 1)
            
            if isinstance(self.global_tags, list):
                temp_tags = set(self.global_tags)
            else:
                temp_tags = self.global_tags
            for t in new_card_data['tags']:
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

    def _collect_bundle_version_ids_from_fs(self, dir_path):
        """Return card ids physically present in a bundle folder, or None if the folder cannot be inspected."""
        if not dir_path:
            return None

        full_dir_path = os.path.join(CARDS_FOLDER, dir_path.replace('/', os.sep))
        if not os.path.isdir(full_dir_path):
            return None

        try:
            version_ids = set()
            for filename in os.listdir(full_dir_path):
                full_path = os.path.join(full_dir_path, filename)
                if os.path.isfile(full_path) and is_card_file(filename):
                    version_ids.add(f"{dir_path}/{filename}".replace('\\', '/'))
            return version_ids
        except OSError as exc:
            logger.warning(f"Inspecting bundle folder failed for {dir_path}: {exc}")
            return None

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
                       char_version, last_modified, file_hash, token_count, is_favorite
                FROM card_metadata
            """)
            rows = cursor.fetchall()
            conn.close()
            return rows

        with self.lock:
            try:
                physical_folders = set()
                physical_bundle_dirs = set()
                try:
                    for root, dirs, files in os.walk(CARDS_FOLDER):
                        # 排除以 . 开头的隐藏目录 (如 .trash, .git)
                        dirs[:] = [d for d in dirs if not d.startswith('.')]
                        
                        # 计算相对路径
                        rel_path = os.path.relpath(root, CARDS_FOLDER)
                        if rel_path == ".":
                            # 根目录下的子文件夹
                            for d in dirs:
                                physical_folders.add(d)
                        else:
                            # 子目录下的子文件夹
                            current_rel = rel_path.replace('\\', '/')
                            physical_folders.add(current_rel)
                            if '.bundle' in files:
                                physical_bundle_dirs.add(current_rel)
                            for d in dirs:
                                physical_folders.add(f"{current_rel}/{d}")
                except Exception as fs_e:
                    logger.error(f"Scanning physical folders failed: {fs_e}")

                # 1. 加载数据
                ui_data = load_ui_data()
                ui_data_stale_cleaned = False
                rows = execute_with_retry(_do_fetch_all, max_retries=5)
                
                raw_cards = []
                for row in rows:
                    try: 
                        tags = json.loads(row['tags']) if row['tags'] else []
                    except: 
                        tags = []
                    tags = self._normalize_tags(tags)
                    
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
                        "file_hash": row['file_hash'],
                        "token_count": row['token_count'] if 'token_count' in row.keys() else 0,
                        "dir_path": dir_path,
                        "is_bundle": False, 
                        "versions": [],
                        "is_favorite": bool(row['is_favorite']),
                    }
                    raw_cards.append(card_data)

                # 2. 处理 Bundle 聚合逻辑
                bundle_dirs = set(physical_bundle_dirs)
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

                old_bundle_map = dict(self.bundle_map)
                unbundled_dirs = set(old_bundle_map.keys()) - bundle_dirs

                if unbundled_dirs:
                    for unbundled_dir in unbundled_dirs:
                        migrated = migrate_bundle_remarks_to_versions(ui_data, unbundled_dir)
                        if migrated > 0:
                            ui_data_stale_cleaned = True

                for card in raw_cards:
                    d = card['dir_path']
                    if d in bundle_dirs:
                        if d not in bundles: bundles[d] = []
                        bundles[d].append(card)
                    else:
                        if self._enrich_card_ui(card, ui_data, is_bundle=False):
                            ui_data_stale_cleaned = True
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

                    bundle_card['versions'] = []
                    cover_id = latest_card['id']
                    for v in version_list:
                        ver_info = {
                            "id": v['id'],
                            "filename": v['filename'],
                            "last_modified": v['last_modified'],
                            "import_time": get_import_time(ui_data, v['id'], v['last_modified']),
                            "char_version": v.get('char_version', '')
                        }
                        ver_remark = get_version_remark(ui_data, dir_path, v['id'], cover_id)
                        if ver_remark:
                            ver_info['ui_summary'] = ver_remark.get('summary', '')
                            ver_info['source_link'] = ver_remark.get('link', '')
                            ver_info['resource_folder'] = ver_remark.get('resource_folder', '')
                        bundle_card['versions'].append(ver_info)

                    # 分类为 Bundle 所在文件夹的父级
                    bundle_card['category'] = dir_path.rsplit('/', 1)[0] if '/' in dir_path else ""

                    if self._enrich_card_ui(bundle_card, ui_data, is_bundle=True):
                        ui_data_stale_cleaned = True
                    final_cards.append(bundle_card)
                    new_bundle_map[dir_path] = bundle_card['id']

                    valid_version_ids = {v['id'] for v in bundle_card['versions']}
                    # ui_data.json is the durable UI store; only remove stale version notes
                    # after checking the physical bundle folder, not DB rows alone.
                    fs_version_ids = self._collect_bundle_version_ids_from_fs(dir_path)
                    if fs_version_ids is not None:
                        valid_version_ids = fs_version_ids
                    if (
                        fs_version_ids is not None
                        and cleanup_stale_version_remarks(ui_data, dir_path, valid_version_ids)
                    ):
                        ui_data_stale_cleaned = True

                if ui_data_stale_cleaned:
                    save_ui_data(ui_data)

                # 3. 统计计数和标签
                new_global_tags = set()
                new_cat_counts = {}
                bundle_paths = set(bundle_dirs)
                # 用于推导文件夹列表
                derived_folders = set()

                for c in final_cards:
                    for t in self._normalize_tags(c.get('tags')):
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
                all_visible = derived_folders.union(physical_folders)
                # 过滤掉 Bundle 文件夹本身 (Bundle 应该作为卡片显示，而不是文件夹)
                self.visible_folders = [
                    f for f in sorted(list(all_visible)) 
                    if f not in bundle_paths and f != "" and f != "."
                ]
                
                # 确保空文件夹也有计数条目 (0)
                for f in self.visible_folders:
                    if f not in new_cat_counts:
                        new_cat_counts[f] = 0
                
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

        ui_info = ui_data.get(key, {})

        if is_bundle and ui_info:
            cover_id = card.get('id')
            if cover_id:
                cover_remark = get_version_remark(ui_data, key, cover_id, cover_id)
                if cover_remark:
                    card['ui_summary'] = cover_remark.get('summary', '')
                    card['source_link'] = cover_remark.get('link', '')
                    card['resource_folder'] = cover_remark.get('resource_folder', '')
                else:
                    card['ui_summary'] = ui_info.get('summary', '')
                    card['source_link'] = ui_info.get('link', '')
                    card['resource_folder'] = ui_info.get('resource_folder', '')
            else:
                card['ui_summary'] = ui_info.get('summary', '')
                card['source_link'] = ui_info.get('link', '')
                card['resource_folder'] = ui_info.get('resource_folder', '')
        else:
            card['ui_summary'] = ui_info.get('summary', '')
            card['source_link'] = ui_info.get('link', '')
            card['resource_folder'] = ui_info.get('resource_folder', '')

        import_time_changed, import_ts = ensure_import_time(ui_data, key, card.get('last_modified', 0))
        card['import_time'] = import_ts
        card['last_sent_to_st'] = get_last_sent_to_st(ui_data, key)

        # 预计算 URL
        mtime = int(card.get('last_modified', 0))
        encoded_id = quote(card['id'])
        card['image_url'] = f"/cards_file/{encoded_id}?t={mtime}"
        card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={mtime}"

        return import_time_changed

