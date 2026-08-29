export const CLASS = {
    root: "holo-card",
    translater: "holo-card__translater",
    rotator: "holo-card__rotator",
    front: "holo-card__front",
    back: "holo-card__back",
    image: "holo-card__image",
    content: "holo-card__content",
    layers: "holo-card__layers",
    layer: "holo-card__layer",
    overlay: "holo-card__overlay",
    shine: "holo-card__shine",
    glare: "holo-card__glare",
    interactive: "holo-card--interactive",
    active: "holo-card--active",
    interacting: "holo-card--interacting",
    loading: "holo-card--loading",
    masked: "holo-card--masked",
    maskCard: "holo-card--mask-card",
    depth: "holo-card--depth",
    customGlare: "holo-card--custom-glare",
    overlayInteractive: "holo-card__overlay--interactive",
};
const requireDocument = () => {
    if (typeof document === "undefined") {
        throw new Error("@kongyo2/cards-css: a DOM document is required to build a holo card element.");
    }
    return document;
};
export const applyVars = (element, vars) => {
    if (!vars) {
        return;
    }
    for (const [name, value] of Object.entries(vars)) {
        const property = name.startsWith("--") ? name : `--${name}`;
        element.style.setProperty(property, typeof value === "number" ? String(value) : value);
    }
};
const CSS_STRING_UNSAFE = /[\\"\n\r\f]/g;
export const cssUrl = (value) => `url("${value.replace(CSS_STRING_UNSAFE, (char) => `\\${char}`)}")`;
export const normalizeMask = (mask) => {
    if (!mask) {
        return null;
    }
    const opts = typeof mask === "string" ? { image: mask } : mask;
    if (!opts.image) {
        return null;
    }
    return {
        image: opts.image,
        size: opts.size,
        position: opts.position,
        repeat: opts.repeat,
        mode: opts.mode ?? "shine",
    };
};
const addClasses = (element, className) => {
    const names = className ? className.split(/\s+/).filter(Boolean) : [];
    if (names.length > 0) {
        element.classList.add(...names);
    }
};
const resolveContent = (doc, content) => typeof content === "function" ? content(doc) : content;
export const buildLayerElement = (doc, layer) => {
    const el = doc.createElement("div");
    el.className = CLASS.layer;
    addClasses(el, layer.className);
    if (typeof layer.blend === "string") {
        el.style.setProperty("--layer-blend", layer.blend);
    }
    if (typeof layer.opacity === "number") {
        el.style.setProperty("--layer-opacity", String(layer.opacity));
    }
    if (typeof layer.parallax === "number") {
        el.style.setProperty("--layer-parallax", String(layer.parallax));
    }
    if (layer.mask) {
        el.style.setProperty("--layer-mask", cssUrl(layer.mask));
        el.classList.add(`${CLASS.layer}--masked`);
    }
    if (layer.image) {
        el.style.setProperty("--layer-image", cssUrl(layer.image));
        el.style.setProperty("--layer-size", layer.size ?? "cover");
        el.style.setProperty("--layer-position", layer.position ?? "center");
    }
    applyVars(el, layer.vars);
    if (layer.content) {
        el.appendChild(resolveContent(doc, layer.content));
    }
    return el;
};
export const buildHoloCardElement = (options) => {
    const doc = requireDocument();
    const root = doc.createElement("div");
    root.className = CLASS.root;
    addClasses(root, options.className);
    root.dataset.effect = options.effect ?? "none";
    const mask = normalizeMask(options.mask);
    if (mask) {
        root.classList.add(CLASS.masked);
        if (mask.mode === "card") {
            root.classList.add(CLASS.maskCard);
        }
    }
    const translater = doc.createElement("div");
    translater.className = CLASS.translater;
    const rotator = doc.createElement("div");
    rotator.className = CLASS.rotator;
    if (options.back) {
        const back = doc.createElement("img");
        back.className = CLASS.back;
        back.src = options.back;
        back.alt = options.backAlt ?? "";
        back.loading = "lazy";
        rotator.appendChild(back);
    }
    const front = doc.createElement("div");
    front.className = CLASS.front;
    if (options.image) {
        const image = doc.createElement("img");
        image.className = CLASS.image;
        image.src = options.image;
        image.alt = options.imageAlt ?? "";
        image.loading = "lazy";
        front.appendChild(image);
    }
    if (options.content) {
        const content = doc.createElement("div");
        content.className = CLASS.content;
        content.appendChild(resolveContent(doc, options.content));
        front.appendChild(content);
    }
    if (options.layers?.length) {
        const layers = doc.createElement("div");
        layers.className = CLASS.layers;
        for (const layer of options.layers) {
            layers.appendChild(buildLayerElement(doc, layer));
        }
        front.appendChild(layers);
    }
    const shine = doc.createElement("div");
    shine.className = CLASS.shine;
    const glare = doc.createElement("div");
    glare.className = CLASS.glare;
    front.appendChild(shine);
    front.appendChild(glare);
    if (options.overlay) {
        const overlay = doc.createElement("div");
        overlay.className = CLASS.overlay;
        if (options.overlayInteractive) {
            overlay.classList.add(CLASS.overlayInteractive);
        }
        overlay.appendChild(resolveContent(doc, options.overlay));
        front.appendChild(overlay);
    }
    rotator.appendChild(front);
    translater.appendChild(rotator);
    root.appendChild(translater);
    return root;
};
//# sourceMappingURL=dom.js.map