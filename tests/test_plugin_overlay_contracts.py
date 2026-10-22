"""插件浮层登记（`api.overlays`）契约测试（设计文档 §6.3 / §7.3；S6、ADR-0007/0016）。

宿主**不接管**插件自绘浮层，只提供可选的最小协调：

- `register(spec) -> unregister`；`layer` 只是建议值（7 档），`modal` 参与 ESC；
- ESC 只关**最上层** `modal: true` 的已登记浮层，并 `preventDefault` +
  `stopImmediatePropagation`（避免同一次 ESC 又关宿主 surface），随后归还焦点；
- `closeAll` 按登记顺序**倒序**逐个 `onDismiss`，回调异常被隔离并上报
  `plugin:runtime-error`；
- kill switch：`killSwitch(ids)` = 逐个插件关闭 + 广播 `overlays:force-closed`
  `{pluginId}`；不卸载 / 不停用插件。

沿用仓库既有做法：静态源码契约 + Node 最小 DOM 垫片下真实执行模块。
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
    reason='Node.js is required for plugin overlay contract checks',
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
  focus() { globalThis.__focused = this; }
  contains(node) { return node === this || this.children.includes(node); }
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


def test_overlay_layer_enum_matches_contract():
    source = read_source(OVERLAY_HOST_PATH)

    layers = ["content", "ambient", "surface", "dock", "popover", "tooltip", "alert"]
    assert 'export const OVERLAY_LAYERS = [' in source
    for layer in layers:
        assert f'"{layer}",' in source, layer
    assert 'export const DEFAULT_OVERLAY_LAYER = "popover"' in source
    assert 'export const OVERLAYS_FORCE_CLOSED_EVENT = "overlays:force-closed"' in source


def test_overlay_registration_api():
    source = read_source(OVERLAY_HOST_PATH)

    for fragment in (
        'register(pluginId, spec = {}) {',
        'unregister(pluginId, id) {',
        'list(pluginId = "") {',
        'get(pluginId, id) {',
        'count(pluginId = "") {',
        'pluginIds() {',
        'closeAll(pluginId) {',
        'closeAllPlugins() {',
        'killSwitch(pluginIds = null) {',
        'topMostModal() {',
        'handleKeydown(event) {',
        'clearPlugin(pluginId) {',
    ):
        assert fragment in source, fragment
    # list() 必须剔除 DOM 引用与回调（管理器 / 调试面板只消费元数据）
    assert 'element,' not in source.split('list(pluginId = "")')[1].split('},')[0]


def test_overlay_esc_listener_is_capture_phase():
    source = read_source(OVERLAY_HOST_PATH)

    assert 'document.addEventListener("keydown"' in source
    assert ', true);' in source
    # 只处理 Escape，且只关最上层 modal
    assert 'event.key !== "Escape"' in source
    assert 'this.topMostModal()' in source
    assert 'event.stopImmediatePropagation' in source


def test_overlay_init_mounts_no_dom():
    """浮层宿主不建 DOM（插件自己画），只登记元数据。"""
    source = read_source(OVERLAY_HOST_PATH)

    assert 'document.createElement' not in source
    assert 'appendChild' not in source


# ------------------------------------------------------------------ 登记 / 查询


@requires_node
def test_register_list_and_unregister():
    payload = run_json(
        """
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';

        PluginOverlayHost.init();
        const element = { id: 'popup' };
        const unregister = PluginOverlayHost.register('demo-plugin', {
          id: 'picker', element, layer: 'alert', modal: true, label: '颜色选择',
        });

        const listed = PluginOverlayHost.list();
        const own = PluginOverlayHost.list('demo-plugin');
        const other = PluginOverlayHost.list('ghost');
        const record = PluginOverlayHost.get('demo-plugin', 'picker');

        const removed = unregister();
        process.stdout.write(JSON.stringify({
          type: typeof unregister,
          listed,
          own,
          other,
          count: PluginOverlayHost.count('demo-plugin'),
          removed,
          removedAgain: PluginOverlayHost.unregister('demo-plugin', 'picker'),
          hasElement: Object.prototype.hasOwnProperty.call(listed[0] || {}, 'element'),
          recordHasElement: Boolean(record && record.element),
          recordHasCallback: Boolean(record && record.onDismiss),
          ids: PluginOverlayHost.pluginIds(),
        }));
        """
    )
    assert payload['type'] == 'function'
    assert payload['listed'] == [{
        'key': 'demo-plugin:picker',
        'id': 'picker',
        'pluginId': 'demo-plugin',
        'layer': 'alert',
        'modal': True,
        'label': '颜色选择',
    }]
    assert payload['own'] == payload['listed']
    assert payload['other'] == []
    assert payload['count'] == 0
    assert payload['removed'] is True
    assert payload['removedAgain'] is False
    assert payload['hasElement'] is False, 'list() 不得泄露 DOM 引用'
    assert payload['recordHasElement'] is True
    assert payload['recordHasCallback'] is False
    assert payload['ids'] == []


@requires_node
def test_register_validates_and_falls_back_layer():
    payload = run_json(
        """
        import { PluginOverlayHost, DEFAULT_OVERLAY_LAYER } from './static/js/pluginOverlayHost.js';

        const noopA = PluginOverlayHost.register('', { id: 'x', element: {} });
        const noopB = PluginOverlayHost.register('demo', { id: '', element: {} });
        const noopC = PluginOverlayHost.register('demo', { id: 'x' });
        assert.equal(typeof noopA, 'function');

        PluginOverlayHost.register('demo', { id: 'bad-layer', element: {}, layer: 'nope' });
        PluginOverlayHost.register('demo', { id: 'explicit', element: {}, layer: 'tooltip' });

        process.stdout.write(JSON.stringify({
          defaultLayer: DEFAULT_OVERLAY_LAYER,
          records: PluginOverlayHost.list('demo').map((record) => ({
            id: record.id, layer: record.layer,
          })),
        }));
        """
    )
    assert payload['defaultLayer'] == 'popover'
    assert payload['records'] == [
        {'id': 'bad-layer', 'layer': 'popover'},
        {'id': 'explicit', 'layer': 'tooltip'},
    ]


@requires_node
def test_reregister_same_id_replaces_previous():
    payload = run_json(
        """
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';
        PluginOverlayHost.register('demo', { id: 'a', element: {}, layer: 'content' });
        PluginOverlayHost.register('demo', { id: 'a', element: {}, layer: 'alert' });
        process.stdout.write(JSON.stringify({
          count: PluginOverlayHost.count('demo'),
          layer: PluginOverlayHost.list('demo')[0].layer,
        }));
        """
    )
    assert payload['count'] == 1
    assert payload['layer'] == 'alert'


# ------------------------------------------------------------------ ESC / 焦点


@requires_node
def test_esc_closes_only_topmost_modal_and_restores_focus():
    payload = run_json(
        """
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';

        PluginOverlayHost.init();
        const focused = [];
        const opener = { focus() { focused.push('opener'); } };
        document.activeElement = opener;

        let dismissed = [];
        PluginOverlayHost.register('alpha', {
          id: 'modal-1', element: {}, modal: true,
          onDismiss() { dismissed.push('alpha:modal-1'); },
        });
        PluginOverlayHost.register('alpha', {
          id: 'popover', element: {}, modal: false,
          onDismiss() { dismissed.push('alpha:popover'); },
        });
        PluginOverlayHost.register('beta', {
          id: 'modal-2', element: {}, modal: true,
          onDismiss() { dismissed.push('beta:modal-2'); },
        });

        const makeEvent = () => ({
          key: 'Escape',
          defaultPrevented: false,
          immediateStopped: false,
          preventDefault() { this.defaultPrevented = true; },
          stopImmediatePropagation() { this.immediateStopped = true; },
        });

        const first = makeEvent();
        document.dispatch('keydown', first);

        const afterFirst = PluginOverlayHost.list().map((record) => record.key);
        const firstResult = {
          dismissed: [...dismissed],
          defaultPrevented: first.defaultPrevented,
          immediateStopped: first.immediateStopped,
          focused: [...focused],
        };

        const second = makeEvent();
        document.dispatch('keydown', second);
        const afterSecond = PluginOverlayHost.list().map((record) => record.key);

        const third = makeEvent();
        document.dispatch('keydown', third);

        // 非 Escape 键 / 无 modal 时不得拦截
        const other = makeEvent();
        other.key = 'Enter';
        document.dispatch('keydown', other);

        process.stdout.write(JSON.stringify({
          firstResult,
          afterFirst,
          secondResult: {
            dismissed,
            defaultPrevented: second.defaultPrevented,
            immediateStopped: second.immediateStopped,
            focused: [...focused],
          },
          afterSecond,
          thirdDefaultPrevented: third.defaultPrevented,
          enterDefaultPrevented: other.defaultPrevented,
        }));
        """
    )
    # 浏览器 ESC 语义：只关最上层 modal，其它浮层保持
    assert payload['firstResult']['dismissed'] == ['beta:modal-2']
    assert payload['firstResult']['defaultPrevented'] is True
    assert payload['firstResult']['immediateStopped'] is True
    assert payload['afterFirst'] == ['alpha:modal-1', 'alpha:popover']
    # 第一次 ESC 归还焦点（记录的是登记时的 activeElement）
    assert payload['firstResult']['focused'] == ['opener']
    assert payload['secondResult']['dismissed'] == ['beta:modal-2', 'alpha:modal-1']
    assert payload['afterSecond'] == ['alpha:popover']
    # 没有 modal 时 ESC 不拦截
    assert payload['thirdDefaultPrevented'] is False
    assert payload['enterDefaultPrevented'] is False


# ------------------------------------------------------------------ closeAll / kill switch


@requires_node
def test_close_all_is_reverse_order_and_isolates_callback_errors():
    payload = run_json(
        """
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';

        const calls = [];
        PluginOverlayHost.register('demo', {
          id: 'first', element: {},
          onDismiss() { calls.push('first'); },
        });
        PluginOverlayHost.register('demo', {
          id: 'boom', element: {},
          onDismiss() { calls.push('boom'); throw new Error('onDismiss 炸了'); },
        });
        PluginOverlayHost.register('demo', {
          id: 'last', element: {},
          onDismiss() { calls.push('last'); },
        });
        PluginOverlayHost.register('other', {
          id: 'untouched', element: {},
          onDismiss() { calls.push('other'); },
        });

        globalThis.__dispatched.length = 0;
        const closed = PluginOverlayHost.closeAll('demo');

        process.stdout.write(JSON.stringify({
          calls,
          closed,
          remaining: PluginOverlayHost.list().map((record) => record.key),
          runtimeErrors: globalThis.__dispatched
            .filter((event) => event.type === 'plugin:runtime-error')
            .map((event) => event.detail),
        }));
        """
    )
    # 倒序：last → boom（抛错但继续）→ first
    assert payload['calls'] == ['last', 'boom', 'first']
    assert payload['closed'] == 3
    assert payload['remaining'] == ['other:untouched']
    assert len(payload['runtimeErrors']) == 1
    assert payload['runtimeErrors'][0]['source'] == 'overlay.onDismiss'


@requires_node
def test_kill_switch_closes_and_broadcasts_per_plugin():
    payload = run_json(
        """
        import { PluginOverlayHost, OVERLAYS_FORCE_CLOSED_EVENT } from './static/js/pluginOverlayHost.js';

        const dismissed = [];
        PluginOverlayHost.register('alpha', {
          id: 'a1', element: {}, onDismiss() { dismissed.push('alpha:a1'); },
        });
        PluginOverlayHost.register('beta', {
          id: 'b1', element: {}, modal: true, onDismiss() { dismissed.push('beta:b1'); },
        });

        globalThis.__dispatched.length = 0;
        const handled = PluginOverlayHost.killSwitch();

        const broadcast = globalThis.__dispatched
          .filter((event) => event.type === OVERLAYS_FORCE_CLOSED_EVENT)
          .map((event) => event.detail.pluginId);

        // 指定 id 时，即使没有登记浮层也要广播（供插件重置状态）
        globalThis.__dispatched.length = 0;
        const explicit = PluginOverlayHost.killSwitch(['ghost', 'alpha']);

        process.stdout.write(JSON.stringify({
          handled,
          dismissed,
          broadcast,
          remaining: PluginOverlayHost.list(),
          explicit,
          explicitBroadcast: globalThis.__dispatched
            .filter((event) => event.type === OVERLAYS_FORCE_CLOSED_EVENT)
            .map((event) => event.detail.pluginId),
          demonstrablyStillRegistered: PluginOverlayHost.count() === 0,
        }));
        """
    )
    assert payload['handled'] == ['alpha', 'beta']
    assert payload['dismissed'] == ['alpha:a1', 'beta:b1']
    assert payload['broadcast'] == ['alpha', 'beta']
    assert payload['remaining'] == []
    assert payload['explicit'] == ['ghost', 'alpha']
    assert payload['explicitBroadcast'] == ['ghost', 'alpha']


@requires_node
def test_close_all_plugins_and_clear_plugin():
    payload = run_json(
        """
        import { PluginOverlayHost } from './static/js/pluginOverlayHost.js';

        const dismissed = [];
        PluginOverlayHost.register('alpha', {
          id: 'a', element: {}, onDismiss() { dismissed.push('alpha'); },
        });
        PluginOverlayHost.register('beta', {
          id: 'b', element: {}, onDismiss() { dismissed.push('beta'); },
        });

        // clearPlugin 是「静默清理」：插件已经卸载，不应再回调 onDismiss
        const removed = PluginOverlayHost.clearPlugin('alpha');
        const plugins = PluginOverlayHost.closeAllPlugins();

        process.stdout.write(JSON.stringify({
          removed, plugins, dismissed,
          remaining: PluginOverlayHost.list(),
        }));
        """
    )
    assert payload['removed'] == 1
    assert payload['plugins'] == ['beta']
    assert payload['dismissed'] == ['beta']
    assert payload['remaining'] == []
