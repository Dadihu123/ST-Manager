/**
 * static/js/components/presetEditor.js
 * 预设全屏编辑器
 */

import { createAutoSaver } from "../utils/autoSave.js";
import { createSnapshot as apiCreateSnapshot } from "../api/system.js";
import {
  getPresetDetail,
  savePreset,
  savePresetExtensions as apiSavePresetExtensions,
  setDefaultPresetVersion,
} from "../api/presets.js";
import { estimateTokens, formatDate } from "../utils/format.js";
import {
  getPresetExtensionSummary,
  normalizePresetExtensionsForEditor,
  normalizePresetExtensionsForSave,
} from "../utils/extensionCompatibility.js";
import {
  buildPromptMarkerIcon,
  getPromptMarkerVisual as resolvePromptMarkerVisual,
} from "../utils/promptMarkerVisuals.js";
import {
  clearActiveRuntimeContext,
  setActiveRuntimeContext,
} from "../runtime/runtimeContext.js";

const PROMPT_ROLE_OPTIONS = [
  { value: "system", label: "系统" },
  { value: "user", label: "用户" },
  { value: "assistant", label: "AI助手" },
];

const PROMPT_TRIGGER_OPTIONS = [
  { value: "normal", label: "常规" },
  { value: "continue", label: "继续" },
  { value: "impersonate", label: "角色扮演" },
  { value: "swipe", label: "滑动" },
  { value: "regenerate", label: "重新生成" },
  { value: "quiet", label: "静默" },
];

const PROMPT_POSITION_OPTIONS = [
  { value: 0, label: "相对" },
  { value: 1, label: "聊天中" },
];

const PROMPT_ROLE_LABELS = Object.fromEntries(
  PROMPT_ROLE_OPTIONS.map((option) => [option.value, option.label]),
);

const VALID_PROMPT_ROLES = new Set(
  PROMPT_ROLE_OPTIONS.map((option) => option.value),
);
const VALID_PROMPT_TRIGGERS = new Set(
  PROMPT_TRIGGER_OPTIONS.map((option) => option.value),
);
const PROMPT_POSITION_LABELS = Object.fromEntries(
  PROMPT_POSITION_OPTIONS.map((option) => [option.value, option.label]),
);

const ST_DEFAULT_PROMPT_ORDER = [
  { identifier: "main", enabled: true },
  { identifier: "worldInfoBefore", enabled: true },
  { identifier: "personaDescription", enabled: true },
  { identifier: "charDescription", enabled: true },
  { identifier: "charPersonality", enabled: true },
  { identifier: "scenario", enabled: true },
  { identifier: "enhanceDefinitions", enabled: false },
  { identifier: "nsfw", enabled: true },
  { identifier: "worldInfoAfter", enabled: true },
  { identifier: "dialogueExamples", enabled: true },
  { identifier: "chatHistory", enabled: true },
  { identifier: "jailbreak", enabled: true },
];

const ST_DEFAULT_SYSTEM_PROMPTS = {
  main: {
    name: "Main Prompt",
    content:
      "Write {{char}}'s next reply in a fictional chat between {{charIfNotGroup}} and {{user}}.",
    forbid_overrides: false,
  },
  nsfw: {
    name: "Nsfw Prompt",
    content: "",
  },
  jailbreak: {
    name: "Jailbreak Prompt",
    content: "",
    forbid_overrides: false,
  },
  enhanceDefinitions: {
    name: "Enhance Definitions",
    content:
      "If you have more knowledge of {{char}}, add to the character's lore and personality to enhance them but keep the Character Sheet's definitions absolute.",
  },
};

const SECTION_LABELS = {
  basic: "基础信息",
  sampling: "采样参数",
  penalties: "惩罚参数",
  length_and_output: "长度与终止",
  dynamic_temperature: "动态温度",
  mirostat: "Mirostat",
  guidance: "引导与负面提示",
  formatting: "格式与运行开关",
  schema_and_grammar: "Schema / Grammar",
  bans_and_bias: "禁词与 Bias",
  sampler_ordering: "采样顺序",
  sequences: "输入输出序列",
  wrapping_and_behavior: "包装与行为",
  activation: "激活规则",
  compatibility: "兼容字段",
  story: "故事模板",
  separator_and_chat: "分隔与聊天",
  insertion_behavior: "插入行为",
  formatting_behavior: "格式行为",
  prompt: "提示词内容",
  placement: "插入位置",
  template: "模板字段",
  runtime_notes: "运行说明",
  extensions: "扩展配置",
  raw: "原始 JSON",
  snapshots: "快照历史",
};

const PROFILE_SOURCE_LABELS = {
  openai: "OpenAI",
  custom: "Custom",
  ai21: "AI21",
  aimlapi: "AIML API",
  azure_openai: "Azure OpenAI",
  chutes: "Chutes",
  claude: "Claude",
  workers_ai: "Workers AI",
  cohere: "Cohere",
  cometapi: "CometAPI",
  deepseek: "DeepSeek",
  electronhub: "ElectronHub",
  fireworks: "Fireworks",
  groq: "Groq",
  makersuite: "Google AI Studio",
  vertexai: "Vertex AI",
  mistralai: "Mistral",
  minimax: "MiniMax",
  moonshot: "Moonshot",
  nanogpt: "NanoGPT",
  openrouter: "OpenRouter",
  perplexity: "Perplexity",
  pollinations: "Pollinations",
  siliconflow: "SiliconFlow",
  xai: "xAI",
  zai: "Z.AI",
};

const PROFILE_OPTION_LABELS = {
  "": "自动",
  " ": "空格",
  "\n": "换行",
  "\n\n": "空两行",
  "-1": "不处理",
  "0": "默认",
  "1": "Completion Object",
  "2": "Message Content",
  auto: "自动",
  low: "低",
  medium: "中",
  high: "高",
  min: "最低",
  max: "最高",
  disabled: "禁用",
  since_last_user: "上个用户消息后",
  active_chain: "当前工具链",
  alphabetically: "按字母排序",
  "pricing.prompt": "输入价格",
  "pricing.completion": "输出价格",
  context_length: "上下文长度",
  express: "Express",
  full: "完整鉴权",
  global: "Global",
  cn: "中国节点",
  common: "通用",
  coding: "Coding",
  on: "开启",
  off: "关闭",
};

const LONG_TEXT_FIELDS = new Set([
  "content",
  "story_string",
  "example_separator",
  "chat_start",
  "prefix",
  "suffix",
  "separator",
  "negative_prompt",
  "json_schema",
  "grammar",
  "input_sequence",
  "output_sequence",
  "system_sequence",
  "first_output_sequence",
  "last_output_sequence",
  "stop_sequence",
  "activation_regex",
]);

function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

export default function presetEditor() {
  const autoSaver = createAutoSaver();
  return {
    showPresetEditor: false,
    isLoading: false,
    isSaving: false,
    hasConflict: false,
    conflictRevision: "",
    activeNav: "basic",
    activeWorkspace: "all",
    activeGroup: "all",
    activePromptId: "",
    promptAppendId: "",
    activeGenericItemId: "",
    activeItemId: "",
    activeMirroredFieldId: "",
    searchTerm: "",
    uiFilter: "all",
    showMobileSidebar: false,
    showMobilePromptDetailView: false,
    presetEditorMobileHeaderCompact: false,
    presetEditorLastScrollTop: 0,
    showMobileHeaderMoreMenu: false,
    showPromptTriggers: false,
    hasUnsavedChanges: false,
    dirtyPaths: {},
    editingPresetFile: null,
    editingData: null,
    baseDataJson: "",
    promptItemsCache: [],
    orderedPromptItemsCache: [],
    filteredItemsCache: [],
    genericWorkspaceItemsCache: [],
    activePromptItemCache: null,
    activeItemCache: null,
    cacheEditingDataRef: null,
    cacheEditorViewRef: null,
    cacheSearchTerm: "",
    cacheUiFilter: "all",
    cacheActiveGroup: "all",
    cacheActiveWorkspace: "all",
    cacheActivePromptId: "",
    cacheActiveItemId: "",
    cacheActiveGenericItemId: "",
    pendingLargeEditorSaveHandler: null,
    pendingAdvancedEditorApplyHandler: null,
    pendingAdvancedEditorPersistHandler: null,
    sectionLabels: SECTION_LABELS,
    promptRoleOptions: PROMPT_ROLE_OPTIONS,
    promptTriggerOptions: PROMPT_TRIGGER_OPTIONS,
    promptPositionOptions: PROMPT_POSITION_OPTIONS,
    formatDate,
    estimateTokens,

    init() {
      window.addEventListener("open-preset-editor", (e) => {
        this.openPresetEditor(e.detail || {});
      });

      window.addEventListener("preset-restore-applied", (e) => {
        const detail = e.detail || {};
        if (!this.showPresetEditor || !this.editingPresetFile) return;
        if (detail.id && detail.id !== this.editingPresetFile.id) return;
        this.reloadFromDisk();
      });

      window.addEventListener("settings-saved", () => {
        if (this.showPresetEditor) this.restartAutoSaver();
      });

      window.addEventListener("beforeunload", (event) => {
        if (!this.showPresetEditor || !this.isDirty) return;
        event.preventDefault();
        event.returnValue = "当前预设有未保存修改，确定离开吗？";
      });

      window.addEventListener("keydown", (event) => {
        if (!this.showPresetEditor) return;
        if (event.key === "Escape") {
          event.preventDefault();
          this.closeEditor();
          return;
        }
        if (
          (event.ctrlKey || event.metaKey) &&
          String(event.key || "").toLowerCase() === "s"
        ) {
          event.preventDefault();
          this.saveOverwrite();
        }
      });

      this.$watch("showPresetEditor", (visible) => {
        if (!visible) {
          autoSaver.stop();
          this.hasConflict = false;
          this.conflictRevision = "";
          clearActiveRuntimeContext("preset");
        }
      });

      this.$watch("searchTerm", () => this.refreshEditorCollections());
      this.$watch("uiFilter", () => this.refreshEditorCollections());
      this.$watch("$store.global.deviceType", (deviceType) => {
        this.resetMobileHeaderState();
        this.showMobileSidebar = false;
        this.showMobilePromptDetailView = false;
        this.updatePresetEditorLayoutMetrics();
      });
      this.$watch("$store.global.settingsForm.auto_save_enabled", () => {
        if (this.showPresetEditor) this.restartAutoSaver();
      });
      this.$watch("$store.global.settingsForm.auto_save_interval", () => {
        if (this.showPresetEditor) this.restartAutoSaver();
      });
    },

    get isDirty() {
      return Boolean(this.editingData && this.hasUnsavedChanges);
    },

    get presetTitle() {
      return (
        this.editingData?.name || this.editingPresetFile?.name || "未命名预设"
      );
    },

    updatePresetName(value) {
      if (!this.editingData) return;
      this.editingData.name = String(value ?? "");
      this.markDirtyWithoutRefresh("name");
    },

    get presetKind() {
      return this.editingPresetFile?.preset_kind || "";
    },

    get availableVersions() {
      return Array.isArray(this.editingPresetFile?.available_versions)
        ? this.editingPresetFile.available_versions
        : [];
    },

    get hasMultipleVersions() {
      return this.availableVersions.length > 1;
    },

    get autoSaveEnabled() {
      return Boolean(this.$store?.global?.settingsForm?.auto_save_enabled);
    },

    get autoSaveStatusLabel() {
      if (!this.autoSaveEnabled) return "自动快照未启用";
      const interval = Math.min(
        60,
        Math.max(
          1,
          Number(this.$store?.global?.settingsForm?.auto_save_interval) || 3,
        ),
      );
      return `自动快照 · ${interval} 分钟`;
    },

    buildReopenContext() {
      return {
        activeWorkspace: this.activeWorkspace,
        activeGroup: this.activeGroup,
        activePromptId: this.activePromptId,
        activeGenericItemId: this.activeGenericItemId,
        activeItemId: this.activeItemId,
      };
    },

    normalizeReopenContext(context = null) {
      return {
        activeWorkspace: context?.activeWorkspace || "all",
        activeGroup: context?.activeGroup || "all",
        activePromptId: context?.activePromptId || "",
        activeGenericItemId: context?.activeGenericItemId || "",
        activeItemId: context?.activeItemId || "",
      };
    },

    reopenPresetVersion(presetId) {
      const targetPresetId = String(presetId || "").trim();
      if (!targetPresetId) return Promise.resolve();
      return this.openPresetEditor({
        presetId: targetPresetId,
        activeNav: this.activeNav,
        preserveNav: true,
        preserveContext: true,
        context: this.buildReopenContext(),
      });
    },

    getMobileHeaderMetaLine() {
      const path =
        this.editingPresetFile?.path ||
        this.editingPresetFile?.file_path ||
        this.editingPresetFile?.name ||
        "未定位文件";
      return path;
    },

    getCompactHeaderStatusLabel() {
      if (this.hasConflict) return "存在冲突";
      if (this.isSaving) return "保存中";
      if (this.isDirty) return "未保存";
      return "已同步";
    },

    resetMobileHeaderState() {
      this.showMobileHeaderMoreMenu = false;
      this.presetEditorMobileHeaderCompact = false;
      this.presetEditorLastScrollTop = 0;
    },

    revealMobileHeader() {
      const changed =
        this.presetEditorMobileHeaderCompact ||
        this.presetEditorLastScrollTop !== 0;
      this.presetEditorMobileHeaderCompact = false;
      this.presetEditorLastScrollTop = 0;
      if (changed) {
        this.updatePresetEditorLayoutMetrics();
      }
    },

    toggleMobileHeaderMoreMenu() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = !this.showMobileHeaderMoreMenu;
      this.updatePresetEditorLayoutMetrics();
    },

    openMobileSidebar() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showMobileSidebar = true;
      this.updatePresetEditorLayoutMetrics();
    },

    closeMobileSidebar() {
      this.showMobileSidebar = false;
      this.showMobileHeaderMoreMenu = false;
      this.updatePresetEditorLayoutMetrics();
    },

    openMobilePromptDetailView() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobilePromptDetailView = true;
      this.updatePresetEditorLayoutMetrics();
    },

    closeMobilePromptDetailView() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobilePromptDetailView = false;
      this.updatePresetEditorLayoutMetrics();
    },

    updatePresetEditorLayoutMetrics() {
      if (typeof document === "undefined") return;
      const root = document.querySelector(".detail-preset-full-screen");
      if (!root?.style?.setProperty) return;
      const header = root.querySelector(".preset-editor-mobile-header");
      const height =
        typeof header?.offsetHeight === "number" ? header.offsetHeight : 0;
      root.style.setProperty("--preset-editor-header-height", `${height}px`);
    },

    syncPresetEditorMobileHeaderCompactState(container) {
      if (this.$store?.global?.deviceType !== "mobile") return;
      if (!container || typeof container.scrollTop !== "number") return;
      if (typeof Element !== "undefined" && !(container instanceof Element)) {
        return;
      }
      if (
        this.showMobileSidebar ||
        this.showMobileHeaderMoreMenu
      ) {
        return;
      }

      const scrollTop = Math.max(0, Number(container.scrollTop) || 0);
      const delta = scrollTop - this.presetEditorLastScrollTop;
      const previousCompact = this.presetEditorMobileHeaderCompact;

      if (scrollTop <= 24 || delta < -14) {
        this.presetEditorMobileHeaderCompact = false;
      } else if (delta > 18 && scrollTop > 72) {
        this.presetEditorMobileHeaderCompact = true;
      }

      this.presetEditorLastScrollTop = scrollTop;

      if (previousCompact !== this.presetEditorMobileHeaderCompact) {
        this.updatePresetEditorLayoutMetrics();
      }
    },

    handleMobileEditorContentScroll(event) {
      this.syncPresetEditorMobileHeaderCompactState(
        event?.target || event?.currentTarget || null,
      );
    },

    get editorView() {
      return (
        this.editingPresetFile?.reader_view || {
          family: "generic",
          family_label: "通用预设",
          groups: [],
          items: [],
          stats: {},
        }
      );
    },

    get isPromptWorkspaceEditor() {
      return this.editorView.family === "prompt_manager";
    },

    get scalarWorkspace() {
      return this.editorView.scalar_workspace || null;
    },

    get hasScalarWorkspace() {
      return Boolean(this.scalarWorkspace);
    },

    get isScalarWorkspaceEditor() {
      return Boolean(
        this.editingPresetFile?.preset_kind === "textgen" &&
        this.editorView.family === "prompt_manager" &&
        this.activeWorkspace === "scalar_fields" &&
        this.editorView.scalar_workspace,
      );
    },

    get scalarWorkspaceSections() {
      return Array.isArray(this.scalarWorkspace?.sections)
        ? this.scalarWorkspace.sections
        : [];
    },

    get editorProfile() {
      return this.editingPresetFile?.editor_profile || null;
    },

    get isMirroredProfileEditor() {
      return Boolean(
        this.editorProfile?.id && this.editorProfile?.family === "st_mirror",
      );
    },

    get mirroredProfileSections() {
      return Array.isArray(this.editorProfile?.sections)
        ? this.editorProfile.sections
        : [];
    },

    get workspaceSections() {
      if (Array.isArray(this.editorProfile?.workspace_sections)) {
        return this.editorProfile.workspace_sections;
      }
      if (Array.isArray(this.scalarWorkspace?.workspace_sections)) {
        return this.scalarWorkspace.workspace_sections;
      }
      return this.mirroredProfileSections;
    },

    get currentCompletionSource() {
      const source = this.getProfileFieldValue("chat_completion_source");
      return String(source || "openai");
    },

    get activeMirroredSection() {
      if (!this.isMirroredProfileEditor) return null;
      if (this.activeWorkspace === "prompts") {
        return (
          this.mirroredProfileSections.find(
            (section) => section.id === "prompt_manager",
          ) || null
        );
      }
      if (this.activeWorkspace === "all") {
        return {
          id: "all",
          label: "全部基础字段",
          description: "按 SillyTavern 的字段定义查看当前预设中的所有基础设置",
        };
      }
      return (
        this.mirroredProfileSections.find(
          (section) => section.id === this.activeWorkspace,
        ) ||
        this.workspaceSections.find(
          (section) => section.id === this.activeWorkspace,
        ) ||
        this.mirroredProfileSections[0] ||
        this.workspaceSections[0] ||
        null
      );
    },

    getFilteredProfileSectionFields(sectionId) {
      const term = String(this.searchTerm || "")
        .trim()
        .toLowerCase();
      const editableControls = new Set([
        "range_with_number",
        "number",
        "checkbox",
        "select",
        "textarea",
        "sortable_string_list",
        "string_list",
        "key_value_list",
        "raw_json",
      ]);

      return this.getProfileSectionFields(sectionId).filter((field) => {
        if (!this.isProfileFieldVisible(field)) {
          return false;
        }
        if (
          this.uiFilter === "editable" &&
          !editableControls.has(field?.control)
        ) {
          return false;
        }
        if (
          this.uiFilter === "changed" &&
          !this.isProfileFieldDirty(
            field?.storage_key || field?.canonical_key || field?.id,
          )
        ) {
          return false;
        }
        if (this.uiFilter === "longtext" && field?.control !== "textarea") {
          return false;
        }
        if (
          this.uiFilter === "collections" &&
          ![
            "sortable_string_list",
            "string_list",
            "key_value_list",
            "prompt_workspace",
          ].includes(field?.control)
        ) {
          return false;
        }
        if (!term) return true;

        const haystack = [
          field?.label,
          field?.description,
          field?.storage_key,
          field?.canonical_key,
          field?.id,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(term);
      });
    },

    getMirroredSectionFieldCount(sectionId) {
      return this.getFilteredProfileSectionFields(sectionId).length;
    },

    get mirroredWorkspaceFieldItems() {
      if (!this.activeMirroredSection) return [];
      if (this.activeMirroredSection.id === "prompt_manager") return [];
      return this.getFilteredProfileSectionFields(
        this.activeMirroredSection.id,
      );
    },

    get activeMirroredField() {
      const visibleFields = this.mirroredWorkspaceFieldItems;
      if (!visibleFields.length) return null;
      return (
        visibleFields.find(
          (field) => field.id === this.activeMirroredFieldId,
        ) ||
        visibleFields[0] ||
        null
      );
    },

    get promptItems() {
      this.ensureEditorCollections();
      return this.promptItemsCache;
    },

    normalizePromptOrder() {
      const promptOrder = this.editingData?.prompt_order;
      if (!Array.isArray(promptOrder)) return [];

      if (
        promptOrder.length &&
        promptOrder.every((entry) => typeof entry === "string")
      ) {
        return promptOrder
          .map((identifier, index) => ({
            identifier: String(identifier || "").trim(),
            enabled: null,
            order_index: index,
          }))
          .filter((entry) => entry.identifier);
      }

      if (
        promptOrder.length &&
        promptOrder.every(
          (entry) =>
            entry && typeof entry === "object" && "identifier" in entry,
        )
      ) {
        return promptOrder
          .map((entry, index) => ({
            identifier: String(entry.identifier || "").trim(),
            enabled: typeof entry.enabled === "boolean" ? entry.enabled : null,
            order_index: index,
          }))
          .filter((entry) => entry.identifier);
      }

      const nestedBucket = promptOrder.find(
        (entry) =>
          entry && typeof entry === "object" && Array.isArray(entry.order),
      );
      if (!nestedBucket) return [];

      return nestedBucket.order
        .map((entry, index) => ({
          identifier: String(entry?.identifier || "").trim(),
          enabled: typeof entry?.enabled === "boolean" ? entry.enabled : null,
          order_index: index,
        }))
        .filter((entry) => entry.identifier);
    },

    hasUnsupportedNestedPromptOrder() {
      const promptOrder = Array.isArray(this.editingData?.prompt_order)
        ? this.editingData.prompt_order
        : [];
      const nestedBucketCount = promptOrder.filter(
        (entry) =>
          entry && typeof entry === "object" && Array.isArray(entry.order),
      ).length;
      return nestedBucketCount > 1;
    },

    isPromptOrderMovable(prompt, direction) {
      if (!prompt || prompt.__is_orphan || this.hasUnsupportedNestedPromptOrder()) {
        return false;
      }
      const orderedPrompts = this.orderedPromptItems.filter(
        (entry) => !entry?.__is_orphan,
      );
      const currentIndex = orderedPrompts.findIndex(
        (entry) => entry.__identifier === prompt.__identifier,
      );
      if (currentIndex === -1) return false;
      return direction < 0
        ? currentIndex > 0
        : currentIndex < orderedPrompts.length - 1;
    },

    get orderedPromptItems() {
      this.ensureEditorCollections();
      return this.orderedPromptItemsCache;
    },

    get detachedPromptItems() {
      return this.orderedPromptItems.filter(
        (prompt) => prompt?.__is_orphan && prompt?.__raw_identifier,
      );
    },

    get activePromptItem() {
      this.ensureEditorCollections();
      return this.activePromptItemCache;
    },

    getPromptRoleValue(prompt) {
      const role = String(prompt?.role || "").trim();
      return VALID_PROMPT_ROLES.has(role) ? role : "system";
    },

    getPromptRoleLabel(role) {
      return PROMPT_ROLE_LABELS[this.getPromptRoleValue({ role })] || "系统";
    },

    normalizePromptPosition(value) {
      return Number(value) === 1 ? 1 : 0;
    },

    normalizePromptDepth(value) {
      const depth = Number(value);
      return Number.isInteger(depth) && depth >= 0 ? depth : 4;
    },

    isChatInjectionPosition(prompt) {
      return this.normalizePromptPosition(prompt?.injection_position) === 1;
    },

    getPromptPositionLabel(prompt) {
      if (!this.isChatInjectionPosition(prompt)) {
        return PROMPT_POSITION_LABELS[0] || "相对";
      }

      const normalizedDepth = this.normalizePromptDepth(
        prompt?.injection_depth,
      );
      return `${PROMPT_POSITION_LABELS[1] || "聊天中"} @ ${normalizedDepth}`;
    },

    get genericWorkspaceItems() {
      this.ensureEditorCollections();
      return this.genericWorkspaceItemsCache;
    },

    get filteredItems() {
      this.ensureEditorCollections();
      return this.filteredItemsCache;
    },

    get activeItem() {
      this.ensureEditorCollections();
      return this.activeItemCache;
    },

    get navSections() {
      const detailSections = this.editingPresetFile?.sections || {};
      const dynamic = Object.keys(detailSections);
      return ["basic", ...dynamic, "extensions", "raw", "snapshots"];
    },

    get visibleSections() {
      return this.editingPresetFile?.sections || {};
    },

    get rawJsonText() {
      if (!this.editingData) return "";
      try {
        return JSON.stringify(this.editingData, null, 2);
      } catch (error) {
        return "{}";
      }
    },

    get extensionSummary() {
      const summary = getPresetExtensionSummary(
        this.editingData?.extensions || {},
      );
      return {
        regexCount: summary.regex_count,
        scriptCount: summary.script_count,
      };
    },

    isItemDirty(item) {
      if (!item) return false;
      return [item.value_path, item.source_key, item.key, item.id].some(
        (dirtyKey) => Boolean(dirtyKey && this.dirtyPaths[dirtyKey]),
      );
    },

    markDirty(path = null) {
      if (path) {
        this.dirtyPaths[path] = true;
      }
      this.hasUnsavedChanges = true;
      this.refreshEditorCollections();
    },

    markDirtyWithoutRefresh(path = null) {
      if (path) {
        this.dirtyPaths[path] = true;
      }
      this.hasUnsavedChanges = true;
    },

    markClean() {
      this.baseDataJson = this.editingData
        ? JSON.stringify(this.editingData)
        : "";
      this.hasUnsavedChanges = false;
      this.dirtyPaths = {};
      this.refreshEditorCollections();
    },

    ensureEditorCollections() {
      const needsRefresh =
        this.cacheEditingDataRef !== this.editingData ||
        this.cacheEditorViewRef !== this.editorView ||
        this.cacheSearchTerm !== this.searchTerm ||
        this.cacheUiFilter !== this.uiFilter ||
        this.cacheActiveGroup !== this.activeGroup ||
        this.cacheActiveWorkspace !== this.activeWorkspace;
      if (needsRefresh) {
        this.refreshEditorCollections();
        return;
      }

      if (
        this.cacheActivePromptId !== this.activePromptId ||
        this.cacheActiveItemId !== this.activeItemId ||
        this.cacheActiveGenericItemId !== this.activeGenericItemId
      ) {
        this.syncActiveEditorSelections();
      }
    },

    markAllReaderItemsDirty() {
      (this.editorView.items || []).forEach((item) => {
        [item.value_path, item.source_key, item.key, item.id].forEach(
          (dirtyKey) => {
            if (dirtyKey) {
              this.dirtyPaths[dirtyKey] = true;
            }
          },
        );
      });
      this.hasUnsavedChanges = true;
      this.refreshEditorCollections();
    },

    refreshEditorCollections() {
      this.promptItemsCache = Array.isArray(this.editingData?.prompts)
        ? this.editingData.prompts
            .map((prompt, index) => {
              if (!prompt || typeof prompt !== "object") {
                return null;
              }
              return {
                ...prompt,
                __prompt_index: index,
              };
            })
            .filter(Boolean)
        : [];

      const promptEntries = this.promptItemsCache.map((prompt, index) => ({
        ...prompt,
        __prompt_index: Number(prompt.__prompt_index ?? index),
        __raw_identifier: String(prompt.identifier || "").trim(),
        __identifier:
          String(prompt.identifier || `prompt_${index + 1}`).trim() ||
          `prompt_${index + 1}`,
      }));
      const promptMap = new Map(
        promptEntries.map((prompt) => [prompt.__identifier, prompt]),
      );
      const ordered = this.normalizePromptOrder()
        .map((entry) => {
          const prompt = promptMap.get(entry.identifier);
          if (!prompt) return null;
          promptMap.delete(entry.identifier);
          return {
            ...prompt,
            __enabled:
              typeof entry.enabled === "boolean"
                ? entry.enabled
                : prompt.enabled !== false,
            __order_index: entry.order_index,
            __is_orphan: false,
          };
        })
        .filter(Boolean);
      const orphaned = [...promptMap.values()].map((prompt, index) => ({
        ...prompt,
        __enabled: prompt.enabled !== false,
        __order_index: ordered.length + index,
        __is_orphan: true,
      }));
      this.orderedPromptItemsCache = [...ordered, ...orphaned];

      const term = String(this.searchTerm || "")
        .trim()
        .toLowerCase();
      this.filteredItemsCache = (this.editorView.items || []).filter((item) => {
        if (this.isScalarWorkspaceEditor && item.group === "scalar_fields") {
          return false;
        }
        if (this.activeGroup !== "all" && item.group !== this.activeGroup) {
          return false;
        }
        if (this.uiFilter === "editable" && !item.editable) return false;
        if (this.uiFilter === "changed" && !this.isItemDirty(item)) {
          return false;
        }
        if (this.uiFilter === "longtext" && item.editor?.kind !== "textarea") {
          return false;
        }
        if (
          this.uiFilter === "collections" &&
          !["sortable-string-list", "string-list", "key-value-list"].includes(
            item.editor?.kind,
          )
        ) {
          return false;
        }
        if (!term) return true;

        const haystack = [
          item.title,
          item.summary,
          item.source_key,
          item.value_path,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(term);
      });

      if (!this.isPromptWorkspaceEditor) {
        this.genericWorkspaceItemsCache = this.filteredItemsCache;
      } else if (!this.activeWorkspace || this.activeWorkspace === "prompts") {
        this.genericWorkspaceItemsCache = [];
      } else if (this.isScalarWorkspaceEditor) {
        this.genericWorkspaceItemsCache = [];
      } else {
        this.genericWorkspaceItemsCache = (this.editorView.items || []).filter(
          (item) => item.group === this.activeWorkspace,
        );
      }

      this.cacheEditingDataRef = this.editingData;
      this.cacheEditorViewRef = this.editorView;
      this.cacheSearchTerm = this.searchTerm;
      this.cacheUiFilter = this.uiFilter;
      this.cacheActiveGroup = this.activeGroup;
      this.cacheActiveWorkspace = this.activeWorkspace;

      this.syncActiveEditorSelections();
      this.syncActiveMirroredField();
    },

    syncActiveEditorSelections() {
      const nextPrompt =
        this.orderedPromptItemsCache.find(
          (prompt) => prompt.__identifier === this.activePromptId,
        ) ||
        this.orderedPromptItemsCache[0] ||
        null;
      this.activePromptItemCache = nextPrompt;
      this.activePromptId = nextPrompt?.__identifier || "";

      const activeItemId =
        this.isPromptWorkspaceEditor && this.activeWorkspace !== "prompts"
          ? this.activeGenericItemId || this.activeItemId
          : this.activeItemId;
      const nextItem =
        this.filteredItemsCache.find((item) => item.id === activeItemId) ||
        this.filteredItemsCache[0] ||
        null;
      this.activeItemCache = nextItem;
      this.activeItemId = nextItem?.id || "";
      if (this.isPromptWorkspaceEditor && this.activeWorkspace !== "prompts") {
        this.activeGenericItemId = nextItem?.id || "";
      }
      this.cacheActivePromptId = this.activePromptId;
      this.cacheActiveItemId = this.activeItemId;
      this.cacheActiveGenericItemId = this.activeGenericItemId;
    },

    getPromptMarkerVisual(prompt) {
      const identifier = String(
        prompt?.identifier || prompt?.__identifier || "",
      ).trim();
      return resolvePromptMarkerVisual(identifier);
    },

    getPromptMarkerIcon(prompt) {
      const visual = this.getPromptMarkerVisual(prompt);
      return buildPromptMarkerIcon(visual);
    },

    syncCachedPromptUpdate(previousIdentifier, nextPrompt, promptIndex) {
      const currentIdentifier = String(nextPrompt?.identifier || "").trim();
      const nextIdentifier = currentIdentifier || previousIdentifier;

      this.promptItemsCache = this.promptItemsCache.map((prompt) =>
        Number(prompt?.__prompt_index) === promptIndex
          ? {
              ...prompt,
              ...nextPrompt,
              __prompt_index: promptIndex,
            }
          : prompt,
      );

      this.orderedPromptItemsCache = this.orderedPromptItemsCache.map(
        (prompt) => {
          if (Number(prompt?.__prompt_index) !== promptIndex) {
            return prompt;
          }
          return {
            ...prompt,
            ...nextPrompt,
            __prompt_index: promptIndex,
            __raw_identifier: currentIdentifier,
            __identifier: nextIdentifier,
          };
        },
      );

      if (Number(this.activePromptItemCache?.__prompt_index) === promptIndex) {
        this.activePromptItemCache = {
          ...this.activePromptItemCache,
          ...nextPrompt,
          __prompt_index: promptIndex,
          __raw_identifier: currentIdentifier,
          __identifier: nextIdentifier,
        };
      }

      if (
        this.activePromptId === previousIdentifier ||
        this.activePromptId === currentIdentifier
      ) {
        this.activePromptId = nextIdentifier;
      }
      this.cacheActivePromptId = this.activePromptId;
    },

    getByPath(path) {
      if (!path || !this.editingData) return undefined;
      const normalized = String(path).replace(/\[(\d+)\]/g, ".$1");
      return normalized
        .split(".")
        .filter(Boolean)
        .reduce((value, part) => {
          if (value === null || value === undefined) return undefined;
          return value[part];
        }, this.editingData);
    },

    setByPath(path, value) {
      if (!path || !this.editingData) return;
      const normalized = String(path).replace(/\[(\d+)\]/g, ".$1");
      const parts = normalized.split(".").filter(Boolean);
      if (!parts.length) return;

      let target = this.editingData;
      for (let index = 0; index < parts.length - 1; index += 1) {
        const part = parts[index];
        const nextPart = parts[index + 1];
        if (target[part] === null || typeof target[part] !== "object") {
          target[part] = /^\d+$/.test(nextPart) ? [] : {};
        }
        target = target[part];
      }

      target[parts[parts.length - 1]] = value;
      this.markDirty(path);
    },

    syncPromptOrder(nextOrderedPrompts = null) {
      if (!this.editingData) return;
      if (this.hasUnsupportedNestedPromptOrder()) return;

      const orderedPrompts = (Array.isArray(nextOrderedPrompts)
        ? nextOrderedPrompts
        : this.orderedPromptItems
      ).filter((prompt) => !prompt?.__is_orphan);
      const canPersistOrder = orderedPrompts.every((prompt) =>
        String(prompt?.__raw_identifier || "").trim(),
      );
      const currentPromptOrder = Array.isArray(this.editingData.prompt_order)
        ? this.editingData.prompt_order
        : [];

      if (!canPersistOrder) {
        if (
          Object.prototype.hasOwnProperty.call(this.editingData, "prompt_order")
        ) {
          delete this.editingData.prompt_order;
          this.markDirty("prompt_order");
        }
        return;
      }

      if (
        currentPromptOrder.some(
          (entry) =>
            entry && typeof entry === "object" && Array.isArray(entry.order),
        )
      ) {
        const nextBuckets = [...currentPromptOrder];
        const bucketIndex = nextBuckets.findIndex(
          (entry) =>
            entry && typeof entry === "object" && Array.isArray(entry.order),
        );
        if (bucketIndex !== -1) {
          const existingOrderEntries = new Map(
            (Array.isArray(nextBuckets[bucketIndex].order)
              ? nextBuckets[bucketIndex].order
              : []
            )
              .filter((entry) => entry && typeof entry === "object")
              .map((entry) => [String(entry.identifier || "").trim(), entry]),
          );
          nextBuckets[bucketIndex] = {
            ...nextBuckets[bucketIndex],
            order: orderedPrompts.map((prompt) => {
              const existing =
                existingOrderEntries.get(
                  prompt.__raw_identifier || prompt.__identifier,
                ) ||
                existingOrderEntries.get(prompt.__identifier) ||
                null;
              const nextEntry = {
                ...(existing || {}),
                identifier: prompt.__raw_identifier || prompt.__identifier,
              };
              if (
                existing &&
                Object.prototype.hasOwnProperty.call(existing, "enabled")
              ) {
                nextEntry.enabled = prompt.__enabled !== false;
              } else {
                delete nextEntry.enabled;
              }
              return nextEntry;
            }),
          };
          this.setByPath("prompt_order", nextBuckets);
          return;
        }
      }

      if (
        currentPromptOrder.length &&
        currentPromptOrder.every(
          (entry) =>
            entry && typeof entry === "object" && "identifier" in entry,
        )
      ) {
        const existingEntries = new Map(
          currentPromptOrder
            .filter((entry) => entry && typeof entry === "object")
            .map((entry) => [String(entry.identifier || "").trim(), entry]),
        );

        this.setByPath(
          "prompt_order",
          orderedPrompts.map((prompt) => {
            const existing =
              existingEntries.get(
                prompt.__raw_identifier || prompt.__identifier,
              ) ||
              existingEntries.get(prompt.__identifier) ||
              null;
            const nextEntry = {
              ...(existing || {}),
              identifier: prompt.__raw_identifier || prompt.__identifier,
            };
            if (
              existing &&
              Object.prototype.hasOwnProperty.call(existing, "enabled")
            ) {
              nextEntry.enabled = prompt.__enabled !== false;
            } else {
              delete nextEntry.enabled;
            }
            return nextEntry;
          }),
        );
        return;
      }

      this.setByPath(
        "prompt_order",
        orderedPrompts.map((prompt) => prompt.__identifier),
      );
    },

    getPromptArrayWithMeta() {
      return this.orderedPromptItems;
    },

    replacePromptOrder(nextOrderedPrompts) {
      if (!this.editingData || !Array.isArray(nextOrderedPrompts)) return;
      if (this.hasUnsupportedNestedPromptOrder()) return;

      const orderedEntries = nextOrderedPrompts.filter(
        (entry) => !entry?.__is_orphan,
      );
      const enriched = orderedEntries.map((entry) => ({
        ...entry,
        __enabled: entry.__enabled !== false,
      }));
      this.syncPromptOrder(enriched);
    },

    movePromptItem(fromIndex, toIndex) {
      const visiblePrompts = this.getPromptArrayWithMeta();
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= visiblePrompts.length ||
        toIndex >= visiblePrompts.length ||
        fromIndex === toIndex
      ) {
        return;
      }

      const sourcePrompt = visiblePrompts[fromIndex];
      const targetPrompt = visiblePrompts[toIndex];
      if (
        !sourcePrompt ||
        !targetPrompt ||
        sourcePrompt.__is_orphan ||
        targetPrompt.__is_orphan
      ) {
        return;
      }

      const orderedPrompts = visiblePrompts.filter(
        (prompt) => !prompt?.__is_orphan,
      );
      const orderedFromIndex = orderedPrompts.findIndex(
        (prompt) => prompt.__identifier === sourcePrompt.__identifier,
      );
      const orderedToIndex = orderedPrompts.findIndex(
        (prompt) => prompt.__identifier === targetPrompt.__identifier,
      );
      if (orderedFromIndex === -1 || orderedToIndex === -1) return;

      const [prompt] = orderedPrompts.splice(orderedFromIndex, 1);
      orderedPrompts.splice(orderedToIndex, 0, prompt);
      this.replacePromptOrder(orderedPrompts);
      this.activePromptId = prompt?.__identifier || this.activePromptId;
    },

    getPromptIdentifier(prompt) {
      return String(prompt?.identifier || prompt?.__identifier || "").trim();
    },

    isPromptEditAllowed(prompt) {
      const identifier = this.getPromptIdentifier(prompt);
      const sourcePrompts = new Set([
        "charDescription",
        "charPersonality",
        "scenario",
        "personaDescription",
        "worldInfoBefore",
        "worldInfoAfter",
      ]);
      return sourcePrompts.has(identifier) || !prompt?.marker;
    },

    isPromptToggleAllowed(prompt) {
      const identifier = this.getPromptIdentifier(prompt);
      if (prompt?.__is_orphan) return false;
      const forcedTogglePrompts = new Set([
        "charDescription",
        "charPersonality",
        "scenario",
        "personaDescription",
        "worldInfoBefore",
        "worldInfoAfter",
        "main",
        "chatHistory",
        "dialogueExamples",
      ]);
      return !prompt?.marker || forcedTogglePrompts.has(identifier);
    },

    isPromptDeleteAllowed(prompt) {
      return Boolean(prompt && prompt.system_prompt === false);
    },

    isPromptOverrideControlVisible(prompt) {
      const identifier = this.getPromptIdentifier(prompt);
      return identifier === "main" || identifier === "jailbreak";
    },

    isSystemPromptResettable(prompt) {
      const identifier = this.getPromptIdentifier(prompt);
      return Boolean(prompt?.system_prompt === true && ST_DEFAULT_SYSTEM_PROMPTS[identifier]);
    },

    resetSystemPrompt() {
      const active = this.activePromptItem;
      const identifier = this.getPromptIdentifier(active);
      const defaults = ST_DEFAULT_SYSTEM_PROMPTS[identifier];
      if (!active || !defaults || !this.editingData) return;

      const promptIndex = Number(active.__prompt_index);
      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      if (
        !Number.isInteger(promptIndex) ||
        promptIndex < 0 ||
        !prompts[promptIndex] ||
        prompts[promptIndex].system_prompt !== true
      ) {
        return;
      }

      prompts[promptIndex] = {
        ...prompts[promptIndex],
        name: defaults.name,
        content: defaults.content,
      };
      if (Object.prototype.hasOwnProperty.call(defaults, "forbid_overrides")) {
        prompts[promptIndex].forbid_overrides = defaults.forbid_overrides;
      }
      this.setByPath("prompts", prompts);
    },

    togglePromptEnabled(identifier) {
      const promptId = String(identifier || "");
      if (!promptId || !this.editingData) return;
      if (this.hasUnsupportedNestedPromptOrder()) return;

      const targetPrompt = this.orderedPromptItems.find(
        (prompt) => prompt.__identifier === promptId,
      );
      if (!this.isPromptToggleAllowed(targetPrompt)) return;

      const orderedPrompts = this.orderedPromptItems.map((prompt) => {
        if (prompt.__identifier !== promptId) {
          return prompt;
        }
        return {
          ...prompt,
          __enabled: prompt.__enabled === false,
        };
      });

      if (
        Array.isArray(this.editingData.prompt_order) &&
        this.editingData.prompt_order.some(
          (entry) =>
            entry && typeof entry === "object" && Array.isArray(entry.order),
        )
      ) {
        this.syncPromptOrder(orderedPrompts);
        return;
      }

      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      const activeEntry = orderedPrompts.find(
        (entry) => entry.__identifier === promptId,
      );
      const promptIndex = Number(activeEntry?.__prompt_index);
      if (promptIndex !== -1) {
        prompts[promptIndex] = {
          ...prompts[promptIndex],
          enabled: activeEntry?.__enabled !== false,
        };
        this.setByPath("prompts", prompts);
      }

      this.syncPromptOrder(orderedPrompts);
    },

    createPrompt() {
      if (!this.editingData) return;
      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      const identifier = `prompt_${Date.now()}_${Math.random()
        .toString(16)
        .slice(2, 8)}`;
      prompts.push({
        identifier,
        name: "",
        role: "system",
        content: "",
        system_prompt: false,
        enabled: false,
        marker: false,
        injection_position: 0,
        injection_order: 100,
        injection_trigger: [],
      });
      this.setByPath("prompts", prompts);
      this.activePromptId = identifier;
      this.refreshEditorCollections();
    },

    deleteActivePrompt() {
      const active = this.activePromptItem;
      if (!active || !this.isPromptDeleteAllowed(active) || !this.editingData) {
        return;
      }
      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      const promptIndex = Number(active.__prompt_index);
      if (!Number.isInteger(promptIndex) || promptIndex < 0) return;
      const hadPromptOrder = Array.isArray(this.editingData.prompt_order);
      prompts.splice(promptIndex, 1);
      this.setByPath("prompts", prompts);
      this.activePromptId = "";
      this.refreshEditorCollections();
      if (hadPromptOrder) this.syncPromptOrder(this.orderedPromptItems);
    },

    getPromptOrderShape() {
      const promptOrder = Array.isArray(this.editingData?.prompt_order)
        ? this.editingData.prompt_order
        : [];
      const bucketIndex = promptOrder.findIndex(
        (entry) =>
          entry && typeof entry === "object" && Array.isArray(entry.order),
      );
      if (bucketIndex !== -1) {
        return {
          mode: "nested",
          bucketIndex,
          entries: promptOrder[bucketIndex].order,
        };
      }
      if (
        promptOrder.length &&
        promptOrder.every((entry) => typeof entry === "string")
      ) {
        return { mode: "strings", bucketIndex: -1, entries: promptOrder };
      }
      if (
        promptOrder.length &&
        promptOrder.every(
          (entry) =>
            entry && typeof entry === "object" && "identifier" in entry,
        )
      ) {
        return { mode: "objects", bucketIndex: -1, entries: promptOrder };
      }
      return { mode: "objects", bucketIndex: -1, entries: [] };
    },

    updatePromptOrderMembership(identifier, include) {
      if (!this.editingData || this.hasUnsupportedNestedPromptOrder()) return;
      const promptId = String(identifier || "").trim();
      if (!promptId) return;

      const currentOrder = Array.isArray(this.editingData.prompt_order)
        ? deepClone(this.editingData.prompt_order)
        : [];
      const shape = this.getPromptOrderShape();
      const getIdentifier = (entry) =>
        typeof entry === "string"
          ? entry
          : String(entry?.identifier || "").trim();
      const entries = Array.isArray(shape.entries) ? [...shape.entries] : [];
      const existingIndex = entries.findIndex(
        (entry) => getIdentifier(entry) === promptId,
      );

      if (include) {
        if (existingIndex !== -1) return;
        entries.unshift(
          shape.mode === "strings"
            ? promptId
            : { identifier: promptId, enabled: false },
        );
      } else {
        if (existingIndex === -1) return;
        entries.splice(existingIndex, 1);
      }

      if (shape.mode === "nested") {
        if (!currentOrder[shape.bucketIndex]) return;
        currentOrder[shape.bucketIndex] = {
          ...currentOrder[shape.bucketIndex],
          order: entries,
        };
        this.setByPath("prompt_order", currentOrder);
      } else {
        this.setByPath("prompt_order", entries);
      }
      this.promptAppendId = "";
      this.refreshEditorCollections();
    },

    appendPromptToOrder(identifier = this.promptAppendId) {
      const promptId = String(identifier || "").trim();
      const prompt = this.promptItems.find(
        (entry) => this.getPromptIdentifier(entry) === promptId,
      );
      if (!prompt) return;
      this.updatePromptOrderMembership(promptId, true);
    },

    detachActivePrompt() {
      const active = this.activePromptItem;
      const promptId = String(active?.__raw_identifier || "").trim();
      if (!promptId) return;
      this.updatePromptOrderMembership(promptId, false);
    },

    resetPromptOrder() {
      if (!this.editingData || this.hasUnsupportedNestedPromptOrder()) return;
      if (
        !confirm(
          "这会恢复 SillyTavern 的默认提示词顺序，不会删除提示词正文。继续吗？",
        )
      ) {
        return;
      }

      const currentOrder = Array.isArray(this.editingData.prompt_order)
        ? deepClone(this.editingData.prompt_order)
        : [];
      const shape = this.getPromptOrderShape();
      const defaultEntries =
        shape.mode === "strings"
          ? ST_DEFAULT_PROMPT_ORDER.map((entry) => entry.identifier)
          : deepClone(ST_DEFAULT_PROMPT_ORDER);

      if (shape.mode === "nested" && currentOrder[shape.bucketIndex]) {
        currentOrder[shape.bucketIndex] = {
          ...currentOrder[shape.bucketIndex],
          order: defaultEntries,
        };
        this.setByPath("prompt_order", currentOrder);
      } else {
        this.setByPath("prompt_order", defaultEntries);
      }
      this.promptAppendId = "";
      this.refreshEditorCollections();
    },

    exportPrompts() {
      if (!this.editingData) return;
      const prompts = (Array.isArray(this.editingData.prompts)
        ? this.editingData.prompts
        : []
      )
        .filter(
          (prompt) =>
            prompt &&
            typeof prompt === "object" &&
            prompt.system_prompt === false &&
            prompt.marker === false,
        )
        .map((prompt) => deepClone(prompt));
      const promptOrder = deepClone(this.getPromptOrderShape().entries || []);
      const payload = {
        version: 1,
        type: "full",
        data: {
          prompts,
          prompt_order: promptOrder,
        },
      };

      const safeTitle = String(this.presetTitle || "st-prompts")
        .replace(/[\\/:*?"<>|]+/g, "-")
        .slice(0, 80);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeTitle || "st-prompts"}-prompts.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      this.$store?.global?.showToast?.("提示词已导出");
    },

    importPrompts() {
      if (!this.editingData) return;
      if (!confirm("同 ID 的现有提示词会被导入内容覆盖。继续吗？")) return;

      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json,application/json";
      input.addEventListener("change", (event) => {
        const file = event.target?.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
          try {
            const parsed = JSON.parse(String(reader.result || ""));
            const imported = parsed?.data;
            if (!imported || !Array.isArray(imported.prompts)) {
              throw new Error("提示词文件结构无效");
            }

            const merged = new Map();
            (Array.isArray(this.editingData.prompts)
              ? this.editingData.prompts
              : []
            ).forEach((prompt) => {
              const identifier = String(prompt?.identifier || "").trim();
              if (identifier) merged.set(identifier, prompt);
            });
            imported.prompts.forEach((prompt) => {
              const identifier = String(prompt?.identifier || "").trim();
              if (identifier) merged.set(identifier, deepClone(prompt));
            });

            this.editingData.prompts = Array.from(merged.values());
            this.markDirty("prompts");
            if (Array.isArray(imported.prompt_order)) {
              const currentOrder = Array.isArray(this.editingData.prompt_order)
                ? deepClone(this.editingData.prompt_order)
                : [];
              const shape = this.getPromptOrderShape();
              if (shape.mode === "nested" && currentOrder[shape.bucketIndex]) {
                currentOrder[shape.bucketIndex] = {
                  ...currentOrder[shape.bucketIndex],
                  order: deepClone(imported.prompt_order),
                };
                this.editingData.prompt_order = currentOrder;
              } else {
                this.editingData.prompt_order = deepClone(imported.prompt_order);
              }
              this.markDirty("prompt_order");
            }
            this.activePromptId =
              String(imported.prompts[0]?.identifier || "").trim() ||
              this.activePromptId;
            this.promptAppendId = "";
            this.refreshEditorCollections();
            this.$store?.global?.showToast?.("提示词已导入并合并");
          } catch (error) {
            console.error(error);
            this.$store?.global?.showToast?.("导入提示词失败", "error");
          }
        };
        reader.onerror = () => {
          this.$store?.global?.showToast?.("读取提示词文件失败", "error");
        };
        reader.readAsText(file);
      });
      document.body.appendChild(input);
      input.click();
      window.setTimeout(() => input.remove(), 0);
    },

    updatePromptField(key, value) {
      const active = this.activePromptItem;
      if (!active || !this.editingData) return;

      const previousIdentifier = active.__identifier;
      const promptIndex = Number(active.__prompt_index);
      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      if (!prompts[promptIndex] || typeof prompts[promptIndex] !== "object") {
        return;
      }
      if (!this.isPromptEditAllowed(prompts[promptIndex])) {
        return;
      }
      if (key === "content" && !this.isPromptContentEditable(prompts[promptIndex])) {
        return;
      }

      const nextPrompt = {
        ...prompts[promptIndex],
        [key]: value,
      };
      if (key === "injection_position") {
        nextPrompt[key] = this.normalizePromptPosition(value);
      }
      if (key === "injection_depth") {
        nextPrompt[key] = this.normalizePromptDepth(value);
      }
      if (key === "injection_order") {
        nextPrompt[key] = Number(value);
      }
      if (key === "role") {
        nextPrompt[key] = this.getPromptRoleValue({ role: value });
      }

      prompts[promptIndex] = nextPrompt;

      if (key === "content") {
        this.editingData.prompts = prompts;
        this.syncCachedPromptUpdate(
          previousIdentifier,
          nextPrompt,
          promptIndex,
        );
        this.markDirtyWithoutRefresh(`prompts.${promptIndex}.content`);
        return;
      }

      this.setByPath("prompts", prompts);

      if (key === "identifier") {
        const nextIdentifier = String(nextPrompt.identifier || "").trim();
        this.activePromptId = nextIdentifier || this.activePromptId;

        if (Array.isArray(this.editingData.prompt_order)) {
          const nextPromptOrder = this.editingData.prompt_order.map((entry) => {
            if (typeof entry === "string") {
              return entry === previousIdentifier ? nextIdentifier : entry;
            }
            if (entry && typeof entry === "object" && "identifier" in entry) {
              if (
                String(entry.identifier || "").trim() === previousIdentifier
              ) {
                return {
                  ...entry,
                  identifier: nextIdentifier,
                };
              }
              return entry;
            }
            if (
              entry &&
              typeof entry === "object" &&
              Array.isArray(entry.order)
            ) {
              return {
                ...entry,
                order: entry.order.map((orderEntry) => {
                  if (
                    orderEntry &&
                    typeof orderEntry === "object" &&
                    String(orderEntry.identifier || "").trim() ===
                      previousIdentifier
                  ) {
                    return {
                      ...orderEntry,
                      identifier: nextIdentifier,
                    };
                  }
                  return orderEntry;
                }),
              };
            }
            return entry;
          });
          this.setByPath("prompt_order", nextPromptOrder);
        }
      }
    },

    updatePromptTriggers(selectedValues) {
      const active = this.activePromptItem;
      if (!active || !this.editingData) return;
      if (!this.isPromptEditAllowed(active)) return;

      const promptIndex = Number(active.__prompt_index);
      const prompts = Array.isArray(this.editingData.prompts)
        ? [...this.editingData.prompts]
        : [];
      if (!prompts[promptIndex] || typeof prompts[promptIndex] !== "object") {
        return;
      }

      prompts[promptIndex] = {
        ...prompts[promptIndex],
        injection_trigger: Array.from(selectedValues || [])
          .map((entry) => String(entry || "").trim())
          .filter((entry) => VALID_PROMPT_TRIGGERS.has(entry)),
      };
      this.setByPath("prompts", prompts);
    },

    isPromptContentEditable(prompt) {
      return Boolean(prompt && this.isPromptEditAllowed(prompt) && !prompt.marker);
    },

    selectGroup(groupId) {
      this.revealMobileHeader();
      if (this.$store?.global?.deviceType === "mobile") {
        this.closeMobileSidebar();
      }
      const previousItemId = this.activeItemId;
      this.activeGroup = groupId || "all";
      this.refreshEditorCollections();
      const matchingItem = this.filteredItems.find(
        (item) => item.id === previousItemId,
      );
      if (matchingItem) {
        this.activeItemId = matchingItem.id;
        this.activeGenericItemId = matchingItem.id;
        this.syncActiveEditorSelections();
        return;
      }

      const first = this.filteredItems[0];
      if (first) {
        this.activeItemId = first.id;
        this.activeGenericItemId = first.id;
      }
      this.syncActiveEditorSelections();
    },

    selectWorkspace(workspaceId) {
      this.revealMobileHeader();
      if (this.$store?.global?.deviceType === "mobile") {
        this.closeMobileSidebar();
      }
      this.activeWorkspace =
        workspaceId || (this.isPromptWorkspaceEditor ? "prompts" : "all");
      if (!this.isPromptWorkspaceEditor) {
        this.selectGroup(this.activeWorkspace);
        this.syncActiveMirroredField();
        return;
      }

      if (this.activeWorkspace === "prompts") {
        this.activeMirroredFieldId = "";
        this.refreshEditorCollections();
        return;
      }

      this.showMobilePromptDetailView = false;
      this.activeGroup = this.activeWorkspace;
      this.refreshEditorCollections();
      this.syncActiveMirroredField();
    },

    getAutoSavePayload() {
      if (!this.editingPresetFile || !this.editingData) return null;
      return {
        id: this.editingPresetFile.id,
        type: "preset",
        file_path:
          this.editingPresetFile.file_path || this.editingPresetFile.path || "",
        content: this.editingData,
      };
    },

    restartAutoSaver() {
      autoSaver.stop();
      if (!this.showPresetEditor || !this.editingData) return;
      autoSaver.initBaseline(this.editingData);
      autoSaver.start(
        () => this.editingData,
        () => this.getAutoSavePayload(),
      );
    },

    openSnapshotSettings() {
      if (this.$store?.global) {
        this.$store.global.showSettingsModal = true;
      }
      window.dispatchEvent(
        new CustomEvent("open-settings-section", {
          detail: { section: "maintenance" },
        }),
      );
      this.showMobileHeaderMoreMenu = false;
    },

    selectItem(itemId) {
      this.revealMobileHeader();
      this.activeItemId = itemId || "";
      this.activeGenericItemId = itemId || "";
      this.syncActiveEditorSelections();
    },

    selectPrompt(promptId) {
      this.revealMobileHeader();
      this.activeWorkspace = "prompts";
      this.activePromptId = String(promptId || "");
      this.showPromptTriggers = false;
      this.refreshEditorCollections();
      if (this.$store?.global?.deviceType === "mobile") {
        this.openMobilePromptDetailView();
      }
    },

    getFieldValue(item) {
      if (!item) return null;
      if (item.value_path) {
        return this.getByPath(item.value_path);
      }
      return this.editingData?.[item.key];
    },

    getScalarWorkspaceFieldValue(fieldKey) {
      const meta = this.scalarWorkspace?.field_map?.[fieldKey];
      const storageKey = meta?.storage_key || fieldKey;
      return this.getByPath(storageKey);
    },

    setScalarWorkspaceFieldValue(fieldKey, value) {
      if (!this.editingData) return;
      const meta = this.scalarWorkspace?.field_map?.[fieldKey];
      this.setByPath(meta?.storage_key || fieldKey, value);
    },

    getScalarWorkspaceSectionEntries(sectionId) {
      const hiddenFields = new Set(this.scalarWorkspace?.hidden_fields || []);
      return Object.entries(this.scalarWorkspace?.field_map || {})
        .filter(([fieldKey]) => !hiddenFields.has(fieldKey))
        .filter(
          ([, meta]) =>
            meta?.section === sectionId ||
            meta?.workspace_section === sectionId,
        )
        .map(([fieldKey, meta]) => ({
          fieldKey,
          storage_key: meta?.storage_key || fieldKey,
          canonical_key: meta?.canonical_key || fieldKey,
          ...meta,
        }))
        .filter((field) => this.isProfileFieldVisible(field));
    },

    getProfileField(fieldKey) {
      const fields = Object.values(this.editorProfile?.fields || {});
      return (
        fields.find(
          (field) =>
            field?.canonical_key === fieldKey ||
            field?.storage_key === fieldKey ||
            field?.id === fieldKey,
        ) || null
      );
    },

    getProfileSectionFields(sectionId) {
      if (sectionId === "all") {
        return Object.values(this.editorProfile?.fields || {}).filter(
          (field) =>
            field?.control !== "prompt_workspace" &&
            field?.canonical_key !== "extensions",
        );
      }
      return Object.values(this.editorProfile?.fields || {}).filter(
        (field) =>
          field.section === sectionId || field.workspace_section === sectionId,
      ).filter(
        (field) =>
          field?.control !== "prompt_workspace" &&
          field?.canonical_key !== "extensions",
      );
    },

    getProfileFieldRawValue(fieldKey) {
      if (!fieldKey) return undefined;
      const field = this.getProfileField(fieldKey);
      const storageKey = field?.storage_key || field?.canonical_key || fieldKey;
      const value = this.getByPath(storageKey);
      if (value !== undefined) return value;
      return this.editingData?.[fieldKey];
    },

    matchesProfileCondition(condition) {
      if (!condition || typeof condition !== "object") return true;
      const value = this.getProfileFieldRawValue(condition.field);
      const normalizedValue =
        condition.field === "chat_completion_source" &&
        (value === undefined || value === null || value === "")
          ? "openai"
          : value;
      if (Array.isArray(condition.in)) {
        return condition.in.some(
          (candidate) => String(candidate) === String(normalizedValue),
        );
      }
      if (Object.prototype.hasOwnProperty.call(condition, "equals")) {
        return normalizedValue === condition.equals;
      }
      if (condition.truthy === true) return Boolean(normalizedValue);
      if (condition.truthy === false) return !normalizedValue;
      return true;
    },

    isProfileFieldVisible(field) {
      if (!field) return false;
      if (!this.matchesProfileCondition(field.visible_when)) return false;
      const dependencies = Array.isArray(field.depends_on)
        ? field.depends_on
        : field.depends_on
          ? [field.depends_on]
          : [];
      return dependencies.every((condition) =>
        this.matchesProfileCondition(condition),
      );
    },

    getProfileFieldOptionLabel(field, value) {
      const key = String(value ?? "");
      if (field?.id === "chat_completion_source") {
        return PROFILE_SOURCE_LABELS[key] || key;
      }
      return PROFILE_OPTION_LABELS[key] || key || "自动";
    },

    getProfileFieldDisplayValue(fieldKey) {
      const field = this.getProfileField(fieldKey);
      const value = this.getProfileFieldValue(fieldKey);
      if (
        field?.sensitive &&
        value !== null &&
        value !== undefined &&
        value !== ""
      ) {
        return "已设置";
      }
      if (field?.control === "checkbox") return value ? "开启" : "关闭";
      if (field?.control === "select") {
        return this.getProfileFieldOptionLabel(field, value);
      }
      if (value && typeof value === "object") {
        return Array.isArray(value) ? `${value.length} 项` : "已配置";
      }
      return value === null || value === undefined || value === ""
        ? "未设置"
        : String(value);
    },

    isProfileFieldDirty(fieldKey) {
      if (!fieldKey) return false;
      const field = this.getProfileField(fieldKey);
      return [
        fieldKey,
        field?.storage_key,
        field?.canonical_key,
        field?.id,
      ].some((dirtyKey) => Boolean(dirtyKey && this.dirtyPaths[dirtyKey]));
    },

    syncActiveMirroredField() {
      const nextField = this.activeMirroredField;
      this.activeMirroredFieldId = nextField?.id || "";
    },

    selectMirroredField(fieldId) {
      this.revealMobileHeader();
      this.activeMirroredFieldId = String(fieldId || "");
      this.syncActiveMirroredField();
    },

    getProfileFieldValue(fieldKey) {
      const field = this.getProfileField(fieldKey);
      if (!field) return null;
      return this.getByPath(field.storage_key || fieldKey);
    },

    resolveProfileFieldMax(field) {
      const maxValue = field?.max;
      const fieldKey = field?.id || field?.canonical_key || field?.storage_key;
      if (
        maxValue &&
        typeof maxValue === "object" &&
        maxValue.type === "dynamic"
      ) {
        const currentValue = Number(this.getProfileFieldValue(fieldKey));
        const fallback = Number(maxValue.fallback ?? 4095);
        return Math.max(
          Number.isFinite(currentValue) ? currentValue : 0,
          fallback,
        );
      }
      const numeric = Number(maxValue);
      return Number.isFinite(numeric) ? numeric : null;
    },

    normalizeProfileFieldValue(field, value) {
      if (!field) return value;
      if (field.control === "checkbox") {
        return (
          value === true || value === "true" || value === 1 || value === "1"
        );
      }
      if (field.control === "select") {
        const options = Array.isArray(field.options) ? field.options : [];
        const normalizedRawValue = String(value ?? "");
        const matchedOption = options.find(
          (option) => String(option ?? "") === normalizedRawValue,
        );
        if (matchedOption !== undefined) return matchedOption;
        const currentValue = this.getProfileFieldValue(
          field?.id || field?.canonical_key || field?.storage_key,
        );
        if (options.includes(currentValue)) return currentValue;
        return field.default ?? options[0] ?? value;
      }
      if (field.control === "range_with_number" || field.control === "number") {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
          return this.getProfileFieldValue(
            field?.id || field?.canonical_key || field?.storage_key,
          );
        }
        const min = Number(field.min ?? 0);
        const max = this.resolveProfileFieldMax(field);
        let nextValue = numeric;
        if (Number.isFinite(min)) nextValue = Math.max(min, nextValue);
        if (Number.isFinite(max)) nextValue = Math.min(max, nextValue);
        const step = Number(field.step || 0);
        if (step > 0) {
          const base = Number.isFinite(min) ? min : 0;
          nextValue = Math.round((nextValue - base) / step) * step + base;
          nextValue = Number(nextValue.toFixed(6));
        }
        return nextValue;
      }
      return value;
    },

    setProfileFieldValue(fieldKey, value) {
      const field = this.getProfileField(fieldKey);
      if (!field) return;
      const normalized = this.normalizeProfileFieldValue(field, value);
      this.setByPath(field.storage_key || fieldKey, normalized);
    },

    getProfileFieldTextValue(fieldKey) {
      const value = this.getProfileFieldValue(fieldKey);
      if (value === null || value === undefined) return "";
      if (typeof value === "object") {
        try {
          return JSON.stringify(value, null, 2);
        } catch (error) {
          return "";
        }
      }
      return String(value);
    },

    setProfileFieldJsonValue(fieldKey, value) {
      const field = this.getProfileField(fieldKey);
      if (!field) return;
      try {
        this.setByPath(
          field.storage_key || fieldKey,
          JSON.parse(String(value || "")),
        );
      } catch (error) {
        return;
      }
    },

    getProfileFieldPercent(fieldKey) {
      const field = this.getProfileField(fieldKey);
      if (!field) return 0;
      const rawValue = Number(this.getProfileFieldValue(fieldKey));
      const min = Number(field.min ?? 0);
      const max = this.resolveProfileFieldMax(field);
      if (!Number.isFinite(rawValue) || !Number.isFinite(max) || max <= min) {
        return 0;
      }
      const ratio = ((rawValue - min) / (max - min)) * 100;
      return Math.max(0, Math.min(100, Math.round(ratio * 100) / 100));
    },

    isProfileFieldSlider(field) {
      return field?.control === "range_with_number";
    },

    isProfileFieldToggle(field) {
      return field?.control === "checkbox";
    },

    isProfileFieldSelect(field) {
      return field?.control === "select";
    },

    setFieldValue(item, value) {
      if (!item || !this.editingData) return;
      if (item.value_path) {
        this.setByPath(item.value_path, value);
        return;
      }
      this.editingData[item.key] = value;
      this.markDirty(item.key || item.id);
    },

    resolveSelectOptionValue(item, rawValue) {
      const options = Array.isArray(item?.editor?.options)
        ? item.editor.options
        : [];
      const normalizedRawValue = String(rawValue ?? "");

      const matchedOption = options.find((option) => {
        const optionValue =
          option && typeof option === "object" && "value" in option
            ? option.value
            : option;
        return String(optionValue ?? "") === normalizedRawValue;
      });

      if (matchedOption === undefined) {
        return rawValue;
      }

      return matchedOption &&
        typeof matchedOption === "object" &&
        "value" in matchedOption
        ? matchedOption.value
        : matchedOption;
    },

    moveListItem(path, fromIndex, toIndex) {
      if (!path || fromIndex === toIndex) return;
      const list = Array.isArray(this.getByPath(path))
        ? [...this.getByPath(path)]
        : [];
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= list.length ||
        toIndex >= list.length
      ) {
        return;
      }
      const [item] = list.splice(fromIndex, 1);
      list.splice(toIndex, 0, item);
      this.setByPath(path, list);
    },

    addStringListItem(path) {
      if (!path) return;
      const list = Array.isArray(this.getByPath(path))
        ? [...this.getByPath(path)]
        : [];
      list.push("");
      this.setByPath(path, list);
    },

    updateStringListItem(path, index, value) {
      if (!path) return;
      const list = Array.isArray(this.getByPath(path))
        ? [...this.getByPath(path)]
        : [];
      if (index < 0 || index >= list.length) return;
      list[index] = value;
      this.setByPath(path, list);
    },

    removeStringListItem(path, index) {
      if (!path) return;
      const list = Array.isArray(this.getByPath(path))
        ? [...this.getByPath(path)]
        : [];
      if (index < 0 || index >= list.length) return;
      list.splice(index, 1);
      this.setByPath(path, list);
    },

    addBiasEntry() {
      const logitBias = Array.isArray(this.getByPath("logit_bias"))
        ? [...this.getByPath("logit_bias")]
        : [];
      logitBias.push({ text: "", value: 0 });
      this.setByPath("logit_bias", logitBias);
    },

    removeBiasEntry(index) {
      const logitBias = Array.isArray(this.getByPath("logit_bias"))
        ? [...this.getByPath("logit_bias")]
        : [];
      if (index < 0 || index >= logitBias.length) return;
      logitBias.splice(index, 1);
      this.setByPath("logit_bias", logitBias);
    },

    updateBiasEntry(index, key, value) {
      const logitBias = Array.isArray(this.getByPath("logit_bias"))
        ? [...this.getByPath("logit_bias")]
        : [];
      if (!logitBias[index] || typeof logitBias[index] !== "object") {
        logitBias[index] = {};
      }
      const nextValue = key === "value" ? Number(value) : value;
      const numericValue = Number(value);
      logitBias[index] = {
        ...logitBias[index],
        [key]:
          key === "value"
            ? Number.isFinite(numericValue)
              ? numericValue
              : 0
            : nextValue,
      };
      this.setByPath("logit_bias", logitBias);
    },

    formatValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "boolean") return value ? "是" : "否";
      if (typeof value === "number")
        return Number.isInteger(value)
          ? value
          : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
      if (typeof value === "object") {
        try {
          return JSON.stringify(value, null, 2);
        } catch (error) {
          return String(value);
        }
      }
      return String(value);
    },

    isLongTextField(item) {
      return Boolean(item && LONG_TEXT_FIELDS.has(item.key));
    },

    estimateFieldTokens(item) {
      if (!item) return 0;
      return estimateTokens(String(this.getFieldValue(item) || ""));
    },

    openLargeEditorForItem(item) {
      if (!item || !this.editingData) return;
      if (this.pendingLargeEditorSaveHandler) {
        window.removeEventListener(
          "large-editor-save",
          this.pendingLargeEditorSaveHandler,
        );
        this.pendingLargeEditorSaveHandler = null;
      }
      const editingData = deepClone(this.editingData);
      window.dispatchEvent(
        new CustomEvent("open-large-editor", {
          detail: {
            field: item.key,
            title: item.label,
            isArray: false,
            index: 0,
            valuePath: item.value_path || item.key || "",
            editingData,
          },
        }),
      );
      const saveHandler = () => {
        window.removeEventListener("large-editor-save", saveHandler);
        this.pendingLargeEditorSaveHandler = null;
        this.editingData = editingData;
        this.markDirty(item.value_path || item.key || item.id || null);
      };
      this.pendingLargeEditorSaveHandler = saveHandler;
      window.addEventListener("large-editor-save", saveHandler);
    },

    async openPresetEditor({
      presetId,
      activeNav = "basic",
      preserveNav = false,
      preserveContext = false,
      context = null,
    } = {}) {
      if (!presetId) return;
      this.isLoading = true;
      try {
        const res = await getPresetDetail(presetId);
        if (!res.success) {
          this.$store.global.showToast(res.msg || "打开预设失败", "error");
          return;
        }

        this.editingPresetFile = deepClone(res.preset);
        this.editingData = deepClone(res.preset.raw_data || {});
        const nextNav = preserveNav ? this.activeNav || activeNav : activeNav;
        const reopenContext = preserveContext
          ? this.normalizeReopenContext(context || this.buildReopenContext())
          : null;
        this.activeNav = nextNav || this.navSections[0] || "basic";
        if (!this.navSections.includes(this.activeNav)) {
          this.activeNav = this.navSections[0] || "basic";
        }
        const defaultWorkspace = this.isPromptWorkspaceEditor ? "prompts" : "all";
        this.activeWorkspace =
          reopenContext?.activeWorkspace || defaultWorkspace;
        if (!this.isPromptWorkspaceEditor && this.activeWorkspace !== "all") {
          this.activeWorkspace = "all";
        }
        this.searchTerm = "";
        this.uiFilter = "all";
        this.activeGroup = reopenContext?.activeGroup || "all";
        this.activePromptId = reopenContext?.activePromptId || "";
        this.promptAppendId = "";
        this.activeGenericItemId = reopenContext?.activeGenericItemId || "";
        this.activeItemId = reopenContext?.activeItemId || "";
        this.showMobileSidebar = false;
        this.showMobilePromptDetailView = false;
        this.resetMobileHeaderState();
        this.showPromptTriggers = false;
        this.markClean();
        if (this.isPromptWorkspaceEditor && this.activeWorkspace === "prompts") {
          this.refreshEditorCollections();
          this.syncActiveEditorSelections();
        } else {
          this.selectGroup(this.activeGroup || "all");
        }
        this.showPresetEditor = true;
        this.hasConflict = false;
        this.conflictRevision = "";

        setActiveRuntimeContext({
          preset: {
            id: this.editingPresetFile.id,
            name: this.editingPresetFile.name,
            type: this.editingPresetFile.type,
            path: this.editingPresetFile.path,
          },
        });

        this.$nextTick(() => {
          this.restartAutoSaver();
          this.updatePresetEditorLayoutMetrics();
        });
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("打开预设失败", "error");
      } finally {
        this.isLoading = false;
      }
    },

    async reloadFromDisk() {
      if (!this.editingPresetFile?.id) return;
      await this.openPresetEditor({ presetId: this.editingPresetFile.id });
    },

    openVersion(versionId) {
      const targetVersionId = String(versionId || "").trim();
      if (!targetVersionId) {
        return;
      }
      return this.reopenPresetVersion(targetVersionId);
    },

    closeEditor() {
      if (this.isDirty && !confirm("当前预设有未保存修改，确定关闭吗？")) {
        return;
      }
      if (this.pendingLargeEditorSaveHandler) {
        window.removeEventListener(
          "large-editor-save",
          this.pendingLargeEditorSaveHandler,
        );
        this.pendingLargeEditorSaveHandler = null;
      }
      this.cleanupAdvancedEditorListeners();
      this.activeWorkspace = "all";
      this.activeGroup = "all";
      this.activePromptId = "";
      this.promptAppendId = "";
      this.activeGenericItemId = "";
      this.activeItemId = "";
      this.showMobilePromptDetailView = false;
      this.showMobileSidebar = false;
      this.resetMobileHeaderState();
      this.showPromptTriggers = false;
      this.promptItemsCache = [];
      this.orderedPromptItemsCache = [];
      this.filteredItemsCache = [];
      this.genericWorkspaceItemsCache = [];
      this.activePromptItemCache = null;
      this.activeItemCache = null;
      this.showPresetEditor = false;
    },

    async saveOverwrite() {
      if (!this.editingPresetFile || !this.editingData || this.isSaving) return;
      this.isSaving = true;
      this.hasConflict = false;
      this.conflictRevision = "";
      try {
        const res = await savePreset({
          preset_id: this.editingPresetFile.id,
          preset_kind: this.editingPresetFile.preset_kind,
          save_mode: "overwrite",
          source_revision: this.editingPresetFile.source_revision,
          content: this.editingData,
        });

        if (!res.success) {
          if (res.current_source_revision) {
            this.hasConflict = true;
            this.conflictRevision = res.current_source_revision;
            this.$store.global.showToast(
              "文件已被外部修改，请重新加载或另存为",
              "error",
            );
            return;
          }
          this.$store.global.showToast(res.msg || "保存失败", "error");
          return;
        }

        this.editingPresetFile = deepClone(
          res.preset || this.editingPresetFile,
        );
        this.editingData = deepClone(
          this.editingPresetFile.raw_data || this.editingData,
        );
        this.markClean();
        this.restartAutoSaver();
        setActiveRuntimeContext({
          preset: {
            id: this.editingPresetFile.id,
            name: this.editingPresetFile.name,
            type: this.editingPresetFile.type,
            path: this.editingPresetFile.path,
          },
        });
        this.$store.global.showToast("预设已保存");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("保存失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    async saveAs() {
      if (!this.editingData || this.isSaving) return;
      const name = prompt(
        "请输入新预设名称：",
        this.editingData.name || this.editingPresetFile?.name || "新预设",
      );
      if (!name) return;
      this.isSaving = true;
      try {
        const res = await savePreset({
          preset_kind: this.editingPresetFile?.preset_kind || "",
          save_mode: "save_as",
          name,
          content: { ...this.editingData, name },
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "另存为失败", "error");
          return;
        }
        this.$store.global.showToast("已另存为新预设");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        await this.openPresetEditor({
          presetId: res.preset_id || res.preset?.id,
        });
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("另存为失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    async saveAsVersion() {
      if (!this.editingPresetFile || !this.editingData || this.isSaving) return;

      const currentFamilyName =
        this.editingPresetFile?.family_info?.family_name ||
        this.editingData?.x_st_manager?.preset_family_name ||
        this.editingData?.name ||
        this.editingPresetFile?.name ||
        "";
      const familyName = prompt("请输入版本家族名称：", currentFamilyName);
      if (!familyName) return;

      const versionLabel = prompt("请输入版本标记：", "");
      if (!versionLabel) return;

      const fileName = prompt(
        "请输入新版本文件名：",
        `${familyName} ${versionLabel}`.trim(),
      );
      if (!fileName) return;

      this.isSaving = true;
      try {
        const content = {
          ...this.editingData,
          name: fileName,
          x_st_manager: {
            ...(this.editingData?.x_st_manager || {}),
            preset_family_name: familyName,
          },
        };
        const res = await savePreset({
          preset_id: this.editingPresetFile.id,
          preset_kind: this.editingPresetFile.preset_kind,
          save_mode: "save_as",
          create_as_version: true,
          version_label: versionLabel,
          source_revision: this.editingPresetFile.source_revision,
          name: fileName,
          content,
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "另存为版本失败", "error");
          return;
        }
        this.$store.global.showToast("已另存为新版本");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        await this.reopenPresetVersion(res.preset_id || res.preset?.id);
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("另存为版本失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    async setCurrentVersionAsDefault() {
      if (!this.editingPresetFile?.id || this.isSaving) return;

      this.isSaving = true;
      try {
        const res = await setDefaultPresetVersion({
          preset_id: this.editingPresetFile.id,
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "设置默认版本失败", "error");
          return;
        }
        this.$store.global.showToast("默认版本已更新");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        await this.reopenPresetVersion(
          res.preset_id || res.preset?.id || this.editingPresetFile.id,
        );
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("设置默认版本失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    async renamePreset() {
      if (!this.editingPresetFile || this.isSaving) return;
      const name = prompt(
        "请输入新的预设名称：",
        this.editingData?.name || this.editingPresetFile.name || "",
      );
      if (!name) return;
      this.isSaving = true;
      try {
        const res = await savePreset({
          preset_id: this.editingPresetFile.id,
          save_mode: "rename",
          new_name: name,
          source_revision: this.editingPresetFile.source_revision,
        });
        if (!res.success) {
          if (res.current_source_revision) {
            this.hasConflict = true;
            this.conflictRevision = res.current_source_revision;
          }
          this.$store.global.showToast(res.msg || "重命名失败", "error");
          return;
        }
        this.$store.global.showToast("预设已重命名");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        await this.openPresetEditor({
          presetId: res.preset_id || res.preset?.id,
        });
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("重命名失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    async deletePreset() {
      if (!this.editingPresetFile || this.isSaving) return;
      if (
        !confirm(
          `确定删除预设“${this.editingPresetFile.name || "未命名预设"}”吗？`,
        )
      )
        return;
      this.isSaving = true;
      try {
        const res = await savePreset({
          preset_id: this.editingPresetFile.id,
          save_mode: "delete",
          source_revision: this.editingPresetFile.source_revision,
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "删除失败", "error");
          return;
        }
        this.$store.global.showToast("预设已删除");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        this.closeEditor();
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("删除失败", "error");
      } finally {
        this.isSaving = false;
      }
    },

    openAdvancedExtensions() {
      if (!this.editingData) return;
      this.cleanupAdvancedEditorListeners();
      const editingData = {
        extensions: normalizePresetExtensionsForEditor(
          this.editingData.extensions || {},
        ),
        editorCommitMode: "buffered",
        showPersistButton: true,
      };
      window.dispatchEvent(
        new CustomEvent("open-advanced-editor", {
          detail: editingData,
        }),
      );
      const applyHandler = async () => {
        this.cleanupAdvancedEditorListeners();
        this.setByPath(
          "extensions",
          deepClone(editingData.extensions || {}),
        );
        this.markDirty("extensions");
      };
      const persistHandler = async () => {
        this.cleanupAdvancedEditorListeners();
        this.setByPath(
          "extensions",
          normalizePresetExtensionsForSave(editingData.extensions || {}),
        );
        this.markDirty("extensions");
        const saveResult = await this.saveExtensions();
        if (saveResult === false) return;
        window.dispatchEvent(new CustomEvent("advanced-editor-close"));
      };
      this.pendingAdvancedEditorApplyHandler = applyHandler;
      this.pendingAdvancedEditorPersistHandler = persistHandler;
      window.addEventListener("advanced-editor-apply", applyHandler);
      window.addEventListener("advanced-editor-persist", persistHandler);
    },

    cleanupAdvancedEditorListeners() {
      if (this.pendingAdvancedEditorApplyHandler) {
        window.removeEventListener(
          "advanced-editor-apply",
          this.pendingAdvancedEditorApplyHandler,
        );
        this.pendingAdvancedEditorApplyHandler = null;
      }
      if (this.pendingAdvancedEditorPersistHandler) {
        window.removeEventListener(
          "advanced-editor-persist",
          this.pendingAdvancedEditorPersistHandler,
        );
        this.pendingAdvancedEditorPersistHandler = null;
      }
    },

    async saveExtensions() {
      if (!this.editingPresetFile || !this.editingData) return;
      try {
        const res = await apiSavePresetExtensions({
          id: this.editingPresetFile.id,
          extensions: normalizePresetExtensionsForSave(
            this.editingData.extensions || {},
          ),
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "保存扩展失败", "error");
          return false;
        }
        this.$store.global.showToast("扩展已保存");
        await this.reloadFromDisk();
        return true;
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("保存扩展失败", "error");
        return false;
      }
    },

    async createSnapshot(isKey = false) {
      if (!this.editingPresetFile || !this.editingData) return;
      try {
        const res = await apiCreateSnapshot({
          id: this.editingPresetFile.id,
          type: "preset",
          file_path:
            this.editingPresetFile.file_path || this.editingPresetFile.path,
          label: isKey ? "KEY" : "",
          content: this.editingData,
          compact: true,
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "快照失败", "error");
          return;
        }
        this.$store.global.showToast(isKey ? "关键快照已保存" : "快照已保存");
      } catch (error) {
        console.error(error);
        this.$store.global.showToast("快照失败", "error");
      }
    },

    openRollback() {
      if (!this.editingPresetFile) return;
      window.dispatchEvent(
        new CustomEvent("open-rollback", {
          detail: {
            type: "preset",
            id: this.editingPresetFile.id,
            path:
              this.editingPresetFile.file_path || this.editingPresetFile.path,
            editingData: this.editingData,
            editingPresetFile: this.editingPresetFile,
          },
        }),
      );
    },
  };
}
