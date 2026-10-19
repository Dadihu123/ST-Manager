"""资源目录绑定的原子写入与恢复。

背景（见 docs/2026-10-19-card-resource-binding-and-save-failure-analysis.md）：
资源目录绑定以前散落在多个路由里，都是「load_ui_data() -> 改字典 -> save_ui_data()」
两段式写法，而且普遍忽略 ``save_ui_data()`` 的返回值。一旦写入失败（Windows 上
临时占用、降级状态、退化护栏），内存缓存却已经更新，于是出现「界面上有资源目录、
重启后绑定消失」。本模块把这类写入收口成：

1. 同一次「读 -> 改 -> 写」在 ``update_ui_data`` 的同一把锁内完成，消除并发丢失更新；
2. 写入结果必须显式检查，失败时返回结构化错误，调用方不得更新缓存；
3. 目录已存在但没有绑定时可以按名字恢复绑定，避免反复新建 ``名字_1`` 空目录。
"""

import logging
import os

from core.config import BASE_DIR, load_config
from core.consts import RESERVED_RESOURCE_NAMES
from core.data.ui_store import update_ui_data
from core.utils.filesystem import sanitize_filename

logger = logging.getLogger(__name__)

#: 内存缓存默认以「未绑定」占位，避免把空值写回 ui_data 后又被误判为绑定存在。
_UNSET = object()


def resolve_resource_root(cfg=None):
    """返回资源根目录绝对路径。"""
    config = cfg if isinstance(cfg, dict) else load_config()
    raw = config.get('resources_dir', 'data/assets/card_assets')
    if not isinstance(raw, str) or not raw:
        raw = 'data/assets/card_assets'
    return raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)


def resource_folder_abs_path(binding_value, resources_root=None):
    """把绑定值解析为绝对路径（兼容绝对路径与相对资源根）。"""
    normalized = str(binding_value or '').strip()
    if not normalized:
        return ''
    if os.path.isabs(normalized):
        return os.path.normpath(normalized)
    root = resources_root or resolve_resource_root()
    return os.path.normpath(os.path.join(root, normalized))


def build_unique_resource_folder_name(resource_root, preferred_name):
    """基于角色名生成安全且不重名的资源目录名。"""
    base_name = sanitize_filename(preferred_name or 'untitled').strip() or 'untitled'
    if base_name.lower() in RESERVED_RESOURCE_NAMES:
        base_name = f'card_{base_name}'

    candidate = base_name
    counter = 1
    while os.path.exists(os.path.join(resource_root, candidate)):
        candidate = f'{base_name}_{counter}'
        counter += 1
    return candidate


def read_card_resource_folder(card_ui_key, loader=None):
    """读取卡片当前绑定的资源目录名（不含路径校验）。"""
    from core.data.ui_store import load_ui_data

    read = loader or load_ui_data
    try:
        ui_data = read()
    except Exception as exc:  # noqa: BLE001 - 读失败按「未绑定」处理由调用方决定
        logger.error('读取 ui_data 失败，无法确认资源目录绑定: %s', exc)
        raise
    if not isinstance(ui_data, dict) or not card_ui_key:
        return ''
    entry = ui_data.get(card_ui_key)
    if not isinstance(entry, dict):
        return ''
    return str(entry.get('resource_folder') or '').strip()


def bind_card_resource_folder(
    card_ui_key,
    folder_name=None,
    *,
    allow_existing=False,
    loader=None,
    saver=None,
):
    """原子地写入卡片资源目录绑定。

    Args:
        card_ui_key: ui_data 顶层键（普通卡是卡片 ID，聚合包是 bundle 目录）。
        folder_name: 要绑定的目录名；传 ``None`` 表示保持既有绑定不变。
        allow_existing: 为 True 时，若已存在绑定则直接返回它（不覆盖）。

    Returns:
        dict: ``{'ok': bool, 'resource_folder': str, 'changed': bool, 'msg': str}``。
    """
    key = str(card_ui_key or '').strip().replace('\\', '/')
    if not key:
        return {'ok': False, 'resource_folder': '', 'changed': False, 'msg': '卡片标识缺失'}

    requested = None if folder_name is None else str(folder_name).strip()
    state = {'previous': '', 'current': '', 'changed': False}

    def _mutate(ui_data):
        entry = ui_data.get(key)
        if not isinstance(entry, dict):
            entry = {}
            ui_data[key] = entry
        previous = str(entry.get('resource_folder') or '').strip()
        current = previous if requested is None else requested
        if allow_existing and previous:
            current = previous
        state['previous'] = previous
        state['current'] = current
        if current != previous:
            entry['resource_folder'] = current
            state['changed'] = True
        return ui_data

    kwargs = {'allow_shrink': True}
    if loader is not None:
        kwargs['loader'] = loader
    if saver is not None:
        kwargs['saver'] = saver

    saved = update_ui_data(_mutate, **kwargs)
    if not saved:
        logger.error('资源目录绑定写入 ui_data 失败: key=%s folder=%s', key, state['current'])
        return {
            'ok': False,
            'resource_folder': state['previous'],
            'changed': False,
            'msg': '资源目录绑定保存失败（本地 UI 数据写入被拒绝或占用），请重试',
        }

    return {
        'ok': True,
        'resource_folder': state['current'],
        'changed': state['changed'],
        'msg': '',
    }


def restore_binding_if_folder_exists(card_ui_key, folder_name, *, resources_root=None):
    """磁盘上已有同名资源目录时，把绑定补回 ui_data。

    用于「绑定丢失但目录和图片都在」的场景：避免再次创建 ``名字_1`` 空目录。
    """
    candidate = str(folder_name or '').strip()
    if not candidate:
        return {'ok': False, 'resource_folder': '', 'changed': False, 'msg': ''}

    target = resource_folder_abs_path(candidate, resources_root)
    if not target or not os.path.isdir(target):
        return {'ok': False, 'resource_folder': '', 'changed': False, 'msg': ''}

    return bind_card_resource_folder(
        card_ui_key,
        candidate,
        allow_existing=True,
    )


def find_recoverable_resource_folder(
    preferred_name,
    *,
    card_ui_key='',
    resources_root=None,
    loader=None,
):
    """在资源根下寻找可安全接管（未被其他卡片绑定）的既有目录。

    只接受「由角色名清洗得到的基础名」及其 ``_N`` 变体，避免误接管其他卡片
    或系统目录。返回目录名，找不到则返回空字符串。
    """
    base_name = sanitize_filename(preferred_name or '').strip()
    if not base_name or base_name.lower() in RESERVED_RESOURCE_NAMES:
        return ''

    root = resources_root or resolve_resource_root()
    if not os.path.isdir(root):
        return ''

    try:
        from core.data.ui_store import load_ui_data

        ui_data = (loader or load_ui_data)()
    except Exception as exc:  # noqa: BLE001 - 读不到绑定时不接管，交给调用方新建
        logger.warning('无法读取 ui_data，跳过既有资源目录接管: %s', exc)
        return ''

    bound_by_others = set()
    if isinstance(ui_data, dict):
        for key, entry in ui_data.items():
            if not isinstance(key, str) or key.startswith('_'):
                continue
            if not isinstance(entry, dict):
                continue
            if key == card_ui_key:
                continue
            value = str(entry.get('resource_folder') or '').strip()
            if value:
                bound_by_others.add(value.replace('\\', '/').strip('/').lower())

    candidates = []
    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        logger.warning('列出资源根目录失败 %s: %s', root, exc)
        return ''

    lowered = base_name.lower()
    for name in entries:
        full_path = os.path.join(root, name)
        if not os.path.isdir(full_path):
            continue
        normalized = name.lower()
        if normalized != lowered and not (
            normalized.startswith(lowered + '_') and normalized[len(lowered) + 1:].isdigit()
        ):
            continue
        if normalized in bound_by_others:
            continue
        candidates.append(name)

    return sorted(candidates)[0] if candidates else ''

