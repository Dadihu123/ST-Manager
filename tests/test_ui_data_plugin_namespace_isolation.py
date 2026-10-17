"""`ui_data._plugins_v1.<id>` 命名空间隔离（设计文档 13.3 回归保护）。"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data.ui_store import load_ui_data, save_ui_data
from core.plugins import api as api_module
from core.plugins import installer
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    clear_plugin_ui_namespace()
    yield
    clear_plugin_ui_namespace()


@pytest.fixture
def plugin_api(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    monkeypatch.setattr(api_module, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    return PluginAPI(PluginManifest.load(plugin_dir))


def _seed_existing_ui_data():
    ui_data = load_ui_data()
    ui_data['card-a.json'] = {'summary': '原有备注'}
    ui_data['_tag_order_v1'] = {'order': ['A'], 'enabled': True}
    ui_data['_plugins_v1'] = {'other-plugin': {'config': {'x': 1}}}
    assert save_ui_data(ui_data, allow_shrink=True) is True


def test_plugin_namespace_write_keeps_existing_keys(plugin_api):
    _seed_existing_ui_data()

    assert plugin_api.private.update(lambda entry: entry.update({'counter': 1})) is True

    data = load_ui_data()
    assert data['card-a.json'] == {'summary': '原有备注'}
    assert data['_tag_order_v1'] == {'order': ['A'], 'enabled': True}
    assert data['_plugins_v1']['other-plugin'] == {'config': {'x': 1}}
    assert data['_plugins_v1']['demo-plugin'] == {'counter': 1}


def test_ui_data_read_only_returns_own_namespace(plugin_api):
    _seed_existing_ui_data()
    plugin_api.private.update(lambda entry: entry.update({'value': 'mine'}))

    snapshot = plugin_api.private.read()

    assert snapshot == {'value': 'mine'}
    assert 'card-a.json' not in snapshot


def test_ui_data_read_returns_empty_for_unknown_plugin(plugin_api):
    assert plugin_api.private.read() == {}


def test_ui_data_update_rejects_non_callable(plugin_api):
    assert plugin_api.private.update({'not': 'callable'}) is False


def test_ui_data_update_supports_returning_new_dict(plugin_api):
    plugin_api.private.update(lambda entry: {'replaced': True})

    assert plugin_api.private.read() == {'replaced': True}


def test_clear_ui_namespace_only_removes_target_plugin():
    _seed_existing_ui_data()

    assert installer._clear_ui_namespace('other-plugin') is True

    data = load_ui_data()
    assert 'other-plugin' not in data['_plugins_v1']
    assert data['card-a.json'] == {'summary': '原有备注'}


def test_clear_ui_namespace_is_idempotent():
    _seed_existing_ui_data()

    assert installer._clear_ui_namespace('missing-plugin') is True
    assert load_ui_data()['card-a.json'] == {'summary': '原有备注'}


def test_other_plugin_namespace_is_not_touched_by_config_writes(plugin_api):
    _seed_existing_ui_data()

    plugin_api.config.set({'greeting': 'hello'})

    data = load_ui_data()
    assert data['_plugins_v1']['other-plugin'] == {'config': {'x': 1}}
    assert data['_plugins_v1']['demo-plugin']['config'] == {'greeting': 'hello'}
