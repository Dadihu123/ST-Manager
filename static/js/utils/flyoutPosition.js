/**
 * static/js/utils/flyoutPosition.js
 * 二级菜单浮层定位（右键菜单 / 批量菜单共用）。
 *
 * 展开方向固定为**向右**（与宿主批量菜单里「自动处理 / 来源更新」的子菜单一致）：
 * 浮层贴在父项右边、顶部与父项对齐。只有纵向做自适应——如果向下延伸会超出
 * 屏幕底部，就整体上移（浮层底边对齐父项底边，即「向上延申」），而不是改成
 * 向下展开。
 *
 * 为什么用 `position: fixed` 而不是 `absolute left-full`：一级菜单盒带
 * `max-height + overflow:auto`（`.ui-context-menu` 还是 `overflow:hidden`），
 * absolute 子元素会被裁掉——「运行自动化」的规则集子菜单就是这么坏的。
 *
 * 尺寸必须在**渲染后**测量：这里只做定位，调用方负责先让浮层可见
 * （`$nextTick` + `requestAnimationFrame`），量不到尺寸时返回 null 由调用方重试。
 */

/** 浮层与视口边缘的安全距离（px）。 */
export const FLYOUT_VIEWPORT_MARGIN = 8;

/** 浮层与父项之间的间距（px）。 */
export const FLYOUT_ANCHOR_GAP = 4;

/**
 * 把模板传进来的锚点归一化成元素。
 *
 * 模板里容易写成 `toggleSubmenu(key, $event)`：Alpine 的 `$event` 是**事件对象**，
 * 不是元素，直接量矩形会拿到 `undefined`，浮层就永远停在初始位置。
 * 这里同时接受事件（取 `currentTarget`，退回 `target`）与元素本身。
 *
 * @param {Event|Element|null} value
 * @returns {Element|null}
 */
export function resolveAnchorElement(value) {
    if (!value) return null;
    if (typeof value.getBoundingClientRect === 'function') return value;
    const candidate = value.currentTarget || value.target || null;
    if (candidate && typeof candidate.getBoundingClientRect === 'function') return candidate;
    return null;
}

/**
 * 纯函数：由父项矩形、浮层尺寸、视口尺寸算出 fixed 坐标。
 *
 * 水平：贴在父项右边（`left = parent.right + 4`）。右边放不下时翻到父项左边
 * （一级菜单本身已经贴右边缘时才会发生）；再放不下就钳进视口。
 *
 * 垂直：顶部与父项对齐（`top = parent.top`）。下方放不下就整体上移，
 * 让浮层底边对齐父项底边（`top = parent.bottom - height`）——这就是
 * 「列表向下延伸会超出屏幕时改为向上延伸」。上移后仍然贴到顶边时，
 * 贴 8px 并允许内部滚动（`maxHeight = innerHeight - 16`）。
 *
 * @param {{top:number,right:number,bottom:number,left:number}} anchorRect
 * @param {{width:number,height:number}} size
 * @param {{width:number,height:number}} viewport
 * @returns {{top:number,left:number,maxHeight:number,placement:'right'|'left'}}
 */
export function computeFlyoutPosition(anchorRect, size, viewport) {
    const margin = FLYOUT_VIEWPORT_MARGIN;
    const gap = FLYOUT_ANCHOR_GAP;
    const vw = Number((viewport && viewport.width) || 0);
    const vh = Number((viewport && viewport.height) || 0);
    const width = Number((size && size.width) || 0);
    const height = Number((size && size.height) || 0);
    const anchor = {
        top: Number((anchorRect && anchorRect.top) || 0),
        right: Number((anchorRect && anchorRect.right) || 0),
        bottom: Number((anchorRect && anchorRect.bottom) || 0),
        left: Number((anchorRect && anchorRect.left) || 0),
    };

    // 水平：默认向右展开；右侧真的放不下才翻到左边。
    let left = anchor.right + gap;
    let placement = 'right';
    if (left + width > vw - margin) {
        const leftSide = anchor.left - width - gap;
        if (leftSide >= margin) {
            left = leftSide;
            placement = 'left';
        } else {
            // 两边都放不下（浮层比剩余空间还宽）：钳进视口，仍按向右处理。
            left = Math.max(margin, vw - margin - width);
        }
    }

    // 垂直：顶部对齐；下方溢出就整体上移（向上延申）。
    let top = anchor.top;
    let maxHeight = 0;
    if (top + height > vh - margin) {
        top = anchor.bottom - height;
        if (top < margin) {
            // 上移也放不下（浮层比视口还高）：贴顶 + 内部滚动。
            top = margin;
            maxHeight = Math.max(0, vh - margin * 2);
        }
    }

    return {
        top: Math.round(top),
        left: Math.round(left),
        maxHeight: Math.round(maxHeight),
        placement,
    };
}

/**
 * 测量已渲染的浮层并把它定位到父项右边。
 *
 * 注意：`max-height` 会改变元素高度，所以每次都要先清掉上一次的钳制再量
 * 自然高度，否则反复开关后浮层会越量越矮。
 *
 * @param {HTMLElement} flyoutEl 二级浮层（必须已可见，否则量到 0）
 * @param {Element|Event} anchorEl 父项按钮（也接受事件，见 `resolveAnchorElement`）
 * @returns {{top:number,left:number,maxHeight:number,placement:string}|null}
 */
export function positionFlyoutElement(flyoutEl, anchorEl) {
    if (!flyoutEl || typeof window === 'undefined') return null;
    const anchor = resolveAnchorElement(anchorEl);
    if (!anchor) return null;

    const anchorRect = anchor.getBoundingClientRect();
    // 清掉上一次的高度钳制，量到的是自然高度。
    flyoutEl.style.maxHeight = '';
    flyoutEl.style.overflowY = '';
    const width = flyoutEl.offsetWidth;
    const height = flyoutEl.offsetHeight;
    // `x-show` 刚切到可见时可能还没完成布局：返回 null 让调用方下一帧重试。
    if (!width || !height) return null;

    const position = computeFlyoutPosition(
        anchorRect,
        { width, height },
        { width: window.innerWidth, height: window.innerHeight },
    );

    flyoutEl.style.top = `${position.top}px`;
    flyoutEl.style.left = `${position.left}px`;
    if (position.maxHeight > 0) {
        flyoutEl.style.maxHeight = `${position.maxHeight}px`;
        flyoutEl.style.overflowY = 'auto';
    }
    return position;
}
