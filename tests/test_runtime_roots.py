"""运行时路径根与宿主能力的断言（防止多端改动悄悄破坏桌面端）。

这些断言存在的理由：``BASE_DIR`` 同时是用户数据根、相对路径锚点、安全边界根；
一旦它的语义漂移，桌面端老用户的 config.json / data/ 会**静默失联**
（macOS 的数据就在 .app/Contents/MacOS 里），且没有任何报错。
"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core import config as config_module


# --- 源码态：两个根必须同值，且等于仓库根 ---


def test_source_mode_roots_are_repo_root():
    assert os.path.abspath(config_module.BASE_DIR) == str(ROOT)
    assert config_module.INTERNAL_DIR == config_module.BASE_DIR


def test_source_mode_derived_paths():
    assert config_module.CONFIG_FILE == os.path.join(config_module.BASE_DIR, 'config.json')
    assert config_module.DATA_DIR == os.path.join(config_module.BASE_DIR, 'data')
    assert config_module.DEFAULT_DB_PATH.endswith('cards_metadata.db')
    # DB / 缩略图 / 回收站 / 临时目录都必须落在 data/ 之下
    for path in (
        config_module.SYSTEM_DIR,
        config_module.DB_FOLDER,
        config_module.THUMB_FOLDER,
        config_module.TRASH_FOLDER,
        config_module.TEMP_DIR,
    ):
        assert os.path.abspath(path).startswith(os.path.abspath(config_module.DATA_DIR))


# --- 平台判定函数 ---


def test_platform_detection_helpers_exist_and_are_disjoint():
    assert config_module.is_ios_platform() in (True, False)
    assert config_module.is_android_platform() in (True, False)
    # 同一时刻不可能既是 iOS 又是 Android
    assert not (config_module.is_ios_platform() and config_module.is_android_platform())


def test_desktop_is_neither_ios_nor_android():
    """在桌面跑测试时，两个移动端判定都必须是 False。"""
    if sys.platform.startswith(('win', 'darwin')) or sys.platform.startswith('linux'):
        # 只有在没有 ANDROID_ROOT 的普通桌面环境才断言
        if 'ANDROID_ROOT' not in os.environ:
            assert config_module.is_ios_platform() is False
            assert config_module.is_android_platform() is False


# --- 8 个随包只读资源读点必须走 INTERNAL_DIR ---


def test_package_resources_resolve_under_internal_dir():
    """随包资源（static/templates）必须从 INTERNAL_DIR 解析，不能用 BASE_DIR。

    打包态下 BASE_DIR 是 exe 同级目录，其中没有 static/，用 BASE_DIR 会静默读到空。
    """
    from core.plugins import catalog, icons
    from core.utils import image

    checks = [
        # 插件图标精灵目录
        icons.icons_dir(),
        # 插件目录清单（包内兜底）
        catalog.bundled_catalog_path(),
        # 默认卡片图
        image.get_default_card_image_path(),
    ]

    internal = os.path.abspath(config_module.INTERNAL_DIR)
    for path in checks:
        assert os.path.abspath(str(path)).startswith(internal), f'{path} 不在 INTERNAL_DIR 下'


def test_flask_static_and_template_folders_under_internal_dir():
    from core import create_app

    app = create_app()
    internal = os.path.abspath(config_module.INTERNAL_DIR)

    assert os.path.abspath(app.static_folder).startswith(internal)
    assert os.path.abspath(app.template_folder).startswith(internal)
    # 静态 URL 前缀必须仍是 /static（模板与 JS 里有 50 处硬编码）
    assert app.static_url_path == '/static'


# --- F2 回归：内置壁纸必须从随包资源根读取 ---


def test_builtin_wallpapers_resolve_from_internal_root():
    """内置壁纸是随包资源，必须走 INTERNAL_DIR（历史上用了 BASE_DIR，打包后丢失）。"""
    from core.services.shared_wallpaper_service import SharedWallpaperService

    service = SharedWallpaperService()
    internal = os.path.abspath(config_module.INTERNAL_DIR)
    expected = os.path.join(internal, 'static', 'assets', 'wallpapers', 'builtin')

    assert os.path.abspath(service.internal_root) == internal
    assert os.path.isdir(expected), '内置壁纸目录应存在于源码树中'


def test_builtin_wallpapers_survive_simulated_frozen(tmp_path, monkeypatch):
    """模拟打包态：BASE_DIR 在别处、INTERNAL_DIR 指向资源根，内置壁纸仍要能找到。"""
    from PIL import Image

    from core.services import shared_wallpaper_service as svc_module

    # 造一个「资源根」：只含内置壁纸目录（放一张真实可解码的 PNG）
    internal = tmp_path / 'meipass'
    builtin = internal / 'static' / 'assets' / 'wallpapers' / 'builtin'
    builtin.mkdir(parents=True)
    Image.new('RGB', (8, 8), (12, 34, 56)).save(builtin / 'sample.png')

    # 造一个「exe 同级目录」：没有 static/
    data_root = tmp_path / 'exe_dir'
    data_root.mkdir()

    monkeypatch.setattr(svc_module, 'BASE_DIR', str(data_root))
    monkeypatch.setattr(svc_module, 'INTERNAL_DIR', str(internal))

    service = svc_module.SharedWallpaperService(project_root=None)
    service.ui_data_loader = lambda: {}
    service.ui_data_saver = lambda payload: None

    items = service._load_builtin_items()

    assert any(key.startswith('builtin:') for key in items), (
        '打包态下内置壁纸必须仍能枚举出来（F2 回归）'
    )
    assert items['builtin:sample.png']['file'] == 'static/assets/wallpapers/builtin/sample.png'
    from core.services.beautify_service import BeautifyService
    preview = BeautifyService(library_root=str(data_root / 'data/library/beautify'), internal_root=str(internal))
    assert preview.get_preview_asset_path(items['builtin:sample.png']['file']) == str(builtin / 'sample.png')


def test_termux_source_keeps_repository_roots(monkeypatch, tmp_path):
    monkeypatch.setenv('ANDROID_ROOT', '/system')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('STM_ANDROID_SHELL', raising=False)
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert config_module.is_android_platform()
    assert not config_module.is_embedded_android()
    assert config_module.resolve_base_dir() == str(ROOT)


def test_builtin_wallpaper_never_relativizes_across_drives(monkeypatch):
    import ntpath
    from core.services.shared_wallpaper_service import SharedWallpaperService
    service = SharedWallpaperService(project_root='D:/data', internal_root='C:/resources')
    service.internal_root = 'C:/resources'
    monkeypatch.setattr(os.path, 'relpath', ntpath.relpath)
    monkeypatch.setattr(service, '_read_image_metadata', lambda *a, **kw: dict(width=1, height=1, mtime=0, created_at=0))
    item = service._build_item('C:/resources/static/a.png', 'builtin', 'builtin:a.png')
    assert item['file'] == 'static/a.png'


def test_builtin_wallpapers_would_be_lost_if_read_from_base_dir(tmp_path, monkeypatch):
    """反证：若按旧实现从 BASE_DIR 读，模拟打包态下确实会一枚都拿不到。"""
    from PIL import Image

    from core.services import shared_wallpaper_service as svc_module

    internal = tmp_path / 'meipass'
    builtin = internal / 'static' / 'assets' / 'wallpapers' / 'builtin'
    builtin.mkdir(parents=True)
    Image.new('RGB', (8, 8), (12, 34, 56)).save(builtin / 'sample.png')

    data_root = tmp_path / 'exe_dir'
    data_root.mkdir()

    monkeypatch.setattr(svc_module, 'BASE_DIR', str(data_root))
    monkeypatch.setattr(svc_module, 'INTERNAL_DIR', str(internal))

    service = svc_module.SharedWallpaperService(project_root=None)
    # 强制回退到旧行为：从 project_root（= exe 同级）读内置壁纸
    service.internal_root = service.project_root
    assert service._load_builtin_items() == {}, '旧实现下打包版确实丢失内置壁纸'
