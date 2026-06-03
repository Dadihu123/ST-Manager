import sys
from pathlib import Path

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
    _write_file(hero_dir / 'lorebooks' / 'arc' / 'book.json', '{}')
    _write_file(hero_dir / 'lorebooks' / 'cover.png')
    _write_file(hero_dir / 'lorebooks' / 'notes.txt')
    _write_file(hero_dir / 'extensions' / 'regex' / 'cleanup.json', '{}')
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
