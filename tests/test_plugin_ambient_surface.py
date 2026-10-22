"""环境层（ambient）surface 契约测试。

`ambient` 是**常驻型** surface：注册即挂载、非模态、不抢焦点、忽略 ESC、
不参与遮罩记账、不渲染头部与关闭按钮。它与 `panel` / `modal` / `page` / `sheet`
的差异是**每一项都相反**，因此这里的断言大多是「与对话框语义相反」的形式。

与 `test_plugin_surface_contracts.py` 相同的做法：仓库没有 JS 测试运行器，也不引入
新依赖，因此自带一个**最小 DOM 垫片**，在 Node 里真实驱动 register/open/close，
而不是只做源码字符串断言。

覆盖的契约：
- 注册即挂载（不调 `openSurface` 也有 DOM）
- **无 `role="dialog"`**、**不抢焦点**
- **ESC 不关闭它**
- 不调 `setFullscreenScrim`（`document.body` 无 `has-fullscreen-scrim`）
- 容器带 `data-marquee-ignore`
- 重复 `register` 同 id 的行为（覆盖既有记录）
- `unregisterPlugin` / `closePlugin` 后 DOM 干净
- 移动端不挂载
- `is-host-occluded` 在 surface 打开时被加上、关闭时被摘掉
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
VARIABLES_CSS_PATH = 'static/css/modules/variables.css'
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
    reason='Node.js is required for ambient surface contract checks',
)


# ------------------------------------------------------------------ DOM 垫片

#: 覆盖 `pluginSurfaceHost.js` 与 `utils/dom.js` 用到的 DOM 子集。
#: 比 `test_plugin_surface_contracts.py` 的垫片多出：`visibilityState`、
#: `document.addEventListener` / `dispatch`（ESC 与 visibilitychange 用例需要）、
#: 以及 `window` 上的事件派发（`host:fullscreen-scrim-changed` 需要）。
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
  focus() { globalThis.document.activeElement = this; }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains && child.contains(node));
  }
  querySelectorAll(selector) {
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
      if (/^[a-zA-Z][a-zA-Z0-9-]*$/.test(part)) {
        return node.tagName === part.toUpperCase();
      }
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
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get firstChild() { return this.children[0] || null; }
  get innerHTML() { return ''; }
  set innerHTML(_value) { this.children = []; }
}

const shimDocument = new ShimNode('#document');
shimDocument.body = new ShimNode('body');
shimDocument.documentElement = new ShimNode('html');
shimDocument.activeElement = null;
shimDocument.visibilityState = 'visible';
shimDocument._byId = new Map();
shimDocument.createElement = (tag) => new ShimNode(tag);
shimDocument.createElementNS = (_ns, tag) => new ShimNode(tag);
shimDocument.getElementById = (id) => shimDocument._byId.get(id) || null;
shimDocument.contains = (node) => shimDocument.body.contains(node);
shimDocument._register = (node) => { if (node.id) shimDocument._byId.set(node.id, node); };

const originalAppend = ShimNode.prototype.appendChild;
ShimNode.prototype.appendChild = function (child) {
  const result = originalAppend.call(this, child);
  if (child && child.id) shimDocument._byId.set(child.id, child);
  return result;
};

const windowListeners = {};
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
};

globalThis.document = shimDocument;
globalThis.window = shimWindow;
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.__shim = { ShimNode, document: shimDocument, windowListeners, window: shimWindow };

/** 把 store 垫进 Alpine，让 deviceType / 其它宿主状态可被读取。 */
globalThis.__setStore = (patch) => {
  globalThis.window.Alpine = {
    store() { return Object.assign({ deviceType: 'desktop' }, patch || {}); },
  };
};
globalThis.__setStore({});
"""


def run_dom_script(body: str) -> subprocess.CompletedProcess:
    """在 DOM 垫片之上运行一段测试脚本。"""
    return run_node(DOM_SHIM + textwrap.dedent(body))


# ------------------------------------------------------------------ 静态契约


def test_ambient_is_a_registered_surface_type():
    """v3 起 surface 类型只由 `PluginSurfaceHost.SURFACE_TYPES` 定义（运行期注册）。"""
    host = read_source(SURFACE_HOST_PATH)
    registry = read_source(REGISTRY_PATH)

    expected = 'SURFACE_TYPES = ["panel", "modal", "page", "sheet", "ambient"]'
    assert expected in host
    # 注册表不再定义第二份 SURFACE_TYPES（v2 的双份同步问题随 entries 契约删除）
    assert 'SURFACE_TYPES' not in registry


def test_host_features_expose_ambient_and_pixel_ratio():
    """`hostFeatures()` 是 `when.feature` 的取值来源，须产出 ambient 门控。"""
    source = read_source(REGISTRY_PATH)

    assert 'features.push("hasAmbient")' in source
    assert 'features.push("hasPixelRatio")' in source
    # ambient 仅在非移动端为真
    assert 'isMobileDevice' in source


def test_ambient_css_uses_layer_token_and_stays_transparent():
    """层级走 `--z-ambient`，且不写字面量、不带背景/边框/阴影。"""
    import re

    css = read_source(SURFACE_CSS_PATH)
    stripped = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    assert 'var(--z-ambient)' in stripped
    literals = re.findall(r'z-index:\s*(\d+)', stripped)
    assert literals == [], f'表面样式出现 z-index 字面量: {literals}'
    assert 'backdrop-filter' not in stripped

    # 环境层是全屏透明层且指针穿透
    ambient_block = stripped[stripped.index('.plugin-surface--ambient'):]
    assert 'position: fixed' in ambient_block
    assert 'pointer-events: none' in ambient_block
    assert 'inset: 0' in ambient_block


def test_ambient_layer_token_sits_between_card_selected_and_surface():
    """`--z-ambient` 必须严格夹在卡片选中态与 surface 之间（唯一的空档）。"""
    import re

    css = read_source(VARIABLES_CSS_PATH)
    stripped = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    def token(name):
        match = re.search(rf'--{name}:\s*(\d+)', stripped)
        assert match, name
        return int(match.group(1))

    assert token('z-card-selected') < token('z-ambient') < token('z-surface')
    assert '.z-ambient' in stripped


def test_ambient_css_documents_pointer_events_inheritance_trap():
    """`pointer-events` 是继承属性——必须写明子元素要自行取回 auto。

    不写的话插件作者会踩「点了没反应」，而这是入口坞已经踩过一次的坑。
    """
    css = read_source(SURFACE_CSS_PATH)
    assert 'pointer-events: auto' in css or 'pointer-events:auto' in css


def test_ambient_css_respects_reduced_motion():
    css = read_source(SURFACE_CSS_PATH)
    assert 'prefers-reduced-motion' in css


# ------------------------------------------------------------------ 行为契约


@requires_node
def test_ambient_mounts_on_register_without_open():
    """核心语义：**注册即挂载**，不需要任何 open 调用。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let mounted = false;
        let container = null;
        const key = PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount(c) { mounted = true; container = c; },
        });

        assert.equal(key, 'demo-plugin:pet');
        assert.equal(mounted, true, '注册时必须已经 mount（无 open 动作）');

        // 容器在文档里，且带宿主约定的标记
        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.ok(root, '必须挂到宿主 surface 根容器');
        const shell = container.parentNode;
        assert.equal(shell.dataset.plugin, 'demo-plugin');
        assert.equal(shell.dataset.surface, 'pet');
        assert.equal(shell.dataset.surfaceType, 'ambient');
        assert.equal(shell.dataset.marqueeIgnore, 'true', '框选不得命中常驻图层');
        assert.ok(shell.classList.contains('plugin-surface--ambient'));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_has_no_dialog_semantics_and_does_not_steal_focus():
    """常驻图层不是对话框：无 role/aria-modal，且**完全不碰焦点**。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        // 先让用户焦点停在一个真实控件上（模拟「用户正在输入」）
        const outside = globalThis.document.createElement('input');
        globalThis.document.body.appendChild(outside);
        outside.focus();
        const before = globalThis.document.activeElement;
        assert.equal(before, outside);

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount(container) {
            // 插件放一个可交互子元素
            const btn = globalThis.document.createElement('button');
            btn.className = 'pet-btn';
            container.appendChild(btn);
          },
        });

        const shell = PluginSurfaceHost.surfaces.get('demo-plugin:pet')
          && globalThis.document.getElementById('plugin-surface-root').firstChild;
        assert.ok(shell, '容器必须已挂载');
        assert.equal(shell.getAttribute('role'), null, '常驻图层不得设 role="dialog"');
        assert.equal(shell.getAttribute('aria-modal'), null, '常驻图层不是模态');

        // 焦点纹丝不动（既没被抢到容器里，也没被拿去聚焦内部按钮）
        assert.equal(
          globalThis.document.activeElement, outside,
          'ambient 挂载不得改变 activeElement',
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_ignores_escape():
    """ESC 关闭对话框型 surface，但对常驻图层必须**无效**。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.init();
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });

        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:pet'), true);

        // 派发一次 ESC（宿主在 document 上装了 keydown 监听）
        globalThis.document.dispatch('keydown', {
          key: 'Escape',
          preventDefault() {},
          stopPropagation() {},
        });

        assert.equal(
          PluginSurfaceHost.isOpen('demo-plugin:pet'), true,
          'ESC 不得关闭常驻图层',
        );
        assert.ok(
          globalThis.document.getElementById('plugin-surface-root').firstChild,
          'ESC 后 DOM 仍应在',
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_does_not_register_fullscreen_scrim():
    """常驻图层不参与遮罩记账——否则会给页面壳永久加上遮罩类。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });

        assert.equal(
          globalThis.document.body.classList.contains('has-fullscreen-scrim'), false,
          'ambient 不得声明 fullscreen scrim',
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_mount_failure_is_isolated():
    """`mount` 抛错时容器被回收，不影响其他插件与宿主。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('broken-plugin', 'pet', {
          type: 'ambient',
          mount() { throw new Error('boom'); },
        });

        assert.equal(
          PluginSurfaceHost.isOpen('broken-plugin:pet'), false,
          '挂载失败后不得留在 open 表里',
        );
        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.equal(
          (root ? root.children.length : 0), 0,
          '挂载失败必须回收 DOM，不留半成品',
        );

        // 别的插件不受影响
        PluginSurfaceHost.register('good-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        assert.equal(PluginSurfaceHost.isOpen('good-plugin:pet'), true);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_close_plugin_leaves_nothing_on_screen():
    """禁用一个带 ambient 的插件后，屏幕上**立刻**什么都不剩。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:pet'), true);

        const closed = PluginSurfaceHost.closePlugin('demo-plugin');
        assert.equal(closed, 1);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:pet'), false);

        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.equal(
          (root ? root.children.length : 0), 0,
          'closePlugin 后 DOM 必须干净',
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_unregister_plugin_removes_definition_and_dom():
    """`unregisterPlugin` 同时注销定义与卸载 DOM。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });

        const removed = PluginSurfaceHost.unregisterPlugin('demo-plugin');
        assert.equal(removed, 1, '必须注销 surface 定义');
        assert.equal(PluginSurfaceHost.has('demo-plugin:pet'), false);
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:pet'), false);

        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.equal((root ? root.children.length : 0), 0);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_disposer_runs_on_close():
    """`mount` 返回的 disposer 在回收时必须被调用（不依赖插件 deactivate）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let disposed = false;
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() { return () => { disposed = true; }; },
        });

        assert.equal(disposed, false, '挂载时不得立刻调用 disposer');
        PluginSurfaceHost.closePlugin('demo-plugin');
        assert.equal(disposed, true, '回收时必须调用 disposer');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_onclose_runs_on_teardown():
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let closedCount = 0;
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
          onClose() { closedCount += 1; },
        });

        PluginSurfaceHost.closePlugin('demo-plugin');
        assert.equal(closedCount, 1);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_registering_same_ambient_id_twice_is_idempotent():
    """重复 `register` 同 id：覆盖既有记录，**不**叠加第二份 DOM。

    语义选择为「覆盖」而不是「拒绝」——与 `surfaces` 表的 Map 语义一致，
    也让插件热重载时不会越堆越多。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let secondMounted = false;
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() { secondMounted = true; },
        });

        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.equal(
          root.children.length, 1,
          '重复注册同一 id 不得叠加第二份常驻图层',
        );
        assert.equal(
          secondMounted, false,
          '已有挂载时重复 register 只覆盖记录，不重复 mount（否则插件会重建两套 DOM）',
        );
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_not_mounted_on_mobile():
    """移动端不挂载常驻图层（屏幕小，遮挡内容且没有「挪开」手段）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        globalThis.__setStore({ deviceType: 'mobile' });

        const { PluginSurfaceHost } = await import('./static/js/pluginSurfaceHost.js');

        let mounted = false;
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() { mounted = true; },
        });

        assert.equal(mounted, false, '移动端不得挂载 ambient');
        assert.equal(PluginSurfaceHost.isOpen('demo-plugin:pet'), false);
        const root = globalThis.document.getElementById('plugin-surface-root');
        assert.equal((root ? root.children.length : 0), 0);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_open_returns_container_without_dialog_chrome():
    """对 ambient 调 `openSurface` 是安全的空操作：只回容器，不建对话框骨架。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let mountCount = 0;
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() { mountCount += 1; },
        });

        const container = PluginSurfaceHost.openSurface('demo-plugin:pet', { source: 'dock' });
        assert.ok(container, '必须返回容器');
        assert.equal(mountCount, 1, '不得重复 mount');

        const shell = container.parentNode;
        assert.equal(shell.querySelectorAll('.plugin-surface__header').length, 0,
          '常驻图层不得渲染头部');
        assert.equal(shell.querySelectorAll('.plugin-surface__close').length, 0,
          '常驻图层不得渲染关闭按钮');
        assert.equal(shell.getAttribute('role'), null);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_occlusion_toggles_with_dialog_surface():
    """宿主统一触发降级：打开对话框型 surface → 加 `is-host-occluded`；关闭 → 摘掉。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        const ambientShell = PluginSurfaceHost.open.get('demo-plugin:pet').shell;
        assert.equal(ambientShell.classList.contains('is-host-occluded'), false,
          '初始（无对话框）不得被标记为遮挡');

        // 打开一个 panel
        PluginSurfaceHost.register('demo-plugin', 'panel', {
          type: 'panel',
          title: '面板',
          mount() {},
        });
        PluginSurfaceHost.openSurface('demo-plugin:panel', {});
        assert.equal(ambientShell.classList.contains('is-host-occluded'), true,
          '对话框打开时常驻图层必须进入降级态');

        PluginSurfaceHost.close('demo-plugin:panel');
        assert.equal(ambientShell.classList.contains('is-host-occluded'), false,
          '对话框关闭后必须摘掉降级标记');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_occlusion_follows_page_visibility():
    """页面不可见时也进入降级态（插件据此暂停动画）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.init();
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        const shell = PluginSurfaceHost.open.get('demo-plugin:pet').shell;
        assert.equal(shell.classList.contains('is-host-occluded'), false);

        globalThis.document.visibilityState = 'hidden';
        globalThis.document.dispatch('visibilitychange', {});
        assert.equal(shell.classList.contains('is-host-occluded'), true,
          '页面不可见时常驻图层必须进入降级态');

        globalThis.document.visibilityState = 'visible';
        globalThis.document.dispatch('visibilitychange', {});
        assert.equal(shell.classList.contains('is-host-occluded'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_ambient_occlusion_follows_fullscreen_scrim():
    """插件自调 `setFullscreenScrim` 也要让常驻图层降级（宿主统一触发）。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';
        import { setFullscreenScrim } from './static/js/utils/dom.js';

        PluginSurfaceHost.init();
        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });
        const shell = PluginSurfaceHost.open.get('demo-plugin:pet').shell;

        setFullscreenScrim(true, 'demo-plugin:overlay');
        assert.equal(shell.classList.contains('is-host-occluded'), true);

        setFullscreenScrim(false, 'demo-plugin:overlay');
        assert.equal(shell.classList.contains('is-host-occluded'), false);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_dialog_surfaces_are_unaffected_by_ambient_changes():
    """常驻图层不得反过来影响对话框型 surface 的既有语义。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        PluginSurfaceHost.register('demo-plugin', 'pet', {
          type: 'ambient',
          mount() {},
        });

        PluginSurfaceHost.register('demo-plugin', 'panel', {
          type: 'panel',
          title: '面板',
          mount() {},
        });
        const container = PluginSurfaceHost.openSurface('demo-plugin:panel', {});
        const shell = container.parentNode;

        assert.equal(shell.getAttribute('role'), 'dialog');
        assert.equal(shell.getAttribute('aria-modal'), 'true');
        assert.equal(globalThis.document.body.classList.contains('has-fullscreen-scrim'), true,
          'panel 仍须声明遮罩');
        assert.equal(shell.classList.contains('is-host-occluded'), false,
          '降级标记只属于 ambient 容器');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_host_filters_ambient_by_device_feature():
    """`hostFeatures()` 在桌面产出 `hasAmbient`，移动端不产出。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { hostFeatures } from './static/js/contributionRegistry.js';

        globalThis.__setStore({ deviceType: 'desktop' });
        const desktop = hostFeatures();
        assert.ok(desktop.includes('hasAmbient'), '桌面必须产出 hasAmbient');

        globalThis.__setStore({ deviceType: 'mobile' });
        const mobile = hostFeatures();
        assert.ok(!mobile.includes('hasAmbient'), '移动端不得产出 hasAmbient');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_host_features_report_high_dpi():
    """`hasPixelRatio` 按 devicePixelRatio >= 1.5 门控。"""
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { hostFeatures } from './static/js/contributionRegistry.js';

        globalThis.window.devicePixelRatio = 1;
        assert.ok(!hostFeatures().includes('hasPixelRatio'));

        globalThis.window.devicePixelRatio = 2;
        assert.ok(hostFeatures().includes('hasPixelRatio'));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
