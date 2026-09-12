import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import system as system_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app


def test_cleanup_thumbnails_system_action_returns_cleanup_stats(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    thumbnails_dir = tmp_path / 'thumbnails'
    expected = {
        'scanned': 8,
        'kept': 5,
        'removed': 3,
        'errors': [],
    }
    calls = []

    def fake_cleanup(cards_folder, thumb_folder):
        calls.append((cards_folder, thumb_folder))
        return expected

    monkeypatch.setattr(system_api, 'CARDS_FOLDER', cards_dir)
    monkeypatch.setattr(system_api, 'THUMB_FOLDER', thumbnails_dir)
    monkeypatch.setattr(system_api, 'clean_orphaned_thumbnail_cache', fake_cleanup)

    response = _make_test_app().test_client().post(
        '/api/system_action', json={'action': 'cleanup_thumbnails'}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['scanned'] == 8
    assert payload['kept'] == 5
    assert payload['removed'] == 3
    assert '清理 3 个无效缓存' in payload['msg']
    assert calls == [(cards_dir, thumbnails_dir)]


def test_cleanup_thumbnails_system_action_reports_file_errors(monkeypatch):
    monkeypatch.setattr(
        system_api,
        'clean_orphaned_thumbnail_cache',
        lambda *_paths: {
            'scanned': 1,
            'kept': 0,
            'removed': 0,
            'errors': ['locked.webp: access denied'],
        },
    )

    response = _make_test_app().test_client().post(
        '/api/system_action', json={'action': 'cleanup_thumbnails'}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['errors'] == ['locked.webp: access denied']
    assert '1 个文件清理失败' in payload['msg']
