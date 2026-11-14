from pathlib import Path
import sys

from flask import Flask
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize('illegal_path', [False, True])
def test_unwritable_android_path_does_not_save_config(tmp_path, monkeypatch, illegal_path):
    from core.api.v1 import system
    from core.services import android_path_service

    blocked = tmp_path / 'a-file'
    blocked.write_text('original')
    calls = []
    monkeypatch.setattr(android_path_service, 'is_embedded_android', lambda: True)
    monkeypatch.setattr(android_path_service, 'load_config', lambda: {'cards_dir': 'old'})
    monkeypatch.setattr(system, 'save_config', lambda cfg: calls.append(cfg))
    app = Flask(__name__)
    app.register_blueprint(system.bp)
    path = 'bad\x00path' if illegal_path else str(blocked)
    result = app.test_client().post('/api/save_settings', json={'cards_dir': path}).get_json()
    assert result['success'] is False
    assert calls == []
    assert blocked.read_text() == 'original'
