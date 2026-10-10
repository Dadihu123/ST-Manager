/**
 * static/js/components/entryDock.js
 * 入口坞（设计文档 D6 / 阶段 5）。
 *
 * 这是 `entries` 契约的**第一个消费者**，也是地基的验收装置：没有坞，插件声明的
 * 入口就没有落地的地方，也就无法端到端验证契约真的可用。
 *
 * 设计要点：
 * - 位置：`position: fixed; right: 0; top: 64px; bottom: 64px`，避开在流顶栏与
 *   翻页栏（`layout.css` 的顶栏与 `.pagination-bar`）。
 * - 收起态 8px 热区（`opacity: 0` 但 `pointer-events: auto`），展开态 56px 图标列。
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
    if (!raw) return { expanded: false, side: "right" };
    const parsed = JSON.parse(raw);
    return {
      expanded: Boolean(parsed && parsed.expanded),
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
      };
      window.addEventListener("resize", this._resizeHandler);

      this.ready = true;
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
      if (this._hoverTimer) clearTimeout(this._hoverTimer);
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
    },

    // ------------------------------------------------------------ 展开/收起

    expand() {
      if (this.deviceType === "mobile") return;
      this.expanded = true;
      writePrefs({ expanded: true });
    },

    collapse() {
      this.expanded = false;
      this.overflowOpen = false;
      writePrefs({ expanded: false });
    },

    toggle() {
      return this.expanded ? this.collapse() : this.expand();
    },

    onHotzoneEnter() {
      if (this.deviceType !== "desktop") return;
      if (this._hoverTimer) clearTimeout(this._hoverTimer);
      this._hoverTimer = setTimeout(() => this.expand(), HOVER_EXPAND_DELAY_MS);
    },

    onHotzoneLeave() {
      if (this._hoverTimer) {
        clearTimeout(this._hoverTimer);
        this._hoverTimer = null;
      }
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

    // ------------------------------------------------------------ 溢出菜单

    toggleOverflow() {
      this.overflowOpen = !this.overflowOpen;
      if (this.overflowOpen) {
        this.$nextTick?.(() => {
          const input = this.$refs?.overflowSearch;
          if (input && typeof input.focus === "function") input.focus();
        });
      }
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
