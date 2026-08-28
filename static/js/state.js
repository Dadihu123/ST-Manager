/**
 * static/js/state.js
 * 全局状态管理 (Alpine.store)
 */

import {
  getServerStatus,
  getSettings,
  saveSettings,
  performSystemAction,
  triggerScan,
} from "./api/system.js";

import { updateCssVariable, applyFont } from "./utils/dom.js";

import {
  getIsolatedCategories,
  saveIsolatedCategories as saveIsolatedCategoriesRequest,
} from "./api/card.js";

// 主题预设常量
const THEME_PRESETS = {
  blue: {
    main: "#2563eb",
    hover: "#1d4ed8",
    light: "#60a5fa",
    faint: "rgba(37, 99, 235, 0.3)",
    rgb: "37, 99, 235",
  },
  purple: {
    main: "#7c3aed",
    hover: "#6d28d9",
    light: "#a78bfa",
    faint: "rgba(124, 58, 237, 0.3)",
    rgb: "124, 58, 237",
  },
  green: {
    main: "#059669",
    hover: "#047857",
    light: "#34d399",
    faint: "rgba(5, 150, 105, 0.3)",
    rgb: "5, 150, 105",
  },
  red: {
    main: "#dc2626",
    hover: "#b91c1c",
    light: "#f87171",
    faint: "rgba(220, 38, 38, 0.3)",
    rgb: "220, 38, 38",
  },
  orange: {
    main: "#ea580c",
    hover: "#c2410c",
    light: "#fb923c",
    faint: "rgba(234, 88, 12, 0.3)",
    rgb: "234, 88, 12",
  },
  pink: {
    main: "#db2777",
    hover: "#be185d",
    light: "#f472b6",
    faint: "rgba(219, 39, 119, 0.3)",
    rgb: "219, 39, 119",
  },
};

const DEFAULT_TAG_CATEGORY = "未分类";
const DEFAULT_TAG_CATEGORY_COLOR = "#64748b";
const DEFAULT_TAG_CATEGORY_OPACITY = 16;
const TAG_VIEW_PREFS_STORAGE_KEY = "st_manager_tag_view_prefs";
const TOAST_ICON_NAMES = new Set([
  "automation-forbidden",
  "card-send",
  "context-close",
  "context-delete",
  "card-check",
  "settings-save",
]);

function buildDefaultTagViewPrefs() {
  return {
    rememberLastTagView: false,
    mixedCategoryView: true,
    categoryFilterInclude: [],
    categoryFilterExclude: [],
    lastCategorySortName: "",
  };
}

export function splitTagTokens(rawValue, options = {}) {
  const source = String(rawValue || "");
  if (!source.trim()) return [];

  const slashIsSeparator = !!options.slashIsSeparator;
  const splitPattern = slashIsSeparator ? /[|/,，\n]+/ : /[|,，\n]+/;
  const seen = new Set();
  const tokens = [];

  source.split(splitPattern).forEach((part) => {
    const token = String(part || "").trim();
    if (!token || seen.has(token)) return;
    seen.add(token);
    tokens.push(token);
  });

  return tokens;
}

export function matchAnyTagSearchToken(haystack, query, options = {}) {
  const value = String(haystack || "")
    .trim()
    .toLowerCase();
  if (!value) return false;

  const tokens = splitTagTokens(query, options).map((token) =>
    token.toLowerCase(),
  );
  if (!tokens.length)
    return value.includes(
      String(query || "")
        .trim()
        .toLowerCase(),
    );

  return tokens.some((token) => value.includes(token));
}

function buildDefaultTagTaxonomy() {
  return {
    default_category: DEFAULT_TAG_CATEGORY,
    category_order: [DEFAULT_TAG_CATEGORY],
    categories: {
      [DEFAULT_TAG_CATEGORY]: {
        color: DEFAULT_TAG_CATEGORY_COLOR,
        opacity: DEFAULT_TAG_CATEGORY_OPACITY,
      },
    },
    tag_to_category: {},
    updated_at: 0,
  };
}

function normalizeHexColor(value, fallback = DEFAULT_TAG_CATEGORY_COLOR) {
  const fallbackColor =
    typeof fallback === "string" && fallback
      ? fallback
      : DEFAULT_TAG_CATEGORY_COLOR;
  if (typeof value !== "string") return fallbackColor;

  let color = value.trim();
  if (!color) return fallbackColor;

  if (!color.startsWith("#")) {
    color = `#${color}`;
  }

  const hex = color.slice(1);
  if (/^[0-9a-fA-F]{3}$/.test(hex)) {
    return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`.toLowerCase();
  }

  if (/^[0-9a-fA-F]{6}$/.test(hex)) {
    return color.toLowerCase();
  }

  return fallbackColor;
}

function normalizeOpacity(value, fallback = DEFAULT_TAG_CATEGORY_OPACITY) {
  const fallbackNum = Number.isFinite(Number(fallback))
    ? Math.max(0, Math.min(100, Math.round(Number(fallback))))
    : DEFAULT_TAG_CATEGORY_OPACITY;

  const raw = Number(value);
  if (!Number.isFinite(raw)) return fallbackNum;

  return Math.max(0, Math.min(100, Math.round(raw)));
}

function buildDefaultCardAdvancedFilterFields() {
  return {
    importDateFrom: "",
    importDateTo: "",
    modifiedDateFrom: "",
    modifiedDateTo: "",
    tokenMin: "",
    tokenMax: "",
  };
}

const CARD_ADVANCED_FILTER_SECTIONS = ["basic", "time", "numeric", "tags"];

function normalizeCardAdvancedFilterSection(value = "") {
  const section = String(value || "").trim();
  return CARD_ADVANCED_FILTER_SECTIONS.includes(section) ? section : "basic";
}

function buildDefaultCardAdvancedFilterValidationState() {
  return {
    section: "",
    field: "",
    message: "",
  };
}

function buildCardAdvancedFilterDraftFromViewState(
  viewState,
  currentSort,
  defaultSort,
) {
  const resolvedDefaultSort = toSummaryLabel(defaultSort) || "date_desc";
  const resolvedSort = toSummaryLabel(currentSort) || resolvedDefaultSort;
  const advancedFields = buildDefaultCardAdvancedFilterFields();
  return {
    favFilter: viewState.favFilter || "none",
    searchScope: viewState.searchScope || "current",
    recursiveFilter: viewState.recursiveFilter !== false,
    sort: resolvedSort,
    ...advancedFields,
    importDateFrom: toSummaryLabel(viewState.importDateFrom),
    importDateTo: toSummaryLabel(viewState.importDateTo),
    modifiedDateFrom: toSummaryLabel(viewState.modifiedDateFrom),
    modifiedDateTo: toSummaryLabel(viewState.modifiedDateTo),
    tokenMin: toSummaryLabel(viewState.tokenMin),
    tokenMax: toSummaryLabel(viewState.tokenMax),
  };
}

function isInvalidDateRange(fromValue, toValue) {
  const from = toSummaryLabel(fromValue);
  const to = toSummaryLabel(toValue);
  if (!from || !to) return false;
  return from > to;
}

function toSummaryLabel(value) {
  return String(value || "").trim();
}

export function initState() {
  Alpine.store("global", {
    // === 状态属性 ===
    isLoading: false,
    isSaving: false,
    showSettingsModal: false,

    // 设备类型: 'desktop' | 'mobile'
    deviceType: "desktop",

    // 模式: 'cards' | 'worldinfo' | 'chats'
    currentMode: "cards",

    // 侧边栏显示状态（移动端使用）
    visibleSidebar: true,

    // 服务器状态
    serverStatus: {
      status: "initializing",
      message: "",
      progress: 0,
      total: 0,
    },
    _bootstrapped: false,

    // 界面状态
    isDarkMode: true,
    windowWidth: window.innerWidth,
    toastMessage: "",
    toastIcon: "",
    showToastState: false,
    toastTimer: null,
    batchProgress: {
      visible: false,
      status: "idle",
      title: "",
      current: 0,
      total: 0,
      currentCardId: "",
      message: "",
      result: null,
      cancelRequested: false,
    },
    indexStatusPollTimer: null,
    _resizeTimer: null,
    _visualViewportResizeHandler: null,

    // 数据池 (供 Sidebar 和 Grid 共享)
    allTagsPool: [],
    sidebarTagsPool: [],
    globalTagsPool: [],
    sidebarTagGroups: [],
    globalTagGroups: [],
    tagTaxonomy: buildDefaultTagTaxonomy(),
    tagViewPrefs: buildDefaultTagViewPrefs(),
    isolatedCategories: [],
    categoryCounts: {},
    libraryTotal: 0,
    allFoldersList: [],
    showTagFilterModal: false,
    showCardAdvancedFilterDrawer: false,
    cardAdvancedFilterDraft: null,
    cardAdvancedFilterActiveSection: "basic",
    cardAdvancedFilterValidationState:
      buildDefaultCardAdvancedFilterValidationState(),
    cardAdvancedFilterTagEditSource: "",

    // 分页配置
    itemsPerPage: 20,

    // 卡片侧边栏分类搜索
    cardCategorySearchQuery: "",

    // 当前会话排序（仅影响当前列表，不写入配置）
    currentSort: "date_desc",

    // 世界书共享状态
    wiList: [], // 世界书列表数据
    wiSearchQuery: "", // 搜索关键词
    cardSearchMode: "fast",
    wiSearchMode: "fast",
    indexStatus: {
      state: "empty",
      scope: "cards",
      progress: 0,
      message: "",
      pending_jobs: 0,
    },
    wiFilterType: "all", // 筛选类型: 'all', 'global', 'resource', 'embedded'
    wiFilterCategory: "",
    wiCategorySearchQuery: "",
    wiAllFolders: [],
    wiCategoryCounts: {},
    wiFolderCapabilities: {},
    wiCurrentPage: 1,
    wiTotalItems: 0,
    wiTotalPages: 1,

    // 聊天记录共享状态
    chatList: [],
    chatSearchQuery: "",
    chatFilterType: "all", // all | bound | unbound
    chatFavFilter: "none", // 'none' | 'included' | 'excluded'
    chatCurrentPage: 1,
    chatTotalItems: 0,
    chatTotalPages: 1,

    extensionFilterType: "all", // 'all', 'global', 'resource'

    // 美化库状态
    beautifyList: [],
    beautifySearch: "",
    beautifyPlatformFilter: "all",
    beautifyWorkspace: "packages",
    beautifySelectedPackageId: "",
    beautifySelectedVariantId: "",
    beautifySelectedWallpaperId: "",
    beautifySelectedScreenshotId: "",
    beautifyStageMode: "preview",
    beautifyPreviewDevice: "pc",
    beautifyVariantSelectionByDevice: {},
    beautifyPreviewUnavailableReason: "",
    beautifyMobileFullscreenOpen: false,
    beautifyPreviewResetToken: 0,
    beautifyPackageDetailCollapsed: false,
    beautifyPackageDetailDrawerOpen: false,
    beautifyGlobalSettings: null,
    beautifyActiveDetail: null,
    beautifyActiveVariant: null,
    beautifyActiveWallpaper: null,
    sharedWallpapers: [],

    // 预设筛选状态
    presetFilterType: "all", // 'all', 'global', 'resource'
    presetFilterCategory: "",
    presetCategorySearchQuery: "",
    presetAllFolders: [],
    presetCategoryCounts: {},
    presetFolderCapabilities: {},
    presetSearch: "",
    extensionSearch: "",

    availableRuleSets: [], // 规则集列表

    // 设置表单
    settingsForm: {
      cards_dir: "data/library/characters",
      chats_dir: "data/library/chats",
      presets_dir: "data/library/presets",
      st_openai_preset_dir: "",
      quick_replies_dir: "data/library/extensions/quick-replies",
      beautify_dir: "data/library/beautify",
      default_sort: "date_desc",
      show_header_sort: true,
      st_url: "http://127.0.0.1:8000",
      st_data_dir: "",
      st_username: "",
      st_password: "",
      st_basic_username: "",
      st_basic_password: "",
      st_web_username: "",
      st_web_password: "",
      st_auth_type: "basic",
      st_proxy: "",
      host: "127.0.0.1",
      port: 5000,
      items_per_page: 0,
      items_per_page_wi: 0,
      theme_accent: "blue",
      auto_save_enabled: false,
      auto_save_interval: 3,
      dark_mode: true,
      font_style: "sans",
      card_width: 220,
      manager_wallpaper_id: "",
      bg_url: "",
      bg_opacity: 0.95,
      bg_blur: 0,
      favorites_first: false,
      png_deterministic_sort: false,
      cards_list_use_index: false,
      fast_search_use_index: false,
      worldinfo_list_use_index: false,
      allowed_abs_resource_roots: [],
      wi_preview_limit: 300,
      wi_preview_entry_max_chars: 2000,
      wi_entry_history_limit: 7,
      auth_username: "",
      auth_password: "",
      auth_trusted_ips: [],
      auth_max_attempts: 5,
      auth_fail_window_seconds: 600,
      auth_lockout_seconds: 900,
      auth_hard_lock_threshold: 50,
      auto_rename_on_import: true,

      // Discord 论坛标签抓取配置
      discord_auth_type: "token",
      discord_bot_token: "",
      discord_user_cookie: "",
      // 类脑搜索站帖子预览 Cookie
      shimmerday_forum_cookie: "",
      // 更新角色卡时默认同步 Discord 来源贴标题
      sync_source_title_on_update: true,

      // 自动化标签分隔规则
      automation_slash_is_tag_separator: false,
    },

    // === 集中管理的视图状态 ===
    viewState: {
      searchQuery: "",
      searchType: "mix",
      searchScope: "current", // 'current' | 'all_dirs' | 'full'
      filterCategory: "",
      filterTags: [],
      excludedTags: [],
      recursiveFilter: true,
      selectedIds: [],
      lastSelectedId: null,
      tagSearchQuery: "",
      draggedCards: [], // 当前正在拖拽的卡片 ID 列表
      draggedFolder: null, // 当前正在拖拽的文件夹路径
      favFilter: "none", // 'none' | 'included' | 'excluded'
      importDateFrom: "",
      importDateTo: "",
      modifiedDateFrom: "",
      modifiedDateTo: "",
      tokenMin: "",
      tokenMax: "",
    },

    // === 文件夹模态框状态 ===
    folderModals: {
      // 重命名模态框
      rename: {
        visible: false,
        path: "",
        name: "",
      },
      // 新建子文件夹模态框
      createSub: {
        visible: false,
        parentPath: "",
        name: "",
      },
      // 新建根/一级文件夹模态框 (兼容 Sidebar 逻辑)
      createRoot: {
        visible: false,
        parent: "",
        name: "",
      },
    },

    // === 初始化逻辑 ===
    init() {
      this.checkServerStatus();
      this.loadUserPreferences();
      this.loadTagViewPrefs();
      this.syncViewportHeight();

      if (!this._visualViewportResizeHandler) {
        this._visualViewportResizeHandler = () => this.syncViewportHeight();
      }

      // 监听窗口大小变化
      window.addEventListener("resize", () => {
        this.windowWidth = window.innerWidth;
        this.syncViewportHeight();
        clearTimeout(this._resizeTimer);
        this._resizeTimer = setTimeout(() => this.updateItemsPerPage(), 200);
      });

      if (window.visualViewport) {
        window.visualViewport.addEventListener(
          "resize",
          this._visualViewportResizeHandler,
          { passive: true },
        );
        window.visualViewport.addEventListener(
          "scroll",
          this._visualViewportResizeHandler,
          { passive: true },
        );
      }

      window.addEventListener(
        "orientationchange",
        this._visualViewportResizeHandler,
        { passive: true },
      );

      // 全局防止浏览器默认打开图片
      window.addEventListener("dragover", (e) => e.preventDefault());
      window.addEventListener("drop", (e) => e.preventDefault());
    },

    syncViewportHeight() {
      const visualViewportHeight = window.visualViewport
        ? Number(window.visualViewport.height)
        : 0;
      const nextHeight =
        visualViewportHeight > 0
          ? visualViewportHeight
          : window.innerHeight || 0;
      if (!Number.isFinite(nextHeight) || nextHeight <= 0) return;

      const roundedHeight = Math.round(nextHeight);
      const safeHeight = Math.max(0, roundedHeight - 1);
      updateCssVariable("--app-viewport-height", `${roundedHeight}px`);
      updateCssVariable("--app-viewport-height-safe", `${safeHeight}px`);
    },

    // 轮询服务器状态，准备就绪后执行 bootstrap
    checkServerStatus() {
      getServerStatus()
        .then((res) => {
          this.serverStatus = res;
          if (res.status === "ready") {
            if (!this._bootstrapped) {
              this._bootstrapped = true;
              this.bootstrapOnce();
            }
          } else {
            setTimeout(() => this.checkServerStatus(), 500);
          }
        })
        .catch(() => {
          setTimeout(() => this.checkServerStatus(), 1000);
        });
    },

    // 仅执行一次的启动逻辑 (加载设置)
    bootstrapOnce() {
      return Promise.all([getSettings(), this.loadIsolatedCategories()])
        .then(([settings]) => {
          const localPerPage = localStorage.getItem("st_manager_per_page");
          const localPerPageWi = localStorage.getItem("st_manager_per_page_wi");

          const normalizedRoots = Array.isArray(
            settings.allowed_abs_resource_roots,
          )
            ? settings.allowed_abs_resource_roots
            : typeof settings.allowed_abs_resource_roots === "string"
              ? settings.allowed_abs_resource_roots
                  .split(/[\r\n,]+/)
                  .map((s) => s.trim())
                  .filter(Boolean)
              : [];

          this.settingsForm = {
            ...settings,
            allowed_abs_resource_roots: normalizedRoots,
            default_sort: settings.default_sort || "date_desc",
            show_header_sort: settings.show_header_sort !== false,
            st_auth_type: settings.st_auth_type || "basic",
            st_basic_username: settings.st_basic_username || "",
            st_basic_password: settings.st_basic_password || "",
            st_web_username: settings.st_web_username || "",
            st_web_password: settings.st_web_password || "",
            st_proxy: settings.st_proxy || "",
            items_per_page: localPerPage
              ? parseInt(localPerPage)
              : settings.items_per_page || 0,
            items_per_page_wi: localPerPageWi
              ? parseInt(localPerPageWi)
              : settings.items_per_page_wi || 0,
            cards_list_use_index: !!settings.cards_list_use_index,
            fast_search_use_index: !!settings.fast_search_use_index,
            worldinfo_list_use_index: !!settings.worldinfo_list_use_index,
            sync_source_title_on_update: settings.sync_source_title_on_update !== false,
          };
          this.sharedWallpapers = Array.isArray(settings.shared_wallpapers)
            ? settings.shared_wallpapers
            : [];

          this.currentSort = this.settingsForm.default_sort || "date_desc";

          // 应用视觉设置
          if (settings.theme_accent) this.applyTheme(settings.theme_accent);
          this.isDarkMode =
            settings.dark_mode !== undefined ? settings.dark_mode : true;
          this.applyDarkMode();
          applyFont(this.settingsForm.font_style || "sans");

          updateCssVariable(
            "--card-min-width",
            (this.settingsForm.card_width || 220) + "px",
          );

          const managerBackgroundUrl = this.resolveManagerBackgroundUrl();
          if (managerBackgroundUrl) {
            this.updateBackgroundImage(this.resolveManagerBackgroundUrl());
            updateCssVariable(
              "--bg-blur",
              (this.settingsForm.bg_blur || 0) + "px",
            );
            updateCssVariable(
              "--bg-overlay-opacity",
              this.settingsForm.bg_opacity || 0.95,
            );
          } else {
            this.updateBackgroundImage("");
          }

          this.updateItemsPerPage();

          // 发出事件通知组件设置已加载 (代替原 app.js 直接调用 fetchCards)
          window.dispatchEvent(new CustomEvent("settings-loaded"));
        })
        .catch((err) => {
          console.error("Bootstrap failed", err);
          // 即使失败也发出事件，让 UI 尝试加载默认数据
          window.dispatchEvent(new CustomEvent("settings-loaded"));
        });
    },

    loadIsolatedCategories() {
      return getIsolatedCategories()
        .then((res) => {
          const paths = res?.isolated_categories?.paths;
          this.isolatedCategories = Array.isArray(paths) ? paths : [];
          return this.isolatedCategories;
        })
        .catch((err) => {
          console.error("Load isolated categories failed", err);
          this.isolatedCategories = [];
          return this.isolatedCategories;
        });
    },

    saveIsolatedCategories(paths) {
      const previous = Array.isArray(this.isolatedCategories)
        ? [...this.isolatedCategories]
        : [];
      const next = Array.isArray(paths) ? [...paths] : [];
      this.isolatedCategories = next;

      return saveIsolatedCategoriesRequest({ paths: next })
        .then((res) => {
          if (!res?.success) {
            this.isolatedCategories = previous;
            alert("保存隔离分类失败: " + (res?.msg || "unknown"));
            return res;
          }

          const canonicalPaths = res?.isolated_categories?.paths;
          this.isolatedCategories = Array.isArray(canonicalPaths)
            ? canonicalPaths
            : [];
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
          return res;
        })
        .catch((err) => {
          this.isolatedCategories = previous;
          alert("保存隔离分类失败: " + err);
          throw err;
        });
    },

    addIsolatedCategory(path) {
      const value = String(path || "").trim();
      if (!value) return Promise.resolve({ success: false, skipped: true });
      const next = [...(this.isolatedCategories || []), value];
      return this.saveIsolatedCategories(next).then((res) => {
        if (res?.success) {
          this.showToast(`已设为隔离分类：${value}`, 1800);
        }
        return res;
      });
    },

    removeIsolatedCategory(path) {
      const value = String(path || "").trim();
      const next = (this.isolatedCategories || []).filter(
        (item) => item !== value,
      );
      return this.saveIsolatedCategories(next).then((res) => {
        if (res?.success) {
          this.showToast(`已取消隔离分类：${value}`, 1800);
        }
        return res;
      });
    },

    // 加载本地存储的偏好 (UI 优先)
    loadUserPreferences() {
      const savedPerPage = localStorage.getItem("st_manager_per_page");

      if (savedPerPage)
        this.settingsForm.items_per_page = parseInt(savedPerPage);
    },

    loadTagViewPrefs() {
      const fallback = buildDefaultTagViewPrefs();

      try {
        const raw = localStorage.getItem(TAG_VIEW_PREFS_STORAGE_KEY);
        if (!raw) {
          this.tagViewPrefs = fallback;
          return this.tagViewPrefs;
        }

        const parsed = JSON.parse(raw);
        const parsedObject =
          parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? parsed
            : {};
        this.tagViewPrefs = {
          ...fallback,
          ...parsedObject,
          rememberLastTagView: parsedObject.rememberLastTagView === true,
          mixedCategoryView: parsedObject.mixedCategoryView !== false,
          categoryFilterInclude: Array.isArray(
            parsedObject.categoryFilterInclude,
          )
            ? parsedObject.categoryFilterInclude.filter(Boolean)
            : [],
          categoryFilterExclude: Array.isArray(
            parsedObject.categoryFilterExclude,
          )
            ? parsedObject.categoryFilterExclude.filter(Boolean)
            : [],
          lastCategorySortName:
            typeof parsedObject.lastCategorySortName === "string"
              ? parsedObject.lastCategorySortName
              : "",
        };
      } catch (_) {
        this.tagViewPrefs = fallback;
      }

      return this.tagViewPrefs;
    },

    saveTagViewPrefs(nextPrefs) {
      const current =
        this.tagViewPrefs && typeof this.tagViewPrefs === "object"
          ? this.tagViewPrefs
          : buildDefaultTagViewPrefs();
      const normalized = {
        ...buildDefaultTagViewPrefs(),
        ...current,
        ...(nextPrefs &&
        typeof nextPrefs === "object" &&
        !Array.isArray(nextPrefs)
          ? nextPrefs
          : {}),
      };

      normalized.rememberLastTagView = normalized.rememberLastTagView === true;
      normalized.mixedCategoryView = normalized.mixedCategoryView !== false;
      normalized.categoryFilterInclude = Array.isArray(
        normalized.categoryFilterInclude,
      )
        ? normalized.categoryFilterInclude.filter(Boolean)
        : [];
      normalized.categoryFilterExclude = Array.isArray(
        normalized.categoryFilterExclude,
      )
        ? normalized.categoryFilterExclude.filter(Boolean)
        : [];
      normalized.lastCategorySortName =
        typeof normalized.lastCategorySortName === "string"
          ? normalized.lastCategorySortName
          : "";
      this.tagViewPrefs = normalized;

      try {
        localStorage.setItem(
          TAG_VIEW_PREFS_STORAGE_KEY,
          JSON.stringify(normalized),
        );
      } catch (_) {
        // ignore localStorage persistence failures and keep runtime state
      }

      return this.tagViewPrefs;
    },

    // === 全局动作 ===

    // 切换深色模式
    toggleDarkMode() {
      this.isDarkMode = !this.isDarkMode;
      this.settingsForm.dark_mode = this.isDarkMode;
      this.applyDarkMode();
      this.saveSettings(false); // 静默保存
    },

    applyDarkMode() {
      if (this.isDarkMode) {
        document.documentElement.classList.remove("light-mode");
      } else {
        document.documentElement.classList.add("light-mode");
      }
    },

    // 应用主题色
    applyTheme(colorName) {
      const t = THEME_PRESETS[colorName] || THEME_PRESETS.blue;
      updateCssVariable("--accent-main", t.main);
      updateCssVariable("--accent-hover", t.hover);
      updateCssVariable("--accent-light", t.light);
      updateCssVariable("--accent-faint", t.faint);
      updateCssVariable("--accent-main-rgb", t.rgb);
      this.settingsForm.theme_accent = colorName;
    },

    // 更新背景图
    updateBackgroundImage(url) {
      if (!url) {
        updateCssVariable("--bg-image-url", "none");
        updateCssVariable("--bg-overlay-opacity", "1");
      } else {
        updateCssVariable("--bg-image-url", `url('${url}')`);
        const opacity =
          this.settingsForm.bg_opacity !== undefined
            ? this.settingsForm.bg_opacity
            : 0.95;
        updateCssVariable("--bg-overlay-opacity", opacity);
      }
    },

    resolveManagerBackgroundUrl() {
      const selectedId = String(
        this.settingsForm.manager_wallpaper_id || "",
      ).trim();
      if (selectedId) {
        const item = this.sharedWallpapers.find(
          (item) => item.id === selectedId,
        );
        if (item && item.file) {
          return `/api/beautify/preview-asset/${item.file
            .split("/")
            .map(encodeURIComponent)
            .join("/")}`;
        }
      }

      return this.settingsForm.bg_url || "";
    },

    // 保存设置
    saveSettings(closeModal = true, options = {}) {
      this.applyTheme(this.settingsForm.theme_accent);

      // 乐观更新 localStorage
      if (this.settingsForm.items_per_page)
        localStorage.setItem(
          "st_manager_per_page",
          this.settingsForm.items_per_page,
        );
      if (this.settingsForm.items_per_page_wi)
        localStorage.setItem(
          "st_manager_per_page_wi",
          this.settingsForm.items_per_page_wi,
        );

      return saveSettings(this.settingsForm, options).then((res) => {
        if (res.success) {
          this.updateItemsPerPage();
          // 触发事件让组件刷新
          if (closeModal) {
            window.dispatchEvent(
              new CustomEvent("settings-saved", {
                detail: { closeModal: true },
              }),
            );
          }
        } else if (!res.requires_confirmation) {
          alert("保存失败: " + res.msg);
        }
        return res;
      });
    },

    // 计算每页项目数 (响应式)
    updateItemsPerPage() {
      const userSetting = parseInt(this.settingsForm.items_per_page) || 0;

      if (userSetting > 0) {
        this.itemsPerPage = Math.min(Math.max(userSetting, 10), 500);
      } else {
        const availableWidth = window.innerWidth - 300 - 48; // Sidebar + Padding
        const availableHeight = window.innerHeight - 64 - 60; // Header + Footer

        // 估算
        const cols = Math.floor(Math.max(1, availableWidth / 224));
        const rows = Math.floor(Math.max(1, availableHeight / 472));

        this.itemsPerPage = Math.max(20, Math.floor(cols * rows * 1.5));
      }
    },

    normalizeTagTaxonomy(raw) {
      const fallback = buildDefaultTagTaxonomy();
      if (!raw || typeof raw !== "object") return fallback;

      const defaultCategory =
        String(raw.default_category || "").trim() || DEFAULT_TAG_CATEGORY;

      const categories = {};
      const rawCategories = raw.categories;
      if (
        rawCategories &&
        typeof rawCategories === "object" &&
        !Array.isArray(rawCategories)
      ) {
        Object.entries(rawCategories).forEach(([rawName, rawCfg]) => {
          const name = String(rawName || "").trim();
          if (!name) return;

          let color = DEFAULT_TAG_CATEGORY_COLOR;
          let opacity = DEFAULT_TAG_CATEGORY_OPACITY;
          if (rawCfg && typeof rawCfg === "object" && !Array.isArray(rawCfg)) {
            color = normalizeHexColor(rawCfg.color, DEFAULT_TAG_CATEGORY_COLOR);
            opacity = normalizeOpacity(
              rawCfg.opacity,
              DEFAULT_TAG_CATEGORY_OPACITY,
            );
          } else if (typeof rawCfg === "string") {
            color = normalizeHexColor(rawCfg, DEFAULT_TAG_CATEGORY_COLOR);
          }

          categories[name] = {
            color,
            opacity,
          };
        });
      }

      if (!categories[defaultCategory]) {
        categories[defaultCategory] = {
          color: DEFAULT_TAG_CATEGORY_COLOR,
          opacity: DEFAULT_TAG_CATEGORY_OPACITY,
        };
      }

      const categoryOrder = [];
      const seen = new Set();
      const rawOrder = Array.isArray(raw.category_order)
        ? raw.category_order
        : [];
      rawOrder.forEach((item) => {
        const name = String(item || "").trim();
        if (!name || seen.has(name) || !categories[name]) return;
        seen.add(name);
        categoryOrder.push(name);
      });

      if (!seen.has(defaultCategory)) {
        categoryOrder.unshift(defaultCategory);
        seen.add(defaultCategory);
      }

      Object.keys(categories)
        .sort((a, b) => a.localeCompare(b, "zh-CN", { sensitivity: "base" }))
        .forEach((name) => {
          if (seen.has(name)) return;
          seen.add(name);
          categoryOrder.push(name);
        });

      const tagToCategory = {};
      const rawMap = raw.tag_to_category;
      if (rawMap && typeof rawMap === "object" && !Array.isArray(rawMap)) {
        Object.entries(rawMap).forEach(([rawTag, rawCategory]) => {
          const tag = String(rawTag || "").trim();
          if (!tag) return;

          let category = String(rawCategory || "").trim();
          if (!category || !categories[category]) {
            category = defaultCategory;
          }
          tagToCategory[tag] = category;
        });
      }

      const categoryTagOrder = {};
      const rawCategoryTagOrder = raw.category_tag_order;
      if (
        rawCategoryTagOrder &&
        typeof rawCategoryTagOrder === "object" &&
        !Array.isArray(rawCategoryTagOrder)
      ) {
        Object.entries(rawCategoryTagOrder).forEach(
          ([rawCategory, rawTags]) => {
            const category = String(rawCategory || "").trim();
            if (!Array.isArray(rawTags)) return;

            rawTags.forEach((rawTag) => {
              const tag = String(rawTag || "").trim();
              if (!tag) return;

              const targetCategory = String(tagToCategory[tag] || "").trim();
              if (!targetCategory || !categories[targetCategory]) return;

              if (category !== targetCategory) {
                return;
              }

              const targetTags = categoryTagOrder[targetCategory] || [];
              if (targetTags.includes(tag)) return;
              targetTags.push(tag);
              categoryTagOrder[targetCategory] = targetTags;
            });
          },
        );

        Object.keys(categoryTagOrder).forEach((category) => {
          if (!categories[category] || !categoryTagOrder[category].length) {
            delete categoryTagOrder[category];
          }
        });
      }

      let updatedAt = parseInt(raw.updated_at, 10);
      if (Number.isNaN(updatedAt) || updatedAt < 0) updatedAt = 0;

      return {
        default_category: defaultCategory,
        category_order: categoryOrder,
        categories,
        tag_to_category: tagToCategory,
        category_tag_order: categoryTagOrder,
        updated_at: updatedAt,
      };
    },

    setTagTaxonomy(raw) {
      this.tagTaxonomy = this.normalizeTagTaxonomy(raw);
      this.rebuildTagGroups();
      return this.tagTaxonomy;
    },

    getCategoryColor(category) {
      const taxonomy = this.tagTaxonomy || buildDefaultTagTaxonomy();
      const categories = taxonomy.categories || {};
      const cfg = categories[category] || {};
      return normalizeHexColor(cfg.color, DEFAULT_TAG_CATEGORY_COLOR);
    },

    getCategoryOpacity(category) {
      const taxonomy = this.tagTaxonomy || buildDefaultTagTaxonomy();
      const categories = taxonomy.categories || {};
      const cfg = categories[category] || {};
      return normalizeOpacity(cfg.opacity, DEFAULT_TAG_CATEGORY_OPACITY);
    },

    getTagCategory(tag) {
      const taxonomy = this.tagTaxonomy || buildDefaultTagTaxonomy();
      const defaultCategory = taxonomy.default_category || DEFAULT_TAG_CATEGORY;
      const tagToCategory = taxonomy.tag_to_category || {};

      const key = String(tag || "").trim();
      if (!key) return defaultCategory;

      const category = String(tagToCategory[key] || "").trim();
      if (!category || !taxonomy.categories || !taxonomy.categories[category]) {
        return defaultCategory;
      }
      return category;
    },

    getTagColor(tag) {
      return this.getCategoryColor(this.getTagCategory(tag));
    },

    getTagChipStyle(tag) {
      const color = this.getTagColor(tag);
      const opacity = this.getCategoryOpacity(this.getTagCategory(tag));
      const bgColorWeight = Math.max(
        8,
        Math.min(62, Math.round(opacity * 0.62)),
      );
      const borderColorWeight = Math.max(
        18,
        Math.min(76, Math.round(opacity * 0.82)),
      );
      const textColorWeight = Math.max(
        8,
        Math.min(34, Math.round(opacity * 0.32)),
      );

      const bgBaseWeight = 100 - bgColorWeight;
      const borderBaseWeight = 100 - borderColorWeight;
      const textBaseWeight = 100 - textColorWeight;

      return `--tag-cat-color:${color};--tag-cat-opacity:${opacity};--tag-cat-bg:color-mix(in srgb, var(--bg-tag, var(--bg-sub)) ${bgBaseWeight}%, ${color} ${bgColorWeight}%);--tag-cat-border:color-mix(in srgb, var(--border-light) ${borderBaseWeight}%, ${color} ${borderColorWeight}%);--tag-cat-text:color-mix(in srgb, var(--text-main) ${textBaseWeight}%, ${color} ${textColorWeight}%);`;
    },

    groupTagsByTaxonomy(tags) {
      const tagList = Array.isArray(tags) ? tags : [];
      if (tagList.length === 0) return [];

      const taxonomy = this.tagTaxonomy || buildDefaultTagTaxonomy();
      const order = Array.isArray(taxonomy.category_order)
        ? taxonomy.category_order
        : [];
      const categoryTagOrder =
        taxonomy.category_tag_order &&
        typeof taxonomy.category_tag_order === "object"
          ? taxonomy.category_tag_order
          : {};
      const grouped = new Map();

      tagList.forEach((rawTag) => {
        const tag = String(rawTag || "").trim();
        if (!tag) return;

        const category = this.getTagCategory(tag);
        if (!grouped.has(category)) {
          grouped.set(category, []);
        }
        grouped.get(category).push(tag);
      });

      const orderedCategories = [];
      const seen = new Set();
      order.forEach((rawCategory) => {
        const category = String(rawCategory || "").trim();
        if (!category || seen.has(category) || !grouped.has(category)) return;
        seen.add(category);
        orderedCategories.push(category);
      });

      Array.from(grouped.keys())
        .sort((a, b) => a.localeCompare(b, "zh-CN", { sensitivity: "base" }))
        .forEach((category) => {
          if (seen.has(category)) return;
          seen.add(category);
          orderedCategories.push(category);
        });

      return orderedCategories.map((category) => ({
        category,
        color: this.getCategoryColor(category),
        opacity: this.getCategoryOpacity(category),
        tags: (() => {
          const tagsInCategory = [...(grouped.get(category) || [])];
          const orderedTags = Array.isArray(categoryTagOrder[category])
            ? categoryTagOrder[category]
            : [];
          if (!orderedTags.length) return tagsInCategory;

          const tagSet = new Set(tagsInCategory);
          const seenTags = new Set();
          const result = [];

          orderedTags.forEach((rawTag) => {
            const tag = String(rawTag || "").trim();
            if (!tag || seenTags.has(tag) || !tagSet.has(tag)) return;
            seenTags.add(tag);
            result.push(tag);
          });

          tagsInCategory.forEach((tag) => {
            if (seenTags.has(tag)) return;
            seenTags.add(tag);
            result.push(tag);
          });

          return result;
        })(),
      }));
    },

    rebuildTagGroups() {
      this.globalTagGroups = this.groupTagsByTaxonomy(
        this.globalTagsPool || [],
      );
      this.sidebarTagGroups = this.groupTagsByTaxonomy(
        this.sidebarTagsPool || [],
      );
    },

    // 显示 Toast 通知
    showToast(msg, duration = 3000, iconName = "") {
      if (typeof duration === "string") {
        duration = 3000;
      }
      this.toastMessage = msg;
      const normalizedIconName = String(iconName || "").trim();
      this.toastIcon = TOAST_ICON_NAMES.has(normalizedIconName)
        ? normalizedIconName
        : "";
      this.showToastState = true;
      if (this.toastTimer) clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => {
        this.showToastState = false;
        this.toastIcon = "";
      }, duration);
    },

    startBatchProgress(title, total) {
      this.batchProgress = {
        visible: true,
        status: "running",
        title: String(title || "批量处理"),
        current: 0,
        total: Math.max(0, Number(total) || 0),
        currentCardId: "",
        message: "准备开始...",
        result: null,
        cancelRequested: false,
      };
    },

    updateBatchProgress(patch = {}) {
      this.batchProgress = {
        ...(this.batchProgress || {}),
        ...patch,
      };
    },

    requestBatchProgressCancel() {
      if (this.batchProgress?.status === "running") {
        this.updateBatchProgress({
          cancelRequested: true,
          message: "将在当前卡片完成后停止...",
        });
      }
    },

    finishBatchProgress(result = {}) {
      const cancelled = result.status === "cancelled" || !!result.cancelled;
      this.updateBatchProgress({
        status: cancelled ? "cancelled" : "completed",
        currentCardId: "",
        message: cancelled ? "已停止后续处理" : "全部处理完成",
        result,
        cancelRequested: false,
      });
    },

    dismissBatchProgress() {
      this.updateBatchProgress({ visible: false });
    },

    // 执行系统操作 (打开文件夹等)
    systemAction(action) {
      performSystemAction(action).then((res) => {
        if (!res.success && res.msg) alert(res.msg);
        else if (res.msg) alert(res.msg);
      });
    },

    // 触发立即扫描
    scanNow() {
      if (
        !confirm(
          "立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）",
        )
      )
        return;
      this.isLoading = true;
      triggerScan()
        .then((res) => {
          if (!res.success) alert("触发扫描失败: " + (res.msg || "unknown"));
          else alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
        })
        .catch((err) => alert("网络错误: " + err))
        .finally(() => {
          this.isLoading = false;
        });
    },
    // 全局标签切换逻辑 (三态：包含 -> 排除 -> 无)
    // options.forceExclude=true 时可直接进入“排除”状态（用于 Shift+点击）
    toggleFilterTag(tag, options = {}) {
      const vs = this.isCardAdvancedFilterTagEditActive()
        ? this.getCardAdvancedFilterTagState()
        : this.viewState;
      let includeTags = [...vs.filterTags];
      let excludeTags = [...vs.excludedTags];
      const forceExclude = !!(options && options.forceExclude);

      const inInclude = includeTags.indexOf(tag);
      const inExclude = excludeTags.indexOf(tag);

      if (forceExclude) {
        // Shift+点击：直接进入排除（若已排除则保持不变）
        if (inInclude > -1) {
          includeTags.splice(inInclude, 1);
        }
        if (inExclude === -1) {
          excludeTags.push(tag);
        }
      } else {
        if (inInclude > -1) {
          // 当前是包含 -> 转为排除
          includeTags.splice(inInclude, 1);
          excludeTags.push(tag);
        } else if (inExclude > -1) {
          // 当前是排除 -> 转为无
          excludeTags.splice(inExclude, 1);
        } else {
          // 当前是无 -> 转为包含
          includeTags.push(tag);
        }
      }

      // 更新状态
      vs.filterTags = includeTags;
      vs.excludedTags = excludeTags;

      if (this.isCardAdvancedFilterTagEditActive()) {
        this.syncCardAdvancedFilterValidationState();
      }

      // 触发列表刷新
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    openCardAdvancedFilterDrawer(section = "") {
      this.cardAdvancedFilterDraft = this.getDefaultCardAdvancedFilterDraft();
      this.clearCardAdvancedFilterValidationState();
      this.setCardAdvancedFilterSection(
        section || this.cardAdvancedFilterActiveSection,
      );
      this.showCardAdvancedFilterDrawer = true;
    },

    getDefaultCardAdvancedFilterDraft() {
      return buildCardAdvancedFilterDraftFromViewState(
        this.viewState,
        this.currentSort,
        this.settingsForm.default_sort,
      );
    },

    closeCardAdvancedFilterDrawer(clearTagEditSource = true) {
      this.showCardAdvancedFilterDrawer = false;
      if (clearTagEditSource) {
        this.setCardAdvancedFilterTagEditSource("");
      }
    },

    setCardAdvancedFilterSection(section = "") {
      const nextSection = normalizeCardAdvancedFilterSection(
        section || this.cardAdvancedFilterActiveSection,
      );
      this.cardAdvancedFilterActiveSection = nextSection;
      return nextSection;
    },

    clearCardAdvancedFilterValidationState() {
      this.cardAdvancedFilterValidationState =
        buildDefaultCardAdvancedFilterValidationState();
    },

    syncCardAdvancedFilterValidationState() {
      const validationError = this.validateCardAdvancedFilterDraft();
      this.cardAdvancedFilterValidationState = validationError
        ? validationError
        : buildDefaultCardAdvancedFilterValidationState();
      return this.cardAdvancedFilterValidationState;
    },

    setCardAdvancedFilterTagEditSource(source = "") {
      this.cardAdvancedFilterTagEditSource =
        String(source || "").trim() === "card-advanced-filter"
          ? "card-advanced-filter"
          : "";
      return this.cardAdvancedFilterTagEditSource;
    },

    isCardAdvancedFilterTagEditActive() {
      return this.cardAdvancedFilterTagEditSource === "card-advanced-filter";
    },

    getCardAdvancedFilterTagState() {
      return this.viewState;
    },

    clearCardAdvancedFilterDraft() {
      if (!this.cardAdvancedFilterDraft) {
        this.cardAdvancedFilterDraft = this.getDefaultCardAdvancedFilterDraft();
      }

      const nextSort =
        toSummaryLabel(this.settingsForm.default_sort) ||
        toSummaryLabel(this.currentSort) ||
        "date_desc";

      this.cardAdvancedFilterDraft = {
        ...this.cardAdvancedFilterDraft,
        favFilter: "none",
        searchScope: "current",
        recursiveFilter: true,
        sort: nextSort,
        ...buildDefaultCardAdvancedFilterFields(),
      };
      this.clearCardAdvancedFilterValidationState();
    },

    validateCardAdvancedFilterDraft(draft = null) {
      const currentDraft = draft || this.cardAdvancedFilterDraft;
      if (!currentDraft) {
        return null;
      }

      const tokenMin = toSummaryLabel(currentDraft.tokenMin);
      const tokenMax = toSummaryLabel(currentDraft.tokenMax);

      if (tokenMin !== "" && !/^\d+$/.test(tokenMin)) {
        return {
          section: "numeric",
          field: "tokenMin",
          message: "Token 最小值必须是非负整数",
        };
      }

      if (tokenMax !== "" && !/^\d+$/.test(tokenMax)) {
        return {
          section: "numeric",
          field: "tokenMax",
          message: "Token 最大值必须是非负整数",
        };
      }

      if (
        tokenMin !== "" &&
        tokenMax !== "" &&
        Number(tokenMin) > Number(tokenMax)
      ) {
        return {
          section: "numeric",
          field: "tokenRange",
          message: "Token 最小值不能大于最大值",
        };
      }

      if (
        isInvalidDateRange(
          currentDraft.importDateFrom,
          currentDraft.importDateTo,
        )
      ) {
        return {
          section: "time",
          field: "importDate",
          message: "导入时间开始日期不能晚于结束日期",
        };
      }

      if (
        isInvalidDateRange(
          currentDraft.modifiedDateFrom,
          currentDraft.modifiedDateTo,
        )
      ) {
        return {
          section: "time",
          field: "modifiedDate",
          message: "修改时间开始日期不能晚于结束日期",
        };
      }

      return null;
    },

    applyCardAdvancedFilterDraft() {
      if (!this.cardAdvancedFilterDraft) {
        this.cardAdvancedFilterDraft = this.getDefaultCardAdvancedFilterDraft();
      }

      const validationError = this.validateCardAdvancedFilterDraft(
        this.cardAdvancedFilterDraft,
      );
      if (validationError) {
        this.cardAdvancedFilterValidationState = validationError;
        return { success: false, ...validationError };
      }

      const draft = this.cardAdvancedFilterDraft;
      this.viewState.favFilter = draft.favFilter || "none";
      this.viewState.searchScope = draft.searchScope || "current";
      this.viewState.recursiveFilter = draft.recursiveFilter !== false;
      this.viewState.importDateFrom = toSummaryLabel(draft.importDateFrom);
      this.viewState.importDateTo = toSummaryLabel(draft.importDateTo);
      this.viewState.modifiedDateFrom = toSummaryLabel(draft.modifiedDateFrom);
      this.viewState.modifiedDateTo = toSummaryLabel(draft.modifiedDateTo);
      this.viewState.tokenMin = toSummaryLabel(draft.tokenMin);
      this.viewState.tokenMax = toSummaryLabel(draft.tokenMax);
      this.currentSort =
        toSummaryLabel(draft.sort) ||
        this.settingsForm.default_sort ||
        "date_desc";
      this.clearCardAdvancedFilterValidationState();
      this.showCardAdvancedFilterDrawer = false;
      this.setCardAdvancedFilterTagEditSource("");
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
      return { success: true };
    },

    getCardAdvancedFilterSummaryItems() {
      const vs = this.viewState || {};
      const items = [];

      if (vs.favFilter === "included") {
        items.push({ key: "favFilter", label: "只看收藏", section: "basic" });
      } else if (vs.favFilter === "excluded") {
        items.push({ key: "favFilter", label: "排除收藏", section: "basic" });
      }

      if (vs.searchScope === "all_dirs") {
        items.push({
          key: "searchScope",
          label: "搜索范围: 全部目录",
          section: "basic",
        });
      } else if (vs.searchScope === "full") {
        items.push({
          key: "searchScope",
          label: "搜索范围: 全库全文",
          section: "basic",
        });
      }

      if (vs.recursiveFilter === false) {
        items.push({
          key: "recursiveFilter",
          label: "不包含子目录",
          section: "basic",
        });
      }

      if (vs.importDateFrom || vs.importDateTo) {
        items.push({
          key: "importDate",
          label: `导入时间: ${vs.importDateFrom || "不限"} - ${vs.importDateTo || "不限"}`,
          section: "time",
        });
      }

      if (vs.modifiedDateFrom || vs.modifiedDateTo) {
        items.push({
          key: "modifiedDate",
          label: `修改时间: ${vs.modifiedDateFrom || "不限"} - ${vs.modifiedDateTo || "不限"}`,
          section: "time",
        });
      }

      if (vs.tokenMin !== "" || vs.tokenMax !== "") {
        items.push({
          key: "tokenRange",
          label: `Token: ${vs.tokenMin || "不限"} - ${vs.tokenMax || "不限"}`,
          section: "numeric",
        });
      }

      const includeTags = Array.isArray(vs.filterTags) ? vs.filterTags : [];
      const excludeTags = Array.isArray(vs.excludedTags) ? vs.excludedTags : [];
      if (includeTags.length || excludeTags.length) {
        const parts = [];
        if (includeTags.length) {
          parts.push(`包含 ${includeTags.join(", ")}`);
        }
        if (excludeTags.length) {
          parts.push(`排除 ${excludeTags.join(", ")}`);
        }
        items.push({
          key: "tags",
          label: `标签: ${parts.join(" / ")}`,
          section: "tags",
        });
      }

      const defaultSort = this.settingsForm.default_sort || "date_desc";
      if ((this.currentSort || defaultSort) !== defaultSort) {
        items.push({
          key: "sort",
          label: `排序: ${this.currentSort}`,
          section: "basic",
        });
      }

      return items;
    },

    getCardAdvancedFilterStatItems() {
      const vs = this.viewState || {};
      const hasTimeRange = !!(
        vs.importDateFrom ||
        vs.importDateTo ||
        vs.modifiedDateFrom ||
        vs.modifiedDateTo
      );
      const hasNumericRange = vs.tokenMin !== "" || vs.tokenMax !== "";
      const includeTags = (Array.isArray(vs.filterTags) ? vs.filterTags : [])
        .length;
      const excludeTags = (
        Array.isArray(vs.excludedTags) ? vs.excludedTags : []
      ).length;
      const hasNumericOrTagFilters =
        hasNumericRange || includeTags || excludeTags;
      // One combined status card summarizes numeric and tag filters,
      // then routes back to whichever editor section is currently relevant.
      const numericAndTagSection = hasNumericRange ? "numeric" : "tags";

      return [
        {
          key: "basic",
          label: "已启用条件",
          value: String(this.getCardAdvancedFilterCount()),
          section: "basic",
        },
        {
          key: "time",
          label: "时间范围",
          value: hasTimeRange ? "已设置" : "未设置",
          section: "time",
        },
        {
          key: "numeric",
          label: "数值 / 标签",
          value: hasNumericOrTagFilters ? "已设置" : "未设置",
          section: numericAndTagSection,
        },
      ];
    },

    getCardAdvancedFilterCount() {
      return this.getCardAdvancedFilterSummaryItems().length;
    },

    clearCardAdvancedFilterItem(key) {
      const targetKey = String(key || "").trim();
      if (!targetKey) return;

      switch (targetKey) {
        case "favFilter":
          this.viewState.favFilter = "none";
          break;
        case "searchScope":
          this.viewState.searchScope = "current";
          break;
        case "recursiveFilter":
          this.viewState.recursiveFilter = true;
          break;
        case "importDate":
          this.viewState.importDateFrom = "";
          this.viewState.importDateTo = "";
          break;
        case "modifiedDate":
          this.viewState.modifiedDateFrom = "";
          this.viewState.modifiedDateTo = "";
          break;
        case "tokenRange":
          this.viewState.tokenMin = "";
          this.viewState.tokenMax = "";
          break;
        case "tags":
          this.viewState.filterTags = [];
          this.viewState.excludedTags = [];
          break;
        case "sort":
          this.currentSort = this.settingsForm.default_sort || "date_desc";
          break;
        default:
          return;
      }

      if (this.cardAdvancedFilterDraft) {
        this.cardAdvancedFilterDraft = this.getDefaultCardAdvancedFilterDraft();
      }
      this.clearCardAdvancedFilterValidationState();
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    clearAllCardAdvancedFilters() {
      this.viewState.favFilter = "none";
      this.viewState.searchScope = "current";
      this.viewState.recursiveFilter = true;
      this.viewState.importDateFrom = "";
      this.viewState.importDateTo = "";
      this.viewState.modifiedDateFrom = "";
      this.viewState.modifiedDateTo = "";
      this.viewState.tokenMin = "";
      this.viewState.tokenMax = "";
      this.viewState.filterTags = [];
      this.viewState.excludedTags = [];
      this.currentSort = this.settingsForm.default_sort || "date_desc";
      if (this.cardAdvancedFilterDraft) {
        this.cardAdvancedFilterDraft = this.getDefaultCardAdvancedFilterDraft();
      }
      this.clearCardAdvancedFilterValidationState();
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    getFavoriteFilter(mode = "") {
      const targetMode = String(mode || this.currentMode || "")
        .trim()
        .toLowerCase();
      if (targetMode === "chats") {
        return this.chatFavFilter || "none";
      }
      if (targetMode === "cards") {
        return this.viewState.favFilter || "none";
      }
      return "none";
    },

    setFavoriteFilter(mode = "", value = "none") {
      const targetMode = String(mode || this.currentMode || "")
        .trim()
        .toLowerCase();
      const nextValue = ["none", "included", "excluded"].includes(value)
        ? value
        : "none";

      if (targetMode === "chats") {
        this.chatFavFilter = nextValue;
        return;
      }

      if (targetMode === "cards") {
        this.viewState.favFilter = nextValue;
      }
    },

    //  切换收藏筛选 (三态循环)
    toggleFavFilter(mode = "") {
      const targetMode = String(mode || this.currentMode || "")
        .trim()
        .toLowerCase();
      const current = this.getFavoriteFilter(targetMode);

      if (current === "none") {
        this.setFavoriteFilter(targetMode, "included");
      } else if (current === "included") {
        this.setFavoriteFilter(targetMode, "excluded");
      } else {
        this.setFavoriteFilter(targetMode, "none");
      }
    },
  });
}
