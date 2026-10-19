/**
 * static/js/components/pluginManager.js
 * 插件管理面板（设计文档第 9 部分）。
 *
 * 作为「系统设置 → 插件管理」第五个导航页嵌入设置弹窗，不再自带模态框外壳。
 * 三个页签：
 * - 已安装：状态 + 四操作（安装/卸载/禁用/启用）+ 配置与密钥表单
 * - 官方目录：catalog 条目 + 安装 + 检查更新
 * - 手动安装：zip 上传 + 元数据确认
 */

import {
  checkPluginUpdates,
  deletePluginSecret,
  disablePlugin,
  enablePlugin,
  getPluginCatalog,
  getPluginConfig,
  getPluginList,
  getPluginReadme,
  getPluginSecrets,
  installPluginFromCatalog,
  installPluginFromGithub,
  savePluginConfig,
  savePluginSecrets,
  uninstallPlugin,
  uploadPluginArchive,
  updatePluginFromCatalog,
} from "../api/plugins.js";
import { icon } from "../uiPrimitives.js";
import { EntryRegistry, compareVersions } from "../entryRegistry.js";
import { PluginSurfaceHost } from "../pluginSurfaceHost.js";

const PERMISSION_LABELS = {
  "cards.read": "读取角色卡",
  "cards.write": "修改角色卡",
  "worldbook.read": "读取世界书",
  "worldbook.write": "修改世界书",
  "tags.read": "读取标签",
  "tags.write": "写入标签",
  "secrets.read": "读取密钥",
  "network.outbound": "访问网络",
  "jobs.run": "运行后台作业",
};

// 设置页搜索结果的锚点 → 面板页签：让「搜索设置」能直接落到对应插件页签。
// 另支持 `plugin-config-<id>` / `plugin-secrets-<id>` 语义（阶段 6.2 深链）：
// 切到「已安装」页签 + 自动展开对应表单 + 滚动到位。
const ANCHOR_TABS = {
  "plugin-panel-installed": "installed",
  "plugin-panel-catalog": "catalog",
  "plugin-panel-upload": "upload",
  "plugin-panel-entries": "entries",
};

const CONFIG_ANCHOR_PATTERN = /^plugin-config-(.+)$/;
const SECRET_ANCHOR_PATTERN = /^plugin-secrets-(.+)$/;

/** 归属分级徽标文案（D5）。 */
const TIER_LABELS = {
  official: "官方",
  verified: "认证",
  community: "社区",
};

/** 入口 kind 的中文标签（D1）。 */
const ENTRY_KIND_LABELS = {
  dock: "坞",
  nav: "导航",
  settings: "设置",
  context: "右键",
  command: "命令",
  status: "状态",
  batch: "批量",
};

/**
 * 入口出现位置的说明（总览页「出现位置」列）。
 *
 * **必须如实描述**：`nav` / `status` 两种 kind 目前宿主**没有任何渲染消费者**。
 * 旧文案写「侧栏导航 / 状态栏」会让用户以为入口已经生效，实际点了什么都不会发生。
 *
 * `settings` 自本次起**已有消费者**：渲染为插件管理页内的「插件设置入口」区块
 * （见 `settingsEntries` / `openSettingsEntry`）。
 */
const ENTRY_LOCATION_LABELS = {
  dock: "入口坞",
  nav: "宿主未实现",
  settings: "插件管理页",
  context: "右键菜单",
  command: "命令面板",
  status: "宿主未实现",
  batch: "批量操作菜单",
};

/**
 * 该 kind 是否有真实的渲染消费者。
 *
 * 用于总览页给未实现的 kind 打上「未实现」标记——这比一句文案更难被忽略。
 */
const IMPLEMENTED_ENTRY_KINDS = new Set(["dock", "context", "command", "batch", "settings"]);

/** 当前呈现方式的说明（总览页「当前呈现」列）。 */
const SURFACE_LABELS = {
  panel: "右侧抽屉",
  modal: "模态框",
  page: "整页",
  sheet: "底部面板",
};

function toast(message, type = "info") {
  if (window.Alpine && typeof window.Alpine.store === "function") {
    const store = window.Alpine.store("global");
    if (store && typeof store.showToast === "function") {
      store.showToast(message, type === "error" ? 4200 : 3000);
      return;
    }
  }
  console.log("[pluginManager]", message);
}

export default function pluginManager() {
  return {
    activeTab: "installed",
    loading: false,
    busyAction: "",
    errorMessage: "",

    /** 正在录制快捷键的入口键（空 = 未录制）。 */
    recordingKey: "",

    plugins: [],
    pluginsDir: "",
    catalog: [],
    catalogMeta: { source: "", offline: false, msg: "", updated_at: "" },
    updates: [],

    configTargetId: "",
    configDraft: {},
    configSchema: {},
    configSaving: false,

    secretTargetId: "",
    secretDraft: {},
    secretMeta: {},
    secretSchema: {},
    secretSaving: false,

    uploadFile: null,
    uploadResult: null,
    uploading: false,

    /** 入口总览（阶段 6.1）：全部插件的入口声明 + 归属分级。 */
    entryRows: [],
    entryQuery: "",

    githubRepo: "",
    githubRef: "",
    githubSubdir: "",
    githubInstalling: false,
    githubResult: null,

    restartHint: false,
    keepDataOnUninstall: false,

    init() {
      if (typeof window === "undefined") return;
      // 设置弹窗切换到「插件管理」导航页时由 settingsModal 派发，避免面板在后台空转。
      this._sectionHandler = (event) => {
        const detail = (event && event.detail) || {};
        if (String(detail.section || "") !== "plugins") return;
        this.activate(detail.anchor);
      };
      window.addEventListener("settings-section-changed", this._sectionHandler);
    },

    destroy() {
      if (typeof window === "undefined" || !this._sectionHandler) return;
      window.removeEventListener("settings-section-changed", this._sectionHandler);
      this._sectionHandler = null;
    },

    activate(anchor = "") {
      this.errorMessage = "";
      const raw = String(anchor || "");

      // 深链：`plugin-config-<id>` / `plugin-secrets-<id>`（阶段 6.2）
      const configMatch = CONFIG_ANCHOR_PATTERN.exec(raw);
      if (configMatch) return this.deepLink(configMatch[1], "config");
      const secretMatch = SECRET_ANCHOR_PATTERN.exec(raw);
      if (secretMatch) return this.deepLink(secretMatch[1], "secrets");

      // 从设置页搜索结果跳进来时，锚点决定先落到哪个插件页签。
      const tab = ANCHOR_TABS[raw];
      return tab ? this.selectTab(tab) : this.reloadActiveTab();
    },

    /**
     * 深链到某个插件的配置 / 密钥区。
     *
     * 必须等 `loadPlugins()` 完成后再展开表单——否则 `item` 还不存在，
     * `openConfig` 会拿到 undefined 而静默失败。
     */
    async deepLink(pluginId, target) {
      const id = String(pluginId || "").trim();
      if (!id) return;
      this.activeTab = "installed";
      await this.loadPlugins();

      const item = this.plugins.find((plugin) => plugin.id === id);
      if (!item) {
        toast(`未找到插件 ${id}`, "error");
        return;
      }

      if (target === "secrets") await this.openSecrets(item);
      else await this.openConfig(item);

      this.scrollToPlugin(id);
    },

    /** 滚动到插件卡片（深链落地时用户需要看到上下文）。 */
    scrollToPlugin(pluginId) {
      if (typeof document === "undefined") return;
      this.$nextTick?.(() => {
        const node = document.querySelector(`[data-plugin-card="${CSS.escape(String(pluginId))}"]`);
        if (node && typeof node.scrollIntoView === "function") {
          node.scrollIntoView({ block: "start", behavior: "smooth" });
        }
      });
    },

    reloadActiveTab() {
      if (this.activeTab === "catalog") return this.loadCatalog();
      if (this.activeTab === "upload") return Promise.resolve();
      if (this.activeTab === "entries") return this.loadEntries();
      return this.loadPlugins();
    },

    selectTab(tab) {
      const next = ["installed", "catalog", "upload", "entries"].includes(tab)
        ? tab
        : "installed";
      this.activeTab = next;
      return this.reloadActiveTab();
    },

    // ---------------------------------------------------------------- 数据

    async loadPlugins() {
      this.loading = true;
      try {
        const data = await getPluginList();
        if (!data.success) {
          this.errorMessage = data.msg || "读取插件列表失败";
          return;
        }
        this.plugins = data.items || [];
        this.pluginsDir = data.plugins_dir || "";
        this.restartHint = this.plugins.some((item) => item.restart_required);
        /*
         * 「已安装」页签上也要有「插件设置入口」区块，而 `settingsEntries`
         * 是从 `entryRows` 派生的。此前只有 `loadEntries()` 会填 `entryRows`，
         * 于是必须先点一次「入口总览」页签，设置在入口才会出现——
         * 用户从设置页搜索「插件设置入口」跳进来时看到的是空区块。
         * `loadPlugins()` 已经拿到 `manifest.entries`，这里顺手同源派生，
         * 不额外打接口。
         */
        this.entryRows = this.buildEntryRows(this.plugins);
      } catch (error) {
        this.errorMessage = `读取插件列表失败: ${error}`;
      } finally {
        this.loading = false;
      }
    },

    async loadCatalog(refresh = false) {
      this.loading = true;
      try {
        const data = await getPluginCatalog(refresh);
        if (!data.success) {
          this.catalogMeta = { source: "", offline: true, msg: data.msg || "", updated_at: "" };
          return;
        }
        this.catalog = data.items || [];
        this.catalogMeta = {
          source: data.source || "",
          offline: Boolean(data.offline),
          msg: data.msg || "",
          updated_at: data.updated_at || "",
        };
      } finally {
        this.loading = false;
      }
    },

    // ---------------------------------------------------------------- 入口总览

    /**
     * 入口总览（阶段 6.1）。
     *
     * 挂在既有「插件管理」页内，**不新增设置顶层 tab**——设置页的
     * `settingsHelpContent` 是硬闸门，新增分区要同时加键，容易静默 no-op。
     * 这里复用 `loadPlugins()` 的结果，不额外打接口。
     */
    async loadEntries() {
      this.loading = true;
      try {
        const data = await getPluginList();
        if (!data.success) {
          this.errorMessage = data.msg || "读取插件列表失败";
          return;
        }
        this.plugins = data.items || [];
        this.pluginsDir = data.plugins_dir || "";
        this.entryRows = this.buildEntryRows(this.plugins);
      } catch (error) {
        this.errorMessage = `读取插件列表失败: ${error}`;
      } finally {
        this.loading = false;
      }
    },

    /** 把各插件的 `manifest.entries` 摊平成总览表格的行。 */
    buildEntryRows(plugins) {
      const rows = [];
      for (const item of plugins || []) {
        const entries = (item.manifest && item.manifest.entries) || [];
        for (const entry of entries) {
          rows.push({
            pluginId: item.id,
            pluginName: item.name || item.id,
            pluginEnabled: item.enabled !== false,
            tier: item.tier || "community",
            id: entry.id,
            key: `${item.id}:${entry.id}`,
            kind: entry.kind,
            label: entry.label,
            description: entry.description || "",
            icon: entry.icon || "",
            shortcut: entry.shortcut || "",
            disabledHint: entry.disabledHint || "",
            // surface 是「去重」与「呈现方式」两列的公共依据：多个入口可以指向
            // 同一个 surface（本插件 4 个入口都指向 workbench）。
            surfaceId: (entry.surface && entry.surface.id) || entry.id,
            surfaceType:
              (entry.surface && entry.surface.type) || "panel",
          });
        }
      }
      rows.sort((left, right) => {
        if (left.pluginId !== right.pluginId) return left.pluginId.localeCompare(right.pluginId);
        return String(left.label).localeCompare(String(right.label));
      });
      return rows;
    },

    get filteredEntryRows() {
      const query = String(this.entryQuery || "").trim().toLowerCase();
      if (!query) return this.entryRows;
      return this.entryRows.filter((row) =>
        `${row.label} ${row.pluginId} ${row.pluginName} ${row.id} ${row.kind}`
          .toLowerCase()
          .includes(query),
      );
    },

    /**
     * 入口图标节点（设计文档 9.3.1「图标 + 名称」列）。
     *
     * 取值可以是宿主图标名，也可以是插件内资源路径（含 `/`）——后者要靠
     * `pluginId` 才能解析成 `/api/plugins/<id>/assets/…`，所以必须传下去。
     * 资源路径会渲染成 `<span>` + CSS mask（见 `uiPrimitives.js:icon`）。
     */
    entryIconNode(row) {
      const name = String((row && row.icon) || "").trim();
      return icon(name || "circle-dot", {
        className: "ui-icon--sm",
        pluginId: String((row && row.pluginId) || ""),
      });
    },

    /** 图标节点的 HTML（模板用 `x-html` 注入）。 */
    entryIconHtml(row) {
      return this.entryIconNode(row).outerHTML;
    },

    tierLabel(item) {
      const tier = typeof item === "string" ? item : item && item.tier;
      return TIER_LABELS[String(tier || "community")] || "社区";
    },

    tierClass(item) {
      const tier = typeof item === "string" ? item : item && item.tier;
      return `is-${String(tier || "community")}`;
    },

    entryKindLabel(row) {
      return ENTRY_KIND_LABELS[String((row && row.kind) || "")] || "入口";
    },

    entryLocationLabel(row) {
      return ENTRY_LOCATION_LABELS[String((row && row.kind) || "")] || "—";
    },

    /** 该 kind 是否已有真实渲染消费者（未实现的不该让用户以为已经生效）。 */
    entryKindImplemented(row) {
      return IMPLEMENTED_ENTRY_KINDS.has(String((row && row.kind) || ""));
    },

    entrySurfaceLabel(row) {
      return SURFACE_LABELS[String((row && row.surfaceType) || "")] || "—";
    },

    // ---------------------------------------------------------------- 快捷键

    /**
     * 该入口能否设置快捷键。
     *
     * `context` 类**不提供**快捷键设置：右键菜单的入口是「对某个右键目标执行」，
     * 键盘上没有「右键目标」这个概念，所有 context 入口又都开同一个右侧面板，
     * 设了快捷键也没有可用的落点（用户原话：「都打开同一个右侧面板，设了也没用」）。
     */
    entryShortcutEditable(row) {
      return String((row && row.kind) || "") !== "context";
    },

    /**
     * 该入口是否持有本插件的**快捷键位**。
     *
     * 去重规则：**按 surface 去重**。同一个 surface 被多个入口复用时（本插件的
     * `workbench` 就服务 dock / context / batch / settings 四个入口），只有第一个
     * 入口保留快捷键位——否则总览页会出现四条指向同一面板的重复快捷键，
     * 用户改绑其中一条会与另一条互相顶掉（`assignEntryShortcut` 里一个组合键
     * 只能绑一个入口）。
     */
    entryHoldsShortcutSlot(row) {
      if (!this.entryShortcutEditable(row)) return false;
      const surfaceKey = `${row.pluginId}:${row.surfaceId || row.id}`;
      const first = this.entryRows.find(
        (item) => `${item.pluginId}:${item.surfaceId || item.id}` === surfaceKey
          && this.entryShortcutEditable(item),
      );
      return !first || first.key === row.key;
    },

    /**
     * 入口当前生效的快捷键。
     *
     * 两级来源（设计文档 2.2：`shortcut` 是「建议快捷键，宿主可覆盖」）：
     * 用户配置（`layout.shortcuts`）优先，否则用插件建议的 `entries[].shortcut`。
     */
    entryShortcut(row) {
      const shortcuts = (EntryRegistry.layout && EntryRegistry.layout.shortcuts) || {};
      const key = String((row && row.key) || "");
      const hit = Object.keys(shortcuts).find((combo) => shortcuts[combo] === key);
      if (hit) return hit;
      // 被用户改绑到别处的建议值不再生效；不持有快捷键位的入口不显示建议值
      if (!this.entryHoldsShortcutSlot(row)) return "";
      return String((row && row.shortcut) || "");
    },

    /** 该入口的快捷键是否为用户显式配置（用于区分「建议」与「已设定」）。 */
    entryShortcutIsCustom(row) {
      const shortcuts = (EntryRegistry.layout && EntryRegistry.layout.shortcuts) || {};
      const key = String((row && row.key) || "");
      return Object.values(shortcuts).includes(key);
    },

    // ---------------------------------------------------------------- settings 入口

    /**
     * `kind: 'settings'` 的渲染消费者（设计文档 D7）。
     *
     * **为什么挂在插件管理页内、不新增设置顶层 tab**：设置页的
     * `selectSettingTab` 有硬闸门——`if (!this.settingsHelpContent[section]) return;`
     * 新增顶层分区必须同时改 `settingsHelpContent` + `COMMAND_PALETTE_ENTRIES` +
     * 模板，成本远大于收益，且会让设置页持续膨胀。`plugins` 键已存在，因此
     * 注入到既有分区内即可规避该闸门。
     *
     * 只取**已启用**插件的 settings 入口：被禁用的插件不该在设置页留按钮。
     */
    get settingsEntries() {
      return this.entryRows.filter(
        (row) => String(row.kind || "") === "settings" && row.pluginEnabled,
      );
    },

    /** 点击 settings 入口：打开该插件声明的 surface。 */
    openSettingsEntry(row) {
      const entry = EntryRegistry.get(String((row && row.key) || ""));
      if (!entry) {
        toast("入口已失效，插件可能已被禁用", "error");
        return false;
      }

      const surfaceKey = `${entry.pluginId}:${
        (entry.surface && entry.surface.id) || entry.id
      }`;

      /*
       * 层级协调：`page` 型 surface 刻意落在模态层之下（它是「替换主内容区」，
       * 不是浮层，见 plugin-surfaces.css），因此从设置弹窗里点开它必须先让出位置，
       * 否则用户只会看到设置页，面板开在背后。
       *
       * 其余类型（`modal` / `panel` / `sheet`）都落在对话框层，能正常盖住设置页，
       * **不需要**关设置页——保留用户所在的设置位置本身就是更好的体验，
       * 关掉还会撞上「未保存修改」的丢弃确认。
       *
       * 类型以 `register()` 的 `spec.type` 为准：那才是决定容器类名与层级的值。
       */
      if (PluginSurfaceHost.typeOf(surfaceKey) === "page") {
        if (typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("settings:request-close", {
              detail: { reason: "plugin-page-surface", surfaceKey },
            }),
          );
        }
      }

      // 与坞的打开路径同一契约：优先走插件注册的 surface，
      // 没有 surface 时派发 `entry:activate` 交给插件自己处理。
      window.dispatchEvent(
        new CustomEvent("entry:open", { detail: { key: entry.key } }),
      );
      return true;
    },

    /** 录制快捷键：按下的组合键写入 `layout.shortcuts`。 */
    async captureEntryShortcut(row) {
      if (this.busyAction) return;
      if (!this.entryShortcutEditable(row)) {
        toast("右键菜单入口不支持快捷键：所有 context 入口打开的是同一个面板", "error");
        return;
      }
      if (!this.entryHoldsShortcutSlot(row)) {
        toast("该入口与同插件的其他入口共用同一个面板，快捷键请设在那一项上", "error");
        return;
      }
      this.recordingKey = String((row && row.key) || "");
      this.$nextTick?.(() => {
        const input = this.$refs?.shortcutInput;
        if (input && typeof input.focus === "function") input.focus();
      });
    },

    /**
     * 处理录制框的按键。
     *
     * 与 `commandPalette.shortcutCombo` 同一套折算规则（修饰键固定顺序 + 主键大写），
     * 这样两处对同一个物理按键会得到同一个字符串。
     */
    async onShortcutKeydown(event) {
      const key = String(event.key || "");
      if (key === "Escape") {
        this.recordingKey = "";
        return;
      }
      if (["Control", "Alt", "Shift", "Meta"].includes(key)) return;
      if (!key) return;

      const parts = [];
      if (event.ctrlKey) parts.push("Ctrl");
      if (event.altKey) parts.push("Alt");
      if (event.shiftKey) parts.push("Shift");
      if (event.metaKey) parts.push("Meta");
      if (!parts.length) {
        toast("快捷键必须包含 Ctrl / Alt / Shift / Meta 修饰键", "error");
        return;
      }
      parts.push(key.length === 1 ? key.toUpperCase() : key);
      const combo = parts.join("+");

      await this.assignEntryShortcut(this.recordingKey, combo);
      this.recordingKey = "";
    },

    /** 写入（或清除）某入口的快捷键。空 `combo` 表示清除。 */
    async assignEntryShortcut(entryKey, combo) {
      const key = String(entryKey || "");
      if (!key) return false;

      const shortcuts = { ...((EntryRegistry.layout && EntryRegistry.layout.shortcuts) || {}) };
      // 一个组合键只能绑一个入口：先摘掉旧绑定，再摘掉该入口的旧组合键
      for (const existing of Object.keys(shortcuts)) {
        if (shortcuts[existing] === key) delete shortcuts[existing];
      }
      const target = String(combo || "").trim();
      if (target) {
        const occupied = shortcuts[target];
        if (occupied && occupied !== key) {
          toast(`快捷键 ${target} 已被其他入口占用`, "error");
          return false;
        }
        shortcuts[target] = key;
      }

      const ok = await EntryRegistry.updateLayout({ shortcuts });
      if (ok) toast(target ? `已绑定 ${target}` : "已清除快捷键");
      else toast("保存快捷键失败", "error");
      return ok;
    },

    /** 清除该入口的快捷键。 */
    async clearEntryShortcut(row) {
      return this.assignEntryShortcut(row && row.key, "");
    },

    /** 该插件将添加多少个入口（安装期披露，阶段 6.3）。 */
    entryCountLabel(item) {
      const entries = (item && item.manifest && item.manifest.entries) || [];
      return `此插件将添加 ${entries.length} 个入口`;
    },

    entryCount(item) {
      const entries = (item && item.manifest && item.manifest.entries) || [];
      return entries.length;
    },

    /** 已安装插件对应的可用更新（没有则 null）。 */
    updateFor(pluginId) {
      const id = String(pluginId || "");
      if (!id) return null;
      return this.updates.find((item) => item.id === id) || null;
    },

    async checkUpdates() {
      this.busyAction = "updates";
      try {
        const data = await checkPluginUpdates(true);
        if (!data.success) {
          toast(data.msg || "检查更新失败", "error");
          return;
        }
        this.updates = data.updates || [];
        const failed = data.errors || [];
        if (failed.length) {
          // 部分条目检查失败（网络 / 没有 Release）时要说清楚，否则「已是最新」会误导
          toast(`发现 ${this.updates.length} 个可用更新；${failed.length} 个检查失败`, "error");
          return;
        }
        toast(this.updates.length ? `发现 ${this.updates.length} 个可用更新` : "已是最新版本");
      } finally {
        this.busyAction = "";
      }
    },

    /**
     * 应用一个可用更新（覆盖安装 + 重启生效）。
     *
     * 与 SillyTavern `POST /api/extensions/update` 同语义：那边是 `git pull`，
     * 这边是重新下载归档并原子替换（插件目录没有 `.git`）。
     * 后端会校验「必须已安装且存在于 catalog」，前端这里只做二次确认。
     */
    async applyUpdate(update) {
      if (this.busyAction) return;
      const id = String((update && update.id) || "");
      if (!id) return;

      const from = (update && update.installed) || "?";
      const to = (update && update.available) || "?";
      if (!window.confirm(`把 ${update.name || id} 从 v${from} 更新到 v${to}？\n\n更新后需要重启应用。`)) {
        return;
      }

      this.busyAction = `update:${id}`;
      try {
        const data = await updatePluginFromCatalog(id);
        if (!data.success) {
          toast(data.msg || "更新失败", "error");
          return;
        }
        toast(data.msg || `已更新到 v${to}，重启应用后生效`);
        this.updates = this.updates.filter((item) => item.id !== id);
        await this.loadPlugins();
      } finally {
        this.busyAction = "";
      }
    },

    // ---------------------------------------------------------------- 四操作

    async installCatalogItem(item) {
      if (this.busyAction) return;

      // 防御：已安装的不走「安装」。UI 已经不渲染该按钮，但函数可能被别处调用，
      // 这里再挡一次，避免用户被引导去覆盖安装（那会静默降级/升级版本）。
      const action = this.catalogAction(item);
      if (action === "update") {
        return this.updateCatalogItem(item);
      }
      if (action === "installed") {
        toast(`${item.name || item.id} 已安装 v${item.installed_version || ""}，无需重复安装`);
        return;
      }

      if (!window.confirm(`确认从 GitHub 安装 ${item.name || item.id}？\n\n来源: ${item.source?.repo || ""}`)) {
        return;
      }

      this.busyAction = `install:${item.id}`;
      try {
        const data = await installPluginFromCatalog(item.id);
        if (!data.success) {
          toast(data.msg || "安装失败", "error");
          return;
        }
        this.restartHint = true;
        toast(data.msg || "安装完成");
        // 同时刷新目录，让卡片立刻切到「已安装」
        await Promise.all([this.loadPlugins(), this.loadCatalog(true)]);
      } finally {
        this.busyAction = "";
      }
    },

    pickUploadFile(event) {
      const file = event?.target?.files?.[0] || null;
      this.uploadFile = file;
      this.uploadResult = null;
    },

    async uploadArchive() {
      if (!this.uploadFile || this.uploading) return;
      this.uploading = true;
      try {
        const data = await uploadPluginArchive(this.uploadFile);
        if (!data.success) {
          this.uploadResult = { success: false, msg: data.msg || "安装失败" };
          toast(data.msg || "安装失败", "error");
          return;
        }
        this.uploadResult = data.result || { success: true };
        this.restartHint = true;
        toast(data.msg || "安装完成");
        await this.loadPlugins();
      } finally {
        this.uploading = false;
      }
    },

    async installFromGithub() {
      const repo = (this.githubRepo || "").trim();
      if (!repo) {
        toast("请输入 GitHub 仓库（owner/repo 或 https://github.com/owner/repo）", "error");
        return;
      }
      if (this.githubInstalling) return;
      this.githubInstalling = true;
      this.githubResult = null;
      try {
        const data = await installPluginFromGithub({
          repo,
          ref: this.githubRef,
          subdir: this.githubSubdir,
        });
        if (!data.success) {
          this.githubResult = { success: false, msg: data.msg || "安装失败" };
          toast(data.msg || "安装失败", "error");
          return;
        }
        this.githubResult = data.result || { success: true };
        this.restartHint = true;
        toast(data.msg || "安装完成");
        await this.loadPlugins();
      } finally {
        this.githubInstalling = false;
      }
    },

    async toggleEnabled(item) {
      if (this.busyAction) return;
      const enable = !item.enabled;
      this.busyAction = `${enable ? "enable" : "disable"}:${item.id}`;
      try {
        const data = enable ? await enablePlugin(item.id) : await disablePlugin(item.id);
        if (!data.success) {
          toast(data.msg || "操作失败", "error");
          return;
        }
        this.restartHint = this.restartHint || Boolean(data.restart_required);
        toast(data.msg || (enable ? "已启用" : "已禁用"));
        if (!enable) {
          // D8 契约：宿主必须在插件被禁用时**强制**回收其运行时资源
          // （surface / 入口条目 / 注入的样式），不依赖插件的 deactivate。
          this.notifyPluginUnloaded(item.id);
        }
        await this.loadPlugins();
      } finally {
        this.busyAction = "";
      }
    },

    /** 通知宿主运行时回收某插件的全部资源。 */
    notifyPluginUnloaded(pluginId) {
      if (!pluginId) return;
      window.dispatchEvent(
        new CustomEvent("plugin:unloaded", { detail: { pluginId: String(pluginId) } }),
      );
    },

    async uninstall(item) {
      if (this.busyAction) return;
      const extra = this.keepDataOnUninstall ? "\n（保留配置与密钥）" : "\n（同时清除配置与密钥）";
      if (!window.confirm(`确认卸载 ${item.name || item.id}？${extra}\n\n插件目录会移入回收站。`)) {
        return;
      }

      this.busyAction = `uninstall:${item.id}`;
      try {
        const data = await uninstallPlugin(item.id, this.keepDataOnUninstall);
        if (!data.success) {
          toast(data.msg || "卸载失败", "error");
          return;
        }
        this.restartHint = true;
        toast(data.msg || "已卸载");
        // 卸载同样要回收运行时资源（条目偏好由后端 `_clear_ui_namespace` 剪除）
        this.notifyPluginUnloaded(item.id);
        await this.loadPlugins();
      } finally {
        this.busyAction = "";
      }
    },

    // ---------------------------------------------------------------- 配置

    async openConfig(item) {
      // 再次点击同一插件的「配置」按钮时收起
      if (this.configTargetId === item.id) {
        this.closeConfig();
        return;
      }
      this.closeSecrets();
      this.configTargetId = item.id;
      const manifest = item.manifest || {};
      this.configSchema = manifest.config_schema || {};
      const data = await getPluginConfig(item.id);
      this.configDraft = data.success ? (data.config || {}) : {};
    },

    closeConfig() {
      this.configTargetId = "";
      this.configDraft = {};
      this.configSchema = {};
    },

    async saveConfig() {
      if (!this.configTargetId || this.configSaving) return;
      this.configSaving = true;
      try {
        const data = await savePluginConfig(this.configTargetId, this.configDraft);
        if (!data.success) {
          toast(data.msg || "保存失败", "error");
          return;
        }
        this.configDraft = data.config || this.configDraft;
        toast("配置已保存");
        // D10：插件 UI 需要立刻读到新值（`when.config.requireKeys` 也要重算）。
        // 不复用 `settings-saved`——那是宿主自身设置的事件，消费方在
        // cardGrid / presetEditor，混用会让插件配置变更误触发宿主重载。
        this.notifyPluginConfigChanged(this.configTargetId, this.configDraft);
      } finally {
        this.configSaving = false;
      }
    },

    /** 派发插件配置变更事件（宿主 → 插件单向通知）。 */
    notifyPluginConfigChanged(pluginId, config) {
      if (!pluginId) return;
      window.dispatchEvent(
        new CustomEvent("plugin-config-changed", {
          detail: { pluginId: String(pluginId), config: config || {} },
        }),
      );
    },

    // ---------------------------------------------------------------- 密钥

    async openSecrets(item) {
      // 再次点击同一插件的「密钥」按钮时收起
      if (this.secretTargetId === item.id) {
        this.closeSecrets();
        return;
      }
      this.closeConfig();
      const manifest = item && item.manifest ? item.manifest : {};
      if (manifest.secret_schema && Object.keys(manifest.secret_schema).length) {
        this.secretSchema = manifest.secret_schema;
        this._secretSchemaPluginId = item.id;
      } else if (this._secretSchemaPluginId !== item.id) {
        this.secretSchema = {};
      }
      this.secretTargetId = item.id;

      const data = await getPluginSecrets(item.id);
      this.secretMeta = data.success ? (data.secrets || {}) : {};

      const properties = (this.secretSchema && this.secretSchema.properties) || {};
      const draft = {};
      Object.keys(this.secretMeta).forEach((key) => {
        const meta = this.secretMeta[key] || {};
        const spec = properties[key] || {};
        if (!spec.secret && typeof meta.value === "string") {
          draft[key] = meta.value;
        }
      });
      this.secretDraft = draft;
    },

    closeSecrets() {
      this.secretTargetId = "";
      this.secretDraft = {};
      this.secretMeta = {};
      this.secretSchema = {};
    },

    async saveSecrets() {
      if (!this.secretTargetId || this.secretSaving) return;
      const payload = {};
      Object.keys(this.secretDraft).forEach((key) => {
        const value = this.secretDraft[key];
        if (value === "" || value === null || value === undefined) return;
        payload[key] = value;
      });

      if (!Object.keys(payload).length) {
        toast("没有需要写入的密钥");
        return;
      }

      this.secretSaving = true;
      try {
        const data = await savePluginSecrets(this.secretTargetId, payload);
        if (!data.success) {
          toast(data.msg || "保存失败", "error");
          return;
        }
        this.secretDraft = {};
        await this.openSecrets({ id: this.secretTargetId, manifest: { secret_schema: this.secretSchema } });
        toast("密钥已保存");
        // D10：密钥变更同样要通知（`when.config.requireKeys` 可能引用密钥键）
        window.dispatchEvent(
          new CustomEvent("plugin-secrets-changed", {
            detail: { pluginId: String(this.secretTargetId), config: { ...payload } },
          }),
        );
      } finally {
        this.secretSaving = false;
      }
    },

    async clearSecret(key) {
      if (!this.secretTargetId) return;
      if (!window.confirm(`确认清除密钥项 ${key}？`)) return;

      const data = await deletePluginSecret(this.secretTargetId, key);
      if (!data.success) {
        toast(data.msg || "清除失败", "error");
        return;
      }
      toast("已清除");
      await this.openSecrets({ id: this.secretTargetId, manifest: { secret_schema: this.secretSchema } });
      // 清除同样要通知：`when.config.requireKeys` 引用了该密钥时，入口必须重新置灰
      window.dispatchEvent(
        new CustomEvent("plugin-secrets-changed", {
          detail: { pluginId: String(this.secretTargetId), config: {}, removed: [String(key)] },
        }),
      );
    },

    async openDocs(item) {
      const data = await getPluginReadme(item.id);
      if (!data.success) {
        toast(data.msg || "读取插件文档失败", "error");
        return;
      }

      const blocks = [];
      if (data.readme && data.readme.found && data.readme.content) {
        blocks.push(data.readme.content.trim());
      }
      if (data.changelog && data.changelog.found && data.changelog.content) {
        blocks.push(`## 更新日志\n\n${data.changelog.content.trim()}`);
      }

      if (!blocks.length) {
        toast("该插件没有 README 或 CHANGELOG");
        return;
      }

      window.dispatchEvent(
        new CustomEvent("open-markdown-view", {
          detail: {
            content: blocks.join("\n\n---\n\n"),
            title: `${item.name || item.id} · 文档`,
            // 插件文档不存在「去详情页编辑」这条路径：内容直接来自插件目录里的
            // README.md / CHANGELOG.md，要改只能改插件本身。这里如实说明来源，
            // 不要继承本地备注弹窗的默认提示。
            footerHint: `只读模式 · 内容来自插件目录中的 README.md / CHANGELOG.md`,
          },
        }),
      );
    },

    // ---------------------------------------------------------------- 渲染辅助

    schemaEntries(schema) {
      const properties = (schema && schema.properties) || {};
      return Object.keys(properties).map((key) => ({
        key,
        spec: properties[key] || {},
      }));
    },

    isRequired(schema, key) {
      return Array.isArray(schema?.required) && schema.required.includes(key);
    },

    statusIcon(item) {
      if (item.load_error) return "⚠";
      return item.enabled ? "●" : "○";
    },

    statusLabel(item) {
      if (item.load_error) return "加载失败";
      return item.enabled ? "已启用" : "已禁用";
    },

    permissionLabels(item) {
      const permissions = item.permissions || [];
      if (!permissions.length) return "无声明权限";
      return permissions.map((item) => PERMISSION_LABELS[item] || item).join(" · ");
    },

    requirementLabels(item) {
      const requires = (item.manifest && item.manifest.requires) || item.requires || {};
      const entries = Object.keys(requires).map((dep) => `${dep} ${requires[dep]}`);
      return entries.join(" · ");
    },

    styleScopeWarnings(item) {
      const errors = item.style_scope_errors || {};
      return Object.keys(errors);
    },

    installStateLabel(item) {
      if (item.installed) return `已安装 v${item.installed_version || ""}`;
      return "未安装";
    },

    /**
     * 目录条目该给什么操作：`install` / `update` / `installed`。
     *
     * 后端 `/api/plugins/catalog` 已经算好 `installed` 与 `installed_version`
     * （见 `routes.py` 的 `installed = {state.plugin_id: state.header ...}`），
     * 前端此前完全没用这两个字段——目录页对已安装插件照样显示「安装」，
     * 于是可以反复覆盖安装同一个插件。这里补上消费。
     *
     * 三态而非两态：已安装但目录版本更新时要给「更新」，否则用户只能先去
     * 「已安装」页签点检查更新，路径太长。
     */
    catalogAction(entry) {
      if (!entry || !entry.installed) return "install";

      const installed = String(entry.installed_version || "").trim();
      const available = String(entry.version || "").trim();

      // 版本缺失时不猜——当作「已安装」，宁可少给一个按钮也不误导
      if (!installed || !available) return "installed";

      return compareVersions(available, installed) > 0 ? "update" : "installed";
    },

    /** 目录页的「更新」：与「已安装」页签的 applyUpdate 同一端点与语义。 */
    async updateCatalogItem(entry) {
      if (this.busyAction) return;
      const id = String((entry && entry.id) || "");
      if (!id) return;

      const from = (entry && entry.installed_version) || "?";
      const to = (entry && entry.version) || "?";
      if (!window.confirm(`把 ${entry.name || id} 从 v${from} 更新到 v${to}？\n\n更新后需要重启应用。`)) {
        return;
      }

      this.busyAction = `update:${id}`;
      try {
        const data = await updatePluginFromCatalog(id);
        if (!data.success) {
          toast(data.msg || "更新失败", "error");
          return;
        }
        toast(data.msg || `已更新到 v${to}，重启应用后生效`);
        // 刷新目录与已安装列表，让卡片切到「已安装」
        await Promise.all([this.loadCatalog(true), this.loadPlugins()]);
      } finally {
        this.busyAction = "";
      }
    },

    restartNotice() {
      return "插件已变更，请手动关闭并重新启动 ST-Manager 后生效。";
    },
  };
}
