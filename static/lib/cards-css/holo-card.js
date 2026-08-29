import { adjust, clamp, round } from "./math.js";
import { Spring } from "./spring.js";
import { CLASS, applyVars, buildLayerElement, cssUrl, normalizeMask } from "./dom.js";
import { getActiveCard, setActiveCard, subscribeActiveCard } from "./active-registry.js";
import { resetBaseOrientation, subscribeOrientation } from "./orientation.js";
import { generateTextures, mulberry32, texturesToCssVariables } from "./textures.js";
import { paletteToCssVariables, PALETTE_VARIABLES } from "./palette.js";
const requestFrame = (cb) => typeof requestAnimationFrame !== "undefined" ? requestAnimationFrame(cb) : setTimeout(cb, 16);
const cancelFrame = (id) => {
    if (typeof cancelAnimationFrame !== "undefined") {
        cancelAnimationFrame(id);
    }
    else {
        clearTimeout(id);
    }
};
const stopTimeout = (id) => {
    if (id !== null) {
        clearTimeout(id);
    }
    return null;
};
const stopInterval = (id) => {
    if (id !== null) {
        clearInterval(id);
    }
    return null;
};
const prefersReducedMotion = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
// Elements that natively turn Enter (buttons also Space) into click events and
// carry their own semantics — keyboard activation is left to the browser there.
const isNativeActivator = (element) => {
    const tag = element.tagName;
    return tag === "BUTTON" || tag === "INPUT" || tag === "SUMMARY" || (tag === "A" && element.hasAttribute("href"));
};
const SPRING_INTERACT = { stiffness: 0.066, damping: 0.25 };
const SPRING_POPOVER = { stiffness: 0.033, damping: 0.45 };
const SNAP_STIFFNESS = 0.01;
const SNAP_DAMPING = 0.06;
const DEFAULT_MAX_TILT = 50 / 3.5;
const DEFAULT_PRECISION = 0.01;
const mergeAxes = (base, override) => {
    if (!base) {
        return override;
    }
    if (!override) {
        return base;
    }
    const out = { ...base };
    for (const key of Object.keys(override)) {
        out[key] = { ...base[key], ...override[key] };
    }
    return out;
};
const resolveDynamics = (base, override) => {
    const out = {
        stiffness: override?.stiffness ?? base.stiffness,
        damping: override?.damping ?? base.damping,
    };
    const precision = override?.precision ?? base.precision;
    if (precision !== undefined) {
        out.precision = precision;
    }
    const axes = mergeAxes(base.axes, override?.axes);
    if (axes !== undefined) {
        out.axes = axes;
    }
    return out;
};
const assignDynamics = (spring, dyn) => {
    spring.stiffness = dyn.stiffness;
    spring.damping = dyn.damping;
    spring.precision = dyn.precision ?? DEFAULT_PRECISION;
    spring.axes = dyn.axes;
};
const cssDimension = (value, unit) => typeof value === "number" ? `${value}${unit}` : value;
const resolveShowcase = (showcase) => {
    const opts = showcase && typeof showcase === "object" ? showcase : {};
    return {
        delay: opts.delay ?? 2000,
        duration: opts.duration ?? 4000,
        loop: opts.loop ?? false,
        speed: opts.speed ?? 0.05,
        intensity: opts.intensity ?? 25,
        respectReducedMotion: opts.respectReducedMotion ?? true,
        dynamics: resolveDynamics({ stiffness: 0.02, damping: 0.5 }, opts.spring),
    };
};
const DEFAULT_GYRO_RANGE_X = 16;
const DEFAULT_GYRO_RANGE_Y = 18;
const resolveGyroscope = (gyroscope) => {
    const opts = gyroscope && typeof gyroscope === "object" ? gyroscope : {};
    const enabled = typeof gyroscope === "boolean" ? gyroscope : (opts.enabled ?? true);
    return {
        enabled,
        rangeX: opts.rangeX ?? DEFAULT_GYRO_RANGE_X,
        rangeY: opts.rangeY ?? DEFAULT_GYRO_RANGE_Y,
        sensitivity: opts.sensitivity ?? 1,
        invertX: opts.invertX ?? false,
        invertY: opts.invertY ?? false,
    };
};
const resolveDepth = (depth) => {
    const opts = depth && typeof depth === "object" ? depth : {};
    return {
        enabled: Boolean(depth),
        strength: opts.strength ?? 14,
        perspective: opts.perspective ?? 600,
        shadow: opts.shadow ?? 0.35,
        layerScale: opts.layerScale ?? 1,
    };
};
const DEFAULT_GLARE_STOPS = ["hsla(0, 0%, 100%, 0.8) 10%", "hsla(0, 0%, 100%, 0.65) 20%", "hsla(0, 0%, 0%, 0.5) 90%"];
const composeGlareImage = (glare) => {
    if (glare.image) {
        return glare.image;
    }
    if (glare.shape === undefined &&
        glare.extent === undefined &&
        glare.size === undefined &&
        glare.stops === undefined) {
        return undefined;
    }
    const sizeTokens = glare.size ? glare.size.trim().split(/\s+/) : [];
    const shape = glare.shape ?? (sizeTokens.length > 1 ? "ellipse" : "circle");
    const geometry = glare.size ? `${shape} ${glare.size}` : `${glare.extent ?? "farthest-corner"} ${shape}`;
    const stops = (glare.stops?.length ? glare.stops : DEFAULT_GLARE_STOPS).join(", ");
    return `radial-gradient(${geometry} at var(--pointer-x) var(--pointer-y), ${stops})`;
};
const DEPTH_VARS = ["--hc-depth", "--card-perspective", "--hc-depth-shadow", "--hc-depth-layer-scale"];
const RENDER_VARS = [
    "--pointer-x",
    "--pointer-y",
    "--pointer-from-center",
    "--pointer-from-top",
    "--pointer-from-left",
    "--pointer-dx",
    "--pointer-dy",
    "--card-opacity",
    "--rotate-x",
    "--rotate-y",
    "--tilt-x",
    "--tilt-y",
    "--background-x",
    "--background-y",
    "--card-scale",
    "--translate-x",
    "--translate-y",
];
export class HoloCard {
    element;
    rotator;
    frontElement;
    layersElement = null;
    options;
    gyroConfig;
    springRotate;
    springGlare;
    springBackground;
    springPointer;
    springRotateDelta;
    springTranslate;
    springScale;
    allSprings;
    liveRotate;
    liveGlare;
    liveBackground;
    livePointer;
    snapDynamics;
    tiltFactorX;
    tiltFactorY;
    tiltScaleX;
    tiltScaleY;
    parallax;
    glareRange;
    returnDelay;
    showcaseConfig;
    isInteracting = false;
    wasActive = false;
    manageAriaPressed = false;
    firstPop = true;
    isVisible = typeof document !== "undefined" ? document.visibilityState === "visible" : true;
    destroyed = false;
    renderScheduled = false;
    interactRaf = null;
    pendingUpdate = null;
    repositionTimer = null;
    endTimer = null;
    showcaseStart = null;
    showcaseEnd = null;
    showcaseInterval = null;
    showcaseRunning;
    cleanups = [];
    unsubscribeOrientation = null;
    constructor(element, options = {}) {
        this.element = element;
        const rotator = element.querySelector(`.${CLASS.rotator}`);
        if (!rotator) {
            throw new Error("@kongyo2/cards-css: holo card element is missing its .holo-card__rotator child.");
        }
        this.rotator = rotator;
        this.frontElement = element.querySelector(`.${CLASS.front}`);
        this.layersElement = element.querySelector(`.${CLASS.layers}`);
        this.options = {
            interactive: options.interactive ?? true,
            activateOnClick: options.activateOnClick ?? false,
            showcase: options.showcase ?? false,
        };
        this.gyroConfig = resolveGyroscope(options.gyroscope);
        this.showcaseRunning = Boolean(options.showcase);
        this.showcaseConfig = resolveShowcase(options.showcase);
        const physics = options.physics ?? {};
        const maxTiltX = physics.maxTiltX ?? physics.maxTilt ?? DEFAULT_MAX_TILT;
        const maxTiltY = physics.maxTiltY ?? physics.maxTilt ?? DEFAULT_MAX_TILT;
        this.tiltFactorX = maxTiltX / 50;
        this.tiltFactorY = maxTiltY / 50;
        this.tiltScaleX = maxTiltX / DEFAULT_MAX_TILT;
        this.tiltScaleY = maxTiltY / DEFAULT_MAX_TILT;
        this.parallax = physics.parallax ?? 1;
        this.glareRange = physics.glareRange ?? 1;
        this.returnDelay = physics.returnDelay ?? 500;
        const interactBase = resolveDynamics(SPRING_INTERACT, physics.interactSpring);
        const popoverBase = resolveDynamics(SPRING_POPOVER, physics.popoverSpring);
        this.snapDynamics = resolveDynamics({ stiffness: SNAP_STIFFNESS, damping: SNAP_DAMPING }, physics.snapSpring);
        this.liveRotate = resolveDynamics(interactBase, physics.springs?.rotate);
        this.liveGlare = resolveDynamics(interactBase, physics.springs?.glare);
        this.liveBackground = resolveDynamics(interactBase, physics.springs?.background);
        this.livePointer = interactBase;
        this.springRotate = new Spring({ x: 0, y: 0 }, this.liveRotate);
        this.springGlare = new Spring({ x: 50, y: 50, o: 0 }, this.liveGlare);
        this.springBackground = new Spring({ x: 50, y: 50 }, this.liveBackground);
        this.springPointer = new Spring({ x: 50, y: 50 }, this.livePointer);
        this.springRotateDelta = new Spring({ x: 0, y: 0 }, resolveDynamics(popoverBase, physics.springs?.rotateDelta));
        this.springTranslate = new Spring({ x: 0, y: 0 }, resolveDynamics(popoverBase, physics.springs?.translate));
        this.springScale = new Spring(1, resolveDynamics(popoverBase, physics.springs?.scale));
        this.allSprings = [
            this.springRotate,
            this.springGlare,
            this.springBackground,
            this.springPointer,
            this.springRotateDelta,
            this.springTranslate,
            this.springScale,
        ];
        if (options.effect) {
            element.dataset.effect = options.effect;
        }
        else if (!element.dataset.effect) {
            element.dataset.effect = "none";
        }
        this.applyPalette(options.palette);
        if (options.glow) {
            element.style.setProperty("--card-glow", options.glow);
        }
        if (typeof options.aspectRatio === "number") {
            element.style.setProperty("--card-aspect", String(options.aspectRatio));
        }
        const mask = normalizeMask(options.mask);
        if (mask?.image) {
            element.style.setProperty("--mask", cssUrl(mask.image));
            if (mask.size) {
                element.style.setProperty("--mask-size", mask.size);
            }
            if (mask.position) {
                element.style.setProperty("--mask-position", mask.position);
            }
            if (mask.repeat) {
                element.style.setProperty("--mask-repeat", mask.repeat);
            }
            element.classList.add(CLASS.masked);
            if (mask.mode === "card") {
                element.classList.add(CLASS.maskCard);
            }
        }
        if (options.foil) {
            element.style.setProperty("--foil", cssUrl(options.foil));
        }
        this.applyVisual(options.visual);
        this.applyGlare(options.glare);
        this.applyDepth(options.depth);
        applyVars(element, options.vars);
        if (!this.layersElement && options.layers?.length && this.frontElement) {
            for (const layer of options.layers) {
                this.addLayer(layer);
            }
        }
        this.applyStaticStyles(options.textureSeed);
        for (const spring of this.allSprings) {
            this.cleanups.push(spring.subscribe(() => this.scheduleRender()));
        }
        this.applyStyles();
        if (this.options.interactive) {
            this.enableInteractive();
        }
        this.cleanups.push(subscribeActiveCard(() => this.onActiveChange()));
        if (typeof document !== "undefined") {
            const onVisibility = () => this.onVisibilityChange();
            document.addEventListener("visibilitychange", onVisibility);
            this.cleanups.push(() => document.removeEventListener("visibilitychange", onVisibility));
        }
        if (this.options.showcase) {
            this.startShowcase();
        }
    }
    applyVisual(visual) {
        if (!visual) {
            return;
        }
        const style = this.element.style;
        const setNumber = (property, value) => {
            if (typeof value === "number") {
                style.setProperty(property, String(value));
            }
        };
        setNumber("--hc-brightness", visual.brightness);
        setNumber("--hc-contrast", visual.contrast);
        setNumber("--hc-saturate", visual.saturate);
        setNumber("--hc-glare-opacity", visual.glareOpacity);
        setNumber("--hc-shine-opacity", visual.shineOpacity);
        if (visual.lineSpace !== undefined) {
            style.setProperty("--space", cssDimension(visual.lineSpace, "%"));
        }
        if (visual.lineAngle !== undefined) {
            style.setProperty("--angle", cssDimension(visual.lineAngle, "deg"));
        }
        if (visual.glitterSize !== undefined) {
            style.setProperty("--glittersize", cssDimension(visual.glitterSize, "%"));
        }
        if (visual.imageFit !== undefined) {
            style.setProperty("--imgsize", visual.imageFit);
        }
    }
    applyPalette(palette) {
        if (!palette) {
            return;
        }
        const style = this.element.style;
        const vars = paletteToCssVariables(palette);
        for (const name of PALETTE_VARIABLES) {
            style.removeProperty(name);
        }
        for (const [name, value] of Object.entries(vars)) {
            style.setProperty(name, value);
        }
    }
    applyGlare(glare) {
        if (!glare) {
            return;
        }
        const style = this.element.style;
        style.removeProperty("--glare-image");
        style.removeProperty("--glare-blend");
        this.element.classList.remove(CLASS.customGlare);
        if (typeof glare.opacity === "number") {
            style.setProperty("--hc-glare-opacity", String(glare.opacity));
        }
        if (glare.blend !== undefined) {
            style.setProperty("--glare-blend", glare.blend);
        }
        const image = composeGlareImage(glare);
        if (image !== undefined) {
            style.setProperty("--glare-image", image);
            this.element.classList.add(CLASS.customGlare);
        }
    }
    applyDepth(depth) {
        const style = this.element.style;
        const config = resolveDepth(depth);
        if (!config.enabled) {
            this.element.classList.remove(CLASS.depth);
            for (const name of DEPTH_VARS) {
                style.removeProperty(name);
            }
            return;
        }
        this.element.classList.add(CLASS.depth);
        style.setProperty("--hc-depth", `${config.strength}px`);
        style.setProperty("--card-perspective", `${config.perspective}px`);
        style.setProperty("--hc-depth-shadow", String(config.shadow));
        style.setProperty("--hc-depth-layer-scale", String(config.layerScale));
    }
    applyStaticStyles(seed) {
        const rng = typeof seed === "number" ? mulberry32(seed) : Math.random;
        const seedX = rng();
        const seedY = rng();
        const cosmosX = Math.floor(seedX * 734);
        const cosmosY = Math.floor(seedY * 1280);
        this.element.style.setProperty("--seedx", String(seedX));
        this.element.style.setProperty("--seedy", String(seedY));
        this.element.style.setProperty("--cosmosbg", `${cosmosX}px ${cosmosY}px`);
        if (typeof seed === "number") {
            const vars = texturesToCssVariables(generateTextures({ seed }));
            for (const [name, value] of Object.entries(vars)) {
                this.element.style.setProperty(name, value);
            }
        }
    }
    enableInteractive() {
        this.element.classList.add(CLASS.interactive);
        const onPointerMove = (event) => this.interact(event);
        const onPointerLeave = () => this.interactEnd();
        const onPointerCancel = () => this.interactEnd(0);
        this.rotator.addEventListener("pointermove", onPointerMove);
        this.rotator.addEventListener("pointerleave", onPointerLeave);
        this.rotator.addEventListener("pointercancel", onPointerCancel);
        this.cleanups.push(() => this.rotator.removeEventListener("pointermove", onPointerMove));
        this.cleanups.push(() => this.rotator.removeEventListener("pointerleave", onPointerLeave));
        this.cleanups.push(() => this.rotator.removeEventListener("pointercancel", onPointerCancel));
        if (this.options.activateOnClick) {
            const onClick = () => this.toggleActive();
            const onFocusOut = (event) => {
                const next = event.relatedTarget;
                if (next instanceof Node && this.element.contains(next)) {
                    return;
                }
                if (this.active) {
                    this.deactivate();
                }
            };
            this.rotator.addEventListener("click", onClick);
            this.rotator.addEventListener("focusout", onFocusOut);
            this.cleanups.push(() => this.rotator.removeEventListener("click", onClick));
            this.cleanups.push(() => this.rotator.removeEventListener("focusout", onFocusOut));
            if (this.rotator.tabIndex < 0) {
                this.rotator.tabIndex = 0;
                this.cleanups.push(() => this.rotator.removeAttribute("tabindex"));
            }
            const nativeActivator = isNativeActivator(this.rotator);
            // aria-pressed belongs on button-like rotators only, and only when the
            // consumer is not already managing the attribute themselves.
            if ((!nativeActivator || this.rotator.tagName === "BUTTON") && !this.rotator.hasAttribute("aria-pressed")) {
                this.manageAriaPressed = true;
                this.rotator.setAttribute("aria-pressed", "false");
                this.cleanups.push(() => {
                    this.rotator.removeAttribute("aria-pressed");
                    this.manageAriaPressed = false;
                });
            }
            if (!nativeActivator) {
                if (!this.rotator.hasAttribute("role")) {
                    this.rotator.setAttribute("role", "button");
                    this.cleanups.push(() => this.rotator.removeAttribute("role"));
                }
                // Only keystrokes aimed at the rotator itself count — events bubbling
                // up from focusable content (interactive overlays, links) must keep
                // their native behaviour. Space toggles on keyup per the ARIA button
                // pattern; keydown swallows it (key repeats included) so the page
                // does not scroll, while Enter activates on first keydown only.
                const onKeyDown = (event) => {
                    if (event.target !== this.rotator) {
                        return;
                    }
                    if (event.key === " ") {
                        event.preventDefault();
                    }
                    else if (event.key === "Enter" && !event.repeat) {
                        event.preventDefault();
                        this.toggleActive();
                    }
                };
                const onKeyUp = (event) => {
                    if (event.target === this.rotator && event.key === " ") {
                        event.preventDefault();
                        this.toggleActive();
                    }
                };
                this.rotator.addEventListener("keydown", onKeyDown);
                this.rotator.addEventListener("keyup", onKeyUp);
                this.cleanups.push(() => this.rotator.removeEventListener("keydown", onKeyDown));
                this.cleanups.push(() => this.rotator.removeEventListener("keyup", onKeyUp));
            }
            const interactiveOverlay = this.element.querySelector(`.${CLASS.overlayInteractive}`);
            if (interactiveOverlay) {
                const stopClick = (event) => event.stopPropagation();
                interactiveOverlay.addEventListener("click", stopClick);
                this.cleanups.push(() => interactiveOverlay.removeEventListener("click", stopClick));
            }
            const onScroll = () => this.reposition();
            window.addEventListener("scroll", onScroll, { passive: true });
            window.addEventListener("resize", onScroll, { passive: true });
            this.cleanups.push(() => window.removeEventListener("scroll", onScroll));
            this.cleanups.push(() => window.removeEventListener("resize", onScroll));
        }
    }
    parallaxBackground(x, y) {
        return { x: round(50 + (x - 50) * this.parallax), y: round(50 + (y - 50) * this.parallax) };
    }
    rangeGlare(x, y, o) {
        return { x: round(50 + (x - 50) * this.glareRange), y: round(50 + (y - 50) * this.glareRange), o };
    }
    interact(event) {
        this.endShowcase();
        if (!this.isVisible) {
            this.setInteracting(false);
            return;
        }
        const active = getActiveCard();
        if (active && active !== this) {
            this.setInteracting(false);
            return;
        }
        const rect = this.rotator.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            return;
        }
        this.setInteracting(true);
        this.endTimer = stopTimeout(this.endTimer);
        const absolute = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        const percent = {
            x: clamp(round((100 / rect.width) * absolute.x)),
            y: clamp(round((100 / rect.height) * absolute.y)),
        };
        const center = { x: percent.x - 50, y: percent.y - 50 };
        this.pendingUpdate = {
            background: this.parallaxBackground(adjust(percent.x, 0, 100, 37, 63), adjust(percent.y, 0, 100, 33, 67)),
            rotate: { x: round(-(center.x * this.tiltFactorX)), y: round(center.y * this.tiltFactorY) },
            glare: this.rangeGlare(round(percent.x), round(percent.y), 1),
            pointer: { x: round(percent.x), y: round(percent.y) },
        };
        if (this.interactRaf === null) {
            this.interactRaf = requestFrame(() => {
                if (this.pendingUpdate) {
                    const update = this.pendingUpdate;
                    this.updateSprings(update.background, update.rotate, update.glare, update.pointer);
                    this.pendingUpdate = null;
                }
                this.interactRaf = null;
            });
        }
    }
    interactEnd(delay = this.returnDelay) {
        if (this.interactRaf !== null) {
            cancelFrame(this.interactRaf);
            this.interactRaf = null;
        }
        this.pendingUpdate = null;
        this.endTimer = stopTimeout(this.endTimer);
        this.endTimer = setTimeout(() => {
            this.setInteracting(false);
            this.setGroupDynamics(this.snapDynamics);
            void this.springRotate.set({ x: 0, y: 0 }, { soft: 1 });
            void this.springGlare.set({ x: 50, y: 50, o: 0 }, { soft: 1 });
            void this.springBackground.set({ x: 50, y: 50 }, { soft: 1 });
            void this.springPointer.set({ x: 50, y: 50 }, { soft: 1 });
        }, delay);
    }
    setGroupDynamics(dyn) {
        assignDynamics(this.springRotate, dyn);
        assignDynamics(this.springGlare, dyn);
        assignDynamics(this.springBackground, dyn);
        assignDynamics(this.springPointer, dyn);
    }
    applyLiveDynamics() {
        assignDynamics(this.springRotate, this.liveRotate);
        assignDynamics(this.springGlare, this.liveGlare);
        assignDynamics(this.springBackground, this.liveBackground);
        assignDynamics(this.springPointer, this.livePointer);
    }
    settle(opts) {
        void this.springScale.set(1, opts);
        void this.springTranslate.set({ x: 0, y: 0 }, opts);
        void this.springRotateDelta.set({ x: 0, y: 0 }, opts);
    }
    updateSprings(background, rotate, glare, pointer) {
        this.applyLiveDynamics();
        void this.springBackground.set(background);
        void this.springRotate.set(rotate);
        void this.springGlare.set(glare);
        void this.springPointer.set(pointer);
    }
    setInteracting(value) {
        this.isInteracting = value;
        this.element.classList.toggle(CLASS.interacting, value);
    }
    get interacting() {
        return this.isInteracting;
    }
    scheduleRender() {
        if (this.renderScheduled) {
            return;
        }
        this.renderScheduled = true;
        requestFrame(() => {
            this.renderScheduled = false;
            if (!this.destroyed) {
                this.applyStyles();
            }
        });
    }
    clearRenderVars() {
        const style = this.element.style;
        for (const name of RENDER_VARS) {
            style.removeProperty(name);
        }
    }
    applyStyles() {
        if (!this.options.interactive &&
            !this.isInteracting &&
            !this.active &&
            this.allSprings.every((spring) => spring.settled)) {
            // At rest, a non-interactive card sheds its inline vars so the pure-CSS
            // hover fallback can drive them; waiting for the springs keeps the
            // showcase/snap-back animation visible instead of jumping to rest.
            this.clearRenderVars();
            return;
        }
        const glare = this.springGlare.current;
        const rotate = this.springRotate.current;
        const rotateDelta = this.springRotateDelta.current;
        const background = this.springBackground.current;
        const pointer = this.springPointer.current;
        const translate = this.springTranslate.current;
        const scale = this.springScale.current;
        const fromCenter = clamp(Math.sqrt((glare.y - 50) * (glare.y - 50) + (glare.x - 50) * (glare.x - 50)) / 50, 0, 1);
        const style = this.element.style;
        style.setProperty("--pointer-x", `${glare.x}%`);
        style.setProperty("--pointer-y", `${glare.y}%`);
        style.setProperty("--pointer-from-center", String(fromCenter));
        style.setProperty("--pointer-from-top", String(glare.y / 100));
        style.setProperty("--pointer-from-left", String(glare.x / 100));
        style.setProperty("--pointer-dx", String(round((pointer.x - 50) / 50)));
        style.setProperty("--pointer-dy", String(round((pointer.y - 50) / 50)));
        style.setProperty("--card-opacity", String(glare.o));
        style.setProperty("--rotate-x", `${rotate.x + rotateDelta.x}deg`);
        style.setProperty("--rotate-y", `${rotate.y + rotateDelta.y}deg`);
        style.setProperty("--tilt-x", String(round(rotate.x + rotateDelta.x)));
        style.setProperty("--tilt-y", String(round(rotate.y + rotateDelta.y)));
        style.setProperty("--background-x", `${background.x}%`);
        style.setProperty("--background-y", `${background.y}%`);
        style.setProperty("--card-scale", String(scale));
        style.setProperty("--translate-x", `${translate.x}px`);
        style.setProperty("--translate-y", `${translate.y}px`);
    }
    onActiveChange() {
        const isActive = getActiveCard() === this;
        if (isActive === this.wasActive) {
            // Only transitions matter: the registry notifies every card on every
            // change, and cards that were never active must not retreat (that would
            // reassign their spring dynamics mid-interaction or mid-showcase).
            return;
        }
        this.wasActive = isActive;
        if (this.manageAriaPressed) {
            this.rotator.setAttribute("aria-pressed", String(isActive));
        }
        if (isActive) {
            this.popover();
            this.element.classList.add(CLASS.active);
            this.element.style.setProperty("--card-active", "1");
            if (this.gyroConfig.enabled) {
                this.startGyroscope();
            }
        }
        else {
            this.retreat();
            this.element.classList.remove(CLASS.active);
            this.element.style.setProperty("--card-active", "0");
            this.stopGyroscope();
        }
    }
    popover() {
        const rect = this.element.getBoundingClientRect();
        let delay = 100;
        const scaleW = (window.innerWidth / rect.width) * 0.9;
        const scaleH = (window.innerHeight / rect.height) * 0.9;
        const scaleF = 1.75;
        this.setCenter();
        if (this.firstPop) {
            delay = 1000;
            void this.springRotateDelta.set({ x: 360, y: 0 });
        }
        this.firstPop = false;
        void this.springScale.set(Math.min(scaleW, scaleH, scaleF));
        this.interactEnd(delay);
    }
    retreat() {
        this.settle({ soft: true });
        this.interactEnd(100);
    }
    reset() {
        this.interactEnd(0);
        this.settle({ hard: true });
        void this.springRotate.set({ x: 0, y: 0 }, { hard: true });
    }
    setCenter() {
        const rect = this.element.getBoundingClientRect();
        const view = document.documentElement;
        void this.springTranslate.set({
            x: round(view.clientWidth / 2 - rect.x - rect.width / 2),
            y: round(view.clientHeight / 2 - rect.y - rect.height / 2),
        });
    }
    reposition() {
        this.repositionTimer = stopTimeout(this.repositionTimer);
        this.repositionTimer = setTimeout(() => {
            if (getActiveCard() === this) {
                this.setCenter();
            }
        }, 300);
    }
    startGyroscope() {
        if (this.unsubscribeOrientation) {
            return;
        }
        this.unsubscribeOrientation = subscribeOrientation((orientation) => this.orientate(orientation));
    }
    stopGyroscope() {
        if (this.unsubscribeOrientation) {
            this.unsubscribeOrientation();
            this.unsubscribeOrientation = null;
        }
    }
    orientate(orientation) {
        if (getActiveCard() !== this) {
            return;
        }
        const gyro = this.gyroConfig;
        const limit = { x: gyro.rangeX, y: gyro.rangeY };
        const dirX = gyro.invertX ? -1 : 1;
        const dirY = gyro.invertY ? -1 : 1;
        const degrees = {
            x: clamp(orientation.relative.gamma * gyro.sensitivity * dirX, -limit.x, limit.x),
            y: clamp(orientation.relative.beta * gyro.sensitivity * dirY, -limit.y, limit.y),
        };
        const fracX = limit.x === 0 ? 0 : degrees.x / limit.x;
        const fracY = limit.y === 0 ? 0 : degrees.y / limit.y;
        const gx = adjust(fracX, -1, 1, 0, 100);
        const gy = adjust(fracY, -1, 1, 0, 100);
        this.setInteracting(true);
        this.updateSprings(this.parallaxBackground(adjust(fracX, -1, 1, 37, 63), adjust(fracY, -1, 1, 33, 67)), {
            x: round(fracX * DEFAULT_GYRO_RANGE_X * -1 * this.tiltScaleX),
            y: round(fracY * DEFAULT_GYRO_RANGE_Y * this.tiltScaleY),
        }, this.rangeGlare(gx, gy, 1), { x: gx, y: gy });
    }
    onVisibilityChange() {
        this.isVisible = document.visibilityState === "visible";
        this.endShowcase();
        if (this.active) {
            // Keep the popover: hard-settling scale/translate here would visually
            // retreat the card while it stays active in the registry.
            this.interactEnd(0);
        }
        else {
            this.reset();
        }
    }
    startShowcase() {
        if (!this.isVisible) {
            return;
        }
        const config = this.showcaseConfig;
        if (config.respectReducedMotion && prefersReducedMotion()) {
            return;
        }
        const amp = config.intensity;
        let r = 0;
        this.showcaseStart = setTimeout(() => {
            this.endTimer = stopTimeout(this.endTimer);
            this.setInteracting(true);
            this.setGroupDynamics(config.dynamics);
            if (!this.isVisible) {
                this.setInteracting(false);
                return;
            }
            this.showcaseInterval = setInterval(() => {
                r += config.speed;
                void this.springRotate.set({ x: Math.sin(r) * amp, y: Math.cos(r) * amp });
                void this.springGlare.set({
                    x: 50 + Math.sin(r) * amp * 2.2,
                    y: 50 + Math.cos(r) * amp * 2.2,
                    o: 0.8,
                });
                void this.springBackground.set({
                    x: 50 + Math.sin(r) * amp * 0.8,
                    y: 50 + Math.cos(r) * amp * 0.8,
                });
                void this.springPointer.set({ x: 50 + Math.sin(r) * amp * 1.6, y: 50 + Math.cos(r) * amp * 1.6 });
            }, 20);
            if (!config.loop) {
                this.showcaseEnd = setTimeout(() => {
                    this.showcaseInterval = stopInterval(this.showcaseInterval);
                    this.interactEnd(0);
                }, config.duration);
            }
        }, config.delay);
    }
    endShowcase() {
        if (!this.showcaseRunning) {
            return;
        }
        this.showcaseEnd = stopTimeout(this.showcaseEnd);
        this.showcaseStart = stopTimeout(this.showcaseStart);
        this.showcaseInterval = stopInterval(this.showcaseInterval);
        this.showcaseRunning = false;
    }
    toggleActive() {
        if (getActiveCard() === this) {
            setActiveCard(null);
        }
        else {
            this.endShowcase();
            resetBaseOrientation();
            setActiveCard(this);
        }
    }
    activate() {
        if (getActiveCard() !== this) {
            this.endShowcase();
            resetBaseOrientation();
            setActiveCard(this);
        }
    }
    deactivate() {
        this.interactEnd();
        if (getActiveCard() === this) {
            setActiveCard(null);
        }
    }
    setEffect(effect) {
        this.element.dataset.effect = effect ?? "none";
    }
    /** The `.holo-card__front` element, for appending custom content at runtime. */
    get front() {
        return this.frontElement;
    }
    /** Apply CSS custom properties to the root element (for content linkage). */
    setVars(vars) {
        applyVars(this.element, vars);
    }
    /** Update fine-grained visual controls at runtime. */
    setVisual(visual) {
        this.applyVisual(visual);
    }
    /**
     * Swap the foil colour palette / theme at runtime. This is a full replacement:
     * any palette variable not present in `palette` reverts to its default.
     */
    setPalette(palette) {
        this.applyPalette(palette);
    }
    /**
     * Update the dynamic glare (reflected light) at runtime. The image / shape /
     * blend are replaced wholesale — omit them to return to the effect's built-in
     * glare. `opacity` is shared with `visual.glareOpacity` and only changes when
     * provided.
     */
    setGlare(glare) {
        this.applyGlare(glare);
    }
    /** Toggle or tune the foil 3D depth / extrusion at runtime. */
    setDepth(depth) {
        this.applyDepth(depth);
    }
    /** Update the gyroscope physical-behaviour tuning at runtime. */
    setGyroscope(gyroscope) {
        const wasEnabled = this.gyroConfig.enabled;
        this.gyroConfig = resolveGyroscope(gyroscope);
        if (getActiveCard() !== this) {
            return;
        }
        if (this.gyroConfig.enabled) {
            if (!wasEnabled) {
                resetBaseOrientation();
            }
            this.startGyroscope();
        }
        else {
            this.stopGyroscope();
            this.interactEnd(0);
        }
    }
    /**
     * Insert an extra layer between the artwork and the foil at runtime, returning
     * the created element. Requires the card to have a `.holo-card__front`.
     */
    addLayer(layer) {
        const front = this.frontElement;
        if (!front) {
            throw new Error("@kongyo2/cards-css: cannot add a layer — the card has no .holo-card__front element.");
        }
        const doc = front.ownerDocument;
        const element = buildLayerElement(doc, layer);
        if (!this.layersElement) {
            const container = doc.createElement("div");
            container.className = CLASS.layers;
            const shine = front.querySelector(`.${CLASS.shine}`);
            front.insertBefore(container, shine);
            this.layersElement = container;
        }
        this.layersElement.appendChild(element);
        return element;
    }
    get active() {
        return getActiveCard() === this;
    }
    destroy() {
        if (this.destroyed) {
            return;
        }
        this.destroyed = true;
        this.endShowcase();
        this.stopGyroscope();
        // Unsubscribe (and remove listeners) before releasing the active slot so
        // this card does not react to its own deactivation mid-teardown.
        for (const cleanup of this.cleanups) {
            cleanup();
        }
        this.cleanups.length = 0;
        if (getActiveCard() === this) {
            setActiveCard(null);
        }
        this.repositionTimer = stopTimeout(this.repositionTimer);
        this.endTimer = stopTimeout(this.endTimer);
        if (this.interactRaf !== null) {
            cancelFrame(this.interactRaf);
            this.interactRaf = null;
        }
        this.pendingUpdate = null;
        for (const spring of this.allSprings) {
            spring.destroy();
        }
        this.clearRenderVars();
        this.element.style.removeProperty("--card-active");
        this.element.classList.remove(CLASS.interactive, CLASS.interacting, CLASS.active);
    }
}
//# sourceMappingURL=holo-card.js.map