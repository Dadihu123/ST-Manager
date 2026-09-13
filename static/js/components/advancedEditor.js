/**
 * static/js/components/advancedEditor.js
 * 高级编辑器组件 (正则脚本 & 扩展脚本)
 */

import { ManagerScriptRuntime } from "../runtime/scriptRuntime.js";
import { subscribeRuntimeManager } from "../runtime/runtimeManager.js";
import { renderUnifiedPreviewHost, updateShadowContent } from "../utils/dom.js";
import { runRegexTestBenchScript } from "../utils/regexTestBench.js";
import {
  extractPresetTavernScripts,
  normalizePresetExtensionsForEditor,
} from "../utils/extensionCompatibility.js";
import { isValidRegexData, isValidScriptData } from "./pasteImportHandler.js";

export default function advancedEditor() {
  return {
    // === 本地状态 ===
    showAdvancedModal: false,
    activeTab: "regex",
    activeRegexIndex: -1,
    showMobileSidebar: false, // 移动端侧边栏显示状态

    regexPreviewMode: "text", // text | html
    showLargePreview: false,

    // 正则测试
    regexTestInput: "",
    regexTestResult: "",
    regexTestResultIcon: "",
    scriptDataError: "",

    // 编辑器级反馈与危险操作确认
    editorFeedback: { type: "", message: "" },
    showDeleteConfirm: false,
    deleteRequest: null,
    isSavingFile: false,
    _editorFeedbackTimer: null,

    // ST脚本扩展
    activeScriptIndex: -1,
    scriptDataJson: "",
    scriptRuntimeState: {
      status: "idle",
      lastError: "",
      logs: [],
      buttonConfig: { enabled: true, buttons: [] },
      height: 0,
      bridgeCapabilities: [
        "toast",
        "fetch(text/json)",
        "get-host-state",
        "get-active-context/card/preset/chat",
        "list-runtimes",
        "open-detail",
        "refresh-list",
        "get-runtime-state",
        "reload-runtime",
        "stop-runtime",
      ],
    },
    runtimeManagerOverview: {
      total: 0,
      byKind: {},
      byStatus: {},
      items: [],
    },
    activeRuntimeScriptId: null,

    // QR脚本扩展
    activeQrIndex: -1,

    // 数据引用 (从 detailModal 传入)
    editingData: {
      extensions: {
        regex_scripts: [],
        tavern_helper: [],
      },
    },

    isFileMode: false,
    currentFilePath: null,
    fileType: null, // 'regex' | 'script'
    editorCommitMode: "apply-only",
    showPersistButton: false,
    isPersistPending: false,

    updateShadowContent,
    renderUnifiedPreviewHost:
      typeof renderUnifiedPreviewHost === "function"
        ? renderUnifiedPreviewHost
        : updateShadowContent,
    scriptRuntime: null,
    _runtimeManagerUnsubscribe: null,

    init() {
      this._runtimeManagerUnsubscribe = subscribeRuntimeManager((snapshot) => {
        this.runtimeManagerOverview = snapshot;
      });
      this.initScriptRuntime();

      // 监听打开事件
      // detailModal 或者 HTML 中的按钮需要触发此事件，并传递 editingData 的引用
      window.addEventListener("open-advanced-editor", (e) => {
        const detail = e.detail || {};
        this.activeRegexIndex = -1;
        this.activeScriptIndex = -1;
        this.activeQrIndex = -1;
        this.isFileMode = false;
        this.currentFilePath = null;
        this.fileType = null;
        this.editorCommitMode = detail.editorCommitMode || "apply-only";
        this.showPersistButton = detail.showPersistButton === true;
        this.isPersistPending = false;
        this.editingData = detail; // 接收引用，实现响应式同步
        this.editingData.extensions = normalizePresetExtensionsForEditor(
          this.editingData.extensions,
        );
        this.showAdvancedModal = true;
        this.activeTab = "regex";
        this.activeRegexIndex = -1;
        this.regexTestInput = "";
        this.regexTestResult = "";
        this.regexTestResultIcon = "";
        this.regexPreviewMode = "text";
        this.scriptDataError = "";
        this.editorFeedback = { type: "", message: "" };
        this.showDeleteConfirm = false;
        this.deleteRequest = null;
        this.isSavingFile = false;
        // 确保数据结构完整
        if (!this.editingData.extensions) this.editingData.extensions = {};
        if (!this.editingData.extensions.regex_scripts)
          this.editingData.extensions.regex_scripts = [];
        if (this.editingData.quick_reply) {
          this._normalizeQrSet(this.editingData.quick_reply);
        }
        // 确保 Helper 脚本也经过清洗
        this.getTavernScripts().forEach((s) => this._normalizeScript(s));

        if (this.$store.global.deviceType === "mobile") {
          this.showMobileSidebar = false;
        }

        this.$nextTick(() => {
          this.mountScriptRuntimeHost();
          this.syncRuntimeContext();
        });
      });

      // 监听打开独立文件事件
      window.addEventListener("open-script-file-editor", (e) => {
        const { fileData, filePath, type } = e.detail;
        this.activeRegexIndex = -1;
        this.activeScriptIndex = -1;
        this.activeQrIndex = -1;
        this.isFileMode = true;
        this.editorCommitMode = "file";
        this.showPersistButton = false;
        this.isPersistPending = false;
        this.currentFilePath = filePath;
        this.fileType = type; // 'regex' or 'script'
        // 立即清洗数据，防止 Alpine 渲染报错
        if (type === "script") {
          this._normalizeScript(fileData);
        } else if (type === "quick_reply") {
          this._normalizeQrSet(fileData);
        }
        this.showAdvancedModal = true;
        this.scriptDataError = "";
        this.editorFeedback = { type: "", message: "" };
        this.showDeleteConfirm = false;
        this.deleteRequest = null;
        this.isSavingFile = false;

        // 构造一个伪造的 editingData 结构，让现有 UI 能够复用
        // 因为 UI 绑定的是 editingData.extensions.regex_scripts 等
        this.editingData = {
          extensions: {
            regex_scripts: type === "regex" ? [fileData] : [],
            tavern_helper:
              type === "script" ? { scripts: [fileData] } : { scripts: [] },
          },
          quick_reply: type === "quick_reply" ? fileData : null,
        };

        // 自动选中
        if (type === "regex") {
          this.activeTab = "regex";
          this.activeRegexIndex = 0;
        } else if (type === "quick_reply") {
          this.activeTab = "quick_reply";
          this.activeQrIndex = fileData.qrList?.length ? 0 : -1;
        } else {
          // 默认为 Scripts
          this.activeTab = "scripts";
          this.activeScriptIndex = 0;
          this.scriptDataJson = JSON.stringify(fileData.data || {}, null, 2);
        }

        this.$nextTick(() => {
          this.mountScriptRuntimeHost();
          this.syncRuntimeContext();
        });
      });

      this._closeAdvancedEditorHandler = () => {
        this.isPersistPending = false;
        this.showAdvancedModal = false;
      };
      window.addEventListener(
        "advanced-editor-close",
        this._closeAdvancedEditorHandler,
      );

      this.$watch("activeScriptIndex", (idx) => {
        if (idx > -1) {
          const script = this.getTavernScripts()[idx];
          if (script) {
            this._normalizeScript(script); // 再次确保安全
            this.scriptDataJson = JSON.stringify(script.data, null, 2);
          }
        }
        this.$nextTick(() => {
          this.mountScriptRuntimeHost();
          this.syncRuntimeContext();
        });
      });

      this.$watch("showAdvancedModal", (visible) => {
        if (!visible) {
          this.stopScriptRuntime();
        } else {
          this.$nextTick(() => {
            this.mountScriptRuntimeHost();
            this.syncRuntimeContext();
          });
        }
      });
    },

    initScriptRuntime() {
      this.scriptRuntime = new ManagerScriptRuntime({
        onStatus: (status, detail) => {
          this.scriptRuntimeState.status = status;
          this.scriptRuntimeState.lastError = detail
            ? String(detail.stack || detail.message || detail)
            : "";
          if (status === "stopped" || status === "idle") {
            this.scriptRuntimeState.height = 0;
          }
        },
        onLog: (entry) => {
          this.scriptRuntimeState.logs.push(entry);
          if (this.scriptRuntimeState.logs.length > 200) {
            this.scriptRuntimeState.logs.splice(
              0,
              this.scriptRuntimeState.logs.length - 200,
            );
          }
        },
        onToast: (message, duration) => {
          this.$store.global.showToast(message, Number(duration) || 3000);
        },
        onDataChange: (data) => {
          const script = this.getActiveScript();
          if (!script) return;
          script.data = data || {};
          this.scriptDataJson = JSON.stringify(script.data, null, 2);
        },
        onButtonsChange: (button) => {
          const script = this.getActiveScript();
          if (!script) return;
          script.button = {
            enabled: button?.enabled !== false,
            buttons: Array.isArray(button?.buttons) ? button.buttons : [],
          };
          this.scriptRuntimeState.buttonConfig = JSON.parse(
            JSON.stringify(script.button),
          );
        },
        onEvent: (eventName, detail) => {
          if (eventName === "__runtime_height__") {
            this.scriptRuntimeState.height = Number(detail?.height) || 0;
            return;
          }
          if (
            eventName === "__bridge_ready__" &&
            Array.isArray(detail?.capabilities)
          ) {
            this.scriptRuntimeState.bridgeCapabilities = detail.capabilities;
            return;
          }
          if (eventName === "button-clicked" && detail?.name) {
            this.$store.global.showToast(`按钮触发: ${detail.name}`, 1500);
          }
        },
      });
    },

    mountScriptRuntimeHost() {
      if (!this.scriptRuntime) return;
      if (!this.$refs.scriptRuntimeHost) return;
      this.scriptRuntime.attachHost(this.$refs.scriptRuntimeHost);
    },

    resetScriptRuntimeState() {
      this.scriptRuntimeState = {
        status: "idle",
        lastError: "",
        logs: [],
        buttonConfig: { enabled: true, buttons: [] },
        height: 0,
        bridgeCapabilities: [
          "toast",
          "fetch(text/json)",
          "get-host-state",
          "get-active-context/card/preset/chat",
          "list-runtimes",
          "open-detail",
          "refresh-list",
          "get-runtime-state",
          "reload-runtime",
          "stop-runtime",
        ],
      };
      this.activeRuntimeScriptId = null;
    },

    getActiveScript() {
      if (this.activeScriptIndex === -1) return null;
      const scripts = this.getTavernScripts();
      return scripts[this.activeScriptIndex] || null;
    },

    getFileTypeLabel() {
      return {
        regex: "正则脚本",
        script: "ST 脚本",
        quick_reply: "快速回复",
      }[this.fileType] || "独立扩展文件";
    },

    getActiveEntryLabel() {
      if (this.activeTab === "regex") {
        return this.editingData?.extensions?.regex_scripts?.[this.activeRegexIndex]
          ?.scriptName || "未命名正则脚本";
      }
      if (this.activeTab === "scripts") {
        return this.getActiveScript()?.name || "未命名 ST 脚本";
      }
      return this.editingData?.quick_reply?.qrList?.[this.activeQrIndex]?.label ||
        (this.activeQrIndex === -1 ? this.editingData?.quick_reply?.name : "未命名回复");
    },

    _setEditorFeedback(type, message, duration = 0) {
      this.editorFeedback = { type: type || "info", message: String(message || "") };
      if (this._editorFeedbackTimer) {
        clearTimeout(this._editorFeedbackTimer);
        this._editorFeedbackTimer = null;
      }
      if (duration > 0 && typeof setTimeout === "function") {
        this._editorFeedbackTimer = setTimeout(() => {
          this.editorFeedback = { type: "", message: "" };
          this._editorFeedbackTimer = null;
        }, duration);
      }
    },

    clearEditorFeedback() {
      if (this._editorFeedbackTimer) {
        clearTimeout(this._editorFeedbackTimer);
        this._editorFeedbackTimer = null;
      }
      this.editorFeedback = { type: "", message: "" };
    },

    handleGlobalKeydown(event) {
      if (!this.showAdvancedModal) return;

      if (event.key === "Escape") {
        event.preventDefault();
        if (this.showDeleteConfirm) {
          this.cancelDeleteConfirmation();
        } else {
          this.requestClose();
        }
        return;
      }

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (this.isFileMode) {
          this.saveFileChanges();
        } else if (this.showPersistButton) {
          this.persistChanges();
        } else {
          this._setEditorFeedback("info", "当前编辑会在点击完成后返回", 2600);
        }
      }
    },

    selectEditorEntry(kind, index) {
      if (kind === "regex") this.activeRegexIndex = index;
      if (kind === "script") this.activeScriptIndex = index;
      if (kind === "quick_reply") this.activeQrIndex = index;
      this.showMobileSidebar = false;
      this.$nextTick(() => {
        if (typeof document === "undefined") return;
        const entry = document.querySelector(
          `[data-advanced-entry="${kind}"][data-entry-index="${index}"]`,
        );
        entry?.focus();
      });
    },

    handleEntryKeydown(event, kind, index) {
      const lists = {
        regex: this.editingData?.extensions?.regex_scripts || [],
        script: this.getTavernScripts(),
        quick_reply: this.editingData?.quick_reply?.qrList || [],
      };
      const list = lists[kind] || [];
      if (!list.length) return;

      let nextIndex = index;
      if (event.key === "ArrowDown") nextIndex = Math.min(index + 1, list.length - 1);
      if (event.key === "ArrowUp") nextIndex = Math.max(index - 1, 0);
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = list.length - 1;
      if (nextIndex === index) return;

      event.preventDefault();
      this.selectEditorEntry(kind, nextIndex);
    },

    syncRuntimeContext() {
      const script = this.getActiveScript();
      if (!script || !this.scriptRuntime) {
        return;
      }

      this._normalizeScript(script);
      this.scriptRuntimeState.buttonConfig = JSON.parse(
        JSON.stringify(script.button || { enabled: true, buttons: [] }),
      );

      if (
        this.activeRuntimeScriptId &&
        this.activeRuntimeScriptId === script.id
      ) {
        this.scriptRuntime.updateContext(script);
      }
    },

    isRuntimeActiveForCurrentScript() {
      const script = this.getActiveScript();
      return !!(
        script &&
        this.activeRuntimeScriptId &&
        this.activeRuntimeScriptId === script.id
      );
    },

    handleRuntimeMetaInput() {
      this.syncRuntimeContext();
    },

    startScriptRuntime() {
      const script = this.getActiveScript();
      if (!script) return;

      try {
        this.syncScriptDataJson();
        this.mountScriptRuntimeHost();
        this.scriptRuntimeState.logs = [];
        this.scriptRuntimeState.lastError = "";
        this.activeRuntimeScriptId = script.id;
        this.scriptRuntime.run(script);
        this.scriptRuntimeState.buttonConfig = JSON.parse(
          JSON.stringify(script.button || { enabled: true, buttons: [] }),
        );
        this.$store.global.showToast(
          `已启动脚本运行时: ${script.name || "未命名脚本"}`,
          1800,
        );
      } catch (error) {
        console.error(error);
        this.scriptRuntimeState.status = "error";
        this.scriptRuntimeState.lastError =
          error?.stack || error?.message || String(error);
        this.$store.global.showToast(
          `脚本启动失败: ${error?.message || error}`,
          2500,
        );
      }
    },

    reloadScriptRuntime() {
      const script = this.getActiveScript();
      if (!script) return;

      if (
        !this.activeRuntimeScriptId ||
        this.activeRuntimeScriptId !== script.id
      ) {
        this.startScriptRuntime();
        return;
      }

      try {
        this.syncScriptDataJson();
        this.scriptRuntime.reload(script);
        this.$store.global.showToast(
          `已重载脚本: ${script.name || "未命名脚本"}`,
          1800,
        );
      } catch (error) {
        console.error(error);
        this.scriptRuntimeState.status = "error";
        this.scriptRuntimeState.lastError =
          error?.stack || error?.message || String(error);
        this.$store.global.showToast(
          `脚本重载失败: ${error?.message || error}`,
          2500,
        );
      }
    },

    stopScriptRuntime() {
      if (this.scriptRuntime) {
        this.scriptRuntime.stop();
      }
      this.resetScriptRuntimeState();
    },

    triggerRuntimeButton(name) {
      if (!name || !this.scriptRuntime || !this.activeRuntimeScriptId) return;
      this.scriptRuntime.triggerButton(name);
    },

    clearRuntimeLogs() {
      this.scriptRuntimeState.logs = [];
    },

    // 初始化/标准化 QR 数据
    _normalizeQrSet(data) {
      if (!data.name) data.name = "New Quick Reply Set";
      if (!Array.isArray(data.qrList)) {
        const sourceList = Array.isArray(data.quickReplies)
          ? data.quickReplies
          : Array.isArray(data.entries)
            ? data.entries
            : [];
        data.qrList = sourceList;
      }
      // 确保每个 QR 条目有必要字段
      data.qrList.forEach((qr) => {
        if (qr.id === undefined) qr.id = Math.floor(Math.random() * 1000000);
        if (qr.label === undefined) qr.label = qr.name || "New Reply";
        if (qr.message === undefined) qr.message = qr.content || "";
      });
      return data;
    },

    // 数据标准化辅助函数
    _normalizeScript(script) {
      if (!script) return;
      if (!script.button || typeof script.button !== "object") {
        script.button = { enabled: true, buttons: [] };
      }
      if (!Array.isArray(script.button.buttons)) script.button.buttons = [];

      // 兼容更老格式: 脚本顶层直接使用 buttons: []
      if (Array.isArray(script.buttons) && script.buttons.length > 0) {
        const normalized_buttons = script.buttons
          .filter((btn) => btn && typeof btn === "object")
          .map((btn) => ({
            name: btn.name || "新按钮",
            visible: btn.visible !== false,
          }));

        if (script.button.buttons.length === 0) {
          script.button.buttons = normalized_buttons;
        }
      }

      if (!script.data) script.data = {};
      if (script.enabled === undefined) script.enabled = true; // 默认启用
    },

    // === 通用工具 ===
    _downloadJson(data, filename) {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    _readJsonFile(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
          try {
            resolve(JSON.parse(e.target.result));
          } catch (err) {
            reject(err);
          }
        };
        reader.readAsText(file);
      });
    },

    // === Regex Import/Export ===
    exportRegex(index) {
      const script = this.editingData.extensions.regex_scripts[index];
      if (!script) return;
      const { id, ...data } = script;
      const name = script.scriptName || "untitled";
      this._downloadJson({ ...data, id: script.id }, `regex-${name}.json`);
    },

    async importRegex(e) {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const importedData = await this._readJsonFile(file);
        if (!isValidRegexData(importedData))
          throw new Error("无效的正则脚本格式");
        if (!this.editingData.extensions.regex_scripts)
          this.editingData.extensions.regex_scripts = [];
        const importedScripts = Array.isArray(importedData)
          ? importedData
          : [importedData];
        importedScripts.forEach((script) => {
          this.editingData.extensions.regex_scripts.push({
            ...script,
            id: crypto.randomUUID(),
          });
        });
        this.activeRegexIndex = this.editingData.extensions.regex_scripts.length - 1;
        this._setEditorFeedback("success", "正则脚本已导入", 3200);
        this.$store.global.showToast("导入成功", 3000, "check");
      } catch (err) {
        this._setEditorFeedback("error", "导入失败：" + err.message);
        this.$store.global.showToast("导入失败", 3600, "close");
      }
      e.target.value = "";
    },

    // === Tavern Script Import/Export ===
    exportScript(index) {
      const scripts = this.getTavernScripts();
      const script = scripts[index];
      if (!script) return;
      this.syncScriptDataJson();
      const name = script.name || "untitled";
      this._downloadJson(script, `酒馆助手脚本-${name}.json`);
    },

    async importScript(e) {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const importedData = await this._readJsonFile(file);
        if (!isValidScriptData(importedData) || importedData.type === "folder")
          throw new Error("无效的 ST 脚本格式");

        const data = importedData.type === "script" &&
          Object.prototype.hasOwnProperty.call(importedData, "value")
          ? { ...importedData.value }
          : { ...importedData };
        data.type = "script";
        data.id = crypto.randomUUID();

        // 导入时标准化
        this._normalizeScript(data);

        const helper = this.editingData.extensions.tavern_helper;
        let scriptBlock = null;

        // 兼容逻辑：查找或创建 scripts 数组
        if (Array.isArray(helper)) {
          scriptBlock = helper.find(
            (item) => Array.isArray(item) && item[0] === "scripts",
          );
          if (!scriptBlock) {
            scriptBlock = ["scripts", []];
            helper.push(scriptBlock);
          }
          scriptBlock[1].push(data);
          // 强制刷新
          this.editingData.extensions.tavern_helper = [...helper];
          this.activeScriptIndex = scriptBlock[1].length - 1;
        } else {
          // 字典结构
          if (!helper.scripts) helper.scripts = [];
          helper.scripts.push(data);
          this.activeScriptIndex = helper.scripts.length - 1;
        }

        this._setEditorFeedback("success", "ST 脚本已导入", 3200);
        this.$store.global.showToast("导入成功", 3000, "check");
        this.$nextTick(() => this.syncRuntimeContext());
      } catch (err) {
        this._setEditorFeedback("error", "导入失败：" + err.message);
        this.$store.global.showToast("导入失败", 3600, "close");
      }
      e.target.value = "";
    },

    // === Tavern Script Data Sync ===
    // 当 textarea 内容变化时，尝试解析 JSON 并回写到对象
    syncScriptDataJson() {
      if (this.activeScriptIndex === -1) return;
      const scripts = this.getTavernScripts();
      const script = scripts[this.activeScriptIndex];
      if (!script) return;
      try {
        const parsed = JSON.parse(this.scriptDataJson);
        script.data = parsed;
        this.scriptDataError = "";
        this.syncRuntimeContext();
      } catch (e) {
        this.scriptDataError = "JSON 格式无效，修正后才会同步到脚本数据。";
        console.warn("JSON Parse Error in Data field");
      }
    },

    formatScriptDataJson() {
      if (this.activeScriptIndex === -1) return;
      try {
        const parsed = JSON.parse(this.scriptDataJson || "{}");
        this.scriptDataJson = JSON.stringify(parsed, null, 2);
        this.syncScriptDataJson();
        if (!this.scriptDataError) {
          this._setEditorFeedback("success", "JSON 已格式化", 2200);
        }
      } catch (error) {
        this.scriptDataError = "JSON 格式无效，无法格式化。";
        this._setEditorFeedback("error", this.scriptDataError);
      }
    },

    // === Regex Script 管理 ===

    addRegexScript() {
      const newScript = {
        id: crypto.randomUUID(),
        scriptName: "新正则脚本",
        findRegex: "",
        replaceString: "",
        trimStrings: [],
        placement: [2],
        disabled: false,
        markdownOnly: false,
        promptOnly: false,
        runOnEdit: true,
        substituteRegex: 0,
        minDepth: null,
        maxDepth: null,
      };
      if (!this.editingData.extensions) this.editingData.extensions = {};
      if (!this.editingData.extensions.regex_scripts)
        this.editingData.extensions.regex_scripts = [];
      this.editingData.extensions.regex_scripts.push(newScript);
      this.activeRegexIndex =
        this.editingData.extensions.regex_scripts.length - 1;
    },

    removeRegexScript(index) {
      const script = this.editingData?.extensions?.regex_scripts?.[index];
      if (!script) return;
      this.openDeleteConfirmation("regex", {
        index,
        label: script.scriptName || "未命名正则脚本",
      });
    },

    moveRegex(index, dir) {
      const list = this.editingData.extensions.regex_scripts;
      const newIdx = index + dir;
      if (newIdx < 0 || newIdx >= list.length) return;
      const temp = list[index];
      list[index] = list[newIdx];
      list[newIdx] = temp;
      if (this.activeRegexIndex === index) this.activeRegexIndex = newIdx;
      else if (this.activeRegexIndex === newIdx) this.activeRegexIndex = index;
      this.editingData.extensions.regex_scripts = [...list];
    },

    // 处理 Placement (SillyTavern 使用整数枚举数组)
    toggleRegexPlacement(script, value) {
      const val = parseInt(value);
      if (!script.placement) script.placement = [];
      const idx = script.placement.indexOf(val);
      if (idx > -1) script.placement.splice(idx, 1);
      else script.placement.push(val);
    },

    // === 正则测试逻辑 ===

    runRegexTest() {
      const script =
        this.editingData.extensions.regex_scripts[this.activeRegexIndex];
      if (!script) return;
      if (!this.regexTestInput) {
        this.regexTestResult = "";
        this.regexTestResultIcon = "";
        return;
      }
      if (!script.findRegex) {
        this.regexTestResult = this.regexTestInput;
        this.regexTestResultIcon = "";
        return;
      }
      try {
        this.regexTestResultIcon = "";
        this.regexTestResult = runRegexTestBenchScript(
          script,
          this.regexTestInput,
        );
      } catch (e) {
        this.regexTestResultIcon = "close";
        this.regexTestResult = "正则表达式错误: " + e.message;
      }
    },

    // === Trim Strings 辅助 (Textarea <-> Array) ===

    updateTrimStrings(script, text) {
      // 按换行符分割，去除空行
      script.trimStrings = text.split("\n").filter((line) => line.length > 0);
    },

    getTrimStringsText(script) {
      if (Array.isArray(script.trimStrings)) {
        return script.trimStrings.join("\n");
      }
      return "";
    },

    // === Tavern Scripts (Post-History / Slash Commands) ===

    getTavernScripts() {
      const extensions = this.editingData?.extensions;
      if (!extensions || typeof extensions !== "object") return [];
      const helper = extensions.tavern_helper;
      const fallbackScripts = extractPresetTavernScripts(extensions);

      if (!Array.isArray(helper) && typeof helper === "object" && helper) {
        if (
          Array.isArray(helper.scripts) &&
          (helper.scripts.length > 0 || fallbackScripts.length === 0)
        ) {
          return helper.scripts;
        }
      }

      if (Array.isArray(helper)) {
        const scriptBlock = helper.find(
          (item) =>
            Array.isArray(item) && item.length >= 2 && item[0] === "scripts",
        );
        if (
          scriptBlock &&
          Array.isArray(scriptBlock[1]) &&
          (scriptBlock[1].length > 0 || fallbackScripts.length === 0)
        ) {
          return scriptBlock[1];
        }
      }

      // Normalize legacy aliases and direct script arrays before exposing them.
      this.editingData.extensions = normalizePresetExtensionsForEditor(
        extensions,
      );
      const normalizedHelper = this.editingData.extensions.tavern_helper;
      if (
        normalizedHelper &&
        typeof normalizedHelper === "object" &&
        !Array.isArray(normalizedHelper) &&
        Array.isArray(normalizedHelper.scripts)
      ) {
        return normalizedHelper.scripts;
      }
      return [];
    },

    addTavernScript() {
      const newScript = {
        name: "新脚本",
        type: "script",
        content: "// Write your JS code here\nconsole.log('Hello World');",
        info: "作者备注信息",
        enabled: false,
        id: crypto.randomUUID(),
        button: { enabled: true, buttons: [] },
        data: {},
      };

      // 确保 extensions 结构
      if (!this.editingData.extensions) this.editingData.extensions = {};
      let helper = this.editingData.extensions.tavern_helper;

      // 智能初始化
      if (!helper) {
        // 默认初始化为新版字典结构
        helper = {
          scripts: [],
          variables: {},
        };
        this.editingData.extensions.tavern_helper = helper;
      }

      let scriptsList = null;

      if (Array.isArray(helper)) {
        // 旧版兼容：保持数组结构
        let scriptBlock = helper.find(
          (item) => Array.isArray(item) && item[0] === "scripts",
        );
        if (!scriptBlock) {
          scriptBlock = ["scripts", []];
          helper.push(scriptBlock);
        }
        scriptsList = scriptBlock[1];
      } else {
        // 新版字典
        if (!helper.scripts) helper.scripts = [];
        scriptsList = helper.scripts;
      }

      scriptsList.push(newScript);
      this.activeScriptIndex = scriptsList.length - 1;
      this.$nextTick(() => this.syncRuntimeContext());
    },

    removeTavernScript(scriptId) {
      const list = this.getTavernScripts();
      const index = list.findIndex((s) => s.id === scriptId);
      if (index > -1) {
        const script = list[index];
        this.openDeleteConfirmation("script", {
          scriptId,
          label: script?.name || "未命名 ST 脚本",
        });
      }
    },

    moveTavernScript(scriptId, dir) {
      const list = this.getTavernScripts();
      const index = list.findIndex((s) => s.id === scriptId);
      if (index === -1) return;

      const newIdx = index + dir;
      if (newIdx < 0 || newIdx >= list.length) return;

      // 交换
      const temp = list[index];
      list[index] = list[newIdx];
      list[newIdx] = temp;

      // 同步选中索引
      if (this.activeScriptIndex === index) {
        this.activeScriptIndex = newIdx;
      } else if (this.activeScriptIndex === newIdx) {
        this.activeScriptIndex = index;
      }

      this.$nextTick(() => this.syncRuntimeContext());
    },

    // === 按钮管理 (New) ===

    addScriptButton(script) {
      this._normalizeScript(script);
      script.button.buttons.push({ name: "新按钮", visible: true });
      this.syncRuntimeContext();
    },

    removeScriptButton(script, btnIndex) {
      if (script.button && script.button.buttons) {
        script.button.buttons.splice(btnIndex, 1);
        this.syncRuntimeContext();
      }
    },

    // QR 管理方法
    addQrEntry() {
      if (!this.editingData.quick_reply) return;
      this.editingData.quick_reply.qrList.push({
        id: Math.floor(Math.random() * 1000000),
        label: "新回复",
        message: "",
        title: "",
        showLabel: false,
        preventAutoExecute: true,
        isHidden: false,
        executeOnStartup: false,
        executeOnUser: false,
        executeOnAi: false,
        executeOnChatChange: false,
        executeOnNewChat: false,
      });
      // 滚动到底部
      this.activeQrIndex = this.editingData.quick_reply.qrList.length - 1;
    },

    removeQrEntry(index) {
      const qr = this.editingData?.quick_reply?.qrList?.[index];
      if (!qr) return;
      this.openDeleteConfirmation("quick_reply", {
        index,
        label: qr.label || "未命名回复",
      });
    },

    openDeleteConfirmation(type, request) {
      this.deleteRequest = { type, ...(request || {}) };
      this.showDeleteConfirm = true;
      this.$nextTick(() => {
        if (typeof document === "undefined") return;
        document.querySelector(".advanced-delete-dialog [data-delete-cancel]")?.focus();
      });
    },

    cancelDeleteConfirmation() {
      this.showDeleteConfirm = false;
      this.deleteRequest = null;
    },

    confirmDelete() {
      const request = this.deleteRequest;
      if (!request) return;

      if (request.type === "regex") {
        const list = this.editingData?.extensions?.regex_scripts || [];
        if (list[request.index]) {
          list.splice(request.index, 1);
          this.activeRegexIndex = list.length
            ? Math.min(request.index, list.length - 1)
            : -1;
        }
      } else if (request.type === "script") {
        const list = this.getTavernScripts();
        const index = list.findIndex((script) => script.id === request.scriptId);
        if (index > -1) {
          if (this.activeRuntimeScriptId === request.scriptId) this.stopScriptRuntime();
          list.splice(index, 1);
          this.activeScriptIndex = list.length
            ? Math.min(index, list.length - 1)
            : -1;
        }
      } else if (request.type === "quick_reply") {
        const list = this.editingData?.quick_reply?.qrList || [];
        if (list[request.index]) {
          list.splice(request.index, 1);
          this.activeQrIndex = list.length
            ? Math.min(request.index, list.length - 1)
            : -1;
        }
      }

      this.cancelDeleteConfirmation();
      this._setEditorFeedback("success", `已删除：${request.label || "扩展条目"}`, 2600);
      this.$store?.global?.showToast?.("已删除扩展条目", 2600, "check");
    },

    moveQrEntry(index, dir) {
      const list = this.editingData.quick_reply.qrList;
      const newIdx = index + dir;
      if (newIdx < 0 || newIdx >= list.length) return;
      const temp = list[index];
      list[index] = list[newIdx];
      list[newIdx] = temp;
      // 保持选中
      if (this.activeQrIndex === index) this.activeQrIndex = newIdx;
    },

    // 保存独立文件的方法
    async saveFileChanges() {
      if (!this.isFileMode || !this.currentFilePath || this.isSavingFile) return;
      this.isSavingFile = true;
      let contentToSave = null;
      try {
        if (this.fileType === "regex") {
          contentToSave = this.editingData.extensions.regex_scripts[0];
        } else if (this.fileType === "script") {
          this.syncScriptDataJson();
          const scripts = this.getTavernScripts();
          contentToSave = scripts[0];
        } else if (this.fileType === "quick_reply") {
          contentToSave = this.editingData.quick_reply;
        }
        const module = await import("../api/resource.js");
        const res = await module.saveScriptFile({
          file_path: this.currentFilePath,
          content: contentToSave,
        });
        if (!res.success) throw new Error(res.msg || "写入文件失败");
        this._setEditorFeedback("success", "文件已保存到磁盘", 3200);
        this.$store?.global?.showToast?.("脚本文件已保存", 3000, "settings-save");
      } catch (e) {
        console.error(e);
        this._setEditorFeedback("error", "保存失败：" + e.message);
        this.$store?.global?.showToast?.("保存失败", 3600, "close");
      } finally {
        this.isSavingFile = false;
      }
    },

    applyChangesAndClose() {
      if (this.isFileMode) return;
      this.isPersistPending = false;
      window.dispatchEvent(
        new CustomEvent("advanced-editor-apply", { detail: this.editingData }),
      );
      this.showAdvancedModal = false;
    },

    persistChanges() {
      if (this.isFileMode || !this.showPersistButton) return;
      if (this.isPersistPending) {
        this._setEditorFeedback("info", "保存正在进行，请稍候", 2200);
        return;
      }
      this.isPersistPending = true;
      window.dispatchEvent(
        new CustomEvent("advanced-editor-persist", {
          detail: this.editingData,
        }),
      );
    },

    requestClose() {
      if (
        !this.isFileMode &&
        this.editorCommitMode === "buffered" &&
        this.showPersistButton &&
        this.isPersistPending
      ) {
        this._setEditorFeedback("info", "保存正在进行，请等待保存完成", 2400);
        return;
      }
      this.showAdvancedModal = false;
    },

    destroy() {
      this.clearEditorFeedback();
      this.stopScriptRuntime();
      if (this.scriptRuntime) {
        this.scriptRuntime.destroy();
        this.scriptRuntime = null;
      }
      if (this._runtimeManagerUnsubscribe) {
        this._runtimeManagerUnsubscribe();
        this._runtimeManagerUnsubscribe = null;
      }
      if (this._closeAdvancedEditorHandler) {
        window.removeEventListener(
          "advanced-editor-close",
          this._closeAdvancedEditorHandler,
        );
        this._closeAdvancedEditorHandler = null;
      }
    },
  };
}
