export const DEFAULT_TEXTURE_SEED = 0x9e3779b9;
/** Deterministic PRNG (mulberry32) returning values in [0, 1) for a given seed. */
export const mulberry32 = (seed) => {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
};
const svgToDataUri = (svg) => {
    const cleaned = svg
        .replace(/>\s+</g, "><")
        .replace(/\s{2,}/g, " ")
        .trim();
    const encoded = cleaned
        .replace(/%/g, "%25")
        .replace(/</g, "%3C")
        .replace(/>/g, "%3E")
        .replace(/#/g, "%23")
        .replace(/&/g, "%26")
        .replace(/"/g, "'")
        .replace(/\n/g, "%0A");
    return `data:image/svg+xml,${encoded}`;
};
const svgDocument = (width, height, defs, body) => svgToDataUri(`<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}' viewBox='0 0 ${width} ${height}'>` +
    (defs ? `<defs>${defs}</defs>` : "") +
    body +
    `</svg>`);
const pick = (rng, items) => {
    const value = items[Math.floor(rng() * items.length)];
    return value ?? items[0];
};
const rand = (rng, min, max) => min + rng() * (max - min);
const circle = (x, y, r, fill, opacity, opts = {}) => {
    const filter = opts.filter ? ` filter='url(${opts.filter})'` : "";
    return `<circle cx='${x.toFixed(1)}' cy='${y.toFixed(1)}' r='${r.toFixed(opts.rDigits ?? 2)}' fill='${fill}' opacity='${opacity.toFixed(2)}'${filter}/>`;
};
const gaussianBlurFilter = (id, std, margin, size) => `<filter id='${id}' x='${margin}' y='${margin}' width='${size}' height='${size}'><feGaussianBlur stdDeviation='${std}'/></filter>`;
const discreteTable = (keep, steps = 32) => {
    const ones = Math.min(steps, Math.max(1, Math.round(steps * keep)));
    const cells = [];
    for (let i = 0; i < steps - ones; i += 1) {
        cells.push("0");
    }
    for (let i = 0; i < ones; i += 1) {
        cells.push("1");
    }
    return cells.join(" ");
};
const speckleField = (idBase, seed, layers, stitch = true) => {
    let defs = "";
    let body = "";
    const stitchTiles = stitch ? "stitch" : "noStitch";
    layers.forEach((layer, index) => {
        const id = `${idBase}${index}`;
        defs +=
            `<filter id='${id}' x='0%' y='0%' width='100%' height='100%'>` +
                `<feTurbulence type='fractalNoise' baseFrequency='${layer.freq}' numOctaves='1' seed='${(seed + index * 37) % 9973}' stitchTiles='${stitchTiles}' result='n'/>` +
                `<feColorMatrix in='n' type='matrix' values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0' result='a'/>` +
                `<feComponentTransfer in='a' result='m'><feFuncA type='discrete' tableValues='${discreteTable(layer.keep)}'/></feComponentTransfer>` +
                `<feComposite in='SourceGraphic' in2='m' operator='in'/>` +
                `</filter>`;
        body += `<rect width='100%' height='100%' fill='${layer.color}' filter='url(#${id})' opacity='${layer.opacity}'/>`;
    });
    return { defs, body };
};
const clusterBlobs = (rng, width, height, count, palette, blurId, radius, opacity) => {
    let blobs = "";
    for (let i = 0; i < count; i += 1) {
        blobs += circle(rng() * width, rng() * height, rand(rng, radius[0], radius[1]), pick(rng, palette), rand(rng, opacity[0], opacity[1]), { rDigits: 1 });
    }
    return `<g filter='url(${blurId})'>${blobs}</g>`;
};
const brightStars = (rng, width, height, count, glowId) => {
    let stars = "";
    for (let i = 0; i < count; i += 1) {
        const x = rng() * width;
        const y = rng() * height;
        const r = rand(rng, 1.1, 2.6);
        stars +=
            circle(x, y, r * 2.6, "#ffffff", 0.14, { rDigits: 1, filter: glowId }) +
                circle(x, y, r, "#ffffff", rand(rng, 0.75, 1));
    }
    return stars;
};
const ringClusters = (rng, width, height, count, color) => {
    let out = "";
    for (let i = 0; i < count; i += 1) {
        const cx = rng() * width;
        const cy = rng() * height;
        const radius = rand(rng, 14, 30);
        const dots = 26 + Math.floor(rng() * 22);
        for (let k = 0; k < dots; k += 1) {
            const angle = rng() * Math.PI * 2;
            const rr = radius * rand(rng, 0.78, 1.28);
            out += circle(cx + Math.cos(angle) * rr, cy + Math.sin(angle) * rr * 1.05, rand(rng, 0.5, 1.5), color, rand(rng, 0.4, 0.9));
        }
    }
    return out;
};
const COSMOS_W = 512;
const COSMOS_H = 716;
const cosmosDefs = (extraDefs) => gaussianBlurFilter("blur", 2.6, "-30%", "160%") + gaussianBlurFilter("glow", 2.4, "-200%", "500%") + extraDefs;
export const grainTexture = (seed) => svgDocument(200, 200, `<filter id='grain' x='0%' y='0%' width='100%' height='100%'>` +
    `<feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='${seed % 9973}' stitchTiles='stitch' result='n'/>` +
    `<feColorMatrix in='n' type='matrix' values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0' result='a'/>` +
    `<feComponentTransfer in='a' result='m'><feFuncA type='discrete' tableValues='${discreteTable(0.28)}'/></feComponentTransfer>` +
    `<feFlood flood-color='#ffffff' result='w'/>` +
    `<feComposite in='w' in2='m' operator='in'/>` +
    `</filter>`, `<rect width='100%' height='100%' fill='#000000'/>` +
    `<rect width='100%' height='100%' filter='url(#grain)' opacity='0.4'/>`);
export const glitterTexture = (seed) => {
    const { defs, body } = speckleField("gl", seed, [
        { freq: 0.82, keep: 0.42, color: "#8f8f8f", opacity: 0.85 },
        { freq: 0.7, keep: 0.22, color: "#dcdcdc", opacity: 1 },
        { freq: 0.6, keep: 0.08, color: "#ffffff", opacity: 1 },
    ]);
    const rng = mulberry32(seed + 99);
    const flares = brightStars(rng, 240, 240, 16, "#glow");
    return svgDocument(240, 240, `${gaussianBlurFilter("glow", 1.5, "-200%", "500%")}${defs}`, `<rect width='100%' height='100%' fill='#050505'/>${body}${flares}`);
};
const cosmosLayer = (idBase, seed, layers, paint) => {
    const rng = mulberry32(seed);
    const { defs, body } = speckleField(idBase, seed, layers, false);
    return svgDocument(COSMOS_W, COSMOS_H, cosmosDefs(defs), paint(rng, body));
};
const cosmosBottom = (seed) => cosmosLayer("csb", seed, [
    { freq: 0.85, keep: 0.32, color: "#97a3c8", opacity: 0.8 },
    { freq: 0.72, keep: 0.13, color: "#ffffff", opacity: 0.95 },
    { freq: 0.76, keep: 0.05, color: "#9fb6ff", opacity: 0.85 },
    { freq: 0.78, keep: 0.04, color: "#ffc2d8", opacity: 0.8 },
], (rng, body) => {
    const clusters = clusterBlobs(rng, COSMOS_W, COSMOS_H, 26, ["#465777", "#6d6088", "#9a7790", "#aab3cc", "#566f9e"], "#blur", [5, 14], [0.18, 0.4]);
    const stars = brightStars(rng, COSMOS_W, COSMOS_H, 24, "#glow");
    return `<rect width='100%' height='100%' fill='#04030c'/>${clusters}${body}${stars}`;
});
const cosmosMiddle = (seed) => cosmosLayer("csm", seed, [
    { freq: 0.66, keep: 0.2, color: "#241a4e", opacity: 0.95 },
    { freq: 0.58, keep: 0.11, color: "#4a2168", opacity: 0.9 },
    { freq: 0.52, keep: 0.055, color: "#7a1f6b", opacity: 0.85 },
    { freq: 0.5, keep: 0.03, color: "#c87a3a", opacity: 0.85 },
], (rng, body) => {
    const clusters = clusterBlobs(rng, COSMOS_W, COSMOS_H, 16, ["#241a4e", "#3a2168", "#1a1430"], "#blur", [7, 18], [0.45, 0.8]);
    return `${clusters}${body}`;
});
const cosmosTop = (seed) => cosmosLayer("cst", seed, [
    { freq: 0.62, keep: 0.06, color: "#6a6a76", opacity: 0.85 },
    { freq: 0.52, keep: 0.035, color: "#42424c", opacity: 0.9 },
], (rng, body) => {
    const rings = ringClusters(rng, COSMOS_W, COSMOS_H, 7, "#54545f");
    return `${body}${rings}`;
});
// The texture key includes the fixed generator profile (including dimensions and
// parameters) plus the card seed. Bump the profile version when those change.
const TEXTURE_CACHE_VERSION = "v1-default-card-textures";
const TEXTURE_CACHE_LIMIT = 24;
const textureCache = new Map();
const TEXTURE_GENERATORS = {
    grain: (seed) => grainTexture(seed),
    glitter: (seed) => glitterTexture(seed + 1),
    cosmosBottom: (seed) => cosmosBottom(seed + 2),
    cosmosMiddle: (seed) => cosmosMiddle(seed + 3),
    cosmosTop: (seed) => cosmosTop(seed + 4),
};
const ALL_TEXTURE_KEYS = Object.freeze(Object.keys(TEXTURE_GENERATORS));
const textureKeysForEffect = (effect) => {
    if (effect === "none") {
        return [];
    }
    if (effect === "glitter") {
        return ["glitter"];
    }
    if (effect === "cosmos") {
        return ["cosmosBottom", "cosmosMiddle", "cosmosTop"];
    }
    return ALL_TEXTURE_KEYS;
};
const getCachedTexture = (key, seed) => {
    const cacheKey = `${TEXTURE_CACHE_VERSION}:${key}:${seed >>> 0}`;
    const cached = textureCache.get(cacheKey);
    if (cached !== undefined) {
        // Map insertion order gives the small cache an inexpensive LRU policy.
        textureCache.delete(cacheKey);
        textureCache.set(cacheKey, cached);
        return cached;
    }

    const texture = TEXTURE_GENERATORS[key](seed);
    textureCache.set(cacheKey, texture);
    while (textureCache.size > TEXTURE_CACHE_LIMIT) {
        textureCache.delete(textureCache.keys().next().value);
    }
    return texture;
};
export const clearTextureCache = () => textureCache.clear();
export const generateTextures = (options = {}) => {
    const seed = options.seed ?? DEFAULT_TEXTURE_SEED;
    const keys = Array.isArray(options.keys) && options.keys.length
        ? options.keys
        : textureKeysForEffect(options.effect);
    const textures = {};
    for (const key of keys) {
        if (TEXTURE_GENERATORS[key]) {
            textures[key] = getCachedTexture(key, seed);
        }
    }
    return textures;
};
export const TEXTURE_VARIABLES = {
    grain: "--hc-grain",
    glitter: "--hc-glitter",
    cosmosBottom: "--hc-cosmos-bottom",
    cosmosMiddle: "--hc-cosmos-middle",
    cosmosTop: "--hc-cosmos-top",
};
export const texturesToCssVariables = (textures) => {
    const vars = {};
    for (const key of Object.keys(TEXTURE_VARIABLES)) {
        if (typeof textures?.[key] === "string") {
            vars[TEXTURE_VARIABLES[key]] = `url("${textures[key]}")`;
        }
    }
    return vars;
};
//# sourceMappingURL=textures.js.map
