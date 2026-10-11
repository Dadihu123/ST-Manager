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
import { EntryRegistry } from "./entryRegistry.js";
import { icon as buildIcon } from "./uiPrimitives.js";

export const SURFACE_TYPES = ["panel", "modal", "page", "sheet"];

/**
 * 表面尺寸档位（`spec.size`）。
 *
 * **为什么需要它**：`modal` 早先用 `max-height` + 内容自适应高度，插件切换页签时
 * 内容长度变化 → 弹层高度跟着跳，看起来像「窗口在自己缩放」。给一个**固定尺寸**
 * 档位让容器在打开期间恒定，切换页签只换内部内容。
 *
 * `md` 是默认档；`lg` 对应旧版插件自绘 shell 的 `min(1080px, 94vw) × min(760px, 90vh)`。
 */
export const SURFACE_SIZES = ["sm", "md", "lg", "xl"];
const DEFAULT_SURFACE_SIZE = "md";

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
      // 尺寸档位（仅对 modal 生效）：让容器在打开期间保持恒定高度。
      size: SURFACE_SIZES.includes(String(spec.size || ""))
        ? String(spec.size)
        : DEFAULT_SURFACE_SIZE,
      // 头部图标：宿主图标名，或插件内资源路径（需 `pluginId` 才能解析）。
      // 传入后标题栏左侧渲染一个图标位——与主程序模态框（`.ui-modal-header-icon`）
      // 的设计元素对齐，插件不必自绘标题。
      icon: String(spec.icon || ""),
      // 头部副标题（主程序模态框的 `.ui-modal-eyebrow` / description 位）。
      description: String(spec.description || ""),
      // 头部附加槽：宿主在「标题块」与「关闭按钮」之间留一个空容器，
      // 调用 `headerExtra(container)` 让插件把自己的状态胶囊放进去。
      // 这样插件的状态信息与宿主标题处于**同一行**，不必自绘第二条状态栏。
      headerExtra: typeof spec.headerExtra === "function" ? spec.headerExtra : null,
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
   *
   * surface **已经打开**时不再 `mount`（那会重建 DOM、丢掉用户已填的表单），
   * 但**仍然把新的 `ctx` 交给 `onOpen`**：同一个 surface 常被多个入口复用
   * （本插件的 `workbench` 就同时服务坞、右键分类、批量菜单、设置四个入口），
   * 第二次点击带的是**不同的作用域**，插件必须有机会据此更新视图，
   * 否则「先右键 A 分类、再右键 B 分类」会一直显示 A 的结果。
   */
  openSurface(key, ctx = {}) {
    const record = this.surfaces.get(String(key || ""));
    if (!record) {
      console.warn(`[surfaceHost] 未注册的 surface: ${key}`);
      return null;
    }
    if (this.open.has(record.key)) {
      // 复用既有容器；把新 ctx 重新投递给插件（这是入口切换作用域的唯一通道）
      if (record.onOpen) {
        try {
          record.onOpen({ ...ctx, pluginId: record.pluginId });
        } catch (error) {
          console.error(`[surfaceHost] 插件 ${record.pluginId} 的 onOpen 失败:`, error);
        }
      }
      return this.open.get(record.key).container;
    }

    const root = ensureSurfaceRoot();
    const shell = document.createElement("div");
    shell.className = SURFACE_CLASSES[record.type] || SURFACE_CLASSES.panel;
    shell.dataset.plugin = record.pluginId;
    shell.dataset.surface = record.id;
    shell.dataset.surfaceType = record.type;
    // 尺寸档位落到 `data-size`，由 CSS 决定具体宽高（modal 用固定高度）。
    shell.dataset.surfaceSize = record.size;
    // 框选（marqueeSelection）不命中坞与浮层
    shell.dataset.marqueeIgnore = "true";
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-modal", "true");
    shell.setAttribute("aria-label", record.title);

    const header = document.createElement("header");
    header.className = "plugin-surface__header";

    // 标题块：图标 + （可选副标题 + 标题）。
    // 与主程序模态框的 `.ui-modal-header-copy` / `.ui-modal-header-icon` /
    // `.ui-modal-eyebrow` 同一套设计元素，让插件弹层与宿主弹层观感一致。
    const headerCopy = document.createElement("div");
    headerCopy.className = "plugin-surface__header-copy";

    if (record.icon) {
      const iconSlot = document.createElement("span");
      iconSlot.className = "plugin-surface__header-icon";
      iconSlot.setAttribute("aria-hidden", "true");
      iconSlot.appendChild(buildIcon(record.icon, {
        className: "ui-icon--md",
        pluginId: record.pluginId,
      }));
      headerCopy.appendChild(iconSlot);
    }

    const titleBlock = document.createElement("div");
    titleBlock.className = "plugin-surface__title-block";

    if (record.description) {
      const eyebrow = document.createElement("p");
      eyebrow.className = "plugin-surface__eyebrow";
      eyebrow.textContent = record.description;
      titleBlock.appendChild(eyebrow);
    }

    const title = document.createElement("h2");
    title.className = "plugin-surface__title";
    title.textContent = record.title;
    titleBlock.appendChild(title);

    headerCopy.appendChild(titleBlock);
    header.appendChild(headerCopy);

    // 头部附加槽（`spec.headerExtra`）：插件把状态胶囊放进宿主标题行，
    // 与主程序「标题 + 状态」同行的做法一致，插件不必自绘第二条状态栏。
    const headerExtra = document.createElement("div");
    headerExtra.className = "plugin-surface__header-extra";
    if (record.headerExtra) {
      try {
        record.headerExtra(headerExtra);
      } catch (error) {
        console.error(
          `[surfaceHost] 插件 ${record.pluginId} 的 headerExtra 失败:`, error,
        );
      }
    }
    header.appendChild(headerExtra);

    // 关闭按钮：用宿主的通用关闭图标（与设置弹窗、详情页一致），
    // 而不是文字「×」——文字字形随字体变化，且与主程序图标体系不一致。
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "plugin-surface__close";
    closeButton.setAttribute("aria-label", "关闭");
    closeButton.setAttribute("title", "关闭");
    closeButton.appendChild(buildIcon("close", { className: "ui-icon--md" }));
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
        // 右键目标（只有 `source === "context"` 会带）：插件据此知道作用域是
        // 整个分类还是单张卡片。`targetPath` 为 `""` 表示根目录，是**合法值**，
        // 因此不能用真值判断来区分「没有目标」——`targetKind` 才是存在性标志。
        targetKind: String(ctx.targetKind || ""),
        targetPath: String(ctx.targetPath == null ? "" : ctx.targetPath),
        // 目标 id 列表（批量入口传选中集，右键卡片传那一张，其余为空数组）。
        // 有了它，插件不必再去读宿主的 `viewState.selectedIds`（Provisional 耦合）。
        targetIds: Array.isArray(ctx.targetIds) ? ctx.targetIds.map(String) : [],
        pluginId: record.pluginId,
        surfaceId: record.id,
      });
      // mount 返回函数时，宿主在关闭时调用它（D8 契约）
      if (typeof returned === "function") state.disposer = returned;
      if (record.onOpen) record.onOpen({ ...ctx, pluginId: record.pluginId });
    } catch (error) {
      console.error(`[surfaceHost] 插件 ${record.pluginId} 的 surface ${record.id} 挂载失败:`, error);
      this.close(record.key);
      this._markEntryError(record, ctx, error);
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

  /**
   * `mount()` 抛错时把对应入口置错误态（设计文档 8.3：失败被隔离在单个插件内）。
   *
   * 错误要反映到**入口**上，用户才能看见「这个插件的面板坏了」而不是点了没反应。
   * 入口 id 从 `ctx.targetId` 取（坞 / 命令面板都会传）；取不到时按 surfaceId 兜底
   * ——多数插件让 `surface.id === entry.id`。
   */
  _markEntryError(record, ctx, error) {
    const entryId = String((ctx && ctx.targetId) || record.id || "");
    if (!entryId) return;
    try {
      EntryRegistry.setStatus(record.pluginId, entryId, "error");
    } catch (exc) {
      // 注册表还没建表（插件在 setPlugins 之前挂载）时忽略：不影响错误上报本身
      console.warn("[surfaceHost] 标记入口错误态失败:", exc);
    }
    console.error(
      `[surfaceHost] 入口 ${record.pluginId}:${entryId} 已置错误态：`,
      String(error),
    );
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
