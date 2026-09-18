"""数据目录的进程级独占锁。

`core/data/ui_store.py` 里的 `_UI_DATA_LOCK` 只能串行化**同一个进程内**的
读写。若同一份 data/ 被两个进程打开（例如用户重复启动、打包版与源码版
同时运行、Flask debug reloader 的双进程），那把锁完全失效，两个进程会互相
覆盖 ui_data.json。

这里用一个带 OS 级文件锁的锁文件来阻止这种情况：第二个进程启动时会明确
报错退出，而不是静默地破坏数据。
"""

import atexit
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK_FILE_NAME = 'st_manager.lock'
_lock_handle = None
_lock_path = ''


class DataDirectoryLockError(RuntimeError):
    """无法取得数据目录独占锁（通常意味着已有实例在运行）。"""


def _try_lock_handle(handle):
    """对已打开的文件句柄尝试加非阻塞独占锁。

    Windows 使用 msvcrt.locking，POSIX 使用 fcntl.flock。
    返回 True 表示取得锁。
    """
    try:
        if os.name == 'nt':
            import msvcrt

            handle.seek(0)
            # 确保文件至少有一个字节，locking 才能作用于有效范围。
            handle.write('\0')
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    except ImportError:  # pragma: no cover - 平台缺少锁模块时退化为不锁
        logger.warning('当前平台缺少文件锁模块，跳过数据目录独占检查。')
        return True


def _unlock_handle(handle):
    if handle is None:
        return
    try:
        if os.name == 'nt':
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def acquire_data_directory_lock(lock_dir):
    """尝试独占 lock_dir，成功返回 True。

    重复调用（已持有锁）直接返回 True，便于幂等初始化。
    """
    global _lock_handle, _lock_path

    if _lock_handle is not None:
        return True

    directory = Path(lock_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(f'无法创建锁目录 {directory}: {exc}，跳过独占检查。')
        return True

    lock_path = directory / _LOCK_FILE_NAME
    try:
        handle = open(lock_path, 'a+', encoding='utf-8')
    except OSError as exc:
        logger.warning(f'无法打开锁文件 {lock_path}: {exc}，跳过独占检查。')
        return True

    if not _try_lock_handle(handle):
        handle.close()
        return False

    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except OSError:
        pass

    _lock_handle = handle
    _lock_path = str(lock_path)
    atexit.register(release_data_directory_lock)
    return True


def release_data_directory_lock():
    """释放数据目录锁（幂等）。"""
    global _lock_handle, _lock_path

    handle = _lock_handle
    _lock_handle = None
    if handle is None:
        return

    _unlock_handle(handle)
    try:
        handle.close()
    except OSError:
        pass

    # 锁文件本身保留也无害，但尽量清理。
    if _lock_path and os.path.exists(_lock_path):
        try:
            os.remove(_lock_path)
        except OSError:
            pass
    _lock_path = ''


def is_data_directory_locked():
    """当前进程是否持有数据目录锁。"""
    return _lock_handle is not None
