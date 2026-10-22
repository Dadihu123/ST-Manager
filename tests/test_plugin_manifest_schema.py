"""manifest v3 JSON Schema 与前端 d.ts 生成物的同步测试。

核心断言：`docs/plugin-manifest.schema.json` / `docs/plugin-api.d.ts` 必须与
`core/plugins/contract.py`（契约单一事实源）和生成器常量一致。改了
contract.py 或生成器却没重跑 `python tools/gen_plugin_api_docs.py`，这里会直接失败。
"""

import json
import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import contract
from tools import gen_plugin_api_docs
from tools.gen_plugin_api_docs import (
    DTS_PATH,
    SCHEMA_PATH,
    check_dts,
    check_schema,
    main,
    render_dts,
    render_schema,
)


@pytest.fixture(scope='module')
def schema():
    assert os.path.isfile(SCHEMA_PATH), 'docs/plugin-manifest.schema.json 不存在，先运行生成器'
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _walk_refs(node, path='$'):
    if isinstance(node, dict):
        ref = node.get('$ref')
        if isinstance(ref, str):
            yield path, ref
        for key, value in node.items():
            yield from _walk_refs(value, f'{path}.{key}')
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_refs(value, f'{path}[{index}]')


# ---------------------------------------------------------------- 生成与同步


def test_schema_exists_and_is_in_sync():
    assert os.path.isfile(SCHEMA_PATH)
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as handle:
        on_disk = handle.read()
    assert on_disk == render_schema(), (
        'docs/plugin-manifest.schema.json 与生成器不一致；'
        '请运行 python tools/gen_plugin_api_docs.py'
    )
    assert check_schema() is True


def test_dts_exists_and_is_in_sync():
    assert os.path.isfile(DTS_PATH)
    with open(DTS_PATH, 'r', encoding='utf-8') as handle:
        on_disk = handle.read()
    assert on_disk == render_dts(), (
        'docs/plugin-api.d.ts 与生成器不一致；请运行 python tools/gen_plugin_api_docs.py'
    )
    assert check_dts() is True


def test_all_generated_artifacts_are_in_sync(capsys):
    assert main(['--check']) == 0
    captured = capsys.readouterr()
    for label in (
        'docs/plugin-api.md',
        'docs/plugin-manifest.schema.json',
        'docs/plugin-api.d.ts',
        'tools/stm_plugin_check.py',
    ):
        assert label in captured.out


def test_generator_imports_contract_as_single_source_of_truth():
    source_path = os.path.join(PROJECT_ROOT, 'tools', 'gen_plugin_api_docs.py')
    with open(source_path, 'r', encoding='utf-8') as handle:
        source = handle.read()
    assert 'from core.plugins import contract' in source


def test_schema_is_valid_json_and_refs_resolve(schema):
    defs = schema['$defs']
    for path, ref in _walk_refs(schema):
        prefix = '#/$defs/'
        assert ref.startswith(prefix), f'{path} 的 $ref 必须指向本地 $defs: {ref}'
        target = ref[len(prefix):]
        assert target in defs, f'{path} 引用了不存在的 $defs.{target}'


# ---------------------------------------------------------------- schema ↔ contract 枚举一致


def test_schema_versions_match_contract(schema):
    assert schema['x-contract-version'] == contract.MANIFEST_VERSION
    assert schema['x-generated-by'] == 'tools/gen_plugin_api_docs.py'
    assert schema['properties']['manifest_version']['const'] == contract.MANIFEST_VERSION
    assert schema['properties']['api_version']['const'] == contract.API_VERSION
    assert schema['required'] == ['manifest_version', 'id', 'version', 'api_version']


def test_schema_patterns_match_contract(schema):
    assert schema['properties']['id']['pattern'] == contract.PLUGIN_ID_PATTERN.pattern
    assert schema['properties']['version']['pattern'] == contract.SEMVER_PATTERN.pattern
    assert (
        schema['properties']['min_app_version']['pattern']
        == contract.SEMVER_PATTERN.pattern
    )
    node_id = schema['$defs']['nodeId']
    assert node_id['pattern'] == contract.NODE_ID_PATTERN.pattern
    command = schema['$defs']['command']
    assert command['properties']['export']['pattern'] == contract.EXPORT_NAME_PATTERN.pattern
    backend = schema['$defs']['backend']
    assert backend['properties']['register']['pattern'] == contract.ENTRY_NAME_PATTERN.pattern
    jobs_items = backend['properties']['jobs']['items']
    assert jobs_items['pattern'] == contract.JOB_TYPE_PATTERN.pattern


def test_schema_rename_removed_fields(schema):
    """v2 的 `permissions` 与 `frontend.entries` 不得出现在 schema 里。"""
    assert 'permissions' not in schema['properties']
    frontend = schema['$defs']['frontend']['properties']
    assert 'entries' not in frontend
    assert set(frontend) == set(contract.KNOWN_FRONTEND_KEYS)
    assert set(schema['properties']) == set(contract.KNOWN_TOP_LEVEL_KEYS)
    assert set(schema['$defs']['contributions']['properties']) == set(
        contract.KNOWN_CONTRIBUTION_KEYS
    )


def test_schema_structural_objects_are_strict(schema):
    """结构键 / 节点键 / action / when 都必须 additionalProperties: false。"""
    assert schema['additionalProperties'] is False
    assert scheme_allow_x(schema)
    for name in ('backend', 'frontend', 'contributions', 'when'):
        assert schema['$defs'][name]['additionalProperties'] is False, name
        assert scheme_allow_x(schema['$defs'][name]), name
    for variant in schema['$defs']['action']['oneOf']:
        assert variant['additionalProperties'] is False
        assert scheme_allow_x(variant)
    for name in gen_plugin_api_docs._MENU_VARIANT_SPECS:
        definition = schema['$defs'][name[0]]
        assert definition['additionalProperties'] is False, name[0]
        assert scheme_allow_x(definition), name[0]


def scheme_allow_x(node):
    return '^x-' in (node.get('patternProperties') or {})


def test_schema_render_mode_and_capabilities(schema):
    frontend = schema['$defs']['frontend']['properties']
    assert frontend['render_mode']['enum'] == list(contract.RENDER_MODES)
    assert frontend['render_mode']['default'] == contract.DEFAULT_RENDER_MODE
    capabilities = schema['properties']['capabilities']
    assert capabilities['x-known-capabilities'] == sorted(contract.KNOWN_CAPABILITIES)
    # 未知能力位宿主保留（只警告），因此 schema 不用 enum 限制。
    assert 'enum' not in capabilities['items']


def test_schema_backend_hooks_known_values(schema):
    hooks = schema['$defs']['backend']['properties']['hooks']
    assert hooks['items']['x-known-hooks'] == sorted(contract.KNOWN_HOOKS)
    assert 'enum' not in hooks['items']


def test_schema_menu_placements_and_node_types(schema):
    root_item = schema['$defs']['menuRootItem']
    assert root_item['properties']['placement']['enum'] == list(contract.MENU_PLACEMENTS)
    assert root_item['properties']['type']['enum'] == list(contract.MENU_NODE_TYPES)
    # 子节点不允许 placement（落点由根节点决定）
    for name in ('menuChildItem', 'menuChildSubmenu', 'menuChildSeparator',
                 'menuGrandchildItem', 'menuGrandchildSeparator'):
        assert 'placement' not in schema['$defs'][name]['properties'], name


def test_schema_menu_depth_is_encoded_in_structure(schema):
    """契约允许 3 层：根 → 子 → 孙；孙节点不能再嵌套 submenu。"""
    assert contract.MAX_MENU_DEPTH == 3
    root_submenu = schema['$defs']['menuRootSubmenu']['properties']['children']
    child_refs = [item['$ref'] for item in root_submenu['items']['oneOf']]
    assert child_refs == [
        '#/$defs/menuChildItem', '#/$defs/menuChildSubmenu', '#/$defs/menuChildSeparator',
    ]
    child_submenu = schema['$defs']['menuChildSubmenu']['properties']['children']
    grandchild_refs = [item['$ref'] for item in child_submenu['items']['oneOf']]
    assert grandchild_refs == [
        '#/$defs/menuGrandchildItem', '#/$defs/menuGrandchildSeparator',
    ]
    assert 'children' not in schema['$defs']['menuGrandchildItem']['properties']


def test_schema_menu_node_type_rules(schema):
    assert set(schema['$defs']['menuRootItem']['required']) == {'id', 'placement', 'type', 'label', 'action'}
    assert 'children' not in schema['$defs']['menuRootItem']['properties']
    assert set(schema['$defs']['menuRootSubmenu']['required']) == {'id', 'placement', 'type', 'label', 'children'}
    assert 'action' not in schema['$defs']['menuRootSubmenu']['properties']
    assert set(schema['$defs']['menuRootSeparator']['required']) == {'id', 'placement', 'type'}
    for forbidden in ('label', 'action', 'children'):
        assert forbidden not in schema['$defs']['menuRootSeparator']['properties']


def test_schema_action_types_match_contract(schema):
    definitions = schema['$defs']['action']['oneOf']
    action_types = [item['properties']['type']['const'] for item in definitions]
    assert action_types == list(contract.ACTION_TYPES)
    url_action = definitions[2]
    assert url_action['properties']['url']['pattern'] == '^https?://'
    command_action = definitions[1]
    assert set(command_action['required']) == {'type', 'id'}


def test_schema_when_keys_match_contract(schema):
    when = schema['$defs']['when']
    assert set(when['properties']) == set(contract.KNOWN_WHEN_KEYS)
    assert when['properties']['selection']['enum'] == sorted(contract.SELECTION_MODES)
    assert when['properties']['indexState']['enum'] == sorted(contract.INDEX_STATES)
    assert when['properties']['mode']['items']['enum'] == sorted(contract.KNOWN_MODES)


def test_schema_slots_and_capacities_match_contract(schema):
    empty_slots = [
        f'{contract.EMPTY_SLOT_PREFIX}{mode}' for mode in sorted(contract.KNOWN_MODES)
    ]
    slot_def = schema['$defs']['slot']
    assert slot_def['properties']['slot']['enum'] == list(contract.SLOT_NAMES) + empty_slots
    assert set(slot_def['required']) == {'id', 'slot', 'module', 'export'}

    contributions = schema['$defs']['contributions']['properties']
    assert contributions['menus']['maxItems'] == contract.MAX_MENU_NODES_PER_PLUGIN
    assert contributions['slots']['maxItems'] == contract.MAX_SLOTS_PER_PLUGIN
    assert contributions['commands']['maxItems'] == contract.MAX_COMMANDS_PER_PLUGIN
    assert schema['$defs']['command']['properties']['shortcut']['pattern'].startswith('^')


def test_schema_form_schema_constraints(schema):
    field = schema['$defs']['formField']
    assert field['properties']['type']['enum'] == sorted(contract.SCHEMA_TYPES)
    assert set(field['properties']) == set(contract.SCHEMA_ALLOWED_KEYS)


# ---------------------------------------------------------------- d.ts ↔ contract 一致


def test_dts_unions_match_contract():
    text = render_dts()
    assert "export type RenderMode = 'declarative' | 'custom';" in text
    placement = ' | '.join(f"'{item}'" for item in contract.MENU_PLACEMENTS)
    assert f'export type MenuPlacement = {placement};' in text
    slot = ' | '.join(f"'{item}'" for item in contract.SLOT_NAMES)
    assert f'export type SlotName = {slot};' in text
    known = ' | '.join("'%s'" % item for item in sorted(contract.KNOWN_CAPABILITIES))
    assert f'export type KnownCapability = {known};' in text


def test_dts_covers_required_contract_types():
    text = render_dts()
    for symbol in (
        'CreateRootOptions',
        'PluginRootApi',
        'OverlaySpec',
        'OverlaysApi',
        'ContributionsApi',
        'ContributionUpdatePatch',
        'SlotContribution',
        'CommandContribution',
        'MenuRootNode',
        'MenuAction',
        'WhenClause',
        'HostState',
        'HostSelection',
        'SurfaceSpec',
        'SurfacesApi',
        'PluginApiV3',
        'PluginManifestV3',
    ):
        assert f'interface {symbol}' in text or f'type {symbol}' in text, symbol
    assert 'api.contributions.update' in text or 'ContributionsApi' in text
    assert 'portal' in text
    assert 'empty.${HostMode}' in text


def test_dts_marks_generated_and_deleted_v2_surface():
    text = render_dts()
    assert 'gen_plugin_api_docs.py' in text
    assert 'entries: {' not in text
    assert 'registerModal' not in text


def test_dts_plugin_api_members_match_build_api():
    """d.ts 的 `PluginApiV3` 顶层成员必须与 `buildApi()` 实际暴露的键一致。"""
    text = render_dts()
    start = text.index('export interface PluginApiV3 {')
    block = text[start:]
    end = block.index('\n}\n')
    names = set()
    for line in block[:end].splitlines()[1:]:
        match = re.match(r'^  (?:readonly )?([A-Za-z][A-Za-z0-9_]*)', line)
        if match:
            names.add(match.group(1))

    exposed = set(gen_plugin_api_docs.collect_frontend_members())
    assert names == exposed, (
        f'd.ts 缺少 {sorted(exposed - names)}；d.ts 多出 {sorted(names - exposed)}'
    )
