/**
 * static/js/pluginOverlayHost.js
 * 插件浮层登记（设计文档 §6.3 / §7.3；实现日志 S6，ADR-0007 / 0016）。
 *
 * 自绘插件可以自己定位、自己控制层级（ADR-0001）；宿主**不接管**浮层，只提供
 * 可选的**最小协调**：
 * - `modal: true` 的已登记浮层参与 ESC 关闭（只关最上层）与焦点归还；
 * - `layer` 只作建议值（调试展示 / 遮挡提示），不改插件元素的 `z-index`；
 * - kill switch：`closeAllPlugins()` / `killSwitch()` 逐个调用 `onDismiss`
 *   并广播 `overlays:force-closed`（`detail = {pluginId}`），由插件清理状态。
 *
 * 未登记的浮层宿主不干预，只能靠清 root（`pluginRootHost`）回收。
 */

/** `layer` 建议值（设计 §7.1）。 */
export const OVERLAY_LAYERS = [
  "content",
  "ambient",
  "surface",
  "dock",
  "popover",
  "tooltip",
  "alert",
];

/** 缺省层级。 */
export const DEFAULT_OVERLAY_LAYER = "popover";

/** kill switch 广播事件名。 */
export const OVERLAYS_FORCE_CLOSED_EVENT = "overlays:force-closed";

/** 运行期异常上报事件名（pluginHost 据此做降级计数）。 */
const RUNTIME_ERROR_EVENT = "plugin:runtime-error";

/** 派发运行期异常（宿主捕获但要让管理器做降级计数）。 */
function reportRuntimeError(pluginId, error, source) {
  console.error(`[pluginOverlayHost] 插件 ${pluginId} 的 ${source} 回调抛错:`, error);
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  try {
    window.dispatchEvent(
      new CustomEvent(RUNTIME_ERROR_EVENT, {
        detail: { pluginId: String(pluginId || ""), error, source },
      }),
    );
  } catch (reportError) {
    console.warn("[pluginOverlayHost] 上报运行期异常失败:", reportError);
  }
}

export const PluginOverlayHost = {
  initialized: false,
  /** 全局键 `<pluginId>:<id>` → 浮层登记记录。 */
  overlays: new Map(),
  /** 登记顺序（越大越上层；ESC 只关最上层 modal）。 */
  _sequence: 0,

  /** 幂等初始化：安装 ESC 监听（捕获阶段，先于宿主其它 ESC 处理）。 */
  init() {
    if (this.initialized) return this;
    this.initialized = true;
    if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
      document.addEventListener("keydown", (event) => this.handleKeydown(event), true);
    }
    return this;
  },

  _key(pluginId, id) {
    return `${String(pluginId || "")}:${String(id || "")}`;
  },

  /**
   * 登记一个浮层。
   *
   * @param {string} pluginId 插件 id
   * @param {{id: string, element: object, layer?: string, modal?: boolean,
   *          label?: string, onDismiss?: Function}} spec
   * @returns {Function} 取消登记函数（重复登记同 id 时先撤销旧登记）
   */
  register(pluginId, spec = {}) {
    const plugin = String(pluginId || "").trim();
    const id = String((spec && spec.id) || "").trim();
    if (!plugin || !id) {
      console.warn("[pluginOverlayHost] register 需要非空的 pluginId 与 spec.id");
      return () => {};
    }
    const element = spec && spec.element;
    if (!element || typeof element !== "object") {
      console.warn(`[pluginOverlayHost] 插件 ${plugin} 的浮层 ${id} 缺少 element，已忽略`);
      return () => {};
    }

    const key = this._key(plugin, id);
    // 同 id 重复登记 = 覆盖：先摘掉旧记录，避免同一浮层被登记两次。
    if (this.overlays.has(key)) this.unregister(plugin, id);

    this._sequence += 1;
    const layer = OVERLAY_LAYERS.includes(String((spec && spec.layer) || ""))
      ? String(spec.layer)
      : DEFAULT_OVERLAY_LAYER;
    this.overlays.set(key, {
      key,
      pluginId: plugin,
      id,
      element,
      layer,
      modal: Boolean(spec && spec.modal),
      label: String((spec && spec.label) || ""),
      onDismiss: spec && typeof spec.onDismiss === "function" ? spec.onDismiss : null,
      sequence: this._sequence,
      // 打开前的焦点元素：ESC 关闭后归还（设计 §6.3）。
      previousFocus:
        typeof document !== "undefined" && document.activeElement ? document.activeElement : null,
    });

    return () => this.unregister(plugin, id);
  },

  /** 取消登记；返回是否确实移除了记录。 */
  unregister(pluginId, id) {
    const key = this._key(pluginId, id);
    const record = this.overlays.get(key);
    if (!record) return false;
    this.overlays.delete(key);
    return true;
  },

  /**
   * 已登记浮层元数据（**不含 DOM 引用**与回调；按登记顺序返回）。
   *
   * @param {string} [pluginId] 只列某个插件；省略 = 全部插件
   */
  list(pluginId = "") {
    const plugin = String(pluginId || "");
    return Array.from(this.overlays.values())
      .filter((record) => !plugin || record.pluginId === plugin)
      .sort((left, right) => left.sequence - right.sequence)
      .map((record) => ({
        key: record.key,
        id: record.id,
        pluginId: record.pluginId,
        layer: record.layer,
        modal: record.modal,
        label: record.label,
      }));
  },

  /** 取一条登记记录（宿主内部 / 测试用；含 element 与回调）。 */
  get(pluginId, id) {
    return this.overlays.get(this._key(pluginId, id)) || null;
  },

  /** 该插件已登记浮层数量。 */
  count(pluginId = "") {
    return this.list(pluginId).length;
  },

  /** 当前有登记浮层的插件 id。 */
  pluginIds() {
    return Array.from(new Set(Array.from(this.overlays.values()).map((record) => record.pluginId)));
  },

  /**
   * 关闭某个插件的全部已登记浮层（按登记顺序倒序，逐个调用 `onDismiss`）。
   *
   * 回调异常被捕获并上报（插件标记降级），不扩散到其他插件。
   * 宿主不直接移除插件 DOM——那是 pluginHost 清 root 的职责。
   *
   * @returns {number} 关闭数量
   */
  closeAll(pluginId) {
    const plugin = String(pluginId || "");
    const records = Array.from(this.overlays.values())
      .filter((record) => record.pluginId === plugin)
      .sort((left, right) => right.sequence - left.sequence);

    let closed = 0;
    for (const record of records) {
      if (record.onDismiss) {
        try {
          record.onDismiss();
        } catch (error) {
          reportRuntimeError(record.pluginId, error, "overlay.onDismiss");
        }
      }
      this.overlays.delete(record.key);
      if (record.modal) this._restoreFocus(record);
      closed += 1;
    }
    return closed;
  },

  /** 关闭全部插件的已登记浮层；返回涉及的插件 id 数组。 */
  closeAllPlugins() {
    const pluginIds = this.pluginIds();
    for (const pluginId of pluginIds) this.closeAll(pluginId);
    return pluginIds;
  },

  /**
   * kill switch 的浮层部分：逐个插件 ①关闭全部已登记浮层 ②广播
   * `overlays:force-closed`。root 清理由 `pluginHost.killSwitch()` 接着做。
   *
   * @param {string[]} [pluginIds] 指定插件；省略 = 当前有浮层的插件
   * @returns {string[]} 处理过的插件 id
   */
  killSwitch(pluginIds = null) {
    const ids = Array.isArray(pluginIds) ? pluginIds.map(String) : this.pluginIds();
    for (const pluginId of ids) {
      this.closeAll(pluginId);
      this._broadcastForceClosed(pluginId);
    }
    return ids;
  },

  _broadcastForceClosed(pluginId) {
    if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
    try {
      window.dispatchEvent(
        new CustomEvent(OVERLAYS_FORCE_CLOSED_EVENT, {
          detail: { pluginId: String(pluginId || "") },
        }),
      );
    } catch (error) {
      console.warn("[pluginOverlayHost] 广播 overlays:force-closed 失败:", error);
    }
  },

  /** 当前最上层的 `modal: true` 浮层（没有则 null）。 */
  topMostModal() {
    let top = null;
    for (const record of this.overlays.values()) {
      if (!record.modal) continue;
      if (!top || record.sequence > top.sequence) top = record;
    }
    return top;
  },

  /**
   * ESC 处理：只关**最上层** `modal: true` 的已登记浮层，并归还焦点。
   *
   * 返回是否处理了该按键（true 时事件已被 `preventDefault`/`stopImmediatePropagation`，
   * 避免同一次 ESC 又去关宿主 surface）。
   */
  handleKeydown(event) {
    if (!event || event.key !== "Escape") return false;
    const record = this.topMostModal();
    if (!record) return false;

    if (typeof event.preventDefault === "function") event.preventDefault();
    if (typeof event.stopImmediatePropagation === "function") {
      event.stopImmediatePropagation();
    } else if (typeof event.stopPropagation === "function") {
      event.stopPropagation();
    }

    if (record.onDismiss) {
      try {
        record.onDismiss();
      } catch (error) {
        reportRuntimeError(record.pluginId, error, "overlay.onDismiss");
      }
    }
    this.overlays.delete(record.key);
    this._restoreFocus(record);
    return true;
  },

  /** 焦点归还给打开前的元素（元素已从 DOM 移除时静默跳过）。 */
  _restoreFocus(record) {
    const target = record && record.previousFocus;
    if (!target || typeof target.focus !== "function") return false;
    if (typeof document !== "undefined" && typeof document.contains === "function") {
      try {
        if (!document.contains(target)) return false;
      } catch (error) {
        // 自定义垫片 / 特殊元素取不到 contains 时按「仍在文档中」处理
      }
    }
    try {
      target.focus();
      return true;
    } catch (error) {
      console.warn("[pluginOverlayHost] 焦点归还失败:", error);
      return false;
    }
  },

  /** 静默清掉某个插件的登记（插件停用 / 卸载时 DOM 已由宿主整体移除）。 */
  clearPlugin(pluginId) {
    const plugin = String(pluginId || "");
    let removed = 0;
    for (const [key, record] of Array.from(this.overlays.entries())) {
      if (record.pluginId !== plugin) continue;
      this.overlays.delete(key);
      removed += 1;
    }
    return removed;
  },
};

export default PluginOverlayHost;
