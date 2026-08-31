import io
import json
import sys
import types
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import beautify as beautify_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(beautify_api.bp)
    return app


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, text='', content=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content if content is not None else (b'{}' if json_data is not None else text.encode('utf-8'))

    def json(self):
        if self._json_data is None:
            raise ValueError('No JSON payload')
        return self._json_data


class FakeSequencedHTTPClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, path, **kwargs):
        self.calls.append((path, dict(kwargs)))
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError(f'unexpected ST call: {path}')
        return self.responses.pop(0)


def _install_send_theme_stubs(monkeypatch, fake_http_client, *, ui_data=None, save_result=True, sent_at=1712345678.25):
    saved_payloads = []
    current_ui_data = dict(ui_data or {})

    monkeypatch.setattr(beautify_api, 'load_config', lambda: {'st_auth_type': 'basic'}, raising=False)
    monkeypatch.setattr(beautify_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client, raising=False)
    monkeypatch.setattr(beautify_api, 'load_ui_data', lambda: current_ui_data, raising=False)
    monkeypatch.setattr(beautify_api, 'save_ui_data', lambda payload: saved_payloads.append(dict(payload)) or save_result, raising=False)
    monkeypatch.setattr(beautify_api, 'time', types.SimpleNamespace(time=lambda: sent_at), raising=False)

    return current_ui_data, saved_payloads, sent_at


class FakeBeautifyService:
    def __init__(self):
        self.calls = []
        self.library_root = 'D:/Workspace/MyOwn/ST-Manager/data/library/beautify'
        self.theme_bundle = {
            'package': {'id': 'pkg_demo', 'name': 'Demo'},
            'variant': {'id': 'var_demo', 'theme_data': {'name': 'Demo Theme', 'main_text_color': '#ffffff'}},
            'theme_data': {
                'name': 'Demo Theme',
                'main_text_color': '#ffffff',
            },
        }

    def get_global_settings(self):
        self.calls.append(('get_global_settings',))
        return {
            'preview_wallpaper_id': 'shared:preview',
            'wallpaper': {'file': 'global/wallpapers/demo.png', 'filename': 'demo.png'},
            'identities': {
                'character': {'name': 'Demo Character', 'avatar_file': 'global/avatars/character.png'},
                'user': {'name': 'Demo User', 'avatar_file': 'global/avatars/user.png'},
            },
        }

    def update_global_settings(self, payload=None):
        self.calls.append(('update_global_settings', payload))
        return {
            'preview_wallpaper_id': 'shared:updated',
            'wallpaper': {'file': 'global/wallpapers/updated.png', 'filename': 'updated.png'},
            'identities': {
                'character': {
                    'name': payload.get('character_name', '') if isinstance(payload, dict) else '',
                    'avatar_file': '',
                },
                'user': {
                    'name': payload.get('user_name', '') if isinstance(payload, dict) else '',
                    'avatar_file': '',
                },
            },
        }

    def import_global_wallpaper(self, source_path, source_name=None):
        self.calls.append(('import_global_wallpaper', source_path, source_name))
        return {'wallpaper': {'name': source_name or 'wallpaper.png'}}

    def import_global_avatar(self, target, source_path, source_name=None):
        self.calls.append(('import_global_avatar', target, source_path, source_name))
        return {
            'identity': {
                'target': target,
                'avatar_file': f'global/avatars/{source_name or "avatar.png"}',
            }
        }

    def import_screenshot(self, package_id, source_path, source_name=None):
        self.calls.append(('import_screenshot', package_id, source_path, source_name))
        return {'package_id': package_id, 'screenshot': {'name': source_name or 'shot.png'}}

    def update_package_identities(self, package_id, identities_payload=None):
        self.calls.append(('update_package_identities', package_id, identities_payload))
        return {
            'package_id': package_id,
            'identity_overrides': {
                'character': {
                    'name': identities_payload.get('character_name', '') if isinstance(identities_payload, dict) else '',
                    'avatar_file': '',
                },
                'user': {
                    'name': identities_payload.get('user_name', '') if isinstance(identities_payload, dict) else '',
                    'avatar_file': '',
                },
            },
        }

    def import_package_avatar(self, package_id, target, source_path, source_name=None):
        self.calls.append(('import_package_avatar', package_id, target, source_path, source_name))
        return {
            'package_id': package_id,
            'identity': {
                'target': target,
                'avatar_file': f'packages/{package_id}/avatars/{source_name or "avatar.png"}',
            },
        }

    def list_packages(self):
        self.calls.append(('list_packages',))
        return [{'id': 'pkg_demo', 'name': 'Demo', 'platforms': ['pc'], 'screenshot_count': 2}]

    def get_package(self, package_id):
        self.calls.append(('get_package', package_id))
        if package_id == 'missing':
            return None
        return {
            'id': package_id,
            'name': 'Demo',
            'variants': {},
            'wallpapers': {},
            'screenshots': {'shot_demo': {'id': 'shot_demo', 'file': 'packages/pkg_demo/screenshots/demo.png'}},
            'identity_overrides': {
                'character': {'name': 'Hero', 'avatar_file': ''},
                'user': {'name': '', 'avatar_file': 'packages/pkg_demo/avatars/user.png'},
            },
        }

    def import_theme(self, source_path, package_id=None, platform=None, source_name=None):
        self.calls.append(('import_theme', source_path, package_id, platform, source_name))
        return {
            'package': {'id': package_id or 'pkg_demo', 'name': 'Demo'},
            'variant': {'id': 'var_demo', 'platform': platform or 'dual'},
        }

    def import_wallpaper(self, package_id, variant_id, source_path, source_name=None):
        self.calls.append(('import_wallpaper', package_id, variant_id, source_path, source_name))
        return {
            'package': {'id': package_id, 'name': 'Demo'},
            'variant': {'id': variant_id},
            'wallpaper': {'id': 'wp_demo', 'variant_id': variant_id},
        }

    def update_variant(self, package_id, variant_id, platform=None, selected_wallpaper_id=''):
        self.calls.append(('update_variant', package_id, variant_id, platform, selected_wallpaper_id))
        return {
            'id': variant_id,
            'platform': platform or 'pc',
            'selected_wallpaper_id': selected_wallpaper_id,
        }

    def get_variant_send_state_key(self, package_id, variant_id):
        self.calls.append(('get_variant_send_state_key', package_id, variant_id))
        return f'beautify::{package_id}::{variant_id}'

    def build_sendable_theme_bundle(self, package_id, variant_id):
        self.calls.append(('build_sendable_theme_bundle', package_id, variant_id))
        return self.theme_bundle

    def delete_package(self, package_id):
        self.calls.append(('delete_package', package_id))
        return True

    def get_preview_asset_path(self, subpath):
        self.calls.append(('get_preview_asset_path', subpath))
        if subpath == 'packages/pkg_demo/wallpapers/demo.png':
            return __file__
        return None


def test_list_endpoint_returns_package_summaries(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.get('/api/beautify/list')
    payload = response.get_json()

    assert payload['success'] is True
    assert payload['items'][0]['id'] == 'pkg_demo'
    assert payload['items'][0]['screenshot_count'] == 2
    assert ('list_packages',) in fake_service.calls


def test_detail_endpoint_returns_identity_overrides_and_screenshots(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.get('/api/beautify/pkg_demo')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['screenshots']['shot_demo']['id'] == 'shot_demo'
    assert payload['item']['identity_overrides']['character']['name'] == 'Hero'


def test_detail_endpoint_returns_404_for_missing_package(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.get('/api/beautify/missing')
    payload = response.get_json()

    assert response.status_code == 404
    assert payload['success'] is False


def test_import_theme_endpoint_requires_uploaded_json_file(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post('/api/beautify/import-theme', data={}, content_type='multipart/form-data')
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_theme_endpoint_forwards_optional_target_package_and_platform(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-theme',
        data={
            'file': (io.BytesIO(b'{"name": "Demo", "main_text_color": "#fff"}'), 'demo.json'),
            'package_id': 'pkg_demo',
            'platform': 'pc',
        },
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_theme'
    assert fake_service.calls[0][2:4] == ('pkg_demo', 'pc')


def test_import_theme_endpoint_forwards_package_scoped_variant_import_fields(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-theme',
        data={
            'file': (io.BytesIO(b'{"name": "Variant Demo", "main_text_color": "#fff"}'), 'variant-demo.json'),
            'package_id': 'pkg_variant_demo',
            'platform': 'mobile',
        },
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_theme'
    assert fake_service.calls[0][2] == 'pkg_variant_demo'
    assert fake_service.calls[0][3] == 'mobile'
    assert fake_service.calls[0][4] == 'variant-demo.json'


def test_import_wallpaper_endpoint_requires_package_and_variant(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-wallpaper',
        data={'file': (io.BytesIO(b'png'), 'demo.png')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 400


def test_import_wallpaper_endpoint_returns_400_for_invalid_image_upload(tmp_path):
    app = _make_test_app()
    client = app.test_client()
    beautify_api._service = beautify_api.BeautifyService(library_root=tmp_path / 'data' / 'library' / 'beautify')

    theme_file = tmp_path / 'theme_pc.json'
    theme_file.write_text(json.dumps({'name': 'Demo', 'main_text_color': '#fff'}, ensure_ascii=False), encoding='utf-8')
    imported_theme = beautify_api._service.import_theme(str(theme_file), platform='pc')

    try:
        response = client.post(
            '/api/beautify/import-wallpaper',
            data={
                'package_id': imported_theme['package']['id'],
                'variant_id': imported_theme['variant']['id'],
                'file': (io.BytesIO(b'not-an-image'), 'wallpaper.png'),
            },
            content_type='multipart/form-data',
        )
        payload = response.get_json()
    finally:
        beautify_api._service = None

    assert response.status_code == 400
    assert payload['success'] is False


def test_get_settings_endpoint_returns_global_settings(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.get('/api/beautify/settings')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['preview_wallpaper_id'] == 'shared:preview'
    assert payload['item']['wallpaper']['filename'] == 'demo.png'
    assert payload['item']['identities']['character']['name'] == 'Demo Character'
    assert ('get_global_settings',) in fake_service.calls


def test_get_settings_endpoint_preserves_selected_preview_wallpaper_object(monkeypatch):
    app = _make_test_app()
    client = app.test_client()

    class PreviewWallpaperService(FakeBeautifyService):
        def get_global_settings(self):
            self.calls.append(('get_global_settings',))
            return {
                'preview_wallpaper_id': 'shared:preview',
                'wallpaper': {
                    'id': 'shared:preview',
                    'file': 'data/library/wallpapers/imported/preview.png',
                    'filename': 'preview.png',
                    'source_type': 'imported',
                },
                'identities': {
                    'character': {'name': 'Demo Character', 'avatar_file': 'global/avatars/character.png'},
                    'user': {'name': 'Demo User', 'avatar_file': 'global/avatars/user.png'},
                },
            }

    fake_service = PreviewWallpaperService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.get('/api/beautify/settings')
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['preview_wallpaper_id'] == 'shared:preview'
    assert payload['item']['wallpaper'] == {
        'id': 'shared:preview',
        'file': 'data/library/wallpapers/imported/preview.png',
        'filename': 'preview.png',
        'source_type': 'imported',
    }


def test_update_settings_endpoint_forwards_json_payload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        json={
            'character_name': 'Updated Character',
            'user_name': '',
            'clear_wallpaper': True,
            'clear_character_avatar': True,
            'clear_user_avatar': False,
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['preview_wallpaper_id'] == 'shared:updated'
    assert payload['item']['wallpaper']['filename'] == 'updated.png'
    assert payload['item']['identities']['character']['name'] == 'Updated Character'
    assert fake_service.calls[0] == (
        'update_global_settings',
        {
            'character_name': 'Updated Character',
            'user_name': '',
            'clear_wallpaper': True,
            'clear_character_avatar': True,
            'clear_user_avatar': False,
        },
    )


def test_update_settings_endpoint_does_not_forward_nested_avatar_updates(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        json={
            'character_name': 'Updated Character',
            'identities': {'character': {'avatar_file': 'should/not/pass.png'}},
            'avatar_file': 'should/not/pass.png',
        },
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_settings_endpoint_preserves_omitted_name_fields(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        json={'clear_wallpaper': True},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0] == (
        'update_global_settings',
        {
            'clear_wallpaper': True,
            'clear_character_avatar': False,
            'clear_user_avatar': False,
        },
    )


def test_update_settings_endpoint_rejects_unsupported_keys(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        json={'avatar_file': 'bad.png', 'identities': {'character': {'name': 'bad'}}},
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_settings_endpoint_rejects_non_dict_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        data=json.dumps(['not', 'a', 'dict']),
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_settings_endpoint_rejects_malformed_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        data='{"character_name": ',
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_settings_endpoint_rejects_wrong_content_type(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        data='character_name=Alice',
        content_type='text/plain',
    )
    payload = response.get_json()

    assert response.status_code in (400, 415)
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_settings_endpoint_ignores_non_boolean_clear_flags(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-settings',
        json={
            'character_name': 'Updated Character',
            'clear_wallpaper': 'false',
            'clear_character_avatar': 1,
            'clear_user_avatar': 'true',
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0] == (
        'update_global_settings',
        {
            'character_name': 'Updated Character',
            'clear_wallpaper': False,
            'clear_character_avatar': False,
            'clear_user_avatar': False,
        },
    )


def test_import_global_wallpaper_endpoint_requires_upload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post('/api/beautify/import-global-wallpaper', data={}, content_type='multipart/form-data')
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_global_wallpaper_endpoint_forwards_upload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-global-wallpaper',
        data={'file': (io.BytesIO(b'png'), 'wallpaper.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_global_wallpaper'
    assert fake_service.calls[0][2] == 'wallpaper.png'


def test_import_global_avatar_endpoint_requires_target(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-global-avatar',
        data={'file': (io.BytesIO(b'png'), 'avatar.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_global_avatar_endpoint_rejects_invalid_target(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-global-avatar',
        data={'target': 'bot', 'file': (io.BytesIO(b'png'), 'avatar.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_global_avatar_endpoint_forwards_target_and_upload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-global-avatar',
        data={'target': 'character', 'file': (io.BytesIO(b'png'), 'avatar.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_global_avatar'
    assert fake_service.calls[0][1] == 'character'
    assert payload['identity']['target'] == 'character'
    assert payload['identity']['avatar_file'].endswith('avatar.png')
    assert fake_service.calls[0][3] == 'avatar.png'


def test_import_screenshot_endpoint_requires_package_id(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-screenshot',
        data={'file': (io.BytesIO(b'png'), 'shot.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_screenshot_endpoint_forwards_package_id_and_upload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-screenshot',
        data={'package_id': 'pkg_demo', 'file': (io.BytesIO(b'png'), 'shot.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_screenshot'
    assert fake_service.calls[0][1] == 'pkg_demo'
    assert fake_service.calls[0][3] == 'shot.png'


def test_update_package_identities_endpoint_requires_package_id(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post('/api/beautify/update-package-identities', json={'name': 'Demo'})
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_package_identities_endpoint_rejects_malformed_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        data='{"package_id": ',
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_package_identities_endpoint_forwards_json_payload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        json={
            'package_id': 'pkg_demo',
            'character_name': 'Hero',
            'user_name': 'Player',
            'clear_character_avatar': True,
            'clear_user_avatar': False,
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['identity_overrides']['character']['name'] == 'Hero'
    assert fake_service.calls[0] == (
        'update_package_identities',
        'pkg_demo',
        {
            'character_name': 'Hero',
            'user_name': 'Player',
            'clear_character_avatar': True,
            'clear_user_avatar': False,
        },
    )


def test_update_package_identities_endpoint_does_not_forward_nested_avatar_updates(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        json={
            'package_id': 'pkg_demo',
            'character_name': 'Hero',
            'character': {'avatar_file': 'should/not/pass.png'},
            'clear_user_avatar': True,
        },
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_package_identities_endpoint_preserves_omitted_name_fields(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        json={
            'package_id': 'pkg_demo',
            'clear_user_avatar': True,
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0] == (
        'update_package_identities',
        'pkg_demo',
        {
            'clear_character_avatar': False,
            'clear_user_avatar': True,
        },
    )


def test_update_package_identities_endpoint_rejects_unsupported_keys(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        json={
            'package_id': 'pkg_demo',
            'avatar_file': 'bad.png',
            'character': {'avatar_file': 'bad.png'},
        },
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_package_identities_endpoint_ignores_non_boolean_clear_flags(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-package-identities',
        json={
            'package_id': 'pkg_demo',
            'character_name': 'Hero',
            'clear_character_avatar': 'false',
            'clear_user_avatar': 1,
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0] == (
        'update_package_identities',
        'pkg_demo',
        {
            'character_name': 'Hero',
            'clear_character_avatar': False,
            'clear_user_avatar': False,
        },
    )


def test_update_variant_endpoint_rejects_malformed_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-variant',
        data='{"package_id": ',
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_update_variant_endpoint_rejects_non_dict_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-variant',
        data=json.dumps(['not', 'a', 'dict']),
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_package_avatar_endpoint_requires_package_id_and_target(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-package-avatar',
        data={'file': (io.BytesIO(b'png'), 'avatar.png')},
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_package_avatar_endpoint_rejects_invalid_target(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-package-avatar',
        data={
            'package_id': 'pkg_demo',
            'target': 'bot',
            'file': (io.BytesIO(b'png'), 'avatar.png'),
        },
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_import_package_avatar_endpoint_forwards_payload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/import-package-avatar',
        data={
            'package_id': 'pkg_demo',
            'target': 'user',
            'file': (io.BytesIO(b'png'), 'avatar.png'),
        },
        content_type='multipart/form-data',
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert fake_service.calls[0][0] == 'import_package_avatar'
    assert payload['identity']['target'] == 'user'
    assert payload['identity']['avatar_file'].endswith('avatar.png')
    assert fake_service.calls[0][1:3] == ('pkg_demo', 'user')
    assert fake_service.calls[0][4] == 'avatar.png'


def test_update_variant_endpoint_rejects_invalid_platform(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post('/api/beautify/update-variant', json={'package_id': 'pkg_demo', 'variant_id': 'var_demo', 'platform': 'tablet'})
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False


def test_update_variant_endpoint_forwards_selected_wallpaper_id_without_requiring_platform(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/update-variant',
        json={
            'package_id': 'pkg_demo',
            'variant_id': 'var_demo',
            'selected_wallpaper_id': 'package_embedded:wall_new',
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['item']['selected_wallpaper_id'] == 'package_embedded:wall_new'
    assert fake_service.calls[-1] == (
        'update_variant',
        'pkg_demo',
        'var_demo',
        None,
        'package_embedded:wall_new',
    )


def test_send_theme_to_st_updates_remote_theme_and_current_setting(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    fake_http_client = FakeSequencedHTTPClient(
        responses=[
            DummyResponse(200, json_data={'saved': True}),
            DummyResponse(200, json_data={'settings': json.dumps({'power_user': {'theme': 'Old Theme'}}, ensure_ascii=False)}),
            DummyResponse(200, json_data={'applied': True}),
        ]
    )
    ui_data, saved_payloads, sent_at = _install_send_theme_stubs(monkeypatch, fake_http_client)
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/send-theme-to-st',
        json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['theme_name'] == 'Demo Theme'
    assert payload['st_response'] == {'saved': True}
    assert payload['last_sent_to_st'] == sent_at
    assert fake_http_client.calls == [
        (
            '/api/themes/save',
            {
                'json': {'name': 'Demo Theme', 'main_text_color': '#ffffff'},
                'timeout': 10,
            },
        ),
        (
            '/api/settings/get',
            {
                'json': {},
                'timeout': 10,
            },
        ),
        (
            '/api/settings/save',
            {
                'json': {'power_user': {'theme': 'Demo Theme'}},
                'timeout': 10,
            },
        ),
    ]
    assert ui_data == {'beautify::pkg_demo::var_demo': {'last_sent_to_st': sent_at}}
    assert saved_payloads == [{'beautify::pkg_demo::var_demo': {'last_sent_to_st': sent_at}}]


def test_send_theme_to_st_success_accepts_plain_text_theme_save_response(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    fake_http_client = FakeSequencedHTTPClient(
        responses=[
            DummyResponse(200, json_data=None, text='saved-ok', content=b'saved-ok'),
            DummyResponse(200, json_data={'settings': json.dumps({'power_user': {'theme': 'Old Theme'}}, ensure_ascii=False)}),
            DummyResponse(200, json_data={'applied': True}),
        ]
    )
    _ui_data, _saved_payloads, sent_at = _install_send_theme_stubs(monkeypatch, fake_http_client)
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/send-theme-to-st',
        json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['success'] is True
    assert payload['theme_name'] == 'Demo Theme'
    assert payload['st_response'] == 'saved-ok'
    assert payload['last_sent_to_st'] == sent_at


def test_send_theme_to_st_rejects_missing_variant_id(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)
    monkeypatch.setattr(
        beautify_api,
        'load_config',
        lambda: (_ for _ in ()).throw(AssertionError('load_config should not be called')),
        raising=False,
    )

    response = client.post('/api/beautify/send-theme-to-st', json={'package_id': 'pkg_demo'})
    payload = response.get_json()

    assert response.status_code == 400
    assert payload == {'success': False, 'error': '缺少 package_id 或 variant_id'}
    assert fake_service.calls == []


def test_send_theme_to_st_reports_invalid_st_settings_payload(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    fake_http_client = FakeSequencedHTTPClient(
        responses=[
            DummyResponse(200, json_data={'saved': True}),
            DummyResponse(200, json_data={'settings': {'power_user': {'theme': 'Old Theme'}}}),
        ]
    )
    ui_data, saved_payloads, _sent_at = _install_send_theme_stubs(monkeypatch, fake_http_client)
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/send-theme-to-st',
        json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'},
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert payload['error'] == '主题已导入 ST，但自动应用失败：远程设置数据无效'
    assert ui_data == {}
    assert saved_payloads == []


def test_send_theme_to_st_reports_partial_failure_without_persisting_timestamp(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    fake_http_client = FakeSequencedHTTPClient(
        responses=[
            DummyResponse(200, json_data={'saved': True}),
            DummyResponse(200, json_data={'settings': json.dumps({'power_user': {'theme': 'Old Theme'}}, ensure_ascii=False)}),
            DummyResponse(500, json_data={'error': 'save failed'}, text='save failed'),
        ]
    )
    ui_data, saved_payloads, _sent_at = _install_send_theme_stubs(monkeypatch, fake_http_client)
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/send-theme-to-st',
        json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'},
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert payload['error'] == '主题已导入 ST，但自动应用失败：ST Error: 500 - save failed'
    assert ui_data == {}
    assert saved_payloads == []


def test_install_and_apply_endpoints_are_removed(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    install_response = client.post('/api/beautify/install', json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'})
    apply_response = client.post('/api/beautify/apply', json={'package_id': 'pkg_demo', 'variant_id': 'var_demo'})

    assert install_response.status_code in (404, 405)
    assert apply_response.status_code in (404, 405)


def test_delete_package_endpoint_requires_package_id(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post('/api/beautify/delete-package', json={})
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False


def test_delete_package_endpoint_rejects_malformed_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/delete-package',
        data='{"package_id": ',
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_delete_package_endpoint_rejects_non_dict_json(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    response = client.post(
        '/api/beautify/delete-package',
        data=json.dumps(['not', 'a', 'dict']),
        content_type='application/json',
    )
    payload = response.get_json()

    assert response.status_code == 400
    assert payload['success'] is False
    assert fake_service.calls == []


def test_delete_package_endpoint_returns_json_when_package_files_are_locked(monkeypatch):
    app = _make_test_app()
    client = app.test_client()

    class LockedBeautifyService(FakeBeautifyService):
        def delete_package(self, package_id):
            raise PermissionError('simulated Windows file lock')

    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: LockedBeautifyService())

    response = client.post('/api/beautify/delete-package', json={'package_id': 'pkg_demo'})
    payload = response.get_json()

    assert response.status_code == 409
    assert response.is_json
    assert payload == {
        'success': False,
        'error': '美化包文件仍被占用，请关闭预览后重试',
    }


def test_import_global_wallpaper_endpoint_returns_400_for_invalid_image_upload(tmp_path):
    app = _make_test_app()
    client = app.test_client()
    beautify_api._service = beautify_api.BeautifyService(library_root=tmp_path / 'data' / 'library' / 'beautify')

    try:
        response = client.post(
            '/api/beautify/import-global-wallpaper',
            data={'file': (io.BytesIO(b'not-an-image'), 'wallpaper.png')},
            content_type='multipart/form-data',
        )
        payload = response.get_json()
    finally:
        beautify_api._service = None

    assert response.status_code == 400
    assert payload['success'] is False


def test_preview_asset_endpoint_blocks_unknown_paths(monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    fake_service = FakeBeautifyService()
    monkeypatch.setattr(beautify_api, 'get_beautify_service', lambda: fake_service)

    blocked = client.get('/api/beautify/preview-asset/../../evil.txt')
    allowed = client.get('/api/beautify/preview-asset/packages/pkg_demo/wallpapers/demo.png')

    assert blocked.status_code == 404
    assert allowed.status_code == 200


def test_preview_asset_endpoint_serves_shared_imported_wallpaper_path(tmp_path):
    app = _make_test_app()
    client = app.test_client()
    beautify_api._service = beautify_api.BeautifyService(library_root=tmp_path / 'data' / 'library' / 'beautify')

    imported_wallpaper = tmp_path / 'data' / 'library' / 'wallpapers' / 'imported' / 'preview.png'
    imported_wallpaper.parent.mkdir(parents=True, exist_ok=True)
    imported_wallpaper.write_bytes(b'preview-bytes')

    try:
        response = client.get('/api/beautify/preview-asset/data/library/wallpapers/imported/preview.png')
    finally:
        beautify_api._service = None

    assert response.status_code == 200
    assert response.data == b'preview-bytes'
