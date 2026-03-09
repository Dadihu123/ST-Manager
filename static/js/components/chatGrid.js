/**
 * static/js/components/chatGrid.js
 * 聊天记录网格与全屏阅读器组件
 */

import {
    bindChatToCard,
    deleteChat,
    getChatDetail,
    importChats,
    listChats,
    saveChat,
    updateChatMeta,
} from '../api/chat.js';
import { getCardDetail, listCards } from '../api/card.js';
import { openPath } from '../api/system.js';
import { formatDate } from '../utils/format.js';
import { ChatAppStage } from '../runtime/chatAppStage.js';
import { renderMarkdown, updateInlineRenderContent, clearInlineIsolatedHtml } from '../utils/dom.js';
import { formatScopedDisplayedHtml } from '../utils/stDisplayFormatter.js';
import { clearActiveRuntimeContext, setActiveRuntimeContext } from '../runtime/runtimeContext.js';


const CHAT_READER_REGEX_STORAGE_KEY = 'st_manager.chat_reader.regex_config.v1';
const CHAT_READER_VIEW_SETTINGS_KEY = 'st_manager.chat_reader.view_settings.v1';
const CHAT_READER_RENDER_PREFS_KEY = 'st_manager.chat_reader.render_prefs.v1';

const DEFAULT_CHAT_READER_REGEX_CONFIG = {
    displayRules: [],
};

const EMPTY_CHAT_READER_REGEX_CONFIG = {
    displayRules: [],
};

const REGEX_RULE_SOURCE_META = {
    draft: { label: '当前草稿', order: 0, tone: 'accent' },
    chat: { label: '聊天专属', order: 1, tone: 'accent' },
    card: { label: '角色卡规则', order: 2, tone: 'success' },
    local: { label: '本地默认', order: 3, tone: 'info' },
    builtin: { label: '内置模板', order: 4, tone: 'muted' },
    unknown: { label: '来源未识别', order: 9, tone: 'muted' },
};

const DEFAULT_CHAT_READER_VIEW_SETTINGS = {
    fullDisplayCount: 8,
    renderNearbyCount: 4,
    compactPreviewLength: 140,
    instanceRenderDepth: 1,
    simpleRenderRadius: 10,
    hiddenHistoryThreshold: 28,
};

const DEFAULT_CHAT_READER_RENDER_PREFS = {
    renderMode: 'markdown',
    componentMode: true,
};

const CHAT_READER_WINDOW_SIZE = 120;
const CHAT_READER_WINDOW_OVERLAP = 24;
const CHAT_READER_WINDOW_STEP = Math.max(1, CHAT_READER_WINDOW_SIZE - CHAT_READER_WINDOW_OVERLAP);


function normalizeDisplayRule(rule, index = 0) {
    const source = rule && typeof rule === 'object' ? rule : {};
    const normalizeNullableNumber = (value) => {
        if (value === null || value === undefined || value === '') return null;
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
    };

    return {
        id: source.id || `display_rule_${Date.now()}_${index}`,
        scriptName: String(source.scriptName || source.name || `规则 ${index + 1}`).trim() || `规则 ${index + 1}`,
        findRegex: String(source.findRegex || '').trim(),
        replaceString: String(source.replaceString || ''),
        substituteRegex: Number(source.substituteRegex || 0),
        trimStrings: Array.isArray(source.trimStrings) ? source.trimStrings.map(item => String(item)) : [],
        disabled: Boolean(source.disabled),
        promptOnly: Boolean(source.promptOnly),
        markdownOnly: Boolean(source.markdownOnly),
        runOnEdit: source.runOnEdit !== false,
        minDepth: normalizeNullableNumber(source.minDepth),
        maxDepth: normalizeNullableNumber(source.maxDepth),
        placement: Array.isArray(source.placement) ? source.placement : [],
        expanded: Boolean(source.expanded),
    };
}


const READER_REGEX_PLACEMENT = {
    MD_DISPLAY: 0,
    USER_INPUT: 1,
    AI_OUTPUT: 2,
    SLASH_COMMAND: 3,
    WORLD_INFO: 5,
    REASONING: 6,
};


function buildDisplayRuleKey(rule) {
    const normalized = normalizeDisplayRule(rule);
    return `${normalized.scriptName}__${normalized.findRegex}`;
}


function getRegexRuleSourceMeta(source) {
    return REGEX_RULE_SOURCE_META[source] || REGEX_RULE_SOURCE_META.unknown;
}


function markRegexConfigRuleSource(config, source) {
    const normalized = normalizeRegexConfig(config);
    return {
        ...normalized,
        displayRules: normalized.displayRules.map((rule) => ({
            ...rule,
            source: rule.source || source,
        })),
    };
}


function parseSillyTavernRegexRules(jsonData) {
    const rules = [];

    const pushRule = (item) => {
        if (!item || typeof item !== 'object' || !item.findRegex) return;
        const normalized = {
            scriptName: String(item.scriptName || item.name || `规则 ${rules.length + 1}`).trim() || `规则 ${rules.length + 1}`,
            findRegex: String(item.findRegex || '').trim(),
            replaceString: String(item.replaceString || ''),
            substituteRegex: Number(item.substituteRegex || 0),
            trimStrings: Array.isArray(item.trimStrings) ? item.trimStrings.map(entry => String(entry)) : [],
            disabled: Boolean(item.disabled),
            promptOnly: Boolean(item.promptOnly),
            markdownOnly: Boolean(item.markdownOnly),
            runOnEdit: item.runOnEdit !== false,
            minDepth: item.minDepth ?? null,
            maxDepth: item.maxDepth ?? null,
            placement: Array.isArray(item.placement) ? item.placement : [],
        };
        const duplicate = rules.some(existing => existing.scriptName === normalized.scriptName && existing.findRegex === normalized.findRegex);
        if (!duplicate) {
            rules.push(normalized);
        }
    };

    if (Array.isArray(jsonData)) {
        jsonData.forEach(pushRule);
        return rules;
    }

    if (Array.isArray(jsonData?.extensions?.regex_scripts)) {
        jsonData.extensions.regex_scripts.forEach(pushRule);
    }

    if (Array.isArray(jsonData?.extensions?.SPreset?.RegexBinding?.regexes)) {
        jsonData.extensions.SPreset.RegexBinding.regexes.forEach(pushRule);
    }

    if (jsonData?.extensions?.SPreset?.config) {
        try {
            const configObj = typeof jsonData.extensions.SPreset.config === 'string'
                ? JSON.parse(jsonData.extensions.SPreset.config)
                : jsonData.extensions.SPreset.config;
            if (Array.isArray(configObj?.RegexBinding?.regexes)) {
                configObj.RegexBinding.regexes.forEach(pushRule);
            }
        } catch {
            // Ignore invalid nested config payloads.
        }
    }

    return rules;
}


function filterReaderDisplayRules(rules) {
    return rules.filter((rule) => {
        if (!rule || rule.disabled || rule.promptOnly) return false;
        if (!Array.isArray(rule.placement) || rule.placement.length === 0) return true;
        return rule.placement.includes(2);
    });
}


function convertRulesToReaderConfig(rules, currentConfig, options = {}) {
    const fillDefaults = options.fillDefaults !== false;
    const nextConfig = normalizeRegexConfig(currentConfig, { fillDefaults });
    const displayRules = [];
    const displayCandidates = filterReaderDisplayRules(rules);
    const sourceTag = options.source || 'draft';

        displayCandidates.forEach((rule) => {
            displayRules.push(normalizeDisplayRule({
                scriptName: rule.scriptName,
                findRegex: rule.findRegex,
                replaceString: rule.replaceString,
                substituteRegex: rule.substituteRegex,
                trimStrings: rule.trimStrings,
                disabled: rule.disabled,
                promptOnly: rule.promptOnly,
                markdownOnly: rule.markdownOnly,
                runOnEdit: rule.runOnEdit,
                minDepth: rule.minDepth,
                maxDepth: rule.maxDepth,
                placement: Array.isArray(rule.placement) ? [...rule.placement] : [],
                source: sourceTag,
            }, displayRules.length));
        });

    nextConfig.displayRules = displayRules;
    return normalizeRegexConfig(nextConfig, { fillDefaults });
}


function normalizeRegexConfig(raw, options = {}) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const fallback = options.fillDefaults === false
        ? EMPTY_CHAT_READER_REGEX_CONFIG
        : DEFAULT_CHAT_READER_REGEX_CONFIG;

    return {
        displayRules: Array.isArray(source.displayRules)
            ? source.displayRules.map((item, index) => normalizeDisplayRule(item, index)).filter(item => item.findRegex)
            : [],
    };
}


function mergeRegexConfigs(baseConfig, overrideConfig) {
    const base = normalizeRegexConfig(baseConfig);
    const override = normalizeRegexConfig(overrideConfig, { fillDefaults: false });

    const next = {
        displayRules: [],
    };

    const mergedRules = [];
    const seen = new Map();
    const feedRule = (rule, expanded = false, replaceExisting = false) => {
        const normalized = normalizeDisplayRule({ ...rule, expanded });
        const key = `${normalized.scriptName}__${normalized.findRegex}`;
        if (!normalized.findRegex) return;

        if (seen.has(key)) {
            if (replaceExisting) {
                mergedRules[seen.get(key)] = normalized;
            }
            return;
        }

        seen.set(key, mergedRules.length);
        mergedRules.push(normalized);
    };

    base.displayRules.forEach(rule => feedRule(rule, false, false));
    override.displayRules.forEach(rule => feedRule(rule, false, true));
    next.displayRules = mergedRules;
    return next;
}


function hasCustomRegexConfig(config) {
    const normalized = normalizeRegexConfig(config, { fillDefaults: false });
    return normalized.displayRules.length > 0;
}


function deriveReaderConfigFromCard(cardDetail) {
    const source = cardDetail?.card && typeof cardDetail.card === 'object'
        ? cardDetail.card
        : cardDetail;

    if (!source || typeof source !== 'object') {
        return normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
    }

    const rules = parseSillyTavernRegexRules(source);
    if (!rules.length) {
        return normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
    }

    return convertRulesToReaderConfig(rules, EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false, source: 'card' });
}


function ensureChatMetadataShape(metadata) {
    if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return {};
    }

    const next = { ...metadata };
    if (Object.keys(next).length === 0) {
        return {};
    }

    if (!Object.prototype.hasOwnProperty.call(next, 'chat_metadata') || typeof next.chat_metadata !== 'object' || Array.isArray(next.chat_metadata)) {
        next.chat_metadata = {};
    }

    return next;
}


function stripCommonIndent(text) {
    const source = String(text || '').replace(/\r\n/g, '\n');
    const lines = source.split('\n');

    while (lines.length && !lines[0].trim()) {
        lines.shift();
    }
    while (lines.length && !lines[lines.length - 1].trim()) {
        lines.pop();
    }

    const indents = lines
        .filter(line => line.trim())
        .map((line) => {
            const match = line.match(/^\s*/);
            return match ? match[0].length : 0;
        });

    const minIndent = indents.length ? Math.min(...indents) : 0;
    return lines.map(line => line.slice(minIndent)).join('\n').trim();
}


function normalizeViewSettings(raw) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const fullDisplayCount = Number.parseInt(source.fullDisplayCount, 10);
    const renderNearbyCount = Number.parseInt(source.renderNearbyCount, 10);
    const compactPreviewLength = Number.parseInt(source.compactPreviewLength, 10);
    const instanceRenderDepth = Number.parseInt(source.instanceRenderDepth, 10);
    const simpleRenderRadius = Number.parseInt(source.simpleRenderRadius, 10);
    const hiddenHistoryThreshold = Number.parseInt(source.hiddenHistoryThreshold, 10);

    return {
        fullDisplayCount: Number.isFinite(fullDisplayCount)
            ? Math.min(40, Math.max(3, fullDisplayCount))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount,
        renderNearbyCount: Number.isFinite(renderNearbyCount)
            ? Math.min(20, Math.max(1, renderNearbyCount))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount,
        compactPreviewLength: Number.isFinite(compactPreviewLength)
            ? Math.min(400, Math.max(40, compactPreviewLength))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.compactPreviewLength,
        instanceRenderDepth: Number.isFinite(instanceRenderDepth)
            ? Math.min(50, Math.max(0, instanceRenderDepth))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth,
        simpleRenderRadius: Number.isFinite(simpleRenderRadius)
            ? Math.min(60, Math.max(0, simpleRenderRadius))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius,
        hiddenHistoryThreshold: Number.isFinite(hiddenHistoryThreshold)
            ? Math.min(120, Math.max(0, hiddenHistoryThreshold))
            : DEFAULT_CHAT_READER_VIEW_SETTINGS.hiddenHistoryThreshold,
    };
}


function loadStoredViewSettings() {
    try {
        const raw = window.localStorage.getItem(CHAT_READER_VIEW_SETTINGS_KEY);
        if (!raw) return normalizeViewSettings(DEFAULT_CHAT_READER_VIEW_SETTINGS);
        return normalizeViewSettings(JSON.parse(raw));
    } catch {
        return normalizeViewSettings(DEFAULT_CHAT_READER_VIEW_SETTINGS);
    }
}


function storeViewSettings(settings) {
    try {
        window.localStorage.setItem(CHAT_READER_VIEW_SETTINGS_KEY, JSON.stringify(normalizeViewSettings(settings)));
    } catch {
        // Ignore storage failures in the reader.
    }
}


function createReaderVisibleMessagesCache() {
    return {
        messagesRef: null,
        bookmarksRef: null,
        detailBookmarkedOnly: false,
        currentFloor: 0,
        windowStartFloor: 0,
        windowEndFloor: 0,
        fullCount: 0,
        renderNearby: 0,
        simpleRenderRadius: 0,
        hiddenHistoryThreshold: 0,
        compactPreviewLength: 0,
        result: [],
    };
}


const readerVisibleMessagesCacheMap = new WeakMap();


function getReaderVisibleMessagesCache(owner) {
    const cache = readerVisibleMessagesCacheMap.get(owner);
    if (cache) {
        return cache;
    }

    const next = createReaderVisibleMessagesCache();
    readerVisibleMessagesCacheMap.set(owner, next);
    return next;
}


function resetReaderVisibleMessagesCache(owner) {
    if (!owner) return;
    readerVisibleMessagesCacheMap.set(owner, createReaderVisibleMessagesCache());
}


function findFloorCardFromNode(node) {
    let current = node instanceof Node ? node : null;

    while (current) {
        if (current instanceof Element) {
            const direct = current.closest('[data-chat-floor]');
            if (direct) {
                return direct;
            }
        }

        const root = typeof current.getRootNode === 'function' ? current.getRootNode() : null;
        if (root instanceof ShadowRoot && root.host) {
            current = root.host;
            continue;
        }

        break;
    }

    return null;
}


function normalizeRenderPreferences(raw) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const renderMode = source.renderMode === 'plain' ? 'plain' : 'markdown';

    return {
        renderMode,
        componentMode: source.componentMode !== false,
    };
}


function loadStoredRenderPreferences() {
    try {
        const raw = window.localStorage.getItem(CHAT_READER_RENDER_PREFS_KEY);
        if (!raw) return normalizeRenderPreferences(DEFAULT_CHAT_READER_RENDER_PREFS);
        return normalizeRenderPreferences(JSON.parse(raw));
    } catch {
        return normalizeRenderPreferences(DEFAULT_CHAT_READER_RENDER_PREFS);
    }
}


function storeRenderPreferences(preferences) {
    try {
        window.localStorage.setItem(
            CHAT_READER_RENDER_PREFS_KEY,
            JSON.stringify(normalizeRenderPreferences(preferences)),
        );
    } catch {
        // Ignore storage failures in the reader.
    }
}


function loadStoredRegexConfig() {
    try {
        const raw = window.localStorage.getItem(CHAT_READER_REGEX_STORAGE_KEY);
        if (!raw) return normalizeRegexConfig(DEFAULT_CHAT_READER_REGEX_CONFIG);
        return normalizeRegexConfig(JSON.parse(raw));
    } catch {
        return normalizeRegexConfig(DEFAULT_CHAT_READER_REGEX_CONFIG);
    }
}


function storeRegexConfig(config) {
    try {
        window.localStorage.setItem(CHAT_READER_REGEX_STORAGE_KEY, JSON.stringify(normalizeRegexConfig(config)));
    } catch {
        // Ignore storage failures in the reader.
    }
}


function compileReaderPattern(pattern, flags = '') {
    if (!pattern) return null;
    try {
        const source = String(pattern);
        const wrapped = source.match(/^\/([\s\S]+)\/([dgimsuvy]*)$/);
        if (wrapped) {
            const mergedFlags = Array.from(new Set(`${wrapped[2]}${flags}`.split(''))).join('');
            return new RegExp(wrapped[1], mergedFlags);
        }
        return new RegExp(source, flags);
    } catch {
        return null;
    }
}


function parseDisplayRuleRegex(findRegex) {
    const source = String(findRegex || '').trim();
    if (!source) return null;

    const wrapped = source.match(/^\/([\s\S]+)\/([dgimsuvy]*)$/);
    if (wrapped) {
        return new RegExp(wrapped[1], wrapped[2]);
    }

    return new RegExp(source, 'g');
}


function sanitizeRegexMacroValue(value) {
    return String(value ?? '').replaceAll(/[\n\r\t\v\f\0.^$*+?{}[\]\\/|()]/gs, (token) => {
        switch (token) {
            case '\n':
                return '\\n';
            case '\r':
                return '\\r';
            case '\t':
                return '\\t';
            case '\v':
                return '\\v';
            case '\f':
                return '\\f';
            case '\0':
                return '\\0';
            default:
                return `\\${token}`;
        }
    });
}


function substituteDisplayRuleMacros(text, macroContext = {}, sanitizer = null) {
    const source = String(text ?? '');
    const context = macroContext && typeof macroContext === 'object' ? macroContext : {};

    return source.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (match, rawKey) => {
        const key = String(rawKey || '').trim().toLowerCase();
        const value = Object.prototype.hasOwnProperty.call(context, key)
            ? context[key]
            : Object.prototype.hasOwnProperty.call(context, rawKey)
                ? context[rawKey]
                : match;
        const normalized = String(value ?? '');
        return typeof sanitizer === 'function' ? sanitizer(normalized) : normalized;
    });
}


function getDisplayRuleRegexSource(rule, options = {}) {
    const normalized = normalizeDisplayRule(rule);
    switch (Number(normalized.substituteRegex || 0)) {
        case 1:
            return substituteDisplayRuleMacros(normalized.findRegex, options.macroContext);
        case 2:
            return substituteDisplayRuleMacros(normalized.findRegex, options.macroContext, sanitizeRegexMacroValue);
        default:
            return normalized.findRegex;
    }
}


function applyDisplayRules(text, config) {
    let content = String(text || '');
    const rules = Array.isArray(config?.displayRules) ? config.displayRules : [];
    const options = arguments[2] && typeof arguments[2] === 'object' ? arguments[2] : {};
    const placement = Number(options.placement ?? READER_REGEX_PLACEMENT.AI_OUTPUT);
    const isMarkdown = options.isMarkdown !== false;
    const isPrompt = options.isPrompt === true;
    const isEdit = options.isEdit === true;
    const readerDisplayRules = options.readerDisplayRules === true;
    const macroContext = options.macroContext && typeof options.macroContext === 'object' ? options.macroContext : {};
    const depth = typeof options.depth === 'number' ? options.depth : null;
    const normalizeDepthBound = (value) => {
        if (value === null || value === undefined || value === '') return null;
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
    };

    const filterTrimStrings = (value, trimStrings = []) => {
        let output = String(value ?? '');
        for (const trimString of trimStrings) {
            const needle = substituteDisplayRuleMacros(trimString || '', macroContext);
            if (!needle) continue;
            output = output.split(needle).join('');
        }
        return output;
    };

    for (const rule of rules) {
        if (!rule || rule.disabled || !rule.findRegex) continue;
        if (rule.promptOnly && !isPrompt) continue;
        if (!readerDisplayRules) {
            if ((rule.markdownOnly && isMarkdown)
                || (rule.promptOnly && isPrompt)
                || (!rule.markdownOnly && !rule.promptOnly && !isMarkdown && !isPrompt)) {
                // allowed
            } else {
                continue;
            }
        }
        if (isEdit && rule.runOnEdit === false) continue;
        if (Array.isArray(rule.placement) && rule.placement.length > 0 && !rule.placement.includes(placement)) continue;
        if (depth !== null) {
            const minDepth = normalizeDepthBound(rule.minDepth);
            const maxDepth = normalizeDepthBound(rule.maxDepth);
            if (minDepth !== null && minDepth >= -1 && depth < minDepth) continue;
            if (maxDepth !== null && maxDepth >= 0 && depth > maxDepth) continue;
        }
        try {
            const regex = parseDisplayRuleRegex(getDisplayRuleRegexSource(rule, { macroContext }));
            if (!regex) continue;
            content = content.replace(regex, (...args) => {
                const replaceString = String(rule.replaceString || '').replace(/\{\{match\}\}/gi, '$0');
                const lastArg = args[args.length - 1];
                const groups = lastArg && typeof lastArg === 'object' ? lastArg : null;
                const captureEndIndex = groups ? args.length - 3 : args.length - 2;
                const captures = args.slice(0, captureEndIndex);

                const replaceWithGroups = replaceString.replaceAll(/\$(\d+)|\$<([^>]+)>|\$0/g, (token, num, groupName) => {
                    if (token === '$0') {
                        return filterTrimStrings(captures[0] ?? '', rule.trimStrings);
                    }

                    if (num) {
                        return filterTrimStrings(captures[Number(num)] ?? '', rule.trimStrings);
                    }

                    if (groupName) {
                        return filterTrimStrings(groups?.[groupName] ?? '', rule.trimStrings);
                    }

                    return '';
                });

                return substituteDisplayRuleMacros(replaceWithGroups, macroContext);
            });
        } catch {
            continue;
        }
    }

    return content;
}


function getMessageExecutableParts(message, host = null) {
    const parts = [];
    const seen = new Set();

    if (host instanceof Element) {
        const codeNodes = Array.from(host.querySelectorAll('pre code'));
        codeNodes.forEach((node) => {
            const text = String(node.textContent || '').trim();
            if (!text) return;
            const analysis = analyzeRuntimeCandidate(text);
            if (analysis.isCandidate && !seen.has(text)) {
                seen.add(text);
                parts.push({ type: 'app-stage', text });
            }
        });
    }

    return parts;
}


function resolveBestMessageExecutablePart(message, host = null) {
    const parts = getMessageExecutableParts(message, host);
    if (!parts.length) return null;

    const scorePart = (part) => {
        let score = 0;
        const text = String(part?.text || '');

        if (part?.type === 'app-stage') score += 100;
        if (/<!doctype html/i.test(text) || /<html[\s>]/i.test(text)) score += 40;
        if (/id=["']readingContent["']/i.test(text)) score += 20;
        if (/function\s+processTextContent\s*\(/i.test(text)) score += 12;
        if (/window\.setTheme\s*=\s*applyTheme/i.test(text)) score += 8;
        if (/showArgMenu\s*\(/i.test(text)) score += 6;
        return score;
    };

    return parts
        .slice()
        .sort((left, right) => scorePart(right) - scorePart(left) || String(right.text || '').length - String(left.text || '').length)[0] || null;
}


function createRuntimeCandidateCache() {
    return {
        floorMap: new Map(),
        executableFloorsKey: '',
        executableFloors: [],
    };
}


function looksLikeFrontendSnippet(source) {
    const text = String(source || '').toLowerCase();
    return ['html>', '<head>', '<body', '<!doctype html'].some(token => text.includes(token));
}


function analyzeRuntimeCandidate(source) {
    const normalizedText = String(source || '').trim();
    const analysis = scoreFullPageAppHtml(normalizedText);
    const frontendLike = looksLikeFrontendSnippet(normalizedText);
    const boostedScore = frontendLike && analysis.score < 8 ? analysis.score + 8 : analysis.score;
    const reasons = frontendLike && !analysis.reasons.includes('frontend-like')
        ? [...analysis.reasons, 'frontend-like']
        : analysis.reasons;

    return {
        ...analysis,
        score: boostedScore,
        reasons,
        frontendLike,
        isCandidate: frontendLike || analysis.score >= 8,
    };
}


function getRenderedDisplayHtmlForMessage(message, renderedFloorHtmlCache = null) {
    const floor = Number(message?.floor || 0);
    if (renderedFloorHtmlCache instanceof Map && floor > 0 && renderedFloorHtmlCache.has(floor)) {
        return String(renderedFloorHtmlCache.get(floor) || '');
    }

    return String(message?.rendered_display_html || '');
}


function buildReaderCacheScopeKey(activeChat, floor = 0, message = null) {
    const chatId = resolveReaderMessageChatId(message, activeChat);
    return `${chatId}:${Number(floor || 0)}`;
}


function getRuntimeScanCandidateFloors(activeChat, viewSettings = null) {
    const messages = Array.isArray(activeChat?.messages) ? activeChat.messages : [];
    if (!messages.length) return [];

    const total = messages.length;
    const settings = viewSettings && typeof viewSettings === 'object' ? viewSettings : DEFAULT_CHAT_READER_VIEW_SETTINGS;
    const recentTailCount = Math.max(
        Number(settings.fullDisplayCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount),
        Number(settings.instanceRenderDepth || DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth),
        8,
    );
    const viewportFloor = Math.min(total, Math.max(1, Number(activeChat?.last_view_floor || total || 1)));
    const nearRadius = Math.max(
        Number(settings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount),
        Number(settings.simpleRenderRadius || DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius),
    );
    const recentStartFloor = Math.max(1, total - recentTailCount + 1);
    const nearStartFloor = Math.max(1, viewportFloor - nearRadius);
    const nearEndFloor = Math.min(total, viewportFloor + nearRadius);
    const candidateSet = new Set();

    for (let floor = recentStartFloor; floor <= total; floor += 1) {
        candidateSet.add(floor);
    }

    for (let floor = nearStartFloor; floor <= nearEndFloor; floor += 1) {
        candidateSet.add(floor);
    }

    return Array.from(candidateSet).sort((left, right) => left - right);
}


function buildRuntimeHostId(floor, index = 0) {
    return `st-runtime-host-${Number(floor || 0)}-${Number(index || 0)}`;
}


function buildRuntimeCandidateSignature(candidates = []) {
    return candidates
        .map((candidate, index) => `${index}:${Number(candidate.score || 0)}:${String(candidate.text || '').length}`)
        .join('|');
}


function wrapRuntimeHostsInContainer(container, floor) {
    if (!(container instanceof Element)) return [];

    const wrappedHosts = [];
    let runtimeIndex = 0;

    Array.from(container.querySelectorAll('pre')).forEach((preNode) => {
        const codeNode = preNode.querySelector('code');
        const rawCodeText = String(codeNode?.textContent || '').trim();
        const preText = String(preNode.textContent || '').trim();
        const text = rawCodeText || preText;
        if (!text) return;

        const normalizedText = text
            .replace(/^```(?:html|text|xml)?\s*/i, '')
            .replace(/```$/i, '')
            .trim();
        const analysis = analyzeRuntimeCandidate(normalizedText);
        if (!analysis.isCandidate) return;

        const existingWrapper = preNode.parentElement?.classList.contains('chat-inline-runtime-wrap')
            ? preNode.parentElement
            : null;
        if (existingWrapper) {
            const existingHost = existingWrapper.querySelector('.chat-inline-runtime-host');
            if (existingHost instanceof Element) {
                existingHost.id = buildRuntimeHostId(floor, runtimeIndex);
                wrappedHosts.push(existingHost);
                runtimeIndex += 1;
            }
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'chat-inline-runtime-wrap';
        const host = document.createElement('div');
        host.id = buildRuntimeHostId(floor, runtimeIndex);
        host.className = 'chat-inline-runtime-host';
        preNode.classList.add('chat-inline-runtime-source');

        preNode.replaceWith(wrapper);
        wrapper.appendChild(host);
        wrapper.appendChild(preNode);
        wrappedHosts.push(host);
        runtimeIndex += 1;
    });

    return wrappedHosts;
}


function setRuntimeWrapperActive(host, active) {
    const wrapper = host instanceof Element ? host.closest('.chat-inline-runtime-wrap') : null;
    if (wrapper instanceof Element) {
        wrapper.classList.toggle('is-active', Boolean(active));
    }
}


function getExecutableMessageFloors(activeChat, renderedFloorHtmlCache = null, viewSettings = null) {
    if (!activeChat || typeof activeChat !== 'object') {
        return [];
    }

    const messages = Array.isArray(activeChat?.messages) ? activeChat.messages : [];
    if (!messages.length) {
        return [];
    }

    const scanFloors = getRuntimeScanCandidateFloors(activeChat, viewSettings);
    const floorSet = new Set(scanFloors);
    const key = messages
        .filter(message => floorSet.has(Number(message?.floor || 0)))
        .map(message => `${Number(message?.floor || 0)}:${getRenderedDisplayHtmlForMessage(message, renderedFloorHtmlCache).length}`)
        .join('|');

    const cache = activeChat.runtime_candidate_cache || createRuntimeCandidateCache();
    if (cache.executableFloorsKey === key) {
        return cache.executableFloors;
    }

    const executableFloors = messages
        .filter(message => floorSet.has(Number(message?.floor || 0)))
        .filter(message => extractRuntimeCandidatesFromRenderedHtml(getRenderedDisplayHtmlForMessage(message, renderedFloorHtmlCache)).length > 0)
        .map(message => Number(message.floor || 0))
        .filter(Boolean);

    activeChat.runtime_candidate_cache = {
        ...cache,
        executableFloorsKey: key,
        executableFloors,
    };
    return executableFloors;
}


function shouldExecuteMessageSegments(message, activeChat, viewSettings, renderedFloorHtmlCache = null) {
    const floor = Number(message?.floor || 0);
    if (!floor) return false;
    if (!activeChat || typeof activeChat !== 'object') return false;

    const candidateFloors = getExecutableMessageFloors(activeChat, renderedFloorHtmlCache, viewSettings);
    if (!candidateFloors.length || !candidateFloors.includes(floor)) {
        return false;
    }

    const depth = Number(viewSettings?.instanceRenderDepth ?? DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth);
    if (depth === 0) {
        return true;
    }

    return candidateFloors.slice(-depth).includes(floor);
}


function buildDeferredInstancePlaceholder(message, viewSettings) {
    const floor = Number(message?.floor || 0);
    const depth = Number(viewSettings?.instanceRenderDepth ?? DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth);
    const scopeText = depth === 0 ? '全部实例楼层都会执行。' : `当前只执行最近 ${depth} 个实例楼层。`;

    return [
        '### 实例预览已折叠',
        `楼层 #${floor} 的前端实例未进入当前执行范围。`,
        scopeText,
        '可点击楼层头部的“实例”按钮，或切换到整页实例模式查看该楼层。',
    ].join('\n\n');
}


function extractRuntimeCandidatesFromContainer(container) {
    if (!(container instanceof Element)) return [];

    const parts = [];
    const seen = new Set();

    Array.from(container.querySelectorAll('pre')).forEach((node) => {
        const codeNode = node.querySelector('code');
        const rawCodeText = String(codeNode?.textContent || '').trim();
        const preText = String(node.textContent || '').trim();
        const text = rawCodeText || preText;
        const normalizedText = text
            .replace(/^```(?:html|text|xml)?\s*/i, '')
            .replace(/```$/i, '')
            .trim();
        if (!text || seen.has(text)) return;
        const analysis = analyzeRuntimeCandidate(normalizedText);
        if (analysis.isCandidate) {
            seen.add(text);
            parts.push({
                type: 'app-stage',
                text: normalizedText,
                score: analysis.score,
                reasons: analysis.reasons,
                host: node,
            });
        }
    });

    return parts;
}


function extractRuntimeCandidatesFromRenderedHtml(renderedHtml) {
    const source = String(renderedHtml || '').trim();
    if (!source) return [];

    const probe = document.createElement('div');
    probe.innerHTML = source;
    return extractRuntimeCandidatesFromContainer(probe);
}


function scoreFullPageAppHtml(htmlPayload) {
    const source = String(htmlPayload || '');
    if (!source.trim()) {
        return { score: 0, reasons: ['empty'] };
    }

    let score = 0;
    const reasons = [];
    const add = (value, reason) => {
        score += value;
        reasons.push(reason);
    };

    if (/<!DOCTYPE html/i.test(source) || /<html[\s>]/i.test(source)) add(2, 'full-document');
    if (/id=["']readingContent["']/i.test(source)) add(8, 'reading-content-root');
    if (/function\s+processTextContent\s*\(/i.test(source)) add(8, 'process-text-content');
    if (/window\.setTheme\s*=\s*applyTheme/i.test(source)) add(5, 'theme-switcher');
    if (/class=["'][^"']*theme-controls/i.test(source)) add(3, 'theme-controls');
    if (/showArgMenu\s*\(/i.test(source)) add(4, 'argument-menu');
    if (/Mvu\.getMvuData\s*\(/i.test(source)) add(4, 'mvu-data');
    if (/triggerSlash\s*\(/i.test(source)) add(4, 'slash-bridge');
    if (/class=["'][^"']*dialogue-container/i.test(source) || /createDialogueElement\s*\(/i.test(source)) add(4, 'dialogue-layout');
    if (/class=["'][^"']*grimoire-container/i.test(source)) add(3, 'full-reader-shell');
    if (/position:\s*fixed/i.test(source) && /class=["'][^"']*header/i.test(source)) add(2, 'fixed-header');

    if (/sakura-collapsible/i.test(source)) add(-8, 'collapsible-widget');
    if (/Sakura\s*-\s*折叠栏/i.test(source)) add(-10, 'thinking-widget');
    if (/id=["']raw-markdown["']/i.test(source)) add(-6, 'inline-markdown-widget');
    if (/toggleCollapsible\s*\(/i.test(source) && !/processTextContent\s*\(/i.test(source)) add(-4, 'standalone-collapse-control');

    return { score, reasons };
}


function extractStatDataFromMessage(message) {
    const source = message && typeof message === 'object' ? message : {};

    if (source.extra && typeof source.extra === 'object' && source.extra.stat_data) {
        return cloneValue(source.extra.stat_data);
    }

    const variables = Array.isArray(source.variables) ? source.variables : [];
    for (const entry of variables) {
        if (entry && typeof entry === 'object' && entry.stat_data) {
            return cloneValue(entry.stat_data);
        }
    }

    return null;
}


function resolveLatestStatData(rawMessages, floor) {
    const list = Array.isArray(rawMessages) ? rawMessages : [];
    const startIndex = Math.min(list.length - 1, Math.max(0, Number(floor || 1) - 1));

    for (let index = startIndex; index >= 0; index -= 1) {
        const statData = extractStatDataFromMessage(list[index]);
        if (statData) {
            return statData;
        }
    }

    return {};
}


function normalizeReaderMessageSource(message) {
    const source = message && typeof message === 'object' ? message : {};
    const extra = source.extra && typeof source.extra === 'object' ? source.extra : {};
    return String(extra.display_text ?? source.mes ?? '');
}


function resolveReaderRegexPlacement(message) {
    const source = message && typeof message === 'object' ? message : {};
    const extra = source.extra && typeof source.extra === 'object' ? source.extra : {};

    if (source.is_user) {
        return READER_REGEX_PLACEMENT.USER_INPUT;
    }
    if (extra.type === 'narrator') {
        return READER_REGEX_PLACEMENT.SLASH_COMMAND;
    }
    return READER_REGEX_PLACEMENT.AI_OUTPUT;
}


function resolveReaderMessageDepth(rawMessages, floor) {
    const list = Array.isArray(rawMessages) ? rawMessages : [];
    const usableMessages = list
        .map((item, index) => ({ message: item, index: index + 1 }))
        .filter(entry => !entry.message?.is_system);
    const currentIndex = usableMessages.findIndex(entry => entry.index === Number(floor || 0));
    if (currentIndex === -1) {
        return null;
    }
    return usableMessages.length - currentIndex - 1;
}


function isReaderRenderableSystemMessage(message) {
    const source = message && typeof message === 'object' ? message : {};
    if (!source.is_system) return false;

    const extra = source.extra && typeof source.extra === 'object' ? source.extra : {};
    if (source.name && source.name !== 'System') {
        return true;
    }

    return Boolean(extra.display_text);
}


function resolveReaderFormatFlags(message) {
    const source = message && typeof message === 'object' ? message : {};
    const extra = source.extra && typeof source.extra === 'object' ? source.extra : {};

    return {
        encodeTags: false,
        promptBias: '',
        hidePromptBias: !source.is_user && !source.is_system,
        reasoningMarkers: [],
        stripSpeakerPrefix: !source.is_user && !source.is_system,
        speakerName: String(source.name || ''),
        usesSystemUi: Boolean(extra.uses_system_ui),
    };
}


function buildReaderDisplaySource(messageText, config, options = {}) {
    if (!messageText) return '';

    let displayText = String(messageText || '');
    const macroContext = options.macroContext && typeof options.macroContext === 'object' ? options.macroContext : {};
    const depth = typeof options.depth === 'number' ? options.depth : null;

    displayText = displayText.replace(/以下是用户的本轮输入[\s\S]*?<\/本轮用户输入>/g, '');
    const strippedDisplayText = stripCommonIndent(displayText);

    return applyDisplayRules(strippedDisplayText, config, {
        ...options,
        placement: READER_REGEX_PLACEMENT.MD_DISPLAY,
        isMarkdown: true,
        readerDisplayRules: true,
        macroContext,
        depth,
    });
}


function extractSingleMatch(messageText, pattern) {
    if (!messageText || !pattern) return null;
    const regex = compileReaderPattern(pattern, 'i');
    if (!regex) return null;
    const match = String(messageText).match(regex);
    if (!match || !match[1]) return null;
    return stripCommonIndent(match[1]);
}


function extractSingleMatchWithIndex(messageText, pattern) {
    if (!messageText || !pattern) return null;
    const regex = compileReaderPattern(pattern, 'i');
    if (!regex) return null;
    const match = regex.exec(String(messageText));
    if (!match || !match[1]) return null;
    return {
        text: stripCommonIndent(match[1]),
        index: Number(match.index || 0),
    };
}


function extractTagBlockWithIndex(messageText, tagNames = []) {
    const source = String(messageText || '');
    for (const tagName of tagNames) {
        const regex = new RegExp(`<${tagName}>([\\s\\S]*?)<\/${tagName}>`, 'i');
        const match = regex.exec(source);
        if (match && match[1]) {
            return {
                text: stripCommonIndent(match[1]),
                index: Number(match.index || 0),
            };
        }
    }
    return null;
}


function buildReaderParsedMessage(rawMessage, floor, config, options = {}) {
    const source = rawMessage && typeof rawMessage === 'object' ? rawMessage : {};
    const messageText = normalizeReaderMessageSource(source);
    const treatedAsSystem = Boolean(source.is_system) && !isReaderRenderableSystemMessage(source);
    const chatId = String(options.chatId || '');

    return {
        chat_id: chatId,
        floor: Number(floor || 0),
        name: source.name || 'Unknown',
        is_user: Boolean(source.is_user),
        is_system: Boolean(source.is_system),
        send_date: source.send_date || '',
        mes: messageText,
        swipes: Array.isArray(source.swipes) ? source.swipes : [],
        extra: source.extra && typeof source.extra === 'object' ? source.extra : {},
        content: messageText,
        display_source: treatedAsSystem ? messageText : '',
        rendered_display_html: '',
        time_bar: null,
        summary: null,
        thinking: null,
        choices: [],
        render_segments: [],
    };
}


function resolveReaderMessageChatId(message, activeChat = null) {
    const directChatId = message && typeof message === 'object' && Object.prototype.hasOwnProperty.call(message, 'chat_id')
        ? String(message.chat_id || '')
        : '';
    if (directChatId) {
        return directChatId;
    }

    if (activeChat && typeof activeChat === 'object' && activeChat.id) {
        return String(activeChat.id);
    }

    return 'chat-preview';
}


function buildCompactPreview(message, limit = DEFAULT_CHAT_READER_VIEW_SETTINGS.compactPreviewLength) {
    const source = message && typeof message === 'object' ? message : {};
    const parts = [];

    if (source.time_bar) parts.push(String(source.time_bar));
    if (source.content) parts.push(String(source.content));
    else if (source.mes) parts.push(String(source.mes));
    if (source.summary) parts.push(`总结: ${source.summary}`);

    const compact = parts
        .join(' · ')
        .replace(/\s+/g, ' ')
        .trim();

    if (!compact) return '空内容';
    if (compact.length <= limit) return compact;
    return `${compact.slice(0, limit)}...`;
}


function buildPlaceholderPreview(message, limit = 72) {
    const source = message && typeof message === 'object' ? message : {};
    const base = source.time_bar
        ? `${source.time_bar} · ${source.name || ''}`
        : `${source.name || ''}`;
    const compact = buildCompactPreview(source, Math.max(32, limit)).replace(/\s+/g, ' ').trim();
    if (!compact) {
        return (base || '历史楼层').trim();
    }
    return `${(base || '历史楼层').trim()} · ${compact}`.trim();
}


function ensureReaderDisplaySource(message, config, options = {}) {
    const source = message && typeof message === 'object' ? message : {};
    if (source.display_source) {
        return String(source.display_source || '');
    }

    const messageText = normalizeReaderMessageSource(source);
    const treatedAsSystem = Boolean(source.is_system) && !isReaderRenderableSystemMessage(source);
    const nextDisplaySource = treatedAsSystem
        ? messageText
        : buildReaderDisplaySource(messageText, config, options);

    source.display_source = String(nextDisplaySource || '');
    source.content = source.display_source || messageText;
    return source.display_source;
}


function looksLikeFullPageChatApp(messageText) {
    return scoreFullPageAppHtml(messageText).score >= 8;
}


function buildChatAppCompatContext(rawMessages, floor, rawMessage, parsedMessage, activeChat) {
    const source = rawMessage && typeof rawMessage === 'object' ? rawMessage : {};
    const parsed = parsedMessage && typeof parsedMessage === 'object' ? parsedMessage : {};
    const chat = activeChat && typeof activeChat === 'object' ? activeChat : {};
    const statData = resolveLatestStatData(rawMessages, floor);

    return {
        latestMessageData: {
            type: 'message',
            stat_data: statData,
            message_id: source.id || parsed.floor || 'latest',
            message_name: parsed.name || source.name || '',
            name: parsed.name || source.name || '',
            mes: source.mes || '',
            extra: cloneValue(source.extra || {}),
            variables: cloneValue(source.variables || []),
            is_user: Boolean(source.is_user),
            is_system: Boolean(source.is_system),
            chat_id: chat.id || '',
        },
        chat: {
            id: chat.id || '',
            title: chat.title || chat.chat_name || '',
            bound_card_id: chat.bound_card_id || '',
            bound_card_name: chat.bound_card_name || chat.character_name || '',
        },
    };
}


function cloneValue(value) {
    if (typeof structuredClone === 'function') {
        try {
            return structuredClone(value);
        } catch (error) {
        }
    }

    try {
        return JSON.parse(JSON.stringify(value));
    } catch (error) {
        return value;
    }
}


function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}


function buildSimpleDiffHtml(beforeText, afterText) {
    const beforeLines = String(beforeText || '').split(/\r?\n/);
    const afterLines = String(afterText || '').split(/\r?\n/);
    const max = Math.max(beforeLines.length, afterLines.length);
    const rows = [];

    for (let index = 0; index < max; index += 1) {
        const before = beforeLines[index] ?? '';
        const after = afterLines[index] ?? '';
        const changed = before !== after;

        rows.push(`
            <div class="chat-diff-row${changed ? ' is-changed' : ''}">
                <div class="chat-diff-cell chat-diff-cell--before"><span class="chat-diff-prefix">-</span><span>${escapeHtml(before) || '&nbsp;'}</span></div>
                <div class="chat-diff-cell chat-diff-cell--after"><span class="chat-diff-prefix">+</span><span>${escapeHtml(after) || '&nbsp;'}</span></div>
            </div>
        `);
    }

    return rows.join('');
}


function escapeRegExp(text) {
    return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}


function replaceTextValue(source, query, replacement, caseSensitive) {
    const input = String(source || '');
    const needle = String(query || '');
    if (!needle) {
        return { text: input, count: 0 };
    }

    if (caseSensitive) {
        const parts = input.split(needle);
        return {
            text: parts.join(replacement),
            count: Math.max(0, parts.length - 1),
        };
    }

    const regex = new RegExp(escapeRegExp(needle), 'gi');
    let count = 0;
    const text = input.replace(regex, () => {
        count += 1;
        return replacement;
    });
    return { text, count };
}


export default function chatGrid() {
    return {
        dragOverChats: false,
        detailOpen: false,
        detailLoading: false,
        activeChat: null,

        detailSearchQuery: '',
        detailSearchResults: [],
        detailSearchIndex: -1,
        detailBookmarkedOnly: false,

        detailDraftName: '',
        detailDraftNotes: '',
        bookmarkDraft: '',
        jumpFloorInput: '',

        replaceQuery: '',
        replaceReplacement: '',
        replaceCaseSensitive: false,
        replaceUseRegex: false,
        replaceStatus: '',

        readerRenderMode: DEFAULT_CHAT_READER_RENDER_PREFS.renderMode,
        readerComponentMode: DEFAULT_CHAT_READER_RENDER_PREFS.componentMode,
        regexConfigOpen: false,
        regexConfigTab: 'extract',
        regexConfigDraft: normalizeRegexConfig(DEFAULT_CHAT_READER_REGEX_CONFIG),
        regexConfigStatus: '',
        regexTestInput: '',
        regexConfigSourceLabel: '',
        activeCardRegexConfig: normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false }),
        readerViewportFloor: 0,
        readerWindowStartFloor: 1,
        readerWindowEndFloor: 0,
        readerViewSettingsOpen: false,
        readerViewSettings: normalizeViewSettings(DEFAULT_CHAT_READER_VIEW_SETTINGS),
        editingFloor: 0,
        editingMessageDraft: '',
        editingMessageRawDraft: '',
        editingMessagePreviewMode: 'parsed',

        linkedCardIdFilter: '',
        linkedCardNameFilter: '',
        pendingOpenChatId: '',

        filePickerMode: 'global',
        filePickerPayload: null,

        readerShowLeftPanel: true,
        readerShowRightPanel: true,
        readerRightTab: 'search',
        readerAppMode: false,
        readerAppFloor: 0,
        readerAppSignature: '',
        readerAppDebug: {
            checkedCount: 0,
            detectedFloor: 0,
            matchedFloors: [],
            status: '未检测',
        },
        readerRuntimeDebug: {
            enabled: true,
            floor: 0,
            preCount: 0,
            candidateCount: 0,
            wrappedCount: 0,
            scores: [],
            snippets: [],
            status: '未检测',
        },
        chatAppStage: null,
        readerSegmentRegistry: new WeakMap(),
        readerPartStages: new Map(),
        readerScrollRaf: 0,
        readerScrollIdleTimer: 0,

        bindPickerOpen: false,
        bindPickerLoading: false,
        bindPickerSearch: '',
        bindPickerResults: [],
        bindPickerTargetChatId: '',

        get chatList() { return this.$store.global.chatList; },
        set chatList(val) { this.$store.global.chatList = val; },
        get chatCurrentPage() { return this.$store.global.chatCurrentPage; },
        set chatCurrentPage(val) { this.$store.global.chatCurrentPage = val; },
        get chatTotalItems() { return this.$store.global.chatTotalItems; },
        set chatTotalItems(val) { this.$store.global.chatTotalItems = val; },
        get chatTotalPages() { return this.$store.global.chatTotalPages; },
        set chatTotalPages(val) { this.$store.global.chatTotalPages = val; },
        get chatSearchQuery() { return this.$store.global.chatSearchQuery; },
        set chatSearchQuery(val) { this.$store.global.chatSearchQuery = val; },
        get chatFilterType() { return this.$store.global.chatFilterType; },
        set chatFilterType(val) { this.$store.global.chatFilterType = val; },

        get visibleDetailMessages() {
            if (!this.activeChat || !Array.isArray(this.activeChat.messages)) return [];

            const bookmarksRef = Array.isArray(this.activeChat.bookmarks) ? this.activeChat.bookmarks : null;
            const bookmarks = bookmarksRef || [];
            const bookmarkSet = new Set(bookmarks.map(item => Number(item.floor || 0)).filter(Boolean));
            const total = this.activeChat.messages.length;
            const currentFloor = Number(this.readerViewportFloor || this.activeChat.last_view_floor || total || 1);
            const windowStartFloor = Math.max(1, Number(this.readerWindowStartFloor || 1));
            const windowEndFloor = Math.min(total, Math.max(windowStartFloor, Number(this.readerWindowEndFloor || total)));
            const fullCount = Number(this.readerViewSettings.fullDisplayCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount);
            const renderNearby = Number(this.readerViewSettings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount);
            const simpleRenderRadius = Number(this.readerViewSettings.simpleRenderRadius || DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius);
            const hiddenHistoryThreshold = Number(this.readerViewSettings.hiddenHistoryThreshold || DEFAULT_CHAT_READER_VIEW_SETTINGS.hiddenHistoryThreshold);
            const compactPreviewLength = Number(this.readerViewSettings.compactPreviewLength || DEFAULT_CHAT_READER_VIEW_SETTINGS.compactPreviewLength);
            const lastAlwaysVisibleFloor = Math.max(1, total - fullCount + 1);
            const expansionStartFloor = Math.max(1, currentFloor - renderNearby);
            const expansionEndFloor = Math.min(total, currentFloor + renderNearby);
            const simpleStartFloor = Math.max(1, currentFloor - simpleRenderRadius);
            const simpleEndFloor = Math.min(total, currentFloor + simpleRenderRadius);
            const cache = getReaderVisibleMessagesCache(this);

            if (cache
                && cache.messagesRef === this.activeChat.messages
                && cache.bookmarksRef === bookmarksRef
                && cache.detailBookmarkedOnly === this.detailBookmarkedOnly
                && cache.currentFloor === currentFloor
                && cache.windowStartFloor === windowStartFloor
                && cache.windowEndFloor === windowEndFloor
                && cache.fullCount === fullCount
                && cache.renderNearby === renderNearby
                && cache.simpleRenderRadius === simpleRenderRadius
                && cache.hiddenHistoryThreshold === hiddenHistoryThreshold
                && cache.compactPreviewLength === compactPreviewLength) {
                return cache.result;
            }

            let messages = this.activeChat.messages
                .slice(Math.max(0, windowStartFloor - 1), windowEndFloor)
                .map((message) => ({
                ...message,
                is_bookmarked: bookmarkSet.has(Number(message.floor || 0)),
                compact_preview: '',
                placeholder_preview: '',
                }));

            messages = messages.map((message) => {
                const floor = Number(message.floor || 0);
                const isRecentFloor = floor >= lastAlwaysVisibleFloor;
                const inFullBand = floor >= expansionStartFloor && floor <= expansionEndFloor;
                const inSimpleBand = floor >= simpleStartFloor && floor <= simpleEndFloor;
                const floorDistance = Math.abs(floor - currentFloor);
                const shouldHideHistory = hiddenHistoryThreshold > 0
                    && floor < lastAlwaysVisibleFloor
                    && floorDistance > hiddenHistoryThreshold;

                let renderTier = 'hidden';
                if (isRecentFloor || inFullBand) {
                    renderTier = 'full';
                } else if (inSimpleBand) {
                    renderTier = 'simple';
                } else if (!shouldHideHistory) {
                    renderTier = 'compact';
                }

                return {
                    ...message,
                    compact_preview: buildCompactPreview({
                        ...message,
                        content: message.display_source || message.content || message.mes || '',
                    }, compactPreviewLength),
                    placeholder_preview: buildPlaceholderPreview({
                        ...message,
                        content: message.display_source || message.content || message.mes || '',
                    }),
                    render_tier: renderTier,
                    is_full_display: renderTier !== 'hidden',
                    should_render_full: renderTier === 'full',
                    should_render_simple: renderTier === 'simple',
                    should_render_placeholder: renderTier === 'hidden',
                    is_compact_display: renderTier === 'compact',
                };
            });

            if (this.detailBookmarkedOnly) {
                messages = messages.filter(item => item.is_bookmarked);
            }

            readerVisibleMessagesCacheMap.set(this, {
                messagesRef: this.activeChat.messages,
                bookmarksRef,
                detailBookmarkedOnly: this.detailBookmarkedOnly,
                currentFloor,
                windowStartFloor,
                windowEndFloor,
                fullCount,
                renderNearby,
                simpleRenderRadius,
                hiddenHistoryThreshold,
                compactPreviewLength,
                result: messages,
            });

            return messages;
        },

        get activeRegexConfig() {
            const localDefault = loadStoredRegexConfig();
            const cardDefault = hasCustomRegexConfig(this.activeCardRegexConfig)
                ? this.activeCardRegexConfig
                : EMPTY_CHAT_READER_REGEX_CONFIG;
            const chatOverride = this.activeChat?.metadata?.reader_regex_config || null;
            const localTagged = markRegexConfigRuleSource(localDefault, 'local');
            const cardTagged = markRegexConfigRuleSource(cardDefault, 'card');
            const chatTagged = chatOverride ? markRegexConfigRuleSource(chatOverride, 'chat') : null;
            const mergedBase = mergeRegexConfigs(localTagged, cardTagged);
            return chatTagged ? mergeRegexConfigs(mergedBase, chatTagged) : normalizeRegexConfig(mergedBase);
        },

        get activeReaderAssetBase() {
            const chat = this.activeChat || {};
            const folder = chat.bound_card_resource_folder || chat.resource_folder || '';
            if (!folder) {
                return `${window.location.origin}/`;
            }
            return `${window.location.origin}/resources_file/${encodeURIComponent(folder)}/`;
        },

        get activeAppMessage() {
            if (!this.activeChat || !Array.isArray(this.activeChat.messages) || !this.readerAppFloor) {
                return null;
            }
            return this.activeChat.messages.find(item => Number(item.floor || 0) === Number(this.readerAppFloor || 0)) || null;
        },

        get executableMessageFloors() {
            return getExecutableMessageFloors(this.activeChat, this.renderedFloorHtmlCache, this.readerViewSettings);
        },

        get hasAppFloorNavigation() {
            return this.executableMessageFloors.length > 1;
        },

        get renderedFloorHtmlCache() {
            if (!this._renderedFloorHtmlCache) {
                this._renderedFloorHtmlCache = new Map();
            }
            return this._renderedFloorHtmlCache;
        },

        get runtimeCandidateCache() {
            if (!this.activeChat) {
                return createRuntimeCandidateCache();
            }
            if (!this.activeChat.runtime_candidate_cache) {
                this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
            }
            return this.activeChat.runtime_candidate_cache;
        },

        buildReaderRegexMacroContext(rawMessage = null, floor = 0) {
            const source = rawMessage && typeof rawMessage === 'object' ? rawMessage : {};
            const chat = this.activeChat || {};
            const characterName = chat.bound_card_name || chat.character_name || '';
            const userName = 'User';

            return {
                char: characterName,
                character: characterName,
                name: characterName,
                user: userName,
                persona: userName,
                chat: chat.title || chat.chat_name || '',
                chatname: chat.title || chat.chat_name || '',
                chatid: chat.id || '',
                floor: String(floor || ''),
                messageid: source.id || String(floor || ''),
                mes: String(source.mes || ''),
            };
        },

        ensureMessageDisplaySource(message) {
            if (!message) return '';
            const floor = Number(message.floor || 0);
            const rawMessages = Array.isArray(this.activeChat?.raw_messages) ? this.activeChat.raw_messages : [];
            const rawMessage = floor > 0 ? rawMessages[floor - 1] : null;
            return ensureReaderDisplaySource(message, this.activeRegexConfig, {
                placement: resolveReaderRegexPlacement(rawMessage || message),
                isMarkdown: true,
                macroContext: this.buildReaderRegexMacroContext(rawMessage || message, floor),
                depth: resolveReaderMessageDepth(rawMessages, floor),
            });
        },

        classifyFrontendPreText(text) {
            const source = String(text || '');
            if (!['<html', '<head', '<body', '<!DOCTYPE html'].some(token => source.includes(token))) {
                return null;
            }

            const analysis = scoreFullPageAppHtml(source);
            if (analysis.score >= 8) {
                return {
                    type: 'app-stage',
                    minHeight: 520,
                    maxHeight: 860,
                };
            }

            return {
                type: 'html-component',
                minHeight: 28,
                maxHeight: 520,
            };
        },

        get editingMessageTarget() {
            const targetFloor = Number(this.editingFloor || 0);
            if (!targetFloor || !this.activeChat || !Array.isArray(this.activeChat.messages)) return null;
            return this.activeChat.messages.find(item => Number(item.floor || 0) === targetFloor) || null;
        },

        get editingMessageParsedPreview() {
            if (!this.editingMessageRawDraft) return '';
            return buildReaderDisplaySource(this.editingMessageRawDraft, this.activeRegexConfig, {
                placement: 2,
                isMarkdown: true,
                isEdit: true,
                macroContext: this.buildReaderRegexMacroContext(this.editingMessageTarget || { mes: this.editingMessageRawDraft }, this.editingFloor),
                depth: 0,
            });
        },

        get editingMessageSourcePreview() {
            return this.editingMessageRawDraft || this.editingMessageDraft || '';
        },

        get editingMessageParsedPreviewHtml() {
            const flags = resolveReaderFormatFlags(this.editingMessageTarget || {});
            return formatScopedDisplayedHtml(this.editingMessageParsedPreview, {
                scopeClass: 'st-reader-floor-edit-preview',
                renderMode: this.readerRenderMode,
                speakerName: flags.speakerName,
                stripSpeakerPrefix: flags.stripSpeakerPrefix,
                encodeTags: flags.encodeTags,
                promptBias: flags.promptBias,
                hidePromptBias: flags.hidePromptBias,
                reasoningMarkers: flags.reasoningMarkers,
            });
        },

        get editingMessageSourcePreviewHtml() {
            const flags = resolveReaderFormatFlags(this.editingMessageTarget || {});
            return formatScopedDisplayedHtml(this.editingMessageSourcePreview, {
                scopeClass: 'st-reader-floor-edit-source',
                renderMode: this.readerRenderMode,
                speakerName: flags.speakerName,
                stripSpeakerPrefix: flags.stripSpeakerPrefix,
                encodeTags: flags.encodeTags,
                promptBias: flags.promptBias,
                hidePromptBias: flags.hidePromptBias,
                reasoningMarkers: flags.reasoningMarkers,
            });
        },

        get editingMessageDiffHtml() {
            const original = this.editingMessageTarget?.mes || '';
            const current = this.editingMessageRawDraft || '';
            return buildSimpleDiffHtml(original, current);
        },

        get regexTestPreview() {
            const source = String(this.regexTestInput || '').trim();
            if (!source) {
                return {
                    content: '',
                    display_source: '',
                    thinking: '',
                    summary: '',
                    time_bar: '',
                    choices: [],
                    render_segments: [],
                };
            }

            return buildReaderParsedMessage({
                mes: source,
                name: 'Regex Test',
            }, 1, normalizeRegexConfig(this.regexConfigDraft), {
                chatId: this.activeChat?.id || 'regex-test',
                macroContext: this.buildReaderRegexMacroContext({ mes: source, name: 'Regex Test' }, 1),
                depth: 0,
            });
        },

        get hasChatRegexConfig() {
            return Boolean(this.activeChat?.metadata && Object.prototype.hasOwnProperty.call(this.activeChat.metadata, 'reader_regex_config'));
        },

        get hasBoundCardRegexConfig() {
            return hasCustomRegexConfig(this.activeCardRegexConfig);
        },

        get regexDraftRuleCount() {
            return Array.isArray(this.regexConfigDraft?.displayRules) ? this.regexConfigDraft.displayRules.length : 0;
        },

        get regexRuleSourceSummary() {
            const groups = this.regexDraftDisplayRules.reduce((acc, rule) => {
                const source = rule.source || 'unknown';
                acc[source] = (acc[source] || 0) + 1;
                return acc;
            }, {});

            return Object.entries(groups)
                .sort((a, b) => getRegexRuleSourceMeta(a[0]).order - getRegexRuleSourceMeta(b[0]).order)
                .map(([source, count]) => `${getRegexRuleSourceMeta(source).label} ${count} 条`)
                .join(' · ');
        },

        get regexDraftDisplayRules() {
            const sourceRules = Array.isArray(this.regexConfigDraft?.displayRules) ? this.regexConfigDraft.displayRules : [];
            return sourceRules
                .map((rule, index) => {
                    const normalized = normalizeDisplayRule(rule, index);
                    const source = normalized.source || 'draft';
                    const meta = getRegexRuleSourceMeta(source);
                    return {
                        ...normalized,
                        source,
                        sourceLabel: meta.label,
                        sourceTone: meta.tone,
                        sourceOrder: meta.order,
                    };
                })
                .sort((a, b) => {
                    if (a.sourceOrder !== b.sourceOrder) {
                        return a.sourceOrder - b.sourceOrder;
                    }
                    return a.scriptName.localeCompare(b.scriptName, 'zh-CN');
                });
        },

        get regexSourceChain() {
            return [
                {
                    id: 'builtin',
                    title: '内置模板',
                    state: '始终可用',
                    detail: '作为最后兜底，不写入聊天文件，也不依赖浏览器缓存。',
                    tone: 'muted',
                },
                {
                    id: 'local',
                    title: '本地默认',
                    state: '浏览器本地',
                    detail: '通过“保存本地默认”写入 localStorage，只在当前浏览器生效。',
                    tone: 'info',
                },
                {
                    id: 'card',
                    title: '角色卡规则',
                    state: this.hasBoundCardRegexConfig ? '已检测到' : (this.activeChat?.bound_card_id ? '未检测到' : '未绑定角色卡'),
                    detail: this.activeChat?.bound_card_id
                        ? '读取绑定角色卡 `extensions.regex_scripts` / ST 预设 RegexBinding，并覆盖同名解析位。'
                        : '当前聊天没有绑定角色卡，因此不会读取角色卡正则。',
                    tone: this.hasBoundCardRegexConfig ? 'success' : 'muted',
                },
                {
                    id: 'chat',
                    title: '聊天专属',
                    state: this.hasChatRegexConfig ? '当前生效' : '未保存',
                    detail: '“保存聊天规则”会写入当前聊天 JSONL 的 metadata.reader_regex_config，优先级最高。',
                    tone: this.hasChatRegexConfig ? 'accent' : 'muted',
                },
            ];
        },

        get readerVisibleSummary() {
            const messages = this.visibleDetailMessages;
            if (!messages.length) {
                return '暂无楼层';
            }

            const total = Number(this.activeChat?.messages?.length || messages.length || 0);
            const windowStartFloor = Math.max(1, Number(this.readerWindowStartFloor || 1));
            const windowEndFloor = Math.min(total || messages.length, Math.max(windowStartFloor, Number(this.readerWindowEndFloor || messages[messages.length - 1]?.floor || windowStartFloor)));
            const fullVisible = messages.filter(item => item.is_full_display).length;
            const renderedNow = messages.filter(item => item.should_render_full).length;
            const instanceDepth = Number(this.readerViewSettings.instanceRenderDepth ?? DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth);
            const instanceSummary = instanceDepth === 0 ? '全部实例执行' : `最近 ${instanceDepth} 层执行实例`;
            return `当前渲染窗口 #${windowStartFloor}-#${windowEndFloor} / ${total} 层 · 完整显示 ${fullVisible} 层，当前高渲染 ${renderedNow} 层 · ${instanceSummary}`;
        },

        get hasEarlierReaderWindow() {
            return Boolean(this.activeChat && this.readerWindowStartFloor > 1);
        },

        get hasLaterReaderWindow() {
            const total = Number(this.activeChat?.messages?.length || 0);
            return Boolean(this.activeChat && total > 0 && this.readerWindowEndFloor < total);
        },

        get resolvedRegexConfigSourceLabel() {
            return this.regexConfigSourceLabel || this.describeRegexConfigSource();
        },

        get readerBodyGridStyle() {
            const isMobile = this.$store.global.deviceType === 'mobile';
            const left = this.readerShowLeftPanel ? (isMobile ? 1 : 320) : 0;
            const right = this.readerShowRightPanel ? (isMobile ? 1 : 300) : 0;

            if (isMobile) {
                if (!this.readerShowLeftPanel && !this.readerShowRightPanel) {
                    return 'grid-template-columns: minmax(0, 1fr);';
                }
                if (this.readerShowLeftPanel && !this.readerShowRightPanel) {
                    return 'grid-template-columns: minmax(0, 1fr);';
                }
                if (!this.readerShowLeftPanel && this.readerShowRightPanel) {
                    return 'grid-template-columns: minmax(0, 1fr);';
                }
                return 'grid-template-columns: minmax(0, 1fr);';
            }

            return `grid-template-columns: ${left}px minmax(0, 1fr) ${right}px;`;
        },

        init() {
            this.chatAppStage = new ChatAppStage({
                onTriggerSlash: async (command) => {
                    await this.executeAppStageSlash(command);
                },
                onToast: (message, duration) => {
                    this.$store.global.showToast(String(message || ''), Number.isFinite(Number(duration)) ? Number(duration) : 2200);
                },
                onAppError: (error) => {
                    console.error('[ChatAppStage]', error);
                    this.$store.global.showToast(`实例错误: ${error.message}`, 2600);
                },
            });

            this.regexConfigDraft = loadStoredRegexConfig();
            this.readerViewSettings = loadStoredViewSettings();
            const renderPreferences = loadStoredRenderPreferences();
            this.readerRenderMode = renderPreferences.renderMode;
            this.readerComponentMode = renderPreferences.componentMode;
            this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });

            this.$watch('$store.global.chatSearchQuery', () => {
                this.chatCurrentPage = 1;
                this.fetchChats();
            });

            this.$watch('$store.global.chatFilterType', () => {
                this.chatCurrentPage = 1;
                this.fetchChats();
            });

            this.$watch('$store.global.deviceType', (deviceType) => {
                if (!this.detailOpen) return;

                if (deviceType === 'mobile' && this.readerShowLeftPanel && this.readerShowRightPanel) {
                    this.hideReaderPanels();
                    return;
                }

                this.updateReaderLayoutMetrics();
            });

            this.$watch('readerRenderMode', (value) => {
                storeRenderPreferences({
                    renderMode: value,
                    componentMode: this.readerComponentMode,
                });
            });

            this.$watch('readerComponentMode', (value) => {
                storeRenderPreferences({
                    renderMode: this.readerRenderMode,
                    componentMode: value,
                });
            });

            this.$watch('readerAppMode', (enabled) => {
                if (!enabled) {
                    this.readerAppSignature = '';
                    if (this.chatAppStage) {
                        this.chatAppStage.clear();
                    }
                    return;
                }

                this.$nextTick(() => {
                    this.mountChatAppStage();
                    this.syncChatAppStage();
                });
            });

            window.addEventListener('refresh-chat-list', () => {
                this.fetchChats();
            });

            window.addEventListener('settings-loaded', () => {
                if (this.$store.global.currentMode === 'chats') {
                    this.fetchChats();
                }
            });

            window.addEventListener('beforeunload', () => {
                this.clearReaderViewportSync();
                if (this.chatAppStage) {
                    this.chatAppStage.destroy();
                    this.chatAppStage = null;
                }
            });

            window.addEventListener('open-chat-manager', (e) => {
                const detail = e.detail || {};
                this.$store.global.currentMode = 'chats';
                this.linkedCardIdFilter = detail.card_id || '';
                this.linkedCardNameFilter = detail.card_name || '';
                this.pendingOpenChatId = detail.chat_id || '';
                this.chatFilterType = 'all';
                this.chatCurrentPage = 1;
                this.fetchChats();
            });

            window.addEventListener('open-chat-reader', (e) => {
                const detail = e.detail || {};
                if (!detail.chat_id) return;
                this.openChatDetail({ id: detail.chat_id });
            });

            window.addEventListener('open-chat-file-picker', (event) => {
                const detail = event.detail || {};
                this.triggerChatImport(detail);
            });

            window.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                if (this.bindPickerOpen) {
                    this.closeBindPicker();
                    return;
                }
                if (this.detailOpen) {
                    this.closeChatDetail();
                }
            });

            window.addEventListener('resize', () => {
                if (this.detailOpen) {
                    this.updateReaderLayoutMetrics();
                    this.syncReaderViewportFloor();
                }
            });

            window.stUploadChatFiles = (files, payload = {}) => {
                this._uploadChatFiles(files, payload.cardId || '', payload.characterName || '');
            };

            if (this.$store.global.currentMode === 'chats' && this.$store.global.serverStatus.status === 'ready') {
                this.fetchChats();
            }
        },

        fetchChats() {
            if (this.$store.global.serverStatus.status !== 'ready') return;

            this.$store.global.isLoading = true;
            const params = {
                page: this.chatCurrentPage,
                page_size: this.$store.global.settingsForm.items_per_page_wi || 20,
                search: this.chatSearchQuery || '',
                filter: this.chatFilterType || 'all',
            };

            if (this.linkedCardIdFilter) {
                params.card_id = this.linkedCardIdFilter;
            }

            listChats(params)
                .then((res) => {
                    this.$store.global.isLoading = false;
                    if (!res.success) return;

                    this.chatList = res.items || [];
                    this.chatTotalItems = res.total || 0;
                    this.chatTotalPages = Math.max(1, Math.ceil((res.total || 0) / (res.page_size || 1)));

                    if (this.pendingOpenChatId) {
                        const targetId = this.pendingOpenChatId;
                        this.pendingOpenChatId = '';
                        const targetItem = (this.chatList || []).find(item => item.id === targetId);
                        this.openChatDetail(targetItem || { id: targetId, title: targetId });
                    }
                })
                .catch(() => {
                    this.$store.global.isLoading = false;
                });
        },

        changeChatPage(page) {
            if (page < 1 || page > this.chatTotalPages) return;
            this.chatCurrentPage = page;
            const el = document.getElementById('chat-scroll-area');
            if (el) el.scrollTop = 0;
            this.fetchChats();
        },

        async openChatDetail(item) {
            if (!item || !item.id) return;

            this.clearReaderViewportSync();
            this.destroyAllReaderPartStages();
            if (this.chatAppStage) {
                this.chatAppStage.clear({ resetSession: true });
            }
            this.detailOpen = true;
            this.detailLoading = true;
            this.activeChat = null;
            this.detailSearchQuery = '';
            this.detailSearchResults = [];
            this.detailSearchIndex = -1;
            this.detailBookmarkedOnly = false;
            this.bookmarkDraft = '';
            this.jumpFloorInput = '';
            this.replaceQuery = '';
            this.replaceReplacement = '';
            this.replaceUseRegex = false;
            this.replaceStatus = '';
            this.readerRightTab = 'search';
            const renderPreferences = loadStoredRenderPreferences();
            this.readerRenderMode = renderPreferences.renderMode;
            this.readerComponentMode = renderPreferences.componentMode;
            this.regexConfigOpen = false;
            this.regexConfigTab = 'extract';
            this.regexConfigStatus = '';
            this.regexTestInput = '';
            this.regexConfigSourceLabel = '';
            this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
            this.readerViewportFloor = 0;
            this.readerWindowStartFloor = 1;
            this.readerWindowEndFloor = 0;
            this._renderedFloorHtmlCache = new Map();
            if (this.activeChat) {
                this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
            }
            resetReaderVisibleMessagesCache(this);
            this.readerViewSettingsOpen = false;
            this.readerAppMode = false;
            this.readerAppFloor = 0;
            this.readerAppSignature = '';
            this.readerAppDebug = {
                checkedCount: 0,
                detectedFloor: 0,
                matchedFloors: [],
                status: '未检测',
            };
            this.editingFloor = 0;
            this.editingMessageDraft = '';
            this.editingMessageRawDraft = '';
            this.editingMessagePreviewMode = 'parsed';
            this.updateReaderLayoutMetrics();

            const isMobile = this.$store.global.deviceType === 'mobile';
            this.readerShowLeftPanel = !isMobile;
            this.readerShowRightPanel = !isMobile;

            try {
                const res = await getChatDetail(item.id);
                if (!res.success || !res.chat) {
                    alert(res.msg || '读取聊天详情失败');
                    this.detailOpen = false;
                    return;
                }

                this.activeChat = res.chat;
                this.detailDraftName = res.chat.display_name || '';
                this.detailDraftNotes = res.chat.notes || '';
                setActiveRuntimeContext({
                    chat: {
                        id: res.chat?.id || item.id,
                        title: res.chat?.title || res.chat?.chat_name || '',
                        bound_card_id: res.chat?.bound_card_id || '',
                        bound_card_name: res.chat?.bound_card_name || res.chat?.character_name || '',
                        message_count: res.chat?.message_count || 0,
                    },
                });
                await this.loadBoundCardRegexConfig(res.chat);
                if (!this.activeChat.bound_card_resource_folder && this.activeChat.bound_card_id) {
                    this.activeChat.bound_card_resource_folder = this.activeCardRegexConfig?.__meta?.resource_folder || '';
                }
                this.rebuildActiveChatMessages(this.activeRegexConfig);
                this.detectChatAppMode();
                this.regexConfigDraft = normalizeRegexConfig(this.activeRegexConfig);
                this.regexConfigSourceLabel = this.describeRegexConfigSource(res.chat);
                this.readerViewportFloor = Number(res.chat.last_view_floor || res.chat.messages?.length || 1);
                this.setReaderWindowAroundFloor(this.readerViewportFloor || 1, 'center');
                this.$nextTick(() => {
                    this.mountChatAppStage();
                    this.syncChatAppStage();
                    this.updateReaderLayoutMetrics();
                    this.syncReaderViewportFloor();
                    this.scrollToFloor(res.chat.last_view_floor || 1, false);
                });
            } catch (err) {
                alert('读取聊天详情失败: ' + err);
                this.detailOpen = false;
            } finally {
                this.detailLoading = false;
            }
        },

        closeChatDetail() {
            this.clearReaderViewportSync();
            this.destroyAllReaderPartStages();
            if (this.chatAppStage) {
                this.chatAppStage.clear({ resetSession: true });
            }
            this.detailOpen = false;
            this.detailLoading = false;
            this.activeChat = null;
            clearActiveRuntimeContext('chat');
            this.detailSearchQuery = '';
            this.detailSearchResults = [];
            this.detailSearchIndex = -1;
            this.detailBookmarkedOnly = false;
            this.bookmarkDraft = '';
            this.jumpFloorInput = '';
            this.replaceQuery = '';
            this.replaceReplacement = '';
            this.replaceUseRegex = false;
            this.replaceStatus = '';
            this.readerRightTab = 'search';
            const renderPreferences = loadStoredRenderPreferences();
            this.readerRenderMode = renderPreferences.renderMode;
            this.readerComponentMode = renderPreferences.componentMode;
            this.regexConfigOpen = false;
            this.regexConfigTab = 'extract';
            this.regexConfigStatus = '';
            this.regexTestInput = '';
            this.regexConfigSourceLabel = '';
            this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
            this.readerViewportFloor = 0;
            this.readerWindowStartFloor = 1;
            this.readerWindowEndFloor = 0;
            this._renderedFloorHtmlCache = new Map();
            if (this.activeChat) {
                this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
            }
            resetReaderVisibleMessagesCache(this);
            this.readerViewSettingsOpen = false;
            this.readerAppMode = false;
            this.readerAppFloor = 0;
            this.readerAppSignature = '';
            this.readerAppDebug = {
                checkedCount: 0,
                detectedFloor: 0,
                matchedFloors: [],
                status: '未检测',
            };
            this.editingFloor = 0;
            this.editingMessageDraft = '';
            this.editingMessageRawDraft = '';
            this.editingMessagePreviewMode = 'parsed';
        },

        updateReaderLayoutMetrics() {
            this.$nextTick(() => {
                const root = document.querySelector('.chat-reader-overlay--fullscreen');
                if (!root) return;

                const header = root.querySelector('.chat-reader-header');
                const headerHeight = header ? Math.ceil(header.getBoundingClientRect().height) : 76;
                root.style.setProperty('--chat-reader-header-height', `${headerHeight}px`);
            });
        },

        clearReaderViewportSync() {
            if (this.readerScrollRaf) {
                window.cancelAnimationFrame(this.readerScrollRaf);
                this.readerScrollRaf = 0;
            }
            if (this.readerScrollIdleTimer) {
                window.clearTimeout(this.readerScrollIdleTimer);
                this.readerScrollIdleTimer = 0;
            }
        },

        destroyAllReaderPartStages() {
            if (!(this.readerPartStages instanceof Map) || this.readerPartStages.size === 0) {
                this.readerPartStages = new Map();
                return;
            }

            this.readerPartStages.forEach((stage, host) => {
                try {
                    if (stage && typeof stage.destroy === 'function') {
                        stage.destroy();
                    }
                } catch (error) {
                    console.warn('[ChatReader] destroy inline app stage failed', error);
                }

                if (host instanceof Element) {
                    setRuntimeWrapperActive(host, false);
                }
            });

            this.readerPartStages = new Map();
        },

        resolveReaderWindowBounds(floor = 1, mode = 'center') {
            const total = Number(this.activeChat?.messages?.length || 0);
            if (!total) {
                return { start: 1, end: 0 };
            }

            const size = Math.min(total, CHAT_READER_WINDOW_SIZE);
            const maxStart = Math.max(1, total - size + 1);
            const targetFloor = Math.min(total, Math.max(1, Number(floor || 1)));
            let start;

            if (mode === 'start') {
                start = targetFloor;
            } else if (mode === 'end') {
                start = targetFloor - size + 1;
            } else {
                start = targetFloor - Math.floor(size / 2);
            }

            start = Math.max(1, Math.min(maxStart, start));
            return {
                start,
                end: Math.min(total, start + size - 1),
            };
        },

        extendReaderWindow(direction = 'backward', anchorFloor = 0) {
            const total = Number(this.activeChat?.messages?.length || 0);
            if (!total) return { start: 1, end: 0 };

            const currentStart = Math.max(1, Number(this.readerWindowStartFloor || 1));
            const currentEnd = Math.max(currentStart, Number(this.readerWindowEndFloor || currentStart));
            let nextStart = currentStart;
            let nextEnd = currentEnd;

            if (direction === 'backward') {
                nextStart = Math.max(1, currentStart - CHAT_READER_WINDOW_STEP);
            } else if (direction === 'forward') {
                nextEnd = Math.min(total, currentEnd + CHAT_READER_WINDOW_STEP);
            } else {
                const bounds = this.resolveReaderWindowBounds(anchorFloor || currentEnd || total, 'center');
                nextStart = bounds.start;
                nextEnd = bounds.end;
            }

            if (nextStart === currentStart && nextEnd === currentEnd) {
                return { start: currentStart, end: currentEnd };
            }

            this.readerWindowStartFloor = nextStart;
            this.readerWindowEndFloor = nextEnd;
            resetReaderVisibleMessagesCache(this);
            return { start: nextStart, end: nextEnd };
        },

        setReaderWindowAroundFloor(floor = 1, mode = 'center') {
            const bounds = this.resolveReaderWindowBounds(floor, mode);
            this.readerWindowStartFloor = bounds.start;
            this.readerWindowEndFloor = bounds.end;
            resetReaderVisibleMessagesCache(this);
            return bounds;
        },

        ensureReaderWindowForFloor(floor = 1, mode = 'center') {
            const targetFloor = Number(floor || 0);
            if (!targetFloor) return false;

            const currentStart = Number(this.readerWindowStartFloor || 1);
            const currentEnd = Number(this.readerWindowEndFloor || 0);
            if (targetFloor >= currentStart && targetFloor <= currentEnd) {
                return false;
            }

            const total = Number(this.activeChat?.messages?.length || 0);
            if (total > 0) {
                if (targetFloor < currentStart) {
                    while (targetFloor < Number(this.readerWindowStartFloor || 1) && Number(this.readerWindowStartFloor || 1) > 1) {
                        this.extendReaderWindow('backward', targetFloor);
                    }
                    if (targetFloor >= Number(this.readerWindowStartFloor || 1) && targetFloor <= Number(this.readerWindowEndFloor || 0)) {
                        return true;
                    }
                }

                if (targetFloor > currentEnd) {
                    while (targetFloor > Number(this.readerWindowEndFloor || 0) && Number(this.readerWindowEndFloor || 0) < total) {
                        this.extendReaderWindow('forward', targetFloor);
                    }
                    if (targetFloor >= Number(this.readerWindowStartFloor || 1) && targetFloor <= Number(this.readerWindowEndFloor || 0)) {
                        return true;
                    }
                }
            }

            this.setReaderWindowAroundFloor(targetFloor, mode);
            return true;
        },

        loadPreviousReaderWindow() {
            if (!this.hasEarlierReaderWindow) return;

            const previousStart = Number(this.readerWindowStartFloor || 1);
            this.extendReaderWindow('backward', previousStart);
            this.$nextTick(() => this.scrollToFloor(previousStart, false, 'auto'));
        },

        loadNextReaderWindow() {
            if (!this.hasLaterReaderWindow) return;

            const previousEnd = Number(this.readerWindowEndFloor || 0);
            this.extendReaderWindow('forward', previousEnd);
            this.$nextTick(() => this.scrollToFloor(previousEnd, false, 'auto'));
        },

        resolveReaderViewportFloor(container) {
            if (!container) return 0;

            const containerRect = container.getBoundingClientRect();
            if (!containerRect.width || !containerRect.height) return 0;

            const sampleX = Math.min(containerRect.right - 24, Math.max(containerRect.left + 24, containerRect.left + containerRect.width * 0.5));
            const sampleRatios = [0.42, 0.28, 0.6];

            for (const ratio of sampleRatios) {
                const sampleY = Math.min(containerRect.bottom - 24, Math.max(containerRect.top + 24, containerRect.top + containerRect.height * ratio));
                const target = document.elementFromPoint(sampleX, sampleY);
                const card = findFloorCardFromNode(target);
                const floor = Number(card?.getAttribute('data-chat-floor') || 0);
                if (floor > 0) {
                    return floor;
                }
            }

            const cards = Array.from(container.querySelectorAll('[data-chat-floor]'));
            if (!cards.length) return 0;

            const viewportTop = containerRect.top;
            const viewportBottom = containerRect.bottom;
            const viewportCenter = containerRect.top + containerRect.height * 0.42;
            let bestFloor = 0;
            let bestDistance = Infinity;

            cards.forEach((card) => {
                const rect = card.getBoundingClientRect();
                if (rect.bottom < viewportTop || rect.top > viewportBottom) {
                    return;
                }

                const center = rect.top + rect.height / 2;
                const distance = Math.abs(center - viewportCenter);
                if (distance < bestDistance) {
                    bestDistance = distance;
                    bestFloor = Number(card.getAttribute('data-chat-floor') || 0);
                }
            });

            if (bestFloor > 0) {
                return bestFloor;
            }

            const firstVisible = cards.find((card) => card.getBoundingClientRect().bottom >= viewportTop);
            return Number(firstVisible?.getAttribute('data-chat-floor') || 0);
        },

        syncReaderViewportFloor(options = {}) {
            const run = () => {
                const root = document.querySelector('.chat-reader-overlay--fullscreen');
                const container = root ? root.querySelector('.chat-reader-center') : null;
                if (!container) return;

                const nextFloor = this.resolveReaderViewportFloor(container);
                if (!nextFloor) return;

                const currentFloor = Number(this.readerViewportFloor || 0);
                const renderNearby = Number(this.readerViewSettings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount);
                const shouldForce = options.force !== false;

                if (!shouldForce && currentFloor && Math.abs(nextFloor - currentFloor) < Math.max(1, renderNearby)) {
                    return;
                }

                if (nextFloor !== currentFloor) {
                    this.readerViewportFloor = nextFloor;
                    this.ensureReaderWindowForFloor(nextFloor, 'center');
                }
            };

            if (options.nextTick === false) {
                run();
                return;
            }

            this.$nextTick(run);
        },

        scheduleReaderViewportSync() {
            if (!this.detailOpen || this.readerAppMode) return;

            if (!this.readerScrollRaf) {
                this.readerScrollRaf = window.requestAnimationFrame(() => {
                    this.readerScrollRaf = 0;
                    this.syncReaderViewportFloor({ force: false, nextTick: false });
                });
            }

            if (this.readerScrollIdleTimer) {
                window.clearTimeout(this.readerScrollIdleTimer);
            }

            this.readerScrollIdleTimer = window.setTimeout(() => {
                this.readerScrollIdleTimer = 0;
                this.syncReaderViewportFloor({ force: true, nextTick: false });
            }, 120);
        },

        handleReaderScroll() {
            this.scheduleReaderViewportSync();
        },

        saveReaderViewSettings() {
            this.readerViewSettings = normalizeViewSettings(this.readerViewSettings);
            storeViewSettings(this.readerViewSettings);
            this.readerViewSettingsOpen = false;
            this.syncReaderViewportFloor();
            this.$store.global.showToast('阅读视图设置已保存', 1500);
        },

        resetReaderViewSettings() {
            this.readerViewSettings = normalizeViewSettings(DEFAULT_CHAT_READER_VIEW_SETTINGS);
            storeViewSettings(this.readerViewSettings);
            this.syncReaderViewportFloor();
        },

        toggleReaderPanel(side) {
            if (this.readerAppMode && side === 'right') {
                this.readerShowRightPanel = !this.readerShowRightPanel;
                this.updateReaderLayoutMetrics();
                return;
            }

            const isMobile = this.$store.global.deviceType === 'mobile';

            if (side === 'left') {
                const next = !this.readerShowLeftPanel;
                this.readerShowLeftPanel = next;
                if (isMobile && next) {
                    this.readerShowRightPanel = false;
                }
                this.updateReaderLayoutMetrics();
                return;
            }

            if (side === 'right') {
                const next = !this.readerShowRightPanel;
                this.readerShowRightPanel = next;
                if (isMobile && next) {
                    this.readerShowLeftPanel = false;
                }
                this.updateReaderLayoutMetrics();
            }
        },

        hideReaderPanels() {
            this.readerShowLeftPanel = false;
            this.readerShowRightPanel = false;
            this.updateReaderLayoutMetrics();
        },

        formatChatDate(ts) {
            const output = formatDate(ts);
            return output || '-';
        },

        formatDate(ts) {
            return this.formatChatDate(ts);
        },

        floorToneClass(floor) {
            const num = Number(floor || 0);
            if (num >= 1000) return 'chat-card-floor-extreme';
            if (num >= 500) return 'chat-card-floor-high';
            if (num >= 100) return 'chat-card-floor-mid';
            return 'chat-card-floor-low';
        },

        messageBadgeClass(message) {
            if (message.is_user) return 'is-user';
            if (message.is_system) return 'is-system';
            return 'is-assistant';
        },

        clearLinkedCardFilter() {
            this.linkedCardIdFilter = '';
            this.linkedCardNameFilter = '';
            this.chatCurrentPage = 1;
            this.fetchChats();
        },

        async reloadActiveChat() {
            if (!this.activeChat || !this.activeChat.id) return;
            const res = await getChatDetail(this.activeChat.id);
            if (!res.success || !res.chat) return;
            this.activeChat = res.chat;
            this.detailDraftName = res.chat.display_name || '';
            this.detailDraftNotes = res.chat.notes || '';
            await this.loadBoundCardRegexConfig(res.chat);
            this.rebuildActiveChatMessages(this.activeRegexConfig);
            this.detectChatAppMode();
            this.regexConfigDraft = normalizeRegexConfig(this.activeRegexConfig);
            this.regexConfigSourceLabel = this.describeRegexConfigSource(res.chat);
            this.$nextTick(() => {
                this.mountChatAppStage();
                this.syncChatAppStage();
            });
        },

        describeRegexConfigSource(chat = null) {
            const target = chat || this.activeChat;
            if (target?.metadata?.reader_regex_config) return '当前聊天专属规则';
            if (target?.bound_card_id && hasCustomRegexConfig(this.activeCardRegexConfig)) return '已绑定角色卡规则';
            if (target?.bound_card_id) return '已绑定角色卡，未检测到正则配置';
            return '本地默认规则';
        },

        async loadBoundCardRegexConfig(chat = null) {
            const target = chat || this.activeChat;
            if (!target?.bound_card_id) {
                this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
                if (target && typeof target === 'object') {
                    target.bound_card_resource_folder = '';
                }
                return;
            }

            try {
                const detail = await getCardDetail(target.bound_card_id, { preview_wi: false });
                if (!detail?.success) {
                    this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
                    if (target && typeof target === 'object') {
                        target.bound_card_resource_folder = '';
                    }
                    return;
                }
                this.activeCardRegexConfig = deriveReaderConfigFromCard(detail);
                if (target && typeof target === 'object') {
                    target.bound_card_resource_folder = detail.card?.resource_folder || '';
                }
            } catch {
                this.activeCardRegexConfig = normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, { fillDefaults: false });
                if (target && typeof target === 'object') {
                    target.bound_card_resource_folder = '';
                }
            }
        },

        detectChatAppMode() {
            if (!this.activeChat || !Array.isArray(this.activeChat.raw_messages)) {
                this.readerAppMode = false;
                this.readerAppFloor = 0;
                this.readerAppSignature = '';
                this.readerAppDebug = {
                    checkedCount: 0,
                    detectedFloor: 0,
                    matchedFloors: [],
                    status: '当前聊天没有 raw_messages',
                };
                if (this.chatAppStage) {
                    this.chatAppStage.clear();
                }
                return;
            }

            const matchedFloors = this.executableMessageFloors;
            const currentFloor = Number(this.readerViewportFloor || this.activeChat.last_view_floor || 0);
            const candidateFloor = matchedFloors.find(floor => floor >= currentFloor)
                || matchedFloors[matchedFloors.length - 1]
                || 0;

            if (!candidateFloor) {
                this.readerAppMode = false;
                this.readerAppFloor = 0;
                this.readerAppSignature = '';
                this.readerAppDebug = {
                    checkedCount: this.activeChat.raw_messages.length,
                    detectedFloor: 0,
                    matchedFloors: [],
                    status: `未检测到整页实例（已检查 ${this.activeChat.raw_messages.length} 条消息）`,
                };
                console.info('[ChatAppMode] no candidate detected', {
                    chatId: this.activeChat.id,
                    checkedCount: this.activeChat.raw_messages.length,
                    regexConfig: this.activeRegexConfig,
                });
                if (this.chatAppStage) {
                    this.chatAppStage.clear();
                }
                return;
            }

            this.readerAppFloor = candidateFloor;
            this.readerAppDebug = {
                checkedCount: this.activeChat.raw_messages.length,
                detectedFloor: this.readerAppFloor,
                matchedFloors,
                status: `检测到整页实例，楼层 #${this.readerAppFloor}`,
            };
        },

        mountChatAppStage() {
            if (!this.chatAppStage || !this.$refs.chatAppStageHost) {
                return;
            }
            this.chatAppStage.attachHost(this.$refs.chatAppStageHost);
        },

        buildChatAppStagePayload() {
            if (!this.readerAppMode || !this.activeChat || !Array.isArray(this.activeChat.raw_messages)) {
                return null;
            }

            const floor = Number(this.readerAppFloor || 0);
            if (!floor) {
                return null;
            }

            const rawMessage = this.activeChat.raw_messages[floor - 1];
            const parsedMessage = Array.isArray(this.activeChat.messages)
                ? this.activeChat.messages.find(item => Number(item.floor || 0) === floor)
                : null;

            const parsedMessageForFloor = Array.isArray(this.activeChat.messages)
                ? this.activeChat.messages.find(item => Number(item.floor || 0) === floor)
                : null;
            const selectedPart = this.resolveRenderedRuntimePart(parsedMessageForFloor);

            if (!selectedPart?.text) {
                return null;
            }

            const partAnalysis = scoreFullPageAppHtml(String(selectedPart.text || ''));

            return {
                floor,
                htmlPayload: String(selectedPart.text || ''),
                assetBase: this.activeReaderAssetBase,
                context: buildChatAppCompatContext(this.activeChat.raw_messages, floor, rawMessage, parsedMessageForFloor || parsedMessage, this.activeChat),
                debug: {
                    score: partAnalysis.score,
                    reasons: partAnalysis.reasons,
                },
            };
        },

        setReaderAppFloor(floor) {
            const targetFloor = Number(floor || 0);
            if (!targetFloor) return;

            if (!this.executableMessageFloors.includes(targetFloor)) {
                this.$store.global.showToast(`楼层 #${targetFloor} 没有可执行的前端实例`, 2200);
                return;
            }

            this.readerAppFloor = targetFloor;
            this.readerAppMode = true;
            this.$nextTick(() => {
                this.mountChatAppStage();
                this.syncChatAppStage();
            });
        },

        stepReaderAppFloor(direction = 1) {
            const floors = this.executableMessageFloors;
            if (!floors.length) return;

            const currentIndex = Math.max(0, floors.indexOf(Number(this.readerAppFloor || floors[0])));
            const nextIndex = Math.min(floors.length - 1, Math.max(0, currentIndex + (direction >= 0 ? 1 : -1)));
            this.setReaderAppFloor(floors[nextIndex]);
        },

        syncChatAppStage() {
            if (!this.chatAppStage || !this.readerAppMode) {
                return;
            }

            const payload = this.buildChatAppStagePayload();
            if (!payload) {
                this.readerAppMode = false;
                this.readerAppFloor = 0;
                this.readerAppSignature = '';
                this.chatAppStage.clear();
                return;
            }

            const signature = JSON.stringify({
                floor: payload.floor,
                htmlPayload: payload.htmlPayload,
                assetBase: payload.assetBase,
            });

            if (signature === this.readerAppSignature) {
                return;
            }

            this.readerAppSignature = signature;
            this.chatAppStage.update(payload);
        },

        activateChatAppStage() {
            if (!this.activeChat) return;
            this.detectChatAppMode();
            if (!this.readerAppFloor) {
                this.$store.global.showToast(this.readerAppDebug.status || '当前聊天未检测到整页前端实例', 2200);
                return;
            }

            this.readerAppMode = true;

            const isMobile = this.$store.global.deviceType === 'mobile';
            if (isMobile) {
                this.readerShowLeftPanel = false;
            }

            this.setReaderAppFloor(this.readerAppFloor);
        },

        deactivateChatAppStage() {
            this.readerAppMode = false;
            this.readerAppSignature = '';
            if (this.chatAppStage) {
                this.chatAppStage.clear({ resetSession: true });
            }
            this.$nextTick(() => this.updateReaderLayoutMetrics());
        },

        formatChatAppSendDate() {
            const now = new Date();
            const formatted = now.toLocaleString('en-US', {
                month: 'long',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true,
            });
            return formatted.replace(', ', ' ').replace(' AM', 'am').replace(' PM', 'pm');
        },

        async appendChatAppUserMessage(text) {
            if (!this.activeChat) return false;

            const rawMessages = JSON.parse(JSON.stringify(this.activeChat.raw_messages || []));
            rawMessages.push({
                name: 'User',
                is_user: true,
                is_system: false,
                mes: String(text || ''),
                send_date: this.formatChatAppSendDate(),
                extra: {},
                force_avatar: this.activeChat.force_avatar || '',
            });

            const ok = await this.persistChatContent(rawMessages, '已追加实例交互消息');
            if (ok) {
                this.detectChatAppMode();
                this.$nextTick(() => {
                    this.mountChatAppStage();
                    this.syncChatAppStage();
                });
            }
            return ok;
        },

        async executeAppStageSlash(command) {
            const source = String(command || '').trim();
            if (!source) return;

            const pipeline = source.split('|').map(item => item.trim()).filter(Boolean);
            const sendSegment = pipeline.find(item => /^\/send\s+/i.test(item));
            const triggerSegment = pipeline.find(item => /^\/trigger\b/i.test(item));

            if (!sendSegment) {
                this.$store.global.showToast(`实例请求执行命令: ${source}`, 2200);
                return;
            }

            const message = sendSegment.replace(/^\/send\s+/i, '').trim();
            if (!message) {
                this.$store.global.showToast('实例发送内容为空，已忽略', 1800);
                return;
            }

            const ok = await this.appendChatAppUserMessage(message);
            if (!ok) return;

            if (triggerSegment) {
                this.$store.global.showToast('已追加用户消息，自动触发生成暂未接入', 2200);
            }
        },

        rebuildActiveChatMessages(config = null) {
            if (!this.activeChat) return;

            const nextConfig = normalizeRegexConfig(config || this.activeRegexConfig);
            const rawMessages = Array.isArray(this.activeChat.raw_messages) ? this.activeChat.raw_messages : [];

            this.activeChat.messages = rawMessages.map((item, index) => buildReaderParsedMessage(item, index + 1, nextConfig, {
                chatId: this.activeChat?.id || '',
                macroContext: this.buildReaderRegexMacroContext(item, index + 1),
                depth: resolveReaderMessageDepth(rawMessages, index + 1),
            }));
            this._renderedFloorHtmlCache = new Map();
            this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
            const anchorFloor = Number(this.readerViewportFloor || this.activeChat.last_view_floor || rawMessages.length || 1);
            this.setReaderWindowAroundFloor(anchorFloor, 'center');
            const warmupStart = Math.max(1, anchorFloor - Math.max(
                Number(this.readerViewSettings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount),
                Number(this.readerViewSettings.simpleRenderRadius || DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius),
            ));
            const warmupEnd = Math.min(rawMessages.length, anchorFloor + Math.max(
                Number(this.readerViewSettings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount),
                Number(this.readerViewSettings.simpleRenderRadius || DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius),
                Number(this.readerViewSettings.fullDisplayCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount),
            ));
            this.activeChat.messages.forEach((message) => {
                const floor = Number(message.floor || 0);
                if (floor >= warmupStart && floor <= warmupEnd) {
                    this.ensureMessageDisplaySource(message);
                }
            });
            resetReaderVisibleMessagesCache(this);
        },

        updateRegexDraftField(field, value) {
            this.regexConfigDraft = {
                ...this.regexConfigDraft,
                [field]: value,
            };
        },

        addRegexDisplayRule() {
            const next = Array.isArray(this.regexConfigDraft.displayRules) ? [...this.regexConfigDraft.displayRules] : [];
            next.push(normalizeDisplayRule({ expanded: true, source: 'draft' }, next.length));
            this.regexConfigDraft = {
                ...this.regexConfigDraft,
                displayRules: next,
            };
        },

        updateRegexDisplayRule(index, field, value) {
            const orderedRules = this.regexDraftDisplayRules;
            const target = orderedRules[index];
            if (!target) return;

            const targetKey = buildDisplayRuleKey(target);
            const next = Array.isArray(this.regexConfigDraft.displayRules)
                ? this.regexConfigDraft.displayRules.map((item) => {
                    const currentKey = buildDisplayRuleKey(item);
                    return currentKey === targetKey ? { ...item, [field]: value } : item;
                })
                : [];
            this.regexConfigDraft = {
                ...this.regexConfigDraft,
                displayRules: next,
            };
        },

        toggleRegexRuleExpanded(index) {
            const orderedRules = this.regexDraftDisplayRules;
            const target = orderedRules[index];
            if (!target) return;

            const targetKey = buildDisplayRuleKey(target);
            const next = Array.isArray(this.regexConfigDraft.displayRules)
                ? this.regexConfigDraft.displayRules.map((item) => {
                    const currentKey = buildDisplayRuleKey(item);
                    return currentKey === targetKey ? { ...item, expanded: !item.expanded } : item;
                })
                : [];
            this.regexConfigDraft = {
                ...this.regexConfigDraft,
                displayRules: next,
            };
        },

        removeRegexDisplayRule(index) {
            const orderedRules = this.regexDraftDisplayRules;
            const target = orderedRules[index];
            if (!target) return;

            const targetKey = buildDisplayRuleKey(target);
            const next = Array.isArray(this.regexConfigDraft.displayRules)
                ? this.regexConfigDraft.displayRules.filter((item) => buildDisplayRuleKey(item) !== targetKey)
                : [];
            this.regexConfigDraft = {
                ...this.regexConfigDraft,
                displayRules: next,
            };
        },

        importRegexConfigFile(event) {
            const file = event?.target?.files?.[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = () => {
                try {
                    const data = JSON.parse(String(reader.result || '{}'));
                    const rules = parseSillyTavernRegexRules(data);
                    if (!rules.length) {
                        alert('未在该文件中识别到可用的 SillyTavern 正则规则');
                        return;
                    }

                    this.regexConfigDraft = convertRulesToReaderConfig(rules, this.regexConfigDraft, { fillDefaults: true, source: 'draft' });
                    this.regexConfigStatus = `已导入 ${rules.length} 条规则`;
                    this.previewRegexConfig();
                } catch (err) {
                    alert(`导入规则失败: ${err.message || err}`);
                } finally {
                    event.target.value = '';
                }
            };
            reader.readAsText(file, 'utf-8');
        },

        restoreRegexConfigFromChat() {
            if (!this.activeChat) return;

            const chatConfig = this.activeChat?.metadata?.reader_regex_config;
            if (!chatConfig) {
                this.regexConfigStatus = '当前聊天还没有保存专属规则';
                return;
            }

            this.regexConfigDraft = markRegexConfigRuleSource(chatConfig, 'chat');
            this.regexConfigSourceLabel = '当前聊天专属规则';
            this.regexConfigStatus = '已从当前聊天恢复规则';
            this.previewRegexConfig();
        },

        restoreRegexConfigFromBoundCard() {
            if (!this.activeChat?.bound_card_id) {
                this.regexConfigStatus = '当前聊天未绑定角色卡';
                return;
            }

            if (!hasCustomRegexConfig(this.activeCardRegexConfig)) {
                this.regexConfigStatus = '绑定角色卡中未找到可用的正则配置';
                return;
            }

            this.regexConfigDraft = markRegexConfigRuleSource(this.activeCardRegexConfig, 'card');
            this.regexConfigSourceLabel = '已绑定角色卡规则';
            this.regexConfigStatus = '已从绑定角色卡恢复规则';
            this.previewRegexConfig();
        },

        restoreRegexConfigFromLocalDefault() {
            this.regexConfigDraft = markRegexConfigRuleSource(loadStoredRegexConfig(), 'local');
            this.regexConfigSourceLabel = '本地默认规则';
            this.regexConfigStatus = '已恢复本地默认规则';
            this.previewRegexConfig();
        },

        exportRegexConfigDraft() {
            const payload = normalizeRegexConfig(this.regexConfigDraft);
            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `chat-reader-regex-${Date.now()}.json`;
            link.click();
            URL.revokeObjectURL(url);
            this.regexConfigStatus = '已导出当前规则';
        },

        resetRegexConfigDraft() {
            this.regexConfigDraft = markRegexConfigRuleSource(DEFAULT_CHAT_READER_REGEX_CONFIG, 'builtin');
            this.regexConfigSourceLabel = '内置默认模板';
            this.regexConfigStatus = '已恢复默认解析规则';
        },

        openRegexConfig() {
            this.regexConfigDraft = markRegexConfigRuleSource(this.activeRegexConfig, 'draft');
            this.regexTestInput = this.activeChat?.raw_messages?.[0]?.mes || '';
            this.regexConfigOpen = true;
            this.regexConfigTab = 'extract';
            this.regexConfigSourceLabel = this.describeRegexConfigSource();
            this.regexConfigStatus = '';
        },

        closeRegexConfig() {
            this.rebuildActiveChatMessages(this.activeRegexConfig);
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
            this.regexConfigOpen = false;
            this.regexConfigStatus = '';
            this.regexConfigSourceLabel = this.describeRegexConfigSource();
        },

        previewRegexConfig() {
            this.rebuildActiveChatMessages(this.regexConfigDraft);
            this.regexConfigStatus = '已预览当前规则';
            this.regexConfigSourceLabel = '当前预览草稿';
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        async saveRegexConfig() {
            if (!this.activeChat) return;

            const nextConfig = normalizeRegexConfig(this.regexConfigDraft);
            const metadata = {
                ...ensureChatMetadataShape(this.activeChat.metadata),
                reader_regex_config: nextConfig,
            };

            const ok = await this.persistChatContent(
                JSON.parse(JSON.stringify(this.activeChat.raw_messages || [])),
                '聊天解析规则已保存',
                metadata,
            );
            if (!ok) return;

            this.regexConfigDraft = nextConfig;
            this.rebuildActiveChatMessages(nextConfig);
            this.regexConfigOpen = false;
            this.regexConfigStatus = '';
            this.regexConfigSourceLabel = '当前聊天专属规则';
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        saveRegexConfigAsLocalDefault() {
            const nextConfig = normalizeRegexConfig(this.regexConfigDraft);
            storeRegexConfig(nextConfig);
            this.regexConfigStatus = '已保存为本地默认规则';
            this.regexConfigSourceLabel = '本地默认规则';
            this.rebuildActiveChatMessages(this.activeRegexConfig);
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        async clearRegexConfigFromChat() {
            if (!this.activeChat) return;

            if (!this.hasChatRegexConfig) {
                this.regexConfigStatus = '当前聊天没有专属规则';
                return;
            }

            const metadata = { ...ensureChatMetadataShape(this.activeChat.metadata) };
            delete metadata.reader_regex_config;

            const ok = await this.persistChatContent(
                JSON.parse(JSON.stringify(this.activeChat.raw_messages || [])),
                '已清除当前聊天专属规则',
                metadata,
            );
            if (!ok) return;

            this.regexConfigDraft = normalizeRegexConfig(this.activeRegexConfig);
            this.regexConfigSourceLabel = this.describeRegexConfigSource();
            this.regexConfigStatus = '当前聊天已恢复继承角色卡 / 本地默认规则';
            this.rebuildActiveChatMessages(this.activeRegexConfig);
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        renderReaderContent(text) {
            const source = String(text || '').trim();
            if (!source) {
                return '<span class="chat-render-empty">空内容</span>';
            }

            if (this.readerRenderMode === 'markdown') {
                return renderMarkdown(source);
            }

            return `<div>${escapeHtml(source).replace(/\n/g, '<br>')}</div>`;
        },

        renderMessageDisplayHtml(message) {
            const source = String(this.ensureMessageDisplaySource(message) || message?.content || '');
            const scopeClass = `st-reader-floor-${Number(message?.floor || 0) || 0}`;
            const flags = resolveReaderFormatFlags(message);
            const html = formatScopedDisplayedHtml(source, {
                scopeClass,
                renderMode: this.readerRenderMode,
                speakerName: flags.speakerName,
                stripSpeakerPrefix: flags.stripSpeakerPrefix,
                encodeTags: flags.encodeTags,
                promptBias: flags.promptBias,
                hidePromptBias: flags.hidePromptBias,
                reasoningMarkers: flags.reasoningMarkers,
            });
            const floor = Number(message?.floor || 0);

            if (floor > 0) {
                const previousHtml = String(this.renderedFloorHtmlCache.get(floor) || message?.rendered_display_html || '');
                if (previousHtml !== html) {
                    const cacheKey = buildReaderCacheScopeKey(this.activeChat, floor, message);
                    this.renderedFloorHtmlCache.set(floor, html);
                    if (message && typeof message === 'object') {
                        message.rendered_display_html = html;
                    }
                    if (Array.isArray(this.activeChat?.messages)) {
                        const originalMessage = this.activeChat.messages.find(item => Number(item?.floor || 0) === floor);
                        if (originalMessage && originalMessage !== message) {
                            originalMessage.rendered_display_html = html;
                        }
                    }
                    this.runtimeCandidateCache.floorMap.delete(cacheKey);
                    this.runtimeCandidateCache.executableFloorsKey = '';
                }
            }
            return html;
        },

        renderMessageSimpleHtml(message) {
            const source = String(this.ensureMessageDisplaySource(message) || message?.content || message?.mes || '');
            if (!source.trim()) {
                return '<div class="chat-message-content chat-message-content--compact">空内容</div>';
            }

            return renderMarkdown(source);
        },

        syncMessageDisplay(el, message, variant = 'full') {
            if (!(el instanceof Element) || !message) return;
            if (!this.detailOpen || !this.activeChat) return;

            const floor = Number(message?.floor || 0);
            const chatId = resolveReaderMessageChatId(message, this.activeChat);
            const html = variant === 'simple'
                ? this.renderMessageSimpleHtml(message)
                : this.renderMessageDisplayHtml(message);
            const signature = JSON.stringify({
                chatId,
                floor,
                variant,
                renderMode: this.readerRenderMode,
                componentMode: variant === 'full' ? this.readerComponentMode : false,
                html,
            });

            if (el.__stmReaderDisplaySignature !== signature) {
                this.destroyMessageRenderPart(el);
                el.innerHTML = html;
                el.__stmReaderDisplaySignature = signature;
                el.__stmReaderDisplayVariant = variant;
            }

            if (variant === 'full') {
                this.mountMessageDisplayNow(el, message);
            }
        },

        shouldRenderMessageAsApp(message) {
            if (!message) return false;
            if (String(message.render_tier || '') !== 'full') return false;
            return this.readerComponentMode
                && shouldExecuteMessageSegments(message, this.activeChat, this.readerViewSettings, this.renderedFloorHtmlCache);
        },

        resolveRenderedRuntimePart(message) {
            if (!message) return null;

            const floor = Number(message.floor || 0);
            const scopedFloorKey = buildReaderCacheScopeKey(this.activeChat, floor, message);
            const cacheKey = floor > 0
                ? `${floor}:${String(message.rendered_display_html || this.renderedFloorHtmlCache.get(floor) || '')}`
                : `preview:${String(message.rendered_display_html || '')}`;
            const cacheEntry = floor > 0 ? this.runtimeCandidateCache.floorMap.get(scopedFloorKey) : null;
            if (cacheEntry && cacheEntry.key === cacheKey) {
                return cacheEntry.part;
            }

            const renderedHtml = floor > 0
                ? this.renderedFloorHtmlCache.get(floor) || message.rendered_display_html || ''
                : message.rendered_display_html || '';
            const candidates = extractRuntimeCandidatesFromRenderedHtml(renderedHtml);
            const part = candidates.length
                ? candidates
                    .slice()
                    .sort((left, right) => Number(right.score || 0) - Number(left.score || 0) || String(right.text || '').length - String(left.text || '').length)[0]
                : null;

            if (floor > 0) {
                this.runtimeCandidateCache.floorMap.set(scopedFloorKey, {
                    key: cacheKey,
                    part,
                });
            }

            return part;
        },

        resolveRenderedRuntimeCandidates(message) {
            if (!message) return [];

            const floor = Number(message.floor || 0);
            const renderedHtml = floor > 0
                ? this.renderedFloorHtmlCache.get(floor) || message.rendered_display_html || ''
                : message.rendered_display_html || '';
            return extractRuntimeCandidatesFromRenderedHtml(renderedHtml);
        },

        wrapRenderedRuntimeHosts(el, message) {
            if (!(el instanceof Element) || !message || !this.readerComponentMode) {
                return [];
            }
            return wrapRuntimeHostsInContainer(el, Number(message.floor || 0));
        },

        updateReaderRuntimeDebug(message, element, candidates = [], wrappedHosts = []) {
            const floor = Number(message?.floor || 0);
            const preCount = element instanceof Element ? element.querySelectorAll('pre').length : 0;
            this.readerRuntimeDebug = {
                enabled: true,
                floor,
                preCount,
                candidateCount: candidates.length,
                wrappedCount: wrappedHosts.length,
                scores: candidates.map(candidate => Number(candidate.score || 0)),
                snippets: candidates.slice(0, 4).map((candidate) => {
                    const text = String(candidate.text || '').replace(/\s+/g, ' ').trim();
                    return text.slice(0, 120);
                }),
                status: candidates.length
                    ? `楼层 #${floor} 检测到 ${candidates.length} 个实例候选`
                    : `楼层 #${floor} 未检测到实例候选`,
            };
            window.__STM_RUNTIME_DEBUG__ = {
                floor,
                preCount,
                candidateCount: candidates.length,
                wrappedCount: wrappedHosts.length,
                scores: this.readerRuntimeDebug.scores,
                snippets: this.readerRuntimeDebug.snippets,
            };

            if (this.readerRuntimeDebug.enabled) {
                console.info('[STM runtime debug]', {
                    floor,
                    preCount,
                    candidateCount: candidates.length,
                    wrappedCount: wrappedHosts.length,
                    scores: this.readerRuntimeDebug.scores,
                    snippets: this.readerRuntimeDebug.snippets,
                });
            }
        },

        mountMessageDisplay(el, message) {
            if (!el || !message) return;

            this.$nextTick(() => {
                if (!el || !el.isConnected) return;
                this.mountMessageDisplayNow(el, message);
            });
        },

        mountMessageDisplayNow(el, message) {
            if (!el || !message) return;
            if (!this.detailOpen || !this.activeChat) return;
            if (resolveReaderMessageChatId(message, this.activeChat) !== String(this.activeChat?.id || '')) return;

            const floor = Number(message.floor || 0);
            const chatId = resolveReaderMessageChatId(message, this.activeChat);
            const allowExecutableHtml = this.shouldRenderMessageAsApp(message);
            const wrappedHosts = this.wrapRenderedRuntimeHosts(el, message);
            const candidates = extractRuntimeCandidatesFromContainer(el);
            this.updateReaderRuntimeDebug(message, el, candidates, wrappedHosts);
            const candidateSignature = buildRuntimeCandidateSignature(candidates);

            const current = this.readerSegmentRegistry.get(el);
            const needsRuntimeAttach = allowExecutableHtml && wrappedHosts.some((host) => !(host instanceof Element) || !host.querySelector('iframe'));
            const needsPlaceholderRender = !allowExecutableHtml && wrappedHosts.some((host) => !(host instanceof Element) || !String(host.innerHTML || '').trim());
            const signature = JSON.stringify({
                chatId,
                floor,
                displaySource: String(message.display_source || message.content || ''),
                candidateSignature,
                appEnabled: allowExecutableHtml,
                renderMode: this.readerRenderMode,
            });

            if (current?.signature === signature && !needsRuntimeAttach && !needsPlaceholderRender) {
                return;
            }

            this.destroyMessageRenderPart(el);
            if (!this.readerComponentMode || !candidates.length) {
                this.readerSegmentRegistry.set(el, { signature, children: [el] });
                return;
            }

            if (!allowExecutableHtml) {
                wrappedHosts.forEach((host) => {
                    if (host instanceof Element) {
                        setRuntimeWrapperActive(host, false);
                        host.innerHTML = this.renderReaderContent(buildDeferredInstancePlaceholder(message, this.readerViewSettings));
                    }
                });
                this.readerSegmentRegistry.set(el, { signature, children: [el] });
                return;
            }

            const rawMessage = floor > 0 && Array.isArray(this.activeChat?.raw_messages)
                ? this.activeChat.raw_messages[floor - 1]
                : { mes: String(message?.mes || message?.content || ''), name: message?.name || 'Preview' };

            candidates.forEach((candidate, index) => {
                const runtimeHost = wrappedHosts[index] || el.querySelector(`#${buildRuntimeHostId(floor || 0, index)}`);
                if (!(runtimeHost instanceof Element)) {
                    return;
                }

                setRuntimeWrapperActive(runtimeHost, true);

                let stage = this.readerPartStages.get(runtimeHost);
                if (!stage) {
                    stage = new ChatAppStage({
                        onTriggerSlash: async (command) => {
                            await this.executeAppStageSlash(command);
                        },
                        onToast: (message, duration) => {
                            this.$store.global.showToast(String(message || ''), Number.isFinite(Number(duration)) ? Number(duration) : 2200);
                        },
                        onAppError: (error) => {
                            console.error('[ChatMessageAppStage]', error);
                            this.$store.global.showToast(`实例错误: ${error.message}`, 2600);
                        },
                    });
                    this.readerPartStages.set(runtimeHost, stage);
                }

                stage.attachHost(runtimeHost);
                stage.update({
                    htmlPayload: String(candidate.text || ''),
                    assetBase: this.activeReaderAssetBase,
                    context: buildChatAppCompatContext(
                        this.activeChat?.raw_messages || [],
                        floor || 1,
                        rawMessage,
                        message,
                        this.activeChat,
                    ),
                });
            });

            this.readerSegmentRegistry.set(el, { signature, children: [el] });
        },

        destroyMessageRenderPart(el) {
            if (!el) return;

            const hosts = [el, ...Array.from(el.querySelectorAll('.chat-inline-runtime-host'))];
            hosts.forEach((host) => {
                const stage = this.readerPartStages.get(host);
                if (stage) {
                    stage.destroy();
                    this.readerPartStages.delete(host);
                }
                if (host instanceof Element) {
                    setRuntimeWrapperActive(host, false);
                }
            });

            clearInlineIsolatedHtml(el, { clearShadow: true });
            this.readerSegmentRegistry.delete(el);
        },

        mountReaderRender(el, text) {
            if (!el) return;

            const source = String(text || '');
            updateInlineRenderContent(el, source, {
                mode: this.readerRenderMode === 'markdown' ? 'markdown' : 'plain',
                isolated: true,
                emptyHtml: '<span class="chat-render-empty">空内容</span>',
            });
        },

        readerMessageRole(message) {
            if (!message) return 'Assistant';
            if (message.is_system) return 'System';
            if (message.is_user) return 'User';
            return 'Assistant';
        },

        openFloorEditor(message) {
            if (!this.activeChat || !message) return;
            const floor = Number(message.floor || 0);
            if (!floor) return;

            this.editingFloor = floor;
            this.editingMessageDraft = String(message.content || message.mes || '');
            this.editingMessageRawDraft = String(message.mes || '');
            this.editingMessagePreviewMode = 'parsed';
        },

        closeFloorEditor() {
            this.editingFloor = 0;
            this.editingMessageDraft = '';
            this.editingMessageRawDraft = '';
            this.editingMessagePreviewMode = 'parsed';
        },

        applyEditedContentToRaw() {
            this.editingMessageRawDraft = this.editingMessageDraft;
        },

        async saveFloorEdit() {
            if (!this.activeChat || !this.editingFloor) return;

            const floorIndex = Number(this.editingFloor) - 1;
            const rawMessages = JSON.parse(JSON.stringify(this.activeChat.raw_messages || []));
            const target = rawMessages[floorIndex];
            if (!target || typeof target !== 'object') return;

            target.mes = String(this.editingMessageRawDraft || '');

            const ok = await this.persistChatContent(rawMessages, `已保存 #${this.editingFloor} 楼层`);
            if (!ok) return;

            this.closeFloorEditor();
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        extractDisplayContent(messageText) {
            return buildReaderDisplaySource(messageText, this.activeRegexConfig, {
                placement: 2,
                isMarkdown: true,
                macroContext: this.buildReaderRegexMacroContext(this.editingMessageTarget || { mes: messageText }, this.editingFloor),
                depth: 0,
            });
        },

        async toggleFavorite(item) {
            if (!item || !item.id) return;

            const next = !item.favorite;
            item.favorite = next;

            try {
                const res = await updateChatMeta({ id: item.id, favorite: next });
                if (!res.success || !res.chat) {
                    item.favorite = !next;
                    alert(res.msg || '收藏状态更新失败');
                    return;
                }

                Object.assign(item, res.chat);
                if (this.activeChat && this.activeChat.id === item.id) {
                    this.activeChat.favorite = res.chat.favorite;
                }
                window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
            } catch (err) {
                item.favorite = !next;
                alert('收藏状态更新失败: ' + err);
            }
        },

        async saveChatMeta() {
            if (!this.activeChat) return;

            const payload = {
                id: this.activeChat.id,
                display_name: this.detailDraftName,
                notes: this.detailDraftNotes,
                last_view_floor: this.activeChat.last_view_floor || 0,
                bookmarks: this.activeChat.bookmarks || [],
                favorite: this.activeChat.favorite || false,
            };

            try {
                const res = await updateChatMeta(payload);
                if (!res.success || !res.chat) {
                    alert(res.msg || '保存失败');
                    return;
                }

                this.activeChat = {
                    ...this.activeChat,
                    ...res.chat,
                    messages: this.activeChat.messages,
                    raw_messages: this.activeChat.raw_messages,
                    metadata: this.activeChat.metadata,
                };

                const index = this.chatList.findIndex(item => item.id === res.chat.id);
                if (index > -1) {
                    this.chatList.splice(index, 1, {
                        ...this.chatList[index],
                        ...res.chat,
                    });
                }

                window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
                this.$store.global.showToast('聊天本地信息已保存', 1500);
            } catch (err) {
                alert('保存聊天信息失败: ' + err);
            }
        },

        async deleteChat(item) {
            if (!item || !item.id) return;
            if (!confirm(`确定将聊天记录 "${item.title || item.chat_name}" 移至回收站吗？`)) return;

            try {
                const res = await deleteChat(item.id);
                if (!res.success) {
                    alert(res.msg || '删除失败');
                    return;
                }

                this.chatList = this.chatList.filter(chat => chat.id !== item.id);
                this.chatTotalItems = Math.max(0, this.chatTotalItems - 1);
                if (this.activeChat && this.activeChat.id === item.id) {
                    this.closeChatDetail();
                }
                window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
                this.$store.global.showToast('聊天记录已移至回收站', 1800);
            } catch (err) {
                alert('删除失败: ' + err);
            }
        },

        openChatFolder(item) {
            if (!item || !item.file_path) return;
            openPath({ path: item.file_path, is_file: true }).then((res) => {
                if (!res.success) {
                    alert(res.msg || '打开失败');
                }
            });
        },

        jumpToBoundCard(item) {
            if (!item || !item.bound_card_id) return;
            window.dispatchEvent(new CustomEvent('jump-to-card-wi', { detail: item.bound_card_id }));
            this.closeChatDetail();
        },

        scrollElementToTop(el, behavior = 'smooth') {
            if (!el) return;

            const container = el.closest('.chat-reader-center');
            if (container) {
                const top = Math.max(0, el.offsetTop - container.offsetTop - 12);
                container.scrollTo({ top, behavior });
                return;
            }

            try {
                el.scrollIntoView({ behavior, block: 'start' });
            } catch {
                el.scrollIntoView();
            }
        },

        async openBindPicker(item) {
            const target = item || this.activeChat;
            if (!target || !target.id) return;

            this.bindPickerOpen = true;
            this.bindPickerTargetChatId = target.id;
            this.bindPickerSearch = target.bound_card_name || target.character_name || '';
            await this.fetchBindPickerResults();
        },

        closeBindPicker() {
            this.bindPickerOpen = false;
            this.bindPickerLoading = false;
            this.bindPickerSearch = '';
            this.bindPickerResults = [];
            this.bindPickerTargetChatId = '';
        },

        async fetchBindPickerResults() {
            this.bindPickerLoading = true;
            try {
                const res = await listCards({
                    page: 1,
                    page_size: 60,
                    category: '',
                    tags: '',
                    excluded_tags: '',
                    excluded_categories: '',
                    search: this.bindPickerSearch || '',
                    search_type: 'name',
                    search_scope: 'all_dirs',
                    sort: 'name_asc',
                    recursive: true,
                });

                this.bindPickerResults = Array.isArray(res.cards) ? res.cards : [];
            } catch (err) {
                this.bindPickerResults = [];
            } finally {
                this.bindPickerLoading = false;
            }
        },

        async applyBinding(chatId, cardId = '', unbind = false) {
            if (!chatId) return;

            try {
                const res = await bindChatToCard({
                    id: chatId,
                    card_id: cardId,
                    unbind,
                });

                if (!res.success) {
                    alert(res.msg || '绑定失败');
                    return;
                }

                this.fetchChats();
                window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
                if (this.activeChat && this.activeChat.id === chatId) {
                    await this.reloadActiveChat();
                }
                this.closeBindPicker();
                this.$store.global.showToast(unbind ? '聊天绑定已解除' : '聊天绑定已更新', 1500);
            } catch (err) {
                alert('绑定失败: ' + err);
            }
        },

        async bindCardPick(card) {
            if (!card || !card.id || !this.bindPickerTargetChatId) return;
            await this.applyBinding(this.bindPickerTargetChatId, card.id, false);
        },

        async unbindCurrentChat() {
            if (!this.bindPickerTargetChatId) return;
            await this.applyBinding(this.bindPickerTargetChatId, '', true);
        },

        _uploadChatFiles(files, cardId = '', characterName = '') {
            const fileList = Array.from(files || []).filter(file => file && file.name && file.name.toLowerCase().endsWith('.jsonl'));
            if (fileList.length === 0) {
                alert('请选择 .jsonl 聊天记录文件');
                return;
            }

            const formData = new FormData();
            fileList.forEach(file => formData.append('files', file));
            if (cardId) formData.append('card_id', cardId);
            if (characterName) formData.append('character_name', characterName);

            this.$store.global.isLoading = true;
            importChats(formData)
                .then((res) => {
                    this.$store.global.isLoading = false;
                    if (!res.success && (!res.items || res.items.length === 0)) {
                        alert(res.msg || '聊天导入失败');
                        return;
                    }

                    if (Array.isArray(res.failed) && res.failed.length > 0) {
                        const message = res.failed.map(item => `${item.name}: ${item.msg}`).join('\n');
                        alert(`部分文件导入失败:\n${message}`);
                    }

                    this.$store.global.showToast(`已导入 ${res.imported || 0} 个聊天记录`, 1800);
                    this.fetchChats();
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
                })
                .catch((err) => {
                    this.$store.global.isLoading = false;
                    alert('聊天导入失败: ' + err);
                });
        },

        handleChatFilesDrop(event, cardId = '', characterName = '') {
            this.dragOverChats = false;
            this._uploadChatFiles(event?.dataTransfer?.files || [], cardId, characterName);
        },

        triggerChatImport(options = {}) {
            this.filePickerMode = options.mode || 'global';
            this.filePickerPayload = options.payload || null;
            if (this.$refs.chatImportInput) {
                this.$refs.chatImportInput.click();
            }
        },

        handleChatInputChange(e) {
            const input = e.target;
            try {
                const payload = this.filePickerPayload || {};
                if (this.filePickerMode === 'card') {
                    this._uploadChatFiles(input.files || [], payload.cardId || '', payload.characterName || '');
                } else {
                    this._uploadChatFiles(input.files || [], '', '');
                }
            } finally {
                this.filePickerMode = 'global';
                this.filePickerPayload = null;
                input.value = '';
            }
        },

        searchInDetail() {
            const query = String(this.detailSearchQuery || '').trim().toLowerCase();
            this.detailSearchResults = [];
            this.detailSearchIndex = -1;
            if (!query || !this.activeChat) return;

            const matches = [];
            const sourceMessages = Array.isArray(this.activeChat.messages) ? this.activeChat.messages : [];
            sourceMessages.forEach((message) => {
                const displaySource = this.ensureMessageDisplaySource(message);
                const text = `${message.name || ''}\n${displaySource || ''}\n${message.mes || ''}`.toLowerCase();
                if (text.includes(query)) {
                    matches.push(Number(message.floor || 0));
                }
            });

            this.detailSearchResults = matches;
            if (matches.length > 0) {
                this.detailSearchIndex = 0;
                this.scrollToFloor(matches[0]);
            }
        },

        nextSearchResult() {
            if (!this.detailSearchResults.length) return;
            this.detailSearchIndex = (this.detailSearchIndex + 1) % this.detailSearchResults.length;
            this.scrollToFloor(this.detailSearchResults[this.detailSearchIndex]);
        },

        previousSearchResult() {
            if (!this.detailSearchResults.length) return;
            this.detailSearchIndex = (this.detailSearchIndex - 1 + this.detailSearchResults.length) % this.detailSearchResults.length;
            this.scrollToFloor(this.detailSearchResults[this.detailSearchIndex]);
        },

        scrollToFloor(floor, persist = true, behavior = 'smooth') {
            const targetFloor = Number(floor || 0);
            if (!targetFloor || !this.activeChat) return;

            if (this.readerAppMode) {
                this.jumpFloorInput = String(targetFloor);
                if (this.executableMessageFloors.includes(targetFloor)) {
                    this.readerViewportFloor = targetFloor;
                    this.setReaderAppFloor(targetFloor);
                    if (persist) {
                        this.activeChat.last_view_floor = targetFloor;
                    }
                } else {
                    this.$store.global.showToast(`楼层 #${targetFloor} 没有可执行实例，已退出整页实例模式`, 2200);
                    this.deactivateChatAppStage();
                    this.$nextTick(() => this.scrollToFloor(targetFloor, persist, behavior));
                }
                return;
            }

            if (this.detailBookmarkedOnly && !this.isBookmarked(targetFloor)) {
                this.detailBookmarkedOnly = false;
            }

            this.jumpFloorInput = String(targetFloor);
            this.readerViewportFloor = targetFloor;
            this.ensureReaderWindowForFloor(targetFloor, 'center');

            this.$nextTick(() => {
                const root = document.querySelector('.chat-reader-overlay--fullscreen');
                const el = root ? root.querySelector(`[data-chat-floor="${targetFloor}"]`) : null;
                if (el) {
                    this.scrollElementToTop(el, behavior);
                }
            });

            if (persist) {
                this.activeChat.last_view_floor = targetFloor;
                updateChatMeta({ id: this.activeChat.id, last_view_floor: targetFloor }).then((res) => {
                    if (res.success && res.chat) {
                        const index = this.chatList.findIndex(item => item.id === res.chat.id);
                        if (index > -1) {
                            this.chatList.splice(index, 1, { ...this.chatList[index], ...res.chat });
                        }
                    }
                }).catch(() => {});
            }
        },

        jumpToInputFloor() {
            const value = String(this.jumpFloorInput || '').trim().replace(/^#/, '');
            const floor = parseInt(value, 10);
            if (!floor || floor < 1) {
                alert('请输入有效的楼层编号');
                return;
            }
            this.scrollToFloor(floor);
        },

        openMessageAsAppStage(message) {
            const floor = Number(message?.floor || 0);
            if (!floor) return;

            if (!this.executableMessageFloors.includes(floor)) {
                this.$store.global.showToast(`楼层 #${floor} 没有检测到可执行实例`, 2200);
                return;
            }

            this.readerViewportFloor = floor;
            this.jumpFloorInput = String(floor);
            this.setReaderAppFloor(floor);
        },

        jumpToEdge(which) {
            const messages = Array.isArray(this.activeChat?.messages) ? this.activeChat.messages : [];
            if (!messages.length) return;
            if (which === 'first') {
                this.scrollToFloor(messages[0].floor);
                return;
            }
            this.scrollToFloor(messages[messages.length - 1].floor);
        },

        toggleBookmark(message) {
            if (!this.activeChat || !message) return;

            const floor = Number(message.floor || 0);
            if (!floor) return;

            const current = Array.isArray(this.activeChat.bookmarks) ? [...this.activeChat.bookmarks] : [];
            const index = current.findIndex(item => Number(item.floor || 0) === floor);
            if (index > -1) {
                current.splice(index, 1);
            } else {
                current.push({
                    id: `${floor}_${Date.now()}`,
                    floor,
                    label: String(this.bookmarkDraft || '').trim(),
                    text: String(this.ensureMessageDisplaySource(message) || message.mes || '').trim().slice(0, 120),
                    created_at: Date.now() / 1000,
                });
                this.bookmarkDraft = '';
            }

            this.activeChat.bookmarks = current;
            this.saveChatMeta();
        },

        isBookmarked(floor) {
            if (!this.activeChat || !Array.isArray(this.activeChat.bookmarks)) return false;
            const target = Number(floor || 0);
            return this.activeChat.bookmarks.some(item => Number(item.floor || 0) === target);
        },

        async persistChatContent(rawMessages, toastText = '聊天内容已保存', metadataOverride = null) {
            if (!this.activeChat) return false;

            const payload = {
                id: this.activeChat.id,
                raw_messages: rawMessages,
                metadata: ensureChatMetadataShape(metadataOverride || this.activeChat.metadata || {}),
            };

            const res = await saveChat(payload);
            if (!res.success || !res.chat) {
                alert(res.msg || '聊天保存失败');
                return false;
            }

            const preserveName = this.detailDraftName;
            const preserveNotes = this.detailDraftNotes;
            const preserveRegexConfigDraft = normalizeRegexConfig(this.regexConfigDraft);
            this.activeChat = res.chat;
            this.detailDraftName = preserveName;
            this.detailDraftNotes = preserveNotes;
            this.regexConfigDraft = preserveRegexConfigDraft;

            const index = this.chatList.findIndex(item => item.id === res.chat.id);
            if (index > -1) {
                this.chatList.splice(index, 1, { ...this.chatList[index], ...res.chat });
            }

            window.dispatchEvent(new CustomEvent('refresh-detail-chats'));
            this.$store.global.showToast(toastText, 1600);
            return true;
        },

        async replaceAllInChat() {
            if (!this.activeChat) return;

            const query = String(this.replaceQuery || '');
            if (!query.trim()) {
                alert('请输入要查找的内容');
                return;
            }

            const replacement = String(this.replaceReplacement || '');
            const rawMessages = JSON.parse(JSON.stringify(this.activeChat.raw_messages || []));
            let regex = null;

            if (this.replaceUseRegex) {
                try {
                    regex = new RegExp(query, this.replaceCaseSensitive ? 'g' : 'gi');
                } catch (err) {
                    alert(`正则表达式无效: ${err.message}`);
                    return;
                }
            }

            let changedMessages = 0;
            let totalReplaced = 0;

            rawMessages.forEach((message) => {
                if (!message || typeof message !== 'object') return;
                const original = String(message.mes || '');
                const result = this.replaceUseRegex
                    ? (() => {
                        let count = 0;
                        const text = original.replace(regex, () => {
                            count += 1;
                            return replacement;
                        });
                        return { text, count };
                    })()
                    : replaceTextValue(original, query, replacement, this.replaceCaseSensitive);
                if (result.count > 0) {
                    message.mes = result.text;
                    changedMessages += 1;
                    totalReplaced += result.count;
                }
            });

            if (totalReplaced === 0) {
                this.replaceStatus = '没有找到可替换内容';
                this.$store.global.showToast(this.replaceStatus, 1400);
                return;
            }

            const ok = await this.persistChatContent(rawMessages, `已替换 ${totalReplaced} 处文本`);
            if (!ok) return;

            this.replaceStatus = `已在 ${changedMessages} 条记录中替换 ${totalReplaced} 处`;
            if (this.detailSearchQuery) {
                this.searchInDetail();
            }
        },

        openImmersive(item) {
            if (!item || !item.id) return;
            this.openChatDetail(item);
        },
    };
}
