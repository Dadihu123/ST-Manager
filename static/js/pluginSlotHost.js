/**
 * static/js/pluginSlotHost.js
 * 插槽宿主（设计文档 §4.5 / §5.2；实现日志 S5 / S7）。
 *
 * 宿主模板在插槽位置放一个**空容器**：
 *
 *   <div data-plugin-slot="settings.section"></div>
 *
 * 本模块扫描这些锚点，对每个命中的贡献建立包装节点（带 `data-plugin` 与
 * `data-slot`），动态 import 插件渲染器并调用 `mount(container, ctx) -> cleanup`。
 *
 * 宿主保证：
 * - 容器由宿主创建、定位、滚动与回收；插件不得在容器或祖先上设 position/z-index/inset；
 * - 卸载时先调用渲染器返回的清理函数，再移除包装节点；
 * - 渲染器抛错被捕获 → 该插槽显示错误占位 + 插件标记降级，不影响其他插件。
 *
 * 刷新时机：`contributions:changed` / `mode-changed` / `plugins:loaded` /
 * `plugin:unloaded`（整体刷新：先全量清理，再重新扫描锚点）。
 *
 * 服务注入：本模块不 import `pluginHost.js`（避免循环），模块加载与 `api` 由
 * pluginHost 在 `init()` 时通过 `configure({ loadModule, getApi })` 注入；
 * app.js 可以无参 `PluginSlotHost.init()`（幂等），服务稍后注入仍然生效。
 */

import { ContributionRegistry } from "./contributionRegistry.js";

/** 模板锚点属性名。 */
export const SLOT_ANCHOR_ATTRIBUTE = "data-plugin-slot";

/** 包装节点类名。 */
export const SLOT_WRAPPER_CLASS = "plugin-slot";

/** 错误占位类名（frontend-render 的 CSS 按此写样式）。 */
export const SLOT_ERROR_CLASS = "plugin-slot__error";

/** 渲染失败占位文案。 */
export const SLOT_ERROR_TEXT = "插件内容加载失败";

/** 会触发整体刷新的事件。 */
export const SLOT_REFRESH_EVENTS = [
  "contributions:changed",
  "mode-changed",
  "plugins:loaded",
  "plugin:unloaded",
];

/** 运行期异常上报事件名（pluginHost 据此做降级计数）。 */
const RUNTIME_ERROR_EVENT = "plugin:runtime-error";

/** 派发运行期异常（宿主捕获但要让管理器做降级计数）。 */
function reportRuntimeError(pluginId, error, source, extra = {}) {
  console.error(`[pluginSlotHost] 插件 ${pluginId} 的 ${source} 抛错:`, error);
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  try {
    window.dispatchEvent(
      new CustomEvent(RUNTIME_ERROR_EVENT, {
        detail: { pluginId: String(pluginId || ""), error, source, ...extra },
      }),
    );
  } catch (reportError) {
    console.warn("[pluginSlotHost] 上报运行期异常失败:", reportError);
  }
}

export const PluginSlotHost = {
  initialized: false,
  /** 已挂载条目：`{anchor, wrapper, record, cleanup}`。 */
  mounted: [],
  /** 注入的服务（pluginHost 提供；缺省时 refresh 会跳过挂载并警告）。 */
  services: {
    loadModule: null,
    getApi: null,
    getTarget: null,
  },
  _pendingRefresh: false,

  /**
   * 幂等初始化：安装刷新事件监听。
   *
   * @param {{loadModule?: Function, getApi?: Function, getTarget?: Function}} [options]
   */
  init(options = {}) {
    this.configure(options);
    if (this.initialized) return this;
    this.initialized = true;

    if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
      for (const name of SLOT_REFRESH_EVENTS) {
        window.addEventListener(name, () => this.scheduleRefresh());
      }
    }
    return this;
  },

  /** 注入 / 更新服务（重复调用只覆盖给出的字段）。 */
  configure(options = {}) {
    if (typeof options.loadModule === "function") this.services.loadModule = options.loadModule;
    if (typeof options.getApi === "function") this.services.getApi = options.getApi;
    if (typeof options.getTarget === "function") this.services.getTarget = options.getTarget;
    return this;
  },

  /** 事件驱动的刷新：合并到微任务，避免一次变更里重复全量扫描。 */
  scheduleRefresh() {
    if (this._pendingRefresh) return;
    this._pendingRefresh = true;
    const run = () => {
      this._pendingRefresh = false;
      this.refresh().catch((error) => {
        console.warn("[pluginSlotHost] 刷新失败:", error);
      });
    };
    if (typeof queueMicrotask === "function") queueMicrotask(run);
    else if (typeof setTimeout === "function") setTimeout(run, 0);
    else run();
  },

  /**
   * 整体刷新：清理全部已挂载包装，然后重新扫描锚点并挂载当前可执行贡献。
   *
   * @returns {Promise<Array>} 已挂载条目快照
   */
  async refresh() {
    this._teardownAll();
    if (typeof document === "undefined" || typeof document.querySelectorAll !== "function") {
      return this.mountedEntries();
    }

    let anchors = [];
    try {
      anchors = Array.from(document.querySelectorAll(`[${SLOT_ANCHOR_ATTRIBUTE}]`) || []);
    } catch (error) {
      console.warn("[pluginSlotHost] 扫描插槽锚点失败:", error);
      return this.mountedEntries();
    }

    const jobs = [];
    for (const anchor of anchors) {
      const slotName = String(anchor.getAttribute(SLOT_ANCHOR_ATTRIBUTE) || "").trim();
      if (!slotName) continue;
      const records = ContributionRegistry.slotRecords(slotName);
      for (const record of records) {
        // `when` 不满足的插槽不挂载（插槽不是菜单项，没有「置灰」形态）。
        if (!record.ok || record.enabled === false) continue;
        jobs.push(this._mount(anchor, record));
      }
    }
    await Promise.all(jobs);
    return this.mountedEntries();
  },

  /** `refresh` 的别名（frontend-render 在 app.js 里用这个名字）。 */
  refreshAll() {
    return this.refresh();
  },

  /** 清理并移除所有已挂载条目。 */
  _teardownAll() {
    const entries = this.mounted.splice(0, this.mounted.length);
    for (const entry of entries) {
      this._teardown(entry);
    }
  },

  _teardown(entry) {
    if (!entry) return;
    if (typeof entry.cleanup === "function") {
      try {
        entry.cleanup();
      } catch (error) {
        reportRuntimeError(entry.record.pluginId, error, "slot.cleanup", {
          slot: entry.record.slot,
        });
      }
    }
    entry.cleanup = null;
    const wrapper = entry.wrapper;
    if (wrapper && wrapper.parentNode) {
      try {
        wrapper.parentNode.removeChild(wrapper);
      } catch (error) {
        console.warn("[pluginSlotHost] 移除插槽包装失败:", error);
      }
    }
  },

  /** 创建一个贡献的包装节点并挂到锚点下。 */
  _createWrapper(anchor, record) {
    const wrapper = document.createElement("div");
    wrapper.className = SLOT_WRAPPER_CLASS;
    wrapper.dataset.plugin = record.pluginId;
    wrapper.dataset.slot = record.slot;
    wrapper.dataset.contributionId = record.id;
    anchor.appendChild(wrapper);
    return wrapper;
  },

  /** 挂载单个插槽贡献；渲染器异常 → 错误占位 + 上报（不抛出）。 */
  async _mount(anchor, record) {
    const wrapper = this._createWrapper(anchor, record);
    const entry = { anchor, wrapper, record, cleanup: null };
    this.mounted.push(entry);

    try {
      const loader = this.services.loadModule;
      if (typeof loader !== "function") {
        throw new Error("PluginSlotHost 尚未注入模块加载器");
      }
      const module = await loader(record.pluginId, record.module, record);
      const renderer = module ? module[record.export] : null;
      if (typeof renderer !== "function") {
        throw new Error(`插槽渲染器导出不存在或不是函数: ${record.export}`);
      }

      const api = typeof this.services.getApi === "function"
        ? this.services.getApi(record.pluginId)
        : null;
      // 前端激活失败的插件不挂插槽（激活期已由 pluginHost 预检过 module/export）。
      if (typeof this.services.getApi === "function" && !api) {
        const index = this.mounted.indexOf(entry);
        if (index >= 0) this.mounted.splice(index, 1);
        this._teardown(entry);
        return;
      }

      const ctx = this._buildContext(anchor, record, api);
      const cleanup = await renderer(wrapper, ctx);
      if (typeof cleanup === "function") entry.cleanup = cleanup;
    } catch (error) {
      this._renderErrorPlaceholder(wrapper, record);
      reportRuntimeError(record.pluginId, error, "slot.renderer", { slot: record.slot });
    }
    return entry;
  },

  /** 构造渲染器 ctx：`{api, pluginId, slot, mode, target, selection}`。 */
  _buildContext(anchor, record, api) {
    const context = ContributionRegistry.context();
    const store = (() => {
      if (typeof window === "undefined") return null;
      const alpine = window.Alpine || window.__ALPINE__;
      return alpine && typeof alpine.store === "function" ? alpine.store("global") : null;
    })();
    const viewState = (store && store.viewState) || {};
    const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];

    let target = null;
    if (typeof this.services.getTarget === "function") {
      try {
        target = this.services.getTarget(anchor, record) || null;
      } catch (error) {
        console.warn("[pluginSlotHost] getTarget 抛错:", error);
        target = null;
      }
    } else if (anchor && anchor.dataset && anchor.dataset.targetId) {
      target = {
        type: String(anchor.dataset.targetType || "card"),
        id: String(anchor.dataset.targetId),
      };
    }

    return {
      api,
      pluginId: record.pluginId,
      slot: record.slot,
      mode: context.mode,
      target,
      selection: {
        mode: context.mode,
        ids: ids.map((item) => String(item || "")).filter(Boolean),
      },
    };
  },

  /** 渲染错误占位（带 `data-plugin-error`，CSS 由 `.plugin-slot__error` 承担）。 */
  _renderErrorPlaceholder(wrapper, record) {
    if (!wrapper) return;
    wrapper.classList.add("is-error");
    const placeholder = document.createElement("div");
    placeholder.className = SLOT_ERROR_CLASS;
    placeholder.dataset.pluginError = "1";
    placeholder.setAttribute("role", "alert");
    placeholder.textContent = SLOT_ERROR_TEXT;
    try {
      wrapper.appendChild(placeholder);
    } catch (error) {
      console.warn("[pluginSlotHost] 渲染错误占位失败:", error);
    }
    // 记录在渲染器失败的条目上，便于调试面板展示。
    record.status = "error";
  },

  /** 清理某个插件的全部插槽挂载（plugin:unloaded / destroy 用）。 */
  clearPlugin(pluginId) {
    const plugin = String(pluginId || "");
    const kept = [];
    let removed = 0;
    for (const entry of this.mounted) {
      if (entry.record.pluginId !== plugin) {
        kept.push(entry);
        continue;
      }
      this._teardown(entry);
      removed += 1;
    }
    this.mounted = kept;
    return removed;
  },

  /** 已挂载条目快照（测试 / 调试面板用）。 */
  mountedEntries() {
    return this.mounted.map((entry) => ({
      pluginId: entry.record.pluginId,
      slot: entry.record.slot,
      id: entry.record.id,
      anchor: entry.anchor,
      wrapper: entry.wrapper,
    }));
  },

  /** 清理全部（测试 / 宿主销毁）。 */
  reset() {
    this._teardownAll();
    this._pendingRefresh = false;
    return true;
  },
};

export default PluginSlotHost;
