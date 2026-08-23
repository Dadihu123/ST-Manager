import sys
import importlib
from pathlib import Path
from types import SimpleNamespace

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

automation_manager = importlib.import_module('core.automation.manager')

from core.api.v1 import automation as automation_api
from core.automation.engine import AutomationEngine
from core.automation.constants import (
    ACT_ADD_TAG,
    ACT_FETCH_FORUM_TAGS,
    ACT_REFRESH_SOURCE_BASELINE,
    ACT_MERGE_TAGS,
    ACT_MOVE,
    ACT_REMOVE_TAG,
    ACT_RENAME_FILE_BY_TEMPLATE,
    ACT_SET_CHAR_NAME_FROM_FILENAME,
    ACT_SET_FILENAME_FROM_CHAR_NAME,
    ACT_SET_FILENAME_FROM_WI_NAME,
    ACT_SET_FAV,
    ACT_SPLIT_CATEGORY_TO_TAGS,
    ACT_SET_WI_NAME_FROM_FILENAME,
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
from core.services import automation_service
from core.automation.manager import RuleManager


def _make_automation_app():
    app = Flask(__name__)
    app.register_blueprint(automation_api.bp)
    return app


def _make_ruleset(field, value, *, case_sensitive=False, action_type='add_tag', action_value='matched'):
    return {
        'rules': [
            {
                'name': f'rule_for_{field}',
                'enabled': True,
                'groups': [
                    {
                        'logic': 'AND',
                        'conditions': [
                            {
                                'field': field,
                                'operator': 'contains',
                                'value': value,
                                'case_sensitive': case_sensitive,
                            }
                        ],
                    }
                ],
                'actions': [{'type': action_type, 'value': action_value}],
            }
        ]
    }


def test_automation_engine_contains_ignores_case_when_case_sensitive_false():
    engine = AutomationEngine()
    card_data = {
        'extensions': {
            'regex_scripts': [
                {'scriptName': 'RegexOne', 'findRegex': 'Foo.*Bar'},
            ]
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('regex_content', 'foo', case_sensitive=False),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == [{'type': 'add_tag', 'value': 'matched'}]


def test_automation_engine_contains_respects_case_when_case_sensitive_true():
    engine = AutomationEngine()
    card_data = {
        'extensions': {
            'regex_scripts': [
                {'scriptName': 'RegexOne', 'findRegex': 'Foo.*Bar'},
            ]
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('regex_content', 'foo', case_sensitive=True),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == []


def test_automation_engine_wi_name_matches_title_only_entries():
    engine = AutomationEngine()
    card_data = {
        'character_book': {
            'entries': [
                {'title': 'OnlyTitle', 'content': 'LoreBeta'},
            ]
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('wi_name', 'Only', case_sensitive=False),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == [{'type': 'add_tag', 'value': 'matched'}]


def test_auto_run_rules_on_card_loads_deep_fields_from_card_file(tmp_path, monkeypatch):
    cards_root = tmp_path / 'cards'
    card_path = cards_root / 'folder' / 'demo.json'
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text('{}', encoding='utf-8')

    ruleset = _make_ruleset('wi_content', 'Lore', case_sensitive=False)
    captured = {}

    fake_cache = SimpleNamespace(
        id_map={
            'folder/demo.json': {
                'id': 'folder/demo.json',
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )

    monkeypatch.setattr(automation_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        automation_service,
        'extract_card_info',
        lambda path: {
            'data': {
                'character_book': {
                    'entries': [
                        {'comment': 'EntryTitle', 'content': 'LoreBeta'},
                    ]
                }
            }
        },
        raising=False,
    )
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
    monkeypatch.setattr(automation_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda card_id: card_id)

    def _fake_apply_plan(card_id, plan, ui_data):
        captured['card_id'] = card_id
        captured['plan'] = plan
        return {
            'moved_to': None,
            'tags_added': list(plan.get('add_tags', [])),
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': None,
            'final_id': card_id,
        }

    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)

    result = automation_service.auto_run_rules_on_card('folder/demo.json')

    assert result is not None
    assert result['run'] is True
    assert captured['card_id'] == 'folder/demo.json'
    assert captured['plan']['add_tags'] == {'matched'}


def test_automation_engine_reads_st_helper_dict_structure():
    engine = AutomationEngine()
    card_data = {
        'extensions': {
            'tavern_helper': {
                'scripts': [
                    {'name': 'ScriptDict', 'content': 'console.log("dict")'},
                ],
                'variables': {},
            }
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('st_script_content', 'dict', case_sensitive=False),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == [{'type': 'add_tag', 'value': 'matched'}]


def test_automation_engine_reads_st_helper_list_structure():
    engine = AutomationEngine()
    card_data = {
        'extensions': {
            'tavern_helper': [
                ['scripts', [
                    {'name': 'ScriptList', 'content': 'console.log("list")'},
                ]],
                ['variables', {}],
            ]
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('st_script_content', 'list', case_sensitive=False),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == [{'type': 'add_tag', 'value': 'matched'}]


def test_automation_engine_reads_st_helper_legacy_structure():
    engine = AutomationEngine()
    card_data = {
        'extensions': {
            'TavernHelper_scripts': [
                {
                    'type': 'script',
                    'value': {'name': 'ScriptLegacy', 'content': 'console.log("legacy")'},
                }
            ]
        }
    }

    plan = engine.evaluate(
        card_data,
        _make_ruleset('st_script_content', 'legacy', case_sensitive=False),
        match_if_no_conditions=True,
    )

    assert plan['actions'] == [{'type': 'add_tag', 'value': 'matched'}]


def _action_types(actions):
    return [action['type'] for action in actions]


def _sample_actions():
    return [
        {'type': ACT_MOVE, 'value': 'folder-a'},
        {'type': ACT_ADD_TAG, 'value': 'tag-a'},
        {'type': ACT_REMOVE_TAG, 'value': 'tag-b'},
        {'type': ACT_SET_FAV, 'value': 'true'},
        {'type': ACT_SET_CHAR_NAME_FROM_FILENAME},
        {'type': ACT_SET_WI_NAME_FROM_FILENAME},
        {'type': ACT_SET_FILENAME_FROM_CHAR_NAME},
        {'type': ACT_SET_FILENAME_FROM_WI_NAME},
        {'type': ACT_FETCH_FORUM_TAGS},
        {'type': ACT_MERGE_TAGS, 'value': {'old': 'new'}},
        {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
        {'type': ACT_SPLIT_CATEGORY_TO_TAGS},
    ]


def test_normalize_actions_for_manual_run_keeps_new_actions_available():
    normalized = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_MANUAL_RUN)

    assert _action_types(normalized['actions']) == [
        ACT_MOVE,
        ACT_ADD_TAG,
        ACT_REMOVE_TAG,
        ACT_SET_FAV,
        ACT_SET_CHAR_NAME_FROM_FILENAME,
        ACT_SET_WI_NAME_FROM_FILENAME,
        ACT_FETCH_FORUM_TAGS,
        ACT_MERGE_TAGS,
        ACT_RENAME_FILE_BY_TEMPLATE,
    ]
    assert normalized['observability'] == {
        'category_tag_expansions': [
            {
                'source_category': '',
                'derived_tags': [],
                'excluded_segments': [],
            }
        ],
        'suppressed_filename_action_conflicts': [
            {
                'reason': 'lower_priority_filename_action',
                'suppressed': ACT_SET_FILENAME_FROM_CHAR_NAME,
                'winner': ACT_RENAME_FILE_BY_TEMPLATE,
            },
            {
                'reason': 'lower_priority_filename_action',
                'suppressed': ACT_SET_FILENAME_FROM_WI_NAME,
                'winner': ACT_RENAME_FILE_BY_TEMPLATE,
            },
        ],
        'noop_rename_reasons': [],
    }
    assert normalized['derived'] == {'add_tags': {'tag-a'}, 'remove_tags': set()}


def test_normalize_actions_for_auto_import_excludes_fetch_and_merge_only():
    normalized = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_AUTO_IMPORT)

    assert _action_types(normalized['actions']) == [
        ACT_MOVE,
        ACT_ADD_TAG,
        ACT_REMOVE_TAG,
        ACT_SET_FAV,
        ACT_SET_CHAR_NAME_FROM_FILENAME,
        ACT_SET_WI_NAME_FROM_FILENAME,
        ACT_RENAME_FILE_BY_TEMPLATE,
    ]
    assert normalized['observability']['category_tag_expansions'] == [
        {
            'source_category': '',
            'derived_tags': [],
            'excluded_segments': [],
        }
    ]


def test_card_update_allowlist_matches_auto_import_allowlist():
    assert TRIGGER_CONTEXT_ALLOWED_ACTIONS[TRIGGER_CONTEXT_CARD_UPDATE] == (
        TRIGGER_CONTEXT_ALLOWED_ACTIONS[TRIGGER_CONTEXT_AUTO_IMPORT]
    )


def test_normalizer_exports_card_update_context_and_matches_auto_import_allowlist():
    assert TRIGGER_CONTEXT_CARD_UPDATE == 'card_update'

    auto_import = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_AUTO_IMPORT)
    card_update = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_CARD_UPDATE)

    assert card_update['trigger_context'] == TRIGGER_CONTEXT_CARD_UPDATE
    assert _action_types(card_update['actions']) == [
        ACT_MOVE,
        ACT_ADD_TAG,
        ACT_REMOVE_TAG,
        ACT_SET_FAV,
        ACT_SET_CHAR_NAME_FROM_FILENAME,
        ACT_SET_WI_NAME_FROM_FILENAME,
        ACT_RENAME_FILE_BY_TEMPLATE,
    ]
    assert {
        key: value for key, value in card_update.items() if key != 'trigger_context'
    } == {
        key: value for key, value in auto_import.items() if key != 'trigger_context'
    }


def test_normalize_actions_for_link_update_only_keeps_fetch_forum_tags():
    normalized = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_LINK_UPDATE)

    assert _action_types(normalized['actions']) == [ACT_FETCH_FORUM_TAGS]


def test_normalize_actions_for_link_update_keeps_source_baseline_action():
    normalized = normalize_actions_for_context(
        [{'type': ACT_REFRESH_SOURCE_BASELINE}],
        TRIGGER_CONTEXT_LINK_UPDATE,
    )

    assert _action_types(normalized['actions']) == [ACT_REFRESH_SOURCE_BASELINE]


def test_auto_and_manual_paths_share_identical_snapshot_template_fields(monkeypatch):
    captured_auto = {}
    captured_manual = {}
    card_id = 'folder/demo.json'
    card_obj = {
        'id': card_id,
        'filename': 'demo.json',
        'category': 'folder',
        'char_name': 'Demo',
        'tags': [],
        'last_modified': 1704067200,
        'token_count': 0,
    }
    fake_cache = SimpleNamespace(
        id_map={card_id: card_obj},
        bundle_map={},
        initialized=True,
        reload_from_db=lambda: None,
    )
    ui_payload = {card_id: {'import_time': 1704153600}}

    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, 'load_ui_data', lambda: ui_payload)
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda value: value)
    monkeypatch.setattr(
        automation_service,
        'load_config',
        lambda: {
            'active_automation_ruleset': 'ruleset-1',
            'automation_slash_is_tag_separator': False,
        },
    )
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.executor, 'apply_plan', lambda *args, **kwargs: {'moved_to': None, 'tags_added': [], 'tags_removed': [], 'final_id': card_id})

    def _capture_auto(context_data, ruleset, match_if_no_conditions=True):
        captured_auto.update({
            'filename_stem': context_data.get('filename_stem'),
            'category': context_data.get('category'),
            'import_time': context_data.get('import_time'),
            'import_date': context_data.get('import_date'),
            'modified_time': context_data.get('modified_time'),
            'modified_date': context_data.get('modified_date'),
        })
        return {'actions': []}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _capture_auto)

    auto_result = automation_service.auto_run_rules_on_card(card_id)

    assert auto_result == {'run': True, 'actions': 0}

    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: ui_payload)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_api.executor, 'apply_plan', lambda *args, **kwargs: {'moved_to': None, 'tags_added': [], 'tags_removed': [], 'final_id': card_id})

    def _capture_manual(context_data, ruleset, match_if_no_conditions=True):
        captured_manual.update({
            'filename_stem': context_data.get('filename_stem'),
            'category': context_data.get('category'),
            'import_time': context_data.get('import_time'),
            'import_date': context_data.get('import_date'),
            'modified_time': context_data.get('modified_time'),
            'modified_date': context_data.get('modified_date'),
        })
        return {'actions': []}

    monkeypatch.setattr(automation_api.engine, 'evaluate', _capture_manual)

    client = _make_automation_app().test_client()
    response = client.post('/api/automation/execute', json={'card_ids': [card_id], 'ruleset_id': 'ruleset-1'})

    assert response.status_code == 200
    assert response.get_json()['success'] is True
    assert captured_manual == captured_auto == {
        'filename_stem': 'demo',
        'category': 'folder',
        'import_time': 1704153600.0,
        'import_date': '2024-01-02',
        'modified_time': 1704067200.0,
        'modified_date': '2024-01-01',
    }


def test_normalize_actions_for_tag_edit_only_keeps_merge_tags():
    normalized = normalize_actions_for_context(_sample_actions(), TRIGGER_CONTEXT_TAG_EDIT)

    assert _action_types(normalized['actions']) == [ACT_MERGE_TAGS]


def test_auto_run_rules_on_card_uses_shared_normalizer_for_auto_import(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_AUTO_IMPORT,
        'actions': [
            {'type': ACT_ADD_TAG, 'value': 'normalized-tag'},
            {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
        ],
        'derived': {'add_tags': {'normalized-tag'}, 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    monkeypatch.setattr(
        automation_service,
        'load_config',
        lambda: {
            'active_automation_ruleset': 'ruleset-1',
            'automation_slash_is_tag_separator': False,
        },
    )
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_ADD_TAG, 'value': 'raw-tag'},
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'raw'}},
                {'type': ACT_MERGE_TAGS, 'value': {'old': 'new'}},
                {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{filename_stem}}'},
            ]
        },
    )

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        captured['trigger_context'] = trigger_context
        captured['card_snapshot'] = card_snapshot
        return normalized_plan

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_card_id'] = card_id_arg
        captured['applied_plan'] = plan
        return {'final_id': card_id_arg, 'tags_added': list(plan.get('add_tags', []))}

    monkeypatch.setattr(automation_service, 'normalize_actions_for_context', _fake_normalize)
    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)

    result = automation_service.auto_run_rules_on_card(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['trigger_context'] == TRIGGER_CONTEXT_AUTO_IMPORT
    assert _action_types(captured['normalize_actions']) == [
        ACT_ADD_TAG,
        ACT_FETCH_FORUM_TAGS,
        ACT_MERGE_TAGS,
        ACT_RENAME_FILE_BY_TEMPLATE,
    ]
    assert captured['card_snapshot'] == {'id': card_id}
    assert captured['applied_card_id'] == card_id
    assert captured['applied_plan']['add_tags'] == {'normalized-tag'}
    assert captured['applied_plan']['remove_tags'] == set()
    assert captured['applied_plan']['fetch_forum_tags'] is None
    assert captured['applied_plan']['rename_file_by_template'] == '{{char_name}}'


def test_auto_run_rules_for_trigger_uses_legacy_default_trigger_contexts(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'legacy-rule',
                'enabled': True,
                'groups': [],
                'actions': [{'type': ACT_ADD_TAG, 'value': 'legacy-tag'}],
            }
        ]
    }

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
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['ruleset'] = filtered_ruleset
        return {'actions': [{'type': ACT_ADD_TAG, 'value': 'legacy-tag'}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': {'legacy-tag'}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: {'final_id': card_id_arg, 'tags_added': list(plan.get('add_tags', []))},
    )

    result = automation_service.auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_AUTO_IMPORT)

    assert result is not None
    assert result['run'] is True
    assert [rule['name'] for rule in captured['ruleset']['rules']] == ['legacy-rule']


def test_normalize_rule_trigger_contexts_derives_legacy_contexts_from_actions():
    assert automation_service._normalize_rule_trigger_contexts({
        'actions': [
            {'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'legacy'}},
            {'type': ACT_MERGE_TAGS, 'value': {'old': 'new'}},
        ]
    }) == [
        TRIGGER_CONTEXT_MANUAL_RUN,
        TRIGGER_CONTEXT_AUTO_IMPORT,
        TRIGGER_CONTEXT_LINK_UPDATE,
        TRIGGER_CONTEXT_TAG_EDIT,
    ]


def test_auto_run_rules_for_trigger_only_evaluates_card_update_rules(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'manual-default',
                'enabled': False,
                'groups': [],
                'actions': [{'type': ACT_ADD_TAG, 'value': 'manual-default'}],
            },
            {
                'name': 'card-update-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_CARD_UPDATE],
                'groups': [],
                'actions': [{'type': ACT_ADD_TAG, 'value': 'card-update-only'}],
            },
            {
                'name': 'auto-import-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_AUTO_IMPORT],
                'groups': [],
                'actions': [{'type': ACT_ADD_TAG, 'value': 'auto-import-only'}],
            },
        ]
    }

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
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {
            'actions': [
                {'type': ACT_ADD_TAG, 'value': 'card-update-only'},
            ]
        }

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': {'card-update-only'}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: {'final_id': card_id_arg, 'tags_added': sorted(plan.get('add_tags', []))},
    )

    result = automation_service.auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_CARD_UPDATE)

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['card-update-only']


def test_auto_run_rules_for_trigger_accepts_string_trigger_contexts(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'string-card-update-only',
                'enabled': True,
                'trigger_contexts': f'  {TRIGGER_CONTEXT_CARD_UPDATE}  ',
                'groups': [],
                'actions': [{'type': ACT_ADD_TAG, 'value': 'card-update-only'}],
            },
        ]
    }

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
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {'actions': [{'type': ACT_ADD_TAG, 'value': 'card-update-only'}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': {'card-update-only'}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: {'final_id': card_id_arg, 'tags_added': sorted(plan.get('add_tags', []))},
    )

    result = automation_service.auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_CARD_UPDATE)

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['string-card-update-only']


def test_auto_run_rules_for_trigger_uses_card_update_normalizer_context(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_CARD_UPDATE,
        'actions': [
            {'type': ACT_ADD_TAG, 'value': 'card-update-tag'},
            {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
        ],
        'derived': {'add_tags': {'card-update-tag'}, 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    monkeypatch.setattr(
        automation_service,
        'load_config',
        lambda: {
            'active_automation_ruleset': 'ruleset-1',
            'automation_slash_is_tag_separator': False,
        },
    )
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_ADD_TAG, 'value': 'raw-tag'},
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'raw'}},
                {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{filename_stem}}'},
            ]
        },
    )

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        captured['trigger_context'] = trigger_context
        captured['card_snapshot'] = card_snapshot
        return normalized_plan

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_card_id'] = card_id_arg
        captured['applied_plan'] = plan
        return {'final_id': card_id_arg, 'tags_added': list(plan.get('add_tags', []))}

    monkeypatch.setattr(automation_service, 'normalize_actions_for_context', _fake_normalize)
    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)

    result = automation_service.auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_CARD_UPDATE)

    assert result is not None
    assert result['run'] is True
    assert captured['trigger_context'] == TRIGGER_CONTEXT_CARD_UPDATE
    assert _action_types(captured['normalize_actions']) == [
        ACT_ADD_TAG,
        ACT_FETCH_FORUM_TAGS,
        ACT_RENAME_FILE_BY_TEMPLATE,
    ]
    assert captured['card_snapshot'] == {'id': card_id}
    assert captured['applied_card_id'] == card_id
    assert captured['applied_plan']['add_tags'] == {'card-update-tag'}
    assert captured['applied_plan']['remove_tags'] == set()
    assert captured['applied_plan']['fetch_forum_tags'] is None
    assert captured['applied_plan']['rename_file_by_template'] == '{{char_name}}'


def test_auto_run_rules_for_trigger_returns_failure_payload_on_internal_error(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )

    monkeypatch.setattr(
        automation_service,
        'load_config',
        lambda: {
            'active_automation_ruleset': 'ruleset-1',
            'automation_slash_is_tag_separator': False,
        },
    )
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_ADD_TAG, 'value': 'card-update-tag'}]},
    )
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': {'card-update-tag'}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: (_ for _ in ()).throw(RuntimeError('boom')),
    )

    result = automation_service.auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_CARD_UPDATE)

    assert result == {'run': False, 'error': 'boom'}


def test_auto_run_forum_tags_on_link_update_normalizes_fetch_only_then_runs_merge_follow_up(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['after-fetch', 'legacy'],
            }
        },
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_ADD_TAG, 'value': 'raw-tag'},
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
                {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
            ]
        },
    )

    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_LINK_UPDATE,
        'actions': [
            {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'normalized-forum'}},
        ],
        'derived': {'add_tags': set(), 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        captured['trigger_context'] = trigger_context
        captured['card_snapshot'] = card_snapshot
        return normalized_plan

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_plan'] = plan
        captured['applied_ui_data'] = ui_data
        return {
            'final_id': card_id_arg,
            'tags_added': ['after-fetch', 'legacy'],
            'forum_tags_fetched': {
                'provider': 'normalized-forum',
                'tags': ['after-fetch', 'fresh-forum-tag'],
            },
        }

    def _fake_tag_merge(card_id_arg, tags, ui_data=None, runtime=None):
        captured['merge_card_id'] = card_id_arg
        captured['merge_tags'] = list(tags)
        captured['merge_ui_data'] = ui_data
        captured['merge_runtime'] = runtime
        return {
            'run': True,
            'actions': 1,
            'result': {
                'tags': ['after-fetch', 'modern'],
                'changed': True,
                'replacements': [{'from': 'legacy', 'to': 'modern'}],
                'replace_rules': {'legacy': 'modern'},
            },
        }

    monkeypatch.setattr(automation_service, 'normalize_actions_for_context', _fake_normalize)
    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_service, 'auto_run_tag_merge_on_tagging', _fake_tag_merge)
    monkeypatch.setattr(automation_service, 'modify_card_attributes_internal', lambda *args, **kwargs: True, raising=False)

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['trigger_context'] == TRIGGER_CONTEXT_LINK_UPDATE
    assert _action_types(captured['normalize_actions']) == [
        ACT_ADD_TAG,
        ACT_FETCH_FORUM_TAGS,
        ACT_MERGE_TAGS,
    ]
    assert captured['card_snapshot'] == {'id': card_id}
    assert captured['applied_plan']['fetch_forum_tags'] == {'provider': 'normalized-forum'}
    assert captured['applied_plan']['add_tags'] == set()
    assert captured['merge_card_id'] == card_id
    assert captured['merge_tags'] == ['after-fetch', 'fresh-forum-tag']
    assert captured['merge_ui_data'] == {'ui': 'data'}
    assert captured['merge_runtime'] == {
        'ruleset_id': 'ruleset-1',
        'ruleset': {'rules': []},
        'slash_as_separator': False,
    }
    assert result['result']['tag_merge'] == {
        'triggered': True,
        'changed': True,
        'replacements': [{'from': 'legacy', 'to': 'modern'}],
        'replace_rules': {'legacy': 'modern'},
        'actions': 1,
    }


def test_auto_run_forum_tags_on_link_update_filters_rules_before_evaluation(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'link-update-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_LINK_UPDATE],
                'groups': [],
                'actions': [{'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'link'}}],
            },
            {
                'name': 'tag-edit-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_TAG_EDIT],
                'groups': [],
                'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'new'}}],
            },
        ]
    }

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
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {'actions': [{'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'link'}}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: {'final_id': card_id_arg, 'tags_added': ['after-fetch']},
    )
    monkeypatch.setattr(
        automation_service,
        'auto_run_tag_merge_on_tagging',
        lambda *args, **kwargs: {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': ['after-fetch']}},
    )

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['link-update-only']


def test_auto_run_forum_tags_on_link_update_keeps_legacy_rules_without_trigger_contexts(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['existing'],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'legacy-link-rule',
                'enabled': True,
                'groups': [],
                'actions': [{'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'legacy'}}],
            },
        ]
    }

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
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {'actions': [{'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'legacy'}}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: {
            'final_id': card_id_arg,
            'forum_tags_fetched': {'provider': 'legacy', 'tags': ['existing', 'fetched']},
        },
    )
    monkeypatch.setattr(
        automation_service,
        'auto_run_tag_merge_on_tagging',
        lambda *args, **kwargs: {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': ['existing', 'fetched']}},
    )

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['legacy-link-rule']


def test_auto_run_forum_tags_on_link_update_filters_governed_tags_before_writeback(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['existing', 'blocked-tag', 'unknown-tag'],
            }
        },
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
                {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
            ]
        },
    )

    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_LINK_UPDATE,
        'actions': [
            {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'normalized-forum'}},
        ],
        'derived': {'add_tags': set(), 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        return normalized_plan

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_plan'] = plan
        fake_cache.id_map[card_id_arg]['tags'] = ['existing', 'allowed-tag', 'blocked-tag', 'unknown-tag']
        return {
            'final_id': card_id_arg,
            'tags_added': ['existing', 'allowed-tag', 'blocked-tag', 'unknown-tag'],
            'forum_tags_fetched': {
                'provider': 'normalized-forum',
                'tags': ['existing', 'allowed-tag', 'blocked-tag', 'unknown-tag'],
            },
        }

    def _fake_tag_merge(card_id_arg, tags, ui_data=None, runtime=None):
        captured['merge_tags'] = list(tags)
        return {
            'run': True,
            'actions': 1,
            'result': {
                'tags': ['existing', 'allowed-tag'],
                'changed': True,
                'replacements': [],
                'replace_rules': {},
                'skipped_unknown': ['unknown-tag'],
                'skipped_blacklist': ['blocked-tag'],
            },
        }

    def _fake_modify_card_attributes_internal(card_id_arg, add_tags=None, remove_tags=None, runtime=None):
        captured['writeback'] = {
            'card_id': card_id_arg,
            'add_tags': list(add_tags or []),
            'remove_tags': list(remove_tags or []),
        }
        return True

    monkeypatch.setattr(automation_service, 'normalize_actions_for_context', _fake_normalize)
    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_service, 'auto_run_tag_merge_on_tagging', _fake_tag_merge)
    monkeypatch.setattr(automation_service, 'modify_card_attributes_internal', _fake_modify_card_attributes_internal, raising=False)

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['applied_plan']['fetch_forum_tags'] == {'provider': 'normalized-forum'}
    assert captured['merge_tags'] == ['existing', 'allowed-tag', 'blocked-tag', 'unknown-tag']
    assert captured['writeback']['card_id'] == card_id
    assert captured['writeback']['add_tags'] == []
    assert set(captured['writeback']['remove_tags']) == {'blocked-tag', 'unknown-tag'}
    assert result['result']['final_tags'] == ['existing', 'allowed-tag']
    assert result['result']['tag_merge'] == {
        'triggered': True,
        'changed': True,
        'replacements': [],
        'replace_rules': {},
        'actions': 1,
        'skipped_unknown': ['unknown-tag'],
        'skipped_blacklist': ['blocked-tag'],
    }


def test_auto_run_forum_tags_on_link_update_uses_full_tag_source_for_merge_follow_up(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
            ]
        },
    )
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        return {
            'final_id': card_id_arg,
            'tags_added': ['delta-only'],
            'forum_tags_fetched': {
                'provider': 'forum',
                'tags': ['full-a', 'full-b'],
            },
        }

    def _fake_tag_merge(card_id_arg, tags, ui_data=None, runtime=None):
        captured['merge_tags'] = list(tags)
        return {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': list(tags)}}

    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_service, 'auto_run_tag_merge_on_tagging', _fake_tag_merge)

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['merge_tags'] == ['full-a', 'full-b']


def test_auto_run_forum_tags_on_link_update_prefers_fetched_full_tags_over_stale_cache(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['stale-cache-tag'],
            }
        },
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
            ]
        },
    )
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        return {
            'final_id': card_id_arg,
            'tags_added': ['delta-only'],
            'forum_tags_fetched': {
                'provider': 'forum',
                'tags': ['fresh-a', 'fresh-b'],
            },
        }

    def _fake_tag_merge(card_id_arg, tags, ui_data=None, runtime=None):
        captured['merge_tags'] = list(tags)
        return {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': list(tags)}}

    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_service, 'auto_run_tag_merge_on_tagging', _fake_tag_merge)

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert captured['merge_tags'] == ['fresh-a', 'fresh-b']


def test_auto_run_forum_tags_on_link_update_keeps_empty_fetched_tags_instead_of_stale_cache(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['stale-cache-tag'],
            }
        },
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
            ]
        },
    )
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        return {
            'final_id': card_id_arg,
            'tags_added': [],
            'forum_tags_fetched': {
                'provider': 'forum',
                'tags': [],
            },
        }

    def _fake_tag_merge(card_id_arg, tags, ui_data=None, runtime=None):
        captured['merge_tags'] = list(tags)
        return {'run': True, 'actions': 0, 'result': {'changed': False, 'tags': list(tags)}}

    monkeypatch.setattr(automation_service.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_service, 'auto_run_tag_merge_on_tagging', _fake_tag_merge)

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result is not None
    assert result['run'] is True
    assert result['result']['final_tags'] == []
    assert 'merge_tags' not in captured


def test_auto_run_tag_merge_on_tagging_uses_shared_normalizer_for_tag_edit(monkeypatch):
    card_id = 'folder/demo.json'
    tags = ['legacy', 'keep']
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': tags,
            }
        },
        bundle_map={},
    )
    captured = {}
    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_TAG_EDIT,
        'actions': [
            {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
        ],
        'derived': {'add_tags': set(), 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_runtime_from_active_ruleset', lambda: {
        'ruleset_id': 'ruleset-1',
        'ruleset': {'rules': []},
        'slash_as_separator': False,
    })
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {'ui': 'data'}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_ADD_TAG, 'value': 'raw-tag'},
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
                {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
            ]
        },
    )

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        captured['trigger_context'] = trigger_context
        captured['card_snapshot'] = card_snapshot
        return normalized_plan

    def _fake_apply_merge_actions_to_tags(tags_arg, merge_actions, slash_as_separator=False):
        captured['merge_tags_input'] = list(tags_arg)
        captured['merge_actions'] = merge_actions
        captured['slash_as_separator'] = slash_as_separator
        return {
            'tags': ['modern', 'keep'],
            'changed': True,
            'replacements': [{'from': 'legacy', 'to': 'modern'}],
            'replace_rules': {'legacy': 'modern'},
        }

    monkeypatch.setattr(automation_service, 'normalize_actions_for_context', _fake_normalize)
    monkeypatch.setattr(automation_service, 'apply_merge_actions_to_tags', _fake_apply_merge_actions_to_tags)

    result = automation_service.auto_run_tag_merge_on_tagging(card_id, tags)

    assert result is not None
    assert result['run'] is True
    assert result['actions'] == 1
    assert captured['trigger_context'] == TRIGGER_CONTEXT_TAG_EDIT
    assert _action_types(captured['normalize_actions']) == [
        ACT_ADD_TAG,
        ACT_FETCH_FORUM_TAGS,
        ACT_MERGE_TAGS,
    ]
    assert captured['card_snapshot'] == {'id': card_id}
    assert captured['merge_tags_input'] == tags
    assert captured['merge_actions'] == [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}}]
    assert captured['merge_actions'] is normalized_plan['actions']
    assert captured['slash_as_separator'] is False


def test_auto_run_tag_merge_on_tagging_filters_rules_before_evaluation(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['legacy'],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'tag-edit-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_TAG_EDIT],
                'groups': [],
                'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'new'}}],
            },
            {
                'name': 'link-update-only',
                'enabled': True,
                'trigger_contexts': [TRIGGER_CONTEXT_LINK_UPDATE],
                'groups': [],
                'actions': [{'type': ACT_FETCH_FORUM_TAGS, 'value': {'source': 'link'}}],
            },
        ]
    }

    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id, 'tags': ['legacy']}, {'ui': 'data'}),
    )

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'new'}}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service,
        'apply_merge_actions_to_tags',
        lambda tags, merge_actions, slash_as_separator=False: {
            'tags': ['new'],
            'changed': True,
            'replacements': ['legacy->new'],
            'replace_rules': {'legacy': 'new'},
        },
    )

    result = automation_service.auto_run_tag_merge_on_tagging(
        card_id,
        ['legacy'],
        runtime={'ruleset_id': 'ruleset-1', 'ruleset': ruleset, 'slash_as_separator': False},
    )

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['tag-edit-only']


def test_auto_run_tag_merge_on_tagging_keeps_legacy_rules_without_trigger_contexts(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': ['legacy'],
            }
        },
        bundle_map={},
    )
    captured = {}
    ruleset = {
        'rules': [
            {
                'name': 'legacy-tag-rule',
                'enabled': True,
                'groups': [],
                'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'new'}}],
            },
        ]
    }

    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id, 'tags': ['legacy']}, {'ui': 'data'}),
    )

    def _fake_evaluate(context_data, filtered_ruleset, match_if_no_conditions=True):
        captured['rule_names'] = [rule['name'] for rule in filtered_ruleset['rules']]
        return {'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'new'}}]}

    monkeypatch.setattr(automation_service.engine, 'evaluate', _fake_evaluate)
    monkeypatch.setattr(
        automation_service,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': actions,
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
    )
    monkeypatch.setattr(
        automation_service,
        'apply_merge_actions_to_tags',
        lambda tags, merge_actions, slash_as_separator=False: {
            'tags': ['new'],
            'changed': True,
            'replacements': ['legacy->new'],
            'replace_rules': {'legacy': 'new'},
        },
    )

    result = automation_service.auto_run_tag_merge_on_tagging(
        card_id,
        ['legacy'],
        runtime={'ruleset_id': 'ruleset-1', 'ruleset': ruleset, 'slash_as_separator': False},
    )

    assert result is not None
    assert result['run'] is True
    assert captured['rule_names'] == ['legacy-tag-rule']


def test_normalize_actions_expands_split_category_to_append_only_add_tags():
    normalized = normalize_actions_for_context(
        [
            {'type': ACT_ADD_TAG, 'value': 'existing'},
            {'type': ACT_SPLIT_CATEGORY_TO_TAGS},
        ],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={
            'category': '  A / b  ',
            'tags': ['existing', 'keep-me'],
        },
    )

    assert normalized['actions'] == [
        {'type': ACT_ADD_TAG, 'value': 'existing'},
        {'type': ACT_ADD_TAG, 'value': 'A'},
        {'type': ACT_ADD_TAG, 'value': 'b'},
    ]
    assert normalized['derived'] == {
        'add_tags': {'existing', 'A', 'b'},
        'remove_tags': set(),
    }
    assert normalized['observability']['category_tag_expansions'] == [
        {
            'source_category': '  A / b  ',
            'derived_tags': ['A', 'b'],
            'excluded_segments': [],
        }
    ]


def test_normalize_actions_split_category_handles_mixed_separators_and_case_insensitive_exclusions():
    normalized = normalize_actions_for_context(
        [
            {
                'type': ACT_SPLIT_CATEGORY_TO_TAGS,
                'value': {'exclude_segments': ['  ROOT ', ' skip ']},
            }
        ],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={
            'category': r'  Root // Alpha\\ Skip / Beta  ',
            'tags': ['keep-me'],
        },
    )

    assert normalized['actions'] == [
        {'type': ACT_ADD_TAG, 'value': 'Alpha'},
        {'type': ACT_ADD_TAG, 'value': 'Beta'},
    ]
    assert normalized['derived']['add_tags'] == {'Alpha', 'Beta'}
    assert normalized['observability']['category_tag_expansions'] == [
        {
            'source_category': r'  Root // Alpha\\ Skip / Beta  ',
            'derived_tags': ['Alpha', 'Beta'],
            'excluded_segments': ['ROOT', 'skip'],
        }
    ]


def test_normalize_actions_split_category_ignores_empty_or_root_only_categories():
    root_only = normalize_actions_for_context(
        [{'type': ACT_SPLIT_CATEGORY_TO_TAGS}],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={'category': ' // \\ ', 'tags': ['keep-me']},
    )
    empty_value = normalize_actions_for_context(
        [{'type': ACT_SPLIT_CATEGORY_TO_TAGS}],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={'category': '', 'tags': ['keep-me']},
    )

    assert root_only['actions'] == []
    assert root_only['derived']['add_tags'] == set()
    assert root_only['observability']['category_tag_expansions'] == [
        {
            'source_category': ' // \\ ',
            'derived_tags': [],
            'excluded_segments': [],
        }
    ]
    assert empty_value['actions'] == []
    assert empty_value['derived']['add_tags'] == set()
    assert empty_value['observability']['category_tag_expansions'] == [
        {
            'source_category': '',
            'derived_tags': [],
            'excluded_segments': [],
        }
    ]


def test_normalize_actions_uses_pre_move_category_for_split_category_to_tags():
    normalized = normalize_actions_for_context(
        [
            {'type': ACT_MOVE, 'value': 'new/place'},
            {'type': ACT_SPLIT_CATEGORY_TO_TAGS},
        ],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={
            'category': 'before/move',
            'tags': [],
        },
    )

    assert normalized['actions'] == [
        {'type': ACT_MOVE, 'value': 'new/place'},
        {'type': ACT_ADD_TAG, 'value': 'before'},
        {'type': ACT_ADD_TAG, 'value': 'move'},
    ]
    assert normalized['observability']['category_tag_expansions'][0]['source_category'] == 'before/move'


def test_normalize_actions_keeps_highest_priority_filename_action_and_reports_suppressed_conflicts():
    normalized = normalize_actions_for_context(
        [
            {'type': ACT_SET_FILENAME_FROM_WI_NAME},
            {'type': ACT_SET_FILENAME_FROM_CHAR_NAME},
            {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
        ],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={'category': 'folder/demo', 'tags': []},
    )

    assert normalized['actions'] == [
        {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
    ]
    assert normalized['observability']['suppressed_filename_action_conflicts'] == [
        {
            'reason': 'lower_priority_filename_action',
            'winner': ACT_RENAME_FILE_BY_TEMPLATE,
            'suppressed': ACT_SET_FILENAME_FROM_CHAR_NAME,
        },
        {
            'reason': 'lower_priority_filename_action',
            'winner': ACT_RENAME_FILE_BY_TEMPLATE,
            'suppressed': ACT_SET_FILENAME_FROM_WI_NAME,
        },
    ]


def test_normalize_actions_reports_same_priority_filename_conflict_separately():
    normalized = normalize_actions_for_context(
        [
            {'type': ACT_SET_FILENAME_FROM_CHAR_NAME},
            {'type': ACT_SET_FILENAME_FROM_CHAR_NAME},
        ],
        TRIGGER_CONTEXT_MANUAL_RUN,
        card_snapshot={'category': 'folder/demo', 'tags': []},
    )

    assert normalized['actions'] == [
        {'type': ACT_SET_FILENAME_FROM_CHAR_NAME},
    ]
    assert normalized['observability']['suppressed_filename_action_conflicts'] == [
        {
            'reason': 'same_priority_filename_action',
            'winner': ACT_SET_FILENAME_FROM_CHAR_NAME,
            'suppressed': ACT_SET_FILENAME_FROM_CHAR_NAME,
        }
    ]


def test_manual_execute_reuses_shared_rule_context_builder(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'tags': [],
            }
        },
        bundle_map={},
        initialized=True,
    )
    captured = {}

    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {'ui': {'summary': 'ui summary', 'link': 'https://example.test'}})
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda value: 'ui')
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: _make_ruleset('file_size', '123'))

    def _fake_build_rule_context(card_id_arg, card_obj_arg, ruleset_arg, ui_data=None, tags=None):
        captured['called'] = True
        captured['card_id'] = card_id_arg
        captured['card_obj'] = card_obj_arg
        captured['ui_data'] = ui_data
        captured['tags'] = tags
        return ({
            'id': card_id_arg,
            'filename': card_obj_arg['filename'],
            'char_name': card_obj_arg['char_name'],
            'token_count': 7,
            'file_size': 123,
            'ui_summary': 'from-helper',
            'source_link': 'helper-link',
        }, ui_data)

    monkeypatch.setattr(automation_service, '_build_rule_context', _fake_build_rule_context)
    monkeypatch.setattr(automation_service.os.path, 'getsize', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('should not compute file_size inline')))

    def _capture_manual(context_data, ruleset, match_if_no_conditions=True):
        captured['context_data'] = context_data
        return {'actions': []}

    monkeypatch.setattr(automation_api.engine, 'evaluate', _capture_manual)
    monkeypatch.setattr(
        automation_api.executor,
        'apply_plan',
        lambda *args, **kwargs: {'moved_to': None, 'tags_added': [], 'tags_removed': [], 'final_id': card_id},
    )

    client = _make_automation_app().test_client()
    response = client.post('/api/automation/execute', json={'card_ids': [card_id], 'ruleset_id': 'ruleset-1'})

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 1,
        'processed': 0,
        'skipped': 0,
        'summary': {
            'moves': 0,
            'tag_changes': 0,
        },
        'details': {
            'skipped': [],
        },
    }
    assert captured['called'] is True
    assert captured['card_id'] == card_id
    assert captured['card_obj'] == fake_cache.id_map[card_id]
    assert captured['tags'] is None
    assert captured['context_data']['file_size'] == 123
    assert captured['context_data']['ui_summary'] == 'from-helper'


def test_manual_execute_uses_shared_normalizer_for_manual_run_and_preserves_merge_follow_up(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'category': 'folder/sub',
                'tags': ['legacy'],
            }
        },
        bundle_map={},
        initialized=True,
    )
    captured = {}

    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {'ui': {'summary': 'ui summary', 'link': 'https://example.test'}})
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda value: 'ui')
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id, 'category': 'folder/sub', 'tags': ['legacy'], 'token_count': 1}, {'ui': 'data'}),
    )
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {
            'actions': [
                {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
                {'type': ACT_SPLIT_CATEGORY_TO_TAGS},
                {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'forum'}},
                {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
            ]
        },
    )

    normalized_plan = {
        'trigger_context': TRIGGER_CONTEXT_MANUAL_RUN,
        'actions': [
            {'type': ACT_ADD_TAG, 'value': 'folder'},
            {'type': ACT_ADD_TAG, 'value': 'sub'},
            {'type': ACT_FETCH_FORUM_TAGS, 'value': {'provider': 'normalized'}},
            {'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}},
            {'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'},
        ],
        'derived': {'add_tags': {'folder', 'sub'}, 'remove_tags': set()},
        'observability': {
            'category_tag_expansions': [],
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [],
        },
    }

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        captured['trigger_context'] = trigger_context
        captured['card_snapshot'] = card_snapshot
        return normalized_plan

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_card_id'] = card_id_arg
        captured['applied_plan'] = plan
        captured['applied_ui_data'] = ui_data
        fake_cache.id_map[card_id_arg]['tags'] = ['legacy', 'folder', 'sub']
        return {
            'moved_to': None,
            'tags_added': ['folder', 'sub'],
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': {'provider': 'normalized'},
            'final_id': card_id_arg,
        }

    def _fake_apply_merge_actions_to_tags(tags, merge_actions, slash_as_separator=False):
        captured['merge_tags_input'] = list(tags)
        captured['merge_actions'] = list(merge_actions)
        captured['merge_slash_as_separator'] = slash_as_separator
        return {
            'tags': ['modern', 'folder', 'sub'],
            'changed': True,
            'replacements': [{'from': 'legacy', 'to': 'modern'}],
            'replace_rules': {'legacy': 'modern'},
        }

    def _fake_modify_card_attributes_internal(card_id_arg, add_tags=None, remove_tags=None):
        captured['merged_card_id'] = card_id_arg
        captured['merged_add_tags'] = list(add_tags or [])
        captured['merged_remove_tags'] = list(remove_tags or [])
        return True

    monkeypatch.setattr(automation_api, 'normalize_actions_for_context', _fake_normalize, raising=False)
    monkeypatch.setattr(automation_api.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(automation_api, 'apply_merge_actions_to_tags', _fake_apply_merge_actions_to_tags)
    monkeypatch.setattr(automation_api, 'modify_card_attributes_internal', _fake_modify_card_attributes_internal)

    client = _make_automation_app().test_client()
    response = client.post('/api/automation/execute', json={'card_ids': [card_id], 'ruleset_id': 'ruleset-1'})

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 1,
        'processed': 1,
        'skipped': 0,
        'summary': {
            'moves': 0,
            'tag_changes': 2,
        },
        'details': {
            'skipped': [],
        },
    }
    assert captured['trigger_context'] == TRIGGER_CONTEXT_MANUAL_RUN
    assert _action_types(captured['normalize_actions']) == [
        ACT_RENAME_FILE_BY_TEMPLATE,
        ACT_SPLIT_CATEGORY_TO_TAGS,
        ACT_FETCH_FORUM_TAGS,
        ACT_MERGE_TAGS,
    ]
    assert captured['card_snapshot'] == {'id': card_id, 'category': 'folder/sub', 'tags': ['legacy'], 'token_count': 1}
    assert captured['applied_card_id'] == card_id
    assert captured['applied_ui_data'] == {'ui': 'data'}
    assert captured['applied_plan']['add_tags'] == {'folder', 'sub'}
    assert captured['applied_plan']['remove_tags'] == set()
    assert captured['applied_plan']['fetch_forum_tags'] == {'provider': 'normalized'}
    assert captured['merge_tags_input'] == ['legacy', 'folder', 'sub']
    assert captured['merge_actions'] == [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}}]
    assert captured['merge_slash_as_separator'] is False
    assert captured['merged_card_id'] == card_id
    assert captured['merged_add_tags'] == ['modern']
    assert captured['merged_remove_tags'] == ['legacy']


def test_manual_execute_preserves_batch_snapshot_when_earlier_items_mutate(monkeypatch):
    first_id = 'folder/first.json'
    second_id = 'folder/second.json'
    fake_cache = SimpleNamespace(
        id_map={
            first_id: {
                'id': first_id,
                'filename': 'first.json',
                'char_name': 'First',
                'category': 'folder/first',
                'tags': [],
            },
            second_id: {
                'id': second_id,
                'filename': 'second.json',
                'char_name': 'Second',
                'category': 'folder/second',
                'tags': [],
            },
        },
        bundle_map={},
        initialized=True,
    )
    captured = {'processed_ids': [], 'normalized_snapshots': []}

    class _FakeCursor:
        def execute(self, *args, **kwargs):
            captured['db_query'] = {'args': args, 'kwargs': kwargs}

        def fetchall(self):
            return [(first_id,), (second_id,)]

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(automation_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})

    def _fake_build_rule_context(card_id_arg, card_obj_arg, ruleset_arg, ui_data=None, tags=None):
        return ({
            'id': card_id_arg,
            'category': card_obj_arg['category'],
            'tags': card_obj_arg.get('tags') or [],
            'token_count': 0,
        }, ui_data or {})

    monkeypatch.setattr(automation_service, '_build_rule_context', _fake_build_rule_context)
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_SPLIT_CATEGORY_TO_TAGS}]},
    )

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalized_snapshots'].append(dict(card_snapshot))
        category = card_snapshot.get('category') or ''
        leaf = category.split('/')[-1]
        return {
            'trigger_context': trigger_context,
            'actions': [{'type': ACT_ADD_TAG, 'value': leaf}],
            'derived': {'add_tags': {leaf}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        }

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['processed_ids'].append(card_id_arg)
        if card_id_arg == first_id:
            fake_cache.id_map[first_id]['category'] = 'renamed/first'
            fake_cache.id_map[second_id]['category'] = 'renamed/second'
            fake_cache.id_map[second_id]['tags'].append('drifted')
        return {
            'moved_to': None,
            'tags_added': list(plan.get('add_tags', [])),
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': None,
            'final_id': card_id_arg,
        }

    monkeypatch.setattr(automation_api, 'normalize_actions_for_context', _fake_normalize, raising=False)
    monkeypatch.setattr(automation_api.executor, 'apply_plan', _fake_apply_plan)

    client = _make_automation_app().test_client()
    response = client.post(
        '/api/automation/execute',
        json={'category': 'folder', 'recursive': True, 'ruleset_id': 'ruleset-1'},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 2,
        'processed': 2,
        'skipped': 0,
        'summary': {
            'moves': 0,
            'tag_changes': 2,
        },
        'details': {
            'skipped': [],
        },
    }
    assert set(captured['processed_ids']) == {first_id, second_id}
    snapshots_by_id = {snapshot['id']: snapshot for snapshot in captured['normalized_snapshots']}
    assert set(snapshots_by_id) == {first_id, second_id}
    assert snapshots_by_id[first_id]['category'] == 'folder/first'
    assert snapshots_by_id[second_id]['category'] == 'folder/second'
    assert snapshots_by_id[first_id]['tags'] == []
    assert snapshots_by_id[second_id]['tags'] == []


def test_manual_execute_reports_skipped_targets_missing_from_cache(monkeypatch):
    existing_id = 'folder/existing.json'
    missing_id = 'folder/missing.json'
    fake_cache = SimpleNamespace(
        id_map={
            existing_id: {
                'id': existing_id,
                'filename': 'existing.json',
                'char_name': 'Existing',
                'category': 'folder',
                'tags': ['legacy'],
            }
        },
        bundle_map={},
        initialized=True,
    )
    captured = {'processed_ids': []}

    class _FakeCursor:
        def execute(self, *args, **kwargs):
            captured['db_query'] = {'args': args, 'kwargs': kwargs}

        def fetchall(self):
            return [(existing_id,), (missing_id,)]

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(automation_api, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': existing_id, 'category': 'folder', 'tags': ['legacy'], 'token_count': 0}, {}),
    )
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_MERGE_TAGS, 'value': {'legacy': 'modern'}}]},
    )
    monkeypatch.setattr(
        automation_api,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': list(actions),
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
        raising=False,
    )
    monkeypatch.setattr(
        automation_service,
        '_build_exec_plan_from_actions',
        lambda actions, slash_as_separator=False: {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'set_favorite': None,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'fetch_forum_tags': None,
            'desired_filename_template': None,
        },
    )

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['processed_ids'].append(card_id_arg)
        fake_cache.id_map[existing_id]['tags'] = ['modern']
        return {
            'moved_to': None,
            'tags_added': [],
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': None,
            'final_id': card_id_arg,
        }

    monkeypatch.setattr(automation_api.executor, 'apply_plan', _fake_apply_plan)
    monkeypatch.setattr(
        automation_api,
        'apply_merge_actions_to_tags',
        lambda current_tags, merge_actions, slash_as_separator=False: {
            'changed': True,
            'tags': ['modern'],
        },
        raising=False,
    )
    monkeypatch.setattr(
        automation_api,
        'modify_card_attributes_internal',
        lambda card_id_arg, add_tags=None, remove_tags=None: {'ok': True},
        raising=False,
    )

    client = _make_automation_app().test_client()
    response = client.post(
        '/api/automation/execute',
        json={'category': 'folder', 'recursive': True, 'ruleset_id': 'ruleset-1'},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 2,
        'processed': 1,
        'skipped': 1,
        'summary': {
            'moves': 0,
            'tag_changes': 1,
        },
        'details': {
            'skipped': [
                {'card_id': missing_id, 'reason': 'card_not_in_cache'},
            ]
        },
    }
    assert captured['processed_ids'] == [existing_id]


def _setup_manual_execute_ordering_test_mocks(monkeypatch, fake_cache, captured):
    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})

    def _fake_build_rule_context(card_id_arg, card_obj_arg, ruleset_arg, ui_data=None, tags=None):
        return (
            {
                'id': card_id_arg,
                'category': card_obj_arg.get('category', ''),
                'tags': list(card_obj_arg.get('tags') or []),
                'token_count': 0,
            },
            ui_data or {},
        )

    monkeypatch.setattr(automation_service, '_build_rule_context', _fake_build_rule_context)
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_ADD_TAG, 'value': 'ordered'}]},
    )
    monkeypatch.setattr(
        automation_api,
        'normalize_actions_for_context',
        lambda actions, trigger_context, card_snapshot=None: {
            'trigger_context': trigger_context,
            'actions': list(actions),
            'derived': {'add_tags': {'ordered'}, 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        },
        raising=False,
    )
    monkeypatch.setattr(
        automation_service,
        '_build_exec_plan_from_actions',
        lambda actions, slash_as_separator=False: {
            'move': None,
            'add_tags': {'ordered'},
            'remove_tags': set(),
            'set_favorite': None,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'fetch_forum_tags': None,
            'desired_filename_template': None,
        },
    )

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['processed_ids'].append(card_id_arg)
        return {
            'moved_to': None,
            'tags_added': list(plan.get('add_tags', [])),
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': None,
            'final_id': card_id_arg,
        }

    monkeypatch.setattr(automation_api.executor, 'apply_plan', _fake_apply_plan)


def test_manual_execute_preserves_explicit_order_then_appends_db_ids_in_order(monkeypatch):
    request_first = 'folder/request-first.json'
    request_second = 'folder/request-second.json'
    db_only = 'folder/db-only.json'
    fake_cache = SimpleNamespace(
        id_map={
            request_first: {
                'id': request_first,
                'filename': 'request-first.json',
                'char_name': 'Request First',
                'category': 'folder',
                'tags': [],
            },
            request_second: {
                'id': request_second,
                'filename': 'request-second.json',
                'char_name': 'Request Second',
                'category': 'folder',
                'tags': [],
            },
            db_only: {
                'id': db_only,
                'filename': 'db-only.json',
                'char_name': 'DB Only',
                'category': 'folder',
                'tags': [],
            },
        },
        bundle_map={},
        initialized=True,
    )
    captured = {'processed_ids': [], 'queries': []}

    class _FakeCursor:
        def execute(self, sql, params=None):
            captured['queries'].append((sql, params))

        def fetchall(self):
            return [(db_only,), (request_first,), (request_second,)]

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(automation_api, 'get_db', lambda: _FakeConn())
    _setup_manual_execute_ordering_test_mocks(monkeypatch, fake_cache, captured)

    client = _make_automation_app().test_client()
    response = client.post(
        '/api/automation/execute',
        json={
            'card_ids': [request_second, request_first],
            'category': 'folder',
            'recursive': True,
            'ruleset_id': 'ruleset-1',
        },
    )

    assert response.status_code == 200
    assert response.get_json()['selected'] == 3
    assert captured['processed_ids'] == [request_second, request_first, db_only]


def test_manual_execute_category_queries_order_targets_by_id(monkeypatch):
    first_id = 'folder/a.json'
    second_id = 'folder/b.json'
    fake_cache = SimpleNamespace(
        id_map={
            first_id: {
                'id': first_id,
                'filename': 'a.json',
                'char_name': 'A',
                'category': 'folder',
                'tags': [],
            },
            second_id: {
                'id': second_id,
                'filename': 'b.json',
                'char_name': 'B',
                'category': 'folder',
                'tags': [],
            },
        },
        bundle_map={},
        initialized=True,
    )
    captured = {'sql': None, 'processed_ids': []}

    class _FakeCursor:
        def execute(self, sql, params=None):
            captured['sql'] = sql

        def fetchall(self):
            return [(first_id,), (second_id,)]

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(automation_api, 'get_db', lambda: _FakeConn())
    _setup_manual_execute_ordering_test_mocks(monkeypatch, fake_cache, captured)

    client = _make_automation_app().test_client()
    response = client.post(
        '/api/automation/execute',
        json={'category': 'folder', 'recursive': True, 'ruleset_id': 'ruleset-1'},
    )

    assert response.status_code == 200
    assert 'ORDER BY id' in captured['sql']
    assert captured['processed_ids'] == [first_id, second_id]


def test_executor_apply_plan_runs_template_rename_before_move(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    captured = {}

    def _fake_modify_card_attributes_internal(card_id_arg, add_tags, remove_tags, fav):
        captured['modify'] = {
            'card_id': card_id_arg,
            'add_tags': list(add_tags),
            'remove_tags': list(remove_tags),
            'favorite': fav,
        }
        return True

    def _fake_sync_card_names_internal(card_id_arg, **kwargs):
        captured['rename'] = {
            'card_id': card_id_arg,
            'kwargs': dict(kwargs),
        }
        return True, 'folder/renamed.json', 'Success', {
            'filename_updated': True,
            'new_filename': 'renamed.json',
        }

    def _fake_move_card_internal(card_id_arg, target_folder):
        captured['move'] = {
            'card_id': card_id_arg,
            'target_folder': target_folder,
        }
        return True, 'moved/renamed.json', 'Success'

    monkeypatch.setattr(automation_executor, 'modify_card_attributes_internal', _fake_modify_card_attributes_internal)
    monkeypatch.setattr(automation_executor, 'sync_card_names_internal', _fake_sync_card_names_internal)
    monkeypatch.setattr(automation_executor, 'move_card_internal', _fake_move_card_internal)

    result = AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': 'moved',
            'add_tags': {'auto-tag'},
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'rename_file_by_template': '{{char_name}}',
        },
        ui_data={'folder/original.json': {'import_time': 1704153600}},
    )

    assert captured['modify']['card_id'] == 'folder/original.json'
    assert captured['rename'] == {
        'card_id': 'folder/original.json',
        'kwargs': {
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'desired_filename_base': None,
            'desired_filename_template': '{{char_name}}',
            'ui_data': {'folder/original.json': {'import_time': 1704153600}},
        },
    }
    assert captured['move'] == {
        'card_id': 'folder/renamed.json',
        'target_folder': 'moved',
    }
    assert result == {
        'moved_to': 'moved',
        'tags_added': ['auto-tag'],
        'tags_removed': [],
        'fav_changed': False,
        'name_sync': {
            'filename_updated': True,
            'new_filename': 'renamed.json',
            'success': True,
            'msg': 'Success',
            'new_id': 'folder/renamed.json',
        },
        'forum_tags_fetched': None,
        'final_id': 'moved/renamed.json',
    }


def test_executor_apply_plan_propagates_template_rename_noop_without_move(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    captured = {}

    monkeypatch.setattr(automation_executor, 'modify_card_attributes_internal', lambda *args, **kwargs: True)

    def _fake_sync_card_names_internal(card_id_arg, **kwargs):
        captured['rename'] = {'card_id': card_id_arg, 'kwargs': dict(kwargs)}
        return True, card_id_arg, 'No changes', {
            'filename_updated': False,
            'new_filename': None,
            'observability': {
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [{'reason': 'same_stem'}],
            },
        }

    def _fail_move(*args, **kwargs):
        raise AssertionError('move_card_internal should not run when move is not requested')

    monkeypatch.setattr(automation_executor, 'sync_card_names_internal', _fake_sync_card_names_internal)
    monkeypatch.setattr(automation_executor, 'move_card_internal', _fail_move)

    result = AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'rename_file_by_template': '{{char_name}}',
        },
        ui_data={'folder/original.json': {'import_time': 1704153600}},
    )

    assert captured['rename']['card_id'] == 'folder/original.json'
    assert result['name_sync'] == {
        'filename_updated': False,
        'new_filename': None,
        'observability': {
            'suppressed_filename_action_conflicts': [],
            'noop_rename_reasons': [{'reason': 'same_stem'}],
        },
        'success': True,
        'msg': 'No changes',
        'new_id': 'folder/original.json',
    }
    assert result['final_id'] == 'folder/original.json'


def test_executor_apply_plan_propagates_template_rename_failure_and_skips_move(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    monkeypatch.setattr(automation_executor, 'modify_card_attributes_internal', lambda *args, **kwargs: True)
    monkeypatch.setattr(
        automation_executor,
        'sync_card_names_internal',
        lambda card_id_arg, **kwargs: (False, card_id_arg, 'rename failed', {'filename_updated': False, 'new_filename': None}),
    )
    monkeypatch.setattr(
        automation_executor,
        'move_card_internal',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('move_card_internal should not run after rename failure')),
    )

    result = AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': 'moved',
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'rename_file_by_template': '{{char_name}}',
        },
        ui_data={},
    )

    assert result['name_sync'] == {
        'filename_updated': False,
        'new_filename': None,
        'success': False,
        'msg': 'rename failed',
        'new_id': 'folder/original.json',
    }
    assert result['moved_to'] is None
    assert result['final_id'] == 'folder/original.json'


def test_executor_fetch_forum_tags_preserves_processed_tags_and_exposes_governed_tags(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    fake_cache = SimpleNamespace(
        id_map={
            'folder/demo.json': {
                'id': 'folder/demo.json',
                'filename': 'demo.json',
                'tags': ['existing'],
            }
        }
    )

    class _FakeFetcher:
        def fetch_tags(self, url):
            return {
                'success': True,
                'tags': ['raw-allowed', 'raw-blocked'],
                'title': 'Demo Thread',
            }

    class _FakeProcessor:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, tags):
            return ['allowed-tag', 'blocked-tag']

        def merge_tags(self, existing_tags, processed_tags, merge_mode):
            assert processed_tags == ['allowed-tag']
            return list(existing_tags) + list(processed_tags)

    monkeypatch.setattr(automation_executor, 'ctx', SimpleNamespace(cache=fake_cache), raising=False)
    monkeypatch.setattr(automation_executor, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(automation_executor, 'get_tag_fetcher', lambda: _FakeFetcher())
    monkeypatch.setattr(automation_executor, 'TagProcessor', _FakeProcessor)
    monkeypatch.setattr(automation_executor, 'load_config', lambda: {'automation_slash_is_tag_separator': False})

    result = AutomationExecutor()._fetch_forum_tags(
        'folder/demo.json',
        {'merge_mode': 'merge'},
        ui_data={
            'folder/demo.json': {'link': 'https://example.test/thread'},
            '_tag_management_prefs_v1': {
                'lock_tag_library': True,
                'tag_blacklist': ['blocked-tag'],
            },
            '_tag_taxonomy_v1': {
                'default_category': 'General',
                'categories': {'General': {'color': '#123456', 'opacity': 30}},
                'tag_to_category': {
                    'allowed-tag': 'General',
                    'existing': 'General',
                },
            },
        },
    )

    assert result['success'] is True
    assert result['processed_tags'] == ['allowed-tag', 'blocked-tag']
    assert result['governed_tags'] == ['allowed-tag']
    assert result['skipped_blacklist'] == ['blocked-tag']
    assert result['skipped_unknown'] == []
    assert result['tags'] == ['existing', 'allowed-tag']


def test_executor_merges_forum_tag_and_source_baseline_requests(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(id_map={card_id: {'id': card_id, 'tags': []}})
    source_fetches = []
    baseline_calls = []
    tag_calls = []
    source_result = {
        'success': True,
        'supported': True,
        'status': 'ok',
        'source': {
            'title': '来源标题',
            'guild_id': '1',
            'channel_id': '2',
            'thread_id': '3',
            'parent_id': '2',
            'applied_tag_ids': ['tag-id'],
            'first_message_available': True,
            'first_message_revision_at_epoch': 123.0,
        },
    }

    class _FakeFetcher:
        def fetch_tags(self, url, prefetched_source=None):
            tag_calls.append((url, prefetched_source))
            return {'success': True, 'tags': [], 'title': '来源标题'}

    class _FakeProcessor:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, tags):
            return list(tags)

        def merge_tags(self, existing_tags, new_tags, mode='merge'):
            return list(existing_tags) + [tag for tag in new_tags if tag not in existing_tags]

    monkeypatch.setattr(automation_executor, 'ctx', SimpleNamespace(cache=fake_cache), raising=False)
    monkeypatch.setattr(
        automation_executor,
        'fetch_discord_source',
        lambda url: source_fetches.append(url) or source_result,
    )
    monkeypatch.setattr(
        automation_executor,
        'refresh_card_source_baseline',
        lambda card_id_arg, **kwargs: baseline_calls.append(kwargs) or {
            'success': True,
            'status': 'baseline_refreshed',
        },
    )
    monkeypatch.setattr(automation_executor, 'resolve_ui_key', lambda card_id_arg: card_id_arg)
    monkeypatch.setattr(automation_executor, 'get_tag_fetcher', lambda: _FakeFetcher())
    monkeypatch.setattr(automation_executor, 'TagProcessor', _FakeProcessor)
    monkeypatch.setattr(automation_executor, 'load_config', lambda: {'automation_slash_is_tag_separator': False})

    result = AutomationExecutor().apply_plan(
        card_id,
        {
            'fetch_forum_tags': {'merge_mode': 'merge'},
            'refresh_source_baseline': {},
        },
        ui_data={card_id: {'link': 'https://discord.com/channels/1/2/threads/3'}},
    )

    assert source_fetches == ['https://discord.com/channels/1/2/threads/3']
    assert len(baseline_calls) == 1
    assert baseline_calls[0]['fetched'] is source_result
    assert tag_calls == [
        (
            'https://discord.com/channels/1/2/threads/3',
            source_result['source'],
        )
    ]
    assert result['source_baseline_refreshed']['status'] == 'baseline_refreshed'
    assert result['forum_tags_fetched']['success'] is True


def test_auto_run_link_update_runs_source_baseline_without_forum_tag_action(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={card_id: {'id': card_id, 'tags': ['existing']}},
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
    monkeypatch.setattr(automation_service.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, '_build_rule_context', lambda *args, **kwargs: ({'id': card_id}, {}))
    monkeypatch.setattr(
        automation_service.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_REFRESH_SOURCE_BASELINE}]},
    )
    monkeypatch.setattr(
        automation_service.executor,
        'apply_plan',
        lambda card_id_arg, plan, ui_data: captured.update(plan=plan) or {
            'final_id': card_id_arg,
            'forum_tags_fetched': None,
            'source_baseline_refreshed': {'success': True, 'status': 'baseline_refreshed'},
        },
    )

    result = automation_service.auto_run_forum_tags_on_link_update(card_id)

    assert result['run'] is True
    assert captured['plan']['fetch_forum_tags'] is None
    assert captured['plan']['refresh_source_baseline'] == {}
    assert result['result']['final_tags'] == ['existing']


def test_executor_fetch_forum_tags_replace_mode_removes_stale_tags(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    writes = []
    fake_cache = SimpleNamespace(
        id_map={
            'folder/demo.json': {
                'id': 'folder/demo.json',
                'filename': 'demo.json',
                'tags': ['existing'],
            }
        }
    )

    monkeypatch.setattr(automation_executor, 'ctx', SimpleNamespace(cache=fake_cache), raising=False)
    monkeypatch.setattr(
        AutomationExecutor,
        '_fetch_forum_tags',
        lambda self, card_id, config, ui_data=None: {
            'success': True,
            'tags': ['allowed-tag'],
            'governed_tags': ['allowed-tag'],
            'merge_mode': 'replace',
        },
    )
    monkeypatch.setattr(
        automation_executor,
        'modify_card_attributes_internal',
        lambda card_id, add_tags, remove_tags, fav=None: writes.append((list(add_tags), list(remove_tags))) or True,
    )

    result = AutomationExecutor().apply_plan(
        'folder/demo.json',
        {
            'fetch_forum_tags': {'merge_mode': 'replace'},
            'move': None,
            'favorite': None,
        },
        ui_data={},
    )

    assert writes == [(['allowed-tag'], ['existing'])]
    assert result['tags_added'] == ['allowed-tag']
    assert result['tags_removed'] == ['existing']


def test_executor_fetch_forum_tags_replace_mode_clears_existing_tags_when_fetch_returns_empty(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    writes = []
    fake_cache = SimpleNamespace(
        id_map={
            'folder/demo.json': {
                'id': 'folder/demo.json',
                'filename': 'demo.json',
                'tags': ['existing'],
            }
        }
    )

    monkeypatch.setattr(automation_executor, 'ctx', SimpleNamespace(cache=fake_cache), raising=False)
    monkeypatch.setattr(
        AutomationExecutor,
        '_fetch_forum_tags',
        lambda self, card_id, config, ui_data=None: {
            'success': True,
            'tags': [],
            'governed_tags': [],
            'merge_mode': 'replace',
        },
    )
    monkeypatch.setattr(
        automation_executor,
        'modify_card_attributes_internal',
        lambda card_id, add_tags, remove_tags, fav=None: writes.append((list(add_tags), list(remove_tags))) or True,
    )

    result = AutomationExecutor().apply_plan(
        'folder/demo.json',
        {
            'fetch_forum_tags': {'merge_mode': 'replace'},
            'move': None,
            'favorite': None,
        },
        ui_data={},
    )

    assert writes == [([], ['existing'])]
    assert result['tags_added'] == []
    assert result['tags_removed'] == ['existing']


def test_sync_card_names_internal_template_rename_reuses_existing_migration_logic(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    source_path = card_dir / 'demo.json'
    sidecar_path = card_dir / 'demo.png'
    source_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    sidecar_path.write_bytes(b'png-sidecar')

    old_id = 'folder/demo.json'
    new_id = 'folder/Hero Card.json'
    saved_ui_snapshots = []
    cache_calls = {}

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.committed = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.committed += 1

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                old_id: {
                    'id': old_id,
                    'filename': 'demo.json',
                    'category': 'folder',
                    'char_name': 'Legacy Name',
                    'last_modified': 1704067200,
                }
            }
            self.bundle_map = {}

        def move_card_update(self, old_id_arg, new_id_arg, old_category, new_category, filename, full_path):
            cache_calls['move_card_update'] = {
                'old_id': old_id_arg,
                'new_id': new_id_arg,
                'old_category': old_category,
                'new_category': new_category,
                'filename': filename,
                'full_path': full_path,
            }
            card = dict(self.id_map.pop(old_id_arg))
            card.update({'id': new_id_arg, 'category': new_category, 'filename': filename})
            self.id_map[new_id_arg] = card

        def update_card_data(self, card_id_arg, payload):
            cache_calls['update_card_data'] = {
                'card_id': card_id_arg,
                'payload': dict(payload),
            }
            self.id_map.setdefault(card_id_arg, {}).update(payload)

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()
    ui_data = {
        old_id: {'import_time': 1704153600, 'summary': 'ui summary'},
        'folder': {
            card_service.VERSION_REMARKS_KEY: {
                old_id: 'version note',
            }
        },
    }

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'extract_card_info', lambda path: {'name': 'Hero Card', 'data': {'name': 'Hero Card'}})
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda path, info: True)
    monkeypatch.setattr(card_service, 'update_card_cache', lambda card_id_arg, full_path_arg, parsed_info=None, mtime=None, remove_entity_ids=None: (
        cache_calls.setdefault('update_card_cache', {
            'card_id': card_id_arg,
            'full_path': full_path_arg,
            'parsed_info': parsed_info,
            'mtime': mtime,
            'remove_entity_ids': remove_entity_ids,
        }),
        {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        }
    )[1])
    sync_calls = []
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: ui_data)
    monkeypatch.setattr(card_service, 'save_ui_data', lambda payload: saved_ui_snapshots.append({key: (value.copy() if isinstance(value, dict) else value) for key, value in payload.items()}))
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)

    ok, final_id, msg, details = card_service.sync_card_names_internal(
        old_id,
        desired_filename_template='{{char_name}}',
    )

    assert ok is True
    assert msg == 'Success'
    assert final_id == new_id
    assert details['filename_updated'] is True
    assert details['new_filename'] == 'Hero Card.json'
    assert source_path.exists() is False
    assert sidecar_path.exists() is False
    assert (card_dir / 'Hero Card.json').exists() is True
    assert (card_dir / 'Hero Card.png').exists() is True
    assert fake_conn.executed == [
        ('DELETE FROM card_metadata WHERE id = ?', (old_id,)),
    ]
    assert fake_conn.committed == 1
    assert ui_data[new_id]['import_time'] == 1704153600
    assert ui_data[new_id]['summary'] == 'ui summary'
    assert old_id not in ui_data
    assert ui_data['folder'][card_service.VERSION_REMARKS_KEY] == {new_id: 'version note'}
    assert cache_calls['update_card_cache']['card_id'] == new_id
    assert cache_calls['update_card_cache']['full_path'].endswith('Hero Card.json')
    assert cache_calls['update_card_cache']['remove_entity_ids'] == [old_id]
    assert cache_calls['move_card_update'] == {
        'old_id': old_id,
        'new_id': new_id,
        'old_category': 'folder',
        'new_category': 'folder',
        'filename': 'Hero Card.json',
        'full_path': str(card_dir / 'Hero Card.json'),
    }
    assert cache_calls['update_card_data']['card_id'] == new_id
    assert cache_calls['update_card_data']['payload']['filename'] == 'Hero Card.json'
    assert cache_calls['update_card_data']['payload']['char_name'] == 'Hero Card'
    assert sync_calls == [
        {
            'card_id': new_id,
            'source_path': str(card_dir / 'Hero Card.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': [old_id],
            'remove_owner_ids': [old_id],
        }
    ]
    assert saved_ui_snapshots[-1][new_id]['import_time'] == 1704153600


def test_sync_card_names_internal_template_rename_keeps_priority_over_legacy_filename_actions(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    source_path = card_dir / 'demo.json'
    source_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {
            'name': 'Legacy Character Name',
            'data': {
                'name': 'Legacy Character Name',
                'character_book': {'name': 'Legacy Wi Name', 'entries': []},
            },
        },
    )
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda path, info: True)
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *args, **kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(card_service, 'get_db', lambda: type('Conn', (), {'execute': lambda self, *a, **k: self, 'commit': lambda self: None})())
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(card_service, 'save_ui_data', lambda payload: None)
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(
            id_map={
                'folder/demo.json': {
                    'id': 'folder/demo.json',
                    'filename': 'demo.json',
                    'category': 'folder',
                    'char_name': 'Legacy Character Name',
                }
            },
            bundle_map={},
            move_card_update=lambda *args, **kwargs: None,
            update_card_data=lambda *args, **kwargs: None,
        ),
        raising=False,
    )
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)

    ok, final_id, msg, details = card_service.sync_card_names_internal(
        'folder/demo.json',
        set_filename_from_char_name=True,
        set_filename_from_wi_name=True,
        desired_filename_template='Template Winner',
    )

    assert ok is True
    assert msg == 'Success'
    assert final_id == 'folder/Template Winner.json'
    assert details['filename_updated'] is True
    assert details['new_filename'] == 'Template Winner.json'
    assert source_path.exists() is False
    assert (card_dir / 'Template Winner.json').exists() is True


def test_manual_execute_runs_template_rename_through_executor_plan(monkeypatch):
    card_id = 'folder/demo.json'
    fake_cache = SimpleNamespace(
        id_map={
            card_id: {
                'id': card_id,
                'filename': 'demo.json',
                'char_name': 'Demo',
                'category': 'folder',
                'tags': [],
            }
        },
        bundle_map={},
        initialized=True,
    )
    captured = {}

    monkeypatch.setattr(automation_api.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_api, 'load_config', lambda: {'automation_slash_is_tag_separator': False})
    monkeypatch.setattr(automation_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_api.rule_manager, 'get_ruleset', lambda ruleset_id: {'rules': []})
    monkeypatch.setattr(
        automation_service,
        '_build_rule_context',
        lambda *args, **kwargs: ({'id': card_id, 'category': 'folder', 'tags': [], 'token_count': 0}, {}),
    )
    monkeypatch.setattr(
        automation_api.engine,
        'evaluate',
        lambda *args, **kwargs: {'actions': [{'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'}]},
    )

    def _fake_normalize(actions, trigger_context, card_snapshot=None):
        captured['normalize_actions'] = list(actions)
        return {
            'trigger_context': trigger_context,
            'actions': [{'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'}],
            'derived': {'add_tags': set(), 'remove_tags': set()},
            'observability': {
                'category_tag_expansions': [],
                'suppressed_filename_action_conflicts': [],
                'noop_rename_reasons': [],
            },
        }

    def _fake_build_exec_plan_from_actions(actions, slash_as_separator=False):
        captured['exec_plan_actions'] = list(actions)
        return {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'rename_file_by_template': '{{char_name}}',
        }

    def _fake_apply_plan(card_id_arg, plan, ui_data):
        captured['applied_plan'] = dict(plan)
        return {
            'moved_to': None,
            'tags_added': [],
            'tags_removed': [],
            'fav_changed': False,
            'name_sync': None,
            'forum_tags_fetched': None,
            'final_id': card_id_arg,
        }

    monkeypatch.setattr(automation_api, 'normalize_actions_for_context', _fake_normalize, raising=False)
    monkeypatch.setattr(automation_service, '_build_exec_plan_from_actions', _fake_build_exec_plan_from_actions)
    monkeypatch.setattr(automation_api.executor, 'apply_plan', _fake_apply_plan)

    client = _make_automation_app().test_client()
    response = client.post('/api/automation/execute', json={'card_ids': [card_id], 'ruleset_id': 'ruleset-1'})

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'selected': 1,
        'processed': 1,
        'skipped': 0,
        'summary': {
            'moves': 0,
            'tag_changes': 0,
        },
        'details': {
            'skipped': [],
        },
    }
    assert captured['normalize_actions'] == [{'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'}]
    assert captured['exec_plan_actions'] == [{'type': ACT_RENAME_FILE_BY_TEMPLATE, 'value': '{{char_name}}'}]
    assert captured['applied_plan'] == {
        'move': None,
        'add_tags': set(),
        'remove_tags': set(),
        'favorite': None,
        'fetch_forum_tags': None,
        'set_char_name_from_filename': False,
        'set_wi_name_from_filename': False,
        'set_filename_from_char_name': False,
        'set_filename_from_wi_name': False,
        'rename_file_by_template': '{{char_name}}',
    }


def test_executor_apply_plan_passes_structured_template_rename_config_to_sync_helper(monkeypatch):
    from core.automation.executor import AutomationExecutor
    from core.automation import executor as automation_executor

    captured = {}

    monkeypatch.setattr(automation_executor, 'modify_card_attributes_internal', lambda *args, **kwargs: True)

    def _fake_sync_card_names_internal(card_id_arg, **kwargs):
        captured['rename_kwargs'] = dict(kwargs)
        return True, 'folder/renamed.json', 'Success', {
            'filename_updated': True,
            'new_filename': 'renamed.json',
        }

    monkeypatch.setattr(automation_executor, 'sync_card_names_internal', _fake_sync_card_names_internal)
    monkeypatch.setattr(automation_executor, 'move_card_internal', lambda *args, **kwargs: (True, 'folder/renamed.json', 'Success'))

    AutomationExecutor().apply_plan(
        'folder/original.json',
        {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None,
            'set_char_name_from_filename': False,
            'set_wi_name_from_filename': False,
            'set_filename_from_char_name': False,
            'set_filename_from_wi_name': False,
            'rename_file_by_template': {
                'template': '{{char_name}} - {{import_date|date:%Y-%m-%d}}',
                'fallback_template': '{{char_name}}',
                'max_length': 120,
            },
        },
        ui_data={'folder/original.json': {'import_time': 1704153600}},
    )

    assert captured['rename_kwargs']['desired_filename_template'] == {
        'template': '{{char_name}} - {{import_date|date:%Y-%m-%d}}',
        'fallback_template': '{{char_name}}',
        'max_length': 120,
    }


def test_sync_card_names_internal_accepts_structured_template_rename_config(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    source_path = card_dir / 'demo.json'
    source_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'extract_card_info', lambda path: {'name': 'Hero Card', 'data': {'name': 'Hero Card'}})
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda path, info: True)
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *args, **kwargs: {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    })
    monkeypatch.setattr(card_service, 'get_db', lambda: type('Conn', (), {'execute': lambda self, *a, **k: self, 'commit': lambda self: None})())
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: {'folder/demo.json': {'import_time': 1704153600}})
    monkeypatch.setattr(card_service, 'save_ui_data', lambda payload: None)
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(
            id_map={
                'folder/demo.json': {
                    'id': 'folder/demo.json',
                    'filename': 'demo.json',
                    'category': 'folder',
                    'char_name': 'Hero Card',
                    'last_modified': 1704153600,
                }
            },
            bundle_map={},
            move_card_update=lambda *args, **kwargs: None,
            update_card_data=lambda *args, **kwargs: None,
        ),
        raising=False,
    )
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)

    ok, final_id, msg, details = card_service.sync_card_names_internal(
        'folder/demo.json',
        desired_filename_template={
            'template': '{{char_name}} - {{import_date|date:%Y-%m-%d}}',
            'fallback_template': '{{char_name}}',
            'max_length': 120,
        },
    )

    assert ok is True
    assert msg == 'Success'
    assert final_id == 'folder/Hero Card - 2024-01-02.json'
    assert details['filename_updated'] is True
    assert details['new_filename'] == 'Hero Card - 2024-01-02.json'
    assert source_path.exists() is False
    assert (card_dir / 'Hero Card - 2024-01-02.json').exists() is True


def test_modify_card_attributes_internal_suppresses_fs_events_before_delayed_tag_write(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    card_path = card_dir / 'demo.json'
    card_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    calls = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.committed = 0

        def execute(self, sql, params):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.committed += 1

    class _FakeCache:
        def __init__(self):
            self.updated = []

        def update_tags_update(self, card_id_arg, new_tags):
            self.updated.append((card_id_arg, list(new_tags)))

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'extract_card_info',
        lambda path: {'data': {'tags': ['existing']}},
    )
    monkeypatch.setattr(
        card_service,
        'suppress_fs_events',
        lambda *args, **kwargs: calls.append(('suppress_fs_events', args, kwargs)),
    )
    monkeypatch.setattr(
        card_service,
        'write_card_metadata',
        lambda path, info: calls.append(('write_card_metadata', path, info)) or True,
    )
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(card_service, 'enqueue_index_job', lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    ok = card_service.modify_card_attributes_internal(
        'folder/demo.json',
        add_tags={'new-tag'},
    )

    assert ok is True
    assert [entry[0] for entry in calls] == ['suppress_fs_events', 'write_card_metadata']
    assert calls[1][1] == str(card_path)
    assert calls[1][2]['data']['tags'] == ['existing', 'new-tag']
    assert fake_conn.executed == [
        ('UPDATE card_metadata SET tags = ? WHERE id = ?', ('["existing", "new-tag"]', 'folder/demo.json')),
    ]
    assert fake_conn.committed == 1
    assert fake_cache.updated == [('folder/demo.json', ['existing', 'new-tag'])]


def test_global_metadata_cache_update_card_data_rebuilds_global_tags_when_tags_shrink():
    from core.data.cache import GlobalMetadataCache

    cache = GlobalMetadataCache()
    cache.id_map = {
        'folder/demo.json': {
            'id': 'folder/demo.json',
            'category': 'folder',
            'tags': ['legacy', 'keep'],
            'last_modified': 1704067200,
        }
    }
    cache.global_tags = {'legacy', 'keep'}

    updated = cache.update_card_data('folder/demo.json', {'tags': ['keep']})

    assert updated['tags'] == ['keep']
    assert cache.global_tags == ['keep']


def test_global_metadata_cache_update_tags_update_rebuilds_global_tags_when_tags_shrink():
    from core.data.cache import GlobalMetadataCache

    cache = GlobalMetadataCache()
    cache.id_map = {
        'folder/demo.json': {
            'id': 'folder/demo.json',
            'tags': ['legacy', 'keep'],
        }
    }
    cache.global_tags = {'legacy', 'keep'}

    cache.update_tags_update('folder/demo.json', ['keep'])

    assert cache.id_map['folder/demo.json']['tags'] == ['keep']
    assert cache.global_tags == ['keep']


def test_modify_card_attributes_internal_enqueues_incremental_index_repair_after_delayed_tag_write(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    card_path = card_dir / 'demo.json'
    card_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    class _FakeConn:
        def execute(self, _sql, _params):
            return self

        def commit(self):
            return None

    job_calls = []

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'extract_card_info', lambda _path: {'data': {'tags': ['existing']}})
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda _path, _info: True)
    monkeypatch.setattr(card_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(card_service, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(update_tags_update=lambda *args, **kwargs: None),
        raising=False,
    )

    ok = card_service.modify_card_attributes_internal('folder/demo.json', add_tags={'new-tag'})

    assert ok is True
    assert job_calls == [
        ('upsert_card', {'entity_id': 'folder/demo.json', 'source_path': str(card_path)}),
    ]


def test_modify_card_attributes_internal_skips_db_cache_and_index_when_delayed_tag_write_fails(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    card_dir = cards_root / 'folder'
    card_dir.mkdir(parents=True, exist_ok=True)
    card_path = card_dir / 'demo.json'
    card_path.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.committed = 0

        def execute(self, sql, params):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.committed += 1

    fake_conn = _FakeConn()
    fake_cache = SimpleNamespace(updated=[])
    fake_cache.update_tags_update = lambda card_id, tags: fake_cache.updated.append((card_id, tags))
    job_calls = []

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'extract_card_info', lambda _path: {'data': {'tags': ['existing']}})
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *args, **kwargs: None)
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda _path, _info: False)
    monkeypatch.setattr(card_service, 'get_db', lambda: fake_conn)
    monkeypatch.setattr(card_service, 'enqueue_index_job', lambda job_type, **kwargs: job_calls.append((job_type, kwargs)), raising=False)
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    ok = card_service.modify_card_attributes_internal('folder/demo.json', add_tags={'new-tag'})

    assert ok is False
    assert fake_conn.executed == []
    assert fake_conn.committed == 0
    assert fake_cache.updated == []
    assert job_calls == []


def test_rule_manager_save_ruleset_preserves_group_condition_and_action_order(monkeypatch, tmp_path):
    rules_dir = tmp_path / 'automation'
    rules_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(automation_manager, 'RULES_DIR', str(rules_dir))

    manager = RuleManager()
    saved_id = manager.save_ruleset(
        None,
        {
            'meta': {'name': 'Ordered Rules'},
            'rules': [
                {
                    'name': 'ordered',
                    'enabled': True,
                    'logic': 'OR',
                    'groups': [
                        {
                            'id': 'group-b',
                            'logic': 'AND',
                            'conditions': [
                                {'field': 'filename', 'operator': 'contains', 'value': 'B'},
                                {'field': 'filename', 'operator': 'contains', 'value': 'A'},
                            ],
                        },
                        {
                            'id': 'group-a',
                            'logic': 'OR',
                            'conditions': [
                                {'field': 'tags', 'operator': 'contains', 'value': 'tag-2'},
                                {'field': 'tags', 'operator': 'contains', 'value': 'tag-1'},
                            ],
                        },
                    ],
                    'actions': [
                        {'type': 'remove_tag', 'value': 'late'},
                        {'type': 'add_tag', 'value': 'early'},
                        {'type': 'move_folder', 'value': 'Sorted/Folder'},
                    ],
                }
            ],
        },
    )

    saved = manager.get_ruleset(saved_id)
    groups = saved['rules'][0]['groups']
    actions = saved['rules'][0]['actions']

    assert [group['id'] for group in groups] == ['group-b', 'group-a']
    assert [cond['value'] for cond in groups[0]['conditions']] == ['B', 'A']
    assert [cond['value'] for cond in groups[1]['conditions']] == ['tag-2', 'tag-1']
    assert [action['type'] for action in actions] == ['remove_tag', 'add_tag', 'move_folder']
    assert [action['value'] for action in actions] == ['late', 'early', 'Sorted/Folder']
