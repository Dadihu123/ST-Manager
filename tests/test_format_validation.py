import json


def _v1_card():
    return {
        'name': 'Hero',
        'description': 'A character',
        'personality': 'Calm',
        'scenario': 'A test',
        'first_mes': 'Hello',
        'mes_example': '<START>\n{{user}}: Hi',
    }


def _v2_card():
    return {
        'spec': 'chara_card_v2',
        'spec_version': '2.0',
        'data': {
            'name': 'Hero',
            'description': 'A character',
            'personality': 'Calm',
            'scenario': 'A test',
            'first_mes': 'Hello',
            'mes_example': '<START>\n{{user}}: Hi',
            'creator_notes': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'alternate_greetings': [],
            'tags': [],
            'creator': '',
            'character_version': '',
            'extensions': {},
        },
    }


def test_character_card_validator_matches_v1_v2_v3_and_rejects_worldbook():
    from core.utils.format_validation import is_valid_character_card_data

    v2 = _v2_card()
    v3 = {'spec': 'chara_card_v3', 'spec_version': '3.0', 'data': {'name': 'Hero'}}

    assert is_valid_character_card_data(_v1_card())
    assert is_valid_character_card_data(v2)
    assert is_valid_character_card_data(v3)
    assert not is_valid_character_card_data({'entries': {}})
    assert not is_valid_character_card_data({**v2, 'data': {**v2['data'], 'tags': {}}})
    assert not is_valid_character_card_data({**v2, 'data': {**v2['data'], 'character_book': {}}})


def test_character_card_validator_rejects_cross_type_payloads():
    """校验器仍需拒绝非卡片数据（放宽字段要求后不能变成「什么都通过」）。"""
    from core.utils.format_validation import is_valid_character_card_data

    assert not is_valid_character_card_data({'entries': {}})
    assert not is_valid_character_card_data({'temperature': 0.8, 'top_p': 0.9})
    assert not is_valid_character_card_data({'user_name': 'u', 'name': 'c', 'chat_metadata': {}})
    assert not is_valid_character_card_data({'name': 'only a name'})


def test_character_card_validator_accepts_v2_without_extension_fields():
    """合法但缺少扩展字段的 v2 卡片必须被接受。

    历史回归：校验器曾要求 data 下 14 个字段全部存在，导致大量第三方工具
    导出的合法卡片被判定为「非卡片」，进而在全量扫描中被当作待删除记录。
    """
    from core.utils.format_validation import get_character_card_version

    # 缺少 creator_notes / system_prompt / post_history_instructions
    partial = {
        'spec': 'chara_card_v2',
        'spec_version': '2.0',
        'data': {
            'name': 'Hero',
            'description': 'A character',
            'personality': 'Calm',
            'scenario': 'A test',
            'first_mes': 'Hello',
            'mes_example': '<START>',
            'tags': [],
            'alternate_greetings': [],
            'extensions': {},
        },
    }
    assert get_character_card_version(partial) == 2

    # 只有核心字段 + extensions 的旧式 v2
    legacy = {
        'spec': 'chara_card_v2',
        'spec_version': '2.0',
        'data': {
            'name': 'Hero',
            'description': 'A character',
            'personality': 'Calm',
            'scenario': 'A test',
            'first_mes': 'Hello',
            'mes_example': '<START>',
            'extensions': {},
        },
    }
    assert get_character_card_version(legacy) == 2


def test_character_card_validator_still_checks_present_extension_types():
    """扩展字段缺失可以接受，但存在时类型必须正确。"""
    from core.utils.format_validation import is_valid_character_card_data

    base = {
        'spec': 'chara_card_v2',
        'spec_version': '2.0',
        'data': {'name': 'Hero', 'first_mes': 'Hi'},
    }
    assert is_valid_character_card_data(base)
    assert not is_valid_character_card_data({**base, 'data': {**base['data'], 'tags': {}}})
    assert not is_valid_character_card_data(
        {**base, 'data': {**base['data'], 'alternate_greetings': 'nope'}}
    )


def test_extract_card_info_status_distinguishes_unreadable_from_not_a_card(tmp_path):
    """读取失败不能等同于「不是卡片」，否则会误删既有索引记录。"""
    from core.utils.image import (
        CARD_INFO_NOT_A_CARD,
        CARD_INFO_UNREADABLE,
        extract_card_info_with_status,
    )

    worldbook_path = tmp_path / 'worldbook.json'
    worldbook_path.write_text(json.dumps({'name': 'Book', 'entries': {}}), encoding='utf-8')

    info, status = extract_card_info_with_status(str(worldbook_path))
    assert info is None
    assert status == CARD_INFO_NOT_A_CARD

    corrupt_path = tmp_path / 'corrupt.png'
    corrupt_path.write_bytes(b'this is not a png')
    info, status = extract_card_info_with_status(str(corrupt_path))
    assert info is None
    assert status == CARD_INFO_UNREADABLE

    missing_path = tmp_path / 'missing.png'
    info, status = extract_card_info_with_status(str(missing_path))
    assert info is None
    assert status == CARD_INFO_UNREADABLE


def test_extract_card_info_rejects_worldbook_json_in_card_directory(tmp_path):
    from core.utils.image import extract_card_info

    worldbook_path = tmp_path / 'worldbook.json'
    worldbook_path.write_text(json.dumps({'name': 'Book', 'entries': {}}), encoding='utf-8')

    assert extract_card_info(str(worldbook_path)) is None


def test_worldinfo_validator_requires_st_entries_shape():
    from core.utils.format_validation import (
        is_valid_legacy_world_info_data,
        is_valid_world_info_data,
    )

    assert is_valid_world_info_data({'entries': {}})
    assert is_valid_world_info_data({'name': 'Book', 'entries': []})
    assert is_valid_world_info_data({'entries': None})
    assert not is_valid_world_info_data({})
    assert not is_valid_world_info_data([{'keys': ['hero'], 'content': 'entry'}])
    assert is_valid_legacy_world_info_data([{'keys': ['hero'], 'content': 'entry'}])
    assert not is_valid_world_info_data([{'name': 'not an entry'}])


def test_extension_validators_match_st_and_js_slash_runner_shapes():
    from core.utils.format_validation import (
        is_valid_quick_reply_data,
        is_valid_regex_data,
        is_valid_st_script_data,
    )

    assert is_valid_regex_data({'findRegex': '/hero/i'})
    assert is_valid_regex_data([{'scriptName': 'Hero', 'findRegex': '/hero/i'}])
    assert not is_valid_regex_data({'scriptName': ''})

    assert is_valid_st_script_data({'type': 'script'})
    assert is_valid_st_script_data({'type': 'folder'})
    assert is_valid_st_script_data({'type': 'folder', 'scripts': [{'type': 'script'}]})
    assert is_valid_st_script_data({'type': 'folder', 'value': [{'buttons': []}]})
    assert not is_valid_st_script_data(['scripts', {'type': 'script'}])
    assert not is_valid_st_script_data({'type': 'folder', 'scripts': {}})

    assert is_valid_quick_reply_data({'version': 1, 'name': 'Quick', 'qrList': []})
    assert not is_valid_quick_reply_data({'version': '1', 'name': 'Quick', 'qrList': []})
    assert not is_valid_quick_reply_data({'version': 1, 'qrList': []})


def test_preset_and_chat_validators_reject_cross_type_payloads():
    from core.utils.format_validation import (
        is_valid_chat_jsonl_bytes,
        is_valid_preset_data,
    )

    assert is_valid_preset_data({'temperature': 0.7})
    assert is_valid_preset_data({'prompts': []})
    assert not is_valid_preset_data({'entries': {}})

    assert is_valid_chat_jsonl_bytes(b'{"name":"Hero"}\n{"mes":"hello"}\n')
    assert not is_valid_chat_jsonl_bytes(b'\n{"name":"Hero"}\n')
    assert not is_valid_chat_jsonl_bytes(b'{}\n')
