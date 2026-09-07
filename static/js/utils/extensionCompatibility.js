const REGEX_EXTENSION_KEYS = [
  "regex_scripts",
  "regexScripts",
  "regex",
  "regexes",
  "regular_expressions",
];

const TAVERN_HELPER_EXTENSION_KEYS = [
  "tavern_helper",
  "tavernHelper",
  "TavernHelper_scripts",
  "tavern_helper_scripts",
  "tavernHelper_scripts",
  "TavernHelper",
  "scripts",
];

const MANAGED_EXTENSION_KEYS = new Set([
  ...REGEX_EXTENSION_KEYS,
  ...TAVERN_HELPER_EXTENSION_KEYS,
  "SPreset",
  "RegexBinding",
]);

function isRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function cloneJson(value) {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    return value;
  }
}

function unwrapScriptItem(item) {
  return isRecord(item) && isRecord(item.value) ? item.value : item;
}

function extractTavernScriptList(value) {
  if (isRecord(value)) {
    if (Array.isArray(value.scripts)) return value.scripts;
    if (isRecord(value.scripts)) return Object.values(value.scripts);
    return [];
  }

  if (!Array.isArray(value)) return [];

  const scriptBlock = value.find(
    (item) => Array.isArray(item) && item.length >= 2 && item[0] === "scripts",
  );
  if (scriptBlock && Array.isArray(scriptBlock[1])) return scriptBlock[1];

  if (value.every((item) => isRecord(item))) return value;
  return [];
}

export function extractPresetTavernScripts(extensions) {
  if (!isRecord(extensions)) return [];

  for (const key of TAVERN_HELPER_EXTENSION_KEYS) {
    const scripts = extractTavernScriptList(extensions[key]);
    if (!scripts.length) continue;
    return scripts
      .map(unwrapScriptItem)
      .filter((script) => isRecord(script));
  }
  return [];
}

function extractRegexList(value) {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return [];

  for (const key of [
    "regex_scripts",
    "regexScripts",
    "regex",
    "regexes",
    "regular_expressions",
  ]) {
    if (Array.isArray(value[key])) return value[key];
  }

  if (
    "findRegex" in value ||
    "pattern" in value ||
    "expression" in value ||
    "match" in value
  ) {
    return [value];
  }
  return [];
}

export function extractPresetRegexScripts(extensions) {
  if (!isRecord(extensions)) return [];

  const candidates = REGEX_EXTENSION_KEYS.map((key) => extensions[key]);
  const spreset = extensions.SPreset;
  if (isRecord(spreset)) {
    candidates.push(
      spreset.regex,
      spreset.regexes,
      spreset.regular_expressions,
      spreset.RegexBinding,
    );
  }
  candidates.push(extensions.RegexBinding);

  for (const candidate of candidates) {
    const scripts = extractRegexList(candidate);
    if (scripts.length) return scripts;
  }
  return [];
}

function hasRegexSource(extensions) {
  if (!isRecord(extensions)) return false;
  if (REGEX_EXTENSION_KEYS.some((key) => key in extensions)) return true;

  return [extensions.SPreset, extensions.RegexBinding].some(
    (container) =>
      isRecord(container) &&
      ["regex", "regexes", "regular_expressions", "RegexBinding"].some(
        (key) => key in container,
      ),
  );
}

function hasTavernHelperSource(extensions) {
  return (
    isRecord(extensions) &&
    TAVERN_HELPER_EXTENSION_KEYS.some((key) => key in extensions)
  );
}

function extractHelperVariables(helper) {
  if (isRecord(helper) && isRecord(helper.variables)) {
    return helper.variables;
  }
  if (Array.isArray(helper)) {
    const variablesBlock = helper.find(
      (item) =>
        Array.isArray(item) && item.length >= 2 && item[0] === "variables",
    );
    if (variablesBlock && isRecord(variablesBlock[1])) return variablesBlock[1];
  }
  return {};
}

export function normalizePresetExtensionsForEditor(extensions) {
  const normalized = isRecord(extensions)
    ? cloneJson(extensions) || {}
    : {};
  const regexScripts = cloneJson(extractPresetRegexScripts(normalized)) || [];
  const tavernScripts = cloneJson(extractPresetTavernScripts(normalized)) || [];

  normalized.regex_scripts = regexScripts;

  const helper = normalized.tavern_helper;
  if (Array.isArray(helper)) {
    const scriptBlock = helper.find(
      (item) =>
        Array.isArray(item) && item.length >= 2 && item[0] === "scripts",
    );
    if (scriptBlock && Array.isArray(scriptBlock[1])) {
      scriptBlock[1] = tavernScripts;
    } else {
      normalized.tavern_helper = { scripts: tavernScripts };
    }
  } else if (isRecord(helper)) {
    normalized.tavern_helper = { ...helper, scripts: tavernScripts };
  } else {
    normalized.tavern_helper = { scripts: tavernScripts };
  }

  return normalized;
}

export function normalizePresetExtensionsForSave(extensions) {
  const normalized = normalizePresetExtensionsForEditor(extensions);
  normalized.regex_scripts = cloneJson(extractPresetRegexScripts(normalized)) || [];
  normalized.tavern_helper = {
    scripts: cloneJson(extractPresetTavernScripts(normalized)) || [],
    variables: cloneJson(extractHelperVariables(normalized.tavern_helper)) || {},
  };

  for (const key of REGEX_EXTENSION_KEYS) {
    if (key !== "regex_scripts") delete normalized[key];
  }
  for (const key of TAVERN_HELPER_EXTENSION_KEYS) {
    if (key !== "tavern_helper") delete normalized[key];
  }
  delete normalized.RegexBinding;

  return normalized;
}

export function getPresetExtensionSummary(extensions) {
  const safeExtensions = isRecord(extensions) ? extensions : {};
  const regexItems = extractPresetRegexScripts(safeExtensions);
  const scriptItems = extractPresetTavernScripts(safeExtensions);
  const customKeys = Object.keys(safeExtensions).filter(
    (key) => !MANAGED_EXTENSION_KEYS.has(key),
  );

  return {
    regex_count: regexItems.length,
    script_count: scriptItems.length,
    other_count: customKeys.length,
    total_count: regexItems.length + scriptItems.length + customKeys.length,
    custom_keys: customKeys,
    keys: Object.keys(safeExtensions),
    has_regex_source: hasRegexSource(safeExtensions),
    has_tavern_helper_source: hasTavernHelperSource(safeExtensions),
  };
}

export { MANAGED_EXTENSION_KEYS };
