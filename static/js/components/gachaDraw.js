/**
 * static/js/components/gachaDraw.js
 * 抽卡弹窗：单抽（pack-opener 开包动画）+ 十连（发牌 / 翻牌 / 拖拽批量翻）
 *
 * 设计要点：
 * - 稀有度完全由后端 `/api/draw_cards` 返回的 `rarity` 字段驱动（收藏 → UR，
 *   其余按 Token 分四档），前端只做「稀有度 → 特效 / 颜色 / 文案」的映射。
 * - 单抽用 pack-opener（WebGL，import map 免打包）。变体切换必须 destroy 后重建，
 *   `setOptions({variant})` 不支持换 variant。
 * - 揭晓后是**完整角色卡**（templates/components/gacha_card.html，与网格同一套 CSS），
 *   并且和网格一样挂 HoloCard 实例 —— 这是「跟随鼠标倾斜」与「光照随指针走」的唯一来源；
 *   不挂实例时 holo-cards.css 的 `:not(.holo-card--interactive):hover` 兜底会把卡固定成
 *   一个姿态（看起来「只能往一边倒」）。
 * - 音效状态存 localStorage（`st_manager_gacha_sound`），不进 ui_data / config.json。
 */

import { getCardGridTokenBadgeClass } from "../utils/format.js";
// 静态 import：卡面特效必须同步挂载（见 attachHoloCard 的注释）。
// 这份模块本来就由 cardGrid.js 静态加载，这里不会多出网络请求。
import {
  attachHoloCard as mountHoloCard,
  prepareHoloCard,
} from "../../lib/cards-css/index.js";

const SOUND_STORAGE_KEY = "st_manager_gacha_sound";

// 卡面标签最多显示几个（与网格的视觉密度对齐）
const TAG_LIMIT = 3;

// 单抽动画方式 → pack-opener 的 preset
const VARIANT_PRESETS = Object.freeze({
  slice: "classic",
  burst: "charged",
  carousel: "showcase",
});

// 稀有度 → cards-css foil 效果（阶梯：哑光 → 宇宙 → 极光 → 金 → 彩虹）
const RARITY_EFFECT = Object.freeze({
  N: "metal",
  R: "cosmos",
  SR: "aurora",
  SSR: "gold",
  UR: "rainbow",
});

// 稀有度 → pokemon-cards-css 的 data-rarity（空串 = 不叠加）
const RARITY_DATASET = Object.freeze({
  N: "",
  R: "",
  SR: "radiant rare",
  SSR: "rare secret",
  UR: "rare rainbow",
});

// 稀有度 → 卡背显影色。这里是**实色**，用于 border / box-shadow；
// UR 另有一份 `--rarity-gradient`（conic-gradient 不能塞进 border-color）。
// N 用 --content-muted 而不是 --border-default：后者就是卡背的默认边框色，
// 会在浅色/深色主题下与「未悬浮」完全同色，等于没有反馈。
const RARITY_COLOR = Object.freeze({
  N: "var(--content-muted)",
  R: "#3b82f6",
  SR: "#a855f7",
  SSR: "#fbbf24",
  UR: "#e879f9",
});

// UR 的彩虹装饰层；其余稀有度回落到实色。
const RARITY_GRADIENT = Object.freeze({
  UR: "conic-gradient(from 210deg, #f87171, #fbbf24, #34d399, #38bdf8, #a78bfa, #f472b6, #f87171)",
});

const RARITY_LABEL = Object.freeze({
  N: "N · 普通",
  R: "R · 稀有",
  SR: "SR · 史诗",
  SSR: "SSR · 传说",
  UR: "UR · 神话",
});

const VARIANT_HINTS = Object.freeze({
  slice: "划过封条切开卡包",
  burst: "长按卡包蓄力至爆开",
  carousel: "拖动转盘选包，再点选一个",
});

// 揭晓卡挂 HoloCard 的重试上限（约 60 帧 ≈ 1 秒；取不到就放弃，不影响功能）
const MAX_HOLO_ATTACH_ATTEMPTS = 60;

// 等 pack-opener 宿主拿到真实尺寸的重试上限（同上，约 1 秒）
const MAX_STAGE_SIZE_ATTEMPTS = 60;

// 揭晓特效时长（与 modal-gacha.css 里的动画时长保持一致）
const REVEAL_EFFECT_MS = 900;

const DEAL_STEP_MS = 90;
const DEAL_DURATION_MS = 620;
const PEEK_HOLD_MS = 120;

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export default function gachaDraw() {
  return {
    // === 状态 ===
    showGachaModal: false,
    gachaMode: "multi", // 'single' | 'multi'
    gachaVariant: "slice", // 'slice' | 'burst' | 'carousel'
    gachaPhase: "idle", // 'idle' | 'loading' | 'ceremony' | 'result'

    drawnCards: [],
    poolSize: 0,
    poolExhausted: false,
    pityApplied: false,

    isDrawing: false,
    isDealing: false,
    soundEnabled: true,

    // 拖拽批量翻牌
    _dragging: false,
    _dragMoved: false,
    _dragOrigin: null,
    _peekTimer: null,
    _peekNode: null,
    // 本次指针手势刚翻开的卡（下标）；紧随其后的 click 只确认翻开，不再进详情
    _flippedByPointer: null,

    // pack-opener
    _opener: null,
    _stageToken: 0,
    _revealedHandled: false,

    // 揭晓卡上的 HoloCard 实例（key: 十连下标 或 'single'）
    _holoCards: null,
    // 组件根元素（init 时抓取；不要用 this.$el，见 init 注释）
    _rootEl: null,

    // === 生命周期（Alpine 自动调用 init，模板里不要再写 x-init） ===
    init() {
      // Alpine 的 `$el` 是按「当前表达式求值上下文」注入的：在按钮 click 触发的
      // 调用链里，this.$el 会是那个按钮，不是组件根元素。这里在 init 阶段把根元素
      // 固定下来，之后所有 DOM 查询都走它。
      this._rootEl =
        this.$el || document.querySelector('[x-data="gachaDraw"]') || null;

      this.soundEnabled = this.readSoundPreference();
      this._holoCards = new Map();

      window.addEventListener("open-gacha-draw", (event) => {
        const detail = event.detail || {};
        this.openGachaDraw(detail.mode);
      });

      this.$watch("showGachaModal", (value) => {
        if (!value) {
          this.teardown();
        }
      });

      // 换变体 = destroy + 重建：pack-opener 的 setOptions({variant}) 明确不支持运行时换机制。
      this.$watch("gachaVariant", () => {
        if (this.gachaMode !== "single" || this.gachaPhase !== "ceremony") {
          return;
        }
        if (!this._opener) {
          return;
        }
        this.restartSingleCeremony();
      });
    },

    // === 派生状态 ===
    get modeLabel() {
      // 起手还没选模式，不要预设成「十连抽」（gachaMode 的默认值）
      if (this.gachaPhase === "idle") {
        return "抽卡";
      }
      return this.gachaMode === "single" ? "单抽" : "十连抽";
    },

    get viewTitle() {
      if (this.gachaPhase === "idle") {
        return "选择抽取方式";
      }
      if (this.gachaPhase === "loading") {
        return "正在抽取…";
      }
      if (this.gachaMode === "single") {
        return this.gachaPhase === "ceremony" ? "开启卡包" : "揭晓结果";
      }
      return "揭晓结果";
    },

    get ceremonyHint() {
      return VARIANT_HINTS[this.gachaVariant] || "";
    },

    get revealedCount() {
      return this.drawnCards.filter((card) => card.revealed).length;
    },

    get allRevealed() {
      return this.drawnCards.length > 0 && this.revealedCount === this.drawnCards.length;
    },

    /** 跟随设置页的「角色卡特效」开关：关掉后揭晓只显示静态卡面。 */
    get effectsEnabled() {
      return this.$store?.global?.settingsForm?.card_effects_enabled !== false;
    },

    get gachaRevealClass() {
      return this.effectsEnabled ? "" : "gacha-reveal--plain";
    },

    get footerStatus() {
      if (this.gachaPhase === "idle") {
        // 起手态的说明已经在按钮上方，页脚不重复
        return "";
      }
      if (this.gachaMode === "multi") {
        return `已翻开 ${this.revealedCount} / ${this.drawnCards.length}`;
      }
      if (this.gachaPhase === "result") {
        const card = this.singleCard;
        return card.id ? `${this.rarityLabel(card)} · ${this.cardName(card)}` : "";
      }
      return "";
    },

    get poolNotice() {
      if (this.gachaMode !== "multi" || !this.poolExhausted) {
        return "";
      }
      return `卡池仅 ${this.poolSize} 张，本次十连可能出现重复`;
    },

    get singleCard() {
      return this.drawnCards[0] || {};
    },

    /**
     * 弹窗宽度档位：起手选择用窄壳（两个方形按钮，不需要 1180px 宽），
     * 十连用宽壳放 5 列网格，单抽用窄壳放一张卡。
     */
    get gachaOverlayClass() {
      if (this.gachaPhase === "idle") {
        return "gacha-overlay--chooser";
      }
      return this.gachaMode === "multi" ? "gacha-overlay--multi" : "gacha-overlay--single";
    },

    // === 稀有度映射 ===
    rarityOf(card) {
      const rarity = String(card?.rarity || "N").toUpperCase();
      return RARITY_EFFECT[rarity] ? rarity : "N";
    },

    rarityEffect(card) {
      return RARITY_EFFECT[this.rarityOf(card)];
    },

    /**
     * 稀有度的**短键**（N/R/SR/SSR/UR），挂在 `.gacha-card[data-rarity-key]` 上。
     *
     * 与 `rarityDataset()` 分开是必要的：那一个返回 pokemon 的稀有度字符串
     * （N 与 R 都是空串），没法用来区分档位；卡背悬浮配色与揭晓特效都要逐档区分。
     */
    rarityKey(card) {
      return this.rarityOf(card);
    },

    rarityDataset(card) {
      return RARITY_DATASET[this.rarityOf(card)] || null;
    },

    rarityLabel(card) {
      return RARITY_LABEL[this.rarityOf(card)];
    },

    rarityChipClass(card) {
      return `gacha-rarity-chip--${this.rarityOf(card).toLowerCase()}`;
    },

    tokenChipClass(card) {
      return getCardGridTokenBadgeClass(card?.token_count);
    },

    cardName(card) {
      return card?.char_name || card?.filename || "未命名";
    },

    cardTags(card) {
      return (Array.isArray(card?.tags) ? card.tags : []).slice(0, TAG_LIMIT);
    },

    cardTagOverflow(card) {
      const total = Array.isArray(card?.tags) ? card.tags.length : 0;
      return Math.max(0, total - TAG_LIMIT);
    },

    resultCardClass(card) {
      return `gacha-result-card--${this.rarityOf(card).toLowerCase()}`;
    },

    rarityStyle(card) {
      const rarity = this.rarityOf(card);
      const style = { "--rarity-color": RARITY_COLOR[rarity] };
      if (RARITY_GRADIENT[rarity]) {
        style["--rarity-gradient"] = RARITY_GRADIENT[rarity];
      }
      return style;
    },

    cardStyle(card, index) {
      return {
        ...this.rarityStyle(card),
        "--deal-index": String(index),
        "--from-x": `${((index * 37) % 21) - 10}vw`,
        "--from-rot": `${((index * 53) % 25) - 12}deg`,
      };
    },

    cardImageUrl(card) {
      // 完整卡按网格尺寸渲染，缩略图（宽 300）够用；原图更清晰但更慢。
      return card?.thumb_url || card?.image_url || "/static/images/default_card.png";
    },

    onCardImageError(event) {
      const image = event?.target;
      if (!image) {
        return;
      }
      image.onerror = null;
      image.src = "/static/images/default_card.png";
    },

    // === 抽取参数：与列表视图对齐 ===
    buildDrawParams(count) {
      const vs = this.$store.global.viewState || {};
      return {
        count,
        category: vs.filterCategory || "",
        tags: vs.filterTags || [],
        excluded_tags: vs.excludedTags || [],
        search: vs.searchQuery || "",
        search_type: vs.searchType || "mix",
        search_scope: vs.searchScope || "current",
        all_dirs_only_with_filters:
          vs.allDirsOnlyWithFilters === true && vs.recursiveFilter !== false,
        recursive: vs.recursiveFilter !== false,
        fav_filter: vs.favFilter || "none",
        import_date_from: vs.importDateFrom || "",
        import_date_to: vs.importDateTo || "",
        modified_date_from: vs.modifiedDateFrom || "",
        modified_date_to: vs.modifiedDateTo || "",
        token_min: vs.tokenMin === "" || vs.tokenMin == null ? "" : String(vs.tokenMin),
        token_max: vs.tokenMax === "" || vs.tokenMax == null ? "" : String(vs.tokenMax),
      };
    },

    async requestDraw(count) {
      const response = await fetch("/api/draw_cards", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.buildDrawParams(count)),
      });
      return response.json();
    },

    // === 打开 / 关闭 ===
    openGachaDraw(mode) {
      this.gachaMode = mode === "single" ? "single" : "multi";
      this.resetDrawState();
      this.showGachaModal = true;
    },

    /**
     * 关闭抽卡弹窗（右上角 X / Esc / 点击外部）。
     *
     * 详情页盖在上面时必须让路：详情页是全屏遮罩，点它里面任意位置都算
     * 「点在 `.gacha-shell` 之外」，`@click.away` 会连带把抽卡弹窗一起关掉；
     * Esc 更糟 —— 两个组件都监听 `keydown.escape.window`，会一次关掉两层。
     * 所以详情页开着时这里直接返回，交给详情页自己处理关闭。
     */
    requestClose() {
      if (this.isDetailModalOpen()) {
        return;
      }
      this.showGachaModal = false;
    },

    backToChooser() {
      if (this.isDrawing) {
        return;
      }
      this.teardown();
      this.gachaPhase = "idle";
      this.drawnCards = [];
      this.poolSize = 0;
      this.poolExhausted = false;
      this.pityApplied = false;
      this.isDealing = false;
    },

    resetDrawState() {
      this.teardown();
      this.gachaPhase = "idle";
      this.drawnCards = [];
      this.poolSize = 0;
      this.poolExhausted = false;
      this.pityApplied = false;
      this.isDealing = false;
      this.isDrawing = false;
    },

    teardown() {
      this._dragging = false;
      this._dragMoved = false;
      this.clearPeekTimer();
      this.destroyOpener();
      this.destroyAllHoloCards();
    },

    // === 抽取主流程 ===
    async startDraw(mode) {
      if (this.isDrawing) {
        return;
      }
      // 起手两个大按钮直接把模式传进来：点哪个就抽哪个，不再需要二次确认。
      if (mode === "single" || mode === "multi") {
        this.gachaMode = mode;
      }

      this.isDrawing = true;
      this.teardown();
      this.drawnCards = [];
      this.poolSize = 0;
      this.poolExhausted = false;
      this.pityApplied = false;
      this.gachaPhase = "loading";

      const count = this.gachaMode === "single" ? 1 : 10;

      try {
        const result = await this.requestDraw(count);

        if (!result || result.success !== true) {
          this.gachaPhase = "idle";
          if (result && result.code === "EMPTY_POOL") {
            // 空池不打开动画，直接提示，避免用户以为功能坏了
            this.showToast(result.msg || "当前筛选条件下没有角色卡，请调整筛选条件后再试");
          } else {
            this.showToast((result && result.msg) || "抽取失败，请稍后重试");
          }
          return;
        }

        const cards = Array.isArray(result.cards) ? result.cards : [];
        if (cards.length === 0) {
          this.gachaPhase = "idle";
          this.showToast("当前筛选条件下没有角色卡，请调整筛选条件后再试");
          return;
        }

        this.poolSize = Number(result.pool_size) || cards.length;
        this.poolExhausted = result.pool_exhausted === true;
        this.pityApplied = result.pity_applied === true;
        this.drawnCards = cards.map((card) => ({ ...card, revealed: false }));

        if (this.gachaMode === "single") {
          await this.startSingleCeremony();
        } else {
          this.startMultiDeal();
        }
      } catch (error) {
        console.error("[gacha] 抽取失败", error);
        this.gachaPhase = "idle";
        this.showToast("网络错误，抽取失败");
      } finally {
        this.isDrawing = false;
      }
    },

    showToast(message) {
      try {
        this.$store.global.showToast(message, 3200, "info");
      } catch (_error) {
        window.alert(message);
      }
    },

    /**
     * 等宿主元素拿到真实尺寸（宽高都 > 0）。
     *
     * 用 rAF 轮询而不是直接读一次：`x-show` 刚从 display:none 切回来时，布局可能
     * 还没跑完。返回 false 表示期间被取消（token 变了 / 弹窗关了），调用方应直接放弃。
     */
    waitForStageSize(host, token, attempt = 0) {
      return new Promise((resolve) => {
        const check = () => {
          if (token !== this._stageToken || !this.showGachaModal) {
            resolve(false);
            return;
          }
          const rect = host.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            resolve(true);
            return;
          }
          if (attempt >= MAX_STAGE_SIZE_ATTEMPTS) {
            // 拿不到尺寸也别卡住流程：照旧交给 pack-opener，它有自己的兜底
            resolve(true);
            return;
          }
          window.requestAnimationFrame(() => {
            this.waitForStageSize(host, token, attempt + 1).then(resolve);
          });
        };
        check();
      });
    },

    // === 单抽：pack-opener（中间流程只出图，不铺完整卡） ===
    async startSingleCeremony() {
      const card = this.drawnCards[0];
      const token = ++this._stageToken;
      this._revealedHandled = false;
      this.gachaPhase = "ceremony";

      this.playCue("open", card);

      await this.$nextTick();

      if (token !== this._stageToken || !this.showGachaModal) {
        return;
      }

      let createPackOpener;
      try {
        const module = await import("/static/lib/pack-opener/index.js");
        createPackOpener = module.createPackOpener;
      } catch (error) {
        console.error("[gacha] pack-opener 加载失败，降级为直接揭晓", error);
        if (token === this._stageToken) {
          this.finishSingleCeremony();
        }
        return;
      }

      if (token !== this._stageToken || !this.showGachaModal) {
        return;
      }

      const host = this.$refs.stage;
      if (!host) {
        this.finishSingleCeremony();
        return;
      }

      /*
       * 必须等宿主真的有尺寸再建场景。
       *
       * pack-opener 用 Pixi 的 `resizeTo: host` 定尺寸；宿主此时若还是
       * `display: none`（刚由 x-show 切过来还没走完布局）就会量到 0，Pixi 回落到
       * 默认 800×600，画面比例随之错掉。
       *
       * 「再抽一次」正是这条路径：第一次抽卡时 pack-opener 模块要现下载，等待期间
       * 布局已经稳定；第二次模块命中缓存，`await import` 几乎立刻返回，反而抢在布局前
       * 建场景 —— 这就是「第一次正常、再抽一次才被压窄」的原因。
       */
      if (!(await this.waitForStageSize(host, token))) {
        return;
      }

      this.destroyOpener();

      try {
        this._opener = await createPackOpener(
          host,
          {
            variant: this.gachaVariant,
            preset: VARIANT_PRESETS[this.gachaVariant] || "classic",
            assets: {
              pack: { url: "/static/images/gacha/pack.png" },
              card: {
                url: card?.image_url || this.cardImageUrl(card),
                facts: this.buildFacts(card),
                badge: {
                  label: this.rarityOf(card),
                  color: this.rarityBadgeColor(card),
                },
              },
            },
            theme: {
              background: "transparent",
              glow: this.rarityBadgeColor(card),
            },
            sound: { enabled: this.soundEnabled, volume: 0.8 },
          },
          {
            onEvent: (event) => this.onOpenerEvent(event, token),
          },
        );

        if (token !== this._stageToken) {
          this.destroyOpener();
        }
      } catch (error) {
        console.error("[gacha] pack-opener 初始化失败", error);
        this.destroyOpener();
        if (token === this._stageToken) {
          this.finishSingleCeremony();
        }
      }
    },

    buildFacts(card) {
      // 仅 carousel 变体播报；其余变体忽略，不会报错。
      return [
        { label: "稀有度", value: this.rarityLabel(card) },
        { label: "Token", value: String(card?.token_count || 0) },
        { label: "分类", value: card?.category || "根目录" },
      ];
    },

    rarityBadgeColor(card) {
      return RARITY_COLOR[this.rarityOf(card)];
    },

    onOpenerEvent(event, token) {
      if (token !== this._stageToken) {
        return;
      }
      const type = event && event.type;

      if (type === "opened") {
        this.playCue("impact", this.drawnCards[0]);
      }

      if (type === "revealed" && !this._revealedHandled) {
        this._revealedHandled = true;
        this.$nextTick(() => {
          if (token === this._stageToken) {
            this.finishSingleCeremony();
          }
        });
      }
    },

    finishSingleCeremony() {
      this.gachaPhase = "result";
      this.destroyOpener();
      this.attachHoloCard("single", 0);
    },

    /** 换变体时重建开包场景（setOptions 不支持运行时换 variant）。 */
    async restartSingleCeremony() {
      if (!this.drawnCards[0]) {
        return;
      }
      // 先失效当前场景：in-flight 的旧 create 回调会被 token 检查挡掉
      this._stageToken += 1;
      this.destroyOpener();
      await this.startSingleCeremony();
    },

    skipCeremony() {
      if (this.gachaPhase !== "ceremony") {
        return;
      }
      if (this._opener && typeof this._opener.autoSlice === "function") {
        this._opener.autoSlice();
      }
    },

    destroyOpener() {
      if (!this._opener) {
        return;
      }
      try {
        this._opener.destroy();
      } catch (error) {
        console.warn("[gacha] pack-opener destroy 失败", error);
      }
      this._opener = null;
    },

    // === 揭晓卡上的 HoloCard（跟随鼠标的唯一来源） ===
    holoOptions(card) {
      return {
        effect: this.rarityEffect(card),
        textureSeed: this.textureSeed(card?.id),
        physics: {
          maxTilt: 7,
          parallax: 0.82,
          glareRange: 0.9,
          returnDelay: 180,
        },
      };
    },

    /**
     * 给揭晓卡挂上 HoloCard 交互实例 —— 这是「跟随鼠标倾斜 / 光照随指针走」的唯一来源。
     *
     * 两个坑，改动前先读：
     * 1. DOM 查询必须走 `this._rootEl`。Alpine 的 `$el` 是按「当前表达式求值上下文」
     *    注入的：由按钮 click 触发的调用链里 `this.$el` 是那个按钮，不是组件根元素，
     *    于是 `querySelector` 永远落空、卡面一直没实例，退化成 holo-cards.css 里
     *    `:not(.holo-card--interactive):hover` 的固定姿态（看起来就是「只能往一边倒」）。
     * 2. 揭晓区块由 x-show 切到可见后，Alpine 可能还没把 DOM 刷出来，所以取不到节点时
     *    重试几帧（`$nextTick` 在这里不够用）。
     */
    attachHoloCard(key, index, attempt = 0) {
      if (!this.effectsEnabled || !this.showGachaModal) {
        return;
      }
      if (this._holoCards?.has(key)) {
        return;
      }
      const shell = this.findHoloShell(index);
      if (!shell) {
        // 揭晓区块刚由 x-show 切到可见，Alpine 可能还没把 DOM 刷出来；重试几帧。
        if (attempt < MAX_HOLO_ATTACH_ATTEMPTS) {
          window.setTimeout(() => {
            this.attachHoloCard(key, index, attempt + 1);
          }, 16);
        }
        return;
      }
      const card = this.drawnCards[index] || {};
      const options = this.holoOptions(card);
      try {
        prepareHoloCard(shell, options);
        const instance = mountHoloCard(shell, {
          ...options,
          interactive: true,
          gyroscope: false,
        });
        this._holoCards.set(key, instance);
      } catch (error) {
        console.warn("[gacha] 卡面特效挂载失败", error);
      }
    },

    findHoloShell(index) {
      const scope = this._rootEl;
      if (!scope) {
        return null;
      }
      if (this.gachaMode === "single") {
        return scope.querySelector(".gacha-result-card .card-effect-shell");
      }
      return scope.querySelector(
        `.gacha-card[data-index="${index}"] .card-effect-shell`,
      );
    },

    destroyHoloCard(key) {
      const instance = this._holoCards?.get(key);
      if (!instance) {
        return;
      }
      try {
        instance.destroy();
      } catch (error) {
        console.warn("[gacha] 卡面特效销毁失败", error);
      }
      this._holoCards.delete(key);
    },

    destroyAllHoloCards() {
      if (!this._holoCards) {
        return;
      }
      for (const key of [...this._holoCards.keys()]) {
        this.destroyHoloCard(key);
      }
    },

    textureSeed(cardId) {
      let hash = 2166136261;
      for (const char of String(cardId ?? "")) {
        hash ^= char.charCodeAt(0);
        hash = Math.imul(hash, 16777619);
      }
      return hash >>> 0;
    },

    // === 十连：发牌 ===
    startMultiDeal() {
      this.gachaPhase = "result";
      this.isDealing = !prefersReducedMotion();
      this.playCue("deal");

      if (!this.isDealing) {
        return;
      }

      const total = DEAL_STEP_MS * this.drawnCards.length + DEAL_DURATION_MS;
      window.setTimeout(() => {
        this.isDealing = false;
      }, total);
    },

    // === 十连：翻牌 / 进详情 ===
    /**
     * 卡片的 click。
     *
     * 陷阱：鼠标按下时 `pointerdown` 已经把这张卡翻开了（见 onGridPointerDown →
     * flipAt），紧接着 pointerup 触发的 `click` 会看到「已经翻开」，于是又进详情页 ——
     * 一次点击既翻牌又跳转。所以要把「本次手势刚翻开的卡」记下来，在随后的 click 里
     * 消费掉（只翻牌，不进详情）。键盘 Enter/Space 不走 pointer 路径，不受影响。
     */
    onCardClick(index) {
      const card = this.drawnCards[index];
      if (!card) {
        return;
      }
      if (this._flippedByPointer?.has(index)) {
        this._flippedByPointer.delete(index);
        return;
      }
      if (!card.revealed) {
        this.revealCard(index);
        return;
      }
      this.openDetail(card);
    },

    /** 记录「这张卡是被指针手势翻开的」，供紧随其后的 click 判断。 */
    markFlippedByPointer(index) {
      if (!this._flippedByPointer) {
        this._flippedByPointer = new Set();
      }
      this._flippedByPointer.add(index);
      // 兜底清理：某些浏览器在 pointerdown 后不一定补发 click（例如拖拽结束点不在卡上）
      window.setTimeout(() => this._flippedByPointer?.delete(index), 600);
    },

    revealCard(index, viaPointer = false) {
      if (this.isDealing) {
        return;
      }
      const card = this.drawnCards[index];
      if (!card || card.revealed) {
        return;
      }
      card.revealed = true;
      if (viaPointer) {
        this.markFlippedByPointer(index);
      }
      this.playCue("flip", card);
      this.attachHoloCard(index, index);
      this.playRevealEffect(index);

      if (this.allRevealed) {
        window.setTimeout(() => this.playCue("complete"), 160);
      }
    },

    /**
     * 稀有度专属的揭晓特效（不同档位强度与颜色不同，批量划开时逐张可见）。
     * 靠 `is-revealing` 类触发 CSS 动画，动画结束后摘掉，避免残留状态。
     */
    playRevealEffect(index) {
      const card = this.drawnCards[index];
      if (!card || this.rarityOf(card) === "N" || !this.effectsEnabled) {
        return;
      }
      card.revealing = true;
      window.setTimeout(() => {
        card.revealing = false;
      }, REVEAL_EFFECT_MS);
    },

    revealAll() {
      if (this.isDealing) {
        return;
      }
      let delay = 0;
      this.drawnCards.forEach((card, index) => {
        if (card.revealed) {
          return;
        }
        const step = delay;
        window.setTimeout(() => {
          if (!card.revealed) {
            card.revealed = true;
            this.playCue("flip", card);
            this.attachHoloCard(index, index);
            this.playRevealEffect(index);
          }
        }, step);
        delay += prefersReducedMotion() ? 0 : 70;
      });
      if (delay > 0) {
        window.setTimeout(() => this.playCue("complete"), delay + 120);
      }
    },

    // === 拖拽 / 触摸批量翻牌 ===
    onGridPointerDown(event) {
      if (this.isDealing || event.button > 0) {
        return;
      }
      this._dragging = true;
      this._dragMoved = false;
      this._dragOrigin = { x: event.clientX, y: event.clientY };

      if (event.pointerType === "touch") {
        // 触摸：先按住 PEEK_HOLD_MS 显影稀有度；一旦滑动就转为批量翻牌
        this.startPeekTimer(event.clientX, event.clientY);
      } else {
        this.flipAt(event.clientX, event.clientY);
      }
    },

    onGridPointerMove(event) {
      if (!this._dragging) {
        return;
      }
      const origin = this._dragOrigin;
      const moved =
        !origin ||
        Math.abs(event.clientX - origin.x) > 6 ||
        Math.abs(event.clientY - origin.y) > 6;
      if (!moved) {
        return;
      }
      this._dragMoved = true;
      this.clearPeekTimer();
      this.flipAt(event.clientX, event.clientY);
    },

    onGridPointerUp() {
      this._dragging = false;
      this._dragMoved = false;
      this._dragOrigin = null;
      this.clearPeekTimer();
    },

    flipAt(x, y) {
      const element = document.elementFromPoint(x, y);
      const node = element && element.closest ? element.closest(".gacha-card") : null;
      if (!node) {
        return;
      }
      const index = Number(node.dataset.index);
      if (Number.isInteger(index)) {
        // viaPointer=true：随后补发的 click 只应「确认翻开」，不该再跳详情
        this.revealCard(index, true);
      }
    },

    startPeekTimer(x, y) {
      this.clearPeekTimer();
      this._peekTimer = window.setTimeout(() => {
        this._peekTimer = null;
        if (this._dragMoved) {
          return;
        }
        const node = document.elementFromPoint(x, y);
        const cardNode = node && node.closest ? node.closest(".gacha-card") : null;
        if (cardNode && !cardNode.classList.contains("is-flipped")) {
          cardNode.classList.add("is-peeking");
          this._peekNode = cardNode;
        }
      }, PEEK_HOLD_MS);
    },

    clearPeekTimer() {
      if (this._peekTimer) {
        window.clearTimeout(this._peekTimer);
        this._peekTimer = null;
      }
      if (this._peekNode) {
        this._peekNode.classList.remove("is-peeking");
        this._peekNode = null;
      }
    },

    // === 结果动作 ===
    /**
     * 打开角色卡详情页。
     *
     * **抽卡弹窗保持打开** —— 十连抽出十张，用户要能逐张点进去看。关掉弹窗的话
     * 点完第一张就回不去抽卡结果了。
     *
     * 为了让它成立，`.gacha-overlay` 的 z-index 被压到 `--z-modal`(1000)，
     * 低于详情页的 `--z-modal-std`(1100)：两者都是 `.modal-overlay`，原本同层级，
     * 而 `detail_card.html` 在 DOM 里排在 `gacha_draw.html` **前面**，
     * 同 z-index 时后出现者胜，详情页会被抽卡弹窗盖住。
     */
    openDetail(card) {
      const target = card && card.id ? card : this.singleCard;
      if (!target || !target.id) {
        return;
      }
      window.dispatchEvent(new CustomEvent("open-detail", { detail: target }));
      window.dispatchEvent(new CustomEvent("highlight-card", { detail: target.id }));
    },

    /**
     * 详情页是否正盖在抽卡弹窗之上。
     *
     * 详情页是独立组件的 `showDetail`，这里不去读它的内部状态（耦合且易碎），
     * 直接看 DOM：它是全屏 fixed 遮罩，隐藏时 `x-show` 会写成 `display: none`。
     */
    isDetailModalOpen() {
      const overlay = document.querySelector(".detail-card-overlay");
      if (!overlay) {
        return false;
      }
      return (
        getComputedStyle(overlay).display !== "none" &&
        overlay.getBoundingClientRect().width > 0
      );
    },

    // === 音效 ===
    readSoundPreference() {
      try {
        const raw = window.localStorage.getItem(SOUND_STORAGE_KEY);
        return raw === null ? true : raw === "1";
      } catch (_error) {
        return true;
      }
    },

    toggleSound() {
      this.soundEnabled = !this.soundEnabled;
      try {
        window.localStorage.setItem(SOUND_STORAGE_KEY, this.soundEnabled ? "1" : "0");
      } catch (_error) {
        /* 隐私模式下写不进去，忽略 */
      }
      if (this._opener && typeof this._opener.setOptions === "function") {
        try {
          this._opener.setOptions({ sound: { enabled: this.soundEnabled, volume: 0.8 } });
        } catch (_error) {
          /* 场景可能已揭晓，忽略 */
        }
      }
      if (this.soundEnabled) {
        this.playCue("flip", this.drawnCards[0] || {});
      }
    },

    audioContext() {
      if (!this.soundEnabled) {
        return null;
      }
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) {
        return null;
      }
      if (!this._audio) {
        try {
          this._audio = new Ctor();
        } catch (_error) {
          return null;
        }
      }
      if (this._audio.state === "suspended" && typeof this._audio.resume === "function") {
        this._audio.resume().catch(() => {});
      }
      return this._audio;
    },

    tone(context, { frequency, start, duration, type = "sine", gain = 0.12 }) {
      const oscillator = context.createOscillator();
      const envelope = context.createGain();
      oscillator.type = type;
      oscillator.frequency.setValueAtTime(frequency, start);
      envelope.gain.setValueAtTime(0.0001, start);
      envelope.gain.exponentialRampToValueAtTime(gain, start + 0.012);
      envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(envelope);
      envelope.connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.02);
    },

    playCue(kind, card) {
      if (!this.soundEnabled) {
        return;
      }
      const context = this.audioContext();
      if (!context) {
        return;
      }
      const now = context.currentTime + 0.01;
      const rarity = card ? this.rarityOf(card) : "N";

      if (kind === "deal") {
        for (let index = 0; index < 10; index += 1) {
          this.tone(context, {
            frequency: 320 + index * 12,
            start: now + index * 0.09,
            duration: 0.07,
            type: "triangle",
            gain: 0.05,
          });
        }
        return;
      }

      if (kind === "flip") {
        // SSR / UR 有专属音效：更高更亮的和弦 + 上行琶音
        if (rarity === "UR") {
          [523.25, 659.25, 783.99, 1046.5].forEach((frequency, index) => {
            this.tone(context, {
              frequency,
              start: now + index * 0.05,
              duration: 0.42,
              type: "sine",
              gain: 0.1,
            });
          });
          return;
        }
        if (rarity === "SSR") {
          [440, 554.37, 659.25].forEach((frequency, index) => {
            this.tone(context, {
              frequency,
              start: now + index * 0.04,
              duration: 0.34,
              type: "sine",
              gain: 0.09,
            });
          });
          return;
        }
        this.tone(context, {
          frequency: rarity === "SR" ? 520 : 380,
          start: now,
          duration: 0.12,
          type: "triangle",
          gain: 0.07,
        });
        return;
      }

      if (kind === "open") {
        this.tone(context, { frequency: 220, start: now, duration: 0.5, type: "sawtooth", gain: 0.05 });
        this.tone(context, { frequency: 330, start: now + 0.08, duration: 0.4, type: "sine", gain: 0.06 });
        return;
      }

      if (kind === "impact") {
        this.tone(context, {
          frequency: rarity === "UR" ? 130.81 : 164.81,
          start: now,
          duration: 0.7,
          type: "sine",
          gain: 0.14,
        });
        return;
      }

      if (kind === "complete") {
        [392, 523.25, 659.25].forEach((frequency, index) => {
          this.tone(context, {
            frequency,
            start: now + index * 0.08,
            duration: 0.3,
            type: "sine",
            gain: 0.07,
          });
        });
      }
    },
  };
}
