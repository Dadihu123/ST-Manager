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

function looksLikeWorldInfo(data) {
  if (data && typeof data === "object" && !Array.isArray(data) && "entries" in data) {
    return true;
  }
  if (!Array.isArray(data) || data.length === 0) return false;
  return data.some(
    (entry) =>
      entry &&
      typeof entry === "object" &&
      ("keys" in entry || "key" in entry || "content" in entry),
  );
}

function classifyExtensionJson(data) {
  if (data && typeof data === "object" && !Array.isArray(data)) {
    if ("findRegex" in data || "regex" in data || "scriptName" in data) {
      return "regex";
    }
    if (data.type === "script" || "scripts" in data) {
      return "scripts";
    }
    if ("qrList" in data || "quickReplies" in data) {
      return "quick_replies";
    }
    if ("entries" in data && ("version" in data || "disableSend" in data)) {
      return "quick_replies";
    }
  }

  if (Array.isArray(data) && data.length > 0 && data[0] === "scripts") {
    return "scripts";
  }

  return "";
}

function looksLikePreset(data) {
  return hasAnyKey(data, [
    "temperature",
    "max_tokens",
    "openai_max_tokens",
    "max_length",
    "top_p",
    "top_k",
    "prompts",
    "prompt_order",
    "system_prompt",
    "api_type",
  ]);
}

function looksLikeCharacterCard(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return false;
  if ((data.spec || data.spec_version) && data.data && typeof data.data === "object") {
    return true;
  }
  const characterKeys = [
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
  ];
  return characterKeys.filter((key) => key in data).length >= 2;
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
  if (looksLikePreset(data)) return { type: "preset" };
  if (looksLikeCharacterCard(data)) return { type: "card" };

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
