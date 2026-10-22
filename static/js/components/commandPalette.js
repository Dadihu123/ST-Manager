/**
 * static/js/components/commandPalette.js
 * 命令面板（设计文档 §4.4.6 / §6.3）。
 *
 * 数据来源：
 * - `ContributionRegistry.paletteEntries()`：插件命令 + `commandPalette` 落点的菜单
 *   根节点（注册表已做 `when` 过滤，`enabledOnly` 等价语义）；
 * - `ContributionRegistry.coreCommands`：宿主内建命令（kill switch）；
 * - 宿主内建的导航动作（打开设置 / 插件管理 / 切换模式）由本文件维护。
 *
 * 触发：所有插件条目统一派发 `contribution:trigger`（S4），渲染层不知道
 * surface / command / url 的差别；宿主内建命令自己执行或派发 `plugins:close-overlays`。
 *
 * 快捷键：`Ctrl/Cmd+K` 开合面板；插件声明的 `shortcut` 在 keydown 时
 * 通过 `ContributionRegistry.findByShortcut()` 查表（设计 §4.6：与 `when` 无关，
 * 按下时求值，置灰项不执行但给提示）。
 */

import { ContributionRegistry, KILL_SWITCH_COMMAND_ID, CORE_PLUGIN_ID } from "../contributionRegistry.js";
import { icon } from "../uiPrimitives.js";

const MAX_RESULTS = 40;

/**
 * 命令面板消费的菜单落点：`ContributionRegistry.paletteEntries()` 内部固定读取
 * 该落点并合并进结果，这里保留常量作为「落点有渲染消费者」的契约锚点
 * （`dock` / `settings.nav` 等其它落点不在这里渲染）。
 */
const PALETTE_PLACEMENT = "commandPalette";

/** kill switch 的展示文案（与 `ContributionRegistry.CORE_COMMANDS` 保持一致）。 */
const KILL_SWITCH_TITLE = "插件：关闭所有浮动界面";

/** 宿主内建命令（不属于插件契约，只服务宿主导航）。 */
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

/** 宿主内建命令的面板视图（调用 CORE_ACTIONS，走同一套渲染）。 */
const HOST_COMMANDS = [
  { key: "core:open-settings", label: "打开设置", description: "打开设置面板", icon: "settings", kind: "host" },
  { key: "core:open-plugin-manager", label: "插件管理", description: "打开插件管理面板", icon: "plugin", kind: "host" },
  { key: "core:open-about", label: "关于 ST-Manager", description: "查看版本与链接", icon: "info", kind: "host" },
  { key: "core:switch-cards", label: "切换到角色卡", description: "进入角色卡视图", icon: "cards", kind: "host" },
  { key: "core:switch-worldinfo", label: "切换到世界书", description: "进入世界书视图", icon: "book", kind: "host" },
  { key: "core:switch-chats", label: "切换到聊天", description: "进入聊天视图", icon: "chat", kind: "host" },
  { key: "core:switch-presets", label: "切换到预设", description: "进入预设视图", icon: "sliders", kind: "host" },
];

function setMode(mode) {
  const store = window.Alpine && window.Alpine.store("global");
  if (store) store.currentMode = mode;
}

/** 触发上下文：命令面板没有右键目标，`target` 为 null。 */
function buildTriggerContext() {
  let mode = "";
  let ids = [];
  try {
    const store = window.Alpine && window.Alpine.store("global");
    if (store) mode = String(store.currentMode || "");
    const viewState = (store && store.viewState) || {};
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
        // 插件快捷键放在最后：不要抢掉面板自己的 Ctrl+K / Escape。
        if (this.handleContributionShortcut(event)) return;
      };
      window.addEventListener("keydown", this._keyHandler);

      this._entriesHandler = () => {
        if (this.open) this.rebuild();
      };
      window.addEventListener("contributions:changed", this._entriesHandler);
      window.addEventListener("plugins:loaded", this._entriesHandler);
    },

    /**
     * 匹配并执行贡献快捷键。
     *
     * 设计 §4.6：快捷键与 `when` **无关**（声明里没有 `when`），按下时求值；
     * `findByShortcut()` 只返回 `ok:true` 的记录，因此不满足条件的组合直接忽略。
     *
     * 三条纪律：
     * 1. **不在输入框里触发**——否则打字会把字母当快捷键；
     * 2. 组合键必须**完全匹配**（`Ctrl+Shift+A` 不等于 `Ctrl+A`）；
     * 3. 置灰的贡献不执行，但给一条提示（D7：不是无反应）。
     *
     * @returns {boolean} 是否已消费该事件。
     */
    handleContributionShortcut(event) {
      if (event.defaultPrevented) return false;
      if (this.isTypingTarget(event.target)) return false;

      const combo = this.shortcutCombo(event);
      if (!combo) return false;

      const node = ContributionRegistry.findByShortcut(combo);
      if (!node) return false;

      event.preventDefault();

      if (node.enabled === false || node.ok === false) {
        const hint = node.disabledHint || `「${node.label || node.title || node.id}」当前不可用`;
        this.showToast(hint);
        return true;
      }

      this.triggerNode(node, "shortcut");
      return true;
    },

    /** 派发统一触发事件；宿主内建（kill switch）直接执行对应窗口事件。 */
    triggerNode(node, trigger) {
      if (!node) return false;

      if (String(node.pluginId || "") === CORE_PLUGIN_ID || node.key === KILL_SWITCH_COMMAND_ID) {
        this.runCoreCommand(node);
        return true;
      }

      window.dispatchEvent(
        new CustomEvent("contribution:trigger", {
          detail: {
            pluginId: String(node.pluginId || ""),
            nodeId: String(node.id || ""),
            trigger: trigger || "palette",
            ctx: buildTriggerContext(),
          },
        }),
      );
      return true;
    },

    /** 宿主内建命令（kill switch）：只派发 `plugins:close-overlays`，由 PluginHost 处理。 */
    runCoreCommand(node) {
      const key = String((node && (node.key || node.id)) || "");
      if (key === KILL_SWITCH_COMMAND_ID || key === "plugins:close-overlays") {
        window.dispatchEvent(new CustomEvent("plugins:close-overlays"));
        return true;
      }
      const action = CORE_ACTIONS[key];
      if (typeof action === "function") {
        action();
        return true;
      }
      return false;
    },

    showToast(message) {
      try {
        const store = this.$store && this.$store.global;
        if (store && typeof store.showToast === "function") store.showToast(message, 3000);
      } catch (error) {
        console.warn("[commandPalette]", message);
      }
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
     * 把键盘事件折算成契约的快捷键键名。
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
        window.removeEventListener("contributions:changed", this._entriesHandler);
        window.removeEventListener("plugins:loaded", this._entriesHandler);
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
      this.items = this.filter(this.commandCandidates());
      this.activeIndex = 0;
    },

    onQueryInput() {
      this.items = this.filter(this.commandCandidates());
      this.activeIndex = 0;
    },

    /**
     * 面板候选集：注册表命令/落点项 + 宿主内建命令。
     *
     * 面板不展示 `context.*` 落点：它们的语义依赖右键目标，面板里没有目标。
     * `paletteEntries()` 只返回 `commandPalette` 落点，天然满足。
     */
    commandCandidates() {
      let entries = [];
      try {
        entries = ContributionRegistry.paletteEntries() || [];
      } catch (error) {
        console.warn("[commandPalette] 读取贡献失败:", error);
        entries = [];
      }

      const normalized = entries.map((entry) => ({
        ...entry,
        label: String(entry.label || entry.title || entry.id || ""),
        kind: entry.kind === "menu" ? "menu" : "command",
        source: String(entry.pluginId || ""),
      }));

      const core = ((ContributionRegistry.coreCommands || []) || []).map((entry) => ({
        ...entry,
        label: String(entry.title || entry.label || entry.id || KILL_SWITCH_TITLE),
        kind: "core",
        source: "宿主",
      }));

      const host = HOST_COMMANDS.map((entry) => ({ ...entry, source: "宿主" }));

      return [...core, ...normalized, ...host];
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
        this.move(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        this.move(-1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const item = this.items[this.activeIndex];
        if (item) this.activate(item);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
      }
    },

    move(offset) {
      if (!this.items.length) return;
      const next = (this.activeIndex + offset + this.items.length) % this.items.length;
      this.activeIndex = next;
    },

    /** 执行一条面板项：宿主动作 / kill switch / 统一触发通道。 */
    activate(item) {
      if (!item) return false;
      this.close();

      if (item.kind === "host" || item.kind === "core") {
        return this.runCoreCommand(item);
      }

      if (item.enabled === false || item.ok === false) {
        this.showToast(item.disabledHint || `「${this.labelOf(item)}」当前不可用`);
        return false;
      }

      return this.triggerNode(item, "palette");
    },

    // ------------------------------------------------------------ 呈现辅助

    labelOf(item) {
      return String((item && (item.label || item.title)) || "");
    },

    iconHtml(item) {
      const name = String((item && item.icon) || "circle-dot");
      return icon(name, {
        className: "ui-icon--sm",
        pluginId: String((item && item.pluginId) || ""),
      }).outerHTML;
    },

    kindLabel(item) {
      if (!item) return "";
      if (item.kind === "host" || item.kind === "core") return "宿主";
      if (item.kind === "menu") return "菜单";
      return "命令";
    },

    tierLabel(item) {
      const labels = { official: "官方", verified: "认证", community: "社区" };
      return labels[String((item && item.tier) || "")] || "";
    },

    originLabel(item) {
      if (!item) return "";
      if (item.kind === "host" || item.kind === "core") return "宿主";
      return String(item.pluginId || "");
    },

    statusClass(item) {
      if (!item) return "is-idle";
      const raw = item.status;
      const status = typeof raw === "string" ? raw : String((raw && raw.kind) || "idle");
      return `is-${status}`;
    },

    isDisabled(item) {
      if (!item) return true;
      if (item.kind === "host" || item.kind === "core") return false;
      return item.enabled === false || item.ok === false;
    },
  };
}
