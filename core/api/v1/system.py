import os
import json
import platform
import subprocess
import shutil
import logging
import tempfile
import time
import re
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify

# === 基础设施 ===
from core.config import (
    CARDS_FOLDER, DATA_DIR, BASE_DIR, TRASH_FOLDER,
    load_config, save_config, get_cards_folder
)
from core.context import ctx
from core.data.ui_store import (
    UI_DATA_FILE,
    get_shared_wallpaper_library,
    load_ui_data,
    save_ui_data,
    set_last_sent_to_st,
    set_shared_wallpaper_library,
)
from core.consts import SIDECAR_EXTENSIONS, RESERVED_RESOURCE_NAMES

# === 核心服务 ===
from core.services.scan_service import request_scan, suppress_fs_events
from core.services.cache_service import schedule_reload, invalidate_wi_list_cache, update_card_cache
from core.services.card_service import resolve_ui_key
from core.services.index_service import get_index_status, request_index_rebuild
from core.services.shared_wallpaper_service import SharedWallpaperService
from core.services.st_client import refresh_st_client
from core.services.st_auth import STAuthError, build_st_http_client
from core.services.st_path_safety import evaluate_st_path_safety
from core.services.user_db_backup_service import UserDbBackupService

# === 工具函数 ===
from core.utils.filesystem import (
    cleanup_old_snapshots, sanitize_filename, write_snapshot_file
)
from core.utils.image import extract_card_info, write_card_metadata, find_sidecar_image

from core.utils.hash import _calculate_data_hash

bp = Blueprint('system', __name__)


REMOVED_ST_PRESET_DIRECTORY_KEYS = (
    'st_textgen_preset_dir',
    'st_instruct_preset_dir',
    'st_context_preset_dir',
    'st_sysprompt_dir',
    'st_reasoning_dir',
)

logger = logging.getLogger(__name__)

_shared_wallpaper_service = None
_user_db_backup_service = None


def get_shared_wallpaper_service():
    global _shared_wallpaper_service
    if _shared_wallpaper_service is None:
        _shared_wallpaper_service = SharedWallpaperService()
    return _shared_wallpaper_service


def get_user_db_backup_service():
    global _user_db_backup_service
    if _user_db_backup_service is None:
        _user_db_backup_service = UserDbBackupService()
    return _user_db_backup_service


def _serialize_shared_wallpaper_items(items):
    return [items[wallpaper_id] for wallpaper_id in sorted(items.keys())]


def _save_upload_to_temp(upload):
    suffix = os.path.splitext(upload.filename or '')[1]
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    upload.save(temp_path)
    return temp_path


def _format_st_auth_error(error):
    if error.stage == 'basic_auth':
        status = error.status_code or 401
        return f"ST Basic/Auth 认证失败 ({status}): 请检查 Basic/Auth 用户名和密码。"
    if error.stage == 'web_login':
        status = error.status_code or 401
        return f"ST Web 登录失败 ({status}): 请检查 Web 用户名和密码。"
    if error.stage == 'connection':
        return error.message

    status = f" ({error.status_code})" if error.status_code else ''
    return f"ST 连接失败{status}: {error.message}"


def _format_st_response_error(response, auth_type):
    if response.status_code == 400:
        return f"ST 请求错误 (400): {response.text}"

    if response.status_code == 401:
        if auth_type == 'web':
            return 'ST 认证失败 (401): Web 登录会话无效，请检查账号或重新登录。'
        if auth_type == 'auth_web':
            return 'ST 认证失败 (401): Basic/Auth 已通过，但 Web 会话无效，请检查 Web 登录信息或 ST 日志。'
        return 'ST 认证失败 (401): Basic/Auth 用户名或密码错误。'

    if response.status_code == 403:
        if auth_type in ('web', 'auth_web'):
            return (
                'ST 权限拒绝 (403): 认证已通过，但请求被 ST 的会话或 CSRF 校验拦截。'
                '请检查 ST 日志，或在 config.yaml 中确认 disableCsrfProtection 配置。'
            )
        return (
            'ST 权限拒绝 (403): 认证已通过，但请求被 ST 的 CSRF 校验拦截。'
            "请在 SillyTavern 的 config.yaml 中检查 'disableCsrfProtection'，"
            '或改用 Web Login / Basic Auth + Web Login 模式。'
        )

    return f"ST Error: {response.status_code} - {response.text}"

def _is_under_base(path: str, base: str) -> bool:
    """检查路径是否在 base 目录内"""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except Exception:
        return False

def _resolve_allowed_roots():
    cfg = load_config()
    raw_chats = cfg.get('chats_dir', 'data/library/chats')
    chats_root = raw_chats if os.path.isabs(raw_chats) else os.path.join(BASE_DIR, raw_chats)

    raw_wi = cfg.get('world_info_dir', 'lorebooks')
    wi_root = raw_wi if os.path.isabs(raw_wi) else os.path.join(BASE_DIR, raw_wi)

    raw_res = cfg.get('resources_dir', 'data/assets/card_assets')
    res_root = raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res)

    roots = [
        str(CARDS_FOLDER),
        DATA_DIR,
        chats_root,
        wi_root,
        res_root,
    ]

    allowed_abs = cfg.get('allowed_abs_resource_roots', []) or []
    for root in allowed_abs:
        if isinstance(root, str) and os.path.isabs(root):
            roots.append(root)

    # 去重 + 归一化
    dedup = []
    for r in roots:
        if not r:
            continue
        abs_r = os.path.abspath(r)
        if abs_r not in dedup:
            dedup.append(abs_r)
    return dedup

def _resolve_safe_path(path: str, relative_to_base: bool = False):
    if not path:
        return None

    if relative_to_base:
        abs_path = os.path.abspath(os.path.join(BASE_DIR, path))
    else:
        abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(BASE_DIR, path))

    for root in _resolve_allowed_roots():
        if _is_under_base(abs_path, root):
            return abs_path
    return None

def _is_safe_card_rel(card_id: str) -> bool:
    if not card_id:
        return False
    safe = card_id.replace('\\', '/')
    if safe.startswith('/') or safe.startswith('..') or '/..' in safe:
        return False
    return True

def _is_valid_lorebook_path(path: str) -> bool:
    if not path:
        return False
    cfg = load_config()
    raw_wi = cfg.get('world_info_dir', 'lorebooks')
    wi_root = raw_wi if os.path.isabs(raw_wi) else os.path.join(BASE_DIR, raw_wi)

    raw_res = cfg.get('resources_dir', 'data/assets/card_assets')
    res_root = raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res)

    if _is_under_base(path, wi_root):
        return True

    if _is_under_base(path, res_root):
        rel_path = os.path.relpath(path, res_root).replace('\\', '/')
        return '/lorebooks/' in f"/{rel_path}/"

    return False


def _is_valid_preset_path(path: str) -> bool:
    if not path:
        return False
    cfg = load_config()
    raw_presets = cfg.get('presets_dir', 'data/library/presets')
    presets_root = raw_presets if os.path.isabs(raw_presets) else os.path.join(BASE_DIR, raw_presets)

    raw_res = cfg.get('resources_dir', 'data/assets/card_assets')
    res_root = raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res)

    if _is_under_base(path, presets_root):
        return True

    if _is_under_base(path, res_root):
        rel_path = os.path.relpath(path, res_root).replace('\\', '/')
        return '/presets/' in f'/{rel_path}/'

    return False


def _extract_settings_save_payload(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    nested_config = payload.get('config') if isinstance(payload.get('config'), dict) else None
    config = dict(nested_config if nested_config is not None else payload)
    config.pop('confirm_risky_paths', None)
    confirm_risky_paths = bool(payload.get('confirm_risky_paths'))
    return config, confirm_risky_paths

@bp.route('/api/status')
def api_status():
    return jsonify(ctx.init_status)


@bp.route('/api/index/status')
def api_index_status():
    return jsonify({'success': True, 'status': get_index_status()})


@bp.route('/api/index/rebuild', methods=['POST'])
def api_index_rebuild():
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get('scope') or 'cards').strip() or 'cards'
    try:
        request_index_rebuild(scope)
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc), 'scope': scope}), 400
    return jsonify({'success': True, 'scope': scope})

@bp.route('/api/scan_now', methods=['POST'])
def api_scan_now():
    """手动触发一次全量扫描（用于 watchdog 不可用或用户想立刻同步）"""
    try:
        request_scan(reason="manual")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/settings_path_safety', methods=['POST'])
def api_settings_path_safety():
    config, _confirm_risky_paths = _extract_settings_save_payload(request.get_json(silent=True) or {})
    evaluation = evaluate_st_path_safety(config)
    return jsonify({'success': True, **evaluation})

@bp.route('/api/save_settings', methods=['POST'])
def api_save_settings():
    try:
        new_config, confirm_risky_paths = _extract_settings_save_payload(request.get_json(silent=True) or {})
        evaluation = evaluate_st_path_safety(new_config)
        if evaluation['conflicts'] and not confirm_risky_paths:
            return jsonify({'success': False, 'requires_confirmation': True, **evaluation}), 409

        config_payload = dict(new_config or {})
        config_payload.pop('manager_wallpaper_id', None)
        config_payload.pop('shared_wallpapers', None)
        for key in REMOVED_ST_PRESET_DIRECTORY_KEYS:
            config_payload.pop(key, None)
        if not save_config(config_payload):
            return jsonify({'success': False, 'msg': '保存配置失败'}), 500

        refresh_st_client()

        ui_data = load_ui_data()
        shared_wallpaper_library = get_shared_wallpaper_library(ui_data)
        manager_wallpaper_id = shared_wallpaper_library.get('manager_wallpaper_id', '')
        if isinstance(new_config, dict) and 'manager_wallpaper_id' in new_config:
            manager_wallpaper_id = str(new_config.get('manager_wallpaper_id') or '').strip()
        next_shared_wallpaper_payload = {
            'items': dict(shared_wallpaper_library.get('items') or {}),
            'manager_wallpaper_id': manager_wallpaper_id,
            'preview_wallpaper_id': shared_wallpaper_library.get('preview_wallpaper_id', ''),
        }
        if set_shared_wallpaper_library(ui_data, next_shared_wallpaper_payload):
            save_ui_data(ui_data)

        # 确保新卡片目录存在（使用动态路径解析）
        new_full_path = get_cards_folder()
        if not os.path.exists(new_full_path):
            try:
                os.makedirs(new_full_path)
            except Exception as e:
                return jsonify({"success": False, "msg": f"路径不存在且无法创建: {str(e)}"})

        # 处理资源目录配置
        resources_dir = new_config.get('resources_dir', 'data/assets/card_assets')
        resources_path = resources_dir if os.path.isabs(resources_dir) else os.path.join(BASE_DIR, resources_dir)
        if not os.path.exists(resources_path):
            try:
                os.makedirs(resources_path)
            except Exception as e:
                # 只是警告，不阻止保存其他设置
                logger.warning(f"无法创建资源目录 {resources_path}: {str(e)}")

        chats_dir = new_config.get('chats_dir', 'data/library/chats')
        chats_path = chats_dir if os.path.isabs(chats_dir) else os.path.join(BASE_DIR, chats_dir)
        if not os.path.exists(chats_path):
            try:
                os.makedirs(chats_path)
            except Exception as e:
                logger.warning(f"无法创建聊天目录 {chats_path}: {str(e)}")

        response = {'success': True}
        if evaluation['conflicts']:
            response.update({'saved_with_warnings': True, **evaluation})
        return jsonify(response)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/get_settings')
def api_get_settings():
    cfg = dict(load_config())
    for key in REMOVED_ST_PRESET_DIRECTORY_KEYS:
        cfg.pop(key, None)

    # 确保有默认值，防止前端 undefined
    if 'cards_dir' not in cfg:
        cfg['cards_dir'] = 'data/library/characters'
    if 'world_info_dir' not in cfg:
        cfg['world_info_dir'] = 'data/library/lorebooks'
    if 'chats_dir' not in cfg:
        cfg['chats_dir'] = 'data/library/chats'
    if 'presets_dir' not in cfg:
        cfg['presets_dir'] = 'data/library/presets'
    if 'st_openai_preset_dir' not in cfg:
        cfg['st_openai_preset_dir'] = ''
    if 'quick_replies_dir' not in cfg:
        cfg['quick_replies_dir'] = 'data/library/extensions/quick-replies'
    if 'default_sort' not in cfg:
        cfg['default_sort'] = 'date_desc'
    if 'show_header_sort' not in cfg:
        cfg['show_header_sort'] = True

    shared_wallpaper_library = get_shared_wallpaper_service().migrate_legacy_backgrounds({
        'bg_url': cfg.get('bg_url', ''),
    })
    cfg['manager_wallpaper_id'] = shared_wallpaper_library.get('manager_wallpaper_id', '')
    cfg['shared_wallpapers'] = _serialize_shared_wallpaper_items(shared_wallpaper_library.get('items') or {})
    return jsonify(cfg)


@bp.route('/api/shared-wallpapers/import', methods=['POST'])
def api_import_shared_wallpaper():
    upload = request.files.get('file')
    if not upload:
        return jsonify({'success': False, 'msg': '请上传壁纸文件'}), 400

    selection_target = str(request.form.get('selection_target') or '').strip()
    if selection_target and selection_target not in ('manager', 'preview'):
        return jsonify({'success': False, 'msg': '无效的 selection_target'}), 400
    temp_path = _save_upload_to_temp(upload)
    try:
        item = get_shared_wallpaper_service().import_wallpaper(
            temp_path,
            selection_target=selection_target,
            source_name=upload.filename,
        )
        if not item:
            return jsonify({'success': False, 'msg': '导入壁纸失败，请确认文件是有效图片'}), 400
        return jsonify({'success': True, 'item': item})
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc)}), 400
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@bp.route('/api/user-db-backup/export', methods=['POST'])
def api_export_user_db_backup():
    try:
        result = get_user_db_backup_service().export_backup()
        return jsonify({'success': True, 'msg': '已备份用户 DB 数据', **result})
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc)}), 400
    except Exception as exc:
        logger.exception('导出用户 DB 备份失败: %s', exc)
        return jsonify({'success': False, 'msg': str(exc)}), 500


@bp.route('/api/user-db-backup/import', methods=['POST'])
def api_import_user_db_backup():
    upload = request.files.get('file')
    if not upload or not (upload.filename or '').lower().endswith('.json'):
        return jsonify({'success': False, 'msg': '请上传 JSON 备份文件'}), 400

    temp_path = _save_upload_to_temp(upload)
    try:
        result = get_user_db_backup_service().import_backup(
            temp_path,
            source_name=upload.filename,
        )
        return jsonify({'success': True, 'msg': '用户 DB 数据导入完成', **result})
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc)}), 400
    except Exception as exc:
        logger.exception('导入用户 DB 备份失败: %s', exc)
        return jsonify({'success': False, 'msg': str(exc)}), 500
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@bp.route('/api/shared-wallpapers/select', methods=['POST'])
def api_select_shared_wallpaper():
    payload = request.get_json(silent=True) or {}
    wallpaper_id = str(payload.get('wallpaper_id') or '').strip()
    selection_target = str(payload.get('selection_target') or '').strip()
    if not wallpaper_id or not selection_target:
        return jsonify({'success': False, 'msg': '缺少 wallpaper_id 或 selection_target'}), 400

    try:
        result = get_shared_wallpaper_service().select_wallpaper(wallpaper_id, selection_target)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return jsonify({'success': False, 'msg': str(exc)}), 400

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
                # === Termux 适配 ===
                if "ANDROID_ROOT" in os.environ:
                    # 使用 termux-open 调用安卓系统选择器
                    subprocess.Popen(["termux-open", "--choose", path])
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

            if not _is_safe_card_rel(card_id):
                return jsonify({"success": False, "msg": "非法路径"})

            full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
            full_path = os.path.abspath(full_path)
            if not _is_under_base(full_path, str(CARDS_FOLDER)):
                return jsonify({"success": False, "msg": "非法路径"})
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
        if snapshot_type == 'preset':
            src_path = req_data.get('file_path')
            backups_root = os.path.join(system_backups_dir, 'presets')
        elif snapshot_type == 'lorebook':
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
            if not _is_safe_card_rel(target_id):
                return jsonify({"success": False, "msg": "非法路径"})
            rel_path = target_id.replace('/', os.sep)
            src_path = os.path.join(CARDS_FOLDER, rel_path)
            backups_root = os.path.join(system_backups_dir, 'cards')

        if snapshot_type == 'preset':
            src_path = os.path.normpath(src_path if os.path.isabs(src_path) else os.path.join(BASE_DIR, src_path))
            if not _is_valid_preset_path(src_path):
                return jsonify({"success": False, "msg": "非法路径"})
        elif snapshot_type == 'lorebook':
            src_path = os.path.normpath(src_path if os.path.isabs(src_path) else os.path.join(BASE_DIR, src_path))
            if not _is_valid_lorebook_path(src_path):
                return jsonify({"success": False, "msg": "非法路径"})
        else:
            src_path = os.path.abspath(src_path)
            if not _is_under_base(src_path, str(CARDS_FOLDER)):
                return jsonify({"success": False, "msg": "非法路径"})

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

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
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
        raw_res = cfg.get('resources_dir', 'data/assets/card_assets')
        res_base = raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res)
        backups_root = ""
        filename = ""
        
        # 解析路径逻辑
        if snapshot_type == 'preset':
            path = req_data.get('file_path')
            filename = os.path.basename(path) if path else 'Unknown.json'
            backups_root = os.path.join(res_base, 'backups', 'presets')
        elif snapshot_type == 'lorebook':
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
        ext = '.json' if snapshot_type in ('lorebook', 'preset') else '.png' # 默认后缀
        # 尝试沿用原文件后缀
        if req_data.get('file_path'):
            ext = os.path.splitext(req_data.get('file_path'))[1]
        elif target_id.endswith('.png'): ext = '.png'
        elif target_id.endswith('.json'): ext = '.json'

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        backup_filename = f"{name_no_ext}_{timestamp}__AUTO__{ext}"
        dst_path = os.path.join(target_dir, backup_filename)
        
        # 写入
        is_png = (ext.lower() == '.png')
        
        # 如果是 PNG，我们需要源文件作为底板
        src_path = ""
        if snapshot_type == 'card':
             if not _is_safe_card_rel(target_id):
                 return jsonify({"success": False, "msg": "非法路径"})
             # 重新构建源路径
             src_path = os.path.join(CARDS_FOLDER, target_id.replace('/', os.sep))
             src_path = os.path.abspath(src_path)
             if not _is_under_base(src_path, str(CARDS_FOLDER)):
                 return jsonify({"success": False, "msg": "非法路径"})
        elif req_data.get('file_path'):
             src_path = req_data.get('file_path')
             src_path = os.path.normpath(src_path if os.path.isabs(src_path) else os.path.join(BASE_DIR, src_path))
             if snapshot_type == 'preset':
                 if not _is_valid_preset_path(src_path):
                     return jsonify({"success": False, "msg": "非法路径"})
             elif not _is_valid_lorebook_path(src_path):
                  return jsonify({"success": False, "msg": "非法路径"})

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
        
        if snapshot_type == 'preset':
            if file_path_param:
                filename = os.path.basename(file_path_param)
            elif target_id:
                filename = os.path.basename(target_id)
            backups_root = os.path.join(system_backups_dir, 'presets')
        elif snapshot_type == 'lorebook':
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


@bp.route('/api/cleanup_init_backups', methods=['POST'])
def api_cleanup_init_backups():
    """
    清理指定目标的 INIT 快照。
    默认 keep_latest=0：关闭编辑器时清空 INIT，下次进入再生成新的 INIT。
    """
    try:
        req = request.json or {}
        target_id = req.get('id')
        snapshot_type = req.get('type', 'card')
        file_path_param = req.get('file_path')
        keep_latest = int(req.get('keep_latest', 0) or 0)
        keep_latest = max(0, min(keep_latest, 5))

        system_backups_dir = os.path.join(DATA_DIR, 'system', 'backups')

        backups_root = ""
        filename = ""

        if snapshot_type == 'preset':
            if file_path_param:
                filename = os.path.basename(file_path_param)
            elif target_id:
                filename = os.path.basename(target_id)
            backups_root = os.path.join(system_backups_dir, 'presets')
        elif snapshot_type == 'lorebook':
            if target_id and target_id.startswith('embedded::'):
                real_card_id = target_id.replace('embedded::', '')
                filename = os.path.basename(real_card_id)
                backups_root = os.path.join(system_backups_dir, 'cards')
            else:
                if file_path_param:
                    filename = os.path.basename(file_path_param)
                elif target_id:
                    filename = os.path.basename(target_id)
                backups_root = os.path.join(system_backups_dir, 'lorebooks')
        else:
            filename = os.path.basename(target_id or '')
            backups_root = os.path.join(system_backups_dir, 'cards')

        name_no_ext = os.path.splitext(filename)[0]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip()
        target_dir = os.path.join(backups_root, safe_dir_name)

        if not os.path.exists(target_dir):
            return jsonify({"success": True, "removed": 0, "target_dir": target_dir})

        init_files = []
        for f in os.listdir(target_dir):
            f_lower = f.lower()
            if not (f_lower.endswith('.png') or f_lower.endswith('.json')):
                continue
            if name_no_ext and name_no_ext not in f:
                continue
            if "__KEY__" not in f:
                continue

            parts = f.split("__KEY__")
            if len(parts) <= 1:
                continue
            label = os.path.splitext(parts[1])[0]
            if label != 'INIT':
                continue

            full_p = os.path.join(target_dir, f)
            init_files.append((full_p, os.path.getmtime(full_p)))

        init_files.sort(key=lambda x: x[1], reverse=True)
        to_remove = init_files[keep_latest:]
        removed = 0

        for f_path, _ in to_remove:
            try:
                if os.path.exists(f_path):
                    os.remove(f_path)
                    removed += 1

                # 清理同名伴生备份
                base_path = os.path.splitext(f_path)[0]
                for ext in ['.json', *SIDECAR_EXTENSIONS]:
                    sidecar = base_path + ext
                    if os.path.exists(sidecar) and sidecar != f_path:
                        try:
                            os.remove(sidecar)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Cleanup INIT backup failed: {f_path}, err={e}")

        return jsonify({"success": True, "removed": removed, "target_dir": target_dir})
    except Exception as e:
        logger.error(f"Cleanup INIT backups error: {e}")
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
        if type_ == 'preset':
            target_path = target_file_path_param
        elif type_ == 'lorebook':
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
        
        # 2. 卡片类型可选标准化重写
        # 仅对卡片文件做标准化，避免把独立世界书 JSON 误判为角色卡并重写结构
        is_embedded_lorebook = (type_ == 'lorebook' and target_id.startswith('embedded::'))
        should_normalize = (type_ == 'card' or is_embedded_lorebook)
        if should_normalize:
            try:
                info = extract_card_info(target_path)
                if info:
                    write_card_metadata(target_path, info)
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
        if type_ == 'preset':
            schedule_reload(reason="restore_backup")
        elif type_ == 'lorebook' and not target_id.startswith('embedded'):
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

        safe_path = _resolve_safe_path(path, relative_to_base=False)
        if not safe_path or not os.path.exists(safe_path):
            return jsonify({"success": False, "msg": "文件不存在或非法路径"}), 400

        # 如果是图片，提取元数据；如果是JSON，直接读
        if safe_path.lower().endswith('.png'):
            info = extract_card_info(safe_path)
            return jsonify({"success": True, "data": info})
        else:
            with open(safe_path, 'r', encoding='utf-8') as f:
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

        ui_data = load_ui_data()
        key = resolve_ui_key(card_id)
        existing_folder = ui_data.get(key, {}).get('resource_folder')

        # 获取资源目录配置
        config = load_config()
        resources_dir_name = config.get('resources_dir', 'data/assets/card_assets')
        resources_dir = resources_dir_name if os.path.isabs(resources_dir_name) else os.path.join(BASE_DIR, resources_dir_name)
        
        # 确保资源目录存在
        if not os.path.exists(resources_dir):
            os.makedirs(resources_dir)

        if existing_folder:
            resource_path = existing_folder if os.path.isabs(existing_folder) else os.path.join(resources_dir, existing_folder)
            return jsonify({
                "success": True,
                "resource_folder": existing_folder,
                "resource_path": resource_path
            })
        
        # 获取角色卡信息
        card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        info = extract_card_info(card_path)
        if not info:
            return jsonify({"success": False, "msg": "未找到角色卡"})
        
        # 获取角色名称
        data_block = info.get('data', {}) if 'data' in info else info
        char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(card_path))[0]
        
        # 创建资源目录（与角色卡同名）
        resource_folder_name = sanitize_filename(char_name or 'untitled').strip() or 'untitled'
        if resource_folder_name.lower() in RESERVED_RESOURCE_NAMES:
            resource_folder_name = f"card_{resource_folder_name}"
        resource_folder_path = os.path.join(resources_dir, resource_folder_name)
        
        # 处理重名情况
        counter = 1
        base_folder_name = resource_folder_name
        while os.path.exists(resource_folder_path):
            resource_folder_name = sanitize_filename(f"{base_folder_name}_{counter}").strip() or f"untitled_{counter}"
            resource_folder_path = os.path.join(resources_dir, resource_folder_name)
            counter += 1
        
        # 创建目录
        os.makedirs(resource_folder_path)
        
        # 更新ui_data
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
        resources_dir_name = config.get('resources_dir', 'data/assets/card_assets')
        resources_dir = resources_dir_name if os.path.isabs(resources_dir_name) else os.path.join(BASE_DIR, resources_dir_name)
        
        # 确保资源目录存在
        if not os.path.exists(resources_dir):
            os.makedirs(resources_dir)
        
        # 处理路径
        if os.path.isabs(resource_path):
            # 绝对路径，直接使用
            final_path = resource_path
            resource_folder_name = resource_path
            check_name = os.path.basename(os.path.normpath(resource_path))
        else:
            # 相对路径，相对于resources目录
            final_path = os.path.join(resources_dir, resource_path)
            resource_folder_name = resource_path
            check_name = resource_path.replace('\\', '/').split('/')[0]
        
        # 检查保留字
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
        resources_dir_name = config.get('resources_dir', 'data/assets/card_assets')
        resources_dir = resources_dir_name if os.path.isabs(resources_dir_name) else os.path.join(BASE_DIR, resources_dir_name)
        
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
        if platform.system() == "Windows":
            os.startfile(resource_path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", resource_path])
        else:
            subprocess.Popen(["xdg-open", resource_path])
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Open resource folder error: {e}")
        return jsonify({"success": False, "msg": str(e)})

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
        
        # === 代理设置逻辑 ===
        proxy_setting = cfg.get('st_proxy', '').strip()
        proxies = {}
        if proxy_setting:
            proxies = {
                'http': proxy_setting,
                'https': proxy_setting
            }
        else:
            # 强制禁用代理 (绕过系统环境变量)
            proxies = {
                'http': None,
                'https': None
            }

        # 2. 检查文件
        rel_path = card_id.replace('/', os.sep)
        file_path = os.path.join(CARDS_FOLDER, rel_path)
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "Local file not found"})
        st_client = build_st_http_client(cfg, timeout=10)
        file_ext = os.path.splitext(file_path)[1].lower()
        with open(file_path, 'rb') as f:
            if file_ext == '.json':
                files = {'avatar': ('card.json', f, 'application/json')}
                data = {'file_type': 'json'}
            else:
                files = {'avatar': ('card.png', f, 'image/png')}
                data = {'file_type': 'png'}

            try:
                response = st_client.post(
                    '/api/characters/import',
                    files=files,
                    data=data,
                    timeout=10,
                )
            except STAuthError as error:
                return jsonify({"success": False, "msg": _format_st_auth_error(error)})

        if response.status_code == 200:
            st_response = response.json() if response.content else 'OK'
            ui_data = load_ui_data()
            ui_key = resolve_ui_key(card_id)
            _, last_sent_to_st = set_last_sent_to_st(ui_data, ui_key, time.time())
            save_ui_data(ui_data)

            target_id = card_id
            if ui_key in ctx.cache.bundle_map:
                target_id = ctx.cache.bundle_map[ui_key]
            ctx.cache.update_card_data(target_id, {'last_sent_to_st': last_sent_to_st})

            return jsonify({
                'success': True,
                'st_response': st_response,
                'last_sent_to_st': last_sent_to_st,
            })

        return jsonify({"success": False, "msg": _format_st_response_error(response, auth_type)})

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
                proxies=proxies,
                timeout=10, 
                headers=auth_headers
            )

        # 5. 处理结果
        if response.status_code == 200:
            st_response = response.json() if response.content else 'OK'
            ui_data = load_ui_data()
            ui_key = resolve_ui_key(card_id)
            _, last_sent_to_st = set_last_sent_to_st(ui_data, ui_key, time.time())
            save_ui_data(ui_data)

            target_id = card_id
            if ui_key in ctx.cache.bundle_map:
                target_id = ctx.cache.bundle_map[ui_key]
            ctx.cache.update_card_data(target_id, {'last_sent_to_st': last_sent_to_st})

            return jsonify({
                'success': True,
                'st_response': st_response,
                'last_sent_to_st': last_sent_to_st,
            })
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
        raw_res = cfg.get('resources_dir', 'data/assets/card_assets')
        res_base = raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res)
        target_dir = os.path.join(res_base, folder_name)

        if not os.path.exists(target_dir):
            return jsonify({"success": True, "skins": []})

        skins = []
        # 支持的图片扩展名
        valid_exts = {'.png', '.jpg', '.jpeg', '.jfif', '.gif', '.webp', '.bmp'}
        
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

        target_open = _resolve_safe_path(path, relative_to_base=relative_to_base)
        if not target_open:
            return jsonify({"success": False, "msg": "非法路径"}), 400

        if os.path.isfile(target_open):
            target_open = os.path.dirname(target_open)
            
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
        if ext not in ['.jpg', '.jpeg', '.jfif', '.png', '.webp', '.gif']:
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
