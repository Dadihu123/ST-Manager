/**
 * static/js/components/chatGrid.js
 * 聊天记录网格与全屏阅读器组件
 */

import {
  bindChatToCard,
  deleteChat,
  getChatDetail,
  getChatRange,
  importChats,
  listChats,
  saveChat,
  searchChats,
  updateChatMeta,
} from "../api/chat.js";
import { getCardDetail, listCards } from "../api/card.js";
import { openPath } from "../api/system.js";
import { formatDate } from "../utils/format.js";
import { ChatAppStage } from "../runtime/chatAppStage.js";
import {
  renderMarkdown,
  updateInlineRenderContent,
  clearInlineIsolatedHtml,
  applyPretextIntrinsicSize,
  estimatePretextBlockHeight,
  updateShadowContent,
} from "../utils/dom.js";
import {
  extractReaderEnhancementMetadata,
  buildReaderEnhancementPolicy,
  decorateReaderRenderedHtml,
} from "../utils/chatReaderEnhancements.js";
import {
  applyUnifiedDisplayRules,
  buildUnifiedDisplaySource,
  renderUnifiedDisplayHtml,
} from "../utils/unifiedTextPreview.js";
import { formatScopedDisplayedHtml } from "../utils/stDisplayFormatter.js";
import {
  createFloorVariableSnapshotResolver,
  getActiveMessageVariables,
  getCardVariables,
  getChatMetadataVariables,
} from "../utils/chatReaderVariableSnapshots.js";
import {
  clearActiveRuntimeContext,
  setActiveRuntimeContext,
} from "../runtime/runtimeContext.js";

const CHAT_READER_VIEW_SETTINGS_KEY = "st_manager.chat_reader.view_settings.v1";
const CHAT_READER_RENDER_PREFS_KEY = "st_manager.chat_reader.render_prefs.v1";
const CHAT_READER_AUTO_PAGE_THRESHOLD = 240;
const CHAT_READER_PAGE_GROUP_PREFETCH_RADIUS = 1;

const DEFAULT_CHAT_READER_REGEX_CONFIG = {
  displayRules: [],
};

const EMPTY_CHAT_READER_REGEX_CONFIG = {
  displayRules: [],
};

const REGEX_RULE_SOURCE_META = {
  card: { label: "角色卡", order: 1, tone: "success" },
  preset_import: { label: "ST 预设导入", order: 2, tone: "accent" },
  regex_import: { label: "Regex 导入", order: 3, tone: "info" },
  manual: { label: "手写", order: 4, tone: "accent" },
  chat: { label: "聊天自定义", order: 5, tone: "muted" },
  unknown: { label: "来源未识别", order: 9, tone: "muted" },
};

REGEX_RULE_SOURCE_META.reader_import = {
  label: "阅读器配置导入",
  order: 2.5,
  tone: "info",
};

const DEFAULT_CHAT_READER_VIEW_SETTINGS = {
  fullDisplayCount: 2,
  renderNearbyCount: 4,
  compactPreviewLength: 140,
  instanceRenderDepth: 1,
  simpleRenderRadius: 12,
  hiddenHistoryThreshold: 28,
  reasoningDefaultCollapsed: true,
  autoCollapseLongCode: true,
};

const DEFAULT_CHAT_READER_RENDER_PREFS = {
  renderMode: "markdown",
  componentMode: true,
  browseMode: "auto",
};

const CHAT_READER_PAGE_SIZE = 96;
const CHAT_READER_NAV_BATCH_SIZE = 200;
const CHAT_READER_PAGE_NEIGHBOR_COUNT = 1;
const CHAT_READER_WINDOW_SIZE = 120;
const CHAT_READER_WINDOW_OVERLAP = 24;
const CHAT_READER_VARIABLE_CHECKPOINT_INTERVAL = 25;
const CHAT_READER_VARIABLE_RECENT_CACHE_SIZE = 24;
const CHAT_READER_WINDOW_STEP = Math.max(
  1,
  CHAT_READER_WINDOW_SIZE - CHAT_READER_WINDOW_OVERLAP,
);
const READER_VIEWPORT_SYNC_IDLE_MS = 120;
const READER_VIEWPORT_TOP_PROBE_OFFSET = 72;
const READER_PAGE_MODE_IMMEDIATE_RUNTIME_RADIUS = 1;

const READER_ANCHOR_MODES = {
  LOCKED_FLOOR: "locked_floor",
  TAIL_COMPATIBLE: "tail_compatible",
  SEMI_AUTO: "semi_auto",
};

const READER_ANCHOR_SOURCES = {
  RESTORE: "restore",
  JUMP: "jump",
  SEARCH: "search",
  BOOKMARK: "bookmark",
  APP_STAGE: "app_stage",
  NAVIGATOR: "navigator",
};

const READER_BROWSE_MODES = {
  AUTO: "auto",
  SCROLL: "scroll",
  PAGE_NON_USER: "page_non_user",
  PAGE_PAIR: "page_pair",
};

function normalizeReaderAnchorMode(mode) {
  switch (String(mode || "").trim()) {
    case READER_ANCHOR_MODES.LOCKED_FLOOR:
      return READER_ANCHOR_MODES.LOCKED_FLOOR;
    case READER_ANCHOR_MODES.TAIL_COMPATIBLE:
      return READER_ANCHOR_MODES.TAIL_COMPATIBLE;
    case "semi_auto":
    case READER_ANCHOR_MODES.SEMI_AUTO:
      return READER_ANCHOR_MODES.SEMI_AUTO;
    default:
      return READER_ANCHOR_MODES.LOCKED_FLOOR;
  }
}

function normalizeReaderBrowseMode(mode) {
  switch (String(mode || "").trim()) {
    case READER_BROWSE_MODES.SCROLL:
      return READER_BROWSE_MODES.SCROLL;
    case READER_BROWSE_MODES.PAGE_NON_USER:
      return READER_BROWSE_MODES.PAGE_NON_USER;
    case READER_BROWSE_MODES.PAGE_PAIR:
      return READER_BROWSE_MODES.PAGE_PAIR;
    default:
      return READER_BROWSE_MODES.AUTO;
  }
}

function resolveEffectiveReaderBrowseMode(
  mode,
  totalMessages = 0,
  activeChat = null,
) {
  const normalized = normalizeReaderBrowseMode(mode);
  const resolved =
    normalized === READER_BROWSE_MODES.AUTO
      ? Number(totalMessages || 0) >= CHAT_READER_AUTO_PAGE_THRESHOLD
        ? READER_BROWSE_MODES.PAGE_PAIR
        : READER_BROWSE_MODES.SCROLL
      : normalized;
  if (
    resolved === READER_BROWSE_MODES.PAGE_NON_USER &&
    activeChat?.message_index_included === false
  ) {
    return READER_BROWSE_MODES.PAGE_PAIR;
  }
  return resolved;
}

function isReaderPageBrowseMode(mode) {
  const normalized = normalizeReaderBrowseMode(mode);
  return (
    normalized === READER_BROWSE_MODES.PAGE_NON_USER ||
    normalized === READER_BROWSE_MODES.PAGE_PAIR
  );
}

function normalizeReaderDepthMode(mode) {
  switch (String(mode || "").trim()) {
    case "anchor_abs":
      return "anchor_abs";
    case "anchor_backward":
      return "anchor_backward";
    case "anchor_relative":
      return "anchor_relative";
    default:
      return "";
  }
}

function normalizeRegexRuleSource(source) {
  switch (String(source || "").trim()) {
    case "card":
      return "card";
    case "preset":
    case "preset_import":
    case "st_preset":
    case "st_preset_import":
      return "preset_import";
    case "regex":
    case "regex_file":
    case "regex_import":
    case "regex_script":
      return "regex_import";
    case "manual":
    case "handwritten":
      return "manual";
    case "chat":
    case "draft":
    case "local":
    case "builtin":
    case "legacy_chat":
      return "chat";
    default:
      return "unknown";
  }
}

function normalizeDisplayRule(rule, index = 0) {
  const source = rule && typeof rule === "object" ? rule : {};
  const normalizeNullableNumber = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  };

  return {
    id: source.id || `display_rule_${Date.now()}_${index}`,
    scriptName:
      String(source.scriptName || source.name || `规则 ${index + 1}`).trim() ||
      `规则 ${index + 1}`,
    findRegex: String(source.findRegex || "").trim(),
    replaceString: String(source.replaceString || ""),
    substituteRegex: Number(source.substituteRegex || 0),
    trimStrings: Array.isArray(source.trimStrings)
      ? source.trimStrings.map((item) => String(item))
      : [],
    disabled: Boolean(source.disabled),
    promptOnly: Boolean(source.promptOnly),
    markdownOnly: Boolean(source.markdownOnly),
    runOnEdit: source.runOnEdit !== false,
    minDepth: normalizeNullableNumber(source.minDepth),
    maxDepth: normalizeNullableNumber(source.maxDepth),
    readerDepthMode: normalizeReaderDepthMode(
      source.readerDepthMode || source.reader_depth_mode,
    ),
    readerMinDepth: normalizeNullableNumber(
      source.readerMinDepth ?? source.reader_min_depth,
    ),
    readerMaxDepth: normalizeNullableNumber(
      source.readerMaxDepth ?? source.reader_max_depth,
    ),
    placement: Array.isArray(source.placement) ? source.placement : [],
    expanded: Boolean(source.expanded),
    deleted: Boolean(source.deleted),
    overrideKey: String(source.overrideKey || source.override_key || "").trim(),
    source: normalizeRegexRuleSource(source.source),
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

const READER_REGEX_PLACEMENT_LABELS = {
  [READER_REGEX_PLACEMENT.MD_DISPLAY]: "Markdown 显示",
  [READER_REGEX_PLACEMENT.USER_INPUT]: "用户输入",
  [READER_REGEX_PLACEMENT.AI_OUTPUT]: "AI 输出",
  [READER_REGEX_PLACEMENT.SLASH_COMMAND]: "Slash 命令",
  [READER_REGEX_PLACEMENT.WORLD_INFO]: "世界书",
  [READER_REGEX_PLACEMENT.REASONING]: "思维链",
};

const READER_REGEX_DEPTH_MODE_LABELS = {
  anchor_abs: "锚点绝对距离",
  anchor_backward: "仅锚点之前",
  anchor_relative: "锚点相对距离",
};

const DISPLAY_RULE_SUBSTITUTE_LABELS = {
  0: "不替换",
  1: "Raw",
  2: "Escaped",
};

function getDisplayRuleRegexDescriptor(findRegex) {
  const raw = String(findRegex || "").trim();
  if (!raw) {
    return {
      raw: "",
      pattern: "",
      flags: "",
      standard: "未填写匹配正则",
      valid: false,
      error: "",
    };
  }

  try {
    const compiled = parseDisplayRuleRegex(raw);
    const flags = compiled.flags || "g";
    return {
      raw,
      pattern: compiled.source,
      flags,
      standard: `/${compiled.source}/${flags}`,
      valid: true,
      error: "",
    };
  } catch (error) {
    return {
      raw,
      pattern: raw,
      flags: "",
      standard: raw,
      valid: false,
      error: error?.message || "正则无效",
    };
  }
}

function describeRegexRulePlacements(placements) {
  const values = Array.isArray(placements) ? placements : [];
  if (!values.length) return "全部位置";
  return values
    .map((value) => READER_REGEX_PLACEMENT_LABELS[value] || `位置 ${value}`)
    .join(" · ");
}

function summarizeRegexRulePlacements(placements) {
  const values = Array.isArray(placements) ? placements : [];
  if (!values.length) return "全部位置";
  if (values.length === 1) {
    return READER_REGEX_PLACEMENT_LABELS[values[0]] || `位置 ${values[0]}`;
  }
  return `${values.length} 个位置`;
}

function describeRegexRuleDepth(rule) {
  const normalizedMode = normalizeReaderDepthMode(rule?.readerDepthMode);
  const parts = [];
  if (normalizedMode) {
    parts.push(
      READER_REGEX_DEPTH_MODE_LABELS[normalizedMode] || normalizedMode,
    );
  }
  if (rule?.readerMinDepth !== null && rule?.readerMinDepth !== undefined) {
    parts.push(`min ${rule.readerMinDepth}`);
  }
  if (rule?.readerMaxDepth !== null && rule?.readerMaxDepth !== undefined) {
    parts.push(`max ${rule.readerMaxDepth}`);
  }
  return parts.length ? parts.join(" · ") : "未限制";
}

function describeRegexRuleScope(rule) {
  const scopes = [];
  if (rule?.markdownOnly) scopes.push("仅 Markdown");
  if (rule?.promptOnly) scopes.push("仅 Prompt");
  return scopes.length ? scopes.join(" · ") : "常规消息";
}

function inspectRegexDisplayRule(rule, index = 0) {
  if (!rule) return null;

  const normalized = normalizeDisplayRule(rule, index);
  const regexDescriptor = getDisplayRuleRegexDescriptor(normalized.findRegex);
  const sourceMeta = getRegexRuleSourceMeta(rule?.source || normalized.source);
  const placementSummary = describeRegexRulePlacements(normalized.placement);
  const placementShort = summarizeRegexRulePlacements(normalized.placement);
  const trimPreview = normalized.trimStrings.join("\n");
  const hasReplacement = String(normalized.replaceString || "").length > 0;
  const showRawPattern = Boolean(
    regexDescriptor.valid &&
    normalized.findRegex &&
    normalized.findRegex !== regexDescriptor.standard,
  );

  return {
    ...normalized,
    sourceLabel: rule?.sourceLabel || sourceMeta.label,
    sourceTone: rule?.sourceTone || sourceMeta.tone,
    standardPattern: regexDescriptor.standard,
    rawPattern: normalized.findRegex || "",
    showRawPattern,
    regexError: regexDescriptor.error,
    flagsLabel: regexDescriptor.flags || "无",
    macroModeLabel:
      DISPLAY_RULE_SUBSTITUTE_LABELS[Number(normalized.substituteRegex || 0)] ||
      "不替换",
    placementSummary,
    placementShort,
    depthSummary: describeRegexRuleDepth(normalized),
    scopeSummary: describeRegexRuleScope(normalized),
    runtimeSummary:
      normalized.runOnEdit === false
        ? "仅显示解析时运行"
        : "编辑和显示解析都会运行",
    trimSummary: normalized.trimStrings.length
      ? `${normalized.trimStrings.length} 条`
      : "无",
    trimPreview,
    hasTrimStrings: normalized.trimStrings.length > 0,
    replacementDisplay: hasReplacement
      ? normalized.replaceString
      : "(空字符串，命中后会删除匹配内容)",
    replacementSummary: hasReplacement
      ? "命中后替换为上方文本"
      : "命中后删除匹配内容",
    stateLabel: normalized.deleted
      ? "已删除"
      : normalized.disabled
        ? "已禁用"
        : "生效中",
    stateTone: normalized.deleted || normalized.disabled ? "muted" : "accent",
    listPattern: regexDescriptor.standard || "未填写匹配正则",
    listMeta: [
      normalized.disabled ? "已禁用" : "启用",
      regexDescriptor.flags ? `/${regexDescriptor.flags}` : "未编译",
      placementShort,
      hasReplacement ? "有替换" : "删除匹配",
    ]
      .filter(Boolean)
      .join(" · "),
    orderLabel: `#${index + 1}`,
  };
}

function buildDisplayRuleKey(rule) {
  const normalized = normalizeDisplayRule(rule);
  return `${normalized.scriptName}__${normalized.findRegex}`;
}

function resolveDisplayRuleMatchKeys(rule) {
  const normalized = normalizeDisplayRule(rule);
  const currentKey = buildDisplayRuleKey(normalized);
  const overrideKey = String(normalized.overrideKey || "").trim();
  return {
    currentKey,
    overrideKey,
    primaryKey: overrideKey || currentKey,
  };
}

function getRegexRuleSourceMeta(source) {
  return (
    REGEX_RULE_SOURCE_META[normalizeRegexRuleSource(source)] ||
    REGEX_RULE_SOURCE_META.unknown
  );
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

function decorateRegexDisplayRules(
  config,
  fallbackSource = "unknown",
  options = {},
) {
  const includeDeleted = options.includeDeleted === true;
  const sourceRules = Array.isArray(config?.displayRules)
    ? config.displayRules
    : [];
  return sourceRules
    .map((rule, index) => {
      const normalized = normalizeDisplayRule(rule, index);
      const source =
        normalized.source !== "unknown"
          ? normalized.source
          : normalizeRegexRuleSource(fallbackSource);
      const meta = getRegexRuleSourceMeta(source);
      return {
        ...normalized,
        source,
        sourceLabel: meta.label,
        sourceTone: meta.tone,
        sourceOrder: meta.order,
      };
    })
    .filter((rule) => includeDeleted || !rule.deleted);
}

function summarizeRegexRuleSources(rules, fallbackSource = "unknown") {
  const groups = decorateRegexDisplayRules(
    { displayRules: rules },
    fallbackSource,
  ).reduce((acc, rule) => {
    acc[rule.source] = (acc[rule.source] || 0) + 1;
    return acc;
  }, {});

  return Object.entries(groups)
    .sort(
      (a, b) =>
        getRegexRuleSourceMeta(a[0]).order - getRegexRuleSourceMeta(b[0]).order,
    )
    .map(
      ([source, count]) =>
        `${getRegexRuleSourceMeta(source).label} ${count} 条`,
    )
    .join(" · ");
}

function isRegexRuleCandidate(item) {
  if (!item || typeof item !== "object") return false;
  return Boolean(
    item.findRegex ||
    item.regex ||
    item.pattern ||
    item.expression ||
    item.match ||
    item.find ||
    item.regexPattern,
  );
}

function parseSillyTavernRegexRules(jsonData) {
  const rules = [];
  const seen = new Set();

  const pushRule = (item, nameHint = "") => {
    if (!isRegexRuleCandidate(item)) return;
    const pattern = String(
      item.findRegex ||
        item.regex ||
        item.pattern ||
        item.expression ||
        item.match ||
        item.find ||
        item.regexPattern ||
        "",
    ).trim();
    if (!pattern) return;
    const normalized = {
      scriptName:
        String(
          item.scriptName ||
            item.name ||
            item.label ||
            nameHint ||
            `规则 ${rules.length + 1}`,
        ).trim() || `规则 ${rules.length + 1}`,
      findRegex: pattern,
      replaceString: String(item.replaceString || ""),
      substituteRegex: Number(item.substituteRegex || 0),
      trimStrings: Array.isArray(item.trimStrings)
        ? item.trimStrings.map((entry) => String(entry))
        : [],
      disabled: Boolean(item.disabled),
      promptOnly: Boolean(item.promptOnly),
      markdownOnly: Boolean(item.markdownOnly),
      runOnEdit: item.runOnEdit !== false,
      minDepth: item.minDepth ?? null,
      maxDepth: item.maxDepth ?? null,
      readerDepthMode: item.readerDepthMode || item.reader_depth_mode || "",
      readerMinDepth: item.readerMinDepth ?? item.reader_min_depth ?? null,
      readerMaxDepth: item.readerMaxDepth ?? item.reader_max_depth ?? null,
      placement: Array.isArray(item.placement) ? item.placement : [],
    };
    const key = `${normalized.scriptName}__${normalized.findRegex}__${normalized.replaceString}`;
    if (seen.has(key)) return;
    seen.add(key);
    rules.push(normalized);
  };

  const visit = (node, nameHint = "") => {
    if (node === null || node === undefined) return;

    if (Array.isArray(node)) {
      node.forEach((item, index) =>
        visit(item, nameHint || `规则 ${index + 1}`),
      );
      return;
    }

    if (typeof node !== "object") {
      return;
    }

    pushRule(node, nameHint);

    Object.entries(node).forEach(([key, value]) => {
      if (key === "config") {
        if (typeof value === "string") {
          try {
            visit(JSON.parse(value), nameHint || key);
          } catch {
            // Ignore invalid nested config payloads.
          }
          return;
        }
        visit(value, nameHint || key);
        return;
      }

      if (key === "prompts" && Array.isArray(value)) {
        value.forEach((prompt, index) => {
          if (
            prompt &&
            typeof prompt === "object" &&
            Object.prototype.hasOwnProperty.call(prompt, "regex")
          ) {
            visit(prompt.regex, prompt.name || `${key}_${index + 1}`);
          }
        });
      }

      visit(value, key);
    });
  };

  visit(jsonData);

  return rules;
}

function detectImportedRegexSource(jsonData) {
  if (Array.isArray(jsonData)) {
    return jsonData.every((item) => isRegexRuleCandidate(item))
      ? "regex_import"
      : "preset_import";
  }

  if (!jsonData || typeof jsonData !== "object") {
    return "regex_import";
  }

  const looksLikeStandaloneRule =
    isRegexRuleCandidate(jsonData) &&
    !jsonData.extensions &&
    !jsonData.extension_settings &&
    !jsonData.prompts &&
    !jsonData.SPreset &&
    !jsonData.RegexBinding;

  return looksLikeStandaloneRule ? "regex_import" : "preset_import";
}

function filterReaderDisplayRules(rules, options = {}) {
  const includeDisabled = options.includeDisabled === true;
  const includeDeleted = options.includeDeleted === true;
  return rules.filter((rule) => {
    const normalized = normalizeDisplayRule(rule);
    if (!normalized.findRegex) return false;
    if (!includeDeleted && normalized.deleted) return false;
    if (!includeDisabled && normalized.disabled) return false;
    if (normalized.promptOnly) return false;
    if (
      !Array.isArray(normalized.placement) ||
      normalized.placement.length === 0
    )
      return true;
    return normalized.placement.includes(READER_REGEX_PLACEMENT.AI_OUTPUT);
  });
}

function buildReaderEffectiveRegexConfig(config) {
  const normalized = normalizeRegexConfig(config, { fillDefaults: false });
  return {
    ...normalized,
    displayRules: filterReaderDisplayRules(
      Array.isArray(normalized.displayRules) ? normalized.displayRules : [],
    ),
  };
}

function buildReaderInspectorRegexConfig(config, options = {}) {
  const normalized = normalizeRegexConfig(config, { fillDefaults: false });
  return {
    ...normalized,
    displayRules: filterReaderDisplayRules(
      Array.isArray(normalized.displayRules) ? normalized.displayRules : [],
      {
        includeDisabled: true,
        includeDeleted: options.includeDeleted === true,
      },
    ),
  };
}

function extractReaderRegexConfig(jsonData) {
  const candidates = [];

  if (jsonData && typeof jsonData === "object") {
    candidates.push(jsonData);

    if (
      jsonData.reader_regex_config &&
      typeof jsonData.reader_regex_config === "object"
    ) {
      candidates.push(jsonData.reader_regex_config);
    }

    if (
      jsonData.metadata?.reader_regex_config &&
      typeof jsonData.metadata.reader_regex_config === "object"
    ) {
      candidates.push(jsonData.metadata.reader_regex_config);
    }

    if (jsonData.config) {
      if (typeof jsonData.config === "string") {
        try {
          const parsedConfig = JSON.parse(jsonData.config);
          if (parsedConfig && typeof parsedConfig === "object") {
            candidates.push(parsedConfig);
          }
        } catch {
          // Ignore invalid nested JSON strings.
        }
      } else if (typeof jsonData.config === "object") {
        candidates.push(jsonData.config);
      }
    }
  }

  for (const candidate of candidates) {
    if (
      !candidate ||
      typeof candidate !== "object" ||
      !Array.isArray(candidate.displayRules)
    ) {
      continue;
    }

    return normalizeRegexConfig(candidate, { fillDefaults: false });
  }

  return null;
}

function importReaderRegexConfig(currentConfig, importedConfig, options = {}) {
  const fillDefaults = options.fillDefaults !== false;
  const nextConfig = normalizeRegexConfig(currentConfig, { fillDefaults });
  const normalizedImport = markRegexConfigRuleSource(
    normalizeRegexConfig(importedConfig, { fillDefaults: false }),
    options.source || "reader_import",
  );

  if (options.mode === "replace") {
    return normalizeRegexConfig(normalizedImport, { fillDefaults });
  }

  return mergeRegexConfigs(nextConfig, normalizedImport);
}

function convertRulesToReaderConfig(rules, currentConfig, options = {}) {
  const fillDefaults = options.fillDefaults !== false;
  const nextConfig = normalizeRegexConfig(currentConfig, { fillDefaults });
  const displayCandidates = filterReaderDisplayRules(rules);
  const sourceTag = options.source || "manual";
  const mode = options.mode || "merge";
  const importedConfig = {
    displayRules: [],
  };

  displayCandidates.forEach((rule) => {
    importedConfig.displayRules.push(
      normalizeDisplayRule(
        {
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
          readerDepthMode: rule.readerDepthMode,
          readerMinDepth: rule.readerMinDepth,
          readerMaxDepth: rule.readerMaxDepth,
          placement: Array.isArray(rule.placement) ? [...rule.placement] : [],
          source: sourceTag,
        },
        importedConfig.displayRules.length,
      ),
    );
  });

  if (mode === "replace") {
    return normalizeRegexConfig(importedConfig, { fillDefaults });
  }

  return mergeRegexConfigs(nextConfig, importedConfig);
}

function normalizeRegexConfig(raw, options = {}) {
  const source = raw && typeof raw === "object" ? raw : {};
  const fallback =
    options.fillDefaults === false
      ? EMPTY_CHAT_READER_REGEX_CONFIG
      : DEFAULT_CHAT_READER_REGEX_CONFIG;

  return {
    displayRules: Array.isArray(source.displayRules)
      ? source.displayRules
          .map((item, index) => normalizeDisplayRule(item, index))
          .filter((item) => item.findRegex)
      : [],
  };
}

function mergeRegexConfigs(baseConfig, overrideConfig) {
  const base = normalizeRegexConfig(baseConfig);
  const override = normalizeRegexConfig(overrideConfig, {
    fillDefaults: false,
  });

  const next = {
    displayRules: [],
  };

  const mergedRules = [];
  const seen = new Map();
  const rememberSeenKey = (key, index) => {
    if (!key) return;
    seen.set(key, index);
  };
  const feedRule = (rule, expanded = false, replaceExisting = false) => {
    const normalized = normalizeDisplayRule({ ...rule, expanded });
    const { currentKey, overrideKey, primaryKey } =
      resolveDisplayRuleMatchKeys(normalized);
    if (!normalized.findRegex) return;

    if (!replaceExisting && seen.has(currentKey)) {
      return;
    }

    const existingIndex = replaceExisting
      ? seen.has(primaryKey)
        ? seen.get(primaryKey)
        : seen.has(currentKey)
          ? seen.get(currentKey)
          : -1
      : -1;
    if (existingIndex >= 0) {
      mergedRules[existingIndex] = normalized;
      rememberSeenKey(primaryKey, existingIndex);
      rememberSeenKey(currentKey, existingIndex);
      rememberSeenKey(overrideKey, existingIndex);
      return;
    }

    const nextIndex = mergedRules.length;
    mergedRules.push(normalized);
    rememberSeenKey(currentKey, nextIndex);
    rememberSeenKey(primaryKey, nextIndex);
    rememberSeenKey(overrideKey, nextIndex);
  };

  base.displayRules.forEach((rule) => feedRule(rule, false, false));
  override.displayRules.forEach((rule) => feedRule(rule, false, true));
  next.displayRules = mergedRules;
  return next;
}

function dedupeRegexConfig(config) {
  return mergeRegexConfigs(
    EMPTY_CHAT_READER_REGEX_CONFIG,
    normalizeRegexConfig(config, { fillDefaults: false }),
  );
}

function hasCustomRegexConfig(config) {
  const normalized = normalizeRegexConfig(config, { fillDefaults: false });
  return normalized.displayRules.length > 0;
}

function deriveReaderConfigFromCard(cardDetail) {
  const source =
    cardDetail?.card && typeof cardDetail.card === "object"
      ? cardDetail.card
      : cardDetail;

  if (!source || typeof source !== "object") {
    return normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, {
      fillDefaults: false,
    });
  }

  const dataBlock =
    source.data && typeof source.data === "object" ? source.data : null;
  const extractionSource = {};

  if (source.extensions && typeof source.extensions === "object") {
    extractionSource.extensions = source.extensions;
  }
  if (
    source.extension_settings &&
    typeof source.extension_settings === "object"
  ) {
    extractionSource.extension_settings = source.extension_settings;
  }
  if (Array.isArray(source.regex_scripts)) {
    extractionSource.regex_scripts = source.regex_scripts;
  }
  if (source.SPreset && typeof source.SPreset === "object") {
    extractionSource.SPreset = source.SPreset;
  }
  if (source.RegexBinding && typeof source.RegexBinding === "object") {
    extractionSource.RegexBinding = source.RegexBinding;
  }
  if (Array.isArray(source.prompts)) {
    extractionSource.prompts = source.prompts;
  }
  if (dataBlock?.extensions && typeof dataBlock.extensions === "object") {
    extractionSource.data = {
      ...(extractionSource.data || {}),
      extensions: dataBlock.extensions,
    };
  }
  if (
    dataBlock?.extension_settings &&
    typeof dataBlock.extension_settings === "object"
  ) {
    extractionSource.data = {
      ...(extractionSource.data || {}),
      extension_settings: dataBlock.extension_settings,
    };
  }
  if (Array.isArray(dataBlock?.prompts)) {
    extractionSource.data = {
      ...(extractionSource.data || {}),
      prompts: dataBlock.prompts,
    };
  }

  const rules = parseSillyTavernRegexRules(
    Object.keys(extractionSource).length
      ? extractionSource
      : { extensions: source.extensions || {} },
  );
  if (!rules.length) {
    return normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, {
      fillDefaults: false,
    });
  }

  return convertRulesToReaderConfig(rules, EMPTY_CHAT_READER_REGEX_CONFIG, {
    fillDefaults: false,
    source: "card",
    mode: "replace",
  });
}

function ensureChatMetadataShape(metadata) {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return {};
  }

  const next = { ...metadata };
  if (Object.keys(next).length === 0) {
    return {};
  }

  if (
    !Object.prototype.hasOwnProperty.call(next, "chat_metadata") ||
    typeof next.chat_metadata !== "object" ||
    Array.isArray(next.chat_metadata)
  ) {
    next.chat_metadata = {};
  }

  return next;
}

function stripCommonIndent(text) {
  const source = String(text || "").replace(/\r\n/g, "\n");
  const lines = source.split("\n");

  while (lines.length && !lines[0].trim()) {
    lines.shift();
  }
  while (lines.length && !lines[lines.length - 1].trim()) {
    lines.pop();
  }

  const indents = lines
    .filter((line) => line.trim())
    .map((line) => {
      const match = line.match(/^\s*/);
      return match ? match[0].length : 0;
    });

  const minIndent = indents.length ? Math.min(...indents) : 0;
  return lines
    .map((line) => line.slice(minIndent))
    .join("\n")
    .trim();
}

function normalizeViewSettings(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const fullDisplayCount = Number.parseInt(
    source.fullDisplayCount ?? source.tailKeepaliveCount,
    10,
  );
  const renderNearbyCount = Number.parseInt(source.renderNearbyCount, 10);
  const compactPreviewLength = Number.parseInt(source.compactPreviewLength, 10);
  const instanceRenderDepth = Number.parseInt(source.instanceRenderDepth, 10);
  const simpleRenderRadius = Number.parseInt(source.simpleRenderRadius, 10);
  const hiddenHistoryThreshold = Number.parseInt(
    source.hiddenHistoryThreshold,
    10,
  );
  const reasoningDefaultCollapsed = source.reasoningDefaultCollapsed;
  const autoCollapseLongCode = source.autoCollapseLongCode;

  return {
    fullDisplayCount: Number.isFinite(fullDisplayCount)
      ? Math.min(20, Math.max(0, fullDisplayCount))
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
    reasoningDefaultCollapsed:
      reasoningDefaultCollapsed === undefined
        ? DEFAULT_CHAT_READER_VIEW_SETTINGS.reasoningDefaultCollapsed
        : Boolean(reasoningDefaultCollapsed),
    autoCollapseLongCode:
      autoCollapseLongCode === undefined
        ? DEFAULT_CHAT_READER_VIEW_SETTINGS.autoCollapseLongCode
        : Boolean(autoCollapseLongCode),
  };
}

function shouldPromoteReaderAnchorForSource(anchorMode, anchorSource) {
  if (anchorMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE) return false;
  if (anchorMode === READER_ANCHOR_MODES.LOCKED_FLOOR) return true;
  return [
    READER_ANCHOR_SOURCES.JUMP,
    READER_ANCHOR_SOURCES.SEARCH,
    READER_ANCHOR_SOURCES.BOOKMARK,
    READER_ANCHOR_SOURCES.APP_STAGE,
    READER_ANCHOR_SOURCES.NAVIGATOR,
  ].includes(anchorSource);
}

function shouldResetReaderWindowForAnchorTarget({
  targetFloor,
  windowStartFloor,
  windowEndFloor,
  totalMessages,
  safetyBand = CHAT_READER_WINDOW_OVERLAP,
}) {
  const target = Number(targetFloor || 0);
  const start = Math.max(1, Number(windowStartFloor || 1));
  const total = Math.max(1, Number(totalMessages || 1));
  const end = Math.min(total, Math.max(start, Number(windowEndFloor || total)));
  const margin = Math.max(1, Number(safetyBand || 0));

  if (!target) return false;
  if (target < start || target > end) return true;

  return target <= start + margin || target >= end - margin;
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
    window.localStorage.setItem(
      CHAT_READER_VIEW_SETTINGS_KEY,
      JSON.stringify(normalizeViewSettings(settings)),
    );
  } catch {
    // Ignore storage failures in the reader.
  }
}

function createReaderManifestMessage(indexItem, floor) {
  const source = indexItem && typeof indexItem === "object" ? indexItem : {};
  const preview = String(source.preview || "").trim();

  return {
    floor: Number(floor || source.floor || 0),
    name: String(
      source.name ||
        (source.is_user ? "User" : source.is_system ? "System" : "Assistant") ||
        "Unknown",
    ),
    is_user: Boolean(source.is_user),
    is_system: Boolean(source.is_system),
    send_date: String(source.send_date || ""),
    mes: preview,
    swipes: [],
    extra: {},
    content: preview,
    display_source: "",
    display_source_cache_key: "",
    rendered_display_html: "",
    tail_depth: null,
    time_bar: null,
    summary: null,
    thinking: null,
    choices: [],
    preview_text: preview,
    has_runtime_candidate: Boolean(source.has_runtime_candidate),
    __loaded: false,
    __readerRegexConfig: null,
    __readerDepthInfo: null,
  };
}

function createReaderManifestMessages(messageIndex, totalCount = 0) {
  const total = Math.max(
    0,
    Number(totalCount || 0) ||
      (Array.isArray(messageIndex) ? messageIndex.length : 0),
  );
  const sourceIndex = Array.isArray(messageIndex) ? messageIndex : [];
  const messages = [];

  for (let floor = 1; floor <= total; floor += 1) {
    messages.push(createReaderManifestMessage(sourceIndex[floor - 1], floor));
  }

  return messages;
}

function mergeReaderManifestIntoMessage(
  existingMessage,
  manifest,
  options = {},
) {
  const existing =
    existingMessage && typeof existingMessage === "object"
      ? existingMessage
      : null;
  const nextManifest =
    manifest && typeof manifest === "object"
      ? manifest
      : createReaderManifestMessage(null, 0);
  if (!existing) {
    return {
      ...nextManifest,
    };
  }

  const preserveLoadedPayload =
    Boolean(options.preserveLoadedPayload) && Boolean(existing.__loaded);
  return {
    ...existing,
    floor: Number(nextManifest.floor || existing.floor || 0),
    name: String(nextManifest.name || existing.name || "Unknown"),
    is_user: Boolean(nextManifest.is_user),
    is_system: Boolean(nextManifest.is_system),
    send_date: String(nextManifest.send_date || existing.send_date || ""),
    preview_text: nextManifest.preview_text || existing.preview_text || "",
    has_runtime_candidate: Boolean(
      nextManifest.has_runtime_candidate || existing.has_runtime_candidate,
    ),
    ...(preserveLoadedPayload
      ? {}
      : {
          mes: nextManifest.mes,
          content: nextManifest.content,
          display_source: nextManifest.display_source,
          display_source_cache_key: nextManifest.display_source_cache_key,
          rendered_display_html: nextManifest.rendered_display_html,
          tail_depth: nextManifest.tail_depth,
          time_bar: nextManifest.time_bar,
          summary: nextManifest.summary,
          thinking: nextManifest.thinking,
          choices: Array.isArray(nextManifest.choices)
            ? nextManifest.choices
            : [],
          swipes: Array.isArray(nextManifest.swipes) ? nextManifest.swipes : [],
          extra:
            nextManifest.extra && typeof nextManifest.extra === "object"
              ? nextManifest.extra
              : {},
          __loaded: false,
        }),
  };
}

function createReaderPageGroup(
  floors = [],
  index = 0,
  mode = READER_BROWSE_MODES.SCROLL,
) {
  const normalizedFloors = [
    ...new Set(
      (Array.isArray(floors) ? floors : [])
        .map((item) => Number(item || 0))
        .filter(Boolean),
    ),
  ].sort((left, right) => left - right);

  if (!normalizedFloors.length) {
    return null;
  }

  const startFloor = normalizedFloors[0];
  const endFloor = normalizedFloors[normalizedFloors.length - 1];
  const anchorFloor = endFloor;

  return {
    id: `${mode}:${startFloor}:${endFloor}:${index}`,
    index,
    floors: normalizedFloors,
    startFloor,
    endFloor,
    anchorFloor,
  };
}

function buildReaderPageGroups(activeChat, mode = READER_BROWSE_MODES.SCROLL) {
  const effectiveMode = normalizeReaderBrowseMode(mode);
  const messages = Array.isArray(activeChat?.messages)
    ? activeChat.messages
    : [];
  const total = messages.length;
  if (!total || !isReaderPageBrowseMode(effectiveMode)) {
    return [];
  }

  if (
    effectiveMode === READER_BROWSE_MODES.PAGE_NON_USER &&
    activeChat?.message_index_included !== false
  ) {
    const groups = messages
      .filter(
        (message) => message && typeof message === "object" && !message.is_user,
      )
      .map((message, index) =>
        createReaderPageGroup(
          [Number(message.floor || 0)],
          index,
          effectiveMode,
        ),
      )
      .filter(Boolean);

    if (groups.length) {
      return groups;
    }
  }

  const groups = [];
  const leadInFloors = [];
  for (let floor = 1; floor <= Math.min(total, 3); floor += 1) {
    leadInFloors.push(floor);
  }
  if (leadInFloors.length) {
    groups.push(
      createReaderPageGroup(leadInFloors, groups.length, effectiveMode),
    );
  }

  for (let startFloor = 4; startFloor <= total; startFloor += 2) {
    const floors = [startFloor];
    if (startFloor + 1 <= total) {
      floors.push(startFloor + 1);
    }
    const group = createReaderPageGroup(floors, groups.length, effectiveMode);
    if (group) {
      groups.push(group);
    }
  }

  return groups.filter(Boolean);
}

function normalizeReaderScopedFloors(floors = []) {
  return [
    ...new Set(
      (Array.isArray(floors) ? floors : [])
        .map((item) => Number(item || 0))
        .filter(Boolean),
    ),
  ].sort((left, right) => left - right);
}

function isReaderIgnorableTailPlaceholder(entry) {
  const source =
    entry && typeof entry === "object"
      ? entry.message && typeof entry.message === "object"
        ? entry.message
        : entry
      : {};
  if (source.is_user || source.is_system) {
    return false;
  }

  const previewText = String(
    source.preview ?? source.preview_text ?? source.content ?? source.mes ?? "",
  ).trim();
  if (previewText) {
    return false;
  }

  const extra =
    source.extra && typeof source.extra === "object" ? source.extra : {};
  if (String(extra.display_text || "").trim()) {
    return false;
  }

  if (Array.isArray(source.swipes)) {
    return (
      source.swipes.length > 0 &&
      source.swipes.every((item) => !String(item || "").trim())
    );
  }

  return !Boolean(source.has_runtime_candidate);
}

function trimReaderIgnorableTailEntries(entries = []) {
  const source = Array.isArray(entries) ? entries.slice() : [];
  while (
    source.length &&
    isReaderIgnorableTailPlaceholder(source[source.length - 1])
  ) {
    source.pop();
  }
  return source;
}

function resolveReaderEffectiveMessageCount(chat = null) {
  const source = chat && typeof chat === "object" ? chat : {};
  const declaredTotal = Math.max(
    0,
    Number(source.message_index_total || source.message_count || 0),
  );
  if (declaredTotal > 0) {
    return declaredTotal;
  }

  const indexedMessages = trimReaderIgnorableTailEntries(source.message_index);
  if (indexedMessages.length) {
    return indexedMessages.length;
  }

  const parsedMessages = trimReaderIgnorableTailEntries(source.messages);
  if (parsedMessages.length) {
    return parsedMessages.length;
  }

  const rawMessages = trimReaderIgnorableTailEntries(source.raw_messages);
  if (rawMessages.length) {
    return rawMessages.length;
  }

  return Math.max(0, Number(source.message_count || 0));
}

function createReaderVisibleMessagesCache() {
  return {
    messagesRef: null,
    bookmarksRef: null,
    detailBookmarkedOnly: false,
    browseMode: "",
    pageGroupId: "",
    currentFloor: 0,
    anchorMode: "",
    anchorSource: "",
    windowStartFloor: 0,
    windowEndFloor: 0,
    fullCount: 0,
    renderNearby: 0,
    simpleRenderRadius: 0,
    expansionStartFloor: 0,
    expansionEndFloor: 0,
    simpleStartFloor: 0,
    simpleEndFloor: 0,
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
      const direct = current.closest("[data-chat-floor]");
      if (direct) {
        return direct;
      }
    }

    const root =
      typeof current.getRootNode === "function" ? current.getRootNode() : null;
    if (root instanceof ShadowRoot && root.host) {
      current = root.host;
      continue;
    }

    break;
  }

  return null;
}

function isReaderProbeCardMatch(container, card, probeY) {
  if (
    !(container instanceof Element) ||
    !(card instanceof Element) ||
    !container.contains(card)
  ) {
    return false;
  }

  const rect = card.getBoundingClientRect();
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    rect.top <= probeY &&
    rect.bottom >= probeY
  );
}

function findReaderFloorCardAtProbe(container, sampleX, probeY) {
  if (!(container instanceof Element)) return null;

  const probeTargets =
    typeof document.elementsFromPoint === "function"
      ? document.elementsFromPoint(sampleX, probeY)
      : [document.elementFromPoint(sampleX, probeY)];

  for (const target of probeTargets) {
    const card = findFloorCardFromNode(target);
    if (isReaderProbeCardMatch(container, card, probeY)) {
      return card;
    }
  }

  return null;
}

function normalizeRenderPreferences(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const renderMode = source.renderMode === "plain" ? "plain" : "markdown";

  return {
    renderMode,
    componentMode: source.componentMode !== false,
    browseMode: normalizeReaderBrowseMode(
      source.browseMode || source.readerBrowseMode,
    ),
  };
}

function loadStoredRenderPreferences() {
  try {
    const raw = window.localStorage.getItem(CHAT_READER_RENDER_PREFS_KEY);
    if (!raw)
      return normalizeRenderPreferences(DEFAULT_CHAT_READER_RENDER_PREFS);
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

function compileReaderPattern(pattern, flags = "") {
  if (!pattern) return null;
  try {
    const source = String(pattern);
    const wrapped = source.match(/^\/([\s\S]+)\/([dgimsuvy]*)$/);
    if (wrapped) {
      const mergedFlags = Array.from(
        new Set(`${wrapped[2]}${flags}`.split("")),
      ).join("");
      return new RegExp(wrapped[1], mergedFlags);
    }
    return new RegExp(source, flags);
  } catch {
    return null;
  }
}

function parseDisplayRuleRegex(findRegex) {
  const source = String(findRegex || "").trim();
  if (!source) return null;

  const wrapped = source.match(/^\/([\s\S]+)\/([dgimsuvy]*)$/);
  if (wrapped) {
    return new RegExp(wrapped[1], wrapped[2]);
  }

  return new RegExp(source, "g");
}

function sanitizeRegexMacroValue(value) {
  return String(value ?? "").replaceAll(
    /[\n\r\t\v\f\0.^$*+?{}[\]\\/|()]/gs,
    (token) => {
      switch (token) {
        case "\n":
          return "\\n";
        case "\r":
          return "\\r";
        case "\t":
          return "\\t";
        case "\v":
          return "\\v";
        case "\f":
          return "\\f";
        case "\0":
          return "\\0";
        default:
          return `\\${token}`;
      }
    },
  );
}

function substituteDisplayRuleMacros(
  text,
  macroContext = {},
  sanitizer = null,
) {
  const source = String(text ?? "");
  const context =
    macroContext && typeof macroContext === "object" ? macroContext : {};

  return source.replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (match, rawKey) => {
    const key = String(rawKey || "")
      .trim()
      .toLowerCase();
    const value = Object.prototype.hasOwnProperty.call(context, key)
      ? context[key]
      : Object.prototype.hasOwnProperty.call(context, rawKey)
        ? context[rawKey]
        : match;
    const normalized = String(value ?? "");
    return typeof sanitizer === "function" ? sanitizer(normalized) : normalized;
  });
}

function getDisplayRuleRegexSource(rule, options = {}) {
  const normalized = normalizeDisplayRule(rule);
  switch (Number(normalized.substituteRegex || 0)) {
    case 1:
      return substituteDisplayRuleMacros(
        normalized.findRegex,
        options.macroContext,
      );
    case 2:
      return substituteDisplayRuleMacros(
        normalized.findRegex,
        options.macroContext,
        sanitizeRegexMacroValue,
      );
    default:
      return normalized.findRegex;
  }
}

function getReaderDisplayRuleOrderBucket(rule, index = 0) {
  const normalized = normalizeDisplayRule(rule, index);
  const pattern = String(normalized.findRegex || "").toLowerCase();
  const replace = String(normalized.replaceString || "");
  const actionTag = `<${"\u884c\u52a8\u9009\u9879"}>`;

  if (pattern.includes("think")) {
    return -100;
  }

  if (
    pattern.includes(actionTag) &&
    pattern.includes("statusplaceholderimpl")
  ) {
    return -60;
  }

  if (
    pattern.includes("summary") ||
    pattern.includes("statusplaceholderimpl") ||
    pattern.includes("now_plot") ||
    pattern.includes("updatevariable") ||
    pattern.includes("<update>")
  ) {
    return -50;
  }

  if (
    /<!doctype html|<html[\s>]|```html|```text|<style[\s>]|<script[\s>]/i.test(
      replace,
    )
  ) {
    return 20;
  }

  return 0;
}

function orderReaderDisplayRules(rules = []) {
  return (Array.isArray(rules) ? rules : [])
    .map((rule, index) => ({
      rule,
      index,
      bucket: getReaderDisplayRuleOrderBucket(rule, index),
    }))
    .sort(
      (left, right) => left.bucket - right.bucket || left.index - right.index,
    )
    .map((entry) => entry.rule);
}

function stripReaderControlBlocks(text) {
  let output = String(text || "");

  output = output.replace(/<disclaimer\b[^>]*>[\s\S]*?<\/disclaimer>/gi, "\n");
  output = output.replace(/(?:\n\s*){3,}/g, "\n\n");

  return output.trim();
}

export function applyDisplayRules(text, config) {
  const options =
    arguments[2] && typeof arguments[2] === "object" ? arguments[2] : {};
  return applyUnifiedDisplayRules(text, config, options);
}

function getMessageExecutableParts(message, host = null) {
  const parts = [];
  const seen = new Set();

  if (host instanceof Element) {
    const codeNodes = Array.from(host.querySelectorAll("pre code"));
    codeNodes.forEach((node) => {
      const text = String(node.textContent || "").trim();
      if (!text) return;
      const analysis = analyzeRuntimeCandidate(text);
      if (analysis.isCandidate && !seen.has(text)) {
        seen.add(text);
        parts.push({ type: "app-stage", text });
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
    const text = String(part?.text || "");

    if (part?.type === "app-stage") score += 100;
    if (/<!doctype html/i.test(text) || /<html[\s>]/i.test(text)) score += 40;
    if (/id=["']readingContent["']/i.test(text)) score += 20;
    if (/function\s+processTextContent\s*\(/i.test(text)) score += 12;
    if (/window\.setTheme\s*=\s*applyTheme/i.test(text)) score += 8;
    if (/showArgMenu\s*\(/i.test(text)) score += 6;
    return score;
  };

  return (
    parts
      .slice()
      .sort(
        (left, right) =>
          scorePart(right) - scorePart(left) ||
          String(right.text || "").length - String(left.text || "").length,
      )[0] || null
  );
}

function createRuntimeCandidateCache() {
  return {
    floorMap: new Map(),
    executableFloorsKey: "",
    executableFloors: [],
  };
}

function looksLikeFrontendSnippet(source) {
  const text = String(source || "").toLowerCase();
  return ["html>", "<head>", "<body", "<!doctype html"].some((token) =>
    text.includes(token),
  );
}

function analyzeRuntimeCandidate(source) {
  const normalizedText = String(source || "").trim();
  const analysis = scoreFullPageAppHtml(normalizedText);
  const frontendLike = looksLikeFrontendSnippet(normalizedText);
  const boostedScore =
    frontendLike && analysis.score < 8 ? analysis.score + 8 : analysis.score;
  const reasons =
    frontendLike && !analysis.reasons.includes("frontend-like")
      ? [...analysis.reasons, "frontend-like"]
      : analysis.reasons;

  return {
    ...analysis,
    score: boostedScore,
    reasons,
    frontendLike,
    isCandidate: frontendLike || analysis.score >= 8,
  };
}

function getRenderedDisplayHtmlForMessage(
  message,
  renderedFloorHtmlCache = null,
) {
  const floor = Number(message?.floor || 0);
  if (
    renderedFloorHtmlCache instanceof Map &&
    floor > 0 &&
    renderedFloorHtmlCache.has(floor)
  ) {
    return String(renderedFloorHtmlCache.get(floor) || "");
  }

  return String(message?.rendered_display_html || "");
}

function buildReaderCacheScopeKey(activeChat, floor = 0, message = null) {
  const chatId = resolveReaderMessageChatId(message, activeChat);
  return `${chatId}:${Number(floor || 0)}`;
}

function resolveReaderLegacyDepthMode(
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
) {
  return normalizeReaderAnchorMode(anchorMode) ===
    READER_ANCHOR_MODES.TAIL_COMPATIBLE
    ? ""
    : "anchor_abs";
}

function buildReaderDisplaySourceCacheKey(
  config,
  anchorFloor = 0,
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
  options = {},
) {
  const rules = Array.isArray(config?.displayRules) ? config.displayRules : [];
  const ignoreDepthLimits = options.ignoreDepthLimits === true;
  const scopedFloors = normalizeReaderScopedFloors(options.scopedFloors);
  const normalizedAnchorMode = normalizeReaderAnchorMode(anchorMode);
  const legacyReaderDepthMode = ignoreDepthLimits
    ? ""
    : resolveReaderLegacyDepthMode(anchorMode);
  const signature = rules
    .map((rule, index) => {
      const normalized = normalizeDisplayRule(rule, index);
      return [
        normalized.scriptName,
        normalized.findRegex,
        normalized.replaceString,
        normalized.substituteRegex,
        normalized.trimStrings.join("\u0001"),
        normalized.disabled ? 1 : 0,
        normalized.promptOnly ? 1 : 0,
        normalized.markdownOnly ? 1 : 0,
        normalized.runOnEdit === false ? 0 : 1,
        normalized.minDepth ?? "",
        normalized.maxDepth ?? "",
        normalized.readerDepthMode || "",
        normalized.readerMinDepth ?? "",
        normalized.readerMaxDepth ?? "",
        Array.isArray(normalized.placement)
          ? normalized.placement.join(",")
          : "",
      ].join("~");
    })
    .join("||");

  const anchorScope = ignoreDepthLimits
    ? `page:${scopedFloors.join(",") || "all"}`
    : Number(anchorFloor || 0);
  const depthModeScope = ignoreDepthLimits
    ? "page_ignore_depth"
    : legacyReaderDepthMode;
  const anchorModeScope = ignoreDepthLimits
    ? `${normalizedAnchorMode}:page`
    : normalizedAnchorMode;
  return `${anchorModeScope}::${depthModeScope}::${anchorScope}::${signature}`;
}

function resolveReaderTailKeepaliveCount(
  viewSettings = null,
  total = 0,
  anchorFloor = 0,
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
) {
  const settings =
    viewSettings && typeof viewSettings === "object"
      ? viewSettings
      : DEFAULT_CHAT_READER_VIEW_SETTINGS;
  const configuredCount = Math.max(
    0,
    Number(
      settings.fullDisplayCount ??
        DEFAULT_CHAT_READER_VIEW_SETTINGS.fullDisplayCount,
    ),
  );
  if (!configuredCount || !total) {
    return 0;
  }

  if (
    normalizeReaderAnchorMode(anchorMode) ===
    READER_ANCHOR_MODES.TAIL_COMPATIBLE
  ) {
    return configuredCount;
  }

  // Tail keepalive should only help when the reader is already near the tail.
  const resolvedAnchorFloor = Math.min(
    total,
    Math.max(1, Number(anchorFloor || total || 1)),
  );
  return total - resolvedAnchorFloor <= configuredCount ? configuredCount : 0;
}

function resolveReaderRenderBandRanges(
  viewSettings = null,
  total = 0,
  anchorFloor = 0,
) {
  const settings =
    viewSettings && typeof viewSettings === "object"
      ? viewSettings
      : DEFAULT_CHAT_READER_VIEW_SETTINGS;
  const resolvedTotal = Math.max(0, Number(total || 0));
  const resolvedAnchorFloor = Math.min(
    resolvedTotal,
    Math.max(1, Number(anchorFloor || resolvedTotal || 1)),
  );
  const renderNearby = Math.max(
    1,
    Number(
      settings.renderNearbyCount ??
        DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount,
    ),
  );
  const simpleRenderRadius = Math.max(
    0,
    Number(
      settings.simpleRenderRadius ??
        DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius,
    ),
  );

  return {
    renderNearby,
    simpleRenderRadius,
    expansionStartFloor: Math.max(1, resolvedAnchorFloor - renderNearby),
    expansionEndFloor: Math.min(
      resolvedTotal,
      resolvedAnchorFloor + renderNearby,
    ),
    simpleStartFloor: Math.max(1, resolvedAnchorFloor - simpleRenderRadius),
    simpleEndFloor: Math.min(
      resolvedTotal,
      resolvedAnchorFloor + simpleRenderRadius,
    ),
  };
}

function pickNearestReaderFloor(floors = [], targetFloor = 0) {
  const candidates = (Array.isArray(floors) ? floors : [])
    .map((floor) => Number(floor || 0))
    .filter(Boolean);
  if (!candidates.length) {
    return 0;
  }

  const resolvedTargetFloor = Number(
    targetFloor || candidates[candidates.length - 1] || 0,
  );
  return (
    candidates
      .slice()
      .sort(
        (left, right) =>
          Math.abs(left - resolvedTargetFloor) -
            Math.abs(right - resolvedTargetFloor) || right - left,
      )[0] || 0
  );
}

function getRuntimeScanCandidateFloors(
  activeChat,
  viewSettings = null,
  anchorFloor = null,
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
) {
  const messages = Array.isArray(activeChat?.messages)
    ? activeChat.messages
    : [];
  if (!messages.length) return [];

  const total = messages.length;
  const settings =
    viewSettings && typeof viewSettings === "object"
      ? viewSettings
      : DEFAULT_CHAT_READER_VIEW_SETTINGS;
  const resolvedAnchorFloor = Math.min(
    total,
    Math.max(
      1,
      Number(anchorFloor || activeChat?.last_view_floor || total || 1),
    ),
  );
  const tailKeepaliveCount = resolveReaderTailKeepaliveCount(
    settings,
    total,
    resolvedAnchorFloor,
    anchorMode,
  );
  const nearRadius = Math.max(
    Number(
      settings.renderNearbyCount ??
        DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount,
    ),
    Number(
      settings.simpleRenderRadius ??
        DEFAULT_CHAT_READER_VIEW_SETTINGS.simpleRenderRadius,
    ),
  );
  const tailStartFloor = Math.max(1, total - tailKeepaliveCount + 1);
  const nearStartFloor = Math.max(1, resolvedAnchorFloor - nearRadius);
  const nearEndFloor = Math.min(total, resolvedAnchorFloor + nearRadius);
  const candidateSet = new Set();

  if (tailKeepaliveCount > 0) {
    for (let floor = tailStartFloor; floor <= total; floor += 1) {
      candidateSet.add(floor);
    }
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
    .map(
      (candidate, index) =>
        `${index}:${Number(candidate.score || 0)}:${String(candidate.text || "").length}`,
    )
    .join("|");
}

function wrapRuntimeHostsInContainer(container, floor) {
  if (!(container instanceof Element)) return [];

  const wrappedHosts = [];
  let runtimeIndex = 0;

  Array.from(container.querySelectorAll("pre")).forEach((preNode) => {
    const codeNode = preNode.querySelector("code");
    const rawCodeText = String(codeNode?.textContent || "").trim();
    const preText = String(preNode.textContent || "").trim();
    const text = rawCodeText || preText;
    if (!text) return;

    const normalizedText = text
      .replace(/^```(?:html|text|xml)?\s*/i, "")
      .replace(/```$/i, "")
      .trim();
    const analysis = analyzeRuntimeCandidate(normalizedText);
    if (!analysis.isCandidate) return;

    const existingWrapper = preNode.closest(".chat-inline-runtime-wrap");
    if (existingWrapper) {
      const existingHost = existingWrapper.querySelector(
        ".chat-inline-runtime-host",
      );
      if (existingHost instanceof Element) {
        let existingPlaceholder = existingWrapper.querySelector(
          ".chat-inline-runtime-placeholder",
        );
        const existingDisclosure = existingWrapper.querySelector(
          ".chat-inline-runtime-disclosure",
        );
        if (!(existingPlaceholder instanceof Element)) {
          existingPlaceholder = document.createElement("div");
          existingPlaceholder.className = "chat-inline-runtime-placeholder";
          if (existingDisclosure instanceof Element) {
            existingWrapper.insertBefore(
              existingPlaceholder,
              existingDisclosure,
            );
          } else {
            existingWrapper.appendChild(existingPlaceholder);
          }
        }
        existingHost.id = buildRuntimeHostId(floor, runtimeIndex);
        wrappedHosts.push(existingHost);
        runtimeIndex += 1;
      }
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "chat-inline-runtime-wrap";
    const disclosure = document.createElement("details");
    disclosure.className = "chat-inline-runtime-disclosure";
    const summary = document.createElement("summary");
    summary.className = "chat-inline-runtime-summary";
    summary.textContent = "源码";
    const sourceShell = document.createElement("div");
    sourceShell.className = "chat-inline-runtime-source-shell";
    const host = document.createElement("div");
    host.id = buildRuntimeHostId(floor, runtimeIndex);
    host.className = "chat-inline-runtime-host";
    const placeholder = document.createElement("div");
    placeholder.className = "chat-inline-runtime-placeholder";
    preNode.classList.add("chat-inline-runtime-source", "is-collapsible");

    preNode.replaceWith(wrapper);
    wrapper.appendChild(host);
    wrapper.appendChild(placeholder);
    wrapper.appendChild(disclosure);
    disclosure.appendChild(summary);
    disclosure.appendChild(sourceShell);
    sourceShell.appendChild(preNode);
    wrappedHosts.push(host);
    runtimeIndex += 1;
  });

  return wrappedHosts;
}

function setRuntimeWrapperActive(host, active) {
  const wrapper =
    host instanceof Element ? host.closest(".chat-inline-runtime-wrap") : null;
  if (wrapper instanceof Element) {
    wrapper.classList.toggle("is-active", Boolean(active));
  }
}

function clearDeferredRuntimePlaceholder(host) {
  const wrapper =
    host instanceof Element ? host.closest(".chat-inline-runtime-wrap") : null;
  const placeholderHost =
    wrapper instanceof Element
      ? wrapper.querySelector(".chat-inline-runtime-placeholder")
      : null;
  if (placeholderHost instanceof Element) {
    placeholderHost.innerHTML = "";
  }
}

function setDeferredRuntimePlaceholder(host, message, viewSettings) {
  const wrapper =
    host instanceof Element ? host.closest(".chat-inline-runtime-wrap") : null;
  const placeholderHost =
    wrapper instanceof Element
      ? wrapper.querySelector(".chat-inline-runtime-placeholder")
      : null;
  if (placeholderHost instanceof Element) {
    placeholderHost.innerHTML = buildDeferredInstancePlaceholder(
      message,
      viewSettings,
    );
  }
}

function getExecutableMessageFloors(
  activeChat,
  renderedFloorHtmlCache = null,
  viewSettings = null,
  anchorFloor = null,
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
  pageFloors = null,
) {
  if (!activeChat || typeof activeChat !== "object") {
    return [];
  }

  const messages = Array.isArray(activeChat?.messages)
    ? activeChat.messages
    : [];
  if (!messages.length) {
    return [];
  }

  const normalizedPageFloors = normalizeReaderScopedFloors(pageFloors);
  const pageFloorSet = normalizedPageFloors.length
    ? new Set(normalizedPageFloors)
    : null;
  const resolvedAnchorFloor = Number(
    anchorFloor || activeChat?.last_view_floor || messages.length || 1,
  );
  const normalizedAnchorMode = normalizeReaderAnchorMode(anchorMode);
  const scanFloors = pageFloorSet
    ? normalizedPageFloors
    : getRuntimeScanCandidateFloors(
        activeChat,
        viewSettings,
        resolvedAnchorFloor,
        normalizedAnchorMode,
      );
  const floorSet = new Set(scanFloors);
  const key = `${pageFloorSet ? `page:${normalizedPageFloors.join(",")}` : normalizedAnchorMode}|${resolvedAnchorFloor}|${messages
    .filter((message) => floorSet.has(Number(message?.floor || 0)))
    .map(
      (message) =>
        `${Number(message?.floor || 0)}:${getRenderedDisplayHtmlForMessage(message, renderedFloorHtmlCache).length}`,
    )
    .join("|")}`;

  const cache =
    activeChat.runtime_candidate_cache || createRuntimeCandidateCache();
  if (cache.executableFloorsKey === key) {
    return cache.executableFloors;
  }

  const executableFloors = messages
    .filter((message) => floorSet.has(Number(message?.floor || 0)))
    .filter(
      (message) =>
        extractRuntimeCandidatesFromRenderedHtml(
          getRenderedDisplayHtmlForMessage(message, renderedFloorHtmlCache),
        ).length > 0,
    )
    .map((message) => Number(message.floor || 0))
    .filter(Boolean);

  activeChat.runtime_candidate_cache = {
    ...cache,
    executableFloorsKey: key,
    executableFloors,
  };
  return executableFloors;
}

function shouldExecuteMessageSegments(
  message,
  activeChat,
  viewSettings,
  renderedFloorHtmlCache = null,
  anchorFloor = null,
  anchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR,
) {
  const floor = Number(message?.floor || 0);
  if (!floor) return false;
  if (!activeChat || typeof activeChat !== "object") return false;

  const resolvedAnchorFloor = Number(
    anchorFloor || activeChat?.last_view_floor || floor || 1,
  );
  const normalizedAnchorMode = normalizeReaderAnchorMode(anchorMode);
  const candidateFloors = getExecutableMessageFloors(
    activeChat,
    renderedFloorHtmlCache,
    viewSettings,
    resolvedAnchorFloor,
    normalizedAnchorMode,
  );
  if (!candidateFloors.length || !candidateFloors.includes(floor)) {
    return false;
  }

  const depth = Number(
    viewSettings?.instanceRenderDepth ??
      DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth,
  );
  if (depth === 0) {
    return true;
  }

  const prioritizedFloors = candidateFloors
    .slice()
    .sort(
      (left, right) =>
        Math.abs(left - resolvedAnchorFloor) -
          Math.abs(right - resolvedAnchorFloor) || right - left,
    )
    .slice(0, depth);

  return prioritizedFloors.includes(floor);
}

function buildDeferredInstancePlaceholder(message, viewSettings) {
  const floor = Number(message?.floor || 0);
  const depth = Number(
    viewSettings?.instanceRenderDepth ??
      DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth,
  );
  const chipLabel =
    depth === 0 ? "实例待激活" : `实例待激活 · 邻近 ${depth} 层`;
  const floorLabel = floor > 0 ? `#${floor}` : "当前楼层";
  return `<div class="chat-inline-runtime-placeholder-chip" title="${floorLabel} 未进入当前执行范围">${chipLabel}</div>`;
}

function extractRuntimeCandidatesFromContainer(container) {
  if (!(container instanceof Element)) return [];

  const parts = [];
  const seen = new Set();

  Array.from(container.querySelectorAll("pre")).forEach((node) => {
    const codeNode = node.querySelector("code");
    const rawCodeText = String(codeNode?.textContent || "").trim();
    const preText = String(node.textContent || "").trim();
    const text = rawCodeText || preText;
    const normalizedText = text
      .replace(/^```(?:html|text|xml)?\s*/i, "")
      .replace(/```$/i, "")
      .trim();
    if (!text || seen.has(text)) return;
    const analysis = analyzeRuntimeCandidate(normalizedText);
    if (analysis.isCandidate) {
      seen.add(text);
      parts.push({
        type: "app-stage",
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
  const source = String(renderedHtml || "").trim();
  if (!source) return [];

  const probe = document.createElement("div");
  probe.innerHTML = source;
  return extractRuntimeCandidatesFromContainer(probe);
}

function scoreFullPageAppHtml(htmlPayload) {
  const source = String(htmlPayload || "");
  if (!source.trim()) {
    return { score: 0, reasons: ["empty"] };
  }

  let score = 0;
  const reasons = [];
  const add = (value, reason) => {
    score += value;
    reasons.push(reason);
  };

  if (/<!DOCTYPE html/i.test(source) || /<html[\s>]/i.test(source))
    add(2, "full-document");
  if (/id=["']readingContent["']/i.test(source)) add(8, "reading-content-root");
  if (/function\s+processTextContent\s*\(/i.test(source))
    add(8, "process-text-content");
  if (/window\.setTheme\s*=\s*applyTheme/i.test(source))
    add(5, "theme-switcher");
  if (/class=["'][^"']*theme-controls/i.test(source)) add(3, "theme-controls");
  if (/showArgMenu\s*\(/i.test(source)) add(4, "argument-menu");
  if (/Mvu\.getMvuData\s*\(/i.test(source)) add(4, "mvu-data");
  if (/triggerSlash\s*\(/i.test(source)) add(4, "slash-bridge");
  if (
    /class=["'][^"']*dialogue-container/i.test(source) ||
    /createDialogueElement\s*\(/i.test(source)
  )
    add(4, "dialogue-layout");
  if (/class=["'][^"']*grimoire-container/i.test(source))
    add(3, "full-reader-shell");
  if (
    /position:\s*fixed/i.test(source) &&
    /class=["'][^"']*header/i.test(source)
  )
    add(2, "fixed-header");

  if (/sakura-collapsible/i.test(source)) add(-8, "collapsible-widget");
  if (/Sakura\s*-\s*折叠栏/i.test(source)) add(-10, "thinking-widget");
  if (/id=["']raw-markdown["']/i.test(source))
    add(-6, "inline-markdown-widget");
  if (
    /toggleCollapsible\s*\(/i.test(source) &&
    !/processTextContent\s*\(/i.test(source)
  )
    add(-4, "standalone-collapse-control");

  return { score, reasons };
}

const chatReaderVariableSnapshotResolver = createFloorVariableSnapshotResolver({
  checkpointInterval: CHAT_READER_VARIABLE_CHECKPOINT_INTERVAL,
  maxRecentSnapshots: CHAT_READER_VARIABLE_RECENT_CACHE_SIZE,
});

function resolveReaderFloorVariables(
  rawMessages,
  floor,
  activeChat,
  activeCardDetail = null,
) {
  const chat = activeChat && typeof activeChat === "object" ? activeChat : {};
  const metadata =
    chat.metadata && typeof chat.metadata === "object" ? chat.metadata : {};
  return chatReaderVariableSnapshotResolver.resolve({
    chatId: chat.id || chat.chat_id || "",
    rawMessages: Array.isArray(rawMessages) ? rawMessages : [],
    floor,
    metadata,
    cardDetail: activeCardDetail,
  });
}

export function buildReaderRenderCacheKey({
  chatId = "",
  floor = 0,
  variant = "full",
  renderMode = "markdown",
  componentMode = false,
  html = "",
} = {}) {
  return JSON.stringify({
    chatId: String(chatId || ""),
    floor: Number(floor || 0),
    variant: String(variant || "full"),
    renderMode: String(renderMode || "markdown"),
    componentMode: Boolean(componentMode),
    html: String(html || ""),
  });
}

export function shouldDeferReaderRuntimeMount({
  isReaderPageMode = false,
  floor = 0,
  anchorFloor = 0,
  immediateRadius = READER_PAGE_MODE_IMMEDIATE_RUNTIME_RADIUS,
} = {}) {
  if (!isReaderPageMode) return false;
  const resolvedFloor = Number(floor || 0);
  const resolvedAnchorFloor = Number(anchorFloor || 0);
  if (!resolvedFloor || !resolvedAnchorFloor) return false;
  return (
    Math.abs(resolvedFloor - resolvedAnchorFloor) >
    Math.max(0, Number(immediateRadius || 0))
  );
}

function normalizeReaderMessageSource(message) {
  const source = message && typeof message === "object" ? message : {};
  const extra =
    source.extra && typeof source.extra === "object" ? source.extra : {};
  return String(extra.display_text ?? source.mes ?? "");
}

function resolveReaderRegexPlacement(message) {
  const source = message && typeof message === "object" ? message : {};
  const extra =
    source.extra && typeof source.extra === "object" ? source.extra : {};

  if (source.is_user) {
    return READER_REGEX_PLACEMENT.USER_INPUT;
  }
  if (extra.type === "narrator") {
    return READER_REGEX_PLACEMENT.SLASH_COMMAND;
  }
  return READER_REGEX_PLACEMENT.AI_OUTPUT;
}

function isReaderDepthEligibleMessage(message) {
  const source = message && typeof message === "object" ? message : {};
  if (!source.is_system) {
    return true;
  }

  return isReaderRenderableSystemMessage(source);
}

function resolveReaderMessageDepth(rawMessages, floor) {
  const list = Array.isArray(rawMessages) ? rawMessages : [];
  const usableMessages = list
    .map((item, index) => ({ message: item, index: index + 1 }))
    .filter((entry) => isReaderDepthEligibleMessage(entry.message));
  const currentIndex = usableMessages.findIndex(
    (entry) => entry.index === Number(floor || 0),
  );
  if (currentIndex === -1) {
    return null;
  }
  return usableMessages.length - currentIndex - 1;
}

function resolveReaderAnchorMessageIndex(usableMessages, anchorFloor) {
  const targetFloor = Number(anchorFloor || 0);
  if (!targetFloor || !usableMessages.length) return -1;

  const exactIndex = usableMessages.findIndex(
    (entry) => entry.index === targetFloor,
  );
  if (exactIndex !== -1) {
    return exactIndex;
  }

  let fallbackIndex = -1;
  usableMessages.forEach((entry, index) => {
    if (entry.index <= targetFloor) {
      fallbackIndex = index;
    }
  });

  if (fallbackIndex !== -1) {
    return fallbackIndex;
  }

  return usableMessages[0] ? 0 : -1;
}

function createReaderDepthLookup(rawMessages, anchorFloor = 0) {
  const list = Array.isArray(rawMessages) ? rawMessages : [];
  const usableMessages = trimReaderIgnorableTailEntries(
    list
      .map((item, index) => ({ message: item, index: index + 1 }))
      .filter((entry) => isReaderDepthEligibleMessage(entry.message)),
  );
  const floorPositionMap = new Map();
  usableMessages.forEach((entry, position) => {
    floorPositionMap.set(Number(entry.index || 0), position);
  });

  return {
    usableCount: usableMessages.length,
    anchorIndex: resolveReaderAnchorMessageIndex(usableMessages, anchorFloor),
    floorPositionMap,
  };
}

function resolveReaderDepthInfoFromLookup(lookup, floor = 0) {
  const empty = {
    tailDepth: null,
    anchorAbsDepth: null,
    anchorBackwardDepth: null,
    anchorRelativeDepth: null,
  };
  const position =
    lookup?.floorPositionMap instanceof Map
      ? lookup.floorPositionMap.get(Number(floor || 0))
      : undefined;
  if (!Number.isInteger(position)) {
    return empty;
  }

  const tailDepth = Math.max(
    0,
    Number(lookup?.usableCount || 0) - position - 1,
  );
  const anchorIndex = Number.isInteger(lookup?.anchorIndex)
    ? lookup.anchorIndex
    : -1;
  if (anchorIndex < 0) {
    return {
      ...empty,
      tailDepth,
    };
  }

  const relativeDepth = position - anchorIndex;
  return {
    tailDepth,
    anchorAbsDepth: Math.abs(relativeDepth),
    anchorBackwardDepth: relativeDepth <= 0 ? Math.abs(relativeDepth) : null,
    anchorRelativeDepth: relativeDepth,
  };
}

function resolveReaderMessageDepthInfo(rawMessages, floor, anchorFloor = 0) {
  return resolveReaderDepthInfoFromLookup(
    createReaderDepthLookup(rawMessages, anchorFloor),
    floor,
  );
}

function isReaderRenderableSystemMessage(message) {
  const source = message && typeof message === "object" ? message : {};
  if (!source.is_system) return false;

  const extra =
    source.extra && typeof source.extra === "object" ? source.extra : {};
  if (source.name && source.name !== "System") {
    return true;
  }

  return Boolean(extra.display_text);
}

function resolveReaderFormatFlags(message) {
  const source = message && typeof message === "object" ? message : {};
  const extra =
    source.extra && typeof source.extra === "object" ? source.extra : {};

  return {
    encodeTags: false,
    promptBias: "",
    hidePromptBias: !source.is_user && !source.is_system,
    reasoningMarkers: [],
    stripSpeakerPrefix: !source.is_user && !source.is_system,
    speakerName: String(source.name || ""),
    usesSystemUi: Boolean(extra.uses_system_ui),
  };
}

function buildReaderDisplaySource(messageText, config, options = {}) {
  return buildUnifiedDisplaySource(messageText, config, options);
}

function extractSingleMatch(messageText, pattern) {
  if (!messageText || !pattern) return null;
  const regex = compileReaderPattern(pattern, "i");
  if (!regex) return null;
  const match = String(messageText).match(regex);
  if (!match || !match[1]) return null;
  return stripCommonIndent(match[1]);
}

function extractSingleMatchWithIndex(messageText, pattern) {
  if (!messageText || !pattern) return null;
  const regex = compileReaderPattern(pattern, "i");
  if (!regex) return null;
  const match = regex.exec(String(messageText));
  if (!match || !match[1]) return null;
  return {
    text: stripCommonIndent(match[1]),
    index: Number(match.index || 0),
  };
}

function extractTagBlockWithIndex(messageText, tagNames = []) {
  const source = String(messageText || "");
  for (const tagName of tagNames) {
    const regex = new RegExp(`<${tagName}>([\\s\\S]*?)<\/${tagName}>`, "i");
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
  const source = rawMessage && typeof rawMessage === "object" ? rawMessage : {};
  const messageText = normalizeReaderMessageSource(source);
  const treatedAsSystem =
    Boolean(source.is_system) && !isReaderRenderableSystemMessage(source);
  const chatId = String(options.chatId || "");
  const tailDepth = Number.isFinite(options.tailDepth)
    ? Number(options.tailDepth)
    : null;

  return {
    chat_id: chatId,
    floor: Number(floor || 0),
    name: source.name || "Unknown",
    is_user: Boolean(source.is_user),
    is_system: Boolean(source.is_system),
    send_date: source.send_date || "",
    mes: messageText,
    swipes: Array.isArray(source.swipes) ? source.swipes : [],
    extra: source.extra && typeof source.extra === "object" ? source.extra : {},
    content: messageText,
    display_source: treatedAsSystem ? messageText : "",
    display_source_cache_key: "",
    rendered_display_html: "",
    tail_depth: tailDepth,
    time_bar: null,
    summary: null,
    thinking: null,
    choices: [],
    render_segments: [],
  };
}

function resolveReaderMessageChatId(message, activeChat = null) {
  const directChatId =
    message &&
    typeof message === "object" &&
    Object.prototype.hasOwnProperty.call(message, "chat_id")
      ? String(message.chat_id || "")
      : "";
  if (directChatId) {
    return directChatId;
  }

  if (activeChat && typeof activeChat === "object" && activeChat.id) {
    return String(activeChat.id);
  }

  return "chat-preview";
}

function buildCompactPreview(
  message,
  limit = DEFAULT_CHAT_READER_VIEW_SETTINGS.compactPreviewLength,
) {
  const source = message && typeof message === "object" ? message : {};
  const parts = [];

  if (source.time_bar) parts.push(String(source.time_bar));
  if (source.content) parts.push(String(source.content));
  else if (source.mes) parts.push(String(source.mes));
  if (source.summary) parts.push(`总结: ${source.summary}`);

  const compact = parts.join(" · ").replace(/\s+/g, " ").trim();

  if (!compact) return "空内容";
  if (compact.length <= limit) return compact;
  return `${compact.slice(0, limit)}...`;
}

function buildPlaceholderPreview(message, limit = 72) {
  const source = message && typeof message === "object" ? message : {};
  const base = source.time_bar
    ? `${source.time_bar} · ${source.name || ""}`
    : `${source.name || ""}`;
  const compact = buildCompactPreview(source, Math.max(32, limit))
    .replace(/\s+/g, " ")
    .trim();
  if (!compact) {
    return (base || "历史楼层").trim();
  }
  return `${(base || "历史楼层").trim()} · ${compact}`.trim();
}

function ensureReaderDisplaySource(message, config, options = {}) {
  const source = message && typeof message === "object" ? message : {};
  const cacheKey = String(options.cacheKey || "");
  if (
    source.display_source &&
    (!cacheKey || source.display_source_cache_key === cacheKey)
  ) {
    return String(source.display_source || "");
  }

  const messageText = normalizeReaderMessageSource(source);
  const treatedAsSystem =
    Boolean(source.is_system) && !isReaderRenderableSystemMessage(source);
  const nextDisplaySource = treatedAsSystem
    ? messageText
    : buildReaderDisplaySource(messageText, config, options);

  source.display_source = String(nextDisplaySource || "");
  source.display_source_cache_key = cacheKey;
  source.content = source.display_source || messageText;
  return source.display_source;
}

function looksLikeFullPageChatApp(messageText) {
  return scoreFullPageAppHtml(messageText).score >= 8;
}

function buildChatAppCompatContext(
  rawMessages,
  floor,
  rawMessage,
  parsedMessage,
  activeChat,
  activeCardDetail = null,
) {
  const source = rawMessage && typeof rawMessage === "object" ? rawMessage : {};
  const parsed =
    parsedMessage && typeof parsedMessage === "object" ? parsedMessage : {};
  const chat = activeChat && typeof activeChat === "object" ? activeChat : {};
  const floorVariables = resolveReaderFloorVariables(
    rawMessages,
    floor,
    chat,
    activeCardDetail,
  );
  const activeVariables = getActiveMessageVariables(source);
  const statData =
    floorVariables && typeof floorVariables.stat_data === "object"
      ? cloneValue(floorVariables.stat_data)
      : {};

  return {
    latestMessageData: {
      type: "message",
      stat_data: statData,
      message_id: source.id || parsed.floor || "latest",
      message_name: parsed.name || source.name || "",
      name: parsed.name || source.name || "",
      mes: source.mes || "",
      extra: cloneValue(source.extra || {}),
      variables: cloneValue(source.variables || []),
      active_variables: activeVariables,
      merged_variables: cloneValue(floorVariables),
      is_user: Boolean(source.is_user),
      is_system: Boolean(source.is_system),
      chat_id: chat.id || "",
    },
    chat: {
      id: chat.id || "",
      title: chat.title || chat.chat_name || "",
      bound_card_id: chat.bound_card_id || "",
      bound_card_name: chat.bound_card_name || chat.character_name || "",
      variables: getChatMetadataVariables(chat.metadata),
    },
    character: {
      variables: getCardVariables(activeCardDetail),
    },
  };
}

function cloneValue(value) {
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(value);
    } catch (error) {}
  }

  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    return value;
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

function buildSimpleDiffHtml(beforeText, afterText) {
  const beforeLines = String(beforeText || "").split(/\r?\n/);
  const afterLines = String(afterText || "").split(/\r?\n/);
  const max = Math.max(beforeLines.length, afterLines.length);
  const rows = [];

  for (let index = 0; index < max; index += 1) {
    const before = beforeLines[index] ?? "";
    const after = afterLines[index] ?? "";
    const changed = before !== after;

    rows.push(`
            <div class="chat-diff-row${changed ? " is-changed" : ""}">
                <div class="chat-diff-cell chat-diff-cell--before"><span class="chat-diff-prefix">-</span><span>${escapeHtml(before) || "&nbsp;"}</span></div>
                <div class="chat-diff-cell chat-diff-cell--after"><span class="chat-diff-prefix">+</span><span>${escapeHtml(after) || "&nbsp;"}</span></div>
            </div>
        `);
  }

  return rows.join("");
}

function escapeRegExp(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceTextValue(source, query, replacement, caseSensitive) {
  const input = String(source || "");
  const needle = String(query || "");
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

  const regex = new RegExp(escapeRegExp(needle), "gi");
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

    detailSearchQuery: "",
    detailSearchResults: [],
    detailSearchIndex: -1,
    detailBookmarkedOnly: false,

    detailDraftName: "",
    detailDraftNotes: "",
    bookmarkDraft: "",
    jumpFloorInput: "",

    replaceQuery: "",
    replaceReplacement: "",
    replaceCaseSensitive: false,
    replaceUseRegex: false,
    replaceStatus: "",
    readerSaveFeedbackTone: "neutral",

    readerRenderMode: DEFAULT_CHAT_READER_RENDER_PREFS.renderMode,
    readerComponentMode: DEFAULT_CHAT_READER_RENDER_PREFS.componentMode,
    readerBrowseMode: DEFAULT_CHAT_READER_RENDER_PREFS.browseMode,
    readerPageGroupIndex: 0,
    regexConfigOpen: false,
    regexHelpOpen: false,
    regexConfigMobileHeaderHidden: false,
    regexConfigMobileTab: "effective",
    regexConfigTab: "extract",
    selectedActiveRegexRuleIndex: 0,
    selectedDraftRegexRuleIndex: 0,
    regexConfigDraft: normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, {
      fillDefaults: false,
    }),
    regexConfigStatus: "",
    regexTestInput: "",
    regexConfigSourceLabel: "",
    activeCardRegexConfig: normalizeRegexConfig(
      EMPTY_CHAT_READER_REGEX_CONFIG,
      { fillDefaults: false },
    ),
    activeBoundCardDetail: null,
    readerResolvedRegexConfig: normalizeRegexConfig(
      DEFAULT_CHAT_READER_REGEX_CONFIG,
    ),
    readerViewportFloor: 0,
    readerAnchorFloor: 0,
    readerAnchorMode: READER_ANCHOR_MODES.LOCKED_FLOOR,
    readerAnchorSource: READER_ANCHOR_SOURCES.RESTORE,
    readerPageSize: CHAT_READER_PAGE_SIZE,
    readerLoadedPageStart: 0,
    readerLoadedPageEnd: 0,
    readerPageRequestToken: 0,
    readerNavBatchIndex: 0,
    readerNavBatchItems: [],
    readerNavBatchLoading: false,
    readerNavRangeStartFloor: 0,
    readerNavRangeEndFloor: 0,
    readerWindowStartFloor: 1,
    readerWindowEndFloor: 0,
    readerViewSettingsOpen: false,
    readerViewSettings: normalizeViewSettings(
      DEFAULT_CHAT_READER_VIEW_SETTINGS,
    ),
    editingFloor: 0,
    editingMessageDraft: "",
    editingMessageRawDraft: "",
    editingMessagePreviewMode: "parsed",

    linkedCardIdFilter: "",
    linkedCardNameFilter: "",
    pendingOpenChatId: "",

    filePickerMode: "global",
    filePickerPayload: null,

    readerShowLeftPanel: true,
    readerShowRightPanel: true,
    readerMobilePanel: "",
    readerRightTab: "search",
    readerMobileHeaderHidden: false,
    readerLastScrollTop: 0,
    readerAppMode: false,
    readerAppFloor: 0,
    readerAppSignature: "",
    readerAppDebug: {
      checkedCount: 0,
      detectedFloor: 0,
      matchedFloors: [],
      status: "未检测",
    },
    readerRuntimeDebug: {
      enabled: true,
      floor: 0,
      preCount: 0,
      candidateCount: 0,
      wrappedCount: 0,
      scores: [],
      snippets: [],
      status: "未检测",
    },
    chatAppStage: null,
    readerSegmentRegistry: new WeakMap(),
    readerPartStages: new Map(),
    readerScrollRaf: 0,
    readerScrollIdleTimer: 0,
    bindPickerOpen: false,
    bindPickerLoading: false,
    bindPickerSearch: "",
    bindPickerResults: [],
    bindPickerTargetChatId: "",

    get chatList() {
      return this.$store.global.chatList;
    },
    set chatList(val) {
      this.$store.global.chatList = val;
    },
    get chatCurrentPage() {
      return this.$store.global.chatCurrentPage;
    },
    set chatCurrentPage(val) {
      this.$store.global.chatCurrentPage = val;
    },
    get chatTotalItems() {
      return this.$store.global.chatTotalItems;
    },
    set chatTotalItems(val) {
      this.$store.global.chatTotalItems = val;
    },
    get chatTotalPages() {
      return this.$store.global.chatTotalPages;
    },
    set chatTotalPages(val) {
      this.$store.global.chatTotalPages = val;
    },
    get chatSearchQuery() {
      return this.$store.global.chatSearchQuery;
    },
    set chatSearchQuery(val) {
      this.$store.global.chatSearchQuery = val;
    },
    get chatFilterType() {
      return this.$store.global.chatFilterType;
    },
    set chatFilterType(val) {
      this.$store.global.chatFilterType = val;
    },
    get chatFavFilter() {
      return this.$store.global.chatFavFilter;
    },
    set chatFavFilter(val) {
      this.$store.global.chatFavFilter = val;
    },

    get readerTotalMessages() {
      return resolveReaderEffectiveMessageCount(this.activeChat);
    },

    get readerTotalPages() {
      const total = this.readerTotalMessages;
      const pageSize = Math.max(
        1,
        Number(this.readerPageSize || CHAT_READER_PAGE_SIZE),
      );
      return total > 0 ? Math.ceil(total / pageSize) : 0;
    },

    get readerNavBatchSize() {
      return Math.max(
        1,
        Number(this.activeChat?.nav_batch_size || CHAT_READER_NAV_BATCH_SIZE),
      );
    },

    get readerNavTotalBatches() {
      const total = this.readerTotalMessages;
      return total > 0 ? Math.ceil(total / this.readerNavBatchSize) : 0;
    },

    get loadedReaderMessageCount() {
      return Array.isArray(this.activeChat?.raw_messages)
        ? this.activeChat.raw_messages.filter(
            (item) => item && typeof item === "object",
          ).length
        : 0;
    },

    get effectiveReaderBrowseMode() {
      return resolveEffectiveReaderBrowseMode(
        this.readerBrowseMode,
        this.readerTotalMessages,
        this.activeChat,
      );
    },

    get isReaderPageMode() {
      return isReaderPageBrowseMode(this.effectiveReaderBrowseMode);
    },

    get readerPageGroups() {
      return buildReaderPageGroups(
        this.activeChat,
        this.effectiveReaderBrowseMode,
      );
    },

    get currentReaderPageGroup() {
      const groups = this.readerPageGroups;
      if (!groups.length) {
        return null;
      }

      const currentFloor = Number(
        this.readerViewportFloor ||
          this.effectiveReaderAnchorFloor ||
          this.activeChat?.last_view_floor ||
          groups[0]?.anchorFloor ||
          1,
      );
      const exactIndex = groups.findIndex((group) =>
        group.floors.includes(currentFloor),
      );
      const fallbackIndex =
        exactIndex >= 0
          ? exactIndex
          : (groups
              .map((group, index) => ({
                index,
                distance: Math.abs(
                  Number(
                    group.anchorFloor ||
                      group.endFloor ||
                      group.startFloor ||
                      0,
                  ) - currentFloor,
                ),
              }))
              .sort(
                (left, right) =>
                  left.distance - right.distance || left.index - right.index,
              )[0]?.index ?? 0);
      const safeIndex = Math.max(
        0,
        Math.min(
          groups.length - 1,
          Number(this.readerPageGroupIndex || fallbackIndex),
        ),
      );
      return groups[safeIndex] || groups[fallbackIndex] || groups[0] || null;
    },

    get hasPreviousReaderPageGroup() {
      if (!this.isReaderPageMode) return false;
      const currentGroup = this.currentReaderPageGroup;
      return Boolean(currentGroup && Number(currentGroup.index || 0) > 0);
    },

    get hasNextReaderPageGroup() {
      if (!this.isReaderPageMode) return false;
      const groups = this.readerPageGroups;
      const currentGroup = this.currentReaderPageGroup;
      return Boolean(
        groups.length &&
        currentGroup &&
        Number(currentGroup.index || 0) < groups.length - 1,
      );
    },

    get readerBrowseModeLabel() {
      switch (this.effectiveReaderBrowseMode) {
        case READER_BROWSE_MODES.PAGE_NON_USER:
          return "单页·非用户";
        case READER_BROWSE_MODES.PAGE_PAIR:
          return "单页·对话";
        default:
          return "滚动";
      }
    },

    get readerPageGroupStatusText() {
      if (!this.isReaderPageMode) {
        return "滚动浏览";
      }

      const groups = this.readerPageGroups;
      const currentGroup = this.currentReaderPageGroup;
      if (!groups.length || !currentGroup) {
        return "单页浏览";
      }

      const floorLabel =
        currentGroup.floors.length === 1
          ? `#${currentGroup.startFloor}`
          : `#${currentGroup.startFloor}-#${currentGroup.endFloor}`;
      return `${this.readerBrowseModeLabel} ${Number(currentGroup.index || 0) + 1}/${groups.length} · ${floorLabel}`;
    },

    get currentReaderNavBatch() {
      const totalBatches = this.readerNavTotalBatches;
      if (!totalBatches) {
        return null;
      }

      const requestedIndex = Number(this.readerNavBatchIndex || 0);
      const safeIndex = Math.max(0, Math.min(totalBatches - 1, requestedIndex));
      const bounds = this.resolveReaderNavBatchBounds(safeIndex + 1);
      return {
        index: safeIndex,
        batch: safeIndex + 1,
        startFloor: bounds.start,
        endFloor: bounds.end,
      };
    },

    get hasPreviousReaderNavBatch() {
      return Boolean(
        this.currentReaderNavBatch &&
        Number(this.currentReaderNavBatch.index || 0) > 0,
      );
    },

    get hasNextReaderNavBatch() {
      return Boolean(
        this.currentReaderNavBatch &&
        Number(this.currentReaderNavBatch.index || 0) <
          Math.max(0, this.readerNavTotalBatches - 1),
      );
    },

    get readerNavBatchStatusText() {
      const currentBatch = this.currentReaderNavBatch;
      if (!currentBatch) {
        return "No index";
      }
      return `Batch ${currentBatch.batch}/${Math.max(1, this.readerNavTotalBatches)} | #${currentBatch.startFloor}-#${currentBatch.endFloor}`;
    },

    get readerNavBatchSummaryText() {
      const total = this.readerTotalMessages;
      const currentBatch = this.currentReaderNavBatch;
      if (!total || !currentBatch) {
        return "No floor index loaded";
      }
      return `Total ${total} floors | Index #${currentBatch.startFloor}-#${currentBatch.endFloor}`;
    },

    get effectiveReaderAnchorFloor() {
      const total = this.readerTotalMessages;
      if (!total) return 0;
      if (this.readerAnchorMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE) {
        return total;
      }
      const committedFloor = Number(this.readerAnchorFloor || 0);
      if (committedFloor > 0) {
        return Math.min(total, Math.max(1, committedFloor));
      }
      const fallback = Number(
        this.readerViewportFloor ||
          this.activeChat?.last_view_floor ||
          total ||
          1,
      );
      return Math.min(total, Math.max(1, fallback));
    },

    get readerAnchorStatusText() {
      if (!this.activeChat) return "未定位";
      const floor = Number(this.effectiveReaderAnchorFloor || 0);
      if (!floor) return "未定位";
      const modeLabel =
        this.readerAnchorMode === READER_ANCHOR_MODES.LOCKED_FLOOR
          ? "锁定楼层"
          : this.readerAnchorMode === READER_ANCHOR_MODES.SEMI_AUTO
            ? "半自动迁移"
            : "末楼兼容";
      return `#${floor} · ${modeLabel}`;
    },

    get readerShellStatusText() {
      if (this.replaceStatus) {
        return this.replaceStatus;
      }
      if (this.regexConfigStatus) {
        return this.regexConfigStatus;
      }
      if (!this.activeChat) {
        return "聊天阅读器已关闭";
      }
      if (this.detailLoading) {
        return "正在读取聊天内容...";
      }
      return `阅读定位 ${this.readerViewportStatusText} · 锚点 ${this.readerAnchorStatusText}`;
    },

    get readerShellStatusLineText() {
      if (!this.activeChat) {
        return "未载入聊天";
      }
      const count = Number(
        this.activeChat?.message_count || this.readerTotalMessages || 0,
      );
      return `${count} 层 · 阅读定位 ${this.readerViewportStatusText} · 锚点 ${this.readerAnchorStatusText}`;
    },

    get readerMobilePanelCloseLabel() {
      if (this.readerResponsiveMode !== "mobile") {
        return "关闭检索栏";
      }
      if (this.readerMobilePanel === "tools") {
        return "关闭工具抽屉";
      }
      if (this.readerMobilePanel === "navigator") {
        return "关闭楼层导航";
      }
      return "关闭全文搜索";
    },

    get readerResponsiveMode() {
      const deviceType = this.$store.global.deviceType;
      if (deviceType === "mobile") {
        return "mobile";
      }
      if (deviceType === "tablet") {
        return "tablet";
      }
      return "desktop";
    },

    get readerDesktopRightPanelOpen() {
      return this.readerShowRightPanel;
    },

    get readerCenterPaneStyle() {
      const mode = this.readerResponsiveMode;
      if (mode === "mobile") {
        return "grid-column: 1;";
      }

      if (mode === "tablet") {
        return this.readerShowLeftPanel ? "grid-column: 2;" : "grid-column: 1;";
      }

      if (this.readerShowLeftPanel && this.readerDesktopRightPanelOpen) {
        return "grid-column: 2;";
      }

      if (this.readerShowLeftPanel) {
        return "grid-column: 2;";
      }

      return "grid-column: 1;";
    },

    get readerLeftPaneStyle() {
      if (!this.readerShowLeftPanel) {
        return "display: none;";
      }

      if (
        this.readerResponsiveMode === "desktop" ||
        this.readerResponsiveMode === "tablet"
      ) {
        return "";
      }

      return "grid-column: 1;";
    },

    get readerRightPaneStyle() {
      if (!this.readerShowRightPanel) {
        return `${this.readerResponsiveMode === "desktop" ? "grid-column: 2;" : this.readerResponsiveMode === "tablet" ? "grid-column: 2;" : "grid-column: 1;"} display: none;`;
      }

      const mode = this.readerResponsiveMode;
      if (mode === "mobile") {
        return "grid-column: 1;";
      }

      if (mode === "tablet") {
        return "grid-column: 2;";
      }

      if (this.readerShowLeftPanel && this.readerDesktopRightPanelOpen) {
        return "grid-column: 3;";
      }

      return "grid-column: 2;";
    },

    get readerViewportStatusText() {
      if (!this.activeChat) return "未定位";
      const total = Number(
        this.readerTotalMessages || this.activeChat?.message_count || 0,
      );
      const floor = Math.min(
        Math.max(
          1,
          Number(
            this.readerViewportFloor ||
              this.activeChat?.last_view_floor ||
              total ||
              0,
          ),
        ),
        Math.max(1, total || 1),
      );
      if (!floor) return "未定位";
      return `#${floor}`;
    },

    setReaderFeedbackTone(tone = "neutral") {
      if (tone === "error" || tone === "danger" || tone === "success") {
        this.readerSaveFeedbackTone = tone;
        return;
      }
      this.readerSaveFeedbackTone = "neutral";
    },

    get visibleDetailMessages() {
      if (!this.activeChat || !Array.isArray(this.activeChat.messages))
        return [];

      const bookmarksRef = Array.isArray(this.activeChat.bookmarks)
        ? this.activeChat.bookmarks
        : null;
      const bookmarks = bookmarksRef || [];
      const bookmarkSet = new Set(
        bookmarks.map((item) => Number(item.floor || 0)).filter(Boolean),
      );
      const total = this.activeChat.messages.length;
      const anchorFloor = Number(
        this.effectiveReaderAnchorFloor ||
          this.activeChat.last_view_floor ||
          total ||
          1,
      );
      const browseMode = this.effectiveReaderBrowseMode;
      const pageGroups = this.readerPageGroups;
      const currentPageGroup = this.currentReaderPageGroup;
      const pageFloorSet = currentPageGroup
        ? new Set(currentPageGroup.floors)
        : null;
      const windowStartFloor = Math.max(
        1,
        Number(this.readerWindowStartFloor || 1),
      );
      const windowEndFloor = Math.min(
        total,
        Math.max(windowStartFloor, Number(this.readerWindowEndFloor || total)),
      );
      const rawTailKeepaliveCount = resolveReaderTailKeepaliveCount(
        this.readerViewSettings,
        total,
        anchorFloor,
        this.readerAnchorMode,
      );
      const renderBands = resolveReaderRenderBandRanges(
        this.readerViewSettings,
        total,
        anchorFloor,
      );
      const renderNearby = renderBands.renderNearby;
      const rawSimpleRenderRadius = renderBands.simpleRenderRadius;
      const rawHiddenHistoryThreshold = Number(
        this.readerViewSettings.hiddenHistoryThreshold ??
          DEFAULT_CHAT_READER_VIEW_SETTINGS.hiddenHistoryThreshold,
      );
      const tailKeepaliveCount = rawTailKeepaliveCount;
      const simpleRenderRadius = rawSimpleRenderRadius;
      const hiddenHistoryThreshold = rawHiddenHistoryThreshold;
      const compactPreviewLength = Number(
        this.readerViewSettings.compactPreviewLength ??
          DEFAULT_CHAT_READER_VIEW_SETTINGS.compactPreviewLength,
      );
      const tailKeepaliveStartFloor =
        tailKeepaliveCount > 0
          ? Math.max(1, total - tailKeepaliveCount + 1)
          : total + 1;
      const expansionStartFloor = renderBands.expansionStartFloor;
      const expansionEndFloor = renderBands.expansionEndFloor;
      const simpleStartFloor = renderBands.simpleStartFloor;
      const simpleEndFloor = renderBands.simpleEndFloor;
      const cache = getReaderVisibleMessagesCache(this);

      if (
        cache &&
        cache.messagesRef === this.activeChat.messages &&
        cache.bookmarksRef === bookmarksRef &&
        cache.detailBookmarkedOnly === this.detailBookmarkedOnly &&
        cache.browseMode === browseMode &&
        cache.pageGroupId === String(currentPageGroup?.id || "") &&
        cache.currentFloor === anchorFloor &&
        cache.anchorMode === this.readerAnchorMode &&
        cache.anchorSource === this.readerAnchorSource &&
        cache.windowStartFloor === windowStartFloor &&
        cache.windowEndFloor === windowEndFloor &&
        cache.fullCount === tailKeepaliveCount &&
        cache.renderNearby === renderNearby &&
        cache.simpleRenderRadius === simpleRenderRadius &&
        cache.expansionStartFloor === expansionStartFloor &&
        cache.expansionEndFloor === expansionEndFloor &&
        cache.simpleStartFloor === simpleStartFloor &&
        cache.simpleEndFloor === simpleEndFloor &&
        cache.hiddenHistoryThreshold === hiddenHistoryThreshold &&
        cache.compactPreviewLength === compactPreviewLength
      ) {
        return cache.result;
      }

      let messages = this.activeChat.messages
        .slice(Math.max(0, windowStartFloor - 1), windowEndFloor)
        .filter((message) => {
          if (!pageFloorSet) return true;
          return pageFloorSet.has(Number(message?.floor || 0));
        })
        .map((message) => ({
          ...message,
          is_bookmarked: bookmarkSet.has(Number(message.floor || 0)),
          compact_preview: "",
          placeholder_preview: "",
        }));

      messages = messages.map((message) => {
        const floor = Number(message.floor || 0);
        const runtimeConfig = normalizeRegexConfig(
          message.__readerRegexConfig ||
            this.readerResolvedRegexConfig ||
            this.activeRegexConfig,
        );
        const rawMessages = Array.isArray(this.activeChat?.raw_messages)
          ? this.activeChat.raw_messages
          : [];
        const rawMessage = floor > 0 ? rawMessages[floor - 1] : null;
        const depthInfo = this.resolveReaderDepthInfoForFloor(
          floor,
          rawMessage,
          runtimeConfig,
          anchorFloor,
        );
        message.__readerRegexConfig = runtimeConfig;
        message.__readerDepthInfo = depthInfo;
        const resolvedDisplaySource = this.ensureMessageDisplaySource(message);
        const isTailKeepaliveFloor =
          tailKeepaliveCount > 0 && floor >= tailKeepaliveStartFloor;
        const inFullBand =
          floor >= expansionStartFloor && floor <= expansionEndFloor;
        const inSimpleBand =
          floor >= simpleStartFloor && floor <= simpleEndFloor;
        const floorDistance = Math.abs(floor - anchorFloor);
        const shouldHideHistory =
          hiddenHistoryThreshold > 0 &&
          !isTailKeepaliveFloor &&
          floorDistance > hiddenHistoryThreshold;

        let renderTier = "hidden";
        if (pageFloorSet) {
          renderTier = "full";
        } else if (isTailKeepaliveFloor || inFullBand) {
          renderTier = "full";
        } else if (inSimpleBand) {
          renderTier = "simple";
        } else if (!shouldHideHistory) {
          renderTier = "compact";
        }

        const enhancementPolicy = buildReaderEnhancementPolicy(
          renderTier,
          message.__readerEnhancementMeta || {},
          {
            anchorFloor,
            floor,
            floorDistance,
            browseMode,
          },
        );
        enhancementPolicy.metaFlags = Array.isArray(enhancementPolicy.metaFlags)
          ? enhancementPolicy.metaFlags
          : enhancementPolicy.showMetaFlags
            ? ["summary"]
            : [];

        return {
          ...message,
          compact_preview: buildCompactPreview(
            {
              ...message,
              content:
                resolvedDisplaySource || message.content || message.mes || "",
            },
            compactPreviewLength,
          ),
          placeholder_preview: buildPlaceholderPreview({
            ...message,
            content:
              resolvedDisplaySource || message.content || message.mes || "",
          }),
          render_tier: renderTier,
          is_full_display: renderTier !== "hidden",
          should_render_full: renderTier === "full",
          should_render_simple: renderTier === "simple",
          should_render_placeholder: renderTier === "hidden",
          is_compact_display: renderTier === "compact",
          __readerEnhancementPolicy: enhancementPolicy,
          meta_flags: enhancementPolicy.metaFlags,
          reasoning_mode: enhancementPolicy.reasoningMode,
          code_mode: enhancementPolicy.codeMode,
        };
      });

      if (this.detailBookmarkedOnly) {
        messages = messages.filter((item) => item.is_bookmarked);
      }

      readerVisibleMessagesCacheMap.set(this, {
        messagesRef: this.activeChat.messages,
        bookmarksRef,
        detailBookmarkedOnly: this.detailBookmarkedOnly,
        browseMode,
        pageGroupId: String(currentPageGroup?.id || ""),
        currentFloor: anchorFloor,
        anchorMode: this.readerAnchorMode,
        anchorSource: this.readerAnchorSource,
        windowStartFloor,
        windowEndFloor,
        fullCount: tailKeepaliveCount,
        renderNearby,
        simpleRenderRadius,
        expansionStartFloor,
        expansionEndFloor,
        simpleStartFloor,
        simpleEndFloor,
        hiddenHistoryThreshold,
        compactPreviewLength,
        result: messages,
      });

      return messages;
    },

    getChatOwnedRegexConfig(chat = null) {
      const target = chat || this.activeChat;
      const chatOverride = target?.metadata?.reader_regex_config || null;
      if (!chatOverride) {
        return normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, {
          fillDefaults: false,
        });
      }
      return markRegexConfigRuleSource(chatOverride, "chat");
    },

    resolveEffectiveRegexConfig(chatConfig = null) {
      const cardDefault = hasCustomRegexConfig(this.activeCardRegexConfig)
        ? markRegexConfigRuleSource(this.activeCardRegexConfig, "card")
        : normalizeRegexConfig(EMPTY_CHAT_READER_REGEX_CONFIG, {
            fillDefaults: false,
          });
      const chatOverride = hasCustomRegexConfig(chatConfig)
        ? markRegexConfigRuleSource(chatConfig, "chat")
        : null;
      return chatOverride
        ? mergeRegexConfigs(cardDefault, chatOverride)
        : normalizeRegexConfig(cardDefault);
    },

    get savedChatRegexConfig() {
      return this.getChatOwnedRegexConfig();
    },

    get activeRegexConfig() {
      return this.resolveEffectiveRegexConfig(this.savedChatRegexConfig);
    },

    get regexDraftResolvedConfig() {
      return this.resolveEffectiveRegexConfig(this.regexConfigDraft);
    },

    get activeReaderRegexConfig() {
      return buildReaderEffectiveRegexConfig(this.activeRegexConfig);
    },

    get regexDraftResolvedReaderConfig() {
      return buildReaderEffectiveRegexConfig(this.regexDraftResolvedConfig);
    },

    get regexWorkbenchEffectiveConfig() {
      return this.regexConfigOpen
        ? this.regexDraftResolvedConfig
        : this.activeRegexConfig;
    },

    get activeRegexDisplayRules() {
      return decorateRegexDisplayRules(
        buildReaderInspectorRegexConfig(this.regexWorkbenchEffectiveConfig),
      );
    },

    get regexDraftResolvedDisplayRules() {
      return decorateRegexDisplayRules(
        buildReaderInspectorRegexConfig(this.regexDraftResolvedConfig),
      );
    },

    get selectedActiveRegexRuleIndexSafe() {
      if (!this.activeRegexDisplayRules.length) return -1;
      const normalizedIndex = Number(this.selectedActiveRegexRuleIndex);
      if (!Number.isFinite(normalizedIndex) || normalizedIndex < 0) return 0;
      return Math.min(normalizedIndex, this.activeRegexDisplayRules.length - 1);
    },

    get selectedActiveRegexRule() {
      const index = this.selectedActiveRegexRuleIndexSafe;
      if (index < 0) return null;
      return this.activeRegexDisplayRules[index] || null;
    },

    get selectedActiveRegexRuleDetail() {
      const index = this.selectedActiveRegexRuleIndexSafe;
      if (index < 0) return null;
      return inspectRegexDisplayRule(this.selectedActiveRegexRule, index);
    },

    get selectedDraftRegexRuleIndexSafe() {
      if (!this.regexDraftDisplayRules.length) return -1;
      const normalizedIndex = Number(this.selectedDraftRegexRuleIndex);
      if (!Number.isFinite(normalizedIndex) || normalizedIndex < 0) return 0;
      return Math.min(normalizedIndex, this.regexDraftDisplayRules.length - 1);
    },

    get selectedDraftRegexRule() {
      const index = this.selectedDraftRegexRuleIndexSafe;
      if (index < 0) return null;
      return this.regexDraftDisplayRules[index] || null;
    },

    get selectedDraftRegexRuleDetail() {
      const index = this.selectedDraftRegexRuleIndexSafe;
      if (index < 0) return null;
      return inspectRegexDisplayRule(this.selectedDraftRegexRule, index);
    },

    get savedChatRegexRuleCount() {
      return decorateRegexDisplayRules(this.savedChatRegexConfig, "chat")
        .length;
    },

    get savedChatRegexDeletionCount() {
      return decorateRegexDisplayRules(this.savedChatRegexConfig, "chat", {
        includeDeleted: true,
      }).filter((rule) => rule.deleted).length;
    },

    get cardRegexRuleCount() {
      return decorateRegexDisplayRules(this.activeCardRegexConfig, "card")
        .length;
    },

    get regexEffectiveRuleCount() {
      return this.activeRegexDisplayRules.length;
    },

    get regexEffectiveDisabledCount() {
      return this.activeRegexDisplayRules.filter((rule) => rule.disabled)
        .length;
    },

    get regexEffectiveSourceSummary() {
      return summarizeRegexRuleSources(this.activeRegexDisplayRules);
    },

    get regexDraftOutcomeSummary() {
      const total = this.regexDraftResolvedDisplayRules.length;
      const runnableCount = Array.isArray(
        this.regexDraftResolvedReaderConfig?.displayRules,
      )
        ? this.regexDraftResolvedReaderConfig.displayRules.length
        : 0;
      const disabledCount = this.regexDraftResolvedDisplayRules.filter(
        (rule) => rule.disabled,
      ).length;
      const deletedCount = this.regexDraftDeletionCount;
      if (!total) {
        return deletedCount > 0
          ? `保存后当前聊天不会使用显示替换规则（含 ${deletedCount} 个删除覆盖）。`
          : "保存后当前聊天不会使用显示替换规则。";
      }
      const summary = summarizeRegexRuleSources(
        this.regexDraftResolvedDisplayRules,
      );
      const extras = [];
      if (disabledCount > 0) extras.push(`已禁用 ${disabledCount} 条`);
      if (deletedCount > 0) extras.push(`删除覆盖 ${deletedCount} 条`);
      return `保存后规则面板显示 ${total} 条，实际参与替换 ${runnableCount} 条${summary ? `：${summary}` : ""}${extras.length ? `（${extras.join("，")}）` : ""}`;
    },

    get regexStateCards() {
      const hasBoundCard = Boolean(this.activeChat?.bound_card_id);
      const hasSavedChatRules = hasCustomRegexConfig(this.savedChatRegexConfig);
      const hasDraftRules = hasCustomRegexConfig(this.regexConfigDraft);
      const effectiveState =
        this.regexEffectiveDisabledCount > 0
          ? `${this.regexEffectiveRuleCount} 条 / 禁用 ${this.regexEffectiveDisabledCount}`
          : `${this.regexEffectiveRuleCount} 条`;
      const savedState = hasSavedChatRules
        ? `${this.savedChatRegexRuleCount} 条${this.savedChatRegexDeletionCount > 0 ? ` / 删除 ${this.savedChatRegexDeletionCount}` : ""}`
        : "未保存";
      const draftState = `${this.regexDraftRuleCount} 条${this.regexDraftDeletionCount > 0 ? ` / 删除 ${this.regexDraftDeletionCount}` : ""}`;
      const effectiveDetail = this.regexConfigOpen
        ? "这里实时预览当前草稿合并后的显示替换规则，保存前不会写回聊天文件。"
        : "这里显示当前聊天合并后的显示替换规则，已禁用项也会保留在列表里并单独标记。";
      return [
        {
          id: "effective",
          title: "当前生效",
          state: effectiveState,
          detail: this.regexEffectiveRuleCount
            ? `${effectiveDetail}${this.regexEffectiveSourceSummary || ""}`
            : "当前聊天还没有生效的显示替换规则。",
          tone: this.regexEffectiveRuleCount ? "accent" : "muted",
        },
        {
          id: "card",
          title: "角色卡继承",
          state: hasBoundCard
            ? `${this.cardRegexRuleCount} 条`
            : "未绑定角色卡",
          detail: hasBoundCard
            ? this.cardRegexRuleCount
              ? "角色卡里的规则会自动参与当前聊天解析。"
              : "已绑定角色卡，但卡内没有可继承的规则。"
            : "当前聊天未绑定角色卡。",
          tone: this.cardRegexRuleCount ? "success" : "muted",
        },
        {
          id: "saved",
          title: "聊天已保存",
          state: savedState,
          detail: hasSavedChatRules
            ? this.savedChatRegexDeletionCount > 0
              ? `这些是已经写入当前聊天文件的自定义规则，另外还有 ${this.savedChatRegexDeletionCount} 个删除覆盖。`
              : "这些是已经写入当前聊天文件的自定义规则。"
            : "当前聊天没有已保存的自定义规则。",
          tone: hasSavedChatRules ? "info" : "muted",
        },
        {
          id: "draft",
          title: "当前草稿",
          state: draftState,
          detail: hasDraftRules
            ? this.regexDraftOutcomeSummary
            : "当前没有聊天自定义草稿，保存时会直接继承角色卡规则。",
          tone: hasDraftRules ? "accent" : "muted",
        },
      ];
    },

    get activeReaderAssetBase() {
      const chat = this.activeChat || {};
      const folder =
        chat.bound_card_resource_folder || chat.resource_folder || "";
      if (!folder) {
        return `${window.location.origin}/`;
      }
      return `${window.location.origin}/resources_file/${encodeURIComponent(folder)}/`;
    },

    get activeAppMessage() {
      if (
        !this.activeChat ||
        !Array.isArray(this.activeChat.messages) ||
        !this.readerAppFloor
      ) {
        return null;
      }
      return (
        this.activeChat.messages.find(
          (item) =>
            Number(item.floor || 0) === Number(this.readerAppFloor || 0),
        ) || null
      );
    },

    get executableMessageFloors() {
      const pageFloors = this.isReaderPageMode
        ? this.getCurrentReaderPageFloors()
        : null;
      return getExecutableMessageFloors(
        this.activeChat,
        this.renderedFloorHtmlCache,
        this.readerViewSettings,
        this.effectiveReaderAnchorFloor,
        this.readerAnchorMode,
        pageFloors,
      );
    },

    get hasAppFloorNavigation() {
      return this.executableMessageFloors.length > 1;
    },

    get renderedFloorHtmlCache() {
      if (!this._renderedFloorHtmlCache) {
        this._renderedFloorHtmlCache = new Map();
        this._readerRenderedDisplayCache = new Map();
      }
      return this._renderedFloorHtmlCache;
    },

    get readerRenderedDisplayCache() {
      if (!this._readerRenderedDisplayCache) {
        this._readerRenderedDisplayCache = new Map();
      }
      return this._readerRenderedDisplayCache;
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

    buildReaderManifestChat(chat) {
      const source = chat && typeof chat === "object" ? chat : {};
      const messageIndex = trimReaderIgnorableTailEntries(
        Array.isArray(source.message_index) ? source.message_index : [],
      );
      const total = resolveReaderEffectiveMessageCount({
        ...source,
        message_index: messageIndex,
      });

      return {
        ...source,
        source_message_count: Math.max(
          0,
          Number(source.message_count || 0) || messageIndex.length,
        ),
        message_count: total,
        end_floor: total,
        page_size: Math.max(
          1,
          Number(source.page_size || CHAT_READER_PAGE_SIZE),
        ),
        nav_batch_size: Math.max(
          1,
          Number(source.nav_batch_size || CHAT_READER_NAV_BATCH_SIZE),
        ),
        message_index_included: source.message_index_included !== false,
        message_index_total: Math.max(
          total,
          Number(source.message_index_total || 0),
        ),
        message_index_truncated: Boolean(source.message_index_truncated),
        message_index: messageIndex,
        messages: createReaderManifestMessages(messageIndex, total),
        raw_messages: Array.from({ length: total }, () => null),
        runtime_candidate_cache: createRuntimeCandidateCache(),
      };
    },

    resetReaderLoadedPages(resetMessages = true) {
      const total = this.readerTotalMessages;
      this.readerLoadedPageStart = 0;
      this.readerLoadedPageEnd = 0;
      this.readerWindowStartFloor = total > 0 ? 1 : 0;
      this.readerWindowEndFloor = 0;
      this._renderedFloorHtmlCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      this._readerDepthLookupCache = null;

      if (this.activeChat) {
        this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
        if (resetMessages) {
          this.activeChat.messages = createReaderManifestMessages(
            this.activeChat.message_index,
            total,
          );
          this.activeChat.raw_messages = Array.from(
            { length: total },
            () => null,
          );
        }
      }

      resetReaderVisibleMessagesCache(this);
    },

    updateReaderWindowFromLoadedPages() {
      if (
        !this.activeChat ||
        !this.readerLoadedPageStart ||
        !this.readerLoadedPageEnd
      ) {
        this.readerWindowStartFloor = this.readerTotalMessages > 0 ? 1 : 0;
        this.readerWindowEndFloor = 0;
        resetReaderVisibleMessagesCache(this);
        return {
          start: this.readerWindowStartFloor,
          end: this.readerWindowEndFloor,
        };
      }

      const firstBounds = this.resolveReaderPageBounds(
        this.readerLoadedPageStart,
      );
      const lastBounds = this.resolveReaderPageBounds(this.readerLoadedPageEnd);
      this.readerWindowStartFloor = firstBounds.start;
      this.readerWindowEndFloor = lastBounds.end;
      resetReaderVisibleMessagesCache(this);
      return {
        start: this.readerWindowStartFloor,
        end: this.readerWindowEndFloor,
      };
    },

    resolveReaderPageForFloor(floor = 1) {
      const total = this.readerTotalMessages;
      if (!total) return 0;
      const pageSize = Math.max(
        1,
        Number(this.readerPageSize || CHAT_READER_PAGE_SIZE),
      );
      const targetFloor = Math.min(total, Math.max(1, Number(floor || 1)));
      return Math.ceil(targetFloor / pageSize);
    },

    resolveReaderPageBounds(pageNo = 1) {
      const total = this.readerTotalMessages;
      if (!total) {
        return { page: 0, start: 0, end: 0 };
      }

      const totalPages = this.readerTotalPages;
      const page = Math.min(totalPages, Math.max(1, Number(pageNo || 1)));
      const pageSize = Math.max(
        1,
        Number(this.readerPageSize || CHAT_READER_PAGE_SIZE),
      );
      const start = (page - 1) * pageSize + 1;
      return {
        page,
        start,
        end: Math.min(total, start + pageSize - 1),
      };
    },

    resolveReaderNavBatchForFloor(floor = 1) {
      const total = this.readerTotalMessages;
      if (!total) return 0;
      const batchSize = Math.max(
        1,
        Number(this.readerNavBatchSize || CHAT_READER_NAV_BATCH_SIZE),
      );
      const targetFloor = Math.min(total, Math.max(1, Number(floor || 1)));
      return Math.ceil(targetFloor / batchSize);
    },

    resolveReaderNavBatchBounds(batchNo = 1) {
      const total = this.readerTotalMessages;
      if (!total) {
        return { batch: 0, start: 0, end: 0 };
      }

      const totalBatches = this.readerNavTotalBatches;
      const batch = Math.min(totalBatches, Math.max(1, Number(batchNo || 1)));
      const batchSize = Math.max(
        1,
        Number(this.readerNavBatchSize || CHAT_READER_NAV_BATCH_SIZE),
      );
      const start = (batch - 1) * batchSize + 1;
      return {
        batch,
        start,
        end: Math.min(total, start + batchSize - 1),
      };
    },

    resolveReaderPagesAroundFloor(floor = 1) {
      const targetPage = this.resolveReaderPageForFloor(floor);
      const totalPages = this.readerTotalPages;
      if (!targetPage || !totalPages) return [];

      const startPage = Math.max(
        1,
        targetPage - CHAT_READER_PAGE_NEIGHBOR_COUNT,
      );
      const endPage = Math.min(
        totalPages,
        targetPage + CHAT_READER_PAGE_NEIGHBOR_COUNT,
      );
      const pages = [];
      for (let page = startPage; page <= endPage; page += 1) {
        pages.push(page);
      }
      return pages;
    },

    getReaderRawMessageForFloor(floor = 0) {
      const targetFloor = Number(floor || 0);
      if (!targetFloor || !Array.isArray(this.activeChat?.raw_messages)) {
        return null;
      }
      const item = this.activeChat.raw_messages[targetFloor - 1];
      return item && typeof item === "object" ? item : null;
    },

    getReaderMessageForFloor(floor = 0) {
      const targetFloor = Number(floor || 0);
      if (!targetFloor || !Array.isArray(this.activeChat?.messages)) {
        return null;
      }
      const item = this.activeChat.messages[targetFloor - 1];
      return item && typeof item === "object" ? item : null;
    },

    resolveReaderPageGroupIndexForFloor(floor = 0, groups = null) {
      const resolvedGroups =
        Array.isArray(groups) && groups.length ? groups : this.readerPageGroups;
      if (!resolvedGroups.length) {
        return -1;
      }

      const targetFloor = Number(
        floor ||
          this.readerViewportFloor ||
          this.effectiveReaderAnchorFloor ||
          resolvedGroups[0]?.anchorFloor ||
          resolvedGroups[0]?.startFloor ||
          1,
      );
      const exactIndex = resolvedGroups.findIndex((group) =>
        group.floors.includes(targetFloor),
      );
      if (exactIndex >= 0) {
        return exactIndex;
      }

      return (
        resolvedGroups
          .map((group, index) => ({
            index,
            distance: Math.abs(
              Number(
                group.anchorFloor || group.endFloor || group.startFloor || 0,
              ) - targetFloor,
            ),
          }))
          .sort(
            (left, right) =>
              left.distance - right.distance || left.index - right.index,
          )[0]?.index ?? 0
      );
    },

    syncReaderPageGroupForFloor(floor = 0, options = {}) {
      if (!this.isReaderPageMode) {
        this.readerPageGroupIndex = 0;
        resetReaderVisibleMessagesCache(this);
        return -1;
      }

      const groups = this.readerPageGroups;
      if (!groups.length) {
        this.readerPageGroupIndex = 0;
        resetReaderVisibleMessagesCache(this);
        return -1;
      }

      const nextIndex = this.resolveReaderPageGroupIndexForFloor(floor, groups);
      const safeIndex = Math.max(0, Math.min(groups.length - 1, nextIndex));
      const targetGroup = groups[safeIndex];
      this.readerPageGroupIndex = safeIndex;

      if (options.syncAnchor !== false && targetGroup) {
        const targetFloor = Number(
          options.anchorFloor ||
            floor ||
            targetGroup.anchorFloor ||
            targetGroup.endFloor ||
            targetGroup.startFloor ||
            0,
        );
        if (targetFloor > 0) {
          this.readerViewportFloor = targetFloor;
          this.readerAnchorFloor = targetFloor;
        }
        if (options.source) {
          this.readerAnchorSource = options.source;
        }
      }

      resetReaderVisibleMessagesCache(this);
      return safeIndex;
    },

    getCurrentReaderPageFloors(group = null) {
      if (!this.isReaderPageMode) {
        return [];
      }
      const targetGroup =
        group && typeof group === "object"
          ? group
          : this.currentReaderPageGroup;
      return normalizeReaderScopedFloors(targetGroup?.floors);
    },

    isReaderCurrentPageFloor(floor = 0, group = null) {
      const targetFloor = Number(floor || 0);
      if (!targetFloor) {
        return false;
      }
      return this.getCurrentReaderPageFloors(group).includes(targetFloor);
    },

    resolveReaderPageDepthOverride(floor = 0, group = null) {
      const scopedFloors = this.getCurrentReaderPageFloors(group);
      if (!scopedFloors.length) {
        return {
          ignoreDepthLimits: false,
          scopedFloors: [],
        };
      }

      const targetFloor = Number(floor || 0);
      return {
        ignoreDepthLimits:
          targetFloor > 0 ? scopedFloors.includes(targetFloor) : true,
        scopedFloors,
      };
    },

    resolveReaderDepthLookup(anchorFloor = null, messages = null) {
      const sourceMessages = Array.isArray(messages)
        ? messages
        : Array.isArray(this.activeChat?.messages)
          ? this.activeChat.messages
          : [];
      const resolvedAnchorFloor = Number(
        anchorFloor ||
          this.effectiveReaderAnchorFloor ||
          this.readerViewportFloor ||
          this.activeChat?.last_view_floor ||
          0,
      );
      const cached = this._readerDepthLookupCache;
      if (
        cached &&
        cached.messagesRef === sourceMessages &&
        cached.anchorFloor === resolvedAnchorFloor
      ) {
        return cached.lookup;
      }

      const lookup = createReaderDepthLookup(
        sourceMessages,
        resolvedAnchorFloor,
      );
      this._readerDepthLookupCache = {
        messagesRef: sourceMessages,
        anchorFloor: resolvedAnchorFloor,
        lookup,
      };
      return lookup;
    },

    collectReaderPageWarmupFloors(
      groupIndex = null,
      radius = CHAT_READER_PAGE_GROUP_PREFETCH_RADIUS,
    ) {
      const groups = this.readerPageGroups;
      if (!groups.length) {
        return [];
      }

      const resolvedRadius = Math.max(0, Number(radius || 0));
      const fallbackIndex = Math.max(
        0,
        Number(
          this.currentReaderPageGroup?.index || this.readerPageGroupIndex || 0,
        ),
      );
      const requestedIndex = Number(groupIndex);
      const hasExplicitIndex =
        groupIndex !== null && groupIndex !== undefined && groupIndex !== "";
      const baseIndex =
        hasExplicitIndex && Number.isFinite(requestedIndex)
          ? Math.max(0, Math.min(groups.length - 1, requestedIndex))
          : fallbackIndex;
      const floorSet = new Set();

      for (
        let index = Math.max(0, baseIndex - resolvedRadius);
        index <= Math.min(groups.length - 1, baseIndex + resolvedRadius);
        index += 1
      ) {
        const floors = Array.isArray(groups[index]?.floors)
          ? groups[index].floors
          : [];
        floors.forEach((floor) => {
          const normalizedFloor = Number(floor || 0);
          if (normalizedFloor > 0) {
            floorSet.add(normalizedFloor);
          }
        });
      }

      return Array.from(floorSet).sort((left, right) => left - right);
    },

    scrollReaderCenterToTop(behavior = "auto") {
      const root = document.querySelector(".chat-reader-overlay--fullscreen");
      const center = root ? root.querySelector(".chat-reader-center") : null;
      if (!(center instanceof Element)) {
        return;
      }
      const previousHidden = this.readerMobileHeaderHidden;
      this.readerMobileHeaderHidden = false;
      this.readerLastScrollTop = 0;
      if (previousHidden) {
        this.updateReaderLayoutMetrics();
      }
      center.scrollTo({
        top: 0,
        behavior,
      });
    },

    setMobileReaderDocumentScrollState(enabled = false) {
      if (this.$store.global.deviceType !== "mobile") {
        return;
      }

      document.documentElement.style.overflow = enabled ? "auto" : "";
      document.body.style.overflow = enabled ? "auto" : "";
      document.body.style.height = enabled ? "auto" : "";
    },

    applyReaderPagePayload(range) {
      if (!this.activeChat || !range || typeof range !== "object") {
        return false;
      }

      const total = this.readerTotalMessages;
      if (!total) {
        return false;
      }

      const nextMessages = Array.isArray(this.activeChat.messages)
        ? [...this.activeChat.messages]
        : createReaderManifestMessages(this.activeChat.message_index, total);
      const nextRawMessages = Array.isArray(this.activeChat.raw_messages)
        ? [...this.activeChat.raw_messages]
        : Array.from({ length: total }, () => null);
      const nextMessageIndex = Array.isArray(this.activeChat.message_index)
        ? [...this.activeChat.message_index]
        : [];
      const parsedMessages = Array.isArray(range.messages)
        ? range.messages
        : [];
      const rawMessages = Array.isArray(range.raw_messages)
        ? range.raw_messages
        : [];
      const indexItems = Array.isArray(range.index_items)
        ? range.index_items
        : [];
      const includeMessages = range.include_messages === true;

      indexItems.forEach((indexItem, index) => {
        const fallbackFloor = Number(range.start_floor || 1) + index;
        const floor = Number(indexItem?.floor || fallbackFloor);
        if (!floor || floor > total) return;

        nextMessageIndex[floor - 1] =
          indexItem && typeof indexItem === "object"
            ? { ...indexItem, floor }
            : null;
        const manifest = createReaderManifestMessage(indexItem, floor);
        nextMessages[floor - 1] = mergeReaderManifestIntoMessage(
          nextMessages[floor - 1],
          manifest,
          {
            preserveLoadedPayload: !includeMessages,
          },
        );
      });

      parsedMessages.forEach((parsedMessage, index) => {
        const fallbackFloor = Number(range.start_floor || 1) + index;
        const floor = Number(
          parsedMessage?.floor || indexItems[index]?.floor || fallbackFloor,
        );
        if (!floor || floor > total) return;

        const manifest = createReaderManifestMessage(
          indexItems[index] || this.activeChat.message_index?.[floor - 1],
          floor,
        );
        const rawMessage =
          rawMessages[index] && typeof rawMessages[index] === "object"
            ? rawMessages[index]
            : null;

        nextRawMessages[floor - 1] = rawMessage;
        nextMessages[floor - 1] = {
          ...nextMessages[floor - 1],
          ...manifest,
          ...(parsedMessage && typeof parsedMessage === "object"
            ? parsedMessage
            : {}),
          preview_text:
            manifest.preview_text ||
            nextMessages[floor - 1]?.preview_text ||
            "",
          __loaded: Boolean(rawMessage),
        };
      });

      this.activeChat.message_index = nextMessageIndex;
      this.activeChat.messages = nextMessages;
      this.activeChat.raw_messages = nextRawMessages;
      return true;
    },

    async loadReaderPageSet(pageNos, options = {}) {
      if (!this.activeChat) return false;

      const uniquePages = [
        ...new Set(
          (Array.isArray(pageNos) ? pageNos : [])
            .map((item) => Number(item || 0))
            .filter((item) => item > 0 && item <= this.readerTotalPages),
        ),
      ].sort((left, right) => left - right);
      if (!uniquePages.length) {
        if (options.reset) {
          this.resetReaderLoadedPages(true);
        }
        return false;
      }

      const chatId = String(this.activeChat.id || "");
      const requestToken = this.readerPageRequestToken;
      const pageSize = Math.max(
        1,
        Number(this.readerPageSize || CHAT_READER_PAGE_SIZE),
      );
      this.logReaderScrollDebug("load_reader_page_set_start", {
        pageNos: uniquePages.slice(),
        reset: options.reset === true,
        mode: String(options.mode || ""),
        requestToken,
        pageSize,
      });
      const responses = await Promise.all(
        uniquePages.map((page) =>
          getChatRange(chatId, {
            page,
            page_size: pageSize,
          }),
        ),
      );

      if (
        !this.activeChat ||
        String(this.activeChat.id || "") !== chatId ||
        requestToken !== this.readerPageRequestToken
      ) {
        this.logReaderScrollDebug("load_reader_page_set_stale", {
          pageNos: uniquePages.slice(),
          requestToken,
        });
        return false;
      }

      const failed = responses.find((item) => !item?.success || !item?.range);
      if (failed) {
        this.logReaderScrollDebug("load_reader_page_set_failed", {
          pageNos: uniquePages.slice(),
          requestToken,
          message: String(failed?.msg || ""),
        });
        alert(failed?.msg || "读取聊天分页失败");
        return false;
      }

      if (options.reset) {
        this.resetReaderLoadedPages(true);
      }

      responses
        .map((item) => item.range)
        .sort(
          (left, right) => Number(left?.page || 0) - Number(right?.page || 0),
        )
        .forEach((range) => {
          this.applyReaderPagePayload(range);
        });

      if (
        options.reset ||
        !this.readerLoadedPageStart ||
        !this.readerLoadedPageEnd
      ) {
        this.readerLoadedPageStart = uniquePages[0];
        this.readerLoadedPageEnd = uniquePages[uniquePages.length - 1];
      } else {
        this.readerLoadedPageStart = Math.min(
          this.readerLoadedPageStart,
          uniquePages[0],
        );
        this.readerLoadedPageEnd = Math.max(
          this.readerLoadedPageEnd,
          uniquePages[uniquePages.length - 1],
        );
      }

      this.updateReaderWindowFromLoadedPages();
      this.rebuildActiveChatMessages(this.activeRegexConfig);
      this.logReaderScrollDebug("load_reader_page_set_done", {
        pageNos: uniquePages.slice(),
        requestToken,
        reset: options.reset === true,
      });
      return true;
    },

    async loadReaderNavBatch(batchNo = 1, options = {}) {
      if (!this.activeChat) return false;

      const totalBatches = this.readerNavTotalBatches;
      if (!totalBatches) {
        this.readerNavBatchIndex = 0;
        this.readerNavBatchItems = [];
        this.readerNavRangeStartFloor = 0;
        this.readerNavRangeEndFloor = 0;
        return false;
      }

      const targetBatch = Math.max(
        1,
        Math.min(totalBatches, Number(batchNo || 1)),
      );
      const chatId = String(this.activeChat.id || "");
      const requestToken = this.readerPageRequestToken;
      const batchSize = Math.max(
        1,
        Number(this.readerNavBatchSize || CHAT_READER_NAV_BATCH_SIZE),
      );
      this.readerNavBatchLoading = true;

      try {
        const res = await getChatRange(chatId, {
          page: targetBatch,
          page_size: batchSize,
          include_messages: false,
        });

        if (
          !this.activeChat ||
          String(this.activeChat.id || "") !== chatId ||
          requestToken !== this.readerPageRequestToken
        ) {
          return false;
        }

        if (!res?.success || !res?.range) {
          alert(res?.msg || "Failed to load floor index");
          return false;
        }

        this.applyReaderPagePayload(res.range);
        const bounds = this.resolveReaderNavBatchBounds(targetBatch);
        const items = Array.isArray(res.range.index_items)
          ? res.range.index_items
          : [];
        this.readerNavBatchItems = items.map((item, index) => {
          const floor = Number(item?.floor || bounds.start + index);
          const preview = String(item?.preview || "").trim();
          return {
            floor,
            name: String(
              item?.name ||
                (item?.is_user
                  ? "User"
                  : item?.is_system
                    ? "System"
                    : "Assistant"),
            ),
            content: preview,
            mes: preview,
            preview,
            is_user: Boolean(item?.is_user),
            is_system: Boolean(item?.is_system),
            send_date: String(item?.send_date || ""),
          };
        });
        this.readerNavBatchIndex = Math.max(0, targetBatch - 1);
        this.readerNavRangeStartFloor = bounds.start;
        this.readerNavRangeEndFloor = bounds.end;
        return true;
      } finally {
        if (requestToken === this.readerPageRequestToken) {
          this.readerNavBatchLoading = false;
        }
      }
    },

    async syncReaderNavBatchForFloor(floor = 1, options = {}) {
      const targetBatch = this.resolveReaderNavBatchForFloor(floor);
      if (!targetBatch) {
        this.readerNavBatchIndex = 0;
        this.readerNavBatchItems = [];
        this.readerNavRangeStartFloor = 0;
        this.readerNavRangeEndFloor = 0;
        return false;
      }

      const nextIndex = Math.max(0, targetBatch - 1);
      const shouldLoad =
        options.force === true ||
        !Array.isArray(this.readerNavBatchItems) ||
        this.readerNavBatchItems.length === 0 ||
        Number(this.readerNavBatchIndex || 0) !== nextIndex;
      this.readerNavBatchIndex = nextIndex;
      if (!shouldLoad) {
        return false;
      }
      return this.loadReaderNavBatch(targetBatch, options);
    },

    async stepReaderNavBatch(offset = 1) {
      const currentBatch = this.currentReaderNavBatch;
      if (!currentBatch) return;

      const nextBatch = Math.max(
        1,
        Math.min(
          this.readerNavTotalBatches,
          Number(currentBatch.batch || 1) + Number(offset || 0),
        ),
      );
      if (nextBatch === Number(currentBatch.batch || 1)) {
        return;
      }

      await this.loadReaderNavBatch(nextBatch);
    },

    resolveReaderDepthInfoForFloor(
      floor,
      rawMessage = null,
      config = null,
      anchorFloor = null,
    ) {
      const targetFloor = Number(floor || 0);
      const fullMessages = Array.isArray(this.activeChat?.messages)
        ? this.activeChat.messages
        : [];
      const normalizedRawMessage =
        rawMessage && typeof rawMessage === "object"
          ? rawMessage
          : this.getReaderRawMessageForFloor(targetFloor);
      const resolvedAnchorFloor = Number(
        anchorFloor || this.effectiveReaderAnchorFloor || targetFloor,
      );
      const resolvedConfig = normalizeRegexConfig(
        config || this.readerResolvedRegexConfig || this.activeRegexConfig,
      );
      const fallbackMessage = this.getReaderMessageForFloor(targetFloor) || {};
      const pageDepthOverride =
        this.resolveReaderPageDepthOverride(targetFloor);
      const depthInfo = resolveReaderDepthInfoFromLookup(
        this.resolveReaderDepthLookup(resolvedAnchorFloor, fullMessages),
        targetFloor,
      );
      const legacyReaderDepthMode = resolveReaderLegacyDepthMode(
        this.readerAnchorMode,
      );
      return {
        ...depthInfo,
        placement: resolveReaderRegexPlacement(
          normalizedRawMessage || fallbackMessage,
        ),
        macroContext: this.buildReaderRegexMacroContext(
          normalizedRawMessage || fallbackMessage,
          targetFloor,
        ),
        legacyReaderDepthMode,
        ignoreDepthLimits: pageDepthOverride.ignoreDepthLimits,
        scopedFloors: pageDepthOverride.scopedFloors,
        cacheKey: buildReaderDisplaySourceCacheKey(
          resolvedConfig,
          resolvedAnchorFloor,
          this.readerAnchorMode,
          pageDepthOverride,
        ),
      };
    },

    updateReaderAnchorFloor(floor, source = READER_ANCHOR_SOURCES.JUMP) {
      const total = this.readerTotalMessages;
      if (!total) return 0;
      const previousAnchorFloor = Number(this.effectiveReaderAnchorFloor || 0);
      this.logReaderScrollDebug("update_anchor_floor_start", {
        requestedFloor: Number(floor || 0),
        previousAnchorFloor,
        source: String(source || ""),
      });

      const nextFloor = Math.min(total, Math.max(1, Number(floor || 0)));
      if (!nextFloor) return 0;

      this.readerViewportFloor = nextFloor;

      if (this.readerAnchorMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE) {
        this.readerAnchorFloor = total;
        this.readerAnchorSource = source;
        void this.ensureReaderWindowForFloor(nextFloor, "center");
        this.readerResolvedRegexConfig = normalizeRegexConfig(
          this.activeRegexConfig,
        );
        if (
          Number(this.effectiveReaderAnchorFloor || 0) !== previousAnchorFloor
        ) {
          this.refreshReaderAnchorState(this.effectiveReaderAnchorFloor);
        }
        this.logReaderScrollDebug("update_anchor_floor_tail_mode", {
          nextFloor,
          resolvedAnchorFloor: Number(this.effectiveReaderAnchorFloor || 0),
        });
        return total;
      }

      this.readerAnchorFloor = nextFloor;
      this.readerAnchorSource = source;
      void this.ensureReaderWindowForFloor(nextFloor, "center");
      this.readerResolvedRegexConfig = normalizeRegexConfig(
        this.activeRegexConfig,
      );
      if (
        Number(this.effectiveReaderAnchorFloor || 0) !== previousAnchorFloor
      ) {
        this.refreshReaderAnchorState(this.effectiveReaderAnchorFloor);
      } else {
        resetReaderVisibleMessagesCache(this);
      }
      this.logReaderScrollDebug("update_anchor_floor_done", {
        nextFloor,
        previousAnchorFloor,
        resolvedAnchorFloor: Number(this.effectiveReaderAnchorFloor || 0),
      });
      return nextFloor;
    },

    refreshReaderAnchorState(anchorFloor = null) {
      if (!this.activeChat || !Array.isArray(this.activeChat.messages)) return;

      const messages = this.activeChat.messages;
      const total = this.readerTotalMessages;
      if (!total) {
        this._renderedFloorHtmlCache = new Map();
        this._readerRenderedDisplayCache = new Map();
        this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
        resetReaderVisibleMessagesCache(this);
        return;
      }

      const resolvedAnchorFloor = Math.min(
        total,
        Math.max(
          1,
          Number(anchorFloor || this.effectiveReaderAnchorFloor || total || 1),
        ),
      );
      this.logReaderScrollDebug("refresh_anchor_state_start", {
        resolvedAnchorFloor,
        total,
      });
      const rawTailKeepaliveCount = resolveReaderTailKeepaliveCount(
        this.readerViewSettings,
        total,
        resolvedAnchorFloor,
        this.readerAnchorMode,
      );
      const tailKeepaliveCount = rawTailKeepaliveCount;
      const renderBands = resolveReaderRenderBandRanges(
        this.readerViewSettings,
        total,
        resolvedAnchorFloor,
      );
      const warmupFloors = new Set();
      const pageGroupFloors = this.isReaderPageMode
        ? this.collectReaderPageWarmupFloors(
            null,
            CHAT_READER_PAGE_GROUP_PREFETCH_RADIUS,
          )
        : [];
      if (pageGroupFloors.length) {
        pageGroupFloors.forEach((floor) => {
          warmupFloors.add(floor);
        });
      } else {
        const warmupStart = Math.max(
          1,
          Math.min(
            renderBands.expansionStartFloor,
            renderBands.simpleStartFloor,
          ),
        );
        const warmupEnd = Math.min(
          total,
          Math.max(
            renderBands.expansionEndFloor,
            renderBands.simpleEndFloor,
            resolvedAnchorFloor +
              Number(
                this.readerViewSettings.instanceRenderDepth ??
                  DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth,
              ),
            tailKeepaliveCount > 0 ? total : 0,
          ),
        );

        for (let floor = warmupStart; floor <= warmupEnd; floor += 1) {
          warmupFloors.add(floor);
        }

        if (tailKeepaliveCount > 0) {
          const tailStart = Math.max(1, total - tailKeepaliveCount + 1);
          for (let floor = tailStart; floor <= total; floor += 1) {
            warmupFloors.add(floor);
          }
        }
      }

      this._renderedFloorHtmlCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
      const clearStartFloor = Math.max(
        1,
        Number(this.readerWindowStartFloor || 1),
      );
      const clearEndFloor = Math.min(
        total,
        Math.max(clearStartFloor, Number(this.readerWindowEndFloor || total)),
      );
      for (let floor = clearStartFloor; floor <= clearEndFloor; floor += 1) {
        const message = messages[floor - 1];
        if (!message || typeof message !== "object") continue;
        message.rendered_display_html = "";
      }

      warmupFloors.forEach((floor) => {
        const message = messages[floor - 1];
        if (!message || typeof message !== "object" || !message.__loaded)
          return;
        this.renderMessageDisplayHtml(message);
      });

      resetReaderVisibleMessagesCache(this);
      this.logReaderScrollDebug("refresh_anchor_state_done", {
        resolvedAnchorFloor,
        warmupCount: warmupFloors.size,
      });
    },

    setReaderBrowseMode(mode) {
      const nextMode = normalizeReaderBrowseMode(mode);
      this.readerBrowseMode = nextMode;
      this.clearReaderViewportSync();
      resetReaderVisibleMessagesCache(this);

      if (!this.activeChat) {
        return;
      }

      const currentFloor = Number(
        this.readerViewportFloor ||
          this.effectiveReaderAnchorFloor ||
          this.activeChat.last_view_floor ||
          1,
      );
      const effectiveMode = this.effectiveReaderBrowseMode;
      if (isReaderPageBrowseMode(effectiveMode)) {
        this.syncReaderPageGroupForFloor(currentFloor, {
          anchorFloor: currentFloor,
          source: READER_ANCHOR_SOURCES.JUMP,
        });
        const focusFloor = Number(
          this.currentReaderPageGroup?.anchorFloor || currentFloor || 1,
        );
        void this.ensureReaderWindowForFloor(focusFloor, "center").then(() => {
          this.refreshReaderAnchorState(focusFloor);
          this.$nextTick(() => this.scrollReaderCenterToTop("auto"));
        });
      } else {
        this.readerPageGroupIndex = 0;
        void this.ensureReaderWindowForFloor(currentFloor, "center").then(
          () => {
            this.refreshReaderAnchorState(currentFloor);
          },
        );
      }

      this.$store.global.showToast(
        `阅读模式已切换为${this.readerBrowseModeLabel}`,
        1500,
      );
    },

    async stepReaderPageGroup(offset = 1) {
      if (!this.isReaderPageMode) return;

      const groups = this.readerPageGroups;
      if (!groups.length) return;

      const currentGroup = this.currentReaderPageGroup;
      const currentIndex = currentGroup ? Number(currentGroup.index || 0) : 0;
      const nextIndex = Math.max(
        0,
        Math.min(groups.length - 1, currentIndex + Number(offset || 0)),
      );
      if (nextIndex === currentIndex) return;

      const nextGroup = groups[nextIndex];
      this.readerPageGroupIndex = nextIndex;
      resetReaderVisibleMessagesCache(this);

      const focusFloor = Number(
        nextGroup?.anchorFloor ||
          nextGroup?.endFloor ||
          nextGroup?.startFloor ||
          0,
      );
      if (!focusFloor) return;

      this.readerViewportFloor = focusFloor;
      this.readerAnchorFloor = focusFloor;
      this.readerAnchorSource = READER_ANCHOR_SOURCES.JUMP;
      this.jumpFloorInput = String(nextGroup.startFloor || focusFloor);

      void this.syncReaderNavBatchForFloor(focusFloor);
      await this.ensureReaderWindowForFloor(focusFloor, "center");
      this.refreshReaderAnchorState(focusFloor);
      this.$nextTick(() => this.scrollReaderCenterToTop("auto"));
    },

    setReaderAnchorMode(mode) {
      const nextMode = normalizeReaderAnchorMode(mode);
      this.readerAnchorMode = nextMode;

      if (!this.activeChat) return;

      const total = this.readerTotalMessages;
      const currentFloor = Number(
        this.readerViewportFloor ||
          this.effectiveReaderAnchorFloor ||
          total ||
          1,
      );
      if (nextMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE) {
        this.readerAnchorFloor = total;
        this.readerAnchorSource = READER_ANCHOR_SOURCES.JUMP;
        void this.setReaderWindowAroundFloor(total || 1, "center");
      } else {
        this.readerAnchorFloor = currentFloor;
        this.readerAnchorSource = READER_ANCHOR_SOURCES.JUMP;
        void this.setReaderWindowAroundFloor(currentFloor, "center");
      }

      this.readerResolvedRegexConfig = normalizeRegexConfig(
        this.activeRegexConfig,
      );
      this.refreshReaderAnchorState(this.effectiveReaderAnchorFloor);
      this.$store.global.showToast(
        `锚点模式已切换为${this.readerAnchorStatusText}`,
        1600,
      );
    },

    reanchorToCurrentFloor() {
      const floor = Number(
        this.readerViewportFloor || this.effectiveReaderAnchorFloor || 0,
      );
      if (!floor) return;

      if (this.readerAnchorMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE) {
        this.readerAnchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR;
      }
      this.updateReaderAnchorFloor(floor, READER_ANCHOR_SOURCES.JUMP);
    },

    buildReaderRegexMacroContext(rawMessage = null, floor = 0) {
      const source =
        rawMessage && typeof rawMessage === "object" ? rawMessage : {};
      const chat = this.activeChat || {};
      const characterName = chat.bound_card_name || chat.character_name || "";
      const userName = "User";

      return {
        char: characterName,
        character: characterName,
        name: characterName,
        user: userName,
        persona: userName,
        chat: chat.title || chat.chat_name || "",
        chatname: chat.title || chat.chat_name || "",
        chatid: chat.id || "",
        floor: String(floor || ""),
        messageid: source.id || String(floor || ""),
        mes: String(source.mes || ""),
      };
    },

    ensureMessageDisplaySource(message) {
      if (!message) return "";
      const floor = Number(message.floor || 0);
      const messageChatId = resolveReaderMessageChatId(
        message,
        this.activeChat,
      );
      const activeChatId = String(this.activeChat?.id || "");
      const rawMessages = Array.isArray(this.activeChat?.raw_messages)
        ? this.activeChat.raw_messages
        : [];
      const rawMessage =
        messageChatId === activeChatId && floor > 0
          ? rawMessages[floor - 1]
          : null;
      const runtimeConfig = normalizeRegexConfig(
        message.__readerRegexConfig ||
          this.readerResolvedRegexConfig ||
          this.activeRegexConfig,
      );
      const depthInfo =
        messageChatId !== activeChatId && message.__readerDepthInfo
          ? message.__readerDepthInfo
          : this.resolveReaderDepthInfoForFloor(
              floor,
              rawMessage,
              runtimeConfig,
            );
      message.__readerRegexConfig = runtimeConfig;
      message.__readerDepthInfo = depthInfo;
      if (message.tail_depth !== depthInfo.tailDepth) {
        message.tail_depth = depthInfo.tailDepth;
      }
      return ensureReaderDisplaySource(message, runtimeConfig, {
        placement: depthInfo.placement,
        isMarkdown: true,
        macroContext: depthInfo.macroContext,
        depth: depthInfo.tailDepth,
        depthInfo,
        legacyReaderDepthMode: depthInfo.legacyReaderDepthMode,
        ignoreDepthLimits: depthInfo.ignoreDepthLimits === true,
        scopedFloors: depthInfo.scopedFloors,
        cacheKey: depthInfo.cacheKey,
      });
    },

    classifyFrontendPreText(text) {
      const source = String(text || "");
      if (
        !["<html", "<head", "<body", "<!DOCTYPE html"].some((token) =>
          source.includes(token),
        )
      ) {
        return null;
      }

      const analysis = scoreFullPageAppHtml(source);
      if (analysis.score >= 8) {
        return {
          type: "app-stage",
          minHeight: 520,
          maxHeight: 0,
        };
      }

      return {
        type: "html-component",
        minHeight: 28,
        maxHeight: 520,
      };
    },

    get editingMessageTarget() {
      const targetFloor = Number(this.editingFloor || 0);
      if (
        !targetFloor ||
        !this.activeChat ||
        !Array.isArray(this.activeChat.messages)
      )
        return null;
      return (
        this.activeChat.messages.find(
          (item) => Number(item.floor || 0) === targetFloor,
        ) || null
      );
    },

    get editingMessageParsedPreview() {
      if (!this.editingMessageRawDraft) return "";
      const depthInfo = this.resolveReaderDepthInfoForFloor(
        this.editingFloor,
        this.editingMessageTarget || { mes: this.editingMessageRawDraft },
      );
      return buildReaderDisplaySource(
        this.editingMessageRawDraft,
        this.activeRegexConfig,
        {
          placement: 2,
          isMarkdown: true,
          isEdit: true,
          macroContext: this.buildReaderRegexMacroContext(
            this.editingMessageTarget || { mes: this.editingMessageRawDraft },
            this.editingFloor,
          ),
          depth: depthInfo.tailDepth ?? 0,
          depthInfo,
          legacyReaderDepthMode: depthInfo.legacyReaderDepthMode,
        },
      );
    },

    get editingMessageSourcePreview() {
      return this.editingMessageRawDraft || this.editingMessageDraft || "";
    },

    updateShadowContent,
    formatScopedDisplayedHtml,

    get editingMessageParsedPreviewHtml() {
      const flags = resolveReaderFormatFlags(this.editingMessageTarget || {});
      return formatScopedDisplayedHtml(this.editingMessageParsedPreview, {
        scopeClass: "st-reader-floor-edit-preview",
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
        scopeClass: "st-reader-floor-edit-source",
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
      const original = this.editingMessageTarget?.mes || "";
      const current = this.editingMessageRawDraft || "";
      return buildSimpleDiffHtml(original, current);
    },

    get regexTestPreview() {
      const source = String(this.regexTestInput || "").trim();
      if (!source) {
        return {
          content: "",
          display_source: "",
          thinking: "",
          summary: "",
          time_bar: "",
          choices: [],
          render_segments: [],
        };
      }

      const previewConfig = normalizeRegexConfig(this.regexDraftResolvedConfig);
      const previewDepthInfo = {
        tailDepth: 0,
        anchorAbsDepth: 0,
        anchorBackwardDepth: 0,
        anchorRelativeDepth: 0,
      };
      const previewMessage = buildReaderParsedMessage(
        {
          mes: source,
          name: "Regex Test",
        },
        1,
        previewConfig,
        {
          chatId: "regex-test",
          macroContext: this.buildReaderRegexMacroContext(
            { mes: source, name: "Regex Test" },
            1,
          ),
          tailDepth: 0,
        },
      );
      previewMessage.__readerRegexConfig = previewConfig;
      previewMessage.__readerDepthInfo = {
        ...previewDepthInfo,
        placement: READER_REGEX_PLACEMENT.AI_OUTPUT,
        macroContext: this.buildReaderRegexMacroContext(
          { mes: source, name: "Regex Test" },
          1,
        ),
        legacyReaderDepthMode: resolveReaderLegacyDepthMode(
          this.readerAnchorMode,
        ),
        cacheKey: buildReaderDisplaySourceCacheKey(
          previewConfig,
          1,
          this.readerAnchorMode,
        ),
      };
      return previewMessage;
    },

    get hasChatRegexConfig() {
      return hasCustomRegexConfig(this.savedChatRegexConfig);
    },

    get hasBoundCardRegexConfig() {
      return hasCustomRegexConfig(this.activeCardRegexConfig);
    },

    get regexDraftRuleCount() {
      return this.regexDraftDisplayRules.length;
    },

    get hasRegexDraftEntries() {
      return (
        Array.isArray(this.regexConfigDraft?.displayRules) &&
        this.regexConfigDraft.displayRules.length > 0
      );
    },

    get canRestoreRegexInheritance() {
      return (
        this.hasRegexDraftEntries || Boolean(this.activeChat?.bound_card_id)
      );
    },

    get regexDraftDeletionCount() {
      return decorateRegexDisplayRules(this.regexConfigDraft, "chat", {
        includeDeleted: true,
      }).filter((rule) => rule.deleted).length;
    },

    get regexRuleSourceSummary() {
      return summarizeRegexRuleSources(this.regexDraftDisplayRules, "chat");
    },

    get regexDraftDisplayRules() {
      return decorateRegexDisplayRules(this.regexConfigDraft, "chat");
    },

    get regexSourceChain() {
      return this.regexStateCards;
    },

    get readerVisibleSummary() {
      const messages = this.visibleDetailMessages;
      if (!messages.length) {
        return "暂无楼层";
      }

      if (this.isReaderPageMode) {
        const currentGroup = this.currentReaderPageGroup;
        const groups = this.readerPageGroups;
        const fullVisible = messages.filter(
          (item) => item.is_full_display,
        ).length;
        const renderedNow = messages.filter(
          (item) => item.should_render_full,
        ).length;
        const groupLabel = currentGroup
          ? currentGroup.floors.length === 1
            ? `#${currentGroup.startFloor}`
            : `#${currentGroup.startFloor}-#${currentGroup.endFloor}`
          : "当前页";
        return `当前模式 ${this.readerBrowseModeLabel} · 第 ${currentGroup ? Number(currentGroup.index || 0) + 1 : 1}/${Math.max(1, groups.length)} 页 · ${groupLabel} · 完整显示 ${fullVisible} 楼，当前高渲染 ${renderedNow} 楼`;
      }

      const total = Number(this.readerTotalMessages || messages.length || 0);
      const windowStartFloor = Math.max(
        1,
        Number(this.readerWindowStartFloor || 1),
      );
      const windowEndFloor = Math.min(
        total || messages.length,
        Math.max(
          windowStartFloor,
          Number(
            this.readerWindowEndFloor ||
              messages[messages.length - 1]?.floor ||
              windowStartFloor,
          ),
        ),
      );
      const fullVisible = messages.filter(
        (item) => item.is_full_display,
      ).length;
      const renderedNow = messages.filter(
        (item) => item.should_render_full,
      ).length;
      const instanceDepth = Number(
        this.readerViewSettings.instanceRenderDepth ??
          DEFAULT_CHAT_READER_VIEW_SETTINGS.instanceRenderDepth,
      );
      const instanceSummary =
        instanceDepth === 0
          ? "全部实例执行"
          : `锚点附近 ${instanceDepth} 层执行实例`;
      return `当前已载入 #${windowStartFloor}-#${windowEndFloor} / ${total} 层 · 锚点 ${this.readerAnchorStatusText} · 完整显示 ${fullVisible} 层，当前高渲染 ${renderedNow} 层 · ${instanceSummary}`;
    },

    get hasEarlierReaderWindow() {
      return Boolean(this.activeChat && this.readerWindowStartFloor > 1);
    },

    get hasLaterReaderWindow() {
      const total = this.readerTotalMessages;
      return Boolean(
        this.activeChat && total > 0 && this.readerWindowEndFloor < total,
      );
    },

    get resolvedRegexConfigSourceLabel() {
      if (this.regexConfigOpen) {
        const hasBoundCard = Boolean(this.activeChat?.bound_card_id);
        const hasCardRules = this.cardRegexRuleCount > 0;
        const hasDraftImpact =
          this.hasRegexDraftEntries || this.regexDraftDeletionCount > 0;
        const hasPreviewRules = this.activeRegexDisplayRules.length > 0;
        if (hasPreviewRules && hasCardRules && hasDraftImpact)
          return "左侧预览：角色卡继承 + 当前草稿";
        if (hasPreviewRules && hasDraftImpact) return "左侧预览：当前草稿";
        if (hasPreviewRules && hasCardRules) return "左侧预览：角色卡继承";
        if (hasBoundCard)
          return "左侧预览：已绑定角色卡，但当前没有可用解析规则";
        return "左侧预览：当前没有可用解析规则";
      }
      return this.regexConfigSourceLabel || this.describeRegexConfigSource();
    },

    get readerBodyGridStyle() {
      const mode = this.readerResponsiveMode;
      if (mode === "mobile") {
        return "grid-template-columns: minmax(0, 1fr);";
      }

      const leftWidth = mode === "tablet" ? 264 : 320;
      const rightWidth = mode === "tablet" ? 280 : 300;

      if (mode === "tablet") {
        if (this.readerShowLeftPanel) {
          return `grid-template-columns: ${leftWidth}px minmax(0, 1fr);`;
        }
        if (this.readerShowRightPanel) {
          return `grid-template-columns: minmax(0, 1fr) ${rightWidth}px;`;
        }
        return "grid-template-columns: minmax(0, 1fr);";
      }

      if (this.readerShowLeftPanel && this.readerDesktopRightPanelOpen) {
        return `grid-template-columns: ${leftWidth}px minmax(0, 1fr) ${rightWidth}px;`;
      }

      if (this.readerShowLeftPanel) {
        return `grid-template-columns: ${leftWidth}px minmax(0, 1fr);`;
      }

      if (this.readerDesktopRightPanelOpen) {
        return `grid-template-columns: minmax(0, 1fr) ${rightWidth}px;`;
      }

      return "grid-template-columns: minmax(0, 1fr);";
    },

    openReaderDesktopPanel(panel) {
      if (this.readerResponsiveMode === "mobile") {
        this.setReaderMobilePanel(
          panel === "navigator" ? "navigator" : "search",
        );
        return;
      }

      const nextTab = panel === "navigator" ? "floors" : "search";
      const isSamePanelOpen =
        this.readerShowRightPanel && this.readerRightTab === nextTab;

      if (isSamePanelOpen) {
        this.readerShowRightPanel = false;
        this.updateReaderLayoutMetrics();
        return;
      }

      this.readerRightTab = nextTab;
      this.readerShowRightPanel = true;
      if (this.readerResponsiveMode === "tablet") {
        this.readerShowLeftPanel = false;
      }

      if (
        this.readerRightTab === "floors" &&
        this.activeChat &&
        (!Array.isArray(this.readerNavBatchItems) ||
          this.readerNavBatchItems.length === 0)
      ) {
        void this.syncReaderNavBatchForFloor(
          this.effectiveReaderAnchorFloor ||
            this.readerViewportFloor ||
            this.activeChat.last_view_floor ||
            1,
          { force: true },
        );
      }

      this.updateReaderLayoutMetrics();
    },

    closeReaderRightPanel() {
      this.readerShowRightPanel = false;
      if (this.readerResponsiveMode === "mobile") {
        this.readerMobilePanel = "";
      }
      this.updateReaderLayoutMetrics();
    },

    init() {
      this.chatAppStage = new ChatAppStage({
        onTriggerSlash: async (command) => {
          await this.executeAppStageSlash(command);
        },
        onToast: (message, duration) => {
          this.$store.global.showToast(
            String(message || ""),
            Number.isFinite(Number(duration)) ? Number(duration) : 2200,
          );
        },
        onAppError: (error) => {
          console.error("[ChatAppStage]", error);
          this.$store.global.showToast(`实例错误: ${error.message}`, 2600);
        },
      });

      this.regexConfigDraft = normalizeRegexConfig(
        EMPTY_CHAT_READER_REGEX_CONFIG,
        { fillDefaults: false },
      );
      this.readerViewSettings = loadStoredViewSettings();
      const renderPreferences = loadStoredRenderPreferences();
      this.readerRenderMode = renderPreferences.renderMode;
      this.readerComponentMode = renderPreferences.componentMode;
      this.readerBrowseMode = renderPreferences.browseMode;
      this.activeCardRegexConfig = normalizeRegexConfig(
        EMPTY_CHAT_READER_REGEX_CONFIG,
        { fillDefaults: false },
      );

      this.$watch("$store.global.chatSearchQuery", () => {
        this.chatCurrentPage = 1;
        this.fetchChats();
      });

      this.$watch("$store.global.chatFilterType", () => {
        this.chatCurrentPage = 1;
        this.fetchChats();
      });

      this.$watch("$store.global.chatFavFilter", () => {
        this.chatCurrentPage = 1;
        this.fetchChats();
      });

      this.$watch("$store.global.deviceType", () => {
        if (!this.detailOpen) return;
        this.reconcileReaderPanelsForDeviceType();
      });

      this.$watch("readerRenderMode", (value) => {
        storeRenderPreferences({
          renderMode: value,
          componentMode: this.readerComponentMode,
          browseMode: this.readerBrowseMode,
        });
      });

      this.$watch("readerComponentMode", (value) => {
        storeRenderPreferences({
          renderMode: this.readerRenderMode,
          componentMode: value,
          browseMode: this.readerBrowseMode,
        });
      });

      this.$watch("readerBrowseMode", (value) => {
        storeRenderPreferences({
          renderMode: this.readerRenderMode,
          componentMode: this.readerComponentMode,
          browseMode: value,
        });
      });

      this.$watch("readerAppMode", (enabled) => {
        if (!enabled) {
          this.readerAppSignature = "";
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

      window.addEventListener("refresh-chat-list", () => {
        this.fetchChats();
      });

      window.addEventListener("settings-loaded", () => {
        if (this.$store.global.currentMode === "chats") {
          this.fetchChats();
        }
      });

      window.addEventListener("beforeunload", () => {
        this.clearReaderViewportSync();
        if (this.chatAppStage) {
          this.chatAppStage.destroy();
          this.chatAppStage = null;
        }
      });

      window.addEventListener("open-chat-manager", (e) => {
        const detail = e.detail || {};
        this.$store.global.currentMode = "chats";
        this.linkedCardIdFilter = detail.card_id || "";
        this.linkedCardNameFilter = detail.card_name || "";
        this.pendingOpenChatId = detail.chat_id || "";
        this.chatFilterType = "all";
        this.chatCurrentPage = 1;
        this.fetchChats();
      });

      window.addEventListener("open-chat-reader", (e) => {
        const detail = e.detail || {};
        if (!detail.chat_id) return;
        this.openChatDetail({ id: detail.chat_id });
      });

      window.addEventListener("open-chat-file-picker", (event) => {
        const detail = event.detail || {};
        this.triggerChatImport(detail);
      });

      window.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (this.bindPickerOpen) {
          this.closeBindPicker();
          return;
        }
        if (this.detailOpen) {
          this.closeChatDetail();
        }
      });

      window.addEventListener("resize", () => {
        if (this.detailOpen) {
          this.reconcileReaderPanelsForDeviceType();
          this.updateReaderLayoutMetrics();
          this.syncReaderViewportFloor();
        }
      });

      window.stUploadChatFiles = (files, payload = {}) => {
        this._uploadChatFiles(
          files,
          payload.cardId || "",
          payload.characterName || "",
        );
      };

      if (
        this.$store.global.currentMode === "chats" &&
        this.$store.global.serverStatus.status === "ready"
      ) {
        this.fetchChats();
      }
    },

    fetchChats() {
      if (this.$store.global.serverStatus.status !== "ready") return;

      this.$store.global.isLoading = true;
      const params = {
        page: this.chatCurrentPage,
        page_size: this.$store.global.settingsForm.items_per_page_wi || 20,
        search: this.chatSearchQuery || "",
        filter: this.chatFilterType || "all",
        fav_filter: this.chatFavFilter || "none",
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
          this.chatTotalPages = Math.max(
            1,
            Math.ceil((res.total || 0) / (res.page_size || 1)),
          );

          if (this.pendingOpenChatId) {
            const targetId = this.pendingOpenChatId;
            this.pendingOpenChatId = "";
            const targetItem = (this.chatList || []).find(
              (item) => item.id === targetId,
            );
            this.openChatDetail(
              targetItem || { id: targetId, title: targetId },
            );
          }
        })
        .catch(() => {
          this.$store.global.isLoading = false;
        });
    },

    changeChatPage(page) {
      if (page < 1 || page > this.chatTotalPages) return;
      this.chatCurrentPage = page;
      const el = document.getElementById("chat-scroll-area");
      if (el) el.scrollTop = 0;
      this.fetchChats();
    },

    async openChatDetail(item) {
      if (!item || !item.id) return;

      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
        window.dispatchEvent(new CustomEvent("close-header-mobile-menu"));
        this.setMobileReaderDocumentScrollState(true);
      }

      this.readerPageRequestToken += 1;
      const requestToken = this.readerPageRequestToken;
      this.clearReaderViewportSync();
      this.destroyAllReaderPartStages();
      if (this.chatAppStage) {
        this.chatAppStage.clear({ resetSession: true });
      }
      this.detailOpen = true;
      this.detailLoading = true;
      this.resetReaderScrollDebugLog(
        `open:${String(item.id || "")}:${requestToken}`,
      );
      this.logReaderScrollDebug("open_chat_detail_start", {
        itemId: String(item.id || ""),
        requestToken,
      });
      this.activeChat = null;
      this.detailSearchQuery = "";
      this.detailSearchResults = [];
      this.detailSearchIndex = -1;
      this.detailBookmarkedOnly = false;
      this.bookmarkDraft = "";
      this.jumpFloorInput = "";
      this.replaceQuery = "";
      this.replaceReplacement = "";
      this.replaceUseRegex = false;
      this.replaceStatus = "";
      this.setReaderFeedbackTone();
      this.readerMobilePanel = "";
      this.readerRightTab = "search";
      const renderPreferences = loadStoredRenderPreferences();
      this.readerRenderMode = renderPreferences.renderMode;
      this.readerComponentMode = renderPreferences.componentMode;
      this.readerBrowseMode = renderPreferences.browseMode;
      this.readerPageGroupIndex = 0;
      this.regexConfigOpen = false;
      this.regexConfigTab = "extract";
      this.regexConfigStatus = "";
      this.regexTestInput = "";
      this.regexConfigSourceLabel = "";
      this.activeCardRegexConfig = normalizeRegexConfig(
        EMPTY_CHAT_READER_REGEX_CONFIG,
        { fillDefaults: false },
      );
      this.readerViewportFloor = 0;
      this.readerAnchorFloor = 0;
      this.readerAnchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR;
      this.readerAnchorSource = READER_ANCHOR_SOURCES.RESTORE;
      this.readerPageSize = CHAT_READER_PAGE_SIZE;
      this.readerLoadedPageStart = 0;
      this.readerLoadedPageEnd = 0;
      this.readerNavBatchIndex = 0;
      this.readerNavBatchItems = [];
      this.readerNavBatchLoading = false;
      this.readerNavRangeStartFloor = 0;
      this.readerNavRangeEndFloor = 0;
      this.readerWindowStartFloor = 1;
      this.readerWindowEndFloor = 0;
      this._renderedFloorHtmlCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      this._readerDepthLookupCache = null;
      if (this.activeChat) {
        this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
      }
      resetReaderVisibleMessagesCache(this);
      this.readerViewSettingsOpen = false;
      this.readerAppMode = false;
      this.readerAppFloor = 0;
      this.readerAppSignature = "";
      this.readerAppDebug = {
        checkedCount: 0,
        detectedFloor: 0,
        matchedFloors: [],
        status: "未检测",
      };
      this.editingFloor = 0;
      this.editingMessageDraft = "";
      this.editingMessageRawDraft = "";
      this.editingMessagePreviewMode = "parsed";
      this.updateReaderLayoutMetrics();

      const responsiveMode = this.readerResponsiveMode;
      this.readerShowLeftPanel = responsiveMode !== "mobile";
      this.readerShowRightPanel = responsiveMode !== "mobile";
      this.readerMobilePanel = "";

      try {
        const res = await getChatDetail(item.id, {
          include_message_index: false,
        });
        if (requestToken !== this.readerPageRequestToken) return;
        if (!res.success || !res.chat) {
          alert(res.msg || "读取聊天详情失败");
          this.detailOpen = false;
          return;
        }

        this.readerPageSize = Math.max(
          1,
          Number(res.chat.page_size || CHAT_READER_PAGE_SIZE),
        );
        this.activeChat = this.buildReaderManifestChat(res.chat);
        this.detailDraftName = this.activeChat.display_name || "";
        this.detailDraftNotes = this.activeChat.notes || "";
        setActiveRuntimeContext({
          chat: {
            id: this.activeChat?.id || item.id,
            title: this.activeChat?.title || this.activeChat?.chat_name || "",
            bound_card_id: this.activeChat?.bound_card_id || "",
            bound_card_name:
              this.activeChat?.bound_card_name ||
              this.activeChat?.character_name ||
              "",
            message_count: this.activeChat?.message_count || 0,
          },
        });
        await this.loadBoundCardRegexConfig(this.activeChat);
        if (requestToken !== this.readerPageRequestToken) return;
        if (
          !this.activeChat.bound_card_resource_folder &&
          this.activeChat.bound_card_id
        ) {
          this.activeChat.bound_card_resource_folder =
            this.activeCardRegexConfig?.__meta?.resource_folder || "";
        }
        this.readerResolvedRegexConfig = normalizeRegexConfig(
          this.activeRegexConfig,
        );
        const initialFloor = Math.min(
          Math.max(1, Number(this.activeChat.last_view_floor || 1)),
          Math.max(1, this.readerTotalMessages || 1),
        );
        this.readerViewportFloor = initialFloor;
        this.readerAnchorFloor = initialFloor;
        this.readerAnchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR;
        this.readerAnchorSource = READER_ANCHOR_SOURCES.RESTORE;
        this.logReaderScrollDebug("open_chat_detail_loaded", {
          initialFloor,
          totalMessages: Number(this.readerTotalMessages || 0),
          pageSize: Number(this.readerPageSize || 0),
          browseMode: this.effectiveReaderBrowseMode,
        });
        this.syncReaderPageGroupForFloor(initialFloor, {
          anchorFloor: initialFloor,
          source: READER_ANCHOR_SOURCES.RESTORE,
        });
        await Promise.all([
          this.setReaderWindowAroundFloor(
            this.effectiveReaderAnchorFloor || 1,
            "center",
          ),
          this.syncReaderNavBatchForFloor(initialFloor, { force: true }),
        ]);
        if (requestToken !== this.readerPageRequestToken) return;
        this.detectChatAppMode();
        this.regexConfigDraft = this.getChatOwnedRegexConfig(this.activeChat);
        this.selectedActiveRegexRuleIndex = 0;
        this.selectedDraftRegexRuleIndex = 0;
        this.regexConfigSourceLabel = this.describeRegexConfigSource(
          this.activeChat,
        );
        this.$nextTick(() => {
          this.mountChatAppStage();
          this.syncChatAppStage();
          this.updateReaderLayoutMetrics();
          this.scrollToFloor(initialFloor || 1, false, "auto");
        });
        this.logReaderScrollDebug("open_chat_detail_ready", {
          initialFloor,
        });
      } catch (err) {
        this.logReaderScrollDebug("open_chat_detail_error", {
          message: String(err?.message || err || ""),
        });
        alert("读取聊天详情失败: " + err);
        this.detailOpen = false;
      } finally {
        if (requestToken === this.readerPageRequestToken) {
          this.detailLoading = false;
          this.logReaderScrollDebug("open_chat_detail_finally", {
            requestToken,
            detailOpen: this.detailOpen === true,
          });
        }
      }
    },

    closeChatDetail() {
      this.logReaderScrollDebug("close_chat_detail_start", {
        activeChatId: String(this.activeChat?.id || ""),
      });
      this.setMobileReaderDocumentScrollState(false);
      this.readerPageRequestToken += 1;
      this.clearReaderViewportSync();
      this.destroyAllReaderPartStages();
      if (this.chatAppStage) {
        this.chatAppStage.clear({ resetSession: true });
      }
      this.detailOpen = false;
      this.detailLoading = false;
      this.activeChat = null;
      this._readerDepthLookupCache = null;
      clearActiveRuntimeContext("chat");
      this.detailSearchQuery = "";
      this.detailSearchResults = [];
      this.detailSearchIndex = -1;
      this.detailBookmarkedOnly = false;
      this.bookmarkDraft = "";
      this.jumpFloorInput = "";
      this.replaceQuery = "";
      this.replaceReplacement = "";
      this.replaceUseRegex = false;
      this.replaceStatus = "";
      this.setReaderFeedbackTone();
      this.readerMobilePanel = "";
      this.readerRightTab = "search";
      const renderPreferences = loadStoredRenderPreferences();
      this.readerRenderMode = renderPreferences.renderMode;
      this.readerComponentMode = renderPreferences.componentMode;
      this.regexConfigOpen = false;
      this.regexConfigTab = "extract";
      this.regexConfigStatus = "";
      this.regexTestInput = "";
      this.regexConfigSourceLabel = "";
      this.activeCardRegexConfig = normalizeRegexConfig(
        EMPTY_CHAT_READER_REGEX_CONFIG,
        { fillDefaults: false },
      );
      this.activeBoundCardDetail = null;
      this.readerResolvedRegexConfig = normalizeRegexConfig(
        DEFAULT_CHAT_READER_REGEX_CONFIG,
      );
      this.readerViewportFloor = 0;
      this.readerAnchorFloor = 0;
      this.readerAnchorMode = READER_ANCHOR_MODES.LOCKED_FLOOR;
      this.readerAnchorSource = READER_ANCHOR_SOURCES.RESTORE;
      this.readerPageSize = CHAT_READER_PAGE_SIZE;
      this.readerLoadedPageStart = 0;
      this.readerLoadedPageEnd = 0;
      this.readerNavBatchIndex = 0;
      this.readerNavBatchItems = [];
      this.readerNavBatchLoading = false;
      this.readerNavRangeStartFloor = 0;
      this.readerNavRangeEndFloor = 0;
      this.readerWindowStartFloor = 1;
      this.readerWindowEndFloor = 0;
      this._renderedFloorHtmlCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      if (this.activeChat) {
        this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
      }
      resetReaderVisibleMessagesCache(this);
      this.readerViewSettingsOpen = false;
      this.readerAppMode = false;
      this.readerAppFloor = 0;
      this.readerAppSignature = "";
      this.readerAppDebug = {
        checkedCount: 0,
        detectedFloor: 0,
        matchedFloors: [],
        status: "未检测",
      };
      this.editingFloor = 0;
      this.editingMessageDraft = "";
      this.editingMessageRawDraft = "";
      this.editingMessagePreviewMode = "parsed";
      this.closeBindPicker();
    },

    updateReaderLayoutMetrics() {
      this.$nextTick(() => {
        const root = document.querySelector(".chat-reader-overlay--fullscreen");
        if (!root) return;

        const header = root.querySelector(".chat-reader-header");
        const headerHeight = header
          ? Math.ceil(header.getBoundingClientRect().height)
          : 76;
        const effectiveHeaderHeight =
          this.readerResponsiveMode === "mobile" &&
          this.readerMobileHeaderHidden
            ? 0
            : headerHeight;
        root.style.setProperty(
          "--chat-reader-header-height",
          `${effectiveHeaderHeight}px`,
        );
      });
    },

    updateRegexConfigLayoutMetrics() {
      this.$nextTick(() => {
        const modal = document.querySelector(".chat-reader-editor-modal");
        if (
          !modal ||
          !this.regexConfigOpen ||
          this.readerResponsiveMode !== "mobile"
        )
          return;

        const header = modal.querySelector(".chat-reader-regex-header");
        const headerHeight = header
          ? Math.ceil(header.getBoundingClientRect().height)
          : 0;
        const effectiveHeaderHeight = this.regexConfigMobileHeaderHidden
          ? 0
          : headerHeight;
        modal.style.setProperty(
          "--chat-reader-regex-header-height",
          `${effectiveHeaderHeight}px`,
        );
      });
    },

    isReaderScrollDebugEnabled() {
      return false;
    },

    resetReaderScrollDebugLog(label = "") {
      void label;
    },

    logReaderScrollDebug(event, payload = {}) {
      void event;
      void payload;
    },

    logReaderLayoutDebug(event, payload = {}) {
      void event;
      void payload;
    },

    describeReaderLayoutNode(node, originTop = 0) {
      if (!(node instanceof Element)) return null;

      const rect = node.getBoundingClientRect();
      const className = String(node.className || "")
        .replace(/\s+/g, " ")
        .trim();
      return {
        tag: String(node.tagName || "").toLowerCase(),
        className: className.slice(0, 160),
        top: Math.round(rect.top - originTop),
        bottom: Math.round(rect.bottom - originTop),
        height: Math.round(rect.height),
        textLength: String(node.innerText || node.textContent || "").trim()
          .length,
      };
    },

    findReaderLastVisibleContentNode(el) {
      if (!(el instanceof Element)) return null;

      const candidates = [el, ...Array.from(el.querySelectorAll("*"))]
        .filter((node) => {
          if (!(node instanceof Element)) return false;
          const rect = node.getBoundingClientRect();
          if (rect.height <= 0 || rect.width <= 0) return false;
          const style = window.getComputedStyle(node);
          if (style.display === "none" || style.visibility === "hidden")
            return false;
          if (
            ["script", "style", "meta", "link"].includes(
              String(node.tagName || "").toLowerCase(),
            )
          )
            return false;
          return true;
        })
        .sort((left, right) => {
          const leftRect = left.getBoundingClientRect();
          const rightRect = right.getBoundingClientRect();
          if (leftRect.bottom !== rightRect.bottom) {
            return rightRect.bottom - leftRect.bottom;
          }
          if (leftRect.top !== rightRect.top) {
            return rightRect.top - leftRect.top;
          }
          return rightRect.height - leftRect.height;
        });

      return candidates[0] || null;
    },

    captureReaderFloorLayoutSnapshot(message, el) {
      if (!(el instanceof Element) || !message) return null;

      const card = el.closest("[data-chat-floor]");
      if (!(card instanceof Element)) return null;

      const floor = Number(
        message.floor || card.getAttribute("data-chat-floor") || 0,
      );
      const cardRect = card.getBoundingClientRect();
      const contentRect = el.getBoundingClientRect();
      const lastVisibleNode = this.findReaderLastVisibleContentNode(el);
      const lastVisibleRect =
        lastVisibleNode instanceof Element
          ? lastVisibleNode.getBoundingClientRect()
          : null;
      const runtimeWrappers = Array.from(
        el.querySelectorAll(".chat-inline-runtime-wrap"),
      ).map((wrapper, index) => {
        const host = wrapper.querySelector(".chat-inline-runtime-host");
        const source = wrapper.querySelector(".chat-inline-runtime-source");
        const shell =
          host instanceof Element
            ? host.querySelector(".chat-reader-app-stage-shell")
            : null;
        const iframe =
          host instanceof Element ? host.querySelector("iframe") : null;
        const wrapperRect = wrapper.getBoundingClientRect();
        const hostRect =
          host instanceof Element ? host.getBoundingClientRect() : null;
        const sourceRect =
          source instanceof Element ? source.getBoundingClientRect() : null;
        const shellRect =
          shell instanceof Element ? shell.getBoundingClientRect() : null;
        const iframeRect =
          iframe instanceof Element ? iframe.getBoundingClientRect() : null;

        return {
          index,
          active: wrapper.classList.contains("is-active"),
          wrapperHeight: Math.round(wrapperRect.height),
          hostHeight: Math.round(hostRect?.height || 0),
          hostScrollHeight:
            host instanceof Element ? Number(host.scrollHeight || 0) : 0,
          sourceHeight: Math.round(sourceRect?.height || 0),
          sourceScrollHeight:
            source instanceof Element ? Number(source.scrollHeight || 0) : 0,
          shellHeight: Math.round(shellRect?.height || 0),
          shellStyleHeight:
            shell instanceof Element ? String(shell.style.height || "") : "",
          iframeHeight: Math.round(iframeRect?.height || 0),
          iframeStyleHeight:
            iframe instanceof Element ? String(iframe.style.height || "") : "",
          sourceTextLength:
            source instanceof Element
              ? String(source.innerText || source.textContent || "").trim()
                  .length
              : 0,
        };
      });

      const cardChildren = Array.from(card.children)
        .map((child) => this.describeReaderLayoutNode(child, cardRect.top))
        .filter(Boolean);

      return {
        floor,
        renderTier: String(message.render_tier || ""),
        displayVariant: String(el.__stmReaderDisplayVariant || ""),
        cardHeight: Math.round(cardRect.height),
        cardScrollHeight: Number(card.scrollHeight || 0),
        contentHeight: Math.round(contentRect.height),
        contentScrollHeight: Number(el.scrollHeight || 0),
        textLength: String(el.innerText || el.textContent || "").trim().length,
        textTail: String(el.innerText || el.textContent || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(-160),
        blankTailHeight: lastVisibleRect
          ? Math.max(0, Math.round(cardRect.bottom - lastVisibleRect.bottom))
          : null,
        contentTailHeight: lastVisibleRect
          ? Math.max(0, Math.round(contentRect.bottom - lastVisibleRect.bottom))
          : null,
        lastVisibleNode: this.describeReaderLayoutNode(
          lastVisibleNode,
          cardRect.top,
        ),
        runtimeWrapperCount: runtimeWrappers.length,
        runtimeWrappers,
        cardChildren,
      };
    },

    shouldTraceReaderFloorLayout(floor, snapshot = null) {
      void floor;
      void snapshot;
      return false;
    },

    scheduleReaderFloorLayoutDebug(
      message,
      el,
      reason = "generic",
      extra = {},
    ) {
      void message;
      void el;
      void reason;
      void extra;
    },

    debugReaderFloorLayoutByFloor(floor, reason = "manual", extra = {}) {
      void floor;
      void reason;
      void extra;
    },

    resolveReaderViewportProbe(container, mode = "top") {
      if (!(container instanceof Element)) return null;

      const containerRect = container.getBoundingClientRect();
      const sampleX = Math.min(
        containerRect.right - 24,
        Math.max(
          containerRect.left + 24,
          containerRect.left + containerRect.width * 0.5,
        ),
      );
      const normalizedMode = String(mode || "")
        .trim()
        .toLowerCase();
      const relativeProbeY =
        normalizedMode === "focus"
          ? Math.min(
              Math.max(96, containerRect.height * 0.42),
              Math.max(96, containerRect.height - 72),
            )
          : Math.min(
              READER_VIEWPORT_TOP_PROBE_OFFSET,
              Math.max(32, containerRect.height * 0.18),
            );
      const probeY = Math.min(
        containerRect.bottom - 24,
        Math.max(containerRect.top + 24, containerRect.top + relativeProbeY),
      );

      return {
        containerRect,
        sampleX,
        probeY,
        probeOffsetTop: probeY - containerRect.top,
      };
    },

    clearReaderViewportSync() {
      this.logReaderScrollDebug("clear_viewport_sync", {
        hadRaf: this.readerScrollRaf > 0,
        hadIdleTimer: this.readerScrollIdleTimer > 0,
      });
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
      if (
        !(this.readerPartStages instanceof Map) ||
        this.readerPartStages.size === 0
      ) {
        this.readerPartStages = new Map();
        return;
      }

      this.readerPartStages.forEach((stage, host) => {
        try {
          if (stage && typeof stage.destroy === "function") {
            stage.destroy();
          }
        } catch (error) {
          console.warn("[ChatReader] destroy inline app stage failed", error);
        }

        if (host instanceof Element) {
          setRuntimeWrapperActive(host, false);
        }
      });

      this.readerPartStages = new Map();
    },

    resolveReaderWindowBounds(floor = 1) {
      const pages = this.resolveReaderPagesAroundFloor(floor);
      if (!pages.length) {
        return { start: 1, end: 0 };
      }

      const firstBounds = this.resolveReaderPageBounds(pages[0]);
      const lastBounds = this.resolveReaderPageBounds(pages[pages.length - 1]);
      return {
        start: firstBounds.start,
        end: lastBounds.end,
      };
    },

    async extendReaderWindow(direction = "backward", anchorFloor = 0) {
      if (!this.activeChat || !this.readerTotalMessages) {
        return { start: 1, end: 0 };
      }
      this.logReaderScrollDebug("extend_reader_window_start", {
        direction: String(direction || ""),
        anchorFloor: Number(anchorFloor || 0),
      });

      if (!this.readerLoadedPageStart || !this.readerLoadedPageEnd) {
        await this.setReaderWindowAroundFloor(
          anchorFloor || this.effectiveReaderAnchorFloor || 1,
          "center",
        );
        return {
          start: this.readerWindowStartFloor,
          end: this.readerWindowEndFloor,
        };
      }

      let targetPage = 0;
      if (direction === "backward") {
        targetPage = this.readerLoadedPageStart - 1;
      } else if (direction === "forward") {
        targetPage = this.readerLoadedPageEnd + 1;
      }

      if (!targetPage || targetPage < 1 || targetPage > this.readerTotalPages) {
        return {
          start: this.readerWindowStartFloor,
          end: this.readerWindowEndFloor,
        };
      }

      await this.loadReaderPageSet([targetPage], { reset: false });
      this.logReaderScrollDebug("extend_reader_window_done", {
        direction: String(direction || ""),
        targetPage,
      });
      return {
        start: this.readerWindowStartFloor,
        end: this.readerWindowEndFloor,
      };
    },

    async setReaderWindowAroundFloor(floor = 1, mode = "center") {
      if (!this.activeChat || !this.readerTotalMessages) {
        this.resetReaderLoadedPages(false);
        return { start: 1, end: 0 };
      }
      this.logReaderScrollDebug("set_reader_window_around_floor_start", {
        floor: Number(floor || 0),
        mode: String(mode || ""),
      });

      const pages = this.resolveReaderPagesAroundFloor(floor);
      if (!pages.length) {
        this.resetReaderLoadedPages(true);
        return { start: 1, end: 0 };
      }

      await this.loadReaderPageSet(pages, { reset: true, mode });
      this.logReaderScrollDebug("set_reader_window_around_floor_done", {
        floor: Number(floor || 0),
        mode: String(mode || ""),
        pages: pages.slice(),
      });
      return {
        start: this.readerWindowStartFloor,
        end: this.readerWindowEndFloor,
      };
    },

    async ensureReaderWindowForFloor(floor = 1, mode = "center") {
      const targetFloor = Number(floor || 0);
      if (!targetFloor) return false;
      this.logReaderScrollDebug("ensure_reader_window_start", {
        targetFloor,
        mode: String(mode || ""),
      });

      const currentStart = Number(this.readerWindowStartFloor || 1);
      const currentEnd = Number(this.readerWindowEndFloor || 0);
      if (targetFloor >= currentStart && targetFloor <= currentEnd) {
        this.logReaderScrollDebug("ensure_reader_window_hit", {
          targetFloor,
          currentStart,
          currentEnd,
        });
        return false;
      }

      const targetPage = this.resolveReaderPageForFloor(targetFloor);
      if (!targetPage) {
        this.logReaderScrollDebug("ensure_reader_window_no_page", {
          targetFloor,
        });
        return false;
      }

      if (
        this.readerLoadedPageStart &&
        targetPage === this.readerLoadedPageStart - 1
      ) {
        this.logReaderScrollDebug("ensure_reader_window_extend_backward", {
          targetFloor,
          targetPage,
        });
        await this.loadReaderPageSet([targetPage], { reset: false, mode });
        return true;
      }

      if (
        this.readerLoadedPageEnd &&
        targetPage === this.readerLoadedPageEnd + 1
      ) {
        this.logReaderScrollDebug("ensure_reader_window_extend_forward", {
          targetFloor,
          targetPage,
        });
        await this.loadReaderPageSet([targetPage], { reset: false, mode });
        return true;
      }

      this.logReaderScrollDebug("ensure_reader_window_reset_around_floor", {
        targetFloor,
        targetPage,
      });
      await this.setReaderWindowAroundFloor(targetFloor, mode);
      return true;
    },

    async loadPreviousReaderWindow() {
      if (!this.hasEarlierReaderWindow) return;

      const previousStart = Number(this.readerWindowStartFloor || 1);
      await this.extendReaderWindow("backward", previousStart);
      this.$nextTick(() =>
        this.scrollToFloor(
          previousStart,
          false,
          "auto",
          READER_ANCHOR_SOURCES.NAVIGATOR,
        ),
      );
    },

    async loadNextReaderWindow() {
      if (!this.hasLaterReaderWindow) return;

      const previousEnd = Number(this.readerWindowEndFloor || 0);
      await this.extendReaderWindow("forward", previousEnd);
      this.$nextTick(() =>
        this.scrollToFloor(
          previousEnd,
          false,
          "auto",
          READER_ANCHOR_SOURCES.NAVIGATOR,
        ),
      );
    },

    resolveReaderViewportFloor(container, reason = "generic") {
      if (!(container instanceof Element)) return 0;

      const topProbe = this.resolveReaderViewportProbe(container, "top");
      const focusProbe = this.resolveReaderViewportProbe(container, "focus");
      const probe = topProbe || focusProbe;
      if (!probe) return 0;

      const { containerRect } = probe;
      if (!containerRect.width || !containerRect.height) return 0;

      const report = (resultFloor, strategy) => {
        const floor = Number(resultFloor || 0);
        this.logReaderScrollDebug("resolve_viewport_floor", {
          reason: String(reason || "generic"),
          resultFloor: floor,
          strategy: String(strategy || ""),
        });
        return floor;
      };

      const viewportTop = containerRect.top;
      const viewportBottom = containerRect.bottom;
      const visibleCards = Array.from(
        container.querySelectorAll("[data-chat-floor]"),
      )
        .map((card) => {
          if (!(card instanceof Element)) return null;
          const rect = card.getBoundingClientRect();
          const visibleTop = Math.max(rect.top, viewportTop);
          const visibleBottom = Math.min(rect.bottom, viewportBottom);
          const visibleHeight = Math.max(0, visibleBottom - visibleTop);

          if (visibleHeight <= 0) {
            return null;
          }

          return {
            card,
            rect,
            visibleTop,
            visibleBottom,
            visibleHeight,
          };
        })
        .filter(Boolean);
      if (!visibleCards.length) return 0;

      const resolveProbeFloor = (probeInfo, domStrategy, visibleStrategy) => {
        if (!probeInfo) return 0;

        const probeCard = findReaderFloorCardAtProbe(
          container,
          probeInfo.sampleX,
          probeInfo.probeY,
        );
        if (probeCard instanceof Element) {
          const floor = Number(probeCard.getAttribute("data-chat-floor") || 0);
          if (floor > 0) {
            return report(floor, domStrategy);
          }
        }

        const containingCard = visibleCards.find(
          ({ rect }) =>
            rect.top <= probeInfo.probeY && rect.bottom >= probeInfo.probeY,
        );
        const floor = Number(
          containingCard?.card?.getAttribute("data-chat-floor") || 0,
        );
        if (floor > 0) {
          return report(floor, visibleStrategy);
        }

        return 0;
      };

      const topProbeFloor = resolveProbeFloor(
        topProbe,
        "top_probe_dom",
        "top_probe_visible",
      );
      if (topProbeFloor > 0) {
        return topProbeFloor;
      }

      const topProbeY = Number(topProbe?.probeY || viewportTop);
      const nearestTopVisibleCard = visibleCards.slice().sort((left, right) => {
        const leftDistance = Math.abs(left.visibleTop - topProbeY);
        const rightDistance = Math.abs(right.visibleTop - topProbeY);
        if (leftDistance !== rightDistance) {
          return leftDistance - rightDistance;
        }
        if (left.visibleTop !== right.visibleTop) {
          return left.visibleTop - right.visibleTop;
        }
        if (left.visibleHeight !== right.visibleHeight) {
          return right.visibleHeight - left.visibleHeight;
        }
        return left.rect.top - right.rect.top;
      })[0];
      const nearestTopVisibleFloor = Number(
        nearestTopVisibleCard?.card?.getAttribute("data-chat-floor") || 0,
      );
      if (nearestTopVisibleFloor > 0) {
        return report(nearestTopVisibleFloor, "nearest_top_visible");
      }

      const focusProbeFloor = resolveProbeFloor(
        focusProbe,
        "focus_probe_dom",
        "focus_probe_visible",
      );
      if (focusProbeFloor > 0) {
        return focusProbeFloor;
      }

      const dominantVisibleCard = visibleCards.slice().sort((left, right) => {
        if (left.visibleHeight !== right.visibleHeight) {
          return right.visibleHeight - left.visibleHeight;
        }
        const leftMid = left.rect.top + (left.rect.bottom - left.rect.top) / 2;
        const rightMid =
          right.rect.top + (right.rect.bottom - right.rect.top) / 2;
        const focusProbeY = Number(focusProbe?.probeY || topProbeY);
        const leftDistance = Math.abs(leftMid - focusProbeY);
        const rightDistance = Math.abs(rightMid - focusProbeY);
        if (leftDistance !== rightDistance) {
          return leftDistance - rightDistance;
        }
        return left.rect.top - right.rect.top;
      })[0];
      const dominantVisibleFloor = Number(
        dominantVisibleCard?.card?.getAttribute("data-chat-floor") || 0,
      );
      if (dominantVisibleFloor > 0) {
        return report(dominantVisibleFloor, "dominant_visible");
      }

      const firstVisible = visibleCards
        .slice()
        .sort((left, right) => left.rect.top - right.rect.top)[0];
      return report(
        Number(firstVisible?.card?.getAttribute("data-chat-floor") || 0),
        "first_visible",
      );
    },

    syncReaderViewportFloor(options = {}) {
      if (this.isReaderPageMode) {
        return;
      }

      const run = () => {
        const root = document.querySelector(".chat-reader-overlay--fullscreen");
        const container = root
          ? root.querySelector(".chat-reader-center")
          : null;
        if (!container) return;

        const nextFloor = this.resolveReaderViewportFloor(
          container,
          options.force === false ? "sync_scroll" : "sync_idle",
        );
        if (!nextFloor) return;

        const currentFloor = Number(this.readerViewportFloor || 0);
        const renderNearby = Number(
          this.readerViewSettings.renderNearbyCount ??
            DEFAULT_CHAT_READER_VIEW_SETTINGS.renderNearbyCount,
        );
        const shouldForce = options.force !== false;
        const floorDelta = currentFloor
          ? Math.abs(nextFloor - currentFloor)
          : Number.POSITIVE_INFINITY;
        const viewportChanged = nextFloor !== currentFloor;

        if (viewportChanged) {
          this.readerViewportFloor = nextFloor;
        }

        if (
          viewportChanged &&
          (shouldForce || floorDelta >= Math.max(1, renderNearby))
        ) {
          void this.ensureReaderWindowForFloor(nextFloor, "center");
        }
      };

      if (options.nextTick === false) {
        run();
        return;
      }

      this.$nextTick(run);
    },

    scheduleReaderViewportSync() {
      if (!this.detailOpen || this.readerAppMode || this.isReaderPageMode)
        return;

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
      }, READER_VIEWPORT_SYNC_IDLE_MS);
    },

    syncReaderMobileHeaderVisibility(container) {
      if (
        this.readerResponsiveMode !== "mobile" ||
        !(container instanceof Element) ||
        this.readerMobilePanel
      ) {
        return;
      }

      const previousHidden = this.readerMobileHeaderHidden;
      const nextTop = Math.max(0, Number(container.scrollTop || 0));
      const delta = nextTop - Number(this.readerLastScrollTop || 0);
      if (nextTop <= 24 || delta < -14) {
        this.readerMobileHeaderHidden = false;
      } else if (delta > 18 && nextTop > 72) {
        this.readerMobileHeaderHidden = true;
      }
      this.readerLastScrollTop = nextTop;
      if (previousHidden !== this.readerMobileHeaderHidden) {
        this.updateReaderLayoutMetrics();
      }
    },

    handleReaderScroll() {
      const center = document.querySelector(".chat-reader-center");
      if (center) {
        this.syncReaderMobileHeaderVisibility(center);
      }

      if (this.isReaderPageMode) {
        return;
      }

      this.scheduleReaderViewportSync();
    },

    handleRegexConfigScroll(event) {
      if (!this.regexConfigOpen || this.readerResponsiveMode !== "mobile") {
        return;
      }

      const container = event?.target;
      if (!(container instanceof Element)) {
        return;
      }

      const nextTop = Math.max(0, Number(container.scrollTop || 0));
      const previousTop = Number(container.dataset.prevScrollTop || 0);
      const delta = nextTop - previousTop;
      const previousHidden = this.regexConfigMobileHeaderHidden;

      if (nextTop <= 24 || delta < -12) {
        this.regexConfigMobileHeaderHidden = false;
      } else if (delta > 16 && nextTop > 64) {
        this.regexConfigMobileHeaderHidden = true;
      }

      container.dataset.prevScrollTop = String(nextTop);

      if (previousHidden !== this.regexConfigMobileHeaderHidden) {
        this.updateRegexConfigLayoutMetrics();
      }
    },

    saveReaderViewSettings() {
      this.readerViewSettings = normalizeViewSettings(this.readerViewSettings);
      storeViewSettings(this.readerViewSettings);
      this.readerViewSettingsOpen = false;
      this.rebuildActiveChatMessages(this.activeRegexConfig);
      resetReaderVisibleMessagesCache(this);
      this.syncReaderViewportFloor();
      this.setReaderFeedbackTone("success");
      this.$store.global.showToast("阅读视图设置已保存", 1500);
    },

    resetReaderViewSettings() {
      this.readerViewSettings = normalizeViewSettings(
        DEFAULT_CHAT_READER_VIEW_SETTINGS,
      );
      storeViewSettings(this.readerViewSettings);
      this.rebuildActiveChatMessages(this.activeRegexConfig);
      resetReaderVisibleMessagesCache(this);
      this.syncReaderViewportFloor();
    },

    toggleReaderPanel(side) {
      const isMobile = this.readerResponsiveMode === "mobile";

      if (isMobile) {
        const panel = side === "left" ? "tools" : "search";
        const isSamePanelOpen = this.readerMobilePanel === panel;
        if (isSamePanelOpen) {
          this.hideReaderPanels();
          return;
        }
        this.setReaderMobilePanel(panel);
        return;
      }

      if (this.readerAppMode && side === "right") {
        this.readerShowRightPanel = !this.readerShowRightPanel;
        this.updateReaderLayoutMetrics();
        return;
      }

      if (side === "left") {
        const next = !this.readerShowLeftPanel;
        this.readerShowLeftPanel = next;
        if (this.readerResponsiveMode === "tablet" && next) {
          this.readerShowRightPanel = false;
        }
        if (isMobile && next) {
          this.readerShowRightPanel = false;
        }
        this.updateReaderLayoutMetrics();
        return;
      }

      if (side === "right") {
        if (this.readerResponsiveMode !== "mobile") {
          this.openReaderDesktopPanel(
            this.readerRightTab === "floors" ? "navigator" : "search",
          );
          return;
        }
        const next = !this.readerShowRightPanel;
        this.readerShowRightPanel = next;
        if (isMobile && next) {
          this.readerShowLeftPanel = false;
        }
        if (
          next &&
          this.activeChat &&
          (!Array.isArray(this.readerNavBatchItems) ||
            this.readerNavBatchItems.length === 0)
        ) {
          void this.syncReaderNavBatchForFloor(
            this.effectiveReaderAnchorFloor ||
              this.readerViewportFloor ||
              this.activeChat.last_view_floor ||
              1,
            { force: true },
          );
        }
        this.updateReaderLayoutMetrics();
      }
    },

    syncMobileReaderPanelState(panel) {
      const normalized = String(panel || "").trim();
      const active =
        normalized === "tools" ||
        normalized === "search" ||
        normalized === "navigator"
          ? normalized
          : "";
      this.readerMobilePanel = active;
      this.readerShowLeftPanel = active === "tools";
      this.readerShowRightPanel = active === "search" || active === "navigator";
      if (active === "search") {
        this.readerRightTab = "search";
      } else if (active === "navigator") {
        this.readerRightTab = "floors";
      }
      if (
        active === "navigator" &&
        this.activeChat &&
        (!Array.isArray(this.readerNavBatchItems) ||
          this.readerNavBatchItems.length === 0)
      ) {
        void this.syncReaderNavBatchForFloor(
          this.effectiveReaderAnchorFloor ||
            this.readerViewportFloor ||
            this.activeChat.last_view_floor ||
            1,
          { force: true },
        );
      }
      this.updateReaderLayoutMetrics();
    },

    reconcileReaderPanelsForDeviceType() {
      const responsiveMode = this.readerResponsiveMode;

      if (responsiveMode === "mobile") {
        this.readerMobileHeaderHidden = false;
        if (
          !this.readerMobilePanel &&
          (this.readerShowLeftPanel || this.readerShowRightPanel)
        ) {
          this.readerMobilePanel = this.readerShowLeftPanel
            ? "tools"
            : this.readerRightTab === "floors"
              ? "navigator"
              : "search";
        }

        if (this.readerMobilePanel) {
          this.readerShowLeftPanel = this.readerMobilePanel === "tools";
          this.readerShowRightPanel =
            this.readerMobilePanel === "search" ||
            this.readerMobilePanel === "navigator";
          this.syncMobileReaderPanelState(this.readerMobilePanel);
          return;
        }

        this.hideReaderPanels();
        return;
      }

      if (responsiveMode === "tablet") {
        if (this.readerMobilePanel === "tools") {
          this.readerShowLeftPanel = true;
          this.readerShowRightPanel = false;
        } else if (
          this.readerMobilePanel === "search" ||
          this.readerMobilePanel === "navigator"
        ) {
          this.readerShowLeftPanel = false;
          this.readerShowRightPanel = true;
          this.readerRightTab =
            this.readerMobilePanel === "navigator" ? "floors" : "search";
        } else if (!this.readerShowLeftPanel && !this.readerShowRightPanel) {
          this.readerShowLeftPanel = true;
          this.readerShowRightPanel = false;
        }

        this.readerMobilePanel = "";
        this.updateReaderLayoutMetrics();
        return;
      }

      if (this.readerMobilePanel === "navigator") {
        this.readerRightTab = "floors";
      } else if (this.readerMobilePanel === "search") {
        this.readerRightTab = "search";
      }

      this.readerMobilePanel = "";
      if (!this.readerShowLeftPanel && !this.readerShowRightPanel) {
        this.readerShowLeftPanel = true;
        this.readerShowRightPanel = true;
      }
      this.updateReaderLayoutMetrics();
    },

    setReaderMobilePanel(panel) {
      if (this.readerResponsiveMode !== "mobile") return;
      const normalized = String(panel || "").trim();
      if (this.readerMobilePanel === normalized) {
        this.hideReaderPanels();
        return;
      }
      this.readerMobileHeaderHidden = false;
      this.syncMobileReaderPanelState(normalized);
    },

    hideReaderPanels() {
      if (this.readerResponsiveMode === "mobile") {
        this.readerMobilePanel = "";
        this.readerShowLeftPanel = false;
        this.readerShowRightPanel = false;
        this.readerMobileHeaderHidden = false;
        this.updateReaderLayoutMetrics();
        return;
      }

      this.readerShowLeftPanel = false;
      this.readerShowRightPanel = false;
      this.updateReaderLayoutMetrics();
    },

    formatChatDate(ts) {
      const output = formatDate(ts);
      return output || "-";
    },

    formatDate(ts) {
      return this.formatChatDate(ts);
    },

    floorToneClass(floor) {
      const num = Number(floor || 0);
      if (num >= 1000) return "chat-card-floor-extreme";
      if (num >= 500) return "chat-card-floor-high";
      if (num >= 100) return "chat-card-floor-mid";
      return "chat-card-floor-low";
    },

    messageBadgeClass(message) {
      if (message.is_user) return "is-user";
      if (message.is_system) return "is-system";
      return "is-assistant";
    },

    clearLinkedCardFilter() {
      this.linkedCardIdFilter = "";
      this.linkedCardNameFilter = "";
      this.chatCurrentPage = 1;
      this.fetchChats();
    },

    async reloadActiveChat() {
      if (!this.activeChat || !this.activeChat.id) return;
      this.readerPageRequestToken += 1;
      const requestToken = this.readerPageRequestToken;
      const res = await getChatDetail(this.activeChat.id, {
        include_message_index: false,
      });
      if (requestToken !== this.readerPageRequestToken) return;
      if (!res.success || !res.chat) return;
      const preserveViewportFloor = Number(
        this.readerViewportFloor || this.effectiveReaderAnchorFloor || 1,
      );
      const preserveAnchorFloor = Number(
        this.effectiveReaderAnchorFloor || preserveViewportFloor || 1,
      );
      this.readerPageSize = Math.max(
        1,
        Number(
          res.chat.page_size || this.readerPageSize || CHAT_READER_PAGE_SIZE,
        ),
      );
      this.activeChat = this.buildReaderManifestChat(res.chat);
      this.readerNavBatchItems = [];
      this.readerNavBatchLoading = false;
      this.readerNavRangeStartFloor = 0;
      this.readerNavRangeEndFloor = 0;
      this.detailDraftName = this.activeChat.display_name || "";
      this.detailDraftNotes = this.activeChat.notes || "";
      this.readerViewportFloor = Math.min(
        Math.max(1, preserveViewportFloor),
        Math.max(1, this.readerTotalMessages || 1),
      );
      this.readerAnchorFloor = Math.min(
        Math.max(1, preserveAnchorFloor),
        Math.max(1, this.readerTotalMessages || 1),
      );
      await this.loadBoundCardRegexConfig(this.activeChat);
      if (requestToken !== this.readerPageRequestToken) return;
      this.readerResolvedRegexConfig = normalizeRegexConfig(
        this.activeRegexConfig,
      );
      this.syncReaderPageGroupForFloor(
        this.effectiveReaderAnchorFloor || this.readerViewportFloor || 1,
        {
          anchorFloor:
            this.effectiveReaderAnchorFloor || this.readerViewportFloor || 1,
          source: READER_ANCHOR_SOURCES.RESTORE,
        },
      );
      await Promise.all([
        this.setReaderWindowAroundFloor(
          this.effectiveReaderAnchorFloor || this.readerViewportFloor || 1,
          "center",
        ),
        this.syncReaderNavBatchForFloor(
          this.effectiveReaderAnchorFloor || this.readerViewportFloor || 1,
          { force: true },
        ),
      ]);
      if (requestToken !== this.readerPageRequestToken) return;
      this.detectChatAppMode();
      this.regexConfigDraft = this.getChatOwnedRegexConfig(this.activeChat);
      this.selectedActiveRegexRuleIndex = 0;
      this.selectedDraftRegexRuleIndex = 0;
      this.regexConfigSourceLabel = this.describeRegexConfigSource(
        this.activeChat,
      );
      this.$nextTick(() => {
        this.mountChatAppStage();
        this.syncChatAppStage();
      });
    },

    describeRegexConfigSource(chat = null) {
      const target = chat || this.activeChat;
      if (
        this.savedChatRegexRuleCount > 0 &&
        target?.bound_card_id &&
        hasCustomRegexConfig(this.activeCardRegexConfig)
      ) {
        return "当前生效：角色卡继承 + 聊天自定义";
      }
      if (this.savedChatRegexRuleCount > 0) return "当前生效：聊天自定义规则";
      if (
        target?.bound_card_id &&
        hasCustomRegexConfig(this.activeCardRegexConfig)
      )
        return "当前生效：角色卡继承规则";
      if (target?.bound_card_id) return "已绑定角色卡，但当前没有可用解析规则";
      return "当前没有可用解析规则";
    },

    async loadBoundCardRegexConfig(chat = null) {
      const target = chat || this.activeChat;
      if (!target?.bound_card_id) {
        this.activeCardRegexConfig = normalizeRegexConfig(
          EMPTY_CHAT_READER_REGEX_CONFIG,
          { fillDefaults: false },
        );
        this.activeBoundCardDetail = null;
        if (target && typeof target === "object") {
          target.bound_card_resource_folder = "";
        }
        return;
      }

      try {
        const detail = await getCardDetail(target.bound_card_id, {
          regex_only: true,
        });
        if (!detail?.success) {
          this.activeCardRegexConfig = normalizeRegexConfig(
            EMPTY_CHAT_READER_REGEX_CONFIG,
            { fillDefaults: false },
          );
          this.activeBoundCardDetail = null;
          if (target && typeof target === "object") {
            target.bound_card_resource_folder = "";
          }
          return;
        }
        this.activeCardRegexConfig = dedupeRegexConfig(
          deriveReaderConfigFromCard(detail),
        );
        this.activeBoundCardDetail = detail;
        if (target && typeof target === "object") {
          target.bound_card_resource_folder =
            detail.card?.resource_folder || "";
        }
      } catch {
        this.activeCardRegexConfig = normalizeRegexConfig(
          EMPTY_CHAT_READER_REGEX_CONFIG,
          { fillDefaults: false },
        );
        this.activeBoundCardDetail = null;
        if (target && typeof target === "object") {
          target.bound_card_resource_folder = "";
        }
      }
    },

    detectChatAppMode() {
      const loadedMessages = Array.isArray(this.activeChat?.messages)
        ? this.activeChat.messages.filter(
            (item) => item && typeof item === "object" && item.__loaded,
          )
        : [];

      if (!this.activeChat || this.readerTotalMessages <= 0) {
        this.readerAppMode = false;
        this.readerAppFloor = 0;
        this.readerAppSignature = "";
        this.readerAppDebug = {
          checkedCount: 0,
          detectedFloor: 0,
          matchedFloors: [],
          status: "当前聊天没有可读取楼层",
        };
        if (this.chatAppStage) {
          this.chatAppStage.clear();
        }
        return;
      }

      if (!loadedMessages.length) {
        this.readerAppMode = false;
        this.readerAppFloor = 0;
        this.readerAppSignature = "";
        this.readerAppDebug = {
          checkedCount: 0,
          detectedFloor: 0,
          matchedFloors: [],
          status: "当前锚点附近分页尚未载入完成",
        };
        if (this.chatAppStage) {
          this.chatAppStage.clear();
        }
        return;
      }

      const matchedFloors = this.executableMessageFloors.filter((floor) =>
        this.getReaderRawMessageForFloor(floor),
      );
      const currentFloor = Number(
        this.effectiveReaderAnchorFloor ||
          this.readerViewportFloor ||
          this.activeChat.last_view_floor ||
          0,
      );
      const candidateFloor = pickNearestReaderFloor(
        matchedFloors,
        currentFloor,
      );

      if (!candidateFloor) {
        this.readerAppMode = false;
        this.readerAppFloor = 0;
        this.readerAppSignature = "";
        this.readerAppDebug = {
          checkedCount: loadedMessages.length,
          detectedFloor: 0,
          matchedFloors: [],
          status: `未检测到整页实例（已检查当前载入的 ${loadedMessages.length} 条消息）`,
        };
        if (this.chatAppStage) {
          this.chatAppStage.clear();
        }
        return;
      }

      this.readerAppFloor = candidateFloor;
      this.readerAppDebug = {
        checkedCount: loadedMessages.length,
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
      if (!this.readerAppMode || !this.activeChat) {
        return null;
      }

      const floor = Number(this.readerAppFloor || 0);
      if (!floor) {
        return null;
      }

      const rawMessage = this.getReaderRawMessageForFloor(floor);
      const parsedMessage = this.getReaderMessageForFloor(floor);
      const parsedMessageForFloor = this.getReaderMessageForFloor(floor);
      if (!rawMessage || !parsedMessageForFloor?.__loaded) {
        return null;
      }
      const selectedPart = this.resolveRenderedRuntimePart(
        parsedMessageForFloor,
      );

      if (!selectedPart?.text) {
        return null;
      }

      const partAnalysis = scoreFullPageAppHtml(
        String(selectedPart.text || ""),
      );

      return {
        floor,
        htmlPayload: String(selectedPart.text || ""),
        assetBase: this.activeReaderAssetBase,
        context: buildChatAppCompatContext(
          this.activeChat.raw_messages || [],
          floor,
          rawMessage,
          parsedMessageForFloor || parsedMessage,
          this.activeChat,
          this.activeBoundCardDetail,
        ),
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
        this.$store.global.showToast(
          `楼层 #${targetFloor} 没有可执行的前端实例`,
          2200,
        );
        return;
      }

      this.readerAppFloor = targetFloor;
      this.readerAppMode = true;
      const shouldPromoteAnchor = shouldPromoteReaderAnchorForSource(
        this.readerAnchorMode,
        READER_ANCHOR_SOURCES.APP_STAGE,
      );
      if (shouldPromoteAnchor) {
        this.updateReaderAnchorFloor(
          targetFloor,
          READER_ANCHOR_SOURCES.APP_STAGE,
        );
      } else {
        this.readerViewportFloor = targetFloor;
        this.readerAnchorSource = READER_ANCHOR_SOURCES.APP_STAGE;
      }
      this.$nextTick(() => {
        this.mountChatAppStage();
        this.syncChatAppStage();
      });
    },

    stepReaderAppFloor(direction = 1) {
      const floors = this.executableMessageFloors;
      if (!floors.length) return;

      const currentIndex = Math.max(
        0,
        floors.indexOf(Number(this.readerAppFloor || floors[0])),
      );
      const nextIndex = Math.min(
        floors.length - 1,
        Math.max(0, currentIndex + (direction >= 0 ? 1 : -1)),
      );
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
        this.readerAppSignature = "";
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
        this.$store.global.showToast(
          this.readerAppDebug.status || "当前聊天未检测到整页前端实例",
          2200,
        );
        return;
      }

      this.readerAppMode = true;

      const isMobile = this.$store.global.deviceType === "mobile";
      if (isMobile) {
        this.hideReaderPanels();
      }

      this.setReaderAppFloor(this.readerAppFloor);
    },

    deactivateChatAppStage() {
      this.readerAppMode = false;
      this.readerAppSignature = "";
      if (this.chatAppStage) {
        this.chatAppStage.clear({ resetSession: true });
      }
      this.$nextTick(() => this.updateReaderLayoutMetrics());
    },

    formatChatAppSendDate() {
      const now = new Date();
      const formatted = now.toLocaleString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
      return formatted
        .replace(", ", " ")
        .replace(" AM", "am")
        .replace(" PM", "pm");
    },

    async appendChatAppUserMessage(text) {
      if (!this.activeChat) return false;

      const rawMessages = await this.fetchCompleteRawMessages();
      if (!Array.isArray(rawMessages)) return false;
      rawMessages.push({
        name: "User",
        is_user: true,
        is_system: false,
        mes: String(text || ""),
        send_date: this.formatChatAppSendDate(),
        extra: {},
        force_avatar: this.activeChat.force_avatar || "",
      });

      const ok = await this.persistChatContent(
        rawMessages,
        "已追加实例交互消息",
        null,
        {
          focusFloor: rawMessages.length,
        },
      );
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
      const source = String(command || "").trim();
      if (!source) return;

      const pipeline = source
        .split("|")
        .map((item) => item.trim())
        .filter(Boolean);
      const sendSegment = pipeline.find((item) => /^\/send\s+/i.test(item));
      const triggerSegment = pipeline.find((item) =>
        /^\/trigger\b/i.test(item),
      );

      if (!sendSegment) {
        this.$store.global.showToast(`实例请求执行命令: ${source}`, 2200);
        return;
      }

      const message = sendSegment.replace(/^\/send\s+/i, "").trim();
      if (!message) {
        this.$store.global.showToast("实例发送内容为空，已忽略", 1800);
        return;
      }

      const ok = await this.appendChatAppUserMessage(message);
      if (!ok) return;

      if (triggerSegment) {
        this.$store.global.showToast(
          "已追加用户消息，自动触发生成暂未接入",
          2200,
        );
      }
    },

    rebuildActiveChatMessages(config = null) {
      if (!this.activeChat) return;

      const nextConfig = normalizeRegexConfig(config || this.activeRegexConfig);
      this.readerResolvedRegexConfig = nextConfig;
      const messages = Array.isArray(this.activeChat.messages)
        ? [...this.activeChat.messages]
        : createReaderManifestMessages(
            this.activeChat.message_index,
            this.readerTotalMessages,
          );
      const rawMessages = Array.isArray(this.activeChat.raw_messages)
        ? this.activeChat.raw_messages
        : Array.from({ length: this.readerTotalMessages }, () => null);
      const isTailCompatible =
        this.readerAnchorMode === READER_ANCHOR_MODES.TAIL_COMPATIBLE;
      const total = Math.max(messages.length, this.readerTotalMessages);
      const anchorFloor = Number(
        (isTailCompatible ? total : this.readerAnchorFloor) ||
          this.readerViewportFloor ||
          this.activeChat.last_view_floor ||
          total ||
          1,
      );
      const rawTailKeepaliveCount = resolveReaderTailKeepaliveCount(
        this.readerViewSettings,
        total,
        anchorFloor,
        this.readerAnchorMode,
      );
      const tailKeepaliveCount = rawTailKeepaliveCount;
      const legacyReaderDepthMode = resolveReaderLegacyDepthMode(
        this.readerAnchorMode,
      );
      const depthLookup = createReaderDepthLookup(messages, anchorFloor);
      const currentPageFloors = this.getCurrentReaderPageFloors();
      const currentPageFloorSet = currentPageFloors.length
        ? new Set(currentPageFloors)
        : null;
      this.logReaderScrollDebug("rebuild_active_chat_messages_start", {
        anchorFloor,
        total,
        tailKeepaliveCount,
      });

      const nextMessages = messages.map((baseMessage, index) => {
        const floor = index + 1;
        const manifest =
          baseMessage && typeof baseMessage === "object"
            ? baseMessage
            : createReaderManifestMessage(
                this.activeChat.message_index?.[index],
                floor,
              );
        const rawMessage =
          rawMessages[index] && typeof rawMessages[index] === "object"
            ? rawMessages[index]
            : null;
        const depthInfo = resolveReaderDepthInfoFromLookup(depthLookup, floor);
        const macroContext = this.buildReaderRegexMacroContext(
          rawMessage || manifest,
          floor,
        );
        const pageDepthOverride = currentPageFloorSet?.has(floor)
          ? {
              ignoreDepthLimits: true,
              scopedFloors: currentPageFloors,
            }
          : {
              ignoreDepthLimits: false,
              scopedFloors: [],
            };
        const runtimeDepthInfo = {
          ...depthInfo,
          placement: resolveReaderRegexPlacement(rawMessage || manifest),
          macroContext,
          legacyReaderDepthMode,
          ignoreDepthLimits: pageDepthOverride.ignoreDepthLimits,
          scopedFloors: pageDepthOverride.scopedFloors,
          cacheKey: buildReaderDisplaySourceCacheKey(
            nextConfig,
            anchorFloor,
            this.readerAnchorMode,
            pageDepthOverride,
          ),
        };

        if (!rawMessage) {
          return {
            ...manifest,
            tail_depth: depthInfo.tailDepth,
            display_source: "",
            display_source_cache_key: "",
            rendered_display_html: "",
            __loaded: false,
            __readerRegexConfig: nextConfig,
            __readerDepthInfo: runtimeDepthInfo,
            __readerEnhancementMeta: {
              hasReasoning: false,
              reasoningText: "",
              reasoningPreview: "",
              reasoningState: "none",
              hasLongCode: false,
              hasRuntimeCandidate: false,
              codeBlockCount: 0,
            },
          };
        }

        const parsedMessage = buildReaderParsedMessage(
          rawMessage,
          floor,
          nextConfig,
          {
            chatId: this.activeChat?.id || "",
            macroContext,
            tailDepth: depthInfo.tailDepth,
          },
        );
        const enhancementMeta = extractReaderEnhancementMetadata(
          rawMessage,
          parsedMessage,
        );
        const normalizedEnhancementMeta = {
          hasReasoning: false,
          reasoningText: "",
          reasoningPreview: "",
          reasoningState: "none",
          hasLongCode: false,
          hasRuntimeCandidate: false,
          codeBlockCount: 0,
          ...(enhancementMeta && typeof enhancementMeta === "object"
            ? enhancementMeta
            : {}),
        };
        if (
          normalizedEnhancementMeta.hasReasoning &&
          !String(normalizedEnhancementMeta.reasoningText || "").trim()
        ) {
          Object.assign(normalizedEnhancementMeta, {
            reasoningState: "missing",
          });
        }

        return {
          ...manifest,
          ...parsedMessage,
          preview_text:
            manifest.preview_text ||
            parsedMessage.content ||
            parsedMessage.mes ||
            "",
          __loaded: true,
          __readerRegexConfig: nextConfig,
          __readerDepthInfo: runtimeDepthInfo,
          __readerEnhancementMeta: normalizedEnhancementMeta,
        };
      });
      this.activeChat.messages = nextMessages;
      this._readerDepthLookupCache = {
        messagesRef: nextMessages,
        anchorFloor,
        lookup: depthLookup,
      };
      this._renderedFloorHtmlCache = new Map();
      this._readerRenderedDisplayCache = new Map();
      this.activeChat.runtime_candidate_cache = createRuntimeCandidateCache();
      this.readerAnchorFloor = anchorFloor;
      const renderBands = resolveReaderRenderBandRanges(
        this.readerViewSettings,
        total,
        anchorFloor,
      );
      const warmupStart = Math.max(
        1,
        Math.min(renderBands.expansionStartFloor, renderBands.simpleStartFloor),
      );
      const warmupEnd = Math.min(
        total,
        Math.max(
          renderBands.expansionEndFloor,
          renderBands.simpleEndFloor,
          tailKeepaliveCount > 0 ? total : 0,
        ),
      );

      const pageWarmupFloors = this.isReaderPageMode
        ? this.collectReaderPageWarmupFloors(
            null,
            CHAT_READER_PAGE_GROUP_PREFETCH_RADIUS,
          )
        : [];
      if (pageWarmupFloors.length) {
        pageWarmupFloors.forEach((floor) => {
          const message = this.activeChat.messages[floor - 1];
          if (message?.__loaded) {
            this.ensureMessageDisplaySource(message);
          }
        });
      } else {
        for (let floor = warmupStart; floor <= warmupEnd; floor += 1) {
          const message = this.activeChat.messages[floor - 1];
          if (message?.__loaded) {
            this.ensureMessageDisplaySource(message);
          }
        }
      }
      resetReaderVisibleMessagesCache(this);
      this.logReaderScrollDebug("rebuild_active_chat_messages_done", {
        anchorFloor,
        total,
        warmupStart,
        warmupEnd,
      });
    },

    updateRegexDraftField(field, value) {
      this.regexConfigDraft = {
        ...this.regexConfigDraft,
        [field]: value,
      };
    },

    setRegexDraftDisplayRules(nextRules) {
      this.regexConfigDraft = {
        ...this.regexConfigDraft,
        displayRules: nextRules,
      };
    },

    selectActiveRegexRule(index) {
      const normalizedIndex = Number(index);
      this.selectedActiveRegexRuleIndex =
        Number.isFinite(normalizedIndex) && normalizedIndex >= 0
          ? normalizedIndex
          : 0;
    },

    selectDraftRegexRule(index) {
      const normalizedIndex = Number(index);
      this.selectedDraftRegexRuleIndex =
        Number.isFinite(normalizedIndex) && normalizedIndex >= 0
          ? normalizedIndex
          : 0;
    },

    getRegexRuleInspector(rule, index = 0) {
      return inspectRegexDisplayRule(rule, index);
    },

    findRegexDraftRuleRawIndex(targetRule) {
      const normalizedTarget = normalizeDisplayRule(targetRule);
      const rawRules = Array.isArray(this.regexConfigDraft?.displayRules)
        ? this.regexConfigDraft.displayRules
        : [];
      const targetKeys = resolveDisplayRuleMatchKeys(normalizedTarget);
      const idMatchIndex = rawRules.findIndex(
        (item) => normalizeDisplayRule(item).id === normalizedTarget.id,
      );
      if (idMatchIndex >= 0) {
        return idMatchIndex;
      }

      return rawRules.findIndex((item) => {
        const normalizedItem = normalizeDisplayRule(item);
        const itemKeys = resolveDisplayRuleMatchKeys(normalizedItem);
        return (
          itemKeys.currentKey === targetKeys.currentKey ||
          itemKeys.currentKey === targetKeys.primaryKey ||
          itemKeys.overrideKey === targetKeys.currentKey ||
          itemKeys.overrideKey === targetKeys.primaryKey
        );
      });
    },

    cardRegexRuleExists(ruleKey = "") {
      const targetKey = String(ruleKey || "").trim();
      if (!targetKey) return false;
      return decorateRegexDisplayRules(this.activeCardRegexConfig, "card", {
        includeDeleted: true,
      }).some((rule) => buildDisplayRuleKey(rule) === targetKey);
    },

    upsertRegexDraftRuleFromSource(targetRule, patch = {}) {
      const normalizedTarget = normalizeDisplayRule(targetRule);
      const rawRules = Array.isArray(this.regexConfigDraft?.displayRules)
        ? [...this.regexConfigDraft.displayRules]
        : [];
      const rawIndex = this.findRegexDraftRuleRawIndex(normalizedTarget);
      const existingRule =
        rawIndex >= 0
          ? normalizeDisplayRule(rawRules[rawIndex], rawIndex)
          : null;
      const targetKeys = resolveDisplayRuleMatchKeys(normalizedTarget);
      const nextRule = normalizeDisplayRule(
        {
          ...(existingRule || normalizedTarget),
          ...patch,
          source:
            existingRule?.source ||
            (normalizedTarget.source === "card"
              ? "chat"
              : normalizedTarget.source || "chat"),
          overrideKey:
            existingRule?.overrideKey ||
            normalizedTarget.overrideKey ||
            (normalizedTarget.source === "card" ? targetKeys.currentKey : ""),
          expanded: true,
          deleted:
            patch.deleted === undefined
              ? Boolean(existingRule?.deleted)
              : Boolean(patch.deleted),
        },
        rawIndex >= 0 ? rawIndex : rawRules.length,
      );

      if (rawIndex >= 0) {
        rawRules[rawIndex] = nextRule;
      } else {
        rawRules.push(nextRule);
      }

      this.setRegexDraftDisplayRules(rawRules);
      return nextRule;
    },

    addRegexDisplayRule() {
      const next = Array.isArray(this.regexConfigDraft.displayRules)
        ? [...this.regexConfigDraft.displayRules]
        : [];
      next.push(
        normalizeDisplayRule({ expanded: true, source: "manual" }, next.length),
      );
      this.setRegexDraftDisplayRules(next);
      this.selectedDraftRegexRuleIndex = Math.max(
        0,
        this.regexDraftDisplayRules.length - 1,
      );
    },

    updateRegexDisplayRule(index, field, value) {
      const orderedRules = this.regexDraftDisplayRules;
      const target = orderedRules[index];
      if (!target) return;

      const targetId = target.id;
      const next = Array.isArray(this.regexConfigDraft.displayRules)
        ? this.regexConfigDraft.displayRules.map((item) => {
            const currentId = normalizeDisplayRule(item).id;
            return currentId === targetId ? { ...item, [field]: value } : item;
          })
        : [];
      this.setRegexDraftDisplayRules(next);
    },

    updateRegexDisplayRuleDepthMode(index, value) {
      const normalizedMode = normalizeReaderDepthMode(value);
      this.updateRegexDisplayRule(index, "readerDepthMode", normalizedMode);
      if (!normalizedMode) {
        this.updateRegexDisplayRule(index, "readerMinDepth", null);
        this.updateRegexDisplayRule(index, "readerMaxDepth", null);
      }
    },

    toggleRegexRuleExpanded(index) {
      const orderedRules = this.regexDraftDisplayRules;
      const target = orderedRules[index];
      if (!target) return;

      const targetId = target.id;
      const next = Array.isArray(this.regexConfigDraft.displayRules)
        ? this.regexConfigDraft.displayRules.map((item) => {
            const currentId = normalizeDisplayRule(item).id;
            return currentId === targetId
              ? { ...item, expanded: !item.expanded }
              : item;
          })
        : [];
      this.setRegexDraftDisplayRules(next);
    },

    removeRegexDisplayRule(index) {
      const orderedRules = this.regexDraftDisplayRules;
      const target = orderedRules[index];
      if (!target) return;

      const targetId = target.id;
      const next = Array.isArray(this.regexConfigDraft.displayRules)
        ? this.regexConfigDraft.displayRules.filter(
            (item) => normalizeDisplayRule(item).id !== targetId,
          )
        : [];
      this.setRegexDraftDisplayRules(next);
      this.regexConfigStatus = `已从聊天自定义草稿移除规则“${target.scriptName || `规则 ${index + 1}`}”。`;
    },

    updateSelectedActiveRegexRule(field, value) {
      const target = this.selectedActiveRegexRule;
      if (!target) return;
      this.upsertRegexDraftRuleFromSource(target, {
        [field]: value,
        deleted: false,
      });
    },

    updateSelectedActiveRegexRuleDepthMode(value) {
      const normalizedMode = normalizeReaderDepthMode(value);
      this.updateSelectedActiveRegexRule("readerDepthMode", normalizedMode);
      if (!normalizedMode) {
        this.updateSelectedActiveRegexRule("readerMinDepth", null);
        this.updateSelectedActiveRegexRule("readerMaxDepth", null);
      }
    },

    removeSelectedActiveRegexRule() {
      const target = this.selectedActiveRegexRule;
      if (!target) return;

      const normalizedTarget = normalizeDisplayRule(target);
      const rawIndex = this.findRegexDraftRuleRawIndex(normalizedTarget);
      const targetKeys = resolveDisplayRuleMatchKeys(normalizedTarget);
      const existingRule =
        rawIndex >= 0
          ? normalizeDisplayRule(
              this.regexConfigDraft.displayRules[rawIndex],
              rawIndex,
            )
          : null;
      const shouldWriteDeletionOverride = Boolean(
        normalizedTarget.source === "card" ||
        existingRule?.overrideKey ||
        this.cardRegexRuleExists(targetKeys.primaryKey) ||
        this.cardRegexRuleExists(targetKeys.currentKey),
      );

      if (!shouldWriteDeletionOverride && existingRule) {
        const next = this.regexConfigDraft.displayRules.filter(
          (_, index) => index !== rawIndex,
        );
        this.setRegexDraftDisplayRules(next);
      } else {
        this.upsertRegexDraftRuleFromSource(existingRule || normalizedTarget, {
          deleted: true,
          disabled: false,
          expanded: false,
        });
      }

      this.regexConfigStatus = `已从当前合并结果移除规则“${normalizedTarget.scriptName}”，保存后生效。`;
    },

    importRegexConfigFile(event) {
      const file = event?.target?.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = () => {
        try {
          const data = JSON.parse(String(reader.result || "{}"));
          const importedReaderConfig = extractReaderRegexConfig(data);
          if (importedReaderConfig) {
            const importedCount = Array.isArray(
              importedReaderConfig.displayRules,
            )
              ? importedReaderConfig.displayRules.length
              : 0;
            this.regexConfigDraft = importReaderRegexConfig(
              this.regexConfigDraft,
              importedReaderConfig,
              {
                fillDefaults: false,
                source: "reader_import",
                mode: "merge",
              },
            );
            this.regexConfigStatus =
              importedCount > 0
                ? `已从阅读器配置导入 ${importedCount} 条规则，保存后会并入当前聊天`
                : "已识别到阅读器配置文件，但其中没有可导入的显示规则";
            return;
          }

          const rules = parseSillyTavernRegexRules(data);
          if (!rules.length) {
            alert("未在该文件中识别到可用的聊天阅读器或 SillyTavern 正则规则");
            return;
          }

          const importableRules = filterReaderDisplayRules(rules);
          if (!importableRules.length) {
            alert("已识别到 ST 规则，但其中没有适用于聊天阅读显示的规则");
            return;
          }

          const importSource = detectImportedRegexSource(data);
          const importMeta = getRegexRuleSourceMeta(importSource);
          this.regexConfigDraft = convertRulesToReaderConfig(
            rules,
            this.regexConfigDraft,
            {
              fillDefaults: false,
              source: importSource,
              mode: "merge",
            },
          );
          this.regexConfigStatus = `已从${importMeta.label}导入 ${importableRules.length} 条聊天阅读规则，保存后会并入当前聊天`;
          return;
        } catch (err) {
          alert(`导入规则失败: ${err.message || err}`);
        } finally {
          event.target.value = "";
        }
      };
      reader.readAsText(file, "utf-8");
    },

    async clearRegexDraft() {
      const hasBoundCard = Boolean(this.activeChat?.bound_card_id);
      if (hasBoundCard) {
        await this.loadBoundCardRegexConfig(this.activeChat);
      }
      this.regexConfigDraft = normalizeRegexConfig(
        EMPTY_CHAT_READER_REGEX_CONFIG,
        { fillDefaults: false },
      );
      this.selectedActiveRegexRuleIndex = 0;
      this.selectedDraftRegexRuleIndex = 0;
      if (hasBoundCard) {
        this.regexConfigStatus =
          this.cardRegexRuleCount > 0
            ? `已重新读取角色卡规则并自动去重，当前可继承 ${this.cardRegexRuleCount} 条；保存后将恢复为角色卡继承`
            : "已清空聊天自定义规则并重新读取角色卡规则，但当前角色卡没有可继承规则";
        return;
      }
      this.regexConfigStatus = "已清空聊天自定义规则，当前聊天未绑定角色卡";
    },

    downloadRegexConfigExport(payload, filenamePrefix, statusMessage) {
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${filenamePrefix}-${Date.now()}.json`;
      link.click();
      URL.revokeObjectURL(url);
      this.regexConfigStatus = statusMessage;
    },

    exportEffectiveRegexConfig() {
      const payload = normalizeRegexConfig(
        {
          displayRules: this.activeRegexDisplayRules,
        },
        { fillDefaults: false },
      );
      this.downloadRegexConfigExport(
        payload,
        "chat-reader-effective-regex",
        "已导出当前实际生效规则",
      );
    },

    exportRegexConfigDraft() {
      const payload = normalizeRegexConfig(this.regexConfigDraft, {
        fillDefaults: false,
      });
      this.downloadRegexConfigExport(
        payload,
        "chat-reader-regex-draft",
        "已导出当前聊天自定义规则",
      );
    },

    openRegexConfig() {
      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
        window.dispatchEvent(new CustomEvent("close-header-mobile-menu"));
      }
      this.readerResolvedRegexConfig = normalizeRegexConfig(
        this.activeRegexConfig,
      );
      this.regexConfigDraft = this.getChatOwnedRegexConfig(this.activeChat);
      this.regexTestInput = "";
      this.selectedActiveRegexRuleIndex = 0;
      this.selectedDraftRegexRuleIndex = 0;
      this.regexConfigMobileHeaderHidden = false;
      this.regexConfigMobileTab = "effective";
      this.regexHelpOpen = false;
      this.regexConfigOpen = true;
      this.regexConfigTab = "extract";
      this.regexConfigSourceLabel = this.describeRegexConfigSource();
      this.regexConfigStatus = "";
      this.updateRegexConfigLayoutMetrics();
    },

    openRegexHelp() {
      if (!this.regexConfigOpen) return;
      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
        window.dispatchEvent(new CustomEvent("close-header-mobile-menu"));
      }
      this.regexHelpOpen = true;
    },

    closeRegexHelp() {
      this.regexHelpOpen = false;
    },

    closeRegexConfig() {
      this.regexConfigOpen = false;
      this.regexHelpOpen = false;
      this.regexConfigMobileHeaderHidden = false;
      this.regexConfigMobileTab = "effective";
      this.selectedActiveRegexRuleIndex = 0;
      this.selectedDraftRegexRuleIndex = 0;
      this.regexConfigStatus = "";
      this.regexConfigDraft = this.getChatOwnedRegexConfig(this.activeChat);
      this.regexConfigSourceLabel = this.describeRegexConfigSource();
    },

    async loadRegexTestInputFromCurrentFloor() {
      if (!this.activeChat) return;

      const floor = Number(
        this.effectiveReaderAnchorFloor || this.readerViewportFloor || 0,
      );
      if (!floor) {
        this.regexConfigStatus = "当前没有可加载的定位楼层。";
        return;
      }

      await this.ensureReaderWindowForFloor(floor, "center");
      const rawMessage = this.getReaderRawMessageForFloor(floor);
      const parsedMessage = this.getReaderMessageForFloor(floor);
      const indexMessage = Array.isArray(this.activeChat?.message_index)
        ? this.activeChat.message_index[floor - 1]
        : null;
      const nextText =
        rawMessage?.mes ||
        parsedMessage?.mes ||
        parsedMessage?.content ||
        parsedMessage?.preview_text ||
        indexMessage?.preview ||
        "";

      if (!String(nextText || "").trim()) {
        this.regexConfigStatus = `楼层 #${floor} 没有可用于测试的文本。`;
        return;
      }

      this.regexTestInput = String(nextText);
      this.regexConfigStatus = `已加载当前定位楼层 #${floor} 的内容到测试区。`;
    },

    clearRegexTestInput() {
      this.regexTestInput = "";
      this.regexConfigStatus = "已清空测试区。";
    },

    async saveRegexConfig() {
      if (!this.activeChat) return;

      const nextConfig = normalizeRegexConfig(this.regexConfigDraft, {
        fillDefaults: false,
      });
      const metadata = {
        ...ensureChatMetadataShape(this.activeChat.metadata),
      };
      if (hasCustomRegexConfig(nextConfig)) {
        metadata.reader_regex_config = nextConfig;
      } else {
        delete metadata.reader_regex_config;
      }
      const rawMessages = await this.fetchCompleteRawMessages();
      if (!Array.isArray(rawMessages)) return;

      const ok = await this.persistChatContent(
        rawMessages,
        hasCustomRegexConfig(nextConfig)
          ? "聊天解析规则已保存"
          : "已恢复为角色卡继承规则",
        metadata,
        { rebuild: false },
      );
      if (!ok) return;

      this.readerResolvedRegexConfig = normalizeRegexConfig(
        this.activeRegexConfig,
      );
      this.regexConfigDraft = this.getChatOwnedRegexConfig(this.activeChat);
      this.rebuildActiveChatMessages(this.activeRegexConfig);
      this.regexConfigOpen = false;
      this.selectedActiveRegexRuleIndex = 0;
      this.selectedDraftRegexRuleIndex = 0;
      this.regexConfigStatus = "";
      this.regexConfigSourceLabel = this.describeRegexConfigSource();
      this.setReaderFeedbackTone("success");
      if (this.detailSearchQuery) {
        this.searchInDetail();
      }
    },

    clearRegexConfigFromChat() {
      this.clearRegexDraft();
    },

    renderReaderContent(text) {
      const source = String(text || "").trim();
      if (!source) {
        return '<span class="chat-render-empty">空内容</span>';
      }

      if (this.readerRenderMode === "markdown") {
        return renderMarkdown(source);
      }

      return `<div>${escapeHtml(source).replace(/\n/g, "<br>")}</div>`;
    },

    renderMessageDisplayHtml(message) {
      if (
        message &&
        typeof message === "object" &&
        !message.__readerRegexConfig
      ) {
        message.__readerRegexConfig = normalizeRegexConfig(
          this.readerResolvedRegexConfig || this.activeRegexConfig,
        );
      }
      const floor = Number(message?.floor || 0);
      const chatId = resolveReaderMessageChatId(message, this.activeChat);
      const cacheKey = buildReaderRenderCacheKey({
        chatId,
        floor,
        variant: "full",
        renderMode: this.readerRenderMode,
        componentMode: this.readerComponentMode,
        html: String(message?.rendered_display_html || ""),
      });
      const cachedHtml = this.readerRenderedDisplayCache.get(cacheKey);
      if (cachedHtml) {
        return cachedHtml;
      }
      const source = String(
        this.ensureMessageDisplaySource(message) || message?.content || "",
      );
      const scopeClass = `st-reader-floor-${Number(message?.floor || 0) || 0}`;
      const flags = resolveReaderFormatFlags(message);
      const html = renderUnifiedDisplayHtml(source, {
        scopeClass,
        renderMode: this.readerRenderMode,
        speakerName: flags.speakerName,
        stripSpeakerPrefix: flags.stripSpeakerPrefix,
        encodeTags: flags.encodeTags,
        promptBias: flags.promptBias,
        hidePromptBias: flags.hidePromptBias,
        reasoningMarkers: flags.reasoningMarkers,
      });
      const enhancementMeta =
        message?.__readerEnhancementMeta ||
        extractReaderEnhancementMetadata(message, message);
      const enhancementPolicy = buildReaderEnhancementPolicy(
        "full",
        enhancementMeta,
        {
          viewportWidth: window.innerWidth,
          reasoningDefaultCollapsed:
            this.readerViewSettings?.reasoningDefaultCollapsed,
          autoCollapseLongCode: this.readerViewSettings?.autoCollapseLongCode,
        },
      );
      const decoratedHtml = this.isReaderPageMode
        ? html
        : decorateReaderRenderedHtml(html, enhancementMeta, enhancementPolicy, {
            viewportWidth: window.innerWidth,
            reasoningStartExpanded:
              this.readerViewSettings?.reasoningDefaultCollapsed === false,
          });
      if (floor > 0) {
        const previousHtml = String(
          this.renderedFloorHtmlCache.get(floor) ||
            message?.rendered_display_html ||
            "",
        );
        if (previousHtml !== decoratedHtml) {
          const cacheKey = buildReaderCacheScopeKey(
            this.activeChat,
            floor,
            message,
          );
          this.renderedFloorHtmlCache.set(floor, decoratedHtml);
          if (message && typeof message === "object") {
            message.rendered_display_html = decoratedHtml;
          }
          if (Array.isArray(this.activeChat?.messages)) {
            const originalMessage = this.activeChat.messages.find(
              (item) => Number(item?.floor || 0) === floor,
            );
            if (originalMessage && originalMessage !== message) {
              originalMessage.rendered_display_html = decoratedHtml;
            }
          }
          this.runtimeCandidateCache.floorMap.delete(cacheKey);
          this.runtimeCandidateCache.executableFloorsKey = "";
        }
      }
      this.readerRenderedDisplayCache.set(
        buildReaderRenderCacheKey({
          chatId,
          floor,
          variant: "full",
          renderMode: this.readerRenderMode,
          componentMode: this.readerComponentMode,
          html: decoratedHtml,
        }),
        decoratedHtml,
      );
      return decoratedHtml;
    },

    resolveSimpleReaderRenderMode(message, source, enhancementMeta) {
      void message;

      const normalizedSource = String(source || "");
      const lineCount = normalizedSource
        .replace(/\r\n/g, "\n")
        .split("\n").length;
      const looksLikeStructuredCode =
        lineCount >= 8 &&
        /(^|\n)\s*(const |let |var |function\b|class\b|def\b|import\b|export\b|return\b|if\b|for\b|while\b|<\/?[A-Za-z][^>]*>)/.test(
          normalizedSource,
        );

      if (
        enhancementMeta?.hasLongCode ||
        source.includes("```") ||
        looksLikeStructuredCode
      ) {
        return "literal";
      }

      return "plain";
    },

    renderMessageSimpleHtml(message) {
      if (
        message &&
        typeof message === "object" &&
        !message.__readerRegexConfig
      ) {
        message.__readerRegexConfig = normalizeRegexConfig(
          this.readerResolvedRegexConfig || this.activeRegexConfig,
        );
      }
      const source = String(
        this.ensureMessageDisplaySource(message) ||
          message?.content ||
          message?.mes ||
          "",
      );
      if (!source.trim()) {
        return '<div class="chat-message-content chat-message-content--compact">空内容</div>';
      }

      const scopeClass = `st-reader-floor-${Number(message?.floor || 0) || 0}`;
      const flags = resolveReaderFormatFlags(message);
      const enhancementMeta =
        message?.__readerEnhancementMeta ||
        extractReaderEnhancementMetadata(message, message);
      const enhancementPolicy = buildReaderEnhancementPolicy(
        "simple",
        enhancementMeta,
        {
          viewportWidth: window.innerWidth,
          reasoningDefaultCollapsed: true,
          autoCollapseLongCode: this.readerViewSettings?.autoCollapseLongCode,
        },
      );
      const baseHtml = renderUnifiedDisplayHtml(source, {
        scopeClass,
        renderMode: this.resolveSimpleReaderRenderMode(
          message,
          source,
          enhancementMeta,
        ),
        speakerName: flags.speakerName,
        stripSpeakerPrefix: flags.stripSpeakerPrefix,
        encodeTags: flags.encodeTags,
        promptBias: flags.promptBias,
        hidePromptBias: flags.hidePromptBias,
        reasoningMarkers: flags.reasoningMarkers,
        blockMedia: true,
      });
      const previewedHtml = this.isReaderPageMode
        ? baseHtml
        : decorateReaderRenderedHtml(
            baseHtml,
            enhancementMeta,
            enhancementPolicy,
            {
              viewportWidth: window.innerWidth,
            },
          );
      return previewedHtml;
    },

    syncMessageDisplay(el, message, variant = "full") {
      if (!(el instanceof Element) || !message) return;
      if (!this.detailOpen || !this.activeChat) return;

      const floor = Number(message?.floor || 0);
      const chatId = resolveReaderMessageChatId(message, this.activeChat);
      const html =
        variant === "simple"
          ? this.renderMessageSimpleHtml(message)
          : this.renderMessageDisplayHtml(message);

      if (this.shouldApplyReaderPretextIntrinsicSize(variant, message)) {
        this.applyReaderPretextIntrinsicSize(el, message, variant, html);
      }
      const signature = JSON.stringify({
        chatId,
        floor,
        variant,
        renderMode: this.readerRenderMode,
        componentMode: variant === "full" ? this.readerComponentMode : false,
        html,
      });

      if (el.__stmReaderDisplaySignature !== signature) {
        this.destroyMessageRenderPart(el);
        el.innerHTML = html;
        el.__stmReaderDisplaySignature = signature;
        el.__stmReaderDisplayVariant = variant;
      }

      if (variant === "full") {
        this.mountMessageDisplayNow(el, message);
      }
    },

    shouldApplyReaderPretextIntrinsicSize(variant, message) {
      void message;
      if (this.isReaderPageMode) return false;
      if (variant !== "simple") return false;
      return true;
    },

    applyReaderPretextIntrinsicSize(
      el,
      message,
      variant = "full",
      renderedHtml = "",
    ) {
      if (!(el instanceof HTMLElement) || !message) return null;

      const source = String(
        renderedHtml ||
          this.ensureMessageDisplaySource(message) ||
          message?.content ||
          message?.mes ||
          "",
      );
      const lineHeight = variant === "simple" ? 28 : 30;
      const fallbackWidth = Math.min(window.innerWidth || 1200, 960);
      const estimate = estimatePretextBlockHeight(source, {
        element: el,
        whiteSpace: "pre-wrap",
        lineHeight,
        minHeight: variant === "simple" ? 44 : 72,
        maxHeight: 0,
        fallbackWidth,
      });

      applyPretextIntrinsicSize(el, source, {
        element: el,
        whiteSpace: "pre-wrap",
        lineHeight: estimate.lineHeight,
        minHeight: estimate.height,
        maxHeight: estimate.height,
        fallbackWidth,
      });

      return estimate;
    },

    shouldRenderMessageAsApp(message) {
      if (!message) return false;
      if (String(message.render_tier || "") !== "full") return false;
      if (!this.readerComponentMode) return false;
      if (this.isReaderPageMode) {
        return Boolean(
          this.currentReaderPageGroup?.floors?.includes(
            Number(message.floor || 0),
          ),
        );
      }
      return (
        this.readerComponentMode &&
        shouldExecuteMessageSegments(
          message,
          this.activeChat,
          this.readerViewSettings,
          this.renderedFloorHtmlCache,
          this.effectiveReaderAnchorFloor,
          this.readerAnchorMode,
        )
      );
    },

    resolveRenderedRuntimePart(message) {
      if (!message) return null;

      const floor = Number(message.floor || 0);
      const scopedFloorKey = buildReaderCacheScopeKey(
        this.activeChat,
        floor,
        message,
      );
      const cacheKey =
        floor > 0
          ? `${floor}:${String(message.rendered_display_html || this.renderedFloorHtmlCache.get(floor) || "")}`
          : `preview:${String(message.rendered_display_html || "")}`;
      const cacheEntry =
        floor > 0
          ? this.runtimeCandidateCache.floorMap.get(scopedFloorKey)
          : null;
      if (cacheEntry && cacheEntry.key === cacheKey) {
        return cacheEntry.part;
      }

      const renderedHtml =
        floor > 0
          ? this.renderedFloorHtmlCache.get(floor) ||
            message.rendered_display_html ||
            ""
          : message.rendered_display_html || "";
      const candidates = extractRuntimeCandidatesFromRenderedHtml(renderedHtml);
      const part = candidates.length
        ? candidates
            .slice()
            .sort(
              (left, right) =>
                Number(right.score || 0) - Number(left.score || 0) ||
                String(right.text || "").length -
                  String(left.text || "").length,
            )[0]
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
      const renderedHtml =
        floor > 0
          ? this.renderedFloorHtmlCache.get(floor) ||
            message.rendered_display_html ||
            ""
          : message.rendered_display_html || "";
      return extractRuntimeCandidatesFromRenderedHtml(renderedHtml);
    },

    wrapRenderedRuntimeHosts(el, message) {
      if (!(el instanceof Element) || !message || !this.readerComponentMode) {
        return [];
      }
      return wrapRuntimeHostsInContainer(el, Number(message.floor || 0));
    },

    updateReaderRuntimeDebug(
      message,
      element,
      candidates = [],
      wrappedHosts = [],
    ) {
      const floor = Number(message?.floor || 0);
      const preCount =
        element instanceof Element ? element.querySelectorAll("pre").length : 0;
      this.readerRuntimeDebug = {
        enabled: true,
        floor,
        preCount,
        candidateCount: candidates.length,
        wrappedCount: wrappedHosts.length,
        scores: candidates.map((candidate) => Number(candidate.score || 0)),
        snippets: candidates.slice(0, 4).map((candidate) => {
          const text = String(candidate.text || "")
            .replace(/\s+/g, " ")
            .trim();
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
    },

    mountMessageDisplay(el, message) {
      if (!el || !message) return;

      this.$nextTick(() => {
        if (!el || !el.isConnected) return;
        this.mountMessageDisplayNow(el, message);
      });
    },

    scheduleDeferredReaderRuntimeMount(el, message) {
      if (!(el instanceof Element) || !message) return;
      const signature = String(el.__stmReaderDisplaySignature || "");
      if (!signature) return;

      const existingTimer = Number(el.__stmDeferredRuntimeTimer || 0);
      if (existingTimer) {
        window.clearTimeout(existingTimer);
      }

      el.__stmDeferredRuntimeTimer = window.setTimeout(() => {
        el.__stmDeferredRuntimeTimer = 0;
        if (!el.isConnected) return;
        if (String(el.__stmReaderDisplaySignature || "") !== signature) return;
        el.__stmForceImmediateRuntimeMount = true;
        this.mountMessageDisplayNow(el, message);
      }, 0);
    },

    mountMessageDisplayNow(el, message) {
      if (!el || !message) return;
      if (!this.detailOpen || !this.activeChat) return;
      if (
        resolveReaderMessageChatId(message, this.activeChat) !==
        String(this.activeChat?.id || "")
      )
        return;

      const floor = Number(message.floor || 0);
      const chatId = resolveReaderMessageChatId(message, this.activeChat);
      const allowExecutableHtml = this.shouldRenderMessageAsApp(message);
      const wrappedHosts = this.wrapRenderedRuntimeHosts(el, message);
      const candidates = extractRuntimeCandidatesFromContainer(el);
      this.updateReaderRuntimeDebug(message, el, candidates, wrappedHosts);
      const candidateSignature = buildRuntimeCandidateSignature(candidates);
      const forceImmediateRuntimeMount =
        el.__stmForceImmediateRuntimeMount === true;
      el.__stmForceImmediateRuntimeMount = false;
      const deferRuntimeMount = shouldDeferReaderRuntimeMount({
        isReaderPageMode: this.isReaderPageMode && !forceImmediateRuntimeMount,
        floor,
        anchorFloor: Number(
          this.currentReaderPageGroup?.anchorFloor ||
            this.effectiveReaderAnchorFloor ||
            0,
        ),
        immediateRadius: READER_PAGE_MODE_IMMEDIATE_RUNTIME_RADIUS,
      });

      const current = this.readerSegmentRegistry.get(el);
      const needsRuntimeAttach =
        allowExecutableHtml &&
        wrappedHosts.some(
          (host) => !(host instanceof Element) || !host.querySelector("iframe"),
        );
      const needsPlaceholderRender =
        !allowExecutableHtml &&
        wrappedHosts.some(
          (host) =>
            !(host instanceof Element) || !String(host.innerHTML || "").trim(),
        );
      const signature = JSON.stringify({
        chatId,
        floor,
        displaySource: String(message.display_source || message.content || ""),
        candidateSignature,
        appEnabled: allowExecutableHtml,
        renderMode: this.readerRenderMode,
      });

      if (
        current?.signature === signature &&
        !needsRuntimeAttach &&
        !needsPlaceholderRender
      ) {
        return;
      }

      this.destroyMessageRenderPart(el);
      if (!this.readerComponentMode || !candidates.length) {
        this.readerSegmentRegistry.set(el, { signature, children: [el] });
        this.scheduleReaderFloorLayoutDebug(message, el, "mount_no_runtime", {
          allowExecutableHtml,
          candidateCount: candidates.length,
          wrappedHostCount: wrappedHosts.length,
        });
        return;
      }

      if (!allowExecutableHtml) {
        wrappedHosts.forEach((host) => {
          if (host instanceof Element) {
            setRuntimeWrapperActive(host, false);
            clearDeferredRuntimePlaceholder(host);
            setDeferredRuntimePlaceholder(
              host,
              message,
              this.readerViewSettings,
            );
          }
        });
        this.readerSegmentRegistry.set(el, { signature, children: [el] });
        this.scheduleReaderFloorLayoutDebug(
          message,
          el,
          "mount_runtime_placeholder",
          {
            allowExecutableHtml,
            candidateCount: candidates.length,
            wrappedHostCount: wrappedHosts.length,
          },
        );
        return;
      }

      if (deferRuntimeMount) {
        wrappedHosts.forEach((host) => {
          if (host instanceof Element) {
            setRuntimeWrapperActive(host, false);
            clearDeferredRuntimePlaceholder(host);
            setDeferredRuntimePlaceholder(
              host,
              message,
              this.readerViewSettings,
            );
          }
        });
        this.readerSegmentRegistry.set(el, { signature, children: [el] });
        this.scheduleDeferredReaderRuntimeMount(el, message);
        this.scheduleReaderFloorLayoutDebug(
          message,
          el,
          "mount_runtime_deferred",
          {
            allowExecutableHtml,
            candidateCount: candidates.length,
            wrappedHostCount: wrappedHosts.length,
          },
        );
        return;
      }

      const rawMessage = this.getReaderRawMessageForFloor(floor) || {
        mes: String(message?.mes || message?.content || ""),
        name: message?.name || "Preview",
      };

      candidates.forEach((candidate, index) => {
        const runtimeHost =
          wrappedHosts[index] ||
          el.querySelector(`#${buildRuntimeHostId(floor || 0, index)}`);
        if (!(runtimeHost instanceof Element)) {
          return;
        }

        setRuntimeWrapperActive(runtimeHost, true);
        clearDeferredRuntimePlaceholder(runtimeHost);

        let stage = this.readerPartStages.get(runtimeHost);
        if (!stage) {
          stage = new ChatAppStage({
            onTriggerSlash: async (command) => {
              await this.executeAppStageSlash(command);
            },
            onToast: (message, duration) => {
              this.$store.global.showToast(
                String(message || ""),
                Number.isFinite(Number(duration)) ? Number(duration) : 2200,
              );
            },
            onAppError: (error) => {
              console.error("[ChatMessageAppStage]", error);
              this.$store.global.showToast(`实例错误: ${error.message}`, 2600);
            },
            embeddedStageStyle: true,
          });
          this.readerPartStages.set(runtimeHost, stage);
        }

        stage.attachHost(runtimeHost);
        stage.update({
          htmlPayload: String(candidate.text || ""),
          assetBase: this.activeReaderAssetBase,
          context: buildChatAppCompatContext(
            this.activeChat?.raw_messages || [],
            floor || 1,
            rawMessage,
            message,
            this.activeChat,
            this.activeBoundCardDetail,
          ),
        });
      });

      this.readerSegmentRegistry.set(el, { signature, children: [el] });
      this.scheduleReaderFloorLayoutDebug(message, el, "mount_runtime_active", {
        allowExecutableHtml,
        candidateCount: candidates.length,
        wrappedHostCount: wrappedHosts.length,
      });
    },

    destroyMessageRenderPart(el) {
      if (!el) return;

      const deferredTimer = Number(el.__stmDeferredRuntimeTimer || 0);
      if (deferredTimer) {
        window.clearTimeout(deferredTimer);
        el.__stmDeferredRuntimeTimer = 0;
      }

      const hosts = [
        el,
        ...Array.from(el.querySelectorAll(".chat-inline-runtime-host")),
      ];
      hosts.forEach((host) => {
        const stage = this.readerPartStages.get(host);
        if (stage) {
          stage.destroy();
          this.readerPartStages.delete(host);
        }
        if (host instanceof Element) {
          setRuntimeWrapperActive(host, false);
          clearDeferredRuntimePlaceholder(host);
        }
      });

      clearInlineIsolatedHtml(el, { clearShadow: true });
      this.readerSegmentRegistry.delete(el);
    },

    mountReaderRender(el, text) {
      if (!el) return;

      const source = String(text || "");
      updateInlineRenderContent(el, source, {
        mode: this.readerRenderMode === "markdown" ? "markdown" : "plain",
        isolated: true,
        emptyHtml: '<span class="chat-render-empty">空内容</span>',
      });
    },

    readerMessageRole(message) {
      if (!message) return "Assistant";
      if (message.is_system) return "System";
      if (message.is_user) return "User";
      return "Assistant";
    },

    openFloorEditor(message) {
      if (!this.activeChat || !message) return;
      const floor = Number(message.floor || 0);
      if (!floor) return;

      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
        window.dispatchEvent(new CustomEvent("close-header-mobile-menu"));
      }

      this.editingFloor = floor;
      this.editingMessageRawDraft = String(message.mes || "");
      this.editingMessageDraft = this.extractDisplayContent(
        this.editingMessageRawDraft,
      );
      this.editingMessagePreviewMode = "parsed";
    },

    closeFloorEditor() {
      this.editingFloor = 0;
      this.editingMessageDraft = "";
      this.editingMessageRawDraft = "";
      this.editingMessagePreviewMode = "parsed";
    },

    applyEditedContentToRaw() {
      this.editingMessageRawDraft = this.editingMessageDraft;
    },

    async saveFloorEdit() {
      if (!this.activeChat || !this.editingFloor) return;

      const floorIndex = Number(this.editingFloor) - 1;
      const rawMessages = await this.fetchCompleteRawMessages();
      if (!Array.isArray(rawMessages)) return;
      const target = rawMessages[floorIndex];
      if (!target || typeof target !== "object") return;

      target.mes = String(this.editingMessageRawDraft || "");

      const ok = await this.persistChatContent(
        rawMessages,
        `已保存 #${this.editingFloor} 楼层`,
        null,
        {
          focusFloor: this.editingFloor,
        },
      );
      if (!ok) return;

      this.setReaderFeedbackTone("success");
      this.closeFloorEditor();
      if (this.detailSearchQuery) {
        this.searchInDetail();
      }
    },

    extractDisplayContent(messageText) {
      const depthInfo = this.resolveReaderDepthInfoForFloor(
        this.editingFloor,
        this.editingMessageTarget || { mes: messageText },
      );
      return buildReaderDisplaySource(messageText, this.activeRegexConfig, {
        placement: 2,
        isMarkdown: true,
        macroContext: this.buildReaderRegexMacroContext(
          this.editingMessageTarget || { mes: messageText },
          this.editingFloor,
        ),
        depth: depthInfo.tailDepth ?? 0,
        depthInfo,
        legacyReaderDepthMode: depthInfo.legacyReaderDepthMode,
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
          alert(res.msg || "收藏状态更新失败");
          return;
        }

        Object.assign(item, res.chat);
        if (this.activeChat && this.activeChat.id === item.id) {
          this.activeChat.favorite = res.chat.favorite;
        }
        if (this.chatFavFilter !== "none") {
          this.fetchChats();
        }
        window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
      } catch (err) {
        item.favorite = !next;
        alert("收藏状态更新失败: " + err);
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
          alert(res.msg || "保存失败");
          return;
        }

        this.activeChat = {
          ...this.activeChat,
          ...res.chat,
          message_index: this.activeChat.message_index,
          messages: this.activeChat.messages,
          raw_messages: this.activeChat.raw_messages,
          metadata: this.activeChat.metadata,
        };

        const index = this.chatList.findIndex(
          (item) => item.id === res.chat.id,
        );
        if (index > -1) {
          this.chatList.splice(index, 1, {
            ...this.chatList[index],
            ...res.chat,
          });
        }

        window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
        this.setReaderFeedbackTone("success");
        this.$store.global.showToast("聊天本地信息已保存", 1500);
      } catch (err) {
        this.setReaderFeedbackTone("error");
        alert("保存聊天信息失败: " + err);
      }
    },

    async deleteChat(item) {
      if (!item || !item.id) return;
      if (
        !confirm(
          `确定将聊天记录 "${item.title || item.chat_name}" 移至回收站吗？`,
        )
      )
        return;

      try {
        const res = await deleteChat(item.id);
        if (!res.success) {
          alert(res.msg || "删除失败");
          return;
        }

        this.chatList = this.chatList.filter((chat) => chat.id !== item.id);
        this.chatTotalItems = Math.max(0, this.chatTotalItems - 1);
        if (this.activeChat && this.activeChat.id === item.id) {
          this.closeChatDetail();
        }
        window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
        this.setReaderFeedbackTone("danger");
        this.$store.global.showToast("聊天记录已移至回收站", 1800);
      } catch (err) {
        this.setReaderFeedbackTone("error");
        alert("删除失败: " + err);
      }
    },

    openChatFolder(item) {
      if (!item || !item.file_path) return;
      openPath({ path: item.file_path, is_file: true }).then((res) => {
        if (!res.success) {
          alert(res.msg || "打开失败");
        }
      });
    },

    jumpToBoundCard(item) {
      if (!item || !item.bound_card_id) return;
      window.dispatchEvent(
        new CustomEvent("jump-to-card-wi", { detail: item.bound_card_id }),
      );
      this.closeChatDetail();
    },

    scrollElementToTop(el, behavior = "smooth") {
      if (!el) return;

      const container = el.closest(".chat-reader-center");
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const elementRect = el.getBoundingClientRect();
        const top = Math.max(
          0,
          container.scrollTop + elementRect.top - containerRect.top - 12,
        );
        container.scrollTo({ top, behavior });
        return;
      }

      try {
        el.scrollIntoView({ behavior, block: "start" });
      } catch {
        el.scrollIntoView();
      }
    },

    async openBindPicker(item) {
      const target = item || this.activeChat;
      if (!target || !target.id) return;

      if (this.$store.global.deviceType === "mobile") {
        this.$store.global.visibleSidebar = false;
        document.body.style.overflow = "";
        window.dispatchEvent(new CustomEvent("close-header-mobile-menu"));
      }

      this.bindPickerOpen = true;
      this.bindPickerTargetChatId = target.id;
      this.bindPickerSearch =
        target.bound_card_name || target.character_name || "";
      await this.fetchBindPickerResults();
    },

    closeBindPicker() {
      this.bindPickerOpen = false;
      this.bindPickerLoading = false;
      this.bindPickerSearch = "";
      this.bindPickerResults = [];
      this.bindPickerTargetChatId = "";
    },

    async fetchBindPickerResults() {
      this.bindPickerLoading = true;
      try {
        const res = await listCards({
          page: 1,
          page_size: 60,
          category: "",
          tags: "",
          excluded_tags: "",
          excluded_categories: "",
          search: this.bindPickerSearch || "",
          search_type: "name",
          search_scope: "all_dirs",
          sort: "name_asc",
          recursive: true,
        });

        this.bindPickerResults = Array.isArray(res.cards) ? res.cards : [];
      } catch (err) {
        this.bindPickerResults = [];
      } finally {
        this.bindPickerLoading = false;
      }
    },

    async applyBinding(chatId, cardId = "", unbind = false) {
      if (!chatId) return;

      try {
        const res = await bindChatToCard({
          id: chatId,
          card_id: cardId,
          unbind,
        });

        if (!res.success) {
          alert(res.msg || "绑定失败");
          return;
        }

        const nextChatId = res.chat?.id || res.id || chatId;
        this.fetchChats();
        window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
        if (this.activeChat && this.activeChat.id === chatId) {
          if (nextChatId !== chatId) {
            this.activeChat.id = nextChatId;
          }
          await this.reloadActiveChat();
        }
        this.closeBindPicker();
        this.setReaderFeedbackTone(unbind ? "danger" : "success");
        this.$store.global.showToast(
          unbind ? "聊天绑定已解除" : "聊天绑定已更新",
          1500,
        );
      } catch (err) {
        this.setReaderFeedbackTone("error");
        alert("绑定失败: " + err);
      }
    },

    async bindCardPick(card) {
      if (!card || !card.id || !this.bindPickerTargetChatId) return;
      await this.applyBinding(this.bindPickerTargetChatId, card.id, false);
    },

    async unbindCurrentChat() {
      if (!this.bindPickerTargetChatId) return;
      await this.applyBinding(this.bindPickerTargetChatId, "", true);
    },

    _uploadChatFiles(files, cardId = "", characterName = "") {
      const fileList = Array.from(files || []).filter(
        (file) =>
          file && file.name && file.name.toLowerCase().endsWith(".jsonl"),
      );
      if (fileList.length === 0) {
        alert("请选择 .jsonl 聊天记录文件");
        return;
      }

      const formData = new FormData();
      fileList.forEach((file) => formData.append("files", file));
      if (cardId) formData.append("card_id", cardId);
      if (characterName) formData.append("character_name", characterName);

      this.$store.global.isLoading = true;
      importChats(formData)
        .then((res) => {
          this.$store.global.isLoading = false;
          if (!res.success && (!res.items || res.items.length === 0)) {
            alert(res.msg || "聊天导入失败");
            return;
          }

          if (Array.isArray(res.failed) && res.failed.length > 0) {
            const message = res.failed
              .map((item) => `${item.name}: ${item.msg}`)
              .join("\n");
            alert(`部分文件导入失败:\n${message}`);
          }

          this.$store.global.showToast(
            `已导入 ${res.imported || 0} 个聊天记录`,
            1800,
          );
          this.fetchChats();
          window.dispatchEvent(new CustomEvent("refresh-card-list"));
          window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
        })
        .catch((err) => {
          this.$store.global.isLoading = false;
          alert("聊天导入失败: " + err);
        });
    },

    handleChatFilesDrop(event, cardId = "", characterName = "") {
      this.dragOverChats = false;
      this._uploadChatFiles(
        event?.dataTransfer?.files || [],
        cardId,
        characterName,
      );
    },

    triggerChatImport(options = {}) {
      this.filePickerMode = options.mode || "global";
      this.filePickerPayload = options.payload || null;
      if (this.$refs.chatImportInput) {
        this.$refs.chatImportInput.click();
      }
    },

    handleChatInputChange(e) {
      const input = e.target;
      try {
        const payload = this.filePickerPayload || {};
        if (this.filePickerMode === "card") {
          this._uploadChatFiles(
            input.files || [],
            payload.cardId || "",
            payload.characterName || "",
          );
        } else {
          this._uploadChatFiles(input.files || [], "", "");
        }
      } finally {
        this.filePickerMode = "global";
        this.filePickerPayload = null;
        input.value = "";
      }
    },

    async searchInDetail() {
      const query = String(this.detailSearchQuery || "").trim();
      this.detailSearchResults = [];
      this.detailSearchIndex = -1;
      if (!query || !this.activeChat) return;

      try {
        const res = await searchChats({
          query,
          limit: 500,
          chat_ids: [this.activeChat.id],
        });
        if (!res?.success) {
          alert(res?.msg || "聊天搜索失败");
          return;
        }

        const matches = [
          ...new Set(
            (Array.isArray(res.items) ? res.items : [])
              .map((item) => Number(item?.floor || 0))
              .filter(Boolean),
          ),
        ].sort((left, right) => left - right);

        this.detailSearchResults = matches;
      } catch (err) {
        alert("聊天搜索失败: " + err);
        return;
      }

      const matches = this.detailSearchResults;
      if (matches.length > 0) {
        this.detailSearchIndex = 0;
        await this.scrollToFloor(
          matches[0],
          true,
          "smooth",
          READER_ANCHOR_SOURCES.SEARCH,
        );
      }
    },

    nextSearchResult() {
      if (!this.detailSearchResults.length) return;
      this.detailSearchIndex =
        (this.detailSearchIndex + 1) % this.detailSearchResults.length;
      this.scrollToFloor(
        this.detailSearchResults[this.detailSearchIndex],
        true,
        "smooth",
        READER_ANCHOR_SOURCES.SEARCH,
      );
    },

    previousSearchResult() {
      if (!this.detailSearchResults.length) return;
      this.detailSearchIndex =
        (this.detailSearchIndex - 1 + this.detailSearchResults.length) %
        this.detailSearchResults.length;
      this.scrollToFloor(
        this.detailSearchResults[this.detailSearchIndex],
        true,
        "smooth",
        READER_ANCHOR_SOURCES.SEARCH,
      );
    },

    async scrollToFloor(
      floor,
      persist = true,
      behavior = "smooth",
      anchorSource = READER_ANCHOR_SOURCES.JUMP,
    ) {
      const rawTargetFloor = Number(floor || 0);
      if (!rawTargetFloor || !this.activeChat) return;
      const targetFloor = Math.min(
        Math.max(1, rawTargetFloor),
        Math.max(1, this.readerTotalMessages || rawTargetFloor),
      );
      const shouldPromoteAnchor = shouldPromoteReaderAnchorForSource(
        this.readerAnchorMode,
        anchorSource,
      );
      const shouldResetWindow = shouldResetReaderWindowForAnchorTarget({
        targetFloor,
        windowStartFloor: this.readerWindowStartFloor,
        windowEndFloor: this.readerWindowEndFloor,
        totalMessages:
          this.readerTotalMessages || this.activeChat?.messages?.length || 0,
      });
      const shouldHideMobilePanel =
        this.readerResponsiveMode === "mobile" &&
        Boolean(this.readerMobilePanel);
      if (shouldHideMobilePanel) {
        this.hideReaderPanels();
      }
      this.logReaderScrollDebug("scroll_to_floor_start", {
        rawTargetFloor,
        targetFloor,
        persist: persist === true,
        behavior: String(behavior || ""),
        anchorSource: String(anchorSource || ""),
      });

      if (this.readerAppMode) {
        this.jumpFloorInput = String(targetFloor);
        if (this.executableMessageFloors.includes(targetFloor)) {
          if (shouldPromoteAnchor) {
            this.updateReaderAnchorFloor(
              targetFloor,
              READER_ANCHOR_SOURCES.APP_STAGE,
            );
          } else {
            this.readerViewportFloor = targetFloor;
          }
          this.setReaderAppFloor(targetFloor);
          if (persist) {
            this.activeChat.last_view_floor = targetFloor;
          }
        } else {
          this.$store.global.showToast(
            `楼层 #${targetFloor} 没有可执行实例，已退出整页实例模式`,
            2200,
          );
          this.deactivateChatAppStage();
          this.$nextTick(() =>
            this.scrollToFloor(targetFloor, persist, behavior, anchorSource),
          );
        }
        return;
      }

      if (this.isReaderPageMode) {
        if (this.detailBookmarkedOnly && !this.isBookmarked(targetFloor)) {
          this.detailBookmarkedOnly = false;
        }

        this.jumpFloorInput = String(targetFloor);
        void this.syncReaderNavBatchForFloor(targetFloor);
        this.syncReaderPageGroupForFloor(targetFloor, {
          anchorFloor: targetFloor,
          source: anchorSource,
        });
        await this.ensureReaderWindowForFloor(targetFloor, "center");
        this.refreshReaderAnchorState(targetFloor);
        this.$nextTick(() => {
          const root = document.querySelector(
            ".chat-reader-overlay--fullscreen",
          );
          const el = root
            ? root.querySelector(`[data-chat-floor="${targetFloor}"]`)
            : null;
          if (el) {
            this.scrollElementToTop(el, behavior);
          } else {
            this.scrollReaderCenterToTop(behavior);
          }
        });

        if (persist) {
          this.activeChat.last_view_floor = targetFloor;
          updateChatMeta({
            id: this.activeChat.id,
            last_view_floor: targetFloor,
          })
            .then((res) => {
              if (res.success && res.chat) {
                const index = this.chatList.findIndex(
                  (item) => item.id === res.chat.id,
                );
                if (index > -1) {
                  this.chatList.splice(index, 1, {
                    ...this.chatList[index],
                    ...res.chat,
                  });
                }
              }
            })
            .catch(() => {});
        }
        return;
      }

      if (this.detailBookmarkedOnly && !this.isBookmarked(targetFloor)) {
        this.detailBookmarkedOnly = false;
      }

      this.jumpFloorInput = String(targetFloor);
      void this.syncReaderNavBatchForFloor(targetFloor);
      if (shouldPromoteAnchor) {
        this.updateReaderAnchorFloor(targetFloor, anchorSource);
      } else {
        this.readerViewportFloor = targetFloor;
        this.readerAnchorSource = anchorSource;
      }
      if (shouldResetWindow) {
        await this.setReaderWindowAroundFloor(targetFloor, "center");
      } else {
        await this.ensureReaderWindowForFloor(targetFloor, "center");
      }
      this.logReaderScrollDebug("scroll_to_floor_after_window", {
        targetFloor,
      });

      this.$nextTick(() => {
        const root = document.querySelector(".chat-reader-overlay--fullscreen");
        const el = root
          ? root.querySelector(`[data-chat-floor="${targetFloor}"]`)
          : null;
        if (el) {
          this.scrollElementToTop(el, behavior);
        }
      });

      if (persist) {
        this.activeChat.last_view_floor = targetFloor;
        updateChatMeta({ id: this.activeChat.id, last_view_floor: targetFloor })
          .then((res) => {
            if (res.success && res.chat) {
              const index = this.chatList.findIndex(
                (item) => item.id === res.chat.id,
              );
              if (index > -1) {
                this.chatList.splice(index, 1, {
                  ...this.chatList[index],
                  ...res.chat,
                });
              }
            }
          })
          .catch(() => {});
      }
    },

    jumpToInputFloor() {
      const value = String(this.jumpFloorInput || "")
        .trim()
        .replace(/^#/, "");
      const floor = parseInt(value, 10);
      if (!floor || floor < 1) {
        alert("请输入有效的楼层编号");
        return;
      }
      this.scrollToFloor(floor, true, "smooth", READER_ANCHOR_SOURCES.JUMP);
    },

    jumpToBookmarkFloor(floor) {
      this.scrollToFloor(floor, true, "smooth", READER_ANCHOR_SOURCES.BOOKMARK);
    },

    jumpToNavigatorFloor(floor) {
      this.scrollToFloor(
        floor,
        true,
        "smooth",
        READER_ANCHOR_SOURCES.NAVIGATOR,
      );
    },

    openMessageAsAppStage(message) {
      const floor = Number(message?.floor || 0);
      if (!floor) return;

      if (!this.executableMessageFloors.includes(floor)) {
        this.$store.global.showToast(
          `楼层 #${floor} 没有检测到可执行实例`,
          2200,
        );
        return;
      }

      this.jumpFloorInput = String(floor);
      this.setReaderAppFloor(floor);
    },

    jumpToEdge(which) {
      const messages = Array.isArray(this.activeChat?.messages)
        ? this.activeChat.messages
        : [];
      if (!messages.length) return;
      if (which === "first") {
        this.scrollToFloor(
          messages[0].floor,
          true,
          "smooth",
          READER_ANCHOR_SOURCES.JUMP,
        );
        return;
      }
      this.scrollToFloor(
        messages[messages.length - 1].floor,
        true,
        "smooth",
        READER_ANCHOR_SOURCES.JUMP,
      );
    },

    toggleBookmark(message) {
      if (!this.activeChat || !message) return;

      const floor = Number(message.floor || 0);
      if (!floor) return;

      const current = Array.isArray(this.activeChat.bookmarks)
        ? [...this.activeChat.bookmarks]
        : [];
      const index = current.findIndex(
        (item) => Number(item.floor || 0) === floor,
      );
      if (index > -1) {
        current.splice(index, 1);
      } else {
        current.push({
          id: `${floor}_${Date.now()}`,
          floor,
          label: String(this.bookmarkDraft || "").trim(),
          text: String(
            this.ensureMessageDisplaySource(message) || message.mes || "",
          )
            .trim()
            .slice(0, 120),
          created_at: Date.now() / 1000,
        });
        this.bookmarkDraft = "";
      }

      this.activeChat.bookmarks = current;
      this.saveChatMeta();
    },

    isBookmarked(floor) {
      if (!this.activeChat || !Array.isArray(this.activeChat.bookmarks))
        return false;
      const target = Number(floor || 0);
      return this.activeChat.bookmarks.some(
        (item) => Number(item.floor || 0) === target,
      );
    },

    async fetchCompleteRawMessages() {
      if (!this.activeChat) return null;
      const total = this.readerTotalMessages;
      if (!total) return [];

      const pageSize = Math.min(
        200,
        Math.max(
          this.readerPageSize || CHAT_READER_PAGE_SIZE,
          CHAT_READER_PAGE_SIZE,
        ),
      );
      const totalPages = Math.ceil(total / pageSize);
      const chatId = String(this.activeChat.id || "");
      const collected = [];

      for (let page = 1; page <= totalPages; page += 1) {
        const res = await getChatRange(chatId, {
          page,
          page_size: pageSize,
        });
        if (!res?.success || !res.range) {
          alert(res?.msg || "读取完整聊天内容失败");
          return null;
        }
        collected.push(
          ...(Array.isArray(res.range.raw_messages)
            ? res.range.raw_messages
            : []),
        );
      }

      return collected.map((item) =>
        item && typeof item === "object"
          ? JSON.parse(JSON.stringify(item))
          : {},
      );
    },

    async persistChatContent(
      rawMessages,
      toastText = "聊天内容已保存",
      metadataOverride = null,
      options = {},
    ) {
      if (!this.activeChat) return false;

      const payload = {
        id: this.activeChat.id,
        raw_messages: rawMessages,
        metadata: ensureChatMetadataShape(
          metadataOverride || this.activeChat.metadata || {},
        ),
      };

      const res = await saveChat(payload);
      if (!res.success || !res.chat) {
        alert(res.msg || "聊天保存失败");
        return false;
      }

      const preserveName = this.detailDraftName;
      const preserveNotes = this.detailDraftNotes;
      const preserveRegexConfigDraft = normalizeRegexConfig(
        this.regexConfigDraft,
        { fillDefaults: false },
      );
      const preserveReaderResolvedRegexConfig = normalizeRegexConfig(
        this.readerResolvedRegexConfig || this.activeRegexConfig,
      );
      const preserveAnchorMode = normalizeReaderAnchorMode(
        this.readerAnchorMode,
      );
      const preserveAnchorSource = this.readerAnchorSource;
      const preservePageSize = Math.max(
        1,
        Number(this.readerPageSize || CHAT_READER_PAGE_SIZE),
      );
      const preserveViewportFloor = Number(
        this.readerViewportFloor || this.activeChat?.last_view_floor || 0,
      );
      const preserveAnchorFloor = Number(
        this.effectiveReaderAnchorFloor ||
          this.readerAnchorFloor ||
          preserveViewportFloor ||
          0,
      );

      this.readerPageRequestToken += 1;
      this.readerPageSize = Math.max(
        1,
        Number(res.chat.page_size || preservePageSize),
      );
      this.activeChat = this.buildReaderManifestChat(res.chat);
      this.detailDraftName = preserveName;
      this.detailDraftNotes = preserveNotes;
      this.regexConfigDraft = preserveRegexConfigDraft;
      this.readerAnchorMode = normalizeReaderAnchorMode(preserveAnchorMode);
      this.readerAnchorSource = preserveAnchorSource;

      const total = this.readerTotalMessages;
      const clampFloor = (value, fallback = 0) => {
        if (!total) return 0;
        const numeric = Number(value || 0);
        if (numeric > 0) {
          return Math.min(total, Math.max(1, numeric));
        }
        return Math.min(total, Math.max(1, Number(fallback || 1)));
      };

      if (total > 0) {
        this.readerViewportFloor = clampFloor(
          preserveViewportFloor,
          preserveAnchorFloor || this.activeChat.last_view_floor || total,
        );
        this.readerAnchorFloor = clampFloor(
          preserveAnchorFloor,
          this.readerViewportFloor || this.activeChat.last_view_floor || total,
        );
      } else {
        this.readerViewportFloor = 0;
        this.readerAnchorFloor = 0;
      }

      const focusFloor = clampFloor(
        options.focusFloor,
        preserveAnchorFloor ||
          this.readerViewportFloor ||
          this.activeChat.last_view_floor ||
          total,
      );
      this.syncReaderPageGroupForFloor(focusFloor, {
        anchorFloor: focusFloor,
        source: READER_ANCHOR_SOURCES.RESTORE,
      });
      await this.setReaderWindowAroundFloor(focusFloor || 1, "center");
      const runtimeConfig = normalizeRegexConfig(
        options.rebuildConfig ||
          this.activeRegexConfig ||
          preserveReaderResolvedRegexConfig,
      );
      this.readerResolvedRegexConfig = runtimeConfig;
      this.rebuildActiveChatMessages(runtimeConfig);
      this.regexConfigSourceLabel = this.describeRegexConfigSource(
        this.activeChat,
      );
      this.detectChatAppMode();

      const index = this.chatList.findIndex((item) => item.id === res.chat.id);
      if (index > -1) {
        this.chatList.splice(index, 1, {
          ...this.chatList[index],
          ...res.chat,
        });
      }

      window.dispatchEvent(new CustomEvent("refresh-detail-chats"));
      this.$store.global.showToast(toastText, 1600);
      return true;
    },

    async replaceAllInChat() {
      if (!this.activeChat) return;

      const query = String(this.replaceQuery || "");
      if (!query.trim()) {
        alert("请输入要查找的内容");
        return;
      }

      const replacement = String(this.replaceReplacement || "");
      const rawMessages = await this.fetchCompleteRawMessages();
      if (!Array.isArray(rawMessages)) return;
      let regex = null;

      if (this.replaceUseRegex) {
        try {
          regex = new RegExp(query, this.replaceCaseSensitive ? "g" : "gi");
        } catch (err) {
          alert(`正则表达式无效: ${err.message}`);
          return;
        }
      }

      let changedMessages = 0;
      let totalReplaced = 0;

      rawMessages.forEach((message) => {
        if (!message || typeof message !== "object") return;
        const original = String(message.mes || "");
        const result = this.replaceUseRegex
          ? (() => {
              let count = 0;
              const text = original.replace(regex, () => {
                count += 1;
                return replacement;
              });
              return { text, count };
            })()
          : replaceTextValue(
              original,
              query,
              replacement,
              this.replaceCaseSensitive,
            );
        if (result.count > 0) {
          message.mes = result.text;
          changedMessages += 1;
          totalReplaced += result.count;
        }
      });

      if (totalReplaced === 0) {
        this.replaceStatus = "没有找到可替换内容";
        this.setReaderFeedbackTone();
        this.$store.global.showToast(this.replaceStatus, 1400);
        return;
      }

      const ok = await this.persistChatContent(
        rawMessages,
        `已替换 ${totalReplaced} 处文本`,
      );
      if (!ok) return;

      this.replaceStatus = `已在 ${changedMessages} 条记录中替换 ${totalReplaced} 处`;
      this.setReaderFeedbackTone("success");
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
