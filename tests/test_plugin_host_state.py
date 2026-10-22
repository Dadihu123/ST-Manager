"""宿主状态广播测试（`api.host.onState`，设计文档 D6）。

插件此前只能自己去读 `window.Alpine.store("global")` 来「与界面联动」——那是
Provisional 耦合，宿主改字段名插件就静默失效。`onState` 把宿主状态收成一份
快照并去抖推送。

覆盖的契约：
- 首次订阅**立即**推一次快照（插件不必自己先探一次）
- 变化时推送，且**合并去抖**（一帧一次，不是每个字段各推一次）
- `reducedMotion` 支持 `change` 事件监听（用户可在系统设置里改，不改页面就变）
- 返回取消订阅函数，取消后不再收到推送
- 快照字段形状固定
"""

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
    reason='Node.js is required for host state contract checks',
)


# ------------------------------------------------------------------ DOM 垫片

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
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.classList = new ShimClassList();
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
  focus() {}
  contains(node) { return node === this; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  get firstChild() { return this.children[0] || null; }
  get innerHTML() { return ''; }
  set innerHTML(_v) { this.children = []; }
}

const shimDocument = new ShimNode('#document');
shimDocument.body = new ShimNode('body');
shimDocument.documentElement = new ShimNode('html');
shimDocument.visibilityState = 'visible';
shimDocument.activeElement = null;
shimDocument._byId = new Map();
shimDocument.createElement = (tag) => new ShimNode(tag);
shimDocument.createElementNS = (_ns, tag) => new ShimNode(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(id) || null;
shimDocument.contains = () => true;

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
  // rAF 用同步队列：测试里手动 flushAll()，避免依赖真实帧
  requestAnimationFrame(callback) { shimWindow.__rafQueue.push(callback); return 0; },
  __rafQueue: [],
};

globalThis.document = shimDocument;
globalThis.window = shimWindow;
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.__shim = { shimDocument, shimWindow, mediaListeners };

/** 注入 store（模拟 `Alpine.store("global")`）。 */
globalThis.__setStore = (patch) => {
  const base = {
    currentMode: 'cards',
    deviceType: 'desktop',
    isDarkMode: true,
    batchProgress: { status: 'idle', current: 0, total: 0 },
    indexStatus: { state: 'ready', scan_active: false },
  };
  globalThis.__store = Object.assign(base, patch || {});
  shimWindow.Alpine = {
    store: () => globalThis.__store,
    reactive: (value) => value,
  };
  return globalThis.__store;
};
globalThis.__setStore({});

globalThis.__flushRaf = () => {
  const queue = shimWindow.__rafQueue.splice(0);
  for (const callback of queue) callback();
};

globalThis.__setReducedMotion = (value) => {
  mediaMatches = Boolean(value);
  for (const entry of mediaListeners) {
    if (entry.type === 'change') entry.handler({ matches: mediaMatches });
  }
};
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    return run_node(DOM_SHIM + textwrap.dedent(body))


# ------------------------------------------------------------------ 静态契约


def test_on_state_is_exposed_on_host_namespace():
    source = read_source(HOST_PATH)

    assert 'onState(handler) {' in source
    assert 'hostStateBroadcaster.subscribe(handler)' in source
    assert 'own(unsubscribe)' in source, '取消订阅必须挂到插件 disposer'


def test_state_snapshot_field_names_are_read_from_real_state_module():
    """字段名必须来自 `state.js` 的真实字段，不能猜。"""
    source = read_source(HOST_PATH)
    state = read_source('static/js/state.js')

    # 快照读的是 store 上确实存在的字段
    for field in ('currentMode', 'deviceType', 'isDarkMode', 'batchProgress', 'indexStatus'):
        assert field in source, field
        assert field in state, f'{field} 不在 state.js 里——字段名猜错了'

    # busy 的判定复用既有状态，不新造一套
    assert 'batchProgress' in source and '"running"' in source
    assert 'indexStatus' in source and "'building'" in source.replace('"building"', "'building'")
    assert 'scan_active' in source


def test_reduced_motion_is_watched_not_read_once():
    """`reducedMotion` **必须**监 change：用户能在系统设置里改，不改页面就变。"""
    source = read_source(HOST_PATH)

    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in source
    assert 'addEventListener("change"' in source
    # 旧 Safari 的签名也要兜住
    assert 'addListener(onChange)' in source


def test_state_push_is_coalesced():
    """推送必须合并去抖：一次视图切换会让十几个字段变化，不能各推一次。"""
    source = read_source(HOST_PATH)

    assert 'schedule()' in source
    assert 'if (this.pending) return;' in source
    assert 'requestAnimationFrame(flush)' in source
    # 只在快照真的变了才推
    assert 'if (serialized === this.last) return;' in source


def test_subscribers_share_one_watcher():
    """多个插件的多个 handler 共用一遍监听与一次计算。"""
    source = read_source(HOST_PATH)

    assert 'installWatchers()' in source
    assert 'if (this.watchersInstalled) return;' in source
    assert 'this.listeners = new Set()' in source or 'listeners: new Set()' in source


def test_alpine_effect_bridges_multi_writer_fields():
    """`batchProgress` / `indexStatus` 有多个写入点，走响应式观察而非逐个补事件。"""
    source = read_source(HOST_PATH)
    registry = read_source('static/js/contributionRegistry.js')

    assert 'alpine.effect(' in source
    # 与 contributionRegistry 对 viewState.selectedIds 的既有判断同源（v3 顶替 entryRegistry）
    assert 'installAlpineWatcher' in source
    assert 'alpine:initialized' in source
    assert 'alpine.effect(' in registry


def test_host_exposes_shared_store_accessor():
    """`PluginHost.store` 与 `api.store` 必须是同一份取法（避免两处漂移）。"""
    source = read_source(HOST_PATH)

    assert 'get store() {' in source
    assert 'return host.store;' in source


# ------------------------------------------------------------------ 行为契约


@requires_node
def test_first_subscription_pushes_snapshot_immediately():
    """首次订阅**立即**推一次快照。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState((state) => seen.push(state));

        assert.equal(seen.length, 1, '首次订阅必须立即收到一次快照');
        const snap = seen[0];
        assert.equal(snap.mode, 'cards');
        assert.equal(snap.deviceType, 'desktop');
        assert.equal(snap.darkMode, true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_snapshot_has_the_documented_shape():
    """快照字段固定为文档里那 8 个。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        let snap = null;
        api.host.onState((state) => { snap = state; });

        assert.deepEqual(Object.keys(snap).sort(), [
          'busy', 'darkMode', 'deviceType', 'mode',
          'reducedMotion', 'scrimActive', 'surfaceOpen', 'visible',
        ].sort());
        assert.equal(typeof snap.busy, 'boolean');
        assert.equal(typeof snap.surfaceOpen, 'boolean');
        assert.equal(typeof snap.reducedMotion, 'boolean');
        assert.equal(typeof snap.visible, 'boolean');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_busy_follows_batch_progress():
    """`busy` 复用 `batchProgress.status`，不新造状态。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        globalThis.__setStore({ batchProgress: { status: 'running', current: 3, total: 9 } });
        let snap = null;
        api.host.onState((state) => { snap = state; });

        assert.equal(snap.busy, true, '批处理在跑时必须 busy');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_busy_follows_index_and_scan():
    """`busy` 也复盖索引构建与全量扫描。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});

        globalThis.__setStore({ indexStatus: { state: 'building', scan_active: false } });
        let snap = null;
        api.host.onState((state) => { snap = state; });
        assert.equal(snap.busy, true, '索引构建时必须 busy');

        globalThis.__setStore({ indexStatus: { state: 'ready', scan_active: true } });
        let scanSnap = null;
        const unsub = api.host.onState((state) => { scanSnap = state; });
        assert.equal(scanSnap.busy, true, '全量扫描时必须 busy');
    """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_idle_state_is_not_busy():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        let snap = null;
        api.host.onState((state) => { snap = state; });
        assert.equal(snap.busy, false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_changes_are_pushed_and_coalesced():
    """变化推送，且一轮里多个字段变化合并成**一次**推送。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState((state) => seen.push(state.mode));
        assert.equal(seen.length, 1, '首次立即推一次');

        // 两个字段同时变（模拟一次视图切换）
        globalThis.__store.currentMode = 'worldinfo';
        globalThis.__store.isDarkMode = false;
        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));

        // 去抖期间还没推
        assert.equal(seen.length, 1, '未 flush 前不得推送（rAF 合并）');
        globalThis.__flushRaf();
        assert.equal(seen.length, 2, '一帧只推一次（多个字段合并）');
        assert.equal(seen[1], 'worldinfo');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_unchanged_snapshot_is_not_pushed():
    """快照没变就不推（避免插件做无谓重建）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState((state) => seen.push(state));

        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));
        globalThis.__flushRaf();

        assert.equal(seen.length, 1, '快照未变时不得重复推送');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_reduced_motion_change_is_pushed():
    """`reducedMotion` 变化的推送（只读一次就永远停在初始值）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState((state) => seen.push(state.reducedMotion));
        assert.equal(seen[0], false);

        globalThis.__setReducedMotion(true);
        globalThis.__flushRaf();

        assert.equal(seen.length, 2, '系统设置改变必须推送');
        assert.equal(seen[1], true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_unsubscribe_stops_delivery():
    """取消订阅后不再收到推送。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        const unsubscribe = api.host.onState((state) => seen.push(state));
        assert.equal(seen.length, 1);

        unsubscribe();
        globalThis.__store.currentMode = 'chats';
        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));
        globalThis.__flushRaf();

        assert.equal(seen.length, 1, '取消订阅后不得再推送');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_handler_exception_does_not_break_other_subscribers():
    """一个插件抛错不影响其他订阅者。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState(() => { throw new Error('boom'); });
        api.host.onState((state) => seen.push(state));

        globalThis.__store.currentMode = 'presets';
        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));
        globalThis.__flushRaf();

        assert.equal(seen.length, 2, '正常订阅者必须照常收到推送');
        assert.equal(seen[1].mode, 'presets');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_state_is_released_on_plugin_destroy():
    """插件销毁后其状态订阅一并摘除（不残留回调）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const seen = [];
        api.host.onState((state) => seen.push(state));
        assert.equal(seen.length, 1);

        PluginHost.destroy('demo-plugin');

        globalThis.__store.currentMode = 'chats';
        globalThis.window.dispatchEvent(new CustomEvent('mode-changed'));
        globalThis.__flushRaf();

        assert.equal(seen.length, 1, '插件销毁后不得再收到推送');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_surface_open_flag_follows_dialog_surfaces():
    """`surfaceOpen` 跟随对话框型 surface 的开合（常驻图层不算）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginHost.init();
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});

        PluginSurfaceHost.register('demo-plugin', 'pet', { type: 'ambient', mount() {} });
        let snap = null;
        api.host.onState((state) => { snap = state; });
        assert.equal(snap.surfaceOpen, false, 'ambient 不是对话框，不算 surfaceOpen');

        PluginSurfaceHost.register('demo-plugin', 'panel', { type: 'panel', mount() {} });
        PluginSurfaceHost.openSurface('demo-plugin:panel', {});
        assert.equal(PluginSurfaceHost.hasOpenSurface(), true);

        const after = [];
        api.host.onState((state) => after.push(state.surfaceOpen));
        assert.equal(after[0], true, '对话框打开时 surfaceOpen 必须为 true');

        PluginSurfaceHost.close('demo-plugin:panel');
        globalThis.__flushRaf();
        assert.equal(after[after.length - 1], false, '关闭后必须回到 false');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_scrim_flag_is_reported():
    """`scrimActive` 上报全屏遮罩活跃态。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';
        import { setFullscreenScrim } from './static/js/utils/dom.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        let snap = null;
        api.host.onState((state) => { snap = state; });
        assert.equal(snap.scrimActive, false);

        setFullscreenScrim(true, 'demo-plugin:overlay');
        let next = null;
        api.host.onState((state) => { next = state; });
        assert.equal(next.scrimActive, true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_visibility_is_reported():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        globalThis.document.visibilityState = 'hidden';
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        let snap = null;
        api.host.onState((state) => { snap = state; });
        assert.equal(snap.visible, false, '页面隐藏时必须上报 visible=false');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_non_function_handler_is_ignored():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        const unsubscribe = api.host.onState(null);
        assert.equal(typeof unsubscribe, 'function');
        unsubscribe();
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


# ------------------------------------------------------------------ 选中集 / 世界书来源


@requires_node
def test_host_selection_reads_view_state():
    """`api.host.selection()` 返回 `{mode, ids}`，且 id 规范成非空字符串。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        __setStore({ currentMode: 'worldinfo', viewState: { selectedIds: [1, '', 'a', null] } });
        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});
        assert.deepEqual(api.host.selection(), { mode: 'worldinfo', ids: ['1', 'a'] });

        // 没有选中集时是空数组，不是 undefined（插件可以无条件读）
        __setStore({ currentMode: 'cards', viewState: {} });
        assert.deepEqual(api.host.selection(), { mode: 'cards', ids: [] });
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_worldbook_sources_filters_by_category_and_source_type():
    """`api.worldbook.sources()` 按**路径段**过滤分类，不会把 `科幻短片` 算进 `科幻`。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        __setStore({ wiList: [
          { source_type: 'global', path: '/wi/a.json', display_category: '科幻',
            name: 'A', owner_card_id: '', entry_count: 3 },
          { source_type: 'global', path: '/wi/b.json', display_category: '科幻/太空',
            name: 'B', owner_card_id: '', entry_count: 5 },
          { source_type: 'global', path: '/wi/c.json', display_category: '科幻短片',
            name: 'C', owner_card_id: '', entry_count: 7 },
          { source_type: 'embedded', path: '', display_category: '科幻',
            name: 'D', owner_card_id: 'card-1' },
        ] });

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});

        // 全部：字段规范化
        const all = api.worldbook.sources();
        assert.equal(all.length, 4);
        assert.deepEqual(all[0], {
          source_type: 'global', file_path: '/wi/a.json', card_id: '',
          category: '科幻', name: 'A', entry_count: 3,
        });
        // 缺 entry_count 时归 0，不是 NaN
        assert.equal(all[3].entry_count, 0);
        assert.equal(all[3].card_id, 'card-1');

        // 分类过滤：含子分类，但 `科幻短片` 不算（按路径段匹配）
        const scoped = api.worldbook.sources({ category: '科幻' });
        assert.deepEqual(scoped.map((item) => item.name), ['A', 'B', 'D']);

        // 来源类型过滤
        const embedded = api.worldbook.sources({ category: '科幻', sourceType: 'embedded' });
        assert.deepEqual(embedded.map((item) => item.name), ['D']);

        // 空列表时返回空数组
        __setStore({ wiList: [] });
        assert.deepEqual(api.worldbook.sources(), []);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_jobs_review_batch_counts_both_failure_modes():
    """`reviewBatch` 的 `failed` 必须同时算上「抛错」与「端点返回 success:false」。

    只数 `rejected` 会让端点返回 `{success: false}` 时 `failed` 恒为 0，
    用户看到「0 条失败」却一条也没审批成功。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginHost } from './static/js/pluginHost.js';

        const api = PluginHost.buildApi({ id: 'demo-plugin', manifest: {} }, {});

        const calls = [];
        api.api = async (path, options = {}) => {
          calls.push(path);
          if (path.includes('boom')) throw new Error('网络炸了');
          if (path.includes('nope')) return { success: false };
          return { success: true };
        };

        const out = await api.jobs.reviewBatch('run-1', [
          { key: 'ok', status: 'done' },
          { key: 'nope', status: 'done' },
          { key: 'boom', status: 'done' },
        ]);

        assert.deepEqual(out, { total: 3, failed: 2 });
        assert.equal(calls.length, 3, '单条失败不得中断其余条目');
        assert.ok(calls[0].endsWith('/jobs/run-1/items/ok/review'), calls[0]);

        // 单条 review 的返回值：以 data.success 判定，不抛错
        assert.equal(await api.jobs.review('run-1', 'ok', 'done'), true);
        assert.equal(await api.jobs.review('run-1', 'nope', 'done'), false);

        // 非数组入参退化为空批次
        assert.deepEqual(await api.jobs.reviewBatch('run-1', null), { total: 0, failed: 0 });
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
