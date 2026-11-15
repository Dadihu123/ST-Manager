/* 视图栈：为「返回上一级」（Android 返回键 / iOS 侧滑 / Alt+←）提供统一语义。
 *
 * 背景：本项目历史上**完全没有历史栈**——页面切换靠 `x-show` + `$store.global.currentMode`，
 * 弹窗靠各自的布尔量。因此在浏览器里按返回会回到上一个 URL 或直接退出；
 * 在 WebView 里更糟：`canGoBack()` 恒为 false，系统返回手势直接退出应用。
 *
 * 设计约束（很重要）：
 * 1. **不改变任何现有 Escape 行为**。Escape 仍由各组件自己处理；本模块只是额外
 *    提供一条「按 LIFO 关闭最上层」的通道，供返回手势调用。
 * 2. **不要求组件改造**。弹层通过 `register()` 声明「我开着的时候，请先关我」，
 *    关闭动作由组件自己的函数完成，本模块不直接操作任何组件状态。
 * 3. **入栈时机由 `sync()` 驱动**，基于「当前是否有层处于活动状态」的轮询式刷新，
 *    而不是要求每个打开动作都记得调 push。这样漏接一处的后果只是「该层不参与
 *    返回手势」，不会让整个栈坏掉。
 */

export const VIEW_STACK_EVENT = "view-stack:depth-changed";

/** 单层：{ key, isActive(): boolean, close(): void, priority?: number } */
const layers = [];

/** 最近一次「有层活动」的状态，用于只在跨越空/非空边界时才动 history。 */
let hasActiveLayer = false;

/** 是否已安装 popstate 监听。 */
let installed = false;

/** 关闭栈顶时的保护：组件 close() 可能同步触发 sync()，避免重入。 */
let closing = false;
let cleanupPending = false;
let nativeBack = false;
let lastNotifiedDepth = -1;

/** 按作用域名索引组件；DOM 结构变化后再重建，避免逐层扫描整页。 */
export function createComponentLookup(root) {
  let index = null;
  const observer = typeof MutationObserver === 'function'
    ? new MutationObserver(() => { index = null; }) : null;
  observer?.observe(root, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['x-data', 'data-back-scope'],
  });
  const lookup = name => {
    if (!index || !observer) {
      index = new Map();
      root.querySelectorAll('[x-data], [data-back-scope]').forEach(element => {
        const data = element.getAttribute('x-data') || '';
        const names = [data.replace(/\(\)$/, ''), element.getAttribute('data-back-scope')];
        for (const key of names) {
          if (key && !index.has(key)) index.set(key, element);
        }
      });
    }
    return index.get(name) || null;
  };
  lookup.disconnect = () => { observer?.disconnect(); index = null; };
  return lookup;
}

function activeLayers() {
  const active = [];
  for (const layer of layers) {
    let isActive = false;
    try {
      isActive = !!layer.isActive();
    } catch (err) {
      // 组件已被销毁时 getter 可能抛错：视为不活动，绝不因此打断返回流程。
      isActive = false;
    }
    if (isActive) active.push(layer);
  }
  return active;
}

/** 栈顶（最后注册且处于活动状态的一层）。 */
export function topLayer() {
  const active = activeLayers();
  return active.length ? active[active.length - 1] : null;
}

export function depth() {
  return activeLayers().length;
}

/**
 * 诊断快照：列出全部已注册层及其活动状态。
 *
 * 为什么需要：真机上「返回键直接退出应用」时，无法从外部判断到底是
 * 「层没注册」「isActive 恒为 false」还是「壳没调到 __stmHostBack」。
 * 有这份快照就能一眼区分三者。也挂到 window 上便于 adb/CDP 直接读取。
 */
export function describe() {
  return {
    registered: layers.map((layer) => {
      let active = false;
      let error = null;
      try {
        active = !!layer.isActive();
      } catch (err) {
        error = String((err && err.message) || err);
      }
      return { key: layer.key, active, error };
    }),
    depth: depth(),
    installed,
    hasActiveLayer,
  };
}

/**
 * 关闭栈顶一层。返回 true 表示确实关掉了什么。
 * 供返回手势（Android 返回键 / iOS 侧滑）调用。
 */
export function closeTop() {
  if (closing) return false;
  const layer = topLayer();
  if (!layer) return false;

  closing = true;
  try {
    layer.close();
  } catch (err) {
    console.warn('[viewStack] 关闭视图层失败:', layer.key, err);
  } finally {
    closing = false;
  }
  sync();
  return true;
}

/**
 * 注册一个可被返回手势关闭的层。
 * 返回注销函数。
 */
export function register(layer) {
  if (!layer || typeof layer.isActive !== 'function' || typeof layer.close !== 'function') {
    throw new TypeError('register(layer) 需要 { key, isActive, close }');
  }
  const entry = {
    key: String(layer.key || `layer-${layers.length}`),
    isActive: layer.isActive,
    close: layer.close,
  };
  layers.push(entry);
  sync();

  return function unregister() {
    const index = layers.indexOf(entry);
    if (index >= 0) layers.splice(index, 1);
    sync();
  };
}

/**
 * 刷新栈状态，并在「是否有活动层」发生跨越时同步 history。
 *
 * 为什么用 pushState 而不是只在需要时手写：系统返回手势在 WebView 里
 * 依赖 `canGoBack()`。只有当浏览器历史中存在一项，`goBack()` 才有意义。
 * 我们在「进入有层状态」时压入一个哨兵项，返回时消费它。
 *
 * 注意：调用方顺序敏感 —— 这里会读取所有层的 isActive()，因此必须在
 * 状态已经改变之后调用。组件侧通过 `notify()` 在状态变化后触发。
 */
export function sync() {
  const activeCount = activeLayers().length;
  const active = activeCount > 0;
  hasActiveLayer = active;

  if (!nativeBack && !window.stmHost && !cleanupPending) {
    try {
      if (active && !window.history.state?.__viewStack) {
        // 压入哨兵：此时 canGoBack() 为 true，系统返回会触发 popstate。
        window.history.pushState({ __viewStack: true }, '');
      } else if (!active && window.history.state?.__viewStack) {
        // 层主动关完了：把哨兵退掉，避免历史里留下空条目。
        cleanupPending = true;
        window.history.back();
      }
    } catch (err) {
      // history 在沙箱 iframe 等环境可能受限；退化时不阻断功能。
      cleanupPending = false;
      console.warn('[viewStack] 同步 history 失败:', err);
    }
  }

  if (activeCount !== lastNotifiedDepth) {
    lastNotifiedDepth = activeCount;
    window.dispatchEvent(
      new CustomEvent(VIEW_STACK_EVENT, { detail: { depth: activeCount } })
    );
  }
}

/**
 * 由组件在「可能改变了层的活动状态」之后调用。
 *
 * 这是让哨兵项真正生效的关键：注册层本身不代表层已打开，只有组件状态变化
 * （弹窗 open/close）才会跨越「有无活动层」的边界。组件不必改造，本模块用
 * MutationObserver + 轻量轮询兜底（见 `install`）。
 */
export function notify() {
  sync();
}

/**
 * 处理一次「返回」请求。
 * 优先级：栈顶视图层 → 工作区（cards/wi/chats 等）→ 交还系统。
 *
 * @param {{getMode: () => string, getHomeMode?: () => string, setMode: (m: string) => void}} workspace
 * @returns {boolean} true = 已被处理，false = 应交还系统（Android 退出 / iOS 无动作）
 */
export function handleBack(workspace) {
  if (closeTop()) return true;

  if (workspace && typeof workspace.getMode === 'function') {
    const home = typeof workspace.getHomeMode === 'function' ? workspace.getHomeMode() : 'cards';
    const current = workspace.getMode();
    if (current && current !== home) {
      workspace.setMode(home);
      return true;
    }
  }
  return false;
}

/**
 * 安装 popstate 监听 + 状态变化观察（幂等）。
 * 宿主外壳（Android/iOS）也可直接调用 handleBack，无需经过 history。
 *
 * 为什么需要观察：本项目的弹窗显隐由各组件的布尔量 + `x-show` 驱动，
 * 没有统一的「打开/关闭」入口可以挂钩。若只靠组件主动调 `notify()`，
 * 漏接一处哨兵项就不会压入，WebView 里 `canGoBack()` 恒为 false，
 * 返回手势形同虚设。这里用 MutationObserver 观察 DOM 结构变化（`x-show`
 * 切换 `display` 会触发属性变化），在其后补一次 `sync()` 兜底。
 */
export function install(options = {}) {
  if (installed) return;
  installed = true;
  nativeBack = !!options.nativeBack;

  window.addEventListener('popstate', () => {
    if (nativeBack) return;
    if (cleanupPending) {
      cleanupPending = false;
      sync();
      return;
    }
    // 浏览器已经消费了历史项；这里只需关掉最上层。
    const state = window.history.state;
    if (!state || !state.__viewStack) {
      hasActiveLayer = false;
    }
    if (!closeTop() && options.onBack) {
      options.onBack();
    }
    sync();
  });

  // DOM 变化兜底：x-show 切换会改 style.display，属于属性变更。
  if (typeof MutationObserver === 'function' && typeof document !== 'undefined') {
    try {
      let scheduled = false;
      const observer = new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        const schedule = window.requestAnimationFrame || queueMicrotask;
        schedule(() => {
          scheduled = false;
          sync();
        });
      });
      observer.observe(document.body || document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['style', 'class', 'hidden'],
      });
    } catch (err) {
      console.warn('[viewStack] 安装 DOM 观察失败（返回手势仍可用）:', err);
    }
  }
}

/** 仅测试用：重置模块内部状态。 */
export function __resetForTests() {
  layers.length = 0;
  hasActiveLayer = false;
  installed = false;
  closing = false;
  cleanupPending = false;
  nativeBack = false;
  lastNotifiedDepth = -1;
}
