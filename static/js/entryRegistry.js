/**
 * static/js/entryRegistry.js
 * 入口注册表（设计文档 D1 / D5 / D6 / D7 / D8 的宿主侧落点）。
 *
 * 「插件声明、宿主渲染」这条契约的中枢：插件在 manifest 的 `frontend.entries`
 * 里声明入口，本模块把它们收进一张全局表，再由入口坞 / 命令面板 / 总览页消费。
 * 插件运行期也可以用 `api.entries.register()` 追加动态入口。
 *
 * 职责边界：
 * - 只做「登记 + 过滤 + 排序 + 求值」，不碰 DOM（渲染归 entryDock / commandPalette）。
 * - 全局键一律 `<plugin_id>:<entry_id>`，宿主内建入口用 `core:` 前缀，两者永不冲突。
 * - `when` 条件表达式**统一在这里求值**（D7）：插件只声明，不自行判断。
 *
 * 数据来源：
 * - 声明层：`/api/plugins/list` 的 `manifest.entries`（已由后端做过结构校验与 tier 过滤）
 * - 偏好层：`/api/plugins/entries/layout` → `ui_data._entry_layout_v1`
 */

const ENTRY_LAYOUT_ENDPOINT = "/api/plugins/entries/layout";

/** 宿主内建入口键前缀（与插件键互斥：插件 id 不含 `:`）。 */
export const CORE_ENTRY_PREFIX = "core:";

/** 坞可见槽位上限与单插件占位上限（D6，与后端 entries.py 保持一致）。 */
export const MAX_DOCK_SLOTS = 8;
export const MAX_DOCK_ENTRIES_PER_PLUGIN = 2;

/** 入口种类与呈现类型（D1）。 */
export const ENTRY_KINDS = ["dock", "nav", "settings", "context", "command", "status"];
export const SURFACE_TYPES = ["panel", "modal", "page", "sheet"];

/** 空布局的形状；`_entry_layout_v1` 缺省时使用。 */
function emptyLayout() {
  return { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
}

/**
 * 宿主内建入口（命令面板的固定项）。
 *
 * 定义在模块顶层而不是 `init()` 里：命令面板与总览页可能在 `init()` 之前就查询
 * `searchable()`（模块加载顺序不保证），内建命令不该因此消失。
 */
const CORE_ENTRIES = Object.freeze(
  [
    { key: `${CORE_ENTRY_PREFIX}open-settings`, kind: "command", label: "打开设置", icon: "settings" },
    { key: `${CORE_ENTRY_PREFIX}open-plugin-manager`, kind: "command", label: "打开插件管理", icon: "plugin" },
    { key: `${CORE_ENTRY_PREFIX}switch-cards`, kind: "command", label: "切换到角色卡", icon: "character-cards" },
    { key: `${CORE_ENTRY_PREFIX}switch-worldinfo`, kind: "command", label: "切换到世界书", icon: "book-open" },
    { key: `${CORE_ENTRY_PREFIX}switch-chats`, kind: "command", label: "切换到会话", icon: "chat-bubble" },
    { key: `${CORE_ENTRY_PREFIX}switch-presets`, kind: "command", label: "切换到预设", icon: "preset" },
  ].map((item) => ({ ...item, pluginId: "", tier: "official", source: "core" })),
);

/** 生成跨插件唯一的全局入口键。 */
export function buildEntryKey(pluginId, entryId) {
  return `${String(pluginId || "").trim()}:${String(entryId || "").trim()}`;
}

/** 判断是否宿主内建入口键。 */
export function isHostEntryKey(key) {
  return typeof key === "string" && key.startsWith(CORE_ENTRY_PREFIX);
}

/** 语义化版本比较；返回 -1 / 0 / 1，非法版本返回 0（视为相等，不误伤）。 */
export function compareVersions(left, right) {
  const parse = (value) =>
    String(value || "")
      .trim()
      .split(".")
      .map((part) => Number.parseInt(part, 10))
      .map((part) => (Number.isFinite(part) ? part : 0));

  const a = parse(left);
  const b = parse(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (a[index] || 0) - (b[index] || 0);
    if (diff !== 0) return diff > 0 ? 1 : -1;
  }
  return 0;
}

/** 解析 `>=1.0.0` / `>1.0.0` / `<=1.0.0` / `=1.0.0` 形式的版本约束。 */
function satisfiesVersion(actual, constraint) {
  const text = String(constraint || "").trim();
  if (!text) return true;

  const match = /^(>=|<=|>|<|=|==)?\s*(.+)$/.exec(text);
  if (!match) return true;

  const operator = match[1] || ">=";
  const target = match[2].trim();
  const diff = compareVersions(actual, target);

  if (operator === ">=") return diff >= 0;
  if (operator === "<=") return diff <= 0;
  if (operator === ">") return diff > 0;
  if (operator === "<") return diff < 0;
  return diff === 0;
}

/** 主程序版本：由 layout.html 注入的 meta 标签提供（缺失时回退空串）。 */
export function hostAppVersion() {
  if (typeof document === "undefined") return "";
  const meta = document.querySelector('meta[name="app-version"]');
  return meta && meta.content ? String(meta.content) : "";
}

/** 宿主能力集合（`when.feature` 的取值来源）。 */
export function hostFeatures() {
  const features = [];
  if (typeof navigator !== "undefined") {
    if (navigator.onLine !== false) features.push("hasNetwork");
  }
  if (typeof EventSource === "function") features.push("hasSSE");
  if (typeof window !== "undefined" && typeof window.fetch === "function") {
    features.push("hasFetch");
  }
  return features;
}

/**
 * 求值 `when` 条件表达式（D7）。
 *
 * 返回 `{ ok, reasons }`：`ok === false` 表示入口**可见但置灰**（不是隐藏），
 * `reasons` 用于生成 tooltip —— 优先取插件声明的 `disabledHint`。
 */
export function evaluateWhen(when, context = {}) {
  const reasons = [];
  if (!when || typeof when !== "object") return { ok: true, reasons };

  const modes = Array.isArray(when.mode) ? when.mode : [];
  if (modes.length && !modes.includes(String(context.mode || ""))) {
    reasons.push("current_mode");
  }

  const selection = String(when.selection || "").trim();
  if (selection) {
    const count = Number(context.selectionCount || 0);
    const actual =
      count === 0 ? "none" : count === 1 ? "single" : "multi";
    // `any` 表示「至少要选中一个」，`multi` 只要求多于一个（单选也满足 any）
    const ok =
      selection === actual ||
      (selection === "any" && count > 0) ||
      (selection === "multi" && count > 1);
    if (!ok) reasons.push("selection");
  }

  const indexState = String(when.indexState || "").trim();
  if (indexState && indexState !== String(context.indexState || "")) {
    reasons.push("index_state");
  }

  const requireKeys =
    when.config && Array.isArray(when.config.requireKeys)
      ? when.config.requireKeys
      : [];
  if (requireKeys.length) {
    const config = context.config && typeof context.config === "object" ? context.config : {};
    const missing = requireKeys.filter((key) => {
      const value = config[key];
      return value === undefined || value === null || String(value).trim() === "";
    });
    if (missing.length) reasons.push("config");
  }

  const hostVersion = String(when.hostVersion || "").trim();
  if (hostVersion && !satisfiesVersion(context.hostVersion || "", hostVersion)) {
    reasons.push("host_version");
  }

  const features = Array.isArray(when.feature) ? when.feature : [];
  if (features.length) {
    const available = new Set(context.feature || []);
    if (features.some((name) => !available.has(name))) reasons.push("feature");
  }

  return { ok: reasons.length === 0, reasons };
}

/** 把后端下发的声明层条目补上宿主默认值。 */
function normalizeDeclaredEntry(raw, pluginId) {
  if (!raw || typeof raw !== "object") return null;
  const entryId = String(raw.id || "").trim();
  if (!entryId) return null;

  const kind = String(raw.kind || "").trim();
  if (!ENTRY_KINDS.includes(kind)) return null;

  const surface = raw.surface && typeof raw.surface === "object" ? raw.surface : {};
  const surfaceType = SURFACE_TYPES.includes(String(surface.type || ""))
    ? String(surface.type)
    : "panel";

  return {
    key: buildEntryKey(pluginId, entryId),
    id: entryId,
    pluginId,
    kind,
    label: String(raw.label || entryId),
    description: String(raw.description || ""),
    icon: String(raw.icon || ""),
    contexts: Array.isArray(raw.contexts) ? raw.contexts.map(String) : [],
    requiresSelection: Boolean(raw.requires_selection),
    surface: { ...surface, type: surfaceType },
    priority: Number.isFinite(Number(raw.priority)) ? Number(raw.priority) : 100,
    badge: raw.badge === undefined ? null : raw.badge,
    shortcut: String(raw.shortcut || ""),
    when: raw.when && typeof raw.when === "object" ? raw.when : {},
    disabledHint: String(raw.disabledHint || ""),
    tier: String(raw.tier || "community"),
    source: "manifest",
    // 运行期状态（由 api.entries.* 维护，不属于声明层）
    status: "idle",
    busy: false,
    progress: null,
  };
}

export const EntryRegistry = {
  initialized: false,
  /** 全局键 → 条目（声明层 + 运行期注册） */
  entries: new Map(),
  /** 插件 id → 该插件的配置快照（`when.config.requireKeys` 求值用） */
  configs: new Map(),
  /** 宿主内建入口（命令面板的固定项）。 */
  coreEntries: [...CORE_ENTRIES],
  layout: emptyLayout(),
  layoutLoaded: false,
  plugins: [],

  init() {
    if (this.initialized) return;
    this.initialized = true;

    this.registerCoreEntries();

    // 插件加载完成（含禁用后重载）→ 重建注册表
    window.addEventListener("plugins:loaded", () => {
      this.loadFromHost();
    });

    // D10：配置/密钥变更后刷新缓存，让 `when.config.requireKeys` 立即重算
    window.addEventListener("plugin-config-changed", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) this.configs.set(String(detail.pluginId), detail.config || {});
      this.notifyChange();
    });
    window.addEventListener("plugin-secrets-changed", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) {
        // 密钥也可能参与 requireKeys（如 api_key 写在 secret_schema）
        const merged = Object.assign(
          {},
          this.configs.get(String(detail.pluginId)) || {},
          detail.config || {},
        );
        this.configs.set(String(detail.pluginId), merged);
      }
      this.notifyChange();
    });

    // 视图模式 / 选中项变化会影响 `when` 求值结果
    ["mode-changed", "selection-changed", "refresh-card-list"].forEach((name) => {
      window.addEventListener(name, () => this.notifyChange());
    });

    this.loadLayout().catch(() => null);
  },

  /** 宿主内建入口：命令面板的固定项。 */
  registerCoreEntries() {
    this.coreEntries = [...CORE_ENTRIES];
  },

  // ------------------------------------------------------------ 偏好层

  async loadLayout() {
    try {
      const response = await fetch(ENTRY_LAYOUT_ENDPOINT, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (data && data.success && data.layout && typeof data.layout === "object") {
        this.layout = Object.assign(emptyLayout(), data.layout);
      }
    } catch (error) {
      console.warn("[entryRegistry] 读取入口布局失败:", error);
    } finally {
      this.layoutLoaded = true;
      this.notifyChange();
    }
  },

  async saveLayout(patch) {
    if (!patch || typeof patch !== "object") return false;
    try {
      const response = await fetch(ENTRY_LAYOUT_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ layout: patch }),
      });
      const data = await response.json();
      if (!data || !data.success) return false;
      this.layout = Object.assign(emptyLayout(), data.layout || {});
      this.notifyChange();
      return true;
    } catch (error) {
      console.warn("[entryRegistry] 保存入口布局失败:", error);
      return false;
    }
  },

  /** 就地更新一份布局偏好并持久化（坞的拖拽 / 固定 / 隐藏都走这里）。 */
  updateLayout(patch) {
    this.layout = Object.assign(emptyLayout(), this.layout, patch || {});
    return this.saveLayout(patch);
  },

  // ------------------------------------------------------------ 登记

  /** 从 `/api/plugins/list` 拉取声明层条目并重建注册表。 */
  async loadFromHost() {
    try {
      const response = await fetch("/api/plugins/list", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!data || data.success !== true) return;
      this.setPlugins(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      console.warn("[entryRegistry] 读取插件列表失败:", error);
    }
  },

  /** 用插件列表快照重建注册表（未启用插件不进入注册表）。 */
  setPlugins(items) {
    this.plugins = Array.isArray(items) ? items : [];

    // 保留运行期注册的条目（source === 'runtime'），声明层整体重建
    const runtimeEntries = Array.from(this.entries.values()).filter(
      (entry) => entry.source === "runtime",
    );

    this.entries = new Map();
    for (const item of this.plugins) {
      if (!item || item.enabled === false) continue;
      const pluginId = String(item.id || "");
      const manifest = item.manifest || {};
      const declared = Array.isArray(manifest.entries) ? manifest.entries : [];
      for (const raw of declared) {
        const entry = normalizeDeclaredEntry(raw, pluginId);
        if (entry) this.entries.set(entry.key, entry);
      }
    }

    // 运行期条目重新挂回（插件若已被禁用则丢弃）
    for (const entry of runtimeEntries) {
      const plugin = this.plugins.find((item) => String(item.id) === entry.pluginId);
      if (plugin && plugin.enabled !== false) this.entries.set(entry.key, entry);
    }

    this.notifyChange();
    this.ensureConfigs().catch(() => null);
  },

  /** 按需拉取参与 `when.config.requireKeys` 的插件配置。 */
  async ensureConfigs() {
    const needed = new Set();
    for (const entry of this.entries.values()) {
      const keys = entry.when && entry.when.config ? entry.when.config.requireKeys : null;
      if (Array.isArray(keys) && keys.length) needed.add(entry.pluginId);
    }

    await Promise.all(
      Array.from(needed).map(async (pluginId) => {
        if (this.configs.has(pluginId)) return;
        try {
          const response = await fetch(`/api/plugins/${encodeURIComponent(pluginId)}/config`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          const data = await response.json();
          this.configs.set(pluginId, data && data.success ? data.config || {} : {});
        } catch (error) {
          this.configs.set(pluginId, {});
        }
      }),
    );
    this.notifyChange();
  },

  /**
   * 运行期注册入口（`api.entries.register`）。
   *
   * 插件只能注册自己命名空间下的键，`key` 由插件 id 前缀强制拼装。
   */
  register(pluginId, spec) {
    if (!spec || typeof spec !== "object") return "";
    const entryId = String(spec.id || "").trim();
    if (!entryId) return "";

    const kind = String(spec.kind || "command").trim();
    if (!ENTRY_KINDS.includes(kind)) {
      console.warn(`[entryRegistry] 插件 ${pluginId} 注册了非法 kind: ${kind}`);
      return "";
    }

    const key = buildEntryKey(pluginId, entryId);
    const surface = spec.surface && typeof spec.surface === "object" ? spec.surface : {};
    this.entries.set(key, {
      key,
      id: entryId,
      pluginId: String(pluginId),
      kind,
      label: String(spec.label || entryId),
      description: String(spec.description || ""),
      icon: String(spec.icon || ""),
      contexts: Array.isArray(spec.contexts) ? spec.contexts.map(String) : [],
      requiresSelection: Boolean(spec.requiresSelection),
      surface: {
        ...surface,
        type: SURFACE_TYPES.includes(String(surface.type || ""))
          ? String(surface.type)
          : "panel",
      },
      priority: Number.isFinite(Number(spec.priority)) ? Number(spec.priority) : 100,
      badge: spec.badge === undefined ? null : spec.badge,
      shortcut: String(spec.shortcut || ""),
      when: spec.when && typeof spec.when === "object" ? spec.when : {},
      disabledHint: String(spec.disabledHint || ""),
      tier: "community",
      source: "runtime",
      status: "idle",
      busy: false,
      progress: null,
    });
    this.notifyChange();
    return key;
  },

  update(pluginId, entryId, patch) {
    const key = buildEntryKey(pluginId, entryId);
    const entry = this.entries.get(key);
    if (!entry || !patch || typeof patch !== "object") return false;

    for (const field of ["label", "description", "icon", "shortcut", "disabledHint"]) {
      if (field in patch) entry[field] = String(patch[field] ?? "");
    }
    if ("priority" in patch && Number.isFinite(Number(patch.priority))) {
      entry.priority = Number(patch.priority);
    }
    if ("badge" in patch) entry.badge = patch.badge;
    if ("kind" in patch && ENTRY_KINDS.includes(String(patch.kind))) {
      entry.kind = String(patch.kind);
    }
    if ("when" in patch && patch.when && typeof patch.when === "object") {
      entry.when = patch.when;
    }
    if ("contexts" in patch && Array.isArray(patch.contexts)) {
      entry.contexts = patch.contexts.map(String);
    }

    this.notifyChange();
    return true;
  },

  remove(pluginId, entryId) {
    const key = buildEntryKey(pluginId, entryId);
    const removed = this.entries.delete(key);
    if (removed) this.notifyChange();
    return removed;
  },

  /** 移除某个插件的全部条目（禁用 / 卸载 / destroy 时调用）。 */
  removePlugin(pluginId) {
    const prefix = `${String(pluginId || "")}:`;
    let changed = false;
    for (const key of Array.from(this.entries.keys())) {
      if (key.startsWith(prefix)) {
        this.entries.delete(key);
        changed = true;
      }
    }
    this.configs.delete(String(pluginId));
    if (changed) this.notifyChange();
    return changed;
  },

  // ------------------------------------------------------------ 运行期状态

  setBadge(pluginId, entryId, value) {
    const entry = this.entries.get(buildEntryKey(pluginId, entryId));
    if (!entry) return false;
    entry.badge = value === null || value === undefined ? null : value;
    this.notifyChange();
    return true;
  },

  setProgress(pluginId, entryId, progress) {
    const entry = this.entries.get(buildEntryKey(pluginId, entryId));
    if (!entry) return false;
    entry.progress =
      progress && Number.isFinite(Number(progress.total))
        ? { done: Number(progress.done) || 0, total: Number(progress.total) || 0 }
        : null;
    this.notifyChange();
    return true;
  },

  setStatus(pluginId, entryId, status) {
    const entry = this.entries.get(buildEntryKey(pluginId, entryId));
    if (!entry) return false;
    const allowed = ["ok", "warn", "error", "idle"];
    entry.status = allowed.includes(String(status)) ? String(status) : "idle";
    this.notifyChange();
    return true;
  },

  setBusy(pluginId, entryId, busy) {
    const entry = this.entries.get(buildEntryKey(pluginId, entryId));
    if (!entry) return false;
    entry.busy = Boolean(busy);
    this.notifyChange();
    return true;
  },

  // ------------------------------------------------------------ 查询

  get(key) {
    return this.entries.get(String(key || "")) || null;
  },

  /** 宿主当前上下文（`when` 求值输入）。 */
  context() {
    const store =
      typeof window !== "undefined" && window.Alpine && typeof window.Alpine.store === "function"
        ? window.Alpine.store("global")
        : null;
    const viewState = (store && store.viewState) || {};
    const selectedIds = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
    const indexStatus = (store && store.indexStatus) || {};

    return {
      mode: String((store && store.currentMode) || ""),
      selectionCount: selectedIds.length,
      indexState: String(indexStatus.state || ""),
      hostVersion: hostAppVersion(),
      feature: hostFeatures(),
    };
  },

  /**
   * 列出入口。
   *
   * @param {object} options
   * @param {string} [options.kind] 只取某个 kind
   * @param {boolean} [options.includeHidden] 是否包含用户隐藏项（默认否）
   * @param {boolean} [options.includeDisabled] 是否包含 `when` 未满足项（默认是，置灰展示）
   */
  list(options = {}) {
    const kind = String(options.kind || "").trim();
    const includeHidden = Boolean(options.includeHidden);
    const context = this.context();
    const hidden = new Set(this.layout.hidden || []);
    const order = Array.isArray(this.layout.order) ? this.layout.order : [];

    const items = [];
    for (const entry of this.entries.values()) {
      if (kind && entry.kind !== kind) continue;
      if (!includeHidden && hidden.has(entry.key)) continue;

      const when = evaluateWhen(entry.when, {
        ...context,
        config: this.configs.get(entry.pluginId) || {},
      });

      // `contexts` 与 `when.mode` 同时存在时取交集（D7）
      let contextsOk = true;
      if (entry.contexts.length) {
        contextsOk = entry.contexts.includes(context.mode);
      }

      const enabled = when.ok && contextsOk;
      items.push({
        ...entry,
        enabled,
        disabledHint: entry.disabledHint || this._defaultDisabledHint(when.reasons),
        pinned: this.isPinned(entry),
      });
    }

    items.sort((left, right) => {
      const leftIndex = order.indexOf(left.key);
      const rightIndex = order.indexOf(right.key);
      // 用户显式排序优先于插件建议的 priority
      if (leftIndex !== -1 || rightIndex !== -1) {
        if (leftIndex === -1) return 1;
        if (rightIndex === -1) return -1;
        if (leftIndex !== rightIndex) return leftIndex - rightIndex;
      }
      if (left.priority !== right.priority) return left.priority - right.priority;
      return left.key.localeCompare(right.key);
    });

    return items;
  },

  /** 全部条目（含隐藏），供总览页使用。 */
  all() {
    return this.list({ includeHidden: true });
  },

  /** 坞槽位内的条目（固定项，上限 8 个）。 */
  dockSlots() {
    const pinned = this.list({ kind: "dock" }).filter((entry) => entry.pinned);
    const slots = [];
    const perPlugin = new Map();

    for (const entry of pinned) {
      if (slots.length >= MAX_DOCK_SLOTS) break;
      const used = perPlugin.get(entry.pluginId) || 0;
      if (used >= MAX_DOCK_ENTRIES_PER_PLUGIN) continue;
      perPlugin.set(entry.pluginId, used + 1);
      slots.push(entry);
    }
    return slots;
  },

  /** 溢出菜单：已声明但未进坞槽位的 dock 入口。 */
  overflowEntries() {
    const slotKeys = new Set(this.dockSlots().map((entry) => entry.key));
    return this.list({ kind: "dock" }).filter((entry) => !slotKeys.has(entry.key));
  },

  /** 判断入口是否固定在坞内（D6：社区插件默认进溢出菜单）。 */
  isPinned(entry) {
    const layout = this.layout || {};
    const pinned = Array.isArray(layout.pinned) ? layout.pinned : [];
    const unpinned = Array.isArray(layout.unpinned) ? layout.unpinned : [];

    if (pinned.includes(entry.key)) return true;
    if (unpinned.includes(entry.key)) return false;
    // 未表态时的默认值：官方 / 认证插件进坞，社区插件进溢出菜单
    return entry.tier !== "community";
  },

  /** 命令面板的搜索范围 = 全部注册表条目 + 宿主内建命令。 */
  searchable() {
    return [...this.coreEntries, ...this.all()];
  },

  /** 按快捷键查找入口（`layout.shortcuts` 由用户在总览页配置）。 */
  findByShortcut(combo) {
    const shortcuts = (this.layout && this.layout.shortcuts) || {};
    const key = shortcuts[String(combo || "")];
    if (!key) return null;
    return this.get(key) || this.coreEntries.find((item) => item.key === key) || null;
  },

  _defaultDisabledHint(reasons) {
    if (!reasons || !reasons.length) return "";
    const map = {
      current_mode: "当前视图下不可用",
      selection: "请先选择条目",
      index_state: "索引尚未就绪",
      config: "请先完成插件配置",
      host_version: "需要更高版本的主程序",
      feature: "当前环境不支持所需能力",
    };
    return map[reasons[0]] || "当前条件下不可用";
  },

  /** 广播变更，让坞 / 命令面板 / 总览页刷新。 */
  notifyChange() {
    if (typeof window === "undefined") return;
    window.dispatchEvent(
      new CustomEvent("entries:changed", {
        detail: { count: this.entries.size + this.coreEntries.length },
      }),
    );
  },
};

export default EntryRegistry;
