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
} from "../api/plugins.js";

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
};

/** 入口出现位置的说明（总览页「出现位置」列）。 */
const ENTRY_LOCATION_LABELS = {
  dock: "入口坞",
  nav: "侧栏导航",
  settings: "设置页",
  context: "右键菜单",
  command: "命令面板",
  status: "状态栏",
};

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

    entrySurfaceLabel(row) {
      return SURFACE_LABELS[String((row && row.surfaceType) || "")] || "—";
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

    async checkUpdates() {
      this.busyAction = "updates";
      try {
        const data = await checkPluginUpdates(true);
        if (!data.success) {
          toast(data.msg || "检查更新失败", "error");
          return;
        }
        this.updates = data.updates || [];
        toast(this.updates.length ? `发现 ${this.updates.length} 个可用更新` : "已是最新版本");
      } finally {
        this.busyAction = "";
      }
    },

    // ---------------------------------------------------------------- 四操作

    async installCatalogItem(item) {
      if (this.busyAction) return;
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
        await this.loadPlugins();
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

    restartNotice() {
      return "插件已变更，请手动关闭并重新启动 ST-Manager 后生效。";
    },
  };
}
