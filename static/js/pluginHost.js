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
import { setFullscreenScrim as applyFullscreenScrim } from "./utils/dom.js";
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
 * 后端 `send_file` 用的是 `Cache-Control: no-cache`（每次都会回源校验），但
 * 「no-cache」只保证会发请求，浏览器仍可能用启发式新鲜度把旧响应给出去；
 * 插件更新后版本号变化会让 URL 变化，从而彻底绕开这个问题。
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

export const PluginHost = {
  initialized: false,
  loading: false,
  root: null,
  loaded: new Map(),
  failed: new Map(),
  /** 插件 id → 该插件的 disposer 列表（activate 返回值 + 内部注册的清理函数） */
  disposers: new Map(),

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
        const alpine = window.Alpine || window.__ALPINE__;
        if (alpine && typeof alpine.store === "function") {
          return alpine.store(PLUGIN_STORE_NAME) || null;
        }
        return null;
      },

      // ---- 事件 ----
      on(event, handler) {
        const name = String(event || "").trim();
        if (!name || typeof handler !== "function") return () => {};
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
      toast(msg, duration = 3000, icon = "") {
        const store = storeRef();
        if (store && typeof store.showToast === "function") {
          const safeDuration = typeof duration === "string" ? 3000 : duration;
          store.showToast(String(msg ?? ""), safeDuration, icon);
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
      ui: buildUiPrimitives(),

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
    return ids.size;
  },
};

export default PluginHost;
