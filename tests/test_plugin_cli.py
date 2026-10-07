"""插件 CLI 子命令测试（设计文档 N2 与附录 I）。"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import cli as cli_module
from core.plugins import registry as registry_module
from core.plugins.errors import PluginCliError
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin

CLI_BACKEND = '''\
def register(api):
    def hello(namespace):
        target = namespace.args[0] if namespace.args else "world"
        print(f"hello {target}")
        return 0

    def counting(namespace):
        return 3

    def boom(namespace):
        raise RuntimeError("kaboom")

    def optional(namespace):
        print(f"model={namespace.options.get('model')} force={namespace.options.get('force')}")
        return 0

    api.register_cli("hello", hello, description="打招呼")
    api.register_cli("counting", counting)
    api.register_cli("boom", boom)
    api.register_cli("optional", optional)
'''


@pytest.fixture(autouse=True)
def _isolate():
    cli_module.reset_for_tests()
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    yield
    cli_module.reset_for_tests()
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    for name in list(sys.modules):
        if name.startswith(registry_module.MODULE_PREFIX):
            sys.modules.pop(name, None)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    import core.config as config_module
    import core.data.data_dir_lock as lock_module

    plugins_root = tmp_path / 'plugins'
    plugins_root.mkdir()

    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(plugins_root))
    monkeypatch.setattr(config_module, 'ensure_config_file', lambda **kwargs: None)
    monkeypatch.setattr(config_module, 'ensure_runtime_dirs', lambda cfg: None)
    monkeypatch.setattr(config_module, 'load_config', lambda: {})
    monkeypatch.setattr(config_module, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(lock_module, 'acquire_data_directory_lock', lambda path: True)

    return {'plugins_root': plugins_root, 'tmp_path': tmp_path}


# ------------------------------------------------------------------ 注册校验


def test_register_cli_stores_command():
    cli_module.register_cli('demo-plugin', 'sync', lambda ns: 0, '同步卡片')

    assert cli_module.list_commands('demo-plugin') == [{'name': 'sync', 'description': '同步卡片'}]
    assert cli_module.all_commands() == [
        {'plugin_id': 'demo-plugin', 'name': 'sync', 'description': '同步卡片'},
    ]


@pytest.mark.parametrize('plugin_id,name', [
    ('Bad_Id', 'sync'),
    ('', 'sync'),
    ('demo-plugin', 'Bad Name'),
    ('demo-plugin', ''),
    ('demo-plugin', '-leading'),
])
def test_register_cli_rejects_invalid_names(plugin_id, name):
    with pytest.raises(ValueError):
        cli_module.register_cli(plugin_id, name, lambda ns: 0)


def test_register_cli_rejects_non_callable():
    with pytest.raises(ValueError):
        cli_module.register_cli('demo-plugin', 'sync', 'not-callable')


def test_register_cli_overwrites_same_name():
    cli_module.register_cli('demo-plugin', 'sync', lambda ns: 0)
    cli_module.register_cli('demo-plugin', 'sync', lambda ns: 1)

    assert len(cli_module.all_commands()) == 1


def test_unregister_plugin_removes_only_its_commands():
    cli_module.register_cli('a-plugin', 'x', lambda ns: 0)
    cli_module.register_cli('b-plugin', 'y', lambda ns: 0)

    assert cli_module.unregister_plugin('a-plugin') == 1
    assert cli_module.list_commands('a-plugin') == []
    assert [item['name'] for item in cli_module.list_commands('b-plugin')] == ['y']


def test_drop_state_clears_cli_commands():
    cli_module.register_cli('demo-plugin', 'x', lambda ns: 0)

    registry_module.drop_state('demo-plugin')

    assert cli_module.list_commands('demo-plugin') == []


def test_namespaces_are_isolated_per_plugin():
    cli_module.register_cli('a-plugin', 'sync', lambda ns: 0)

    assert cli_module.list_commands('b-plugin') == []
    with pytest.raises(PluginCliError):
        cli_module.run_plugin_command('b-plugin', 'sync', [])


# ------------------------------------------------------------------ 参数解析


def test_build_namespace_keeps_positional_args():
    namespace = cli_module.build_namespace(['a', 'b', 'c'])

    assert namespace.args == ['a', 'b', 'c']
    assert namespace.options == {}


def test_build_namespace_parses_option_value_pairs():
    namespace = cli_module.build_namespace(['--model', 'gpt-4o', 'target'])

    assert namespace.options == {'model': 'gpt-4o'}
    assert namespace.model == 'gpt-4o'
    assert namespace.args == ['target']


def test_build_namespace_parses_equals_form():
    namespace = cli_module.build_namespace(['--limit=10'])

    assert namespace.options == {'limit': '10'}
    assert namespace.limit == '10'


def test_build_namespace_parses_flags():
    namespace = cli_module.build_namespace(['--force'])

    assert namespace.options == {'force': True}
    assert namespace.force is True


def test_build_namespace_normalizes_dashed_keys():
    namespace = cli_module.build_namespace(['--dry-run'])

    assert getattr(namespace, 'dry_run') is True


def test_build_namespace_treats_double_dash_as_separator():
    namespace = cli_module.build_namespace(['--', '--not-an-option', 'x'])

    assert namespace.args == ['--not-an-option', 'x']
    assert namespace.options == {}


def test_build_namespace_handles_missing_option_value():
    namespace = cli_module.build_namespace(['--model', '--force'])

    assert namespace.options == {'model': True, 'force': True}


def test_build_namespace_tolerates_empty_input():
    namespace = cli_module.build_namespace(None)

    assert namespace.args == []
    assert namespace.options == {}


# ------------------------------------------------------------------ 执行


def test_run_plugin_command_returns_zero_by_default():
    cli_module.register_cli('demo-plugin', 'noop', lambda ns: None)

    assert cli_module.run_plugin_command('demo-plugin', 'noop', []) == 0


def test_run_plugin_command_propagates_integer_exit_code():
    cli_module.register_cli('demo-plugin', 'code', lambda ns: 7)

    assert cli_module.run_plugin_command('demo-plugin', 'code', []) == 7


@pytest.mark.parametrize('result,expected', [(True, 0), (False, 1)])
def test_run_plugin_command_maps_booleans(result, expected):
    cli_module.register_cli('demo-plugin', 'flag', lambda ns: result)

    assert cli_module.run_plugin_command('demo-plugin', 'flag', []) == expected


def test_run_plugin_command_passes_namespace():
    seen = {}
    cli_module.register_cli('demo-plugin', 'echo', lambda ns: seen.update(vars(ns)) or 0)

    cli_module.run_plugin_command('demo-plugin', 'echo', ['pos', '--key', 'value'])

    assert seen['args'] == ['pos']
    assert seen['options'] == {'key': 'value'}


def test_run_plugin_command_rejects_unknown_command():
    cli_module.register_cli('demo-plugin', 'known', lambda ns: 0)

    with pytest.raises(PluginCliError, match='没有子命令'):
        cli_module.run_plugin_command('demo-plugin', 'unknown', [])


def test_run_plugin_command_lets_handler_exceptions_propagate():
    cli_module.register_cli('demo-plugin', 'boom', lambda ns: (_ for _ in ()).throw(RuntimeError('x')))

    with pytest.raises(RuntimeError):
        cli_module.run_plugin_command('demo-plugin', 'boom', [])


# ------------------------------------------------------------------ 端到端


def test_cli_lists_commands(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'list')
    output = capsys.readouterr().out

    assert exit_code == 0
    assert 'hello' in output
    assert '打招呼' in output
    assert 'python app.py plugin cli-plugin' in output


def test_cli_runs_registered_command(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'hello', ['Alice'])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert 'hello Alice' in output
    assert '执行完成' in output


def test_cli_forwards_options_to_handler(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    cli_module.run_plugin_cli('cli-plugin', 'optional', ['--model', 'x', '--force'])
    output = capsys.readouterr().out

    assert 'model=x' in output
    assert 'force=True' in output


def test_cli_propagates_exit_code(cli_env):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    assert cli_module.run_plugin_cli('cli-plugin', 'counting') == 3


def test_cli_reports_handler_exception(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'boom')
    output = capsys.readouterr().out

    assert exit_code == 1
    assert 'kaboom' in output


def test_cli_reports_unknown_command(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'nope')
    output = capsys.readouterr().out

    assert exit_code == 2
    assert '没有子命令' in output


def test_cli_reports_missing_plugin(cli_env, capsys):
    exit_code = cli_module.run_plugin_cli('ghost-plugin', 'list')
    output = capsys.readouterr().out

    assert exit_code == 1
    assert '不存在' in output


def test_cli_rejects_invalid_plugin_id(cli_env, capsys):
    assert cli_module.run_plugin_cli('Bad_Id', 'list') == 2
    assert '非法' in capsys.readouterr().out


def test_cli_refuses_disabled_plugin(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)
    registry_module.set_enabled('cli-plugin', False)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'hello')
    output = capsys.readouterr().out

    assert exit_code == 1
    assert '已被禁用' in output


def test_cli_refuses_when_data_dir_is_locked(cli_env, monkeypatch, capsys):
    import core.data.data_dir_lock as lock_module

    write_plugin(cli_env['plugins_root'], 'cli-plugin', backend=CLI_BACKEND)
    monkeypatch.setattr(lock_module, 'acquire_data_directory_lock', lambda path: False)

    exit_code = cli_module.run_plugin_cli('cli-plugin', 'hello')
    output = capsys.readouterr().out

    assert exit_code == 1
    assert '数据目录已被占用' in output


def test_cli_reports_plugin_without_commands(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'quiet-plugin')

    exit_code = cli_module.run_plugin_cli('quiet-plugin', '')
    output = capsys.readouterr().out

    assert exit_code == 0
    assert '未提供任何 CLI 子命令' in output


def test_cli_reports_load_error(cli_env, capsys):
    write_plugin(cli_env['plugins_root'], 'broken-plugin', backend='raise RuntimeError("bad plugin")\n')

    exit_code = cli_module.run_plugin_cli('broken-plugin', 'list')
    output = capsys.readouterr().out

    assert exit_code == 1
    assert '加载失败' in output


def test_module_main_requires_arguments(capsys):
    assert cli_module.main([]) == 2
    assert '用法' in capsys.readouterr().out
