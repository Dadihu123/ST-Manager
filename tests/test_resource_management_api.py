import json
import sys
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import resources as resources_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(resources_api.bp)
    return app


def _configure_resource_api(monkeypatch, tmp_path):
    resources_root = tmp_path / 'resources'
    resources_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(resources_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(resources_api, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(
        resources_api,
        'load_config',
        lambda: {'resources_dir': str(resources_root), 'allowed_abs_resource_roots': []},
    )
    monkeypatch.setattr(resources_api, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(
        resources_api,
        'load_ui_data',
        lambda: {'cards/hero.png': {'resource_folder': 'hero'}},
    )
    return resources_root


def _write_file(path: Path, content='x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def test_list_resource_files_includes_nested_images_and_unknown_resources(monkeypatch, tmp_path):
    resources_root = _configure_resource_api(monkeypatch, tmp_path)
    hero_dir = resources_root / 'hero'
    _write_file(hero_dir / 'root.webp')
    _write_file(hero_dir / 'portrait.jfif')
    _write_file(hero_dir / 'poses' / 'happy.png')
    _write_file(
        hero_dir / 'lorebooks' / 'arc' / 'book.json',
        '{"name": "Book", "entries": {}}',
    )
    _write_file(hero_dir / 'lorebooks' / 'arc' / 'invalid.json', '{"name": "Not a book"}')
    _write_file(hero_dir / 'lorebooks' / 'cover.png')
    _write_file(hero_dir / 'lorebooks' / 'notes.txt')
    _write_file(
        hero_dir / 'extensions' / 'regex' / 'cleanup.json',
        '{"findRegex": "/hero/"}',
    )
    _write_file(hero_dir / 'extensions' / 'regex' / 'invalid.json', '{"name": "Not regex"}')
    _write_file(
        hero_dir / 'extensions' / 'tavern_helper' / 'script.json',
        '{"type": "script", "name": "Script"}',
    )
    _write_file(
        hero_dir / 'extensions' / 'quick-replies' / 'quick.json',
        '{"version": 1, "name": "Quick", "qrList": []}',
    )
    _write_file(
        hero_dir / 'presets' / 'preset.json',
        '{"name": "Preset", "temperature": 0.7}',
    )
    _write_file(hero_dir / 'extensions' / 'regex' / 'preview.png')
    _write_file(hero_dir / 'presets' / 'preview.png')
    _write_file(hero_dir / 'audio' / 'line.wav')
    _write_file(hero_dir / 'notes' / 'readme.md')

    client = _make_test_app().test_client()
    res = client.post('/api/list_resource_files', json={'folder_name': 'hero'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['files']['skins'] == ['portrait.jfif', 'poses/happy.png', 'root.webp']
    assert {item['relative_path'] for item in payload['files']['lorebooks']} == {
        'lorebooks/arc/book.json'
    }
    assert {item['relative_path'] for item in payload['files']['regex']} == {
        'extensions/regex/cleanup.json'
    }
    assert {item['relative_path'] for item in payload['files']['scripts']} == {
        'extensions/tavern_helper/script.json'
    }
    assert {item['relative_path'] for item in payload['files']['quick_replies']} == {
        'extensions/quick-replies/quick.json'
    }
    assert {item['relative_path'] for item in payload['files']['presets']} == {
        'presets/preset.json'
    }
    assert {item['relative_path'] for item in payload['files']['unknown']} == {
        'audio/line.wav',
    }


def test_delete_resource_file_accepts_nested_relative_path_and_blocks_traversal(monkeypatch, tmp_path):
    resources_root = _configure_resource_api(monkeypatch, tmp_path)
    target_file = resources_root / 'hero' / 'audio' / 'line.wav'
    secret_file = resources_root / 'secret.txt'
    _write_file(target_file)
    _write_file(secret_file)

    client = _make_test_app().test_client()
    delete_res = client.post(
        '/api/delete_resource_file',
        json={'card_id': 'cards/hero.png', 'filename': 'audio/line.wav'},
    )

    assert delete_res.status_code == 200
    assert delete_res.get_json()['success'] is True
    assert target_file.exists() is False
    assert any((tmp_path / 'trash').glob('line_*.wav'))

    traversal_res = client.post(
        '/api/delete_resource_file',
        json={'card_id': 'cards/hero.png', 'filename': '../secret.txt'},
    )

    assert traversal_res.status_code == 200
    assert traversal_res.get_json()['success'] is False
    assert secret_file.exists() is True


def test_save_script_file_rejects_invalid_typed_resource_payload(monkeypatch, tmp_path):
    resources_root = _configure_resource_api(monkeypatch, tmp_path)
    target_file = resources_root / 'hero' / 'extensions' / 'regex' / 'cleanup.json'
    target_file.parent.mkdir(parents=True, exist_ok=True)

    client = _make_test_app().test_client()
    invalid_res = client.post(
        '/api/scripts/save',
        json={'file_path': str(target_file), 'content': {'name': 'not regex'}},
    )

    assert invalid_res.status_code == 200
    assert invalid_res.get_json()['success'] is False
    assert target_file.exists() is False

    valid_res = client.post(
        '/api/scripts/save',
        json={'file_path': str(target_file), 'content': {'findRegex': '/hero/'}},
    )

    assert valid_res.status_code == 200
    assert valid_res.get_json()['success'] is True
    assert json.loads(target_file.read_text(encoding='utf-8')) == {'findRegex': '/hero/'}


@pytest.mark.parametrize('failure', ['replace', 'fsync'])
def test_save_script_file_write_failure_preserves_original(monkeypatch, tmp_path, failure):
    from core.utils import filesystem

    resources_root = _configure_resource_api(monkeypatch, tmp_path)
    target = resources_root / 'hero/extensions/regex/cleanup.json'
    _write_file(target, '{"findRegex":"/original/"}')
    original = target.read_bytes()

    def denied(*args, **kwargs):
        raise OSError('synthetic write failure')

    monkeypatch.setattr(filesystem.os, failure, denied)
    result = _make_test_app().test_client().post('/api/scripts/save', json={
        'file_path': str(target), 'content': {'findRegex': '/edited/'}})
    assert result.status_code == 200
    assert result.get_json() == {'success': False, 'msg': '写入文件失败'}
    assert target.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize('area', ['restore', 'protection', 'library', 'snapshot'])
def test_resource_delete_and_upload_cannot_change_migration_workspace(monkeypatch, tmp_path, area):
    import io
    _configure_resource_api(monkeypatch, tmp_path)
    folder = tmp_path / 'data/migration' / ('a' * 32) / area / 'resources_dir'
    target = folder / 'note.txt'
    _write_file(target, 'original')
    monkeypatch.setattr(resources_api, 'load_ui_data', lambda: {
        'cards/hero.png': {'resource_folder': str(folder)}})
    monkeypatch.setattr(resources_api, '_ensure_card_resource_folder', lambda _: (str(folder), False, None))
    client = _make_test_app().test_client()
    deleted = client.post('/api/delete_resource_file', json={
        'card_id': 'cards/hero.png', 'filename': 'note.txt'})
    assert deleted.get_json()['success'] is False
    assert '迁移' in deleted.get_json()['msg']
    uploaded = client.post('/api/upload_card_resource', data={
        'card_id': 'cards/hero.png', 'file': (io.BytesIO(b'injected'), 'new.txt')})
    assert uploaded.get_json()['success'] is False
    assert '迁移' in uploaded.get_json()['msg']
    assert target.read_text() == 'original'
    assert not (folder / 'new.txt').exists()
