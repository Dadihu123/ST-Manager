"""
ST Sync API - SillyTavern 资源同步接口

提供从 SillyTavern 读取和同步资源的 REST API

@module st_sync
@version 1.0.0
"""

import os
import json
import logging
from typing import Dict, Any
from flask import Blueprint, request, jsonify
from core.config import load_config, BASE_DIR
from core.services.st_client import get_st_client, refresh_st_client, STClient
from core.services.scan_service import request_scan
from core.services.cache_service import invalidate_wi_list_cache
from core.utils.filesystem import sanitize_filename
from core.utils.regex import extract_global_regex_from_settings

logger = logging.getLogger(__name__)

bp = Blueprint('st_sync', __name__, url_prefix='/api/st')
LAST_VALID_ST_PATH = None

def _normalize_input_path(path: str) -> str:
    if not isinstance(path, str):
        return ""
    cleaned = path.strip().strip('"').strip("'")
    return os.path.normpath(cleaned) if cleaned else ""

def _normalize_st_root(path: str) -> str:
    if not path:
        return ""
    normalized = os.path.normpath(path)
    parts = normalized.split(os.sep)
    lower_parts = [p.lower() for p in parts]

    # public 目录视为安装根目录的子目录
    if lower_parts and lower_parts[-1] == 'public':
        root = os.sep.join(parts[:-1])
        return root or normalized

    # data/default-user 或 data/<user> -> 返回 data 的上一级
    if 'data' in lower_parts:
        try:
            data_idx = len(lower_parts) - 1 - lower_parts[::-1].index('data')
        except ValueError:
            data_idx = -1
        if data_idx >= 0:
            base = os.sep.join(parts[:data_idx]) or normalized
            # 仅当当前路径位于 data 目录内部时才回退
            if len(parts) > data_idx + 1:
                return base
            # 当前路径就是 data 目录，直接回退到安装根目录
            if len(parts) == data_idx + 1:
                return base

    # default-user 直接目录
    if lower_parts and lower_parts[-1] == 'default-user':
        parent = os.path.dirname(normalized)
        if os.path.basename(parent).lower() == 'data':
            return os.path.dirname(parent)
        return parent or normalized

    return normalized


def _export_global_regex(settings_path: str, target_dir: str) -> Dict[str, Any]:
    """
    将 settings.json 中的全局正则导出为独立脚本文件，便于同步到本地库。
    返回 { success, failed, files }。
    """
    result = {"success": 0, "failed": 0, "files": []}
    if not settings_path or not os.path.exists(settings_path):
        return result

    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"读取 settings.json 失败: {e}")
        return result

    regex_items = []
    raw_list = (raw.get('extension_settings') or {}).get('regex')
    if isinstance(raw_list, list) and raw_list:
        for item in raw_list:
            if isinstance(item, dict) and (item.get('findRegex') or item.get('scriptName')):
                regex_items.append(item)
    else:
        for idx, item in enumerate(extract_global_regex_from_settings(raw)):
            if not isinstance(item, dict):
                continue
            regex_items.append({
                "scriptName": item.get("name") or f"Global Regex {idx + 1}",
                "findRegex": item.get("pattern", ""),
                "replaceString": item.get("replace", ""),
                "disabled": not bool(item.get("enabled", True)),
                "placement": item.get("scope") if isinstance(item.get("scope"), list) else [],
                "flags": item.get("flags", "")
            })

    if not regex_items:
        return result

    os.makedirs(target_dir, exist_ok=True)

    def _signature(payload: Dict[str, Any]) -> str:
        sanitized = dict(payload)
        sanitized.pop('__source', None)
        try:
            return json.dumps(sanitized, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(sanitized)

    existing_exports = {}
    existing_filenames = set()
    try:
        for f in os.listdir(target_dir):
            if not (f.startswith("global__") and f.lower().endswith('.json')):
                continue
            file_path = os.path.join(target_dir, f)
            existing_filenames.add(f)
            try:
                with open(file_path, 'r', encoding='utf-8') as rf:
                    data = json.load(rf)
                if not (isinstance(data, dict) and data.get('__source') == 'settings.json'):
                    continue
                name = data.get('scriptName') or data.get('name')
                if not name:
                    base = os.path.splitext(f)[0]
                    if base.startswith('global__'):
                        base = base[len('global__'):]
                    name = base.lstrip('_- ') or f
                name = str(name).strip()
                sig = _signature(data)
                existing_exports.setdefault(name, []).append({
                    "path": file_path,
                    "filename": f,
                    "signature": sig
                })
            except Exception:
                continue
    except Exception:
        pass

    def _unique_filename(base_name: str) -> str:
        safe_name = sanitize_filename(str(base_name)) or 'global'
        candidate = f"global__{safe_name}.json"
        if candidate not in existing_filenames and not os.path.exists(os.path.join(target_dir, candidate)):
            existing_filenames.add(candidate)
            return candidate
        idx = 1
        while True:
            candidate = f"global__{safe_name}__{idx}.json"
            if candidate not in existing_filenames and not os.path.exists(os.path.join(target_dir, candidate)):
                existing_filenames.add(candidate)
                return candidate
            idx += 1

    for idx, item in enumerate(regex_items):
        try:
            name = item.get('scriptName') or item.get('name') or f"global_{idx + 1}"
            payload = dict(item)
            if not payload.get('scriptName'):
                payload['scriptName'] = name
            payload.setdefault('__source', 'settings.json')
            signature = _signature(payload)

            file_path = None
            for entry in existing_exports.get(str(name).strip(), []):
                if entry.get('signature') == signature:
                    file_path = entry.get('path')
                    break

            if not file_path:
                filename = _unique_filename(name)
                file_path = os.path.join(target_dir, filename)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            result["success"] += 1
            result["files"].append(os.path.basename(file_path))
        except Exception as e:
            logger.warning(f"写入全局正则文件失败: {e}")
            result["failed"] += 1

    return result


@bp.route('/test_connection', methods=['GET'])
def test_connection():
    """
    测试与 SillyTavern 的连接
    
    Returns:
        连接状态信息
    """
    try:
        client = get_st_client()
        result = client.test_connection()
        return jsonify({
            "success": True,
            **result
        })
    except Exception as e:
        logger.error(f"测试连接失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/detect_path', methods=['GET'])
def detect_path():
    """
    自动探测 SillyTavern 安装路径
    
    Returns:
        探测到的路径信息
    """
    try:
        client = get_st_client()
        detected = client.detect_st_path()
        
        if detected:
            global LAST_VALID_ST_PATH
            detected = _normalize_st_root(detected)
            LAST_VALID_ST_PATH = detected
            return jsonify({
                "success": True,
                "path": detected,
                "valid": True
            })
        else:
            return jsonify({
                "success": True,
                "path": None,
                "valid": False,
                "message": "未能自动探测到 SillyTavern 安装路径，请手动配置"
            })
    except Exception as e:
        logger.error(f"探测路径失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/validate_path', methods=['POST'])
def validate_path():
    """
    验证指定路径是否为有效的 SillyTavern 安装目录
    
    Body:
        path: 要验证的路径
        
    Returns:
        验证结果
    """
    try:
        data = request.get_json() or {}
        path = _normalize_input_path(data.get('path', ''))
        
        if not path:
            return jsonify({
                "success": False,
                "error": "请提供路径"
            }), 400
            
        client = STClient(st_data_dir=path)
        is_valid = client._validate_st_path(path)
        normalized_path = _normalize_st_root(path) if is_valid else path
        if normalized_path and not os.path.exists(normalized_path):
            normalized_path = path

        resources = {}
        if is_valid:
            global LAST_VALID_ST_PATH
            LAST_VALID_ST_PATH = normalized_path
            # 检查各资源目录（兼容传入 data/default-user 或根目录）
            for res_type in ['characters', 'worlds', 'presets', 'regex', 'quick_replies']:
                subdir = client.get_st_subdir(res_type)
                if res_type == 'regex':
                    script_count = 0
                    if subdir and os.path.exists(subdir):
                        try:
                            script_count = len([f for f in os.listdir(subdir) if f.endswith('.json')])
                        except Exception:
                            script_count = 0
                    global_info = client.get_global_regex()
                    global_count = global_info.get("count", 0) if isinstance(global_info, dict) else 0
                    resources[res_type] = {
                        "path": subdir or (global_info.get("path") if isinstance(global_info, dict) else None),
                        "count": script_count + global_count,
                        "script_count": script_count,
                        "global_count": global_count
                    }
                    continue

                if subdir and os.path.exists(subdir):
                    try:
                        count = len([f for f in os.listdir(subdir)
                                   if f.endswith('.json') or f.endswith('.png')])
                        resources[res_type] = {
                            "path": subdir,
                            "count": count
                        }
                    except Exception:
                        resources[res_type] = {"path": subdir, "count": 0}
        
        return jsonify({
            "success": True,
            "valid": is_valid,
            "normalized_path": normalized_path,
            "resources": resources
        })
    except Exception as e:
        logger.error(f"验证路径失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/list/<resource_type>', methods=['GET'])
def list_resources(resource_type: str):
    """
    列出指定类型的 SillyTavern 资源
    
    Args:
        resource_type: 资源类型 (characters/worlds/presets/regex/quick_replies)
        
    Query Params:
        use_api: 是否使用 API 模式 (默认 false)
        st_data_dir: SillyTavern 安装目录（可选）
        
    Returns:
        资源列表
    """
    try:
        use_api = request.args.get('use_api', 'false').lower() == 'true'
        st_data_dir = _normalize_input_path(request.args.get('st_data_dir', ''))
        if not st_data_dir:
            st_data_dir = LAST_VALID_ST_PATH
        if st_data_dir:
            st_data_dir = _normalize_st_root(st_data_dir)
        client = STClient(st_data_dir=st_data_dir) if st_data_dir else get_st_client()
        
        if resource_type == 'characters':
            items = client.list_characters(use_api)
        elif resource_type == 'worlds':
            items = client.list_world_books(use_api)
        elif resource_type == 'presets':
            items = client.list_presets(use_api)
        elif resource_type == 'regex':
            items = client.list_regex_scripts(use_api)
        elif resource_type == 'quick_replies':
            items = client.list_quick_replies(use_api)
        else:
            return jsonify({
                "success": False,
                "error": f"未知资源类型: {resource_type}"
            }), 400
            
        return jsonify({
            "success": True,
            "resource_type": resource_type,
            "items": items,
            "count": len(items)
        })
    except Exception as e:
        logger.error(f"列出资源失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/get/<resource_type>/<resource_id>', methods=['GET'])
def get_resource(resource_type: str, resource_id: str):
    """
    获取单个资源详情
    
    Args:
        resource_type: 资源类型
        resource_id: 资源 ID
        
    Query Params:
        use_api: 是否使用 API 模式
        st_data_dir: SillyTavern 安装目录（可选）
        
    Returns:
        资源详情
    """
    try:
        use_api = request.args.get('use_api', 'false').lower() == 'true'
        st_data_dir = _normalize_input_path(request.args.get('st_data_dir', ''))
        if not st_data_dir:
            st_data_dir = LAST_VALID_ST_PATH
        if st_data_dir:
            st_data_dir = _normalize_st_root(st_data_dir)
        client = STClient(st_data_dir=st_data_dir) if st_data_dir else get_st_client()
        
        if resource_type == 'characters':
            item = client.get_character(resource_id, use_api)
        elif resource_type == 'worlds':
            # 世界书需要完整读取
            items = client.list_world_books(use_api)
            item = next((w for w in items if w.get('id') == resource_id), None)
            if item and item.get('filepath'):
                item['data'] = client._read_world_book_file(item['filepath'])
        else:
            return jsonify({
                "success": False,
                "error": f"不支持获取详情的资源类型: {resource_type}"
            }), 400
            
        if item:
            return jsonify({
                "success": True,
                "item": item
            })
        else:
            return jsonify({
                "success": False,
                "error": f"未找到资源: {resource_id}"
            }), 404
    except Exception as e:
        logger.error(f"获取资源失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/sync', methods=['POST'])
def sync_resources():
    """
    同步资源到本地
    
    Body:
        resource_type: 资源类型
        resource_ids: 资源 ID 列表（可选，为空则同步全部）
        use_api: 是否使用 API 模式
        
    Returns:
        同步结果
    """
    try:
        data = request.get_json() or {}
        resource_type = data.get('resource_type')
        resource_ids = data.get('resource_ids', [])
        use_api = data.get('use_api', False)
        st_data_dir = _normalize_input_path(data.get('st_data_dir'))
        if not st_data_dir:
            st_data_dir = LAST_VALID_ST_PATH
        st_data_dir = _normalize_st_root(st_data_dir)
        
        if not resource_type:
            return jsonify({
                "success": False,
                "error": "请指定资源类型"
            }), 400
            
        # 获取目标目录
        config = load_config()
        target_dir_map = {
            "characters": config.get('cards_dir', 'data/library/characters'),
            "worlds": config.get('world_info_dir', 'data/library/lorebooks'),
            "presets": config.get('presets_dir', 'data/library/presets'),
            "regex": config.get('regex_dir', 'data/library/extensions/regex'),
            "quick_replies": config.get('quick_replies_dir', 'data/library/extensions/quick-replies'),
        }
        
        target_dir = target_dir_map.get(resource_type)
        if not target_dir:
            return jsonify({
                "success": False,
                "error": f"未知资源类型: {resource_type}"
            }), 400
            
        # 处理相对路径
        if not os.path.isabs(target_dir):
            target_dir = os.path.join(BASE_DIR, target_dir)
            
        # 使用用户提供的路径创建客户端
        client = STClient(st_data_dir=st_data_dir) if st_data_dir else get_st_client()
        
        if resource_ids:
            # 同步指定资源
            result = {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "errors": [],
                "synced": []
            }
            for res_id in resource_ids:
                success, msg = client.sync_resource(resource_type, res_id, target_dir, use_api)
                if success:
                    result["success"] += 1
                    result["synced"].append(res_id)
                else:
                    result["failed"] += 1
                    result["errors"].append(f"{res_id}: {msg}")
        else:
            # 同步全部
            result = client.sync_all_resources(resource_type, target_dir, use_api)

        # 正则同步：补充全局正则（settings.json）
        if resource_type == 'regex':
            settings_path = client.get_settings_path()
            global_result = _export_global_regex(settings_path, target_dir)
            result["global_regex"] = global_result
            if global_result.get("success"):
                result["success"] += global_result.get("success", 0)
            if global_result.get("failed"):
                result["failed"] += global_result.get("failed", 0)

        # 同步成功后触发扫描，将新文件导入数据库
        if result.get("success", 0) > 0:
            if resource_type == 'characters':
                request_scan(reason="st_sync")
            elif resource_type == 'worlds':
                invalidate_wi_list_cache()
            
        return jsonify({
            "success": True,
            "resource_type": resource_type,
            "target_dir": target_dir,
            "result": result
        })
    except Exception as e:
        logger.error(f"同步资源失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/refresh', methods=['POST'])
def refresh_client():
    """
    刷新 ST 客户端配置
    
    用于配置变更后重新初始化客户端
    """
    try:
        refresh_st_client()
        return jsonify({
            "success": True,
            "message": "客户端已刷新"
        })
    except Exception as e:
        logger.error(f"刷新客户端失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/summary', methods=['GET'])
def get_summary():
    """
    获取 SillyTavern 资源概览
    
    Query Params:
        st_data_dir: SillyTavern 安装目录（可选）
    
    Returns:
        各类资源的数量统计
    """
    try:
        st_data_dir = _normalize_input_path(request.args.get('st_data_dir', ''))
        if not st_data_dir:
            st_data_dir = LAST_VALID_ST_PATH
        if st_data_dir:
            st_data_dir = _normalize_st_root(st_data_dir)
        client = STClient(st_data_dir=st_data_dir) if st_data_dir else get_st_client()
        
        summary = {
            "st_path": client.st_data_dir or client.detect_st_path(),
            "resources": {}
        }
        
        # 统计各类资源
        resource_types = ['characters', 'worlds', 'presets', 'regex', 'quick_replies']
        for res_type in resource_types:
            try:
                if res_type == 'characters':
                    items = client.list_characters()
                elif res_type == 'worlds':
                    items = client.list_world_books()
                elif res_type == 'presets':
                    items = client.list_presets()
                elif res_type == 'regex':
                    items = client.list_regex_scripts()
                elif res_type == 'quick_replies':
                    items = client.list_quick_replies()
                else:
                    items = []
                    
                summary["resources"][res_type] = {
                    "count": len(items),
                    "available": True
                }
            except Exception as e:
                summary["resources"][res_type] = {
                    "count": 0,
                    "available": False,
                    "error": str(e)
                }
                
        return jsonify({
            "success": True,
            **summary
        })
    except Exception as e:
        logger.error(f"获取概览失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route('/regex', methods=['GET'])
def get_regex_aggregate():
    """
    聚合全局正则 + 预设绑定正则
    Query:
        presets_path: 自定义预设目录（可选）
        settings_path: 自定义 settings.json 路径（可选）
        st_data_dir: SillyTavern 安装目录（可选）
    """
    try:
        presets_path = request.args.get('presets_path')
        settings_path = request.args.get('settings_path')
        st_data_dir = _normalize_input_path(request.args.get('st_data_dir', ''))
        if not st_data_dir:
            st_data_dir = LAST_VALID_ST_PATH
        client = STClient(st_data_dir=st_data_dir) if st_data_dir else get_st_client()
        result = client.aggregate_regex(presets_path, settings_path)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"获取正则汇总失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
