/**
 * static/js/components/sidebar.js
 * 侧边栏组件：文件夹树与标签索引
 */

import { createFolder, moveFolder } from "../api/system.js";
import { moveCard } from "../api/card.js";
import { migrateLorebooks } from "../api/wi.js";

const TAG_PANE_RATIO_STORAGE_KEY = "st_manager_card_tags_split_ratio";
const DEFAULT_TAG_PANE_RATIO = 0.34;
const DEFAULT_VISIBLE_TAG_COUNT = 30;
const MIN_CARD_TAG_PANE_HEIGHT = 112;
const MIN_CARD_CATEGORY_PANE_HEIGHT = 220;
const MAX_CARD_TAG_PANE_RATIO = 0.6;
const ESTIMATED_TAG_ROW_HEIGHT = 34;
const ESTIMATED_TAG_CHIP_WIDTH = 96;
const MODULE_LABELS = Object.freeze({
  cards: "角色卡",
  worldinfo: "世界书",
  chats: "聊天",
  presets: "预设",
  regex: "正则脚本",
  scripts: "ST 脚本",
  quick_replies: "快速回复",
  beautify: "美化",
});

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function getMaxTagPaneHeight(totalHeight) {
  const preferredMaxHeight = Math.min(
    totalHeight * MAX_CARD_TAG_PANE_RATIO,
    totalHeight - MIN_CARD_CATEGORY_PANE_HEIGHT,
  );

  if (preferredMaxHeight >= MIN_CARD_TAG_PANE_HEIGHT) {
    return preferredMaxHeight;
  }

  return Math.max(0, totalHeight - MIN_CARD_CATEGORY_PANE_HEIGHT);
}

function readStoredTagPaneRatio() {
  try {
    const raw = localStorage.getItem(TAG_PANE_RATIO_STORAGE_KEY);
    if (raw === null) return DEFAULT_TAG_PANE_RATIO;

    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return DEFAULT_TAG_PANE_RATIO;

    return clamp(parsed, 0.18, MAX_CARD_TAG_PANE_RATIO);
  } catch (e) {
    return DEFAULT_TAG_PANE_RATIO;
  }
}

async function moveWorldInfoItems(items, targetCategory) {
  for (const item of items) {
    const resp = await fetch("/api/world_info/category/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_type: item.source_type || item.type,
        file_path: item.path,
        target_category: targetCategory,
      }),
    });
    const res = await resp.json();
    if (!res?.success) {
      throw new Error(res?.msg || "移动失败");
    }
  }
}

async function movePresetItems(items, targetCategory) {
  for (const item of items) {
    const resp = await fetch("/api/presets/category/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: item.id,
        source_type: item.source_type || item.type,
        file_path: item.path,
        target_category: targetCategory,
      }),
    });
    const res = await resp.json();
    if (!res?.success) {
      throw new Error(res?.msg || "移动失败");
    }
  }
}

function buildFolderTree(list, expandedFolders, extra = {}) {
  return (list || []).map((folder) => {
    let isVisible = true;

    if (folder.level > 0) {
      const parts = folder.path.split("/");
      let currentPath = "";
      for (let i = 0; i < parts.length - 1; i++) {
        currentPath = i === 0 ? parts[i] : `${currentPath}/${parts[i]}`;
        if (!expandedFolders[currentPath]) {
          isVisible = false;
          break;
        }
      }
    }

    return {
      ...folder,
      ...extra,
      visible: isVisible,
      expanded: !!expandedFolders[folder.path],
    };
  });
}

function normalizeCategorySearchQuery(query) {
  return String(query || "").trim().toLowerCase();
}

function filterFolderTreeByQuery(list, query) {
  const normalizedQuery = normalizeCategorySearchQuery(query);
  if (!normalizedQuery) {
    return list || [];
  }

  const folders = list || [];
  const folderMap = new Map(folders.map((folder) => [folder.path, folder]));
  const includedPaths = new Set();

  folders.forEach((folder) => {
    const folderName = normalizeCategorySearchQuery(folder.name);
    const folderPath = normalizeCategorySearchQuery(folder.path);
    if (
      !folderName.includes(normalizedQuery) &&
      !folderPath.includes(normalizedQuery)
    ) {
      return;
    }

    let currentPath = folder.path;
    while (currentPath) {
      includedPaths.add(currentPath);
      const lastSlashIndex = currentPath.lastIndexOf("/");
      if (lastSlashIndex === -1) {
        break;
      }
      currentPath = currentPath.slice(0, lastSlashIndex);
    }
  });

  return folders.filter((folder) => includedPaths.has(folder.path));
}

export default function sidebar() {
  return {
    // 本地展开状态
    expandedFolders: {},
    dragOverFolder: null,
    // 标签索引展开状态（从本地存储读取，默认展开）
    tagsSectionExpanded: (() => {
      try {
        const saved = localStorage.getItem("st_manager_tags_section_expanded");
        return saved !== null ? saved === "true" : true;
      } catch (e) {
        return true;
      }
    })(),
    tagPaneRatio: readStoredTagPaneRatio(),
    dynamicVisibleTagCount: DEFAULT_VISIBLE_TAG_COUNT,
    tagPaneResizeState: null,
    _tagPaneLayoutRaf: 0,
    _syncTagPaneLayoutHandler: null,
    _handleTagPaneResizeMove: null,
    _handleTagPaneResizeEnd: null,
    moduleMenuOpen: false,

    // 设备类型和模式
    get deviceType() {
      return this.$store.global.deviceType;
    },

    get currentMode() {
      return this.$store.global.currentMode;
    },

    get currentModeLabel() {
      return MODULE_LABELS[this.currentMode] || "管理模块";
    },

    openModuleMenu() {
      this.moduleMenuOpen = true;
      this.$nextTick(() => {
        const activeItem = this.$refs.moduleMenu?.querySelector(
          '[aria-current="page"]',
        );
        const firstItem = this.$refs.moduleMenu?.querySelector("button");
        (activeItem || firstItem)?.focus();
      });
    },

    closeModuleMenu(restoreFocus = false) {
      this.moduleMenuOpen = false;
      if (restoreFocus) {
        this.$nextTick(() => this.$refs.moduleSwitcher?.focus());
      }
    },

    handleModuleMenuKeydown(event) {
      const items = Array.from(
        this.$refs.moduleMenu?.querySelectorAll("button") || [],
      );
      if (!items.length) return;

      if (event.key === "Escape") {
        event.preventDefault();
        this.closeModuleMenu(true);
        return;
      }

      if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        (event.key === "Home" ? items[0] : items[items.length - 1])?.focus();
        return;
      }

      const offset =
        event.key === "ArrowDown"
          ? 2
          : event.key === "ArrowUp"
            ? -2
            : event.key === "ArrowRight"
              ? 1
              : event.key === "ArrowLeft"
                ? -1
                : 0;
      if (!offset) return;

      event.preventDefault();
      const currentIndex = Math.max(items.indexOf(event.target), 0);
      const nextIndex =
        (currentIndex + offset + items.length) % items.length;
      items[nextIndex]?.focus();
    },

    get shouldShowCardTagSplitter() {
      return (
        this.currentMode === "cards" &&
        this.deviceType !== "mobile" &&
        this.tagsSectionExpanded
      );
    },

    get cardTagPaneBasisStyle() {
      if (!this.shouldShowCardTagSplitter) return null;
      return `${(this.tagPaneRatio * 100).toFixed(2)}%`;
    },

    get visibleSidebar() {
      return this.$store.global.visibleSidebar;
    },

    set visibleSidebar(val) {
      this.$store.global.visibleSidebar = val;
      return true;
    },

    get filterCategory() {
      return this.$store.global.viewState.filterCategory;
    },
    set filterCategory(val) {
      this.$store.global.viewState.filterCategory = val;
      return true;
    },

    get filterTags() {
      return this.$store.global.viewState.filterTags;
    },
    set filterTags(val) {
      this.$store.global.viewState.filterTags = val;
      return true;
    },

    // === 代理拖拽状态 ===
    get draggedCards() {
      return this.$store.global.viewState.draggedCards;
    },
    get draggedFolder() {
      return this.$store.global.viewState.draggedFolder;
    },
    set draggedFolder(val) {
      this.$store.global.viewState.draggedFolder = val;
      return true;
    },

    get allTagsPool() {
      return this.$store.global.allTagsPool;
    },
    get sidebarTagsPool() {
      return this.$store.global.sidebarTagsPool;
    },
    get libraryTotal() {
      return this.$store.global.libraryTotal;
    },
    get tagSearchQuery() {
      return this.$store.global.tagSearchQuery;
    },
    get isolatedCategories() {
      return this.$store.global.isolatedCategories || [];
    },
    set showTagFilterModal(val) {
      this.$store.global.showTagFilterModal = val;
      return true;
    },

    get wiFilterType() {
      return this.$store.global.wiFilterType;
    },
    get wiFilterCategory() {
      return this.$store.global.wiFilterCategory || "";
    },
    get wiAllFolders() {
      return this.$store.global.wiAllFolders || [];
    },
    get wiCategoryCounts() {
      return this.$store.global.wiCategoryCounts || {};
    },
    get wiList() {
      return this.$store.global.wiList || [];
    },
    get presetFilterCategory() {
      return this.$store.global.presetFilterCategory || "";
    },
    get presetAllFolders() {
      return this.$store.global.presetAllFolders || [];
    },
    get presetCategoryCounts() {
      return this.$store.global.presetCategoryCounts || {};
    },

    // 选中状态 (用于清空)
    get selectedIds() {
      return this.$store.global.viewState.selectedIds;
    },
    set selectedIds(val) {
      this.$store.global.viewState.selectedIds = val;
      return true;
    },

    get tagIndexCategoryNames() {
      const groups = this.$store.global.groupTagsByTaxonomy(
        this.allTagsPool || [],
      );
      return groups.map((group) => group.category).filter(Boolean);
    },

    get tagIndexVisibleTags() {
      const activeCategory = this.$store.global.tagIndexActiveCategory || "";
      const tags = this.allTagsPool || [];
      if (!activeCategory) return tags;
      return tags.filter(
        (tag) => this.$store.global.getTagCategory(tag) === activeCategory,
      );
    },

    get tagIndexActiveCategory() {
      return this.$store.global.tagIndexActiveCategory || "";
    },

    get cardCategorySearchQuery() {
      return this.$store.global.cardCategorySearchQuery || "";
    },
    set cardCategorySearchQuery(val) {
      this.$store.global.cardCategorySearchQuery = String(val || "");
      return true;
    },

    get wiCategorySearchQuery() {
      return this.$store.global.wiCategorySearchQuery || "";
    },
    set wiCategorySearchQuery(val) {
      this.$store.global.wiCategorySearchQuery = String(val || "");
      return true;
    },

    get presetCategorySearchQuery() {
      return this.$store.global.presetCategorySearchQuery || "";
    },
    set presetCategorySearchQuery(val) {
      this.$store.global.presetCategorySearchQuery = String(val || "");
      return true;
    },

    get isCardCategorySearchActive() {
      return !!normalizeCategorySearchQuery(this.cardCategorySearchQuery);
    },

    get isCardCategorySearchEmpty() {
      return this.isCardCategorySearchActive && this.folderTree.length === 0;
    },

    get isWiCategorySearchActive() {
      return !!normalizeCategorySearchQuery(this.wiCategorySearchQuery);
    },

    get isWiCategorySearchEmpty() {
      return this.isWiCategorySearchActive && this.wiFolderTree.length === 0;
    },

    get isPresetCategorySearchActive() {
      return !!normalizeCategorySearchQuery(this.presetCategorySearchQuery);
    },

    get isPresetCategorySearchEmpty() {
      return this.isPresetCategorySearchActive && this.presetFolderTree.length === 0;
    },

    // 计算属性：构建文件夹树 (依赖全局 Store 数据)
    get folderTree() {
      const list = filterFolderTreeByQuery(
        this.$store.global.allFoldersList || [],
        this.cardCategorySearchQuery,
      );
      return buildFolderTree(list, this.expandedFolders, {
        isIsolated: false,
        isInsideIsolatedBranch: false,
        visible: this.isCardCategorySearchActive ? true : undefined,
      }).map((folder) => ({
        ...folder,
        visible: this.isCardCategorySearchActive ? true : folder.visible,
        isIsolated: this.isIsolatedFolder(folder.path),
        isInsideIsolatedBranch: this.isInsideIsolatedBranch(folder.path),
      }));
    },

    get wiFolderTree() {
      const list = filterFolderTreeByQuery(
        this.wiFolderList,
        this.wiCategorySearchQuery,
      );
      return buildFolderTree(list, this.expandedFolders, {
        visible: this.isWiCategorySearchActive ? true : undefined,
      }).map((folder) => ({
        ...folder,
        visible: this.isWiCategorySearchActive ? true : folder.visible,
      }));
    },

    get presetFolderTree() {
      const list = filterFolderTreeByQuery(
        this.presetFolderList,
        this.presetCategorySearchQuery,
      );
      return buildFolderTree(list, this.expandedFolders, {
        visible: this.isPresetCategorySearchActive ? true : undefined,
      }).map((folder) => ({
        ...folder,
        visible: this.isPresetCategorySearchActive ? true : folder.visible,
      }));
    },

    get wiFolderList() {
      return (this.wiAllFolders || []).map((p) => ({
        path: p,
        name: p.split("/").pop(),
        level: p.split("/").length - 1,
      }));
    },

    get presetFolderList() {
      return (this.presetAllFolders || []).map((p) => ({
        path: p,
        name: p.split("/").pop(),
        level: p.split("/").length - 1,
      }));
    },

    isIsolatedFolder(path) {
      const normalized = String(path || "").trim();
      if (!normalized) return false;
      return this.isolatedCategories.includes(normalized);
    },

    isInsideIsolatedBranch(path) {
      const normalized = String(path || "").trim();
      if (!normalized) return false;
      return this.isolatedCategories.some(
        (item) => normalized === item || normalized.startsWith(item + "/"),
      );
    },

    init() {
      this.handleMobileUploadRequest =
        this.handleMobileUploadRequest.bind(this);
      this._syncTagPaneLayoutHandler = this.scheduleTagPaneLayoutSync.bind(this);
      this._handleTagPaneResizeMove = this.handleTagPaneResize.bind(this);
      this._handleTagPaneResizeEnd = this.endTagPaneResize.bind(this);
      window.addEventListener(
        "request-mobile-upload",
        this.handleMobileUploadRequest,
      );
      window.addEventListener("resize", this._syncTagPaneLayoutHandler);

      // 监听标签索引展开状态变化，保存到本地存储
      this.$watch("tagsSectionExpanded", (value) => {
        try {
          localStorage.setItem(
            "st_manager_tags_section_expanded",
            value.toString(),
          );
        } catch (e) {
          console.warn("Failed to save tags section expanded state:", e);
        }

        if (!value) {
          this.endTagPaneResize();
          this.dynamicVisibleTagCount = DEFAULT_VISIBLE_TAG_COUNT;
          return;
        }

        this.$nextTick(() => this.scheduleTagPaneLayoutSync());
      });

      window.addEventListener("refresh-folder-list", () => {
        window.dispatchEvent(new CustomEvent("refresh-card-list"));
      });

      this.$watch("$store.global.currentMode", () => {
        this.endTagPaneResize();
        this.$nextTick(() => this.scheduleTagPaneLayoutSync());
      });

      this.$watch("$store.global.deviceType", () => {
        this.endTagPaneResize();
        this.$nextTick(() => this.scheduleTagPaneLayoutSync());
      });

      this.$watch("$store.global.tagIndexActiveCategory", () => {
        this.$nextTick(() => this.scheduleTagPaneLayoutSync());
      });

      this.$watch("$store.global.allTagsPool", () => {
        this.$nextTick(() => this.scheduleTagPaneLayoutSync());
      });

      // === 监听当前分类变化，自动展开目录树并滚动 ===
      this.$watch("$store.global.viewState.filterCategory", (newPath) => {
        if (!newPath) return;

        // 1. 自动展开父级目录
        const parts = newPath.split("/");
        // 如果路径是 A/B/C，我们需要确保 A 和 A/B 都是展开状态
        let currentPath = "";
        for (let i = 0; i < parts.length - 1; i++) {
          currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
          this.expandedFolders[currentPath] = true;
        }
        // 强制更新对象以触发 Alpine 响应式
        this.expandedFolders = { ...this.expandedFolders };

        // 2. 滚动到对应的文件夹条目
        // 使用 $nextTick 确保 DOM 已经根据 expandedFolders 更新完毕
        this.$nextTick(() => {
          // 查找侧边栏中所有 active 的元素，取最后一个（通常是当前选中的最深层级）
          const activeElements = document.querySelectorAll(
            ".sidebar .folder-item.active",
          );
          if (activeElements.length > 0) {
            const targetEl = activeElements[activeElements.length - 1];

            // 使用 scrollIntoView 将其滚动到顶部，更符合目录定位习惯
            targetEl.scrollIntoView({
              behavior: "smooth",
              block: "start",
              inline: "nearest",
            });
          }
        });
      });

      this.$watch("$store.global.wiAllFolders", (folders) => {
        if (this.currentMode !== "worldinfo") return;
        if (!this.wiFilterCategory) return;
        if (
          !Array.isArray(folders) ||
          !folders.includes(this.wiFilterCategory)
        ) {
          this.$store.global.wiFilterCategory = "";
        }
      });

      this.$watch("$store.global.presetAllFolders", (folders) => {
        if (this.currentMode !== "presets") return;
        if (!this.presetFilterCategory) return;
        if (
          !Array.isArray(folders) ||
          !folders.includes(this.presetFilterCategory)
        ) {
          this.$store.global.presetFilterCategory = "";
        }
      });
      // 初始化sidebar显示状态
      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
      }

      this.$nextTick(() => this.scheduleTagPaneLayoutSync());
    },

    destroy() {
      window.removeEventListener(
        "request-mobile-upload",
        this.handleMobileUploadRequest,
      );
      window.removeEventListener("resize", this._syncTagPaneLayoutHandler);
      window.removeEventListener("pointermove", this._handleTagPaneResizeMove);
      window.removeEventListener("pointerup", this._handleTagPaneResizeEnd);
      window.removeEventListener("pointercancel", this._handleTagPaneResizeEnd);
      if (this._tagPaneLayoutRaf) {
        cancelAnimationFrame(this._tagPaneLayoutRaf);
      }
    },

    // 切换侧边栏可见性
    toggleSidebarVisible() {
      this.$store.global.visibleSidebar = !this.$store.global.visibleSidebar;
      // 移动端打开侧边栏时，阻止 body 滚动
      if (this.$store.global.deviceType === "mobile") {
        if (this.$store.global.visibleSidebar) {
          document.body.style.overflow = "hidden";
        } else {
          document.body.style.overflow = "";
        }
      }
    },

    openTagFilter() {
      window.dispatchEvent(new CustomEvent("open-tag-filter-modal"));
    },

    // 切换文件夹展开/收起
    toggleFolder(path) {
      this.expandedFolders[path] = !this.expandedFolders[path];
      // 强制更新 (Alpine sometimes needs help with deep object mutation reactivity)
      this.expandedFolders = { ...this.expandedFolders };
    },

    clearCategorySearch(mode = this.currentMode) {
      if (mode === "worldinfo") {
        this.wiCategorySearchQuery = "";
        return;
      }
      if (mode === "presets") {
        this.presetCategorySearchQuery = "";
        return;
      }
      this.cardCategorySearchQuery = "";
    },

    // 设置当前分类
    setCategory(category) {
      // 更新父级 layout 的状态
      this.filterCategory = category;
      this.selectedIds = []; // 清空选中

      // 触发 Grid 刷新
      window.dispatchEvent(new CustomEvent("reset-scroll"));
    },

    // 获取分类计数 (从 Store 读取)
    getCategoryCount(category) {
      const counts = this.$store.global.categoryCounts || {};
      if (category === "" || category === "根目录") {
        return counts[""] || 0;
      }
      return counts[category] || 0;
    },

    getWiCategoryCount(category) {
      const counts = this.wiCategoryCounts || {};
      if (category === "" || category === "根目录") {
        return counts[""] || 0;
      }
      return counts[category] || 0;
    },

    getPresetCategoryCount(category) {
      const counts = this.presetCategoryCounts || {};
      if (category === "" || category === "根目录") {
        return counts[""] || 0;
      }
      return counts[category] || 0;
    },

    getFolderCapabilities(path, mode = this.currentMode) {
      if (mode === "worldinfo") {
        return (
          (this.$store.global.wiFolderCapabilities || {})[path || ""] || {}
        );
      }
      if (mode === "presets") {
        return (
          (this.$store.global.presetFolderCapabilities || {})[path || ""] || {}
        );
      }
      return {};
    },

    // === 右键菜单 ===
    showFolderContextMenu(e, folder) {
      e.preventDefault();
      e.stopPropagation();
      // 触发全局右键菜单事件 (ContextMenu 组件会监听)
      window.dispatchEvent(
        new CustomEvent("show-context-menu", {
          detail: {
            x: e.clientX,
            y: e.clientY,
            type: "folder",
            target: folder.path,
            targetFolder: folder,
          },
        }),
      );
    },

    // 移动端：从三个点按钮触发右键菜单
    showFolderContextMenuFromButton(e, folder) {
      e.preventDefault();
      e.stopPropagation();

      // 获取按钮的位置
      const buttonRect = e.target.closest("button").getBoundingClientRect();

      // 创建模拟事件对象，使用按钮右下角位置（稍微偏移，避免遮挡按钮）
      const mockEvent = {
        clientX: buttonRect.right - 10,
        clientY: buttonRect.bottom + 5,
        preventDefault: () => {},
        stopPropagation: () => {},
      };

      // 调用原有的右键菜单方法
      this.showFolderContextMenu(mockEvent, folder);
    },

    hideContextMenu() {
      window.dispatchEvent(new CustomEvent("hide-context-menu"));
    },

    // === 文件夹 CRUD (通常由模态框回调触发，这里提供逻辑) ===
    // 注意：HTML 中通常调用 $store.global.showCreateFolder = true

    createFolder() {
      // 这个函数绑定在模态框的确认按钮上
      const name = this.$store.global.newFolderName;
      const parent = this.$store.global.newFolderParent;

      createFolder({ name, parent }).then((res) => {
        if (res.success) {
          // 刷新文件夹列表
          window.dispatchEvent(new CustomEvent("refresh-folder-list"));
          this.$store.global.showCreateFolder = false;
          this.$store.global.newFolderName = "";
        } else {
          alert(res.msg);
        }
      });
    },

    // === 拖拽逻辑 (Folder Drag) ===

    folderDragStart(e, folder) {
      // 更新 layout 中的拖拽状态
      this.draggedFolder = folder.path;

      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-st-folder", folder.path);

      const el = e.currentTarget;

      // 样式
      el.classList.add("drag-source");

      const handleDragEnd = () => {
        window.dispatchEvent(new CustomEvent("global-drag-end"));
        el.classList.remove("drag-source");
        el.removeEventListener("dragend", handleDragEnd);
      };
      el.addEventListener("dragend", handleDragEnd);
    },

    folderDragOver(e, folder) {
      e.preventDefault();
      e.stopPropagation();

      if (folder?.mode === "worldinfo") {
        if (!this.canMoveWorldInfoSelection()) return;
        this.dragOverFolder = folder.path;
        return;
      }

      if (folder?.mode === "presets") {
        if (!this.canMovePresetSelection()) return;
        this.dragOverFolder = folder.path;
        return;
      }

      // 如果正在拖拽卡片，则高亮当前文件夹 (除非是当前所在目录)
      if (this.draggedCards.length > 0) {
        if (folder.path !== this.filterCategory) {
          this.dragOverFolder = folder.path; // 设置 layout 状态
        }
        return;
      }

      // 文件夹拖拽检查：不能拖到自己或子目录
      if (this.draggedFolder) {
        if (
          folder.path === this.draggedFolder ||
          folder.path.startsWith(this.draggedFolder + "/") ||
          this.draggedFolder.startsWith(folder.path + "/")
        ) {
          return;
        }
        this.dragOverFolder = folder.path;
      }
    },

    folderDragLeave(e, folder) {
      const relatedTarget = e.relatedTarget;
      if (!relatedTarget || !relatedTarget.closest(".folder-item")) {
        this.dragOverFolder = null;
      }
    },

    presetRootDragOver(e) {
      this.folderDragOver(e, { path: "", name: "根目录", mode: "presets" });
      if (this.draggedCards.length > 0) {
        this.dragOverFolder = "根目录";
      }
    },

    presetRootDragLeave(e) {
      this.folderDragLeave(e, { path: "", name: "根目录", mode: "presets" });
    },

    presetRootDrop(e) {
      this.folderDrop(e, { path: "", name: "根目录", mode: "presets" });
    },

    folderDrop(e, targetFolder) {
      e.preventDefault();
      e.stopPropagation();

      // 清理视觉
      document
        .querySelectorAll(".drag-source")
        .forEach((el) => el.classList.remove("drag-source"));
      this.dragOverCat = null;
      this.dragOverMain = false;
      this.dragOverFolder = null;

      // 1. 世界书 -> 分类
      if (targetFolder?.mode === "worldinfo" && this.draggedCards.length > 0) {
        if (!this.canMoveWorldInfoSelection()) {
          window.dispatchEvent(new CustomEvent("global-drag-end"));
          return;
        }

        const items = this.selectedWorldInfoItems();
        const count = items.length;
        moveWorldInfoItems(items, targetFolder.path)
          .then(() => {
            this.$store.global.viewState.selectedIds = [];
            window.dispatchEvent(
              new CustomEvent("refresh-wi-list", {
                detail: { resetPage: false },
              }),
            );
            this.$store.global.showToast(`✅ 已移动 ${count} 本世界书`);
          })
          .catch((err) => alert(err.message || err));

        window.dispatchEvent(new CustomEvent("global-drag-end"));
        return;
      }

      if (targetFolder?.mode === "presets" && this.draggedCards.length > 0) {
        if (!this.canMovePresetSelection()) {
          alert("当前选中的预设包含资源绑定项，不能移动分类");
          window.dispatchEvent(new CustomEvent("global-drag-end"));
          return;
        }

        const items = this.selectedPresetItems();
        const count = items.length;
        movePresetItems(items, targetFolder.path)
          .then(() => {
            this.$store.global.viewState.selectedIds = [];
            window.dispatchEvent(
              new CustomEvent("refresh-preset-list", {
                detail: { resetPage: false },
              }),
            );
            this.$store.global.showToast(`已移动 ${count} 个预设`, 3000, "card-check");
          })
          .catch((err) => alert(err.message || err));

        window.dispatchEvent(new CustomEvent("global-drag-end"));
        return;
      }

      // 2. 文件夹 -> 文件夹
      if (this.draggedFolder && targetFolder) {
        if (this.draggedFolder === targetFolder.path) return;
        const sourceName = this.draggedFolder.split("/").pop();
        if (
          confirm(`移动文件夹 "${sourceName}" 到 "${targetFolder.name}" 下?`)
        ) {
          moveFolder({
            source_path: this.draggedFolder,
            target_parent_path: targetFolder.path,
            merge_if_exists: false,
          }).then((res) => {
            if (res.success)
              window.dispatchEvent(new CustomEvent("refresh-folder-list"));
            else alert(res.msg);
          });
        }
      }
      // 3. 卡片 -> 文件夹
      else if (this.draggedCards.length > 0 && targetFolder) {
        const targetName = targetFolder.name;
        const count = this.draggedCards.length;

        if (confirm(`移动 ${count} 张卡片到 "${targetName}"?`)) {
          moveCard({
            card_ids: this.draggedCards,
            target_category: targetFolder.path,
          }).then((res) => {
            if (res.success) {
              // 更新计数
              if (res.category_counts)
                this.$store.global.categoryCounts = res.category_counts;
              // 清空选中
              this.$store.global.viewState.selectedIds = [];
              // 刷新列表
              window.dispatchEvent(new CustomEvent("refresh-card-list"));
              // 显示提示
              this.$store.global.showToast(`✅ 已移动 ${count} 张卡片`);
            } else alert(res.msg);
          });
        }
      }
      // 4. 外部文件 -> 文件夹
      else if (e.dataTransfer.files.length > 0 && targetFolder) {
        window.dispatchEvent(
          new CustomEvent("handle-files-drop", {
            detail: { event: e, category: targetFolder.path },
          }),
        );
      }

      // 触发全局清理
      window.dispatchEvent(new CustomEvent("global-drag-end"));
    },

    persistTagPaneRatio() {
      try {
        localStorage.setItem(TAG_PANE_RATIO_STORAGE_KEY, String(this.tagPaneRatio));
      } catch (e) {
        console.warn("Failed to save card tag pane ratio:", e);
      }
    },

    normalizeTagPaneHeight(totalHeight, requestedHeight) {
      const maxHeight = getMaxTagPaneHeight(totalHeight);
      const minHeight = Math.min(MIN_CARD_TAG_PANE_HEIGHT, maxHeight);
      return clamp(requestedHeight, minHeight, maxHeight);
    },

    scheduleTagPaneLayoutSync() {
      if (this._tagPaneLayoutRaf) {
        cancelAnimationFrame(this._tagPaneLayoutRaf);
      }
      this._tagPaneLayoutRaf = requestAnimationFrame(() => {
        this._tagPaneLayoutRaf = 0;
        this.syncTagPaneLayout();
      });
    },

    syncTagPaneLayout() {
      if (!this.shouldShowCardTagSplitter) {
        this.dynamicVisibleTagCount = DEFAULT_VISIBLE_TAG_COUNT;
        return;
      }

      const shell = this.$refs.cardSidebarShell;
      const tagsPane = this.$refs.cardTagsPane;
      if (!shell || !tagsPane) {
        this.dynamicVisibleTagCount = DEFAULT_VISIBLE_TAG_COUNT;
        return;
      }

      const totalHeight = shell.getBoundingClientRect().height;
      if (!Number.isFinite(totalHeight) || totalHeight <= 0) {
        this.dynamicVisibleTagCount = DEFAULT_VISIBLE_TAG_COUNT;
        return;
      }

      const normalizedHeight = this.normalizeTagPaneHeight(
        totalHeight,
        totalHeight * this.tagPaneRatio,
      );
      this.tagPaneRatio = normalizedHeight / totalHeight;
      this.dynamicVisibleTagCount = this.computeDynamicVisibleTagCount();
    },

    computeDynamicVisibleTagCount() {
      const tagsPane = this.$refs.cardTagsPane;
      const tagsHeader = this.$refs.cardTagsHeader;
      const categoryStrip = this.$refs.cardTagCategoryStrip;
      const tagCloud = this.$refs.cardTagCloud;
      if (!tagsPane || !tagCloud) return DEFAULT_VISIBLE_TAG_COUNT;

      const tagCloudWidth = tagCloud.clientWidth || 0;
      const tagsPaneHeight = tagsPane.getBoundingClientRect().height || 0;
      if (!tagCloudWidth || !tagsPaneHeight) return DEFAULT_VISIBLE_TAG_COUNT;

      const headerHeight = tagsHeader
        ? tagsHeader.getBoundingClientRect().height
        : 0;
      const categoryHeight = categoryStrip
        ? categoryStrip.getBoundingClientRect().height
        : 0;
      const availableTagHeight = Math.max(
        ESTIMATED_TAG_ROW_HEIGHT,
        tagsPaneHeight - headerHeight - categoryHeight - 16,
      );
      const chipsPerRow = Math.max(
        1,
        Math.floor((tagCloudWidth + 6) / ESTIMATED_TAG_CHIP_WIDTH),
      );
      const visibleRows = Math.max(
        1,
        Math.floor((availableTagHeight + 6) / ESTIMATED_TAG_ROW_HEIGHT),
      );
      return visibleRows * chipsPerRow;
    },

    beginTagPaneResize(event) {
      if (!this.shouldShowCardTagSplitter) return;

      const shell = this.$refs.cardSidebarShell;
      const tagsPane = this.$refs.cardTagsPane;
      if (!shell || !tagsPane) return;

      const totalHeight = shell.getBoundingClientRect().height;
      const startHeight = tagsPane.getBoundingClientRect().height;
      if (!Number.isFinite(totalHeight) || !Number.isFinite(startHeight)) return;

      this.tagPaneResizeState = {
        startY: event.clientY,
        startHeight,
        totalHeight,
      };
      shell.classList.add("is-resizing");
      window.addEventListener("pointermove", this._handleTagPaneResizeMove);
      window.addEventListener("pointerup", this._handleTagPaneResizeEnd);
      window.addEventListener("pointercancel", this._handleTagPaneResizeEnd);
    },

    handleTagPaneResize(event) {
      if (!this.tagPaneResizeState) return;

      const deltaY = event.clientY - this.tagPaneResizeState.startY;
      const nextHeight = this.tagPaneResizeState.startHeight - deltaY;
      const normalizedHeight = this.normalizeTagPaneHeight(
        this.tagPaneResizeState.totalHeight,
        nextHeight,
      );
      this.tagPaneRatio = normalizedHeight / this.tagPaneResizeState.totalHeight;
      this.$nextTick(() => this.scheduleTagPaneLayoutSync());
    },

    endTagPaneResize() {
      if (this.$refs.cardSidebarShell) {
        this.$refs.cardSidebarShell.classList.remove("is-resizing");
      }
      window.removeEventListener("pointermove", this._handleTagPaneResizeMove);
      window.removeEventListener("pointerup", this._handleTagPaneResizeEnd);
      window.removeEventListener("pointercancel", this._handleTagPaneResizeEnd);

      if (!this.tagPaneResizeState) return;

      this.tagPaneResizeState = null;
      this.persistTagPaneRatio();
      this.$nextTick(() => this.scheduleTagPaneLayoutSync());
    },

    // === 标签云 ===

    toggleFilterTag(tag, event = null) {
      this.$store.global.toggleFilterTag(tag, {
        forceExclude: !!(event && event.shiftKey),
      });
    },

    setTagIndexCategory(category) {
      this.$store.global.tagIndexActiveCategory = String(category || "").trim();
    },

    // === 世界书侧边栏逻辑 ===

    setWiFilter(type) {
      this.$store.global.wiFilterType = type;
    },

    setWiCategory(category) {
      this.$store.global.wiFilterCategory = category;
      window.dispatchEvent(
        new CustomEvent("refresh-wi-list", { detail: { resetPage: true } }),
      );
    },

    selectedWorldInfoItems() {
      return this.selectedIds
        .map((id) => this.wiList.find((item) => item.id === id))
        .filter(Boolean);
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
        .map((id) =>
          (this.$store.global.presetList || []).find((item) => item.id === id),
        )
        .filter(Boolean);
    },

    canMovePresetSelection() {
      const items = this.selectedPresetItems();
      return (
        items.length > 0 &&
        items.every((item) => (item.source_type || item.type) === "global")
      );
    },

    setPresetCategory(category) {
      this.$store.global.presetFilterCategory = category;
      window.dispatchEvent(
        new CustomEvent("refresh-preset-list", { detail: { resetPage: true } }),
      );
    },

    createWorldInfoBook() {
      window.dispatchEvent(new CustomEvent("create-worldinfo"));
    },

    migrateLorebooks() {
      if (
        !confirm(
          "这将扫描所有角色资源目录，并将散乱的 JSON 世界书移动到 'lorebooks' 子文件夹中。\n是否继续？",
        )
      )
        return;

      migrateLorebooks().then((res) => {
        alert(`整理完成，共移动了 ${res.count} 个文件。`);
        window.dispatchEvent(new CustomEvent("refresh-wi-list"));
      });
    },

    handleMobileUploadRequest() {
      if (
        this.deviceType !== "mobile" ||
        !this.$refs.mobileImportInput ||
        this.currentMode === "chats"
      ) {
        return;
      }

      this.$refs.mobileImportInput.click();
    },

    /**
     * 移动端悬浮导入按钮：文件选择完成回调
     * - 在角色卡模式下：复用 cardGrid 的拖拽上传逻辑 (window.stUploadCardFiles)
     * - 在世界书模式下：复用 wiGrid 的拖拽上传逻辑 (window.stUploadWorldInfoFiles)
     * - 在预设/正则脚本/ST脚本/快速回复模式下：复用对应 grid 的拖拽上传逻辑
     */
    handleMobileImportChange(e) {
      const input = e.target;
      const files = input.files;

      if (!files || files.length === 0) {
        input.value = "";
        return;
      }

      const mode = this.currentMode; // 'cards' | 'worldinfo' | 'chats' | 'presets' | 'regex' | 'scripts' | 'quick_replies' | 'beautify'

      // === 1. 角色卡上传 ===
      if (mode === "cards") {
        if (window.stUploadCardFiles) {
          // 直接复用 cardGrid 的内部上传逻辑（带有批量导入弹窗等）
          window.stUploadCardFiles(files, null);
        } else {
          alert("卡片网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 2. 世界书上传 ===
      if (mode === "worldinfo") {
        if (window.stUploadWorldInfoFiles) {
          // 直接复用 wiGrid 的内部上传逻辑（与拖拽上传完全一致）
          window.stUploadWorldInfoFiles(files);
        } else {
          alert("世界书网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 3. 聊天记录上传 ===
      if (mode === "chats") {
        if (window.stUploadChatFiles) {
          window.stUploadChatFiles(files, {});
        } else {
          alert("聊天网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 4. 预设上传 ===
      if (mode === "presets") {
        if (window.stUploadPresetFiles) {
          window.stUploadPresetFiles(files);
        } else {
          alert("预设网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 5. 正则脚本上传 ===
      if (mode === "regex") {
        if (window.stUploadRegexFiles) {
          window.stUploadRegexFiles(files);
        } else {
          alert("正则脚本网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 6. ST脚本上传 ===
      if (mode === "scripts") {
        if (window.stUploadScriptFiles) {
          window.stUploadScriptFiles(files);
        } else {
          alert("ST脚本网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      // === 7. 快速回复上传 ===
      if (mode === "quick_replies") {
        if (window.stUploadQuickReplyFiles) {
          window.stUploadQuickReplyFiles(files);
        } else {
          alert("快速回复网格尚未准备好，稍后再试一次。");
        }

        input.value = "";
        return;
      }

      if (mode === "beautify") {
        if (window.stUploadBeautifyThemeFiles) {
          window.stUploadBeautifyThemeFiles(files);
        } else {
          alert("美化视图尚未准备好，稍后再试一次。");
        }

        window.dispatchEvent(new CustomEvent("refresh-beautify-list"));
        input.value = "";
        return;
      }

      // 其他模式兜底
      alert("当前模式不支持导入操作。");
      input.value = "";
    },
  };
}
