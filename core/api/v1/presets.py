"""
core/api/v1/presets.py
预设管理 API - 对齐扩展脚本的实现模式
"""
import os
import json
import logging
import shutil
import time
from io import BytesIO

from flask import Blueprint, request, jsonify, send_file
from core.config import BASE_DIR, load_config
from core.context import ctx
from core.data.ui_store import (
    get_last_sent_to_st,
    get_resource_item_categories,
    load_ui_data,
    save_ui_data,
    set_last_sent_to_st,
    set_resource_item_categories,
)
from core.services.preset_editor_schema import normalize_preset_content_for_save
from core.services.preset_editor_schema import resolve_global_save_dir_config_key
from core.services.preset_extensions import REGEX_EXTENSION_KEYS
from core.services.preset_extensions import TAVERN_HELPER_EXTENSION_KEYS
from core.services.preset_extensions import extract_regex_script_items
from core.services.preset_extensions import extract_tavern_helper_scripts
from core.services.preset_extensions import normalize_extensions_for_save
from core.services.preset_model import PRESET_KIND_LABELS, build_preset_detail
from core.services.preset_model import detect_preset_kind, merge_preset_content
from core.services.preset_model import strip_managed_kind_marker
from core.services.preset_versions import extract_preset_version_meta
from core.services.preset_versions import build_merge_version_plan
from core.services.preset_versions import generate_preset_family_id
from core.services.preset_versions import group_preset_list_items
from core.services.preset_versions import upsert_preset_version_meta
from core.services.preset_storage import (
    PresetConflictError,
    build_renamed_path,
    build_save_as_path,
    ensure_unique_path,
    load_preset_json,
    require_matching_revision,
    write_preset_json,
)
from core.services.scan_service import suppress_fs_events
from core.services.st_auth import STAuthError, build_st_http_client
from core.api.v1.system import _format_st_auth_error, _format_st_response_error
from core.utils.filesystem import sanitize_filename
from core.utils.format_validation import (
    is_valid_character_card_data,
    is_valid_legacy_world_info_data,
    is_valid_preset_data,
)
from core.utils.regex import extract_regex_from_preset_data
from core.utils.source_revision import build_file_source_revision

logger = logging.getLogger(__name__)
bp = Blueprint('presets', __name__)


def _paginate_preset_items(items):
    """按请求参数切分预设列表，同时保留无分页调用的兼容行为。"""
    total = len(items)
    pagination_requested = 'page' in request.args or 'page_size' in request.args

    if not pagination_requested:
        return items, total, 1, max(total, 20), 1

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(500, int(request.args.get('page_size', 20))))
    except (TypeError, ValueError):
        page_size = 20

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return items[start:start + page_size], total, page, page_size, total_pages

ALTERNATE_GLOBAL_ROOT_CONFIG_KEYS = (
    'st_openai_preset_dir',
)

VALID_PRESET_KINDS = {'openai', 'generic'}


def _resolve_requested_preset_kind(requested_kind: str, fallback_data, *, source_folder='', file_path='') -> str:
    kind = str(requested_kind or '').strip()
    if kind in VALID_PRESET_KINDS:
        return kind
    sanitized_fallback = strip_managed_kind_marker(fallback_data)
    return detect_preset_kind(sanitized_fallback, source_folder=source_folder, file_path=file_path)


def _normalize_category_path(value) -> str:
    if value is None:
        return ''
    path = str(value).replace('\\', '/').strip().strip('/')
    if not path:
        return ''
    parts = [part.strip() for part in path.split('/') if part.strip()]
    return '/'.join(parts)


def _get_parent_category(rel_path: str) -> str:
    rel_norm = str(rel_path or '').replace('\\', '/').strip('/')
    if not rel_norm or '/' not in rel_norm:
        return ''
    return _normalize_category_path(rel_norm.rsplit('/', 1)[0])


def _normalize_resource_item_key(path: str) -> str:
    if not path:
        return ''
    try:
        return os.path.normcase(os.path.normpath(str(path))).replace('\\', '/')
    except Exception:
        return ''


def _iter_category_ancestors(category: str):
    current = _normalize_category_path(category)
    while current:
        yield current
        if '/' not in current:
            break
        current = current.rsplit('/', 1)[0]


def _build_folder_metadata(items):
    all_folders = set()
    category_counts = {}
    folder_capabilities = {}

    def _ensure_capability(path):
        if path not in folder_capabilities:
            folder_capabilities[path] = {
                'has_physical_folder': False,
                'has_virtual_items': False,
                'can_create_child_folder': False,
                'can_rename_physical_folder': False,
                'can_delete_physical_folder': False,
            }
        return folder_capabilities[path]

    for item in items:
        display_category = _normalize_category_path(item.get('display_category'))
        if display_category:
            for path in _iter_category_ancestors(display_category):
                all_folders.add(path)
                category_counts[path] = category_counts.get(path, 0) + 1
                if item.get('type') != 'global':
                    _ensure_capability(path)['has_virtual_items'] = True

        physical_category = _normalize_category_path(item.get('physical_category'))
        if physical_category:
            for path in _iter_category_ancestors(physical_category):
                all_folders.add(path)
                caps = _ensure_capability(path)
                caps['has_physical_folder'] = True
                caps['can_create_child_folder'] = True
                caps['can_rename_physical_folder'] = True

    return {
        'all_folders': sorted(all_folders),
        'category_counts': category_counts,
        'folder_capabilities': folder_capabilities,
    }


def _add_physical_folder_nodes(folder_meta: dict, base_dir: str):
    if not isinstance(folder_meta, dict) or not base_dir or not os.path.exists(base_dir):
        return folder_meta

    all_folders = set(folder_meta.get('all_folders') or [])
    folder_capabilities = dict(folder_meta.get('folder_capabilities') or {})

    def _ensure_capability(path):
        if path not in folder_capabilities:
            folder_capabilities[path] = {
                'has_physical_folder': False,
                'has_virtual_items': False,
                'can_create_child_folder': False,
                'can_rename_physical_folder': False,
                'can_delete_physical_folder': False,
            }
        return folder_capabilities[path]

    root_caps = _ensure_capability('')
    root_caps['has_physical_folder'] = True
    root_caps['can_create_child_folder'] = True

    for root, dirs, files in os.walk(base_dir):
        rel_root = os.path.relpath(root, base_dir).replace('\\', '/')
        current_category = '' if rel_root == '.' else _normalize_category_path(rel_root)
        if not current_category:
            continue

        for path in _iter_category_ancestors(current_category):
            all_folders.add(path)
            caps = _ensure_capability(path)
            caps['has_physical_folder'] = True
            caps['can_create_child_folder'] = True
            caps['can_rename_physical_folder'] = True

        current_caps = _ensure_capability(current_category)
        current_caps['can_delete_physical_folder'] = not bool(dirs or files)

    folder_meta['all_folders'] = sorted(all_folders)
    folder_meta['folder_capabilities'] = folder_capabilities
    return folder_meta


def _is_in_category_subtree(display_category: str, selected_category: str) -> bool:
    display = _normalize_category_path(display_category)
    selected = _normalize_category_path(selected_category)
    if not selected:
        return True
    return display == selected or display.startswith(selected + '/')


def _item_matches_category(item: dict, selected_category: str) -> bool:
    selected = _normalize_category_path(selected_category)
    if not selected:
        return True

    display_categories = item.get('display_categories') or []
    if display_categories:
        for display_category in display_categories:
            if _is_in_category_subtree(display_category, selected):
                return True
        return False

    return _is_in_category_subtree(item.get('display_category', ''), selected)


def _safe_join_category_path(base_dir: str, category: str, leaf_name: str = '') -> str:
    base_abs = os.path.abspath(base_dir)
    rel_path = _normalize_category_path(category)
    parts = [part for part in rel_path.split('/') if part] if rel_path else []
    if leaf_name:
        parts.append(str(leaf_name).strip())

    candidate = os.path.abspath(os.path.join(base_abs, *parts)) if parts else base_abs
    try:
        if os.path.commonpath([candidate, base_abs]) != base_abs:
            return ''
    except Exception:
        return ''
    return candidate


def _save_resource_category_override(file_path: str, category: str) -> bool:
    ui_data = load_ui_data()
    payload = get_resource_item_categories(ui_data)
    mode_items = dict(payload.get('presets') or {})
    path_key = _normalize_resource_item_key(file_path)
    normalized_category = _normalize_category_path(category)

    if normalized_category:
        mode_items[path_key] = {
            'category': normalized_category,
            'updated_at': int(time.time()),
        }
    else:
        mode_items.pop(path_key, None)

    next_payload = {
        'worldinfo': dict(payload.get('worldinfo') or {}),
        'presets': mode_items,
    }
    set_resource_item_categories(ui_data, next_payload)
    return save_ui_data(ui_data)


def _is_resource_preset_path(file_path: str) -> bool:
    if not file_path or not os.path.exists(file_path):
        return False

    cfg = load_config()
    raw_resources = cfg.get('resources_dir', 'data/assets/card_assets')
    resources_root = raw_resources if os.path.isabs(raw_resources) else os.path.join(BASE_DIR, raw_resources)
    if not _safe_join(resources_root, os.path.relpath(file_path, resources_root).replace('\\', '/')):
        return False

    if not os.path.commonpath([os.path.abspath(file_path), os.path.abspath(resources_root)]) == os.path.abspath(resources_root):
        return False

    rel_path = os.path.relpath(file_path, resources_root).replace('\\', '/')
    return '/presets/' in f'/{rel_path}/'


def _build_global_folder_metadata(base_dir: str):
    items = []
    if os.path.exists(base_dir):
        for root, _dirs, files in os.walk(base_dir):
            for name in files:
                if not name.lower().endswith('.json'):
                    continue
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, base_dir).replace('\\', '/')
                physical_category = _get_parent_category(rel_path)
                items.append({'type': 'global', 'display_category': physical_category, 'physical_category': physical_category})
    return _add_physical_folder_nodes(_build_folder_metadata(items), base_dir)


def _get_cards_by_resource_folder():
    mapping = {}
    try:
        ui_data = load_ui_data()
        cache = getattr(ctx, 'cache', None)
        cards = list(getattr(cache, 'cards', []) or [])
        initialized = bool(getattr(cache, 'initialized', False))
        if cache is not None and not initialized and hasattr(cache, 'reload_from_db'):
            cache.reload_from_db()
            cards = list(getattr(cache, 'cards', []) or [])

        for card in cards:
            card_id = str(card.get('id') or '')
            if not card_id:
                continue
            ui_info = ui_data.get(card_id, {}) or {}
            res_folder = ui_info.get('resource_folder') or card.get('resource_folder')
            if not res_folder:
                continue
            mapping[str(res_folder)] = card
    except Exception:
        return {}
    return mapping


def _resolve_configured_global_root(config_key: str) -> str:
    cfg = load_config()
    raw_path = cfg.get(config_key)
    if not raw_path:
        return ''
    return raw_path if os.path.isabs(raw_path) else os.path.join(BASE_DIR, raw_path)


def _get_alternate_global_roots():
    roots = {}
    for config_key in ALTERNATE_GLOBAL_ROOT_CONFIG_KEYS:
        root_path = _resolve_configured_global_root(config_key)
        if root_path:
            roots[config_key] = root_path
    return roots


def _iter_global_preset_roots(presets_root: str):
    yield None, presets_root
    for config_key, root_path in _get_alternate_global_roots().items():
        yield config_key, root_path


def _resolve_preset_file_path(preset_id, presets_root):
    if not preset_id:
        return '', None, None

    if '::' in preset_id and not (
        preset_id.startswith('resource::')
        or preset_id.startswith('global::')
        or preset_id.startswith('global-alt::')
    ):
        return '', None, None

    if preset_id.startswith('resource::'):
        parts = preset_id.split('::', 2)
        if len(parts) != 3:
            return '', None, None

        _, folder, name = parts
        cfg = load_config()
        res_root = os.path.join(BASE_DIR, cfg.get('resources_dir', 'data/assets/card_assets'))
        folder_abs = _safe_join(res_root, folder)
        if not folder_abs:
            return '', None, None
        presets_base = os.path.join(folder_abs, 'presets')
        return _safe_join(presets_base, f'{name}.json'), 'resource', folder

    if preset_id.startswith('global::'):
        rel_path = preset_id.split('::', 1)[1]
        return _safe_join(presets_root, rel_path), 'global', None

    if preset_id.startswith('global-alt::'):
        parts = preset_id.split('::', 2)
        if len(parts) != 3:
            return '', None, None

        _, config_key, rel_path = parts
        root_path = _get_alternate_global_roots().get(config_key)
        if not root_path:
            return '', None, None
        return _safe_join(root_path, rel_path), 'global', config_key

    return _safe_join(presets_root, f'{preset_id}.json'), 'global', None


def _build_canonical_preset_id(file_path, preset_type, source_folder, presets_root):
    if not file_path:
        return ''

    if preset_type == 'resource' and source_folder:
        return f"resource::{source_folder}::{os.path.splitext(os.path.basename(file_path))[0]}"

    file_abs = os.path.abspath(file_path)
    presets_abs = os.path.abspath(presets_root)
    try:
        if os.path.commonpath([file_abs, presets_abs]) == presets_abs:
            rel_path = os.path.relpath(file_abs, presets_abs).replace('\\', '/')
            return f'global::{rel_path}'
    except Exception:
        pass

    for config_key, root_path in _get_alternate_global_roots().items():
        root_abs = os.path.abspath(root_path)
        try:
            if os.path.commonpath([file_abs, root_abs]) != root_abs:
                continue
        except Exception:
            continue

        rel_path = os.path.relpath(file_abs, root_abs).replace('\\', '/')
        return f'global-alt::{config_key}::{rel_path}'

    rel_path = os.path.basename(file_abs)
    return f'global::{rel_path}'


def _build_preset_ui_key(preset_type: str, file_path: str, preset_id: str, presets_root: str) -> str:
    if str(preset_type or '').strip().lower() == 'resource':
        path_key = os.path.abspath(str(file_path or '')).replace('\\', '/') if file_path else ''
        return f'preset::resource::{path_key}' if path_key else ''

    canonical_id = _build_canonical_preset_id(file_path, preset_type, None, presets_root)
    if canonical_id.startswith('global::'):
        return f'preset::{canonical_id}'

    if str(preset_id or '').startswith('global::'):
        return f'preset::{preset_id}'

    return ''


def _get_preset_last_sent_to_st(ui_data: dict, preset_type: str, file_path: str, preset_id: str, presets_root: str) -> float:
    ui_key = _build_preset_ui_key(preset_type, file_path, preset_id, presets_root)
    return get_last_sent_to_st(ui_data, ui_key) if ui_key else 0.0


def _build_st_openai_preset_payload(preset_data, file_path: str = '') -> dict:
    payload = preset_data if isinstance(preset_data, dict) else {}
    preset_name = str(payload.get('name') or payload.get('title') or '').strip()
    if not preset_name and file_path:
        preset_name = os.path.splitext(os.path.basename(file_path))[0].strip()
    return {
        'apiId': 'openai',
        'name': preset_name or 'Preset',
        'preset': payload,
    }


def _build_preset_kind_source_hint(preset_id: str, source_folder):
    if str(source_folder or '').strip():
        return source_folder
    preset_id = str(preset_id or '').strip()
    if preset_id.startswith('global-alt::st_openai_preset_dir::'):
        return 'st_openai_preset_dir'
    return source_folder

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
            os.makedirs(presets_root, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create presets directory: {e}")
    
    return presets_root


def _resolve_global_save_dir(preset_kind: str, raw_data=None) -> str:
    cfg = load_config()
    config_key = resolve_global_save_dir_config_key(raw_data, preset_kind)
    raw_path = cfg.get(config_key)
    if not raw_path:
        raw_path = cfg.get('presets_dir', 'data/library/presets')
    target_root = raw_path if os.path.isabs(raw_path) else os.path.join(BASE_DIR, raw_path)
    if not os.path.exists(target_root):
        try:
            os.makedirs(target_root, exist_ok=True)
        except Exception as e:
            logger.error(f'Failed to create presets directory: {e}')
    return target_root


def _build_saved_preset_response(file_path: str, preset_type: str, source_folder, presets_root: str, preset_kind_hint: str = ''):
    raw_data = load_preset_json(file_path)
    return build_preset_detail(
        preset_id=_build_canonical_preset_id(file_path, preset_type, source_folder, presets_root),
        file_path=file_path,
        filename=os.path.basename(file_path),
        source_type=preset_type,
        source_folder=source_folder,
        raw_data=raw_data,
        base_dir=BASE_DIR,
        preset_kind_hint=preset_kind_hint,
    )


def _resolve_existing_preset_target_dir(file_path: str, preset_type: str, source_folder, presets_root: str) -> str:
    if preset_type == 'resource' and source_folder:
        return os.path.dirname(file_path)
    if preset_type == 'global' and source_folder:
        return _get_alternate_global_roots().get(source_folder) or os.path.dirname(file_path)
    return presets_root


def _list_family_version_paths(file_path: str, preset_type: str, source_folder, presets_root: str, family_id: str):
    if not family_id:
        return []

    version_paths = []
    for item in _scan_preset_scope_items(preset_type, source_folder, presets_root):
        version_meta = item.get('preset_version') or {}
        if version_meta.get('family_id') != family_id:
            continue
        member_path, _member_type, _member_source_folder = _resolve_preset_file_path(item.get('id'), presets_root)
        if member_path and os.path.exists(member_path):
            version_paths.append(member_path)
    return version_paths


def _rewrite_family_default_flags(
    file_path: str,
    *,
    preset_type: str,
    source_folder,
    presets_root: str,
    target_default_path: str,
):
    raw_data = load_preset_json(file_path)
    version_meta = extract_preset_version_meta(
        raw_data,
        fallback_name=raw_data.get('name', ''),
        fallback_filename=os.path.basename(file_path),
    )
    family_id = version_meta.get('family_id') or ''
    if not family_id:
        return

    target_default_norm = os.path.normcase(os.path.normpath(target_default_path))
    for version_path in _list_family_version_paths(file_path, preset_type, source_folder, presets_root, family_id):
        member_raw = load_preset_json(version_path)
        member_meta = extract_preset_version_meta(
            member_raw,
            fallback_name=member_raw.get('name', ''),
            fallback_filename=os.path.basename(version_path),
        )
        updated = upsert_preset_version_meta(
            member_raw,
            family_id=member_meta.get('family_id') or family_id,
            family_name=member_meta.get('family_name') or version_meta.get('family_name') or member_raw.get('name', ''),
            version_label=member_meta.get('version_label') or os.path.splitext(os.path.basename(version_path))[0],
            version_order=member_meta.get('version_order'),
            is_default_version=os.path.normcase(os.path.normpath(version_path)) == target_default_norm,
        )
        write_preset_json(version_path, updated)


def _promote_next_family_default_if_needed(file_path: str, preset_type: str, source_folder, presets_root: str):
    raw_data = load_preset_json(file_path)
    version_meta = extract_preset_version_meta(
        raw_data,
        fallback_name=raw_data.get('name', ''),
        fallback_filename=os.path.basename(file_path),
    )
    if not version_meta.get('is_versioned') or not version_meta.get('is_default_version'):
        return

    remaining_paths = [
        path for path in _list_family_version_paths(file_path, preset_type, source_folder, presets_root, version_meta.get('family_id') or '')
        if os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(file_path))
    ]
    if not remaining_paths:
        return

    ranked_paths = []
    for version_path in remaining_paths:
        member_raw = load_preset_json(version_path)
        member_meta = extract_preset_version_meta(
            member_raw,
            fallback_name=member_raw.get('name', ''),
            fallback_filename=os.path.basename(version_path),
        )
        ranked_paths.append(
            (
                int(member_meta.get('version_order') or 100),
                -float(os.path.getmtime(version_path)),
                os.path.basename(version_path),
                version_path,
            )
        )

    ranked_paths.sort()
    _rewrite_family_default_flags(
        remaining_paths[0],
        preset_type=preset_type,
        source_folder=source_folder,
        presets_root=presets_root,
        target_default_path=ranked_paths[0][3],
    )


def _handle_preset_save_as_version(data):
    preset_id = str(data.get('preset_id') or '').strip()
    content = data.get('content')
    requested_preset_kind = str(data.get('preset_kind') or '').strip()
    version_label = str(data.get('version_label') or '').strip()
    name = str(data.get('name') or (content or {}).get('name') or '').strip()
    if not preset_id:
        return jsonify({'success': False, 'msg': '缺少预设ID'}), 400
    if not name:
        return jsonify({'success': False, 'msg': '名称不能为空'}), 400
    if not version_label:
        return jsonify({'success': False, 'msg': '版本标记不能为空'}), 400

    presets_root = _get_presets_path()
    file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)
    if not file_path:
        return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

    require_matching_revision(file_path, str(data.get('source_revision') or '').strip())
    raw_data = load_preset_json(file_path)
    preset_kind = _resolve_requested_preset_kind(
        requested_preset_kind,
        raw_data,
        source_folder=source_folder,
        file_path=file_path,
    )

    source_meta = extract_preset_version_meta(
        raw_data,
        fallback_name=raw_data.get('name', ''),
        fallback_filename=os.path.basename(file_path),
    )
    family_id = source_meta.get('family_id') or generate_preset_family_id()
    family_name = source_meta.get('family_name') or raw_data.get('name') or os.path.splitext(os.path.basename(file_path))[0]
    source_version_label = source_meta.get('version_label') or os.path.splitext(os.path.basename(file_path))[0]
    source_version_order = int(source_meta.get('version_order') or 100)

    if not source_meta.get('is_versioned'):
        raw_data = upsert_preset_version_meta(
            raw_data,
            family_id=family_id,
            family_name=family_name,
            version_label=source_version_label,
            version_order=source_version_order,
            is_default_version=True,
        )

    final_content = merge_preset_content(raw_data, preset_kind, content or {})
    if isinstance(final_content, dict):
        final_content['name'] = name

    family_paths = _list_family_version_paths(file_path, preset_type, source_folder, presets_root, family_id)
    next_version_order = source_version_order + 10
    if family_paths:
        next_version_order = max(
            extract_preset_version_meta(
                load_preset_json(path),
                fallback_name='',
                fallback_filename=os.path.basename(path),
            ).get('version_order') or 100
            for path in family_paths
        ) + 10

    final_content = upsert_preset_version_meta(
        final_content,
        family_id=family_id,
        family_name=family_name,
        version_label=version_label,
        version_order=next_version_order,
        is_default_version=False,
    )

    target_dir = _resolve_existing_preset_target_dir(file_path, preset_type, source_folder, presets_root)
    clone_path = ensure_unique_path(build_save_as_path(target_dir, name))

    suppress_fs_events(2.5)
    if not source_meta.get('is_versioned'):
        write_preset_json(file_path, raw_data)
    new_revision = write_preset_json(clone_path, final_content)
    detail = _build_saved_preset_response(clone_path, preset_type, source_folder, presets_root, preset_kind_hint=preset_kind)
    family_info, current_version, available_versions = _build_family_context_for_detail(
        clone_path,
        preset_type,
        source_folder,
        presets_root,
    )
    detail['family_info'] = family_info
    detail['current_version'] = current_version
    detail['available_versions'] = available_versions or []
    return jsonify({'success': True, 'source_revision': new_revision, 'preset': detail, 'preset_id': detail['id']})


def _save_preset_legacy(data):
    preset_id = data.get('id')
    content = data.get('content')

    if preset_id is None or content is None:
        return jsonify({"success": False, "msg": "缺少必要参数"})

    content_to_write = content
    if isinstance(content, str):
        try:
            content_to_write = json.loads(content)
        except json.JSONDecodeError:
            return jsonify({"success": False, "msg": "JSON格式无效"}), 400
    content_to_write = strip_managed_kind_marker(content_to_write)

    presets_root = _get_presets_path()
    file_path, _preset_type, _source_folder = _resolve_preset_file_path(preset_id, presets_root)

    if not file_path:
        return jsonify({"success": False, "msg": "Invalid preset ID"}), 400

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    write_preset_json(file_path, content_to_write)
    return jsonify({"success": True, "msg": "预设已保存"})


def _handle_preset_overwrite(data):
    preset_id = str(data.get('preset_id') or '').strip()
    content = data.get('content')
    requested_preset_kind = str(data.get('preset_kind') or '').strip()
    presets_root = _get_presets_path()
    file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)

    if not file_path:
        return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

    require_matching_revision(file_path, str(data.get('source_revision') or '').strip())
    raw_data = load_preset_json(file_path)
    preset_kind = _resolve_requested_preset_kind(
        requested_preset_kind,
        raw_data,
        source_folder=source_folder,
        file_path=file_path,
    )

    merged = merge_preset_content(raw_data, preset_kind, content)
    suppress_fs_events(2.5)
    new_revision = write_preset_json(file_path, merged)
    detail = _build_saved_preset_response(file_path, preset_type, source_folder, presets_root)
    return jsonify({'success': True, 'source_revision': new_revision, 'preset': detail})


def _handle_preset_save_as(data):
    if bool(data.get('create_as_version')):
        return _handle_preset_save_as_version(data)

    content = data.get('content')
    name = str(data.get('name') or (content or {}).get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'msg': '名称不能为空'}), 400

    preset_kind = _resolve_requested_preset_kind(str(data.get('preset_kind') or '').strip(), content or {})
    final_content = merge_preset_content({}, preset_kind, content or {})
    if isinstance(final_content, dict):
        final_content['name'] = name

    target_dir = _resolve_global_save_dir(preset_kind, final_content)
    file_path = ensure_unique_path(build_save_as_path(target_dir, name))

    suppress_fs_events(2.5)
    new_revision = write_preset_json(file_path, final_content)
    detail = _build_saved_preset_response(file_path, 'global', None, _get_presets_path(), preset_kind_hint=preset_kind)
    return jsonify({'success': True, 'source_revision': new_revision, 'preset': detail, 'preset_id': detail['id']})


def _handle_preset_rename(data):
    preset_id = str(data.get('preset_id') or '').strip()
    new_name = str(data.get('new_name') or '').strip()
    if not new_name:
        return jsonify({'success': False, 'msg': '名称不能为空'}), 400

    presets_root = _get_presets_path()
    file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)
    if not file_path:
        return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

    require_matching_revision(file_path, str(data.get('source_revision') or '').strip())
    target_path = build_renamed_path(file_path, new_name)
    if os.path.normcase(os.path.normpath(target_path)) != os.path.normcase(os.path.normpath(file_path)) and os.path.exists(target_path):
        return jsonify({'success': False, 'msg': '目标位置已存在同名文件'}), 400

    raw_data = load_preset_json(file_path)
    if isinstance(raw_data, dict) and ('name' in raw_data or preset_type == 'global'):
        raw_data['name'] = new_name
    suppress_fs_events(2.5)
    write_preset_json(file_path, raw_data)
    os.rename(file_path, target_path)
    detail = _build_saved_preset_response(target_path, preset_type, source_folder, presets_root)
    return jsonify({'success': True, 'source_revision': detail['source_revision'], 'preset': detail, 'preset_id': detail['id']})


def _handle_preset_delete_via_save(data):
    preset_id = str(data.get('preset_id') or '').strip()
    presets_root = _get_presets_path()
    file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)
    if not file_path:
        return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

    require_matching_revision(file_path, str(data.get('source_revision') or '').strip())
    suppress_fs_events(2.5)
    _promote_next_family_default_if_needed(file_path, preset_type, source_folder, presets_root)
    os.remove(file_path)
    return jsonify({'success': True, 'msg': '预设已删除'})


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

        # A preset directory may contain old arbitrary JSON, but typed card and
        # world-info payloads must not be rendered as preset entries.
        if is_valid_character_card_data(data) or is_valid_legacy_world_info_data(data):
            return None

        if not isinstance(data, dict):
            data = {}
        
        preset_id = os.path.splitext(filename)[0]
        
        # 1. 提取基本信息
        name = data.get('name') or data.get('title') or preset_id
        description = data.get('description') or data.get('note') or ''
        
        # 2. 提取完整采样参数 (Samplers)
        samplers = {
            'temperature': data.get('temperature'),
            'max_tokens': data.get('max_tokens') or data.get('openai_max_tokens') or data.get('max_length'),
            'min_length': data.get('min_length'),
            'top_p': data.get('top_p'),
            'top_k': data.get('top_k'),
            'top_a': data.get('top_a'),              # ST 特有
            'min_p': data.get('min_p'),              # ST 特有
            'tail_free_sampling': data.get('tfs'),   # TFS
            'repetition_penalty': data.get('repetition_penalty') or data.get('rep_pen'),
            'repetition_penalty_range': data.get('repetition_penalty_range'),
            'frequency_penalty': data.get('frequency_penalty') or data.get('freq_pen'),
            'presence_penalty': data.get('presence_penalty') or data.get('pres_pen'),
            'typical_p': data.get('typical'),        # Typical Sampling
            'temperature_last': data.get('temperature_last', False), # 采样顺序
            'mirostat_mode': data.get('mirostat_mode'),
            'mirostat_tau': data.get('mirostat_tau'),
            'mirostat_eta': data.get('mirostat_eta'),
        }

        # 3. 提取上下文与输出配置 (Config)
        config = {
            'context_length': data.get('openai_max_context') or data.get('context_length'),
            'streaming': data.get('stream_openai', False),
            'wrap_in_quotes': data.get('wrap_in_quotes', False),
            'names_behavior': data.get('names_behavior'), # 0=Default, 1=Force, etc.
            'show_thoughts': data.get('show_thoughts', True), # CoT
            'reasoning_effort': data.get('reasoning_effort'), # O1 parameters
            'seed': data.get('seed', -1),
        }

        # 4. 提取格式化模板 (Formatting)
        formatting = {
            'system_prompt_marker': data.get('use_makersuite_sysprompt', True), # 特殊开关
            'wi_format': data.get('wi_format'),
            'scenario_format': data.get('scenario_format'),
            'personality_format': data.get('personality_format'),
            'assistant_prefill': data.get('assistant_prefill'),
            'assistant_impersonation': data.get('assistant_impersonation'),
            'impersonation_prompt': data.get('impersonation_prompt'),
            'new_chat_prompt': data.get('new_chat_prompt'),
            'continue_nudge_prompt': data.get('continue_nudge_prompt'),
            'bias_preset': data.get('bias_preset_selected'),
        }

        # 5. 提取 Prompts (使用之前的标准化逻辑)
        prompts = _normalize_prompts(data)
        prompt_count = len(prompts) if isinstance(prompts, list) else 0
        
        # 6. 提取扩展
        regexes = _extract_regex_from_preset(data)
        extensions = data.get('extensions')
        extensions = extensions if isinstance(extensions, dict) else {}
        regex_count = len(regexes) or len(extract_regex_script_items(extensions))
        script_count = len(extract_tavern_helper_scripts(extensions))
        mtime = os.path.getmtime(file_path)
        file_size = os.path.getsize(file_path)
        
        return {
            'summary': {
                'id': preset_id,
                'name': name,
                'description': description[:200] if description else '',
                'filename': filename,
                'temperature': samplers['temperature'],
                'max_tokens': samplers['max_tokens'],
                'prompt_count': prompt_count,
                'regex_count': regex_count,
                'script_count': script_count,
                'mtime': mtime,
                'file_size': file_size,
            },
            'details': {
                'id': preset_id,
                'name': name,
                'description': description,
                'filename': filename,
                'path': os.path.relpath(file_path, BASE_DIR),
                
                # 分组数据
                'samplers': samplers,
                'config': config,
                'formatting': formatting,
                
                # 列表数据
                'prompts': prompts,
                'extensions': extensions,
                
                # 兼容旧前端字段 (Flattened)
                'temperature': samplers['temperature'],
                'max_tokens': samplers['max_tokens'],
                'top_p': samplers['top_p'],
                'top_k': samplers['top_k'],
                'prompt_count': prompt_count,
                'regex_count': regex_count,
                'script_count': script_count,
                
                # 原始数据
                'raw_data': data,
                
                'mtime': mtime,
                'file_size': file_size,
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to parse preset {filename}: {e}")
        return None


def _match_preset_search(item: dict, search: str) -> bool:
    if not search:
        return True

    search = str(search or '').lower().strip()
    if not search:
        return True

    for field in ('name', 'description', 'family_name', 'default_version_label'):
        if search in str(item.get(field, '')).lower():
            return True

    for version in item.get('versions') or []:
        if search in str(version.get('name', '')).lower():
            return True
        version_meta = version.get('preset_version') or {}
        if search in str(version_meta.get('version_label', '')).lower():
            return True

    return False


def _build_scoped_preset_summary(
    file_path,
    *,
    source_type,
    source_folder,
    presets_root,
    root_scope_key,
    display_category='',
    physical_category='',
    category_mode='',
    category_override='',
    owner_card_id='',
    owner_card_name='',
    owner_card_category='',
):
    parsed = _parse_preset_file(file_path, os.path.basename(file_path))
    if not parsed:
        return None

    item = parsed['summary']
    canonical_id = _build_canonical_preset_id(file_path, source_type, source_folder, presets_root)
    preset_kind = detect_preset_kind(
        parsed['details'].get('raw_data') or {},
        source_folder=_build_preset_kind_source_hint(canonical_id, source_folder),
        file_path=file_path,
    )
    version_meta = extract_preset_version_meta(
        parsed['details'].get('raw_data') or {},
        fallback_name=item.get('name', ''),
        fallback_filename=item.get('filename', ''),
    )

    item['id'] = canonical_id
    item['type'] = source_type
    item['source_type'] = source_type
    item['source_folder'] = source_folder
    item['root_scope_key'] = root_scope_key
    item['path'] = os.path.relpath(file_path, BASE_DIR)
    item['display_category'] = display_category
    item['physical_category'] = physical_category
    item['category_mode'] = category_mode
    item['category_override'] = category_override
    item['owner_card_id'] = owner_card_id
    item['owner_card_name'] = owner_card_name
    item['owner_card_category'] = owner_card_category
    item['preset_kind'] = preset_kind
    item['preset_kind_label'] = PRESET_KIND_LABELS[preset_kind]
    item['preset_version'] = version_meta
    return item


def _scan_preset_scope_items(preset_type, source_folder, presets_root):
    if preset_type == 'resource' and source_folder:
        scope_root = os.path.join(
            os.path.join(BASE_DIR, load_config().get('resources_dir', 'data/assets/card_assets')),
            source_folder,
            'presets',
        )
        root_scope_key = f'resource::{source_folder}'
    elif preset_type == 'global' and source_folder:
        scope_root = _get_alternate_global_roots().get(source_folder)
        root_scope_key = source_folder
    else:
        scope_root = presets_root
        root_scope_key = 'global'

    if not scope_root or not os.path.exists(scope_root):
        return []

    source_items = []
    for root, _dirs, files in os.walk(scope_root):
        for name in files:
            if not name.lower().endswith('.json'):
                continue
            full_path = os.path.join(root, name)
            if not os.path.isfile(full_path):
                continue
            rel_path = os.path.relpath(full_path, scope_root).replace('\\', '/')
            physical_category = _get_parent_category(rel_path)
            item = _build_scoped_preset_summary(
                full_path,
                source_type=preset_type,
                source_folder=source_folder,
                presets_root=presets_root,
                root_scope_key=root_scope_key,
                display_category=physical_category if preset_type == 'global' else '',
                physical_category=physical_category if preset_type == 'global' else '',
                category_mode='physical' if preset_type == 'global' else 'inherited',
            )
            if item:
                source_items.append(item)

    return source_items


def _build_family_context_for_detail(file_path, preset_type, source_folder, presets_root):
    source_items = _scan_preset_scope_items(preset_type, source_folder, presets_root)
    if not source_items:
        return None, None, None

    grouped_items = group_preset_list_items(source_items)
    canonical_id = _build_canonical_preset_id(file_path, preset_type, source_folder, presets_root)

    for entry in grouped_items:
        if entry.get('entry_type') != 'family':
            continue
        versions = entry.get('versions') or []
        current_version = next((version for version in versions if version.get('id') == canonical_id), None)
        if not current_version:
            continue

        family_info = {
            'entry_type': 'family',
            'id': entry.get('id'),
            'family_id': entry.get('family_id'),
            'family_name': entry.get('family_name'),
            'default_version_id': entry.get('default_version_id'),
            'default_version_label': entry.get('default_version_label'),
            'version_count': entry.get('version_count'),
            'source_type': entry.get('source_type'),
            'root_scope_key': entry.get('root_scope_key'),
        }
        current_meta = current_version.get('preset_version') or {}
        current_version_payload = {
            'id': current_version.get('id'),
            'name': current_version.get('name'),
            'version_label': current_meta.get('version_label'),
            'version_order': current_meta.get('version_order'),
            'is_default_version': bool(current_meta.get('is_default_version')),
        }
        available_versions = [
            {
                'id': version.get('id'),
                'name': version.get('name'),
                'version_label': (version.get('preset_version') or {}).get('version_label'),
                'version_order': (version.get('preset_version') or {}).get('version_order'),
                'is_default_version': bool((version.get('preset_version') or {}).get('is_default_version')),
            }
            for version in versions
        ]
        return family_info, current_version_payload, available_versions

    return None, None, None


def _load_preset_version_member(preset_id: str, presets_root: str):
    file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)
    if not file_path:
        return None
    if not os.path.exists(file_path):
        return None

    raw_data = load_preset_json(file_path)
    preset_kind = _resolve_requested_preset_kind(
        '',
        raw_data,
        source_folder=source_folder,
        file_path=file_path,
    )
    version_meta = extract_preset_version_meta(
        raw_data,
        fallback_name=raw_data.get('name', ''),
        fallback_filename=os.path.basename(file_path),
    )
    root_scope_key = 'global'
    if preset_type == 'resource' and source_folder:
        root_scope_key = f'resource::{source_folder}'
    elif preset_type == 'global' and source_folder:
        root_scope_key = source_folder

    return {
        'id': _build_canonical_preset_id(file_path, preset_type, source_folder, presets_root),
        'file_path': file_path,
        'preset_type': preset_type,
        'source_folder': source_folder,
        'root_scope_key': root_scope_key,
        'raw_data': raw_data,
        'preset_kind': preset_kind,
        'preset_version': version_meta,
        'name': raw_data.get('name') or os.path.splitext(os.path.basename(file_path))[0],
        'filename': os.path.basename(file_path),
    }


def _scope_signature_for_member(member: dict):
    return (
        str(member.get('preset_type') or '').strip(),
        str(member.get('source_folder') or '').strip(),
    )


def _dedupe_preset_ids(preset_ids, *, exclude_id=''):
    unique_ids = []
    seen_ids = set()
    excluded = str(exclude_id or '').strip()
    for preset_id in preset_ids or []:
        normalized = str(preset_id or '').strip()
        if not normalized or normalized == excluded or normalized in seen_ids:
            continue
        seen_ids.add(normalized)
        unique_ids.append(normalized)
    return unique_ids


def _build_family_detail_response(file_path: str, preset_type: str, source_folder, presets_root: str, *, preset_kind_hint=''):
    detail = _build_saved_preset_response(
        file_path,
        preset_type,
        source_folder,
        presets_root,
        preset_kind_hint=preset_kind_hint,
    )
    family_info, current_version, available_versions = _build_family_context_for_detail(
        file_path,
        preset_type,
        source_folder,
        presets_root,
    )
    detail['family_info'] = family_info
    detail['current_version'] = current_version
    detail['available_versions'] = available_versions or []
    return detail


def _coerce_member_to_merge_entry(member: dict, *, family_id: str):
    entry = {
        'id': member.get('id'),
        'name': member.get('name'),
        'filename': member.get('filename'),
        'preset_version': dict(member.get('preset_version') or {}),
    }
    if family_id:
        entry['family_id'] = family_id
    entry['default_version_id'] = str(member.get('id') or '').strip()
    return entry


def _apply_version_plan_members(planned_members, presets_root: str):
    for member in planned_members or []:
        file_path, _preset_type, _source_folder = _resolve_preset_file_path(member.get('id'), presets_root)
        if not file_path or not os.path.exists(file_path):
            continue
        raw_data = load_preset_json(file_path)
        version_meta = member.get('preset_version') or {}
        updated = upsert_preset_version_meta(
            raw_data,
            family_id=version_meta.get('family_id') or '',
            family_name=version_meta.get('family_name') or '',
            version_label=version_meta.get('version_label') or os.path.splitext(os.path.basename(file_path))[0],
            version_order=version_meta.get('version_order'),
            is_default_version=bool(version_meta.get('is_default_version')),
        )
        write_preset_json(file_path, updated)


def _resolve_family_default_version_id(preset_id: str, presets_root: str) -> str:
    preset_id = str(preset_id or '').strip()
    if not preset_id or '::' not in preset_id:
        return ''

    parts = preset_id.split('::')
    if not parts:
        return ''

    source_type = parts[0]
    source_folder = None

    if source_type == 'resource':
        if len(parts) < 4 or parts[1] != 'resource':
            return ''
        source_folder = parts[2]
        family_id = '::'.join(parts[3:]).strip()
    elif source_type == 'global':
        if len(parts) < 3:
            return ''
        root_scope_key = parts[1]
        source_folder = root_scope_key if root_scope_key and root_scope_key != 'global' else None
        family_id = '::'.join(parts[2:]).strip()
    else:
        return ''

    if not family_id:
        return ''

    source_items = _scan_preset_scope_items(source_type, source_folder, presets_root)
    if not source_items:
        return ''

    for entry in group_preset_list_items(source_items):
        if entry.get('entry_type') != 'family':
            continue
        if entry.get('id') != preset_id:
            continue
        return str(entry.get('default_version_id') or '').strip()

    return ''


def _inherit_family_default_version_fields(grouped_items):
    for item in grouped_items:
        if not isinstance(item, dict) or item.get('entry_type') != 'family':
            continue

        default_version_id = str(item.get('default_version_id') or '').strip()
        if not default_version_id:
            continue

        default_version = next(
            (
                version for version in (item.get('versions') or [])
                if str(version.get('id') or '').strip() == default_version_id
            ),
            None,
        )
        if not default_version:
            continue

        item['last_sent_to_st'] = default_version.get('last_sent_to_st', item.get('last_sent_to_st', 0))
        item['preset_kind'] = default_version.get('preset_kind', item.get('preset_kind', ''))
        item['preset_kind_label'] = default_version.get('preset_kind_label', item.get('preset_kind_label', ''))

    return grouped_items


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
        selected_category = _normalize_category_path(request.args.get('category', ''))

        source_items = []
        seen_global_ids = set()
        items = []
        presets_root = _get_presets_path()
        ui_data = load_ui_data()
        resource_item_categories = get_resource_item_categories(ui_data).get('presets', {})
        cards_by_resource_folder = _get_cards_by_resource_folder()

        # 1. 扫描全局目录
        if filter_type in ['all', 'global']:
            for config_key, root_dir in _iter_global_preset_roots(presets_root):
                if not root_dir or not os.path.exists(root_dir):
                    continue

                for root, _dirs, files in os.walk(root_dir):
                    for f in files:
                        if not f.lower().endswith('.json'):
                            continue

                        full_path = os.path.join(root, f)
                        if not os.path.isfile(full_path):
                            continue

                        rel_path = os.path.relpath(full_path, root_dir).replace('\\', '/')
                        physical_category = _get_parent_category(rel_path)
                        item = _build_scoped_preset_summary(
                            full_path,
                            source_type='global',
                            source_folder=config_key,
                            presets_root=presets_root,
                            root_scope_key='global' if not config_key else config_key,
                            display_category=physical_category,
                            physical_category=physical_category,
                            category_mode='physical',
                        )
                        if not item:
                            continue
                        canonical_id = item['id']
                        if canonical_id in seen_global_ids:
                            continue
                        seen_global_ids.add(canonical_id)
                        if config_key:
                            item['id'] = canonical_id
                            item['source_folder'] = config_key
                        else:
                            item['id'] = canonical_id
                            item['source_folder'] = None
                        item['type'] = 'global'
                        item['source_type'] = 'global'
                        item['last_sent_to_st'] = _get_preset_last_sent_to_st(
                            ui_data,
                            'global',
                            full_path,
                            canonical_id,
                            presets_root,
                        )
                        item['path'] = os.path.relpath(full_path, BASE_DIR)
                        item['display_category'] = physical_category
                        item['physical_category'] = physical_category
                        item['category_mode'] = 'physical'
                        item['category_override'] = ''
                        item['owner_card_id'] = ''
                        item['owner_card_name'] = ''
                        item['owner_card_category'] = ''

                        source_items.append(item)
        
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
                            
                            item = None
                            if os.path.isfile(full_path):
                                path_key = _normalize_resource_item_key(full_path)
                                override_info = resource_item_categories.get(path_key) or {}
                                override_category = _normalize_category_path(override_info.get('category'))
                                owner_card = cards_by_resource_folder.get(folder) or {}
                                owner_category = _normalize_category_path(owner_card.get('category', ''))
                                item = _build_scoped_preset_summary(
                                    full_path,
                                    source_type='resource',
                                    source_folder=folder,
                                    presets_root=presets_root,
                                    root_scope_key=f'resource::{folder}',
                                    display_category=override_category or owner_category,
                                    physical_category='',
                                    category_mode='override' if override_category else 'inherited',
                                    category_override=override_category,
                                    owner_card_id=owner_card.get('id', ''),
                                    owner_card_name=owner_card.get('char_name', ''),
                                    owner_card_category=owner_category,
                                )
                            if item:
                                item['last_sent_to_st'] = _get_preset_last_sent_to_st(
                                    ui_data,
                                    'resource',
                                    full_path,
                                    item.get('id', ''),
                                    presets_root,
                                )
                                source_items.append(item)
                                
                except Exception as e:
                    logger.error(f"Error scanning resource presets: {e}")
        
        folder_meta = _add_physical_folder_nodes(_build_folder_metadata(source_items), presets_root)

        grouped_items = _inherit_family_default_version_fields(group_preset_list_items(source_items))

        for item in grouped_items:
            if not _item_matches_category(item, selected_category):
                continue
            if not _match_preset_search(item, search):
                continue
            items.append(item)

        paginated_items, total, page, page_size, total_pages = _paginate_preset_items(items)

        return jsonify({
            "success": True,
            "items": paginated_items,
            "count": total,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "all_folders": folder_meta['all_folders'],
            "category_counts": folder_meta['category_counts'],
            "folder_capabilities": folder_meta['folder_capabilities'],
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
        file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)

        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "Preset not found"}), 404
        
        try:
            with open(file_path, 'r', encoding='utf-8') as handle:
                raw_data = json.load(handle)
        except Exception as exc:
            logger.error(f"Failed to read preset detail: {exc}")
            return jsonify({"success": False, "msg": "Failed to parse preset"}), 500

        parsed = _parse_preset_file(file_path, os.path.basename(file_path))
        if not parsed:
            return jsonify({"success": False, "msg": "Failed to parse preset"}), 500

        details = parsed['details']
        detail_payload = build_preset_detail(
            preset_id=_build_canonical_preset_id(file_path, preset_type, source_folder, presets_root),
            file_path=file_path,
            filename=os.path.basename(file_path),
            source_type=preset_type,
            source_folder=_build_preset_kind_source_hint(preset_id, source_folder),
            raw_data=raw_data,
            base_dir=BASE_DIR,
        )
        details.update(detail_payload)
        family_info, current_version, available_versions = _build_family_context_for_detail(
            file_path,
            preset_type,
            source_folder,
            presets_root,
        )
        details['family_info'] = family_info
        details['current_version'] = current_version
        details['available_versions'] = available_versions or []
        details['last_sent_to_st'] = _get_preset_last_sent_to_st(
            load_ui_data(),
            preset_type,
            file_path,
            details.get('id', preset_id),
            presets_root,
        )
        
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

        source_context = str(request.form.get('source_context') or '').strip().lower()
        target_category = _normalize_category_path(request.form.get('target_category'))
        allow_global_fallback = str(request.form.get('allow_global_fallback') or '').strip().lower() in ('1', 'true', 'yes', 'on')

        if source_context and source_context != 'global' and not target_category and not allow_global_fallback:
            return jsonify({
                "success": False,
                "msg": "当前不在全局分类上下文，上传到全局目录需要明确确认。",
                "requires_global_fallback_confirmation": True,
                "fallback_target": "global_root",
            })
        
        presets_root = _get_presets_path()
        target_dir = _safe_join_category_path(presets_root, target_category)
        if not target_dir:
            return jsonify({"success": False, "msg": "目标分类不合法"})
        os.makedirs(target_dir, exist_ok=True)
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
                
                if not is_valid_preset_data(data):
                    failed_list.append(f"{file.filename} (不是有效的预设格式)")
                    continue
                
                # 保存文件
                safe_name = sanitize_filename(file.filename)
                save_path = os.path.join(target_dir, safe_name)
                
                # 防重名
                name_part, ext = os.path.splitext(safe_name)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(target_dir, f"{name_part}_{counter}{ext}")
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


@bp.route('/api/presets/category/move', methods=['POST'])
def move_preset_category():
    try:
        data = request.get_json(silent=True) or {}
        preset_id = data.get('id')
        source_type = str(data.get('source_type') or '').strip()
        target_category = _normalize_category_path(data.get('target_category'))
        if str(data.get('mode') or '').strip() == 'resource_only' and source_type != 'resource':
            return jsonify({"success": False, "msg": "该操作仅支持资源预设"})
        presets_root = _get_presets_path()

        if source_type == 'resource':
            file_path = str(data.get('file_path') or '').strip()
            if not _is_resource_preset_path(file_path):
                return jsonify({"success": False, "msg": "预设文件不存在"})
            if not _save_resource_category_override(file_path, target_category):
                return jsonify({"success": False, "msg": "保存分类覆盖失败"})
            return jsonify({"success": True, "msg": "已更新管理器分类，未移动实际文件"})

        file_path, _preset_type, _source_folder = _resolve_preset_file_path(preset_id, presets_root)
        if not file_path or not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "预设文件不存在"})

        target_dir = _safe_join_category_path(presets_root, target_category)
        if not target_dir:
            return jsonify({"success": False, "msg": "目标分类不合法"})
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, os.path.basename(file_path))
        if os.path.normcase(os.path.normpath(target_path)) != os.path.normcase(os.path.normpath(file_path)):
            if os.path.exists(target_path):
                return jsonify({"success": False, "msg": "目标位置已存在同名文件"})
            shutil.move(file_path, target_path)
        return jsonify({"success": True, "msg": "预设已移动", "path": target_path})
    except Exception as e:
        logger.error(f"Error moving preset category: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/category/reset', methods=['POST'])
def reset_preset_category():
    try:
        data = request.get_json(silent=True) or {}
        source_type = str(data.get('source_type') or '').strip()
        if source_type != 'resource':
            return jsonify({"success": False, "msg": "该操作仅支持资源预设"})
        file_path = str(data.get('file_path') or '').strip()
        if not _is_resource_preset_path(file_path):
            return jsonify({"success": False, "msg": "预设文件不存在"})
        if not _save_resource_category_override(file_path, ''):
            return jsonify({"success": False, "msg": "保存分类覆盖失败"})
        return jsonify({"success": True, "msg": "已恢复跟随角色卡分类"})
    except Exception as e:
        logger.error(f"Error resetting preset category: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/folders/create', methods=['POST'])
def create_preset_folder():
    try:
        data = request.get_json(silent=True) or {}
        presets_root = _get_presets_path()
        parent_category = _normalize_category_path(data.get('parent_category'))
        folder_name = _normalize_category_path(data.get('name'))
        if not folder_name or '/' in folder_name:
            return jsonify({"success": False, "msg": "目录名称不合法"})
        target_dir = _safe_join_category_path(presets_root, parent_category, folder_name)
        if not target_dir:
            return jsonify({"success": False, "msg": "目标分类不合法"})
        os.makedirs(target_dir, exist_ok=True)
        folder_meta = _build_global_folder_metadata(presets_root)
        return jsonify({"success": True, "msg": "目录已创建", **folder_meta})
    except Exception as e:
        logger.error(f"Error creating preset folder: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/folders/rename', methods=['POST'])
def rename_preset_folder():
    try:
        data = request.get_json(silent=True) or {}
        presets_root = _get_presets_path()
        category = _normalize_category_path(data.get('category'))
        new_name = _normalize_category_path(data.get('new_name'))
        if not category or not new_name or '/' in new_name:
            return jsonify({"success": False, "msg": "目录名称不合法"})
        source_dir = _safe_join_category_path(presets_root, category)
        target_dir = _safe_join_category_path(presets_root, _get_parent_category(category), new_name)
        if not source_dir or not os.path.isdir(source_dir):
            return jsonify({"success": False, "msg": "目录不存在"})
        os.rename(source_dir, target_dir)
        folder_meta = _build_global_folder_metadata(presets_root)
        return jsonify({"success": True, "msg": "目录已重命名", **folder_meta})
    except Exception as e:
        logger.error(f"Error renaming preset folder: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/folders/delete', methods=['POST'])
def delete_preset_folder():
    try:
        data = request.get_json(silent=True) or {}
        presets_root = _get_presets_path()
        category = _normalize_category_path(data.get('category'))
        target_dir = _safe_join_category_path(presets_root, category)
        if not target_dir or not os.path.isdir(target_dir):
            return jsonify({"success": False, "msg": "目录不存在"})
        if os.listdir(target_dir):
            return jsonify({"success": False, "msg": "只能删除空目录"})
        os.rmdir(target_dir)
        folder_meta = _build_global_folder_metadata(presets_root)
        return jsonify({"success": True, "msg": "目录已删除", **folder_meta})
    except Exception as e:
        logger.error(f"Error deleting preset folder: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/delete', methods=['POST'])
def delete_preset():
    """
    删除预设文件
    """
    try:
        data = request.get_json(silent=True) or {}
        preset_id = str(data.get('id') or '').strip()
        if not preset_id:
            return jsonify({"success": False, "msg": "缺少预设ID"})

        presets_root = _get_presets_path()
        file_path, _preset_type, _source_folder = _resolve_preset_file_path(preset_id, presets_root)
        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "预设文件不存在"})

        source_revision = str(data.get('source_revision') or '').strip() or build_file_source_revision(file_path)
        return _handle_preset_delete_via_save({'preset_id': preset_id, 'source_revision': source_revision})

    except PresetConflictError as exc:
        current_revision = str(exc) if str(exc) else ''
        return jsonify({
            'success': False,
            'msg': 'source_revision mismatch' if current_revision else 'source_revision required for overwrite',
            'current_source_revision': current_revision,
        }), 409
    except Exception as e:
        logger.error(f"Error deleting preset: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/version/set-default', methods=['POST'])
def set_default_preset_version():
    try:
        data = request.get_json(silent=True) or {}
        preset_id = str(data.get('preset_id') or '').strip()
        if not preset_id:
            return jsonify({'success': False, 'msg': '缺少预设ID'}), 400

        presets_root = _get_presets_path()
        file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)
        if not file_path:
            return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

        raw_data = load_preset_json(file_path)
        version_meta = extract_preset_version_meta(
            raw_data,
            fallback_name=raw_data.get('name', ''),
            fallback_filename=os.path.basename(file_path),
        )
        if not version_meta.get('is_versioned'):
            return jsonify({'success': False, 'msg': '当前预设不是版本化预设'}), 400

        suppress_fs_events(2.5)
        _rewrite_family_default_flags(
            file_path,
            preset_type=preset_type,
            source_folder=source_folder,
            presets_root=presets_root,
            target_default_path=file_path,
        )

        detail = _build_saved_preset_response(file_path, preset_type, source_folder, presets_root)
        family_info, current_version, available_versions = _build_family_context_for_detail(
            file_path,
            preset_type,
            source_folder,
            presets_root,
        )
        detail['family_info'] = family_info
        detail['current_version'] = current_version
        detail['available_versions'] = available_versions or []
        return jsonify({'success': True, 'preset': detail, 'preset_id': detail['id']})
    except Exception as e:
        logger.error(f'Error setting default preset version: {e}')
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/presets/version/merge', methods=['POST'])
def merge_preset_versions():
    try:
        data = request.get_json(silent=True) or {}
        target_preset_id = str(data.get('target_preset_id') or '').strip()
        source_preset_ids = [
            str(item or '').strip()
            for item in (data.get('source_preset_ids') or [])
            if str(item or '').strip()
        ]
        family_name = str(data.get('family_name') or '').strip()

        if not target_preset_id or not source_preset_ids:
            return jsonify({'success': False, 'msg': '缺少预设ID'}), 400

        source_preset_ids = _dedupe_preset_ids(source_preset_ids, exclude_id=target_preset_id)
        if not source_preset_ids:
            return jsonify({'success': False, 'msg': '缺少预设ID'}), 400

        presets_root = _get_presets_path()
        target_member = _load_preset_version_member(target_preset_id, presets_root)
        if not target_member:
            return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

        source_members = []
        for source_preset_id in source_preset_ids:
            source_member = _load_preset_version_member(source_preset_id, presets_root)
            if not source_member:
                return jsonify({'success': False, 'msg': '预设文件不存在'}), 404
            source_members.append(source_member)

        all_members = [target_member, *source_members]
        if any(member.get('preset_kind') != 'openai' for member in all_members):
            return jsonify({'success': False, 'msg': '仅支持 OpenAI/对话补全预设合并版本'}), 400

        target_scope = _scope_signature_for_member(target_member)
        if any(_scope_signature_for_member(member) != target_scope for member in source_members):
            return jsonify({'success': False, 'msg': '仅支持同一作用域内的预设合并版本'}), 400

        family_id = target_member.get('preset_version', {}).get('family_id') or generate_preset_family_id()
        planned = build_merge_version_plan(
            target_entry=_coerce_member_to_merge_entry(target_member, family_id=family_id),
            source_entries=[_coerce_member_to_merge_entry(member, family_id=family_id) for member in source_members],
            family_name=family_name or target_member.get('name') or '',
        )

        suppress_fs_events(2.5)
        _apply_version_plan_members(planned.get('members') or [], presets_root)
        detail = _build_family_detail_response(
            target_member['file_path'],
            target_member['preset_type'],
            target_member['source_folder'],
            presets_root,
            preset_kind_hint='openai',
        )
        return jsonify({'success': True, 'preset': detail, 'preset_id': detail['id']})
    except Exception as e:
        logger.error(f'Error merging preset versions: {e}')
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/presets/version/import', methods=['POST'])
def import_preset_version():
    try:
        preset_id = str(request.form.get('preset_id') or '').strip()
        upload = request.files.get('file')
        if not preset_id:
            return jsonify({'success': False, 'msg': '缺少预设ID'}), 400
        if upload is None or not str(upload.filename or '').strip():
            return jsonify({'success': False, 'msg': '未接收到文件'}), 400

        presets_root = _get_presets_path()
        target_member = _load_preset_version_member(preset_id, presets_root)
        if not target_member:
            return jsonify({'success': False, 'msg': '预设文件不存在'}), 404
        if target_member.get('preset_kind') != 'openai':
            return jsonify({'success': False, 'msg': '仅支持 OpenAI/对话补全预设导入版本'}), 400

        try:
            incoming_raw = json.loads(upload.read())
        except json.JSONDecodeError:
            return jsonify({'success': False, 'msg': 'JSON格式无效'}), 400

        if not isinstance(incoming_raw, dict):
            return jsonify({'success': False, 'msg': 'JSON格式无效'}), 400
        if not is_valid_preset_data(incoming_raw):
            return jsonify({'success': False, 'msg': '不是有效的预设格式'}), 400

        incoming_kind = _resolve_requested_preset_kind(
            '',
            incoming_raw,
            source_folder=target_member.get('source_folder'),
        )
        if incoming_kind != 'openai':
            return jsonify({'success': False, 'msg': '仅支持 OpenAI/对话补全预设导入版本'}), 400

        target_meta = target_member.get('preset_version') or {}
        family_id = target_meta.get('family_id') or generate_preset_family_id()
        family_name = target_meta.get('family_name') or target_member.get('name') or ''

        if not target_meta.get('is_versioned'):
            upgraded_target = upsert_preset_version_meta(
                target_member['raw_data'],
                family_id=family_id,
                family_name=family_name,
                version_label=target_meta.get('version_label') or os.path.splitext(target_member['filename'])[0],
                version_order=target_meta.get('version_order'),
                is_default_version=True,
            )
            suppress_fs_events(2.5)
            write_preset_json(target_member['file_path'], upgraded_target)

        existing_family_paths = _list_family_version_paths(
            target_member['file_path'],
            target_member['preset_type'],
            target_member['source_folder'],
            presets_root,
            family_id,
        )
        next_version_order = 20
        if existing_family_paths:
            next_version_order = max(
                extract_preset_version_meta(
                    load_preset_json(path),
                    fallback_name='',
                    fallback_filename=os.path.basename(path),
                ).get('version_order') or 100
                for path in existing_family_paths
            ) + 10

        upload_stem = os.path.splitext(str(upload.filename or '').strip())[0]
        imported_name = str(incoming_raw.get('name') or '').strip() or upload_stem
        final_content = merge_preset_content({}, 'openai', incoming_raw)
        if isinstance(final_content, dict):
            final_content['name'] = imported_name
        final_content = upsert_preset_version_meta(
            final_content,
            family_id=family_id,
            family_name=family_name,
            version_label=upload_stem,
            version_order=next_version_order,
            is_default_version=False,
        )

        target_dir = _resolve_existing_preset_target_dir(
            target_member['file_path'],
            target_member['preset_type'],
            target_member['source_folder'],
            presets_root,
        )
        import_path = ensure_unique_path(build_save_as_path(target_dir, upload_stem))
        suppress_fs_events(2.5)
        write_preset_json(import_path, final_content)

        import_source_folder = target_member['source_folder']
        if target_member['preset_type'] == 'resource' and import_source_folder:
            import_preset_id = f"resource::{import_source_folder}::{os.path.splitext(os.path.basename(import_path))[0]}"
        else:
            import_preset_id = _build_canonical_preset_id(
                import_path,
                target_member['preset_type'],
                import_source_folder,
                presets_root,
            )

        detail = _build_family_detail_response(
            import_path,
            target_member['preset_type'],
            import_source_folder,
            presets_root,
            preset_kind_hint='openai',
        )
        return jsonify({'success': True, 'preset': detail, 'preset_id': import_preset_id})
    except Exception as e:
        logger.error(f'Error importing preset version: {e}')
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/presets/export', methods=['POST'])
def export_preset():
    try:
        data = request.get_json(silent=True) or {}
        preset_id = data.get('id')
        presets_root = _get_presets_path()
        file_path, _preset_type, _source_folder = _resolve_preset_file_path(preset_id, presets_root)

        if not file_path:
            return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'msg': 'Preset not found'}), 404

        with open(file_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)

        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        buf = BytesIO(json_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/json; charset=utf-8',
            as_attachment=True,
            download_name=os.path.basename(file_path),
        )
    except Exception as e:
        logger.error(f"Error exporting preset: {e}")
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/presets/send_to_st', methods=['POST'])
def send_preset_to_st():
    try:
        data = request.get_json(silent=True) or {}
        requested_preset_id = str(data.get('id') or '').strip()
        preset_id = requested_preset_id
        presets_root = _get_presets_path()

        if requested_preset_id.startswith('global-alt::'):
            return jsonify({'success': False, 'msg': '仅管理器预设库中的预设支持发送到 ST'}), 400

        resolved_family_version_id = _resolve_family_default_version_id(requested_preset_id, presets_root)
        if resolved_family_version_id:
            preset_id = resolved_family_version_id

        if preset_id.startswith('global-alt::'):
            return jsonify({'success': False, 'msg': '仅管理器预设库中的预设支持发送到 ST'}), 400

        file_path, preset_type, source_folder = _resolve_preset_file_path(preset_id, presets_root)

        if not file_path:
            return jsonify({'success': False, 'msg': 'Invalid preset ID'}), 400

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'msg': '预设文件不存在'}), 404

        preset_data = load_preset_json(file_path)
        preset_kind = _resolve_requested_preset_kind(
            '',
            preset_data,
            source_folder=source_folder,
            file_path=file_path,
        )
        if preset_kind != 'openai':
            return jsonify({'success': False, 'msg': '仅 OpenAI/对话补全预设可发送到 ST'}), 400

        cfg = load_config()
        auth_type = str(cfg.get('st_auth_type') or 'basic').strip().lower()
        st_client = build_st_http_client(cfg, timeout=10)

        try:
            response = st_client.post(
                '/api/presets/save',
                json=_build_st_openai_preset_payload(preset_data, file_path),
                timeout=10,
            )
        except STAuthError as error:
            return jsonify({'success': False, 'msg': _format_st_auth_error(error)})

        if response.status_code != 200:
            return jsonify({'success': False, 'msg': _format_st_response_error(response, auth_type)})

        st_response = 'OK'
        if response.content:
            try:
                st_response = response.json()
            except (ValueError, TypeError):
                st_response = response.text or 'OK'
        ui_data = load_ui_data()
        ui_key = _build_preset_ui_key(preset_type, file_path, preset_id, presets_root)
        _, last_sent_to_st = set_last_sent_to_st(ui_data, ui_key, time.time())
        if not save_ui_data(ui_data):
            return jsonify({'success': False, 'msg': '保存发送时间失败'}), 500

        return jsonify({
            'success': True,
            'st_response': st_response,
            'last_sent_to_st': last_sent_to_st,
        })
    except Exception as e:
        logger.error('Send preset to ST error: %s', e)
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/presets/save', methods=['POST'])
def save_preset():
    """
    保存/更新预设文件
    """
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "msg": "缺少必要参数"})

        save_mode = str(data.get('save_mode') or '').strip()
        if save_mode:
            try:
                if save_mode == 'overwrite':
                    return _handle_preset_overwrite(data)
                if save_mode == 'save_as':
                    return _handle_preset_save_as(data)
                if save_mode == 'rename':
                    return _handle_preset_rename(data)
                if save_mode == 'delete':
                    return _handle_preset_delete_via_save(data)
                return jsonify({"success": False, "msg": "不支持的保存模式"}), 400
            except PresetConflictError as exc:
                current_revision = str(exc) if str(exc) else ''
                return jsonify({
                    'success': False,
                    'msg': 'source_revision mismatch' if current_revision else 'source_revision required for overwrite',
                    'current_source_revision': current_revision,
                }), 409

        return _save_preset_legacy(data)
        
    except Exception as e:
        logger.error(f"Error saving preset: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500


@bp.route('/api/presets/save-extensions', methods=['POST'])
def save_preset_extensions():
    """
    保存/更新预设的extensions（正则脚本和ST脚本）
    """
    try:
        data = request.json
        preset_id = data.get('id')
        extensions = data.get('extensions')
        
        if not preset_id or extensions is None:
            return jsonify({"success": False, "msg": "缺少必要参数"})
        
        presets_root = _get_presets_path()
        file_path, _preset_type, _source_folder = _resolve_preset_file_path(preset_id, presets_root)

        if not file_path:
            return jsonify({"success": False, "msg": "Invalid preset ID"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "预设文件不存在"})
        
        # 读取现有文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            preset_data = json.load(f)
        
        if not isinstance(extensions, dict):
            return jsonify({'success': False, 'msg': 'extensions 必须是对象'}), 400

        # Keep unrelated extension keys, but canonicalize managed data before saving.
        normalized_extensions = normalize_extensions_for_save(extensions)
        existing_extensions = preset_data.get('extensions')
        if not isinstance(existing_extensions, dict):
            existing_extensions = {}
            preset_data['extensions'] = existing_extensions

        regex_payload_present = any(
            key in extensions for key in REGEX_EXTENSION_KEYS
        ) or 'RegexBinding' in extensions
        if regex_payload_present:
            for key in REGEX_EXTENSION_KEYS - {'regex_scripts'}:
                existing_extensions.pop(key, None)
            existing_extensions.pop('RegexBinding', None)

        script_payload_present = any(key in extensions for key in TAVERN_HELPER_EXTENSION_KEYS)
        if script_payload_present:
            for key in TAVERN_HELPER_EXTENSION_KEYS - {'tavern_helper'}:
                existing_extensions.pop(key, None)

        for key, value in normalized_extensions.items():
            existing_extensions[key] = value

        # 写回文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(preset_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "msg": "扩展已保存"})
        
    except Exception as e:
        logger.error(f"Error saving preset extensions: {e}")
        return jsonify({"success": False, "msg": str(e)}), 500
