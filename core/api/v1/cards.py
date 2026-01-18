import os
import json
import shutil
import uuid
import random
import time
import requests
import sqlite3
import logging
from urllib.parse import quote, unquote, urlparse
from PIL import Image
from flask import Blueprint, request, jsonify

# === 基础设施 ===
from core.config import CARDS_FOLDER, DATA_DIR, BASE_DIR, THUMB_FOLDER, TRASH_FOLDER, DEFAULT_DB_PATH, load_config, current_config
from core.context import ctx
from core.data.db_session import get_db
from core.data.ui_store import load_ui_data, save_ui_data
from core.consts import SIDECAR_EXTENSIONS

# === 核心服务 ===
from core.services.scan_service import suppress_fs_events
from core.services.cache_service import schedule_reload, force_reload, update_card_cache
from core.services.card_service import update_card_content, rename_folder_in_db, rename_folder_in_ui, resolve_ui_key
from core.services.update_service import check_chub_update, check_discord_update, fetch_remote_metadata

# === 工具函数 ===
from core.utils.image import (
    extract_card_info, write_card_metadata,
    find_sidecar_image, clean_thumbnail_cache,
    clean_sidecar_images, resize_image_if_needed )
from core.utils.filesystem import safe_move_to_trash, is_card_file
from core.utils.hash import get_file_hash_and_size
from core.utils.text import calculate_token_count
from core.utils.data import get_wi_meta, normalize_card_v3, deterministic_sort

logger = logging.getLogger(__name__)

bp = Blueprint('cards', __name__)

@bp.route('/api/list_cards')
def api_list_cards():
    # 确保缓存已加载
    if not ctx.cache.initialized:
        ctx.cache.reload_from_db()

    # 参数获取
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
    except:
        page, page_size = 1, 20
    
    category = request.args.get('category', '')
    tags_param = request.args.get('tags', '')
    search = request.args.get('search', '').lower().strip()
    search_type = request.args.get('search_type', 'mix')
    sort_mode = request.args.get('sort', current_config.get('default_sort', 'date_desc'))
    
    # --- 获取是否递归显示的参数 (默认 true) ---
    recursive_str = request.args.get('recursive', 'true')
    is_recursive = recursive_str.lower() == 'true'

    filter_fav = request.args.get('favorites_only', 'false') == 'true'
    fav_first = request.args.get('favorites_first', 'false') == 'true'

    # 1. 获取所有卡片, 浅拷贝
    with ctx.cache.lock:
        candidates = list(ctx.cache.cards)
    library_total = len(candidates)

    # 2. 分类过滤 (支持递归子分类)
    # 逻辑：如果选了分类，先缩减范围；如果没选(根目录)，则范围是全部
    if category and category != "根目录":
        target_cat_lower = category.lower()
        target_cat_prefix = target_cat_lower + '/'
        
        if is_recursive:
            # 保留：分类完全相等 OR 是其子分类 (以 "name/" 开头)
            candidates  = [
                c for c in candidates  
                if c['category'].lower() == target_cat_lower or c['category'].lower().startswith(target_cat_prefix)
            ]
        else:
            # --- 严格匹配当前分类，不包含子分类 ---
            candidates = [
                c for c in candidates  
                if c['category'].lower() == target_cat_lower
            ]
    else:
        # 根目录情况
        if not is_recursive:
            # 根目录下不递归 = 只看 category 为空的卡片
            candidates = [c for c in candidates if c['category'] == ""]

    # === 在应用“搜索”和“标签”过滤之前，先计算当前分类下的标签池 ===
    # 这样标签池就只受“文件夹/分类”影响，而不会被“选中的标签”把自己给过滤没了
    sidebar_tags_set = set()
    for c in candidates:
        for t in c['tags']:
            sidebar_tags_set.add(t)
    sidebar_tags = sorted(list(sidebar_tags_set))

    if filter_fav:
        candidates = [c for c in candidates if c.get('is_favorite')]

    # 3. 搜索过滤 (在已经(可能)被分类缩小范围的基础上继续过滤)
    if search:
        # 辅助函数：安全转小写
        def safe_lower(val):
            return str(val).lower() if val is not None else ""
        if search_type == 'name':
            candidates = [c for c in candidates if search in safe_lower(c.get('char_name', ''))]
        elif search_type == 'filename':
            candidates = [c for c in candidates if search in safe_lower(c.get('filename', ''))]
        elif search_type == 'tags':
            # 确保 tags 是列表
            candidates = [
                c for c in candidates 
                if isinstance(c.get('tags'), list) and any(search in safe_lower(t) for t in c['tags'])
            ]
        elif search_type == 'creator':
            candidates = [c for c in candidates if search in safe_lower(c.get('creator', ''))]
        else: # mix (包含 global)
            # 混合搜索：名称 OR 文件名 OR 备注 OR 标签
            candidates = [
                c for c in candidates if (
                    search in safe_lower(c.get('char_name', '')) or 
                    search in safe_lower(c.get('filename', '')) or 
                    search in safe_lower(c.get('ui_summary', '')) or
                    (isinstance(c.get('tags'), list) and any(search in safe_lower(t) for t in c['tags']))
                )
            ]

    # 4. 标签过滤 (继续在结果上过滤，只影响卡片列表，不影响 sidebar_tags)
    if tags_param:
        tag_list = [t.strip() for t in tags_param.split('|||') if t.strip()]
        if tag_list:
            candidates = [c for c in candidates if all(t in c['tags'] for t in tag_list)]

    # 5. 排序
    filtered_cards = candidates
    reverse = 'desc' in sort_mode
    key_func = lambda x: x['last_modified'] # 默认
    if 'date' in sort_mode:
        key_func = lambda x: x['last_modified']
    elif 'create' in sort_mode:
        key_func = lambda x: x.get('created_at', 0)
    elif 'name' in sort_mode:
        key_func = lambda x: x['char_name'].lower()
    elif 'token' in sort_mode:
        key_func = lambda x: x.get('token_count', 0)

    # 执行排序
    if fav_first:
        filtered_cards.sort(key=key_func, reverse=reverse)
        filtered_cards.sort(key=lambda x: 0 if x.get('is_favorite') else 1)
    else:
        filtered_cards.sort(key=key_func, reverse=reverse)

    # 6. 分页
    total_count = len(filtered_cards)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = filtered_cards[start:end]

    # 7. 返回结果
    safe_folders = [f for f in ctx.cache.visible_folders if f]
    
    return jsonify({
        "cards": paginated,
        "global_tags": ctx.cache.global_tags, 
        "sidebar_tags": sidebar_tags,              
        "all_folders": [f['path'] for f in sorted([{'path': p} for p in safe_folders], key=lambda x: x['path'])],
        "category_counts": ctx.cache.category_counts,
        "total_count": total_count,
        "library_total": library_total,
        "page": page,
        "page_size": page_size
    })

# 切换收藏状态
@bp.route('/api/toggle_favorite', methods=['POST'])
def api_toggle_favorite():
    try:
        card_id = request.json.get('id')
        if not card_id: return jsonify({"success": False, "msg": "Missing ID"})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取当前状态并取反
        cursor.execute("SELECT is_favorite FROM card_metadata WHERE id = ?", (card_id,))
        row = cursor.fetchone()
        if not row: return jsonify({"success": False, "msg": "Card not found in DB"})
        
        new_status = 0 if row['is_favorite'] else 1
        
        # 更新数据库
        cursor.execute("UPDATE card_metadata SET is_favorite = ? WHERE id = ?", (new_status, card_id))
        conn.commit()
        
        # 更新缓存
        ctx.cache.toggle_favorite_update(card_id, bool(new_status))
        
        return jsonify({"success": True, "new_status": bool(new_status)})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/update_card', methods=['POST'])
def api_update_card():
    try:
        # 保存会写 PNG/JSON + utime + rename，抑制 watchdog
        suppress_fs_events(2.5)
        data = request.json
        raw_id = data.get('id')
        # 获取强制更新标记 (用于设为封面)
        force_set_cover = data.get('set_as_cover', False) 
        
        if not raw_id: return jsonify({"success": False, "msg": "Missing ID"})
        
        card_id = raw_id.replace('/', os.sep)
        # 默认不改文件名
        new_filename = data.get('new_filename') or os.path.basename(card_id)
        
        old_full_path = os.path.join(CARDS_FOLDER, card_id)
        
        # 检查是否需要移动/改名
        folder_path = os.path.dirname(old_full_path)
        new_full_path = os.path.join(folder_path, new_filename)
        is_renamed = False
        if os.path.abspath(old_full_path).lower() != os.path.abspath(new_full_path).lower():
            is_renamed = True

        # --- 辅助函数：深度清洗数据 ---
        def clean_for_compare(obj):
            if isinstance(obj, dict):
                new_dict = {}
                for k, v in obj.items():
                    cleaned_v = clean_for_compare(v)
                    if cleaned_v not in [None, "", [], {}]:
                        new_dict[k] = cleaned_v
                return new_dict if new_dict else None
            elif isinstance(obj, list):
                new_list = []
                for item in obj:
                    cleaned_item = clean_for_compare(item)
                    if cleaned_item not in [None, "", [], {}]:
                        new_list.append(cleaned_item)
                return new_list if new_list else None
            elif isinstance(obj, str):
                return obj.strip() if obj.strip() else None
            else:
                return obj

        # 读取原文件信息
        info = extract_card_info(old_full_path)
        file_content_modified = False

        # =========================================================
        # 1. 元数据写入逻辑 (如果是设为封面，完全跳过此步骤)
        # =========================================================
        if info and not force_set_cover:
            target = info.get('data', info)
            
            # 仅当不是设为封面时，才从前端 data 获取字段并比对
            # 如果是设为封面，data 里这些字段都是空的，绝对不能同步！
            core_fields = {
                'name': data.get('char_name'),
                'description': data.get('description'),
                'first_mes': data.get('first_mes'),
                'mes_example': data.get('mes_example'),
                'personality': data.get('personality'),
                'scenario': data.get('scenario'),
                'creator_notes': data.get('creator_notes'),
                'system_prompt': data.get('system_prompt'),
                'post_history_instructions': data.get('post_history_instructions'),
                'creator': data.get('creator'),
                'character_version': data.get('character_version'),
            }
            
            for k, v in core_fields.items():
                old_val = target.get(k) or ''
                new_val = v or ''
                if str(old_val).strip() != str(new_val).strip():
                    target[k] = v
                    file_content_modified = True
                    # 同步到 root (V2兼容)
                    if target is not info:
                        if k in info: info[k] = v
                        elif k == 'creator_notes' and 'creatorcomment' in info: info['creatorcomment'] = v
            
            if clean_for_compare(data.get('extensions')) != clean_for_compare(target.get('extensions')):
                target['extensions'] = data.get('extensions')
                file_content_modified = True

            new_tags = data.get('tags') or []
            old_tags = target.get('tags') or []
            set_new = set(t.strip() for t in new_tags if t and t.strip())
            set_old = set(t.strip() for t in old_tags if t and t.strip())
            if set_new != set_old:
                final_tags = list(set_new)
                target['tags'] = final_tags
                file_content_modified = True
                if target is not info and 'tags' in info: info['tags'] = final_tags
                
            new_alt = [x.strip() for x in (data.get('alternate_greetings') or []) if x and x.strip()]
            old_alt = [x.strip() for x in (target.get('alternate_greetings') or []) if x and x.strip()]
            if json.dumps(new_alt, sort_keys=True) != json.dumps(old_alt, sort_keys=True):
                target['alternate_greetings'] = new_alt
                file_content_modified = True
                if target is not info and 'alternate_greetings' in info: info['alternate_greetings'] = new_alt

            new_book = data.get('character_book')
            old_book = target.get('character_book')
            if clean_for_compare(new_book) != clean_for_compare(old_book):
                target['character_book'] = new_book
                file_content_modified = True
                
            if file_content_modified:
                if 'name' in info and data.get('char_name'): info['name'] = data.get('char_name')
                write_card_metadata(old_full_path, info)

        # 2. 处理重命名/移动
        final_rel_path_id = raw_id
        current_full_path = old_full_path
        
        if is_renamed:
            if os.path.exists(new_full_path):
                return jsonify({"success": False, "msg": f"目标文件名已存在: {new_filename}"})
            os.rename(old_full_path, new_full_path)
            rel_dir = os.path.dirname(raw_id)
            final_rel_path_id = f"{rel_dir}/{new_filename}" if rel_dir else new_filename
            current_full_path = new_full_path
            file_content_modified = True 

        # 3. 始终更新 UI Data (Bundle模式下不影响文件内容)
        ui_data = load_ui_data()
        
        if data.get('save_ui_to_bundle') and data.get('bundle_dir'):
            ui_key = data.get('bundle_dir')
        else:
            ui_key = final_rel_path_id
            if raw_id != final_rel_path_id and raw_id in ui_data:
                ui_data[final_rel_path_id] = ui_data[raw_id]
                del ui_data[raw_id]

        if ui_key not in ui_data: ui_data[ui_key] = {}
        # 注意：如果是设为封面，前端发来的 ui_summary 可能是空的，保留原有值
        if not force_set_cover: 
            ui_data[ui_key]['summary'] = data.get('ui_summary', '')
            ui_data[ui_key]['link'] = str(data.get('source_link') or '').strip()
            ui_data[ui_key]['source_title_sync'] = data.get('source_title_sync', '')
            ui_data[ui_key]['resource_folder'] = data.get('resource_folder', '')
            save_ui_data(ui_data)

        # 4. 强制更新修改时间 & 数据库
        import time
        current_mtime = 0
        should_touch_file = (file_content_modified or is_renamed or force_set_cover)
        
        if should_touch_file:
            current_mtime = time.time()
            if force_set_cover: current_mtime += 1.0
            try: 
                os.utime(current_full_path, (current_mtime, current_mtime))
            except: pass
        else:
            # 如果只改了 UI 数据，保持原文件的修改时间
            current_mtime = os.path.getmtime(current_full_path)
        
        if not info and os.path.exists(current_full_path):
             info = extract_card_info(current_full_path)
            
        # 获取现有的收藏状态，防止更新时丢失
        old_card_obj = ctx.cache.id_map.get(raw_id)
        is_favorite_val = 1 if (old_card_obj and old_card_obj.get('is_favorite')) else 0

        # 更新 DB (Hash / Time)
        update_card_cache(final_rel_path_id, current_full_path, parsed_info=info, mtime=current_mtime, is_favorite=is_favorite_val)

        
        data_block = info.get('data', info) if info else {}
        
        # 使用文件中的数据，而不是 request.json 中的数据（因为设为封面时 request 是空的）
        calc_data = data_block.copy()
        if 'name' not in calc_data: calc_data['name'] = data_block.get('name', '')
        
        token_count = calculate_token_count(calc_data)

        # 确定 UI 数据的来源
        ui_summary_val = ui_data.get(ui_key, {}).get('summary', '')
        source_link_val = ui_data.get(ui_key, {}).get('link', '')
        source_title_sync_val = ui_data.get(ui_key, {}).get('source_title_sync', '')
        res_folder_val = ui_data.get(ui_key, {}).get('resource_folder', '')

        update_payload = {
            "id": final_rel_path_id,
            "filename": new_filename,
            "char_name": calc_data.get('name', ''),
            "description": data_block.get('description', ''),
            "tags": data_block.get('tags', []), # 从文件读 Tags，防止覆盖为空
            "is_favorite": bool(is_favorite_val),
            "ui_summary": ui_summary_val,
            "source_link": source_link_val,
            "source_title_sync": source_title_sync_val,
            "resource_folder": res_folder_val,
            "token_count": token_count,
            "last_modified": current_mtime,
            "dir_path": os.path.dirname(final_rel_path_id) if '/' in final_rel_path_id else ""
        }
        
        # 更新单卡内存对象
        updated_card_obj = ctx.cache.update_card_data(raw_id, update_payload)
        
        # ID 变更处理
        if raw_id != final_rel_path_id:
            with ctx.cache.lock:
                if raw_id in ctx.cache.id_map: del ctx.cache.id_map[raw_id]
                if updated_card_obj:
                    ctx.cache.id_map[final_rel_path_id] = updated_card_obj

        # =========================================================================
        # Bundle 重新聚合逻辑 (Database Based)
        # =========================================================================
        final_return_obj = updated_card_obj
        
        bundle_dir = data.get('bundle_dir')
        if not bundle_dir:
            dir_path = os.path.dirname(current_full_path)
            if os.path.exists(os.path.join(dir_path, '.bundle')):
                bundle_dir = os.path.relpath(dir_path, CARDS_FOLDER).replace('\\', '/')

        if bundle_dir:
            with ctx.cache.lock:
                db_path = DEFAULT_DB_PATH
                version_list = []
                
                with sqlite3.connect(db_path, timeout=10) as conn:
                    conn.row_factory = sqlite3.Row
                    escaped_bundle_dir = bundle_dir.replace('_', r'\_').replace('%', r'\%')

                    cursor = conn.execute(
                        "SELECT id, char_name, last_modified, char_version FROM card_metadata WHERE category = ?", 
                        (bundle_dir,)
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        cursor = conn.execute(
                            "SELECT id, char_name, last_modified, char_version FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", 
                            (escaped_bundle_dir,)
                        )
                        rows = cursor.fetchall()

                    for row in rows:
                        v_obj = {
                            "id": row['id'],
                            "filename": os.path.basename(row['id']),
                            "last_modified": row['last_modified'],
                            "char_version": row['char_version'],
                            "char_name": row['char_name'],
                            "category": bundle_dir,
                            "bundle_dir": bundle_dir
                        }
                        
                        # 强制使用最新时间
                        if v_obj['id'] == final_rel_path_id:
                            v_obj['last_modified'] = current_mtime
                            
                        version_list.append(v_obj)

                if version_list:
                    # 重新排序
                    version_list.sort(key=lambda x: x['last_modified'], reverse=True)
                    
                    new_leader_stub = version_list[0]
                    bundle_card = new_leader_stub.copy()
                    
                    # 补全 Leader 信息
                    if bundle_card['id'] == final_rel_path_id:
                        bundle_card.update(update_payload)
                    else:
                        if new_leader_stub['id'] in ctx.cache.id_map:
                            cached = ctx.cache.id_map[new_leader_stub['id']]
                            bundle_card.update(cached)

                    bundle_card['is_bundle'] = True
                    bundle_card['bundle_dir'] = bundle_dir
                    bundle_card['versions'] = [
                        {"id": v['id'], "filename": v['filename'], "last_modified": v['last_modified'], "char_version": v.get('char_version', '')} 
                        for v in version_list
                    ]
                    
                    # UI Data
                    ui_info = ui_data.get(bundle_dir, {})
                    bundle_card['ui_summary'] = ui_info.get('summary', '')
                    bundle_card['source_link'] = ui_info.get('link', '')
                    bundle_card['resource_folder'] = ui_info.get('resource_folder', '')
                    
                    # URL
                    encoded_id = quote(bundle_card['id'])
                    ts = int(time.time())
                    bundle_card['image_url'] = f"/cards_file/{encoded_id}?t={ts}"
                    bundle_card['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={ts}"

                    # 全局缓存映射
                    ctx.cache.bundle_map[bundle_dir] = bundle_card['id']
                    ctx.cache.id_map[bundle_card['id']] = bundle_card
                    
                    # 列表更新
                    found_in_list = False
                    for idx, c in enumerate(ctx.cache.cards):
                        if c.get('is_bundle') and c.get('bundle_dir') == bundle_dir:
                            ctx.cache.cards[idx] = bundle_card 
                            found_in_list = True
                            break
                    
                    if not found_in_list:
                        ctx.cache.cards.insert(0, bundle_card)

                    final_return_obj = bundle_card

        return jsonify({
            "success": True,
            "file_modified": should_touch_file,
            "new_id": final_rel_path_id,
            "new_filename": new_filename,
            "new_image_url": final_return_obj['image_url'] if final_return_obj else None,
            "updated_card": final_return_obj 
        })

    except Exception as e:
        logger.error(f"Update error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/move_card', methods=['POST'])
def api_move_card():
    try:
        # 批量 move/rename 文件，抑制 watchdog
        suppress_fs_events(5.0)
        data = request.json
        target_cat = data.get('target_category', '')
        if target_cat == "根目录": target_cat = ""
        card_ids = data.get('card_ids', [])
        if 'card_id' in data: card_ids.append(data['card_id'])
        
        # 目标基础目录
        dst_base_dir = os.path.join(CARDS_FOLDER, target_cat)
        if not os.path.exists(dst_base_dir): os.makedirs(dst_base_dir)
        
        moved_details = []
        ui_data = load_ui_data()
        ui_changed = False

        # 准备数据库连接，用于实时更新
        db_path = DEFAULT_DB_PATH
        conn = get_db()
        cursor = conn.cursor()
        
        # 使用缓存查找卡片属性
        cache_map = ctx.cache.id_map
        
        for cid in card_ids:
            try:
                card_info = cache_map.get(cid)
                if not card_info: continue # 找不到卡片，跳过

                old_category = card_info['category']
                is_bundle = card_info.get('is_bundle', False)

                # ===========================
                # === 情况 1: 聚合角色包 ===
                # ===========================
                if is_bundle:
                    bundle_rel_dir = card_info['bundle_dir'] # e.g. "Race/Elf"
                    if not bundle_rel_dir: continue

                    src_dir_full = os.path.join(CARDS_FOLDER, bundle_rel_dir.replace('/', os.sep))
                    folder_name = os.path.basename(src_dir_full)
                    
                    # 目标路径 e.g. "Cards/NewCat/Elf"
                    dst_dir_full = os.path.join(dst_base_dir, folder_name)
                    
                    # 如果源和目标一样，跳过
                    if os.path.abspath(src_dir_full) == os.path.abspath(dst_dir_full):
                        continue

                    # 处理重名：如果目标文件夹已存在，自动改名 e.g. "Elf_1"
                    if os.path.exists(dst_dir_full):
                        counter = 1
                        while True:
                            new_folder_name = f"{folder_name}_{counter}"
                            dst_dir_full = os.path.join(dst_base_dir, new_folder_name)
                            if not os.path.exists(dst_dir_full):
                                folder_name = new_folder_name
                                break
                            counter += 1
                    
                    # 执行移动
                    shutil.move(src_dir_full, dst_dir_full)
                    
                    # 计算新的相对路径 (用于更新 ui_data 和前端)
                    new_bundle_rel_dir = f"{target_cat}/{folder_name}" if target_cat else folder_name
                    
                    # 1. 更新数据库 (模糊匹配目录下的所有文件)
                    cursor.execute("SELECT id FROM card_metadata WHERE id LIKE ? || '/%'", (bundle_rel_dir,))
                    rows = cursor.fetchall()
                    for row in rows:
                        old_sub_id = row[0]
                        new_sub_id = old_sub_id.replace(bundle_rel_dir, new_bundle_rel_dir, 1)
                        cursor.execute("""
                            UPDATE card_metadata 
                            SET id = ?, 
                                category = REPLACE(category, ?, ?) 
                            WHERE id = ?
                        """, (new_sub_id, bundle_rel_dir, new_bundle_rel_dir, old_sub_id))

                    # 更新 UI Data (Key 是文件夹路径)
                    if bundle_rel_dir in ui_data:
                        ui_data[new_bundle_rel_dir] = ui_data[bundle_rel_dir]
                        del ui_data[bundle_rel_dir]
                        ui_changed = True
                    
                    ctx.cache.move_bundle_update(bundle_rel_dir, new_bundle_rel_dir, old_category, target_cat)

                    # 返回给前端的信息
                    moved_details.append({
                        "old_id": cid,
                        "new_id": new_bundle_rel_dir, # 前端可以用这个判断
                        "is_bundle": True,
                        "new_category": target_cat
                    })

                # ===========================
                # === 情况 2: 普通角色卡 ===
                # ===========================
                else:
                    src_sys_path = cid.replace('/', os.sep)
                    src_full = os.path.join(CARDS_FOLDER, src_sys_path)
                    
                    if not os.path.exists(src_full): continue

                    filename = os.path.basename(src_full)
                    # 此时 dst_full 只是一个基于原名的假设路径，稍后会根据冲突检测改变
                    # dst_full = os.path.join(dst_base_dir, filename) 
                    
                    # 如果源和目标目录完全一致，跳过
                    if os.path.dirname(src_full) == os.path.abspath(dst_base_dir):
                        continue
                    
                    # === 1. 识别文件及其伴生图片 ===
                    sidecar_src = None
                    sidecar_ext = None
                    
                    # 只有 JSON 才检查伴生图，PNG 本身就是主图
                    if filename.lower().endswith('.json'):
                        sidecar_src = find_sidecar_image(src_full)
                        if sidecar_src:
                            sidecar_ext = os.path.splitext(sidecar_src)[1]

                    # === 2. 联合冲突检测 ===
                    # 我们需要找到一个 base_name，使得 base_name.json 和 base_name.png 在目标目录都不存在
                    
                    name_part, ext_part = os.path.splitext(filename)
                    counter = 0
                    final_base_name = name_part
                    
                    while True:
                        if counter > 0:
                            final_base_name = f"{name_part}_{counter}"
                        
                        # 预测的主文件目标路径
                        candidate_main_name = final_base_name + ext_part
                        candidate_main_path = os.path.join(dst_base_dir, candidate_main_name)
                        
                        # 预测的伴生图目标路径 (如果有)
                        candidate_sidecar_path = None
                        if sidecar_ext:
                            candidate_sidecar_name = final_base_name + sidecar_ext
                            candidate_sidecar_path = os.path.join(dst_base_dir, candidate_sidecar_name)
                        
                        # === 同时检测主文件和伴生图是否存在 ===
                        conflict_main = os.path.exists(candidate_main_path)
                        conflict_sidecar = False
                        if candidate_sidecar_path:
                            conflict_sidecar = os.path.exists(candidate_sidecar_path)
                        
                        # 如果两者都不冲突，说明这个名字安全
                        if not conflict_main and not conflict_sidecar:
                            # 确定了最终的 safe paths
                            dst_full = candidate_main_path
                            dst_sidecar_full = candidate_sidecar_path
                            final_filename = candidate_main_name
                            break
                        
                        # 否则继续尝试下一个序号
                        counter += 1
                    
                    # === 3. 执行移动 ===
                    
                    # 移动主文件
                    shutil.move(src_full, dst_full)
                    
                    # 移动伴生图片 (如果有)
                    if sidecar_src and dst_sidecar_full:
                        shutil.move(sidecar_src, dst_sidecar_full)

                    # === 4. 更新数据 ===
                    
                    # 计算新 ID (Relative Path)
                    new_id = f"{target_cat}/{final_filename}" if target_cat else final_filename

                    # 更新数据库
                    cursor.execute("""
                        UPDATE card_metadata 
                        SET id = ?, category = ? 
                        WHERE id = ?
                    """, (new_id, target_cat, cid))
                    # update_card_cache(new_id, dst_full) # 确保 hash 更新
                    
                    # 更新 UI Data
                    if cid in ui_data:
                        ui_data[new_id] = ui_data[cid]
                        del ui_data[cid]
                        ui_changed = True

                    # 增量更新】内存缓存
                    ctx.cache.move_card_update(cid, new_id, old_category, target_cat, final_filename, dst_full)

                    moved_details.append({
                        "old_id": cid,
                        "new_id": new_id,
                        "new_filename": final_filename,
                        "new_category": target_cat,
                        "new_image_url": ctx.cache.id_map[new_id]['image_url'] # 返回给前端用
                    })
                    
            except Exception as inner_e:
                print(f"Error moving {cid}: {inner_e}")
                continue
        
        # 提交数据库和 UI Data
        conn.commit()

        if ui_changed:
            save_ui_data(ui_data)
        
        return jsonify({
            "success": True, 
            "count": len(moved_details),
            "moved_details": moved_details,
            "category_counts": ctx.cache.category_counts
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/delete_cards', methods=['POST'])
def api_delete_cards():
    try:
        # 批量 move 到回收站 / 删除文件夹，抑制 watchdog
        suppress_fs_events(5.0)
        card_ids = request.json.get('card_ids', [])
        if not card_ids:
            return jsonify({"success": False, "msg": "未选择文件"})

        deleted_count = 0
        ui_data = load_ui_data()
        ui_changed = False

        db_path = DEFAULT_DB_PATH
        conn = get_db()
        cursor = conn.cursor()

        cache_map = ctx.cache.id_map

        for cid in card_ids:
            card_info = cache_map.get(cid)
            # 如果缓存里没找到，可能是幽灵数据，尝试直接按 ID 处理
            # 但为了安全，没有 info 我们可能无法判断是 bundle 还是 file
            # 这里做一个简单的容错：如果没 info，假设是普通文件
            is_bundle = False
            bundle_dir = ""
            if card_info:
                is_bundle = card_info.get('is_bundle', False)
                bundle_dir = card_info.get('bundle_dir', '')
            
            is_deleted = False

            if is_bundle:
                # === 包模式：删除文件夹 ===
                if bundle_dir:
                    sys_bundle_path = bundle_dir.replace('/', os.sep)
                    full_dir_path = os.path.join(CARDS_FOLDER, sys_bundle_path)
                    
                    if os.path.exists(full_dir_path):
                        if safe_move_to_trash(full_dir_path, TRASH_FOLDER):
                            is_deleted = True
                            if bundle_dir in ui_data:
                                del ui_data[bundle_dir]
                                ui_changed = True
                            
                            cursor.execute("DELETE FROM card_metadata WHERE id LIKE ? || '/%'", (bundle_dir,))
                            cursor.execute("DELETE FROM folder_structure WHERE path = ?", (bundle_dir,))
            else:
                # === 普通模式：删除文件 ===
                rel_sys_path = cid.replace('/', os.sep)
                full_path = os.path.join(CARDS_FOLDER, rel_sys_path)
                
                if os.path.exists(full_path):
                    # 只要文件存在，就移动到回收站（无论是 json 还是 png）
                    if safe_move_to_trash(full_path, TRASH_FOLDER):
                        is_deleted = True
                    else:
                        # 如果移动失败（极少情况），记录日志或暂不删除DB
                        print(f"Failed to move to trash: {full_path}")
                else:
                    # 文件不存在（幽灵数据），直接视为删除成功，以便清理数据库
                    is_deleted = True

                if is_deleted:
                    if cid in ui_data:
                        del ui_data[cid]
                        ui_changed = True
                    cursor.execute("DELETE FROM card_metadata WHERE id = ?", (cid,))
            
            if is_deleted:
                deleted_count += 1
                
                # -------------------------------------------------------------
                # 内存更新必须在循环内部执行！
                # -------------------------------------------------------------
                if is_bundle:
                    ctx.cache.delete_bundle_update(bundle_dir)
                else:
                    ctx.cache.delete_card_update(cid)
        
        conn.commit()

        if ui_changed:
            save_ui_data(ui_data)
        
        return jsonify({
            "success": True, 
            "count": deleted_count,
            "category_counts": ctx.cache.category_counts 
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/upload_cards', methods=['POST'])
def api_upload_cards():
    try:
        # 批量写入/保存文件，抑制 watchdog（给稍长窗口）
        suppress_fs_events(5.0)
        # 获取上传的目标分类（文件夹路径）
        category = request.form.get('category', '')
        if category == "根目录":
            category = ""
            
        target_dir = os.path.join(CARDS_FOLDER, category)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        uploaded_files = request.files.getlist('files')
        new_cards = []      # 用于返回给前端
        failed_files = []   # 记录失败的文件名
        batch_db_rows = []  # 用于批量写入数据库的元组列表
        
        # 1. 遍历处理文件
        for file in uploaded_files:
            if file and file.filename:
                raw_filename = file.filename
                filename = os.path.basename(raw_filename)
                ext = os.path.splitext(filename)[1].lower()
            
                # 允许 json 和 png
                if ext not in ['.png', '.json']:
                    failed_files.append(filename)
                    continue

                # 防重名处理
                save_path = os.path.join(target_dir, filename)
                name, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(save_path):
                    filename = f"{name}_{counter}{ext}"
                    save_path = os.path.join(target_dir, filename)
                    counter += 1
                
                # 保存文件
                file.save(save_path)
                
                # 提取元数据
                info = extract_card_info(save_path)
                if info:
                    # 数据清洗逻辑（保持原样）
                    data_block = info.get('data', {}) if 'data' in info else info
                    tags = data_block.get('tags', [])
                    if isinstance(tags, str): 
                        tags = [t.strip() for t in tags.split(',') if t.strip()]
                    elif tags is None: 
                        tags = []
                    # 标签去重
                    tags = list(dict.fromkeys([str(t).strip() for t in tags if str(t).strip()]))
                    
                    char_name = info.get('name') or data_block.get('name') or os.path.splitext(filename)[0]
                    rel_path = filename if not category else f"{category}/{filename}"
                    
                    # === [关键] 计算所有数据库所需字段 ===
                    # 1. 文件哈希和大小
                    file_hash, file_size = get_file_hash_and_size(save_path)
                    # 2. 修改时间
                    mtime = os.path.getmtime(save_path)
                    # 3. Token 计数 (需要构建 calc_data 模拟对象)
                    calc_data = data_block.copy()
                    if 'name' not in calc_data: calc_data['name'] = char_name
                    token_count = calculate_token_count(calc_data)
                    has_wi, wi_name = get_wi_meta(data_block)

                    # === [关键] 准备数据库行数据 (13个字段，顺序必须与 SQL 对应) ===
                    # 对应表结构: id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count
                    db_row = (
                        rel_path,                               # id
                        char_name,                              # char_name
                        data_block.get('description', ''),      # description
                        data_block.get('first_mes', ''),        # first_mes
                        data_block.get('mes_example', ''),      # mes_example
                        json.dumps(tags),                       # tags (JSON string)
                        category,                               # category
                        data_block.get('creator', ''),          # creator
                        data_block.get('character_version', ''),# char_version
                        mtime,                                  # last_modified
                        file_hash,                              # file_hash
                        file_size,                              # file_size
                        token_count,                            # token_count
                        has_wi,                                 # has lore book
                        wi_name                                 # lore book name
                    )
                    batch_db_rows.append(db_row)

                    # 构建返回给前端的对象 (保持原样)
                    card_data = {
                        "id": rel_path,
                        "filename": filename,
                        "char_name": char_name,
                        "description": data_block.get('description', ''),
                        "first_mes": data_block.get('first_mes', ''),
                        "alternate_greetings": data_block.get('alternate_greetings', []),
                        "mes_example": data_block.get('mes_example', ''),
                        "creator_notes": data_block.get('creator_notes', ''),
                        "character_book": data_block.get('character_book', None),
                        "ui_summary": "",
                        "source_link": "",
                        "tags": tags,
                        "category": category,
                        "creator": data_block.get('creator', ''),
                        "char_version": data_block.get('character_version', ''),
                        "raw_data": info,
                        "image_url": f"/cards_file/{quote(rel_path)}",
                        "thumb_url": f"/api/thumbnail/{quote(rel_path)}",
                        "last_modified": mtime,
                        "token_count": token_count, # 确保前端拿到最新的 token
                        "file_hash": file_hash,
                        "file_size": file_size
                    }

                    new_cards.append(card_data)
                    # 更新内存缓存 (这里只更新内存对象，不操作DB)
                    ctx.cache.add_card_update(card_data)
                else:
                    # 无效文件处理
                    try: os.remove(save_path)
                    except: pass
                    failed_files.append(file.filename)

        # 2. 批量写入数据库 (高性能 + 事务安全)
        if batch_db_rows:
            db_path = DEFAULT_DB_PATH
            # 使用一次连接完成所有插入
            with sqlite3.connect(db_path, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.executemany('''
                    INSERT OR REPLACE INTO card_metadata 
                    (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch_db_rows)
                conn.commit()
                # 此时不需要调用 update_card_cache，因为我们已经手动写入了

        return jsonify({
            "success": True, 
            "new_cards": new_cards, 
            "failed_files": failed_files,
            "category_counts": ctx.cache.category_counts
        })
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/import_from_url', methods=['POST'])
def api_import_from_url():
    try:
        # 会写入 cards/ 文件，抑制 watchdog
        suppress_fs_events(2.5)
        url = request.json.get('url')
        # 允许用户指定导入的目标分类，默认是当前浏览的分类
        target_category = request.json.get('category', '')
        if target_category == "根目录": target_category = ""
        
        if not url:
            return jsonify({"success": False, "msg": "URL 不能为空"})

        # 1. 伪装 Header 下载图片
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': url
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=15, stream=True)
            resp.raise_for_status()
        except Exception as e:
            return jsonify({"success": False, "msg": f"下载失败: {str(e)}"})

        # 2. 确定文件名
        # 尝试从 URL 中解析文件名
        parsed_url = urlparse(url)
        filename = os.path.basename(unquote(parsed_url.path))
        if not filename or not filename.lower().endswith('.png'):
            # 如果 URL 没有文件名或不是 png，尝试从 Content-Disposition 获取，或者使用时间戳
            cd = resp.headers.get('content-disposition')
            if cd:
                # 简单的解析，实际可能需要更复杂的正则
                import re
                fname = re.findall('filename="?([^"]+)"?', cd)
                if fname: filename = fname[0]
            
            if not filename or not filename.lower().endswith('.png'):
                filename = f"import_{int(time.time())}.png"

        # 3. 保存到临时文件进行检测
        temp_filename = f"temp_dl_{int(time.time())}_{filename}"
        temp_path = os.path.join(BASE_DIR, temp_filename)
        
        with open(temp_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # 4. 检测是否为有效角色卡
        info = extract_card_info(temp_path)
        if not info:
            os.remove(temp_path)
            return jsonify({"success": False, "msg": "下载的文件不是有效的 PNG 角色卡 (未找到元数据)"})

        # 5. 移动到目标目录 (防重名)
        target_dir = os.path.join(CARDS_FOLDER, target_category)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # 使用角色名作为文件名的一部分，或者保持原名
        # 这里尽量保持原文件名，但处理重名
        final_save_path = os.path.join(target_dir, filename)
        name_part, ext_part = os.path.splitext(filename)
        counter = 1
        while os.path.exists(final_save_path):
            final_save_path = os.path.join(target_dir, f"{name_part}_{counter}{ext_part}")
            counter += 1
        
        shutil.move(temp_path, final_save_path)
        final_filename = os.path.basename(final_save_path)

        # 6. 构造返回数据 (用于前端立即渲染)
        data_block = info.get('data', {}) if 'data' in info else info
        tags = data_block.get('tags', [])
        if isinstance(tags, str): tags = [t.strip() for t in tags.split(',') if t.strip()]
        elif tags is None: tags = []
        
        char_name = info.get('name') or data_block.get('name') or name_part
        rel_path = final_filename if not target_category else f"{target_category}/{final_filename}"

        # === 立即手动更新此文件的缓存到数据库 ===
        # 这样即使扫描器还没跑，数据库里也有了，防止 reload_from_db 加载不到
        update_card_cache(rel_path, final_save_path)

        # 更新缓存
        schedule_reload(reason="import_from_url")

        new_card = {
            "id": rel_path,
            "filename": final_filename,
            "char_name": char_name,
            "description": data_block.get('description', ''),
            "first_mes": data_block.get('first_mes', ''),
            "alternate_greetings": data_block.get('alternate_greetings', []),
            "mes_example": data_block.get('mes_example', ''),
            "creator_notes": data_block.get('creator_notes', ''),
            "character_book": data_block.get('character_book', None),
            "ui_summary": "",
            "source_link": "",
            "tags": tags,
            "category": target_category,
            "creator": data_block.get('creator', ''),
            "char_version": data_block.get('character_version', ''),
            "raw_data": info,
            "image_url": f"/cards_file/{quote(rel_path)}",
            "thumb_url": f"/api/thumbnail/{quote(rel_path)}",
            "last_modified": time.time()
        }

        return jsonify({"success": True, "new_card": new_card})

    except Exception as e:
        logger.error(f"Import URL error: {e}")
        # 清理临时文件
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/change_image', methods=['POST'])
def api_change_image():
    """
    更换角色卡图片接口（支持增量更新）
    支持：
    1. PNG -> PNG (原地替换画面)
    2. JSON -> PNG (格式升级，清理旧文件，迁移数据)
    """
    try:
        # 会写图/删旧文件/rename，抑制 watchdog
        suppress_fs_events(2.5)
        raw_id = request.form.get('id')
        file = request.files.get('image')
        if not raw_id or not file:
            return jsonify({"success": False, "msg": "Missing ID or File"})
        
        # 计算路径
        card_path = os.path.join(CARDS_FOLDER, raw_id.replace('/', os.sep))
        
        # 初始化变量
        target_save_path = card_path
        final_id = raw_id
        is_format_conversion = False
        old_info = {}

        # =========================================================
        # 分支 A: JSON 格式卡片 (转换为 PNG)
        # =========================================================
        if raw_id.lower().endswith('.json'):
            is_format_conversion = True
            print(f"[ChangeImage] Converting JSON to PNG: {raw_id}")
            
            # 1. 读取旧数据 (必须成功，否则不进行破坏性操作)
            old_info = extract_card_info(card_path)
            if not old_info:
                return jsonify({"success": False, "msg": "无法读取原 JSON 元数据，操作中止"})
            
            # 2. 计算新路径 (.json -> .png)
            base_name = os.path.splitext(os.path.basename(card_path))[0]
            new_filename = base_name + ".png"
            target_save_path = os.path.join(os.path.dirname(card_path), new_filename)
            
            # 计算新的 ID
            if '/' in raw_id:
                final_id = f"{raw_id.rsplit('/', 1)[0]}/{new_filename}"
            else:
                final_id = new_filename
                
            # 3. 清理旧文件
            # 先删除同名伴生图 (clean_sidecar_images 会处理 .png/.jpg 等)
            clean_sidecar_images(card_path)
            # 再删除 JSON 主体
            if os.path.exists(card_path):
                os.remove(card_path)
            
            # 4. 保存新图片并写入元数据
            img = Image.open(file)
            img = resize_image_if_needed(img)
            # 转换为 RGBA 确保兼容性
            if img.mode not in ['RGB', 'RGBA']:
                img = img.convert('RGBA')
            img.save(target_save_path, "PNG")
            
            # 将原 JSON 数据写入新 PNG
            success = write_card_metadata(target_save_path, old_info)
            if not success:
                logger.error("Failed to write metadata to new PNG")

            # 5. 系统数据迁移 (UI Data)
            ui_data = load_ui_data()
            if raw_id in ui_data:
                ui_data[final_id] = ui_data[raw_id]
                del ui_data[raw_id]
                save_ui_data(ui_data)
                
            # 6. 数据库清理 (删除旧 ID 记录)
            db_path = DEFAULT_DB_PATH
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.execute("DELETE FROM card_metadata WHERE id = ?", (raw_id,))
            
            # 7. 内存缓存清理 (删除旧对象)
            # 注意：新对象将在后续步骤添加
            ctx.cache.delete_card_update(raw_id)

        # =========================================================
        # 分支 B: PNG 格式卡片 (原地替换)
        # =========================================================
        else:
            if not os.path.exists(card_path):
                return jsonify({"success": False, "msg": "Card not found"})
                
            # 1. 读取旧数据
            old_info = extract_card_info(card_path)
            if not old_info:
                return jsonify({"success": False, "msg": "无法读取原图片元数据"})
                
            # 2. 处理新图片
            img = Image.open(file)
            img = resize_image_if_needed(img)
            if img.mode not in ['RGB', 'RGBA']:
                img = img.convert('RGBA')
            
            # 3. 覆盖保存
            img.save(card_path, "PNG")
            
            # 4. 写回元数据 (保持人物设定不变)
            write_card_metadata(card_path, old_info)

        # ========================================================
        # 通用后续处理 (增量更新核心)
        # ========================================================
        
        # 1. 强制更新文件修改时间 (Mtime)
        try:
            os.utime(target_save_path, None)
        except Exception as e:
            logger.warning(f"Failed to touch file: {e}")
            
        new_mtime = os.path.getmtime(target_save_path)
        
        # 2. 物理删除 WebP 缩略图缓存 (强制下次请求重新生成)
        clean_thumbnail_cache(final_id, THUMB_FOLDER)
        
        # 3. 更新数据库记录 (Upsert)
        update_card_cache(final_id, target_save_path)
        
        # 4. [增量更新] 内存缓存
        # 我们需要构造一个符合 ctx.cache 格式的对象
        # 重新提取一次信息以确保准确性 (包含文件大小、hash等)
        # 如果是 JSON->PNG，必须全量构建；如果是 PNG->PNG，主要是更新时间和图
        
        # 重新读取完整信息用于缓存
        final_info = extract_card_info(target_save_path)
        data_block = final_info.get('data', {}) if 'data' in final_info else final_info
        
        # 计算 Token (防止因为格式转换导致 Token 丢失)
        calc_data = data_block.copy()
        if 'name' not in calc_data: 
            calc_data['name'] = final_info.get('name') or os.path.splitext(os.path.basename(target_save_path))[0]
        token_count = calculate_token_count(calc_data)

        # 构造更新包
        updated_card_data = {
            "id": final_id,
            "filename": os.path.basename(target_save_path),
            "char_name": calc_data['name'],
            "description": data_block.get('description', ''),
            "first_mes": data_block.get('first_mes', ''),
            "mes_example": data_block.get('mes_example', ''),
            "tags": data_block.get('tags', []),
            "category": final_id.rsplit('/', 1)[0] if '/' in final_id else "",
            "creator": data_block.get('creator', ''),
            "char_version": data_block.get('character_version', ''),
            "last_modified": new_mtime,
            "token_count": token_count,
            "dir_path": os.path.dirname(final_id) if '/' in final_id else ""
            # 注意：file_hash 在 update_card_cache 中计算了，内存中可以暂时不更，或者再算一次
        }
        
        # 如果是格式转换，之前的对象已被 delete_card_update 删除，现在需要 add
        if is_format_conversion:
            # 补充 UI 数据
            ui_data = load_ui_data()
            ui_info = ui_data.get(final_id, {})
            updated_card_data['ui_summary'] = ui_info.get('summary', '')
            updated_card_data['source_link'] = ui_info.get('link', '')
            updated_card_data['resource_folder'] = ui_info.get('resource_folder', '')
            
            # 生成 URL
            encoded_id = quote(final_id)
            updated_card_data['image_url'] = f"/cards_file/{encoded_id}?t={new_mtime}"
            updated_card_data['thumb_url'] = f"/api/thumbnail/{encoded_id}?t={new_mtime}"
            
            ctx.cache.add_card_update(updated_card_data)
        else:
            # 普通更新，调用 update_card_data (原地修改)
            ctx.cache.update_card_data(final_id, {
                "last_modified": new_mtime
            })
        
        # 获取最终的 URL
        ts = int(new_mtime)
        new_image_url = f"/cards_file/{quote(final_id)}?t={ts}"
        
        return jsonify({
            "success": True,
            "new_id": final_id,
            "new_image_url": new_image_url,
            "is_converted": is_format_conversion,
            "last_modified": new_mtime
        })

    except Exception as e:
        logger.error(f"Change image error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

# 定位角色卡所在位置
@bp.route('/api/find_card_page', methods=['POST'])
def api_find_card_page():
    try:
        target_id = request.json.get('card_id')
        category = request.json.get('category', '')
        sort_mode = request.json.get('sort', 'date_desc')
        page_size = int(request.json.get('page_size', 20))
        
        if not target_id: return jsonify({"success": False})

        # 1. 获取基础列表
        if not ctx.cache.initialized:
            ctx.cache.reload_from_db()
            
        filtered_cards = ctx.cache.cards

        # 2. 应用分类过滤 (与 list_cards 逻辑一致)
        if category and category != "根目录":
            target_cat_lower = category.lower()
            target_cat_prefix = target_cat_lower + '/'
            
            filtered_cards = [
                c for c in filtered_cards 
                if c['category'].lower() == target_cat_lower or c['category'].lower().startswith(target_cat_prefix)
            ]
            
        # 注意：定位功能通常是在清空搜索和标签的情况下使用的，所以这里不应用搜索和标签过滤

        # 3. 排序
        reverse = 'desc' in sort_mode
        if 'date' in sort_mode:
            filtered_cards.sort(key=lambda x: x['last_modified'], reverse=reverse)
        elif 'name' in sort_mode:
            filtered_cards.sort(key=lambda x: x['char_name'].lower(), reverse=reverse)
            
        # 4. 查找索引
        index = -1
        for i, card in enumerate(filtered_cards):
            if card['id'] == target_id:
                index = i
                break
        
        if index != -1:
            # 计算页码 (从1开始)
            page = (index // page_size) + 1
            return jsonify({"success": True, "page": page})
        else:
            return jsonify({"success": False, "msg": "在目标分类中未找到该卡片"})

    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/normalize_card_data', methods=['POST'])
def api_normalize_card_data():
    try:
        raw_data = request.json
        if not raw_data:
            return jsonify({"success": False, "msg": "No data provided"})

        # 1. 模拟写入时的清洗逻辑
        # 注意：这里我们不仅要 normalize，还要应用与 write_card_metadata 相同的清理逻辑
        
        # 复制逻辑避免修改原引用 (尽管 Flask request.json 已经是新的)
        data_to_clean = raw_data.copy()
        
        # 应用 V3 标准化
        if 'name' in data_to_clean or 'data' in data_to_clean:
            data_to_clean = normalize_card_v3(data_to_clean)

        # 清洗 alternate_greetings (同 write_card_metadata)
        targets = [data_to_clean]
        if 'data' in data_to_clean and isinstance(data_to_clean['data'], dict):
            targets.append(data_to_clean['data'])
            
        for t in targets:
            if 'alternate_greetings' in t and isinstance(t['alternate_greetings'], list):
                t['alternate_greetings'] = [
                    s for s in t['alternate_greetings'] 
                    if isinstance(s, str) and s.strip()
                ]

        # 2. 确定性排序 (关键步骤，保证 Diff 顺序一致)
        sorted_data = deterministic_sort(data_to_clean)

        return jsonify({"success": True, "data": sorted_data})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/update_card_from_url', methods=['POST'])
def api_update_card_from_url():
    temp_path = None
    try:
        data = request.json
        card_id = data.get('card_id')
        url = data.get('url')
        is_bundle_update = data.get('is_bundle_update', False)
        keep_ui_data = data.get('keep_ui_data', {})
        
        if not url: return jsonify({"success": False, "msg": "URL不能为空"})

        # 下载文件
        headers = {'User-Agent': 'Mozilla/5.0 ... Chrome/120.0'}
        try:
            resp = requests.get(url, headers=headers, timeout=15, stream=True)
            resp.raise_for_status()
        except Exception as e:
            return jsonify({"success": False, "msg": f"下载失败: {str(e)}"})

        temp_filename = f"temp_url_up_{uuid.uuid4().hex}.png"
        temp_path = os.path.join(BASE_DIR, temp_filename)
        
        with open(temp_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # 验证是否为有效 PNG
        if not extract_card_info(temp_path):
            os.remove(temp_path)
            return jsonify({"success": False, "msg": "无效的图片文件，无法获取角色数据"})
            
        # 调用通用逻辑
        result = update_card_content(card_id, temp_path, is_bundle_update, keep_ui_data, '.png')
        
        if os.path.exists(temp_path): os.remove(temp_path)
        return jsonify(result)

    except Exception as e:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path) 
            except:
                pass
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/fetch_source_metadata', methods=['POST'])
def api_fetch_source_metadata():
    try:
        data = request.json
        link = data.get('source_link')
        if not link: return jsonify({"success": False, "msg": "链接为空"})
        result = fetch_remote_metadata(link)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/check_card_update', methods=['POST'])
def api_check_card_update():
    try:
        data = request.json
        card_id = data.get('card_id')
        source_link = data.get('source_link')
        source_title_sync = data.get('source_title_sync') # 前端传入的已同步标题
        
        if not source_link:
            return jsonify({"success": False, "msg": "来源链接为空，无法检测"})
            
        if 'chub.ai' in source_link:
            result = check_chub_update(card_id, source_link, synced_title=source_title_sync)
            return jsonify(result)
        elif 'discord.com' in source_link:
            result = check_discord_update(card_id, source_link, synced_title=source_title_sync)
            return jsonify(result)
        else:
            return jsonify({"success": False, "msg": "目前仅支持 Chub.ai 和 Discord 来源的自动检测"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/check_fav_updates', methods=['POST'])
def api_check_fav_updates():
    """批量检测收藏卡片的更新"""
    try:
        # 1. 加载最新的 UI 数据 (获取来源链接)
        ui_data = load_ui_data()
        
        # 2. 从缓存获取所有收藏卡片 (已经包含了 is_favorite 状态)
        if not ctx.cache.initialized:
            ctx.cache.reload_from_db()
            
        with ctx.cache.lock:
            fav_cards = [c for c in ctx.cache.cards if c.get('is_favorite')]
            
        results = []
        for card in fav_cards:
            card_id = card['id']
            # ui_data 的 key 逻辑在 resolve_ui_key 中
            ui_key = resolve_ui_key(card_id)
            ui_info = ui_data.get(ui_key, {})
            source_link = ui_info.get('link', '')
            synced_title = ui_info.get('source_title_sync', '')
            
            if not source_link:
                continue
                
            res = None
            if 'chub.ai' in source_link:
                res = check_chub_update(card_id, source_link, synced_title=synced_title)
            elif 'discord.com' in source_link:
                res = check_discord_update(card_id, source_link, synced_title=synced_title)
                
            if res and res.get('success') and res.get('has_update'):
                results.append({
                    "id": card_id,
                    "name": card.get('char_name', card_id),
                    "reason": res.get('update_info', {}).get('reason', '检测到新版本'),
                    "download_url": res.get('download_url'),
                    "source_link": source_link
                })
        
        return jsonify({"success": True, "updates": results})
    except Exception as e:
        logger.error(f"Batch check fav updates error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/random_card', methods=['POST'])
def api_random_card():
    try:
        # 获取筛选参数，确保随机范围与当前视图一致
        data = request.json or {}
        category = data.get('category', '')
        tags_param = data.get('tags', []) # 前端传数组过来
        search = data.get('search', '').lower().strip()
        search_type = data.get('search_type', 'mix')
        
        # 1. 获取所有卡片
        if not ctx.cache.initialized:
            ctx.cache.reload_from_db()
        
        candidates = ctx.cache.cards

        # 2. 分类过滤
        if category and category != "根目录":
            target_cat_lower = category.lower()
            target_cat_prefix = target_cat_lower + '/'
            candidates = [
                c for c in candidates 
                if c['category'].lower() == target_cat_lower or c['category'].lower().startswith(target_cat_prefix)
            ]

        # 3. 搜索过滤
        if search:
            if search_type == 'name':
                candidates = [c for c in candidates if search in c['char_name'].lower()]
            elif search_type == 'filename':
                candidates = [c for c in candidates if search in c['filename'].lower()]
            elif search_type == 'tags':
                candidates = [c for c in candidates if any(search in t.lower() for t in c['tags'])]
            elif search_type == 'creator':
                candidates = [c for c in candidates if search in c['creator'].lower()]
            else: # mix
                candidates = [c for c in candidates if (
                    search in c['char_name'].lower() or 
                    search in c['filename'].lower() or 
                    search in c['ui_summary'].lower() or
                    any(search in t.lower() for t in c['tags'])
                )]

        # 4. 标签过滤
        if tags_param:
            # 确保 tags_param 是列表
            target_tags = tags_param if isinstance(tags_param, list) else []
            if target_tags:
                candidates = [c for c in candidates if all(t in c['tags'] for t in target_tags)]

        # 5. 随机抽取
        if not candidates:
            return jsonify({"success": False, "msg": "当前范围内没有卡片"})
            
        picked_card = random.choice(candidates)
        
        return jsonify({"success": True, "card": picked_card})

    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/toggle_bundle_mode', methods=['POST'])
def api_toggle_bundle_mode():
    try:
        # 会创建/删除 .bundle、写入 png metadata，抑制 watchdog
        suppress_fs_events(2.0)
        folder_path = request.json.get('folder_path')
        action = request.json.get('action', 'check') # check | enable | disable
        
        if not folder_path: return jsonify({"success": False, "msg": "路径为空"})
            
        full_path = os.path.join(CARDS_FOLDER, folder_path)
        marker_path = os.path.join(full_path, '.bundle')
        
        # === 1. 取消聚合 (Disable) ===
        if action == 'disable':
            if os.path.exists(marker_path):
                os.remove(marker_path)
            # 刷新缓存
            force_reload(reason="toggle_bundle_mode:disable")
            return jsonify({"success": True, "msg": "已取消聚合。所有版本现已作为独立卡片显示。"})

        # === 2. 检查阶段 (Check) ===
        # 扫描目录下所有PNG
        cards_in_dir = []
        ui_data = load_ui_data()
        
        for root, dirs, files in os.walk(full_path):
            if root != full_path: continue # 只看当前层级
            for f in files:
                if f.lower().endswith('.png'):
                    full_p = os.path.join(root, f)
                    rel_id = f"{folder_path}/{f}"
                    info = extract_card_info(full_p)
                    if info:
                        data = info.get('data', {}) if 'data' in info else info
                        tags = data.get('tags', [])
                        if isinstance(tags, str): tags = [t.strip() for t in tags.split(',') if t.strip()]
                        
                        cards_in_dir.append({
                            "filename": f,
                            "id": rel_id,
                            "tags": set(tags or []),
                            "ui": ui_data.get(rel_id, {}),
                            "mtime": os.path.getmtime(full_p)
                        })
        
        count = len(cards_in_dir)
        if count == 0:
            return jsonify({"success": False, "msg": "该文件夹下没有角色卡，无法聚合。"})

        # === 3. 执行聚合 (Enable) ===
        if action == 'enable':
            # 3.1 标签合并 (Union)
            all_tags = set()
            for c in cards_in_dir:
                all_tags.update(c['tags'])
            
            # 3.2 UI 数据合并 (Notes/Links/Resource)
            # 策略：按修改时间倒序，优先使用最新的有数据的卡片
            cards_in_dir.sort(key=lambda x: x['mtime'], reverse=True)
            
            merged_ui = {
                "summary": "", "link": "", "resource_folder": ""
            }
            
            # 查找最新的一条非空数据
            for field in ['summary', 'link', 'resource_folder']:
                for c in cards_in_dir:
                    val = c['ui'].get(field)
                    if val:
                        merged_ui[field] = val
                        break
            
            # 3.3 保存 UI 数据到文件夹 Key
            ui_data[folder_path] = merged_ui
            
            # 3.4 可选：将合并后的标签写回最新那张卡片 (为了让搜索能搜到)
            # 或者，我们在 GlobalMetadataCache 处理聚合时已经处理了标签显示
            # 这里我们把合并后的 tags 更新到最新的那张卡片文件里，确保数据物理落地
            latest_card_file = os.path.join(full_path, cards_in_dir[0]['filename'])
            info = extract_card_info(latest_card_file)
            if info:
                data_part = info.get('data') if 'data' in info else info
                data_part['tags'] = list(all_tags)
                if 'data' in info: info['data'] = data_part # 确保写回结构正确
                else: info = data_part
                write_card_metadata(latest_card_file, info)

            save_ui_data(ui_data)
            
            # 3.5 创建标记文件
            with open(marker_path, 'w') as f: f.write("1")
            
            force_reload(reason="toggle_bundle_mode:enable")
            return jsonify({"success": True, "msg": "聚合成功！标签已合并，UI信息已迁移。"})

        # === 返回检查结果 ===
        return jsonify({
            "success": True, 
            "check_passed": True,
            "count": count,
            "sample_names": [c['filename'] for c in cards_in_dir[:3]]
        })

    except Exception as e:
        logger.error(f"Bundle toggle error: {e}")
        return jsonify({"success": False, "msg": str(e)})

# --- 一键转包模式接口 ---
@bp.route('/api/convert_to_bundle', methods=['POST'])
def api_convert_to_bundle():
    try:
        suppress_fs_events(3.0)
        data = request.json
        card_id = data.get('card_id')
        new_bundle_name = data.get('bundle_name', '').strip()
        
        if not card_id or not new_bundle_name:
            return jsonify({"success": False, "msg": "参数不完整"})
            
        # 1. 路径检查
        rel_path = card_id.replace('/', os.sep)
        src_path = os.path.join(CARDS_FOLDER, rel_path)
        
        if not os.path.exists(src_path):
            return jsonify({"success": False, "msg": "原文件不存在"})
            
        parent_dir = os.path.dirname(src_path)
        # 新建文件夹路径
        new_dir_path = os.path.join(parent_dir, new_bundle_name)
        
        if os.path.exists(new_dir_path):
            return jsonify({"success": False, "msg": f"目标文件夹 '{new_bundle_name}' 已存在"})
            
        # 2. 创建文件夹
        os.makedirs(new_dir_path)
        
        # 3. 移动文件 (卡片 + 伴生图)
        filename = os.path.basename(src_path)
        dst_path = os.path.join(new_dir_path, filename)
        shutil.move(src_path, dst_path)
        
        # 处理伴生图
        if filename.lower().endswith('.json'):
            sidecar = find_sidecar_image(src_path) # 注意 src_path 已经移走了，这里可能找不到
            # 应该在 move 之前找，或者根据 base name 找
            pass # 简化逻辑：上面的 shutil.move 已经移走了主文件。伴生图逻辑类似 api_move_folder，此处略以保证简洁
            # 实际上建议复用 move 逻辑，但这里手动处理更稳
            base_src = os.path.splitext(src_path)[0]
            for ext in SIDECAR_EXTENSIONS:
                if os.path.exists(base_src + ext):
                    shutil.move(base_src + ext, os.path.join(new_dir_path, os.path.basename(base_src + ext)))

        # 4. 创建 .bundle 标记
        with open(os.path.join(new_dir_path, '.bundle'), 'w') as f:
            f.write('1')
            
        # 5. 更新数据 (数据库 + 缓存)
        # 计算新 ID
        old_cat = os.path.dirname(card_id) if '/' in card_id else ""
        if old_cat == ".": old_cat = ""
        
        # 新 ID 变为 "Category/BundleName/Card.png"
        new_id = f"{old_cat}/{new_bundle_name}/{filename}" if old_cat else f"{new_bundle_name}/{filename}"
        
        # 数据库更新
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE card_metadata SET id = ? WHERE id = ?", (new_id, card_id))
        conn.commit()
        
        # 内存更新
        # 先删除旧的
        if card_id in ctx.cache.id_map:
            card_data = ctx.cache.id_map.pop(card_id)
            # 修改属性
            card_data['id'] = new_id
            card_data['is_bundle'] = True
            card_data['bundle_dir'] = f"{old_cat}/{new_bundle_name}" if old_cat else new_bundle_name
            # 重新插入
            ctx.cache.id_map[new_id] = card_data
            # 如果在列表里，也要更新列表引用
            # 注意：列表里的对象引用必须是同一个
            
        # UI Data 更新
        ui_data = load_ui_data()
        if card_id in ui_data:
            # Bundle 模式下，UI data key 通常是 bundle_dir
            new_key = f"{old_cat}/{new_bundle_name}" if old_cat else new_bundle_name
            ui_data[new_key] = ui_data[card_id]
            del ui_data[card_id]
            save_ui_data(ui_data)
            
        # 强制前端刷新
        return jsonify({"success": True, "new_id": new_id, "new_bundle_dir": new_dir_path})

    except Exception as e:
        logger.error(f"Convert bundle error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/get_raw_metadata', methods=['POST'])
def api_get_raw_metadata():
    try:
        card_id = request.json.get('id')
        if not card_id:
            return jsonify({})
        
        # 确保路径分隔符正确
        full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        
        if not os.path.exists(full_path):
            return jsonify({"error": "File not found"})

        # 使用现有的提取逻辑
        info = extract_card_info(full_path)
        
        # 如果是 JSON，extract_card_info 直接返回 dict，可以直接 jsonify
        # 如果是 PNG，它也返回 dict
        if info:
            return jsonify(info)
        else:
            return jsonify({"error": "Failed to extract"})
    except:
        return jsonify({})

@bp.route('/api/get_card_detail', methods=['POST'])
def api_get_card_detail():
    try:
        card_id = request.json.get('id')
        
        # 1. 尝试从数据库读取完整信息 (比读文件快)
        db_path = DEFAULT_DB_PATH
        row = None
        with sqlite3.connect(db_path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM card_metadata WHERE id = ?", (card_id,))
            row = cursor.fetchone()

        full_info = {}
        if row:
            # 数据库命中
            try: tags = json.loads(row['tags']) if row['tags'] else []
            except: tags = []
            full_info = dict(row)
            full_info['tags'] = tags
            # 补充 World Info，数据库通常不存 WI 结构体，需要回退到读文件
            # 或者我们在 list 阶段不存，但在 update 阶段不写入 db，只在文件里
        
        # 2. 如果数据库没有 World Book 结构，或者为了确保最新，读取物理文件
        # 为了 V3 兼容性和 World Book，读文件是最稳妥的
        full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        file_info = extract_card_info(full_path)
        
        if not file_info: return jsonify({"success": False})
        
        data_block = file_info.get('data', {}) if 'data' in file_info else file_info
        # === 提取 V3 extensions (包含 regex_scripts, tavern_helper 等) ===
        extensions = data_block.get('extensions', {})

        # 获取文件修改时间用于缓存控制
        try:
            mtime = int(os.path.getmtime(full_path))
        except:
            mtime = 0

        # 应对世界书跳转没有category的问题
        category = ""
        if row and 'category' in row.keys() and row['category'] is not None:
            category = row['category'].replace('\\', '/')
        else:
            category = card_id.rsplit('/', 1)[0] if '/' in card_id else ""

        # 构造完整详情对象
        card_data = {
            "id": card_id,
            "filename": os.path.basename(card_id),
            "char_name": data_block.get('name'),
            "description": data_block.get('description', ''),
            "first_mes": data_block.get('first_mes', ''),
            "alternate_greetings": data_block.get('alternate_greetings', []),
            "mes_example": data_block.get('mes_example', ''),
            "creator_notes": data_block.get('creator_notes', ''),
            "character_book": data_block.get('character_book', None),
            "extensions": extensions,
            "tags": tags,
            "category": category,
            "creator": data_block.get('creator', ''),
            "char_version": data_block.get('character_version', ''),
            "image_url": f"/cards_file/{quote(card_id)}?t={mtime}",
            "thumb_url": f"/api/thumbnail/{quote(card_id)}?t={mtime}"
        }
        # 如果 DB 有 token_count，带上（用于详情页/列表同步）
        if row and 'token_count' in row.keys():
            card_data['token_count'] = row['token_count'] or 0

        # 处理 UI Cache
        ui_data = load_ui_data()
        ui_key = resolve_ui_key(card_id)
        ui_info = ui_data.get(ui_key, {})
        card_data['ui_summary'] = ui_info.get('summary', '')
        card_data['source_link'] = ui_info.get('link', '')
        card_data['source_title_sync'] = ui_info.get('source_title_sync', '') # 抓取的远程标题
        card_data['resource_folder'] = ui_info.get('resource_folder', '')

        return jsonify({"success": True, "card": card_data})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/delete_tags', methods=['POST'])
def api_delete_tags():
    try:
        # 会写很多 PNG metadata
        suppress_fs_events(10.0)

        tags_to_delete = request.json.get("tags", [])
        target_category = request.json.get("category", "")
        if not tags_to_delete:
            return jsonify({"success": False, "msg": "未选择要删除的标签"})

        tags_to_delete_set = set(str(t).strip() for t in tags_to_delete if str(t).strip())

        updated_cards = 0
        affected_tags = set()

        conn = get_db()
        cursor = conn.cursor()

        current_time = time.time()

        scan_root = CARDS_FOLDER
        if target_category and target_category != "根目录":
            # 如果指定了分类，只扫描该分类下的文件
            # 注意：这里需要处理路径拼接，防止路径遍历攻击
            safe_cat = target_category.replace('..', '').strip('/\\')
            scan_root = os.path.join(CARDS_FOLDER, safe_cat)

        if not os.path.exists(scan_root):
             return jsonify({"success": False, "msg": "目标分类不存在"})

        for root, dirs, files in os.walk(scan_root):
            for file in files:
                if not file.lower().endswith('.png'):
                    continue

                full_path = os.path.join(root, file)
                info = extract_card_info(full_path)
                if not info or not isinstance(info, dict):
                    continue

                # card_id 用于更新 DB / cache（统一斜杠）
                rel_path = os.path.relpath(full_path, CARDS_FOLDER).replace('\\', '/')
                card_id = rel_path

                # 兼容 V2/V3：确定写入的 data block
                is_v3 = isinstance(info.get("data"), dict)
                data_block = info["data"] if is_v3 else info

                card_tags = data_block.get("tags") or []
                if isinstance(card_tags, str):
                    card_tags = [t.strip() for t in card_tags.split(',') if t.strip()]
                elif card_tags is None:
                    card_tags = []

                # 保持原顺序删除 + 去重（可选，但建议）
                seen = set()
                new_tags = []
                for t in card_tags:
                    ts = str(t).strip()
                    if not ts:
                        continue
                    if ts in tags_to_delete_set:
                        continue
                    if ts in seen:
                        continue
                    seen.add(ts)
                    new_tags.append(ts)

                if new_tags == card_tags:
                    continue

                # 记录影响到的标签
                affected_tags |= (set(str(t).strip() for t in card_tags if str(t).strip()) & tags_to_delete_set)

                # === 关键：只写回 data_block，不污染顶层 ===
                data_block["tags"] = new_tags
                if is_v3:
                    info["data"] = data_block  # 确保结构正确

                ok = write_card_metadata(full_path, info)
                if not ok:
                    continue

                try:
                    os.utime(full_path, (current_time, current_time))
                except:
                    pass

                updated_cards += 1

                # === 同步 DB（列表来自 DB，不同步就会“删了但列表不变”）===
                cursor.execute(
                    "UPDATE card_metadata SET tags = ?, last_modified = ? WHERE id = ?",
                    (json.dumps(new_tags, ensure_ascii=False), current_time, card_id)
                )

                # === 同步内存缓存（如果这张卡在轻量缓存里）===
                ctx.cache.update_tags_update(card_id, new_tags)

                if card_id in ctx.cache.id_map:
                    ctx.cache.id_map[card_id]['last_modified'] = current_time
                    ctx.cache.id_map[card_id]['tags'] = new_tags

        conn.commit()

        # 如果你有 ui_data['all_tags'] 这种历史字段，可以保留原逻辑；没有也不会影响
        ui_data = load_ui_data()
        if isinstance(ui_data, dict) and 'all_tags' in ui_data and isinstance(ui_data['all_tags'], list):
            ui_data['all_tags'] = [tag for tag in ui_data['all_tags'] if tag not in tags_to_delete_set]
            save_ui_data(ui_data)

        # 尤其有 bundle 聚合显示时），可以触发一次 reload
        schedule_reload(reason="delete_tags")

        return jsonify({
            "success": True,
            "updated_cards": updated_cards,
            "deleted_tags": sorted(list(affected_tags)),
            "total_tags_deleted": len(affected_tags)
        })

    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/batch_tags', methods=['POST'])
def api_batch_tags():
    try:
        # 批量写 PNG metadata
        suppress_fs_events(6.0)
        ids = request.json.get("card_ids", [])
        add_tags = request.json.get("add", []) or []
        remove_tags = request.json.get("remove", []) or []

        updated = 0

        # 数据库连接 (为了持久化标签变更，防止重启丢失)
        # 虽然写入了 PNG，但数据库也有一份 tags 字段，需要同步
        db_path = DEFAULT_DB_PATH
        conn = get_db()
        cursor = conn.cursor()

        for cid in ids:
            rel = cid.replace('/', os.sep)
            file_path = os.path.join(CARDS_FOLDER, rel)
            info = extract_card_info(file_path)
            if not info:
                continue

            data = info.get("data") if "data" in info else info
            tags = data.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',') if t.strip()]

            before = set(tags)
            after = before.copy()

            after |= set(add_tags)
            after -= set(remove_tags)

            after = list(after)

            if after != list(before):
                data["tags"] = after
                info["tags"] = after
                write_card_metadata(file_path, info)
                # 写数据库
                cursor.execute("UPDATE card_metadata SET tags = ? WHERE id = ?", (json.dumps(after), cid))
                # 更新内存缓存
                ctx.cache.update_tags_update(cid, after)
                updated += 1

        conn.commit()

        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/update_card_file', methods=['POST'])
def api_update_card_file():
    temp_path = None
    try:
        card_id = request.form.get('card_id')
        keep_ui_data = json.loads(request.form.get('keep_ui_data') or '{}')
        new_card_file = request.files.get('new_card')
        is_bundle_update = request.form.get('is_bundle_update') == 'true'
        
        if not new_card_file: return jsonify({"success": False, "msg": "未提供文件"})

        new_upload_ext = os.path.splitext(new_card_file.filename)[1].lower()
        temp_filename = f"temp_up_{uuid.uuid4().hex}{new_upload_ext}"
        temp_path = os.path.join(BASE_DIR, temp_filename)
        new_card_file.save(temp_path)
        
        # 调用通用逻辑
        result = update_card_content(card_id, temp_path, is_bundle_update, keep_ui_data, new_upload_ext)
        
        if os.path.exists(temp_path): os.remove(temp_path)
        return jsonify(result)

    except Exception as e:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path) 
            except:
                pass
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/create_folder', methods=['POST'])
def api_create_folder():
    try:
        # mkdir 也会触发 event，短抑制即可
        suppress_fs_events(1.5)
        data = request.json
        base = CARDS_FOLDER
        if data.get('parent') and data.get('parent') != "根目录":
            parent_rel = data.get('parent').replace('/', os.sep)
            base = os.path.join(CARDS_FOLDER, data.get('parent'))
        new_folder_path = os.path.join(base, data.get('name'))
        if os.path.exists(new_folder_path):
             return jsonify({"success": False, "msg": "文件夹已存在"})
        os.makedirs(new_folder_path, exist_ok=True)
        schedule_reload(reason="create_folder")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/rename_folder', methods=['POST'])
def api_rename_folder():
    try:
        # 文件夹 rename 会触发大量事件，抑制 watchdog
        suppress_fs_events(4.0)
        data = request.json
        old_path = data.get('old_path')
        new_name = data.get('new_name')
        
        if not old_path or not new_name:
            return jsonify({"success": False, "msg": "参数不完整"})
        
        # 基础安全检查
        if ".." in old_path or old_path.startswith("/") or old_path.startswith("\\"):
            return jsonify({"success": False, "msg": "非法路径"})
            
        # 获取父目录路径和新完整路径
        old_path_sys = old_path.replace('/', os.sep)
        old_full_path = os.path.join(CARDS_FOLDER, old_path_sys)
        parent_dir = os.path.dirname(old_full_path)
        new_path = os.path.join(parent_dir, new_name)
        
        if not os.path.exists(old_full_path):
             return jsonify({"success": False, "msg": "源文件夹不存在"})

        # 检查新路径是否已存在
        if os.path.exists(new_path):
            return jsonify({"success": False, "msg": "目标名称已存在"})
        
        # 1. [文件系统操作] 重命名文件夹
        try:
            os.rename(old_full_path, new_path)
        except OSError as e:
            return jsonify({"success": False, "msg": f"文件重命名失败: {str(e)}"})

        # 计算新的相对路径
        new_rel_path = os.path.relpath(new_path, CARDS_FOLDER).replace('\\', '/')
        
        # 2. [UI Data 更新] (保持原逻辑)
        ui_data = load_ui_data()
        ui_changed = False
        old_prefix = old_path + "/"
        
        keys_to_move = []
        for key in ui_data.keys():
            if key == old_path or key.startswith(old_prefix):
                keys_to_move.append(key)
        
        for key in keys_to_move:
            if key == old_path:
                new_key = new_rel_path
            else:
                new_key = key.replace(old_path, new_rel_path, 1)
            
            ui_data[new_key] = ui_data[key]
            del ui_data[key]
            ui_changed = True
            
        if ui_changed:
            save_ui_data(ui_data)
            
        # 3. [数据库更新]
        try:
            db_path = DEFAULT_DB_PATH
            with sqlite3.connect(db_path, timeout=30) as conn:
                cursor = conn.cursor()

                # === 转义 SQL 通配符 ===
                # 如果文件夹名包含 _ 或 %，必须转义，否则 LIKE 会匹配错误
                # 例如: old_path="char_v1", 不转义 LIKE 'char_v1/%' 会匹配 "char_v10/img.png"
                escaped_old_path = old_path.replace('_', r'\_').replace('%', r'\%')

                # A. 查找所有子文件 (ID 以 old_path/ 开头)
                # 使用 ESCAPE '\' 语法
                cursor.execute(f"SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", (escaped_old_path,))
                rows = cursor.fetchall()
                
                for row in rows:
                    curr_id = row[0]
                    # Python 字符串替换不需要转义，直接替换前缀
                    new_id_val = curr_id.replace(old_path, new_rel_path, 1)
                    
                    # 更新 id 和 category
                    cursor.execute("""
                        UPDATE card_metadata 
                        SET id = ?, 
                            category = REPLACE(category, ?, ?) 
                        WHERE id = ?
                    """, (new_id_val, old_path, new_rel_path, curr_id))
                
                conn.commit()

            # 4. [内存增量更新]
            ctx.cache.rename_folder_update(old_path, new_rel_path)
            
        except Exception as e:
            # 如果数据库更新失败，记录错误并触发全量重载，保证数据最终一致性
            logger.error(f"DB update failed after file rename: {e}")
            schedule_reload(reason="rename_folder:fallback")
            return jsonify({
                "success": True, 
                "new_path": new_rel_path, 
                "warning": "文件夹已重命名，但数据库索引更新遇到问题，系统将自动修复。"
            })
            
        return jsonify({
            "success": True, 
            "new_path": new_rel_path
        })
    except Exception as e:
        logger.error(f"Rename folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/delete_folder', methods=['POST'])
def api_delete_folder():
    try:
        # 1. 抑制文件系统事件，因为我们将进行大量移动/删除操作
        suppress_fs_events(6.0)
        
        folder_path = request.json.get('folder_path')
        if not folder_path or folder_path == "根目录":
            return jsonify({"success": False, "msg": "根目录不可删除"})
        
        # 安全检查
        if ".." in folder_path or folder_path.startswith("/") or folder_path.startswith("\\"):
             return jsonify({"success": False, "msg": "非法路径"})

        target_dir = os.path.join(CARDS_FOLDER, folder_path)
        # 删除文件夹通常意味着“解散”，即将内容移到上一级
        parent_dir = os.path.dirname(target_dir)

        if not os.path.exists(target_dir):
             return jsonify({"success": False, "msg": "文件夹不存在"})
        
        ui_data = load_ui_data()
        ui_changed = False
        moved_details = []

        conn = get_db()
        cursor = conn.cursor()

        # === 阶段 1: 收集阶段 (只读) ===
        # 先遍历并收集所有有效的角色卡文件，不进行移动，防止破坏 os.walk 的迭代
        # 我们使用 list 存储，以便稍后排序
        files_to_process = []
        
        for root, dirs, files in os.walk(target_dir):
            for f in files:
                # 只处理受支持的卡片文件，垃圾文件留给最后整体删除
                if is_card_file(f): 
                    full_src_path = os.path.join(root, f)
                    files_to_process.append(full_src_path)

        # 排序：让 .json 排在同名 .png 前面处理
        # 这样处理 json 时能顺便把伴生图带走，逻辑更清晰
        files_to_process.sort(key=lambda x: 0 if x.lower().endswith('.json') else 1)
        
        processed_files = set() # 记录已处理的绝对路径（防止 PNG 被处理两次）

        # === 阶段 2: 执行阶段 (移动) ===
        for src_full_path in files_to_process:
            if src_full_path in processed_files:
                continue

            filename = os.path.basename(src_full_path)
            current_root = os.path.dirname(src_full_path)
            
            # 标记为主文件已处理
            processed_files.add(src_full_path)

            # --- 伴生图逻辑 ---
            sidecar_filename = None
            sidecar_ext = None
            sidecar_full_path = None
            
            name_part, ext_part = os.path.splitext(filename)
            
            # 如果是 JSON，尝试查找同一目录下的伴生图
            if ext_part.lower() == '.json':
                for ext in SIDECAR_EXTENSIONS:
                    test_sidecar = os.path.join(current_root, name_part + ext)
                    # 检查该文件是否在我们要处理的列表中（或者存在于磁盘）
                    if os.path.exists(test_sidecar):
                        sidecar_filename = name_part + ext
                        sidecar_ext = ext
                        sidecar_full_path = test_sidecar
                        processed_files.add(test_sidecar) # 标记伴生图已处理
                        break
            
            # --- 冲突检测与重命名 ---
            # 我们要找到一个名字，使得主文件和伴生图在 parent_dir 都不存在
            counter = 0
            final_filename = filename
            
            while True:
                if counter > 0:
                    final_filename = f"{name_part}_{counter}{ext_part}"
                
                # 检查主文件冲突
                dst_test_main = os.path.join(parent_dir, final_filename)
                conflict = os.path.exists(dst_test_main)
                
                # 如果主文件没冲突，且有伴生图，检查伴生图冲突
                if not conflict and sidecar_filename:
                    final_sidecar_name = f"{name_part}_{counter}{sidecar_ext}" if counter > 0 else sidecar_filename
                    dst_test_sidecar = os.path.join(parent_dir, final_sidecar_name)
                    if os.path.exists(dst_test_sidecar):
                        conflict = True
                
                if not conflict:
                    break # 找到安全文件名，跳出循环
                counter += 1

            # --- 执行移动操作 ---
            try:
                # 1. 移动主文件
                dst_full_path = os.path.join(parent_dir, final_filename)
                shutil.move(src_full_path, dst_full_path)
                
                # 2. 移动伴生图 (如果有)
                if sidecar_filename:
                    final_sidecar_name = f"{name_part}_{counter}{sidecar_ext}" if counter > 0 else sidecar_filename
                    dst_sidecar_path = os.path.join(parent_dir, final_sidecar_name)
                    shutil.move(sidecar_full_path, dst_sidecar_path)

                # --- 更新元数据 ---
                old_id = os.path.relpath(src_full_path, CARDS_FOLDER).replace('\\', '/')
                new_id = os.path.relpath(dst_full_path, CARDS_FOLDER).replace('\\', '/')
                
                new_cat = os.path.relpath(parent_dir, CARDS_FOLDER).replace('\\', '/')
                if new_cat == ".": new_cat = ""

                # 更新 UI Data Key
                if old_id in ui_data:
                    ui_data[new_id] = ui_data[old_id]
                    del ui_data[old_id]
                    ui_changed = True

                # 更新数据库
                cursor.execute("""
                    UPDATE card_metadata 
                    SET id = ?, category = ? 
                    WHERE id = ?
                """, (new_id, new_cat, old_id))

                # 更新内存缓存
                # 注意：如果 old_id 在缓存中不存在（极为罕见），需要容错
                old_card_data = ctx.cache.id_map.get(old_id)
                old_cat_val = old_card_data['category'] if old_card_data else folder_path
                
                ctx.cache.move_card_update(
                    old_id, new_id, old_cat_val, new_cat, final_filename, dst_full_path
                )

                moved_details.append({
                    "old_id": old_id,
                    "new_id": new_id,
                    "new_filename": final_filename,
                    "new_category": new_cat
                })
            
            except Exception as move_err:
                logger.error(f"Failed to move file {filename}: {move_err}")
                continue

        # === 阶段 3: 提交与清理 ===
        conn.commit()

        if ui_changed: 
            save_ui_data(ui_data)
        
        # 将原文件夹（此时应该只剩下不支持的文件或空目录）移入回收站
        # 这比 shutil.rmtree 更安全，也比 os.rmdir 更彻底（防止有 .DS_Store 等垃圾文件导致无法删除）
        try:
            safe_move_to_trash(target_dir, TRASH_FOLDER)
        except Exception as e:
            logger.warning(f"Could not trash folder structure: {e}")

        # 更新全局缓存中的可见文件夹列表
        # 从 visible_folders 中移除以该路径开头的所有条目
        with ctx.cache.lock:
            prefix = folder_path + '/'
            ctx.cache.visible_folders = [
                f for f in ctx.cache.visible_folders 
                if f != folder_path and not f.startswith(prefix)
            ]
            # 清理计数缓存
            keys_to_del = [k for k in ctx.cache.category_counts if k == folder_path or k.startswith(prefix)]
            for k in keys_to_del:
                del ctx.cache.category_counts[k]

        return jsonify({
            "success": True, 
            "moved_details": moved_details,
            "msg": f"已解散文件夹，{len(moved_details)} 张卡片已移至上级目录。"
        })

    except Exception as e:
        logger.error(f"Delete folder error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/move_folder', methods=['POST'])
def api_move_folder():
    try:
        # move/merge 文件夹会触发大量 fs events，抑制 watchdog（较长窗口）
        suppress_fs_events(6.0)
        data = request.json
        source_path = data.get('source_path')
        target_parent_path = data.get('target_parent_path')
        merge_if_exists = data.get('merge_if_exists', False)
        
        if not source_path:
            return jsonify({"success": False, "msg": "源路径不能为空"})
            
        # 基础安全检查
        if ".." in source_path or source_path.startswith("/") or source_path.startswith("\\"):
            return jsonify({"success": False, "msg": "非法源路径"})
        
        # 处理路径
        source_full_path = os.path.join(CARDS_FOLDER, source_path)
        source_name = os.path.basename(source_full_path)
        
        # 确定目标目录
        if target_parent_path and target_parent_path != "根目录":
            target_base = os.path.join(CARDS_FOLDER, target_parent_path)
            target_full_path = os.path.join(target_base, source_name)
            # 计算新的相对路径前缀
            new_path_prefix = f"{target_parent_path}/{source_name}"
        else:
            target_base = CARDS_FOLDER
            target_full_path = os.path.join(CARDS_FOLDER, source_name)
            new_path_prefix = source_name
            
        # 检查源路径是否存在
        if not os.path.exists(source_full_path):
            return jsonify({"success": False, "msg": "源文件夹不存在"})

        # -------------------------------------------------------------
        # 防止将文件夹移动到自己内部 (避免 test -> test1 误判)
        # -------------------------------------------------------------
        src_abs = os.path.abspath(source_full_path)
        tgt_base_abs = os.path.abspath(target_base)
        
        # 只有当目标路径是源路径加上分隔符的前缀时，才算是子目录
        # 例如: src="/a/b", tgt="/a/b/c" -> True
        # 例如: src="/a/test", tgt="/a/test1" -> False
        if tgt_base_abs == src_abs or tgt_base_abs.startswith(src_abs + os.sep):
             return jsonify({"success": False, "msg": "无法将文件夹移动到其子目录中"})
        # -------------------------------------------------------------

        # === 场景 A: 目标不存在，直接整文件夹移动 (最快) ===
        if not os.path.exists(target_full_path):
            shutil.move(source_full_path, target_full_path)
            
            # 更新数据
            ui_data = load_ui_data()
            rename_folder_in_db(source_path, new_path_prefix) # 见下方辅助函数说明或直接写SQL
            rename_folder_in_ui(ui_data, source_path, new_path_prefix)
            save_ui_data(ui_data)
            
            # 内存增量更新
            ctx.cache.move_folder_update(source_path, new_path_prefix)
            
            return jsonify({
                "success": True, 
                "new_path": new_path_prefix,
                "mode": "move",
                # 返回最新计数
                "category_counts": ctx.cache.category_counts
            })

        # === 场景 B: 目标已存在，需要合并 (Merge) ===
        if not merge_if_exists:
            return jsonify({"success": False, "msg": "目标位置已存在同名文件夹", "needs_merge": True})
        
        # 执行合并逻辑
        ui_data = load_ui_data()
        
        # 递归遍历源目录
        for root, dirs, files in os.walk(source_full_path):
            # 筛选文件：PNG 和 JSON
            files_to_process = []
            processed_files = set()

            # 1. 找 JSON (带伴生图)
            for f in files:
                if f.lower().endswith('.json'):
                    files_to_process.append(f)
                    processed_files.add(f)
                    base = os.path.splitext(f)[0]
                    for ext in SIDECAR_EXTENSIONS:
                        if (base + ext) in files: processed_files.add(base + ext)
            
            # 2. 找剩余 PNG
            for f in files:
                if f.lower().endswith('.png') and f not in processed_files:
                    files_to_process.append(f)

            # 移动文件
            for filename in files_to_process:
                src_file = os.path.join(root, filename)
                
                # 计算在目标文件夹中的对应位置
                # rel_from_source: "Sub/Card.json"
                rel_from_source = os.path.relpath(src_file, source_full_path)
                dst_file = os.path.join(target_full_path, rel_from_source)
                
                # 确保目标子目录存在
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                
                # 重名检测
                final_dst = dst_file
                if os.path.exists(final_dst):
                    base_name, ext_part = os.path.splitext(os.path.basename(dst_file))
                    dir_name = os.path.dirname(dst_file)
                    counter = 1
                    while True:
                        new_name = f"{base_name}_{counter}{ext_part}"
                        final_dst = os.path.join(dir_name, new_name)
                        # 如果是 JSON，还需要检查伴生图是否冲突 (略简化，假设主文件冲突则全部重命名)
                        if not os.path.exists(final_dst): break
                        counter += 1
                
                # 移动主文件
                shutil.move(src_file, final_dst)
                
                # 如果是 JSON，移动伴生图
                if filename.lower().endswith('.json'):
                    base_src = os.path.splitext(filename)[0]
                    base_dst = os.path.splitext(os.path.basename(final_dst))[0] # 使用可能重命名后的名字
                    src_dir = os.path.dirname(src_file)
                    dst_dir = os.path.dirname(final_dst)
                    
                    for ext in SIDECAR_EXTENSIONS:
                        s_src = os.path.join(src_dir, base_src + ext)
                        if os.path.exists(s_src):
                            s_dst = os.path.join(dst_dir, base_dst + ext)
                            shutil.move(s_src, s_dst)

        # 这里的合并逻辑其实相当于“打散”了，原本的 update_folder_cache 并不适用
        # 因为文件可能发生了重命名。
        # 简化处理：合并模式下，我们直接使用全量扫描更安全，或者只对数据库做单文件更新
        # 考虑到“合并文件夹”操作频率较低，为了数据准确性，
        # 我们在这里做一次【特殊的处理】：
        # 1. 删除旧文件夹的 DB 记录
        # 2. 扫描新文件夹并插入 DB
        # 3. 重新加载
        # 这是最稳妥的，因为合并涉及太多的路径变化和重命名。
        
        # 删除源文件夹 (此时应为空)
        try: shutil.rmtree(source_full_path)
        except: pass
        
        # 触发全量刷新 (仅在 Merge 模式下)
        force_reload(reason="move_folder:merge")
        # 由于我们没有实现复杂的 Merge 增量逻辑，告诉前端刷新
        return jsonify({"success": True, "new_path": new_path_prefix, "mode": "merge_reload"})
    except Exception as e:
        logger.error(f"Move folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/upload_note_image', methods=['POST'])
def api_upload_note_image():
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({"success": False, "msg": "未接收到图片"})
        
        # 1. 确定保存路径: data/assets/notes_images
        cfg = load_config()
        notes_dir = os.path.join(DATA_DIR, 'assets', 'notes_images')
        
        if not os.path.exists(notes_dir):
            os.makedirs(notes_dir)
            
        # 2. 生成文件名
        ext = os.path.splitext(file.filename)[1].lower()
        if not ext: ext = '.png'
        # 使用时间戳+随机码防止重名
        filename = f"note_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        save_path = os.path.join(notes_dir, filename)
        
        # 3. 保存
        file.save(save_path)
        
        # 4. 返回 Markdown 友好的相对路径
        # 复用现有的 /resources_file/ 路由
        url = f"/assets/notes/{filename}"
        
        return jsonify({"success": True, "url": url})
    except Exception as e:
        logger.error(f"Note image upload error: {e}")
        return jsonify({"success": False, "msg": str(e)})
