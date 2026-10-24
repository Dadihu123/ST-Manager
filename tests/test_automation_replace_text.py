"""规则集「替换文本」动作的回归测试。"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

from core.api.v1 import automation as automation_api
from core.automation.constants import (
    ACT_REPLACE_TEXT,
    TRIGGER_CONTEXT_ALLOWED_ACTIONS,
)
from core.automation.normalizer import (
    TRIGGER_CONTEXT_AUTO_IMPORT,
    TRIGGER_CONTEXT_CARD_UPDATE,
    TRIGGER_CONTEXT_LINK_UPDATE,
    TRIGGER_CONTEXT_MANUAL_RUN,
    TRIGGER_CONTEXT_TAG_EDIT,
    normalize_actions_for_context,
)
from core.automation.replace_text import DEFAULT_TARGETS, apply_replace_text
from core.services import automation_service


def _card_info(description='小明走进了房间。小明笑了。'):
    return {
        'spec': 'chara_card_v3',
        'name': 'Hero',
        'data': {
            'name': 'Hero',
            'description': description,
            'alternate_greetings': ['小明说你好', '再见'],
            'character_book': {
                'entries': [
                    {
                        'comment': '小明档案',
                        'content': '小明是学生',
                        'keys': ['小明'],
                        'enabled': True,
                    }
                ]
            },
        },
    }


def _make_automation_app():
    app = Flask(__name__)
    app.register_blueprint(automation_api.bp)
    return app


def test_literal_replace_defaults_to_body_fields_only():
    info = _card_info('小明来了')
    info['data']['name'] = '小明'
    info['data']['character_book']['entries'][0]['keys'] = ['小明']

    result = apply_replace_text(info, [{'find': '小明', 'replace': '{{user}}'}])

    assert result['success'] is True
    assert result['changed'] is True
    assert info['data']['description'] == '{{user}}来了'
    # 角色名与世界书触发词默认不在目标里。
    assert info['data']['name'] == '小明'
    assert info['data']['character_book']['entries'][0]['keys'] == ['小明']
    assert set(result['per_target']) <= set(DEFAULT_TARGETS)


def test_literal_replace_can_target_name_and_keys_when_selected():
    info = _card_info('小明来了')
    info['data']['name'] = '小明'
    info['data']['character_book']['entries'][0]['keys'] = ['小明']

    result = apply_replace_text(
        info,
        [
            {
                'find': '小明',
                'replace': '{{user}}',
                'targets': ['name', 'wi_keys'],
            }
        ],
    )

    assert result['success'] is True
    assert info['data']['name'] == '{{user}}'
    # root 层 name 也同步，避免旧软件读到旧名。
    assert info['name'] == '{{user}}'
    assert info['data']['character_book']['entries'][0]['keys'] == ['{{user}}']


def test_regex_replace_supports_dollar_backrefs_and_first_only():
    info = _card_info('abc123def456')

    result = apply_replace_text(
        info,
        [
            {
                'find': r'([a-z]+)(\d+)',
                'replace': '$2-$1',
                'regex': True,
                'first_only': True,
                'targets': ['description'],
            }
        ],
    )

    assert result['success'] is True
    assert result['total'] == 1
    assert info['data']['description'] == '123-abcdef456'


def test_invalid_regex_is_reported_and_nothing_is_mutated():
    info = _card_info('abc')
    before = json.loads(json.dumps(info))

    result = apply_replace_text(
        info,
        [{'find': '([a-z', 'replace': 'x', 'regex': True, 'targets': ['description']}],
    )

    assert result['success'] is False
    assert result['changed'] is False
    assert result['errors']
    assert info == before


def test_one_bad_config_aborts_the_whole_action_set():
    info = _card_info('abc')
    before = json.loads(json.dumps(info))

    result = apply_replace_text(
        info,
        [
            {'find': 'abc', 'replace': 'x', 'targets': ['description']},
            {'find': '', 'replace': 'y', 'targets': ['description']},
        ],
    )

    assert result['success'] is False
    assert result['changed'] is False
    assert info == before


def test_empty_find_is_rejected():
    result = apply_replace_text(_card_info('abc'), [{'find': '', 'replace': 'x'}])

    assert result['success'] is False
    assert '查找内容不能为空' in result['errors'][0]['error']


def test_literal_replacement_keeps_backslashes():
    info = _card_info('path')

    apply_replace_text(
        info,
        [{'find': 'path', 'replace': r'C:\new', 'targets': ['description']}],
    )

    assert info['data']['description'] == r'C:\new'


def test_case_sensitivity_can_be_enabled():
    info = _card_info('Hello hello HELLO')

    apply_replace_text(
        info,
        [{'find': 'hello', 'replace': 'hi', 'case_sensitive': True, 'targets': ['description']}],
    )

    assert info['data']['description'] == 'Hello hi HELLO'


def test_replace_covers_worldbook_content_and_comment():
    info = _card_info('无关文本')

    result = apply_replace_text(
        info,
        [{'find': '小明', 'replace': '{{user}}', 'targets': ['wi_content', 'wi_comment']}],
    )

    entry = info['data']['character_book']['entries'][0]
    assert result['per_target'] == {'wi_content': 1, 'wi_comment': 1}
    assert entry['content'] == '{{user}}是学生'
    assert entry['comment'] == '{{user}}档案'


def test_no_match_reports_unchanged_so_caller_skips_write():
    info = _card_info('nothing here')
    before = json.loads(json.dumps(info))

    result = apply_replace_text(
        info,
        [{'find': 'zzz', 'replace': 'x', 'targets': ['description']}],
    )

    assert result['success'] is True
    assert result['changed'] is False
    assert result['total'] == 0
    assert info == before


def test_replace_text_is_allowed_for_manual_run_only():
    for trigger_context in (
        TRIGGER_CONTEXT_AUTO_IMPORT,
        TRIGGER_CONTEXT_CARD_UPDATE,
        TRIGGER_CONTEXT_LINK_UPDATE,
        TRIGGER_CONTEXT_TAG_EDIT,
    ):
        assert ACT_REPLACE_TEXT not in TRIGGER_CONTEXT_ALLOWED_ACTIONS[trigger_context]

    assert ACT_REPLACE_TEXT in TRIGGER_CONTEXT_ALLOWED_ACTIONS[TRIGGER_CONTEXT_MANUAL_RUN]

    actions = [{'type': ACT_REPLACE_TEXT, 'value': {'find': 'a', 'replace': 'b'}}]
    manual = normalize_actions_for_context(actions, TRIGGER_CONTEXT_MANUAL_RUN)
    auto = normalize_actions_for_context(actions, TRIGGER_CONTEXT_AUTO_IMPORT)

    assert [act['type'] for act in manual['actions']] == [ACT_REPLACE_TEXT]
    assert auto['actions'] == []


def test_executor_applies_replace_before_name_sync_and_move(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    calls = []

    def _fake_replace(card_id_arg, replacements):
        calls.append(('replace', card_id_arg, list(replacements)))
        return {
            'success': True,
            'changed': True,
            'total': 2,
            'per_target': {'description': 2},
            'per_action': [],
            'errors': [],
        }

    def _fake_sync(card_id_arg, **kwargs):
        calls.append(('rename', card_id_arg))
        return True, 'folder/renamed.json', 'Success', {'filename_updated': True}

    def _fake_move(card_id_arg, target_folder):
        calls.append(('move', card_id_arg))
        return True, 'moved/renamed.json', 'Success'

    monkeypatch.setattr(automation_executor, 'replace_card_text_internal', _fake_replace)
    monkeypatch.setattr(automation_executor, 'modify_card_attributes_internal', lambda *args, **kwargs: True)
    monkeypatch.setattr(automation_executor, 'sync_card_names_internal', _fake_sync)
    monkeypatch.setattr(automation_executor, 'move_card_internal', _fake_move)

    result = AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': 'moved',
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'text_replacements': [{'find': '小明', 'replace': '{{user}}'}],
            'rename_file_by_template': '{{char_name}}',
        },
        ui_data={},
    )

    assert [call[0] for call in calls] == ['replace', 'rename', 'move']
    assert result['text_replacements']['total'] == 2


def test_executor_skips_id_changing_steps_when_replace_fails(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    calls = []

    monkeypatch.setattr(
        automation_executor,
        'replace_card_text_internal',
        lambda *args, **kwargs: {
            'success': False,
            'changed': False,
            'total': 0,
            'errors': [{'index': 0, 'error': '正则表达式无效'}],
        },
    )
    monkeypatch.setattr(
        automation_executor,
        'sync_card_names_internal',
        lambda *args, **kwargs: calls.append('rename') or (True, 'x', 'ok', {}),
    )
    monkeypatch.setattr(
        automation_executor,
        'move_card_internal',
        lambda *args, **kwargs: calls.append('move') or (True, 'y', 'ok'),
    )

    result = AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': 'moved',
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'text_replacements': [{'find': '(', 'replace': 'x', 'regex': True}],
            'set_filename_from_char_name': True,
        },
        ui_data={},
    )

    assert calls == []
    assert result['final_id'] == 'folder/original.json'
    assert result['moved_to'] is None
    assert result['text_replacements']['success'] is False


def test_manual_execute_reports_text_replacement_count(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={card_id: {'id': card_id, 'category': 'folder', 'tags': []}},
        bundle_map={},
        initialized=True,
    )
    ruleset = {
        'rules': [
            {
                'name': 'replace',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_MANUAL_RUN],
                'groups': [],
                'actions': [
                    {
                        'type': ACT_REPLACE_TEXT,
                        'value': {'find': '小明', 'replace': '{{user}}'},
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: ruleset)
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id, 'category': 'folder', 'tags': [], 'token_count': 0}, {}),
    )
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [{'type': ACT_REPLACE_TEXT, 'value': {'find': '小明', 'replace': '{{user}}'}}]
        },
    )
    monkeypatch.setattr(
        automation_api.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data, **kwargs: {
            'moved_to': None,
            'tags_added': [],
            'tags_removed': [],
            'final_id': card_id_arg,
            'text_replacements': {'success': True, 'changed': True, 'total': 3},
        },
    )

    client = _make_automation_app().test_client()
    response = client.post(
        '/api/automation/execute',
        json={'card_ids': [card_id], 'ruleset_id': 'ruleset-1'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['summary']['text_replacements'] == 3


def test_frontend_wires_replace_text_action_and_help():
    modal_js = (ROOT / 'static' / 'js' / 'components' / 'automationModal.js').read_text(encoding='utf-8')
    template = (ROOT / 'templates' / 'modals' / 'automation.html').read_text(encoding='utf-8')
    batch_js = (ROOT / 'static' / 'js' / 'utils' / 'batchOperations.js').read_text(encoding='utf-8')
    header_js = (ROOT / 'static' / 'js' / 'components' / 'header.js').read_text(encoding='utf-8')

    assert "{ value: 'replace_text', label: '替换文本' }" in modal_js
    assert "replace_text: ['manual_run']" in modal_js
    assert 'replaceTargetOptions: REPLACE_TARGET_OPTIONS' in modal_js
    assert 'function createReplaceTextConfig' in modal_js
    assert 'action.value = serializeReplaceTextConfig(' in modal_js

    # 参数面板与兜底输入框都不能漏。
    assert "action.type === 'replace_text'" in template
    assert "action.type !== 'replace_text'" in template
    assert 'aria-label="替换文本的查找内容"' in template
    assert 'aria-label="替换文本的替换内容"' in template
    assert '@click="toggleReplaceTarget(cfg, option.value)"' in template

    # 帮助：动作说明、触发矩阵与手动执行动作计数都要同步。
    assert '替换文本：把写死的玩家名换掉' in template
    assert '仅手动执行；直接改写卡文件，无法撤销' in template
    assert '全部 15 个动作' in template
    assert '不执行「替换文本」：它会直接改写卡文件且无法撤销，只开放手动执行。' in template

    # 结果上报：批量汇总与 toast 都要有替换计数。
    assert 'text_replacements' in batch_js
    assert '替换: ${result.text_replacements || 0} 处' in header_js


def test_replace_card_text_internal_writes_file_and_syncs_index(tmp_path, monkeypatch):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    (cards_root / 'folder').mkdir(parents=True, exist_ok=True)
    card_path = cards_root / 'folder' / 'demo.json'
    card_path.write_text(
        json.dumps(
            {
                'spec': 'chara_card_v3',
                'spec_version': '3.0',
                'data': {'name': 'Hero', 'description': '小明来了'},
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    calls = []
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'suppress_fs_events',
        lambda *args, **kwargs: calls.append(('suppress', args, kwargs)),
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda *args, **kwargs: {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        },
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: calls.append(('index', kwargs)),
    )

    result = card_service.replace_card_text_internal(
        'folder/demo.json',
        [{'find': '小明', 'replace': '{{user}}', 'targets': ['description']}],
    )

    assert result['success'] is True
    assert result['changed'] is True
    assert result['total'] == 1
    assert calls[0][0] == 'suppress'
    assert calls[1][0] == 'index'
    assert calls[1][1]['file_content_changed'] is True

    written = json.loads(card_path.read_text(encoding='utf-8'))
    assert written['data']['description'] == '{{user}}来了'


def test_replace_card_text_internal_does_not_touch_file_without_match(tmp_path, monkeypatch):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    (cards_root).mkdir(parents=True, exist_ok=True)
    card_path = cards_root / 'demo.json'
    original_text = json.dumps(
        {
            'spec': 'chara_card_v3',
            'spec_version': '3.0',
            'data': {'name': 'Hero', 'description': '小明来了'},
        },
        ensure_ascii=False,
    )
    card_path.write_text(original_text, encoding='utf-8')

    calls = []
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'suppress_fs_events',
        lambda *args, **kwargs: calls.append('suppress'),
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda *args, **kwargs: calls.append('cache'),
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: calls.append('index'),
    )

    result = card_service.replace_card_text_internal(
        'demo.json',
        [{'find': '不存在', 'replace': 'x', 'targets': ['description']}],
    )

    assert result['success'] is True
    assert result['changed'] is False
    assert calls == []
    assert card_path.read_text(encoding='utf-8') == original_text
