/**
 * static/js/components/tagFilterModal.js
 * 标签管理模态框 (查看全库标签/删除标签)
 */

import {
  deleteTags,
  getTagManagementPrefs,
  getTagOrder,
  saveTagManagementPrefs,
  saveTagOrder,
  saveTagTaxonomy,
} from "../api/system.js";
import {
  DEFAULT_TAG_CATEGORY_COLOR,
  DEFAULT_TAG_CATEGORY_OPACITY,
  matchAnyTagSearchToken,
  splitTagTokens,
} from "../state.js";

export default function tagFilterModal() {
  return {
    // === 本地状态 ===
    showTagFilterModal: false,
    tagSearchQuery: "",
    customOrderEnabled: false,
    _syncClosing: false,
    mobileActiveTab: "filter",
    desktopWorkspaceMode: "filter",
    isDesktopWorkspaceFullscreen: false,
    isWorkspaceHelpOpen: false,
    lastWorkspaceHelpTrigger: null,
    isGovernanceDrawerOpen: false,
    isMobileToolsOpen: false,
    rememberLastTagView: false,
    lockTagLibrary: false,
    tagBlacklistInput: "",
    tagBlacklistTags: [],

    // 排序模式（仅全量标签库）
    isSortMode: false,
    sortWorkingTags: [],
    sortOriginalTags: [],
    sortWorkingCategoryOrder: [],
    sortOriginalCategoryOrder: [],
    sortWorkingCategoryTagOrder: {},
    sortOriginalCategoryTagOrder: {},
    dragTag: null,
    dragTagCategory: "",
    dragOverTag: null,
    dragCategory: null,
    dragOverCategory: null,

    // 删除模式状态
    isDeleteMode: false,
    selectedTagsForDeletion: [],
    showCategoryMode: false,
    selectedCategoryTags: [],
    categorySelectionInput: "",
    categoryDraftName: "",
    categoryDraftColor: DEFAULT_TAG_CATEGORY_COLOR,
    categoryDraftOpacity: DEFAULT_TAG_CATEGORY_OPACITY,
    showCategoryManager: false,
    categoryManagerDraftName: "",
    categoryManagerDraftColor: DEFAULT_TAG_CATEGORY_COLOR,
    categoryManagerDraftOpacity: DEFAULT_TAG_CATEGORY_OPACITY,
    selectedBlacklistTags: [],
    blacklistSelectionInput: "",
    categoryFilterInclude: [],
    categoryFilterExclude: [],
    mixedCategoryView: true,
    workspaceHelpSections: [
      { id: "overview", label: "总览" },
      { id: "search-view", label: "搜索与视图" },
      { id: "separator-rules", label: "分隔符规则" },
      { id: "filter-mode", label: "筛选模式" },
      { id: "batch-category-mode", label: "批量分类" },
      { id: "sort-mode", label: "排序模式" },
      { id: "delete-mode", label: "删除模式" },
      { id: "blacklist-mode", label: "黑名单模式" },
      { id: "category-manager-mode", label: "分类管理" },
      { id: "governance", label: "治理设置" },
      { id: "workflow", label: "推荐工作流" },
      { id: "faq", label: "常见问题" },
    ],
    activeWorkspaceHelpSection: "overview",
    workspaceHelpContent: {
      overview: {
        title: "工作台总览",
        description: "先浏览标签分布，再按模式完成筛选、整理和治理。",
        items: [
          "顶部区域提供当前模式、选中数量、帮助和工作台工具入口。",
          "筛选、排序、删除、黑名单和分类模式分别对应不同的标签处理流程。",
          "移动端标签池支持连续换行显示，点击标签即可完成当前模式的主要操作。",
        ],
      },
      "search-view": {
        title: "搜索与视图",
        description: "用搜索和视图切换快速缩小标签范围。",
        items: [
          "搜索框支持多个关键词并集匹配，适合先缩小范围再操作。",
          "混合视图适合快速点选标签；分组视图适合按分类核对标签分布。",
          "分类条支持包含、排除和恢复三态，Shift+点击可直接进入排除。",
        ],
      },
      "separator-rules": {
        title: "分隔符规则",
        description: "搜索和批量输入使用不同的分隔符语义。",
        items: [
          "搜索框中的 | 表示多个关键词并集匹配，不会写入标签库。",
          "批量分类、黑名单和手动输入会把 |、逗号或换行拆成多个标签名。",
          "斜杠是否作为分隔符取决于自动化相关设置；点击现有标签不会解析分隔符。",
        ],
      },
      "filter-mode": {
        title: "筛选模式",
        description: "通过包含、排除和取消三种状态调整当前结果。",
        items: [
          "点击标签会在包含、排除、取消之间循环切换。",
          "按住 Shift 点击标签可以直接进入排除状态。",
          "筛选模式只影响当前列表结果，不会修改标签库结构。",
        ],
      },
      "batch-category-mode": {
        title: "批量分类模式",
        description: "一次选择多个标签，再统一写入分类和视觉配置。",
        items: [
          "先点击标签或使用批量输入选中目标标签，再设置分类名称、颜色和透明度。",
          "保存后会批量写入分类；不存在的分类会自动创建。",
          "适合建立分类体系，或把零散标签快速归类。",
        ],
      },
      "sort-mode": {
        title: "排序模式",
        description: "调整完整标签库的全局顺序和分类内顺序。",
        items: [
          "混合视图下可以调整标签的全局顺序；分组视图下还能调整分类和分类内标签顺序。",
          "移动端使用行内上移、下移按钮完成排序，保存后同步到全局标签库。",
          "恢复字符排序会清除全局自定义顺序并回到默认排序。",
        ],
      },
      "delete-mode": {
        title: "删除模式",
        description: "把确认无用的标签加入待删除列表后永久清理。",
        items: [
          "点击标签或使用批量输入加入待删除列表，底部操作栏会显示当前待处理数量。",
          "永久删除不可撤销，只建议在确认标签无用时使用。",
          "如果只是想暂时不看某些标签，请使用筛选模式而不是删除模式。",
        ],
      },
      "blacklist-mode": {
        title: "黑名单模式",
        description: "集中维护自动流程和批量流程需要跳过的标签。",
        items: [
          "点击标签或使用分隔符批量选择要加入黑名单的标签。",
          "保存后，自动流程和批量流程会跳过这些标签；手动单个编辑不受影响。",
          "当前黑名单中的标签会单独列出，点击即可移出。",
        ],
      },
      "category-manager-mode": {
        title: "分类管理模式",
        description: "维护分类定义、默认分类和视觉配置。",
        items: [
          "可以新增、重命名、设为默认、删除分类，并调整分类颜色和透明度。",
          "新增空分类后，它会立即出现在分类条和相关选择器中。",
          "删除分类时，分类下标签会迁移到默认分类，不会直接丢失映射。",
        ],
      },
      governance: {
        title: "治理设置",
        description: "控制标签视图记忆和自动来源的标签准入规则。",
        items: [
          "记住上次标签视图会保存视图模式和分类筛选状态，方便下次继续。",
          "拒绝新增未知标签会约束自动化和批量来源，减少意外污染标签库。",
          "手动单个添加不受治理开关影响；黑名单维护在独立的黑名单模式中完成。",
        ],
      },
      workflow: {
        title: "推荐工作流",
        description: "按照从观察到治理的顺序处理标签库。",
        items: [
          "先用搜索和分类条了解标签分布，再进入批量分类整理明显散乱的标签。",
          "然后用分类管理维护分类定义、默认分类和视觉配置。",
          "最后调整全局顺序，确认无用后再进入删除模式清理。",
        ],
      },
      faq: {
        title: "常见问题",
        description: "遇到显示或操作疑问时，先检查当前模式和分类筛选状态。",
        items: [
          "分组视图看不到某个分类时，先检查分类条是否将它排除，或该分类当前没有匹配标签。",
          "新增分类后没有看到时，确认保存成功；空分类也会出现在分类条和选择器中。",
          "排序无法退出时，通常是因为存在未保存改动，需要先保存或确认放弃。",
        ],
      },
    },

    get sidebarTagsPool() {
      return this.$store.global.sidebarTagsPool || [];
    },

    get globalTagsPool() {
      return this.$store.global.globalTagsPool || [];
    },

    // 获取过滤后的标签池 (搜索用)
    get filteredTagsPool() {
      const query = this.tagSearchQuery || "";
      const pool = this.sidebarTagsPool || []; // 使用侧边栏专用池
      if (!query) return pool;
      const slashIsSeparator =
        !!this.$store?.global?.settingsForm?.automation_slash_is_tag_separator;
      return pool.filter((t) =>
        matchAnyTagSearchToken(t, query, { slashIsSeparator }),
      );
    },

    get baseTagGroups() {
      return this.$store.global.groupTagsByTaxonomy(
        this.filteredTagsPool || [],
      );
    },

    get filteredTagGroups() {
      const includeSet = new Set(this.categoryFilterInclude || []);
      const excludeSet = new Set(this.categoryFilterExclude || []);
      const groups = this.baseTagGroups || [];

      return groups.filter((group) => {
        const category = String(group.category || "").trim();
        if (!category) return false;
        if (excludeSet.has(category)) return false;
        if (includeSet.size > 0 && !includeSet.has(category)) return false;
        return true;
      });
    },

    get filteredMixedTagsPool() {
      const includeSet = new Set(this.categoryFilterInclude || []);
      const excludeSet = new Set(this.categoryFilterExclude || []);
      const pool = this.filteredTagsPool || [];

      if (includeSet.size === 0 && excludeSet.size === 0) {
        return pool;
      }

      return pool.filter((tag) => {
        const category = this.getTagCategory(tag);
        if (excludeSet.has(category)) return false;
        if (includeSet.size > 0 && !includeSet.has(category)) return false;
        return true;
      });
    },

    get filteredVisibleTagCount() {
      if (this.isSortMode) return this.sortModeVisibleTagCount;
      if (this.mixedCategoryView) return this.filteredMixedTagsPool.length;
      return this.filteredTagGroups.reduce(
        (acc, group) => acc + (group.tags || []).length,
        0,
      );
    },

    get isCategoryFilterAllMixed() {
      return (
        this.mixedCategoryView &&
        this.categoryFilterInclude.length === 0 &&
        this.categoryFilterExclude.length === 0
      );
    },

    get filterCategoryNames() {
      return this.availableCategoryNames;
    },

    get availableCategoryNames() {
      const taxonomy = this.$store.global.tagTaxonomy || {};
      const categories = taxonomy.categories || {};
      const order = Array.isArray(taxonomy.category_order)
        ? taxonomy.category_order
        : [];

      const names = [];
      const seen = new Set();

      order.forEach((rawName) => {
        const name = String(rawName || "").trim();
        if (!name || seen.has(name) || !categories[name]) return;
        seen.add(name);
        names.push(name);
      });

      Object.keys(categories)
        .sort((a, b) => a.localeCompare(b, "zh-CN", { sensitivity: "base" }))
        .forEach((name) => {
          if (seen.has(name)) return;
          seen.add(name);
          names.push(name);
        });

      return names;
    },

    get canSaveCategoryBatch() {
      return (
        this.showCategoryMode &&
        String(this.categoryDraftName || "").trim().length > 0
      );
    },

    get isBlacklistMode() {
      return this.desktopWorkspaceMode === "blacklist";
    },

    get canSaveBlacklistSelection() {
      return this.selectedBlacklistTags.length > 0;
    },

    get categorySelectionCount() {
      return this.selectedCategoryTags.length;
    },

    get footerCategoryIndexNames() {
      return this.availableCategoryNames;
    },

    get categoryManagerItems() {
      const taxonomy = this.$store.global.tagTaxonomy || {};
      const defaultCategory =
        String(taxonomy.default_category || "未分类").trim() || "未分类";

      const counts = {};
      const groups = this.$store.global.groupTagsByTaxonomy(
        this.globalTagsPool || [],
      );
      groups.forEach((group) => {
        counts[group.category] = (group.tags || []).length;
      });

      return this.availableCategoryNames.map((name, index) => ({
        name,
        index,
        color: this.getCategoryColor(name),
        opacity: this.getCategoryOpacity(name),
        count: counts[name] || 0,
        isDefault: name === defaultCategory,
      }));
    },

    get sortModeTagsPool() {
      return this.sortWorkingTags || [];
    },

    get sortModeMixedTagsPool() {
      return this.filterTagsByCurrentCategoryFilters(
        this.sortModeTagsPool || [],
      );
    },

    get sortModeTagGroups() {
      return this.buildTagGroups(
        this.sortModeTagsPool || [],
        this.sortWorkingCategoryOrder || [],
      );
    },

    get sortModeVisibleTagCount() {
      if (this.mixedCategoryView) return this.sortModeMixedTagsPool.length;
      return this.sortModeTagGroups.reduce(
        (acc, group) => acc + (group.tags || []).length,
        0,
      );
    },

    get isSortDirty() {
      const a = this.sortWorkingTags || [];
      const b = this.sortOriginalTags || [];
      if (a.length !== b.length) return true;
      for (let i = 0; i < a.length; i += 1) {
        if (a[i] !== b[i]) return true;
      }
      return false;
    },

    get isSortCategoryOrderDirty() {
      const a = this.sortWorkingCategoryOrder || [];
      const b = this.sortOriginalCategoryOrder || [];
      if (a.length !== b.length) return true;
      for (let i = 0; i < a.length; i += 1) {
        if (a[i] !== b[i]) return true;
      }
      return false;
    },

    get isSortCategoryTagDirty() {
      return !this.areCategoryTagOrdersEqual(
        this.sortWorkingCategoryTagOrder,
        this.sortOriginalCategoryTagOrder,
      );
    },

    get hasSortChanges() {
      return (
        this.isSortDirty ||
        this.isSortCategoryOrderDirty ||
        this.isSortCategoryTagDirty
      );
    },

    get filterTags() {
      return this.$store.global.getCardAdvancedFilterTagState().filterTags;
    },
    set filterTags(val) {
      this.$store.global.getCardAdvancedFilterTagState().filterTags =
        Array.isArray(val) ? val : [];
    },

    get excludedTags() {
      return this.$store.global.getCardAdvancedFilterTagState().excludedTags;
    },
    set excludedTags(val) {
      this.$store.global.getCardAdvancedFilterTagState().excludedTags =
        Array.isArray(val) ? val : [];
    },

    switchMobileTagTab(tab) {
      const changed = this.syncMobileTabState(tab);
      if (changed === false) return;
      this.closeMobileTools();
      this.mobileActiveTab = tab;
    },

    setDesktopWorkspaceMode(mode) {
      const changed = this.syncDesktopWorkspaceMode(mode);
      if (changed === false) return false;
      this.desktopWorkspaceMode = mode;
      return true;
    },

    syncDesktopWorkspaceMode(mode) {
      if (
        ![
          "filter",
          "batch-category",
          "sort",
          "delete",
          "blacklist",
          "category-manager",
        ].includes(mode)
      ) {
        return false;
      }

      this.closeWorkspaceHelp();
      this.closeGovernanceDrawer();

      const previousMode = this.desktopWorkspaceMode;
      const previousWasCategoryWorkspace = [
        "batch-category",
        "category-manager",
      ].includes(previousMode);
      const nextIsCategoryWorkspace = [
        "batch-category",
        "category-manager",
      ].includes(mode);

      if (previousMode === "sort" && mode !== "sort" && this.isSortMode) {
        this.cancelSortMode();
        if (this.isSortMode) return false;
      }

      if (previousMode === "delete" && mode !== "delete") {
        this.selectedTagsForDeletion = [];
        this.isDeleteMode = false;
      }

      if (previousMode === "blacklist" && mode !== "blacklist") {
        this.selectedBlacklistTags = [];
        this.blacklistSelectionInput = "";
      }

      if (previousWasCategoryWorkspace && !nextIsCategoryWorkspace) {
        this.selectedCategoryTags = [];
        this.categorySelectionInput = "";
        this.categoryDraftName = "";
        this.categoryDraftColor = DEFAULT_TAG_CATEGORY_COLOR;
        this.categoryDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;
        this.showCategoryManager = false;
        this.showCategoryMode = false;
      }

      if (mode === "sort") {
        this.tagSearchQuery = "";
        if (!this.isSortMode) {
          this.enterSortMode();
        }
        return this.isSortMode;
      }

      if (mode === "delete") {
        this.showCategoryMode = false;
        this.showCategoryManager = false;
        this.isDeleteMode = true;
        return true;
      }

      if (mode === "blacklist") {
        this.isDeleteMode = false;
        this.showCategoryMode = false;
        this.showCategoryManager = false;
        this.tagSearchQuery = "";
        return true;
      }

      if (mode === "batch-category") {
        this.isDeleteMode = false;
        this.showCategoryManager = false;
        this.showCategoryMode = true;
        this.tagSearchQuery = "";
        return true;
      }

      if (mode === "category-manager") {
        this.isDeleteMode = false;
        this.showCategoryMode = false;
        this.showCategoryManager = true;
        this.tagSearchQuery = "";
        return true;
      }

      this.isDeleteMode = false;
      this.showCategoryMode = false;
      this.showCategoryManager = false;

      return true;
    },

    toggleDesktopWorkspaceFullscreen() {
      const shell = this._desktopWorkspaceShell();
      const doc = document;
      const activeFullscreenElement =
        doc.fullscreenElement || doc.webkitFullscreenElement || null;

      if (activeFullscreenElement === shell) {
        this.exitDesktopWorkspaceFullscreen();
        return;
      }

      if (activeFullscreenElement) {
        return;
      }

      const requestFullscreen =
        shell && (shell.requestFullscreen || shell.webkitRequestFullscreen);
      if (typeof requestFullscreen === "function") {
        Promise.resolve(requestFullscreen.call(shell))
          .then(() => {
            this.isDesktopWorkspaceFullscreen = true;
          })
          .catch(() => {
            this.isDesktopWorkspaceFullscreen = false;
          });
        return;
      }

      this.isDesktopWorkspaceFullscreen = !this.isDesktopWorkspaceFullscreen;
    },

    _desktopWorkspaceShell() {
      return this.$root?.querySelector(".tag-filter-desktop-shell") || null;
    },

    exitDesktopWorkspaceFullscreen() {
      const doc = document;
      const shell = this._desktopWorkspaceShell();
      const activeFullscreenElement =
        doc.fullscreenElement || doc.webkitFullscreenElement || null;
      const exitFullscreen = doc.exitFullscreen || doc.webkitExitFullscreen;

      this.isDesktopWorkspaceFullscreen = false;
      if (activeFullscreenElement !== shell || typeof exitFullscreen !== "function") {
        return Promise.resolve(false);
      }

      return Promise.resolve(exitFullscreen.call(doc))
        .catch(() => {})
        .finally(() => {
          const currentFullscreenElement =
            doc.fullscreenElement || doc.webkitFullscreenElement || null;
          if (!currentFullscreenElement || currentFullscreenElement === shell) {
            this.isDesktopWorkspaceFullscreen = false;
          }
        });
    },

    toggleGovernanceDrawer() {
      this.isGovernanceDrawerOpen = !this.isGovernanceDrawerOpen;
    },

    closeGovernanceDrawer() {
      this.isGovernanceDrawerOpen = false;
    },

    toggleMobileTools() {
      if (!this.isMobileToolsOpen) this.closeWorkspaceHelp();
      this.isMobileToolsOpen = !this.isMobileToolsOpen;
    },

    closeMobileTools() {
      this.isMobileToolsOpen = false;
    },

    toggleWorkspaceHelp() {
      if (!this.isWorkspaceHelpOpen) {
        if (typeof document !== "undefined") {
          this.lastWorkspaceHelpTrigger = document.activeElement;
        }
        this.closeGovernanceDrawer();
        this.closeMobileTools();
        this.activeWorkspaceHelpSection = "overview";
      }
      this.isWorkspaceHelpOpen = !this.isWorkspaceHelpOpen;
      if (this.isWorkspaceHelpOpen) {
        this.focusWorkspaceHelp();
      } else {
        this.restoreWorkspaceHelpFocus();
      }
    },

    closeWorkspaceHelp() {
      this.isWorkspaceHelpOpen = false;
      this.restoreWorkspaceHelpFocus();
    },

    focusWorkspaceHelp(attempt = 0) {
      if (!this.isWorkspaceHelpOpen) return;

      const selector =
        this.$store?.global?.deviceType === "mobile"
          ? "#tag-filter-mobile-help [aria-label='关闭标签工作台帮助']"
          : ".tag-filter-workspace-help-hero-actions button";
      const closeButton = this.$root?.querySelector(selector);
      if (closeButton?.getClientRects?.().length) {
        closeButton.focus?.();
        return;
      }
      if (attempt < 12) {
        setTimeout(() => this.focusWorkspaceHelp(attempt + 1), 50);
      }
    },

    restoreWorkspaceHelpFocus() {
      const focusTarget = this.lastWorkspaceHelpTrigger;
      this.lastWorkspaceHelpTrigger = null;
      if (focusTarget?.focus) setTimeout(() => focusTarget.focus(), 0);
    },

    selectWorkspaceHelpSection(sectionId) {
      const nextId = String(sectionId || "").trim();
      if (!nextId || !this.workspaceHelpContent[nextId]) return;
      this.activeWorkspaceHelpSection = nextId;
    },

    jumpToWorkspaceHelpSection(sectionId) {
      const nextId = String(sectionId || "").trim();
      if (!nextId || !this.workspaceHelpContent[nextId]) return;

      this.activeWorkspaceHelpSection = nextId;
      queueMicrotask(() => {
        const target = this.$root?.querySelector(
          `[data-workspace-help-section="${nextId}"]`,
        );
        if (target && typeof target.scrollIntoView === "function") {
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    },

    syncMobileTabState(tab) {
      if (!["filter", "sort", "delete", "blacklist", "category"].includes(tab)) {
        return false;
      }

      const previousTab = this.mobileActiveTab;

      if (previousTab === "sort" && tab !== "sort" && this.isSortMode) {
        this.cancelSortMode();
        if (this.isSortMode) return false;
      }

      if (previousTab === "delete" && tab !== "delete") {
        this.selectedTagsForDeletion = [];
        this.isDeleteMode = false;
      }

      if (previousTab === "blacklist" && tab !== "blacklist") {
        this.selectedBlacklistTags = [];
        this.blacklistSelectionInput = "";
      }

      if (previousTab === "category" && tab !== "category") {
        this.selectedCategoryTags = [];
        this.categorySelectionInput = "";
        this.categoryDraftName = "";
        this.categoryDraftColor = DEFAULT_TAG_CATEGORY_COLOR;
        this.categoryDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;
        this.showCategoryManager = false;
        this.showCategoryMode = false;
      }

      if (tab === "sort") {
        this.desktopWorkspaceMode = "sort";
        this.tagSearchQuery = "";
        if (!this.isSortMode) {
          this.enterSortMode();
        }
        return this.isSortMode;
      }

      if (tab === "delete") {
        this.desktopWorkspaceMode = "delete";
        if (!this.isDeleteMode) {
          this.isDeleteMode = true;
        }
        return true;
      }

      if (tab === "blacklist") {
        this.desktopWorkspaceMode = "blacklist";
        this.isDeleteMode = false;
        this.showCategoryMode = false;
        this.showCategoryManager = false;
        return true;
      }

      if (tab === "category") {
        this.desktopWorkspaceMode = "batch-category";
        if (!this.showCategoryMode) {
          this.showCategoryMode = true;
          this.tagSearchQuery = "";
        }
        return true;
      }

      this.isDeleteMode = false;
      this.showCategoryMode = false;
      this.showCategoryManager = false;
      this.desktopWorkspaceMode = "filter";

      return true;
    },

    init() {
      this.loadDesktopWorkbenchPrefs();
      this.loadTagManagementPrefs();

      this._handleDesktopFullscreenChange = () => {
        const activeFullscreenElement =
          document.fullscreenElement ||
          document.webkitFullscreenElement ||
          null;
        this.isDesktopWorkspaceFullscreen =
          activeFullscreenElement === this._desktopWorkspaceShell();
      };
      document.addEventListener(
        "fullscreenchange",
        this._handleDesktopFullscreenChange,
      );
      document.addEventListener(
        "webkitfullscreenchange",
        this._handleDesktopFullscreenChange,
      );

      this.$watch("$store.global.showTagFilterModal", (val) => {
        if (this._syncClosing) return;

        if (val) {
          this.showTagFilterModal = true;
          this.loadDesktopWorkbenchPrefs();
          this.loadTagManagementPrefs();
          this.loadTagOrderMeta();
          return;
        }

        this.showTagFilterModal = val;
        if (!val) {
          if (this.isSortMode && this.hasSortChanges) {
            const ok = confirm(
              "当前排序尚未保存，关闭后将丢失改动。确定关闭吗？",
            );
            if (!ok) {
              this.$store.global.showTagFilterModal = true;
              this.showTagFilterModal = true;
              return;
            }
          }
          this.exitDesktopWorkspaceFullscreen();
          this.resetModalStateAfterClose();
        }
      });

      // 双向绑定：组件关闭时更新 store
      this.$watch("showTagFilterModal", (val) => {
        this.$store.global.showTagFilterModal = val;
      });

      window.addEventListener("open-tag-filter-modal", () => {
        this.showTagFilterModal = true;
        this.$store.global.showTagFilterModal = true;
        this.loadDesktopWorkbenchPrefs();
        this.loadTagManagementPrefs();
        this.loadTagOrderMeta();
      });

      this.$watch("$store.global.tagTaxonomy.updated_at", () => {
        this.sanitizeCategoryFilterState();
      });
    },

    resetModalStateAfterClose() {
      this.isDeleteMode = false;
      this.selectedTagsForDeletion = [];
      this.showCategoryMode = false;
      this.selectedCategoryTags = [];
      this.categorySelectionInput = "";
      this.categoryDraftName = "";
      this.categoryDraftColor = DEFAULT_TAG_CATEGORY_COLOR;
      this.categoryDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;
      this.showCategoryManager = false;
      this.categoryManagerDraftName = "";
      this.categoryManagerDraftColor = DEFAULT_TAG_CATEGORY_COLOR;
      this.categoryManagerDraftOpacity = DEFAULT_TAG_CATEGORY_OPACITY;
      this.selectedBlacklistTags = [];
      this.blacklistSelectionInput = "";
      this.categoryFilterInclude = [];
      this.categoryFilterExclude = [];
      this.mixedCategoryView = true;
      this.resetSortModeState();
      this.mobileActiveTab = "filter";
      this.desktopWorkspaceMode = "filter";
      this.isDesktopWorkspaceFullscreen = false;
      this.closeWorkspaceHelp();
      this.closeGovernanceDrawer();
      this.closeMobileTools();
    },

    loadDesktopWorkbenchPrefs() {
      const tagViewPrefs = this.$store.global.loadTagViewPrefs();
      this.rememberLastTagView = tagViewPrefs.rememberLastTagView === true;
      this.mixedCategoryView = this.rememberLastTagView
        ? tagViewPrefs.mixedCategoryView !== false
        : true;
      this.categoryFilterInclude = this.rememberLastTagView
        ? [...(tagViewPrefs.categoryFilterInclude || [])]
        : [];
      this.categoryFilterExclude = this.rememberLastTagView
        ? [...(tagViewPrefs.categoryFilterExclude || [])]
        : [];
      this.sanitizeCategoryFilterState();
    },

    saveDesktopWorkbenchPrefs() {
      this.$store.global.saveTagViewPrefs({
        rememberLastTagView: this.rememberLastTagView,
        mixedCategoryView: this.mixedCategoryView,
        categoryFilterInclude: this.categoryFilterInclude,
        categoryFilterExclude: this.categoryFilterExclude,
      });
    },

    loadTagManagementPrefs() {
      return getTagManagementPrefs()
        .then((res) => {
          const prefs =
            res &&
            res.tag_management_prefs &&
            typeof res.tag_management_prefs === "object"
              ? res.tag_management_prefs
              : {};
          const blacklist = this.normalizeTagList(prefs.tag_blacklist || []);
          this.lockTagLibrary = prefs.lock_tag_library === true;
          this.tagBlacklistTags = blacklist;
          this.tagBlacklistInput = blacklist.join(", ");
          return prefs;
        })
        .catch(() => ({}));
    },

    saveTagManagementPrefsState() {
      const blacklist = this.normalizeTagList(this.tagBlacklistTags || []);

      return saveTagManagementPrefs({
        tag_management_prefs: {
          lock_tag_library: this.lockTagLibrary,
          tag_blacklist: blacklist,
        },
      })
        .then((res) => {
          const prefs =
            res &&
            res.tag_management_prefs &&
            typeof res.tag_management_prefs === "object"
              ? res.tag_management_prefs
              : {
                  lock_tag_library: this.lockTagLibrary,
                  tag_blacklist: blacklist,
                };
          const normalizedBlacklist = this.normalizeTagList(
            prefs.tag_blacklist || blacklist,
          );
          this.lockTagLibrary = prefs.lock_tag_library === true;
          this.tagBlacklistTags = normalizedBlacklist;
          this.tagBlacklistInput = normalizedBlacklist.join(", ");
          return prefs;
        })
        .catch(() => null);
    },

    loadTagOrderMeta() {
      getTagOrder()
        .then((res) => {
          if (!res || !res.success) return;
          this.customOrderEnabled = !!res.enabled;
        })
        .catch(() => {});
    },

    requestCloseModal() {
      if (this.isSortMode && this.hasSortChanges) {
        const ok = confirm("当前排序尚未保存，关闭后将丢失改动。确定关闭吗？");
        if (!ok) return;
      }

      this.exitDesktopWorkspaceFullscreen();
      this._syncClosing = true;
      this.resetModalStateAfterClose();
      this.showTagFilterModal = false;
      this.$store.global.showTagFilterModal = false;
      this._syncClosing = false;
    },

    requestCloseTagFilterEditor() {
      this.requestCloseModal();
      if (!this.$store.global.isCardAdvancedFilterTagEditActive()) {
        this.$store.global.setCardAdvancedFilterTagEditSource("");
        return;
      }

      this.$store.global.openCardAdvancedFilterDrawer("tags");
    },

    toggleFilterTag(tag, event = null) {
      this.$store.global.toggleFilterTag(tag, {
        forceExclude: !!(event && event.shiftKey),
      });
    },

    getTagChipStyle(tag) {
      return this.$store.global.getTagChipStyle(tag);
    },

    getTagCategory(tag) {
      return this.$store.global.getTagCategory(tag);
    },

    getCategoryColor(category) {
      return this.$store.global.getCategoryColor(category);
    },

    getCategoryChipStyle(category) {
      return this.$store.global.getCategoryChipStyle(category);
    },

    getCategoryOpacity(category) {
      return this.$store.global.getCategoryOpacity(category);
    },

    splitManualTagInput(rawValue) {
      const slashIsSeparator =
        !!this.$store?.global?.settingsForm?.automation_slash_is_tag_separator;
      return splitTagTokens(rawValue, { slashIsSeparator });
    },

    normalizeTagList(values) {
      const seen = new Set();
      const list = [];

      (Array.isArray(values) ? values : []).forEach((rawValue) => {
        const value = String(rawValue || "").trim();
        if (!value || seen.has(value)) return;
        seen.add(value);
        list.push(value);
      });

      return list;
    },

    appendTokensToSelection(tokens, targetKey) {
      const selected = new Set(this.normalizeTagList(this[targetKey] || []));
      let addedCount = 0;

      (tokens || []).forEach((rawToken) => {
        const token = String(rawToken || "").trim();
        if (!token || selected.has(token)) return;
        selected.add(token);
        addedCount += 1;
      });

      this[targetKey] = [...selected];
      return addedCount;
    },

    appendTokensToBlacklistSelection(tokens) {
      const selected = new Set(
        this.normalizeTagList(this.selectedBlacklistTags || []),
      );
      let addedCount = 0;

      (tokens || []).forEach((rawToken) => {
        const token = String(rawToken || "").trim();
        if (!token || selected.has(token)) return;
        selected.add(token);
        addedCount += 1;
      });

      this.selectedBlacklistTags = [...selected];
      return addedCount;
    },

    normalizeOpacity(value, fallback = DEFAULT_TAG_CATEGORY_OPACITY) {
      const fallbackNum = Number.isFinite(Number(fallback))
        ? Number(fallback)
        : 16;
      const raw = Number(value);
      if (!Number.isFinite(raw))
        return Math.max(0, Math.min(100, Math.round(fallbackNum)));
      return Math.max(0, Math.min(100, Math.round(raw)));
    },

    normalizeCategoryTagOrder(rawValue) {
      const next = {};
      if (!rawValue || typeof rawValue !== "object") return next;

      Object.entries(rawValue).forEach(([rawCategory, rawTags]) => {
        const category = String(rawCategory || "").trim();
        if (!category || !Array.isArray(rawTags)) return;

        const seen = new Set();
        const tags = [];
        rawTags.forEach((rawTag) => {
          const tag = String(rawTag || "").trim();
          if (!tag || seen.has(tag)) return;
          seen.add(tag);
          tags.push(tag);
        });

        if (tags.length > 0) {
          next[category] = tags;
        }
      });

      return next;
    },

    areCategoryTagOrdersEqual(leftValue, rightValue) {
      const left = this.normalizeCategoryTagOrder(leftValue);
      const right = this.normalizeCategoryTagOrder(rightValue);
      const leftKeys = Object.keys(left).sort();
      const rightKeys = Object.keys(right).sort();

      if (leftKeys.length !== rightKeys.length) return false;

      for (let i = 0; i < leftKeys.length; i += 1) {
        if (leftKeys[i] !== rightKeys[i]) return false;
        const leftTags = left[leftKeys[i]] || [];
        const rightTags = right[rightKeys[i]] || [];
        if (leftTags.length !== rightTags.length) return false;
        for (let j = 0; j < leftTags.length; j += 1) {
          if (leftTags[j] !== rightTags[j]) return false;
        }
      }

      return true;
    },

    filterTagsByCurrentCategoryFilters(tags) {
      const includeSet = new Set(this.categoryFilterInclude || []);
      const excludeSet = new Set(this.categoryFilterExclude || []);
      const list = Array.isArray(tags) ? tags : [];

      if (includeSet.size === 0 && excludeSet.size === 0) {
        return list;
      }

      return list.filter((tag) => {
        const category = this.getTagCategory(tag);
        if (excludeSet.has(category)) return false;
        if (includeSet.size > 0 && !includeSet.has(category)) return false;
        return true;
      });
    },

    applyExplicitTagOrder(tags, orderedTags) {
      const tagList = Array.isArray(tags) ? tags : [];
      const orderList = Array.isArray(orderedTags) ? orderedTags : [];
      if (!orderList.length) return tagList;

      const tagSet = new Set(tagList);
      const seen = new Set();
      const result = [];

      orderList.forEach((rawTag) => {
        const tag = String(rawTag || "").trim();
        if (!tag || seen.has(tag) || !tagSet.has(tag)) return;
        seen.add(tag);
        result.push(tag);
      });

      tagList.forEach((tag) => {
        if (seen.has(tag)) return;
        seen.add(tag);
        result.push(tag);
      });

      return result;
    },

    getSortCategoryTags(categoryName) {
      const category = String(categoryName || "").trim();
      if (!category) return [];

      const tags = (this.sortModeTagsPool || []).filter(
        (tag) => this.getTagCategory(tag) === category,
      );
      const orderedTags =
        this.sortWorkingCategoryTagOrder &&
        this.sortWorkingCategoryTagOrder[category];
      return this.applyExplicitTagOrder(tags, orderedTags);
    },

    buildTagGroups(tags, categoryOrder = []) {
      const filteredTags = this.filterTagsByCurrentCategoryFilters(tags);
      if (!filteredTags.length) return [];

      const grouped = new Map();
      filteredTags.forEach((tag) => {
        const category = this.getTagCategory(tag);
        if (!grouped.has(category)) {
          grouped.set(category, []);
        }
        grouped.get(category).push(tag);
      });

      const orderedCategories = [];
      const seen = new Set();
      (Array.isArray(categoryOrder) ? categoryOrder : []).forEach(
        (rawCategory) => {
          const category = String(rawCategory || "").trim();
          if (!category || seen.has(category) || !grouped.has(category)) return;
          seen.add(category);
          orderedCategories.push(category);
        },
      );

      Array.from(grouped.keys()).forEach((category) => {
        if (seen.has(category)) return;
        seen.add(category);
        orderedCategories.push(category);
      });

      return orderedCategories.map((category) => ({
        category,
        color: this.getCategoryColor(category),
        opacity: this.getCategoryOpacity(category),
        tags: this.applyExplicitTagOrder(
          grouped.get(category) || [],
          this.sortWorkingCategoryTagOrder[category],
        ),
      }));
    },

    getCategoryFilterState(category) {
      if (this.categoryFilterInclude.includes(category)) return "included";
      if (this.categoryFilterExclude.includes(category)) return "excluded";
      return "none";
    },

    toggleCategoryFilter(category, event = null) {
      const name = String(category || "").trim();
      if (!name) return;

      const forceExclude = !!(event && event.shiftKey);
      const include = [...(this.categoryFilterInclude || [])];
      const exclude = [...(this.categoryFilterExclude || [])];

      const inInclude = include.indexOf(name);
      const inExclude = exclude.indexOf(name);

      this.mixedCategoryView = false;

      if (forceExclude) {
        if (inInclude > -1) include.splice(inInclude, 1);
        if (inExclude === -1) exclude.push(name);
      } else if (inInclude > -1) {
        include.splice(inInclude, 1);
        if (inExclude === -1) exclude.push(name);
      } else if (inExclude > -1) {
        exclude.splice(inExclude, 1);
      } else {
        include.push(name);
      }

      this.categoryFilterInclude = include;
      this.categoryFilterExclude = exclude;
      this.saveDesktopWorkbenchPrefs();
    },

    showAllCategoriesMixed() {
      this.categoryFilterInclude = [];
      this.categoryFilterExclude = [];
      this.mixedCategoryView = true;
      this.saveDesktopWorkbenchPrefs();
    },

    applyFooterCategoryQuickFilter(category) {
      this.mixedCategoryView = false;
      this.categoryFilterInclude = [String(category || "").trim()].filter(
        Boolean,
      );
      this.categoryFilterExclude = [];
      this.saveDesktopWorkbenchPrefs();
    },

    isTagBlacklisted(tag) {
      const name = String(tag || "").trim();
      if (!name) return false;
      return this.tagBlacklistTags.includes(name);
    },

    sanitizeCategoryFilterState() {
      const valid = new Set(this.availableCategoryNames || []);
      this.categoryFilterInclude = (this.categoryFilterInclude || []).filter(
        (name) => valid.has(name),
      );
      this.categoryFilterExclude = (this.categoryFilterExclude || []).filter(
        (name) => valid.has(name),
      );
    },

    buildTaxonomyPayload() {
      const current = this.$store.global.tagTaxonomy || {};
      const defaultCategory =
        String(current.default_category || "未分类").trim() || "未分类";
      const categories =
        current.categories && typeof current.categories === "object"
          ? { ...current.categories }
          : {};
      const categoryOrder = Array.isArray(current.category_order)
        ? [...current.category_order]
        : [];
      const tagToCategory =
        current.tag_to_category && typeof current.tag_to_category === "object"
          ? { ...current.tag_to_category }
          : {};
      const categoryTagOrder =
        current.category_tag_order &&
        typeof current.category_tag_order === "object"
          ? Object.fromEntries(
              Object.entries(current.category_tag_order).map(([name, tags]) => [
                name,
                Array.isArray(tags) ? [...tags] : [],
              ]),
            )
          : {};

      if (!categories[defaultCategory]) {
        categories[defaultCategory] = {
          color: DEFAULT_TAG_CATEGORY_COLOR,
          opacity: DEFAULT_TAG_CATEGORY_OPACITY,
        };
      }

      if (!categoryOrder.includes(defaultCategory)) {
        categoryOrder.unshift(defaultCategory);
      }

      return {
        default_category: defaultCategory,
        category_order: categoryOrder,
        categories,
        tag_to_category: tagToCategory,
        category_tag_order: categoryTagOrder,
      };
    },

    saveTaxonomy(taxonomy, successMsg = "") {
      return saveTagTaxonomy({ taxonomy })
        .then((res) => {
          if (!res || !res.success) {
            alert("保存标签分类失败: " + ((res && res.msg) || "未知错误"));
            return null;
          }

          this.$store.global.setTagTaxonomy(res.taxonomy || taxonomy);
          this.sanitizeCategoryFilterState();
          if (this.showCategoryMode) {
            const draftName = String(this.categoryDraftName || "").trim();
            if (draftName && this.availableCategoryNames.includes(draftName)) {
              this.categoryDraftColor = this.getCategoryColor(draftName);
              this.categoryDraftOpacity = this.getCategoryOpacity(draftName);
            }
          }
          if (successMsg) {
            this.$store.global.showToast(successMsg, 1800, "check");
          }
          return res.taxonomy || taxonomy;
        })
        .catch((err) => {
          alert("保存标签分类失败: " + err);
          return null;
        });
    },

    toggleCategoryManager() {
      this.showCategoryManager = !this.showCategoryManager;
    },

    addCategoryFromManager() {
      const name = String(this.categoryManagerDraftName || "").trim();
      if (!name) {
        alert("请输入分类名称");
        return;
      }

      const color =
        String(this.categoryManagerDraftColor || "").trim() ||
        DEFAULT_TAG_CATEGORY_COLOR;
      const opacity = this.normalizeOpacity(
        this.categoryManagerDraftOpacity,
        16,
      );
      const taxonomy = this.buildTaxonomyPayload();
      const exists = !!taxonomy.categories[name];

      taxonomy.categories[name] = {
        ...(taxonomy.categories[name] || {}),
        color,
        opacity,
      };

      if (!taxonomy.category_order.includes(name)) {
        taxonomy.category_order.push(name);
      }

      this.saveTaxonomy(
        taxonomy,
        exists ? `已更新分类「${name}」颜色` : `已新增分类「${name}」`,
      ).then((saved) => {
        if (!saved) return;
        this.categoryManagerDraftName = "";
      });
    },

    renameCategory(categoryName) {
      const oldName = String(categoryName || "").trim();
      if (!oldName) return;

      const nextNameRaw = prompt("请输入新的分类名称", oldName);
      if (nextNameRaw === null) return;

      const newName = String(nextNameRaw || "").trim();
      if (!newName || newName === oldName) return;

      const taxonomy = this.buildTaxonomyPayload();
      if (!taxonomy.categories[oldName]) return;

      const targetExists = !!taxonomy.categories[newName];
      if (targetExists) {
        const okMerge = confirm(
          `分类「${newName}」已存在，是否将「${oldName}」合并到它？`,
        );
        if (!okMerge) return;
      }

      if (!targetExists) {
        taxonomy.categories[newName] = { ...taxonomy.categories[oldName] };
      }
      delete taxonomy.categories[oldName];

      taxonomy.category_order = taxonomy.category_order.map((name) =>
        name === oldName ? newName : name,
      );
      taxonomy.category_order = [
        ...new Set(taxonomy.category_order.filter(Boolean)),
      ];

      Object.keys(taxonomy.tag_to_category).forEach((tag) => {
        if (taxonomy.tag_to_category[tag] === oldName) {
          taxonomy.tag_to_category[tag] = newName;
        }
      });

      if (taxonomy.default_category === oldName) {
        taxonomy.default_category = newName;
      }

      this.saveTaxonomy(taxonomy, `已重命名分类「${oldName}」`);
    },

    deleteCategory(categoryName) {
      const name = String(categoryName || "").trim();
      if (!name) return;

      const taxonomy = this.buildTaxonomyPayload();
      const defaultCategory =
        String(taxonomy.default_category || "未分类").trim() || "未分类";

      if (name === defaultCategory) {
        alert("默认分类无法删除，请先将其他分类设为默认");
        return;
      }

      const ok = confirm(
        `确定删除分类「${name}」吗？该分类下标签将迁移到「${defaultCategory}」。`,
      );
      if (!ok) return;

      delete taxonomy.categories[name];
      taxonomy.category_order = taxonomy.category_order.filter(
        (item) => item !== name,
      );

      Object.keys(taxonomy.tag_to_category).forEach((tag) => {
        if (taxonomy.tag_to_category[tag] === name) {
          taxonomy.tag_to_category[tag] = defaultCategory;
        }
      });

      this.saveTaxonomy(taxonomy, `已删除分类「${name}」`);
    },

    setDefaultCategory(categoryName) {
      const name = String(categoryName || "").trim();
      if (!name) return;

      const taxonomy = this.buildTaxonomyPayload();
      if (!taxonomy.categories[name]) return;

      taxonomy.default_category = name;
      taxonomy.category_order = [
        name,
        ...taxonomy.category_order.filter((item) => item !== name),
      ];
      this.saveTaxonomy(taxonomy, `已将「${name}」设为默认分类`);
    },

    setCategoryColor(categoryName, color) {
      const name = String(categoryName || "").trim();
      if (!name) return;

      const taxonomy = this.buildTaxonomyPayload();
      if (!taxonomy.categories[name]) return;

      taxonomy.categories[name] = {
        ...taxonomy.categories[name],
        color: String(color || "").trim() || DEFAULT_TAG_CATEGORY_COLOR,
      };

      if (String(this.categoryDraftName || "").trim() === name) {
        this.categoryDraftColor = taxonomy.categories[name].color;
      }

      this.saveTaxonomy(taxonomy);
    },

    setCategoryOpacity(categoryName, opacity) {
      const name = String(categoryName || "").trim();
      if (!name) return;

      const taxonomy = this.buildTaxonomyPayload();
      if (!taxonomy.categories[name]) return;

      taxonomy.categories[name] = {
        ...taxonomy.categories[name],
        opacity: this.normalizeOpacity(opacity, DEFAULT_TAG_CATEGORY_OPACITY),
      };

      if (String(this.categoryDraftName || "").trim() === name) {
        this.categoryDraftOpacity = taxonomy.categories[name].opacity;
      }

      this.saveTaxonomy(taxonomy);
    },

    moveCategory(categoryName, direction) {
      const name = String(categoryName || "").trim();
      if (!name) return;

      const taxonomy = this.buildTaxonomyPayload();
      const order = [...taxonomy.category_order];
      const index = order.indexOf(name);
      if (index < 0) return;

      const nextIndex = index + (direction < 0 ? -1 : 1);
      if (nextIndex < 0 || nextIndex >= order.length) return;

      const target = order[nextIndex];
      order[nextIndex] = name;
      order[index] = target;
      taxonomy.category_order = order;

      this.saveTaxonomy(taxonomy);
    },

    toggleCategoryMode() {
      this.setDesktopWorkspaceMode(
        this.desktopWorkspaceMode === "batch-category"
          ? "filter"
          : "batch-category",
      );
    },

    resetSortModeState() {
      this.isSortMode = false;
      this.sortWorkingTags = [];
      this.sortOriginalTags = [];
      this.sortWorkingCategoryOrder = [];
      this.sortOriginalCategoryOrder = [];
      this.sortWorkingCategoryTagOrder = {};
      this.sortOriginalCategoryTagOrder = {};
      this.dragTag = null;
      this.dragTagCategory = "";
      this.dragOverTag = null;
      this.dragCategory = null;
      this.dragOverCategory = null;
    },

    enterSortMode() {
      if (this.isDeleteMode) {
        alert("删除模式下无法排序，请先退出删除模式");
        return false;
      }

      this.isSortMode = true;
      this.tagSearchQuery = "";
      this.sortWorkingTags = [...(this.globalTagsPool || [])];
      this.sortOriginalTags = [...this.sortWorkingTags];
      this.sortWorkingCategoryOrder = [...this.availableCategoryNames];
      this.sortOriginalCategoryOrder = [...this.sortWorkingCategoryOrder];

      const taxonomy = this.buildTaxonomyPayload();
      const categoryTagOrder = this.normalizeCategoryTagOrder(
        taxonomy.category_tag_order,
      );
      this.sortWorkingCategoryTagOrder = categoryTagOrder;
      this.sortOriginalCategoryTagOrder =
        this.normalizeCategoryTagOrder(categoryTagOrder);

      this.dragTag = null;
      this.dragTagCategory = "";
      this.dragOverTag = null;
      this.dragCategory = null;
      this.dragOverCategory = null;
      return true;
    },

    toggleTagSelectionForCategory(tag) {
      const index = this.selectedCategoryTags.indexOf(tag);
      if (index > -1) {
        this.selectedCategoryTags.splice(index, 1);
        return;
      }
      this.selectedCategoryTags.push(tag);
    },

    toggleTagSelectionForBlacklist(tag) {
      const name = String(tag || "").trim();
      if (!name) return;

      const index = this.selectedBlacklistTags.indexOf(name);
      if (index > -1) {
        this.selectedBlacklistTags.splice(index, 1);
        return;
      }
      this.selectedBlacklistTags.push(name);
    },

    applyCategorySelectionInput() {
      const tokens = this.splitManualTagInput(this.categorySelectionInput);
      if (!tokens.length) return;

      const addedCount = this.appendTokensToSelection(
        tokens,
        "selectedCategoryTags",
      );
      this.categorySelectionInput = "";

      if (addedCount > 0) {
        this.$store.global.showToast(
          `已向分类选择中加入 ${addedCount} 个标签`,
          2200,
        );
        return;
      }

      this.$store.global.showToast("这些标签都已经在当前分类选择中", 2200);
    },

    applyBlacklistSelectionInput() {
      const tokens = this.splitManualTagInput(this.blacklistSelectionInput);
      if (!tokens.length) return;

      const addedCount = this.appendTokensToBlacklistSelection(tokens);
      this.blacklistSelectionInput = "";

      if (addedCount > 0) {
        this.$store.global.showToast(
          `已向黑名单选择中加入 ${addedCount} 个标签`,
          2200,
        );
        return;
      }

      this.$store.global.showToast("这些标签都已经在当前黑名单选择中", 2200);
    },

    setCategoryDraft(categoryName) {
      const name = String(categoryName || "").trim();
      if (!name) return;
      this.categoryDraftName = name;
      this.categoryDraftColor = this.getCategoryColor(name);
      this.categoryDraftOpacity = this.getCategoryOpacity(name);
    },

    saveCategoryBatch() {
      const categoryName = String(this.categoryDraftName || "").trim();
      if (!categoryName) {
        alert("请先填写分类名");
        return;
      }

      const categoryColor =
        String(this.categoryDraftColor || "").trim() ||
        DEFAULT_TAG_CATEGORY_COLOR;
      const categoryOpacity = this.normalizeOpacity(
        this.categoryDraftOpacity,
        DEFAULT_TAG_CATEGORY_OPACITY,
      );
      const tags = [
        ...new Set(
          (this.selectedCategoryTags || [])
            .map((t) => String(t || "").trim())
            .filter(Boolean),
        ),
      ];

      const taxonomy = this.buildTaxonomyPayload();

      if (!taxonomy.categories[categoryName]) {
        taxonomy.categories[categoryName] = {
          color: categoryColor,
          opacity: categoryOpacity,
        };
      } else {
        taxonomy.categories[categoryName] = {
          ...taxonomy.categories[categoryName],
          color: categoryColor,
          opacity: categoryOpacity,
        };
      }

      if (!taxonomy.category_order.includes(categoryName)) {
        taxonomy.category_order.push(categoryName);
      }

      tags.forEach((tag) => {
        taxonomy.tag_to_category[tag] = categoryName;
      });

      const successMsg =
        tags.length > 0
          ? `已为 ${tags.length} 个标签设置分类`
          : `已更新分类「${categoryName}」样式`;

      this.saveTaxonomy(taxonomy, successMsg).then((saved) => {
        if (!saved) return;
        this.categoryDraftColor = this.getCategoryColor(categoryName);
        this.categoryDraftOpacity = this.getCategoryOpacity(categoryName);
        this.selectedCategoryTags = [];
      });
    },

    mergeTagsIntoBlacklist(tags, options = {}) {
      const normalizedTags = this.normalizeTagList(tags || []);
      if (!normalizedTags.length) {
        alert("请先选择要加入黑名单的标签");
        return Promise.resolve(false);
      }

      const {
        successMessage,
        duplicateMessage = "所选标签已在黑名单中",
        clearBlacklistSelectionOnSuccess = false,
        clearBlacklistInputOnSuccess = false,
        clearDeleteSelectionOnSuccess = false,
      } = options;

      const nextBlacklist = [
        ...this.normalizeTagList(this.tagBlacklistTags || []),
      ];
      const existing = new Set(nextBlacklist);
      let addedCount = 0;

      normalizedTags.forEach((tag) => {
        if (existing.has(tag)) return;
        existing.add(tag);
        nextBlacklist.push(tag);
        addedCount += 1;
      });

      if (addedCount === 0) {
        if (clearBlacklistSelectionOnSuccess) this.selectedBlacklistTags = [];
        if (clearBlacklistInputOnSuccess) this.blacklistSelectionInput = "";
        this.$store.global.showToast(duplicateMessage, 1800);
        return Promise.resolve(false);
      }

      const previousBlacklist = this.normalizeTagList(
        this.tagBlacklistTags || [],
      );
      const previousBlacklistInput = this.tagBlacklistInput;
      this.tagBlacklistTags = nextBlacklist;
      this.tagBlacklistInput = nextBlacklist.join(", ");

      return this.saveTagManagementPrefsState()
        .then((prefs) => {
          if (!prefs) {
            this.tagBlacklistTags = previousBlacklist;
            this.tagBlacklistInput = previousBlacklistInput;
            return false;
          }
          if (clearBlacklistSelectionOnSuccess) this.selectedBlacklistTags = [];
          if (clearBlacklistInputOnSuccess) this.blacklistSelectionInput = "";
          if (clearDeleteSelectionOnSuccess) this.selectedTagsForDeletion = [];
          this.$store.global.showToast(
            successMessage || `已加入 ${addedCount} 个黑名单标签`,
            1800,
            "check",
          );
          return true;
        })
        .catch(() => {
          this.tagBlacklistTags = previousBlacklist;
          this.tagBlacklistInput = previousBlacklistInput;
          return false;
        });
    },

    saveBlacklistSelection() {
      return this.mergeTagsIntoBlacklist(this.selectedBlacklistTags, {
        clearBlacklistSelectionOnSuccess: true,
        clearBlacklistInputOnSuccess: true,
      });
    },

    addDeleteSelectionToBlacklist() {
      if (this.selectedTagsForDeletion.length === 0) {
        alert("请先选择要加入黑名单的标签");
        return;
      }

      return this.mergeTagsIntoBlacklist(this.selectedTagsForDeletion, {
        successMessage: `已将 ${this.selectedTagsForDeletion.length} 个待删除标签加入黑名单`,
        clearDeleteSelectionOnSuccess: true,
      });
    },

    removeBlacklistedTag(tag) {
      const name = String(tag || "").trim();
      if (!name) return;

      const nextBlacklist = this.normalizeTagList(
        this.tagBlacklistTags.filter((item) => item !== name),
      );
      if (nextBlacklist.length === this.tagBlacklistTags.length) return;

      this.tagBlacklistTags = nextBlacklist;
      this.tagBlacklistInput = nextBlacklist.join(", ");
      this.selectedBlacklistTags = this.selectedBlacklistTags.filter(
        (item) => item !== name,
      );

      this.saveTagManagementPrefsState().then((prefs) => {
        if (!prefs) return;
        this.$store.global.showToast(`已将「${name}」移出黑名单`, 1800, "check");
      });
    },

    toggleSortMode() {
      this.setDesktopWorkspaceMode(
        this.desktopWorkspaceMode === "sort" ? "filter" : "sort",
      );
    },

    cancelSortMode() {
      if (this.hasSortChanges) {
        const ok = confirm("当前排序尚未保存，确定放弃改动吗？");
        if (!ok) return;
      }
      this.resetSortModeState();
    },

    moveSortTag(tag, delta) {
      const tags = [...(this.sortWorkingTags || [])];
      if (!this.isSortMode || !tag || !Number.isFinite(delta)) return false;

      const currentIndex = tags.indexOf(tag);
      const targetIndex = currentIndex + delta;
      if (currentIndex === -1 || targetIndex < 0 || targetIndex >= tags.length)
        return false;

      tags.splice(currentIndex, 1);
      tags.splice(targetIndex, 0, tag);
      this.sortWorkingTags = tags;
      return true;
    },

    moveSortTagUp(tag) {
      return this.moveSortTag(tag, -1);
    },

    moveSortTagDown(tag) {
      return this.moveSortTag(tag, 1);
    },

    moveSortCategory(categoryName, delta) {
      const category = String(categoryName || "").trim();
      const order = [...(this.sortWorkingCategoryOrder || [])];
      if (!this.isSortMode || this.mixedCategoryView || !category || !Number.isFinite(delta)) {
        return false;
      }

      const currentIndex = order.indexOf(category);
      const targetIndex = currentIndex + delta;
      if (currentIndex === -1 || targetIndex < 0 || targetIndex >= order.length) {
        return false;
      }

      order.splice(currentIndex, 1);
      order.splice(targetIndex, 0, category);
      this.sortWorkingCategoryOrder = order;
      return true;
    },

    moveSortCategoryUp(categoryName) {
      return this.moveSortCategory(categoryName, -1);
    },

    moveSortCategoryDown(categoryName) {
      return this.moveSortCategory(categoryName, 1);
    },

    moveSortCategoryTag(tag, delta) {
      const name = String(tag || "").trim();
      const category = String(this.getTagCategory(name) || "").trim();
      if (!this.isSortMode || this.mixedCategoryView || !name || !category || !Number.isFinite(delta)) {
        return false;
      }

      const tags = [...this.getSortCategoryTags(category)];
      const currentIndex = tags.indexOf(name);
      const targetIndex = currentIndex + delta;
      if (currentIndex === -1 || targetIndex < 0 || targetIndex >= tags.length) {
        return false;
      }

      tags.splice(currentIndex, 1);
      tags.splice(targetIndex, 0, name);
      this.sortWorkingCategoryTagOrder = {
        ...(this.sortWorkingCategoryTagOrder || {}),
        [category]: tags,
      };
      return true;
    },

    moveSortCategoryTagUp(tag) {
      return this.moveSortCategoryTag(tag, -1);
    },

    moveSortCategoryTagDown(tag) {
      return this.moveSortCategoryTag(tag, 1);
    },

    onSortDragStart(event, tag) {
      if (!this.isSortMode) return;
      this.dragTag = tag;
      this.dragTagCategory = String(this.getTagCategory(tag) || "").trim();
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", tag);
    },

    onSortDragOver(e, tag) {
      if (!this.isSortMode) return;
      if (!this.mixedCategoryView) {
        const targetCategory = String(this.getTagCategory(tag) || "").trim();
        if (
          this.dragTagCategory &&
          targetCategory &&
          this.dragTagCategory !== targetCategory
        ) {
          return;
        }
      }
      e.preventDefault();
      this.dragOverTag = tag;
    },

    onSortDrop(e, targetTag) {
      if (!this.isSortMode) return;
      e.preventDefault();
      const sourceTag = this.dragTag || e.dataTransfer.getData("text/plain");
      if (!sourceTag || !targetTag || sourceTag === targetTag) return;

      if (!this.mixedCategoryView) {
        const category = String(this.getTagCategory(sourceTag) || "").trim();
        if (
          !category ||
          category !== String(this.getTagCategory(targetTag) || "").trim()
        )
          return;

        const currentTags = [...this.getSortCategoryTags(category)];
        const from = currentTags.indexOf(sourceTag);
        const to = currentTags.indexOf(targetTag);
        if (from < 0 || to < 0) return;

        currentTags.splice(from, 1);
        currentTags.splice(to, 0, sourceTag);
        this.sortWorkingCategoryTagOrder = {
          ...(this.sortWorkingCategoryTagOrder || {}),
          [category]: currentTags,
        };
        this.dragOverTag = null;
        return;
      }

      const list = [...this.sortWorkingTags];
      const from = list.indexOf(sourceTag);
      const to = list.indexOf(targetTag);
      if (from < 0 || to < 0) return;

      list.splice(from, 1);
      const targetIndex = list.indexOf(targetTag);
      list.splice(targetIndex, 0, sourceTag);
      this.sortWorkingTags = list;
      this.dragOverTag = null;
    },

    onSortDragEnd() {
      this.dragTag = null;
      this.dragTagCategory = "";
      this.dragOverTag = null;
    },

    onSortCategoryDragStart(event, categoryName) {
      if (!this.isSortMode || this.mixedCategoryView) return;
      const category = String(categoryName || "").trim();
      if (!category) return;

      this.dragCategory = category;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", category);
    },

    onSortCategoryDragOver(event, categoryName) {
      if (!this.isSortMode || this.mixedCategoryView) return;
      const category = String(categoryName || "").trim();
      if (!category) return;

      event.preventDefault();
      this.dragOverCategory = category;
    },

    onSortCategoryDrop(event, targetCategoryName) {
      if (!this.isSortMode || this.mixedCategoryView) return;
      event.preventDefault();

      const sourceCategory = String(
        this.dragCategory || event.dataTransfer.getData("text/plain") || "",
      ).trim();
      const targetCategory = String(targetCategoryName || "").trim();
      if (
        !sourceCategory ||
        !targetCategory ||
        sourceCategory === targetCategory
      )
        return;

      const order = [...(this.sortWorkingCategoryOrder || [])];
      const from = order.indexOf(sourceCategory);
      const to = order.indexOf(targetCategory);
      if (from < 0 || to < 0) return;

      order.splice(from, 1);
      order.splice(to, 0, sourceCategory);
      this.sortWorkingCategoryOrder = order;
      this.dragOverCategory = null;
    },

    onSortCategoryDragEnd() {
      this.dragCategory = null;
      this.dragOverCategory = null;
    },

    saveSortMode() {
      if (!this.isSortMode) return;

      const nextOrder = [...this.sortWorkingTags];
      saveTagOrder({ order: nextOrder, enabled: true })
        .then((res) => {
          if (!res.success) {
            alert("保存排序失败: " + (res.msg || "未知错误"));
            return null;
          }

          this.$store.global.globalTagsPool = [...nextOrder];

          const sidebarSet = new Set(this.$store.global.sidebarTagsPool || []);
          const orderedSidebar = nextOrder.filter((t) => sidebarSet.has(t));
          this.$store.global.sidebarTagsPool = orderedSidebar;
          this.$store.global.allTagsPool = orderedSidebar;
          this.$store.global.rebuildTagGroups();
          this.customOrderEnabled = true;
          this.sortOriginalTags = [...nextOrder];

          if (!this.isSortCategoryOrderDirty && !this.isSortCategoryTagDirty) {
            return { taxonomySaved: false };
          }

          const taxonomy = this.buildTaxonomyPayload();
          taxonomy.category_order = [...(this.sortWorkingCategoryOrder || [])];
          taxonomy.category_tag_order = this.normalizeCategoryTagOrder(
            this.sortWorkingCategoryTagOrder,
          );

          return this.saveTaxonomy(taxonomy).then((saved) => {
            if (!saved) return null;
            this.sortOriginalCategoryOrder = [
              ...(this.sortWorkingCategoryOrder || []),
            ];
            this.sortOriginalCategoryTagOrder = this.normalizeCategoryTagOrder(
              this.sortWorkingCategoryTagOrder,
            );
            return { taxonomySaved: true };
          });
        })
        .then((result) => {
          if (!result) return;
          this.$store.global.showToast("标签顺序已保存", 1800, "check");
          this.resetSortModeState();
        })
        .catch((err) => {
          alert("保存排序失败: " + err);
        });
    },

    clearCustomOrder() {
      if (this.isSortMode && this.hasSortChanges) {
        const ok = confirm(
          "当前排序尚未保存，清除自定义排序会丢失这些改动。确定继续吗？",
        );
        if (!ok) return;
      }

      if (!confirm("确定清除自定义标签排序并恢复字符排序吗？")) return;

      saveTagOrder({ order: [], enabled: false })
        .then((res) => {
          if (!res.success) {
            alert("清除自定义排序失败: " + (res.msg || "未知错误"));
            return;
          }

          this.customOrderEnabled = false;
          this.resetSortModeState();

          window.dispatchEvent(new CustomEvent("refresh-card-list"));
          this.$store.global.showToast("已恢复字符排序", 1800, "check");
        })
        .catch((err) => {
          alert("清除自定义排序失败: " + err);
        });
    },

    // === 删除模式逻辑 ===

    toggleDeleteMode() {
      this.setDesktopWorkspaceMode(
        this.desktopWorkspaceMode === "delete" ? "filter" : "delete",
      );
    },

    toggleTagSelectionForDeletion(tag) {
      const index = this.selectedTagsForDeletion.indexOf(tag);
      if (index > -1) {
        this.selectedTagsForDeletion.splice(index, 1);
      } else {
        this.selectedTagsForDeletion.push(tag);
      }
    },

    // 从当前视图的卡片中移除选中的标签
    deleteFilterTags() {
      // 合并包含和排除的标签
      const includeTags = this.filterTags;
      const excludeTags = this.excludedTags;

      // 合并并去重
      const tags = [...new Set([...includeTags, ...excludeTags])];

      if (!tags || tags.length === 0) {
        alert("请先选择要删除的标签");
        return;
      }

      // 派发事件给 CardGrid 处理（因为只有 CardGrid 知道当前显示了哪些卡片 ID）
      window.dispatchEvent(
        new CustomEvent("req-batch-remove-current-tags", {
          detail: { tags: [...tags] },
        }),
      );
    },

    deleteSelectedTags() {
      if (this.selectedTagsForDeletion.length === 0) {
        alert("请先选择要删除的标签");
        return;
      }

      const tagsToDelete = this.selectedTagsForDeletion.join(", ");

      // 获取当前分类 (从全局状态)
      const currentCategory = this.$store.global.viewState.filterCategory;
      const scopeText = currentCategory
        ? `"${currentCategory}" 分类下`
        : "所有";

      const confirmMsg = `警告：确定要从【${scopeText}】的角色卡中移除以下标签吗？\n\n${tagsToDelete}\n\n此操作不可撤销！`;

      if (!confirm(confirmMsg)) return;

      deleteTags({
        tags: this.selectedTagsForDeletion,
        category: currentCategory,
      })
        .then((res) => {
          if (res.success) {
            const failedCards = Array.isArray(res.failed_cards)
              ? res.failed_cards
              : [];
            const indexSyncErrors = Array.isArray(res.index_sync_errors)
              ? res.index_sync_errors
              : [];
            const cacheSyncErrors = Array.isArray(res.cache_sync_errors)
              ? res.cache_sync_errors
              : [];
            let message = `成功删除 ${res.total_tags_deleted} 个标签，更新了 ${res.updated_cards} 张卡片`;
            const syncErrorCount =
              failedCards.length + cacheSyncErrors.length + indexSyncErrors.length;
            if (syncErrorCount) {
              message += `\n部分同步失败：${syncErrorCount} 项`;
            }
            alert(message);

            // 标签池以服务端重算结果为准，避免按分类删除时错误清空全局标签。
            window.dispatchEvent(
              new CustomEvent("tags-deleted", {
                detail: {
                  cardIds: Array.isArray(res.changed_card_ids)
                    ? res.changed_card_ids
                    : [],
                },
              }),
            );

            this.selectedTagsForDeletion = [];
            this.isDeleteMode = false;

            // 刷新列表会重新加载 global_tags/sidebar_tags。
            window.dispatchEvent(new CustomEvent("refresh-card-list"));
          } else {
            alert("删除失败: " + res.msg);
          }
        })
        .catch((err) => {
          alert("网络错误: " + err);
        });
    },
  };
}
