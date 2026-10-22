/**
 * static/js/components/entryDock.js
 * 入口坞（设计文档 §4.4.4 / §5.1 / D6 的 v3 实现）。
 *
 * 坞是插件贡献里 `dock` 落点的宿主渲染器，也是「插件 UI 能不能落地」的验收装置。
 *
 * 设计要点：
 * - 位置：`position: fixed; right: 0; top: 64px; bottom: 64px` 的一条**不可见**
 *   定位带，避开在流顶栏与翻页栏（`layout.css` 的顶栏与 `.pagination-bar`）。
 * - 收起态（默认）：右边缘垂直居中一枚毛玻璃小箭头，坞不占内容区宽度。
 * - 展开态：箭头左侧弹出毛玻璃浮层，**高度随入口数量自适应**。
 * - 坞内槽位只显示图标，名称走 `title` tooltip 与 `aria-label`。
 * - 悬停箭头停留 150ms 自动展开；点击箭头显式开合（收起会取消挂起的悬停展开）。
 * - 根元素带 `data-marquee-ignore`，框选不会命中坞。
 * - 键盘：`role="toolbar"` + `aria-orientation="vertical"` + roving tabindex，
 *   `ArrowUp/Down` 移动、`Enter` 打开。
 * - 移动端不渲染侧条，退化为顶栏按钮 + 底部 sheet。
 *
 * 状态来源：`ContributionRegistry.dockItems()` / `dockOverflow()`。
 * 排序由注册表决定（`order → pluginId → id`），坞**不再维护** pinned / hidden /
 * order / 拖拽 —— 那是 v2 的入口布局偏好，v3 由插件 `order` + 宿主容量裁剪决定。
 * 全局 8 / 每插件 2 的上限也由注册表统一裁剪（§4.4.4），坞只负责渲染。
 */

import { ContributionRegistry } from "../contributionRegistry.js";
import { icon } from "../uiPrimitives.js";

const DOCK_ROOT_ID = "entry-dock-root";
const DOCK_PREFS_KEY = "st_manager_entry_dock_prefs";

/** 展开触发：hover 停留 150ms 或点击热区。 */
const HOVER_EXPAND_DELAY_MS = 150;

function readPrefs() {
  try {
    const raw = localStorage.getItem(DOCK_PREFS_KEY);
    // 首次运行（无偏好）默认**收起**：收起态现在是右边缘一枚常驻可见、
    // 垂直居中的毛玻璃箭头，可发现性由箭头自己承担，不再需要靠展开状态
    // 才能被看见。默认收起同时保证坞不占用内容区宽度。
    if (!raw) return { expanded: false, side: "right" };
    const parsed = JSON.parse(raw);
    return {
      expanded: parsed && parsed.expanded === undefined ? false : Boolean(parsed.expanded),
      side: parsed && parsed.side === "left" ? "left" : "right",
    };
  } catch (error) {
    return { expanded: false, side: "right" };
  }
}

function writePrefs(patch) {
  try {
    localStorage.setItem(DOCK_PREFS_KEY, JSON.stringify({ ...readPrefs(), ...patch }));
  } catch (error) {
    console.warn("[entryDock] 保存坞偏好失败:", error);
  }
}

export default function entryDock() {
  return {
    ready: false,
    /** 坞内槽位（注册表按全局 8 / 每插件 2 裁剪后的结果）。 */
    slots: [],
    /** 溢出菜单条目（未进槽位但仍可用的 dock 贡献）。 */
    overflow: [],
    /** 槽位 + 溢出的全部 dock 贡献（移动端 sheet / 数量标用）。 */
    entries: [],
    overflowOpen: false,
    overflowQuery: "",
    /** 打开溢出菜单的那次点击事件；`@click.outside` 必须忽略它（见 closeOverflow）。 */
    _overflowOpenedByEvent: null,
    expanded: false,
    deviceType: "desktop",
    activeKey: "",

    _hoverTimer: null,
    _entriesHandler: null,

    init() {
      if (typeof window === "undefined") return;

      const prefs = readPrefs();
      this.expanded = prefs.expanded;
      this.deviceType = this.resolveDeviceType();

      this.refresh();

      // 贡献注册表变更 → 重新渲染（插件加载 / 禁用 / 配置变更都会触发）
      this._entriesHandler = () => this.refresh();
      window.addEventListener("contributions:changed", this._entriesHandler);
      window.addEventListener("plugins:loaded", this._entriesHandler);

      // 设备类型变化（平板默认收起且不自动展开）
      this._resizeHandler = () => {
        const next = this.resolveDeviceType();
        if (next === this.deviceType) return;
        this.deviceType = next;
        if (next !== "desktop") this.collapse();
        this.syncMobileDockedClass();
      };
      window.addEventListener("resize", this._resizeHandler);

      this.syncMobileDockedClass();
      this.ready = true;
    },

    /**
     * 在 `<body>` 上同步 `entry-dock-mobile-docked`：移动端底部箭头可见时为真。
     *
     * 用途：`.pagination-bar` 需要为贴在其上的箭头让出右侧空间，否则箭头会盖住
     * 「下一页」按钮（实测 420px 视口下翻页控件右边缘 404px 正好顶满栏内容区）。
     *
     * ⚠️ 为什么用 JS 挂类而不是 CSS `:has(.entry-dock-mobile-trigger)`：
     * `:has()` 只看元素**是否存在于 DOM**，不看可见性；模板里箭头是
     * `<template x-if="deviceType === 'mobile'">` 包着的，Alpine 一旦克隆它就常驻，
     * `x-show="hasEntries"` 只切 `display` —— 于是「一个入口都没有」时
     * `:has()` 依然成立，翻页栏会白白留出一段空隙。本仓在坞的遮挡规则上
     * 已经踩过同一个坑（见设计文档 §7.1「遮挡处理」）。
     */
    syncMobileDockedClass() {
      if (typeof document === "undefined") return;
      // 某些宿主/测试环境只有残缺的 document 存根（没有 body）
      if (!document.body || !document.body.classList) return;
      const docked = this.deviceType === "mobile" && this.hasEntries;
      document.body.classList.toggle("entry-dock-mobile-docked", docked);
    },

    destroy() {
      if (typeof window === "undefined") return;
      if (this._entriesHandler) {
        window.removeEventListener("contributions:changed", this._entriesHandler);
        window.removeEventListener("plugins:loaded", this._entriesHandler);
        this._entriesHandler = null;
      }
      if (this._resizeHandler) {
        window.removeEventListener("resize", this._resizeHandler);
        this._resizeHandler = null;
      }
      this.cancelHoverTimer();
      // 组件销毁时摘掉 body 上的停靠类，否则翻页栏会永远留一段空隙
      if (typeof document !== "undefined" && document.body && document.body.classList) {
        document.body.classList.remove("entry-dock-mobile-docked");
      }
    },

    /** 与 `layout.js:reDeviceType()` 同一套断点，保证坞与侧栏判定一致。 */
    resolveDeviceType() {
      const width = window.innerWidth || document.documentElement?.clientWidth || 0;
      if (width > 0) {
        if (width < 900) return "mobile";
        if (width < 1180) return "tablet";
        return "desktop";
      }
      const ua = navigator.userAgent || "";
      if (/iPad|Android/.test(ua) && !/Mobile/.test(ua)) return "tablet";
      if (/Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/.test(ua)) return "mobile";
      return "desktop";
    },

    /** 贡献节点的稳定键（注册表给 `key`；回退到 `pluginId:id`）。 */
    entryKey(node) {
      if (!node) return "";
      if (node.key) return String(node.key);
      return `${String(node.pluginId || "")}:${String(node.id || "")}`;
    },

    /**
     * 把注册表节点归一成坞渲染需要的形态。
     *
     * - `enabled`：`when` 通过且未被插件 `update` 关掉；置灰项仍要渲染（D7）。
     * - `progress`：设计 §4.4.5 是 0–1 比例，这里原样保留，渲染时归一成百分比。
     */
    normalizeNode(node) {
      if (!node || typeof node !== "object") return null;
      if (node.type === "separator") return null;
      return {
        ...node,
        key: this.entryKey(node),
        label: String(node.label || node.id || ""),
        enabled: node.enabled !== false && node.ok !== false,
      };
    },

    refresh() {
      try {
        const slots = Array.isArray(ContributionRegistry.dockItems())
          ? ContributionRegistry.dockItems()
          : [];
        const overflow = Array.isArray(ContributionRegistry.dockOverflow())
          ? ContributionRegistry.dockOverflow()
          : [];
        this.slots = slots.map((node) => this.normalizeNode(node)).filter(Boolean);
        this.overflow = overflow.map((node) => this.normalizeNode(node)).filter(Boolean);
      } catch (error) {
        console.warn("[entryDock] 读取 dock 贡献失败:", error);
        this.slots = [];
        this.overflow = [];
      }
      this.entries = [...this.slots, ...this.overflow];
      if (!this.entries.some((entry) => entry.key === this.activeKey)) this.activeKey = "";
      this.syncMobileDockedClass();
    },

    /**
     * 坞里是否有任何东西可展示（槽位或溢出菜单里的入口）。
     *
     * 宿主内建命令（kill switch 等）不是 dock 贡献，**不进坞**——`dockItems()` /
     * `dockOverflow()` 都只取 `dock` 落点。所以两者同时为空 ⇔ 当前没有插件
     * 声明了 dock 入口，箭头整个不出现。
     */
    get hasEntries() {
      return this.slots.length > 0 || this.overflow.length > 0;
    },

    /** 坞里可见入口数（槽位 + 溢出），用于箭头 / 移动端按钮上的数字标。 */
    get entryCount() {
      return this.entries.length;
    },

    // ------------------------------------------------------------ 展开/收起

    /**
     * 展开。
     *
     * ⚠️ 这里**不能**写 `if (this.deviceType === "mobile") return;`。
     * 移动端的顶栏按钮走的是 `toggle()` → `expand()`，同时 `expanded` 又是
     * 底部 sheet 的开关（`x-if="deviceType === 'mobile' && expanded"`）。
     * 旧实现在这里对 mobile 提前 return，顶栏按钮因此永远打不开 sheet。
     *
     * hover 展开（真正的误触来源）在 `onHotzoneEnter()` 里按 deviceType 判断，
     * 那里才是该拦的地方。
     */
    expand() {
      this.expanded = true;
      writePrefs({ expanded: true });
    },

    collapse() {
      // ⚠️ 必须先取消挂起的 hover 展开定时器。
      // 收起态下指针要移到箭头上去点「收起」，这个进入动作会重新排一次 150ms
      // 的展开定时器；不清掉的话，用户点击收起后 150ms 坞又自己弹开 ——
      // 实测症状就是「点了收起没反应」。
      this.cancelHoverTimer();
      this.expanded = false;
      this.overflowOpen = false;
      writePrefs({ expanded: false });
    },

    toggle() {
      return this.expanded ? this.collapse() : this.expand();
    },

    /** 取消挂起的 hover 展开（收起、离开热区、销毁时都要调用）。 */
    cancelHoverTimer() {
      if (this._hoverTimer) {
        clearTimeout(this._hoverTimer);
        this._hoverTimer = null;
      }
    },

    onHotzoneEnter() {
      if (this.deviceType !== "desktop") return;
      this.cancelHoverTimer();
      this._hoverTimer = setTimeout(() => {
        this._hoverTimer = null;
        this.expand();
      }, HOVER_EXPAND_DELAY_MS);
    },

    onHotzoneLeave() {
      this.cancelHoverTimer();
    },

    // ------------------------------------------------------------ 打开贡献

    /** 坞的贡献上下文（§5.1：dock 落点 `{mode, selection}`，没有 target）。 */
    contributionContext() {
      let mode = "";
      let ids = [];
      try {
        mode = String(ContributionRegistry.context().mode || "");
      } catch (error) {
        mode = "";
      }
      try {
        const store = this.$store && this.$store.global;
        const viewState = (store && store.viewState) || {};
        if (!mode && store && store.currentMode) mode = String(store.currentMode);
        ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
      } catch (error) {
        ids = [];
      }
      return {
        mode,
        target: null,
        selection: {
          mode: ids.length === 0 ? "none" : ids.length > 1 ? "multi" : "single",
          ids: ids.map((id) => String(id)).filter(Boolean),
        },
      };
    },

    /**
     * 打开一个 dock 贡献：统一派发 `contribution:trigger`（S4）。
     *
     * 渲染层不知道 surface / command 的区别——由运行时按节点 `action` 分派。
     * 置灰项不执行，改用 `onDisabledClick` 引导到插件配置（D7：不是无反应）。
     */
    open(node) {
      const item = typeof node === "string" ? this.entries.find((entry) => entry.key === node) : node;
      if (!item || item.enabled === false) return false;

      window.dispatchEvent(
        new CustomEvent("contribution:trigger", {
          detail: {
            pluginId: String(item.pluginId || ""),
            nodeId: String(item.id || ""),
            trigger: "dock",
            ctx: this.contributionContext(),
          },
        }),
      );
      this.activeKey = item.key;
      return true;
    },

    // ------------------------------------------------------------ 溢出菜单

    /**
     * 开合溢出菜单。
     *
     * ⚠️ 必须把**打开菜单的那次点击事件**记下来（`_overflowOpenedByEvent`），
     * 交给 `closeOverflow()` 去忽略它。原因见 `closeOverflow()` 的注释。
     */
    toggleOverflow(event) {
      if (this.overflowOpen) {
        this.closeOverflow();
        return;
      }

      this._overflowOpenedByEvent = event || null;
      this.overflowOpen = true;
      this.$nextTick?.(() => {
        const input = this.$refs?.overflowSearch;
        if (input && typeof input.focus === "function") input.focus();
      });
    },

    /**
     * 关闭溢出菜单（`@click.outside` 与 Escape 都走这里）。
     *
     * ⚠️ 这里必须忽略「打开菜单的那一次点击」，否则菜单**根本打不开**。
     *
     * 机制（已在真实 Chromium 里逐帧确认）：
     * 1. 用户点 `⋯`，点击事件 E 开始派发；
     * 2. Alpine 的 `@click` 先把 `overflowOpen` 置为 true，响应式副作用随即
     *    把 `.entry-overflow` 插入 DOM，并给它挂上 document 级的
     *    `@click.outside` 监听器；
     * 3. 此时 E **仍在冒泡**。按 DOM 规范，「派发过程中新注册的监听器」会对
     *    尚未访问到的祖先节点生效 —— 于是这个刚挂上的 `@click.outside`
     *    在同一轮派发里收到 E，发现 target 不在菜单内，立刻把菜单关掉。
     *
     * 实测症状：点 `⋯` 后 `overflowOpen` 在同一帧内 true→false，
     * DOM 里 `.entry-overflow` 数量始终为 0，即菜单闪都不闪一下。
     *
     * 修法选择：**事件身份守卫**，而不是在按钮上加 `@click.stop`。
     * `stopPropagation` 会让这次点击再也到不了 document，从而连带破坏仓库里
     * 「点任意处关闭其它浮层」的既有约定（如 `contextMenu.js:83` 的全局监听）。
     * 守卫只精确跳过"我们自己那一次"点击，其余行为完全不变。
     */
    closeOverflow(event) {
      if (event && event === this._overflowOpenedByEvent) return;
      this._overflowOpenedByEvent = null;
      this.overflowOpen = false;
    },

    get filteredOverflow() {
      const query = String(this.overflowQuery || "").trim().toLowerCase();
      if (!query) return this.overflow;
      return this.overflow.filter((entry) => {
        const haystack = `${entry.label} ${entry.description} ${entry.pluginId}`.toLowerCase();
        return haystack.includes(query);
      });
    },

    /** 按插件分组（溢出菜单的呈现方式）。 */
    get overflowGroups() {
      const groups = new Map();
      for (const entry of this.filteredOverflow) {
        if (!groups.has(entry.pluginId)) {
          groups.set(entry.pluginId, { pluginId: entry.pluginId, items: [] });
        }
        groups.get(entry.pluginId).items.push(entry);
      }
      return Array.from(groups.values());
    },

    // ------------------------------------------------------------ 键盘

    /** roving tabindex：只有当前项可 Tab 到达。 */
    tabIndexFor(entry) {
      if (!this.slots.length) return -1;
      const active = this.activeKey || this.slots[0].key;
      return entry.key === active ? 0 : -1;
    },

    handleKeydown(event) {
      const items = this.slots;
      if (!items.length) return;

      const currentIndex = Math.max(
        0,
        items.findIndex((entry) => entry.key === (this.activeKey || items[0].key)),
      );

      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const offset = event.key === "ArrowDown" ? 1 : -1;
        const next = (currentIndex + offset + items.length) % items.length;
        this.activeKey = items[next].key;
        this.focusActive();
        return;
      }

      if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        this.activeKey = (event.key === "Home" ? items[0] : items[items.length - 1]).key;
        this.focusActive();
        return;
      }

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.open(items[currentIndex]);
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        this.collapse();
      }
    },

    focusActive() {
      this.$nextTick?.(() => {
        const key = this.activeKey;
        if (!key) return;
        const node = document.querySelector(`[data-entry-key="${CSS.escape(key)}"]`);
        if (node && typeof node.focus === "function") node.focus();
      });
    },

    // ------------------------------------------------------------ 呈现辅助

    /** 图标取值：宿主图标名，或插件内资源路径（含 `/`，设计文档 2.2）。 */
    iconHref(entry) {
      const name = String((entry && entry.icon) || "").trim();
      if (!name) return "";
      return name;
    },

    /** 图标节点。资源路径需要 `pluginId` 才能解析成 `/api/plugins/<id>/assets/…`。 */
    buildIcon(entry) {
      return icon(this.iconHref(entry) || "circle-dot", {
        className: "ui-icon--sm",
        pluginId: String((entry && entry.pluginId) || ""),
      });
    },

    badgeText(entry) {
      const value = entry && entry.badge;
      if (value === null || value === undefined || value === "") return "";
      if (typeof value === "object") {
        return String(value.text ?? value.inner ?? value.value ?? "");
      }
      return String(value);
    },

    /**
     * 进度文案：设计 §4.4.5 的 `progress` 是 **0–1 比例**；同时兼容
     * `{done,total}` 旧形态（宿主内部面板用后者）。
     */
    progressText(entry) {
      const progress = entry && entry.progress;
      if (progress === null || progress === undefined) return "";
      if (typeof progress === "number") {
        if (!Number.isFinite(progress)) return "";
        return `${Math.max(0, Math.min(100, Math.round(progress * 100)))}%`;
      }
      if (typeof progress === "object") {
        const total = Number(progress.total || 0);
        if (!Number.isFinite(total) || total <= 0) return "";
        return `${Number(progress.done || 0)}/${total}`;
      }
      return "";
    },

    /** 节点状态类名（`idle` / `running` / `error`…，设计 §4.4.5）。 */
    statusClass(entry) {
      const raw = entry && entry.status;
      const status = typeof raw === "string" ? raw : String((raw && raw.kind) || "idle");
      return `is-${status}`;
    },

    /** 置灰项的悬浮说明（可见但不可点，给原因）。 */
    menuNodeHint(entry) {
      if (!entry) return "";
      return String(entry.disabledHint || entry.description || "");
    },

    /** 置灰项点击时跳到该插件的配置/密钥区（D7：不是无反应）。 */
    onDisabledClick(entry) {
      if (!entry) return;
      window.dispatchEvent(
        new CustomEvent("open-settings-section", {
          detail: { section: "plugins", anchor: `plugin-config-${entry.pluginId}` },
        }),
      );
    },
  };
}
