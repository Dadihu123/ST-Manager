import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.services.preset_editor_schema import CHAT_COMPLETION_FIELDS
from core.services.preset_editor_schema import build_editor_profile_payload


ST_SETTINGS_TO_UPDATE_KEYS = {
    'chat_completion_source', 'temperature', 'frequency_penalty', 'presence_penalty',
    'top_p', 'top_k', 'top_a', 'min_p', 'repetition_penalty', 'max_context_unlocked',
    'group_models', 'sort_models', 'openai_model', 'claude_model', 'openrouter_model',
    'openrouter_use_fallback', 'openrouter_providers', 'openrouter_quantizations',
    'openrouter_allow_fallbacks', 'openrouter_middleout', 'tool_reasoning_mode',
    'ai21_model', 'mistralai_model', 'cohere_model', 'perplexity_model', 'groq_model',
    'chutes_model', 'siliconflow_model', 'siliconflow_endpoint', 'minimax_model',
    'minimax_endpoint', 'electronhub_model', 'nanogpt_model', 'nanogpt_provider',
    'nanogpt_payg_override', 'deepseek_model', 'aimlapi_model', 'xai_model',
    'pollinations_model', 'moonshot_model', 'fireworks_model', 'cometapi_model',
    'custom_model', 'custom_url', 'custom_include_body', 'custom_exclude_body',
    'custom_include_headers', 'custom_prompt_post_processing', 'google_model',
    'vertexai_model', 'zai_model', 'zai_endpoint', 'workers_ai_model',
    'workers_ai_account_id', 'openai_max_context', 'openai_max_tokens', 'names_behavior',
    'send_if_empty', 'impersonation_prompt', 'new_chat_prompt', 'new_group_chat_prompt',
    'new_example_chat_prompt', 'continue_nudge_prompt', 'bias_preset_selected',
    'reverse_proxy', 'wi_format', 'scenario_format', 'personality_format',
    'group_nudge_prompt', 'stream_openai', 'prompts', 'prompt_order', 'show_external_models',
    'proxy_password', 'assistant_prefill', 'assistant_impersonation', 'use_sysprompt',
    'vertexai_auth_mode', 'vertexai_region', 'vertexai_express_project_id',
    'squash_system_messages', 'media_inlining', 'inline_image_quality', 'continue_prefill',
    'continue_postfix', 'function_calling', 'tool_call_recurse_limit', 'show_thoughts',
    'reasoning_effort', 'verbosity', 'enable_web_search', 'seed', 'n', 'bypass_status_check',
    'request_images', 'request_image_aspect_ratio', 'request_image_resolution',
    'azure_base_url', 'azure_deployment_name', 'azure_api_version', 'azure_openai_model',
    'extensions',
}


def test_openai_schema_matches_settings_to_update_registry_exactly():
    assert set(CHAT_COMPLETION_FIELDS) == ST_SETTINGS_TO_UPDATE_KEYS
    assert 'logit_bias' not in CHAT_COMPLETION_FIELDS


def test_openai_schema_masks_connection_values_and_matches_st_option_values():
    profile = build_editor_profile_payload(
        {
            'proxy_password': 'secret',
            'custom_url': 'https://example.test',
            'deepseek_model': 'deepseek-chat',
            'continue_postfix': ' ',
            'inline_image_quality': 'auto',
            'vertexai_auth_mode': 'express',
        },
        'openai',
    )

    assert profile['fields']['proxy_password']['sensitive'] is True
    assert profile['fields']['custom_url']['sensitive'] is True
    assert profile['fields']['deepseek_model']['source_key'] == 'deepseek_model'
    assert profile['fields']['chat_completion_source']['options'] == [
        'openai', 'custom', 'ai21', 'aimlapi', 'azure_openai', 'chutes', 'claude',
        'workers_ai', 'cohere', 'cometapi', 'deepseek', 'electronhub', 'fireworks',
        'groq', 'makersuite', 'vertexai', 'mistralai', 'minimax', 'moonshot', 'nanogpt',
        'openrouter', 'perplexity', 'pollinations', 'siliconflow', 'xai', 'zai',
    ]
    assert profile['fields']['names_behavior']['options'] == [-1, 0, 1, 2]
    assert profile['fields']['continue_postfix']['options'] == ['', ' ', '\n', '\n\n']
    assert profile['fields']['inline_image_quality']['options'] == ['auto', 'low', 'high']
    assert profile['fields']['vertexai_auth_mode']['options'] == ['express', 'full']


def test_openai_schema_exposes_required_st_alignment_field_subset():
    profile = build_editor_profile_payload({}, 'openai')

    assert profile['id'] == 'st_chat_completion_preset'
    assert set(profile['fields']) >= {
        'chat_completion_source',
        'openai_model',
        'openrouter_model',
        'custom_url',
        'reverse_proxy',
        'proxy_password',
        'openai_max_context',
        'openai_max_tokens',
        'names_behavior',
        'use_sysprompt',
        'show_thoughts',
        'reasoning_effort',
        'verbosity',
        'function_calling',
        'media_inlining',
        'request_images',
        'request_image_aspect_ratio',
        'request_image_resolution',
        'prompts',
        'prompt_order',
        'extensions',
    }
    assert profile['fields']['use_sysprompt']['section'] == 'templates_and_features'
    assert profile['fields']['media_inlining']['section'] == 'images_and_advanced'
    assert set(profile['fields']['chat_completion_source']['options']) >= {
        'openai',
        'openrouter',
        'custom',
        'claude',
        'azure_openai',
        'zai',
    }
