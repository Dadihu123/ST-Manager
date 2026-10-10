"""入口注册表前端契约测试（设计文档 D1 / D5 / D6 / D7）。

仓库里没有 JS 测试运行器，因此这里的策略与既有的
`tests/test_*_frontend_contracts.py` 一致：用 Node 直接 import 真实模块并断言
行为。`entryRegistry.js` 刻意做成**纯逻辑 + 可注入上下文**（`evaluateWhen` 接
受显式 context、`list()` 走 `this.context()`），因此可以在没有 DOM 的情况下
验证核心契约。

若环境没有 Node，这些用例跳过（与 `test_color_system_contracts.py` 的既有做法一致）。
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

REGISTRY_PATH = 'static/js/entryRegistry.js'


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
    reason='Node.js is required for entry registry contract checks',
)


# ------------------------------------------------------------------ 静态契约


def test_registry_module_exists_and_exports_contract():
    source = read_source(REGISTRY_PATH)

    for fragment in (
        'export const EntryRegistry',
        'export function buildEntryKey(',
        'export function evaluateWhen(',
        'export function isHostEntryKey(',
        'CORE_ENTRY_PREFIX = "core:"',
        'export const MAX_DOCK_SLOTS = 8',
        'export const MAX_DOCK_ENTRIES_PER_PLUGIN = 2',
    ):
        assert fragment in source, fragment


def test_kind_and_surface_sets_match_backend_contract():
    """前端集合必须与 `core/plugins/entries.py` 完全一致。"""
    from core.plugins.entries import ENTRY_KINDS, SURFACE_TYPES

    source = read_source(REGISTRY_PATH)

    assert (
        'ENTRY_KINDS = ["dock", "nav", "settings", "context", "command", "status", "batch"]'
        in source
    )
    assert 'SURFACE_TYPES = ["panel", "modal", "page", "sheet"]' in source

    # 逐项对齐，防止只改一侧
    assert set(ENTRY_KINDS) == {'dock', 'nav', 'settings', 'context', 'command', 'status', 'batch'}
    assert set(SURFACE_TYPES) == {'panel', 'modal', 'page', 'sheet'}


def test_target_kinds_match_backend_contract():
    """`when.target` 的合法值也必须两侧一致。"""
    from core.plugins.entries import TARGET_KINDS

    source = read_source(REGISTRY_PATH)

    assert 'export const TARGET_KINDS = ["folder", "card", "any"]' in source
    assert set(TARGET_KINDS) == {'folder', 'card', 'any'}


def test_registry_rebuilds_on_plugins_loaded():
    source = read_source(REGISTRY_PATH)

    assert 'window.addEventListener("plugins:loaded"' in source
    assert 'this.loadFromHost();' in source


def test_disabled_plugins_do_not_enter_registry():
    source = read_source(REGISTRY_PATH)

    assert 'if (!item || item.enabled === false) continue;' in source


def test_layout_endpoint_is_used_for_preferences():
    source = read_source(REGISTRY_PATH)

    assert '/api/plugins/entries/layout' in source
    assert 'async saveLayout(patch)' in source


# ------------------------------------------------------------------ 运行时契约


@requires_node
def test_entry_keys_are_globally_unique_across_plugins():
    """同插件重复 id 去重、跨插件同 id 不冲突（D1）。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { buildEntryKey, isHostEntryKey } from './static/js/entryRegistry.js';

        // 跨插件同 id 必须得到不同全局键
        assert.notEqual(
          buildEntryKey('plugin-a', 'open'),
          buildEntryKey('plugin-b', 'open'),
        );
        assert.equal(buildEntryKey('plugin-a', 'open'), 'plugin-a:open');

        // 宿主内建键与插件键永不冲突
        assert.equal(isHostEntryKey('core:open-settings'), true);
        assert.equal(isHostEntryKey('plugin-a:open'), false);
        assert.equal(isHostEntryKey(''), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_when_target_is_evaluated_only_by_consumers_that_supply_it():
    """`when.target` 只对**右键菜单**有意义。

    两条纪律：
    1. 提供 `targetKind` 的消费方（右键菜单）按目标类型求值；
    2. 不提供 `targetKind` 的消费方（入口坞 / 命令面板 / 批量菜单 / 总览页）
       **跳过**该条件——否则「只在右键分类时可用」的 context 入口会在所有
       别的地方被误判为不可用。
    """
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { evaluateWhen } from './static/js/entryRegistry.js';

        const base = { mode: 'cards', selectionCount: 0 };

        // 1) 右键分类：targetKind = folder
        const onFolder = { ...base, targetKind: 'folder' };
        assert.equal(evaluateWhen({ target: 'folder' }, onFolder).ok, true);
        assert.equal(evaluateWhen({ target: 'card' }, onFolder).ok, false);

        // 2) 右键卡片：targetKind = card
        const onCard = { ...base, targetKind: 'card' };
        assert.equal(evaluateWhen({ target: 'card' }, onCard).ok, true);
        assert.equal(evaluateWhen({ target: 'folder' }, onCard).ok, false);

        // 3) any：两种目标都可用
        assert.equal(evaluateWhen({ target: 'any' }, onFolder).ok, true);
        assert.equal(evaluateWhen({ target: 'any' }, onCard).ok, true);

        // 4) 不提供 targetKind → 跳过（关键：否则 context 入口在坞里会消失）
        assert.equal(evaluateWhen({ target: 'folder' }, base).ok, true);
        assert.equal(evaluateWhen({ target: 'folder' }, { ...base, targetKind: '' }).ok, true);

        // 5) 拒绝时给出可用的 reason（供 disabledHint 兜底文案使用）
        const rejected = evaluateWhen({ target: 'folder' }, onCard);
        assert.equal(rejected.ok, false);
        assert.deepEqual(rejected.reasons, ['target']);

        // 6) 与其它条件叠加时各自独立计入 reason
        const both = evaluateWhen(
          { target: 'folder', mode: ['chats'] },
          onCard,
        );
        assert.equal(both.ok, false);
        assert.equal(both.reasons.length, 2);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_context_override_replaces_global_selection_for_right_click():
    """右键菜单用**右键目标**求值，而不是全局选中集。

    这是问题 1 的核心：右键一个分类时，作用域是那个分类，与用户恰好勾选了
    哪几张卡无关。`list({ contextOverride })` 必须能覆盖 `selectionCount`，
    否则「右键分类 → 分析整个分类」会被全局选中数误判（勾了 1 张就变 single）。
    """
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          { id: 'p1', enabled: true, manifest: { entries: [
            { id: 'analyze-folder', kind: 'context', label: '分析此分类',
              when: { target: 'folder' } },
            { id: 'analyze-card', kind: 'context', label: '分析这张卡',
              when: { target: 'card', selection: 'any' } },
          ] } },
        ]);
        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };

        // 右键文件夹：只有 folder 入口可用（selection 被覆盖为 0）
        const onFolder = EntryRegistry.list({
          kind: 'context',
          contextOverride: { targetKind: 'folder', selectionCount: 0 },
        });
        const folderById = Object.fromEntries(onFolder.map((e) => [e.id, e]));
        assert.equal(folderById['analyze-folder'].enabled, true);
        assert.equal(folderById['analyze-card'].enabled, false);

        // 右键卡片：card 入口可用（selection 覆盖为 1）
        const onCard = EntryRegistry.list({
          kind: 'context',
          contextOverride: { targetKind: 'card', selectionCount: 1 },
        });
        const cardById = Object.fromEntries(onCard.map((e) => [e.id, e]));
        assert.equal(cardById['analyze-folder'].enabled, false);
        assert.equal(cardById['analyze-card'].enabled, true);

        // 覆盖是逐字段合并：未覆盖的字段仍取全局上下文
        const merged = EntryRegistry.list({
          kind: 'context',
          contextOverride: { targetKind: 'folder' },
        });
        assert.equal(merged.length, 2, '未覆盖的字段不应导致条目丢失');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_batch_kind_entries_are_registered_and_listed():
    """`kind: "batch"` 必须能进注册表，并能被 `list({kind:'batch'})` 取出。

    批量操作菜单就靠这一次调用拿到菜单项；注册表若不认这个 kind，
    插件的批量入口会被 `normalizeDeclaredEntry` 静默丢弃（返回 null）。
    """
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          { id: 'p1', enabled: true, manifest: { entries: [
            { id: 'bulk', kind: 'batch', label: 'AI 分析选中卡片',
              requires_selection: true, when: { selection: 'any' },
              disabledHint: '请先选中卡片' },
            { id: 'dock', kind: 'dock', label: '面板' },
          ] } },
        ]);
        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };

        const items = EntryRegistry.list({ kind: 'batch' });
        assert.equal(items.length, 1, 'batch 入口必须进注册表');
        assert.equal(items[0].id, 'bulk');
        assert.equal(items[0].enabled, false, '未选中时应置灰');
        assert.equal(items[0].disabledHint, '请先选中卡片');

        // 全局选中集满足时可用（批量菜单沿用全局 selection 语义）
        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
        const withSelection = EntryRegistry.list({
          kind: 'batch',
          contextOverride: { selectionCount: 3 },
        });
        assert.equal(withSelection[0].enabled, true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_when_condition_evaluation():
    """D7：`when` 的每种条件都必须按契约求值。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { evaluateWhen } from './static/js/entryRegistry.js';

        const base = {
          mode: 'cards',
          selectionCount: 0,
          indexState: 'ready',
          hostVersion: '1.2.0',
          feature: ['hasNetwork', 'hasSSE'],
        };

        // 空条件恒通过
        assert.equal(evaluateWhen(null, base).ok, true);
        assert.equal(evaluateWhen({}, base).ok, true);

        // mode
        assert.equal(evaluateWhen({ mode: ['cards'] }, base).ok, true);
        assert.equal(evaluateWhen({ mode: ['chats'] }, base).ok, false);

        // selection：none / any / single / multi
        assert.equal(evaluateWhen({ selection: 'none' }, base).ok, true);
        assert.equal(evaluateWhen({ selection: 'any' }, base).ok, false);
        assert.equal(evaluateWhen({ selection: 'any' }, { ...base, selectionCount: 1 }).ok, true);
        assert.equal(evaluateWhen({ selection: 'single' }, { ...base, selectionCount: 1 }).ok, true);
        assert.equal(evaluateWhen({ selection: 'single' }, { ...base, selectionCount: 3 }).ok, false);
        assert.equal(evaluateWhen({ selection: 'multi' }, { ...base, selectionCount: 3 }).ok, true);
        assert.equal(evaluateWhen({ selection: 'multi' }, { ...base, selectionCount: 1 }).ok, false);

        // indexState
        assert.equal(evaluateWhen({ indexState: 'ready' }, base).ok, true);
        assert.equal(evaluateWhen({ indexState: 'building' }, base).ok, false);

        // config.requireKeys：未配置则置灰
        const withConfig = { ...base, config: { api_key: 'sk-x' } };
        assert.equal(
          evaluateWhen({ config: { requireKeys: ['api_key'] } }, withConfig).ok,
          true,
        );
        const missing = evaluateWhen({ config: { requireKeys: ['api_key'] } }, base);
        assert.equal(missing.ok, false);
        assert.deepEqual(missing.reasons, ['config']);
        // 空串等同于未配置
        assert.equal(
          evaluateWhen(
            { config: { requireKeys: ['api_key'] } },
            { ...base, config: { api_key: '   ' } },
          ).ok,
          false,
        );

        // hostVersion：>= 语义
        assert.equal(evaluateWhen({ hostVersion: '>=1.0.0' }, base).ok, true);
        assert.equal(evaluateWhen({ hostVersion: '>=2.0.0' }, base).ok, false);
        assert.equal(evaluateWhen({ hostVersion: '<2.0.0' }, base).ok, true);

        // feature
        assert.equal(evaluateWhen({ feature: ['hasNetwork'] }, base).ok, true);
        assert.equal(evaluateWhen({ feature: ['hasQuantum'] }, base).ok, false);

        // 多个条件同时不满足时收集多个 reason
        const multi = evaluateWhen(
          { mode: ['chats'], selection: 'any' },
          base,
        );
        assert.equal(multi.ok, false);
        assert.equal(multi.reasons.length, 2);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_registry_applies_tier_filtering_and_entry_limit():
    """D5 分级与 D1 上限：从插件列表快照建表时生效。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        const entries = [
          { id: 'ok-dock', kind: 'dock', label: 'Dock' },
          { id: 'ok-command', kind: 'command', label: 'Cmd' },
        ];

        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries },
          },
          {
            id: 'disabled-plugin',
            enabled: false,
            manifest: { entries: [{ id: 'hidden', kind: 'dock', label: 'X' }] },
          },
        ]);

        // 禁用插件的条目不进入注册表
        assert.equal(EntryRegistry.get('disabled-plugin:hidden'), null);
        assert.equal(EntryRegistry.get('demo:ok-dock').key, 'demo:ok-dock');
        assert.equal(EntryRegistry.list().length, 2);

        // 非法 kind 被丢弃
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [{ id: 'bad', kind: 'nonsense', label: 'X' }] },
          },
        ]);
        assert.equal(EntryRegistry.list().length, 0);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_registry_drops_entries_beyond_the_sixteen_limit():
    """D1：单插件上限 16 项，超出部分被忽略。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        // 前端只消费后端已裁剪的结果；这里验证后端下发的 16 项被完整接收，
        // 且第 17 项（若后端漏裁）不会被静默吞掉成错误状态。
        const entries = [];
        for (let index = 0; index < 16; index += 1) {
          entries.push({ id: `e-${index}`, kind: 'command', label: `E${index}` });
        }

        EntryRegistry.setPlugins([{ id: 'demo', enabled: true, manifest: { entries } }]);
        assert.equal(EntryRegistry.list().length, 16);

        // 重复 id 在归一化时被覆盖而不是产生两个条目
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              { id: 'dup', kind: 'command', label: 'A' },
              { id: 'dup', kind: 'command', label: 'B' },
            ] },
          },
        ]);
        assert.equal(EntryRegistry.list().length, 1);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_dock_slots_are_host_allocated_resources():
    """D6：社区插件默认进溢出菜单；坞槽位上限 8、单插件上限 2。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        const dockEntries = [];
        for (let index = 0; index < 3; index += 1) {
          dockEntries.push({ id: `d-${index}`, kind: 'dock', label: `D${index}` });
        }

        // community（默认 tier）：不进坞槽位，全部进溢出菜单
        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
        EntryRegistry.setPlugins([
          { id: 'community-plugin', enabled: true, manifest: { entries: dockEntries } },
        ]);
        assert.equal(EntryRegistry.dockSlots().length, 0);
        assert.equal(EntryRegistry.overflowEntries().length, 3);

        // 用户显式固定后才进坞
        EntryRegistry.layout = {
          order: [], pinned: ['community-plugin:d-0'], hidden: [], groups: {}, shortcuts: {},
        };
        assert.equal(EntryRegistry.dockSlots().length, 1);

        // 单插件在坞内最多 2 个槽位
        EntryRegistry.layout = {
          order: [],
          pinned: ['community-plugin:d-0', 'community-plugin:d-1', 'community-plugin:d-2'],
          hidden: [], groups: {}, shortcuts: {},
        };
        assert.equal(EntryRegistry.dockSlots().length, 2);

        // official 插件默认进坞（无需用户固定）
        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
        EntryRegistry.setPlugins([
          {
            id: 'official-plugin',
            enabled: true,
            manifest: { entries: [{ id: 'd', kind: 'dock', label: 'D', tier: 'official' }] },
          },
        ]);
        assert.equal(EntryRegistry.dockSlots().length, 1);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_registry_sorts_by_user_preference_then_priority():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              { id: 'c', kind: 'command', label: 'C', priority: 300 },
              { id: 'a', kind: 'command', label: 'A', priority: 100 },
              { id: 'b', kind: 'command', label: 'B', priority: 200 },
            ] },
          },
        ]);

        // 无用户偏好时按 priority 升序
        assert.deepEqual(
          EntryRegistry.list().map((item) => item.id),
          ['a', 'b', 'c'],
        );

        // 用户显式排序优先于插件建议的 priority
        EntryRegistry.layout = {
          order: ['demo:c', 'demo:b'], pinned: [], hidden: [], groups: {}, shortcuts: {},
        };
        assert.deepEqual(
          EntryRegistry.list().map((item) => item.id),
          ['c', 'b', 'a'],
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_hidden_entries_are_excluded_from_dock_but_visible_in_overview():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              { id: 'visible', kind: 'command', label: 'V' },
              { id: 'muted', kind: 'command', label: 'M' },
            ] },
          },
        ]);
        EntryRegistry.layout = {
          order: [], pinned: [], hidden: ['demo:muted'], groups: {}, shortcuts: {},
        };

        assert.equal(EntryRegistry.list().length, 1);
        // 总览页需要看到隐藏项才能恢复
        assert.equal(EntryRegistry.all().length, 2);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_runtime_registered_entries_survive_host_reload():
    """运行期条目在 `plugins:loaded` 重建后仍在（插件未禁用）。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([{ id: 'demo', enabled: true, manifest: { entries: [] } }]);
        const key = EntryRegistry.register('demo', { id: 'runtime-1', kind: 'command', label: 'R' });
        assert.equal(key, 'demo:runtime-1');
        assert.equal(EntryRegistry.get(key).source, 'runtime');

        // 宿主重载（声明层重建）
        EntryRegistry.setPlugins([{ id: 'demo', enabled: true, manifest: { entries: [] } }]);
        assert.notEqual(EntryRegistry.get('demo:runtime-1'), null);

        // 插件被禁用后运行期条目一并消失
        EntryRegistry.setPlugins([{ id: 'demo', enabled: false, manifest: { entries: [] } }]);
        assert.equal(EntryRegistry.get('demo:runtime-1'), null);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_remove_plugin_clears_entries_and_config_cache():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [{ id: 'x', kind: 'command', label: 'X' }] },
          },
        ]);
        EntryRegistry.configs.set('demo', { api_key: 'sk' });
        assert.equal(EntryRegistry.removePlugin('demo'), true);
        assert.equal(EntryRegistry.get('demo:x'), null);
        assert.equal(EntryRegistry.configs.has('demo'), false);
        // 幂等：再次移除返回 false 而不是抛错
        assert.equal(EntryRegistry.removePlugin('demo'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_require_keys_consults_secret_schema_too():
    """D7：`requireKeys` 必须同时看 `config_schema` 与 `secret_schema`。

    `/api/plugins/<id>/config` 只返回 config 段（密钥明文永不回传），因此密钥键
    必须另外查 `/secrets` 的 `set` 标志。漏了这一步，`requireKeys: ['api_key']`
    会让入口**永远置灰**——这是最难发现的一类契约 bug（不报错，只是点不动）。
    """
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        const requested = [];
        globalThis.window = {
          dispatchEvent() {},
          addEventListener() {},
        };
        globalThis.fetch = async (url) => {
          requested.push(String(url));
          if (String(url).endsWith('/config')) {
            return { json: async () => ({ success: true, config: { greeting: 'hi' } }) };
          }
          if (String(url).endsWith('/secrets')) {
            return { json: async () => ({ success: true, secrets: { api_key: { set: true } } }) };
          }
          return { json: async () => ({ success: false }) };
        };

        EntryRegistry.configs.clear();
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              {
                id: 'needs-secret',
                kind: 'command',
                label: 'S',
                when: { config: { requireKeys: ['api_key'] } },
              },
            ] },
          },
        ]);

        await EntryRegistry.ensureConfigs();

        // 必须真的去查了 /secrets
        assert.ok(
          requested.some((url) => url.endsWith('/secrets')),
          'requireKeys 引用了密钥键时必须查询 /secrets',
        );

        // 密钥已设置 → 入口可用
        const items = EntryRegistry.list();
        assert.equal(items.length, 1);
        assert.equal(items[0].enabled, true, '密钥已设置时入口必须可用');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_require_keys_greys_out_when_secret_absent():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        globalThis.window = { dispatchEvent() {}, addEventListener() {} };
        globalThis.fetch = async (url) => {
          if (String(url).endsWith('/config')) {
            return { json: async () => ({ success: true, config: {} }) };
          }
          // 密钥未设置
          return { json: async () => ({ success: true, secrets: { api_key: { set: false } } }) };
        };

        EntryRegistry.configs.clear();
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              {
                id: 'needs-secret',
                kind: 'command',
                label: 'S',
                disabledHint: '请先填写 API Key',
                when: { config: { requireKeys: ['api_key'] } },
              },
            ] },
          },
        ]);

        await EntryRegistry.ensureConfigs();

        const item = EntryRegistry.list()[0];
        assert.equal(item.enabled, false);
        assert.equal(item.disabledHint, '请先填写 API Key');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_clearing_a_secret_regreys_the_entry():
    """清除密钥后入口必须重新置灰（否则会停在可用态）。"""
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        const listeners = {};
        globalThis.window = {
          dispatchEvent() {},
          addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
        };

        EntryRegistry.init();
        EntryRegistry.configs.set('demo', { api_key: '__set__' });
        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [
              { id: 'x', kind: 'command', label: 'X', when: { config: { requireKeys: ['api_key'] } } },
            ] },
          },
        ]);
        assert.equal(EntryRegistry.list()[0].enabled, true);

        // 宿主清除密钥后派发事件
        const event = new CustomEvent('plugin-secrets-changed', {
          detail: { pluginId: 'demo', config: {}, removed: ['api_key'] },
        });
        for (const handler of listeners['plugin-secrets-changed'] || []) handler(event);

        assert.equal(EntryRegistry.list()[0].enabled, false, '清除密钥后必须重新置灰');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_searchable_includes_core_commands_and_plugin_entries():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry, CORE_ENTRY_PREFIX } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [{ id: 'x', kind: 'command', label: 'X' }] },
          },
        ]);

        const items = EntryRegistry.searchable();
        const coreItems = items.filter((item) => item.key.startsWith(CORE_ENTRY_PREFIX));
        const pluginItems = items.filter((item) => item.pluginId === 'demo');

        assert.ok(coreItems.length > 0, '宿主内建命令必须在搜索范围内');
        assert.equal(pluginItems.length, 1);
        assert.equal(coreItems.length + pluginItems.length, items.length);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_registry_emits_change_event():
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        let fired = 0;
        globalThis.window = {
          dispatchEvent() { fired += 1; },
          addEventListener() {},
        };

        EntryRegistry.setPlugins([
          {
            id: 'demo',
            enabled: true,
            manifest: { entries: [{ id: 'x', kind: 'command', label: 'X' }] },
          },
        ]);
        assert.ok(fired > 0, '重建注册表必须广播 entries:changed');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
