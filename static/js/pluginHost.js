/**
 * static/js/pluginHost.js
 * 前端插件运行时（设计文档第 8 部分 / 10.3 契约）。
 *
 * 职责：
 * 1. 拉取 `/api/plugins/list`，只加载「已启用且含前端入口」的插件。
 * 2. 注入插件样式（F11：未通过作用域检查的样式被拒绝加载）。
 * 3. 动态 `import()` 插件入口并调用 `activate(api)`。
 * 4. 构造并维护插件侧的 PluginAPI 门面（`api.api()` / `api.state` / SSE 等）。
 *
 * 硬约束：
 * - F1：`api()` 以 `data.success` 判断成败，绝不只看 `res.ok`。
 * - F11：样式作用域检查失败的条目直接跳过。
 * - F12：`api.createRoot()` 生成的容器自动带 `data-plugin="<id>"`。
 */

import { parseSSEFrames, parseSSEPayload } from "./utils/sse.js";

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

function toAbsoluteAssetUrl(pluginId, relativePath) {
  const cleaned = String(relativePath || "")
    .replace(/\\/g, "/")
    .replace(/^\/+/, "");
  if (!cleaned) return "";
  const encoded = cleaned
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `/api/plugins/${encodeURIComponent(pluginId)}/assets/${encoded}`;
}

function injectStyle(pluginId, relativePath) {
  const url = toAbsoluteAssetUrl(pluginId, relativePath);
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

export const PluginHost = {
  initialized: false,
  loading: false,
  root: null,
  loaded: new Map(),
  failed: new Map(),

  init() {
    if (this.initialized) return;
    this.initialized = true;
    this.root = ensureRootNode();

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

    const styleErrors = entry.style_scope_errors || {};
    for (const stylePath of manifest.frontend_styles || []) {
      if (styleErrors[stylePath]) {
        console.warn(
          `[pluginHost] 插件 ${pluginId} 的样式未通过作用域检查，已拒绝加载:`,
          stylePath,
        );
        continue;
      }
      injectStyle(pluginId, stylePath);
    }

    const entryUrl = toAbsoluteAssetUrl(pluginId, manifest.frontend_entry);
    if (!entryUrl) return;

    const module = await import(entryUrl);
    const api = this.buildApi(entry, manifest);
    const root = api.createRoot("div");
    root.classList.add(`plugin-${pluginId}`);

    if (module && typeof module.activate === "function") {
      await module.activate(api);
    }

    this.loaded.set(pluginId, { entry, manifest, api, module, root });
    window.dispatchEvent(
      new CustomEvent(`plugin:${pluginId}:ready`, { detail: { id: pluginId } }),
    );
  },

  buildApi(entry, manifest) {
    const pluginId = entry.id;
    const host = this;
    const storeRef = () => this.store;
    const state = window.Alpine && typeof window.Alpine.reactive === "function"
      ? window.Alpine.reactive({})
      : {};

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

      // ---- 打开既有 UI ----
      openDetail(target = "card", id = "") {
        if (!id) return;
        const eventName = {
          card: "open-detail",
          preset: "open-preset-reader",
          chat: "open-chat-reader",
          worldinfo: "open-wi-detail-modal",
        }[String(target)];
        if (!eventName) return;
        window.dispatchEvent(new CustomEvent(eventName, { detail: { id } }));
      },

      refresh(target = "cards") {
        const eventName = REFRESH_EVENTS[String(target)];
        if (!eventName) return;
        window.dispatchEvent(new CustomEvent(eventName));
      },

      switchMode(mode) {
        const store = storeRef();
        if (store) store.currentMode = String(mode || "");
      },

      openSettingsSection(section, anchor = "") {
        const store = storeRef();
        if (store) store.showSettingsModal = true;
        window.dispatchEvent(
          new CustomEvent("open-settings-section", {
            detail: { section: String(section || ""), anchor: String(anchor || "") },
          }),
        );
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

      registerModal(spec) {
        if (!spec || !spec.id) return;
        host.modals = host.modals || new Map();
        host.modals.set(String(spec.id), spec);
      },

      registerSettingsSection(spec) {
        if (!spec || !spec.id) return;
        host.settingsSections = host.settingsSections || new Map();
        host.settingsSections.set(String(spec.id), spec);
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
          return stop;
        }

        startPolling();
        return stop;
      },

      // ---- 工具 ----
      estimateTokens(text) {
        const source = String(text || "");
        if (!source) return 0;
        const cjk = (source.match(/[\u4e00-\u9fa5]/g) || []).length;
        return Math.ceil(cjk + (source.length - cjk) / 3.5);
      },

      utils: {
        toAbsoluteAssetUrl: (relativePath) => toAbsoluteAssetUrl(pluginId, relativePath),
        parseSSEFrames,
        parseSSEPayload,
        formatDate: (value) => {
          if (!value) return "-";
          const date = new Date(Number(value) * 1000);
          if (Number.isNaN(date.getTime())) return "-";
          return date.toLocaleString("zh-CN");
        },
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

  destroy(pluginId) {
    const key = String(pluginId || "");
    const record = this.loaded.get(key);
    if (!record) return false;

    try {
      if (record.root && record.root.parentNode) {
        record.root.parentNode.removeChild(record.root);
      }
      if (record.module && typeof record.module.deactivate === "function") {
        record.module.deactivate(record.api);
      }
    } finally {
      this.loaded.delete(key);
    }
    return true;
  },
};

export default PluginHost;
