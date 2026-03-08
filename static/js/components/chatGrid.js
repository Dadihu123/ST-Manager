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
import { renderMarkdown, updateInlineRenderContent } from '../utils/dom.js';
import { clearActiveRuntimeContext, setActiveRuntimeContext } from '../runtime/runtimeContext.js';


const CHAT_READER_REGEX_STORAGE_KEY = 'st_manager.chat_reader.regex_config.v1';
const CHAT_READER_VIEW_SETTINGS_KEY = 'st_manager.chat_reader.view_settings.v1';
const CHAT_READER_RENDER_PREFS_KEY = 'st_manager.chat_reader.render_prefs.v1';

const DEFAULT_CHAT_READER_REGEX_CONFIG = {
    userInputPattern: '<本轮用户输入>\\s*([\\s\\S]*?)\\s*</本轮用户输入>',
    recallPattern: '<recall>([\\s\\S]*?)</recall>',
    thinkingPattern: '\\[metacognition\\]([\\s\\S]*?)(?=\\n<content>|$)',
    contentPattern: '<content>([\\s\\S]*?)</content>',
    summaryPattern: '<details>\\s*<summary>\\s*小总结\\s*</summary>([\\s\\S]*?)</details>',
    choicePattern: '<choice>([\\s\\S]*?)</choice>',
    timeBarPattern: '```([^`·]+·[^`]+)```',
    displayRules: [],
};

const EMPTY_CHAT_READER_REGEX_CONFIG = {
    userInputPattern: '',
    recallPattern: '',
    thinkingPattern: '',
    contentPattern: '',
    summaryPattern: '',
    choicePattern: '',
    timeBarPattern: '',
    displayRules: [],
};

const CHAT_READER_REGEX_FIELDS = [
    'userInputPattern',
    'recallPattern',
    'thinkingPattern',
    'contentPattern',
    'summaryPattern',
    'choicePattern',
    'timeBarPattern',
];

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
};

const DEFAULT_CHAT_READER_RENDER_PREFS = {
    renderMode: 'markdown',
    componentMode: true,
};


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


function canMapRuleToReaderField(rule) {
    if (!rule || typeof rule !== 'object') return false;
    return !String(rule.replaceString || '').trim();
}


function convertRulesToReaderConfig(rules, currentConfig, options = {}) {
    const fillDefaults = options.fillDefaults !== false;
    const nextConfig = normalizeRegexConfig(currentConfig, { fillDefaults });
    const displayRules = [];
    const displayCandidates = filterReaderDisplayRules(rules);
    const claimedFields = new Set();
    const sourceTag = options.source || 'draft';

    const fieldMappings = [
        { field: 'thinkingPattern', keywords: ['思维链', 'think', 'meow', 'metacognition', '内心', '思考', 'cognition', 'inner'] },
        { field: 'summaryPattern', keywords: ['小总结', 'summary', '摘要', '总结'] },
        { field: 'userInputPattern', keywords: ['用户输入', 'user.?input', '本轮用户'] },
        { field: 'timeBarPattern', keywords: ['时间', 'time', 'timebar', '状态栏', '地点'] },
        { field: 'recallPattern', keywords: ['recall', '记忆', '召回', '回忆'] },
        { field: 'contentPattern', keywords: ['content', '正文', '内容'] },
        { field: 'choicePattern', keywords: ['choice', '选项', 'option', '选择'] },
    ];

    displayCandidates.forEach((rule) => {
        const haystack = `${rule.scriptName} ${rule.findRegex}`.toLowerCase();
        const mapping = fieldMappings.find((item) => item.keywords.some((keyword) => new RegExp(keyword, 'i').test(haystack)));
        if (mapping && canMapRuleToReaderField(rule) && !claimedFields.has(mapping.field)) {
            const currentValue = String(nextConfig[mapping.field] || '').trim();
            const defaultValue = fillDefaults ? String(DEFAULT_CHAT_READER_REGEX_CONFIG[mapping.field] || '').trim() : '';
            if (!currentValue || currentValue === defaultValue) {
                nextConfig[mapping.field] = rule.findRegex;
                claimedFields.add(mapping.field);
                return;
            }
        }

        displayRules.push(normalizeDisplayRule({
            scriptName: rule.scriptName,
            findRegex: rule.findRegex,
            replaceString: rule.replaceString,
            substituteRegex: rule.substituteRegex,
            trimStrings: rule.trimStrings,
            disabled: rule.disabled,
            runOnEdit: rule.runOnEdit,
            minDepth: rule.minDepth,
            maxDepth: rule.maxDepth,
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
        userInputPattern: String(source.userInputPattern ?? fallback.userInputPattern),
        recallPattern: String(source.recallPattern ?? fallback.recallPattern),
        thinkingPattern: String(source.thinkingPattern ?? fallback.thinkingPattern),
        contentPattern: String(source.contentPattern ?? fallback.contentPattern),
        summaryPattern: String(source.summaryPattern ?? fallback.summaryPattern),
        choicePattern: String(source.choicePattern ?? fallback.choicePattern),
        timeBarPattern: String(source.timeBarPattern ?? fallback.timeBarPattern),
        displayRules: Array.isArray(source.displayRules)
            ? source.displayRules.map((item, index) => normalizeDisplayRule(item, index)).filter(item => item.findRegex)
            : [],
    };
}


function mergeRegexConfigs(baseConfig, overrideConfig) {
    const base = normalizeRegexConfig(baseConfig);
    const override = normalizeRegexConfig(overrideConfig, { fillDefaults: false });

    const next = {
        userInputPattern: override.userInputPattern || base.userInputPattern,
        recallPattern: override.recallPattern || base.recallPattern,
        thinkingPattern: override.thinkingPattern || base.thinkingPattern,
        contentPattern: override.contentPattern || base.contentPattern,
        summaryPattern: override.summaryPattern || base.summaryPattern,
        choicePattern: override.choicePattern || base.choicePattern,
        timeBarPattern: override.timeBarPattern || base.timeBarPattern,
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
    return CHAT_READER_REGEX_FIELDS.some((field) => String(normalized[field] || '').trim())
        || normalized.displayRules.length > 0;
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
    const placement = Number(options.placement ?? 2);
    const isMarkdown = options.isMarkdown !== false;
    const isPrompt = options.isPrompt === true;
    const isEdit = options.isEdit === true;
    const macroContext = options.macroContext && typeof options.macroContext === 'object' ? options.macroContext : {};

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
        if (rule.markdownOnly && !isMarkdown) continue;
        if (isEdit && rule.runOnEdit === false) continue;
        if (Array.isArray(rule.placement) && rule.placement.length > 0 && !rule.placement.includes(placement)) continue;
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


function extractHtmlPayloadFromText(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';

    const codeBlockRegex = /```(?:html|xml|text|js|css|json)?\s*([\s\S]*?)```/gi;
    let match;

    while ((match = codeBlockRegex.exec(raw)) !== null) {
        const block = stripCommonIndent(match[1] || '');
        if (/<!DOCTYPE html/i.test(block) || /<html[\s>]/i.test(block) || /id=["']readingContent["']/i.test(block)) {
            return block;
        }
    }

    if (/<!DOCTYPE html/i.test(raw) || /<html[\s>]/i.test(raw)) {
        return raw;
    }

    return '';
}


function buildFullPageAppHtml(messageText, config, macroContext = {}) {
    const rawMessage = String(messageText || '');
    if (!rawMessage.trim()) return '';

    const transformedRaw = applyDisplayRules(rawMessage, config, { placement: 2, isMarkdown: true, macroContext });
    const htmlFromRaw = extractHtmlPayloadFromText(transformedRaw);
    if (htmlFromRaw) {
        return htmlFromRaw;
    }

    const extractedContent = extractContentWithConfig(rawMessage, config, { placement: 2, isMarkdown: true, macroContext });
    const htmlFromExtractedContent = extractHtmlPayloadFromText(extractedContent);
    if (htmlFromExtractedContent) {
        return htmlFromExtractedContent;
    }

    return '';
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


function extractContentWithConfig(messageText, config, options = {}) {
    if (!messageText) return '';

    let content = String(messageText || '');

    const userInputRegex = compileReaderPattern(config.userInputPattern, 'i');
    if (userInputRegex) {
        const match = content.match(userInputRegex);
        if (match && match[1]) {
            content = match[1];
        }
    }

    const recallRegex = compileReaderPattern(config.recallPattern, 'gi');
    if (recallRegex) {
        content = content.replace(recallRegex, '');
    }

    const thinkingRegex = compileReaderPattern(config.thinkingPattern, 'gi');
    if (thinkingRegex) {
        content = content.replace(thinkingRegex, '');
    }

    const mainContentRegex = compileReaderPattern(config.contentPattern, 'i');
    if (mainContentRegex) {
        const match = content.match(mainContentRegex);
        if (match && match[1]) {
            content = match[1];
        }
    }

    content = content.replace(/以下是用户的本轮输入[\s\S]*?<\/本轮用户输入>/g, '');
    return applyDisplayRules(stripCommonIndent(content), config, options);
}


function extractSingleMatch(messageText, pattern) {
    if (!messageText || !pattern) return null;
    const regex = compileReaderPattern(pattern, 'i');
    if (!regex) return null;
    const match = String(messageText).match(regex);
    if (!match || !match[1]) return null;
    return stripCommonIndent(match[1]);
}


function parseChoicesWithConfig(messageText, config, options = {}) {
    const match = extractSingleMatch(messageText, config.choicePattern);
    if (!match) return [];

    const choices = [];
    for (const line of match.split(/\r?\n/)) {
        const itemMatch = line.match(/^\s*(.+?)\s*-\s*(.+?)\s*$/);
        if (!itemMatch) continue;
        choices.push({
            text: applyDisplayRules(itemMatch[1].trim(), config, { placement: 2, isMarkdown: true, macroContext: options.macroContext }),
            desc: applyDisplayRules(itemMatch[2].trim(), config, { placement: 2, isMarkdown: true, macroContext: options.macroContext }),
        });
    }
    return choices;
}


function buildReaderParsedMessage(rawMessage, floor, config, options = {}) {
    const source = rawMessage && typeof rawMessage === 'object' ? rawMessage : {};
    const messageText = String(source.mes || '');
    const macroContext = options.macroContext && typeof options.macroContext === 'object' ? options.macroContext : {};

    return {
        floor: Number(floor || 0),
        name: source.name || 'Unknown',
        is_user: Boolean(source.is_user),
        is_system: Boolean(source.is_system),
        send_date: source.send_date || '',
        mes: messageText,
        swipes: Array.isArray(source.swipes) ? source.swipes : [],
        extra: source.extra && typeof source.extra === 'object' ? source.extra : {},
        content: extractContentWithConfig(messageText, config, { placement: 2, isMarkdown: true, macroContext }),
        time_bar: applyDisplayRules(extractSingleMatch(messageText, config.timeBarPattern) || '', config, { placement: 2, isMarkdown: true, macroContext }) || null,
        summary: applyDisplayRules(extractSingleMatch(messageText, config.summaryPattern) || '', config, { placement: 2, isMarkdown: true, macroContext }) || null,
        thinking: applyDisplayRules(extractSingleMatch(messageText, config.thinkingPattern) || '', config, { placement: 2, isMarkdown: true, macroContext }) || null,
        choices: parseChoicesWithConfig(messageText, config, { macroContext }),
    };
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


function looksLikeFullPageChatApp(messageText) {
    return Boolean(extractHtmlPayloadFromText(messageText));
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
        chatAppStage: null,

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

            const bookmarks = Array.isArray(this.activeChat.bookmarks) ? this.activeChat.bookmarks : [];
            const bookmarkSet = new Set(bookmarks.map(item => Number(item.floor || 0)).filter(Boolean));
            const total = this.activeChat.messages.length;
            const currentFloor = Number(this.readerViewportFloor || this.activeChat.last_view_floor || total || 1);
            const fullCount = Number(this.readerViewSettings.fullDisplayCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount);
            const renderNearby = Number(this.readerViewSettings.renderNearbyCount || DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount);
            const lastAlwaysVisibleFloor = Math.max(1, total - fullCount + 1);
            const expansionStartFloor = Math.max(1, currentFloor - renderNearby);
            const expansionEndFloor = Math.min(total, currentFloor + renderNearby);

            let messages = this.activeChat.messages.map((message) => ({
                ...message,
                is_bookmarked: bookmarkSet.has(Number(message.floor || 0)),
                is_full_display: Number(message.floor || 0) >= lastAlwaysVisibleFloor
                    || Number(message.floor || 0) >= expansionStartFloor && Number(message.floor || 0) <= expansionEndFloor,
                should_render_full: Number(message.floor || 0) >= expansionStartFloor
                    && Number(message.floor || 0) <= expansionEndFloor,
                compact_preview: buildCompactPreview(message, this.readerViewSettings.compactPreviewLength),
            }));

            if (this.detailBookmarkedOnly) {
                messages = messages.filter(item => item.is_bookmarked);
            }

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

        get editingMessageTarget() {
            const targetFloor = Number(this.editingFloor || 0);
            if (!targetFloor || !this.activeChat || !Array.isArray(this.activeChat.messages)) return null;
            return this.activeChat.messages.find(item => Number(item.floor || 0) === targetFloor) || null;
        },

        get editingMessageParsedPreview() {
            if (!this.editingMessageRawDraft) return '';
            return extractContentWithConfig(this.editingMessageRawDraft, this.activeRegexConfig, {
                placement: 2,
                isMarkdown: true,
                isEdit: true,
                macroContext: this.buildReaderRegexMacroContext(this.editingMessageTarget || { mes: this.editingMessageRawDraft }, this.editingFloor),
            });
        },

        get editingMessageSourcePreview() {
            return this.editingMessageRawDraft || this.editingMessageDraft || '';
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
                    thinking: '',
                    summary: '',
                    time_bar: '',
                    choices: [],
                };
            }

            return buildReaderParsedMessage({
                mes: source,
                name: 'Regex Test',
            }, 1, normalizeRegexConfig(this.regexConfigDraft), { macroContext: this.buildReaderRegexMacroContext({ mes: source, name: 'Regex Test' }, 1) });
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

            const fullVisible = messages.filter(item => item.is_full_display).length;
            const renderedNow = messages.filter(item => item.should_render_full).length;
            return `完整显示 ${fullVisible} 层，当前高渲染 ${renderedNow} 层`;
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
            if (this.chatAppStage) {
                this.chatAppStage.clear();
            }
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

        syncReaderViewportFloor() {
            this.$nextTick(() => {
                const root = document.querySelector('.chat-reader-overlay--fullscreen');
                const container = root ? root.querySelector('.chat-reader-center') : null;
                if (!container) return;

                const cards = Array.from(container.querySelectorAll('[data-chat-floor]'));
                if (!cards.length) return;

                const containerRect = container.getBoundingClientRect();
                const viewportCenter = containerRect.top + containerRect.height * 0.42;
                let bestFloor = this.readerViewportFloor || 1;
                let bestDistance = Infinity;

                cards.forEach((card) => {
                    const rect = card.getBoundingClientRect();
                    const center = rect.top + rect.height / 2;
                    const distance = Math.abs(center - viewportCenter);
                    if (distance < bestDistance) {
                        bestDistance = distance;
                        bestFloor = Number(card.getAttribute('data-chat-floor') || bestFloor);
                    }
                });

                this.readerViewportFloor = bestFloor;
            });
        },

        handleReaderScroll() {
            this.syncReaderViewportFloor();
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

            const matchedFloors = [];
            const candidate = this.activeChat.raw_messages.find((message, index) => {
                const floor = Number(message?.floor || index + 1 || 0);
                const htmlPayload = buildFullPageAppHtml(message?.mes || '', this.activeRegexConfig, this.buildReaderRegexMacroContext(message, floor));
                const matched = Boolean(htmlPayload && looksLikeFullPageChatApp(htmlPayload));
                if (matched) {
                    matchedFloors.push(floor);
                }
                return matched;
            });

            if (!candidate) {
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

            this.readerAppFloor = Number(candidate.floor || this.activeChat.raw_messages.indexOf(candidate) + 1 || 0);
            this.readerAppMode = this.readerAppFloor > 0;
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

            const htmlPayload = buildFullPageAppHtml(rawMessage?.mes || '', this.activeRegexConfig, this.buildReaderRegexMacroContext(rawMessage, floor));
            if (!htmlPayload) {
                return null;
            }

            return {
                floor,
                htmlPayload,
                assetBase: this.activeReaderAssetBase,
                context: buildChatAppCompatContext(this.activeChat.raw_messages, floor, rawMessage, parsedMessage, this.activeChat),
            };
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
            if (!this.readerAppMode) {
                this.$store.global.showToast(this.readerAppDebug.status || '当前聊天未检测到整页前端实例', 2200);
                return;
            }

            const isMobile = this.$store.global.deviceType === 'mobile';
            if (isMobile) {
                this.readerShowLeftPanel = false;
            }

            this.$nextTick(() => {
                this.mountChatAppStage();
                this.syncChatAppStage();
            });
        },

        deactivateChatAppStage() {
            this.readerAppMode = false;
            this.readerAppSignature = '';
            if (this.chatAppStage) {
                this.chatAppStage.clear();
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
                macroContext: this.buildReaderRegexMacroContext(item, index + 1),
            }));
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

        detectRenderMode(text) {
            const source = String(text || '').trim();
            if (!source) return 'plain';

            const htmlFragmentRegex = /^\s*<(?:div|style|details|section|article|main|link|table|script|iframe|svg)/i;
            const fencedHtmlRegex = /```(?:html|xml|text|js|css|json)?\s*[\s\S]*?(?:<div|<style|<!DOCTYPE|<html|<script)/i;

            if (this.readerComponentMode && (htmlFragmentRegex.test(source) || fencedHtmlRegex.test(source))) {
                return 'html-component';
            }

            if (this.readerRenderMode === 'markdown') {
                return 'markdown';
            }

            return 'plain';
        },

        mountReaderRender(el, text) {
            if (!el) return;

            const mode = this.detectRenderMode(text);

            if (mode === 'html-component') {
                updateInlineRenderContent(el, String(text || ''), {
                    mode: 'html-component',
                    minHeight: 220,
                    maxHeight: 520,
                    assetBase: this.activeReaderAssetBase,
                });
                return;
            }

            updateInlineRenderContent(el, String(text || ''), {
                mode,
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
            const raw = String(this.editingMessageRawDraft || '');
            const contentPattern = String(this.activeRegexConfig.contentPattern || '').trim();
            if (!contentPattern) {
                this.editingMessageRawDraft = this.editingMessageDraft;
                return;
            }

            try {
                const regex = new RegExp(contentPattern, 'i');
                if (!regex.test(raw)) {
                    this.editingMessageRawDraft = this.editingMessageDraft;
                    return;
                }
                this.editingMessageRawDraft = raw.replace(regex, (_match, captured) => {
                    const fallback = typeof captured === 'string' ? captured : '';
                    return _match.replace(fallback, this.editingMessageDraft);
                });
            } catch {
                this.editingMessageRawDraft = this.editingMessageDraft;
            }
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
            return extractContentWithConfig(messageText, this.activeRegexConfig, {
                placement: 2,
                isMarkdown: true,
                macroContext: this.buildReaderRegexMacroContext(this.editingMessageTarget || { mes: messageText }, this.editingFloor),
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
            this.visibleDetailMessages.forEach((message) => {
                const text = `${message.name || ''}\n${message.content || ''}\n${message.mes || ''}`.toLowerCase();
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

        scrollToFloor(floor, persist = true) {
            const targetFloor = Number(floor || 0);
            if (!targetFloor || !this.activeChat) return;

            if (this.readerAppMode) {
                this.readerViewportFloor = targetFloor;
                if (persist) {
                    this.activeChat.last_view_floor = targetFloor;
                }
                return;
            }

            this.jumpFloorInput = String(targetFloor);
            this.readerViewportFloor = targetFloor;

            this.$nextTick(() => {
                const root = document.querySelector('.chat-reader-overlay--fullscreen');
                const el = root ? root.querySelector(`[data-chat-floor="${targetFloor}"]`) : null;
                if (el) {
                    this.scrollElementToTop(el, 'smooth');
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

        jumpToEdge(which) {
            const messages = this.visibleDetailMessages;
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
                    text: String(message.content || message.mes || '').trim().slice(0, 120),
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
