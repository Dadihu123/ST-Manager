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
