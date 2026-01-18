import os
import time
import json
import shutil
import sqlite3
import re
import logging
from PIL import Image
from urllib.parse import quote

# === 基础设施 ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH, THUMB_FOLDER
from core.context import ctx
from core.data.db_session import get_db
from core.data.ui_store import load_ui_data, save_ui_data

# === 服务依赖 ===
from core.services.cache_service import update_card_cache
from core.services.scan_service import suppress_fs_events

# === 工具函数 ===
from core.utils.image import (
    extract_card_info, write_card_metadata, resize_image_if_needed,
    clean_thumbnail_cache, find_sidecar_image, clean_sidecar_images
)
from core.utils.filesystem import save_json_atomic
from core.utils.text import calculate_token_count
from core.utils.hash import get_file_hash_and_size

logger = logging.getLogger(__name__)

def update_card_content(card_id, temp_path, is_bundle_update, keep_ui_data, new_upload_ext):
    """
    核心卡片更新逻辑。
    处理文件上传、覆盖、版本新增、格式转换 (JSON<->PNG) 以及元数据合并。
    
    Args:
        card_id (str): 目标卡片 ID (相对路径)。
        temp_path (str): 临时上传文件的路径。
        is_bundle_update (bool): 是否为 Bundle 模式下的版本新增。
        keep_ui_data (dict): 前端传递的 UI 数据 (如 summary, link, tags)。
        new_upload_ext (str): 上传文件的扩展名 (.png/.json)。
        
    Returns:
        dict: 更新结果，包含新的 ID、URL 和更新后的卡片对象。
    """
    # 1. 抑制文件系统事件，避免 watchdog 触发重复扫描
    suppress_fs_events(2.5)
    
    # 路径准备
    original_rel_path = card_id.replace('/', os.sep)
    original_full_path = os.path.join(CARDS_FOLDER, original_rel_path)
    
    # 检查原文件是否存在 (非 Bundle 新增模式下)
    if not os.path.exists(original_full_path) and not is_bundle_update:
        return {"success": False, "msg": f"原角色卡文件不存在: {original_rel_path}"}
        
    old_ext = os.path.splitext(original_full_path)[1].lower()
    
    # ==============================================================================
    # 元数据提取与深度合并策略 (V3 兼容)
    # ==============================================================================
    
    # A. 提取新文件元数据
    new_info_raw = extract_card_info(temp_path) or {}
    
    # B. 提取旧文件元数据 (作为底板)
    old_info_raw = {}
    if os.path.exists(original_full_path) and not is_bundle_update:
         old_info_raw = extract_card_info(original_full_path) or {}
    
    # C. 合并策略：以旧数据为基础，覆盖核心字段，保留 V3 扩展字段
    final_info = old_info_raw.copy() if old_info_raw else new_info_raw.copy()
    
    def get_data_ref(root_dict):
        """获取 V2 root 或 V3 data 节点引用"""
        if 'data' in root_dict and isinstance(root_dict['data'], dict):
            return root_dict['data']
        return root_dict

    target_block = get_data_ref(final_info)
    source_block = get_data_ref(new_info_raw)
    
    # # 允许更新的核心字段白名单
    # core_fields = [
    #     'name', 'description', 'first_mes', 'mes_example', 'alternate_greetings',
    #     'character_book', 'creator', 'character_version', 'creator_notes',
    #     'personality', 'scenario', 'system_prompt', 'post_history_instructions',
    #     'tags', 'spec', 'spec_version'
    # ]
    
    # for key in core_fields:
    #     if key in source_block:
    #          target_block[key] = source_block[key]

    target_block.update(source_block)
    
    # 特殊处理顶层 name
    if 'name' in source_block:
        if 'name' in final_info: 
            final_info['name'] = source_block['name']
            
    # 应用前端传递的 Tags (优先级最高)
    if 'tags' in keep_ui_data:
        target_block['tags'] = keep_ui_data['tags']
        
    # ==============================================================================
    # 文件写入操作
    # ==============================================================================
    
    target_save_path = original_full_path
    final_rel_id = card_id
    new_filename = os.path.basename(original_full_path)

    def save_card_atomic(save_path, image_obj, meta_data):
        """原子保存图片及元数据"""
        temp_save = save_path + ".tmp"
        try:
            image_obj.save(temp_save, "PNG")
            if not write_card_metadata(temp_save, meta_data):
                raise Exception("Failed to write metadata")
            os.replace(temp_save, save_path)
            return True
        except Exception as e:
            if os.path.exists(temp_save): os.remove(temp_save)
            raise e
    
    # === 分支 A: Bundle 模式新增版本 ===
    if is_bundle_update:
        dir_name = os.path.dirname(original_full_path)
        base_name = os.path.basename(original_full_path)
        name_part, _ = os.path.splitext(base_name)
        # 清理版本号后缀
        name_clean = re.sub(r'_v\d+$', '', name_part)
        # 生成新版本文件名
        new_filename = f"{name_clean}_v{int(time.time())}.png"
        target_save_path = os.path.join(dir_name, new_filename)
        
        if '/' in card_id:
            final_rel_id = f"{card_id.rsplit('/', 1)[0]}/{new_filename}"
        else:
            final_rel_id = new_filename
            
        img = Image.open(temp_path)
        img = resize_image_if_needed(img)
        save_card_atomic(target_save_path, img, final_info)
        
    # === 分支 B: 覆盖更新 ===
    else:
        # 情况 B1: JSON -> PNG 格式升级
        if old_ext == '.json' and new_upload_ext == '.png': 
            base_name = os.path.splitext(os.path.basename(original_full_path))[0]
            new_filename = base_name + ".png"
            target_save_path = os.path.join(os.path.dirname(original_full_path), new_filename)
            
            if '/' in card_id:
                final_rel_id = f"{card_id.rsplit('/', 1)[0]}/{new_filename}"
            else:
                final_rel_id = new_filename
                
            img = Image.open(temp_path)
            img = resize_image_if_needed(img)
            save_card_atomic(target_save_path, img, final_info)
            
            # 清理旧 JSON
            clean_sidecar_images(original_full_path)
            if os.path.exists(original_full_path):
                os.remove(original_full_path)
                
        # 情况 B2: 常规更新
        else: 
            if new_upload_ext == '.png':
                img = Image.open(temp_path)
                img = resize_image_if_needed(img)
                save_card_atomic(target_save_path, img, final_info)
            else:
                # JSON -> JSON
                save_json_atomic(target_save_path, final_info)
                    
    # ==============================================================================
    # 数据同步
    # ==============================================================================
    
    # 1. UI Data 同步
    ui_data = load_ui_data()
    ui_key = resolve_ui_key(final_rel_id)
    # 如果 ID 变更，迁移旧数据
    if card_id != final_rel_id and card_id in ui_data and not is_bundle_update:
        if ui_key != card_id: # 避免覆盖
            ui_data[ui_key] = ui_data[card_id]
            del ui_data[card_id]
        
    if ui_key not in ui_data: ui_data[ui_key] = {}
    ui_data[ui_key]['summary'] = keep_ui_data.get('ui_summary', '')
    ui_data[ui_key]['link'] = keep_ui_data.get('source_link', '')
    ui_data[ui_key]['source_title_sync'] = keep_ui_data.get('source_title_sync', '') # 抓取的远程标题
    ui_data[ui_key]['resource_folder'] = keep_ui_data.get('resource_folder', '')
    save_ui_data(ui_data)
    
    # 2. 更新 mtime 和 清理缩略图
    try: os.utime(target_save_path, None)
    except: pass
    new_mtime = os.path.getmtime(target_save_path)
    clean_thumbnail_cache(final_rel_id, THUMB_FOLDER)
    
    # === 获取旧的收藏状态 (用于 ID 变更时迁移或防止覆盖) ===
    old_card_obj = ctx.cache.id_map.get(card_id)
    is_favorite = 1 if (old_card_obj and old_card_obj.get('is_favorite')) else 0

    # 3. 数据库清理 (仅针对 ID 变更)
    if card_id != final_rel_id and not is_bundle_update:
        ctx.cache.delete_card_update(card_id)
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            conn.execute("DELETE FROM card_metadata WHERE id = ?", (card_id,))

    # 4. 数据库写回 (Upsert)
    file_hash, file_size = get_file_hash_and_size(target_save_path)
    update_card_cache(
        final_rel_id,
        target_save_path,
        parsed_info=final_info,
        file_hash=file_hash,
        file_size=file_size,
        mtime=new_mtime,
        is_favorite=is_favorite
    )
    
    # 5. 内存缓存更新
    updated_card_obj = None
    
    if is_bundle_update:
        # Bundle 更新涉及版本列表重构，建议全量 Reload
        ctx.cache.reload_from_db()
        # 找回对象
        bundle_dir_rel = os.path.dirname(final_rel_id).replace('\\', '/')
        if bundle_dir_rel == "": bundle_dir_rel = "."
        for c in ctx.cache.cards:
            if c.get('is_bundle') and c.get('bundle_dir') == bundle_dir_rel:
                updated_card_obj = c
                break
    else:
        # 增量更新内存
        calc_data = target_block.copy()
        if 'name' not in calc_data: 
            calc_data['name'] = final_info.get('name') or os.path.splitext(new_filename)[0]
        token_count = calculate_token_count(calc_data)
        
        update_payload = {
            "id": final_rel_id,
            "filename": new_filename,
            "char_name": calc_data['name'],
            "tags": calc_data.get('tags', []),
            "token_count": token_count,
            "last_modified": new_mtime,
            "is_favorite": bool(is_favorite),
            "ui_summary": keep_ui_data.get('ui_summary', ''),
            "source_link": keep_ui_data.get('source_link', ''),
            "resource_folder": keep_ui_data.get('resource_folder', '')
        }
        
        if card_id != final_rel_id:
            # 补全如果是新对象的额外字段
            update_payload.update({
                "category": final_rel_id.rsplit('/', 1)[0] if '/' in final_rel_id else "",
                "dir_path": os.path.dirname(final_rel_id) if '/' in final_rel_id else "",
                "creator": calc_data.get('creator', ''),
                "char_version": calc_data.get('character_version', ''),
                "image_url": f"/cards_file/{quote(final_rel_id)}?t={new_mtime}",
                "thumb_url": f"/api/thumbnail/{quote(final_rel_id)}?t={new_mtime}"
            })
            ctx.cache.add_card_update(update_payload)
            updated_card_obj = ctx.cache.id_map.get(final_rel_id)
        else:
            updated_card_obj = ctx.cache.update_card_data(card_id, update_payload)

    # 构造返回
    new_image_url = ""
    if updated_card_obj:
        new_image_url = updated_card_obj['image_url']
        if '?t=' not in new_image_url:
            new_image_url += f"?t={int(new_mtime)}"

    return {
        "success": True,
        "file_modified": True,
        "new_id": final_rel_id,
        "new_filename": new_filename,
        "new_image_url": new_image_url,
        "updated_card": updated_card_obj
    }

def resolve_ui_key(card_id):
    """
    智能解析 UI Data Key。
    如果是 Bundle，返回文件夹路径；否则返回 card_id。
    """
    # 1. 缓存命中 (主版本)
    cache_item = ctx.cache.id_map.get(card_id)
    if cache_item and cache_item.get('is_bundle'):
        return cache_item['bundle_dir']
    
    # 2. 检查父目录是否为 Bundle
    parent_dir = os.path.dirname(card_id).replace('\\', '/')
    if parent_dir in ctx.cache.bundle_map:
        return parent_dir
        
    return card_id

def rename_folder_in_db(old_path, new_path):
    """
    在数据库中批量重命名 ID 和 Category 前缀。
    """
    conn = get_db()
    cursor = conn.cursor()
    
    escaped_old_path = old_path.replace('_', r'\_').replace('%', r'\%')

    cursor.execute(f"SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", (escaped_old_path,))
    rows = cursor.fetchall()
    for row in rows:
        curr_id = row[0]
        new_id_val = curr_id.replace(old_path, new_path, 1)
        cursor.execute("""
            UPDATE card_metadata 
            SET id = ?, category = REPLACE(category, ?, ?) 
            WHERE id = ?
        """, (new_id_val, old_path, new_path, curr_id))
    conn.commit()

def rename_folder_in_ui(ui_data, old_path, new_path):
    """
    在 UI Data 中批量重命名 Key 前缀。
    """
    keys_to_move = []
    old_prefix = old_path + "/"
    for key in ui_data.keys():
        if key == old_path or key.startswith(old_prefix):
            keys_to_move.append(key)
    
    changed = False
    for key in keys_to_move:
        if key == old_path: new_key = new_path
        else: new_key = key.replace(old_path, new_path, 1)
        ui_data[new_key] = ui_data[key]
        del ui_data[key]
        changed = True
    return changed