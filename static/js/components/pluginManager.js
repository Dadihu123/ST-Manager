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
import { compareVersions } from "../contributionRegistry.js";

/**
 * 能力位（capability）中文标签（设计 §4.7，v3 用 `capabilities` 取代 `permissions`）。
 *
 * 能力位是**披露性**的（ADR-0008）：宿主不据此拦截调用，只用于让用户知道
 * 「这个插件会碰什么」。未知能力位显示为「未知名」，而不是静默丢弃——
 * 未来新增能力位时，旧版管理页也能如实展示。
 */
const CAPABILITY_LABELS = {
  "cards.read": "读取角色卡",
  "cards.write": "修改角色卡",
  "worldbook.read": "读取世界书",
  "worldbook.write": "修改世界书",
  "tags.read": "读取标签",
  "tags.write": "写入标签",
  "chats.read": "读取聊天",
  "chats.write": "修改聊天",
  "presets.read": "读取预设",
  "presets.write": "修改预设",
  "secrets.read": "读取密钥",
  "network.outbound": "访问网络",
  "jobs.run": "运行后台作业",
  "hooks.subscribe": "订阅后端事件",
  "cli.run": "执行命令行",
  "ui.custom": "自绘 UI",
  "ui.global_styles": "修改全局样式",
};

/** 菜单落点中文标签（设计 §4.4.1 的 7 个落点）。 */
const MENU_PLACEMENT_LABELS = {
  "context.folder": "文件夹右键",
  "context.card": "角色卡右键",
  "context.footer": "右键菜单尾部",
  "batch.actions": "批量操作",
  "commandPalette": "命令面板",
  dock: "入口坞",
  "settings.nav": "设置侧栏",
};

/** 插槽中文标签（设计 §4.4.2）。 */
const SLOT_LABELS = {
  "settings.section": "设置分区",
  "header.actions": "顶栏动作",
  "card.detail.tabs": "详情页签",
  "page.cards.toolbar": "角色卡工具栏",
  "page.worldinfo.toolbar": "世界书工具栏",
};

/** 空状态插槽（`empty.<mode>`）的 mode 中文标签。 */
const EMPTY_SLOT_MODE_LABELS = {
  cards: "角色卡",
  worldinfo: "世界书",
  chats: "聊天",
  presets: "预设",
  regex: "正则",
  scripts: "脚本",
  quick_replies: "快速回复",
  beautify: "美化",
};

/** 呈现方式（`render_mode`，manifest 顶层扁平快照；设计 §4.5）。 */
const RENDER_MODE_LABELS = {
  declarative: "声明式",
  custom: "自绘",
};

// 设置页搜索结果的锚点 → 面板页签：让「搜索设置」能直接落到对应插件页签。
// 另支持 `plugin-config-<id>` / `plugin-secrets-<id>` 语义（阶段 6.2 深链）：
// 切到「已安装」页签 + 自动展开对应表单 + 滚动到位。
const ANCHOR_TABS = {
  "plugin-panel-installed": "installed",
  "plugin-panel-catalog": "catalog",
  "plugin-panel-upload": "upload",
  "plugin-panel-contributions": "contributions",
};

const CONFIG_ANCHOR_PATTERN = /^plugin-config-(.+)$/;
const SECRET_ANCHOR_PATTERN = /^plugin-secrets-(.+)$/;

/** 归属分级徽标文案（D5）。 */
const TIER_LABELS = {
  official: "官方",
  verified: "认证",
  community: "社区",
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

    /** 贡献总览（只读）：菜单 / 插槽 / 命令 + 归属分级。 */
    contributionRows: [],
    contributionQuery: "",

    /** 前端激活失败的插件 id（来自运行时 `plugins:loaded` 事件）。 */
    failedPluginIds: [],

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

      // 运行时广播加载结果：`failed` 是 id 数组，用于在已安装列表里标出
      // 「前端激活失败」并给「重试」。重试走 `plugin:reload`（运行时等价 reloadPlugin）。
      this._loadedHandler = (event) => {
        const detail = (event && event.detail) || {};
        this.failedPluginIds = Array.isArray(detail.failed) ? detail.failed.map(String) : [];
      };
      window.addEventListener("plugins:loaded", this._loadedHandler);
    },

    destroy() {
      if (typeof window === "undefined") return;
      if (this._sectionHandler) {
        window.removeEventListener("settings-section-changed", this._sectionHandler);
        this._sectionHandler = null;
      }
      if (this._loadedHandler) {
        window.removeEventListener("plugins:loaded", this._loadedHandler);
        this._loadedHandler = null;
      }
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
      if (this.activeTab === "contributions") return this.loadContributions();
      return this.loadPlugins();
    },

    selectTab(tab) {
      const next = ["installed", "catalog", "upload", "contributions"].includes(tab)
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
        // 「已安装」页签也要能显示贡献数量（只读总览的数据同源派生）。
        this.contributionRows = this.buildContributionRows(this.plugins);
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

    // ---------------------------------------------------------------- 贡献总览

    /**
     * 贡献总览（v3 只读视图）。
     *
     * 挂在既有「插件管理」页内，**不新增设置顶层 tab**——设置页的
     * `settingsHelpContent` 是硬闸门，新增分区要同时加键，容易静默 no-op。
     * 这里复用 `loadPlugins()` 的结果，不额外打接口；数据源是 manifest 里
     * 静态声明的 `contributions`（不含运行时 `api.contributions.update`
     * 动态浮现的内容——那是插件自身状态，宿主只读展示声明结构）。
     */
    async loadContributions() {
      this.loading = true;
      try {
        const data = await getPluginList();
        if (!data.success) {
          this.errorMessage = data.msg || "读取插件列表失败";
          return;
        }
        this.plugins = data.items || [];
        this.pluginsDir = data.plugins_dir || "";
        this.contributionRows = this.buildContributionRows(this.plugins);
      } catch (error) {
        this.errorMessage = `读取插件列表失败: ${error}`;
      } finally {
        this.loading = false;
      }
    },

    /**
     * 插件 manifest 的 `contributions`（v3 结构，缺省空对象）。
     *
     * `/api/plugins/list` 返回的是 S2 定稿的**扁平快照**：`frontend` 是布尔、
     * `render_mode` / `contributions` / `frontend_global_styles` 都在 manifest
     * 顶层，**不是** v2 的 nested `frontend` 对象。
     */
    contributionsOf(item) {
      const manifest = (item && item.manifest) || {};
      const contributions = manifest.contributions;
      return contributions && typeof contributions === "object" ? contributions : {};
    },

    /** 把各插件声明的贡献摊平成总览表格的行（菜单树递归展开，插槽/命令各一行）。 */
    buildContributionRows(plugins) {
      const rows = [];

      const walkMenus = (plugin, nodes, depth) => {
        for (const node of Array.isArray(nodes) ? nodes : []) {
          if (!node || typeof node !== "object") continue;
          const placement = String(node.placement || "");
          rows.push({
            pluginId: plugin.id,
            pluginName: plugin.name || plugin.id,
            pluginEnabled: plugin.enabled !== false,
            tier: plugin.tier || "community",
            kind: "menu",
            id: String(node.id || ""),
            label: String(node.label || node.id || ""),
            description: String(node.description || ""),
            icon: String(node.icon || ""),
            location: MENU_PLACEMENT_LABELS[placement] || placement || "—",
            placement,
            depth,
            when: node.when || {},
          });
          walkMenus(plugin, node.children, depth + 1);
        }
      };

      for (const item of plugins || []) {
        const contributions = this.contributionsOf(item);
        walkMenus(item, contributions.menus, 0);

        for (const slot of Array.isArray(contributions.slots) ? contributions.slots : []) {
          if (!slot || typeof slot !== "object") continue;
          const name = String(slot.slot || "");
          let location = SLOT_LABELS[name] || name || "—";
          if (name.startsWith("empty.")) {
            const mode = name.slice("empty.".length);
            location = `空状态 · ${EMPTY_SLOT_MODE_LABELS[mode] || mode}`;
          }
          rows.push({
            pluginId: item.id,
            pluginName: item.name || item.id,
            pluginEnabled: item.enabled !== false,
            tier: item.tier || "community",
            kind: "slot",
            id: String(slot.id || ""),
            label: String(slot.title || slot.id || ""),
            description: String(slot.description || ""),
            icon: String(slot.icon || ""),
            location,
            placement: name,
            depth: 0,
            module: String(slot.module || ""),
            exportName: String(slot.export || ""),
            when: slot.when || {},
          });
        }

        for (const command of Array.isArray(contributions.commands) ? contributions.commands : []) {
          if (!command || typeof command !== "object") continue;
          rows.push({
            pluginId: item.id,
            pluginName: item.name || item.id,
            pluginEnabled: item.enabled !== false,
            tier: item.tier || "community",
            kind: "command",
            id: String(command.id || ""),
            label: String(command.title || command.id || ""),
            description: String(command.description || ""),
            icon: String(command.icon || ""),
            location: "命令面板 / 快捷键",
            placement: "command",
            depth: 0,
            shortcut: String(command.shortcut || ""),
            module: String(command.module || ""),
            exportName: String(command.export || ""),
            when: command.when || {},
          });
        }
      }

      const kindOrder = { menu: 0, slot: 1, command: 2 };
      rows.sort((left, right) => {
        if (left.pluginId !== right.pluginId) return left.pluginId.localeCompare(right.pluginId);
        const kindDiff = (kindOrder[left.kind] || 0) - (kindOrder[right.kind] || 0);
        if (kindDiff !== 0) return kindDiff;
        return String(left.label).localeCompare(String(right.label));
      });
      return rows;
    },

    get filteredContributionRows() {
      const query = String(this.contributionQuery || "").trim().toLowerCase();
      if (!query) return this.contributionRows;
      return this.contributionRows.filter((row) =>
        `${row.label} ${row.pluginId} ${row.pluginName} ${row.id} ${row.kind} ${row.location}`
          .toLowerCase()
          .includes(query),
      );
    },

    /**
     * 贡献图标节点（总览页「图标 + 名称」列）。
     *
     * 取值可以是宿主图标名，也可以是插件内资源路径（含 `/`）——后者要靠
     * `pluginId` 才能解析成 `/api/plugins/<id>/assets/…`，所以必须传下去。
     */
    contributionIconNode(row) {
      const name = String((row && row.icon) || "").trim();
      return icon(name || "circle-dot", {
        className: "ui-icon--sm",
        pluginId: String((row && row.pluginId) || ""),
      });
    },

    /** 图标节点的 HTML（模板用 `x-html` 注入）。 */
    contributionIconHtml(row) {
      return this.contributionIconNode(row).outerHTML;
    },

    tierLabel(item) {
      const tier = typeof item === "string" ? item : item && item.tier;
      return TIER_LABELS[String(tier || "community")] || "社区";
    },

    tierClass(item) {
      const tier = typeof item === "string" ? item : item && item.tier;
      return `is-${String(tier || "community")}`;
    },

    /** 贡献 kind 的中文标签。 */
    contributionKindLabel(row) {
      const kind = String((row && row.kind) || "");
      if (kind === "menu") return "菜单";
      if (kind === "slot") return "插槽";
      if (kind === "command") return "命令";
      return "贡献";
    },

    /** 贡献出现位置（落点 / 插槽名 / 命令面板）。 */
    contributionLocationLabel(row) {
      return String((row && row.location) || "—");
    },

    /** 菜单树缩进（只对菜单节点生效，插槽/命令不缩进）。 */
    contributionIndent(row) {
      const depth = Number((row && row.depth) || 0);
      return row && row.kind === "menu" && depth > 0 ? `${depth * 14}px` : "0px";
    },

    // ---------------------------------------------------------------- 能力 / 呈现方式

    /**
     * 插件声明的能力位数组（v3 `manifest.capabilities`，缺省空数组）。
     *
     * 能力位是**披露性**的（ADR-0008）：宿主不会据此拦截调用，但必须如实展示，
     * 让用户知道插件会碰哪些数据。未知值显示「未知名」，不静默丢弃。
     */
    capabilitiesOf(item) {
      const direct = item && item.capabilities;
      if (Array.isArray(direct)) return direct.map(String);
      const manifest = (item && item.manifest) || {};
      return Array.isArray(manifest.capabilities) ? manifest.capabilities.map(String) : [];
    },

    /** 能力位文案：已知能力位用中文名，未知值显示「未知名」。 */
    capabilityLabel(capability) {
      const key = String(capability || "");
      return CAPABILITY_LABELS[key] || "未知名";
    },

    /** 能力位列表文案（卡片与配置区共用）。 */
    capabilityLabels(item) {
      const capabilities = this.capabilitiesOf(item);
      if (!capabilities.length) return "无能力位声明";
      return capabilities.map((capability) => this.capabilityLabel(capability)).join(" · ");
    },

    /** 能力位个数（安装在安装/卸载提示里披露影响面）。 */
    capabilityCount(item) {
      return this.capabilitiesOf(item).length;
    },

    /** 该能力位是否为已知值（未知能力位在卡片上加「未知名」标记）。 */
    capabilityIsKnown(capability) {
      return Boolean(CAPABILITY_LABELS[String(capability || "")]);
    },

    /** `render_mode`（manifest 顶层的 S2 扁平快照，缺省 `declarative`）。 */
    renderMode(item) {
      const direct = item && item.render_mode;
      if (direct) return String(direct);
      const manifest = (item && item.manifest) || {};
      return String(manifest.render_mode || "declarative");
    },

    renderModeLabel(item) {
      return RENDER_MODE_LABELS[this.renderMode(item)] || this.renderMode(item);
    },

    renderModeClass(item) {
      return `is-${this.renderMode(item)}`;
    },

    /**
     * 自绘模式的提示：声明 `render_mode: custom` 必须同时声明 `ui.custom`
     * 能力位（设计 §4.7 / §7.4）。没声明时给出可见警告，但不阻止使用——
     * 能力位是披露性的，宿主不做硬拦截。
     */
    renderModeWarning(item) {
      if (this.renderMode(item) !== "custom") return "";
      if (this.capabilitiesOf(item).includes("ui.custom")) return "";
      return "未声明自绘";
    },

    /**
     * `frontend_global_styles`（manifest 顶层的 S2 扁平快照；未声明返回空）。
     *
     * 是否真的注入仍由运行时按 `ui.global_styles` 能力位二次门控。
     */
    globalStylesOf(item) {
      const direct = item && item.frontend_global_styles;
      if (Array.isArray(direct)) return direct;
      const manifest = (item && item.manifest) || {};
      return Array.isArray(manifest.frontend_global_styles) ? manifest.frontend_global_styles : [];
    },

    /**
     * 全局样式提示：会修改全局样式的插件必须显式声明，让用户知道风险。
     *
     * 是否真的注入了样式由运行时按 `ui.global_styles` 能力位二次门控；
     * 这里只负责在管理面板上把风险说清楚。
     */
    globalStylesWarning(item) {
      if (!this.globalStylesOf(item).length) return "";
      return "此插件会修改全局样式";
    },

    /** 该插件前端激活失败（运行时 `plugins:loaded` 广播的 failed 名单）。 */
    isPluginFailed(item) {
      const id = String((item && item.id) || "");
      if (!id) return false;
      return (this.failedPluginIds || []).includes(id);
    },

    /** 前端激活失败的原因（运行时只广播 id；后端扫描的加载错误可能有详情）。 */
    pluginFailReason(item) {
      return String((item && item.load_error) || "插件前端激活失败，功能未生效");
    },

    /**
     * 重试前端激活：派发 `plugin:reload`，运行时重新拉取 manifest 并 activate。
     *
     * 不直接 import 运行时模块：渲染层只通过事件与运行时通信（S4 同一原则），
     * 这样管理面板在运行时懒加载失败时也能正常渲染。
     */
    retryPluginActivation(item) {
      const pluginId = String((item && item.id) || "");
      if (!pluginId) return false;
      window.dispatchEvent(new CustomEvent("plugin:reload", { detail: { pluginId } }));
      toast(`正在重新激活 ${item.name || pluginId}…`);
      return true;
    },

    /** 该插件声明了多少条贡献（菜单 / 插槽 / 命令），安装期披露用。 */
    contributionCounts(item) {
      const contributions = this.contributionsOf(item);
      return {
        menus: Array.isArray(contributions.menus) ? contributions.menus.length : 0,
        slots: Array.isArray(contributions.slots) ? contributions.slots.length : 0,
        commands: Array.isArray(contributions.commands) ? contributions.commands.length : 0,
      };
    },

    /** 「此插件将添加 N 个入口」文案（安装/上传确认页披露）。 */
    entryCountLabel(item) {
      const counts = this.contributionCounts(item);
      const total = counts.menus + counts.slots + counts.commands;
      return `此插件将添加 ${total} 条贡献（菜单 ${counts.menus} · 插槽 ${counts.slots} · 命令 ${counts.commands}）`;
    },

    /** 贡献总条数。 */
    entryCount(item) {
      const counts = this.contributionCounts(item);
      return counts.menus + counts.slots + counts.commands;
    },

    // ---------------------------------------------------------------- kill switch

    /**
     * 关闭所有插件浮层（kill switch，设计 §4.10）。
     *
     * 与命令面板的「插件：关闭所有浮动界面」同一条通道：派发
     * `plugins:close-overlays`，由 `PluginHost.killSwitch()` 强制清理全部
     * overlay / surface / 自绘根节点。渲染层不直接碰运行时。
     */
    closeAllPluginOverlays() {
      window.dispatchEvent(new CustomEvent("plugins:close-overlays"));
      toast("已关闭所有插件浮层");
      return true;
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

    /** 能力位文案（卡片与配置区共用；未知能力位显示「未知名」）。 */
    capabilitySummary(item) {
      return this.capabilityLabels(item);
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
