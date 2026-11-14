"""文件系统监听启动失败不得拖垮后台服务初始化。

历史缺陷：``observer.start()`` 未被 try/except 包住，一旦在 FUSE（Android）
或受限文件系统上抛异常，会冒泡到 ``init_services`` 的最外层 try，导致其后的
索引 worker、监控调度器与插件 job worker 全部不启动。
"""

import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FailingObserver:
    """schedule 正常，start 抛异常（模拟 FUSE 上 inotify 不可用）。"""

    def __init__(self):
        self.stopped = False
        self.daemon = False

    def schedule(self, handler, path, recursive=False):
        return None

    def start(self):
        raise OSError('inotify_add_watch failed: Operation not permitted')

    def stop(self):
        self.stopped = True


class _OkObserver(_FailingObserver):
    def start(self):
        self.started = True


def _install_fake_watchdog(monkeypatch, observer_cls):
    observers_mod = types.ModuleType('watchdog.observers')
    observers_mod.Observer = observer_cls
    events_mod = types.ModuleType('watchdog.events')

    class _Handler:
        pass

    events_mod.FileSystemEventHandler = _Handler
    watchdog_mod = types.ModuleType('watchdog')

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_mod)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_mod)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_mod)


def test_start_fs_watcher_swallows_start_failure(monkeypatch, tmp_path):
    """start() 抛异常时只记 warning，不得向外冒泡。"""
    from core.services import scan_service

    created = {}

    def factory():
        created['observer'] = _FailingObserver()
        return created['observer']

    _install_fake_watchdog(monkeypatch, factory)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(tmp_path))
    monkeypatch.setattr(scan_service, 'load_config', lambda: {})

    # 不得抛异常
    scan_service.start_fs_watcher()

    assert created['observer'].stopped is True, '启动失败后应尝试 stop 清理'


def test_start_fs_watcher_starts_normally(monkeypatch, tmp_path):
    """正常路径：start() 被调用且不 stop。"""
    from core.services import scan_service

    created = {}

    def factory():
        created['observer'] = _OkObserver()
        return created['observer']

    _install_fake_watchdog(monkeypatch, factory)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(tmp_path))
    monkeypatch.setattr(scan_service, 'load_config', lambda: {})

    scan_service.start_fs_watcher()

    assert created['observer'].started is True
    assert created['observer'].stopped is False


def test_missing_watchdog_module_is_tolerated(monkeypatch, tmp_path):
    """watchdog 未安装时静默跳过，不抛异常。"""
    from core.services import scan_service

    for name in ('watchdog', 'watchdog.observers', 'watchdog.events'):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(tmp_path))

    scan_service.start_fs_watcher()  # 不抛即通过


def test_platform_without_watcher_skips_auto_scan(monkeypatch):
    """不支持文件监听的平台不得调用 start_fs_watcher。"""
    from core.services import scan_service

    called = []
    monkeypatch.setattr(scan_service, 'CAN_WATCH_FILESYSTEM', False)
    monkeypatch.setattr(scan_service, 'start_fs_watcher', lambda: called.append(True))
    monkeypatch.setattr(
        scan_service, 'current_config', types.SimpleNamespace(get=lambda k, d=None: True)
    )

    monkeypatch.setattr(scan_service.ctx, 'scan_active', False)
    monkeypatch.setattr(scan_service, '_should_run_startup_scan', lambda: False)
    monkeypatch.setattr(scan_service.threading, 'Thread', lambda **kwargs: types.SimpleNamespace(start=lambda: None))
    scan_service.start_background_scanner()
    assert scan_service.ctx.scan_active is True
    assert called == []
