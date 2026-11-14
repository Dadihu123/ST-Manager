"""宿主能力声明与「打开文件管理器」降级行为。"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.utils import host_capabilities


def test_desktop_has_all_capabilities():
    """桌面端能力必须全开，且与历史行为一致。"""
    if 'ANDROID_ROOT' in os.environ or sys.platform == 'ios':
        pytest.skip('非桌面环境')

    assert host_capabilities.is_mobile_platform() is False
    assert host_capabilities.CAN_OPEN_SYSTEM_FILE_MANAGER is True
    assert host_capabilities.CAN_SPAWN_SUBPROCESS is True
    assert host_capabilities.CAN_WATCH_FILESYSTEM is True
    assert host_capabilities.REQUIRES_SECURITY_SCOPED_DIRS is False


def test_describe_returns_all_keys():
    snapshot = host_capabilities.describe()
    assert set(snapshot) == {
        'is_mobile',
        'can_open_system_file_manager',
        'can_spawn_subprocess',
        'can_watch_filesystem',
        'can_run_background_service',
        'requires_security_scoped_dirs',
    }


def test_mobile_platform_disables_file_manager_and_watcher():
    """模拟移动端：文件管理器与文件监听都必须关闭。"""
    import importlib

    import core.config as config_module

    original = {
        'is_ios_platform': config_module.is_ios_platform,
        'is_android_platform': config_module.is_android_platform,
    }
    config_module.is_ios_platform = lambda: True
    config_module.is_android_platform = lambda: False
    try:
        reloaded = importlib.reload(host_capabilities)
        assert reloaded.CAN_OPEN_SYSTEM_FILE_MANAGER is False
        assert reloaded.CAN_SPAWN_SUBPROCESS is False
        assert reloaded.CAN_WATCH_FILESYSTEM is False
        assert reloaded.REQUIRES_SECURITY_SCOPED_DIRS is True
    finally:
        config_module.is_ios_platform = original['is_ios_platform']
        config_module.is_android_platform = original['is_android_platform']
        importlib.reload(host_capabilities)


# --- 6 个「打开文件管理器」入口在移动端必须返回结构化降级响应 ---


def _make_app():
    from flask import Flask

    from core.api.v1 import system as system_api

    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app, system_api


def test_open_folder_returns_unsupported_on_mobile(monkeypatch):
    app, system_api = _make_app()
    monkeypatch.setattr(system_api, 'CAN_OPEN_SYSTEM_FILE_MANAGER', False)

    calls = []
    monkeypatch.setattr(
        system_api.subprocess, 'Popen', lambda *a, **k: calls.append(a)
    )

    client = app.test_client()
    resp = client.post('/api/system_action', json={'action': 'open_folder'})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is False
    assert body['error'] == 'unsupported_on_platform'
    assert calls == [], '移动端不得尝试启动子进程'


def test_trash_open_returns_unsupported_on_mobile(monkeypatch, tmp_path):
    app, system_api = _make_app()
    monkeypatch.setattr(system_api, 'CAN_OPEN_SYSTEM_FILE_MANAGER', False)
    monkeypatch.setattr(system_api, 'TRASH_FOLDER', str(tmp_path))

    client = app.test_client()
    resp = client.post('/api/trash/open')

    body = resp.get_json()
    assert body['success'] is False
    assert body['error'] == 'unsupported_on_platform'


def test_open_path_returns_unsupported_on_mobile(monkeypatch, tmp_path):
    app, system_api = _make_app()
    target = tmp_path / 'sub'
    target.mkdir()
    monkeypatch.setattr(system_api, 'CAN_OPEN_SYSTEM_FILE_MANAGER', False)
    monkeypatch.setattr(system_api, '_resolve_safe_path', lambda p, relative_to_base=False: str(target))

    client = app.test_client()
    resp = client.post('/api/open_path', json={'path': str(target)})

    body = resp.get_json()
    assert body['success'] is False
    assert body['error'] == 'unsupported_on_platform'
