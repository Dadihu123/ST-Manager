"""路径归属判断工具。

仓库里原本有 4 份「路径是否位于某个根目录内」的实现（chats / world_info /
system 各一份函数定义，cards 一处内联），语义存在细微差异。这里统一收敛为
单一实现，避免新增接口时再复制一份。
"""

import os


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
