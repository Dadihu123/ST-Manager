"""SillyTavern「待定」桥接清单的持久化。

清单只记录「哪张库卡被复制进了酒馆角色目录」，卡片文件本身始终在酒馆那一侧。
写盘走「临时文件 + 原子替换」，读-改-写用进程内锁串行化，避免 UI 并发操作互相覆盖。
"""

import json
import logging
import os
import threading

from core.config import DB_FOLDER

logger = logging.getLogger(__name__)

STORE_FILENAME = 'st_bridge.json'
STORE_VERSION = 1

_lock = threading.RLock()


def _store_path():
    return os.path.join(DB_FOLDER, STORE_FILENAME)


def load_all():
    """读取全部登记项，返回 {staged_name: entry}。

    文件缺失、损坏或结构不对时一律按空清单处理，不让桥接功能把主流程带崩。
    """
    path = _store_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning('读取 %s 失败，按空清单处理: %s', STORE_FILENAME, exc)
        return {}

    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {str(key): value for key, value in items.items() if isinstance(value, dict)}


def save_all(items):
    """整表写回（原子替换）。"""
    payload = {'version': STORE_VERSION, 'items': dict(items or {})}
    path = _store_path()
    temp_path = path + '.tmp'
    with _lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temp_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            os.replace(temp_path, path)
            return True
        except OSError as exc:
            logger.error('写入 %s 失败: %s', STORE_FILENAME, exc)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False


def get(staged_name):
    """按待定文件名取登记项，没有则返回 None。"""
    return load_all().get(str(staged_name))


def put(staged_name, entry):
    """新增或覆盖一条登记项。"""
    with _lock:
        items = load_all()
        items[str(staged_name)] = dict(entry or {})
        return save_all(items)


def update(staged_name, **fields):
    """局部更新一条登记项，不存在时返回 False。"""
    with _lock:
        items = load_all()
        entry = items.get(str(staged_name))
        if entry is None:
            return False
        entry.update(fields)
        items[str(staged_name)] = entry
        return save_all(items)


def remove(staged_name):
    """删除一条登记项，不存在时返回 False。"""
    with _lock:
        items = load_all()
        if str(staged_name) not in items:
            return False
        items.pop(str(staged_name), None)
        return save_all(items)
