"""入口（entries）契约测试：全局键、分级准入、上限与 `core:` 前缀隔离。

对应设计文档 2.2 的「入口（entries）规范（D1）」「入口 kind 准入分级（D5）」
「坞槽位（D6）」。这些是宿主与插件之间的硬契约，任何一条被破坏都会让第三方插件
在坞/命令面板里出现「越权」或「消失」的行为。
"""

import pytest

from core.plugins.entries import (
    CORE_ENTRY_PREFIX,
    DEFAULT_ENTRY_TIER,
    ENTRY_KINDS,
    MAX_DOCK_ENTRIES_PER_PLUGIN,
    MAX_DOCK_SLOTS,
    MAX_ENTRIES_PER_PLUGIN,
    SURFACE_TYPES,
    TARGET_KINDS,
    apply_tier,
    build_entry_key,
    entry_kind_allowed,
    is_host_entry_key,
    normalize_entries,
    split_entry_key,
    unknown_entry_keys,
)


def _entry(entry_id='demo-entry', **overrides):
    payload = {'id': entry_id, 'kind': 'dock', 'label': '演示入口'}
    payload.update(overrides)
    return payload


# --- 全局键 -----------------------------------------------------------------


def test_build_entry_key_is_plugin_scoped():
    assert build_entry_key('demo-plugin', 'open-demo') == 'demo-plugin:open-demo'


def test_same_entry_id_across_plugins_does_not_collide():
    first = build_entry_key('plugin-a', 'open')
    second = build_entry_key('plugin-b', 'open')

    assert first != second
    assert split_entry_key(first) == ('plugin-a', 'open')
    assert split_entry_key(second) == ('plugin-b', 'open')


def test_core_prefix_is_reserved_for_host_entries():
    key = f'{CORE_ENTRY_PREFIX}settings'

    assert is_host_entry_key(key) is True
    assert split_entry_key(key) is None
    # 插件 id 正则不含 `:`，因此插件键不可能落进宿主命名空间
    assert is_host_entry_key(build_entry_key('demo-plugin', 'x')) is False


def test_split_entry_key_rejects_malformed_keys():
    assert split_entry_key('demo-plugin') is None
    assert split_entry_key(':open') is None
    assert split_entry_key('demo-plugin:') is None
    assert split_entry_key(None) is None


# --- 归属分级准入（D5） -----------------------------------------------------


@pytest.mark.parametrize('kind', ['command', 'context', 'settings', 'dock', 'batch'])
@pytest.mark.parametrize('tier', ['official', 'verified', 'community'])
def test_common_kinds_are_allowed_for_every_tier(kind, tier):
    assert entry_kind_allowed(kind, tier) is True


@pytest.mark.parametrize('kind', ['status', 'nav'])
def test_status_and_nav_require_official_or_verified(kind):
    assert entry_kind_allowed(kind, 'official') is True
    assert entry_kind_allowed(kind, 'verified') is True
    assert entry_kind_allowed(kind, 'community') is False


def test_unknown_kind_is_never_allowed():
    assert entry_kind_allowed('toolbar', 'official') is False
    assert entry_kind_allowed('', 'official') is False


# --- batch kind（批量操作菜单的落点） ---------------------------------------


def test_batch_kind_is_accepted_by_the_contract():
    """`kind: "batch"` 是批量操作菜单的落点（D1）。

    没有它，插件无法把「对选中卡片整体执行」注册到批量菜单——旧版只能挤进
    右键菜单，而右键菜单的作用域是**右键目标**，与全局选中集不是一回事。
    """
    assert 'batch' in ENTRY_KINDS

    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('analyze-selected', kind='batch')],
    )

    assert [item['id'] for item in entries] == ['analyze-selected']
    assert entries[0]['kind'] == 'batch'
    assert warnings == []


@pytest.mark.parametrize('tier', ['official', 'verified', 'community'])
def test_batch_kind_is_allowed_for_every_tier(tier):
    """`batch` 对所有 tier 开放（它不是高权限落点，只是菜单项）。"""
    assert entry_kind_allowed('batch', tier) is True


def test_community_batch_entry_survives_tier_filter():
    """社区插件的 batch 入口不得被 tier 过滤掉（与 status/nav 相反）。"""
    declared, _ = normalize_entries('demo-plugin', [_entry('bulk', kind='batch')])

    kept, warnings = apply_tier('demo-plugin', declared, tier='community')

    assert [item['id'] for item in kept] == ['bulk']
    assert warnings == []


def test_unknown_kind_is_still_rejected_after_adding_batch():
    """新增 kind 不能把白名单放宽成「什么都收」。"""
    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('x', kind='batch-job')],
    )

    assert entries == []
    assert any('batch-job' in item for item in warnings)


# --- when.target（右键菜单的求值目标） --------------------------------------


def test_when_target_is_normalized_and_kept():
    """`when.target` 必须被保留——它是 context 入口「只在右键分类时可用」的唯一表达。"""
    for value in ('folder', 'card', 'any'):
        entries, warnings = normalize_entries(
            'demo-plugin', [_entry('a', kind='context', when={'target': value})],
        )

        assert entries[0]['when'] == {'target': value}, value
        assert warnings == [], value


def test_invalid_when_target_is_rejected_with_warning():
    """非法值必须被丢弃 + 警告，而不是原样透传给前端求值。"""
    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('a', kind='context', when={'target': 'category'})],
    )

    assert entries[0]['when'] == {}
    assert any('target' in item for item in warnings)


def test_when_target_coexists_with_other_conditions():
    """`target` 与 `mode` / `selection` 可以并存（右键菜单会一起求值）。"""
    entries, warnings = normalize_entries(
        'demo-plugin',
        [_entry('a', kind='context', when={
            'mode': ['cards'], 'target': 'folder', 'selection': 'any',
        })],
    )

    assert entries[0]['when'] == {
        'mode': ['cards'], 'target': 'folder', 'selection': 'any',
    }
    assert warnings == []


def test_target_kinds_are_a_closed_set():
    assert TARGET_KINDS == frozenset({'folder', 'card', 'any'})


def test_community_status_entry_is_dropped_with_warning():
    """D5：tier 由 catalog 决定，manifest 解析阶段不做准入过滤，注册表侧用 apply_tier。"""
    raw = [_entry('status-badge', kind='status'), _entry('open', kind='command')]

    declared, _ = normalize_entries('demo-plugin', raw)
    assert [item['id'] for item in declared] == ['status-badge', 'open']

    kept, warnings = apply_tier('demo-plugin', declared, tier='community')

    assert [item['id'] for item in kept] == ['open']
    assert any('status' in item for item in warnings)


def test_verified_status_entry_is_kept():
    declared, _ = normalize_entries('demo-plugin', [_entry('status-badge', kind='status')])

    kept, warnings = apply_tier('demo-plugin', declared, tier='verified')

    assert [item['id'] for item in kept] == ['status-badge']
    assert kept[0]['tier'] == 'verified'
    assert warnings == []


def test_unknown_tier_falls_back_to_community():
    declared, _ = normalize_entries('demo-plugin', [_entry()])

    kept, _ = apply_tier('demo-plugin', declared, tier='platinum')

    assert kept[0]['tier'] == DEFAULT_ENTRY_TIER


def test_apply_tier_does_not_mutate_input():
    declared, _ = normalize_entries('demo-plugin', [_entry()])

    kept, _ = apply_tier('demo-plugin', declared, tier='official')

    assert kept[0] is not declared[0]
    assert 'tier' not in declared[0]


# --- 字段规范化 -------------------------------------------------------------


def test_entry_kinds_and_surface_types_are_closed_sets():
    assert ENTRY_KINDS == frozenset({
        'dock', 'nav', 'settings', 'context', 'command', 'status', 'batch',
    })
    assert SURFACE_TYPES == frozenset({'panel', 'modal', 'page', 'sheet'})


def test_dock_slot_limits_are_host_owned_constants():
    """D6：坞槽位由宿主分配，插件 priority 只是建议值。"""
    assert MAX_DOCK_SLOTS == 8
    assert MAX_DOCK_ENTRIES_PER_PLUGIN == 2


def test_priority_is_advisory_and_defaults_when_invalid():
    entries, _ = normalize_entries(
        'demo-plugin',
        [_entry('a', priority=5), _entry('b', priority='high'), _entry('c')],
    )

    assert entries[0]['priority'] == 5
    assert entries[1]['priority'] == 100
    assert entries[2]['priority'] == 100


def test_duplicate_entry_id_within_plugin_is_dropped():
    entries, warnings = normalize_entries('demo-plugin', [_entry('same'), _entry('same')])

    assert [item['id'] for item in entries] == ['same']
    assert any('重复' in item for item in warnings)


def test_entries_limit_drops_the_excess():
    raw = [_entry(f'entry-{index}', kind='command') for index in range(20)]

    entries, warnings = normalize_entries('demo-plugin', raw)

    assert len(entries) == MAX_ENTRIES_PER_PLUGIN
    assert any('上限' in item for item in warnings)


def test_invalid_surface_type_drops_the_entry():
    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('bad', surface={'type': 'window'})],
    )

    assert entries == []
    assert any('surface.type' in item for item in warnings)


def test_surface_defaults_to_panel():
    entries, _ = normalize_entries('demo-plugin', [_entry('a', surface={})])

    assert entries[0]['surface'] == {'type': 'panel'}


def test_contexts_drop_unknown_modes_only():
    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('a', contexts=['cards', 'nope', 'chats'])],
    )

    assert entries[0]['contexts'] == ['cards', 'chats']
    assert any('nope' in item for item in warnings)


def test_when_expression_is_normalized():
    entries, warnings = normalize_entries(
        'demo-plugin',
        [_entry('a', when={
            'mode': ['cards', 'bogus'],
            'selection': 'single',
            'config': {'requireKeys': ['api_key', '']},
            'hostVersion': '>=1.0.0',
            'unknownKey': 1,
        })],
    )

    when = entries[0]['when']

    assert when['mode'] == ['cards']
    assert when['selection'] == 'single'
    assert when['config'] == {'requireKeys': ['api_key']}
    assert when['hostVersion'] == '>=1.0.0'
    assert 'unknownKey' not in when
    assert any('bogus' in item for item in warnings)
    assert any('unknownKey' in item for item in warnings)


def test_invalid_selection_is_ignored():
    entries, warnings = normalize_entries(
        'demo-plugin', [_entry('a', when={'selection': 'lots'})],
    )

    assert entries[0]['when'] == {}
    assert any('selection' in item for item in warnings)


def test_non_list_entries_are_ignored():
    entries, warnings = normalize_entries('demo-plugin', {'id': 'a'})

    assert entries == []
    assert any('数组' in item for item in warnings)


def test_entry_payload_is_json_serializable():
    import json

    entries, _ = normalize_entries('demo-plugin', [_entry('a', badge=3)])

    assert json.loads(json.dumps(entries))[0]['key'] == 'demo-plugin:a'


def test_unknown_entry_keys_helper_reports_offenders():
    assert unknown_entry_keys({'id': 'a', 'surfaces': {}, 'label': 'x'}) == ['surfaces']
    assert unknown_entry_keys({'id': 'a', 'kind': 'dock', 'label': 'x'}) == []
    assert unknown_entry_keys('not-a-dict') == []
