/**
 * static/js/pluginHost.js
 * 前端插件运行时（设计文档第 8 部分 / 10.3 契约）。
 *
 * 职责：
 * 1. 拉取 `/api/plugins/list`，只加载「已启用且含前端入口」的插件。
 * 2. 注入插件样式（F11：未通过作用域检查的样式被拒绝加载）。
 * 3. 动态 `import()` 插件入口并调用 `activate(api)`。
 * 4. 构造并维护插件侧的 PluginAPI 门面。
 *
 * 硬约束：
 * - F1：`api()` 以 `data.success` 判断成败，绝不只看 `res.ok`。
 * - F11：样式作用域检查失败的条目直接跳过。
 * - F12：`api.createRoot()` 生成的容器自动带 `data-plugin="<id>"`。
 * - D8：API 命名统一到「名词命名空间」（`entries` / `surfaces` / `ui` / `storage` /
 *   `host`）；旧成员保留为别名并委托到新实现。
 * - D9.1：`activate()` 的返回值被记录为插件级 disposer，`destroy` 时调用。
 * - D9.2：`destroy()` 有真实调用方（入口注册表 / 表面宿主 / 卸载事件）。
 * - D11：插件资产 URL 追加 `?v=<插件版本>`，避免更新后浏览器复用旧 CSS/JS。
 */

import { parseSSEFrames, parseSSEPayload } from "./utils/sse.js";
// 这一行**保持单行原样**：`test_fullscreen_scrim_compositing_contracts.py` 的
// `test_plugin_host_exposes_the_scrim_contract` 断言的是它的**完整字面量**。
// 需要 import 同模块的第二个符号时另起一行，不要合并成多行解构。
import { setFullscreenScrim as applyFullscreenScrim } from "./utils/dom.js";
import { isFullscreenScrimActive } from "./utils/dom.js";
import { resolveIconUrl } from "./utils/icons.js";
import { EntryRegistry } from "./entryRegistry.js";
import { PluginSurfaceHost } from "./pluginSurfaceHost.js";
import { buildUiPrimitives } from "./uiPrimitives.js";

const PLUGIN_ROOT_ID = "plugin-host-root";
const PLUGIN_STORE_NAME = "global";
const CORE_EVENTS = new Set([
  "app.ready",
  "card.created",
  "card.updated",
  "card.deleted",
  "card.moved",
  "tag.applied",
  "tag.deleted",
  "worldbook.saved",
  "worldbook.entry_changed",
  "scan.completed",
  "index.job_done",
]);

const REFRESH_EVENTS = {
  cards: "refresh-card-list",
  worldinfo: "refresh-wi-list",
  wi: "refresh-wi-list",
  chats: "refresh-chat-list",
  presets: "refresh-preset-list",
  beautify: "refresh-beautify-list",
};

/** 视图模式 → 主程序 store 的取值（`api.host.switchMode`）。 */
const KNOWN_MODES = new Set([
  "cards",
  "worldinfo",
  "chats",
  "presets",
  "regex",
  "scripts",
  "quick_replies",
  "beautify",
]);

function scheduleIdle(callback) {
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(callback, { timeout: 2000 });
    return;
  }
  setTimeout(callback, 0);
}

function ensureRootNode() {
  let node = document.getElementById(PLUGIN_ROOT_ID);
  if (node) return node;

  node = document.createElement("div");
  node.id = PLUGIN_ROOT_ID;
  node.className = "plugin-host-root";
  node.setAttribute("aria-live", "off");
  document.body.appendChild(node);
  return node;
}

/**
 * D11：资产 URL 追加 `?v=<插件版本>`。
 *
 * ⚠️ **这个 `v=` 只对入口 URL 有效，不能当作「子模块也会随版本失效」的依据。**
 *
 * 后端 `core/plugins/assets.py` 现在下发 `Cache-Control: private, no-cache`
 * （必须先校验）。这里刻意记录曾经的错误假设，避免有人再改回强缓存：
 *
 * 早先后端发 `private, max-age=31536000, immutable`，理由是「URL 带 `?v=`，
 * 版本变化即 URL 变化」。但该理由**对 ES 模块的子导入不成立** ——
 * 查询串不会被相对 import 继承：
 *
 *     new URL('./panel.js', '.../plugin.js?v=0.1.0').href  →  '.../panel.js'
 *
 * 实测插件 6 个子模块（`panel.js` / `petview.js` / `announce.js` / `clock.js` /
 * `physics.js` / `statemachine.js`）的请求 URL 全都不带 `?v=`，恒定不变。
 * 于是 `immutable` 让它们永久缓存：改代码、**重装插件**、甚至硬刷新都可能
 * 仍执行旧模块（真实踩过：修好 bug 并重装插件，用户仍看到旧行为）。
 *
 * 因此 `v=` 的作用是「让入口多一条廉价回源路径」，**不是**强缓存的许可证。
 * 后端同时支持条件请求（`If-None-Match` → 304），内容未变时无响应体开销。
 */
function withAssetVersion(url, version) {
  const stamp = String(version || "").trim();
  if (!url || !stamp) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}v=${encodeURIComponent(stamp)}`;
}

function toAbsoluteAssetUrl(pluginId, relativePath, version = "") {
  const cleaned = String(relativePath || "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "");
  if (!cleaned) return "";
  const encoded = cleaned
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return withAssetVersion(
    `/api/plugins/${encodeURIComponent(pluginId)}/assets/${encoded}`,
    version,
  );
}

function injectStyle(pluginId, relativePath, version = "") {
  const url = toAbsoluteAssetUrl(pluginId, relativePath, version);
  if (!url) return false;

  const styleId = `plugin-style-${pluginId}-${String(relativePath).replace(/[^a-zA-Z0-9]+/g, "-")}`;
  if (document.getElementById(styleId)) return true;

  const link = document.createElement("link");
  link.id = styleId;
  link.rel = "stylesheet";
  link.href = url;
  link.dataset.plugin = pluginId;
  document.head.appendChild(link);
  return true;
}

/** 移除插件注入的样式（destroy 时调用，避免残留影响宿主）。 */
function removeInjectedStyles(pluginId) {
  const nodes = document.querySelectorAll(`link[data-plugin="${pluginId}"]`);
  for (const node of nodes) {
    if (node.parentNode) node.parentNode.removeChild(node);
  }
  return nodes.length;
}

/**
 * 核心事件的前端通路（设计文档 6.7.2）。
 *
 * **懒连接**：首次订阅核心事件时才建立 SSE；零订阅的插件不占连接配额。
 * **一条流服务一个插件的全部核心事件订阅**——`api.on()` 调 N 次也只有一个
 * `EventSource`，因为服务端配额按连接数计。
 *
 * 分派在**插件本地**完成（`listeners: Map<event, Set<handler>>`），因此
 * `?events=` 不需要随订阅变化重连：流一次订阅全部核心事件即可。
 */
const coreEventBridge = {
  /** pluginId → { source, listeners, stopped } */
  connections: new Map(),

  subscribe(pluginId, event, handler, own) {
    const key = String(pluginId);
    let conn = this.connections.get(key);
    if (!conn) {
      conn = { source: null, listeners: new Map(), stopped: false, polling: false };
      this.connections.set(key, conn);
      this._connect(key, conn);
      // 连接生命周期挂到插件 disposer，与 subscribeJob 完全同一个模式
      if (typeof own === "function") {
        own(() => this.close(key));
      }
    }

    if (!conn.listeners.has(event)) conn.listeners.set(event, new Set());
    conn.listeners.get(event).add(handler);

    return () => {
      const current = this.connections.get(key);
      if (!current) return;
      const bucket = current.listeners.get(event);
      if (bucket) {
        bucket.delete(handler);
        if (!bucket.size) current.listeners.delete(event);
      }
      // 零订阅 → 立刻释放连接（零订阅的插件不该占配额）
      if (!current.listeners.size) this.close(key);
    };
  },

  _connect(key, conn) {
    const url = "/api/plugins/events";
    const dispatch = (payload) => this._dispatch(key, conn, payload);

    if (typeof EventSource !== "function") {
      // 无 SSE 能力时不伪装成轮询：核心事件只有这一条通路，编造一个不存在的
      // 轮询端点只会让插件在 404 里静默失败。明确告警，让插件作者用
      // `when: { feature: ['hasSSE'] }` 门控（与作业流不同：作业还有可回看的表，
      // 核心事件是**广播**，没有历史可轮询）。
      console.warn(
        `[pluginHost] 当前环境不支持 EventSource，插件 ${key} 的 api.on(核心事件) 将收不到推送`,
      );
      return;
    }

    let source = null;
    try {
      source = new EventSource(url);
    } catch (error) {
      console.warn(`[pluginHost] 插件 ${key} 的核心事件流建立失败:`, error);
      return;
    }
    conn.source = source;

    source.addEventListener("core", (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        payload = null;
      }
      dispatch(payload);
    });

    let opened = false;
    source.addEventListener("open", () => {
      opened = true;
    });
    source.addEventListener("error", () => {
      if (conn.stopped) return;
      source.close();
      if (!opened) {
        console.warn(`[pluginHost] 插件 ${key} 的核心事件流不可用（连接被拒绝）`);
        return;
      }
      // 已连上过：让浏览器自动重连（EventSource 内置退避）。
      // 监听不随实例复用，因此重连后必须重新挂一次。
      try {
        const next = new EventSource(url);
        conn.source = next;
        this._wire(key, conn, next, dispatch);
      } catch (error) {
        console.warn(`[pluginHost] 插件 ${key} 的核心事件流重连失败:`, error);
      }
    });
  },

  /** 把帧派发给该插件在当前事件名上的全部监听器。 */
  _dispatch(key, conn, payload) {
    const name = String((payload && payload.event) || "");
    const bucket = conn.listeners.get(name);
    if (!bucket) return;
    for (const handler of Array.from(bucket)) {
      try {
        handler(payload ? payload.payload : null);
      } catch (error) {
        console.warn(`[pluginHost] 插件 ${key} 的 ${name} 处理器抛错:`, error);
      }
    }
  },

  /** 重连后重新挂监听。 */
  _wire(key, conn, source, dispatch) {
    source.addEventListener("core", (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        payload = null;
      }
      dispatch(payload);
    });
    source.addEventListener("error", () => {
      if (conn.stopped) return;
      source.close();
      try {
        const next = new EventSource("/api/plugins/events");
        conn.source = next;
        this._wire(key, conn, next, dispatch);
      } catch (error) {
        console.warn(`[pluginHost] 插件 ${key} 的核心事件流重连失败:`, error);
      }
    });
  },

  close(key) {
    const conn = this.connections.get(String(key));
    if (!conn) return false;
    conn.stopped = true;
    if (conn.source) conn.source.close();
    conn.source = null;
    conn.listeners.clear();
    this.connections.delete(String(key));
    return true;
  },

  closeAll() {
    for (const key of Array.from(this.connections.keys())) this.close(key);
  },
};

/**
 * 订阅一个核心事件。
 *
 * 每次订阅都先**清理该事件上的同名监听**：`api.on()` 的取消函数已经负责摘除，
 * 这里只保证 `Set<handler>` 的语义成立（同一个函数重复订阅只登记一次）。
 */
function subscribeCoreEvent(pluginId, event, handler) {
  return coreEventBridge.subscribe(
    pluginId,
    event,
    handler,
    (disposer) => PluginHost.addDisposer(pluginId, disposer),
  );
}

/**
 * 宿主状态广播（`api.host.onState`，设计文档 D6）。
 *
 * 插件要「与界面联动」（宠物随视图切换改变行为、忙时安静下来…），此前只能各自
 * 去读 `window.Alpine.store("global")` —— 那是 Provisional 耦合，宿主改字段名
 * 插件就静默失效。这里把宿主状态收成**一份**快照并去抖推送。
 *
 * 单一订阅源：内部只装一遍监听，多个插件的多个 handler 共用一次计算。
 */
const hostStateBroadcaster = {
  listeners: new Set(),
  watchersInstalled: false,
  mediaQuery: null,
  pending: false,
  last: null,

  subscribe(handler) {
    if (typeof handler !== "function") return () => {};
    this.listeners.add(handler);
    this.installWatchers();

    // 首次订阅**立即推一次快照**，插件不必自己先探一次。
    // 同时把它记为「已推送的最后值」，否则随后的第一次去抖 flush 会把同一份
    // 快照再推一遍（订阅后什么都没变，插件却收到两次回调）。
    let initial = null;
    try {
      initial = this.snapshot();
    } catch (error) {
      console.warn("[pluginHost] 读取宿主状态失败:", error);
    }
    if (initial) {
      this.last = JSON.stringify(initial);
      try {
        handler(initial);
      } catch (error) {
        console.warn("[pluginHost] 插件状态处理器抛错:", error);
      }
    }

    return () => {
      this.listeners.delete(handler);
    };
  },

  /** 采集当前快照。字段名以 `static/js/state.js` 为准（不猜）。 */
  snapshot() {
    const store = PluginHost.store || null;
    const batch = (store && store.batchProgress) || {};
    const index = (store && store.indexStatus) || {};

    // 忙碌 = 批处理在跑，或索引/扫描在建。两者都是既有状态，不新造一套。
    const busy =
      String(batch.status || "") === "running" ||
      String(index.state || "") === "building" ||
      Boolean(index.scan_active);

    return {
      mode: String((store && store.currentMode) || ""),
      deviceType: String((store && store.deviceType) || "desktop"),
      darkMode: store ? Boolean(store.isDarkMode) : false,
      scrimActive: Boolean(isFullscreenScrimActive()),
      surfaceOpen: PluginSurfaceHost.hasOpenSurface(),
      busy,
      reducedMotion: Boolean(this.mediaQuery && this.mediaQuery.matches),
      visible: typeof document !== "undefined" && document.visibilityState
        ? document.visibilityState === "visible"
        : true,
    };
  },

  /**
   * 合并去抖推送。
   *
   * 一次视图切换会同时改 `currentMode` 与多个无关字段；逐字段各推一次会让插件
   * 在一帧里收到十几个回调并重复重建 DOM。这里用 rAF（不可用时退 100ms 微批）
   * 合并成**一次**推送，并且只在快照真的变了才推。
   */
  schedule() {
    if (this.pending) return;
    this.pending = true;
    const flush = () => {
      this.pending = false;
      this.flush();
    };
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(flush);
      return;
    }
    setTimeout(flush, 100);
  },

  flush() {
    if (!this.listeners.size) return;
    let next = null;
    try {
      next = this.snapshot();
    } catch (error) {
      console.warn("[pluginHost] 读取宿主状态失败:", error);
      return;
    }

    const serialized = JSON.stringify(next);
    if (serialized === this.last) return;
    this.last = serialized;

    for (const handler of Array.from(this.listeners)) {
      try {
        handler(next);
      } catch (error) {
        console.warn("[pluginHost] 插件状态处理器抛错:", error);
      }
    }
  },

  installWatchers() {
    if (this.watchersInstalled) return;
    this.watchersInstalled = true;

    // `reducedMotion` **必须**监听 change：用户可以在系统设置里改，
    // 不改页面就变，只读一次会永远停在初始值。
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      try {
        this.mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
        const onChange = () => this.schedule();
        if (typeof this.mediaQuery.addEventListener === "function") {
          this.mediaQuery.addEventListener("change", onChange);
        } else if (typeof this.mediaQuery.addListener === "function") {
          // Safari < 14 的旧签名
          this.mediaQuery.addListener(onChange);
        }
      } catch (error) {
        console.warn("[pluginHost] reduced-motion 监听安装失败:", error);
      }
    }

    if (typeof window === "undefined") return;

    // 宿主内部的显式信号
    window.addEventListener("host:surface-state-changed", () => this.schedule());
    window.addEventListener("host:fullscreen-scrim-changed", () => this.schedule());
    window.addEventListener("entries:changed", () => this.schedule());
    ["mode-changed", "theme-mode-changed", "settings-saved"].forEach((name) => {
      window.addEventListener(name, () => this.schedule());
    });

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => this.schedule());
    }

    // 其余字段（`batchProgress` / `indexStatus` / `deviceType`）走 Alpine 响应式：
    // 它们有多个写入点，逐个补 dispatchEvent 迟早漏一个（`entryRegistry` 对
    // `viewState.selectedIds` 用了同一个判断与同一个做法）。
    const installAlpineWatcher = () => {
      const alpine = window.Alpine;
      if (!alpine || typeof alpine.effect !== "function") return false;
      try {
        alpine.effect(() => {
          const store = PluginHost.store;
          if (!store) return;
          // 只为建立依赖：读到的值不影响计算，变化时靠 schedule() 去抖合并
          void String(store.currentMode || "");
          void String(store.deviceType || "");
          void Boolean(store.isDarkMode);
          void String((store.batchProgress || {}).status || "");
          void Number((store.batchProgress || {}).current || 0);
          void String((store.indexStatus || {}).state || "");
          void Boolean((store.indexStatus || {}).scan_active);
          this.schedule();
        });
        return true;
      } catch (error) {
        console.warn("[pluginHost] 宿主状态监听安装失败:", error);
        return false;
      }
    };

    if (!installAlpineWatcher()) {
      if (typeof document !== "undefined" && document.addEventListener) {
        document.addEventListener("alpine:initialized", () => {
          installAlpineWatcher();
        });
      }
    }
  },
};



export const PluginHost = {
  initialized: false,
  loading: false,
  root: null,
  loaded: new Map(),
  failed: new Map(),
  /** 插件 id → 该插件的 disposer 列表（activate 返回值 + 内部注册的清理函数） */
  disposers: new Map(),

  /** 主程序 store（`Alpine.store("global")`）。宿主内部与状态广播共用同一个取法。 */
  get store() {
    const alpine = window.Alpine || window.__ALPINE__;
    if (alpine && typeof alpine.store === "function") {
      return alpine.store(PLUGIN_STORE_NAME) || null;
    }
    return null;
  },

  init() {
    if (this.initialized) return;
    this.initialized = true;
    this.root = ensureRootNode();

    EntryRegistry.init();
    PluginSurfaceHost.init();

    // 插件被禁用 / 卸载时，宿主**强制**回收其运行时资源（D8 契约）
    window.addEventListener("plugin:unloaded", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) this.destroy(String(detail.pluginId));
    });

    // 懒加载：首屏渲染完成后（或空闲时）再拉取插件，避免拖慢首屏。
    scheduleIdle(() => {
      this.loadAll().catch((error) => {
        console.warn("[pluginHost] 插件加载失败:", error);
      });
    });
  },

  async loadAll() {
    if (this.loading) return;
    this.loading = true;

    try {
      const data = await this.request("/api/plugins/list");
      if (!data || data.success !== true) {
        console.warn("[pluginHost] 插件列表读取失败:", data && data.msg);
        return;
      }

      const items = Array.isArray(data.items) ? data.items : [];
      for (const entry of items) {
        if (!entry || entry.enabled === false) continue;
        const manifest = entry.manifest || {};
        if (!manifest.frontend || !manifest.frontend_entry) continue;
        await this.loadPlugin(entry, manifest).catch((error) => {
          this.failed.set(entry.id, String(error));
          console.warn(`[pluginHost] 插件 ${entry.id} 加载失败:`, error);
        });
      }

      // 注册表从同一份列表快照建表（含只有 entries、没有前端入口的纯声明插件）
      EntryRegistry.setPlugins(items);

      window.dispatchEvent(
        new CustomEvent("plugins:loaded", {
          detail: {
            loaded: Array.from(this.loaded.keys()),
            failed: Array.from(this.failed.keys()),
          },
        }),
      );
    } finally {
      this.loading = false;
    }
  },

  async loadPlugin(entry, manifest) {
    const pluginId = entry.id;
    const version = String(manifest.version || "");

    const styleErrors = entry.style_scope_errors || {};
    for (const stylePath of manifest.frontend_styles || []) {
      if (styleErrors[stylePath]) {
        console.warn(
          `[pluginHost] 插件 ${pluginId} 的样式未通过作用域检查，已拒绝加载:`,
          stylePath,
        );
        continue;
      }
      injectStyle(pluginId, stylePath, version);
    }

    const entryUrl = toAbsoluteAssetUrl(pluginId, manifest.frontend_entry, version);
    if (!entryUrl) return;

    const module = await import(entryUrl);
    const api = this.buildApi(entry, manifest);
    const root = api.createRoot("div");
    root.classList.add(`plugin-${pluginId}`);

    // D9.1：activate() 的返回值可能是清理函数，记录下来在 destroy 时调用。
    // 此前这里直接丢弃返回值，插件无法在停用时回收定时器 / 事件监听。
    if (module && typeof module.activate === "function") {
      const disposer = await module.activate(api);
      if (typeof disposer === "function") {
        this.addDisposer(pluginId, disposer);
      } else if (disposer && typeof disposer.dispose === "function") {
        this.addDisposer(pluginId, () => disposer.dispose());
      }
    }

    this.loaded.set(pluginId, { entry, manifest, api, module, root });
    window.dispatchEvent(
      new CustomEvent(`plugin:${pluginId}:ready`, { detail: { id: pluginId } }),
    );
  },

  /** 登记一个插件级 disposer（activate 返回值 / api 内部注册）。 */
  addDisposer(pluginId, disposer) {
    if (typeof disposer !== "function") return false;
    const key = String(pluginId || "");
    if (!this.disposers.has(key)) this.disposers.set(key, []);
    this.disposers.get(key).push(disposer);
    return true;
  },

  buildApi(entry, manifest) {
    const pluginId = entry.id;
    const pluginVersion = String(manifest.version || "");
    const host = this;
    const storeRef = () => this.store;
    const state = window.Alpine && typeof window.Alpine.reactive === "function"
      ? window.Alpine.reactive({})
      : {};

    /** 记录一个需要随插件销毁而执行的清理函数。 */
    const own = (disposer) => {
      host.addDisposer(pluginId, disposer);
      return disposer;
    };

    // ---- 存储（api.storage.*，底层走 ui_data._plugins_v1.<id>.storage） ----
    // 本地缓存 + 异步落盘：`get` / `keys` 必须同步返回（插件常在渲染期调用），
    // 因此读一次到内存，写操作先改内存再提交后端。
    let storageCache = null;

    const loadStorage = async () => {
      if (storageCache) return storageCache;
      const data = await api.api('/storage');
      storageCache = data && data.success && data.storage ? data.storage : {};
      return storageCache;
    };

    const commitStorage = async (bucket) => {
      storageCache = bucket;
      const data = await api.api('/storage', { method: 'POST', body: { storage: bucket } });
      if (!data || !data.success) {
        console.warn(`[pluginHost] 插件 ${pluginId} 存储写入失败:`, data && data.msg);
        return false;
      }
      if (data.storage) storageCache = data.storage;
      return true;
    };

    // 启动时预热一次，让后续同步读有数据可用
    own(() => {
      storageCache = null;
    });
    loadStorage().catch(() => null);

    const api = {
      id: pluginId,
      manifest,

      state,

      get store() {
        return host.store;
      },

      // ---- 事件 ----
      //
      // 核心事件（`CORE_EVENTS`）走后端 SSE 流：后端在关键流程末尾 `hooks.emit(...)`，
      // 前端 `window.addEventListener` 是**收不到**的（那是两条独立的总线）。
      // 其余事件名保持既有行为（`window` CustomEvent），语义不变。
      on(event, handler) {
        const name = String(event || "").trim();
        if (!name || typeof handler !== "function") return () => {};
        if (CORE_EVENTS.has(name)) {
          return subscribeCoreEvent(pluginId, name, handler);
        }
        const wrapped = (domEvent) => handler(domEvent.detail);
        window.addEventListener(name, wrapped);
        return () => window.removeEventListener(name, wrapped);
      },

      off(event, handler) {
        const name = String(event || "").trim();
        if (!name || typeof handler !== "function") return;
        window.removeEventListener(name, handler);
      },

      emit(event, detail) {
        const name = String(event || "").trim();
        if (!name) return;
        if (!CORE_EVENTS.has(name) && !name.startsWith(`${pluginId}:`)) {
          console.warn(
            `[pluginHost] 插件自定义事件必须以 "${pluginId}:" 开头，已忽略: ${name}`,
          );
          return;
        }
        window.dispatchEvent(new CustomEvent(name, { detail }));
      },

      /**
       * D10：订阅插件自身配置变更。
       *
       * 只投递本插件的变更（`plugin-config-changed` 是全局事件，插件不该看到别人的
       * 配置）。返回取消订阅函数。
       */
      onConfigChange(handler) {
        if (typeof handler !== "function") return () => {};
        const listener = (event) => {
          const detail = (event && event.detail) || {};
          if (String(detail.pluginId || "") !== pluginId) return;
          handler(detail.config || {});
        };
        window.addEventListener("plugin-config-changed", listener);
        return () => window.removeEventListener("plugin-config-changed", listener);
      },

      // ---- 通知与进度 ----
      // `pluginId` 透传给宿主 store，让插件能在图标位写**自己的资源路径**
      // （如 `frontend/assets/icon.svg`）。宿主自身的既有调用不传第 4 参，
      // 行为不变；拿不到 id 时 `resolveIcon()` 返回 missing（只留空白图标位 + warn），
      // 不会去猜一个 URL。
      toast(msg, duration = 3000, icon = "") {
        const store = storeRef();
        if (store && typeof store.showToast === "function") {
          const safeDuration = typeof duration === "string" ? 3000 : duration;
          store.showToast(String(msg ?? ""), safeDuration, icon, { pluginId });
        }
      },

      progress: {
        start(title, total) {
          const store = storeRef();
          if (store && typeof store.startBatchProgress === "function") {
            store.startBatchProgress(title, total);
          }
        },
        update(patch) {
          const store = storeRef();
          if (store && typeof store.updateBatchProgress === "function") {
            store.updateBatchProgress(patch || {});
          }
        },
        cancelRequested() {
          const store = storeRef();
          return Boolean(store && store.batchProgress && store.batchProgress.cancelRequested);
        },
        finish(result) {
          const store = storeRef();
          if (store && typeof store.finishBatchProgress === "function") {
            store.finishBatchProgress(result || {});
          }
        },
        dismiss() {
          const store = storeRef();
          if (store && typeof store.dismissBatchProgress === "function") {
            store.dismissBatchProgress();
          }
        },
      },

      // ---- D8：宿主内建能力（旧的裸动词收敛到这里，旧名保留为别名） ----
      host: {
        toast(msg, duration, iconName) {
          return api.toast(msg, duration, iconName);
        },
        refresh(target) {
          const eventName = REFRESH_EVENTS[String(target)];
          if (!eventName) return false;
          window.dispatchEvent(new CustomEvent(eventName));
          return true;
        },
        switchMode(mode) {
          const next = String(mode || "");
          if (!KNOWN_MODES.has(next)) {
            console.warn(`[pluginHost] 插件 ${pluginId} 请求了未知视图模式: ${next}`);
            return false;
          }
          const store = storeRef();
          if (store) store.currentMode = next;
          return true;
        },
        openDetail(target, id) {
          return api.openDetail(target, id);
        },
        openSettingsSection(section, anchor = "") {
          return api.openSettingsSection(section, anchor);
        },
        notify(message, level = "info") {
          if (level === "error") return api.toast(String(message ?? ""), 4200);
          if (level === "warning") return api.toast(String(message ?? ""), 3600);
          return api.toast(String(message ?? ""), 3000);
        },
        log(message, level = "info") {
          const text = `[plugin:${pluginId}] ${String(message ?? "")}`;
          if (level === "error") console.error(text);
          else if (level === "warning") console.warn(text);
          else console.log(text);
        },

        /**
         * 订阅宿主状态快照（D6）。
         *
         * 首次订阅**立即**收到一次快照，之后变化时推送（已合并去抖，一帧一次）。
         * 返回取消订阅函数，与其他订阅 API 一致。
         *
         * 快照形状（字段名取自 `static/js/state.js`，不猜）：
         * `{mode, deviceType, darkMode, scrimActive, surfaceOpen, busy,
         *   reducedMotion, visible}`。
         *
         * 用途：插件要「与界面联动」时不用再去读 `store`（那是 Provisional 耦合，
         * 宿主改字段名插件就静默失效）。
         */
        onState(handler) {
          if (typeof handler !== "function") return () => {};
          const unsubscribe = hostStateBroadcaster.subscribe(handler);
          own(unsubscribe);
          return unsubscribe;
        },
      },

      // ---- D8：入口 ----
      entries: {
        register(spec) {
          return EntryRegistry.register(pluginId, spec);
        },
        update(entryId, patch) {
          return EntryRegistry.update(pluginId, entryId, patch);
        },
        remove(entryId) {
          return EntryRegistry.remove(pluginId, entryId);
        },
        setBadge(entryId, value) {
          return EntryRegistry.setBadge(pluginId, entryId, value);
        },
        setProgress(entryId, progress) {
          return EntryRegistry.setProgress(pluginId, entryId, progress);
        },
        setStatus(entryId, status) {
          return EntryRegistry.setStatus(pluginId, entryId, status);
        },
        setBusy(entryId, busy) {
          return EntryRegistry.setBusy(pluginId, entryId, busy);
        },
        open(entryId) {
          const entryRecord = EntryRegistry.get(`${pluginId}:${entryId}`);
          if (!entryRecord) return false;
          window.dispatchEvent(
            new CustomEvent("entry:open", { detail: { key: entryRecord.key } }),
          );
          return true;
        },
        list() {
          return EntryRegistry.list({ includeHidden: true }).filter(
            (item) => item.pluginId === pluginId,
          );
        },
      },

      // ---- D8：表面 ----
      //
      // `ambient` 是**常驻型** surface，与其余四种语义相反：注册即挂载、
      // 非模态、不抢焦点、忽略 ESC、不参与遮罩记账、不渲染头部与关闭按钮。
      // 容器是全屏透明层且整体 `pointer-events: none`——插件在其中的
      // **每个可交互子元素都必须显式取回 `pointer-events: auto`**
      // （该属性可继承，漏掉的表现是「点了没反应」）。
      // 宿主在判定被遮挡时给容器加 `is-host-occluded`，插件据此暂停动画或降频。
      // 移动端不挂载（`register()` 返回空串并 console.warn）。
      surfaces: {
        register(surfaceId, spec) {
          return PluginSurfaceHost.register(pluginId, surfaceId, spec);
        },
        open(surfaceId, ctx = {}) {
          const key = `${pluginId}:${String(surfaceId || "")}`;
          return PluginSurfaceHost.openSurface(key, ctx);
        },
        close(surfaceId) {
          return PluginSurfaceHost.close(`${pluginId}:${String(surfaceId || "")}`);
        },
        isOpen(surfaceId) {
          return PluginSurfaceHost.isOpen(`${pluginId}:${String(surfaceId || "")}`);
        },
      },

      // ---- D8：宿主 UI 原语 ----
      // 传入 pluginId：`api.ui.icon('assets/logo.svg')` 这类插件自带资源
      // 需要它才能解析成 `/api/plugins/<id>/assets/…`（D4 允许两种图标取值）。
      ui: buildUiPrimitives({ pluginId }),

      // ---- D8：存储 ----
      storage: {
        get(key) {
          const bucket = storageCache || {};
          const name = String(key);
          return Object.prototype.hasOwnProperty.call(bucket, name) ? bucket[name] : null;
        },
        set(key, value) {
          const bucket = { ...(storageCache || {}) };
          bucket[String(key)] = value;
          return commitStorage(bucket);
        },
        remove(key) {
          const bucket = { ...(storageCache || {}) };
          delete bucket[String(key)];
          return commitStorage(bucket);
        },
        keys() {
          return Object.keys(storageCache || {});
        },
      },

      // ---- 打开既有 UI ----
      openDetail(target = "card", id = "") {
        if (!id) return false;
        const eventName = {
          card: "open-detail",
          preset: "open-preset-reader",
          chat: "open-chat-reader",
          worldinfo: "open-wi-detail-modal",
        }[String(target)];
        if (!eventName) return false;
        window.dispatchEvent(new CustomEvent(eventName, { detail: { id } }));
        return true;
      },

      refresh(target = "cards") {
        return api.host.refresh(target);
      },

      switchMode(mode) {
        return api.host.switchMode(mode);
      },

      openSettingsSection(section, anchor = "") {
        const store = storeRef();
        if (store) store.showSettingsModal = true;
        window.dispatchEvent(
          new CustomEvent("open-settings-section", {
            detail: { section: String(section || ""), anchor: String(anchor || "") },
          }),
        );
        return true;
      },

      // ---- 注册 UI ----
      registerAlpineComponent(name, factory) {
        const register = () => {
          if (window.Alpine && typeof window.Alpine.data === "function") {
            window.Alpine.data(name, factory);
          }
        };
        if (window.Alpine) {
          register();
        } else {
          document.addEventListener("alpine:init", register, { once: true });
        }
      },

      /**
       * @deprecated 用 `api.entries.register({ kind: 'context', surface: {...} })`
       * + `api.surfaces.register()` 替代。保留仅为兼容既有插件。
       */
      registerModal(spec) {
        if (!spec || !spec.id) return "";
        host.modals = host.modals || new Map();
        host.modals.set(String(spec.id), spec);
        return String(spec.id);
      },

      /**
       * @deprecated 用 `api.entries.register({ kind: 'settings' })` 替代。
       * 保留仅为兼容既有插件。
       */
      registerSettingsSection(spec) {
        if (!spec || !spec.id) return "";
        host.settingsSections = host.settingsSections || new Map();
        host.settingsSections.set(String(spec.id), spec);
        return String(spec.id);
      },

      // ---- 后端调用 ----
      async api(path, options = {}) {
        const suffix = String(path || "");
        const url = suffix.startsWith("http")
          ? suffix
          : `/api/plugins/${encodeURIComponent(pluginId)}${suffix.startsWith("/") ? suffix : `/${suffix}`}`;

        const headers = Object.assign({}, options.headers || {});
        headers["X-Requested-With"] = "XMLHttpRequest";
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta && csrfMeta.content) {
          headers["X-CSRFToken"] = csrfMeta.content;
        }

        const init = Object.assign({}, options, { headers });
        const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
        if (options.body && !isFormData && !headers["Content-Type"]) {
          headers["Content-Type"] = "application/json";
          if (typeof options.body !== "string") {
            init.body = JSON.stringify(options.body);
          }
        }

        let response;
        try {
          response = await fetch(url, init);
        } catch (error) {
          return { success: false, msg: `网络请求失败: ${error}` };
        }

        let data = null;
        try {
          data = await response.json();
        } catch (error) {
          data = null;
        }

        // F1：即使 HTTP 200 也可能是业务失败，因此统一以 data.success 为准。
        if (!data || typeof data !== "object") {
          return { success: false, msg: `请求失败 (HTTP ${response.status})` };
        }
        if (typeof data.success !== "boolean") {
          data.success = response.ok;
        }
        return data;
      },

      // ---- SSE ----
      subscribeJob(runId, handlers = {}) {
        const path = `/jobs/${encodeURIComponent(runId)}/events`;
        const url = `/api/plugins/${encodeURIComponent(pluginId)}${path}`;
        const notify = (name, payload) => {
          const handler = handlers[name];
          if (typeof handler === "function") handler(payload);
        };

        let pollTimer = null;
        let closed = false;

        const startPolling = () => {
          if (closed || pollTimer) return;
          const tick = async () => {
            if (closed) return;
            const data = await api.api(`/jobs/${encodeURIComponent(runId)}`);
            if (data && data.success && data.job) {
              notify("snapshot", data.job);
              if (["completed", "failed", "cancelled", "aborted"].includes(data.job.status)) {
                notify("done", data.job);
                stop();
                return;
              }
            } else if (data) {
              notify("error", data);
            }
            pollTimer = setTimeout(tick, 4000);
          };
          pollTimer = setTimeout(tick, 0);
        };

        let source = null;
        const stop = () => {
          closed = true;
          if (source) source.close();
          if (pollTimer) clearTimeout(pollTimer);
          pollTimer = null;
        };

        if (typeof EventSource === "function") {
          let opened = false;
          try {
            source = new EventSource(url);
          } catch (error) {
            startPolling();
            return stop;
          }

          source.addEventListener("open", () => {
            opened = true;
          });
          ["snapshot", "item", "log", "done"].forEach((name) => {
            source.addEventListener(name, (event) => {
              let payload = null;
              try {
                payload = JSON.parse(event.data);
              } catch (error) {
                payload = null;
              }
              notify(name, payload);
              if (name === "done") stop();
            });
          });
          source.addEventListener("error", () => {
            if (closed) return;
            source.close();
            if (!opened) {
              // 从未连上（代理拦截 / 浏览器策略）→ 直接降级为轮询
              notify("error", { success: false, msg: "SSE 不可用，已降级为轮询" });
              startPolling();
            } else {
              // 已连上过：让浏览器自动重连（EventSource 内置退避）
              try {
                source = new EventSource(url);
              } catch (error) {
                startPolling();
              }
            }
          });
          // 插件销毁时必须关掉 SSE，否则连接会一直挂着
          own(stop);
          return stop;
        }

        startPolling();
        own(stop);
        return stop;
      },

      // ---- 工具 ----
      estimateTokens(text) {
        const source = String(text || "");
        if (!source) return 0;
        const cjk = (source.match(/[\u4e00-\u9fff]/g) || []).length;
        return Math.ceil(cjk + (source.length - cjk) / 3.5);
      },

      utils: {
        toAbsoluteAssetUrl: (relativePath) =>
          toAbsoluteAssetUrl(pluginId, relativePath, pluginVersion),
        parseSSEFrames,
        parseSSEPayload,
        resolveIconUrl,
        formatDate: (value) => {
          if (!value) return "-";
          const date = new Date(Number(value) * 1000);
          if (Number.isNaN(date.getTime())) return "-";
          return date.toLocaleString("zh-CN");
        },
      },

      /**
       * 声明「我打开/关闭了一个覆盖整个视口的遮罩」。
       *
       * 插件的全屏 overlay 必须调用这个：宿主会在遮罩打开期间关掉页面壳的
       * `backdrop-filter`。原因见 `docs/plugin-api.md` 与
       * `static/css/modules/layout.css` —— 祖先一旦带 `backdrop-filter`
       * 就成为 backdrop root，遮罩只能采样到不完整的 backdrop，Chromium 会
       * 画出黑块或一整片平坦灰。
       *
       * 按 owner 记账（默认取插件 id），多层遮罩叠加时只有最后一个关闭才摘掉；
       * 同一个 owner 重复 open 不会重复计数。
       */
      setFullscreenScrim(open, owner = pluginId) {
        return applyFullscreenScrim(Boolean(open), `${pluginId}:${owner}`);
      },

      jobs: {
        async get(runId) {
          const data = await api.api(`/jobs/${encodeURIComponent(runId)}`);
          return data && data.success ? data.job : null;
        },
        async list(options = {}) {
          const query = new URLSearchParams();
          if (options.limit) query.set("limit", String(options.limit));
          if (options.offset) query.set("offset", String(options.offset));
          const suffix = query.toString();
          const data = await api.api(`/jobs${suffix ? `?${suffix}` : ""}`);
          return data && data.success ? data.items : [];
        },
        async submit(jobType, items, payload = {}) {
          const data = await api.api("/jobs", {
            method: "POST",
            body: { job_type: jobType, items, payload },
          });
          return data && data.success ? data.run_id : "";
        },
        async cancel(runId) {
          const data = await api.api(`/jobs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
          return Boolean(data && data.success);
        },
        async pause(runId) {
          const data = await api.api(`/jobs/${encodeURIComponent(runId)}/pause`, { method: "POST" });
          return Boolean(data && data.success);
        },
        async resume(runId) {
          const data = await api.api(`/jobs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
          return Boolean(data && data.success);
        },
        async retry(runId, onlyFailed = true) {
          const data = await api.api(`/jobs/${encodeURIComponent(runId)}/retry`, {
            method: "POST",
            body: { only_failed: onlyFailed },
          });
          return data && data.success ? data.run_id : "";
        },
        open(runId, options = {}) {
          if (!runId) return;
          window.dispatchEvent(
            new CustomEvent("open-plugin-job-panel", {
              detail: {
                pluginId,
                runId: String(runId),
                title: String(options.title || ""),
              },
            }),
          );
        },
      },

      // F12：插件容器统一带 data-plugin 标记，与 F11 的 CSS 作用域配套。
      createRoot(tag = "div") {
        const node = document.createElement(tag);
        node.dataset.plugin = pluginId;
        node.classList.add(`plugin-${pluginId}`);
        ensureRootNode().appendChild(node);
        return node;
      },
    };

    return api;
  },

  async request(url, options = {}) {
    const headers = Object.assign({ "X-Requested-With": "XMLHttpRequest" }, options.headers || {});
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta && csrfMeta.content) headers["X-CSRFToken"] = csrfMeta.content;

    try {
      const response = await fetch(url, Object.assign({}, options, { headers }));
      return await response.json();
    } catch (error) {
      return { success: false, msg: `网络请求失败: ${error}` };
    }
  },

  getPluginApi(pluginId) {
    const record = this.loaded.get(String(pluginId || ""));
    return record ? record.api : null;
  },

  /**
   * 销毁插件运行时（D9.2：本方法有真实调用方）。
   *
   * 调用方：
   * - `plugin:unloaded` 事件（禁用 / 卸载 / 重载时由管理 UI 派发）
   * - `entryDock` / `pluginSurfaceHost` 在回收资源时
   *
   * 顺序很重要：先卸载 surface（DOM 先落地），再跑 disposer，最后 deactivate
   * 与摘除容器 —— 保证插件代码在清理时看到的 DOM 仍是完整的。
   */
  destroy(pluginId) {
    const key = String(pluginId || "");

    // 强制卸载该插件的全部 surface（不依赖插件的 deactivate）
    PluginSurfaceHost.unregisterPlugin(key);
    // 核心事件流连接一并断开（与 subscribeJob 的 disposer 同一模式，
    // 但 dispose 只在有记录时才跑，这里保证即便插件已消失也不残留连接）
    coreEventBridge.close(key);
    // 注册表条目一并移除
    EntryRegistry.removePlugin(key);

    const record = this.loaded.get(key);
    const disposers = this.disposers.get(key) || [];
    this.disposers.delete(key);

    if (!record && !disposers.length) return false;

    for (const dispose of disposers) {
      try {
        dispose();
      } catch (error) {
        console.warn(`[pluginHost] 插件 ${key} 的 disposer 抛错:`, error);
      }
    }

    try {
      if (record) {
        if (record.module && typeof record.module.deactivate === "function") {
          record.module.deactivate(record.api);
        }
        if (record.root && record.root.parentNode) {
          record.root.parentNode.removeChild(record.root);
        }
      }
    } catch (error) {
      console.warn(`[pluginHost] 插件 ${key} 停用失败:`, error);
    } finally {
      removeInjectedStyles(key);
      this.loaded.delete(key);
      this.failed.delete(key);
    }
    return true;
  },

  /** 销毁全部插件（宿主关闭 / 重置时使用）。 */
  destroyAll() {
    const ids = new Set([...this.loaded.keys(), ...this.disposers.keys()]);
    for (const id of ids) this.destroy(id);
    coreEventBridge.closeAll();
    return ids.size;
  },
};

export default PluginHost;
