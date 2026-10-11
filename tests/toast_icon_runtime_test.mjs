/**
 * toast 图标位运行时契约（真实驱动 `static/js/state.js`）。
 *
 * 仓库没有 JS 测试运行器，宿主对插件 JS 的做法是 **Node + 最小 DOM 垫片**
 * （见 `tests/test_plugin_ambient_surface.py`）。这里照同一模式驱动**真实模块**，
 * 而不是对源码做字符串断言——图标位的行为（三态解析 + 未知名字告警）只有跑起来才看得见。
 *
 * 用法：node tests/toast_icon_runtime_test.mjs
 * 退出码 0 = 全部通过。
 */

import assert from 'node:assert/strict';

// ---------------------------------------------------------------- 最小 DOM 垫片

class ShimClassList {
  constructor() { this.s = new Set(); }
  add(...names) { names.forEach((n) => this.s.add(n)); }
  remove(...names) { names.forEach((n) => this.s.delete(n)); }
  contains(name) { return this.s.has(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.s.has(name) : Boolean(force);
    if (on) this.s.add(name); else this.s.delete(name);
    return on;
  }
  get value() { return [...this.s].join(' '); }
}

class ShimNode {
  constructor(tagName) {
    this.tagName = String(tagName || '').toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.classList = new ShimClassList();
    this.textContent = '';
    this.style = { setProperty() {}, removeProperty() {} };
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] ?? null; }
  removeAttribute(name) { delete this.attributes[String(name)]; }
  appendChild(child) { this.children.push(child); return child; }
  prepend() {}
  removeChild() {}
  insertBefore() {}
  addEventListener() {}
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  get innerHTML() { return ''; }
  set innerHTML(_value) {}
  focus() {}
  contains() { return false; }
  animate() { return {}; }
  getBoundingClientRect() { return { width: 0, height: 0, top: 0, left: 0 }; }
}

const documentElement = new ShimNode('html');
globalThis.document = {
  documentElement,
  body: new ShimNode('body'),
  head: new ShimNode('head'),
  createElement: (tag) => new ShimNode(tag),
  createElementNS: (_ns, tag) => new ShimNode(tag),
  createTextNode: (text) => ({ textContent: String(text) }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent: () => true,
  visibilityState: 'visible',
  readyState: 'complete',
};

globalThis.window = globalThis;
globalThis.innerWidth = 1440;
globalThis.innerHeight = 900;
globalThis.visualViewport = {
  height: 900, width: 1440, addEventListener() {}, removeEventListener() {},
};
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.matchMedia = () => ({
  matches: false, addEventListener() {}, removeEventListener() {},
});
globalThis.dispatchEvent = () => true;
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.Node = class Node {};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.fetch = async () => ({ json: async () => ({}) });
globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });

// 捕获 console.warn：未知名字必须**可见**，这是本次修复的一半价值。
const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => { warnings.push(args.map(String).join(' ')); };

// 注入 store：`initState()` 里的 `Alpine.store("global", {...})` 落到这里。
let capturedStore = null;
globalThis.Alpine = {
  store(_name, value) { capturedStore = value; return value; },
  reactive: (value) => value,
  initTree() {},
  $data() { return {}; },
};

// ---------------------------------------------------------------- 真实模块

const stateModule = await import('../static/js/state.js');
const { resolveToastIcon, initState } = stateModule;
initState();
const store = capturedStore;

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, detail: error && error.message });
  }
}

function toast(icon, options) {
  warnings.length = 0;
  store.showToast('文案必须照常显示', 1000, icon, options);
  return {
    kind: store.toastIconKind,
    href: store.toastIconHref,
    mask: store.toastIconMask,
    icon: store.toastIcon,
    text: store.toastMessage,
    warned: warnings.length > 0,
    warning: warnings[0] || '',
  };
}

// ------------------------------------------------ ① 宿主图标（含旧白名单外的）

check('旧白名单内的宿主图标：href 与旧实现逐字节相同', () => {
  const value = toast('check');
  assert.equal(value.kind, 'host');
  assert.equal(value.href, '/static/icons/ui.svg#icon-check');
  assert.equal(value.mask, '');
  assert.equal(value.warned, false);
});

check('宿主真实图标但不在旧白名单：现在能渲染（旧实现静默置空）', () => {
  const value = toast('heart');
  assert.equal(value.kind, 'host');
  assert.equal(value.href, '/static/icons/ui.svg#icon-heart');
  assert.equal(value.mask, '');
  assert.equal(value.warned, false, 'heart 是合法图标名，不该告警');
});

check('宿主图标必须走 <use>（sprite 引用），不得退化成 mask', () => {
  const value = toast('wand');
  assert.equal(value.kind, 'host');
  assert.ok(value.href.includes('#icon-wand'));
  assert.equal(value.mask, '', '描边式 sprite 用 mask 会渲染成实心块');
});

check('跨 sprite 的图标名解析到正确的 sprite', () => {
  const value = toast('backup-rollback');
  assert.equal(value.kind, 'host');
  assert.equal(value.href, '/static/icons/detail.svg#icon-backup-rollback');
});

check('旧实现把 tags / link-source 错指到 detail.svg（那里没有 symbol），现已纠正', () => {
  for (const name of ['tags', 'link-source']) {
    const value = toast(name);
    assert.equal(value.kind, 'host', name);
    assert.equal(value.href, `/static/icons/ui.svg#icon-${name}`);
  }
});

// ------------------------------------------------ ② 独立动效 SVG 特例

check('loading-animation 仍走 <img> 分支（不在 sprite 表里，永远解析不出 symbol）', () => {
  const value = toast('loading-animation');
  assert.equal(value.kind, 'image');
  assert.equal(value.href, '/static/icons/loading-animation.svg');
  assert.equal(value.mask, '');
  assert.equal(value.warned, false, '这是受支持的特例，不该告警');
});

// ------------------------------------------------ ③ 插件自带资源路径

check('插件资源路径：有 pluginId 时解析为 asset + mask', () => {
  const value = toast('frontend/assets/icon.svg', { pluginId: 'stm-pet' });
  assert.equal(value.kind, 'asset');
  assert.equal(value.href, '', '插件资源不能塞进 <use>，会渲染成空图形');
  assert.equal(
    value.mask,
    'url("/api/plugins/stm-pet/assets/frontend/assets/icon.svg")',
  );
  assert.equal(value.warned, false);
});

check('插件资源路径：拿不到 pluginId 时降级而非猜 URL', () => {
  const value = toast('frontend/assets/icon.svg');
  assert.equal(value.kind, 'missing');
  assert.equal(value.mask, '');
  assert.equal(value.href, '');
  assert.equal(value.warned, true);
});

check('插件资源路径：拒绝 `..` 穿越（与后端 assets.py 同一套约束）', () => {
  for (const bad of ['../secret.svg', 'a/../../b.svg', 'a/..\\b.svg']) {
    const value = toast(bad, { pluginId: 'stm-pet' });
    assert.equal(value.kind, 'missing', `${bad} 必须被拒绝`);
    assert.equal(value.warned, true, `${bad} 被拒时必须告警`);
  }
});

check('插件资源路径：前导斜杠按「插件内相对路径」归一，URL 始终落在插件资产路由下', () => {
  // `resolvePluginIcon()` 的既有语义（与 `entries[].icon` / `api.ui.icon()` 共用）：
  // 剥掉前导 `/` 当作插件内相对路径，**不是**放行绝对路径——产物永远是
  // `/api/plugins/<id>/assets/<path>`，真正的越界检查在后端
  // `core/plugins/assets.py:_resolve_asset_path()`（`realpath` + `is_under_base`）。
  const value = toast('/assets/icon.svg', { pluginId: 'stm-pet' });
  assert.equal(value.kind, 'asset');
  assert.equal(
    value.mask,
    'url("/api/plugins/stm-pet/assets/assets/icon.svg")',
    '绝不能解析成宿主静态目录或文件系统绝对路径',
  );
  assert.ok(value.mask.startsWith('url("/api/plugins/stm-pet/assets/'));
});

check('插件资源路径：扩展名收窄到 svg/png/webp', () => {
  const gif = toast('assets/anim.gif', { pluginId: 'stm-pet' });
  assert.equal(gif.kind, 'missing');

  const png = toast('assets/logo.png', { pluginId: 'stm-pet' });
  assert.equal(png.kind, 'asset');
  assert.ok(png.mask.includes('/api/plugins/stm-pet/assets/assets/logo.png'));
});

// ------------------------------------------------ ④ 未知名字 / 宽容降级

check('未知图标名：留空图标位 + console.warn（旧实现完全静默）', () => {
  const value = toast('no-such-icon');
  assert.equal(value.kind, 'missing');
  assert.equal(value.icon, '', 'toastIcon 为空 → 模板不渲染图标位');
  assert.equal(value.warned, true, '静默失效必须变成可见');
  assert.ok(
    value.warning.includes('no-such-icon'),
    `告警要带上原始取值，实际=${value.warning}`,
  );
});

check('图标缺失不影响文案：文案必须照常显示', () => {
  const value = toast('no-such-icon');
  assert.equal(value.text, '文案必须照常显示');
});

check('空图标位不告警（宿主大量调用只传前两个参数）', () => {
  for (const empty of ['', '   ', null, undefined]) {
    const value = toast(empty);
    assert.equal(value.kind, '');
    assert.equal(value.warned, false, `icon=${JSON.stringify(empty)} 不该告警`);
  }
});

check('字符串 duration 仍被容忍（旧调用形如 showToast(msg, "error")）', () => {
  warnings.length = 0;
  store.showToast('测试', 'error');
  assert.equal(store.showToastState, true);
  assert.equal(store.toastIconKind, '');
  assert.equal(store.toastIcon, '');
});

// ------------------------------------------------ ⑤ 隐藏时状态要一起清空

check('隐藏 toast 时清空全部图标状态（不留陈旧 mask/href）', async () => {
  store.showToast('测试', 1, 'frontend/assets/icon.svg', { pluginId: 'stm-pet' });
  assert.equal(store.toastIconKind, 'asset');
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(store.showToastState, false);
  assert.equal(store.toastIcon, '');
  assert.equal(store.toastIconKind, '');
  assert.equal(store.toastIconHref, '');
  assert.equal(store.toastIconMask, '');
});

// ------------------------------------------------ ⑥ 纯函数：resolveToastIcon

check('resolveToastIcon 与 uiPrimitives 的三态契约一致', () => {
  assert.deepEqual(resolveToastIcon('check'), {
    requested: 'check', kind: 'host',
    href: '/static/icons/ui.svg#icon-check', mask: '',
  });
  assert.equal(resolveToastIcon('heart').kind, 'host');
  assert.equal(resolveToastIcon('loading-animation').kind, 'image');
  assert.equal(
    resolveToastIcon('assets/i.svg', { pluginId: 'p' }).kind,
    'asset',
  );
  assert.equal(resolveToastIcon('nope').kind, 'missing');
  assert.deepEqual(resolveToastIcon(''), {
    requested: '', kind: '', href: '', mask: '',
  });
});

check('resolveToastIcon 不产生宿主前缀硬拼漏洞（不接受裸 sprite 文件名）', () => {
  // 旧模板是把 `/static/icons/` 硬拼在插件的入参后面，白名单并不参与路径校验。
  // 现在取值必须先通过 resolveIcon 的命名空间判定。
  assert.equal(resolveToastIcon('ui.svg').kind, 'missing');
  assert.equal(resolveToastIcon('../ui.svg').kind, 'missing');
});

console.warn = realWarn;

// ---------------------------------------------------------------- 汇总

let failed = 0;
for (const item of results) {
  if (item.ok) {
    process.stdout.write(`  PASS  ${item.name}\n`);
  } else {
    failed += 1;
    process.stdout.write(`  FAIL  ${item.name}\n        ${item.detail}\n`);
  }
}
process.stdout.write(
  `\ntoast 图标位运行时契约：${results.length - failed}/${results.length} 通过\n`,
);
process.exit(failed ? 1 : 0);
