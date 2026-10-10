/**
 * static/js/pluginSurfaceHost.js
 * 宿主表面宿主（设计文档 D8 的 `mount(container, ctx)` 契约落点）。
 *
 * 核心承诺：**容器归宿主，插件只在容器内画东西**。
 * 插件不再需要自己写 `position: fixed` 的浮层——这正是本次地基修缮要消灭的模式
 * （`data/plugins/stm-ai-assistant/frontend/plugin.css` 里的 launcher/overlay 就是
 * 反面教材：它必须自己处理层级、滚动、焦点、ESC，还要绕开 backdrop-filter 黑块）。
 *
 * 宿主负责（插件不得重复实现）：
 * - 层级与尺寸、滚动、`data-marquee-ignore`（框选不命中）
 * - `role="dialog"` / `aria-modal`、焦点陷阱、ESC 关闭
 * - 运行时 `mount()` 抛错时销毁该 surface 并把入口置错误态，**不影响其他插件与宿主**
 *
 * 不使用 `backdrop-filter`：`.main-container` 已带 backdrop-filter，Chromium 会把它
 * 当 backdrop root，叠加固定定位的大内容会渲染出黑块（详见 layout.css 的实测记录）。
 */

import { setFullscreenScrim } from "./utils/dom.js";

export const SURFACE_TYPES = ["panel", "modal", "page", "sheet"];

const SURFACE_ROOT_ID = "plugin-surface-root";

/** 每种类型的容器类名与无障碍角色。 */
const SURFACE_CLASSES = {
  panel: "plugin-surface plugin-surface--panel",
  modal: "plugin-surface plugin-surface--modal",
  page: "plugin-surface plugin-surface--page",
  sheet: "plugin-surface plugin-surface--sheet",
};

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

function ensureSurfaceRoot() {
  let node = document.getElementById(SURFACE_ROOT_ID);
  if (node) return node;

  node = document.createElement("div");
  node.id = SURFACE_ROOT_ID;
  node.className = "plugin-surface-root";
  document.body.appendChild(node);
  return node;
}

export const PluginSurfaceHost = {
  initialized: false,
  /** 全局键 `<pluginId>:<surfaceId>` → 记录 */
  surfaces: new Map(),
  /** 已打开的全局键 → { key, entry, container, scrimOwner } */
  open: new Map(),
  activeKey: "",

  init() {
    if (this.initialized) return;
    this.initialized = true;
    ensureSurfaceRoot();

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !this.activeKey) return;
      event.preventDefault();
      event.stopPropagation();
      this.close(this.activeKey);
    });

    // 插件被禁用 / 卸载时，宿主**强制**卸载它的全部 surface（不依赖插件 deactivate）
    window.addEventListener("plugin:unloaded", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) this.closePlugin(String(detail.pluginId));
    });
  },

  /** 注册一个 surface。`spec.mount(container, ctx)` 是唯一必需的成员。 */
  register(pluginId, surfaceId, spec) {
    const id = String(surfaceId || "").trim();
    if (!id || !spec || typeof spec.mount !== "function") {
      console.warn(`[surfaceHost] 插件 ${pluginId} 注册了非法 surface: ${surfaceId}`);
      return "";
    }

    const key = `${String(pluginId)}:${id}`;
    this.surfaces.set(key, {
      key,
      id,
      pluginId: String(pluginId),
      title: String(spec.title || id),
      type: SURFACE_TYPES.includes(String(spec.type || "")) ? String(spec.type) : "panel",
      mount: spec.mount,
      unmount: typeof spec.unmount === "function" ? spec.unmount : null,
      onOpen: typeof spec.onOpen === "function" ? spec.onOpen : null,
      onClose: typeof spec.onClose === "function" ? spec.onClose : null,
    });
    return key;
  },

  has(key) {
    return this.surfaces.has(String(key || ""));
  },

  isOpen(key) {
    return this.open.has(String(key || ""));
  },

  /**
   * 打开一个 surface。
   *
   * `mount()` 抛错时：销毁该 surface 并把对应入口置错误态，返回 null —— 错误被
   * 隔离在单个插件内，其他插件与宿主不受影响。
   */
  openSurface(key, ctx = {}) {
    const record = this.surfaces.get(String(key || ""));
    if (!record) {
      console.warn(`[surfaceHost] 未注册的 surface: ${key}`);
      return null;
    }
    if (this.open.has(record.key)) return this.open.get(record.key).container;

    const root = ensureSurfaceRoot();
    const shell = document.createElement("div");
    shell.className = SURFACE_CLASSES[record.type] || SURFACE_CLASSES.panel;
    shell.dataset.plugin = record.pluginId;
    shell.dataset.surface = record.id;
    shell.dataset.surfaceType = record.type;
    // 框选（marqueeSelection）不命中坞与浮层
    shell.dataset.marqueeIgnore = "true";
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-modal", "true");
    shell.setAttribute("aria-label", record.title);

    const header = document.createElement("header");
    header.className = "plugin-surface__header";

    const title = document.createElement("h2");
    title.className = "plugin-surface__title";
    title.textContent = record.title;
    header.appendChild(title);

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "plugin-surface__close";
    closeButton.setAttribute("aria-label", "关闭");
    closeButton.textContent = "×";
    closeButton.addEventListener("click", () => this.close(record.key));
    header.appendChild(closeButton);

    const body = document.createElement("div");
    body.className = "plugin-surface__body";

    shell.appendChild(header);
    shell.appendChild(body);
    root.appendChild(shell);

    const scrimOwner = `plugin-surface:${record.key}`;
    // page 类型占满主内容区，不遮罩全屏，因此不声明 scrim
    if (record.type !== "page") setFullscreenScrim(true, scrimOwner);

    const state = {
      key: record.key,
      record,
      container: body,
      shell,
      scrimOwner: record.type === "page" ? "" : scrimOwner,
      disposer: null,
    };

    this.open.set(record.key, state);
    this.activeKey = record.key;

    try {
      const returned = record.mount(body, {
        source: String(ctx.source || ""),
        targetId: String(ctx.targetId || ""),
        mode: String(ctx.mode || ""),
        pluginId: record.pluginId,
        surfaceId: record.id,
      });
      // mount 返回函数时，宿主在关闭时调用它（D8 契约）
      if (typeof returned === "function") state.disposer = returned;
      if (record.onOpen) record.onOpen({ ...ctx, pluginId: record.pluginId });
    } catch (error) {
      console.error(`[surfaceHost] 插件 ${record.pluginId} 的 surface ${record.id} 挂载失败:`, error);
      this.close(record.key);
      window.dispatchEvent(
        new CustomEvent("plugin:surface-error", {
          detail: { pluginId: record.pluginId, surfaceId: record.id, error: String(error) },
        }),
      );
      return null;
    }

    this._trapFocus(shell);
    return body;
  },

  close(key) {
    const target = String(key || "");
    const state = this.open.get(target);
    if (!state) return false;

    this.open.delete(target);
    if (this.activeKey === target) this.activeKey = "";

    const { record } = state;
    // 卸载顺序：插件 disposer → unmount → onClose → 摘除 DOM。
    // 每一步单独 try/except，任何一步抛错都不能阻断容器回收。
    if (typeof state.disposer === "function") {
      try {
        state.disposer();
      } catch (error) {
        console.warn(`[surfaceHost] ${target} 的 mount disposer 抛错:`, error);
      }
    }
    if (record.unmount) {
      try {
        record.unmount(state.container);
      } catch (error) {
        console.warn(`[surfaceHost] ${target} 的 unmount 抛错:`, error);
      }
    }
    if (record.onClose) {
      try {
        record.onClose();
      } catch (error) {
        console.warn(`[surfaceHost] ${target} 的 onClose 抛错:`, error);
      }
    }

    if (state.shell && state.shell.parentNode) state.shell.parentNode.removeChild(state.shell);
    if (state.scrimOwner) setFullscreenScrim(false, state.scrimOwner);

    const previous = this.activeKey;
    if (!previous) this._restoreFocus();
    return true;
  },

  /** 关闭某插件的全部 surface（禁用 / 卸载 / destroy 时强制调用）。 */
  closePlugin(pluginId) {
    const prefix = `${String(pluginId || "")}:`;
    let closed = 0;
    for (const key of Array.from(this.open.keys())) {
      if (key.startsWith(prefix) && this.close(key)) closed += 1;
    }
    return closed;
  },

  /** 注销某插件的全部 surface 定义。 */
  unregisterPlugin(pluginId) {
    const prefix = `${String(pluginId || "")}:`;
    this.closePlugin(pluginId);
    let removed = 0;
    for (const key of Array.from(this.surfaces.keys())) {
      if (key.startsWith(prefix)) {
        this.surfaces.delete(key);
        removed += 1;
      }
    }
    return removed;
  },

  /** 焦点陷阱：Tab 在容器内循环，保证键盘用户不会跑到宿主 UI 上。 */
  _trapFocus(shell) {
    this._previousFocus = document.activeElement;

    const focusables = () => Array.from(shell.querySelectorAll(FOCUSABLE_SELECTOR));
    const first = focusables()[0];
    if (first && typeof first.focus === "function") first.focus();

    shell.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];

      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    });
  },

  _restoreFocus() {
    const target = this._previousFocus;
    this._previousFocus = null;
    if (target && typeof target.focus === "function" && document.contains(target)) {
      target.focus();
    }
  },
};

export default PluginSurfaceHost;
