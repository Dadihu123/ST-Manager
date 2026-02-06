import os
import json
import time
import shutil
import logging
import sqlite3
import hashlib
import re
from io import BytesIO
from flask import Blueprint, request, jsonify, send_file

# === 基础设施 ===
from core.config import BASE_DIR, load_config, DEFAULT_DB_PATH, CARDS_FOLDER, TRASH_FOLDER 
from core.context import ctx
from core.data.db_session import get_db
from core.data.ui_store import load_ui_data, UI_DATA_FILE
from core.services.cache_service import invalidate_wi_list_cache
from core.services.wi_entry_history_service import (
    ensure_entry_uids,
    collect_previous_versions,
    append_entry_history_records,
    list_entry_history_records,
    get_history_limit
)
from core.utils.filesystem import safe_move_to_trash

def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path) if path and os.path.exists(path) else 0.0
    except:
        return 0.0

def _is_under_base(path: str, base: str) -> bool:
    try:
        norm_path = os.path.normcase(os.path.normpath(path))
        norm_base = os.path.normcase(os.path.normpath(base))
        return os.path.commonpath([norm_path, norm_base]) == norm_base
    except Exception:
        return False

def _resolve_wi_dir(cfg: dict) -> str:
    raw_wi_dir = cfg.get('world_info_dir', 'lorebooks')
    return raw_wi_dir if os.path.isabs(raw_wi_dir) else os.path.join(BASE_DIR, raw_wi_dir)

def _resolve_resources_dir(cfg: dict) -> str:
    raw_res_dir = cfg.get('resources_dir', 'resources')
    return raw_res_dir if os.path.isabs(raw_res_dir) else os.path.join(BASE_DIR, raw_res_dir)

def _is_valid_wi_file(path: str, cfg: dict) -> bool:
    if not path:
        return False
    global_dir = _resolve_wi_dir(cfg)
    resources_dir = _resolve_resources_dir(cfg)

    if _is_under_base(path, global_dir):
        return True

    if _is_under_base(path, resources_dir):
        rel_path = os.path.relpath(path, resources_dir).replace('\\', '/')
        return '/lorebooks/' in f"/{rel_path}/"

    return False

def _normalize_wi_entries(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get('entries', [])
        if isinstance(entries, dict):
            entries = list(entries.values())
    else:
        return []

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        keys = entry.get('keys')
        if keys is None:
            keys = entry.get('key')
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, list):
            keys = []

        sec = entry.get('secondary_keys')
        if sec is None:
            sec = entry.get('keysecondary')
        if isinstance(sec, str):
            sec = [sec]
        if not isinstance(sec, list):
            sec = []

        enabled = entry.get('enabled')
        if enabled is None:
            enabled = not bool(entry.get('disable', False))

        keys_norm = sorted({str(k).strip().lower() for k in keys if str(k).strip()})
        sec_norm = sorted({str(k).strip().lower() for k in sec if str(k).strip()})

        normalized.append({
            "keys": keys_norm,
            "secondary_keys": sec_norm,
            "content": entry.get('content') or "",
            "comment": entry.get('comment') or "",
            "enabled": bool(enabled),
            "constant": bool(entry.get('constant', False)),
            "vectorized": bool(entry.get('vectorized', False)),
            "position": entry.get('position') if entry.get('position') is not None else entry.get('pos'),
            "order": entry.get('insertion_order') or entry.get('order') or 0,
            "selective": bool(entry.get('selective', True)),
            "use_regex": bool(entry.get('use_regex', False))
        })

    normalized.sort(key=lambda x: (','.join(x.get('keys', [])), x.get('content', ''), x.get('comment', '')))
    return normalized


def _build_st_compatible_worldbook_payload(name: str) -> dict:
    """
    构建与 SillyTavern 新建世界书兼容的最小结构。
    使用最小字段可最大化跨版本兼容性：name + entries(dict)。
    """
    clean_name = str(name or '').strip() or 'World Info'
    return {
        "name": clean_name,
        "entries": {}
    }

def _compute_wi_signature(raw):
    try:
        entries = _normalize_wi_entries(raw)
        if not entries:
            return None
        def _clean_text(text):
            if not isinstance(text, str):
                return ""
            cleaned = text.replace('\r\n', '\n').replace('\r', '\n')
            cleaned = re.sub(r'\s+', ' ', cleaned)
            return cleaned.strip()

        entry_sigs = []
        for entry in entries:
            content = _clean_text(entry.get('content', ''))
            comment = _clean_text(entry.get('comment', ''))
            if not content and not comment:
                continue
            entry_sigs.append(f"{content}||{comment}")

        entry_sigs.sort()
        payload = "\n".join(entry_sigs)
        return hashlib.sha1(payload.encode('utf-8')).hexdigest()
    except Exception:
        return None

# === 工具函数 ===
from core.utils.image import extract_card_info # 用于 export logic

logger = logging.getLogger(__name__)

bp = Blueprint('wi', __name__)

@bp.route('/api/world_info/list', methods=['GET'])
def api_list_world_infos():
    try:
        search = request.args.get('search', '').lower().strip()
        wi_type = request.args.get('type', 'all') # all, global, resource, embedded

        # 新增分页参数
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
        except:
            page, page_size = 1, 20

        # === 动态获取配置中的路径，而不是使用全局静态变量 ===
        cfg = load_config()
        current_wi_folder = _resolve_wi_dir(cfg)
            
        if not os.path.exists(current_wi_folder):
            try: os.makedirs(current_wi_folder)
            except: pass

        # ===== [CACHE] key = type + search（未分页 items）=====
        cache_key = f"{wi_type}||{search}"

        cfg = load_config()
        default_res_dir = _resolve_resources_dir(cfg)
        db_path = DEFAULT_DB_PATH
        cards_dir_sig = _safe_mtime(str(CARDS_FOLDER))

        global_dir_sig   = _safe_mtime(current_wi_folder)
        resource_dir_sig = _safe_mtime(default_res_dir)
        ui_data_sig      = _safe_mtime(UI_DATA_FILE)
        db_sig           = _safe_mtime(db_path)

        if wi_type == 'global':
            sig = ('global', global_dir_sig, db_sig, cards_dir_sig)
        elif wi_type == 'resource':
            sig = ('resource', resource_dir_sig, ui_data_sig)
        elif wi_type == 'embedded':
            sig = ('embedded', db_sig, cards_dir_sig)
        else:  # all
            sig = ('all', global_dir_sig, resource_dir_sig, ui_data_sig, db_sig, cards_dir_sig)

        cached_items = None
        with ctx.wi_list_cache_lock:
            cached = ctx.wi_list_cache.get(cache_key)
            if cached and cached.get("sig") == sig:
                items = cached.get("items") or []
                # === 命中缓存直接分页返回，不再往下扫描 ===
                total_count = len(items)
                start = (page - 1) * page_size
                end = start + page_size
                return jsonify({
                    "success": True,
                    "items": items[start:end],
                    "total": total_count,
                    "page": page,
                    "page_size": page_size
                })

        # 原扫描
        items = []
        embedded_name_set = set()
        embedded_sig_set = set()

        # 预先读取内嵌世界书名称与内容签名，用于全局列表去重
        if wi_type in ['all', 'global']:
            try:
                conn = get_db()
                cursor = conn.execute(
                    "SELECT char_name, character_book_name FROM card_metadata WHERE has_character_book = 1"
                )
                rows = cursor.fetchall()
                for row in rows:
                    book_name = row['character_book_name'] or f"{row['char_name']}'s WI"
                    if book_name:
                        embedded_name_set.add(str(book_name).strip().lower())
            except Exception:
                embedded_name_set = set()

            # 计算内容签名（按需从卡片文件提取）
            try:
                if not ctx.cache.initialized:
                    ctx.cache.reload_from_db()
                for card in ctx.cache.cards:
                    if not card.get('has_character_book'):
                        continue
                    card_id = card.get('id')
                    if not card_id:
                        continue
                    try:
                        full_path = os.path.join(str(CARDS_FOLDER), card_id.replace('/', os.sep))
                        if not os.path.exists(full_path):
                            continue
                        info = extract_card_info(full_path)
                        if not info:
                            continue
                        data_block = info.get('data', {}) if 'data' in info else info
                        book = data_block.get('character_book')
                        sig = _compute_wi_signature(book)
                        if sig:
                            embedded_sig_set.add(sig)
                    except Exception:
                        continue
            except Exception:
                embedded_sig_set = set()

        # 预先收集资源世界书目录，用于去重/排除
        resource_targets = []
        resource_lore_dirs = set()
        res_root_dir = None
        if wi_type in ['all', 'resource', 'global']:
            ui_data = load_ui_data()
            cfg = load_config()
            default_res_dir = os.path.join(BASE_DIR, cfg.get('resources_dir', 'resources'))
            res_root_dir = os.path.normpath(default_res_dir)
            if not ctx.cache.initialized:
                ctx.cache.reload_from_db()
            for card in ctx.cache.cards:
                key = card.get('bundle_dir') if card.get('is_bundle') else card.get('id')
                ui_info = ui_data.get(key, {}) or {}
                res_folder = ui_info.get('resource_folder') or card.get('resource_folder')
                if not res_folder and key != card.get('id'):
                    fallback_info = ui_data.get(card.get('id', ''), {}) or {}
                    res_folder = fallback_info.get('resource_folder') or res_folder
                if not res_folder:
                    continue
                if os.path.isabs(res_folder):
                    target_dir = res_folder
                else:
                    target_dir = os.path.join(default_res_dir, res_folder)
                lore_dir = os.path.join(target_dir, 'lorebooks')
                lore_dir = os.path.normpath(lore_dir)
                resource_lore_dirs.add(lore_dir)
                resource_targets.append({
                    "key": key,
                    "card": card,
                    "lore_dir": lore_dir
                })

            # 扫描 resources 根目录下的 lorebooks（防止 UI 数据缺失导致遗漏）
            if res_root_dir and os.path.exists(res_root_dir):
                try:
                    for folder in os.listdir(res_root_dir):
                        full = os.path.join(res_root_dir, folder)
                        if not os.path.isdir(full):
                            continue
                        lore_dir = os.path.normpath(os.path.join(full, 'lorebooks'))
                        if os.path.exists(lore_dir):
                            resource_lore_dirs.add(lore_dir)
                except Exception:
                    pass

        # 1. 全局目录 (Global)
        if wi_type in ['all', 'global']:
            for root, dirs, files in os.walk(current_wi_folder):
                for f in files:
                    if f.lower().endswith('.json'):
                        full_path = os.path.join(root, f)
                        # 排除资源目录下的世界书，避免误判为全局
                        if any(_is_under_base(full_path, lore_dir) for lore_dir in resource_lore_dirs):
                            continue
                        if res_root_dir and not _is_under_base(current_wi_folder, res_root_dir):
                            if _is_under_base(full_path, res_root_dir):
                                continue
                        try:
                            if os.path.getsize(full_path) == 0: continue
                            # 简单读取 header，不读取全部 entries 以优化性能
                            # 如果文件巨大，可以考虑只读前几KB解析
                            with open(full_path, 'r', encoding='utf-8') as f_obj:
                                data = json.load(f_obj)
                                # 兼容 list 或 dict
                                file_name = os.path.basename(f)
                                base_name = os.path.splitext(file_name)[0]
                                name_source = "filename"
                                if isinstance(data, dict):
                                    name_val = (data.get('name') or "").strip()
                                    if name_val:
                                        name = name_val
                                        name_source = "meta"
                                    else:
                                        name = file_name  # 显示含扩展名，更像“文件”
                                else:
                                    name = file_name

                                # 如果与内嵌世界书同名或内容相同，跳过（避免全局混入）
                                if embedded_name_set:
                                    name_key = str(name).strip().lower()
                                    base_key = os.path.splitext(str(name).strip())[0].lower()
                                    file_base_key = os.path.splitext(file_name)[0].lower() if file_name else base_key
                                    if name_key in embedded_name_set or base_key in embedded_name_set or file_base_key in embedded_name_set:
                                        continue
                                if embedded_sig_set:
                                    sig = _compute_wi_signature(data)
                                    if sig and sig in embedded_sig_set:
                                        continue
                                    
                                items.append({
                                    "id": f"global::{os.path.relpath(full_path, current_wi_folder)}",
                                    "type": "global",
                                    "name": name,
                                    "name_source": name_source,
                                    "file_name": file_name,
                                    "path": full_path,
                                    "mtime": os.path.getmtime(full_path)
                                })
                        except Exception as e: 
                            print(f"Error reading WI {f}: {e}")
                            continue

        # 2. 资源目录 (Resource) - 基于 ui_data 查找自定义路径
        if wi_type in ['all', 'resource']:
            # 建立 card_id -> resource_path 的映射
            # 此时我们要扫描的是哪些文件夹里有 'lorebooks/*.json'
            # 为了避免重复扫描同一个文件夹（多个卡片可能指向同一个资源目录），我们需要去重
            scanned_paths = set()
            
            # 遍历资源目标目录
            for target in resource_targets:
                key = target.get('key')
                card = target.get('card') or {}
                lore_dir = target.get('lore_dir')
                
                if lore_dir in scanned_paths: continue # 已扫描过
                scanned_paths.add(lore_dir)
                
                if os.path.exists(lore_dir):
                    for f in os.listdir(lore_dir):
                        if f.lower().endswith('.json'):
                            full_path = os.path.join(lore_dir, f)
                            try:
                                with open(full_path, 'r', encoding='utf-8') as f_obj:
                                    data = json.load(f_obj)
                                    file_name = os.path.basename(f)
                                    base_name = os.path.splitext(file_name)[0]
                                    name_source = "filename"
                                    if isinstance(data, dict):
                                        name_val = (data.get('name') or "").strip()
                                        if name_val:
                                            name = name_val
                                            name_source = "meta"
                                        else:
                                            name = file_name
                                    else:
                                        name = file_name
                                    items.append({
                                        "id": f"resource::{key}::{f}",
                                        "type": "resource",
                                        "name": name,
                                        "name_source": name_source,
                                        "file_name": file_name,
                                        "path": full_path,
                                        "card_name": card.get('char_name', ''), # 关联的角色名
                                        "card_id": card.get('id', ''), # 用于跳转
                                        "mtime": os.path.getmtime(full_path)
                                    })
                            except: continue

        # 3. 角色卡内嵌 (Embedded) - 查询数据库
        if wi_type in ['all', 'embedded']:
            conn = get_db()
            cursor = conn.execute("SELECT id, char_name, character_book_name, last_modified FROM card_metadata WHERE has_character_book = 1")
            rows = cursor.fetchall()
            for row in rows:
                items.append({
                    "id": f"embedded::{row['id']}",
                    "type": "embedded",
                    "name": row['character_book_name'] or f"{row['char_name']}'s WI",
                    "card_name": row['char_name'],
                    "card_id": row['id'],
                    "mtime": row['last_modified']
                })

        # 过滤与排序
        if search:
            items = [i for i in items if search in i['name'].lower() or (i.get('card_name') and search in i['card_name'].lower())]
            
        items.sort(key=lambda x: x.get('mtime', 0), reverse=True)

        # ===== [CACHE WRITE] 只在未命中缓存时写入 =====
        if cached_items is None:
            with ctx.wi_list_cache_lock:
                # 简单上限，避免 key 太多（比如用户疯狂换 search）
                if len(ctx.wi_list_cache) > 200:
                    ctx.wi_list_cache.clear()
                ctx.wi_list_cache[cache_key] = {"sig": sig, "items": items, "ts": time.time()}

        # 分页切片
        total_count = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = items[start:end]
        
        return jsonify({
            "success": True, 
            "items": paginated_items, 
            "total": total_count,
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        logger.error(f"List WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/world_info/create', methods=['POST'])
def api_create_world_info():
    """
    创建全局世界书（SillyTavern 兼容结构）。
    仅创建到全局 world_info_dir，避免资源目录歧义。
    """
    try:
        req = request.json or {}
        raw_name = str(req.get('name') or '').strip()
        if not raw_name:
            return jsonify({"success": False, "msg": "世界书名称不能为空"})

        safe_name = raw_name.replace('/', '_').replace('\\', '_').strip()
        if not safe_name:
            return jsonify({"success": False, "msg": "世界书名称不合法"})

        cfg = load_config()
        target_dir = _resolve_wi_dir(cfg)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        final_path = os.path.join(target_dir, f"{safe_name}.json")
        base, ext = os.path.splitext(final_path)
        idx = 1
        while os.path.exists(final_path):
            final_path = f"{base}_{idx}{ext}"
            idx += 1

        payload = _build_st_compatible_worldbook_payload(raw_name)
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

        invalidate_wi_list_cache()

        rel = os.path.relpath(final_path, target_dir).replace('\\', '/')
        file_name = os.path.basename(final_path)
        item = {
            "id": f"global::{rel}",
            "type": "global",
            "name": payload.get('name') or os.path.splitext(file_name)[0],
            "name_source": "meta",
            "file_name": file_name,
            "path": final_path,
            "mtime": os.path.getmtime(final_path)
        }
        return jsonify({
            "success": True,
            "msg": "世界书已创建",
            "path": final_path,
            "item": item
        })
    except Exception as e:
        logger.error(f"Create WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})

# 上传世界书
@bp.route('/api/upload_world_info', methods=['POST'])
def api_upload_world_info():
    try:
        files = request.files.getlist('files')
        if not files:
            return jsonify({"success": False, "msg": "未接收到文件"})

        # 获取全局世界书目录
        cfg = load_config()
        raw_wi_dir = cfg.get('world_info_dir', 'lorebooks')
        target_dir = raw_wi_dir if os.path.isabs(raw_wi_dir) else os.path.join(BASE_DIR, raw_wi_dir)
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        success_count = 0
        failed_list = []

        for file in files:
            if not file.filename.lower().endswith('.json'):
                failed_list.append(file.filename)
                continue
            
            # 防重名
            safe_name = os.path.basename(file.filename)
            name_part, ext = os.path.splitext(safe_name)
            save_path = os.path.join(target_dir, safe_name)
            
            counter = 1
            while os.path.exists(save_path):
                save_path = os.path.join(target_dir, f"{name_part}_{counter}{ext}")
                counter += 1
            
            try:
                # 尝试验证 JSON 格式
                content = file.read()
                json.loads(content) # 校验格式
                
                # 重置指针并保存
                file.seek(0)
                file.save(save_path)
                success_count += 1
            except Exception:
                failed_list.append(file.filename)

        msg = f"成功上传 {success_count} 个世界书。"
        if failed_list:
            msg += f" 失败: {', '.join(failed_list)}"
        invalidate_wi_list_cache()
        return jsonify({"success": True, "count": success_count, "msg": msg})
        
    except Exception as e:
        logger.error(f"Upload WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/world_info/detail', methods=['POST'])
def api_get_world_info_detail():
    try:
        # id 格式: "type::path"
        wi_id = request.json.get('id')
        source_type = request.json.get('source_type')
        file_path = request.json.get('file_path')
        preview_limit = request.json.get('preview_limit')
        force_full = bool(request.json.get('force_full', False))

        if not file_path:
             return jsonify({"success": False, "msg": "文件路径为空"})

        cfg = load_config()
        global_dir = _resolve_wi_dir(cfg)
        resources_dir = _resolve_resources_dir(cfg)

        # 处理相对路径：如果是相对路径，基于 BASE_DIR 转换为绝对路径
        if not os.path.isabs(file_path):
            file_path = os.path.join(BASE_DIR, file_path)
            file_path = os.path.normpath(file_path)

        # 仅允许访问世界书相关目录
        if source_type == 'global':
            if not _is_under_base(file_path, global_dir):
                return jsonify({"success": False, "msg": "非法路径"}), 400
        elif source_type == 'resource':
            if not _is_under_base(file_path, resources_dir):
                return jsonify({"success": False, "msg": "非法路径"}), 400
            rel_path = os.path.relpath(file_path, resources_dir).replace('\\', '/')
            if '/lorebooks/' not in f"/{rel_path}/":
                return jsonify({"success": False, "msg": "非法路径"}), 400
        elif source_type:
            return jsonify({"success": False, "msg": "非法路径"}), 400
        else:
            # 兼容老请求：允许全局或资源目录
            if not (_is_under_base(file_path, global_dir) or _is_under_base(file_path, resources_dir)):
                return jsonify({"success": False, "msg": "非法路径"}), 400

        if not os.path.exists(file_path):
             return jsonify({"success": False, "msg": "文件不存在"})
             
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 预览模式：条目过多时只返回前 N 条，避免前端卡死
        truncated = False
        truncated_content = False
        total_entries = 0
        applied_limit = 0
        applied_content_limit = 0

        def _count_entries(raw):
            if isinstance(raw, list):
                return len(raw)
            if isinstance(raw, dict):
                entries = raw.get('entries')
                if isinstance(entries, list):
                    return len(entries)
                if isinstance(entries, dict):
                    return len(entries.keys())
            return 0

        def _slice_entries(raw, limit):
            if isinstance(raw, list):
                return raw[:limit]
            if isinstance(raw, dict):
                entries = raw.get('entries')
                if isinstance(entries, list):
                    new_data = dict(raw)
                    new_data['entries'] = entries[:limit]
                    return new_data
                if isinstance(entries, dict):
                    keys = list(entries.keys())
                    try:
                        keys.sort(key=lambda k: int(k))
                    except Exception:
                        keys.sort()
                    trimmed = {k: entries[k] for k in keys[:limit]}
                    new_data = dict(raw)
                    new_data['entries'] = trimmed
                    return new_data
            return raw

        try:
            limit_val = int(preview_limit) if preview_limit is not None else 0
        except Exception:
            limit_val = 0

        default_limit = cfg.get('wi_preview_limit', 300)
        default_content_limit = cfg.get('wi_preview_entry_max_chars', 2000)

        if not force_full:
            if limit_val <= 0:
                try:
                    limit_val = int(default_limit) if default_limit is not None else 0
                except Exception:
                    limit_val = 0

            content_limit = 0
            try:
                content_limit = int(default_content_limit) if default_content_limit is not None else 0
            except Exception:
                content_limit = 0

            if limit_val > 0:
                total_entries = _count_entries(data)
                if total_entries > limit_val:
                    data = _slice_entries(data, limit_val)
                    truncated = True
                    applied_limit = limit_val

            # 内容长度截断（避免超长文本渲染卡死）
            if content_limit > 0:
                applied_content_limit = content_limit

                def _truncate_entry(entry):
                    nonlocal truncated_content
                    if not isinstance(entry, dict):
                        return entry
                    new_entry = dict(entry)
                    content = new_entry.get('content')
                    if isinstance(content, str) and len(content) > content_limit:
                        new_entry['content'] = content[:content_limit] + ' ...'
                        truncated_content = True
                    comment = new_entry.get('comment')
                    if isinstance(comment, str) and len(comment) > content_limit:
                        new_entry['comment'] = comment[:content_limit] + ' ...'
                        truncated_content = True
                    return new_entry

                if isinstance(data, list):
                    data = [_truncate_entry(e) for e in data]
                elif isinstance(data, dict):
                    entries = data.get('entries')
                    if isinstance(entries, list):
                        data = dict(data)
                        data['entries'] = [_truncate_entry(e) for e in entries]
                    elif isinstance(entries, dict):
                        data = dict(data)
                        new_entries = {}
                        for k, v in entries.items():
                            new_entries[k] = _truncate_entry(v)
                        data['entries'] = new_entries
            
        resp = {"success": True, "data": data}
        if truncated:
            resp.update({
                "truncated": True,
                "total_entries": total_entries,
                "preview_limit": applied_limit
            })
        if truncated_content:
            resp.update({
                "truncated_content": True,
                "preview_entry_max_chars": applied_content_limit
            })
        return jsonify(resp)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/world_info/save', methods=['POST'])
def api_save_world_info():
    try:
        save_mode = request.json.get('save_mode') # 'overwrite', 'new_global', 'new_resource'
        target_path = request.json.get('file_path') # 如果是 overwrite
        name = request.json.get('name')
        content = request.json.get('content') # JSON 对象
        old_content = None
        history_records = []
        
        final_path = ""
        
        if save_mode == 'overwrite':
            if not target_path or not os.path.exists(target_path):
                return jsonify({"success": False, "msg": "目标文件不存在，无法覆盖"})
            final_path = target_path
            if not os.path.isabs(final_path):
                final_path = os.path.normpath(os.path.join(BASE_DIR, final_path))
            else:
                final_path = os.path.normpath(final_path)
            cfg = load_config()
            if not _is_valid_wi_file(final_path, cfg):
                return jsonify({"success": False, "msg": "非法路径"})
            try:
                with open(final_path, 'r', encoding='utf-8') as f:
                    old_content = json.load(f)
            except Exception:
                old_content = None
            
        elif save_mode == 'new_global':
            cfg = load_config()
            raw_wi = cfg.get('world_info_dir', 'lorebooks')
            current_wi_folder = raw_wi if os.path.isabs(raw_wi) else os.path.join(BASE_DIR, raw_wi)
            if not os.path.exists(current_wi_folder): os.makedirs(current_wi_folder)
            # 保存到全局目录
            filename = f"{name}.json".replace('/', '_').replace('\\', '_')
            final_path = os.path.join(current_wi_folder, filename)
            # 防重名
            counter = 1
            base, ext = os.path.splitext(final_path)
            while os.path.exists(final_path):
                final_path = f"{base}_{counter}{ext}"
                counter += 1
        
        elif save_mode == 'new_resource':
            # 保存到指定角色的资源目录
            card_id = request.json.get('card_id')
            # 获取资源目录
            ui_data = load_ui_data()
            # ... (获取资源路径逻辑) ...
            # 略，需要复用 get_resource_folder 逻辑
            pass 

        if isinstance(content, (dict, list)):
            ensure_entry_uids(content)
            history_records = collect_previous_versions(old_content, content)

        # 写入
        compact = bool(request.json.get('compact', False))
        with open(final_path, 'w', encoding='utf-8') as f:
            if compact:
                json.dump(content, f, ensure_ascii=False, separators=(',', ':'))
            else:
                json.dump(content, f, ensure_ascii=False, indent=2)

        if history_records:
            append_entry_history_records(
                source_type='lorebook',
                source_id='',
                file_path=final_path,
                records=history_records
            )
        
        invalidate_wi_list_cache()
        return jsonify({"success": True, "new_path": final_path})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/world_info/entry_history/list', methods=['POST'])
def api_list_wi_entry_history():
    try:
        source_type = request.json.get('source_type') or 'lorebook'
        source_id = request.json.get('source_id') or ''
        file_path = request.json.get('file_path') or ''
        entry_uid = request.json.get('entry_uid') or ''
        limit = request.json.get('limit')

        records = list_entry_history_records(
            source_type=source_type,
            source_id=source_id,
            file_path=file_path,
            entry_uid=entry_uid,
            limit=limit
        )

        return jsonify({
            'success': True,
            'items': records,
            'limit': get_history_limit(limit)
        })
    except Exception as e:
        logger.error(f"List WI entry history error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/tools/migrate_lorebooks', methods=['POST'])
def api_migrate_lorebooks():
    """
    一键整理：遍历所有卡片的资源目录，将根目录下的 json 世界书移动到 lorebooks 子目录
    """
    try:
        cfg = load_config()
        default_res_dir = os.path.join(BASE_DIR, cfg.get('resources_dir', 'resources'))
        ui_data = load_ui_data()
        
        # 获取所有涉及的资源目录路径 (去重)
        target_res_dirs = set()
        
        # 1. 扫描 resources/ 根目录下的文件夹
        if os.path.exists(default_res_dir):
            for d in os.listdir(default_res_dir):
                full = os.path.join(default_res_dir, d)
                if os.path.isdir(full): target_res_dirs.add(full)

        # 2. 扫描卡片指定的自定义路径
        if not ctx.cache.initialized: ctx.cache.reload_from_db()
        for card in ctx.cache.cards:
            res_folder = card.get('resource_folder')
            if not res_folder:
                # 尝试从 ui_data 获取
                key = card.get('bundle_dir') if card.get('is_bundle') else card['id']
                res_folder = ui_data.get(key, {}).get('resource_folder')
            
            if res_folder:
                if os.path.isabs(res_folder):
                    if os.path.exists(res_folder): target_res_dirs.add(res_folder)
                else:
                    full = os.path.join(default_res_dir, res_folder)
                    if os.path.exists(full): target_res_dirs.add(full)

        moved_count = 0
        
        for res_path in target_res_dirs:
            lore_target_dir = os.path.join(res_path, 'lorebooks')
            
            # 扫描该资源目录根下的文件
            try:
                files = os.listdir(res_path)
            except:
                continue

            for f in files:
                if f.lower().endswith('.json'):
                    src_path = os.path.join(res_path, f)
                    if not os.path.isfile(src_path): continue

                    # 检查是否为有效 WI
                    try:
                        with open(src_path, 'r', encoding='utf-8') as f_obj:
                            try:
                                data = json.load(f_obj)
                            except: continue # JSON 解析失败跳过

                            is_wi = False
                            # 判定标准
                            if isinstance(data, dict) and 'entries' in data: is_wi = True
                            elif isinstance(data, list) and len(data) > 0:
                                # 检查第一项是否有 keys 或 key，防止把其他配置json误判
                                first = data[0]
                                if isinstance(first, dict) and ('keys' in first or 'key' in first):
                                    is_wi = True
                            
                            if is_wi:
                                if not os.path.exists(lore_target_dir):
                                    os.makedirs(lore_target_dir)
                                
                                dst_path = os.path.join(lore_target_dir, f)
                                # 防重名
                                if os.path.exists(dst_path):
                                    if os.path.samefile(src_path, dst_path): continue
                                    base, ext = os.path.splitext(f)
                                    dst_path = os.path.join(lore_target_dir, f"{base}_{int(time.time())}{ext}")
                                
                                # 执行移动
                                try:
                                    # 1. 尝试移动
                                    shutil.move(src_path, dst_path)               
                                    moved_count += 1
                                except Exception as move_err:
                                    print(f"Move failed for {f}: {move_err}")
                                    # 尝试回滚或忽略，防止数据丢失
                                    continue
                    except Exception as e:
                        print(f"Error checking file {src_path}: {e}")
                        continue
        
        invalidate_wi_list_cache()
        return jsonify({"success": True, "count": moved_count})
    except Exception as e:
        logger.error(f"Migrate error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/export_worldbook_single', methods=['POST'])
def api_export_worldbook_single():
    try:
        cid = request.json.get("card_id")
        if not cid:
            return jsonify({"success": False, "msg": "角色卡ID缺失"})

        rel = cid.replace('/', os.sep)
        file_path = os.path.join(CARDS_FOLDER, rel)
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "未找到角色卡"})

        info = extract_card_info(file_path)
        if not info:
            return jsonify({"success": False, "msg": "未找到元数据"})

        # 获取世界书数据
        book = info.get("data", {}).get("character_book") or info.get("character_book")
        if not book:
            return jsonify({"success": False, "msg": "角色卡无世界书"})

        # === 数据源获取 ===
        entries_raw = []
        if isinstance(book, list):
            entries_raw = book
        elif isinstance(book, dict):
            if 'entries' in book:
                if isinstance(book['entries'], list):
                    entries_raw = book['entries']
                elif isinstance(book['entries'], dict):
                    entries_raw = list(book['entries'].values())
        
        # === 增量导出逻辑 (Pass-through) ===
        export_entries = {}
        for idx, entry in enumerate(entries_raw):
            # 1. 【关键】复制原始数据，保留所有未知字段 (如 vectorized, depth 等)
            final_entry = entry.copy()
            
            # 2. 更新/标准化 ST 核心字段
            # 我们内部使用 keys(复数)/enabled(正向)，ST 使用 key(单数)/disable(反向)
            
            # UID 重置为索引
            final_entry['uid'] = idx
            final_entry['displayIndex'] = idx
            
            # 关键字映射: keys -> key
            # 优先使用内部的 keys，如果没有则保留原有的 key
            if 'keys' in entry:
                final_entry['key'] = entry['keys']
            if 'key' not in final_entry:
                final_entry['key'] = []

            # 次要关键字映射
            if 'secondary_keys' in entry:
                final_entry['keysecondary'] = entry['secondary_keys']
            if 'keysecondary' not in final_entry:
                final_entry['keysecondary'] = []

            # 启用状态映射: enabled -> disable
            is_enabled = entry.get('enabled', not entry.get('disable', False))
            final_entry['disable'] = not is_enabled
            
            # 权重映射: insertion_order -> order
            if 'insertion_order' in entry:
                final_entry['order'] = entry['insertion_order']
            
            # 移除我们内部使用的临时字段 (可选，为了保持 JSON 整洁)
            final_entry.pop('enabled', None)
            final_entry.pop('keys', None)
            final_entry.pop('secondary_keys', None)
            final_entry.pop('insertion_order', None)

            export_entries[str(idx)] = final_entry

        final_export = {
            "entries": export_entries,
            "name": book.get('name', 'World Info') if isinstance(book, dict) else "World Info"
        }
        
        # 保留原始书的其他顶层属性 (如 description 等，如果有的话)
        if isinstance(book, dict):
            for k, v in book.items():
                if k not in ['entries', 'name']:
                    final_export[k] = v

        json_bytes = json.dumps(final_export, ensure_ascii=False, indent=2).encode("utf-8")
        buf = BytesIO(json_bytes)
        buf.seek(0)

        return send_file(
            buf,
            mimetype="application/json; charset=utf-8",
            as_attachment=True,
            download_name=f"{cid.replace('/', '_')}_worldbook.json"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

# --- WI Clipboard APIs ---
@bp.route('/api/wi/clipboard/list', methods=['GET'])
def api_wi_clipboard_list():
    try:
        db_path = DEFAULT_DB_PATH
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM wi_clipboard ORDER BY sort_order ASC, created_at DESC")
            rows = cursor.fetchall()
            items = []
            for r in rows:
                items.append({
                    "db_id": r['id'],
                    "content": json.loads(r['content_json']),
                    "sort_order": r['sort_order']
                })
        return jsonify({"success": True, "items": items})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/wi/clipboard/add', methods=['POST'])
def api_wi_clipboard_add():
    try:
        entry = request.json.get('entry')
        overwrite_id = request.json.get('overwrite_id') # 如果有值，则是覆盖操作
        limit = 50 # 限制数量

        db_path = DEFAULT_DB_PATH
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            
            # 覆盖模式
            if overwrite_id:
                cursor.execute("UPDATE wi_clipboard SET content_json = ?, created_at = ? WHERE id = ?", 
                              (json.dumps(entry), time.time(), overwrite_id))
                conn.commit()
                return jsonify({"success": True, "msg": "已覆盖条目"})

            # 新增模式：检查数量
            cursor.execute("SELECT COUNT(*) FROM wi_clipboard")
            count = cursor.fetchone()[0]
            if count >= limit:
                return jsonify({"success": False, "code": "FULL", "msg": "剪切板已满"})
            
            # 获取最大排序
            cursor.execute("SELECT MAX(sort_order) FROM wi_clipboard")
            max_order = cursor.fetchone()[0]
            new_order = (max_order if max_order is not None else 0) + 1

            cursor.execute("INSERT INTO wi_clipboard (content_json, sort_order, created_at) VALUES (?, ?, ?)",
                           (json.dumps(entry), new_order, time.time()))
            conn.commit()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/wi/clipboard/delete', methods=['POST'])
def api_wi_clipboard_delete():
    try:
        db_id = request.json.get('db_id')
        db_path = DEFAULT_DB_PATH
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("DELETE FROM wi_clipboard WHERE id = ?", (db_id,))
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/wi/clipboard/clear', methods=['POST'])
def api_wi_clipboard_clear():
    try:
        db_path = DEFAULT_DB_PATH
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("DELETE FROM wi_clipboard")
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/wi/clipboard/reorder', methods=['POST'])
def api_wi_clipboard_reorder():
    try:
        order_map = request.json.get('order_map') # list of db_ids in order
        db_path = DEFAULT_DB_PATH
        with sqlite3.connect(db_path, timeout=10) as conn:
            for idx, db_id in enumerate(order_map):
                conn.execute("UPDATE wi_clipboard SET sort_order = ? WHERE id = ?", (idx, db_id))
            conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})
    
# 删除世界书
@bp.route('/api/world_info/delete', methods=['POST'])
def api_delete_world_info():
    try:
        # 传入完整文件路径
        file_path = request.json.get('file_path')
        if not file_path:
            return jsonify({"success": False, "msg": "文件不存在或路径为空"})

        file_path = file_path if os.path.isabs(file_path) else os.path.join(BASE_DIR, file_path)
        file_path = os.path.normpath(file_path)

        cfg = load_config()
        if not _is_valid_wi_file(file_path, cfg):
            return jsonify({"success": False, "msg": "非法路径"})

        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "文件不存在或路径为空"})
            
        # 简单的安全检查，防止删除系统关键文件
        if 'card_metadata' in file_path or 'config.json' in file_path:
             return jsonify({"success": False, "msg": "非法操作：禁止删除系统文件"})

        # 执行移动到回收站
        if safe_move_to_trash(file_path, TRASH_FOLDER):
            # 刷新列表缓存
            invalidate_wi_list_cache()
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "msg": "移动到回收站失败"})
            
    except Exception as e:
        logger.error(f"Delete WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})
