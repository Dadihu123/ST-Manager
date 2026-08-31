/**
 * static/js/components/settingsModal.js
 * 系统设置组件
 */

import { uploadBackground } from "../api/resource.js";
import {
  evaluateSettingsPathSafety,
  openTrash,
  emptyTrash,
  performSystemAction,
  triggerScan,
  exportUserDbBackup,
  importUserDbBackup,
} from "../api/system.js";
import { updateCssVariable, applyFont as applyFontDom } from "../utils/dom.js";
import sharedWallpaperPicker from "./sharedWallpaperPicker.js";

if (typeof window !== "undefined") {
  window.sharedWallpaperPicker = sharedWallpaperPicker;
}

const DEFAULT_SETTINGS = {
  cards_dir: "data/library/characters",
  world_info_dir: "data/library/lorebooks",
  chats_dir: "data/library/chats",
  presets_dir: "data/library/presets",
  st_openai_preset_dir: "",
  regex_dir: "data/library/extensions/regex",
  scripts_dir: "data/library/extensions/tavern_helper",
  quick_replies_dir: "data/library/extensions/quick-replies",
  beautify_dir: "data/library/beautify",
  resources_dir: "data/assets/card_assets",
  default_sort: "date_desc",
  show_header_sort: true,
  theme_accent: "blue",
  host: "127.0.0.1",
  port: 5000,
  st_url: "http://127.0.0.1:8000",
  st_data_dir: "",
  st_auth_type: "basic",
  st_username: "",
  st_password: "",
  st_basic_username: "",
  st_basic_password: "",
  st_web_username: "",
  st_web_password: "",
  st_proxy: "",
  items_per_page: 0,
  items_per_page_wi: 0,
  dark_mode: true,
  font_style: "sans",
  card_width: 220,
  card_effects_enabled: true,
  manager_wallpaper_id: "",
  bg_url: "/assets/backgrounds/default_background.jpeg",
  bg_opacity: 0.45,
  bg_blur: 2,
  auto_save_enabled: false,
  auto_save_interval: 3,
  snapshot_limit_manual: 50,
  snapshot_limit_auto: 5,
  enable_auto_scan: true,
  png_deterministic_sort: false,
  cards_list_use_index: false,
  fast_search_use_index: false,
  worldinfo_list_use_index: false,
  index_auto_bootstrap: true,
  allowed_abs_resource_roots: [],
  wi_preview_limit: 300,
  wi_preview_entry_max_chars: 2000,
  wi_entry_history_limit: 7,
  auth_username: "",
  auth_password: "",
  auth_trusted_ips: [],
  auth_domain_cache_seconds: 60,
  auth_trusted_proxies: [],
  auth_max_attempts: 5,
  auth_fail_window_seconds: 600,
  auth_lockout_seconds: 900,
  auth_hard_lock_threshold: 50,
  auto_rename_on_import: true,
  discord_auth_type: "token",
  discord_bot_token: "",
  discord_user_cookie: "",
  shimmerday_forum_cookie: "",
  sync_source_title_on_update: true,
  automation_slash_is_tag_separator: false,
  silent_snapshot: false,
};

const SETTINGS_SEARCH_ITEMS = [
  { id: "general-manager", section: "general", anchor: "settings-general-manager", title: "管理目录", keywords: "角色卡 世界书 聊天 资源 预设 路径", icon: "folder-root" },
  { id: "general-st", section: "general", anchor: "settings-general-st", title: "SillyTavern 兼容目录", keywords: "st openai preset 预设", icon: "folder-sync" },
  { id: "general-safety", section: "general", anchor: "settings-general-safety", title: "路径安全检查", keywords: "风险 重叠 白名单 安全", icon: "shield-check" },
  { id: "appearance-theme", section: "appearance", anchor: "settings-appearance-theme", title: "主题与视觉", keywords: "深色 浅色 主题 强调色 字体 卡片特效", icon: "palette" },
  { id: "appearance-layout", section: "appearance", anchor: "settings-appearance-layout", title: "布局与列表", keywords: "卡片 分页 排序 收藏", icon: "layout" },
  { id: "appearance-isolated", section: "appearance", anchor: "settings-appearance-isolated", title: "隔离分类", keywords: "隔离 隐藏 分类", icon: "folder-search" },
  { id: "appearance-wallpaper", section: "appearance", anchor: "settings-appearance-wallpaper", title: "个性化壁纸", keywords: "壁纸 背景 上传 美化", icon: "wallpaper" },
  { id: "connection-st", section: "connection", anchor: "settings-connection-st", title: "SillyTavern 连接与同步", keywords: "st 连接 同步 探测 验证", icon: "plug" },
  { id: "connection-api", section: "connection", anchor: "settings-connection-api", title: "API 与服务地址", keywords: "api 代理 主机 端口", icon: "plug" },
  { id: "connection-auth", section: "connection", anchor: "settings-connection-auth", title: "ST 认证", keywords: "basic web 用户名 密码", icon: "key" },
  { id: "connection-manager-auth", section: "connection", anchor: "settings-connection-manager-auth", title: "访问认证与失败限制", keywords: "认证 登录 密码 ip 代理 锁定", icon: "shield-key" },
  { id: "connection-external", section: "connection", anchor: "settings-connection-external", title: "外部服务", keywords: "discord cookie token 类脑", icon: "external-link" },
  { id: "maintenance-actions", section: "maintenance", anchor: "settings-maintenance-actions", title: "维护操作", keywords: "扫描 备份 回收站 用户 db 导入 导出", icon: "settings-maintenance" },
  { id: "maintenance-performance", section: "maintenance", anchor: "settings-maintenance-performance", title: "扫描与性能", keywords: "自动扫描 索引 性能", icon: "sliders-settings" },
  { id: "maintenance-import", section: "maintenance", anchor: "settings-maintenance-import", title: "导入行为", keywords: "标签 分隔符 重命名 png", icon: "file-import" },
  { id: "maintenance-worldinfo", section: "maintenance", anchor: "settings-maintenance-worldinfo", title: "世界书预览与历史", keywords: "世界书 条目 字符 历史", icon: "book-sync" },
  { id: "maintenance-snapshots", section: "maintenance", anchor: "settings-maintenance-snapshots", title: "快照与自动保存", keywords: "快照 自动保存 保留", icon: "snapshot" },
];

export default function settingsModal() {
  const EMPTY_PATH_SAFETY = {
    risk_level: "safe",
    risk_summary: "",
    blocked_actions: [],
    conflicts: [],
  };

  return {
    // === 本地状态 ===
    activeSettingTab: "general",
    allowedAbsRootsText: "",
    authTrustedProxiesText: "",
    settingsQuery: "",
    settingsSnapshot: null,
    settingsSnapshotDarkMode: null,
    settingsSessionOpen: false,
    lastFocusedElement: null,
    saving: false,
    saveState: "idle",
    saveMessage: "",
    showDiscardConfirm: false,
    showAuthPassword: false,
    showStBasicPassword: false,
    showStWebPassword: false,
    pathSafetyState: "idle",
    pathSafetyMessage: "",
    operationLoadingAction: "",
    operationState: "",
    operationMessage: "",
    backgroundUploadState: "idle",
    backgroundUploadMessage: "",

    // Discord 认证显示状态
    showDiscordToken: false,
    showDiscordCookie: false,
    showShimmerdayCookie: false,

    // 帮助模态框状态
    showSettingsHelpModal: false,
    pathSafety: { ...EMPTY_PATH_SAFETY },
    pathSafetyDebounceTimer: null,
    pathSafetyEvaluationVersion: 0,

    // 帮助内容配置
    settingsHelpContent: {
      general: {
        title: "常规路径设置帮助",
        label: "常规路径",
        kicker: "PATHS & STORAGE",
        description: "管理 ST-Manager 与 SillyTavern 资源的存储位置。",
      },
      appearance: {
        title: "外观显示设置帮助",
        label: "外观显示",
        kicker: "APPEARANCE & LAYOUT",
        description: "调整主题、字体、卡片密度与背景体验。",
      },
      connection: {
        title: "连接与服务设置帮助",
        label: "连接与服务",
        kicker: "CONNECTIONS & SERVICES",
        description: "配置 SillyTavern、类脑搜索与 ST-Manager 服务连接。",
      },
      maintenance: {
        title: "维护与高级设置帮助",
        label: "维护与高级",
        kicker: "MAINTENANCE & ADVANCED",
        description: "执行扫描、备份、同步与高级数据保留策略。",
      },
    },

    get settingsForm() {
      return this.$store.global.settingsForm;
    },
    get isDarkMode() {
      return Boolean(this.$store?.global?.isDarkMode);
    },
    get settingsSearchItems() {
      return SETTINGS_SEARCH_ITEMS;
    },
    get currentSettingHelp() {
      return this.settingsHelpContent[this.activeSettingTab] || this.settingsHelpContent.general;
    },
    get searchResults() {
      const query = String(this.settingsQuery || "").trim().toLowerCase();
      if (!query) return [];
      return this.settingsSearchItems
        .filter((item) => `${item.title} ${item.keywords}`.toLowerCase().includes(query))
        .slice(0, 10);
    },
    get isSettingsDirty() {
      if (!this.settingsSnapshot) return false;
      const current = this.cloneSettings(this.settingsForm);
      const snapshot = this.settingsSnapshot;
      return (
        JSON.stringify(current) !== JSON.stringify(snapshot.form) ||
        this.normalizeLineList(this.allowedAbsRootsText).join("\n") !== snapshot.rootsText ||
        this.normalizeLineList(this.authTrustedProxiesText).join("\n") !== snapshot.proxiesText ||
        Boolean(this.$store?.global?.isDarkMode) !== Boolean(this.settingsSnapshotDarkMode)
      );
    },
    get saveStatusLabel() {
      if (this.saving || this.saveState === "saving") return "保存中";
      if (this.saveState === "saved") return this.saveMessage || "已保存";
      if (this.saveState === "warning") return this.saveMessage || "需要确认";
      if (this.saveState === "error") return this.saveMessage || "保存失败";
      return this.isSettingsDirty ? "未保存" : "已同步";
    },
    get saveStatusIcon() {
      if (this.saveState === "saved") return "check";
      if (this.saveState === "warning") return "alert-triangle";
      if (this.saveState === "error") return "close";
      return this.isSettingsDirty ? "settings-save" : "shield-check";
    },
    cloneSettings(value) {
      if (value === null || value === undefined) return value;
      if (typeof value !== "object") return value;
      try {
        return JSON.parse(JSON.stringify(value));
      } catch (_) {
        return { ...value };
      }
    },
    normalizeLineList(value) {
      if (Array.isArray(value)) {
        return value.map((item) => String(item || "").trim()).filter(Boolean);
      }
      return String(value || "")
        .split(/[\r\n,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
    },
    beginEditSession() {
      if (!this.$store?.global?.settingsForm) return;
      this.settingsSnapshot = {
        form: this.cloneSettings(this.settingsForm),
        rootsText: this.normalizeLineList(
          this.settingsForm.allowed_abs_resource_roots,
        ).join("\n"),
        proxiesText: this.normalizeLineList(
          this.settingsForm.auth_trusted_proxies,
        ).join("\n"),
      };
      this.settingsSnapshotDarkMode = Boolean(this.$store.global.isDarkMode);
      this.allowedAbsRootsText = this.settingsSnapshot.rootsText;
      this.authTrustedProxiesText = this.settingsSnapshot.proxiesText;
      this.settingsSessionOpen = true;
      this.showDiscardConfirm = false;
      this.saveState = "idle";
      this.saveMessage = "";
      this.pathSafetyMessage = "";
      this.operationMessage = "";
      this.backgroundUploadMessage = "";
      if (typeof document !== "undefined" && document.activeElement) {
        this.lastFocusedElement = document.activeElement;
      }
      setTimeout(() => this.$refs?.settingsSearch?.focus?.(), 0);
    },
    selectSettingTab(section) {
      if (!this.settingsHelpContent[section]) return;
      this.activeSettingTab = section;
      if (this.$refs?.settingsScroll) this.$refs.settingsScroll.scrollTop = 0;
    },
    jumpToSetting(section, anchor) {
      this.selectSettingTab(section);
      this.settingsQuery = "";
      if (typeof document === "undefined") return;
      setTimeout(() => {
        const target = document.getElementById(anchor);
        if (target?.scrollIntoView) {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }, 0);
    },
    openSettingsHelp() {
      this.showSettingsHelpModal = true;
      setTimeout(() => {
        const dialog = document.querySelector?.(".settings-help-modal");
        dialog?.focus?.();
      }, 0);
    },
    closeSettingsHelp() {
      this.showSettingsHelpModal = false;
    },
    keepEditing() {
      this.showDiscardConfirm = false;
    },
    handleEscape() {
      if (this.showDiscardConfirm) {
        this.keepEditing();
        return;
      }
      if (this.showSettingsHelpModal) {
        this.closeSettingsHelp();
        return;
      }
      if (this.showSettingsModal) this.requestClose();
    },
    requestClose() {
      if (this.saving) return;
      if (this.isSettingsDirty) {
        this.showDiscardConfirm = true;
        return;
      }
      this.closeSettings();
    },
    closeSettings() {
      this.showSettingsHelpModal = false;
      this.showDiscardConfirm = false;
      this.showSettingsModal = false;
      this.settingsSessionOpen = false;
      const focusTarget = this.lastFocusedElement;
      this.lastFocusedElement = null;
      if (focusTarget?.focus) setTimeout(() => focusTarget.focus(), 0);
    },
    discardChanges() {
      const snapshot = this.settingsSnapshot;
      if (snapshot?.form && this.$store?.global) {
        this.$store.global.settingsForm = this.cloneSettings(snapshot.form);
        this.$store.global.isDarkMode = Boolean(this.settingsSnapshotDarkMode);
        this.$store.global.applyDarkMode?.();
        this.$store.global.applyTheme?.(this.settingsForm.theme_accent);
        applyFontDom(this.settingsForm.font_style);
        this.$store.global.updateBackgroundImage?.(
          this.$store.global.resolveManagerBackgroundUrl?.() || this.settingsForm.bg_url || "",
        );
        this.allowedAbsRootsText = snapshot.rootsText;
        this.authTrustedProxiesText = snapshot.proxiesText;
      }
      this.closeSettings();
    },
    resetSettingsToDefaults() {
      const current = this.cloneSettings(this.settingsForm);
      Object.entries(DEFAULT_SETTINGS).forEach(([key, value]) => {
        current[key] = this.cloneSettings(value);
      });
      this.$store.global.settingsForm = current;
      this.$store.global.isDarkMode = Boolean(DEFAULT_SETTINGS.dark_mode);
      this.$store.global.applyDarkMode?.();
      this.$store.global.applyTheme?.(DEFAULT_SETTINGS.theme_accent);
      applyFontDom(DEFAULT_SETTINGS.font_style);
      this.allowedAbsRootsText = "";
      this.authTrustedProxiesText = "";
      this.schedulePathSafetyEvaluation(0);
      this.saveState = "idle";
      this.saveMessage = "默认值已载入，保存后生效";
    },
    get isolatedCategories() {
      return this.$store.global.isolatedCategories || [];
    },
    get showSettingsModal() {
      return this.$store.global.showSettingsModal;
    },
    set showSettingsModal(val) {
      this.$store.global.showSettingsModal = val;
    },

    updateCssVariable,

    get syncSafetySummary() {
      return this.pathSafety.blocked_actions?.length
        ? "部分同步操作因路径风险已被禁用。"
        : "当前同步操作未发现需要拦截的路径风险。";
    },

    resetPathSafety() {
      this.pathSafety = { ...EMPTY_PATH_SAFETY };
      this.pathSafetyState = "idle";
      this.pathSafetyMessage = "";
    },

    applyPathSafety(pathSafety) {
      const nextState = pathSafety && typeof pathSafety === "object" ? pathSafety : {};
      this.pathSafety = {
        ...EMPTY_PATH_SAFETY,
        ...nextState,
        blocked_actions: Array.isArray(nextState.blocked_actions)
          ? nextState.blocked_actions
          : [],
        conflicts: Array.isArray(nextState.conflicts) ? nextState.conflicts : [],
      };
      this.pathSafetyState = "ready";
      this.pathSafetyMessage = "";
    },

    getPathConflict(field) {
      return (this.pathSafety.conflicts || []).find((item) => item.field === field) || null;
    },

    getPathConflictMessage(field) {
      return this.getPathConflict(field)?.message || "";
    },

    buildPathSafetyConfirmationText(pathSafety = this.pathSafety) {
      const conflicts = Array.isArray(pathSafety?.conflicts) ? pathSafety.conflicts : [];
      const lines = conflicts.map((item) => `- ${item.message}`).filter(Boolean);
      if (!lines.length) {
        return "检测到路径存在重叠风险，确认后将继续保存。";
      }
      return [
        "检测到以下路径风险，确认后将继续保存：",
        ...lines,
      ].join("\n");
    },

    isSyncActionBlocked(action) {
      return (this.pathSafety.blocked_actions || []).includes(action);
    },

    beginPathSafetyEvaluation() {
      this.pathSafetyEvaluationVersion += 1;
      return this.pathSafetyEvaluationVersion;
    },

    async refreshPathSafety(evaluationVersion = null) {
      const activeVersion = evaluationVersion ?? this.beginPathSafetyEvaluation();
      if (!this.settingsForm.st_data_dir) {
        if (activeVersion === this.pathSafetyEvaluationVersion) this.resetPathSafety();
        return this.pathSafety;
      }

      this.pathSafetyState = "loading";
      this.pathSafetyMessage = "";
      try {
        const result = await evaluateSettingsPathSafety(this.settingsForm);

        if (activeVersion !== this.pathSafetyEvaluationVersion) {
          return this.pathSafety;
        }

        if (!this.settingsForm.st_data_dir) {
          this.resetPathSafety();
          return this.pathSafety;
        }

        this.applyPathSafety(result);
        return this.pathSafety;
      } catch (err) {
        if (activeVersion !== this.pathSafetyEvaluationVersion) return this.pathSafety;
        this.pathSafetyState = "error";
        this.pathSafetyMessage = err?.message || "路径安全检查请求失败";
        return this.pathSafety;
      }
    },

    async schedulePathSafetyEvaluation(delay = 250) {
      if (this.pathSafetyDebounceTimer) {
        clearTimeout(this.pathSafetyDebounceTimer);
        this.pathSafetyDebounceTimer = null;
      }

      const evaluationVersion = this.beginPathSafetyEvaluation();

      if (!this.settingsForm.st_data_dir) {
        this.resetPathSafety();
        return this.pathSafety;
      }

      return new Promise((resolve) => {
        this.pathSafetyDebounceTimer = setTimeout(async () => {
          this.pathSafetyDebounceTimer = null;
          resolve(await this.refreshPathSafety(evaluationVersion));
        }, delay);
      });
    },

    applyFont(type) {
      // 1. 更新全局状态 (这会让按钮的高亮 :class 重新计算)
      this.$store.global.settingsForm.font_style = type;

      // 2. 应用 CSS 样式 (改变视觉字体)
      applyFontDom(type);
    },

    // 1. 应用主题 (调用全局 Store 的 action)
    applyTheme(color) {
      if (typeof this.$store.global.applyTheme === "function") {
        this.$store.global.applyTheme(color);
      } else {
        this.settingsForm.theme_accent = color;
      }
    },

    // 2. 切换深色模式 (调用全局 Store)
    toggleDarkMode() {
      const global = this.$store.global;
      global.isDarkMode = !Boolean(global.isDarkMode);
      this.settingsForm.dark_mode = global.isDarkMode;
      if (typeof global.applyDarkMode === "function") global.applyDarkMode();
    },

    // 3. 立即扫描 (scanNow)
    scanNow() {
      if (
        !confirm(
          "立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）",
        )
      )
        return;

      this.operationLoadingAction = "scan";
      this.operationState = "loading";
      this.operationMessage = "正在触发全量扫描...";
      this.$store.global.isLoading = true;
      triggerScan()
        .then((res) => {
          if (!res.success) {
            this.operationState = "error";
            this.operationMessage = "触发扫描失败: " + (res.msg || "unknown");
            alert(this.operationMessage);
          } else {
            this.operationState = "success";
            this.operationMessage = "已触发扫描任务，后台正在进行。";
            alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
          }
        })
        .catch((err) => {
          this.operationState = "error";
          this.operationMessage = "网络错误: " + err;
          alert(this.operationMessage);
        })
        .finally(() => {
          this.operationLoadingAction = "";
          this.$store.global.isLoading = false;
        });
    },

    // 数字设置步进控制
    adjustNumberSetting(field, delta, min = null, max = null) {
      const current = Number(this.settingsForm[field]);
      const fallback = min === null ? 0 : Number(min);
      let next = Number.isFinite(current) ? current : fallback;
      next = Math.round(next + Number(delta));

      if (min !== null) next = Math.max(Number(min), next);
      if (max !== null) next = Math.min(Number(max), next);

      this.settingsForm[field] = next;
    },

    // 4. 系统操作 (systemAction: 打开文件夹、备份等)
    systemAction(action) {
      this.operationLoadingAction = action;
      this.operationState = "loading";
      this.operationMessage = "正在执行操作...";
      performSystemAction(action)
        .then((res) => {
          if (!res.success) {
            this.operationState = "error";
            this.operationMessage = res.msg || "操作失败";
          } else {
            this.operationState = "success";
            this.operationMessage = res.msg || "操作已完成";
          }
          if (res.msg) alert(res.msg);
        })
        .catch((err) => {
          this.operationState = "error";
          this.operationMessage = "请求失败: " + err;
          alert(this.operationMessage);
        })
        .finally(() => {
          this.operationLoadingAction = "";
        });
    },

    // === 初始化 ===
    init() {
      // 设置数据直接绑定到 $store.global.settingsForm
      // 无需本地 duplicate
      this.$watch("showSettingsModal", (val) => {
        if (val) {
          if (!this.settingsSessionOpen) this.beginEditSession();
          if (this.settingsForm.st_data_dir) {
            this.schedulePathSafetyEvaluation(0);
          } else {
            this.resetPathSafety();
          }
        } else {
          this.settingsSessionOpen = false;
        }
      });

      [
        "settingsForm.cards_dir",
        "settingsForm.world_info_dir",
        "settingsForm.chats_dir",
        "settingsForm.resources_dir",
        "settingsForm.presets_dir",
        "settingsForm.regex_dir",
        "settingsForm.scripts_dir",
        "settingsForm.quick_replies_dir",
        "settingsForm.beautify_dir",
        "settingsForm.st_data_dir",
        "settingsForm.st_openai_preset_dir",
      ].forEach((expression) => {
        this.$watch(expression, () => {
          if (!this.showSettingsModal) return;
          this.schedulePathSafetyEvaluation();
        });
      });
    },

    openSettings() {
      this.beginEditSession();
      this.showSettingsModal = true;
    },

    async saveSettings(closeModal = true, options = {}) {
      if (this.saving && !options.confirm_risky_paths) return { success: false, msg: "正在保存" };

      this.settingsForm.allowed_abs_resource_roots = this.normalizeLineList(
        this.allowedAbsRootsText,
      );
      this.settingsForm.auth_trusted_proxies = this.normalizeLineList(
        this.authTrustedProxiesText,
      );
      this.saving = true;
      this.saveState = "saving";
      this.saveMessage = "";

      try {
        const res = await this.$store.global.saveSettings(closeModal, options);
        if (res?.path_safety) this.applyPathSafety(res.path_safety);

        if (res?.requires_confirmation) {
          this.saving = false;
          this.saveState = "warning";
          this.saveMessage = "需要确认路径风险";
          const confirmed = confirm(
            this.buildPathSafetyConfirmationText(res.path_safety),
          );
          if (!confirmed) return res;
          return this.saveSettings(closeModal, {
            ...options,
            confirm_risky_paths: true,
          });
        }

        if (res?.success) {
          this.settingsSnapshot = {
            form: this.cloneSettings(this.settingsForm),
            rootsText: this.normalizeLineList(
              this.settingsForm.allowed_abs_resource_roots,
            ).join("\n"),
            proxiesText: this.normalizeLineList(
              this.settingsForm.auth_trusted_proxies,
            ).join("\n"),
          };
          this.settingsSnapshotDarkMode = Boolean(this.$store.global.isDarkMode);
          this.saveState = res.saved_with_warnings ? "warning" : "saved";
          this.saveMessage = res.saved_with_warnings ? "已保存，有提示" : "已保存";
          if (closeModal) this.closeSettings();
        } else {
          this.saveState = "error";
          this.saveMessage = res?.msg || "保存失败";
        }
        return res;
      } catch (err) {
        this.saveState = "error";
        this.saveMessage = err?.message || "保存请求失败";
        return { success: false, msg: this.saveMessage };
      } finally {
        this.saving = false;
      }
    },

    applyBackgroundUrlInput() {
      this.$store.global.settingsForm.manager_wallpaper_id = "";
      this.$store.global.updateBackgroundImage(
        this.$store.global.resolveManagerBackgroundUrl(),
      );
    },

    clearBackgroundSelection() {
      this.$store.global.settingsForm.manager_wallpaper_id = "";
      this.$store.global.settingsForm.bg_url = "";
      this.$store.global.updateBackgroundImage(
        this.$store.global.resolveManagerBackgroundUrl(),
      );
    },

    applySharedWallpaperSelection(detail = {}) {
      if (String(detail.selectionTarget || "").trim() !== "manager") return;

      const wallpaper = detail.wallpaper || null;
      if (!wallpaper?.id) return;

      this.$store.global.settingsForm.manager_wallpaper_id = wallpaper.id;
      this.$store.global.settingsForm.bg_url = "";
      this.$store.global.updateBackgroundImage(
        this.$store.global.resolveManagerBackgroundUrl(),
      );
    },

    removeIsolatedCategory(path) {
      return this.$store.global.removeIsolatedCategory(path);
    },

    clearIsolatedCategories() {
      return this.$store.global.saveIsolatedCategories([]).then((res) => {
        if (res?.success) {
          this.$store.global.showToast("已清空隔离分类", 1800);
        }
        return res;
      });
    },

    // === 背景图上传 ===

    triggerBackgroundUpload() {
      this.$refs.bgUploadInput.click();
    },

    handleBackgroundUpload(e) {
      const file = e.target.files[0];
      if (!file) return;

      if (file.size > 10 * 1024 * 1024) {
        this.backgroundUploadState = "error";
        this.backgroundUploadMessage = "图片太大，请上传 10MB 以内的图片";
        alert("图片太大，请上传 10MB 以内的图片");
        return;
      }

      const formData = new FormData();
      formData.append("file", file);

      const btn = e.target.previousElementSibling;
      const originalContent = btn ? btn.innerHTML : "";
      const originalText = btn ? btn.innerText : "";
      if (btn) {
        if ("innerText" in btn) btn.innerText = "上传中...";
        else btn.innerHTML = '<svg class="ui-icon ui-icon--md" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="/static/icons/ui.svg#icon-loader-circle"></use></svg>';
      }
      this.backgroundUploadState = "loading";
      this.backgroundUploadMessage = "正在上传壁纸...";

      return uploadBackground(formData)
        .then((res) => {
          if (res.success) {
            // 更新 Store
            this.$store.global.settingsForm.manager_wallpaper_id = "";
            this.$store.global.settingsForm.bg_url = res.url;
            this.$store.global.updateBackgroundImage(
              this.$store.global.resolveManagerBackgroundUrl(),
            );
            this.backgroundUploadState = "success";
            this.backgroundUploadMessage = "壁纸上传成功";
          } else {
            this.backgroundUploadState = "error";
            this.backgroundUploadMessage = "上传失败: " + (res.msg || "unknown");
            alert("上传失败: " + res.msg);
          }
        })
        .catch((err) => {
          this.backgroundUploadState = "error";
          this.backgroundUploadMessage = "网络错误: " + err;
          alert("网络错误: " + err);
        })
        .finally(() => {
          if (btn) {
            if ("innerText" in btn) btn.innerText = originalText;
            else btn.innerHTML = originalContent;
          }
          e.target.value = "";
        });
    },

    // === 回收站操作 ===

    openTrashFolder() {
      this.operationLoadingAction = "open_trash";
      this.operationState = "loading";
      this.operationMessage = "正在打开回收站...";
      return openTrash()
        .then((res) => {
          this.operationState = res.success ? "success" : "error";
          this.operationMessage = res.success
            ? "已打开回收站"
            : "打开失败: " + res.msg;
          if (!res.success) alert(this.operationMessage);
          return res;
        })
        .catch((err) => {
          this.operationState = "error";
          this.operationMessage = "打开失败: " + err;
          alert(this.operationMessage);
          return { success: false, msg: this.operationMessage };
        })
        .finally(() => {
          this.operationLoadingAction = "";
        });
    },

    emptyTrash() {
      if (!confirm("确定要彻底清空回收站吗？此操作无法撤销！")) return;
      this.operationLoadingAction = "empty_trash";
      this.operationState = "loading";
      this.operationMessage = "正在清空回收站...";
      return emptyTrash()
        .then((res) => {
          this.operationState = res.success ? "success" : "error";
          this.operationMessage = res.success
            ? res.msg || "回收站已清空"
            : "清空失败: " + res.msg;
          alert(this.operationMessage);
          return res;
        })
        .catch((err) => {
          this.operationState = "error";
          this.operationMessage = "清空失败: " + err;
          alert(this.operationMessage);
          return { success: false, msg: this.operationMessage };
        })
        .finally(() => {
          this.operationLoadingAction = "";
        });
    },

    async exportUserDbData() {
      this.operationLoadingAction = "export_user_db";
      this.operationState = "loading";
      this.operationMessage = "正在导出用户 DB 数据...";
      try {
        const res = await exportUserDbBackup();
        if (!res.success) {
          this.operationState = "error";
          this.operationMessage = "导出失败: " + (res.msg || "unknown");
          alert("导出失败: " + (res.msg || "unknown"));
          return;
        }
        this.operationState = "success";
        this.operationMessage = "用户 DB 数据导出成功";
        alert("导出成功: " + (res.file_name || "unknown"));
      } catch (err) {
        this.operationState = "error";
        this.operationMessage = "导出失败: " + (err.message || err);
        alert("导出失败: " + (err.message || err));
      } finally {
        this.operationLoadingAction = "";
      }
    },

    triggerUserDbImport() {
      this.$refs.userDbImportInput?.click();
    },

    async handleUserDbImport(e) {
      const file = e.target.files[0];
      if (!file) return;

      try {
        const confirmed = confirm(
          "确定要导入该备份吗？\n这会恢复仅存储在用户 DB 中的状态（如收藏、剪贴板、历史记录、监控池配置与成员），不会影响 ui_data.json。",
        );
        if (!confirmed) return;

        this.operationLoadingAction = "import_user_db";
        this.operationState = "loading";
        this.operationMessage = "正在导入用户 DB 数据...";

        const formData = new FormData();
        formData.append("file", file);

        const res = await importUserDbBackup(formData);
        if (!res.success) {
          this.operationState = "error";
          this.operationMessage = "导入失败: " + (res.msg || "unknown");
          alert("导入失败: " + (res.msg || "unknown"));
          return;
        }

        const stats = res.stats || {};
        const favorites = stats.favorites?.imported || 0;
        const clipboard = stats.wi_clipboard?.imported || 0;
        const history = stats.wi_entry_history?.imported || 0;
        const monitor = stats.source_update_monitor;
        const resultLines = [
          "导入成功",
          `收藏: 导入 ${favorites}`,
          `剪贴板: 导入 ${clipboard}`,
          `历史记录: 导入 ${history}`,
        ];
        if (monitor) {
          const monitorPools = monitor.pools?.imported || 0;
          const monitorEntries = monitor.entries?.imported || 0;
          resultLines.push(`监控池: 导入 ${monitorPools} 个配置、${monitorEntries} 个成员`);
        }
        alert(
          resultLines.join("\n"),
        );
        this.operationState = "success";
        this.operationMessage = "用户 DB 数据导入成功";
      } catch (err) {
        this.operationState = "error";
        this.operationMessage = "导入失败: " + (err.message || err);
        alert("导入失败: " + (err.message || err));
      } finally {
        this.operationLoadingAction = "";
        e.target.value = "";
      }
    },

    // === SillyTavern 同步功能 ===

    stPathStatus: "",
    stPathStatusIcon: "",
    stPathValid: false,
    stResources: {},
    syncing: false,
    syncStatus: "",
    syncStatusIcon: "",
    syncSuccess: false,

    getResourceLabel(type) {
      const labels = {
        characters: "角色卡",
        chats: "聊天记录",
        worlds: "世界书",
        presets: "预设",
        regex: "正则脚本",
        quick_replies: "快速回复",
        scripts: "ST脚本",
      };
      return labels[type] || type;
    },

    getResourceIcon(type) {
      const icons = {
        characters: "cards-stack",
        chats: "chat-bubbles",
        worlds: "book-stack",
        presets: "preset-stack",
        regex: "regex-file",
        quick_replies: "reply-bolt",
        scripts: "script-brackets",
      };
      return icons[type] || "folder-solid";
    },

    async detectSTPath() {
      try {
        this.stPathStatus = "正在探测...";
        this.stPathStatusIcon = "";
        const resp = await fetch("/api/st/detect_path");
        const data = await resp.json();

        if (data.success && data.path) {
          this.$store.global.settingsForm.st_data_dir = data.path;
          this.stPathStatus = `探测到路径: ${data.path}`;
          this.stPathStatusIcon = "check";
          this.stPathValid = true;
          await this.validateSTPath();
        } else {
          this.stPathStatus = "未能自动探测到 SillyTavern 安装路径，请手动配置";
          this.stPathStatusIcon = "close";
          this.stPathValid = false;
        }
      } catch (err) {
        this.stPathStatus = "探测失败: " + err.message;
        this.stPathStatusIcon = "close";
        this.stPathValid = false;
      }
    },

    async validateSTPath() {
      const path = this.$store.global.settingsForm.st_data_dir;
      if (!path) {
        this.stPathStatus = "请输入或探测路径";
        this.stPathStatusIcon = "close";
        this.stPathValid = false;
        this.stResources = {};
        return;
      }

      try {
        this.stPathStatus = "正在验证...";
        this.stPathStatusIcon = "";
        const resp = await fetch("/api/st/validate_path", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        const data = await resp.json();

        if (data.success && data.valid) {
          if (data.normalized_path && data.normalized_path !== path) {
            this.$store.global.settingsForm.st_data_dir = data.normalized_path;
            this.stPathStatus = `路径有效，已转换为安装根目录：${data.normalized_path}`;
          } else {
            this.stPathStatus = "路径有效";
          }
          this.stPathStatusIcon = "check";
          this.stPathValid = true;
          this.stResources = data.resources || {};
          await this.refreshPathSafety();
        } else {
          this.stPathStatus = "路径无效或不是 SillyTavern 安装目录";
          this.stPathStatusIcon = "close";
          this.stPathValid = false;
          this.stResources = {};
          this.resetPathSafety();
        }
      } catch (err) {
        this.stPathStatus = "验证失败: " + err.message;
        this.stPathStatusIcon = "close";
        this.stPathValid = false;
        this.stResources = {};
        this.resetPathSafety();
      }
    },

    async syncFromST(resourceType) {
      if (this.syncing) return;
      const action = `sync_${resourceType}`;
      if (this.isSyncActionBlocked(action)) {
        this.syncStatus = `${this.getResourceLabel(resourceType)}同步已被禁用：${this.syncSafetySummary}`;
        this.syncStatusIcon = "close";
        this.syncSuccess = false;
        return;
      }

      this.syncing = true;
      this.syncStatus = `正在同步 ${this.getResourceLabel(resourceType)}...`;
      this.syncStatusIcon = "";
      this.syncSuccess = false;

      try {
        let stPath = (this.$store.global.settingsForm.st_data_dir || "").trim();
        if (!stPath) {
          const input = document.querySelector(
            'input[x-model="settingsForm.st_data_dir"]',
          );
          if (input && input.value) stPath = input.value.trim();
        }
        const resp = await fetch("/api/st/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resource_type: resourceType,
            st_data_dir: stPath,
          }),
        });
        const data = await resp.json();

        if (data.success) {
          const result = data.result;
          this.syncStatus = `同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
          this.syncSuccess = result.failed === 0;
          this.syncStatusIcon = result.failed === 0 ? "check" : "alert-triangle";

          // 同步成功后触发刷新
          if (result.success > 0) {
            if (resourceType === "characters") {
              this.syncStatus += "，正在刷新列表...";
              // 等待后端扫描完成
              await new Promise((r) => setTimeout(r, 1500));
              window.dispatchEvent(new CustomEvent("refresh-card-list"));
              this.syncStatus = `同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
            } else if (resourceType === "chats") {
              window.dispatchEvent(new CustomEvent("refresh-chat-list"));
            } else if (resourceType === "worlds") {
              window.dispatchEvent(new CustomEvent("refresh-wi-list"));
            }
          }
        } else {
          this.syncStatus = "同步失败: " + (data.error || "未知错误");
          this.syncStatusIcon = "close";
          this.syncSuccess = false;
        }
      } catch (err) {
        this.syncStatus = "同步失败: " + err.message;
        this.syncStatusIcon = "close";
        this.syncSuccess = false;
      } finally {
        this.syncing = false;
      }
    },

    async syncAllFromST() {
      if (this.syncing) return;
      if (this.isSyncActionBlocked("sync_all")) {
        this.syncStatus = `全部同步已被禁用：${this.syncSafetySummary}`;
        this.syncStatusIcon = "close";
        this.syncSuccess = false;
        return;
      }

      const types = [
        "characters",
        "chats",
        "worlds",
        "presets",
        "regex",
        "quick_replies",
      ];
      let totalSuccess = 0;
      let totalFailed = 0;
      let hasCharacters = false;
      let hasChats = false;
      let hasWorlds = false;

      this.syncing = true;
      this.syncStatusIcon = "";

      let stPath = (this.$store.global.settingsForm.st_data_dir || "").trim();
      if (!stPath) {
        const input = document.querySelector(
          'input[x-model="settingsForm.st_data_dir"]',
        );
        if (input && input.value) stPath = input.value.trim();
      }
      for (const type of types) {
        this.syncStatus = `正在同步 ${this.getResourceLabel(type)}...`;

        try {
          const resp = await fetch("/api/st/sync", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resource_type: type, st_data_dir: stPath }),
          });
          const data = await resp.json();

          if (data.success) {
            totalSuccess += data.result.success;
            totalFailed += data.result.failed;
            if (type === "characters" && data.result.success > 0) {
              hasCharacters = true;
            }
            if (type === "chats" && data.result.success > 0) {
              hasChats = true;
            }
            if (type === "worlds" && data.result.success > 0) {
              hasWorlds = true;
            }
          }
        } catch (err) {
          totalFailed++;
        }
      }

      this.syncStatus = `全部同步完成: ${totalSuccess} 个成功, ${totalFailed} 个失败`;
      this.syncSuccess = totalFailed === 0;
      this.syncStatusIcon = totalFailed === 0 ? "check" : "alert-triangle";
      this.syncing = false;

      // 同步成功后触发刷新
      if (hasCharacters) {
        await new Promise((r) => setTimeout(r, 1500));
        window.dispatchEvent(new CustomEvent("refresh-card-list"));
      }
      if (hasChats) {
        window.dispatchEvent(new CustomEvent("refresh-chat-list"));
      }
      if (hasWorlds) {
        window.dispatchEvent(new CustomEvent("refresh-wi-list"));
      }
    },
  };
}
