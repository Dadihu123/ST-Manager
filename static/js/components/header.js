/**
 * static/js/components/header.js
 * 顶部导航栏组件
 */

import { getRandomCard } from "../api/card.js";
import { batchUpdateTags, getIndexStatus } from "../api/system.js";
import { listRuleSets } from "../api/automation.js";
import {
  isBatchOperationRunning,
  runAutomationBatch,
  runSourceUpdateAcknowledgeBatch,
  runSourceUpdateBatch,
} from "../utils/batchOperations.js";
import { listChats } from "../api/chat.js";

const MOBILE_HEADER_UPLOAD_MODES = [
  "cards",
  "worldinfo",
  "presets",
  "regex",
  "scripts",
  "quick_replies",
  "beautify",
];

export default function header() {
  return {
    availableRuleSets: [],

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

    ensureSearchModeAllowed() {
      if (this.searchMode !== "fulltext" || this.canUseFulltextSearch) return;
      this.searchMode = "fast";
    },

    refreshIndexStatus() {
      return getIndexStatus()
        .then((res) => {
          if (res && res.success && res.status) {
            this.$store.global.indexStatus = res.status;
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

    startIndexStatusPolling() {
      this.stopIndexStatusPolling();
      this.refreshIndexStatus();
      this.$store.global.indexStatusPollTimer = window.setInterval(() => {
        this.refreshIndexStatus();
      }, 5000);
    },

    stopIndexStatusPolling() {
      if (this.$store.global.indexStatusPollTimer) {
        window.clearInterval(this.$store.global.indexStatusPollTimer);
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
      this.$store.global.viewState.recursiveFilter = val;
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
    toggleDarkMode() {
      this.$store.global.toggleDarkMode();
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
      const state = String(this.$store.global.indexStatus?.state || "");
      if (state === "building") return "索引构建中";
      if (state === "error") return "索引异常";
      return "";
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
    },

    // 切换排除目录 (用于 Header 点击 Chip)
    toggleExcludedCategory(cat) {
      let list = [...this.$store.global.viewState.excludedCategories];
      if (list.includes(cat)) {
        list = list.filter((t) => t !== cat);
      } else {
        list.push(cat);
      }
      this.$store.global.viewState.excludedCategories = list;
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
        return `✅ 检查完成！\n已检查: ${result.checked || 0} 张\n本次发现变化: ${result.updated || 0} 张\n当前待处理: ${result.pending || 0} 张\n本次无新变化: ${result.unchanged || 0} 张\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
      }
      if (mode === "source_acknowledge") {
        return `确认完成！\n已确认无需更新: ${result.acknowledged || 0} 张\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
      }

      return `✅ 执行完成！\n已处理: ${result.processed || 0} 张\n移动: ${result.moves || 0} 张\n标签变更: ${result.tag_changes || 0} 次\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
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
          alert(`${this.formatBatchResult(result)}${result.cancelled ? "\n\n已停止后续处理。" : ""}`);
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
          window.dispatchEvent(new CustomEvent("refresh-folder-list"));
        }
      } catch (error) {
        this.$store.global.showToast(`❌ ${error?.message || "批量执行失败"}`, 3600);
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
          alert(`${this.formatBatchResult(result, "source_update")}${result.cancelled ? "\n\n已停止后续处理。" : ""}`);
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
        }
      } catch (error) {
        this.$store.global.showToast(`❌ ${error?.message || "批量检查失败"}`, 3600);
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
        this.$store.global.showToast(`❌ ${error?.message || "批量确认失败"}`, 3600);
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
          let resourceMsg = `⚠️ 检测到以下角色卡关联了资源目录：\n\n`;

          folders.forEach((item) => {
            resourceMsg += `📁 ${item.card_name}\n   资源目录: ${item.resource_folder}\n\n`;
          });

          resourceMsg += `是否连带删除这些资源目录？\n`;
          resourceMsg += `（注意：如果资源目录包含重要文件，建议选择"取消"保留目录）`;

          deleteResources = confirm(resourceMsg);
        }

        deleteCards(ids, deleteResources).then((res) => {
          if (res.success) {
            this.$store.global.showToast(`🗑️ 已删除 ${ids.length} 张卡片`);
            this.selectedIds = []; // 清空 Store
            window.dispatchEvent(new CustomEvent("refresh-card-list")); // 通知 Grid 刷新
          } else {
            alert("删除失败: " + res.msg);
          }
        });
      });
    },

    // 随机抽取角色卡
    randomCard() {
      if (this.$store.global.isLoading) return;
      this.$store.global.isLoading = true;

      const vs = this.$store.global.viewState;

      // 使用 layout 中的筛选条件
      const params = {
        category: vs.filterCategory, // 访问父级 scope
        tags: vs.filterTags,
        search: vs.searchQuery,
        search_type: vs.searchType,
        search_scope: vs.searchScope || "current",
      };

      getRandomCard(params)
        .then((res) => {
          this.$store.global.isLoading = false;
          if (res.success && res.card) {
            // 触发打开详情页事件
            window.dispatchEvent(
              new CustomEvent("open-detail", { detail: res.card }),
            );

            // 高亮逻辑交给 Grid 监听
            window.dispatchEvent(
              new CustomEvent("highlight-card", { detail: res.card.id }),
            );
          } else {
            alert("抽取失败: " + (res.msg || "未知错误"));
          }
        })
        .catch((err) => {
          this.$store.global.isLoading = false;
          alert("网络错误: " + err);
        });
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
