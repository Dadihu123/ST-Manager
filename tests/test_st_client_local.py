import json
import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import st_sync as st_sync_api
from core.services.st_client import STClient


def _make_st_user(tmp_path: Path, handle: str = 'alice'):
    root = tmp_path / 'SillyTavern'
    user_dir = root / 'data' / handle
    for name in ('characters', 'chats', 'worlds', 'OpenAI Settings', 'regex', 'QuickReplies'):
        (user_dir / name).mkdir(parents=True, exist_ok=True)
    return root, user_dir


def _write_resource_fixture(user_dir: Path):
    (user_dir / 'worlds' / 'lore.json').write_text(
        json.dumps({'name': 'Lore', 'entries': {}}),
        encoding='utf-8',
    )
    (user_dir / 'OpenAI Settings' / 'openai.json').write_text(
        json.dumps({'name': 'OpenAI', 'temperature': 0.7}),
        encoding='utf-8',
    )
    (user_dir / 'regex' / 'global.json').write_text(
        json.dumps({'scriptName': 'Global', 'findRegex': '/foo/g', 'replaceString': 'bar'}),
        encoding='utf-8',
    )
    (user_dir / 'QuickReplies' / 'common.json').write_text(
        json.dumps({'name': 'Common', 'qrList': []}),
        encoding='utf-8',
    )
    (user_dir / 'chats' / 'Alice').mkdir(parents=True, exist_ok=True)
    (user_dir / 'chats' / 'Alice' / 'session.jsonl').write_text(
        '{"mes":"hello"}\n',
        encoding='utf-8',
    )
    (user_dir / 'settings.json').write_text(
        json.dumps({
            'extension_settings': {
                'regex': [
                    {
                        'scriptName': 'Settings Global',
                        'findRegex': '/settings/g',
                        'replaceString': 'value',
                    }
                ],
                'tavern_helper': {
                    'script': {
                        'scripts': [
                            {
                                'type': 'script',
                                'id': 'script-one',
                                'name': 'One',
                                'content': 'console.log("one")',
                                'button': {'enabled': True, 'buttons': []},
                                'data': {'scope': 'global'},
                                'export_with': {'data': True, 'button': True},
                            },
                            {
                                'type': 'folder',
                                'id': 'folder-one',
                                'name': 'Folder One',
                                'scripts': [
                                    {
                                        'type': 'script',
                                        'id': 'script-two',
                                        'name': 'Two',
                                        'content': 'console.log("two")',
                                    }
                                ],
                            },
                        ]
                    }
                },
            }
        }),
        encoding='utf-8',
    )


def test_st_client_reads_configured_user_directory_from_install_root(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)

    client = STClient(st_data_dir=str(root), st_user_handle='alice')

    assert client.get_user_dir() == str(user_dir)
    assert client.get_install_root() == str(root)
    assert client.list_user_handles() == ['alice']
    assert [item['id'] for item in client.list_world_books()] == ['lore']
    assert [item['id'] for item in client.list_presets()] == ['openai']
    assert [item['id'] for item in client.list_regex_scripts()] == ['global']
    assert [item['id'] for item in client.list_quick_replies()] == ['common']
    assert [item['id'] for item in client.list_scripts()] == ['script-one', 'folder-one']
    assert client.list_scripts()[1]['scripts_count'] == 1
    assert [item['id'] for item in client.list_chats()] == ['Alice']
    assert client.get_global_regex()['count'] == 1


def test_st_client_exports_js_slash_runner_scripts_and_preserves_conflicts(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)
    client = STClient(st_data_dir=str(root), st_user_handle='alice')
    target_dir = tmp_path / 'manager' / 'scripts'

    success, message = client.sync_resource('scripts', 'script-one', str(target_dir))

    assert success is True
    exported = target_dir / 'script-script-one.json'
    assert message == str(exported)
    assert json.loads(exported.read_text(encoding='utf-8'))['content'] == 'console.log("one")'

    unchanged, unchanged_message = client.sync_resource('scripts', 'script-one', str(target_dir))
    assert unchanged is True
    assert unchanged_message.startswith('unchanged:')

    exported.write_text('{"manager": true}', encoding='utf-8')
    conflict, conflict_message = client.sync_resource('scripts', 'script-one', str(target_dir))
    assert conflict is False
    assert conflict_message.startswith('conflict:')
    assert json.loads(exported.read_text(encoding='utf-8')) == {'manager': True}

    result = client.sync_all_resources('scripts', str(target_dir))
    assert result['success'] == 1
    assert result['skipped'] == 1
    assert result['conflicts'][0]['id'] == 'script-one'
    assert json.loads((target_dir / 'script-folder-one.json').read_text(encoding='utf-8'))['type'] == 'folder'


def test_st_client_reads_legacy_tavern_helper_script_repository(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    settings_path = user_dir / 'settings.json'
    settings_path.write_text(
        json.dumps({
            'extension_settings': {
                'TavernHelper': {
                    'script': {
                        'scriptsRepository': [
                            {
                                'name': 'Legacy Script',
                                'content': 'return 1',
                                'buttons': [{'name': 'Run', 'visible': True}],
                            }
                        ]
                    }
                }
            }
        }),
        encoding='utf-8',
    )

    scripts = STClient(st_data_dir=str(root), st_user_handle='alice').list_scripts()

    assert len(scripts) == 1
    assert scripts[0]['name'] == 'Legacy Script'
    assert scripts[0]['data']['type'] == 'script'
    assert scripts[0]['data']['button']['buttons'][0]['name'] == 'Run'


def test_st_client_reads_legacy_wrapped_script_repository(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    settings_path = user_dir / 'settings.json'
    settings_path.write_text(
        json.dumps({
            'extension_settings': {
                'TavernHelper': {
                    'script': {
                        'scriptsRepository': [
                            {
                                'type': 'script',
                                'value': {
                                    'id': 'wrapped-script',
                                    'name': 'Wrapped Script',
                                    'content': 'return 2',
                                    'buttons': [{'name': 'Run', 'visible': True}],
                                },
                            }
                        ]
                    }
                }
            }
        }),
        encoding='utf-8',
    )

    scripts = STClient(st_data_dir=str(root), st_user_handle='alice').list_scripts()

    assert len(scripts) == 1
    assert scripts[0]['id'] == 'wrapped-script'
    assert scripts[0]['data']['content'] == 'return 2'
    assert scripts[0]['data']['button']['buttons'][0]['name'] == 'Run'


def test_st_client_reads_js_slash_runner_scripts_from_native_settings_api(tmp_path):
    client = STClient(st_url='http://127.0.0.1:8000')

    class _Response:
        ok = True

        def json(self):
            return {
                'settings': json.dumps({
                    'extension_settings': {
                        'tavern_helper': {
                            'script': {
                                'scripts': [
                                    {
                                        'type': 'script',
                                        'id': 'api-script',
                                        'name': 'API Script',
                                        'content': 'return 3',
                                    }
                                ]
                            }
                        }
                    }
                })
            }

    client._api_post = lambda *_args, **_kwargs: _Response()

    scripts = client.list_scripts(use_api=True)

    assert len(scripts) == 1
    assert scripts[0]['id'] == 'api-script'
    assert scripts[0]['data']['content'] == 'return 3'


def test_st_connection_counts_global_regex_from_settings_without_regex_directory(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)
    (user_dir / 'regex' / 'global.json').unlink()
    (user_dir / 'regex').rmdir()

    client = STClient(st_data_dir=str(root), st_user_handle='alice')

    class _Response:
        ok = False

    class _HttpClient:
        def get(self, *_args, **_kwargs):
            return _Response()

    client._create_http_client = lambda: _HttpClient()

    result = client.test_connection()

    assert result['local']['available'] is True
    assert result['local']['resources']['regex'] == 1


def test_st_client_defaults_to_default_user_and_accepts_data_or_user_paths(tmp_path):
    root, user_dir = _make_st_user(tmp_path, handle='default-user')
    _write_resource_fixture(user_dir)

    root_client = STClient(st_data_dir=str(root))
    data_client = STClient(st_data_dir=str(root / 'data'))
    user_client = STClient(st_data_dir=str(user_dir))

    for client in (root_client, data_client, user_client):
        assert client.st_user_handle == 'default-user'
        assert client.get_user_dir() == str(user_dir)
        assert client.get_presets_dir() == str(user_dir / 'OpenAI Settings')


def test_st_client_does_not_overwrite_conflicting_files_or_chat_directories(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)
    target_dir = tmp_path / 'manager' / 'regex'

    client = STClient(st_data_dir=str(root), st_user_handle='alice')
    first_success, first_message = client.sync_resource('regex', 'global', str(target_dir))
    second_success, second_message = client.sync_resource('regex', 'global', str(target_dir))

    assert first_success is True
    assert first_message == str(target_dir / 'global.json')
    assert second_success is True
    assert second_message.startswith('unchanged:')

    (target_dir / 'global.json').write_text('manager version', encoding='utf-8')
    conflict_success, conflict_message = client.sync_resource('regex', 'global', str(target_dir))
    assert conflict_success is False
    assert conflict_message.startswith('conflict:')
    assert (target_dir / 'global.json').read_text(encoding='utf-8') == 'manager version'

    chat_target = tmp_path / 'manager' / 'chats' / 'Alice'
    chat_target.mkdir(parents=True)
    (chat_target / 'session.jsonl').write_text('manager version\n', encoding='utf-8')
    chat_success, chat_message = client.sync_resource('chats', 'Alice', str(tmp_path / 'manager' / 'chats'))
    assert chat_success is False
    assert chat_message.startswith('conflict:')
    assert (chat_target / 'session.jsonl').read_text(encoding='utf-8') == 'manager version\n'

    result = client.sync_all_resources('regex', str(target_dir))
    assert result['success'] == 0
    assert result['failed'] == 0
    assert result['skipped'] == 1
    assert len(result['conflicts']) == 1


def test_st_client_syncs_directory_world_books_without_overwriting(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)
    world_dir = user_dir / 'worlds' / 'directory-lore'
    world_dir.mkdir()
    (world_dir / 'world_info.json').write_text(
        json.dumps({'name': 'Directory Lore', 'entries': {'0': {'content': 'text'}}}),
        encoding='utf-8',
    )
    (world_dir / 'metadata.json').write_text('{"version": 1}', encoding='utf-8')

    client = STClient(st_data_dir=str(root), st_user_handle='alice')
    target_dir = tmp_path / 'manager' / 'lorebooks'

    success, message = client.sync_resource('worlds', 'directory-lore', str(target_dir))
    assert success is True
    assert message == str(target_dir / 'directory-lore')
    assert (target_dir / 'directory-lore' / 'world_info.json').exists()
    assert (target_dir / 'directory-lore' / 'metadata.json').exists()

    unchanged, unchanged_message = client.sync_resource(
        'worlds', 'directory-lore', str(target_dir)
    )
    assert unchanged is True
    assert unchanged_message.startswith('unchanged:')

    (target_dir / 'directory-lore' / 'world_info.json').write_text(
        '{"manager": true}',
        encoding='utf-8',
    )
    conflict, conflict_message = client.sync_resource(
        'worlds', 'directory-lore', str(target_dir)
    )
    assert conflict is False
    assert conflict_message.startswith('conflict:')


def test_st_client_accepts_resource_and_settings_paths(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)
    client = STClient(st_data_dir=str(root), st_user_handle='alice')

    assert client._validate_st_path(str(user_dir / 'characters')) is True
    assert client._validate_st_path(str(user_dir / 'settings.json')) is True
    assert client.get_user_dir(str(user_dir / 'characters')) == str(user_dir)
    assert client.get_user_dir(str(user_dir / 'settings.json')) == str(user_dir)


def test_global_regex_export_skips_same_name_content_conflicts(tmp_path):
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(
        json.dumps({
            'extension_settings': {
                'regex': [
                    {
                        'scriptName': 'Global Rule',
                        'findRegex': '/foo/g',
                        'replaceString': 'bar',
                    }
                ]
            }
        }),
        encoding='utf-8',
    )
    target_dir = tmp_path / 'manager' / 'regex'

    first = st_sync_api._export_global_regex(str(settings_path), str(target_dir))
    second = st_sync_api._export_global_regex(str(settings_path), str(target_dir))

    assert first['success'] == 1
    assert second['success'] == 0
    assert second['skipped'] == 1
    assert second['conflicts'] == []

    exported_path = target_dir / 'global__Global Rule.json'
    exported = json.loads(exported_path.read_text(encoding='utf-8'))
    exported['replaceString'] = 'manager-version'
    exported_path.write_text(json.dumps(exported), encoding='utf-8')

    conflict = st_sync_api._export_global_regex(str(settings_path), str(target_dir))
    assert conflict['success'] == 0
    assert conflict['skipped'] == 1
    assert conflict['conflicts'][0]['name'] == 'Global Rule'
    assert not (target_dir / 'global__Global Rule__1.json').exists()


def test_st_validate_path_reports_custom_user_and_resources(tmp_path):
    root, user_dir = _make_st_user(tmp_path)
    _write_resource_fixture(user_dir)

    app = Flask(__name__)
    app.register_blueprint(st_sync_api.bp)
    response = app.test_client().post(
        '/api/st/validate_path',
        json={'path': str(root), 'st_user_handle': 'alice'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['valid'] is True
    assert payload['normalized_path'] == str(root)
    assert payload['user_handle'] == 'alice'
    assert payload['user_dir'] == str(user_dir)
    assert payload['user_dir_exists'] is True
    assert payload['available_user_handles'] == ['alice']
    assert payload['resources']['presets']['count'] == 1
    assert payload['resources']['regex']['script_count'] == 1
    assert payload['resources']['regex']['global_count'] == 1
    assert payload['resources']['scripts']['count'] == 2
