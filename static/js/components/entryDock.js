/**
 * static/js/components/entryDock.js
 * 入口坞（设计文档 D6 / 阶段 5）。
 *
 * 这是 `entries` 契约的**第一个消费者**，也是地基的验收装置：没有坞，插件声明的
 * 入口就没有落地的地方，也就无法端到端验证契约真的可用。
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
 *   `ArrowUp/Down` 移动、`Enter` 打开、`Delete` 取消固定。
 * - 移动端不渲染侧条，退化为顶栏按钮 + 底部 sheet。
 * - 平板默认收起且不自动展开。
 *
 * 状态来源：`EntryRegistry`（条目）+ `ui_data._entry_layout_v1`（偏好）。
 */

import { EntryRegistry } from "../entryRegistry.js";
import { PluginSurfaceHost } from "../pluginSurfaceHost.js";
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
    entries: [],
    slots: [],
    overflow: [],
    overflowOpen: false,
    overflowQuery: "",
    /** 打开溢出菜单的那次点击事件；`@click.outside` 必须忽略它（见 closeOverflow）。 */
    _overflowOpenedByEvent: null,
    expanded: false,
    deviceType: "desktop",
    activeKey: "",

    /** 拖拽重排状态（D6：坞槽位顺序可调，写入 `layout.order`）。 */
    draggingKey: "",
    dragOverKey: "",

    _hoverTimer: null,
    _entriesHandler: null,

    init() {
      if (typeof window === "undefined") return;

      const prefs = readPrefs();
      this.expanded = prefs.expanded;
      this.deviceType = this.resolveDeviceType();

      this.refresh();

      // 注册表变更 → 重新渲染（插件加载 / 禁用 / 配置变更都会触发）
      this._entriesHandler = () => this.refresh();
      window.addEventListener("entries:changed", this._entriesHandler);
      window.addEventListener("plugins:loaded", this._entriesHandler);

      // 入口打开请求（命令面板 / 插件 API 也会派发）
      this._openHandler = (event) => {
        const detail = (event && event.detail) || {};
        if (detail.key) this.open(detail.key);
      };
      window.addEventListener("entry:open", this._openHandler);

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
        window.removeEventListener("entries:changed", this._entriesHandler);
        window.removeEventListener("plugins:loaded", this._entriesHandler);
        this._entriesHandler = null;
      }
      if (this._openHandler) {
        window.removeEventListener("entry:open", this._openHandler);
        this._openHandler = null;
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

    refresh() {
      this.slots = EntryRegistry.dockSlots();
      this.overflow = EntryRegistry.overflowEntries();
      this.entries = EntryRegistry.list({ kind: "dock" });
      if (!this.slots.some((entry) => entry.key === this.activeKey)) this.activeKey = "";
      this.syncMobileDockedClass();
    },

    /**
     * 坞里是否有任何东西可展示（槽位或溢出菜单里的入口）。
     *
     * 用来决定「右侧箭头 / 移动端顶栏按钮」要不要出现。宿主内建命令全部是
     * `kind: "command"`（见 `entryRegistry.js` 的 `CORE_ENTRIES`），**不进坞**——
     * `dockSlots()` / `overflowEntries()` 都只取 `kind: "dock"`。所以这两个数组
     * 同时为空 ⇔ 当前没有任何插件声明了 dock 入口。
     *
     * ⚠️ 不能用 `entries.length` 代替：`entries` 是 `list({kind:"dock"})`，
     * 它按设计**排除用户隐藏项**，但**保留 `when` 未满足的置灰项**——后者仍然要
     * 展示（D7：置灰可见 + disabledHint），所以它就是"有没有东西可看"的正解，
     * 与 slots/overflow 同源、不会出现两者不一致的分歧。
     */
    get hasEntries() {
      return this.slots.length > 0 || this.overflow.length > 0;
    },

    /**
     * 当前坞里有几个入口（槽位 + 溢出菜单），供箭头/移动端按钮上的数字标使用。
     *
     * 用 `entries.length`（= `list({kind:"dock"})`）而不是 `slots.length`：
     * `slots` 只含**已固定**的入口（且受 `MAX_DOCK_SLOTS` / 每插件上限裁剪），
     * 社区插件默认进溢出菜单不进槽位 —— 只看 slots 会让「只装了社区插件」时
     * 数字标不显示（实测：`slots=0, overflow=1` 时旧代码的
     * `x-show="slots.length"` 判假，徽标凭空消失，而入口明明有 1 个）。
     *
     * `entries` 已按设计排除用户隐藏项，因此这个数就是「用户看得见的入口数」。
     */
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
     * 之前之所以没暴露，是因为旧默认值是「展开」—— 静默地把 bug 盖住了。
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

    // ------------------------------------------------------------ 打开入口

    /** 打开入口：优先走插件注册的 surface，其次派发事件让宿主自己处理。 */
    open(key) {
      const entry = EntryRegistry.get(String(key || ""));
      if (!entry) return false;

      const surfaceKey = `${entry.pluginId}:${entry.surface && entry.surface.id ? entry.surface.id : entry.id}`;
      if (PluginSurfaceHost.has(surfaceKey)) {
        PluginSurfaceHost.openSurface(surfaceKey, {
          source: "dock",
          targetId: entry.id,
          mode: EntryRegistry.context().mode,
        });
        this.activeKey = entry.key;
        return true;
      }

      // 没有对应 surface：交给插件自己监听（例如 command 类入口）
      window.dispatchEvent(
        new CustomEvent(`entry:activate`, { detail: { key: entry.key, entry } }),
      );
      this.activeKey = entry.key;
      return true;
    },

    // ------------------------------------------------------------ 坞槽位

    /** 用户显式固定 / 取消固定（D6：坞槽位是宿主分配的资源）。 */
    async togglePin(entry) {
      if (!entry) return false;
      const pinned = Array.isArray(EntryRegistry.layout.pinned)
        ? [...EntryRegistry.layout.pinned]
        : [];
      const unpinned = Array.isArray(EntryRegistry.layout.unpinned)
        ? [...EntryRegistry.layout.unpinned]
        : [];

      const isPinned = pinned.includes(entry.key);
      let nextPinned = pinned;
      let nextUnpinned = unpinned;

      if (isPinned) {
        nextPinned = pinned.filter((key) => key !== entry.key);
        if (!nextUnpinned.includes(entry.key)) nextUnpinned.push(entry.key);
      } else {
        nextUnpinned = unpinned.filter((key) => key !== entry.key);
        if (!nextPinned.includes(entry.key)) nextPinned.push(entry.key);
      }

      const ok = await EntryRegistry.updateLayout({
        pinned: nextPinned,
        unpinned: nextUnpinned,
      });
      this.refresh();
      return ok;
    },

    async hide(entry) {
      if (!entry) return false;
      const hidden = Array.isArray(EntryRegistry.layout.hidden)
        ? [...EntryRegistry.layout.hidden]
        : [];
      if (!hidden.includes(entry.key)) hidden.push(entry.key);
      const ok = await EntryRegistry.updateLayout({ hidden });
      this.refresh();
      return ok;
    },

    // ------------------------------------------------------------ 拖拽重排
    //
    // D6：坞槽位顺序由用户决定（文档阶段 5 验收清单里的「拖拽重排持久化」）。
    // 用原生 HTML5 拖放，不引第三方库。
    //
    // 顺序写进 `layout.order`（全局键数组）——`EntryRegistry.list()` 排序时
    // **用户显式排序优先于插件建议的 priority**，所以这里只要维护 order 即可。

    onSlotDragStart(entry, event) {
      if (!entry) return;
      this.draggingKey = entry.key;
      // Firefox 要求必须 setData 才会真正开始拖拽
      try {
        event?.dataTransfer?.setData("text/plain", entry.key);
        if (event?.dataTransfer) event.dataTransfer.effectAllowed = "move";
      } catch (error) {
        /* 某些环境禁用 dataTransfer，忽略即可 */
      }
    },

    onSlotDragOver(entry, event) {
      if (!this.draggingKey || !entry || entry.key === this.draggingKey) return;
      event?.preventDefault?.();
      this.dragOverKey = entry.key;
      if (event?.dataTransfer) event.dataTransfer.dropEffect = "move";
    },

    onSlotDragLeave(entry) {
      if (entry && this.dragOverKey === entry.key) this.dragOverKey = "";
    },

    onSlotDragEnd() {
      this.draggingKey = "";
      this.dragOverKey = "";
    },

    /**
     * 放下：把被拖的槽位插到目标槽位的位置。
     *
     * `layout.order` 是**全局**顺序（含溢出菜单里的入口），所以要在完整顺序里
     * 搬移，而不是只重排当前可见的坞槽位——否则拖一次会把没进坞的入口顺序打乱。
     */
    async onSlotDrop(targetEntry, event) {
      event?.preventDefault?.();
      const sourceKey = String(this.draggingKey || "");
      const targetKey = String((targetEntry && targetEntry.key) || "");
      this.onSlotDragEnd();

      if (!sourceKey || !targetKey || sourceKey === targetKey) return false;

      const current = Array.isArray(EntryRegistry.layout.order)
        ? [...EntryRegistry.layout.order]
        : [];

      // 完整顺序 = 用户已排序的 + 未出现的（按注册表当前顺序补齐）
      const known = new Set(current);
      for (const item of EntryRegistry.searchable()) {
        if (!known.has(item.key)) {
          current.push(item.key);
          known.add(item.key);
        }
      }

      const from = current.indexOf(sourceKey);
      const to = current.indexOf(targetKey);
      if (from === -1 || to === -1) return false;

      current.splice(from, 1);
      current.splice(to, 0, sourceKey);

      const ok = await EntryRegistry.updateLayout({ order: current });
      this.refresh();
      return ok;
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
        this.open(items[currentIndex].key);
        return;
      }

      if (event.key === "Delete") {
        event.preventDefault();
        this.togglePin(items[currentIndex]);
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
      return String(value);
    },

    progressText(entry) {
      const progress = entry && entry.progress;
      if (!progress) return "";
      return `${progress.done}/${progress.total}`;
    },

    statusClass(entry) {
      const status = String((entry && entry.status) || "idle");
      return `is-${status}`;
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
