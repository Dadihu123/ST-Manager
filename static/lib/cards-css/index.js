import { HoloCard } from "./holo-card.js";
import { buildHoloCardElement } from "./dom.js";
export { HoloCard, prepareHoloCard } from "./holo-card.js";
export { buildHoloCardElement, buildLayerElement, applyVars, normalizeMask, CLASS } from "./dom.js";
export {
    generateTextures,
    texturesToCssVariables,
    grainTexture,
    glitterTexture,
    mulberry32,
    TEXTURE_VARIABLES,
    DEFAULT_TEXTURE_SEED,
    clearTextureCache,
} from "./textures.js";
export { subscribeOrientation, requestOrientationPermission, resetBaseOrientation, } from "./orientation.js";
export { PALETTES, resolvePalette, paletteToCssVariables } from "./palette.js";
export { getActiveCard, setActiveCard, subscribeActiveCard } from "./active-registry.js";
export { Spring } from "./spring.js";
export { round, clamp, adjust } from "./math.js";
export { HOLO_EFFECTS } from "./types.js";
export const createHoloCard = (options) => {
    const element = buildHoloCardElement(options);
    return new HoloCard(element, options);
};
export const attachHoloCard = (element, options = {}) => new HoloCard(element, options);
//# sourceMappingURL=index.js.map
