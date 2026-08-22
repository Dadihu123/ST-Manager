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
from core.data.ui_store import (
    get_last_sent_to_st,
    load_ui_data,
    save_ui_data,
    UI_DATA_FILE,
    get_resource_item_categories,
    set_last_sent_to_st,
    set_resource_item_categories,
    get_worldinfo_note,
    set_worldinfo_note,
    delete_worldinfo_note,
    rename_global_worldinfo_note_path_prefix,
)
from core.services.card_service import resolve_ui_key
from core.services.cache_service import invalidate_wi_list_cache
from core.services.index_build_service import (
    connect_index_db,
    refresh_worldinfo_category_stats,
    resolve_resource_worldinfo_owner_card_ids,
)
from core.services.index_job_worker import enqueue_index_job
from core.services.scan_service import suppress_fs_events
from core.services.st_auth import STAuthError, build_st_http_client
from core.services.worldinfo_index_query_service import query_worldinfo_index
from core.services.wi_entry_history_service import (
    ensure_entry_uids,
    collect_previous_versions,
    append_entry_history_records,
    list_entry_history_records,
    get_history_limit
)
from core.utils.filesystem import safe_move_to_trash
from core.utils.filesystem import sanitize_filename
from core.utils.source_revision import build_file_source_revision
from core.utils.world_info_sort import (
    normalize_world_info_sort_mode,
    sort_world_info_entries,
    sort_world_info_mapping,
)

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


def _safe_join_under_base(base_dir: str, rel_path: str) -> str:
    if not base_dir or not rel_path:
        return ''

    rel_value = str(rel_path).strip()
    if not rel_value or os.path.isabs(rel_value):
        return ''

    drive, _ = os.path.splitdrive(rel_value)
    if drive:
        return ''

    base_abs = os.path.abspath(base_dir)
    candidate = os.path.abspath(os.path.join(base_abs, rel_value.replace('/', os.sep)))
    try:
        if os.path.commonpath([candidate, base_abs]) != base_abs:
            return ''
    except Exception:
        return ''
    return candidate

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


def _build_export_worldbook_payload(book, fallback_name='World Info'):
    export_entries = {}
    entries_raw = []

    if isinstance(book, list):
        entries_raw = book
    elif isinstance(book, dict):
        entries = book.get('entries', [])
        if isinstance(entries, list):
            entries_raw = entries
        elif isinstance(entries, dict):
            entries_raw = []
            for entry_key, entry in entries.items():
                if (
                    isinstance(entry, dict)
                    and entry.get('uid') in (None, '')
                    and entry.get('st_source_id') in (None, '')
                    and entry.get('id') in (None, '')
                ):
                    entries_raw.append({**entry, 'uid': entry_key})
                else:
                    entries_raw.append(entry)

    used_uids = set()
    next_uid = 0

    def _allocate_uid():
        nonlocal next_uid
        while str(next_uid) in used_uids:
            next_uid += 1
        uid = next_uid
        used_uids.add(str(uid))
        next_uid += 1
        return uid

    for idx, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            continue

        final_entry = entry.copy()
        uid = entry.get('uid')
        if uid is None or uid == '':
            uid = entry.get('st_source_id')
        if uid is None or uid == '':
            uid = entry.get('id', idx)
        if str(uid) in used_uids:
            uid = _allocate_uid()
        else:
            used_uids.add(str(uid))

        display_index = entry.get('displayIndex')
        if display_index is None:
            extensions = entry.get('extensions')
            if isinstance(extensions, dict):
                display_index = extensions.get('display_index')
        if display_index is None:
            display_index = idx

        final_entry['uid'] = uid
        final_entry['displayIndex'] = display_index

        if 'keys' in entry:
            final_entry['key'] = entry['keys']
        if 'key' not in final_entry:
            final_entry['key'] = []

        if 'secondary_keys' in entry:
            final_entry['keysecondary'] = entry['secondary_keys']
        if 'keysecondary' not in final_entry:
            final_entry['keysecondary'] = []

        is_enabled = entry.get('enabled', not entry.get('disable', False))
        final_entry['disable'] = not is_enabled

        if 'insertion_order' in entry:
            final_entry['order'] = entry['insertion_order']

        final_entry.pop('enabled', None)
        final_entry.pop('keys', None)
        final_entry.pop('secondary_keys', None)
        final_entry.pop('insertion_order', None)

        export_entries[str(uid)] = final_entry

    final_export = {
        'entries': export_entries,
        'name': book.get('name', fallback_name) if isinstance(book, dict) else fallback_name,
    }

    if isinstance(book, dict):
        for key, value in book.items():
            if key not in ['entries', 'name']:
                final_export[key] = value

    return final_export


def _serialize_worldbook_json_bytes(book, fallback_name='World Info') -> bytes:
    payload = _build_export_worldbook_payload(book, fallback_name=fallback_name)
    return json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')


def _build_send_worldbook_json_bytes(book, raw_bytes: bytes) -> bytes:
    if isinstance(book, list):
        return _serialize_worldbook_json_bytes(book)
    return raw_bytes

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
    if not rel_norm:
        return ''
    if '/' not in rel_norm:
        return ''
    return _normalize_category_path(rel_norm.rsplit('/', 1)[0])


def _normalize_resource_item_key(path: str) -> str:
    if not path:
        return ''
    try:
        return os.path.normcase(os.path.normpath(str(path))).replace('\\', '/')
    except Exception:
        return ''


def _build_worldinfo_note_kwargs(source_type: str, file_path: str = '', card_id: str = '') -> dict:
    normalized_source = str(source_type or '').strip().lower()
    if normalized_source == 'embedded':
        return {'card_id': card_id}
    return {'file_path': file_path}


def _format_st_auth_error(error):
    if error.stage == 'basic_auth':
        status = error.status_code or 401
        return f'ST Basic/Auth 认证失败 ({status}): 请检查 Basic/Auth 用户名和密码。'
    if error.stage == 'web_login':
        status = error.status_code or 401
        return f'ST Web 登录失败 ({status}): 请检查 Web 用户名和密码。'
    if error.stage == 'connection':
        return error.message

    status = f' ({error.status_code})' if error.status_code else ''
    return f'ST 连接失败{status}: {error.message}'


def _format_st_response_error(response, auth_type):
    if response.status_code == 400:
        return f'ST 请求错误 (400): {response.text}'

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

    return f'ST Error: {response.status_code} - {response.text}'


def _get_worldinfo_ui_key(source_type: str, file_path: str, cfg: dict) -> str:
    normalized_source = str(source_type or '').strip().lower()
    normalized_path = os.path.normpath(str(file_path or ''))

    if normalized_source == 'global':
        rel_path = os.path.relpath(normalized_path, _resolve_wi_dir(cfg)).replace('\\', '/')
        return f'global::{rel_path}'

    if normalized_source == 'resource':
        rel_path = os.path.relpath(normalized_path, _resolve_resources_dir(cfg)).replace('\\', '/')
        return f'resource::{rel_path}'

    return ''


def _get_worldinfo_last_sent_to_st(ui_data: dict, source_type: str, file_path: str, cfg: dict) -> float:
    ui_key = _get_worldinfo_ui_key(source_type, file_path, cfg)
    return get_last_sent_to_st(ui_data, ui_key) if ui_key else 0.0


def _is_sendable_worldinfo_payload(data) -> bool:
    if isinstance(data, list):
        return True
    if not isinstance(data, dict):
        return False

    entries = data.get('entries')
    return isinstance(entries, (list, dict))


class _MultipartUploadBuffer(BytesIO):
    def read(self, size=-1):
        chunk = super().read(size)
        return _NormalizedDecodedBytes(chunk)


class _NormalizedDecodedBytes(bytes):
    def decode(self, encoding='utf-8', errors='strict'):
        text = super().decode(encoding, errors)
        return text.replace('\r\n', '\n').replace('\r', '\n')


def _get_worldinfo_ui_summary(ui_data: dict, source_type: str, file_path: str = '', card_id: str = '') -> str:
    note = get_worldinfo_note(ui_data, source_type, **_build_worldinfo_note_kwargs(source_type, file_path=file_path, card_id=card_id))
    return note.get('summary', '') if isinstance(note, dict) else ''


def _get_embedded_worldinfo_ui_summary(ui_data: dict, card_id: str = '') -> str:
    try:
        ui_key = resolve_ui_key(card_id)
    except Exception:
        ui_key = card_id
    card_summary = ''
    if ui_key and isinstance(ui_data, dict):
        card_meta = ui_data.get(ui_key)
        if isinstance(card_meta, dict):
            card_summary = str(card_meta.get('summary') or '')

    if card_summary.strip():
        return card_summary

    return _get_worldinfo_ui_summary(ui_data, 'embedded', card_id=card_id)


def _worldinfo_owner_card_id(item: dict) -> str:
    owner_entity_id = str(item.get('owner_entity_id') or '')
    if owner_entity_id.startswith('card::'):
        return owner_entity_id[6:]

    item_id = str(item.get('id') or '')
    if item.get('type') == 'embedded' and item_id.startswith('world::embedded::'):
        return item_id[len('world::embedded::'):]

    parts = item_id.split('::')
    if item.get('type') == 'resource' and len(parts) >= 4:
        return parts[2]

    return ''


def _legacy_worldinfo_id(item: dict) -> str:
    item_id = str(item.get('id') or '')
    item_type = str(item.get('type') or '')

    if item_type == 'global' and item_id.startswith('world::global::'):
        return 'global::' + item_id[len('world::global::'):]

    if item_type == 'resource' and item_id.startswith('world::resource::'):
        return 'resource::' + item_id[len('world::resource::'):]

    if item_type == 'embedded' and item_id.startswith('world::embedded::'):
        return 'embedded::' + item_id[len('world::embedded::'):]

    return item_id


def _infer_worldinfo_name_source(name: str, file_name: str, source_type: str = '', path: str = '') -> str:
    if str(name or '').strip() != str(file_name or '').strip():
        return 'meta'

    normalized_type = str(source_type or '').strip().lower()
    if normalized_type not in ('global', 'resource') or not path:
        return 'meta'

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        if isinstance(data, dict) and str(data.get('name') or '').strip():
            return 'meta'
        return 'filename'
    except Exception:
        return 'meta'


def _enrich_indexed_worldinfo_item(item: dict, card_map: dict, ui_data: dict, cfg: dict) -> dict:
    enriched = dict(item)
    enriched['id'] = _legacy_worldinfo_id(enriched)
    file_name = str(enriched.get('filename') or '')
    owner_card_id = _worldinfo_owner_card_id(enriched)
    owner_card = card_map.get(owner_card_id) or {}
    owner_card_name = str(owner_card.get('char_name') or '')
    owner_card_category = _normalize_category_path(owner_card.get('category', ''))
    item_type = str(enriched.get('type') or '')

    enriched['file_name'] = file_name
    enriched['name_source'] = _infer_worldinfo_name_source(
        enriched.get('name', ''),
        file_name,
        item_type,
        str(enriched.get('path') or ''),
    )
    enriched['category_override'] = enriched.get('display_category', '') if enriched.get('category_mode') == 'override' else ''
    enriched['owner_card_id'] = owner_card_id
    enriched['owner_card_name'] = owner_card_name
    enriched['owner_card_category'] = owner_card_category

    if item_type == 'global':
        enriched['card_id'] = ''
        enriched['card_name'] = ''
        enriched['ui_summary'] = _get_worldinfo_ui_summary(ui_data, 'global', file_path=str(enriched.get('path') or ''))
        enriched['last_sent_to_st'] = _get_worldinfo_last_sent_to_st(
            ui_data,
            'global',
            str(enriched.get('path') or ''),
            cfg,
        )
    elif item_type == 'resource':
        enriched['card_id'] = owner_card_id
        enriched['card_name'] = owner_card_name
        enriched['ui_summary'] = _get_worldinfo_ui_summary(ui_data, 'resource', file_path=str(enriched.get('path') or ''))
        enriched['last_sent_to_st'] = _get_worldinfo_last_sent_to_st(
            ui_data,
            'resource',
            str(enriched.get('path') or ''),
            cfg,
        )
    else:
        enriched['card_id'] = owner_card_id
        enriched['card_name'] = owner_card_name
        enriched['ui_summary'] = _get_embedded_worldinfo_ui_summary(ui_data, card_id=owner_card_id)
        enriched['last_sent_to_st'] = 0.0

    return enriched


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


def _save_resource_category_override(mode: str, file_path: str, category: str) -> bool:
    ui_data = load_ui_data()
    payload = get_resource_item_categories(ui_data)
    mode_items = dict(payload.get(mode) or {})
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
        'presets': dict(payload.get('presets') or {}),
    }
    next_payload[mode] = mode_items
    set_resource_item_categories(ui_data, next_payload)
    return save_ui_data(ui_data)


def _is_resource_worldinfo_path(file_path: str, cfg: dict) -> bool:
    if not file_path or not _is_valid_wi_file(file_path, cfg):
        return False
    resources_dir = _resolve_resources_dir(cfg)
    if not _is_under_base(file_path, resources_dir):
        return False
    rel_path = os.path.relpath(file_path, resources_dir).replace('\\', '/')
    return '/lorebooks/' in f'/{rel_path}/'


def _enqueue_worldinfo_note_refresh(source_type: str, file_path: str = '', card_id: str = ''):
    normalized_source = str(source_type or '').strip().lower()
    if normalized_source == 'global' and file_path:
        enqueue_index_job('upsert_worldinfo_path', source_path=file_path)
        return

    if normalized_source == 'resource' and file_path:
        for owner_card_id in resolve_resource_worldinfo_owner_card_ids(file_path):
            enqueue_index_job('upsert_world_owner', entity_id=owner_card_id, source_path=file_path)
        return

    if normalized_source == 'embedded' and card_id:
        enqueue_index_job('upsert_world_embedded', entity_id=card_id, source_path='')


def _enqueue_worldinfo_file_refresh(file_path: str, cfg: dict):
    if not file_path or not _is_valid_wi_file(file_path, cfg):
        return

    if _is_resource_worldinfo_path(file_path, cfg):
        _enqueue_resource_worldinfo_owner_refresh(file_path)
        return

    enqueue_index_job('upsert_worldinfo_path', source_path=file_path)


def _enqueue_resource_worldinfo_owner_refresh(file_path: str):
    for owner_card_id in resolve_resource_worldinfo_owner_card_ids(file_path):
        enqueue_index_job('upsert_world_owner', entity_id=owner_card_id, source_path=file_path)


def _move_global_worldinfo_file(file_path: str, target_category: str, cfg: dict) -> str:
    global_dir = _resolve_wi_dir(cfg)
    if not _is_under_base(file_path, global_dir):
        raise ValueError('非法路径')

    filename = os.path.basename(file_path)
    target_dir = _safe_join_category_path(global_dir, target_category)
    if not target_dir:
        raise ValueError('目标分类不合法')

    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, filename)
    if os.path.normcase(os.path.normpath(target_path)) == os.path.normcase(os.path.normpath(file_path)):
        return file_path

    if os.path.exists(target_path):
        raise ValueError('目标位置已存在同名文件')

    shutil.move(file_path, target_path)
    return target_path


def _remap_global_worldinfo_note_path(old_path: str, new_path: str):
    if not old_path or not new_path:
        return False

    ui_data = load_ui_data()
    changed = rename_global_worldinfo_note_path_prefix(ui_data, old_path, new_path)
    if not changed:
        return False
    if not save_ui_data(ui_data):
        raise ValueError('保存世界书备注失败')
    return True


def _folder_response(base_dir: str, success_msg: str, warning: str = ''):
    items = []
    for root, _dirs, files in os.walk(base_dir):
        for name in files:
            if not name.lower().endswith('.json'):
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, base_dir).replace('\\', '/')
            physical_category = _get_parent_category(rel_path)
            items.append({'type': 'global', 'display_category': physical_category, 'physical_category': physical_category})
    folder_meta = _add_physical_folder_nodes(_build_folder_metadata(items), base_dir)
    response = {
        'success': True,
        'msg': success_msg,
        'all_folders': folder_meta['all_folders'],
        'category_counts': folder_meta['category_counts'],
        'folder_capabilities': folder_meta['folder_capabilities'],
    }
    if warning:
        response['warning'] = warning
    return jsonify(response)


def _refresh_worldinfo_folder_stats(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    if not bool(cfg.get('worldinfo_list_use_index', False)):
        return ''

    try:
        with connect_index_db(DEFAULT_DB_PATH) as conn:
            refresh_worldinfo_category_stats(conn, cfg)
        return ''
    except Exception as exc:
        logger.warning('Refresh worldinfo folder stats failed: %s', exc)
        return f'索引分类统计刷新失败: {exc}'


def _build_card_category_sig(cards) -> tuple:
    pairs = []
    for card in cards or []:
        card_id = str((card or {}).get('id') or '')
        category = _normalize_category_path((card or {}).get('category', ''))
        pairs.append((card_id, category))
    pairs.sort()
    return tuple(pairs)


def _build_dir_tree_sig(base_dir: str) -> tuple:
    if not base_dir:
        return ()
    try:
        norm_base = os.path.normpath(base_dir)
        if not os.path.exists(norm_base):
            return ()

        entries = []
        for root, dirs, files in os.walk(norm_base):
            rel_root = os.path.relpath(root, norm_base).replace('\\', '/')
            if rel_root == '.':
                rel_root = ''

            try:
                dir_names = sorted(dirs)
            except Exception:
                dir_names = []
            entries.append(('dir', rel_root, tuple(dir_names), _safe_mtime(root)))

            for name in sorted(files):
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, norm_base).replace('\\', '/')
                entries.append(('file', rel_path, _safe_mtime(full_path)))

        return tuple(entries)
    except Exception:
        return ()


def _select_preferred_resource_target(existing: dict, candidate: dict) -> dict:
    if not existing:
        return candidate
    existing_card = existing.get('card') or {}
    candidate_card = candidate.get('card') or {}
    existing_key = (
        str(existing_card.get('id') or ''),
        str(existing_card.get('char_name') or ''),
    )
    candidate_key = (
        str(candidate_card.get('id') or ''),
        str(candidate_card.get('char_name') or ''),
    )
    return candidate if candidate_key < existing_key else existing


def _apply_world_info_preview(
    data,
    cfg: dict,
    preview_limit=None,
    force_full: bool = False,
    sort_mode='priority',
) -> dict:
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

    normalized_sort_mode = normalize_world_info_sort_mode(sort_mode)

    def _slice_entries(raw, limit):
        if isinstance(raw, list):
            return sort_world_info_entries(raw, normalized_sort_mode)[:limit]
        if isinstance(raw, dict):
            entries = raw.get('entries')
            if isinstance(entries, list):
                new_data = dict(raw)
                new_data['entries'] = sort_world_info_entries(
                    entries,
                    normalized_sort_mode,
                )[:limit]
                return new_data
            if isinstance(entries, dict):
                ordered_items = sort_world_info_mapping(entries, normalized_sort_mode)
                trimmed = dict(ordered_items[:limit])
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
    return resp

# === 工具函数 ===
from core.utils.image import extract_card_info # 用于 export logic

logger = logging.getLogger(__name__)
WI_LIST_CACHE_VERSION = 3

bp = Blueprint('wi', __name__)

@bp.route('/api/world_info/list', methods=['GET'])
def api_list_world_infos():
    try:
        search = request.args.get('search', '').strip()
        category = _normalize_category_path(request.args.get('category', ''))
        wi_type = request.args.get('type', 'all') # all, global, resource, embedded
        search_mode = request.args.get('search_mode', 'fast').strip().lower()
        if search_mode not in ('fast', 'fulltext'):
            search_mode = 'fast'

        # 新增分页参数
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
        except:
            page, page_size = 1, 20

        # === 动态获取配置中的路径，而不是使用全局静态变量 ===
        cfg = load_config()
        if bool(cfg.get('worldinfo_list_use_index', False)):
            ui_data = load_ui_data()
            if not ctx.cache.initialized:
                ctx.cache.reload_from_db()
            card_map = {str(card.get('id') or ''): card for card in getattr(ctx.cache, 'cards', []) or []}
            extra_source_paths = []
            extra_owner_entity_ids = []
            if search:
                search_lc = search.lower()
                notes = (ui_data.get('_worldinfo_notes_v1') or {}) if isinstance(ui_data, dict) else {}
                for note_key, note_value in notes.items():
                    summary = str((note_value or {}).get('summary') or '').lower() if isinstance(note_value, dict) else ''
                    if search_lc not in summary:
                        continue
                    note_key_str = str(note_key or '')
                    if note_key_str.startswith('resource::') or note_key_str.startswith('global::'):
                        extra_source_paths.append(note_key_str.split('::', 1)[1])
                    elif note_key_str.startswith('embedded::'):
                        extra_owner_entity_ids.append(f"card::{note_key_str.split('::', 1)[1]}")

                for card_id, card in card_map.items():
                    if search_lc in str(card.get('char_name') or '').lower():
                        extra_owner_entity_ids.append(f'card::{card_id}')

            query_filters = {
                'type': wi_type,
                'category': category,
                'search': search,
                'search_mode': search_mode,
                'page': page,
                'page_size': page_size,
                'db_path': DEFAULT_DB_PATH,
                'paginate': True,
            }
            if extra_source_paths:
                query_filters['source_paths'] = sorted(set(extra_source_paths))
            if extra_owner_entity_ids:
                query_filters['owner_entity_ids'] = sorted(set(extra_owner_entity_ids))

            indexed_source = query_worldinfo_index(query_filters)
            if indexed_source.get('index_ready', True):
                items = [
                    _enrich_indexed_worldinfo_item(item, card_map, ui_data, cfg)
                    for item in indexed_source['items']
                ]
                return jsonify({
                    'success': True,
                    'items': items,
                    'total': int(indexed_source.get('total') or 0),
                    'page': page,
                    'page_size': page_size,
                    'all_folders': indexed_source.get('all_folders') or [],
                    'category_counts': indexed_source.get('category_counts') or {},
                    'folder_capabilities': indexed_source.get('folder_capabilities') or {},
                })

        current_wi_folder = _resolve_wi_dir(cfg)
        resources_root = _resolve_resources_dir(cfg)
        if not os.path.exists(current_wi_folder):
            try: os.makedirs(current_wi_folder, exist_ok=True)
            except: pass

        # ===== [CACHE] key = type + category + search（未分页 items）=====
        cache_key = f"{wi_type}||{category}||{search_mode}||{search.lower()}"

        cfg = load_config()
        default_res_dir = _resolve_resources_dir(cfg)
        db_path = DEFAULT_DB_PATH
        cards_dir_sig = _safe_mtime(str(CARDS_FOLDER))

        global_dir_sig   = _build_dir_tree_sig(current_wi_folder)
        resource_dir_sig = _build_dir_tree_sig(default_res_dir)
        ui_data_sig      = _safe_mtime(UI_DATA_FILE)
        db_sig           = _safe_mtime(db_path)

        cached_items = None
        with ctx.wi_list_cache_lock:
            card_category_sig = _build_card_category_sig(getattr(ctx.cache, 'cards', []))

        if wi_type == 'global':
            sig = ('global', WI_LIST_CACHE_VERSION, global_dir_sig, ui_data_sig, db_sig, cards_dir_sig, card_category_sig)
        elif wi_type == 'resource':
            sig = ('resource', WI_LIST_CACHE_VERSION, resource_dir_sig, ui_data_sig, card_category_sig)
        elif wi_type == 'embedded':
            sig = ('embedded', WI_LIST_CACHE_VERSION, ui_data_sig, db_sig, cards_dir_sig, card_category_sig)
        else:  # all
            sig = ('all', WI_LIST_CACHE_VERSION, global_dir_sig, resource_dir_sig, ui_data_sig, db_sig, cards_dir_sig, card_category_sig)

        with ctx.wi_list_cache_lock:
            cached = ctx.wi_list_cache.get(cache_key)
            if cached and cached.get("sig") == sig:
                items = cached.get("items") or []
                folder_meta = cached.get('folder_meta') or _build_folder_metadata(items)
                # === 命中缓存直接分页返回，不再往下扫描 ===
                total_count = len(items)
                start = (page - 1) * page_size
                end = start + page_size
                return jsonify({
                    "success": True,
                    "items": items[start:end],
                    "total": total_count,
                    "page": page,
                    "page_size": page_size,
                    "all_folders": folder_meta['all_folders'],
                    "category_counts": folder_meta['category_counts'],
                    "folder_capabilities": folder_meta['folder_capabilities'],
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
        resource_target_map = {}
        resource_lore_dirs = set()
        res_root_dir = None
        ui_data = load_ui_data()
        resource_item_categories = get_resource_item_categories(ui_data).get('worldinfo', {})
        if wi_type in ['all', 'resource', 'global']:
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
                target_info = {
                    "key": key,
                    "card": card,
                    "lore_dir": lore_dir
                }
                resource_target_map[lore_dir] = _select_preferred_resource_target(resource_target_map.get(lore_dir), target_info)

            resource_targets = [resource_target_map[path] for path in sorted(resource_target_map.keys())]

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

        card_map = {str(card.get('id') or ''): card for card in getattr(ctx.cache, 'cards', []) or []}

        # 1. 全局目录 (Global)
        if wi_type in ['all', 'global']:
            global_count_before = len(items)
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
                                    
                                rel_path = os.path.relpath(full_path, current_wi_folder).replace('\\', '/')
                                physical_category = _get_parent_category(rel_path)
                                items.append({
                                    "id": f"global::{rel_path}",
                                    "type": "global",
                                    "source_type": "global",
                                    "name": name,
                                    "name_source": name_source,
                                    "file_name": file_name,
                                    "path": full_path,
                                    "mtime": os.path.getmtime(full_path),
                                    "display_category": physical_category,
                                    "physical_category": physical_category,
                                    "category_mode": "physical",
                                    "category_override": "",
                                    "owner_card_id": "",
                                    "owner_card_name": "",
                                    "owner_card_category": "",
                                    "ui_summary": _get_worldinfo_ui_summary(ui_data, 'global', file_path=full_path),
                                    "last_sent_to_st": _get_worldinfo_last_sent_to_st(ui_data, 'global', full_path, cfg),
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
            resource_count_before = len(items)
            
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
                                    path_key = _normalize_resource_item_key(full_path)
                                    override_info = resource_item_categories.get(path_key) or {}
                                    override_category = _normalize_category_path(override_info.get('category'))
                                    owner_category = _normalize_category_path(card.get('category', ''))
                                    display_category = override_category or owner_category
                                    items.append({
                                        "id": f"resource::{key}::{f}",
                                        "type": "resource",
                                        "source_type": "resource",
                                        "name": name,
                                        "name_source": name_source,
                                        "file_name": file_name,
                                        "path": full_path,
                                        "card_name": card.get('char_name', ''), # 关联的角色名
                                        "card_id": card.get('id', ''), # 用于跳转
                                        "mtime": os.path.getmtime(full_path),
                                        "display_category": display_category,
                                        "physical_category": _get_parent_category(os.path.relpath(full_path, lore_dir).replace('\\', '/')),
                                        "category_mode": "override" if override_category else "inherited",
                                        "category_override": override_category,
                                        "owner_card_id": card.get('id', ''),
                                        "owner_card_name": card.get('char_name', ''),
                                        "owner_card_category": owner_category,
                                        "ui_summary": _get_worldinfo_ui_summary(ui_data, 'resource', file_path=full_path),
                                        "last_sent_to_st": _get_worldinfo_last_sent_to_st(ui_data, 'resource', full_path, cfg),
                                    })
                            except: continue
        # 3. 角色卡内嵌 (Embedded) - 查询数据库
        if wi_type in ['all', 'embedded']:
            conn = get_db()
            cursor = conn.execute("SELECT id, char_name, character_book_name, last_modified FROM card_metadata WHERE has_character_book = 1")
            rows = cursor.fetchall()
            for row in rows:
                card = card_map.get(str(row['id']) or '') or {}
                owner_category = _normalize_category_path(card.get('category', ''))
                items.append({
                    "id": f"embedded::{row['id']}",
                    "type": "embedded",
                    "source_type": "embedded",
                    "name": row['character_book_name'] or f"{row['char_name']}'s WI",
                    "card_name": row['char_name'],
                    "card_id": row['id'],
                    "mtime": row['last_modified'],
                    "display_category": owner_category,
                    "physical_category": '',
                    "category_mode": 'inherited',
                    "category_override": '',
                    "owner_card_id": row['id'],
                    "owner_card_name": row['char_name'],
                    "owner_card_category": owner_category,
                    "ui_summary": _get_embedded_worldinfo_ui_summary(ui_data, card_id=row['id']),
                    "last_sent_to_st": 0.0,
                })

        source_items = list(items)

        # 过滤与排序
        if category:
            items = [i for i in items if _is_in_category_subtree(i.get('display_category', ''), category)]

        if search:
            items = [
                i for i in items if (
                    search in i['name'].lower()
                    or (i.get('card_name') and search in i['card_name'].lower())
                    or search in str(i.get('ui_summary', '')).lower()
                )
            ]
            
        items.sort(key=lambda x: x.get('mtime', 0), reverse=True)
        folder_meta = _add_physical_folder_nodes(_build_folder_metadata(source_items), current_wi_folder)

        # ===== [CACHE WRITE] 只在未命中缓存时写入 =====
        if cached_items is None:
            with ctx.wi_list_cache_lock:
                # 简单上限，避免 key 太多（比如用户疯狂换 search）
                if len(ctx.wi_list_cache) > 200:
                    ctx.wi_list_cache.clear()
                ctx.wi_list_cache[cache_key] = {
                    "sig": sig,
                    "items": items,
                    "folder_meta": folder_meta,
                    "ts": time.time(),
                }

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
            "page_size": page_size,
            "all_folders": folder_meta['all_folders'],
            "category_counts": folder_meta['category_counts'],
            "folder_capabilities": folder_meta['folder_capabilities'],
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
        target_category = _normalize_category_path(req.get('target_category'))
        target_dir = _safe_join_category_path(_resolve_wi_dir(cfg), target_category)
        if not target_dir:
            return jsonify({"success": False, "msg": "目标分类不合法"})
        os.makedirs(target_dir, exist_ok=True)

        final_path = os.path.join(target_dir, f"{safe_name}.json")
        base, ext = os.path.splitext(final_path)
        idx = 1
        while os.path.exists(final_path):
            final_path = f"{base}_{idx}{ext}"
            idx += 1

        suppress_fs_events(2.0)
        payload = _build_st_compatible_worldbook_payload(raw_name)
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

        invalidate_wi_list_cache()
        _enqueue_worldinfo_file_refresh(final_path, load_config())

        rel = os.path.relpath(final_path, _resolve_wi_dir(cfg)).replace('\\', '/')
        file_name = os.path.basename(final_path)
        item = {
            "id": f"global::{rel}",
            "type": "global",
            "name": payload.get('name') or os.path.splitext(file_name)[0],
            "name_source": "meta",
            "file_name": file_name,
            "path": final_path.replace('\\', '/'),
            "mtime": os.path.getmtime(final_path)
        }
        return jsonify({
            "success": True,
            "msg": "世界书已创建",
            "path": final_path.replace('\\', '/'),
            "item": item
        })
    except Exception as e:
        logger.error(f"Create WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/world_info/category/move', methods=['POST'])
def api_move_world_info_category():
    try:
        req = request.get_json(silent=True) or {}
        source_type = str(req.get('source_type') or '').strip()
        file_path = str(req.get('file_path') or '').strip()
        target_category = _normalize_category_path(req.get('target_category'))
        if str(req.get('mode') or '').strip() == 'resource_only' and source_type != 'resource':
            return jsonify({'success': False, 'msg': '该操作仅支持资源世界书'})
        cfg = load_config()

        if source_type == 'embedded':
            return jsonify({'success': False, 'msg': '内嵌世界书跟随角色卡分类，如需调整请移动所属角色卡'})

        if source_type == 'resource':
            if not _is_resource_worldinfo_path(file_path, cfg):
                return jsonify({'success': False, 'msg': '非法路径'})
            if not _save_resource_category_override('worldinfo', file_path, target_category):
                return jsonify({'success': False, 'msg': '保存分类覆盖失败'})
            invalidate_wi_list_cache()
            _enqueue_resource_worldinfo_owner_refresh(file_path)
            return jsonify({'success': True, 'msg': '已更新管理器分类，未移动实际文件'})

        if source_type != 'global' or not file_path:
            return jsonify({'success': False, 'msg': '缺少必要参数'})

        suppress_fs_events(3.0)
        old_path = file_path
        new_path = _move_global_worldinfo_file(file_path, target_category, cfg)
        try:
            _remap_global_worldinfo_note_path(old_path, new_path)
        except ValueError:
            if os.path.exists(new_path) and not os.path.exists(old_path):
                shutil.move(new_path, old_path)
            raise
        invalidate_wi_list_cache()
        cfg = load_config()
        _enqueue_worldinfo_file_refresh(old_path, cfg)
        _enqueue_worldinfo_file_refresh(new_path, cfg)
        return jsonify({'success': True, 'msg': '世界书已移动', 'path': new_path})
    except ValueError as e:
        return jsonify({'success': False, 'msg': str(e)})
    except Exception as e:
        logger.error(f'Move WI category error: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/world_info/category/reset', methods=['POST'])
def api_reset_world_info_category():
    try:
        req = request.get_json(silent=True) or {}
        source_type = str(req.get('source_type') or '').strip()
        if source_type != 'resource':
            return jsonify({'success': False, 'msg': '该操作仅支持资源世界书'})
        file_path = str(req.get('file_path') or '').strip()
        cfg = load_config()
        if not _is_resource_worldinfo_path(file_path, cfg):
            return jsonify({'success': False, 'msg': '非法路径'})
        if not _save_resource_category_override('worldinfo', file_path, ''):
            return jsonify({'success': False, 'msg': '保存分类覆盖失败'})
        invalidate_wi_list_cache()
        _enqueue_resource_worldinfo_owner_refresh(file_path)
        return jsonify({'success': True, 'msg': '已恢复跟随角色卡分类'})
    except Exception as e:
        logger.error(f'Reset WI category error: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/world_info/folders/create', methods=['POST'])
def api_create_world_info_folder():
    try:
        req = request.get_json(silent=True) or {}
        cfg = load_config()
        global_dir = _resolve_wi_dir(cfg)
        parent_category = _normalize_category_path(req.get('parent_category'))
        folder_name = _normalize_category_path(req.get('name'))
        if not folder_name or '/' in folder_name:
            return jsonify({'success': False, 'msg': '目录名称不合法'})
        target_dir = _safe_join_category_path(global_dir, parent_category, folder_name)
        if not target_dir:
            return jsonify({'success': False, 'msg': '目标分类不合法'})
        suppress_fs_events(1.5)
        os.makedirs(target_dir, exist_ok=True)
        invalidate_wi_list_cache()
        warning = _refresh_worldinfo_folder_stats(cfg)
        return _folder_response(global_dir, '目录已创建', warning=warning)
    except Exception as e:
        logger.error(f'Create WI folder error: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/world_info/folders/rename', methods=['POST'])
def api_rename_world_info_folder():
    try:
        req = request.get_json(silent=True) or {}
        cfg = load_config()
        global_dir = _resolve_wi_dir(cfg)
        category = _normalize_category_path(req.get('category'))
        new_name = _normalize_category_path(req.get('new_name'))
        if not category or not new_name or '/' in new_name:
            return jsonify({'success': False, 'msg': '目录名称不合法'})
        source_dir = _safe_join_category_path(global_dir, category)
        parent_category = _get_parent_category(category)
        target_dir = _safe_join_category_path(global_dir, parent_category, new_name)
        if not source_dir or not target_dir or not os.path.isdir(source_dir):
            return jsonify({'success': False, 'msg': '目录不存在'})
        suppress_fs_events(3.0)
        moved_global_files = []
        for root, _dirs, files in os.walk(source_dir):
            for name in files:
                if not name.lower().endswith('.json'):
                    continue
                old_file_path = os.path.join(root, name)
                rel_file_path = os.path.relpath(old_file_path, source_dir)
                moved_global_files.append((old_file_path, os.path.join(target_dir, rel_file_path)))
        old_prefix = os.path.normcase(os.path.normpath(source_dir)).replace('\\', '/')
        os.rename(source_dir, target_dir)
        new_prefix = os.path.normcase(os.path.normpath(target_dir)).replace('\\', '/')
        try:
            _remap_global_worldinfo_note_path(old_prefix, new_prefix)
        except ValueError:
            if os.path.exists(target_dir) and not os.path.exists(source_dir):
                os.rename(target_dir, source_dir)
            raise
        invalidate_wi_list_cache()
        for old_file_path, new_file_path in moved_global_files:
            _enqueue_worldinfo_file_refresh(old_file_path, cfg)
            _enqueue_worldinfo_file_refresh(new_file_path, cfg)
        warning = _refresh_worldinfo_folder_stats(cfg)
        return _folder_response(global_dir, '目录已重命名', warning=warning)
    except Exception as e:
        logger.error(f'Rename WI folder error: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/world_info/folders/delete', methods=['POST'])
def api_delete_world_info_folder():
    try:
        req = request.get_json(silent=True) or {}
        cfg = load_config()
        global_dir = _resolve_wi_dir(cfg)
        category = _normalize_category_path(req.get('category'))
        target_dir = _safe_join_category_path(global_dir, category)
        if not target_dir or not os.path.isdir(target_dir):
            return jsonify({'success': False, 'msg': '目录不存在'})
        if os.listdir(target_dir):
            return jsonify({'success': False, 'msg': '只能删除空目录'})
        suppress_fs_events(1.5)
        os.rmdir(target_dir)
        invalidate_wi_list_cache()
        warning = _refresh_worldinfo_folder_stats(cfg)
        return _folder_response(global_dir, '目录已删除', warning=warning)
    except Exception as e:
        logger.error(f'Delete WI folder error: {e}')
        return jsonify({'success': False, 'msg': str(e)})

# 上传世界书
@bp.route('/api/upload_world_info', methods=['POST'])
def api_upload_world_info():
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

        # 获取全局世界书目录
        cfg = load_config()
        raw_wi_dir = cfg.get('world_info_dir', 'lorebooks')
        global_dir = raw_wi_dir if os.path.isabs(raw_wi_dir) else os.path.join(BASE_DIR, raw_wi_dir)
        target_dir = _safe_join_category_path(global_dir, target_category)
        if not target_dir:
            return jsonify({"success": False, "msg": "目标分类不合法"})
        
        suppress_fs_events(2.5)
        os.makedirs(target_dir, exist_ok=True)

        success_count = 0
        failed_list = []
        saved_paths = []

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
                saved_paths.append(save_path)
            except Exception:
                failed_list.append(file.filename)

        msg = f"成功上传 {success_count} 个世界书。"
        if failed_list:
            msg += f" 失败: {', '.join(failed_list)}"
        invalidate_wi_list_cache()
        for save_path in saved_paths:
            _enqueue_worldinfo_file_refresh(save_path, cfg)
        return jsonify({"success": True, "count": success_count, "msg": msg})
        
    except Exception as e:
        logger.error(f"Upload WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/world_info/export', methods=['POST'])
def api_export_world_info():
    try:
        req = request.get_json(silent=True) or {}
        source_type = str(req.get('source_type') or '').strip().lower()
        file_path = str(req.get('file_path') or '').strip()
        card_id = str(req.get('card_id') or '').strip()

        if source_type not in ('global', 'resource', 'embedded'):
            return jsonify({'success': False, 'msg': '不支持的世界书来源'}), 400

        if source_type == 'embedded':
            if not card_id:
                wi_id = str(req.get('id') or '').strip()
                if wi_id.startswith('embedded::'):
                    card_id = wi_id.split('::', 1)[1]
            if not card_id:
                return jsonify({'success': False, 'msg': '角色卡ID缺失'})

            file_path = _safe_join_under_base(str(CARDS_FOLDER), card_id)
            if not file_path:
                return jsonify({'success': False, 'msg': '非法路径'}), 400
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'msg': '未找到角色卡'})

            info = extract_card_info(file_path)
            if not info:
                return jsonify({'success': False, 'msg': '未找到元数据'})

            data_block = info.get('data', {}) if isinstance(info, dict) and 'data' in info else info
            book = data_block.get('character_book') if isinstance(data_block, dict) else None
            if not book:
                return jsonify({'success': False, 'msg': '角色卡无世界书'})

            payload = _build_export_worldbook_payload(book)
            book_name = book.get('name', 'World Info') if isinstance(book, dict) else 'World Info'
            safe_name = sanitize_filename(str(book_name or 'World Info')).strip() or 'World Info'
            download_name = f'{safe_name}.json'
        else:
            cfg = load_config()
            global_dir = _resolve_wi_dir(cfg)
            resources_dir = _resolve_resources_dir(cfg)

            if source_type == 'global':
                if not _is_under_base(file_path, global_dir):
                    return jsonify({'success': False, 'msg': '非法路径'}), 400
            elif source_type == 'resource':
                if not _is_under_base(file_path, resources_dir):
                    return jsonify({'success': False, 'msg': '非法路径'}), 400
                rel_path = os.path.relpath(file_path, resources_dir).replace('\\', '/')
                if '/lorebooks/' not in f'/{rel_path}/':
                    return jsonify({'success': False, 'msg': '非法路径'}), 400

            if not _is_valid_wi_file(file_path, cfg):
                return jsonify({'success': False, 'msg': '非法路径'}), 400
            if not os.path.exists(file_path):
                return jsonify({'success': False, 'msg': '文件不存在'})

            with open(file_path, 'r', encoding='utf-8') as handle:
                book = json.load(handle)

            payload = _build_export_worldbook_payload(book)
            download_name = os.path.basename(file_path)

        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        buf = BytesIO(json_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/json; charset=utf-8',
            as_attachment=True,
            download_name=download_name,
        )
    except Exception as e:
        logger.error(f"Export WI error: {e}")
        return jsonify({'success': False, 'msg': str(e)}), 500


@bp.route('/api/world_info/send_to_st', methods=['POST'])
def api_send_world_info_to_st():
    try:
        req = request.get_json(silent=True) or {}
        source_type = str(req.get('source_type') or '').strip().lower()
        file_path = str(req.get('file_path') or '').strip()

        if source_type == 'embedded':
            return jsonify({'success': False, 'msg': 'embedded 世界书暂不支持发送到 ST'}), 400

        if source_type not in ('global', 'resource') or not file_path:
            return jsonify({'success': False, 'msg': '缺少必要参数'}), 400

        cfg = load_config()
        global_dir = _resolve_wi_dir(cfg)
        resources_dir = _resolve_resources_dir(cfg)
        auth_type = cfg.get('st_auth_type', 'basic')

        if not os.path.isabs(file_path):
            file_path = os.path.normpath(os.path.join(BASE_DIR, file_path))

        if source_type == 'global':
            if not _is_under_base(file_path, global_dir):
                return jsonify({'success': False, 'msg': '非法路径'}), 400
        else:
            if not _is_under_base(file_path, resources_dir):
                return jsonify({'success': False, 'msg': '非法路径'}), 400
            rel_path = os.path.relpath(file_path, resources_dir).replace('\\', '/')
            if '/lorebooks/' not in f'/{rel_path}/':
                return jsonify({'success': False, 'msg': '非法路径'}), 400

        if not _is_valid_wi_file(file_path, cfg):
            return jsonify({'success': False, 'msg': '非法路径'}), 400
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'msg': '文件不存在'})

        with open(file_path, 'r', encoding='utf-8') as handle:
            book = json.load(handle)
        if not _is_sendable_worldinfo_payload(book):
            return jsonify({'success': False, 'msg': '世界书格式无效'}), 400

        with open(file_path, 'rb') as handle:
            raw_bytes = handle.read()
        payload_bytes = _build_send_worldbook_json_bytes(book, raw_bytes)

        st_client = build_st_http_client(cfg, timeout=10)
        payload_file = _MultipartUploadBuffer(payload_bytes)
        files = {
            'avatar': (
                os.path.basename(file_path),
                payload_file,
                'application/json',
            )
        }
        try:
            response = st_client.post(
                '/api/worldinfo/import',
                files=files,
                timeout=10,
            )
        except STAuthError as error:
            return jsonify({'success': False, 'msg': _format_st_auth_error(error)})

        if response.status_code != 200:
            return jsonify({'success': False, 'msg': _format_st_response_error(response, auth_type)})

        st_response = response.json() if response.content else 'OK'
        ui_data = load_ui_data()
        ui_key = _get_worldinfo_ui_key(source_type, file_path, cfg)
        _, last_sent_to_st = set_last_sent_to_st(ui_data, ui_key, time.time())
        save_ui_data(ui_data)
        invalidate_wi_list_cache()

        return jsonify({
            'success': True,
            'st_response': st_response,
            'last_sent_to_st': last_sent_to_st,
        })
    except Exception as e:
        logger.error('Send world info to ST error: %s', e)
        return jsonify({'success': False, 'msg': str(e)})

@bp.route('/api/world_info/detail', methods=['POST'])
def api_get_world_info_detail():
    try:
        # id 格式: "type::path"
        req = request.json or {}
        wi_id = req.get('id')
        source_type = req.get('source_type')
        file_path = req.get('file_path')
        card_id = req.get('card_id')
        preview_limit = request.json.get('preview_limit')
        force_full = bool(request.json.get('force_full', False))
        sort_mode = request.json.get('sort_mode', 'priority')
        ui_data = load_ui_data()

        if source_type == 'embedded' and wi_id and not file_path:
            try:
                _prefix, card_id = str(wi_id).split('::', 1)
            except ValueError:
                card_id = ''

            if not card_id:
                return jsonify({"success": False, "msg": "文件路径为空"})

            file_path = os.path.join(str(CARDS_FOLDER), card_id.replace('/', os.sep))
            if not os.path.exists(file_path):
                return jsonify({"success": False, "msg": "文件不存在"})

            info = extract_card_info(file_path)
            if not info:
                return jsonify({"success": False, "msg": "文件不存在"})

            data_block = info.get('data', {}) if isinstance(info, dict) and 'data' in info else info
            book = data_block.get('character_book') if isinstance(data_block, dict) else None
            if book is None:
                return jsonify({"success": False, "msg": "未找到内嵌世界书"})

            cfg = load_config()
            resp = _apply_world_info_preview(
                book,
                cfg,
                preview_limit=preview_limit,
                force_full=force_full,
                sort_mode=sort_mode,
            )
            resp['ui_summary'] = _get_embedded_worldinfo_ui_summary(ui_data, card_id=card_id)
            resp['source_revision'] = build_file_source_revision(file_path)
            return jsonify(resp)

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

        resp = _apply_world_info_preview(
            data,
            cfg,
            preview_limit=preview_limit,
            force_full=force_full,
            sort_mode=sort_mode,
        )
        effective_source = source_type if source_type in ('global', 'resource') else ('resource' if _is_under_base(file_path, resources_dir) else 'global')
        resp['ui_summary'] = _get_worldinfo_ui_summary(ui_data, effective_source, file_path=file_path)
        if effective_source in ('global', 'resource'):
            resp['last_sent_to_st'] = _get_worldinfo_last_sent_to_st(ui_data, effective_source, file_path, cfg)
        resp['source_revision'] = build_file_source_revision(file_path)
        return jsonify(resp)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})


@bp.route('/api/world_info/detail_search', methods=['POST'])
def api_world_info_detail_search():
    req = request.get_json(silent=True) or {}
    data = req.get('data') or {}
    query = str(req.get('query') or '').strip().lower()
    if not query:
        return jsonify({'success': True, 'items': []})

    def _normalize_terms(value):
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        if value is None:
            return []
        return [str(value)]

    entries = []
    raw_entries = data.get('entries') if isinstance(data, dict) else []
    if isinstance(raw_entries, dict):
        raw_entries = list(raw_entries.values())
    for index, entry in enumerate(raw_entries or []):
        entry = entry or {}
        comment = str(entry.get('comment') or '')
        content = str(entry.get('content') or '')
        key_terms = []
        key_terms.extend(_normalize_terms(entry.get('keys')))
        key_terms.extend(_normalize_terms(entry.get('secondary_keys')))
        key_terms.extend(_normalize_terms(entry.get('keysecondary')))
        key_terms.extend(_normalize_terms(entry.get('key')))
        text = ' '.join([comment, content, ' '.join(key_terms)]).lower()
        if query in text:
            entries.append({'index': index})
    return jsonify({'success': True, 'items': entries})


@bp.route('/api/world_info/note/save', methods=['POST'])
def api_save_world_info_note():
    try:
        req = request.get_json(silent=True) or {}
        source_type = str(req.get('source_type') or '').strip().lower()
        file_path = req.get('file_path') or ''
        card_id = req.get('card_id') or ''
        summary = req.get('summary', '')

        cfg = load_config()
        if source_type in ('global', 'resource'):
            if not file_path:
                return jsonify({'success': False, 'msg': '文件路径为空'})

            if not os.path.isabs(file_path):
                file_path = os.path.normpath(os.path.join(BASE_DIR, file_path))
            else:
                file_path = os.path.normpath(file_path)

            if not _is_valid_wi_file(file_path, cfg):
                return jsonify({'success': False, 'msg': '非法路径'})
        elif source_type == 'embedded':
            if not card_id:
                try:
                    _prefix, card_id = str(req.get('id') or '').split('::', 1)
                except ValueError:
                    card_id = ''
            if not card_id:
                return jsonify({'success': False, 'msg': '卡片 ID 为空'})
        else:
            return jsonify({'success': False, 'msg': '非法来源'})

        ui_data = load_ui_data()
        changed = set_worldinfo_note(
            ui_data,
            source_type,
            summary,
            **_build_worldinfo_note_kwargs(source_type, file_path=file_path, card_id=card_id)
        )
        if changed:
            save_ui_data(ui_data)
            invalidate_wi_list_cache()
            _enqueue_worldinfo_note_refresh(source_type, file_path=file_path, card_id=card_id)

        return jsonify({
            'success': True,
            'ui_summary': _get_worldinfo_ui_summary(ui_data, source_type, file_path=file_path, card_id=card_id),
            'source_type': source_type,
            'file_path': file_path,
            'card_id': card_id,
        })
    except Exception as e:
        logger.error(f'Save worldinfo note error: {e}')
        return jsonify({'success': False, 'msg': str(e)})

@bp.route('/api/world_info/save', methods=['POST'])
def api_save_world_info():
    try:
        req = request.get_json(silent=True)
        if not isinstance(req, dict):
            return jsonify({"success": False, "msg": "请求必须为 JSON 对象"})

        save_mode = req.get('save_mode') # 'overwrite', 'new_global', 'new_resource'
        target_path = req.get('file_path') # 如果是 overwrite
        name = req.get('name')
        content = req.get('content') # JSON 对象
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
            if _is_under_base(final_path, str(CARDS_FOLDER)):
                return jsonify({"success": False, "msg": "内嵌世界书请通过卡片保存流程更新"})
            if not _is_valid_wi_file(final_path, cfg):
                return jsonify({"success": False, "msg": "非法路径"})
            requested_revision = str(req.get('source_revision') or '').strip()
            if not requested_revision:
                return jsonify({
                    'success': False,
                    'msg': 'source_revision required for overwrite',
                    'current_source_revision': build_file_source_revision(final_path),
                }), 409
            current_revision = build_file_source_revision(final_path)
            if current_revision and requested_revision != current_revision:
                return jsonify({
                    'success': False,
                    'msg': f'source_revision mismatch: expected {current_revision}',
                    'current_source_revision': current_revision,
                }), 409
            try:
                with open(final_path, 'r', encoding='utf-8') as f:
                    old_content = json.load(f)
            except Exception:
                old_content = None
            
        elif save_mode == 'new_global':
            cfg = load_config()
            raw_wi = cfg.get('world_info_dir', 'lorebooks')
            current_wi_folder = raw_wi if os.path.isabs(raw_wi) else os.path.join(BASE_DIR, raw_wi)
            os.makedirs(current_wi_folder, exist_ok=True)
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
            return jsonify({"success": False, "msg": "当前阶段暂不支持直接创建 resource 世界书"})

        if isinstance(content, (dict, list)):
            ensure_entry_uids(content)
            history_records = collect_previous_versions(old_content, content)

        # 写入
        compact = bool(req.get('compact', False))
        suppress_fs_events(2.5)
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
        try:
            _enqueue_worldinfo_file_refresh(final_path, load_config())
        except Exception as exc:
            logger.warning('Enqueue world info refresh failed for %s: %s', final_path, exc)
        return jsonify({
            "success": True,
            "new_path": final_path,
            "source_revision": build_file_source_revision(final_path),
        })
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

        suppress_fs_events(5.0)
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
                                os.makedirs(lore_target_dir, exist_ok=True)
                                
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

        file_path = _safe_join_under_base(str(CARDS_FOLDER), cid)
        if not file_path:
            return jsonify({"success": False, "msg": "非法路径"}), 400
        if not os.path.exists(file_path):
            return jsonify({"success": False, "msg": "未找到角色卡"})

        info = extract_card_info(file_path)
        if not info:
            return jsonify({"success": False, "msg": "未找到元数据"})

        # 获取世界书数据
        book = info.get("data", {}).get("character_book") or info.get("character_book")
        if not book:
            return jsonify({"success": False, "msg": "角色卡无世界书"})

        final_export = _build_export_worldbook_payload(book)

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
        source_type = str((request.json or {}).get('source_type') or '').strip().lower()
        if source_type == 'embedded':
            return jsonify({"success": False, "msg": "内嵌世界书不支持删除，请改为删除本地备注"})

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
        suppress_fs_events(2.5)
        if safe_move_to_trash(file_path, TRASH_FOLDER):
            ui_data = load_ui_data()
            if source_type in ('global', 'resource'):
                if delete_worldinfo_note(ui_data, source_type, file_path=file_path):
                    save_ui_data(ui_data)
            # 刷新列表缓存
            invalidate_wi_list_cache()
            _enqueue_worldinfo_file_refresh(file_path, cfg)
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "msg": "移动到回收站失败"})
            
    except Exception as e:
        logger.error(f"Delete WI error: {e}")
        return jsonify({"success": False, "msg": str(e)})
