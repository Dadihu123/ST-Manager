"""Helpers for keeping card UI data stable when card paths change."""

from copy import deepcopy

from core.utils.card_identity import CARD_UID_FIELD, new_card_uid, normalize_card_uid


CHAT_BINDING_FIELD = 'chat_ids'
STALE_CARD_BINDINGS_KEY = '_stale_card_bindings_v1'


def _normalize_card_path(value):
    return str(value or '').replace('\\', '/').strip('/')


def _is_card_ui_key(key):
    """Return whether a top-level ui_data key can represent a card path."""
    return isinstance(key, str) and bool(key) and not key.startswith('_')


def _merge_card_ui_entries(source, target):
    """Merge two card entries without dropping existing chat bindings."""
    if not isinstance(source, dict):
        return deepcopy(target) if isinstance(target, dict) else deepcopy(source)
    if not isinstance(target, dict):
        return deepcopy(source)

    merged = deepcopy(target)
    for key, value in source.items():
        if key != CHAT_BINDING_FIELD:
            if key == CARD_UID_FIELD and normalize_card_uid(merged.get(CARD_UID_FIELD)):
                continue
            merged[key] = deepcopy(value)
            continue

        chat_ids = []
        for raw_ids in (merged.get(CHAT_BINDING_FIELD), value):
            if not isinstance(raw_ids, list):
                continue
            for chat_id in raw_ids:
                normalized = str(chat_id or '').replace('\\', '/')
                if normalized and normalized not in chat_ids:
                    chat_ids.append(normalized)
        if chat_ids:
            merged[CHAT_BINDING_FIELD] = chat_ids
        else:
            merged.pop(CHAT_BINDING_FIELD, None)
    return merged


def normalize_chat_ids(raw_ids):
    """Normalize a UI entry's chat ID list while preserving its order."""
    if not isinstance(raw_ids, list):
        return []

    normalized_ids = []
    for chat_id in raw_ids:
        value = str(chat_id or '').replace('\\', '/').strip().strip('/')
        if value and value not in normalized_ids:
            normalized_ids.append(value)
    return normalized_ids


def ensure_card_ui_uid(entry, card_uid=None):
    """Return and persist a stable UUID on a card UI entry."""
    if not isinstance(entry, dict):
        return ''

    normalized = normalize_card_uid(card_uid) or normalize_card_uid(entry.get(CARD_UID_FIELD))
    if not normalized:
        normalized = new_card_uid()
    if entry.get(CARD_UID_FIELD) != normalized:
        entry[CARD_UID_FIELD] = normalized
    return normalized


def migrate_legacy_card_bindings(ui_data, card_uid_by_ui_key):
    """Attach database UUIDs to legacy path-based UI chat bindings."""
    if not isinstance(ui_data, dict):
        return False

    changed = False
    for raw_key, card_uid in (card_uid_by_ui_key or {}).items():
        key = _normalize_card_path(raw_key)
        normalized_uid = normalize_card_uid(card_uid)
        entry = ui_data.get(key)
        if not key or not normalized_uid or not isinstance(entry, dict):
            continue
        if not normalize_chat_ids(entry.get(CHAT_BINDING_FIELD)):
            continue
        if normalize_card_uid(entry.get(CARD_UID_FIELD)) != normalized_uid:
            entry[CARD_UID_FIELD] = normalized_uid
            changed = True
    return changed


def reconcile_stale_card_bindings(ui_data, valid_card_ui_keys, card_uid_by_ui_key=None):
    """Move bindings from UI keys that no longer map to a physical card.

    The original entry is retained for its ordinary UI metadata, while its
    chat IDs are moved to a recoverable special record.  A later UUID-aware
    migration can use that record to restore the binding after a restart.
    """
    if not isinstance(ui_data, dict):
        return False

    valid_keys = {
        _normalize_card_path(key)
        for key in (valid_card_ui_keys or [])
        if _normalize_card_path(key)
    }
    uid_by_key = {
        _normalize_card_path(key): normalize_card_uid(value)
        for key, value in (card_uid_by_ui_key or {}).items()
        if _normalize_card_path(key) and normalize_card_uid(value)
    }
    stale_store = ui_data.get(STALE_CARD_BINDINGS_KEY)
    if not isinstance(stale_store, dict):
        stale_store = {}

    changed = migrate_legacy_card_bindings(ui_data, uid_by_key)

    current_key_by_uid = {
        card_uid: key
        for key, card_uid in uid_by_key.items()
        if key in valid_keys
    }

    for stale_key in list(stale_store.keys()):
        record = stale_store.get(stale_key)
        if not isinstance(record, dict):
            continue
        record_uid = normalize_card_uid(record.get(CARD_UID_FIELD))
        record_entry = record.get('entry')
        if not record_uid and isinstance(record_entry, dict):
            record_uid = normalize_card_uid(record_entry.get(CARD_UID_FIELD))
        target_key = current_key_by_uid.get(record_uid)
        if not target_key:
            continue

        target_entry = ui_data.get(target_key)
        if not isinstance(target_entry, dict):
            target_entry = {}
        restored_entry = deepcopy(record_entry) if isinstance(record_entry, dict) else {}
        restored_entry[CHAT_BINDING_FIELD] = normalize_chat_ids(record.get(CHAT_BINDING_FIELD))
        restored_entry[CARD_UID_FIELD] = record_uid
        ui_data[target_key] = _merge_card_ui_entries(restored_entry, target_entry)
        stale_store.pop(stale_key, None)
        changed = True

    for key in list(ui_data.keys()):
        if not _is_card_ui_key(key) or _normalize_card_path(key) in valid_keys:
            continue

        entry = ui_data.get(key)
        if not isinstance(entry, dict):
            continue

        entry_uid = normalize_card_uid(entry.get(CARD_UID_FIELD))
        target_key = current_key_by_uid.get(entry_uid)
        if not target_key:
            continue

        target_entry = ui_data.get(target_key)
        if not isinstance(target_entry, dict):
            target_entry = {}
        ui_data[target_key] = _merge_card_ui_entries(entry, target_entry)
        ui_data[target_key][CARD_UID_FIELD] = entry_uid
        ui_data.pop(key, None)
        stale_store.pop(key, None)
        changed = True

    for key in list(ui_data.keys()):
        if not _is_card_ui_key(key) or _normalize_card_path(key) in valid_keys:
            continue
        entry = ui_data.get(key)
        if not isinstance(entry, dict):
            continue

        chat_ids = normalize_chat_ids(entry.get(CHAT_BINDING_FIELD))
        if not chat_ids:
            continue

        record = stale_store.get(key)
        if not isinstance(record, dict):
            record = {}
        previous_ids = normalize_chat_ids(record.get(CHAT_BINDING_FIELD))
        record[CHAT_BINDING_FIELD] = normalize_chat_ids(previous_ids + chat_ids)

        metadata = deepcopy(entry)
        metadata.pop(CHAT_BINDING_FIELD, None)
        if metadata:
            record['entry'] = metadata
        entry_uid = normalize_card_uid(entry.get(CARD_UID_FIELD))
        if entry_uid:
            record[CARD_UID_FIELD] = entry_uid
        stale_store[key] = record
        entry.pop(CHAT_BINDING_FIELD, None)
        changed = True

    if stale_store:
        ui_data[STALE_CARD_BINDINGS_KEY] = stale_store
    elif changed:
        ui_data.pop(STALE_CARD_BINDINGS_KEY, None)
    return changed


def rename_card_ui_references(ui_data, old_id, new_id, *, recursive=False):
    """Move card UI entries from an old path to a new path.

    ``chat_ids`` are merged when a destination entry already exists.  Special
    top-level UI records (whose keys start with ``_``) are intentionally left
    untouched; their path-specific migrations are handled by their owners.
    """
    if not isinstance(ui_data, dict):
        return False

    old_path = _normalize_card_path(old_id)
    new_path = _normalize_card_path(new_id)
    if not old_path or not new_path or old_path == new_path:
        return False

    old_prefix = f'{old_path}/'
    stale_store = ui_data.get(STALE_CARD_BINDINGS_KEY)
    moved = []
    for key in list(ui_data.keys()):
        if not _is_card_ui_key(key):
            continue
        normalized_key = _normalize_card_path(key)
        if normalized_key == old_path:
            target_key = new_path
        elif recursive and normalized_key.startswith(old_prefix):
            target_key = new_path + normalized_key[len(old_path):]
        else:
            continue
        moved.append((key, target_key, ui_data[key]))

    active_source_keys = {source_key for source_key, _, _ in moved}
    stale_moved = []
    if isinstance(stale_store, dict):
        for source_key, record in list(stale_store.items()):
            if source_key in active_source_keys or not isinstance(record, dict):
                continue
            normalized_key = _normalize_card_path(source_key)
            if normalized_key == old_path:
                target_key = new_path
            elif recursive and normalized_key.startswith(old_prefix):
                target_key = new_path + normalized_key[len(old_path):]
            else:
                continue

            source_entry = record.get('entry')
            source_entry = deepcopy(source_entry) if isinstance(source_entry, dict) else {}
            chat_ids = normalize_chat_ids(record.get(CHAT_BINDING_FIELD))
            if chat_ids:
                source_entry[CHAT_BINDING_FIELD] = chat_ids
            record_uid = normalize_card_uid(record.get(CARD_UID_FIELD))
            if record_uid:
                source_entry[CARD_UID_FIELD] = record_uid
            stale_moved.append((source_key, target_key, source_entry))

    if not moved and not stale_moved:
        return False

    for source_key, _, _ in moved:
        ui_data.pop(source_key, None)

    for source_key, target_key, source_entry in moved:
        if isinstance(stale_store, dict):
            stale_record = stale_store.get(source_key)
            if isinstance(stale_record, dict) and isinstance(source_entry, dict):
                recovered_ids = normalize_chat_ids(
                    normalize_chat_ids(source_entry.get(CHAT_BINDING_FIELD))
                    + normalize_chat_ids(stale_record.get(CHAT_BINDING_FIELD))
                )
                source_entry = deepcopy(source_entry)
                if recovered_ids:
                    source_entry[CHAT_BINDING_FIELD] = recovered_ids
                stale_store.pop(source_key, None)
        if target_key in ui_data:
            ui_data[target_key] = _merge_card_ui_entries(source_entry, ui_data[target_key])
        else:
            ui_data[target_key] = deepcopy(source_entry)

    for source_key, target_key, source_entry in stale_moved:
        stale_store.pop(source_key, None)
        if target_key in ui_data:
            ui_data[target_key] = _merge_card_ui_entries(source_entry, ui_data[target_key])
        else:
            ui_data[target_key] = source_entry

    if isinstance(stale_store, dict) and not stale_store:
        ui_data.pop(STALE_CARD_BINDINGS_KEY, None)
    return True
