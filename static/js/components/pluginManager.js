/**
 * static/js/components/pluginManager.js
 * 插件管理模态框（设计文档第 9 部分）。
 *
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
  getPluginSecrets,
  installPluginFromCatalog,
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
    showPluginManager: false,
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

    restartHint: false,
    keepDataOnUninstall: false,

    init() {
      this._openHandler = () => this.open();
      window.addEventListener("open-plugin-manager", this._openHandler);
    },

    destroy() {
      window.removeEventListener("open-plugin-manager", this._openHandler);
    },

    async open() {
      this.showPluginManager = true;
      this.errorMessage = "";
      await this.loadPlugins();
    },

    close() {
      this.showPluginManager = false;
      this.closeConfig();
      this.closeSecrets();
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

    async checkUpdates() {
      if (this.busyAction) return;
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
        await this.loadPlugins();
      } finally {
        this.busyAction = "";
      }
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
        await this.loadPlugins();
      } finally {
        this.busyAction = "";
      }
    },

    // ---------------------------------------------------------------- 配置

    async openConfig(item) {
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
      } finally {
        this.configSaving = false;
      }
    },

    // ---------------------------------------------------------------- 密钥

    async openSecrets(item) {
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
