import logging
import os
import shutil
import time

from flask import Blueprint, jsonify, request

from core.config import CARDS_FOLDER, CHATS_FOLDER, TRASH_FOLDER
from core.context import ctx
from core.data.chat_store import (
    delete_chat_entry,
    ensure_chat_entry,
    load_chat_data,
    rename_chat_entry,
    save_chat_data,
)
from core.data.ui_store import load_ui_data, save_ui_data
from core.services.card_binding_service import (
    ensure_card_ui_uid,
    reconcile_stale_card_bindings,
)
from core.services.card_service import resolve_ui_key
from core.utils.card_identity import normalize_card_uid
from core.utils.chat_parser import (
    build_chat_stats,
    build_chat_stats_from_index,
    get_chat_jsonl_index,
    invalidate_chat_jsonl_index,
    parse_messages,
    read_chat_jsonl,
    read_chat_jsonl_range,
    write_chat_jsonl,
)
from core.utils.filesystem import safe_move_to_trash, sanitize_filename
from core.utils.image import extract_card_info


logger = logging.getLogger(__name__)

bp = Blueprint('chats', __name__)

CHAT_BINDING_FIELD = 'chat_ids'
CHAT_RANGE_PAGE_SIZE = 96
CHAT_NAV_BATCH_SIZE = 200
CHAT_DETAIL_FULL_INDEX_THRESHOLD = 600


def _get_chats_root() -> str:
    return os.path.abspath(os.fspath(CHATS_FOLDER))


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _normalize_chat_id(chat_id: str) -> str:
    return str(chat_id or '').replace('\\', '/').strip().strip('/').replace('//', '/')


def _is_safe_chat_rel(chat_id: str) -> bool:
    value = _normalize_chat_id(chat_id)
    if not value:
        return False
    if os.path.isabs(value):
        return False
    drive, _ = os.path.splitdrive(value)
    if drive:
        return False
    if value.startswith('../') or '/../' in f'/{value}' or value == '..':
        return False
    return value.lower().endswith('.jsonl')


def _chat_abs_path(chat_id: str) -> str:
    return os.path.abspath(os.path.join(_get_chats_root(), _normalize_chat_id(chat_id).replace('/', os.sep)))


def _is_under_base(path: str, base: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) == os.path.abspath(base)
    except Exception:
        return False


def _relative_chat_id(full_path: str) -> str:
    rel = os.path.relpath(full_path, _get_chats_root())
    return rel.replace('\\', '/')


def _ensure_ui_chat_list(entry: dict):
    if not isinstance(entry, dict):
        return []

    raw = entry.get(CHAT_BINDING_FIELD)
    if not isinstance(raw, list):
        return []

    normalized = []
    seen = set()
    for item in raw:
        chat_id = _normalize_chat_id(item)
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        normalized.append(chat_id)
    return normalized


def _set_ui_chat_list(entry: dict, chat_ids):
    if not isinstance(entry, dict):
        return False

    normalized = []
    seen = set()
    for item in chat_ids if isinstance(chat_ids, list) else []:
        chat_id = _normalize_chat_id(item)
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        normalized.append(chat_id)

    if normalized:
        if entry.get(CHAT_BINDING_FIELD) == normalized:
            return False
        entry[CHAT_BINDING_FIELD] = normalized
        return True

    if CHAT_BINDING_FIELD in entry:
        del entry[CHAT_BINDING_FIELD]
        return True

    return False


def _chat_special_ui_key(key: str) -> bool:
    return str(key or '').startswith('_')


def _current_card_ui_keys():
    identities = _current_card_ui_identities()
    return None if identities is None else set(identities)


def _current_card_ui_identities():
    cache = ctx.cache
    if cache is None or not getattr(cache, 'initialized', True):
        return None

    identities = {}
    for card_id in getattr(cache, 'id_map', {}) or {}:
        cache_item = cache.id_map.get(card_id) or {}
        try:
            ui_key = resolve_ui_key(card_id)
        except Exception:
            ui_key = card_id
        if ui_key:
            normalized_key = str(ui_key).replace('\\', '/').strip('/')
            identities[normalized_key] = normalize_card_uid(cache_item.get('card_uid'))

    for bundle_dir in getattr(cache, 'bundle_map', {}) or {}:
        if bundle_dir:
            normalized_key = str(bundle_dir).replace('\\', '/').strip('/')
            if normalized_key not in identities:
                real_card_id = cache.bundle_map.get(bundle_dir)
                cache_item = cache.id_map.get(real_card_id) or {}
                identities[normalized_key] = normalize_card_uid(cache_item.get('card_uid'))
    return identities


def _resolve_card_entry(card_id: str):
    if not card_id:
        return None

    cache = ctx.cache
    if cache is None:
        return None

    cache_item = cache.id_map.get(card_id)
    if cache_item:
        resolved = {
            'ui_key': resolve_ui_key(card_id),
            'card_id': card_id,
            'card_name': cache_item.get('char_name') or os.path.basename(card_id),
            'category': cache_item.get('category', ''),
            'is_bundle': bool(cache_item.get('is_bundle')),
        }
        card_uid = normalize_card_uid(cache_item.get('card_uid'))
        if card_uid:
            resolved['card_uid'] = card_uid
        return resolved

    if card_id in cache.bundle_map:
        real_card_id = cache.bundle_map.get(card_id)
        cache_item = cache.id_map.get(real_card_id)
        if cache_item:
            resolved = {
                'ui_key': card_id,
                'card_id': real_card_id,
                'card_name': cache_item.get('char_name') or os.path.basename(real_card_id),
                'category': cache_item.get('category', ''),
                'is_bundle': bool(cache_item.get('is_bundle')),
            }
            card_uid = normalize_card_uid(cache_item.get('card_uid'))
            if card_uid:
                resolved['card_uid'] = card_uid
            return resolved

    return None


def _build_binding_info(ui_data: dict, chat_id: str):
    results = []
    target = _normalize_chat_id(chat_id)
    if not target or not isinstance(ui_data, dict):
        return results

    for key, value in ui_data.items():
        if _chat_special_ui_key(key) or not isinstance(value, dict):
            continue

        bound_ids = _ensure_ui_chat_list(value)
        if target not in bound_ids:
            continue

        resolved = _resolve_card_entry(key)
        if not resolved:
            continue
        results.append(resolved)

    results.sort(key=lambda item: (item.get('card_name') or '').lower())
    return results


def _remove_chat_from_bindings(ui_data: dict, chat_id: str, card_id: str = None):
    changed = False
    target = _normalize_chat_id(chat_id)
    if not target or not isinstance(ui_data, dict):
        return False

    only_ui_key = resolve_ui_key(card_id) if card_id else None

    for key, value in ui_data.items():
        if _chat_special_ui_key(key) or not isinstance(value, dict):
            continue
        if only_ui_key and key != only_ui_key:
            continue

        current = _ensure_ui_chat_list(value)
        if target not in current:
            continue

        next_ids = [item for item in current if item != target]
        if _set_ui_chat_list(value, next_ids):
            changed = True

    if not only_ui_key:
        stale_store = ui_data.get('_stale_card_bindings_v1')
        if isinstance(stale_store, dict):
            for record in stale_store.values():
                if not isinstance(record, dict):
                    continue
                current = [
                    item for item in _ensure_ui_chat_list(record)
                    if item != target
                ]
                if _set_ui_chat_list(record, current):
                    changed = True

    return changed


def _bind_chat_to_card(ui_data: dict, chat_id: str, card_id: str):
    target = _normalize_chat_id(chat_id)
    if not target or not card_id or not isinstance(ui_data, dict):
        return False, []

    resolved = _resolve_card_entry(card_id)
    ui_key = resolved.get('ui_key') if resolved else None
    if not ui_key:
        return False, []

    changed = _remove_chat_from_bindings(ui_data, target)

    if ui_key not in ui_data or not isinstance(ui_data.get(ui_key), dict):
        ui_data[ui_key] = {}
        changed = True

    entry = ui_data[ui_key]
    resolved_uid = normalize_card_uid(resolved.get('card_uid'))
    previous_uid = normalize_card_uid(entry.get('card_uid'))
    next_uid = ensure_card_ui_uid(entry, resolved_uid or previous_uid)
    if previous_uid != next_uid:
        changed = True

    current = _ensure_ui_chat_list(entry)
    if target not in current:
        current.append(target)
        if _set_ui_chat_list(entry, current):
            changed = True

    return changed, _build_binding_info(ui_data, target)


def _derive_character_name_from_chat_id(chat_id: str) -> str:
    target = _normalize_chat_id(chat_id)
    if '/' not in target:
        return ''
    return target.split('/', 1)[0]


def _derive_card_character_name(card_id: str) -> str:
    cache_item = ctx.cache.id_map.get(card_id)
    if cache_item and cache_item.get('char_name'):
        return str(cache_item.get('char_name')).strip()

    try:
        full_path = os.path.join(os.fspath(CARDS_FOLDER), str(card_id).replace('/', os.sep))
        info = extract_card_info(full_path)
        if info:
            data_block = info.get('data', info) if isinstance(info, dict) else {}
            value = info.get('name') or data_block.get('name')
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass

    return os.path.splitext(os.path.basename(card_id or 'untitled'))[0]


def _resolve_chat_folder_name(card_id: str = '', character_name: str = '', fallback: str = 'Imported') -> str:
    if card_id:
        raw_name = _derive_card_character_name(card_id)
    else:
        raw_name = str(character_name or '').strip()

    if not raw_name:
        return fallback

    folder_name = sanitize_filename(raw_name).strip()
    return folder_name or fallback


def _build_chat_target_path(target_dir: str, filename: str) -> str:
    safe_filename = sanitize_filename(os.path.basename(filename or '')).strip()
    if not safe_filename:
        safe_filename = 'chat.jsonl'

    target_path = os.path.join(target_dir, safe_filename)
    name_part, ext = os.path.splitext(safe_filename)
    counter = 1
    while os.path.exists(target_path):
        target_path = os.path.join(target_dir, f'{name_part}_{counter}{ext}')
        counter += 1
    return target_path


def _rename_chat_in_bindings(ui_data: dict, old_chat_id: str, new_chat_id: str):
    changed = False
    old_target = _normalize_chat_id(old_chat_id)
    new_target = _normalize_chat_id(new_chat_id)

    if not old_target or not new_target or old_target == new_target or not isinstance(ui_data, dict):
        return False

    for key, value in ui_data.items():
        if _chat_special_ui_key(key) or not isinstance(value, dict):
            continue

        current = _ensure_ui_chat_list(value)
        if old_target not in current:
            continue

        next_ids = []
        seen = set()
        for item in current:
            candidate = new_target if item == old_target else item
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            next_ids.append(candidate)

        if _set_ui_chat_list(value, next_ids):
            changed = True

    stale_store = ui_data.get('_stale_card_bindings_v1')
    if isinstance(stale_store, dict):
        for record in stale_store.values():
            if not isinstance(record, dict):
                continue
            current = _ensure_ui_chat_list(record)
            if old_target not in current:
                continue
            next_ids = []
            seen = set()
            for item in current:
                candidate = new_target if item == old_target else item
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                next_ids.append(candidate)
            if _set_ui_chat_list(record, next_ids):
                changed = True

    return changed


def _set_chat_character_name(chat_data: dict, chat_id: str, character_name: str):
    target = _normalize_chat_id(chat_id)
    next_name = str(character_name or '').strip()
    if not target or not next_name or not isinstance(chat_data, dict):
        return False

    entry = chat_data.get(target)
    if not isinstance(entry, dict):
        return False

    if str(entry.get('character_name') or '').strip() == next_name:
        return False

    entry['character_name'] = next_name
    entry['updated_at'] = time.time()
    chat_data[target] = entry
    return True


def _move_chat_to_bound_folder(chat_id: str, card_id: str, chat_data: dict, ui_data: dict):
    source_chat_id = _normalize_chat_id(chat_id)
    source_path = _chat_abs_path(source_chat_id)
    if not os.path.exists(source_path):
        raise FileNotFoundError('聊天记录不存在')

    target_folder_name = _resolve_chat_folder_name(card_id=card_id)
    target_dir = os.path.join(_get_chats_root(), target_folder_name)
    source_dir = os.path.dirname(source_path)

    if os.path.abspath(source_dir) == os.path.abspath(target_dir):
        return source_chat_id, source_path, False, False, False

    os.makedirs(target_dir, exist_ok=True)
    target_path = _build_chat_target_path(target_dir, os.path.basename(source_path))
    shutil.move(source_path, target_path)
    invalidate_chat_jsonl_index(source_path)
    invalidate_chat_jsonl_index(target_path)

    target_chat_id = _relative_chat_id(target_path)
    chat_changed = rename_chat_entry(chat_data, source_chat_id, target_chat_id)
    ui_changed = _rename_chat_in_bindings(ui_data, source_chat_id, target_chat_id)

    _cleanup_empty_chat_dirs(source_dir)
    return target_chat_id, target_path, True, chat_changed, ui_changed


def _refresh_chat_entry(chat_id: str, full_path: str, chat_data: dict, need_messages: bool = False):
    if not os.path.exists(full_path):
        return None, False, None, [], []

    stat = os.stat(full_path)
    existing = chat_data.get(chat_id, {}) if isinstance(chat_data, dict) else {}
    file_mtime = float(stat.st_mtime)
    file_size = int(stat.st_size)

    stale = (
        not isinstance(existing, dict)
        or float(existing.get('file_mtime') or 0) != file_mtime
        or int(existing.get('file_size') or 0) != file_size
        or int(existing.get('message_count') or 0) <= 0
    )

    metadata = None
    raw_messages = []
    parsed_messages = []
    changed = False

    if stale or need_messages:
        if stale and not need_messages:
            index_data = get_chat_jsonl_index(full_path)
            metadata = index_data.get('metadata') if isinstance(index_data.get('metadata'), dict) else {}
        else:
            metadata, raw_messages = read_chat_jsonl(full_path)
            parsed_messages = parse_messages(raw_messages)

    if stale:
        if need_messages:
            stats = build_chat_stats(full_path, metadata, raw_messages, parsed_messages)
        else:
            index_data = get_chat_jsonl_index(full_path)
            stats = build_chat_stats_from_index(
                full_path,
                metadata,
                index_data.get('message_index') if isinstance(index_data, dict) else [],
            )
        fallback = {
            **stats,
            'character_name': _derive_character_name_from_chat_id(chat_id),
            'file_mtime': file_mtime,
            'file_size': file_size,
            'import_time': existing.get('import_time') or file_mtime,
            'updated_at': time.time(),
            'source_type': 'local',
        }
        _, changed = ensure_chat_entry(chat_data, chat_id, fallback)
    else:
        fallback = {
            'chat_name': existing.get('chat_name') or os.path.splitext(os.path.basename(chat_id))[0],
            'character_name': existing.get('character_name') or _derive_character_name_from_chat_id(chat_id),
            'file_mtime': file_mtime,
            'file_size': file_size,
            'import_time': existing.get('import_time') or file_mtime,
        }
        _, changed = ensure_chat_entry(chat_data, chat_id, fallback)

    return chat_data.get(chat_id), changed, metadata, raw_messages, parsed_messages


def _chat_title(entry: dict, chat_id: str) -> str:
    if isinstance(entry, dict):
        display_name = str(entry.get('display_name') or '').strip()
        if display_name:
            return display_name
        chat_name = str(entry.get('chat_name') or '').strip()
        if chat_name:
            return chat_name
    return os.path.splitext(os.path.basename(chat_id))[0]


def _build_chat_item(chat_id: str, entry: dict, ui_data: dict, full_path: str = None):
    bound_cards = _build_binding_info(ui_data, chat_id)
    source = entry if isinstance(entry, dict) else {}
    message_count = int(source.get('message_count') or 0)
    display_name = _chat_title(source, chat_id)
    character_name = str(source.get('character_name') or '').strip() or _derive_character_name_from_chat_id(chat_id)

    return {
        'id': chat_id,
        'title': display_name,
        'display_name': str(source.get('display_name') or '').strip(),
        'chat_name': str(source.get('chat_name') or '').strip() or os.path.splitext(os.path.basename(chat_id))[0],
        'character_name': character_name,
        'filename': os.path.basename(chat_id),
        'relative_dir': os.path.dirname(chat_id).replace('\\', '/'),
        'favorite': bool(source.get('favorite', False)),
        'notes': str(source.get('notes') or ''),
        'preview': str(source.get('preview') or ''),
        'message_count': message_count,
        'start_floor': 1 if message_count > 0 else 0,
        'end_floor': message_count,
        'user_count': int(source.get('user_count') or 0),
        'assistant_count': int(source.get('assistant_count') or 0),
        'created_at': source.get('created_at') or '',
        'first_message_at': source.get('first_message_at') or '',
        'last_message_at': source.get('last_message_at') or '',
        'import_time': float(source.get('import_time') or 0),
        'file_mtime': float(source.get('file_mtime') or 0),
        'file_size': int(source.get('file_size') or 0),
        'last_view_floor': int(source.get('last_view_floor') or 0),
        'bookmark_count': len(source.get('bookmarks') or []),
        'bound_cards': bound_cards,
        'bound_card_count': len(bound_cards),
        'bound_card_id': bound_cards[0]['card_id'] if bound_cards else '',
        'bound_card_name': bound_cards[0]['card_name'] if bound_cards else '',
        'bound_card_category': bound_cards[0].get('category', '') if bound_cards else '',
        'file_path': os.path.abspath(full_path) if full_path else _chat_abs_path(chat_id),
        'metadata': source.get('metadata') if isinstance(source.get('metadata'), dict) else {},
    }


def _cleanup_missing_chats(chat_data: dict, ui_data: dict, existing_chat_ids):
    if not isinstance(chat_data, dict):
        return False, False

    existing = set(_normalize_chat_id(item) for item in existing_chat_ids)
    chat_changed = False
    ui_changed = False

    for chat_id in list(chat_data.keys()):
        if _normalize_chat_id(chat_id) in existing:
            continue
        if delete_chat_entry(chat_data, chat_id):
            chat_changed = True
        if _remove_chat_from_bindings(ui_data, chat_id):
            ui_changed = True

    return chat_changed, ui_changed


def _cleanup_empty_chat_dirs(start_dir: str):
    root = _get_chats_root()
    current = os.path.abspath(start_dir)

    while current and current != root and _is_under_base(current, root):
        try:
            if os.listdir(current):
                break
            os.rmdir(current)
        except Exception:
            break
        current = os.path.dirname(current)


def _search_match(query: str, chat_item: dict) -> bool:
    if not query:
        return True

    haystack = ' '.join([
        str(chat_item.get('title') or ''),
        str(chat_item.get('chat_name') or ''),
        str(chat_item.get('character_name') or ''),
        str(chat_item.get('preview') or ''),
        str(chat_item.get('bound_card_name') or ''),
        str(chat_item.get('notes') or ''),
    ]).lower()
    return query in haystack


def _iter_chat_files():
    root = _get_chats_root()
    if not os.path.exists(root):
        return []

    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not str(name).startswith('.')]
        for filename in filenames:
            if not str(filename).lower().endswith('.jsonl'):
                continue
            full_path = os.path.join(dirpath, filename)
            if not _is_under_base(full_path, root):
                continue
            items.append(full_path)
    return items


@bp.route('/api/chats/list')
def api_list_chats():
    try:
        try:
            page = max(1, int(request.args.get('page', 1)))
        except Exception:
            page = 1
        try:
            page_size = max(1, min(500, int(request.args.get('page_size', 30))))
        except Exception:
            page_size = 30

        query = str(request.args.get('search', '') or '').strip().lower()
        filter_type = str(request.args.get('filter', 'all') or 'all').strip().lower()
        fav_filter = str(request.args.get('fav_filter', 'none') or 'none').strip().lower()
        card_id = str(request.args.get('card_id', '') or '').strip()

        if fav_filter not in ('none', 'included', 'excluded'):
            fav_filter = 'none'

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        card_identities = _current_card_ui_identities()
        valid_card_ui_keys = None if card_identities is None else set(card_identities)
        ui_changed = False
        if valid_card_ui_keys is not None:
            ui_changed = reconcile_stale_card_bindings(
                ui_data,
                valid_card_ui_keys,
                card_uid_by_ui_key=card_identities,
            )

        found_chat_ids = []
        items = []
        chat_changed = False

        for full_path in _iter_chat_files():
            chat_id = _relative_chat_id(full_path)
            found_chat_ids.append(chat_id)

            entry, changed, _, _, _ = _refresh_chat_entry(chat_id, full_path, chat_data, need_messages=False)
            if changed:
                chat_changed = True

            item = _build_chat_item(chat_id, entry, ui_data, full_path=full_path)

            if card_id:
                target_ui_key = resolve_ui_key(card_id)
                if not any(bound.get('ui_key') == target_ui_key for bound in item.get('bound_cards', [])):
                    continue

            if filter_type == 'bound' and item.get('bound_card_count', 0) == 0:
                continue
            if filter_type == 'unbound' and item.get('bound_card_count', 0) > 0:
                continue
            if filter_type == 'favorites' and not item.get('favorite'):
                continue
            if fav_filter == 'included' and not item.get('favorite'):
                continue
            if fav_filter == 'excluded' and item.get('favorite'):
                continue

            if not _search_match(query, item):
                continue

            items.append(item)

        missing_chat_changed, missing_ui_changed = _cleanup_missing_chats(
            chat_data,
            ui_data,
            found_chat_ids,
        )
        chat_changed = chat_changed or missing_chat_changed
        ui_changed = ui_changed or missing_ui_changed

        if chat_changed:
            save_chat_data(chat_data)
        if ui_changed:
            save_ui_data(ui_data)

        items.sort(key=lambda item: (
            0 if item.get('favorite') else 1,
            -(float(item.get('file_mtime') or 0)),
            (item.get('title') or '').lower(),
        ))

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        paged = items[start:end]

        return jsonify({
            'success': True,
            'items': paged,
            'total': total,
            'page': page,
            'page_size': page_size,
            'stats': {
                'favorites': sum(1 for item in items if item.get('favorite')),
                'bound': sum(1 for item in items if item.get('bound_card_count', 0) > 0),
                'unbound': sum(1 for item in items if item.get('bound_card_count', 0) == 0),
            }
        })
    except Exception as e:
        logger.error(f'聊天列表读取失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/detail', methods=['POST'])
def api_chat_detail():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        include_messages = _coerce_bool(data.get('include_messages'), default=False)
        include_message_index = _coerce_bool(data.get('include_message_index'), default=True)
        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400

        full_path = _chat_abs_path(chat_id)
        if not _is_under_base(full_path, _get_chats_root()) or not os.path.exists(full_path):
            return jsonify({'success': False, 'msg': '聊天记录不存在'}), 404

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        entry, changed, metadata, raw_messages, parsed_messages = _refresh_chat_entry(
            chat_id,
            full_path,
            chat_data,
            need_messages=include_messages,
        )
        if changed:
            save_chat_data(chat_data)

        index_data = get_chat_jsonl_index(full_path)
        item = _build_chat_item(chat_id, entry, ui_data, full_path=full_path)
        item['metadata'] = metadata if include_messages and isinstance(metadata, dict) else (
            index_data.get('metadata') if isinstance(index_data.get('metadata'), dict) else {}
        )
        item['bookmarks'] = list((entry or {}).get('bookmarks') or [])
        full_message_index = index_data.get('message_index') if isinstance(index_data.get('message_index'), list) else []
        should_include_message_index = include_message_index or len(full_message_index) <= CHAT_DETAIL_FULL_INDEX_THRESHOLD
        item['message_index'] = full_message_index if should_include_message_index else []
        item['message_index_included'] = should_include_message_index
        item['message_index_total'] = len(full_message_index)
        item['message_index_truncated'] = not should_include_message_index
        item['page_size'] = CHAT_RANGE_PAGE_SIZE
        item['nav_batch_size'] = CHAT_NAV_BATCH_SIZE
        if include_messages:
            item['raw_messages'] = raw_messages
            item['messages'] = parsed_messages

        return jsonify({'success': True, 'chat': item})
    except Exception as e:
        logger.error(f'聊天详情读取失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/range', methods=['POST'])
def api_chat_range():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        include_messages = _coerce_bool(data.get('include_messages'), default=True)
        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400

        full_path = _chat_abs_path(chat_id)
        if not _is_under_base(full_path, _get_chats_root()) or not os.path.exists(full_path):
            return jsonify({'success': False, 'msg': '聊天记录不存在'}), 404

        try:
            page_size = max(1, min(200, int(data.get('page_size') or CHAT_RANGE_PAGE_SIZE)))
        except Exception:
            page_size = CHAT_RANGE_PAGE_SIZE
        try:
            page = max(1, int(data.get('page') or 1))
        except Exception:
            page = 1

        chat_data = load_chat_data()
        entry, changed, _, _, _ = _refresh_chat_entry(chat_id, full_path, chat_data, need_messages=False)
        if changed:
            save_chat_data(chat_data)

        index_data = get_chat_jsonl_index(full_path)
        message_index = index_data.get('message_index') if isinstance(index_data.get('message_index'), list) else []
        total_messages = len(message_index)
        total_pages = max(1, (total_messages + page_size - 1) // page_size) if total_messages > 0 else 0
        if total_pages > 0:
            page = min(page, total_pages)
        else:
            page = 1

        start_floor = (page - 1) * page_size + 1 if total_messages > 0 else 0
        end_floor = min(total_messages, start_floor + page_size - 1) if total_messages > 0 else 0
        metadata = index_data.get('metadata') if isinstance(index_data.get('metadata'), dict) else {}
        raw_messages = []
        parsed_messages = []
        if include_messages and total_messages > 0:
            metadata, raw_messages, parsed_messages = read_chat_jsonl_range(
                full_path,
                start_floor=start_floor,
                end_floor=end_floor,
                index_data=index_data,
            )

        return jsonify({
            'success': True,
            'range': {
                'chat_id': chat_id,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'total_messages': total_messages,
                'start_floor': start_floor,
                'end_floor': end_floor,
                'metadata': metadata if isinstance(metadata, dict) else {},
                'index_items': message_index[start_floor - 1:end_floor] if start_floor > 0 else [],
                'raw_messages': raw_messages,
                'messages': parsed_messages,
                'include_messages': include_messages,
                'has_previous': start_floor > 1,
                'has_next': end_floor < total_messages,
                'last_view_floor': int((entry or {}).get('last_view_floor') or 0),
            }
        })
    except Exception as e:
        logger.error(f'聊天范围读取失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/update_meta', methods=['POST'])
def api_update_chat_meta():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400

        full_path = _chat_abs_path(chat_id)
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'msg': '聊天记录不存在'}), 404

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        entry, changed, _, _, _ = _refresh_chat_entry(chat_id, full_path, chat_data, need_messages=False)

        if not isinstance(entry, dict):
            entry = {}
            chat_data[chat_id] = entry
            changed = True

        for field in ('display_name', 'notes'):
            if field in data:
                next_value = str(data.get(field) or '').strip()
                if entry.get(field) != next_value:
                    entry[field] = next_value
                    changed = True

        if 'favorite' in data:
            next_favorite = bool(data.get('favorite'))
            if bool(entry.get('favorite')) != next_favorite:
                entry['favorite'] = next_favorite
                changed = True

        if 'last_view_floor' in data:
            try:
                next_floor = max(0, int(data.get('last_view_floor') or 0))
            except Exception:
                next_floor = 0
            if int(entry.get('last_view_floor') or 0) != next_floor:
                entry['last_view_floor'] = next_floor
                changed = True

        if 'bookmarks' in data and isinstance(data.get('bookmarks'), list):
            if entry.get('bookmarks') != data.get('bookmarks'):
                entry['bookmarks'] = data.get('bookmarks')
                changed = True

        entry['updated_at'] = time.time()
        chat_data[chat_id] = entry
        if save_chat_data(chat_data):
            changed = False

        item = _build_chat_item(chat_id, chat_data.get(chat_id), ui_data, full_path=full_path)
        item['bookmarks'] = list((chat_data.get(chat_id) or {}).get('bookmarks') or [])

        return jsonify({'success': True, 'chat': item})
    except Exception as e:
        logger.error(f'聊天元数据更新失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/bind', methods=['POST'])
def api_bind_chat():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        card_id = str(data.get('card_id') or '').strip()
        unbind = bool(data.get('unbind', False))

        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        ui_changed = False
        chat_changed = False
        bindings = []
        effective_chat_id = chat_id
        effective_full_path = _chat_abs_path(chat_id)
        moved = False

        if unbind or not card_id:
            ui_changed = _remove_chat_from_bindings(ui_data, effective_chat_id)
            bindings = _build_binding_info(ui_data, effective_chat_id)
        else:
            effective_chat_id, effective_full_path, moved, move_chat_changed, move_ui_changed = _move_chat_to_bound_folder(
                chat_id,
                card_id,
                chat_data,
                ui_data,
            )
            chat_changed = chat_changed or move_chat_changed
            ui_changed = ui_changed or move_ui_changed

            bind_changed, bindings = _bind_chat_to_card(ui_data, effective_chat_id, card_id)
            ui_changed = ui_changed or bind_changed

        entry, refreshed, _, _, _ = _refresh_chat_entry(
            effective_chat_id,
            effective_full_path,
            chat_data,
            need_messages=False,
        )
        chat_changed = chat_changed or refreshed

        if not unbind and card_id:
            if _set_chat_character_name(chat_data, effective_chat_id, _derive_card_character_name(card_id)):
                chat_changed = True
                entry = chat_data.get(effective_chat_id)

        if chat_changed:
            save_chat_data(chat_data)
        if ui_changed:
            save_ui_data(ui_data)

        item = _build_chat_item(effective_chat_id, entry, ui_data, full_path=effective_full_path)

        return jsonify({
            'success': True,
            'id': effective_chat_id,
            'moved': moved,
            'chat': item,
            'bound_cards': bindings,
            'bound_card_count': len(bindings),
        })
    except FileNotFoundError as e:
        return jsonify({'success': False, 'msg': str(e)}), 404
    except Exception as e:
        logger.error(f'聊天绑定失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/import', methods=['POST'])
def api_import_chats():
    try:
        files = request.files.getlist('files')
        card_id = str(request.form.get('card_id') or '').strip()
        character_name = str(request.form.get('character_name') or '').strip()

        valid_files = [item for item in files if item and item.filename]
        if not valid_files:
            return jsonify({'success': False, 'msg': '未选择文件'})

        target_folder_name = _resolve_chat_folder_name(card_id=card_id, character_name=character_name)
        root = _get_chats_root()
        target_dir = os.path.join(root, target_folder_name)
        os.makedirs(target_dir, exist_ok=True)

        chat_data = load_chat_data()
        ui_data = load_ui_data()

        imported = []
        failed = []
        chat_changed = False
        ui_changed = False

        for file_item in valid_files:
            filename = sanitize_filename(os.path.basename(file_item.filename or ''))
            if not filename.lower().endswith('.jsonl'):
                failed.append({'name': file_item.filename, 'msg': '仅支持 .jsonl 聊天记录'})
                continue

            save_path = _build_chat_target_path(target_dir, filename)
            saved = False

            try:
                file_item.save(save_path)
                saved = True
            except Exception as e:
                failed.append({'name': file_item.filename, 'msg': f'保存失败: {e}'})
                logger.error(f'聊天文件保存失败 {file_item.filename}: {e}')
                continue

            chat_id = _relative_chat_id(save_path)
            try:
                entry, changed, _, _, _ = _refresh_chat_entry(chat_id, save_path, chat_data, need_messages=False)
                if changed:
                    chat_changed = True

                if card_id:
                    bind_changed, _ = _bind_chat_to_card(ui_data, chat_id, card_id)
                    ui_changed = ui_changed or bind_changed

                imported.append(_build_chat_item(chat_id, entry, ui_data, full_path=save_path))
            except Exception as e:
                logger.error(f'聊天导入后处理失败 {save_path}: {e}')
                failed.append({'name': file_item.filename, 'msg': f'解析失败: {e}'})
                if saved and os.path.exists(save_path):
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass

        if chat_changed:
            save_chat_data(chat_data)
        if ui_changed:
            save_ui_data(ui_data)

        return jsonify({
            'success': len(imported) > 0,
            'items': imported,
            'imported': len(imported),
            'failed': failed,
            'msg': f'已导入 {len(imported)} 个聊天记录',
        })
    except Exception as e:
        logger.error(f'聊天导入失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/save', methods=['POST'])
def api_save_chat():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        raw_messages = data.get('raw_messages')
        metadata = data.get('metadata')

        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400
        if not isinstance(raw_messages, list):
            return jsonify({'success': False, 'msg': 'raw_messages 格式错误'}), 400

        full_path = _chat_abs_path(chat_id)
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'msg': '聊天记录不存在'}), 404

        existing_metadata, _ = read_chat_jsonl(full_path)
        target_metadata = metadata if isinstance(metadata, dict) else existing_metadata

        if not write_chat_jsonl(full_path, target_metadata, raw_messages):
            return jsonify({'success': False, 'msg': '写入聊天文件失败'})
        invalidate_chat_jsonl_index(full_path)

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        entry, changed, _, _, _ = _refresh_chat_entry(
            chat_id,
            full_path,
            chat_data,
            need_messages=False,
        )
        if changed:
            save_chat_data(chat_data)

        index_data = get_chat_jsonl_index(full_path)
        item = _build_chat_item(chat_id, entry, ui_data, full_path=full_path)
        item['metadata'] = index_data.get('metadata') if isinstance(index_data.get('metadata'), dict) else {}
        item['bookmarks'] = list((entry or {}).get('bookmarks') or [])
        item['message_index'] = index_data.get('message_index') if isinstance(index_data.get('message_index'), list) else []
        item['page_size'] = CHAT_RANGE_PAGE_SIZE

        return jsonify({'success': True, 'chat': item})
    except Exception as e:
        logger.error(f'聊天保存失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/delete', methods=['POST'])
def api_delete_chat():
    try:
        data = request.get_json() or {}
        chat_id = _normalize_chat_id(data.get('id'))
        if not _is_safe_chat_rel(chat_id):
            return jsonify({'success': False, 'msg': '非法聊天路径'}), 400

        full_path = _chat_abs_path(chat_id)
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'msg': '聊天记录不存在'}), 404

        if not safe_move_to_trash(full_path, TRASH_FOLDER):
            return jsonify({'success': False, 'msg': '移动到回收站失败'})

        _cleanup_empty_chat_dirs(os.path.dirname(full_path))

        chat_data = load_chat_data()
        ui_data = load_ui_data()
        chat_changed = delete_chat_entry(chat_data, chat_id)
        ui_changed = _remove_chat_from_bindings(ui_data, chat_id)
        if chat_changed:
            save_chat_data(chat_data)
        if ui_changed:
            save_ui_data(ui_data)

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'聊天删除失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})


@bp.route('/api/chats/search', methods=['POST'])
def api_search_chats():
    try:
        data = request.get_json() or {}
        query = str(data.get('query') or '').strip()
        if not query:
            return jsonify({'success': True, 'items': []})

        query_lower = query.lower()
        limit = max(1, min(500, int(data.get('limit') or 80)))
        card_id = str(data.get('card_id') or '').strip()
        chat_ids = data.get('chat_ids') if isinstance(data.get('chat_ids'), list) else []

        ui_data = load_ui_data()
        chat_data = load_chat_data()
        allowed_chat_ids = set()
        if card_id:
            target_ui_key = resolve_ui_key(card_id)
            for chat_id in chat_ids or []:
                allowed_chat_ids.add(_normalize_chat_id(chat_id))
            if not allowed_chat_ids:
                for chat_path in _ensure_ui_chat_list(ui_data.get(target_ui_key, {})):
                    allowed_chat_ids.add(_normalize_chat_id(chat_path))
        elif chat_ids:
            for chat_id in chat_ids:
                allowed_chat_ids.add(_normalize_chat_id(chat_id))

        items = []
        for full_path in _iter_chat_files():
            chat_id = _relative_chat_id(full_path)
            if allowed_chat_ids and chat_id not in allowed_chat_ids:
                continue

            _, raw_messages = read_chat_jsonl(full_path)
            parsed_messages = parse_messages(raw_messages)
            entry = chat_data.get(chat_id, {})
            title = _chat_title(entry, chat_id)

            for message in parsed_messages:
                raw_text = str(message.get('mes') or '')
                parsed_text = str(message.get('content') or '')
                if query_lower not in raw_text.lower() and query_lower not in parsed_text.lower():
                    continue

                snippet_src = parsed_text or raw_text
                snippet = ' '.join(snippet_src.strip().split())[:220]
                items.append({
                    'chat_id': chat_id,
                    'chat_title': title,
                    'character_name': _derive_character_name_from_chat_id(chat_id),
                    'floor': message.get('floor'),
                    'name': message.get('name'),
                    'is_user': bool(message.get('is_user')),
                    'send_date': message.get('send_date') or '',
                    'snippet': snippet,
                })
                if len(items) >= limit:
                    return jsonify({'success': True, 'items': items})

        return jsonify({'success': True, 'items': items})
    except Exception as e:
        logger.error(f'聊天搜索失败: {e}')
        return jsonify({'success': False, 'msg': str(e)})
