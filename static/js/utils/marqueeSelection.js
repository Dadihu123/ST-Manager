const DEFAULT_DRAG_THRESHOLD = 6;
const INTERACTIVE_TARGET_SELECTOR = [
  "a",
  "button",
  "input",
  "label",
  "option",
  "select",
  "textarea",
  "[contenteditable=\"true\"]",
  "[data-marquee-ignore]",
].join(", ");

function getElement(target) {
  if (target && typeof target.closest === "function") {
    return target;
  }
  return target?.parentElement || null;
}

function normalizeRect(startX, startY, endX, endY) {
  return {
    left: Math.min(startX, endX),
    top: Math.min(startY, endY),
    width: Math.abs(endX - startX),
    height: Math.abs(endY - startY),
  };
}

function isPointInsideRect(x, y, rect) {
  return (
    x >= rect.left &&
    x <= rect.right &&
    y >= rect.top &&
    y <= rect.bottom
  );
}

function mergeSelectionIds(baseIds, marqueeIds) {
  return [...new Set([...baseIds, ...marqueeIds])];
}

export function createMarqueeSelection(config = {}) {
  const {
    mode,
    rootId,
    itemSelector,
    getId = (element) => element?.dataset?.id,
    canSelectElement = () => true,
    isDisabled = () => false,
    threshold = DEFAULT_DRAG_THRESHOLD,
  } = config;

  const isModeActive = (component) => {
    const currentMode = component.$store?.global?.currentMode;
    return currentMode === undefined || currentMode === mode;
  };

  const getRoot = () => {
    if (typeof document === "undefined") return null;
    return document.getElementById(rootId);
  };

  const canSelect = (component, element) => {
    try {
      return Boolean(canSelectElement(element, component));
    } catch (error) {
      console.warn("Marquee selection skipped an invalid item", error);
      return false;
    }
  };

  const resolveId = (component, element) => {
    try {
      const id = getId(element, component);
      return id === undefined || id === null || id === "" ? null : id;
    } catch (error) {
      console.warn("Marquee selection could not resolve an item id", error);
      return null;
    }
  };

  const getContentPoint = (root, event) => {
    const rootRect = root.getBoundingClientRect();
    return {
      x: event.clientX - rootRect.left + root.scrollLeft,
      y: event.clientY - rootRect.top + root.scrollTop,
    };
  };

  const getSelectionClientRect = (root, contentRect) => {
    const rootRect = root.getBoundingClientRect();
    return {
      left: contentRect.left - root.scrollLeft + rootRect.left,
      top: contentRect.top - root.scrollTop + rootRect.top,
      right:
        contentRect.left - root.scrollLeft + rootRect.left + contentRect.width,
      bottom:
        contentRect.top - root.scrollTop + rootRect.top + contentRect.height,
    };
  };

  const setSelectionVisualState = (component, active, rect) => {
    getRoot()?.classList.toggle("is-marquee-selecting", active);
    component.marqueeSelection.active = active;
    component.marqueeSelection.rect = rect || {
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    };
    component.marqueeSelectionStyle = active
      ? {
          left: `${component.marqueeSelection.rect.left}px`,
          top: `${component.marqueeSelection.rect.top}px`,
          width: `${component.marqueeSelection.rect.width}px`,
          height: `${component.marqueeSelection.rect.height}px`,
        }
      : {
          left: "0px",
          top: "0px",
          width: "0px",
          height: "0px",
        };
  };

  const releasePointerCapture = (session) => {
    if (!session?.root?.releasePointerCapture) return;
    try {
      if (
        !session.root.hasPointerCapture ||
        session.root.hasPointerCapture(session.pointerId)
      ) {
        session.root.releasePointerCapture(session.pointerId);
      }
    } catch (error) {
      // Pointer capture can already be released by the browser.
    }
  };

  const getItemIdAtPoint = (component, root, clientX, clientY) => {
    const point = { x: clientX, y: clientY };
    const elements = root.querySelectorAll(itemSelector);
    for (const element of elements) {
      if (!canSelect(component, element)) continue;
      const rect = element.getBoundingClientRect();
      if (isPointInsideRect(point.x, point.y, rect)) {
        return resolveId(component, element);
      }
    }
    return null;
  };

  const applySelection = (component, session, selectionClientRect) => {
    const marqueeIds = [];
    const elements = session.root.querySelectorAll(itemSelector);

    for (const element of elements) {
      if (!canSelect(component, element)) continue;
      const rect = element.getBoundingClientRect();
      const centerX = (rect.left + rect.right) / 2;
      const centerY = (rect.top + rect.bottom) / 2;
      if (!isPointInsideRect(centerX, centerY, selectionClientRect)) continue;

      const id = resolveId(component, element);
      if (id !== null) marqueeIds.push(id);
    }

    session.lastMarqueeIds = marqueeIds;
    component.selectedIds = session.additive
      ? mergeSelectionIds(session.baseSelection, marqueeIds)
      : marqueeIds;
  };

  const isStartTarget = (root, event) => {
    const target = getElement(event.target);
    if (!target || !root.contains(target)) return false;
    if (target.closest(itemSelector)) return false;
    if (target.closest(INTERACTIVE_TARGET_SELECTOR)) return false;
    if (target.closest(".drag-over-main-overlay")) return false;

    const rootRect = root.getBoundingClientRect();
    const verticalScrollbarWidth = Math.max(0, root.offsetWidth - root.clientWidth);
    const horizontalScrollbarHeight = Math.max(0, root.offsetHeight - root.clientHeight);
    if (
      verticalScrollbarWidth > 0 &&
      event.clientX >= rootRect.right - verticalScrollbarWidth
    ) {
      return false;
    }
    if (
      horizontalScrollbarHeight > 0 &&
      event.clientY >= rootRect.bottom - horizontalScrollbarHeight
    ) {
      return false;
    }
    return true;
  };

  const isPrimaryMousePointer = (event) =>
    event.button === 0 &&
    event.pointerType === "mouse" &&
    event.isPrimary !== false;

  const scheduleClickSuppression = (component) => {
    if (component._marqueeSuppressTimer) {
      clearTimeout(component._marqueeSuppressTimer);
    }
    component._marqueeSuppressClick = true;
    component._marqueeSuppressTimer = setTimeout(() => {
      component._marqueeSuppressClick = false;
      component._marqueeSuppressTimer = null;
    }, 0);
  };

  return {
    marqueeSelection: {
      active: false,
      rect: { left: 0, top: 0, width: 0, height: 0 },
    },
    marqueeSelectionStyle: {
      left: "0px",
      top: "0px",
      width: "0px",
      height: "0px",
    },
    _marqueeSession: null,
    _marqueeInitialized: false,
    _marqueeCancelHandler: null,
    _marqueeKeydownHandler: null,
    _marqueePointermoveHandler: null,
    _marqueePointerupHandler: null,
    _marqueePointercancelHandler: null,
    _marqueeSuppressClick: false,
    _marqueeSuppressTimer: null,

    initMarqueeSelection() {
      if (this._marqueeInitialized) return;
      this._marqueeInitialized = true;

      if (typeof window !== "undefined") {
        this._marqueeCancelHandler = (event) =>
          this.cancelMarqueeSelection({
            restoreSelection: event?.detail?.restoreSelection !== false,
          });
        window.addEventListener(
          "cancel-marquee-selection",
          this._marqueeCancelHandler,
        );
        window.addEventListener("blur", this._marqueeCancelHandler);
        this._marqueeKeydownHandler = (event) => {
          if (event.key === "Escape") this.cancelMarqueeSelection();
        };
        window.addEventListener("keydown", this._marqueeKeydownHandler);
        this._marqueePointermoveHandler = (event) => {
          const session = this._marqueeSession;
          const target = getElement(event.target);
          if (session && (!target || !session.root.contains(target))) {
            this.updateMarqueeSelection(event);
          }
        };
        this._marqueePointerupHandler = (event) => {
          this.endMarqueeSelection(event);
        };
        this._marqueePointercancelHandler = () => {
          this.cancelMarqueeSelection();
        };
        window.addEventListener("pointermove", this._marqueePointermoveHandler);
        window.addEventListener("pointerup", this._marqueePointerupHandler);
        window.addEventListener(
          "pointercancel",
          this._marqueePointercancelHandler,
        );
      }

      if (typeof this.$watch === "function") {
        this.$watch("$store.global.currentMode", (currentMode) => {
          if (currentMode !== mode) {
            this.cancelMarqueeSelection({ restoreSelection: false });
          }
        });
      }
    },

    beginMarqueeSelection(event) {
      if (
        !isPrimaryMousePointer(event) ||
        !isModeActive(this) ||
        this.$store?.global?.deviceType === "mobile"
      ) {
        return;
      }

      const root = getRoot();
      if (!root || isDisabled(this) || !isStartTarget(root, event)) return;

      if (this._marqueeSession) this.cancelMarqueeSelection();

      const point = getContentPoint(root, event);
      this._marqueeSession = {
        root,
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startContentX: point.x,
        startContentY: point.y,
        baseSelection: [...(this.selectedIds || [])],
        baseAnchor: this.lastSelectedId,
        additive: Boolean(event.ctrlKey || event.metaKey || event.shiftKey),
        moved: false,
        lastMarqueeIds: [],
      };
    },

    updateMarqueeSelection(event) {
      const session = this._marqueeSession;
      if (
        !session ||
        event.pointerId !== session.pointerId ||
        !isModeActive(this) ||
        isDisabled(this)
      ) {
        return;
      }

      const deltaX = event.clientX - session.startClientX;
      const deltaY = event.clientY - session.startClientY;
      if (!session.moved && Math.hypot(deltaX, deltaY) < threshold) return;

      if (!session.moved) {
        session.moved = true;
        try {
          session.root.setPointerCapture?.(session.pointerId);
        } catch (error) {
          // Pointer capture is optional; pointer events still work without it.
        }
        session.root.classList.add("is-marquee-selecting");
      }

      if (event.cancelable !== false) event.preventDefault();
      const point = getContentPoint(session.root, event);
      const contentRect = normalizeRect(
        session.startContentX,
        session.startContentY,
        point.x,
        point.y,
      );
      const selectionClientRect = getSelectionClientRect(
        session.root,
        contentRect,
      );
      setSelectionVisualState(this, true, contentRect);
      applySelection(this, session, selectionClientRect);
    },

    endMarqueeSelection(event) {
      const session = this._marqueeSession;
      if (!session || event.pointerId !== session.pointerId) return;

      if (!session.moved) {
        this._marqueeSession = null;
        releasePointerCapture(session);
        setSelectionVisualState(this, false);
        this.selectedIds = [];
        this.lastSelectedId = null;
        return;
      }

      this.updateMarqueeSelection(event);
      const endpointId = getItemIdAtPoint(
        this,
        session.root,
        event.clientX,
        event.clientY,
      );
      const lastMarqueeId =
        session.lastMarqueeIds[session.lastMarqueeIds.length - 1] ?? null;
      const selectedIds = [...(this.selectedIds || [])];
      const endpointIsSelected =
        endpointId !== null && selectedIds.includes(endpointId);

      this._marqueeSession = null;
      setSelectionVisualState(this, false);
      releasePointerCapture(session);
      this.lastSelectedId = endpointIsSelected
        ? endpointId
        : lastMarqueeId ?? selectedIds[selectedIds.length - 1] ?? null;
      scheduleClickSuppression(this);
    },

    cancelMarqueeSelection({ restoreSelection = true } = {}) {
      const session = this._marqueeSession;
      if (!session) {
        setSelectionVisualState(this, false);
        return;
      }

      this._marqueeSession = null;
      if (restoreSelection) {
        this.selectedIds = [...session.baseSelection];
        this.lastSelectedId = session.baseAnchor;
      }
      setSelectionVisualState(this, false);
      releasePointerCapture(session);
    },

    handleMarqueeClick(event) {
      if (this._marqueeSuppressClick) {
        this._marqueeSuppressClick = false;
        if (this._marqueeSuppressTimer) {
          clearTimeout(this._marqueeSuppressTimer);
          this._marqueeSuppressTimer = null;
        }
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation?.();
        return;
      }

      const target = getElement(event.target);
      if (
        !target ||
        target.closest(itemSelector) ||
        target.closest(INTERACTIVE_TARGET_SELECTOR) ||
        target.closest(".drag-over-main-overlay")
      ) {
        return;
      }

      this.selectedIds = [];
      this.lastSelectedId = null;
    },
  };
}
