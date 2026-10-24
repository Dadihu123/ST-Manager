/**
 * static/js/components/header.js
 * 顶部导航栏组件
 */

import { addSourceUpdateMonitorEntries } from "../api/card.js";
import { batchUpdateTags, getIndexStatus } from "../api/system.js";
import { listRuleSets } from "../api/automation.js";
import {
  isBatchOperationRunning,
  runAutomationBatch,
  runSourceUpdateAcknowledgeBatch,
  runSourceUpdateBatch,
} from "../utils/batchOperations.js";
import { listChats } from "../api/chat.js";
import { ContributionRegistry } from "../contributionRegistry.js";
import { icon as buildIcon } from "../uiPrimitives.js";
import { positionFlyoutElement, resolveAnchorElement } from "../utils/flyoutPosition.js";

const MOBILE_HEADER_UPLOAD_MODES = [
  "cards",
  "worldinfo",
  "chats",
  "presets",
  "regex",
  "scripts",
  "quick_replies",
  "beautify",
];

export default function header() {
  return {
    availableRuleSets: [],

    /** 批量菜单里的贡献节点（`menuTree("batch.actions")` 产物，可含子菜单）。 */
    pluginBatchNodes: [],
    /**
     * 当前展开的贡献子菜单 id（`''` = 没有二级菜单）。
     *
     * 与右键菜单同一套：桌面端点父项弹一个 **fixed 浮层**（`.plugin-menu-flyout`），
     * 不能就地展开——批量菜单盒同样有高度钳制，`pl-6` 子项块会被裁掉。
     * 状态放组件上而不是 `x-for` 克隆里的局部 `x-data`：后者会丢绑定。
     */
    activePluginBatchGroup: "",
    /** 二级浮层的锚点（父项按钮），只用于定位。 */
    _pluginBatchGroupAnchor: null,
    _pluginEntriesHandler: null,
    _pluginFlyoutKeyHandler: null,
    _pluginFlyoutScrollHandler: null,

    get searchQuery() {
      return this.$store.global.viewState.searchQuery;
    },
    set searchQuery(val) {
      this.$store.global.viewState.searchQuery = val;
    },

    get wiSearchQuery() {
      return this.$store.global.wiSearchQuery;
    },
    set wiSearchQuery(val) {
      this.$store.global.wiSearchQuery = val;
    },

    get chatSearchQuery() {
      return this.$store.global.chatSearchQuery;
    },
    set chatSearchQuery(val) {
      this.$store.global.chatSearchQuery = val;
    },

    get presetSearch() {
      return this.$store.global.presetSearch;
    },
    set presetSearch(val) {
      this.$store.global.presetSearch = val;
    },

    get extensionSearch() {
      return this.$store.global.extensionSearch;
    },
    set extensionSearch(val) {
      this.$store.global.extensionSearch = val;
    },

    get beautifySearch() {
      return this.$store.global.beautifySearch;
    },
    set beautifySearch(val) {
      this.$store.global.beautifySearch = val;
    },

    get searchType() {
      return this.$store.global.viewState.searchType;
    },
    set searchType(val) {
      this.$store.global.viewState.searchType = val;
    },

    get searchScope() {
      return this.$store.global.viewState.searchScope || "current";
    },
    set searchScope(val) {
      const vs = this.$store.global.viewState;
      const next = ["current", "all_dirs", "full"].includes(val)
        ? val
        : "current";
      if (vs.searchScope === next) return;
      vs.searchScope = next;
      if (next !== "all_dirs") {
        vs.allDirsOnlyWithFilters = false;
      }

      // 切换范围时清空选择，避免跨范围误操作
      vs.selectedIds = [];
      vs.lastSelectedId = null;
      vs.draggedCards = [];
    },

    get searchMode() {
      return this.currentMode === "worldinfo"
        ? this.$store.global.wiSearchMode
        : this.$store.global.cardSearchMode;
    },
    set searchMode(val) {
      const next = val === "fulltext" ? "fulltext" : "fast";
      if (this.currentMode === "worldinfo") {
        this.$store.global.wiSearchMode = next;
        return;
      }
      this.$store.global.cardSearchMode = next;
    },

    get canUseFulltextSearch() {
      if (this.currentMode === "worldinfo") {
        return !!this.$store.global.settingsForm.worldinfo_list_use_index;
      }
      if (this.currentMode === "cards") {
        return (
          !!this.$store.global.settingsForm.cards_list_use_index &&
          !!this.$store.global.settingsForm.fast_search_use_index
        );
      }
      return false;
    },

    // 世界书搜索分类：智能搜索会同时匹配名称、内容、备注与所属角色卡；
    // 其余三项只查对应索引列，因此更快也更精确。
    get wiSearchField() {
      return this.$store.global.wiSearchField || "smart";
    },
    set wiSearchField(val) {
      const allowed = ["smart", "name", "filename", "owner"];
      this.$store.global.wiSearchField = allowed.includes(val) ? val : "smart";
    },

    // 精确分类绕开全文索引，因此不受「全文」开关限制。
    get wiSearchFieldIsPrecise() {
      return this.wiSearchField !== "smart";
    },

    ensureSearchModeAllowed() {
      if (this.searchMode !== "fulltext" || this.canUseFulltextSearch) return;
      this.searchMode = "fast";
    },

    refreshIndexStatus() {
      const previous = this.$store.global.indexStatus || {};
      return getIndexStatus()
        .then((res) => {
          if (res && res.success && res.status) {
            this.$store.global.indexStatus = res.status;
            this.handleIndexStatusTransition(previous, res.status);
          }
          this.ensureSearchModeAllowed();
          return res;
        })
        .catch(() => {
          this.$store.global.indexStatus = {
            ...(this.$store.global.indexStatus || {}),
            state: "error",
            message: "index_status_unavailable",
          };
          this.ensureSearchModeAllowed();
          return { success: false };
        });
    },

    // 后台索引升级结束（building → ready）时刷新列表：
    // 升级前列表走的是旧索引/磁盘回退路径，新索引生效后需要重取一次。
    handleIndexStatusTransition(previous, next) {
      const wasBuilding =
        String(previous.state || "") === "building" ||
        Boolean(previous.upgrade_active);
      const isBuilding =
        String(next.state || "") === "building" || Boolean(next.upgrade_active);
      if (!wasBuilding || isBuilding) return;

      window.dispatchEvent(new CustomEvent("refresh-wi-list", { detail: { resetPage: false } }));
      window.dispatchEvent(new CustomEvent("refresh-card-list"));

      // 升级是在后台悄悄完成的，明确告诉用户一声，否则「进度条怎么没了」很容易
      // 被当成构建失败。
      if (previous.upgrade_active && typeof this.$store.global.showToast === "function") {
        this.$store.global.showToast("索引升级完成，列表已刷新", 3000, "check");
      }
    },

    startIndexStatusPolling() {
      this.stopIndexStatusPolling();
      const tick = () => {
        this.refreshIndexStatus().finally(() => {
          // 用链式 setTimeout 而不是固定 interval：构建中要更快（1.5s），
          // 空闲时放慢到 5s，避免无谓轮询。
          this.$store.global.indexStatusPollTimer = window.setTimeout(
            tick,
            this.indexStatusPollInterval,
          );
        });
      };
      tick();
    },

    get indexStatusPollInterval() {
      const status = this.$store.global.indexStatus || {};
      const busy =
        String(status.state || "") === "building" || Boolean(status.upgrade_active);
      return busy ? 1500 : 5000;
    },

    stopIndexStatusPolling() {
      if (this.$store.global.indexStatusPollTimer) {
        window.clearTimeout(this.$store.global.indexStatusPollTimer);
        this.$store.global.indexStatusPollTimer = null;
      }
    },

    get currentSort() {
      return (
        this.$store.global.currentSort ||
        this.$store.global.settingsForm.default_sort ||
        "date_desc"
      );
    },
    set currentSort(val) {
      this.$store.global.currentSort = val;
    },

    get showHeaderSort() {
      return this.$store.global.settingsForm.show_header_sort !== false;
    },

    get filterTags() {
      return this.$store.global.viewState.filterTags;
    },
    set filterTags(val) {
      this.$store.global.viewState.filterTags = val;
    },

    get recursiveFilter() {
      return this.$store.global.viewState.recursiveFilter;
    },
    set recursiveFilter(val) {
      const viewState = this.$store.global.viewState;
      viewState.recursiveFilter = val;
      if (val !== true) {
        viewState.allDirsOnlyWithFilters = false;
      }
    },

    get selectedIds() {
      return this.$store.global.viewState.selectedIds;
    },
    set selectedIds(val) {
      this.$store.global.viewState.selectedIds = val;
    },
    get wiList() {
      return this.$store.global.wiList || [];
    },
    get presetList() {
      return this.$store.global.presetList || [];
    },

    // 当前页是否全选（用于显示逻辑）
    isCurrentPageAllSelected: false,

    get currentMode() {
      return this.$store.global.currentMode;
    },
    get isDarkMode() {
      return this.$store.global.isDarkMode;
    },
    get deviceType() {
      return this.$store.global.deviceType;
    },
    toggleDarkMode(event) {
      this.$store.global.toggleDarkMode(event);
    },
    get showFavoriteFilter() {
      return this.currentMode === "chats";
    },
    get cardAdvancedFilterCount() {
      if (this.currentMode !== "cards") return 0;
      return this.$store.global.getCardAdvancedFilterCount();
    },
    get activeFavFilter() {
      return this.$store.global.getFavoriteFilter(this.currentMode);
    },
    get favoriteFilterTitle() {
      if (this.activeFavFilter === "included") return "当前：只显示收藏";
      if (this.activeFavFilter === "excluded") return "当前：排除收藏";
      return "当前：显示全部";
    },
    get indexStatusLabel() {
      const status = this.$store.global.indexStatus || {};
      if (status.scan_active) return "正在扫描资源";
      const state = String(status.state || "");
      if (state === "building") return this.indexStatusPhaseLabel;
      if (state === "error") return "索引异常";
      return "";
    },

    // 索引构建阶段 → 人话。后台重建不再阻塞启动，用户需要知道现在在干什么。
    get indexStatusPhaseLabel() {
      const status = this.$store.global.indexStatus || {};
      const scope = String(status.scope || "");
      const phase = String((status[scope] || {}).phase || status.phase || "");
      const scopeLabel = scope === "worldinfo" ? "世界书" : "角色卡";
      if (phase === "backfill_embedded_worldinfo_metadata") {
        return "正在扫描内嵌世界书";
      }
      if (phase === "build_entities") return `正在重建${scopeLabel}索引`;
      if (phase === "activate_generation") return `正在启用${scopeLabel}索引`;
      if (phase === "prepare_generation") return `准备重建${scopeLabel}索引`;
      // 升级线程已起但还没分配 generation：scope 行仍是上一次的 ready，
      // 别让用户看到「已就绪」而整体状态是构建中。
      return `准备重建${scopeLabel}索引`;
    },

    // 当前构建 scope 的进度：有 total 才算百分比，否则返回 null 表示"不确定"。
    get indexStatusProgress() {
      const status = this.$store.global.indexStatus || {};
      const scope = String(status.scope || "");
      const block = status[scope] || {};
      const done = Number(block.progress_done || 0);
      const total = Number(block.progress_total || 0);
      return { done, total };
    },

    get indexStatusPercent() {
      const { done, total } = this.indexStatusProgress;
      if (!total || total <= 0) return null;
      return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
    },

    get indexStatusCountText() {
      const { done, total } = this.indexStatusProgress;
      if (!total || total <= 0) return "";
      return `${Math.min(done, total)} / ${total}`;
    },

    get indexStatusTitle() {
      const status = this.$store.global.indexStatus || {};
      if (String(status.state || "") === "error") {
        return String(status.message || "索引构建失败，可在设置里手动重建");
      }
      if (status.scan_active) {
        return `正在校验磁盘资源：${String(status.scan_message || "")}`;
      }
      return "索引在后台构建，期间可正常浏览；重建完成后会自动刷新列表";
    },
    get favoriteFilterLabel() {
      if (this.activeFavFilter === "included") return "只看收藏";
      if (this.activeFavFilter === "excluded") return "排除收藏";
      return "收藏筛选";
    },
    get canOpenUrlImport() {
      return this.currentMode === "cards";
    },
    get urlImportTitle() {
      return this.canOpenUrlImport
        ? "URL 导入角色卡"
        : "URL 导入仅支持角色卡模式";
    },
    get showMobileUploadButton() {
      return (
        this.deviceType === "mobile" &&
        MOBILE_HEADER_UPLOAD_MODES.includes(this.currentMode)
      );
    },
    get showMobileRefreshButton() {
      return (
        this.deviceType === "mobile" &&
        MOBILE_HEADER_UPLOAD_MODES.includes(this.currentMode)
      );
    },

    // 移动端菜单状态
    showMobileMenu: false,

    init() {
      this.startIndexStatusPolling();

      this.$watch("currentMode", () => {
        this.ensureSearchModeAllowed();
      });

      this.$watch("$store.global.settingsForm.cards_list_use_index", () => {
        this.ensureSearchModeAllowed();
      });

      this.$watch("$store.global.settingsForm.fast_search_use_index", () => {
        this.ensureSearchModeAllowed();
      });

      this.$watch("$store.global.settingsForm.worldinfo_list_use_index", () => {
        this.ensureSearchModeAllowed();
      });

      window.addEventListener("close-header-mobile-menu", () => {
        this.closeMobileMenu();
      });

      // 监听加载菜单请求
      window.addEventListener("load-rulesets-for-menu", () => {
        listRuleSets().then((res) => {
          if (res.success) {
            this.availableRuleSets = res.items;
            // 同步到全局 store 供 contextMenu 使用
            this.$store.global.availableRuleSets = res.items;
          }
        });
      });

      // 监听选中状态变化，更新当前页全选状态
      this.$watch("selectedIds", () => {
        this.updateCurrentPageAllSelectedStatus();
      });

      // 监听页面变化，更新当前页全选状态
      window.addEventListener("refresh-card-list", () => {
        setTimeout(() => this.updateCurrentPageAllSelectedStatus(), 200);
      });

      // 监听分页切换事件，立即更新全选状态
      window.addEventListener("card-page-changed", () => {
        // 延迟一点，等待 DOM 更新完成
        setTimeout(() => this.updateCurrentPageAllSelectedStatus(), 100);
      });

      window.addEventListener("beforeunload", () => {
        this.stopIndexStatusPolling();
      });

      // 插件 `batch.actions` 落点：注册表变更 / 选中变化都要重算
      this._pluginEntriesHandler = () => this.refreshPluginBatchEntries();
      window.addEventListener("contributions:changed", this._pluginEntriesHandler);
      window.addEventListener("plugins:loaded", this._pluginEntriesHandler);
      this.refreshPluginBatchEntries();

      // 二级浮层：Escape 关闭；宿主页面 / 菜单滚动时父项会跑位，也收起。
      // 浮层自身滚动不算（长列表要能在浮层里滚）。
      this._pluginFlyoutKeyHandler = (event) => {
        if (event.key !== "Escape" || !this.activePluginBatchGroup) return;
        event.stopPropagation();
        this.closePluginBatchGroup();
      };
      window.addEventListener("keydown", this._pluginFlyoutKeyHandler, true);
      this._pluginFlyoutScrollHandler = (event) => {
        if (!this.activePluginBatchGroup) return;
        const flyout = this.pluginBatchFlyoutEl();
        if (flyout && event.target instanceof Node && flyout.contains(event.target)) return;
        this.closePluginBatchGroup();
      };
      window.addEventListener("scroll", this._pluginFlyoutScrollHandler, true);
    },

    destroy() {
      if (this._pluginEntriesHandler) {
        window.removeEventListener("contributions:changed", this._pluginEntriesHandler);
        window.removeEventListener("plugins:loaded", this._pluginEntriesHandler);
        this._pluginEntriesHandler = null;
      }
      if (this._pluginFlyoutKeyHandler) {
        window.removeEventListener("keydown", this._pluginFlyoutKeyHandler, true);
        this._pluginFlyoutKeyHandler = null;
      }
      if (this._pluginFlyoutScrollHandler) {
        window.removeEventListener("scroll", this._pluginFlyoutScrollHandler, true);
        this._pluginFlyoutScrollHandler = null;
      }
    },

    // === 插件批量落点（v3：batch.actions） ===

    /** 批量菜单求值用的贡献上下文（设计 §5.1：`{mode, target, selection}`）。 */
    contributionContext() {
      const mode = String(this.currentMode || "");
      const ids = Array.isArray(this.selectedIds)
        ? this.selectedIds.map((id) => String(id)).filter(Boolean)
        : [];
      return {
        mode,
        target: { type: "selection", kind: "selection", mode, id: "", path: "", ids },
        selection: {
          mode: ids.length === 0 ? "none" : ids.length > 1 ? "multi" : "single",
          ids,
        },
      };
    },

    /**
     * 批量菜单里的贡献节点（注册表 `menuTree("batch.actions")`）。
     *
     * `when` 不通过的节点**仍然返回**，但 `enabled === false`——渲染层把
     * 「不适用」表达成置灰 + `disabledHint`（设计 §4.4.3），不再自己过滤：
     * 过滤会让插件作者无从解释「为什么我的动作不见了」。
     */
    refreshPluginBatchEntries() {
      try {
        const ctx = this.contributionContext();
        this.pluginBatchNodes =
          ContributionRegistry.menuTree("batch.actions", {
            context: ctx,
            contextOverride: ctx,
          }) || [];
      } catch (error) {
        console.warn("[header] 读取插件 batch 菜单失败:", error);
        this.pluginBatchNodes = [];
      }
      this.closePluginBatchGroup();
    },

    /** 贡献节点图标（资源路径需要 pluginId 才能解析）。 */
    menuNodeIconHtml(node) {
      return buildIcon(String((node && node.icon) || "circle-dot"), {
        className: "ui-icon--sm",
        pluginId: String((node && node.pluginId) || ""),
      }).outerHTML;
    },

    /** 节点是否是子菜单（有 children）。 */
    hasMenuChildren(node) {
      return Boolean(node && Array.isArray(node.children) && node.children.length);
    },

    /** 节点是否不可执行（`when` 不通过或被插件置为不可用）。 */
    isMenuNodeDisabled(node) {
      return Boolean(node) && (node.enabled === false || node.ok === false);
    },

    /** 节点角标文案：数字超 99 折成 `99+`；对象形态取 `text/inner/value`。 */
    menuNodeBadge(node) {
      const badge = node && node.badge;
      if (badge === null || badge === undefined || badge === "") return "";
      if (typeof badge === "object") {
        return String(badge.text ?? badge.inner ?? badge.value ?? "");
      }
      const num = Number(badge);
      if (Number.isFinite(num)) return num > 99 ? "99+" : String(num);
      return String(badge);
    },

    /** 置灰项的悬浮说明（可见但不可点，给原因）。 */
    menuNodeHint(node) {
      if (!node) return "";
      return String(node.disabledHint || node.description || "");
    },

    /**
     * 移动端选中条用：把贡献树拍平成可执行节点数组。
     *
     * 移动端是一排图标按钮，没有悬停子菜单的位置，所以不折叠——直接平铺
     * 每个任务按钮。置灰节点不放进移动端扁平栏（那里没法展示 disabledHint）。
     */
    get pluginBatchFlatEntries() {
      const rows = [];
      const walk = (nodes) => {
        for (const node of nodes || []) {
          if (!node || node.type === "separator") continue;
          if (this.hasMenuChildren(node)) walk(node.children);
          else if (!this.isMenuNodeDisabled(node)) rows.push(node);
        }
      };
      walk(this.pluginBatchNodes);
      return rows;
    },

    /**
     * 二级浮层元素。
     *
     * 浮层被 `x-teleport` 移到了 `body`（`.header-bar` 的 backdrop-filter 会给
     * fixed 后代造包含块，留在 header 里定位会以 header 为基准），所以不能在
     * `this.$el` 里找，也不能靠 x-ref。
     */
    pluginBatchFlyoutEl() {
      if (typeof document === "undefined") return null;
      return document.querySelector("[data-plugin-batch-flyout]");
    },

    /**
     * 打开某个贡献子菜单的二级浮层（fixed，固定向右展开、纵向自适应）。
     *
     * `anchorEl` 是父项按钮：坐标按它的 `getBoundingClientRect()` 计算。
     */
    openPluginBatchGroup(nodeId, anchorEl) {
      const target = String(nodeId || "");
      if (!target) return;
      this.activePluginBatchGroup = target;
      // 模板可能传 `$event`（Alpine 的事件对象），统一归一化成元素
      this._pluginBatchGroupAnchor = resolveAnchorElement(anchorEl);
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          const flyout = this.pluginBatchFlyoutEl();
          if (!flyout || !this._pluginBatchGroupAnchor) return;
          if (!positionFlyoutElement(flyout, this._pluginBatchGroupAnchor)) {
            requestAnimationFrame(() => {
              const retry = this.pluginBatchFlyoutEl();
              if (retry && this._pluginBatchGroupAnchor) {
                positionFlyoutElement(retry, this._pluginBatchGroupAnchor);
              }
            });
          }
        });
      });
    },

    /** 同一个父项再点一次就收起（与「自动处理 / 来源更新」的交互一致）。 */
    togglePluginBatchGroup(node, anchorEl) {
      if (!node || this.isMenuNodeDisabled(node)) return;
      const target = String(node.id || "");
      if (!target) return;
      if (String(this.activePluginBatchGroup || "") === target) {
        this.closePluginBatchGroup();
        return;
      }
      this.openPluginBatchGroup(target, anchorEl);
    },

    /** 收起二级菜单。 */
    closePluginBatchGroup() {
      this.activePluginBatchGroup = "";
      this._pluginBatchGroupAnchor = null;
    },

    /** 二级菜单当前展示的贡献节点（找不到时返回 null）。 */
    activePluginBatchGroupUnit() {
      const key = String(this.activePluginBatchGroup || "");
      if (!key) return null;
      return (this.pluginBatchNodes || []).find((node) => node && String(node.id || "") === key) || null;
    },

    /** 某个贡献子菜单是否展开。 */
    isPluginBatchGroupOpen(node) {
      const target = String((node && node.id) || node || "");
      return Boolean(target) && String(this.activePluginBatchGroup || "") === target;
    },

    /**
     * 入口进度百分比（`node.progress` 是 0–1 的比例，设计 §4.4.5）。
     *
     * 兼容旧形态 `{done,total}`：两者都归一化到 0–100。
     * 返回 `null` 表示「没有进度可画」，让模板整块跳过——返回 0 会画出一条
     * 0% 的空槽，看起来像「卡住了」。
     */
    pluginBatchEntryProgressPercent(node) {
      const progress = node && node.progress;
      if (progress === null || progress === undefined) return null;
      if (typeof progress === "number") {
        if (!Number.isFinite(progress)) return null;
        return Math.max(0, Math.min(100, Math.round(progress * 100)));
      }
      if (typeof progress === "object") {
        const total = Number(progress.total || 0);
        if (!Number.isFinite(total) || total <= 0) return null;
        const done = Number(progress.done || 0);
        const ratio = Number.isFinite(done) ? done / total : 0;
        return Math.max(0, Math.min(100, Math.round(ratio * 100)));
      }
      return null;
    },

    /** 入口角标文案（`null` / `undefined` / `''` 都表示不画角标）。 */
    pluginBatchEntryBadge(node) {
      return this.menuNodeBadge(node);
    },

    /**
     * 执行一个批量入口：选中集随 ctx 一起交给运行时（S4 统一触发通道）。
     *
     * 置灰项不执行（菜单里仍可见并附 `disabledHint`）。
     */
    runPluginBatchEntry(node) {
      if (!node || node.type === "separator" || this.hasMenuChildren(node)) return false;
      if (this.isMenuNodeDisabled(node)) return false;

      window.dispatchEvent(
        new CustomEvent("contribution:trigger", {
          detail: {
            pluginId: String(node.pluginId || ""),
            nodeId: String(node.id || ""),
            trigger: "menu",
            ctx: this.contributionContext(),
          },
        }),
      );
      return true;
    },

    // 更新当前页全选状态
    updateCurrentPageAllSelectedStatus() {
      if (this.currentMode === "worldinfo") {
        const currentPageWorldInfoIds = this.wiList
          .filter((item) => this.canSelectWorldInfoItem(item))
          .map((item) => item.id);

        if (currentPageWorldInfoIds.length === 0) {
          this.isCurrentPageAllSelected = false;
          return;
        }

        const currentSelected = new Set(this.selectedIds);
        this.isCurrentPageAllSelected = currentPageWorldInfoIds.every((id) =>
          currentSelected.has(id),
        );
        return;
      }

      if (this.currentMode === "presets") {
        const currentPagePresetIds = this.presetList
          .filter((item) => this.canSelectPresetItem(item))
          .map((item) => item.id);

        if (currentPagePresetIds.length === 0) {
          this.isCurrentPageAllSelected = false;
          return;
        }

        const currentSelected = new Set(this.selectedIds);
        this.isCurrentPageAllSelected = currentPagePresetIds.every((id) =>
          currentSelected.has(id),
        );
        return;
      }

      if (this.currentMode !== "cards") {
        this.isCurrentPageAllSelected = false;
        return;
      }

      let currentPageCardIds = [];
      let responded = false;

      const handler = (e) => {
        currentPageCardIds = e.detail.ids || [];
        responded = true;
        window.removeEventListener("all-card-ids-response", handler);

        if (currentPageCardIds.length === 0) {
          this.isCurrentPageAllSelected = false;
          return;
        }

        const currentSelected = new Set(this.selectedIds);
        this.isCurrentPageAllSelected = currentPageCardIds.every((id) =>
          currentSelected.has(id),
        );
      };
      window.addEventListener("all-card-ids-response", handler);
      window.dispatchEvent(new CustomEvent("get-all-card-ids"));

      setTimeout(() => {
        if (!responded) {
          window.removeEventListener("all-card-ids-response", handler);
          const cardElements = document.querySelectorAll("[data-card-id]");
          currentPageCardIds = Array.from(cardElements)
            .map((el) => el.getAttribute("data-card-id"))
            .filter(Boolean);

          if (currentPageCardIds.length === 0) {
            this.isCurrentPageAllSelected = false;
            return;
          }

          const currentSelected = new Set(this.selectedIds);
          this.isCurrentPageAllSelected = currentPageCardIds.every((id) =>
            currentSelected.has(id),
          );
        }
      }, 100);
    },

    formatBatchResult(result, mode = "automation") {
      if (!result) return "操作未返回结果";
      if (mode === "source_update") {
        return `检查完成！\n已检查: ${result.checked || 0} 张\n本次发现变化: ${result.updated || 0} 张\n当前待处理: ${result.pending || 0} 张\n本次无新变化: ${result.unchanged || 0} 张\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
      }
      if (mode === "source_acknowledge") {
        return `确认完成！\n已确认无需更新: ${result.acknowledged || 0} 张\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
      }

      return `执行完成！\n已处理: ${result.processed || 0} 张\n移动: ${result.moves || 0} 张\n标签变更: ${result.tag_changes || 0} 次\n替换: ${result.text_replacements || 0} 处\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
    },

    async executeRuleSet(rulesetId) {
      if (this.selectedIds.length === 0) return;
      if (isBatchOperationRunning()) {
        this.$store.global.showToast("已有批量操作正在进行", 2400);
        return;
      }

      const count = this.selectedIds.length;
      if (!confirm(`确定对选中的 ${count} 张卡片执行此规则集吗？`)) return;

      const targetPayload = { card_ids: [...this.selectedIds] };
      try {
        const result = await runAutomationBatch({
          rulesetId,
          targetPayload,
          title: `自动处理 ${count} 张卡片`,
        });
        if (result?.selected) {
          this.$store.global.showToast("执行完成！", 2400, "check");
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
          window.dispatchEvent(new CustomEvent("refresh-folder-list"));
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "批量执行失败", 3600, "close");
      }
    },

    async checkSelectedSourceUpdates() {
      if (this.currentMode !== "cards" || this.selectedIds.length === 0) return;
      if (isBatchOperationRunning()) {
        this.$store.global.showToast("已有批量操作正在进行", 2400);
        return;
      }

      const ids = [...this.selectedIds];
      if (!confirm(`确定检查选中的 ${ids.length} 张卡片的来源更新吗？\n\n不支持的来源会跳过，网络失败会记录后继续。`)) return;

      try {
        const result = await runSourceUpdateBatch({
          targetPayload: { card_ids: ids },
          title: `检查 ${ids.length} 张卡片的来源更新`,
        });
        if (result?.selected) {
          this.$store.global.showToast("检查完成！", 2400, "check");
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "批量检查失败", 3600, "close");
      }
    },

    async acknowledgeSelectedSourceUpdates() {
      if (this.currentMode !== "cards" || this.selectedIds.length === 0) return;
      if (isBatchOperationRunning()) {
        this.$store.global.showToast("已有批量操作正在进行", 2400);
        return;
      }

      const ids = [...this.selectedIds];
      if (!confirm(`确认将选中卡片中已有的待处理更新标记为“无需更新”吗？\n\n只处理已显示“有更新”的角色卡；不会修改任何角色卡文件。`)) {
        return;
      }

      try {
        const result = await runSourceUpdateAcknowledgeBatch({
          targetPayload: { card_ids: ids },
          title: "确认待处理更新无需处理",
        });
        if (result?.selected) {
          alert(`${this.formatBatchResult(result, "source_acknowledge")}${result.cancelled ? "\n\n已停止后续处理。" : ""}`);
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "批量确认失败", 3600, "close");
      }
    },

    openSourceMonitorPool() {
      window.dispatchEvent(new CustomEvent("open-source-monitor-pool"));
    },

    async addSelectedToSourceMonitorPool() {
      if (this.currentMode !== "cards" || this.selectedIds.length === 0) return;
      try {
        const response = await addSourceUpdateMonitorEntries([...this.selectedIds]);
        const results = response?.results || [];
        const added = results.filter((item) => item.status === "added").length;
        const failed = results.filter((item) => !item.success).length;
        const reasons = results
          .filter((item) => !item.success && item.reason)
          .slice(0, 2)
          .map((item) => `${item.card_id}：${item.reason}`)
          .join("；");
        this.$store.global.showToast(
          `已加入监控池 ${added} 张${failed ? `；${failed} 项失败${reasons ? `：${reasons}` : ""}` : ""}`,
          reasons ? 5200 : 3200,
        );
        this.openSourceMonitorPool();
      } catch (error) {
        this.$store.global.showToast(`加入监控池失败：${error?.message || "网络错误"}`, 3200, "close");
      }
    },

    fetchCards() {
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    fetchWorldInfoList() {
      window.dispatchEvent(new CustomEvent("refresh-wi-list"));
    },

    fetchChats() {
      window.dispatchEvent(new CustomEvent("refresh-chat-list"));
    },

    refreshCurrentMode() {
      this.closeMobileMenu();
      if (this.currentMode === "cards") {
        this.fetchCards();
        return;
      }
      if (this.currentMode === "worldinfo") {
        this.fetchWorldInfoList();
        return;
      }
      if (this.currentMode === "chats") {
        this.fetchChats();
        return;
      }
      if (this.currentMode === "presets") {
        window.dispatchEvent(new CustomEvent("refresh-preset-list"));
        return;
      }
      if (["regex", "scripts", "quick_replies"].includes(this.currentMode)) {
        window.dispatchEvent(
          new CustomEvent("refresh-extension-list", {
            detail: { mode: this.currentMode },
          }),
        );
        return;
      }
      if (this.currentMode === "beautify") {
        window.dispatchEvent(new CustomEvent("refresh-beautify-list"));
      }
    },

    createWorldInfoBook() {
      if (this.currentMode !== "worldinfo") return;
      window.dispatchEvent(new CustomEvent("create-worldinfo"));
    },

    get showImportUrlModal() {
      // 这里返回什么不重要，因为弹窗状态由 importModal 组件自己管理
      return false;
    },
    set showImportUrlModal(val) {
      if (!val || !this.canOpenUrlImport) return;

      // 获取当前浏览的分类作为默认导入位置
      const currentCat = this.$store.global.viewState.filterCategory;
      // 触发 importModal 打开
      window.dispatchEvent(
        new CustomEvent("open-import-url", {
          detail: { category: currentCat },
        }),
      );
    },

    openUrlImport() {
      if (!this.canOpenUrlImport) return;
      this.showImportUrlModal = true;
    },

    // 打开设置模态框
    openSettings() {
      this.$store.global.showSettingsModal = true;
    },

    openBatchTagModal() {
      if (this.selectedIds.length === 0) return;

      // 派发事件，将 Store 中的 selectedIds 传给 Modal
      window.dispatchEvent(
        new CustomEvent("open-batch-tag-modal", {
          detail: { ids: [...this.selectedIds] },
        }),
      );
    },

    selectedWorldInfoItems() {
      return this.selectedIds
        .map((id) => this.wiList.find((item) => item.id === id))
        .filter(Boolean);
    },

    canSelectWorldInfoItem(item) {
      return !!item && (item.source_type || item.type) !== "embedded";
    },

    canDeleteWorldInfoSelection() {
      const items = this.selectedWorldInfoItems();
      return (
        items.length > 0 &&
        items.every((item) => (item.source_type || item.type) !== "embedded")
      );
    },

    canMoveWorldInfoSelection() {
      const items = this.selectedWorldInfoItems();
      return (
        items.length > 0 &&
        items.every((item) => (item.source_type || item.type) === "global")
      );
    },

    selectedPresetItems() {
      return this.selectedIds
        .map((id) => this.presetList.find((item) => item.id === id))
        .filter(Boolean);
    },

    canSelectPresetItem(item) {
      return !!item;
    },

    canDeletePresetSelection() {
      const items = this.selectedPresetItems();
      return (
        items.length > 0 &&
        items.every((item) => this.canSelectPresetItem(item))
      );
    },

    canMovePresetSelection() {
      const items = this.selectedPresetItems();
      return (
        items.length > 0 &&
        items.every((item) => (item.source_type || item.type) === "global")
      );
    },

    canMergePresetSelection() {
      const items = this.selectedPresetItems();
      if (items.length < 2) return false;
      const scopeKeys = new Set(items.map((item) => String(item.root_scope_key || "")));
      return (
        scopeKeys.size === 1 &&
        items.every((item) => String(item.preset_kind || "").trim() === "openai")
      );
    },

    getPresetMergeSelectionTitle() {
      const items = this.selectedPresetItems();
      if (items.length < 2) return "至少选择两个预设后才能合并";
      const scopeKeys = new Set(items.map((item) => String(item.root_scope_key || "")));
      if (scopeKeys.size !== 1) return "仅支持同一作用域内合并";
      if (!items.every((item) => String(item.preset_kind || "").trim() === "openai")) {
        return "仅支持 OpenAI/对话补全预设";
      }
      return "合并选中的预设为多版本家族";
    },

    deleteSelectedWorldInfo() {
      if (!this.canDeleteWorldInfoSelection()) return;
      window.dispatchEvent(new CustomEvent("delete-selected-worldinfo"));
    },

    moveSelectedWorldInfo() {
      if (!this.canMoveWorldInfoSelection()) return;
      window.dispatchEvent(
        new CustomEvent("move-selected-worldinfo", {
          detail: {
            target_category: this.$store.global.wiFilterCategory || "",
          },
        }),
      );
    },

    deleteSelectedPresets() {
      if (!this.canDeletePresetSelection()) return;
      window.dispatchEvent(new CustomEvent("delete-selected-presets"));
    },

    moveSelectedPresets() {
      if (!this.canMovePresetSelection()) return;
      window.dispatchEvent(
        new CustomEvent("move-selected-presets", {
          detail: {
            target_category: this.$store.global.presetFilterCategory || "",
          },
        }),
      );
    },

    mergeSelectedPresets() {
      if (!this.canMergePresetSelection()) return;
      window.dispatchEvent(
        new CustomEvent("merge-selected-presets", {
          detail: {
            selected_ids: this.selectedIds.slice(),
          },
        }),
      );
    },

    // 触发导入弹窗
    triggerImport() {
      this.openUrlImport();
    },

    async deleteSelectedCards() {
      const ids = this.selectedIds;
      if (ids.length === 0) return;

      // 复用 CardGrid 的删除逻辑不太方便，建议直接调用 API
      import("../api/card.js").then(async (module) => {
        const { deleteCards, checkResourceFolders } = module;

        if (!confirm(`确定将选中的 ${ids.length} 张卡片移至回收站吗？`)) return;

        // 检查是否有资源目录需要确认
        const checkRes = await checkResourceFolders(ids);
        let deleteResources = false;

        if (checkRes.success && checkRes.has_resources) {
          const folders = checkRes.resource_folders;
          let resourceMsg = `检测到以下角色卡关联了资源目录：\n\n`;

          folders.forEach((item) => {
            resourceMsg += `${item.card_name}\n   资源目录: ${item.resource_folder}\n\n`;
          });

          resourceMsg += `是否连带删除这些资源目录？\n`;
          resourceMsg += `（注意：如果资源目录包含重要文件，建议选择"取消"保留目录）`;

          deleteResources = confirm(resourceMsg);
        }

        deleteCards(ids, deleteResources).then((res) => {
          if (res.success) {
            this.$store.global.showToast(`已删除 ${ids.length} 张卡片`, 3000, "trash");
            this.selectedIds = []; // 清空 Store
            window.dispatchEvent(new CustomEvent("refresh-card-list")); // 通知 Grid 刷新
          } else {
            alert("删除失败: " + res.msg);
          }
        });
      });
    },

    // 随机抽取角色卡 —— 已由抽卡弹窗（单抽 / 十连）取代。
    // 保留一个显式转发，避免外部（插件 / 快捷键）调用 randomCard() 时静默失效。
    randomCard() {
      this.openGachaDraw();
    },

    // 抽卡：单抽 / 十连（弹窗自身管理抽取与动画）
    openGachaDraw(mode = "multi") {
      if (this.currentMode !== "cards") {
        return;
      }
      window.dispatchEvent(
        new CustomEvent("open-gacha-draw", {
          detail: { mode: mode === "single" ? "single" : "multi" },
        }),
      );
    },

    randomByMode() {
      if (this.currentMode === "cards") {
        this.randomCard();
        return;
      }
      if (this.currentMode === "worldinfo") {
        this.randomWorldInfo();
        return;
      }
      if (this.currentMode === "chats") {
        this.randomChat();
        return;
      }
    },

    // 随机世界书
    randomWorldInfo() {
      // 世界书列表在 State 中，可以直接取
      const list = this.$store.global.wiList || [];
      if (list.length === 0) return;

      const item = list[Math.floor(Math.random() * list.length)];

      if (item.type === "embedded") {
        // 触发跳转事件
        window.dispatchEvent(
          new CustomEvent("jump-to-card-wi", { detail: item.card_id }),
        );
        alert(`随机选中了内嵌世界书: ${item.name}\n即将跳转到对应角色卡...`);
      } else {
        // 打开编辑器事件
        window.dispatchEvent(
          new CustomEvent("open-wi-editor", { detail: item }),
        );
      }
    },

    async randomChat() {
      const currentItems = this.$store.global.chatList || [];
      if (currentItems.length > 0) {
        const item =
          currentItems[Math.floor(Math.random() * currentItems.length)];
        window.dispatchEvent(
          new CustomEvent("open-chat-manager", {
            detail: { chat_id: item.id },
          }),
        );
        return;
      }

      const res = await listChats({
        page: 1,
        page_size: 100,
        search: this.chatSearchQuery || "",
        filter: this.$store.global.chatFilterType || "all",
        fav_filter: this.$store.global.getFavoriteFilter("chats"),
      });
      if (!res.success || !Array.isArray(res.items) || res.items.length === 0) {
        alert("当前没有可用聊天记录");
        return;
      }
      const item = res.items[Math.floor(Math.random() * res.items.length)];
      this.$store.global.currentMode = "chats";
      window.dispatchEvent(
        new CustomEvent("open-chat-manager", {
          detail: { chat_id: item.id },
        }),
      );
    },

    triggerChatImport() {
      if (this.currentMode !== "chats") {
        this.$store.global.currentMode = "chats";
      }

      if (!window.stUploadChatFiles) {
        alert("聊天网格尚未准备好，请稍后重试。");
        return;
      }
      window.dispatchEvent(
        new CustomEvent("open-chat-file-picker", {
          detail: { mode: "global" },
        }),
      );
    },

    // 删除当前筛选的所有标签 (批量操作)
    deleteFilterTags() {
      if (this.filterTags.length === 0) {
        return alert("请先选择要删除的标签");
      }

      if (this.selectedIds.length === 0) {
        return alert("请先全选或选中卡片，再执行批量删除标签操作。");
      }

      if (
        !confirm(
          `确定从选中的 ${this.selectedIds.length} 张卡片中移除标签: ${this.filterTags.join(", ")}?`,
        )
      )
        return;

      batchUpdateTags({
        card_ids: this.selectedIds,
        remove: this.filterTags,
      }).then((res) => {
        if (res.success) {
          let message = `成功更新 ${res.updated} 张卡片`;
          const merge = res.tag_merge || {};
          if (merge.cards) {
            message += `\n全局标签合并已应用到 ${merge.cards} 张卡片`;
          }
          alert(message);
          this.filterTags = []; // 清空筛选
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
        } else {
          alert(res.msg);
        }
      });
    },

    // 切换递归筛选
    toggleRecursiveFilter() {
      this.recursiveFilter = !this.recursiveFilter;
    },

    // 切换移动端菜单
    toggleMobileMenu() {
      this.showMobileMenu = !this.showMobileMenu;
    },

    // 关闭移动端菜单
    closeMobileMenu() {
      this.showMobileMenu = false;
    },

    openMobileSidebar() {
      this.closeMobileMenu();
      const nextVisible = !this.$store.global.visibleSidebar;
      this.$store.global.visibleSidebar = nextVisible;
      document.body.style.overflow = nextVisible ? "hidden" : "";
    },

    triggerMobileUpload() {
      this.closeMobileMenu();
      if (this.currentMode === "chats") {
        this.triggerChatImport();
        return;
      }
      window.dispatchEvent(new CustomEvent("request-mobile-upload"));
    },

    // 切换筛选标签
    toggleFilterTag(tag) {
      this.$store.global.toggleFilterTag(tag);
    },

    // 直接移除某个筛选标签（无论包含/排除）
    removeFilterTag(tag) {
      const vs = this.$store.global.viewState;
      const includeTags = (vs.filterTags || []).filter((t) => t !== tag);
      const excludeTags = (vs.excludedTags || []).filter((t) => t !== tag);

      vs.filterTags = includeTags;
      vs.excludedTags = excludeTags;
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    // 收藏显示切换
    toggleFavFilter() {
      if (!this.showFavoriteFilter) return;
      this.$store.global.toggleFavFilter(this.currentMode);
    },

    openCardAdvancedFilter() {
      if (this.currentMode !== "cards") return;
      this.closeMobileMenu();
      this.$store.global.openCardAdvancedFilterDrawer();
    },

    // 全选/取消全选（仅针对当前页）
    toggleSelectAll() {
      if (this.currentMode === "worldinfo") {
        const currentPageWorldInfoIds = this.wiList
          .filter((item) => this.canSelectWorldInfoItem(item))
          .map((item) => item.id);

        if (currentPageWorldInfoIds.length === 0) {
          return;
        }

        const currentSelected = new Set(this.selectedIds);
        const allSelected = currentPageWorldInfoIds.every((id) =>
          currentSelected.has(id),
        );
        this.selectedIds = allSelected
          ? this.selectedIds.filter(
              (id) => !currentPageWorldInfoIds.includes(id),
            )
          : Array.from(
              new Set([...this.selectedIds, ...currentPageWorldInfoIds]),
            );
        this.isCurrentPageAllSelected = !allSelected;
        return;
      }

      if (this.currentMode === "presets") {
        const currentPagePresetIds = this.presetList
          .filter((item) => this.canSelectPresetItem(item))
          .map((item) => item.id);

        if (currentPagePresetIds.length === 0) {
          return;
        }

        const currentSelected = new Set(this.selectedIds);
        const allSelected = currentPagePresetIds.every((id) =>
          currentSelected.has(id),
        );
        this.selectedIds = allSelected
          ? this.selectedIds.filter((id) => !currentPagePresetIds.includes(id))
          : Array.from(new Set([...this.selectedIds, ...currentPagePresetIds]));
        this.isCurrentPageAllSelected = !allSelected;
        return;
      }

      if (this.currentMode !== "cards") {
        return;
      }

      // 通过事件获取当前页的卡片 ID
      let currentPageCardIds = [];
      let responded = false;

      // 监听响应事件
      const handler = (e) => {
        currentPageCardIds = e.detail.ids || [];
        responded = true;
        window.removeEventListener("all-card-ids-response", handler);

        if (currentPageCardIds.length === 0) {
          return;
        }

        // 检查当前页是否已全选
        const currentSelected = new Set(this.selectedIds);
        const allSelected = currentPageCardIds.every((id) =>
          currentSelected.has(id),
        );

        if (allSelected) {
          // 取消全选：只移除当前页的卡片ID，保留其他页的选中
          const remainingIds = this.selectedIds.filter(
            (id) => !currentPageCardIds.includes(id),
          );
          this.selectedIds = remainingIds;
        } else {
          // 全选：合并当前选中和当前页的卡片 ID（去重）
          const merged = new Set([...this.selectedIds, ...currentPageCardIds]);
          this.selectedIds = Array.from(merged);
        }
        // 更新全选状态
        this.isCurrentPageAllSelected = !allSelected;
      };
      window.addEventListener("all-card-ids-response", handler);

      // 派发请求事件
      window.dispatchEvent(new CustomEvent("get-all-card-ids"));

      // 超时处理：如果 cardGrid 没有响应，尝试通过 DOM 获取
      setTimeout(() => {
        if (!responded) {
          window.removeEventListener("all-card-ids-response", handler);
          // 获取当前可见的卡片元素（当前页）
          const cardElements = document.querySelectorAll("[data-card-id]");
          currentPageCardIds = Array.from(cardElements)
            .map((el) => el.getAttribute("data-card-id"))
            .filter(Boolean);

          if (currentPageCardIds.length === 0) {
            return;
          }

          const currentSelected = new Set(this.selectedIds);
          const allSelected = currentPageCardIds.every((id) =>
            currentSelected.has(id),
          );

          if (allSelected) {
            // 取消全选：只移除当前页的卡片ID
            const remainingIds = this.selectedIds.filter(
              (id) => !currentPageCardIds.includes(id),
            );
            this.selectedIds = remainingIds;
          } else {
            // 全选：合并当前选中和当前页的卡片 ID
            const merged = new Set([
              ...this.selectedIds,
              ...currentPageCardIds,
            ]);
            this.selectedIds = Array.from(merged);
          }
          // 更新全选状态
          this.isCurrentPageAllSelected = !allSelected;
        }
      }, 100);
    },

    // 打开移动弹窗（触发事件）
    openMoveModal() {
      if (this.selectedIds.length === 0) return;
      // 派发事件，将选中的卡片ID传给移动弹窗
      window.dispatchEvent(
        new CustomEvent("open-move-cards-modal", {
          detail: { ids: [...this.selectedIds] },
        }),
      );
    },

    // 打开移动端执行规则弹窗（触发事件）
    openExecuteRulesMobile() {
      if (this.selectedIds.length === 0) return;
      // 派发事件，将选中的卡片ID传给执行规则弹窗
      window.dispatchEvent(
        new CustomEvent("open-execute-rules-mobile-modal", {
          detail: { ids: [...this.selectedIds] },
        }),
      );
    },
  };
}
