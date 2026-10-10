"""宿主图标名契约测试（设计文档 2.2「图标名契约（D4）」）。

D4 承诺图标名整表 Stable：允许新增，删除/改名走 deprecation。因此这里断言的是
**契约行为**（解析规则、命名空间区分、缓存一致性），不是具体图标数量。
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import icons as icons_module


@pytest.fixture(autouse=True)
def _reset_cache():
    icons_module.reset_cache_for_tests()
    yield
    icons_module.reset_cache_for_tests()


# --- 命名空间区分 -----------------------------------------------------------


def test_host_icon_names_are_flat_identifiers():
    assert icons_module.is_host_icon_name('wand') is True
    assert icons_module.is_host_icon_name('chevron-down') is True


@pytest.mark.parametrize('value', [
    'assets/logo.svg',
    'logo.svg',
    'assets\\logo.svg',
    '',
    None,
    '   ',
])
def test_asset_paths_are_not_host_icon_names(value):
    assert icons_module.is_host_icon_name(value) is False


# --- 索引内容 ---------------------------------------------------------------


def test_index_covers_all_four_sprites():
    sprites = {record['sprite'] for record in icons_module.icon_index().values()}

    assert sprites == set(icons_module.HOST_ICON_SPRITES)


def test_known_icon_resolves_to_its_sprite():
    assert icons_module.sprite_for_icon('wand') == 'ui.svg'
    assert icons_module.sprite_for_icon('bolt') == 'ui.svg'


def test_unknown_icon_resolves_to_empty():
    assert icons_module.sprite_for_icon('definitely-not-an-icon') == ''
    assert icons_module.resolve_icon('definitely-not-an-icon') == {}
    assert icons_module.sprite_for_icon(None) == ''


def test_resolve_icon_returns_full_record():
    record = icons_module.resolve_icon('wand')

    assert record['name'] == 'wand'
    assert record['sprite'] == 'ui.svg'
    assert record['category'] == 'ui'
    assert 'wand' in record['keywords']


def test_icon_names_are_unique_across_sprites():
    """同名图标跨精灵重复会让 `<use>` 解析产生歧义，契约要求全局唯一。"""
    seen = {}
    for sprite in icons_module.HOST_ICON_SPRITES:
        path = os.path.join(icons_module.icons_dir(), sprite)
        with open(path, 'r', encoding='utf-8') as handle:
            source = handle.read()
        for name in icons_module._ICON_ID_PATTERN.findall(source):
            assert name not in seen, f'图标名 {name} 同时出现在 {seen.get(name)} 与 {sprite}'
            seen[name] = sprite


# --- 导出与缓存 -------------------------------------------------------------


def test_list_host_icons_is_sorted_and_json_friendly():
    import json

    icons = icons_module.list_host_icons()

    assert icons, '至少应解析出一个宿主图标'
    names = [item['name'] for item in icons]
    assert names == sorted(names)
    assert set(icons[0]) == {'name', 'sprite', 'category', 'keywords'}
    assert json.loads(json.dumps(icons))


def test_list_host_icons_does_not_leak_cache():
    """调用方修改返回值不得污染进程内缓存。"""
    first = icons_module.list_host_icons()
    first[0]['name'] = 'tampered'

    assert icons_module.list_host_icons()[0]['name'] != 'tampered'


def test_index_is_cached_until_reset():
    first = icons_module.icon_index()

    assert icons_module.icon_index() is first

    icons_module.reset_cache_for_tests()

    assert icons_module.icon_index() is not first


def test_icons_dir_points_inside_internal_dir():
    """PyInstaller 打包态 `static/` 只读，必须从 INTERNAL_DIR 读取。"""
    from core.config import INTERNAL_DIR

    assert icons_module.icons_dir().startswith(str(INTERNAL_DIR))
    assert os.path.isdir(icons_module.icons_dir())
