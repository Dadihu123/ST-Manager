"""`spec_from_file_location` 隔离测试（设计文档 4.3 / 13.1）。"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import registry as registry_module
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import write_plugin

BACKEND_WITH_RELATIVE_IMPORT = '''\
from . import helper


def register(api):
    api.loaded_value = helper.VALUE
'''

BACKEND_WITH_ABSOLUTE_IMPORT = '''\
import backend


def register(api):
    api.loaded_value = getattr(backend, 'VALUE', '')
'''

HELPER_SOURCE = "VALUE = 'from-helper'\n"


@pytest.fixture(autouse=True)
def _cleanup_modules():
    yield
    for name in list(sys.modules):
        if name.startswith(registry_module.MODULE_PREFIX):
            sys.modules.pop(name, None)


def _make_plugin(tmp_path, plugin_id):
    plugin_dir = write_plugin(tmp_path, plugin_id, backend=BACKEND_WITH_RELATIVE_IMPORT)
    with open(os.path.join(plugin_dir, 'backend', 'helper.py'), 'w', encoding='utf-8') as handle:
        handle.write(HELPER_SOURCE)
    return plugin_dir


def test_two_plugins_with_same_layout_do_not_conflict(tmp_path):
    app = Flask('plugin-loader-test')
    first_dir = _make_plugin(tmp_path, 'first-plugin')
    second_dir = _make_plugin(tmp_path, 'second-plugin')

    first_api, first_module = registry_module._instantiate_plugin(app, PluginManifest.load(first_dir))
    second_api, second_module = registry_module._instantiate_plugin(app, PluginManifest.load(second_dir))

    assert first_api.loaded_value == 'from-helper'
    assert second_api.loaded_value == 'from-helper'
    assert first_module is not second_module
    assert first_module.__name__ != second_module.__name__


def test_module_name_uses_prefix_and_underscores(tmp_path):
    app = Flask('plugin-loader-test')
    plugin_dir = _make_plugin(tmp_path, 'first-plugin')

    _, module = registry_module._instantiate_plugin(app, PluginManifest.load(plugin_dir))

    assert module.__name__ == 'st_plugin_first_plugin'
    assert module.__package__ == 'st_plugin_first_plugin'


def test_no_top_level_backend_module_residue(tmp_path):
    app = Flask('plugin-loader-test')
    plugin_dir = _make_plugin(tmp_path, 'first-plugin')

    registry_module._instantiate_plugin(app, PluginManifest.load(plugin_dir))

    assert 'backend' not in sys.modules
    assert 'helper' not in sys.modules
    assert 'st_plugin_first_plugin.helper' in sys.modules


def test_absolute_import_of_backend_fails(tmp_path):
    app = Flask('plugin-loader-test')
    plugin_dir = write_plugin(tmp_path, 'absolute-plugin', backend=BACKEND_WITH_ABSOLUTE_IMPORT)

    with pytest.raises(ImportError):
        registry_module._instantiate_plugin(app, PluginManifest.load(plugin_dir))


def test_failed_load_leaves_no_module_residue(tmp_path):
    app = Flask('plugin-loader-test')
    plugin_dir = write_plugin(tmp_path, 'broken-plugin', backend='raise RuntimeError("boom")\n')

    with pytest.raises(RuntimeError):
        registry_module._instantiate_plugin(app, PluginManifest.load(plugin_dir))

    assert 'st_plugin_broken_plugin' not in sys.modules


def test_register_function_can_add_routes_after_loading(tmp_path):
    app = Flask('plugin-loader-test')
    plugin_dir = write_plugin(tmp_path, 'route-plugin')

    registry_module._instantiate_plugin(app, PluginManifest.load(plugin_dir))

    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert any(rule.endswith('/ping') for rule in rules)
