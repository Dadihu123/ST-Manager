"""宿主图标名契约（设计文档 2.2 的「图标名契约（D4）」）。

插件在 `entries[].icon` 里只能写**宿主图标名**（如 `wand`、`bolt`），宿主负责把它
解析成正确的 sprite 与 `<use>` 引用。这样插件既不需要知道图标在哪个精灵里，也不会
因为宿主调整精灵划分而失效。

命名空间区分（硬规则）：
- 宿主图标名**不含** `/` 与 `.`（如 `wand`）
- 插件自带资源路径**必含** `/`（如 `assets/logo.svg`）

PyInstaller 打包态下 `static/` 是只读的 `_MEIPASS` 快照，因此这里从
`core.config.INTERNAL_DIR` 读取精灵，绝不写回 `static/`。
"""

import logging
import os
import re
import threading

from core.config import INTERNAL_DIR

logger = logging.getLogger(__name__)

ICONS_RELATIVE_DIR = os.path.join('static', 'icons')

#: 参与图标名解析的精灵（`loading-animation.svg` 是独立动效，不含 symbol）
HOST_ICON_SPRITES = ('ui.svg', 'detail.svg', 'sidebar.svg', 'preset.svg')

_ICON_ID_PATTERN = re.compile(r'id="icon-([^"]+)"')

_cache_lock = threading.RLock()
_cache = None


def icons_dir() -> str:
    """宿主图标精灵所在目录（打包态指向 `_MEIPASS`）。"""
    return os.path.join(str(INTERNAL_DIR), ICONS_RELATIVE_DIR)


def is_host_icon_name(value) -> bool:
    """判断取值是否是宿主图标名（而非插件自带资源路径）。

    `/` 或 `.` 一旦出现就视为资源路径：宿主图标名是扁平的 kebab-case 标识符。
    """
    text = str(value or '').strip()
    if not text:
        return False
    return '/' not in text and '\\' not in text and '.' not in text


def _load_index() -> dict:
    """解析 `static/icons/*.svg` 的 `id="icon-*"`，返回 `{名字: 记录}`。"""
    index = {}
    directory = icons_dir()
    for sprite in HOST_ICON_SPRITES:
        path = os.path.join(directory, sprite)
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                source = handle.read()
        except OSError as exc:
            logger.warning('读取图标精灵失败 %s: %s', sprite, exc)
            continue

        category = os.path.splitext(sprite)[0]
        for name in _ICON_ID_PATTERN.findall(source):
            # 同名图标在多个精灵中重复时以先声明者为准，避免 `<use>` 解析歧义
            index.setdefault(str(name), {
                'name': str(name),
                'sprite': sprite,
                'category': category,
                'keywords': [part for part in str(name).split('-') if part],
            })
    return index


def icon_index() -> dict:
    """进程内缓存的图标名索引（`{名字: 记录}`）。"""
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = _load_index()
        return _cache


def reset_cache_for_tests() -> None:
    """清空图标缓存（仅测试使用）。"""
    global _cache
    with _cache_lock:
        _cache = None


def list_host_icons() -> list:
    """全部宿主图标（按名字排序），供 `GET /api/plugins/ui-icons` 导出。"""
    index = icon_index()
    return [dict(index[name]) for name in sorted(index)]


def sprite_for_icon(name) -> str:
    """返回图标所属精灵文件名；未知名字返回空串。"""
    return str(icon_index().get(str(name or '').strip(), {}).get('sprite', ''))


def resolve_icon(name) -> dict:
    """返回 `{name, sprite, category, keywords}`；未知名字返回空 dict。"""
    record = icon_index().get(str(name or '').strip())
    return dict(record) if record else {}
