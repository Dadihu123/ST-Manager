"""
core/api/v1/presets.py
预设管理 API - 对齐扩展脚本的实现模式
"""
import os
import json
import logging
from flask import Blueprint, request, jsonify
from core.config import BASE_DIR, load_config
from core.utils.filesystem import sanitize_filename
from core.utils.regex import extract_regex_from_preset_data

logger = logging.getLogger(__name__)
bp = Blueprint('presets', __name__)

def _safe_join(base_dir: str, rel_path: str) -> str:
    """在 base_dir 下安全拼接相对路径，返回绝对路径；不安全则返回空字符串"""
    if not rel_path:
        return ""
    rel_path = str(rel_path).strip()
    if rel_path == "":
        return ""
    if os.path.isabs(rel_path):
        return ""
    drive, _ = os.path.splitdrive(rel_path)
    if drive:
        return ""
    rel_norm = os.path.normpath(rel_path).replace('\\', '/')
    if rel_norm == '.' or rel_norm.startswith('../') or rel_norm == '..' or '/..' in f'/{rel_norm}':
        return ""
    base_abs = os.path.abspath(base_dir)
    full_abs = os.path.abspath(os.path.join(base_abs, rel_norm))
    try:
        if os.path.commonpath([full_abs, base_abs]) != base_abs:
            return ""
    except Exception:
        return ""
    return full_abs


def _get_presets_path():
    """获取预设目录路径"""
    cfg = load_config()
    raw_presets = cfg.get('presets_dir', 'data/library/presets')
    presets_root = raw_presets if os.path.isabs(raw_presets) else os.path.join(BASE_DIR, raw_presets)
    
    # 确保目录存在
    if not os.path.exists(presets_root):
        try:
            os.makedirs(presets_root)
        except Exception as e:
            logger.error(f"Failed to create presets directory: {e}")
    
    return presets_root


def _extract_regex_from_preset(data):
    """
    从预设数据中提取绑定的正则脚本
    参考 st-external-bridge 的 preset-manager.js
    """
    return extract_regex_from_preset_data(data)

def _normalize_prompts(data):
    prompts = data.get('prompts')
    prompt_order = data.get('prompt_order')

    if isinstance(prompts, list):
        return prompts

    if isinstance(prompts, dict):
        if isinstance(prompt_order, list):
            ordered = []
            order_set = set()
            for key in prompt_order:
                order_set.add(key)
                item = prompts.get(key)
                if isinstance(item, dict):
                    if 'name' not in item:
                        item = {**item, 'name': key}
                    ordered.append(item)
                else:
                    ordered.append({'name': str(key)})
            for key, item in prompts.items():
                if key in order_set:
                    continue
                if isinstance(item, dict):
                    if 'name' not in item:
                        item = {**item, 'name': key}
                    ordered.append(item)
                else:
                    ordered.append({'name': str(key)})
            return ordered

        return [
            ({**item, 'name': key} if isinstance(item, dict) and 'name' not in item else item)
            for key, item in prompts.items()
        ]

    if isinstance(prompt_order, list):
        return prompt_order

    return []


def _parse_preset_file(file_path, filename):
    """
    解析单个预设文件，提取摘要和详情
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        preset_id = os.path.splitext(filename)[0]
        
        # 提取基本信息
        name = data.get('name') or data.get('title') or preset_id
        description = data.get('description') or data.get('note') or ''
        
        # 提取关键参数
        temperature = data.get('temperature') or data.get('temp')
        max_tokens = data.get('max_tokens') or data.get('openai_max_tokens') or data.get('max_length')
        top_p = data.get('top_p')
        top_k = data.get('top_k')
        frequency_penalty = data.get('frequency_penalty') or data.get('freq_pen')
        presence_penalty = data.get('presence_penalty') or data.get('pres_pen')
        
        # 提取 prompts
        prompts = _normalize_prompts(data)
        prompt_count = len(prompts) if isinstance(prompts, list) else 0
        
        # 提取绑定的正则
        regexes = _extract_regex_from_preset(data)
        
        # 获取文件修改时间
        mtime = os.path.getmtime(file_path)
        file_size = os.path.getsize(file_path)
        
        return {
            'summary': {
                'id': preset_id,
                'name': name,
                'description': description[:200] if description else '',
                'filename': filename,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'prompt_count': prompt_count,
                'regex_count': len(regexes),
                'mtime': mtime,
                'file_size': file_size,
            },
            'details': {
                'id': preset_id,
                'name': name,
                'description': description,
                'filename': filename,
                'path': os.path.relpath(file_path, BASE_DIR),
                
                # 模型参数
                'temperature': temperature,
                'max_tokens': max_tokens,
                'top_p': top_p,
                'top_k': top_k,
                'frequency_penalty': frequency_penalty,
                'presence_penalty': presence_penalty,
                
                # 提示词相关
                'prompts': prompts,
                'prompt_count': prompt_count,
                
                # 绑定的正则
                'regexes': regexes,
                'regex_count': len(regexes),
                
                # 原始数据 (供编辑器使用)
                'raw_data': data,
                
                # 文件信息
                'mtime': mtime,
                'file_size': file_size,
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to parse preset {filename}: {e}")
        return None


@bp.route('/api/presets/list', methods=['GET'])
def list_presets():
    """
    列出所有预设
    支持参数:
    - search: 搜索关键词
    - filter_type: 'all' | 'global' | 'resource'
    """
    try:
        search = request.args.get('search', '').lower().strip()
        filter_type = request.args.get('filter_type', 'all')
        
        items = []
        presets_root = _get_presets_path()
        
        # 1. 扫描全局目录
        if filter_type in ['all', 'global']:
            if os.path.exists(presets_root):
                for f in os.listdir(presets_root):
                    if not f.lower().endswith('.json'):
                        continue
                    
                    full_path = os.path.join(presets_root, f)
                    if not os.path.isfile(full_path):
                        continue
                    
                    parsed = _parse_preset_file(full_path, f)
                    if parsed:
                        item = parsed['summary']
                        item['type'] = 'global'
                        item['source_folder'] = None
                        item['path'] = os.path.relpath(full_path, BASE_DIR)
                        
                        # 搜索过滤
                        if search:
                            if search not in item['name'].lower() and search not in item['description'].lower():
                                continue
                        
                        items.append(item)
        
        # 2. 扫描资源目录
        if filter_type in ['all', 'resource']:
            cfg = load_config()
            res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
            
            if os.path.exists(res_root):
                try:
                    for folder in os.listdir(res_root):
                        folder_path = os.path.join(res_root, folder)
                        if not os.path.isdir(folder_path):
                            continue
                        
                        # 预设子目录
                        presets_subdir = os.path.join(folder_path, 'presets')
                        if not os.path.exists(presets_subdir):
                            continue
                        
                        for f in os.listdir(presets_subdir):
                            if not f.lower().endswith('.json'):
                                continue
                            
                            full_path = os.path.join(presets_subdir, f)
                            if not os.path.isfile(full_path):
                                continue
                            
                            parsed = _parse_preset_file(full_path, f)
                            if parsed:
                                item = parsed['summary']
                                item['id'] = f"resource::{folder}::{parsed['summary']['id']}"
                                item['type'] = 'resource'
                                item['source_folder'] = folder
                                item['path'] = os.path.relpath(full_path, BASE_DIR)
                                
                                # 搜索过滤
                                if search:
                                    if search not in item['name'].lower() and search not in item['description'].lower():
                                        continue
                                
                                items.append(item)
                                
                except Exception as e:
                    logger.error(f"Error scanning resource presets: {e}")
        
        # 按修改时间倒序
        items.sort(key=lambda x: x.get('mtime', 0), reverse=True)
        
        return jsonify({
            "success": True,
            "items": items,
            "count": len(items)
        })
        
    except Exception as e:
        logger.error(f"Error listing presets: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/detail/<path:preset_id>', methods=['GET'])
def get_preset_detail(preset_id):
    """
    获取预设详情
    preset_id 格式:
    - 'preset_name' - 全局预设
    - 'resource::folder::preset_name' - 资源目录预设
    """
    try:
        presets_root = _get_presets_path()
        
        # 解析 ID
        if preset_id.startswith('resource::'):
            parts = preset_id.split('::', 2)
            if len(parts) != 3:
                return jsonify({"success": False, "msg": "Invalid preset ID format"}), 400
            
            _, folder, name = parts
            cfg = load_config()
            res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
            folder_abs = _safe_join(res_root, folder)
            if not folder_abs:
                return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
            presets_base = os.path.join(folder_abs, 'presets')
            file_path = _safe_join(presets_base, f"{name}.json")
            preset_type = 'resource'
            source_folder = folder
        else:
            file_path = _safe_join(presets_root, f"{preset_id}.json")
            preset_type = 'global'
            source_folder = None
        
        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "Preset not found"}), 404
        
        parsed = _parse_preset_file(file_path, os.path.basename(file_path))
        if not parsed:
            return jsonify({"success": False, "msg": "Failed to parse preset"}), 500
        
        details = parsed['details']
        details['type'] = preset_type
        details['source_folder'] = source_folder
        
        return jsonify({
            "success": True,
            "preset": details
        })
        
    except Exception as e:
        logger.error(f"Error getting preset detail: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/upload', methods=['POST'])
def upload_preset():
    """
    上传预设文件
    """
    try:
        files = request.files.getlist('files')
        if not files:
            return jsonify({"success": False, "msg": "未接收到文件"})
        
        presets_root = _get_presets_path()
        success_count = 0
        failed_list = []
        
        for file in files:
            if not file.filename.lower().endswith('.json'):
                failed_list.append(f"{file.filename} (非JSON格式)")
                continue
            
            try:
                content = file.read()
                data = json.loads(content)
                file.seek(0)
                
                # 验证是否为预设格式 (至少包含一些预设特征字段)
                is_preset = False
                
                # 检测常见的预设字段
                preset_indicators = [
                    'temperature', 'max_tokens', 'top_p', 'top_k',
                    'frequency_penalty', 'presence_penalty',
                    'prompts', 'prompt_order', 'system_prompt',
                    'openai_max_tokens', 'openai_model',
                    'claude_model', 'api_type'
                ]
                
                if isinstance(data, dict):
                    for indicator in preset_indicators:
                        if indicator in data:
                            is_preset = True
                            break
                
                if not is_preset:
                    failed_list.append(f"{file.filename} (不是有效的预设格式)")
                    continue
                
                # 保存文件
                safe_name = sanitize_filename(file.filename)
                save_path = os.path.join(presets_root, safe_name)
                
                # 防重名
                name_part, ext = os.path.splitext(safe_name)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(presets_root, f"{name_part}_{counter}{ext}")
                    counter += 1
                
                file.save(save_path)
                success_count += 1
                
            except json.JSONDecodeError:
                failed_list.append(f"{file.filename} (JSON解析失败)")
            except Exception as e:
                logger.error(f"Error uploading preset {file.filename}: {e}")
                failed_list.append(file.filename)
        
        msg = f"成功上传 {success_count} 个预设文件。"
        if failed_list:
            msg += f" 失败/跳过: {', '.join(failed_list)}"
        
        return jsonify({"success": True, "msg": msg})
        
    except Exception as e:
        logger.error(f"Error in preset upload: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/delete', methods=['POST'])
def delete_preset():
    """
    删除预设文件
    """
    try:
        data = request.json
        preset_id = data.get('id')
        
        if not preset_id:
            return jsonify({"success": False, "msg": "缺少预设ID"})
        
        presets_root = _get_presets_path()
        
        # 解析 ID
        if preset_id.startswith('resource::'):
            parts = preset_id.split('::', 2)
            if len(parts) != 3:
                return jsonify({"success": False, "msg": "Invalid preset ID format"}), 400
            
            _, folder, name = parts
            cfg = load_config()
            res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
            folder_abs = _safe_join(res_root, folder)
            if not folder_abs:
                return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
            presets_base = os.path.join(folder_abs, 'presets')
            file_path = _safe_join(presets_base, f"{name}.json")
        else:
            file_path = _safe_join(presets_root, f"{preset_id}.json")
        
        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "预设文件不存在"})
        
        os.remove(file_path)
        
        return jsonify({"success": True, "msg": "预设已删除"})
        
    except Exception as e:
        logger.error(f"Error deleting preset: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/save', methods=['POST'])
def save_preset():
    """
    保存/更新预设文件
    """
    try:
        data = request.json
        preset_id = data.get('id')
        content = data.get('content')
        
        if not preset_id or not content:
            return jsonify({"success": False, "msg": "缺少必要参数"})
        
        presets_root = _get_presets_path()
        
        # 解析 ID 获取文件路径
        if preset_id.startswith('resource::'):
            parts = preset_id.split('::', 2)
            if len(parts) != 3:
                return jsonify({"success": False, "msg": "Invalid preset ID format"}), 400
            
            _, folder, name = parts
            cfg = load_config()
            res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
            folder_abs = _safe_join(res_root, folder)
            if not folder_abs:
                return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
            presets_base = os.path.join(folder_abs, 'presets')
            file_path = _safe_join(presets_base, f"{name}.json")
        else:
            file_path = _safe_join(presets_root, f"{preset_id}.json")
        
        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            if isinstance(content, str):
                f.write(content)
            else:
                json.dump(content, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "msg": "预设已保存"})
        
    except Exception as e:
        logger.error(f"Error saving preset: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500
