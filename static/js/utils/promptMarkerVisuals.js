const PRESET_ICON_SPRITE_URL = "/static/icons/preset.svg";

export const PROMPT_MARKER_VISUALS = {
  worldInfoBefore: {
    key: "worldInfoBefore",
    label: "世界书（前）",
    asset: "definition-before",
    paths: [
      "M7.5 5.75h7.25A2.75 2.75 0 0 1 17.5 8.5v10.25",
      "M7.5 5.75v11.5c0 .552.448 1 1 1h8",
      "M10 9.5h4.5",
      "M10 12.5h3.5",
    ],
  },
  worldInfoAfter: {
    key: "worldInfoAfter",
    label: "世界书（后）",
    asset: "definition-after",
    paths: [
      "M6.5 5.75h7.25A2.75 2.75 0 0 1 16.5 8.5v10.25",
      "M6.5 5.75v11.5c0 .552.448 1 1 1h8",
      "M9 9.5h4.5",
      "M9 12.5h5.5",
    ],
  },
  charDescription: {
    key: "charDescription",
    label: "角色描述",
    asset: "character-description",
    paths: [
      "M12 12a3.25 3.25 0 1 0 0-6.5A3.25 3.25 0 0 0 12 12Z",
      "M6.75 18.25c1.1-2.35 3.02-3.5 5.25-3.5s4.15 1.15 5.25 3.5",
    ],
  },
  charPersonality: {
    key: "charPersonality",
    label: "角色性格",
    asset: "character-personality",
    paths: [
      "M12 4.75c3.73 0 6.75 3.02 6.75 6.75S15.73 18.25 12 18.25 5.25 15.23 5.25 11.5 8.27 4.75 12 4.75Z",
      "M9.5 10a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z",
      "M14.5 10a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z",
      "M9.25 13.25c.75.83 1.65 1.25 2.75 1.25s2-.42 2.75-1.25",
    ],
  },
  personaDescription: {
    key: "personaDescription",
    label: "人格描述",
    asset: "persona-description",
    paths: [
      "M12 4.5 14.4 9.3 19.75 10.08 15.88 13.86 16.8 19.2 12 16.68 7.2 19.2 8.12 13.86 4.25 10.08 9.6 9.3Z",
    ],
  },
  scenario: {
    key: "scenario",
    label: "场景",
    asset: "scenario",
    paths: [
      "M4.75 17.5 9.5 12.75 12.25 15.5 16.75 11 19.25 13.5",
      "M7 9.75 9.25 7.5 12 10.25 15.75 6.5 19.25 10",
    ],
  },
  chatHistory: {
    key: "chatHistory",
    label: "聊天记录",
    asset: "chat-history",
    paths: [
      "M6.75 7.25h10.5A1.75 1.75 0 0 1 19 9v6a1.75 1.75 0 0 1-1.75 1.75H11l-3.75 2v-2H6.75A1.75 1.75 0 0 1 5 15V9c0-.967.783-1.75 1.75-1.75Z",
      "M8.75 10.5h6.5",
      "M8.75 13h4.5",
    ],
  },
  dialogueExamples: {
    key: "dialogueExamples",
    label: "对话示例",
    asset: "chat-examples",
    paths: [
      "M6.75 8h6.5A1.75 1.75 0 0 1 15 9.75v3.5A1.75 1.75 0 0 1 13.25 15H9.5l-2.75 1.75V15H6.75A1.75 1.75 0 0 1 5 13.25v-3.5C5 8.78 5.78 8 6.75 8Z",
      "M13 10.5h4.25A1.75 1.75 0 0 1 19 12.25v3.5A1.75 1.75 0 0 1 17.25 17.5H17v1.75L14.25 17.5H13",
    ],
  },
  fallback: {
    key: "marker",
    label: "预留字段",
    paths: ["M12 5v14", "M5 12h14", "M7.5 7.5l9 9"],
  },
};

export function getPromptMarkerVisual(identifier) {
  const key = String(identifier || "").trim();
  return PROMPT_MARKER_VISUALS[key] || PROMPT_MARKER_VISUALS.fallback;
}

export function buildPromptMarkerIcon(visual, options = {}) {
  const {
    strokeWidth = "1.5",
    svgAttributes = 'aria-hidden="true" fill="none"',
    pathAttributes = 'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" fill="none"',
  } = options;
  if (visual?.asset) {
    const asset = String(visual.asset).trim();
    return `<svg class="preset-icon preset-marker-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="currentColor" stroke="none" stroke-width="${strokeWidth}"><use href="${PRESET_ICON_SPRITE_URL}#icon-${asset}"></use></svg>`;
  }
  const paths = Array.isArray(visual?.paths)
    ? visual.paths
        .map(
          (path) =>
            `<path d="${path}" ${pathAttributes} stroke-width="${strokeWidth}"></path>`,
        )
        .join("")
    : "";
  return `<svg class="preset-icon preset-marker-icon" viewBox="0 0 24 24" ${svgAttributes}>${paths}</svg>`;
}
