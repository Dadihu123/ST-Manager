"""Preset editor profile payload helpers."""

import copy


CHAT_COMPLETION_PROFILE_ID = 'st_chat_completion_preset'
GENERIC_PROFILE_ID = 'generic_json'


CHAT_COMPLETION_MARKER_FIELDS = {
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
    'ai21_model',
    'mistralai_model',
    'cohere_model',
    'perplexity_model',
    'groq_model',
    'chutes_model',
    'siliconflow_model',
    'minimax_model',
    'electronhub_model',
    'nanogpt_model',
    'deepseek_model',
    'aimlapi_model',
    'xai_model',
    'pollinations_model',
    'moonshot_model',
    'fireworks_model',
    'cometapi_model',
    'custom_model',
    'custom_include_body',
    'custom_exclude_body',
    'custom_include_headers',
    'custom_prompt_post_processing',
    'google_model',
    'vertexai_model',
    'zai_model',
    'zai_endpoint',
    'workers_ai_model',
    'workers_ai_account_id',
    'send_if_empty',
    'bias_preset_selected',
    'show_external_models',
    'assistant_prefill',
    'assistant_impersonation',
    'vertexai_auth_mode',
    'vertexai_region',
    'vertexai_express_project_id',
    'squash_system_messages',
    'inline_image_quality',
    'continue_prefill',
    'continue_postfix',
    'tool_call_recurse_limit',
    'enable_web_search',
    'bypass_status_check',
    'azure_base_url',
    'azure_deployment_name',
    'azure_api_version',
    'azure_openai_model',
}

ALLOWED_PASSTHROUGH_SAVE_KEYS = {
    'name',
    'title',
    'description',
    'note',
    'extensions',
}

OPENAI_RUNTIME_ONLY_SAVE_KEYS = {
    'api_url',
}

MANAGED_PRESET_KIND_KEY = '__st_manager_preset_kind'


def _field(
    canonical_key,
    storage_keys,
    *,
    section,
    label,
    control,
    description='',
    min_value=None,
    max_value=None,
    step=None,
    default=None,
    options=None,
    preset_bound=True,
    preserve_existing_key=True,
    visibility_rule='core_or_present',
    reader_style=None,
    sensitive=False,
):
    payload = {
        'canonical_key': canonical_key,
        'storage_keys': list(storage_keys),
        'section': section,
        'label': label,
        'control': control,
        'description': description,
        'preset_bound': preset_bound,
        'preserve_existing_key': preserve_existing_key,
        'visibility_rule': visibility_rule,
        'reader_style': reader_style or control,
        'sensitive': bool(sensitive),
    }
    if min_value is not None:
        payload['min'] = min_value
    if max_value is not None:
        payload['max'] = max_value
    if step is not None:
        payload['step'] = step
    if default is not None:
        payload['default'] = default
    if options is not None:
        payload['options'] = list(options)
    return payload


CHAT_COMPLETION_SECTIONS = [
    {'id': 'provider_and_models', 'label': '提供商与模型', 'description': '来源、模型选择与提供商相关配置'},
    {'id': 'connection_and_endpoints', 'label': '连接与端点', 'description': 'API 地址、代理与鉴权等连接配置'},
    {'id': 'output_and_reasoning', 'label': '输出与推理', 'description': '上下文、回复长度、流式与推理配置'},
    {'id': 'core_sampling', 'label': '核心采样', 'description': '温度、Top P、Top K 与相关采样参数'},
    {'id': 'penalties_and_behavior', 'label': '惩罚与行为', 'description': '频率、存在、命名与系统提示等行为配置'},
    {'id': 'prompt_manager', 'label': '提示词管理', 'description': 'Prompt 顺序、启用状态与正文编辑'},
    {'id': 'templates_and_features', 'label': '模板与特性', 'description': '模板字段、函数调用与多模态特性'},
    {'id': 'images_and_advanced', 'label': '图像与高级', 'description': '图像请求、扩展、bias、seed 与高级参数'},
]


TEXTGEN_SECTIONS = [
    {'id': 'length_and_output', 'label': '长度与输出', 'description': '输出长度、流式与输出行为'},
    {'id': 'core_sampling', 'label': '核心采样', 'description': '温度、Top P、Top K 等核心采样参数'},
    {'id': 'penalties', 'label': '惩罚', 'description': '重复、频率、存在和 ngram 惩罚'},
    {'id': 'dynamic_temperature', 'label': '动态温度', 'description': '动态温度开关与上下限'},
    {'id': 'mirostat_and_advanced', 'label': 'Mirostat 与高级采样', 'description': 'Mirostat、beam、CFG 等高级参数'},
    {'id': 'constraints_and_control', 'label': '约束与控制', 'description': '负面提示、grammar、schema 和 token 限制'},
    {'id': 'sampler_ordering', 'label': '采样器排序', 'description': '采样器顺序与优先级'},
    {'id': 'prompt_manager', 'label': '提示词管理', 'description': 'Prompt 顺序、启用状态与正文编辑'},
]


CHAT_COMPLETION_FIELDS = {
    'chat_completion_source': _field(
        'chat_completion_source',
        ['chat_completion_source'],
        section='provider_and_models',
        label='聊天补全来源',
        control='select',
        default='openai',
        options=[
            'openai',
            'custom',
            'ai21',
            'aimlapi',
            'azure_openai',
            'chutes',
            'claude',
            'workers_ai',
            'cohere',
            'cometapi',
            'deepseek',
            'electronhub',
            'fireworks',
            'groq',
            'makersuite',
            'vertexai',
            'mistralai',
            'minimax',
            'moonshot',
            'nanogpt',
            'openrouter',
            'perplexity',
            'pollinations',
            'siliconflow',
            'xai',
            'zai',
        ],
    ),
    'openai_model': _field(
        'openai_model',
        ['openai_model'],
        section='provider_and_models',
        label='OpenAI 模型',
        control='text',
    ),
    'openrouter_model': _field(
        'openrouter_model',
        ['openrouter_model'],
        section='provider_and_models',
        label='OpenRouter 模型',
        control='text',
    ),
    'custom_url': _field(
        'custom_url',
        ['custom_url'],
        section='connection_and_endpoints',
        label='自定义接口地址',
        control='text',
    ),
    'reverse_proxy': _field(
        'reverse_proxy',
        ['reverse_proxy'],
        section='connection_and_endpoints',
        label='反向代理',
        control='text',
    ),
    'proxy_password': _field(
        'proxy_password',
        ['proxy_password'],
        section='connection_and_endpoints',
        label='代理密码',
        control='password',
        sensitive=True,
    ),
    'openai_max_context': _field(
        'openai_max_context',
        ['openai_max_context'],
        section='output_and_reasoning',
        label='上下文长度',
        control='range_with_number',
        min_value=512,
        max_value={'type': 'dynamic', 'rule': 'chat_completion_context_limit', 'fallback': 4095},
        step=1,
        default=4095,
        reader_style='slider_snapshot',
    ),
    'openai_max_tokens': _field(
        'openai_max_tokens',
        ['openai_max_tokens'],
        section='output_and_reasoning',
        label='最大回复长度',
        control='range_with_number',
        min_value=1,
        max_value=128000,
        step=1,
        default=300,
        reader_style='slider_snapshot',
    ),
    'stream_openai': _field(
        'stream_openai',
        ['stream_openai'],
        section='output_and_reasoning',
        label='流式传输',
        control='checkbox',
        default=False,
    ),
    'show_thoughts': _field(
        'show_thoughts',
        ['show_thoughts'],
        section='output_and_reasoning',
        label='显示思维链',
        control='checkbox',
        default=True,
    ),
    'reasoning_effort': _field(
        'reasoning_effort',
        ['reasoning_effort'],
        section='output_and_reasoning',
        label='推理强度',
        control='select',
        default='auto',
        options=['auto', 'low', 'medium', 'high', 'min', 'max'],
    ),
    'verbosity': _field(
        'verbosity',
        ['verbosity'],
        section='output_and_reasoning',
        label='输出冗长度',
        control='select',
        default='auto',
        options=['auto', 'low', 'medium', 'high'],
        visibility_rule='present_or_core',
    ),
    'use_sysprompt': _field(
        'use_sysprompt',
        ['use_sysprompt'],
        section='templates_and_features',
        label='使用系统提示词',
        control='checkbox',
        default=False,
    ),
    'temperature': _field(
        'temperature',
        ['temperature', 'temp'],
        section='core_sampling',
        label='温度',
        control='range_with_number',
        min_value=0,
        max_value=2,
        step=0.01,
        default=1,
        reader_style='slider_snapshot',
    ),
    'top_p': _field(
        'top_p',
        ['top_p'],
        section='core_sampling',
        label='Top P',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.01,
        default=1,
        reader_style='slider_snapshot',
    ),
    'top_k': _field(
        'top_k',
        ['top_k'],
        section='core_sampling',
        label='Top K',
        control='range_with_number',
        min_value=0,
        max_value=500,
        step=1,
        default=0,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'top_a': _field(
        'top_a',
        ['top_a'],
        section='core_sampling',
        label='Top A',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        default=0,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'min_p': _field(
        'min_p',
        ['min_p'],
        section='core_sampling',
        label='Min P',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        default=0,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'frequency_penalty': _field(
        'frequency_penalty',
        ['frequency_penalty', 'freq_pen'],
        section='penalties_and_behavior',
        label='频率惩罚',
        control='range_with_number',
        min_value=-2,
        max_value=2,
        step=0.01,
        default=0,
        reader_style='slider_snapshot',
    ),
    'presence_penalty': _field(
        'presence_penalty',
        ['presence_penalty', 'pres_pen'],
        section='penalties_and_behavior',
        label='存在惩罚',
        control='range_with_number',
        min_value=-2,
        max_value=2,
        step=0.01,
        default=0,
        reader_style='slider_snapshot',
    ),
    'repetition_penalty': _field(
        'repetition_penalty',
        ['repetition_penalty', 'rep_pen'],
        section='penalties_and_behavior',
        label='重复惩罚',
        control='range_with_number',
        min_value=1,
        max_value=2,
        step=0.01,
        default=1,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'names_behavior': _field(
        'names_behavior',
        ['names_behavior'],
        section='penalties_and_behavior',
        label='名称行为',
        control='select',
        default=-1,
        options=[-1, 0, 1, 2],
    ),
    'prompts': _field(
        'prompts',
        ['prompts'],
        section='prompt_manager',
        label='Prompts',
        control='prompt_workspace',
        visibility_rule='core_only',
    ),
    'prompt_order': _field(
        'prompt_order',
        ['prompt_order'],
        section='prompt_manager',
        label='Prompt Order',
        control='prompt_workspace',
        visibility_rule='core_only',
    ),
    'wi_format': _field(
        'wi_format',
        ['wi_format'],
        section='templates_and_features',
        label='世界书格式',
        control='textarea',
        visibility_rule='present_or_core',
    ),
    'scenario_format': _field(
        'scenario_format',
        ['scenario_format'],
        section='templates_and_features',
        label='场景格式',
        control='textarea',
        visibility_rule='present_or_core',
    ),
    'personality_format': _field(
        'personality_format',
        ['personality_format'],
        section='templates_and_features',
        label='人格格式',
        control='textarea',
        visibility_rule='present_or_core',
    ),
    'assistant_prefill': _field(
        'assistant_prefill',
        ['assistant_prefill'],
        section='templates_and_features',
        label='Assistant Prefill',
        control='textarea',
        visibility_rule='present_only',
    ),
    'assistant_impersonation': _field(
        'assistant_impersonation',
        ['assistant_impersonation'],
        section='templates_and_features',
        label='Assistant Impersonation',
        control='textarea',
        visibility_rule='present_only',
    ),
    'impersonation_prompt': _field(
        'impersonation_prompt',
        ['impersonation_prompt'],
        section='templates_and_features',
        label='Impersonation Prompt',
        control='textarea',
        visibility_rule='present_only',
    ),
    'new_chat_prompt': _field(
        'new_chat_prompt',
        ['new_chat_prompt'],
        section='templates_and_features',
        label='New Chat Prompt',
        control='textarea',
        visibility_rule='present_or_core',
    ),
    'new_group_chat_prompt': _field(
        'new_group_chat_prompt',
        ['new_group_chat_prompt'],
        section='templates_and_features',
        label='New Group Chat Prompt',
        control='textarea',
        visibility_rule='present_only',
    ),
    'new_example_chat_prompt': _field(
        'new_example_chat_prompt',
        ['new_example_chat_prompt'],
        section='templates_and_features',
        label='New Example Chat Prompt',
        control='textarea',
        visibility_rule='present_only',
    ),
    'continue_nudge_prompt': _field(
        'continue_nudge_prompt',
        ['continue_nudge_prompt'],
        section='templates_and_features',
        label='Continue Nudge Prompt',
        control='textarea',
        visibility_rule='present_or_core',
    ),
    'group_nudge_prompt': _field(
        'group_nudge_prompt',
        ['group_nudge_prompt'],
        section='templates_and_features',
        label='Group Nudge Prompt',
        control='textarea',
        visibility_rule='present_only',
    ),
    'function_calling': _field(
        'function_calling',
        ['function_calling'],
        section='templates_and_features',
        label='函数调用',
        control='checkbox',
        default=False,
    ),
    'media_inlining': _field(
        'media_inlining',
        ['media_inlining'],
        section='images_and_advanced',
        label='媒体内联',
        control='checkbox',
        default=True,
    ),
    'request_images': _field(
        'request_images',
        ['request_images'],
        section='images_and_advanced',
        label='请求图像',
        control='checkbox',
        default=False,
    ),
    'request_image_aspect_ratio': _field(
        'request_image_aspect_ratio',
        ['request_image_aspect_ratio'],
        section='images_and_advanced',
        label='图像比例',
        control='select',
        options=['', '1:1', '9:16', '16:9', '3:4', '4:3', '3:2', '2:3', '5:4', '4:5', '21:9'],
    ),
    'request_image_resolution': _field(
        'request_image_resolution',
        ['request_image_resolution'],
        section='images_and_advanced',
        label='图像分辨率',
        control='select',
        options=['', '1K', '2K', '4K'],
    ),
    'extensions': _field(
        'extensions',
        ['extensions'],
        section='images_and_advanced',
        label='扩展',
        control='raw_json',
        visibility_rule='present_or_core',
    ),
    'logit_bias': _field(
        'logit_bias',
        ['logit_bias'],
        section='images_and_advanced',
        label='Logit Bias',
        control='key_value_list',
        visibility_rule='present_only',
    ),
    'seed': _field(
        'seed',
        ['seed'],
        section='images_and_advanced',
        label='Seed',
        control='number',
        min_value=-1,
        max_value=2147483647,
        step=1,
        visibility_rule='present_only',
    ),
    'n': _field(
        'n',
        ['n'],
        section='images_and_advanced',
        label='生成分支数',
        control='number',
        min_value=1,
        max_value=32,
        step=1,
        default=1,
        visibility_rule='present_only',
    ),
}


CHAT_COMPLETION_FIELDS.pop('logit_bias', None)


CHAT_COMPLETION_FIELDS.update(
    {
        'max_context_unlocked': _field(
            'max_context_unlocked',
            ['max_context_unlocked'],
            section='output_and_reasoning',
            label='解锁上下文上限',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'group_models': _field(
            'group_models',
            ['group_models', 'openrouter_group_models'],
            section='provider_and_models',
            label='按提供商分组模型',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'sort_models': _field(
            'sort_models',
            ['sort_models', 'openrouter_sort_models'],
            section='provider_and_models',
            label='模型排序',
            control='select',
            options=['alphabetically', 'pricing.prompt', 'pricing.completion', 'context_length'],
            visibility_rule='present_only',
        ),
        'claude_model': _field(
            'claude_model',
            ['claude_model'],
            section='provider_and_models',
            label='Claude 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'openrouter_use_fallback': _field(
            'openrouter_use_fallback',
            ['openrouter_use_fallback'],
            section='provider_and_models',
            label='OpenRouter 回退模型',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'openrouter_providers': _field(
            'openrouter_providers',
            ['openrouter_providers'],
            section='provider_and_models',
            label='OpenRouter 提供商',
            control='raw_json',
            visibility_rule='present_only',
        ),
        'openrouter_quantizations': _field(
            'openrouter_quantizations',
            ['openrouter_quantizations'],
            section='provider_and_models',
            label='OpenRouter 量化',
            control='raw_json',
            visibility_rule='present_only',
        ),
        'openrouter_allow_fallbacks': _field(
            'openrouter_allow_fallbacks',
            ['openrouter_allow_fallbacks'],
            section='provider_and_models',
            label='允许提供商回退',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'openrouter_middleout': _field(
            'openrouter_middleout',
            ['openrouter_middleout'],
            section='provider_and_models',
            label='OpenRouter Middle-out',
            control='select',
            options=['on', 'off', 'auto'],
            visibility_rule='present_only',
        ),
        'tool_reasoning_mode': _field(
            'tool_reasoning_mode',
            ['tool_reasoning_mode'],
            section='output_and_reasoning',
            label='工具调用推理模式',
            control='select',
            options=['disabled', 'since_last_user', 'active_chain'],
            visibility_rule='present_only',
        ),
        'ai21_model': _field(
            'ai21_model',
            ['ai21_model'],
            section='provider_and_models',
            label='AI21 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'mistralai_model': _field(
            'mistralai_model',
            ['mistralai_model'],
            section='provider_and_models',
            label='Mistral 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'cohere_model': _field(
            'cohere_model',
            ['cohere_model'],
            section='provider_and_models',
            label='Cohere 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'perplexity_model': _field(
            'perplexity_model',
            ['perplexity_model'],
            section='provider_and_models',
            label='Perplexity 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'groq_model': _field(
            'groq_model',
            ['groq_model'],
            section='provider_and_models',
            label='Groq 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'chutes_model': _field(
            'chutes_model',
            ['chutes_model'],
            section='provider_and_models',
            label='Chutes 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'siliconflow_model': _field(
            'siliconflow_model',
            ['siliconflow_model'],
            section='provider_and_models',
            label='SiliconFlow 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'siliconflow_endpoint': _field(
            'siliconflow_endpoint',
            ['siliconflow_endpoint'],
            section='connection_and_endpoints',
            label='SiliconFlow 端点',
            control='select',
            options=['global', 'cn'],
            visibility_rule='present_only',
        ),
        'minimax_model': _field(
            'minimax_model',
            ['minimax_model'],
            section='provider_and_models',
            label='MiniMax 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'minimax_endpoint': _field(
            'minimax_endpoint',
            ['minimax_endpoint'],
            section='connection_and_endpoints',
            label='MiniMax 端点',
            control='select',
            options=['global', 'cn'],
            visibility_rule='present_only',
        ),
        'electronhub_model': _field(
            'electronhub_model',
            ['electronhub_model'],
            section='provider_and_models',
            label='ElectronHub 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'nanogpt_model': _field(
            'nanogpt_model',
            ['nanogpt_model'],
            section='provider_and_models',
            label='NanoGPT 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'nanogpt_provider': _field(
            'nanogpt_provider',
            ['nanogpt_provider'],
            section='provider_and_models',
            label='NanoGPT 提供商',
            control='text',
            visibility_rule='present_only',
        ),
        'nanogpt_payg_override': _field(
            'nanogpt_payg_override',
            ['nanogpt_payg_override'],
            section='provider_and_models',
            label='NanoGPT 按量付费覆盖',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'deepseek_model': _field(
            'deepseek_model',
            ['deepseek_model'],
            section='provider_and_models',
            label='DeepSeek 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'aimlapi_model': _field(
            'aimlapi_model',
            ['aimlapi_model'],
            section='provider_and_models',
            label='AIML API 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'xai_model': _field(
            'xai_model',
            ['xai_model'],
            section='provider_and_models',
            label='xAI 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'pollinations_model': _field(
            'pollinations_model',
            ['pollinations_model'],
            section='provider_and_models',
            label='Pollinations 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'moonshot_model': _field(
            'moonshot_model',
            ['moonshot_model'],
            section='provider_and_models',
            label='Moonshot 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'fireworks_model': _field(
            'fireworks_model',
            ['fireworks_model'],
            section='provider_and_models',
            label='Fireworks 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'cometapi_model': _field(
            'cometapi_model',
            ['cometapi_model'],
            section='provider_and_models',
            label='CometAPI 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'custom_model': _field(
            'custom_model',
            ['custom_model'],
            section='provider_and_models',
            label='自定义模型',
            control='text',
            visibility_rule='present_only',
        ),
        'custom_include_body': _field(
            'custom_include_body',
            ['custom_include_body'],
            section='connection_and_endpoints',
            label='自定义请求体字段',
            control='textarea',
            visibility_rule='present_only',
        ),
        'custom_exclude_body': _field(
            'custom_exclude_body',
            ['custom_exclude_body'],
            section='connection_and_endpoints',
            label='自定义排除字段',
            control='textarea',
            visibility_rule='present_only',
        ),
        'custom_include_headers': _field(
            'custom_include_headers',
            ['custom_include_headers'],
            section='connection_and_endpoints',
            label='自定义请求头',
            control='textarea',
            visibility_rule='present_only',
        ),
        'custom_prompt_post_processing': _field(
            'custom_prompt_post_processing',
            ['custom_prompt_post_processing'],
            section='templates_and_features',
            label='自定义 Prompt 后处理',
            control='select',
            options=['', 'claude', 'merge', 'merge_tools', 'semi', 'semi_tools', 'strict', 'strict_tools', 'single'],
            visibility_rule='present_only',
        ),
        'google_model': _field(
            'google_model',
            ['google_model'],
            section='provider_and_models',
            label='Google 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'vertexai_model': _field(
            'vertexai_model',
            ['vertexai_model'],
            section='provider_and_models',
            label='Vertex AI 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'zai_model': _field(
            'zai_model',
            ['zai_model'],
            section='provider_and_models',
            label='Z.AI 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'zai_endpoint': _field(
            'zai_endpoint',
            ['zai_endpoint'],
            section='connection_and_endpoints',
            label='Z.AI 端点',
            control='select',
            options=['common', 'coding'],
            visibility_rule='present_only',
        ),
        'workers_ai_model': _field(
            'workers_ai_model',
            ['workers_ai_model'],
            section='provider_and_models',
            label='Workers AI 模型',
            control='text',
            visibility_rule='present_only',
        ),
        'workers_ai_account_id': _field(
            'workers_ai_account_id',
            ['workers_ai_account_id'],
            section='connection_and_endpoints',
            label='Workers AI 账户 ID',
            control='text',
            visibility_rule='present_only',
        ),
        'send_if_empty': _field(
            'send_if_empty',
            ['send_if_empty'],
            section='templates_and_features',
            label='空消息发送内容',
            control='textarea',
            visibility_rule='present_only',
        ),
        'bias_preset_selected': _field(
            'bias_preset_selected',
            ['bias_preset_selected'],
            section='images_and_advanced',
            label='Bias 预设',
            control='text',
            visibility_rule='present_only',
        ),
        'show_external_models': _field(
            'show_external_models',
            ['show_external_models'],
            section='provider_and_models',
            label='显示外部模型',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'vertexai_auth_mode': _field(
            'vertexai_auth_mode',
            ['vertexai_auth_mode'],
            section='connection_and_endpoints',
            label='Vertex AI 鉴权模式',
            control='select',
            options=['express', 'full'],
            visibility_rule='present_only',
        ),
        'vertexai_region': _field(
            'vertexai_region',
            ['vertexai_region'],
            section='connection_and_endpoints',
            label='Vertex AI 区域',
            control='text',
            visibility_rule='present_only',
        ),
        'vertexai_express_project_id': _field(
            'vertexai_express_project_id',
            ['vertexai_express_project_id'],
            section='connection_and_endpoints',
            label='Vertex AI 项目 ID',
            control='text',
            visibility_rule='present_only',
        ),
        'squash_system_messages': _field(
            'squash_system_messages',
            ['squash_system_messages'],
            section='templates_and_features',
            label='合并连续系统消息',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'inline_image_quality': _field(
            'inline_image_quality',
            ['inline_image_quality'],
            section='images_and_advanced',
            label='内联图像质量',
            control='select',
            options=['auto', 'low', 'high'],
            visibility_rule='present_only',
        ),
        'continue_prefill': _field(
            'continue_prefill',
            ['continue_prefill'],
            section='templates_and_features',
            label='继续生成预填充',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'continue_postfix': _field(
            'continue_postfix',
            ['continue_postfix'],
            section='templates_and_features',
            label='继续生成后缀',
            control='select',
            options=['', ' ', '\n', '\n\n'],
            visibility_rule='present_only',
        ),
        'tool_call_recurse_limit': _field(
            'tool_call_recurse_limit',
            ['tool_call_recurse_limit'],
            section='output_and_reasoning',
            label='工具调用递归上限',
            control='number',
            min_value=1,
            max_value=50,
            step=1,
            visibility_rule='present_only',
        ),
        'enable_web_search': _field(
            'enable_web_search',
            ['enable_web_search'],
            section='images_and_advanced',
            label='启用联网搜索',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'bypass_status_check': _field(
            'bypass_status_check',
            ['bypass_status_check'],
            section='connection_and_endpoints',
            label='跳过连接状态检查',
            control='checkbox',
            visibility_rule='present_only',
        ),
        'azure_base_url': _field(
            'azure_base_url',
            ['azure_base_url'],
            section='connection_and_endpoints',
            label='Azure OpenAI 地址',
            control='text',
            visibility_rule='present_only',
        ),
        'azure_deployment_name': _field(
            'azure_deployment_name',
            ['azure_deployment_name'],
            section='connection_and_endpoints',
            label='Azure 部署名称',
            control='text',
            visibility_rule='present_only',
        ),
        'azure_api_version': _field(
            'azure_api_version',
            ['azure_api_version'],
            section='connection_and_endpoints',
            label='Azure API 版本',
            control='text',
            visibility_rule='present_only',
        ),
        'azure_openai_model': _field(
            'azure_openai_model',
            ['azure_openai_model'],
            section='provider_and_models',
            label='Azure OpenAI 模型',
            control='text',
            visibility_rule='present_only',
        ),
    }
)


for _sensitive_key in {
    'reverse_proxy',
    'proxy_password',
    'custom_url',
    'custom_include_body',
    'custom_exclude_body',
    'custom_include_headers',
    'vertexai_region',
    'vertexai_express_project_id',
    'azure_base_url',
    'azure_deployment_name',
    'workers_ai_account_id',
}:
    if _sensitive_key in CHAT_COMPLETION_FIELDS:
        CHAT_COMPLETION_FIELDS[_sensitive_key]['sensitive'] = True


TEXTGEN_FIELDS = {
    'max_length': _field(
        'max_length',
        ['max_length', 'max_tokens', 'openai_max_tokens'],
        section='length_and_output',
        label='最大生成长度',
        control='range_with_number',
        min_value=1,
        max_value=131072,
        step=1,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'min_length': _field(
        'min_length',
        ['min_length'],
        section='length_and_output',
        label='最小长度',
        control='number',
        min_value=0,
        max_value=131072,
        step=1,
        visibility_rule='present_only',
    ),
    'streaming': _field(
        'streaming',
        ['streaming'],
        section='length_and_output',
        label='流式传输',
        control='checkbox',
        default=False,
        visibility_rule='present_or_core',
    ),
    'include_reasoning': _field(
        'include_reasoning',
        ['include_reasoning'],
        section='length_and_output',
        label='输出推理内容',
        control='checkbox',
        visibility_rule='present_only',
    ),
    'temp': _field(
        'temp',
        ['temp', 'temperature'],
        section='core_sampling',
        label='温度',
        control='range_with_number',
        min_value=0,
        max_value=5,
        step=0.01,
        default=1,
        reader_style='slider_snapshot',
    ),
    'top_p': _field(
        'top_p',
        ['top_p'],
        section='core_sampling',
        label='Top P',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.01,
        default=1,
        reader_style='slider_snapshot',
    ),
    'top_k': _field(
        'top_k',
        ['top_k'],
        section='core_sampling',
        label='Top K',
        control='range_with_number',
        min_value=0,
        max_value=500,
        step=1,
        default=0,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'top_a': _field(
        'top_a',
        ['top_a'],
        section='core_sampling',
        label='Top A',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        default=0,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'min_p': _field(
        'min_p',
        ['min_p'],
        section='core_sampling',
        label='Min P',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        default=0,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'typical_p': _field(
        'typical_p',
        ['typical_p', 'typical'],
        section='core_sampling',
        label='Typical P',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'tfs': _field(
        'tfs',
        ['tfs'],
        section='core_sampling',
        label='TFS',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.001,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'rep_pen': _field(
        'rep_pen',
        ['rep_pen', 'repetition_penalty'],
        section='penalties',
        label='重复惩罚',
        control='range_with_number',
        min_value=1,
        max_value=3,
        step=0.01,
        default=1,
        reader_style='slider_snapshot',
    ),
    'freq_pen': _field(
        'freq_pen',
        ['freq_pen', 'frequency_penalty'],
        section='penalties',
        label='频率惩罚',
        control='range_with_number',
        min_value=-2,
        max_value=2,
        step=0.01,
        default=0,
        reader_style='slider_snapshot',
    ),
    'pres_pen': _field(
        'pres_pen',
        ['pres_pen', 'presence_penalty'],
        section='penalties',
        label='存在惩罚',
        control='range_with_number',
        min_value=-2,
        max_value=2,
        step=0.01,
        default=0,
        reader_style='slider_snapshot',
    ),
    'no_repeat_ngram_size': _field(
        'no_repeat_ngram_size',
        ['no_repeat_ngram_size'],
        section='penalties',
        label='No Repeat Ngram',
        control='number',
        min_value=0,
        max_value=64,
        step=1,
        visibility_rule='present_only',
    ),
    'dynatemp': _field(
        'dynatemp',
        ['dynatemp', 'dynamic_temperature'],
        section='dynamic_temperature',
        label='动态温度',
        control='checkbox',
        visibility_rule='present_or_core',
    ),
    'min_temp': _field(
        'min_temp',
        ['min_temp', 'dynatemp_low'],
        section='dynamic_temperature',
        label='动态温度下限',
        control='range_with_number',
        min_value=0,
        max_value=5,
        step=0.01,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'max_temp': _field(
        'max_temp',
        ['max_temp', 'dynatemp_high'],
        section='dynamic_temperature',
        label='动态温度上限',
        control='range_with_number',
        min_value=0,
        max_value=5,
        step=0.01,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'mirostat_mode': _field(
        'mirostat_mode',
        ['mirostat_mode'],
        section='mirostat_and_advanced',
        label='Mirostat 模式',
        control='number',
        min_value=0,
        max_value=2,
        step=1,
        visibility_rule='present_or_core',
    ),
    'mirostat_tau': _field(
        'mirostat_tau',
        ['mirostat_tau'],
        section='mirostat_and_advanced',
        label='Mirostat Tau',
        control='range_with_number',
        min_value=0,
        max_value=10,
        step=0.01,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'mirostat_eta': _field(
        'mirostat_eta',
        ['mirostat_eta'],
        section='mirostat_and_advanced',
        label='Mirostat Eta',
        control='range_with_number',
        min_value=0,
        max_value=1,
        step=0.01,
        visibility_rule='present_or_core',
        reader_style='slider_snapshot',
    ),
    'guidance_scale': _field(
        'guidance_scale',
        ['guidance_scale'],
        section='mirostat_and_advanced',
        label='Guidance Scale',
        control='range_with_number',
        min_value=0,
        max_value=10,
        step=0.01,
        visibility_rule='present_only',
        reader_style='slider_snapshot',
    ),
    'negative_prompt': _field(
        'negative_prompt',
        ['negative_prompt'],
        section='constraints_and_control',
        label='Negative Prompt',
        control='textarea',
        visibility_rule='present_only',
    ),
    'grammar': _field(
        'grammar',
        ['grammar', 'grammar_string'],
        section='constraints_and_control',
        label='Grammar',
        control='textarea',
        visibility_rule='present_only',
    ),
    'json_schema': _field(
        'json_schema',
        ['json_schema'],
        section='constraints_and_control',
        label='JSON Schema',
        control='textarea',
        visibility_rule='present_only',
    ),
    'banned_tokens': _field(
        'banned_tokens',
        ['banned_tokens'],
        section='constraints_and_control',
        label='禁词',
        control='textarea',
        visibility_rule='present_only',
    ),
    'logit_bias': _field(
        'logit_bias',
        ['logit_bias'],
        section='constraints_and_control',
        label='Logit Bias',
        control='key_value_list',
        visibility_rule='present_only',
    ),
    'sampler_order': _field(
        'sampler_order',
        ['sampler_order'],
        section='sampler_ordering',
        label='Sampler Order',
        control='sortable_string_list',
        visibility_rule='present_only',
    ),
    'samplers': _field(
        'samplers',
        ['samplers'],
        section='sampler_ordering',
        label='Sampler Priority',
        control='sortable_string_list',
        visibility_rule='present_only',
    ),
    'prompts': _field(
        'prompts',
        ['prompts'],
        section='prompt_manager',
        label='Prompts',
        control='prompt_workspace',
        visibility_rule='core_only',
    ),
    'prompt_order': _field(
        'prompt_order',
        ['prompt_order'],
        section='prompt_manager',
        label='Prompt Order',
        control='prompt_workspace',
        visibility_rule='core_only',
    ),
}


PROFILE_REGISTRY = {
    CHAT_COMPLETION_PROFILE_ID: {
        'id': CHAT_COMPLETION_PROFILE_ID,
        'label': 'ST 聊天补全预设',
        'family': 'st_mirror',
        'supports_prompt_workspace': True,
        'reader_layout': 'mirrored_sections',
        'save_target': 'st_openai_preset_dir',
        'sections': CHAT_COMPLETION_SECTIONS,
        'fields': CHAT_COMPLETION_FIELDS,
    },
    GENERIC_PROFILE_ID: {
        'id': GENERIC_PROFILE_ID,
        'label': 'Generic JSON',
        'family': 'generic',
        'supports_prompt_workspace': False,
        'reader_layout': 'generic',
        'save_target': 'presets_dir',
        'sections': [],
        'fields': {},
    },
}


def _resolve_source_key(data, storage_keys):
    for storage_key in storage_keys:
        if storage_key in data:
            return storage_key
    return None


def _iter_field_lookup_keys(field_def):
    seen = set()
    for key in [field_def['canonical_key'], *field_def.get('storage_keys', [])]:
        if key in seen:
            continue
        seen.add(key)
        yield key


def _resolve_field_def(profile_def, key):
    for field_def in profile_def.get('fields', {}).values():
        if key in set(_iter_field_lookup_keys(field_def)):
            return field_def
    return None


def _clamp_numeric_value(value, min_value=None, max_value=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if isinstance(min_value, (int, float)):
        value = max(value, min_value)
    if isinstance(max_value, (int, float)):
        value = min(value, max_value)
    return value


def _resolve_dynamic_max_value(max_value, current_value, incoming_value=None):
    if not isinstance(max_value, dict):
        return max_value
    if max_value.get('type') != 'dynamic':
        return None

    fallback = max_value.get('fallback', 4095)
    if isinstance(current_value, (int, float)) and not isinstance(current_value, bool):
        return max(current_value, fallback)
    if isinstance(incoming_value, (int, float)) and not isinstance(incoming_value, bool):
        return max(incoming_value, fallback)
    return fallback


def detect_editor_profile_id(raw_data, preset_kind):
    data = raw_data if isinstance(raw_data, dict) else {}
    if preset_kind == 'openai':
        return CHAT_COMPLETION_PROFILE_ID
    if preset_kind == 'generic':
        return GENERIC_PROFILE_ID
    if any(field in data for field in CHAT_COMPLETION_MARKER_FIELDS):
        return CHAT_COMPLETION_PROFILE_ID
    if isinstance(data.get('prompts'), list):
        return CHAT_COMPLETION_PROFILE_ID
    return GENERIC_PROFILE_ID


def get_editor_profile_definition(raw_data, preset_kind):
    profile_id = detect_editor_profile_id(raw_data, preset_kind)
    return PROFILE_REGISTRY[profile_id]


def resolve_profile_storage_key(raw_data, preset_kind, incoming_key):
    data = raw_data if isinstance(raw_data, dict) else {}
    field_def = _resolve_field_def(get_editor_profile_definition(data, preset_kind), incoming_key)
    if field_def is None:
        return incoming_key
    return _resolve_source_key(data, field_def.get('storage_keys', [])) or field_def['storage_keys'][0]


def resolve_profile_remove_keys(raw_data, preset_kind, content):
    source_data = raw_data if isinstance(raw_data, dict) else {}
    incoming_content = content if isinstance(content, dict) else {}
    profile_data = dict(source_data)
    profile_data.update(incoming_content)
    profile_def = get_editor_profile_definition(profile_data, preset_kind)
    if not profile_def.get('fields'):
        return []

    remove_keys = set()
    for key in incoming_content.keys():
        field_def = _resolve_field_def(profile_def, key)
        if field_def is None:
            continue

        target_key = _resolve_source_key(source_data, field_def.get('storage_keys', [])) or field_def['storage_keys'][0]
        for lookup_key in _iter_field_lookup_keys(field_def):
            if lookup_key != target_key and lookup_key in source_data:
                remove_keys.add(lookup_key)

    return sorted(remove_keys)


def normalize_preset_content_for_save(raw_data, preset_kind, content):
    source_data = raw_data if isinstance(raw_data, dict) else {}
    normalized = copy.deepcopy(content or {})
    profile_data = dict(source_data)
    if isinstance(normalized, dict):
        profile_data.update(normalized)
    profile_id = detect_editor_profile_id(profile_data, preset_kind)
    profile_def = PROFILE_REGISTRY[profile_id]
    if not profile_def.get('fields'):
        return normalized

    filtered = {}

    for key in list(normalized.keys()):
        field_def = _resolve_field_def(profile_def, key)
        if field_def is None:
            if key == MANAGED_PRESET_KIND_KEY:
                continue
            if key in ALLOWED_PASSTHROUGH_SAVE_KEYS:
                filtered[key] = copy.deepcopy(normalized[key])
                continue
            if profile_id == CHAT_COMPLETION_PROFILE_ID and key not in OPENAI_RUNTIME_ONLY_SAVE_KEYS:
                filtered[key] = copy.deepcopy(normalized[key])
            continue

        value = normalized[key]
        current_key = _resolve_source_key(source_data, field_def.get('storage_keys', []))
        current_value = source_data.get(current_key) if current_key else None

        options = field_def.get('options')
        if isinstance(options, list) and value not in options:
            if current_value in options:
                filtered[key] = current_value
            continue

        filtered[key] = _clamp_numeric_value(
            value,
            min_value=field_def.get('min'),
            max_value=_resolve_dynamic_max_value(
                field_def.get('max'),
                current_value,
                value if not source_data else None,
            ),
        )

    return filtered


def resolve_global_save_dir_config_key(raw_data, preset_kind):
    profile_id = detect_editor_profile_id(raw_data if isinstance(raw_data, dict) else {}, preset_kind)
    return PROFILE_REGISTRY.get(profile_id, PROFILE_REGISTRY[GENERIC_PROFILE_ID]).get('save_target', 'presets_dir')


def build_editor_profile_payload(raw_data, preset_kind):
    data = raw_data if isinstance(raw_data, dict) else {}
    profile_def = get_editor_profile_definition(data, preset_kind)

    fields = {}
    for canonical_key, field_def in profile_def.get('fields', {}).items():
        source_key = _resolve_source_key(data, field_def['storage_keys'])
        if field_def.get('visibility_rule') == 'present_only' and source_key is None:
            continue
        resolved_key = source_key or canonical_key
        field_payload = copy.deepcopy(field_def)
        field_payload['id'] = canonical_key
        field_payload['storage_key'] = resolved_key
        field_payload['source_key'] = source_key
        fields[canonical_key] = field_payload

    return {
        'id': profile_def['id'],
        'label': profile_def['label'],
        'family': profile_def.get('family', 'generic'),
        'supports_prompt_workspace': profile_def.get('supports_prompt_workspace', False),
        'save_target': profile_def.get('save_target', 'presets_dir'),
        'reader_layout': profile_def.get('reader_layout', 'generic'),
        'sections': copy.deepcopy(profile_def.get('sections', [])),
        'fields': fields,
    }
