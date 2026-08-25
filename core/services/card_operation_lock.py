"""角色卡级别的非阻塞操作锁。"""

from contextlib import contextmanager
from functools import wraps
import threading

from core.context import ctx


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
    if not normalized_ids:
        return []

    cache = getattr(owner, 'cache', None)
    id_map = getattr(cache, 'id_map', None)
    if not isinstance(id_map, dict):
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

            for scope_key in ('folder_path', 'source_path', 'old_path'):
                scope_id = payload.get(scope_key)
                if scope_id:
                    raw_ids.append(scope_id)

        form_card_id = request.form.get('card_id') or request.form.get('id')
        if form_card_id:
            raw_ids = [*raw_ids, form_card_id]

        card_ids = _expand_card_ids(raw_ids)
        held_locks = []
        try:
            for card_id in card_ids:
                acquired, lock = try_acquire_card_lock(card_id, blocking=True)
                if not acquired:
                    # blocking=True 下通常不会走到这里，保留安全兜底。
                    for held in reversed(held_locks):
                        release_card_lock(held)
                    return card_busy_result(card_id)
                held_locks.append(lock)
            return func(*args, **kwargs)
        finally:
            for lock in reversed(held_locks):
                release_card_lock(lock)

    return wrapped


def card_operation_locked(func):
    """给服务层单卡文件操作使用的阻塞式锁装饰器。"""
    @wraps(func)
    def wrapped(card_id, *args, **kwargs):
        held_locks = []
        for affected_id in _expand_card_ids([card_id]):
            acquired, lock = try_acquire_card_lock(affected_id, blocking=True)
            if not acquired:
                for held in reversed(held_locks):
                    release_card_lock(held)
                return card_busy_result(card_id)
            held_locks.append(lock)
        try:
            return func(card_id, *args, **kwargs)
        finally:
            for lock in reversed(held_locks):
                release_card_lock(lock)

    return wrapped
