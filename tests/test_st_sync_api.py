import os
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import st_sync as st_sync_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(st_sync_api.bp)
    return app


class GuardClient:
    def __init__(self, *args, **kwargs):
        raise AssertionError('ST client should not be created for blocked syncs')


class FakeClient:
    def __init__(self):
        self.calls = []

    def sync_all_resources(self, resource_type, target_dir, use_api):
        self.calls.append(('sync_all_resources', resource_type, target_dir, use_api))
        return {'success': 2, 'failed': 0, 'skipped': 0, 'errors': [], 'synced': ['a', 'b']}


class ScriptListClient:
    st_user_handle = 'alice'

    def list_scripts(self, use_api=False):
        return [
            {
                'id': 'script-one',
                'name': 'One',
                'type': 'script',
                'data': {'type': 'script', 'id': 'script-one', 'name': 'One'},
            }
        ]


def test_sync_rejects_blocked_single_resource_before_client_creation(monkeypatch):
    monkeypatch.setattr(st_sync_api, 'load_config', lambda: {'chats_dir': 'data/library/chats'})
    monkeypatch.setattr(
        st_sync_api,
        'evaluate_st_path_safety',
        lambda config: {
            'risk_level': 'danger',
            'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
            'conflicts': [
                {
                    'field': 'chats_dir',
                    'label': '聊天记录路径',
                    'manager_path': 'D:/manager/chats',
                    'st_path': 'D:/SillyTavern/data/default-user/chats',
                    'resource_type': 'chats',
                    'severity': 'danger',
                    'relation': 'same',
                    'message': 'blocked',
                }
            ],
            'blocked_actions': ['sync_all', 'sync_chats'],
        },
    )
    monkeypatch.setattr(st_sync_api, 'STClient', GuardClient)
    monkeypatch.setattr(st_sync_api, 'get_st_client', lambda: GuardClient())

    client = _make_test_app().test_client()
    res = client.post(
        '/api/st/sync',
        json={
            'resource_type': 'chats',
            'resource_ids': ['chat-1'],
            'st_data_dir': 'D:/SillyTavern',
        },
    )
    payload = res.get_json()

    assert res.status_code == 409
    assert payload == {
        'success': False,
        'error': '当前路径配置禁止执行该同步操作。',
        'blocked_action': 'sync_chats',
        'path_safety': {
            'risk_level': 'danger',
            'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
            'conflicts': [
                {
                    'field': 'chats_dir',
                    'label': '聊天记录路径',
                    'manager_path': 'D:/manager/chats',
                    'st_path': 'D:/SillyTavern/data/default-user/chats',
                    'resource_type': 'chats',
                    'severity': 'danger',
                    'relation': 'same',
                    'message': 'blocked',
                }
            ],
            'blocked_actions': ['sync_all', 'sync_chats'],
        },
    }


def test_sync_all_rejects_when_path_safety_blocks_underlying_resource(monkeypatch):
    monkeypatch.setattr(st_sync_api, 'load_config', lambda: {'cards_dir': 'data/library/characters'})
    monkeypatch.setattr(
        st_sync_api,
        'evaluate_st_path_safety',
        lambda config: {
            'risk_level': 'warning',
            'risk_summary': '检测到 1 个路径与 SillyTavern 目录重叠。',
            'conflicts': [
                {
                    'field': 'cards_dir',
                    'label': '角色卡存储路径',
                    'manager_path': 'D:/manager/cards',
                    'st_path': 'D:/SillyTavern/data/default-user/characters',
                    'resource_type': 'characters',
                    'severity': 'warning',
                    'relation': 'same',
                    'message': 'blocked',
                }
            ],
            'blocked_actions': ['sync_all', 'sync_characters'],
        },
    )
    monkeypatch.setattr(st_sync_api, 'STClient', GuardClient)
    monkeypatch.setattr(st_sync_api, 'get_st_client', lambda: GuardClient())

    client = _make_test_app().test_client()
    res = client.post(
        '/api/st/sync',
        json={
            'resource_type': 'characters',
            'st_data_dir': 'D:/SillyTavern',
        },
    )
    payload = res.get_json()

    assert res.status_code == 409
    assert payload['blocked_action'] == 'sync_characters'
    assert payload['path_safety']['blocked_actions'] == ['sync_all', 'sync_characters']


def test_sync_unknown_resource_type_returns_legacy_400_before_path_safety(monkeypatch):
    monkeypatch.setattr(st_sync_api, 'load_config', lambda: {'cards_dir': 'data/library/characters'})

    def fail_if_called(config):
        raise AssertionError('path safety should not run for unsupported resource types')

    monkeypatch.setattr(st_sync_api, 'evaluate_st_path_safety', fail_if_called)
    monkeypatch.setattr(st_sync_api, 'STClient', GuardClient)
    monkeypatch.setattr(st_sync_api, 'get_st_client', lambda: GuardClient())

    client = _make_test_app().test_client()
    res = client.post(
        '/api/st/sync',
        json={
            'resource_type': 'unknown_resource',
            'st_data_dir': 'D:/SillyTavern',
        },
    )
    payload = res.get_json()

    assert res.status_code == 400
    assert payload == {
        'success': False,
        'error': '未知资源类型: unknown_resource',
    }


def test_script_list_and_detail_routes_expose_js_slash_runner_resources(monkeypatch):
    fake_client = ScriptListClient()
    monkeypatch.setattr(st_sync_api, 'STClient', lambda **_kwargs: fake_client)

    client = _make_test_app().test_client()
    list_response = client.get(
        '/api/st/list/scripts',
        query_string={'st_data_dir': 'D:/SillyTavern'},
    )
    detail_response = client.get(
        '/api/st/get/scripts/script-one',
        query_string={'st_data_dir': 'D:/SillyTavern'},
    )

    assert list_response.status_code == 200
    assert list_response.get_json()['count'] == 1
    assert list_response.get_json()['items'][0]['id'] == 'script-one'
    assert detail_response.status_code == 200
    assert detail_response.get_json()['item']['data']['name'] == 'One'


def test_sync_safe_request_delegates_to_client_as_before(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        st_sync_api,
        'load_config',
        lambda: {
            'cards_dir': 'data/library/characters',
            'chats_dir': 'data/library/chats',
            'world_info_dir': 'data/library/lorebooks',
            'presets_dir': 'data/library/presets',
            'regex_dir': 'data/library/extensions/regex',
            'quick_replies_dir': 'data/library/extensions/quick-replies',
            'st_data_dir': 'D:/SillyTavern',
        },
    )
    monkeypatch.setattr(
        st_sync_api,
        'evaluate_st_path_safety',
        lambda config: {
            'risk_level': 'none',
            'risk_summary': '当前路径配置安全。',
            'conflicts': [],
            'blocked_actions': [],
        },
    )
    monkeypatch.setattr(st_sync_api, 'STClient', lambda st_data_dir='': fake_client)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/st/sync',
        json={
            'resource_type': 'characters',
            'st_data_dir': 'D:/SillyTavern',
            'use_api': True,
        },
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload['success'] is True
    assert payload['resource_type'] == 'characters'
    assert len(fake_client.calls) == 1
    call_name, resource_type, target_dir, use_api = fake_client.calls[0]
    assert call_name == 'sync_all_resources'
    assert resource_type == 'characters'
    assert os.path.normpath(target_dir) == os.path.join(str(ROOT), 'data', 'library', 'characters')
    assert use_api is True
