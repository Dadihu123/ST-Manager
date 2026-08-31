import json
import sys
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data.ui_store import get_beautify_library, set_beautify_library
from core.services import beautify_service as beautify_service_module
from core.services.beautify_service import BeautifyService
from core.services.shared_wallpaper_service import SharedWallpaperService


def _build_service(tmp_path, ui_data):
    library_root = tmp_path / 'data' / 'library' / 'beautify'
    return BeautifyService(
        library_root=library_root,
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: ui_data.clear() or ui_data.update(data),
    )


def _import_theme_for_package(service, tmp_path, filename='theme_pc.json', name='Demo', platform='pc'):
    theme_file = tmp_path / filename
    theme_file.write_text(
        json.dumps({'name': name, 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )
    return service.import_theme(str(theme_file), platform=platform)


def test_set_beautify_library_normalizes_package_variant_and_wallpaper_shape():
    ui_data = {}

    changed = set_beautify_library(
        ui_data,
        {
            'packages': {
                ' pkg_demo ': {
                    'id': ' pkg_demo ',
                    'name': ' Demo Theme ',
                    'variants': {
                        ' var_mobile ': {
                            'id': ' var_mobile ',
                            'platform': ' MOBILE ',
                            'theme_name': ' Demo Theme ',
                            'theme_file': 'data\\library\\beautify\\packages\\pkg_demo\\themes\\mobile.json',
                            'wallpaper_ids': [' wp_1 ', '', 'wp_1'],
                            'selected_wallpaper_id': ' wp_1 ',
                            'preview_hint': {
                                'needs_platform_review': 'yes',
                                'preview_accuracy': 'unknown',
                            },
                        },
                    },
                    'wallpapers': {
                        ' wp_1 ': {
                            'id': ' wp_1 ',
                            'variant_id': ' var_mobile ',
                            'file': 'data\\library\\beautify\\packages\\pkg_demo\\wallpapers\\mobile-1.webp',
                            'filename': ' demo.webp ',
                            'width': '1080',
                            'height': '1920',
                            'mtime': '123',
                        },
                    },
                },
            },
        },
    )

    assert changed is True

    payload = get_beautify_library(ui_data)
    package_info = payload['packages']['pkg_demo']
    variant_info = package_info['variants']['var_mobile']
    wallpaper_info = package_info['wallpapers']['wp_1']

    assert package_info['name'] == 'Demo Theme'
    assert variant_info['platform'] == 'mobile'
    assert variant_info['theme_file'] == 'data/library/beautify/packages/pkg_demo/themes/mobile.json'
    assert variant_info['wallpaper_ids'] == []
    assert variant_info['selected_wallpaper_id'] == ''
    assert variant_info['preview_hint']['needs_platform_review'] is True
    assert variant_info['preview_hint']['preview_accuracy'] == 'approx'
    assert wallpaper_info['variant_id'] == 'var_mobile'
    assert wallpaper_info['file'] == 'data/library/beautify/packages/pkg_demo/wallpapers/mobile-1.webp'
    assert wallpaper_info['filename'] == 'demo.webp'
    assert wallpaper_info['width'] == 1080
    assert wallpaper_info['height'] == 1920
    assert wallpaper_info['mtime'] == 123
    assert payload['updated_at'] > 0


def test_set_beautify_library_drops_package_local_variant_wallpaper_references_from_active_shape():
    ui_data = {}

    changed = set_beautify_library(
        ui_data,
        {
            'packages': {
                'pkg_demo': {
                    'id': 'pkg_demo',
                    'name': 'Demo Theme',
                    'variants': {
                        'var_mobile': {
                            'id': 'var_mobile',
                            'platform': 'mobile',
                            'theme_name': 'Demo Theme',
                            'theme_file': 'data/library/beautify/packages/pkg_demo/themes/mobile.json',
                            'wallpaper_ids': ['wp_legacy', 'package_embedded:shared123'],
                            'selected_wallpaper_id': 'wp_legacy',
                            'preview_hint': {
                                'needs_platform_review': False,
                                'preview_accuracy': 'approx',
                            },
                        },
                    },
                    'wallpapers': {
                        'wp_legacy': {
                            'id': 'wp_legacy',
                            'variant_id': 'var_mobile',
                            'file': 'data/library/beautify/packages/pkg_demo/wallpapers/mobile-1.webp',
                            'filename': 'mobile-1.webp',
                            'width': 1080,
                            'height': 1920,
                            'mtime': 123,
                        },
                    },
                },
            },
        },
    )

    assert changed is True

    payload = get_beautify_library(ui_data)
    variant_info = payload['packages']['pkg_demo']['variants']['var_mobile']

    assert variant_info['wallpaper_ids'] == ['package_embedded:shared123']
    assert variant_info['selected_wallpaper_id'] == ''


def test_set_beautify_library_normalizes_global_settings_screenshots_and_identity_overrides():
    ui_data = {}

    changed = set_beautify_library(
        ui_data,
        {
            'global_settings': {
                'wallpaper': {
                    'file': 'data\\library\\beautify\\global\\wallpapers\\main.webp',
                    'filename': ' main.webp ',
                    'width': '1080',
                    'height': '1920',
                    'mtime': '456',
                },
                'identities': {
                    'character': {
                        'name': ' Alice ',
                        'avatar_file': 'data\\avatars\\alice.png',
                    },
                    'user': {
                        'name': ' Bob ',
                        'avatar_file': 'data\\avatars\\bob.png',
                    },
                },
            },
            'packages': {
                ' pkg_demo ': {
                    'id': ' pkg_demo ',
                    'name': ' Demo Theme ',
                    'screenshots': {
                        ' shot_1 ': {
                            'id': ' shot_1 ',
                            'file': 'data\\library\\beautify\\packages\\pkg_demo\\screens\\01.webp',
                            'filename': ' 01.webp ',
                            'width': '1280',
                            'height': '720',
                            'mtime': '789',
                        },
                        '': {
                            'file': 'ignored.webp',
                        },
                    },
                    'identity_overrides': {
                        'character': {
                            'name': ' Carol ',
                            'avatar_file': 'data\\avatars\\carol.png',
                        },
                        'user': {
                            'name': ' Dave ',
                            'avatar_file': 'data\\avatars\\dave.png',
                        },
                    },
                    'variants': {},
                    'wallpapers': {},
                },
            },
        },
    )

    assert changed is True

    payload = get_beautify_library(ui_data)
    global_settings = payload['global_settings']
    global_wallpaper = global_settings['wallpaper']
    package_info = payload['packages']['pkg_demo']
    screenshot_info = package_info['screenshots']['shot_1']

    assert global_wallpaper['file'] == 'data/library/beautify/global/wallpapers/main.webp'
    assert global_wallpaper['filename'] == 'main.webp'
    assert global_wallpaper['width'] == 1080
    assert global_wallpaper['height'] == 1920
    assert global_wallpaper['mtime'] == 456
    assert global_settings['identities']['character'] == {
        'name': 'Alice',
        'avatar_file': 'data/avatars/alice.png',
    }
    assert global_settings['identities']['user'] == {
        'name': 'Bob',
        'avatar_file': 'data/avatars/bob.png',
    }
    assert screenshot_info == {
        'id': 'shot_1',
        'file': 'data/library/beautify/packages/pkg_demo/screens/01.webp',
        'filename': '01.webp',
        'width': 1280,
        'height': 720,
        'mtime': 789,
    }
    assert package_info['identity_overrides']['character'] == {
        'name': 'Carol',
        'avatar_file': 'data/avatars/carol.png',
    }
    assert package_info['identity_overrides']['user'] == {
        'name': 'Dave',
        'avatar_file': 'data/avatars/dave.png',
    }


def test_set_beautify_library_global_settings_affects_equality():
    ui_data = {}
    base_payload = {
        'global_settings': {
            'wallpaper': {
                'file': 'data\\library\\beautify\\global\\wallpapers\\main.webp',
                'filename': ' main.webp ',
                'width': '1080',
                'height': '1920',
                'mtime': '456',
            },
            'identities': {
                'character': {
                    'name': ' Alice ',
                    'avatar_file': 'data\\avatars\\alice.png',
                },
                'user': {
                    'name': ' Bob ',
                    'avatar_file': 'data\\avatars\\bob.png',
                },
            },
        },
        'packages': {
            'pkg_demo': {
                'id': 'pkg_demo',
                'name': 'Demo Theme',
                'variants': {},
                'wallpapers': {},
            },
        },
    }

    assert set_beautify_library(ui_data, base_payload) is True
    assert set_beautify_library(
        ui_data,
        {
            'global_settings': {
                'wallpaper': {
                    'file': 'data/library/beautify/global/wallpapers/main.webp',
                    'filename': 'main.webp',
                    'width': 1080,
                    'height': 1920,
                    'mtime': 456,
                },
                'identities': {
                    'character': {
                        'name': 'Alice',
                        'avatar_file': 'data/avatars/alice.png',
                    },
                    'user': {
                        'name': 'Bob',
                        'avatar_file': 'data/avatars/bob.png',
                    },
                },
            },
            'packages': {
                'pkg_demo': {
                    'id': 'pkg_demo',
                    'name': 'Demo Theme',
                    'variants': {},
                    'wallpapers': {},
                },
            },
        },
    ) is False

    assert set_beautify_library(
        ui_data,
        {
            'global_settings': {
                'wallpaper': {
                    'file': 'data/library/beautify/global/wallpapers/updated.webp',
                    'filename': 'updated.webp',
                    'width': 1080,
                    'height': 1920,
                    'mtime': 457,
                },
                'identities': {
                    'character': {
                        'name': 'Alice',
                        'avatar_file': 'data/avatars/alice.png',
                    },
                    'user': {
                        'name': 'Bob',
                        'avatar_file': 'data/avatars/bob.png',
                    },
                },
            },
            'packages': {
                'pkg_demo': {
                    'id': 'pkg_demo',
                    'name': 'Demo Theme',
                    'variants': {},
                    'wallpapers': {},
                },
            },
        },
    ) is True


def test_import_theme_creates_package_from_theme_name_and_detects_mobile_platform(tmp_path):
    library_root = tmp_path / 'data' / 'library' / 'beautify'
    ui_data = {}
    saved_payloads = []

    source_file = tmp_path / 'crying_移动端.json'
    source_file.write_text(
        json.dumps(
            {
                'name': 'crying',
                'main_text_color': '#ffffff',
                'custom_css': '.mes { color: red; }',
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    service = BeautifyService(
        library_root=library_root,
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: saved_payloads.append(json.loads(json.dumps(data, ensure_ascii=False))),
    )

    result = service.import_theme(str(source_file))

    assert result['package']['name'] == 'crying'
    assert result['package']['id'].startswith('pkg_')
    assert result['variant']['platform'] == 'mobile'
    assert result['variant']['theme_name'] == 'crying'
    assert result['variant']['preview_hint']['needs_platform_review'] is False
    assert result['variant']['preview_hint']['preview_accuracy'] == 'approx'

    saved_library = get_beautify_library(saved_payloads[-1])
    saved_package = saved_library['packages'][result['package']['id']]
    saved_variant = saved_package['variants'][result['variant']['id']]

    assert saved_variant['theme_file'].endswith('/themes/mobile.json')
    assert (tmp_path / saved_variant['theme_file']).exists()
    assert json.loads((tmp_path / saved_variant['theme_file']).read_text(encoding='utf-8'))['name'] == 'crying'


def test_import_theme_defaults_to_dual_and_marks_platform_review_when_guess_is_unclear(tmp_path):
    library_root = tmp_path / 'data' / 'library' / 'beautify'
    ui_data = {}

    source_file = tmp_path / 'mystery.json'
    source_file.write_text(
        json.dumps(
            {
                'name': '梧桐树下',
                'main_text_color': '#ffffff',
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    service = BeautifyService(
        library_root=library_root,
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: ui_data.clear() or ui_data.update(data),
    )

    result = service.import_theme(str(source_file))

    assert result['variant']['platform'] == 'dual'
    assert result['variant']['preview_hint']['needs_platform_review'] is True
    assert result['variant']['preview_hint']['preview_accuracy'] == 'base'


def test_import_theme_into_existing_package_creates_new_same_platform_variant(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first = _import_theme_for_package(
        service,
        tmp_path,
        filename='mono-pc.json',
        name='Mono Demo',
        platform='pc',
    )
    package_id = first['package']['id']

    second_theme = tmp_path / 'warm-pc.json'
    second_theme.write_text(
        json.dumps({'name': 'Warm Demo', 'main_text_color': '#ffeeaa'}, ensure_ascii=False),
        encoding='utf-8',
    )

    second = service.import_theme(str(second_theme), package_id=package_id, platform='pc')
    package_detail = service.get_package(package_id)

    assert second['package']['id'] == package_id
    assert second['variant']['id'] != first['variant']['id']
    assert len(package_detail['variants']) == 2
    assert sorted(variant['platform'] for variant in package_detail['variants'].values()) == ['pc', 'pc']


def test_import_theme_into_existing_package_keeps_older_same_platform_variant_untouched(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first = _import_theme_for_package(
        service,
        tmp_path,
        filename='first-pc.json',
        name='First Demo',
        platform='pc',
    )
    package_id = first['package']['id']
    original_variant_id = first['variant']['id']
    original_theme_file = first['variant']['theme_file']
    original_theme_path = tmp_path / original_theme_file
    original_theme_payload = json.loads(original_theme_path.read_text(encoding='utf-8'))

    second_theme = tmp_path / 'second-pc.json'
    second_theme.write_text(
        json.dumps({'name': 'Second Demo', 'main_text_color': '#dbeafe'}, ensure_ascii=False),
        encoding='utf-8',
    )

    second = service.import_theme(str(second_theme), package_id=package_id, platform='pc')
    package_detail = service.get_package(package_id)

    assert original_variant_id in package_detail['variants']
    assert package_detail['variants'][original_variant_id]['theme_file'] == original_theme_file
    assert json.loads(original_theme_path.read_text(encoding='utf-8')) == original_theme_payload
    assert second['variant']['theme_file'] != original_theme_file
    assert {variant['theme_name'] for variant in package_detail['variants'].values()} == {'First Demo', 'Second Demo'}


def test_import_theme_into_existing_package_persists_variant_name_through_reload_and_recovery(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first = _import_theme_for_package(
        service,
        tmp_path,
        filename='first-pc.json',
        name='First Demo',
        platform='pc',
    )
    package_id = first['package']['id']

    second_theme = tmp_path / 'named-pc.json'
    second_theme.write_text(
        json.dumps({'name': 'Named Demo', 'main_text_color': '#c084fc'}, ensure_ascii=False),
        encoding='utf-8',
    )

    second = service.import_theme(str(second_theme), package_id=package_id, platform='pc')
    second_variant_id = second['variant']['id']
    second_theme_file = second['variant']['theme_file']

    persisted_library = get_beautify_library(ui_data)
    assert persisted_library['packages'][package_id]['variants'][second_variant_id]['name'] == 'Named Demo'

    ui_data.clear()

    recovered_library = service.load_library()
    recovered_variants = recovered_library['packages'][package_id]['variants']
    recovered_named_variant = next(
        variant for variant in recovered_variants.values() if variant['theme_file'] == second_theme_file
    )
    assert recovered_named_variant['name'] == 'Named Demo'


def test_import_wallpaper_registers_shared_variant_wallpaper_and_selects_it(tmp_path):
    library_root = tmp_path / 'data' / 'library' / 'beautify'
    ui_data = {}

    theme_file = tmp_path / 'demo_pc.json'
    theme_file.write_text(
        json.dumps({'name': 'Demo PC', 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )

    wallpaper_file = tmp_path / 'wallpaper.png'
    Image.new('RGB', (1440, 900), '#334455').save(wallpaper_file)

    service = BeautifyService(
        library_root=library_root,
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: ui_data.clear() or ui_data.update(data),
    )
    imported_theme = service.import_theme(str(theme_file), platform='pc')

    result = service.import_wallpaper(
        imported_theme['package']['id'],
        imported_theme['variant']['id'],
        str(wallpaper_file),
    )

    assert result['wallpaper']['id'].startswith('package_embedded:')
    assert result['wallpaper']['source_type'] == 'package_embedded'
    assert result['wallpaper']['origin_package_id'] == imported_theme['package']['id']
    assert result['wallpaper']['origin_variant_id'] == imported_theme['variant']['id']
    assert result['wallpaper']['width'] == 1440
    assert result['wallpaper']['height'] == 900
    assert result['wallpaper']['file'].endswith(f"/{imported_theme['package']['id']}/{imported_theme['variant']['id']}/wallpaper.png")
    assert (tmp_path / result['wallpaper']['file']).exists()

    package_info = service.get_package(imported_theme['package']['id'])
    variant_info = package_info['variants'][imported_theme['variant']['id']]
    assert variant_info['wallpaper_ids'] == [result['wallpaper']['id']]
    assert variant_info['selected_wallpaper_id'] == result['wallpaper']['id']
    assert package_info['wallpapers'][result['wallpaper']['id']] == result['wallpaper']
    assert ui_data['_shared_wallpaper_library_v1']['items'][result['wallpaper']['id']] == result['wallpaper']


def test_get_package_hydrates_shared_wallpapers_for_variant_references(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Hydration Demo', platform='pc')

    wallpaper_file = tmp_path / 'hydrated.png'
    Image.new('RGB', (1280, 720), '#445566').save(wallpaper_file)
    imported_wallpaper = service.import_wallpaper(
        imported_theme['package']['id'],
        imported_theme['variant']['id'],
        str(wallpaper_file),
    )['wallpaper']

    package_detail = service.get_package(imported_theme['package']['id'])

    assert package_detail['wallpapers'][imported_wallpaper['id']] == imported_wallpaper


def test_build_sendable_theme_bundle_returns_theme_copy_and_normalized_name(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name=' Aurora Blue ')

    bundle = service.build_sendable_theme_bundle(
        imported_theme['package']['id'],
        imported_theme['variant']['id'],
    )

    assert bundle['package']['id'] == imported_theme['package']['id']
    assert bundle['variant']['id'] == imported_theme['variant']['id']
    assert bundle['theme_data']['name'] == 'Aurora Blue'
    assert bundle['theme_data'] is not bundle['variant']['theme_data']


def test_build_sendable_theme_bundle_rejects_missing_theme_name(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Nameless Demo')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']

    package_detail = service.get_package(package_id)
    theme_file = tmp_path / package_detail['variants'][variant_id]['theme_file']
    theme_file.write_text(json.dumps({'main_text_color': '#fff'}, ensure_ascii=False), encoding='utf-8')

    try:
        service.build_sendable_theme_bundle(package_id, variant_id)
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '当前变体主题缺少 name，无法发送到 ST'


def test_get_package_includes_variant_last_sent_to_st(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Timestamp Demo')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']
    ui_key = service.get_variant_send_state_key(package_id, variant_id)
    ui_data[ui_key] = {'last_sent_to_st': 1712362222.75}

    package_detail = service.get_package(package_id)

    assert package_detail['variants'][variant_id]['last_sent_to_st'] == 1712362222.75


def test_list_packages_uses_shared_variant_wallpaper_references_not_legacy_package_wallpapers(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Summary Demo', platform='pc')

    shared_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'package_embedded' / imported_theme['package']['id'] / imported_theme['variant']['id'] / 'selected.png'
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(shared_wallpaper)

    ui_data['_beautify_library_v1']['packages'][imported_theme['package']['id']]['variants'][imported_theme['variant']['id']]['wallpaper_ids'] = [
        'package_embedded:selected',
    ]
    ui_data['_beautify_library_v1']['packages'][imported_theme['package']['id']]['variants'][imported_theme['variant']['id']]['selected_wallpaper_id'] = 'package_embedded:selected'
    ui_data['_beautify_library_v1']['packages'][imported_theme['package']['id']]['wallpapers'] = {
        'wp_legacy': {
            'id': 'wp_legacy',
            'variant_id': imported_theme['variant']['id'],
            'file': 'data/library/beautify/packages/%s/wallpapers/legacy.png' % imported_theme['package']['id'],
            'filename': 'legacy.png',
            'width': 1080,
            'height': 1920,
            'mtime': 1,
        }
    }
    ui_data['_shared_wallpaper_library_v1'] = {
        'items': {
            'package_embedded:selected': {
                'id': 'package_embedded:selected',
                'source_type': 'package_embedded',
                'file': 'data/library/wallpapers/package_embedded/%s/%s/selected.png' % (
                    imported_theme['package']['id'],
                    imported_theme['variant']['id'],
                ),
                'filename': 'selected.png',
                'width': 1440,
                'height': 900,
                'mtime': int(shared_wallpaper.stat().st_mtime),
                'created_at': int(shared_wallpaper.stat().st_mtime),
                'origin_package_id': imported_theme['package']['id'],
                'origin_variant_id': imported_theme['variant']['id'],
            }
        },
        'manager_wallpaper_id': '',
        'preview_wallpaper_id': '',
    }

    package_summary = service.list_packages()[0]

    assert package_summary['wallpaper_count'] == 1
    assert package_summary['wallpaper_previews'] == [
        'data/library/wallpapers/package_embedded/%s/%s/selected.png' % (
            imported_theme['package']['id'],
            imported_theme['variant']['id'],
        )
    ]


def test_load_library_drops_stale_shared_wallpaper_ids_from_variant_state(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Stale Shared Demo', platform='pc')

    variant_id = imported_theme['variant']['id']
    package_id = imported_theme['package']['id']
    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['wallpaper_ids'] = [
        'package_embedded:missing',
        'package_embedded:live',
    ]
    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['selected_wallpaper_id'] = 'package_embedded:missing'
    ui_data['_shared_wallpaper_library_v1'] = {
        'items': {
            'package_embedded:live': {
                'id': 'package_embedded:live',
                'source_type': 'package_embedded',
                'file': 'data/library/wallpapers/package_embedded/%s/%s/live.png' % (package_id, variant_id),
                'filename': 'live.png',
                'width': 1440,
                'height': 900,
                'mtime': 1,
                'created_at': 1,
                'origin_package_id': package_id,
                'origin_variant_id': variant_id,
            }
        },
        'manager_wallpaper_id': '',
        'preview_wallpaper_id': '',
    }

    library = service.load_library()
    variant_info = library['packages'][package_id]['variants'][variant_id]
    persisted_variant = ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]

    assert variant_info['wallpaper_ids'] == ['package_embedded:live']
    assert variant_info['selected_wallpaper_id'] == ''
    assert persisted_variant['wallpaper_ids'] == ['package_embedded:live']
    assert persisted_variant['selected_wallpaper_id'] == ''


def test_load_library_recovers_package_embedded_shared_wallpaper_ids_from_disk(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Shared Demo', platform='pc')

    variant_id = imported_theme['variant']['id']
    package_id = imported_theme['package']['id']
    shared_wallpaper = (
        tmp_path
        / 'data'
        / 'library'
        / 'wallpapers'
        / 'package_embedded'
        / package_id
        / variant_id
        / 'recovered.png'
    )
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(shared_wallpaper)

    shared_service = SharedWallpaperService(
        project_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )
    recovered_wallpaper_id = shared_service._wallpaper_id_for_path(
        str(shared_wallpaper),
        prefix='package_embedded',
    )

    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['wallpaper_ids'] = [
        recovered_wallpaper_id,
    ]
    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['selected_wallpaper_id'] = recovered_wallpaper_id
    ui_data['_shared_wallpaper_library_v1'] = {
        'items': {},
        'manager_wallpaper_id': '',
        'preview_wallpaper_id': '',
    }

    library = service.load_library()
    variant_info = library['packages'][package_id]['variants'][variant_id]
    package_info = service.get_package(package_id)

    assert variant_info['wallpaper_ids'] == [recovered_wallpaper_id]
    assert variant_info['selected_wallpaper_id'] == recovered_wallpaper_id
    assert package_info['wallpapers'][recovered_wallpaper_id] == {
        'id': recovered_wallpaper_id,
        'source_type': 'package_embedded',
        'file': f'data/library/wallpapers/package_embedded/{package_id}/{variant_id}/recovered.png',
        'filename': 'recovered.png',
        'width': 1440,
        'height': 900,
        'mtime': int(shared_wallpaper.stat().st_mtime),
        'created_at': int(shared_wallpaper.stat().st_mtime),
        'origin_package_id': package_id,
        'origin_variant_id': variant_id,
    }


def test_update_variant_can_switch_selected_wallpaper_without_changing_platform(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Wallpaper Switch Demo', platform='pc')

    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']

    first_wallpaper = tmp_path / 'first.png'
    second_wallpaper = tmp_path / 'second.png'
    Image.new('RGB', (1280, 720), '#334455').save(first_wallpaper)
    Image.new('RGB', (1280, 720), '#556677').save(second_wallpaper)

    first_result = service.import_wallpaper(package_id, variant_id, str(first_wallpaper))
    second_result = service.import_wallpaper(package_id, variant_id, str(second_wallpaper))

    updated_variant = service.update_variant(
        package_id,
        variant_id,
        selected_wallpaper_id=first_result['wallpaper']['id'],
    )
    persisted_variant = ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]

    assert updated_variant['platform'] == 'pc'
    assert updated_variant['selected_wallpaper_id'] == first_result['wallpaper']['id']
    assert updated_variant['wallpaper_ids'] == [
        first_result['wallpaper']['id'],
        second_result['wallpaper']['id'],
    ]
    assert persisted_variant['selected_wallpaper_id'] == first_result['wallpaper']['id']


def test_update_variant_allows_same_platform_sibling_variants(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first = _import_theme_for_package(service, tmp_path, filename='first-pc.json', name='First Demo', platform='pc')
    package_id = first['package']['id']

    second_theme = tmp_path / 'second-mobile.json'
    second_theme.write_text(
        json.dumps({'name': 'Second Demo', 'main_text_color': '#dbeafe'}, ensure_ascii=False),
        encoding='utf-8',
    )
    second = service.import_theme(str(second_theme), package_id=package_id, platform='mobile')

    updated_variant = service.update_variant(package_id, second['variant']['id'], platform='pc')
    package_detail = service.get_package(package_id)

    assert updated_variant['platform'] == 'pc'
    assert updated_variant['theme_file'].endswith(f"/{second['variant']['id']}.json")
    assert sorted(variant['platform'] for variant in package_detail['variants'].values()) == ['pc', 'pc']


def test_update_variant_does_not_overwrite_existing_legacy_same_platform_theme_file(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    package_id = 'pkg_legacy_demo'
    themes_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'themes'
    themes_dir.mkdir(parents=True)
    pc_theme_path = themes_dir / 'pc.json'
    mobile_theme_path = themes_dir / 'mobile.json'
    pc_theme_path.write_text(
        json.dumps({'name': 'First Demo', 'main_text_color': '#ffffff'}, ensure_ascii=False),
        encoding='utf-8',
    )
    mobile_theme_path.write_text(
        json.dumps({'name': 'Second Demo', 'main_text_color': '#dbeafe'}, ensure_ascii=False),
        encoding='utf-8',
    )

    ui_data['_beautify_library_v1'] = {
        'packages': {
            package_id: {
                'id': package_id,
                'name': 'Legacy Demo',
                'cover_variant_id': 'var_pc_legacy',
                'variants': {
                    'var_pc_legacy': {
                        'id': 'var_pc_legacy',
                        'platform': 'pc',
                        'theme_name': 'First Demo',
                        'theme_file': f'data/library/beautify/packages/{package_id}/themes/pc.json',
                        'wallpaper_ids': [],
                        'selected_wallpaper_id': '',
                        'preview_hint': {
                            'needs_platform_review': False,
                            'preview_accuracy': 'approx',
                        },
                    },
                    'var_mobile_legacy': {
                        'id': 'var_mobile_legacy',
                        'platform': 'mobile',
                        'theme_name': 'Second Demo',
                        'theme_file': f'data/library/beautify/packages/{package_id}/themes/mobile.json',
                        'wallpaper_ids': [],
                        'selected_wallpaper_id': '',
                        'preview_hint': {
                            'needs_platform_review': False,
                            'preview_accuracy': 'approx',
                        },
                    },
                },
                'wallpapers': {},
                'screenshots': {},
                'identity_overrides': {},
            },
        },
    }

    first_theme_payload = json.loads(pc_theme_path.read_text(encoding='utf-8'))
    updated_variant = service.update_variant(package_id, 'var_mobile_legacy', platform='pc')
    package_detail = service.get_package(package_id)

    assert package_detail['variants']['var_pc_legacy']['theme_file'].endswith('/themes/pc.json')
    assert json.loads(pc_theme_path.read_text(encoding='utf-8')) == first_theme_payload
    assert updated_variant['theme_file'] != 'data/library/beautify/packages/pkg_legacy_demo/themes/pc.json'
    assert updated_variant['theme_file'].endswith('/themes/var_mobile_legacy.json')


def test_update_variant_preserves_sibling_safe_platform_after_disk_recovery(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first = _import_theme_for_package(service, tmp_path, filename='first-pc.json', name='First Demo', platform='pc')
    package_id = first['package']['id']

    second_theme = tmp_path / 'second-mobile.json'
    second_theme.write_text(
        json.dumps({'name': 'Second Demo', 'main_text_color': '#dbeafe'}, ensure_ascii=False),
        encoding='utf-8',
    )
    second = service.import_theme(str(second_theme), package_id=package_id, platform='mobile')

    updated_variant = service.update_variant(package_id, second['variant']['id'], platform='pc')
    assert updated_variant['theme_file'].endswith(f"/{second['variant']['id']}.json")

    ui_data.clear()

    recovered_library = service.load_library()
    recovered_variant = next(
        variant
        for variant in recovered_library['packages'][package_id]['variants'].values()
        if variant['theme_file'] == updated_variant['theme_file']
    )

    assert recovered_variant['platform'] == 'pc'


def test_get_global_settings_reads_preview_wallpaper_id_from_shared_library_even_when_beautify_state_has_stale_value(tmp_path):
    shared_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(shared_wallpaper)

    ui_data = {
        '_beautify_library_v1': {
            'global_settings': {
                'preview_wallpaper_id': 'stale:beautify',
                'wallpaper': {
                    'file': 'data/library/beautify/global/wallpapers/legacy.png',
                    'filename': 'legacy.png',
                    'width': 1080,
                    'height': 1920,
                    'mtime': 1,
                },
            },
            'packages': {},
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'width': 1440,
                    'height': 900,
                    'mtime': int(shared_wallpaper.stat().st_mtime),
                    'created_at': int(shared_wallpaper.stat().st_mtime),
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        },
    }
    service = _build_service(tmp_path, ui_data)

    settings = service.get_global_settings()

    assert settings['preview_wallpaper_id'] == 'imported:preview'
    assert settings['wallpaper']['id'] == 'imported:preview'
    assert settings['wallpaper']['file'] == 'data/library/wallpapers/imported/preview.png'
    assert settings['identities'] == {
        'character': {'name': '', 'avatar_file': ''},
        'user': {'name': '', 'avatar_file': ''},
    }


def test_update_global_settings_clear_wallpaper_clears_shared_preview_selection(tmp_path):
    shared_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#334455').save(shared_wallpaper)

    ui_data = {
        '_beautify_library_v1': {
            'global_settings': {},
            'packages': {},
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'width': 1440,
                    'height': 900,
                    'mtime': int(shared_wallpaper.stat().st_mtime),
                    'created_at': int(shared_wallpaper.stat().st_mtime),
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        },
    }
    service = _build_service(tmp_path, ui_data)

    settings = service.update_global_settings({'clear_wallpaper': True})

    assert settings['preview_wallpaper_id'] == ''
    assert settings['wallpaper'] == {
        'file': '',
        'filename': '',
        'width': 0,
        'height': 0,
        'mtime': 0,
    }
    assert ui_data['_shared_wallpaper_library_v1']['preview_wallpaper_id'] == ''


def test_get_global_settings_resolves_preview_wallpaper_from_shared_library(tmp_path):
    shared_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(shared_wallpaper)

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'width': 1440,
                    'height': 900,
                    'mtime': int(shared_wallpaper.stat().st_mtime),
                    'created_at': int(shared_wallpaper.stat().st_mtime),
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        }
    }
    service = _build_service(tmp_path, ui_data)

    settings = service.get_global_settings()

    assert settings['preview_wallpaper_id'] == 'imported:preview'
    assert settings['wallpaper'] == {
        'id': 'imported:preview',
        'source_type': 'imported',
        'file': 'data/library/wallpapers/imported/preview.png',
        'filename': 'preview.png',
        'width': 1440,
        'height': 900,
        'mtime': int(shared_wallpaper.stat().st_mtime),
        'created_at': int(shared_wallpaper.stat().st_mtime),
        'origin_package_id': '',
        'origin_variant_id': '',
    }
    assert settings['identities'] == {
        'character': {'name': '', 'avatar_file': ''},
        'user': {'name': '', 'avatar_file': ''},
    }


def test_get_global_settings_resolves_builtin_preview_wallpaper_from_shared_library_view(tmp_path):
    builtin_wallpaper = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    builtin_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1920, 1080), '#112244').save(builtin_wallpaper)

    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'builtin:space/stars.png',
        }
    }
    service = _build_service(tmp_path, ui_data)

    settings = service.get_global_settings()

    assert settings['preview_wallpaper_id'] == 'builtin:space/stars.png'
    assert settings['wallpaper'] == {
        'id': 'builtin:space/stars.png',
        'source_type': 'builtin',
        'file': 'static/assets/wallpapers/builtin/space/stars.png',
        'filename': 'stars.png',
        'width': 1920,
        'height': 1080,
        'mtime': int(builtin_wallpaper.stat().st_mtime),
        'created_at': int(builtin_wallpaper.stat().st_mtime),
        'origin_package_id': '',
        'origin_variant_id': '',
    }


def test_get_global_settings_prefers_migrated_manager_wallpaper_state_without_disturbing_preview_selection(tmp_path):
    legacy_wallpaper = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy.png'
    legacy_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1200, 800), '#223344').save(legacy_wallpaper)

    preview_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    preview_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1080, 1920), '#556677').save(preview_wallpaper)
    preview_mtime = int(preview_wallpaper.stat().st_mtime)

    ui_data = {
        'settings': {
            'bg_url': '/assets/backgrounds/legacy.png',
        },
        '_beautify_library_v1': {
            'global_settings': {
                'preview_wallpaper_id': 'stale:beautify',
                'wallpaper': {
                    'file': 'data/library/beautify/global/wallpapers/stale.png',
                    'filename': 'stale.png',
                    'width': 300,
                    'height': 200,
                    'mtime': 1,
                },
            },
            'packages': {},
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'width': 1080,
                    'height': 1920,
                    'mtime': preview_mtime,
                    'created_at': preview_mtime,
                    'origin_package_id': '',
                    'origin_variant_id': '',
                },
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        },
    }
    service = _build_service(tmp_path, ui_data)

    SharedWallpaperService(
        project_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    ).migrate_legacy_backgrounds(ui_data)

    settings = service.get_global_settings()
    shared_library = SharedWallpaperService(
        project_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    ).load_library()

    assert shared_library['manager_wallpaper_id']
    assert shared_library['preview_wallpaper_id'] == 'imported:preview'
    assert settings['preview_wallpaper_id'] == 'imported:preview'
    assert settings['wallpaper']['id'] == 'imported:preview'
    assert settings['wallpaper']['file'] == 'data/library/wallpapers/imported/preview.png'


def test_get_preview_asset_path_resolves_builtin_wallpaper_under_project_static(tmp_path):
    builtin_wallpaper = tmp_path / 'static' / 'assets' / 'wallpapers' / 'builtin' / 'space' / 'stars.png'
    builtin_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1920, 1080), '#112244').save(builtin_wallpaper)

    service = _build_service(tmp_path, {})

    asset_path = service.get_preview_asset_path('static/assets/wallpapers/builtin/space/stars.png')

    assert asset_path == str(builtin_wallpaper)


def test_get_preview_asset_path_resolves_shared_imported_wallpaper_under_project_data_library(tmp_path):
    imported_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    imported_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(imported_wallpaper)

    service = _build_service(tmp_path, {})

    asset_path = service.get_preview_asset_path('data/library/wallpapers/imported/preview.png')

    assert asset_path == str(imported_wallpaper)


def test_import_screenshot_and_update_package_identities_persist_package_detail_fields(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Screenshot Demo')

    screenshot_file = tmp_path / 'preview shot.png'
    Image.new('RGB', (1600, 900), '#224466').save(screenshot_file)

    screenshot_result = service.import_screenshot(imported_theme['package']['id'], str(screenshot_file))
    updated_package = service.update_package_identities(
        imported_theme['package']['id'],
        {
            'character_name': 'Alice',
            'user_name': 'Bob',
        },
    )

    package_summary = service.list_packages()[0]
    package_detail = service.get_package(imported_theme['package']['id'])

    assert package_summary['screenshot_count'] == 1
    assert screenshot_result['screenshot']['file'].endswith('/screenshots/preview shot.png')
    assert screenshot_result['screenshot']['width'] == 1600
    assert screenshot_result['screenshot']['height'] == 900
    assert package_detail['screenshots'] == {screenshot_result['screenshot']['id']: screenshot_result['screenshot']}
    assert package_detail['identity_overrides'] == {
        'character': {'name': 'Alice', 'avatar_file': ''},
        'user': {'name': 'Bob', 'avatar_file': ''},
    }
    assert updated_package['identity_overrides'] == package_detail['identity_overrides']


def test_load_library_recovers_packages_from_disk_when_ui_index_missing(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Demo', platform='pc')
    package_id = imported_theme['package']['id']

    ui_data.clear()

    recovered_library = service.load_library()

    assert package_id in recovered_library['packages']
    recovered_package = recovered_library['packages'][package_id]
    assert recovered_package['name'] == 'Recovered Demo'
    assert list(recovered_package['variants'].values())[0]['theme_file'].endswith('/themes/pc.json')
    assert get_beautify_library(ui_data)['packages'][package_id]['name'] == 'Recovered Demo'


def test_load_library_recovery_rebuilds_variant_wallpaper_truth_from_package_local_wallpapers(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Local Wallpaper Demo', platform='pc')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']
    package_wallpaper_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'wallpapers'
    package_wallpaper_dir.mkdir(parents=True)
    Image.new('RGB', (1280, 720), '#445566').save(package_wallpaper_dir / 'legacy.png')
    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['selected_wallpaper_id'] = 'wp_selected'
    ui_data['_beautify_library_v1']['packages'][package_id]['wallpapers'] = {
        'wp_selected': {
            'id': 'wp_selected',
            'variant_id': variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/legacy.png',
            'filename': 'legacy.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        }
    }

    ui_data.pop('_shared_wallpaper_library_v1', None)

    recovered_library = service.load_library()
    recovered_variant = next(iter(recovered_library['packages'][package_id]['variants'].values()))
    recovered_id = recovered_variant['wallpaper_ids'][0]
    package_detail = service.get_package(package_id)

    assert recovered_id.startswith('package_embedded:')
    assert recovered_variant['selected_wallpaper_id'] == recovered_id
    assert package_detail['wallpapers'][recovered_id]['file'] == (
        f'data/library/wallpapers/package_embedded/{package_id}/{variant_id}/legacy.png'
    )
    assert package_detail['wallpapers'][recovered_id]['origin_package_id'] == package_id
    assert package_detail['wallpapers'][recovered_id]['origin_variant_id'] == variant_id


def test_load_library_recovery_preserves_legacy_selected_wallpaper_end_to_end(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Local Wallpaper Demo', platform='pc')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']
    package_wallpaper_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'wallpapers'
    package_wallpaper_dir.mkdir(parents=True)
    Image.new('RGB', (1280, 720), '#112233').save(package_wallpaper_dir / 'first.png')
    Image.new('RGB', (1280, 720), '#445566').save(package_wallpaper_dir / 'selected.png')

    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['selected_wallpaper_id'] = 'wp_selected'
    ui_data['_beautify_library_v1']['packages'][package_id]['wallpapers'] = {
        'wp_first': {
            'id': 'wp_first',
            'variant_id': variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/first.png',
            'filename': 'first.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        },
        'wp_selected': {
            'id': 'wp_selected',
            'variant_id': variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/selected.png',
            'filename': 'selected.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        },
    }
    ui_data.pop('_shared_wallpaper_library_v1', None)

    recovered_library = service.load_library()
    recovered_variant = recovered_library['packages'][package_id]['variants'][variant_id]
    package_detail = service.get_package(package_id)

    assert len(recovered_variant['wallpaper_ids']) == 2
    assert recovered_variant['selected_wallpaper_id'].startswith('package_embedded:')
    assert package_detail['wallpapers'][recovered_variant['selected_wallpaper_id']]['filename'] == 'selected.png'


def test_load_library_recovery_keeps_empty_legacy_selection_empty_end_to_end(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Local Wallpaper Demo', platform='pc')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']
    package_wallpaper_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'wallpapers'
    package_wallpaper_dir.mkdir(parents=True)
    Image.new('RGB', (1280, 720), '#112233').save(package_wallpaper_dir / 'first.png')
    Image.new('RGB', (1280, 720), '#445566').save(package_wallpaper_dir / 'second.png')

    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][variant_id]['selected_wallpaper_id'] = ''
    ui_data['_beautify_library_v1']['packages'][package_id]['wallpapers'] = {
        'wp_first': {
            'id': 'wp_first',
            'variant_id': variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/first.png',
            'filename': 'first.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        },
        'wp_second': {
            'id': 'wp_second',
            'variant_id': variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/second.png',
            'filename': 'second.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        },
    }
    ui_data.pop('_shared_wallpaper_library_v1', None)

    recovered_library = service.load_library()
    recovered_variant = recovered_library['packages'][package_id]['variants'][variant_id]

    assert len(recovered_variant['wallpaper_ids']) == 2
    assert recovered_variant['selected_wallpaper_id'] == ''


def test_load_library_recovery_recovers_multi_variant_package_wallpapers_by_variant_id(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_pc = _import_theme_for_package(service, tmp_path, filename='theme_pc.json', name='Multi Variant Demo', platform='pc')
    package_id = imported_pc['package']['id']
    mobile_theme_file = tmp_path / 'theme_mobile.json'
    mobile_theme_file.write_text(
        json.dumps({'name': 'Multi Variant Demo', 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )
    imported_mobile = service.import_theme(str(mobile_theme_file), package_id=package_id, platform='mobile')
    pc_variant_id = imported_pc['variant']['id']
    mobile_variant_id = imported_mobile['variant']['id']
    package_wallpaper_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'wallpapers'
    package_wallpaper_dir.mkdir(parents=True)
    Image.new('RGB', (1280, 720), '#223344').save(package_wallpaper_dir / 'pc-only.png')
    Image.new('RGB', (1080, 1920), '#556677').save(package_wallpaper_dir / 'mobile-only.png')

    ui_data['_beautify_library_v1']['packages'][package_id]['variants'][pc_variant_id]['selected_wallpaper_id'] = 'wp_pc'
    ui_data['_beautify_library_v1']['packages'][package_id]['wallpapers'] = {
        'wp_pc': {
            'id': 'wp_pc',
            'variant_id': pc_variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/pc-only.png',
            'filename': 'pc-only.png',
            'width': 1280,
            'height': 720,
            'mtime': 1,
        },
        'wp_mobile': {
            'id': 'wp_mobile',
            'variant_id': mobile_variant_id,
            'file': f'data/library/beautify/packages/{package_id}/wallpapers/mobile-only.png',
            'filename': 'mobile-only.png',
            'width': 1080,
            'height': 1920,
            'mtime': 1,
        },
    }

    ui_data.pop('_shared_wallpaper_library_v1', None)

    recovered_library = service.load_library()
    recovered_package = recovered_library['packages'][package_id]
    recovered_pc_variant = recovered_package['variants'][pc_variant_id]
    recovered_mobile_variant = recovered_package['variants'][mobile_variant_id]
    package_detail = service.get_package(package_id)

    assert len(recovered_pc_variant['wallpaper_ids']) == 1
    assert recovered_pc_variant['selected_wallpaper_id'] == recovered_pc_variant['wallpaper_ids'][0]
    assert len(recovered_mobile_variant['wallpaper_ids']) == 1
    assert recovered_mobile_variant['selected_wallpaper_id'] == ''
    assert package_detail['wallpapers'][recovered_pc_variant['wallpaper_ids'][0]]['origin_variant_id'] == pc_variant_id
    assert package_detail['wallpapers'][recovered_mobile_variant['wallpaper_ids'][0]]['origin_variant_id'] == mobile_variant_id


def test_match_existing_variant_requires_theme_file_match_for_same_platform_siblings(tmp_path):
    service = _build_service(tmp_path, {})

    variant_id, existing_variant = service._match_existing_variant(
        {
            'var_pc_first': {
                'id': 'var_pc_first',
                'platform': 'pc',
                'theme_file': 'data/library/beautify/packages/pkg_demo/themes/var_pc_first.json',
                'name': 'First Variant',
            },
            'var_pc_second': {
                'id': 'var_pc_second',
                'platform': 'pc',
                'theme_file': 'data/library/beautify/packages/pkg_demo/themes/var_pc_second.json',
                'name': 'Second Variant',
            },
        },
        'pc',
        'data/library/beautify/packages/pkg_demo/themes/missing.json',
    )

    assert variant_id == ''
    assert existing_variant is None


def test_load_library_recovery_does_not_duplicate_package_local_wallpaper_imports(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    imported_theme = _import_theme_for_package(service, tmp_path, name='Recovered Local Wallpaper Demo', platform='pc')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']

    package_wallpaper_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id / 'wallpapers'
    package_wallpaper_dir.mkdir(parents=True)
    Image.new('RGB', (1280, 720), '#556677').save(package_wallpaper_dir / 'legacy.png')

    ui_data.clear()

    first_library = service.load_library()
    second_library = service.load_library()
    first_variant = next(iter(first_library['packages'][package_id]['variants'].values()))
    second_variant = next(iter(second_library['packages'][package_id]['variants'].values()))
    embedded_dir = (
        tmp_path / 'data' / 'library' / 'wallpapers' / 'package_embedded' / package_id / variant_id
    )

    assert first_variant['wallpaper_ids'] == second_variant['wallpaper_ids']
    assert sorted(path.name for path in embedded_dir.iterdir()) == ['legacy.png']


def test_load_library_skips_invalid_theme_files_during_disk_recovery(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    themes_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / 'pkg_broken' / 'themes'
    themes_dir.mkdir(parents=True)
    (themes_dir / 'pc.json').write_text(json.dumps({'name': 'Broken Only Name'}, ensure_ascii=False), encoding='utf-8')

    recovered_library = service.load_library()

    assert 'pkg_broken' not in recovered_library['packages']
    assert 'pkg_broken' not in get_beautify_library(ui_data)['packages']


def test_load_library_uses_stable_package_name_when_recovered_variants_disagree(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    themes_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / 'pkg_multi_variant' / 'themes'
    themes_dir.mkdir(parents=True)
    (themes_dir / 'mobile.json').write_text(
        json.dumps({'name': 'Mobile Theme', 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )
    (themes_dir / 'pc.json').write_text(
        json.dumps({'name': 'Desktop Theme', 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )

    recovered_library = service.load_library()

    recovered_package = recovered_library['packages']['pkg_multi_variant']
    assert recovered_package['name'] == 'multi variant'
    assert {variant['theme_name'] for variant in recovered_package['variants'].values()} == {'Mobile Theme', 'Desktop Theme'}


def test_import_global_avatar_and_import_package_avatar_use_stable_slots(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Avatar Demo')

    global_avatar = tmp_path / 'global-character.png'
    package_avatar = tmp_path / 'package-user.png'
    Image.new('RGB', (400, 400), '#884422').save(global_avatar)
    Image.new('RGB', (512, 512), '#228844').save(package_avatar)

    global_result = service.import_global_avatar('character', str(global_avatar))
    package_result = service.import_package_avatar(imported_theme['package']['id'], 'user', str(package_avatar))

    assert global_result['identity']['avatar_file'] == 'data/library/beautify/global/avatars/character.png'
    assert package_result['identity']['avatar_file'].endswith('/avatars/user.png')
    assert (tmp_path / global_result['identity']['avatar_file']).exists()
    assert (tmp_path / package_result['identity']['avatar_file']).exists()

    package_detail = service.get_package(imported_theme['package']['id'])
    assert package_detail['identity_overrides']['user'] == package_result['identity']
    assert get_beautify_library(ui_data)['global_settings']['identities']['character'] == global_result['identity']


def test_import_global_avatar_replaces_slot_and_removes_stale_old_extension_file(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    first_avatar = tmp_path / 'character.png'
    second_avatar = tmp_path / 'character.webp'
    Image.new('RGB', (300, 300), '#335577').save(first_avatar)
    Image.new('RGB', (320, 320), '#775533').save(second_avatar)

    first_result = service.import_global_avatar('character', str(first_avatar))
    second_result = service.import_global_avatar('character', str(second_avatar))

    assert first_result['identity']['avatar_file'] == 'data/library/beautify/global/avatars/character.png'
    assert second_result['identity']['avatar_file'] == 'data/library/beautify/global/avatars/character.webp'
    assert (tmp_path / 'data' / 'library' / 'beautify' / 'global' / 'avatars' / 'character.png').exists() is False
    assert (tmp_path / 'data' / 'library' / 'beautify' / 'global' / 'avatars' / 'character.webp').exists()


def test_update_global_settings_can_clear_names_and_avatar_values(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    character_avatar = tmp_path / 'character.png'
    user_avatar = tmp_path / 'user.png'
    wallpaper_file = tmp_path / 'wallpaper.png'
    Image.new('RGB', (300, 300), '#335577').save(character_avatar)
    Image.new('RGB', (300, 300), '#775533').save(user_avatar)
    Image.new('RGB', (1080, 1920), '#112244').save(wallpaper_file)

    service.import_global_wallpaper(str(wallpaper_file))
    service.import_global_avatar('character', str(character_avatar))
    service.import_global_avatar('user', str(user_avatar))
    updated_settings = service.update_global_settings(
        {
            'character_name': 'Alice',
            'user_name': 'Bob',
        }
    )

    cleared_settings = service.update_global_settings(
        {
            'clear_wallpaper': True,
            'character_name': '   ',
            'user_name': None,
            'clear_character_avatar': True,
            'clear_user_avatar': True,
        }
    )

    assert updated_settings['identities']['character']['name'] == 'Alice'
    assert updated_settings['identities']['user']['avatar_file'].endswith('/global/avatars/user.png')
    assert updated_settings['wallpaper']['file'].endswith('/global/wallpapers/wallpaper.png')
    assert cleared_settings['wallpaper'] == {
        'file': '',
        'filename': '',
        'width': 0,
        'height': 0,
        'mtime': 0,
    }
    assert cleared_settings['identities'] == {
        'character': {'name': '', 'avatar_file': ''},
        'user': {'name': '', 'avatar_file': ''},
    }
    assert (tmp_path / 'data' / 'library' / 'beautify' / 'global' / 'wallpapers' / 'wallpaper.png').exists() is False
    assert (tmp_path / 'data' / 'library' / 'beautify' / 'global' / 'avatars' / 'character.png').exists() is False
    assert (tmp_path / 'data' / 'library' / 'beautify' / 'global' / 'avatars' / 'user.png').exists() is False


def test_update_global_settings_ignores_nested_identity_avatar_payloads(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    character_avatar = tmp_path / 'character.png'
    Image.new('RGB', (300, 300), '#335577').save(character_avatar)
    service.import_global_avatar('character', str(character_avatar))

    updated_settings = service.update_global_settings(
        {
            'character_name': 'Alice',
            'identities': {'character': {'avatar_file': ''}},
            'avatar_file': '',
        }
    )

    assert updated_settings['identities']['character']['name'] == 'Alice'
    assert updated_settings['identities']['character']['avatar_file'].endswith('/global/avatars/character.png')


def test_update_global_settings_ignores_non_boolean_clear_flags(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    character_avatar = tmp_path / 'character.png'
    wallpaper_file = tmp_path / 'wallpaper.png'
    Image.new('RGB', (300, 300), '#335577').save(character_avatar)
    Image.new('RGB', (1080, 1920), '#112244').save(wallpaper_file)

    service.import_global_wallpaper(str(wallpaper_file))
    service.import_global_avatar('character', str(character_avatar))
    updated_settings = service.update_global_settings(
        {
            'character_name': 'Alice',
            'clear_wallpaper': 'false',
            'clear_character_avatar': 1,
        }
    )

    assert updated_settings['wallpaper']['file'].endswith('/global/wallpapers/wallpaper.png')
    assert updated_settings['identities']['character']['name'] == 'Alice'
    assert updated_settings['identities']['character']['avatar_file'].endswith('/global/avatars/character.png')


def test_update_global_settings_returns_resolved_shared_preview_wallpaper_view(tmp_path):
    shared_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    shared_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (1440, 900), '#2468ac').save(shared_wallpaper)

    ui_data = {
        '_beautify_library_v1': {
            'global_settings': {
                'wallpaper': {
                    'file': 'data/library/beautify/global/wallpapers/legacy.png',
                    'filename': 'legacy.png',
                    'width': 1080,
                    'height': 1920,
                    'mtime': 1,
                },
                'identities': {
                    'character': {'name': '', 'avatar_file': ''},
                    'user': {'name': '', 'avatar_file': ''},
                },
            },
            'packages': {},
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:preview': {
                    'id': 'imported:preview',
                    'source_type': 'imported',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'width': 1440,
                    'height': 900,
                    'mtime': int(shared_wallpaper.stat().st_mtime),
                    'created_at': int(shared_wallpaper.stat().st_mtime),
                    'origin_package_id': '',
                    'origin_variant_id': '',
                }
            },
            'manager_wallpaper_id': '',
            'preview_wallpaper_id': 'imported:preview',
        },
    }
    service = _build_service(tmp_path, ui_data)

    updated_settings = service.update_global_settings({'character_name': 'Alice'})

    assert updated_settings['preview_wallpaper_id'] == 'imported:preview'
    assert updated_settings['wallpaper'] == {
        'id': 'imported:preview',
        'source_type': 'imported',
        'file': 'data/library/wallpapers/imported/preview.png',
        'filename': 'preview.png',
        'width': 1440,
        'height': 900,
        'mtime': int(shared_wallpaper.stat().st_mtime),
        'created_at': int(shared_wallpaper.stat().st_mtime),
        'origin_package_id': '',
        'origin_variant_id': '',
    }
    assert updated_settings['identities']['character']['name'] == 'Alice'


def test_update_package_identities_uses_flat_payload_and_clear_flags(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Identity Demo')

    avatar_file = tmp_path / 'package-user.png'
    Image.new('RGB', (512, 512), '#228844').save(avatar_file)
    service.import_package_avatar(imported_theme['package']['id'], 'user', str(avatar_file))

    updated_package = service.update_package_identities(
        imported_theme['package']['id'],
        {
            'character_name': 'Hero',
            'user_name': '',
            'clear_user_avatar': True,
            'user': {'avatar_file': 'should/not/pass.png'},
        },
    )

    assert updated_package['identity_overrides'] == {
        'character': {'name': 'Hero', 'avatar_file': ''},
        'user': {'name': '', 'avatar_file': ''},
    }


def test_update_package_identities_clear_flag_removes_package_avatar_file(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Avatar Clear Demo')

    avatar_file = tmp_path / 'package-character.png'
    Image.new('RGB', (512, 512), '#228844').save(avatar_file)
    imported_avatar = service.import_package_avatar(imported_theme['package']['id'], 'character', str(avatar_file))
    saved_avatar_path = tmp_path / imported_avatar['identity']['avatar_file']

    updated_package = service.update_package_identities(
        imported_theme['package']['id'],
        {
            'clear_character_avatar': True,
        },
    )

    assert saved_avatar_path.exists() is False
    assert updated_package['identity_overrides']['character']['avatar_file'] == ''


def test_update_package_identities_ignores_non_boolean_clear_flags(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Safe Flag Demo')

    avatar_file = tmp_path / 'package-user.png'
    Image.new('RGB', (512, 512), '#228844').save(avatar_file)
    imported_avatar = service.import_package_avatar(imported_theme['package']['id'], 'user', str(avatar_file))
    saved_avatar_path = tmp_path / imported_avatar['identity']['avatar_file']

    updated_package = service.update_package_identities(
        imported_theme['package']['id'],
        {
            'user_name': 'Player',
            'clear_user_avatar': 'false',
        },
    )

    assert saved_avatar_path.exists()
    assert updated_package['identity_overrides']['user']['name'] == 'Player'
    assert updated_package['identity_overrides']['user']['avatar_file'].endswith('/avatars/user.png')


def test_import_global_wallpaper_raises_value_error_for_invalid_image(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    invalid_file = tmp_path / 'invalid-wallpaper.png'
    invalid_file.write_bytes(b'not-an-image')

    try:
        service.import_global_wallpaper(str(invalid_file))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '壁纸文件无效'


def test_invalid_global_wallpaper_replacement_preserves_existing_asset(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    valid_wallpaper = tmp_path / 'valid-wallpaper.png'
    invalid_wallpaper = tmp_path / 'invalid-wallpaper.png'
    Image.new('RGB', (1080, 1920), '#112244').save(valid_wallpaper)
    invalid_wallpaper.write_bytes(b'not-an-image')

    first_result = service.import_global_wallpaper(str(valid_wallpaper))
    original_path = tmp_path / first_result['wallpaper']['file']
    original_mtime = first_result['wallpaper']['mtime']

    try:
        service.import_global_wallpaper(str(invalid_wallpaper))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '壁纸文件无效'

    settings = service.get_global_settings()
    assert original_path.exists()
    assert settings['wallpaper']['file'] == first_result['wallpaper']['file']
    assert settings['wallpaper']['mtime'] == original_mtime


def test_import_screenshot_raises_value_error_for_invalid_image(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Invalid Screenshot Demo')

    invalid_file = tmp_path / 'invalid-screenshot.png'
    invalid_file.write_bytes(b'not-an-image')

    try:
        service.import_screenshot(imported_theme['package']['id'], str(invalid_file))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '截图文件无效'


def test_import_wallpaper_raises_value_error_for_invalid_image_and_removes_copied_file(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Invalid Wallpaper Demo')

    invalid_file = tmp_path / 'invalid-wallpaper.png'
    invalid_file.write_bytes(b'not-an-image')
    wallpapers_dir = (
        tmp_path
        / 'data'
        / 'library'
        / 'wallpapers'
        / 'package_embedded'
        / imported_theme['package']['id']
        / imported_theme['variant']['id']
    )

    try:
        service.import_wallpaper(imported_theme['package']['id'], imported_theme['variant']['id'], str(invalid_file))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '壁纸文件无效'

    assert wallpapers_dir.exists() is False or list(wallpapers_dir.iterdir()) == []


def test_import_global_avatar_raises_value_error_for_invalid_image(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    invalid_file = tmp_path / 'invalid-avatar.png'
    invalid_file.write_bytes(b'not-an-image')

    try:
        service.import_global_avatar('character', str(invalid_file))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '头像文件无效'


def test_invalid_global_avatar_replacement_preserves_existing_asset(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)

    valid_avatar = tmp_path / 'valid-avatar.png'
    invalid_avatar = tmp_path / 'invalid-avatar.png'
    Image.new('RGB', (300, 300), '#335577').save(valid_avatar)
    invalid_avatar.write_bytes(b'not-an-image')

    first_result = service.import_global_avatar('character', str(valid_avatar))
    original_path = tmp_path / first_result['identity']['avatar_file']

    try:
        service.import_global_avatar('character', str(invalid_avatar))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '头像文件无效'

    settings = service.get_global_settings()
    assert original_path.exists()
    assert settings['identities']['character']['avatar_file'] == first_result['identity']['avatar_file']


def test_invalid_package_avatar_replacement_preserves_existing_asset(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Package Avatar Preserve Demo')

    valid_avatar = tmp_path / 'valid-package-avatar.png'
    invalid_avatar = tmp_path / 'invalid-package-avatar.png'
    Image.new('RGB', (300, 300), '#335577').save(valid_avatar)
    invalid_avatar.write_bytes(b'not-an-image')

    first_result = service.import_package_avatar(imported_theme['package']['id'], 'user', str(valid_avatar))
    original_path = tmp_path / first_result['identity']['avatar_file']

    try:
        service.import_package_avatar(imported_theme['package']['id'], 'user', str(invalid_avatar))
        assert False, 'expected ValueError'
    except ValueError as exc:
        assert str(exc) == '头像文件无效'

    package_detail = service.get_package(imported_theme['package']['id'])
    assert original_path.exists()
    assert package_detail['identity_overrides']['user']['avatar_file'] == first_result['identity']['avatar_file']


def test_get_package_ignores_tampered_theme_file_outside_library(tmp_path):
    external_theme = tmp_path / 'external-theme.json'
    external_theme.write_text(json.dumps({'name': 'External', 'main_text_color': '#f00'}, ensure_ascii=False), encoding='utf-8')

    ui_data = {
        '_beautify_library_v1': {
            'packages': {
                'pkg_demo': {
                    'id': 'pkg_demo',
                    'name': 'Demo',
                    'variants': {
                        'var_pc': {
                            'id': 'var_pc',
                            'platform': 'pc',
                            'theme_name': 'Demo',
                            'theme_file': '../../external-theme.json',
                            'wallpaper_ids': [],
                            'preview_hint': {'needs_platform_review': False, 'preview_accuracy': 'base'},
                        }
                    },
                    'wallpapers': {},
                    'screenshots': {},
                    'identity_overrides': {},
                }
            }
        }
    }
    service = _build_service(tmp_path, ui_data)

    package_detail = service.get_package('pkg_demo')

    assert package_detail['variants']['var_pc']['theme_data'] == {}


def test_import_wallpaper_sanitizes_malicious_source_name(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Wallpaper Name Demo')

    wallpaper_file = tmp_path / 'wallpaper.png'
    Image.new('RGB', (1280, 720), '#223344').save(wallpaper_file)

    result = service.import_wallpaper(
        imported_theme['package']['id'],
        imported_theme['variant']['id'],
        str(wallpaper_file),
        source_name='../../outside.png',
    )
    saved_path = tmp_path / result['wallpaper']['file']

    assert result['wallpaper']['filename'] == 'outside.png'
    assert saved_path.exists()
    assert saved_path.parent.name == imported_theme['variant']['id']
    assert '..' not in result['wallpaper']['file']


def test_import_screenshot_sanitizes_windows_style_malicious_source_name(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Screenshot Name Demo')

    screenshot_file = tmp_path / 'shot.png'
    Image.new('RGB', (1280, 720), '#223344').save(screenshot_file)

    result = service.import_screenshot(
        imported_theme['package']['id'],
        str(screenshot_file),
        source_name='..\\..\\outside.png',
    )
    saved_path = tmp_path / result['screenshot']['file']

    assert result['screenshot']['filename'] == 'outside.png'
    assert saved_path.exists()
    assert saved_path.parent.name == 'screenshots'
    assert '..' not in result['screenshot']['file']


def test_remove_asset_file_does_not_delete_file_outside_library_for_malformed_metadata(tmp_path):
    outside_file = tmp_path / 'outside-avatar.png'
    outside_file.write_text('keep me', encoding='utf-8')

    service = _build_service(tmp_path, {})
    service._remove_asset_file('data/library/beautify/../../../outside-avatar.png')

    assert outside_file.exists()


def test_delete_package_removes_package_screenshots_and_avatars_with_directory(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Delete Demo')
    package_id = imported_theme['package']['id']

    screenshot_file = tmp_path / 'delete-shot.png'
    avatar_file = tmp_path / 'delete-avatar.png'
    Image.new('RGB', (1280, 720), '#111111').save(screenshot_file)
    Image.new('RGB', (256, 256), '#999999').save(avatar_file)

    screenshot_result = service.import_screenshot(package_id, str(screenshot_file))
    avatar_result = service.import_package_avatar(package_id, 'character', str(avatar_file))
    package_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id

    assert (tmp_path / screenshot_result['screenshot']['file']).exists()
    assert (tmp_path / avatar_result['identity']['avatar_file']).exists()
    assert package_dir.exists()

    deleted = service.delete_package(package_id)

    assert deleted is True
    assert service.get_package(package_id) is None
    assert package_dir.exists() is False
    assert (tmp_path / screenshot_result['screenshot']['file']).exists() is False
    assert (tmp_path / avatar_result['identity']['avatar_file']).exists() is False


def test_delete_package_removes_package_embedded_shared_wallpapers_from_disk_and_library(tmp_path):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Delete Wallpaper Demo')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']

    wallpaper_file = tmp_path / 'delete-wallpaper.png'
    Image.new('RGB', (1280, 720), '#345678').save(wallpaper_file)

    wallpaper_result = service.import_wallpaper(package_id, variant_id, str(wallpaper_file))
    shared_wallpaper = wallpaper_result['wallpaper']
    shared_wallpaper_path = tmp_path / shared_wallpaper['file']

    assert shared_wallpaper_path.exists()
    assert shared_wallpaper['id'] in ui_data['_shared_wallpaper_library_v1']['items']

    deleted = service.delete_package(package_id)

    assert deleted is True
    assert service.get_package(package_id) is None
    assert shared_wallpaper_path.exists() is False
    assert shared_wallpaper['id'] not in ui_data['_shared_wallpaper_library_v1']['items']


def test_delete_package_retries_directory_cleanup_after_transient_lock(tmp_path, monkeypatch):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Delete Retry Demo')
    package_id = imported_theme['package']['id']
    package_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id
    original_rmtree = beautify_service_module.shutil.rmtree
    attempts = []

    def flaky_rmtree(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError('simulated transient Windows file lock')
        return original_rmtree(path)

    monkeypatch.setattr(beautify_service_module.shutil, 'rmtree', flaky_rmtree)

    assert service.delete_package(package_id) is True
    assert len(attempts) == 2
    assert package_dir.exists() is False
    assert service.get_package(package_id) is None


def test_delete_package_keeps_library_record_when_directory_stays_locked(tmp_path, monkeypatch):
    ui_data = {}
    service = _build_service(tmp_path, ui_data)
    imported_theme = _import_theme_for_package(service, tmp_path, name='Delete Locked Demo')
    package_id = imported_theme['package']['id']
    package_dir = tmp_path / 'data' / 'library' / 'beautify' / 'packages' / package_id

    def locked_rmtree(path):
        raise PermissionError('simulated persistent Windows file lock')

    monkeypatch.setattr(beautify_service_module.shutil, 'rmtree', locked_rmtree)

    with pytest.raises(PermissionError):
        service.delete_package(package_id)

    assert package_dir.exists()
    assert service.get_package(package_id) is not None


def test_beautify_package_shape_no_longer_requires_install_state(tmp_path):
    library_root = tmp_path / 'data' / 'library' / 'beautify'
    ui_data = {}
    theme_file = tmp_path / 'theme_pc.json'
    theme_file.write_text(
        json.dumps({'name': 'Demo', 'main_text_color': '#fff'}, ensure_ascii=False),
        encoding='utf-8',
    )
    wallpaper_file = tmp_path / 'bg.webp'
    Image.new('RGB', (1280, 720), '#223344').save(wallpaper_file)

    service = BeautifyService(
        library_root=library_root,
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: ui_data.clear() or ui_data.update(data),
    )
    imported_theme = service.import_theme(str(theme_file), platform='pc')
    imported_wallpaper = service.import_wallpaper(
        imported_theme['package']['id'],
        imported_theme['variant']['id'],
        str(wallpaper_file),
    )

    package_info = service.get_package(imported_theme['package']['id'])
    assert 'install_state' not in package_info


def test_beautify_service_removes_dead_st_client_and_wallpaper_index_helpers():
    source = (ROOT / 'core/services/beautify_service.py').read_text(encoding='utf-8')

    assert 'self.st_client =' not in source
    assert '_wallpaper_index_for_variant' not in source
