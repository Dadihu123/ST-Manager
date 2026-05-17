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
from core.consts import RESERVED_RESOURCE_NAMES
from core.context import ctx

# === 工具函数 ===
from core.utils.image import (
    extract_card_info, find_sidecar_image, get_default_card_image_path
)
from core.utils.filesystem import safe_move_to_trash, sanitize_filename, save_json_atomic

from core.services.card_service import resolve_ui_key
from core.data.ui_store import load_ui_data, save_ui_data

logger = logging.getLogger(__name__)

bp = Blueprint('resources', __name__)

GENERIC_RESOURCE_SCAN_SKIP_ROOTS = {
    name.lower() for name in RESERVED_RESOURCE_NAMES
} | {'extensions', 'presets'}

def _is_within_base(path: str, base: str) -> bool:
    """检查路径是否在 base 目录内"""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except Exception:
        return False

def _is_safe_filename(name: str) -> bool:
    """仅允许文件名，不允许路径或父目录引用"""
    if not name:
        return False
    if name != os.path.basename(name):
        return False
    if '..' in name.replace('\\', '/'):
        return False
    return True

def _normalize_resource_relative_path(path_value: str):
    if not path_value or os.path.isabs(str(path_value)):
        return None

    normalized = str(path_value).replace('\\', '/').strip('/')
    if not normalized:
        return None

    parts = [part for part in normalized.split('/') if part]
    if any(part in ('.', '..') for part in parts):
        return None

    return '/'.join(parts)

def _safe_join_resource_file(base_dir: str, relative_path: str):
    normalized = _normalize_resource_relative_path(relative_path)
    if not normalized:
        return None, None

    target_path = os.path.abspath(os.path.join(base_dir, normalized.replace('/', os.sep)))
    if not _is_within_base(target_path, base_dir):
        return None, None

    return target_path, normalized

def _resource_api_path(full_path: str) -> str:
    full_abs = os.path.abspath(full_path)
    base_abs = os.path.abspath(BASE_DIR)
    if _is_within_base(full_abs, base_abs):
        return os.path.relpath(full_abs, base_abs).replace('\\', '/')
    return full_abs

def _build_resource_file_item(full_path: str, relative_path: str) -> dict:
    ext = os.path.splitext(full_path)[1].lower()
    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        mtime = 0
    try:
        size = os.path.getsize(full_path)
    except OSError:
        size = 0

    return {
        "name": os.path.basename(full_path),
        "relative_path": relative_path,
        "path": _resource_api_path(full_path),
        "mtime": mtime,
        "size": size,
        "extension": ext,
    }

def _get_resource_root() -> str:
    """返回资源根目录绝对路径。"""
    cfg = load_config()
    res_dir_conf = cfg.get('resources_dir', 'data/assets/card_assets')
    return res_dir_conf if os.path.isabs(res_dir_conf) else os.path.join(BASE_DIR, res_dir_conf)

def _build_unique_resource_folder_name(resource_root: str, preferred_name: str) -> str:
    """基于角色名生成安全且不重名的资源目录名。"""
    base_name = sanitize_filename(preferred_name or 'untitled').strip() or 'untitled'
    if base_name.lower() in RESERVED_RESOURCE_NAMES:
        base_name = f'card_{base_name}'

    candidate = base_name
    counter = 1
    while os.path.exists(os.path.join(resource_root, candidate)):
        candidate = f'{base_name}_{counter}'
        counter += 1
    return candidate

def _ensure_card_resource_folder(card_id: str):
    """确保角色卡已绑定资源目录；若未绑定则自动创建。"""
    ui_data = load_ui_data()
    ui_key = resolve_ui_key(card_id)
    existing_folder = ui_data.get(ui_key, {}).get('resource_folder')
    if existing_folder:
        return existing_folder, False, None

    card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
    info = extract_card_info(card_path)
    if not info:
        return None, False, '未找到角色卡，无法自动创建资源目录'

    data_block = info.get('data', {}) if isinstance(info.get('data'), dict) else info
    char_name = (
        info.get('name')
        or data_block.get('name')
        or os.path.splitext(os.path.basename(card_path))[0]
    )

    resource_root = _get_resource_root()
    os.makedirs(resource_root, exist_ok=True)

    resource_folder_name = _build_unique_resource_folder_name(resource_root, char_name)
    os.makedirs(os.path.join(resource_root, resource_folder_name), exist_ok=True)

    if ui_key not in ui_data:
        ui_data[ui_key] = {}
    ui_data[ui_key]['resource_folder'] = resource_folder_name
    save_ui_data(ui_data)

    target_id = ctx.cache.bundle_map.get(ui_key, card_id) if ui_key in ctx.cache.bundle_map else card_id
    ctx.cache.update_card_data(target_id, {'resource_folder': resource_folder_name})

    return resource_folder_name, True, None

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
        data = request.json or {}
        card_id = data.get('card_id')
        filename = data.get('filename')
        
        if not card_id or not filename:
            return jsonify({"success": False, "msg": "参数缺失"})
        normalized_filename = _normalize_resource_relative_path(filename)
        if not normalized_filename:
            return jsonify({"success": False, "msg": "非法路径"})

        # 1. 解析资源目录路径
        ui_data = load_ui_data()
        ui_key = resolve_ui_key(card_id)
        res_folder_name = ui_data.get(ui_key, {}).get('resource_folder')
        
        if not res_folder_name:
            return jsonify({"success": False, "msg": "该卡片未设置资源目录"})

        res_root = _get_resource_root()
        
        # 确定完整路径
        if os.path.isabs(res_folder_name):
            target_base_dir = res_folder_name
        else:
            target_base_dir = os.path.join(res_root, res_folder_name)
            if not _is_within_base(target_base_dir, res_root):
                return jsonify({"success": False, "msg": "非法路径"})
            
        # 安全检查：防止目录遍历
        target_file, _relative_path = _safe_join_resource_file(target_base_dir, normalized_filename)
        if not target_file:
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

        # 1. 获取或自动创建资源目录
        res_folder_name, folder_created, error_msg = _ensure_card_resource_folder(card_id)
        if not res_folder_name:
            return jsonify({"success": False, "msg": error_msg or "资源目录创建失败"})

        res_root = _get_resource_root()
        
        # 处理绝对路径/相对路径
        if os.path.isabs(res_folder_name):
            target_base_dir = res_folder_name
        else:
            target_base_dir = os.path.join(res_root, res_folder_name)
            
        os.makedirs(target_base_dir, exist_ok=True)

        # 2. 分析文件类型并确定子目录
        raw_filename = file.filename
        filename = sanitize_filename(raw_filename)
        ext = os.path.splitext(filename)[1].lower()
        sub_dir = "" # 默认根目录
        
        is_lorebook = False
        is_preset = False
        
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
                    
                # D. 快速回复特征: 包含 'qrList'
                elif (isinstance(data, dict) and 'qrList' in data):
                    sub_dir = "extensions/quick-replies"
                
                # E. 预设文件特征: 包含 temperature, max_tokens, prompt_order 等预设特有字段
                elif isinstance(data, dict) and any(key in data for key in ['temperature', 'max_tokens', 'openai_max_tokens', 'max_length', 'prompt_order', 'prompts']):
                    sub_dir = "presets"
                    is_preset = True
                
                # F. 兜底: 无法识别的 JSON 放在根目录，或者你可以指定一个 'misc' 目录
                else:
                    sub_dir = "" 
            except Exception as e:
                print(f"JSON detection failed: {e}")
                sub_dir = "" 

        # 3. 构建最终路径
        final_dir = os.path.join(target_base_dir, sub_dir.replace('/', os.sep))
        os.makedirs(final_dir, exist_ok=True)
            
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
            "is_preset": is_preset,
            "category": sub_dir,
            "resource_folder": res_folder_name,
            "resource_folder_created": folder_created
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

        # 资源根目录
        res_root = _get_resource_root()
        
        # 目标资源目录 (支持绝对路径或相对路径)
        if os.path.isabs(folder_name):
            cfg = load_config()
            allowed_roots = cfg.get('allowed_abs_resource_roots', []) or []
            allowed_abs = []
            for root in allowed_roots:
                if isinstance(root, str) and os.path.isabs(root):
                    allowed_abs.append(root)

            ui_data = load_ui_data()
            for v in ui_data.values():
                if isinstance(v, dict):
                    abs_path = v.get('resource_folder')
                    if isinstance(abs_path, str) and os.path.isabs(abs_path):
                        allowed_abs.append(abs_path)

            if not any(_is_within_base(folder_name, base) for base in allowed_abs):
                return jsonify({"success": False, "msg": "非法路径"})
            target_dir = folder_name
        else:
            target_dir = os.path.join(res_root, folder_name)
            if not _is_within_base(target_dir, res_root):
                return jsonify({"success": False, "msg": "非法路径"})

        result = {
            "skins": [],
            "lorebooks": [],
            "regex": [],
            "scripts": [],
            "quick_replies": [],
            "presets": [],
            "unknown": [],
        }

        if not os.path.exists(target_dir):
            return jsonify({"success": True, "files": result})

        valid_img_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        sub_map = {
            'lorebooks': 'lorebooks',
            'regex': 'extensions/regex',
            'scripts': 'extensions/tavern_helper',
            'quick_replies': 'extensions/quick-replies',
            'presets': 'presets',
        }
        sub_prefixes = [
            (category, sub_name.replace('\\', '/').strip('/'))
            for category, sub_name in sub_map.items()
        ]

        try:
            for root, _dirs, files in os.walk(target_dir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, target_dir).replace('\\', '/')
                    ext = os.path.splitext(filename)[1].lower()

                    category = None
                    in_managed_resource_tree = False
                    top_dir = rel_path.split('/', 1)[0].lower()

                    for category_name, prefix in sub_prefixes:
                        if rel_path.startswith(f'{prefix}/'):
                            in_managed_resource_tree = True
                            if ext == '.json':
                                category = category_name
                            break

                    if in_managed_resource_tree:
                        if category:
                            item = _build_resource_file_item(full_path, rel_path)
                            result[category].append(item)
                        continue

                    if top_dir in GENERIC_RESOURCE_SCAN_SKIP_ROOTS:
                        continue

                    if ext in valid_img_exts:
                        result["skins"].append(rel_path)
                        continue

                    if ext == '.json':
                        for category_name, prefix in sub_prefixes:
                            if rel_path == prefix or rel_path.startswith(f'{prefix}/'):
                                category = category_name
                                break

                    item = _build_resource_file_item(full_path, rel_path)
                    if category:
                        result[category].append(item)
                    else:
                        result["unknown"].append(item)
        except OSError as e:
            logger.warning(f"Failed to scan resource files in {target_dir}: {e}")

        result["skins"].sort(key=lambda x: x.lower())
        for key in ["lorebooks", "regex", "scripts", "quick_replies", "presets", "unknown"]:
            result[key].sort(key=lambda x: x.get("relative_path", x.get("name", "")).lower())

        return jsonify({"success": True, "files": result})

    except Exception as e:
        logger.error(f"List resource files error: {e}")
        return jsonify({"success": False, "msg": str(e)})
