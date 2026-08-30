/**
 * Semantic fallback colors for isolated previews.
 *
 * srcdoc/blob iframes do not inherit the host document's CSS custom properties,
 * so their small shell needs an explicit light/dark token set. User-authored
 * preview CSS remains untouched and can still override these defaults.
 */

const ISOLATED_PREVIEW_COLOR_TOKENS = Object.freeze({
    dark: Object.freeze({
        surfacePage: '#0f172a',
        surfaceNote: '#1e293b',
        contentPrimary: '#e2e8f0',
        contentNote: '#e2e8f0',
        borderSubtle: '#64748b',
        scrollbar: '#64748b',
        scrollbarHover: '#94a3b8',
    }),
    light: Object.freeze({
        surfacePage: '#f8fafc',
        surfaceNote: '#e2e8f0',
        contentPrimary: '#172033',
        contentNote: '#172033',
        borderSubtle: '#64748b',
        scrollbar: '#64748b',
        scrollbarHover: '#475569',
    }),
});

const BEAUTIFY_PREVIEW_COLOR_TOKENS = Object.freeze({
    dark: Object.freeze({
        avatarSurface: '#d8e8c8',
        avatarText: '#3c5a2a',
        contentPrimary: '#f8fafc',
        contentSecondary: '#cbd5e1',
        contentLink: '#38bdf8',
        contentQuote: '#f59e0b',
        blurTint: 'rgba(15, 23, 42, 0.48)',
        chatTint: 'rgba(15, 23, 42, 0.52)',
        userMessageTint: 'rgba(59, 130, 246, 0.22)',
        botMessageTint: 'rgba(15, 23, 42, 0.58)',
        shadow: 'rgba(15, 23, 42, 0.35)',
        border: 'rgba(148, 163, 184, 0.24)',
    }),
    light: Object.freeze({
        avatarSurface: '#e2e8f0',
        avatarText: '#172033',
        contentPrimary: '#172033',
        contentSecondary: '#334155',
        contentLink: '#075985',
        contentQuote: '#92400e',
        blurTint: 'rgba(248, 250, 252, 0.72)',
        chatTint: 'rgba(226, 232, 240, 0.78)',
        userMessageTint: 'rgba(37, 99, 235, 0.14)',
        botMessageTint: 'rgba(226, 232, 240, 0.64)',
        shadow: 'rgba(15, 23, 42, 0.18)',
        border: 'rgba(71, 85, 105, 0.32)',
    }),
});

export function getIsolatedPreviewColorTokens(themeMode = 'dark') {
    return ISOLATED_PREVIEW_COLOR_TOKENS[themeMode === 'light' ? 'light' : 'dark'];
}

export function getIsolatedPreviewColorVariables(themeMode = 'dark') {
    const tokens = getIsolatedPreviewColorTokens(themeMode);
    return [
        `  --preview-surface-page: ${tokens.surfacePage};`,
        `  --preview-surface-note: ${tokens.surfaceNote};`,
        `  --preview-content-primary: ${tokens.contentPrimary};`,
        `  --preview-content-note: ${tokens.contentNote};`,
        `  --preview-border-subtle: ${tokens.borderSubtle};`,
        `  --preview-scrollbar: ${tokens.scrollbar};`,
        `  --preview-scrollbar-hover: ${tokens.scrollbarHover};`,
    ];
}

export function getBeautifyPreviewColorTokens(themeMode = 'dark') {
    return BEAUTIFY_PREVIEW_COLOR_TOKENS[themeMode === 'light' ? 'light' : 'dark'];
}
