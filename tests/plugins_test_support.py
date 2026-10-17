"""插件系统测试的共用夹具工具（不以 test_ 开头，pytest 不会收集）。"""

import json
import os

DEFAULT_BACKEND_SOURCE = '''\
from flask import jsonify


def register(api):
    @api.http.route('/ping', ['GET'])
    def ping():
        return jsonify({'success': True, 'pong': True, 'plugin': api.plugin_id})
'''

DEFAULT_FRONTEND_SOURCE = '''\
export function activate(api) {
  return null;
}
'''

def default_css(plugin_id):
    """默认的作用域合规样式（F11 检查通过）。"""
    return f'.plugin-{plugin_id} {{\n  color: inherit;\n}}\n'


def clear_plugin_ui_namespace():
    """清空 ui_data 中的插件命名空间（测试间隔离，避免 enabled/load_error 互相污染）。

    同时清掉入口布局偏好（`_entry_layout_v1`）：它也是插件系统的宿主持久化状态，
    若不清会让用例之间互相看到对方的 pinned/hidden，产生顺序依赖的假失败。
    """
    from core.data.ui_store import ENTRY_LAYOUT_KEY, update_ui_data

    def mutator(ui_data):
        ui_data.pop('_plugins_v1', None)
        ui_data.pop(ENTRY_LAYOUT_KEY, None)

    return update_ui_data(mutator)


def base_manifest(plugin_id, **overrides):
    payload = {
        'id': plugin_id,
        'name': f'{plugin_id} 测试插件',
        'version': '0.1.0',
        'api_version': 1,
        'author': 'tests',
        'description': '单元测试夹具',
        'backend': {
            'entry': 'backend',
            'register': 'register',
            'jobs': ['demo.run'],
            'hooks': ['card.updated'],
        },
        'frontend': {
            'entry': 'frontend/plugin.js',
            'styles': ['frontend/plugin.css'],
        },
        'permissions': ['cards.read'],
        'config_schema': {
            'type': 'object',
            'properties': {
                'greeting': {'type': 'string', 'title': '问候语', 'default': 'hi'},
                'count': {'type': 'integer', 'title': '数量', 'default': 3, 'minimum': 1, 'maximum': 9},
            },
        },
        'secret_schema': {
            'type': 'object',
            'properties': {
                'api_key': {'type': 'string', 'title': 'API Key', 'secret': True},
                'base_url': {'type': 'string', 'title': 'API 地址', 'default': 'https://example.com/v1'},
            },
        },
    }
    payload.update(overrides)
    return payload


def write_plugin(
    root,
    plugin_id='demo-plugin',
    *,
    manifest=None,
    backend=DEFAULT_BACKEND_SOURCE,
    frontend=DEFAULT_FRONTEND_SOURCE,
    css=None,
):
    """在 root 下生成一个结构完整的插件目录，返回插件根路径。"""
    plugin_dir = os.path.join(str(root), plugin_id)
    os.makedirs(plugin_dir, exist_ok=True)

    payload = base_manifest(plugin_id) if manifest is None else manifest
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    if backend is not None:
        os.makedirs(os.path.join(plugin_dir, 'backend'), exist_ok=True)
        with open(os.path.join(plugin_dir, 'backend', '__init__.py'), 'w', encoding='utf-8') as handle:
            handle.write(backend)

    if frontend is not None:
        os.makedirs(os.path.join(plugin_dir, 'frontend'), exist_ok=True)
        with open(os.path.join(plugin_dir, 'frontend', 'plugin.js'), 'w', encoding='utf-8') as handle:
            handle.write(frontend)

        style_source = default_css(plugin_id) if css is None else css
        if style_source is not None:
            with open(os.path.join(plugin_dir, 'frontend', 'plugin.css'), 'w', encoding='utf-8') as handle:
                handle.write(style_source)

    return plugin_dir


def write_card(cards_root, card_id, *, name='测试卡片', tags=None, description='desc'):
    """写一张可被 `extract_card_info` 解析的 V3 JSON 角色卡。"""
    full_path = os.path.join(str(cards_root), card_id.replace('/', os.sep))
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    payload = {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'name': name,
        'data': {
            'name': name,
            'description': description,
            'first_mes': '你好',
            'mes_example': '',
            'creator': 'tests',
            'character_version': '1.0',
            'tags': list(tags or []),
        },
    }
    with open(full_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return full_path
