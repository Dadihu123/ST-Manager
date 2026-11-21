import logging
import os
import time
import uuid

from core.config import DB_FOLDER


logger = logging.getLogger(__name__)

CHAT_DATA_FILE = os.path.join(DB_FOLDER, 'chat_data.json')


def _normalize_timestamp(value, fallback=0.0):
    if isinstance(value, bool):
        return float(fallback)

    try:
        ts = float(value)
    except (TypeError, ValueError):
        return float(fallback)

    if ts <= 0:
        return float(fallback)
    return ts


def _normalize_int(value, fallback=0):
    if isinstance(value, bool):
        return int(fallback)

    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _normalize_text(value, fallback=''):
    if value is None:
        return fallback
    return str(value).strip()


def _normalize_bookmark(item):
    if not isinstance(item, dict):
        return None

    bookmark_id = _normalize_text(item.get('id')) or uuid.uuid4().hex[:12]

    floor = item.get('floor')
    if floor in (None, ''):
        floor_value = None
    else:
        floor_value = _normalize_int(floor, 0)
        if floor_value <= 0:
            floor_value = None

    label = _normalize_text(item.get('label'))
    text = _normalize_text(item.get('text') or item.get('excerpt'))
    created_at = _normalize_timestamp(item.get('created_at'), time.time())

    return {
        **item,
        'id': bookmark_id,
        'floor': floor_value,
        'label': label,
        'text': text,
        'created_at': created_at,
    }


def default_chat_entry():
    return {
        'display_name': '',
        'chat_name': '',
        'character_name': '',
        'favorite': False,
        'notes': '',
        'import_time': 0.0,
        'file_mtime': 0.0,
        'file_size': 0,
        'message_count': 0,
        'user_count': 0,
        'assistant_count': 0,
        'created_at': '',
        'first_message_at': '',
        'last_message_at': '',
        'preview': '',
        'last_view_floor': 0,
        'metadata': {},
        'bookmarks': [],
        'source_type': 'local',
        'updated_at': 0.0,
    }


def normalize_chat_entry(raw):
    entry = default_chat_entry()
    source = raw if isinstance(raw, dict) else {}
    entry.update(source)  # Preserve unknown extension fields across metadata refreshes.

    entry['display_name'] = _normalize_text(source.get('display_name'))
    entry['chat_name'] = _normalize_text(source.get('chat_name'))
    entry['character_name'] = _normalize_text(source.get('character_name'))
    entry['favorite'] = bool(source.get('favorite', False))
    entry['notes'] = _normalize_text(source.get('notes'))
    entry['import_time'] = _normalize_timestamp(source.get('import_time'), 0.0)
    entry['file_mtime'] = _normalize_timestamp(source.get('file_mtime'), 0.0)
    entry['file_size'] = max(0, _normalize_int(source.get('file_size'), 0))
    entry['message_count'] = max(0, _normalize_int(source.get('message_count'), 0))
    entry['user_count'] = max(0, _normalize_int(source.get('user_count'), 0))
    entry['assistant_count'] = max(0, _normalize_int(source.get('assistant_count'), 0))
    entry['created_at'] = _normalize_text(source.get('created_at'))
    entry['first_message_at'] = _normalize_text(source.get('first_message_at'))
    entry['last_message_at'] = _normalize_text(source.get('last_message_at'))
    entry['preview'] = _normalize_text(source.get('preview'))
    entry['last_view_floor'] = max(0, _normalize_int(source.get('last_view_floor'), 0))
    entry['metadata'] = source.get('metadata') if isinstance(source.get('metadata'), dict) else {}
    entry['source_type'] = _normalize_text(source.get('source_type'), 'local') or 'local'
    entry['updated_at'] = _normalize_timestamp(source.get('updated_at'), 0.0)

    raw_bookmarks = source.get('bookmarks') if isinstance(source.get('bookmarks'), list) else []
    bookmarks = []
    seen_ids = set()
    for item in raw_bookmarks:
        normalized = _normalize_bookmark(item)
        if not normalized:
            continue
        bookmark_id = normalized['id']
        if bookmark_id in seen_ids:
            continue
        seen_ids.add(bookmark_id)
        bookmarks.append(normalized)
    entry['bookmarks'] = bookmarks

    return entry


def load_chat_data():
    from core.data.local_state_repository import snapshot
    return snapshot('chat')


def save_chat_data(data, *, guard=None, conn=None):
    from core.data.local_state_repository import Repository
    try:
        repository = Repository('chat')
        if guard is None:
            return repository.save(data, conn=conn)
        with repository.transaction() as conn:
            guard(conn)
            return repository.save(data, conn=conn)
    except Exception as exc:
        logger.error('保存聊天本地状态失败: %s', exc)
        return False


def ensure_chat_entry(chat_data, chat_id, fallback=None):
    if not isinstance(chat_data, dict):
        return None, False

    key = _normalize_text(chat_id)
    if not key:
        return None, False

    existing = normalize_chat_entry(chat_data.get(key))
    changed = key not in chat_data

    if isinstance(fallback, dict):
        merged = dict(existing)
        for field, value in fallback.items():
            if field == 'bookmarks':
                continue
            if value is None:
                continue
            if field in ('favorite',):
                merged[field] = bool(value)
            elif field in ('import_time', 'file_mtime', 'updated_at'):
                merged[field] = _normalize_timestamp(value, merged.get(field, 0.0))
            elif field in ('file_size', 'message_count', 'user_count', 'assistant_count', 'last_view_floor'):
                merged[field] = max(0, _normalize_int(value, merged.get(field, 0)))
            elif field == 'metadata':
                merged[field] = value if isinstance(value, dict) else merged.get(field, {})
            else:
                merged[field] = _normalize_text(value, merged.get(field, ''))

        existing = normalize_chat_entry(merged)
        if chat_data.get(key) != existing:
            changed = True

    chat_data[key] = existing
    return existing, changed


def rename_chat_entry(chat_data, old_chat_id, new_chat_id):
    if not isinstance(chat_data, dict):
        return False

    old_key = _normalize_text(old_chat_id)
    new_key = _normalize_text(new_chat_id)
    if not old_key or not new_key or old_key == new_key:
        return False

    if old_key not in chat_data:
        return False

    chat_data[new_key] = normalize_chat_entry(chat_data.pop(old_key))
    return True


def delete_chat_entry(chat_data, chat_id):
    if not isinstance(chat_data, dict):
        return False

    key = _normalize_text(chat_id)
    if not key or key not in chat_data:
        return False

    del chat_data[key]
    return True
