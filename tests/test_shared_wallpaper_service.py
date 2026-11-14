import sys
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.services.shared_wallpaper_service import SharedWallpaperService


def _write_image(path: Path, size=(64, 32), color=(12, 34, 56)):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', size, color)
    image.save(path)


def test_load_library_merges_builtin_and_persisted_items(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {
                'user-wallpaper': {
                    'id': 'user-wallpaper',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/user.png',
                    'filename': 'user.png',
                    'width': 100,
                    'height': 80,
                    'mtime': 123,
                    'created_at': 120,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': 'user-wallpaper',
            'preview_wallpaper_id': '',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    payload = service.load_library()

    assert payload['manager_wallpaper_id'] == 'user-wallpaper'
    assert payload['preview_wallpaper_id'] == ''
    assert sorted(payload['items']) == ['builtin:space/stars.png', 'user-wallpaper']
    assert payload['items']['builtin:space/stars.png'] == {
        'id': 'builtin:space/stars.png',
        'source_type': 'builtin',
        'file': 'static/assets/wallpapers/builtin/space/stars.png',
        'filename': 'stars.png',
        'width': 640,
        'height': 360,
        'mtime': int(builtin_path.stat().st_mtime),
        'created_at': int(builtin_path.stat().st_mtime),
        'origin_package_id': '',
        'origin_variant_id': '',
    }


def test_load_library_preserves_builtin_selection_ids(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': 'builtin:space/stars.png',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    first_payload = service.load_library()
    second_payload = service.load_library()

    assert first_payload['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert first_payload['preview_wallpaper_id'] == 'builtin:space/stars.png'
    assert second_payload['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert second_payload['preview_wallpaper_id'] == 'builtin:space/stars.png'


def test_import_wallpaper_preserves_existing_builtin_manager_selection(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    source = tmp_path / 'fixtures' / 'sunset.png'
    _write_image(source, size=(800, 600))

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    item = service.import_wallpaper(str(source), selection_target='preview')
    payload = service.load_library()

    assert item['id'] == payload['preview_wallpaper_id']
    assert payload['manager_wallpaper_id'] == 'builtin:space/stars.png'


def test_select_wallpaper_preserves_existing_builtin_manager_selection(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    imported_path = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview-bg.png'
    _write_image(imported_path, size=(800, 600))
    imported_mtime = int(imported_path.stat().st_mtime)

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {
                'user-wallpaper': {
                    'id': 'user-wallpaper',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview-bg.png',
                    'filename': 'preview-bg.png',
                    'width': 800,
                    'height': 600,
                    'mtime': imported_mtime,
                    'created_at': imported_mtime,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    service.select_wallpaper('user-wallpaper', 'preview')
    payload = service.load_library()

    assert payload['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert payload['preview_wallpaper_id'] == 'user-wallpaper'


def test_select_builtin_wallpaper_persists_to_existing_store(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': '',
        }
    }
    saved_payloads = []

    def save_ui_data(data):
        stored = data.get('_shared_wallpaper_library_v1', {}).copy()
        saved_payloads.append(stored)
        return True

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=save_ui_data,
    )

    service.select_wallpaper('builtin:space/stars.png', 'manager')

    assert saved_payloads
    assert saved_payloads[-1]['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert service.load_library()['manager_wallpaper_id'] == 'builtin:space/stars.png'


def test_select_wallpaper_replaces_existing_builtin_manager_selection_with_imported_item(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    imported_path = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'manager-bg.png'
    _write_image(imported_path, size=(800, 600))
    imported_mtime = int(imported_path.stat().st_mtime)

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:manager': {
                    'id': 'imported:manager',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/manager-bg.png',
                    'filename': 'manager-bg.png',
                    'width': 800,
                    'height': 600,
                    'mtime': imported_mtime,
                    'created_at': imported_mtime,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    service.select_wallpaper('imported:manager', 'manager')

    assert service.load_library()['manager_wallpaper_id'] == 'imported:manager'


def test_import_wallpaper_replaces_existing_builtin_manager_selection_with_imported_item(tmp_path):
    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    source = tmp_path / 'fixtures' / 'manager-import.png'
    _write_image(source, size=(800, 600))

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    imported_item = service.import_wallpaper(str(source), selection_target='manager')

    assert service.load_library()['manager_wallpaper_id'] == imported_item['id']


def test_import_wallpaper_copies_manager_asset_and_updates_selection(tmp_path):
    source = tmp_path / 'fixtures' / 'sunset.png'
    _write_image(source, size=(800, 600))
    preserved_mtime = int(time.time()) - 3600
    os_utime = __import__('os').utime
    os_utime(source, (preserved_mtime, preserved_mtime))

    saved_payloads = []
    ui_data = {}

    def save_ui_data(data):
        saved_payloads.append(data.copy())
        return True

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=save_ui_data,
    )

    item = service.import_wallpaper(str(source), selection_target='manager', source_name='custom-name.png')
    payload = service.load_library()

    assert item['source_type'] == 'imported'
    assert item['filename'] == 'custom-name.png'
    assert item['file'].startswith('data/library/wallpapers/imported/')
    assert item['width'] == 800
    assert item['height'] == 600
    assert item['mtime'] == preserved_mtime
    assert item['created_at'] >= preserved_mtime + 3590
    assert payload['manager_wallpaper_id'] == item['id']
    assert payload['preview_wallpaper_id'] == ''
    assert payload['items'][item['id']] == item
    assert (tmp_path / item['file']).is_file()
    assert saved_payloads


def test_import_wallpaper_removes_invalid_copied_file(tmp_path):
    source = tmp_path / 'fixtures' / 'broken.png'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'not-an-image')

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: {},
        ui_data_saver=lambda data: True,
    )

    imported_dir = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported'
    package_dir = tmp_path / 'data' / 'library' / 'wallpapers' / 'package_embedded' / 'pkg-demo' / 'variant-main'

    item = service.import_wallpaper(str(source))
    package_item = service.import_wallpaper(
        str(source),
        package_id='pkg-demo',
        variant_id='variant-main',
    )

    assert item == {}
    assert package_item == {}
    assert not imported_dir.exists() or list(imported_dir.iterdir()) == []
    assert not package_dir.exists() or list(package_dir.iterdir()) == []


def test_import_wallpaper_copies_package_asset_and_updates_preview_selection(tmp_path):
    source = tmp_path / 'fixtures' / 'package-bg.png'
    _write_image(source, size=(320, 200))

    ui_data = {}
    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    item = service.import_wallpaper(
        str(source),
        selection_target='preview',
        package_id='pkg-demo',
        variant_id='variant-main',
    )
    payload = service.load_library()

    assert item['source_type'] == 'package_embedded'
    assert item['origin_package_id'] == 'pkg-demo'
    assert item['origin_variant_id'] == 'variant-main'
    assert item['file'].startswith('data/library/wallpapers/package_embedded/pkg-demo/variant-main/')
    assert payload['preview_wallpaper_id'] == item['id']
    assert payload['manager_wallpaper_id'] == ''
    assert (tmp_path / item['file']).is_file()


def test_migrate_legacy_backgrounds_registers_existing_manager_background(tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    _write_image(legacy_path, size=(1024, 768))

    ui_data = {
        'bg_url': '/assets/backgrounds/legacy-bg.png',
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    migrated = service.migrate_legacy_backgrounds()
    payload = service.load_library()

    assert migrated['manager_wallpaper_id']
    manager_item = payload['items'][migrated['manager_wallpaper_id']]
    assert manager_item['source_type'] == 'imported'
    assert manager_item['file'].startswith('data/library/wallpapers/imported/')
    assert manager_item['filename'] == 'legacy-bg.png'
    assert manager_item['width'] == 1024
    assert manager_item['height'] == 768
    assert payload['manager_wallpaper_id'] == migrated['manager_wallpaper_id']
    assert (tmp_path / manager_item['file']).is_file()


def test_migrate_legacy_backgrounds_reads_nested_settings_bg_url_and_preserves_preview_selection(tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    _write_image(legacy_path, size=(1024, 768))

    preview_path = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview-bg.png'
    _write_image(preview_path, size=(640, 360))
    preview_mtime = int(preview_path.stat().st_mtime)

    ui_data = {
        'settings': {
            'bg_url': '/assets/backgrounds/legacy-bg.png',
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview-bg.png',
                    'filename': 'preview-bg.png',
                    'width': 640,
                    'height': 360,
                    'mtime': preview_mtime,
                    'created_at': preview_mtime,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        },
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    migrated = service.migrate_legacy_backgrounds(ui_data)
    payload = service.load_library()

    assert migrated['manager_wallpaper_id']
    assert migrated['manager_wallpaper_id'] == payload['manager_wallpaper_id']
    assert payload['preview_wallpaper_id'] == 'imported:preview'
    assert payload['items'][payload['preview_wallpaper_id']]['filename'] == 'preview-bg.png'
    assert payload['items'][payload['manager_wallpaper_id']]['filename'] == 'legacy-bg.png'


def test_migrate_legacy_backgrounds_does_not_override_existing_manager_selection(tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    _write_image(legacy_path, size=(1024, 768))

    builtin_path = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    _write_image(builtin_path, size=(640, 360))

    ui_data = {
        'bg_url': '/assets/backgrounds/legacy-bg.png',
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        },
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    migrated = service.migrate_legacy_backgrounds(ui_data)
    payload = service.load_library()

    assert migrated['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert payload['manager_wallpaper_id'] == 'builtin:space/stars.png'
    imported_items = [
        item
        for item in payload['items'].values()
        if item['source_type'] == 'imported' and item['filename'] == 'legacy-bg.png'
    ]
    assert imported_items == []


def test_migrate_legacy_backgrounds_is_idempotent_for_same_legacy_file(tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    _write_image(legacy_path, size=(1024, 768))

    ui_data = {
        'bg_url': '/assets/backgrounds/legacy-bg.png',
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    first_payload = service.migrate_legacy_backgrounds(ui_data)
    second_payload = service.migrate_legacy_backgrounds(ui_data)

    assert first_payload['manager_wallpaper_id']
    assert second_payload['manager_wallpaper_id'] == first_payload['manager_wallpaper_id']
    imported_items = [
        item for item in second_payload['items'].values()
        if item['source_type'] == 'imported' and item['filename'] == 'legacy-bg.png'
    ]
    assert len(imported_items) == 1


def test_migrate_legacy_backgrounds_is_idempotent_when_first_import_uses_suffixed_filename(tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    _write_image(legacy_path, size=(1024, 768))

    existing_import = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'legacy-bg.png'
    _write_image(existing_import, size=(320, 200), color=(200, 100, 50))

    ui_data = {
        'bg_url': '/assets/backgrounds/legacy-bg.png',
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    first_payload = service.migrate_legacy_backgrounds(ui_data)
    second_payload = service.migrate_legacy_backgrounds(ui_data)

    assert first_payload['manager_wallpaper_id']
    assert second_payload['manager_wallpaper_id'] == first_payload['manager_wallpaper_id']
    imported_items = [
        item for item in second_payload['items'].values()
        if item['source_type'] == 'imported' and item['width'] == 1024 and item['height'] == 768
    ]
    assert len(imported_items) == 1
    assert imported_items[0]['filename'] == 'legacy-bg_2.png'


def test_load_library_clears_stale_raw_selection_ids_without_restoring_them(tmp_path):
    preview_path = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview-bg.png'
    _write_image(preview_path, size=(640, 360))
    preview_mtime = int(preview_path.stat().st_mtime)

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview-bg.png',
                    'filename': 'preview-bg.png',
                    'width': 640,
                    'height': 360,
                    'mtime': preview_mtime,
                    'created_at': preview_mtime,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': 'missing-manager',
            'preview_wallpaper_id': 'imported:preview',
        }
    }

    service = SharedWallpaperService(
        project_root=str(tmp_path),
        internal_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    first_payload = service.load_library()
    second_payload = service.load_library()

    assert first_payload['manager_wallpaper_id'] == ''
    assert first_payload['preview_wallpaper_id'] == 'imported:preview'
    assert second_payload['manager_wallpaper_id'] == ''
    assert second_payload['preview_wallpaper_id'] == 'imported:preview'
