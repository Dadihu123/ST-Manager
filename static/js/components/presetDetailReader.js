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
  scalar_fields: "基础字段",
  structured_objects: "结构化对象",
};

const PROMPT_POSITION_LABELS = {
  0: "相对",
  1: "聊天中",
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
    presetMobileHeaderHidden: false,
    presetLastScrollTop: 0,
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
        this.updatePresetLayoutMetrics();
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
        this.activeWorkspace === "scalar_fields" &&
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
      return fieldEntries.filter(([fieldKey]) => !hiddenFields.has(fieldKey))
        .length;
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

    revealMobileHeader() {
      const previousHidden = this.presetMobileHeaderHidden;
      this.presetMobileHeaderHidden = false;
      this.presetLastScrollTop = 0;
      if (previousHidden) {
        this.updatePresetLayoutMetrics();
      }
    },

    resetMobileHeaderState() {
      this.showMobileMoreMenu = false;
      this.presetMobileHeaderHidden = false;
      this.presetLastScrollTop = 0;
    },

    toggleMobileSidebar() {
      this.revealMobileHeader();
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = !this.showMobileSidebar;
    },

    toggleMobileRightPanel() {
      this.revealMobileHeader();
      this.showMobileMoreMenu = false;
      this.showRightPanel = !this.showRightPanel;
    },

    openMobileDetailView() {
      this.revealMobileHeader();
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobileDetailView = true;
      this.showRightPanel = false;
    },

    closeMobileDetailView() {
      this.revealMobileHeader();
      this.showMobileMoreMenu = false;
      this.showMobileSidebar = false;
      this.showMobileDetailView = false;
      this.showRightPanel = false;
    },

    toggleMobileMoreMenu() {
      this.revealMobileHeader();
      this.showMobileMoreMenu = !this.showMobileMoreMenu;
    },

    updatePresetLayoutMetrics() {
      const applyMetrics = () => {
        if (typeof document === "undefined") return;

        const root = document.querySelector(".preset-reader-modal");
        if (!root) return;

        const header = root.querySelector(".preset-reader-mobile-header");
        const headerHeight = header
          ? Math.ceil(header.getBoundingClientRect().height)
          : 0;
        const effectiveHeaderHeight =
          this.$store?.global?.deviceType === "mobile" &&
          this.presetMobileHeaderHidden
            ? 0
            : headerHeight;
        root.style.setProperty(
          "--preset-reader-header-height",
          `${effectiveHeaderHeight}px`,
        );
      };

      if (typeof this.$nextTick === "function") {
        this.$nextTick(() => {
          applyMetrics();
        });
        return;
      }

      applyMetrics();
    },

    syncPresetMobileHeaderVisibility(container) {
      if (
        this.$store?.global?.deviceType !== "mobile" ||
        typeof Element === "undefined" ||
        !(container instanceof Element) ||
        this.showMobileSidebar ||
        this.showRightPanel ||
        this.showMobileMoreMenu
      ) {
        return;
      }

      const previousHidden = this.presetMobileHeaderHidden;
      const nextTop = Math.max(0, Number(container.scrollTop || 0));
      const delta = nextTop - Number(this.presetLastScrollTop || 0);

      if (nextTop <= 24 || delta < -14) {
        this.presetMobileHeaderHidden = false;
      } else if (delta > 18 && nextTop > 72) {
        this.presetMobileHeaderHidden = true;
      }

      this.presetLastScrollTop = nextTop;
      if (previousHidden !== this.presetMobileHeaderHidden) {
        this.updatePresetLayoutMetrics();
      }
    },

    handleMobileContentScroll(event) {
      const container = event?.target;
      if (typeof Element !== "undefined" && container instanceof Element) {
        this.syncPresetMobileHeaderVisibility(container);
      }
    },

    async openPreset(item) {
      const presetId =
        item?.entry_type === "family" && item?.default_version_id
          ? item.default_version_id
          : item?.id;
      if (!presetId) return;
      this.isLoading = true;
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
      this.updatePresetLayoutMetrics();

      try {
        const res = await getPresetDetail(presetId);
        if (!res.success) {
          this.$store.global.showToast(res.msg || "获取详情失败", "error");
          this.closeModal();
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
        this.updatePresetLayoutMetrics();
      } catch (error) {
        console.error("Failed to load preset detail:", error);
        this.$store.global.showToast("获取详情失败", "error");
        this.closeModal();
      } finally {
        this.isLoading = false;
      }
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
      this.updatePresetLayoutMetrics();
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
      this.updatePresetLayoutMetrics();
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
      this.updatePresetLayoutMetrics();
      if (this.$store?.global?.deviceType === "mobile") {
        this.showMobileDetailView = false;
        this.showMobileSidebar = false;
        this.showRightPanel = false;
      } else {
        this.showRightPanel = true;
      }
    },

    selectItem(itemId) {
      this.activeItemId = itemId || "";
      this.syncActiveReaderSelections();
      this.resetMobileHeaderState();
      this.updatePresetLayoutMetrics();
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
      this.updatePresetLayoutMetrics();
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
          this.$store.global.showToast("已发送到 ST", 1800, "card-send");
        } else {
          this.$store.global.showToast(res?.msg || "发送失败", 2600, "context-close");
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "发送失败", 2600, "context-close");
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
      return this.mirroredProfileSections.filter(
        (section) => !HIDDEN_READER_MIRRORED_SECTION_IDS.has(section?.id),
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
        (field) => field.section === sectionId,
      );
    },

    getProfileFieldValue(fieldKey) {
      const field = this.getProfileField(fieldKey);
      if (!field) return null;
      const storageKey = field.storage_key || fieldKey;
      return this.activePresetDetail?.raw_data?.[storageKey];
    },

    getProfileFieldDisplay(fieldKey) {
      return this.formatValue(this.getProfileFieldValue(fieldKey));
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
        extensions: {
          regex_scripts: Array.isArray(extensions.regex_scripts)
            ? JSON.parse(JSON.stringify(extensions.regex_scripts))
            : [],
          tavern_helper: JSON.parse(
            JSON.stringify(extensions.tavern_helper || { scripts: [] }),
          ),
        },
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
        this.activePresetDetail.extensions = JSON.parse(
          JSON.stringify(editingData.extensions),
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
          extensions,
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
