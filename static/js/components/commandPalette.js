/**
 * static/js/components/commandPalette.js
 * 命令面板（设计文档 阶段 5）。
 *
 * 搜索范围 = **全部注册表条目 + 宿主内建命令**（`EntryRegistry.searchable()`），
 * 因此插件声明的 `command` / `dock` / `nav` 等入口自动进入面板，不需要插件
 * 自己实现任何 UI。
 *
 * 快捷键：`Ctrl/Cmd+K`（全仓 grep 确认零占用）。
 *
 * 与坞的关系：坞是「固定入口的常驻位置」，面板是「全部入口的检索入口」。
 * 两者都只是 `EntryRegistry` 的消费者——这就是地基该有的样子。
 */

import { EntryRegistry, isHostEntryKey } from "../entryRegistry.js";
import { PluginSurfaceHost } from "../pluginSurfaceHost.js";
import { icon } from "../uiPrimitives.js";

const MAX_RESULTS = 40;

/** 宿主内建命令的键 → 实际动作。 */
const CORE_ACTIONS = {
  "core:open-settings": () => {
    const store = window.Alpine && window.Alpine.store("global");
    if (store) store.showSettingsModal = true;
  },
  "core:open-plugin-manager": () => {
    const store = window.Alpine && window.Alpine.store("global");
    if (store) store.showSettingsModal = true;
    window.dispatchEvent(
      new CustomEvent("open-settings-section", {
        detail: { section: "plugins", anchor: "plugin-panel-installed" },
      }),
    );
  },
  "core:open-about": () => {
    const store = window.Alpine && window.Alpine.store("global");
    if (store) store.showSettingsModal = true;
    window.dispatchEvent(
      new CustomEvent("open-settings-section", {
        detail: { section: "about", anchor: "settings-about-links" },
      }),
    );
  },
  "core:switch-cards": () => setMode("cards"),
  "core:switch-worldinfo": () => setMode("worldinfo"),
  "core:switch-chats": () => setMode("chats"),
  "core:switch-presets": () => setMode("presets"),
};

function setMode(mode) {
  const store = window.Alpine && window.Alpine.store("global");
  if (store) store.currentMode = mode;
}

export default function commandPalette() {
  return {
    open: false,
    query: "",
    activeIndex: 0,
    items: [],

    _keyHandler: null,
    _entriesHandler: null,

    init() {
      if (typeof window === "undefined") return;

      this._keyHandler = (event) => {
        const isPaletteCombo =
          (event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === "k";
        if (isPaletteCombo) {
          event.preventDefault();
          this.toggle();
          return;
        }
        if (event.key === "Escape" && this.open) {
          event.preventDefault();
          this.close();
          return;
        }
        // 插件入口快捷键（`layout.shortcuts` → `EntryRegistry.findByShortcut`）。
        // 放在最后：不要抢掉面板自己的 Ctrl+K / Escape。
        if (this.handleEntryShortcut(event)) return;
      };
      window.addEventListener("keydown", this._keyHandler);

      this._entriesHandler = () => {
        if (this.open) this.rebuild();
      };
      window.addEventListener("entries:changed", this._entriesHandler);
    },

    /**
     * 匹配并执行插件入口快捷键。
     *
     * 用户在入口总览页给某个入口配的 `layout.shortcuts[combo] = entryKey`，
     * `EntryRegistry.findByShortcut(combo)` 负责查表（含宿主内建入口）。
     *
     * 三条纪律：
     * 1. **不在输入框里触发**——否则打字会把字母当快捷键；
     * 2. 组合键必须**完全匹配**（`Ctrl+Shift+A` 不等于 `Ctrl+A`）；
     * 3. 置灰的入口不执行，但仍给一条提示（D7：不是无反应）。
     *
     * @returns {boolean} 是否已消费该事件。
     */
    handleEntryShortcut(event) {
      if (event.defaultPrevented) return false;
      if (this.isTypingTarget(event.target)) return false;

      const combo = this.shortcutCombo(event);
      if (!combo) return false;

      const entry = EntryRegistry.findByShortcut(combo);
      if (!entry) return false;

      event.preventDefault();

      // 置灰项：不执行，但告诉用户为什么（否则「按了没反应」）
      const record = EntryRegistry.get(entry.key);
      if (record && record.enabled === false) {
        const store = this.$store && this.$store.global;
        if (store && typeof store.showToast === "function") {
          store.showToast(record.disabledHint || `「${record.label}」当前不可用`, 3000);
        }
        return true;
      }

      if (isHostEntryKey(entry.key)) {
        const action = CORE_ACTIONS[entry.key];
        if (typeof action === "function") action();
        return true;
      }

      const surfaceId = entry.surface && entry.surface.id ? entry.surface.id : entry.id;
      const surfaceKey = `${entry.pluginId}:${surfaceId}`;
      if (PluginSurfaceHost.has(surfaceKey)) {
        PluginSurfaceHost.openSurface(surfaceKey, {
          source: "shortcut",
          targetId: entry.id,
          mode: EntryRegistry.context().mode,
        });
        return true;
      }

      window.dispatchEvent(
        new CustomEvent("entry:activate", { detail: { key: entry.key, entry } }),
      );
      return true;
    },

    /** 焦点是否在可输入元素里（此时不该把按键当快捷键）。 */
    isTypingTarget(target) {
      const node = target;
      if (!node || !node.tagName) return false;
      const tag = String(node.tagName).toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return true;
      return Boolean(node.isContentEditable);
    },

    /**
     * 把键盘事件折算成 `layout.shortcuts` 的键名。
     *
     * 规范形如 `Ctrl+Shift+A`：修饰键按 `Ctrl` / `Alt` / `Shift` / `Meta` 的固定顺序，
     * 主键大写（字母）或原名（`F5`、`ArrowUp`、`Escape` 等）。没有任何修饰键时返回空串
     * ——避免把裸字母变成全局快捷键（那会破坏正常输入）。
     */
    shortcutCombo(event) {
      const key = String(event.key || "");
      if (!key || key === "Control" || key === "Alt" || key === "Shift" || key === "Meta") {
        return "";
      }

      const parts = [];
      if (event.ctrlKey) parts.push("Ctrl");
      if (event.altKey) parts.push("Alt");
      if (event.shiftKey) parts.push("Shift");
      if (event.metaKey) parts.push("Meta");

      // 要求至少一个修饰键：裸键不进快捷键表
      if (!parts.length) return "";

      const main = key.length === 1 ? key.toUpperCase() : key;
      parts.push(main);
      return parts.join("+");
    },

    destroy() {
      if (typeof window === "undefined") return;
      if (this._keyHandler) {
        window.removeEventListener("keydown", this._keyHandler);
        this._keyHandler = null;
      }
      if (this._entriesHandler) {
        window.removeEventListener("entries:changed", this._entriesHandler);
        this._entriesHandler = null;
      }
    },

    toggle() {
      return this.open ? this.close() : this.show();
    },

    show() {
      this.open = true;
      this.query = "";
      this.rebuild();
      this.$nextTick?.(() => {
        const input = this.$refs?.paletteInput;
        if (input && typeof input.focus === "function") input.focus();
      });
    },

    close() {
      this.open = false;
      this.query = "";
      this.items = [];
      this.activeIndex = 0;
    },

    rebuild() {
      this.items = this.filter(EntryRegistry.searchable());
      this.activeIndex = 0;
    },

    onQueryInput() {
      this.items = this.filter(EntryRegistry.searchable());
      this.activeIndex = 0;
    },

    /** 简单子串匹配（含中文），按「前缀命中优先、其次标签长度」排序。 */
    filter(candidates) {
      const query = String(this.query || "").trim().toLowerCase();
      const scored = [];

      for (const entry of candidates) {
        const label = String(entry.label || "").toLowerCase();
        const description = String(entry.description || "").toLowerCase();
        const pluginId = String(entry.pluginId || "").toLowerCase();
        const haystack = `${label} ${description} ${pluginId}`;

        if (query && !haystack.includes(query)) continue;

        let score = 0;
        if (query) {
          if (label.startsWith(query)) score = 3;
          else if (label.includes(query)) score = 2;
          else score = 1;
        }
        scored.push({ entry, score });
      }

      scored.sort((left, right) => {
        if (left.score !== right.score) return right.score - left.score;
        const leftLabel = String(left.entry.label || "");
        const rightLabel = String(right.entry.label || "");
        if (leftLabel.length !== rightLabel.length) return leftLabel.length - rightLabel.length;
        return leftLabel.localeCompare(rightLabel);
      });

      return scored.slice(0, MAX_RESULTS).map((item) => item.entry);
    },

    // ------------------------------------------------------------ 键盘

    handleKeydown(event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (this.items.length) {
          this.activeIndex = (this.activeIndex + 1) % this.items.length;
        }
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (this.items.length) {
          this.activeIndex = (this.activeIndex - 1 + this.items.length) % this.items.length;
        }
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        this.activateIndex(this.activeIndex);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
      }
    },

    activateIndex(index) {
      const entry = this.items[index];
      if (!entry) return false;
      return this.activate(entry);
    },

    /** 执行一个入口：宿主内建走内建动作，插件入口走 surface 或事件。 */
    activate(entry) {
      if (!entry) return false;

      if (isHostEntryKey(entry.key)) {
        const action = CORE_ACTIONS[entry.key];
        if (typeof action === "function") action();
        this.close();
        return true;
      }

      const surfaceId = entry.surface && entry.surface.id ? entry.surface.id : entry.id;
      const surfaceKey = `${entry.pluginId}:${surfaceId}`;
      if (PluginSurfaceHost.has(surfaceKey)) {
        PluginSurfaceHost.openSurface(surfaceKey, {
          source: "command",
          targetId: entry.id,
          mode: EntryRegistry.context().mode,
        });
        this.close();
        return true;
      }

      window.dispatchEvent(
        new CustomEvent("entry:activate", { detail: { key: entry.key, entry } }),
      );
      this.close();
      return true;
    },

    // ------------------------------------------------------------ 呈现辅助

    buildIcon(entry) {
      const name = String((entry && entry.icon) || "").trim();
      // 资源路径（含 `/`）需要 pluginId 才能解析（设计文档 2.2 允许两种取值）
      return icon(name || "circle-dot", {
        className: "ui-icon--sm",
        pluginId: String((entry && entry.pluginId) || ""),
      });
    },

    kindLabel(entry) {
      const labels = {
        dock: "坞",
        nav: "导航",
        settings: "设置",
        context: "右键",
        command: "命令",
        status: "状态",
      };
      return labels[String((entry && entry.kind) || "")] || "入口";
    },

    tierLabel(entry) {
      const labels = { official: "官方", verified: "认证", community: "社区" };
      return labels[String((entry && entry.tier) || "")] || "";
    },

    originLabel(entry) {
      if (isHostEntryKey(entry && entry.key)) return "宿主";
      return String((entry && entry.pluginId) || "");
    },

    statusClass(entry) {
      return `is-${String((entry && entry.status) || "idle")}`;
    },

    isDisabled(entry) {
      // 内建命令始终可用；插件入口看 `when` 求值结果
      if (isHostEntryKey(entry && entry.key)) return false;
      return entry && entry.enabled === false;
    },
  };
}
