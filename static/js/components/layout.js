/**
 * static/js/components/layout.js
 * 根布局组件：管理浏览状态(筛选/选中)与全局拖拽
 */

import { moveFolder } from "../api/system.js";
import { moveCard } from "../api/card.js";
import { installHostBridge } from "../utils/hostBridge.js";
import { installLongPressContextMenu } from "../utils/longPress.js";
import { installNativeDownloads } from "../utils/download.js";
import { register as registerViewLayer } from "../utils/viewStack.js";

export default function layout() {
  return {
    // === 代理状态 (为了兼容 HTML 中可能存在的引用) ===
    // === 1. 映射全局状态 (Global Store Proxies) ===
    get serverStatus() {
      return this.$store.global.serverStatus;
    },
    get isDarkMode() {
      return this.$store.global.isDarkMode;
    },
    get isLoading() {
      return this.$store.global.isLoading;
    },
    get toastMessage() {
      return this.$store.global.toastMessage;
    },
    get toastIcon() {
      return this.$store.global.toastIcon;
    },
    get toastIconKind() {
      return this.$store.global.toastIconKind;
    },
    get toastIconHref() {
      return this.$store.global.toastIconHref;
    },
    get toastIconMask() {
      return this.$store.global.toastIconMask;
    },
    get showToastState() {
      return this.$store.global.showToastState;
    },

    // 映射模式状态
    get currentMode() {
      return this.$store.global.currentMode;
    },

    // 映射全屏遮罩状态 (如果不属于特定组件)
    get showSettingsModal() {
      return this.$store.global.showSettingsModal;
    },

    // 映射全局操作 (Actions)
    toggleDarkMode() {
      this.$store.global.toggleDarkMode();
    },

    // 映射设备类型
    get deviceType() {
      return this.$store.global.deviceType;
    },

    // 如果 HTML 直接引用了 searchType，这里提供代理
    get searchQuery() {
      return this.$store.global.viewState.searchQuery;
    },
    get filterCategory() {
      return this.$store.global.viewState.filterCategory;
    },
    get selectedIds() {
      return this.$store.global.viewState.selectedIds;
    },
    set selectedIds(val) {
      this.$store.global.viewState.selectedIds = val;
      return true;
    },

    // 拖拽状态也建议走 Store，特别是 draggedCards
    get draggedCards() {
      return this.$store.global.viewState.draggedCards;
    },
    set draggedCards(val) {
      this.$store.global.viewState.draggedCards = val;
      return true;
    },

    get draggedFolder() {
      return this.$store.global.viewState.draggedFolder;
    },
    set draggedFolder(val) {
      this.$store.global.viewState.draggedFolder = val;
      return true;
    },

    // 本地 UI 状态 (仅 Layout 自身使用)
    dragCounter: 0,
    dragOverMain: false, // 主视图拖拽遮罩
    dragOverCat: null, // 侧边栏文件夹高亮

    // 初始化
    init() {
      this.reDeviceType();

      window.addEventListener("resize", () => {
        this.reDeviceType();
      });

      // === 返回手势支持（Android 返回键 / iOS 侧滑 / Alt+←）===
      // 只新增通道：既有 Escape / 拖拽取消等行为保持不变。
      this._installBackGestureSupport();

      // === 触摸长按 → 合成 contextmenu ===
      // 让 11 处既有的 @contextmenu 右键入口在触摸设备上可复用；
      // 桌面鼠标路径不受影响（模块内部只在触摸设备上挂钩子）。
      installLongPressContextMenu();
      installNativeDownloads();


      window.addEventListener("keydown", (e) => {
        if (
          e.key === "Escape" &&
          (this.draggedFolder || this.draggedCards.length > 0)
        ) {
          this.handleGlobalDragEnd();
        }
      });
      // 监听来自其他组件的重置信号
      window.addEventListener("reset-selection", () => {
        this.selectedIds = [];
      });
      // 监听全局拖拽结束事件 (由 Sidebar/Grid 触发)
      window.addEventListener("global-drag-end", () => {
        this.handleGlobalDragEnd();
      });

      // 粘贴导入等跨模块操作通过统一事件同步左侧导航和主视图。
      window.addEventListener("switch-mode", (event) => {
        const mode = event.detail?.mode;
        if (mode) this.switchMode(mode);
      });

      // 监听 Escape 取消拖拽
      window.addEventListener("keydown", (e) => {
        if (
          e.key === "Escape" &&
          (this.draggedFolder || this.draggedCards.length > 0)
        ) {
          this.handleGlobalDragEnd();
        }
      });

      // 监听从世界书跳转的事件
      window.addEventListener("jump-to-card-wi", (e) => {
        const cardId = e.detail;
        if (!cardId) return;

        // 1. 切换到角色卡模式
        this.switchMode("cards");

        // 2. 稍作延迟，等待 cardGrid 组件挂载/显示
        setTimeout(() => {
          // 派发定位事件，不传 category，让后端自动推导
          window.dispatchEvent(
            new CustomEvent("locate-card", {
              detail: {
                id: cardId,
                category: null,
                shouldOpenDetail: true,
              },
            }),
          );
        }, 100);
      });
    },

    // 重新设置设备类型
    reDeviceType() {
      const userAgent = navigator.userAgent || navigator.vendor || window.opera;
      let deviceType = "desktop";
      const viewportWidth =
        window.innerWidth || document.documentElement?.clientWidth || 0;

      if (viewportWidth > 0) {
        if (viewportWidth < 900) deviceType = "mobile";
        else if (viewportWidth < 1180) deviceType = "tablet";
      }

      if (viewportWidth <= 0) {
        // 平板设备检测（iPad 或 Android 平板）
        if (/iPad|Android/.test(userAgent) && !/Mobile/.test(userAgent)) {
          deviceType = "tablet";
        }

        // 手机设备检测
        if (
          /Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/.test(
            userAgent,
          )
        ) {
          deviceType = "mobile";
        }
      }

      this.syncSidebarForDeviceChange(
        this.$store.global.deviceType,
        deviceType,
      );
      this.$store.global.deviceType = deviceType;
    },

    // === 返回手势支持 ===
    // 把「当前有哪些层可以返回」注册给 viewStack，返回手势按 LIFO 关闭。
    // 这里刻意**不改动**任何既有的 Escape 处理逻辑：Escape 仍由各组件自己处理，
    // 本方法只是额外提供一条给 Android 返回键 / iOS 侧滑 / Alt+← 用的通道。
    //
    // ⚠️ 新增浮层时**必须**往下面 `layers` 表里加一行，否则按返回键会直接退出应用
    //（真机反馈过：左侧导航、右侧 dock、抽屉类都是这样被漏掉的）。
    _installBackGestureSupport() {
      const store = this.$store.global;

      const componentElement = name => document.querySelector(
        `[x-data="${name}"], [x-data="${name}()"], [data-back-scope="${name}"]`);
      const getField = (object, path) => path.split('.').reduce((value, key) => value?.[key], object);
      const componentParents = {
        detailModal: 'showDetail', wiEditor: 'showFullScreenWI', presetEditor: 'showPresetEditor',
        advancedEditor: 'showAdvancedModal', automationModal: 'showAutomationModal',
        batchImportModal: 'showBatchImportModal', importModal: 'showImportUrlModal',
        moveCardsModal: 'showMoveCardsModal', wiDetailPopup: 'showWiDetailModal',
        presetDetailReader: 'showModal', tagFilterModal: 'showTagFilterModal',
      };
      const mobileFields = new Set(['mobileNavOpen', 'showMobileSidebar', 'showMobilePromptDetailView',
        'showMobileHeaderMoreMenu', 'showMobileDetailView', 'showMobileMoreMenu', 'isMobileToolsOpen',
        'showMobileMenu']);

      // 读组件或具名局部作用域；所有子层都受父层和布局约束。
      const readComponent = (xDataName, field) => {
        if (typeof window.Alpine === "undefined") return null;
        const el = componentElement(xDataName);
        if (!el) return null;
        try {
          return getField(window.Alpine.$data(el), field);
        } catch (err) {
          return null;
        }
      };
      const componentLayer = (name, field, method, isVisible = () => true, isOpen = Boolean) => ({
        key: `${name}:${field}`,
        isActive: () => {
          const parent = componentParents[name];
          return isVisible() && (!parent || field === parent || !!readComponent(name, parent)) &&
            (!mobileFields.has(field) || store.deviceType === 'mobile') && isOpen(readComponent(name, field));
        },
        close: () => {
          const el = componentElement(name);
          const component = el && window.Alpine?.$data(el);
          if (!component) return;
          if (method) component[method]();
          else {
            const keys = field.split('.');
            const key = keys.pop();
            const owner = keys.reduce((value, part) => value[part], component);
            owner[key] = typeof owner[key] === 'object' ? null :
              typeof owner[key] === 'string' ? '' : false;
          }
        },
      });
      const chatReaderVisible = () =>
        store.currentMode === "chats" && readComponent("chatGrid", "detailOpen") === true;

      // 声明式浮层表：**顺序即优先级，靠后的先被返回键关闭**。
      // 因此列表从「最底层」写到「最顶层」。
      //
      // 排序原则：视觉上越靠前/越像"页面主体"的越靠前（越晚被关）。
      //   底部 sheet / 边栏 → 抽屉 → 弹窗 → 菜单 → 设置
      const layers = [
        // ---- 导航类（最早被关：它们是"页面外观"而非内容）----
        {
          key: "card-advanced-filter-drawer",
          isActive: () => store.currentMode === 'cards' && !!store.showCardAdvancedFilterDrawer,
          close: () => {
            store.showCardAdvancedFilterDrawer = false;
          },
        },
        {
          key: "beautify-package-detail-drawer",
          isActive: () => store.currentMode === 'beautify' && !!store.beautifyPackageDetailDrawerOpen,
          close: () => {
            store.beautifyPackageDetailDrawerOpen = false;
          },
        },
        {
          key: "beautify-mobile-fullscreen",
          isActive: () => store.currentMode === 'beautify' && store.deviceType === 'mobile' &&
            !!store.beautifyMobileFullscreenOpen,
          close: () => {
            store.beautifyMobileFullscreenOpen = false;
          },
        },
        // 右侧入口坞（移动端展开为底部 sheet）
        //
        // ⚠️ 只在移动端**展开**时才算一层。桌面的竖排坞是常驻边栏，
        // 若把它列为活动层，返回键会先去「收起坞」而不是回上一级，
        // 且桌面端坞可能默认展开 → 返回键永远被它吃掉。
        {
          key: "entry-dock",
          isActive: () =>
            store.deviceType === "mobile" &&
            readComponent("entryDock", "hasEntries") === true &&
            readComponent("entryDock", "expanded") === true,
          close: () => {
            const el = document.querySelector('[x-data="entryDock"]');
            if (el && typeof window.Alpine !== "undefined") {
              try {
                window.Alpine.$data(el).collapse();
                return;
              } catch (err) {
                // 拿不到组件就退回事件通道
              }
            }
            window.dispatchEvent(new CustomEvent("entry-dock:collapse"));
          },
        },
        // 左侧导航栏。
        //
        // ⚠️ 判定原则是「**侧栏是否常驻**」，不是设备类型本身：
        //   - mobile（窄屏）：侧栏是带遮罩的滑入抽屉 → **参与返回**
        //   - tablet / desktop（宽屏）：侧栏常驻占位，不是浮层 → **不参与返回**
        // 否则宽屏下按返回会先去"收边栏"，而用户根本看不出它被关过。
        //
        // 这条判据与模板一致：`sidebar.html` 用
        // `deviceType === 'mobile'` 决定是否渲染遮罩与 `sidebar-mobile` 类。
        // 真机验证过 392 CSS（mobile）和 1098 CSS（tablet）两档，
        // 且 mobile→tablet 过渡时哨兵项会自动退掉，不留历史残留。
        {
          key: "sidebar",
          isActive: () =>
            store.deviceType === "mobile" && !!store.visibleSidebar,
          close: () => {
            store.visibleSidebar = false;
            document.body.style.overflow = "";
          },
        },

        // ---- 弹窗类 ----
        componentLayer('sidebar', 'moduleMenuOpen', 'closeModuleMenu', () => !!store.visibleSidebar),
        componentLayer('entryDock', 'overflowOpen', 'closeOverflow', () =>
          store.deviceType !== 'mobile' && readComponent('entryDock', 'hasEntries') === true),
        componentLayer('gachaDraw', 'showGachaModal', 'requestClose'),
        componentLayer("chatGrid", "detailOpen", "closeChatDetail", chatReaderVisible),
        componentLayer("chatGrid", "readerMobilePanel", "closeReaderRightPanel", () =>
          chatReaderVisible() && readComponent("chatGrid", "readerResponsiveMode") === "mobile"),
        componentLayer("chatGrid", "readerViewSettingsOpen", null, chatReaderVisible),
        componentLayer("chatGrid", "regexConfigOpen", "closeRegexConfig", chatReaderVisible),
        componentLayer("chatGrid", "regexHelpOpen", "closeRegexHelp", chatReaderVisible),
        componentLayer("chatGrid", "editingFloor", "closeFloorEditor", chatReaderVisible),
        componentLayer("chatGrid", "bindPickerOpen", "closeBindPicker", chatReaderVisible),
        componentLayer("chatGrid", "regexRulePickerOpen", "closeRegexRulePicker", chatReaderVisible),
        componentLayer("chatGrid", "regexPresetPickerOpen", "closeRegexPresetPicker", chatReaderVisible),
        componentLayer("chatGrid", "readerDeleteConfirmOpen", "cancelDeleteChat", chatReaderVisible),
        componentLayer("detailModal", "showDetail", "requestClose"),
        componentLayer("detailModal", "mobileNavOpen", "closeMobileNav"),
        componentLayer("detailModal", "showGreetingListModal", "closeGreetingList"),
        componentLayer("detailModal", "showSetResourceFolderModal"),
        componentLayer("detailModal", "showRenameResourceFolderModal", "closeRenameResourceFolderModal"),
        componentLayer("detailModal", "showSkinGallery", "closeSkinGallery"),
        componentLayer("detailModal", "skinGalleryPreviewPath", "closeSkinGalleryPreview"),
        componentLayer("detailModal", "mainImagePreviewUrl", "closeMainImagePreview"),
        componentLayer("detailModal", "personaPreviewField", "closePersonaPreview"),
        componentLayer("detailModal", "showHelpModal"),
        componentLayer('wiDetailPopup', 'showWiDetailModal'),
        componentLayer('wiDetailPopup', 'showMobileSidebar'),
        componentLayer('wiDetailPopup', 'activeEntry', null, () => store.deviceType === 'mobile'),
        componentLayer('wiDetailPopup', 'showWiSortMenu'),
        componentLayer('presetDetailReader', 'showModal', 'closeModal'),
        componentLayer('presetDetailReader', 'showMobileDetailView', 'closeMobileDetailView'),
        componentLayer('presetDetailReader', 'showMobileSidebar'),
        componentLayer('presetDetailReader', 'showMobileMoreMenu', null, () =>
          !readComponent('presetDetailReader', 'showMobileDetailView')),
        componentLayer("wiEditor", "showFullScreenWI", "requestCloseEditor"),
        componentLayer("wiEditor", "showWiSortMenu"),
        componentLayer('wi-editor-tools', 'showWiEditorToolsMenu', null, () =>
          !!readComponent('wiEditor', 'showFullScreenWI') &&
          readComponent('wiEditor', 'wiEditorActionRailMode') === 'compact'),
        componentLayer("wiEditor", "showFindReplaceModal", "closeFindReplaceModal"),
        componentLayer("wiEditor", "showTaggedImportModal", "closeTaggedImportModal"),
        componentLayer("wiEditor", "showEntryHistoryModal"),
        componentLayer("wiEditor", "showHelpModal"),
        componentLayer("presetEditor", "showPresetEditor", "closeEditor"),
        componentLayer("presetEditor", "showMobileSidebar", "closeMobileSidebar"),
        componentLayer("presetEditor", "showMobilePromptDetailView", "closeMobilePromptDetailView"),
        componentLayer("presetEditor", "showMobileHeaderMoreMenu"),
        componentLayer('presetVersionMergeModal', 'showModal', 'close'),
        componentLayer('worldbookUpdate', 'show', 'close'),
        componentLayer('rollbackModal', 'showRollbackModal'),
        componentLayer('tagFilterModal', 'showTagFilterModal', 'requestCloseModal'),
        componentLayer('tagFilterModal', 'isGovernanceDrawerOpen', 'closeGovernanceDrawer', () =>
          store.deviceType !== 'mobile'),
        componentLayer('tagFilterModal', 'isMobileToolsOpen', 'closeMobileTools'),
        componentLayer('tagFilterModal', 'isWorkspaceHelpOpen', 'closeWorkspaceHelp'),
        componentLayer('batchTagModal', 'showBatchTagModal'),
        componentLayer('folderOperations', 'showCreateFolder'),
        componentLayer('folderOperations', 'folderRenameModal.visible'),
        componentLayer('folderOperations', 'folderCreateSubModal.visible'),
        componentLayer('importModal', 'showImportUrlModal'),
        componentLayer('importModal', 'categoryMenuOpen'),
        componentLayer('moveCardsModal', 'showMoveCardsModal'),
        componentLayer('moveCardsModal', 'categoryMenuOpen'),
        componentLayer('executeRulesMobileModal', 'showExecuteRulesModal'),
        componentLayer('automationModal', 'showAutomationModal', 'closeModal'),
        componentLayer('automationModal', 'showMobileSidebar'),
        componentLayer('automationModal', 'openActionMenuKey', 'closeActionMenu'),
        componentLayer('automationModal', 'showHelpModal', 'closeHelpModal'),
        componentLayer('automationModal', 'showCreateModal', 'closeCreateModal'),
        componentLayer('automationModal', 'showConfirmModal', 'cancelConfirmation'),
        componentLayer('batchImportModal', 'showBatchImportModal', 'cancelImport'),
        componentLayer('batchImportModal', 'openConflictActionKey', 'closeConflictActionMenu',
          () => true, value => value != null),
        componentLayer('forumThreadPreview', 'visible', 'close'),
        componentLayer('sourceUpdateMonitor', 'visible', 'close'),
        componentLayer('pluginJobPanel', 'showPluginJobPanel', 'close'),
        // 右键 / 长按菜单：组件不在 layout 作用域内，通过既有事件收口。
        componentLayer("advancedEditor", "showAdvancedModal", "requestClose"),
        componentLayer("advancedEditor", "showMobileSidebar"),
        componentLayer('advancedEditor', 'showDeleteConfirm', 'cancelDeleteConfirmation'),
        componentLayer("largeEditor", "showLargeEditor"),
        componentLayer("largeEditor", "showMarkdownModal"),
        componentLayer("largeEditor", "showLargePreview"),
        componentLayer('header', 'showMobileMenu', 'closeMobileMenu'),
        componentLayer('header-batch-actions', 'showBatchActionsMenu', null, () =>
          store.deviceType !== 'mobile' && !!store.viewState?.selectedIds?.length),
        componentLayer('header-batch-actions', 'showSourceUpdateMenu', null, () =>
          store.deviceType !== 'mobile' && !!store.viewState?.selectedIds?.length),
        componentLayer('header-batch-actions', 'showRuleMenu', null, () =>
          store.deviceType !== 'mobile' && !!store.viewState?.selectedIds?.length &&
          !!readComponent('header-batch-actions', 'showBatchActionsMenu')),
        componentLayer('header', 'activePluginBatchGroup', 'closePluginBatchGroup', () =>
          store.deviceType !== 'mobile' && !!store.viewState?.selectedIds?.length &&
          !!readComponent('header-batch-actions', 'showBatchActionsMenu')),
        {
          key: "context-menu",
          isActive: () => readComponent("contextMenu", "visible") === true,
          close: () => {
            window.dispatchEvent(new CustomEvent("hide-context-menu"));
          },
        },
        // 设置弹窗（最上层）：复用 Escape 的子层顺序与未保存确认。
        {
          key: "settings-modal",
          isActive: () => !!store.showSettingsModal,
          close: () => {
            window.dispatchEvent(
              new CustomEvent("settings:request-close", {
                detail: { reason: "back-gesture" },
              }),
            );
          },
        },
        componentLayer('pluginManager', 'updateConfirm', 'cancelUpdateConfirm'),
        componentLayer('commandPalette', 'open', 'close'),
      ];

      const disposers = layers.map((layer) => registerViewLayer(layer));

      // 工作区：非默认模式时返回默认模式
      const disposeBridge = installHostBridge({
        getMode: () => store.currentMode,
        getHomeMode: () => "cards",
        setMode: (mode) => this.switchMode(mode),
      });

      this._disposeBackGestureSupport = () => {
        disposers.forEach((fn) => fn());
        disposeBridge();
      };
    },

    syncSidebarForDeviceChange(previousDeviceType, nextDeviceType) {
      const global = this.$store.global;
      if (!global || previousDeviceType === nextDeviceType) return;

      if (nextDeviceType === "mobile") {
        global.visibleSidebar = false;
        document.body.style.overflow = "";
        return;
      }

      if (previousDeviceType === "mobile") {
        global.visibleSidebar = true;
        document.body.style.overflow = "";
      }
    },

    handleBackgroundClick(e) {
      // 检查点击目标是否是卡片本身或按钮，如果不是，则清空
      if (
        !e.target.closest(".st-card") &&
        !e.target.closest("button") &&
        !e.target.closest(".clickable-area")
      ) {
        this.selectedIds = []; // 清空 Store
      }
    },

    // 切换模式 (Cards / WorldInfo)
    switchMode(mode) {
      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
      }

      this.$store.global.currentMode = mode;
      this.selectedIds = []; // 清空选中
      this.$store.global.viewState.lastSelectedId = null;
      window.dispatchEvent(
        new CustomEvent("cancel-marquee-selection", {
          detail: { restoreSelection: false },
        }),
      );

      // 切换到非卡片模式时，清除过滤条件
      if (
        mode !== "cards" &&
        mode !== "worldinfo" &&
        mode !== "chats" &&
        mode !== "beautify"
      ) {
        this.$store.global.viewState.searchQuery = "";
        this.$store.global.viewState.filterTags = [];
        this.$store.global.viewState.excludedTags = [];
        this.$store.global.viewState.filterCategory = "";
        this.$store.global.viewState.favFilter = "none";
      }

      // 触发数据加载 (通过事件通知 Grid 组件)
      if (mode === "worldinfo") {
        window.dispatchEvent(new CustomEvent("refresh-wi-list"));
      } else if (mode === "chats") {
        window.dispatchEvent(new CustomEvent("refresh-chat-list"));
      } else if (mode === "beautify") {
        window.dispatchEvent(new CustomEvent("refresh-beautify-list"));
      } else {
        window.dispatchEvent(new CustomEvent("refresh-card-list"));
      }
    },

    // === 全局拖拽逻辑 ===

    handleGlobalDragEnd() {
      this.dragCounter = 0;
      this.draggedFolder = null;
      this.dragOverCat = null;
      this.dragOverMain = false;
      this.draggedCards = [];

      // 清理 DOM 类名
      document
        .querySelectorAll(".drag-source")
        .forEach((el) => el.classList.remove("drag-source"));
      document
        .querySelectorAll(".drag-over")
        .forEach((el) => el.classList.remove("drag-over"));

      if (window.dragImageElement) {
        if (window.dragImageElement.parentNode)
          window.dragImageElement.parentNode.removeChild(
            window.dragImageElement,
          );
        window.dragImageElement = null;
      }
    },

    // 根容器拖拽进入 (显示遮罩)
    handleDragEnterRoot(e) {
      this.dragCounter++;
    },

    // 根容器拖拽离开
    handleDragLeaveRoot(e) {
      this.dragCounter--;
      if (this.dragCounter <= 0) {
        this.dragCounter = 0;
        // 注意：这里通常不清除 dragOverMain，因为它由 main area 控制
        // 但可以清除一些全局的高亮
        this.dragOverCat = null;
      }
    },

    // 根容器拖拽悬停 (处理侧边栏根目录高亮)
    handleDragOverRoot(e) {
      e.preventDefault();
      e.stopPropagation();

      // 检查拖拽类型是否匹配
      const isCard = e.dataTransfer.types.includes("application/x-st-card");
      const isFolder = !!this.draggedFolder;
      const isFile = e.dataTransfer.files.length > 0;

      if (isCard || isFolder || isFile) {
        // 如果鼠标悬停在“全部卡片”区域 (需要配合 HTML 绑定)
        // 这里逻辑由 Sidebar HTML 中的 @dragover 触发具体赋值
        // 此函数主要作为兜底 preventDefault
      }
    },

    // 根容器放下 (Drop)
    handleDropOnRoot(e) {
      e.preventDefault();
      e.stopPropagation();

      this.dragOverCat = null;
      this.dragOverMain = false;

      // 1. 卡片拖拽 -> 根目录
      if (this.draggedCards.length > 0) {
        const count = this.draggedCards.length;
        if (confirm(`移动 ${count} 张卡片到根目录?`)) {
          moveCard({ card_ids: this.draggedCards, target_category: "" }).then(
            (res) => {
              if (res.success) {
                if (res.category_counts)
                  this.$store.global.categoryCounts = res.category_counts;
                window.dispatchEvent(new CustomEvent("refresh-card-list"));
              } else alert(res.msg);
            },
          );
        }
      }
      // 2. 文件夹 -> 根目录
      else if (this.draggedFolder) {
        const sourceName = this.draggedFolder.split("/").pop();
        if (confirm(`移动文件夹 "${sourceName}" 到根目录?`)) {
          moveFolder({
            source_path: this.draggedFolder,
            target_parent_path: "",
            merge_if_exists: false,
          }).then((res) => {
            if (res.success)
              window.dispatchEvent(new CustomEvent("refresh-folder-list"));
            else alert(res.msg);
          });
        }
      }
      // 3. 外部文件
      else if (e.dataTransfer.files.length > 0) {
        window.dispatchEvent(
          new CustomEvent("handle-files-drop", {
            detail: { event: e, category: "" },
          }),
        );
      }

      this.handleGlobalDragEnd();
    },

    // 仅处理主视图区域的遮罩状态 (由 grid_cards.html 调用)
    handleMainDragEnter(e) {
      this.dragCounter++;
      this.dragOverMain = true;
    },

    handleMainDragLeave(e) {
      this.dragCounter--;
      if (this.dragCounter <= 0) {
        this.dragCounter = 0;
        this.dragOverMain = false;
      }
    },
  };
}
