import { getIsolatedPreviewColorVariables } from './previewColorTokens.js';
import { buildAutoHeightScript, buildViewportSyncScript } from './renderFrameScripts.js';

const VIEWPORT_VAR = 'var(--stm-viewport-height)';

function normalizeAssetBase(assetBase = '') {
    const raw = String(assetBase || '').trim();
    if (!raw) {
        return `${window.location.origin}/`;
    }

    try {
        const resolved = new URL(raw, window.location.origin);
        const pathname = resolved.pathname.endsWith('/') ? resolved.pathname : `${resolved.pathname}/`;
        return `${resolved.origin}${pathname}`;
    } catch {
        return `${window.location.origin}/`;
    }
}

function convertViewportUnitValue(value) {
    return value.replace(/(\d+(?:\.\d+)?)vh\b/gi, (match, rawNumber) => {
        const parsed = Number.parseFloat(rawNumber);
        if (!Number.isFinite(parsed)) return match;
        if (parsed === 100) return VIEWPORT_VAR;
        return `calc(${VIEWPORT_VAR} * ${parsed / 100})`;
    });
}

function replaceViewportUnits(content) {
    if (!content || !/\d+(?:\.\d+)?vh\b/i.test(content)) {
        return content;
    }

    content = content.replace(
        /((?:min-|max-)?height\s*:\s*)([^;{}]*?\d+(?:\.\d+)?vh)(?=\s*[;}])/gi,
        (_match, prefix, value) => `${prefix}${convertViewportUnitValue(value)}`,
    );

    content = content.replace(
        /(style\s*=\s*(["']))([^"']*?)\2/gi,
        (match, prefix, quote, styleContent) => {
            if (!/(?:min-|max-)?height\s*:\s*[^;]*vh/i.test(styleContent)) {
                return match;
            }
            const replaced = styleContent.replace(
                /((?:min-|max-)?height\s*:\s*)([^;]*?\d+(?:\.\d+)?vh)/gi,
                (_innerMatch, innerPrefix, value) => `${innerPrefix}${convertViewportUnitValue(value)}`,
            );
            return `${prefix}${replaced}${quote}`;
        },
    );

    content = content.replace(
        /(\.style\.(?:minHeight|maxHeight|height)\s*=\s*(["']))([\s\S]*?)(\2)/gi,
        (match, prefix, _quote, value, suffix) => {
            if (!/\b\d+(?:\.\d+)?vh\b/i.test(value)) {
                return match;
            }
            return `${prefix}${convertViewportUnitValue(value)}${suffix}`;
        },
    );

    content = content.replace(
        /(setProperty\s*\(\s*(["'])(?:min-height|max-height|height)\2\s*,\s*(["']))([\s\S]*?)(\3\s*\))/gi,
        (match, prefix, _quoteOne, _quoteTwo, value, suffix) => {
            if (!/\b\d+(?:\.\d+)?vh\b/i.test(value)) {
                return match;
            }
            return `${prefix}${convertViewportUnitValue(value)}${suffix}`;
        },
    );

    return content;
}

function createSupportStyle(themeMode = 'dark') {
    const previewTokens = getIsolatedPreviewColorVariables(themeMode);

    return [
        '<style>',
        ':root {',
        '  --stm-viewport-height: 100vh;',
        '  /* Isolated iframe tokens cannot inherit the host document variables. */',
        ...previewTokens,
        '}',
        '*, *::before, *::after {',
        '  box-sizing: border-box;',
        '}',
        'html, body {',
        '  width: 100%;',
        '  max-width: 100%;',
        '  margin: 0 !important;',
        '  padding: 0 !important;',
        '  min-height: 100% !important;',
        '  height: 100% !important;',
        '  overflow-x: hidden !important;',
        '  overflow-y: auto !important;',
        '  background: transparent;',
        '}',
        'body {',
        '  position: relative !important;',
        '  color: var(--preview-content-primary);',
        '  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;',
        '}',
        'body > :not(#st-manager-note-container) {',
        '  max-width: 100% !important;',
        '}',
        '#st-manager-note-container {',
        '  display: block !important;',
        '  width: 100% !important;',
        '  padding: 16px 24px !important;',
        '  margin: 0 !important;',
        '  background: var(--preview-surface-note);',
        '  color: var(--preview-content-note);',
        '  border-bottom: 1px solid var(--preview-border-subtle);',
        '  font-size: 14px;',
        '  line-height: 1.6;',
        '  text-align: left;',
        '  white-space: normal;',
        '}',
        '#st-manager-note-container img {',
        '  max-width: 100%;',
        '  height: auto;',
        '}',
        '#st-manager-note-container pre {',
        '  overflow-x: auto;',
        '  white-space: pre-wrap;',
        '}',
        '::-webkit-scrollbar { width: 8px; height: 8px; }',
        '::-webkit-scrollbar-track { background: transparent; }',
        '::-webkit-scrollbar-thumb { background: var(--preview-scrollbar); border-radius: 4px; }',
        '::-webkit-scrollbar-thumb:hover { background: var(--preview-scrollbar-hover); }',
        '</style>',
    ].join('');
}

function createSupportHead(runtimeId, assetBase = '', themeMode = 'dark') {
    return [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        `<base href="${normalizeAssetBase(assetBase)}">`,
        createSupportStyle(themeMode),
        `<script>${buildViewportSyncScript(runtimeId).replace(/<\/script>/gi, '<\\/script>')}</script>`,
        `<script>${buildAutoHeightScript(runtimeId).replace(/<\/script>/gi, '<\\/script>')}</script>`,
    ].join('');
}

function ensureBodyInsertion(html, bodyPrefix) {
    if (!bodyPrefix) return html;

    if (/<body[\s>]/i.test(html)) {
        return html.replace(/<body([^>]*)>/i, `<body$1>${bodyPrefix}`);
    }

    if (/<\/head>/i.test(html)) {
        return html.replace(/<\/head>/i, `</head><body>${bodyPrefix}</body>`);
    }

    if (/<\/html>/i.test(html)) {
        return html.replace(/<\/html>/i, `<body>${bodyPrefix}</body></html>`);
    }

    return `${html}<body>${bodyPrefix}</body>`;
}

function injectIntoFullDocument(htmlPayload, headMarkup, bodyPrefix) {
    let finalHtml = htmlPayload;

    if (/<head[\s>]/i.test(finalHtml)) {
        finalHtml = finalHtml.replace(/<head([^>]*)>/i, `<head$1>${headMarkup}`);
    } else if (/<html[\s>]/i.test(finalHtml)) {
        finalHtml = finalHtml.replace(/<html([^>]*)>/i, `<html$1><head>${headMarkup}</head>`);
    } else {
        return `<!DOCTYPE html><html><head>${headMarkup}</head><body>${bodyPrefix}${htmlPayload}</body></html>`;
    }

    return ensureBodyInsertion(finalHtml, bodyPrefix);
}

export function buildRenderIframeDocument({ runtimeId, htmlPayload, noteHtml = '', assetBase = '', themeMode = 'dark' }) {
    const payload = replaceViewportUnits(String(htmlPayload || ''));
    const noteBlock = noteHtml ? `<div id="st-manager-note-container">${noteHtml}</div>` : '';
    const headMarkup = createSupportHead(runtimeId, assetBase, themeMode);
    const isFullDocument = /<!doctype html/i.test(payload) || /<html[\s>]/i.test(payload);

    if (isFullDocument) {
        return injectIntoFullDocument(payload, headMarkup, noteBlock);
    }

    return `<!DOCTYPE html><html><head>${headMarkup}</head><body>${noteBlock}${payload}</body></html>`;
}
