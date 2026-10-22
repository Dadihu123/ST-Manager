"""前端 PluginHost v3 契约测试（设计文档 §6 / §7.2；实现日志 S4–S9）。

仓库没有 JS 测试运行器，沿用既有做法：静态源码契约断言 + 最小 DOM 垫片下在
Node 里**真实执行** `init() / buildApi()`。覆盖：

- `buildApi()` 顶层键与 S9 完全一致（生成器按此逐字校验）；
- `api.emit` 核心事件警告忽略、自定义事件必须带 `<pluginId>:` 前缀；
- `createRoot` 两层（内容层 / portal 层）与 `data-plugin` 标记；
- `contribution:trigger` 唯一监听 + 执行器（surface / command / url / kill switch）；
- kill switch 监听 `plugins:close-overlays`；
- 崩溃隔离 / 降级（5 次/分钟、`isDegraded`、`plugin:degraded`）；
- global_styles 能力位门控 + `data-plugin-style`；
- 激活期模块预加载（S5）与单插件重试 `reloadPlugin`（S9 失败展示）。
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

HOST_PATH = 'static/js/pluginHost.js'
ROOT_HOST_PATH = 'static/js/pluginRootHost.js'

#: S9 定义的 `buildApi()` 顶层键全集（生成器 `FRONTEND_MEMBERS` 同源）。
BUILD_API_TOP_LEVEL_KEYS = {
    'api',
    'contributions',
    'createRoot',
    'emit',
    'estimateTokens',
    'host',
    'id',
    'jobs',
    'manifest',
    'off',
    'on',
    'onConfigChange',
    'openDetail',
    'openSettingsSection',
    'overlays',
    'progress',
    'refresh',
    'registerAlpineComponent',
    'setFullscreenScrim',
    'state',
    'storage',
    'store',
    'subscribeJob',
    'surfaces',
    'switchMode',
    'toast',
    'ui',
    'utils',
    'worldbook',
}

#: v2 已删除的顶层键（出现即说明没有真正迁移）。
REMOVED_TOP_LEVEL_KEYS = ('entries', 'registerModal', 'registerSettingsSection')


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
    reason='Node.js is required for plugin host contract checks',
)


# ------------------------------------------------------------------ DOM 垫片

DOM_SHIM = r"""
class ShimClassList {
  constructor(node) { this.node = node; this.set = new Set(); }
  add(...names) { for (const name of names) this.set.add(name); }
  remove(...names) { for (const name of names) this.set.delete(name); }
  contains(name) { return this.set.has(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.set.has(name) : Boolean(force);
    if (on) this.set.add(name); else this.set.delete(name);
    return on;
  }
  get value() { return Array.from(this.set).join(' '); }
}

class ShimNode {
  constructor(tagName) {
    this.tagName = String(tagName || '').toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.classList = new ShimClassList(this);
    this.textContent = '';
    this.innerHTML = '';
    this.value = '';
    this.style = { setProperty() {} };
    this.id = '';
    this.isConnected = true;
  }
  get className() { return this.classList.value; }
  set className(value) {
    this.classList.set = new Set(String(value || '').split(/\s+/).filter(Boolean));
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] ?? null; }
  removeAttribute(name) { delete this.attributes[String(name)]; }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    if (child.id) this.ownerDocument._byId.set(child.id, child);
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
    return true;
  }
  addEventListener(type, handler) {
    (this.listeners[type] = this.listeners[type] || []).push(handler);
  }
  removeEventListener(type, handler) {
    const list = this.listeners[type] || [];
    const index = list.indexOf(handler);
    if (index >= 0) list.splice(index, 1);
  }
  dispatch(type, event = {}) {
    for (const handler of [...(this.listeners[type] || [])]) handler(event);
  }
  focus() { globalThis.__focused = this; }
  contains(node) { return node === this || this.children.includes(node); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  get firstChild() { return this.children[0] || null; }
}

const shimDocument = new ShimNode('#document');
shimDocument.ownerDocument = shimDocument;
shimDocument.body = new ShimNode('body');
shimDocument.body.ownerDocument = shimDocument;
shimDocument.head = new ShimNode('head');
shimDocument.head.ownerDocument = shimDocument;
shimDocument.documentElement = new ShimNode('html');
shimDocument.visibilityState = 'visible';
shimDocument.activeElement = null;
shimDocument._byId = new Map();
shimDocument.createTextNode = (text) => {
  const node = new ShimNode('#text');
  node.textContent = String(text);
  return node;
};
shimDocument.createElement = (tag) => {
  const node = new ShimNode(tag);
  node.ownerDocument = shimDocument;
  return node;
};
shimDocument.createElementNS = (_ns, tag) => shimDocument.createElement(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(String(id)) || null;
shimDocument.contains = (node) => Boolean(node);
shimDocument.querySelector = () => null;
shimDocument.querySelectorAll = (selector) => globalThis.__queryAll(selector);

const windowListeners = {};
const mediaListeners = [];
let mediaMatches = false;

const shimWindow = {
  devicePixelRatio: 1,
  addEventListener(type, handler) {
    (windowListeners[type] = windowListeners[type] || []).push(handler);
  },
  removeEventListener(type, handler) {
    const list = windowListeners[type] || [];
    const index = list.indexOf(handler);
    if (index >= 0) list.splice(index, 1);
  },
  dispatchEvent(event) {
    for (const handler of [...(windowListeners[event.type] || [])]) handler(event);
    return true;
  },
  matchMedia() {
    return {
      get matches() { return mediaMatches; },
      addEventListener(type, handler) { mediaListeners.push({ type, handler }); },
      removeEventListener() {},
    };
  },
  requestAnimationFrame(callback) { shimWindow.__rafQueue.push(callback); return 0; },
  __rafQueue: [],
  open(...args) { shimWindow.__opened.push(args); return null; },
  __opened: [],
};

globalThis.document = shimDocument;
globalThis.window = shimWindow;
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.__shim = { shimDocument, shimWindow, mediaListeners };

/** 插槽锚点 / 样式链接查询（querySelectorAll 的极简实现）。 */
globalThis.__anchors = [];
globalThis.__queryAll = (selector) => {
  const text = String(selector);
  if (text.includes('[data-plugin-slot]')) return [...globalThis.__anchors];
  const pluginMatch = /\[data-plugin="([^"]+)"\]/.exec(text);
  if (pluginMatch) {
    const pluginId = pluginMatch[1];
    const links = [];
    for (const node of shimDocument._byId.values()) {
      if (node.tagName !== 'LINK') continue;
      if (node.dataset && node.dataset.plugin === pluginId) links.push(node);
    }
    return links;
  }
  return [];
};

/** 注入 store（模拟 `Alpine.store("global")`）。 */
globalThis.__setStore = (patch) => {
  const base = {
    currentMode: 'cards',
    deviceType: 'desktop',
    isDarkMode: true,
    batchProgress: { status: 'idle', current: 0, total: 0 },
    indexStatus: { state: 'ready', scan_active: false },
    viewState: { selectedIds: [] },
    showToast() {},
  };
  globalThis.__store = Object.assign(base, patch || {});
  shimWindow.Alpine = {
    store: () => globalThis.__store,
    reactive: (value) => value,
    effect: (callback) => { globalThis.__effects.push(callback); return () => {}; },
  };
  return globalThis.__store;
};
globalThis.__effects = [];
globalThis.__setStore({});

globalThis.__flushRaf = () => {
  const queue = shimWindow.__rafQueue.splice(0);
  for (const callback of queue) callback();
};

globalThis.__events = [];
const originalDispatch = shimWindow.dispatchEvent;
shimWindow.dispatchEvent = (event) => {
  globalThis.__events.push(event);
  return originalDispatch(event);
};
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    return run_node(DOM_SHIM + textwrap.dedent(body))


# ------------------------------------------------------------------ S9：顶层键


def test_build_api_top_level_keys_are_declared():
    """S9：新增 contributions / overlays，删除 entries / registerModal / registerSettingsSection。"""
    import re

    source = read_source(HOST_PATH)

    for key in sorted(BUILD_API_TOP_LEVEL_KEYS):
        # 约定写法：6 空格缩进的成员声明（`name: …` / `name(...)` / `get name()` /
        # 简写 `name,`）。生成器按字面量校验顶层键。
        pattern = rf'^      (?:get )?{re.escape(key)}(?:\(|:|,| =)'
        assert re.search(pattern, source, re.MULTILINE), key
    for removed in REMOVED_TOP_LEVEL_KEYS:
        assert re.search(rf'^      {re.escape(removed)}(?:\(|:|,)', source, re.MULTILINE) is None
    assert 'registerModal(spec)' not in source
    assert 'registerSettingsSection(spec)' not in source


def test_contributions_namespace_contract():
    source = read_source(HOST_PATH)

    for fragment in (
        'contributions: {',
        'update(id, patch) {',
        'remove(id) {',
        'get(id) {',
        'list() {',
        'trigger(id, ctx = {}) {',
        'host.executeContribution(pluginId, id, "api", ctx)',
    ):
        assert fragment in source, fragment


def test_overlays_namespace_contract():
    source = read_source(HOST_PATH)

    for fragment in (
        'overlays: {',
        'register(spec = {}) {',
        'PluginOverlayHost.register(pluginId, spec)',
        'unregister(id) {',
        'list() {',
        'closeAll() {',
    ):
        assert fragment in source, fragment


@requires_node
def test_build_api_exposes_exactly_the_s9_top_level_keys():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const keys = Object.keys(api).sort();

        process.stdout.write(JSON.stringify({ keys }));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(payload['keys']) == BUILD_API_TOP_LEVEL_KEYS


# ------------------------------------------------------------------ 加载 / 样式


def test_plugin_loading_is_lazy():
    source = read_source(HOST_PATH)

    assert 'requestIdleCallback' in source
    assert 'scheduleIdle(' in source


def test_styles_are_skipped_when_scope_check_fails():
    source = read_source(HOST_PATH)

    assert 'style_scope_errors' in source
    assert 'injectStyle(pluginId, stylePath, version)' in source


def test_global_styles_require_capability_and_mark_data_plugin_style():
    """§4.7 / §7.4：只有 `ui.global_styles` 能力位才允许注入，且带 data-plugin-style。"""
    source = read_source(HOST_PATH)

    assert 'injectGlobalStyle(pluginId, stylePath, version)' in source
    assert 'capabilities.includes("ui.global_styles")' in source
    assert 'link.dataset.pluginStyle = pluginId' in source
    # 缺能力位时必须拒绝注入，不能静默放行
    assert '已拒绝注入' in source


def test_manifests_load_contributions_not_entries():
    source = read_source(HOST_PATH)

    assert 'manifest.contributions' in source or 'contributions.slots' in source
    assert 'manifest.frontend_entries' not in source
    assert 'manifest.entries' not in source


def test_frontend_activation_uses_s2_flat_manifest_fields():
    """S2 定稿快照里 `frontend` 是 boolean；不能再用 v2 的 `manifest.frontend` 对象守卫。

    真实浏览器冒烟曾因此把**所有插件**跳过（`PluginHost.loaded` 为空），
    而自造的 nested fixture 全绿 —— 这条断言锁住形状来源。
    """
    source = read_source(HOST_PATH)

    assert 'manifest.frontend && typeof manifest.frontend !== "object"' not in source
    assert 'if (manifest.frontend && this.needsFrontendActivation(manifest))' not in source
    assert 'const frontend = (manifest && manifest.frontend) || {}' not in source
    # 只读扁平字段
    assert 'String(manifest.frontend_entry || "").trim()' in source
    assert 'manifest.frontend_styles' in source
    assert 'manifest.frontend_global_styles' in source


# ------------------------------------------------------------------ S4：执行器


def test_contribution_trigger_is_the_single_entrypoint():
    source = read_source(HOST_PATH)

    assert 'const CONTRIBUTION_TRIGGER_EVENT = "contribution:trigger"' in source
    # 唯一监听：init() 注册一次
    assert source.count('window.addEventListener(CONTRIBUTION_TRIGGER_EVENT') == 1
    assert 'this.executeContribution(' in source


def test_executor_handles_all_action_types_and_kill_switch():
    source = read_source(HOST_PATH)

    assert 'const isCoreKillSwitch =' in source
    assert 'KILL_SWITCH_COMMAND_ID' in source
    assert 'PluginSurfaceHost.openSurface(surfaceKey, ctx)' in source
    assert 'this._executeCommand(plugin, action.id, record, trigger, ctx)' in source
    assert 'window.open(url, "_blank", "noopener")' in source
    assert 'this.killSwitch();' in source


def test_executor_uses_the_documented_command_context_shape():
    source = read_source(HOST_PATH)

    for fragment in (
        'buildCommandContext(loaded, command, node, trigger, ctx = {})',
        'api: loaded ? loaded.api : null',
        'trigger: {',
        'kind: String(trigger || "menu")',
        'nodeId: node ? String(node.id || "") : ""',
        'selection,',
        'target: source.target',
    ):
        assert fragment in source, fragment


# ------------------------------------------------------------------ S6：共存 / 降级


def test_create_root_delegates_to_root_host_with_two_layers():
    source = read_source(HOST_PATH)
    root_host = read_source(ROOT_HOST_PATH)

    assert 'PluginRootHost.create(pluginId, {' in source
    assert 'portal: Boolean(options.portal)' in source
    assert 'plugin-layer--content' in root_host
    assert 'plugin-layer--portal' in root_host
    # 两个层都是 body 直接子元素、fixed + inset + pointer-events:none
    assert 'position = "fixed"' in root_host
    assert 'inset = "0"' in root_host
    assert 'pointerEvents = "none"' in root_host
    assert 'node.dataset.plugin = plugin' in root_host


def test_kill_switch_event_and_overlay_broadcast():
    source = read_source(HOST_PATH)

    assert 'const PLUGINS_CLOSE_OVERLAYS_EVENT = "plugins:close-overlays"' in source
    assert 'window.addEventListener(PLUGINS_CLOSE_OVERLAYS_EVENT, () => this.killSwitch())' in source
    assert 'PluginOverlayHost.killSwitch([pluginId])' in source
    assert 'PluginRootHost.clear(pluginId)' in source


def test_crash_isolation_and_degraded_threshold():
    source = read_source(HOST_PATH)

    assert 'const DEGRADED_ERROR_LIMIT = 5' in source
    assert 'const DEGRADED_WINDOW_MS = 60 * 1000' in source
    assert 'reportRuntimeError(pluginId, error, source = "")' in source
    assert 'this.degraded.add(key)' in source
    assert 'new CustomEvent("plugin:degraded"' in source
    assert 'isDegraded(pluginId) {' in source
    assert 'clearDegraded(pluginId) {' in source
    # 运行期异常统一入口（surface / slot / overlay / command 都派发这个事件）
    assert 'const PLUGIN_RUNTIME_ERROR_EVENT = "plugin:runtime-error"' in source
    assert 'window.addEventListener(PLUGIN_RUNTIME_ERROR_EVENT' in source


def test_failed_plugins_do_not_abort_the_backend_or_other_plugins():
    source = read_source(HOST_PATH)

    # 单个插件加载失败：写 failed + 继续循环（不 throw 出 loadAll）
    assert 'this.failed.set(entry.id, message)' in source
    assert 'await this.loadPlugin(entry, manifest).catch((error) => {' in source
    # 激活期预加载失败 = 前端激活失败（S5，不是插槽占位）
    assert 'preloadContributionModules(pluginId, manifest, version)' in source
    assert 'throw new Error(' in source
    assert '缺少导出函数' in source
    # 管理器重试
    assert 'async reloadPlugin(pluginId) {' in source
    assert 'PLUGIN_RELOAD_EVENT' in source


def test_module_cache_is_keyed_by_plugin_and_path():
    source = read_source(HOST_PATH)

    assert 'const contributionModuleCache = new Map()' in source
    assert 'const key = `${plugin}:${path}`' in source
    assert 'contributionModuleCache.delete(key)' in source
    assert 'clearContributionModuleCache(key)' in source


def test_surface_error_marks_contribution_status():
    surface = read_source('static/js/pluginSurfaceHost.js')

    assert 'ContributionRegistry.update(record.pluginId, entryId, { status: "error" })' in surface
    assert 'plugin:runtime-error' in surface


# ------------------------------------------------------------------ S8：事件收紧


def test_plugins_cannot_emit_core_events():
    source = read_source(HOST_PATH)

    assert 'CORE_EVENT_EMIT_WARNING' in source
    assert 'if (CORE_EVENTS.has(name)) {' in source
    # emit() 内的核心事件分支：警告后直接 return（不再 dispatchEvent）
    emit_start = source.index('      emit(event, detail) {')
    emit_block = source[emit_start:emit_start + 900]
    core_index = emit_block.index('if (CORE_EVENTS.has(name)) {')
    core_block = emit_block[core_index:core_index + 320]
    assert 'return;' in core_block
    assert 'window.dispatchEvent(new CustomEvent(name' in emit_block


def test_entries_changed_is_replaced_by_contributions_changed():
    source = read_source(HOST_PATH)
    registry = read_source('static/js/contributionRegistry.js')

    assert 'contributions:changed' in source
    assert 'contributions:changed' in registry
    assert 'entries:changed' not in source
    assert 'entries:changed' not in registry


# ------------------------------------------------------------------ 行为测试


@requires_node
def test_api_emit_ignores_core_events_and_dispatches_custom_events():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        globalThis.__events.length = 0;

        api.emit('card.updated', { card_id: 'a' });
        assert.equal(globalThis.__events.length, 0, '核心事件必须被忽略');

        api.emit('demo-plugin:ping', { value: 1 });
        const custom = globalThis.__events.find((event) => event.type === 'demo-plugin:ping');
        assert.ok(custom, '自定义事件必须派发');
        assert.deepEqual(custom.detail, { value: 1 });

        // 不带插件前缀的自定义事件同样被忽略
        globalThis.__events.length = 0;
        api.emit('someone-else:ping', {});
        assert.equal(globalThis.__events.length, 0);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_create_root_uses_content_and_portal_layers():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';
        import { PluginRootHost } from './static/js/pluginRootHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});

        const content = api.createRoot();
        assert.ok(content, 'createRoot() 必须返回元素');
        assert.equal(content.parentNode.id, 'plugin-layer-content');
        assert.equal(content.dataset.plugin, 'demo-plugin');
        assert.ok(content.classList.contains('plugin-demo-plugin'));

        const portal = api.createRoot({ portal: true });
        assert.equal(portal.parentNode.id, 'plugin-layer-portal');

        const button = api.createRoot({ tag: 'button' });
        assert.equal(button.tagName, 'BUTTON');

        // 宿主跟踪：clear 后 DOM 干净
        assert.equal(PluginRootHost.getRoots('demo-plugin').length, 3);
        assert.equal(PluginRootHost.clear('demo-plugin'), 3);
        assert.equal(PluginRootHost.getRoots('demo-plugin').length, 0);
        assert.equal(content.parentNode, null);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_executor_opens_surface_command_and_url():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';
        import { PluginHost } from './static/js/pluginHost.js';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginHost.init();
        PluginSurfaceHost.init();
        PluginSurfaceHost.register('demo-plugin', 'panel-1', {
          type: 'panel', title: 'T', mount() {},
        });
        ContributionRegistry.setPlugins([
          {
            id: 'demo-plugin',
            enabled: true,
            manifest: {
              version: '1.0.0',
              contributions: {
                menus: [
                  { id: 'surface-node', placement: 'dock', type: 'item', label: 'S',
                    action: { type: 'surface', id: 'panel-1' } },
                  { id: 'url-node', placement: 'dock', type: 'item', label: 'U',
                    action: { type: 'url', url: 'https://example.com/x' } },
                ],
              },
            },
          },
        ]);

        assert.equal(PluginHost.executeContribution('demo-plugin', 'surface-node', 'dock', {}), true);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:panel-1'), true);

        assert.equal(PluginHost.executeContribution('demo-plugin', 'url-node', 'dock', {}), true);
        assert.deepEqual(window.__opened[0], ['https://example.com/x', '_blank', 'noopener']);

        // 不存在的节点 / 未知插件 → false
        assert.equal(PluginHost.executeContribution('demo-plugin', 'nope', 'dock', {}), false);
        assert.equal(PluginHost.executeContribution('ghost', 'surface-node', 'dock', {}), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_executor_respects_when_filter_and_core_kill_switch():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';
        import {
          CORE_PLUGIN_ID,
          KILL_SWITCH_COMMAND_ID,
        } from './static/js/contributionRegistry.js';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        ContributionRegistry.setPlugins([
          {
            id: 'demo-plugin',
            enabled: true,
            manifest: {
              contributions: {
                menus: [
                  { id: 'only-worldinfo', placement: 'dock', type: 'item', label: 'W',
                    when: { mode: ['worldinfo'] },
                    action: { type: 'url', url: 'https://example.com' } },
                ],
              },
            },
          },
        ]);

        window.__opened.length = 0;
        // when 不满足 → false，且不派发动作
        assert.equal(PluginHost.executeContribution('demo-plugin', 'only-worldinfo', 'dock', {}), false);
        assert.equal(window.__opened.length, 0);

        // 核心 kill switch 命令（两种 id 形式都接受）
        globalThis.__events.length = 0;
        assert.equal(
          PluginHost.executeContribution(CORE_PLUGIN_ID, 'plugins:close-overlays', 'palette', {}),
          true,
        );
        assert.equal(
          PluginHost.executeContribution(CORE_PLUGIN_ID, KILL_SWITCH_COMMAND_ID, 'shortcut', {}),
          true,
        );
        const forceClosed = globalThis.__events.filter(
          (event) => event.type === 'overlays:force-closed',
        );
        assert.ok(forceClosed.length >= 2, 'kill switch 必须广播 overlays:force-closed');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_report_runtime_error_marks_degraded_after_threshold():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        globalThis.__events.length = 0;
        for (let index = 0; index < 4; index += 1) {
          assert.equal(PluginHost.reportRuntimeError('demo-plugin', new Error('boom'), 'test'), false);
        }
        assert.equal(PluginHost.isDegraded('demo-plugin'), false, '4 次未达阈值');

        const degraded = PluginHost.reportRuntimeError('demo-plugin', new Error('boom'), 'test');
        assert.equal(degraded, true, '第 5 次必须标记降级');
        assert.equal(PluginHost.isDegraded('demo-plugin'), true);
        assert.ok(
          globalThis.__events.some((event) => event.type === 'plugin:degraded'),
          '必须广播 plugin:degraded',
        );

        PluginHost.clearDegraded('demo-plugin');
        assert.equal(PluginHost.isDegraded('demo-plugin'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_load_all_activates_plugins_from_real_s2_flat_payload():
    """真实 `/api/plugins/list` 的 S2 快照（`frontend: true` 扁平形状）驱动 `loadAll()`。

    回归：v2 的 `manifest.frontend` 对象假设导致真实插件**一个都不激活**
    （`loaded` / `failed` 都是空 Map），但 contributionRegistry 里已有声明。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { register } from 'node:module';
        import { PluginHost } from './static/js/pluginHost.js';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        // ---- 真实后端 `PluginManifest.to_dict()` 快照形状（S2）----
        const payload = {
          success: true,
          items: [
            {
              id: 'pet',
              enabled: true,
              manifest: {
                manifest_version: 3,
                api_version: 3,
                version: '1.0.0',
                frontend: true,
                frontend_only: false,
                frontend_entry: 'frontend/plugin.js',
                frontend_styles: ['frontend/plugin.css'],
                frontend_global_styles: [],
                render_mode: 'custom',
                capabilities: ['ui.custom', 'ui.ambient'],
                contributions: {
                  menus: [
                    { id: 'pet-dock', placement: 'dock', type: 'item', label: 'Pet',
                      action: { type: 'surface', id: 'pet-settings' } },
                  ],
                  slots: [],
                  commands: [],
                },
              },
            },
            {
              id: 'declarative',
              enabled: true,
              manifest: {
                manifest_version: 3,
                api_version: 3,
                version: '2.1.0',
                frontend: true,
                frontend_entry: '',
                frontend_styles: [],
                frontend_global_styles: [],
                render_mode: 'declarative',
                capabilities: [],
                contributions: {
                  menus: [
                    { id: 'cmd-node', placement: 'commandPalette', type: 'item', label: 'Run',
                      action: { type: 'command', id: 'run' } },
                  ],
                  slots: [],
                  commands: [
                    { id: 'run', title: 'Run', module: 'frontend/commands.js', export: 'run' },
                  ],
                },
              },
            },
            {
              id: 'pure-static',
              enabled: true,
              manifest: {
                manifest_version: 3,
                api_version: 3,
                version: '0.1.0',
                frontend: true,
                frontend_entry: '',
                frontend_styles: [],
                frontend_global_styles: [],
                render_mode: 'declarative',
                capabilities: [],
                contributions: {
                  menus: [
                    { id: 'static-item', placement: 'commandPalette', type: 'item', label: 'S',
                      action: { type: 'url', url: 'https://example.com/static' } },
                  ],
                  slots: [],
                  commands: [],
                },
              },
            },
            {
              id: 'disabled-plugin',
              enabled: false,
              manifest: { frontend: true, frontend_entry: 'frontend/never.js' },
            },
          ],
        };

        globalThis.fetch = async (url) => ({
          ok: true,
          status: 200,
          json: async () => (
            String(url).includes('/api/plugins/list') ? payload : { success: false }
          ),
        });

        // ---- 入口 / 贡献模块：真实 import() 路径（loader hook 映射成 data: 模块）----
        const hookSource = [
          'export async function resolve(specifier, context, nextResolve) {',
          '  const target = String(specifier);',
          "  if (!target.startsWith('/api/plugins/')) return nextResolve(specifier, context);",
          '  const code = [',
          "    'globalThis.__moduleUrls = globalThis.__moduleUrls || [];',",
          "    'globalThis.__moduleUrls.push(import.meta.url);',",
          "    'export function activate(api) {',",
          "    '  globalThis.__activated = globalThis.__activated || [];',",
          "    '  globalThis.__activated.push(api.id);',",
          "    '  return () => { globalThis.__disposed = globalThis.__disposed || []; globalThis.__disposed.push(api.id); };',",
          "    '}',",
          "    'export function run(ctx) {',",
          "    '  globalThis.__commandRuns = globalThis.__commandRuns || [];',",
          "    '  globalThis.__commandRuns.push(ctx.pluginId);',",
          "    '}',",
          "  ].join('\\\\n');",
          "  return { url: 'data:text/javascript,' + encodeURIComponent(code) + '#' + encodeURIComponent(target), shortCircuit: true };",
          '}',
        ].join('\\n');
        await register('data:text/javascript,' + encodeURIComponent(hookSource));

        globalThis.__moduleUrls = [];
        globalThis.__activated = [];
        globalThis.__disposed = [];
        globalThis.__commandRuns = [];
        globalThis.__events.length = 0;

        PluginHost.init();
        await PluginHost.loadAll();
        // 懒加载与手动刷新会各调一次 loadAll —— 必须幂等（不得重复 activate）
        await PluginHost.loadAll();

        // 1) 两个需要前端激活的插件都必须加载成功（旧 bug：一个都没有）
        assert.deepEqual(
          Array.from(PluginHost.loaded.keys()).sort(),
          ['declarative', 'pet'],
          'S2 扁平 manifest 必须被识别为可激活',
        );
        assert.equal(PluginHost.failed.size, 0, '不得把真实 payload 判成激活失败');
        // 纯声明插件不激活但仍在注册表；禁用插件整体跳过
        assert.equal(PluginHost.needsFrontendActivation(payload.items[2].manifest), false);
        assert.deepEqual(
          ContributionRegistry.plugins.map((item) => item.id).sort(),
          ['declarative', 'pet', 'pure-static'],
        );

        // 2) entry 模块 import 且 activate 被调用（唯一有 entry 的 pet）
        assert.deepEqual([...globalThis.__activated], ['pet'], 'entry.activate 必须被调用');
        const importedTargets = globalThis.__moduleUrls.map(
          (url) => decodeURIComponent(url.split('#')[1] || ''),
        );
        assert.ok(
          importedTargets.some((target) => target.includes('/api/plugins/pet/assets/frontend/plugin.js')),
          'pet 的 frontend_entry 必须被真实 import',
        );
        assert.ok(
          importedTargets.some(
            (target) => target.includes('/api/plugins/declarative/assets/frontend/commands.js'),
          ),
          '纯声明插件的命令模块必须在激活期预加载',
        );

        // 3) 样式：pet 的 scoped 样式注入 head（带 data-plugin 便于卸载时回收）
        const petStyles = document.head.children
          .filter((node) => node.tagName === 'LINK' && node.dataset.plugin === 'pet')
          .map((node) => node.href);
        assert.deepEqual(petStyles, ['/api/plugins/pet/assets/frontend/plugin.css?v=1.0.0']);

        // 4) 静态 surface 菜单没有被「surface 尚未注册」丢掉（bug A 回归）
        assert.ok(
          ContributionRegistry.menuTree('dock').some((node) => node.key === 'pet:pet-dock'),
          '静态 surface 声明必须先进注册表（surface 运行期才注册）',
        );
        assert.ok(ContributionRegistry.getCommand('declarative', 'run'));

        // 5) 命令执行器可用（证明加载的 api / 模块缓存链路打通）
        assert.equal(
          PluginHost.executeContribution('declarative', 'cmd-node', 'palette', {}),
          true,
        );
        await new Promise((resolve) => setTimeout(resolve, 20));
        assert.deepEqual([...globalThis.__commandRuns], ['declarative']);

        // 6) 卸载走 activate 返回的 disposer
        assert.equal(PluginHost.destroy('pet'), true);
        assert.deepEqual([...globalThis.__disposed], ['pet']);

        assert.ok(
          globalThis.__events.some((event) => event.type === 'plugins:loaded'),
          'loadAll 必须广播 plugins:loaded',
        );

        process.stdout.write(JSON.stringify({
          loaded: Array.from(PluginHost.loaded.keys()).sort(),
          activated: [...globalThis.__activated],
          disposed: [...globalThis.__disposed],
          imports: importedTargets.length,
        }));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['loaded'] == ['declarative']
    assert payload['activated'] == ['pet']
    assert payload['disposed'] == ['pet']
