import json
import sys
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import config as config_module
from core.api.v1 import system as system_api
from core.config import normalize_config
from core.services import st_auth
from core.services import st_client as st_client_module


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, text='', ok=None, content=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.ok = (200 <= status_code < 300) if ok is None else ok
        self.content = content if content is not None else (b'{}' if json_data is not None else text.encode('utf-8'))

    def json(self):
        if self._json_data is None:
            raise ValueError('No JSON payload')
        return self._json_data


class FakeSession:
    def __init__(self, scripted_responses):
        self.scripted_responses = list(scripted_responses)
        self.headers = {}
        self.cookies = {}
        self.auth = None
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({
            'method': method,
            'url': url,
            'kwargs': kwargs,
            'headers': dict(self.headers),
            'auth': self.auth,
        })
        if not self.scripted_responses:
            raise AssertionError('Unexpected extra HTTP request')
        handler = self.scripted_responses.pop(0)
        if callable(handler):
            return handler(method, url, kwargs, self)
        return handler


class FakeHTTPClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, path, **kwargs):
        self.calls.append(('post', path, kwargs))
        if self.error:
            raise self.error
        return self.response


class FakeApiHTTPClient:
    def __init__(self):
        self.calls = []

    def get(self, path, timeout=None):
        self.calls.append(('get', path, timeout))
        if path == '/api/plugins/st-external-bridge/health':
            return DummyResponse(200, json_data={'version': '9.9.9'})
        if path == '/api/status':
            return DummyResponse(200, json_data={'status': 'ok'})
        raise AssertionError(f'Unexpected GET path: {path}')

    def post(self, path, json=None, timeout=None):
        self.calls.append(('post', path, timeout, json))
        if path == '/api/st-api/character/list':
            return DummyResponse(200, json_data={'characters': [{'id': 'alice'}]})
        raise AssertionError(f'Unexpected POST path: {path}')


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app


def test_normalize_config_maps_legacy_basic_credentials():
    cfg = normalize_config({
        'st_auth_type': 'basic',
        'st_username': 'legacy-basic',
        'st_password': 'legacy-pass',
    })

    assert cfg['st_basic_username'] == 'legacy-basic'
    assert cfg['st_basic_password'] == 'legacy-pass'
    assert cfg['st_username'] == 'legacy-basic'
    assert cfg['st_password'] == 'legacy-pass'


def test_normalize_config_maps_legacy_web_credentials():
    cfg = normalize_config({
        'st_auth_type': 'web',
        'st_username': 'legacy-web',
        'st_password': 'legacy-pass',
    })

    assert cfg['st_web_username'] == 'legacy-web'
    assert cfg['st_web_password'] == 'legacy-pass'
    assert cfg['st_username'] == 'legacy-web'
    assert cfg['st_password'] == 'legacy-pass'


def test_save_config_clears_legacy_credentials_for_auth_web(tmp_path, monkeypatch):
    target = tmp_path / 'config.json'
    monkeypatch.setattr(config_module, 'CONFIG_FILE', str(target))

    assert config_module.save_config({
        'st_auth_type': 'auth_web',
        'st_basic_username': 'admin',
        'st_basic_password': 'admin-pass',
        'st_web_username': 'default-user',
        'st_web_password': 'web-pass',
        'st_username': 'legacy-user',
        'st_password': 'legacy-pass',
    })

    raw = json.loads(target.read_text(encoding='utf-8'))
    assert raw['st_basic_username'] == 'admin'
    assert raw['st_web_username'] == 'default-user'
    assert raw['st_username'] == ''
    assert raw['st_password'] == ''


def test_st_http_client_basic_applies_basic_auth_and_csrf(monkeypatch):
    def warmup(method, url, kwargs, session):
        session.cookies['XSRF-TOKEN'] = 'csrf-basic'
        return DummyResponse(200, text='ok')

    fake_session = FakeSession([warmup, DummyResponse(404)])
    monkeypatch.setattr(st_auth.requests, 'Session', lambda: fake_session)

    client = st_auth.build_st_http_client({
        'st_auth_type': 'basic',
        'st_url': 'http://127.0.0.1:8000',
        'st_basic_username': 'admin',
        'st_basic_password': 'secret',
    })
    client.ensure_authenticated()

    assert fake_session.auth.username == 'admin'
    assert fake_session.auth.password == 'secret'
    assert fake_session.headers['X-XSRF-TOKEN'] == 'csrf-basic'
    assert fake_session.calls[0]['kwargs']['proxies'] == {'http': None, 'https': None}


def test_st_http_client_web_performs_login(monkeypatch):
    def login(method, url, kwargs, session):
        session.cookies['XSRF-TOKEN'] = 'csrf-web'
        return DummyResponse(200, json_data={'ok': True})

    fake_session = FakeSession([DummyResponse(404), login])
    monkeypatch.setattr(st_auth.requests, 'Session', lambda: fake_session)

    client = st_auth.build_st_http_client({
        'st_auth_type': 'web',
        'st_url': 'http://127.0.0.1:8000',
        'st_web_username': 'default-user',
        'st_web_password': 'susu',
    })
    client.ensure_authenticated()

    assert fake_session.auth is None
    assert fake_session.calls[1]['url'].endswith('/api/users/login')
    assert fake_session.calls[1]['kwargs']['json'] == {'handle': 'default-user', 'password': 'susu'}
    assert fake_session.headers['X-XSRF-TOKEN'] == 'csrf-web'


def test_st_http_client_auth_web_uses_basic_then_web_then_request(monkeypatch):
    def warmup(method, url, kwargs, session):
        session.cookies['XSRF-TOKEN'] = 'csrf-basic'
        return DummyResponse(200, text='ok')

    def login(method, url, kwargs, session):
        assert session.auth.username == 'admin'
        assert session.auth.password == 'secret'
        assert kwargs['json'] == {'handle': 'default-user', 'password': 'susu'}
        session.cookies['XSRF-TOKEN'] = 'csrf-web'
        return DummyResponse(200, json_data={'ok': True})

    fake_session = FakeSession([
        warmup,
        DummyResponse(404),
        login,
        DummyResponse(200, json_data={'imported': True}),
    ])
    monkeypatch.setattr(st_auth.requests, 'Session', lambda: fake_session)

    client = st_auth.build_st_http_client({
        'st_auth_type': 'auth_web',
        'st_url': 'http://127.0.0.1:8000',
        'st_proxy': 'http://127.0.0.1:7890',
        'st_basic_username': 'admin',
        'st_basic_password': 'secret',
        'st_web_username': 'default-user',
        'st_web_password': 'susu',
    })
    response = client.post('/api/characters/import', data={'file_type': 'png'})

    assert response.status_code == 200
    assert [call['url'] for call in fake_session.calls] == [
        'http://127.0.0.1:8000',
        'http://127.0.0.1:8000/csrf-token',
        'http://127.0.0.1:8000/api/users/login',
        'http://127.0.0.1:8000/api/characters/import',
    ]
    assert fake_session.calls[3]['kwargs']['proxies'] == {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890',
    }
    assert fake_session.calls[3]['headers']['X-XSRF-TOKEN'] == 'csrf-web'


@pytest.mark.parametrize('auth_type', ['basic', 'web', 'auth_web'])
def test_st_http_client_uses_modern_csrf_for_login_and_writes(monkeypatch, auth_type):
    needs_warmup = auth_type != 'web'
    needs_login = auth_type != 'basic'
    responses = [DummyResponse(200)] if needs_warmup else []
    responses.append(DummyResponse(200, json_data={'token': 'session-token'}))
    if needs_login:
        responses.append(DummyResponse(200, json_data={'handle': 'alice'}))
    responses.extend([DummyResponse(200), DummyResponse(200)])
    fake_session = FakeSession(responses)
    monkeypatch.setattr(st_auth.requests, 'Session', lambda: fake_session)

    client = st_auth.build_st_http_client({'st_auth_type': auth_type})
    client.post('/api/themes/save', json={'name': 'theme'})
    client.post('/api/settings/save', json={'power_user': {'theme': 'theme'}})

    calls = fake_session.calls[int(needs_warmup):]
    assert calls[0]['method'] == 'GET'
    assert calls[0]['url'].endswith('/csrf-token')
    if needs_login:
        assert calls[1]['url'].endswith('/api/users/login')
    assert all(call['method'] == 'POST' for call in calls[1:])
    assert all(call['headers']['X-CSRF-Token'] == 'session-token' for call in calls[1:])


def test_st_http_client_reports_rejected_csrf_request_before_login(monkeypatch):
    fake_session = FakeSession([DummyResponse(403)])
    monkeypatch.setattr(st_auth.requests, 'Session', lambda: fake_session)
    client = st_auth.build_st_http_client({'st_auth_type': 'web'})

    with pytest.raises(st_auth.STAuthError) as error:
        client.ensure_authenticated()

    assert error.value.stage == 'csrf'
    assert error.value.status_code == 403
    assert len(fake_session.calls) == 1


def test_send_to_st_reports_basic_auth_failures(tmp_path, monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    (tmp_path / 'card.png').write_bytes(b'png')

    fake_http_client = FakeHTTPClient(
        error=st_auth.STAuthError('basic_auth', 'bad auth', status_code=401)
    )
    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(tmp_path))
    monkeypatch.setattr(system_api, 'load_config', lambda: normalize_config({'st_auth_type': 'basic'}))
    monkeypatch.setattr(system_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client)

    response = client.post('/api/send_to_st', json={'card_id': 'card.png'})
    payload = response.get_json()

    assert payload['success'] is False
    assert 'Basic/Auth 认证失败 (401)' in payload['msg']


def test_send_to_st_reports_web_login_failures(tmp_path, monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    (tmp_path / 'card.png').write_bytes(b'png')

    fake_http_client = FakeHTTPClient(
        error=st_auth.STAuthError('web_login', 'bad web login', status_code=401)
    )
    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(tmp_path))
    monkeypatch.setattr(system_api, 'load_config', lambda: normalize_config({'st_auth_type': 'auth_web'}))
    monkeypatch.setattr(system_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client)

    response = client.post('/api/send_to_st', json={'card_id': 'card.png'})
    payload = response.get_json()

    assert payload['success'] is False
    assert 'Web 登录失败 (401)' in payload['msg']


def test_send_to_st_reports_csrf_failures(tmp_path, monkeypatch):
    app = _make_test_app()
    client = app.test_client()
    (tmp_path / 'card.png').write_bytes(b'png')

    fake_http_client = FakeHTTPClient(response=DummyResponse(403, text='Forbidden', content=b'Forbidden'))
    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(tmp_path))
    monkeypatch.setattr(system_api, 'load_config', lambda: normalize_config({'st_auth_type': 'basic'}))
    monkeypatch.setattr(system_api, 'build_st_http_client', lambda cfg, timeout=10: fake_http_client)

    response = client.post('/api/send_to_st', json={'card_id': 'card.png'})
    payload = response.get_json()

    assert payload['success'] is False
    assert 'CSRF' in payload['msg']


def test_st_client_api_methods_use_shared_http_client(monkeypatch):
    fake_http_client = FakeApiHTTPClient()
    monkeypatch.setattr(st_client_module, 'build_st_http_client', lambda config, st_url=None, timeout=30: fake_http_client)

    client = st_client_module.STClient(st_data_dir='')
    result = client.test_connection()
    characters = client.list_characters(use_api=True)

    assert result['api']['available'] is True
    assert result['api']['version'] == '9.9.9'
    assert characters == [{'id': 'alice'}]
    assert ('get', '/api/plugins/st-external-bridge/health', 5) in fake_http_client.calls
    assert ('post', '/api/st-api/character/list', client.timeout, {'full': False}) in fake_http_client.calls
