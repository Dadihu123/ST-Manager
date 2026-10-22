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
import {
  ContributionRegistry,
  CORE_PLUGIN_ID,
  KILL_SWITCH_COMMAND_ID,
} from "./contributionRegistry.js";
import { PluginRootHost } from "./pluginRootHost.js";
import { PluginOverlayHost } from "./pluginOverlayHost.js";
import { PluginSlotHost } from "./pluginSlotHost.js";
import { PluginSurfaceHost } from "./pluginSurfaceHost.js";
import { listWorldInfo } from "./api/wi.js";
import { buildUiPrimitives } from "./uiPrimitives.js";

const PLUGIN_ROOT_ID = "plugin-host-root";
const PLUGIN_STORE_NAME = "global";
/** 插件 emit 核心事件时的警告文案（§6.6：核心事件只能宿主发出）。 */
const CORE_EVENT_EMIT_WARNING = "核心事件只能由宿主发出，插件 emit 已被忽略";
/** 贡献触发事件（渲染层 → 运行时的唯一通道，S4）。 */
const CONTRIBUTION_TRIGGER_EVENT = "contribution:trigger";
/** kill switch 事件（命令面板内置命令 / 管理器按钮都派发它，S6）。 */
const PLUGINS_CLOSE_OVERLAYS_EVENT = "plugins:close-overlays";
/** 单插件重试事件（管理器「重试」按钮；与 reloadPlugin() 等价）。 */
const PLUGIN_RELOAD_EVENT = "plugin:reload";
/** 运行期异常上报事件（surface / slot / overlay / command 捕获后统一上报）。 */
const PLUGIN_RUNTIME_ERROR_EVENT = "plugin:runtime-error";
/** 降级阈值：同一插件每分钟连续错误 N 次 → 标记降级（设计 §7.2 建议值）。 */
const DEGRADED_ERROR_LIMIT = 5;
const DEGRADED_WINDOW_MS = 60 * 1000;

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

/**
 * 分类路径是否等于 `prefix` 或在它之下（按路径段匹配）。
 *
 * 不能用裸 `startsWith`：`科幻` 会命中 `科幻短片`，把两个不相干的分类混在一起。
 * 与 `sidebar.isInsideIsolatedBranch` / `cardGrid` 的递归判断保持同一套语义。
 */
function isSameOrDescendantCategory(path, prefix) {
  const normalized = String(path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  const base = String(prefix || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  if (!base) return true;
  return normalized === base || normalized.startsWith(`${base}/`);
}

/**
 * 世界书来源的全量枚举（`api.worldbook.sources({ all: true })`）。
 *
 * 为什么需要它：`sources()` 读的是世界书视图的列表缓存（`store.wiList`），
 * 那是**当前页**——右键「精简此分类全部世界书」时，分类里第 21 本以后的
 * 书根本不在缓存里，作用域会静默不全。
 *
 * 为什么不能一口气拉：一个分类上千本世界书时，一次 `page_size=10000` 会把
 * 主线程和响应体一起拖爆。所以这里：
 * - 按 `pageSize`（默认 500）**分页**请求，每页之间让出事件循环；
 * - 总量封顶 `limit`（默认 2000 本），超出的用 `truncated` 明确告知调用方，
 *   由插件决定是提示用户缩小范围还是分批处理——**绝不静默截断**；
 * - 顺带把 `total` 返回，插件可以直接显示「该分类共 N 本」。
 *
 * @returns {Promise<{items: Array, total: number, truncated: boolean}>}
 */
const WORLDBOOK_SOURCES_HARD_LIMIT = 2000;

async function listAllWorldbookSources({ category = "", sourceType = "", pageSize = 500, limit = 0 } = {}) {
  const size = Math.min(Math.max(Number(pageSize) || 500, 50), 1000);
  const cap = Math.min(Math.max(Number(limit) || WORLDBOOK_SOURCES_HARD_LIMIT, 1), WORLDBOOK_SOURCES_HARD_LIMIT);
  const prefix = String(category || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");

  const items = [];
  let total = 0;
  let page = 1;
  // 最多翻 cap/size + 1 页：分类再大也不会无限翻下去
  const maxPages = Math.ceil(cap / size) + 1;

  while (page <= maxPages && items.length < cap) {
    let data;
    try {
      data = await listWorldInfo({ type: "all", page: String(page), page_size: String(size) });
    } catch (error) {
      console.warn("[pluginHost] 列举世界书失败:", error);
      break;
    }
    if (!data || data.success === false) break;

    const batch = Array.isArray(data.items) ? data.items : [];
    total = Number(data.total || total || 0) || total;
    if (!batch.length) break;

    for (const raw of batch) {
      const sourceType_ = String(raw.source_type || raw.type || "global");
      if (sourceType && sourceType_ !== sourceType) continue;
      const category_ = String(raw.display_category || raw.physical_category || "");
      if (!isSameOrDescendantCategory(category_, prefix)) continue;
      const id = String(raw.id || "");
      const filePath = sourceType_ === "embedded" ? "" : id.split("::").slice(1).join("::");
      items.push({
        source_type: sourceType_,
        file_path: filePath,
        card_id: String(raw.card_id || raw.owner_card_id || ""),
        category: category_,
        name: String(raw.name || ""),
        entry_count: Number(raw.entry_count || raw.entries_count || 0) || 0,
      });
      if (items.length >= cap) break;
    }

    // 已经翻完
    if (total && page * size >= total) break;
    if (batch.length < size) break;
    page += 1;
    // 让出事件循环：分页期间 UI 仍可响应
    await new Promise((resolve) => setTimeout(resolve, 0));
  }

  return {
    items,
    total: total || items.length,
    // 只有「还有没取到的」才算截断
    truncated: Boolean(total && total > items.length) || items.length >= cap,
  };
}

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

/**
 * 注入**免作用域**的全局样式（设计 §7.4）。
 *
 * 只有声明了 `ui.global_styles` 能力位才允许注入；注入的 `<link>` 带
 * `data-plugin-style="<id>"`，停用 / 卸载时整体移除。调用方（`loadPlugin`）
 * 负责能力位门控——本函数只做注入。
 */
function injectGlobalStyle(pluginId, relativePath, version = "") {
  const url = toAbsoluteAssetUrl(pluginId, relativePath, version);
  if (!url) return false;

  const styleId = `plugin-global-style-${pluginId}-${String(relativePath).replace(/[^a-zA-Z0-9]+/g, "-")}`;
  if (document.getElementById(styleId)) return true;

  const link = document.createElement("link");
  link.id = styleId;
  link.rel = "stylesheet";
  link.href = url;
  link.dataset.plugin = pluginId;
  // §7.4：全局样式注入带 data-plugin-style="<id>"（调试面板 / 卸载定位用）。
  link.dataset.pluginStyle = pluginId;
  document.head.appendChild(link);
  return true;
}

/** 移除插件注入的样式（destroy 时调用，避免残留影响宿主）。 */
function removeInjectedStyles(pluginId) {
  const nodes = document.querySelectorAll(
    `link[data-plugin="${pluginId}"], link[data-plugin-style="${pluginId}"]`,
  );
  for (const node of nodes) {
    if (node.parentNode) node.parentNode.removeChild(node);
  }
  return nodes.length;
}

/**
 * 贡献模块缓存（S5）：按 `(pluginId, path)` 缓存动态 `import()`。
 *
 * 插槽渲染器与命令处理器共用同一份缓存：激活期预加载一次，运行期直接用，
 * 避免用户每次点命令都重新拉模块。失败不缓存（重试要能重新拉）。
 */
const contributionModuleCache = new Map();

/** 清掉某个插件的模块缓存（禁用 / 卸载 / 重载时调用）。 */
function clearContributionModuleCache(pluginId) {
  const prefix = `${String(pluginId || "")}:`;
  let removed = 0;
  for (const key of Array.from(contributionModuleCache.keys())) {
    if (key.startsWith(prefix)) {
      contributionModuleCache.delete(key);
      removed += 1;
    }
  }
  return removed;
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
    window.addEventListener("contributions:changed", () => this.schedule());
    ["mode-changed", "theme-mode-changed", "settings-saved"].forEach((name) => {
      window.addEventListener(name, () => this.schedule());
    });

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => this.schedule());
    }

    // 其余字段（`batchProgress` / `indexStatus` / `deviceType`）走 Alpine 响应式：
    // 它们有多个写入点，逐个补 dispatchEvent 迟早漏一个（`contributionRegistry` 对
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
  /** 已标记降级的插件（5 次/分钟阈值，见 `reportRuntimeError`）。 */
  degraded: new Set(),
  /** pluginId → `{count, windowStart}`（降级阈值的滑动窗口）。 */
  errorStats: new Map(),
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

    // 自绘/共存宿主（S6/S7）：先建层与 ESC 监听，再初始化消费端。
    PluginRootHost.ensureLayers();
    PluginOverlayHost.init();
    ContributionRegistry.init();
    // 插槽宿主不 import 本模块（避免循环）：模块加载与 api 从这里注入。
    PluginSlotHost.init({
      loadModule: (pluginId, modulePath, record) =>
        this.loadContributionModule(pluginId, modulePath, record),
      getApi: (pluginId) => this.getPluginApi(pluginId),
    });
    // `api.contributions.update({children})` 的 surface 引用要按「已注册」校验。
    ContributionRegistry.setActionValidator((pluginId, action) =>
      this.isContributionActionAllowed(pluginId, action),
    );
    PluginSurfaceHost.init();

    // 插件被禁用 / 卸载时，宿主**强制**回收其运行时资源（D8 契约）
    window.addEventListener("plugin:unloaded", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) this.destroy(String(detail.pluginId));
    });

    // 单插件重试（管理器「重试」按钮 / 事件两条入口等价）。
    window.addEventListener(PLUGIN_RELOAD_EVENT, (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) {
        this.reloadPlugin(String(detail.pluginId)).catch((error) => {
          console.warn("[pluginHost] 插件重试失败:", error);
        });
      }
    });

    // S4：渲染层 → 运行时的唯一触发通道（渲染层不 import 本模块）。
    window.addEventListener(CONTRIBUTION_TRIGGER_EVENT, (event) => {
      const detail = (event && event.detail) || {};
      this.executeContribution(
        String(detail.pluginId || ""),
        String(detail.nodeId || ""),
        String(detail.trigger || "menu"),
        detail.ctx && typeof detail.ctx === "object" ? detail.ctx : {},
      );
    });

    // S6：kill switch（命令面板内置命令 / 管理器按钮都派发这个事件）。
    window.addEventListener(PLUGINS_CLOSE_OVERLAYS_EVENT, () => this.killSwitch());

    // S6：运行期异常统一上报（surface / slot / overlay / command 捕获后派发）。
    window.addEventListener(PLUGIN_RUNTIME_ERROR_EVENT, (event) => {
      const detail = (event && event.detail) || {};
      this.reportRuntimeError(detail.pluginId, detail.error, detail.source);
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
        // S2 定稿快照：`frontend` 是 boolean，入口/样式/贡献都在扁平字段上，
        // 不能再用 v2 的 `manifest.frontend` 对象守卫（会把真实插件全部跳过）。
        if (!this.needsFrontendActivation(manifest)) continue;
        // 幂等：重复 loadAll（初始懒加载 + 手动刷新）不得重复 activate，
        // 否则插件的根节点 / 监听器会被注册两遍，disposer 也会重复。
        if (this.loaded.has(String(entry.id || ""))) continue;
        await this.loadPlugin(entry, manifest).catch((error) => {
          const message = String((error && error.message) || error);
          this.failed.set(entry.id, message);
          console.warn(`[pluginHost] 插件 ${entry.id} 加载失败:`, error);
        });
      }

      // 注册表从同一份列表快照建表（含只有菜单/命令声明、没有前端入口的纯声明插件）
      ContributionRegistry.setPlugins(items);
      this.notifyPluginsLoaded(items);
    } finally {
      this.loading = false;
    }
  },

  /**
   * 该插件是否需要前端激活（加载入口模块 / 预加载贡献模块）。
   *
   * S2 定稿快照里 `frontend` 是**布尔**（"有前端"的摘要标记），入口路径等都在
   * 扁平字段上：`frontend_entry` / `frontend_styles` / `frontend_global_styles` /
   * `render_mode` / `contributions`。不要再假设 `manifest.frontend` 是对象。
   *
   * 纯声明式插件（只有 menus / slots / commands 且没有 `frontend_entry`）不需要
   * `activate()`；但**有 slot/command 模块**时必须激活——否则渲染器拿不到 `ctx.api`。
   */
  needsFrontendActivation(manifest) {
    if (!manifest || typeof manifest !== "object") return false;
    if (String(manifest.frontend_entry || "").trim()) return true;
    const contributions = manifest.contributions;
    if (!contributions || typeof contributions !== "object") return false;
    return (
      (Array.isArray(contributions.slots) && contributions.slots.length > 0) ||
      (Array.isArray(contributions.commands) && contributions.commands.length > 0)
    );
  },

  async loadPlugin(entry, manifest) {
    const pluginId = entry.id;
    const version = String(manifest.version || "");
    const capabilities = Array.isArray(manifest.capabilities) ? manifest.capabilities : [];

    // ---- 样式：受作用域约束的 styles[] 走扫描结果，global_styles[] 要能力位 ----
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
    const globalStyles = Array.isArray(manifest.frontend_global_styles)
      ? manifest.frontend_global_styles
      : [];
    for (const stylePath of globalStyles) {
      // §4.7 / §7.4：只有声明 `ui.global_styles` 才允许注入；后端已把未声明能力位
      // 的 global_styles 置空，这里再门控一层，前端绝不绕过能力位。
      if (!capabilities.includes("ui.global_styles")) {
        console.warn(
          `[pluginHost] 插件 ${pluginId} 声明了 global_styles 但缺少 ui.global_styles 能力位，` +
            "已拒绝注入:",
          stylePath,
        );
        continue;
      }
      injectGlobalStyle(pluginId, stylePath, version);
    }

    // ---- S5 激活期静态校验 + 入口模块 + activate ----
    // 任一环节失败 → 该插件前端激活失败（PluginHost.failed + 管理器重试），
    // 后端继续运行（设计 §4.9）；已经注入的样式 / 建好的 root 一并回滚。
    try {
      await this.preloadContributionModules(pluginId, manifest, version);

      // 入口模块（可选：纯插槽/命令的插件可以没有 activate）
      const entryUrl = toAbsoluteAssetUrl(pluginId, manifest.frontend_entry, version);
      const module = entryUrl ? await import(entryUrl) : null;

      const api = this.buildApi(entry, manifest);
      // 兼容既有插件：仍先给一个插件级根容器；v3 的 createRoot 已按内容层/portal 分层。
      const root = api.createRoot("div");
      if (root) root.classList.add(`plugin-${pluginId}`);

      // D9.1：activate() 的返回值可能是清理函数，记录下来在 destroy 时调用。
      if (module && typeof module.activate === "function") {
        const disposer = await module.activate(api);
        if (typeof disposer === "function") {
          this.addDisposer(pluginId, disposer);
        } else if (disposer && typeof disposer.dispose === "function") {
          this.addDisposer(pluginId, () => disposer.dispose());
        }
      }

      this.loaded.set(pluginId, { entry, manifest, api, module, root, version });
      // 激活成功：清掉上一次的失败记录（重试路径）。
      this.failed.delete(pluginId);
      this.clearDegraded(pluginId);
      window.dispatchEvent(
        new CustomEvent(`plugin:${pluginId}:ready`, { detail: { id: pluginId } }),
      );
    } catch (error) {
      // 半成品清理：不留下残留样式 / 根节点 / 已注册的 disposer。
      PluginRootHost.clear(pluginId);
      removeInjectedStyles(pluginId);
      for (const dispose of this.disposers.get(pluginId) || []) {
        try {
          dispose();
        } catch (disposeError) {
          console.warn(`[pluginHost] 插件 ${pluginId} 激活回滚时 disposer 抛错:`, disposeError);
        }
      }
      this.disposers.delete(pluginId);
      this.loaded.delete(pluginId);
      this.failed.set(pluginId, String((error && error.message) || error));
      throw error;
    }
  },

  /** 预加载 `contributions.slots[]` / `commands[]` 的模块并校验导出（S5）。 */
  async preloadContributionModules(pluginId, manifest, version = "") {
    const contributions =
      manifest && manifest.contributions && typeof manifest.contributions === "object"
        ? manifest.contributions
        : {};
    const expected = [];
    for (const slot of Array.isArray(contributions.slots) ? contributions.slots : []) {
      if (!slot || !slot.module || !slot.export) continue;
      expected.push({
        path: String(slot.module),
        export: String(slot.export),
        kind: "slot",
        id: slot.id,
        version,
      });
    }
    for (const command of Array.isArray(contributions.commands) ? contributions.commands : []) {
      if (!command || !command.module || !command.export) continue;
      expected.push({
        path: String(command.module),
        export: String(command.export),
        kind: "command",
        id: command.id,
        version,
      });
    }
    if (!expected.length) return true;

    for (const item of expected) {
      const module = await this.loadContributionModule(pluginId, item.path, item);
      const exported = module ? module[item.export] : null;
      if (typeof exported !== "function") {
        throw new Error(
          `贡献模块 ${item.path} 缺少导出函数 ${item.export}（${item.kind} ${item.id}）`,
        );
      }
    }
    return true;
  },

  /**
   * 动态 import 一个贡献模块（S5，按 `(pluginId, path)` 缓存）。
   *
   * `modulePath` 是相对插件根目录的路径；URL 走既有 `toAbsoluteAssetUrl()`。
   */
  loadContributionModule(pluginId, modulePath, record = null) {
    const plugin = String(pluginId || "");
    const path = String(modulePath || "").trim();
    if (!plugin || !path) return Promise.reject(new Error("贡献模块路径为空"));

    const key = `${plugin}:${path}`;
    if (contributionModuleCache.has(key)) return contributionModuleCache.get(key);

    const loaded = this.loaded.get(plugin);
    const version = loaded
      ? String(loaded.version || (loaded.manifest && loaded.manifest.version) || "")
      : String((record && record.version) || "");
    const url = toAbsoluteAssetUrl(plugin, path, version);
    const promise = import(url).catch((error) => {
      // 失败不缓存：管理器重试 / 下次触发要能重新拉。
      contributionModuleCache.delete(key);
      throw error;
    });
    contributionModuleCache.set(key, promise);
    return promise;
  },

  /** action 里的 surface 引用是否合法（已由 `api.surfaces.register` 注册）。 */
  isContributionActionAllowed(pluginId, action) {
    if (!action || typeof action !== "object") return false;
    const type = String(action.type || "");
    if (type === "command") {
      return Boolean(ContributionRegistry.getCommand(pluginId, action.id));
    }
    if (type === "url") {
      return /^https?:\/\//i.test(String(action.url || ""));
    }
    if (type === "surface") {
      const surfaceId = String(action.id || "");
      if (!surfaceId) return false;
      const key = `${String(pluginId || "")}:${surfaceId}`;
      return PluginSurfaceHost.has(key) || PluginSurfaceHost.isOpen(key);
    }
    return false;
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
        // §6.6 / S8：核心事件只能宿主发出——插件 emit 一律警告并忽略，
        // 不再允许伪造 `card.updated` 这类事件干扰其他插件。
        if (CORE_EVENTS.has(name)) {
          console.warn(
            `[pluginHost] ${CORE_EVENT_EMIT_WARNING}: ${name}（插件 ${pluginId}）`,
          );
          return;
        }
        if (!name.startsWith(`${pluginId}:`)) {
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

        /**
         * 读取主程序当前的选中集（视图 + id 列表）。
         *
         * 返回 `{ mode: 'cards' | 'worldinfo' | 'presets' | …, ids: string[] }`。
         * 与 `onState()` 不同：这个接口给的是**数据**，状态快照只给界面字段。
         *
         * 这是读取选中集的**契约入口**——不要直接读 `store.viewState.selectedIds`
         * （那是 Provisional 耦合，宿主改字段名时插件会静默拿到空数组）。
         */
        selection() {
          const store = storeRef();
          const viewState = (store && store.viewState) || {};
          const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
          return {
            mode: String((store && store.currentMode) || ""),
            ids: ids.map((item) => String(item || "")).filter(Boolean),
          };
        },
      },

      // ---- v3：贡献（`api.contributions`，设计 §6.1 / S3） ----
      //
      // 静态声明是唯一的结构来源（ADR-0015）：运行期只能更新 / 移除节点，
      // 不能新增落点、节点类型或贡献（`register` 已删除）。
      contributions: {
        update(id, patch) {
          return ContributionRegistry.update(pluginId, id, patch);
        },
        remove(id) {
          return ContributionRegistry.remove(pluginId, id);
        },
        get(id) {
          return ContributionRegistry.get(pluginId, id);
        },
        list() {
          return ContributionRegistry.list(pluginId);
        },
        // 走与 `contribution:trigger` 完全相同的执行器；节点不存在或被 when
        // 过滤时返回 false。
        trigger(id, ctx = {}) {
          return host.executeContribution(pluginId, id, "api", ctx);
        },
      },

      // ---- v3：浮层登记（`api.overlays`，设计 §6.3 / 可选协调） ----
      //
      // 未登记的浮层宿主不干预；登记且 modal 的浮层由宿主处理 ESC 与焦点归还。
      overlays: {
        register(spec = {}) {
          const unregister = PluginOverlayHost.register(pluginId, spec);
          // 随插件销毁自动撤销登记（kill switch 已经关掉的再撤销是空操作）。
          own(() => unregister());
          return unregister;
        },
        unregister(id) {
          return PluginOverlayHost.unregister(pluginId, id);
        },
        list() {
          return PluginOverlayHost.list(pluginId);
        },
        closeAll() {
          return PluginOverlayHost.closeAll(pluginId);
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

      // ---- 世界书来源（文件级） ----
      //
      // 世界书任务的作用域是「世界书文件」，但宿主此前只把「条目」暴露给前端，
      // 插件要枚举「某个分类下有哪些书」只能去读 `store.wiList`（Provisional 耦合）。
      // 这里把那份缓存包成契约接口，字段名与宿主的列表项一致。
      worldbook: {
        /**
         * 世界书来源列表。
         *
         * 两条路径，**语义不同、返回类型也不同**，调用方要明确：
         * - 默认（`all: false`）：同步返回数组，读 `store.wiList` 缓存，只覆盖
         *   **当前已加载的那一页**，适合「右键的那个分类正好在视图里」；
         * - `all: true`：返回 `Promise<{items, total, truncated}>`，走
         *   `/api/world_info/list` 分页拉全量（每页让步、总量封顶 2000）。
         *   分类可能上千本时必须用它，否则作用域会静默少书。
         *
         * `truncated: true` 表示「还有没取到的」——插件必须告知用户，
         * 不能当成完整集合作业。
         */
        sources({ category = "", sourceType = "", all = false, pageSize = 500 } = {}) {
          if (all) return listAllWorldbookSources({ category, sourceType, pageSize });
          const store = storeRef();
          const list = (store && store.wiList) || [];
          const prefix = String(category || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
          return (Array.isArray(list) ? list : [])
            .filter((item) => !prefix || isSameOrDescendantCategory(
              String(item && (item.display_category || item.physical_category) || ""),
              prefix,
            ))
            .filter((item) => !sourceType || String(item.source_type || item.type) === sourceType)
            .map((item) => ({
              source_type: String((item && (item.source_type || item.type)) || "global"),
              file_path: String((item && item.path) || ""),
              card_id: String((item && item.owner_card_id) || ""),
              category: String((item && (item.display_category || item.physical_category)) || ""),
              name: String((item && item.name) || ""),
              entry_count: Number((item && (item.entry_count || item.entries_count)) || 0) || 0,
            }));
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
        /**
         * 审批一个作业条目（`status`：`done` / `skipped` / …）。
         *
         * 插件此前要手拼 `/jobs/<id>/items/<key>/review` 路径调宿主端点；这里
         * 与其它 `jobs.*` 对称，形状确定后不必再记路由。
         */
        async review(runId, itemKey, status) {
          const data = await api.api(
            `/jobs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemKey)}/review`,
            { method: "POST", body: { status } },
          );
          return Boolean(data && data.success);
        },
        /**
         * 批量审批：逐条走 `review()`，**单条失败不影响其余条目**。
         *
         * 返回 `{ total, failed }`——审批是「尽量都落库」，一条失败就整体抛错会
         * 让用户不知道该重试哪条。
         */
        async reviewBatch(runId, updates) {
          const list = Array.isArray(updates) ? updates : [];
          const results = await Promise.allSettled(
            list.map((item) => api.jobs.review(runId, item.key, item.status)),
          );
          // `review()` 网络失败不抛错而是返回 `false`，所以两种失败都要算进去，
          // 否则 `failed` 在「端点返回 success: false」时恒为 0。
          const failed = results.filter(
            (item) => item.status === "rejected" || item.value === false,
          ).length;
          return { total: list.length, failed };
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

      /**
       * v3 自绘根节点（设计 §6.2 / S6）。
       *
       * - `createRoot()` / `createRoot("div")`：内容层（宿主内容之上、宿主模态之下）；
       * - `createRoot({ portal: true })`：body 级 portal 层（宿主模态之上、告警之下），
       *   用于绕开 `backdrop-filter` / `transform` 的层叠上下文陷阱；
       * - `createRoot({ tag: "button" })`：指定标签名。
       *
       * 返回元素由宿主创建、带 `data-plugin` 与 `plugin-<id>`，并登记在
       * `PluginRootHost.roots` 下：插件停用 / 卸载 / kill switch 时整体移除。
       */
      createRoot(tagOrOptions = "div") {
        let options = {};
        if (typeof tagOrOptions === "string") {
          options = { tag: tagOrOptions };
        } else if (tagOrOptions && typeof tagOrOptions === "object") {
          options = tagOrOptions;
        }
        const node = PluginRootHost.create(pluginId, {
          tag: String(options.tag || "div"),
          portal: Boolean(options.portal),
        });
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
   * 贡献执行器（S4）：渲染层 / `api.contributions.trigger` 的唯一动作出口。
   *
   * 按节点 `action` 执行：
   * - `surface` → `PluginSurfaceHost.openSurface("<pluginId>:<id>", ctx)`；
   * - `command` → 动态 import 命令模块并调用 `handler(ctx)`（异常被捕获 + 降级计数）；
   * - `url` → 新标签页打开（不继承插件权限）；
   * - 核心命令（kill switch）→ `killSwitch()`。
   *
   * 节点不存在、被 `remove` 或被 `when` 过滤 → 返回 false。
   *
   * @returns {boolean} 是否派发了动作（命令处理器异步执行）
   */
  executeContribution(pluginId, nodeId, trigger = "menu", ctx = {}) {
    const plugin = String(pluginId || "");
    const node = String(nodeId || "");
    if (!node) return false;

    // 核心命令：kill switch（`core:plugins:close-overlays`）。
    const isCoreKillSwitch =
      node === KILL_SWITCH_COMMAND_ID ||
      (plugin === CORE_PLUGIN_ID && node === "plugins:close-overlays");
    if (isCoreKillSwitch) {
      this.killSwitch();
      return true;
    }

    const record = ContributionRegistry.get(plugin, node);
    if (!record) return false;
    if (!record.ok || record.enabled === false) return false;
    const action = record.action;
    if (!action) return false;

    if (action.type === "surface") {
      const surfaceId = String(action.id || "");
      const surfaceKey = `${plugin}:${surfaceId}`;
      // 静态声明只校验格式（设计 §4.3），运行期点击时未注册 → 警告并忽略，
      // 不抛错、不影响菜单其余项（surfaceHost 也会记录同一条警告）。
      const opened = PluginSurfaceHost.openSurface(surfaceKey, ctx);
      if (!opened) {
        console.warn(
          `[pluginHost] 插件 ${plugin} 的 surface 未注册或无法打开，点击已忽略: ${surfaceId}`,
        );
        return false;
      }
      return true;
    }
    if (action.type === "command") {
      return this._executeCommand(plugin, action.id, record, trigger, ctx);
    }
    if (action.type === "url") {
      const url = String(action.url || "");
      if (!/^https?:\/\//i.test(url)) {
        console.warn(`[pluginHost] 插件 ${plugin} 节点的 url 非法，已忽略: ${url}`);
        return false;
      }
      try {
        window.open(url, "_blank", "noopener");
        return true;
      } catch (error) {
        console.warn("[pluginHost] 打开插件 url 失败:", error);
        return false;
      }
    }
    return false;
  },

  /** 执行一个命令贡献的处理器（异步；异常被捕获并计入降级）。 */
  _executeCommand(pluginId, commandId, node, trigger, ctx = {}) {
    const plugin = String(pluginId || "");
    const command = ContributionRegistry.getCommand(plugin, commandId);
    if (!command) {
      console.warn(`[pluginHost] 插件 ${plugin} 引用了未声明的命令: ${commandId}`);
      return false;
    }
    if (!command.ok || command.enabled === false) return false;

    const loaded = this.loaded.get(plugin);
    if (!loaded) {
      console.warn(`[pluginHost] 插件 ${plugin} 的前端未激活，命令 ${commandId} 已忽略`);
      return false;
    }

    const commandCtx = this.buildCommandContext(loaded, command, node, trigger, ctx);
    Promise.resolve()
      .then(() => this.loadContributionModule(plugin, command.module))
      .then((module) => {
        const handler = module ? module[command.export] : null;
        if (typeof handler !== "function") {
          throw new Error(
            `命令处理器导出不存在或不是函数: ${command.export}（${command.module}）`,
          );
        }
        return handler(commandCtx);
      })
      .catch((error) => {
        console.error(`[pluginHost] 插件 ${plugin} 的命令 ${commandId} 执行失败:`, error);
        this.reportRuntimeError(plugin, error, `command:${commandId}`);
      });
    return true;
  },

  /** 构造命令处理器 ctx（设计 §4.6）：`{api, pluginId, mode, target, selection, trigger}`。 */
  buildCommandContext(loaded, command, node, trigger, ctx = {}) {
    const source = ctx && typeof ctx === "object" ? ctx : {};
    const context = ContributionRegistry.context();
    const selection =
      source.selection && typeof source.selection === "object"
        ? source.selection
        : { mode: context.mode, ids: [] };
    return {
      ...source,
      api: loaded ? loaded.api : null,
      pluginId: command.pluginId,
      mode: String(source.mode || context.mode || ""),
      target: source.target && typeof source.target === "object" ? source.target : null,
      selection,
      trigger: {
        kind: String(trigger || "menu"),
        nodeId: node ? String(node.id || "") : "",
      },
    };
  },

  /**
   * 上报一个运行期异常（S6 崩溃隔离）：日志 + toast + 降级计数。
   *
   * 同一插件在 1 分钟内累计 5 次 → 标记 `degraded`，广播 `plugin:degraded`
   * （管理器展示「降级」与一键停用）；**不卸载插件、不影响后端**。
   *
   * @returns {boolean} 该插件当前是否已降级
   */
  reportRuntimeError(pluginId, error, source = "") {
    const key = String(pluginId || "");
    if (!key) return false;

    console.error(`[pluginHost] 插件 ${key} 运行期异常（${source || "unknown"}）:`, error);

    const now = Date.now();
    let stat = this.errorStats.get(key);
    if (!stat || now - stat.windowStart > DEGRADED_WINDOW_MS) {
      stat = { count: 0, windowStart: now };
      this.errorStats.set(key, stat);
    }
    stat.count += 1;

    // 用户可感知的错误提示（拿不到 store 时静默：日志已经写了）。
    try {
      const store = this.store;
      if (store && typeof store.showToast === "function") {
        store.showToast(`插件 ${key} 运行出错，已隔离`, 4200, "", { pluginId: key });
      }
    } catch (toastError) {
      console.warn("[pluginHost] 运行期错误提示失败:", toastError);
    }

    if (stat.count >= DEGRADED_ERROR_LIMIT && !this.degraded.has(key)) {
      this.degraded.add(key);
      console.warn(
        `[pluginHost] 插件 ${key} 在 ${DEGRADED_ERROR_LIMIT} 次/分钟阈值内连续出错，已标记降级`,
      );
      window.dispatchEvent(
        new CustomEvent("plugin:degraded", {
          detail: { pluginId: key, count: stat.count, source: String(source || "") },
        }),
      );
    }
    return this.degraded.has(key);
  },

  /** 该插件是否已降级（管理器展示 / 一键停用入口）。 */
  isDegraded(pluginId) {
    return this.degraded.has(String(pluginId || ""));
  },

  /** 清除降级标记（重试成功后调用）。 */
  clearDegraded(pluginId) {
    const key = String(pluginId || "");
    this.degraded.delete(key);
    this.errorStats.delete(key);
    return true;
  },

  /**
   * kill switch（设计 §7.3 / S6）：不卸载、不停用插件，只回收界面。
   *
   * 对每个插件依次：①已登记浮层逐个 `onDismiss`；②广播 `overlays:force-closed`
   * `{pluginId}`；③清空并移除该插件全部 root（内容层 + portal 层）。
   *
   * @returns {number} 处理过的插件数量
   */
  killSwitch() {
    const ids = new Set([
      ...this.loaded.keys(),
      ...this.disposers.keys(),
      ...PluginRootHost.pluginIds(),
      ...PluginOverlayHost.pluginIds(),
      // 已声明的插件也纳入：没有 root/overlay 的插件同样可以据 broadcast 重置
      // 自己的 UI 状态（事件本身无副作用）。
      ...ContributionRegistry.plugins.map((item) => String((item && item.id) || "")),
    ]);
    ids.delete("");
    if (!ids.size) return 0;

    for (const pluginId of ids) {
      // `PluginOverlayHost.killSwitch([id])` 完成 ①关闭 ②广播；顺序由设计规定。
      PluginOverlayHost.killSwitch([pluginId]);
      // ③ 清空并移除 root（未登记浮层只能靠这一步回收）。
      PluginRootHost.clear(pluginId);
    }
    return ids.size;
  },

  /**
   * 单插件重试（管理器「前端激活失败 + 重试」，设计 §4.9）。
   *
   * 销毁该插件的运行时资源，重新拉列表并尝试激活；更新 `failed` 后广播
   * `plugins:loaded`（detail 带快照）与 `contributions:changed`。
   */
  async reloadPlugin(pluginId) {
    const key = String(pluginId || "");
    if (!key) return false;

    this.destroy(key);

    const data = await this.request("/api/plugins/list");
    if (!data || data.success !== true) {
      this.failed.set(key, "插件列表读取失败");
      this.notifyPluginsLoaded([]);
      return false;
    }

    const items = Array.isArray(data.items) ? data.items : [];
    const entry = items.find((item) => item && String(item.id) === key);
    if (!entry || entry.enabled === false) {
      this.failed.set(key, "插件不存在或未启用");
      this.notifyPluginsLoaded(items);
      return false;
    }

    const manifest = entry.manifest || {};
    let ok = true;
    if (this.needsFrontendActivation(manifest)) {
      try {
        await this.loadPlugin(entry, manifest);
      } catch (error) {
        ok = false;
        this.failed.set(key, String((error && error.message) || error));
        console.warn(`[pluginHost] 插件 ${key} 重试失败:`, error);
      }
    }

    ContributionRegistry.setPlugins(items);
    this.notifyPluginsLoaded(items);
    return ok;
  },

  /** 广播 `plugins:loaded`（detail 带当前 loaded/failed 与列表快照）。 */
  notifyPluginsLoaded(items = []) {
    const failed = Array.from(this.failed.keys());
    window.dispatchEvent(
      new CustomEvent("plugins:loaded", {
        detail: {
          loaded: Array.from(this.loaded.keys()),
          failed,
          items: Array.isArray(items) ? items : [],
        },
      }),
    );
    if (failed.length) {
      window.dispatchEvent(
        new CustomEvent("plugins:frontend-failed", { detail: { failed } }),
      );
    }
    return failed;
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

    // 强制卸载该插件的全部 surface / 浮层 / 根节点（不依赖插件的 deactivate）
    PluginSurfaceHost.unregisterPlugin(key);
    PluginOverlayHost.clearPlugin(key);
    PluginRootHost.clear(key);
    PluginSlotHost.clearPlugin(key);
    // 核心事件流连接一并断开（与 subscribeJob 的 disposer 同一模式，
    // 但 dispose 只在有记录时才跑，这里保证即便插件已消失也不残留连接）
    coreEventBridge.close(key);
    // 注册表条目与模块缓存一并移除（重载时要拿到新版本模块）
    ContributionRegistry.removePlugin(key);
    clearContributionModuleCache(key);

    const record = this.loaded.get(key);
    const disposers = this.disposers.get(key) || [];
    this.disposers.delete(key);

    if (!record && !disposers.length) {
      removeInjectedStyles(key);
      this.failed.delete(key);
      this.clearDegraded(key);
      return false;
    }

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
      this.clearDegraded(key);
    }
    return true;
  },

  /** 销毁全部插件（宿主关闭 / 重置时使用）。 */
  destroyAll() {
    const ids = new Set([...this.loaded.keys(), ...this.disposers.keys()]);
    for (const id of ids) this.destroy(id);
    coreEventBridge.closeAll();
    PluginOverlayHost.overlays.clear();
    PluginRootHost.clearAll();
    PluginSlotHost.reset();
    return ids.size;
  },
};

export default PluginHost;
