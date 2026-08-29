import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.constants import (
    ACT_ADD_TAGS_FROM_SOURCE_TITLE,
    ACT_SET_CREATOR_FROM_SOURCE,
    TRIGGER_CONTEXT_LINK_UPDATE,
)
from core.automation.executor import AutomationExecutor
from core.automation.source_actions import (
    DEFAULT_SOURCE_TITLE_PATTERN,
    extract_source_title_tags,
    normalize_source_author,
    render_source_creator,
)
from core.services import automation_service
from core.services import card_service
from core.services import shimmerday_forum_service


executor_module = importlib.import_module('core.automation.executor')


def test_extract_source_title_tags_supports_multiple_matches_and_custom_split():
    result = extract_source_title_tags(
        '【a/b】【c|d】',
        {
            'pattern': DEFAULT_SOURCE_TITLE_PATTERN,
            'capture_groups': [1],
            'split_pattern': r'[/|]',
        },
    )

    assert result['success'] is True
    assert result['match_count'] == 2
    assert result['matched_values'] == ['a/b', 'c|d']
    assert result['extracted_tags'] == ['a', 'b', 'c', 'd']


def test_extract_source_title_tags_supports_named_capture_groups_and_flags():
    result = extract_source_title_tags(
        'PRIMARY=Elf SECONDARY=Human/Mage',
        {
            'pattern': r'primary=(?P<primary>\w+)\s+secondary=(?P<secondary>[^\s]+)',
            'capture_groups': ['primary', 'secondary'],
            'split_pattern': r'[/|]',
            'flags': 'i',
        },
    )

    assert result['success'] is True
    assert result['matched_values'] == ['Elf', 'Human/Mage']
    assert result['extracted_tags'] == ['Elf', 'Human', 'Mage']


def test_extract_source_title_tags_reports_invalid_custom_regex():
    result = extract_source_title_tags(
        'title',
        {
            'pattern': '(',
            'capture_groups': [0],
        },
    )

    assert result['success'] is False
    assert '正则表达式无效' in result['error']


def test_source_author_normalization_and_creator_template_rendering():
    author = normalize_source_author({
        'id': '123',
        'username': 'abcd',
        'global_name': '作者显示名',
    })

    assert author == {
        'id': '123',
        'username': 'abcd',
        'name': 'abcd',
        'display_name': '作者显示名',
        'global_name': '作者显示名',
    }
    assert render_source_creator(
        '{{author}}@{{author}}',
        source={'title': '标题', 'source_url': 'https://example.test/post'},
        author=author,
    ) == 'abcd@abcd'
    assert render_source_creator(
        '{{display_name}}/{{author_id}}/{{title}}',
        source={'title': '标题'},
        author=author,
        author_field='display_name',
    ) == '作者显示名/123/标题'


def test_fetch_shimmerday_source_normalizes_author(monkeypatch):
    monkeypatch.setattr(
        shimmerday_forum_service,
        'fetch_thread_preview',
        lambda **kwargs: {
            'success': True,
            'thread_id': '456',
            'data': {
                'title': '类脑标题',
                'author': {'name': 'abcd', 'display_name': '作者'},
            },
        },
    )

    result = shimmerday_forum_service.fetch_shimmerday_source(
        source_link='https://discord.com/channels/1/456',
    )

    assert result['success'] is True
    assert result['source']['title'] == '类脑标题'
    assert result['source']['author']['username'] == 'abcd'
    assert result['source']['author_source'] == 'shimmerday'


def test_executor_runs_source_title_and_creator_actions_with_one_discord_request(monkeypatch):
    card_id = 'folder/demo.json'
    source_link = 'https://discord.com/channels/1/2/3'
    fake_cache = SimpleNamespace(
        id_map={card_id: {
            'id': card_id,
            'tags': ['existing'],
            'creator': '',
        }},
        bundle_map={},
    )
    calls = []
    discord_calls = []
    shimmerday_calls = []

    monkeypatch.setattr(AutomationExecutor, '_source_link_for_card', lambda *args: source_link)
    monkeypatch.setattr(executor_module, 'ctx', SimpleNamespace(cache=fake_cache))
    monkeypatch.setattr(
        executor_module,
        'fetch_discord_source',
        lambda link: discord_calls.append(link) or {
            'success': True,
            'source': {
                'title': '【a/b】',
                'author': {
                    'id': '123',
                    'username': 'abcd',
                    'display_name': '作者',
                },
                'author_source': 'discord',
            },
        },
    )
    monkeypatch.setattr(
        executor_module,
        'fetch_shimmerday_source',
        lambda **kwargs: shimmerday_calls.append(kwargs) or {
            'success': False,
            'error': '不应调用类脑',
        },
    )
    monkeypatch.setattr(
        executor_module,
        'filter_governed_tags',
        lambda tags, **kwargs: {
            'accepted': list(tags),
            'skipped_unknown': [],
            'skipped_blacklist': [],
        },
    )
    monkeypatch.setattr(
        executor_module,
        'modify_card_attributes_internal',
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    plan = {
        'add_tags': set(),
        'remove_tags': set(),
        'favorite': None,
        ACT_ADD_TAGS_FROM_SOURCE_TITLE: {
            'pattern': DEFAULT_SOURCE_TITLE_PATTERN,
            'capture_groups': [1],
            'split_pattern': r'[/|]',
        },
        ACT_SET_CREATOR_FROM_SOURCE: {
            'provider': 'discord',
            'author_field': 'username',
            'format': '{{author}}@{{author}}',
            'overwrite': True,
        },
    }

    result = AutomationExecutor().apply_plan(card_id, plan, ui_data={})

    assert discord_calls == [source_link]
    assert shimmerday_calls == []
    assert calls
    assert calls[0][1]['set_creator'] == 'abcd@abcd'
    assert set(calls[0][0][1]) == {'a', 'b'}
    assert result['source_title_tags']['governed_tags'] == ['a', 'b']
    assert result['creator_sync']['creator'] == 'abcd@abcd'
    assert result['creator_sync']['changed'] is True


def test_executor_does_not_overwrite_existing_creator_by_default(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={card_id: {
            'id': card_id,
            'tags': [],
            'creator': 'existing',
        }},
        bundle_map={},
    )
    writes = []

    monkeypatch.setattr(AutomationExecutor, '_source_link_for_card', lambda *args: 'https://discord.com/channels/1/2/3')
    monkeypatch.setattr(executor_module, 'ctx', SimpleNamespace(cache=fake_cache))
    monkeypatch.setattr(
        executor_module,
        'fetch_discord_source',
        lambda link: {
            'success': True,
            'source': {
                'title': '标题',
                'author': {'username': 'abcd'},
                'author_source': 'discord',
            },
        },
    )
    monkeypatch.setattr(
        executor_module,
        'modify_card_attributes_internal',
        lambda *args, **kwargs: writes.append((args, kwargs)) or True,
    )

    result = AutomationExecutor().apply_plan(
        card_id,
        {
            ACT_SET_CREATOR_FROM_SOURCE: {
                'provider': 'discord',
                'format': '{{author}}',
                'overwrite': False,
            }
        },
        ui_data={},
    )

    assert writes == []
    assert result['creator_sync']['success'] is True
    assert result['creator_sync']['changed'] is False
    assert result['creator_sync']['skipped_reason'] == 'creator_not_empty'


def test_executor_reports_source_unavailable_instead_of_silent_title_success(monkeypatch):
    card_id = 'folder/demo.json'
    executor_module_ctx = SimpleNamespace(
        cache=SimpleNamespace(
            id_map={card_id: {'id': card_id, 'tags': [], 'creator': ''}},
            bundle_map={},
        ),
    )
    monkeypatch.setattr(executor_module, 'ctx', executor_module_ctx)
    monkeypatch.setattr(AutomationExecutor, '_source_link_for_card', lambda *args: '')
    monkeypatch.setattr(
        executor_module,
        'fetch_shimmerday_source',
        lambda **kwargs: {'success': False, 'error': '未配置类脑 Cookie'},
    )

    result = AutomationExecutor().apply_plan(
        card_id,
        {
            ACT_ADD_TAGS_FROM_SOURCE_TITLE: {
                'pattern': DEFAULT_SOURCE_TITLE_PATTERN,
                'capture_groups': [1],
            },
        },
        ui_data={},
    )

    assert result['source_title_tags']['success'] is False
    assert result['source_title_tags']['skipped_reason'] == 'source_unavailable'
    assert result['source_title_tags']['error'] == '未配置类脑 Cookie'


def test_modify_card_attributes_internal_writes_creator_to_file_db_and_cache(monkeypatch, tmp_path):
    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True)
    card_path = card_dir / 'demo.json'
    card_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    class FakeConn:
        def __init__(self):
            self.executed = []
            self.committed = 0

        def execute(self, sql, params):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.committed += 1

    fake_conn = FakeConn()
    cache = SimpleNamespace(
        id_map={'folder/demo.json': {'creator': ''}},
        update_card_data=lambda card_id, payload: cache.id_map[card_id].update(payload),
    )
    written = []

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'tags': [], 'creator': ''}},
    )
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        card_service,
        'write_card_metadata',
        lambda path, info: written.append((path, info)) or True,
    )
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(card_service, 'enqueue_index_job', lambda *args, **kwargs: None)
    monkeypatch.setattr(card_service.ctx, 'cache', cache, raising=False)

    assert card_service.modify_card_attributes_internal(
        'folder/demo.json',
        set_creator='abcd@abcd',
    ) is True

    assert written[0][1]['data']['creator'] == 'abcd@abcd'
    assert fake_conn.executed == [
        ('UPDATE card_metadata SET creator = ? WHERE id = ?', ('abcd@abcd', 'folder/demo.json')),
    ]
    assert cache.id_map['folder/demo.json']['creator'] == 'abcd@abcd'


def test_link_update_source_actions_require_active_global_ruleset(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={card_id: {'id': card_id, 'tags': [], 'creator': ''}},
        bundle_map={},
    )
    monkeypatch.setattr(automation_service, 'load_config', lambda: {})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)

    assert automation_service.auto_run_forum_tags_on_link_update(card_id) is None


def test_link_update_runs_new_source_actions_from_enabled_global_rule(monkeypatch):
    card_id = 'folder/demo.json'
    action_value = {
        'pattern': DEFAULT_SOURCE_TITLE_PATTERN,
        'capture_groups': [1],
        'split_pattern': r'[/|]',
    }
    creator_value = {
        'provider': 'discord',
        'format': '{{author}}',
        'overwrite': False,
    }
    ruleset = {
        'rules': [{
            'enabled': True,
            'trigger_contexts': [TRIGGER_CONTEXT_LINK_UPDATE],
            'groups': [],
            'actions': [
                {'type': ACT_ADD_TAGS_FROM_SOURCE_TITLE, 'value': action_value},
                {'type': ACT_SET_CREATOR_FROM_SOURCE, 'value': creator_value},
            ],
        }],
    }
    fake_cache = SimpleNamespace(
        id_map={card_id: {'id': card_id, 'tags': [], 'creator': ''}},
        bundle_map={},
    )
    captured = {}

    monkeypatch.setattr(
        automation_service,
        'load_config',
        lambda: {
            'active_automation_ruleset': 'ruleset-1',
            'automation_slash_is_tag_separator': False,
        },
    )
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: ruleset)
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}),
    )
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': ruleset['rules'][0]['actions']},
    )
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': list(actions),
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {},
        },
    )

    def fake_apply(card_id_arg, plan, ui_data):
        captured['plan'] = plan
        return {
            'final_id': card_id_arg,
            'source_title_tags': {'governed_tags': ['a', 'b']},
            'creator_sync': {'changed': True, 'creator': 'abcd'},
        }

    monkeypatch.setattr(automation_service.executor, 'apply_plan', fake_apply)
    monkeypatch.setattr(
        automation_service,
        'auto_run_tag_merge_on_tagging',
        lambda *args, **kwargs: {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': ['a', 'b']}},
    )

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result['run'] is True
    assert captured['plan'][ACT_ADD_TAGS_FROM_SOURCE_TITLE] == action_value
    assert captured['plan'][ACT_SET_CREATOR_FROM_SOURCE] == creator_value
    assert result['result']['final_tags'] == ['a', 'b']
