"""Discord 标签抓取器的持久化映射测试。"""

import json
import sys
from pathlib import Path
import importlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.forum_tag_fetcher import ForumTagFetcher

forum_tag_fetcher_module = importlib.import_module('core.automation.forum_tag_fetcher')


class _Response:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self.payload = payload
        self.content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.text = self.content.decode('utf-8')

    def json(self):
        return self.payload


def test_forum_tag_fetcher_uses_persisted_parent_tag_definitions(monkeypatch):
    responses = [
        _Response({'name': 'First', 'applied_tags': ['tag-1'], 'parent_id': '2'}),
        _Response({'available_tags': [{'id': 'tag-1', 'name': '角色'}]}),
        _Response({'name': 'Second', 'applied_tags': ['tag-1'], 'parent_id': '2'}),
    ]
    calls = []
    stored_mappings = {}

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return responses.pop(0)

    def fake_get_mapping(parent_id, tag_ids, *, guild_id=''):
        return {
            str(tag_id): stored_mappings[str(tag_id)]
            for tag_id in tag_ids
            if str(tag_id) in stored_mappings
        }

    def fake_save_mapping(parent_id, tags, *, guild_id=''):
        for tag in tags:
            stored_mappings[str(tag['id'])] = tag['name']
        return len(tags)

    fetcher = ForumTagFetcher(discord_cookie='session=private')
    monkeypatch.setattr(forum_tag_fetcher_module.requests, 'get', fake_get)
    monkeypatch.setattr(forum_tag_fetcher_module, 'get_discord_tag_name_map', fake_get_mapping)
    monkeypatch.setattr(forum_tag_fetcher_module, 'save_discord_tag_mappings', fake_save_mapping)

    first = fetcher._fetch_discord_thread_tags('1', '2', '3')
    second = fetcher._fetch_discord_thread_tags('1', '2', '4')

    assert first == (['角色'], 'First', None)
    assert second == (['角色'], 'Second', None)
    assert stored_mappings == {'tag-1': '角色'}
    assert calls == [
        'https://discord.com/api/v10/channels/3',
        'https://discord.com/api/v10/channels/2',
        'https://discord.com/api/v10/channels/4',
    ]
