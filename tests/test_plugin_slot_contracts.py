"""插件插槽宿主（`data-plugin-slot` + `contributions.slots[]`）契约测试。

设计文档 §4.5 / §5.2 / §7.1；实现日志 S5、S7。

宿主模板只放空容器：

    <div data-plugin-slot="settings.section"></div>

`pluginSlotHost.js` 扫描锚点 → 建包装节点（`data-plugin` / `data-slot` /
`data-contribution-id`）→ 动态 import 渲染器 → `mount(container, ctx) -> cleanup`。
宿主保证：容器定位/滚动/回收归宿主；`when` 不满足的插槽不挂载；渲染器抛错 →
错误占位 + `plugin:runtime-error`（插件降级，不影响其他插件）；刷新时机为
`contributions:changed` / `mode-changed` / `plugins:loaded` / `plugin:unloaded`。
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

SLOT_HOST_PATH = 'static/js/pluginSlotHost.js'


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
    reason='Node.js is required for plugin slot contract checks',
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
    this.style = { setProperty() {} };
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
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
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
  contains(node) { return node === this || this.children.includes(node); }
  querySelectorAll() { return []; }
}

const shimDocument = new ShimNode('#document');
shimDocument.body = new ShimNode('body');
shimDocument.documentElement = new ShimNode('html');
shimDocument.activeElement = null;
shimDocument._byId = new Map();
shimDocument.createElement = (tag) => new ShimNode(tag);
shimDocument.createElementNS = (_ns, tag) => new ShimNode(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(String(id)) || null;
shimDocument.contains = (node) => Boolean(node);
/** 插槽锚点登记表：`__addAnchor(slotName, dataset)` 返回锚点节点。 */
globalThis.__anchors = [];
shimDocument.querySelectorAll = (selector) => {
  if (String(selector).includes('[data-plugin-slot]')) return [...globalThis.__anchors];
  return [];
};
globalThis.__addAnchor = (slotName, dataset = {}) => {
  const anchor = new ShimNode('div');
  anchor.setAttribute('data-plugin-slot', slotName);
  Object.assign(anchor.dataset, dataset);
  globalThis.__anchors.push(anchor);
  return anchor;
};

const windowListeners = new Map();
const dispatched = [];
globalThis.__dispatched = dispatched;
globalThis.document = shimDocument;
globalThis.window = {
  addEventListener(name, fn) {
    if (!windowListeners.has(name)) windowListeners.set(name, new Set());
    windowListeners.get(name).add(fn);
  },
  removeEventListener(name, fn) { windowListeners.get(name)?.delete(fn); },
  dispatchEvent(event) {
    dispatched.push(event);
    for (const fn of [...(windowListeners.get(event.type) || [])]) fn(event);
  },
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.__store = {
  currentMode: 'cards',
  deviceType: 'desktop',
  viewState: { selectedIds: ['card-1'] },
  indexStatus: { state: 'idle' },
};
globalThis.window.Alpine = {
  store: () => globalThis.__store,
  effect: () => () => {},
  reactive: (value) => value,
};
globalThis.__setMode = (mode) => { globalThis.__store.currentMode = mode; };
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    return run_node(DOM_SHIM + textwrap.dedent(body))


def run_json(body: str) -> dict:
    result = run_dom_script(body)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line for line in (result.stdout or '').strip().splitlines() if line.strip()]
    assert lines, result.stderr or result.stdout
    return json.loads(lines[-1])


# 共享的插件声明：一个合法插槽、一个 `when` 受限插槽、一个无 api 插件。
PLUGINS_FIXTURE = r"""
import { ContributionRegistry } from './static/js/contributionRegistry.js';
import { PluginSlotHost } from './static/js/pluginSlotHost.js';

ContributionRegistry.setPlugins([
  {
    id: 'alpha',
    enabled: true,
    manifest: { contributions: { slots: [
      { id: 'settings-alpha', slot: 'settings.section', title: 'Alpha',
        order: 10, module: 'frontend/settings.js', export: 'mountSettings' },
      { id: 'header-alpha', slot: 'header.actions', title: 'A',
        order: 20, module: 'frontend/header.js', export: 'mountHeader' },
      { id: 'worldinfo-only', slot: 'settings.section', title: 'WI',
        order: 30, when: { mode: ['worldinfo'] },
        module: 'frontend/wi.js', export: 'mountWi' },
      { id: 'bad-module', slot: 'header.actions', title: 'Bad',
        order: 40, module: 'frontend/bad.js', export: 'mountBad' },
    ] } },
  },
]);
"""


# ------------------------------------------------------------------ 静态契约


def test_slot_host_exports():
    source = read_source(SLOT_HOST_PATH)

    for fragment in (
        'export const SLOT_ANCHOR_ATTRIBUTE = "data-plugin-slot"',
        'export const SLOT_WRAPPER_CLASS = "plugin-slot"',
        'export const SLOT_ERROR_CLASS = "plugin-slot__error"',
        'export const SLOT_ERROR_TEXT = "插件内容加载失败"',
        'export const SLOT_REFRESH_EVENTS = [',
        'export const PluginSlotHost = {',
        'init(options = {}) {',
        'configure(options = {}) {',
        'scheduleRefresh() {',
        'async refresh() {',
        'refreshAll() {',
        'clearPlugin(pluginId) {',
        'reset() {',
    ):
        assert fragment in source, fragment

    for name in ('contributions:changed', 'mode-changed', 'plugins:loaded', 'plugin:unloaded'):
        assert f'"{name}",' in source, name


def test_refresh_tears_down_before_rescanning():
    source = read_source(SLOT_HOST_PATH)

    refresh = source.split('async refresh() {', 1)[1].split('async refreshAll', 1)[0] \
        if 'async refreshAll' in source else source.split('async refresh() {', 1)[1]
    assert '_teardownAll()' in refresh
    assert 'querySelectorAll(`[${SLOT_ANCHOR_ATTRIBUTE}]`)' in refresh


def test_wrapper_and_error_placeholder_contract():
    source = read_source(SLOT_HOST_PATH)

    assert 'wrapper.className = SLOT_WRAPPER_CLASS' in source
    assert 'wrapper.dataset.plugin = record.pluginId' in source
    assert 'wrapper.dataset.slot = record.slot' in source
    assert 'wrapper.dataset.contributionId = record.id' in source
    assert 'placeholder.dataset.pluginError = "1"' in source
    assert 'placeholder.setAttribute("role", "alert")' in source
    assert 'placeholder.textContent = SLOT_ERROR_TEXT' in source


def test_when_filtered_slots_are_not_mounted():
    source = read_source(SLOT_HOST_PATH)

    assert 'if (!record.ok || record.enabled === false) continue;' in source


def test_slot_host_does_not_hardcode_position_or_z_index():
    """容器由宿主模板定位；宿主 JS 不得注入 position/z-index（CSS 归 frontend-render）。"""
    source = read_source(SLOT_HOST_PATH)

    assert 'style.zIndex' not in source
    assert 'style.position' not in source
    assert 'z-index:' not in source
    assert 'position:' not in source


# ------------------------------------------------------------------ 挂载 / 上下文


@requires_node
def test_refresh_mounts_slots_with_wrapper_and_context():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const settingsAnchor = globalThis.__addAnchor('settings.section');
        const headerAnchor = globalThis.__addAnchor('header.actions');
        const api = { pluginId: 'alpha', marker: true };
        const mounts = [];

        PluginSlotHost.init({
          loadModule: async (pluginId, modulePath) => ({
            mountSettings(container, ctx) {
              mounts.push({ pluginId, modulePath, container, ctx });
              container.textContent = 'settings';
            },
            mountHeader(container, ctx) {
              mounts.push({ pluginId, modulePath, container, ctx });
            },
            mountBad() { throw new Error('boom'); },
          }),
          getApi: (pluginId) => api,
        });

        const entries = await PluginSlotHost.refresh();
        const wrapper = settingsAnchor.children[0];

        process.stdout.write(JSON.stringify({
          entries: entries.map((entry) => ({
            pluginId: entry.pluginId, slot: entry.slot, id: entry.id,
          })),
          wrappers: {
            settings: settingsAnchor.children.length,
            header: headerAnchor.children.length,
          },
          wrapper: {
            className: wrapper.className,
            plugin: wrapper.dataset.plugin,
            slot: wrapper.dataset.slot,
            contributionId: wrapper.dataset.contributionId,
          },
          mount: {
            pluginId: mounts[0].pluginId,
            modulePath: mounts[0].modulePath,
            hasApi: mounts[0].ctx.api === api,
            slot: mounts[0].ctx.slot,
            mode: mounts[0].ctx.mode,
            selection: mounts[0].ctx.selection,
            target: mounts[0].ctx.target,
            content: mounts[0].container.textContent,
          },
        }));
        """
    )
    assert payload['entries'] == [
        {'pluginId': 'alpha', 'slot': 'settings.section', 'id': 'settings-alpha'},
        {'pluginId': 'alpha', 'slot': 'header.actions', 'id': 'header-alpha'},
        {'pluginId': 'alpha', 'slot': 'header.actions', 'id': 'bad-module'},
    ]
    # settings 只 1 个包装（worldinfo-only 的 when 不满足被跳过）；
    # header 2 个包装（header-alpha + bad-module 的错误占位）
    assert payload['wrappers'] == {'settings': 1, 'header': 2}
    assert payload['wrapper'] == {
        'className': 'plugin-slot',
        'plugin': 'alpha',
        'slot': 'settings.section',
        'contributionId': 'settings-alpha',
    }
    assert payload['mount']['pluginId'] == 'alpha'
    assert payload['mount']['modulePath'] == 'frontend/settings.js'
    assert payload['mount']['hasApi'] is True
    assert payload['mount']['slot'] == 'settings.section'
    assert payload['mount']['mode'] == 'cards'
    assert payload['mount']['selection'] == {'mode': 'cards', 'ids': ['card-1']}
    assert payload['mount']['target'] is None
    assert payload['mount']['content'] == 'settings'


@requires_node
def test_refresh_teardown_calls_cleanup_and_remounts():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const anchor = globalThis.__addAnchor('settings.section');
        const calls = { mount: 0, cleanup: 0 };

        PluginSlotHost.init({
          loadModule: async () => ({
            mountSettings(container) {
              calls.mount += 1;
              return () => { calls.cleanup += 1; };
            },
          }),
          getApi: () => ({ pluginId: 'alpha' }),
        });

        await PluginSlotHost.refresh();
        const firstWrapper = anchor.children[0];
        const before = { ...calls };

        await PluginSlotHost.refresh();
        const secondWrapper = anchor.children[0];

        process.stdout.write(JSON.stringify({
          before,
          after: calls,
          anchorChildren: anchor.children.length,
          replaced: firstWrapper !== secondWrapper,
          firstDetached: firstWrapper.parentNode === null,
        }));
        """
    )
    assert payload['before'] == {'mount': 1, 'cleanup': 0}
    assert payload['after'] == {'mount': 2, 'cleanup': 1}
    assert payload['anchorChildren'] == 1
    assert payload['replaced'] is True
    assert payload['firstDetached'] is True


@requires_node
def test_when_filtered_slot_is_skipped_and_appears_in_worldinfo_mode():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const anchor = globalThis.__addAnchor('settings.section');
        const mounted = [];

        PluginSlotHost.init({
          loadModule: async (pluginId, modulePath) => ({
            mountSettings(container, ctx) {
              mounted.push(ctx.slot + ':' + ctx.mode + ':' + modulePath);
            },
            mountWi(container, ctx) {
              mounted.push(ctx.slot + ':' + ctx.mode + ':' + modulePath);
            },
            mountHeader(container, ctx) {
              mounted.push(ctx.slot + ':' + ctx.mode + ':' + modulePath);
            },
          }),
          getApi: () => ({ pluginId: 'alpha' }),
        });

        await PluginSlotHost.refresh();
        const cardsMode = mounted.length;

        globalThis.__setMode('worldinfo');
        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));
        await new Promise((resolve) => setTimeout(resolve, 0));

        process.stdout.write(JSON.stringify({
          cardsMode,
          worldinfoMode: mounted.slice(cardsMode),
        }));
        """
    )
    # 本用例只放了 settings.section 锚点：cards 模式挂 settings-alpha 一个
    assert payload['cardsMode'] == 1
    # worldinfo 模式下 worldinfo-only 插槽出现（settings-alpha 照常重挂）
    assert payload['worldinfoMode'] == [
        'settings.section:worldinfo:frontend/settings.js',
        'settings.section:worldinfo:frontend/wi.js',
    ]


@requires_node
def test_renderer_error_shows_placeholder_and_isolates():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const settingsAnchor = globalThis.__addAnchor('settings.section');
        const headerAnchor = globalThis.__addAnchor('header.actions');

        PluginSlotHost.init({
          loadModule: async (pluginId, modulePath) => {
            if (modulePath === 'frontend/bad.js') {
              throw new Error('模块加载失败');
            }
            return {
              mountSettings(container) { container.textContent = 'ok'; },
              mountHeader(container) { container.textContent = 'ok'; },
            };
          },
          getApi: () => ({ pluginId: 'alpha' }),
        });

        globalThis.__dispatched.length = 0;
        await PluginSlotHost.refresh();

        const errorWrappers = headerAnchor.children.filter(
          (node) => node.classList.contains('is-error'),
        );
        const placeholderNode = errorWrappers.flatMap((node) => node.children)[0];

        process.stdout.write(JSON.stringify({
          settingsChildren: settingsAnchor.children.length,
          headerChildren: headerAnchor.children.length,
          errorCount: errorWrappers.length,
          placeholder: placeholderNode && {
            className: placeholderNode.className,
            pluginError: placeholderNode.dataset.pluginError,
            role: placeholderNode.getAttribute('role'),
            text: placeholderNode.textContent,
          },
          runtimeErrors: globalThis.__dispatched
            .filter((event) => event.type === 'plugin:runtime-error')
            .map((event) => ({ pluginId: event.detail.pluginId, source: event.detail.source })),
        }));
        """
    )
    assert payload['settingsChildren'] == 1, '正常插槽不受影响'
    assert payload['headerChildren'] == 2
    assert payload['errorCount'] == 1
    assert payload['placeholder'] == {
        'className': 'plugin-slot__error',
        'pluginError': '1',
        'role': 'alert',
        'text': '插件内容加载失败',
    }
    assert payload['runtimeErrors'] == [{'pluginId': 'alpha', 'source': 'slot.renderer'}]


@requires_node
def test_slot_skipped_when_plugin_frontend_activation_failed():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const anchor = globalThis.__addAnchor('settings.section');
        let loaded = 0;

        PluginSlotHost.init({
          loadModule: async () => {
            loaded += 1;
            return { mountSettings() {} };
          },
          // 前端激活失败 → getApi 返回 null → 不挂载（激活期已由 pluginHost 预检）
          getApi: () => null,
        });

        await PluginSlotHost.refresh();
        process.stdout.write(JSON.stringify({
          loaded,
          children: anchor.children.length,
          mounted: PluginSlotHost.mountedEntries().length,
        }));
        """
    )
    assert payload['loaded'] >= 1, '渲染器加载才可能知道激活失败（预检之外的兜底）'
    assert payload['children'] == 0
    assert payload['mounted'] == 0


@requires_node
def test_contributions_changed_schedules_microtask_refresh():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const anchor = globalThis.__addAnchor('settings.section');
        let renders = 0;

        PluginSlotHost.init({
          loadModule: async () => ({
            mountSettings() { renders += 1; },
          }),
          getApi: () => ({ pluginId: 'alpha' }),
        });

        await PluginSlotHost.refresh();
        const initial = renders;

        // 两次变更合并成一次刷新（微任务去抖）
        globalThis.window.dispatchEvent(new CustomEvent('contributions:changed'));
        globalThis.window.dispatchEvent(new CustomEvent('contributions:changed'));
        await new Promise((resolve) => setTimeout(resolve, 0));

        process.stdout.write(JSON.stringify({ initial, after: renders }));
        """
    )
    assert payload['initial'] == 1
    assert payload['after'] == 2, '同一批变更只触发一次刷新'


@requires_node
def test_clear_plugin_and_reset_remove_mounts():
    payload = run_json(
        PLUGINS_FIXTURE
        + """
        const settingsAnchor = globalThis.__addAnchor('settings.section');
        const headerAnchor = globalThis.__addAnchor('header.actions');
        const cleaned = [];

        PluginSlotHost.init({
          loadModule: async (pluginId, modulePath) => ({
            mountSettings() { return () => cleaned.push('settings'); },
            mountHeader() { return () => cleaned.push('header'); },
          }),
          getApi: () => ({ pluginId: 'alpha' }),
        });

        await PluginSlotHost.refresh();
        const before = PluginSlotHost.mountedEntries().length;
        const removed = PluginSlotHost.clearPlugin('alpha');
        PluginSlotHost.reset();

        process.stdout.write(JSON.stringify({
          before, removed, cleaned,
          settingsChildren: settingsAnchor.children.length,
          headerChildren: headerAnchor.children.length,
          mounted: PluginSlotHost.mountedEntries().length,
        }));
        """
    )
    assert payload['before'] == 3, 'settings-alpha + header-alpha + bad-module（错误占位也算挂载）'
    assert payload['removed'] == 3
    assert payload['cleaned'] == ['settings', 'header']
    assert payload['settingsChildren'] == 0
    assert payload['headerChildren'] == 0
    assert payload['mounted'] == 0
