"""Hello World 示例插件（阶段 0 验收夹具）。

演示 PluginAPI 的基本用法：
- `api.route()` 注册插件路由（自动加 `/api/plugins/hello-world` 前缀）
- `api.on()` 订阅核心事件
- `api.migrate()` 建一张带 `plugin_hello-world_` 前缀的私有表
- `api.get_config()` / `api.get_secret()` 读取配置与密钥

注意：插件内部只能使用相对导入，不要写 `import backend`。
"""

import time

from flask import jsonify, request


def register(api):
    """插件入口（manifest.backend.register 指定的函数名）。"""

    @api.route('/ping', ['GET'])
    def ping():
        config = api.get_config()
        return jsonify({
            'success': True,
            'pong': True,
            'plugin': api.plugin_id,
            'version': api.manifest.get('version', ''),
            'greeting': config.get('greeting', ''),
            'has_api_key': bool(api.get_secret('api_key')),
            'timestamp': time.time(),
        })

    @api.route('/echo', ['POST'])
    def echo():
        payload = request.get_json(silent=True) or {}
        return jsonify({'success': True, 'echo': payload})

    def on_card_updated(payload):
        api.log('info', f"收到 card.updated: {payload.get('card_id', '')}")

    api.on('card.updated', on_card_updated)

    api.migrate([
        '''
        CREATE TABLE IF NOT EXISTS plugin_hello_world_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visited_at REAL
        )
        ''',
    ])

    api.log('info', 'hello-world 插件已注册')
