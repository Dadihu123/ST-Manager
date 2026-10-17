"""卡片域一致性测试（方案 §6.3 建议：测「机制确实生效」而不是「函数返回 True」）。

重点覆盖三件事：
1. `cards.move()` 之后缓存 / `card_metadata` / 索引增量三处**都**同步了；
2. `cards.write_note()` 走的是 `ui_data`（不是卡片文件），bundle 走版本级备注；
3. `cards.read_note()` / `write_note()` 不与宿主 UI 的并发写丢更新。
"""

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
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from core.services import card_service
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    """清掉插件命名空间**与**卡片级 ui_data（备注跨用例会互相污染）。"""
    from core.data.ui_store import load_ui_data, save_ui_data

    def _reset():
        clear_plugin_ui_namespace()
        ui_data = load_ui_data()
        for key in [k for k in ui_data if not str(k).startswith('_')]:
            ui_data.pop(key, None)
        save_ui_data(ui_data, allow_shrink=True)

    _reset()
    yield
    _reset()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """插件 + 卡片根目录 + 独立 DB + 干净的全局缓存。"""
    from core.context import ctx
    from core.data import db_session
    from flask import Flask

    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    data_root = tmp_path / 'data'
    data_root.mkdir()
    db_path = tmp_path / 'cards_metadata.db'

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(data_root))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(db_path))
    # 服务层各自 import 了 CARDS_FOLDER / DEFAULT_DB_PATH，要一并替换
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(db_path), raising=False)
    # `get_db()` 读的是 `db_session` 模块级的 DEFAULT_DB_PATH（来自 core.config）
    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db_path))
    _ensure_metadata_table(db_path)

    cache = _FakeCache()
    monkeypatch.setattr(ctx, 'cache', cache, raising=False)

    index_jobs = []
    import core.services.index_job_worker as index_worker

    monkeypatch.setattr(
        index_worker, 'enqueue_index_job',
        lambda job_type, entity_id='', source_path='', payload=None: index_jobs.append(
            {'job_type': job_type, 'entity_id': entity_id}
        ),
    )

    # `move_card_internal` 走 `core.data.db_session.get_db`（依赖 Flask `g`），
    # 因此需要一个应用上下文。
    app = Flask('plugin-domain-test')
    app.config['TESTING'] = True
    with app.app_context():
        api = PluginAPI(PluginManifest.load(plugin_dir))
        yield {
            'api': api, 'cards': cards_root, 'root': tmp_path,
            'cache': cache, 'index_jobs': index_jobs, 'db': db_path,
            'app': app,
        }


class _FakeCache:
    """最小可用的全局缓存替身：只实现插件写路径会用到的接口。"""

    def __init__(self):
        self.id_map = {}
        self.bundle_map = {}
        self.category_counts = {}
        self.visible_folders = []

    def update_card_data(self, card_id, new_data):
        card = self.id_map.setdefault(card_id, {'id': card_id})
        old_category = card.get('category', '')
        if 'category' in new_data and new_data['category'] != old_category:
            self.category_counts[old_category] = max(0, self.category_counts.get(old_category, 0) - 1)
            self.category_counts[new_data['category']] = self.category_counts.get(new_data['category'], 0) + 1
        card.update(new_data)
        return card

    def move_card_update(self, old_id, new_id, old_category, new_category, final_name, dst_full_path):
        card = self.id_map.pop(old_id, None)
        if card is None:
            return None
        card = dict(card)
        card.update({'id': new_id, 'category': new_category, 'filename': final_name})
        self.id_map[new_id] = card
        return card


def _ensure_metadata_table(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS card_metadata ('
            'id TEXT PRIMARY KEY, char_name TEXT, description TEXT, first_mes TEXT,'
            ' mes_example TEXT, tags TEXT, creator TEXT, char_version TEXT,'
            ' last_modified REAL, file_hash TEXT, file_size INTEGER, category TEXT)'
        )
        conn.commit()
    finally:
        conn.close()


def _seed_metadata_row(db_path, card_id, category=''):
    _ensure_metadata_table(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            'INSERT OR REPLACE INTO card_metadata (id, category, tags) VALUES (?, ?, ?)',
            (card_id, category, '[]'),
        )
        conn.commit()
    finally:
        conn.close()


# ================================================================ 移动


def test_move_updates_cache_db_and_index(env):
    """方案 §P0-1 的验收：移动后三处一致性都要成立。"""
    api = env['api']
    write_card(env['cards'], 'old/card.json')
    _seed_metadata_row(env['db'], 'old/card.json', category='old')
    env['cache'].id_map['old/card.json'] = {'id': 'old/card.json', 'category': 'old'}

    result = api.cards.move(['old/card.json'], 'new')

    assert result['count'] == 1
    assert result['failed'] == []
    moved = result['moved'][0]
    assert moved['new_id'] == 'new/card.json'
    assert moved['new_category'] == 'new'

    # ① 文件真的移动了
    assert os.path.isfile(os.path.join(str(env['cards']), 'new', 'card.json'))
    assert not os.path.isfile(os.path.join(str(env['cards']), 'old', 'card.json'))

    # ② 缓存里 id_map 已更新（这是最容易漏的一环）
    assert 'old/card.json' not in env['cache'].id_map
    assert env['cache'].id_map['new/card.json']['category'] == 'new'

    # ③ card_metadata 行的路径与分类都已变
    conn = sqlite3.connect(str(env['db']))
    try:
        row = conn.execute(
            'SELECT id, category FROM card_metadata WHERE id = ?', ('new/card.json',),
        ).fetchone()
        stale = conn.execute(
            'SELECT id FROM card_metadata WHERE id = ?', ('old/card.json',),
        ).fetchone()
    finally:
        conn.close()

    assert row == ('new/card.json', 'new')
    assert stale is None


def test_move_dispatches_card_moved_hook(env):
    """其它插件（如桌宠）必须能收到 `card.moved`。"""
    from core.plugins import hooks

    api = env['api']
    write_card(env['cards'], 'a/card.json')

    received = []
    hooks.register('card.moved', received.append, plugin_id='observer-plugin')
    try:
        api.cards.move(['a/card.json'], 'b')
    finally:
        hooks.unregister_plugin('observer-plugin')

    assert len(received) == 1
    assert received[0]['moves'] == [{'old_id': 'a/card.json', 'new_id': 'b/card.json'}]


def test_move_suppresses_fs_events_around_the_batch(env, monkeypatch):
    """一次批量移动会触发几百次文件事件，抑制窗口要覆盖整个循环。"""
    import core.services.scan_service as scan_service

    calls = []
    monkeypatch.setattr(
        scan_service, 'suppress_fs_events',
        lambda seconds=1.5: calls.append(seconds),
    )

    api = env['api']
    write_card(env['cards'], 'x/one.json')
    write_card(env['cards'], 'x/two.json')

    api.cards.move(['x/one.json', 'x/two.json'], 'y')

    # 进入 + 退出 = 2 次，而不是每张卡各一对
    assert calls == [5.0, 5.0]


def test_move_accepts_root_keyword(env):
    write_card(env['cards'], 'sub/card.json')

    result = env['api'].cards.move(['sub/card.json'], '根目录')

    assert result['moved'][0]['new_id'] == 'card.json'


@pytest.mark.parametrize('bad_target', [
    '..',
    '../escape',
    '/abs/path',
    'C:/windows',
    'bad:name',
    'has<angle>',
    'pipe|name',
    'x' * 80,
    'backups',
    'notes',
])
def test_move_rejects_unsafe_target_categories(env, bad_target):
    """分类名可能来自 AI 输出：必须做 slug 化 + 白名单校验。"""
    write_card(env['cards'], 'card.json')

    result = env['api'].cards.move(['card.json'], bad_target)

    assert result['count'] == 0
    assert result['failed']
    # 文件没被搬走
    assert os.path.isfile(os.path.join(str(env['cards']), 'card.json'))


def test_move_rejects_unsafe_card_path(env):
    write_card(env['cards'], 'card.json')

    result = env['api'].cards.move(['../../etc/passwd'], 'safe')

    assert result['count'] == 0
    assert result['failed'][0]['old_id'] == '../../etc/passwd'


def test_move_reports_per_card_failures_without_aborting(env):
    write_card(env['cards'], 'ok.json')

    result = env['api'].cards.move(['ok.json', 'missing.json'], 'dest')

    assert result['count'] == 1
    assert [item['old_id'] for item in result['failed']] == ['missing.json']


def test_move_resolves_name_conflicts_by_suffixing(env):
    write_card(env['cards'], 'one/card.json')
    write_card(env['cards'], 'two/card.json')

    env['api'].cards.move(['one/card.json'], 'two')
    result = env['api'].cards.move(['two/card.json'], 'two')

    # 同名冲突时自动递增，不覆盖既有卡片
    assert os.path.isfile(os.path.join(str(env['cards']), 'two', 'card.json'))
    assert len(os.listdir(os.path.join(str(env['cards']), 'two'))) == 2


# ================================================================ 分类


def test_create_category_is_idempotent(env):
    api = env['api']

    assert api.cards.create_category('新分类') is True
    assert os.path.isdir(os.path.join(str(env['cards']), '新分类'))

    assert api.cards.create_category('新分类') is True


def test_create_category_with_parent(env):
    assert env['api'].cards.create_category('子', parent='父') is True
    assert os.path.isdir(os.path.join(str(env['cards']), '父', '子'))


def test_create_category_registers_in_visible_folders(env):
    env['api'].cards.create_category('可见分类')

    assert '可见分类' in env['cache'].visible_folders


@pytest.mark.parametrize('bad_name', [
    '..', '.', '', 'a/b', 'a\\b', 'bad:name', 'q?mark', 'star*', 'quote"',
    'lt<gt>', 'pipe|', 'notes', 'backups', 'lorebooks', 'thumbnails', 'cards', 'trash',
    'x' * 65,
])
def test_create_category_rejects_unsafe_names(env, bad_name):
    before = set(os.listdir(str(env['cards'])))

    assert env['api'].cards.create_category(bad_name) is False

    # 关键断言：卡片根目录下没有**新增**任何东西
    assert set(os.listdir(str(env['cards']))) == before


def test_create_category_rejects_unsafe_parent(env):
    assert env['api'].cards.create_category('leaf', parent='../escape') is False
    assert env['api'].cards.create_category('leaf', parent='bad:parent') is False


def test_list_categories_returns_nested_paths(env):
    write_card(env['cards'], 'a/card.json')
    write_card(env['cards'], 'a/b/card.json')

    categories = env['api'].cards.list_categories()

    assert 'a' in categories
    assert 'a/b' in categories


def test_rename_category_migrates_db_prefix(env):
    write_card(env['cards'], 'old/card.json')
    _seed_metadata_row(env['db'], 'old/card.json', category='old')

    assert env['api'].cards.rename_category('old', 'renamed') is True

    assert os.path.isdir(os.path.join(str(env['cards']), 'renamed'))
    assert os.path.isfile(os.path.join(str(env['cards']), 'renamed', 'card.json'))

    conn = sqlite3.connect(str(env['db']))
    try:
        row = conn.execute(
            'SELECT id FROM card_metadata WHERE id = ?', ('renamed/card.json',),
        ).fetchone()
        stale = conn.execute(
            'SELECT id FROM card_metadata WHERE id = ?', ('old/card.json',),
        ).fetchone()
    finally:
        conn.close()

    assert row == ('renamed/card.json',)
    assert stale is None


def test_rename_category_migrates_ui_data_prefix(env):
    from core.data.ui_store import load_ui_data, save_ui_data

    write_card(env['cards'], 'old/card.json')

    ui_data = load_ui_data()
    ui_data['old/card.json'] = {'summary': '备注跟着走'}
    save_ui_data(ui_data, allow_shrink=True)

    assert env['api'].cards.rename_category('old', 'renamed') is True

    assert load_ui_data().get('renamed/card.json', {}).get('summary') == '备注跟着走'


def test_rename_category_rejects_unsafe_paths(env):
    api = env['api']

    assert api.cards.rename_category('..', 'ok') is False
    assert api.cards.rename_category('ok', '../escape') is False
    assert api.cards.rename_category('notes', 'ok') is False


def test_rename_category_rejects_existing_target(env):
    write_card(env['cards'], 'src/card.json')
    env['api'].cards.create_category('dst')

    assert env['api'].cards.rename_category('src', 'dst') is False


# ================================================================ 本地备注


def test_write_note_goes_to_ui_data_not_card_file(env):
    """方案 §P0-2 的验收：备注在 `ui_data` 里，卡片文件不变。"""
    api = env['api']
    write_card(env['cards'], 'card.json')
    card_path = os.path.join(str(env['cards']), 'card.json')
    before = open(card_path, encoding='utf-8').read()

    assert api.cards.write_note('card.json', '这是本地备注') is True

    after = open(card_path, encoding='utf-8').read()
    assert before == after, '备注不应该写进卡片文件'

    from core.data.ui_store import load_ui_data

    assert load_ui_data()['card.json']['summary'] == '这是本地备注'


def test_read_note_returns_empty_for_card_without_note(env):
    write_card(env['cards'], 'card.json')

    assert env['api'].cards.read_note('card.json') == ''


def test_read_note_returns_what_write_note_wrote(env):
    api = env['api']
    write_card(env['cards'], 'card.json')

    api.cards.write_note('card.json', '概览文本')

    assert api.cards.read_note('card.json') == '概览文本'


def test_write_note_preserves_concurrently_written_link(env):
    """备注写入必须是 `update_ui_data` 的锁内合并，不能整块覆盖条目。"""
    from core.data.ui_store import load_ui_data, save_ui_data

    api = env['api']
    write_card(env['cards'], 'card.json')

    ui_data = load_ui_data()
    ui_data['card.json'] = {'summary': '旧备注', 'link': 'https://example.com/src', 'resource_folder': 'RF'}
    save_ui_data(ui_data, allow_shrink=True)

    assert api.cards.write_note('card.json', '新备注') is True

    entry = load_ui_data()['card.json']
    assert entry['summary'] == '新备注'
    assert entry['link'] == 'https://example.com/src'
    assert entry['resource_folder'] == 'RF'


def test_write_note_clears_with_empty_string(env):
    api = env['api']
    write_card(env['cards'], 'card.json')
    api.cards.write_note('card.json', '有内容')

    api.cards.write_note('card.json', '')

    assert api.cards.read_note('card.json') == ''


def test_write_note_rejects_missing_card(env):
    assert env['api'].cards.write_note('missing.json', 'x') is False


def test_write_note_rejects_path_escape(env):
    assert env['api'].cards.write_note('../../outside.json', 'x') is False


def test_read_notes_bulk(env):
    api = env['api']
    write_card(env['cards'], 'one.json')
    write_card(env['cards'], 'two.json')
    api.cards.write_note('one.json', 'A')

    assert api.cards.read_notes(['one.json', 'two.json']) == {'one.json': 'A', 'two.json': ''}


def test_bundle_version_note_uses_version_level_remarks(env):
    """bundle 卡片的备注必须走版本级 `_version_remarks`，而不是根上的 summary。"""
    api = env['api']
    write_card(env['cards'], 'pack/v1.json')
    write_card(env['cards'], 'pack/v2.json')

    env['cache'].bundle_map['pack'] = 'pack/v1.json'
    env['cache'].id_map['pack/v1.json'] = {
        'id': 'pack/v1.json', 'is_bundle': True, 'bundle_dir': 'pack',
        'versions': [{'id': 'pack/v1.json'}, {'id': 'pack/v2.json'}],
    }
    env['cache'].id_map['pack/v2.json'] = {
        'id': 'pack/v2.json', 'is_bundle': False, 'bundle_dir': 'pack',
    }

    assert api.cards.write_note('pack/v2.json', 'v2 的备注') is True

    from core.data.ui_store import load_ui_data

    entry = load_ui_data()['pack']
    assert entry['_version_remarks']['pack/v2.json']['summary'] == 'v2 的备注'
    assert 'summary' not in entry

    assert api.cards.read_note('pack/v2.json') == 'v2 的备注'
