import os
import json
import logging
from flask import Blueprint, request, jsonify
from core.config import BASE_DIR, load_config
from core.utils.filesystem import sanitize_filename

logger = logging.getLogger(__name__)
bp = Blueprint('extensions', __name__)

def _get_paths():
    """获取配置的路径"""
    cfg = load_config()
    
    # 获取 regex 路径
    raw_regex = cfg.get('regex_dir', 'data/library/extensions/regex')
    regex_root = raw_regex if os.path.isabs(raw_regex) else os.path.join(BASE_DIR, raw_regex)
    
    # 获取 scripts 路径
    raw_scripts = cfg.get('scripts_dir', 'data/library/extensions/tavern_helper')
    scripts_root = raw_scripts if os.path.isabs(raw_scripts) else os.path.join(BASE_DIR, raw_scripts)
    
    # 确保目录存在
    for p in [regex_root, scripts_root]:
        if not os.path.exists(p):
            try: os.makedirs(p)
            except: pass
            
    return regex_root, scripts_root

@bp.route('/api/extensions/list', methods=['GET'])
def list_extensions():
    """
    列出扩展文件
    mode: 'regex' | 'scripts'
    filter_type: 'all' | 'global' | 'resource'
    """
    mode = request.args.get('mode', 'regex')
    filter_type = request.args.get('filter_type', 'all')
    
    items = []
    regex_global_root, scripts_global_root = _get_paths()
    
    # 确定目标全局目录和资源子目录名
    target_global_dir = regex_global_root if mode == 'regex' else scripts_global_root
    target_res_sub = "extensions/regex" if mode == 'regex' else "extensions/tavern_helper"

    # 1. 扫描全局目录
    if filter_type in ['all', 'global']:
        if os.path.exists(target_global_dir):
            for f in os.listdir(target_global_dir):
                if f.lower().endswith('.json'):
                    full_path = os.path.join(target_global_dir, f)
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f_obj:
                            data = json.load(f_obj)
                            # 尝试获取脚本名称
                            name = f
                            if isinstance(data, dict):
                                name = data.get('scriptName') or data.get('name') or f
                            elif isinstance(data, list) and mode == 'scripts':
                                # 旧版 ST 脚本可能是列表，通常没有顶层名字，用文件名
                                name = f
                                
                            items.append({
                                "id": f"global::{f}",
                                "name": name,
                                "filename": f,
                                "type": "global",
                                "path": os.path.relpath(full_path, BASE_DIR),
                                "mtime": os.path.getmtime(full_path)
                            })
                    except: pass

    # 2. 扫描资源目录
    if filter_type in ['all', 'resource']:
        cfg = load_config()
        res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
        
        if os.path.exists(res_root):
            try:
                res_folders = [d for d in os.listdir(res_root) if os.path.isdir(os.path.join(res_root, d))]
                for folder in res_folders:
                    target_dir = os.path.join(res_root, folder, target_res_sub.replace('/', os.sep))
                    if os.path.exists(target_dir):
                        for f in os.listdir(target_dir):
                            if f.lower().endswith('.json'):
                                full_path = os.path.join(target_dir, f)
                                try:
                                    # 简略读取以获取名称
                                    with open(full_path, 'r', encoding='utf-8') as f_obj:
                                        data = json.load(f_obj)
                                        name = f
                                        if isinstance(data, dict):
                                            name = data.get('scriptName') or data.get('name') or f
                                        
                                        items.append({
                                            "id": f"resource::{folder}::{f}",
                                            "name": name,
                                            "filename": f,
                                            "type": "resource",
                                            "source_folder": folder,
                                            "path": os.path.relpath(full_path, BASE_DIR),
                                            "mtime": os.path.getmtime(full_path)
                                        })
                                except: pass
            except Exception as e:
                logger.error(f"Error scanning resource extensions: {e}")

    # 按时间倒序
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return jsonify({"success": True, "items": items})

@bp.route('/api/extensions/upload', methods=['POST'])
def upload_extension():
    """
    上传并自动识别 Regex / Script
    """
    try:
        files = request.files.getlist('files')
        target_type = request.form.get('target_type') # 'regex' | 'scripts' (可选强制指定，否则自动检测)
        
        if not files:
            return jsonify({"success": False, "msg": "未接收到文件"})

        regex_root, scripts_root = _get_paths()
        success_count = 0
        failed_list = []
        
        for file in files:
            if not file.filename.lower().endswith('.json'):
                continue
                
            try:
                content = file.read()
                data = json.loads(content)
                file.seek(0) # 重置指针准备保存
                
                # === 自动检测类型 ===
                is_regex = False
                is_script = False
                
                # 1. 检测 Regex
                if isinstance(data, dict) and ('findRegex' in data or 'regex' in data or 'scriptName' in data):
                    is_regex = True
                
                # 2. 检测 ST Script (Tavern Helper)
                # 新版: dict with type='script' or has 'scripts' key
                if isinstance(data, dict) and (data.get('type') == 'script' or 'scripts' in data):
                    is_script = True
                # 旧版: list starting with ["scripts", ...]
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], str) and data[0] == 'scripts':
                    is_script = True
                
                # 决定保存路径
                final_dir = None
                
                # 如果前端强制指定了类型（例如在正则页拖拽），优先使用前端意图，但需校验
                if target_type == 'regex':
                    if is_regex: final_dir = regex_root
                elif target_type == 'scripts':
                    if is_script: final_dir = scripts_root
                else:
                    # 自动归类模式
                    if is_script: final_dir = scripts_root
                    elif is_regex: final_dir = regex_root
                
                if not final_dir:
                    failed_list.append(f"{file.filename} (格式不匹配)")
                    continue
                    
                # 保存文件
                safe_name = sanitize_filename(file.filename)
                save_path = os.path.join(final_dir, safe_name)
                
                # 防重名
                name_part, ext = os.path.splitext(safe_name)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(final_dir, f"{name_part}_{counter}{ext}")
                    counter += 1
                    
                file.save(save_path)
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error processing {file.filename}: {e}")
                failed_list.append(file.filename)

        msg = f"成功上传 {success_count} 个文件。"
        if failed_list:
            msg += f" 失败/跳过: {', '.join(failed_list)}"
            
        return jsonify({"success": True, "msg": msg})

    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})