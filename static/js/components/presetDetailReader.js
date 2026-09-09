/**
 * static/js/components/presetDetailReader.js
 * 预设详情阅读器组件
 */

import {
  getPresetDetail,
  importPresetVersion,
  sendPresetToSillyTavern,
  isPresetSendToStPending,
  setPresetSendToStPending,
  savePresetExtensions as apiSavePresetExtensions,
} from "../api/presets.js";
import {
  clearActiveRuntimeContext,
  setActiveRuntimeContext,
} from "../runtime/runtimeContext.js";
import { downloadFileFromApi } from "../utils/download.js";
import { formatDate } from "../utils/format.js";
import {
  getPresetExtensionSummary,
  normalizePresetExtensionsForEditor,
  normalizePresetExtensionsForSave,
} from "../utils/extensionCompatibility.js";
import {
  buildPromptMarkerIcon,
  getPromptMarkerVisual as resolvePromptMarkerVisual,
} from "../utils/promptMarkerVisuals.js";

const UI_FILTERS = [
  { id: "all", label: "全部" },
  { id: "structured", label: "结构化" },
  { id: "extension", label: "扩展" },
];

const PROMPT_UI_FILTERS = [
  { id: "all", label: "全部" },
  { id: "enabled", label: "启用" },
  { id: "disabled", label: "禁用" },
  { id: "marker", label: "预留字段" },
];

const TYPE_LABELS = {
  extension: "扩展",
  field: "字段",
  structured: "结构化",
};

const GROUP_FALLBACK_LABELS = {
  extensions: "扩展",
  scalar_fields: "基础设置",
  structured_objects: "结构化对象",
};

const PROMPT_POSITION_LABELS = {
  0: "相对",
  1: "聊天中",
};

const PROFILE_SOURCE_LABELS = {
  openai: "OpenAI",
  custom: "Custom",
  ai21: "AI21",
  aimlapi: "AIML API",
  azure_openai: "Azure OpenAI",
  chutes: "Chutes",
  cohere: "Cohere",
  cometapi: "CometAPI",
  electronhub: "ElectronHub",
  fireworks: "Fireworks",
  groq: "Groq",
  makersuite: "Google AI Studio",
  claude: "Claude",
  deepseek: "DeepSeek",
  minimax: "MiniMax",
  mistralai: "Mistral",
  moonshot: "Moonshot",
  nanogpt: "NanoGPT",
  openrouter: "OpenRouter",
  perplexity: "Perplexity",
  pollinations: "Pollinations",
  siliconflow: "SiliconFlow",
  vertexai: "Vertex AI",
  workers_ai: "Workers AI",
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

const UI_FILTER_IDS = new Set(UI_FILTERS.map((filter) => filter.id));
const PROMPT_UI_FILTER_IDS = new Set(
  PROMPT_UI_FILTERS.map((filter) => filter.id),
);
const HIDDEN_READER_MIRRORED_SECTION_IDS = new Set([
  "prompt_manager",
  "extensions_and_advanced",
]);

function normalizeText(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase();
}

export default function presetDetailReader() {
  return {
    showModal: false,
    isLoading: false,
    loadError: "",
    activePresetRequestId: "",
    activePresetDetail: null,
    activeWorkspace: "all",
    activeGroup: "all",
    activePromptId: "",
    activeItemId: "",
    searchTerm: "",
    uiFilter: "all",
    showRightPanel: true,
    showMobileDetailView: false,
    showMobileSidebar: false,
    showMobileMoreMenu: false,
    isSendingPresetToST: false,
    promptItemsCache: [],
    orderedPromptItemsCache: [],
    promptFilteredItemsCache: [],
    filteredItemsCache: [],
    activePromptItemCache: null,
    activeItemCache: null,
    activeContextItemCache: null,
    readerStatsCache: { total_count: 0, visible_count: 0 },
    pendingAdvancedEditorApplyHandler: null,
    pendingAdvancedEditorPersistHandler: null,

    init() {
      this.showRightPanel = this.$store?.global?.deviceType !== "mobile";
      this.$watch?.("$store.global.deviceType", (deviceType) => {
        this.resetMobileHeaderState();
        if (deviceType !== "mobile") {
          this.showMobileDetailView = false;
          this.showMobileSidebar = false;
          this.showRightPanel = true;
        } else {
          this.showMobileDetailView = false;
          this.showMobileSidebar = false;
          this.showRightPanel = false;
        }
      });
      window.addEventListener("open-preset-reader", (e) => {
        this.openPreset(e.detail || {});
      });

      window.addEventListener("preset-sent-to-st", (e) => {
        const detail = e.detail || {};
        if (!detail?.id) return;
        if (!detail.last_sent_to_st) return;
        if (this.activePresetDetail && this.activePresetDetail.id === detail.id) {
          this.activePresetDetail = {
            ...this.activePresetDetail,
            last_sent_to_st: Number(detail.last_sent_to_st || 0),
          };
        }
      });

      window.addEventListener("preset-send-to-st-pending", (e) => {
        setPresetSendToStPending(e.detail?.id, true);
        if (this.activePresetDetail?.id !== e.detail?.id) return;
        this.syncActivePresetSendingState(e.detail?.id);
      });

      window.addEventListener("preset-send-to-st-finished", (e) => {
        setPresetSendToStPending(e.detail?.id, false);
        if (this.activePresetDetail?.id !== e.detail?.id) return;
        this.syncActivePresetSendingState(e.detail?.id);
      });
    },

    syncActivePresetSendingState(presetId = null) {
      const activeId = String(
        presetId || this.activePresetDetail?.id || "",
      ).trim();
      this.isSendingPresetToST = activeId
        ? isPresetSendToStPending(activeId)
        : false;
    },

    updateSearchTerm(value) {
      this.searchTerm = value || "";
      this.refreshReaderCollections();
    },

    setUiFilter(filterId) {
      this.uiFilter = filterId || "all";
      this.refreshReaderCollections();
    },

    get readerView() {
      const view = this.activePresetDetail?.reader_view;
      if (view && Array.isArray(view.items)) {
        return {
          family: view.family || "generic",
          family_label: view.family_label || "通用预设",
          groups: Array.isArray(view.groups) ? view.groups : [],
          items: view.items,
          scalar_workspace:
            view.scalar_workspace && typeof view.scalar_workspace === "object"
              ? view.scalar_workspace
              : null,
          stats: view.stats && typeof view.stats === "object" ? view.stats : {},
        };
      }
      return {
        family: "generic",
        family_label: "通用预设",
        groups: [],
        items: [],
        scalar_workspace: null,
        stats: {
          total_count: 0,
        },
      };
    },

    get readerGroups() {
      const groups = Array.isArray(this.readerView.groups)
        ? this.readerView.groups
        : [];
      return groups.map((group) => ({
        ...group,
        label: group.label || GROUP_FALLBACK_LABELS[group.id] || group.id,
      }));
    },

    get readerItems() {
      return Array.isArray(this.readerView.items) ? this.readerView.items : [];
    },

    get availableVersions() {
      return Array.isArray(this.activePresetDetail?.available_versions)
        ? this.activePresetDetail.available_versions
        : [];
    },

    get hasMultipleVersions() {
      return this.availableVersions.length > 1;
    },

    get isPromptWorkspaceReader() {
      return this.readerView.family === "prompt_manager";
    },

    get scalarWorkspace() {
      return this.readerView.scalar_workspace || null;
    },

    get hasScalarWorkspace() {
      return !!this.scalarWorkspace;
    },

    get isScalarWorkspaceReader() {
      return (
        this.readerView.family === "prompt_manager" &&
        this.activeWorkspace !== "prompts" &&
        (this.readerWorkspaceSections.some(
          (section) => section.id === this.activeWorkspace,
        ) || this.activeWorkspace === "scalar_fields") &&
        this.hasScalarWorkspace
      );
    },

    get scalarWorkspaceSections() {
      return Array.isArray(this.scalarWorkspace?.sections)
        ? this.scalarWorkspace.sections
        : [];
    },

    get scalarWorkspaceVisibleFieldEntries() {
      const fieldEntries = Object.entries(
        this.scalarWorkspace?.field_map || {},
      );
      const hiddenFields = new Set(this.scalarWorkspace?.hidden_fields || []);
      const query = normalizeText(this.searchTerm);

      return fieldEntries.filter(([fieldKey, fieldConfig]) => {
        if (hiddenFields.has(fieldKey)) {
          return false;
        }

        if (
          Object.prototype.hasOwnProperty.call(fieldConfig || {}, "source_key") &&
          fieldConfig.source_key === null
        ) {
          return false;
        }

        if (!this.isProfileFieldVisible(fieldConfig)) {
          return false;
        }

        if (
          this.activeWorkspace !== "all" &&
          this.activeWorkspace !== "scalar_fields" &&
          fieldConfig?.section !== this.activeWorkspace &&
          fieldConfig?.workspace_section !== this.activeWorkspace
        ) {
          return false;
        }

        if (!query) {
          return true;
        }

        const haystack = [
          fieldKey,
          fieldConfig?.canonical_key,
          fieldConfig?.label,
          fieldConfig?.section,
        ]
          .map(normalizeText)
          .filter(Boolean)
          .join(" ");
        return haystack.includes(query);
      });
    },

    get scalarWorkspaceTotalVisibleFieldCount() {
      const fieldEntries = Object.entries(
        this.scalarWorkspace?.field_map || {},
      );
      const hiddenFields = new Set(this.scalarWorkspace?.hidden_fields || []);
      return fieldEntries.filter(([fieldKey, fieldConfig]) => {
        if (hiddenFields.has(fieldKey)) return false;
        if (
          Object.prototype.hasOwnProperty.call(fieldConfig || {}, "source_key") &&
          fieldConfig.source_key === null
        ) {
          return false;
        }
        if (!this.isProfileFieldVisible(fieldConfig)) return false;
        if (
          this.activeWorkspace !== "all" &&
          this.activeWorkspace !== "scalar_fields" &&
          fieldConfig?.section !== this.activeWorkspace &&
          fieldConfig?.workspace_section !== this.activeWorkspace
        ) {
          return false;
        }
        return true;
      }).length;
    },

    get scalarWorkspaceSummaryCards() {
      return [
        {
          id: "visible_fields",
          label: "可见字段",
          value: this.scalarWorkspaceVisibleFieldEntries.length,
        },
        {
          id: "sections",
          label: "分区数量",
          value: this.scalarWorkspaceSections.length,
        },
      ];
    },

    get scalarWorkspaceCards() {
      return this.scalarWorkspaceSummaryCards;
    },

    get promptItems() {
      return this.promptItemsCache;
    },

    get orderedPromptItems() {
      return this.orderedPromptItemsCache;
    },

    get promptFilteredItems() {
      return this.promptFilteredItemsCache;
    },

    get filteredItems() {
      return this.filteredItemsCache;
    },

    get activeItem() {
      return this.activeItemCache;
    },

    get activePromptItem() {
      return this.activePromptItemCache;
    },

    get activeContextItem() {
      return this.activeContextItemCache;
    },

    get readerStats() {
      return this.readerStatsCache;
    },

    get extensionOverview() {
      const detailExtensions = this.activePresetDetail?.extensions;
      const rawExtensions = this.activePresetDetail?.raw_data?.extensions;
      const extensions =
        detailExtensions &&
        typeof detailExtensions === "object" &&
        !Array.isArray(detailExtensions)
          ? detailExtensions
          : rawExtensions &&
              typeof rawExtensions === "object" &&
              !Array.isArray(rawExtensions)
            ? rawExtensions
            : {};

      return getPresetExtensionSummary(extensions);
    },

    get extensionMetricCards() {
      const overview = this.extensionOverview;
      return [
        { id: "regex", label: "正则脚本", value: overview.regex_count },
        { id: "scripts", label: "ST 脚本", value: overview.script_count },
        { id: "other", label: "其他扩展", value: overview.other_count },
      ];
    },

    get uiFilters() {
      if (this.isPromptWorkspaceReader && this.activeWorkspace === "prompts") {
        return PROMPT_UI_FILTERS;
      }
      return UI_FILTERS;
    },

    getMobileHeaderMetaLine() {
      const kind = this.activePresetDetail?.preset_kind || "预设";
      const source = this.getSourceLabel();
      const family = this.readerView.family_label || "通用预设";
      return source ? `${kind} · ${source} / ${family}` : `${kind} · ${family}`;
    },

    getMobileHeaderContextLabel() {
      if (this.isPromptWorkspaceReader && this.activeWorkspace === "prompts") {
        return "提示词列表";
      }
      return "内容流";
    },

    getMobileHeaderCountLabel() {
      if (this.isPromptWorkspaceReader && this.activeWorkspace === "prompts") {
        return `${this.promptFilteredItems.length} / ${this.orderedPromptItems.length}`;
      }
      if (this.isScalarWorkspaceReader) {
        return `${this.readerStats.visible_count} / ${this.readerStats.total_count}`;
      }
      return `${this.filteredItems.length} / ${this.readerStats.total_count}`;
    },

    getActivePresetSyncLabel() {
      if (this.isSendingPresetToST) return "正在发送到 ST";
      if (Number(this.activePresetDetail?.last_sent_to_st || 0) > 0) {
        return "已发送到 ST";
      }
      return "尚未发送到 ST";
    },

    getPromptRoleLabel(item) {
      const role = String(item?.payload?.role || "").trim();
      return role || "未指定角色";
    },

    getPromptTriggerLabel(item) {
      const triggers = item?.payload?.injection_trigger;
      if (!Array.isArray(triggers) || triggers.length === 0) {
        return "默认触发";
      }
      return triggers.join("、");
    },

    resetMobileHeaderState() {
      this.showMobileMoreMenu = false;
    },

    toggleMobileSidebar() {
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = !this.showMobileSidebar;
    },

    toggleMobileRightPanel() {
      this.showMobileMoreMenu = false;
      this.showRightPanel = !this.showRightPanel;
    },

    openMobileDetailView() {
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobileDetailView = true;
      this.showRightPanel = false;
    },

    closeMobileDetailView() {
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobileDetailView = false;
      this.showRightPanel = false;
    },

    toggleMobileMoreMenu() {
      this.showMobileMoreMenu = !this.showMobileMoreMenu;
    },

    handleReaderEscape() {
      if (this.showMobileMoreMenu) {
        this.showMobileMoreMenu = false;
        return;
      }
      if (this.showMobileSidebar) {
        this.showMobileSidebar = false;
        return;
      }
      if (this.showMobileDetailView) {
        this.closeMobileDetailView();
        return;
      }
      this.closeModal();
    },

    async openPreset(item) {
      const presetId =
        item?.entry_type === "family" && item?.default_version_id
          ? item.default_version_id
          : item?.id;
      if (!presetId) return;
      this.activePresetRequestId = presetId;
      this.isLoading = true;
      this.loadError = "";
      this.showModal = true;
      this.showMobileSidebar = false;
      this.showMobileDetailView = false;
      this.showRightPanel = this.$store?.global?.deviceType !== "mobile";
      this.resetMobileHeaderState();
      this.searchTerm = "";
      this.uiFilter = "all";
      this.activeWorkspace = "all";
      this.activeGroup = "all";
      this.activePromptId = "";
      this.activeItemId = "";
      this.refreshReaderCollections();

      try {
        const res = await getPresetDetail(presetId);
        if (!res.success) {
          this.activePresetDetail = null;
          this.loadError = res.msg || "获取详情失败";
          this.$store.global.showToast(this.loadError, "error");
          return;
        }

        this.activePresetDetail = res.preset;
        this.syncActivePresetSendingState(res.preset?.id || item.id);
        setActiveRuntimeContext({
          preset: {
            id: res.preset?.id || presetId || "",
            name: res.preset?.name || "",
            type: res.preset?.type || "",
            path: res.preset?.path || "",
          },
        });
        this.initializeReaderState();
      } catch (error) {
        console.error("Failed to load preset detail:", error);
        this.activePresetDetail = null;
        this.loadError = error?.message || "获取详情失败";
        this.$store.global.showToast(this.loadError, "error");
      } finally {
        this.isLoading = false;
      }
    },

    async retryActivePreset() {
      if (!this.activePresetRequestId) return;
      await this.openPreset({ id: this.activePresetRequestId });
    },

    async switchVersion(versionId) {
      if (!versionId || versionId === this.activePresetDetail?.id) {
        return;
      }
      await this.openPreset({ id: versionId });
    },

    initializeReaderState() {
      if (this.isPromptWorkspaceReader) {
        const availableWorkspaces = new Set(
          this.readerGroups.map((group) => group.id).filter(Boolean),
        );
        this.activeWorkspace = availableWorkspaces.has(this.activeWorkspace)
          ? this.activeWorkspace
          : this.readerGroups.find((group) => group.id === "prompts")?.id ||
            this.readerGroups[0]?.id ||
            "prompts";
        this.activeGroup = "all";
        this.activeItemId = "";
        this.refreshReaderCollections();
        if (this.$store?.global?.deviceType !== "mobile") {
          this.showRightPanel = true;
        } else {
          this.showMobileDetailView = false;
        }
        return;
      }

      const firstGroup = this.readerGroups[0]?.id || "all";
      this.activeGroup = firstGroup;
      this.activeWorkspace = "all";
      this.activePromptId = "";
      this.activeItemId = "";
      this.refreshReaderCollections();
      if (this.$store?.global?.deviceType !== "mobile") {
        this.showRightPanel = true;
      } else {
        this.showMobileDetailView = false;
      }
    },

    closeModal() {
      this.cleanupAdvancedEditorHandlers();
      this.showModal = false;
      this.loadError = "";
      this.activePresetRequestId = "";
      this.activePresetDetail = null;
      this.activeWorkspace = "all";
      this.activeGroup = "all";
      this.activePromptId = "";
      this.activeItemId = "";
      this.searchTerm = "";
      this.uiFilter = "all";
      this.showRightPanel = this.$store?.global?.deviceType !== "mobile";
      this.showMobileDetailView = false;
      this.showMobileSidebar = false;
      this.isSendingPresetToST = false;
      this.resetMobileHeaderState();
      this.refreshReaderCollections();
      clearActiveRuntimeContext("preset");
    },

    cleanupAdvancedEditorHandlers() {
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

    selectGroup(groupId) {
      this.activeGroup = groupId || "all";
      this.activeItemId = "";
      this.refreshReaderCollections();
      this.resetMobileHeaderState();
      if (this.$store?.global?.deviceType === "mobile") {
        this.showMobileDetailView = false;
        this.showMobileSidebar = false;
        this.showRightPanel = false;
      }
    },

    selectWorkspace(workspaceId) {
      this.activeWorkspace = workspaceId || "prompts";
      if (this.activeWorkspace === "prompts") {
        if (!PROMPT_UI_FILTER_IDS.has(this.uiFilter)) {
          this.uiFilter = "all";
        }
        this.activePromptId = this.promptFilteredItems[0]?.id || "";
      } else {
        if (!UI_FILTER_IDS.has(this.uiFilter)) {
          this.uiFilter = "all";
        }
        this.activeGroup = this.activeWorkspace;
        this.activeItemId = "";
      }
      this.refreshReaderCollections();
      this.resetMobileHeaderState();
      if (this.$store?.global?.deviceType === "mobile") {
        this.showMobileDetailView = false;
        this.showMobileSidebar = false;
        this.showRightPanel = false;
      } else {
        this.showRightPanel = !this.isScalarWorkspaceReader;
      }
    },

    selectItem(itemId) {
      if (this.isScalarWorkspaceReader) {
        this.showRightPanel = false;
        this.showMobileDetailView = false;
        return;
      }
      this.activeItemId = itemId || "";
      this.syncActiveReaderSelections();
      this.resetMobileHeaderState();
      if (this.$store?.global?.deviceType === "mobile") {
        this.openMobileDetailView();
      } else {
        this.showRightPanel = true;
      }
    },

    selectPrompt(itemId) {
      this.activeWorkspace = "prompts";
      this.activePromptId = itemId || "";
      this.refreshReaderCollections();
      this.resetMobileHeaderState();
      if (this.$store?.global?.deviceType === "mobile") {
        this.openMobileDetailView();
      } else {
        this.showRightPanel = true;
      }
    },

    refreshReaderCollections() {
      const query = normalizeText(this.searchTerm);
      this.promptItemsCache = this.readerItems.filter(
        (item) => item.type === "prompt",
      );
      this.orderedPromptItemsCache = [...this.promptItemsCache].sort(
        (left, right) => {
          const leftIndex = Number(
            left.prompt_meta?.order_index ?? Number.MAX_SAFE_INTEGER,
          );
          const rightIndex = Number(
            right.prompt_meta?.order_index ?? Number.MAX_SAFE_INTEGER,
          );
          if (leftIndex !== rightIndex) {
            return leftIndex - rightIndex;
          }
          return String(left.title || "").localeCompare(
            String(right.title || ""),
          );
        },
      );

      this.promptFilteredItemsCache = this.orderedPromptItemsCache.filter(
        (item) => {
          if (
            this.uiFilter === "enabled" &&
            item.prompt_meta?.is_enabled === false
          ) {
            return false;
          }
          if (
            this.uiFilter === "disabled" &&
            item.prompt_meta?.is_enabled !== false
          ) {
            return false;
          }
          if (this.uiFilter === "marker" && !item.prompt_meta?.is_marker) {
            return false;
          }

          if (!query) {
            return true;
          }

          const haystack = [
            item.title,
            item.summary,
            item.payload?.identifier,
            this.getPromptPreview(item),
            this.getPromptPositionLabel(item),
          ]
            .map(normalizeText)
            .filter(Boolean)
            .join(" ");
          return haystack.includes(query);
        },
      );

      this.filteredItemsCache = this.readerItems.filter((item) => {
        if (this.isScalarWorkspaceReader && item.group === "scalar_fields") {
          return false;
        }

        if (this.activeGroup !== "all" && item.group !== this.activeGroup) {
          return false;
        }

        if (this.uiFilter === "structured" && item.type !== "structured") {
          return false;
        }
        if (this.uiFilter === "extension" && item.type !== "extension") {
          return false;
        }

        if (!query) {
          return true;
        }

        const haystack = [
          item.title,
          item.summary,
          item.type,
          item.group,
          item.payload?.key,
          item.payload?.identifier,
          this.getItemValuePreview(item),
        ]
          .map(normalizeText)
          .filter(Boolean)
          .join(" ");
        return haystack.includes(query);
      });

      this.syncActiveReaderSelections();
    },

    syncActiveReaderSelections() {
      const visibleActiveItem = this.filteredItemsCache.find(
        (item) => item.id === this.activeItemId,
      );
      if (visibleActiveItem) {
        this.activeItemCache = visibleActiveItem;
      } else if (!this.filteredItemsCache.length) {
        this.activeItemCache = null;
      } else {
        this.activeItemCache = this.filteredItemsCache[0] || null;
      }
      this.activeItemId = this.activeItemCache?.id || "";

      this.activePromptItemCache =
        this.promptFilteredItemsCache.find(
          (item) => item.id === this.activePromptId,
        ) ||
        this.promptFilteredItemsCache[0] ||
        null;
      this.activePromptId = this.activePromptItemCache?.id || "";

      this.activeContextItemCache =
        this.isPromptWorkspaceReader && this.activeWorkspace === "prompts"
          ? this.activePromptItemCache
          : this.activeItemCache;

      const stats = this.readerView.stats || {};
      this.readerStatsCache = {
        total_count: this.isScalarWorkspaceReader
          ? this.scalarWorkspaceTotalVisibleFieldCount
          : Number(stats.total_count) || this.readerItems.length,
        visible_count: this.isScalarWorkspaceReader
          ? this.scalarWorkspaceVisibleFieldEntries.length
          : this.isPromptWorkspaceReader && this.activeWorkspace === "prompts"
            ? this.promptFilteredItemsCache.length
            : this.filteredItemsCache.length,
      };
    },

    getSourceLabel() {
      const source =
        this.activePresetDetail?.source || this.activePresetDetail?.type;
      return source === "global" ? "全局" : "资源";
    },

    canSendActivePresetToST() {
      const source_folder = String(this.activePresetDetail?.source_folder || "").trim();
      if (
        source_folder.includes("global-alt::") ||
        source_folder === "st_openai_preset_dir" ||
        String(this.activePresetDetail?.id || "").startsWith("global-alt::")
      ) {
        return false;
      }
      return this.activePresetDetail?.preset_kind === "openai";
    },

    canImportActivePresetVersion() {
      return this.activePresetDetail?.preset_kind === "openai";
    },

    triggerImportActivePresetVersion() {
      if (!this.canImportActivePresetVersion()) return;
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json,application/json";
      input.addEventListener("change", async () => {
        const file = input.files?.[0];
        if (!file) return;
        await this.importActivePresetVersion(file);
      }, { once: true });
      input.click();
    },

    async importActivePresetVersion(file) {
      if (!this.activePresetDetail?.id || !file) return;
      const formData = new FormData();
      formData.append("preset_id", this.activePresetDetail.id);
      formData.append("file", file, file.name || "imported.json");
      try {
        const res = await importPresetVersion(formData);
        if (!res?.success || !res?.preset) {
          this.$store.global.showToast(res?.msg || "导入失败", "error");
          return;
        }
        this.activePresetDetail = {
          ...this.activePresetDetail,
          ...res.preset,
        };
        this.$store.global.showToast("已导入并合并到当前预设");
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
      } catch (error) {
        this.$store.global.showToast(error?.message || "导入失败", "error");
      }
    },

    getActivePresetSendToSTTitle() {
      if (!this.canSendActivePresetToST()) {
        return "仅 OpenAI/对话补全预设可发送到 ST";
      }
      if (this.isSendingPresetToST) return "正在发送到 ST";
      if (Number(this.activePresetDetail?.last_sent_to_st || 0) > 0) {
        return `已发送到 ST：${new Date(this.activePresetDetail.last_sent_to_st * 1000).toLocaleString()}`;
      }
      return "发送到 ST（对话补全预设，同名将直接覆盖 ST 中现有预设）";
    },

    async sendActivePresetToST() {
      if (!this.activePresetDetail) return;
      if (!this.canSendActivePresetToST()) return;
      const presetId = String(this.activePresetDetail.id || "").trim();
      if (!presetId) return;
      if (isPresetSendToStPending(presetId)) {
        this.syncActivePresetSendingState(presetId);
        return;
      }

      setPresetSendToStPending(presetId, true);
      window.dispatchEvent(new CustomEvent("preset-send-to-st-pending", {
        detail: { id: presetId, sending: true },
      }));
      this.syncActivePresetSendingState(presetId);
      try {
        const res = await sendPresetToSillyTavern({ id: presetId });
        if (res?.success) {
          const sentAt = Number(res.last_sent_to_st || Date.now() / 1000);
          if (this.activePresetDetail?.id === presetId) {
            this.activePresetDetail = {
              ...this.activePresetDetail,
              last_sent_to_st: sentAt,
            };
          }
          window.dispatchEvent(new CustomEvent("preset-sent-to-st", {
            detail: {
              id: presetId,
              last_sent_to_st: sentAt,
            },
          }));
          this.$store.global.showToast("已发送到 ST", 1800, "card-send-to-st");
        } else {
          this.$store.global.showToast(res?.msg || "发送失败", 2600, "close");
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "发送失败", 2600, "close");
      } finally {
        setPresetSendToStPending(presetId, false);
        window.dispatchEvent(new CustomEvent("preset-send-to-st-finished", {
          detail: { id: presetId, sending: false },
        }));
        this.syncActivePresetSendingState();
      }
    },

    getItemGroupLabel(item) {
      return (
        this.readerGroups.find((group) => group.id === item?.group)?.label ||
        GROUP_FALLBACK_LABELS[item?.group] ||
        item?.group ||
        "未分组"
      );
    },

    getItemValuePreview(item) {
      if (!item) return "-";

      const payload = item.payload || {};
      if (item.type === "extension") {
        return this.formatValue(payload.value);
      }
      if (item.type === "field") {
        return this.formatValue(payload.value);
      }
      if (item.type === "structured") {
        const value = payload.value;
        if (Array.isArray(value)) {
          return `${value.length} 项`;
        }
        if (value && typeof value === "object") {
          return `${Object.keys(value).length} 个键`;
        }
      }

      return item.summary || this.formatValue(payload.value ?? payload);
    },

    getItemFullDetail(item) {
      if (!item) return "-";

      const payload = item.payload || {};
      if (
        item.type === "extension" ||
        item.type === "field" ||
        item.type === "structured"
      ) {
        return this.formatFullValue(payload.value);
      }

      return this.formatFullValue(payload.value ?? payload);
    },

    getItemBadge(item) {
      if (!item) return TYPE_LABELS.field;
      return TYPE_LABELS[item.type] || "条目";
    },

    getPromptPreview(item) {
      if (!item) return "-";
      if (item.prompt_meta?.is_marker) {
        return "";
      }
      const content = String(item.payload?.content || "").trim();
      return content ? this.formatValue(content) : "暂无提示词内容";
    },

    getPromptFullDetail(item) {
      if (!item) return "";
      if (item.prompt_meta?.is_marker) {
        return "";
      }
      return String(item.payload?.content || "").trim();
    },

    getPromptPositionLabel(item) {
      const position = Number(item?.payload?.injection_position ?? 0);
      if (position === 1) {
        const rawDepth = Number(item?.payload?.injection_depth ?? 4);
        const depth =
          Number.isInteger(rawDepth) && rawDepth >= 0 ? rawDepth : 4;
        return `聊天中 @ ${depth}`;
      }
      return PROMPT_POSITION_LABELS[position] || "相对";
    },

    isPromptChatInjection(item) {
      return Number(item?.payload?.injection_position ?? 0) === 1;
    },

    getPromptMarkerVisual(item) {
      const identifier = String(item?.payload?.identifier || "");
      return resolvePromptMarkerVisual(identifier);
    },

    getPromptMarkerIcon(item) {
      const visual = this.getPromptMarkerVisual(item);
      return buildPromptMarkerIcon(visual);
    },

    getScalarWorkspaceFieldValue(fieldKey) {
      const fieldConfig = this.scalarWorkspace?.field_map?.[fieldKey] || {};
      const rawData = this.activePresetDetail?.raw_data || {};
      const valueKey =
        fieldConfig.storage_key || fieldKey || fieldConfig.canonical_key || "";
      return rawData[valueKey];
    },

    getScalarWorkspaceFieldSummary(fieldKey) {
      return this.formatValue(this.getScalarWorkspaceFieldValue(fieldKey));
    },

    getScalarWorkspaceFieldDisplay(fieldKey) {
      return this.getScalarWorkspaceFieldSummary(fieldKey);
    },

    get editorProfile() {
      return this.activePresetDetail?.editor_profile || null;
    },

    get isMirroredProfileReader() {
      return Boolean(
        this.editorProfile?.id && this.editorProfile?.family === "st_mirror",
      );
    },

    get mirroredProfileSections() {
      return Array.isArray(this.editorProfile?.sections)
        ? this.editorProfile.sections
        : [];
    },

    get readerMirroredProfileSections() {
      return this.readerWorkspaceSections;
    },

    get readerWorkspaceSections() {
      const workspaceSections = Array.isArray(
        this.editorProfile?.workspace_sections,
      )
        ? this.editorProfile.workspace_sections
        : this.mirroredProfileSections;
      return workspaceSections.filter(
        (section) =>
          !HIDDEN_READER_MIRRORED_SECTION_IDS.has(section?.id) &&
          this.getProfileSectionFields(section?.id).length > 0,
      );
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
        (field) =>
          (field.section === sectionId || field.workspace_section === sectionId) &&
          this.isProfileFieldVisible(field) &&
          field.source_key !== null &&
          field.canonical_key !== "prompts" &&
          field.canonical_key !== "prompt_order" &&
          field.canonical_key !== "extensions",
      );
    },

    getProfileFieldRawValue(fieldKey) {
      if (!fieldKey) return undefined;
      const field = this.getProfileField(fieldKey);
      const storageKey = field?.storage_key || field?.canonical_key || fieldKey;
      const rawData = this.activePresetDetail?.raw_data;
      if (!rawData || typeof rawData !== "object") return undefined;
      return rawData[storageKey];
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

    getProfileFieldValue(fieldKey) {
      const field = this.getProfileField(fieldKey);
      if (!field) return null;
      const readerField = this.scalarWorkspace?.field_map?.[field.canonical_key];
      if (readerField && Object.prototype.hasOwnProperty.call(readerField, "reader_value")) {
        return readerField.reader_value;
      }
      const storageKey = field.storage_key || fieldKey;
      return this.activePresetDetail?.raw_data?.[storageKey];
    },

    getProfileFieldDisplay(fieldKey) {
      const field = this.getProfileField(fieldKey);
      if (!field) return "-";
      const value = this.getProfileFieldValue(fieldKey);
      if (field.sensitive) {
        return value === "已设置" || value === "未设置"
          ? value
          : value
            ? "已设置"
            : "未设置";
      }
      if (field.control === "select") {
        const valueKey = String(value ?? "");
        if (field.canonical_key === "chat_completion_source") {
          return PROFILE_SOURCE_LABELS[valueKey] || valueKey || "OpenAI";
        }
        return PROFILE_OPTION_LABELS[valueKey] || valueKey || "自动";
      }
      return this.formatValue(value);
    },

    isProfileFieldExpanded(field) {
      return [
        "textarea",
        "raw_json",
        "key_value_list",
        "sortable_string_list",
        "prompt_workspace",
      ].includes(field?.control);
    },

    isProfileFieldTextual(field) {
      return [
        "text",
        "password",
        "textarea",
        "number",
        "raw_json",
        "key_value_list",
        "sortable_string_list",
      ].includes(field?.control);
    },

    resolveProfileFieldMax(field) {
      const maxValue = field?.max;
      if (
        maxValue &&
        typeof maxValue === "object" &&
        maxValue.type === "dynamic"
      ) {
        const currentValue = Number(
          this.getProfileFieldValue(field.canonical_key),
        );
        const fallback = Number(maxValue.fallback ?? 4095);
        return Math.max(
          Number.isFinite(currentValue) ? currentValue : 0,
          fallback,
        );
      }
      const numeric = Number(maxValue);
      return Number.isFinite(numeric) ? numeric : null;
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

    openFullscreenEditor(options = {}) {
      if (!this.activePresetDetail) return;
      window.dispatchEvent(
        new CustomEvent("open-preset-editor", {
          detail: {
            presetId: this.activePresetDetail.id,
            activeNav: options.activeNav || "basic",
          },
        }),
      );
      this.closeModal();
    },

    async exportActivePreset() {
      const detail = this.activePresetDetail;
      if (!detail) return;

      try {
        await downloadFileFromApi({
          url: "/api/presets/export",
          body: { id: detail.id },
          defaultFilename: detail.filename || `${detail.name || "preset"}.json`,
          showToast: this.$store?.global?.showToast,
        });
      } catch (error) {
        this.$store.global.showToast(error.message || "导出失败", "error");
      }
    },

    openAdvancedExtensions() {
      if (!this.activePresetDetail) return;

      this.cleanupAdvancedEditorHandlers();

      const extensions = this.activePresetDetail.extensions || {};
      const editingData = {
        extensions: normalizePresetExtensionsForEditor(extensions),
        editorCommitMode: "buffered",
        showPersistButton: true,
      };

      window.dispatchEvent(
        new CustomEvent("open-advanced-editor", {
          detail: editingData,
        }),
      );

      const applyHandler = async () => {
        this.cleanupAdvancedEditorHandlers();
        this.activePresetDetail.extensions = JSON.parse(
          JSON.stringify(editingData.extensions),
        );
      };

      const persistHandler = async () => {
        this.cleanupAdvancedEditorHandlers();
        const persistedExtensions = normalizePresetExtensionsForSave(
          editingData.extensions,
        );
        this.activePresetDetail.extensions = JSON.parse(
          JSON.stringify(persistedExtensions),
        );
        const didSave = await this.savePresetExtensions(
          this.activePresetDetail.extensions,
        );
        if (didSave) {
          window.dispatchEvent(new CustomEvent("advanced-editor-close"));
        }
      };

      this.pendingAdvancedEditorApplyHandler = applyHandler;
      this.pendingAdvancedEditorPersistHandler = persistHandler;
      window.addEventListener("advanced-editor-apply", applyHandler);
      window.addEventListener("advanced-editor-persist", persistHandler);
    },

    async savePresetExtensions(extensions) {
      if (!this.activePresetDetail) return;
      try {
        const res = await apiSavePresetExtensions({
          id: this.activePresetDetail.id,
          extensions: normalizePresetExtensionsForSave(extensions),
        });
        if (!res.success) {
          this.$store.global.showToast(res.msg || "保存失败", "error");
          return false;
        }
        this.$store.global.showToast("扩展已保存");
        await this.openPreset({ id: this.activePresetDetail.id });
        return true;
      } catch (error) {
        console.error("Failed to save preset extensions:", error);
        this.$store.global.showToast("保存失败", "error");
        return false;
      }
    },

    formatValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "boolean") return value ? "是" : "否";
      if (typeof value === "number") {
        return Number.isInteger(value)
          ? String(value)
          : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
      }
      if (typeof value === "object") {
        try {
          const serialized = JSON.stringify(value, null, 2);
          return serialized.length > 240
            ? `${serialized.slice(0, 240)}...`
            : serialized;
        } catch (error) {
          return String(value);
        }
      }
      const text = String(value);
      return text.length > 240 ? `${text.slice(0, 240)}...` : text;
    },

    formatFullValue(value) {
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "boolean") return value ? "是" : "否";
      if (typeof value === "number") {
        return Number.isInteger(value)
          ? String(value)
          : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
      }
      if (typeof value === "object") {
        try {
          return JSON.stringify(value, null, 2);
        } catch (error) {
          return String(value);
        }
      }
      return String(value);
    },

    formatDate(ts) {
      return formatDate(ts, { includeYear: true });
    },

    formatSize(bytes) {
      const size = Number(bytes) || 0;
      if (!size) return "0 B";
      if (size < 1024) return `${size} B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${(size / 1024 / 1024).toFixed(1)} MB`;
    },

    async copyText(value, label = "内容") {
      try {
        await navigator.clipboard.writeText(String(value ?? ""));
        this.$store.global.showToast(`${label}已复制`);
      } catch (error) {
        console.error(error);
        this.$store.global.showToast(`复制${label}失败`, "error");
      }
    },
  };
}
