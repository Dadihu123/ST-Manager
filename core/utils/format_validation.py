"""Format validators shared by importers, filesystem scans, and indexes."""

import json
import math
from typing import Any


CHARACTER_CARD_V1_FIELDS = (
    'name',
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
)

CHARACTER_CARD_V2_DATA_FIELDS = (
    'name',
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
    'creator_notes',
    'system_prompt',
    'post_history_instructions',
    'alternate_greetings',
    'tags',
    'creator',
    'character_version',
    'extensions',
)

PRESET_FORMAT_KEYS = frozenset(
    {
        'temperature',
        'temp',
        'top_p',
        'top_k',
        'top_a',
        'min_p',
        'typical_p',
        'typical',
        'tfs',
        'temperature_last',
        'dynamic_temperature',
        'dynatemp',
        'dynatemp_low',
        'dynatemp_high',
        'min_temp',
        'max_temp',
        'repetition_penalty',
        'rep_pen',
        'frequency_penalty',
        'freq_pen',
        'presence_penalty',
        'pres_pen',
        'mirostat_mode',
        'mirostat_tau',
        'mirostat_eta',
        'guidance_scale',
        'negative_prompt',
        'json_schema',
        'grammar',
        'grammar_string',
        'banned_tokens',
        'logit_bias',
        'sampler_order',
        'samplers',
        'input_sequence',
        'output_sequence',
        'system_sequence',
        'first_output_sequence',
        'last_output_sequence',
        'max_tokens',
        'openai_max_tokens',
        'max_length',
        'min_length',
        'prompts',
        'prompt_order',
        'system_prompt',
        'post_history_instructions',
        'api_type',
        'openai_max_context',
        'stream_openai',
        'show_thoughts',
        'reasoning_effort',
        'verbosity',
        'chat_completion_source',
        'openai_model',
        'openrouter_model',
        'use_sysprompt',
        'custom_url',
        'reverse_proxy',
        'proxy_password',
        'names_behavior',
        'function_calling',
        'media_inlining',
        'request_images',
        'request_image_aspect_ratio',
        'request_image_resolution',
        'max_context_unlocked',
        'group_models',
        'sort_models',
        'claude_model',
        'openrouter_use_fallback',
        'openrouter_providers',
        'openrouter_quantizations',
        'openrouter_allow_fallbacks',
        'openrouter_middleout',
        'tool_reasoning_mode',
        'assistant_prefill',
        'assistant_impersonation',
        'impersonation_prompt',
        'new_chat_prompt',
        'continue_nudge_prompt',
        'continue_prefill',
        'continue_postfix',
        'bias_preset_selected',
        'custom_model',
        'custom_include_body',
        'custom_exclude_body',
        'custom_include_headers',
        'custom_prompt_post_processing',
        'send_if_empty',
        'use_system_prompt',
        'use_stop_strings',
        'stop_strings',
        '__st_manager_preset_kind',
    }
)

CHAT_HEADER_FIELDS = ('user_name', 'name', 'chat_metadata')


def _is_js_object(value: Any) -> bool:
    """Match JavaScript's object check for JSON values closely enough for import validation."""
    return value is None or isinstance(value, (dict, list))


def _is_valid_character_card_v2(card: dict) -> bool:
    if card.get('spec') != 'chara_card_v2' or card.get('spec_version') != '2.0':
        return False

    data = card.get('data')
    if not isinstance(data, dict):
        return False
    if not all(field in data for field in CHARACTER_CARD_V2_DATA_FIELDS):
        return False
    if not isinstance(data.get('alternate_greetings'), list):
        return False
    if not isinstance(data.get('tags'), list):
        return False
    if not _is_js_object(data.get('extensions')):
        return False

    character_book = data.get('character_book')
    if character_book is None or character_book is False or character_book == 0 or character_book == '':
        return True
    if not isinstance(character_book, dict):
        return False
    if not all(field in character_book for field in ('extensions', 'entries')):
        return False
    return (
        isinstance(character_book.get('entries'), list)
        and _is_js_object(character_book.get('extensions'))
    )


def _coerce_card_version(value: Any):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 3.0 or number >= 4.0:
        return None
    return number


def _is_valid_character_card_v3(card: dict) -> bool:
    if card.get('spec') != 'chara_card_v3':
        return False
    if _coerce_card_version(card.get('spec_version')) is None:
        return False
    return isinstance(card.get('data'), dict)


def get_character_card_version(card: Any):
    """Return the SillyTavern character card version, or ``None`` for other JSON."""
    if not isinstance(card, dict):
        return None

    if all(field in card for field in CHARACTER_CARD_V1_FIELDS):
        return 1
    if _is_valid_character_card_v2(card):
        return 2
    if _is_valid_character_card_v3(card):
        return 3
    return None


def is_valid_character_card_data(card: Any) -> bool:
    return get_character_card_version(card) is not None


def is_valid_world_info_data(data: Any) -> bool:
    """Validate the top-level shape accepted by SillyTavern's world info importer."""
    return isinstance(data, dict) and 'entries' in data


def is_valid_legacy_world_info_data(data: Any) -> bool:
    """Validate the manager's old entry-array export format for migration only."""
    if is_valid_world_info_data(data):
        return True
    if isinstance(data, list) and data:
        return all(
            isinstance(entry, dict)
            and any(key in entry for key in ('keys', 'key', 'content'))
            for entry in data
        )
    return False


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_regex_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    # ST accepts exported objects with scriptName and raw imports with findRegex.
    return _is_non_empty_string(value.get('scriptName')) or 'findRegex' in value


def is_valid_regex_data(data: Any) -> bool:
    if isinstance(data, dict):
        return _is_valid_regex_object(data)
    if isinstance(data, list) and data:
        return all(_is_valid_regex_object(item) for item in data)
    return False


def _is_valid_coerced_string(value: Any) -> bool:
    """z.coerce.string() accepts every JSON value and stringifies it."""
    return True


def _is_valid_script_button(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        'name' in value
        and _is_valid_coerced_string(value.get('name'))
        and 'visible' in value
        and isinstance(value.get('visible'), bool)
    )


def _is_valid_backward_script_button(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if 'name' in value and not isinstance(value.get('name'), str):
        return False
    return 'visible' not in value or isinstance(value.get('visible'), bool)


def _is_valid_new_script(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if 'type' in value and value.get('type') != 'script':
        return False
    if 'enabled' in value and not isinstance(value.get('enabled'), bool):
        return False
    for key in ('name', 'id', 'content', 'info'):
        if key in value and not _is_valid_coerced_string(value.get(key)):
            return False
    if 'button' in value:
        button = value.get('button')
        if not isinstance(button, dict):
            return False
        if 'enabled' in button and not isinstance(button.get('enabled'), bool):
            return False
        if 'buttons' in button:
            buttons = button.get('buttons')
            if not isinstance(buttons, list) or not all(_is_valid_script_button(item) for item in buttons):
                return False
    if 'data' in value and not isinstance(value.get('data'), dict):
        return False
    if 'export_with' in value:
        export_with = value.get('export_with')
        if not isinstance(export_with, dict):
            return False
        if any(
            key in export_with and not isinstance(export_with.get(key), bool)
            for key in ('data', 'button')
        ):
            return False
    return True


def _is_valid_backward_script(value: dict) -> bool:
    buttons = value.get('buttons')
    if buttons is None:
        buttons = []
    if not isinstance(buttons, list) or not all(_is_valid_backward_script_button(item) for item in buttons):
        return False
    if 'enabled' in value and not isinstance(value.get('enabled'), bool):
        return False
    for key in ('name', 'id', 'content', 'info'):
        if key in value and not isinstance(value.get(key), str):
            return False
    return 'data' not in value or isinstance(value.get('data'), dict)


def _is_valid_script_folder(value: dict) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get('type') != 'folder':
        return False
    if 'enabled' in value and not isinstance(value.get('enabled'), bool):
        return False
    for key in ('name', 'id'):
        if key in value and not _is_valid_coerced_string(value.get(key)):
            return False
    for key in ('icon', 'color'):
        if key in value and not isinstance(value.get(key), str):
            return False
    scripts = value.get('scripts', [])
    if not isinstance(scripts, list):
        return False
    return all(_is_valid_new_script(item) for item in scripts)


def _is_valid_backward_script_tree_item(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    item_type = value.get('type')
    if item_type == 'script':
        return isinstance(value.get('value'), dict) and _is_valid_backward_script(value['value'])
    if item_type == 'folder':
        scripts = value.get('value', [])
        return isinstance(scripts, list) and all(_is_valid_backward_script(item) for item in scripts)
    return _is_valid_backward_script(value)


def is_valid_st_script_data(data: Any) -> bool:
    """Validate JS-Slash-Runner Script/ScriptFolder and its legacy ScriptData shape."""
    if not isinstance(data, dict):
        return False

    script_type = data.get('type')
    if script_type == 'script':
        if 'value' in data:
            return _is_valid_backward_script_tree_item(data)
        return _is_valid_new_script(data)
    if script_type == 'folder':
        if 'value' in data:
            return _is_valid_backward_script_tree_item(data)
        return _is_valid_script_folder(data)
    if script_type is None and 'buttons' in data:
        return _is_valid_backward_script(data)
    return False


def _is_integer_json_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and number.is_integer()


def is_valid_quick_reply_data(data: Any) -> bool:
    """Match SillyTavern QuickReplySet import requirements."""
    return (
        isinstance(data, dict)
        and _is_integer_json_number(data.get('version'))
        and isinstance(data.get('name'), str)
        and isinstance(data.get('qrList'), list)
    )


def is_valid_preset_data(data: Any) -> bool:
    """Recognize the sampler/prompt fields used by SillyTavern presets."""
    if not isinstance(data, dict):
        return False
    if is_valid_character_card_data(data) or is_valid_world_info_data(data):
        return False
    # ST preset managers also persist generic JSON and legacy files that only
    # carry a display name/description. Keep those valid without accepting a
    # bare arbitrary object such as a worldbook or character card.
    generic_keys = {'name', 'title', 'description', 'note'}
    return bool(
        PRESET_FORMAT_KEYS.intersection(data.keys())
        or generic_keys.intersection(data.keys())
    )


def is_valid_chat_header(data: Any) -> bool:
    """Match SillyTavern's JSONL import header check."""
    return isinstance(data, dict) and any(field in data for field in CHAT_HEADER_FIELDS)


def is_valid_chat_jsonl_bytes(raw: Any) -> bool:
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, (bytes, bytearray)):
        try:
            text = bytes(raw).decode('utf-8-sig')
        except UnicodeDecodeError:
            return False
    else:
        return False

    if not text:
        return False
    try:
        header = json.loads(text.split('\n')[0])
    except (TypeError, ValueError):
        return False
    return is_valid_chat_header(header)
