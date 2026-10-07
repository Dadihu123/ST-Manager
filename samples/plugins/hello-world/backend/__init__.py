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

    def run_count_job(ctx):
        """demo.count：逐项处理，演示进度上报、协作式取消与失败重试。"""
        total = len(ctx.items)
        ctx.set_total(total)
        for index, item in enumerate(ctx.items, start=1):
            if ctx.should_cancel():
                ctx.log('warning', f'收到取消请求，已在第 {index - 1}/{total} 项停下')
                return

            key = item['key']
            time.sleep(0.002)  # 模拟逐项耗时
            if item['payload'].get('fail'):
                ctx.report(key, status='failed', error='示例失败：可在面板里「只重跑失败项」')
            else:
                ctx.report(key, status='done', result={'index': index, 'value': key})

        ctx.set_summary({'handled': total})
        ctx.set_message(f'已处理 {total} 项')

    api.register_job('demo.count', run_count_job)

    def cli_hello(namespace):
        """CLI 子命令：python app.py plugin hello-world hello <名字> --times N"""
        target = namespace.args[0] if namespace.args else 'world'
        try:
            times = max(1, int(namespace.options.get('times', 1)))
        except (TypeError, ValueError):
            times = 1

        for _ in range(times):
            print(f'Hello, {target}!')
        return 0

    api.register_cli('hello', cli_hello, description='打印 Hello 问候（位置参数: 名字；--times N）')

    api.migrate([
        '''
        CREATE TABLE IF NOT EXISTS plugin_hello_world_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visited_at REAL
        )
        ''',
    ])

    api.log('info', 'hello-world 插件已注册')
