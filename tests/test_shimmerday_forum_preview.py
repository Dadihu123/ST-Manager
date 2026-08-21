"""Discord URL 解析与类脑搜索站预览转发测试。"""

import sys
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import forum as forum_api
from core.services import shimmerday_forum_service
from core.utils.discord_url import extract_discord_thread_id


def test_extract_discord_thread_id_two_segment_url():
    url = 'https://discord.com/channels/1380075940285124724/1525005842158714991'
    assert extract_discord_thread_id(url) == '1525005842158714991'


def test_extract_discord_thread_id_three_segment_uses_middle():
    url = (
        'https://discord.com/channels/1380075940285124724/'
        '1525874881328316539/1525874992267661443'
    )
    assert extract_discord_thread_id(url) == '1525874881328316539'


def test_extract_discord_thread_id_threads_path():
    url = (
        'https://discord.com/channels/1/2/threads/999888777666555444'
    )
    assert extract_discord_thread_id(url) == '999888777666555444'


def test_extract_discord_thread_id_rejects_non_discord():
    assert extract_discord_thread_id('https://example.com/channels/1/2') is None
    assert extract_discord_thread_id('') is None
    assert extract_discord_thread_id(None) is None


def test_fetch_thread_preview_requires_cookie(monkeypatch):
    monkeypatch.setattr(
        shimmerday_forum_service,
        'load_config',
        lambda: {'shimmerday_forum_cookie': ''},
    )
    result = shimmerday_forum_service.fetch_thread_preview(
        source_link='https://discord.com/channels/1/1525005842158714991'
    )
    assert result['success'] is False
    assert 'Cookie' in result['msg']


def test_fetch_thread_preview_success(monkeypatch):
    monkeypatch.setattr(
        shimmerday_forum_service,
        'load_config',
        lambda: {'shimmerday_forum_cookie': 'session=abc'},
    )

    class _Resp:
        status_code = 200

        def json(self):
            return {
                'thread_id': '1525005842158714991',
                'title': 'demo',
                'author': {'display_name': 'A'},
                'tags': ['t1'],
            }

    captured = {}

    def _fake_get(url, headers=None, timeout=None):
        captured['url'] = url
        captured['headers'] = headers
        captured['timeout'] = timeout
        return _Resp()

    monkeypatch.setattr(shimmerday_forum_service.requests, 'get', _fake_get)

    result = shimmerday_forum_service.fetch_thread_preview(
        source_link='https://discord.com/channels/1/1525005842158714991'
    )
    assert result['success'] is True
    assert result['thread_id'] == '1525005842158714991'
    assert result['data']['title'] == 'demo'
    assert '1525005842158714991' in captured['url']
    assert captured['headers']['Cookie'] == 'session=abc'


def test_api_forum_thread_preview_endpoint(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(forum_api.bp)
    client = app.test_client()

    monkeypatch.setattr(
        forum_api,
        'fetch_thread_preview',
        lambda **kwargs: {
            'success': True,
            'thread_id': '123',
            'data': {'title': 'ok'},
        },
    )

    res = client.post(
        '/api/forum/thread_preview',
        json={'source_link': 'https://discord.com/channels/1/123'},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['data']['title'] == 'ok'


def test_api_forum_thread_preview_requires_input():
    app = Flask(__name__)
    app.register_blueprint(forum_api.bp)
    client = app.test_client()
    res = client.post('/api/forum/thread_preview', json={})
    assert res.status_code == 400
    assert res.get_json()['success'] is False


def test_config_default_includes_shimmerday_forum_cookie():
    from core.config import DEFAULT_CONFIG

    assert 'shimmerday_forum_cookie' in DEFAULT_CONFIG
    assert DEFAULT_CONFIG['shimmerday_forum_cookie'] == ''
