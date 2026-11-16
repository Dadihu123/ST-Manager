"""路径归属判断工具。

仓库里原本有 4 份「路径是否位于某个根目录内」的实现（chats / world_info /
system 各一份函数定义，cards 一处内联），语义存在细微差异。这里统一收敛为
单一实现，避免新增接口时再复制一份。
"""

import json
import os
import re


def is_under_base(path: str, base: str, *, resolve_symlinks: bool = False) -> bool:
    """判断 path 是否位于 base 目录内（含 base 自身）。

    Args:
        path: 待检查的路径。
        base: 允许的根目录。
        resolve_symlinks: 是否先用 realpath 解析符号链接与短路径。
            面向「用户可控路径的读写」时应开启，防止链接逃逸；
            仅做常规目录归属判断时保持默认 False，贴合既有行为。

    Returns:
        bool: 归一化后 path 等于 base 或位于其下时返回 True；
            空值、跨盘符（Windows）或非法路径一律返回 False。
    """
    if not path or not base:
        return False

    resolver = os.path.realpath if resolve_symlinks else os.path.abspath
    try:
        target = os.path.normcase(os.path.normpath(resolver(os.fspath(path))))
        root = os.path.normcase(os.path.normpath(resolver(os.fspath(base))))
    except (TypeError, ValueError, OSError):
        return False

    try:
        return os.path.commonpath([target, root]) == root
    except (TypeError, ValueError, OSError):
        return False


def is_protected_migration_path(path, base, active_roots=()):
    """迁移控制文件不可作为业务资源；仅放行当前配置已启用的 library 子根。"""
    workspace = os.path.join(base, 'data', 'migration')
    resolved_workspace = os.path.realpath(workspace)
    if not (is_under_base(path, workspace) or
            is_under_base(path, workspace, resolve_symlinks=True)):
        return False
    for root in active_roots:
        if not isinstance(root, str) or not root:
            continue
        root = os.path.abspath(os.path.join(base, root))
        resolved_root = os.path.realpath(root)
        if is_under_base(root, workspace):
            relative = os.path.relpath(root, workspace)
        elif is_under_base(resolved_root, resolved_workspace):
            relative = os.path.relpath(resolved_root, resolved_workspace)
        else:
            continue
        parts = relative.replace('\\', '/').split('/')
        if (len(parts) < 3 or not re.fullmatch(r'[0-9a-f]{32}', parts[0]) or
                parts[1] != 'library' or not is_under_base(root, workspace, resolve_symlinks=True)):
            continue
        # 只解析工作区前缀，保留类型边界，不能让 library/<类型> 的链接指向保护副本。
        # Android 的 /data/user/0 与 /data/data 必须在同一实际路径空间内比较。
        library = os.path.join(resolved_workspace, *parts[:3])
        if not is_under_base(resolved_root, library):
            continue
        journal = os.path.join(workspace, 'pending.json')
        if os.path.exists(journal):
            try:
                with open(journal, encoding='utf-8') as handle:
                    if json.load(handle).get('job') == parts[0]:
                        continue
            except (OSError, ValueError, AttributeError):
                return True
        if is_under_base(path, root, resolve_symlinks=True):
            return False
    return True


def require_business_write_path(path, base, cfg):
    """用户路径写入口共用迁移保护，避免旧快照等入口绕过暂存区保护。"""
    from core.config import RUNTIME_DIR_DEFAULTS

    roots = [cfg.get(key) for key in (*RUNTIME_DIR_DEFAULTS, 'st_openai_preset_dir')]
    roots.extend(cfg.get('allowed_abs_resource_roots') or [])
    if is_protected_migration_path(path, base, roots):
        raise ValueError('迁移暂存、待启用目录和保护副本禁止通过业务接口修改')
