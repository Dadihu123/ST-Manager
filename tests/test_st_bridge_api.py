import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import st_bridge as st_bridge_api
from core.services import st_bridge_service
from core.services.st_bridge_service import StBridgeError


def _client():
    app = Flask(__name__)
    app.register_blueprint(st_bridge_api.bp)
    return app.test_client()


def test_status_passes_verify_flag(monkeypatch):
    seen = {}

    def fake_status(verify=False):
        seen['verify'] = verify
        return {'success': True, 'total': 0, 'items': []}

    monkeypatch.setattr(st_bridge_service, 'status', fake_status)
    response = _client().get('/api/st_bridge/status?verify=1')

    assert response.status_code == 200
    assert response.get_json()['success'] is True
    assert seen['verify'] is True


def test_public_tree_returns_folders(monkeypatch):
    monkeypatch.setattr(
        st_bridge_service,
        'public_tree',
        lambda: {'success': True, 'folders': {'a': 2}, 'total': 2, 'pending_dir': '/st/characters'},
    )
    payload = _client().get('/api/st_bridge/public_tree').get_json()

    assert payload['folders'] == {'a': 2}
    assert payload['total'] == 2


def test_checkout_requires_card_id(monkeypatch):
    called = []
    monkeypatch.setattr(st_bridge_service, 'checkout', lambda card_id: called.append(card_id) or {'success': True})

    response = _client().post('/api/st_bridge/checkout', json={})

    assert response.status_code == 400
    assert called == []


def test_checkout_maps_business_error_to_status_code(monkeypatch):
    def boom(card_id):
        raise StBridgeError('卡片不存在', 404)

    monkeypatch.setattr(st_bridge_service, 'checkout', boom)
    response = _client().post('/api/st_bridge/checkout', json={'card_id': 'a/b.png'})

    assert response.status_code == 404
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['error'] == '卡片不存在'


def test_checkout_forwards_card_id(monkeypatch):
    captured = {}

    def fake_checkout(card_id):
        captured['card_id'] = card_id
        return {'success': True, 'staged_name': 'b.png'}

    monkeypatch.setattr(st_bridge_service, 'checkout', fake_checkout)
    response = _client().post('/api/st_bridge/checkout', json={'card_id': '  a/b.png  '})

    assert response.status_code == 200
    assert captured['card_id'] == 'a/b.png'
    assert response.get_json()['staged_name'] == 'b.png'


def test_commit_forwards_force_flag(monkeypatch):
    captured = {}

    def fake_commit(staged_name, force=False):
        captured.update({'staged_name': staged_name, 'force': force})
        return {'success': True}

    monkeypatch.setattr(st_bridge_service, 'commit', fake_commit)
    response = _client().post('/api/st_bridge/commit', json={'staged_name': 'a.png', 'force': True})

    assert response.status_code == 200
    assert captured == {'staged_name': 'a.png', 'force': True}


def test_commit_accepts_card_id_alias(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        st_bridge_service,
        'commit',
        lambda staged_name, force=False: captured.setdefault('staged_name', staged_name) or {'success': True},
    )

    _client().post('/api/st_bridge/commit', json={'card_id': 'alias.png'})

    assert captured['staged_name'] == 'alias.png'


def test_commit_conflict_payload_keeps_extra_fields(monkeypatch):
    def conflict(staged_name, force=False):
        raise StBridgeError('原卡被改过', 409, conflict=True, source_hash='old', current_hash='new')

    monkeypatch.setattr(st_bridge_service, 'commit', conflict)
    response = _client().post('/api/st_bridge/commit', json={'staged_name': 'a.png'})

    assert response.status_code == 409
    payload = response.get_json()
    assert payload['conflict'] is True
    assert payload['current_hash'] == 'new'


def test_discard_requires_staged_name(monkeypatch):
    monkeypatch.setattr(st_bridge_service, 'discard', lambda staged_name: {'success': True})
    response = _client().post('/api/st_bridge/discard', json={})
    assert response.status_code == 400


def test_unexpected_error_returns_500_without_traceback(monkeypatch):
    def explode(card_id):
        raise RuntimeError('内部炸了')

    monkeypatch.setattr(st_bridge_service, 'checkout', explode)
    response = _client().post('/api/st_bridge/checkout', json={'card_id': 'a.png'})

    assert response.status_code == 500
    payload = response.get_json()
    assert payload == {'success': False, 'error': '服务端处理失败'}


def test_cors_allows_loopback_origin(monkeypatch):
    monkeypatch.setattr(st_bridge_service, 'status', lambda verify=False: {'success': True})
    response = _client().get('/api/st_bridge/status', headers={'Origin': 'http://127.0.0.1:8000'})

    assert response.headers['Access-Control-Allow-Origin'] == 'http://127.0.0.1:8000'
    assert response.headers['Vary'] == 'Origin'


def test_cors_allows_localhost_without_port(monkeypatch):
    monkeypatch.setattr(st_bridge_service, 'status', lambda verify=False: {'success': True})
    response = _client().get('/api/st_bridge/status', headers={'Origin': 'http://localhost'})
    assert response.headers.get('Access-Control-Allow-Origin') == 'http://localhost'


def test_cors_ignores_remote_origin(monkeypatch):
    monkeypatch.setattr(st_bridge_service, 'status', lambda verify=False: {'success': True})
    response = _client().get('/api/st_bridge/status', headers={'Origin': 'https://evil.example'})

    assert 'Access-Control-Allow-Origin' not in response.headers


def test_cors_answers_preflight(monkeypatch):
    monkeypatch.setattr(st_bridge_service, 'checkout', lambda card_id: {'success': True})
    response = _client().options(
        '/api/st_bridge/checkout',
        headers={
            'Origin': 'http://127.0.0.1:8000',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        },
    )

    assert response.status_code in (200, 204)
    assert response.headers['Access-Control-Allow-Origin'] == 'http://127.0.0.1:8000'
    assert 'POST' in response.headers['Access-Control-Allow-Methods']
