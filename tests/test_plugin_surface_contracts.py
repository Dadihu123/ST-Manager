"""宿主表面（surface）契约测试（设计文档 D8 的 `mount(container, ctx)` 契约）。

仓库没有 JS 测试运行器，也没有 DOM 库（且本次不引入新依赖）。因此这里自带一个
**最小 DOM 垫片**：只实现 `pluginSurfaceHost.js` 真正用到的那几个 API，从而能
在 Node 里真实驱动 register/open/close，而不是只做源码字符串断言。

覆盖的契约：
- `mount(container, ctx)` 收到的是宿主提供的容器
- `mount` 返回函数时，关闭时被调用（D8）
- 插件停用时宿主**强制**卸载 surface（不依赖插件 deactivate）
- 容器带 `data-plugin` 与 `data-marquee-ignore`
- `mount` 抛错时错误被隔离，不影响其他插件与宿主
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

SURFACE_HOST_PATH = 'static/js/pluginSurfaceHost.js'
SURFACE_CSS_PATH = 'static/css/modules/plugin-surfaces.css'
PRIMITIVES_CSS_PATH = 'static/css/modules/ui-primitives.css'


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
    reason='Node.js is required for surface contract checks',
)


# ------------------------------------------------------------------ DOM 垫片

#: 覆盖 `pluginSurfaceHost.js` 用到的 DOM 子集。
DOM_SHIM = r"""
// ---- 最小 DOM 垫片（仅覆盖 surface host 用到的 API） ----
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
    for (const handler of this.listeners[type] || []) handler(event);
  }
  focus() { globalThis.document.activeElement = this; }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains && child.contains(node));
  }
  querySelectorAll(selector) {
    // 只支持逗号分隔的简单选择器集合（够用即可）
    const parts = String(selector).split(',').map((item) => item.trim()).filter(Boolean);
    const matches = (node) => parts.some((part) => {
      if (part.startsWith('.')) return node.classList.contains(part.slice(1));
      if (part.includes('[')) {
        const name = part.slice(part.indexOf('[') + 1, part.indexOf(']')).split('=')[0];
        return node.hasAttribute(name);
      }
      if (part === 'button') return node.tagName === 'BUTTON';
      if (part === 'input') return node.tagName === 'INPUT';
      if (part === 'select') return node.tagName === 'SELECT';
      if (part === 'textarea') return node.tagName === 'TEXTAREA';
      if (part === 'a') return node.tagName === 'A';
      return false;
    });
    const found = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (matches(child)) found.push(child);
        walk(child);
      }
    };
    walk(this);
    return found;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  get innerHTML() { return ''; }
  set innerHTML(_value) { this.children = []; }
}

const shimDocument = new ShimNode('#document');
shimDocument.body = new ShimNode('body');
shimDocument.documentElement = new ShimNode('html');
shimDocument.activeElement = null;
shimDocument._byId = new Map();
shimDocument.createElement = (tag) => new ShimNode(tag);
shimDocument.createElementNS = (_ns, tag) => new ShimNode(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(id) || null;
shimDocument.contains = (node) => shimDocument.body.contains(node);
shimDocument._register = (node) => { if (node.id) shimDocument._byId.set(node.id, node); };

// appendChild 时登记 id，模拟真实 DOM 的 getElementById
const originalAppend = ShimNode.prototype.appendChild;
ShimNode.prototype.appendChild = function (child) {
  const result = originalAppend.call(this, child);
  if (child && child.id) shimDocument._byId.set(child.id, child);
  return result;
};

globalThis.document = shimDocument;
globalThis.window = {
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {},
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.__shim = { ShimNode, document: shimDocument };
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    """在 DOM 垫片之上运行一段测试脚本。"""
    return run_node(DOM_SHIM + textwrap.dedent(body))


# ------------------------------------------------------------------ 静态契约


def test_surface_host_module_exists():
    source = read_source(SURFACE_HOST_PATH)

    for fragment in (
        'export const PluginSurfaceHost',
        'export const SURFACE_TYPES = ["panel", "modal", "page", "sheet"]',
        'register(pluginId, surfaceId, spec)',
        'openSurface(key, ctx = {})',
        'close(key)',
        'isOpen(key)',
        'closePlugin(pluginId)',
        'unregisterPlugin(pluginId)',
    ):
        assert fragment in source, fragment


def test_surface_types_match_backend_contract():
    from core.plugins.entries import SURFACE_TYPES

    source = read_source(SURFACE_HOST_PATH)
    assert 'SURFACE_TYPES = ["panel", "modal", "page", "sheet"]' in source
    assert set(SURFACE_TYPES) == {'panel', 'modal', 'page', 'sheet'}


def test_surface_host_avoids_backdrop_filter():
    """陷阱 #8：宿主浮层绝不能用 `backdrop-filter`（Chromium 会画黑块）。

    注释里提到该属性是允许的（那正是要记录的坑），因此只看**声明**。
    """
    import re

    for path in (SURFACE_CSS_PATH, PRIMITIVES_CSS_PATH):
        # 去掉注释后再查，避免把解释性文字当成真实声明
        css = re.sub(r'/\*.*?\*/', '', read_source(path), flags=re.S)
        assert 'backdrop-filter' not in css, path


def test_surface_css_uses_z_index_tokens():
    """层级必须走令牌，不写字面量（便于统一调整与排查层叠问题）。"""
    css = read_source(SURFACE_CSS_PATH)

    assert 'var(--z-surface)' in css
    assert 'var(--z-modal-popover)' in css
    # 不允许裸数字 z-index
    import re

    literals = re.findall(r'z-index:\s*(\d+)', css)
    assert literals == [], f'表面样式出现 z-index 字面量: {literals}'


def test_surface_css_has_no_hardcoded_hex_colors():
    import re

    css = read_source(SURFACE_CSS_PATH)
    assert not re.search(r'#[0-9a-fA-F]{6}\b', css), '表面样式不应写死十六进制颜色'


def test_plugin_stylesheets_are_registered_in_entry_css():
    entry = read_source('static/css/style.css')

    assert 'modules/ui-primitives.css' in entry
    assert 'modules/plugin-surfaces.css' in entry


def test_primitive_css_respects_reduced_motion():
    css = read_source(PRIMITIVES_CSS_PATH)

    assert 'prefers-reduced-motion' in css


def test_primitive_css_avoids_palette_utilities():
    import re

    css = read_source(PRIMITIVES_CSS_PATH)

    for pattern in (r'\bbg-(red|blue|green|purple)-\d', r'\btext-(red|blue|green|purple)-\d'):
        assert not re.search(pattern, css), pattern


# ------------------------------------------------------------------ 行为契约


@requires_node
def test_register_and_open_mounts_into_host_container():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let received = null;
        let ctxSeen = null;
        PluginSurfaceHost.register('demo-plugin', 'main', {
          title: '演示面板',
          mount(container, ctx) {
            received = container;
            ctxSeen = ctx;
          },
        });

        const container = PluginSurfaceHost.openSurface('demo-plugin:main', {
          source: 'dock',
          targetId: 'card-1',
          mode: 'cards',
        });

        assert.ok(container, 'openSurface 必须返回容器');
        assert.equal(received, container, 'mount 收到的必须是宿主返回的同一个容器');
        assert.equal(ctxSeen.pluginId, 'demo-plugin');
        assert.equal(ctxSeen.surfaceId, 'main');
        assert.equal(ctxSeen.source, 'dock');
        assert.equal(ctxSeen.targetId, 'card-1');
        assert.equal(ctxSeen.mode, 'cards');

        // 容器带 data-plugin（F12）与 data-marquee-ignore（框选不命中）
        assert.equal(container.parentNode.dataset.plugin, 'demo-plugin');
        assert.equal(container.parentNode.dataset.marqueeIgnore, 'true');
        assert.equal(container.parentNode.dataset.surface, 'main');
        assert.equal(container.parentNode.getAttribute('role'), 'dialog');
        assert.equal(container.parentNode.getAttribute('aria-modal'), 'true');

        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:main'), true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_mount_returned_disposer_runs_on_close():
    """D8：`mount` 返回函数时，宿主在关闭时调用它。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        const calls = [];
        PluginSurfaceHost.register('demo-plugin', 'main', {
          mount() { calls.push('mount'); return () => calls.push('disposer'); },
          unmount() { calls.push('unmount'); },
          onOpen() { calls.push('onOpen'); },
          onClose() { calls.push('onClose'); },
        });

        PluginSurfaceHost.openSurface('demo-plugin:main');
        assert.deepEqual(calls, ['mount', 'onOpen']);

        PluginSurfaceHost.close('demo-plugin:main');
        // 顺序：disposer → unmount → onClose
        assert.deepEqual(calls, ['mount', 'onOpen', 'disposer', 'unmount', 'onClose']);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:main'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_mount_error_is_isolated_to_the_failing_surface():
    """`mount` 抛错时必须销毁该 surface，且不影响其他插件与宿主。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        const errors = [];
        globalThis.window.dispatchEvent = (event) => {
          if (event && event.type === 'plugin:surface-error') errors.push(event.detail);
        };

        PluginSurfaceHost.register('broken-plugin', 'boom', {
          mount() { throw new Error('插件内部炸了'); },
        });
        PluginSurfaceHost.register('healthy-plugin', 'fine', {
          mount(container) { container.textContent = 'ok'; },
        });

        const failed = PluginSurfaceHost.openSurface('broken-plugin:boom');
        assert.equal(failed, null, 'mount 抛错时 openSurface 必须返回 null');
        assert.equal(PluginSurfaceHost.isOpen('broken-plugin:boom'), false);
        assert.equal(errors.length, 1);
        assert.equal(errors[0].pluginId, 'broken-plugin');

        // 宿主与其他插件仍然可用
        const ok = PluginSurfaceHost.openSurface('healthy-plugin:fine');
        assert.ok(ok, '健康插件不受影响');
        assert.equal(PluginSurfaceHost.isOpen('healthy-plugin:fine'), true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_mount_error_marks_the_entry_as_error():
    """设计文档 8.3：`mount()` 抛错时「把对应入口置错误态」。

    用户要能看见「这个插件的面板坏了」，而不是点了没反应。入口 id 从
    `ctx.targetId` 取（坞 / 命令面板都会传）。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';
        import { EntryRegistry } from './static/js/entryRegistry.js';

        EntryRegistry.setPlugins([
          { id: 'broken-plugin', enabled: true, manifest: { entries: [
            { id: 'workbench', kind: 'dock', label: '工作台' },
          ] } },
        ]);

        PluginSurfaceHost.register('broken-plugin', 'workbench', {
          mount() { throw new Error('插件内部炸了'); },
        });

        const failed = PluginSurfaceHost.openSurface('broken-plugin:workbench', {
          source: 'dock',
          targetId: 'workbench',
        });
        assert.equal(failed, null);

        const entry = EntryRegistry.get('broken-plugin:workbench');
        assert.ok(entry, '入口应仍在注册表里');
        assert.equal(entry.status, 'error', '入口必须被置为 error 态');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_disabling_plugin_force_unloads_all_its_surfaces():
    """D8 契约：宿主必须在插件被禁用/卸载时强制卸载 surface，不依赖 deactivate。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        const closed = [];
        for (const id of ['a', 'b']) {
          PluginSurfaceHost.register('demo-plugin', id, {
            mount() { return () => closed.push(id); },
          });
        }
        PluginSurfaceHost.register('other-plugin', 'c', { mount() {} });

        PluginSurfaceHost.openSurface('demo-plugin:a');
        PluginSurfaceHost.openSurface('demo-plugin:b');
        PluginSurfaceHost.openSurface('other-plugin:c');

        // 插件的 deactivate 完全没有被调用（这里根本没有 deactivate）
        const removed = PluginSurfaceHost.unregisterPlugin('demo-plugin');

        assert.equal(removed, 2, '两个 surface 定义都被注销');
        assert.deepEqual(closed.sort(), ['a', 'b'], '两个 disposer 都被执行');
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:a'), false);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:b'), false);
        // 其他插件不受影响
        assert.equal(PluginSurfaceHost.isOpen('other-plugin:c'), true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_close_plugin_only_affects_that_plugin():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'a', { mount() {} });
        PluginSurfaceHost.register('other-plugin', 'b', { mount() {} });
        PluginSurfaceHost.openSurface('demo-plugin:a');
        PluginSurfaceHost.openSurface('other-plugin:b');

        assert.equal(PluginSurfaceHost.closePlugin('demo-plugin'), 1);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:a'), false);
        assert.equal(PluginSurfaceHost.isOpen('other-plugin:b'), true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_unmount_error_does_not_block_container_teardown():
    """插件的 unmount 抛错时容器仍必须被回收（不能让坏插件挂住 DOM）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'a', {
          mount() {},
          unmount() { throw new Error('unmount 炸了'); },
          onClose() { throw new Error('onClose 也炸了'); },
        });
        PluginSurfaceHost.openSurface('demo-plugin:a');
        const shell = PluginSurfaceHost.open.get('demo-plugin:a').shell;

        assert.equal(PluginSurfaceHost.close('demo-plugin:a'), true);
        assert.equal(shell.parentNode, null, '容器必须被摘除');
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:a'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_surface_type_selects_the_right_container_class():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        for (const type of ['panel', 'modal', 'page', 'sheet']) {
          PluginSurfaceHost.register('demo-plugin', type, { mount() {}, type });
          PluginSurfaceHost.openSurface(`demo-plugin:${type}`);
          const shell = PluginSurfaceHost.open.get(`demo-plugin:${type}`).shell;
          assert.ok(
            shell.classList.contains(`plugin-surface--${type}`),
            `${type} 应使用对应容器类`,
          );
          assert.equal(shell.dataset.surfaceType, type);
        }

        // 非法 type 回退 panel
        PluginSurfaceHost.register('demo-plugin', 'bogus', { mount() {}, type: 'nonsense' });
        PluginSurfaceHost.openSurface('demo-plugin:bogus');
        const shell = PluginSurfaceHost.open.get('demo-plugin:bogus').shell;
        assert.ok(shell.classList.contains('plugin-surface--panel'));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_opening_same_surface_twice_reuses_the_container():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let mounts = 0;
        PluginSurfaceHost.register('demo-plugin', 'a', { mount() { mounts += 1; } });

        const first = PluginSurfaceHost.openSurface('demo-plugin:a');
        const second = PluginSurfaceHost.openSurface('demo-plugin:a');

        assert.equal(first, second, '重复 open 必须复用容器而不是再挂一次');
        assert.equal(mounts, 1);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_invalid_registration_is_rejected_without_throwing():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        // 缺 mount
        assert.equal(PluginSurfaceHost.register('demo-plugin', 'a', {}), '');
        // 缺 id
        assert.equal(PluginSurfaceHost.register('demo-plugin', '', { mount() {} }), '');
        assert.equal(PluginSurfaceHost.surfaces.size, 0);

        // 打开未注册的 surface 返回 null 而不是抛错
        assert.equal(PluginSurfaceHost.openSurface('demo-plugin:nope'), null);
        // 关闭未打开的 surface 返回 false
        assert.equal(PluginSurfaceHost.close('demo-plugin:nope'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_escape_key_closes_the_active_surface():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.init();
        PluginSurfaceHost.register('demo-plugin', 'a', { mount() {} });
        PluginSurfaceHost.openSurface('demo-plugin:a');
        assert.equal(PluginSurfaceHost.activeKey, 'demo-plugin:a');

        let prevented = false;
        document.dispatch('keydown', {
          key: 'Escape',
          preventDefault() { prevented = true; },
          stopPropagation() {},
        });

        assert.equal(prevented, true);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:a'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
