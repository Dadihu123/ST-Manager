const PASTE_HANDLER_KEY = "__stManagerPasteImportHandlerInstalled";

const IMPORT_MODE_BY_GROUP = Object.freeze({
  card: "cards",
  worldinfo: "worldinfo",
  preset: "presets",
  chat: "chats",
});

const EXTENSION_IMPORT_TYPES = Object.freeze([
  "regex",
  "scripts",
  "quick_replies",
]);

const EDITABLE_SELECTOR = [
  "input",
  "textarea",
  "select",
  "[contenteditable]",
  '[role="textbox"]',
  ".CodeMirror",
  ".cm-editor",
].join(",");

function getGlobalStore() {
  if (!window.Alpine || typeof window.Alpine.store !== "function") return null;
  try {
    return window.Alpine.store("global");
  } catch {
    return null;
  }
}

function notify(message, tone = "info") {
  const store = getGlobalStore();
  if (store && typeof store.showToast === "function") {
    store.showToast(message, tone === "error" ? "error" : 2600);
    return;
  }
  if (typeof window.alert === "function") {
    window.alert(message);
  }
}

function isHttpUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function getFileExtension(file) {
  const name = String(file?.name || "").toLowerCase();
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index);
}

function hasAnyKey(source, keys) {
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    return false;
  }
  return keys.some((key) => Object.prototype.hasOwnProperty.call(source, key));
}

function hasAllKeys(source, keys) {
  return !!source && keys.every((key) => Object.prototype.hasOwnProperty.call(source, key));
}

function isJsObject(value) {
  return value === null || (typeof value === "object" && value !== undefined);
}

function looksLikeWorldInfo(data) {
  return data && typeof data === "object" && !Array.isArray(data) && "entries" in data;
}

function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function isValidRegexObject(value) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (isNonEmptyString(value.scriptName) || Object.prototype.hasOwnProperty.call(value, "findRegex"))
  );
}

export function isValidRegexData(data) {
  if (isValidRegexObject(data)) return true;
  return Array.isArray(data) && data.length > 0 && data.every(isValidRegexObject);
}

function isScalarForCoerceString(value) {
  return true;
}

function isValidScriptButton(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return "name" in value && isScalarForCoerceString(value.name) && "visible" in value && typeof value.visible === "boolean";
}

function isValidBackwardScriptButton(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if ("name" in value && typeof value.name !== "string") return false;
  return !("visible" in value) || typeof value.visible === "boolean";
}

function isValidNewScript(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if ("type" in value && value.type !== "script") return false;
  if ("enabled" in value && typeof value.enabled !== "boolean") return false;
  for (const key of ["name", "id", "content", "info"]) {
    if (key in value && !isScalarForCoerceString(value[key])) return false;
  }
  if ("button" in value) {
    const button = value.button;
    if (!button || typeof button !== "object" || Array.isArray(button)) return false;
    if ("enabled" in button && typeof button.enabled !== "boolean") return false;
    if (
      "buttons" in button &&
      (!Array.isArray(button.buttons) || !button.buttons.every(isValidScriptButton))
    ) {
      return false;
    }
  }
  if ("data" in value && (!value.data || typeof value.data !== "object" || Array.isArray(value.data))) {
    return false;
  }
  if ("export_with" in value) {
    const exportWith = value.export_with;
    if (!exportWith || typeof exportWith !== "object" || Array.isArray(exportWith)) return false;
    for (const key of ["data", "button"]) {
      if (key in exportWith && typeof exportWith[key] !== "boolean") return false;
    }
  }
  return true;
}

function isValidBackwardScript(value) {
  const buttons = value.buttons === undefined ? [] : value.buttons;
  if (!Array.isArray(buttons) || !buttons.every(isValidBackwardScriptButton) ||
    ("enabled" in value && typeof value.enabled !== "boolean")) {
    return false;
  }
  for (const key of ["name", "id", "content", "info"]) {
    if (key in value && typeof value[key] !== "string") return false;
  }
  return !("data" in value) || (!!value.data && typeof value.data === "object" && !Array.isArray(value.data));
}

function isValidScriptFolder(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || value.type !== "folder") return false;
  if ("enabled" in value && typeof value.enabled !== "boolean") return false;
  for (const key of ["name", "id"]) {
    if (key in value && !isScalarForCoerceString(value[key])) return false;
  }
  for (const key of ["icon", "color"]) {
    if (key in value && typeof value[key] !== "string") return false;
  }
  const scripts = value.scripts === undefined ? [] : value.scripts;
  return Array.isArray(scripts) && scripts.every(isValidNewScript);
}

function isValidBackwardScriptTreeItem(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (value.type === "script") {
    return !!value.value && typeof value.value === "object" && !Array.isArray(value.value) &&
      isValidBackwardScript(value.value);
  }
  if (value.type === "folder") {
    const scripts = value.value === undefined ? [] : value.value;
    return Array.isArray(scripts) && scripts.every(isValidBackwardScript);
  }
  return isValidBackwardScript(value);
}

export function isValidScriptData(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return false;
  if (data.type === "script") {
    if (Object.prototype.hasOwnProperty.call(data, "value")) {
      return isValidBackwardScriptTreeItem(data);
    }
    return isValidNewScript(data);
  }
  if (data.type === "folder") {
    if (Object.prototype.hasOwnProperty.call(data, "value")) {
      return isValidBackwardScriptTreeItem(data);
    }
    return isValidScriptFolder(data);
  }
  return data.type === undefined && "buttons" in data && isValidBackwardScript(data);
}

function isValidQuickReply(data) {
  return (
    data &&
    typeof data === "object" &&
    !Array.isArray(data) &&
    typeof data.version === "number" &&
    Number.isFinite(data.version) &&
    Number.isInteger(data.version) &&
    typeof data.name === "string" &&
    Array.isArray(data.qrList)
  );
}

function classifyExtensionJson(data) {
  if (isValidRegexData(data)) return "regex";
  if (isValidScriptData(data)) return "scripts";
  if (isValidQuickReply(data)) return "quick_replies";

  return "";
}

function looksLikePreset(data) {
  return hasAnyKey(data, [
    "name",
    "title",
    "description",
    "note",
    "temperature",
    "temp",
    "max_tokens",
    "openai_max_tokens",
    "max_length",
    "min_length",
    "top_p",
    "top_k",
    "top_a",
    "min_p",
    "typical_p",
    "typical",
    "tfs",
    "temperature_last",
    "dynamic_temperature",
    "dynatemp",
    "dynatemp_low",
    "dynatemp_high",
    "min_temp",
    "max_temp",
    "repetition_penalty",
    "rep_pen",
    "frequency_penalty",
    "freq_pen",
    "presence_penalty",
    "pres_pen",
    "mirostat_mode",
    "mirostat_tau",
    "mirostat_eta",
    "guidance_scale",
    "negative_prompt",
    "json_schema",
    "grammar",
    "grammar_string",
    "banned_tokens",
    "logit_bias",
    "sampler_order",
    "samplers",
    "input_sequence",
    "output_sequence",
    "system_sequence",
    "first_output_sequence",
    "last_output_sequence",
    "prompts",
    "prompt_order",
    "system_prompt",
    "post_history_instructions",
    "api_type",
    "openai_max_context",
    "stream_openai",
    "show_thoughts",
    "reasoning_effort",
    "verbosity",
    "chat_completion_source",
    "openai_model",
    "openrouter_model",
    "use_sysprompt",
    "custom_url",
    "reverse_proxy",
    "proxy_password",
    "names_behavior",
    "function_calling",
    "media_inlining",
    "request_images",
    "request_image_aspect_ratio",
    "request_image_resolution",
    "max_context_unlocked",
    "group_models",
    "sort_models",
    "claude_model",
    "openrouter_use_fallback",
    "openrouter_providers",
    "openrouter_quantizations",
    "openrouter_allow_fallbacks",
    "openrouter_middleout",
    "tool_reasoning_mode",
    "assistant_prefill",
    "assistant_impersonation",
    "impersonation_prompt",
    "new_chat_prompt",
    "continue_nudge_prompt",
    "continue_prefill",
    "continue_postfix",
    "bias_preset_selected",
    "custom_model",
    "custom_include_body",
    "custom_exclude_body",
    "custom_include_headers",
    "custom_prompt_post_processing",
    "send_if_empty",
    "use_system_prompt",
    "use_stop_strings",
    "stop_strings",
    "__st_manager_preset_kind",
  ]);
}

function looksLikeCharacterCard(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return false;
  if (hasAllKeys(data, ["name", "description", "personality", "scenario", "first_mes", "mes_example"])) {
    return true;
  }

  const cardData = data.data;
  if (data.spec === "chara_card_v2" && data.spec_version === "2.0") {
    if (
      !cardData ||
      typeof cardData !== "object" ||
      Array.isArray(cardData) ||
      !hasAllKeys(cardData, [
        "name",
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
        "alternate_greetings",
        "tags",
        "creator",
        "character_version",
        "extensions",
      ]) ||
      !Array.isArray(cardData.alternate_greetings) ||
      !Array.isArray(cardData.tags) ||
      !isJsObject(cardData.extensions)
    ) {
      return false;
    }
    if (!cardData.character_book) return true;
    const characterBook = cardData.character_book;
    return (
      characterBook &&
      typeof characterBook === "object" &&
      !Array.isArray(characterBook) &&
      hasAllKeys(characterBook, ["extensions", "entries"]) &&
      Array.isArray(characterBook.entries) &&
      isJsObject(characterBook.extensions)
    );
  }

  const cardVersion = Number(data.spec_version);
  if (
    data.spec === "chara_card_v3" &&
    Number.isFinite(cardVersion) &&
    cardVersion >= 3 &&
    cardVersion < 4
  ) {
    return !!cardData && typeof cardData === "object" && !Array.isArray(cardData);
  }

  return false;
}

async function readJsonFile(file) {
  const text =
    typeof file.text === "function"
      ? await file.text()
      : await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(reader.error || new Error("read failed"));
          reader.readAsText(file);
        });
  return JSON.parse(text);
}

export function shouldIgnorePasteTarget(target) {
  if (!target || typeof target.closest !== "function") return false;
  return !!target.closest(EDITABLE_SELECTOR);
}

export function extractPastedUrl(event) {
  const text = String(event?.clipboardData?.getData?.("text/plain") || "").trim();
  if (!text || /\s/.test(text)) return "";
  return isHttpUrl(text) ? text : "";
}

export function extractPastedFiles(event) {
  const files = Array.from(event?.clipboardData?.files || []).filter(Boolean);
  if (files.length > 0) return files;

  const items = Array.from(event?.clipboardData?.items || []);
  return items
    .filter((item) => item && item.kind === "file")
    .map((item) => item.getAsFile())
    .filter(Boolean);
}

export async function classifyFile(file) {
  const ext = getFileExtension(file);
  if (ext === ".jsonl") return { type: "chat" };
  if (ext === ".png" || String(file?.type || "").toLowerCase() === "image/png") {
    return { type: "card" };
  }
  if (ext !== ".json") {
    return { type: "unknown", reason: "不支持的文件类型" };
  }

  let data;
  try {
    data = await readJsonFile(file);
  } catch {
    return { type: "unknown", reason: "JSON 解析失败" };
  }

  const extensionType = classifyExtensionJson(data);
  if (extensionType) return { type: "extension", extensionType };
  if (looksLikeWorldInfo(data)) return { type: "worldinfo" };
  if (looksLikeCharacterCard(data)) return { type: "card" };
  if (looksLikePreset(data)) return { type: "preset" };

  return { type: "unknown", reason: "无法识别资源类型" };
}

export async function classifyFiles(files) {
  const groups = {
    card: [],
    worldinfo: [],
    preset: [],
    chat: [],
    extension: {
      regex: [],
      scripts: [],
      quick_replies: [],
    },
    unknown: [],
  };

  for (const file of files || []) {
    const result = await classifyFile(file);
    if (result.type === "extension") {
      groups.extension[result.extensionType || "regex"].push(file);
    } else if (result.type && result.type !== "unknown") {
      groups[result.type].push(file);
    } else {
      groups.unknown.push({
        file,
        reason: result.reason || "无法识别资源类型",
      });
    }
  }

  return groups;
}

/**
 * Only switch the workspace automatically when a paste contains one resource
 * type. Mixed pastes stay in the current workspace so the final view remains
 * predictable while each uploader still receives its own file group.
 */
export function getPasteImportMode(groups) {
  const modes = [];

  Object.entries(IMPORT_MODE_BY_GROUP).forEach(([group, mode]) => {
    if (Array.isArray(groups?.[group]) && groups[group].length > 0) {
      modes.push(mode);
    }
  });

  EXTENSION_IMPORT_TYPES.forEach((extensionType) => {
    if (
      Array.isArray(groups?.extension?.[extensionType]) &&
      groups.extension[extensionType].length > 0
    ) {
      modes.push(extensionType);
    }
  });

  const uniqueModes = [...new Set(modes)];
  return uniqueModes.length === 1 ? uniqueModes[0] : "";
}

export function syncViewToPasteImportMode(groups) {
  const mode = getPasteImportMode(groups);
  if (!mode) return "";

  const store = getGlobalStore();
  if (store) store.currentMode = mode;

  if (typeof window.dispatchEvent === "function") {
    window.dispatchEvent(
      new CustomEvent("switch-mode", {
        detail: { mode },
      }),
    );
  }

  return mode;
}

function callUploader(name, files, ...args) {
  if (!files || files.length === 0) return false;
  const uploader = window[name];
  if (typeof uploader !== "function") {
    notify(`当前页面未就绪，无法处理 ${files.length} 个文件`, "error");
    return false;
  }
  uploader(files, ...args);
  return true;
}

export function dispatchImportGroups(groups) {
  let dispatched = 0;

  if (callUploader("stUploadCardFiles", groups.card)) dispatched += groups.card.length;
  if (callUploader("stUploadWorldInfoFiles", groups.worldinfo)) dispatched += groups.worldinfo.length;
  if (callUploader("stUploadPresetFiles", groups.preset)) dispatched += groups.preset.length;
  if (callUploader("stUploadChatFiles", groups.chat)) dispatched += groups.chat.length;

  Object.entries(groups.extension || {}).forEach(([targetType, files]) => {
    if (callUploader("stUploadExtensionFiles", files, targetType)) {
      dispatched += files.length;
    }
  });

  return dispatched;
}

export function showPasteImportSummary(groups, dispatched) {
  const unknown = groups.unknown || [];
  if (unknown.length > 0) {
    const message = unknown
      .map((item) => `${item.file?.name || "未命名文件"}: ${item.reason}`)
      .join("\n");
    notify(`部分文件无法通过粘贴导入：\n${message}`, "error");
    return;
  }

  if (dispatched > 1) {
    notify(`已分流 ${dispatched} 个粘贴文件`);
  }
}

export async function handlePasteImport(event) {
  if (shouldIgnorePasteTarget(event?.target)) return false;

  const files = extractPastedFiles(event);
  if (files.length > 0) {
    event.preventDefault();
    const groups = await classifyFiles(files);
    syncViewToPasteImportMode(groups);
    const dispatched = dispatchImportGroups(groups);
    showPasteImportSummary(groups, dispatched);
    return true;
  }

  const url = extractPastedUrl(event);
  if (!url) return false;

  event.preventDefault();
  const store = getGlobalStore();
  const category = store?.viewState?.filterCategory || "";
  window.dispatchEvent(
    new CustomEvent("open-import-url", {
      detail: { url, category },
    }),
  );
  return true;
}

export function initPasteImportHandler() {
  if (window[PASTE_HANDLER_KEY]) return;
  window[PASTE_HANDLER_KEY] = true;
  window.addEventListener("paste", (event) => {
    handlePasteImport(event).catch((error) => {
      console.error("[paste import]", error);
      notify("粘贴导入失败", "error");
    });
  });
}
