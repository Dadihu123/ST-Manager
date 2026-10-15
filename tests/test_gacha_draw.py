"""抽卡接口与服务层测试。

覆盖：
- 稀有度派生（收藏 → UR，Token 四档 → N/R/SR/SSR，阈值边界）
- 单抽 / 十连的数量与不重复语义
- 卡池边界：空池、不足 10 张（重复标记）、恰好 1 张
- 十连保底：有 SR+ 时触发、无 SR+ 时静默跳过
- 筛选条件对齐 list_cards（收藏、排除标签、Token 范围、非递归）
- 不污染 ctx.cache.cards（稀有度不得写回共享字典）
"""

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import cards as cards_api
from core.data import ui_store as ui_store_module
from core.services.gacha_service import (
    TOKEN_DANGER,
    TOKEN_EXTREME,
    TOKEN_WARN,
    derive_rarity,
    draw_cards,
    normalize_count,
)


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def _ts(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def _make_card(
    card_id,
    *,
    char_name=None,
    category='',
    import_time=0.0,
    last_modified=0.0,
    token_count=0,
    tags=None,
    is_favorite=False,
):
    return {
        'id': card_id,
        'category': category,
        'char_name': char_name or card_id,
        'filename': card_id,
        'tags': list(tags or []),
        'is_favorite': is_favorite,
        'ui_summary': '',
        'last_modified': last_modified,
        'import_time': import_time,
        'token_count': token_count,
        'thumb_url': f'/api/thumbnail/{card_id}',
    }


class _FakeCache:
    def __init__(self, cards):
        self.cards = list(cards)
        self.visible_folders = []
        self.category_counts = {}
        self.global_tags = set()
        self.lock = threading.Lock()
        self.initialized = True

    def reload_from_db(self):
        raise AssertionError('reload_from_db should not run in gacha tests')


def _install(monkeypatch, tmp_path, cards):
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps({}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    fake_cache = _FakeCache(cards)
    monkeypatch.setattr(cards_api.ctx, 'cache', fake_cache)
    return fake_cache


def _post(client, payload):
    return client.post('/api/draw_cards', json=payload)


# ---------------------------------------------------------------- 稀有度派生

def test_derive_rarity_favorite_is_ur():
    assert derive_rarity(_make_card('a.png', is_favorite=True, token_count=0)) == 'UR'


def test_derive_rarity_token_tiers():
    assert derive_rarity(_make_card('n.png', token_count=0)) == 'N'
    assert derive_rarity(_make_card('n.png', token_count=TOKEN_WARN)) == 'N'
    assert derive_rarity(_make_card('r.png', token_count=TOKEN_WARN + 1)) == 'R'
    assert derive_rarity(_make_card('r.png', token_count=TOKEN_DANGER)) == 'R'
    assert derive_rarity(_make_card('sr.png', token_count=TOKEN_DANGER + 1)) == 'SR'
    assert derive_rarity(_make_card('sr.png', token_count=TOKEN_EXTREME)) == 'SR'
    assert derive_rarity(_make_card('ssr.png', token_count=TOKEN_EXTREME + 1)) == 'SSR'


def test_derive_rarity_handles_missing_and_bad_token_count():
    assert derive_rarity({'id': 'x.png'}) == 'N'
    assert derive_rarity({'id': 'x.png', 'token_count': None}) == 'N'
    assert derive_rarity({'id': 'x.png', 'token_count': 'not-a-number'}) == 'N'
    assert derive_rarity(None) == 'N'


# ---------------------------------------------------------------- count 规整

@pytest.mark.parametrize(
    'raw,expected',
    [(1, 1), (10, 10), (0, 1), (-3, 1), (99, 10), ('7', 7), ('abc', 1), (None, 1)],
)
def test_normalize_count_clamps_to_valid_range(raw, expected):
    assert normalize_count(raw) == expected


# ---------------------------------------------------------------- 抽取语义

def _pool(n, **kwargs):
    return [_make_card(f'c{i}.png', **kwargs) for i in range(n)]


def test_draw_single_returns_one_card_with_rarity():
    result = draw_cards(_pool(5), 1)
    assert len(result['cards']) == 1
    assert result['cards'][0]['rarity'] in ('N', 'R', 'SR', 'SSR', 'UR')
    assert result['pool_size'] == 5
    assert result['pool_exhausted'] is False


def test_draw_ten_from_large_pool_has_no_duplicates():
    result = draw_cards(_pool(40), 10)
    ids = [card['id'] for card in result['cards']]
    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert not any(card.get('duplicate') for card in result['cards'])
    assert result['pool_exhausted'] is False


def test_draw_ten_from_small_pool_marks_duplicates():
    result = draw_cards(_pool(3), 10)
    assert len(result['cards']) == 10
    assert result['pool_size'] == 3
    assert result['pool_exhausted'] is True
    # 3 张卡池出 10 张，必然有重复
    assert any(card.get('duplicate') for card in result['cards'])
    # 第一次出现不应被标为重复
    seen = set()
    for card in result['cards']:
        if card['id'] in seen:
            assert card.get('duplicate') is True
        else:
            assert not card.get('duplicate')
        seen.add(card['id'])


def test_draw_ten_from_single_card_pool():
    result = draw_cards(_pool(1), 10)
    assert len(result['cards']) == 10
    assert result['pool_size'] == 1
    assert result['pool_exhausted'] is True
    assert result['cards'][0].get('duplicate') is None
    assert all(card.get('duplicate') for card in result['cards'][1:])


def test_draw_from_empty_pool_returns_empty_result():
    result = draw_cards([], 10)
    assert result['cards'] == []
    assert result['pool_size'] == 0
    assert result['pity_applied'] is False


def test_draw_does_not_mutate_cached_cards():
    """稀有度是派生字段，绝不能写回 ctx.cache.cards 里的共享字典。"""
    pool = _pool(5, token_count=TOKEN_EXTREME + 1)
    draw_cards(pool, 3)
    for card in pool:
        assert 'rarity' not in card
        assert 'duplicate' not in card


def test_draw_with_idless_cards_does_not_raise():
    """缺 id 的卡片不应被互相误判为重复。"""
    pool = [
        {'char_name': 'A', 'token_count': 0},
        {'char_name': 'B', 'token_count': 0},
    ]
    result = draw_cards(pool, 2)
    assert len(result['cards']) == 2
    assert not any(card.get('duplicate') for card in result['cards'])


# ---------------------------------------------------------------- 保底

def test_pity_applied_when_high_rarity_exists():
    pool = _pool(20, token_count=0) + [
        _make_card('high.png', token_count=TOKEN_EXTREME + 1)
    ]
    result = draw_cards(pool, 10, apply_pity=True)
    assert result['pity_applied'] is True
    rarities = {card['rarity'] for card in result['cards']}
    assert rarities & {'SR', 'SSR', 'UR'}


def test_pity_skipped_silently_when_no_high_rarity():
    """卡池全是 N 时，保底静默跳过而不是报错。"""
    result = draw_cards(_pool(20, token_count=0), 10, apply_pity=True)
    assert result['pity_applied'] is False
    assert len(result['cards']) == 10
    assert {card['rarity'] for card in result['cards']} == {'N'}


def test_pity_disabled_by_flag():
    pool = _pool(20, token_count=0) + [
        _make_card('high.png', token_count=TOKEN_EXTREME + 1)
    ]
    result = draw_cards(pool, 10, apply_pity=False)
    assert result['pity_applied'] is False


def test_pity_not_applied_for_single_draw():
    """单抽不改变基础概率。"""
    pool = _pool(20, token_count=0) + [
        _make_card('high.png', token_count=TOKEN_EXTREME + 1)
    ]
    result = draw_cards(pool, 1, apply_pity=True)
    assert result['pity_applied'] is False
    assert len(result['cards']) == 1


def test_pity_can_apply_when_pool_smaller_than_count():
    pool = _pool(2, token_count=0) + [
        _make_card('high.png', token_count=TOKEN_EXTREME + 1)
    ]
    result = draw_cards(pool, 10, apply_pity=True)
    assert result['pity_applied'] is True
    assert any(card['rarity'] in ('SR', 'SSR', 'UR') for card in result['cards'])


# ---------------------------------------------------------------- 接口层

def test_draw_cards_empty_pool_returns_empty_pool_code(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, [])
    res = _post(_make_test_app().test_client(), {'count': 10})
    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['code'] == 'EMPTY_POOL'
    assert payload['pool_size'] == 0


def test_draw_cards_single(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(5))
    res = _post(_make_test_app().test_client(), {'count': 1})
    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['count'] == 1
    assert len(payload['cards']) == 1
    assert payload['pool_size'] == 5


def test_draw_cards_ten(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(30))
    res = _post(_make_test_app().test_client(), {'count': 10})
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['count'] == 10
    assert payload['pool_exhausted'] is False


def test_draw_cards_reports_exhausted_pool(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(4))
    res = _post(_make_test_app().test_client(), {'count': 10})
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['pool_size'] == 4
    assert payload['pool_exhausted'] is True
    assert payload['count'] == 10


def test_draw_cards_defaults_to_single(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(5))
    res = _post(_make_test_app().test_client(), {})
    payload = res.get_json()
    assert payload['count'] == 1


# ---------------------------------------------------------------- 筛选对齐

def test_draw_respects_favorite_filter(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('fav.png', is_favorite=True),
            _make_card('plain.png', is_favorite=False),
        ],
    )
    res = _post(_make_test_app().test_client(), {'count': 10, 'fav_filter': 'included'})
    payload = res.get_json()
    assert {card['id'] for card in payload['cards']} == {'fav.png'}
    # 收藏卡派生为 UR
    assert all(card['rarity'] == 'UR' for card in payload['cards'])


def test_draw_respects_excluded_tags(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('keep.png', tags=['keep']),
            _make_card('drop.png', tags=['nsfw']),
        ],
    )
    res = _post(_make_test_app().test_client(), {
        'count': 10,
        'excluded_tags': ['nsfw'],
    })
    payload = res.get_json()
    assert {card['id'] for card in payload['cards']} == {'keep.png'}


def test_draw_respects_token_range(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('small.png', token_count=100),
            _make_card('big.png', token_count=TOKEN_DANGER + 1),
        ],
    )
    res = _post(_make_test_app().test_client(), {
        'count': 10,
        'token_min': TOKEN_DANGER,
    })
    payload = res.get_json()
    assert {card['id'] for card in payload['cards']} == {'big.png'}


def test_draw_respects_import_date_range(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('old.png', import_time=_ts(2026, 1, 1), last_modified=_ts(2026, 1, 1)),
            _make_card('new.png', import_time=_ts(2026, 6, 1), last_modified=_ts(2026, 6, 1)),
        ],
    )
    res = _post(_make_test_app().test_client(), {
        'count': 10,
        'import_date_from': '2026-05-01',
    })
    payload = res.get_json()
    assert {card['id'] for card in payload['cards']} == {'new.png'}


def test_draw_respects_non_recursive_root(monkeypatch, tmp_path):
    """recursive=False 且根目录时，只应抽到 category 为空的卡。"""
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('root.png', category=''),
            _make_card('sub.png', category='foo'),
        ],
    )
    res = _post(_make_test_app().test_client(), {
        'count': 10,
        'category': '根目录',
        'recursive': False,
    })
    payload = res.get_json()
    assert {card['id'] for card in payload['cards']} == {'root.png'}


def test_draw_respects_category_recursive(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('a.png', category='foo'),
            _make_card('b.png', category='foo/bar'),
            _make_card('c.png', category='other'),
        ],
    )
    client = _make_test_app().test_client()
    recursive = _post(client, {'count': 10, 'category': 'foo', 'recursive': True}).get_json()
    assert {card['id'] for card in recursive['cards']} == {'a.png', 'b.png'}

    strict = _post(client, {'count': 10, 'category': 'foo', 'recursive': False}).get_json()
    assert {card['id'] for card in strict['cards']} == {'a.png'}


def test_draw_rejects_inverted_token_range(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(3))
    res = _post(_make_test_app().test_client(), {
        'count': 1,
        'token_min': 5000,
        'token_max': 100,
    })
    assert res.status_code == 400
    assert res.get_json()['success'] is False


def test_draw_rejects_malformed_date(monkeypatch, tmp_path):
    _install(monkeypatch, tmp_path, _pool(3))
    res = _post(_make_test_app().test_client(), {
        'count': 1,
        'import_date_from': 'not-a-date',
    })
    assert res.status_code == 400
    assert res.get_json()['success'] is False


# ---------------------------------------------------------------- random_card 回归

def test_random_card_respects_favorite_filter(monkeypatch, tmp_path):
    """回归：random_card 此前忽略 fav_filter，会抽到当前视图看不见的卡。"""
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('fav.png', is_favorite=True),
            _make_card('plain.png', is_favorite=False),
        ],
    )
    client = _make_test_app().test_client()
    for _ in range(12):
        payload = client.post('/api/random_card', json={'fav_filter': 'included'}).get_json()
        assert payload['success'] is True
        assert payload['card']['id'] == 'fav.png'


def test_random_card_respects_excluded_tags(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('keep.png', tags=['keep']),
            _make_card('drop.png', tags=['nsfw']),
        ],
    )
    client = _make_test_app().test_client()
    for _ in range(12):
        payload = client.post('/api/random_card', json={'excluded_tags': ['nsfw']}).get_json()
        assert payload['card']['id'] == 'keep.png'


def test_random_card_respects_token_range(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        tmp_path,
        [
            _make_card('small.png', token_count=100),
            _make_card('big.png', token_count=TOKEN_DANGER + 1),
        ],
    )
    client = _make_test_app().test_client()
    for _ in range(12):
        payload = client.post('/api/random_card', json={'token_min': TOKEN_DANGER}).get_json()
        assert payload['card']['id'] == 'big.png'


def test_random_card_empty_pool_message_unchanged(monkeypatch, tmp_path):
    """保持既有返回文案，避免破坏调用方与既有测试。"""
    _install(monkeypatch, tmp_path, [])
    payload = _make_test_app().test_client().post('/api/random_card', json={}).get_json()
    assert payload['success'] is False
    assert payload['msg'] == '当前范围内没有卡片'
