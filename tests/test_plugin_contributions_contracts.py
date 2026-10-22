"""贡献（contributions）契约测试：三原语、落点/插槽、容量与节点级容错。

对应设计文档 §4.4–§4.6（菜单树 / 插槽 / 命令）、§4.9（校验与容错）、
§5（v1 落点与插槽）与 ADR-0009/0013/0015。

规则本体在 `core/plugins/contract.py`（宿主与 `stm-plugin-check` 的单一事实源）；
`core/plugins/contributions.py` 只是宿主适配层（契约调用 + 图标检查 + 计数）。
这里两侧都覆盖：契约常量的钉死属于「契约本身」，宿主适配层保证 manifest 侧
拿到的 warnings/结构是前端可以直接消费的形状。
"""

import json

import pytest

from core.plugins import contract
from core.plugins.contributions import (
    check_contribution_icons,
    contribution_counts,
    issues_to_warnings,
    normalize_contributions,
)


# ------------------------------------------------------------------ v1 落点 / 插槽


@pytest.mark.parametrize('placement', contract.MENU_PLACEMENTS)
def test_every_menu_placement_is_accepted(placement):
    menus, issues = contract.normalize_menu_roots([{
        'id': 'demo',
        'placement': placement,
        'type': 'item',
        'label': '演示',
        'action': {'type': 'url', 'url': 'https://example.com'},
    }])

    assert issues == [], placement
    assert menus[0]['placement'] == placement


@pytest.mark.parametrize('slot_name', contract.SLOT_NAMES)
def test_every_named_slot_is_accepted(slot_name):
    slots, issues = contract.normalize_slots([{
        'id': 'demo-slot',
        'slot': slot_name,
        'module': 'frontend/views/section.js',
        'export': 'mountSection',
    }])

    assert issues == [], slot_name
    assert slots[0]['slot'] == slot_name


@pytest.mark.parametrize('mode', contract.KNOWN_MODES)
def test_every_empty_mode_slot_is_accepted(mode):
    slots, issues = contract.normalize_slots([{
        'id': f'empty-{mode.replace("_", "-")}',
        'slot': f'{contract.EMPTY_SLOT_PREFIX}{mode}',
        'module': 'frontend/views/empty.js',
        'export': 'mountEmpty',
    }])

    assert issues == [], mode
    assert slots[0]['slot'] == f'empty.{mode}'


def test_seven_menu_placements_are_exactly_the_v1_list():
    assert contract.MENU_PLACEMENTS == (
        'context.folder',
        'context.card',
        'context.footer',
        'batch.actions',
        'commandPalette',
        'dock',
        'settings.nav',
    )


def test_five_named_slots_are_exactly_the_v1_list():
    assert contract.SLOT_NAMES == (
        'settings.section',
        'header.actions',
        'card.detail.tabs',
        'page.cards.toolbar',
        'page.worldinfo.toolbar',
    )


def test_empty_slots_cover_all_eight_work_modes():
    assert contract.EMPTY_SLOT_PREFIX == 'empty.'
    assert len(contract.KNOWN_MODES) == 8

    for mode in contract.KNOWN_MODES:
        assert contract.is_known_slot(f'empty.{mode}'), mode
    assert contract.is_known_slot('empty.unknown-mode') is False


def test_unknown_placement_and_slot_are_rejected():
    assert contract.is_known_placement('toolbar') is False
    assert contract.is_known_placement('dock') is True
    assert contract.is_known_placement('context.card') is True
    assert contract.is_known_slot('header.action') is False
    assert contract.is_known_slot('settings.section') is True


def test_contribution_primitives_and_limits_are_pinned():
    assert contract.MENU_NODE_TYPES == ('item', 'submenu', 'separator')
    assert contract.ACTION_TYPES == ('surface', 'command', 'url')
    assert contract.DEFAULT_ORDER == 100
    assert contract.MAX_MENU_NODES_PER_PLUGIN == 64
    assert contract.MAX_MENU_DEPTH == 3
    assert contract.MAX_COMMANDS_PER_PLUGIN == 32
    assert contract.MAX_SLOTS_PER_PLUGIN == 16
    # dock 槽位由宿主渲染约束（全局 8、单插件 2）
    assert contract.MAX_DOCK_SLOTS == 8
    assert contract.MAX_DOCK_PER_PLUGIN == 2


# ------------------------------------------------------------------ 三原语归一化


def _valid_contributions():
    return {
        'commands': [
            {
                'id': 'open-workbench',
                'title': '打开工作台',
                'shortcut': 'ctrl+shift+a',
                'module': 'frontend/commands.js',
                'export': 'openWorkbench',
            },
        ],
        'slots': [
            {
                'id': 'settings-body',
                'slot': 'settings.section',
                'title': 'AI 设置',
                'order': 10,
                'module': 'frontend/views/settingsSection.js',
                'export': 'mountSettingsSection',
            },
        ],
        'menus': [
            {
                'id': 'workbench',
                'placement': 'dock',
                'type': 'item',
                'label': 'AI 助手',
                'icon': 'wand',
                'badge': 3,
                'when': {'mode': ['cards'], 'selection': 'any'},
                'action': {'type': 'command', 'id': 'open-workbench'},
            },
            {
                'id': 'tools',
                'placement': 'context.card',
                'type': 'submenu',
                'label': '工具',
                'children': [
                    {'id': 'url-doc', 'type': 'item', 'label': '文档', 'action': {
                        'type': 'url', 'url': 'https://example.com/doc',
                    }},
                    {'id': 'divider', 'type': 'separator'},
                    {'id': 'surface-hub', 'type': 'item', 'label': '打开 Hub', 'action': {
                        'type': 'surface', 'id': 'hub',
                    }},
                ],
            },
        ],
    }


def test_valid_contributions_normalize_to_host_shape():
    normalized, issues = contract.normalize_contributions(_valid_contributions())

    assert issues == []
    assert len(normalized['commands']) == 1
    command = normalized['commands'][0]
    assert command == {
        'id': 'open-workbench',
        'title': '打开工作台',
        'description': '',
        'icon': '',
        'shortcut': 'Ctrl+Shift+A',
        'when': {},
        'module': 'frontend/commands.js',
        'export': 'openWorkbench',
    }

    assert len(normalized['slots']) == 1
    slot = normalized['slots'][0]
    assert slot['slot'] == 'settings.section'
    assert slot['order'] == 10
    assert slot['when'] == {}

    menus = normalized['menus']
    assert [node['id'] for node in menus] == ['workbench', 'tools']
    root = menus[0]
    assert root['placement'] == 'dock'
    assert root['type'] == 'item'
    assert root['action'] == {'type': 'command', 'id': 'open-workbench'}
    assert root['when'] == {'mode': ['cards'], 'selection': 'any'}
    assert root['badge'] == 3
    assert root['order'] == contract.DEFAULT_ORDER
    # 节点默认值总是补齐（前端可无条件读取）
    for key in ('description', 'icon', 'disabledHint', 'children'):
        assert key in root

    submenu = menus[1]
    assert submenu['type'] == 'submenu'
    assert [child['type'] for child in submenu['children']] == ['item', 'separator', 'item']
    separator = submenu['children'][1]
    assert separator['action'] is None
    assert separator['children'] == []
    # 子节点不允许 placement（落点由根节点决定）
    assert 'placement' not in separator


def test_contributions_are_json_serializable():
    normalized, _ = contract.normalize_contributions(_valid_contributions())

    payload = json.loads(json.dumps(normalized, ensure_ascii=False))

    assert payload['menus'][0]['id'] == 'workbench'


def test_contributions_must_be_object():
    normalized, issues = contract.normalize_contributions(['not', 'an', 'object'])

    assert normalized == {'menus': [], 'slots': [], 'commands': []}
    assert any(issue['code'] == 'contributions_invalid' for issue in issues)


def test_empty_contributions_are_valid():
    normalized, issues = contract.normalize_contributions(None)

    assert normalized == {'menus': [], 'slots': [], 'commands': []}
    assert issues == []


# ------------------------------------------------------------------ 菜单节点容错


def _item(node_id='demo', placement='dock', **overrides):
    payload = {
        'id': node_id,
        'placement': placement,
        'type': 'item',
        'label': '演示',
        'action': {'type': 'url', 'url': 'https://example.com'},
    }
    payload.update(overrides)
    return payload


def _leaf(node_id='leaf'):
    """子节点：不允许 placement（落点只属于根节点）。"""
    return {
        'id': node_id,
        'type': 'item',
        'label': '子项',
        'action': {'type': 'url', 'url': 'https://example.com'},
    }


def test_unknown_placement_drops_only_that_node():
    menus, issues = contract.normalize_menu_roots([
        _item('bad', placement='toolbar'),
        _item('ok'),
    ])

    assert [node['id'] for node in menus] == ['ok']
    assert any(issue['code'] == 'menu_placement_unknown' for issue in issues)


def test_invalid_menu_node_is_dropped_but_other_nodes_load():
    menus, issues = contract.normalize_menu_roots([
        {'id': 'Bad_Id', 'placement': 'dock', 'type': 'item', 'label': '非法 id'},
        {'id': 'bad-type', 'placement': 'dock', 'type': 'toolbar', 'label': '非法 type'},
        {'id': 'no-action', 'placement': 'dock', 'type': 'item', 'label': '缺 action'},
        _item('ok'),
    ])

    assert [node['id'] for node in menus] == ['ok']
    assert len(issues) >= 3


def test_unknown_node_subkey_only_warns():
    menus, issues = contract.normalize_menu_roots([
        _item('ok', surfaces={'type': 'panel'}),
    ])

    assert [node['id'] for node in menus] == ['ok']
    assert any(issue['code'] == 'menu_unknown_key' for issue in issues)


def test_x_prefixed_node_keys_are_silently_ignored():
    menus, issues = contract.normalize_menu_roots([
        _item('ok', **{'x-experimental': {'anything': True}}),
    ])

    assert [node['id'] for node in menus] == ['ok']
    assert issues == []


def test_duplicate_menu_ids_drop_the_later_node():
    menus, issues = contract.normalize_menu_roots([_item('same'), _item('same', label='重复')])

    assert [node['id'] for node in menus] == ['same']
    assert menus[0]['label'] == '演示'
    assert any(issue['code'] == 'menu_id_duplicate' for issue in issues)


def test_submenu_requires_children():
    menus, issues = contract.normalize_menu_roots([
        {'id': 'empty-sub', 'placement': 'dock', 'type': 'submenu', 'label': '空菜单'},
    ])

    assert menus == []
    assert any('children' in issue['field'] for issue in issues)


def test_submenu_children_are_normalized_recursively():
    menus, issues = contract.normalize_menu_roots([{
        'id': 'root',
        'placement': 'batch.actions',
        'type': 'submenu',
        'label': 'AI',
        'children': [
            {'id': 'sub', 'type': 'submenu', 'label': '更多', 'children': [_leaf('deep')]},
        ],
    }])

    assert issues == []
    assert menus[0]['children'][0]['children'][0]['id'] == 'deep'


def test_menu_depth_limit_is_three_levels():
    too_deep = [{
        'id': 'l1',
        'placement': 'dock',
        'type': 'submenu',
        'label': 'L1',
        'children': [{
            'id': 'l2',
            'type': 'submenu',
            'label': 'L2',
            'children': [{
                'id': 'l3',
                'type': 'submenu',
                'label': 'L3',
                'children': [_item('l4')],
            }],
        }],
    }]

    menus, issues = contract.normalize_menu_roots(too_deep)

    assert menus == []
    assert any(issue['code'] == 'menu_depth_exceeded' for issue in issues)


def test_menu_capacity_is_64_nodes():
    nodes = [_item(f'node-{index}') for index in range(70)]

    menus, issues = contract.normalize_menu_roots(nodes)

    assert len(menus) == contract.MAX_MENU_NODES_PER_PLUGIN
    assert any(issue['code'] == 'menu_capacity' for issue in issues)


def test_menu_depth_allows_root_submenu_item():
    """三层（根 → 子菜单 → 子项）是允许的最深结构。"""
    menus, issues = contract.normalize_menu_roots([{
        'id': 'root',
        'placement': 'context.folder',
        'type': 'submenu',
        'label': '根',
        'children': [{
            'id': 'sub',
            'type': 'submenu',
            'label': '子菜单',
            'children': [_leaf('leaf')],
        }],
    }])

    assert issues == []
    assert menus[0]['children'][0]['children'][0]['id'] == 'leaf'


# ------------------------------------------------------------------ action 引用


def test_command_action_must_reference_declared_command():
    contributions, issues = contract.normalize_contributions({
        'menus': [_item('menu-item', action={'type': 'command', 'id': 'missing'})],
        'commands': [],
    })

    assert contributions['menus'] == []
    assert any(issue['code'] == 'action_command_missing' for issue in issues)


def test_command_action_resolves_when_declared():
    contributions, issues = contract.normalize_contributions({
        'commands': [{
            'id': 'open', 'title': '打开',
            'module': 'frontend/commands.js', 'export': 'open',
        }],
        'menus': [_item('menu-item', action={'type': 'command', 'id': 'open'})],
    })

    assert issues == []
    assert contributions['menus'][0]['action'] == {'type': 'command', 'id': 'open'}


def test_url_action_requires_http_schema():
    menus, issues = contract.normalize_menu_roots([
        _item('http-ok', action={'type': 'url', 'url': 'http://example.com'}),
        _item('https-ok', action={'type': 'url', 'url': 'https://example.com'}),
        _item('bad', action={'type': 'url', 'url': 'javascript:alert(1)'}),
        _item('relative', action={'type': 'url', 'url': '/local/path'}),
    ])

    assert [node['id'] for node in menus] == ['http-ok', 'https-ok']
    assert any(issue['code'] == 'action_invalid' for issue in issues)


def test_unknown_action_type_is_dropped():
    menus, issues = contract.normalize_menu_roots([
        _item('bad', action={'type': 'modal', 'id': 'x'}),
    ])

    assert menus == []
    assert any(issue['code'] == 'action_invalid' for issue in issues)


# ------------------------------------------------------------------ 命令 / 插槽


def _command(command_id='open', **overrides):
    payload = {
        'id': command_id,
        'title': '打开',
        'module': 'frontend/commands.js',
        'export': 'open',
    }
    payload.update(overrides)
    return payload


def test_command_shortcut_is_normalized():
    commands, issues = contract.normalize_commands([
        _command(shortcut='ctrl + shift + a'),
    ])

    assert issues == []
    assert commands[0]['shortcut'] == 'Ctrl+Shift+A'


def test_command_shortcut_requires_modifier():
    commands, issues = contract.normalize_commands([_command(shortcut='F5')])

    assert commands[0]['shortcut'] == ''
    assert any(issue['code'] == 'shortcut_invalid' for issue in issues)


def test_command_duplicate_shortcut_keeps_first():
    commands, issues = contract.normalize_commands([
        _command('first', shortcut='Ctrl+K'),
        _command('second', shortcut='Ctrl+K'),
    ])

    assert [item['id'] for item in commands] == ['first', 'second']
    assert commands[1]['shortcut'] == ''
    assert any(issue['code'] == 'shortcut_duplicate' for issue in issues)


def test_command_capacity_is_32():
    commands, issues = contract.normalize_commands([
        _command(f'cmd-{index}') for index in range(40)
    ])

    assert len(commands) == contract.MAX_COMMANDS_PER_PLUGIN
    assert any(issue['code'] == 'command_capacity' for issue in issues)


def test_command_missing_module_is_dropped():
    commands, issues = contract.normalize_commands([
        _command('ok'),
        {'id': 'no-module', 'title': '缺模块', 'export': 'x'},
    ])

    assert [item['id'] for item in commands] == ['ok']
    assert any(issue['code'] == 'command_invalid' for issue in issues)


def test_slot_capacity_is_16():
    slots, issues = contract.normalize_slots([
        {
            'id': f'slot-{index}',
            'slot': 'settings.section',
            'module': 'frontend/views/section.js',
            'export': 'mountSection',
        }
        for index in range(20)
    ])

    assert len(slots) == contract.MAX_SLOTS_PER_PLUGIN
    assert any(issue['code'] == 'slot_capacity' for issue in issues)


def test_slot_unknown_slot_name_is_dropped():
    slots, issues = contract.normalize_slots([{
        'id': 'bad',
        'slot': 'somewhere.else',
        'module': 'frontend/views/section.js',
        'export': 'mount',
    }])

    assert slots == []
    assert any(issue['code'] == 'slot_unknown' for issue in issues)


def test_slot_empty_mode_is_accepted():
    slots, issues = contract.normalize_slots([{
        'id': 'empty-cards',
        'slot': 'empty.cards',
        'module': 'frontend/views/empty.js',
        'export': 'mountEmpty',
    }])

    assert issues == []
    assert slots[0]['slot'] == 'empty.cards'


# ------------------------------------------------------------------ when 条件


def test_when_unknown_keys_are_ignored_with_warning():
    normalized, issues = contract.normalize_when({'target': 'card', 'mode': ['cards']})

    assert normalized == {'mode': ['cards']}
    assert any(issue['code'] == 'when_unknown_key' for issue in issues)


def test_when_unknown_mode_is_dropped():
    normalized, issues = contract.normalize_when({'mode': ['cards', 'unknown-mode']})

    assert normalized == {'mode': ['cards']}
    assert any(issue['code'] == 'when_unknown_mode' for issue in issues)


def test_when_invalid_selection_is_dropped():
    normalized, issues = contract.normalize_when({'selection': 'lots'})

    assert normalized == {}
    assert any(issue['code'] == 'when_invalid' for issue in issues)


# ------------------------------------------------------------------ 宿主适配层


def test_host_adapter_normalizes_and_converts_issues_to_warnings():
    contributions, warnings = normalize_contributions('demo-plugin', _valid_contributions())

    assert contributions['menus'][0]['id'] == 'workbench'
    assert warnings == []


def test_host_adapter_reports_node_level_problems_as_warnings():
    contributions, warnings = normalize_contributions('demo-plugin', {
        'menus': [_item('bad', placement='toolbar')],
    })

    assert contributions['menus'] == []
    assert warnings
    assert all(isinstance(item, str) for item in warnings)
    assert any('toolbar' in item for item in warnings)


def test_issues_to_warnings_prefixes_field():
    warnings = issues_to_warnings([
        {'severity': 'warning', 'field': 'frontend.contributions.menus[0]', 'message': '出问题了'},
    ])

    assert warnings == ['frontend.contributions.menus[0]: 出问题了']


def test_contribution_icon_check_flags_unknown_host_icon():
    contributions = {
        'menus': [_item('menu', icon='not-a-real-icon')],
        'slots': [],
        'commands': [_command('cmd', icon='wand')],
    }

    warnings = check_contribution_icons(contributions)

    assert any('not-a-real-icon' in warning for warning in warnings)
    # 已知宿主图标与插件资源路径都不警告
    assert not any('wand' in warning for warning in warnings)


def test_plugin_asset_icon_paths_are_not_checked_as_host_icons():
    contributions = {
        'menus': [_item('menu', icon='frontend/assets/icon.svg')],
        'slots': [],
        'commands': [],
    }

    assert check_contribution_icons(contributions) == []


def test_contribution_counts_cover_tree_and_primitives():
    contributions, _ = normalize_contributions('demo-plugin', _valid_contributions())

    counts = contribution_counts(contributions)

    # 2 个根节点 + 3 个子节点（含 separator）
    assert counts['menus'] == 5
    assert counts['menu_roots'] == 2
    assert counts['slots'] == 1
    assert counts['commands'] == 1
