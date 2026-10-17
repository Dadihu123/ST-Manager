"""PluginAPI 门面测试（设计文档 10.2 / 13.1；域命名空间见方案 §3）。"""

import json
import os
import sqlite3
import sys

import pytest

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


# ------------------------------------------------------------------ 身份与域


def test_identity_fields(plugin_env):
    api = plugin_env['api']

    assert api.plugin_id == 'demo-plugin'
    assert api.manifest['id'] == 'demo-plugin'
    assert api.manifest['version'] == '0.1.0'
    assert api.app_version


def test_domain_attributes_are_same_instance(plugin_env):
    """方案 §3.4：域对象每次访问返回同一个实例，插件的 isinstance/缓存才不会失效。"""
    api = plugin_env['api']

    for name in ('cards', 'tags', 'worldbook', 'backups', 'jobs', 'private',
                 'config', 'secrets', 'http', 'cli', 'log', 'index',
                 'chats', 'presets', 'extensions'):
        assert getattr(api, name) is getattr(api, name), name


def test_directory_style_facade_only_keeps_three_public_members():
    """方案 §3.7：PluginAPI 类体只剩 3 个公开成员（+ 内部方法）。"""
    import inspect

    public = sorted(
        name for name, member in inspect.getmembers(PluginAPI, predicate=inspect.isfunction)
        if not name.startswith('_')
    )

    assert public == ['bind_job', 'emit', 'estimate_tokens', 'finalize', 'on']


def test_removed_flat_members_are_gone(plugin_env):
    """方案 §3.2：这些是**删除**而不是改名。"""
    api = plugin_env['api']

    for name in ('db', 'notify', 'suppress_fs_events', 'table_prefix', 'migrate',
                 'data_dir', 'ui_data_read', 'ui_data_update', 'read_card',
                 'write_card_fields', 'apply_tags', 'read_tag_library',
                 'snapshot_card', 'read_worldbook', 'write_worldbook',
                 'get_config', 'set_config', 'get_secret', 'register_job',
                 'submit_job', 'register_cli'):
        assert not hasattr(api, name), f'旧扁平成员仍然存在: {name}'


# ------------------------------------------------------------------ 配置


def test_config_defaults_and_roundtrip(plugin_env):
    api = plugin_env['api']

    assert api.config.get() == {'greeting': 'hi', 'count': 3}
    assert api.config.set({'greeting': 'hello'}) is True
    assert api.config.get()['greeting'] == 'hello'
    assert api.config.get()['count'] == 3


def test_set_config_ignores_unknown_keys(plugin_env):
    api = plugin_env['api']

    assert api.config.set({'nope': 1}) is False
    assert 'nope' not in api.config.get()


# ------------------------------------------------------------------ 密钥


def test_get_secret_falls_back_to_schema_default(plugin_env):
    api = plugin_env['api']

    assert api.secrets.get('api_key') is None
    assert api.secrets.get('base_url') == 'https://example.com/v1'


def test_list_secrets_masks_secret_items(plugin_env):
    api = plugin_env['api']
    api.secrets.set('api_key', 'sk-1234567890abcdef')

    described = api.secrets.list()

    assert described['api_key']['set'] is True
    assert described['api_key']['hint'] == 'sk-…cdef'
    assert 'value' not in described['api_key']


# ------------------------------------------------------------------ 私有数据


def test_migrate_creates_prefixed_table(plugin_env):
    api = plugin_env['api']

    api.private.migrate([
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
        api.private.migrate(['CREATE TABLE core_hack (id INTEGER)'])
    with pytest.raises(ValueError):
        api.private.migrate(['CREATE INDEX idx_hack ON card_metadata (id)'])


def test_migrate_rejects_non_create_statements(plugin_env):
    api = plugin_env['api']

    with pytest.raises(ValueError):
        api.private.migrate(['DROP TABLE card_metadata'])
    with pytest.raises(ValueError):
        api.private.migrate(['DELETE FROM card_metadata'])


def test_table_prefix_normalizes_dashes(plugin_env):
    assert plugin_env['api'].private.table_prefix() == 'plugin_demo_plugin_'


def test_data_dir_is_created_inside_plugin_dir(plugin_env):
    target = plugin_env['api'].private.dir()

    assert os.path.isdir(target)
    assert target == os.path.join(plugin_env['plugin_dir'], 'data')


def test_private_query_returns_dicts(plugin_env):
    api = plugin_env['api']
    api.private.migrate(['CREATE TABLE plugin_demo_plugin_rows (id INTEGER, label TEXT)'])

    conn = job_store.connect(ensure_schema=False)
    try:
        conn.execute("INSERT INTO plugin_demo_plugin_rows (id, label) VALUES (1, 'a')")
        conn.commit()
    finally:
        conn.close()

    rows = api.private.query('SELECT id, label FROM plugin_demo_plugin_rows')

    assert rows == [{'id': 1, 'label': 'a'}]


def test_private_query_accepts_parameters(plugin_env):
    api = plugin_env['api']
    api.private.migrate(['CREATE TABLE plugin_demo_plugin_rows (id INTEGER, label TEXT)'])

    conn = job_store.connect(ensure_schema=False)
    try:
        conn.execute("INSERT INTO plugin_demo_plugin_rows (id, label) VALUES (1, 'a')")
        conn.commit()
    finally:
        conn.close()

    assert api.private.query('SELECT id FROM plugin_demo_plugin_rows WHERE label = ?', ('a',)) == [{'id': 1}]


@pytest.mark.parametrize('statement', [
    'DELETE FROM plugin_demo_plugin_rows',
    'DROP TABLE plugin_demo_plugin_rows',
    'UPDATE plugin_demo_plugin_rows SET label = ? ',
    'INSERT INTO plugin_demo_plugin_rows (id) VALUES (1)',
    'PRAGMA journal_mode = DELETE',
    'ATTACH DATABASE \'x.db\' AS x',
])
def test_private_query_rejects_non_select(plugin_env, statement):
    """方案 §3.2：能力放开，但写入一律走域方法——`query` 只允许只读 SELECT。"""
    with pytest.raises(ValueError):
        plugin_env['api'].private.query(statement)


def test_private_query_rejects_multiple_statements(plugin_env):
    with pytest.raises(ValueError):
        plugin_env['api'].private.query('SELECT 1; SELECT 2')


def test_private_query_rejects_cte_smuggling(plugin_env):
    """`WITH … INSERT` 这类绕过必须被拦住。"""
    with pytest.raises(ValueError):
        plugin_env['api'].private.query(
            'WITH x AS (SELECT 1) INSERT INTO plugin_demo_plugin_rows (id) SELECT 1'
        )


def test_private_query_allows_cte_select(plugin_env):
    assert plugin_env['api'].private.query('WITH x AS (SELECT 1 AS n) SELECT n FROM x') == [{'n': 1}]


# ------------------------------------------------------------------ 卡片读


def test_read_card_returns_full_payload(plugin_env):
    write_card(plugin_env['cards'], 'sub/card.json', tags=['a', 'b'])

    info = plugin_env['api'].cards.read('sub/card.json')

    assert info['data']['tags'] == ['a', 'b']
    assert info['id'] == 'sub/card.json'


def test_read_cards_returns_mapping(plugin_env):
    write_card(plugin_env['cards'], 'one.json')
    write_card(plugin_env['cards'], 'two.json')

    result = plugin_env['api'].cards.read_many(['one.json', 'two.json', 'missing.json'])

    assert set(result.keys()) == {'one.json', 'two.json', 'missing.json'}
    assert result['one.json'] is not None
    assert result['missing.json'] is None


def test_read_card_rejects_path_escape(plugin_env):
    api = plugin_env['api'].cards

    assert api.read('../../outside.json') is None
    assert api.read('/etc/passwd') is None
    assert api.write_fields('../../outside.json', {'description': 'x'}) is False


# ------------------------------------------------------------------ 卡片写


def _seed_metadata_row(root, card_id='card.json'):
    conn = sqlite3.connect(str(root / 'cards_metadata.db'))
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS card_metadata (id TEXT PRIMARY KEY, char_name TEXT, description TEXT,'
            ' first_mes TEXT, mes_example TEXT, tags TEXT, creator TEXT, char_version TEXT,'
            ' last_modified REAL, file_hash TEXT, file_size INTEGER)'
        )
        conn.execute('INSERT OR REPLACE INTO card_metadata (id, tags) VALUES (?, ?)', (card_id, '[]'))
        conn.commit()
    finally:
        conn.close()


def test_write_card_fields_updates_file_and_db(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']
    _seed_metadata_row(plugin_env['root'])

    assert api.cards.write_fields('card.json', {'description': 'updated', 'tags': ['a', 'c']}) is True

    info = api.cards.read('card.json')
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

    assert api.cards.write_fields('card.json', {'character_book': {'entries': []}}) is True

    assert api.cards.read('card.json')['data'].get('character_book') is None


def test_write_card_fields_uses_suppress_fs_events(plugin_env, monkeypatch):
    write_card(plugin_env['cards'], 'card.json')
    calls = []

    import core.services.scan_service as scan_service

    monkeypatch.setattr(scan_service, 'suppress_fs_events', lambda seconds=1.5: calls.append(seconds))

    assert plugin_env['api'].cards.write_fields('card.json', {'description': 'x'}) is True
    assert len(calls) >= 2


def test_apply_tags_merges_by_default(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']

    result = api.cards.apply_tags(['card.json'], add=['b'])

    assert result['updated'] == 1
    assert result['added'] == ['b']
    assert api.cards.read('card.json')['data']['tags'] == ['a', 'b']


def test_apply_tags_replace_mode_overwrites(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a'])
    api = plugin_env['api']

    api.cards.apply_tags(['card.json'], add=['b'], replace=True)

    assert api.cards.read('card.json')['data']['tags'] == ['b']


def test_apply_tags_remove(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a', 'b'])
    api = plugin_env['api']

    result = api.cards.apply_tags(['card.json'], remove=['a'])

    assert result['removed'] == ['a']
    assert api.cards.read('card.json')['data']['tags'] == ['b']


def test_apply_tags_respects_blacklist(plugin_env):
    from core.data.ui_store import load_ui_data, save_ui_data, set_tag_management_prefs

    write_card(plugin_env['cards'], 'card.json', tags=['a'])

    ui_data = load_ui_data()
    set_tag_management_prefs(ui_data, {'tag_blacklist': ['blocked'], 'lock_tag_library': False})
    save_ui_data(ui_data, allow_shrink=True)

    result = plugin_env['api'].cards.apply_tags(['card.json'], add=['blocked', 'ok'])

    assert result['skipped_blacklist'] == ['blocked']
    assert plugin_env['api'].cards.read('card.json')['data']['tags'] == ['a', 'ok']


def test_apply_tags_reports_failed_cards(plugin_env):
    write_card(plugin_env['cards'], 'card.json')

    result = plugin_env['api'].cards.apply_tags(['card.json', 'missing.json'], add=['x'])

    assert result['failed'] == ['missing.json']
    assert result['updated'] == 1


# ------------------------------------------------------------------ 标签库


def test_read_tag_library_returns_taxonomy_and_prefs(plugin_env):
    write_card(plugin_env['cards'], 'card.json', tags=['a', 'b'])

    library = plugin_env['api'].tags.library()

    assert 'taxonomy' in library
    assert 'prefs' in library
    assert isinstance(library['order'], list)


# ------------------------------------------------------------------ 快照


def test_snapshot_card_copies_file(plugin_env):
    write_card(plugin_env['cards'], 'card.json')
    api = plugin_env['api']

    snapshot_path = api.backups.snapshot_card('card.json', remark='unit-test')

    assert snapshot_path and os.path.isfile(snapshot_path)
    assert 'unit-test' in os.path.basename(snapshot_path)


def test_snapshot_card_rejects_unknown_card(plugin_env):
    assert plugin_env['api'].backups.snapshot_card('missing.json') is None


# ------------------------------------------------------------------ 世界书


def _worldbook_env(plugin_env, monkeypatch):
    world_root = plugin_env['root'] / 'lorebooks'
    world_root.mkdir(exist_ok=True)
    world_file = world_root / 'book.json'
    world_file.write_text(
        json.dumps({'entries': [{'uid': 1, 'content': 'a'}]}, ensure_ascii=False),
        encoding='utf-8',
    )

    monkeypatch.setattr(api_module, 'load_config', lambda: {
        'world_info_dir': str(world_root),
        'resources_dir': str(plugin_env['root'] / 'resources'),
    })
    return world_file


def test_write_worldbook_roundtrip(plugin_env, monkeypatch):
    world_file = _worldbook_env(plugin_env, monkeypatch)
    api = plugin_env['api']

    book = api.worldbook.read({'source_type': 'global', 'file_path': str(world_file)})
    assert book['entries'][0]['content'] == 'a'

    result = api.worldbook.write(
        {'source_type': 'global', 'file_path': str(world_file)},
        {'entries': [{'uid': 1, 'content': 'b'}]},
    )
    assert result['success'] is True

    written = json.loads(world_file.read_text(encoding='utf-8'))
    assert written['entries'][0]['content'] == 'b'


def test_write_worldbook_rejects_stale_revision(plugin_env, monkeypatch):
    world_file = _worldbook_env(plugin_env, monkeypatch)

    result = plugin_env['api'].worldbook.write(
        {'source_type': 'global', 'file_path': str(world_file)},
        {'entries': []},
        expected_revision='stale-revision',
    )

    assert result['success'] is False
    assert result['error'] == 'revision_conflict'


def test_read_worldbook_returns_none_for_unknown_source(plugin_env):
    assert plugin_env['api'].worldbook.read({'source_type': 'global', 'file_path': ''}) is None


def test_worldbook_list_entries(plugin_env, monkeypatch):
    world_file = _worldbook_env(plugin_env, monkeypatch)

    entries = plugin_env['api'].worldbook.list_entries(
        {'source_type': 'global', 'file_path': str(world_file)},
    )

    assert len(entries) == 1
    assert entries[0]['content'] == 'a'


# ------------------------------------------------------------------ token 估算


def test_estimate_tokens_matches_shared_formula(plugin_env):
    from core.utils.text import calculate_token_count, estimate_text_tokens

    api = plugin_env['api']

    assert api.estimate_tokens('中文abc') == estimate_text_tokens('中文abc')
    assert api.estimate_tokens('') == 0
    assert api.estimate_tokens(None) == 0
    # 公式：CJK 1 + 非 CJK / 3.5，向上取整 → 3 个其他字符 = 1 → 合计 3
    assert api.estimate_tokens('中文abc') == 3


def test_estimate_tokens_shares_formula_with_card_level_estimator():
    """两处后端估算必须同源：卡片级只是把字段聚合后交给通用估算。"""
    from core.utils.text import NON_CJK_TOKEN_RATIO, calculate_token_count, estimate_text_tokens

    card = {
        'name': '卡',
        'description': 'abcdefg',
        'first_mes': '',
        'mes_example': '',
        'character_book': {'entries': [{'content': '条目', 'keys': ['k']}]},
    }
    # calculate_token_count 聚合的是 name+description+first_mes+mes_example
    # + 已启用世界书条目的 content 与 keys
    aggregated = '卡' + 'abcdefg' + '' + '' + '条目' + 'k'

    assert NON_CJK_TOKEN_RATIO == 3.5
    assert calculate_token_count(card) == estimate_text_tokens(aggregated)
    assert calculate_token_count(card) == 6  # 3 CJK + 8 非 CJK / 3.5 = 5.29 → 6


# ------------------------------------------------------------------ ui_data 配额（N4）


def test_ui_data_update_rejects_oversized_namespace(plugin_env):
    """超过配额时整次写入被拒绝，磁盘内容回滚到写入前状态。"""
    api = plugin_env['api']
    assert api.private.update(lambda entry: entry.update({'blob': 'ok'})) is True

    oversized = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES + 4096)
    assert api.private.update(lambda entry: entry.update({'blob': oversized})) is False

    assert api.private.read().get('blob') == 'ok'


def test_ui_data_update_logs_rejection(plugin_env, monkeypatch):
    warnings = []
    monkeypatch.setattr(api_module.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    api = plugin_env['api']
    oversized = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES + 1)

    assert api.private.update(lambda entry: entry.update({'blob': oversized})) is False
    assert any('写入被拒绝' in str(args[0]) for args in warnings)
    # 拒绝原因（含实际上限）作为格式化参数传入
    assert any('超过' in str(arg) for args in warnings for arg in args[1:])


def test_ui_data_update_warns_when_near_quota(plugin_env, monkeypatch):
    warnings = []
    monkeypatch.setattr(api_module.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    api = plugin_env['api']
    nearly = 'x' * (api_module.PLUGIN_DATA_QUOTA_WARN_BYTES + 1024)

    assert api.private.update(lambda entry: entry.update({'blob': nearly})) is True
    assert any('即将被拒绝' in str(args[0]) for args in warnings)


def test_ui_data_update_accepts_payload_within_quota(plugin_env):
    api = plugin_env['api']
    payload = 'x' * (api_module.PLUGIN_DATA_QUOTA_BYTES - 4096)

    assert api.private.update(lambda entry: entry.update({'blob': payload})) is True
    assert api.private.read()['blob'] == payload


def test_ui_data_quota_constants_are_reasonable():
    assert api_module.PLUGIN_DATA_QUOTA_BYTES == 256 * 1024
    assert api_module.PLUGIN_DATA_QUOTA_WARN_BYTES < api_module.PLUGIN_DATA_QUOTA_BYTES


# ------------------------------------------------------------------ 事件与日志


def test_on_and_emit_stay_flat(plugin_env):
    api = plugin_env['api']
    received = []

    api.on('demo-plugin:hello', lambda payload: received.append(payload))
    api.emit('demo-plugin:hello', {'value': 1})

    assert received == [{'value': 1}]


def test_emit_rejects_foreign_namespace(plugin_env):
    with pytest.raises(ValueError):
        plugin_env['api'].emit('other-plugin:hello', {})


def test_named_log_levels(plugin_env, monkeypatch):
    calls = []
    monkeypatch.setattr(api_module.logger, 'debug', lambda *a, **k: calls.append('debug'))
    monkeypatch.setattr(api_module.logger, 'info', lambda *a, **k: calls.append('info'))
    monkeypatch.setattr(api_module.logger, 'warning', lambda *a, **k: calls.append('warning'))
    monkeypatch.setattr(api_module.logger, 'error', lambda *a, **k: calls.append('error'))

    api = plugin_env['api']
    api.log.debug('d')
    api.log.info('i')
    api.log.warn('w')
    api.log.error('e')

    assert calls == ['debug', 'info', 'warning', 'error']


def test_log_appends_job_event_when_bound(plugin_env, monkeypatch):
    from core.plugins import jobs

    events = []
    monkeypatch.setattr(jobs, 'append_log_event', lambda run_id, level, text: events.append((run_id, level, text)))

    api = plugin_env['api']
    api.bind_job('run-1')
    api.log.warn('careful')
    api.bind_job(None)
    api.log.warn('ignored')

    assert events == [('run-1', 'warning', 'careful')]
