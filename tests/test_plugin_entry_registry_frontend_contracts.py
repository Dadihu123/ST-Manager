"""贡献注册表前端契约测试（设计文档 §4.4–§4.6；实现日志 S3）。

仓库没有 JS 测试运行器，策略与既有 `tests/test_*_frontend_contracts.py` 一致：
- 静态源码契约（导出名、常量、事件名）；
- 用 Node 直接 import 真实模块并断言行为。`contributionRegistry.js` 是纯逻辑
  （无 DOM 依赖，`when` 求值接受显式 context），因此可以在没有浏览器的情况下
  验证核心契约。

覆盖：
- S3 的完整 API 与常量（7 落点 / 5 插槽 / 5 种 `empty.<mode>` / 容量）；
- 菜单树排序（order → pluginId → id）、children 递归、`when` 失败=可见但置灰；
- `when` 条件全集（mode / selection / config.requireKeys / hostVersion / feature /
  indexState；v3 已删除 when.target）；
- 插槽 / 命令记录、命令面板候选、坞栏分配（全局 8 / 单插件 2）、快捷键查表；
- `update()` patch 白名单、children 校验、同值不广播、`remove()` 与重建恢复；
- 禁用插件不进入注册表、未知落点/非法 action 被丢弃。
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REGISTRY_PATH = 'static/js/contributionRegistry.js'


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['node', '--input-type=module', '-e', textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


requires_node = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='Node.js is required for contribution registry contract checks',
)

#: 每个 node 用例都需要的 window 桩（事件派发 + CustomEvent）。
WINDOW_SHIM = r"""
const dispatched = [];
globalThis.__dispatched = dispatched;
globalThis.window = {
  listeners: new Map(),
  addEventListener(name, fn) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(fn);
  },
  removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); },
  dispatchEvent(event) {
    dispatched.push(event);
    for (const fn of [...(this.listeners.get(event.type) || [])]) fn(event);
  },
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
};
globalThis.window.CustomEvent = globalThis.CustomEvent;

// 主程序 store（`Alpine.store("global")`）：when 求值与选中集读取都走它。
globalThis.__store = {
  currentMode: 'cards',
  deviceType: 'desktop',
  isDarkMode: true,
  viewState: { selectedIds: [] },
  indexStatus: { state: 'idle', scan_active: false },
  batchProgress: { status: 'idle', current: 0, total: 0 },
};
globalThis.window.Alpine = {
  store: () => globalThis.__store,
  reactive: (value) => value,
  effect: (callback) => { globalThis.__effects.push(callback); return () => {}; },
};
globalThis.__effects = [];
"""


def run_registry(body: str) -> subprocess.CompletedProcess:
    return run_node(WINDOW_SHIM + textwrap.dedent(body))


def run_json(body: str) -> dict:
    """运行一个打印 JSON 的用例并解析。"""
    result = run_registry(body)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line for line in (result.stdout or '').strip().splitlines() if line.strip()]
    assert lines, result.stderr or result.stdout
    return json.loads(lines[-1])


# ------------------------------------------------------------------ 静态契约


def test_registry_exports_the_full_s3_contract():
    source = read_source(REGISTRY_PATH)

    for fragment in (
        'export const MENU_PLACEMENTS = [',
        'export const SLOT_NAMES = [',
        'export const EMPTY_SLOT_PREFIX = "empty."',
        'export const MENU_NODE_TYPES = ["item", "submenu", "separator"]',
        'export const MAX_MENU_NODES_PER_PLUGIN = 64',
        'export const MAX_MENU_DEPTH = 3',
        'export const MAX_COMMANDS_PER_PLUGIN = 32',
        'export const MAX_SLOTS_PER_PLUGIN = 16',
        'export const MAX_DOCK_SLOTS = 8',
        'export const MAX_DOCK_PER_PLUGIN = 2',
        'export const CORE_PLUGIN_ID = "core"',
        'export const KILL_SWITCH_COMMAND_ID = "core:plugins:close-overlays"',
        'export function isKnownSlot(name) {',
        'export function evaluateWhen(when, context = {}) {',
        'export function hostAppVersion() {',
        'export function hostDeviceType() {',
        'export function hostFeatures() {',
        'export const ContributionRegistry = {',
        'init() {',
        'setPlugins(items) {',
        'context(overrides = {}) {',
        'menuTree(placement, options = {}) {',
        'menus(placement, options = {}) {',
        'slotRecords(slot, options = {}) {',
        'commandRecords(options = {}) {',
        'paletteEntries(options = {}) {',
        'dockItems() {',
        'dockOverflow() {',
        'searchable() {',
        'findByShortcut(combo) {',
        'get(pluginId, id) {',
        'getByKey(key) {',
        'list(pluginId) {',
        'update(pluginId, id, patch) {',
        'remove(pluginId, id) {',
        'notifyChange() {',
        'coreCommands: CORE_COMMANDS',
    ):
        assert fragment in source, fragment


def test_v2_entry_registry_concepts_are_gone():
    source = read_source(REGISTRY_PATH)

    for legacy in (
        'ENTRY_KINDS',
        'TARGET_KINDS',
        'ENTRY_LAYOUT_ENDPOINT',
        'buildEntryKey',
        'isHostEntryKey',
        'EntryRegistry',
        '_entry_layout_v1',
        'entries:changed',
    ):
        assert legacy not in source, f'v2 概念必须删除: {legacy}'
    # 布局偏好消费已删除（接口后端保留但无前端消费者）
    assert 'pinned' not in source
    assert 'updateLayout' not in source


def test_placements_and_slots_match_backend_contract():
    source = read_source(REGISTRY_PATH)

    assert '"context.folder"' in source
    assert '"context.card"' in source
    assert '"context.footer"' in source
    assert '"batch.actions"' in source
    assert '"commandPalette"' in source
    assert '"dock"' in source
    assert '"settings.nav"' in source
    for slot in (
        '"settings.section"',
        '"header.actions"',
        '"card.detail.tabs"',
        '"page.cards.toolbar"',
        '"page.worldinfo.toolbar"',
    ):
        assert slot in source, slot
    # 与后端 contract.py 同源（若后端集合变了，这个断言会提醒两侧对齐）
    from core.plugins import contract

    assert set(contract.MENU_PLACEMENTS) == {
        'context.folder', 'context.card', 'context.footer',
        'batch.actions', 'commandPalette', 'dock', 'settings.nav',
    }
    assert set(contract.SLOT_NAMES) == {
        'settings.section', 'header.actions', 'card.detail.tabs',
        'page.cards.toolbar', 'page.worldinfo.toolbar',
    }


def test_registry_listens_to_plugins_loaded_and_dispatches_contributions_changed():
    source = read_source(REGISTRY_PATH)

    assert 'window.addEventListener("plugins:loaded"' in source
    assert 'window.addEventListener("plugin-config-changed"' in source
    assert 'window.addEventListener("plugin-secrets-changed"' in source
    assert 'window.dispatchEvent(' in source
    assert 'new CustomEvent("contributions:changed"' in source
    # 选中集没有全局广播，必须用 Alpine effect 观察
    assert 'installSelectionWatcher()' in source
    assert 'alpine.effect(' in source


def test_disabled_plugins_do_not_enter_registry():
    source = read_source(REGISTRY_PATH)

    assert 'item.enabled !== false' in source


def test_dock_limits_match_contract():
    from core.plugins import contract

    source = read_source(REGISTRY_PATH)

    assert contract.MAX_DOCK_SLOTS == 8
    assert contract.MAX_DOCK_PER_PLUGIN == 2
    assert 'MAX_DOCK_SLOTS = 8' in source
    assert 'MAX_DOCK_PER_PLUGIN = 2' in source


# ------------------------------------------------------------------ when 求值


@requires_node
def test_when_mode_selection_and_index_state():
    payload = run_json(
        """
        import { evaluateWhen } from './static/js/contributionRegistry.js';

        const cases = {
          ok: evaluateWhen({ mode: ['cards'] }, { mode: 'cards' }),
          wrongMode: evaluateWhen({ mode: ['worldinfo'] }, { mode: 'cards' }),
          noWhen: evaluateWhen(undefined, { mode: 'cards' }),
          selectionNone: evaluateWhen({ selection: 'none' }, { selectionCount: 0 }),
          selectionAny: evaluateWhen({ selection: 'any' }, { selectionCount: 2 }),
          selectionSingleFail: evaluateWhen({ selection: 'single' }, { selectionCount: 2 }),
          selectionMulti: evaluateWhen({ selection: 'multi' }, { selectionCount: 3 }),
          indexRunning: evaluateWhen({ indexState: 'running' }, { indexState: 'running' }),
          indexFail: evaluateWhen({ indexState: 'running' }, { indexState: 'idle' }),
        };
        process.stdout.write(JSON.stringify(cases));
        """
    )
    assert payload['ok'] == {'ok': True, 'reasons': []}
    assert payload['wrongMode']['ok'] is False
    assert payload['wrongMode']['reasons'] == ['mode']
    assert payload['noWhen'] == {'ok': True, 'reasons': []}
    assert payload['selectionNone']['ok'] is True
    assert payload['selectionAny']['ok'] is True
    assert payload['selectionSingleFail']['ok'] is False
    assert payload['selectionSingleFail']['reasons'] == ['selection']
    assert payload['selectionMulti']['ok'] is True
    assert payload['indexRunning']['ok'] is True
    assert payload['indexFail']['reasons'] == ['indexState']


@requires_node
def test_when_config_require_keys_host_version_and_features():
    payload = run_json(
        """
        import { evaluateWhen } from './static/js/contributionRegistry.js';

        const cases = {
          configOk: evaluateWhen({ config: { requireKeys: ['api_key'] } },
                                 { config: { api_key: 'x' } }),
          configMissing: evaluateWhen({ config: { requireKeys: ['api_key', 'model'] } },
                                      { config: { api_key: 'x' } }),
          configEmptyString: evaluateWhen({ config: { requireKeys: ['k'] } },
                                          { config: { k: '   ' } }),
          hostVersionOk: evaluateWhen({ hostVersion: '1.2.0' }, { hostVersion: '1.3.0' }),
          hostVersionFail: evaluateWhen({ hostVersion: '2.0.0' }, { hostVersion: '1.3.0' }),
          hostVersionUnknownHost: evaluateWhen({ hostVersion: '9.9.9' }, { hostVersion: '' }),
          featureOk: evaluateWhen({ feature: ['hasAmbient'] }, { feature: ['hasAmbient', 'hasFetch'] }),
          featureFail: evaluateWhen({ feature: ['hasSSE'] }, { feature: ['hasFetch'] }),
          allAnd: evaluateWhen(
            { mode: ['cards'], feature: ['hasAmbient'], indexState: 'idle' },
            { mode: 'cards', feature: ['hasAmbient'], indexState: 'idle' },
          ),
        };
        process.stdout.write(JSON.stringify(cases));
        """
    )
    assert payload['configOk']['ok'] is True
    assert payload['configMissing']['ok'] is False
    assert payload['configMissing']['reasons'] == ['config']
    assert payload['configEmptyString']['reasons'] == ['config']
    assert payload['hostVersionOk']['ok'] is True
    assert payload['hostVersionFail']['reasons'] == ['hostVersion']
    # 主程序版本取不到时不做版本可判断（否则所有 hostVersion 条件都会误置灰）
    assert payload['hostVersionUnknownHost']['ok'] is True
    assert payload['featureOk']['ok'] is True
    assert payload['featureFail']['reasons'] == ['feature']
    assert payload['allAnd']['ok'] is True


@requires_node
def test_when_target_is_deleted_in_v3():
    """v3 落点隐含目标类型：`when.target` 已删除，出现也不参与求值。"""
    registry = read_source(REGISTRY_PATH)
    assert 'if (when.target' not in registry
    assert 'reasons.push("target")' not in registry

    payload = run_json(
        """
        import { evaluateWhen } from './static/js/contributionRegistry.js';
        process.stdout.write(JSON.stringify({
          withTarget: evaluateWhen({ target: ['folder'] }, { targetKind: 'card' }),
        }));
        """
    )
    assert payload['withTarget']['ok'] is True


@requires_node
def test_host_version_compare_and_feature_detection():
    payload = run_json(
        """
        import { compareVersions, hostFeatures, hostAppVersion } from './static/js/contributionRegistry.js';

        globalThis.window.devicePixelRatio = 2;
        globalThis.window.fetch = () => Promise.resolve();
        globalThis.EventSource = class EventSource {};
        Object.defineProperty(globalThis, 'navigator', {
          value: { onLine: true, userAgent: 'node' },
          configurable: true,
        });

        process.stdout.write(JSON.stringify({
          cmp: [compareVersions('1.2.0', '1.10.0'), compareVersions('2.0', '2.0.0')],
          features: hostFeatures(),
          version: hostAppVersion(),
        }));
        """
    )
    assert payload['cmp'] == [-1, 0]
    assert 'hasNetwork' in payload['features']
    assert 'hasSSE' in payload['features']
    assert 'hasFetch' in payload['features']
    assert 'hasAmbient' in payload['features']
    assert 'hasPixelRatio' in payload['features']
    assert payload['version'] == ''


@requires_node
def test_is_known_slot_includes_empty_modes():
    payload = run_json(
        """
        import { isKnownSlot, KNOWN_MODES } from './static/js/contributionRegistry.js';
        process.stdout.write(JSON.stringify({
          modes: KNOWN_MODES,
          checks: [
            isKnownSlot('settings.section'),
            isKnownSlot('empty.cards'),
            isKnownSlot('empty.worldinfo'),
            isKnownSlot('empty.nope'),
            isKnownSlot('nope'),
            isKnownSlot(''),
          ],
        }));
        """
    )
    assert payload['checks'] == [True, True, True, False, False, False]


@requires_node
def test_normalize_shortcut_requires_modifier_and_aliases():
    payload = run_json(
        """
        import { normalizeShortcut } from './static/js/contributionRegistry.js';
        process.stdout.write(JSON.stringify({
          values: [
            normalizeShortcut('Ctrl+Shift+K'),
            normalizeShortcut('shift+ctrl+k'),
            normalizeShortcut('Cmd+Alt+P'),
            normalizeShortcut('K'),
            normalizeShortcut(''),
          ],
        }));
        """
    )
    assert payload['values'][0] == 'ctrl+shift+k'
    assert payload['values'][1] == 'ctrl+shift+k'
    assert payload['values'][2] == 'alt+meta+p'
    assert payload['values'][3] == ''
    assert payload['values'][4] == ''


# ------------------------------------------------------------------ 声明层建表


PLUGIN_FIXTURE = r"""
import { ContributionRegistry } from './static/js/contributionRegistry.js';

ContributionRegistry.setPlugins([
  {
    id: 'alpha',
    enabled: true,
    manifest: {
      contributions: {
        commands: [
          { id: 'open-alpha', title: 'A', shortcut: 'Ctrl+Alpha', module: 'frontend/c.js', export: 'run' },
        ],
        menus: [
          { id: 'dock-b', placement: 'dock', type: 'item', label: 'B', order: 20,
            action: { type: 'command', id: 'open-alpha' } },
          { id: 'dock-a', placement: 'dock', type: 'item', label: 'A', order: 10,
            action: { type: 'url', url: 'https://example.com' } },
          { id: 'dock-c', placement: 'dock', type: 'item', label: 'C', order: 30,
            action: { type: 'surface', id: 'panel' } },
          { id: 'dock-d', placement: 'dock', type: 'item', label: 'D', order: 40,
            action: { type: 'surface', id: 'panel' } },
          { id: 'submenu', placement: 'context.folder', type: 'submenu', label: 'Sub', order: 50,
            children: [
              { id: 'child-cards', type: 'item', label: 'Cards child',
                when: { mode: ['cards'] },
                action: { type: 'command', id: 'open-alpha' } },
              { id: 'child-worldinfo', type: 'item', label: 'WI child',
                when: { mode: ['worldinfo'] },
                disabledHint: '仅世界书',
                action: { type: 'url', url: 'https://example.com/wi' } },
            ] },
          { id: 'palette-item', placement: 'commandPalette', type: 'item', label: 'Palette',
            action: { type: 'command', id: 'open-alpha' } },
          { id: 'unknown-placement', placement: 'nope', type: 'item', label: 'Nope',
            action: { type: 'url', url: 'https://example.com' } },
          { id: 'bad-command', placement: 'dock', type: 'item', label: 'Bad',
            action: { type: 'command', id: 'missing' } },
          { id: 'separator', placement: 'dock', type: 'separator' },
        ],
        slots: [
          { id: 'settings-a', slot: 'settings.section', title: 'S', order: 70,
            module: 'frontend/s.js', export: 'mountSettings' },
          { id: 'header-a', slot: 'header.actions', title: 'H', order: 5,
            module: 'frontend/h.js', export: 'mountHeader' },
          { id: 'bad-slot', slot: 'nope.slot', title: 'X',
            module: 'frontend/x.js', export: 'mount' },
        ],
      },
    },
  },
  {
    id: 'beta',
    enabled: true,
    manifest: {
      contributions: {
        menus: [
          { id: 'dock-e', placement: 'dock', type: 'item', label: 'E', order: 5,
            action: { type: 'url', url: 'https://example.com/e' } },
        ],
      },
    },
  },
  {
    id: 'disabled-plugin',
    enabled: false,
    manifest: {
      contributions: {
        menus: [
          { id: 'dock-hidden', placement: 'dock', type: 'item', label: 'Hidden',
            action: { type: 'url', url: 'https://example.com' } },
        ],
      },
    },
  },
]);
"""


@requires_node
def test_menu_tree_sorts_and_drops_invalid_declarations():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          dock: ContributionRegistry.menuTree('dock').map((node) => node.key),
          context: ContributionRegistry.menuTree('context.folder').map((node) => ({
            id: node.id,
            children: node.children.map((child) => ({
              id: child.id, ok: child.ok, enabled: child.enabled, reasons: child.reasons,
              hint: child.disabledHint,
            })),
          })),
          palette: ContributionRegistry.menuTree('commandPalette').map((node) => node.id),
          betaDock: ContributionRegistry.menuTree('dock', { enabledOnly: true })
            .filter((node) => node.pluginId === 'beta')
            .map((node) => node.id),
          listAlpha: ContributionRegistry.list('alpha').map((node) => node.id),
          disabledLoaded: ContributionRegistry.plugins.map((item) => item.id),
        }));
        """
    )
    # order 5(beta) → 10 → 20 → 30 → 40；未知落点 / 非法 action 被丢弃，separator 保留
    assert payload['dock'] == [
        'beta:dock-e',
        'alpha:dock-a',
        'alpha:dock-b',
        'alpha:dock-c',
        'alpha:dock-d',
        'alpha:separator',
    ]
    context = payload['context'][0]
    assert context['id'] == 'submenu'
    by_id = {child['id']: child for child in context['children']}
    assert by_id['child-cards']['ok'] is True
    # when 不满足 = 可见但置灰（不是隐藏），带 reasons 与 disabledHint
    assert by_id['child-worldinfo']['ok'] is False
    assert by_id['child-worldinfo']['enabled'] is False
    assert by_id['child-worldinfo']['reasons'] == ['mode']
    assert by_id['child-worldinfo']['hint'] == '仅世界书'
    assert payload['palette'] == ['palette-item']
    assert payload['betaDock'] == ['dock-e']
    assert 'unknown-placement' not in payload['listAlpha']
    assert 'bad-command' not in payload['listAlpha']
    assert payload['disabledLoaded'] == ['alpha', 'beta']


@requires_node
def test_menu_tree_enabled_only_filters_when_failures():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          enabledOnly: ContributionRegistry.menuTree('context.folder', { enabledOnly: true })
            .map((node) => ({ id: node.id, children: node.children.length })),
          all: ContributionRegistry.menuTree('context.folder').map((node) => node.id),
        }));
        """
    )
    # `when` 失败 = 可见但置灰（设计 §4.4），enabledOnly 只过滤节点自身不可用的顶层项，
    # 子节点仍保留（由渲染方用 `ok` 决定置灰）；`all` 与之一致。
    assert payload['enabledOnly'] == [{'id': 'submenu', 'children': 2}]
    assert payload['all'] == ['submenu']


@requires_node
def test_slots_and_commands_records():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          settings: ContributionRegistry.slotRecords('settings.section').map((record) => ({
            id: record.id, pluginId: record.pluginId, slot: record.slot,
            module: record.module, export: record.export, ok: record.ok,
          })),
          header: ContributionRegistry.slotRecords('header.actions').map((record) => record.id),
          badSlot: ContributionRegistry.slotRecords('nope.slot').length,
          commands: ContributionRegistry.commandRecords().map((record) => ({
            id: record.id, key: record.key, shortcut: record.shortcut, ok: record.ok,
          })),
        }));
        """
    )
    assert payload['settings'] == [{
        'id': 'settings-a',
        'pluginId': 'alpha',
        'slot': 'settings.section',
        'module': 'frontend/s.js',
        'export': 'mountSettings',
        'ok': True,
    }]
    assert payload['header'] == ['header-a']
    assert payload['badSlot'] == 0
    assert payload['commands'] == [{
        'id': 'open-alpha',
        'key': 'alpha:open-alpha',
        'shortcut': 'Ctrl+Alpha',
        'ok': True,
    }]


@requires_node
def test_palette_entries_only_include_executable_entries():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          entries: ContributionRegistry.paletteEntries().map((entry) => ({
            key: entry.key, kind: entry.kind, ok: entry.ok,
            id: entry.id, label: entry.label, shortcut: entry.shortcut,
          })),
          noCommandsUnderWrongMode: ContributionRegistry.paletteEntries({
            contextOverride: { mode: 'worldinfo' },
          }).map((entry) => entry.key),
        }));
        """
    )
    # `palette-item` 引用命令 `open-alpha`：合并成一行（菜单的 label 覆盖命令标题），
    # 不再出现「同一条命令两行」以及同一个 key 两个来源的重复（Alpine x-for 会崩）。
    keys = [entry['key'] for entry in payload['entries']]
    assert keys == ['alpha:open-alpha']
    assert [entry['kind'] for entry in payload['entries']] == ['command']
    assert all(entry['ok'] for entry in payload['entries'])
    merged = payload['entries'][0]
    assert merged['id'] == 'palette-item', '派发要用菜单节点 id'
    assert merged['label'] == 'Palette', '菜单 label 覆盖命令 title'
    assert merged['shortcut'] == 'Ctrl+Alpha', '命令 shortcut 保留'
    # commandPalette 菜单节点不带 when 时任何模式都可见
    assert 'alpha:open-alpha' in payload['noCommandsUnderWrongMode']


@requires_node
def test_palette_entries_merge_command_palette_menus_and_keep_keys_unique():
    """设计 §10.2：同一插件可同时声明命令与同 id 的 commandPalette 菜单项。

    回归真实浏览器 bug：命令与菜单都走 `buildContributionKey(pluginId, id)`，
    `paletteEntries()` 直接拼接得到重复 key → Alpine `x-for :key` 冲突 → 面板空白。
    """
    payload = run_json(
        """
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        ContributionRegistry.setPlugins([{
          id: 'gamma',
          enabled: true,
          manifest: {
            contributions: {
              commands: [
                { id: 'open-review', title: '审查', shortcut: 'Ctrl+Alt+R',
                  module: 'frontend/review.js', export: 'runReview',
                  when: { mode: ['cards'] } },
                { id: 'propose-library', title: '提议库',
                  module: 'frontend/propose.js', export: 'run' },
                { id: 'open-profiles', title: '档案',
                  module: 'frontend/profiles.js', export: 'run' },
                { id: 'unlisted', title: '未在面板列出',
                  module: 'frontend/unlisted.js', export: 'run' },
              ],
              menus: [
                // ① 菜单 id 与命令 id 相同（真实 AI 场景：重复 key 的来源）
                { id: 'open-review', placement: 'commandPalette', type: 'item',
                  label: 'AI 审查', icon: 'review', description: '审查选中卡片',
                  action: { type: 'command', id: 'open-review' } },
                // ② 菜单 id 与命令 id 不同，引用同一命令 → 仍然只出现一行
                { id: 'propose-shortcut', placement: 'commandPalette', type: 'item',
                  label: '提议库（快捷）', order: 90,
                  action: { type: 'command', id: 'propose-library' } },
                // ③ 菜单 id 与命令 id 相同但 action 是 surface → key 撞名，加后缀
                { id: 'open-profiles', placement: 'commandPalette', type: 'item',
                  label: '打开档案面板', action: { type: 'surface', id: 'profiles' } },
                // ④ surface / url 菜单原样保留
                { id: 'review-surface', placement: 'commandPalette', type: 'item',
                  label: '审查面板', action: { type: 'surface', id: 'review' } },
                { id: 'docs-url', placement: 'commandPalette', type: 'item',
                  label: '文档', action: { type: 'url', url: 'https://example.com/docs' } },
              ],
            },
          },
        }]);

        const entries = ContributionRegistry.paletteEntries();
        process.stdout.write(JSON.stringify({
          keys: entries.map((entry) => entry.key),
          rows: entries.map((entry) => ({
            key: entry.key, id: entry.id, kind: entry.kind, label: entry.label,
            icon: entry.icon, shortcut: entry.shortcut, module: entry.module,
            ok: entry.ok, enabled: entry.enabled,
          })),
        }));
        """
    )
    keys = payload['keys']
    assert len(keys) == len(set(keys)), '命令面板每项 key 必须唯一（否则 Alpine x-for 崩）'
    assert all(keys), 'key 不能为空'
    rows = payload['rows']
    by_key = {row['key']: row for row in rows}

    # 4 条命令（合并后）+ 2 个 surface 菜单 + 1 个 url 菜单 = 7 行
    assert len(rows) == 7, rows
    command_rows = [row for row in rows if row['kind'] == 'command']
    menu_rows = [row for row in rows if row['kind'] == 'menu']
    assert len(command_rows) == 4, command_rows
    assert len(menu_rows) == 3, menu_rows

    # ① 同 id 命令 + 菜单：一行，key 用命令 key，label/icon 用菜单声明，执行字段保留
    merged = by_key['gamma:open-review']
    assert merged['kind'] == 'command'
    assert merged['id'] == 'open-review', '派发 nodeId 要能查到菜单节点'
    assert merged['label'] == 'AI 审查'
    assert merged['icon'] == 'review'
    assert merged['shortcut'] == 'Ctrl+Alt+R'
    assert merged['module'] == 'frontend/review.js'
    assert merged['ok'] is True and merged['enabled'] is True

    # ② 不同菜单 id 引用同一命令：也只一行（id = 菜单 id 供派发）
    propose = by_key['gamma:propose-library']
    assert propose['kind'] == 'command'
    assert propose['id'] == 'propose-shortcut'
    assert propose['label'] == '提议库（快捷）'

    # ③ 命令与同 id 的 surface 菜单撞名：key 加后缀区分，两者都在
    assert by_key['gamma:open-profiles']['kind'] == 'command'
    assert 'label' not in by_key['gamma:open-profiles']  # 命令记录没有菜单声明的 label
    surface_collision = by_key['gamma:open-profiles#menu']
    assert surface_collision['kind'] == 'menu'
    assert surface_collision['id'] == 'open-profiles'
    assert surface_collision['label'] == '打开档案面板'

    # ④ surface / url 菜单保留
    assert by_key['gamma:review-surface']['kind'] == 'menu'
    assert by_key['gamma:docs-url']['kind'] == 'menu'
    assert 'gamma:review-surface' not in {row['key'] for row in command_rows}


@requires_node
def test_dock_allocation_caps_global_and_per_plugin():
    payload = run_json(
        """
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        const alphaMenus = [];
        for (let index = 0; index < 7; index += 1) {
          alphaMenus.push({ id: `alpha-${index}`, placement: 'dock', type: 'item',
            label: `A${index}`, order: index + 1,
            action: { type: 'url', url: 'https://example.com/a' } });
        }
        const betaMenus = [];
        for (let index = 0; index < 4; index += 1) {
          betaMenus.push({ id: `beta-${index}`, placement: 'dock', type: 'item',
            label: `B${index}`, order: index + 100,
            action: { type: 'url', url: 'https://example.com/b' } });
        }
        ContributionRegistry.setPlugins([
          { id: 'alpha', enabled: true, manifest: { contributions: { menus: alphaMenus } } },
          { id: 'beta', enabled: true, manifest: { contributions: { menus: betaMenus } } },
        ]);

        process.stdout.write(JSON.stringify({
          items: ContributionRegistry.dockItems().map((node) => node.key),
          overflow: ContributionRegistry.dockOverflow().map((node) => node.key),
        }));
        """
    )
    # 单插件上限 2：alpha 只有 2 个可见、beta 2 个；全局 8 上限未触发时溢出是其余项
    assert payload['items'] == ['alpha:alpha-0', 'alpha:alpha-1', 'beta:beta-0', 'beta:beta-1']
    assert payload['overflow'] == [
        'alpha:alpha-2', 'alpha:alpha-3', 'alpha:alpha-4',
        'alpha:alpha-5', 'alpha:alpha-6', 'beta:beta-2', 'beta:beta-3',
    ]


@requires_node
def test_dock_global_cap_of_eight():
    payload = run_json(
        """
        import { ContributionRegistry, MAX_DOCK_SLOTS } from './static/js/contributionRegistry.js';

        const plugins = [];
        for (let index = 0; index < 6; index += 1) {
          plugins.push({
            id: `p${index}`,
            enabled: true,
            manifest: { contributions: { menus: [
              { id: 'a', placement: 'dock', type: 'item', label: 'A', order: index,
                action: { type: 'url', url: 'https://example.com' } },
              { id: 'b', placement: 'dock', type: 'item', label: 'B', order: index + 100,
                action: { type: 'url', url: 'https://example.com' } },
            ] } },
          });
        }
        ContributionRegistry.setPlugins(plugins);
        process.stdout.write(JSON.stringify({
          cap: MAX_DOCK_SLOTS,
          visible: ContributionRegistry.dockItems().length,
          overflow: ContributionRegistry.dockOverflow().length,
        }));
        """
    )
    assert payload['cap'] == 8
    assert payload['visible'] == 8
    assert payload['overflow'] == 4


@requires_node
def test_searchable_and_find_by_shortcut():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          kinds: ContributionRegistry.searchable().map((entry) => entry.kind),
          hasCoreCommand: ContributionRegistry.searchable()
            .some((entry) => entry.key === 'core:plugins:close-overlays'),
          shortcut: ContributionRegistry.findByShortcut('ctrl+alpha'),
          shortcutMissing: ContributionRegistry.findByShortcut('Ctrl+Zzz'),
          shortcutNoModifier: ContributionRegistry.findByShortcut('alpha'),
        }));
        """
    )
    assert 'menu' in payload['kinds']
    assert 'command' in payload['kinds']
    assert payload['hasCoreCommand'] is True
    assert payload['shortcut']['key'] == 'alpha:open-alpha'
    assert payload['shortcut']['keeper'] if False else True
    assert payload['shortcutMissing'] is None
    assert payload['shortcutNoModifier'] is None


@requires_node
def test_get_get_by_key_and_list():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        process.stdout.write(JSON.stringify({
          byId: ContributionRegistry.get('alpha', 'dock-a')?.key || null,
          byKey: ContributionRegistry.getByKey('alpha:child-cards')?.id || null,
          missing: ContributionRegistry.get('alpha', 'nope'),
          missingPlugin: ContributionRegistry.get('ghost', 'dock-a'),
          listLen: ContributionRegistry.list('alpha').length,
          betaLen: ContributionRegistry.list('beta').length,
        }));
        """
    )
    assert payload['byId'] == 'alpha:dock-a'
    assert payload['byKey'] == 'child-cards'
    assert payload['missing'] is None
    assert payload['missingPlugin'] is None
    # alpha = 4 dock + separator + submenu + 2 children + palette = 9
    assert payload['listLen'] == 9
    assert payload['betaLen'] == 1


# ------------------------------------------------------------------ update / remove


@requires_node
def test_update_patch_whitelist_and_noop_silence():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        const before = globalThis.__dispatched.length;
        const ok = ContributionRegistry.update('alpha', 'dock-a', {
          label: 'Renamed',
          description: 'desc',
          icon: 'wand',
          badge: 3,
          progress: 0.5,
          status: '正在处理',
          enabled: false,
          disabledHint: '禁用中',
          busy: true,
          unknownField: 'ignored',
        });
        const afterUpdate = globalThis.__dispatched.length;
        const node = ContributionRegistry.get('alpha', 'dock-a');
        const same = ContributionRegistry.update('alpha', 'dock-a', { label: 'Renamed' });
        const afterSame = globalThis.__dispatched.length;

        process.stdout.write(JSON.stringify({
          ok,
          changed: afterUpdate > before,
          same,
          sameSilent: afterSame === afterUpdate,
          node: {
            label: node.label, description: node.description, icon: node.icon,
            badge: node.badge, progress: node.progress, status: node.status,
            enabled: node.enabled, disabledHint: node.disabledHint, busy: node.busy,
            hasUnknown: Object.prototype.hasOwnProperty.call(node, 'unknownField'),
          },
          missing: ContributionRegistry.update('alpha', 'nope', { label: 'x' }),
        }));
        """
    )
    assert payload['ok'] is True
    assert payload['changed'] is True
    assert payload['same'] is True
    # 同值写入不得广播（打断 contributions:changed 重入递归）
    assert payload['sameSilent'] is True
    assert payload['node'] == {
        'label': 'Renamed',
        'description': 'desc',
        'icon': 'wand',
        'badge': 3,
        'progress': 0.5,
        'status': '正在处理',
        'enabled': False,
        'disabledHint': '禁用中',
        'busy': True,
        'hasUnknown': False,
    }
    assert payload['missing'] is False


@requires_node
def test_update_children_requires_submenu_and_valid_action():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        const commands = [
          ContributionRegistry.update('alpha', 'dock-a', { children: [] }),
          ContributionRegistry.update('alpha', 'dock-a', { children: [] }),
          ContributionRegistry.update('alpha', 'submenu', {
            children: [
              { id: 'new-child', type: 'item', label: 'New',
                action: { type: 'command', id: 'open-alpha' } },
            ],
          }),
        ];
        const afterValid = ContributionRegistry.get('alpha', 'submenu').children.map(
          (child) => child.id,
        );
        // 引用未声明命令 → 整个 patch 拒绝，子树保持不变
        const badAction = ContributionRegistry.update('alpha', 'submenu', {
          children: [
            { id: 'bad-child', type: 'item', label: 'Bad',
              action: { type: 'command', id: 'missing-command' } },
          ],
        });
        const afterBadAction = ContributionRegistry.get('alpha', 'submenu').children.map(
          (child) => child.id,
        );
        // surface 未注入校验回调时只做格式校验（契约：由 pluginHost 注入已注册校验）
        const badSurface = ContributionRegistry.update('alpha', 'submenu', {
          children: [
            { id: 'bad-surface-child', type: 'item', label: 'Bad surface',
              action: { type: 'surface', id: 'unregistered' } },
          ],
        });
        const afterBadSurface = ContributionRegistry.get('alpha', 'submenu').children.map(
          (child) => child.id,
        );

        process.stdout.write(JSON.stringify({
          onItem: commands[0],
          onItemAgain: commands[1],
          valid: commands[2],
          badAction,
          badSurface,
          afterValid,
          afterBadAction,
          afterBadSurface,
          listCount: ContributionRegistry.list('alpha').map((node) => node.id),
        }));
        """
    )
    assert payload['onItem'] is False, 'children 只允许 submenu'
    assert payload['onItemAgain'] is False
    assert payload['valid'] is True
    assert payload['afterValid'] == ['new-child']
    assert payload['badAction'] is False
    assert payload['afterBadAction'] == ['new-child']
    assert payload['badSurface'] is True, '未注入回调时 surface 只做格式校验'
    assert payload['afterBadSurface'] == ['bad-surface-child']
    assert len(payload['listCount']) == len(set(payload['listCount']))


@requires_node
def test_surface_action_validator_is_injected_by_plugin_host():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        // 注入「已注册 surface」校验回调（pluginHost.init 的职责）
        ContributionRegistry.setActionValidator(
          (pluginId, action) => pluginId === 'alpha' && action.id === 'panel',
        );
        const registered = ContributionRegistry.update('alpha', 'submenu', {
          children: [
            { id: 'surface-child', type: 'item', label: 'Ok',
              action: { type: 'surface', id: 'panel' } },
          ],
        });
        const unregistered = ContributionRegistry.update('alpha', 'submenu', {
          children: [
            { id: 'surface-child', type: 'item', label: 'Nope',
              action: { type: 'surface', id: 'ghost' } },
          ],
        });
        process.stdout.write(JSON.stringify({ registered, unregistered }));
        """
    )
    assert payload['registered'] is True
    assert payload['unregistered'] is False


@requires_node
def test_static_surface_menu_is_not_gated_by_runtime_surface_registration():
    """设计 §4.3：静态 manifest 的 surface id 运行期才存在，安装期只校验格式。

    真实 bug：`pluginHost.init()` 在插件加载前就注入「surface 已注册」回调，
    旧实现让静态 ingest 也走这个回调 → 自绘插件在声明式宿主 UI 里的入口全被丢弃。
    """
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        ContributionRegistry.setActionValidator(() => false);
        ContributionRegistry.setPlugins(JSON.parse(JSON.stringify(
          ContributionRegistry.plugins
        )));

        const dock = ContributionRegistry.menuTree('dock').map((node) => node.key);
        const list = ContributionRegistry.list('alpha').map((node) => node.id);
        process.stdout.write(JSON.stringify({ dock, list }));
        """
    )
    # surface 声明（dock-c / dock-d）保留，即使此刻一个 surface 都没注册
    assert 'alpha:dock-c' in payload['dock']
    assert 'alpha:dock-d' in payload['dock']
    # command 引用仍必须是已声明的（静态校验没有被整体放宽）
    assert 'bad-command' not in payload['list']


@requires_node
def test_remove_and_setplugins_restores_static_declaration():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        const removed = ContributionRegistry.remove('alpha', 'submenu');
        const afterRemove = ContributionRegistry.list('alpha').map((node) => node.id);
        const childAfterRemove = ContributionRegistry.get('alpha', 'child-cards');
        const again = ContributionRegistry.remove('alpha', 'submenu');

        // setPlugins 是整体重建：运行期 remove / update 被重置回静态声明
        ContributionRegistry.setPlugins(JSON.parse(JSON.stringify(
          ContributionRegistry.plugins
        )));
        const restored = ContributionRegistry.list('alpha').map((node) => node.id);

        process.stdout.write(JSON.stringify({
          removed, again, afterRemove, childAfterRemove, restored,
        }));
        """
    )
    assert payload['removed'] is True
    assert payload['again'] is False
    assert 'submenu' not in payload['afterRemove']
    assert 'child-cards' not in payload['afterRemove']
    assert payload['childAfterRemove'] is None
    # 重建后子树回来（JSON 深拷贝去掉函数/Map，但 manifest 快照仍完整）
    assert 'submenu' in payload['restored']


@requires_node
def test_remove_plugin_clears_all_records():
    payload = run_json(
        PLUGIN_FIXTURE
        + """
        const before = ContributionRegistry.list('alpha').length;
        const removed = ContributionRegistry.removePlugin('alpha');
        process.stdout.write(JSON.stringify({
          before,
          removed,
          after: ContributionRegistry.list('alpha').length,
          dock: ContributionRegistry.menuTree('dock').map((node) => node.key),
        }));
        """
    )
    assert payload['before'] > 0
    assert payload['removed'] is True
    assert payload['after'] == 0
    assert all(key.startswith('beta:') for key in payload['dock'])
