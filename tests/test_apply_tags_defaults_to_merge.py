"""D4 回归保护：`apply_tags` 默认合并、不清空既有标签（设计文档 13.3）。"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import job_store
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    clear_plugin_ui_namespace()
    yield
    clear_plugin_ui_namespace()


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))

    return {'api': PluginAPI(PluginManifest.load(plugin_dir)), 'cards': cards_root}


def _tags(api, card_id='card.json'):
    return api.read_card(card_id)['data']['tags']


def test_default_call_merges_without_clearing(api_env):
    write_card(api_env['cards'], 'card.json', tags=['原有A', '原有B'])

    api_env['api'].apply_tags(['card.json'], add=['新增C'])

    assert _tags(api_env['api']) == ['原有A', '原有B', '新增C']


def test_default_is_merge_even_when_add_is_empty(api_env):
    write_card(api_env['cards'], 'card.json', tags=['原有A'])

    api_env['api'].apply_tags(['card.json'], add=[])

    assert _tags(api_env['api']) == ['原有A']


def test_replace_requires_explicit_flag(api_env):
    write_card(api_env['cards'], 'card.json', tags=['原有A'])

    api_env['api'].apply_tags(['card.json'], add=['仅此一个'], replace=True)

    assert _tags(api_env['api']) == ['仅此一个']


def test_remove_only_keeps_other_tags(api_env):
    write_card(api_env['cards'], 'card.json', tags=['A', 'B', 'C'])

    result = api_env['api'].apply_tags(['card.json'], remove=['B'])

    assert _tags(api_env['api']) == ['A', 'C']
    assert result['removed'] == ['B']
    assert result['added'] == []


def test_duplicate_add_is_deduplicated(api_env):
    write_card(api_env['cards'], 'card.json', tags=['A'])

    api_env['api'].apply_tags(['card.json'], add=['A', 'A', 'B', 'B'])

    assert _tags(api_env['api']) == ['A', 'B']


def test_replace_then_remove_order(api_env):
    write_card(api_env['cards'], 'card.json', tags=['A'])

    api_env['api'].apply_tags(['card.json'], add=['X', 'Y'], remove=['X'], replace=True)

    assert _tags(api_env['api']) == ['Y']


def test_apply_tags_reports_counts(api_env):
    write_card(api_env['cards'], 'one.json', tags=['A'])
    write_card(api_env['cards'], 'two.json', tags=['A'])

    result = api_env['api'].apply_tags(['one.json', 'two.json'], add=['B'])

    assert result['updated'] == 2
    assert result['added'] == ['B']
    assert result['failed'] == []
