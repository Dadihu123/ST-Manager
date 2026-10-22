/**
 * static/js/pluginRootHost.js
 * 插件根节点宿主（设计文档 §6.2 / §7.3；实现日志 S6）。
 *
 * 自绘模式放开后，宿主仍要保证「禁用 / 卸载 / 崩溃 / kill switch 后屏幕可恢复」
 * （ADR-0006）：插件所有 DOM 都必须挂在宿主分配的根节点之下。
 *
 * 两个层都是 `document.body` 的直接子元素、`position:fixed; inset:0;
 * pointer-events:none`：
 * - 内容层（默认）：位于宿主内容之上、宿主模态之下；
 * - portal 层：位于宿主模态之上、宿主提示/告警之下，用于绕开
 *   `backdrop-filter` / `transform` 造成的包含块与层叠上下文陷阱。
 *
 * `api.createRoot(tag)` / `api.createRoot({ portal: true })` /
 * `api.createRoot({ tag: "button" })` 都走 `PluginRootHost.create()`。
 */

/** 内容层元素 id（CSS 与调试面板按 id 定位）。 */
export const PLUGIN_CONTENT_LAYER_ID = "plugin-layer-content";

/** portal 层元素 id。 */
export const PLUGIN_PORTAL_LAYER_ID = "plugin-layer-portal";

/** 层元素类名（`plugin-layers.css` 提供层级与定位）。 */
export const PLUGIN_LAYER_CLASS = "plugin-layer";

/** 根节点类名。 */
export const PLUGIN_ROOT_CLASS = "plugin-root";

/** 根节点与层元素共用的数据标记（`data-plugin`）。 */
export const PLUGIN_DATA_ATTRIBUTE = "data-plugin";

function reportError(error) {
  console.error("[pluginRootHost]", error);
}

export const PluginRootHost = {
  initialized: false,
  contentLayer: null,
  portalLayer: null,
  /** 插件 id → 该插件的根节点集合（宿主跟踪，kill switch / 停用时整体回收）。 */
  roots: new Map(),

  /** 幂等创建两个层。返回 `{content, portal}`；无 DOM 环境返回 null。 */
  ensureLayers() {
    if (typeof document === "undefined" || !document.body) return null;
    if (!this.contentLayer || !this.contentLayer.parentNode) {
      this.contentLayer = this._createLayer(PLUGIN_CONTENT_LAYER_ID, `${PLUGIN_LAYER_CLASS} plugin-layer--content`);
    }
    if (!this.portalLayer || !this.portalLayer.parentNode) {
      this.portalLayer = this._createLayer(PLUGIN_PORTAL_LAYER_ID, `${PLUGIN_LAYER_CLASS} plugin-layer--portal`);
    }
    this.initialized = true;
    return { content: this.contentLayer, portal: this.portalLayer };
  },

  _createLayer(id, className) {
    const layer = document.createElement("div");
    layer.id = id;
    layer.className = className;
    // 层本身不接收指针事件：插件只在自己的交互子元素上显式取回 pointer-events。
    layer.style.position = "fixed";
    layer.style.inset = "0";
    layer.style.pointerEvents = "none";
    document.body.appendChild(layer);
    return layer;
  },

  /** 取某个层的元素（`portal` 为 true 时返回 portal 层）。 */
  layer(portal = false) {
    const layers = this.ensureLayers();
    if (!layers) return null;
    return portal ? layers.portal : layers.content;
  },

  /**
   * 在宿主分配的层里创建一个根节点。
   *
   * @param {string} pluginId 插件 id
   * @param {{tag?: string, portal?: boolean}} options `tag` 默认 `div`
   * @returns {HTMLElement|null} 仍挂在 DOM 上的根节点（无 DOM 环境返回 null）
   */
  create(pluginId, options = {}) {
    const plugin = String(pluginId || "").trim();
    if (!plugin) return null;
    const tag = String((options && options.tag) || "div").trim() || "div";
    const portal = Boolean(options && options.portal);
    const parent = this.layer(portal);
    if (!parent) return null;

    const node = document.createElement(tag);
    node.classList.add(PLUGIN_ROOT_CLASS);
    node.classList.add(`plugin-${plugin}`);
    node.classList.add(portal ? "plugin-root--portal" : "plugin-root--content");
    node.dataset.plugin = plugin;
    node.dataset.pluginRoot = portal ? "portal" : "content";
    parent.appendChild(node);

    if (!this.roots.has(plugin)) this.roots.set(plugin, new Set());
    this.roots.get(plugin).add(node);
    return node;
  },

  /** 某个插件当前的全部根节点（快照）。 */
  getRoots(pluginId) {
    const set = this.roots.get(String(pluginId || ""));
    return set ? Array.from(set) : [];
  },

  /** 该插件是否有根节点。 */
  has(pluginId) {
    return this.getRoots(pluginId).length > 0;
  },

  /** 清空并移除某个插件的全部 root（内容层 + portal 层），返回移除数量。 */
  clear(pluginId) {
    const plugin = String(pluginId || "");
    const set = this.roots.get(plugin);
    if (!set || !set.size) {
      this.roots.delete(plugin);
      return 0;
    }
    let removed = 0;
    for (const node of set) {
      try {
        if (node.parentNode) node.parentNode.removeChild(node);
        else if (node.remove) node.remove();
        removed += 1;
      } catch (error) {
        reportError(error);
      }
    }
    this.roots.delete(plugin);
    return removed;
  },

  /** 清空全部插件的 root（宿主关闭 / 重置 / kill switch 全量路径）。 */
  clearAll() {
    const ids = Array.from(this.roots.keys());
    let removed = 0;
    for (const pluginId of ids) removed += this.clear(pluginId);
    return removed;
  },

  /** 当前有 root 的插件 id（kill switch 的插件集合来源之一）。 */
  pluginIds() {
    return Array.from(this.roots.keys()).filter((pluginId) => this.roots.get(pluginId).size > 0);
  },

  /** 移除层本身（仅测试 / 宿主销毁时使用；正常流程保留层）。 */
  reset() {
    for (const layer of [this.contentLayer, this.portalLayer]) {
      if (layer && layer.parentNode) layer.parentNode.removeChild(layer);
    }
    this.contentLayer = null;
    this.portalLayer = null;
    this.roots.clear();
    this.initialized = false;
    return true;
  },
};

export default PluginRootHost;
