"""Preset detail model helpers."""

import copy
import os

from core.services.preset_editor_schema import build_editor_profile_payload
from core.services.preset_editor_schema import normalize_preset_content_for_save
from core.services.preset_editor_schema import resolve_profile_remove_keys
from core.services.preset_editor_schema import resolve_profile_storage_key
from core.services.preset_extensions import is_managed_extension_key
from core.utils.source_revision import build_file_source_revision


PRESET_KIND_LABELS = {
    'openai': 'ST 聊天补全预设',
    'generic': '通用 JSON',
}

MANAGED_PRESET_KIND_KEY = '__st_manager_preset_kind'
MANAGED_PRESET_KIND_VALUES = {'openai', 'generic'}

GENERIC_READER_FAMILY_LABEL = '通用预设'
PROMPT_MANAGER_READER_FAMILY_LABEL = '提示词管理预设'

LONG_TEXT_EDITOR_KEYS = {
    'content',
    'story_string',
    'example_separator',
    'chat_start',
    'prefix',
    'suffix',
    'separator',
    'negative_prompt',
    'json_schema',
    'grammar',
    'input_sequence',
    'output_sequence',
    'system_sequence',
    'first_output_sequence',
    'last_output_sequence',
    'activation_regex',
}

SELECT_EDITOR_OPTIONS = {
    'names_behavior': ['default', 'always', 'never'],
    'insertion_position': ['before', 'after'],
    'injection_role': ['system', 'user', 'assistant'],
}


COMMON_FIELD_KEYS = {
    'name',
    'title',
    'description',
    'note',
    'extensions',
    'prompts',
    'prompt_order',
}


FIELD_ALIAS_MAP = {}

LEGACY_PROMPT_WORKSPACE_MARKERS = {
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
}

READER_COMMON_FIELD_DEFS = [
    {'key': 'name', 'label': '名称'},
    {'key': 'title', 'label': '标题'},
    {'key': 'description', 'label': '描述'},
    {'key': 'note', 'label': '备注'},
]

GENERIC_READER_GROUP_LABELS = {
    'scalar_fields': '基础字段',
    'structured_objects': '结构化对象',
    'prompts': '消息模板',
    'extensions': '扩展设置',
}

PROMPT_MANAGER_READER_GROUP_LABELS = {
    'prompts': 'Prompt 条目',
    'scalar_fields': '基础字段',
    'structured_objects': '结构化对象',
    'extensions': '扩展设置',
}

PROMPT_INJECTION_POSITION_LABELS = {
    0: '相对位置',
    1: 'In-Chat 注入',
}

SCALAR_WORKSPACE_PROFILE_ID = 'legacy_scalar_workspace'

SCALAR_WORKSPACE_SECTIONS = [
    {'id': 'core_sampling', 'label': '核心采样'},
    {'id': 'penalties', 'label': '惩罚'},
    {'id': 'advanced_sampling', 'label': '高级采样'},
    {'id': 'constraints_and_control', 'label': '约束与控制'},
    {'id': 'sampler_ordering', 'label': '采样器排序'},
]

SCALAR_WORKSPACE_FIELD_DEFS = [
    {
        'canonical_key': 'temp',
        'storage_keys': ['temp', 'temperature'],
        'section': 'core_sampling',
        'label': '温度',
        'editor': 'number',
    },
    {
        'canonical_key': 'top_p',
        'storage_keys': ['top_p'],
        'section': 'core_sampling',
        'label': 'Top P',
        'editor': 'number',
    },
    {
        'canonical_key': 'top_k',
        'storage_keys': ['top_k'],
        'section': 'core_sampling',
        'label': 'Top K',
        'editor': 'number',
    },
    {
        'canonical_key': 'min_p',
        'storage_keys': ['min_p'],
        'section': 'core_sampling',
        'label': 'Min P',
        'editor': 'number',
    },
    {
        'canonical_key': 'repetition_penalty',
        'storage_keys': ['repetition_penalty', 'rep_pen'],
        'section': 'penalties',
        'label': '重复惩罚',
        'editor': 'number',
    },
    {
        'canonical_key': 'frequency_penalty',
        'storage_keys': ['frequency_penalty', 'freq_pen'],
        'section': 'penalties',
        'label': '频率惩罚',
        'editor': 'number',
    },
    {
        'canonical_key': 'presence_penalty',
        'storage_keys': ['presence_penalty', 'pres_pen'],
        'section': 'penalties',
        'label': '存在惩罚',
        'editor': 'number',
    },
    {
        'canonical_key': 'temperature_last',
        'storage_keys': ['temperature_last'],
        'section': 'advanced_sampling',
        'label': 'Temperature Last',
        'editor': 'boolean',
    },
    {
        'canonical_key': 'dynamic_temperature',
        'storage_keys': ['dynamic_temperature', 'dynatemp'],
        'section': 'advanced_sampling',
        'label': '动态温度',
        'editor': 'boolean',
    },
    {
        'canonical_key': 'dynatemp_low',
        'storage_keys': ['dynatemp_low', 'min_temp'],
        'section': 'advanced_sampling',
        'label': '动态温度下限',
        'editor': 'number',
    },
    {
        'canonical_key': 'dynatemp_high',
        'storage_keys': ['dynatemp_high', 'max_temp'],
        'section': 'advanced_sampling',
        'label': '动态温度上限',
        'editor': 'number',
    },
    {
        'canonical_key': 'mirostat_mode',
        'storage_keys': ['mirostat_mode'],
        'section': 'advanced_sampling',
        'label': 'Mirostat 模式',
        'editor': 'number',
    },
    {
        'canonical_key': 'mirostat_tau',
        'storage_keys': ['mirostat_tau'],
        'section': 'advanced_sampling',
        'label': 'Mirostat Tau',
        'editor': 'number',
    },
    {
        'canonical_key': 'mirostat_eta',
        'storage_keys': ['mirostat_eta'],
        'section': 'advanced_sampling',
        'label': 'Mirostat Eta',
        'editor': 'number',
    },
    {
        'canonical_key': 'guidance_scale',
        'storage_keys': ['guidance_scale'],
        'section': 'constraints_and_control',
        'label': 'Guidance Scale',
        'editor': 'number',
    },
    {
        'canonical_key': 'negative_prompt',
        'storage_keys': ['negative_prompt'],
        'section': 'constraints_and_control',
        'label': 'Negative Prompt',
        'editor': 'textarea',
    },
    {
        'canonical_key': 'json_schema',
        'storage_keys': ['json_schema'],
        'section': 'constraints_and_control',
        'label': 'JSON Schema',
        'editor': 'textarea',
    },
    {
        'canonical_key': 'grammar',
        'storage_keys': ['grammar', 'grammar_string'],
        'section': 'constraints_and_control',
        'label': 'Grammar',
        'editor': 'textarea',
    },
    {
        'canonical_key': 'banned_tokens',
        'storage_keys': ['banned_tokens'],
        'section': 'constraints_and_control',
        'label': '禁词',
        'editor': 'textarea',
    },
    {
        'canonical_key': 'logit_bias',
        'storage_keys': ['logit_bias'],
        'section': 'constraints_and_control',
        'label': 'Logit Bias',
        'editor': 'key-value-list',
    },
    {
        'canonical_key': 'sampler_order',
        'storage_keys': ['sampler_order'],
        'section': 'sampler_ordering',
        'label': 'Sampler Order',
        'editor': 'sortable-string-list',
    },
    {
        'canonical_key': 'samplers',
        'storage_keys': ['samplers'],
        'section': 'sampler_ordering',
        'label': 'Sampler Priority',
        'editor': 'sortable-string-list',
    },
]

SCALAR_WORKSPACE_HIDDEN_FIELDS = [
    'top_a',
    'typical_p',
    'tfs',
    'repetition_penalty_range',
    'repetition_penalty_decay',
    'no_repeat_ngram_size',
    'max_tokens',
    'openai_max_tokens',
    'max_length',
    'min_length',
    'num_beams',
    'length_penalty',
    'do_sample',
    'early_stopping',
    'stream_openai',
    'wrap_in_quotes',
    'show_thoughts',
    'xtc_threshold',
]


SECTION_DEFINITIONS = {
    'openai': {
        'provider_and_models': [
            {'key': 'chat_completion_source', 'aliases': [], 'label': '聊天补全来源'},
            {'key': 'openai_model', 'aliases': [], 'label': 'OpenAI 模型'},
            {'key': 'openrouter_model', 'aliases': [], 'label': 'OpenRouter 模型'},
        ],
        'connection_and_endpoints': [
            {'key': 'custom_url', 'aliases': [], 'label': '自定义接口地址'},
            {'key': 'reverse_proxy', 'aliases': [], 'label': '反向代理'},
            {'key': 'proxy_password', 'aliases': [], 'label': '代理密码'},
        ],
        'output_and_reasoning': [
            {'key': 'openai_max_context', 'aliases': [], 'label': '上下文长度'},
            {'key': 'openai_max_tokens', 'aliases': ['max_tokens', 'max_length'], 'label': '最大生成长度'},
            {'key': 'stream_openai', 'aliases': [], 'label': '流式输出'},
            {'key': 'show_thoughts', 'aliases': [], 'label': '显示思维链'},
            {'key': 'reasoning_effort', 'aliases': [], 'label': '推理强度'},
            {'key': 'verbosity', 'aliases': [], 'label': '输出冗长度'},
            {'key': 'min_length', 'aliases': [], 'label': '最小长度'},
            {'key': 'num_beams', 'aliases': [], 'label': 'Beam 数'},
            {'key': 'length_penalty', 'aliases': [], 'label': 'Length Penalty'},
            {'key': 'do_sample', 'aliases': [], 'label': 'Do Sample'},
            {'key': 'early_stopping', 'aliases': [], 'label': 'Early Stopping'},
        ],
        'core_sampling': [
            {'key': 'temperature', 'aliases': ['temp'], 'label': '温度'},
            {'key': 'top_p', 'aliases': [], 'label': 'Top P'},
            {'key': 'top_k', 'aliases': [], 'label': 'Top K'},
            {'key': 'top_a', 'aliases': [], 'label': 'Top A'},
            {'key': 'min_p', 'aliases': [], 'label': 'Min P'},
            {'key': 'typical_p', 'aliases': ['typical'], 'label': 'Typical P'},
            {'key': 'tfs', 'aliases': [], 'label': 'TFS'},
            {'key': 'temperature_last', 'aliases': [], 'label': 'Temperature Last'},
        ],
        'penalties_and_behavior': [
            {'key': 'repetition_penalty', 'aliases': ['rep_pen'], 'label': '重复惩罚'},
            {'key': 'repetition_penalty_range', 'aliases': [], 'label': '重复范围'},
            {'key': 'repetition_penalty_decay', 'aliases': [], 'label': '重复衰减'},
            {'key': 'frequency_penalty', 'aliases': ['freq_pen'], 'label': '频率惩罚'},
            {'key': 'presence_penalty', 'aliases': ['pres_pen'], 'label': '存在惩罚'},
            {'key': 'no_repeat_ngram_size', 'aliases': [], 'label': 'No Repeat Ngram'},
            {'key': 'names_behavior', 'aliases': [], 'label': '名称行为'},
        ],
        'images_and_advanced': [
            {'key': 'dynamic_temperature', 'aliases': [], 'label': '动态温度'},
            {'key': 'dynatemp_low', 'aliases': [], 'label': '动态温度下限'},
            {'key': 'dynatemp_high', 'aliases': [], 'label': '动态温度上限'},
            {'key': 'mirostat_mode', 'aliases': [], 'label': 'Mirostat 模式'},
            {'key': 'mirostat_tau', 'aliases': [], 'label': 'Mirostat Tau'},
            {'key': 'mirostat_eta', 'aliases': [], 'label': 'Mirostat Eta'},
            {'key': 'guidance_scale', 'aliases': [], 'label': 'Guidance Scale'},
            {'key': 'negative_prompt', 'aliases': [], 'label': 'Negative Prompt'},
            {'key': 'wrap_in_quotes', 'aliases': [], 'label': '包裹引号'},
            {'key': 'media_inlining', 'aliases': [], 'label': '媒体内联'},
            {'key': 'request_images', 'aliases': [], 'label': '请求图像'},
            {'key': 'request_image_aspect_ratio', 'aliases': [], 'label': '图像比例'},
            {'key': 'request_image_resolution', 'aliases': [], 'label': '图像分辨率'},
            {'key': 'json_schema', 'aliases': [], 'label': 'JSON Schema'},
            {'key': 'grammar', 'aliases': [], 'label': 'Grammar'},
            {'key': 'banned_tokens', 'aliases': [], 'label': '禁词'},
            {'key': 'logit_bias', 'aliases': [], 'label': 'Logit Bias'},
            {'key': 'sampler_order', 'aliases': [], 'label': 'Sampler Order'},
            {'key': 'samplers', 'aliases': [], 'label': 'Sampler Priority'},
        ],
        'templates_and_features': [
            {'key': 'use_sysprompt', 'aliases': [], 'label': '使用系统提示词'},
            {'key': 'function_calling', 'aliases': [], 'label': '函数调用'},
        ],
    },
}

for _kind_sections in SECTION_DEFINITIONS.values():
    for _field_defs in _kind_sections.values():
        for _field_def in _field_defs:
            FIELD_ALIAS_MAP[_field_def['key']] = [_field_def['key'], *_field_def.get('aliases', [])]


def detect_preset_kind(raw_data, source_folder='', file_path=''):
    data = raw_data if isinstance(raw_data, dict) else {}
    managed_kind = str(data.get(MANAGED_PRESET_KIND_KEY) or '').strip()
    if managed_kind in MANAGED_PRESET_KIND_VALUES:
        return managed_kind
    openai_markers = {
        'openai_max_context',
        'openai_max_tokens',
        'stream_openai',
        'show_thoughts',
        'reasoning_effort',
        'verbosity',
        'chat_completion_source',
        'openai_model',
        'use_sysprompt',
        'openrouter_model',
        'custom_url',
        'reverse_proxy',
        'proxy_password',
        'names_behavior',
        'function_calling',
        'media_inlining',
        'request_images',
        'request_image_aspect_ratio',
        'request_image_resolution',
    }
    if any(key in data for key in openai_markers):
        return 'openai'
    if _matches_openai_prompt_workspace_shape(data):
        return 'openai'
    if _matches_openai_path_hint(source_folder, file_path):
        return 'openai'
    return 'generic'


def _matches_openai_path_hint(source_folder, file_path):
    return str(source_folder or '').strip().lower() == 'st_openai_preset_dir'


def _matches_openai_prompt_workspace_shape(data):
    prompts = data.get('prompts')
    if not isinstance(prompts, list):
        return False

    prompt_metadata_keys = {'system_prompt', 'marker', 'injection_position', 'injection_depth'}
    if any(
        isinstance(prompt, dict) and any(key in prompt for key in prompt_metadata_keys)
        for prompt in prompts
    ):
        return True

    prompt_order = data.get('prompt_order')
    if not isinstance(prompt_order, list):
        return False

    if any(isinstance(prompt, dict) and 'enabled' in prompt for prompt in prompts):
        return True

    if prompt_order and all(isinstance(entry, dict) and 'identifier' in entry for entry in prompt_order):
        return True

    if any(isinstance(entry, dict) and 'order' in entry for entry in prompt_order):
        return True

    return False


def _sanitize_preset_data(raw_data):
    if not isinstance(raw_data, dict):
        return raw_data

    sanitized = copy.deepcopy(raw_data)
    sanitized.pop(MANAGED_PRESET_KIND_KEY, None)
    return sanitized


def strip_managed_kind_marker(raw_data):
    return _sanitize_preset_data(raw_data)


def _resolve_field(data, field_def):
    candidates = [field_def['key'], *field_def.get('aliases', [])]
    for source_key in candidates:
        if source_key in data:
            return source_key, data.get(source_key)
    return None, None


def build_sections(raw_data, preset_kind):
    data = raw_data if isinstance(raw_data, dict) else {}
    definitions = SECTION_DEFINITIONS.get(preset_kind, {})
    sections = {}
    consumed_keys = set(COMMON_FIELD_KEYS)

    for section_name, field_defs in definitions.items():
        items = []
        for field_def in field_defs:
            source_key, value = _resolve_field(data, field_def)
            if source_key is None:
                continue
            consumed_keys.add(source_key)
            items.append({
                'key': field_def['key'],
                'source_key': source_key,
                'label': field_def['label'],
                'value': value,
            })
        if items:
            sections[section_name] = items

    unknown_fields = sorted(key for key in data.keys() if key not in consumed_keys)
    return sections, unknown_fields


def _build_reader_item(*, item_id, item_type, group, title, payload, summary=''):
    return {
        'id': item_id,
        'type': item_type,
        'group': group,
        'title': title,
        'summary': summary,
        'payload': copy.deepcopy(payload),
    }


def _infer_scalar_editor_kind(key, value):
    if key in SELECT_EDITOR_OPTIONS:
        return 'select'
    if key in LONG_TEXT_EDITOR_KEYS:
        return 'textarea'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 'number'
    return 'text'


def _build_editor_meta(kind, label='', description='', raw_fallback=False, options=None):
    meta = {
        'kind': kind,
        'label': label,
        'description': description,
        'raw_fallback': raw_fallback,
    }
    if options is not None:
        meta['options'] = list(options)
    return meta


def _with_editor_fields(item, *, editable, source_key, value_path, unknown, editor):
    enriched = dict(item)
    enriched['editable'] = editable
    enriched['source_key'] = source_key
    enriched['value_path'] = value_path
    enriched['unknown'] = unknown
    enriched['editor'] = copy.deepcopy(editor)
    return enriched


def _build_scalar_reader_item(group, key, value, title=''):
    editor_kind = _infer_scalar_editor_kind(key, value)
    editor_options = SELECT_EDITOR_OPTIONS.get(key)
    return _with_editor_fields(
        _build_reader_item(
        item_id=f'{group}:{key}',
        item_type='field',
        group=group,
        title=title or key,
        summary=str(value),
        payload={'key': key, 'value': copy.deepcopy(value)},
        ),
        editable=True,
        source_key=key,
        value_path=key,
        unknown=False,
        editor=_build_editor_meta(editor_kind, label=title or key, options=editor_options),
    )


def _build_structured_reader_item(group, key, value, title=''):
    value_type = type(value).__name__
    if key == 'logit_bias':
        editor_kind = 'key-value-list'
    elif key in {'prompt_order', 'sampler_order', 'samplers'}:
        editor_kind = 'sortable-string-list'
    elif key == 'stop_sequence':
        editor_kind = 'string-list'
    else:
        editor_kind = 'raw-json'
    return _with_editor_fields(
        _build_reader_item(
        item_id=f'{group}:{key}',
        item_type='structured',
        group=group,
        title=title or key,
        summary=value_type,
        payload={'key': key, 'value': copy.deepcopy(value)},
        ),
        editable=editor_kind != 'raw-json',
        source_key=key,
        value_path=key,
        unknown=False,
        editor=_build_editor_meta(editor_kind, label=title or key, raw_fallback=True),
    )


def _build_prompt_reader_items(data):
    items = []
    for index, prompt in enumerate(data.get('prompts') or []):
        if not isinstance(prompt, dict):
            continue
        identifier = str(prompt.get('identifier') or f'prompt_{index + 1}')
        title = str(prompt.get('name') or identifier)
        role = str(prompt.get('role') or '').strip()
        enabled = prompt.get('enabled', True) is not False
        summary_parts = [role or 'prompt', 'enabled' if enabled else 'disabled']
        if prompt.get('marker'):
            summary_parts.append('marker')
        summary = ' · '.join(summary_parts)
        items.append(
            _with_editor_fields(
                _build_reader_item(
                    item_id=f'prompt:{identifier}',
                    item_type='prompt',
                    group='prompts',
                    title=title,
                    summary=summary,
                    payload=copy.deepcopy(prompt),
                ),
                editable=False,
                source_key='prompts',
                value_path=f'prompts[{index}]',
                unknown=False,
                editor=_build_editor_meta('raw-json', label='消息模板', raw_fallback=True),
            )
        )
    return items


def _is_prompt_workspace_candidate(data):
    prompts = data.get('prompts')
    return isinstance(prompts, list) and any(isinstance(prompt, dict) for prompt in prompts)


def _normalize_prompt_order_entries(prompt_order):
    if not isinstance(prompt_order, list):
        return []

    if prompt_order and all(isinstance(entry, str) for entry in prompt_order):
        return [
            {'identifier': str(entry).strip(), 'enabled': None}
            for entry in prompt_order
            if str(entry).strip()
        ]

    if prompt_order and all(isinstance(entry, dict) and 'identifier' in entry for entry in prompt_order):
        return [
            {
                'identifier': str(entry.get('identifier') or '').strip(),
                'enabled': entry.get('enabled', True) is not False,
            }
            for entry in prompt_order
            if str(entry.get('identifier') or '').strip()
        ]

    entries = []
    for bucket in prompt_order:
        if not isinstance(bucket, dict) or not isinstance(bucket.get('order'), list):
            continue
        entries.extend(
            {
                'identifier': str(entry.get('identifier') or '').strip(),
                'enabled': entry.get('enabled', True) is not False,
            }
            for entry in bucket['order']
            if isinstance(entry, dict) and str(entry.get('identifier') or '').strip()
        )
    if entries:
        return entries

    return []


def _resolve_scalar_workspace_field(data, field_def):
    for storage_key in field_def['storage_keys']:
        if storage_key in data:
            return storage_key
    return None


def _matches_textgen_scalar_workspace(data, preset_kind):
    return False


def _build_scalar_workspace(data, preset_kind):
    if not _matches_textgen_scalar_workspace(data, preset_kind):
        return None

    field_map = {}
    section_ids = set()
    for field_def in SCALAR_WORKSPACE_FIELD_DEFS:
        storage_key = _resolve_scalar_workspace_field(data, field_def)
        if storage_key is None:
            continue

        section_ids.add(field_def['section'])
        field_map[storage_key] = {
            'canonical_key': field_def['canonical_key'],
            'storage_key': storage_key,
            'section': field_def['section'],
            'label': field_def['label'],
            'editor': field_def['editor'],
        }

    sections = [section for section in SCALAR_WORKSPACE_SECTIONS if section['id'] in section_ids]
    return {
        'profile_id': SCALAR_WORKSPACE_PROFILE_ID,
        'sections': sections,
        'field_map': field_map,
        'hidden_fields': list(SCALAR_WORKSPACE_HIDDEN_FIELDS),
    }


def _prompt_position_label(prompt):
    try:
        position = int(prompt.get('injection_position', 0) or 0)
    except (TypeError, ValueError):
        position = 0

    if position == 1:
        try:
            depth = int(prompt.get('injection_depth', 4) or 4)
        except (TypeError, ValueError):
            depth = 4
        return f'In-Chat @ {depth}'
    return PROMPT_INJECTION_POSITION_LABELS.get(position, '相对位置')


def _build_prompt_manager_prompt_items(data):
    indexed_prompts = [
        (index, prompt)
        for index, prompt in enumerate(data.get('prompts') or [])
        if isinstance(prompt, dict)
    ]
    prompt_order_entries = _normalize_prompt_order_entries(data.get('prompt_order'))
    order_lookup = {}
    for index, entry in enumerate(prompt_order_entries):
        identifier = entry['identifier']
        if identifier in order_lookup:
            continue
        order_lookup[identifier] = {'order_index': index, 'enabled': entry['enabled']}
    prompt_lookup = {
        str(prompt.get('identifier') or f'prompt_{index + 1}'): (index, prompt)
        for index, prompt in indexed_prompts
    }

    ordered_identifiers = []
    seen_identifiers = set()
    for entry in prompt_order_entries:
        identifier = entry['identifier']
        if identifier not in prompt_lookup or identifier in seen_identifiers:
            continue
        ordered_identifiers.append(identifier)
        seen_identifiers.add(identifier)
    orphan_identifiers = [
        identifier
        for identifier in prompt_lookup.keys()
        if identifier not in order_lookup
    ]

    items = []
    for order_index, identifier in enumerate([*ordered_identifiers, *orphan_identifiers]):
        prompt_index, prompt = prompt_lookup[identifier]
        prompt_enabled = prompt.get('enabled', True) is not False
        ordered_enabled = order_lookup.get(identifier, {}).get('enabled')
        enabled = prompt_enabled if ordered_enabled is None else ordered_enabled
        is_marker = bool(prompt.get('marker'))
        role = str(prompt.get('role') or '').strip()
        summary_parts = [role or 'prompt', '启用' if enabled else '禁用', _prompt_position_label(prompt)]
        if is_marker:
            summary_parts.append('预留字段')

        item = _with_editor_fields(
            _build_reader_item(
                item_id=f'prompt:{identifier}',
                item_type='prompt',
                group='prompts',
                title=str(prompt.get('name') or identifier),
                summary=' · '.join(summary_parts),
                payload=copy.deepcopy(prompt),
            ),
            editable=True,
            source_key='prompts',
            value_path=f'prompts[{prompt_index}]',
            unknown=False,
            editor=_build_editor_meta('prompt-manager-item', label='Prompt 条目', raw_fallback=True),
        )
        item['reorderable'] = True
        item['content_editable'] = not is_marker
        item['prompt_meta'] = {
            'identifier': identifier,
            'is_marker': is_marker,
            'is_enabled': enabled,
            'content_editable': not is_marker,
            'uses_prompt_order': bool(prompt_order_entries),
            'order_index': order_index,
            'is_orphan': identifier not in order_lookup,
        }
        items.append(item)
    return items

def _build_extension_items(data):
    extensions = data.get('extensions')
    if not isinstance(extensions, dict):
        return []

    items = []
    for key in sorted(extensions.keys()):
        if is_managed_extension_key(key):
            continue
        value = extensions.get(key)
        items.append(
            _with_editor_fields(
                _build_reader_item(
                    item_id=f'extensions:{key}',
                    item_type='extension',
                    group='extensions',
                    title=key,
                    summary=type(value).__name__,
                    payload={'key': key, 'value': copy.deepcopy(value)},
                ),
                editable=True,
                source_key='extensions',
                value_path=f'extensions.{key}',
                unknown=False,
                editor=_build_editor_meta('raw-json', label=key, raw_fallback=True),
            )
        )
    return items


def _build_group_defs(group_labels, items):
    counts = {}
    for item in items:
        group = item['group']
        counts[group] = counts.get(group, 0) + 1

    groups = []
    for group_id, label in group_labels.items():
        count = counts.get(group_id, 0)
        if count == 0:
            continue
        groups.append({'id': group_id, 'label': label, 'count': count})
    return groups


def _build_generic_reader_items(data):
    items = []
    for field_def in READER_COMMON_FIELD_DEFS:
        key = field_def['key']
        if key not in data:
            continue
        items.append(_build_scalar_reader_item('scalar_fields', key, data.get(key), field_def['label']))

    for key, value in data.items():
        if key in {'name', 'title', 'description', 'note'}:
            continue
        if key == 'extensions':
            continue
        if key == 'prompts' and isinstance(value, list):
            continue
        if key == 'prompt_order' and isinstance(value, list):
            continue
        if isinstance(value, (dict, list)):
            items.append(_build_structured_reader_item('structured_objects', key, value, key))
        else:
            items.append(_build_scalar_reader_item('scalar_fields', key, value, key))

    items.extend(_build_prompt_reader_items(data))
    items.extend(_build_extension_items(data))
    return items


def _build_prompt_manager_reader_items(data, preset_kind=None):
    items = []
    hidden_scalar_fields = (
        set(SCALAR_WORKSPACE_HIDDEN_FIELDS)
        if _matches_textgen_scalar_workspace(data, preset_kind)
        else set()
    )

    for field_def in READER_COMMON_FIELD_DEFS:
        key = field_def['key']
        if key in data:
            items.append(_build_scalar_reader_item('scalar_fields', key, data.get(key), field_def['label']))

    items.extend(_build_prompt_manager_prompt_items(data))

    for key, value in data.items():
        if key in {'name', 'title', 'description', 'note', 'prompts', 'prompt_order', 'extensions'}:
            continue
        if key in hidden_scalar_fields:
            continue
        if isinstance(value, (dict, list)):
            items.append(_build_structured_reader_item('structured_objects', key, value, key))
        else:
            items.append(_build_scalar_reader_item('scalar_fields', key, value, key))

    items.extend(_build_extension_items(data))
    return items


def build_reader_view(raw_data, preset_kind=None):
    data = raw_data if isinstance(raw_data, dict) else {}
    if preset_kind == 'openai' and _is_prompt_workspace_candidate(data):
        items = _build_prompt_manager_reader_items(data, preset_kind)
        groups = _build_group_defs(PROMPT_MANAGER_READER_GROUP_LABELS, items)
        prompt_count = len([item for item in items if item['type'] == 'prompt'])

        return {
            'family': 'prompt_manager',
            'family_label': PROMPT_MANAGER_READER_FAMILY_LABEL,
            'scalar_workspace': _build_scalar_workspace(data, preset_kind),
            'groups': groups,
            'items': items,
            'stats': {
                'prompt_count': prompt_count,
                'unknown_count': 0,
            },
        }

    items = _build_generic_reader_items(data)
    groups = _build_group_defs(GENERIC_READER_GROUP_LABELS, items)
    prompt_count = len([item for item in items if item['type'] == 'prompt'])

    return {
        'family': 'generic',
        'family_label': GENERIC_READER_FAMILY_LABEL,
        'scalar_workspace': None,
        'groups': groups,
        'items': items,
        'stats': {
            'prompt_count': prompt_count,
            'unknown_count': 0,
        },
    }


def build_preset_detail(*, preset_id, file_path, filename, source_type, source_folder, raw_data, base_dir, preset_kind_hint=''):
    preset_kind = str(preset_kind_hint or '').strip() or detect_preset_kind(
        raw_data,
        source_folder=source_folder,
        file_path=file_path,
    )
    sanitized_raw_data = _sanitize_preset_data(raw_data)
    sections, _unknown_fields = build_sections(sanitized_raw_data, preset_kind)
    reader_view = build_reader_view(sanitized_raw_data, preset_kind)
    editor_profile = build_editor_profile_payload(sanitized_raw_data, preset_kind)
    data = sanitized_raw_data if isinstance(sanitized_raw_data, dict) else {}

    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        mtime = 0
    try:
        file_size = os.path.getsize(file_path)
    except OSError:
        file_size = 0

    rel_path = file_path
    try:
        rel_path = os.path.relpath(file_path, base_dir)
    except Exception:
        pass

    return {
        'id': preset_id,
        'name': data.get('name') or data.get('title') or os.path.splitext(filename)[0],
        'filename': filename,
        'path': rel_path,
        'file_path': file_path,
        'source_folder': source_folder,
        'file_size': file_size,
        'mtime': mtime,
        'type': source_type,
        'preset_kind': preset_kind,
        'preset_kind_label': PRESET_KIND_LABELS[preset_kind],
        'source_revision': build_file_source_revision(file_path),
        'is_default_candidate': source_type == 'global',
        'raw_data': copy.deepcopy(sanitized_raw_data or {}),
        'sections': sections,
        'editor_profile': editor_profile,
        'reader_view': reader_view,
        'extensions': copy.deepcopy(data.get('extensions') or {}),
    }


def merge_preset_content(raw_data, preset_kind, content):
    source_data = raw_data if isinstance(raw_data, dict) else {}
    merged = copy.deepcopy(source_data)
    remove_keys = resolve_profile_remove_keys(source_data, preset_kind, content)
    content = normalize_preset_content_for_save(source_data, preset_kind, content)

    for key in remove_keys:
        merged.pop(key, None)

    normalized_content = {}
    for key, value in content.items():
        normalized_content[resolve_profile_storage_key(source_data, preset_kind, key)] = value

    for key, value in normalized_content.items():
        if key == 'extensions':
            continue
        merged[key] = value

    if 'extensions' in source_data or 'extensions' in normalized_content:
        merged['extensions'] = copy.deepcopy(
            source_data.get('extensions')
            if 'extensions' not in normalized_content
            else normalized_content.get('extensions')
        ) or {}

    if preset_kind in MANAGED_PRESET_KIND_VALUES:
        merged[MANAGED_PRESET_KIND_KEY] = preset_kind
    else:
        merged.pop(MANAGED_PRESET_KIND_KEY, None)

    return merged
