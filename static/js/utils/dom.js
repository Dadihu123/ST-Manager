/**
 * static/js/utils/dom.js
 * DOM 操作与渲染工具
 */

import {
  buildUnifiedDisplaySource,
  renderUnifiedDisplayHtml,
} from "./unifiedTextPreview.js";

const htmlComponentRenderCache = new WeakMap();
const pretextIntrinsicSignatureCache = new WeakMap();
const pretextEstimateCache = new Map();
let pretextModule = null;
let pretextModulePromise = null;
let renderRuntimeModule = null;
let renderRuntimeModulePromise = null;
let messageSegmentRendererModule = null;
let messageSegmentRendererModulePromise = null;

function loadPretextModule() {
  if (pretextModule) {
    return Promise.resolve(pretextModule);
  }

  if (!pretextModulePromise) {
    pretextModulePromise = import("../vendor/pretext/layout.js")
      .then((module) => {
        pretextModule = module;
        return module;
      })
      .catch((error) => {
        pretextModulePromise = null;
        console.warn("Failed to load pretext module:", error);
        throw error;
      });
  }

  return pretextModulePromise;
}

function loadRenderRuntimeModule() {
  if (renderRuntimeModule) {
    return Promise.resolve(renderRuntimeModule);
  }

  if (!renderRuntimeModulePromise) {
    renderRuntimeModulePromise = import("../runtime/renderRuntime.js")
      .then((module) => {
        renderRuntimeModule = module;
        return module;
      })
      .catch((error) => {
        renderRuntimeModulePromise = null;
        console.warn("Failed to load render runtime module:", error);
        throw error;
      });
  }

  return renderRuntimeModulePromise;
}

function loadMessageSegmentRendererModule() {
  if (messageSegmentRendererModule) {
    return Promise.resolve(messageSegmentRendererModule);
  }

  if (!messageSegmentRendererModulePromise) {
    messageSegmentRendererModulePromise =
      import("../runtime/messageSegmentRenderer.js")
        .then((module) => {
          messageSegmentRendererModule = module;
          return module;
        })
        .catch((error) => {
          messageSegmentRendererModulePromise = null;
          console.warn(
            "Failed to load message segment renderer module:",
            error,
          );
          throw error;
        });
  }

  return messageSegmentRendererModulePromise;
}

function scorePreviewAppHtml(htmlPayload) {
  const source = String(htmlPayload || "");
  if (!source.trim()) {
    return 0;
  }

  let score = 0;
  if (/<!DOCTYPE html/i.test(source) || /<html[\s>]/i.test(source)) score += 2;
  if (/id=["']readingContent["']/i.test(source)) score += 8;
  if (/function\s+processTextContent\s*\(/i.test(source)) score += 8;
  if (/window\.setTheme\s*=\s*applyTheme/i.test(source)) score += 5;
  if (/showArgMenu\s*\(/i.test(source)) score += 4;
  if (/triggerSlash\s*\(/i.test(source)) score += 4;
  if (
    /class=["'][^"']*dialogue-container/i.test(source) ||
    /createDialogueElement\s*\(/i.test(source)
  )
    score += 4;

  if (/sakura-collapsible/i.test(source)) score -= 8;
  if (/Sakura\s*-\s*折叠栏/i.test(source)) score -= 10;
  if (/id=["']raw-markdown["']/i.test(source)) score -= 6;

  return score;
}

function classifyPreviewFrontendText(text, options = {}) {
  const source = String(text || "").trim();
  if (!source) {
    return null;
  }

  const frontendLike = ["<!doctype html", "<html", "<head", "<body"].some(
    (token) => source.toLowerCase().includes(token),
  );

  const resolvePreviewBound = (value, fallback) => {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  };

  const normalized = source
    .replace(/^```(?:html|text|xml)?\s*/i, "")
    .replace(/```$/i, "")
    .trim();
  const score = scorePreviewAppHtml(normalized);
  if (!frontendLike && score < Number(options.appThreshold || 8)) {
    return null;
  }

  return {
    type: "app-stage",
    minHeight: resolvePreviewBound(options.minHeight, 260),
    maxHeight: resolvePreviewBound(options.maxHeight, 3200),
  };
}

function destroyMixedPreviewHost(el) {
  if (!el) return;

  if (messageSegmentRendererModule?.destroyMessageSegmentHost) {
    if (el.__stmMixedPreviewHost) {
      messageSegmentRendererModule.destroyMessageSegmentHost(
        el.__stmMixedPreviewHost,
      );
    }
    messageSegmentRendererModule.destroyMessageSegmentHost(el);
  }

  if (el.__stmMixedPreviewHost instanceof HTMLElement) {
    el.__stmMixedPreviewHost.innerHTML = "";
  }
  el.__stmMixedPreviewHost = null;
}

function buildPreviewRenderOptions(options = {}) {
  return {
    scopeClass: String(options.scopeClass || "stm-reader-scope"),
    renderMode:
      options.renderMode ||
      (options.isMarkdown === false ? "plain" : "markdown"),
    speakerName: options.speakerName,
    stripSpeakerPrefix: options.stripSpeakerPrefix,
    encodeTags: options.encodeTags,
    promptBias: options.promptBias,
    hidePromptBias: options.hidePromptBias,
    reasoningMarkers: options.reasoningMarkers,
    blockMedia: options.blockMedia,
    isMarkdown: options.isMarkdown,
  };
}

export function clearInlineIsolatedHtml(el, options = {}) {
  if (!el || !renderRuntimeModule?.clearIsolatedHtml) {
    return;
  }
  renderRuntimeModule.clearIsolatedHtml(el, options);
}

function buildHtmlComponentSignature(content, options = {}) {
  return JSON.stringify({
    content: String(content || ""),
    minHeight: Number.parseInt(options.minHeight, 10) || 0,
    maxHeight: Number.parseInt(options.maxHeight, 10) || 0,
    mode: String(options.mode || "html-component"),
    assetBase: String(options.assetBase || ""),
  });
}

function decodePretextEntities(text) {
  return String(text || "")
    .replace(/&nbsp;/gi, " ")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'");
}

function stripHtmlForPretext(text) {
  return String(text || "")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(
      /<\/(?:p|div|section|article|main|header|footer|blockquote|li|tr|table|pre|h[1-6])>/gi,
      "\n",
    )
    .replace(/<[^>]+>/g, " ");
}

function normalizePretextSourceText(content, options = {}) {
  let source = String(content || "");
  if (!source.trim()) {
    return "";
  }

  source = source.replace(/<open>|<\/open>/gi, "");
  source = source.replace(/```(?:[a-z0-9_-]+)?\s*/gi, "");
  source = source.replace(/```/g, "");

  if (options.stripTags !== false && /<\/?[a-z][\s\S]*>/i.test(source)) {
    source = stripHtmlForPretext(source);
  }

  source = decodePretextEntities(source)
    .replace(/\r\n/g, "\n")
    .replace(/[\r\f]/g, "\n")
    .replace(/\t/g, "        ")
    .replace(/\n{3,}/g, "\n\n");

  return source.trim();
}

function resolvePretextFont(target, options = {}) {
  if (typeof options.font === "string" && options.font.trim()) {
    return options.font.trim();
  }

  if (
    target instanceof HTMLElement &&
    typeof window !== "undefined" &&
    typeof window.getComputedStyle === "function"
  ) {
    const style = window.getComputedStyle(target);
    if (style.font && style.font.trim()) {
      return style.font.trim();
    }

    const parts = [
      style.fontStyle || "normal",
      style.fontVariant || "normal",
      style.fontWeight || "400",
    ];

    if (style.fontStretch && style.fontStretch !== "normal") {
      parts.push(style.fontStretch);
    }

    parts.push(style.fontSize || "16px");
    parts.push(style.fontFamily || "sans-serif");
    return parts.filter(Boolean).join(" ").trim();
  }

  return "400 16px sans-serif";
}

function resolvePretextLineHeight(target, options = {}) {
  if (
    Number.isFinite(Number(options.lineHeight)) &&
    Number(options.lineHeight) > 0
  ) {
    return Number(options.lineHeight);
  }

  if (
    target instanceof HTMLElement &&
    typeof window !== "undefined" &&
    typeof window.getComputedStyle === "function"
  ) {
    const style = window.getComputedStyle(target);
    const fontSize = Number.parseFloat(style.fontSize) || 16;
    const rawLineHeight = String(style.lineHeight || "").trim();
    const numericLineHeight = Number.parseFloat(rawLineHeight);
    if (
      rawLineHeight.endsWith("px") &&
      Number.isFinite(numericLineHeight) &&
      numericLineHeight > 0
    ) {
      return numericLineHeight;
    }
    if (
      /^[\d.]+$/.test(rawLineHeight) &&
      Number.isFinite(numericLineHeight) &&
      numericLineHeight > 0
    ) {
      return numericLineHeight * fontSize;
    }
    return fontSize * 1.6;
  }

  return 24;
}

function resolvePretextMeasureWidth(target, options = {}) {
  const explicitWidth = Number(options.maxWidth ?? options.measureWidth ?? 0);
  if (Number.isFinite(explicitWidth) && explicitWidth > 0) {
    return explicitWidth;
  }

  if (target instanceof HTMLElement) {
    const width = Number(
      target.clientWidth || target.parentElement?.clientWidth || 0,
    );
    if (Number.isFinite(width) && width > 0) {
      return width;
    }
  }

  const fallbackWidth = Number(options.fallbackWidth ?? 720);
  return Number.isFinite(fallbackWidth) && fallbackWidth > 0
    ? fallbackWidth
    : 720;
}

function clampPretextHeight(height, options = {}) {
  const minHeight = Number.parseInt(options.minHeight, 10);
  const maxHeight = Number.parseInt(options.maxHeight, 10);
  const resolvedMin = Number.isFinite(minHeight) ? Math.max(0, minHeight) : 0;
  const resolvedMax =
    Number.isFinite(maxHeight) && maxHeight > 0
      ? Math.max(resolvedMin, maxHeight)
      : null;

  let nextHeight = Number.isFinite(Number(height))
    ? Math.max(resolvedMin, Math.ceil(Number(height)))
    : resolvedMin;
  if (resolvedMax !== null) {
    nextHeight = Math.min(resolvedMax, nextHeight);
  }
  return nextHeight;
}

function approximatePretextFallbackHeight(text, maxWidth, lineHeight) {
  const normalized = String(text || "");
  if (!normalized) {
    return lineHeight;
  }

  const estimatedCharsPerLine = Math.max(
    8,
    Math.floor(Math.max(1, maxWidth) / 8),
  );
  const estimatedLines = normalized
    .split("\n")
    .reduce(
      (total, line) =>
        total +
        Math.max(
          1,
          Math.ceil(Math.max(1, line.length) / estimatedCharsPerLine),
        ),
      0,
    );

  return estimatedLines * lineHeight;
}

export function estimatePretextBlockHeight(content, options = {}) {
  const element =
    options.element instanceof HTMLElement ? options.element : null;
  const text = normalizePretextSourceText(content, options);
  const font = resolvePretextFont(element, options);
  const maxWidth = resolvePretextMeasureWidth(element, options);
  const lineHeight = resolvePretextLineHeight(element, options);

  if (!text) {
    const emptyHeight = clampPretextHeight(lineHeight, options);
    return {
      text: "",
      font,
      maxWidth,
      lineHeight,
      lineCount: 0,
      height: emptyHeight,
    };
  }

  const fallbackHeight = clampPretextHeight(
    approximatePretextFallbackHeight(text, maxWidth, lineHeight),
    options,
  );
  const fallbackEstimate = {
    text,
    font,
    maxWidth,
    lineHeight,
    lineCount: Math.max(
      1,
      Math.round(fallbackHeight / Math.max(1, lineHeight)),
    ),
    height: fallbackHeight,
  };
  const cacheKey = JSON.stringify({
    text,
    font,
    maxWidth,
    lineHeight,
    minHeight: Number.parseInt(options.minHeight, 10) || 0,
    maxHeight: Number.parseInt(options.maxHeight, 10) || 0,
    whiteSpace: options.whiteSpace === "normal" ? "normal" : "pre-wrap",
  });
  const cachedEstimate = pretextEstimateCache.get(cacheKey);
  if (cachedEstimate) {
    return cachedEstimate;
  }

  try {
    const module = pretextModule;
    if (!module?.prepare || !module?.layout) {
      loadPretextModule().catch(() => null);
      return fallbackEstimate;
    }
    const prepared = module.prepare(text, font, {
      whiteSpace: options.whiteSpace === "normal" ? "normal" : "pre-wrap",
    });
    const measured = module.layout(prepared, maxWidth, lineHeight);
    const estimate = {
      text,
      font,
      maxWidth,
      lineHeight,
      lineCount: Number(measured.lineCount || 0),
      height: clampPretextHeight(measured.height, options),
    };
    pretextEstimateCache.set(cacheKey, estimate);
    return estimate;
  } catch (error) {
    console.warn("Pretext estimate fallback used:", error);
    pretextEstimateCache.set(cacheKey, fallbackEstimate);
    return fallbackEstimate;
  }
}

export function applyPretextIntrinsicSize(el, content, options = {}) {
  if (!(el instanceof HTMLElement)) {
    return null;
  }

  const estimate = estimatePretextBlockHeight(content, {
    ...options,
    element: options.element instanceof HTMLElement ? options.element : el,
  });
  const heightPx = `${Math.max(0, Math.ceil(Number(estimate.height) || 0))}px`;
  const signature = JSON.stringify({
    text: estimate.text,
    font: estimate.font,
    maxWidth: estimate.maxWidth,
    lineHeight: estimate.lineHeight,
    runtimeOwner: String(options.runtimeOwner || ""),
  });

  if (
    pretextIntrinsicSignatureCache.get(el) !== signature ||
    el.style.getPropertyValue("--stm-pretext-block-size") !== heightPx
  ) {
    pretextIntrinsicSignatureCache.set(el, signature);
    el.style.setProperty("--stm-pretext-block-size", heightPx);
    el.style.containIntrinsicSize = `auto ${heightPx}`;
    if (options.enableContentVisibility !== false) {
      el.style.contentVisibility = "auto";
    }
  }

  return estimate;
}

export function updateCssVariable(name, value) {
  document.documentElement.style.setProperty(name, value);
}

export function applyFont(type) {
  let fontVal = "ui-sans-serif, system-ui, sans-serif";
  if (type === "serif")
    fontVal = 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif';
  if (type === "mono")
    fontVal =
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
  updateCssVariable("--app-font-family", fontVal);
}

export function insertAtCursor(textarea, myValue) {
  if (textarea.selectionStart || textarea.selectionStart == "0") {
    var startPos = textarea.selectionStart;
    var endPos = textarea.selectionEnd;
    return (
      textarea.value.substring(0, startPos) +
      myValue +
      textarea.value.substring(endPos, textarea.value.length)
    );
  } else {
    return textarea.value + myValue;
  }
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function renderMarkdown(text) {
  if (!text) return '<span class="color-text-muted italic">空内容</span>';
  let safeText = String(text);
  if (typeof marked !== "undefined") {
    marked.setOptions({ breaks: true });
    try {
      return marked.parse(safeText);
    } catch (e) {
      console.error("Markdown parse error:", e);
      return safeText;
    }
  }
  return safeText;
}

export function updateInlineRenderContent(el, content, options = {}) {
  if (!el) return;

  const rawContent = String(content || "");
  const trimmed = rawContent.trim();
  const mode = options.mode || "markdown";
  const isolated = Boolean(options.isolated);
  const emptyHtml =
    options.emptyHtml || '<span class="color-text-muted italic">空内容</span>';

  if (!trimmed) {
    htmlComponentRenderCache.delete(el);
    clearInlineIsolatedHtml(el);
    if (el.shadowRoot) {
      el.shadowRoot.innerHTML = `<div>${emptyHtml}</div>`;
    } else {
      el.innerHTML = emptyHtml;
    }
    return;
  }

  if (mode === "html-component") {
    const signature = buildHtmlComponentSignature(rawContent, options);
    if (htmlComponentRenderCache.get(el) === signature) {
      return;
    }
    htmlComponentRenderCache.set(el, signature);
    if (!el.shadowRoot) {
      el.attachShadow({ mode: "open" });
    }
    updateShadowContent(el, rawContent, options);
    return;
  }

  htmlComponentRenderCache.delete(el);
  clearInlineIsolatedHtml(el);

  const rendered =
    mode === "markdown"
      ? renderMarkdown(rawContent)
      : `<div>${escapeHtml(rawContent).replace(/\n/g, "<br>")}</div>`;

  if (isolated && !el.shadowRoot) {
    el.attachShadow({ mode: "open" });
  }

  if (el.shadowRoot) {
    el.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                    color: inherit;
                }
                .inline-render {
                    display: block;
                    color: inherit;
                    min-width: 0;
                    overflow-wrap: anywhere;
                    word-break: break-word;
                }
                .inline-render img {
                    max-width: 100%;
                    height: auto;
                }
                .inline-render pre {
                    white-space: pre-wrap;
                    word-break: break-word;
                }
            </style>
            <div class="inline-render markdown-body">${rendered}</div>
        `;
    return;
  }

  el.innerHTML = rendered;
}

export function updateShadowContent(el, content, options = {}) {
  destroyMixedPreviewHost(el);

  const shadowRenderToken = Number(el.__stmShadowRenderToken || 0) + 1;
  el.__stmShadowRenderToken = shadowRenderToken;

  if (!el.shadowRoot) {
    el.attachShadow({ mode: "open" });
  }

  const shadow = el.shadowRoot;
  const minHeight = Number.parseInt(options.minHeight, 10);
  const hostMinHeight = Number.isFinite(minHeight)
    ? `${Math.max(0, minHeight)}px`
    : "0px";
  const maxHeight = Number.parseInt(options.maxHeight, 10);
  const hostMaxHeight = Number.isFinite(maxHeight)
    ? `${Math.max(0, maxHeight)}px`
    : "none";
  const scrollMode = Boolean(options.scroll);
  const hostOverflow = scrollMode ? "hidden" : "visible";
  const wrapperOverflow = scrollMode ? "auto" : "visible";
  const hostHeight = scrollMode ? "100%" : "auto";
  const wrapperHeight = scrollMode ? "100%" : "auto";

  if (content === null || content === undefined) {
    htmlComponentRenderCache.delete(el);
    clearInlineIsolatedHtml(el);
    shadow.innerHTML = "";
    return;
  }

  const source = String(content || "");
  let rawContent = source;
  const trimmedContent = rawContent.trim();
  applyPretextIntrinsicSize(el, source, {
    ...options,
    element: el,
    whiteSpace: "pre-wrap",
  });

  const htmlFragmentRegex =
    /^\s*<(?:div|style|details|section|article|main|link|table|script|iframe|svg|html|body|head|canvas)/i;
  let forceHtmlMode = false;

  if (htmlFragmentRegex.test(trimmedContent)) {
    forceHtmlMode = true;
  }

  let htmlPayload = "";
  let markdownCommentary = "";

  const codeBlockRegex = /```(?:html|xml|text|js|css|json)?\s*([\s\S]*?)```/gi;
  let match;
  let foundPayload = false;

  while ((match = codeBlockRegex.exec(rawContent)) !== null) {
    const blockContent = match[1];
    if (
      blockContent.includes("<!DOCTYPE") ||
      blockContent.includes("<html") ||
      blockContent.includes("<script") ||
      blockContent.includes("export default") ||
      (blockContent.includes("<div") && blockContent.includes("<style"))
    ) {
      htmlPayload = blockContent;
      markdownCommentary = rawContent.replace(match[0], "");
      foundPayload = true;
      break;
    }
  }

  if (!foundPayload) {
    if (
      forceHtmlMode ||
      rawContent.includes("<!DOCTYPE") ||
      rawContent.includes("<html") ||
      rawContent.includes("<script")
    ) {
      htmlPayload = rawContent;
      markdownCommentary = "";
    } else {
      markdownCommentary = rawContent;
    }
  }

  markdownCommentary = markdownCommentary
    .replace(/<open>|<\/open>/gi, "")
    .trim();

  const hasPayload = !!htmlPayload;

  if (hasPayload) {
    let renderedMd = "";
    if (markdownCommentary) {
      const looksLikeTrustedHtml = /^\s*<(?:[a-z][\w:-]*|!doctype|!--)/i.test(
        markdownCommentary,
      );
      if (looksLikeTrustedHtml) {
        renderedMd = markdownCommentary;
      } else if (typeof marked !== "undefined") {
        renderedMd = marked.parse(markdownCommentary, { breaks: true });
      } else {
        renderedMd = `<p>${markdownCommentary.replace(/\n/g, "<br>")}</p>`;
      }
    }
    loadRenderRuntimeModule()
      .then((module) => {
        if (
          el.__stmShadowRenderToken !== shadowRenderToken ||
          !el.isConnected
        ) {
          return;
        }
        module.renderIsolatedHtml(el, {
          htmlPayload,
          noteHtml: renderedMd,
          minHeight: Number.parseInt(options.minHeight, 10),
          maxHeight: Number.parseInt(options.maxHeight, 10),
          assetBase: options.assetBase || "",
        });
      })
      .catch(() => {
        if (
          el.__stmShadowRenderToken !== shadowRenderToken ||
          !el.isConnected
        ) {
          return;
        }
        shadow.innerHTML = `<div class="scroll-wrapper markdown-body">运行时模块加载失败，无法渲染 HTML 预览。</div>`;
      });
    return;
  }

  clearInlineIsolatedHtml(el);

  const style = `
                <style>
                    :host {
                        display: block;
                        min-height: ${hostMinHeight};
                        max-height: ${hostMaxHeight};
                        width: 100%;
                        height: ${hostHeight};
                        overflow: ${hostOverflow};
                        background-color: transparent;
                        color: var(--content-primary);
                        font-family: ui-sans-serif, system-ui, sans-serif;
                        font-size: 0.9rem;
                        line-height: 1.6;
                    }
                    .scroll-wrapper {
                        min-height: ${hostMinHeight};
                        max-height: ${hostMaxHeight};
                        width: 100%;
                        height: ${wrapperHeight};
                        overflow: ${wrapperOverflow};
                        padding: 1rem;
                        box-sizing: border-box;
                    }
                    img { max-width: 100%; border-radius: 4px; }
                    a { color: var(--accent-text); }
                    blockquote { border-left: 4px solid var(--accent-outline); padding-left: 1em; margin: 1em 0; color: var(--content-secondary); }
                    /* 代码块样式修复 */
                    pre { background: var(--surface-code); border: 1px solid var(--border-subtle); padding: 1em; border-radius: 6px; overflow-x: auto; }
                    code { font-family: monospace; }
                </style>
            `;

  const looksLikeTrustedHtml = /^\s*<(?:[a-z][\w:-]*|!doctype|!--)/i.test(
    rawContent,
  );

  let renderedHtml = rawContent;
  if (looksLikeTrustedHtml) {
    renderedHtml = rawContent;
  } else if (typeof marked !== "undefined") {
    renderedHtml = marked.parse(rawContent || "", { breaks: true });
  } else {
    renderedHtml = (rawContent || "").replace(/\n/g, "<br>");
  }

  const htmlWrapper =
    renderedHtml ||
    '<div style="color: var(--content-muted); font-style: italic;">空内容</div>';
  shadow.innerHTML =
    style + `<div class="scroll-wrapper markdown-body">${htmlWrapper}</div>`;
}

export function renderUnifiedPreviewHost(el, content, options = {}) {
  if (!el) return;

  const renderVersion = Number(el.__stmMixedPreviewVersion || 0) + 1;
  el.__stmMixedPreviewVersion = renderVersion;
  const scrollMode = Boolean(options.scroll);

  destroyMixedPreviewHost(el);

  if (!el.shadowRoot) {
    el.attachShadow({ mode: "open" });
  }

  const resolvePreviewCssBound = (value) => {
    if (value === null || value === undefined || value === "") {
      return "none";
    }
    const numeric = Number.parseInt(value, 10);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return "none";
    }
    return `${Math.max(0, numeric)}px`;
  };

  const minHeight = Number.parseInt(options.minHeight, 10);
  const hostMinHeight = Number.isFinite(minHeight)
    ? `${Math.max(0, minHeight)}px`
    : "0px";
  const hostMaxHeight = resolvePreviewCssBound(options.maxHeight);
  const shadow = el.shadowRoot;

  shadow.innerHTML = `
        <style>
            :host {
                display: block;
                min-height: ${hostMinHeight};
                max-height: ${hostMaxHeight};
                width: 100%;
                height: ${scrollMode ? "100%" : "auto"};
                overflow: ${scrollMode ? "hidden" : "visible"};
                background-color: transparent;
                color: var(--content-primary);
                font-family: ui-sans-serif, system-ui, sans-serif;
                font-size: 0.9rem;
                line-height: 1.6;
            }
            .mixed-preview-scroll {
                min-height: ${hostMinHeight};
                max-height: ${hostMaxHeight};
                width: 100%;
                height: ${scrollMode ? "100%" : "auto"};
                overflow: ${scrollMode ? "auto" : "visible"};
                box-sizing: border-box;
                padding: 1rem;
                scrollbar-gutter: stable both-edges;
                scrollbar-width: thin;
                scrollbar-color: color-mix(in srgb, var(--accent-text) 48%, var(--border-default)) transparent;
            }
            .mixed-preview-host {
                width: 100%;
                min-width: 0;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .mixed-preview-host[data-fill-stage="true"] {
                display: flex;
                flex-direction: column;
                min-height: 100%;
                height: auto;
            }
            .mixed-preview-host .chat-message-render-chunk {
                display: block;
                width: 100%;
                min-width: 0;
                margin: 0;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .mixed-preview-host[data-fill-stage="true"] .chat-message-render-chunk {
                flex: 0 0 auto;
            }
            .mixed-preview-host .chat-message-render-chunk + .chat-message-render-chunk,
            .mixed-preview-host .chat-message-render-chunk + .chat-message-pre-anchor,
            .mixed-preview-host .chat-message-pre-anchor + .chat-message-render-chunk,
            .mixed-preview-host .chat-message-pre-anchor + .chat-message-pre-anchor {
                margin-top: 0.9rem;
            }
            .mixed-preview-host .chat-message-pre-anchor {
                display: block;
                width: 100%;
                min-width: 0;
                max-width: 100%;
                overflow: hidden;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .mixed-preview-host[data-fill-stage="true"] .chat-message-pre-anchor {
                flex: 1 1 auto;
                min-height: 100%;
                height: auto;
            }
            .mixed-preview-host .chat-reader-app-stage-shell,
            .mixed-preview-host .chat-reader-app-stage-frame,
            .mixed-preview-host .stm-render-shell,
            .mixed-preview-host .stm-render-frame {
                min-height: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
            }
            .mixed-preview-host .chat-reader-app-stage-shell,
            .mixed-preview-host .stm-render-shell {
                overflow: hidden !important;
            }
            .mixed-preview-host img {
                max-width: 100%;
                height: auto;
            }
            .mixed-preview-host pre {
                background: var(--surface-code);
                border: 1px solid var(--border-subtle);
                padding: 1em;
                border-radius: 6px;
                overflow-x: auto;
                white-space: pre-wrap;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .mixed-preview-host code {
                font-family: monospace;
                white-space: inherit;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .mixed-preview-scroll::-webkit-scrollbar,
            .mixed-preview-host pre::-webkit-scrollbar {
                width: 8px;
                height: 8px;
            }
            .mixed-preview-scroll::-webkit-scrollbar-track,
            .mixed-preview-host pre::-webkit-scrollbar-track {
                background: transparent;
            }
            .mixed-preview-scroll::-webkit-scrollbar-thumb,
            .mixed-preview-host pre::-webkit-scrollbar-thumb {
                border-radius: 999px;
                background: color-mix(in srgb, var(--accent-text) 42%, var(--border-default));
                border: 2px solid transparent;
                background-clip: padding-box;
            }
            .mixed-preview-scroll::-webkit-scrollbar-thumb:hover,
            .mixed-preview-host pre::-webkit-scrollbar-thumb:hover {
                background: color-mix(in srgb, var(--accent-text) 62%, var(--border-default));
                border: 2px solid transparent;
                background-clip: padding-box;
            }
        </style>
        <div class="mixed-preview-scroll markdown-body">
            <div class="mixed-preview-host"></div>
        </div>
    `;

  const host = shadow.querySelector(".mixed-preview-host");
  if (!(host instanceof HTMLElement)) {
    return;
  }

  if (options.fillStageHeight === true) {
    host.dataset.fillStage = "true";
  } else {
    delete host.dataset.fillStage;
  }

  el.__stmMixedPreviewHost = host;

  const source = String(content || "");
  const displaySource =
    options.applyDisplayRules === true
      ? buildUnifiedDisplaySource(source, options.config || {}, options)
      : source;
  const renderOptions = buildPreviewRenderOptions(options);
  const renderHtml = (text) => renderUnifiedDisplayHtml(text, renderOptions);
  const renderHtmlSignature = JSON.stringify({
    scopeClass: renderOptions.scopeClass,
    renderMode: renderOptions.renderMode,
    speakerName: String(renderOptions.speakerName || ""),
    stripSpeakerPrefix: renderOptions.stripSpeakerPrefix === true,
    encodeTags: renderOptions.encodeTags === true,
    promptBias: String(renderOptions.promptBias || ""),
    hidePromptBias: renderOptions.hidePromptBias === true,
    reasoningMarkers: Array.isArray(renderOptions.reasoningMarkers)
      ? renderOptions.reasoningMarkers
      : [],
    blockMedia: renderOptions.blockMedia === true,
    isMarkdown: renderOptions.isMarkdown !== false,
  });
  applyPretextIntrinsicSize(el, source, {
    ...options,
    source: displaySource,
    element: el,
    whiteSpace: "pre-wrap",
  });
  applyPretextIntrinsicSize(host, source, {
    ...options,
    source: displaySource,
    element: host,
    whiteSpace: "pre-wrap",
  });
  if (!displaySource.trim()) {
    const emptyHtml =
      options.emptyHtml || '<span class="color-text-muted italic">空内容</span>';
    host.innerHTML = emptyHtml;
    return;
  }

  loadMessageSegmentRendererModule()
    .then((module) => {
      if (el.__stmMixedPreviewVersion !== renderVersion || !el.isConnected) {
        return;
      }

      if (typeof module?.mountMessageSegmentHost !== "function") {
        throw new Error("mountMessageSegmentHost unavailable");
      }

      module.mountMessageSegmentHost(host, {
        source: displaySource,
        renderHtml,
        renderHtmlSignature,
        classifyFrontendText: (text) =>
          classifyPreviewFrontendText(text, options),
        assetBase: options.assetBase || "",
        embeddedStageStyle: options.embeddedStageStyle === true,
        fillStageHeight: options.fillStageHeight === true,
        runtimeOwner: options.runtimeOwner || "preview",
        runtimeLabel: options.runtimeLabel || "Preview Segment",
      });
    })
    .catch(() => {
      if (el.__stmMixedPreviewVersion !== renderVersion || !el.isConnected) {
        return;
      }
      host.innerHTML = renderHtml(displaySource);
    });
}

export function updateMixedPreviewContent(el, content, options = {}) {
  return renderUnifiedPreviewHost(el, content, options);
}
