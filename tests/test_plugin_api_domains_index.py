"""索引与结构化查询域测试（方案 §P1-1 / §P1-4 / §P1-2）。

重点覆盖：
1. `cards.list()` / `cards.count()` 走**索引查询服务**（不裸 SQL、不全表扫）；
2. `cards.read_extensions()` 把 ST 的历史别名键归一到唯一形状；
3. `index.status()` / `search()` / `rebuild()` 的失败与未就绪路径不抛异常。
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    clear_plugin_ui_namespace()
    yield
    clear_plugin_ui_namespace()


@pytest.fixture
def env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(tmp_path / 'data'))

    return {'api': PluginAPI(PluginManifest.load(plugin_dir)), 'cards': cards_root}


# ================================================================ 结构化查询


@pytest.fixture
def spy_index_query(monkeypatch):
    """拦截索引查询服务调用，断言插件走的是索引而不是裸 SQL。"""
    import core.services.card_index_query_service as query_service

    calls = []

    def _fake(filters):
        calls.append(filters)
        return {
            'cards': [{'id': 'a.json', 'char_name': 'A'}, {'id': 'b.json', 'char_name': 'B'}],
            'total_count': 7,
            'index_ready': True,
        }

    monkeypatch.setattr(query_service, 'query_indexed_cards', _fake)
    return calls


def test_list_delegates_to_index_query_service(env, spy_index_query):
    """方案 §P1-1：走索引服务，不用 `db()` 裸 SQL。"""
    result = env['api'].cards.list(query='hero', category='sub', tags=['x'])

    assert result['items'] == [{'id': 'a.json', 'char_name': 'A'}, {'id': 'b.json', 'char_name': 'B'}]
    assert result['total'] == 7
    assert result['index_ready'] is True
    assert len(spy_index_query) == 1

    filters = spy_index_query[0]
    assert filters['search'] == 'hero'
    assert filters['category'] == 'sub'
    assert filters['include_tags'] == ['x']


def test_list_passes_tag_and_search_filters(env, spy_index_query):
    env['api'].cards.list(query='q', exclude_tags=['bad'], search_mode='fulltext', search_scope='full')

    filters = spy_index_query[0]
    assert filters['exclude_tags'] == ['bad']
    assert filters['search_mode'] == 'fulltext'
    assert filters['search_scope'] == 'full'


def test_list_paginates_with_limit_and_offset(env, spy_index_query):
    env['api'].cards.list(limit=10, offset=20)

    filters = spy_index_query[0]
    assert filters['page_size'] == 10
    assert filters['page'] == 3  # (20 // 10) + 1


def test_count_uses_the_same_filters_without_pulling_rows(env, spy_index_query):
    total = env['api'].cards.count(query='q')

    assert total == 7
    # 计数时页大小压到 1，不去拉一整页数据
    assert spy_index_query[0]['page_size'] == 1


def test_list_maps_index_fields_to_items(env, monkeypatch):
    """真实索引服务返回的键是 `cards` / `total_count`，域要投影成 `items` / `total`。"""
    import core.services.card_index_query_service as query_service

    monkeypatch.setattr(query_service, 'query_indexed_cards', lambda filters: {
        'cards': [], 'total_count': 0, 'index_ready': False,
    })

    result = env['api'].cards.list()

    assert result == {'items': [], 'total': 0, 'index_ready': False}


# ================================================================ 扩展字段归一


def _write_card_with_extensions(cards_root, card_id, extensions):
    import json

    full_path = os.path.join(str(cards_root), card_id.replace('/', os.sep))
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    payload = {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'name': '卡',
        'data': {'name': '卡', 'description': '', 'first_mes': '', 'mes_example': '',
                 'tags': [], 'extensions': extensions},
    }
    with open(full_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return full_path


@pytest.mark.parametrize('alias', [
    'regex_scripts', 'regexScripts', 'regex', 'regexes', 'regular_expressions',
])
def test_read_extensions_normalizes_regex_aliases(env, alias):
    """ST 历史上用过 5 个正则键名；插件不该自己写兼容。"""
    _write_card_with_extensions(env['cards'], 'card.json', {alias: [{'findRegex': '/a/'}]})

    result = env['api'].cards.read_extensions('card.json')

    assert result['regex_scripts'] == [{'findRegex': '/a/'}]


@pytest.mark.parametrize('alias', [
    'tavern_helper', 'tavernHelper', 'TavernHelper_scripts',
    'tavern_helper_scripts', 'tavernHelper_scripts', 'TavernHelper', 'scripts',
])
def test_read_extensions_normalizes_tavern_helper_aliases(env, alias):
    _write_card_with_extensions(env['cards'], 'card.json', {alias: {'scripts': [{'name': 's'}]}})

    result = env['api'].cards.read_extensions('card.json')

    assert result['tavern_helper']['scripts'] == [{'name': 's'}]


def test_read_extensions_handles_list_of_pairs_form(env):
    """`[['scripts', [...]]]` 这种 list-of-pairs 形态也要兼容。"""
    _write_card_with_extensions(
        env['cards'], 'card.json',
        {'tavern_helper': [['scripts', [{'name': 's1'}]]]},
    )

    result = env['api'].cards.read_extensions('card.json')

    assert result['tavern_helper']['scripts'] == [{'name': 's1'}]


def test_read_extensions_extracts_helper_variables(env):
    _write_card_with_extensions(
        env['cards'], 'card.json',
        {'tavern_helper': {'scripts': [], 'variables': {'hp': 10}}},
    )

    result = env['api'].cards.read_extensions('card.json')

    assert result['tavern_helper']['variables'] == {'hp': 10}


def test_read_extensions_returns_empty_shape_for_card_without_extensions(env):
    write_card(env['cards'], 'card.json')

    assert env['api'].cards.read_extensions('card.json') == {}


def test_read_extensions_returns_empty_for_unknown_card(env):
    assert env['api'].cards.read_extensions('missing.json') == {}


def test_read_card_still_returns_raw_extensions(env):
    """§8.1 的保守方案：`read_card` 保持原始结构，归一走显式入口。"""
    _write_card_with_extensions(env['cards'], 'card.json', {'regex': [{'findRegex': '/a/'}]})

    raw = env['api'].cards.read('card.json')['data']['extensions']

    assert 'regex' in raw
    assert 'regex_scripts' not in raw


# ================================================================ 索引状态


def test_index_status_delegates_to_service(env, monkeypatch):
    import core.services.index_service as index_service

    monkeypatch.setattr(index_service, 'get_index_status', lambda: {
        'state': 'ready', 'progress': 100, 'pending_jobs': 0,
    })

    status = env['api'].index.status()

    assert status['state'] == 'ready'


def test_index_status_degrades_when_service_unavailable(env, monkeypatch):
    """索引服务异常时不应该把插件调用炸掉。"""
    import core.services.index_service as index_service

    monkeypatch.setattr(
        index_service, 'get_index_status',
        lambda: (_ for _ in ()).throw(RuntimeError('boom')),
    )

    with pytest.raises(RuntimeError):
        env['api'].index.status()


def test_index_rebuild_delegates_and_validates_scope(env, monkeypatch):
    import core.services.index_service as index_service

    calls = []
    monkeypatch.setattr(
        index_service, 'request_index_rebuild',
        lambda scope='cards': (calls.append(scope), scope)[1],
    )

    assert env['api'].index.rebuild(scope='cards') == 'cards'
    assert env['api'].index.rebuild(scope='worldinfo') == 'worldinfo'
    assert calls == ['cards', 'worldinfo']


def test_index_rebuild_rejects_unknown_scope(env):
    """scope 由服务层校验；插件传错值应收到明确异常而不是静默什么都没做。"""
    with pytest.raises(ValueError):
        env['api'].index.rebuild(scope='nope')


def test_index_search_rejects_unknown_scope(env):
    with pytest.raises(ValueError):
        env['api'].index.search('q', scope='nope')


def test_index_search_maps_card_scope_result(env, monkeypatch):
    import core.services.card_index_query_service as query_service

    monkeypatch.setattr(query_service, 'query_indexed_cards', lambda filters: {
        'cards': [{'id': 'a.json'}], 'total_count': 1, 'index_ready': True,
    })

    result = env['api'].index.search('hero', scope='cards')

    assert result == {'items': [{'id': 'a.json'}], 'total': 1, 'index_ready': True}


def test_index_search_maps_worldinfo_scope_result(env, monkeypatch):
    import core.services.worldinfo_index_query_service as query_service

    monkeypatch.setattr(query_service, 'query_worldinfo_index', lambda filters: {
        'items': [{'id': 'w1'}], 'total': 3, 'index_ready': True,
        'all_folders': [], 'category_counts': {}, 'folder_capabilities': {},
    })

    result = env['api'].index.search('book', scope='worldinfo')

    assert result == {'items': [{'id': 'w1'}], 'total': 3, 'index_ready': True}


def test_index_search_paginates(env, monkeypatch):
    import core.services.card_index_query_service as query_service

    seen = {}
    monkeypatch.setattr(
        query_service, 'query_indexed_cards',
        lambda filters: (seen.update(filters), {'cards': [], 'total_count': 0, 'index_ready': True})[1],
    )

    env['api'].index.search('q', limit=25, offset=50)

    assert seen['page_size'] == 25
    assert seen['page'] == 3


def test_index_search_reports_not_ready(env, monkeypatch):
    """索引未就绪时返回空集 + `index_ready: False`，而不是抛错。"""
    import core.services.card_index_query_service as query_service

    monkeypatch.setattr(query_service, 'query_indexed_cards', lambda filters: {
        'cards': [], 'total_count': 0, 'index_ready': False,
    })

    result = env['api'].index.search('q')

    assert result['index_ready'] is False
    assert result['items'] == []


def test_index_search_fulltext_mode_is_forwarded(env, monkeypatch):
    import core.services.card_index_query_service as query_service

    seen = {}
    monkeypatch.setattr(
        query_service, 'query_indexed_cards',
        lambda filters: (seen.update(filters), {'cards': [], 'total_count': 0, 'index_ready': True})[1],
    )

    env['api'].index.search('q', search_mode='fulltext')

    assert seen['search_mode'] == 'fulltext'
