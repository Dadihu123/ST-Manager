import os
import hashlib
import logging
from PIL import Image
import json
from flask import Blueprint, request, jsonify, send_from_directory

# === 基础设施 ===
from core.config import (
    CARDS_FOLDER, DATA_DIR, BASE_DIR, 
    load_config, THUMB_FOLDER, TRASH_FOLDER
)
from core.context import ctx

# === 工具函数 ===
from core.utils.image import (
    find_sidecar_image, get_default_card_image_path
)
from core.utils.filesystem import safe_move_to_trash, sanitize_filename, save_json_atomic

from core.services.card_service import resolve_ui_key
from core.data.ui_store import load_ui_data

logger = logging.getLogger(__name__)

bp = Blueprint('resources', __name__)

@bp.route('/cards_file/<path:filename>')
def serve_card_image(filename):
    """
    提供角色卡原图文件。
    如果请求的是 JSON 文件，会自动寻找并返回对应的伴生图片。
    """
    # 如果请求的是 JSON 文件，尝试寻找同名图片
    if filename.lower().endswith('.json'):
        full_path = os.path.join(CARDS_FOLDER, filename.replace('/', os.sep))
        sidecar = find_sidecar_image(full_path)
        if sidecar:
            # 发送找到的图片
            return send_from_directory(os.path.dirname(sidecar), os.path.basename(sidecar))
        else:
            # 找不到同名图片，返回系统默认图
            default_img = get_default_card_image_path()
            if os.path.exists(default_img):
                return send_from_directory(os.path.dirname(default_img), os.path.basename(default_img))
            return "No image found", 404
    
    return send_from_directory(CARDS_FOLDER, filename)

@bp.route('/api/thumbnail/<path:filename>')
def serve_thumbnail(filename):
    """
    按需生成并提供卡片缩略图。
    - 检查 WebP 缓存是否存在且有效。
    - 如果无效，则生成并保存为 WebP 格式。
    - 使用 ctx.thumb_semaphore 限制并发生成数量。
    """
    try:
        # 1. 构造原始文件和缩略图缓存的路径
        original_path = os.path.join(CARDS_FOLDER, filename.replace('/', os.sep))

        # 如果是 JSON，切换目标到其 Sidecar 图片
        if filename.lower().endswith('.json'):
            sidecar = find_sidecar_image(original_path)
            if not sidecar:
                default_img = get_default_card_image_path()
                if os.path.exists(default_img):
                    return send_from_directory(os.path.dirname(default_img), os.path.basename(default_img))
                return "No image found", 404
            original_path = sidecar
            # 使用图片文件名做 hash，避免 JSON 内容变了但图片没变导致重算
            filename = os.path.basename(sidecar)

        if not os.path.exists(original_path):
            default_img = get_default_card_image_path()
            if os.path.exists(default_img):
                return send_from_directory(os.path.dirname(default_img), os.path.basename(default_img))
            return "Card not found", 404

        # 使用原始路径的 hash 作为缓存文件名
        normalized_name = filename.replace('\\', '/')
        thumb_hash_name = hashlib.md5(normalized_name.encode('utf-8')).hexdigest() + ".webp"
        thumb_path = os.path.join(THUMB_FOLDER, thumb_hash_name)

        # 2. 检查缓存是否有效（文件存在且比原图新）
        if os.path.exists(thumb_path):
            original_mtime = os.path.getmtime(original_path)
            thumb_mtime = os.path.getmtime(thumb_path)
            if thumb_mtime >= original_mtime:
                return send_from_directory(THUMB_FOLDER, thumb_hash_name)

        # 3. 生成缩略图 (限制并发)
        # 如果获取不到信号量（当前满载），阻塞等待
        with ctx.thumb_semaphore:
            # 再次检查（防止排队期间被别的线程生成了）
            if os.path.exists(thumb_path) and os.path.getmtime(thumb_path) >= os.path.getmtime(original_path):
                return send_from_directory(THUMB_FOLDER, thumb_hash_name)

            with Image.open(original_path) as img:
                # 优化：使用 draft 模式加速加载
                img.draft('RGB', (300, 600)) 
                
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 优化：限制最大尺寸计算
                width, height = img.size
                if width > 300:
                    new_height = int(height * (300 / width))
                    # 使用 BILINEAR 平衡速度和质量
                    img = img.resize((300, new_height), Image.Resampling.BILINEAR)
                
                # 优化：生成 WebP，质量 75
                img.save(thumb_path, 'WEBP', quality=75, method=3)

        return send_from_directory(THUMB_FOLDER, thumb_hash_name)

    except Exception as e:
        logger.error(f"Thumbnail generation failed for {filename}: {e}")
        # 出错时返回默认图
        default_img = get_default_card_image_path()
        if os.path.exists(default_img):
            return send_from_directory(os.path.dirname(default_img), os.path.basename(default_img))
        return "Error", 500

@bp.route('/resources_file/<path:subpath>')
def serve_resource_file(subpath):
    """
    提供用户资源目录下的文件 (例如 skin 图片)。
    """
    # 兼容旧版逻辑：如果请求的是 notes/xxx，转发到 Note 图片目录
    if subpath.startswith('notes/') or subpath.startswith('notes\\'):
        real_filename = os.path.basename(subpath)
        return send_from_directory(os.path.join(DATA_DIR, 'assets', 'notes_images'), real_filename)

    # 正常请求指向配置的 resources_dir
    cfg = load_config()
    res_dir_conf = cfg.get('resources_dir', 'data/assets/card_assets')
    
    if os.path.isabs(res_dir_conf):
        res_base = res_dir_conf
    else:
        res_base = os.path.join(BASE_DIR, res_dir_conf)
        
    return send_from_directory(res_base, subpath)

@bp.route('/assets/backgrounds/<path:filename>')
def serve_background_assets(filename):
    """提供背景图片"""
    bg_dir = os.path.join(DATA_DIR, 'assets', 'backgrounds')
    return send_from_directory(bg_dir, filename)

@bp.route('/assets/notes/<path:filename>')
def serve_note_assets(filename):
    """提供笔记内嵌图片"""
    notes_dir = os.path.join(DATA_DIR, 'assets', 'notes_images')
    return send_from_directory(notes_dir, filename)

@bp.route('/api/delete_resource_file', methods=['POST'])
def api_delete_resource_file():
    try:
        data = request.json
        card_id = data.get('card_id')
        filename = data.get('filename')
        
        if not card_id or not filename:
            return jsonify({"success": False, "msg": "参数缺失"})

        # 1. 解析资源目录路径
        ui_data = load_ui_data()
        ui_key = resolve_ui_key(card_id)
        res_folder_name = ui_data.get(ui_key, {}).get('resource_folder')
        
        if not res_folder_name:
            return jsonify({"success": False, "msg": "该卡片未设置资源目录"})

        cfg = load_config()
        res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
        
        # 确定完整路径
        if os.path.isabs(res_folder_name):
            target_file = os.path.join(res_folder_name, filename)
        else:
            target_file = os.path.join(res_root, res_folder_name, filename)
            
        # 安全检查：防止目录遍历
        if not os.path.abspath(target_file).startswith(os.path.abspath(res_root)) and not os.path.isabs(res_folder_name):
             return jsonify({"success": False, "msg": "非法路径"})

        if not os.path.exists(target_file):
            return jsonify({"success": False, "msg": "文件不存在"})

        # 2. 移至回收站
        if safe_move_to_trash(target_file, TRASH_FOLDER):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "msg": "移动到回收站失败"})

    except Exception as e:
        logger.error(f"Delete resource file error: {e}")
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/upload_card_resource', methods=['POST'])
def api_upload_card_resource():
    """
    智能上传资源文件到角色对应的资源目录。
    - 图片 -> 资源根目录
    - 世界书 JSON -> /lorebooks 子目录
    - 其他 -> 资源根目录
    """
    try:
        card_id = request.form.get('card_id')
        file = request.files.get('file')
        
        if not card_id or not file:
            return jsonify({"success": False, "msg": "参数缺失"})

        # 1. 获取资源目录路径
        ui_data = load_ui_data()
        ui_key = resolve_ui_key(card_id)
        res_folder_name = ui_data.get(ui_key, {}).get('resource_folder')
        
        if not res_folder_name:
            return jsonify({"success": False, "msg": "该卡片尚未设置资源目录，请先在'管理'页创建。"})

        cfg = load_config()
        res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
        
        # 处理绝对路径/相对路径
        if os.path.isabs(res_folder_name):
            target_base_dir = res_folder_name
        else:
            target_base_dir = os.path.join(res_root, res_folder_name)
            
        if not os.path.exists(target_base_dir):
            os.makedirs(target_base_dir)

        # 2. 分析文件类型并确定子目录
        raw_filename = file.filename
        filename = sanitize_filename(raw_filename)
        ext = os.path.splitext(filename)[1].lower()
        sub_dir = "" # 默认根目录
        
        is_lorebook = False
        
        # 检测 JSON 是否为世界书
        if ext == '.json':
            try:
                content = file.read()
                file.seek(0)
                try:
                    data = json.loads(content)
                except:
                    data = {} # 解析失败，视为普通文件放根目录

                # A. 正则脚本特征: 包含 'findRegex'
                if isinstance(data, dict) and ('findRegex' in data or 'regex' in data):
                    sub_dir = "extensions/regex"
                
                # B. ST 脚本 (Tavern Helper)
                # 兼容旧版 (list) 和 新版 (dict type='script')
                elif (isinstance(data, dict) and (data.get('type') == 'script' or 'scripts' in data)) or \
                     (isinstance(data, list) and len(data) > 0 and isinstance(data[0], str) and data[0] == 'scripts'):
                    sub_dir = "extensions/tavern_helper"
                
                # C. 世界书
                elif (isinstance(data, dict) and ('entries' in data)) or \
                     (isinstance(data, list) and len(data) > 0 and ('keys' in data[0] or 'key' in data[0])):
                    sub_dir = "lorebooks"
                    is_lorebook = True
                
                # D. 兜底: 无法识别的 JSON 放在根目录，或者你可以指定一个 'misc' 目录
                else:
                    sub_dir = "" 
            except Exception as e:
                print(f"JSON detection failed: {e}")
                sub_dir = "" 

        # 3. 构建最终路径
        final_dir = os.path.join(target_base_dir, sub_dir.replace('/', os.sep))
        if not os.path.exists(final_dir):
            os.makedirs(final_dir)
            
        save_path = os.path.join(final_dir, filename)
        
        # 4. 防重名 (Auto Increment)
        name_part, ext_part = os.path.splitext(filename)
        counter = 1
        while os.path.exists(save_path):
            save_path = os.path.join(final_dir, f"{name_part}_{counter}{ext_part}")
            counter += 1
            
        # 5. 保存文件
        file.save(save_path)
        
        return jsonify({
            "success": True, 
            "msg": f"已存入 {sub_dir if sub_dir else '根目录'}",
            "filename": os.path.basename(save_path),
            "is_lorebook": is_lorebook,
            "category": sub_dir
        })

    except Exception as e:
        logger.error(f"Resource upload error: {e}") 
        return jsonify({"success": False, "msg": str(e)})
    
@bp.route('/api/scripts/save', methods=['POST'])
def api_save_script_file():
    """
    保存独立的 Regex 或 ST Helper 脚本文件 (.json)
    """
    try:
        data = request.json
        file_path = data.get('file_path')
        content = data.get('content')

        if not file_path or content is None:
            return jsonify({"success": False, "msg": "参数缺失"})

        # 1. 安全性检查：防止路径遍历
        # 确保 file_path 是绝对路径或相对于 BASE_DIR
        if not os.path.isabs(file_path):
            abs_path = os.path.abspath(os.path.join(BASE_DIR, file_path))
        else:
            abs_path = os.path.abspath(file_path)

        base_abs = os.path.abspath(BASE_DIR)
        
        # 检查目标路径是否在 BASE_DIR 范围内
        if not abs_path.startswith(base_abs):
            return jsonify({"success": False, "msg": "非法路径：禁止访问程序目录之外的文件"})

        # 2. 检查文件扩展名
        if not abs_path.lower().endswith('.json'):
            return jsonify({"success": False, "msg": "非法文件类型：仅支持 .json"})

        # 3. 检查目录是否存在
        parent_dir = os.path.dirname(abs_path)
        if not os.path.exists(parent_dir):
            return jsonify({"success": False, "msg": f"目标目录不存在: {parent_dir}"})

        # 4. 执行原子写入
        # 使用 save_json_atomic 确保写入过程不会因为中断导致文件损坏
        if save_json_atomic(abs_path, content):
            return jsonify({"success": True, "path": abs_path})
        else:
            return jsonify({"success": False, "msg": "写入文件失败"})

    except Exception as e:
        logger.error(f"Save script error: {e}")
        return jsonify({"success": False, "msg": str(e)})
    
@bp.route('/api/list_resource_files', methods=['POST'])
def api_list_resource_files():
    """
    列出资源目录下的所有分类文件 (皮肤、世界书、正则、脚本)。
    返回包含路径的分类列表。
    """
    try:
        folder_name = request.json.get('folder_name')
        if not folder_name:
            return jsonify({"success": False, "msg": "folder_name is required"})

        cfg = load_config()
        # 资源根目录
        res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
        
        # 目标资源目录 (支持绝对路径或相对路径)
        if os.path.isabs(folder_name):
            target_dir = folder_name
        else:
            target_dir = os.path.join(res_root, folder_name)

        if not os.path.exists(target_dir):
            return jsonify({"success": True, "files": {"skins": [], "lorebooks": [], "regex": [], "scripts": []}})

        result = {
            "skins": [],
            "lorebooks": [],
            "regex": [],
            "scripts": []
        }

        # 1. 扫描根目录获取皮肤 (Skins)
        valid_img_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        try:
            for f in os.listdir(target_dir):
                full_p = os.path.join(target_dir, f)
                if os.path.isfile(full_p):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_img_exts:
                        result["skins"].append(f) # 皮肤只存文件名，前端自己拼 URL
        except: pass

        # 2. 扫描子目录获取逻辑文件 (Lorebooks, Regex, Scripts)
        # 定义子目录映射关系
        sub_map = {
            'lorebooks': 'lorebooks',
            'regex': 'extensions/regex',
            'scripts': 'extensions/tavern_helper'
        }

        for category, sub_name in sub_map.items():
            sub_dir_path = os.path.join(target_dir, sub_name.replace('/', os.sep))
            if os.path.exists(sub_dir_path):
                try:
                    for f in os.listdir(sub_dir_path):
                        if f.lower().endswith('.json'):
                            full_p = os.path.join(sub_dir_path, f)
                            rel_path = os.path.relpath(full_p, BASE_DIR)
                            
                            result[category].append({
                                "name": f,
                                "path": rel_path, # data/assets/.../regex/abc.json
                                "mtime": os.path.getmtime(full_p)
                            })
                except: pass
        
        # 排序
        result["skins"].sort()
        for key in ["lorebooks", "regex", "scripts"]:
            result[key].sort(key=lambda x: x["name"])

        return jsonify({"success": True, "files": result})

    except Exception as e:
        logger.error(f"List resource files error: {e}")
        return jsonify({"success": False, "msg": str(e)})