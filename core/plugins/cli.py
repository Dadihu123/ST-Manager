"""插件 CLI 子命令（设计文档 N2）。

契约（见设计文档 10.2 与附录 I）：

- 插件在 `register(api)` 中调用 `api.register_cli(name, handler, description='')`；
  `name` 匹配 `^[a-z][a-z0-9-]{0,31}$`，只在本插件命名空间内寻址。
- `handler` 接收一个 `argparse.Namespace`，字段约定：
  - `namespace.args`：位置参数列表（原样，未做类型转换）
  - `namespace.options`：`--key value` / `--key=value` / `--flag` 的解析结果（dict）
  - 同时把每个选项展开为属性（`--model x` → `namespace.model == 'x'`，连字符转下划线）
- `handler` 返回 `int | None`：`None` 视为 0，`True`→0、`False`→1，其余整数原样作为退出码。

入口：

```powershell
python app.py plugin <plugin_id> --list
python app.py plugin <plugin_id> <command> [args...] [--key value]
```
"""

import argparse
import logging
import os
import re
import sys
import threading

from core.plugins import registry
from core.plugins.errors import PluginCliError

logger = logging.getLogger(__name__)

PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
CLI_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9-]{0,31}$')

_cli_lock = threading.RLock()
_cli_commands = {}


def register_cli(plugin_id: str, name: str, handler, description: str = '') -> None:
    """注册一个插件 CLI 子命令（同名重复注册会被覆盖）。"""
    plugin_id = str(plugin_id or '').strip()
    name = str(name or '').strip()

    if not PLUGIN_ID_PATTERN.match(plugin_id):
        raise ValueError(f'插件 id 非法: {plugin_id!r}')
    if not CLI_NAME_PATTERN.match(name):
        raise ValueError(f'CLI 子命令名必须匹配 {CLI_NAME_PATTERN.pattern}: {name!r}')
    if not callable(handler):
        raise ValueError('CLI handler 必须可调用')

    with _cli_lock:
        _cli_commands[(plugin_id, name)] = {
            'plugin_id': plugin_id,
            'name': name,
            'handler': handler,
            'description': str(description or '').strip(),
        }


def list_commands(plugin_id: str) -> list:
    """某个插件注册的子命令（按名称排序）。"""
    plugin_id = str(plugin_id or '').strip()
    with _cli_lock:
        entries = [
            {'name': item['name'], 'description': item['description']}
            for (owner, _name), item in _cli_commands.items()
            if owner == plugin_id
        ]
    return sorted(entries, key=lambda item: item['name'])


def all_commands() -> list:
    """全部已注册的子命令（跨插件）。"""
    with _cli_lock:
        return sorted(
            (
                {'plugin_id': item['plugin_id'], 'name': item['name'], 'description': item['description']}
                for item in _cli_commands.values()
            ),
            key=lambda item: (item['plugin_id'], item['name']),
        )


def get_command(plugin_id: str, name: str):
    """取单个命令条目；不存在返回 None。"""
    with _cli_lock:
        return _cli_commands.get((str(plugin_id or '').strip(), str(name or '').strip()))


def unregister_plugin(plugin_id: str) -> int:
    """移除某个插件的全部子命令，返回移除数量。"""
    plugin_id = str(plugin_id or '').strip()
    with _cli_lock:
        keys = [key for key in _cli_commands if key[0] == plugin_id]
        for key in keys:
            _cli_commands.pop(key, None)
    return len(keys)


def reset_for_tests() -> None:
    with _cli_lock:
        _cli_commands.clear()


def build_namespace(argv) -> argparse.Namespace:
    """把原始参数拆成 `args`（位置参数）与 `options`（简易选项）。

    支持 `--key value`、`--key=value`、`--flag`（值为 True）；`--` 之后的
    内容一律作为位置参数。插件无需声明参数表即可自行解释。
    """
    items = [str(item) for item in (argv or [])]
    positional = []
    options = {}

    index = 0
    while index < len(items):
        item = items[index]
        if item == '--':
            positional.extend(items[index + 1:])
            break
        if item.startswith('--') and len(item) > 2:
            body = item[2:]
            if '=' in body:
                key, value = body.split('=', 1)
                options[key] = value
            else:
                following = items[index + 1] if index + 1 < len(items) else ''
                if following and not following.startswith('--'):
                    options[body] = following
                    index += 1
                else:
                    options[body] = True
        else:
            positional.append(item)
        index += 1

    namespace = argparse.Namespace()
    namespace.args = positional
    namespace.options = options
    for key, value in options.items():
        setattr(namespace, key.replace('-', '_'), value)
    return namespace


def run_plugin_command(plugin_id: str, name: str, argv=None) -> int:
    """执行一个已注册的子命令，返回退出码。"""
    entry = get_command(plugin_id, name)
    if entry is None:
        available = ', '.join(item['name'] for item in list_commands(plugin_id)) or '（无）'
        raise PluginCliError(f'插件 {plugin_id} 没有子命令 {name!r}；可用: {available}')

    namespace = build_namespace(argv)
    result = entry['handler'](namespace)

    if result is None:
        return 0
    if isinstance(result, bool):
        return 0 if result else 1
    if isinstance(result, int):
        return int(result)
    return 0


def _configure_stdout() -> None:
    """Windows 控制台默认 GBK，直接打印非 ASCII 会抛 UnicodeEncodeError。"""
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError, ValueError):
        pass


def run_plugin_cli(plugin_id: str, command: str = '', argv=None) -> int:
    """`python app.py plugin <id> <cmd> [args…]` 的实现。

    会确保配置与运行目录存在、获取数据目录独占锁（避免与运行中的实例并发写
    `ui_data.json`），然后加载全部插件并分发命令。
    """
    _configure_stdout()

    plugin_id = str(plugin_id or '').strip()
    command = str(command or '').strip()

    if not PLUGIN_ID_PATTERN.match(plugin_id):
        print(f'❌ 插件 id 非法: {plugin_id!r}')
        return 2

    from flask import Flask

    from core.config import DATA_DIR, ensure_config_file, ensure_runtime_dirs, load_config

    try:
        ensure_config_file()
        ensure_runtime_dirs(load_config())
    except Exception as exc:  # noqa: BLE001 - CLI 需要可读的错误输出
        print(f'❌ 初始化失败: {type(exc).__name__}: {exc}')
        return 1

    from core.data.data_dir_lock import acquire_data_directory_lock

    if not acquire_data_directory_lock(DATA_DIR):
        print('❌ 数据目录已被占用：请先关闭正在运行的 ST-Manager，再执行插件命令。')
        return 1

    app = Flask('st-manager-plugin-cli')
    try:
        registry.load_all(app)
    except Exception as exc:  # noqa: BLE001
        print(f'❌ 插件加载失败: {type(exc).__name__}: {exc}')
        return 1

    state = registry.get_state(plugin_id)
    if state is None:
        print(f'❌ 插件不存在或未安装: {plugin_id}')
        return 1
    if not state.enabled:
        print(f'❌ 插件已被禁用: {plugin_id}（在插件管理里启用后重试）')
        return 1
    if state.load_error:
        print(f'❌ 插件加载失败: {state.load_error}')
        return 1

    commands = list_commands(plugin_id)
    if command in ('', 'list', '--list'):
        if not commands:
            print(f'插件 {plugin_id} 未提供任何 CLI 子命令。')
            return 0
        print(f'插件 {plugin_id} 提供的命令：')
        for item in commands:
            print(f'  {item["name"]:<20} {item["description"]}')
        print(f'\n用法: python app.py plugin {plugin_id} <command> [args...] [--key value]')
        return 0

    try:
        exit_code = run_plugin_command(plugin_id, command, argv)
    except PluginCliError as exc:
        print(f'❌ {exc.message}')
        return 2
    except Exception as exc:  # noqa: BLE001 - 插件代码异常需要可读输出
        logger.exception('插件 %s 的命令 %s 执行失败', plugin_id, command)
        print(f'❌ 执行失败: {type(exc).__name__}: {exc}')
        return 1

    print(f'✅ {plugin_id} {command} 执行完成（退出码 {exit_code}）')
    return exit_code


def main(argv=None) -> int:
    """独立入口：`python -m core.plugins.cli <plugin_id> [command] [args…]`。"""
    items = list(sys.argv[1:] if argv is None else argv)
    if not items:
        print('用法: python -m core.plugins.cli <plugin_id> [command] [args...]')
        return 2
    return run_plugin_cli(items[0], items[1] if len(items) > 1 else '', items[2:])


if __name__ == '__main__':
    sys.exit(main())
