/**
 * static/js/utils/data.js
 * 数据清洗、转换与归一化
 */

/** 生成本地临时 ID；HTTP 等非安全上下文下 crypto.randomUUID 可能不可用。 */
export function createLocalId() {
  const cryptoRef = typeof globalThis !== 'undefined' ? globalThis.crypto : null;
  if (cryptoRef && typeof cryptoRef.randomUUID === 'function') {
    return cryptoRef.randomUUID();
  }

  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// 递归键排序函数 (解决 JSON 乱序导致的大量 Diff 问题)
export function recursiveSort(obj) {
  // 如果是数组，递归处理每一项，但不改变数组本身的顺序
  if (Array.isArray(obj)) {
    return obj.map(recursiveSort);
  }
  // 如果是对象，按键名排序重建对象
  if (obj && typeof obj === "object") {
    return Object.keys(obj)
      .sort()
      .reduce((acc, key) => {
        acc[key] = recursiveSort(obj[key]);
        return acc;
      }, {});
  }
  // 基本类型直接返回
  return obj;
}

// 辅助：更新 Keys (String -> Array)
export function updateWiKeys(entry, value) {
  // 按逗号分割，去空格，去空值
  entry.keys = value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s);
}

// 清洗 ST 世界书条目的默认值 (用于导出或保存)
const ST_DEFAULT_DEPTH = 4;
const ST_DEFAULT_GROUP_WEIGHT = 100;
const ST_DEFAULT_ORDER = 100;
const ST_DEFAULT_POSITION = 0;
const ST_DEFAULT_ROLE = 0;

const hasOwn = (obj, key) =>
  !!obj && Object.prototype.hasOwnProperty.call(obj, key);

const isPlainObject = (value) =>
  value && typeof value === "object" && !Array.isArray(value);

const cloneArray = (value) => (Array.isArray(value) ? [...value] : []);

const toFiniteNumber = (value, fallback) => {
  if (value === true) return 1;
  if (value === false) return 0;
  if (value === null || value === undefined || value === "") return fallback;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
};

const setExtensionField = (extensions, key, value, defaultValue) => {
  const existed = hasOwn(extensions, key);
  if (value === undefined) return;

  if (Array.isArray(value)) {
    if (value.length > 0 || existed) extensions[key] = [...value];
    else delete extensions[key];
    return;
  }

  if (value === null) {
    if (defaultValue !== null || existed) extensions[key] = null;
    else delete extensions[key];
    return;
  }

  if (value !== defaultValue || existed) extensions[key] = value;
  else delete extensions[key];
};

const serializeEmbeddedWiEntry = (entry, index = 0) => {
  const rawSource = isPlainObject(entry) ? entry : {};
  const source = normalizeWiEntry(rawSource, index);
  const extensions = isPlainObject(rawSource.extensions)
    ? { ...rawSource.extensions }
    : {};
  const sourceId =
    source.st_source_id ?? source.uid ?? source.id ?? source.displayIndex ?? index;
  const numericPosition = toFiniteNumber(source.position, ST_DEFAULT_POSITION);

  const out = { ...source };
  out.id = sourceId;
  out.keys = cloneArray(source.keys ?? source.key);
  out.secondary_keys = cloneArray(source.secondary_keys ?? source.keysecondary);
  out.comment = source.comment || "";
  out.content = source.content || "";
  out.constant = !!source.constant;
  out.selective = source.selective !== undefined ? !!source.selective : false;
  out.enabled =
    source.enabled !== undefined ? !!source.enabled : !(source.disable === true);
  out.insertion_order = toFiniteNumber(
    source.insertion_order ?? source.order,
    ST_DEFAULT_ORDER,
  );
  out.position =
    numericPosition === ST_DEFAULT_POSITION ? "before_char" : "after_char";

  setExtensionField(extensions, "position", numericPosition, ST_DEFAULT_POSITION);
  setExtensionField(
    extensions,
    "role",
    toFiniteNumber(source.role, ST_DEFAULT_ROLE),
    ST_DEFAULT_ROLE,
  );
  setExtensionField(
    extensions,
    "depth",
    toFiniteNumber(source.depth, ST_DEFAULT_DEPTH),
    ST_DEFAULT_DEPTH,
  );
  setExtensionField(
    extensions,
    "display_index",
    toFiniteNumber(source.displayIndex, index),
    index,
  );
  setExtensionField(extensions, "exclude_recursion", !!source.excludeRecursion, false);
  setExtensionField(extensions, "prevent_recursion", !!source.preventRecursion, false);
  setExtensionField(
    extensions,
    "delay_until_recursion",
    source.delayUntilRecursion ?? false,
    false,
  );
  setExtensionField(extensions, "ignore_budget", !!source.ignoreBudget, false);
  setExtensionField(extensions, "vectorized", !!source.vectorized, false);
  setExtensionField(
    extensions,
    "probability",
    toFiniteNumber(source.probability, 100),
    100,
  );
  setExtensionField(
    extensions,
    "useProbability",
    source.useProbability !== undefined ? !!source.useProbability : true,
    true,
  );
  setExtensionField(
    extensions,
    "selectiveLogic",
    toFiniteNumber(source.selectiveLogic, 0),
    0,
  );
  setExtensionField(extensions, "outlet_name", source.outletName || "", "");
  setExtensionField(extensions, "scan_depth", source.scanDepth ?? null, null);
  setExtensionField(extensions, "case_sensitive", source.caseSensitive ?? null, null);
  setExtensionField(extensions, "match_whole_words", source.matchWholeWords ?? null, null);
  setExtensionField(extensions, "group", source.group || "", "");
  setExtensionField(extensions, "group_override", !!source.groupOverride, false);
  setExtensionField(
    extensions,
    "group_weight",
    toFiniteNumber(source.groupWeight, ST_DEFAULT_GROUP_WEIGHT),
    ST_DEFAULT_GROUP_WEIGHT,
  );
  setExtensionField(extensions, "use_group_scoring", source.useGroupScoring ?? null, null);
  setExtensionField(extensions, "automation_id", source.automationId || "", "");
  setExtensionField(extensions, "sticky", source.sticky ?? null, null);
  setExtensionField(extensions, "cooldown", source.cooldown ?? null, null);
  setExtensionField(extensions, "delay", source.delay ?? null, null);
  setExtensionField(extensions, "triggers", cloneArray(source.triggers), []);
  setExtensionField(
    extensions,
    "match_persona_description",
    !!source.matchPersonaDescription,
    false,
  );
  setExtensionField(
    extensions,
    "match_character_description",
    !!source.matchCharacterDescription,
    false,
  );
  setExtensionField(
    extensions,
    "match_character_personality",
    !!source.matchCharacterPersonality,
    false,
  );
  setExtensionField(
    extensions,
    "match_character_depth_prompt",
    !!source.matchCharacterDepthPrompt,
    false,
  );
  setExtensionField(extensions, "match_scenario", !!source.matchScenario, false);
  setExtensionField(
    extensions,
    "match_creator_notes",
    !!source.matchCreatorNotes,
    false,
  );

  if (source.characterFilter) out.character_filter = source.characterFilter;
  out.extensions = extensions;

  [
    "st_source_id",
    "st_manager_uid",
    "uid",
    "key",
    "keysecondary",
    "disable",
    "order",
    "role",
    "depth",
    "displayIndex",
    "excludeRecursion",
    "preventRecursion",
    "delayUntilRecursion",
    "ignoreBudget",
    "vectorized",
    "probability",
    "useProbability",
    "selectiveLogic",
    "outletName",
    "scanDepth",
    "caseSensitive",
    "matchWholeWords",
    "matchWholeWordsState",
    "caseSensitiveState",
    "group",
    "groupOverride",
    "groupWeight",
    "useGroupScoring",
    "useGroupScoringState",
    "automationId",
    "sticky",
    "cooldown",
    "delay",
    "triggers",
    "matchPersonaDescription",
    "matchCharacterDescription",
    "matchCharacterPersonality",
    "matchCharacterDepthPrompt",
    "matchScenario",
    "matchCreatorNotes",
    "use_regex",
    "characterFilter",
  ].forEach((key) => delete out[key]);

  return out;
};

const serializeEmbeddedWorldbook = (bookData, fallbackName = "World Info") => {
  if (!bookData) return null;
  const book = Array.isArray(bookData)
    ? { name: fallbackName, entries: bookData }
    : bookData;
  let entries = book.entries ?? [];
  if (entries && !Array.isArray(entries)) entries = Object.values(entries);

  return {
    ...book,
    name: book.name || fallbackName,
    entries: (entries || []).map((entry, index) =>
      serializeEmbeddedWiEntry(entry, index),
    ),
  };
};

export function stripStLoreEntryDefaults(entry) {
  const e = entry;

  // 1) 删 null
  Object.keys(e).forEach((k) => {
    if (e[k] === null) delete e[k];
  });

  // 2) 删空字符串
  Object.keys(e).forEach((k) => {
    if (typeof e[k] === "string" && e[k] === "") delete e[k];
  });

  // 3) 删空数组 (保留 key)
  Object.keys(e).forEach((k) => {
    if (Array.isArray(e[k]) && e[k].length === 0 && k !== "key") delete e[k];
  });

  // 4) 删默认 false 的布尔字段
  const defaultFalseKeys = [
    "constant",
    "disable",
    "use_regex",
    "vectorized",
    "addMemo",
    "ignoreBudget",
    "excludeRecursion",
    "preventRecursion",
    "groupOverride",
    "matchPersonaDescription",
    "matchCharacterDescription",
    "matchCharacterPersonality",
    "matchCharacterDepthPrompt",
    "matchScenario",
    "matchCreatorNotes",
  ];
  defaultFalseKeys.forEach((k) => {
    if (e[k] === false) delete e[k];
  });

  return e;
}

// 反向转换回 SillyTavern Lorebook V3 常见规范
export function toStV3Worldbook(bookData, fallbackName = "World Info") {
  if (!bookData) {
    return { name: fallbackName, entries: {} };
  }

  // 允许传入 V2 array
  const book = Array.isArray(bookData)
    ? { name: fallbackName, entries: bookData }
    : bookData;

  // entries: array / dict 都兼容
  let entries = book.entries ?? [];
  if (entries && !Array.isArray(entries)) {
    entries = Object.values(entries);
  }
  entries = entries || [];

  const exportEntries = {};
  entries.forEach((e, idx) => {
    const out = { ...e };

    // enabled -> disable (反向)
    const enabled =
      e.enabled !== undefined ? !!e.enabled : !(e.disable === true);
    out.disable = !enabled;

    // keys -> key
    out.key = e.keys !== undefined ? e.keys : (e.key ?? []);
    out.keysecondary =
      e.secondary_keys !== undefined
        ? e.secondary_keys
        : (e.keysecondary ?? []);

    // insertion_order -> order
    const order =
      e.insertion_order !== undefined
        ? Number(e.insertion_order)
        : e.order !== undefined
          ? Number(e.order)
          : 100;
    out.order = Number.isFinite(order) ? order : 100;

    // ST 常用字段：uid/displayIndex（用 idx 统一）
    const uid = e.uid ?? e.st_source_id ?? e.id ?? idx;
    out.uid = uid;
    out.displayIndex = e.displayIndex ?? idx;

    // 清理内部字段（避免写回文件污染）
    delete out.enabled;
    delete out.keys;
    delete out.secondary_keys;
    delete out.insertion_order;

    // 清理前端内部使用的字段
    delete out.id;
    delete out.st_manager_uid;
    delete out.st_source_id;

    stripStLoreEntryDefaults(out);
    exportEntries[String(uid)] = out;
  });

  // 保留世界书顶层其他字段（如果有），但覆盖 entries/name
  return {
    ...book,
    name: book.name || fallbackName,
    entries: exportEntries,
  };
}

// 前端归一化 entry 字段
export function normalizeWiEntry(entry, index = 0) {
  // === 辅助转换函数 ===
  const ST_DEFAULT_DEPTH = 4;
  const ST_DEFAULT_GROUP_WEIGHT = 100;
  const ST_DEFAULT_POSITION = 0;
  const ST_DEFAULT_ROLE = 0;
  const isPlainObject = (value) =>
    value && typeof value === "object" && !Array.isArray(value);
  const cloneArray = (value) => (Array.isArray(value) ? [...value] : []);
  const toFiniteNumber = (val, fallback) => {
    if (val === true) return 1;
    if (val === false) return 0;
    if (val === null || val === undefined || val === "") return fallback;
    const n = Number(val);
    return Number.isFinite(n) ? n : fallback;
  };
  const toNumber = (val, fieldName) => {
    if (val === true) return 1;
    if (val === false) return 0;
    if (val === null || val === undefined || val === "") {
      if (fieldName === "delayUntilRecursion") return 0;
      if (fieldName === "probability") return 100;
      return 0;
    }
    const n = Number(val);
    return isNaN(n) ? 0 : n;
  };

  const normalizeDelayUntilRecursion = (val) => {
    if (val === true || val === false) return val;
    if (val === null || val === undefined || val === "") return false;
    const n = Number(val);
    return Number.isFinite(n) ? n : false;
  };

  const normalizeTriStateBoolean = (val) => {
    if (val === true || val === false || val === null) return val;
    if (val === undefined || val === "") return null;
    if (val === "true") return true;
    if (val === "false") return false;
    if (val === "null") return null;
    return null;
  };

  // 1. 获取原始数组 (优先使用新字段，回退到旧字段)
  // 使用浅拷贝 [...arr] 断开引用
  const rawKeys = Array.isArray(entry.keys)
    ? entry.keys
    : Array.isArray(entry.key)
      ? entry.key
      : [];
  const rawSecKeys = Array.isArray(entry.secondary_keys)
    ? entry.secondary_keys
    : Array.isArray(entry.keysecondary)
      ? entry.keysecondary
      : [];

  // 2. 计算核心规范化字段
  const ext = isPlainObject(entry.extensions) ? entry.extensions : {};
  const sourceId = entry.st_source_id ?? entry.uid ?? entry.id;
  const isCharacterBookEntry =
    Array.isArray(entry.keys) || entry.enabled !== undefined || !!entry.extensions;
  const rawPosition =
    ext.position ??
    (typeof entry.position === "string"
      ? entry.position === "before_char"
        ? 0
        : 1
      : entry.position);

  const normalizedFields = {
    // ID: 使用索引号 (0,1,2,3...)，确保 Alpine.js key 追踪稳定
    // id 越大条目越靠下显示
    id: index,

    st_source_id: sourceId,
    insertion_order: toNumber(entry.insertion_order ?? entry.order, "order"),
    position: toFiniteNumber(rawPosition, ST_DEFAULT_POSITION),
    depth: toFiniteNumber(ext.depth ?? entry.depth, ST_DEFAULT_DEPTH),
    role: toFiniteNumber(ext.role ?? entry.role, ST_DEFAULT_ROLE),
    displayIndex: toFiniteNumber(
      ext.display_index ?? entry.displayIndex,
      index,
    ),
    probability: toNumber(ext.probability ?? entry.probability, "probability"),
    selectiveLogic: toNumber(
      ext.selectiveLogic ?? entry.selectiveLogic,
      "selectiveLogic",
    ),
    delayUntilRecursion: normalizeDelayUntilRecursion(
      ext.delay_until_recursion ?? entry.delayUntilRecursion,
    ),

    // 逻辑反转处理：统一使用enabled
    enabled:
      entry.enabled !== undefined ? !!entry.enabled : !(entry.disable === true),

    constant: !!entry.constant,
    vectorized: !!(ext.vectorized ?? entry.vectorized),
    excludeRecursion: !!(ext.exclude_recursion ?? entry.excludeRecursion),
    preventRecursion: !!(ext.prevent_recursion ?? entry.preventRecursion),
    ignoreBudget: !!(ext.ignore_budget ?? entry.ignoreBudget),
    matchWholeWords: normalizeTriStateBoolean(
      ext.match_whole_words ?? entry.matchWholeWords,
    ),
    caseSensitive: normalizeTriStateBoolean(
      ext.case_sensitive ?? entry.caseSensitive,
    ),
    use_regex: !!entry.use_regex,
    selective:
      entry.selective !== undefined ? !!entry.selective : !isCharacterBookEntry,
    useProbability:
      (ext.useProbability ?? entry.useProbability) !== undefined
        ? !!(ext.useProbability ?? entry.useProbability)
        : true,
    outletName: ext.outlet_name ?? entry.outletName ?? "",
    group: ext.group ?? entry.group ?? "",
    groupOverride: !!(ext.group_override ?? entry.groupOverride),
    groupWeight: toFiniteNumber(
      ext.group_weight ?? entry.groupWeight,
      ST_DEFAULT_GROUP_WEIGHT,
    ),
    scanDepth:
      (ext.scan_depth ?? entry.scanDepth) === null ||
      (ext.scan_depth ?? entry.scanDepth) === undefined ||
      (ext.scan_depth ?? entry.scanDepth) === ""
        ? null
        : toFiniteNumber(ext.scan_depth ?? entry.scanDepth, null),
    useGroupScoring: normalizeTriStateBoolean(
      ext.use_group_scoring ?? entry.useGroupScoring,
    ),
    automationId: ext.automation_id ?? entry.automationId ?? "",
    sticky: ext.sticky ?? entry.sticky ?? null,
    cooldown: ext.cooldown ?? entry.cooldown ?? null,
    delay: ext.delay ?? entry.delay ?? null,
    triggers: cloneArray(ext.triggers ?? entry.triggers),
    characterFilter: entry.characterFilter ?? entry.character_filter,
    matchPersonaDescription: !!(
      ext.match_persona_description ?? entry.matchPersonaDescription
    ),
    matchCharacterDescription: !!(
      ext.match_character_description ?? entry.matchCharacterDescription
    ),
    matchCharacterPersonality: !!(
      ext.match_character_personality ?? entry.matchCharacterPersonality
    ),
    matchCharacterDepthPrompt: !!(
      ext.match_character_depth_prompt ?? entry.matchCharacterDepthPrompt
    ),
    matchScenario: !!(ext.match_scenario ?? entry.matchScenario),
    matchCreatorNotes: !!(
      ext.match_creator_notes ?? entry.matchCreatorNotes
    ),

    // 数组拷贝
    keys: [...rawKeys],
    secondary_keys: [...rawSecKeys],

    content: entry.content || "",
    comment: entry.comment || "",
  };

  // 3. 构造最终对象：保留 Unknown Fields，但移除 Legacy Fields
  // 这里的技巧是：先解构出我们不要的旧字段，把剩下的放在 others 里
  const {
    // 黑名单：这些是 ST 的旧字段名，我们已经转换到上面的 normalizedFields 里了，不要保留在对象中
    key,
    keysecondary,
    disable,
    order,
    uid,
    // 同时也把我们要覆盖的字段解构出来（防止它们留在 others 里被重复定义）
    id,
    insertion_order,
    enabled,
    keys,
    secondary_keys,
    content,
    comment,
    st_source_id,
    displayIndex,
    outletName,
    scanDepth,
    group,
    groupOverride,
    groupWeight,
    useGroupScoring,
    automationId,
    sticky,
    cooldown,
    delay,
    triggers,
    matchPersonaDescription,
    matchCharacterDescription,
    matchCharacterPersonality,
    matchCharacterDepthPrompt,
    matchScenario,
    matchCreatorNotes,
    character_filter,
    // 剩下的就是真正的 Unknown Fields
    ...others
  } = entry;

  return {
    ...others, // 1. 先放插件数据/未知字段
    ...normalizedFields, // 2. 再放我们标准化的核心数据
  };
}

// 归一化整本世界书
export function normalizeWiBook(bookData, fallbackName = "World Info") {
  let book = bookData || {};

  // 兼容 Array
  if (Array.isArray(book)) {
    book = { entries: book, name: fallbackName };
  }

  let entries = book.entries;
  // 兼容 Dict entries
  if (entries && !Array.isArray(entries)) {
    entries = Object.values(entries);
  }
  if (!entries) entries = [];

  // 执行归一化，并分配索引作为 id（0,1,2,3...）
  const fixedEntries = entries.map((e, idx) => normalizeWiEntry(e, idx));

  return {
    ...book,
    name: book.name || fallbackName,
    entries: fixedEntries,
  };
}

// === 获取清洗后的标准 V3 数据对象 ===
export function getCleanedV3Data(editingData) {
  // 1. 深拷贝当前编辑数据
  const raw = JSON.parse(JSON.stringify(editingData));

  // 2. 清洗备用开场白 (移除空字符串)
  if (raw.alternate_greetings && Array.isArray(raw.alternate_greetings)) {
    raw.alternate_greetings = raw.alternate_greetings.filter(
      (s) => s && s.trim() !== "",
    );
  }

  // 3. 清洗世界书 (防止空对象或只有默认名的情况)
  if (raw.character_book) {
    const entries = raw.character_book.entries;
    const name = raw.character_book.name;
    // 如果既无条目，名字又是默认/空，视为无世界书，存为 null
    if (
      (!entries || entries.length === 0) &&
      (!name || name === "World Info" || name === "")
    ) {
      raw.character_book = null;
    }
  }

  // 4. 清洗扩展数据 (确保是数组)
  if (raw.extensions) {
    if (!Array.isArray(raw.extensions.regex_scripts)) {
      // 如果不存在或不是数组，初始化为空数组
      raw.extensions.regex_scripts = raw.extensions.regex_scripts || [];
    }

    // 对 tavern_helper 进行智能判断
    const th = raw.extensions.tavern_helper;
    if (!th) {
      // 不存在则初始化为空数组 (旧版兼容默认)
      raw.extensions.tavern_helper = [];
    } else {
      // 如果存在，判断类型
      if (Array.isArray(th)) {
        // 是数组 (旧版)，保留
      } else if (typeof th === "object") {
        // 是对象 (新版)，保留
      } else {
        // 异常数据，重置
        raw.extensions.tavern_helper = [];
      }
    }
  } else {
    // 如果 extensions 根节点都不存在
    raw.extensions = { regex_scripts: [], tavern_helper: [] };
  }

  // 5. 清理世界书条目的前端内部字段，并重新分配索引 id（0,1,2,3...）
  if (raw.character_book) {
    raw.character_book = serializeEmbeddedWorldbook(
      raw.character_book,
      raw.char_name || "World Info",
    );
  }

  // 6. 构建标准 V3 结构 (明确指定字段，丢弃多余的 UI 临时状态)
  return {
    name: raw.char_name,
    description: raw.description || "",
    first_mes: raw.first_mes || "",
    mes_example: raw.mes_example || "",
    personality: raw.personality || "",
    scenario: raw.scenario || "",
    creator_notes: raw.creator_notes || "",
    system_prompt: raw.system_prompt || "",
    post_history_instructions: raw.post_history_instructions || "",
    tags: raw.tags || [],
    creator: raw.creator || "",
    character_version: raw.character_version || "",
    alternate_greetings: raw.alternate_greetings || [],
    extensions: raw.extensions || {},
    character_book: raw.character_book,
    spec: "chara_card_v3",
    spec_version: "3.0",
    data: {
      name: raw.char_name,
      description: raw.description || "",
      first_mes: raw.first_mes || "",
      mes_example: raw.mes_example || "",
      personality: raw.personality || "",
      scenario: raw.scenario || "",
      creator_notes: raw.creator_notes || "",
      system_prompt: raw.system_prompt || "",
      post_history_instructions: raw.post_history_instructions || "",
      tags: raw.tags || [],
      creator: raw.creator || "",
      character_version: raw.character_version || "",
      alternate_greetings: raw.alternate_greetings || [],
      extensions: raw.extensions || {},
      character_book: raw.character_book,
    },
  };
}
