"""Format validators shared by importers, filesystem scans, and indexes."""

import json
import math
from typing import Any


# V1 卡片识别使用全部核心字段（保持历史行为不变）。
CHARACTER_CARD_V1_FIELDS = (
    'name',
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
)

# V2 的 spec 标头本身已是很强的判别信号；data 只需包含任一核心字段即可认定为卡片。
# creator_notes / system_prompt / post_history_instructions 等属于扩展字段，
# 大量非官方工具导出的合法卡片并不包含它们，因此不能要求必须存在。
CHARACTER_CARD_V2_CORE_FIELDS = (
    'name',
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
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


def _is_valid_character_card_v2(card: dict) -> bool:
    """是否是可被 SillyTavern 导入的 V2 角色卡。

    SillyTavern 的 ``importFromPng`` / ``importFromJson``（``src/endpoints/characters.js``）
    只以 ``spec`` 标头判定卡片：``spec`` 存在即按 V2/V3 信封读取，**不**校验
    ``spec_version``、``data`` 字段类型，也不校验 ``character_book``。宿主此前按
    V2 规范逐字段校验，导致 ST 能导入的合法卡片被判为「非有效卡片」
    （典型：``character_book`` 缺 ``extensions``；该字段在实际导出的卡片里
    普遍缺失）。这里对齐 ST 的判定，只保留两个最小约束：

    - ``data`` 必须是对象（宿主的下游解析/编辑器都按 V2 信封读取 ``data``）；
    - ``data`` 至少出现一个 V1 核心字段（ST 生成文件名同样依赖角色名字段）。

    V1 没有 ``spec`` 标头，判定仍保持严格，见 ``get_character_card_version``。
    """
    if card.get('spec') != 'chara_card_v2':
        return False
    data = card.get('data')
    if not isinstance(data, dict):
        return False
    return any(field in data for field in CHARACTER_CARD_V2_CORE_FIELDS)


def _is_valid_character_card_v3(card: dict) -> bool:
    """V3 标头 + 对象型 ``data`` 即视为卡片（与 ST 的导入判定一致）。"""
    if card.get('spec') != 'chara_card_v3':
        return False
    return isinstance(card.get('data'), dict)


def get_character_card_version(card: Any):
    """Return the SillyTavern character card version, or ``None`` for other JSON.

    判定顺序与 SillyTavern 的导入逻辑一致：先看 ``spec`` 标头，再退回 V1 字段。
    V1 仍要求全部核心字段——V1 没有标头，而世界书 / 预设 / 聊天头也常带
    ``name``，放宽会把它们误识别成卡片（见
    ``test_character_card_validator_rejects_cross_type_payloads``）。
    """
    if not isinstance(card, dict):
        return None

    if _is_valid_character_card_v3(card):
        return 3
    if _is_valid_character_card_v2(card):
        return 2
    if all(field in card for field in CHARACTER_CARD_V1_FIELDS):
        return 1
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
