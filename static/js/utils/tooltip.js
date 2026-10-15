/**
 * static/js/utils/tooltip.js
 * 全局悬浮提示（tooltip）控制器。
 *
 * 存在的意义：全仓 500+ 处提示都写成原生 `title` 属性，浏览器渲染的是系统
 * 默认的白底方框黑字，跟项目的深色玻璃面板体系完全不是一套语言。逐个模板
 * 改属性既不现实也会立刻过期，所以这里做**一次性的运行时接管**：
 *
 * 1. 指针进入带 `title` 的元素时，把文案迁移到 `data-tooltip` 并摘掉 `title`，
 *    从而关掉浏览器自带的那个框；
 * 2. 用宿主自己的 `.ui-tooltip` 浮层（`static/css/modules/tooltip.css`）呈现，
 *    跟随主题、层级令牌与动效偏好。
 *
 * 对外契约（插件同样可用，不需要引入任何模块）：
 * - `title="文案"`：宿主与插件沿用至今的写法，运行时自动接管；
 * - `data-tooltip="文案"`：显式声明，不依赖 `title`（`title` 存在时以 `title` 为准）；
 * - `data-tooltip-placement="top|bottom|left|right"`：指定方向，默认按空间自动选；
 * - `data-tooltip-disabled`：该元素不做提示（例如提示文案与可见文字重复）。
 *
 * 关键取舍：
 * - **懒迁移**：只在真正被悬停/聚焦时才改属性，避免为整棵 DOM 建观察器，
 *   也不会在元素尚未渲染时误改（Alpine 的 `:title` 绑定重渲染后仍能被接管）。
 * - **保留可访问名**：`title` 对图标按钮、`<iframe>` 这类无文本元素是唯一的
 *   可访问名来源。迁移时按 `needsAccessibleNameFallback()` 的规则补 `aria-label`，
 *   表单控件一律不补（它们靠 `<label>` / `placeholder`，补了反而会覆盖正确名字）。
 * - **触摸不触发**：`pointerType === "touch"` 直接跳过，否则点一下按钮会闪出一个
 *   没人来得及读的提示。
 * - **只读文案**：浮层文本走 `textContent`，`title` 里的任何标记都不会被解析。
 */

const TOOLTIP_ID = "ui-tooltip-root";
const INSTALL_FLAG = "__stManagerTooltipSystemInstalled";

/** 悬停多久才显示。接近系统 tooltip 的节奏，又不至于让人以为没有提示。 */
const HOVER_SHOW_DELAY_MS = 420;
/** 键盘聚焦时不等 —— 键盘用户已经明确表达了「我停在这里」。 */
const FOCUS_SHOW_DELAY_MS = 80;
/** 浮层与锚点之间的间距（箭头占位）。 */
const ANCHOR_GAP_PX = 10;
/** 浮层与视口边缘的安全距离。 */
const VIEWPORT_MARGIN_PX = 8;
/** 箭头中心距浮层圆角的最小距离，避免箭头压在圆角上。 */
const ARROW_EDGE_INSET_PX = 14;

const PLACEMENTS = ["top", "bottom", "left", "right"];

/** 这些标签的可访问名不能靠内容文本，且表单控件通常已有 `<label>`，一律不补。 */
const FORM_CONTROL_TAGS = new Set(["INPUT", "SELECT", "TEXTAREA"]);

/** 嵌入类元素没有可渲染的内容文本，`title` 就是它们唯一的可访问名。 */
const EMBED_TAGS = new Set(["IFRAME", "IMG", "OBJECT", "EMBED"]);

/**
 * 补可访问名时最多扫描这么多子元素。
 *
 * `textContent` 会序列化整棵子树；提示可能挂在卡片、面板这类大容器上，
 * 悬停时扫全树是不可接受的代价。子元素超过这个数量就认定「它自带可见文本」，
 * 直接放弃补名 —— 真正需要补名的是图标按钮这类叶子节点。
 */
const MAX_NAME_SCAN_CHILDREN = 4;

let tooltipEl = null;
let textEl = null;
let arrowEl = null;
let anchorEl = null;
let showTimer = 0;
let hideTimer = 0;
let describedAnchor = null;
/** 浮层当前是否真的亮着 —— 滚动/失焦会高频调用 `hideTooltip()`，用它做廉价短路。 */
let isShown = false;

function isElement(node) {
  return node instanceof Element;
}

/** 取事件真正命中的节点（穿透 Shadow DOM 的重定向）。 */
function eventTargetNode(event) {
  const path = typeof event.composedPath === "function" ? event.composedPath() : null;
  const first = path && path.length ? path[0] : null;
  if (isElement(first)) return first;
  return isElement(event.target) ? event.target : null;
}

/**
 * 判断摘掉 `title` 后是否需要补一个可访问名。
 *
 * `title` 只在「元素没有任何其它名字来源」时才承担可访问名；其余情况它只是
 * 补充描述。摘掉描述不影响可用性，摘掉名字会让读屏用户面对一个无名按钮。
 */
function needsAccessibleNameFallback(el) {
  if (el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby")) return false;
  if (el.hasAttribute("alt")) return false;
  if (FORM_CONTROL_TAGS.has(el.tagName)) return false;
  // 嵌入类元素没有可渲染内容文本，`title` 就是它们唯一的可访问名。
  if (EMBED_TAGS.has(el.tagName)) return true;
  // 大容器一定自带可见文本，扫全树只为确认这件事不值得。
  if (el.childElementCount > MAX_NAME_SCAN_CHILDREN) return false;
  const text = el.textContent;
  return !(text && text.trim());
}

/**
 * 读取提示文案，并把原生 `title` 迁移成 `data-tooltip`。
 *
 * `title` 优先：Alpine 的 `:title` 绑定在响应式更新时会重新写回属性，此时
 * 缓存过的 `data-tooltip` 可能已经过期，必须以最新的 `title` 为准。
 */
function readTooltipText(el) {
  const title = el.getAttribute("title");
  if (title !== null && title.trim()) {
    const text = title.trim();
    el.removeAttribute("title");
    el.setAttribute("data-tooltip", text);
    if (needsAccessibleNameFallback(el)) {
      el.setAttribute("aria-label", text);
    }
    return text;
  }

  const explicit = el.getAttribute("data-tooltip");
  return explicit === null ? "" : explicit.trim();
}

/** 解析出当前指针所在的可提示元素（就近优先）。 */
function resolveAnchor(node) {
  if (!isElement(node)) return null;
  if (!node.isConnected) return null;
  const el = node.closest("[data-tooltip], [title]");
  if (!el || el === tooltipEl) return null;
  if (el.hasAttribute("data-tooltip-disabled")) return null;
  return el;
}

function resolvePlacementPreference(el) {
  const raw = String(el.getAttribute("data-tooltip-placement") || "").toLowerCase();
  return PLACEMENTS.includes(raw) ? raw : "auto";
}

function ensureTooltipElement() {
  if (tooltipEl && tooltipEl.isConnected) return tooltipEl;

  tooltipEl = document.createElement("div");
  tooltipEl.id = TOOLTIP_ID;
  tooltipEl.className = "ui-tooltip";
  tooltipEl.setAttribute("role", "tooltip");
  tooltipEl.setAttribute("aria-hidden", "true");

  textEl = document.createElement("span");
  textEl.className = "ui-tooltip__text";
  tooltipEl.appendChild(textEl);

  arrowEl = document.createElement("span");
  arrowEl.className = "ui-tooltip__arrow";
  arrowEl.setAttribute("aria-hidden", "true");
  tooltipEl.appendChild(arrowEl);

  document.body.appendChild(tooltipEl);
  return tooltipEl;
}

function cancelShowTimer() {
  if (showTimer) {
    window.clearTimeout(showTimer);
    showTimer = 0;
  }
}

function cancelHideTimer() {
  if (hideTimer) {
    window.clearTimeout(hideTimer);
    hideTimer = 0;
  }
}

function releaseDescribedBy() {
  if (!describedAnchor) return;
  if (describedAnchor.dataset.tooltipDescribedby === "1") {
    describedAnchor.removeAttribute("aria-describedby");
    delete describedAnchor.dataset.tooltipDescribedby;
  }
  describedAnchor = null;
}

/** 立即隐藏浮层（不做延时）。 */
export function hideTooltip() {
  cancelShowTimer();
  cancelHideTimer();
  const hadAnchor = anchorEl !== null;
  releaseDescribedBy();
  anchorEl = null;
  // 滚动与失焦都会高频调用这里；没有任何东西在显示时不要碰 DOM。
  if (!hadAnchor && !isShown) return;
  isShown = false;
  if (!tooltipEl) return;
  tooltipEl.classList.remove("is-visible");
  tooltipEl.setAttribute("aria-hidden", "true");
  delete tooltipEl.dataset.placement;
}

function scheduleHide() {
  cancelShowTimer();
  if (!anchorEl) return;
  cancelHideTimer();
  hideTimer = window.setTimeout(() => {
    hideTimer = 0;
    hideTooltip();
  }, 0);
}

/** 计算浮层落点，返回 `{ placement, left, top, arrowOffset }`。 */
function computePosition(anchorRect, box, preference) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const spaceTop = anchorRect.top - VIEWPORT_MARGIN_PX;
  const spaceBottom = viewportHeight - anchorRect.bottom - VIEWPORT_MARGIN_PX;
  const spaceLeft = anchorRect.left - VIEWPORT_MARGIN_PX;
  const spaceRight = viewportWidth - anchorRect.right - VIEWPORT_MARGIN_PX;
  const needVertical = box.height + ANCHOR_GAP_PX;
  const needHorizontal = box.width + ANCHOR_GAP_PX;

  const fits = {
    top: spaceTop >= needVertical,
    bottom: spaceBottom >= needVertical,
    left: spaceLeft >= needHorizontal,
    right: spaceRight >= needHorizontal,
  };

  let placement = preference;
  if (placement === "auto") {
    if (fits.bottom && !fits.top) placement = "bottom";
    else if (fits.top && !fits.bottom) placement = "top";
    else if (fits.top && fits.bottom) placement = "top";
    else if (fits.right) placement = "right";
    else if (fits.left) placement = "left";
    else {
      // 四个方向都放不下：退到空间最大的一侧，交给下面的视口夹取收尾。
      const candidates = [
        ["top", spaceTop],
        ["bottom", spaceBottom],
        ["left", spaceLeft],
        ["right", spaceRight],
      ];
      candidates.sort((a, b) => b[1] - a[1]);
      placement = candidates[0][0];
    }
  }

  const centerX = anchorRect.left + anchorRect.width / 2;
  const centerY = anchorRect.top + anchorRect.height / 2;
  let left;
  let top;

  if (placement === "top" || placement === "bottom") {
    left = centerX - box.width / 2;
    top =
      placement === "top"
        ? anchorRect.top - ANCHOR_GAP_PX - box.height
        : anchorRect.bottom + ANCHOR_GAP_PX;
  } else {
    top = centerY - box.height / 2;
    left =
      placement === "left"
        ? anchorRect.left - ANCHOR_GAP_PX - box.width
        : anchorRect.right + ANCHOR_GAP_PX;
  }

  const maxLeft = Math.max(VIEWPORT_MARGIN_PX, viewportWidth - VIEWPORT_MARGIN_PX - box.width);
  const maxTop = Math.max(VIEWPORT_MARGIN_PX, viewportHeight - VIEWPORT_MARGIN_PX - box.height);
  const clampedLeft = Math.min(Math.max(left, VIEWPORT_MARGIN_PX), maxLeft);
  const clampedTop = Math.min(Math.max(top, VIEWPORT_MARGIN_PX), maxTop);

  // 箭头始终指向锚点中心；被视口夹取后偏移量会变，所以按夹取结果反算。
  let arrowOffset;
  if (placement === "top" || placement === "bottom") {
    arrowOffset = centerX - clampedLeft;
    arrowOffset = Math.min(
      Math.max(arrowOffset, ARROW_EDGE_INSET_PX),
      Math.max(ARROW_EDGE_INSET_PX, box.width - ARROW_EDGE_INSET_PX),
    );
  } else {
    arrowOffset = centerY - clampedTop;
    arrowOffset = Math.min(
      Math.max(arrowOffset, ARROW_EDGE_INSET_PX),
      Math.max(ARROW_EDGE_INSET_PX, box.height - ARROW_EDGE_INSET_PX),
    );
  }

  return { placement, left: clampedLeft, top: clampedTop, arrowOffset };
}

function renderTooltip(anchor, text) {
  if (!anchor.isConnected || !text) return;
  const node = ensureTooltipElement();

  textEl.textContent = text;
  node.classList.remove("is-visible");
  node.setAttribute("aria-hidden", "true");
  // 先复位到原点并量尺寸：残留的 left/top 会让测量结果被夹取污染。
  node.style.left = "0px";
  node.style.top = "0px";
  node.dataset.placement = "top";
  node.style.setProperty("--ui-tooltip-arrow-offset", "50%");

  const box = node.getBoundingClientRect();
  const anchorRect = anchor.getBoundingClientRect();
  const position = computePosition(
    anchorRect,
    box,
    resolvePlacementPreference(anchor),
  );

  node.dataset.placement = position.placement;
  node.style.left = `${Math.round(position.left)}px`;
  node.style.top = `${Math.round(position.top)}px`;
  node.style.setProperty(
    "--ui-tooltip-arrow-offset",
    `${Math.round(position.arrowOffset)}px`,
  );

  // 让浮层与锚点建立语义关联，读屏用户也能拿到同一份说明。
  releaseDescribedBy();
  if (!anchor.hasAttribute("aria-describedby")) {
    anchor.setAttribute("aria-describedby", TOOLTIP_ID);
    anchor.dataset.tooltipDescribedby = "1";
    describedAnchor = anchor;
  }

  // 下一帧再亮起，否则首次创建时浏览器会把「已可见」当作初始状态，动效丢失。
  window.requestAnimationFrame(() => {
    if (anchorEl !== anchor || !anchor.isConnected) return;
    isShown = true;
    node.classList.add("is-visible");
    node.setAttribute("aria-hidden", "false");
  });
}

function scheduleShow(anchor, text, delay) {
  cancelShowTimer();
  cancelHideTimer();
  showTimer = window.setTimeout(() => {
    showTimer = 0;
    if (anchorEl !== anchor) return;
    renderTooltip(anchor, text);
  }, delay);
}

function onPointerOver(event) {
  if (event.pointerType === "touch") return;
  const anchor = resolveAnchor(eventTargetNode(event));
  if (!anchor) {
    scheduleHide();
    return;
  }
  // 同一个锚点内部移动（例如按钮里的图标换了个节点）不该重开计时器。
  if (anchor === anchorEl) {
    cancelHideTimer();
    return;
  }
  const text = readTooltipText(anchor);
  if (!text) {
    scheduleHide();
    return;
  }
  anchorEl = anchor;
  scheduleShow(anchor, text, HOVER_SHOW_DELAY_MS);
}

function onPointerOut(event) {
  if (event.pointerType === "touch") return;
  const related = event.relatedTarget;
  if (anchorEl && isElement(related) && anchorEl.contains(related)) return;
  scheduleHide();
}

function onFocusIn(event) {
  const anchor = resolveAnchor(eventTargetNode(event));
  if (!anchor) return;
  let focusVisible = false;
  try {
    focusVisible = anchor.matches(":focus-visible");
  } catch {
    focusVisible = false;
  }
  if (!focusVisible) return;
  const text = readTooltipText(anchor);
  if (!text) return;
  anchorEl = anchor;
  scheduleShow(anchor, text, FOCUS_SHOW_DELAY_MS);
}

function onFocusOut() {
  scheduleHide();
}

function onKeyDown(event) {
  if (event.key === "Escape") hideTooltip();
}

/**
 * 安装全局提示接管（幂等）。
 *
 * 挂在 `document` 上用捕获阶段做事件委托：DOM 由 Alpine 大量重渲染，逐元素
 * 绑定既贵又会在重渲染后失效。捕获阶段能拿到最早的事件，避免被业务代码的
 * `stopPropagation` 顺手挡掉。
 */
export function initTooltipSystem() {
  if (typeof document === "undefined") return false;
  if (window[INSTALL_FLAG]) return false;
  window[INSTALL_FLAG] = true;

  const install = () => {
    document.addEventListener("pointerover", onPointerOver, true);
    document.addEventListener("pointerout", onPointerOut, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("pointerdown", hideTooltip, true);
    document.addEventListener("keydown", onKeyDown, true);
    // 捕获阶段监听滚动：内层滚动容器（阅读器、模态正文）也要能收掉浮层，
    // 否则锚点滚走了提示还钉在屏幕上。
    window.addEventListener("scroll", hideTooltip, true);
    window.addEventListener("resize", hideTooltip);
    window.addEventListener("blur", hideTooltip);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
  return true;
}

/** 供测试与调试使用：当前浮层节点（未创建时为 null）。 */
export function getTooltipElement() {
  return tooltipEl;
}
