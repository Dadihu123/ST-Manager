"""自绘 / 共存契约测试（设计文档 §6.2 / §7；实现日志 S6、S8，ADR-0001/0007/0016）。

自绘插件自己画 UI，宿主的责任是**提供可预期的挂载点与回收手段**，而不是接管：

- `api.createRoot()` 两个层：`.plugin-layer--content`（内容之上、宿主模态之下）与
  `.plugin-layer--portal`（宿主模态之上、告警之下），都是 body 直接子元素、
  `position: fixed; inset: 0; pointer-events: none`；
- root 自带 `data-plugin` 与 `plugin-<id>`，由 `PluginRootHost` 跟踪，插件停用 /
  卸载 / kill switch 时整体移除；
- kill switch：关闭已登记浮层 → 广播 `overlays:force-closed` → 清 root，
  **不卸载、不停用插件**；
- 崩溃隔离：`plugin:runtime-error` → `pluginHost` 计数，5 次/分钟 → `plugin:degraded`。
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
OVERLAY_HOST_PATH = 'static/js/pluginOverlayHost.js'


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
    reason='Node.js is required for plugin self-render contract checks',
)

DOM_SHIM = r"""
class ShimClassList {
  constructor() { this.set = new Set(); }
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
    this.listeners = {};
    this.classList = new ShimClassList();
    this.dataset = {};
    this.attributes = {};
    this.textContent = '';
    this.style = {};
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
    if (child.id) shimDocument._byId.set(child.id, child);
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    if (child.id) shimDocument._byId.delete(child.id);
    return child;
  }
  get styleProperties() { return this._styleProperties || (this._styleProperties = {}); }
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
  contains(node) { return node === this || this.children.includes(node); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() { globalThis.__focused = this; }
}

const shimDocument = new ShimNode('#document');
shimDocument.body = new ShimNode('body');
shimDocument.head = new ShimNode('head');
shimDocument.documentElement = new ShimNode('html');
shimDocument.activeElement = null;
shimDocument.visibilityState = 'visible';
shimDocument._byId = new Map();
shimDocument.createElement = (tag) => {
  const node = new ShimNode(tag);
  return node;
};
shimDocument.createElementNS = (_ns, tag) => shimDocument.createElement(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(String(id)) || null;
shimDocument.contains = (node) => Boolean(node);
shimDocument.querySelectorAll = (selector) => {
  if (String(selector).includes('[data-plugin-slot]')) return globalThis.__anchors || [];
  const match = /\[data-plugin="([^"]+)"\]/.exec(String(selector));
  if (match) {
    const pluginId = match[1];
    const links = [];
    for (const node of shimDocument._byId.values()) {
      if (node.tagName === 'LINK' && node.dataset && node.dataset.plugin === pluginId) {
        links.push(node);
      }
    }
    return links;
  }
  return [];
};
globalThis.__anchors = [];

const windowListeners = new Map();
const dispatched = [];
globalThis.__dispatched = dispatched;
globalThis.document = shimDocument;
globalThis.window = {
  devicePixelRatio: 1,
  addEventListener(name, fn) {
    if (!windowListeners.has(name)) windowListeners.set(name, new Set());
    windowListeners.get(name).add(fn);
  },
  removeEventListener(name, fn) { windowListeners.get(name)?.delete(fn); },
  dispatchEvent(event) {
    dispatched.push(event);
    for (const fn of [...(windowListeners.get(event.type) || [])]) fn(event);
  },
  matchMedia() {
    return { matches: false, addEventListener() {}, removeEventListener() {} };
  },
  requestAnimationFrame(callback) { callback(0); return 0; },
  open() { return null; },
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.fetch = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ success: true, items: [] }),
});
const store = {
  currentMode: 'cards',
  deviceType: 'desktop',
  isDarkMode: true,
  viewState: { selectedIds: [] },
  indexStatus: { state: 'idle', scan_active: false },
  batchProgress: { status: 'idle', current: 0, total: 0 },
  showToast() {},
};
globalThis.__store = store;
globalThis.window.Alpine = {
  store: () => store,
  reactive: (value) => value,
  effect: () => () => {},
};
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    return run_node(DOM_SHIM + textwrap.dedent(body))


def run_json(body: str) -> dict:
    result = run_dom_script(body)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line for line in (result.stdout or '').strip().splitlines() if line.strip()]
    assert lines, result.stderr or result.stdout
    return json.loads(lines[-1])


# ------------------------------------------------------------------ 静态契约


def test_root_host_exports_and_layer_contract():
    source = read_source(ROOT_HOST_PATH)

    for fragment in (
        'export const PLUGIN_CONTENT_LAYER_ID = "plugin-layer-content"',
        'export const PLUGIN_PORTAL_LAYER_ID = "plugin-layer-portal"',
        'export const PLUGIN_LAYER_CLASS = "plugin-layer"',
        'export const PLUGIN_ROOT_CLASS = "plugin-root"',
        'export const PLUGIN_DATA_ATTRIBUTE = "data-plugin"',
        'export const PluginRootHost = {',
        'ensureLayers() {',
        'create(pluginId, options = {}) {',
        'getRoots(pluginId) {',
        'has(pluginId) {',
        'pluginIds() {',
        'clear(pluginId) {',
        'clearAll() {',
        'reset() {',
    ):
        assert fragment in source, fragment


def test_layers_are_fixed_pointer_transparent_body_children():
    source = read_source(ROOT_HOST_PATH)

    # 设计 §6.2：两层都是 body 直接子元素，fixed + inset 0 + 指针穿透
    assert 'document.body.appendChild(layer)' in source
    assert 'layer.style.position = "fixed"' in source
    assert 'layer.style.inset = "0"' in source
    assert 'layer.style.pointerEvents = "none"' in source
    assert 'plugin-layer--content' in source
    assert 'plugin-layer--portal' in source
    # 层级由 CSS 令牌承担，JS 不写 z-index（ADR-0016：层叠顺序归 CSS）
    assert 'zIndex' not in source
    assert 'z-index' not in source


def test_create_root_two_layers_and_kill_switch_order():
    host = read_source(HOST_PATH)

    assert 'PluginRootHost.create(pluginId, {' in host
    assert 'portal: Boolean(options.portal)' in host
    # kill switch 顺序：关闭浮层（含广播）→ 清 root；且**不得**卸载插件
    kill = host.split('killSwitch() {', 1)[1].split('async reloadPlugin', 1)[0]
    dismiss_index = kill.index('PluginOverlayHost.killSwitch([pluginId])')
    clear_index = kill.index('PluginRootHost.clear(pluginId)')
    assert dismiss_index < clear_index
    assert 'destroy(' not in kill
    assert 'deactivate' not in kill


def test_runtime_error_degrades_plugin_but_keeps_it_loaded():
    source = read_source(HOST_PATH)

    assert 'plugin:degraded' in source
    assert 'this.degraded.add(key)' in source
    assert 'isDegraded(pluginId) {' in source
    # 降级不卸载：reportRuntimeError 里不得调用 destroy / deactivate
    report = source.split('reportRuntimeError(pluginId, error, source = "") {', 1)[1] \
        .split('isDegraded(pluginId)', 1)[0]
    assert 'destroy(' not in report
    assert 'deactivate' not in report


def test_plugin_host_initializes_root_overlay_slot_hosts():
    source = read_source(HOST_PATH)

    assert 'PluginRootHost.ensureLayers();' in source
    assert 'PluginOverlayHost.init();' in source
    assert 'PluginSlotHost.init({' in source
    assert 'loadModule: (pluginId, modulePath, record) =>' in source
    assert 'getApi: (pluginId) => this.getPluginApi(pluginId)' in source


# ------------------------------------------------------------------ root 生命周期


@requires_node
def test_root_host_layers_roots_and_clear():
    payload = run_json(
        """
        import { PluginRootHost } from './static/js/pluginRootHost.js';

        PluginRootHost.ensureLayers();
        const second = PluginRootHost.ensureLayers();
        const existingContent = document.getElementById('plugin-layer-content');
        const secondEnsure = Boolean(second && second.content === existingContent);

        const content = PluginRootHost.create('demo-plugin', { tag: 'div' });
        const portal = PluginRootHost.create('demo-plugin', { portal: true });
        const button = PluginRootHost.create('demo-plugin', { tag: 'button' });
        const other = PluginRootHost.create('other-plugin');

        const bodyChildren = document.body.children.map((node) => node.id);

        process.stdout.write(JSON.stringify({
          layers: {
            content: document.getElementById('plugin-layer-content') !== null,
            portal: document.getElementById('plugin-layer-portal') !== null,
            bodyHasExactly: bodyChildren.filter((id) => id.startsWith('plugin-layer-')).length,
          },
          secondEnsure,
          sameContentLayer: content.parentNode
            && content.parentNode.id === 'plugin-layer-content',
          portalParent: portal.parentNode && portal.parentNode.id,
          buttonTag: button.tagName,
          content: {
            plugin: content.dataset.plugin,
            root: content.dataset.pluginRoot,
            className: content.className,
          },
          roots: PluginRootHost.getRoots('demo-plugin').length,
          has: PluginRootHost.has('other-plugin'),
          ids: PluginRootHost.pluginIds().sort(),
          cleared: PluginRootHost.clear('demo-plugin'),
          afterClear: PluginRootHost.getRoots('demo-plugin').length,
          otherStill: PluginRootHost.has('other-plugin'),
          detached: content.parentNode === null,
          clearedAll: PluginRootHost.clearAll(),
          otherDetached: other.parentNode === null,
          layersSurvive: document.getElementById('plugin-layer-content') !== null,
          reset: PluginRootHost.reset(),
          layersAfterReset: document.getElementById('plugin-layer-content') !== null,
        }));
        """
    )
    assert payload['layers'] == {
        'content': True,
        'portal': True,
        'bodyHasExactly': 2,
    }
    assert payload['secondEnsure'] is True
    assert payload['sameContentLayer'] is True
    assert payload['portalParent'] == 'plugin-layer-portal'
    assert payload['buttonTag'] == 'BUTTON'
    assert payload['content']['plugin'] == 'demo-plugin'
    assert payload['content']['root'] == 'content'
    assert 'plugin-root' in payload['content']['className']
    assert 'plugin-demo-plugin' in payload['content']['className']
    assert payload['roots'] == 3
    assert payload['has'] is True
    assert payload['ids'] == ['demo-plugin', 'other-plugin']
    assert payload['cleared'] == 3
    assert payload['afterClear'] == 0
    assert payload['otherStill'] is True
    assert payload['detached'] is True
    assert payload['clearedAll'] == 1
    assert payload['otherDetached'] is True
    # clear 只清 root，层本身保留（下次插件还往同一层挂）
    assert payload['layersSurvive'] is True
    assert payload['reset'] is True
    assert payload['layersAfterReset'] is False


@requires_node
def test_destroy_removes_self_render_roots():
    payload = run_json(
        """
        import { PluginHost } from './static/js/pluginHost.js';
        import { PluginRootHost } from './static/js/pluginRootHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        api.createRoot();
        api.createRoot({ portal: true });
        PluginHost.loaded.set('demo-plugin', {
          entry: { id: 'demo-plugin' }, manifest: {}, api, module: null,
          root: null, version: '1.0.0',
        });

        const before = PluginRootHost.getRoots('demo-plugin').length;
        const destroyed = PluginHost.destroy('demo-plugin');

        process.stdout.write(JSON.stringify({
          before, destroyed,
          after: PluginRootHost.getRoots('demo-plugin').length,
          loaded: PluginHost.loaded.has('demo-plugin'),
        }));
        """
    )
    assert payload['before'] == 2
    assert payload['destroyed'] is True
    assert payload['after'] == 0
    assert payload['loaded'] is False


# ------------------------------------------------------------------ kill switch


@requires_node
def test_kill_switch_clears_roots_and_overlays_without_unloading_plugins():
    payload = run_json(
        """
        import { PluginHost } from './static/js/pluginHost.js';
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        PluginHost.init();
        ContributionRegistry.setPlugins([
          { id: 'demo-plugin', enabled: true, manifest: { contributions: { menus: [] } } },
        ]);
        PluginHost.loaded.set('demo-plugin', {
          entry: { id: 'demo-plugin' }, manifest: {}, api: null, module: null,
          root: null, version: '1.0.0',
        });

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        api.createRoot();
        api.createRoot({ portal: true });
        const dismissed = [];
        const unregister = api.overlays.register({
          id: 'popover', element: {}, modal: true,
          onDismiss() { dismissed.push('popover'); },
        });

        globalThis.__dispatched.length = 0;
        window.dispatchEvent(new CustomEvent('plugins:close-overlays'));

        process.stdout.write(JSON.stringify({
          dismissed,
          roots: 0,
          loadedStill: PluginHost.loaded.has('demo-plugin'),
          registryStill: ContributionRegistry.plugins.length,
          overlays: PluginOverlayHost.list('demo-plugin').length,
          forceClosed: globalThis.__dispatched
            .filter((event) => event.type === 'overlays:force-closed')
            .map((event) => event.detail.pluginId),
          unregisterType: typeof unregister,
        }));
        """
    )
    assert payload['dismissed'] == ['popover'], '① 已登记浮层逐个 onDismiss'
    assert payload['forceClosed'] == ['demo-plugin'], '② 广播 overlays:force-closed'
    assert payload['overlays'] == 0
    # ③ 插件本身保持加载：kill switch 只回收界面
    assert payload['loadedStill'] is True
    assert payload['registryStill'] == 1


# ------------------------------------------------------------------ 降级（事件集成）


@requires_node
def test_repeated_runtime_errors_mark_plugin_degraded():
    payload = run_json(
        """
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        globalThis.__dispatched.length = 0;
        const toast = [];
        globalThis.__store.showToast = (message) => toast.push(message);

        for (let index = 0; index < 4; index += 1) {
          window.dispatchEvent(new CustomEvent('plugin:runtime-error', {
            detail: { pluginId: 'demo-plugin', error: new Error('boom'), source: 'slot.renderer' },
          }));
        }
        const before = PluginHost.isDegraded('demo-plugin');

        window.dispatchEvent(new CustomEvent('plugin:runtime-error', {
          detail: { pluginId: 'demo-plugin', error: new Error('boom'), source: 'slot.renderer' },
        }));

        process.stdout.write(JSON.stringify({
          before,
          after: PluginHost.isDegraded('demo-plugin'),
          degradedEvents: globalThis.__dispatched
            .filter((event) => event.type === 'plugin:degraded')
            .map((event) => event.detail.pluginId),
          toasts: toast.length,
          loaded: PluginHost.loaded.size,
        }));
        """
    )
    assert payload['before'] is False
    assert payload['after'] is True
    assert payload['degradedEvents'] == ['demo-plugin']
    assert payload['toasts'] >= 1, '运行期错误要有用户可见提示'
    # 降级不卸载插件（loaded 里本来就没有它；关键是不抛错、不影响其他插件）
    assert payload['loaded'] == 0


# ------------------------------------------------------------------ 静态 surface 执行


@requires_node
def test_executing_unregistered_surface_action_warns_and_is_ignored():
    """设计 §4.3 + §6：静态 surface 菜单先入表；点击时未注册 → 警告 + 忽略，不抛错。"""
    payload = run_json(
        """
        import { PluginHost } from './static/js/pluginHost.js';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        PluginHost.init();
        // 真实 S2 扁平 manifest：自绘插件在声明式宿主 UI 里的入口（surface 菜单）
        ContributionRegistry.setPlugins([
          {
            id: 'pet',
            enabled: true,
            manifest: {
              manifest_version: 3, api_version: 3, version: '1.0.0',
              frontend: true, frontend_entry: 'frontend/plugin.js',
              frontend_styles: [], frontend_global_styles: [],
              render_mode: 'custom', capabilities: ['ui.custom', 'ui.ambient'],
              contributions: {
                menus: [
                  { id: 'pet-dock', placement: 'dock', type: 'item', label: 'Pet',
                    action: { type: 'surface', id: 'pet-settings' } },
                ],
                slots: [], commands: [],
              },
            },
          },
        ]);

        // ① 静态声明必须先进注册表（surface 尚未注册也不能丢）
        const dockKeys = ContributionRegistry.menuTree('dock').map((node) => node.key);

        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (...args) => { warnings.push(args.join(' ')); };
        let result = null;
        let threw = false;
        try {
          result = PluginHost.executeContribution('pet', 'pet-dock', 'dock', {});
        } catch (error) {
          threw = true;
          warnings.push(String(error && error.message));
        } finally {
          console.warn = originalWarn;
        }

        process.stdout.write(JSON.stringify({
          dockKeys, result, threw,
          warnings: warnings.map((text) => String(text)),
          degraded: PluginHost.isDegraded('pet'),
        }));
        """
    )
    assert payload['dockKeys'] == ['pet:pet-dock']
    assert payload['result'] is False, '未注册 surface 的点击必须被忽略'
    assert payload['threw'] is False, '必须是警告 + 忽略，不能抛错'
    assert any('pet-settings' in warning for warning in payload['warnings'])
    assert any('未注册' in warning for warning in payload['warnings'])
    assert payload['degraded'] is False, '点击被忽略不是运行期崩溃，不应降级'


# ------------------------------------------------------------------ 模块预加载（S5）


def test_activation_preflight_checks_every_slot_and_command_module():
    source = read_source(HOST_PATH)

    assert 'async preloadContributionModules(pluginId, manifest, version = "")' in source
    preload = source.split('async preloadContributionModules', 1)[1] \
        .split('loadContributionModule(pluginId, modulePath, record = null)', 1)[0]
    assert 'contributions.slots' in preload
    assert 'contributions.commands' in preload
    assert 'typeof exported !== "function"' in preload
    assert '缺少导出函数' in preload


def test_plugins_without_frontend_are_not_activated_but_are_registered():
    source = read_source(HOST_PATH)

    assert 'needsFrontendActivation(manifest)' in source
    assert 'ContributionRegistry.setPlugins(items);' in source


@requires_node
def test_load_plugin_preflight_failure_marks_failed_and_keeps_backend():
    payload = run_json(
        """
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const entry = { id: 'broken-plugin', enabled: true };
        // S2 定稿快照：frontend 是 boolean，入口/贡献都在扁平字段上。
        const manifest = {
          version: '1.0.0',
          frontend: true,
          frontend_entry: 'frontend/main.js',
          contributions: {
            slots: [
              { id: 'settings', slot: 'settings.section', title: 'S',
                module: 'frontend/settings.js', export: 'mountSettings' },
            ],
          },
        };

        // 贡献模块 import 失败 → 激活失败（不是插槽占位）：failed 记录 + 重试入口，
        // 后端插件仍在运行（这里不触达后端，只验证前端不让注册表/其他插件受牵连）。
        const originalImport = globalThis.__importUrl;
        const result = await PluginHost.loadPlugin(entry, manifest).then(
          () => ({ ok: true }),
          (error) => ({ ok: false, message: String(error && error.message) }),
        );

        process.stdout.write(JSON.stringify({
          result,
          failed: PluginHost.failed.get('broken-plugin') || '',
          loaded: PluginHost.loaded.has('broken-plugin'),
          hasRetry: typeof PluginHost.reloadPlugin === 'function',
        }));
        """
    )
    assert payload['result']['ok'] is False
    assert 'settings.js' in payload['failed'], payload['failed']
    assert payload['loaded'] is False
    assert payload['hasRetry'] is True
