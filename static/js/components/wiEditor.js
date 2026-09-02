/**
 * static/js/components/wiEditor.js
 * 全屏世界书编辑器组件
 */

import {
  getWorldInfoDetail,
  saveWorldInfo,
  saveWorldInfoNote,
  listWiEntryHistory,
  clipboardList,
  clipboardAdd,
  clipboardDelete,
  clipboardClear,
  clipboardReorder,
} from "../api/wi.js";
import { getCardDetail, updateCard } from "../api/card.js";
import {
  createSnapshot as apiCreateSnapshot,
  cleanupInitBackups as apiCleanupInitBackups,
} from "../api/system.js";
import {
  normalizeWiBook,
  toStV3Worldbook,
  getCleanedV3Data,
  updateWiKeys,
} from "../utils/data.js";
import { createAutoSaver } from "../utils/autoSave.js";
import { wiHelpers } from "../utils/wiHelpers.js";
import {
  formatWiKeys,
  estimateTokens,
  getTotalWiTokens,
  getWiTokenClass,
} from "../utils/format.js";
import {
  getNextWiDisplayIndex,
  WI_SORT_OPTIONS,
  getWiSortLabel,
  loadWiSortMode,
  setWiCustomDisplayIndexes,
} from "../utils/wiSort.js";

export default function wiEditor() {
  const autoSaver = createAutoSaver();
  return {
    // === 本地状态 ===
    showFullScreenWI: false,
    showWiList: true,
    showWiSettings: true,
    // 三栏工作台的显式视图状态。桌面端保持三栏，移动端由底部导航切换面板。
    editorPane: "content",
    showLeftList: true,
    showRightPanel: true,
    rightTab: "settings",
    isLoading: false,
    isSaving: false,
    editorSaveState: "idle", // idle | saving | saved | error
    editorSaveMessage: "尚未保存",
    editorLastSavedAt: "",
    editorBaselineJson: null,
    openWorldInfoEditorRequestToken: 0,
    openWorldInfoFileRequestToken: 0,

    // 编辑器核心数据
    editingData: {
      id: null,
      char_name: "",
      character_book: { name: "", entries: [] },
      extensions: { regex_scripts: [], tavern_helper: [] },
      source_revision: "",
    },

    // 当前编辑的文件元数据 (用于保存路径)
    editingWiFile: null,

    // 索引与视图控制
    currentWiIndex: 0,
    currentWiEntryKey: "",
    entryUidField: "st_manager_uid",
    wiSortMode: loadWiSortMode(),
    wiSortOptions: WI_SORT_OPTIONS,
    showWiSortMenu: false,
    wiEntryFilterQuery: "",
    wiEditorActionRailMode: "expanded",
    wiEditorActionRailResizeObserver: null,
    wiEditorActionRailSyncFrame: null,
    initialSnapshotChecked: false,
    initialSnapshotInitPromise: null,
    // 内嵌世界书进入编辑器时的归一化基线。关闭时只把真实改动同步回角色卡，
    // 避免 normalizeWiBook/_ensureEntryUids 产生的前端字段被误判为卡片修改。
    embeddedWorldbookBaselineJson: null,
    // 最近一次已直接写入角色卡文件的世界书，用于关闭时重置宿主卡片基线。
    embeddedWorldbookLastSavedJson: null,

    // 帮助模态框
    showHelpModal: false,

    // 条目历史回滚
    showEntryHistoryModal: false,
    isEntryHistoryLoading: false,
    entryHistoryItems: [],
    entryHistoryTargetUid: "",
    entryHistoryVersions: [],
    entryHistorySelection: { left: null, right: null },
    entryHistoryDiff: { left: "", right: "" },

    // 查找与替换
    showFindReplaceModal: false,
    findReplaceQuery: "",
    findReplaceReplacement: "",
    findReplaceScope: "current", // current | all
    findReplaceCaseSensitive: false,
    findReplaceExcludeText: "",
    findReplaceLastHit: null,
    findReplacePanelX: 0,
    findReplacePanelY: 0,
    findReplaceDragActive: false,
    findReplaceDragOffsetX: 0,
    findReplaceDragOffsetY: 0,

    // JSONL 标签导入
    showTaggedImportModal: false,
    taggedImportDragOver: false,
    taggedImportPendingFile: null,
    taggedImportPendingFileName: "",
    taggedImportIgnoreText: "thinking\nrecap\ncontent\ndetails\nsummary",

    // === 剪切板状态 ===
    showWiClipboard: false,
    wiClipboardItems: [],
    wiClipboardOverwriteMode: false,
    clipboardPendingEntry: null, // 等待覆写的条目
    isEditingClipboard: false, // 是否正在编辑剪切板内容
    currentClipboardIndex: -1,

    // 拖拽状态
    wiDraggingIndex: null,
    wiDraggingEntryKey: "",

    formatWiKeys,
    estimateTokens,
    getWiTokenClass,
    getWiSortLabel,
    updateWiKeys,
    ...wiHelpers,

    get activeCard() {
      return this.editingData;
    },

    getEditorSourceLabel() {
      const type = this.editingWiFile?.type || this.editingWiFile?.source_type;
      if (type === "embedded") return "角色卡内嵌";
      if (type === "resource") return "资源世界书";
      if (type === "global") return "全局世界书";
      return "世界书编辑器";
    },

    getEditorSourceDescription() {
      const type = this.editingWiFile?.type || this.editingWiFile?.source_type;
      if (type === "embedded") {
        return this.editingData?.char_name
          ? `${this.editingData.char_name} · 随角色卡保存`
          : "随角色卡保存";
      }
      if (type === "resource") return "资源目录中的独立文件";
      if (type === "global") return "应用共享的独立文件";
      return "等待载入来源";
    },

    getEditorVisibleEntryCount() {
      return typeof this.getFilteredSortedWIEntries === "function"
        ? this.getFilteredSortedWIEntries().length
        : 0;
    },

    getEditorTotalEntryCount() {
      return typeof this.getSortedWIEntries === "function"
        ? this.getSortedWIEntries().length
        : 0;
    },

    _serializeEditorBookForComparison(book) {
      const transientFields = new Set([
        "matchWholeWordsState",
        "caseSensitiveState",
        "useGroupScoringState",
      ]);

      return JSON.stringify(book, (key, value) => {
        return transientFields.has(key) ? undefined : value;
      });
    },

    hasEditorUnsavedChanges() {
      if (!this.editingData?.character_book || !this.editorBaselineJson) {
        return false;
      }

      try {
        return (
          this._serializeEditorBookForComparison(this.editingData.character_book) !==
          this.editorBaselineJson
        );
      } catch (e) {
        console.warn("Unable to compare worldbook editor state:", e);
        return true;
      }
    },

    getEditorSaveStatusLabel() {
      if (this.isLoading) return "正在载入";
      if (this.isSaving || this.editorSaveState === "saving") return "正在保存";
      if (this.hasEditorUnsavedChanges()) return "有未保存修改";
      if (this.editorSaveState === "error") return this.editorSaveMessage || "保存失败";
      if (this.editorSaveState === "saved" && this.editorLastSavedAt) {
        return `已保存 ${this.editorLastSavedAt}`;
      }
      return this.editorSaveMessage || "已载入";
    },

    getEditorSaveStatusClass() {
      if (this.isSaving || this.editorSaveState === "saving") return "is-saving";
      if (this.editorSaveState === "error") return "is-error";
      if (this.hasEditorUnsavedChanges()) return "is-dirty";
      if (this.editorSaveState === "saved") return "is-saved";
      return "is-idle";
    },

    _setEditorBaseline() {
      if (!this.editingData?.character_book) {
        this.editorBaselineJson = null;
        return;
      }

      try {
        this.editorBaselineJson = this._serializeEditorBookForComparison(
          this.editingData.character_book,
        );
      } catch (e) {
        this.editorBaselineJson = null;
        console.warn("Unable to store worldbook editor baseline:", e);
      }
    },

    _markEditorSaveStarted(message = "正在保存") {
      this.editorSaveState = "saving";
      this.editorSaveMessage = message;
    },

    _markEditorSaveSuccess(message = "已保存") {
      this.editorSaveState = "saved";
      this.editorSaveMessage = message;
      this.editorLastSavedAt = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      this._setEditorBaseline();
    },

    _markEditorSaveError(message = "保存失败") {
      this.editorSaveState = "error";
      this.editorSaveMessage = message;
    },

    isEditorMobileViewport() {
      return (
        this.$store?.global?.deviceType === "mobile" ||
        (typeof window !== "undefined" &&
          typeof window.matchMedia === "function" &&
          window.matchMedia("(max-width: 900px)").matches)
      );
    },

    _scheduleEditorActionRailSync() {
      if (typeof window === "undefined") return;
      if (this.wiEditorActionRailSyncFrame !== null) {
        window.cancelAnimationFrame?.(this.wiEditorActionRailSyncFrame);
      }
      const schedule = window.requestAnimationFrame || ((callback) => callback());
      this.wiEditorActionRailSyncFrame = schedule(() => {
        this.wiEditorActionRailSyncFrame = null;
        this._syncEditorActionRail();
      });
    },

    _syncEditorActionRail() {
      if (!this.showFullScreenWI || typeof document === "undefined") return;

      const root = this._getEditorRootEl?.();
      const actions = root?.querySelector?.(".wi-editor-actions");
      if (!actions || actions.offsetParent === null) return;

      // 先临时恢复完整工具组，再读取实际的 scrollWidth。这样折叠由
      // “展开后是否超出当前工具栏”决定，而不是由固定视口断点决定。
      const previousMode = actions.getAttribute("data-action-density");
      actions.setAttribute("data-action-density", "expanded");
      const actionRect = actions.getBoundingClientRect();
      const expandedContentRight = Math.max(
        actionRect.right,
        ...Array.from(actions.children).map((element) =>
          element.getBoundingClientRect().right,
        ),
      );
      const expandedOverflow =
        actions.scrollWidth > actions.clientWidth + 1 ||
        expandedContentRight > actionRect.right + 1;
      if (previousMode) {
        actions.setAttribute("data-action-density", previousMode);
      } else {
        actions.removeAttribute("data-action-density");
      }

      const nextMode = this.isEditorMobileViewport()
        ? "compact"
        : expandedOverflow
          ? "compact"
          : "expanded";
      if (nextMode !== this.wiEditorActionRailMode) {
        this.wiEditorActionRailMode = nextMode;
      }
    },

    _initEditorActionRail() {
      const root = this._getEditorRootEl?.();
      const header = root?.querySelector?.(".wi-editor-header");
      const actions = root?.querySelector?.(".wi-editor-actions");
      const heading = root?.querySelector?.(".wi-editor-heading");
      if (!header || !actions) return;

      this.wiEditorActionRailResizeObserver?.disconnect?.();
      if (typeof ResizeObserver === "function") {
        this.wiEditorActionRailResizeObserver = new ResizeObserver(() => {
          this._scheduleEditorActionRailSync();
        });
        [header, actions, heading].filter(Boolean).forEach((element) => {
          this.wiEditorActionRailResizeObserver.observe(element);
        });
      }
      this._scheduleEditorActionRailSync();
    },

    _destroyEditorActionRail() {
      this.wiEditorActionRailResizeObserver?.disconnect?.();
      this.wiEditorActionRailResizeObserver = null;
      if (
        typeof window !== "undefined" &&
        this.wiEditorActionRailSyncFrame !== null
      ) {
        window.cancelAnimationFrame?.(this.wiEditorActionRailSyncFrame);
      }
      this.wiEditorActionRailSyncFrame = null;
      this.wiEditorActionRailMode = "expanded";
    },

    setEditorPane(pane) {
      const nextPane = ["list", "content", "inspector"].includes(pane)
        ? pane
        : "content";
      this.editorPane = nextPane;
      if (nextPane === "list") {
        this.showLeftList = true;
        this.showRightPanel = false;
      } else if (nextPane === "inspector") {
        this.showLeftList = false;
        this.showRightPanel = true;
      } else if (this.isEditorMobileViewport()) {
        this.showLeftList = false;
        this.showRightPanel = false;
      }

      this.$nextTick(() => {
        if (nextPane === "list") {
          this._getEditorRootEl()?.querySelector("#wi-entry-filter-input")?.focus();
        } else if (nextPane === "content") {
          this._getContentTextareaEl()?.focus();
        }
      });
    },

    toggleEditorList() {
      this.showLeftList = !this.showLeftList;
      if (this.showLeftList) this.editorPane = "list";
    },

    toggleEditorInspector() {
      this.showRightPanel = !this.showRightPanel;
      if (this.showRightPanel) this.editorPane = "inspector";
    },

    requestCloseEditor() {
      if (this.isLoading) return;
      if (
        this.hasEditorUnsavedChanges() &&
        !confirm("当前世界书有未保存的修改，确定要关闭编辑器吗？")
      ) {
        return;
      }
      this.showFullScreenWI = false;
    },

    selectAdjacentWiEntry(step) {
      if (this.isEditingClipboard) return;
      const entries = this.getSortedWIEntries();
      if (!entries.length) return;
      const current = this.activeEditorEntry;
      const currentIndex = entries.indexOf(current);
      const nextIndex =
        currentIndex < 0
          ? 0
          : (currentIndex + step + entries.length) % entries.length;
      this.selectMainWiItem(entries[nextIndex], nextIndex);
      this.$nextTick(() => {
        const listItem = Array.from(
          this._getEditorRootEl()?.querySelectorAll(".wi-list-item") || [],
        ).find((item) => item.dataset.entryKey === this.currentWiEntryKey);
        listItem?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      });
    },

    getWiEntrySearchText(entry) {
      if (!entry || typeof entry !== "object") return "";
      return [
        entry.comment,
        entry.title,
        entry.content,
        entry.keys,
        entry.secondary_keys,
        entry.group,
        entry.outletName,
        entry.automationId,
      ]
        .map((value) =>
          Array.isArray(value) ? value.join(" ") : String(value ?? ""),
        )
        .join("\n");
    },

    isWiEntryFilterActive() {
      return String(this.wiEntryFilterQuery ?? "").trim().length > 0;
    },

    getFilteredSortedWIEntries() {
      const entries = this.getSortedWIEntries();
      const query = String(this.wiEntryFilterQuery ?? "")
        .trim()
        .toLowerCase();
      if (!query) return entries;

      return entries.filter((entry) =>
        this.getWiEntrySearchText(entry).toLowerCase().includes(query),
      );
    },

    openLargeEditor(
      field,
      title,
      isArray = false,
      index = 0,
      editingData = this.editingData,
    ) {
      window.dispatchEvent(
        new CustomEvent("open-large-editor", {
          detail: {
            field,
            title,
            isArray,
            index,
            editingData,
          },
        }),
      );
    },

    openMarkdownView(content) {
      if (!content) return;
      window.dispatchEvent(
        new CustomEvent("open-markdown-view", {
          detail: content,
        }),
      );
    },

    getEditorPositionSelectValue(entry) {
      const position = Number(entry?.position ?? 0);
      if (position !== 4) {
        return String(Number.isFinite(position) ? position : 0);
      }

      const role = Number(entry?.role);
      if (role === 1) return "4:1";
      if (role === 2) return "4:2";
      return "4:0";
    },

    updateEditorPositionFromSelect(entry, rawValue) {
      if (!entry || typeof entry !== "object") return;

      const value = String(rawValue ?? "").trim();
      if (value === "4:1") {
        entry.position = 4;
        entry.role = 1;
        return;
      }
      if (value === "4:2") {
        entry.position = 4;
        entry.role = 2;
        return;
      }
      if (value === "4:0") {
        entry.position = 4;
        entry.role = 0;
        return;
      }

      const position = Number(value);
      entry.position = Number.isFinite(position) ? position : 0;
      entry.role = null;
    },

    getDelayUntilRecursionEnabled(entry) {
      return !!entry?.delayUntilRecursion;
    },

    getDelayUntilRecursionLevel(entry) {
      const value = entry?.delayUntilRecursion;
      return typeof value === "number" ? value : "";
    },

    setDelayUntilRecursionEnabled(entry, enabled) {
      if (!entry || typeof entry !== "object") return;
      if (!enabled) {
        entry.delayUntilRecursion = false;
        return;
      }

      const current = entry.delayUntilRecursion;
      entry.delayUntilRecursion = typeof current === "number" ? current : true;
    },

    setDelayUntilRecursionLevel(entry, rawValue) {
      if (!entry || typeof entry !== "object") return;

      const content = String(rawValue ?? "").trim();
      if (content === "") {
        entry.delayUntilRecursion = this.getDelayUntilRecursionEnabled(entry)
          ? true
          : false;
        return;
      }

      const value = Number(content);
      entry.delayUntilRecursion = Number.isFinite(value) ? value : false;
    },

    getTriStateSelectValue(value) {
      if (value === true) return "true";
      if (value === false) return "false";
      return "null";
    },

    setTriStateValue(entry, key, rawValue) {
      if (!entry || typeof entry !== "object" || !key) return;

      const value = String(rawValue ?? "null").trim();
      if (value === "true") {
        entry[key] = true;
        return;
      }
      if (value === "false") {
        entry[key] = false;
        return;
      }
      entry[key] = null;
    },

    getOptionalNumberInputValue(value) {
      return value === null || value === undefined ? "" : value;
    },

    setOptionalNumberField(entry, key, rawValue) {
      if (!entry || typeof entry !== "object" || !key) return;

      const content = String(rawValue ?? "").trim();
      if (content === "") {
        entry[key] = null;
        return;
      }

      const value = Number(content);
      entry[key] = Number.isFinite(value) ? value : null;
    },

    setMultiSelectField(entry, key, selectEl) {
      if (!entry || typeof entry !== "object" || !key || !selectEl) return;
      entry[key] = Array.from(
        selectEl.selectedOptions || [],
        (option) => option.value,
      );
    },

    ensureCharacterFilterShape(entry) {
      if (!entry || typeof entry !== "object") return null;
      if (
        !entry.characterFilter ||
        typeof entry.characterFilter !== "object" ||
        Array.isArray(entry.characterFilter)
      ) {
        entry.characterFilter = {
          isExclude: false,
          names: [],
          tags: [],
        };
      }
      entry.characterFilter.isExclude = !!entry.characterFilter.isExclude;
      entry.characterFilter.names = Array.isArray(entry.characterFilter.names)
        ? entry.characterFilter.names
        : [];
      entry.characterFilter.tags = Array.isArray(entry.characterFilter.tags)
        ? entry.characterFilter.tags
        : [];
      return entry.characterFilter;
    },

    toggleCharacterFilterExclude(entry, checked) {
      if (!entry || typeof entry !== "object") return;
      if (checked) {
        const filter = this.ensureCharacterFilterShape(entry);
        filter.isExclude = true;
        return;
      }

      if (
        !entry.characterFilter ||
        typeof entry.characterFilter !== "object" ||
        Array.isArray(entry.characterFilter)
      ) {
        return;
      }

      const names = Array.isArray(entry.characterFilter.names)
        ? entry.characterFilter.names
        : [];
      const tags = Array.isArray(entry.characterFilter.tags)
        ? entry.characterFilter.tags
        : [];
      if (names.length === 0 && tags.length === 0) {
        delete entry.characterFilter;
        return;
      }

      entry.characterFilter.isExclude = false;
    },

    getCharacterFilterCsv(entry, key) {
      const values = entry?.characterFilter?.[key];
      return Array.isArray(values) ? values.join(", ") : "";
    },

    setCharacterFilterCsv(entry, key, rawValue) {
      if (
        !entry ||
        typeof entry !== "object" ||
        !["names", "tags"].includes(key)
      )
        return;

      const filter = this.ensureCharacterFilterShape(entry);
      const values = String(rawValue ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);

      filter[key] = values;

      if (
        !filter.isExclude &&
        filter.names.length === 0 &&
        filter.tags.length === 0
      ) {
        delete entry.characterFilter;
      }
    },

    // === 初始化 ===
    init() {
      // 监听打开编辑器事件
      window.addEventListener("open-wi-editor", (e) => {
        this.openWorldInfoEditor(e.detail);
      });

      // 监听打开文件事件 (通常用于独立文件)
      window.addEventListener("open-wi-file", (e) => {
        this.openWorldInfoFile(e.detail);
      });

      // 监听时光机恢复，确保编辑器内存与磁盘恢复结果同步
      window.addEventListener("wi-restore-applied", (e) => {
        this._handleRestoreApplied(e?.detail || {});
      });

      window.addEventListener("wi-note-updated", (e) => {
        const detail = e.detail || {};
        if (
          !detail?.id ||
          !this.editingWiFile ||
          this.editingWiFile.id !== detail.id
        )
          return;
        this.editingWiFile = {
          ...this.editingWiFile,
          ui_summary: detail.ui_summary || "",
        };
        this.editingData.ui_summary = detail.ui_summary || "";
      });

      // 监听关闭
      this.$watch("showFullScreenWI", (val) => {
        if (!val) {
          this._destroyEditorActionRail();
          // 如果是内嵌模式，触发关闭事件同步数据回父组件
          if (
            this.editingWiFile &&
            this.editingWiFile.type === "embedded" &&
            this.editingData &&
            this.editingData.character_book
          ) {
            const currentWorldbookJson = JSON.stringify(
              this.editingData.character_book,
            );
            const currentWorldbookComparableJson =
              this._serializeEditorBookForComparison(
                this.editingData.character_book,
              );
            const hasWorldbookChanges =
              !this.embeddedWorldbookBaselineJson ||
              currentWorldbookComparableJson !==
                this.embeddedWorldbookBaselineJson;
            const hasSavedWorldbook =
              this.embeddedWorldbookLastSavedJson !== null;

            const closeDetail = {
              card_id: this.editingData.id || this.editingWiFile.card_id,
              changed: hasWorldbookChanges,
            };
            if (hasWorldbookChanges || hasSavedWorldbook) {
              closeDetail.character_book = JSON.parse(currentWorldbookJson);
            }
            if (hasSavedWorldbook) {
              closeDetail.persisted_character_book = JSON.parse(
                this.embeddedWorldbookLastSavedJson,
              );
            }
            window.dispatchEvent(
              new CustomEvent("wi-editor-closed", {
                detail: closeDetail,
              }),
            );
          }
          this.embeddedWorldbookBaselineJson = null;
          this.embeddedWorldbookLastSavedJson = null;
          this.editorBaselineJson = null;
          this.editorSaveState = "idle";
          this.editorSaveMessage = "尚未保存";
          this.editorLastSavedAt = "";
          this._cleanupInitBackupsOnExit();
          autoSaver.stop();
          this.isEditingClipboard = false;
          this.currentWiIndex = 0;
          this.currentWiEntryKey = "";
          this.wiEntryFilterQuery = "";
          this.initialSnapshotChecked = false;
          this.initialSnapshotInitPromise = null;
          this.showFindReplaceModal = false;
          this.findReplaceLastHit = null;
          this._detachFindReplaceDragListeners();
          this.showTaggedImportModal = false;
          this.taggedImportDragOver = false;
          this.taggedImportPendingFile = null;
          this.taggedImportPendingFileName = "";
          this.showLeftList = false;
          this.showRightPanel = false;
          this.editorPane = "content";
        } else {
          this.$nextTick(() => this._initEditorActionRail());
        }
      });

      window.addEventListener("keydown", (e) => {
        if (!this.showFullScreenWI) return;

        // Ctrl/Cmd + H: 打开查找替换
        if (
          (e.ctrlKey || e.metaKey) &&
          String(e.key || "").toLowerCase() === "h"
        ) {
          e.preventDefault();
          e.stopPropagation();
          this.openFindReplaceModal();
          return;
        }

        // Ctrl/Cmd + S 保存当前编辑，Ctrl/Cmd + Shift + S 保存整本并生成快照。
        if (
          (e.ctrlKey || e.metaKey) &&
          String(e.key || "").toLowerCase() === "s"
        ) {
          e.preventDefault();
          e.stopPropagation();
          if (e.shiftKey) this.saveWholeWorldbook();
          else if (this.editingWiFile?.type === "embedded") this.saveChanges();
          else this.saveWiFileChanges();
          return;
        }

        // Alt + 上下方向键在条目间移动，保留方向键在表单中的原生行为。
        if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
          e.preventDefault();
          e.stopPropagation();
          this.selectAdjacentWiEntry(e.key === "ArrowUp" ? -1 : 1);
          return;
        }

        if (e.key === "Escape" && this.showFindReplaceModal) {
          e.preventDefault();
          this.closeFindReplaceModal();
          return;
        }

        if (e.key === "Escape" && this.showTaggedImportModal) {
          e.preventDefault();
          this.closeTaggedImportModal();
          return;
        }

        if (e.key === "Escape" && this.showEntryHistoryModal) {
          e.preventDefault();
          this.showEntryHistoryModal = false;
          return;
        }

        if (e.key === "Escape" && this.showHelpModal) {
          e.preventDefault();
          this.showHelpModal = false;
          return;
        }

        if (e.key === "Escape") {
          e.preventDefault();
          this.requestCloseEditor();
        }
      });
    },

    openRollback() {
      this.handleOpenRollback(this.editingWiFile, this.editingData);
    },

    _getEditorRootEl() {
      return document.querySelector(".detail-wi-full-screen");
    },

    _getContentTextareaEl() {
      const root = this._getEditorRootEl();
      if (!root) return null;
      return root.querySelector('textarea[x-ref="wiContentTextarea"]');
    },

    _scrollFindHitIntoView(textarea, start, length) {
      if (
        !textarea ||
        typeof document === "undefined" ||
        typeof window === "undefined" ||
        typeof document.createElement !== "function" ||
        typeof window.getComputedStyle !== "function"
      ) {
        return;
      }

      const host = document.body || document.documentElement;
      if (!host || typeof host.appendChild !== "function") return;

      const value = String(textarea.value ?? "");
      const rawStart = Number(start);
      const rawLength = Number(length);
      const safeStart = Number.isFinite(rawStart)
        ? Math.max(0, Math.min(Math.trunc(rawStart), value.length))
        : 0;
      const safeLength = Number.isFinite(rawLength)
        ? Math.max(0, Math.trunc(rawLength))
        : 0;
      const safeEnd = Math.max(
        safeStart,
        Math.min(value.length, safeStart + safeLength),
      );
      if (safeEnd <= safeStart) return;

      const visibleWidth = Number(textarea.clientWidth) || 0;
      const visibleHeight = Number(textarea.clientHeight) || 0;
      if (!visibleWidth || !visibleHeight) return;

      const textareaStyle = window.getComputedStyle(textarea);
      const mirror = document.createElement("div");
      const marker = document.createElement("span");
      const copiedStyleProperties = [
        "fontFamily",
        "fontSize",
        "fontStretch",
        "fontStyle",
        "fontVariant",
        "fontWeight",
        "letterSpacing",
        "lineHeight",
        "tabSize",
        "textAlign",
        "textIndent",
        "textRendering",
        "textTransform",
        "unicodeBidi",
        "whiteSpace",
        "wordBreak",
        "wordSpacing",
        "overflowWrap",
        "writingMode",
      ];

      copiedStyleProperties.forEach((property) => {
        const value = textareaStyle[property];
        if (value) mirror.style[property] = value;
      });

      Object.assign(mirror.style, {
        position: "fixed",
        left: "-100000px",
        top: "0",
        width: `${visibleWidth}px`,
        height: "auto",
        minHeight: "0",
        maxHeight: "none",
        boxSizing: "border-box",
        padding: textareaStyle.padding || "0",
        border: "0",
        margin: "0",
        overflow: "visible",
        visibility: "hidden",
        pointerEvents: "none",
        display: "block",
      });

      marker.textContent = value.slice(safeStart, safeEnd);
      mirror.textContent = value.slice(0, safeStart);
      mirror.appendChild(marker);

      host.appendChild(mirror);
      try {
        const mirrorRect = mirror.getBoundingClientRect();
        const markerRect = marker.getBoundingClientRect();
        const lineHeight = Number.parseFloat(textareaStyle.lineHeight);
        const markerHeight =
          Number(markerRect.height) || (Number.isFinite(lineHeight) ? lineHeight : 1);
        const markerTop = Number(markerRect.top) - Number(mirrorRect.top);
        const markerLeft = Number(markerRect.left) - Number(mirrorRect.left);
        const markerCenterY = markerTop + markerHeight / 2;
        const markerCenterX =
          markerLeft + (Number(markerRect.width) || 0) / 2;
        const maxScrollTop = Math.max(
          0,
          Number(textarea.scrollHeight || 0) - visibleHeight,
        );
        const desiredScrollTop = Math.max(
          0,
          Math.min(maxScrollTop, markerCenterY - visibleHeight / 2),
        );

        textarea.scrollTop = desiredScrollTop;

        const visibleScrollWidth = Number(textarea.scrollWidth || 0);
        const maxScrollLeft = Math.max(0, visibleScrollWidth - visibleWidth);
        if (maxScrollLeft > 0) {
          textarea.scrollLeft = Math.max(
            0,
            Math.min(maxScrollLeft, markerCenterX - visibleWidth / 2),
          );
        }
      } finally {
        if (typeof mirror.remove === "function") mirror.remove();
        else if (typeof host.removeChild === "function") host.removeChild(mirror);
      }
    },

    _scrollWiEntryIntoView(entry, fallbackIndex = 0) {
      if (!entry || typeof this._getEditorRootEl !== "function") return;

      const entryKey =
        typeof this.getWiEntryIdentity === "function"
          ? this.getWiEntryIdentity(entry, fallbackIndex)
          : "";
      if (!entryKey) return;

      const reveal = () => {
        const root = this._getEditorRootEl();
        if (!root || typeof root.querySelectorAll !== "function") return;

        const item = Array.from(root.querySelectorAll(".wi-list-item")).find(
          (candidate) =>
            (candidate.dataset?.entryKey ||
              candidate.getAttribute?.("data-entry-key")) === entryKey,
        );
        if (!item || typeof item.scrollIntoView !== "function") return;

        const reducedMotion =
          typeof window !== "undefined" &&
          typeof window.matchMedia === "function" &&
          window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        item.scrollIntoView({
          behavior: reducedMotion ? "auto" : "smooth",
          block: "center",
        });
      };

      const scheduleFrame = (callback) => {
        if (
          typeof window !== "undefined" &&
          typeof window.requestAnimationFrame === "function"
        ) {
          window.requestAnimationFrame(callback);
        } else {
          callback();
        }
      };

      if (typeof this.$nextTick === "function") {
        this.$nextTick(() => scheduleFrame(reveal));
      } else {
        scheduleFrame(reveal);
      }
    },

    _focusAndRevealFindHit(start, length) {
      const reveal = () => {
        const textarea = this._getContentTextareaEl();
        if (!textarea) return;

        const rawStart = Number(start);
        const rawLength = Number(length);
        const selectionStart = Number.isFinite(rawStart)
          ? Math.max(0, Math.trunc(rawStart))
          : 0;
        const selectionLength = Number.isFinite(rawLength)
          ? Math.max(0, Math.trunc(rawLength))
          : 0;
        const maxLength =
          typeof textarea.value === "string"
            ? textarea.value.length
            : selectionStart + selectionLength;
        const safeStart = Math.min(selectionStart, maxLength);
        const safeEnd = Math.min(
          maxLength,
          safeStart + selectionLength,
        );

        if (typeof textarea.focus === "function") {
          try {
            textarea.focus({ preventScroll: true });
          } catch (_error) {
            textarea.focus();
          }
        }
        if (typeof textarea.setSelectionRange === "function") {
          textarea.setSelectionRange(safeStart, safeEnd);
        }
        this._scrollFindHitIntoView(
          textarea,
          safeStart,
          Math.max(0, safeEnd - safeStart),
        );
      };

      const scheduleFrame = (callback) => {
        if (
          typeof window !== "undefined" &&
          typeof window.requestAnimationFrame === "function"
        ) {
          window.requestAnimationFrame(callback);
        } else {
          callback();
        }
      };

      this.$nextTick(() => {
        // 全部条目切换时 textarea 会被 x-if 重建，等待两帧确保尺寸和换行布局已稳定。
        scheduleFrame(() => scheduleFrame(reveal));
      });
    },

    _getFindInputEl() {
      const root = this._getEditorRootEl();
      if (!root) return null;
      return root.querySelector('input[x-ref="findReplaceInput"]');
    },

    _getFindReplacePanelEl() {
      const root = this._getEditorRootEl();
      if (!root) return null;
      return root.querySelector('[x-ref="findReplacePanel"]');
    },

    _clampFindReplacePos(x, y) {
      const panel = this._getFindReplacePanelEl();
      const panelW = panel ? panel.offsetWidth : 640;
      const panelH = panel ? panel.offsetHeight : 340;
      const maxX = Math.max(12, window.innerWidth - panelW - 12);
      const maxY = Math.max(12, window.innerHeight - panelH - 12);
      return {
        x: Math.max(12, Math.min(Math.floor(x), maxX)),
        y: Math.max(12, Math.min(Math.floor(y), maxY)),
      };
    },

    get findReplacePanelStyle() {
      const clamped = this._clampFindReplacePos(
        this.findReplacePanelX || 0,
        this.findReplacePanelY || 0,
      );
      return `left:${clamped.x}px;top:${clamped.y}px;`;
    },

    _resetFindReplacePanelPos() {
      const panelW = 640;
      const panelH = 340;
      const x = Math.max(12, Math.floor((window.innerWidth - panelW) / 2));
      const y = Math.max(12, Math.floor((window.innerHeight - panelH) / 2));
      const clamped = this._clampFindReplacePos(x, y);
      this.findReplacePanelX = clamped.x;
      this.findReplacePanelY = clamped.y;
    },

    _attachFindReplaceDragListeners() {
      if (this._findReplaceMoveHandler || this._findReplaceUpHandler) return;
      this._findReplaceMoveHandler = (evt) => this.onFindReplaceDragMove(evt);
      this._findReplaceUpHandler = () => this.stopFindReplaceDrag();
      window.addEventListener("mousemove", this._findReplaceMoveHandler);
      window.addEventListener("mouseup", this._findReplaceUpHandler);
    },

    _detachFindReplaceDragListeners() {
      if (this._findReplaceMoveHandler) {
        window.removeEventListener("mousemove", this._findReplaceMoveHandler);
        this._findReplaceMoveHandler = null;
      }
      if (this._findReplaceUpHandler) {
        window.removeEventListener("mouseup", this._findReplaceUpHandler);
        this._findReplaceUpHandler = null;
      }
      this.findReplaceDragActive = false;
    },

    startFindReplaceDrag(evt) {
      const panel = this._getFindReplacePanelEl();
      if (!panel) return;

      const rect = panel.getBoundingClientRect();
      this.findReplaceDragActive = true;
      this.findReplaceDragOffsetX = (evt.clientX || 0) - rect.left;
      this.findReplaceDragOffsetY = (evt.clientY || 0) - rect.top;
      this._attachFindReplaceDragListeners();
    },

    onFindReplaceDragMove(evt) {
      if (!this.findReplaceDragActive) return;
      const x = (evt.clientX || 0) - this.findReplaceDragOffsetX;
      const y = (evt.clientY || 0) - this.findReplaceDragOffsetY;
      const clamped = this._clampFindReplacePos(x, y);
      this.findReplacePanelX = clamped.x;
      this.findReplacePanelY = clamped.y;
    },

    stopFindReplaceDrag() {
      this.findReplaceDragActive = false;
      this._detachFindReplaceDragListeners();
    },

    openFindReplaceModal() {
      if (!this.activeEditorEntry && !this.getWIArrayRef().length) {
        alert("当前没有可查找的条目。");
        return;
      }

      if (!this.findReplacePanelX && !this.findReplacePanelY) {
        this._resetFindReplacePanelPos();
      }
      this.showFindReplaceModal = true;
      this.findReplaceLastHit = null;

      // 若正文有选中文本，优先带入查找词
      const ta = this._getContentTextareaEl();
      if (ta && ta.selectionStart !== ta.selectionEnd) {
        const selected = ta.value.slice(ta.selectionStart, ta.selectionEnd);
        if (selected && !this.findReplaceQuery) {
          this.findReplaceQuery = selected;
        }
      }

      this.$nextTick(() => {
        const focusInput = () => {
          const input = this._getFindInputEl();
          const panel = this._getFindReplacePanelEl();
          const activeElement = document.activeElement;
          if (
            !input ||
            (panel &&
              activeElement &&
              panel.contains(activeElement) &&
              activeElement !== input)
          ) {
            return;
          }
          if (typeof input.focus === "function") {
            input.focus();
            if (typeof input.select === "function") input.select();
          }
        };
        focusInput();
        window.setTimeout(focusInput, 0);
        window.setTimeout(focusInput, 120);
        window.setTimeout(focusInput, 320);
      });
    },

    closeFindReplaceModal() {
      this.stopFindReplaceDrag();
      this.showFindReplaceModal = false;
    },

    _getFindReplaceTargets() {
      if (this.findReplaceScope === "current") {
        const current = this.activeEditorEntry;
        if (!current || typeof current !== "object") return [];
        return [
          {
            entry: current,
            index: this.isEditingClipboard ? -1 : this.currentWiIndex,
          },
        ];
      }

      const arr = this.getWIArrayRef();
      if (!Array.isArray(arr) || !arr.length) return [];
      return arr.map((entry, index) => ({ entry, index }));
    },

    _normalizeFindText(text) {
      return String(text ?? "");
    },

    _parseFindReplaceExcludeTokens() {
      const raw = String(this.findReplaceExcludeText || "");
      if (!raw.trim()) return [];
      const parts = raw
        .split(/\r?\n|,/)
        .map((s) => String(s || "").trim())
        .filter(Boolean);
      const unique = Array.from(new Set(parts));
      // 长词优先，减少短词遮挡误判
      unique.sort((a, b) => b.length - a.length);
      return unique;
    },

    _mergeRanges(ranges) {
      if (!ranges.length) return [];
      const sorted = [...ranges].sort(
        (a, b) => a.start - b.start || a.end - b.end,
      );
      const merged = [sorted[0]];
      for (let i = 1; i < sorted.length; i++) {
        const cur = sorted[i];
        const last = merged[merged.length - 1];
        if (cur.start <= last.end) {
          last.end = Math.max(last.end, cur.end);
        } else {
          merged.push({ start: cur.start, end: cur.end });
        }
      }
      return merged;
    },

    _buildBlockedRanges(text, excludeTokens, caseSensitive = false) {
      const src = this._normalizeFindText(text);
      const tokens = Array.isArray(excludeTokens)
        ? excludeTokens.filter(Boolean)
        : [];
      if (!tokens.length || !src) return [];

      const ranges = [];
      if (caseSensitive) {
        tokens.forEach((token) => {
          let from = 0;
          while (from <= src.length - token.length) {
            const idx = src.indexOf(token, from);
            if (idx < 0) break;
            ranges.push({ start: idx, end: idx + token.length });
            from = idx + Math.max(1, token.length);
          }
        });
      } else {
        const srcLower = src.toLowerCase();
        tokens.forEach((token) => {
          const t = token.toLowerCase();
          let from = 0;
          while (from <= srcLower.length - t.length) {
            const idx = srcLower.indexOf(t, from);
            if (idx < 0) break;
            ranges.push({ start: idx, end: idx + t.length });
            from = idx + Math.max(1, t.length);
          }
        });
      }

      return this._mergeRanges(ranges);
    },

    _isRangeBlocked(start, length, blockedRanges) {
      const end = start + length;
      for (const rg of blockedRanges) {
        if (start < rg.end && end > rg.start) {
          return true;
        }
      }
      return false;
    },

    _findInText(
      text,
      query,
      fromIndex = 0,
      caseSensitive = false,
      blockedRanges = [],
    ) {
      const src = this._normalizeFindText(text);
      const needle = this._normalizeFindText(query);
      if (!needle) return -1;

      const start = Math.max(0, Math.min(Number(fromIndex) || 0, src.length));
      let pos = start;
      while (pos <= src.length) {
        let found = -1;
        if (caseSensitive) {
          found = src.indexOf(needle, pos);
        } else {
          found = src.toLowerCase().indexOf(needle.toLowerCase(), pos);
        }
        if (found < 0) return -1;
        if (!this._isRangeBlocked(found, needle.length, blockedRanges))
          return found;
        pos = found + 1;
      }
      return -1;
    },

    _findPreviousInText(
      text,
      query,
      fromIndex = Number.POSITIVE_INFINITY,
      caseSensitive = false,
      blockedRanges = [],
    ) {
      const src = this._normalizeFindText(text);
      const needle = this._normalizeFindText(query);
      if (!needle) return -1;

      const maxStart = src.length - needle.length;
      if (maxStart < 0) return -1;

      const rawStart = Number(fromIndex);
      let pos = Number.isFinite(rawStart) ? Math.trunc(rawStart) : maxStart;
      pos = Math.min(pos, maxStart);
      while (pos >= 0) {
        const found = caseSensitive
          ? src.lastIndexOf(needle, pos)
          : src.toLowerCase().lastIndexOf(needle.toLowerCase(), pos);
        if (found < 0) return -1;
        if (!this._isRangeBlocked(found, needle.length, blockedRanges)) {
          return found;
        }
        pos = found - 1;
      }
      return -1;
    },

    _applyFindHit(hit) {
      if (!hit || !hit.entry) return false;

      // 全部条目模式下切换到命中条目
      if (
        this.findReplaceScope === "all" &&
        typeof hit.index === "number" &&
        hit.index >= 0
      ) {
        this.isEditingClipboard = false;
        this.currentClipboardIndex = -1;
        this.currentWiIndex = hit.index;
        this.currentWiEntryKey = this.getWiEntryIdentity(hit.entry, hit.index);
      }

      this.findReplaceLastHit = {
        query: this.findReplaceQuery,
        scope: this.findReplaceScope,
        caseSensitive: !!this.findReplaceCaseSensitive,
        index: hit.index,
        entryUid: String(hit.entry?.[this.entryUidField] || ""),
        start: hit.start,
        length: hit.length,
      };

      if (typeof this._scrollWiEntryIntoView === "function") {
        this._scrollWiEntryIntoView(hit.entry, hit.index);
      }
      this._focusAndRevealFindHit(hit.start, hit.length);
      return true;
    },

    findNextMatch() {
      const query = this._normalizeFindText(this.findReplaceQuery).trim();
      if (!query) {
        alert("请输入查找内容。");
        return false;
      }

      const targets = this._getFindReplaceTargets();
      if (!targets.length) {
        alert("当前范围没有可查找的条目。");
        return false;
      }

      let startTargetIdx = 0;
      let startOffset = 0;
      const last = this.findReplaceLastHit;

      if (this.findReplaceScope === "current") {
        const ta = this._getContentTextareaEl();
        if (ta && typeof ta.selectionEnd === "number") {
          startOffset = ta.selectionEnd;
        }
      } else if (
        last &&
        last.query === this.findReplaceQuery &&
        last.scope === this.findReplaceScope &&
        !!last.caseSensitive === !!this.findReplaceCaseSensitive
      ) {
        let idx = targets.findIndex((t) => {
          const uid = String(t.entry?.[this.entryUidField] || "");
          return uid && uid === String(last.entryUid || "");
        });
        if (idx < 0 && typeof last.index === "number") idx = last.index;
        if (idx >= 0 && idx < targets.length) {
          startTargetIdx = idx;
          startOffset = Number(last.start || 0) + Number(last.length || 0);
        }
      }

      for (let pass = 0; pass < targets.length; pass++) {
        const targetIdx = (startTargetIdx + pass) % targets.length;
        const target = targets[targetIdx];
        const content = this._normalizeFindText(target.entry?.content);
        const excluded = this._parseFindReplaceExcludeTokens();
        const blockedRanges = this._buildBlockedRanges(
          content,
          excluded,
          this.findReplaceCaseSensitive,
        );
        const from = pass === 0 ? startOffset : 0;
        const pos = this._findInText(
          content,
          query,
          from,
          this.findReplaceCaseSensitive,
          blockedRanges,
        );
        if (pos >= 0) {
          const hit = {
            entry: target.entry,
            index: target.index,
            start: pos,
            length: query.length,
          };
          this._applyFindHit(hit);
          return true;
        }
      }

      // 回到起点条目开头，完成一整圈查找
      if (startOffset > 0) {
        const target = targets[startTargetIdx];
        const content = this._normalizeFindText(target.entry?.content);
        const excluded = this._parseFindReplaceExcludeTokens();
        const blockedRanges = this._buildBlockedRanges(
          content,
          excluded,
          this.findReplaceCaseSensitive,
        );
        const pos = this._findInText(
          content,
          query,
          0,
          this.findReplaceCaseSensitive,
          blockedRanges,
        );
        if (pos >= 0) {
          const hit = {
            entry: target.entry,
            index: target.index,
            start: pos,
            length: query.length,
          };
          this._applyFindHit(hit);
          return true;
        }
      }

      alert("未找到匹配内容。");
      return false;
    },

    findPreviousMatch() {
      const query = this._normalizeFindText(this.findReplaceQuery).trim();
      if (!query) {
        alert("请输入查找内容。");
        return false;
      }

      const targets = this._getFindReplaceTargets();
      if (!targets.length) {
        alert("当前范围没有可查找的条目。");
        return false;
      }

      let startTargetIdx = 0;
      let startOffset = Number.POSITIVE_INFINITY;
      const last = this.findReplaceLastHit;
      let resumedFromLast = false;

      if (this.findReplaceScope === "current") {
        const content = this._normalizeFindText(targets[0].entry?.content);
        const textarea = this._getContentTextareaEl();
        const cursorStart =
          textarea && typeof textarea.selectionStart === "number"
            ? textarea.selectionStart
            : content.length;
        startOffset = cursorStart - query.length;
      } else if (
        last &&
        last.query === this.findReplaceQuery &&
        last.scope === this.findReplaceScope &&
        !!last.caseSensitive === !!this.findReplaceCaseSensitive
      ) {
        let idx = targets.findIndex((target) => {
          const uid = String(target.entry?.[this.entryUidField] || "");
          return uid && uid === String(last.entryUid || "");
        });
        if (idx < 0 && typeof last.index === "number") {
          idx = targets.findIndex((target) => target.index === last.index);
        }
        if (idx >= 0 && idx < targets.length) {
          startTargetIdx = idx;
          startOffset = Number(last.start || 0) - 1;
          resumedFromLast = true;
        }
      }

      if (this.findReplaceScope === "all" && !resumedFromLast) {
        const current = this.activeEditorEntry;
        const currentIndex = targets.findIndex(
          (target) => target.entry === current,
        );
        startTargetIdx = currentIndex >= 0 ? currentIndex : 0;
        const content = this._normalizeFindText(
          targets[startTargetIdx].entry?.content,
        );
        const textarea = this._getContentTextareaEl();
        const cursorStart =
          textarea && typeof textarea.selectionStart === "number"
            ? textarea.selectionStart
            : content.length;
        startOffset = cursorStart - query.length;
      }

      const findInTarget = (target, fromIndex) => {
        const content = this._normalizeFindText(target.entry?.content);
        const excluded = this._parseFindReplaceExcludeTokens();
        const blockedRanges = this._buildBlockedRanges(
          content,
          excluded,
          this.findReplaceCaseSensitive,
        );
        return this._findPreviousInText(
          content,
          query,
          fromIndex,
          this.findReplaceCaseSensitive,
          blockedRanges,
        );
      };

      for (let pass = 0; pass < targets.length; pass++) {
        const targetIdx =
          (startTargetIdx - pass + targets.length) % targets.length;
        const target = targets[targetIdx];
        const from = pass === 0 ? startOffset : Number.POSITIVE_INFINITY;
        const pos = findInTarget(target, from);
        if (pos >= 0) {
          this._applyFindHit({
            entry: target.entry,
            index: target.index,
            start: pos,
            length: query.length,
          });
          return true;
        }
      }

      // 回到起点条目末尾，完成一整圈反向查找。
      const startTarget = targets[startTargetIdx];
      const pos = findInTarget(startTarget, Number.POSITIVE_INFINITY);
      if (pos >= 0) {
        this._applyFindHit({
          entry: startTarget.entry,
          index: startTarget.index,
          start: pos,
          length: query.length,
        });
        return true;
      }

      alert("未找到匹配内容。");
      return false;
    },

    _resolveLastFindHitEntry() {
      const last = this.findReplaceLastHit;
      if (!last) return null;

      const targets = this._getFindReplaceTargets();
      if (!targets.length) return null;

      let target = null;
      if (last.entryUid) {
        target = targets.find(
          (t) =>
            String(t.entry?.[this.entryUidField] || "") ===
            String(last.entryUid),
        );
      }
      if (!target && typeof last.index === "number") {
        target = targets.find((t) => t.index === last.index);
      }
      return target || null;
    },

    replaceCurrentMatch() {
      const query = this._normalizeFindText(this.findReplaceQuery).trim();
      if (!query) {
        alert("请输入查找内容。");
        return;
      }

      const replacement = this._normalizeFindText(this.findReplaceReplacement);
      let last = this.findReplaceLastHit;
      if (
        !last ||
        last.query !== this.findReplaceQuery ||
        last.scope !== this.findReplaceScope
      ) {
        const found = this.findNextMatch();
        if (!found) return;
        last = this.findReplaceLastHit;
      }

      const target = this._resolveLastFindHitEntry();
      if (!target || !target.entry) {
        const found = this.findNextMatch();
        if (!found) return;
      }

      const resolved = this._resolveLastFindHitEntry();
      if (!resolved || !resolved.entry) return;

      const content = this._normalizeFindText(resolved.entry.content);
      const start = Number(this.findReplaceLastHit.start || 0);
      const length = Number(this.findReplaceLastHit.length || query.length);
      const segment = content.slice(start, start + length);
      const excluded = this._parseFindReplaceExcludeTokens();
      const blockedRanges = this._buildBlockedRanges(
        content,
        excluded,
        this.findReplaceCaseSensitive,
      );
      const isEqual = this.findReplaceCaseSensitive
        ? segment === query
        : segment.toLowerCase() === query.toLowerCase();
      const isBlocked = this._isRangeBlocked(start, length, blockedRanges);

      if (!isEqual || isBlocked) {
        const found = this.findNextMatch();
        if (!found) return;
        return this.replaceCurrentMatch();
      }

      resolved.entry.content =
        content.slice(0, start) + replacement + content.slice(start + length);

      this.findReplaceLastHit = {
        ...this.findReplaceLastHit,
        start,
        length: replacement.length,
      };

      this._focusAndRevealFindHit(start, replacement.length);
      this.$store.global.showToast("已替换当前匹配", 1200);
    },

    replaceAllMatches() {
      const query = this._normalizeFindText(this.findReplaceQuery).trim();
      if (!query) {
        alert("请输入查找内容。");
        return;
      }

      const replacement = this._normalizeFindText(this.findReplaceReplacement);
      const targets = this._getFindReplaceTargets();
      if (!targets.length) {
        alert("当前范围没有可替换的条目。");
        return;
      }

      const excluded = this._parseFindReplaceExcludeTokens();
      let replaceCount = 0;
      let hitEntries = 0;
      targets.forEach((target) => {
        const content = this._normalizeFindText(target.entry?.content);
        const blockedRanges = this._buildBlockedRanges(
          content,
          excluded,
          this.findReplaceCaseSensitive,
        );

        let from = 0;
        let cnt = 0;
        let out = "";
        while (from <= content.length) {
          const pos = this._findInText(
            content,
            query,
            from,
            this.findReplaceCaseSensitive,
            blockedRanges,
          );
          if (pos < 0) break;
          out += content.slice(from, pos) + replacement;
          from = pos + query.length;
          cnt += 1;
        }
        if (!cnt) return;

        out += content.slice(from);
        target.entry.content = out;
        replaceCount += cnt;
        hitEntries += 1;
      });

      this.findReplaceLastHit = null;
      if (!replaceCount) {
        this.$store.global.showToast("没有匹配内容可替换", 1500);
        return;
      }
      this.$store.global.showToast(
        `已替换 ${replaceCount} 处（${hitEntries} 条目）`,
        1800,
      );
    },

    openTaggedImportModal() {
      this.showTaggedImportModal = true;
      this.taggedImportDragOver = false;
      this.taggedImportPendingFile = null;
      this.taggedImportPendingFileName = "";
    },

    closeTaggedImportModal() {
      this.showTaggedImportModal = false;
      this.taggedImportDragOver = false;
      this.taggedImportPendingFile = null;
      this.taggedImportPendingFileName = "";
      const root = this._getEditorRootEl();
      const input = root?.querySelector('input[x-ref="taggedJsonlInput"]');
      if (input) input.value = "";
    },

    triggerTaggedImportFilePick() {
      const root = this._getEditorRootEl();
      if (!root) return;
      const input = root.querySelector('input[x-ref="taggedJsonlInput"]');
      if (!input) return;
      input.click();
    },

    _setTaggedImportPendingFile(file) {
      if (!file) return;
      this.taggedImportPendingFile = file;
      this.taggedImportPendingFileName =
        String(file.name || "").trim() || "未命名文件";
    },

    handleTaggedImportFilePick(evt) {
      const file = evt?.target?.files?.[0];
      if (!file) return;
      this._setTaggedImportPendingFile(file);
    },

    handleTaggedImportDrop(evt) {
      this.taggedImportDragOver = false;
      const file = evt?.dataTransfer?.files?.[0];
      if (!file) return;
      this._setTaggedImportPendingFile(file);
    },

    _collectTextFragmentsFromJsonNode(node, out, depth = 0) {
      if (depth > 8 || node === null || node === undefined) return;

      if (typeof node === "string") {
        const text = String(node).trim();
        if (text) out.push(text);
        return;
      }
      if (typeof node !== "object") return;

      if (Array.isArray(node)) {
        node.forEach((item) =>
          this._collectTextFragmentsFromJsonNode(item, out, depth + 1),
        );
        return;
      }

      const prioritizedKeys = [
        "mes",
        "message",
        "content",
        "text",
        "raw_message",
        "swipes",
      ];
      prioritizedKeys.forEach((k) => {
        if (Object.prototype.hasOwnProperty.call(node, k)) {
          this._collectTextFragmentsFromJsonNode(node[k], out, depth + 1);
        }
      });

      Object.keys(node).forEach((k) => {
        if (prioritizedKeys.includes(k)) return;
        this._collectTextFragmentsFromJsonNode(node[k], out, depth + 1);
      });
    },

    _parseTaggedImportIgnoredTags() {
      const raw = String(this.taggedImportIgnoreText || "");
      const items = raw
        .split(/\r?\n|,/)
        .map((s) =>
          String(s || "")
            .trim()
            .toLowerCase(),
        )
        .filter(Boolean);
      return new Set(items);
    },

    _escapeRegExp(text) {
      return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    },

    _stripImportNoiseTags(text, ignoredTags = null) {
      const raw = String(text || "");
      if (!raw) return "";
      const ignoreSet = ignoredTags || this._parseTaggedImportIgnoredTags();
      let out = raw;
      ignoreSet.forEach((tag) => {
        const safe = this._escapeRegExp(tag);
        if (!safe) return;
        const rg = new RegExp(`<\\/?${safe}\\b[^>]*>`, "gi");
        out = out.replace(rg, "");
      });
      return out;
    },

    _isIgnoredImportTag(tagName, ignoredTags = null) {
      const tag = String(tagName || "")
        .trim()
        .toLowerCase();
      const ignoreSet = ignoredTags || this._parseTaggedImportIgnoredTags();
      return ignoreSet.has(tag);
    },

    _extractTaggedBlocksFromText(text, depth = 0, ignoredTags = null) {
      if (depth > 8) return [];
      const ignoreSet = ignoredTags || this._parseTaggedImportIgnoredTags();
      const raw = this._stripImportNoiseTags(text, ignoreSet);
      if (!raw) return [];
      const regex = /<([a-zA-Z][\w:-]{0,63})\b[^>]*>([\s\S]*?)<\/\1>/gi;
      const found = [];
      let m;
      while ((m = regex.exec(raw)) !== null) {
        const tag = String(m[1] || "")
          .trim()
          .toLowerCase();
        const block = String(m[0] || "").trim();
        const inner = String(m[2] || "");
        if (!tag || !block) continue;

        if (this._isIgnoredImportTag(tag, ignoreSet)) {
          // 对被忽略标签，继续从内部提取可用标签，避免包裹层吞掉内部内容
          const nested = this._extractTaggedBlocksFromText(
            inner,
            depth + 1,
            ignoreSet,
          );
          if (nested.length) found.push(...nested);
          continue;
        }

        found.push({ tag, block });
      }
      return found;
    },

    _buildTaggedEntry(tagName, blockText) {
      const tag =
        String(tagName || "")
          .trim()
          .toLowerCase() || "tag";
      return {
        id: Math.floor(Math.random() * 1000000),
        [this.entryUidField]: this._generateEntryUid(),
        comment: tag,
        content: String(blockText || ""),
        keys: [tag],
        secondary_keys: [],
        enabled: true,
        constant: false,
        vectorized: false,
        insertion_order: 100,
        position: 1,
        role: null,
        depth: 4,
        selective: true,
        selectiveLogic: 0,
        preventRecursion: false,
        excludeRecursion: false,
        delayUntilRecursion: 0,
        ignoreBudget: false,
        probability: 100,
        useProbability: true,
      };
    },

    async importTaggedJsonlFromPending() {
      const file = this.taggedImportPendingFile;
      if (!file) return;

      try {
        const ignoreSet = this._parseTaggedImportIgnoredTags();
        const raw = await file.text();
        const lines = String(raw || "")
          .split(/\r?\n/)
          .map((s) => String(s || "").trim())
          .filter(Boolean);

        if (!lines.length) {
          alert("文件为空，无法导入。");
          return;
        }

        const textPool = [];
        lines.forEach((line) => {
          try {
            const obj = JSON.parse(line);
            this._collectTextFragmentsFromJsonNode(obj, textPool, 0);
          } catch {
            textPool.push(line);
          }
        });

        const blocks = [];
        textPool.forEach((txt) => {
          const hit = this._extractTaggedBlocksFromText(txt, 0, ignoreSet);
          if (hit.length) blocks.push(...hit);
        });

        const uniqueMap = new Map();
        blocks.forEach((it) => {
          const tag = String(it?.tag || "")
            .trim()
            .toLowerCase();
          const block = String(it?.block || "").trim();
          if (!tag || !block) return;
          const key = `${tag}|||${block}`;
          if (!uniqueMap.has(key)) uniqueMap.set(key, { tag, block });
        });
        const uniqueBlocks = Array.from(uniqueMap.values());
        if (!uniqueBlocks.length) {
          alert("未找到 <tag>...</tag> 格式内容。");
          return;
        }

        const arr = this.getWIArrayRef();
        const insertStart = arr.length;
        uniqueBlocks.forEach((it) => {
          arr.push(this._buildTaggedEntry(it.tag, it.block));
        });
        this.currentWiIndex = insertStart;
        this.isEditingClipboard = false;
        this.currentClipboardIndex = -1;

        this.$nextTick(() => {
          const el = document.getElementById(`wi-item-${insertStart}`);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        });

        this.$store.global.showToast(
          `已导入 ${uniqueBlocks.length} 条标签条目`,
          2200,
          'check',
        );
        this.closeTaggedImportModal();
      } catch (e) {
        console.error("Import tagged blocks from JSONL failed:", e);
        alert(`导入失败: ${e.message || e}`);
      }
    },

    async handleTaggedJsonlImport(evt) {
      const file = evt?.target?.files?.[0];
      if (!file) return;
      this._setTaggedImportPendingFile(file);
      return this.importTaggedJsonlFromPending();
    },

    // 兼容旧模板调用名
    triggerWorldviewJsonlImport() {
      return this.openTaggedImportModal();
    },

    // 兼容旧模板调用名
    handleWorldviewJsonlImport(evt) {
      return this.handleTaggedJsonlImport(evt);
    },

    _normalizePathForCompare(path) {
      return String(path || "")
        .replace(/\\/g, "/")
        .toLowerCase();
    },

    _isRestoreForCurrentEditor(detail) {
      if (!this.showFullScreenWI || !this.editingWiFile) return false;

      const targetType = String(detail.targetType || "");
      const targetId = String(detail.targetId || "");
      const targetFilePath = this._normalizePathForCompare(
        detail.targetFilePath || "",
      );
      const currentFile = this.editingWiFile || {};

      if (targetType === "card") {
        // 仅内嵌模式会直接编辑角色卡
        const currentCardId = String(
          this.editingData?.id || currentFile.card_id || "",
        );
        const normalizedTargetCardId = targetId.startsWith("embedded::")
          ? targetId.replace("embedded::", "")
          : targetId;
        return !!currentCardId && currentCardId === normalizedTargetCardId;
      }

      if (targetType === "lorebook") {
        // 内嵌世界书回滚会落到宿主卡片
        if (targetId.startsWith("embedded::")) {
          const currentCardId = String(
            this.editingData?.id || currentFile.card_id || "",
          );
          return (
            !!currentCardId &&
            currentCardId === targetId.replace("embedded::", "")
          );
        }

        // 独立世界书按 file_path 精确匹配
        const currentPath = this._normalizePathForCompare(
          currentFile.file_path || currentFile.path || "",
        );
        return (
          !!currentPath && !!targetFilePath && currentPath === targetFilePath
        );
      }

      return false;
    },

    async _syncEditorStateAfterRestore() {
      if (!this.editingWiFile) return false;

      const keepIndex = this.currentWiIndex;
      const currentFile = this.editingWiFile;

      if (currentFile.type === "embedded" || this.editingData?.id) {
        const cardId = this.editingData?.id || currentFile.card_id;
        const res = await getCardDetail(cardId);
        if (!res || !res.success || !res.card) {
          return false;
        }

        const card = res.card;
        if (card.character_book) {
          card.character_book = normalizeWiBook(
            card.character_book,
            card.char_name || "WI",
          );
        }

        this.editingData = card;
        this._ensureEntryUids();
      } else {
        const res = await getWorldInfoDetail({
          id: currentFile.id,
          source_type: currentFile.source_type,
          file_path: currentFile.file_path || currentFile.path,
          force_full: true,
        });

        if (!res || !res.success) {
          return false;
        }

        const book = normalizeWiBook(
          res.data,
          currentFile.name || "World Info",
        );
        this.editingData.character_book = book;
        this.editingWiFile.source_revision = res.source_revision || "";
        this._ensureEntryUids();
      }

      const entries = this.getWIArrayRef();
      if (!entries.length) {
        this.currentWiIndex = 0;
      } else {
        this.currentWiIndex = Math.max(
          0,
          Math.min(keepIndex, entries.length - 1),
        );
      }

      if (autoSaver && typeof autoSaver.initBaseline === "function") {
        autoSaver.initBaseline(this.editingData);
      }
      return true;
    },

    async _handleRestoreApplied(detail) {
      if (!this._isRestoreForCurrentEditor(detail)) return;

      try {
        const synced = await this._syncEditorStateAfterRestore();
        if (synced) {
          this.$store.global.showToast("已同步恢复版本到当前编辑器", 2200, "backup-rollback");
        }
      } catch (e) {
        console.warn("Sync editor after restore failed:", e);
      }
    },

    _generateEntryUid() {
      return `wi-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    },

    _ensureEntryUids() {
      const arr = this.getWIArrayRef();
      const used = new Set();
      const usedSourceIds = new Set(
        arr
          .map((entry) => entry?.st_source_id ?? entry?.uid)
          .filter((value) => value !== undefined && value !== null && value !== "")
          .map((value) => String(value)),
      );
      let nextSourceId = 0;
      arr.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        let uid = String(entry[this.entryUidField] || "").trim();
        if (!uid || used.has(uid)) {
          uid = this._generateEntryUid();
          entry[this.entryUidField] = uid;
        }
        used.add(uid);

        if (
          entry.st_source_id === undefined ||
          entry.st_source_id === null ||
          entry.st_source_id === ""
        ) {
          while (usedSourceIds.has(String(nextSourceId))) nextSourceId += 1;
          entry.st_source_id = nextSourceId;
          usedSourceIds.add(String(nextSourceId));
          nextSourceId += 1;
        }
      });
    },

    _getEntryHistoryContext() {
      const file = this.editingWiFile || {};
      if (file.type === "embedded" || (!file.type && this.editingData?.id)) {
        return {
          source_type: "embedded",
          source_id:
            this.editingData && this.editingData.id
              ? this.editingData.id
              : file.card_id || "",
          file_path: "",
        };
      }
      return {
        source_type: "lorebook",
        source_id: file.id || "",
        file_path: file.file_path || file.path || "",
      };
    },

    formatEntryHistoryTime(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      if (Number.isNaN(d.getTime())) return "";
      return d.toLocaleString();
    },

    _escapeEntryHistoryHtml(text) {
      return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    },

    _toEntryHistoryArray(val) {
      if (Array.isArray(val))
        return val.map((v) => String(v ?? "").trim()).filter(Boolean);
      if (typeof val === "string")
        return val
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      return [];
    },

    _normalizeEntryHistorySnapshot(raw) {
      if (!raw || typeof raw !== "object") return null;
      return {
        comment: String(raw.comment ?? ""),
        content: String(raw.content ?? ""),
        keys: this._toEntryHistoryArray(raw.keys ?? raw.key),
        secondary_keys: this._toEntryHistoryArray(
          raw.secondary_keys ?? raw.keysecondary,
        ),
      };
    },

    _getEntryHistoryMeta(left, right) {
      if (left && right) {
        const changed = {
          comment: left.comment !== right.comment,
          keys:
            left.keys.join("|") !== right.keys.join("|") ||
            left.secondary_keys.join("|") !== right.secondary_keys.join("|"),
          content: left.content !== right.content,
        };
        const status =
          changed.comment || changed.keys || changed.content
            ? "changed"
            : "same";
        return { status, changed };
      }
      if (left && !right) {
        return {
          status: "removed",
          changed: { comment: true, keys: true, content: true },
        };
      }
      return {
        status: "added",
        changed: { comment: true, keys: true, content: true },
      };
    },

    _entryHistoryFieldDiffClass(meta, side, fieldChanged) {
      if (meta.status === "added" && side === "right") {
        return "color-status-success";
      }
      if (meta.status === "removed" && side === "left") {
        return "color-status-danger";
      }
      if (meta.status === "changed" && fieldChanged) {
        return "color-status-warning";
      }
      return "color-surface-container";
    },

    _splitEntryHistoryLinesWithLimit(text, maxLines = 240, maxChars = 16000) {
      const raw = String(text ?? "")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n");
      let limited = raw;
      let truncatedByChars = false;
      if (limited.length > maxChars) {
        limited = limited.slice(0, maxChars);
        truncatedByChars = true;
      }
      let lines = limited.split("\n");
      let truncatedByLines = false;
      if (lines.length > maxLines) {
        lines = lines.slice(0, maxLines);
        truncatedByLines = true;
      }
      if (truncatedByChars || truncatedByLines) {
        lines.push("...(内容过长，已截断显示)");
      }
      return lines;
    },

    _buildEntryHistoryLineOps(leftLines, rightLines, maxCells = 70000) {
      const n = leftLines.length;
      const m = rightLines.length;

      if (n * m > maxCells) {
        const approx = [];
        const len = Math.max(n, m);
        for (let i = 0; i < len; i++) {
          const l = i < n ? leftLines[i] : null;
          const r = i < m ? rightLines[i] : null;
          if (l !== null && r !== null) {
            approx.push({ t: l === r ? "same" : "changed", left: l, right: r });
          } else if (l !== null) {
            approx.push({ t: "removed", left: l, right: null });
          } else {
            approx.push({ t: "added", left: null, right: r });
          }
        }
        return approx;
      }

      const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          if (leftLines[i] === rightLines[j]) {
            dp[i][j] = dp[i + 1][j + 1] + 1;
          } else {
            dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
          }
        }
      }

      const rawOps = [];
      let i = 0;
      let j = 0;
      while (i < n && j < m) {
        if (leftLines[i] === rightLines[j]) {
          rawOps.push({ t: "same", text: leftLines[i] });
          i += 1;
          j += 1;
        } else if (dp[i + 1][j] >= dp[i][j + 1]) {
          rawOps.push({ t: "remove", text: leftLines[i] });
          i += 1;
        } else {
          rawOps.push({ t: "add", text: rightLines[j] });
          j += 1;
        }
      }
      while (i < n) {
        rawOps.push({ t: "remove", text: leftLines[i] });
        i += 1;
      }
      while (j < m) {
        rawOps.push({ t: "add", text: rightLines[j] });
        j += 1;
      }

      const aligned = [];
      let k = 0;
      while (k < rawOps.length) {
        const op = rawOps[k];
        if (op.t === "same") {
          aligned.push({ t: "same", left: op.text, right: op.text });
          k += 1;
          continue;
        }

        const removes = [];
        const adds = [];
        while (k < rawOps.length && rawOps[k].t !== "same") {
          if (rawOps[k].t === "remove") removes.push(rawOps[k].text);
          if (rawOps[k].t === "add") adds.push(rawOps[k].text);
          k += 1;
        }

        const pairCount = Math.min(removes.length, adds.length);
        for (let x = 0; x < pairCount; x++) {
          aligned.push({ t: "changed", left: removes[x], right: adds[x] });
        }
        for (let x = pairCount; x < removes.length; x++) {
          aligned.push({ t: "removed", left: removes[x], right: null });
        }
        for (let x = pairCount; x < adds.length; x++) {
          aligned.push({ t: "added", left: null, right: adds[x] });
        }
      }
      return aligned;
    },

    _entryHistoryLineClass(type, side) {
      if (type === "changed")
        return "color-status-warning";
      if (type === "added" && side === "right")
        return "color-status-success";
      if (type === "removed" && side === "left")
        return "color-status-danger";
      if (type === "added" && side === "left")
        return "color-status-success";
      if (type === "removed" && side === "right")
        return "color-status-danger";
      return "color-surface-container";
    },

    _renderEntryHistoryLineDiffHtml(leftText, rightText, side) {
      const leftLines = this._splitEntryHistoryLinesWithLimit(leftText);
      const rightLines = this._splitEntryHistoryLinesWithLimit(rightText);
      const rows = this._buildEntryHistoryLineOps(leftLines, rightLines);

      let leftNo = 0;
      let rightNo = 0;
      let html = "";
      rows.forEach((row) => {
        const isLeft = side === "left";
        const text = isLeft ? row.left : row.right;
        const cls = this._entryHistoryLineClass(row.t, side);

        if (row.left !== null) leftNo += 1;
        if (row.right !== null) rightNo += 1;
        const lineNo = isLeft
          ? row.left !== null
            ? leftNo
            : ""
          : row.right !== null
            ? rightNo
            : "";
        const lineText =
          text === null ? "∅" : this._escapeEntryHistoryHtml(text);
        const lineTextClass =
          text === null
            ? "text-[var(--content-muted)] italic"
            : "text-[var(--content-primary)]";

        html += `
                    <div class="px-2 py-0.5 rounded ${cls}">
                        <span class="inline-block w-8 mr-2 text-[10px] text-[var(--content-muted)] text-right select-none">${lineNo || " "}</span>
                        <span class="text-[11px] whitespace-pre-wrap break-words ${lineTextClass}">${lineText || " "}</span>
                    </div>
                `;
      });
      return html;
    },

    _renderEntryHistoryPane(entry, oppositeEntry, meta, side) {
      if (!entry) {
        return `
                    <div class="m-2 p-3 rounded border border-dashed border-[var(--border-default)] text-[11px] text-[var(--content-muted)] opacity-70">
                        <div>（此侧无对应条目）</div>
                    </div>
                `;
      }

      const isLeft = side === "left";
      const markClass =
        isLeft && (meta.status === "removed" || meta.status === "changed")
          ? "status-danger-text"
          : !isLeft && (meta.status === "added" || meta.status === "changed")
            ? "status-success-text"
            : "text-[var(--content-primary)]";

      const comment = this._escapeEntryHistoryHtml(entry.comment || "(无备注)");
      const keys = this._escapeEntryHistoryHtml(
        entry.keys.join(", ") || "(空)",
      );
      const sec = this._escapeEntryHistoryHtml(
        entry.secondary_keys.join(", ") || "(空)",
      );

      const commentCls = meta.changed.comment
        ? markClass
        : "text-[var(--content-primary)]";
      const keyCls = meta.changed.keys ? markClass : "text-[var(--content-primary)]";
      const contentCls = meta.changed.content
        ? markClass
        : "text-[var(--content-primary)]";

      const commentBgCls = this._entryHistoryFieldDiffClass(
        meta,
        side,
        meta.changed.comment,
      );
      const keysBgCls = this._entryHistoryFieldDiffClass(
        meta,
        side,
        meta.changed.keys,
      );
      const leftContent =
        side === "left" ? entry.content || "" : oppositeEntry?.content || "";
      const rightContent =
        side === "right" ? entry.content || "" : oppositeEntry?.content || "";
      const lineDiffHtml = this._renderEntryHistoryLineDiffHtml(
        leftContent,
        rightContent,
        side,
      );

      return `
                <div class="m-2 p-3 rounded border bg-[var(--surface-container-raised)] border-[var(--border-default)]">
                    <div class="mt-1 p-1.5 rounded ${commentBgCls}">
                        <div class="text-sm font-bold ${commentCls}">${comment}</div>
                    </div>
                    <div class="mt-2 p-1.5 rounded ${keysBgCls}">
                        <div class="text-[11px] ${keyCls}">关键词: ${keys}</div>
                        <div class="mt-1 text-[11px] ${keyCls}">次级词: ${sec}</div>
                    </div>
                    <div class="mt-2 p-1.5 rounded color-surface-sunken border border-[var(--border-default)]">
                        <div class="text-[11px] text-[var(--content-muted)]">内容预览</div>
                        <div class="mt-1 p-2 rounded color-surface-container max-h-72 overflow-auto">${lineDiffHtml}</div>
                        <div class="mt-1 text-[10px] ${contentCls}">行级高亮：绿=新增，黄=修改，红=删除</div>
                    </div>
                </div>
            `;
    },

    updateEntryHistoryDiff() {
      const leftVer = this.entryHistorySelection.left;
      const rightVer = this.entryHistorySelection.right;
      if (!leftVer || !rightVer) {
        this.entryHistoryDiff = {
          left: '<div class="p-6 text-center text-[var(--content-muted)] text-xs">请选择版本进行对比</div>',
          right:
            '<div class="p-6 text-center text-[var(--content-muted)] text-xs">请选择版本进行对比</div>',
        };
        return;
      }

      const left = this._normalizeEntryHistorySnapshot(leftVer.snapshot);
      const right = this._normalizeEntryHistorySnapshot(rightVer.snapshot);
      const meta = this._getEntryHistoryMeta(left, right);

      this.entryHistoryDiff = {
        left: this._renderEntryHistoryPane(left, right, meta, "left"),
        right: this._renderEntryHistoryPane(right, left, meta, "right"),
      };
    },

    setEntryHistorySide(side, version) {
      if (!version) return;
      this.entryHistorySelection[side] = version;
      this.updateEntryHistoryDiff();
    },

    openEntryHistoryModal() {
      if (this.isEditingClipboard) {
        alert("剪切板条目不支持历史版本。");
        return;
      }
      if (!this.activeEditorEntry) return;

      this._ensureEntryUids();
      const uid = this.activeEditorEntry[this.entryUidField];
      if (!uid) {
        alert("当前条目缺少唯一标识，无法读取历史版本。");
        return;
      }

      const context = this._getEntryHistoryContext();
      this.entryHistoryTargetUid = uid;
      this.entryHistoryItems = [];
      this.entryHistoryVersions = [];
      this.entryHistorySelection = { left: null, right: null };
      this.entryHistoryDiff = { left: "", right: "" };
      this.showEntryHistoryModal = true;
      this.isEntryHistoryLoading = true;

      listWiEntryHistory({
        ...context,
        entry_uid: uid,
      })
        .then((res) => {
          if (res.success) {
            const rawItems = Array.isArray(res.items) ? res.items : [];
            this.entryHistoryItems = rawItems.map((item, idx) => ({
              ...item,
              // 历史记录一律标记为非 current，避免类型混淆导致按钮误禁用
              is_current: false,
              id:
                item && item.id !== undefined
                  ? item.id
                  : `h-${item?.created_at || Date.now()}-${idx}`,
            }));
            const currentVersion = {
              id: "__current__",
              is_current: true,
              created_at: Math.floor(Date.now() / 1000),
              snapshot: JSON.parse(
                JSON.stringify(this.activeEditorEntry || {}),
              ),
            };
            this.entryHistoryVersions = [
              currentVersion,
              ...this.entryHistoryItems,
            ];
            this.entryHistorySelection = {
              left: this.entryHistoryItems[0] || null,
              right: currentVersion,
            };
            this.updateEntryHistoryDiff();
          } else {
            alert("读取历史失败: " + (res.msg || "未知错误"));
          }
        })
        .catch((e) => {
          alert("读取历史失败: " + e);
        })
        .finally(() => {
          this.isEntryHistoryLoading = false;
        });
    },

    canRestoreEntryFromSelection() {
      const left = this.entryHistorySelection.left;
      if (!left) return false;
      if (left.is_current === true) return false;
      return !!left.snapshot;
    },

    restoreEntryFromSelectedHistory() {
      const target = this.entryHistorySelection.left;
      if (!this.canRestoreEntryFromSelection()) {
        alert("请在左侧选择一个历史版本再恢复。");
        return;
      }
      this.restoreEntryFromHistory(target);
    },

    _resolveEntryRestoreTarget(uid) {
      const targetUid = String(uid || this.entryHistoryTargetUid || "").trim();
      const current = this.activeEditorEntry;
      if (current && targetUid) {
        const currentUid = String(current[this.entryUidField] || "").trim();
        if (currentUid && currentUid === targetUid) {
          return { entry: current, index: this.currentWiIndex };
        }
      }

      const arr = this.getWIArrayRef();
      if (!Array.isArray(arr) || !arr.length || !targetUid)
        return { entry: current, index: this.currentWiIndex };
      const idx = arr.findIndex(
        (it) => String(it?.[this.entryUidField] || "").trim() === targetUid,
      );
      if (idx >= 0) return { entry: arr[idx], index: idx };
      return { entry: current, index: this.currentWiIndex };
    },

    restoreEntryFromHistory(item) {
      if (!item || !item.snapshot) return;
      const keepUid = String(
        this.entryHistoryTargetUid || item.snapshot?.[this.entryUidField] || "",
      ).trim();
      const resolved = this._resolveEntryRestoreTarget(keepUid);
      const target = resolved.entry;
      if (!target) {
        alert("未找到可恢复的目标条目，请重新打开条目时光机后再试。");
        return;
      }
      if (!confirm("确定回滚当前条目到该历史版本吗？")) return;
      const keepId = target.id;
      const keepRestoreUid = target[this.entryUidField] || keepUid;
      const restored = JSON.parse(JSON.stringify(item.snapshot));

      Object.keys(target).forEach((k) => delete target[k]);
      Object.assign(target, restored);

      if (keepId !== undefined) target.id = keepId;
      if (keepRestoreUid) target[this.entryUidField] = keepRestoreUid;
      if (typeof resolved.index === "number" && resolved.index >= 0) {
        this.currentWiIndex = resolved.index;
      }

      this.showEntryHistoryModal = false;
      this.$store.global.showToast("条目已回滚，请记得保存世界书", 2200, "backup-rollback");
    },

    getTotalWiTokens() {
      // 必须传入当前的条目数组
      return getTotalWiTokens(this.getWIArrayRef());
    },

    async _createWholeWorldbookSnapshot() {
      const payload = this._getAutoSavePayload();
      const isLorebook = payload.type === "lorebook";
      const res = await apiCreateSnapshot({
        id: payload.id,
        type: isLorebook ? "lorebook" : "card",
        file_path: payload.file_path || "",
        label: "",
        // 整本保存前快照：备份磁盘上的“旧文件状态”，避免首版被覆盖
        content: null,
        compact: isLorebook,
      });
      return res;
    },

    async _ensureInitialBaselineSnapshot() {
      const payload = this._getAutoSavePayload();
      const isLorebook = payload.type === "lorebook";
      const snapshotType = isLorebook ? "lorebook" : "card";

      const snapshotRes = await apiCreateSnapshot({
        id: payload.id,
        type: snapshotType,
        file_path: payload.file_path || "",
        label: "INIT",
        content: null,
        compact: isLorebook,
      });

      if (!snapshotRes || !snapshotRes.success) {
        throw new Error(
          snapshotRes && snapshotRes.msg ? snapshotRes.msg : "创建初始快照失败",
        );
      }
      return { created: true };
    },

    async _ensureInitialBaselineOnEnter() {
      if (this.initialSnapshotChecked) return;
      if (!this.initialSnapshotInitPromise) {
        this.initialSnapshotInitPromise = this._ensureInitialBaselineSnapshot()
          .then((res) => {
            this.initialSnapshotChecked = true;
            if (res && res.created)
              this.$store.global.showToast("已记录本次编辑初始版本", 1800, "link-source");
            return res;
          })
          .catch((e) => {
            this.initialSnapshotChecked = false;
            throw e;
          })
          .finally(() => {
            this.initialSnapshotInitPromise = null;
          });
      }
      return this.initialSnapshotInitPromise;
    },

    _nextTickPromise() {
      return new Promise((resolve) => {
        this.$nextTick(() => resolve());
      });
    },

    async _flushPendingEditorInput() {
      const active = document.activeElement;
      if (!active || !this.$root || !this.$root.contains(active)) return;

      const tag = active.tagName;
      const isField = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (!isField) return;

      try {
        active.dispatchEvent(new Event("input", { bubbles: true }));
        active.dispatchEvent(new Event("change", { bubbles: true }));
        if (typeof active.blur === "function") active.blur();
      } catch (e) {
        console.warn("Flush editor input failed:", e);
      }

      await this._nextTickPromise();
    },

    _getSnapshotContext() {
      const file = this.editingWiFile || {};

      if (file.type === "embedded" || (!file.type && this.editingData?.id)) {
        return {
          id:
            this.editingData && this.editingData.id
              ? this.editingData.id
              : file.card_id || "",
          type: "card",
          file_path: "",
        };
      }

      return {
        id: file.id || file.path || file.file_path || "",
        type: "lorebook",
        file_path: file.file_path || file.path || "",
      };
    },

    async _cleanupInitBackupsOnExit() {
      const pendingInit = this.initialSnapshotInitPromise;
      if (pendingInit) {
        try {
          await pendingInit;
        } catch (e) {
          console.warn("Init snapshot promise rejected before cleanup:", e);
        }
      }

      const ctx = this._getSnapshotContext();
      if (!ctx.id) return;
      try {
        const res = await apiCleanupInitBackups({
          id: ctx.id,
          type: ctx.type,
          file_path: ctx.file_path,
          // 保留最近一个 INIT，避免“仅保存条目”后时光机无历史
          keep_latest: 1,
        });
        if (!res || !res.success) {
          console.warn(
            "Cleanup INIT backups failed:",
            res && res.msg ? res.msg : res,
          );
        }
      } catch (e) {
        console.warn("Cleanup INIT backups error:", e);
      }
    },

    async _ensureInitSnapshotReadyForSave() {
      if (this.initialSnapshotInitPromise) {
        try {
          await this.initialSnapshotInitPromise;
        } catch (e) {
          console.warn("Init snapshot on enter failed:", e);
        }
        return;
      }

      if (!this.initialSnapshotChecked) {
        try {
          await this._ensureInitialBaselineOnEnter();
        } catch (e) {
          console.warn("Init snapshot retry before save failed:", e);
        }
      }
    },

    saveWholeWorldbook() {
      if (this.editingWiFile && this.editingWiFile.type === "embedded") {
        return this.saveChanges(true);
      }
      return this.saveWiFileChanges(true);
    },

    saveCurrentWorldbook() {
      if (this.editingWiFile && this.editingWiFile.type === "embedded") {
        return this.saveChanges();
      }
      return this.saveWiFileChanges();
    },

    async saveChanges(withSnapshot = false) {
      // 如果不是内嵌模式，但误调了此方法，转给文件保存逻辑
      if (!this.editingWiFile || this.editingWiFile.type !== "embedded") {
        return this.saveWiFileChanges(withSnapshot);
      }

      await this._flushPendingEditorInput();
      this._ensureEntryUids();
      this.isSaving = true;
      this._markEditorSaveStarted(withSnapshot ? "正在保存整本" : "正在保存修改");
      await this._ensureInitSnapshotReadyForSave();

      if (withSnapshot) {
        try {
          const snapshotRes = await this._createWholeWorldbookSnapshot();
          if (!snapshotRes || !snapshotRes.success) {
            this.isSaving = false;
            this._markEditorSaveError("整本保存失败");
            alert(
              "整本保存失败：无法创建版本快照" +
                (snapshotRes && snapshotRes.msg ? ` (${snapshotRes.msg})` : ""),
            );
            return;
          }
        } catch (e) {
          this.isSaving = false;
          this._markEditorSaveError("整本保存失败");
          alert("整本保存失败：创建版本快照异常 - " + e);
          return;
        }
      }

      // 1. 深拷贝当前编辑数据
      const cardData = JSON.parse(JSON.stringify(this.editingData));

      // 2. 使用工具函数清洗 V3 数据结构 (构建标准角色卡 Payload)
      const cleanData = getCleanedV3Data(cardData);

      // 3. 构造发送给 update_card 的完整数据
      const payload = {
        id: this.editingData.id, // 角色卡 ID
        ...cleanData,
        // 1. 映射后端专用字段名
        char_name: cleanData.name || this.editingData.char_name,

        // 2. 传递文件名 (防止意外重命名或丢失扩展名)
        new_filename: this.editingData.filename,

        // 3. 补全 UI 专属字段 (如果不传，后端会将其清空)
        ui_summary: this.editingData.ui_summary || "",
        source_link: this.editingData.source_link || "",
        resource_folder: this.editingData.resource_folder || "",
        source_revision: this.editingData.source_revision || "",

        // 4. Bundle 状态透传 (保持包模式状态不丢失)
        save_ui_to_bundle: this.editingData.is_bundle,
        bundle_dir: this.editingData.is_bundle
          ? this.editingData.bundle_dir
          : undefined,
        // 显式确保 character_book 被包含（虽然 getCleanedV3Data 也会包含，但双重保险）
        character_book: cleanData.character_book,
      };

      updateCard(payload)
        .then((res) => {
          this.isSaving = false;
          if (res.success) {
            this.editingData.source_revision =
              res.updated_card?.source_revision ||
              this.editingData.source_revision ||
              "";
            if (withSnapshot) {
              this.$store.global.showToast("已保存整本并生成回滚版本", 2200, "settings-save");
            } else {
              this.$store.global.showToast("条目修改已保存", 1800, "settings-save");
            }
            this._markEditorSaveSuccess(withSnapshot ? "整本已保存" : "修改已保存");

            // 通知外部 (如卡片列表或详情页) 刷新数据
            window.dispatchEvent(
              new CustomEvent("card-updated", { detail: res.updated_card }),
            );

            // 更新自动保存的基准
            if (autoSaver && typeof autoSaver.initBaseline === "function") {
              autoSaver.initBaseline(this.editingData);
            }
            if (this.editingWiFile?.type === "embedded") {
              const savedWorldbookJson = JSON.stringify(
                this.editingData.character_book,
              );
              this.embeddedWorldbookBaselineJson =
                this._serializeEditorBookForComparison(
                  this.editingData.character_book,
                );
              this.embeddedWorldbookLastSavedJson = savedWorldbookJson;
            }
          } else {
            this._markEditorSaveError("保存失败");
            alert("保存失败: " + res.msg);
          }
        })
        .catch((e) => {
          this.isSaving = false;
          this._markEditorSaveError("请求错误");
          alert("请求错误: " + e);
        });
    },

    // === 辅助：生成自动保存的 Payload ===
    _getAutoSavePayload() {
      // 场景 A: 角色卡内嵌模式
      if (this.editingWiFile && this.editingWiFile.type === "embedded") {
        // 如果是内嵌，我们需要保存整个 Card 数据 (以此确保一致性)
        const contentToSave = getCleanedV3Data(this.editingData);
        return {
          id: this.editingData.id, // 角色卡 ID
          type: "card",
          content: contentToSave,
          file_path: "",
        };
      }

      // 场景 B: 独立世界书文件
      const name = this.editingData.character_book?.name || "World Info";
      const contentToSave = toStV3Worldbook(
        this.editingData.character_book,
        name,
      );

      return {
        id: this.editingWiFile ? this.editingWiFile.id : "unknown",
        type: "lorebook",
        content: contentToSave,
        file_path: this.editingWiFile
          ? this.editingWiFile.path || this.editingWiFile.file_path
          : "",
      };
    },

    // === 核心打开逻辑 ===

    // 打开编辑器 (适配三种来源: global, resource, embedded)
    openWorldInfoEditor(item) {
      this.isLoading = true;
      this.wiEntryFilterQuery = "";
      const targetId = item.id;
      const openRequestToken = ++this.openWorldInfoEditorRequestToken;
      this.editingWiFile = item;
      this.initialSnapshotChecked = false;
      this.initialSnapshotInitPromise = null;
      this.embeddedWorldbookBaselineJson = null;
      this.embeddedWorldbookLastSavedJson = null;

      const handleSuccess = (dataObj, source) => {
        // === 强制执行归一化 ===
        // 不管是 embedded 还是 global，统统过一遍清洗
        // normalizeWiBook 会为每个条目分配索引 id（0,1,2,3...）
        if (dataObj.character_book) {
          dataObj.character_book = normalizeWiBook(
            dataObj.character_book,
            dataObj.char_name || "WI",
          );
        }

        // 赋值给响应式对象
        this.editingData = dataObj;
        this.editingData.ui_summary =
          this.editingWiFile?.ui_summary ||
          item?.ui_summary ||
          dataObj?.ui_summary ||
          "";
        this.editingWiFile = {
          ...item,
          ...(this.editingWiFile || {}),
        };
        this._ensureEntryUids();
        this._setEditorBaseline();
        this.editorSaveState = "idle";
        this.editorSaveMessage = "已载入";
        this.editorLastSavedAt = "";
        this.embeddedWorldbookBaselineJson =
          this.editingWiFile?.type === "embedded"
            ? this._serializeEditorBookForComparison(
                this.editingData.character_book,
              )
            : null;
        this.embeddedWorldbookLastSavedJson = null;
        let targetIndex = 0;
        if (typeof item.jumpToIndex === "number" && item.jumpToIndex >= 0) {
          targetIndex = item.jumpToIndex;
        }
        this.currentWiIndex = targetIndex;
        const targetEntry = this.getWIArrayRef()[targetIndex];
        this.currentWiEntryKey = targetEntry
          ? this.getWiEntryIdentity(targetEntry, targetIndex)
          : "";
        this.isLoading = false;

        this.openFullScreenWI();

        // 滚动到选中项
        if (targetIndex >= 0) {
          this.$nextTick(() => {
            // 稍微延迟以等待列表渲染
            setTimeout(() => {
              // 再次强制设置一次 index
              this.currentWiIndex = targetIndex;
              const targetEntry = this.getWIArrayRef()[targetIndex];
              this.currentWiEntryKey = targetEntry
                ? this.getWiEntryIdentity(targetEntry, targetIndex)
                : "";

              const elId = `wi-item-${targetIndex}`;
              const el = document.getElementById(elId);
              if (el) {
                el.scrollIntoView({ behavior: "auto", block: "center" }); // 使用 auto 瞬间定位，避免 smooth 还没滚到就停止
                el.classList.add("color-accent-soft", "color-text-accent"); // 临时高亮
                setTimeout(
                  () => el.classList.remove("color-accent-soft", "color-text-accent"),
                  800,
                );
              }
            }, 100);
          });
        }
      };

      // 1. 内嵌类型 (Embedded): 获取角色卡数据
      if (item.type === "embedded") {
        // 如果传递了character_book数据（从detailModal同步过来的），直接使用
        if (item.character_book && item.editingData) {
          const cardData = JSON.parse(JSON.stringify(item.editingData));

          // 确保 character_book 存在
          if (!cardData.character_book) {
            cardData.character_book = {
              name: item.name || "World Info",
              entries: [],
            };
          } else if (Array.isArray(cardData.character_book)) {
            // 兼容 V2 数组
            cardData.character_book = {
              name: item.name || "World Info",
              entries: cardData.character_book,
            };
          }

          this.editingData = cardData;
          this.editingWiFile = item;
          this.currentWiIndex = 0;
          this.isEditingClipboard = false;
          this.currentClipboardIndex = -1;

          handleSuccess(cardData, "Embedded");
          return;
        }

        // 如果没有传递数据（兼容旧逻辑），从服务器加载
        getCardDetail(item.card_id)
          .then((res) => {
            if (openRequestToken !== this.openWorldInfoEditorRequestToken)
              return;
            if (!this.editingWiFile || this.editingWiFile.id !== targetId)
              return;
            if (res.success && res.card) {
              // 这是一个角色卡对象，character_book 在其中
              this.editingData = res.card;

              // 确保 character_book 存在
              if (!this.editingData.character_book) {
                this.editingData.character_book = {
                  name: item.name || "World Info",
                  entries: [],
                };
              } else if (Array.isArray(this.editingData.character_book)) {
                // 兼容 V2 数组
                this.editingData.character_book = {
                  name: item.name || "World Info",
                  entries: this.editingData.character_book,
                };
              }

              this.editingWiFile = {
                ...item,
                source_revision:
                  res.card?.source_revision || item.source_revision || "",
              };
              this.currentWiIndex = 0;
              this.isEditingClipboard = false;
              this.currentClipboardIndex = -1;

              handleSuccess(res.card, "Embedded");
            } else {
              alert("无法加载关联的角色卡数据");
            }
          })
          .catch((e) => {
            if (openRequestToken !== this.openWorldInfoEditorRequestToken)
              return;
            if (!this.editingWiFile || this.editingWiFile.id !== targetId)
              return;
            this.isLoading = false;
            alert("加载失败: " + e);
          });
        return;
      } else {
        // 独立文件 (Global / Resource)
        getWorldInfoDetail({
          id: item.id,
          source_type: item.type, // list 返回的是 type
          file_path: item.path,
          force_full: true,
        })
          .then((res) => {
            if (openRequestToken !== this.openWorldInfoEditorRequestToken)
              return;
            if (!this.editingWiFile || this.editingWiFile.id !== targetId)
              return;
            if (res.success) {
              // 归一化数据
              const bookData = normalizeWiBook(res.data, "");
              this.editingData.character_book = bookData;

              this.editingWiFile = {
                ...item,
                source_revision:
                  res.source_revision || item.source_revision || "",
                ui_summary: res.ui_summary || item.ui_summary || "",
              };
              this.currentWiIndex = 0;
              this.isEditingClipboard = false;
              this.currentClipboardIndex = -1;
              const dummyObj = {
                id: null,
                character_book: res.data,
                ui_summary: res.ui_summary || item.ui_summary || "",
              };
              handleSuccess(dummyObj, "Global/Resource");
            } else {
              alert(res.msg);
            }
          })
          .catch((e) => {
            if (openRequestToken !== this.openWorldInfoEditorRequestToken)
              return;
            if (!this.editingWiFile || this.editingWiFile.id !== targetId)
              return;
            this.isLoading = false;
            alert("加载失败: " + e);
          });
      }
    },

    // 打开独立文件 (兼容接口)
    openWorldInfoFile(item) {
      this.isLoading = true;
      this.wiEntryFilterQuery = "";
      const targetId = item.id;
      this.editingWiFile = item;
      this.openWorldInfoFileRequestToken += 1;
      const requestToken = this.openWorldInfoFileRequestToken;
      this.initialSnapshotChecked = false;
      this.initialSnapshotInitPromise = null;
      this.embeddedWorldbookBaselineJson = null;
      this.embeddedWorldbookLastSavedJson = null;
      getWorldInfoDetail({
        id: item.id,
        source_type: item.source_type,
        file_path: item.file_path,
        force_full: true,
      })
        .then((res) => {
          if (requestToken !== this.openWorldInfoFileRequestToken) return;
          if (!this.editingWiFile || this.editingWiFile.id !== targetId) return;
          this.isLoading = false;
          if (res.success) {
            // normalizeWiBook 会为每个条目分配索引 id（0,1,2,3...）
            const book = normalizeWiBook(res.data, item.name || "World Info");
            this.editingData.character_book = book;
            this.editingData.ui_summary =
              res.ui_summary || item.ui_summary || "";
            this.editingWiFile = item;
            this.editingWiFile.source_revision = res.source_revision || "";
            this._ensureEntryUids();
            this._setEditorBaseline();
            this.editorSaveState = "idle";
            this.editorSaveMessage = "已载入";
            this.editorLastSavedAt = "";
            this.openFullScreenWI();
            this.$nextTick(async () => {
              if (this.initialSnapshotInitPromise) {
                try {
                  await this.initialSnapshotInitPromise;
                } catch (e) {
                  console.warn(
                    "Init snapshot on enter failed before auto-save start:",
                    e,
                  );
                }
              }
              autoSaver.initBaseline(this.editingData);
              autoSaver.start(
                () => this.editingData,
                () => this._getAutoSavePayload(),
              );
            });
          } else {
            this.isLoading = false;
            alert(res.msg);
          }
        })
        .catch((e) => {
          if (requestToken !== this.openWorldInfoFileRequestToken) return;
          if (!this.editingWiFile || this.editingWiFile.id !== targetId) return;
          this.isLoading = false;
          alert("加载失败: " + e);
        });
    },

    openFullScreenWI() {
      this.showFullScreenWI = true;
      this.wiEntryFilterQuery = "";
      this.editorPane = "content";
      this.rightTab = "settings";
      const isMobile = this.isEditorMobileViewport();
      this.showLeftList = !isMobile;
      this.showRightPanel = !isMobile;
      this.$nextTick(() => this._initEditorActionRail());
      // 确保选中第一项
      const entries = this.getWIArrayRef();
      const hasSelectedEntry =
        this.currentWiEntryKey &&
        entries.some(
          (entry, index) =>
            this.getWiEntryIdentity(entry, index) === this.currentWiEntryKey,
        );
      const firstEntry = this.getSortedWIEntries()[0];
      if (firstEntry && !hasSelectedEntry) {
        this.currentWiIndex = this._resolveWiEntryIndex(firstEntry);
        this.currentWiEntryKey = this.getWiEntryIdentity(firstEntry);
      }
      // 加载剪切板
      this.loadWiClipboard();

      // 进入编辑器时自动生成“本次编辑起点”的 INIT 快照
      this._ensureInitialBaselineOnEnter().catch((e) => {
        console.warn("Auto init snapshot failed:", e);
      });
    },

    // === 数据存取 ===

    getWIEntries() {
      return this.getWIArrayRef();
    },

    // 获取当前编辑器应该显示的数据 (Computed)
    get activeEditorEntry() {
      if (this.isEditingClipboard) {
        if (
          this.currentClipboardIndex >= 0 &&
          this.currentClipboardIndex < this.wiClipboardItems.length
        ) {
          return this.wiClipboardItems[this.currentClipboardIndex].content;
        }
        return null;
      } else {
        const arr = this.getWIArrayRef();
        if (this.currentWiEntryKey) {
          const selected = arr.find((entry, index) =>
            this.getWiEntryIdentity(entry, index) === this.currentWiEntryKey,
          );
          if (selected) return selected;
        }
        if (this.currentWiIndex >= 0 && this.currentWiIndex < arr.length) {
          this.currentWiEntryKey = this.getWiEntryIdentity(
            arr[this.currentWiIndex],
            this.currentWiIndex,
          );
          return arr[this.currentWiIndex];
        }
        return null;
      }
    },

    // === 保存逻辑 ===

    buildEditingWorldInfoNotePayload(summary) {
      const file = this.editingWiFile || {};
      const payload = {
        source_type: file.type,
        summary,
      };

      if (file.type === "embedded") {
        payload.card_id = this.editingData.id || file.card_id;
      } else {
        payload.file_path = file.file_path || file.path;
      }
      return payload;
    },

    getEditingWorldInfoNoteLabel() {
      return this.editingWiFile?.type === "embedded"
        ? "角色卡备注"
        : "本地备注";
    },

    buildEmbeddedEditingNotePayload(summary) {
      return {
        id: this.editingData?.id || this.editingWiFile?.card_id,
        ui_summary: summary,
        source_link: "",
        resource_folder: "",
        source_revision: this.editingData.source_revision || "",
        ui_only: true,
      };
    },

    emitEditingWorldInfoNoteUpdated(uiSummary) {
      if (!this.editingWiFile) return;
      const detail = {
        ...this.editingWiFile,
        ui_summary: uiSummary || "",
      };
      this.editingWiFile = detail;
      this.editingData.ui_summary = uiSummary || "";
      window.dispatchEvent(new CustomEvent("wi-note-updated", { detail }));
      window.dispatchEvent(new CustomEvent("refresh-wi-list"));
    },

    async saveEditingWorldInfoNote() {
      if (!this.editingWiFile) return;
      this._markEditorSaveStarted("正在保存备注");
      try {
        let res;
        if (this.editingWiFile.type === "embedded") {
          res = await updateCard(
            this.buildEmbeddedEditingNotePayload(
              this.editingData.ui_summary || "",
            ),
          );
        } else {
          res = await saveWorldInfoNote(
            this.buildEditingWorldInfoNotePayload(
              this.editingData.ui_summary || "",
            ),
          );
        }
        if (!res?.success) {
          this._markEditorSaveError("备注保存失败");
          alert(`保存备注失败: ${res?.msg || "未知错误"}`);
          return;
        }
        const nextSummary =
          res?.updated_card?.ui_summary || res?.ui_summary || "";
        this.editingData.source_revision =
          res?.updated_card?.source_revision ||
          this.editingData.source_revision ||
          "";
        this.emitEditingWorldInfoNoteUpdated(nextSummary);
        this.$store.global.showToast(
          `${this.getEditingWorldInfoNoteLabel()}已保存`,
          1600,
          "settings-save",
        );
        this._markEditorSaveSuccess("备注已保存");
      } catch (e) {
        this._markEditorSaveError("备注保存失败");
        alert(`保存备注失败: ${e}`);
      }
    },

    openEditingWorldInfoNotePreview() {
      const content = this.editingData?.ui_summary || "";
      if (!content) return;
      this.openMarkdownView(content);
    },

    async saveWiFileChanges(withSnapshot = false) {
      if (!this.editingWiFile) return;

      // 如果是内嵌模式，实际上应该调用 UpdateCard
      if (this.editingWiFile.type === "embedded") {
        alert(
          "内嵌世界书将随角色卡自动保存 (Auto-save) 或请关闭后点击角色保存。",
        );
        return;
      }

      await this._flushPendingEditorInput();
      this._ensureEntryUids();
      this.isSaving = true;
      this._markEditorSaveStarted(withSnapshot ? "正在保存整本" : "正在保存修改");
      await this._ensureInitSnapshotReadyForSave();

      if (withSnapshot) {
        try {
          const snapshotRes = await this._createWholeWorldbookSnapshot();
          if (!snapshotRes || !snapshotRes.success) {
            this.isSaving = false;
            this._markEditorSaveError("整本保存失败");
            alert(
              "整本保存失败：无法创建版本快照" +
                (snapshotRes && snapshotRes.msg ? ` (${snapshotRes.msg})` : ""),
            );
            return;
          }
        } catch (e) {
          this.isSaving = false;
          this._markEditorSaveError("整本保存失败");
          alert("整本保存失败：创建版本快照异常 - " + e);
          return;
        }
      }

      // 独立文件保存
      const contentToSave = toStV3Worldbook(
        this.editingData.character_book,
        this.editingData.character_book?.name ||
          this.editingWiFile?.name ||
          "World Info",
      );

      saveWorldInfo({
        save_mode: "overwrite",
        file_path: this.editingWiFile.file_path || this.editingWiFile.path,
        content: contentToSave,
        compact: true,
        source_revision: this.editingWiFile?.source_revision || "",
      })
        .then((res) => {
          this.isSaving = false;
          if (res.success) {
            this.editingWiFile.source_revision =
              res.source_revision || this.editingWiFile?.source_revision || "";
            window.dispatchEvent(new CustomEvent("refresh-wi-list"));
            if (withSnapshot) {
              this.$store.global.showToast("已保存整本并生成回滚版本", 2200, "settings-save");
            } else {
              this.$store.global.showToast("条目修改已保存", 1800, "settings-save");
            }
            this._markEditorSaveSuccess(withSnapshot ? "整本已保存" : "修改已保存");
            autoSaver.initBaseline(this.editingData);
          } else {
            this._markEditorSaveError("保存失败");
            alert("保存失败: " + res.msg);
          }
        })
        .catch((e) => {
          this.isSaving = false;
          this._markEditorSaveError("请求错误");
          alert("请求错误: " + e);
        });
    },

    saveAsGlobalWi() {
      const name = prompt(
        "请输入新世界书名称:",
        this.editingData.character_book.name || "New World Book",
      );
      if (!name) return;

      this._ensureEntryUids();
      const contentToSave = toStV3Worldbook(
        this.editingData.character_book,
        name,
      );
      contentToSave.name = name; // 确保内部名一致

      saveWorldInfo({
        save_mode: "new_global",
        name: name,
        content: contentToSave,
        compact: true,
      }).then((res) => {
        if (res.success) {
          alert("已另存为全局世界书！");
          window.dispatchEvent(new CustomEvent("refresh-wi-list"));
        } else {
          alert(res.msg);
        }
      });
    },

    exportWorldBookSingle() {
      const book = this.editingData.character_book || {
        entries: [],
        name: "World Info",
      };
      this.downloadWorldInfoJson(book, book.name);
    },

    // === 剪切板逻辑 ===

    loadWiClipboard() {
      clipboardList().then((res) => {
        if (res.success) {
          // 1. 先清空，给 Alpine 一个明确的信号
          this.wiClipboardItems = [];

          // 2. 在 nextTick 中赋值，确保 DOM 准备好重绘
          this.$nextTick(() => {
            this.wiClipboardItems = res.items;

            // 3. 强制确保侧边栏是展开的，否则用户看不到
            if (this.wiClipboardItems.length > 0) {
              this.showWiClipboard = true;
            }
          });
        }
      });
    },

    saveClipboardItem() {
      if (!this.isEditingClipboard || this.currentClipboardIndex === -1) return;
      const item = this.wiClipboardItems[this.currentClipboardIndex];
      if (!item) return;

      // 更新 (Overwrite)
      this._addWiClipboardRequest(item.content, item.db_id);
      alert("剪切板条目已更新");
    },

    copyWiToClipboard(entry) {
      // 1. 确定目标数据：优先使用传入参数，否则使用当前编辑器内容
      let targetData = entry;

      // 如果传入的是 Event 对象（点击事件），或者为空，则使用当前编辑器数据
      if (
        !targetData ||
        targetData instanceof Event ||
        (targetData.target && targetData.type)
      ) {
        targetData = this.activeEditorEntry;
      }

      if (!targetData) {
        alert("无法获取要复制的条目内容");
        return;
      }

      // 2. 深度拷贝并清洗 (移除 Proxy，转为纯 JSON 对象)
      let copy;
      try {
        // 使用 JSON 序列化再反序列化，彻底斩断引用和 Proxy
        copy = JSON.parse(JSON.stringify(targetData));
      } catch (e) {
        console.error("Copy failed:", e);
        return;
      }

      // 3. 清理 ID 和 UID，确保被视为新条目
      // 注意：必须显式设置为 undefined 或 delete，防止后端复用 ID
      delete copy.id;
      delete copy.uid;
      delete copy[this.entryUidField];

      // 4. 确保 content 字段存在
      if (copy.content === undefined || copy.content === null)
        copy.content = "";

      // 5. 发送请求
      this._addWiClipboardRequest(copy);
    },

    _addWiClipboardRequest(entry, overwriteId = null) {
      // 获取当前焦点元素
      const activeEl = document.activeElement;
      const isSafeButton =
        activeEl &&
        activeEl.tagName === "BUTTON" &&
        !activeEl.classList.contains("wi-list-item");
      const originalHtml = isSafeButton ? activeEl.innerHTML : "";
      if (isSafeButton && !overwriteId) {
        activeEl.innerHTML =
          '<img class="ui-icon ui-icon--sm ui-loading-icon" src="/static/icons/loading-animation.svg" alt="" aria-hidden="true" draggable="false">';
      }

      clipboardAdd(entry, overwriteId)
        .then((res) => {
          if (res.success) {
            this.wiClipboardItems = [];
            setTimeout(() => {
              this.loadWiClipboard();
            }, 50);
            this.wiClipboardOverwriteMode = false;
            this.clipboardPendingEntry = null;
            if (!this.showWiClipboard) this.showWiClipboard = true;

            this.$store.global.showToast("已复制到全局剪切板", 3000, "clipboard");
          } else if (res.code === "FULL") {
            this.wiClipboardOverwriteMode = true;
            this.clipboardPendingEntry = entry;
            if (!this.showWiClipboard) this.showWiClipboard = true;
          } else {
            alert("保存失败: " + res.msg);
          }
        })
        .finally(() => {
          if (isSafeButton && !overwriteId) activeEl.innerHTML = originalHtml;
        });
    },

    addWiEntryFromClipboard(content) {
      if (
        typeof this.isWiEntryFilterActive === "function" &&
        this.isWiEntryFilterActive()
      ) {
        this.$store?.global?.showToast?.(
          "请先清空条目搜索后再插入剪切板条目",
          1800,
        );
        return false;
      }

      const arr = this.getWIArrayRef();
      const newEntry = JSON.parse(JSON.stringify(content));
      // 不预先设置 id，在插入后统一重新分配
      delete newEntry.uid;
      delete newEntry.id;
      newEntry[this.entryUidField] = this._generateEntryUid();
      newEntry.st_source_id = this._getWiSourceUidCandidate(arr);
      newEntry.displayIndex = getNextWiDisplayIndex(arr);

      const sortMode = this.getWiSortMode();
      let visibleInsertPos = null;
      if (sortMode === "custom") {
        const ordered = this.getSortedWIEntries();
        const currentVisibleIndex = this.currentWiEntryKey
          ? ordered.findIndex(
              (entry, index) =>
                this.getWiEntryIdentity(entry, index) === this.currentWiEntryKey,
            )
          : -1;
        visibleInsertPos =
          currentVisibleIndex >= 0 ? currentVisibleIndex + 1 : ordered.length;
        arr.push(newEntry);
        ordered.splice(visibleInsertPos, 0, newEntry);
        setWiCustomDisplayIndexes(ordered);
      } else {
        let insertPos = this.currentWiIndex + 1;
        if (insertPos < 0 || insertPos > arr.length) insertPos = arr.length;
        arr.splice(insertPos, 0, newEntry);
      }

      this.currentWiIndex = this._resolveWiEntryIndex(newEntry);
      this.currentWiEntryKey = this.getWiEntryIdentity(newEntry, this.currentWiIndex);
      this.isEditingClipboard = false;

      this._syncWiEntryIndexes(arr);

      this.$nextTick(() => {
        const visibleIndex = this.getSortedWIEntries().findIndex(
          (entry) => entry === newEntry,
        );
        const item = document.querySelectorAll(".wi-list-item")[visibleIndex];
        if (item) item.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    },

    deleteWiClipboardItem(dbId) {
      if (!confirm("删除此剪切板条目？")) return;
      clipboardDelete(dbId).then(() => this.loadWiClipboard());
    },

    clearWiClipboard() {
      if (!confirm("清空所有剪切板内容？")) return;
      clipboardClear().then(() => this.loadWiClipboard());
    },

    selectMainWiItem(entryOrIndex, viewIndex = null) {
      this.isEditingClipboard = false;
      this.currentClipboardIndex = -1;
      const arr = this.getWIArrayRef();
      const rawIndex = this._resolveWiEntryIndex(entryOrIndex);
      if (rawIndex < 0) return;
      this.currentWiIndex = rawIndex;
      this.currentWiEntryKey = this.getWiEntryIdentity(arr[rawIndex], rawIndex);
      if (this.isEditorMobileViewport()) {
        this.editorPane = "content";
        this.showLeftList = false;
        this.showRightPanel = false;
      }
    },

    selectClipboardItem(index) {
      // 覆写模式检查
      if (this.wiClipboardOverwriteMode) {
        const item = this.wiClipboardItems[index];
        if (confirm(`确定要覆盖 "${item.content.comment || "未命名"}" 吗？`)) {
          this._addWiClipboardRequest(this.clipboardPendingEntry, item.db_id);
        }
        return;
      }
      this.isEditingClipboard = true;
      this.currentClipboardIndex = index;
      this.currentWiIndex = -1;
      if (this.isEditorMobileViewport()) {
        this.editorPane = "content";
        this.showLeftList = false;
        this.showRightPanel = false;
      }
    },

    exitClipboardEdit() {
      this.isEditingClipboard = false;
      this.currentClipboardIndex = -1;
      // 恢复之前选中的主条目 (如果有)
      const arr = this.getWIArrayRef();
      if (arr.length > 0 && this.currentWiIndex === -1) {
        this.currentWiIndex = 0;
      }
    },

    // === 拖拽排序逻辑 ===

    // 1. 主列表拖拽
    wiDragStart(e, index) {
      if (
        typeof this.isWiEntryFilterActive === "function" &&
        this.isWiEntryFilterActive()
      ) {
        e?.preventDefault?.();
        if (e?.dataTransfer) e.dataTransfer.effectAllowed = "none";
        return false;
      }

      this.wiDraggingIndex = index;
      const visibleEntries = this.getSortedWIEntries();
      const item = visibleEntries[index];
      this.wiDraggingEntryKey = item
        ? this.getWiEntryIdentity(item, index)
        : "";
      e.dataTransfer.effectAllowed = "copyMove";
      e.dataTransfer.setData(
        "application/x-wi-entry-key",
        this.wiDraggingEntryKey,
      );

      if (item) {
        const exportItem = JSON.parse(JSON.stringify(item));
        e.dataTransfer.setData(
          "text/plain",
          JSON.stringify(exportItem, null, 2),
        );
      }
      const target = e.target;
      target.classList.add("dragging");
      const cleanup = () => {
        target.classList.remove("dragging");
        this.wiDraggingIndex = null;
        this.wiDraggingEntryKey = "";
      };
      target.addEventListener("dragend", cleanup, { once: true });
    },

    wiDragOver(e, index) {
      if (
        typeof this.isWiEntryFilterActive === "function" &&
        this.isWiEntryFilterActive()
      ) {
        e.currentTarget?.classList?.remove("drag-over-top", "drag-over-bottom");
        return;
      }

      e.preventDefault();
      const target = e.currentTarget;
      const rect = target.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;

      target.classList.remove("drag-over-top", "drag-over-bottom");
      if (e.clientY < midY) target.classList.add("drag-over-top");
      else target.classList.add("drag-over-bottom");
    },

    wiDragLeave(e) {
      e.currentTarget.classList.remove("drag-over-top", "drag-over-bottom");
    },

    wiDrop(e, targetIndex) {
      if (
        typeof this.isWiEntryFilterActive === "function" &&
        this.isWiEntryFilterActive()
      ) {
        e.preventDefault();
        e.stopPropagation();
        e.currentTarget?.classList?.remove(
          "drag-over-top",
          "drag-over-bottom",
          "dragging",
        );
        return false;
      }

      e.preventDefault();
      e.stopPropagation();
      const el = e.currentTarget;
      el.classList.remove("drag-over-top", "drag-over-bottom", "dragging");

      // A. 从剪切板拖入
      const clipData = e.dataTransfer.getData("application/x-wi-clipboard");
      if (clipData) {
        try {
          const content = JSON.parse(clipData);
          const arr = this.getWIArrayRef();
          const newEntry = JSON.parse(JSON.stringify(content));
          // 不预先设置 id，在插入后统一重新分配
          delete newEntry.uid;
          delete newEntry.id;
          newEntry[this.entryUidField] = this._generateEntryUid();
          newEntry.st_source_id = this._getWiSourceUidCandidate(arr);
          newEntry.displayIndex = getNextWiDisplayIndex(arr);

          const sortMode = this.getWiSortMode();
          if (sortMode === "custom") {
            const ordered = this.getSortedWIEntries();
            const insertIndex = Math.max(
              0,
              Math.min(Number(targetIndex) || 0, ordered.length),
            );
            arr.push(newEntry);
            ordered.splice(insertIndex, 0, newEntry);
            setWiCustomDisplayIndexes(ordered);
          } else {
            const visibleEntries = this.getSortedWIEntries();
            const targetEntry = visibleEntries[targetIndex];
            const rawTargetIndex = targetEntry
              ? this._resolveWiEntryIndex(targetEntry)
              : arr.length;
            arr.splice(
              rawTargetIndex < 0 ? arr.length : rawTargetIndex,
              0,
              newEntry,
            );
          }
          this.currentWiIndex = this._resolveWiEntryIndex(newEntry);
          this.currentWiEntryKey = this.getWiEntryIdentity(newEntry);
          this.isEditingClipboard = false;

          this._syncWiEntryIndexes(arr);
        } catch (err) {
          console.error(err);
        }
        return;
      }

      // B: ST 的自定义排序只持久化 displayIndex；其他模式不改写条目顺序。
      if (this.getWiSortMode() !== "custom") return;

      const sourceKey =
        e.dataTransfer.getData("application/x-wi-entry-key") ||
        this.wiDraggingEntryKey;
      if (!sourceKey) return;

      const ordered = this.getSortedWIEntries();
      const sourceIndex = ordered.findIndex(
        (entry, index) => this.getWiEntryIdentity(entry, index) === sourceKey,
      );
      if (sourceIndex < 0 || sourceIndex === targetIndex) return;

      const [itemToMove] = ordered.splice(sourceIndex, 1);
      const insertIndex = Math.max(
        0,
        Math.min(targetIndex > sourceIndex ? targetIndex - 1 : targetIndex, ordered.length),
      );
      ordered.splice(insertIndex, 0, itemToMove);
      setWiCustomDisplayIndexes(ordered);

      const rawIndex = this._resolveWiEntryIndex(itemToMove);
      if (rawIndex >= 0) {
        this.currentWiIndex = rawIndex;
        this.currentWiEntryKey = this.getWiEntryIdentity(itemToMove, rawIndex);
      }
    },

    // 2. 剪切板拖拽
    clipboardDragStart(e, item, idx) {
      e.dataTransfer.setData(
        "application/x-wi-clipboard",
        JSON.stringify(item.content),
      );
      e.dataTransfer.setData("text/plain", JSON.stringify(item.content));
      e.dataTransfer.effectAllowed = "copyMove";
      // 内部排序用
      e.dataTransfer.setData("application/x-wi-clipboard-index", idx);

      const target = e.target;
      target.classList.add("dragging");
      target.addEventListener(
        "dragend",
        () => {
          target.classList.remove("dragging");
        },
        { once: true },
      );
    },

    clipboardDropInside(e, targetIdx) {
      e.preventDefault();
      e.stopPropagation();
      const sourceIdxStr = e.dataTransfer.getData(
        "application/x-wi-clipboard-index",
      );
      if (sourceIdxStr) {
        const sourceIdx = parseInt(sourceIdxStr);
        if (sourceIdx === targetIdx) return;
        const items = [...this.wiClipboardItems];
        const [moved] = items.splice(sourceIdx, 1);
        items.splice(targetIdx, 0, moved);
        this.wiClipboardItems = items;
        const orderMap = items.map((i) => i.db_id);
        clipboardReorder(orderMap);
        return;
      }

      if (this.wiDraggingEntryKey) {
        const arr = this.getWIArrayRef();
        const rawEntry = arr.find(
          (entry, index) =>
            this.getWiEntryIdentity(entry, index) === this.wiDraggingEntryKey,
        );
        if (rawEntry) {
          this.copyWiToClipboard(rawEntry);
        }
      }
    },

    // === 处理剪切板容器的 Drop ===
    handleClipboardDropReorder(e) {
      e.preventDefault();
      e.stopPropagation();

      // 剪切板内部排序
      const isClipboardInternal = e.dataTransfer.types.includes(
        "application/x-wi-clipboard-index",
      );

      if (isClipboardInternal) {
        const sourceIdxStr = e.dataTransfer.getData(
          "application/x-wi-clipboard-index",
        );
        if (sourceIdxStr) {
          const sourceIdx = parseInt(sourceIdxStr);
          if (sourceIdx === this.wiClipboardItems.length - 1) return;

          const items = [...this.wiClipboardItems];
          const [moved] = items.splice(sourceIdx, 1);
          items.push(moved);

          this.wiClipboardItems = items;
          const orderMap = items.map((i) => i.db_id);
          clipboardReorder(orderMap);
        }
      } else {
        // 从左侧主列表拖入 (复制)
        if (
          this.wiDraggingEntryKey
        ) {
          const arr = this.getWIArrayRef();
          const rawEntry = arr.find(
            (entry, index) =>
              this.getWiEntryIdentity(entry, index) === this.wiDraggingEntryKey,
          );

          if (rawEntry) {
            // 深拷贝
            let entryCopy = null;
            try {
              entryCopy = JSON.parse(JSON.stringify(rawEntry));
            } catch (err) {
              return;
            }
            this.copyWiToClipboard(entryCopy);
          }
        }
      }
    },
  };
}
