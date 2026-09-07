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

const PRESET_DRAFT_PREFIX = "st-manager:preset-draft:";

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
    activeGenericItemId: "",
    activeItemId: "",
    activeMirroredFieldId: "",
    searchTerm: "",
    uiFilter: "all",
    showMobileSidebar: false,
    showRightPanel: true,
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
    draftState: { savedAt: "", restored: false },
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
        this.showRightPanel = deviceType !== "mobile";
        this.showMobilePromptDetailView = false;
        this.updatePresetEditorLayoutMetrics();
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
      const kind =
        this.editingPresetFile?.preset_kind_label ||
        this.presetKind ||
        this.editingPresetFile?.type ||
        "预设";
      const path =
        this.editingPresetFile?.path ||
        this.editingPresetFile?.file_path ||
        this.editingPresetFile?.name ||
        "未定位文件";
      return `${kind} · ${path}`;
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

    toggleMobileRightPanel() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showRightPanel = !this.showRightPanel;
      this.updatePresetEditorLayoutMetrics();
    },

    closeMobileRightPanel() {
      this.showRightPanel = false;
      this.showMobileHeaderMoreMenu = false;
      this.updatePresetEditorLayoutMetrics();
    },

    openMobilePromptDetailView() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobilePromptDetailView = true;
      this.showRightPanel = false;
      this.updatePresetEditorLayoutMetrics();
    },

    closeMobilePromptDetailView() {
      this.revealMobileHeader();
      this.showMobileHeaderMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobilePromptDetailView = false;
      this.showRightPanel = false;
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
        this.showRightPanel ||
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

    get activeMirroredSection() {
      if (!this.isMirroredProfileEditor) return null;
      if (this.activeWorkspace === "prompts") {
        return (
          this.mirroredProfileSections.find(
            (section) => section.id === "prompt_manager",
          ) || null
        );
      }
      return (
        this.mirroredProfileSections.find(
          (section) => section.id === this.activeWorkspace,
        ) ||
        this.mirroredProfileSections[0] ||
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
      return this.getProfileSectionFields(sectionId).length;
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

    get orderedPromptItems() {
      this.ensureEditorCollections();
      return this.orderedPromptItemsCache;
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

    buildDraftKey() {
      return `${PRESET_DRAFT_PREFIX}${this.editingPresetFile?.id || "unknown"}`;
    },

    persistLocalDraft() {
      if (!this.editingData || !this.editingPresetFile) return;
      const payload = {
        saved_at: new Date().toISOString(),
        source_revision: this.editingPresetFile.source_revision || "",
        content: this.editingData,
      };
      localStorage.setItem(this.buildDraftKey(), JSON.stringify(payload));
      this.draftState.savedAt = payload.saved_at;
    },

    restoreLocalDraft() {
      if (!this.editingPresetFile) return false;
      const raw = localStorage.getItem(this.buildDraftKey());
      if (!raw) return false;
      try {
        const payload = JSON.parse(raw);
        if (payload?.content && confirm("检测到本地草稿，是否恢复到编辑器？")) {
          this.editingData = payload.content;
          this.dirtyPaths = {};
          this.markAllReaderItemsDirty();
          this.draftState.savedAt = payload.saved_at || "";
          this.draftState.restored = true;
          this.refreshEditorCollections();
          return true;
        }
      } catch (error) {
        console.warn("Restore preset draft failed:", error);
      }
      return false;
    },

    clearLocalDraft() {
      if (!this.editingPresetFile) return;
      localStorage.removeItem(this.buildDraftKey());
      this.draftState = { savedAt: "", restored: false };
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

      const orderedPrompts = Array.isArray(nextOrderedPrompts)
        ? nextOrderedPrompts
        : this.orderedPromptItems;
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

      const reordered = nextOrderedPrompts
        .map((entry) => {
          const promptIndex = Number(entry?.__prompt_index);
          if (!Number.isInteger(promptIndex)) {
            return null;
          }
          return this.promptItems.find(
            (prompt) => Number(prompt.__prompt_index) === promptIndex,
          );
        })
        .filter(Boolean)
        .map((prompt) => {
          const nextPrompt = { ...prompt };
          delete nextPrompt.__prompt_index;
          return nextPrompt;
        });

      this.setByPath("prompts", reordered);
      const enriched = nextOrderedPrompts.map((entry) => ({
        ...entry,
        __enabled: entry.__enabled !== false,
      }));
      this.syncPromptOrder(enriched);
    },

    movePromptItem(fromIndex, toIndex) {
      const orderedPrompts = [...this.getPromptArrayWithMeta()];
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= orderedPrompts.length ||
        toIndex >= orderedPrompts.length ||
        fromIndex === toIndex
      ) {
        return;
      }

      const [prompt] = orderedPrompts.splice(fromIndex, 1);
      orderedPrompts.splice(toIndex, 0, prompt);
      this.replacePromptOrder(orderedPrompts);
      this.activePromptId = prompt?.__identifier || this.activePromptId;
    },

    togglePromptEnabled(identifier) {
      const promptId = String(identifier || "");
      if (!promptId || !this.editingData) return;
      if (this.hasUnsupportedNestedPromptOrder()) return;

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
      if (key === "content" && prompts[promptIndex].marker) {
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
      return Boolean(prompt && !prompt.marker);
    },

    selectGroup(groupId) {
      this.revealMobileHeader();
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
        if (this.$store?.global?.deviceType !== "mobile") {
          this.showRightPanel = true;
        }
        return;
      }

      this.showMobilePromptDetailView = false;
      this.activeGroup = this.activeWorkspace;
      this.refreshEditorCollections();
      this.syncActiveMirroredField();
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
        .filter(([, meta]) => meta?.section === sectionId)
        .map(([fieldKey, meta]) => ({
          fieldKey,
          storage_key: meta?.storage_key || fieldKey,
          canonical_key: meta?.canonical_key || fieldKey,
          ...meta,
        }));
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
      return Object.values(this.editorProfile?.fields || {}).filter(
        (field) => field.section === sectionId,
      );
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
        this.activeGenericItemId = reopenContext?.activeGenericItemId || "";
        this.activeItemId = reopenContext?.activeItemId || "";
        this.showMobileSidebar = false;
        this.showRightPanel = this.$store?.global?.deviceType !== "mobile";
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
        this.draftState = { savedAt: "", restored: false };
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
          this.restoreLocalDraft();
          autoSaver.initBaseline(this.editingData);
          autoSaver.start(
            () => this.editingData,
            () => null,
            async () => {
              this.persistLocalDraft();
            },
          );
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
      const preserveDraft = this.isDirty;
      if (preserveDraft) {
        this.persistLocalDraft();
      }
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
      if (this.isDirty) {
        this.persistLocalDraft();
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
      this.activeGenericItemId = "";
      this.activeItemId = "";
      this.showMobilePromptDetailView = false;
      this.showMobileSidebar = false;
      this.showRightPanel = this.$store?.global?.deviceType !== "mobile";
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
        autoSaver.initBaseline(this.editingData);
        this.clearLocalDraft();
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

    async createSnapshot() {
      if (!this.editingPresetFile || !this.editingData) return;
      try {
        const res = await apiCreateSnapshot({
          id: this.editingPresetFile.id,
          type: "preset",
          file_path:
            this.editingPresetFile.file_path || this.editingPresetFile.path,
          label: "",
          content: this.editingData,
          compact: true,
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "快照失败", "error");
          return;
        }
        this.$store.global.showToast("快照已保存");
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
