/**
 * World Info sorting compatible with SillyTavern's world-info sorter.
 *
 * `displayIndex` is the persisted custom-order field.  It is deliberately
 * kept separate from the manager's array index and from `st_manager_uid`.
 */

export const WI_SORT_STORAGE_KEY = "st_manager_wi_sort_mode";

export const WI_SORT_OPTIONS = [
  { value: "priority", label: "优先级", shortLabel: "优先级" },
  { value: "custom", label: "自定义", shortLabel: "自定义" },
  { value: "title_asc", label: "标题 A-Z", shortLabel: "标题 A-Z" },
  { value: "title_desc", label: "标题 Z-A", shortLabel: "标题 Z-A" },
  { value: "tokens_asc", label: "Token ↑", shortLabel: "Token ↑" },
  { value: "tokens_desc", label: "Token ↓", shortLabel: "Token ↓" },
  { value: "depth_asc", label: "深度 ↑", shortLabel: "深度 ↑" },
  { value: "depth_desc", label: "深度 ↓", shortLabel: "深度 ↓" },
  { value: "order_asc", label: "Order ↑", shortLabel: "Order ↑" },
  { value: "order_desc", label: "Order ↓", shortLabel: "Order ↓" },
  { value: "uid_asc", label: "UID ↑", shortLabel: "UID ↑" },
  { value: "uid_desc", label: "UID ↓", shortLabel: "UID ↓" },
  { value: "probability_asc", label: "触发率 ↑", shortLabel: "触发率 ↑" },
  { value: "probability_desc", label: "触发率 ↓", shortLabel: "触发率 ↓" },
];

const VALID_SORT_MODES = new Set(WI_SORT_OPTIONS.map((option) => option.value));

export function normalizeWiSortMode(value) {
  const mode = String(value || "").trim();
  return VALID_SORT_MODES.has(mode) ? mode : "priority";
}

export function loadWiSortMode() {
  try {
    return normalizeWiSortMode(window.localStorage.getItem(WI_SORT_STORAGE_KEY));
  } catch (_error) {
    return "priority";
  }
}

export function saveWiSortMode(value) {
  const mode = normalizeWiSortMode(value);
  try {
    window.localStorage.setItem(WI_SORT_STORAGE_KEY, mode);
  } catch (_error) {
    // Private browsing and disabled storage should not break the editor.
  }
  return mode;
}

export function getWiSortLabel(value) {
  const mode = normalizeWiSortMode(value);
  return (
    WI_SORT_OPTIONS.find((option) => option.value === mode)?.label ||
    WI_SORT_OPTIONS[0].label
  );
}

export function getWiEntrySourceUid(entry, fallbackIndex = 0) {
  if (!entry || typeof entry !== "object") return fallbackIndex;
  const sourceUid = entry.st_source_id ?? entry.uid;
  if (sourceUid !== undefined && sourceUid !== null && sourceUid !== "") {
    return sourceUid;
  }
  return entry.id ?? fallbackIndex;
}

export function getWiEntryIdentity(entry, fallbackIndex = 0) {
  if (!entry || typeof entry !== "object") return `index:${fallbackIndex}`;
  if (entry.st_manager_uid) return `manager:${String(entry.st_manager_uid)}`;
  const sourceUid = getWiEntrySourceUid(entry, fallbackIndex);
  return `source:${String(sourceUid)}`;
}

function toNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function entryOrder(entry) {
  return toNumber(entry?.insertion_order ?? entry?.order, 0);
}

function entryDepth(entry) {
  return toNumber(entry?.depth, 0);
}

function entryProbability(entry) {
  return toNumber(entry?.probability, 100);
}

function entryTitle(entry) {
  return String(entry?.comment ?? entry?.title ?? "");
}

function entryContentLength(entry) {
  return String(entry?.content ?? "").length;
}

function compareValues(left, right, direction = 1) {
  if (typeof left === "string" || typeof right === "string") {
    return String(left).localeCompare(String(right), undefined, {
      numeric: true,
      sensitivity: "base",
    }) * direction;
  }
  return (toNumber(left) - toNumber(right)) * direction;
}

function compareUids(left, right) {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return String(left).localeCompare(String(right), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

export function getWiDisplayIndex(entry, fallbackIndex = 0) {
  const value = entry?.displayIndex ?? entry?.extensions?.display_index;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallbackIndex;
}

export function getNextWiDisplayIndex(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return 0;
  return (
    Math.max(
      ...entries.map((entry, index) => getWiDisplayIndex(entry, index)),
    ) + 1
  );
}

function priorityRank(entry) {
  if (entry?.disable === true || entry?.enabled === false) return 2;
  if (entry?.constant) return 0;
  return 1;
}

function primaryCompare(left, right, mode) {
  switch (mode) {
    case "custom":
      return compareValues(
        left?.displayIndex ?? left?.extensions?.display_index ?? left?.id ?? 0,
        right?.displayIndex ?? right?.extensions?.display_index ?? right?.id ?? 0,
      );
    case "title_asc":
      return compareValues(entryTitle(left), entryTitle(right));
    case "title_desc":
      return compareValues(entryTitle(left), entryTitle(right), -1);
    case "tokens_asc":
      return compareValues(entryContentLength(left), entryContentLength(right));
    case "tokens_desc":
      return compareValues(
        entryContentLength(left),
        entryContentLength(right),
        -1,
      );
    case "depth_asc":
      return compareValues(entryDepth(left), entryDepth(right));
    case "depth_desc":
      return compareValues(entryDepth(left), entryDepth(right), -1);
    case "order_asc":
      return compareValues(entryOrder(left), entryOrder(right));
    case "order_desc":
      return compareValues(entryOrder(left), entryOrder(right), -1);
    case "uid_asc":
      return compareUids(
        getWiEntrySourceUid(left),
        getWiEntrySourceUid(right),
      );
    case "uid_desc":
      return compareUids(
        getWiEntrySourceUid(right),
        getWiEntrySourceUid(left),
      );
    case "probability_asc":
      return compareValues(entryProbability(left), entryProbability(right));
    case "probability_desc":
      return compareValues(
        entryProbability(left),
        entryProbability(right),
        -1,
      );
    case "priority":
    default:
      return priorityRank(left) - priorityRank(right);
  }
}

export function compareWiEntries(left, right, mode = "priority") {
  const normalizedMode = normalizeWiSortMode(mode);
  const primary = primaryCompare(left, right, normalizedMode);
  if (primary) return primary;

  // This mirrors SillyTavern: insertion order is the secondary descending key.
  const secondary = entryOrder(right) - entryOrder(left);
  if (secondary) return secondary;

  return compareUids(
    getWiEntrySourceUid(left),
    getWiEntrySourceUid(right),
  );
}

export function sortWiEntries(entries, mode = "priority") {
  if (!Array.isArray(entries)) return [];
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => {
      const result = compareWiEntries(left.entry, right.entry, mode);
      return result || left.index - right.index;
    })
    .map(({ entry }) => entry);
}

export function setWiCustomDisplayIndexes(entries) {
  if (!Array.isArray(entries)) return entries;
  const startIndex = entries.length
    ? Math.min(
        ...entries.map((entry, index) => getWiDisplayIndex(entry, index)),
      )
    : 0;
  entries.forEach((entry, index) => {
    if (entry && typeof entry === "object") {
      // SillyTavern keeps the first existing display index as the base and
      // only rewrites the relative order after a custom drag.
      entry.displayIndex = startIndex + index;
    }
  });
  return entries;
}
