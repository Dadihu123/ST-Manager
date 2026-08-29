/** Built-in foil colour schemes, keyed by {@link PalettePreset}. */
export const PALETTES = {
    rainbow: {
        sunpillars: [
            "hsl(2, 100%, 73%)",
            "hsl(53, 100%, 69%)",
            "hsl(93, 100%, 69%)",
            "hsl(176, 100%, 76%)",
            "hsl(228, 100%, 74%)",
            "hsl(283, 100%, 73%)",
        ],
        spectrum: ["#f80e35", "#eedf10", "#21e985", "#0dbde9", "#c929f1"],
        cosmos: [
            "hsl(53, 65%, 60%)",
            "hsl(93, 56%, 50%)",
            "hsl(176, 54%, 49%)",
            "hsl(228, 59%, 55%)",
            "hsl(283, 60%, 55%)",
            "hsl(326, 59%, 51%)",
        ],
    },
    gold: {
        sunpillars: [
            "hsl(45, 100%, 80%)",
            "hsl(38, 100%, 68%)",
            "hsl(50, 100%, 78%)",
            "hsl(33, 95%, 62%)",
            "hsl(48, 100%, 85%)",
            "hsl(40, 100%, 70%)",
        ],
        spectrum: ["#8c5a12", "#ffd24a", "#fff0b0", "#e0962a", "#6b3f06"],
        cosmos: [
            "hsl(45, 80%, 65%)",
            "hsl(40, 75%, 58%)",
            "hsl(36, 70%, 52%)",
            "hsl(50, 85%, 70%)",
            "hsl(33, 65%, 48%)",
            "hsl(28, 70%, 55%)",
        ],
        edge: "hsl(45, 100%, 78%)",
        glow: "hsl(45, 100%, 80%)",
    },
    aurora: {
        sunpillars: [
            "hsl(150, 90%, 72%)",
            "hsl(170, 85%, 68%)",
            "hsl(190, 90%, 72%)",
            "hsl(260, 85%, 78%)",
            "hsl(140, 80%, 70%)",
            "hsl(200, 90%, 74%)",
        ],
        spectrum: ["#10b981", "#34d399", "#a7f3d0", "#22d3ee", "#8b5cf6"],
        cosmos: [
            "hsl(160, 60%, 55%)",
            "hsl(180, 55%, 50%)",
            "hsl(200, 60%, 55%)",
            "hsl(260, 55%, 58%)",
            "hsl(150, 55%, 52%)",
            "hsl(290, 50%, 55%)",
        ],
        edge: "hsl(160, 90%, 80%)",
        glow: "hsl(170, 100%, 85%)",
    },
    ruby: {
        sunpillars: [
            "hsl(350, 100%, 75%)",
            "hsl(330, 100%, 72%)",
            "hsl(10, 100%, 72%)",
            "hsl(300, 90%, 72%)",
            "hsl(355, 100%, 80%)",
            "hsl(20, 100%, 70%)",
        ],
        spectrum: ["#e11d48", "#fb7185", "#fecdd3", "#f43f5e", "#9f1239"],
        cosmos: [
            "hsl(350, 65%, 58%)",
            "hsl(330, 60%, 55%)",
            "hsl(10, 65%, 58%)",
            "hsl(300, 55%, 55%)",
            "hsl(355, 60%, 52%)",
            "hsl(20, 60%, 55%)",
        ],
        edge: "hsl(350, 100%, 82%)",
        glow: "hsl(345, 100%, 85%)",
    },
    sapphire: {
        sunpillars: [
            "hsl(210, 100%, 75%)",
            "hsl(190, 100%, 72%)",
            "hsl(230, 100%, 76%)",
            "hsl(170, 90%, 70%)",
            "hsl(250, 90%, 78%)",
            "hsl(200, 100%, 74%)",
        ],
        spectrum: ["#1d4ed8", "#3b82f6", "#bfdbfe", "#06b6d4", "#4338ca"],
        cosmos: [
            "hsl(210, 65%, 58%)",
            "hsl(190, 60%, 55%)",
            "hsl(230, 60%, 58%)",
            "hsl(170, 55%, 52%)",
            "hsl(250, 55%, 58%)",
            "hsl(200, 60%, 55%)",
        ],
        edge: "hsl(205, 100%, 80%)",
        glow: "hsl(200, 100%, 85%)",
    },
    mono: {
        sunpillars: [
            "hsl(0, 0%, 92%)",
            "hsl(0, 0%, 82%)",
            "hsl(0, 0%, 96%)",
            "hsl(0, 0%, 78%)",
            "hsl(0, 0%, 88%)",
            "hsl(0, 0%, 84%)",
        ],
        spectrum: ["#9ca3af", "#e5e7eb", "#ffffff", "#d1d5db", "#6b7280"],
        cosmos: [
            "hsl(0, 0%, 75%)",
            "hsl(0, 0%, 68%)",
            "hsl(0, 0%, 82%)",
            "hsl(0, 0%, 62%)",
            "hsl(0, 0%, 78%)",
            "hsl(0, 0%, 70%)",
        ],
        edge: "hsl(0, 0%, 90%)",
        glow: "hsl(0, 0%, 92%)",
    },
};
/** Merge a palette's `preset` base with its explicit overrides into a flat scheme. */
export const resolvePalette = (palette) => {
    const base = palette.preset ? PALETTES[palette.preset] : undefined;
    const merged = { ...base, ...palette };
    delete merged.preset;
    return merged;
};
const SPECTRUM_VARS = ["--red", "--yellow", "--green", "--blue", "--violet"];
/** Every CSS custom property the palette can own — used to clear stale values when swapping palettes. */
export const PALETTE_VARIABLES = [
    "--sunpillar-1",
    "--sunpillar-2",
    "--sunpillar-3",
    "--sunpillar-4",
    "--sunpillar-5",
    "--sunpillar-6",
    ...SPECTRUM_VARS,
    "--cosmos-clr-1",
    "--cosmos-clr-2",
    "--cosmos-clr-3",
    "--cosmos-clr-4",
    "--cosmos-clr-5",
    "--cosmos-clr-6",
    "--card-edge",
    "--card-back",
    "--card-glow",
];
const cycle = (colors, index) => colors[index % colors.length];
const cycleInto = (vars, prefix, count, colors) => {
    if (colors.length === 0) {
        return;
    }
    for (let i = 0; i < count; i += 1) {
        vars[`${prefix}${i + 1}`] = cycle(colors, i);
    }
};
/** Convert a (resolved or raw) palette into the CSS custom properties it drives. */
export const paletteToCssVariables = (palette) => {
    const resolved = resolvePalette(palette);
    const vars = {};
    if (resolved.sunpillars) {
        cycleInto(vars, "--sunpillar-", 6, resolved.sunpillars);
    }
    const spectrum = resolved.spectrum;
    if (spectrum && spectrum.length > 0) {
        SPECTRUM_VARS.forEach((name, i) => {
            vars[name] = cycle(spectrum, i);
        });
    }
    if (resolved.cosmos) {
        cycleInto(vars, "--cosmos-clr-", 6, resolved.cosmos);
    }
    if (resolved.edge) {
        vars["--card-edge"] = resolved.edge;
    }
    if (resolved.back) {
        vars["--card-back"] = resolved.back;
    }
    if (resolved.glow) {
        vars["--card-glow"] = resolved.glow;
    }
    return vars;
};
//# sourceMappingURL=palette.js.map