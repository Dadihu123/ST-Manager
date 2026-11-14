/* 触摸长按 → 合成 contextmenu。
 *
 * 背景：本项目有 11 处 `@contextmenu.prevent` 右键菜单入口（卡片、文件夹、
 * 快照等）。桌面鼠标右键天然可用；触摸设备上则不可靠：
 * - Android 浏览器长按通常会触发 contextmenu，但伴随文本选择与放大镜；
 * - iOS Safari 长按**优先**弹出「选择/拷贝」系统菜单，contextmenu 常常不投递；
 * - WebView 里行为随风壳实现而变，不能假定。
 *
 * 做法：在触摸设备上自己识别「长按」（按住 500ms 且手指基本未移动），
 * 然后**合成**一个 contextmenu 事件派发给同一元素。这样：
 * 1. 11 处既有 Alpine 绑定**零改动**即可在触摸下工作；
 * 2. 合成事件带真实 clientX/clientY，菜单定位与桌面一致；
 * 3. 桌面鼠标路径完全不受影响（本模块只在触摸时激活）。
 *
 * 不干扰的情形：
 * - 手指移动超过阈值（视为滚动或拖拽）→ 取消；
 * - 元素带有 `data-no-long-press` → 跳过（给需要保留原生长按的元素留出口）；
 * - 只处理 data-long-press-menu 业务目标；输入框与可编辑区域保留原生菜单。
 * - 一次按压最多合成一次菜单，抑制同次按压迟到的原生事件。
 */

/** 长按判定阈值（毫秒）。与系统常见「约 500ms」保持一致。 */
export const LONG_PRESS_MS = 500;

/** 位移容忍（像素）。超过即视为滚动/拖拽而非长按。 */
export const MOVE_TOLERANCE_PX = 10;

const INSTALL_FLAG = '__stmLongPressInstalled';

/** 指向当前正在计时的一次按压。 */
let pending = null;

/** 最近一次浏览器自己投递 contextmenu 的时间，用于去重。 */
let endedPress = null;
const syntheticEvents = new WeakSet();

/** 判定当前是否为「触摸优先」设备。 */
export function isTouchDevice() {
  if (typeof window === 'undefined') return false;
  try {
    if (window.matchMedia) {
      // 带触屏的桌面笔记本也会 maxTouchPoints > 0，但鼠标 hover 正常，
      // 若据此挂钩子会让长按与右键互相打架，因此以「主指针是手指」为准。
      if (window.matchMedia('(pointer: coarse)').matches) return true;
      if (window.matchMedia('(any-pointer: coarse)').matches
          && !window.matchMedia('(any-pointer: fine)').matches) return true;
      return false;
    }
  } catch (err) {
    // matchMedia 在极老环境可能缺失，继续用下面的兜底。
  }
  return typeof window.ontouchstart === 'function';
}

function clearPending() {
  if (!pending) return;
  if (pending.timer) clearTimeout(pending.timer);
  pending = null;
}

/** 目标元素是否被显式排除。 */
function isExcluded(node) {
  let el = node;
  while (el && el.nodeType === 1) {
    if (el.hasAttribute && el.hasAttribute('data-no-long-press')) return true;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable) return true;
    el = el.parentElement;
  }
  return false;
}

/**
 * 合成并派发 contextmenu。
 * 返回 true 表示事件被某处消费（preventDefault 调用过）。
 */
function synthesizeContextMenu(node, touch) {
  if (typeof node.dispatchEvent !== 'function') return false;
  let event;
  try {
    event = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: touch.clientX,
      clientY: touch.clientY,
      screenX: touch.screenX,
      screenY: touch.screenY,
      button: 2,
      buttons: 2,
    });
  } catch (err) {
    console.warn('[longPress] 无法合成 contextmenu:', err);
    return false;
  }
  syntheticEvents.add(event);
  node.dispatchEvent(event);
  return event.defaultPrevented;
}

function onTouchStart(event) {
  clearPending();
  endedPress = null;
  if (!event.touches || event.touches.length !== 1) {
    clearPending();
    return;
  }
  const touch = event.touches[0];
  const node = event.target;
  if (!node || isExcluded(node)) return;
  let menuTarget = node;
  while (menuTarget && !menuTarget.hasAttribute?.('data-long-press-menu')) {
    menuTarget = menuTarget.parentElement;
  }
  if (!menuTarget) return;

  clearPending();
  pending = {
    node,
    startX: touch.clientX,
    startY: touch.clientY,
    clientX: touch.clientX,
    clientY: touch.clientY,
    screenX: touch.screenX,
    screenY: touch.screenY,
    timer: 0,
    fired: false,
  };

  pending.timer = setTimeout(() => {
    if (!pending) return;
    const current = pending;
    // 保留按压对象到 touchend，用 fired 抑制定时器之后到达的原生事件。
    current.fired = true;
    synthesizeContextMenu(current.node, current);
  }, LONG_PRESS_MS);
}

function onTouchMove(event) {
  if (!pending || !event.touches || event.touches.length !== 1) return;
  const touch = event.touches[0];
  const dx = touch.clientX - pending.startX;
  const dy = touch.clientY - pending.startY;
  if (Math.hypot(dx, dy) > MOVE_TOLERANCE_PX) {
    // 视为滚动/拖拽：取消长按，让浏览器正常处理。
    clearPending();
    return;
  }
  // 仍在容忍范围内：更新最新坐标，合成事件时用落点更准。
  pending.clientX = touch.clientX;
  pending.clientY = touch.clientY;
}

function onTouchEnd() {
  if (pending?.fired) endedPress = { ...pending, expires: Date.now() + 800 };
  clearPending();
}

function onTouchCancel() {
  clearPending();
}

/**
 * 原生 contextmenu 的处理。
 *
 * 关键修正（真机测出来的）：Android WebView 在长按约 500ms 时会**自己**派发
 * 一个 `contextmenu`，坐标是系统给的（往往是页面角落或文字选区位置），
 * 而不是手指位置。原实现在收到它时 `clearPending()` 取消自己的长按，
 * 结果合成事件永远发不出去 —— 表现为「长按没有任何菜单」。
 *
 * 现在改为：触摸设备上**接管**原生 contextmenu（preventDefault 掉系统菜单），
 * 由我们按手指落点合成一个位置正确的事件。
 *
 * 注意只拦「长按期间」的那一次：桌面右键不受影响（本桥在桌面根本不安装）。
 */
function onNativeContextMenu(event) {
  if (syntheticEvents.has(event)) return;
  const current = pending || (endedPress?.expires > Date.now() ? endedPress : null);
  if (!current || (event.target && event.target !== current.node && !current.node.contains?.(event.target))) {
    // 没有进行中的长按：可能是系统在别处触发的，不做干预。
    return;
  }

  // 有进行中的长按 → 这是浏览器自己的长按菜单，拦掉，改用我们的坐标。
  if (current.timer) clearTimeout(current.timer);

  try {
    event.preventDefault();
    event.stopPropagation();
  } catch (err) {
    // 某些环境 preventDefault 无效，继续走合成路径即可。
  }

  if (!current.fired) {
    current.fired = true;
    synthesizeContextMenu(current.node, current);
  }
}

/**
 * 安装长按桥（幂等）。仅在触摸设备上真正挂钩子。
 * @returns {boolean} 是否已安装（重复调用返回 false）
 */
export function installLongPressContextMenu() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return false;
  if (window[INSTALL_FLAG]) return false;

  if (!isTouchDevice()) {
    // 桌面环境：不挂钩子，鼠标右键路径保持原样。
    window[INSTALL_FLAG] = true;
    return true;
  }

  window[INSTALL_FLAG] = true;

  // 用捕获阶段，避免业务代码 stopPropagation 让长按失效。
  document.addEventListener('touchstart', onTouchStart, { capture: true, passive: true });
  document.addEventListener('touchmove', onTouchMove, { capture: true, passive: true });
  document.addEventListener('touchend', onTouchEnd, { capture: true, passive: true });
  document.addEventListener('touchcancel', onTouchCancel, { capture: true, passive: true });
  document.addEventListener('contextmenu', onNativeContextMenu, { capture: true });

  return true;
}

/** 仅测试用：重置内部状态。 */
export function __resetForTests() {
  clearPending();
  endedPress = null;
  if (typeof window !== 'undefined') {
    try {
      delete window[INSTALL_FLAG];
    } catch (err) {
      window[INSTALL_FLAG] = false;
    }
  }
  if (typeof document !== 'undefined' && document.removeEventListener) {
    document.removeEventListener('touchstart', onTouchStart, { capture: true });
    document.removeEventListener('touchmove', onTouchMove, { capture: true });
    document.removeEventListener('touchend', onTouchEnd, { capture: true });
    document.removeEventListener('touchcancel', onTouchCancel, { capture: true });
    document.removeEventListener('contextmenu', onNativeContextMenu, { capture: true });
  }
}
