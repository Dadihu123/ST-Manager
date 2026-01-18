import os
import json
import platform
import subprocess
import shutil
import logging
import base64
import requests
import time
import re
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify

# === 基础设施 ===
from core.config import (
    CARDS_FOLDER, DATA_DIR, BASE_DIR, TRASH_FOLDER,
    load_config, save_config
)
from core.context import ctx
from core.data.ui_store import load_ui_data, save_ui_data, UI_DATA_FILE
from core.consts import SIDECAR_EXTENSIONS, RESERVED_RESOURCE_NAMES, APP_VERSION

# === 核心服务 ===
from core.services.scan_service import request_scan, suppress_fs_events
from core.services.cache_service import schedule_reload, invalidate_wi_list_cache, update_card_cache
from core.services.card_service import resolve_ui_key

# === 工具函数 ===
from core.utils.filesystem import (
    cleanup_old_snapshots, write_snapshot_file
)
from core.utils.image import extract_card_info, write_card_metadata, find_sidecar_image

from core.utils.hash import _calculate_data_hash

bp = Blueprint('system', __name__)

logger = logging.getLogger(__name__)

@bp.route('/api/status')
def api_status():
    status = ctx.init_status.copy()
    status["is_docker"] = os.path.exists('/.dockerenv')
    return jsonify(status)

@bp.route('/api/scan_now', methods=['POST'])
def api_scan_now():
    """手动触发一次全量扫描（用于 watchdog 不可用或用户想立刻同步）"""
    try:
        request_scan(reason="manual")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    global CARDS_FOLDER
    try:
        new_config = request.json
        save_config(new_config)
        # 更新全局变量 CARDS_FOLDER
        raw_path = new_config.get('cards_dir', 'cards')
        if os.path.isabs(raw_path):
            new_full_path = raw_path
        else:
            new_full_path = os.path.join(BASE_DIR, raw_path)
        # 检查路径是否存在，不存在则尝试创建
        if not os.path.exists(new_full_path):
            try:
                os.makedirs(new_full_path)
            except Exception as e:
                return jsonify({"success": False, "msg": f"路径不存在且无法创建: {str(e)}"})
        CARDS_FOLDER = new_full_path

        # 处理资源目录配置
        resources_dir = new_config.get('resources_dir', 'resources')
        resources_path = os.path.join(BASE_DIR, resources_dir)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path)
            except Exception as e:
                # 只是警告，不阻止保存其他设置
                logger.warning(f"无法创建资源目录 {resources_path}: {str(e)}")

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/save_discord_token', methods=['POST'])
def api_save_discord_token():
    """专门为一键同步提供的简易接口"""
    try:
        token = request.json.get('token')
        if not token:
            return jsonify({"success": False, "msg": "Token 不能为空"})
        
        # 强制转换为字符串，并去除空格/引号
        if isinstance(token, dict):
            token = token.get('token', '') or token.get('value', '') or str(token)
        
        token = str(token).strip().strip('"').strip("'")
        
        if not token:
            return jsonify({"success": False, "msg": "无效的 Token 格式"})

        cfg = load_config()
        cfg['discord_token'] = token
        save_config(cfg)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/get_settings')
def api_get_settings():
    cfg = load_config()
    # 确保有默认值，防止前端 undefined
    if 'default_sort' not in cfg:
        cfg['default_sort'] = 'date_desc'
    
    # 注入当前程序版本
    cfg['app_version'] = APP_VERSION
    return jsonify(cfg)

@bp.route('/api/system_action', methods=['POST'])
def api_system_action():
    action = request.json.get('action')
    try:
        if action == 'open_folder':
            path = CARDS_FOLDER
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return jsonify({"success": True})
        # === 打开 Notes 目录 ===
        elif action == 'open_notes':
            notes_dir = os.path.join(DATA_DIR, 'assets', 'notes_images')
            
            # 确保目录存在
            if not os.path.exists(notes_dir):
                os.makedirs(notes_dir)
                
            path = notes_dir
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return jsonify({"success": True})
        elif action == 'backup_data':
            # 简单备份 ui_data.json
            if os.path.exists(UI_DATA_FILE):
                bk_name = f"ui_data_backup_{int(time.time())}.json"
                shutil.copy(UI_DATA_FILE, os.path.join(BASE_DIR, bk_name))
                return jsonify({"success": True, "msg": f"已备份为 {bk_name}"})
            return jsonify({"success": False, "msg": "暂无数据文件"})
        elif action == 'open_card_dir':
            card_id = request.json.get('card_id')
            if not card_id: return jsonify({"success": False, "msg": "ID missing"})
            
            full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
            full_path = os.path.abspath(full_path)
            target_dir = os.path.dirname(full_path)
            
            if not os.path.exists(target_dir):
                # 如果文件在根目录，target_dir 就是 CARDS_FOLDER
                target_dir = CARDS_FOLDER
                
            if platform.system() == "Windows":
                # Windows explorer /select 可以选中文件
                subprocess.Popen(f'explorer /select,"{full_path}"')
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", full_path])
            else:
                subprocess.Popen(["xdg-open", target_dir])
            return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})
    return jsonify({"success": False, "msg": "Unknown action"})

@bp.route('/api/trash/open', methods=['POST'])
def api_open_trash():
    """在资源管理器中打开回收站"""
    try:
        if not os.path.exists(TRASH_FOLDER):
            os.makedirs(TRASH_FOLDER)
            
        path = TRASH_FOLDER
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/trash/empty', methods=['POST'])
def api_empty_trash():
    """清空回收站"""
    try:
        if os.path.exists(TRASH_FOLDER):
            # 遍历删除内容，保留 .trash 文件夹本身
            for filename in os.listdir(TRASH_FOLDER):
                file_path = os.path.join(TRASH_FOLDER, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f'Failed to delete {file_path}. Reason: {e}')
        return jsonify({"success": True, "msg": "回收站已清空"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/create_snapshot', methods=['POST'])
def api_create_snapshot():
    try:
        # 这里的 suppress_fs_events 依然需要，因为备份也是写文件
        suppress_fs_events(1.0)
        
        req_data = request.json
        target_id = req_data.get('id')
        snapshot_type = req_data.get('type', 'card') 
        label = req_data.get('label', '').strip()
        
        # === 获取前端传来的未保存内容 ===
        unsaved_content = req_data.get('content') 

        # 获取 compact 参数，默认为 False
        compact = req_data.get('compact', False)

        if not target_id: return jsonify({"success": False, "msg": "ID missing"})

        cfg = load_config()
        system_backups_dir = os.path.join(DATA_DIR, 'system', 'backups')
        
        src_path = ""
        backups_root = ""
        
        # === 路径解析逻辑 (保持不变) ===
        if snapshot_type == 'lorebook':
            if target_id.startswith('embedded::'):
                real_card_id = target_id.replace('embedded::', '')
                src_path = os.path.join(CARDS_FOLDER, real_card_id.replace('/', os.sep))
                backups_root = os.path.join(system_backups_dir, 'cards')
                snapshot_type = 'card' 
                # 注意：如果是嵌入式WI，前端传来的 content 是整个卡片数据，所以逻辑兼容
            elif target_id.startswith('global::') or target_id.startswith('resource::'):
                src_path = req_data.get('file_path')
                backups_root = os.path.join(system_backups_dir, 'lorebooks')
            else:
                src_path = target_id
                backups_root = os.path.join(system_backups_dir, 'lorebooks')
        else:
            rel_path = target_id.replace('/', os.sep)
            src_path = os.path.join(CARDS_FOLDER, rel_path)
            backups_root = os.path.join(system_backups_dir, 'cards')

        if not src_path or not os.path.exists(src_path):
            return jsonify({"success": False, "msg": f"源文件不存在: {src_path}"})

        # === 目标文件命名 ===
        filename = os.path.basename(src_path)
        name_no_ext = os.path.splitext(filename)[0]
        ext = os.path.splitext(filename)[1]
        is_png = (ext.lower() == '.png')
        
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip() or "unnamed_backup"
        target_dir = os.path.join(backups_root, safe_dir_name)
        if not os.path.exists(target_dir): os.makedirs(target_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if label:
            safe_label = re.sub(r'[\\/:*?"<>|]', '-', label)
            backup_filename = f"{name_no_ext}_{timestamp}__KEY__{safe_label}{ext}"
        else:
            backup_filename = f"{name_no_ext}_{timestamp}{ext}"
            
        dst_path = os.path.join(target_dir, backup_filename)
        
        # === 清理旧的手动快照 ===
        cfg = load_config()
        # 读取配置，默认为 20
        manual_limit = cfg.get('snapshot_limit_manual', 20)
        # 限制范围 1 ~ 200
        manual_limit = max(1, min(manual_limit, 200))
        
        cleanup_old_snapshots(target_dir, manual_limit, prefix_filter=None)

        # === 执行快照写入 ===
        # 使用新函数，传入 unsaved_content
        success = write_snapshot_file(src_path, dst_path, unsaved_content, is_png, compact=compact)
        
        if not success:
             return jsonify({"success": False, "msg": "快照写入失败"})

        # === 处理 JSON 伴生图 (Copy Only) ===
        # 如果是 JSON 卡片，我们还需要备份它的图片
        # 注意：图片通常不会在编辑器里被修改（除非换图，但换图通常会立即保存）
        # 所以图片直接复制原文件即可
        if snapshot_type == 'card' and not is_png:
            sidecar = find_sidecar_image(src_path)
            if sidecar:
                sidecar_ext = os.path.splitext(sidecar)[1]
                if label:
                    side_name = f"{name_no_ext}_{timestamp}__KEY__{safe_label}{sidecar_ext}"
                else:
                    side_name = f"{name_no_ext}_{timestamp}{sidecar_ext}"
                try:
                    shutil.copy2(sidecar, os.path.join(target_dir, side_name))
                except:
                    pass

        return jsonify({"success": True, "msg": f"快照已保存", "path": dst_path})

    except Exception as e:
        logger.error(f"Snapshot error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

# ================= 智能快照逻辑 =================
@bp.route('/api/smart_auto_snapshot', methods=['POST'])
def api_smart_auto_snapshot():
    try:
        # 自动备份涉及文件写入，抑制 watchdog
        suppress_fs_events(1.0)
        
        req_data = request.json
        target_id = req_data.get('id')
        snapshot_type = req_data.get('type', 'card')
        content = req_data.get('content') # 当前编辑器内容的 V3 标准对象
        
        if not content:
            return jsonify({"success": False, "msg": "Content empty"})

        # 1. 计算当前内容的 Hash
        current_hash = _calculate_data_hash(content)

        # 2. 确定备份目录 (复用之前的逻辑)
        cfg = load_config()
        res_base = os.path.join(BASE_DIR, cfg.get('resources_dir', 'resources'))
        backups_root = ""
        filename = ""
        
        # 解析路径逻辑
        if snapshot_type == 'lorebook':
            if target_id.startswith('embedded::'):
                real_card_id = target_id.replace('embedded::', '')
                filename = os.path.basename(real_card_id)
                backups_root = os.path.join(res_base, 'backups', 'cards')
                snapshot_type = 'card' # 嵌入式WI实际上是存为角色卡快照
            elif target_id.startswith('global::') or target_id.startswith('resource::'):
                path = req_data.get('file_path')
                filename = os.path.basename(path)
                backups_root = os.path.join(res_base, 'backups', 'lorebooks')
            else:
                backups_root = os.path.join(res_base, 'backups', 'lorebooks')
                filename = "Unknown.json"
        else:
            filename = os.path.basename(target_id)
            backups_root = os.path.join(res_base, 'backups', 'cards')

        name_no_ext = os.path.splitext(filename)[0]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip()
        target_dir = os.path.join(backups_root, safe_dir_name)

        # 3. 智能比对：检查现有备份
        # 为了性能，我们只检查最近的 20 个备份（避免历史太久远导致 IO 爆炸）
        if os.path.exists(target_dir):
            existing_backups = sorted(
                [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.endswith(('.json', '.png'))],
                key=os.path.getmtime,
                reverse=True
            )[:20] 

            for backup_path in existing_backups:
                try:
                    # 读取备份内容
                    info = extract_card_info(backup_path)
                    if info:
                        # 如果是 PNG，info 是字典；如果是 JSON，info 也是字典
                        # 针对嵌入式 WI 的特殊提取：如果当前保存的是 WI，我们需要从备份卡片中提取 WI 来比对
                        if snapshot_type == 'card' and req_data.get('is_embedded_wi_only'):
                            # 提取备份中的 character_book
                            data_block = info.get('data', info)
                            backup_content = data_block.get('character_book', {})
                        else:
                            backup_content = info
                        
                        backup_hash = _calculate_data_hash(backup_content)
                        
                        if backup_hash == current_hash:
                            return jsonify({
                                "success": True, 
                                "status": "skipped", 
                                "msg": "内容未变更，跳过备份"
                            })
                except Exception as e:
                    print(f"Error checking backup {backup_path}: {e}")
                    continue

        if not os.path.exists(target_dir): os.makedirs(target_dir)

        # === 清理旧的自动快照 ===
        # 在确定 target_dir 后，写入文件前
        cfg = load_config()
        auto_limit = cfg.get('snapshot_limit_auto', 5)
        auto_limit = max(1, min(auto_limit, 50))
        
        # 自动快照文件名包含 __AUTO__，我们以此过滤
        cleanup_old_snapshots(target_dir, auto_limit, prefix_filter="__AUTO__")

        # 4. 执行保存 (如果没被跳过)
        # 复用之前的 create_snapshot 逻辑，但这里我们自己在内部处理，或者调用内部函数
        # 为了方便，这里简单重写核心路径逻辑 
        ext = '.json' if snapshot_type == 'lorebook' else '.png' # 默认后缀
        # 尝试沿用原文件后缀
        if req_data.get('file_path'):
            ext = os.path.splitext(req_data.get('file_path'))[1]
        elif target_id.endswith('.png'): ext = '.png'
        elif target_id.endswith('.json'): ext = '.json'

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"{name_no_ext}_{timestamp}__AUTO__{ext}"
        dst_path = os.path.join(target_dir, backup_filename)
        
        # 写入
        is_png = (ext.lower() == '.png')
        
        # 如果是 PNG，我们需要源文件作为底板
        src_path = ""
        if snapshot_type == 'card':
             # 重新构建源路径
             src_path = os.path.join(CARDS_FOLDER, target_id.replace('/', os.sep))
        elif req_data.get('file_path'):
             src_path = req_data.get('file_path')

        if is_png and os.path.exists(src_path):
            write_snapshot_file(src_path, dst_path, content, True)
        else:
            # JSON 直接写
            write_snapshot_file(None, dst_path, content, False, compact=True)

        return jsonify({
            "success": True, 
            "status": "created", 
            "path": dst_path,
            "msg": "自动快照已生成"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})

# 获取备份列表接口
@bp.route('/api/list_backups', methods=['POST'])
def api_list_backups():
    try:
        target_id = request.json.get('id')
        snapshot_type = request.json.get('type', 'card')
        file_path_param = request.json.get('file_path')
        
        system_backups_dir = os.path.join(DATA_DIR, 'system', 'backups')
        
        # 确定备份根目录和目标文件名
        backups_root = ""
        filename = ""
        
        if snapshot_type == 'lorebook':
            if target_id and target_id.startswith('embedded::'):
                # 内嵌WI：备份在 cards 目录下，使用宿主卡片名
                real_card_id = target_id.replace('embedded::', '')
                filename = os.path.basename(real_card_id)
                backups_root = os.path.join(system_backups_dir, 'cards')
            else:
                # 独立WI：备份在 lorebooks 目录下
                # 优先使用文件名，如果没有则尝试从 ID 解析
                if file_path_param:
                    filename = os.path.basename(file_path_param)
                elif target_id:
                    filename = os.path.basename(target_id)
                backups_root = os.path.join(system_backups_dir, 'lorebooks')
        else:
            # 角色卡
            filename = os.path.basename(target_id)
            backups_root = os.path.join(system_backups_dir, 'cards')

        name_no_ext = os.path.splitext(filename)[0]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip()
        target_dir = os.path.join(backups_root, safe_dir_name)

        backups = []
        if os.path.exists(target_dir):
            for f in os.listdir(target_dir):
                f_lower = f.lower()
                if not (f_lower.endswith('.png') or f_lower.endswith('.json')):
                    continue
                
                # 检查文件名是否包含原名主体 (防止目录混用)
                if name_no_ext not in f:
                    continue

                full_p = os.path.join(target_dir, f)
                
                # 解析标签
                is_key = "__KEY__" in f
                is_auto = "__AUTO__" in f
                label = ""
                
                if is_key:
                    parts = f.split("__KEY__")
                    if len(parts) > 1:
                        # 去掉扩展名取标签
                        label = os.path.splitext(parts[1])[0]
                elif is_auto:
                    label = "Auto Save"

                backups.append({
                    "filename": f,
                    "path": full_p,
                    "mtime": os.path.getmtime(full_p),
                    "size": os.path.getsize(full_p),
                    "is_key": is_key,
                    "is_auto": is_auto,
                    "label": label,
                    "ext": os.path.splitext(f)[1]
                })
        
        backups.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify({"success": True, "backups": backups, "backup_dir": target_dir})

    except Exception as e:
        logger.error(f"List backups error: {e}")
        return jsonify({"success": False, "msg": str(e)})

# 回滚接口
@bp.route('/api/restore_backup', methods=['POST'])
def api_restore_backup():
    try:
        suppress_fs_events(2.0)
        backup_path = request.json.get('backup_path')
        target_id = request.json.get('target_id')
        type_ = request.json.get('type')
        target_file_path_param = request.json.get('target_file_path')
        
        if not os.path.exists(backup_path):
            return jsonify({"success": False, "msg": "备份文件丢失"})

        # 确定目标路径
        target_path = ""
        if type_ == 'lorebook':
            if target_id.startswith('embedded::'):
                real_card_id = target_id.replace('embedded::', '')
                target_path = os.path.join(CARDS_FOLDER, real_card_id.replace('/', os.sep))
            else:
                target_path = target_file_path_param
        else:
            target_path = os.path.join(CARDS_FOLDER, target_id.replace('/', os.sep))
            
        if not target_path: return jsonify({"success": False, "msg": "目标路径解析失败"})

        # 1. 物理覆盖 (恢复图片像素 或 JSON 内容)
        shutil.copy2(backup_path, target_path)
        
        # 2. [关键修改] 标准化重写
        # 读取刚刚恢复的文件，进行 deterministic_sort 后原地写回
        # 这样能保证回滚后的文件格式与当前系统保存的格式完全一致 (Key排序、缩进等)
        try:
            # 提取刚刚恢复的文件信息
            info = extract_card_info(target_path)
            if info:
                # data_block 提取逻辑，确保兼容 V2/V3
                data_to_write = info
                
                # 如果是 V3 嵌套结构，extract_card_info 返回的可能是最外层
                # write_card_metadata 会再次调用 deterministic_sort
                # 所以我们只需要把读取到的 info 原样传进去，write_card_metadata 会负责清洗和排序
                
                # 执行标准化写入 (这会更新 last_modified，并统一 JSON 格式)
                write_card_metadata(target_path, data_to_write)
                
                print(f"Normalized restored file: {target_path}")
        except Exception as e:
            logger.warning(f"Restored file normalization failed (non-fatal): {e}")

        # 3. 恢复伴生图 (针对 JSON 卡片)
        if target_path.lower().endswith('.json'):
            backup_base = os.path.splitext(backup_path)[0]
            backup_dir = os.path.dirname(backup_path)
            target_dir = os.path.dirname(target_path)
            target_base = os.path.splitext(os.path.basename(target_path))[0]
            
            for ext in SIDECAR_EXTENSIONS:
                side_bk = backup_base + ext
                if os.path.exists(side_bk):
                    shutil.copy2(side_bk, os.path.join(target_dir, target_base + ext))
                    break

        # 4. 刷新缓存
        if type_ == 'lorebook' and not target_id.startswith('embedded'):
            invalidate_wi_list_cache()
        else:
            real_id = target_id.replace('embedded::', '') if 'embedded::' in target_id else target_id
            update_card_cache(real_id, target_path)
            schedule_reload(reason="restore_backup")

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Restore error: {e}")
        return jsonify({"success": False, "msg": str(e)})

# 读取文件内容用于 Diff
@bp.route('/api/read_file_content', methods=['POST'])
def api_read_file_content():
    try:
        path = request.json.get('path')
        if not os.path.exists(path): return jsonify({"success": False})
        
        # 如果是图片，提取元数据；如果是JSON，直接读
        if path.lower().endswith('.png'):
            info = extract_card_info(path)
            return jsonify({"success": True, "data": info})
        else:
            with open(path, 'r', encoding='utf-8') as f:
                return jsonify({"success": True, "data": json.load(f)})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/create_resource_folder', methods=['POST'])
def api_create_resource_folder():
    try:
        data = request.json
        card_id = data.get('card_id')
        if not card_id:
            return jsonify({"success": False, "msg": "角色卡ID缺失"})
        
        # 获取资源目录配置
        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)
        
        # 确保资源目录存在
        if not os.path.exists(resources_dir):
            os.makedirs(resources_dir)
        
        # 获取角色卡信息
        card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        info = extract_card_info(card_path)
        if not info:
            return jsonify({"success": False, "msg": "未找到角色卡"})
        
        # 获取角色名称
        data_block = info.get('data', {}) if 'data' in info else info
        char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(card_path))[0]
        
        # 创建资源目录（与角色卡同名）
        resource_folder_name = char_name
        resource_folder_path = os.path.join(resources_dir, resource_folder_name)
        
        # 处理重名情况
        counter = 1
        original_path = resource_folder_path
        while os.path.exists(resource_folder_path):
            resource_folder_name = f"{char_name}_{counter}"
            resource_folder_path = os.path.join(resources_dir, resource_folder_name)
            counter += 1
        
        # 创建目录
        os.makedirs(resource_folder_path)
        
        # 更新ui_data
        ui_data = load_ui_data()
        key = resolve_ui_key(card_id) # 使用智能 Key 解析

        if key not in ui_data:
            ui_data[key] = {}
        ui_data[key]['resource_folder'] = resource_folder_name
        save_ui_data(ui_data)

        # 更新缓存
        target_id = card_id
        # 如果 key 指向的是文件夹(bundle)，我们要更新该 bundle 对应的主卡片缓存
        if key in ctx.cache.bundle_map:
            target_id = ctx.cache.bundle_map[key]

        ctx.cache.update_card_data(target_id, {"resource_folder": resource_folder_name})
        
        return jsonify({
            "success": True,
            "resource_folder": resource_folder_name,
            "resource_path": resource_folder_path
        })
    except Exception as e:
        logger.error(f"Create resource folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/set_resource_folder', methods=['POST'])
def api_set_resource_folder():
    try:
        data = request.json
        card_id = data.get('card_id')
        resource_path = data.get('resource_path')
        
        if not card_id:
            return jsonify({"success": False, "msg": "角色卡ID缺失"})
        
        if not resource_path:
            return jsonify({"success": False, "msg": "资源路径不能为空"})
        
        # 获取资源目录配置
        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)
        
        # 确保资源目录存在
        if not os.path.exists(resources_dir):
            os.makedirs(resources_dir)
        
        # 处理路径
        if os.path.isabs(resource_path):
            # 绝对路径，直接使用
            final_path = resource_path
            resource_folder_name = resource_path  # 保存完整绝对路径
        else:
            # 相对路径，相对于resources目录
            final_path = os.path.join(resources_dir, resource_path)
            resource_folder_name = resource_path
        
        # 检查保留字
        # 统一取第一层目录名进行检查
        check_name = resource_path.replace('\\', '/').split('/')[0] if 'resource_path' in locals() else resource_folder_name
        if check_name.lower() in RESERVED_RESOURCE_NAMES:
            return jsonify({"success": False, "msg": f"无法使用 '{check_name}' 作为资源目录，这是系统保留名称。"})

        # 检查目录是否存在，不存在则创建
        if not os.path.exists(final_path):
            os.makedirs(final_path)
        
        # 更新ui_data
        ui_data = load_ui_data()
        key = resolve_ui_key(card_id) # 使用智能 Key 解析

        if key not in ui_data:
            ui_data[key] = {}
        ui_data[key]['resource_folder'] = resource_folder_name
        save_ui_data(ui_data)

        # 更新缓存
        target_id = card_id
        if key in ctx.cache.bundle_map:
            target_id = ctx.cache.bundle_map[key]

        ctx.cache.update_card_data(target_id, {"resource_folder": resource_folder_name})
        
        return jsonify({
            "success": True,
            "resource_folder": resource_folder_name,
            "resource_path": final_path
        })
    except Exception as e:
        logger.error(f"Set resource folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/open_resource_folder', methods=['POST'])
def api_open_resource_folder():
    try:
        data = request.json
        card_id = data.get('card_id')
        if not card_id:
            return jsonify({"success": False, "msg": "角色卡ID缺失"})
        
        # 获取资源目录配置
        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)
        
        # 获取角色卡资源目录
        ui_data = load_ui_data()
        # 1. 优先尝试智能解析 Key (处理包模式)
        key = resolve_ui_key(card_id)
        resource_folder = ui_data.get(key, {}).get('resource_folder')

        # 2. 兜底：如果智能解析没找到，尝试直接用 card_id 找 (兼容旧数据)
        if not resource_folder and key != card_id:
            resource_folder = ui_data.get(card_id, {}).get('resource_folder')
        
        if not resource_folder:
            return jsonify({"success": False, "msg": "未设置资源目录"})
        
        # 处理绝对路径和相对路径
        if os.path.isabs(resource_folder):
            resource_path = resource_folder
        else:
            resource_path = os.path.join(resources_dir, resource_folder)
        
        # 检查目录是否存在
        if not os.path.exists(resource_path):
            return jsonify({"success": False, "msg": f"资源目录不存在: {resource_path}"})
        
        # 打开目录
        try:
            if platform.system() == "Windows":
                # 使用 normpath 确保路径格式正确
                os.startfile(os.path.normpath(resource_path))
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", resource_path])
            else:
                # 检查是否在 Docker 中 (docker 会在根目录创建 .dockerenv)
                if os.path.exists('/.dockerenv'):
                    return jsonify({"success": False, "msg": "程序运行在 Docker 环境下，无法直接在浏览器触发打开宿主机文件夹的操作。请手动在宿主机文件浏览器中查看挂载的资源目录。"})
                subprocess.Popen(["xdg-open", resource_path])
            
            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Open resource folder failed: {e}")
            return jsonify({"success": False, "msg": f"打开目录时出错: {str(e)}"})
    except Exception as e:
        logger.error(f"Open resource folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/list_resource_files', methods=['POST'])
def api_list_resource_files():
    """列出资源目录下的所有文件以及详细信息"""
    try:
        data = request.json
        card_id = data.get('card_id')
        if not card_id:
            return jsonify({"success": False, "msg": "角色卡ID缺失"})

        # 获取资源目录配置
        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)

        # 获取角色卡资源目录
        ui_data = load_ui_data()
        key = resolve_ui_key(card_id)
        resource_folder = ui_data.get(key, {}).get('resource_folder')

        if not resource_folder and key != card_id:
            resource_folder = ui_data.get(card_id, {}).get('resource_folder')

        if not resource_folder:
            return jsonify({"success": True, "files": []})

        # 处理绝对路径和相对路径
        if os.path.isabs(resource_folder):
            resource_path = resource_folder
        else:
            resource_path = os.path.join(resources_dir, resource_folder)

        if not os.path.exists(resource_path):
            return jsonify({"success": True, "files": []})

        files = []
        for f in os.listdir(resource_path):
            full_path = os.path.join(resource_path, f)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "url": f"/resources_file/{resource_folder}/{f}" if not os.path.isabs(resource_folder) else f"/api/raw_resource_file?path={base64.b64encode(full_path.encode()).decode()}"
                })
        
        # 按修改时间倒序排列
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify({"success": True, "files": files, "folder_name": resource_folder})
    except Exception as e:
        logger.error(f"List resource files error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/delete_resource_file', methods=['POST'])
def api_delete_resource_file():
    try:
        data = request.json
        card_id = data.get('card_id')
        filename = data.get('filename')
        if not card_id or not filename:
            return jsonify({"success": False, "msg": "参数缺失"})

        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)

        ui_data = load_ui_data()
        key = resolve_ui_key(card_id)
        resource_folder = ui_data.get(key, {}).get('resource_folder') or ui_data.get(card_id, {}).get('resource_folder')

        if not resource_folder:
            return jsonify({"success": False, "msg": "未找到资源目录"})

        # 防止目录穿越
        if '..' in filename or '/' in filename or '\\' in filename:
             return jsonify({"success": False, "msg": "非法文件名"})

        if os.path.isabs(resource_folder):
            resource_path = resource_folder
        else:
            resource_path = os.path.join(resources_dir, resource_folder)

        file_path = os.path.join(resource_path, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "msg": "文件不存在"})
    except Exception as e:
        logger.error(f"Delete resource file error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/upload_resource_file', methods=['POST'])
def api_upload_resource_file():
    try:
        card_id = request.form.get('card_id')
        file = request.files.get('file')
        if not card_id or not file:
            return jsonify({"success": False, "msg": "参数缺失"})

        config = load_config()
        resources_dir_name = config.get('resources_dir', 'resources')
        resources_dir = os.path.join(BASE_DIR, resources_dir_name)

        ui_data = load_ui_data()
        key = resolve_ui_key(card_id)
        resource_folder = ui_data.get(key, {}).get('resource_folder') or ui_data.get(card_id, {}).get('resource_folder')

        if not resource_folder:
            return jsonify({"success": False, "msg": "未设置资源目录"})

        if os.path.isabs(resource_folder):
            resource_path = resource_folder
        else:
            resource_path = os.path.join(resources_dir, resource_folder)

        if not os.path.exists(resource_path):
            os.makedirs(resource_path)

        save_path = os.path.join(resource_path, file.filename)
        file.save(save_path)
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Upload resource file error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/raw_resource_file')
def api_serve_raw_resource_file():
    """提供物理路径文件的访问 (用于绝对路径挂载)"""
    try:
        path_b64 = request.args.get('path')
        if not path_b64: return "Missing path", 400
        real_path = base64.b64decode(path_b64).decode()
        if not os.path.exists(real_path): return "Not found", 404
        return send_from_directory(os.path.dirname(real_path), os.path.basename(real_path))
    except:
        return "Error", 500

@bp.route('/api/send_to_st', methods=['POST'])
def api_send_to_st():
    try:
        card_id = request.json.get('card_id')
        if not card_id:
            return jsonify({"success": False, "msg": "Card ID missing"})

        # 1. 获取配置
        cfg = load_config()
        st_base_url = cfg.get('st_url', 'http://127.0.0.1:8000').rstrip('/')
        username = cfg.get('st_username', '')
        password = cfg.get('st_password', '')
        auth_type = cfg.get('st_auth_type', 'basic') # 获取认证类型
        
        # 目标 API
        target_url = f"{st_base_url}/api/characters/import"

        # 2. 检查文件
        rel_path = card_id.replace('/', os.sep)
        file_path = os.path.join(CARDS_FOLDER, rel_path)
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "Local file not found"})

        # 3. 创建 Session (保持 Cookie)
        session = requests.Session()
        
        # 伪装 User-Agent
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        # === 处理 认证 ===
        auth_headers = {}

        if password:
            if auth_type == 'web':
                # === Web Login 模式 ===
                login_url = f"{st_base_url}/api/users/login"
                login_payload = {"handle": username, "password": password}
                try:
                    # 先尝试登录获取 Cookie
                    login_resp = session.post(login_url, json=login_payload, timeout=5)
                    if login_resp.status_code != 200:
                        return jsonify({"success": False, "msg": f"Web登录失败 ({login_resp.status_code}): 请检查用户名密码"})
                except Exception as e:
                    return jsonify({"success": False, "msg": f"无法连接到 ST 登录接口: {str(e)}"})
            else:
                # === Basic Auth 模式 (原有逻辑) ===
                # 如果用户名为空，ST 有时默认是 'user' 或者空，视 ST 配置而定，这里直接编码配置的值
                # base64 已经在头部 import 过了
                auth_str = f"{username}:{password}"
                auth_token = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
                auth_headers["Authorization"] = f"Basic {auth_token}"
            
                # 尝试访问主页获取 Cookie
                try:
                    session.get(st_base_url, timeout=5)
                except requests.exceptions.ConnectionError:
                    return jsonify({"success": False, "msg": "无法连接到 SillyTavern，请确认它已启动。"})

        # 获取 CSRF Token 并添加到 Header
        csrf_token = session.cookies.get('XSRF-TOKEN')
        if csrf_token:
            session.headers.update({'X-XSRF-TOKEN': csrf_token})

        # 4. 发送文件
        file_ext = os.path.splitext(file_path)[1].lower()
        with open(file_path, 'rb') as f:
            # 区分处理 PNG 和 JSON 
            if file_ext == '.json':
                files = {'avatar': ('card.json', f, 'application/json')}
                data = {'file_type': 'json'} 
            else:
                files = {'avatar': ('card.png', f, 'image/png')}
                data = {'file_type': 'png'}
            
            # 同时传入 files 和 data
            response = session.post(
                target_url, 
                files=files, 
                data=data, 
                timeout=10, 
                headers=auth_headers
            )

        # 5. 处理结果
        if response.status_code == 200:
            return jsonify({"success": True, "st_response": response.json() if response.content else "OK"})
        elif response.status_code == 400:
            return jsonify({"success": False, "msg": f"ST 请求错误 (400): {response.text}"})
        elif response.status_code == 401:
            return jsonify({"success": False, "msg": "ST 认证失败 (401): Basic Auth 密码错误。"})
        elif response.status_code == 403:
            # 细化 403 提示
            err_msg = "ST 权限拒绝 (403): "
            if auth_type == 'web':
                err_msg += "Web认证失效或CSRF校验失败。请尝试重启 ST Manager 或检查 ST 日志。"
            else:
                err_msg += "请在 SillyTavern 的 config.yaml 中设置 'disableCsrfProtection: true' 或尝试切换到 Web Login 模式。"
            return jsonify({"success": False, "msg": err_msg})
        else:
            return jsonify({"success": False, "msg": f"ST Error: {response.status_code} - {response.text}"})

    except Exception as e:
        logger.error(f"Send to ST error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/list_resource_skins', methods=['POST'])
def api_list_resource_skins():
    """列出资源目录下的所有图片文件"""
    try:
        folder_name = request.json.get('folder_name')
        if not folder_name:
            return jsonify({"success": True, "skins": []})

        # 获取配置的资源根目录
        cfg = load_config()
        res_base = os.path.join(BASE_DIR, cfg.get('resources_dir', 'resources'))
        target_dir = os.path.join(res_base, folder_name)

        if not os.path.exists(target_dir):
            return jsonify({"success": True, "skins": []})

        skins = []
        # 支持的图片扩展名
        valid_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        
        for f in os.listdir(target_dir):
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                skins.append(f)
        
        # 排序，保证顺序稳定
        skins.sort()
        return jsonify({"success": True, "skins": skins})
    except Exception as e:
        logger.error(f"List skins error: {e}")
        return jsonify({"success": False, "msg": str(e)})

# API: 打开角色卡所在路径
@bp.route('/api/open_path', methods=['POST'])
def api_open_path():
    try:
        path = request.json.get('path')
        is_file = request.json.get('is_file', False)

        relative_to_base = request.json.get('relative_to_base', False)
        
        if not path:
            return jsonify({"success": False, "msg": "Path missing"})
            
        # 如果是相对路径，尝试基于 BASE_DIR 解析 (视情况而定，这里假设传入的是绝对路径或已处理好的路径)
        # 为了安全，也可以限制只能打开 CARDS_FOLDER 或 RESOURCES_FOLDER 下的路径
        
        target_open = path
        if relative_to_base:
            target_open = os.path.join(BASE_DIR, path)

        if is_file and os.path.isfile(path):
            target_open = os.path.dirname(path)
            
        if not os.path.exists(target_open):
            return jsonify({"success": False, "msg": f"路径不存在: {target_open}"})

        if platform.system() == "Windows":
            os.startfile(target_open)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", target_open])
        else:
            subprocess.Popen(["xdg-open", target_open])
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/upload_background', methods=['POST'])
def api_upload_background():
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({"success": False, "msg": "未接收到文件"})
        
        # 1. 确定保存路径 (static/backgrounds)
        bg_folder = os.path.join(DATA_DIR, 'assets', 'backgrounds')
        if not os.path.exists(bg_folder):
            os.makedirs(bg_folder)
            
        # 2. 生成安全的文件名 (使用时间戳防止重名)
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
             return jsonify({"success": False, "msg": "不支持的图片格式"})
             
        new_filename = f"bg_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        save_path = os.path.join(bg_folder, new_filename)
        
        # 3. 保存文件
        file.save(save_path)
        
        # 4. 返回相对 URL
        # 注意：前端通过 /static/backgrounds/filename 访问
        url = f"/assets/backgrounds/{new_filename}"
        
        return jsonify({"success": True, "url": url})
        
    except Exception as e:
        logger.error(f"Background upload error: {e}")
        return jsonify({"success": False, "msg": str(e)})