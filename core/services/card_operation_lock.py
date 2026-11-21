"""角色卡级别的非阻塞操作锁。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
import posixpath
import threading

from core.context import ctx

_file_intents = ContextVar('card_file_intents', default=None)
_file_locks = ContextVar('card_file_locks', default=None)


@contextmanager
def file_intent_scope():
    """Keep operation receipts local to the writer, including nested service calls."""
    token = _file_intents.set([]) if _file_intents.get() is None else None
    lock_token = _file_locks.set({}) if token is not None else None
    try:
        yield
    finally:
        if token is not None:
            for lock in reversed(list(_file_locks.get().values())):
                release_card_lock(lock)
            _file_locks.reset(lock_token)
            _file_intents.reset(token)


def record_file_intent(job_id, operation):
    receipts = _file_intents.get()
    if receipts is not None and isinstance(job_id, int):
        receipts.append((job_id, operation))


def current_file_intents():
    return tuple(_file_intents.get() or ())


def _normalize_card_id(card_id) -> str:
    return str(card_id or '').strip().replace('\\', '/')


def _get_lock(card_id, context=None):
    owner = context or ctx
    guard = getattr(owner, 'card_locks_guard', None)
    locks = getattr(owner, 'card_locks', None)
    if guard is None or locks is None:
        return None

    normalized = _normalize_card_id(card_id)
    if not normalized:
        return None
    with guard:
        return locks.setdefault(normalized, threading.RLock())


def _expand_card_ids(card_ids, context=None):
    """将聚合包/文件夹路径展开为缓存中的具体卡片 ID，统一锁定影响范围。"""
    owner = context or ctx
    normalized_ids = {
        normalized
        for normalized in (_normalize_card_id(card_id) for card_id in card_ids)
        if normalized
    }
    # JSON writers can convert to the same-name PNG. Acquire both in the same
    # order as recovery before reading or publishing the conversion intent.
    normalized_ids.update(card_id[:-5] + '.png' for card_id in tuple(normalized_ids)
                          if card_id.lower().endswith('.json'))
    if not normalized_ids:
        return []

    cache = getattr(owner, 'cache', None)
    id_map = getattr(cache, 'id_map', None)
    if not isinstance(id_map, dict):
        return sorted(normalized_ids)

    if all(card_id.lower().endswith(('.png', '.json'))
           and not (id_map.get(card_id) or {}).get('is_bundle') for card_id in normalized_ids):
        return sorted(normalized_ids)

    cache_lock = getattr(cache, 'lock', None)
    if cache_lock is None:
        cached_ids = list(id_map.keys())
    else:
        with cache_lock:
            cached_ids = list(id_map.keys())

    for raw_id in cached_ids:
        cached_id = _normalize_card_id(raw_id)
        if not cached_id:
            continue
        if any(cached_id == base or cached_id.startswith(base + '/') for base in normalized_ids):
            normalized_ids.add(cached_id)
    return sorted(normalized_ids)


def try_acquire_card_lock(card_id, *, context=None, blocking=False, allow_reentrant=True):
    """尝试取得卡片锁，返回 ``(是否取得, lock)``。"""
    lock = _get_lock(card_id, context=context)
    if lock is None:
        return True, None
    if not allow_reentrant:
        is_owned = getattr(lock, '_is_owned', None)
        if callable(is_owned) and is_owned():
            return False, lock
    return bool(lock.acquire(blocking=blocking)), lock


def release_card_lock(lock):
    if lock is None:
        return
    try:
        lock.release()
    except RuntimeError:
        # 仅保护异常路径；正常流程始终由持有锁的线程释放。
        pass


@contextmanager
def card_lock(card_id, *, context=None, blocking=False):
    acquired, lock = try_acquire_card_lock(
        card_id,
        context=context,
        blocking=blocking,
    )
    try:
        yield acquired
    finally:
        if acquired:
            release_card_lock(lock)


@contextmanager
def card_locks(card_ids):
    """Wait for the complete set without holding a subset while another writer runs."""
    ordered = sorted({_normalize_card_id(card_id) for card_id in card_ids if card_id})
    held = []
    try:
        while True:
            for card_id in ordered:
                acquired, lock = try_acquire_card_lock(card_id)
                if not acquired:
                    break
                held.append(lock)
            else:
                break
            for lock in reversed(held):
                release_card_lock(lock)
            held.clear()
            # A writer may already own an old ID and synchronously write a new
            # ID (plugin hook / conflict-resolved move). Never keep the new ID
            # locked while waiting for that writer's old ID.
            acquired, lock = try_acquire_card_lock(card_id, blocking=True)
            if acquired:
                release_card_lock(lock)
        yield
    finally:
        for lock in reversed(held):
            release_card_lock(lock)


def _file_card_ids(paths):
    from core.config import CARDS_FOLDER
    root = os.path.normcase(os.path.abspath(CARDS_FOLDER))
    ids = []
    for path in paths:
        if not path or not str(path).lower().endswith(('.png', '.json')):
            continue
        absolute = os.path.normcase(os.path.abspath(path))
        try:
            inside = os.path.commonpath([root, absolute]) == root
        except ValueError:
            inside = False
        if inside:
            ids.append(os.path.relpath(path, CARDS_FOLDER).replace('\\', '/'))
    return _expand_card_ids(ids)


def retain_card_file_locks(*paths):
    """Hold resolved move IDs through writer cleanup; never wait while expanding its set."""
    retained = _file_locks.get()
    if retained is None:
        return  # Standalone intent preparation has no enclosing file operation.
    acquired_locks = {}
    try:
        for card_id in _file_card_ids(paths):
            if card_id in retained:
                continue
            acquired, lock = try_acquire_card_lock(card_id)
            if not acquired:
                raise RuntimeError('角色文件正在使用，请重试')
            acquired_locks[card_id] = lock
    except BaseException:
        for lock in reversed(list(acquired_locks.values())):
            release_card_lock(lock)
        raise
    retained.update(acquired_locks)


@contextmanager
def card_file_locks(*paths):
    """Protect intent publication through file commit, including non-HTTP writers."""
    with card_locks(_file_card_ids(paths)):
        yield


def card_busy_result(card_id):
    return {
        'success': False,
        'status': 'card_busy',
        'error': '角色卡正在被其他操作使用，请稍后重试',
        'card_id': str(card_id or ''),
        'card_busy': True,
    }


def request_card_locks(func):
    """为卡片写入类 Flask 接口取得涉及卡片的锁，保持批量顺序避免死锁。"""
    @wraps(func)
    def wrapped(*args, **kwargs):
        from flask import request

        try:
            payload = request.get_json(silent=True) or {}
        except (TypeError, ValueError):
            payload = {}

        raw_ids = payload.get('card_ids', []) if isinstance(payload, dict) else []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        if not isinstance(raw_ids, (list, tuple, set)):
            raw_ids = []
        if isinstance(payload, dict):
            single_id = payload.get('card_id') or payload.get('id')
            if single_id:
                raw_ids = [*raw_ids, single_id]
            if payload.get('version_id'):
                raw_ids.append(payload['version_id'])

            for scope_key in ('folder_path', 'source_path', 'old_path'):
                scope_id = payload.get(scope_key)
                if scope_id:
                    raw_ids.append(scope_id)

            # Compute fixed destinations before taking any lock. Recovery uses
            # both IDs, and synchronous hooks may immediately write the new ID.
            moves = []
            if single_id and isinstance(payload.get('new_filename'), str):
                moves.append((single_id, posixpath.join(
                    posixpath.dirname(_normalize_card_id(single_id)), payload['new_filename'])))
            if payload.get('old_path') and isinstance(payload.get('new_name'), str):
                moves.append((payload['old_path'], posixpath.join(
                    posixpath.dirname(_normalize_card_id(payload['old_path'])), payload['new_name'])))
            if payload.get('source_path') and 'target_parent_path' in payload:
                parent = payload.get('target_parent_path') or ''
                parent = '' if parent == '根目录' else _normalize_card_id(parent)
                moves.append((payload['source_path'], posixpath.join(
                    parent, posixpath.basename(_normalize_card_id(payload['source_path'])))))
            if single_id and isinstance(payload.get('bundle_name'), str):
                source = _normalize_card_id(single_id)
                moves.append((source, posixpath.join(posixpath.dirname(source),
                    payload['bundle_name'].strip(), posixpath.basename(source))))
            for source, destination in moves:
                source = _normalize_card_id(source)
                for affected_id in _expand_card_ids([source]):
                    if affected_id == source or affected_id.startswith(source + '/'):
                        raw_ids.append(destination + affected_id[len(source):])

        form_card_id = request.form.get('card_id') or request.form.get('id')
        if form_card_id:
            raw_ids = [*raw_ids, form_card_id]

        card_ids = _expand_card_ids(raw_ids)
        with card_locks(card_ids):
            with file_intent_scope():
                return func(*args, **kwargs)

    return wrapped


def card_operation_locked(func):
    """给服务层单卡文件操作使用的阻塞式锁装饰器。"""
    @wraps(func)
    def wrapped(card_id, *args, **kwargs):
        with card_locks(_expand_card_ids([card_id])):
            with file_intent_scope():
                return func(card_id, *args, **kwargs)

    return wrapped
