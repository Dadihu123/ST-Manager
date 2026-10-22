/**
 * static/js/contributionRegistry.js
 * v3 贡献注册表（设计文档 §4.4–§4.6 / §5；实现日志 S3）。
 *
 * 「插件声明、宿主渲染」这条契约的中枢：插件在 manifest 的
 * `frontend.contributions.{menus,slots,commands}` 里静态声明贡献，本模块把它们
 * 收进一张全局表，再由 7 个落点（右键菜单 / 批量菜单 / 命令面板 / 坞栏 /
 * 设置导航）与插槽宿主消费。
 *
 * 职责边界：
 * - 只做「登记 + 过滤 + 排序 + `when` 求值」，不碰 DOM（渲染归各消费者）。
 * - 全局键一律 `<plugin_id>:<id>`，宿主内建命令用 `core:` 前缀，两者永不冲突。
 * - **静态声明是唯一的结构来源**（ADR-0015）：运行期只允许 `update` / `remove`，
 *   不允许新增节点 / 落点 / 节点类型。
 * - `when` 求值失败 = **可见但置灰**（`ok:false` + `reasons`），不是隐藏；
 *   命令面板 / 快捷键只执行 `ok:true` 的项。
 *
 * 数据来源：`/api/plugins/list` 的 `item.manifest.contributions`（`enabled !== false`
 * 的插件）。本模块不 import 任何宿主模块，避免与 `pluginHost.js` 形成循环依赖。
 */

/** 宿主内建命令的插件 id。 */
export const CORE_PLUGIN_ID = "core";

/** kill switch 命令的全局键（`core:plugins:close-overlays`）。 */
export const KILL_SWITCH_COMMAND_ID = "core:plugins:close-overlays";

/** 菜单落点（7 个，与 `core/plugins/contract.py:MENU_PLACEMENTS` 一致）。 */
export const MENU_PLACEMENTS = [
  "context.folder",
  "context.card",
  "context.footer",
  "batch.actions",
  "commandPalette",
  "dock",
  "settings.nav",
];

/** 命名插槽（5 个，与 `contract.py:SLOT_NAMES` 一致）。 */
export const SLOT_NAMES = [
  "settings.section",
  "header.actions",
  "card.detail.tabs",
  "page.cards.toolbar",
  "page.worldinfo.toolbar",
];

/** `empty.<mode>` 插槽前缀（各视图空状态区）。 */
export const EMPTY_SLOT_PREFIX = "empty.";

/** 菜单节点类型。 */
export const MENU_NODE_TYPES = ["item", "submenu", "separator"];

/** `action.type` 合法取值。 */
export const ACTION_TYPES = ["surface", "command", "url"];

/** 宿主工作模式（与 `contract.py:KNOWN_MODES` 一致，`empty.<mode>` 也用这套）。 */
export const KNOWN_MODES = [
  "cards",
  "worldinfo",
  "chats",
  "presets",
  "regex",
  "scripts",
  "quick_replies",
  "beautify",
];

/** 容量上限（与 `contract.py` 一致）。 */
export const MAX_MENU_NODES_PER_PLUGIN = 64;
export const MAX_MENU_DEPTH = 3;
export const MAX_COMMANDS_PER_PLUGIN = 32;
export const MAX_SLOTS_PER_PLUGIN = 16;
export const MAX_DOCK_SLOTS = 8;
export const MAX_DOCK_PER_PLUGIN = 2;

/** 菜单节点默认排序值。 */
export const DEFAULT_ORDER = 100;

/** `update()` 允许的运行期 patch 字段（S3 白名单）。 */
export const UPDATE_PATCH_KEYS = [
  "label",
  "description",
  "icon",
  "badge",
  "progress",
  "status",
  "enabled",
  "disabledHint",
  "busy",
  "children",
];

/**
 * `notifyChange` 允许的最大补发轮数。
 *
 * 监听器在回调里写运行期状态是推荐模式（插件需重放 activate 期间丢失的状态），
 * 所以一次重入是**正常**的，补发一次即可收敛。超过这个轮数说明插件在回调里
 * 反复改写不同值，属于病态行为——停止补发并警告，而不是让页面栈溢出。
 */
export const MAX_NOTIFY_ROUNDS = 5;

/**
 * 密钥「已设置」的哨兵值。
 *
 * `/api/plugins/<id>/config` 只返回 config 段，密钥明文永不回传，因此
 * `when.config.requireKeys` 里的密钥键要靠 `/secrets` 的 `set` 标志折算。
 * 这里用非空哨兵而不是 `true`，是为了让「非空」判定也对布尔真值成立。
 */
const SECRET_SET_SENTINEL = "__set__";

/** 判定 `when.config.requireKeys` 的取值是否算「已配置」。 */
function hasValue(value) {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  return true;
}

/** 读取主程序 store（`Alpine.store("global")`），取不到时返回 null。 */
function readStore() {
  if (typeof window === "undefined") return null;
  const alpine = window.Alpine || window.__ALPINE__;
  if (alpine && typeof alpine.store === "function") {
    return alpine.store("global") || null;
  }
  return null;
}

/** 生成跨插件唯一的全局贡献键（菜单 / 插槽 / 命令各自在有命名空间的 Map 里）。 */
export function buildContributionKey(pluginId, id) {
  return `${String(pluginId || "").trim()}:${String(id || "").trim()}`;
}

/** 语义化版本比较；返回 -1 / 0 / 1，非法版本按 0 处理（视为相等，不误伤）。 */
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

/**
 * `when.hostVersion`：普通语义化版本门槛（主程序 ≥ 该版本时成立）。
 *
 * 设计 §4.4.3 明确「不带比较符」，这里仍兼容旧的 `>=1.0.0` 写法：
 * 迁移期插件可能尚未清洗，宽容解析不会让条件误判为不可用。
 */
function satisfiesHostVersion(actual, required) {
  const text = String(required || "").trim();
  if (!text) return true;

  const match = /^(>=|<=|>|<|=|==)?\s*(.+)$/.exec(text);
  const operator = (match && match[1]) || ">=";
  const target = String(match ? match[2] : text).trim();
  const diff = compareVersions(actual, target);

  if (operator === ">=") return diff >= 0;
  if (operator === "<=") return diff <= 0;
  if (operator === ">") return diff > 0;
  if (operator === "<") return diff < 0;
  return diff === 0;
}

/** 主程序版本：由模板注入的 meta 标签提供（缺失时回退空串）。 */
export function hostAppVersion() {
  if (typeof document === "undefined" || !document.querySelector) return "";
  const meta = document.querySelector('meta[name="app-version"]');
  return meta && meta.content ? String(meta.content) : "";
}

/** 宿主当前设备类型（`store.deviceType`）。取不到 store 时按桌面处理。 */
export function hostDeviceType() {
  const store = readStore();
  return String((store && store.deviceType) || "desktop");
}

/** 是否移动端（`ambient` 与高分屏探测共用）。 */
function isMobileDevice() {
  return hostDeviceType() === "mobile";
}

/**
 * 宿主能力集合（`when.feature` 的取值来源）。
 *
 * 插件声明 `when: { feature: ["hasAmbient"] }` 即可让宿主替它门控，
 * 比插件自己去读 `store.deviceType` 更合规（后者是 Provisional 耦合）。
 */
export function hostFeatures() {
  const features = [];
  if (typeof navigator !== "undefined") {
    if (navigator.onLine !== false) features.push("hasNetwork");
  }
  if (typeof EventSource === "function") features.push("hasSSE");
  if (typeof window !== "undefined" && typeof window.fetch === "function") {
    features.push("hasFetch");
  }
  // 常驻环境层只在桌面/平板上挂载：移动端屏幕小，常驻图层会遮挡内容
  // 且没有「挪开」的手段。
  if (!isMobileDevice()) features.push("hasAmbient");
  // 高分屏探测：留给插件做「2x 帧图」一类的能力门控。
  if (typeof window !== "undefined" && Number(window.devicePixelRatio) >= 1.5) {
    features.push("hasPixelRatio");
  }
  return features;
}

/** `isKnownSlot`：5 个命名插槽 + `empty.<8 个工作模式>`。 */
export function isKnownSlot(name) {
  const value = String(name || "").trim();
  if (!value) return false;
  if (SLOT_NAMES.includes(value)) return true;
  if (!value.startsWith(EMPTY_SLOT_PREFIX)) return false;
  return KNOWN_MODES.includes(value.slice(EMPTY_SLOT_PREFIX.length));
}

/**
 * 求值 `when` 条件表达式（设计 §4.4.3）。
 *
 * 返回 `{ ok, reasons }`：`ok === false` 表示入口**可见但置灰**（不是隐藏），
 * `reasons` 是拒绝原因列表，渲染方用节点的 `disabledHint` 兜底文案。
 *
 * `context` 字段：`{mode, selectionCount, config, hostVersion, feature, indexState}`。
 * v3 已删除 `when.target`：落点（`context.folder` / `context.card`）隐含目标类型。
 */
export function evaluateWhen(when, context = {}) {
  const reasons = [];
  if (!when || typeof when !== "object") return { ok: true, reasons };

  const modes = Array.isArray(when.mode) ? when.mode.map(String) : [];
  if (modes.length && !modes.includes(String(context.mode || ""))) {
    reasons.push("mode");
  }

  const selection = String(when.selection || "").trim();
  if (selection) {
    // `selectionCount` 是宿主视图选中集大小；消费方可以用 `selectionMode`
    // 直接给出 none/any/single/multi 的语义，避免自己去数。
    const explicit = String(context.selectionMode || "").trim();
    const count = Number(context.selectionCount || 0);
    const actual = explicit || (count === 0 ? "none" : count === 1 ? "single" : "multi");
    const ok =
      selection === actual ||
      (selection === "any" && (explicit ? explicit !== "none" : count > 0)) ||
      (selection === "multi" && (explicit ? explicit === "multi" : count > 1));
    if (!ok) reasons.push("selection");
  }

  const indexState = String(when.indexState || "").trim();
  if (indexState && indexState !== String(context.indexState || "")) {
    reasons.push("indexState");
  }

  const requireKeys =
    when.config && Array.isArray(when.config.requireKeys)
      ? when.config.requireKeys.map(String)
      : [];
  if (requireKeys.length) {
    const config = context.config && typeof context.config === "object" ? context.config : {};
    if (requireKeys.some((key) => !hasValue(config[key]))) reasons.push("config");
  }

  const hostVersion = String(when.hostVersion || "").trim();
  if (hostVersion) {
    const actual = String(context.hostVersion || hostAppVersion() || "");
    // 取不到主程序版本时不做门槛判断（否则所有 hostVersion 条件都会被误置灰）。
    if (actual && !satisfiesHostVersion(actual, hostVersion)) reasons.push("hostVersion");
  }

  const features = Array.isArray(when.feature) ? when.feature.map(String) : [];
  if (features.length) {
    const available = new Set(context.feature || hostFeatures());
    if (features.some((name) => !available.has(name))) reasons.push("feature");
  }

  return { ok: reasons.length === 0, reasons };
}

/**
 * 规范化快捷键（设计 §4.6：必须含 Ctrl/Alt/Meta 修饰键）。
 *
 * 比较时不区分大小写、修饰键顺序、空格与 `Cmd`/`Command`/`Option` 别名。
 */
export function normalizeShortcut(combo) {
  const source = String(combo || "").trim();
  if (!source) return "";

  const parts = source
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return "";

  const modifiers = new Set();
  let key = "";
  const modifierAliases = {
    ctrl: "ctrl",
    control: "ctrl",
    alt: "alt",
    option: "alt",
    shift: "shift",
    meta: "meta",
    cmd: "meta",
    command: "meta",
    win: "meta",
    super: "meta",
  };

  for (const part of parts) {
    const lower = part.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(modifierAliases, lower)) {
      modifiers.add(modifierAliases[lower]);
    } else {
      key = lower;
    }
  }

  // 没有修饰键的「快捷键」没有全局意义，视为非法（返回空串）。
  if (!key || !modifiers.size) return "";

  const ordered = ["ctrl", "alt", "shift", "meta"].filter((name) => modifiers.has(name));
  return [...ordered, key].join("+");
}

/** 宿主内建命令（命令面板固定项；kill switch 的唯一前端入口之一）。 */
export const CORE_COMMANDS = Object.freeze([
  Object.freeze({
    id: "plugins:close-overlays",
    key: KILL_SWITCH_COMMAND_ID,
    pluginId: CORE_PLUGIN_ID,
    title: "插件：关闭所有浮动界面",
    description: "强制关闭全部已登记浮层并清空插件自绘根节点（kill switch）。",
    icon: "plugin",
    shortcut: "",
    when: {},
    module: "",
    export: "",
    status: "idle",
    busy: false,
    progress: null,
    enabled: true,
    source: "core",
  }),
].map((item) => ({ ...item })));

/** 给声明层节点补默认值；返回 null 表示节点非法（调用方负责警告 + 丢弃）。 */
function normalizeMenuNode(raw, pluginId, placement, depth) {
  if (!raw || typeof raw !== "object") return null;

  const id = String(raw.id || "").trim();
  if (!id) return null;

  const type = String(raw.type || "item").trim();
  if (!MENU_NODE_TYPES.includes(type)) return null;

  if (type === "separator") {
    return {
      id,
      key: buildContributionKey(pluginId, id),
      pluginId,
      placement,
      type,
      label: "",
      description: "",
      icon: "",
      order: Number.isFinite(Number(raw.order)) ? Number(raw.order) : DEFAULT_ORDER,
      badge: raw.badge === undefined ? null : raw.badge,
      disabledHint: "",
      action: null,
      when: {},
      children: [],
      depth,
      parent: null,
      status: "idle",
      busy: false,
      progress: null,
      enabled: true,
      source: "manifest",
    };
  }

  const label = String(raw.label || "").trim();
  if (!label) return null;

  const action = raw.action && typeof raw.action === "object" ? raw.action : null;
  if (type === "item" && !action) return null;
  if (action) {
    const actionType = String(action.type || "").trim();
    if (!ACTION_TYPES.includes(actionType)) return null;
  }

  const node = {
    id,
    key: buildContributionKey(pluginId, id),
    pluginId,
    placement,
    type,
    label,
    description: String(raw.description || ""),
    icon: String(raw.icon || ""),
    order: Number.isFinite(Number(raw.order)) ? Number(raw.order) : DEFAULT_ORDER,
    badge: raw.badge === undefined ? null : raw.badge,
    disabledHint: String(raw.disabledHint || ""),
    action: action
      ? {
        type: String(action.type),
        id: String(action.id || ""),
        url: String(action.url || ""),
      }
      : null,
    when: raw.when && typeof raw.when === "object" ? raw.when : {},
    children: [],
    // 声明层的原始 children 只在构建期用；`_attachChildren` 处理完即删除。
    _rawChildren: Array.isArray(raw.children) ? raw.children : [],
    depth,
    parent: null,
    status: "idle",
    busy: false,
    progress: null,
    enabled: true,
    source: "manifest",
  };
  return node;
}

/** 生成数组排序比较器：`order` 升序 → `pluginId` → `id`。 */
function compareByOrder(left, right) {
  const leftOrder = Number(left.order);
  const rightOrder = Number(right.order);
  if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  const pluginDiff = String(left.pluginId || "").localeCompare(String(right.pluginId || ""));
  if (pluginDiff !== 0) return pluginDiff;
  return String(left.id || "").localeCompare(String(right.id || ""));
}

/**
 * 取查询方法的求值上下文覆盖。
 *
 * 消费者可以传 `{mode: "cards"}`、`{contextOverride: {…}}` 或
 * `{context: {…}}`——三种写法都接受（多给的字段被 `evaluateWhen` 忽略）。
 */
function overridesOf(options) {
  if (!options || typeof options !== "object") return {};
  return {
    ...(options.contextOverride && typeof options.contextOverride === "object"
      ? options.contextOverride
      : {}),
    ...(options.context && typeof options.context === "object" ? options.context : {}),
    ...options,
  };
}

/** 只读快照：避免消费者改到注册表内部状态。 */
function snapshotRecord(record) {
  const { _rawChildren, ...rest } = record;
  return {
    ...rest,
    action: record.action ? { ...record.action } : null,
    when: { ...(record.when || {}) },
  };
}

export const ContributionRegistry = {
  initialized: false,
  /** 插件列表快照（`enabled !== false`）。 */
  plugins: [],
  /** 全局键 → 菜单节点（含 children 展开后的每个节点）。 */
  menuRecords: new Map(),
  /** 全局键 → `{pluginId}:{slot}` 记录。 */
  slotRecordsMap: new Map(),
  /** 全局键 → 命令记录。 */
  commandRecordsMap: new Map(),
  /** 插件 id → 配置快照（`when.config.requireKeys` 求值用）。 */
  configs: new Map(),
  /** 宿主内建命令（命令面板固定项）。 */
  coreCommands: CORE_COMMANDS.map((item) => ({ ...item })),
  /** `update(children)` 的 action 合法性回调：`(pluginId, action) => boolean`。 */
  _actionAllowed: null,
  /** `notifyChange` 重入保护（见该方法注释）。 */
  _notifying: false,
  _notifyPending: false,
  /** 选中集响应式监听是否已安装（幂等，见 `installSelectionWatcher`）。 */
  _selectionWatcherInstalled: false,

  /** 幂等初始化：监听插件加载 / 配置与密钥 / 模式与选中变化，广播 contributions:changed。 */
  init() {
    if (this.initialized) return;
    this.initialized = true;

    if (typeof window === "undefined" || typeof window.addEventListener !== "function") {
      return;
    }

    // 插件加载完成（含禁用后重载）→ 重建注册表。`detail.items` 由
    // pluginHost.loadAll() 直接带过来时省掉一次 `/api/plugins/list` 请求。
    window.addEventListener("plugins:loaded", (event) => {
      const detail = (event && event.detail) || {};
      if (Array.isArray(detail.items)) {
        this.setPlugins(detail.items);
      } else {
        this.loadFromHost();
      }
    });

    // 配置/密钥变更后刷新缓存，让 `when.config.requireKeys` 立即重算。
    window.addEventListener("plugin-config-changed", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) this.configs.set(String(detail.pluginId), detail.config || {});
      this.notifyChange();
    });
    window.addEventListener("plugin-secrets-changed", (event) => {
      const detail = (event && event.detail) || {};
      if (detail.pluginId) {
        const pluginId = String(detail.pluginId);
        // 密钥也可能参与 requireKeys（如 api_key 写在 secret_schema）。
        // 清除密钥时必须把对应键**摘掉**，否则入口会一直停在可用态。
        const merged = Object.assign({}, this.configs.get(pluginId) || {});
        for (const key of Array.isArray(detail.removed) ? detail.removed : []) {
          delete merged[String(key)];
        }
        Object.assign(merged, detail.config || {});
        this.configs.set(pluginId, merged);
      }
      this.notifyChange();
    });

    // 视图模式 / 选中项变化会影响 `when` 求值结果。
    ["mode-changed", "selection-changed", "refresh-card-list"].forEach((name) => {
      window.addEventListener(name, () => this.notifyChange());
    });

    // 选中集变化必须让 `when` 重算。全仓没有任何地方 dispatch `selection-changed`
    // （cardGrid 直接写 viewState.selectedIds），所以用 Alpine 的响应式 effect
    // 直接观察它——这是唯一可靠的做法（选中集有 6 个写入点）。
    if (!this.installSelectionWatcher()) {
      if (typeof document !== "undefined" && document.addEventListener) {
        document.addEventListener("alpine:initialized", () => {
          this.installSelectionWatcher();
        });
      }
    }
  },

  /**
   * 观察 `viewState.selectedIds`，变化时广播 `contributions:changed`。
   *
   * 幂等：重复调用只装一次。拿不到 Alpine（或它还没就绪）时返回 false，
   * 由 `alpine:initialized` 再试一次。
   */
  installSelectionWatcher() {
    if (this._selectionWatcherInstalled) return true;
    if (typeof window === "undefined") return false;

    const alpine = window.Alpine || window.__ALPINE__;
    if (!alpine || typeof alpine.effect !== "function") return false;

    const readIds = () => {
      const store = typeof alpine.store === "function" ? alpine.store("global") : null;
      const viewState = (store && store.viewState) || {};
      return Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
    };

    let last = readIds().join("\u0000");
    try {
      alpine.effect(() => {
        const next = readIds().join("\u0000");
        if (next === last) return;
        last = next;
        this.notifyChange();
      });
    } catch (error) {
      console.warn("[contributionRegistry] 安装选中集监听失败:", error);
      return false;
    }

    this._selectionWatcherInstalled = true;
    return true;
  },

  /** 从 `/api/plugins/list` 拉取声明并重建注册表（plugins:loaded 的兜底路径）。 */
  async loadFromHost() {
    if (typeof fetch !== "function") return;
    try {
      const response = await fetch("/api/plugins/list", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!data || data.success !== true) return;
      this.setPlugins(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      console.warn("[contributionRegistry] 读取插件列表失败:", error);
    }
  },

  /**
   * 用插件列表快照整体重建声明层（未启用插件不进入注册表）。
   *
   * 运行期的 `update` / `remove` 会被重置——这就是「重新激活恢复静态声明」。
   */
  setPlugins(items) {
    this.plugins = Array.isArray(items)
      ? items.filter((item) => item && item.enabled !== false)
      : [];
    this.menuRecords.clear();
    this.slotRecordsMap.clear();
    this.commandRecordsMap.clear();

    const liveIds = new Set(this.plugins.map((item) => String(item.id || "")));
    for (const pluginId of Array.from(this.configs.keys())) {
      if (!liveIds.has(pluginId)) this.configs.delete(pluginId);
    }

    for (const item of this.plugins) {
      try {
        this._buildPluginRecords(item);
      } catch (error) {
        console.warn(
          `[contributionRegistry] 插件 ${item && item.id} 的贡献声明解析失败:`,
          error,
        );
      }
    }

    this.notifyChange();
    this.ensureConfigs().catch(() => null);
  },

  /** 移除某个插件的全部贡献（禁用 / 卸载 / destroy 时调用）。 */
  removePlugin(pluginId) {
    const key = String(pluginId || "");
    if (!key) return false;
    const prefix = `${key}:`;
    let changed = false;
    for (const map of [this.menuRecords, this.slotRecordsMap, this.commandRecordsMap]) {
      for (const recordKey of Array.from(map.keys())) {
        if (recordKey.startsWith(prefix)) {
          map.delete(recordKey);
          changed = true;
        }
      }
    }
    this.configs.delete(key);
    if (changed) this.notifyChange();
    return changed;
  },

  /** 读取一个插件的静态贡献声明（兼容 manifest 快照与 item 顶层快照）。 */
  _contributionsOf(item) {
    const manifest = (item && item.manifest) || {};
    const fromManifest = manifest.contributions;
    if (fromManifest && typeof fromManifest === "object") return fromManifest;
    const fromItem = item && item.contributions;
    return fromItem && typeof fromItem === "object" ? fromItem : {};
  },

  /** 把单个插件的 commands / slots / menus 收进注册表。 */
  _buildPluginRecords(item) {
    const pluginId = String((item && item.id) || "").trim();
    if (!pluginId) return;

    const contributions = this._contributionsOf(item);

    // ---------------- commands（先建，菜单 action 引用要校验） ----------------
    const rawCommands = Array.isArray(contributions.commands) ? contributions.commands : [];
    let commandCount = 0;
    for (const raw of rawCommands) {
      if (commandCount >= MAX_COMMANDS_PER_PLUGIN) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 命令数超过 ${MAX_COMMANDS_PER_PLUGIN}，多余命令已丢弃`,
        );
        break;
      }
      if (!raw || typeof raw !== "object") continue;
      const id = String(raw.id || "").trim();
      const title = String(raw.title || "").trim();
      if (!id || !title) continue;
      commandCount += 1;
      this.commandRecordsMap.set(buildContributionKey(pluginId, id), {
        id,
        key: buildContributionKey(pluginId, id),
        pluginId,
        title,
        description: String(raw.description || ""),
        icon: String(raw.icon || ""),
        shortcut: String(raw.shortcut || ""),
        when: raw.when && typeof raw.when === "object" ? raw.when : {},
        module: String(raw.module || ""),
        export: String(raw.export || ""),
        status: "idle",
        busy: false,
        progress: null,
        enabled: true,
        source: "manifest",
      });
    }

    const commandIds = new Set(
      Array.from(this.commandRecordsMap.values())
        .filter((record) => record.pluginId === pluginId)
        .map((record) => record.id),
    );

    // ---------------- slots ----------------
    const rawSlots = Array.isArray(contributions.slots) ? contributions.slots : [];
    let slotCount = 0;
    for (const raw of rawSlots) {
      if (slotCount >= MAX_SLOTS_PER_PLUGIN) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 插槽数超过 ${MAX_SLOTS_PER_PLUGIN}，多余插槽已丢弃`,
        );
        break;
      }
      if (!raw || typeof raw !== "object") continue;
      const id = String(raw.id || "").trim();
      const slot = String(raw.slot || "").trim();
      if (!id || !slot) continue;
      if (!isKnownSlot(slot)) {
        console.warn(`[contributionRegistry] 插件 ${pluginId} 声明了未知插槽，已丢弃: ${slot}`);
        continue;
      }
      const module = String(raw.module || "").trim();
      const exportName = String(raw.export || "").trim();
      if (!module || !exportName) {
        console.warn(`[contributionRegistry] 插件 ${pluginId} 插槽 ${id} 缺少 module/export，已丢弃`);
        continue;
      }
      slotCount += 1;
      this.slotRecordsMap.set(buildContributionKey(pluginId, id), {
        id,
        key: buildContributionKey(pluginId, id),
        pluginId,
        slot,
        title: String(raw.title || ""),
        order: Number.isFinite(Number(raw.order)) ? Number(raw.order) : DEFAULT_ORDER,
        when: raw.when && typeof raw.when === "object" ? raw.when : {},
        module,
        export: exportName,
        status: "idle",
        busy: false,
        progress: null,
        enabled: true,
        source: "manifest",
      });
    }

    // ---------------- menus（扁平列表 + 显式树） ----------------
    const rawMenus = Array.isArray(contributions.menus) ? contributions.menus : [];
    // 单插件菜单节点上限 64（含子节点）。用一个共享计数器同时约束根节点与 children。
    const menuCounter = { count: 0 };
    for (const raw of rawMenus) {
      if (!raw || typeof raw !== "object") continue;
      if (menuCounter.count >= MAX_MENU_NODES_PER_PLUGIN) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 菜单节点数超过 ${MAX_MENU_NODES_PER_PLUGIN}，多余节点已丢弃`,
        );
        break;
      }
      const placement = String(raw.placement || "").trim();
      if (!MENU_PLACEMENTS.includes(placement)) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 声明了未知落点，已丢弃: ${placement || "(空)"}`,
        );
        continue;
      }
      // 静态声明路径：surface 的 id 运行期才存在，安装期只校验格式（设计 §4.3）。
      const staticActionOptions = { requireRegisteredSurface: false };
      const root = this._buildMenuNode(
        raw,
        pluginId,
        placement,
        1,
        commandIds,
        staticActionOptions,
      );
      if (!root) continue;
      menuCounter.count += 1;
      this._attachChildren(root, pluginId, commandIds, menuCounter, staticActionOptions);
    }
  },

  /** 递归构建子节点；用共享计数器核算单插件 64 节点上限。 */
  _attachChildren(parent, pluginId, commandIds, counter, actionOptions = {}) {
    const rawChildren = Array.isArray(parent._rawChildren) ? parent._rawChildren : [];
    delete parent._rawChildren;
    if (parent.type !== "submenu" || !rawChildren.length) return 0;
    let count = 0;
    for (const raw of rawChildren) {
      if (!raw || typeof raw !== "object") continue;
      if (counter.count >= MAX_MENU_NODES_PER_PLUGIN) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 菜单节点数超过 ${MAX_MENU_NODES_PER_PLUGIN}，多余节点已丢弃`,
        );
        break;
      }
      if (parent.depth >= MAX_MENU_DEPTH) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 菜单深度超过 ${MAX_MENU_DEPTH}，更深节点已丢弃`,
        );
        break;
      }
      const child = this._buildMenuNode(
        raw,
        pluginId,
        parent.placement,
        parent.depth + 1,
        commandIds,
        actionOptions,
      );
      if (!child) continue;
      child.parent = parent.key;
      parent.children.push(child);
      this.menuRecords.set(child.key, child);
      counter.count += 1;
      count += 1;
      count += this._attachChildren(child, pluginId, commandIds, counter, actionOptions);
    }
    return count;
  },

  /** 构建单个菜单节点并校验 `action` 引用；非法节点返回 null。 */
  _buildMenuNode(raw, pluginId, placement, depth, commandIds, actionOptions = {}) {
    const node = normalizeMenuNode(raw, pluginId, placement, depth);
    if (!node) {
      console.warn(`[contributionRegistry] 插件 ${pluginId} 存在非法菜单节点，已丢弃`);
      return null;
    }
    if (node.action) {
      const allowed = this._isAllowedAction(pluginId, node.action, commandIds, actionOptions);
      if (!allowed) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 菜单节点 ${node.id} 的 action 引用非法，已丢弃`,
        );
        return null;
      }
    }
    this.menuRecords.set(node.key, node);
    return node;
  },

  /**
   * 校验 action：command 必须已声明；url 必须 http(s)；surface 视路径而定。
   *
   * `options.requireRegisteredSurface` 是**显式**的路径开关，不能靠
   * `setActionValidator` 是否已注入来判断（插件加载顺序不保证，ingest 时回调可能
   * 已经存在）：
   * - `false`（默认）：静态 manifest ingest（设计 §4.3）——surface 的 id 运行期才
   *   存在，安装期**只校验非空 id 格式**；未注册时点击层面再警告并忽略；
   * - `true`：`api.contributions.update({children})`（设计 §6）——child 的
   *   surface 必须已由 `api.surfaces.register()` 注册，否则整包 patch 拒绝。
   */
  _isAllowedAction(pluginId, action, commandIds = null, options = {}) {
    if (!action || typeof action !== "object") return false;
    const type = String(action.type || "");
    if (!ACTION_TYPES.includes(type)) return false;
    if (type === "command") {
      const commandId = String(action.id || "");
      if (!commandId) return false;
      const known = commandIds || new Set(
        Array.from(this.commandRecordsMap.values())
          .filter((record) => record.pluginId === pluginId)
          .map((record) => record.id),
      );
      return known.has(commandId);
    }
    if (type === "url") {
      return /^https?:\/\//i.test(String(action.url || ""));
    }
    if (type === "surface") {
      const surfaceId = String(action.id || "");
      if (!surfaceId) return false;
      // 静态声明路径：只校验格式（设计 §4.3）。
      if (!options || options.requireRegisteredSurface !== true) return true;
      // 运行期 children 路径：要求已注册（设计 §6）。无宿主注入回调时（注册表被
      // 单独使用）退回格式校验，宿主环境下 `pluginHost.init()` 一定会注入。
      if (typeof this._actionAllowed === "function") {
        try {
          return Boolean(this._actionAllowed(pluginId, action));
        } catch (error) {
          console.warn("[contributionRegistry] action 校验回调抛错:", error);
          return false;
        }
      }
      return true;
    }
    return false;
  },

  /** 注入 `action` 合法性回调（pluginHost 用它把「已注册 surface」纳入校验）。 */
  setActionValidator(validator) {
    this._actionAllowed = typeof validator === "function" ? validator : null;
  },

  /**
   * 按需拉取参与 `when.config.requireKeys` 的插件配置。
   *
   * `requireKeys` 同时检查 `config_schema` 与 `secret_schema`；但
   * `/api/plugins/<id>/config` 只返回 config 段（密钥永不回传明文），所以密钥键
   * 必须另外查 `/secrets` 的 `set` 标志，折算成非空哨兵。
   */
  async ensureConfigs() {
    const needed = new Map();
    const collect = (record) => {
      const keys = record.when && record.when.config ? record.when.config.requireKeys : null;
      if (!Array.isArray(keys) || !keys.length) return;
      if (!needed.has(record.pluginId)) needed.set(record.pluginId, new Set());
      for (const key of keys) needed.get(record.pluginId).add(String(key));
    };
    for (const map of [this.menuRecords, this.slotRecordsMap, this.commandRecordsMap]) {
      for (const record of map.values()) collect(record);
    }
    if (!needed.size || typeof fetch !== "function") return;

    await Promise.all(
      Array.from(needed.entries()).map(async ([pluginId, keys]) => {
        if (this.configs.has(pluginId)) return;

        const merged = {};
        try {
          const response = await fetch(`/api/plugins/${encodeURIComponent(pluginId)}/config`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          const data = await response.json();
          if (data && data.success && data.config && typeof data.config === "object") {
            Object.assign(merged, data.config);
          }
        } catch (error) {
          // 读不到配置就当作未配置（入口置灰而不是报错）
        }

        const missing = Array.from(keys).filter((key) => !hasValue(merged[key]));
        if (missing.length) {
          try {
            const response = await fetch(`/api/plugins/${encodeURIComponent(pluginId)}/secrets`, {
              headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const data = await response.json();
            const described = data && data.success ? data.secrets || {} : {};
            for (const key of missing) {
              const meta = described[key];
              if (meta && meta.set) merged[key] = SECRET_SET_SENTINEL;
            }
          } catch (error) {
            // 密钥读不到时保持缺失，入口置灰
          }
        }

        this.configs.set(pluginId, merged);
      }),
    );
    this.notifyChange();
  },

  /** 设置插件的配置快照（测试 / 外部刷新用）。 */
  setPluginConfig(pluginId, config) {
    this.configs.set(String(pluginId || ""), config && typeof config === "object" ? config : {});
    this.notifyChange();
    return true;
  },

  /** 推断索引作业状态（`when.indexState` 求值用）。 */
  _indexState(store) {
    const index = (store && store.indexStatus) || {};
    const value = String(index.state || "");
    if (value === "building" || index.scan_active) return "running";
    return "idle";
  },

  /**
   * 构造 `when` 求值上下文。
   *
   * 形状：`{mode, selectionCount, config, hostVersion, feature, indexState}`；
   * `config` 是**单个插件**的配置，因此求值统一走 `_contextFor(pluginId)`。
   */
  context(overrides = {}) {
    const store = readStore();
    const viewState = (store && store.viewState) || {};
    const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
    const selectionCount =
      overrides.selectionCount !== undefined && overrides.selectionCount !== null
        ? Number(overrides.selectionCount) || 0
        : ids.length;

    return {
      mode: overrides.mode !== undefined ? String(overrides.mode) : String((store && store.currentMode) || ""),
      selectionCount,
      selectionMode: String(overrides.selectionMode || ""),
      config: overrides.config && typeof overrides.config === "object" ? overrides.config : {},
      hostVersion: String(overrides.hostVersion || hostAppVersion() || ""),
      feature: Array.isArray(overrides.feature) ? overrides.feature : hostFeatures(),
      indexState: overrides.indexState !== undefined
        ? String(overrides.indexState)
        : this._indexState(store),
    };
  },

  /** 为某个插件的记录构造上下文（把该插件的配置并进去）。 */
  _contextFor(pluginId, overrides = {}) {
    const context = this.context(overrides);
    context.config = this.configs.get(String(pluginId || "")) || context.config || {};
    return context;
  },

  /** 给记录附加 `ok/reasons/enabled`（只读快照）。 */
  _decorate(record, pluginId, overrides = {}) {
    const context = this._contextFor(pluginId, overrides);
    const result = evaluateWhen(record.when, context);
    const enabled = result.ok && record.enabled !== false;
    return {
      ...snapshotRecord(record),
      ok: result.ok,
      reasons: result.reasons,
      enabled,
    };
  },

  /** 递归装饰菜单节点（children 一并装饰）。 */
  _decorateNode(record, overrides = {}) {
    const decorated = this._decorate(record, record.pluginId, overrides);
    decorated.children = (record.children || []).map((child) => this._decorateNode(child, overrides));
    return decorated;
  },

  /**
   * 一个落点的根节点数组（children 递归），排序：`order` → `pluginId` → `id`。
   *
   * 每个节点带 `ok` / `reasons` / `enabled`：`when` 不满足时**仍然返回**
   * （渲染方可置灰），`options.enabledOnly` 为 true 时只返回可执行的节点。
   */
  menuTree(placement, options = {}) {
    const name = String(placement || "");
    const roots = [];
    for (const record of this.menuRecords.values()) {
      if (record.parent || record.placement !== name) continue;
      roots.push(record);
    }
    roots.sort(compareByOrder);
    const overrides = overridesOf(options);
    const decorated = roots.map((record) => this._decorateNode(record, overrides));
    if (!options.enabledOnly) return decorated;
    return decorated.filter((node) => node.ok && node.enabled !== false);
  },

  /** 根层扁平别名（`menus(placement)` 与 `menuTree(placement)` 同义）。 */
  menus(placement, options = {}) {
    return this.menuTree(placement, options);
  },

  /** 某个插槽的贡献记录数组（排序：`order` → `pluginId` → `id`）。 */
  slotRecords(slot, options = {}) {
    const name = String(slot || "");
    const records = Array.from(this.slotRecordsMap.values())
      .filter((record) => record.slot === name)
      .sort(compareByOrder);
    const decorated = records.map((record) =>
      this._decorate(record, record.pluginId, overridesOf(options)));
    if (!options.enabledOnly) return decorated;
    return decorated.filter((record) => record.ok && record.enabled !== false);
  },

  /** 全部命令记录数组（排序：`order` → `pluginId` → `id`）。 */
  commandRecords(options = {}) {
    const records = Array.from(this.commandRecordsMap.values()).sort(compareByOrder);
    const decorated = records.map((record) =>
      this._decorate(record, record.pluginId, overridesOf(options)));
    if (!options.enabledOnly) return decorated;
    return decorated.filter((record) => record.ok && record.enabled !== false);
  },

  /** `commandPalette` 菜单项若引用命令，返回该命令的全局 key，否则空串。 */
  _paletteCommandKey(menu) {
    const action = menu && menu.action;
    if (!action || action.type !== "command") return "";
    return buildContributionKey(menu.pluginId, action.id);
  },

  /**
   * 命令面板候选：命令 + `commandPalette` 落点菜单根节点。
   *
   * **每个 entry 的 `key` 全局唯一且非空**（面板模板 `x-for :key="entry.key"`，
   * 重复 key 会让 Alpine 的 reorder 分支拿不到节点而整列表空白）。
   *
   * 合并规则（设计 §10.2：AI 同时声明 3 条命令 + 3 项 commandPalette 菜单）：
   * - `action.type === "command"` 的菜单项与对应命令记录**合并为一行**，同一命令
   *   即使被多个菜单引用也只出现一行（取排序后第一条菜单的展示字段）；
   *   菜单的 `label` / `icon` / `description` / `badge` / `disabledHint` 覆盖展示，
   *   命令的 `shortcut` / `module` / `export` / `when` / `id` 保证执行语义；
   * - `action.type === "surface" | "url"` 的菜单项保留为 `kind:"menu"`；
   * - 命令 key 与菜单 key 撞名（插件用同一个 id 同时声明命令与菜单）时给菜单项
   *   追加 `#menu` 后缀，命令/菜单各自仍只出现一次。
   *
   * 返回扁平数组（命令在前），每项带 `kind: "command" | "menu"`。
   */
  paletteEntries(options = {}) {
    const commands = this.commandRecords(options);
    const menus = this.menuTree("commandPalette", options);

    const commandByKey = new Map(commands.map((record) => [record.key, record]));
    // 命令 key → 排序后第一条引用它的 commandPalette 菜单项（展示字段来源）。
    const paletteMenuByCommand = new Map();
    for (const menu of menus) {
      const commandKey = this._paletteCommandKey(menu);
      if (!commandKey || !commandByKey.has(commandKey)) continue;
      if (!paletteMenuByCommand.has(commandKey)) paletteMenuByCommand.set(commandKey, menu);
    }

    const usedKeys = new Set();
    const entries = [];
    const push = (entry, suffixHint = "menu") => {
      const base = String((entry && entry.key) || "");
      if (!base) return;
      let key = base;
      if (usedKeys.has(key)) {
        key = `${base}#${suffixHint}`;
        let index = 2;
        while (usedKeys.has(key)) {
          key = `${base}#${suffixHint}${index}`;
          index += 1;
        }
      }
      usedKeys.add(key);
      entries.push({ ...entry, key });
    };

    for (const command of commands) {
      const menu = paletteMenuByCommand.get(command.key);
      if (!menu) {
        push({ ...command, kind: "command" });
        continue;
      }
      push({
        ...command,
        // 派发用菜单节点 id（`contribution:trigger` 的 nodeId 要能在菜单表里查到），
        // key 保持命令 key 作为面板行身份。
        id: menu.id,
        kind: "command",
        label: String(menu.label || command.title || ""),
        title: String(command.title || ""),
        description: String(menu.description || command.description || ""),
        icon: String(menu.icon || command.icon || ""),
        badge: menu.badge !== undefined && menu.badge !== null ? menu.badge : command.badge,
        progress: menu.progress !== undefined && menu.progress !== null
          ? menu.progress
          : command.progress,
        order: menu.order,
        disabledHint: String(menu.disabledHint || ""),
        when: { ...(command.when || {}) },
        ok: Boolean(command.ok) && Boolean(menu.ok),
        enabled: command.enabled !== false && menu.enabled !== false,
        reasons: Array.from(new Set([...(command.reasons || []), ...(menu.reasons || [])])),
      });
    }

    for (const menu of menus) {
      const commandKey = this._paletteCommandKey(menu);
      if (commandKey && commandByKey.has(commandKey)) continue; // 已合并，不再单独列出
      push({ ...menu, kind: "menu" });
    }
    return entries;
  },

  /**
   * 坞栏分配：全局 ≤ `MAX_DOCK_SLOTS`、单插件 ≤ `MAX_DOCK_PER_PLUGIN`。
   *
   * 分配规则：排序后依次占位；单插件超出 2 个或全局超出 8 个的进入溢出集，
   * 由宿主渲染的「更多」浮层消费。
   */
  _partitionDock() {
    const roots = Array.from(this.menuRecords.values())
      .filter((record) => !record.parent && record.placement === "dock")
      .filter((record) => record.type !== "separator")
      .sort(compareByOrder);

    const visible = [];
    const overflow = [];
    const perPlugin = new Map();
    for (const record of roots) {
      const used = perPlugin.get(record.pluginId) || 0;
      if (visible.length >= MAX_DOCK_SLOTS || used >= MAX_DOCK_PER_PLUGIN) {
        overflow.push(this._decorateNode(record));
        continue;
      }
      perPlugin.set(record.pluginId, used + 1);
      visible.push(this._decorateNode(record));
    }
    return { visible, overflow };
  },

  /** 坞栏可见项（全局 ≤ 8、单插件 ≤ 2）。 */
  dockItems() {
    return this._partitionDock().visible;
  },

  /** 坞栏溢出项（进入「更多」浮层）。 */
  dockOverflow() {
    return this._partitionDock().overflow;
  },

  /**
   * 兼容入口总览：菜单节点（全部落点、含 children）+ 命令 + 宿主内建命令。
   *
   * 该接口服务于插件管理器 / 快捷键总览等聚合视图；命令面板请用
   * `paletteEntries()`（它只返回可执行项）。每项带 `kind` 字段。
   */
  searchable() {
    const menus = [];
    for (const record of Array.from(this.menuRecords.values()).sort(compareByOrder)) {
      menus.push({ ...this._decorateNode(record), kind: "menu" });
    }
    const commands = this.commandRecords().map((record) => ({ ...record, kind: "command" }));
    const core = this.coreCommands.map((record) => ({ ...record, ok: true, reasons: [], kind: "command" }));
    return [...menus, ...commands, ...core];
  },

  /**
   * 快捷键查表（命令 + 宿主内建命令，规范化比较）。
   *
   * 设计 §4.6：快捷键与 when 无关，按下时求值，不满足则忽略——因此这里只返回
   * `ok:true` 的命令；没有匹配或条件不满足都返回 null。
   */
  findByShortcut(combo) {
    const normalized = normalizeShortcut(combo);
    if (!normalized) return null;

    const candidates = [...this.commandRecords(), ...this.coreCommands];
    for (const record of candidates) {
      if (normalizeShortcut(record.shortcut) !== normalized) continue;
      const decorated = record.pluginId === CORE_PLUGIN_ID
        ? { ...record, ok: true, reasons: [], enabled: true }
        : this._decorate(record, record.pluginId);
      if (decorated.ok && decorated.enabled !== false) return decorated;
    }
    return null;
  },

  /** 菜单节点：`(pluginId, id)`；不存在 → null。 */
  get(pluginId, id) {
    const record = this.menuRecords.get(buildContributionKey(pluginId, id));
    if (!record) return null;
    return this._decorateNode(record);
  },

  /** 全局键 `<pluginId>:<id>` 查询；不存在 → null。 */
  getByKey(key) {
    const record = this.menuRecords.get(String(key || ""));
    if (!record) return null;
    return this._decorateNode(record);
  },

  /** 本插件全部菜单节点（扁平，含 children）。 */
  list(pluginId) {
    const key = String(pluginId || "");
    return Array.from(this.menuRecords.values())
      .filter((record) => record.pluginId === key)
      .sort(compareByOrder)
      .map((record) => this._decorateNode(record));
  },

  /** 插槽 / 命令的单条查询（渲染方 / 执行器用）。 */
  getSlot(pluginId, id) {
    const record = this.slotRecordsMap.get(buildContributionKey(pluginId, id));
    return record ? this._decorate(record, record.pluginId) : null;
  },

  getCommand(pluginId, id) {
    const record = this.commandRecordsMap.get(buildContributionKey(pluginId, id));
    return record ? this._decorate(record, record.pluginId) : null;
  },

  /**
   * 更新一个菜单节点的运行期状态（S3 patch 白名单）。
   *
   * - 节点不存在 / 已被移除 / patch 非法 → `false`。
   * - `children` 只允许用于 `submenu`，完整替换子节点；每个子节点必须带 `id`，
   *   `action` 只能引用已声明命令或**已注册** surface（运行期路径，设计 §6；
   *   静态 manifest ingest 在安装期只校验 surface id 格式，见 §4.3）；任一子节点
   *   非法 → **整个 patch 拒绝**（返回 false + 警告）。
   * - 同值写入不广播（打断 `contributions:changed` 的重入递归）。
   */
  update(pluginId, id, patch) {
    const record = this.menuRecords.get(buildContributionKey(pluginId, id));
    if (!record || !patch || typeof patch !== "object") return false;

    // 先做完整校验：children 非法时整个 patch 拒绝（不能只更新一半）。
    let nextChildren = null;
    if (Object.prototype.hasOwnProperty.call(patch, "children")) {
      if (record.type !== "submenu") {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 节点 ${record.id} 不是 submenu，children 被忽略`,
        );
        return false;
      }
      nextChildren = this._parseChildrenPatch(pluginId, record, patch.children);
      if (nextChildren === null) return false;
    }

    let changed = false;
    const assign = (field, value) => {
      if (Object.is(record[field], value)) return;
      record[field] = value;
      changed = true;
    };

    if ("label" in patch) assign("label", String(patch.label ?? ""));
    if ("description" in patch) assign("description", String(patch.description ?? ""));
    if ("icon" in patch) assign("icon", String(patch.icon ?? ""));
    if ("badge" in patch) {
      assign("badge", patch.badge === undefined || patch.badge === null ? null : patch.badge);
    }
    if ("progress" in patch) {
      let next = null;
      if (patch.progress !== null && patch.progress !== undefined && patch.progress !== "") {
        const number = Number(patch.progress);
        if (Number.isFinite(number)) next = Math.min(1, Math.max(0, number));
      }
      assign("progress", next);
    }
    if ("status" in patch) assign("status", String(patch.status ?? ""));
    if ("enabled" in patch) assign("enabled", patch.enabled !== false);
    if ("disabledHint" in patch) assign("disabledHint", String(patch.disabledHint ?? ""));
    if ("busy" in patch) assign("busy", Boolean(patch.busy));
    if (nextChildren !== null) {
      // children 是完整替换：先摘掉旧子树的扁平记录，再挂新子树。
      this._removeDescendants(record);
      record.children = [];
      for (const child of nextChildren) this._indexSubtree(record, child);
      changed = true;
    }

    if (changed) this.notifyChange();
    return true;
  },

  /** 解析 `update({children})` 的子树；任何非法都返回 null（拒绝整个 patch）。 */
  _parseChildrenPatch(pluginId, parent, children) {
    if (!Array.isArray(children)) {
      console.warn(`[contributionRegistry] 插件 ${pluginId} 的 children patch 不是数组`);
      return null;
    }
    if (parent.depth >= MAX_MENU_DEPTH) {
      console.warn(
        `[contributionRegistry] 插件 ${pluginId} 的 children 超过菜单深度上限 ${MAX_MENU_DEPTH}`,
      );
      return null;
    }

    const commandIds = new Set(
      Array.from(this.commandRecordsMap.values())
        .filter((record) => record.pluginId === pluginId)
        .map((record) => record.id),
    );
    const usedKeys = new Set();
    return this._parseChildrenPatchInto(pluginId, parent, children, commandIds, usedKeys);
  },

  /** `_parseChildrenPatch` 的递归实现：解析一层并把更深层继续挂上。 */
  _parseChildrenPatchInto(pluginId, parent, children, commandIds, usedKeys) {
    if (!children.length) return [];
    if (parent.type !== "submenu") {
      console.warn(`[contributionRegistry] 插件 ${pluginId} 的非 submenu 节点不能有 children`);
      return null;
    }
    const parsed = [];
    for (const raw of children) {
      const child = normalizeMenuNode(raw, pluginId, parent.placement, parent.depth + 1);
      if (!child) {
        console.warn(`[contributionRegistry] 插件 ${pluginId} 的 children 中存在非法节点`);
        return null;
      }
      if (usedKeys.has(child.key) || this.menuRecords.has(child.key)) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 的 children 节点 id 重复或已存在: ${child.id}`,
        );
        return null;
      }
      // 运行期 children 路径：surface 必须已注册（设计 §6），整包拒绝而非降级。
      if (
        child.action
        && !this._isAllowedAction(pluginId, child.action, commandIds, {
          requireRegisteredSurface: true,
        })
      ) {
        console.warn(
          `[contributionRegistry] 插件 ${pluginId} 的 children 节点 ${child.id} action 引用非法`,
        );
        return null;
      }
      usedKeys.add(child.key);

      const rawGrandChildren = Array.isArray(child._rawChildren) ? child._rawChildren : [];
      delete child._rawChildren;
      if (rawGrandChildren.length) {
        if (child.depth >= MAX_MENU_DEPTH) {
          console.warn(
            `[contributionRegistry] 插件 ${pluginId} 的 children 超过菜单深度上限 ${MAX_MENU_DEPTH}`,
          );
          return null;
        }
        const grandchildren = this._parseChildrenPatchInto(
          pluginId,
          child,
          rawGrandChildren,
          commandIds,
          usedKeys,
        );
        if (grandchildren === null) return null;
        child.children = grandchildren;
      }
      parsed.push(child);
    }
    return parsed;
  },

  /** 递归删除某个节点的全部后代扁平记录。 */
  _removeDescendants(record) {
    for (const child of record.children || []) {
      this._removeDescendants(child);
      this.menuRecords.delete(child.key);
    }
  },

  /** 递归把子树挂进扁平索引（`update({children})` 用）。 */
  _indexSubtree(parent, node) {
    node.parent = parent.key;
    parent.children.push(node);
    this.menuRecords.set(node.key, node);
    for (const child of node.children || []) this._indexSubtree(node, child);
  },

  /**
   * 移除一个菜单节点（本次激活内有效；重新激活恢复静态声明）。
   *
   * 移除 submenu 时其子树一并移除；返回是否真的移除。
   */
  remove(pluginId, id) {
    const key = buildContributionKey(pluginId, id);
    const record = this.menuRecords.get(key);
    if (!record) return false;

    if (record.parent) {
      const parent = this.menuRecords.get(record.parent);
      if (parent) {
        parent.children = parent.children.filter((child) => child.key !== key);
      }
    }
    this._removeDescendants(record);
    this.menuRecords.delete(key);
    this.notifyChange();
    return true;
  },

  /**
   * 派发 `contributions:changed`。
   *
   * 重入保护：监听器在回调里写运行期状态是推荐模式，补发有限轮次即可收敛；
   * 病态插件持续改写不同值时停止补发并警告，而不是让页面栈溢出。
   */
  notifyChange() {
    if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;

    if (this._notifying) {
      this._notifyPending = true;
      return;
    }

    this._notifying = true;
    let rounds = 0;
    try {
      do {
        this._notifyPending = false;
        window.dispatchEvent(
          new CustomEvent("contributions:changed", {
            detail: { count: this.menuRecords.size },
          }),
        );
        rounds += 1;
      } while (this._notifyPending && rounds < MAX_NOTIFY_ROUNDS);

      if (this._notifyPending) {
        console.warn(
          "[contributionRegistry] contributions:changed 连续重入过多，已停止补发；" +
            "插件可能在监听回调里持续改写运行期状态。",
        );
      }
    } finally {
      this._notifying = false;
      this._notifyPending = false;
    }
  },
};

export default ContributionRegistry;
