"""来源帖子更新检查服务测试。"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services import forum_update_service as service


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class _Getter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return self.responses.pop(0)


def _prepare(monkeypatch, *, last_modified=300.0, ui_data=None):
    data = ui_data if ui_data is not None else {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
        }
    }
    cache = SimpleNamespace(id_map={
        'cards/demo.png': {
            'id': 'cards/demo.png',
            'last_modified': last_modified,
        }
    })
    monkeypatch.setattr(service, 'ctx', SimpleNamespace(cache=cache))
    monkeypatch.setattr(service, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(service, 'load_ui_data', lambda: data)
    monkeypatch.setattr(service, 'save_ui_data', lambda value: True)
    monkeypatch.setattr(service, 'load_config', lambda: {
        'discord_auth_type': 'token',
        'discord_bot_token': 'bot-token',
        'discord_user_cookie': '',
    })
    return data, cache


def _thread_payload(title, applied_tags=None, parent_id='2'):
    return {
        'id': '3',
        'name': title,
        'applied_tags': list(applied_tags or []),
        'parent_id': parent_id,
        'thread_metadata': {'create_timestamp': '2026-02-23T12:00:00.000Z'},
    }


def _message_payload(timestamp, edited=None, author=None):
    payload = {
        'id': '3',
        'timestamp': timestamp,
        'edited_timestamp': edited,
    }
    if author is not None:
        payload['author'] = author
    return payload


def test_fetch_discord_source_reads_starter_message_not_pin_or_activity(monkeypatch):
    _prepare(monkeypatch)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('2026-08-05T12:00:00.000Z', '2026-08-05T13:00:00.000Z')]),
    ])

    result = service.fetch_discord_source(
        'https://discord.com/channels/1/2/threads/3',
        http_get=getter,
    )

    assert result['success'] is True
    assert result['source']['title'] == '标题 A'
    assert result['source']['applied_tag_ids'] == []
    assert result['source']['parent_id'] == '2'
    assert result['source']['first_message_edited_at_epoch'] is not None
    assert getter.urls == [
        'https://discord.com/api/v10/channels/3',
        'https://discord.com/api/v10/channels/3/messages?around=3&limit=1',
    ]


def test_fetch_discord_source_normalizes_starter_author(monkeypatch):
    _prepare(monkeypatch)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload(
            '2026-08-05T12:00:00.000Z',
            author={
                'id': '123',
                'username': 'abcd',
                'global_name': '作者显示名',
            },
        )]),
    ])

    result = service.fetch_discord_source(
        'https://discord.com/channels/1/2/threads/3',
        http_get=getter,
    )

    assert result['source']['author'] == {
        'id': '123',
        'username': 'abcd',
        'name': 'abcd',
        'display_name': '作者显示名',
        'global_name': '作者显示名',
    }
    assert result['source']['author_source'] == 'discord'


def test_first_check_reports_remote_revision_after_local_card(monkeypatch):
    data, cache = _prepare(monkeypatch, last_modified=100.0)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('1970-01-01T00:03:20Z')]),
    ])

    result = service.check_card_source_update(
        'cards/demo.png',
        http_get=getter,
        now=500.0,
    )

    assert result['status'] == 'first_check_updated'
    assert result['first_check'] is True
    assert result['changed'] is True
    assert result['title_changed'] is False
    assert data['cards/demo.png']['_source_update_v1']['baseline_established'] is True
    assert cache.id_map['cards/demo.png']['source_title'] == '标题 A'


def test_first_check_without_remote_update_establishes_baseline(monkeypatch):
    data, _ = _prepare(monkeypatch, last_modified=2_000_000_000.0)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('2026-08-05T13:00:00Z')]),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['status'] == 'baseline_established'
    assert result['changed'] is False
    assert result['message'] == '已建立基线，下一次才能判断'
    assert data['cards/demo.png']['_source_update_v1']['first_message_revision_at'] is not None


def test_subsequent_check_detects_title_and_first_message_changes(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '旧标题',
                'first_message_revision_at': 100.0,
                'first_message_edited_at': 100.0,
                'baseline_established': True,
            },
        }
    }
    _prepare(monkeypatch, last_modified=200.0, ui_data=ui_data)
    getter = _Getter([
        _Response(_thread_payload('新标题')),
        _Response([_message_payload('1970-01-01T00:05:00Z', '1970-01-01T00:06:40Z')]),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['status'] == 'title_and_content_updated'
    assert result['title_changed'] is True
    assert result['first_message_changed'] is True
    assert result['changed'] is True
    assert ui_data['cards/demo.png']['_source_update_v1']['source_title'] == '新标题'


def test_repeated_unchanged_check_preserves_legacy_pending_update(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '标题 A',
                'first_message_revision_at': 100.0,
                'first_message_timestamp': 100.0,
                'baseline_established': True,
                'last_checked_at': 450.0,
                'last_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, last_modified=50.0, ui_data=ui_data)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('1970-01-01T00:01:40Z')]),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['status'] == 'unchanged'
    assert result['changed'] is False
    assert result['message'] == '来源暂无后续变化，仍有待处理更新'
    assert result['source_update']['pending_update'] is True
    assert result['source_update']['pending_status'] == 'updated'
    assert result['source_update']['pending_since'] == 450.0


def test_later_remote_change_keeps_pending_and_advances_observed_revision(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '标题 A',
                'first_message_revision_at': 100.0,
                'first_message_timestamp': 100.0,
                'baseline_established': True,
                'pending_update': True,
                'pending_status': 'updated',
                'pending_since': 450.0,
                'last_checked_at': 450.0,
                'last_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, last_modified=50.0, ui_data=ui_data)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('1970-01-01T00:01:40Z', '1970-01-01T00:03:20Z')]),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=600.0)

    assert result['status'] == 'updated'
    assert result['changed'] is True
    assert result['source_update']['pending_update'] is True
    assert result['source_update']['pending_since'] == 450.0
    assert result['source_update']['first_message_revision_at'] == 200.0


def test_failed_recheck_preserves_existing_pending_update(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '标题 A',
                'first_message_revision_at': 100.0,
                'baseline_established': True,
                'pending_update': True,
                'pending_status': 'updated',
                'pending_since': 450.0,
                'last_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, ui_data=ui_data)
    getter = _Getter([_Response({'message': 'Unauthorized'}, status_code=401)])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=600.0)

    assert result['success'] is False
    assert result['status'] == 'error'
    assert result['source_update']['last_status'] == 'error'
    assert result['source_update']['pending_update'] is True
    assert result['source_update']['pending_status'] == 'updated'


def test_acknowledge_only_clears_an_existing_pending_update(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': 'https://discord.com/channels/1/2/threads/3',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '标题 A',
                'first_message_revision_at': 100.0,
                'baseline_established': True,
                'last_checked_at': 450.0,
                'last_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, ui_data=ui_data)

    result = service.acknowledge_card_source_update('cards/demo.png')

    assert result['success'] is True
    assert result['acknowledged'] is True
    assert result['status'] == 'acknowledged'
    assert result['source_update']['pending_update'] is False
    assert result['source_update']['pending_status'] == ''
    assert result['source_update']['first_message_revision_at'] == 100.0

    repeated = service.acknowledge_card_source_update('cards/demo.png')
    assert repeated['success'] is True
    assert repeated['acknowledged'] is False
    assert repeated['status'] == 'not_pending'


def test_missing_starter_message_does_not_claim_complete_baseline(monkeypatch):
    data, _ = _prepare(monkeypatch, last_modified=100.0)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response({'message': 'Unknown Message'}, status_code=404),
        _Response({'message': 'Unknown Message'}, status_code=404),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['status'] == 'first_message_unavailable'
    assert result['baseline_established'] is False
    assert result['changed'] is False
    assert data['cards/demo.png']['_source_update_v1']['last_status'] == 'first_message_unavailable'


def test_forbidden_starter_message_exposes_discord_auth_reason(monkeypatch):
    _prepare(monkeypatch, last_modified=100.0)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response({'message': '只有机器人可使用此端点', 'code': 20002}, status_code=403),
        _Response({'message': '只有机器人可使用此端点', 'code': 20002}, status_code=403),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['status'] == 'first_message_unavailable'
    assert result['baseline_established'] is False
    assert result['source']['edit_http_status'] == 403
    assert result['source']['edit_api_code'] == 20002
    assert result['source']['edit_api_message'] == '只有机器人可使用此端点'
    assert '仅 Bot 可使用此接口' in result['source']['edit_error']
    assert result['warnings'] == [result['source']['edit_error']]
    assert '仅 Bot 可使用此接口' in result['message']


def test_non_discord_source_is_explicitly_unsupported(monkeypatch):
    _prepare(monkeypatch)
    result = service.check_card_source_update(
        'cards/demo.png',
        source_link='https://forum.shimmerday.top/thread/3',
    )
    assert result['success'] is True
    assert result['supported'] is False
    assert result['status'] == 'unsupported'


def test_check_without_source_clears_previous_source_state(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': '',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '旧标题',
                'first_message_revision_at': 100.0,
                'baseline_established': True,
                'pending_update': True,
                'pending_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, ui_data=ui_data)

    result = service.check_card_source_update('cards/demo.png')

    assert result['status'] == 'no_source'
    assert result['source_update']['source_title'] == ''
    assert result['source_update']['baseline_established'] is False
    assert result['source_update']['pending_update'] is False


def test_title_sync_is_distinct_from_baseline_check(monkeypatch):
    data, cache = _prepare(monkeypatch)
    getter = _Getter([_Response(_thread_payload('标题 A'))])

    result = service.save_source_title_for_card(
        'cards/demo.png',
        '标题 A',
        ui_data=data,
    )

    assert result['success'] is True
    assert result['status'] == 'title_synced'
    assert result['source_update']['baseline_established'] is False
    assert result['source_update']['last_status'] == 'title_synced'
    assert result['source_update']['source_title'] == '标题 A'
    assert cache.id_map['cards/demo.png']['source_title'] == '标题 A'

    synced = service.sync_source_title_for_card(
        'cards/demo.png',
        ui_data=data,
        http_get=getter,
    )
    assert synced['success'] is True
    assert getter.urls == ['https://discord.com/api/v10/channels/3']


def test_source_link_removal_resets_baseline(monkeypatch):
    ui_data = {
        'cards/demo.png': {
            'link': '',
            '_source_update_v1': {
                'source_url': 'https://discord.com/channels/1/2/threads/3',
                'source_title': '旧标题',
                'first_message_revision_at': 100.0,
                'baseline_established': True,
                'pending_update': True,
                'pending_status': 'updated',
            },
        }
    }
    _prepare(monkeypatch, ui_data=ui_data)

    changed, state = service.save_source_title_state(
        ui_data,
        'cards/demo.png',
        '新标题',
        source_url='',
    )

    assert changed is True
    assert state['baseline_established'] is False
    assert state['first_message_revision_at'] is None
    assert state['pending_update'] is False


def test_first_check_updated_message_is_explicit(monkeypatch):
    _prepare(monkeypatch, last_modified=100.0)
    getter = _Getter([
        _Response(_thread_payload('标题 A')),
        _Response([_message_payload('1970-01-01T00:03:20Z')]),
    ])

    result = service.check_card_source_update('cards/demo.png', http_get=getter, now=500.0)

    assert result['message'] == '首次检查发现来源首帖晚于本地角色卡，已标记为待处理更新'


def test_prepare_source_link_does_not_make_network_request(monkeypatch):
    data, _ = _prepare(monkeypatch)
    result = service.prepare_source_link_for_card(
        'cards/demo.png',
        source_link='https://discord.com/channels/1/2/threads/9',
        ui_data=data,
    )

    assert result['status'] == 'never_checked'
    assert result['source_update']['source_url'].endswith('/threads/9')
    assert result['source_update']['source_title'] == ''
    assert result['source_update']['baseline_established'] is False


def test_refresh_after_card_update_adopts_remote_revision_as_new_baseline(monkeypatch):
    data, cache = _prepare(monkeypatch, last_modified=100.0)
    data['cards/demo.png']['_source_update_v1'] = {
        'source_url': 'https://discord.com/channels/1/2/threads/3',
        'source_title': '旧标题',
        'first_message_revision_at': 100.0,
        'baseline_established': True,
        'pending_update': True,
        'pending_status': 'updated',
        'pending_since': 450.0,
    }
    getter = _Getter([
        _Response(_thread_payload('新标题')),
        _Response([_message_payload('1970-01-01T00:05:00Z', '1970-01-01T00:06:40Z')]),
    ])

    result = service.refresh_card_source_baseline(
        'cards/demo.png',
        ui_data=data,
        http_get=getter,
        now=500.0,
    )

    assert result['status'] == 'baseline_refreshed'
    assert result['message'] == '角色卡更新后，已刷新来源标题和首帖时间基线'
    assert result['baseline_established'] is True
    assert result['source_update']['source_title'] == '新标题'
    assert result['source_update']['first_message_revision_at'] == 400.0
    assert result['source_update']['last_status'] == 'baseline_refreshed'
    assert result['source_update']['pending_update'] is False
    assert cache.id_map['cards/demo.png']['source_title'] == '新标题'


def test_refresh_after_card_update_keeps_pending_when_starter_message_is_unavailable(monkeypatch):
    data, _ = _prepare(monkeypatch, last_modified=100.0)
    data['cards/demo.png']['_source_update_v1'] = {
        'source_url': 'https://discord.com/channels/1/2/threads/3',
        'source_title': '旧标题',
        'first_message_revision_at': 100.0,
        'baseline_established': True,
        'pending_update': True,
        'pending_status': 'updated',
        'pending_since': 450.0,
    }
    getter = _Getter([
        _Response(_thread_payload('新标题')),
        _Response({'message': 'Unknown Message'}, status_code=404),
        _Response({'message': 'Unknown Message'}, status_code=404),
    ])

    result = service.refresh_card_source_baseline(
        'cards/demo.png',
        ui_data=data,
        http_get=getter,
        now=500.0,
    )

    assert result['status'] == 'first_message_unavailable'
    assert result['source_update']['pending_update'] is True
    assert result['source_update']['pending_status'] == 'updated'
