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
import re
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
VARIABLES_CSS_PATH = 'static/css/modules/variables.css'


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
      // 通用标签名回退（`svg` / `span` / `header` / `h2` …）。
      // 没有这一条，断言「图标位里有 svg」会恒为 0 —— 不是代码错，是垫片不够用。
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
        'export const SURFACE_TYPES = ["panel", "modal", "page", "sheet", "ambient"]',
        'register(pluginId, surfaceId, spec)',
        'openSurface(key, ctx = {})',
        'close(key)',
        'isOpen(key)',
        'closePlugin(pluginId)',
        'unregisterPlugin(pluginId)',
    ):
        assert fragment in source, fragment


def test_surface_types_match_backend_contract():
    """前端 surface 类型必须是**后端可声明类型的超集**。

    真实契约是「宿主前端支持的 surface 类型 ⊇ manifest 允许声明的类型」：

    - 后端 `core/plugins/entries.py:SURFACE_TYPES` 用于校验 manifest 的
      `entries[].surface.type`，而 `ambient`（常驻环境层）**没有用户可见入口**
      （注册即挂载），在 manifest 里声明它没有意义，因此后端**保持四元组不变**。
    - 前端额外支持宿主专属类型 `ambient`，并在本地拒绝后才降级为 `panel`。

    函数名保留（避免无谓变更），但语义是**超集**而不是恒等——原来的写法比较的
    是从后端 import 的变量与后端自身，是同义反复，并没有真的在查前端。
    """
    from core.plugins.entries import SURFACE_TYPES

    source = read_source(SURFACE_HOST_PATH)
    assert 'SURFACE_TYPES = ["panel", "modal", "page", "sheet", "ambient"]' in source

    # 后端集合不变（manifest 仍只允许四种），且前端是它的超集
    assert set(SURFACE_TYPES) == {'panel', 'modal', 'page', 'sheet'}
    assert set(SURFACE_TYPES) <= {'panel', 'modal', 'page', 'sheet', 'ambient'}


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


def test_surface_root_does_not_create_a_stacking_context():
    """回归：挂载根上的 `z-index` 会创建层叠上下文，把所有 surface 锁在下层。

    `position` + 非 `auto` 的 `z-index` 触发层叠上下文；根节点一旦被锁在
    `--z-surface`(60)，它内部 surface 声明的 `--z-modal-popover`(3400) 就只在
    60 层**内部**比较，对外一律被宿主模态（设置页 1100 / 详情页 3000）盖住。
    表现：从设置页的「插件设置入口」点开插件面板，面板开了却完全看不见。

    实测（Playwright/Chromium，`tools/verify_plugin_surface_layering.py`）：
    加回根节点的 `z-index` 后，声明 3400 的 modal/panel/sheet 全部被 z-index 1100
    的设置页盖住；移除后三者都正常压住设置页。
    """
    css = read_source(SURFACE_CSS_PATH)
    declarations = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    root_block = declarations.split('.plugin-surface-root {', 1)[1].split('}', 1)[0]
    assert 'position: relative;' in root_block
    assert 'z-index' not in root_block, (
        '.plugin-surface-root 不得设 z-index：它会创建层叠上下文，'
        '把内部所有 surface 锁在下层（宿主模态一开就全被盖住）'
    )
    # 也不能用其他会触发层叠上下文的属性代替
    for trigger in ('opacity', 'transform', 'filter', 'isolation', 'contain',
                    'will-change', 'perspective'):
        assert trigger not in root_block, trigger


def test_dialog_type_surfaces_sit_above_host_modals():
    """`modal` / `panel` / `sheet` 是用户主动打开的浮层，必须在对话框层。

    `panel` 还是 `entries[].surface.type` 缺省时的回退值
    （`entryRegistry.js:normalizeDeclaredEntry`），因此它必须与 `modal` 一样
    能盖住唤起它的宿主模态，否则「插件声明了 settings 入口但没写 type」就会重现
    「点了看不见」的问题。

    `page` 刻意例外：它替换主内容区，不是浮层，宿主模态打开时就该压在它上面；
    因此它从设置页被点开时由 `pluginManager.openSettingsEntry` 先请设置页让位。
    """
    css = read_source(SURFACE_CSS_PATH)
    declarations = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    for selector in ('.plugin-surface--modal', '.plugin-surface--panel',
                     '.plugin-surface--sheet'):
        block = declarations.split(selector + ' {', 1)[1].split('}', 1)[0]
        assert 'z-index: var(--z-modal-popover);' in block, (
            f'{selector} 必须在对话框层（--z-modal-popover），否则会被宿主模态盖住'
        )

    page_block = declarations.split('.plugin-surface--page {', 1)[1].split('}', 1)[0]
    assert 'z-index' not in page_block, 'page 型刻意保持低层，不要抬到对话框层'

    ambient_block = declarations.split('.plugin-surface--ambient {', 1)[1].split('}', 1)[0]
    assert 'z-index: var(--z-ambient);' in ambient_block


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


def test_primitive_dialog_overlay_sits_above_plugin_surfaces():
    """回归：`api.ui.confirm` / `api.ui.prompt` 的遮罩必须盖得住插件 surface。

    实测现场：AI 助手工作台是 `modal` 型 surface（`--z-modal-popover` 3400），
    而原语遮罩带 `.modal-overlay` 的缺省 `--z-modal-std`(1100)。首次打开设置页时
    弹出的「出站内容提示」就画在工作台**下面**：看得见、点不到，用户报「层级在
    模态框之下」。

    因此这里锁死三件事：遮罩显式取 `--z-modal-alert`；令牌严格高于
    `--z-modal-popover`；且仍低于提示 / Toast，不抢更靠前的反馈层。
    """
    import re

    css = re.sub(r'/\*.*?\*/', '', read_source(PRIMITIVES_CSS_PATH), flags=re.S)
    block = css.split('.modal-overlay.ui-primitive-overlay {', 1)[1].split('}', 1)[0]
    assert 'z-index: var(--z-modal-alert);' in block, (
        '原语对话框遮罩必须显式取 --z-modal-alert，否则会被插件 surface 盖住'
    )

    variables = re.sub(r'/\*.*?\*/', '', read_source(VARIABLES_CSS_PATH), flags=re.S)

    def token(name):
        match = re.search(rf'--{name}:\s*(\d+)', variables)
        assert match is not None, name
        return int(match.group(1))

    assert token('z-modal-popover') < token('z-modal-alert') < token('z-context-menu'), (
        '--z-modal-alert 必须夹在插件对话框层与右键菜单层之间'
    )
    assert token('z-modal-alert') < token('z-tooltip')
    assert token('z-modal-alert') < token('z-toast')
    assert '.z-modal-alert {' in variables, '令牌要配 !important 工具类（与其它 --z-* 一致）'


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
        assert.equal(ctxSeen.entryId, 'card-1');
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
def test_reopening_an_open_surface_delivers_the_new_ctx():
    """surface 已打开时再次从别的入口进入，必须把**新的 ctx** 交给插件。

    同一个 surface 常被多个入口复用（本插件的 `workbench` 服务坞 / 右键分类 /
    批量菜单 / 设置四个入口）。若第二次点击只返回既有容器、不投递新 ctx，
    「先右键 A 分类、再右键 B 分类」会一直显示 A 的作用域——用户看到的是
    上一次的分析范围，却以为已经切到 B。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        const seen = [];
        PluginSurfaceHost.register('demo-plugin', 'workbench', {
          mount(container, ctx) { seen.push(['mount', ctx.target.path]); },
          onOpen(ctx) { seen.push(['onOpen', ctx.target.path]); },
        });

        PluginSurfaceHost.openSurface('demo-plugin:workbench', {
          source: 'context', targetId: 'analyze-folder',
          target: { kind: 'folder', path: 'A' },
        });
        assert.deepEqual(seen, [['mount', 'A'], ['onOpen', 'A']]);

        // 第二次从另一个入口进入同一个 surface：不重新 mount，但必须投递新 ctx
        PluginSurfaceHost.openSurface('demo-plugin:workbench', {
          source: 'context', targetId: 'analyze-folder',
          target: { kind: 'folder', path: 'B' },
        });
        assert.deepEqual(seen, [
          ['mount', 'A'], ['onOpen', 'A'], ['onOpen', 'B'],
        ], '重复打开必须投递新 ctx，且不得重新 mount（会丢用户已填的表单）');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_open_surface_forwards_right_click_target_to_mount():
    """右键目标必须出现在 mount 的 ctx 里，形状是 `ctx.target`。

    只传 `entryId`（= 入口 id）的话，插件无法知道「分析哪一个分类」，只能退回去
    读宿主的全局选中集——而右键分类的作用域根本不是选中集。

    `target.path` 为 `""` 表示根目录，是**合法值**，因此不能靠真值判断来区分
    「没有目标」：存在性由 `ctx.target === null` 表达。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let ctxSeen = null;
        PluginSurfaceHost.register('demo-plugin', 'workbench', {
          mount(container, ctx) { ctxSeen = ctx; },
        });

        PluginSurfaceHost.openSurface('demo-plugin:workbench', {
          source: 'context',
          targetId: 'analyze-folder',
          mode: 'cards',
          target: { kind: 'folder', path: '', ids: ['a/b.png', 'a/c.png'] },
        });

        assert.deepEqual(ctxSeen.target, {
          kind: 'folder',
          mode: 'cards',
          path: '',
          id: '',
          ids: ['a/b.png', 'a/c.png'],
        });
        // 旧扁平字段已删除：留着会诱导插件继续读旧形状
        assert.equal('targetKind' in ctxSeen, false);
        assert.equal('targetPath' in ctxSeen, false);
        assert.equal('targetIds' in ctxSeen, false);
        // 入口 id 改名为 entryId（旧名 targetId 容易被读成「目标卡片 id」）
        assert.equal(ctxSeen.entryId, 'analyze-folder');

        // 不带目标时 `target` 是 null，而不是「一个字段全空的 target」
        let plain = null;
        PluginSurfaceHost.register('demo-plugin', 'plain', {
          mount(container, ctx) { plain = ctx; },
        });
        PluginSurfaceHost.openSurface('demo-plugin:plain', { source: 'dock', target: null });
        assert.equal(plain.target, null);
        assert.equal(plain.entryId, '');

        // 旧扁平字段即便被调用方传进来也要被丢弃——否则第三方插件仍能读到旧形状，
        // 「删除旧字段」就只是宿主自己的口头约定。
        let legacy = null;
        PluginSurfaceHost.register('demo-plugin', 'legacy', {
          mount(container, ctx) { legacy = ctx; },
        });
        PluginSurfaceHost.openSurface('demo-plugin:legacy', {
          source: 'context',
          targetId: 'entry-x',
          targetKind: 'folder',
          targetPath: 'A',
          targetIds: ['c1'],
          target: { kind: 'folder', path: 'A' },
          myCustomField: 'kept',
        });
        assert.equal('targetKind' in legacy, false);
        assert.equal('targetPath' in legacy, false);
        assert.equal('targetIds' in legacy, false);
        assert.equal('targetId' in legacy, false);
        assert.equal(legacy.entryId, 'entry-x');
        // 插件自定义字段仍然原样透传
        assert.equal(legacy.myCustomField, 'kept');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_surface_header_renders_icon_title_and_generic_close():
    """标题行：图标 + 副标题 + 标题 + 通用关闭图标（问题 3）。

    旧版头部只有纯文本标题 + 文字「×」，插件不得不在自己内容区**再画一条**
    状态栏放品牌图标与状态胶囊 → 弹层顶部出现两行，比主程序自己的弹窗「多一层」。
    现在图标归标题行（`.plugin-surface__header-icon`，与主程序
    `.ui-modal-header-icon` 同款开放字形），状态胶囊走 `headerExtra` 同行显示。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost } from './static/js/pluginSurfaceHost.js';

        let extraContainer = null;
        PluginSurfaceHost.register('demo-plugin', 'workbench', {
          title: 'AI 助手',
          description: '角色卡分析工作台',
          icon: 'wand',
          headerExtra(container) { extraContainer = container; },
          mount() {},
        });
        PluginSurfaceHost.openSurface('demo-plugin:workbench');

        const shell = globalThis.__shim.document.body
          .querySelectorAll('.plugin-surface')[0];
        const header = shell.querySelectorAll('.plugin-surface__header')[0];

        // 图标位存在，且是**开放字形**（无边框无底色由 CSS 保证）
        const iconSlot = header.querySelectorAll('.plugin-surface__header-icon')[0];
        assert.ok(iconSlot, '标题行必须有图标位');
        assert.equal(iconSlot.querySelectorAll('svg').length, 1, '图标位里应有 svg');

        // 副标题 + 标题
        const eyebrow = header.querySelectorAll('.plugin-surface__eyebrow')[0];
        assert.equal(eyebrow.textContent, '角色卡分析工作台');
        const title = header.querySelectorAll('.plugin-surface__title')[0];
        assert.equal(title.textContent, 'AI 助手');

        // 附加槽交给插件（状态胶囊同行显示）
        assert.ok(extraContainer, 'headerExtra 必须被调用');
        assert.equal(extraContainer.className, 'plugin-surface__header-extra');

        // 关闭按钮用宿主通用图标，而不是文字「×」
        const close = header.querySelectorAll('.plugin-surface__close')[0];
        assert.equal(close.textContent, '', '关闭按钮不该是文字 ×');
        assert.equal(close.querySelectorAll('svg').length, 1, '关闭按钮应是图标');
        assert.equal(close.getAttribute('aria-label'), '关闭');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_modal_size_tier_is_fixed_and_reflected_on_the_shell():
    """modal 的尺寸档位落到 `data-surface-size`，由 CSS 给出**固定**宽高。

    早先用 `max-height` + 内容自适应高度：插件切换页签时内容长度变化 →
    弹层高度跟着跳，看起来像「窗口在自己缩放」。固定档位让容器在打开期间恒定。
    """
    result = run_dom_script(
        """
        import assert from 'node:assert/strict';
        import { PluginSurfaceHost, SURFACE_SIZES } from './static/js/pluginSurfaceHost.js';

        assert.deepEqual(SURFACE_SIZES, ['sm', 'md', 'lg', 'xl']);

        const sizes = [];
        for (const size of ['lg', 'sm']) {
          PluginSurfaceHost.register('demo-plugin', 's-' + size, {
            title: size, type: 'modal', size, mount() {},
          });
          PluginSurfaceHost.openSurface('demo-plugin:s-' + size);
          const shell = globalThis.__shim.document.body
            .querySelectorAll('.plugin-surface--modal')
            .find((node) => node.dataset.surfaceSize === size);
          assert.ok(shell, size + ' 档位必须落到 data-surface-size');
          sizes.push(shell.dataset.surfaceSize);
          PluginSurfaceHost.close('demo-plugin:s-' + size);
        }
        assert.deepEqual(sizes, ['lg', 'sm']);

        // 非法档位回退默认（md），不抛错
        PluginSurfaceHost.register('demo-plugin', 'bad', {
          title: 'bad', type: 'modal', size: 'huge', mount() {},
        });
        PluginSurfaceHost.openSurface('demo-plugin:bad');
        const badShell = globalThis.__shim.document.body
          .querySelectorAll('.plugin-surface--modal')
          .find((node) => node.dataset.surface === 'bad');
        assert.equal(badShell.dataset.surfaceSize, 'md');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_modal_css_uses_fixed_height_not_content_sized():
    """CSS 侧：modal 用 `height` 固定档位，且没有 `max-height` 内容自适应残留。"""
    css = read_source(SURFACE_CSS_PATH)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    for size in ('sm', 'md', 'lg', 'xl'):
        assert f"[data-surface-size='{size}']" in code, size

    modal_block = code.split('.plugin-surface--modal {', 1)[1].split('}', 1)[0]
    assert 'height' not in modal_block or 'max-height' not in modal_block, (
        '基础 modal 规则不该再靠 max-height 自适应内容高度'
    )
    # 每个档位都给出确定高度。
    # 注意用正则而不是 `'height:' in block`——`max-height:` 也包含 `height:` 子串，
    # 那样写的话「把 height 换回 max-height」仍然通过，等于没测。
    for size in ('sm', 'md', 'lg', 'xl'):
        block = code.split(f"[data-surface-size='{size}'] {{", 1)[1].split('}', 1)[0]
        assert re.search(r'(?<!max-)height:\s*\S', block), (
            f'{size} 档位必须给出固定 height（不是 max-height 自适应）'
        )
        assert 'max-height' not in block, (
            f'{size} 档位不得用 max-height 撑高，否则切换页签时弹层会跳动'
        )
        assert re.search(r'(?<!max-)width:\s*\S', block), f'{size} 档位必须给出固定 width'


def test_surface_css_has_no_hardcoded_close_glyph():
    """关闭按钮不再依赖文字「×」（字形随字体变化，且与宿主图标体系不一致）。"""
    css = read_source(SURFACE_CSS_PATH)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    close_block = code.split('.plugin-surface__close {', 1)[1].split('}', 1)[0]
    assert 'font-size' not in close_block, (
        '关闭按钮现在是图标，不该再靠 font-size 撑文字字形'
    )


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
