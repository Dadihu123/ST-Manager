import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clean_ui_data import clean_ui_data_file


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _build_config(tmp_path, cards_dir, world_info_dir, presets_dir, beautify_dir, resources_dir):
    config_path = tmp_path / 'config.json'
    _write_json(
        config_path,
        {
            'cards_dir': str(cards_dir),
            'world_info_dir': str(world_info_dir),
            'presets_dir': str(presets_dir),
            'beautify_dir': str(beautify_dir),
            'resources_dir': str(resources_dir),
        },
    )
    return config_path


def test_clean_ui_data_file_removes_stale_file_references_and_creates_backup(tmp_path):
    cards_dir = tmp_path / 'cards'
    world_info_dir = tmp_path / 'world-info'
    presets_dir = tmp_path / 'presets'
    beautify_dir = tmp_path / 'beautify'
    resources_dir = tmp_path / 'resources'
    for directory in (cards_dir, world_info_dir, presets_dir, beautify_dir, resources_dir):
        directory.mkdir()

    (cards_dir / 'alice.png').write_bytes(b'card')
    bundle_dir = cards_dir / 'bundle'
    bundle_dir.mkdir()
    (bundle_dir / '.bundle').write_text('1', encoding='utf-8')
    (bundle_dir / 'cover.json').write_text('{}', encoding='utf-8')

    (resources_dir / 'alice').mkdir()
    global_world_info = world_info_dir / 'global.json'
    resource_world_info = resources_dir / 'alice' / 'world.json'
    resource_world_info.parent.mkdir(parents=True, exist_ok=True)
    global_world_info.write_text('{}', encoding='utf-8')
    resource_world_info.write_text('{}', encoding='utf-8')
    preset_file = presets_dir / 'writing.json'
    preset_file.write_text('{}', encoding='utf-8')
    (cards_dir / 'isolated').mkdir()

    package_dir = beautify_dir / 'packages' / 'demo'
    themes_dir = package_dir / 'themes'
    themes_dir.mkdir(parents=True)
    theme_file = themes_dir / 'pc.json'
    theme_file.write_text('{}', encoding='utf-8')
    screenshot_file = package_dir / 'screenshots' / 'preview.png'
    screenshot_file.parent.mkdir()
    screenshot_file.write_bytes(b'image')
    shared_wallpaper = tmp_path / 'wallpaper.png'
    shared_wallpaper.write_bytes(b'image')

    config_path = _build_config(
        tmp_path,
        cards_dir,
        world_info_dir,
        presets_dir,
        beautify_dir,
        resources_dir,
    )
    ui_data_path = tmp_path / 'data' / 'system' / 'db' / 'ui_data.json'
    original = {
        'alice.png': {'resource_folder': 'alice'},
        'bundle': {
            '_version_remarks': {
                'bundle/cover.json': {'summary': 'keep'},
                'bundle/missing.json': {'summary': 'remove'},
            }
        },
        'missing.png': {'summary': 'remove'},
        '_isolated_categories_v1': {'paths': ['isolated', 'missing']},
        '_resource_item_categories_v1': {
            'worldinfo': {
                str(global_world_info): {'category': 'global'},
                str(tmp_path / 'gone-world.json'): {'category': 'gone'},
            },
            'presets': {
                str(preset_file): {'category': 'writing'},
                str(tmp_path / 'gone-preset.json'): {'category': 'gone'},
            },
        },
        '_worldinfo_notes_v1': {
            f'global::{global_world_info}': {'summary': 'keep'},
            f'resource::{resource_world_info}': {'summary': 'keep'},
            'embedded::bundle/cover.json': {'summary': 'keep'},
            'global::missing.json': {'summary': 'remove'},
            'embedded::missing.json': {'summary': 'remove'},
        },
        '_shared_wallpaper_library_v1': {
            'items': {
                'imported:keep': {'file': str(shared_wallpaper), 'source_type': 'imported'},
                'imported:gone': {'file': str(tmp_path / 'gone-wallpaper.png'), 'source_type': 'imported'},
            },
            'manager_wallpaper_id': 'imported:gone',
            'preview_wallpaper_id': 'imported:keep',
        },
        '_beautify_library_v1': {
            'global_settings': {
                'wallpaper': {'file': str(shared_wallpaper)},
                'identities': {'character': {'avatar_file': str(tmp_path / 'gone-avatar.png')}},
            },
            'packages': {
                'demo': {
                    'cover_variant_id': 'bad',
                    'variants': {
                        'good': {
                            'theme_file': str(theme_file),
                            'wallpaper_ids': ['imported:keep', 'imported:gone'],
                            'selected_wallpaper_id': 'imported:gone',
                        },
                        'bad': {'theme_file': str(tmp_path / 'gone-theme.json')},
                    },
                    'wallpapers': {
                        'keep': {'file': str(shared_wallpaper)},
                        'gone': {'file': str(tmp_path / 'gone-package-wallpaper.png')},
                    },
                    'screenshots': {
                        'keep': {'file': str(screenshot_file)},
                        'gone': {'file': str(tmp_path / 'gone-screenshot.png')},
                    },
                    'identity_overrides': {
                        'user': {'avatar_file': str(tmp_path / 'gone-package-avatar.png')}
                    },
                },
                'gone': {'variants': {}},
            },
        },
    }
    _write_json(ui_data_path, original)

    stats = clean_ui_data_file(config_path=config_path, ui_data_path=ui_data_path)

    cleaned = json.loads(ui_data_path.read_text(encoding='utf-8'))
    backup = json.loads((ui_data_path.with_name('ui_data.json.bak')).read_text(encoding='utf-8'))
    assert backup == original
    assert stats['changed'] is True
    assert stats['removed_entries'] == 1
    assert stats['removed_version_remarks'] == 1
    assert stats['removed_worldinfo_notes'] == 2
    assert stats['removed_resource_categories'] == 2
    assert stats['removed_shared_wallpapers'] == 1
    assert stats['removed_beautify_packages'] == 1
    assert 'missing.png' not in cleaned
    assert set(cleaned['bundle']['_version_remarks']) == {'bundle/cover.json'}
    assert cleaned['_shared_wallpaper_library_v1']['manager_wallpaper_id'] == ''
    assert cleaned['_beautify_library_v1']['packages']['demo']['cover_variant_id'] == ''
    assert cleaned['_beautify_library_v1']['packages']['demo']['variants']['good']['wallpaper_ids'] == [
        'imported:keep'
    ]
    assert cleaned['_beautify_library_v1']['packages']['demo']['variants']['good']['selected_wallpaper_id'] == ''


def test_clean_ui_data_file_dry_run_does_not_backup_or_write(tmp_path):
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    config_path = _build_config(
        tmp_path,
        cards_dir,
        tmp_path / 'world-info',
        tmp_path / 'presets',
        tmp_path / 'beautify',
        tmp_path / 'resources',
    )
    ui_data_path = tmp_path / 'ui_data.json'
    original = {'missing.png': {'summary': 'stale'}}
    _write_json(ui_data_path, original)

    stats = clean_ui_data_file(
        config_path=config_path,
        ui_data_path=ui_data_path,
        dry_run=True,
    )

    assert stats['changed'] is True
    assert not ui_data_path.with_name('ui_data.json.bak').exists()
    assert json.loads(ui_data_path.read_text(encoding='utf-8')) == original


def test_clean_ui_data_file_uses_executable_directory_when_frozen(tmp_path, monkeypatch):
    executable_root = tmp_path / 'package'
    cards_dir = executable_root / 'data' / 'library' / 'characters'
    cards_dir.mkdir(parents=True)
    ui_data_path = executable_root / 'data' / 'system' / 'db' / 'ui_data.json'
    _write_json(ui_data_path, {'missing.png': {'summary': 'stale'}})

    monkeypatch.setattr('clean_ui_data.sys.frozen', True, raising=False)
    monkeypatch.setattr('clean_ui_data.sys.executable', str(executable_root / 'clean_ui_data.exe'))

    stats = clean_ui_data_file(dry_run=True)

    assert stats['config_path'] == str(executable_root / 'config.json')
    assert stats['ui_data_path'] == str(ui_data_path)
    assert stats['changed'] is True
