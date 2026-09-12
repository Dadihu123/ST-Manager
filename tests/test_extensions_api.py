import json
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import extensions as extensions_api


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(extensions_api.bp)
    return app


def test_list_extensions_paginates_sorted_results(monkeypatch, tmp_path):
    regex_dir = tmp_path / 'regex'
    scripts_dir = tmp_path / 'scripts'
    quick_replies_dir = tmp_path / 'quick-replies'
    resources_dir = tmp_path / 'resources'
    regex_dir.mkdir()
    scripts_dir.mkdir()
    quick_replies_dir.mkdir()
    resources_dir.mkdir()

    monkeypatch.setattr(extensions_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        extensions_api,
        'load_config',
        lambda: {
            'regex_dir': str(regex_dir),
            'scripts_dir': str(scripts_dir),
            'quick_replies_dir': str(quick_replies_dir),
            'resources_dir': str(resources_dir),
        },
    )

    for index in range(5):
        path = regex_dir / f'rule-{index}.json'
        path.write_text(json.dumps({'name': f'Rule {index}'}), encoding='utf-8')
        path.touch()

    client = _make_test_app().test_client()
    res = client.get(
        '/api/extensions/list?mode=regex&filter_type=global&page=2&page_size=2'
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['total'] == 5
    assert payload['count'] == 5
    assert payload['page'] == 2
    assert payload['page_size'] == 2
    assert payload['total_pages'] == 3
    assert len(payload['items']) == 2
