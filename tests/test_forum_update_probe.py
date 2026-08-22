"""Offline contract tests for the forum update diagnostic probe."""

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import forum_update_probe as probe


class _Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.text = self.content.decode('utf-8')
        self.encoding = 'utf-8'
        self.headers = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(self.content)),
            'Set-Cookie': 'should-not-be-saved=1',
            'X-Cache': 'HIT',
        }
        self.elapsed = timedelta(milliseconds=3)

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({'url': url, 'headers': dict(headers or {}), 'timeout': timeout})
        return self.responses.pop(0)


def test_redact_payload_removes_sensitive_mapping_fields():
    value = probe._redact_payload({'title': 'Demo', 'session_token': 'secret', 'nested': {'cookie': 'x'}})
    assert value == {
        'title': 'Demo',
        'session_token': '<redacted>',
        'nested': {'cookie': '<redacted>'},
    }


def test_probe_rejects_non_discord_source_urls():
    assert probe._parse_discord_parts('https://example.com/channels/1/2', 7) == (None, None, None)
    assert probe._safe_url('https://discord.com/channels/1/2?token=private') == (
        'https://discord.com/channels/1/2'
    )


def test_probe_discord_mirrors_two_requests_and_writes_safe_bodies(tmp_path):
    session = _Session(
        [
            _Response(
                {
                    'id': '3',
                    'name': 'Current title',
                    'applied_tags': ['tag-1'],
                    'parent_id': '2',
                    'last_message_id': '4',
                }
            ),
            _Response({'available_tags': [{'id': 'tag-1', 'name': '角色'}]}),
        ]
    )

    result = probe._probe_discord(
        session.get,
        url='https://discord.com/channels/1/2/threads/3',
        credential='session=private',
        auth_type='cookie',
        timeout=7,
        output_dir=tmp_path,
        prefix='001_demo',
    )

    assert result['success'] is True
    assert result['extracted']['title'] == 'Current title'
    assert result['extracted']['resolved_tag_names'] == ['角色']
    assert len(session.calls) == 2
    assert session.calls[0]['url'].endswith('/channels/3')
    assert session.calls[1]['url'].endswith('/channels/2')
    assert session.calls[0]['headers']['Cookie'] == 'session=private'
    assert all('Cookie' not in item for item in result['requests'])
    body = (tmp_path / '001_demo_discord_thread.json').read_text(encoding='utf-8')
    assert 'private' not in body
    assert 'Current title' in body
    assert result['requests'][0]['content_headers']['X-Cache'] == 'HIT'
    assert 'Set-Cookie' not in result['requests'][0]['content_headers']


def test_probe_shimmerday_uses_one_request_and_extracts_candidates(tmp_path):
    session = _Session(
        [
            _Response(
                {
                    'thread_id': '3',
                    'title': 'Search title',
                    'last_active_at': '2026-08-23T00:00:00Z',
                }
            )
        ]
    )

    result = probe._probe_shimmerday(
        session.get,
        url='https://discord.com/channels/1/2/threads/3',
        credential='session=private',
        timeout=7,
        output_dir=tmp_path,
        prefix='001_demo',
    )

    assert result['success'] is True
    assert len(session.calls) == 1
    assert session.calls[0]['url'].endswith('/3')
    assert result['extracted']['candidates']['title'] == 'Search title'
    assert result['extracted']['candidates']['last_active_at'] == '2026-08-23T00:00:00Z'
