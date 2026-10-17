"""标签治理域测试（方案 §P0-3）。

重点覆盖：
1. `tags.create()` **只写分类体系**，不碰任何卡片（语义单一，可组合）；
2. `tags.merge()` 复用 `core/automation/tag_merge.py`，含链式解析与环检测；
3. `update_taxonomy` / `update_prefs` 是锁内合并，不丢宿主的并发写。
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.context import ctx
from core.plugins import api as api_module
from core.plugins import job_store
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    """清插件命名空间**与**标签治理状态（taxonomy / prefs 跨用例会互相污染）。"""
    from core.data.ui_store import (
        load_ui_data,
        save_ui_data,
        set_tag_management_prefs,
        set_tag_taxonomy,
    )

    def _reset():
        clear_plugin_ui_namespace()
        ui_data = load_ui_data()
        set_tag_taxonomy(ui_data, {})
        set_tag_management_prefs(ui_data, {'tag_blacklist': [], 'lock_tag_library': False})
        save_ui_data(ui_data, allow_shrink=True)

    _reset()
    yield
    _reset()


@pytest.fixture
def env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))

    # 标签库优先读 `ctx.cache.global_tags`（宿主缓存），这里给一个可控替身
    cache = _FakeCache()
    monkeypatch.setattr(ctx, 'cache', cache, raising=False)

    return {
        'api': PluginAPI(PluginManifest.load(plugin_dir)),
        'cards': cards_root,
        'cache': cache,
    }


class _FakeCache:
    """最小缓存替身：只提供标签库读取依赖的 `global_tags`。"""

    def __init__(self):
        self.global_tags = []

    def update_card_data(self, card_id, new_data):
        return None

    def update_tags_update(self, card_id, new_tags):
        return None


def test_library_reads_tags_from_host_cache(env):
    env['cache'].global_tags = ['A', 'B']

    assert env['api'].tags.library()['tags'] == ['A', 'B']


# ================================================================ 读取


def test_taxonomy_defaults_to_empty_dict(env):
    assert isinstance(env['api'].tags.taxonomy(), dict)


def test_prefs_defaults_are_readable(env):
    prefs = env['api'].tags.prefs()

    assert isinstance(prefs, dict)
    assert 'tag_blacklist' in prefs


def test_library_includes_taxonomy_and_prefs(env):
    env['cache'].global_tags = ['A', 'B']

    library = env['api'].tags.library()

    assert library['taxonomy'] == env['api'].tags.taxonomy()
    assert library['prefs'] == env['api'].tags.prefs()
    assert 'A' in library['tags']


# ================================================================ 写入


def test_update_taxonomy_merges_and_persists(env):
    """分类体系是 `categories`（定义）+ `tag_to_category`（归属）两层结构。"""
    api = env['api']

    assert api.tags.update_taxonomy({
        'categories': {'分类一': {'color': '#123456'}},
        'tag_to_category': {'A': '分类一'},
    }) is True

    taxonomy = api.tags.taxonomy()
    assert taxonomy['tag_to_category']['A'] == '分类一'
    assert '分类一' in taxonomy['categories']


def test_unknown_category_falls_back_to_default(env):
    """归属到未登记分类的标签会退回默认分类——这是 `ui_store` 的既有语义。"""
    api = env['api']

    api.tags.update_taxonomy({'tag_to_category': {'A': '不存在的分类'}})

    taxonomy = api.tags.taxonomy()
    assert taxonomy['tag_to_category']['A'] == taxonomy['default_category']


def test_update_taxonomy_preserves_other_keys(env):
    """浅合并语义：未提到的键保持原值（否则插件一写就把宿主配置清了）。"""
    api = env['api']
    api.tags.update_taxonomy({
        'categories': {'一': {}, '二': {}},
        'tag_to_category': {'A': '一'},
    })

    api.tags.update_taxonomy({'tag_to_category': {'A': '一', 'B': '二'}})

    taxonomy = api.tags.taxonomy()
    assert taxonomy['tag_to_category']['A'] == '一'
    assert taxonomy['tag_to_category']['B'] == '二'
    assert set(taxonomy['categories']) >= {'一', '二'}


def test_update_taxonomy_rejects_non_dict(env):
    assert env['api'].tags.update_taxonomy('nope') is False
    assert env['api'].tags.update_taxonomy({}) is False


def test_update_prefs_roundtrip(env):
    api = env['api']

    assert api.tags.update_prefs({'lock_tag_library': True}) is True

    assert api.tags.prefs()['lock_tag_library'] is True


def test_update_prefs_preserves_other_keys(env):
    api = env['api']
    api.tags.update_prefs({'tag_blacklist': ['bad']})

    api.tags.update_prefs({'lock_tag_library': True})

    prefs = api.tags.prefs()
    assert prefs['tag_blacklist'] == ['bad']
    assert prefs['lock_tag_library'] is True


# ================================================================ create


def test_create_adds_tags_to_taxonomy_only(env):
    """方案 §P0-3 的裁定：`create` 只做 ①（写分类体系），不做 ②（写卡片）。"""
    api = env['api']
    write_card(env['cards'], 'card.json', tags=['原有'])

    result = api.tags.create(['新标签'])

    assert result['created'] == ['新标签']
    assert result['existing'] == []
    assert result['failed'] == []

    # 分类体系里有了
    assert '新标签' in api.tags.taxonomy()['tag_to_category']
    # 卡片**没有**被动过
    assert api.cards.read('card.json')['data']['tags'] == ['原有']


def test_create_reports_existing_tags(env):
    api = env['api']
    api.tags.create(['已经有的'])

    result = api.tags.create(['已经有的'])

    assert result['created'] == []
    assert result['existing'] == ['已经有的']


def test_create_deduplicates_input(env):
    result = env['api'].tags.create(['A', 'A', 'B'])

    assert result['created'] == ['A', 'B']


def test_create_rejects_invalid_tag_names(env):
    result = env['api'].tags.create(['bad\x00tag', 'x' * 200, ''])

    assert result['created'] == []
    assert set(result['failed']) >= {'bad\x00tag', 'x' * 200}


def test_create_returns_empty_for_no_tags(env):
    assert env['api'].tags.create([]) == {'created': [], 'existing': [], 'failed': []}


# ================================================================ merge


def test_merge_resolves_chains(env):
    """`a→b`、`b→c` 必须解析成 `a→c`（链式解析）。"""
    api = env['api']
    env['cache'].global_tags = ['a']

    result = api.tags.merge({'a': 'b', 'b': 'c'})

    assert result['replacements'] == [{'from': 'a', 'to': 'c'}]
    assert result['cycles'] == []


def test_merge_detects_cycles(env):
    """`a→b→a` 必须被识别为环，并且不无限循环。"""
    api = env['api']
    env['cache'].global_tags = ['a']

    result = api.tags.merge({'a': 'b', 'b': 'a'})

    assert result['cycles'], '环没有被检出'
    assert set(result['cycles']) == {'a', 'b'}


def test_merge_accepts_text_rule_form(env):
    """`'旧1|旧2 → 新'` 文本形态要能解析。"""
    api = env['api']
    env['cache'].global_tags = ['旧1', '旧2']

    result = api.tags.merge('旧1|旧2 → 新')

    assert result['replace_rules'] == {'旧1': '新', '旧2': '新'}
    assert result['tags'] == ['新']


def test_merge_does_not_touch_cards(env):
    """`merge` 只计算，不落盘——要落盘由调用方调 `cards.apply_tags`。"""
    api = env['api']
    env['cache'].global_tags = ['old']
    write_card(env['cards'], 'card.json', tags=['old'])

    result = api.tags.merge({'old': 'new'})

    assert result['changed'] is True
    assert api.cards.read('card.json')['data']['tags'] == ['old']


def test_merge_then_apply_tags_composes(env):
    """语义单一 + 可组合：merge 出结果，apply_tags 落盘。"""
    api = env['api']
    env['cache'].global_tags = ['old']
    write_card(env['cards'], 'card.json', tags=['old'])

    merged = api.tags.merge({'old': 'new'})
    api.cards.apply_tags(['card.json'], add=merged['tags'], replace=True)

    assert api.cards.read('card.json')['data']['tags'] == ['new']


def test_merge_returns_empty_for_no_rules(env):
    result = env['api'].tags.merge({})

    assert result['changed'] is False
    assert result['replacements'] == []


# ================================================================ 与治理联动


def test_created_tag_passes_library_lock(env):
    """标签库锁打开时，先 `tags.create` 再把标签打到卡片上应该能通过。"""
    api = env['api']
    write_card(env['cards'], 'card.json')
    api.tags.update_prefs({'lock_tag_library': True})

    blocked = api.cards.apply_tags(['card.json'], add=['未登记的标签'])
    assert blocked['skipped_unknown'] == ['未登记的标签']

    api.tags.create(['未登记的标签'])
    accepted = api.cards.apply_tags(['card.json'], add=['未登记的标签'])

    assert accepted['skipped_unknown'] == []
    assert '未登记的标签' in api.cards.read('card.json')['data']['tags']


def test_blacklisted_tag_still_rejected_after_create(env):
    """黑名单优先级高于分类体系：`create` 之后仍不该被放行。"""
    api = env['api']
    write_card(env['cards'], 'card.json')
    api.tags.update_prefs({'tag_blacklist': ['禁止的']})

    api.tags.create(['禁止的'])
    result = api.cards.apply_tags(['card.json'], add=['禁止的'])

    assert result['skipped_blacklist'] == ['禁止的']
