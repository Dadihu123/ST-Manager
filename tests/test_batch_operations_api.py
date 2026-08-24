"""批量目标解析和来源检查 API 契约测试。"""

import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import automation as automation_api
from core.api.v1 import cards as cards_api


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def execute(self, *args):
        self.query = args

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_automation_targets_freezes_explicit_and_category_ids(monkeypatch):
    connection = _Connection([
        ('folder/a.png',),
        ('folder/b.png',),
    ])
    monkeypatch.setattr(automation_api, 'get_db', lambda: connection)

    app = Flask(__name__)
    app.register_blueprint(automation_api.bp)
    response = app.test_client().post(
        '/api/automation/targets',
        json={
            'card_ids': ['picked.png', 'folder/a.png', 'picked.png'],
            'category': 'folder',
            'recursive': True,
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 3,
        'card_ids': ['picked.png', 'folder/a.png', 'folder/b.png'],
    }


def test_source_update_batch_continues_after_failure_and_skips_unsupported(monkeypatch):
    connection = _Connection([
        ('folder/a.png',),
        ('folder/b.png',),
        ('folder/c.png',),
    ])
    monkeypatch.setattr(cards_api, 'get_db', lambda: connection)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})

    def fake_check(card_id, ui_data=None):
        if card_id.endswith('/a.png'):
            return {
                'success': True,
                'supported': True,
                'status': 'updated',
                'changed': True,
                'message': '有更新',
            }
        if card_id.endswith('/b.png'):
            return {
                'success': True,
                'supported': False,
                'status': 'unsupported',
                'message': '不支持',
            }
        raise RuntimeError('network down')

    monkeypatch.setattr(cards_api, 'check_card_source_update', fake_check)

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    response = app.test_client().post(
        '/api/cards/source_update/check_batch',
        json={'category': 'folder', 'recursive': True},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['selected'] == 3
    assert payload['checked'] == 1
    assert payload['updated'] == 1
    assert payload['skipped'] == 1
    assert payload['failed'] == 1
    assert [item['card_id'] for item in payload['details']] == [
        'folder/a.png',
        'folder/b.png',
        'folder/c.png',
    ]
