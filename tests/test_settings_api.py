import io
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import system as system_api
from core.config import build_default_config
from core.services.shared_wallpaper_service import SharedWallpaperService


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app


class FakeSharedWallpaperService:
    def __init__(self):
        self.calls = []
        self.library = {
            'items': {
                'builtin:space/stars.png': {
                    'id': 'builtin:space/stars.png',
                    'file': 'static/assets/wallpapers/builtin/space/stars.png',
                    'filename': 'stars.png',
                    'source_type': 'builtin',
                },
                'imported:demo': {
                    'id': 'imported:demo',
                    'file': 'data/library/wallpapers/imported/demo.png',
                    'filename': 'demo.png',
                    'source_type': 'imported',
                },
            },
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': 'imported:demo',
            'updated_at': 123,
        }

    def load_library(self):
        self.calls.append(('load_library',))
        return self.library

    def migrate_legacy_backgrounds(self, ui_data=None):
        self.calls.append(('migrate_legacy_backgrounds', ui_data))
        return self.library

    def import_wallpaper(self, source_path, selection_target='', source_name=None):
        self.calls.append(('import_wallpaper', source_path, selection_target, source_name))
        return {
            'id': 'imported:new',
            'file': 'data/library/wallpapers/imported/new.png',
            'filename': source_name or 'new.png',
            'source_type': 'imported',
        }

    def select_wallpaper(self, wallpaper_id, selection_target):
        self.calls.append(('select_wallpaper', wallpaper_id, selection_target))
        return {
            'selected': True,
            'selection_target': selection_target,
            'wallpaper_id': wallpaper_id,
        }


class FakeUserDbBackupService:
    def __init__(self):
        self.calls = []

    def export_backup(self):
        self.calls.append(('export_backup',))
        return {'backup_path': 'data/backups/user-db.json'}

    def import_backup(self, source_path, source_name=''):
        self.calls.append(('import_backup', source_path, source_name))
        return {'imported': True, 'source_name': source_name}


def test_build_default_config_only_includes_openai_preset_directory():
    cfg = build_default_config()

    assert cfg['st_openai_preset_dir'] == ''
    assert 'st_textgen_preset_dir' not in cfg
    assert 'st_instruct_preset_dir' not in cfg
    assert 'st_context_preset_dir' not in cfg
    assert 'st_sysprompt_dir' not in cfg
    assert 'st_reasoning_dir' not in cfg


def test_get_settings_only_returns_openai_preset_directory(monkeypatch):
    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {
            'cards_dir': 'cards',
            'world_info_dir': 'worlds',
            'chats_dir': 'chats',
            'presets_dir': 'presets',
            'quick_replies_dir': 'quick',
            'default_sort': 'date_desc',
            'show_header_sort': True,
            'st_openai_preset_dir': 'st/openai',
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/get_settings')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['st_openai_preset_dir'] == 'st/openai'
    assert 'st_textgen_preset_dir' not in payload
    assert 'st_instruct_preset_dir' not in payload
    assert 'st_context_preset_dir' not in payload
    assert 'st_sysprompt_dir' not in payload
    assert 'st_reasoning_dir' not in payload


def test_get_settings_filters_legacy_preset_directory_keys_from_loaded_config(monkeypatch):
    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {
            'cards_dir': 'cards',
            'world_info_dir': 'worlds',
            'chats_dir': 'chats',
            'presets_dir': 'presets',
            'quick_replies_dir': 'quick',
            'default_sort': 'date_desc',
            'show_header_sort': True,
            'st_openai_preset_dir': 'st/openai',
            'st_textgen_preset_dir': 'st/textgen',
            'st_instruct_preset_dir': 'st/instruct',
            'st_context_preset_dir': 'st/context',
            'st_sysprompt_dir': 'st/sysprompt',
            'st_reasoning_dir': 'st/reasoning',
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/get_settings')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['st_openai_preset_dir'] == 'st/openai'
    assert 'st_textgen_preset_dir' not in payload
    assert 'st_instruct_preset_dir' not in payload
    assert 'st_context_preset_dir' not in payload
    assert 'st_sysprompt_dir' not in payload
    assert 'st_reasoning_dir' not in payload


def test_get_settings_includes_shared_wallpaper_library_for_manager(monkeypatch):
    fake_service = FakeSharedWallpaperService()
    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {
            'cards_dir': 'cards',
            'world_info_dir': 'worlds',
            'chats_dir': 'chats',
            'presets_dir': 'presets',
            'quick_replies_dir': 'quick',
        },
    )
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.get('/api/get_settings')
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['manager_wallpaper_id'] == 'builtin:space/stars.png'
    assert payload['shared_wallpapers'] == [
        {
            'id': 'builtin:space/stars.png',
            'file': 'static/assets/wallpapers/builtin/space/stars.png',
            'filename': 'stars.png',
            'source_type': 'builtin',
        },
        {
            'id': 'imported:demo',
            'file': 'data/library/wallpapers/imported/demo.png',
            'filename': 'demo.png',
            'source_type': 'imported',
        },
    ]
    assert ('migrate_legacy_backgrounds', {'bg_url': ''}) in fake_service.calls


def test_get_settings_migrates_config_backed_legacy_manager_background_before_serializing_shared_wallpapers(monkeypatch, tmp_path):
    legacy_path = tmp_path / 'data' / 'assets' / 'backgrounds' / 'legacy-bg.png'
    legacy_path.parent.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    Image.new('RGB', (1024, 768), (12, 34, 56)).save(legacy_path)

    ui_data = {}
    service = SharedWallpaperService(
        project_root=str(tmp_path),
        ui_data_loader=lambda: ui_data,
        ui_data_saver=lambda data: True,
    )

    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {
            'cards_dir': 'cards',
            'world_info_dir': 'worlds',
            'chats_dir': 'chats',
            'presets_dir': 'presets',
            'quick_replies_dir': 'quick',
            'bg_url': '/assets/backgrounds/legacy-bg.png',
        },
    )
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: service, raising=False)

    client = _make_test_app().test_client()
    res = client.get('/api/get_settings')
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['manager_wallpaper_id']
    assert payload['shared_wallpapers']
    manager_item = next(item for item in payload['shared_wallpapers'] if item['id'] == payload['manager_wallpaper_id'])
    assert manager_item['filename'] == 'legacy-bg.png'
    assert manager_item['source_type'] == 'imported'


def test_import_shared_wallpaper_endpoint_delegates_to_service(monkeypatch):
    fake_service = FakeSharedWallpaperService()
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/shared-wallpapers/import',
        data={
            'selection_target': 'manager',
            'file': (io.BytesIO(b'png-data'), 'manager-bg.png'),
        },
        content_type='multipart/form-data',
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['success'] is True
    assert payload['item']['id'] == 'imported:new'
    assert fake_service.calls[0][0] == 'import_wallpaper'
    assert fake_service.calls[0][2:] == ('manager', 'manager-bg.png')


def test_import_shared_wallpaper_endpoint_rejects_invalid_image(monkeypatch):
    fake_service = FakeSharedWallpaperService()

    def import_invalid(source_path, selection_target='', source_name=None):
        fake_service.calls.append(('import_wallpaper', source_path, selection_target, source_name))
        return {}

    fake_service.import_wallpaper = import_invalid
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/shared-wallpapers/import',
        data={
            'selection_target': 'manager',
            'file': (io.BytesIO(b'not-a-real-image'), 'broken.png'),
        },
        content_type='multipart/form-data',
    )
    payload = res.get_json()

    assert res.status_code == 400
    assert payload['success'] is False
    assert payload['msg'] == '导入壁纸失败，请确认文件是有效图片'


def test_import_shared_wallpaper_endpoint_rejects_invalid_selection_target(monkeypatch):
    fake_service = FakeSharedWallpaperService()
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/shared-wallpapers/import',
        data={
            'selection_target': 'broken-target',
            'file': (io.BytesIO(b'png-data'), 'manager-bg.png'),
        },
        content_type='multipart/form-data',
    )
    payload = res.get_json()

    assert res.status_code == 400
    assert payload['success'] is False
    assert payload['msg'] == '无效的 selection_target'


def test_save_settings_persists_manager_wallpaper_id_to_shared_library(monkeypatch):
    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    monkeypatch.setattr(system_api, 'save_config', lambda cfg: True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: None)
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: 'cards')
    monkeypatch.setattr(system_api, 'BASE_DIR', 'D:/Workspace/MyOwn/ST-Manager')
    monkeypatch.setattr(system_api, '_shared_wallpaper_service', None, raising=False)
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    response = client.post('/api/save_settings', json={'manager_wallpaper_id': '', 'bg_url': '/legacy/background.png'})

    assert response.status_code == 200
    assert ui_data['_shared_wallpaper_library_v1']['manager_wallpaper_id'] == ''


def test_save_settings_preserves_existing_manager_wallpaper_when_field_is_omitted(monkeypatch):
    ui_data = {
        '_shared_wallpaper_library_v1': {
            'items': {},
            'manager_wallpaper_id': 'builtin:space/stars.png',
            'preview_wallpaper_id': '',
        }
    }

    monkeypatch.setattr(system_api, 'save_config', lambda cfg: True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: None)
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: 'cards')
    monkeypatch.setattr(system_api, 'BASE_DIR', 'D:/Workspace/MyOwn/ST-Manager')
    monkeypatch.setattr(system_api, '_shared_wallpaper_service', None, raising=False)
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    response = client.post('/api/save_settings', json={'bg_url': '/legacy/background.png'})

    assert response.status_code == 200
    assert ui_data['_shared_wallpaper_library_v1']['manager_wallpaper_id'] == 'builtin:space/stars.png'


def test_save_settings_does_not_forward_shared_wallpaper_ui_fields_to_config(monkeypatch):
    captured_configs = []

    monkeypatch.setattr(system_api, 'save_config', lambda cfg: captured_configs.append(dict(cfg)) or True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: None)
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: 'cards')
    monkeypatch.setattr(system_api, 'BASE_DIR', 'D:/Workspace/MyOwn/ST-Manager')
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    response = client.post(
        '/api/save_settings',
        json={
            'bg_url': '/legacy/background.png',
            'manager_wallpaper_id': 'imported:demo',
            'shared_wallpapers': [
                {'id': 'imported:demo', 'file': 'data/library/wallpapers/imported/demo.png'}
            ],
        },
    )

    assert response.status_code == 200
    assert captured_configs
    assert 'manager_wallpaper_id' not in captured_configs[-1]
    assert 'shared_wallpapers' not in captured_configs[-1]


def test_save_settings_drops_removed_legacy_st_preset_directory_keys(monkeypatch):
    captured_configs = []

    monkeypatch.setattr(system_api, 'save_config', lambda cfg: captured_configs.append(dict(cfg)) or True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: None)
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: 'cards')
    monkeypatch.setattr(system_api, 'BASE_DIR', 'D:/Workspace/MyOwn/ST-Manager')
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    response = client.post(
        '/api/save_settings',
        json={
            'st_openai_preset_dir': 'st/openai',
            'st_textgen_preset_dir': 'st/textgen',
            'st_instruct_preset_dir': 'st/instruct',
            'st_context_preset_dir': 'st/context',
            'st_sysprompt_dir': 'st/sysprompt',
            'st_reasoning_dir': 'st/reasoning',
        },
    )

    assert response.status_code == 200
    assert captured_configs
    assert captured_configs[-1]['st_openai_preset_dir'] == 'st/openai'
    assert 'st_textgen_preset_dir' not in captured_configs[-1]
    assert 'st_instruct_preset_dir' not in captured_configs[-1]
    assert 'st_context_preset_dir' not in captured_configs[-1]
    assert 'st_sysprompt_dir' not in captured_configs[-1]
    assert 'st_reasoning_dir' not in captured_configs[-1]


def test_settings_path_safety_endpoint_returns_evaluator_payload(monkeypatch):
    evaluation = {
        'risk_level': 'warning',
        'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
        'conflicts': [
            {
                'field': 'cards_dir',
                'label': '角色卡存储路径',
                'manager_path': 'D:/workspace/cards',
                'st_path': 'D:/SillyTavern/data/default-user/characters',
                'resource_type': 'characters',
                'severity': 'warning',
                'relation': 'same',
                'message': '当前路径与 SillyTavern characters 目录重叠，ST-Manager 的独立目录结构可能与酒馆目录混用。',
            }
        ],
        'blocked_actions': ['sync_all', 'sync_characters'],
    }
    monkeypatch.setattr(system_api, 'evaluate_st_path_safety', lambda cfg: evaluation)

    client = _make_test_app().test_client()
    res = client.post('/api/settings_path_safety', json={'config': {'st_data_dir': 'D:/SillyTavern'}})
    payload = res.get_json()

    assert res.status_code == 200
    assert payload == {'success': True, **evaluation}


def test_settings_path_safety_endpoint_accepts_legacy_flat_payload(monkeypatch):
    seen = {}
    evaluation = {
        'risk_level': 'none',
        'risk_summary': '当前路径配置安全。',
        'conflicts': [],
        'blocked_actions': [],
    }

    def fake_evaluate(cfg):
        seen['config'] = dict(cfg)
        return evaluation

    monkeypatch.setattr(system_api, 'evaluate_st_path_safety', fake_evaluate)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/settings_path_safety',
        json={'cards_dir': 'data/library/characters', 'st_data_dir': 'D:/SillyTavern'},
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload == {'success': True, **evaluation}
    assert seen['config'] == {
        'cards_dir': 'data/library/characters',
        'st_data_dir': 'D:/SillyTavern',
    }


def test_save_settings_requires_confirmation_before_persisting_risky_paths(monkeypatch):
    save_calls = []
    evaluation = {
        'risk_level': 'danger',
        'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
        'conflicts': [
            {
                'field': 'chats_dir',
                'label': '聊天记录路径',
                'manager_path': 'D:/SillyTavern/data/default-user/chats',
                'st_path': 'D:/SillyTavern/data/default-user/chats',
                'resource_type': 'chats',
                'severity': 'danger',
                'relation': 'same',
                'message': '当前聊天记录路径与 SillyTavern chats 目录重叠，同步聊天时可能覆盖同名聊天目录，因此聊天同步已被禁用。',
            }
        ],
        'blocked_actions': ['sync_all', 'sync_chats'],
    }
    monkeypatch.setattr(system_api, 'evaluate_st_path_safety', lambda cfg: evaluation)
    monkeypatch.setattr(system_api, 'save_config', lambda cfg: save_calls.append(dict(cfg)) or True)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/save_settings',
        json={
            'config': {
                'chats_dir': 'D:/SillyTavern/data/default-user/chats',
                'st_data_dir': 'D:/SillyTavern',
            },
            'confirm_risky_paths': False,
        },
    )
    payload = res.get_json()

    assert res.status_code == 409
    assert payload['success'] is False
    assert payload['requires_confirmation'] is True
    assert payload['blocked_actions'] == ['sync_all', 'sync_chats']
    assert save_calls == []


def test_save_settings_confirmed_request_persists_only_nested_config(monkeypatch, tmp_path):
    saved = {}
    evaluation = {
        'risk_level': 'warning',
        'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
        'conflicts': [
            {
                'field': 'cards_dir',
                'label': '角色卡存储路径',
                'manager_path': 'D:/SillyTavern/data/default-user/characters',
                'st_path': 'D:/SillyTavern/data/default-user/characters',
                'resource_type': 'characters',
                'severity': 'warning',
                'relation': 'same',
                'message': '当前路径与 SillyTavern characters 目录重叠，ST-Manager 的独立目录结构可能与酒馆目录混用。',
            }
        ],
        'blocked_actions': ['sync_all', 'sync_characters'],
    }
    refresh_calls = []
    monkeypatch.setattr(system_api, 'evaluate_st_path_safety', lambda cfg: evaluation)
    monkeypatch.setattr(system_api, 'save_config', lambda cfg: saved.setdefault('config', dict(cfg)) or True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: refresh_calls.append('called'))
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: str(tmp_path / 'cards'))
    monkeypatch.setattr(system_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/save_settings',
        json={
            'config': {
                'cards_dir': 'data/library/characters',
                'st_data_dir': 'D:/SillyTavern',
            },
            'confirm_risky_paths': True,
        },
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['success'] is True
    assert payload['saved_with_warnings'] is True
    assert payload['blocked_actions'] == ['sync_all', 'sync_characters']
    assert saved['config'] == {
        'cards_dir': 'data/library/characters',
        'st_data_dir': 'D:/SillyTavern',
    }
    assert refresh_calls == ['called']


def test_save_settings_legacy_flat_payload_does_not_persist_confirm_flag(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(
        system_api,
        'evaluate_st_path_safety',
        lambda cfg: {
            'risk_level': 'none',
            'risk_summary': '当前路径配置安全。',
            'conflicts': [],
            'blocked_actions': [],
        },
    )
    monkeypatch.setattr(system_api, 'save_config', lambda cfg: saved.setdefault('config', dict(cfg)) or True)
    monkeypatch.setattr(system_api, 'refresh_st_client', lambda: None)
    monkeypatch.setattr(system_api, 'get_cards_folder', lambda: str(tmp_path / 'cards'))
    monkeypatch.setattr(system_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(system_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(system_api, 'save_ui_data', lambda data, **_kwargs: True)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/save_settings',
        json={
            'cards_dir': 'data/library/characters',
            'st_data_dir': 'D:/SillyTavern',
            'confirm_risky_paths': True,
        },
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['success'] is True
    assert saved['config'] == {
        'cards_dir': 'data/library/characters',
        'st_data_dir': 'D:/SillyTavern',
    }


def test_select_shared_wallpaper_endpoint_delegates_to_service(monkeypatch):
    fake_service = FakeSharedWallpaperService()
    monkeypatch.setattr(system_api, 'get_shared_wallpaper_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/shared-wallpapers/select',
        json={
            'wallpaper_id': 'builtin:space/stars.png',
            'selection_target': 'manager',
        },
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['success'] is True
    assert payload['wallpaper_id'] == 'builtin:space/stars.png'
    assert payload['selection_target'] == 'manager'
    assert fake_service.calls == [('select_wallpaper', 'builtin:space/stars.png', 'manager')]


def test_user_db_backup_export_endpoint_delegates_to_service(monkeypatch):
    fake_service = FakeUserDbBackupService()
    monkeypatch.setattr(system_api, 'get_user_db_backup_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/user-db-backup/export')
    payload = res.get_json()

    assert res.status_code == 200
    assert payload == {
        'success': True,
        'msg': '已备份用户 DB 数据',
        'backup_path': 'data/backups/user-db.json',
    }
    assert fake_service.calls == [('export_backup',)]


def test_user_db_backup_import_endpoint_rejects_missing_json_file(monkeypatch):
    fake_service = FakeUserDbBackupService()
    monkeypatch.setattr(system_api, 'get_user_db_backup_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post('/api/user-db-backup/import', data={}, content_type='multipart/form-data')
    payload = res.get_json()

    assert res.status_code == 400
    assert payload == {'success': False, 'msg': '请上传 JSON 备份文件'}
    assert fake_service.calls == []


def test_user_db_backup_import_endpoint_delegates_to_service_with_original_filename(monkeypatch):
    fake_service = FakeUserDbBackupService()
    monkeypatch.setattr(system_api, 'get_user_db_backup_service', lambda: fake_service, raising=False)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/user-db-backup/import',
        data={
            'file': (io.BytesIO(b'{"schema_version": 1}'), 'user-backup.json'),
        },
        content_type='multipart/form-data',
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload == {
        'success': True,
        'msg': '用户 DB 数据导入完成',
        'imported': True,
        'source_name': 'user-backup.json',
    }
    assert fake_service.calls
    assert fake_service.calls[0][0] == 'import_backup'
    assert fake_service.calls[0][2] == 'user-backup.json'
