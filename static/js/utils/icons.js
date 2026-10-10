/**
 * static/js/utils/icons.js
 * 宿主图标名解析（设计文档 D4 的前端侧）。
 *
 * 契约：插件在 `entries[].icon` 与 `api.ui.icon()` 里写**宿主图标名**
 * （如 `wand`、`bolt`），宿主负责解析成正确的 sprite 与 `<use>` 引用。
 *
 * 命名空间区分（硬规则，设计文档 2.2「图标名契约（D4）」）：
 * - 宿主图标名**不含** `/` 与 `.`（如 `wand`）→ 解析为宿主 sprite 的 `<use>`
 * - 插件自带资源路径**必含** `/`（如 `assets/logo.svg`）→ 解析为
 *   `/api/plugins/<pluginId>/assets/<path>`（见 `resolvePluginIcon`）
 *
 * 名字 → sprite 的映射由 `tools/gen_plugin_ui_icons.py` 从 `static/icons/*.svg`
 * 生成（见 `./iconMap.js`），与后端 `core/plugins/icons.py` 同源。
 */

import { HOST_ICON_COUNT, ICON_ALIASES, ICON_SPRITE_MAP } from "./iconMap.js";

const STATIC_ICON_BASE = "/static/icons";
const PLUGIN_ASSET_BASE = "/api/plugins";

/** 与后端 `assets.ALLOWED_EXTENSIONS` 对齐的图标扩展名子集。 */
export const PLUGIN_ICON_EXTENSIONS = new Set([".svg", ".png", ".webp"]);

/** 判断取值是否是宿主图标名（而非插件自带资源路径）。 */
export function isHostIconName(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return !text.includes("/") && !text.includes("\\") && !text.includes(".");
}

/** 解析别名（`plus` → `plus-square`、`grid` → `layout`）。 */
export function canonicalIconName(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return ICON_ALIASES[text] || text;
}

/** 返回图标所属精灵文件名；未知名字返回空串。 */
export function spriteForIcon(value) {
  const name = canonicalIconName(value);
  if (!name) return "";
  return ICON_SPRITE_MAP[name] || "";
}

/**
 * 把插件自带资源路径解析为可用的 URL。
 *
 * `entries[].icon` 允许两种取值（设计文档 2.2 / 8.3.1）：宿主图标名，或
 * 插件内资源路径（如 `assets/icon.svg`、`frontend/assets/icon.svg`）。
 * 后者必须带上插件 id 才能定位——路径里本身不含 id，所以这里要求调用方
 * 提供 `pluginId`；拿不到 id 时返回空串（降级为占位图标，而不是猜一个 URL）。
 *
 * 安全：与后端 `core/plugins/assets.py` 同一套约束——拒绝绝对路径、拒绝 `..`、
 * 只放行 `ALLOWED_EXTENSIONS`（`.svg` 在内）。这里做的是**前端侧**的提前拒绝，
 * 真正的边界检查仍在后端路由。
 *
 * @param {string} value 资源路径（相对插件根目录）。
 * @param {string} pluginId 插件 id。
 * @returns {string} `/api/plugins/<id>/assets/<path>`；非法或缺少 id 时返回空串。
 */
export function resolvePluginIcon(value, pluginId) {
  const id = String(pluginId || "").trim();
  if (!id) return "";

  const relative = String(value || "").trim().replace(/\\/g, "/").replace(/^\/+/, "");
  if (!relative) return "";
  if (relative.split("/").includes("..")) return "";

  const extension = relative.slice(relative.lastIndexOf(".")).toLowerCase();
  if (!PLUGIN_ICON_EXTENSIONS.has(extension)) return "";

  const encoded = relative
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `${PLUGIN_ASSET_BASE}/${encodeURIComponent(id)}/assets/${encoded}`;
}

/**
 * 解析出可直接用于渲染的图标描述。
 *
 * 返回值区分三种情况，调用方据此决定怎么渲染：
 * - `{ kind: 'host', href }`：宿主 sprite 的 `<use href>`；
 * - `{ kind: 'asset', url }`：插件自带资源，需用 `<img>` 或 CSS `mask` 渲染
 *   （**不能**塞进 `<use href>`：插件 SVG 是填充式图形，宿主 sprite 是描边式，
 *   两者几何与着色方式都不同）；
 * - `{ kind: 'missing', name }`：未知宿主图标名 / 非法资源路径 → 占位图标。
 *
 * @param {string} value `entries[].icon` 或 `api.ui.icon()` 的取值。
 * @param {object} [options]
 * @param {string} [options.pluginId] 资源路径必需。
 */
export function resolveIcon(value, options = {}) {
  const text = String(value || "").trim();
  if (!text) return { kind: "missing", name: "" };

  if (isHostIconName(text)) {
    const href = resolveIconUrl(text);
    return href ? { kind: "host", href, name: canonicalIconName(text) }
      : { kind: "missing", name: text };
  }

  const url = resolvePluginIcon(text, options.pluginId);
  return url ? { kind: "asset", url, name: text } : { kind: "missing", name: text };
}

/**
 * 解析出 `<use href>` 的值；未知名字返回空串。
 *
 * 只处理宿主图标名。插件自带资源请用 `resolvePluginIcon()` / `resolveIcon()`
 * ——含 `/` 或 `.` 的取值在这里一律返回空串（它们不是 sprite 引用）。
 */
export function resolveIconUrl(value) {
  const sprite = spriteForIcon(value);
  if (!sprite) return "";
  return `${STATIC_ICON_BASE}/${sprite}#icon-${canonicalIconName(value)}`;
}

/** 图标名是否存在。 */
export function hasHostIcon(value) {
  return Boolean(spriteForIcon(value));
}

/** 全部宿主图标名（按字母序），供插件作者与设置页查询。 */
export function listHostIconNames() {
  return Object.keys(ICON_SPRITE_MAP).sort();
}

export { HOST_ICON_COUNT, ICON_ALIASES, ICON_SPRITE_MAP };
