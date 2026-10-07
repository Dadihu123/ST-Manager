"""PluginAPI 门面测试（设计文档 10.2 / 13.1）。"""

import json
import os
import sqlite3
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import job_store
from core.plugins import secrets as secrets_module
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui(tmp_path, monkeypatch):
    clear_plugin_ui_namespace()
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    secrets_module._clear_degraded()
    yield
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    data_root = tmp_path / 'data'
    data_root.mkdir()

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(data_root))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))

    api = PluginAPI(PluginManifest.load(plugin_dir))
    return {'api': api, 'cards': cards_root, 'plugin_dir': plugin_dir, 'root': tmp_path}


def test_identity_fields(plugin_env):
    api = plugin_env['api']

    assert api.plugin_id == 'demo-plugin'
    assert api.manifest['id'] == 'demo-plugin'
    assert api.manifest['version'] == '0.1.0'
    assert api.app_version


def test_config_defaults_and_roundtrip(plugin_env):
    api = plugin_env['api']

    assert api.get_config() == {'greeting': 'hi', 'count': 3}
    assert api.set_config({'greeting': 'hello'}) is True
    assert api.get_config()['greeting'] == 'hello'
    assert api.get_config()['count'] == 3


def test_set_config_ignores_unknown_keys(plugin_env):
    api = plugin_env['api']

    assert api.set_config({'nope': 1}) is False
    assert 'nope' not in api.get_config()


def test_get_secret_falls_back_to_schema_default(plugin_env):
    api = plugin_env['api']

    assert api.get_secret('api_key') is None
    assert api.get_secret('base_url') == 'https://example.com/v1'


def test_list_secrets_masks_secret_items(plugin_env):
    api = plugin_env['api']
    api.set_secret('api_key', 'sk-1234567890abcdef')

    described = api.list_secrets()

    assert described['api_key']['set'] is True
    assert described['api_key']['hint'] == 'sk-…cdef'
    assert 'value' not in described['api_key']


def test_migrate_creates_prefixed_table(plugin_env):
    api = plugin_env['api']

    api.migrate([
        'CREATE TABLE IF NOT EXISTS plugin_demo_plugin_logs (id INTEGER PRIMARY KEY)',
        'CREATE INDEX IF NOT EXISTS plugin_demo_plugin_logs_idx ON plugin_demo_plugin_logs (id)',
    ])

    conn = sqlite3.connect(str(plugin_env['root'] / 'cards_metadata.db'))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert 'plugin_demo_plugin_logs' in names


def test_migrate_rejects_unprefixed_names(plugin_env):
    api = plugin_env['api']

    with pytest.raises(ValueError):
        api.migrate(['CREATE TABLE core_hack (id INTEGER)'])
    with pytest.raises(ValueError):
        api.migrate(['CREATE INDEX idx_hack ON card_metadata (id)'])


def test_migrate_rejects_non_create_statements(plugin_env):
    api = plugin_env['api']

    with pytest.raises(ValueError):
        api.migrate(['DROP TABLE card_metadata'])
    with pytest.raises(ValueError):
        api.migrate(['DELETE FROM card_metadata'])


def test_table_prefix_normalizes_dashes(plugin_env):
    assert plugin_env['api'].table_prefix() == 'plugin_demo_plugin_'


def test_data_dir_is_created_inside_plugin_dir(plugin_env):
    target = plugin_env['api'].data_dir()

    assert os.path.isdir(target)
    assert target == os.path.join(plugin_env['plugin_dir'], 'data')


def test_read_card_returns_full_payload(plugin_env):
    write_card(plugin_env['cards'], 'sub/card.json', tags=['a', 'b'])

    info = plugin_env['api'].read_card('sub/card.json')

    assert info['data']['tags'] == ['a', 'b']
    assert info['id'] == 'sub/card.json'


def test_read_cards_returns_mapping(plugin_env):
    write_card(plugin_env['cards'], 'one.json')
    write_card(plugin_env['cards'], 'two.json')

    result = plugin_env['api'].read_cards(['one.json', 'two.json', 'missing.json'])

    assert set(result.keys()) == {'one.json', 'two.json', 'missing.json'}
    assert result['one.json'] is not None
    assert result['missing.json'] is None


def test_read_card_rejects_path_escape(plugin_env):
    api = plugin_env['api']

    assert api.read_card('../../outside.json') is None
    assert api.read_card('/etc/passwd') is None
    assert api.write_card_fields('../../outside.json', {'description': 'x'}) is False


def test_write_card_fields_updates_file_and_db(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']

    conn = sqlite3.connect(str(plugin_env['root'] / 'cards_metadata.db'))
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT,'
            ' first_mes TEXT, mes_example TEXT, tags TEXT, creator TEXT, char_version TEXT,'
            ' last_modified REAL, file_hash TEXT, file_size INTEGER)'
        )
        conn.execute("INSERT OR REPLACE INTO card_metadata (id, tags) VALUES ('card.json', '[]')")
        conn.commit()
    finally:
        conn.close()

    assert api.write_card_fields('card.json', {'description': 'updated', 'tags': ['a', 'c']}) is True

    info = api.read_card('card.json')
    assert info['data']['description'] == 'updated'
    assert info['data']['tags'] == ['a', 'c']

    conn = sqlite3.connect(str(plugin_env['root'] / 'cards_metadata.db'))
    try:
        row = conn.execute(
            'SELECT description, tags FROM card_metadata WHERE id = ?', ('card.json',),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == 'updated'
    assert json.loads(row[1]) == ['a', 'c']


def test_write_card_fields_ignores_unlisted_fields(plugin_env):
    write_card(plugin_env['cards'], 'card.json')
    api = plugin_env['api']

    assert api.write_card_fields('card.json', {'character_book': {'entries': []}}) is True

    assert api.read_card('card.json')['data'].get('character_book') is None


def test_write_card_fields_uses_suppress_fs_events(plugin_env, monkeypatch):
    write_card(plugin_env['cards'], 'card.json')
    calls = []

    import core.services.scan_service as scan_service

    monkeypatch.setattr(scan_service, 'suppress_fs_events', lambda seconds=1.5: calls.append(seconds))

    assert plugin_env['api'].write_card_fields('card.json', {'description': 'x'}) is True
    assert len(calls) >= 2


def test_suppress_fs_events_context_manager(plugin_env, monkeypatch):
    calls = []

    import core.services.scan_service as scan_service

    monkeypatch.setattr(scan_service, 'suppress_fs_events', lambda seconds=1.5: calls.append(seconds))

    with plugin_env['api'].suppress_fs_events(2.0):
        calls.append('body')

    assert calls == [2.0, 'body', 2.0]


def test_apply_tags_merges_by_default(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']

    result = api.apply_tags(['card.json'], add=['b'])

    assert result['updated'] == 1
    assert result['added'] == ['b']
    assert api.read_card('card.json')['data']['tags'] == ['a', 'b']


def test_apply_tags_replace_mode_overwrites(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']

    api.apply_tags(['card.json'], add=['b'], replace=True)

    assert api.read_card('card.json')['data']['tags'] == ['b']


def test_apply_tags_remove(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a', 'b'])
    api = plugin_env['api']

    result = api.apply_tags(['card.json'], remove=['a'])

    assert result['removed'] == ['a']
    assert api.read_card('card.json')['data']['tags'] == ['b']


def test_apply_tags_respects_blacklist(plugin_env):
    from core.data.ui_store import load_ui_data, save_ui_data, set_tag_management_prefs

    write_card(plugin_env['cards'], 'card.json', tags=['a'])

    ui_data = load_ui_data()
    set_tag_management_prefs(ui_data, {'tag_blacklist': ['blocked'], 'lock_tag_library': False})
    save_ui_data(ui_data, allow_shrink=True)

    result = plugin_env['api'].apply_tags(['card.json'], add=['blocked', 'ok'])

    assert result['skipped_blacklist'] == ['blocked']
    assert plugin_env['api'].read_card('card.json')['data']['tags'] == ['a', 'ok']


def test_apply_tags_reports_failed_cards(plugin_env):
    write_card(plugin_env['cards'], 'card.json')

    result = plugin_env['api'].apply_tags(['card.json', 'missing.json'], add=['x'])

    assert result['failed'] == ['missing.json']
    assert result['updated'] == 1


def test_read_tag_library_returns_taxonomy_and_prefs(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a', 'b'])

    library = plugin_env['api'].read_tag_library()

    assert 'taxonomy' in library
    assert 'prefs' in library
    assert isinstance(library['order'], list)


def test_db_returns_sqlite_connection(plugin_env):
    conn = plugin_env['api'].db()
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.execute('SELECT 1').fetchone()[0] == 1
    finally:
        conn.close()


def test_snapshot_card_copies_file(plugin_env):
    write_card(plugin_env['cards'], 'card.json')
    api = plugin_env['api']

    snapshot_path = api.snapshot_card('card.json', remark='unit-test')

    assert snapshot_path and os.path.isfile(snapshot_path)
    assert 'unit-test' in os.path.basename(snapshot_path)


def test_snapshot_card_rejects_unknown_card(plugin_env):
    assert plugin_env['api'].snapshot_card('missing.json') is None


def test_write_worldbook_roundtrip(plugin_env, monkeypatch):
    world_root = plugin_env['root'] / 'lorebooks'
    world_root.mkdir()
    world_file = world_root / 'book.json'
    world_file.write_text(json.dumps({'entries': [{'uid': 1, 'content': 'a'}]}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(api_module, 'load_config', lambda: {
        'world_info_dir': str(world_root),
        'resources_dir': str(plugin_env['root'] / 'resources'),
    })

    api = plugin_env['api']
    book = api.read_worldbook({'source_type': 'global', 'file_path': str(world_file)})
    assert book['entries'][0]['content'] == 'a'

    result = api.write_worldbook(
        {'source_type': 'global', 'file_path': str(world_file)},
        {'entries': [{'uid': 1, 'content': 'b'}]},
    )
    assert result['success'] is True

    written = json.loads(world_file.read_text(encoding='utf-8'))
    assert written['entries'][0]['content'] == 'b'


def test_write_worldbook_rejects_stale_revision(plugin_env, monkeypatch):
    world_root = plugin_env['root'] / 'lorebooks'
    world_root.mkdir()
    world_file = world_root / 'book.json'
    world_file.write_text(json.dumps({'entries': []}), encoding='utf-8')

    monkeypatch.setattr(api_module, 'load_config', lambda: {
        'world_info_dir': str(world_root),
        'resources_dir': str(plugin_env['root'] / 'resources'),
    })

    result = plugin_env['api'].write_worldbook(
        {'source_type': 'global', 'file_path': str(world_file)},
        {'entries': []},
        expected_revision='stale-revision',
    )

    assert result['success'] is False
    assert result['error'] == 'revision_conflict'


def test_read_worldbook_returns_none_for_unknown_source(plugin_env):
    assert plugin_env['api'].read_worldbook({'source_type': 'global', 'file_path': ''}) is None


# ---------------------------------------------------------------- ui_data 配额（N4）


def test_ui_data_update_rejects_oversized_namespace(plugin_env):
    """超过配额时整次写入被拒绝，磁盘内容回滚到写入前状态。"""
    api = plugin_env['api']
    assert api.ui_data_update(lambda entry: entry.update({'blob': 'ok'})) is True

    oversized = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES + 4096)
    assert api.ui_data_update(lambda entry: entry.update({'blob': oversized})) is False

    assert api.ui_data_read().get('blob') == 'ok'


def test_ui_data_update_logs_rejection(plugin_env, monkeypatch):
    warnings = []
    monkeypatch.setattr(api_module.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    api = plugin_env['api']
    oversized = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES + 1)

    assert api.ui_data_update(lambda entry: entry.update({'blob': oversized})) is False
    assert any('写入被拒绝' in str(args[0]) for args in warnings)
    # 拒绝原因（含实际上限）作为格式化参数传入
    assert any('超过' in str(arg) for args in warnings for arg in args[1:])


def test_ui_data_update_warns_when_near_quota(plugin_env, monkeypatch):
    warnings = []
    monkeypatch.setattr(api_module.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    api = plugin_env['api']
    nearly = 'x' * (api_module.PLUGIN_DATA_QUOTA_WARN_BYTES + 1024)

    assert api.ui_data_update(lambda entry: entry.update({'blob': nearly})) is True
    assert any('即将被拒绝' in str(args[0]) for args in warnings)


def test_ui_data_update_accepts_payload_within_quota(plugin_env):
    api = plugin_env['api']
    payload = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES - 4096)

    assert api.ui_data_update(lambda entry: entry.update({'blob': payload})) is True
    assert api.ui_data_read()['blob'] == payload


def test_ui_data_quota_constants_are_reasonable():
    assert api_module.PLUGIN_DATA_QUOTA_BYTES == 256 * 1024
    assert api_module.PLUGIN_DATA_QUOTA_WARN_BYTES < api_module.PLUGIN_DATA_QUOTA_BYTES
