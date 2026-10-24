"""规则集「Token 数（含未启用条目）」条件与共享 token 聚合的回归测试。"""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.automation.constants import FIELD_MAP
from core.automation.engine import AutomationEngine
from core.services import automation_service
from core.utils.text import (
    calculate_all_worldbook_token_count,
    calculate_token_count,
    iter_worldbook_entries,
)

#: 条件字段里没有 FIELD_MAP 条目的 id：引擎按原字段名从上下文取值，
#: 值由 `_build_rule_context` 或 ui_data 注入。新增字段时必须显式加到这里，
#: 否则前后端字段清单漂移会静默通过。
CONDITION_FIELDS_WITHOUT_FIELD_MAP = {
    'personality',
    'scenario',
    'creator_notes',
    'system_prompt',
    'post_history_instructions',
    'source_link',
}


def _ruleset_with_condition(field, operator='gt', value='0'):
    return {
        'rules': [
            {
                'name': f'rule_{field}',
                'enabled': True,
                'groups': [
                    {
                        'logic': 'AND',
                        'conditions': [
                            {'field': field, 'operator': operator, 'value': value}
                        ],
                    }
                ],
                'actions': [],
            }
        ]
    }


def _card(entries, *, description='abcdefg'):
    return {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'data': {
            'name': 'Hero',
            'description': description,
            'first_mes': '',
            'mes_example': '',
            'character_book': {'entries': entries},
        },
    }


def test_iter_worldbook_entries_accepts_list_and_dict_shapes():
    list_entries = [{'content': 'a'}, {'content': 'b'}]
    dict_entries = {'0': {'content': 'a'}, '1': {'content': 'b'}}

    assert iter_worldbook_entries({'character_book': list_entries}) == list_entries
    assert iter_worldbook_entries({'character_book': {'entries': list_entries}}) == list_entries
    assert iter_worldbook_entries({'character_book': {'entries': dict_entries}}) == list_entries
    # 非字典条目（脏数据）被跳过，不再让整卡估算崩成 0。
    assert iter_worldbook_entries({'character_book': {'entries': [None, 'x', {'content': 'a'}]}}) == [
        {'content': 'a'}
    ]


def test_calculate_token_count_treats_dict_entries_like_list_entries():
    """回归：entries 是字典时旧实现抛异常并把整卡 token 吞成 0。"""

    entries = [
        {'content': 'Lore', 'keys': ['k'], 'enabled': True},
        {'content': 'Hidden lore', 'keys': ['h'], 'enabled': False},
    ]
    list_card = _card(entries)['data']
    dict_card = _card({'0': entries[0], '1': entries[1]})['data']

    quoted = calculate_token_count(list_card)
    assert quoted > 0
    assert calculate_token_count(dict_card) == quoted
    assert calculate_all_worldbook_token_count(dict_card) == calculate_all_worldbook_token_count(list_card)


def test_calculate_token_count_keeps_legacy_enabled_only_semantics():
    """旧口径只看 enabled：只有 disable 的条目仍会计入（既有行为，不在本次改动范围）。"""

    card = _card([{'content': 'Disabled entry', 'keys': [], 'disable': True}])['data']

    assert calculate_token_count(card) > 0


def test_all_worldbook_token_count_includes_disabled_entries():
    card = _card(
        [
            {'content': 'Enabled entry', 'keys': ['k'], 'enabled': True},
            {'content': 'Disabled entry with plenty of extra words', 'keys': ['h'], 'enabled': False},
        ]
    )['data']

    assert calculate_all_worldbook_token_count(card) > calculate_token_count(card)


def test_all_worldbook_token_count_equals_legacy_when_everything_is_enabled():
    card = _card(
        [
            {'content': 'Enabled A', 'keys': ['a'], 'enabled': True},
            {'content': 'Enabled B', 'keys': ['b']},
        ]
    )['data']

    assert calculate_all_worldbook_token_count(card) == calculate_token_count(card)


def test_all_worldbook_token_count_keeps_card_text_fields():
    """新条件不是"纯世界书"：没有世界书时它必须等于旧值，而不是 0。"""

    text_only = {
        'name': 'Hero',
        'description': '这是一段简介，用来验证正文是否被计入。',
        'first_mes': '开场白',
        'mes_example': '',
    }

    legacy = calculate_token_count(text_only)
    assert legacy > 0
    assert calculate_all_worldbook_token_count(text_only) == legacy


def test_all_worldbook_token_count_adds_entries_on_top_of_card_text():
    text_only = {
        'name': 'Hero',
        'description': '这是一段简介，用来验证正文是否被计入。',
        'first_mes': '开场白',
        'mes_example': '',
    }
    disabled_entry = {'content': 'Hidden entry content', 'keys': ['hidden'], 'enabled': False}
    with_entry = dict(text_only)
    with_entry['character_book'] = {'entries': [disabled_entry]}
    entry_only = {'character_book': {'entries': [disabled_entry]}}

    text_tokens = calculate_all_worldbook_token_count(text_only)
    entry_tokens = calculate_all_worldbook_token_count(entry_only)
    combined = calculate_all_worldbook_token_count(with_entry)

    assert combined > text_tokens
    assert combined > entry_tokens
    # 正文与条目都计入：合成值同时高于"只有正文"和"只有条目"。
    assert combined >= text_tokens + entry_tokens - 2


def test_build_rule_context_computes_token_all_wi_from_card_file(tmp_path, monkeypatch):
    cards_root = tmp_path / 'cards'
    card_path = cards_root / 'demo.json'
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card = _card(
        [
            {'content': 'Enabled entry', 'keys': ['k'], 'enabled': True},
            {'content': 'Disabled entry with plenty of extra words', 'keys': ['h'], 'enabled': False},
        ]
    )
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding='utf-8')

    fake_cache = SimpleNamespace(id_map={'demo.json': {'id': 'demo.json'}}, bundle_map={})
    monkeypatch.setattr(automation_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda card_id: card_id)

    context, _ = automation_service._build_rule_context(
        'demo.json',
        fake_cache.id_map['demo.json'],
        _ruleset_with_condition('token_all_wi'),
    )

    expected = calculate_all_worldbook_token_count(card['data'])
    assert expected > 0
    assert context['token_all_wi'] == expected


def test_build_rule_context_defaults_token_all_wi_to_zero_when_card_missing(tmp_path, monkeypatch):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)

    fake_cache = SimpleNamespace(id_map={'demo.json': {'id': 'demo.json'}}, bundle_map={})
    monkeypatch.setattr(automation_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(automation_service.ctx, 'cache', fake_cache, raising=False)
    monkeypatch.setattr(automation_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(automation_service, 'resolve_ui_key', lambda card_id: card_id)

    context, _ = automation_service._build_rule_context(
        'demo.json',
        fake_cache.id_map['demo.json'],
        _ruleset_with_condition('token_all_wi'),
    )

    # 读不到卡文件时给出数值 0，而不是 None（None 会让所有比较都判假）。
    assert context['token_all_wi'] == 0


def test_token_all_wi_is_registered_as_deep_field():
    assert 'token_all_wi' in automation_service.DEEP_AUTOMATION_FIELDS
    assert automation_service._ruleset_uses_fields(
        _ruleset_with_condition('token_all_wi'),
        automation_service.DEEP_AUTOMATION_FIELDS,
    )


def test_engine_matches_token_all_wi_with_numeric_operator():
    engine = AutomationEngine()
    ruleset = {
        'rules': [
            {
                'name': 'big worldbook',
                'enabled': True,
                'groups': [
                    {
                        'logic': 'AND',
                        'conditions': [
                            {'field': 'token_all_wi', 'operator': 'gt', 'value': '100'}
                        ],
                    }
                ],
                'actions': [{'type': 'add_tag', 'value': 'big'}],
            }
        ]
    }

    assert engine.evaluate({'token_all_wi': 101}, ruleset)['actions'] == [
        {'type': 'add_tag', 'value': 'big'}
    ]
    assert engine.evaluate({'token_all_wi': 100}, ruleset)['actions'] == []


def test_condition_option_label_does_not_imply_worldbook_only():
    """标签必须说清"含未启用条目"，否则会被读成"只算世界书"。"""

    template = (ROOT / 'templates' / 'modals' / 'automation.html').read_text(encoding='utf-8')

    assert '<option value="token_all_wi">Token 数（含未启用条目）</option>' in template
    # 条件行里有整行说明，明确"从卡片正文算起"。
    assert '和「Token 数」一样从卡片正文' in template
    # 帮助里的对比卡片也按新名字写。
    assert '<strong>Token 数（含未启用条目）</strong>' in template
    assert '世界书全量 Token' not in template


def test_condition_field_options_stay_in_sync_with_backend_field_map():
    """条件字段清单是硬编码在模板里的，这里守住前后端不漂移。"""

    template = (ROOT / 'templates' / 'modals' / 'automation.html').read_text(encoding='utf-8')
    start = template.index('cond.field')
    block = template[start:template.index('{% endcall %}', start)]
    options = set(re.findall(r'<option value="([A-Za-z0-9_.]+)"', block))

    assert 'token_all_wi' in options
    # 后端必须知道每个可选项怎么取值：要么在 FIELD_MAP，要么在显式白名单里。
    assert set(FIELD_MAP) <= options
    assert options - set(FIELD_MAP) == CONDITION_FIELDS_WITHOUT_FIELD_MAP
