"""协调路径变更和索引读取、备注保存对这些路径的使用。"""
import os
import threading
from contextlib import contextmanager

from core.utils.filesystem import filesystem_path_bucket


PATH_BUSY = '目录或文件正在更新，请刷新后重试'
PATH_RETRY_SECONDS = 0.5
_guard = threading.Lock()
_active_shared = set()
_active_exclusive = set()
_global_readers = set()
_observations = set()


class PathOperationBusy(RuntimeError):
    pass


def _overlaps(left, right):
    return (left == right or left.startswith(right.rstrip(os.sep) + os.sep)
            or right.startswith(left.rstrip(os.sep) + os.sep))


def _path_keys(paths):
    return frozenset(filesystem_path_bucket(os.path.abspath(path)) for path in paths if path)


def _groups_overlap(left, right):
    return any(_overlaps(key, path) for key in left for path in right)


class _PathObservation:
    def __init__(self, keys):
        self.keys = keys
        self.changed = any(self.overlaps(active) for active, _ in _active_exclusive)

    def overlaps(self, keys):
        return (self.keys is None and bool(keys)) or _groups_overlap(self.keys or (), keys)

    @contextmanager
    def pin(self):
        """原子核验观察结果并阻止新的路径变更，直至投影提交。"""
        claim = self.keys, object()
        with _guard:
            valid = not self.changed
            if valid and self.keys is not None:
                _active_shared.add(claim)
            elif valid:
                _global_readers.add(claim)
        try:
            yield valid
        finally:
            if valid:
                with _guard:
                    (_global_readers if self.keys is None else _active_shared).remove(claim)


@contextmanager
def observe_path_changes(*paths, all_paths=False):
    """允许文件读取期间的修改，但对应读取结果不能提交。"""
    with _guard:
        observation = _PathObservation(None if all_paths else _path_keys(paths))
        _observations.add(observation)
    try:
        yield observation
    finally:
        with _guard:
            _observations.remove(observation)


@contextmanager
def path_operation(*paths, exclusive=True):
    """文件移动期间排斥重叠路径的索引读取及备注保存。"""
    # 目标文件的父目录可能尚未创建。保守处理 Windows 大小写别名，以便保护覆盖整个移动过程。
    keys = _path_keys(paths)
    active = _active_exclusive if exclusive else _active_shared
    claim = keys, object()
    with _guard:
        conflicts = _active_exclusive | _active_shared if exclusive else _active_exclusive
        acquired = not (exclusive and keys and _global_readers) and not any(
            _groups_overlap(keys, group) for group, _ in conflicts)
        if acquired:
            active.add(claim)
            if exclusive:
                for observation in _observations:
                    if observation.overlaps(keys):
                        observation.changed = True
    try:
        yield acquired
    finally:
        if acquired:
            with _guard:
                active.remove(claim)
