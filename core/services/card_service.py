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
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH, THUMB_FOLDER, BASE_DIR, load_config
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
from core.utils.filesystem import save_json_atomic, sanitize_filename
from core.utils.text import calculate_token_count
from core.utils.hash import get_file_hash_and_size

logger = logging.getLogger(__name__)

# 内部辅助函数：获取或创建资源目录
def _ensure_resource_folder_exists(card_id, hint_name):
    """
    确保卡片有资源目录。如果未设置，则基于 hint_name 自动创建并绑定。
    返回: (folder_name, full_path, is_newly_created)
    """
    ui_data = load_ui_data()
    ui_key = resolve_ui_key(card_id)
    
    current_val = ui_data.get(ui_key, {}).get('resource_folder')
    
    cfg = load_config()
    res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
    
    # 情况 A: 已配置，确保物理目录存在
    if current_val:
        # 处理绝对路径
        if os.path.isabs(current_val):
            full_path = current_val
        else:
            full_path = os.path.join(res_root, current_val)
            
        if not os.path.exists(full_path):
            try: os.makedirs(full_path)
            except: pass
        return current_val, full_path, False

    # 情况 B: 未配置，自动创建
    safe_name = sanitize_filename(hint_name)
    if not safe_name or safe_name == 'undefined':
        safe_name = "untitled_card"
        
    new_folder_name = safe_name
    full_path = os.path.join(res_root, new_folder_name)
    
    # 防重名
    counter = 1
    while os.path.exists(full_path):
        new_folder_name = f"{safe_name}_{counter}"
        full_path = os.path.join(res_root, new_folder_name)
        counter += 1
        
    # 创建物理目录
    os.makedirs(full_path)
    
    # 绑定数据 (UI Data)
    if ui_key not in ui_data: ui_data[ui_key] = {}
    ui_data[ui_key]['resource_folder'] = new_folder_name
    save_ui_data(ui_data)
    
    # 绑定数据 (Cache) - 确保前端能即时感知
    target_id = card_id
    if ctx.cache and ui_key in ctx.cache.bundle_map:
        target_id = ctx.cache.bundle_map[ui_key]
    
    if ctx.cache:
        ctx.cache.update_card_data(target_id, {"resource_folder": new_folder_name})
        
    return new_folder_name, full_path, True

def update_card_content(card_id, temp_path, is_bundle_update, keep_ui_data, new_upload_ext, image_policy='overwrite'):
    """
    核心卡片更新逻辑。
    处理文件上传、覆盖、版本新增、格式转换 (JSON<->PNG) 以及元数据合并。
    
    Args:
        card_id (str): 目标卡片 ID (相对路径)。
        temp_path (str): 临时上传文件的路径。
        is_bundle_update (bool): 是否为 Bundle 模式下的版本新增。
        keep_ui_data (dict): 前端传递的 UI 数据 (如 summary, link, tags)。
        new_upload_ext (str): 上传文件的扩展名 (.png/.json)。
        image_policy (str): 图片处理策略
            - 'overwrite': 直接覆盖 (默认)
            - 'keep_image': 保留原图像素，只更新元数据
            - 'archive_old': 覆盖前，将原图存入资源目录
            - 'archive_new': 保留原图像素，将新上传的图存入资源目录
        
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
    
    # 如果上传的是 JSON 文件，必须包含角色卡的关键特征字段，防止误传其他 JSON 覆盖数据
    if new_upload_ext == '.json':
        is_valid_card = False
        
        # V2/V1 特征: 根节点有 name/description/first_mes 等
        if 'name' in new_info_raw or 'description' in new_info_raw or 'first_mes' in new_info_raw:
            is_valid_card = True
            
        # V3 特征: 有 spec='chara_card_v3' 或 data 节点
        if 'spec' in new_info_raw or 'data' in new_info_raw:
            is_valid_card = True
            
        if not is_valid_card:
            logger.warning(f"Update rejected: Uploaded JSON does not look like a character card. Keys: {list(new_info_raw.keys())}")
            return {"success": False, "msg": "上传的文件不是有效的角色卡格式 (缺少必要字段)"}
    
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

    target_block.update(source_block)
    
    # 特殊处理顶层 name
    if 'name' in source_block:
        if 'name' in final_info: 
            final_info['name'] = source_block['name']
            
    # 应用前端传递的 Tags (优先级最高)
    if 'tags' in keep_ui_data:
        target_block['tags'] = keep_ui_data['tags']
    
    # 提取 card_name 用于自动命名资源文件夹
    # 优先用新数据的名字，其次旧数据的名字，最后文件名
    hint_name_for_folder = ""
    if 'name' in source_block: 
        hint_name_for_folder = source_block['name']
    elif 'name' in target_block: 
        hint_name_for_folder = target_block['name']
    else: 
        hint_name_for_folder = os.path.splitext(new_filename)[0]
    
    # --- 资源归档辅助函数 ---
    def _archive_file(src_path, label):
        try:
            # 自动获取或创建目录
            res_name, res_full_path, is_new = _ensure_resource_folder_exists(card_id, hint_name_for_folder)
            
            # 如果是新创建的，需要同步到 keep_ui_data 以便稍后 save_ui_data 时不会被覆盖为空
            if is_new:
                keep_ui_data['resource_folder'] = res_name

            ext = os.path.splitext(src_path)[1]
            timestamp = int(time.time())
            dst_name = f"{label}_{timestamp}{ext}"
            shutil.copy2(src_path, os.path.join(res_full_path, dst_name))
            
            return res_name # 返回目录名供后续使用
        except Exception as e:
            logger.error(f"Archive failed: {e}")
            return None
    
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
        
    # ==============================================================================
    # 文件写入操作
    # ==============================================================================
    
    target_save_path = original_full_path
    final_rel_id = card_id
    new_filename = os.path.basename(original_full_path)
    
    # 标记：是否发生了格式转换 (JSON -> PNG)
    is_format_conversion = (not is_bundle_update) and (old_ext == '.json' and new_upload_ext == '.png')
    
    # 如果发生了格式转换，必须计算新的路径
    if is_format_conversion:
        base_name = os.path.splitext(os.path.basename(original_full_path))[0]
        new_filename = base_name + ".png"
        target_save_path = os.path.join(os.path.dirname(original_full_path), new_filename)
        if '/' in card_id:
            final_rel_id = f"{card_id.rsplit('/', 1)[0]}/{new_filename}"
        else:
            final_rel_id = new_filename
    
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
        # 2.1 执行归档策略
        if image_policy == 'archive_old' and os.path.exists(original_full_path):
            if old_ext == '.json':
                sidecar = find_sidecar_image(original_full_path)
                if sidecar: _archive_file(sidecar, "archived_cover")
            else:
                _archive_file(original_full_path, "archived_cover")
        
        elif image_policy == 'archive_new':
            if new_upload_ext == '.png':
                _archive_file(temp_path, "archived_upload")

        # 2.2 确定图片源 (Pixel Source)
        # 默认使用新上传的图片
        source_img_path = temp_path 
        use_old_image = False

        if image_policy == 'keep_image' or image_policy == 'archive_new':
            # 用户想保留原图。
            # 如果原文件是 PNG，可以直接用。
            if old_ext == '.png' and os.path.exists(original_full_path):
                source_img_path = original_full_path
                use_old_image = True
            # 如果原文件是 JSON，尝试找伴生图
            elif old_ext == '.json':
                sidecar = find_sidecar_image(original_full_path)
                if sidecar:
                    source_img_path = sidecar
                    use_old_image = True
                else:
                    # 原来是 JSON 且没图，用户却选了 keep_image，这是矛盾的。
                    # 回退到使用新上传的图 (temp_path)
                    pass

        # 2.3 执行写入
        # 情况 A: 目标是 PNG (无论是升级还是原生覆盖)
        if target_save_path.lower().endswith('.png'):
            img = Image.open(source_img_path)
            # 如果使用新图，可能需要 resize；旧图通常不动
            if not use_old_image:
                img = resize_image_if_needed(img)
            
            save_card_atomic(target_save_path, img, final_info)
            
            # 如果是格式转换 (JSON -> PNG)，完成后删除旧 JSON 和伴生图
            if is_format_conversion:
                clean_sidecar_images(original_full_path)
                if os.path.exists(original_full_path):
                    os.remove(original_full_path)

        # 情况 B: 目标是 JSON (仅当没升级格式且上传的也是 JSON 时)
        else:
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
    
    # 如果 keep_ui_data 里有值（即前端传来 或者 上面 _archive_file 注入的），使用它
    current_res_folder = keep_ui_data.get('resource_folder')
    if current_res_folder:
        ui_data[ui_key]['resource_folder'] = str(current_res_folder).strip()
    
    # UI Data 安全同步
    target_fields = [
        ('summary', 'ui_summary'), 
        ('link', 'source_link')
    ]
    
    for db_field, input_field in target_fields:
        new_val = keep_ui_data.get(input_field)
        if new_val:
            ui_data[ui_key][db_field] = str(new_val).strip()
        elif not is_bundle_update:
            if input_field in keep_ui_data:
                ui_data[ui_key][db_field] = ""
    save_ui_data(ui_data)
    
    # 2. 更新 mtime 和 清理缩略图
    try: os.utime(target_save_path, None)
    except: pass
    new_mtime = os.path.getmtime(target_save_path)
    clean_thumbnail_cache(final_rel_id, THUMB_FOLDER)
    
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
        mtime=new_mtime
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
            "ui_summary": keep_ui_data.get('ui_summary', ''),
            "source_link": keep_ui_data.get('source_link', ''),
            "resource_folder": keep_ui_data.get('resource_folder', ''),
            "char_version": calc_data.get('character_version', ''),
            "creator": calc_data.get('creator', '')
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

# 皮肤换封服务
def swap_skin_to_cover(card_id, skin_filename, save_old_to_resource=False):
    """
    将资源目录下的皮肤设为当前卡片封面。
    :param save_old_to_resource: 是否将被替换的封面保存回资源目录
    """
    suppress_fs_events(2.0)
    
    # 1. 定位卡片
    card_rel_path = card_id.replace('/', os.sep)
    card_full_path = os.path.join(CARDS_FOLDER, card_rel_path)
    
    if not os.path.exists(card_full_path):
        return {"success": False, "msg": "Card not found"}
        
    # 2. 定位皮肤
    ui_data = load_ui_data()
    ui_key = resolve_ui_key(card_id)
    res_folder_name = ui_data.get(ui_key, {}).get('resource_folder')
    
    if not res_folder_name:
        return {"success": False, "msg": "Resource folder not set"}
        
    cfg = load_config()
    res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
    
    # 支持绝对路径配置
    if os.path.isabs(res_folder_name):
        skin_path = os.path.join(res_folder_name, skin_filename)
        res_dir_path = res_folder_name
    else:
        skin_path = os.path.join(res_root, res_folder_name, skin_filename)
        res_dir_path = os.path.join(res_root, res_folder_name)
        
    if not os.path.exists(skin_path):
        return {"success": False, "msg": "Skin file not found"}

    # 3. 读取当前卡片元数据 (因为皮肤图通常没有 Metadata，或者 Metadata 不对)
    # 我们需要保留卡片当前的设定，只换图
    current_info = extract_card_info(card_full_path)
    if not current_info:
        return {"success": False, "msg": "Failed to read current card metadata"}

    # 4. 归档旧封面
    if save_old_to_resource:
        if not os.path.exists(res_dir_path): os.makedirs(res_dir_path)
        timestamp = int(time.time())
        old_ext = os.path.splitext(card_full_path)[1]
        archive_name = f"prev_cover_{timestamp}{old_ext}"
        shutil.copy2(card_full_path, os.path.join(res_dir_path, archive_name))

    # 5. 执行替换
    try:
        # 打开皮肤图片
        img = Image.open(skin_path)
 
        # 先保存皮肤像素到目标，再写入 Meta
        # 为了原子性写入临时文件
        temp_target = card_full_path + ".tmp.png"
        
        # 构造 PngInfo
        from PIL import PngImagePlugin
        meta = PngImagePlugin.PngInfo()
        # 序列化当前数据
        import json, base64
        # 使用工具函数确保 V3 标准化
        from core.utils.data import normalize_card_v3, deterministic_sort
        norm_data = normalize_card_v3(current_info)
        sorted_data = deterministic_sort(norm_data)
        chara_str = base64.b64encode(json.dumps(sorted_data).encode('utf-8')).decode('utf-8')
        meta.add_text('chara', chara_str)
        
        img.save(temp_target, "PNG", pnginfo=meta)
        
        # 替换
        os.replace(temp_target, card_full_path)
        
        # 更新数据库缓存 (Hash变了，但Meta没变，更新Hash和Size)
        from core.services.cache_service import update_card_cache
        from core.utils.hash import get_file_hash_and_size
        
        f_hash, f_size = get_file_hash_and_size(card_full_path)
        update_card_cache(card_id, card_full_path, file_hash=f_hash, file_size=f_size)
        
        # 清理缩略图
        from core.utils.image import clean_thumbnail_cache
        from core.config import THUMB_FOLDER
        clean_thumbnail_cache(card_id, THUMB_FOLDER)
        
        return {"success": True, "new_hash": f_hash}
        
    except Exception as e:
        return {"success": False, "msg": str(e)}

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

# 内部移动卡片逻辑
def move_card_internal(card_id, target_category):
    """
    将卡片(文件)或聚合包(文件夹)移动到指定分类。
    
    Args:
        card_id (str): 源 ID (相对路径，可能是 "Category/Char.png" 或 "Category/BundleDir")
        target_category (str): 目标父分类 (例如 "NewCategory")
    
    Returns:
        (bool, str, str): (success, new_id, message)
    """
    try:
        # 1. 基础检查与路径准备
        if not card_id: return False, None, "ID missing"
        if target_category == "根目录": target_category = ""
        
        old_rel_path = card_id.replace('/', os.sep)
        old_full_path = os.path.join(CARDS_FOLDER, old_rel_path)
        
        if not os.path.exists(old_full_path):
            return False, None, "Source not found"

        # 判断是文件还是文件夹 (Bundle)
        is_directory = os.path.isdir(old_full_path)

        # 准备目标基础目录
        dst_base_dir = os.path.join(CARDS_FOLDER, target_category)
        if not os.path.exists(dst_base_dir):
            os.makedirs(dst_base_dir)
            
        # 如果源目录的父级就是目标目录，无需移动
        if os.path.dirname(old_full_path) == os.path.abspath(dst_base_dir):
            return True, card_id, "Target is same as source"

        # 2. 冲突检测与自动重命名
        basename = os.path.basename(old_full_path)
        counter = 0
        final_name = basename
        
        # 拆分文件名用于递增 (文件夹则不拆扩展名)
        if is_directory:
            name_part, ext_part = basename, ""
        else:
            name_part, ext_part = os.path.splitext(basename)
        
        while True:
            if counter > 0:
                final_name = f"{name_part}_{counter}{ext_part}"
            
            candidate_path = os.path.join(dst_base_dir, final_name)
            
            # 检查主路径冲突
            if not os.path.exists(candidate_path):
                # 如果是单文件 JSON，还需检查伴生图是否会冲突
                if not is_directory and final_name.lower().endswith('.json'):
                    # 预测伴生图名称 (假设伴生图肯定和主文件同名)
                    # 实际上我们需要知道原文件是否有伴生图，如果有，就得检查目标是否有同名图
                    sidecar_src = find_sidecar_image(old_full_path)
                    if sidecar_src:
                        side_ext = os.path.splitext(sidecar_src)[1]
                        side_candidate = os.path.join(dst_base_dir, f"{name_part}_{counter}{side_ext}" if counter > 0 else f"{name_part}{side_ext}")
                        if os.path.exists(side_candidate):
                            counter += 1
                            continue
                break
            counter += 1
            
        dst_full_path = os.path.join(dst_base_dir, final_name)

        # 3. 获取旧分类信息 (用于缓存更新)
        old_category = ""
        if ctx.cache and card_id in ctx.cache.id_map:
            old_category = ctx.cache.id_map[card_id].get('category', "")
        elif '/' in card_id:
            old_category = card_id.rsplit('/', 1)[0]

        # 4. 执行物理移动
        shutil.move(old_full_path, dst_full_path)
        
        # 如果是单文件且为 JSON，尝试移动伴生图
        if not is_directory and basename.lower().endswith('.json'):
            # 注意：old_full_path 已经移走了，不能再用 find_sidecar_image(old_full_path)
            # 我们根据路径推断
            from core.consts import SIDECAR_EXTENSIONS
            old_dir = os.path.dirname(old_full_path)
            new_dir = os.path.dirname(dst_full_path)
            old_base_no_ext = os.path.splitext(basename)[0]
            new_base_no_ext = os.path.splitext(final_name)[0]
            
            for ext in SIDECAR_EXTENSIONS:
                s_src = os.path.join(old_dir, old_base_no_ext + ext)
                if os.path.exists(s_src):
                    s_dst = os.path.join(new_dir, new_base_no_ext + ext)
                    shutil.move(s_src, s_dst)

        # 5. 计算新 ID
        new_id = f"{target_category}/{final_name}" if target_category else final_name
        
        # 6. 数据同步 (DB, UI, Cache)
        conn = get_db()
        ui_data = load_ui_data()
        ui_changed = False

        if is_directory:
            # === Bundle 模式处理 ===
            
            # DB: 更新该文件夹下所有文件的 ID 和 Category
            # 使用 SQL 字符串替换功能
            escaped_old_id = card_id.replace('_', r'\_').replace('%', r'\%')
            
            # 查找所有子文件
            cursor = conn.execute(f"SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", (escaped_old_id,))
            rows = cursor.fetchall()
            
            for row in rows:
                sub_old_id = row[0]
                # 替换前缀: old_id -> new_id
                sub_new_id = sub_old_id.replace(card_id, new_id, 1)
                
                # Bundle 内的卡片，其 category 实际上就是 Bundle 的路径 (即 new_id)
                # 所以 category 也要更新为新的 Bundle 路径 (new_id)
                conn.execute("""
                    UPDATE card_metadata 
                    SET id = ?, category = ? 
                    WHERE id = ?
                """, (sub_new_id, new_id, sub_old_id))
            
            # UI Data: 迁移文件夹本身的 UI 数据
            if card_id in ui_data:
                ui_data[new_id] = ui_data[card_id]
                del ui_data[card_id]
                ui_changed = True

            # Cache: 调用 move_bundle_update
            if ctx.cache:
                # 注意：参数4 new_category 传 new_id，因为 Bundle 内的卡片 category = bundle_path
                ctx.cache.move_bundle_update(card_id, new_id, old_category, new_id)

        else:
            # === 单文件模式处理 ===
            
            # DB
            conn.execute("UPDATE card_metadata SET id = ?, category = ? WHERE id = ?", (new_id, target_category, card_id))
            
            # UI Data
            if card_id in ui_data:
                ui_data[new_id] = ui_data[card_id]
                del ui_data[card_id]
                ui_changed = True
            
            # Cache
            if ctx.cache:
                ctx.cache.move_card_update(card_id, new_id, old_category, target_category, final_name, dst_full_path)

        conn.commit()
        if ui_changed: save_ui_data(ui_data)

        return True, new_id, "Success"
        
    except Exception as e:
        print(f"Move internal error: {e}") # 打印日志以便调试
        return False, None, str(e)

# 内部标签/收藏更新逻辑
def modify_card_attributes_internal(card_id, add_tags=None, remove_tags=None, set_favorite=None):
    """
    修改卡片属性 (标签、收藏)
    """
    try:
        full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        if not os.path.exists(full_path): return False

        info = extract_card_info(full_path)
        if not info: return False
        
        changed = False
        
        # 1. 处理标签 (写入文件 + DB)
        if add_tags or remove_tags:
            data_block = info.get('data', {}) if 'data' in info else info
            current_tags = data_block.get('tags', []) or []
            
            tags_set = set(current_tags)
            if add_tags: tags_set.update(add_tags)
            if remove_tags: tags_set.difference_update(remove_tags)
            
            new_tags = sorted(list(tags_set))
            
            if new_tags != sorted(current_tags):
                data_block['tags'] = new_tags
                if 'data' in info: info['data'] = data_block # V3 write back
                else: info = data_block # V2 write back
                
                write_card_metadata(full_path, info)
                
                # Update DB
                conn = get_db()
                conn.execute("UPDATE card_metadata SET tags = ? WHERE id = ?", (json.dumps(new_tags), card_id))
                conn.commit()
                
                # Update Cache
                if ctx.cache: ctx.cache.update_tags_update(card_id, new_tags)
                changed = True

        # 2. 处理收藏 (仅 DB + Cache)
        if set_favorite is not None:
            new_status = 1 if set_favorite else 0
            conn = get_db()
            conn.execute("UPDATE card_metadata SET is_favorite = ? WHERE id = ?", (new_status, card_id))
            conn.commit()
            
            if ctx.cache: ctx.cache.toggle_favorite_update(card_id, bool(new_status))
            changed = True
            
        return True
    except Exception as e:
        logger.error(f"Modify attributes error: {e}")
        return False