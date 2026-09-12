import os
from typing import Any, Callable, Dict, List

from core.config import BASE_DIR
from core.services.st_client import STClient


MANAGER_FIELD_LABELS = {
    'cards_dir': '角色卡存储路径',
    'world_info_dir': '世界书存储路径',
    'chats_dir': '聊天记录路径',
    'resources_dir': '资源文件夹路径',
    'presets_dir': '预设路径',
    'regex_dir': '正则脚本路径',
    'scripts_dir': 'ST 脚本路径',
    'quick_replies_dir': '快速回复路径',
}

FIELD_RESOURCE_TYPES = {
    'cards_dir': 'characters',
    'world_info_dir': 'worlds',
    'chats_dir': 'chats',
    'presets_dir': 'presets',
    'regex_dir': 'regex',
    'scripts_dir': 'scripts',
    'quick_replies_dir': 'quick_replies',
}

BLOCKED_ACTIONS_BY_RESOURCE = {
    'characters': 'sync_characters',
    'chats': 'sync_chats',
    'worlds': 'sync_worlds',
    'presets': 'sync_presets',
    'regex': 'sync_regex',
    'quick_replies': 'sync_quick_replies',
}


def _clean_path(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    cleaned = value.strip().strip('"').strip("'")
    return os.path.normpath(cleaned) if cleaned else ''


def _resolve_manager_path(raw_path: Any, base_dir: str) -> str:
    cleaned = _clean_path(raw_path)
    if not cleaned:
        return ''
    if os.path.isabs(cleaned):
        return os.path.normpath(cleaned)
    return os.path.normpath(os.path.join(base_dir, cleaned))


def _normalize_compare_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _resolve_st_install_root(st_data_dir: str, default_user_dir: str) -> str:
    if default_user_dir:
        parent = os.path.dirname(default_user_dir)
        if os.path.basename(parent).lower() == 'data':
            return os.path.dirname(parent)

    normalized = _clean_path(st_data_dir)
    if not normalized:
        return ''

    base = os.path.basename(normalized).lower()
    if base == 'default-user':
        data_dir = os.path.dirname(normalized)
        if os.path.basename(data_dir).lower() == 'data':
            return os.path.dirname(data_dir)
    if base == 'data':
        return os.path.dirname(normalized)
    return normalized


def _path_relation(manager_path: str, st_path: str) -> str:
    if not manager_path or not st_path:
        return ''

    normalized_manager = _normalize_compare_path(manager_path)
    normalized_st = _normalize_compare_path(st_path)
    if normalized_manager == normalized_st:
        return 'same'

    try:
        common = os.path.commonpath([normalized_manager, normalized_st])
    except ValueError:
        return ''

    if common == normalized_st:
        return 'manager_inside_st'
    if common == normalized_manager:
        return 'st_inside_manager'
    return ''


def _message_for(field: str, resource_type: str) -> str:
    if field == 'chats_dir':
        return '当前聊天记录路径与 SillyTavern chats 目录重叠，同步聊天时可能覆盖同名聊天目录，因此聊天同步已被禁用。'
    if field == 'resources_dir':
        return '当前资源根目录与 SillyTavern 核心目录重叠，可能导致 ST-Manager 资源与酒馆运行目录混用。'
    return f'当前路径与 SillyTavern {resource_type} 目录重叠，ST-Manager 的独立目录结构可能与酒馆目录混用。'


def _severity_for(field: str) -> str:
    return 'danger' if field == 'chats_dir' else 'warning'


def _build_conflict(
    field: str,
    manager_path: str,
    st_path: str,
    relation: str,
    resource_type: str,
) -> Dict[str, Any]:
    return {
        'field': field,
        'label': MANAGER_FIELD_LABELS[field],
        'manager_path': os.path.normpath(manager_path),
        'st_path': os.path.normpath(st_path),
        'resource_type': resource_type,
        'severity': _severity_for(field),
        'relation': relation,
        'message': _message_for(field, resource_type),
    }


def evaluate_st_path_safety(
    config: Dict[str, Any],
    *,
    base_dir: str = BASE_DIR,
    st_client_factory: Callable[..., Any] = STClient,
) -> Dict[str, Any]:
    draft = dict(config or {})
    st_data_dir = _clean_path(draft.get('st_data_dir', ''))
    result = {
        'risk_level': 'none',
        'risk_summary': '当前路径配置安全。',
        'conflicts': [],
        'blocked_actions': [],
    }
    if not st_data_dir:
        return result

    st_user_handle = draft.get('st_user_handle')
    if st_user_handle is None:
        client = st_client_factory(st_data_dir=st_data_dir)
    else:
        client = st_client_factory(
            st_data_dir=st_data_dir,
            st_user_handle=st_user_handle,
        )
    configured_st_path = _clean_path(getattr(client, 'st_data_dir', '') or st_data_dir)

    try:
        resolved_user_dir = _clean_path(client._normalize_default_user_dir(configured_st_path))
    except Exception:
        resolved_user_dir = ''

    st_root = _resolve_st_install_root(configured_st_path, resolved_user_dir)

    resource_targets = {}
    for field, resource_type in FIELD_RESOURCE_TYPES.items():
        try:
            resource_targets[field] = _clean_path(client.get_st_subdir(resource_type))
        except Exception:
            resource_targets[field] = ''

    core_roots = [
        _clean_path(os.path.join(st_root, 'public')) if st_root else '',
        resolved_user_dir,
        _clean_path(os.path.join(st_root, 'data')) if st_root else '',
        st_root,
    ]

    conflicts: List[Dict[str, Any]] = []
    blocked_actions = set()

    for field in MANAGER_FIELD_LABELS:
        manager_path = _resolve_manager_path(draft.get(field, ''), base_dir)
        if not manager_path:
            continue

        if field == 'resources_dir':
            for st_path in core_roots:
                relation = _path_relation(manager_path, st_path)
                if relation:
                    conflicts.append(_build_conflict(field, manager_path, st_path, relation, 'resources'))
                    break
            continue

        resource_type = FIELD_RESOURCE_TYPES.get(field, '')
        st_path = resource_targets.get(field, '')
        relation = _path_relation(manager_path, st_path)
        if not relation:
            continue

        conflicts.append(_build_conflict(field, manager_path, st_path, relation, resource_type))
        blocked_action = BLOCKED_ACTIONS_BY_RESOURCE.get(resource_type)
        if blocked_action:
            blocked_actions.add(blocked_action)

    if not conflicts:
        return result

    risk_level = 'danger' if any(item['severity'] == 'danger' for item in conflicts) else 'warning'
    sorted_actions = sorted(blocked_actions)
    if sorted_actions:
        sorted_actions = ['sync_all', *sorted_actions]

    return {
        'risk_level': risk_level,
        'risk_summary': f'检测到 {len(conflicts)} 个路径与 SillyTavern 目录重叠。',
        'conflicts': conflicts,
        'blocked_actions': sorted_actions,
    }
