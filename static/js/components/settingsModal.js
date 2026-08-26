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
      this.$store.global.applyTheme(color);
    },

    // 2. 切换深色模式 (调用全局 Store)
    toggleDarkMode() {
      this.$store.global.toggleDarkMode();
    },

    // 3. 立即扫描 (scanNow)
    scanNow() {
      if (
        !confirm(
          "立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）",
        )
      )
        return;

      this.$store.global.isLoading = true;
      triggerScan()
        .then((res) => {
          if (!res.success) alert("触发扫描失败: " + (res.msg || "unknown"));
          else alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
        })
        .catch((err) => alert("网络错误: " + err))
        .finally(() => {
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
      performSystemAction(action)
        .then((res) => {
          if (!res.success && res.msg) alert(res.msg);
          else if (res.msg) alert(res.msg);
        })
        .catch((err) => alert("请求失败: " + err));
    },

    // === 初始化 ===
    init() {
      // 设置数据直接绑定到 $store.global.settingsForm
      // 无需本地 duplicate
      this.$watch("showSettingsModal", (val) => {
        if (val) {
          const roots = this.settingsForm.allowed_abs_resource_roots || [];
          this.allowedAbsRootsText = Array.isArray(roots)
            ? roots.join("\n")
            : String(roots || "");
          if (this.settingsForm.st_data_dir) {
            this.schedulePathSafetyEvaluation(0);
          } else {
            this.resetPathSafety();
          }
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
      const roots = this.settingsForm.allowed_abs_resource_roots || [];
      this.allowedAbsRootsText = Array.isArray(roots)
        ? roots.join("\n")
        : String(roots || "");
      this.showSettingsModal = true;
    },

    async saveSettings(closeModal = true, options = {}) {
      const roots = (this.allowedAbsRootsText || "")
        .split(/[\r\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      this.settingsForm.allowed_abs_resource_roots = roots;
      const res = await this.$store.global.saveSettings(closeModal, options);
      if (res?.path_safety) {
        this.applyPathSafety(res.path_safety);
      }

      if (res?.requires_confirmation) {
        const confirmed = confirm(this.buildPathSafetyConfirmationText(res.path_safety));
        if (!confirmed) return res;
        return this.saveSettings(closeModal, { ...options, confirm_risky_paths: true });
      }

      if (res?.success && closeModal) {
        this.showSettingsModal = false;
      }
      return res;
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
        alert("图片太大，请上传 10MB 以内的图片");
        return;
      }

      const formData = new FormData();
      formData.append("file", file);

      const btn = e.target.previousElementSibling;
      const originalText = btn ? btn.innerText : "";
      if (btn) btn.innerText = "⏳...";

      return uploadBackground(formData)
        .then((res) => {
          if (res.success) {
            // 更新 Store
            this.$store.global.settingsForm.manager_wallpaper_id = "";
            this.$store.global.settingsForm.bg_url = res.url;
            this.$store.global.updateBackgroundImage(
              this.$store.global.resolveManagerBackgroundUrl(),
            );
          } else {
            alert("上传失败: " + res.msg);
          }
        })
        .catch((err) => {
          alert("网络错误: " + err);
        })
        .finally(() => {
          if (btn) btn.innerText = originalText;
          e.target.value = "";
        });
    },

    // === 回收站操作 ===

    openTrashFolder() {
      openTrash().then((res) => {
        if (!res.success) alert("打开失败: " + res.msg);
      });
    },

    emptyTrash() {
      if (!confirm("确定要彻底清空回收站吗？此操作无法撤销！")) return;
      emptyTrash().then((res) => {
        if (res.success) alert(res.msg);
        else alert("清空失败: " + res.msg);
      });
    },

    async exportUserDbData() {
      try {
        const res = await exportUserDbBackup();
        if (!res.success) {
          alert("导出失败: " + (res.msg || "unknown"));
          return;
        }
        alert("导出成功: " + (res.file_name || "unknown"));
      } catch (err) {
        alert("导出失败: " + (err.message || err));
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
          "确定要导入该备份吗？\n这会恢复仅存储在用户 DB 中的状态（如收藏、剪贴板、历史记录），不会影响 ui_data.json。",
        );
        if (!confirmed) return;

        const formData = new FormData();
        formData.append("file", file);

        const res = await importUserDbBackup(formData);
        if (!res.success) {
          alert("导入失败: " + (res.msg || "unknown"));
          return;
        }

        const stats = res.stats || {};
        const favorites = stats.favorites?.imported || 0;
        const clipboard = stats.wi_clipboard?.imported || 0;
        const history = stats.wi_entry_history?.imported || 0;
        alert(
          [
            "导入成功",
            `收藏: 导入 ${favorites}`,
            `剪贴板: 导入 ${clipboard}`,
            `历史记录: 导入 ${history}`,
          ].join("\n"),
        );
      } catch (err) {
        alert("导入失败: " + (err.message || err));
      } finally {
        e.target.value = "";
      }
    },

    // === SillyTavern 同步功能 ===

    stPathStatus: "",
    stPathValid: false,
    stResources: {},
    syncing: false,
    syncStatus: "",
    syncSuccess: false,

    getResourceLabel(type) {
      const labels = {
        characters: "🎴 角色卡",
        chats: "💬 聊天记录",
        worlds: "📚 世界书",
        presets: "📝 预设",
        regex: "🔧 正则脚本",
        quick_replies: "💬 快速回复",
        scripts: "📜 ST脚本",
      };
      return labels[type] || type;
    },

    async detectSTPath() {
      try {
        this.stPathStatus = "正在探测...";
        const resp = await fetch("/api/st/detect_path");
        const data = await resp.json();

        if (data.success && data.path) {
          this.$store.global.settingsForm.st_data_dir = data.path;
          this.stPathStatus = `✓ 探测到路径: ${data.path}`;
          this.stPathValid = true;
          await this.validateSTPath();
        } else {
          this.stPathStatus = "未能自动探测到 SillyTavern 安装路径，请手动配置";
          this.stPathValid = false;
        }
      } catch (err) {
        this.stPathStatus = "探测失败: " + err.message;
        this.stPathValid = false;
      }
    },

    async validateSTPath() {
      const path = this.$store.global.settingsForm.st_data_dir;
      if (!path) {
        this.stPathStatus = "请输入或探测路径";
        this.stPathValid = false;
        this.stResources = {};
        return;
      }

      try {
        this.stPathStatus = "正在验证...";
        const resp = await fetch("/api/st/validate_path", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        const data = await resp.json();

        if (data.success && data.valid) {
          if (data.normalized_path && data.normalized_path !== path) {
            this.$store.global.settingsForm.st_data_dir = data.normalized_path;
            this.stPathStatus = `✓ 路径有效，已转换为安装根目录：${data.normalized_path}`;
          } else {
            this.stPathStatus = "✓ 路径有效";
          }
          this.stPathValid = true;
          this.stResources = data.resources || {};
          await this.refreshPathSafety();
        } else {
          this.stPathStatus = "✗ 路径无效或不是 SillyTavern 安装目录";
          this.stPathValid = false;
          this.stResources = {};
          this.resetPathSafety();
        }
      } catch (err) {
        this.stPathStatus = "验证失败: " + err.message;
        this.stPathValid = false;
        this.stResources = {};
        this.resetPathSafety();
      }
    },

    async syncFromST(resourceType) {
      if (this.syncing) return;
      const action = `sync_${resourceType}`;
      if (this.isSyncActionBlocked(action)) {
        this.syncStatus = `✗ ${this.getResourceLabel(resourceType)}同步已被禁用：${this.syncSafetySummary}`;
        this.syncSuccess = false;
        return;
      }

      this.syncing = true;
      this.syncStatus = `正在同步 ${this.getResourceLabel(resourceType)}...`;
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
          this.syncStatus = `✓ 同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
          this.syncSuccess = result.failed === 0;

          // 同步成功后触发刷新
          if (result.success > 0) {
            if (resourceType === "characters") {
              this.syncStatus += "，正在刷新列表...";
              // 等待后端扫描完成
              await new Promise((r) => setTimeout(r, 1500));
              window.dispatchEvent(new CustomEvent("refresh-card-list"));
              this.syncStatus = `✓ 同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
            } else if (resourceType === "chats") {
              window.dispatchEvent(new CustomEvent("refresh-chat-list"));
            } else if (resourceType === "worlds") {
              window.dispatchEvent(new CustomEvent("refresh-wi-list"));
            }
          }
        } else {
          this.syncStatus = "✗ 同步失败: " + (data.error || "未知错误");
          this.syncSuccess = false;
        }
      } catch (err) {
        this.syncStatus = "✗ 同步失败: " + err.message;
        this.syncSuccess = false;
      } finally {
        this.syncing = false;
      }
    },

    async syncAllFromST() {
      if (this.syncing) return;
      if (this.isSyncActionBlocked("sync_all")) {
        this.syncStatus = `✗ 全部同步已被禁用：${this.syncSafetySummary}`;
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

      this.syncStatus = `✓ 全部同步完成: ${totalSuccess} 个成功, ${totalFailed} 个失败`;
      this.syncSuccess = totalFailed === 0;
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
